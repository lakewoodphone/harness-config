#!/bin/bash
# mesh-hygiene.sh -- the node hygiene policy and its drift report, for a Linux or macOS mesh worker.
#
# OWNER: stream O4 of the overnight program (docs/mesh/81-overnight-program.md section 1).
# DOC:   docs/mesh/85-hygiene.md.   WINDOWS SIBLING: scripts/mesh-hygiene.ps1 (same modes, same JSON
#        RECORD SHAPE, so one reader and one drift series format cover every node).
# MODEL: docs/mesh/80-mac-worker-hygiene.md -- the Mac mini's reclaim policy, generalised here and
#        extended with the drift report.
#
# THE PROBLEM, IN THE OWNER'S OWN WORDS (2026-09-16):
#   "macs don't close down processes like on Windows -- when I X things out they are still running"
# On the Mac mini that produced thirteen orphaned `Tailscale` CLI probes of our own making burning
# ~0.8 of a core for 32 hours (docs/mesh/74-mac-mini.md section 4), and a free-memory floor of
# 111-148 MB that made the node silently unplaceable. The broker reads memory honestly, so a node
# that drifts is simply not chosen and nobody is told why. This script reclaims what is ours to
# reclaim and -- the more valuable half -- writes a per-node DRIFT series so the slide is visible
# BEFORE the node stops being chosen.
#
# TWO RECLAIM CLASSES, AND NOTHING ELSE IS EVER ELIGIBLE.
#   CLASS A -- applications on an EXPLICIT target list, matched by the process's own EXECUTABLE PATH
#              (a directory prefix: an .app bundle on macOS, an install prefix on Linux). Only
#              processes belonging to the CONSOLE USER are eligible.
#   CLASS B -- ORPHANS of our own tooling: the parent is gone (ppid 1, or a ppid that is not in the
#              table), the command line matches one of OUR tool entry points, the process is older
#              than the age floor, and it holds no LISTENING socket.
#
# THE THREE GATES (81 section 1): no console user active; no dispatch in flight
# (`dsh ... --profile headless`); no unexpired admission-governor lease. Extra guards, each measured
# on a real node: the engine, anything invoked with --listen-port/--engine-port, and `tailscaled`
# are never candidates; a process holding a listening socket is never a candidate (the Mac mini's
# own gate is parentless by design). If a console session exists but its idle time CANNOT be
# measured here, the script DECLINES: an unmeasurable idle time is never read as idle.
#
# THE THREE COUNTERS (in every record)
#   avail_mib          -- THE CAPACITY CONTRACT'S NUMBER, the same definition the gate uses
#                         (scripts/phone-gate.py _memory_bytes()): Linux = /proc/meminfo
#                         MemAvailable; macOS = vm_stat (Pages free + inactive + speculative +
#                         purgeable) x hw.pagesize. NOT `Pages free`, which reads as critical on a
#                         Mac that is merely caching (docs/mesh/74 section 3.1).
#   reclaimable_rss_kb -- bytes held by processes this policy may reclaim right now.
#   placeable_children -- the broker's frozen formula reproduced (71 s2.2): memorySlots =
#                         min(floor((availMiB - 3885)/160), 24) - governor.inUse; coreSlots =
#                         floor(physicalCores x 0.75); slots = min(...); swap >= 90% halves it.
#                         The disk and transport terms are NOT in it, and the record says so.
#
# A LOG LINE ON EVERY PATH, INCLUDING EVERY DECLINE, WITH THE REASON AND THE BYTES:
#   <status dir>/mesh-hygiene.log     one human line per run
#   <status dir>/mesh-hygiene.jsonl   one JSON object per run
#   <status dir>/mesh-hygiene.json    the latest record
# Status dir: /var/log when writable (the worker-node default), else $HOME/.dsh-sync-status;
# override with --status-dir or HYGIENE_STATUS_DIR.
#
# NOTHING IS KILLED UNLESS YOU PASS --reclaim.  Exit codes: 0 ran (reported/acted/declined),
# 1 usage or self-test failure, 3 a counter could not be measured (nothing touched).
#
# USAGE
#   mesh-hygiene.sh                     # read-only report
#   mesh-hygiene.sh --reclaim           # act, with the shipped gates
#   mesh-hygiene.sh --drift 20          # the drift series for this node
#   mesh-hygiene.sh --collect           # every node's latest record, one command
#   mesh-hygiene.sh --self-test         # regression test (spawns and cleans up its own two hogs)
#   --idle-seconds N | --min-orphan-age N | --grace-seconds N
#   --targets "a,b"      REPLACE the class A list; `--targets ""` disables class A entirely.
#   --orphan-patterns RE REPLACE the class B regex.      --governor-root DIR   lease directory.
#   --gate-url URL       the local gate capacity route.  --status-dir DIR      where records go.
#   --nodes "name=alias=kind …"  nodes for --collect (kind: win|posix; default posix).
#                                --no-escalate / --quiet / --version
#
# INSTALL (running this script installs nothing):
#   Linux, systemd timer:
#     sudo install -m 755 mesh-hygiene.sh /usr/local/lib/lakewoodphone/mesh-hygiene.sh
#     ExecStart=/bin/bash /usr/local/lib/lakewoodphone/mesh-hygiene.sh --reclaim --quiet
#     OnUnitActiveSec=5min
#     OFF SWITCH, one command: sudo systemctl disable --now mesh-hygiene.timer
#   macOS: the Mac mini already has its own job (docs/mesh/80-mac-worker-hygiene.md section 4) which
#   this script does NOT replace; see docs/mesh/85-hygiene.md section 9.
#
# THREATS THIS FILE IS WRITTEN AGAINST, ALL MEASURED (docs/mesh/80-mac-worker-hygiene.md section 4.5,
# docs/mesh/74-mac-mini.md section 4):
#   * `uid` is a bash READONLY builtin: using it as a variable name silently kills the loop that uses
#     it, and every earlier check then reads as "nothing found". Never used here (want_uid, puid).
#   * macOS `ps -o comm=` returns the full path INCLUDING ITS SPACES as ONE column, so `$NF` is the
#     word "Chrome" or "Helper". `-ww` plus "everything from field 6 on is the command" is used.
#   * `pmset -g assertionslog` HANGS FOREVER on macOS and is never called by this script.
#   * a bare `tailscale` on macOS resolves to a shim in front of a GUI binary that never answers, so
#     a probe that calls it leaves a spinning orphan. This script never invokes it -- it only
#     RECOGNISES its CLI form, and never `tailscaled`, which carries the tunnel.
set -u

VERSION="1.0.0"

# 71 s2.2, frozen.
RESERVE_MIB=3885
PER_CHILD_MIB=160
MAX_SLOTS=24

MODE="report"
IDLE_REQUIRED="${HYGIENE_IDLE_SECONDS:-1800}"
MIN_ORPHAN_AGE="${HYGIENE_MIN_ORPHAN_AGE:-300}"
GRACE_SECS="${HYGIENE_GRACE_SECONDS:-10}"
DRIFT_LAST=10
NO_ESCALATE=0
QUIET=0
TARGETS_OVERRIDE=""; TARGETS_BOUND=0
PATTERNS_OVERRIDE=""; PATTERNS_BOUND=0
GOVERNOR_ROOT="${DSH_HOME:-$HOME/.dsh}/governor"
GATE_URL="${HYGIENE_GATE_URL:-http://127.0.0.1:3086/mesh/capacity}"
STATUS_DIR_OVERRIDE="${HYGIENE_STATUS_DIR:-}"
COLLECT_NODES=""

DEFAULT_TARGETS="
/Applications/Google Chrome.app
/Applications/Microsoft Edge.app
/Applications/Brave Browser.app
/Applications/Firefox.app
/Applications/Opera.app
/Applications/Vivaldi.app
/Applications/Spotify.app
/Applications/Slack.app
/Applications/Discord.app
/Applications/Notion.app
/Applications/Obsidian.app
/Applications/zoom.us.app
/Applications/Microsoft Teams.app
/Applications/WhatsApp.app
/Applications/Telegram.app
/usr/lib/chromium/chromium
/usr/lib/chromium-browser/chromium-browser
/opt/google/chrome/chrome
/usr/lib/firefox/firefox
/usr/bin/firefox
/opt/spotify/spotify
/usr/lib/slack/slack
/usr/lib/discord/discord
/snap/bin/chromium
/snap/bin/slack
/snap/bin/discord
"

# Our own tool entry points, by command line. `tailscale` is matched ONLY in its CLI form.
DEFAULT_PATTERNS='tailscale (status|ip|debug|serve|funnel|netcheck|ping|whois|version)|phone-gate\.py|mesh-run\.mjs|mesh-capacity-probe|mesh-e2e|mesh-health|governor\.mjs|agent-fleet|journal\.py|mesh-hygiene'

# Never candidates, however their command line reads: services are parentless by design on a machine
# where they were started from a shell that exited.
PROTECT_PATTERN='dsh/lib/bin\.js[ ]+web|--listen-port|--engine-port|tailscaled'

