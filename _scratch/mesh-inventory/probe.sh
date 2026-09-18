host=$(hostname 2>/dev/null)
os=$( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || sw_vers -productVersion 2>/dev/null || echo unknown )
cores=$( (nproc 2>/dev/null) || (sysctl -n hw.ncpu 2>/dev/null) || echo 0 )
if [ -r /proc/meminfo ]; then
  total=$(awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo)
  free=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
  cl=$(awk '/^CommitLimit:/{print int($2/1024)}' /proc/meminfo)
  cf=$(awk '/^Committed_AS:/{print int($2/1024)}' /proc/meminfo)
  if [ -n "$cl" ] && [ "$cl" != "0" ]; then cf=$((cl - cf)); else cf=""; fi
else
  total=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1048576 ))
  free=""
  cl=""
  cf=""
fi
cfree=$(df -Pk / 2>/dev/null | awk 'NR==2{printf "%.1f", $4/1048576}')
# `command -v node` ALONE PRODUCED A FALSE NEGATIVE, and that is why this loop exists.
# On mac-mini-ts (2026-09-18) sshd hands a non-interactive session the PATH
# `/usr/bin:/bin:/usr/sbin:/sbin`; node lives in `/usr/local/bin` and in a versioned directory that
# only `.zshrc` adds, so `node -v` printed nothing. The machine has TWO working runtimes. A probe
# that reports "no runtime" for a machine that has two is worse than no probe -- the same failure
# class as a health check that can report green for something absent. So: try PATH, then the
# absolute places, and report WHICH path answered, so a reader can tell "there is no runtime" from
# "there is no runtime on THIS PATH".
nv="absent"
npath=""
for cand in "$(command -v node 2>/dev/null)" /usr/local/bin/node /opt/homebrew/bin/node "$HOME"/.local/node-*/bin/node; do
  [ -n "$cand" ] && [ -x "$cand" ] || continue
  v=$("$cand" -v 2>/dev/null)
  if [ -n "$v" ]; then nv="$v"; npath="$cand"; break; fi
done
dshp=$( command -v dsh >/dev/null 2>&1 && echo true || echo false )
# THE SECOND macOS FALSE NEGATIVE, same cause, found the same way. `ss -ltn || netstat -ltn` is a
# Linux-shaped question: macOS has no `ss`, and BSD netstat does not accept `-ltn`, so the count came
# back 0 BY ERROR and the probe reported "no engine on 3099" for a machine that had one
# (`lsof -nP -iTCP:3099 -sTCP:LISTEN` -> pid 12458 LISTEN). Try the tools in order of precision and
# never let a tool's ABSENCE read as a negative answer.
if command -v ss >/dev/null 2>&1; then
  eng=$(ss -ltn 2>/dev/null | grep -c ':3099')
elif command -v lsof >/dev/null 2>&1; then
  eng=$(lsof -nP -iTCP:3099 -sTCP:LISTEN 2>/dev/null | grep -c 'LISTEN')
else
  eng=$(netstat -an -p tcp 2>/dev/null | grep -c '[.:]3099 .*LISTEN')
fi
cfg=$( [ -d "$HOME/code/harness-config" ] && echo true || echo false )
procs=$( (ps -e 2>/dev/null | wc -l) )
cat <<EOF
{"reachable":true,"host":"$host","os":"$os","cores":$cores,"memTotalMiB":$total,"memFreeMiB":"$free","commitLimitMiB":"$cl","commitFreeMiB":"$cf","cFreeGiB":"$cfree","nodeVersion":"$nv","nodePath":"$npath","dshOnPath":$dshp,"engineOn3099":$( [ "$eng" -gt 0 ] && echo true || echo false ),"harnessConfig":$cfg,"procTotal":$procs,"shell":"posix"}
EOF
