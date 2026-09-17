#!/usr/bin/env bash
#
# Install the mesh broker as a systemd service ON THE AUTHORITY. Idempotent; safe to re-run.
#
#   sudo bash deploy/install-authority.sh [SOURCE_DIR]
#
# SOURCE_DIR defaults to this package's own root (`<script>/..`). The script deploys that tree to
# /home/zabz/mesh-broker, records the sha256 of every deployed file in PROVENANCE.md, runs the
# package's own tests FROM THE DEPLOYED COPY, retires the hand-started broker if one is still
# around, installs and enables the unit, and then proves the result with raw output.
#
# WHY IT VERIFIES THE COPY AND NOT THE EXIT CODE. `scp -r <dir> host:/an/existing/dir` is a no-op
# that exits 0 - stream S5 lost an hour to exactly that (docs/mesh/76-broker.md §6.4). So this
# script hashes what is on disk, runs the tests from the deployed path, and asserts on the
# systemd MainPID rather than on "the port answers".
#
# It does NOT reboot anything, does NOT touch tailscale, does NOT open a firewall port and does
# NOT publish the broker: the broker is loopback-only by the owner's decision.
#
# Written by stream O5 of the overnight program, 2026-09-17. See docs/mesh/86-authority.md §1.

set -uo pipefail

DEST=/home/zabz/mesh-broker
UNIT=/etc/systemd/system/mesh-broker.service
SERVICE=mesh-broker
NODE_BIN=/usr/bin/node
PORT=3091
PIDFILE=/tmp/mesh-broker.pid
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="${1:-$(cd "$SCRIPT_DIR/.." && pwd)}"

PASS=0
FAIL=0
declare -a RESULTS