# ---------------------------------------------------------------------------------------------
# EVERY global this script uses is declared here. The script runs under `set -u`, and MEASURED
# 2026-09-17 04:04Z: the self-test read $CONSOLE_PRESENT before console_state() had ever set it and
# died with "CONSOLE_PRESENT: unbound variable" in the middle of a test that had already spawned
# processes -- a half-run test is worse than no test. Declaring the state up front removes the whole
# class: a variable that exists but is empty is a measurement nobody has taken yet, and every reader
# of it treats it as such.
# ---------------------------------------------------------------------------------------------
TABLE=""; LIVE_PIDS=""; LISTENERS=" "; LISTENER_SOURCE="unmeasured"
TARGET_PROCESSES=""; ORPHAN_PROCESSES=""; SPARED=""; ALL_ROWS=""
TARGETS_TOP=""; PATTERNS_OPT=""; TARGET_SOURCE="default"
CONSOLE_USER=""; CONSOLE_UID=""; IDLE_SECONDS=""; IDLE_SOURCE="unmeasured"; CONSOLE_PRESENT="false"
AVAIL_MIB=""; TOTAL_MIB=""; SWAP_PCT=""; CORES="0"; AVAIL_SOURCE="unmeasured"
MEM_SLOTS=""; CORE_SLOTS=""; SLOTS=""; PLACEABLE=""
DISPATCH_PIDS=""; DISPATCH_COUNT=0; LEASE_HELD=0; LEASE_HOLDERS=""
GATE_REACHABLE="false"; GATE_FREE=""; GATE_MAXC=""; GATE_FLEET=""; GATE_NODE=""; GATE_LOOPS=""
GATE_MS=""; GATE_ERROR=""
RECLAIM_KB=0; RECLAIMED_KB=0; AFTER_KB=0; ACTED_PIDS=""; ESCALATED_PIDS=""; FAILED_GATES=""
DRIFT_SECS=""; DRIFT_DAVAIL=""; DRIFT_DPLACE=""; DRIFT_DRECL=""; DRIFT_RATE=""; DRIFT_HOURS=""
DRIFT_ZERO=""; DRIFT_BASE=""; DRIFT_TREND="no-history"
SELFTEST_BYPASS="false"

while [ $# -gt 0 ]; do
  case "$1" in
    --reclaim)          MODE="reclaim" ;;
    --report)           MODE="report" ;;
    --self-test)        MODE="selftest" ;;
    --collect)          MODE="collect" ;;
    --drift)            MODE="drift"; case "${2:-}" in ''|*[!0-9]*) ;; *) DRIFT_LAST="$2"; shift ;; esac ;;
    --idle-seconds)     IDLE_REQUIRED="${2:-}"; shift ;;
    --min-orphan-age)   MIN_ORPHAN_AGE="${2:-}"; shift ;;
    --grace-seconds)    GRACE_SECS="${2:-}"; shift ;;
    --targets)          TARGETS_OVERRIDE="${2:-}"; TARGETS_BOUND=1; shift ;;
    --orphan-patterns)  PATTERNS_OVERRIDE="${2:-}"; PATTERNS_BOUND=1; shift ;;
    --governor-root)    GOVERNOR_ROOT="${2:-}"; shift ;;
    --gate-url)         GATE_URL="${2:-}"; shift ;;
    --status-dir)       STATUS_DIR_OVERRIDE="${2:-}"; shift ;;
    --nodes)            COLLECT_NODES="${2:-}"; shift ;;
    --no-escalate)      NO_ESCALATE=1 ;;
    --quiet)            QUIET=1 ;;
    --version)          echo "$VERSION"; exit 0 ;;
    -h|--help)          sed -n '2,95p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "mesh-hygiene: unknown argument '$1'" >&2; exit 2 ;;
  esac
  shift
done

case "$IDLE_REQUIRED" in ''|*[!0-9]*) echo "mesh-hygiene: --idle-seconds needs a whole number" >&2; exit 2 ;; esac
case "$MIN_ORPHAN_AGE" in ''|*[!0-9]*) echo "mesh-hygiene: --min-orphan-age needs a whole number" >&2; exit 2 ;; esac

if [ -n "$STATUS_DIR_OVERRIDE" ]; then STATUS_DIR="$STATUS_DIR_OVERRIDE"
elif [ -w /var/log ]; then STATUS_DIR="/var/log"
else STATUS_DIR="$HOME/.dsh-sync-status"; fi
mkdir -p "$STATUS_DIR" 2>/dev/null
LOG="$STATUS_DIR/mesh-hygiene.log"
DECISIONS="$STATUS_DIR/mesh-hygiene.jsonl"
LATEST="$STATUS_DIR/mesh-hygiene.json"
PLATFORM="$(uname -s)"

# ---------------------------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------------------------
log_line() { printf '%s\n' "$1" >>"$LOG" 2>/dev/null || true; [ "$QUIET" -eq 1 ] || printf '%s\n' "$1"; }
out() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$1"; }

jstr() { # any text -> quoted JSON string, or null when empty
  if [ -z "${1:-}" ]; then printf 'null'; return; fi
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\n\r' | sed -e 's/^/"/' -e 's/$/"/'
}
jnum() { case "${1:-}" in ''|*[!0-9.-]*) printf 'null' ;; *) printf '%s' "$1" ;; esac; }
now_utc() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
now_epoch() { date -u '+%s'; }
count_lines() { printf '%s\n' "${1:-}" | awk 'NF{n++} END{print n+0}'; }
rss_sum() { printf '%s\n' "${1:-}" | awk -F'|' '/^[0-9]+\|/ {s+=$3} END{print s+0}'; }

run_bounded() { # run_bounded SECONDS CMD...  -- kills the whole process GROUP on timeout
  _secs="$1"; shift
  if command -v perl >/dev/null 2>&1; then
    perl -e 'setpgrp(0,0); exec @ARGV' "$@" 2>/dev/null &
    _bpid=$!
    ( sleep "$_secs"; kill -9 -"$_bpid" 2>/dev/null ) >/dev/null 2>&1 &
    _watch=$!
    wait "$_bpid" 2>/dev/null; _brc=$?
    kill "$_watch" 2>/dev/null; wait "$_watch" 2>/dev/null
    return $_brc
  fi
  "$@"
}

# ---------------------------------------------------------------------------------------------
# THE COUNTERS: one definition each, and each one is the definition the capacity contract uses.
# ---------------------------------------------------------------------------------------------
mem_avail_bytes() {
  if [ "$PLATFORM" = "Darwin" ]; then
    _psz="$(run_bounded 10 sysctl -n hw.pagesize 2>/dev/null)"
    case "$_psz" in ''|*[!0-9]*) echo ""; return ;; esac
    run_bounded 20 vm_stat 2>/dev/null | awk -v ps="$_psz" '
      /Pages free/        { v=$3; gsub(/[^0-9]/,"",v); f=v }
      /Pages inactive/    { v=$3; gsub(/[^0-9]/,"",v); i=v }
      /Pages speculative/ { v=$3; gsub(/[^0-9]/,"",v); s=v }
      /Pages purgeable/   { v=$3; gsub(/[^0-9]/,"",v); p=v }
      END { if (f=="" || i=="") { print "" } else { printf "%d", (f+i+s+p)*ps } }'
    return
  fi
  awk '/^MemAvailable:/ { printf "%d", $2*1024; found=1; exit } END { if (!found) print "" }' /proc/meminfo 2>/dev/null
}

mem_total_bytes() {
  if [ "$PLATFORM" = "Darwin" ]; then
    _v="$(run_bounded 10 sysctl -n hw.memsize 2>/dev/null)"
    case "$_v" in ''|*[!0-9]*) echo "" ;; *) echo "$_v" ;; esac
    return
  fi
  awk '/^MemTotal:/ { printf "%d", $2*1024; found=1; exit } END { if (!found) print "" }' /proc/meminfo 2>/dev/null
}

swap_used_pct() {
  if [ "$PLATFORM" = "Darwin" ]; then
    run_bounded 10 sysctl -n vm.swapusage 2>/dev/null | awk '
      { for (i=1;i<=NF;i++) { if ($i=="total") { t=$(i+2); gsub(/[^0-9.]/,"",t) } if ($i=="used") { u=$(i+2); gsub(/[^0-9.]/,"",u) } } }
      END { if (t+0 > 0) printf "%.1f", (u/t)*100; else print "" }'
    return
  fi
  awk '/^SwapTotal:/ {t=$2} /^SwapFree:/ {f=$2} END { if (t+0 > 0) printf "%.1f", ((t-f)/t)*100; else print "0.0" }' /proc/meminfo 2>/dev/null
}

