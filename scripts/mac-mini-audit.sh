#!/usr/bin/env bash
# mac-mini-audit.sh — read-only audit of what actually consumes `LakewooechsMini` (mac-mini-ts).
#
# WHAT THIS IS
#   Every number printed here is read from the live machine at the moment printed, with its
#   source named in the section header. It is RE-RUNNABLE: run it again after any change and
#   compare the same section, over the same window, from the same counter.
#
# WHAT THIS DOES NOT DO — and this is deliberate
#   It starts nothing, stops nothing, quits nothing and changes no setting. It never calls a GUI.
#   The only things it writes on the target are short-lived scratch files under /tmp that it
#   removes on the way out. No sudo is required (sudo is used only for read-only diagnostics
#   when a passwordless sudo happens to exist).
#
# USAGE
#   On the Mac:        bash mac-mini-audit.sh [window_seconds] [step_seconds]     # 120 20 default
#   From a Windows box (no remote write, script arrives on stdin):
#       cmd /c "ssh mac-mini-ts bash -s < C:\Users\ezabz\code\harness-config\scripts\mac-mini-audit.sh"
#   From Linux/macOS:
#       ssh mac-mini-ts 'bash -s' < scripts/mac-mini-audit.sh
#
# TRAP THIS SCRIPT EXISTS TO AVOID (measured 2026-09-16, see docs/mesh/74-mac-mini.md)
#   `/Applications/Tailscale.app/Contents/MacOS/Tailscale <subcommand>` and
#   `/usr/local/bin/tailscale ...` HANG FOREVER when invoked over a non-interactive ssh
#   session on this host. A hung invocation leaves an orphan that spins at ~1 % CPU for as
#   long as the machine is up, and ten of them were measured squatting 6.8 % CPU plus
#   ~150 MB. So: EVERY tailnet CLI call below is wrapped in with_timeout(), and the wrapper
#   is part of the audit's own contract. Do not add an unbounded tailscale call to this file.
#
# Set MAC_AUDIT_NO_TAILSCALE=1 to skip even the guarded tailnet probe.

set -u

WINDOW="${1:-${MAC_AUDIT_WINDOW:-120}}"
STEP="${2:-${MAC_AUDIT_STEP:-20}}"
SAMPLES=$(( WINDOW / STEP ))
[ "$SAMPLES" -lt 3 ] && SAMPLES=3
PAGESIZE=$(sysctl -n hw.pagesize 2>/dev/null || echo 16384)

now()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
sec()  { printf '\n=== %s ===\n[at %s]\n' "$1" "$(now)"; }
have() { command -v "$1" >/dev/null 2>&1; }

