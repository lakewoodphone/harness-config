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
nv=$( (command -v node >/dev/null 2>&1 && node -v) || echo absent )
dshp=$( command -v dsh >/dev/null 2>&1 && echo true || echo false )
eng=$( (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -c ':3099' )
cfg=$( [ -d "$HOME/code/harness-config" ] && echo true || echo false )
procs=$( (ps -e 2>/dev/null | wc -l) )
cat <<EOF
{"reachable":true,"host":"$host","os":"$os","cores":$cores,"memTotalMiB":$total,"memFreeMiB":"$free","commitLimitMiB":"$cl","commitFreeMiB":"$cf","cFreeGiB":"$cfree","nodeVersion":"$nv","dshOnPath":$dshp,"engineOn3099":$( [ "$eng" -gt 0 ] && echo true || echo false ),"harnessConfig":$cfg,"procTotal":$procs,"shell":"posix"}
EOF