physical_cores() {
  if [ "$PLATFORM" = "Darwin" ]; then
    _v="$(run_bounded 10 sysctl -n hw.physicalcpu 2>/dev/null)"
    case "$_v" in ''|*[!0-9]*) run_bounded 10 sysctl -n hw.ncpu 2>/dev/null ;; *) echo "$_v" ;; esac
    return
  fi
  _n="$(awk -F: '/^physical id/ {gsub(/ /,"",$2); p=$2} /^core id/ {gsub(/ /,"",$2); print p":"$2}' /proc/cpuinfo 2>/dev/null | sort -u | awk 'END{print NR+0}')"
  if [ "${_n:-0}" -gt 0 ]; then echo "$_n"; else nproc 2>/dev/null || echo 0; fi
}

etime_to_seconds() {
  printf '%s\n' "$1" | awk -F'[-:]' '
    { if (NF==4) print $1*86400+$2*3600+$3*60+$4
      else if (NF==3) print $1*3600+$2*60+$3
      else if (NF==2) print $1*60+$2
      else print 0 }'
}

proc_table() { # pid|ppid|uid|rss_kb|age_sec|command
  # `-ww` and "everything from field 6 on is the command" is the fix for the macOS trap where a path
  # containing spaces arrives as one column, so `$NF` would be the word "Chrome" or "Helper"
  # (docs/mesh/80-mac-worker-hygiene.md section 4.5). etime -> seconds happens in awk because a shell
  # function per process would cost one subshell per process per run.
  if [ "$PLATFORM" = "Darwin" ]; then
    run_bounded 30 ps -ww -A -o pid=,ppid=,uid=,rss=,etime=,args= 2>/dev/null
  else
    ps -ww -A -o pid=,ppid=,uid=,rss=,etime=,args= 2>/dev/null
  fi | awk '
    function etime2sec(e,   n, a) {
      n = split(e, a, /[-:]/)
      if (n == 4) return a[1]*86400 + a[2]*3600 + a[3]*60 + a[4]
      if (n == 3) return a[1]*3600 + a[2]*60 + a[3]
      if (n == 2) return a[1]*60 + a[2]
      return 0
    }
    {
      cmd=""; for (i=6;i<=NF;i++) { cmd = cmd (i>6 ? " " : "") $i }
      if ($1 ~ /^[0-9]+$/) printf "%s|%s|%s|%s|%s|%s\n", $1, $2, $3, $4, etime2sec($5), cmd
    }' 2>/dev/null
}

listener_pids() { # prints "pidlist|source"
  if command -v ss >/dev/null 2>&1; then
    _l="$(ss -H -ltnp 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u | tr '\n' ' ')"
    echo "$_l|ss"
    return
  fi
  if command -v lsof >/dev/null 2>&1; then
    _l="$(run_bounded 25 lsof -nP -iTCP -sTCP:LISTEN -t 2>/dev/null | sort -u | tr '\n' ' ')"
    echo "$_l|lsof"
    return
  fi
  echo "|unavailable"
}

console_state() {
  CONSOLE_USER=""; CONSOLE_UID=""; IDLE_SECONDS=""; IDLE_SOURCE="unmeasured"; CONSOLE_PRESENT="false"
  if [ "$PLATFORM" = "Darwin" ]; then
    CONSOLE_USER="$(run_bounded 10 stat -f %Su /dev/console 2>/dev/null)"
    case "$CONSOLE_USER" in ''|root|loginwindow|_mbsetupuser) CONSOLE_USER="" ;; esac
    if [ -z "$CONSOLE_USER" ]; then IDLE_SOURCE="no-active-session"; return; fi
    CONSOLE_PRESENT="true"
    CONSOLE_UID="$(run_bounded 10 id -u "$CONSOLE_USER" 2>/dev/null)"
    _t="$(run_bounded 20 ioreg -c IOHIDSystem 2>/dev/null | awk -F'= ' '/HIDIdleTime/ { print $2; exit }' | tr -d ' ')"
    case "$_t" in ''|*[!0-9]*) IDLE_SOURCE="unmeasurable(ioreg gave no HIDIdleTime)" ;; *)
      IDLE_SECONDS=$(( _t / 1000000000 )); IDLE_SOURCE="IOHIDSystem.HIDIdleTime" ;; esac
    return
  fi
  _who="$(who -u 2>/dev/null)"
  if [ -z "$_who" ]; then IDLE_SOURCE="no-active-session"; return; fi
  CONSOLE_PRESENT="true"
  CONSOLE_USER="$(printf '%s\n' "$_who" | awk 'NR==1{print $1}')"
  CONSOLE_UID="$(run_bounded 10 id -u "$CONSOLE_USER" 2>/dev/null)"
  _min=""
  _oldifs="$IFS"; IFS='
'
  for _line in $_who; do
    # Parse from the RIGHT, not by column index: `who -u`'s LOGIN@ is one field for today's logins
    # and TWO ("YYYY-MM-DD HH:MM") for older ones, so the idle column is not at a fixed position.
    # The layout ends with `... IDLE PID [COMMENT]`; strip a trailing (comment) and take the field
    # before the numeric pid.
    _idle="$(printf '%s\n' "$_line" | awk '{
      n = NF
      if ($n ~ /^\(.*\)$/) n = n - 1
      if ($n ~ /^[0-9]+$/) { print $(n-1) } else { print "" }
    }')"
    _s=""
    case "$_idle" in
      '.') _s=0 ;;
      old) _s=86400 ;;
      *:*) _s="$(printf '%s' "$_idle" | awk -F: '{ if (NF==2) print $1*60+$2; else print "" }')" ;;
      *) _s="" ;;
    esac
    if [ -n "$_s" ]; then
      if [ -z "$_min" ] || [ "$_s" -lt "$_min" ]; then _min="$_s"; fi
    fi
  done
  IFS="$_oldifs"
  if [ -n "$_min" ]; then IDLE_SECONDS="$_min"; IDLE_SOURCE="who -u idlex"; else IDLE_SOURCE="unmeasurable(who -u idle column did not parse)"; fi
}

