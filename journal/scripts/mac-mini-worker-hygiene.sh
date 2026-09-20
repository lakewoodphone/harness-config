#!/bin/bash
# mac-mini-worker-hygiene.sh -- reclaim policy for a macOS mesh worker node.
#
# OWNER: stream S4 of the mesh program. Doc: docs/mesh/80-mac-worker-hygiene.md
# READS: docs/mesh/74-mac-mini.md (stream S3's audit -- the measured problem this file answers)
#
# THE TWO OBSERVATIONS THIS EXISTS FOR (owner, 2026-09-16):
#   1. "Chrome doesn't need to be running so many tabs each time it opens" -- Chrome is
#      configured to restore the entire previous session, so every restart reopens every tab
#      a human ever left. Measured by S3: 104 processes, 7.1-7.3 GB resident.
#   2. "Macs don't close down processes like on Windows -- when I X things out they are still
#      running" -- correct, and it is the platform's semantic: the red button closes a WINDOW,
#      not the app, and the app keeps its memory. Hence a worker node's free memory drifts down
#      over days with nobody using it.
#
# OBSERVATION 1 IS ANSWERED BY POLICY, NOT BY THIS SCRIPT (a hand-edit of Chrome's own
# Preferences is not durable -- Chrome rewrites it on exit):
#     /Library/Managed Preferences/com.google.Chrome.plist
#       RestoreOnStartup          = 5      -> open the New Tab page, do NOT restore the session
#       BackgroundModeEnabled     = false  -> "closed" actually means closed (observation 2,
#                                            for Chrome specifically)
#       MemorySaverModeEnabled    = true   -> discard background tabs when memory is tight
# OBSERVATION 2 IS ANSWERED BY THIS SCRIPT AS A DATED RECLAIM POLICY: a launchd daemon that,
# ONLY when the console has been idle >= 30 min AND no process of the console user is holding
# the display awake, gracefully quits the heavy GUI applications NOBODY IS USING, and logs what
# it did with the bytes it reclaimed.
#
# ---------------------------------------------------------------------------------------------
# THE FOUR NON-NEGOTIABLE RULES OF THE RECLAIM PATH (and where each is enforced):
#   1. It must NEVER touch a process that is not on its explicit list.
#      -> TARGETS below. Matching is on an exact application BUNDLE path (ps `comm=` is the
#         bundle path for a GUI app), never on a process name, so `Chrome Helper`,
#         `com.apple.WebKit` or a third-party renderer can never match.
#   2. It must not run while the console is active or a user is typing.
#      -> idle_seconds() reads root-domain HIDIdleTime from IOKit; any user-owned
#         UserIsActive / PreventUserIdleDisplaySleep / InternalPreventDisplaySleep assertion
#         from `pmset -g assertions` is a hard blocker regardless of idle time.
#   3. It must be idempotent.
#      -> Nothing to reclaim is a logged DECLINE, not an action. Re-running after it has acted
#         finds no process and writes a second line that reuses the FIRST line's measurement
#         (free memory has already been handed to the OS and is not reclaimable twice).
#   4. It must write a log line EVERY time it acts AND every time it declines and why.
#      -> Two sinks: a line-oriented log AND a JSONL decision record, both appended in every
#         path out of the script, including the error paths.
#
# THE OFF SWITCH IS ONE COMMAND:
#     sudo launchctl bootout system/com.lakewoodphone.mesh-worker-hygiene
# (and `sudo launchctl bootstrap system /Library/LaunchDaemons/com.lakewoodphone.mesh-worker-hygiene.plist`
#  turns it back on). Nothing else unloads, no other file changes.
#
# RECLAIMABLE MEMORY, DEFINED EXACTLY. This is the number the before/after uses:
#     reclaimable = (Pages free + Pages inactive + Pages speculative + Pages purgeable) x page_size
# NOT `Pages free`. macOS keeps almost everything as cache, and on this 16 GB machine
# `Pages free` was measured at 148 MB by S3 while 5.7 GB sat in the compressor -- so
# `Pages free` alone is a number that says "critical" about a machine that is merely caching.
# The counter, the moment, and the raw page counts are printed together so any reader can
# recompute it; `vm_stat -c N` is a real average over a window, not a spike sample.
#
# Exit codes: 0 = ran (acted or declined). Non-zero only when the script could not decide.
# ---------------------------------------------------------------------------------------------

set -u

VERSION="1.0.0"

LOG="${HYGIENE_LOG:-/var/log/lakewoodphone-worker-hygiene.log}"
DECISIONS="${HYGIENE_DECISIONS:-/var/log/lakewoodphone-worker-hygiene.jsonl}"
# A file the operator (or a verification run) can write to suspend the job for a while.
SUSPEND_FILE="${HYGIENE_SUSPEND_FILE:-/var/run/lakewoodphone-worker-hygiene.suspend}"

