#!/usr/bin/env python3
"""engine-watch -- notice when the DSH engine that serves the owner's phone dies.

WHY THIS EXISTS, measured 2026-10-02. `phone-engine.service` (the engine behind
http://127.0.0.1:3089, the Web UI and the phone) exited with status=1 at
2026-10-02T02:47:52Z after 1h41m of uptime:

    Error: UNKNOWN: unknown error, write   (errno -122 = EDQUOT)
      at OutputCollector.spillAll (dsh-subprocess-local/lib/runner-launch-*.js:769)

a tool-output spill write failing on the exhausted /tmp tmpfs user quota. systemd
restarted it 4 seconds later, so the *process* was fine and nothing looked wrong -
but every live session and every running subagent was killed with it, silently.
Nothing on this host watched the engine: `grep -rl phone-engine ~/bin/*.sh ~/bin/*.py`
returned nothing. The first thing to notice was the owner. A control whose trip is
silent is half a control.

WHAT IT DOES
  * reads the unit's restart counter and its current uptime once per run;
  * appends ONE line every run to ~/.dsh-engine-watch/watch.log (so there is a
    history even when nothing is wrong);
  * when the counter increases, or the unit is found not active, appends a loud
    incident line with the engine's own stderr tail, and raises EXACTLY ONE
    owner-queue row per incident - deduped by an open-row marker - because a dead
    engine means the owner's own phone is dark, which is his business and not an
    internal notice.

Read-only apart from its own log, the owner queue, and nothing else. Never
restarts anything: systemd already does that, and a second restarting authority
would fight it.

    python3 ~/bin/engine-watch.py            # check and record
    python3 ~/bin/engine-watch.py --status   # print the last state, change nothing
"""

import json
import os
import re
import subprocess
import sys
import time

UNIT = os.environ.get("ENGINE_WATCH_UNIT", "phone-engine.service")
STATE_DIR = os.path.expanduser("~/.dsh-engine-watch")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = os.path.join(STATE_DIR, "watch.log")
ERR_FILE = os.environ.get("ENGINE_WATCH_ERR", "/home/zabz/.dsh-phone/engine-3089.err")
QUEUE = os.environ.get("ENGINE_WATCH_QUEUE", os.path.expanduser("~/bin/owner-queue.py"))
MARKER = "[engine-watch]"
STAMP = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg):
    line = "%s %s" % (STAMP, msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def unit_facts():
    out = subprocess.run(
        ["systemctl", "show", UNIT, "-p", "NRestarts", "-p", "ActiveState",
         "-p", "Result", "-p", "ExecMainStartTimestamp", "-p", "MainPID"],
        capture_output=True, text=True).stdout
    facts = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            facts[k] = v.strip()
    try:
        facts["NRestarts"] = int(facts.get("NRestarts") or 0)
    except ValueError:
        facts["NRestarts"] = 0
    return facts


def err_tail(n=400):
    try:
        with open(ERR_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4000))
            return f.read().decode("utf-8", "replace")[-n:]
    except OSError:
        return "(no stderr file)"


def queue_row_already_open():
    try:
        r = subprocess.run([sys.executable, QUEUE, "list", "--json"],
                           capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout or "[]")
    except Exception:
        return False
    rows = data.get("rows") or data.get("items") if isinstance(data, dict) else data
    for row in rows or []:
        if str(row.get("status")) == "pending" and MARKER in str(row.get("question") or ""):
            return True
    return False


def raise_owner_row(facts, why):
    if queue_row_already_open():
        log("an owner row for %s is already open; not raising again" % MARKER)
        return
    tail = err_tail().replace("\n", " | ")
    subprocess.run([
        sys.executable, QUEUE, "add",
        "--question",
        "Your phone engine (phone-engine.service) died and restarted: %s. "
        "Do you want me to harden it so a full disk cannot kill the engine again? %s"
        % (why, MARKER),
        "--recommendation",
        "Harden it. A tool-output spill write failure should cost the output, never the engine.",
        "--options", "Harden it now|Leave it",
        "--severity", "high",
        "--blocks", "The engine behind your phone and this Web UI; a restart kills every live session and subagent",
        "--context", "%s at %s. NRestarts=%s ActiveState=%s Result=%s. stderr tail: %s"
        % (why, STAMP, facts.get("NRestarts"), facts.get("ActiveState"),
           facts.get("Result"), tail[:600]),
        "--source", "engine-watch",
    ], capture_output=True, text=True, timeout=90)


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    facts = unit_facts()
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            state = json.load(open(STATE_FILE))
        except Exception:
            state = {}
    last = state.get("nrestarts")
    state["nrestarts"] = facts["NRestarts"]
    state["checked"] = STAMP
    state["active"] = facts.get("ActiveState")
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1)

    if "--status" in sys.argv:
        print(json.dumps(state, indent=1))
        return 0

    log("unit=%s active=%s result=%s restarts=%s pid=%s"
        % (UNIT, facts.get("ActiveState"), facts.get("Result"),
           facts.get("NRestarts"), facts.get("MainPID")))

    if last is not None and facts["NRestarts"] > last:
        delta = facts["NRestarts"] - last
        log("INCIDENT: %s restarted %d time(s) since the last check (now %d) -- "
            "every live session and subagent died with it" % (UNIT, delta, facts["NRestarts"]))
        raise_owner_row(facts, "%s restart counter rose by %d" % (UNIT, delta))
        return 1
    if facts.get("ActiveState") not in ("active", "activating", "reloading"):
        log("INCIDENT: %s is %s" % (UNIT, facts.get("ActiveState")))
        raise_owner_row(facts, "%s is %s" % (UNIT, facts.get("ActiveState")))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