# ---------------------------------------------------------------------------------------------
# The two reclaim classes
# ---------------------------------------------------------------------------------------------
# ROW LAYOUT, fixed and used by every reader and writer below:
#     pid|class|rss_kb|age_s|executable|why
# MEASURED 2026-09-17 04:06Z: the writers put the executable in field 3 while the readers took field 3
# as RSS (`rss_sum`), so every orphan's bytes summed to 0 ("reclaimable 0 MiB" with two orphans in
# front of it) and the reclaim loop arithmetic read the string "sh" as a number and died under
# `set -u` with "sh: unbound variable". One layout, written down, is the fix.
target_match() { # target_match EXE -> the matching prefix, or nothing
  printf '%s\n' "$TARGETS_OPT" | while read -r _t; do
    [ -n "$_t" ] || continue
    case "$1" in "$_t"|"$_t"/*) printf '%s' "$_t"; break ;; esac
  done | head -1
}

# A parent that only reaps is not a parent in any sense this policy cares about. MEASURED on
# secratary 2026-09-17 04:05Z: an abandoned `sh` was reparented to pid 1, so the strict test would
# have worked there -- but on a host with a per-user systemd (or any PR_SET_CHILD_SUBREAPER) the
# reparented child's parent is a LIVE process, and a strict "parent must be gone" test would then
# never see any orphan at all on that node.
is_reaper_parent() { # pid -> 0 (yes) / 1 (no)
  [ "$1" = "1" ] && return 0
  _pcmd="$(printf '%s\n' "$TABLE" | awk -F'|' -v p="$1" '$1==p {print $6; exit}')"
  case "$_pcmd" in
    ''|systemd|/usr/lib/systemd/systemd|/lib/systemd/systemd|/sbin/init|init|/sbin/launchd|/usr/sbin/launchd) return 0 ;;
    *"/systemd "*) return 0 ;;
    *) return 1 ;;
  esac
}

classify() {
  if [ "$TARGETS_BOUND" -eq 1 ]; then TARGETS_OPT="$TARGETS_OVERRIDE"; else TARGETS_OPT="$DEFAULT_TARGETS"; fi
  if [ "$PATTERNS_BOUND" -eq 1 ]; then PATTERNS_OPT="$PATTERNS_OVERRIDE"; else PATTERNS_OPT="$DEFAULT_PATTERNS"; fi
  [ -n "${CONSOLE_UID:-}" ] || CONSOLE_UID="0"
  if [ "$TARGETS_BOUND" -eq 1 ] && [ -z "$TARGETS_OVERRIDE" ]; then TARGET_SOURCE="override(empty: class A disabled)"
  elif [ "$TARGETS_BOUND" -eq 1 ]; then TARGET_SOURCE="override"
  else TARGET_SOURCE="default"; fi

  _list="$(listener_pids)"
  LISTENER_SOURCE="${_list##*|}"
  LISTENERS=" ${_list%|*} "

  LIVE_PIDS=" $(printf '%s\n' "$TABLE" | cut -d'|' -f1 | tr '\n' ' ') "
  _tt="$(mktemp)"; _ot="$(mktemp)"; _st="$(mktemp)"

  printf '%s\n' "$TABLE" | while IFS='|' read -r pid ppid puid rss age cmd; do
    [ -n "${pid:-}" ] || continue
    [ "$pid" = "$$" ] && continue
    [ "$ppid" = "$$" ] && continue

    # ---- class A: the process's own executable under a target prefix, and owned by the console user
    if [ "$CONSOLE_PRESENT" = "true" ] && [ -n "$cmd" ] && [ "$puid" = "$CONSOLE_UID" ]; then
      _exe="$(printf '%s' "$cmd" | awk '{print $1}')"
      case "$_exe" in
        /*) _t="$(target_match "$_exe")"
            [ -n "$_t" ] && printf '%s|target|%s|%s|%s|path under %s\n' "$pid" "$rss" "$age" "$_exe" "$_t" >>"$_tt" ;;
      esac
    fi

    # ---- class B: parent gone + our tooling + old enough + not a service
    case "$LIVE_PIDS" in *" $ppid "*) _parent_gone=0 ;; *) _parent_gone=1 ;; esac
    if [ "$_parent_gone" = "0" ] && is_reaper_parent "$ppid"; then _parent_gone=1; fi
    [ "$_parent_gone" = "1" ] || continue
    [ -n "$cmd" ] || continue
    printf '%s' "$cmd" | grep -Eq "$PROTECT_PATTERN" && continue
    printf '%s' "$cmd" | grep -Eq "$PATTERNS_OPT" || continue
    # proc_table ALREADY emits age in seconds, so this line must not convert again. MEASURED
    # 2026-09-17 04:05Z: converting a second time turned every age into 0 (etime_to_seconds("6") has
    # one field and returns 0), so no orphan ever passed the age floor and the self-test failed with
    # "nothing ... to reclaim -- already clean" while two eligible orphans sat in front of it.
    _age_s="${age:-0}"
    if [ "${_age_s:-0}" -lt "$MIN_ORPHAN_AGE" ]; then
      printf '%s not-yet: parent is gone and it matches our tooling, but age %ss < floor %ss\n' "$pid" "$_age_s" "$MIN_ORPHAN_AGE" >>"$_st"
      continue
    fi
    case "$LISTENERS" in *" $pid "*) printf '%s spared: holds a LISTENING socket, so it is a service this node depends on (matched %s)\n' "$pid" "$(printf '%s' "$cmd" | cut -c1-90)" >>"$_st"; continue ;; esac
    printf '%s|orphan|%s|%s|%s|orphan (ppid %s is gone), matches our tooling, age %ss\n' "$pid" "$rss" "$_age_s" "$(printf '%s' "$cmd" | awk '{print $1}')" "$ppid" "$_age_s" >>"$_ot"
  done

  TARGET_PROCESSES="$(cat "$_tt")"; ORPHAN_PROCESSES="$(cat "$_ot")"; SPARED="$(cat "$_st")"
  rm -f "$_tt" "$_ot" "$_st"
}

# ---------------------------------------------------------------------------------------------
# Capacity (the broker's arithmetic, reproduced) and the gate's own answer
# ---------------------------------------------------------------------------------------------
capacity_slots() { # AVAIL_MIB IN_USE CORES SWAP_PCT -> "memSlots coreSlots slots placeable"
  awk -v a="$1" -v r="$RESERVE_MIB" -v p="$PER_CHILD_MIB" -v m="$MAX_SLOTS" -v u="$2" -v c="$3" -v sw="$4" 'BEGIN {
    mem = int((a - r)/p); if (mem > m) mem = m; mem = mem - u
    core = int(c * 0.75)
    s = mem; if (s > core) s = core
    if (sw+0 >= 90) s = int(s/2)
    place = (s > 0 ? s : 0)
    printf "%d %d %d %d", mem, core, s, place }'
}

gate_reading() { # -> "reachable|free_mib|max_children|fleet|node|loops|elapsed_ms|error"
  if ! command -v curl >/dev/null 2>&1; then echo "false|||||||curl not installed"; return; fi
  _t0="$(now_epoch)"
  _body="$(run_bounded 6 curl -s --max-time 3 --noproxy '*' "$GATE_URL" 2>/dev/null)"
  _t1="$(now_epoch)"
  if [ -z "$_body" ]; then echo "false||||||$(( (_t1-_t0)*1000 ))|no answer from $GATE_URL"; return; fi
  printf '%s' "$_body" | awk -v ms="$(( (_t1-_t0)*1000 ))" '{
    free="null"; mc="null"; loops="null"; node="null"; fleet="false"
    if (match($0, "\"freeMiB\"[ ]*:[ ]*[^,}]*")) { free=substr($0,RSTART,RLENGTH); sub(/.*:[ ]*/,"",free); gsub(/[^0-9.-]/,"",free) }
    if (match($0, "\"maxChildren\"[ ]*:[ ]*[^,}]*")) { mc=substr($0,RSTART,RLENGTH); sub(/.*:[ ]*/,"",mc); gsub(/[^0-9.-]/,"",mc) }
    if (match($0, "\"loopsRunning\"[ ]*:[ ]*[^,}]*")) { loops=substr($0,RSTART,RLENGTH); sub(/.*:[ ]*/,"",loops); gsub(/[^0-9.-]/,"",loops) }
    if (match($0, "\"node\"[ ]*:[ ]*\"[^\"]*\"")) { node=substr($0,RSTART,RLENGTH); sub(/.*:[ ]*"/,"",node); sub(/"$/,"",node) }
    if (match($0, "\"fleet\"[ ]*:[ ]*(true|false)")) { if (substr($0,RSTART,RLENGTH) ~ /true/) fleet="true" }
    if (free=="") free="null"; if (mc=="") mc="null"; if (loops=="") loops="null"
    printf "true|%s|%s|%s|%s|%s|%s|\n", free, mc, fleet, node, loops, ms }'
}

# ---------------------------------------------------------------------------------------------
# Drift. Records are this tool's own fixed-shape JSON, read BY KEY; `at_epoch` is written so no
# platform's `date -d` / `date -j` dialect is needed to compute a rate.
# ---------------------------------------------------------------------------------------------
# jfield VALUE — a NUMBER or nothing. MEASURED 2026-09-17 04:31Z: with `\([-0-9.]*\)` a JSON `null`
# matched with an EMPTY capture, so the substitution returned the whole remainder of the line and the
# collector printed `rate=null,"hours_to_zero_children":null,…}` as a value. The pattern now requires
# the value to start with a digit or a minus, which is what makes a number a number.
jfield() { [ -f "$1" ] || { echo ""; return; }; sed -n "s/.*\"$2\":\(-\{0,1\}[0-9][0-9.]*\).*/\1/p" "$1" | tail -1; }
jfield_str() { [ -f "$1" ] || { echo ""; return; }; sed -n "s/.*\"$2\":\"\([^\"]*\)\".*/\1/p" "$1" | tail -1; }

drift_compute() { # AVAIL_MIB PLACEABLE RECLAIM_KB
  _avail="$1"; _place="$2"; _recl="$3"
  DRIFT_SECS=""; DRIFT_DAVAIL=""; DRIFT_DPLACE=""; DRIFT_DRECL=""; DRIFT_RATE=""; DRIFT_HOURS=""
  DRIFT_ZERO=""; DRIFT_BASE=""; DRIFT_TREND="no-history"
  [ -f "$DECISIONS" ] || return 0
  _last="$(tail -1 "$DECISIONS" 2>/dev/null)"
  [ -n "$_last" ] || return 0
  _t1="$(mktemp)"; printf '%s\n' "$_last" >"$_t1"
  _p_at="$(jfield "$_t1" at_epoch)"; _p_av="$(jfield "$_t1" avail_mib)"
  _p_pl="$(jfield "$_t1" placeable_children)"; _p_rc="$(jfield "$_t1" reclaimable_rss_kb)"
  rm -f "$_t1"
  _now="$(now_epoch)"
  [ -n "$_p_at" ] && DRIFT_SECS=$(( _now - _p_at ))
  [ -n "$_p_av" ] && DRIFT_DAVAIL=$(( _avail - _p_av ))
  [ -n "$_p_pl" ] && DRIFT_DPLACE=$(( _place - _p_pl ))
  [ -n "$_p_rc" ] && DRIFT_DRECL=$(( _recl - _p_rc ))

  # The baseline is the OLDEST record inside 24 h (the file is chronological, so: the first match).
  _cut=$(( _now - 86400 ))
  _base="$(awk -v cut="$_cut" 'match($0, /"at_epoch":[0-9]+/) { t=substr($0,RSTART,RLENGTH); sub(/.*:/,"",t); if (t+0 >= cut) { print; exit } }' "$DECISIONS" 2>/dev/null)"
  [ -n "$_base" ] || _base="$(head -1 "$DECISIONS" 2>/dev/null)"
  if [ -n "$_base" ]; then
    _t2="$(mktemp)"; printf '%s\n' "$_base" >"$_t2"
    _b_at="$(jfield "$_t2" at_epoch)"; _b_av="$(jfield "$_t2" avail_mib)"
    DRIFT_BASE="$(jfield_str "$_t2" at)"
    rm -f "$_t2"
    if [ -n "$_b_at" ] && [ "$_b_at" != "${_p_at:-x}" ] && [ "$_now" -gt "$_b_at" ] && [ -n "$_b_av" ]; then
      DRIFT_HOURS="$(awk -v n="$_now" -v b="$_b_at" 'BEGIN{printf "%.2f",(n-b)/3600}')"
      DRIFT_RATE="$(awk -v d="$(( _avail - _b_av ))" -v h="$DRIFT_HOURS" 'BEGIN{printf "%d", d/h}')"
      if [ "$_avail" -le "$RESERVE_MIB" ]; then DRIFT_ZERO="0.0"
      elif [ "$DRIFT_RATE" -lt 0 ]; then
        DRIFT_ZERO="$(awk -v sp="$(( _avail - RESERVE_MIB ))" -v r="$DRIFT_RATE" 'BEGIN{printf "%.1f", sp/(-r)}')"
      fi
    fi
  fi
  if [ -n "$DRIFT_RATE" ]; then
    if [ "$DRIFT_RATE" -le -256 ]; then DRIFT_TREND="shrinking"
    elif [ "$DRIFT_RATE" -ge 256 ]; then DRIFT_TREND="growing"
    else DRIFT_TREND="stable"; fi
  else DRIFT_TREND="insufficient-window"; fi
}

