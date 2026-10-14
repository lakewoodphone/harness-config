#!/usr/bin/env bash
# check-autonomy-status-drift.sh -- FAIL LOUDLY when the repo's copy of autonomy-status.sh has
# drifted from the copy that actually runs on the authority.
#
# WHY THIS EXISTS (ledger item 217): two lineages of autonomy-status.sh grew apart. The repo copy
# was 13080 bytes / md5 90ec479c44f865ba1b0351de06d7104d, while the live copy on the authority
# carried fixes that were never committed. Copying the repo file over the live file reverts those
# fixes, and the same shape of mistake already cost this estate once (ledger item 163).
#
# THIS CHECK ONLY REPORTS. It never copies, never repairs, never writes anything anywhere - the
# authority is read with exactly one ssh running `md5sum` and `stat`.
#
# Exit contract -- each outcome is a DIFFERENT sentence, on purpose, because "I could not look"
# and "I looked and it is fine" are not the same answer:
#   0  IN SYNC          the repo copy and the live copy have the same md5
#   1  DRIFT            they differ (the loud failure this exists for)
#   2  USAGE            the repo copy is missing or unreadable, so nothing was compared
#   3  CANNOT MEASURE   the authority was unreachable, or answered without an md5.
#                       This is NOT "in sync" and must never be reported as health.
#
# Overrides (all optional): AUTHORITY_HOST, LIVE_PATH, REPO_PATH, SSH_TIMEOUT.
set -uo pipefail

AUTHORITY_HOST=${AUTHORITY_HOST:-secratary-cloud}
# The path the live system actually executes. On the authority, drift-check.py's
# inv_value_budget() runs `bash <DRIFT_ROOT>/autonomy-status.sh` with DRIFT_ROOT defaulting to
# /home/zabz/bin, and run-wake-sources.sh calls drift-check.py every 30 minutes. /root/bin/
# autonomy-status.sh is the same inode as this path on the authority, so measuring this one
# measures both.
LIVE_PATH=${LIVE_PATH:-/home/zabz/bin/autonomy-status.sh}
SSH_TIMEOUT=${SSH_TIMEOUT:-15}

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
REPO_PATH=${REPO_PATH:-$REPO_ROOT/scripts/wake/autonomy-status.sh}

md5_of_file() {
    if command -v md5sum >/dev/null 2>&1; then
        md5sum "$1" | awk '{print $1}'
    else
        python3 -c 'import hashlib,sys; print(hashlib.md5(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
    fi
}

say_cannot_measure() {
    # Exit 3 is deliberately distinct from 0. An unreadable authority is an UNKNOWN, and the whole
    # point of this check is that an unknown must never be printed in the same words as health.
    printf 'CANNOT MEASURE (exit 3) - %s\n' "$1" >&2
    printf '  authority : %s\n' "$AUTHORITY_HOST"
    printf '  live path : %s\n' "$LIVE_PATH"
    if [ -n "${2:-}" ]; then printf '  it said   : %s\n' "$2" >&2; fi
    printf '  NOT "in sync" - the live copy was not successfully read. This is unknown, not health.\n' >&2
    exit 3
}

if [ ! -f "$REPO_PATH" ]; then
    printf 'USAGE (exit 2) - the repo copy is missing, so nothing could be compared.\n' >&2
    printf '  expected : %s\n' "$REPO_PATH" >&2
    exit 2
fi

repo_md5=$(md5_of_file "$REPO_PATH")
if [ -z "$repo_md5" ]; then
    printf 'USAGE (exit 2) - could not hash the repo copy.\n' >&2
    printf '  path : %s\n' "$REPO_PATH" >&2
    exit 2
fi

# READ-ONLY toward the authority: one ssh, md5sum and stat, no writes anywhere.
live_out=$(ssh -o BatchMode=yes -o ConnectTimeout="$SSH_TIMEOUT" \
               "$AUTHORITY_HOST" \
               "md5sum '$LIVE_PATH' 2>/dev/null; stat -c '%s' '$LIVE_PATH' 2>/dev/null" 2>&1)
ssh_rc=$?

if [ "$ssh_rc" -ne 0 ]; then
    say_cannot_measure "the authority did not answer (ssh rc=$ssh_rc)." \
        "$(printf '%s' "$live_out" | head -3 | tr '\n' ' ')"
fi

live_md5=$(printf '%s\n' "$live_out" | grep -oE '^[0-9a-f]{32}' | head -1)
live_size=$(printf '%s\n' "$live_out" | grep -oE '^[0-9]+$' | head -1)

if [ -z "$live_md5" ]; then
    say_cannot_measure "the authority was reached but named no md5 for the live copy." \
        "$(printf '%s' "$live_out" | head -3 | tr '\n' ' ')"
fi

repo_size=$(wc -c <"$REPO_PATH" | tr -d '[:space:]')

if [ "$repo_md5" = "$live_md5" ]; then
    printf 'IN SYNC - the repo copy and the live copy are the same file.\n'
    printf '  live  : %s on %s\n' "$LIVE_PATH" "$AUTHORITY_HOST"
    printf '  md5   : %s\n' "$repo_md5"
    printf '  bytes : %s (repo) / %s (live)\n' "$repo_size" "${live_size:-unknown}"
    printf '  repo  : %s\n' "$REPO_PATH"
    exit 0
fi

printf 'DRIFT (exit 1) - the repo copy and the live copy are NOT the same file.\n' >&2
printf '  live  : %s on %s\n' "$LIVE_PATH" "$AUTHORITY_HOST" >&2
printf '            md5 %s  bytes %s\n' "$live_md5" "${live_size:-unknown}" >&2
printf '  repo  : %s\n' "$REPO_PATH" >&2
printf '            md5 %s  bytes %s\n' "$repo_md5" "$repo_size" >&2
printf '\n  DO NOT copy the repo file over the live file: that reverts live-only fixes\n' >&2
printf '  (ledger item 217; the same shape of mistake already cost this estate once, item 163).\n' >&2
printf '  Bring the LIVE content INTO the repo on a branch, then commit.\n' >&2
exit 1
