#!/usr/bin/env python3
"""Read the provider balance, and refuse to keep spending when it cannot cover the ceiling.

WHY. The wake spend ceiling was 70.00 USD per day while the account held 49.10 (measured 2026-09-30 by
querying the provider with the credentials the shifts themselves use). A ceiling larger than the balance is
not a ceiling: a runaway day can spend past the money and then die mid-work with shifts in flight and no
warning, which is the worst possible moment to stop. This tool makes the guard bind.

WHAT IT DOES
  (no flag)   print the balance, the runway-aware ceiling and the tier, and exit 0
  --guard     THE RUNWAY-AWARE CONTROL, replacing the two fixed thresholds that were here before:
              --warn  (default 75.00) is a WARNING: raise the owner question and pause NOTHING. It now
                      also IS the tier boundary, because configured_max (25.00) x runway_days (3.0)
                      = 75.00: above it the runway cap cannot bind, so above it there is nothing to
                      conserve. One number, two meanings.
              THE CAP is `clamp(balance / runway_days, min_daily, configured_max)`, and never more
              than the balance. It is written to ~/.sms-inbox/wake-budget.json on every run, and
              THAT FILE is the single source every other reader uses - see wake_budget.py.
              THE HARD STOP is only where spending would go past the money: the pause file is written
              when the balance is below `min_daily x runway_days` (0.75), the point at which a day's
              minimum does not exist. It is NOT written at 10.00 any more.
              --floor is now an OVERRIDE of that stop line, defaulting to the derived 0.75 rather
                      than to 10.00, and --hysteresis defaults to 0.0. THE ONE-WAY DOOR IS GONE: the
                      guard resumes as soon as the same arithmetic yields a non-stop tier, which is
                      the same balance that stopped it. There is no band between the trigger and the
                      resume in which the system needs a human. A pause an operator set (a non-empty
                      file whose body is not this guard's) is still never touched.
  --json      machine-readable

DEFECT 2, FIXED HERE. The pause file is now written ATOMICALLY (`wake_budget.atomic_write`: temp file
in the same directory + os.replace), and ownership no longer depends on the body surviving a crash.
On 2026-10-14T22:41:02Z `open(PAUSE, "w")` truncated the file and then died with ENOSPC, leaving it
0 bytes; the old resume test required `body.startswith("low-balance")`, so the guard could not
recognise - or clear - its own pause at ANY balance. An empty pause file is now recognised as this
guard's own (nothing else in the estate writes an empty one: `wake.py pause` writes a body, and
`deploy.sh --apply` writes a body) and is repaired in place before the resume test runs.

WHY THERE IS NO AUTO-RECHARGE IN THIS FILE. The owner asked for it on 2026-10-05 and could not find it,
because it does not exist to find: the provider's own API FAQ documents top-up by PayPal, bank card,
Alipay or WeChat Pay on https://platform.deepseek.com/top_up and nothing automatic, and the account is a
prepaid balance with no stored payment method. So "set it and forget it" has to be built here, and this
guard is where it is built: ask EARLY, carry the link and the number, and make the answer one tap
instead of a hunt through a console.

It never prints a credential. It reads ~/.dsh/.credentials.yaml, finds the first key, and uses it; the key
never leaves the process.

FAILS SOFT ON PURPOSE. If the provider cannot be reached, the tool says so and CHANGES NOTHING - a network
blip must not pause the company, and a guard that cannot read the balance must not pretend the balance is
fine either. It reports unresolvable, and the caller decides.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

CRED = os.path.expanduser("~/.dsh/.credentials.yaml")
PAUSE = os.path.expanduser("~/.sms-inbox/WAKE_PAUSED")
PAUSE_GUARD = PAUSE + ".guard"      # the ownership sidecar, written before the pause itself
MARK = "low-balance"
ENDPOINT = "https://api.deepseek.com/user/balance"

# wake_budget.py is the ONE place the ceiling arithmetic lives; importing it here is what stops
# this file's `ceiling()` and wake-value.py's from drifting apart again.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import wake_budget
except Exception as _exc:          # noqa: BLE001 - a guard that cannot compute must still guard
    wake_budget = None
    BUDGET_IMPORT_ERROR = "%s: %s" % (type(_exc).__name__, _exc)
else:
    BUDGET_IMPORT_ERROR = None


def pause_body(bal, cap, tier, at):
    return json.dumps({"guard": "wake-balance", "marker": MARK, "schema": "wake-pause/1",
                       "balance": bal, "cap": cap, "tier": tier, "at": at}, sort_keys=True) + "\n"


def pause_is_ours(body, sidecar_exists):
    """Is this pause file OURS to clear? Never raises; a wrong 'no' is a stranded company.

    Order matters, and the empty case is the defect this exists to close:
      1. an EMPTY body is ours. No other writer in the estate produces one - `wake.py pause`
         (wake.py:1757) and `deploy.sh --apply` (deploy.sh:324) both write a body - and the only
         way to get an empty one is our own interrupted `open(..., "w")`, which is exactly what
         happened at 2026-10-14T22:41:02Z. Treating it as "an operator's" was the one-way door.
      2. the legacy marker `low-balance` at the start is ours (every pre-2026-10-14 pause).
      3. our JSON schema is ours.
      4. the body is unreadable but our sidecar exists: ours, and it gets repaired.
      5. anything else is an OPERATOR's and is never touched.
    """
    if body is None:
        return bool(sidecar_exists)
    if body == "":
        return True
    if body.startswith(MARK):
        return True
    try:
        doc = json.loads(body)
        if isinstance(doc, dict) and str(doc.get("guard")) == "wake-balance":
            return True
    except Exception:
        pass
    return bool(sidecar_exists)


def read_pause():
    try:
        return open(PAUSE, encoding="utf-8", errors="ignore").read()
    except Exception:
        return "" if os.path.exists(PAUSE) else None



def read_key():
    try:
        txt = open(CRED, encoding="utf-8", errors="ignore").read()
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    keys = re.findall(r"(sk-[A-Za-z0-9_\-]{8,})", txt)
    if not keys:
        return None, "no key matching sk- in %s" % CRED
    return keys[0], None


def balance():
    key, err = read_key()
    if key is None:
        return None, err
    try:
        req = urllib.request.Request(ENDPOINT, headers={"Authorization": "Bearer " + key})
        doc = json.load(urllib.request.urlopen(req, timeout=25))
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, str(exc)[:140])
    infos = doc.get("balance_infos") or []
    if not infos:
        return None, "provider returned no balance_infos"
    try:
        return float(infos[0].get("total_balance")), None
    except Exception as exc:
        return None, "unparseable balance: %s" % exc


def ceiling(bal=None):
    """The USD ceiling in force - SINGLE-SOURCED (defect 3).

    This used to resolve `WAKE_MAX_USD_PER_DAY` / `wake.DEFAULT_MAX_USD_PER_DAY` itself, which is
    exactly how one concept came to live in three files (`wake-balance.py`, `wake-value.py`, the
    fanout crontab) that could not see each other and all said 25.00 against a 5.70 balance. It now
    defers to wake_budget.py, the one implementation, and returns None only when even that is
    unavailable: printing a ceiling the guard cannot compute would be a lie, not a default.
    """
    if wake_budget is None:
        return None
    if bal is None:
        # No balance this run: report what the budget file last recorded, else the absolute.
        return wake_budget.read_cap(fallback=wake_budget.configured_max())
    return wake_budget.cap_for_balance(bal)["cap"]


TOPUP_URL = "https://platform.deepseek.com/top_up"
WARNED = os.path.expanduser("~/.sms-inbox/BALANCE_WARNED")


def _run_add(q, args, allow_duplicate):
    """One `owner-queue.py add`, with the duplicate override off unless asked for."""
    env = dict(os.environ)
    env["OWNER_QUEUE_ALLOW_DUPLICATE"] = "1" if allow_duplicate else "0"
    p = subprocess.run(
        [sys.executable or "python3", q] + args,
        capture_output=True, text=True, timeout=60, env=env,
    )
    txt = ((p.stdout or "") + (p.stderr or "")).strip().replace("\n", " ")
    return p.returncode, txt


def warned_recently(state, repeat_hours):
    """Have we already raised THIS state inside the repeat window?

    The queue's own duplicate check refuses a question similar to an already
    answered one -- correct for everyone else, and useless for a running guard:
    once the owner answers "I will top it up", the question is resolved and the
    next depleted balance would be refused as a duplicate and reach nobody. So
    the guard limits ITSELF, on a marker, and a real recurrence still gets
    through. Twelve hours by default: long enough that a slow top-up does not
    nag him hourly, short enough that a forgotten one comes back.
    """
    if repeat_hours <= 0:
        return False
    try:
        doc = json.loads(open(WARNED, encoding="utf-8").read())
        if str(doc.get("state")) != str(state):
            return False
        return (time.time() - float(doc.get("ts") or 0)) < (repeat_hours * 3600.0)
    except Exception:
        return False


def mark_warned(state, bal):
    try:
        with open(WARNED, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"state": state, "balance": bal, "ts": time.time(),
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    except Exception:
        pass


def escalate(bal, floor, cap, state="paused", warn=None, repeat_hours=12.0, resume_at=None):
    """Tell the OWNER, once, in ONE row, whether the work is merely threatened or already stopped.

    A PAUSE FILE IS NOT A MESSAGE. Measured 2026-10-02 19:41Z: the balance crossed the floor, the
    guard wrote ~/.sms-inbox/WAKE_PAUSED and the whole trigger system stopped releasing sessions --
    and NOTHING told the owner. Every other guard in this system ends in a worker or a question
    (sources/README.md), and a guard whose only output is a file nobody opens is the exact defect
    this estate has been burned by (`P167`, `P2819`). The sanctioned channel for "only he can
    decide" is the owner queue, so this raises ONE row there and owner-ask texts it to him.

    The QUESTION TEXT carries no numbers on purpose: owner-queue.py dedupes on it, and an amount in
    the text would mint a new row every time the balance moved. The figures live in the
    recommendation and the context, which are rewritten in place by the next escalation. The warning
    and the stop deliberately share ONE question text so they cannot turn into two rows about one
    depleted account -- the row just gets sharper as the state gets worse.

    The LINK is in the recommendation because the provider has no auto-recharge to switch on: the
    only lever the owner has is a top-up page, and making him find it again is what he complained
    about on 2026-10-05.

    Never raises: a guard that cannot escalate must still guard.
    """
    q = os.path.expanduser("~/bin/owner-queue.py")
    if not os.path.exists(q):
        return "not escalated: no owner queue at %s" % q
    question = ("The prepaid AI balance is low. Top it up so the autonomous work does not stop?")
    if state == "paused":
        # The resume line is reported as the SAME number that stopped it (hysteresis is 0 on
        # purpose). The old text promised a resume five dollars ABOVE the stop line - the
        # one-way door, described to the owner as a courtesy that did not exist.
        outcome = ("Every release is paused right now and it resumes by itself once the balance "
                   "passes %.2f - no other action is needed."
                   % (floor if resume_at is None else resume_at,))
        options = "I will top it up now|Leave it paused for now|Stop asking about this"
        severity = "high"
    else:
        outcome = ("Work is still running. This is the early warning, raised while the balance can still "
                   "be topped up calmly; it stops by itself only if the balance falls to %.2f." % (floor,))
        options = "I will top it up now|Top up a larger amount so it lasts|Stop asking about this"
        severity = "medium"
    rec = ("Top up at %s - the provider has NO auto-recharge to turn on (its own API FAQ documents "
           "PayPal, bank card, Alipay and WeChat Pay and nothing automatic), so this cannot be made to "
           "run itself. Balance %.2f; warning threshold %s; stop threshold %.2f. %s"
           % (TOPUP_URL, bal, "off" if warn is None else "%.2f" % warn, floor, outcome))
    if warned_recently(state, repeat_hours):
        return "skipped: this %s state was already escalated inside %.0f h" % (state, repeat_hours)
    context = ("Measured by ~/bin/wake-balance.py at %s: balance %.2f, ceiling/day %s, "
               "warning %s, stop line %.2f, state=%s. The pause file is %s. Nothing autonomous "
               "runs while a pause stands: sources may still file work, but no session is "
               "released to do it. Measured burn while work is actually running: 1.86 to 2.70 "
               "per hour (wake-balance.log, 2026-10-13/14), so the ceiling is now derived as "
               "balance / 3 days and can always bind."
               % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), bal,
                  "unknown" if cap is None else "%.2f" % cap,
                  "off" if warn is None else "%.2f" % warn, floor, state, PAUSE))
    args = ["add",
            "--question", question,
            "--recommendation", rec,
            "--options", options,
            "--context", context,
            "--blocks", "every autonomous session (the whole wake trigger system)",
            "--severity", severity,
            "--source", "wake-balance"]
    try:
        rc, txt = _run_add(q, args, allow_duplicate=False)
        if rc != 0 and "already exists" in txt and "(resolved" in txt:
            # THE RECURRENCE CASE, and the reason the override exists. The queue refuses a
            # question similar to one already ANSWERED, which is right for a caller that
            # would otherwise re-ask a settled thing. A depleted account is not settled: the
            # owner tops it up, it empties again, and the second depletion must reach him.
            # Scoped narrowly -- only when the queue itself says the prior row is resolved,
            # and only after the guard's own marker has let this state through again.
            rc, txt = _run_add(q, args, allow_duplicate=True)
            txt = "re-filed over a resolved row: " + txt
        if rc == 0:
            mark_warned(state, bal)
            return "escalated: %s" % (txt[:200] or "rc=0")
        return "escalation did not land: %s" % (txt[:200] or "rc=%s" % rc)
    except Exception as exc:  # noqa: BLE001 -- never break the guard
        return "escalation FAILED: %s" % exc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", action="store_true")
    ap.add_argument("--warn", type=float, default=75.0,
                    help="raise the owner question below this balance, and pause NOTHING. It is also "
                         "the tier boundary, because configured_max x runway_days = 75.00 "
                         "(default 75.0; use 0 to switch the early warning off)")
    ap.add_argument("--floor", type=float, default=None,
                    help="OVERRIDE the hard-stop balance. Default: the derived min_daily x "
                         "runway_days (currently 0.75). This used to default to 10.00, which is "
                         "what created the one-way door at 10.00/15.00.")
    ap.add_argument("--hysteresis", type=float, default=0.0,
                    help="extra balance required before auto-resume. Default 0.0 ON PURPOSE: the "
                         "rate control, not the stop, is the instrument for a low balance, so the "
                         "stop must have no band in which the company needs a human.")
    ap.add_argument("--repeat-hours", type=float, default=12.0,
                    help="do not raise the same state at the owner again inside this many hours "
                         "(default 12.0; use 0 to never repeat-limit)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    warn = a.warn if a.warn and a.warn > 0 else None

    bal, err = balance()

    # --- the runway-aware control -------------------------------------------------
    if wake_budget is None:
        budget = {"tier": "unresolvable", "cap": None, "max_per_day": 0,
                  "why": "wake_budget.py could not be imported (%s)" % BUDGET_IMPORT_ERROR}
    else:
        budget = wake_budget.cap_for_balance(bal)
    cap = budget.get("cap")
    tier = budget.get("tier")
    stop_below = a.floor if a.floor is not None else budget.get("stop_below")
    # --floor is an override of the STOP LINE, not of the ceiling. Re-derive the tier against it so
    # an operator who moves the line moves the resume line with it and cannot re-open the door.
    if a.floor is not None and bal is not None:
        tier = "stop" if bal < a.floor else ("ok" if cap is not None and
                                             cap >= (budget.get("configured_max") or 0) else "conserve")

    if bal is None:
        state = "unresolvable"
    elif tier == "stop":
        state = "stop"
    elif warn is not None and bal < warn:
        state = "warn"
    else:
        state = "ok"
    out = {"ok": bal is not None, "balance": bal, "ceiling": cap, "tier": tier,
           "floor": stop_below, "warn": warn, "state": state, "error": err, "budget": budget,
           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    if a.guard:
        if bal is None:
            out["action"] = "none (balance unreadable - changing nothing)"
        elif tier == "stop":
            # THE ONLY HARD STOP, written atomically, sidecar first. But NEVER over an OPERATOR's
            # pause: if he has already stopped the fleet, this guard may not (a) destroy his record
            # of why, nor (b) make the file its own so that a later balance recovery deletes HIS
            # pause. Measured by test_operator_pause_is_never_touched, which failed before this.
            existing = read_pause() if os.path.exists(PAUSE) else None
            if existing is not None and not pause_is_ours(existing, os.path.exists(PAUSE_GUARD)):
                out["action"] = ("left alone: already stopped at balance %.2f and the pause is an "
                                 "operator's - not writing over it" % bal)
            elif wake_budget is not None:
                try:
                    wake_budget.atomic_write(PAUSE_GUARD, json.dumps(
                        {"guard": "wake-balance", "schema": "wake-pause/1", "at": out["at"]}) + "\n")
                except OSError as exc:
                    out["guard_note"] = "ownership sidecar not written: %s" % exc
                wake_budget.atomic_write(PAUSE, pause_body(bal, cap, tier, out["at"]))
                out["action"] = "STOPPED below %s (balance %.2f; no day's minimum is affordable)" % (
                    "%.2f" % stop_below if stop_below is not None else "the stop line", bal)
            else:
                out["action"] = "STOP-worthy but wake_budget.py is unavailable: refusing to write"
            out["escalated"] = escalate(bal, stop_below or 0.0, cap, state="paused", warn=warn,
                                        repeat_hours=a.repeat_hours)
        elif os.path.exists(PAUSE):
            body = read_pause()
            ours = pause_is_ours(body, os.path.exists(PAUSE_GUARD))
            if not ours:
                out["action"] = "pause file left alone (an operator's, not this guard's)"
            else:
                # REPAIR FIRST. An empty or truncated body is repaired in place, so the record of
                # WHY the fleet stopped is never lost even though the write that created it died.
                if wake_budget is not None and (not body or not body.startswith("{")):
                    try:
                        wake_budget.atomic_write(PAUSE, pause_body(bal, cap, tier, out["at"]))
                        out["repaired"] = "the pause body was empty/legacy and has been rewritten"
                    except OSError as exc:
                        out["repaired"] = "repair failed: %s" % exc
                    out["adopted"] = ("an empty pause file is this guard's own interrupted write: "
                                      "no other writer in the estate produces one")
                if bal >= ((stop_below or 0.0) + a.hysteresis):
                    try:
                        if os.path.exists(PAUSE_GUARD):
                            os.remove(PAUSE_GUARD)
                        os.remove(PAUSE)
                        out["action"] = ("RESUMED - balance %.2f is at or above the stop line %s "
                                         "(hysteresis %.2f); cap %.4f/day, %s releases/day, tier %s"
                                         % (bal, "%.2f" % stop_below if stop_below is not None else "?",
                                            a.hysteresis, cap or 0.0,
                                            budget.get("max_per_day"), tier))
                    except OSError as exc:
                        out["action"] = "resume FAILED: %s" % exc
                else:
                    out["action"] = ("pause held: balance %.2f is below the stop line %s" %
                                     (bal, "%.2f" % stop_below if stop_below is not None else "?"))
                    out["escalated"] = escalate(bal, stop_below or 0.0, cap, state="paused", warn=warn,
                                                repeat_hours=a.repeat_hours)

        # THE EARLY WARNING, AND IT IS DELIBERATELY NOT A PAUSE. Measured 2026-10-02: the guard's
        # only signal arrived when work had already stopped, and the owner learned about a depleted
        # account 53 hours late. This branch speaks while the balance is still spendable.
        if bal is not None and not os.path.exists(PAUSE):
            if warn is not None and bal < warn:
                out["action"] = "%s; raised the early warning below %.2f (not paused)%s" % (
                    out.get("action") or "none", warn,
                    "" if tier == "ok" else "; tier %s: cap %.2f/day, %s releases/day" % (
                        tier, cap or 0.0, budget.get("max_per_day")))
                out["escalated"] = escalate(bal, stop_below or 0.0, cap, state="warn", warn=warn,
                                            repeat_hours=a.repeat_hours)
            elif not out.get("action"):
                out["action"] = "none (balance healthy)"

    # PUBLISH THE BUDGET. Every other reader - wake-value.py, wake-budget-env.sh (the crontab),
    # wake-fanout.sh - takes the number from this one file, which is what stops the three copies
    # of "the ceiling" from diverging again. Written after the guard has acted so the file always
    # describes the state the guard just enforced.
    if bal is not None and wake_budget is not None:
        try:
            payload = dict(budget)
            payload["ts"] = time.time()
            payload["balance"] = bal
            payload["max_usd_per_day"] = cap
            payload["tier"] = tier
            payload["lane"] = wake_budget.lane_for(tier)
            payload["paused"] = bool(os.path.exists(PAUSE))
            payload["pause_is_ours"] = bool(os.path.exists(PAUSE) and pause_is_ours(
                read_pause(), os.path.exists(PAUSE_GUARD)))
            wake_budget.write_budget(payload)
            out["budget_file"] = wake_budget.BUDGET
        except OSError as exc:
            out["budget_file_error"] = str(exc)

    if a.json:
        print(json.dumps(out))
    else:
        print("balance %s | ceiling/day %s | warn %s | floor %s | %s%s"
              % ("unreadable" if bal is None else ("%.2f" % bal),
                 "unknown" if cap is None else ("%.2f" % cap),
                 "off" if warn is None else ("%.2f" % warn),
                 "%.2f" % (stop_below if stop_below is not None else 0.0), state,
                 "" if not out.get("action") else " | " + out["action"]))
        if tier:
            print("tier %s | cap %.4f/day (%s releases/day) | runway_days %s | stop below %s"
                  % (tier, cap or 0.0, budget.get("max_per_day"),
                     budget.get("runway_days"), budget.get("stop_below")))
            print("why: %s" % budget.get("why"))
        if bal is not None and cap is not None and cap > bal:
            # Kept, and it must now be unreachable: cap <= balance is the invariant. If this ever
            # prints, the arithmetic is wrong and the guard says so instead of hiding it.
            print("WARNING: the daily ceiling (%.2f) is larger than the balance (%.2f) - it cannot bind."
                  % (cap, bal))
    return 0


if __name__ == "__main__":
    sys.exit(main())
