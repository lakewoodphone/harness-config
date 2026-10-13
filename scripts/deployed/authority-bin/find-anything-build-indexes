#!/usr/bin/env bash
# Build the per-machine path + symbol indexes that make `fa files` and `fa symbols` split-second,
# per S1's design: a prebuilt path list for filenames, ctags for symbols, ripgrep for content.
# Also rebuilds the journal index, because nothing else owns "keep the search indexes fresh".
#
# PORTABILITY. This script used to resolve `$H/harness-config`, which is not where harness-config
# lives on any node (it is `$H/code/harness-config`), so the journal step and one code root were
# silently skipped everywhere it ran. It now resolves both estate roots, with env overrides, exactly
# as `find-anything` does. Measured 2026-10-12 on secratary-cloud: the checkout is /opt/company and
# harness-config is $HOME/code/harness-config.
set -u
H="${HOME:-/home/zabz}"
IDX="${FAINDEX:-$H/.faindex}"
CO="${FA_CHECKOUT:-$H/personal-secretary-mvp}"; [ -d "$CO" ] || CO=/opt/company
HC="${FA_HARNESS_CONFIG:-$H/code/harness-config}"; [ -d "$HC" ] || HC="$H/harness-config"
mkdir -p "$IDX"

echo "=== 0. layout ==="
echo "  index:    $IDX"
echo "  checkout: $CO"
echo "  harness:  $HC"

echo
echo "=== 1. the tooling ==="
# Installing an OS package is a side effect, so it is opt-in and never silent. Before this, the
# script called `sudo apt-get install -y universal-ctags` on every run and reported nothing about it.
if command -v ctags >/dev/null 2>&1; then
  echo -n "  ctags: "; ctags --version 2>/dev/null | head -1
elif [ "${FA_INSTALL_CTAGS:-0}" = 1 ]; then
  echo "  ctags: absent -- installing (FA_INSTALL_CTAGS=1)"
  (command -v sudo >/dev/null 2>&1 && sudo apt-get install -y universal-ctags \
     || apt-get install -y universal-ctags) >/dev/null 2>&1
  command -v ctags >/dev/null 2>&1 && echo "  ctags: installed" || echo "  ctags: STILL ABSENT"
else
  echo "  ctags: ABSENT - the symbol index will be skipped (set FA_INSTALL_CTAGS=1 to install)."
  echo "         'fa symbol' is unaffected: it is a live scan and never uses this index."
fi

echo
echo "=== 2. the code roots (tracked-ish code only, never data/ or node_modules) ==="
ROOTS=()
for d in "$CO/app" "$CO/scripts" "$CO/tests" \
         "$HC/scripts" "$HC/journal/tools" "$H/bin" "$H/code"; do
  [ -d "$d" ] && ROOTS+=("$d")
done
if [ "${#ROOTS[@]}" -eq 0 ]; then
  echo "  NO ROOTS RESOLVED - refusing to write an empty index over a good one." >&2
  exit 4
fi
printf '  %s\n' "${ROOTS[@]}"
echo "  roots: ${#ROOTS[@]}"

