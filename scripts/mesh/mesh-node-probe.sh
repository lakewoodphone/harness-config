#!/usr/bin/env bash
# mesh-node-probe.sh — re-measure every mesh node with a REAL child turn, and shout when a
# node's measured dispatchability disagrees with the broker's roster.
#
# WHY THIS EXISTS (2026-10-08)
# `mesh-broker/nodes.json` carries `dispatch.v1` — "can this node ACCEPT v1 work" — and
# NOTHING ever re-measured it. ZABZ-TECH's row said `true` from a 2026-09-16 measurement
# while, on 2026-10-08, every dispatch to it exited 1 with no completion frame. The broker
# still ranked it first (it was `true`), the provider still placed there (a placement is not
# a run), the lease was logged `place` then `done` as if all was well, and every session
# silently fell back to doing its work LOCALLY. The owner found out because his laptop
# became unusable. A measurement that is never renewed is not a measurement; it is a memory.
#
# WHAT IT DOES
# For each node below: run the same one-shot a dispatch runs, with a real prompt, and record
# whether it produced a final message. Then compare with the roster's own `dispatch.v1`:
#   * measured OK but roster says false  -> the node is being wasted (flag it, flip it back)
#   * measured FAIL but roster says true -> every dispatch to it dies here (flag it)
# Flags go through `wake.py flag`, whose subject is stable so it can never file twice a day.
#
# ADD A NODE: add a row here AND a row in mesh-broker/nodes.json. The script checks that the
# two agree on NAMES and reports any roster node it has no probe for, so a new node cannot be
# silently unmeasured — which is the exact failure this file exists to prevent.
set -u

STATE_DIR="${HOME}/.mesh-probe"
STATE="${STATE_DIR}/last.json"
ROSTER="${HOME}/mesh-broker/nodes.json"
mkdir -p "$STATE_DIR"

# node|ssh alias|invocation. Keep in step with packages/plugin-remote-fanout/lib/nodes.js:
# Windows nodes have NO `dsh` executor and use the interpreter form; POSIX nodes use the
# executor, which is the only thing that sources the worker credential.
NODES=(
  "zabz-tech|zabz-tech|C:/PROGRA~1/nodejs/node.exe C:/Users/ezabz/AppData/Local/npm-cache/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/dsh/lib/bin.js"
  "zabz-tech-linux|zabz-tech-linux|dsh"
  "lakewooechsmini|mac-mini-ts|/usr/local/bin/node /Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js"
  "zabz-yoga-1|zabz-yoga-1|C:/PROGRA~1/nodejs/node.exe C:/Users/ezabz/AppData/Local/npm-cache/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/dsh/lib/bin.js"
)
PROMPT='Reply with exactly MESH-PROBE-OK and nothing else.'
TIMEOUT=240

printf '{\n' > "$STATE.tmp"
first=1
declare -A RESULT

for row in "${NODES[@]}"; do
  node="${row%%|*}"; rest="${row#*|}"; alias="${rest%%|*}"; inv="${rest#*|}"
  started=$(date +%s)
  out=$(timeout "$TIMEOUT" ssh -o ConnectTimeout=10 -o BatchMode=yes "$alias" \
        "$inv --profile headless '$PROMPT'" 2>&1)
  code=$?
  ms=$(( ($(date +%s) - started) * 1000 ))
  if printf '%s' "$out" | grep -q 'MESH-PROBE-OK'; then ok=true; else ok=false; fi
  RESULT["$node"]="$ok|$code|$ms"
  printf '  "%s": {"ok": %s, "exit": %s, "ms": %s, "at": "%s"},\n' \
    "$node" "$ok" "$code" "$ms" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$STATE.tmp"
  printf 'PROBE %-18s ok=%-5s exit=%-4s %sms\n' "$node" "$ok" "$code" "$ms"
done
printf '  "_probed_at": "%s"\n}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$STATE.tmp"
mv "$STATE.tmp" "$STATE"

# ---- compare with the roster, and flag every disagreement -------------------------------
if [ -r "$ROSTER" ]; then
  roster_states=$(python3 - "$ROSTER" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for n in d.get("nodes", []):
    print(f"{n['node']}\t{n['dispatch']['v1']}")
PY
)
  flagged=0
  while IFS=$'\t' read -r node want; do
    [ -z "$node" ] && continue
    # A node the roster has never measured (dispatch.v1 null) is not a dispatch target -
    # secratary is the control plane and has no headless profile. Report it as excluded,
    # never as a gap, or the probe cries wolf about a node nobody intends to dispatch to.
    if [ "$want" = "None" ]; then
      echo "SKIP  $node: roster marks it unmeasured (dispatch.v1 null) - not a dispatch target"
      continue
    fi
    have="${RESULT[$node]:-}"
    if [ -z "$have" ]; then
      echo "GAP   roster node '$node' has no probe row in $0 (add one) - the failure this file prevents"
      continue
    fi
    ok="${have%%|*}"
    if [ "$want" = "True" ] && [ "$ok" = "false" ]; then
      echo "ALERT $node is in the roster as dispatchable but a real child turn FAILED"
      python3 ~/bin/wake.py flag \
        --subject "mesh-node-dispatch-failed:${node}" \
        --prompt "The mesh roster says node '$node' accepts v1 work, but a real headless child turn failed on it just now (see ~/.mesh-probe/last.json). Every dispatch placed there dies and is redone locally, which is what makes the owner's laptop unusable. Re-measure, set dispatch.v1 to false with the evidence (the broker ranks false below true), and fix the node." \
        --kind mesh-health --source mesh-node-probe --priority high 2>&1 | tail -1
      flagged=1
    elif [ "$want" = "False" ] && [ "$ok" = "true" ]; then
      echo "ALERT $node works but is marked NOT dispatchable - capacity is being wasted"
      python3 ~/bin/wake.py flag \
        --subject "mesh-node-dispatch-restored:${node}" \
        --prompt "Node '$node' just completed a real headless child turn, but the mesh roster still says dispatch.v1=false, so the broker ranks it below broken nodes and the mesh runs on less capacity than it has. Re-measure and flip the flag back, citing ~/.mesh-probe/last.json." \
        --kind mesh-health --source mesh-node-probe --priority normal 2>&1 | tail -1
      flagged=1
    fi
  done <<< "$roster_states"
  [ "$flagged" = 0 ] && echo "OK    every probed node agrees with the roster"
else
  echo "WARN  no roster at $ROSTER - measured, but nothing to compare against"
fi
