#!/usr/bin/env bash
# autonomy-status - ONE read-only command that says what the autonomous system is doing.
#
# WHY THIS EXISTS. Driving this system tonight took roughly ninety throwaway probe scripts in /tmp, each
# one written to answer a slightly different question: is anything in flight, is the queue gated or stuck,
# what closed, what is the spend, is the reaper keeping up, did the last dispatch fail. Every one of those
# answered a real question and every one was then abandoned. The cost is not the typing - it is that the
# NEXT session, with no memory, has no way to ask any of it without writing them all again, and the owner
# has no way to ask at all.
#
# This is READ-ONLY by construction: no claim, no finish, no flag, no merge, no cron edit, no write to
# either store. It is safe to run at any time, by anyone, including from a cron monitor.
#
# Usage: autonomy-status [--json]
# Exit:  0 always. A status command that can fail is a status command that lies when it matters.

set -u
JSON=0
[ "${1:-}" = "--json" ] && JSON=1

WAKE_CLI=${WAKE_CLI:-/root/bin/wake.py}
WORK_CLI=${WORK_CLI:-/root/bin/work.py}
WORK_DB=${WORK_DB:-/root/work/work.db}
LOG=${WAKE_LOG:-/root/.sms-inbox/wake-dispatch.log}
FANOUT=${WAKE_FANOUT_LOG:-/root/.sms-inbox/wake-fanout.log}
SRC_HB=/root/.sms-inbox/sources-heartbeat
WAKE_HB=/root/.sms-inbox/wake-heartbeat

python3 - "$JSON" "$WAKE_CLI" "$WORK_CLI" "$WORK_DB" "$LOG" "$FANOUT" "$SRC_HB" "$WAKE_HB" <<'PY'
import json, os, re, subprocess, sqlite3, sys, time, datetime

as_json = sys.argv[1] == "1"
wake_cli, work_cli, work_db, log, fanout, src_hb, wake_hb = sys.argv[2:9]

out = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "ok": True, "problems": []}

def note_problem(msg):
    out["problems"].append(msg)

# --- the wake store's own numbers -------------------------------------------------------------
# THE CAP THE LOOP ENFORCES, NOT THE DEFAULT THIS SHELL CAN SEE. Measured 2026-10-13: the cron
# line that runs wake-fanout exports WAKE_MAX_PER_DAY=150 and WAKE_MAX_USD_PER_DAY=25, while
# this script is run by a human in a shell that carries neither - so wake.py reported its own
# defaults (500 / 25.0) and this reader printed "releases today : 150 of 500 backstop" with an
# empty caps-in-force line. The truth was that the release cap WAS reached and every release had
# been refused for 3h44m. wake-dispatch.sh now records the ceilings it actually gates on, and
# this reader prefers that record. A reading that cannot distinguish the enforced cap from the
# default is the exact failure both files exist to prevent.
CAPS_EFFECTIVE = os.path.expanduser("~/.sms-inbox/wake-caps-effective.json")
try:
    raw = subprocess.run(["python3", wake_cli, "stats", "--json"], capture_output=True,
                         text=True, timeout=120).stdout
    d = json.loads(raw or "{}")
    caps = d.get("caps") or {}
    eff = {}
    try:
        eff = json.loads(open(CAPS_EFFECTIVE, encoding="utf-8").read() or "{}")
    except Exception:
        eff = {}
    eff_caps = eff.get("caps") or {}
    out["wake"] = {
        "released_today": d.get("released_today"),
        "failed_today": d.get("failed_today"),
        "backstop": caps.get("max_per_day"),
        "spend_today_usd": d.get("spend_today_usd"),
        "spend_ceiling_usd": caps.get("max_usd_per_day"),
        "states": {k: v for k, v in (d.get("states") or {}).items() if v},
        "caps_in_force": d.get("caps_in_force") or [],
        "paused": caps.get("paused"),
        "effective_max_per_day": eff_caps.get("max_per_day"),
        "effective_max_usd_per_day": eff_caps.get("max_usd_per_day"),
        "effective_caps_at": eff.get("at"),
        "effective_caps_source": eff.get("written_by"),
        "effective_caps_force": eff.get("caps_in_force") or [],
    }
    if caps.get("paused"):
        note_problem("the wake system is PAUSED (pause file present)")
    # A REACHED CAP IS NOT A PROBLEM, so it is NOT reported as one. It is a guard working, and
    # the estate's own rule is that "IDLE: healthy - N row(s) waiting, every one gated by <cap>"
    # is the single most useful reading there is; putting a working guard in the PROBLEMS list is
    # how a PROBLEMS list stops being read. It is said in three other places instead: the
    # releases line names the ENFORCED cap, the `caps in force` line names the reached one, and
    # the IDLE line says GATED with the reason. What was missing on 2026-10-13 was not a warning
    # - it was that this reader showed the DEFAULT and an empty caps list while the loop was
    # refusing every release for 3h44m.