echo
echo "=== 3. PATH INDEX (S1: 6.4 s to build, 48-117 ms to query, vs 6,412 ms to re-walk) ==="
S=$(date +%s%N)
# Write to a temp file and move only on success, so a killed run never leaves a half-written
# index that `fa files` would happily answer from.
find "${ROOTS[@]}" -type f \
  -not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/.venv/*' \
  -not -path '*/__pycache__/*' -not -path '*/data/*' -not -path '*/dist/*' \
  -not -path '*/.next/*' -not -path '*/build/*' -not -path '*/backups/*' \
  2>/dev/null > "$IDX/paths.txt.tmp"
E=$(date +%s%N)
if [ -s "$IDX/paths.txt.tmp" ]; then
  mv "$IDX/paths.txt.tmp" "$IDX/paths.txt"
  echo "  paths: $(wc -l < "$IDX/paths.txt")  in $(( (E-S)/1000000 )) ms  ($(du -h "$IDX/paths.txt" | cut -f1))"
else
  rm -f "$IDX/paths.txt.tmp"
  echo "  paths: EMPTY RESULT - kept the previous index in place" >&2
fi

echo
echo "=== 4. SYMBOL INDEX (universal-ctags over the same roots) ==="
if command -v ctags >/dev/null 2>&1; then
  S=$(date +%s%N)
  ctags -f "$IDX/tags.tmp" --languages=Python,JavaScript,TypeScript,Bash,Shell,Go,Java,Kotlin \
        --extras=+q --fields=+n -R "${ROOTS[@]}" 2>/dev/null
  E=$(date +%s%N)
  if [ -s "$IDX/tags.tmp" ]; then
    mv "$IDX/tags.tmp" "$IDX/tags"
    echo "  symbols: $(grep -vc '^!' "$IDX/tags")  in $(( (E-S)/1000000 )) ms  ($(du -h "$IDX/tags" | cut -f1))"
  else
    rm -f "$IDX/tags.tmp"
    echo "  ctags produced nothing - kept the previous index in place" >&2
  fi
else
  echo "  skipped - ctags absent"
fi

echo
echo "=== 5. STAMP so staleness is measurable ==="
date -u +%Y-%m-%dT%H:%M:%SZ > "$IDX/built_at.txt"
echo "  built_at: $(cat "$IDX/built_at.txt")"
ls -la "$IDX"

echo
echo "=== 6. PROVE the query speed against the index ==="
if [ -s "$IDX/paths.txt" ]; then
  S=$(date +%s%N); grep -i "database.py" "$IDX/paths.txt" | head -3 >/dev/null; E=$(date +%s%N)
  echo "  path query on the index : $(( (E-S)/1000000 )) ms"
  S=$(date +%s%N); find "${ROOTS[@]}" -name "database.py" -not -path '*/.git/*' 2>/dev/null | head -3 >/dev/null; E=$(date +%s%N)
  echo "  same query by re-walking: $(( (E-S)/1000000 )) ms"
fi
if [ -s "$IDX/tags" ]; then
  S=$(date +%s%N); grep -P "\tdef\b|\tclass\b" "$IDX/tags" | grep -m3 "owner" >/dev/null; E=$(date +%s%N)
  echo "  symbol query on the index: $(( (E-S)/1000000 )) ms"
fi

echo
echo "=== 7. JOURNAL INDEX (what \`fa journal\` reads) ==="
# WHY THIS LIVES HERE. Nothing rebuilt this index. Measured 2026-10-08: the authority's journal
# index was last written 62 minutes earlier by hand, while `fa journal` reported its age and
# answered from it -- tool and index both installed, neither on a clock. This service already owns
# "keep the search indexes fresh", so the journal's index belongs in it. 0.37 s measured, against
# 15 minutes of tolerance.
JTOOL="$HC/journal/tools/journal.py"
JIDX="$HC/journal/index"
if [ -f "$JTOOL" ]; then
  S=$(date +%s%N)
  if timeout 120 python3 "$JTOOL" status --quiet >/tmp/fa-journal-index.log 2>&1; then
    E=$(date +%s%N)
    N=0; NEWEST="?"
    if [ -f "$JIDX/entries.tsv" ]; then
      N=$(tail -n +2 "$JIDX/entries.tsv" | wc -l)
      NEWEST=$(tail -n +2 "$JIDX/entries.tsv" | cut -f5 | sort | tail -1)
    fi
    echo "  journal index: ok in $(( (E-S)/1000000 )) ms, ${N} entries, newest ${NEWEST}"
  else
    echo "  journal index: FAILED (exit $?) -- see /tmp/fa-journal-index.log"
  fi
else
  echo "  journal index: tool absent at $JTOOL"
fi
