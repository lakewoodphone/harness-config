#!/usr/bin/env bash
# install.sh -- put the estate's search subsystem on a host, from the repo that owns it.
#
# WHY THIS DIRECTION. Measured 2026-10-12: the whole search surface existed only as files on the
# office box `secratary` -- the engine in `~/bin/find-anything` (89 lines ahead of its own git ref),
# the tool body in `data/tools/search.py` (a gitignored path), and the index builder in `~/bin/`.
# The cloud authority that replaced it carried NONE of the three, so `ps_search` -- the tool the
# `fast-search` skill tells every agent to use -- answered `Tool search not found` to every caller.
# A tool that only exists on one machine is a tool with one disk. The canonical copies live in
# harness-config and this script installs them, repo -> host, the same direction
# `scripts/guards/install.sh` and `scripts/wake/sources/` already use.
#
# WHAT IT INSTALLS
#   find-anything            -> $BIN_DIR/find-anything          (the engine)
#   find-anything            -> $BIN_DIR/fa                     (symlink, the short name)
#   build-indexes.sh         -> $BIN_DIR/find-anything-build-indexes
#   search-tool.py           -> <checkout>/data/tools/search.py (the dynamic tool body)
# then registers `search` in the tool registry and builds the indexes.
#
# SAFETY
#   * sha256 compared before and after every copy; a file that does not verify fails the run.
#   * an existing file is kept as `<name>.bak-install-<timestamp>` before it is replaced.
#   * --dry-run prints every action and writes nothing.
#   * it installs FILES ONLY. Cron is a per-host decision and is listed as NOTES, never applied.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${FA_BIN_DIR:-/usr/local/bin}"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
TS="$(date -u +%Y%m%dT%H%M%SZ)"

# The checkout, resolved rather than assumed -- hardcoding this is what broke the tool once already.
CO="${FA_CHECKOUT:-$HOME/personal-secretary-mvp}"
[ -d "$CO" ] || CO="$HOME/code/personal-secretary-mvp"
[ -d "$CO" ] || CO=/opt/company

sha() { sha256sum "$1" 2>/dev/null | cut -c1-16; }

install_one() {
  local from="$1" to="$2" mode="${3:-0755}"
  [ -f "$from" ] || { echo "  MISSING IN REPO: $from"; return 1; }
  if [ -f "$to" ] && [ "$(sha "$from")" = "$(sha "$to")" ]; then
    printf "  = %-34s already current (%s)\n" "$(basename "$to")" "$(sha "$to")"
    return 0
  fi
  if (( DRY )); then
    printf "  + %-34s would install (%s)\n" "$(basename "$to")" "$(sha "$from")"
    return 0
  fi
  mkdir -p "$(dirname "$to")"
  [ -f "$to" ] && cp -p "$to" "$to.bak-install-$TS"
  cp -p "$from" "$to"
  chmod "$mode" "$to" 2>/dev/null || true
  # LF IS NOT OPTIONAL for anything with a shebang: a CR turns every line into
  # "$'\r': command not found" on Linux (journal P264).
  sed -i 's/\r$//' "$to" 2>/dev/null || true
  if [ "$(sha "$from")" = "$(sha "$to")" ]; then
    printf "  + %-34s installed (%s)\n" "$(basename "$to")" "$(sha "$to")"
  else
    printf "  ! %-34s FAILED VERIFICATION: %s -> %s\n" "$(basename "$to")" "$(sha "$from")" "$(sha "$to")"
    return 1
  fi
}

echo "search subsystem from $HERE"
echo "  engine -> $BIN_DIR"
echo "  tool   -> $CO/data/tools/"
rc=0
install_one "$HERE/find-anything"     "$BIN_DIR/find-anything"                  0755 || rc=1
install_one "$HERE/build-indexes.sh"  "$BIN_DIR/find-anything-build-indexes"   0755 || rc=1
install_one "$HERE/search-tool.py"    "$CO/data/tools/search.py"               0644 || rc=1

if (( DRY )); then
  echo "  (dry run: not creating the symlink, not registering, not building indexes)"
  exit "$rc"
fi

ln -sfn "$BIN_DIR/find-anything" "$BIN_DIR/fa"
echo "  + fa -> $BIN_DIR/find-anything"

# Register `search` so it is DISCOVERABLE, not merely callable. An unregistered tool is invisible
# to every agent that has not been told its name by hand.
PY="$CO/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
if [ -x "$PY" ] && [ -f "$HERE/register-search-tool.py" ]; then
  if (cd "$CO" && "$PY" "$HERE/register-search-tool.py"); then
    :
  else
    echo "  ! could not register 'search' -- the tool will work by name but stay undiscoverable"
    rc=1
  fi
fi

echo
echo "build the indexes:"
if [ -x "$BIN_DIR/find-anything-build-indexes" ]; then
  "$BIN_DIR/find-anything-build-indexes" | sed 's/^/  /' || rc=1
fi

echo
echo "verify:"
echo "  $BIN_DIR/fa stats"
echo "  $BIN_DIR/fa files <name> ; $BIN_DIR/fa symbol <name> ; $BIN_DIR/fa journal <words> ; $BIN_DIR/fa data <words>"

cat <<'NOTES'

NOT APPLIED HERE, on purpose -- cron is a per-host decision. On the host that owns the indexes
(secratary-cloud), install these two with install-crontab-fragment.sh:

  */15 * * * * /usr/local/bin/cron-wrap.sh fa-index-refresh /usr/local/bin/find-anything-build-indexes
  22 * * * *   /usr/local/bin/cron-wrap.sh fa-index-freshness /usr/local/bin/check-faindex-freshness

The first keeps the path, symbol and journal indexes current. The second is the CLOCK GUARD: this
estate has twice shipped a search index whose refresh was silently dead while every surface still
called it "scheduled" (journal P2899 D2 -- a trigger whose repetition pattern expired after one day;
H3376 -- 21 days stale, NextRunTime empty). A freshness checker that only prints is worth nothing;
the one shipped beside this installer exits non-zero, which cron-wrap.sh records in
~/.cron-status/runs.tsv.

Never install these from a copy in ~/bin. This script is the installer; the repo is the source.
NOTES

exit "$rc"
