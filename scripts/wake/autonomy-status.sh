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

WAKE_CLI=${WAKE_CLI:-/home/zabz/bin/wake.py}
WORK_CLI=${WORK_CLI:-/home/zabz/bin/work.py}
WORK_DB=${WORK_DB:-/home/zabz/work/work.db}
LOG=${WAKE_LOG:-/home/zabz/.sms-inbox/wake-dispatch.log}
FANOUT=${WAKE_FANOUT_LOG:-/home/zabz/.sms-inbox/wake-fanout.log}
SRC_HB=/home/zabz/.sms-inbox/sources-heartbeat
WAKE_HB=/home/zabz/.sms-inbox/wake-heartbeat

python3 - "$JSON" "$WAKE_CLI" "$WORK_CLI" "$WORK_DB" "$LOG" "$FANOUT" "$SRC_HB" "$WAKE_HB" <<'PY'
import json, os, re, subprocess, sqlite3, sys, time, datetime

as_json = sys.argv[1] == "1"
wake_cli, work_cli, work_db, log, fanout, src_hb, wake_hb = sys.argv[2:9]

out = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "ok": True, "problems": []}

def note_problem(msg):
    out["problems"].append(msg)

# --- the wake store's own numbers -------------------------------------------------------------
try:
    raw = subprocess.run(["python3", wake_cli, "stats", "--json"], capture_output=True,
                         text=True, timeout=120).stdout
    d = json.loads(raw or "{}")
    caps = d.get("caps") or {}
    out["wake"] = {
        "released_today": d.get("released_today"),
        "failed_today": d.get("failed_today"),
        "backstop": caps.get("max_per_day"),
        "spend_today_usd": d.get("spend_today_usd"),
        "spend_ceiling_usd": caps.get("max_usd_per_day"),
        "states": {k: v for k, v in (d.get("states") or {}).items() if v},
        "caps_in_force": d.get("caps_in_force") or [],
        "paused": caps.get("paused"),
    }
    if caps.get("paused"):
        note_problem("the wake system is PAUSED (pause file present)")
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
if wake_age is None or wake_age > 15:
    note_problem("the dispatcher heartbeat is %s minutes old (>15) - nothing can revive work"
                 % (wake_age if wake_age is not None else "missing"))
if src_age is None or src_age > 45:
    note_problem("the sources heartbeat is %s minutes old (>45) - no new work is being filed"
                 % (src_age if src_age is not None else "missing"))

# --- processes: is anything actually working right now ----------------------------------------
try:
    ps = subprocess.run(["ps", "-eo", "args="], capture_output=True, text=True, timeout=30).stdout
    procs = [l for l in ps.splitlines() if l.startswith("bash /home/zabz/bin/wake-dispatch.sh")]
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
print("  releases today : %s of %s backstop | failed %s | spend %s of %s USD" % (
    w.get("released_today"), w.get("backstop"), w.get("failed_today"),
    w.get("spend_today_usd"), w.get("spend_ceiling_usd")))
if w.get("caps_in_force"):
    print("  caps in force  : %s" % "; ".join(w["caps_in_force"]))
print("  wake states    : %s" % w.get("states"))
print("  ledger         : %s" % l.get("states"))
print("  todo by priority: %s" % l.get("todo_by_priority"))
print("  proofs         : %s of %s settled attempts carry one (%s still in progress)" % (
    l.get("settled_with_proof"), l.get("settled_attempts"), l.get("children_in_progress")))
print("  in flight      : %s dispatch process(es)" % out.get("liveness", {}).get("dispatch_processes"))
print("  liveness       : dispatcher heartbeat %s min, sources heartbeat %s min" % (
    out.get("liveness", {}).get("dispatcher_heartbeat_age_min"),
    out.get("liveness", {}).get("sources_heartbeat_age_min")))
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
    if waiting and w.get("caps_in_force"):
        print("  IDLE          : healthy - %d row(s) waiting, every one gated by %s"
              % (waiting, "; ".join(w["caps_in_force"])))
    elif waiting:
        print("  IDLE          : %d row(s) waiting and no cap in force - the next cron tick should claim"
              % waiting)
    else:
        print("  IDLE          : healthy - the queue is EMPTY (no new rows)")
PY
exit 0
