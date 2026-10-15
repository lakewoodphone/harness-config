#!/usr/bin/env bash
# check-deployed-wake-drift.sh -- fail loudly when ANY file the repo carries under
# scripts/wake/ has drifted from the copy that actually runs on the host.
#
# SUCCESSOR TO check-autonomy-status-drift.sh (ledger item 217), which compared
# exactly ONE file (autonomy-status.sh). Ledger item 221 measured that the same
# failure class covers far more than one file -- the live copies under
# /home/zabz/bin (== /root/bin, same inode) carry fixes that were never committed,
# and a repo->live sync would silently revert one lineage. This check therefore
# compares the WHOLE name-matched DEPLOYED set, recursively, and NAMES every file
# that differs.
#
# READ-ONLY, ALWAYS. It never copies, never repairs, never writes anything
# anywhere. The live root is read either locally (when this runs on the host that
# has it -- the authority cannot ssh to itself) or with exactly ONE ssh.
#
# Exit contract -- each outcome is a DIFFERENT sentence, on purpose, because
# "I could not look" and "I looked and it is fine" are not the same answer:
#   0  IN SYNC          every deployed, name-matched file has the same md5
#   1  DRIFT            at least one differs; every drifting file is named
#   2  USAGE            nothing to compare (no repo scripts/wake, or no name match)
#   3  CANNOT MEASURE   the live root could not be read (host down, ssh refused,
#                       or the answer carried no md5). This is NOT "in sync".
#
# A repo file must NEVER be copied over a live file to make this green: that
# reverts live-only fixes (ledger 217, and the same shape already cost this estate
# once as ledger 163). Bring the LIVE content INTO the repo on a branch instead.
#
# Overrides (all optional): REPO_ROOT, LIVE_ROOT, AUTHORITY_HOST, SSH_TIMEOUT,
#                           FORCE_SSH (1 = never read the live root locally)
set -uo pipefail

AUTHORITY_HOST=${AUTHORITY_HOST:-secratary-cloud}
LIVE_ROOT=${LIVE_ROOT:-/home/zabz/bin}
SSH_TIMEOUT=${SSH_TIMEOUT:-15}
FORCE_SSH=${FORCE_SSH:-0}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=${REPO_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}
WAKE_DIR="$REPO_ROOT/scripts/wake"

say_usage() {
    printf 'USAGE (exit 2) - %s\n' "$1" >&2
    printf '  repo scripts/wake : %s\n' "$WAKE_DIR" >&2
    exit 2
}

say_cannot_measure() {
    printf 'CANNOT MEASURE (exit 3) - %s\n' "$1" >&2
    printf '  live root : %s (mode=%s)\n' "$LIVE_ROOT" "$MODE" >&2
    printf '  authority : %s\n' "$AUTHORITY_HOST" >&2
    if [ -n "${2:-}" ]; then printf '  it said   : %s\n' "$2" >&2; fi
    printf '  NOT "in sync" - the live copies were not successfully read. Unknown, not health.\n' >&2
    exit 3
}

md5_of() {
    if command -v md5sum >/dev/null 2>&1; then
        md5sum "$1" | cut -d' ' -f1
    else
        python3 -c 'import hashlib,sys;print(hashlib.md5(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
    fi
}
bytes_of() { wc -c <"$1" 2>/dev/null | tr -d '[:space:]'; }

[ -d "$WAKE_DIR" ] || say_usage "no repo scripts/wake directory"

# Every regular file the repo carries under scripts/wake/, recursively, as a
# path RELATIVE to scripts/wake/. The deployed mirror keeps the same relative
# layout (scripts/wake/sources/x.py  <->  $LIVE_ROOT/sources/x.py).
NAMES=()
while IFS= read -r rel; do NAMES+=("$rel"); done < <(
    cd "$WAKE_DIR" && find . -type f 2>/dev/null | sed 's|^\./||' | LC_ALL=C sort
)
if [ "${#NAMES[@]}" -eq 0 ]; then
    say_usage "repo scripts/wake holds no regular files"
fi

if [ "$FORCE_SSH" != "1" ] && [ -d "$LIVE_ROOT" ]; then
    MODE=local
else
    MODE=ssh
fi

ROWS=""
if [ "$MODE" = local ]; then
    for n in "${NAMES[@]}"; do
        p="$LIVE_ROOT/$n"
        if [ -f "$p" ]; then
            ROWS+=$(printf '%s\t%s\t%s\n' "$n" "$(md5_of "$p")" "$(bytes_of "$p")")
            ROWS+=$'\n'
        fi
    done
else
    ROWS=$(ssh -o BatchMode=yes -o ConnectTimeout="$SSH_TIMEOUT" \
               "$AUTHORITY_HOST" bash -s -- "$LIVE_ROOT" "${NAMES[@]}" <<'REMOTE' 2>&1
live_root=$1; shift
for n in "$@"; do
    p="$live_root/$n"
    if [ -f "$p" ]; then
        printf '%s\t%s\t%s\n' "$n" "$(md5sum "$p" 2>/dev/null | cut -d' ' -f1)" "$(wc -c <"$p" 2>/dev/null | tr -d '[:space:]')"
    fi
done
REMOTE
)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        say_cannot_measure "the live root could not be read over ssh (rc=$rc)." \
            "$(printf '%s' "$ROWS" | head -3 | tr '\n' ' ')"
    fi
fi

compared=0; drift=0
DRIFT_LINES=()
for n in "${NAMES[@]}"; do
    row=$(printf '%s\n' "$ROWS" | awk -F'\t' -v k="$n" '$1==k{print; exit}')
    [ -n "$row" ] || continue                      # not deployed: not compared
    lmd5=$(printf '%s' "$row" | cut -f2)
    lbytes=$(printf '%s' "$row" | cut -f3)
    if [ -z "$lmd5" ]; then
        say_cannot_measure "the live root was read but carried no md5 for $n."
    fi
    rmd5=$(md5_of "$WAKE_DIR/$n")
    rbytes=$(bytes_of "$WAKE_DIR/$n")
    compared=$((compared+1))
    if [ "$rmd5" != "$lmd5" ]; then
        drift=$((drift+1))
        DRIFT_LINES+=("$(printf '  %-44s repo %s (%s B)  live %s (%s B)' "$n" "$rmd5" "$rbytes" "$lmd5" "$lbytes")")
    fi
done

if [ "$compared" -eq 0 ]; then
    say_usage "no repo scripts/wake file is name-matched at $LIVE_ROOT, so nothing was compared"
fi

if [ "$drift" -eq 0 ]; then
    printf 'IN SYNC - all %s deployed scripts/wake/ file(s) match the repo copy.\n' "$compared"
    printf '  live root : %s (%s)\n' "$LIVE_ROOT" "$MODE"
    printf '  repo root : %s\n' "$REPO_ROOT"
    exit 0
fi

printf 'DRIFT (exit 1) - %s of %s deployed scripts/wake/ file(s) differ from the repo copy.\n' "$drift" "$compared" >&2
printf '  live root : %s (%s)\n' "$LIVE_ROOT" "$MODE" >&2
printf '  repo root : %s\n' "$REPO_ROOT" >&2
for line in "${DRIFT_LINES[@]}"; do printf '%s\n' "$line" >&2; done
printf '\n  DO NOT copy the repo file over the live file: that reverts live-only fixes\n' >&2
printf '  (ledger items 217/221; the same shape already cost this estate once, item 163).\n' >&2
printf '  Bring the LIVE content INTO the repo on a branch, then commit.\n' >&2
exit 1
