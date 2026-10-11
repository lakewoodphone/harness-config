#!/usr/bin/env bash
# =============================================================================
# guard-service-state.sh — ASK BEFORE YOU CHANGE A MACHINE'S SERVICE STATE.
#
# THE RULE THIS ENFORCES (general, not a special case):
#   Before changing the service state of ANY machine — starting, stopping,
#   masking, unmasking, enabling, disabling or restarting — find out what that
#   machine is FOR and who decided its current state.
#
# WHY, in one measured incident. 2026-10-11: an agent found `cron.service` masked
# on the office box `secratary`, read a masked unit as "something broke",
# concluded the company had been down 15 hours, and reversed a deliberate
# post-cutover freeze — `systemctl unmask cron.service cron.socket`,
# `systemctl enable --now cron`, then starting secretary-api, dialpad-sms-ws,
# secretary-dashboard and phone-engine. It then pushed ~5,129 session-event rows
# and a Dialpad SMS harvest into what was the FROZEN ROLLBACK ANCHOR, creating a
# SECOND WRITER of the company database. The freeze was deliberate, taken at the
# 05:43:36Z cutover the same day, and written down only in
# `docs/mesh/131-MIGRATION-BRIEF.md` (Rule 1: "The office box is READ-ONLY…",
# Rule 2: "Only ONE writer may exist for the company database, and it is
# `/root/authority.db` on the cloud box.") — a document that existed only on
# ZABZ-YOGA, never on the machine it governed. Full record:
# `docs/mesh/142-ANCHOR-WRITE-NOTICE.md`; standing rule: `AGENTS.md` §5.
#
# WHAT IT DOES. Given a host, it reads that host's posture from
# `settings/machines/host-posture.tsv` (a PIPE-separated file despite the .tsv
# extension — see its header for why) — a FILE, not a hardcoded list, so the
# next cutover only has to update one place — and:
#   frozen     -> REFUSES, exit 2, prints what the host is FOR, who decided it,
#                 since when, and which document to read.
#   read-only  -> REFUSES unless --owner-confirmed is passed, exit 3.
#   writable   -> ALLOWS, exit 0, and says so.
#   unknown    -> REFUSES, exit 4. An unrecognised host is not permission.
#
# USAGE
#   guard-service-state.sh --host secratary-ts --op unmask
#   guard-service-state.sh --host secratary-cloud --op restart
#   guard-service-state.sh --list                 # every designation
#   guard-service-state.sh --check-offline --host secratary   # no ssh needed (default)
#
# EXIT CONTRACT (frozen, so a dispatcher can gate on it):
#   0 allow   1 usage/environment error   2 frozen — REFUSED
#   3 read-only — REFUSED   4 host not designated — REFUSED
#
# NOTE ON SCOPE. This script never contacts the target host and never runs
# systemctl. It is a PREFLIGHT, deliberately: a guard that had to reach the box
# could not protect a box that is meant to be untouched.
# =============================================================================
set -u

PROG="$(basename "$0")"
HERE="$(cd "$(dirname "$0")" && pwd)"

# --- frozen exit contract ---------------------------------------------------
EX_USAGE=1; EX_FROZEN=2; EX_READONLY=3; EX_UNDESIGNATED=4

# The operation vocabularies the rule names, verbatim.
STATE_VERBS="start stop restart mask unmask enable disable reenable"
LIFECYCLE_VERBS="status is-active is-enabled daemon-reload list-units cat"

die() { printf '%s: %s\n' "$PROG" "$*" >&2; exit "$EX_USAGE"; }
warn() { printf '%s: %s\n' "$PROG" "$*" >&2; }

usage() {
  cat <<'U'
guard-service-state.sh — refuse-and-explain before a machine's service state is changed.

  --host <name>          REQUIRED for a check. Any ssh alias, hostname or address of the machine.
  --op <verb>            the operation you were about to perform
                         (start|stop|restart|mask|unmask|enable|disable|reenable).
                         If omitted, the guard still reports the designation and refuses
                         on a frozen host, because arriving is enough to need the answer.
  --posture <file>       override the designation file (default: the repo's
                         settings/machines/host-posture.tsv)
  --owner-confirmed      required to allow a `read-only` host; ignored for `frozen`
  --list                 print every designation and exit 0
  --quiet                only the exit code, plus refusals on stderr
  -h, --help             this text

EXIT: 0 allow · 1 usage/env · 2 FROZEN refused · 3 read-only refused · 4 host not designated
U
}

HOST=""; OP=""; POSTURE=""; OWNER_CONFIRMED=0; LIST_ONLY=0; QUIET=0

while [ $# -gt 0 ]; do
  case "$1" in
    --host) [ $# -ge 2 ] || die "--host needs a value"; HOST="$2"; shift 2 ;;
    --host=*) HOST="${1#*=}"; shift ;;
    --op) [ $# -ge 2 ] || die "--op needs a value"; OP="$2"; shift 2 ;;
    --op=*) OP="${1#*=}"; shift ;;
    --posture) [ $# -ge 2 ] || die "--posture needs a value"; POSTURE="$2"; shift 2 ;;
    --posture=*) POSTURE="${1#*=}"; shift ;;
    --owner-confirmed) OWNER_CONFIRMED=1; shift ;;
    --list) LIST_ONLY=1; shift ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
done