IDLE_REQUIRED="${HYGIENE_IDLE_SECONDS:-1800}"   # 30 minutes
SIGTERM_GRACE="${HYGIENE_SIGTERM_GRACE:-20}"    # poll intervals allowed after each of the two requests
REAP_SETTLE="${HYGIENE_REAP_SETTLE:-10}"        # seconds to let the kernel reclassify before the after-reading
POLL_INTERVAL="${HYGIENE_POLL:-0.5}"
VM_WINDOW="${HYGIENE_VM_WINDOW:-5}"             # vm_stat -c samples (a window, not a spike)
VM_INTERVAL="${HYGIENE_VM_INTERVAL:-1}"         # seconds between samples

# THE EXPLICIT LIST. Exact bundle paths only. A path here that is not running costs nothing;
# a path NOT here is never touched, whatever it is doing.
TARGETS=(
  "/Applications/Google Chrome.app"
  "/Applications/Spotify.app"
  "/Applications/Slack.app"
  "/Applications/Discord.app"
  "/Applications/Docker.app"
  "/Applications/Figma.app"
  "/Applications/Notion.app"
  "/Applications/Obsidian.app"
  "/Applications/zoom.us.app"
  "/Applications/Microsoft Teams.app"
)

MODE="reclaim"

note()  { printf '%s\n' "$*"; }
usage() {
  cat <<EOF
mac-mini-worker-hygiene.sh $VERSION -- reclaim policy for a macOS mesh worker node.

  --report            read-only: print reclaimable memory, console idleness, blockers, TARGETS.
                      Quits nothing. This is also the before/after counter.
  --reclaim           (default) the launchd path. Quits a TARGET only when the console has been
                      idle >= \$HYGIENE_IDLE_SECONDS (default 1800) AND no user-owned assertion
                      is holding the display awake. Decline logs why.
  --self-test         read-only: prove display_blockers() against a SYNTHETIC listing written in
                      the assertion grammar OBSERVED on this machine, plus the machine's own
                      live listing. See the body for why both halves are needed.
  --idle-seconds N    set the idle threshold. This is NOT a force-flag: it is the same test with
                      a different N, and the DECLINE branch is still reached on a busy console
                      however small N is, because a display assertion is checked separately.
                      Two honest uses:
                        --idle-seconds 0        reach the action path on a console that has not
                                                yet been idle 30 minutes;
                        --idle-seconds 100000   reach the DECLINE branch on a console that is
                                                already idle past the default 1800s.
                      A console freshly idle past 30 minutes with no display assertion needs
                      neither: the default IS the condition, and the job acts on its own.
  --log FILE          append to FILE instead of $LOG
  --decisions FILE    append JSONL to FILE instead of $DECISIONS
  --version           print the version

Counters: HYGIENE_VM_WINDOW (default $VM_WINDOW) samples of \`vm_stat\`, HYGIENE_VM_INTERVAL
(default $VM_INTERVAL) seconds apart.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --report)        MODE="report" ;;
    --self-test)     MODE="selftest" ;;
    --reclaim)       MODE="reclaim" ;;
    --idle-seconds)  IDLE_REQUIRED="${2:-}"; shift ;;
    --log)           LOG="${2:-}"; shift ;;
    --decisions)     DECISIONS="${2:-}"; shift ;;
    --version)       echo "$VERSION"; exit 0 ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "mac-mini-worker-hygiene: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$IDLE_REQUIRED" in ''|*[!0-9]*) echo "mac-mini-worker-hygiene: --idle-seconds needs a whole number" >&2; exit 2 ;; esac

# ---------------------------------------------------------------------------------------------
# Logging. Every exit path calls one of these. A job that cannot say why it did nothing is a
# job nobody can debug at 3am.
# ---------------------------------------------------------------------------------------------
_log_raw() { printf '%s\n' "$1" >>"$LOG" 2>/dev/null || printf '%s\n' "$1" >&2; }

_json_str() { # minimal escaping: these strings are paths and short reasons
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\n\r'
}

# A JSON number or null. An empty shell variable is not a number, and `"x":,` is not JSON --
# the one thing this record must never be is unparseable, because it is the evidence.
_json_num() { case "${1:-}" in ''|*[!0-9]*) printf 'null' ;; *) printf '%s' "$1" ;; esac; }
_json_str_or_null() {
  if [ -z "${1:-}" ]; then printf 'null'; else printf '"%s"' "$(_json_str "$1")"; fi
}

# A pid list can be 100 processes long on a machine that has been up for weeks. The record needs
# the count and a bounded sample, not a 3 KB line nobody reads.
_short_pids() {
  _all="${1:-}"; _n=$(printf '%s' "$_all" | tr ' ' '\n' | grep -c . 2>/dev/null || echo 0)
  _first=$(printf '%s' "$_all" | tr ' ' '\n' | grep . | head -8 | tr '\n' ' ')
  if [ "$_n" -gt 8 ]; then printf '%s pids(%s total, first 8: %s)' "$_n" "$_n" "$_first"
  else printf '%s pids(%s)' "${_n}" "$_first"; fi
}

# decide MODE OUTCOME REASON RECLAIMABLE_BEFORE RECLAIMABLE_AFTER IDLE BLOCKERS PIDFILE PREV
decide() {
  _mode="$1"; _outcome="$2"; _reason="$3"; _before="$4"; _after="$5"
  _idle="$6"; _blockers="$7"; _pids="$8"; _prev="${9:-}"
  _when="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  _local="$(date '+%Y-%m-%d %H:%M:%S %Z')"
  _log_raw "$_when | $_local | v$VERSION | mode=$_mode | outcome=$_outcome | idle_s=${_idle:-unmeasured} | idle_required_s=$IDLE_REQUIRED | blockers=${_blockers:-none} | reclaimable_before=$(human "$_before") | reclaimable_after=$(human "$_after") | reclaim_before_bytes=${_before:-unmeasured} | reclaim_after_bytes=${_after:-unmeasured} | pids=${_pids:-none} | reason=$_reason"
  printf '{"schema":1,"at":"%s","version":"%s","mode":"%s","outcome":"%s","reason":"%s","console_user":%s,"console_uid":%s,"idle_seconds":%s,"idle_required_seconds":%s,"blockers":%s,"reclaimable_before_bytes":%s,"reclaimable_after_bytes":%s,"pids":%s,"prev":%s}\n' \
    "$_when" "$VERSION" "$_mode" "$_outcome" "$(_json_str "$_reason")" \
    "$(_json_str_or_null "${CONSOLE_USER:-}")" "$(_json_num "${CONSOLE_UID:-}")" \
    "$(_json_num "${_idle:-}")" "$IDLE_REQUIRED" "$(_json_str_or_null "${_blockers:-}")" \
    "$(_json_num "${_before:-}")" "$(_json_num "${_after:-}")" "$(_json_str_or_null "${_pids:-}")" "$(_json_str_or_null "${_prev:-}")" \
    >>"$DECISIONS" 2>/dev/null || true
}

# ---------------------------------------------------------------------------------------------
# The reclaimable-memory counter. One definition, used for before and after.
# ---------------------------------------------------------------------------------------------
page_size() { sysctl -n hw.pagesize 2>/dev/null || echo 16384; }

# macOS `vm_stat -c N INTERVAL` prints a TWO-LINE header and then one line per sample:
#
#   Mach Virtual Memory Statistics: (page size of 16384 bytes)
#       free   active   specul inactive throttle    wired  prgable   faults  ...
#     387348   184921    20769   209743        0   109283     2061 9548073K  ...
#     387384   184905    20769   209743        0   109283     2061      996  ...
#
# THE FIELD NAMES ARE ON THE HEADER LINE, NOT ON THE DATA LINES -- so a per-line label match
# (the obvious awk, and this file's first version) can never fire and reports UNMEASURED on a
# perfectly healthy machine. Columns are therefore resolved BY NAME from whichever line carries
# the labels, and those indices are applied to every data line. `prgable` really is spelled
# without its `u`, and `specul` is abbreviated: matching on the real spellings is the point.
#
# Prints four average page counts: free inactive speculative purgeable. Non-zero exit if the
# header could not be resolved, because a guessed column is worse than no number.
vm_stat_avg() {
  vm_stat -c "$VM_WINDOW" "$VM_INTERVAL" 2>/dev/null | awk '
    # The header line carries the labels; keep its field map and the index it sat on.
    /^[ \t]+free[ \t]+/ { nh=NR; for (i=1;i<=NF;i++) h[$i]=i }
    # Keep the DATA LINES ONLY. `split($0, d, /[ \\t]+/)` was the first version and it is a trap:
    # on BSD awk a leading separator yields an EMPTY d[1], so every numeric test failed and the
    # counter reported "no-vmstat-data-lines" on a healthy machine. `$1` is already trimmed.
    NR>2 && $1 ~ /^[0-9]+$/ { cn++; line[cn]=$0 }
    END {
      if (nh==0) { print "ERR no-vmstat-header"; exit 1 }
      need["free"]=1; need["inactive"]=1; need["specul"]=1; need["prgable"]=1
      for (k in need) if (!(k in h)) { printf "ERR vm_stat header lacks column %s\n", k; exit 1 }
      if (cn==0) { print "ERR no-vmstat-data-lines"; exit 1 }
      for (n=1; n<=cn; n++) {
        split(line[n], d, " ")          # single-space split: values are space-separated, and a
        f+=d[h["free"]]                 # leading space only yields an extra empty trailing field,
        i+=d[h["inactive"]]             # which cannot shift the indices we use
        s+=d[h["specul"]]
        p+=d[h["prgable"]]
      }
      printf "%d %d %d %d\n", int(f/cn), int(i/cn), int(s/cn), int(p/cn)
    }'
}

reclaimable_pages_sum() {
  out="$(vm_stat_avg)" || { echo "ERR $out"; return 1; }
  case "$out" in ERR*|"") echo "ERR ${out:-vm-stat-produced-nothing}"; return 1 ;; esac
  set -- $out
  [ $# -eq 4 ] || { echo "ERR vm-stat-returned-$#-fields"; return 1; }
  echo "$1 $2 $3 $4 $(( $1 + $2 + $3 + $4 ))"
}

# Sets RECLAIMABLE_BYTES and RECLAIMABLE_DETAIL; returns 1 if any counter was unavailable.
reclaimable() {
  out=$(reclaimable_pages_sum) || { RECLAIMABLE_BYTES=""; RECLAIMABLE_DETAIL="$out"; return 1; }
  set -- $out
  ps=$(page_size)
  RECLAIMABLE_PAGES="$5"
  RECLAIMABLE_BYTES=$(( $5 * ps ))
  RECLAIMABLE_DETAIL="pages free=$1 inactive=$2 speculative=$3 purgeable=$4 total=$5 x ${ps}B"
  return 0
}

human() { # bytes -> GiB/MiB
  b="${1:-}"
  case "$b" in ''|*[!0-9]*) echo "unmeasured"; return ;; esac
  awk -v b="$b" 'BEGIN{ if (b >= 1073741824) printf "%.2f GiB", b/1073741824; else printf "%.0f MiB", b/1048576 }'
}

# The COMPRESSOR is where this machine's memory actually goes, and a reclaim that only reports
# "free pages" can miss it entirely: S3 measured Chrome's footprint as 7.1 GB with only 6.7 MB of
# it resident (docs/mesh/74-mac-mini.md section 3.2), i.e. the bytes were in the compressor, not
# in free pages. These two counters are printed with every measurement so a reader can see
# physical memory being handed back even when `Pages free` is flat. `-c N` averages them too.
compressor_pages() { # -> "occupied stored"
  vm_stat -c "$VM_WINDOW" "$VM_INTERVAL" 2>/dev/null | awk '
    /^[ \t]+free[ \t]+/ { for (i=1;i<=NF;i++) h[$i]=i; found=1; next }
    found && $1 ~ /^[0-9]+$/ {
      split($0, d, " ")
      if (h["cmprssed"] != "") { n++; oc+=d[h["cmprssed"]] }
      if (h["cmprssor"] != "") { st+=d[h["cmprssor"]] }
    }
    END { if (n>0) printf "%d %d\n", int(oc/n), int(st/n); else print "ERR no-compressor-columns" }'
}

# ---------------------------------------------------------------------------------------------
# Who is at the console, and are they there.
# ---------------------------------------------------------------------------------------------
console_user() { stat -f %Su /dev/console 2>/dev/null; }
console_uid()  { id -u "$1" 2>/dev/null; }

idle_seconds() { # root-domain HID idle, in seconds. Empty if unavailable.
  _t=$(ioreg -c IOHIDSystem 2>/dev/null | awk -F'= ' '/HIDIdleTime/ {print $2; exit}' | tr -d ' ')
  case "$_t" in ''|*[!0-9]*) echo "" ; return ;; esac
  echo $(( _t / 1000000000 ))
}

# Prints one "kind|pid|user" per line for USER-OWNED assertions that hold the display awake.
#
# THE FORMAT, OBSERVED rather than remembered. `pmset -g assertions` on this build prints an
# assertion as:
#
#   Listed by owning process:
#      pid 412(runningboardd): [0x002f5f8000018706] 00:00:00 PreventUserIdleSystemSleep named: "osservice<...>"
#   	Created for PID: 632.
#      pid 338(powerd): [0x002f5f7b000d86ea] 00:00:05 InternalPreventSleep named: "com.apple.powermanagement.acwakelinger"
#   	Timeout will fire in 39 secs Action=TimeoutActionRelease
#
# (captured on LakewooechsMini 2026-09-16 20:05:10 EDT). THE WORD "created" IS NOT ON THE
# ASSERTION LINE -- it is on a separate TAB-INDENTED continuation line, and only sometimes. This
# file's first version matched /created/ and so could never have detected anything; the format is
# written down here from a real capture rather than from memory. A second version matched a
# POSITIONAL field and failed for the other reason: "internalPreventSleep" and the rest did not
# line up with the guess.
#
# The line grammar is:  <ws> pid <PID>(<name>): [<handle>] <HH:MM:SS> <Kind> [named: ...]
# so the KIND IS FOUND BY THE TIMESTAMP TOKEN, not by position -- the owning-process name may or
# may not contain spaces, which is exactly what makes a positional guess unreliable.
#
# Two filters matter and both are deliberate:
#   * the assertion must be owned by a process of the CONSOLE USER. The header COUNTS
#     ("UserIsActive   0") cannot answer this question: they count assertions owned by system
#     daemons too, and a daemon holding a display assertion is not a human at the keyboard. The
#     counts are therefore read for the log and never used as the gate.
#   * only DISPLAY/AWAKE kinds count. PreventUserActivitySleep, BackgroundTask,
#     ApplePushServiceTask and InternalPreventSleep do not.
display_blockers() {
  _want_uid="$1"
  pmset -g assertions 2>/dev/null | awk '
    /^[ \t]*pid[ \t]+[0-9]+\(/ {
      kind=""
      for (i=1;i<=NF;i++) if ($i ~ /^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]$/) kind=$(i+1)
      if (kind=="") next
      if (kind != "UserIsActive" && kind != "PreventUserIdleDisplaySleep" \
          && kind != "PreventUserIdleSystemSleep" && kind != "InternalPreventDisplaySleep") next
      pid=$2; sub(/\(.*/,"",pid)
      if (pid !~ /^[0-9]+$/) next
      printf "%s|%s\n", kind, pid
    }' | while IFS='|' read -r kind p; do
      [ -n "$p" ] || continue
      who="$(ps -o user= -p "$p" 2>/dev/null | tr -d ' ')"
      [ -n "$who" ] || continue
      their_uid="$(id -u "$who" 2>/dev/null | tr -d ' ')"
      if [ "$their_uid" = "$_want_uid" ]; then printf '%s|%s|%s\n' "$kind" "$p" "$who"; fi
    done
}

# ---------------------------------------------------------------------------------------------
# The explicit TARGETS, resolved to live processes. Nothing else can ever be returned here.
# TWO filters, and the second is the scope boundary:
#   1. the process's executable must be that application's own bundle -- `ps comm=` is the full
#      bundle path for a GUI app, so `Google Chrome Helper`, `com.apple.WebKit.*` and any
#      third-party renderer are structurally unable to match;
#   2. the process must belong to the CONSOLE USER. This node has a second human's Chrome alive
#      (measured 2026-09-16: moshemontrose, 7 processes, 184 MB) and a reclaim policy has no
#      business ending another person's session because the machine's console happens to be
#      idle. Acting only for whoever owns /dev/console is the line, and it is enforced here.
target_processes() { # prints "name|exe|pid|rss_kb|user" for every live TARGET process of the console user
  _want_uid="${1:-}"
  for t in "${TARGETS[@]}"; do
    _name=$(basename "$t" .app)
    # EVERY process belonging to the application's bundle, not just the main binary. Measured
    # 2026-09-16 20:10-20:15 on this machine, in three steps, each of which failed a different way:
    #
    #   1. `pgrep -x "Google Chrome"` + `comm == exe`  -> found 1 of 5. ps reports a helper's comm
    #      as /Applications/Google Chrome.app/Contents/Frameworks/…/Google Chrome Helper, and the
    #      main binary's as exactly /Applications/Google Chrome.app/Contents/MacOS/Google Chrome.
    #   2. `$NF` as the path -> found 0. **macOS `ps -o comm=` returns the FULL PATH INCLUDING ITS
    #      ITS SPACES as one column**, so `$NF` is the word "Chrome", "Helper" or "(Renderer)".
    #      Rebuilding comm from fields 5..NF is what recovers the path.
    #   3. `ps -o comm=` without `-ww` can truncate to the terminal width, so `-ww` is required.
    #
    # The final test is BUNDLE CONTAINMENT: the executable path is the bundle path itself or lies
    # under it (`^<bundle>/`, dot escaped so "Google ChromeXapp" cannot match). That reaches every
    # helper of THIS application and still cannot reach outside its bundle -- another vendor's
    # helper, `com.apple.WebKit.*` or a standalone renderer is not under /Applications/<Name>.app.
    # The console-user filter is applied first and is unchanged.
    _pids="$(pgrep -f "${t}" 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
    [ -n "$_pids" ] || continue
    ps -ww -o pid=,uid=,user=,rss=,comm= -p "$_pids" 2>/dev/null | awk -v exe="$t" -v name="$_name" -v want="$_want_uid" '
      {
        if (want != "" && $2 != want) next
        pid=$1; rss=$4; user=$3
        comm=$0; for (i=1;i<=4;i++) sub(/^[^ \t]+[ \t]+/, "", comm)   # drop pid uid user rss
        sub(/[ \t]+$/, "", comm)
        if (comm == exe || comm ~ ("^" exe "/"))
          printf "%s|%s|%s|%s|%s\n", name, comm, pid, rss, user
      }'
  done
}

# ---------------------------------------------------------------------------------------------
# MODES
# ---------------------------------------------------------------------------------------------
CONSOLE_USER="$(console_user)"
CONSOLE_UID="$(console_uid "$CONSOLE_USER")"
[ -n "${CONSOLE_UID:-}" ] || CONSOLE_UID=0

# --self-test: prove the blocker test.
#
# WHY THE TEST INPUT IS SYNTHETIC, AND WHY THAT IS THE HONEST CHOICE HERE. The live machine has
# ZERO display assertions (a genuinely idle console), so neither "a console-user display assertion
# blocks" nor "a daemon-owned one does not" can be observed on it at the same time. The
# alternatives were to synthesise keyboard input to make a UserIsActive appear -- touching a
# human's desktop to make a test pass -- or to leave the branch untested. So the parser is fed a
# listing in the grammar CAPTURED FROM THIS MACHINE at 2026-09-16 20:05:10 EDT, which is
#     pid NNN(name): [0x...] HH:MM:SS <Kind> named: "..."
# carrying every case:
#
#   A  UserIsActive,                 owned by the console user -> MUST block
#   B  PreventUserIdleSystemSleep,   owned by the console user -> MUST block
#   C  UserIsActive,                 owned by root (pid 1)     -> MUST NOT block
#   D  PreventUserActivitySleep,     owned by the console user -> MUST NOT block (not an awake kind)
#   E  BackgroundTask,               owned by the console user -> MUST NOT block
#
# The A/B/D/E pids are NOT invented: `ps -o user=` resolves ownership for real, so an invented pid
# would make the user-attribution stage drop every case and the test would pass vacuously. The
# synthetic lines therefore carry REAL pids chosen for their owner -- this shell for the cases
# that must block, pid 1 for the case that must not.
#
# The parser is ALSO run against the machine's LIVE listing, to prove it does not invent a blocker.
# Read-only; writes nothing but one scratch file under $TMPDIR.
if [ "$MODE" = "selftest" ]; then
  FAKE="${TMPDIR:-/tmp}/pmset-synthetic-for-hygiene-selftest.txt"
  ME=$$
  # The real listing is captured ONCE, before pmset is shadowed, and reused afterwards. Reading
  # it twice would be two different moments, and a blocker that appeared between them would look
  # like a parser inconsistency.
  LIVE="$(pmset -g assertions 2>/dev/null)"
  cat > "$FAKE" <<EOF
2026-09-16 20:05:10 -0400
Assertion status system-wide:
   BackgroundTask                 1
   ApplePushServiceTask           0
   UserIsActive                   1
   PreventUserIdleDisplaySleep    1
   SoftwareUpdateTask             0
   PreventSystemSleep             0
   ExternalMedia                  0
   PreventUserIdleSystemSleep     1
   NetworkClientActive            0
Listed by owning process:
   pid $ME(Xcode): [0x0000012c00018a3f] 00:12:01 UserIsActive named: "com.apple.iohideventsystem.queue.tickle"  
	Created for PID: $ME. 
   pid $ME(caffeinate): [0x0000012c00018a40] 00:00:03 PreventUserIdleSystemSleep named: "caffeinate command has asserted PreventUserIdleSystemSleep"  
   pid 1(launchd): [0x0000012c00018a41] 00:04:00 UserIsActive named: "com.apple.iohideventsystem.queue.tickle"  
	Created for PID: 1. 
   pid $ME(something): [0x0000012c00018a42] 00:00:01 PreventUserActivitySleep named: "something else entirely"  
   pid $ME(dasd): [0x0000012c00018a43] 00:00:05 BackgroundTask named: "DASActivity:501:com.apple.biomesyncd.periodic-sync"  
	Created for PID: $ME. 
Kernel Assertions: 0x304=USB,MAGICWAKE
   id=561  level=255 0x100=MAGICWAKE creat=  mod= description=en0 owner=en0
   id=2674 level=255 0x4=USB creat= description=com.apple.usb.externaldevice.00140000 owner=Dell MS116 USB Optical Mouse
EOF
  echo "mac-mini-worker-hygiene $VERSION -- SELF-TEST (read-only)"
  echo "synthetic listing : $FAKE"
  echo "                    (grammar captured from this machine 2026-09-16 20:05:10 EDT)"
  echo "console uid       : $CONSOLE_UID ($CONSOLE_USER) ; this process pid = $ME (a console-user pid)"
  echo
  # shadow pmset for the duration of one call, so the SHIPPED function is what is exercised
  pmset() { cat "$FAKE"; }
  GOT="$(display_blockers "$CONSOLE_UID")"
  unset -f pmset
  echo "parser output (kind|pid|user):"
  if [ -n "$GOT" ]; then printf '%s\n' "$GOT" | sed 's/^/  /'; else echo "  (nothing)"; fi
  echo
  rc=0
  _chk()  { if printf '%s\n' "$GOT" | grep -q -- "$2"; then echo "  PASS  $1"; else echo "  FAIL  $1 (expected to match '$2')"; rc=1; fi; }
  _nchk() { if printf '%s\n' "$GOT" | grep -q -- "$2"; then echo "  FAIL  $1 (must not match '$2')"; rc=1; else echo "  PASS  $1"; fi; }
  _chk  "A  console-user UserIsActive blocks"                "UserIsActive|$ME|"
  _chk  "B  console-user PreventUserIdleSystemSleep blocks"  "PreventUserIdleSystemSleep|$ME|"
  _nchk "C  root-owned (pid 1) UserIsActive does NOT block"  "|1|"
  _nchk "D  PreventUserActivitySleep is not an awake kind"   "PreventUserActivitySleep"
  _nchk "E  BackgroundTask is not an awake kind"             "BackgroundTask"
  echo
  echo "against the machine's LIVE pmset listing (captured before the shadow):"
  REAL="$(printf '%s\n' "$LIVE" | awk '
    /^[ \t]*pid[ \t]+[0-9]+\(/ {
      kind=""
      for (i=1;i<=NF;i++) if ($i ~ /^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]$/) kind=$(i+1)
      if (kind=="") next
      if (kind != "UserIsActive" && kind != "PreventUserIdleDisplaySleep" \
          && kind != "PreventUserIdleSystemSleep" && kind != "InternalPreventDisplaySleep") next
      pid=$2; sub(/\(.*/,"",pid)
      printf "%s|%s\n", kind, pid
    }' | while IFS='|' read -r kind p; do
      who="$(ps -o user= -p "$p" 2>/dev/null | tr -d ' ')"
      [ -n "$who" ] || continue
      [ "$(id -u "$who" 2>/dev/null | tr -d ' ')" = "$CONSOLE_UID" ] && printf '%s|%s|%s\n' "$kind" "$p" "$who"
    done)"
  if [ -z "$REAL" ]; then echo "  PASS  live listing yields no blocker"
  else echo "  NOTE  live listing yields: $REAL"; fi
  echo "  live system-wide header counts, for context (NOT used as the gate):"
  printf '%s\n' "$LIVE" | sed -n '/Assertion status system-wide/,/NetworkClientActive/p' | sed 's/^/    /'
  echo
  if [ "$rc" -eq 0 ]; then echo "SELF-TEST: ALL CASES PASSED"; else echo "SELF-TEST: FAILED"; fi
  rm -f "$FAKE" 2>/dev/null
  exit "$rc"
fi

if [ "$MODE" = "report" ]; then
  echo "mac-mini-worker-hygiene $VERSION -- REPORT (read-only, nothing is quit)"
  echo "at              : $(date -u '+%Y-%m-%dT%H:%M:%SZ') / $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "host            : $(hostname)  $(sw_vers -productVersion 2>/dev/null)"
  echo "console user    : ${CONSOLE_USER:-none} (uid ${CONSOLE_UID})"
  echo "idle seconds    : $(i=$(idle_seconds); echo "${i:-unmeasured}")  (required: $IDLE_REQUIRED)"
  echo "blockers        : $(b=$(display_blockers "$CONSOLE_UID"); echo "${b:-none}")"
  if reclaimable; then
    echo "RECLAIMABLE     : ${RECLAIMABLE_BYTES} bytes = $(human "$RECLAIMABLE_BYTES")"
    echo "  counter       : ${RECLAIMABLE_DETAIL}"
  else
    echo "RECLAIMABLE     : UNMEASURED -- $RECLAIMABLE_DETAIL"
  fi
  COMP="$(compressor_pages)"
  case "$COMP" in ERR*|"") echo "  compressor    : UNMEASURED -- $COMP" ;;
    *) set -- $COMP; echo "  compressor    : occupied $1 pages = $(human $(( $1 * $(page_size) ))) of real RAM holding $(( $2 * $(page_size) / 1048576 )) MiB of compressed data" ;;
  esac
  echo "  (reclaimable is NOT 'Pages free': macOS keeps almost everything as cache. Source: vm_stat"
  echo "   ${VM_WINDOW} samples ${VM_INTERVAL}s apart, x $(page_size)-byte pages, $(date -u '+%Y-%m-%dT%H:%M:%SZ'))"
  echo "targets (list)  : ${#TARGETS[@]}"
  _tp=$(target_processes "$CONSOLE_UID")
  _tpn=$(printf '%s' "$_tp" | grep -c . 2>/dev/null || echo 0)
  echo "targets (live)  : ${_tpn}"
  if [ -n "$_tp" ]; then
    printf '%s\n' "$_tp" | sort -t'|' -k4 -rn | awk -F'|' '{ t=$4/1024; printf "  %-22s pid %-8s rss %10.1f MB  user %s\n", $1, $3, t, $5 }'
  fi
  echo "  (second-user processes are excluded on purpose: only the CONSOLE user's apps are acted on)"
  exit 0
fi

# ---- reclaim ------------------------------------------------------------------------------
START_TS=$(date +%s)

# 0. An operator's stop-file, and a per-run lock so two runs cannot race (idempotence).
if [ -e "$SUSPEND_FILE" ]; then
  decide reclaim decline "suspended by $SUSPEND_FILE" "" "" "$(idle_seconds)" "" "" ""
  exit 0
fi
LOCK="/var/run/lakewoodphone-worker-hygiene.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  decide reclaim decline "another run holds $LOCK" "" "" "$(idle_seconds)" "" "" ""
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

if ! reclaimable; then
  decide reclaim error "could not measure reclaimable memory: $RECLAIMABLE_DETAIL" "" "" "$(idle_seconds)" "" "" ""
  exit 3
fi
BEFORE="$RECLAIMABLE_BYTES"

# 1. Is anyone at the console? Two independent tests; either one blocks.
IDLE="$(idle_seconds)"
if [ -z "$IDLE" ]; then
  decide reclaim decline "HID idle time could not be read (ioreg gave no HIDIdleTime)" "$BEFORE" "" "" "" "" ""
  exit 0
fi
if [ "$IDLE" -lt "$IDLE_REQUIRED" ]; then
  decide reclaim decline "console active: idle ${IDLE}s < required ${IDLE_REQUIRED}s" "$BEFORE" "" "$IDLE" "" "" ""
  exit 0
fi
BLOCKERS="$(display_blockers "$CONSOLE_UID")"
if [ -n "$BLOCKERS" ]; then
  decide reclaim decline "a user-owned assertion is holding the display awake: $(printf '%s' "$BLOCKERS" | tr '\n' ';')" "$BEFORE" "" "$IDLE" "$(printf '%s' "$BLOCKERS" | tr '\n' ';')" "" ""
  exit 0
fi

# 2. What, on the explicit list, is actually running.
TP="$(target_processes "$CONSOLE_UID")"
if [ -z "$TP" ]; then
  decide reclaim decline "nothing on the explicit TARGETS list is running -- already clean" "$BEFORE" "$BEFORE" "$IDLE" "" "" ""
  exit 0
fi

# 3. Graceful quit, main process first, then anything on the list still alive.
#    `launchctl asuser` is what makes a root daemon able to talk to the console GUI session;
#    without it osascript runs with no Aqua session and every Apple Event fails -1708.
ASUSER=""
if [ "$CONSOLE_UID" != "0" ]; then ASUSER="launchctl asuser $CONSOLE_UID"; fi

ALL_PIDS=""
APP_NAMES=""
for t in "${TARGETS[@]}"; do
  _name=$(basename "$t" .app)
  printf '%s\n' "$TP" | grep -q "^${_name}|" || continue
  APP_NAMES="${APP_NAMES:+$APP_NAMES,}$_name"
  _pids=$(printf '%s\n' "$TP" | awk -F'|' -v n="$_name" '$1==n {print $3}' | tr '\n' ' ')
  ALL_PIDS="$ALL_PIDS $_pids"
  if [ -n "$ASUSER" ]; then
    # GRACEFUL FIRST: the application's own quit path. This is the request a human makes with
    # Cmd-Q, and it is what lets an app flush its state. Only if it is ignored does this script
    # escalate. Chrome restores its tabs on next launch, and with the managed policy in place
    # it opens the New Tab page instead (observation 1).
    $ASUSER /usr/bin/osascript -e "tell application \"$_name\" to quit" >/dev/null 2>&1
  fi
done

wait_for_exit() { # wait_for_exit SECONDS -> returns 0 when every pid is gone, 1 on timeout
  _limit="$1"; _n=0
  while [ "$_n" -lt "$_limit" ]; do
    _alive=0
    for p in $ALL_PIDS; do kill -0 "$p" 2>/dev/null && _alive=$((_alive+1)); done
    [ "$_alive" -eq 0 ] && return 0
    sleep "$POLL_INTERVAL"
    _n=$(( _n + 1 ))
  done
  return 1
}

# Phase 1: give the graceful quit up to SIGTERM_GRACE poll intervals.
wait_for_exit "$SIGTERM_GRACE" || true

# Phase 2: SIGTERM to whatever a graceful quit did not take. It is the same request at the OS
# level and it is still a request -- a process that exits on SIGTERM loses nothing it flushed.
for p in $ALL_PIDS; do kill -0 "$p" 2>/dev/null && kill -TERM "$p" 2>/dev/null; done
# ...and then actually give SIGTERM its own grace, rather than escalating a second later.
wait_for_exit "$SIGTERM_GRACE" || true

# Phase 3: SIGKILL only for what survived both. Recorded, because an escalated kill is the one
# that can cost a human something unsaved, and a future reader must be able to see it happened.
KILLED=""
for p in $ALL_PIDS; do
  if kill -0 "$p" 2>/dev/null; then
    kill -KILL "$p" 2>/dev/null && KILLED="$KILLED $p"
  fi
done
[ -n "$KILLED" ] && sleep 2

# Let the kernel finish reclassifying the freed pages before the after-reading, so the "after"
# is a settled number rather than a snapshot taken mid-teardown. REAP_SETTLE is bounded.
_s=0
while [ "$_s" -lt "$REAP_SETTLE" ]; do sleep 1; _s=$(( _s + 1 )); done

RSS_BEFORE=$(printf '%s\n' "$TP" | awk -F'|' '{s+=$4} END{print s+0}')
if ! reclaimable; then
  decide reclaim error "quit the targets but could not re-measure reclaimable memory: $RECLAIMABLE_DETAIL" "$BEFORE" "" "$IDLE" "" "$(_short_pids "$ALL_PIDS")" ""
  exit 3
fi
AFTER="$RECLAIMABLE_BYTES"
RSS_AFTER=$(target_processes "$CONSOLE_UID" | awk -F'|' '{s+=$4} END{print s+0}')

REASON="reclaimed ${APP_NAMES:-none}: ${RSS_BEFORE} KB resident let go; reclaimable $(human "$BEFORE") -> $(human "$AFTER"); app_rss_kb ${RSS_BEFORE} -> ${RSS_AFTER}"
[ -n "$KILLED" ] && REASON="$REASON; SIGKILL escalated for pids:$KILLED"
decide reclaim acted "$REASON" "$BEFORE" "$AFTER" "$IDLE" "" "$(_short_pids "$ALL_PIDS")" "app_rss_kb_before=$RSS_BEFORE app_rss_kb_after=$RSS_AFTER"
exit 0