# ---------------------------------------------------------------------------------------------
# Measurement + the record writer
# ---------------------------------------------------------------------------------------------
measure_gates() {
  DISPATCH_PIDS="$(printf '%s\n' "$TABLE" | awk -F'|' '$6 ~ /profile[ ]+headless/ { printf "%s ", $1 }')"
  DISPATCH_COUNT="$(count_lines "$DISPATCH_PIDS")"
  LEASE_HELD=0; LEASE_HOLDERS=""
  _leases="$GOVERNOR_ROOT/leases"
  if [ -d "$_leases" ]; then
    _nowms="$(( $(now_epoch) * 1000 ))"
    for _f in "$_leases"/slot-*.lease; do
      [ -f "$_f" ] || continue
      _exp="$(sed -n 's/.*"expiresAt":[ ]*\([0-9]*\).*/\1/p' "$_f" 2>/dev/null | head -1)"
      _pidv="$(sed -n 's/.*"pid":[ ]*\([0-9]*\).*/\1/p' "$_f" 2>/dev/null | head -1)"
      _kind="$(sed -n 's/.*"kind":[ ]*"\([^"]*\)".*/\1/p' "$_f" 2>/dev/null | head -1)"
      if [ -n "$_exp" ] && [ "$_exp" -gt "$_nowms" ]; then
        LEASE_HELD=$(( LEASE_HELD + 1 ))
        LEASE_HOLDERS="$LEASE_HOLDERS pid ${_pidv:-?} ${_kind:-?} [$(basename "$_f")]"
      fi
    done
  fi
}

measure_all() {
  TABLE="$(proc_table)"
  [ -n "$TABLE" ] || return 3
  _ab="$(mem_avail_bytes)"; _tb="$(mem_total_bytes)"
  AVAIL_SOURCE="MemAvailable(/proc/meminfo)"
  [ "$PLATFORM" = "Darwin" ] && AVAIL_SOURCE="vm_stat free+inactive+speculative+purgeable x hw.pagesize"
  if [ -n "$_ab" ]; then AVAIL_MIB=$(( _ab / 1048576 )); else AVAIL_MIB=""; fi
  if [ -n "$_tb" ]; then TOTAL_MIB=$(( _tb / 1048576 )); else TOTAL_MIB=""; fi
  SWAP_PCT="$(swap_used_pct)"
  CORES="$(physical_cores)"
  console_state
  measure_gates
  if [ -n "$AVAIL_MIB" ]; then
    set -- $(capacity_slots "$AVAIL_MIB" "$LEASE_HELD" "${CORES:-0}" "${SWAP_PCT:-0}")
    MEM_SLOTS="$1"; CORE_SLOTS="$2"; SLOTS="$3"; PLACEABLE="$4"
  else MEM_SLOTS=""; CORE_SLOTS=""; SLOTS=""; PLACEABLE=""; fi
  # The gate answer is pipe-delimited ON PURPOSE (`set -- $(...)` splits on whitespace, so a
  # delimiter made of pipes cannot be swallowed by a value containing a space). MEASURED 2026-09-17
  # 04:02Z: the first version used `set -- $(gate_reading)` and every field landed in GATE_REACHABLE.
  _g="$(gate_reading)"
  GATE_REACHABLE="${_g%%|*}"; _rest="${_g#*|}"
  GATE_FREE="${_rest%%|*}";    _rest="${_rest#*|}"
  GATE_MAXC="${_rest%%|*}";    _rest="${_rest#*|}"
  GATE_FLEET="${_rest%%|*}";   _rest="${_rest#*|}"
  GATE_NODE="${_rest%%|*}";    _rest="${_rest#*|}"
  GATE_LOOPS="${_rest%%|*}";   _rest="${_rest#*|}"
  GATE_MS="${_rest%%|*}";      GATE_ERROR="${_rest#*|}"
  [ "$GATE_FREE" = "null" ] && GATE_FREE=""
  [ "$GATE_MAXC" = "null" ] && GATE_MAXC=""
  [ "$GATE_LOOPS" = "null" ] && GATE_LOOPS=""
  [ "$GATE_NODE" = "null" ] && GATE_NODE=""
  classify_and_sum
  RECLAIMED_KB=0; AFTER_KB=0; ACTED_PIDS=""; ESCALATED_PIDS=""
  drift_compute "${AVAIL_MIB:-0}" "${PLACEABLE:-0}" "$RECLAIM_KB"
  return 0
}

write_record() { # write_record MODE OUTCOME REASON
  _mode="$1"; _outcome="$2"; _reason="$3"
  _at="$(now_utc)"; _epoch="$(now_epoch)"
  _idle_txt="${IDLE_SECONDS:-unmeasured}"
  _line="$_at | $(uname -n) | v$VERSION | mode=$_mode | outcome=$_outcome | console=${CONSOLE_USER:-none} uid=${CONSOLE_UID:-none} idle_s=$_idle_txt idle_required_s=$IDLE_REQUIRED idle_source=$IDLE_SOURCE | work dispatch=$DISPATCH_COUNT leases=$LEASE_HELD loops=${GATE_LOOPS:-n/a} | mem avail=${AVAIL_MIB:-unmeasured}MiB swap=${SWAP_PCT:-unmeasured}% | placeable=${PLACEABLE:-unmeasured} (memSlots=${MEM_SLOTS:-none} coreSlots=${CORE_SLOTS:-none}) gate_free=${GATE_FREE:-none}MiB gate_maxchildren=${GATE_MAXC:-none} | reclaimable_rss=$(( RECLAIM_KB / 1024 ))MiB targets=$(count_lines "$TARGET_PROCESSES") orphans=$(count_lines "$ORPHAN_PROCESSES") spared=$(count_lines "$SPARED") reclaimed=$(( RECLAIMED_KB / 1024 ))MiB | drift prev_d=${DRIFT_DAVAIL:-none} MiB in ${DRIFT_SECS:-none} s rate=${DRIFT_RATE:-none} MiB/h over ${DRIFT_HOURS:-none} h placeable_d=${DRIFT_DPLACE:-none} zero_children_in_h=${DRIFT_ZERO:-none} trend=$DRIFT_TREND | status_dir=$STATUS_DIR | reason=$_reason"
  log_line "$_line"

  _j="{\"schema\":1,\"tool\":\"mesh-hygiene\",\"version\":$(jstr "$VERSION"),\"at\":$(jstr "$_at"),\"at_epoch\":$_epoch,"
  # Small values first, then assemble. This file failed `bash -n` once with
  #   "line 563: syntax error near unexpected token `}' while looking for matching `)'"
  # on the two monster lines that used to live here (written 2026-09-17 04:00Z, fixed 04:05Z). The
  # fix was to split them into one value per line -- and the fault was NOT isolated to a single
  # construct: each of the shapes in those lines (nested command substitutions, a parameter default
  # containing one, an escaped-quote JSON fragment around one) parses fine on its own when tested
  # (bash 5.3.9, /tmp/tA.sh, tB.sh, tC.sh). What is recorded is the observation, not a theory: many
  # substitutions on one line is unverifiable by eye, one value per line is verifiable.
  _host="$(uname -n)"
  _node="${GATE_NODE:-$_host}"
  _secs="${DRIFT_SECS:-}"; _dav="${DRIFT_DAVAIL:-}"; _dpl="${DRIFT_DPLACE:-}"; _drc="${DRIFT_DRECL:-}"
  _bhrs="${DRIFT_HOURS:-}"; _rate="${DRIFT_RATE:-}"; _zero="${DRIFT_ZERO:-}"
  _acted="${ACTED_PIDS# }"; _esc="${ESCALATED_PIDS# }"
  _spared_join="$(printf '%s' "$SPARED" | tr '\n' ';')"
  _cand="$(printf '%s\n%s\n' "$TARGET_PROCESSES" "$ORPHAN_PROCESSES" | awk -F'|' 'NF>1 { printf "%s:%s ", $1, $6 }')"
  _cl_t="$(count_lines "$TARGET_PROCESSES")"; _cl_o="$(count_lines "$ORPHAN_PROCESSES")"
  _rs_t="$(rss_sum "$TARGET_PROCESSES")"; _rs_o="$(rss_sum "$ORPHAN_PROCESSES")"
  _j="$_j\"host\":$(jstr "$_host"),\"node\":$(jstr "$_node"),\"platform\":$(jstr "$PLATFORM"),"
  _j="$_j\"mode\":$(jstr "$_mode"),\"outcome\":$(jstr "$_outcome"),\"reason\":$(jstr "$_reason"),"
  _j="$_j\"gates\":{\"failed\":$(jstr "${FAILED_GATES:-}"),\"idle_required_s\":$IDLE_REQUIRED,\"bypassed_for_selftest\":${SELFTEST_BYPASS:-false}},"
  _j="$_j\"console\":{\"user\":$(jstr "${CONSOLE_USER:-}"),\"uid\":$(jnum "${CONSOLE_UID:-}"),\"present\":$CONSOLE_PRESENT,\"idle_seconds\":$(jnum "${IDLE_SECONDS:-}"),\"idle_source\":$(jstr "$IDLE_SOURCE")},"
  _j="$_j\"work\":{\"dispatch_in_flight\":$(jstr "${DISPATCH_PIDS:-}"),\"dispatch_count\":${DISPATCH_COUNT:-0},\"leases_held\":${LEASE_HELD:-0},\"lease_holders\":$(jstr "${LEASE_HOLDERS:-}"),\"lease_root\":$(jstr "$GOVERNOR_ROOT"),\"agent_loops\":$(jnum "${GATE_LOOPS:-}")},"
  _j="$_j\"memory\":{\"total_mib\":$(jnum "${TOTAL_MIB:-}"),\"avail_mib\":$(jnum "${AVAIL_MIB:-}"),\"avail_source\":$(jstr "$AVAIL_SOURCE"),\"swap_used_pct\":$(jnum "${SWAP_PCT:-}")},"
  _j="$_j\"capacity\":{\"formula\":\"71 s2.2 (memory + cores; disk and transport terms NOT included)\",\"reserve_mib\":$RESERVE_MIB,\"per_child_mib\":$PER_CHILD_MIB,\"memory_slots\":$(jnum "${MEM_SLOTS:-}"),\"core_slots\":$(jnum "${CORE_SLOTS:-}"),\"slots\":$(jnum "${SLOTS:-}"),\"placeable_children\":$(jnum "${PLACEABLE:-}")},"
  _j="$_j\"gate\":{\"url\":$(jstr "$GATE_URL"),\"reachable\":${GATE_REACHABLE:-false},\"error\":$(jstr "${GATE_ERROR:-}"),\"free_mib\":$(jnum "${GATE_FREE:-}"),\"max_children\":$(jnum "${GATE_MAXC:-}"),\"fleet\":${GATE_FLEET:-null}},"
  _j="$_j\"reclaim\":{\"targets_live\":$_cl_t,\"targets_rss_kb\":$_rs_t,\"orphans_live\":$_cl_o,\"orphans_rss_kb\":$_rs_o,"
  _j="$_j\"reclaimable_rss_kb\":$RECLAIM_KB,\"reclaimed_rss_kb\":$RECLAIMED_KB,\"after_rss_kb\":${AFTER_KB:-0},"
  _j="$_j\"acted_pids\":$(jstr "$_acted"),\"escalated_pids\":$(jstr "$_esc"),\"target_list_source\":$(jstr "$TARGET_SOURCE"),"
  _j="$_j\"orphan_patterns\":$(jstr "$PATTERNS_OPT"),\"listener_protection\":$(jstr "$LISTENER_SOURCE"),\"candidates\":$(jstr "$_cand"),\"spared\":$(jstr "$_spared_join")},"
  _j="$_j\"drift\":{\"secs_since_prev\":$(jnum "$_secs"),\"d_avail_mib\":$(jnum "$_dav"),\"d_placeable\":$(jnum "$_dpl"),"
  _j="$_j\"d_reclaimable_rss_kb\":$(jnum "$_drc"),\"baseline_at\":$(jstr "${DRIFT_BASE:-}"),\"baseline_hours\":$(jnum "$_bhrs"),"
  _j="$_j\"avail_mib_per_hour\":$(jnum "$_rate"),\"hours_to_zero_children\":$(jnum "$_zero"),\"trend\":$(jstr "$DRIFT_TREND")},"
  _j="$_j\"status_dir\":$(jstr "$STATUS_DIR"),\"log\":$(jstr "$LOG")}"
  printf '%s\n' "$_j" >>"$DECISIONS" 2>/dev/null || true
  printf '%s\n' "$_j" >"$LATEST.tmp" 2>/dev/null && mv "$LATEST.tmp" "$LATEST" 2>/dev/null
}

# ---------------------------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------------------------
print_report() {
  out "mesh-hygiene $VERSION -- REPORT (read-only; nothing is killed)"
  out "at              : $(now_utc)"
  out "host / platform : $(uname -n) / $PLATFORM"
  out "status dir      : $STATUS_DIR    (log $LOG, series $DECISIONS)"
  out "console user    : ${CONSOLE_USER:-none} (uid ${CONSOLE_UID:-none}) idle=${IDLE_SECONDS:-unmeasured}s required=${IDLE_REQUIRED}s source=$IDLE_SOURCE"
  out "work            : dispatch=${DISPATCH_COUNT} (pids ${DISPATCH_PIDS:-none}) leases=${LEASE_HELD}${LEASE_HOLDERS:+ ($LEASE_HOLDERS)} loops=${GATE_LOOPS:-n/a}"
  out "memory          : avail=${AVAIL_MIB:-unmeasured}MiB total=${TOTAL_MIB:-unmeasured}MiB swap=${SWAP_PCT:-unmeasured}%  [${AVAIL_MIB:+$AVAIL_SOURCE}]"
  out "capacity (71 2.2): memSlots=${MEM_SLOTS:-none} coreSlots=${CORE_SLOTS:-none} slots=${SLOTS:-none} -> placeable children=${PLACEABLE:-none}"
  out "gate (localhost): reachable=$GATE_REACHABLE free=${GATE_FREE:-none}MiB maxChildren=${GATE_MAXC:-none} fleet=${GATE_FLEET:-none} node=${GATE_NODE:-none} ${GATE_ERROR:+($GATE_ERROR)}"
  out "reclaimable now : $(( RECLAIM_KB / 1024 )) MiB in $(count_lines "$TARGET_PROCESSES") target(s) + $(count_lines "$ORPHAN_PROCESSES") orphan(s); $(count_lines "$SPARED") spared"
  if [ -n "$TARGET_PROCESSES" ]; then
    out "  class A (explicit target list, console user only):"
    printf '%s\n' "$TARGET_PROCESSES" | while IFS='|' read -r pid cls rss age exe why; do
      out "    pid $pid  rss $(( rss / 1024 )) MiB  $exe  [$why]"
    done
  fi
  if [ -n "$ORPHAN_PROCESSES" ]; then
    out "  class B (orphans of our own tooling):"
    printf '%s\n' "$ORPHAN_PROCESSES" | while IFS='|' read -r pid cls rss age exe why; do
      out "    pid $pid  rss $(( rss / 1024 )) MiB  $exe  [$why]"
    done
  fi
  if [ -n "$SPARED" ]; then
    out "  spared:"
    printf '%s\n' "$SPARED" | while read -r l; do [ -n "$l" ] && out "    $l"; done
  fi
  out "drift           : prev ${DRIFT_DAVAIL:-none} MiB in ${DRIFT_SECS:-none}s, rate ${DRIFT_RATE:-none} MiB/h over ${DRIFT_HOURS:-none}h, placeable ${DRIFT_DPLACE:-none}, zero-children-in ${DRIFT_ZERO:-none}h, trend $DRIFT_TREND"
}

# ---------------------------------------------------------------------------------------------
# Reclaim
# ---------------------------------------------------------------------------------------------
classify_and_sum() { classify; RECLAIM_KB=$(( $(rss_sum "$TARGET_PROCESSES") + $(rss_sum "$ORPHAN_PROCESSES") )); }

do_reclaim() {
  # RE-CLASSIFY: the floors and the target list may have been changed since measure_all ran (the
  # self-test does exactly that), and MEASURED 2026-09-17 04:05Z the stale classification made the
  # self-test report "nothing ... to reclaim" while two eligible orphans sat in front of it.
  classify_and_sum
  FAILED_GATES=""
  if [ "$CONSOLE_PRESENT" = "true" ]; then
    if [ -z "$IDLE_SECONDS" ]; then FAILED_GATES="$FAILED_GATES console_present_idle_unmeasurable"
    elif [ "$IDLE_SECONDS" -lt "$IDLE_REQUIRED" ]; then FAILED_GATES="$FAILED_GATES console_active"; fi
  fi
  [ "${DISPATCH_COUNT:-0}" -gt 0 ] && FAILED_GATES="$FAILED_GATES dispatch_in_flight"
  [ "${LEASE_HELD:-0}" -gt 0 ] && FAILED_GATES="$FAILED_GATES lease_held"
  FAILED_GATES="$(printf '%s' "$FAILED_GATES" | sed -e 's/^ *//')"

  if [ -n "$FAILED_GATES" ]; then
    _bits=""
    case "$FAILED_GATES" in *console_active*) _bits="$_bits console active: idle ${IDLE_SECONDS}s < required ${IDLE_REQUIRED}s (user ${CONSOLE_USER:-?})";; esac
    case "$FAILED_GATES" in *console_present_idle_unmeasurable*) _bits="$_bits a console session exists (user ${CONSOLE_USER:-?}) but its idle time is not readable here: $IDLE_SOURCE";; esac
    case "$FAILED_GATES" in *dispatch_in_flight*) _bits="$_bits a dispatch is in flight: pids ${DISPATCH_PIDS:-?}";; esac
    case "$FAILED_GATES" in *lease_held*) _bits="$_bits a governor lease is held:${LEASE_HOLDERS}";; esac
    if [ "$MODE" = "reclaim" ]; then write_record "$MODE" "declined" "$(printf '%s' "$_bits" | sed -e 's/^ *//')"
    else write_record "$MODE" "reported" "gates not all pass:$_bits"; fi
    return 0
  fi

  if [ "$MODE" != "reclaim" ]; then
    write_record "$MODE" "reported" "report only (pass --reclaim to act); all three gates pass; $(count_lines "$TARGET_PROCESSES") target(s) and $(count_lines "$ORPHAN_PROCESSES") orphan(s) would be reclaimed"
    return 0
  fi

  if [ "$(count_lines "$TARGET_PROCESSES")" -eq 0 ] && [ "$(count_lines "$ORPHAN_PROCESSES")" -eq 0 ]; then
    write_record "$MODE" "declined" "nothing on the explicit target list and no orphan of our tooling -- already clean"
    return 0
  fi

  ALL_ROWS="$(printf '%s\n%s\n' "$TARGET_PROCESSES" "$ORPHAN_PROCESSES" | awk -F'|' 'NF>1 && $1 ~ /^[0-9]+$/ {print}')"
  ACTED_PIDS=""; _names=""
  # CLASS A, graceful first: on macOS the application's own quit path through the console user's
  # session (an Apple Event -- the request a human makes with Cmd-Q); TERM everywhere.
  if [ -n "$TARGET_PROCESSES" ]; then
    printf '%s\n' "$TARGET_PROCESSES" | while IFS='|' read -r pid cls rss age exe why; do
      [ -n "$pid" ] || continue
      if [ "$PLATFORM" = "Darwin" ] && [ -n "${CONSOLE_UID:-}" ]; then
        _appname="$(printf '%s' "$exe" | sed -n 's#.*/\([^/]*\)\.app/.*#\1#p')"
        [ -n "$_appname" ] && run_bounded 20 launchctl asuser "$CONSOLE_UID" /usr/bin/osascript -e "tell application \"$_appname\" to quit" >/dev/null 2>&1
      fi
      kill -TERM "$pid" 2>/dev/null
    done
    _n=0
    while [ "$_n" -lt "$GRACE_SECS" ]; do
      _left="$(printf '%s\n' "$TARGET_PROCESSES" | awk -F'|' '{print $1}' | while read -r _p; do kill -0 "$_p" 2>/dev/null && echo "$_p"; done | awk 'NF{n++} END{print n+0}')"
      [ "${_left:-0}" -eq 0 ] && break
      sleep 1; _n=$(( _n + 1 ))
    done
  fi
  # CLASS B: orphans of our own tooling. TERM first, then KILL for what survives.
  if [ -n "$ORPHAN_PROCESSES" ]; then
    printf '%s\n' "$ORPHAN_PROCESSES" | awk -F'|' '{print $1}' | while read -r _p; do kill -TERM "$_p" 2>/dev/null; done
    sleep 2
  fi
  if [ "$NO_ESCALATE" -eq 0 ]; then
    for _p in $(printf '%s\n' "$ALL_ROWS" | awk -F'|' '{print $1}'); do
      if kill -0 "$_p" 2>/dev/null; then kill -KILL "$_p" 2>/dev/null && ESCALATED_PIDS="$ESCALATED_PIDS $_p"; fi
    done
  fi
  sleep 3
  RECLAIMED_KB=0
  for _p in $(printf '%s\n' "$ALL_ROWS" | awk -F'|' '{print $1}'); do
    ACTED_PIDS="$ACTED_PIDS $_p"
    _row="$(printf '%s\n' "$ALL_ROWS" | awk -F'|' -v p="$_p" '$1==p {print; exit}')"
    _kb="$(printf '%s' "$_row" | awk -F'|' '{print $3}')"
    _nm="$(printf '%s' "$_row" | awk -F'|' '{ n=split($5,a,"/"); print a[n] }')"
    RECLAIMED_KB=$(( RECLAIMED_KB + ${_kb:-0} ))
    _names="$_names ${_nm:-pid-}${_p}"
  done
  # Re-measure what is left, so the after-number is a measurement and not arithmetic.
  TABLE="$(proc_table)"
  classify
  AFTER_KB=$(( $(rss_sum "$TARGET_PROCESSES") + $(rss_sum "$ORPHAN_PROCESSES") ))
  write_record "$MODE" "acted" "reclaimed $(count_lines "$ALL_ROWS") process(es) [$_names ]: $(( RECLAIMED_KB / 1024 )) MiB resident let go; reclaimable_rss_kb $RECLAIM_KB -> $AFTER_KB${ESCALATED_PIDS:+; escalated to SIGKILL for pids$ESCALATED_PIDS}"
  return 0
}