# --- locate the designation file --------------------------------------------
# Order: explicit --posture, $HARNESS_CONFIG_POSTURE, then the repo this script is
# installed in, then the conventional checkout paths. There is no fallback list
# of hosts anywhere in this script; if the file cannot be found the guard refuses.
find_posture() {
  if [ -n "$POSTURE" ]; then [ -f "$POSTURE" ] && { printf '%s' "$POSTURE"; return 0; }; return 1; fi
  if [ -n "${HARNESS_CONFIG_POSTURE:-}" ]; then
    [ -f "$HARNESS_CONFIG_POSTURE" ] && { printf '%s' "$HARNESS_CONFIG_POSTURE"; return 0; }; return 1
  fi
  # $HERE = <repo>/scripts/mesh
  local r; r="$(cd "$HERE/../.." 2>/dev/null && pwd)" || r=""
  local c
  for c in \
    "$r/settings/machines/host-posture.tsv" \
    "${HARNESS_CONFIG_ROOT:-}/settings/machines/host-posture.tsv" \
    "$HOME/code/harness-config/settings/machines/host-posture.tsv" \
    "$HOME/harness-config/settings/machines/host-posture.tsv" \
    "$HERE/host-posture.tsv"
  do
    [ -n "$c" ] && [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  done
  return 1
}

POSTURE_FILE="$(find_posture)" || POSTURE_FILE=""

if [ -z "$POSTURE_FILE" ]; then
  warn "REFUSED (environment): could not find settings/machines/host-posture.tsv."
  warn "That file IS the designation. Without it this host is UNDESIGNATED, and an"
  warn "undesignated host is not permission to change service state. Fix the file, then retry."
  exit "$EX_USAGE"
fi

if [ "$LIST_ONLY" -eq 1 ]; then
  printf '# host-posture designations read from %s\n' "$POSTURE_FILE"
  printf '%-22s %-11s %-22s %s\n' HOST POSTURE SINCE DECIDED
  awk -F'|' '!/^[[:space:]]*#/ && NF>=4 {k=$1; gsub(/^[[:space:]]+|[[:space:]]+$/,"",k); printf "%-22s %-11s %-22s %s\n", k, $2, $3, $4}' "$POSTURE_FILE"
  exit 0
fi

[ -n "$HOST" ] || { usage >&2; die "no --host given. This guard refuses to guess which machine you mean."; }

# exact, case-insensitive lookup — never a substring match, because `secratary`
# is a prefix of `secratary-cloud` and confusing those two is the whole incident.
row="$(awk -F'|' -v h="$HOST" '
  /^[[:space:]]*#/ { next }
  NF < 5 { next }
  { k=$1; gsub(/^[[:space:]]+|[[:space:]]+$/,"",k);
    if (tolower(k)==tolower(h)) { print; exit } }' "$POSTURE_FILE")"

if [ -z "$row" ]; then
  warn "REFUSED (undesignated host): '$HOST' is not in $POSTURE_FILE."
  warn "An unrecognised host is NOT permission to change its service state. Add its"
  warn "designation to that file first, so the next agent inherits the decision."
  exit "$EX_UNDESIGNATED"
fi

POST="$(printf '%s' "$row" | awk -F'|' '{v=$2; gsub(/[[:space:]]/,"",v); print tolower(v)}')"
SINCE="$(printf '%s' "$row" | awk -F'|' '{v=$3; gsub(/^[[:space:]]+|[[:space:]]+$/,"",v); print v}')"
DECIDED="$(printf '%s' "$row" | awk -F'|' '{print $4}')"
REASON="$(printf '%s' "$row" | awk -F'|' '{print $5}')"

op_line=""
[ -n "$OP" ] && op_line=" (you were about to: systemctl $OP $HOST)"

case "$POST" in
  frozen)
    warn ""
    warn "REFUSED — '$HOST' IS FROZEN.${op_line}"
    warn ""
    warn "  WHAT IT IS FOR : $REASON"
    warn "  WHO DECIDED    : $DECIDED"
    warn "  SINCE          : $SINCE"
    warn "  DESIGNATION    : $POST   (from $POSTURE_FILE)"
    warn ""
    warn "  A MASKED OR STOPPED UNIT ON THIS HOST IS DELIBERATE. It does not mean the"
    warn "  company is down, and it is not yours to 'restore'. Do not start, stop, mask,"
    warn "  unmask, enable, disable or restart anything here, and do not write to its"
    warn "  database. If you believe the freeze is genuinely wrong, ASK THE OWNER — the"
    warn "  answer is a decision, not a command you already have."
    warn ""
    warn "  READ FIRST: docs/mesh/131-MIGRATION-BRIEF.md (Rule 1 and Rule 2),"
    warn "              docs/mesh/142-ANCHOR-WRITE-NOTICE.md, AGENTS.md §5."
    exit "$EX_FROZEN"
    ;;
  read-only)
    if [ "$OWNER_CONFIRMED" -eq 1 ]; then
      [ "$QUIET" -eq 0 ] && printf 'ALLOW (read-only, owner-confirmed): %s — %s\n' "$HOST" "$REASON"
      exit 0
    fi
    warn ""
    warn "REFUSED — '$HOST' IS READ-ONLY.${op_line}"
    warn ""
    warn "  WHAT IT IS FOR : $REASON"
    warn "  WHO DECIDED    : $DECIDED"
    warn "  SINCE          : $SINCE"
    warn ""
    warn "  Service state here is not an agent's to change without the owner's yes in the"
    warn "  current conversation. Re-run with --owner-confirmed only once you have it."
    exit "$EX_READONLY"
    ;;
  writable)
    [ "$QUIET" -eq 0 ] && printf 'ALLOW: %s is WRITABLE. %s (decided %s: %s)\n' "$HOST" "$REASON" "$SINCE" "$DECIDED"
    exit 0
    ;;
  *)
    warn "REFUSED (bad designation): '$HOST' has posture '$POST', which is not one of frozen/read-only/writable."
    warn "Fix $POSTURE_FILE; an unreadable designation is not permission."
    exit "$EX_USAGE"
    ;;
esac
