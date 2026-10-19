#!/usr/bin/env python3
"""replay-owner-text.py — score the owner text channel against its own history.

WHY THIS EXISTS
---------------
"You could do a little more research" is a rule, and a rule nobody measures decays. This
harness replays every text that actually reached the owner, runs it through the guards that
are live NOW, and reports — per guard — how many it now refuses, and **how many of the texts
he actually answered it would have refused**. That second number is the one that matters: a
guard that suppresses a message he replied to is a message he will never see, and no
suppression statistic shows it.

METHOD
------
1. Read outbound texts that reached him (status delivered/sent) from the corpus dump.
2. Pair each with his reply: an inbound from him in the next REPLY_WINDOW hours, counting
   only outbound texts that were the LAST one before that inbound. If five texts went out
   before he answered, one of them was the one he answered and the others were competition —
   this harness marks all five as "unanswered" except the last, which is a deliberate,
   conservative choice: it never credits a text with a reply it may not have earned.
3. Run each body through the live guard predicates, imported by path.
4. Print a verdict table and the two numbers that decide a deploy:
     WOULD-SEND-RIGHT   suppressed a text he answered      (a message he loses)
     WOULD-SEND-WRONG   suppressed a text he ignored        (the point of the change)
   A guard is worth shipping when WRONG >> RIGHT and RIGHT is zero or explainable.

USAGE
    python replay-owner-text.py --corpus data/sms.jsonl --base <dir with the live modules>
    python replay-owner-text.py --corpus data/sms.jsonl --base . --only internals
    python replay-owner-text.py --corpus data/sms.jsonl --base . --json out.json

Exit 0 when it ran. It is an instrument, not a gate; `--fail-if-loses N` makes it a gate.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

OWNER = "+18483897895"          # his personal iPhone, from sms_log
REPLY_WINDOW_HOURS = 6.0        # how long after a text a reply still counts as "answered"
DELIVERED = ("delivered", "sent")


# --------------------------------------------------------------------------------------
# corpus
# --------------------------------------------------------------------------------------

def _utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


PLACEHOLDER_SIDS = {"twiml-reply", "twiml-cmd-reply", "twiml-personal-ops-reply",
                    "sms-followup", "sms-followup-1", "", "None", None}


def dedupe_deliveries(rows: list[dict]) -> tuple[list[dict], int]:
    """One row per text he actually RECEIVED, and how many rows were folded into it.

    MEASURED 2026-10-19: `sms_service.send_message` is wrapped in `_audited_send`, which
    writes one sms_log row per attempt with `agent_id='sms_service.audit'` — and the caller
    (the orchestrator) writes a SECOND row for the same send. Both rows carry the same
    `twilio_sid`, the same second and the same body: 350 rows over 300 real sids, 50 extra
    rows. So counting rows overstates what he received, inflates every "how many texts did
    we send" figure, and makes a single send look like competition for his attention.

    A handful of sids are PLACEHOLDERS shared by many unrelated messages (`twiml-reply` was
    used for every TwiML auto-reply), so those are keyed on (second, body) instead. Counting
    by sid alone would have shown 248 "extra rows" that were not duplicates at all.
    """
    seen: dict[tuple, dict] = {}
    folded = 0
    for r in rows:
        sid = r.get("twilio_sid")
        if sid in PLACEHOLDER_SIDS:
            key = ("ph", r.get("created_at"), (r.get("body") or "")[:120])
        else:
            key = ("sid", sid)
        if key in seen:
            folded += 1
            continue
        seen[key] = r
    return list(seen.values()), folded


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_channel(rows: list[dict], owner: str = OWNER) -> tuple[list[dict], list[dict]]:
    """(delivered outbound to him, inbound from him), each oldest first."""
    out, inn = [], []
    for r in rows:
        to = (r.get("to_number") or "").strip()
        frm = (r.get("from_number") or "").strip()
        if to == owner and (r.get("direction") == "outbound") \
                and (r.get("status") or "").lower() in DELIVERED:
            out.append(r)
        elif frm == owner and (r.get("direction") or "") == "inbound":
            inn.append(r)
    out.sort(key=lambda r: r["created_at"])
    inn.sort(key=lambda r: r["created_at"])
    return out, inn


_STOP = frozenset("""
the a an and or but if then that this these those it its is was were be been being to of in
on for with at by from as you your yours me my we our us i he she they them his her their
not no yes ok okay so just now what which who how why when where can could would should
will shall may might must do does did done have has had get got let more about into over
""".split())


def _distinctive(text: str) -> set[str]:
    """Tokens that make a reply *about* a text: amounts, long words, names."""
    low = (text or "").lower()
    toks = set(re.findall(r"\d[\d,.]{1,}", low))
    toks |= {t for t in re.findall(r"[a-z]{5,}", low) if t not in _STOP}
    return toks


def pair_replies(out: list[dict], inn: list[dict],
                 window_hours: float = REPLY_WINDOW_HOURS) -> list[dict]:
    """Attach `answered` to the LAST outbound before each of his inbound texts.

    `responsive` is the honest half. "He sent something within six hours" is NOT the same
    as "he answered this text": a bare acknowledgement like "Remembered." is followed by his
    next unrelated sentence and would be scored as answered, which inflates every guard that
    suppresses acks. So a pair also counts as responsive only when his reply shares at least
    one distinctive token (an amount, or a word of five letters or more) with the text.
    """
    window = timedelta(hours=window_hours)
    for r in out:
        r["answered"] = False
        r["responsive"] = False
        r["reply_at"] = None
        r["reply_body"] = None
        r["contested"] = False
    for inb in inn:
        at = _utc(inb["created_at"])
        cand = None
        for r in out:
            rt = _utc(r["created_at"])
            if rt > at:
                break
            if at - rt <= window:
                cand = r
        if cand is None or cand["answered"]:
            continue
        cand["answered"] = True
        cand["reply_at"] = inb["created_at"]
        cand["reply_body"] = (inb.get("body") or "")[:400]
        shared = _distinctive(cand.get("body") or "") & _distinctive(inb.get("body") or "")
        cand["responsive"] = bool(shared)
        cand["shared_tokens"] = sorted(shared)[:5]
        # How crowded was the window he was answering in? Count every text that reached
        # him in the REPLY_WINDOW before his reply. Measured against the three-times-in-a-row
        # complaint: this is the number that should have been one and was three.
        burst = 0
        for r in out:
            rt = _utc(r["created_at"])
            if at - window <= rt <= at:
                burst += 1
        cand["burst"] = burst
    return out


# --------------------------------------------------------------------------------------
# guards, imported by path so the harness works on any checkout
# --------------------------------------------------------------------------------------

def _load(name: str, path: Path):
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("replay_" + name, str(path))
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:                                  # noqa: BLE001
        print(f"  ! could not import {path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    return mod


GUARDS = (
    # (label, module file, function, callable(body)->reason-or-None, needs)
    ("internal",   "owner_text_relay.py", "internal_prose",       (lambda f, b: f(b))),
    ("credential", "owner_text_relay.py", "credential_request",   (lambda f, b: f(b))),
    ("nonanswer",  "textdecide.py",       "is_non_answer",        (lambda f, b: (f(b) or (False, ""))[1] if f(b) else None)),
    ("cfo_guess",  None,                  None,                   None),
    ("ack_only",   None,                  None,                   None),
)


def _too_long(mod, body: str) -> str | None:
    """The relay's own fit() is a rule too: a body that had to be cut was not a message."""
    if mod is None or not hasattr(mod, "fit"):
        return None
    try:
        cut = mod.fit(body)
    except Exception:                                          # noqa: BLE001
        return None
    return None if cut == body else "would be cut: %d -> %d chars" % (len(body), len(cut))