ok()   { PASS=$((PASS + 1)); RESULTS+=("PASS  $1"); printf 'PASS  %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); RESULTS+=("FAIL  $1"); printf 'FAIL  %s\n' "$1"; }
step() { printf '\n== %s ==\n' "$1"; }

if [ "$(id -u)" != "0" ]; then
  echo "this script installs a systemd unit and must run as root:  sudo bash $0 $*" >&2
  exit 2
fi
for f in bin/mesh-broker.mjs lib/scoring.js lib/broker.js lib/server.js lib/config.js lib/capacity.js \
         lib/leases.js nodes.json package.json deploy/mesh-broker.service; do
  if [ ! -f "$SRC/$f" ]; then
    echo "SOURCE_DIR $SRC is not a mesh-broker package: $f is missing" >&2
    exit 2
  fi
done

step "source and runtime"
echo "source   : $SRC"
echo "dest     : $DEST"
echo "date     : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "node     : $($NODE_BIN --version)  ($NODE_BIN)"
echo "host     : $(hostname)  $(uname -sr)"

# ---------------------------------------------------------------- 1. deploy the tree
step "1. deploy the tree to $DEST"
if [ "$(readlink -f "$SRC")" = "$(readlink -f "$DEST" 2>/dev/null || echo /nonexistent)" ]; then
  echo "   source IS the destination; nothing to copy (rerun in place)"
else
  install -d -o zabz -g zabz -m 0755 "$DEST"
  for d in bin lib test deploy; do
    install -d -o zabz -g zabz -m 0755 "$DEST/$d"
    for f in "$SRC/$d"/*; do
      [ -f "$f" ] || continue
      install -o zabz -g zabz -m 0644 "$f" "$DEST/$d/$(basename "$f")"
    done
  done
  chmod 0755 "$DEST/bin/"*.mjs 2>/dev/null
  chmod 0755 "$DEST/deploy/"*.sh 2>/dev/null
  install -o zabz -g zabz -m 0644 "$SRC/nodes.json" "$DEST/nodes.json"
  install -o zabz -g zabz -m 0644 "$SRC/package.json" "$DEST/package.json"
fi
chmod 0755 "$DEST" "$DEST/bin" "$DEST/lib" "$DEST/test" "$DEST/deploy" 2>/dev/null
echo "   $(find "$DEST" -maxdepth 1 -type f | wc -l) file(s) at the top level, $(find "$DEST" -type f | wc -l) in the tree"

# ---------------------------------------------------------------- 2. provenance
step "2. PROVENANCE.md - the sha256 of every deployed file, written from the deployed copy"
{
  echo "# Provenance of the deployed mesh broker"
  echo
  echo "Deployed: $(date -u '+%Y-%m-%dT%H:%M:%SZ')  by \`deploy/install-authority.sh\` (stream O5)."
  echo "Source of truth for this package: \`packages/mesh-broker/**\` in \`harness-config\`"
  echo "(docs: \`docs/mesh/76-broker.md\`, \`docs/mesh/86-authority.md\`)."
  echo
  echo "This file is DELIBERATELY a manifest and not a promise. Re-running"
  echo "\`deploy/verify-deploy.sh\` re-hashes the deployed tree against the source tree and fails"
  echo "loudly on any difference, because a copy that drifts silently is a copy nobody can trust."
  echo
  echo '```'
  echo "source: $SRC"
  echo "dest:   $DEST"
  echo "node:   $($NODE_BIN --version)"
  echo '```'
  echo
  echo "| file | sha256 |"
  echo "|---|---|"
  (cd "$DEST" && find bin lib nodes.json package.json deploy -type f | sort | while read -r f; do
     printf '| `%s` | `%s` |\n' "$f" "$(sha256sum "$f" | cut -d' ' -f1)"
   done)
  echo
  echo "The unit is installed at \`$UNIT\` from \`$SRC/deploy/mesh-broker.service\`;"
  echo "its sha256 is recorded in docs/mesh/86-authority.md rather than here, because a unit file"
  echo "living in /etc is not part of this tree."
} > "$DEST/PROVENANCE.md"
chown zabz:zabz "$DEST/PROVENANCE.md"
echo "   wrote $DEST/PROVENANCE.md ($(wc -l < "$DEST/PROVENANCE.md") lines, $(grep -c '^| `' "$DEST/PROVENANCE.md") files hashed)"
DEPLOYED_HASHES=$(grep '^| `' "$DEST/PROVENANCE.md" | wc -l)

# ---------------------------------------------------------------- 3. the deployed copy is the code that passes
step "3. run the package tests FROM THE DEPLOYED COPY (proves the copy, not the exit code)"
TEST_LOG=$(mktemp)
if (cd "$DEST" && $NODE_BIN --test test/scoring.test.mjs test/config.test.mjs test/leases.test.mjs test/acceptance.test.mjs) > "$TEST_LOG" 2>&1; then
  ok "the deployed copy passes its own suite: $(grep -E '^. (tests|pass|fail) ' "$TEST_LOG" | tr '\n' ' ')"
else
  bad "the deployed copy FAILS its own suite - not installing a broken broker"
  tail -40 "$TEST_LOG"
  exit 1
fi
# Assert on something only the amended code has, so a stale copy cannot pass silently.
if grep -q 'reserveMiB(reading)' "$DEST/lib/scoring.js" && grep -q 'IPAddressDeny' "$DEST/deploy/mesh-broker.service"; then
  ok "the deployed copy carries the per-node reserve and the loopback-enforcing unit"
else
  bad "the deployed copy is STALE (no per-node reserve / no IPAddressDeny in its unit)"
  exit 1
fi
rm -f "$TEST_LOG"

# ---------------------------------------------------------------- 4. retire the hand-started broker
step "4. retire the hand-started broker, if one is still running"
if [ -f "$PIDFILE" ]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null | tr -dc '0-9')
  if [ -n "${OLD_PID:-}" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    OLD_CMD=$(tr '\0' ' ' < "/proc/$OLD_PID/cmdline" 2>/dev/null)
    if printf '%s' "$OLD_CMD" | grep -q 'mesh-broker'; then
      echo "   pid $OLD_PID is the hand-started broker: $(printf '%s' "$OLD_CMD" | head -c 120)"
      kill "$OLD_PID" 2>/dev/null
      WAITED=0
      while kill -0 "$OLD_PID" 2>/dev/null && [ "$WAITED" -lt 50 ]; do sleep 0.2; WAITED=$((WAITED + 1)); done
      if kill -0 "$OLD_PID" 2>/dev/null; then kill -9 "$OLD_PID" 2>/dev/null; sleep 0.5; fi
      if kill -0 "$OLD_PID" 2>/dev/null; then bad "pid $OLD_PID would not die"; else ok "hand-started broker pid $OLD_PID stopped after $((WAITED / 5)) s"; fi
    else
      echo "   PIDFILE names pid $OLD_PID but that process is NOT a mesh broker - NOT killing it"
      echo "   (a stale pidfile is a licence to kill a stranger; this is the check that stops it)"
    fi
  else
    echo "   pidfile $PIDFILE is stale (no live process)"
  fi
  # Retire the pidfile rather than delete it: a stale 8-byte pidfile is what the smoke script
  # would `kill`, and in this world pids get reused. Evidence kept, hazard gone.
  mv -f "$PIDFILE" "$PIDFILE.retired-by-o5-$(date -u +%Y%m%dT%H%M%SZ)" && ok "the /tmp pidfile is retired, not deleted, so nothing can kill a reused pid"
else
  echo "   no $PIDFILE"
fi
if ss -ltnH "sport = :$PORT" | grep -q .; then
  HOLDER=$(ss -ltnpH "sport = :$PORT" | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  MAINNOW=$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null)
  # ss reports the process NAME as "node", so matching on the string "mesh-broker" is wrong - the
  # first version of this check would have read our own service as a stranger and aborted. The
  # identity that matters is the pid, and it must be THIS service's MainPID.
  if [ -n "$HOLDER" ] && [ "$HOLDER" = "$MAINNOW" ] && [ "$MAINNOW" != "0" ]; then
    ok "port $PORT is held by this service itself (MainPID $MAINNOW); the restart in step 5 replaces it"
  else
    echo "   port $PORT is held by pid ${HOLDER:-unknown}, which is NOT this service's MainPID ($MAINNOW):"
    ss -ltnpH "sport = :$PORT" | sed 's/^/   /'
    bad "port $PORT is held by something else - refusing to fight it for the port"
    exit 1
  fi
else
  ok "port $PORT is free"
fi

# ---------------------------------------------------------------- 5. install the unit
step "5. install and enable $UNIT"
install -o root -g root -m 0644 "$DEST/deploy/mesh-broker.service" "$UNIT"
echo "   sha256 $(sha256sum "$UNIT" | cut -d' ' -f1)"
if systemd-analyze verify "$UNIT" 2>&1 | grep -v '^$'; then :; else echo "   systemd-analyze verify: clean"; fi
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"
sleep 2
systemctl is-enabled "$SERVICE" >/dev/null 2>&1 && ok "enabled (so it comes up on boot without a human)" || bad "not enabled"
LINK=/etc/systemd/system/multi-user.target.wants/$SERVICE.service
[ -L "$LINK" ] && ok "boot wiring present: $LINK -> $(readlink "$LINK")" || bad "no multi-user.target.wants symlink"
systemctl is-active "$SERVICE" >/dev/null 2>&1 && ok "active" || { bad "not active"; systemctl status "$SERVICE" --no-pager -l | tail -30; journalctl -u "$SERVICE" -n 40 --no-pager; exit 1; }

# ---------------------------------------------------------------- 6. prove it, with raw output
step "6. the service, and only the service, owns the port"
MAIN=$(systemctl show -p MainPID --value "$SERVICE")
echo "   systemd MainPID   : $MAIN"
echo "   nodes.json owner  : $(ls -l "$DEST/nodes.json" | awk '{print $3":"$4}')"
ss -ltnpH "sport = :$PORT" | sed 's/^/   /'
if ss -ltnpH "sport = :$PORT" | grep -q "pid=$MAIN,"; then ok "the listening pid IS the systemd MainPID ($MAIN)"; else bad "the listening pid is not the MainPID - a stranger is answering"; fi
if ss -ltnH "sport = :$PORT" | awk '{print $4}' | grep -qv '^127\.0\.0\.1:'; then bad "bound to something other than 127.0.0.1"; else ok "bound to 127.0.0.1 only"; fi

step "7. LOOPBACK ONLY, proved three ways"
LOOP=$(curl -s --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/healthz")
[ "$LOOP" = "200" ] && ok "loopback answers 200" || bad "loopback answered $LOOP"
HOSTIP=$(hostname -I | awk '{print $1}')
curl -s --max-time 3 -o /dev/null "http://$HOSTIP:$PORT/healthz"; E1=$?
[ "$E1" != "0" ] && ok "a request to this host's own LAN address ($HOSTIP) does NOT get through (curl exit $E1: nothing is bound there - the bind is 127.0.0.1)" || bad "the LAN address reached the broker (curl exit 0)"
TSIP=$(tailscale ip -4 2>/dev/null | head -1)
if [ -n "${TSIP:-}" ] && [ "$TSIP" != "$HOSTIP" ]; then
  curl -s --max-time 3 -o /dev/null "http://$TSIP:$PORT/healthz"; E2=$?
  [ "$E2" != "0" ] && ok "a request to the tailnet address ($TSIP) does NOT get through (curl exit $E2)" || bad "the tailnet address reached the broker"
fi
tailscale serve status 2>/dev/null | sed 's/^/   tailscale serve: /' || true
if tailscale serve status 2>/dev/null | grep -q "$PORT"; then bad "something published the broker via tailscale serve"; else ok "tailscale serve publishes nothing on $PORT"; fi

step "8. the four verbs still answer, through the service"
curl -s --max-time 10 "http://127.0.0.1:$PORT/healthz" | head -c 400; echo
NODES=$(curl -s --max-time 25 "http://127.0.0.1:$PORT/nodes")
printf '%s' "$NODES" | $NODE_BIN -e '
let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
  const r=JSON.parse(s);
  console.log("   nodes",r.nodes.length,"| reads",r.reads,"| readFailures",r.readFailures);
  for(const n of r.nodes) console.log("   ",n.node.padEnd(18),n.state.padEnd(20),"slots",String(n.slots).padStart(3),
    "| reserve",(n.scoreTerms&&n.scoreTerms.reserveMiB)+" ("+(n.scoreTerms&&n.scoreTerms.reserveBasis)+")");
  const okn=r.nodes.filter(n=>n.state==="ok").length;
  const derived=r.nodes.filter(n=>n.scoreTerms&&n.scoreTerms.reserveBasis==="derived").length;
  console.log("   SUMMARY ok="+okn+" derivedReserve="+derived);
});' 2>&1 | tee /tmp/o5-nodes-summary.txt
# THE ASSERTION WHOSE ABSENCE LET A BLIND BROKER PASS. The first version of this script proved the
# port, the loopback rule and the verbs while the service could not reach a single node - a
# sandbox rule on egress - and reported 19/20 PASS. A broker that cannot read a node cannot place
# work, so "can it read the mesh" is an install-time assertion, not an assumption.
if grep -qE 'SUMMARY ok=[1-9]' /tmp/o5-nodes-summary.txt; then
  ok "the service can READ the mesh (at least one node answered its gate)"
else
  bad "THE SERVICE CANNOT READ ANY NODE. Its own /nodes says so above. Check egress: a sandbox rule (IPAddress*/SocketBind*), a firewall, or the tailnet - NOT the roster."