# MEASUREMENT TRAP #2, measured 2026-09-16 on this host: `top -pid` accepts exactly ONE integer
# and REJECTS a comma-separated list with "invalid -pid argument (not an integer)", exiting without
# sampling — and if its stderr is redirected, the result is an empty table that looks like "no
# processes found" rather than a failure. So per-process windows are taken with `ps` in a loop.
ps_window() { # ps_window SAMPLES STEP  -> "<sample> <pid> <%cpu> <rss> <time> <name...>" lines
  local i=0 n="$1" step="$2"
  while [ "$i" -lt "$n" ]; do
    ps -axo pid,%cpu,rss,time,comm 2>/dev/null | awk -v s="$i" 'NR>1{print s, $0}'
    i=$((i + 1))
    [ "$i" -lt "$n" ] && sleep "$step"
  done
}
# Aggregate a ps_window stream: per-pid mean %CPU, group totals, machine-wide busy cores.
ps_aggregate() { # ps_aggregate LABFILE  (reads the window on stdin)
  local lab="$1" tmp="/tmp/.mac-audit-win.$$"
  cat > "$tmp"
  awk -v LAB="$lab" '
    BEGIN{ while ((getline l < LAB) > 0) { split(l, f, "\t"); lab[f[1]] = f[2] } }
    {
      s = $1; p = $2; cpu = $3 + 0; rss = $4 + 0
      name = $0; sub(/^[ \t]*[0-9]+[ \t]+[0-9.]+[ \t]+[0-9]+[ \t]+[0-9:.]+[ \t]+[0-9:-]+[ \t]+/, "", name)
      nm[p] = name; ns[p]++; c[p] += cpu; if (rss > mx[p]) mx[p] = rss
      if (!(s in seen)) { seen[s] = 1; nsamp++ }
      samp[s] += cpu; allcpu += cpu
      g = lab[p]; if (g != "") { gc[g] += cpu; if (rss > gmx[g]) gmx[g] = rss }
    }
    END{
      printf "  samples=%d   machine-wide busy cores (mean of sum%%CPU/100) = %.2f\n", nsamp, (nsamp > 0 ? (allcpu/nsamp)/100 : 0)
      print  "  --- peak machine-wide %%CPU in one sample (all processes) ---"
      for (s in samp) if (samp[s] > best) best = samp[s]
      printf "    %.1f %%CPU total in the busiest sample = %.2f of 10 cores\n", best, best/100
      print  "  --- named groups: mean %CPU summed over the group ---"
      for (g in gc) printf "    %-20s %7.2f %%CPU   peak RSS %6.0f MB\n", g, gc[g]/nsamp, gmx[g]/1024
      print  "  --- each tracked process ---"
      for (p in c) if (lab[p] != "") printf "    pid %-7s %-18s mean %6.2f %%CPU   peak RSS %6.0f MB   %s\n", p, lab[p], c[p]/ns[p], mx[p]/1024, nm[p]
    }' "$tmp"
  echo "  --- top 12 processes by mean %CPU (all processes) ---"
  awk '
    { s=$1; p=$2; cpu=$3+0; rss=$4+0
      name=$0; sub(/^[ \t]*[0-9]+[ \t]+[0-9.]+[ \t]+[0-9]+[ \t]+[0-9:.]+[ \t]+[0-9:-]+[ \t]+/, "", name)
      nm[p]=name; ns[p]++; c[p]+=cpu; if (rss>mx[p]) mx[p]=rss }
    END{ for (p in c) printf "    %8.2f  %8.0f MB  pid %-7s %s\n", c[p]/ns[p], mx[p]/1024, p, nm[p] }' "$tmp" \
    | sort -k1 -rn | head -12
  rm -f "$tmp"
}

