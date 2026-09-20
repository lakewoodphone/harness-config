#!/bin/sh
# O2 / transport-v2 reconnaissance on a POSIX node (macOS or Linux), piped to it over ssh stdin.
#
# READ-ONLY: it reads process tables, ports and timestamps and writes nothing but its own stdout.
# Deliberately POSIX sh and not bash, because the Mac Mini runs zsh and Apple ships Python 3.9
# without the modules a richer probe would want.
echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "HOST=$(hostname)"
echo "UNAME=$(uname -sr)"
echo
echo "== node / engine processes =="
ps -Ao pid,ppid,etime,comm,args 2>/dev/null | grep -E '[n]ode|[d]sh' | head -20
echo
echo "== the engine, the gate and their listeners =="
for port in 3086 3089 3099; do
    line=$(netstat -an 2>/dev/null | grep -E "[.:]$port .*LISTEN" | head -2)
    if [ -n "$line" ]; then echo "port $port: $line"; else echo "port $port: no LISTEN"; fi
done
echo
echo "== does the node answer its own gate? =="
curl -s -m 6 --noproxy '*' -o /tmp/o2-cap.$$ -w 'capacity http=%{http_code} bytes=%{size_download}\n' http://127.0.0.1:3086/mesh/capacity
head -c 400 /tmp/o2-cap.$$ 2>/dev/null; echo; rm -f /tmp/o2-cap.$$
echo
echo "== tailscale =="
# Not on PATH for a non-login shell on the Mac; the daemon lives under /opt/homebrew there.
(tailscale serve status 2>/dev/null || /opt/homebrew/opt/tailscale/bin/tailscale serve status 2>/dev/null || echo "tailscale not found on PATH or in /opt/homebrew/opt/tailscale/bin") | head -6
echo
echo "== node and dsh =="
# A non-login shell does not get the user's PATH, and on the Mac Mini the runtime this fleet uses
# lives under ~/.local — so `command -v node` is absent while the ENGINE runs that very binary.
# Both are reported, because "no node in PATH" and "no node on the machine" are different facts.
command -v node >/dev/null 2>&1 && echo "node in PATH: $(node --version)" || echo "node: not in this shell's PATH"
for exe in "$HOME/.local/node-v24.12.0-darwin-arm64/bin/node" "$HOME/.local/node-v24.12.0-linux-x64/bin/node" /usr/local/bin/node; do
    [ -x "$exe" ] && echo "node binary present: $exe ($("$exe" --version 2>/dev/null))"
done
for dsh in /Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js "$HOME/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js" /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js; do
    [ -f "$dsh" ] && echo "dsh bin present: $dsh"
done
echo "the engine that is running, with its own interpreter:"
ps -Ao pid,args 2>/dev/null | grep -E '[b]in\.js web' | head -3
echo
echo "== dsh sessions touched in the last 30 minutes (is anyone working here?) =="
find "$HOME/.dsh/sessions" -type f -newermt '30 minutes ago' 2>/dev/null | head -8
echo "count=$(find "$HOME/.dsh/sessions" -type f -newermt '30 minutes ago' 2>/dev/null | wc -l | tr -d ' ')"
echo
echo "== the busiest processes right now (top 6 by CPU) =="
ps -Ao pcpu,pmem,pid,comm -r 2>/dev/null | head -7 || ps aux 2>/dev/null | head -7
echo
echo "== memory pressure =="
memory_pressure 2>/dev/null | tail -3 || free -m 2>/dev/null | head -3
