#!/usr/bin/env bash
# deploy-integrator.sh -- install the work-integrator scanner from the repo, and prove it.
#
# WHY THIS EXISTS (ledger item 1268, measured 2026-10-25): /root/bin/work-integrator.py grew to
# 43,672 bytes by in-place edits while the repo copy at scripts/wake/work-integrator.py sat at the
# 2026-10-22 state (41,961 bytes). Item 1265 fixed the scanner in the live file only, so a deploy
# from the repo would silently revert the done_titles guard. The scanner is cron-driven and has no
# build step; a deploy has to be one command that (a) refuses a source that does not compile,
# (b) keeps a backup, and (c) leaves the live file byte-identical to the repo.
#
#   deploy-integrator.sh                  check only (default): compare repo copy with live
#   deploy-integrator.sh --apply          compile, back up, install, verify sha256
#   deploy-integrator.sh --src F --dst G  override paths (defaults below)
#
# Exit: 0 in sync / deployed; 1 drift in --check; 2 refused (missing or uncompilable source).
# It never touches a crontab, never restarts anything, and never deletes a backup.
set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/work-integrator.py"
DST="/root/bin/work-integrator.py"
APPLY=0

usage() { awk 'NR>1 { if (/^#/) { sub(/^# ?/, ""); print; next } else { exit } }' "${BASH_SOURCE[0]}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --check) APPLY=0; shift ;;
    --apply) APPLY=1; shift ;;
    --src) SRC="${2:?--src needs a path}"; shift 2 ;;
    --dst) DST="${2:?--dst needs a path}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done

[ -f "$SRC" ] || { echo "REFUSED: source not found: $SRC" >&2; exit 2; }

# Compile before anything is written. An unparseable scanner would break the hourly pass
# silently, and a sha256 match after install would still "prove" the deploy.
TMPC="$(mktemp -d)" || { echo "REFUSED: cannot create a temp dir" >&2; exit 2; }
trap 'rm -rf "$TMPC"' EXIT
if ! python3 -c 'import py_compile,sys; py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)' \
      "$SRC" "$TMPC/wi.pyc"; then
  echo "REFUSED: source does not compile: $SRC" >&2
  exit 2
fi

src_sha="$(sha256sum "$SRC" | cut -d' ' -f1)"
live_sha=""
[ -f "$DST" ] && live_sha="$(sha256sum "$DST" | cut -d' ' -f1)"

echo "source: $SRC"
echo "live  : $DST"
echo "source_sha256=$src_sha"
echo "live_sha256=${live_sha:-ABSENT}"

if [ "$APPLY" -eq 0 ]; then
  if [ -n "$live_sha" ] && [ "$src_sha" = "$live_sha" ]; then
    echo "RESULT: IN-SYNC - the live scanner is byte-identical to the repo copy."
    exit 0
  fi
  echo "RESULT: DRIFT - the live scanner differs from the repo copy; run --apply to install the repo copy." >&2
  exit 1
fi

if [ -n "$live_sha" ] && [ "$src_sha" = "$live_sha" ]; then
  echo "RESULT: ALREADY IN-SYNC - nothing to install, no backup written."
  exit 0
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [ -n "$live_sha" ]; then
  BAK="$DST.bak-deploy-$STAMP"
  cp -p "$DST" "$BAK" || { echo "REFUSED: backup failed: $BAK" >&2; exit 2; }
  echo "backup=$BAK"
fi

install -m 0644 "$SRC" "$DST" || { echo "FAILED: install failed" >&2; exit 2; }
new_sha="$(sha256sum "$DST" | cut -d' ' -f1)"
if [ "$new_sha" != "$src_sha" ]; then
  echo "FAILED: post-install sha256 $new_sha != source $src_sha" >&2
  exit 2
fi
echo "installed_sha256=$new_sha"
echo "RESULT: DEPLOYED - the live scanner is byte-identical to the repo copy."
