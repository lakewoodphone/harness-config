#!/usr/bin/env bash
# 03-modes.sh -- exercise EVERY engine mode, in a fresh process, and report the exit code.
#
# WHY THE EXIT CODE AND NOT THE OUTPUT. The engine's contract is:
#     0 hits | 1 a real negative | 2 bad usage | 3 answered but possibly stale | 4 NOTHING was searched
#     | 5 the index failed
# Measured 2026-10-08 (journal L3359/L3388): three of eight modes used to exit 0 on a genuine
# no-match, and the MCP wrapper read only exit 3, so a REFUSAL (4/5) reached agents as
# `ok:true "(no hits)"`. Reading the prose instead of the code is how a search tool lies.
#
# It also checks that a word equal to a mode name is not eaten as a mode, and that --json parses
# wherever it is advertised (files emits one object per line by design; the rest emit one object).
#
# READ-ONLY.
set -uo pipefail

FA="${FIND_ANYTHING_BIN:-}"
if [ -z "$FA" ]; then
  for c in "$(command -v fa 2>/dev/null)" "$(command -v find-anything 2>/dev/null)" \
           /usr/local/bin/find-anything "$HOME/bin/find-anything"; do
    [ -n "$c" ] && [ -x "$c" ] && { FA="$c"; break; }
  done
fi
if [ -z "$FA" ]; then
  echo "03-modes: no engine found (set FIND_ANYTHING_BIN, or put fa on PATH). NOTHING was tested." >&2
  exit 4
fi

echo "node:   $(hostname)"
echo "engine: $FA  sha256 $(sha256sum "$FA" 2>/dev/null | cut -c1-16)"
echo

run() { # label arg...
  local label="$1"; shift
  local t0 t1 rc out
  t0=$(date +%s%N); out=$("$FA" "$@" 2>&1); rc=$?; t1=$(date +%s%N)
  printf '  %-38s rc=%-2s %6s ms  %s\n' "$label" "$rc" "$(( (t1-t0)/1000000 ))" \
    "$(printf '%s' "$out" | head -1 | cut -c1-88)"
}

echo "=== positive cases (expect rc=0) ==="
run 'files  database.py'          files  database.py
run 'symbol create_task'          symbol create_task
run 'code   _owner_sms_allowed'   code   _owner_sms_allowed
run 'journal lock'                journal journal
run 'data   battery'              data   battery
echo
echo "=== REAL NEGATIVES -- a term that cannot exist (expect rc=1, NOT 4) ==="
run 'files  zzqq_no_such_file'    files  zzqq-no-such-file-9931
run 'symbol zzqq_no_such_symbol'  symbol zzqq_no_such_symbol_9931
run 'code   zzqq_no_such_term'    code   zzqq-no-such-term-9931
run 'journal zzqq_no_such_term'   journal zzqq-no-such-term-9931
echo "  (rc=4 here would mean NOTHING WAS SEARCHED -- a refusal, and a different answer entirely)"
echo
echo "=== a word that equals a mode name must survive as a QUERY ==="
run 'code journal --limit 1'      code   journal --limit 1
echo
echo "=== --json must parse wherever it is advertised ==="
for pair in "files:database.py" "symbol:run" "code:_owner_sms_allowed" "journal:journal" "data:battery"; do
  m="${pair%%:*}"; q="${pair#*:}"
  res=$("$FA" "$m" "$q" --json 2>/dev/null)
  if [ "$m" = files ]; then
    # documented: `files` emits ONE OBJECT PER LINE
    if printf '%s\n' "$res" | head -1 | python3 -c 'import json,sys; json.loads(sys.stdin.readline())' 2>/dev/null; then
      echo "  files   --json: VALID (one object per line, as documented)"
    else echo "  files   --json: NOT PARSEABLE"; fi
  else
    if printf '%s' "$res" | python3 -c 'import json,sys; json.loads(sys.stdin.read())' 2>/dev/null; then
      echo "  $m --json: VALID ($(printf '%s' "$res" | wc -c) bytes)"
    else echo "  $m --json: NOT PARSEABLE"; fi
  fi
done
echo
echo "=== staleness must be able to say so (rc=3), not be silent ==="
"$FA" symbols create_task >/dev/null 2>&1
rc=$?
case "$rc" in
  0) echo "  symbols: rc=0 (ctags index present and fresh)";;
  3) echo "  symbols: rc=3 STALE -- the correct third answer, not a lie";;
  4) echo "  symbols: rc=4 NO ctags index -- a refusal, correctly distinguished from 'no match'";;
  *) echo "  symbols: rc=$rc (see the engine's contract)";;
esac
echo
echo "=== the engine's own ledger ==="
"$FA" stats 2>&1 | head -12
exit 0