fi
if grep -qE 'SUMMARY ok=[1-9] derivedReserve=[1-9]' /tmp/o5-nodes-summary.txt; then
  ok "at least one node's reserve is DERIVED from its own mem.totalMiB (the per-node reserve is live)"
else
  bad "every reachable node fell back to the frozen 3885 MiB reserve - the nodes are not reporting mem.totalMiB"
fi
PLACE=$(curl -s --max-time 25 -X POST -H 'content-type: application/json' \
  -d '{"task":{"kind":"fleet","children":2,"worktreeGiB":0}}' "http://127.0.0.1:$PORT/place")
printf '%s' "$PLACE" | $NODE_BIN -e '
let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const j=JSON.parse(s);
  console.log("   place ->",j.node,"position",j.position,"score",j.score,"tier",j.tier,"lease",j.lease);
  console.log("   "+(j.rationale||[]).filter(l=>/reserve/.test(l)).join("\n   "));
  require("fs").writeFileSync("/tmp/o5-lease.txt",j.lease);
});' 2>&1
LEASE=$(cat /tmp/o5-lease.txt 2>/dev/null)
DONE=$(curl -s --max-time 10 -X POST -H 'content-type: application/json' -d "{\"lease\":\"$LEASE\",\"ok\":true}" "http://127.0.0.1:$PORT/done")
echo "   done  -> $DONE"
printf '%s' "$PLACE" | grep -q '"node"' && ok "POST /place answered a placement" || bad "POST /place did not answer a placement"
# The broker pretty-prints its JSON, so match `"released": true` with optional whitespace -
# the first version of this line required no space and reported a FAILURE on a released lease.
printf '%s' "$DONE" | grep -qE '"released": *true' && ok "POST /done released it" || bad "POST /done did not release the lease"
rm -f /tmp/o5-lease.txt

