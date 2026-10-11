#!/usr/bin/env bash
# tmpfs-reaper.sh -- keep the RAM-backed /tmp from filling up and killing engines.
#
# WHY THIS EXISTS (measured 2026-10-02 on the office box, incident: phone-engine EDQUOT)
# --------------------------------------------------------------------------------------
# /tmp on secratary was `tmpfs (rw,nosuid,nodev,size=11992032k,usrquota)`. It is RAM, and it is
# quota'd. DSH's subprocess output collector spills large tool output to
# `mkdtempSync(join(os.tmpdir(), "dsh-subprocess-"))`, i.e. under /tmp. When the tmpfs user quota
# is reached, that write does not fail gracefully: it raises EDQUOT (`errno: -122`) out of a
# synchronous writeSync() inside a socket 'data' handler, which is an uncaught exception, and the
# whole engine process exits status=1.
#
# Measured: phone-engine.service died that way at 01:06:21Z and again at 02:47:52Z, taking every
# in-flight turn with it, with /tmp at 9.2 GB of 12 GB.
#
# ── WHY IT IS STILL PORTED TO THE CLOUD BOX (2026-10-11), AND WITH WHAT NUMBERS ──────────────
# The migration inventory marked this job DEAD-by-rationale ("nothing on the cloud box has that
# defect"). That reading is wrong, and it was wrong from a measurement that was never taken:
#
#     secratary-cloud: findmnt -no SOURCE,FSTYPE,SIZE,OPTIONS /tmp
#       tmpfs tmpfs 3.8G  rw,nosuid,nodev,nr_inodes=1048576,inode64,usrquota
#     secratary-cloud: df -h /tmp
#       tmpfs  3.8G  11M  3.8G  1% /tmp
#
# The cloud box's /tmp IS a RAM-backed tmpfs, IS 3.8 GB, and DOES carry `usrquota` -- the same
# three properties whose combination killed two engine processes on the office box. It is 3.2x
# SMALLER than the office one, so it fills sooner, not later. A DSH session's spilled tool output
# is on this box too. The rationale for the job is unchanged; only the numbers are.
#
# Numbers chosen for the cloud (all overridable): MIN_FREE_MB=600, TARGET_FREE_MB=1500.
# 600 MB free on a 3891 MB tmpfs is ~15%, high enough to act before a spill of a few hundred MB
# fails, low enough not to reap every run. The rescue root is on the disk-backed / (27 GB free,
# only ever holding moved bytes that the manifest can put back).
#
# WHAT IT DOES
#   * if /tmp free space is >= MIN_FREE_MB, does nothing (exit 0, one log line, no writes);
#   * otherwise MOVES the oldest entries to disk-backed storage on / (never deletes: the rescue
#     directory keeps every byte, and a manifest records what moved and where from);
#   * stops as soon as free space is back above TARGET_FREE_MB;
#   * never touches a dotfile, never touches anything modified in the last MIN_AGE_MIN minutes,
#     and never touches a path that a live process holds open.
set -u
TMP=${TMP:-/tmp}
MIN_FREE_MB=${MIN_FREE_MB:-600}     # below this, reap   (cloud: 3.8 GB tmpfs)
TARGET_FREE_MB=${TARGET_FREE_MB:-1500}
MIN_AGE_MIN=${MIN_AGE_MIN:-120}     # never reap anything touched in the last 2 hours
RESCUE_ROOT=${RESCUE_ROOT:-/root/tmp-rescue}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
RESCUE="$RESCUE_ROOT/$STAMP"
LOG="$RESCUE_ROOT/reaper.log"
mkdir -p "$RESCUE_ROOT"

free_mb() { df -Pm "$TMP" | awk 'NR==2{print $4}'; }

start=$(free_mb)
if [ "$start" -ge "$MIN_FREE_MB" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ok free=${start}MB (floor ${MIN_FREE_MB}MB) - nothing to do" >> "$LOG"
  exit 0
fi

mkdir -p "$RESCUE"
MANIFEST="$RESCUE/MANIFEST.txt"
: > "$MANIFEST"
moved=0
# oldest first, so the reaper takes the coldest scratch and leaves today's work alone
while IFS= read -r entry; do
  [ -e "$entry" ] || continue
  name=$(basename "$entry")
  case "$name" in .*) continue;; esac
  # skip anything a live process has open
  if command -v lsof >/dev/null 2>&1 && lsof -- "$entry" >/dev/null 2>&1; then
    echo "HELD   $entry" >> "$MANIFEST"; continue
  fi
  size=$(du -sm "$entry" 2>/dev/null | cut -f1)
  if mv -f "$entry" "$RESCUE/" 2>/dev/null; then
    moved=$((moved+1))
    echo "MOVED  ${size}MB  $entry" >> "$MANIFEST"
  else
    echo "FAILED $entry" >> "$MANIFEST"
  fi
  if [ "$(free_mb)" -ge "$TARGET_FREE_MB" ]; then break; fi
done < <(find "$TMP" -maxdepth 1 -mindepth 1 ! -name '.*' -mmin "+$MIN_AGE_MIN" -printf '%T@ %p\n' 2>/dev/null | sort -n | cut -d' ' -f2-)

end=$(free_mb)
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) reaped moved=$moved free=${start}MB->${end}MB rescue=$RESCUE" >> "$LOG"
echo "tmpfs-reaper: moved=$moved free=${start}MB->${end}MB"