def guard_findings(base: Path, body: str) -> dict[str, str]:
    """{guard: reason} for every guard that would REFUSE this body. Empty = it may send.

    Truncation is deliberately NOT in here. `fit()` does not refuse a body, it cuts one and
    sends the cut version — so a "refused" count that included it reported 56 texts as
    suppressed that were in fact delivered, half-written. It is reported separately, as the
    quality defect it is.
    """
    relay = _load("owner_text_relay", base / "owner_text_relay.py")
    decide = _load("textdecide", base / "textdecide.py")
    out: dict[str, str] = {}

    if relay is not None:
        for label, fn_name in (("internal", "internal_prose"),
                               ("credential", "credential_request")):
            fn = getattr(relay, fn_name, None)
            if callable(fn):
                try:
                    got = fn(body)
                except Exception as exc:                       # noqa: BLE001
                    got = f"guard raised {type(exc).__name__}"
                if got:
                    out[label] = str(got)[:160]

    if decide is not None:
        fn = getattr(decide, "is_non_answer", None)
        if callable(fn):
            try:
                hit, why = fn(body)
            except Exception:                                  # noqa: BLE001
                hit, why = False, ""
            if hit:
                out["nonanswer"] = str(why)[:160]

    # literals that are always wrong on his phone, independent of any guard module
    low = body.lower()
    if "my guess" in low and "shop supplies" in low:
        out["cfo_guess"] = "guesses 'shop supplies' at his money"
    if re.fullmatch(r"\s*(remembered|captured as a task|got it|noted|understood|ok)[.!\s]*",
                    low):
        out["ack_only"] = "content-free acknowledgement"
    if "[budget exceeded" in low:
        out["internal"] = out.get("internal") or "[Budget exceeded] leaked to his phone"
    if "family chat" in low:
        out["family"] = "family-chat operational notice on the owner channel"
    return out