# Portable timeout: macOS ships no `timeout(1)`. It runs the command in its OWN PROCESS GROUP
# (perl setpgrp — macOS has no setsid(1)) and kills the whole group, because killing only the
# direct child is exactly how the tailscale hang leaks: /usr/local/bin/tailscale is a `#!/bin/sh`
# shim that FORKS the app binary, so `kill $pid` kills the shim and leaves the real process
# spinning forever. Measured 2026-09-16: a naive bounded probe of that shim created a fresh
# ~1.4 %-CPU orphan (pid 3760, born 23:16:27Z). This wrapper cannot do that.
with_timeout() { # with_timeout SECONDS cmd [args...]
  local t="$1"; shift
  local out="/tmp/.mac-audit-to.$$"
  perl -e 'setpgrp(0,0); exec @ARGV or exit 127' "$@" > "$out" 2>&1 &
  local pid=$!
  ( sleep "$t"; kill -9 -"$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null ) &
  local watcher=$!
  wait "$pid" 2>/dev/null; local rc=$?
  kill "$watcher" 2>/dev/null
  if [ "$rc" -eq 137 ] || [ "$rc" -eq 143 ]; then
    echo "TIMEOUT: killed after ${t}s (whole process group) — this command is the known hang"
  else
    cat "$out"
  fi
  rm -f "$out"
}

echo "############################################################"
echo "# mac-mini-audit.sh — READ-ONLY consumption audit"
echo "# window=${WINDOW}s  step=${STEP}s  samples=${SAMPLES}  page=${PAGESIZE}B"
echo "# ran at $(now)   host=$(hostname)   user=$(id -un)"
echo "# source of every number: this machine, this moment, unless said otherwise"
echo "############################################################"

sec "0. IDENTITY / UPTIME / LOAD  (source: sw_vers, sysctl, uptime)"
sw_vers 2>/dev/null
echo "model=$(sysctl -n hw.model 2>/dev/null)  ncpu=$(sysctl -n hw.ncpu 2>/dev/null)  physical=$(sysctl -n hw.physicalcpu 2>/dev/null)"
echo "memsize=$(sysctl -n hw.memsize 2>/dev/null) B"
uptime
echo "console_owner=$(stat -f %Su /dev/console 2>/dev/null)   (the GUI session on the display)"
echo "--- who ---"; who
echo "--- disk (source: df -h) ---"; df -h /

# ---------------------------------------------------------------------------
# FOCUS MODE — `MAC_AUDIT_FOCUS=1` runs only this block and exits.
# It exists so a BEFORE and an AFTER can be taken from the SAME counter over the SAME window
# in ~90 s instead of ~6 min, which is what makes a before/after claim honest: same counter,
# same window, same conditions. It measures the specific processes named below and nothing else.
# ---------------------------------------------------------------------------
if [ "${MAC_AUDIT_FOCUS:-0}" = "1" ]; then
  sec "F. FOCUS MEASUREMENT — window ${WINDOW}s, step ${STEP}s, $SAMPLES samples"
  echo "condition: load=$(uptime | sed 's/.*load averages*: //')   console=$(stat -f %Su /dev/console 2>/dev/null)"
  HIDNS=$(ioreg -c IOHIDSystem 2>/dev/null | grep -m1 -o 'HIDIdleTime" = [0-9]*' | grep -o '[0-9]*$')
  echo "condition: HID idle = $(( ${HIDNS:-0} / 1000000000 / 60 )) minutes  (when a human last touched the keyboard/mouse)"
  echo "condition: display assertion: $(pmset -g assertions 2>/dev/null | grep -m1 -E 'UserIsActive[[:space:]]+[0-9]')  |  $(pmset -g assertions 2>/dev/null | grep -m1 'PreventUserIdleSystemSleep')"
  echo "condition: $(top -l 1 2>/dev/null | grep -E '^(CPU usage|PhysMem)')"
  echo "condition: $(sysctl vm.swapusage)"

  LABF=/tmp/.mac-audit-labels.$$
  : > "$LABF"
  add_group() { # add_group "label" "pids,comma,sep"
    local label="$1" list="$2" p
    for p in $(echo "$list" | tr ',' ' '); do [ -n "$p" ] && printf '%s\t%s\n' "$p" "$label" >> "$LABF"; done
  }
  add_group "nesessionmanager"    "$(pgrep -x nesessionmanager 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  add_group "WallpaperAerialsExt" "$(pgrep -f WallpaperAerialsExtension 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  add_group "VTDecoderXPC"        "$(pgrep -f VTDecoderXPCService 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  add_group "WallpaperAgent"      "$(pgrep -f WallpaperAgent.app 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  add_group "WindowServer"        "$(pgrep -f 'SkyLight.framework/Resources/WindowServer' 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  add_group "tailscaled-brew"     "$(pgrep -f 'opt/tailscale/bin/tailscaled' 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  add_group "neagent"             "$(pgrep -x neagent 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  add_group "DSH-engine"          "$(pgrep -f 'dsh/lib/bin.js' 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  add_group "hung-tailscale-cli"  "$(ps -axo pid,args 2>/dev/null | grep -E '(Tailscale|tailscale)[^ ]* +(ip|status|version|serve|funnel|debug|netcheck|ping|whois)' | grep -v grep | awk '{print $1}' | tr '\n' ',' | sed 's/,$//')"
  add_group "Chrome"              "$(pgrep -f 'Google Chrome' 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  add_group "Spotify"             "$(pgrep -f Spotify 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  echo "  window taken with: ps -axo pid,%cpu,rss,time,comm  x$SAMPLES every ${STEP}s"
  echo "  targets: $(cut -f1 "$LABF" | sort -u | wc -l | tr -d ' ') pids, in $(cut -f2 "$LABF" | sort -u | wc -l | tr -d ' ') named groups"
  ps_window "$SAMPLES" "$STEP" | ps_aggregate "$LABF"
  rm -f "$LABF"
  echo "  --- Chrome (source: ps -axo %cpu,rss,comm — one instant) ---"
  ps -axo %cpu,rss,comm 2>/dev/null | awk '/Google Chrome/{n++; c+=$1; s+=$2} END{printf "  chrome processes %d  summed%%CPU %.1f  resident %.0f MB\n", n, c, s/1024}'
  echo "  --- hung-client census (same shape as section 7) ---"
  ps -axo pid,time,args 2>/dev/null \
    | grep -E '(Tailscale|tailscale)[^ ]* +(ip|status|version|serve|funnel|debug|netcheck|ping|whois)' | grep -v grep \
    | awk '{t=$2; split(t,a,":"); if(length(a)==3) s=a[1]*3600+a[2]*60+a[3]; else if(length(a)==2) s=a[1]*60+a[2]; else s=a[1];
             n++; tot+=s} END{printf "  %d hung clients, %.1f CPU-minutes burned\n", n, tot/60}'
  printf '\n=== END OF FOCUS — %s ===\n' "$(now)"
  exit 0
fi

sec "1. CPU OVER A ${WINDOW}s WINDOW — GLOBAL  (source: top -l $((SAMPLES+1)) -s ${STEP})"top -l $((SAMPLES + 1)) -s "$STEP" 2>/dev/null \
  | grep -E '^(Processes:|Load Avg:|CPU usage:|PhysMem:|VM:|Networks:|Disks:)' \
  | sed 's/^/  /'

sec "2. CPU OVER THE SAME WINDOW — PER PROCESS, MEAN ACROSS SAMPLES  (source: top -l $SAMPLES -s $STEP -o cpu -n 15 -stats pid,cpu,mem,purg,cmprs)"
# MEAN %CPU PER PID over the whole window, not a single instant: each sample contributes the
# process's own instantaneous %CPU; the mean is what "what is burning the CPU" means.
# A single instant is what made an earlier version of this section sample only short-lived XPC
# processes that had already exited by the next sample. The mean over samples cannot do that.
: > /tmp/.mac-audit-empty-labels.$$
ps_window "$SAMPLES" "$STEP" | ps_aggregate /tmp/.mac-audit-empty-labels.$$
rm -f /tmp/.mac-audit-empty-labels.$$

sec "3. WHAT IS RUNNING WITH A CPU HISTORY — ps snapshot  (source: ps -axo ... -r)"
ps -axo pid,ppid,%cpu,time,etime,rss,vsz,user,comm -r 2>/dev/null | head -25

sec "4. MEMORY — THE OS'S OWN ACCOUNTING  (source: vm_stat, sysctl vm.swapusage, memory_pressure)"
echo "--- vm_stat (start) ---"
vm_stat
echo "--- swapfile backing store (source: ls -la /private/var/vm) ---"
ls -la /private/var/vm/ 2>/dev/null
echo "--- sysctl vm.swapusage ---"
sysctl vm.swapusage
echo "--- memory_pressure (free percentage is the one-line verdict) ---"
if sudo -n true 2>/dev/null; then sudo -n memory_pressure 2>&1 | tail -12; else memory_pressure 2>&1 | tail -12; fi
echo "--- vm_stat deltas over ${WINDOW}s: is it swapping NOW, or was it? ---"
VM_A=$(vm_stat 2>/dev/null)
sleep "$WINDOW"
VM_B=$(vm_stat 2>/dev/null)
echo "metric                     | start   | end     | delta   | per-second"
for k in "Pageins" "Pageouts" "Swapins" "Swapouts" "Compressions" "Decompressions" \
         "Pages free" "Pages wired down" "Pages occupied by compressor" "Pages stored in compressor" \
         "Pages active" "Pages inactive" "Pages purgeable" "Anonymous pages" "File-backed pages"; do
  a=$(echo "$VM_A" | awk -v k="$k" 'index($0,k":")==1{gsub(/[^0-9]/,"",$0); print $0+0}')
  b=$(echo "$VM_B" | awk -v k="$k" 'index($0,k":")==1{gsub(/[^0-9]/,"",$0); print $0+0}')
  [ -z "$a" ] && continue
  printf "  %-26s | %-9s | %-9s | %-9s | %s\n" "$k" "$a" "$b" "$((b - a))" \
    "$(awk -v d="$((b-a))" -v w="$WINDOW" -v ps="$PAGESIZE" 'BEGIN{printf "%.3f pages/s = %.3f MB/s", d/w, d*ps/1048576/w}')"
done
echo "  (interpretation: Swapins/Swapouts delta 0 over the window means the 6 GB of swap in use is"
echo "   HISTORICAL, not active thrashing. 'Pages occupied by compressor' is real RAM held by compressed pages.)"

sec "5. MEMORY — BY PROCESS  (source: top -l 1 -o mem -stats pid,cpu,mem,purg,cmprs)"
echo "MEM = footprint, CMPRS = this process's compressed bytes (real RAM it costs)"
top -l 1 -o mem -n 18 -stats pid,cpu,mem,purg,cmprs 2>/dev/null | tail -20
echo "--- same, with names (source: ps) ---"
for p in $(top -l 1 -o mem -n 18 2>/dev/null | awk '/^PID/{h=1;next} h && /^[0-9]/{print $1}'); do
  ps -p "$p" -o pid=,user=,comm= 2>/dev/null | sed 's/^/  /'
done
echo "--- per-user resident total (source: ps -axo user,rss -r) ---"
ps -axo user,rss 2>/dev/null | awk 'NR>1{s[$1]+=$2} END{for(u in s) printf "  %-16s %7.0f MB\n", u, s[u]/1024}' | sort -k2 -rn
echo "--- Google Chrome aggregate (source: ps -axo pid,rss,comm) ---"
ps -axo pid,rss,comm 2>/dev/null | awk '/Google Chrome/{n++; s+=$2; if($2>mx) mx=$2} END{printf "  chrome processes: %d   resident sum: %.0f MB   largest single: %.0f MB\n", n, s/1024, mx/1024}'
echo "--- Chrome CPU share (source: ps -axo %cpu — a decayed average, same counter before and after) ---"
ps -axo %cpu,rss,comm 2>/dev/null | awk '/Google Chrome/{n++; c+=$1; s+=$2} END{printf "  chrome processes: %d   summed %%CPU: %.1f   resident sum: %.0f MB\n", n, c, s/1024}'

sec "6. THE DSH ENGINE'S OWN FOOTPRINT  (source: pgrep -f 'dsh/lib/bin.js' + a ps window)"
ENGPIDS=$(pgrep -f 'dsh/lib/bin.js' 2>/dev/null | tr '\n' ',' | sed 's/,$//')
echo "engine pids: ${ENGPIDS:-NONE}"
if [ -n "$ENGPIDS" ]; then
  ps -p "$ENGPIDS" -o pid=,ppid=,etime=,time=,%cpu=,rss=,vsz=,args= 2>/dev/null | sed 's/^/  /'
  printf '%s\n' "$(echo "$ENGPIDS" | tr ',' '\n' | awk '{printf "%s\tdsh-engine\n", $1}')" > /tmp/.mac-audit-eng.$$
  echo "--- engine over the same window (ps window; MEM/CMPRS columns come from section 5) ---"
  ps_window "$SAMPLES" "$STEP" | ps_aggregate /tmp/.mac-audit-eng.$$ | sed -n '1,3p;/dsh-engine/p'
  rm -f /tmp/.mac-audit-eng.$$
  echo "--- live sessions on this DSH_HOME (source: ls ~/.dsh/sessions) ---"
  ls -1 "$HOME/.dsh/sessions" 2>/dev/null | sed 's/^/  /'
fi

sec "7. STALE / HUNG TAILNET CLI PROBES  (source: ps -axo args — this is the section that changes)"
echo "A GUI session is NOT required for the tailnet; the tunnel is served by a daemon. These rows are"
echo "CLIENTS. If the parent is 1 (reparented to launchd) nobody owns them any more."
ps -axo pid,ppid,state,etime,time,%cpu,rss,args 2>/dev/null \
  | grep -E '(Tailscale|tailscale)[^ ]* +(ip|status|version|serve|funnel|debug|netcheck|ping|whois)' \
  | grep -v 'grep -E' | sed 's/^/  /'
echo "--- the daemons that DO serve the tailnet (never touch these) ---"
ps -axo pid,ppid,etime,time,%cpu,rss,args 2>/dev/null | grep -E '(tailscaled|nesessionmanager|neagent)' | grep -v grep | sed 's/^/  /'
echo "--- count and total CPU time burned by the hung clients ---"
ps -axo pid,time,args 2>/dev/null \
  | grep -E '(Tailscale|tailscale)[^ ]* +(ip|status|version|serve|funnel|debug|netcheck|ping|whois)' \
  | grep -v grep \
  | awk '{t=$2; split(t,a,":"); if(length(a)==3) s=a[1]*3600+a[2]*60+a[3]; else if(length(a)==2) s=a[1]*60+a[2]; else s=a[1];
           n++; tot+=s; printf "  pid %-8s cpu %-12s %s\n", $1, t, substr($0, index($0,$3))} END{printf "  --> %d hung clients, %.1f CPU-minutes burned since they started\n", n, tot/60}'
if [ "${MAC_AUDIT_NO_TAILSCALE:-0}" != "1" ]; then
  TS="${MAC_AUDIT_TAILSCALE_CLI:-/opt/homebrew/bin/tailscale}"
  echo "--- bounded tailnet CLI probe: the WORKING path, 8s, own process group ---"
  echo "    THE TRAP: /usr/local/bin/tailscale is a 3-line shim to the GUI app binary, and the app"
  echo "    binary used as a CLI HANGS FOREVER over a non-interactive ssh session — and a naive"
  echo "    timeout leaves the real process behind as a ~1.4 %-CPU orphan. $TS talks to the"
  echo "    running tailscaled and answers. Every probe here uses that path."
  printf '  %-52s ip -4        -> ' "$TS"; with_timeout 8 "$TS" ip -4 2>&1 | tr '\n' ' '; echo
  printf '  %-52s status --json -> ' "$TS"; with_timeout 8 "$TS" status --json 2>&1 | head -c 220 | tr '\n' ' '; echo
  printf '  %-52s serve status  -> ' "$TS"; with_timeout 8 "$TS" serve status 2>&1 | head -c 220 | tr '\n' ' '; echo
  if [ "${MAC_AUDIT_REPRO_HANG:-0}" = "1" ]; then
    echo "  (opt-in reproduction of the hang, MAC_AUDIT_REPRO_HANG=1)"
    printf '  %-52s -> ' "/usr/local/bin/tailscale"; with_timeout 8 /usr/local/bin/tailscale ip -4 2>&1 | tr '\n' ' '; echo
  fi
fi

sec "8. WHAT THE WALLPAPER IS, AND WHETHER A HUMAN CHOSE IT  (source: ps, plutil, stat, pmset)"
echo "--- wallpaper processes ---"
ps -axo pid,user,etime,%cpu,time,rss,comm 2>/dev/null | grep -iE 'wallpaper|aerial|VTDecoder' | grep -v grep | sed 's/^/  /'
echo "--- the configured desktop picture (plutil -p of the store; Provider 'default' = never chosen by a human) ---"
plutil -p "$HOME/Library/Application Support/com.apple.wallpaper/Store/Index.plist" 2>&1 | sed 's/^/  /'
echo "--- when was that store last written (mtime) vs when the account was created (who) ---"
stat -f "  %Sm  %N" "$HOME/Library/Application Support/com.apple.wallpaper/Store/Index.plist" 2>&1
stat -f "  %SB  (birth)  %N" "$HOME/Library/Application Support/com.apple.wallpaper/Store/Index.plist" 2>&1
echo "--- is the display awake? (source: pmset -g log — the wallpaper only decodes while it is) ---"
if sudo -n true 2>/dev/null; then
  sudo -n pmset -g log 2>/dev/null | grep -E 'Display is turned|Entering Sleep|Wake from|DarkWake' | tail -14 | sed 's/^/  /'
fi
echo "--- pmset -g ---"; pmset -g 2>/dev/null | sed 's/^/  /'
echo "--- sleep/display assertions (source: pmset -g assertions) ---"
pmset -g assertions 2>&1 | head -18 | sed 's/^/  /'

sec "9. ANYTHING ELSE ODD — listening ports, mds, network extensions  (source: lsof, ps)"
lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | head -12 | sed 's/^/  /'
echo "--- spotlight indexing (source: mdutil) ---"
mdutil -s / 2>&1 | sed 's/^/  /'
echo "--- load contributors by process count ---"
ps -axo comm 2>/dev/null | sort | uniq -c | sort -rn | head -12 | sed 's/^/  /'

printf '\n=== END OF AUDIT — %s — window %ss ===\n' "$(now)" "$WINDOW"