# ---------------------------------------------------------------------------------------------
# Drift table and cross-node collection
# ---------------------------------------------------------------------------------------------
show_drift() {
  _n=0; [ -f "$DECISIONS" ] && _n="$(count_lines "$(cat "$DECISIONS" 2>/dev/null)")"
  out "mesh-hygiene $VERSION -- DRIFT REPORT (read-only): $_n record(s) in $DECISIONS"
  if [ "$_n" -eq 0 ]; then out "no readings yet: run the script once in any mode to start the series"; return 0; fi
  printf '%-21s %-9s %10s %9s %6s %14s %3s %3s %-19s %s\n' "at(UTC)" outcome availMiB d-avail place reclaimableKB T O trend reason
  _prev=""
  tail -"$DRIFT_LAST" "$DECISIONS" | while read -r _r; do
    _f="$(mktemp)"; printf '%s\n' "$_r" >"$_f"
    _at="$(jfield_str "$_f" at)"; _oc="$(jfield_str "$_f" outcome)"; _av="$(jfield "$_f" avail_mib)"
    _pl="$(jfield "$_f" placeable_children)"; _rk="$(jfield "$_f" reclaimable_rss_kb)"
    _tl="$(jfield "$_f" targets_live)"; _ol="$(jfield "$_f" orphans_live)"
    _tr="$(jfield_str "$_f" trend)"; _rs="$(jfield_str "$_f" reason)"
    rm -f "$_f"
    _d="-"; if [ -n "$_prev" ] && [ -n "$_av" ]; then _d=$(( _av - _prev )); fi
    _prev="$_av"
    printf '%-21s %-9s %10s %9s %6s %14s %3s %3s %-19s %s\n' "$_at" "$_oc" "$_av" "$_d" "$_pl" "$_rk" "$_tl" "$_ol" "$_tr" "$(printf '%s' "$_rs" | cut -c1-76)"
  done
  out "A node is drifting when the rate is negative for hours and zero-children-in is finite, while placeable is still greater than zero."
  out "Files a human reads: $LATEST (latest), $DECISIONS (history), $LOG (one line per run)"
  return 0
}