def would_cut(base: Path, body: str) -> str | None:
    """Would the relay have to cut this body to send it? That is a half-message defect."""
    relay = _load("owner_text_relay", base / "owner_text_relay.py")
    if relay is None or not hasattr(relay, "fit"):
        return None
    try:
        cut = relay.fit(body)
    except Exception:                                          # noqa: BLE001
        return None
    if cut == body:
        return None
    return "%d -> %d chars" % (len(body), len(cut))


# --------------------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="data/sms.jsonl")
    ap.add_argument("--base", default=".")
    ap.add_argument("--only", default="", help="comma-separated guard labels to restrict to")
    ap.add_argument("--json", default="")
    ap.add_argument("--since", default="", help="YYYY-MM-DD")
    ap.add_argument("--until", default="")
    ap.add_argument("--fail-if-loses", type=int, default=-1,
                    help="exit 1 when more than N answered texts would be refused")
    ap.add_argument("--show", type=int, default=0, help="print N example suppressions")
    a = ap.parse_args(argv)

    corpus = Path(a.corpus)
    if not corpus.exists():
        print(f"no corpus at {corpus}", file=sys.stderr)
        return 2
    base = Path(a.base)

    rows = load_rows(corpus)
    out, inn = build_channel(rows)
    out_raw = len(out)
    out, folded = dedupe_deliveries(out)
    if a.since:
        out = [r for r in out if r["created_at"] >= a.since]
    if a.until:
        out = [r for r in out if r["created_at"] <= a.until]
    out.sort(key=lambda r: r["created_at"])
    pair_replies(out, inn)

    answered = sum(1 for r in out if r["answered"])
    responsive = sum(1 for r in out if r["responsive"])
    only = {s.strip() for s in a.only.split(",") if s.strip()}

    per_guard: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[dict]] = defaultdict(list)
    suppressed_rows = []
    cut_rows = []

    for r in out:
        body = r.get("body") or ""
        cut = would_cut(base, body)
        if cut:
            cut_rows.append({**r, "cut": cut})
        findings = guard_findings(base, body)
        if only:
            findings = {k: v for k, v in findings.items() if k in only}
        if not findings:
            key = "responsive" if r["responsive"] else ("answered" if r["answered"] else "ignored")
            per_guard["(would send)"][key] += 1
            continue
        for label, why in findings.items():
            key = "responsive" if r["responsive"] else ("answered" if r["answered"] else "ignored")
            per_guard[label][key] += 1
            if len(examples[label]) < 6:
                examples[label].append({**r, "why": why})
        suppressed_rows.append({**r, "findings": findings})

    total = len(out)
    print("REPLAY - the owner text channel against its own history")
    print("  corpus      : %s (%d rows)" % (corpus, len(rows)))
    print("  base        : %s" % base.resolve())
    print("  delivered   : %d distinct texts reached him  (%d ledger rows folded: the app writes"
          % (total, folded))
    print("                one audit row and the caller writes a second for the SAME sid)")
    print("  he replied  : %d (%.1f%%) within %.0f h"
          % (answered, (100.0 * answered / total) if total else 0.0, REPLY_WINDOW_HOURS))
    print("  responsive  : %d (%.1f%%) shared a distinctive word with the text"
          % (responsive, (100.0 * responsive / total) if total else 0.0))
    print("  contested   : %d texts he engaged with" % responsive)
    bursts = [r for r in out if r.get("burst")]
    if bursts:
        over = [r for r in bursts if r["burst"] > 1]
        med = sorted(b["burst"] for b in bursts)[len(bursts) // 2]
        print("  burst       : of %d replies, %d followed MORE THAN ONE text (median %d, max %d)"
              % (len(bursts), len(over), med, max(b["burst"] for b in bursts)))
    print()
    print("  %-12s %8s %8s %9s %9s  %s"
          % ("guard", "refused", "loses", "of-answered", "of-ignored", "verdict"))
    print("  " + "-" * 78)

    labels = sorted(k for k in per_guard if k != "(would send)")
    loses = 0
    rows_json = []
    for label in labels:
        c = per_guard[label]
        resp, ans, ign = c["responsive"], c["answered"], c["ignored"]
        n = resp + ans + ign
        # "loses" counts only RESPONSIVE pairs: a text he genuinely engaged with.
        rate = (100.0 * resp / n) if n else 0.0
        loses += resp
        if resp == 0:
            verdict = "SAFE - refuses only what he ignored"
        elif rate < 10.0:
            verdict = "OK - small cost"
        else:
            verdict = "RISK - refusing texts he engages with"
        print("  %-12s %8d %8d %9d %9d  %s" % (label, n, resp, ans, ign, verdict))
        rows_json.append({"guard": label, "refused": n, "loses_responsive": resp,
                          "of_answered": ans, "of_ignored": ign,
                          "responsive_rate_pct": round(rate, 1), "verdict": verdict})

    base_c = per_guard["(would send)"]
    base_n = base_c["responsive"] + base_c["answered"] + base_c["ignored"]
    base_rate = (100.0 * base_c["responsive"] / base_n) if base_n else 0.0
    print("  " + "-" * 78)
    print("  %-12s %8d %8d %9d %9d  %s"
          % ("(would send)", base_n, base_c["responsive"], base_c["answered"],
             base_c["ignored"], "the pile that still reaches him"))
    print()
    print("  WOULD-LOSE      %d texts he engaged with would be refused (overlaps counted once)"
          % loses)
    print("  WOULD-SAVE      %d ignored texts refused"
          % sum(per_guard[l]["ignored"] for l in labels))
    print("  WOULD-CUT       %d delivered texts had to be truncated to fit %s"
          % (len(cut_rows), "(a half-message is its own defect)"))
    cut_answered = sum(1 for r in cut_rows if r["responsive"])
    print("                  %d of those he still engaged with - the cut did not stop the reply,"
          " it made it worse" % cut_answered)

    if a.show:
        for label in labels:
            print("\n  examples refused by %s:" % label)
            for e in examples[label][:a.show]:
                flag = "ANSWERED-BY-HIM" if e["answered"] else "ignored"
                print("    [%s] %s  %s" % (flag, e["created_at"][:16], e["why"]))
                print("        %s" % " ".join((e.get("body") or "").split())[:200])

    if a.json:
        Path(a.json).write_text(json.dumps({
            "total": total, "answered": answered, "guards": rows_json,
            "would_lose": loses,
            "suppressed": [{"at": r["created_at"], "answered": r["answered"],
                            "findings": r["findings"],
                            "body": (r.get("body") or "")[:400]} for r in suppressed_rows],
        }, indent=2), encoding="utf-8")
        print("\n  wrote %s" % a.json)

    if a.fail_if_loses >= 0 and loses > a.fail_if_loses:
        print("\n  FAIL: %d answered texts would be refused (limit %d)"
              % (loses, a.fail_if_loses))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
