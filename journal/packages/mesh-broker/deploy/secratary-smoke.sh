#!/usr/bin/env bash
#
# The smoke run for stream S5, on the authority itself.
#
#   scp -r packages/mesh-broker secratary-ts:/home/zabz/mesh-broker-run
#   ssh secratary-ts "bash /home/zabz/mesh-broker-run/deploy/secratary-smoke.sh"
#
# It does three things and changes nothing else on the machine:
#   1. runs the package's tests under the authority's own Node (v20.20.2 measured 2026-09-17,
#      the broker's floor is Node 18: global fetch is not used anywhere, `node --test` and
#      `node:http` are);
#   2. starts the broker on 127.0.0.1:$PORT with a pidfile and a log in /tmp;
#   3. asks it the three frozen verbs and prints the raw answers, including a 6-child fleet
#      placement with its full rationale.
#
# It installs nothing, writes no service unit, restarts no engine, and touches no other
# port. A live broker is left running so stream S6/S7 can use it; stop it with
# `kill "$(cat /tmp/mesh-broker.pid)"`.
#
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PKG_ROOT="$(pwd)"
PORT="${MESH_BROKER_PORT:-3091}"
PIDFILE=/tmp/mesh-broker.pid
LOG=/tmp/mesh-broker.log

echo "== host and runtime =="
hostname
node --version
echo "package: $PKG_ROOT"
echo

echo "== tests (node --test) =="
node --test test/scoring.test.mjs test/config.test.mjs test/leases.test.mjs test/acceptance.test.mjs 2>&1 | tail -18
echo

if systemctl cat mesh-broker >/dev/null 2>&1; then
  # THE SERVICE IS INSTALLED (stream O5, 2026-09-17 - docs/mesh/86-authority.md §1). systemd owns
  # the broker on this host now, so this script must not start a second one on the same port: the
  # second would die of EADDRINUSE while the first answered every curl below, which is the exact
  # "green while proving nothing" failure §6.4 of 76-broker.md records. It uses the service, and
  # it names the code the service is actually running so the reader can tell it apart from the
  # tree this script just tested.
  echo "== the broker is a SUPERVISED SERVICE on this host =="
  systemctl show -p MainPID -p ExecStart -p Restart --value mesh-broker | sed 's/^/   /'
  echo "   enabled: $(systemctl is-enabled mesh-broker 2>&1)   active: $(systemctl is-active mesh-broker 2>&1)"
  if ! systemctl is-active --quiet mesh-broker; then
    echo "   the unit exists but is not running; starting it"
    systemctl start mesh-broker
    sleep 1.5
  fi
  SVC_PID=$(systemctl show -p MainPID --value mesh-broker)
  if [ -z "$SVC_PID" ] || [ "$SVC_PID" = "0" ]; then
    echo "FATAL: the service has no MainPID"; systemctl status mesh-broker --no-pager -l | tail -25; exit 1
  fi
  echo "   the code the SERVICE runs: $(tr '\0' ' ' < "/proc/$SVC_PID/cmdline")"
  # /proc/<pid>/cmdline is NUL-separated. The first version of this line did `tr -d '\0'`, which
  # DELETES the separators and glues the argv together - so the path it then tried to hash was
  # "/usr/bin/node/home/zabz/..." and the hash printed as an empty string. A line that promises a
  # sha256 and prints nothing is worse than no line: it is the "green while proving nothing"
  # pattern 76-broker.md §6.4 records, in a line whose whole job is provenance.
  SVC_SCRIPT=$(tr '\0' '\n' < "/proc/$SVC_PID/cmdline" | grep -m1 'mesh-broker\.mjs$')
  SVC_SHA=$(sha256sum "$(dirname "$SVC_SCRIPT")/../lib/scoring.js" 2>/dev/null | cut -d' ' -f1)
  echo "   sha256 lib/scoring.js the SERVICE runs : ${SVC_SHA:-COULD NOT HASH $SVC_SCRIPT}"
  echo "   sha256 lib/scoring.js THIS SCRIPT tested: $(sha256sum "$PKG_ROOT/lib/scoring.js" | cut -d' ' -f1)"
  echo "   (if those two differ, the verbs below are answered by a DIFFERENT build than the tests above)"
  echo "   journal, last 8 lines:"; journalctl -u mesh-broker -n 8 --no-pager | sed 's/^/   /'
  echo
elif [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  OLD_PID="$(cat "$PIDFILE")"
  echo "== stopping the previous broker on pid $OLD_PID =="
  kill "$OLD_PID" 2>/dev/null
  # WAIT for it to be gone. The first version slept 0.5 s and started the new broker
  # immediately; if the old process had not released the port yet the new one died with
  # EADDRINUSE, the pidfile pointed at a corpse, and every curl below was answered by the
  # OLD broker - so the smoke run "passed" while proving nothing about the new code.
  # MEASURED 2026-09-17: that is exactly what happened, and it is why this waits on the pid.
  WAITED=0
  while kill -0 "$OLD_PID" 2>/dev/null && [ "$WAITED" -lt 50 ]; do
    sleep 0.2
    WAITED=$((WAITED + 1))
  done
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "   pid $OLD_PID ignored SIGTERM for 10 s; sending SIGKILL"
    kill -9 "$OLD_PID" 2>/dev/null
    sleep 0.5
  fi
  echo "   pid $OLD_PID is gone after $((WAITED / 5)) s"
fi

if ! systemctl cat mesh-broker >/dev/null 2>&1; then
  echo "== starting the broker on 127.0.0.1:$PORT =="
  nohup node bin/mesh-broker.mjs --port "$PORT" > "$LOG" 2>&1 &
  NEW_PID=$!
  echo $NEW_PID > "$PIDFILE"
  sleep 1.5
  if ! kill -0 "$NEW_PID" 2>/dev/null; then
    echo "FATAL: the new broker (pid $NEW_PID) is not running - the port may still be held, or the roster refused to load."
    echo "---- its log: ----"
    cat "$LOG"
    exit 1
  fi
  echo "pid $NEW_PID, log $LOG"
  cat "$LOG"
  echo
fi

echo "== GET /healthz =="
curl -s --max-time 10 "http://127.0.0.1:$PORT/healthz"
echo
echo "== GET /nodes =="
curl -s --max-time 20 "http://127.0.0.1:$PORT/nodes"
echo
echo "== POST /place : a 6-child fleet with a 2 GiB worktree =="
curl -s --max-time 20 -X POST -H 'content-type: application/json' \
  -d '{"task":{"kind":"fleet","children":6,"worktreeGiB":2,"prefer":null,"exclude":[]}}' \
  "http://127.0.0.1:$PORT/place"
echo
echo "== POST /place : a malformed body must still place =="
curl -s --max-time 20 -X POST -H 'content-type: application/json' -d 'not json' \
  "http://127.0.0.1:$PORT/place"
echo
if systemctl cat mesh-broker >/dev/null 2>&1; then
  echo "== the broker stays up under systemd; stop it with: sudo systemctl stop mesh-broker =="
else
  echo "== leaving the broker running; stop it with: kill \$(cat $PIDFILE) =="
fi