show_collect() {
  out "mesh-hygiene $VERSION -- DRIFT ACROSS NODES (read-only; each node's latest record, read over ssh)"
  printf '%-18s %-21s %9s %6s %12s %s\n' node at-UTC availMiB place reclaimKB drift
  # Node list: `name=ssh-alias=kind`, kind being `win` or `posix` (a list entry with no kind is
  # treated as posix). THE KIND MATTERS: the remote read is a different program on each platform, and
  # MEASURED 2026-09-17 04:31Z one line containing both shapes cannot work -- cmd.exe cannot parse
  # `2>/dev/null`, so every Windows row came back "no record" while the POSIX rows worked.
  # The default list is a variable, not a quoted literal inside ${...:-...}: quoting it there makes
  # the whole list ONE word, so the loop ran once and ssh got every name as a single hostname.
  _default_nodes="zabz-yoga-1=laptop-ts=win zabz-tech=zabz-tech-ts=win secratary=secratary-ts=posix zabz-tech-linux=linux-pc-ts=posix lakewooechsmini=mac-mini-ts=posix"
  for _n in ${COLLECT_NODES:-$_default_nodes}; do
    _name="${_n%%=*}"
    _rest="${_n#*=}"
    _alias="${_rest%%=*}"
    _kind="${_rest#*=}"
    [ "$_kind" = "$_alias" ] && _kind="posix"
    if [ "$_kind" = "win" ]; then
      _remote='cmd /c type "%USERPROFILE%\.dsh-sync-status\mesh-hygiene.json"'
    else
      _remote='cat /var/log/mesh-hygiene.json 2>/dev/null || cat $HOME/.dsh-sync-status/mesh-hygiene.json 2>/dev/null'
    fi
    _raw="$(ssh -o BatchMode=yes -o ConnectTimeout=15 "$_alias" "$_remote" 2>/dev/null)"
    _rc=$?
    case "$_raw" in
      \{*) _f="$(mktemp)"; printf '%s\n' "$_raw" >"$_f"
           printf '%-18s %-21s %9s %6s %12s trend=%s rate=%sMiB/h zero_in=%sh\n' "$_name" \
             "$(jfield_str "$_f" at)" "$(jfield "$_f" avail_mib)" "$(jfield "$_f" placeable_children)" \
             "$(jfield "$_f" reclaimable_rss_kb)" "$(jfield_str "$_f" trend)" "$(jfield "$_f" avail_mib_per_hour)" "$(jfield "$_f" hours_to_zero_children)"
           rm -f "$_f" ;;
      *)   printf '%-18s %-21s %9s %6s %12s %s\n' "$_name" "-" "-" "-" "-" "no record (ssh exit $_rc: either the node has no record, or this host cannot reach/ authenticate to $_alias)" ;;
    esac
  done
  out "A node whose trend is 'shrinking' with a finite zero_in is the node to look at before the broker stops choosing it."
  return 0
}