step "9. the service comes back on its own - a supervised restart and a SIGKILL"
BEFORE=$(systemctl show -p MainPID --value "$SERVICE")
systemctl restart "$SERVICE"; sleep 2
AFTER_RESTART=$(systemctl show -p MainPID --value "$SERVICE")
[ "$AFTER_RESTART" != "$BEFORE" ] && [ "$AFTER_RESTART" != "0" ] && ok "systemctl restart: MainPID $BEFORE -> $AFTER_RESTART" || bad "restart did not replace the process"
curl -s --max-time 5 -o /dev/null "http://127.0.0.1:$PORT/healthz" && ok "answers after a supervised restart" || bad "silent after a supervised restart"
echo "   sending SIGKILL to $AFTER_RESTART (the crash systemd cannot distinguish from a fault)"
kill -9 "$AFTER_RESTART" 2>/dev/null
sleep 5
AFTER_KILL=$(systemctl show -p MainPID --value "$SERVICE")
STATE=$(systemctl is-active "$SERVICE")
[ "$AFTER_KILL" != "$AFTER_RESTART" ] && [ "$AFTER_KILL" != "0" ] && [ "$STATE" = "active" ] && ok "SIGKILL: MainPID $AFTER_RESTART -> $AFTER_KILL, service $STATE" || bad "did NOT come back after SIGKILL (MainPID $AFTER_KILL, state $STATE)"
curl -s --max-time 5 -o /dev/null "http://127.0.0.1:$PORT/healthz" && ok "answers after the SIGKILL restart" || bad "silent after the SIGKILL restart"
echo "   journal, last 12 lines of this service:"
journalctl -u "$SERVICE" -n 12 --no-pager | sed 's/^/   /'

step "result"
printf '%s\n' "${RESULTS[@]}"
echo
echo "$PASS passed, $FAIL failed   ($(date -u '+%Y-%m-%dT%H:%M:%SZ'))"
echo "REBOOT NOT PERFORMED by this script: it proves a supervised restart and a SIGKILL crash,"
echo "and the unit's enable symlink is what starts it at boot. See docs/mesh/86-authority.md §1.5."
[ "$FAIL" -eq 0 ]
