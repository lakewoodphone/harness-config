#!/usr/bin/env bash
# 04-acceptance.sh -- the final sweep: are the guards green, the clocks installed and recording, and
# every mode working? This is the script that produced section 4 of docs/mesh/171.
#
# It is the only script in this directory that lets anything write, and only the product's own guards
# (each writes a small status file under $HOME). No service state, crontab or database is touched.
set -uo pipefail

H="${HOME:-/root}"
CO="${FA_CHECKOUT:-$H/personal-secretary-mvp}"; [ -d "$CO" ] || CO="$H/code/personal-secretary-mvp"; [ -d "$CO" ] || CO=/opt/company
IDX="${FAINDEX:-$H/.faindex}"
GUARD="$H/bin/tool-body-guard.py"; [ -f "$GUARD" ] || GUARD=/root/bin/tool-body-guard.py
FRESH=/usr/local/bin/check-faindex-freshness
FA=/usr/local/bin/find-anything; [ -x "$FA" ] || FA="$(command -v fa 2>/dev/null)"

echo "############ 1. the clocks: installed, and have they FIRED? ############"
crontab -l 2>/dev/null | grep -E 'fa-index-refresh|fa-index-freshness|tool-body-guard' | sed 's/^/  /' \
  || echo "  (none installed -- see scripts/find-anything/make-crontab-fragment.sh)"
echo
echo "  --- the run ledger: did they actually run? a job that never runs looks identical to a job with nothing to say ---"
for j in fa-index-refresh fa-index-freshness tool-body-guard; do
  line=$(grep -h "$j" "$H/.cron-status/runs.tsv" 2>/dev/null | tail -1)
  printf '  %-20s %s\n' "$j" "${line:-NOT IN THE LEDGER YET}"
done

echo
echo "############ 2. the tool-body guard (every ACTIVE tool must have an implementation) ############"
if [ -f "$GUARD" ]; then
  python3 "$GUARD"; echo "  guard exit=$? (0 = ok, 1 = missing bodies, 2 = COULD NOT CHECK)"
else
  echo "  guard not installed at $GUARD -- install with scripts/guards/install.sh"
fi
echo
echo "  --- and it can fail: the selftest must PASS ---"
[ -f "$GUARD" ] && python3 "$GUARD" --selftest | tail -5

echo
echo "############ 3. the freshness clock guard (a refresh job cannot report that it stopped) ############"
if [ -x "$FRESH" ]; then
  "$FRESH"; echo "  freshness exit=$?"
else
  echo "  not installed at $FRESH"
fi

echo
echo "############ 4. every mode, exit code + latency, fresh process ############"
if [ -x "$FA" ]; then
  for pair in "files:database.py" "symbol:create_task" "code:_owner_sms_allowed" \
              "journal:cloud migration secretary" "data:battery" "auto:battery"; do
    m="${pair%%:*}"; q="${pair#*:}"
    t0=$(date +%s%N); out=$("$FA" "$m" "$q" --limit 2 --json 2>&1); rc=$?; t1=$(date +%s%N)
    printf '  %-8s %-30s rc=%-2s %6s ms  %s\n' "$m" "\"$q\"" "$rc" "$(( (t1-t0)/1000000 ))" \
      "$(printf '%s' "$out" | head -c 78 | tr '\n' ' ')"
  done
fi

echo
echo "############ 5. the registered entry (discoverable, not merely callable) ############"
if [ -f "$CO/data/tool_registry.json" ]; then
  python3 - "$CO" <<'PY'
import json, sys
root = sys.argv[1]
r = json.load(open(f"{root}/data/tool_registry.json"))
t = r.get("tools", {}).get("search")
print("  search:", ("registered | status %s | version %s | file %s" %
      (t["status"], t.get("version"), t.get("file"))) if t else "MISSING FROM THE REGISTRY")
print("  registry total:", len(r.get("tools", {})))
PY
fi

echo
echo "############ 6. the journal's own health check ############"
JC="${FA_HARNESS_CONFIG:-$H/code/harness-config}"; [ -d "$JC" ] || JC="$H/harness-config"
if [ -f "$JC/journal/tools/journal.py" ]; then
  python3 "$JC/journal/tools/journal.py" check 2>&1 | tail -2
  echo "  check exit=${PIPESTATUS[0]} (non-zero only on a REAL error: duplicate id, malformed entry, sha mismatch)"
fi
exit 0