# ---------------------------------------------------------------------------------------------
# Self-test: two named hogs in a scratch tree; the matching one MUST die, the other MUST survive.
# The scratch directory must not contain a pattern string, or the SPARED hog would match its own path.
# ---------------------------------------------------------------------------------------------
do_self_test() {
  SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/hygiene-selftest-XXXXXX")"
  HOG_A="$SCRATCH/mesh-hygiene-hog-a.sh"
  HOG_B="$SCRATCH/unlisted-hog-b.sh"
  # Each hog records its OWN pid. MEASURED 2026-09-17 04:03Z: finding them by matching `ps` output
  # for the path also matches the matcher (awk's own argv carries the path), which reported two pids
  # per hog -- and the second changed between calls. A pid the hog writes itself cannot be faked.
  printf '#!/bin/sh\necho $$ > "%s/hog-a.pid"\nsleep 300\n' "$SCRATCH" >"$HOG_A"; chmod +x "$HOG_A"
  printf '#!/bin/sh\necho $$ > "%s/hog-b.pid"\nsleep 300\n' "$SCRATCH" >"$HOG_B"; chmod +x "$HOG_B"
  out "SELF-TEST (spawns and then cleans up ITS OWN two hogs)"
  out "  scratch      : $SCRATCH"
  out "  hog A        : mesh-hygiene-hog-a.sh   -- matches the SHIPPED orphan pattern (mesh-hygiene)"
  out "  hog B        : unlisted-hog-b.sh       -- matches nothing; it MUST survive"
  out "  pattern used : the shipped default"
  out "  gates        : pre-set to PASS, so the matching/kill/accounting code below is the shipped"
  out "                 code running on a machine that is NOT idle"
  for _h in "$HOG_A" "$HOG_B"; do
    sh -c "sh '$_h' >/dev/null 2>&1 &"      # the intermediate sh exits at once -> the hog is a real orphan
  done
  _w=0
  while [ "$_w" -lt 10 ]; do
    [ -f "$SCRATCH/hog-a.pid" ] && [ -f "$SCRATCH/hog-b.pid" ] && break
    sleep 1; _w=$(( _w + 1 ))
  done
  HOG_A_PID="$(cat "$SCRATCH/hog-a.pid" 2>/dev/null)"
  HOG_B_PID="$(cat "$SCRATCH/hog-b.pid" 2>/dev/null)"
  sleep 5                                       # let both hogs age past the test's own floor
  out "  hogs         : A pid ${HOG_A_PID:-none}  B pid ${HOG_B_PID:-none}  (both parentless: real orphans)"
  SAVED_STATUS="$STATUS_DIR"; SAVED_LOG="$LOG"; SAVED_DEC="$DECISIONS"; SAVED_LAT="$LATEST"
  STATUS_DIR="$SCRATCH"; LOG="$SCRATCH/mesh-hygiene.log"; DECISIONS="$SCRATCH/mesh-hygiene.jsonl"; LATEST="$SCRATCH/mesh-hygiene.json"
  measure_all >/dev/null 2>&1
  SAVED_PRESENT="$CONSOLE_PRESENT"; SAVED_IDLE="$IDLE_SECONDS"; SAVED_DISP="$DISPATCH_PIDS"
  SAVED_DISPC="$DISPATCH_COUNT"; SAVED_LEASE="$LEASE_HELD"; SAVED_MODE="$MODE"; SAVED_AGE="$MIN_ORPHAN_AGE"
  SAVED_TB="$TARGETS_BOUND"; SAVED_TO="$TARGETS_OVERRIDE"
  CONSOLE_PRESENT="false"; IDLE_SECONDS=""; IDLE_SOURCE="pre-set-to-pass-for-selftest"
  DISPATCH_PIDS=""; DISPATCH_COUNT=0; LEASE_HELD=0; SELFTEST_BYPASS="true"
  MODE="reclaim"; MIN_ORPHAN_AGE=3; TARGETS_BOUND=1; TARGETS_OVERRIDE=""   # class A OFF for the test
  do_reclaim
  STATUS_DIR="$SAVED_STATUS"; LOG="$SAVED_LOG"; DECISIONS="$SAVED_DEC"; LATEST="$SAVED_LAT"
  CONSOLE_PRESENT="$SAVED_PRESENT"; IDLE_SECONDS="$SAVED_IDLE"; DISPATCH_PIDS="$SAVED_DISP"
  DISPATCH_COUNT="$SAVED_DISPC"; LEASE_HELD="$SAVED_LEASE"; MODE="$SAVED_MODE"; MIN_ORPHAN_AGE="$SAVED_AGE"
  TARGETS_BOUND="$SAVED_TB"; TARGETS_OVERRIDE="$SAVED_TO"; SELFTEST_BYPASS="false"
  IDLE_SOURCE="$( [ -n "$SAVED_IDLE" ] && echo "restored-after-selftest" || echo "$IDLE_SOURCE" )"
  sleep 2
  rc=0
  if [ -n "${HOG_A_PID:-}" ] && kill -0 "$HOG_A_PID" 2>/dev/null; then
    out "  A mesh-hygiene-hog pid $HOG_A_PID alive now -> FAIL"; rc=1
  else
    out "  A mesh-hygiene-hog pid ${HOG_A_PID:-none} gone   -> PASS"
  fi
  if [ -n "${HOG_B_PID:-}" ] && kill -0 "$HOG_B_PID" 2>/dev/null; then
    out "  B unlisted-hog      pid $HOG_B_PID alive now -> PASS (spared)"
  else
    out "  B unlisted-hog      pid ${HOG_B_PID:-none} gone   -> FAIL"; rc=1
  fi
  out "  the reclaim log line this test wrote (scratch, not the production series):"
  sed -e 's/^/    /' "$SCRATCH/mesh-hygiene.log" 2>/dev/null
  for _p in "${HOG_A_PID:-}" "${HOG_B_PID:-}"; do [ -n "$_p" ] && kill -KILL "$_p" 2>/dev/null; done
  rm -rf "$SCRATCH" 2>/dev/null
  if [ "$rc" -eq 0 ]; then out "SELF-TEST: ALL CASES PASSED"; else out "SELF-TEST: FAILED"; fi
  return "$rc"
}

# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------
case "$MODE" in
  drift)    show_drift; exit 0 ;;
  collect)  show_collect; exit 0 ;;
  selftest) do_self_test; exit $? ;;
esac

measure_all || { write_record "$MODE" "error" "the process table could not be measured, so nothing can be identified: refusing to act"; exit 3; }
if [ -z "$AVAIL_MIB" ]; then
  write_record "$MODE" "error" "reclaimable memory could not be measured (source: $AVAIL_SOURCE)"; exit 3
fi
[ "$MODE" = "report" ] && print_report
do_reclaim
exit 0
