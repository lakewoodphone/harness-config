#!/usr/bin/env bash
#
# Anti-drift check for the deployed mesh broker. Read-only; exits non-zero on any difference.
#
#   bash deploy/verify-deploy.sh [SOURCE_DIR]
#
# WHY THIS EXISTS. The deployed broker is a COPY of `packages/mesh-broker/**`, because pinning a
# running service's ExecStart at a git working tree that other streams branch and merge underneath
# it is how a service starts running code nobody chose. A copy has exactly one failure mode -
# silent drift - so the copy is hashed, the manifest lives beside it (PROVENANCE.md), and this
# script re-hashes both sides and names every file that differs. Stream S5 lost an hour to a
# deploy that "succeeded" while changing nothing (docs/mesh/76-broker.md §6.4); this is the
# mechanism that makes that impossible to repeat.
#
# It also checks the two things a copy cannot show: that the INSTALLED unit matches the one in the
# tree, and that the RUNNING process was started from the deployed path.

set -uo pipefail

DEST=/home/zabz/mesh-broker
UNIT=/etc/systemd/system/mesh-broker.service
SERVICE=mesh-broker
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="${1:-$(cd "$SCRIPT_DIR/.." && pwd)}"
FILES="bin lib nodes.json package.json deploy"

fail=0
printf 'source : %s\n' "$SRC"
printf 'deployed: %s\n' "$DEST"
printf 'at      : %s\n\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

for tree in "$SRC" "$DEST"; do
  if [ ! -d "$tree" ]; then echo "MISSING TREE: $tree"; fail=1; fi
done
[ "$fail" -eq 0 ] || exit 1

for f in $(cd "$SRC" && find $FILES -type f | sort); do
  if [ ! -f "$DEST/$f" ]; then printf 'MISSING IN DEPLOY  %s\n' "$f"; fail=1; continue; fi
  a=$(sha256sum "$SRC/$f" | cut -d' ' -f1)
  b=$(sha256sum "$DEST/$f" | cut -d' ' -f1)
  if [ "$a" = "$b" ]; then printf 'same    %s\n' "$f"; else printf 'DIFFERS %s\n        source   %s\n        deployed %s\n' "$f" "$a" "$b"; fail=1; fi
done
for f in $(cd "$DEST" && find $FILES -type f | sort); do
  [ -f "$SRC/$f" ] || { printf 'EXTRA IN DEPLOY (not in the source tree): %s\n' "$f"; fail=1; }
done

if [ -f "$UNIT" ]; then
  a=$(sha256sum "$SRC/deploy/mesh-broker.service" | cut -d' ' -f1)
  b=$(sha256sum "$UNIT" | cut -d' ' -f1)
  if [ "$a" = "$b" ]; then printf 'same    %s (installed unit)\n' "deploy/mesh-broker.service"; else printf 'DIFFERS the INSTALLED unit %s\n        tree     %s\n        installed %s\n' "$UNIT" "$a" "$b"; fail=1; fi
else
  printf 'the unit is NOT installed at %s\n' "$UNIT"; fail=1
fi

if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
  main=$(systemctl show -p MainPID --value "$SERVICE")
  exe=$(tr '\0' ' ' < "/proc/$main/cmdline" 2>/dev/null)
  printf 'running : pid %s: %s\n' "$main" "$exe"
  case "$exe" in *"$DEST/bin/mesh-broker.mjs"*) printf 'same    the running process IS the deployed copy\n' ;;
    *) printf 'DIFFERS the running process is NOT %s/bin/mesh-broker.mjs\n' "$DEST"; fail=1 ;; esac
else
  printf 'the service is NOT active\n'; fail=1
fi

echo
if [ "$fail" -eq 0 ]; then echo "NO DRIFT: the deployed tree, the installed unit and the running process all agree."; else echo "DRIFT OR MISSING PIECE - see the lines above."; fi
exit "$fail"