except Exception as exc:
    out["wake"] = {"error": "%s: %s" % (type(exc).__name__, exc)}
    note_problem("could not read the wake store")

# --- the ledger -------------------------------------------------------------------------------
try:
    c = sqlite3.connect("file:%s?mode=ro" % work_db, uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    states = {r["state"]: r["n"] for r in
              c.execute("select state, count(*) as n from work_item group by 1")}
    by_pri = {str(r["priority"]): r["n"] for r in
              c.execute("select priority, count(*) as n from work_item where state='todo' group by 1")}
    per = [dict(r) for r in c.execute(
        "select project, sum(state='todo') as todo, sum(state='running') as run, "
        "sum(state='done') as done from work_item group by project order by todo desc")]
    attempts = c.execute("select count(*) from attempt").fetchone()[0]
    # COUNT ONLY SETTLED WORK. The ratio that matters is of attempts that REACHED a terminal state -
    # '11 of 13' understated it because one of the 13 is a claim still in progress, which carries no
    # proof by definition. An honest ratio must exclude work that is not finished.
    closed = c.execute("select count(*) from attempt where state_after is not null "
                       "and state_after <> ''").fetchone()[0]
    with_proof = c.execute("select count(*) from attempt where state_after is not null "
                           "and state_after <> '' and proof is not null and proof <> ''").fetchone()[0]
    open_attempts = c.execute("select count(*) from attempt where ended_at is null").fetchone()[0]
    running_missing_attempt = c.execute(
        "select count(*) from work_item w where w.state in ('running','done') "
        "and not exists (select 1 from attempt a where a.item=w.id)").fetchone()[0]
    orphans = c.execute(
        "select count(*) from attempt a left join work_item w on w.id=a.item where w.id is null").fetchone()[0]
    running_no_lease = c.execute(
        "select count(*) from work_item where state='running' and lease_until is null").fetchone()[0]
    expired_held = c.execute(
        "select count(*) from work_item where state='running' and lease_until < datetime('now')").fetchone()[0]
    done_no_proof = c.execute(
        "select count(*) from work_item w where w.state='done' and not exists ("
        "select 1 from attempt a where a.item=w.id and a.state_after='done' and a.proof is not null "
        "and a.proof<>'')").fetchone()[0]
    unregistered = c.execute(
        "select count(*) from work_item w left join project p on p.id=w.project where p.id is null").fetchone()[0]
    c.close()
    out["ledger"] = {
        "states": states, "todo_by_priority": by_pri, "per_project": per,
        "attempts": attempts, "children_in_progress": open_attempts,
        "settled_attempts": closed, "settled_with_proof": with_proof,
        "running_without_attempt": running_missing_attempt, "orphan_attempts": orphans,
        "running_without_lease": running_no_lease, "expired_leases_held": expired_held,
        "done_without_proof": done_no_proof, "items_in_unregistered_project": unregistered,
    }
    for key, label in (("orphan_attempts", "attempt rows point at items that do not exist"),
                       ("running_without_attempt", "running/done items have no attempt row"),
                       ("running_without_lease", "running items have no lease"),
                       ("expired_leases_held", "expired leases are still held"),
                       ("done_without_proof", "items are marked done without a proof"),
                       ("items_in_unregistered_project", "items point at an unregistered project")):
        if out["ledger"].get(key):
            note_problem("%d %s" % (out["ledger"][key], label))
    if closed and with_proof < closed:
        out["ledger"]["settled_without_proof"] = closed - with_proof
except Exception as exc:
    out["ledger"] = {"error": "%s: %s" % (type(exc).__name__, exc)}
    note_problem("could not read the work ledger")

# --- liveness: a quiet system and a dead system look identical unless you measure the heartbeats ---
def age_min(path):
    try:
        t = os.path.getmtime(path)
        return round((time.time() - t) / 60.0, 1)
    except Exception:
        return None

src_age, wake_age = age_min(src_hb), age_min(wake_hb)
out["liveness"] = {"sources_heartbeat_age_min": src_age, "dispatcher_heartbeat_age_min": wake_age}
# THE RELEASE HEARTBEAT IS WRITTEN BY A RELEASE, SO A SPENT CAP LOOKS LIKE A DEATH.
# Measured 2026-10-14 14:19Z: this raised "the dispatcher heartbeat is 183.4 minutes old (>15) -
# nothing can revive work" while wake-fanout.sh was running every minute printing
# `skip: nothing claimable ... gate: daily-cap, daily_cap: 150/150 releases today`, and the
# sources heartbeat was 12 min old. The dispatcher's OWN liveness is the fan-out log, which is
# appended every minute whether or not anything is released.
fanout_age = age_min(fanout)
fanout_last = ""
try:
    fanout_last = (open(fanout, encoding="utf-8", errors="replace").read().splitlines() or [""])[-1].strip()[:180]
except Exception:
    fanout_last = ""
out["liveness"]["fanout_heartbeat_age_min"] = fanout_age
out["liveness"]["fanout_last"] = fanout_last
if wake_age is None or wake_age > 15:
    if fanout_age is not None and fanout_age <= 5:
        # ALIVE AND GATED, NOT DEAD. Nothing has been released and nothing needs to be: the
        # fan-out is running this minute and its own last line says why it started nothing.
        out["liveness"]["no_release_because"] = fanout_last or "the fan-out log says nothing yet"
    else:
        note_problem("the dispatcher is DEAD: no release for %s min and the fan-out log is %s min old"
                     % (wake_age if wake_age is not None else "missing",
                        fanout_age if fanout_age is not None else "missing"))
if src_age is None or src_age > 45:
    note_problem("the sources heartbeat is %s minutes old (>45) - no new work is being filed"
                 % (src_age if src_age is not None else "missing"))

# --- processes: is anything actually working right now ----------------------------------------
try:
    ps = subprocess.run(["ps", "-eo", "args="], capture_output=True, text=True, timeout=30).stdout
    procs = [l for l in ps.splitlines() if l.startswith("bash ") and l.rstrip().endswith("bin/wake-dispatch.sh")]
    out["liveness"]["dispatch_processes"] = len(procs)
    if len(procs) > 8:
        note_problem("%d dispatcher processes alive - above the fan-out ceiling" % len(procs))
except Exception:
    pass

# --- the last few releases, so a failure is visible without reading a log ---------------------
try:
    lines = [l for l in open(log, encoding="utf-8", errors="replace").read().splitlines()
             if "releasing wake" in l][-4:]
    out["last_releases"] = [l.strip()[:130] for l in lines]
    fails = [l for l in lines if "failed" in l]
    if fails:
        out.setdefault("recent_release_failures", fails)
except Exception:
    pass
try:
    tail = open(fanout, encoding="utf-8", errors="replace").read().splitlines()[-3:]
    out["last_fanout"] = [l.strip()[:130] for l in tail]
except Exception:
    pass

# --- the answer, for a human ------------------------------------------------------------------
if as_json:
    print(json.dumps(out, indent=2, sort_keys=False))
    raise SystemExit(0)

w, l = out.get("wake", {}), out.get("ledger", {})
print("AUTONOMY %s" % out["at"])
# Name the cap the LOOP enforces first; put this shell's default in parentheses only when it
# differs, and never let the default stand in for the enforced value (see the block above).
_eff, _eff_usd = w.get("effective_max_per_day"), w.get("effective_max_usd_per_day")
if _eff is not None and str(_eff) != str(w.get("backstop")):
    cap_txt = "%s ENFORCED (wake.py default %s; recorded by %s at %s)" % (
        _eff, w.get("backstop"), w.get("effective_caps_source"), w.get("effective_caps_at"))
    usd_txt = "%s ENFORCED" % _eff_usd
else:
    cap_txt = "%s backstop" % w.get("backstop")
    usd_txt = w.get("spend_ceiling_usd")
print("  releases today : %s of %s | failed %s | spend %s of %s USD" % (
    w.get("released_today"), cap_txt, w.get("failed_today"),
    w.get("spend_today_usd"), usd_txt))
_force = w.get("caps_in_force") or []
if not _force and w.get("effective_caps_force"):
    # The recorded reading is from the environment the loop actually runs in; this shell's is not.
    _force = w["effective_caps_force"]
if _force:
    print("  caps in force  : %s" % "; ".join(_force))
print("  wake states    : %s" % w.get("states"))
print("  ledger         : %s" % l.get("states"))
print("  todo by priority: %s" % l.get("todo_by_priority"))
print("  proofs         : %s of %s settled attempts carry one (%s still in progress)" % (
    l.get("settled_with_proof"), l.get("settled_attempts"), l.get("children_in_progress")))
print("  in flight      : %s dispatch process(es)" % out.get("liveness", {}).get("dispatch_processes"))
print("  liveness       : dispatcher heartbeat %s min (fan-out log %s min), sources heartbeat %s min" % (
    out.get("liveness", {}).get("dispatcher_heartbeat_age_min"),
    out.get("liveness", {}).get("fanout_heartbeat_age_min"),
    out.get("liveness", {}).get("sources_heartbeat_age_min")))
if out.get("liveness", {}).get("no_release_because"):
    print("  no release     : the dispatcher is alive and gated - %s"
          % out["liveness"]["no_release_because"])
if l.get("per_project"):
    # ONLY PROJECTS WITH WORK. A project holding nothing is not information - and listing it makes the
    # real backlog harder to read. Its rows are kept in the store regardless, so nothing is lost by not
    # printing zeros here. (Measured: a disabled test project showed as a row of zeros.)
    live = [p for p in l["per_project"]
            if (p.get("todo") or 0) + (p.get("run") or 0) + (p.get("done") or 0) > 0]
    if live:
        print("  per project    :")
        for p in live:
            print("    %-20s todo=%-4s running=%-3s done=%-3s" % (
                p.get("project"), p.get("todo"), p.get("run"), p.get("done")))
    hidden = len(l["per_project"]) - len(live)
    if hidden:
        print("    (+%d project(s) with no items at all, not shown)" % hidden)
if out.get("last_releases"):
    print("  last releases  :")
    for r in out["last_releases"]:
        print("    %s" % r)
if out.get("problems"):
    print("  PROBLEMS:")
    for p in out["problems"]:
        print("    - %s" % p)
else:
    print("  PROBLEMS      : none")

# IDLE IS NOT A PROBLEM, and a status command that cannot say so will make somebody "fix" a healthy
# system. Say WHY nothing is running: gated rows are the guards working; no rows at all is a quiet queue.
st = (w.get("states") or {})
in_flight = out.get("liveness", {}).get("dispatch_processes") or 0
if not in_flight and not out["problems"]:
    waiting = st.get("new") or 0
    # A WAITING COUNT CANNOT DISTINGUISH GATED FROM STALLED. Measured 2026-09-30: seven rows waiting,
    # every one gated days into the future (two by 28 days), while this line said "the next cron tick
    # should claim" - so a healthy gated queue and a 55-minute stall printed the same sentence. Ask the
    # store when anything could ACTUALLY be claimed, and say that instead.
    nc = None
    try:
        # ASK IT IN THE LOOP'S OWN ENVIRONMENT. Without the recorded overrides this call answers
        # against wake.py's defaults and reports rows claimable that `wake.py claim` will refuse -
        # which is how this line printed "the next cron tick should claim" for 3h44m on
        # 2026-10-13 while the enforced cap was reached. The numbers stay wake.py's; only the
        # environment is corrected to the one the loop runs in.
        nc_env = dict(os.environ)
        try:
            _rec = json.loads(open(CAPS_EFFECTIVE, encoding="utf-8").read() or "{}")
            for _k, _v in (_rec.get("env") or {}).items():
                if _v:
                    nc_env[_k] = str(_v)
        except Exception:
            pass
        raw_nc = subprocess.run(
            ["python3", os.environ.get("WAKE_NEXTCLAIM", "/root/bin/wake-nextclaim.py"), "--json"],
            capture_output=True, text=True, timeout=60, env=nc_env).stdout
        d_nc = json.loads(raw_nc)
        if d_nc.get("ok"):
            nc = d_nc
    except Exception:
        nc = None
    if not waiting:
        print("  IDLE          : healthy - the queue is EMPTY (no new rows)")
    elif nc is None:
        print("  IDLE          : %d row(s) waiting; the claim gate could NOT be read" % waiting)
    elif nc.get("blocked_by"):
        # A cap IN FORCE is not idleness and must never read as "the next tick should claim".
        # Measured 2026-10-13: this branch did not exist, so with the enforced daily cap reached
        # and every release refused for 3h44m the line said "75 row(s) CLAIMABLE NOW ... the next
        # cron tick should claim" - a sentence that was false every minute it was printed.
        print("  IDLE          : GATED - %d row(s) waiting, NONE claimable now because %s is in "
              "force (%s); %d would be claimable the moment it clears"
              % (waiting, nc.get("blocked_by"), nc.get("blocking_detail") or "no detail",
                 nc.get("claimable_when_open", 0)))
    elif nc.get("claimable_now"):
        print("  IDLE          : %d row(s) CLAIMABLE NOW (ids %s) and nothing running - the next cron tick should claim"
              % (nc["claimable_now"], ",".join(str(i) for i in nc.get("claimable_ids", [])[:6])))
    else:
        print("  IDLE          : healthy - %d row(s) waiting, NONE claimable now; earliest %s (%s)"
              % (waiting, nc.get("earliest") or "unknown", (nc.get("earliest_subject") or "")[:40]))
PY
# VALUE AND BUDGET, in one read. Items closed today, dollars per closed item, and the spend against
# the ceiling the queue itself enforces - so a reader can never be shown a cap no process honours.
python3 "${WAKE_VALUE:-/root/bin/wake-value.py}" 2>/dev/null || true
exit 0
