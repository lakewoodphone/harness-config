#!/usr/bin/env bash
# 01-survey.sh -- what search actually exists on THIS node, with provenance.
#
# Answers, in one pass and without assuming any machine's layout:
#   * is the engine / rg / ctags / usearch / comms-search present, and where does each resolve to?
#   * which search indexes exist, how big, and how old (mtime, UTC)?
#   * is there a scheduled refresh, and is the freshness guard installed?
#   * where is the checkout and the harness-config root on this node?
#
# READ-ONLY. It starts nothing, changes nothing.
#
# Why this exists: at the cloud cutover the authority "had" a search system in every register and
# inventory, and had no engine, no index and no schedule (docs/mesh/171 section R2). A survey that
# asks the machine rather than the inventory is the only kind that catches that.
set -uo pipefail

H="${HOME:-/root}"
CO="${FA_CHECKOUT:-$H/personal-secretary-mvp}"; [ -d "$CO" ] || CO="$H/code/personal-secretary-mvp"; [ -d "$CO" ] || CO=/opt/company
HC="${FA_HARNESS_CONFIG:-$H/code/harness-config}"; [ -d "$HC" ] || HC="$H/harness-config"
IDX="${FAINDEX:-$H/.faindex}"

echo "=== node ==="
echo "  hostname : $(hostname)"
echo "  uptime   : $(uptime 2>/dev/null | sed 's/^ *//')"
echo "  checkout : $CO$( [ -d "$CO" ] && echo "  -> $(readlink -f "$CO")" || echo "  (ABSENT)")"
echo "  harness  : $HC$( [ -d "$HC" ] && echo "" || echo "  (ABSENT)")"
echo "  index dir: $IDX$( [ -d "$IDX" ] && echo "" || echo "  (ABSENT)")"
if [ -d "$HC/.git" ]; then
  echo "  harness HEAD: $(git -C "$HC" log --oneline -1 2>/dev/null)"
fi

echo
echo "=== binaries ==="
for b in fa find-anything fa-estate usearch rg ctags; do
  p=$(command -v "$b" 2>/dev/null)
  if [ -n "$p" ]; then printf '  PRESENT %-14s -> %s\n' "$b" "$(readlink -f "$p" 2>/dev/null || echo "$p")"
  else printf '  ABSENT  %-14s\n' "$b"; fi
done
for p in /usr/local/bin/find-anything-build-indexes /usr/local/bin/check-faindex-freshness "$H/bin/tool-body-guard.py"; do
  [ -x "$p" ] && echo "  PRESENT guard/builder -> $p"
done

echo
echo "=== indexes (size, and age in UTC -- a file mtime is not content freshness, but it is the clock) ==="
show() { # label path
  if [ -e "$2" ]; then
    printf '  %-16s %14s B  %s  %s\n' "$1" "$(stat -c %s "$2" 2>/dev/null)" \
      "$(date -r "$2" -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" "$2"
  else printf '  %-16s ABSENT     %s\n' "$1" "$2"; fi
}
show paths   "$IDX/paths.txt"
show tags    "$IDX/tags"
show built   "$IDX/built_at.txt"
show comms   "$H/.fsearch/comms.db"
show usearch "$H/.usearch/usearch.db"
show jrn-idx "$HC/journal/index/journal.db"
show jrn-tsv "$HC/journal/index/entries.tsv"
if [ -f "$HC/journal/index/entries.tsv" ]; then
  echo "  journal entries indexed: $(( $(wc -l < "$HC/journal/index/entries.tsv") - 1 ))"
  echo "  journal entries on disk: $(find "$HC/journal/entries" -name '*.md' 2>/dev/null | wc -l)"
fi

echo
echo "=== scheduled refresh ==="
crontab -l 2>/dev/null | grep -Ei 'fa-index|find-anything|faindex|comms-refresh|tool-body|journal-commit' | sed 's/^/  cron: /' || echo "  (no matching cron lines, or no crontab)"
systemctl list-timers --all --no-pager 2>/dev/null | grep -Ei 'fa-index|faindex|search' | sed 's/^/  timer: /' || true

echo
echo "=== verdict ==="
missing=0
command -v fa >/dev/null 2>&1 || { echo "  engine (fa/find-anything) is NOT installed -- every ps_search call on this node will refuse"; missing=1; }
[ -d "$IDX" ] || { echo "  no index directory at $IDX -- run find-anything-build-indexes"; missing=1; }
[ "$missing" = 0 ] && echo "  engine present and an index directory exists -- run 03-modes.sh to prove the modes answer."
exit 0
