# install-from-repo.sh — run ON the cloud authority. Copies a repo-relative file to its destination.
#
# WHY THIS EXISTS
# The manager session writes files on Windows, and Windows line endings or a BOM silently break both
# cron (`bad day-of-week` on a line that looks perfect) and shell scripts (`bad interpreter`). Measured
# 2026-10-11: a crontab fragment that had been validated locally failed to install because every line
# ended in CR. So every file the manager ships goes through here, which normalises the bytes and prints
# a digest, rather than being trusted as it arrived.
#
# Usage: install-from-repo.sh <source-file> <destination-path> [mode]
set -uo pipefail

SRC="${1:?source file}"
DST="${2:?destination path}"
MODE="${3:-0644}"

[ -f "$SRC" ] || { echo "no such source: $SRC" >&2; exit 2; }

# 1. normalise: strip CR, strip a UTF-8 BOM, ensure a trailing newline
sed -i 's/\r$//' "$SRC"
sed -i '1s/^\xEF\xBB\xBF//' "$SRC"
[ -n "$(tail -c1 "$SRC")" ] && printf '\n' >> "$SRC"

# 2. prove it: no CR anywhere, and the file is not empty
if grep -q $'\r' "$SRC"; then echo "REFUSING: $SRC still contains CR after normalisation" >&2; exit 3; fi
if [ ! -s "$SRC" ]; then echo "REFUSING: $SRC is empty" >&2; exit 3; fi

# 3. place it and report
install -m "$MODE" "$SRC" "$DST"
printf '%-52s %s bytes  sha256 %s\n' "$DST" "$(stat -c %s "$DST")" "$(sha256sum "$DST" | cut -c1-16)"
case "$DST" in
  *.sh) bash -n "$DST" && echo "   bash -n: syntax ok" ;;
  *.py) python3 -m py_compile "$DST" 2>/dev/null && echo "   py_compile: syntax ok" || echo "   WARNING: python syntax check failed" ;;
esac
