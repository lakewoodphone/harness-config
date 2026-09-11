#!/usr/bin/env bash
# serve-phone.sh — publish this host's harness to the tailnet, so the owner's iPhone can talk to it.
#
# The Linux twin of scripts/serve-phone.ps1, with one difference that matters: this runs on the
# ALWAYS-ON host, which is the point. On a workstation the phone dies when the laptop sleeps, and the
# secretary bridge has to reach the company's database over the network — which is what PAIN P23 caught
# spawning processes on the company host every time a network blip killed the connection. Here the engine
# and the database are on the same box, so the bridge is a local child and there is no network hop.
#
# Why the engine cannot simply bind a LAN address: `dsh web` refuses `--host 0.0.0.0` on purpose ("it
# would expose remote code execution to the network"). The supported way in is a reverse proxy that
# preserves Host in front of loopback, plus `--trusted-host <that authority>`, which is what Tailscale
# Serve gives us: HTTPS, valid certificate, tailnet-only, no public exposure, no domain to buy.
#
# Verified by experiment (docs/dsh-mobile/00-RESEARCH.md §2): with --trusted-host, the one-time ?token=
# URL is accepted from that authority, the cookie is minted FOR that authority, and it is useless on any
# other. Untrusted Host without the flag → 403; no cookie → 401.
#
# usage: serve-phone.sh [--port N] [--status] [--stop] [--print-link]
set -uo pipefail

PORT="${PHONE_PORT:-3086}"
STATE="${PHONE_STATE:-$HOME/.dsh-phone}"
NODE="${PHONE_NODE:-/home/zabz/node/bin/node}"
BIN="${PHONE_BIN:-/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js}"
LOG="$STATE/engine-$PORT.log"
ERR="$STATE/engine-$PORT.err"

mkdir -p "$STATE" 2>/dev/null || exit 2

tailnet_name() {
  tailscale status --json 2>/dev/null | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
    print((d.get("Self") or {}).get("DNSName","").rstrip("."))
except Exception:
    print("")'
}

engine_pid() {
  pgrep -f "dsh/lib/bin.js web --port $PORT" 2>/dev/null | head -1
}

token() { grep -o 'token=[A-Za-z0-9_-]*' "$LOG" 2>/dev/null | head -1 | cut -d= -f2; }

case "${1:-}" in
  --status)
    DNS="$(tailnet_name)"
    PID="$(engine_pid)"
    echo "host      : $(hostname)  tailnet: ${DNS:-unknown}"
    echo "engine    : ${PID:-NOT running}  port $PORT"
    tailscale serve status 2>&1 | head -4
    if [ -n "$PID" ] && [ -n "$DNS" ]; then
      T="$(token)"
      echo ""
      echo "phone URL : https://$DNS/"
      [ -n "$T" ] && echo "one-time  : https://$DNS/?token=$T"
    fi
    exit 0
    ;;
  --print-link)
    DNS="$(tailnet_name)"; T="$(token)"
    [ -n "$DNS" ] && [ -n "$T" ] && echo "https://$DNS/?token=$T"
    exit 0
    ;;
  --stop)
    tailscale serve reset >/dev/null 2>&1 && echo "serve config cleared on this host"
    P="$(engine_pid)"; [ -n "$P" ] && kill "$P" 2>/dev/null && echo "stopped engine pid $P"
    exit 0
    ;;
esac

[ -x "$NODE" ] || { echo "node not found at $NODE (the harness needs Node >= 22)"; exit 2; }
[ -f "$BIN" ] || { echo "harness not found at $BIN"; exit 2; }

DNS="$(tailnet_name)"
[ -n "$DNS" ] || { echo "could not determine this node's tailnet name (is tailscale up?)"; exit 2; }

SERVE_OUT="$(tailscale serve --bg "$PORT" 2>&1)"
echo "$SERVE_OUT" | head -6
if echo "$SERVE_OUT" | grep -qi 'not enabled'; then
  echo ""
  echo "Serve is not enabled on this tailnet. Only the owner can enable it:"
  echo "  https://login.tailscale.com/f/serve"
  exit 3
fi

if [ -z "$(engine_pid)" ]; then
  echo "starting the engine on :$PORT (trusting $DNS)"
  rm -f "$LOG" "$ERR"
  # setsid + nohup so it survives this shell; the log carries the one-time token, so treat it as a secret.
  setsid nohup "$NODE" "$BIN" web --port "$PORT" --no-open --trusted-host "$DNS" >"$LOG" 2>>"$ERR" < /dev/null &
  for _ in $(seq 1 30); do sleep 3; grep -q 'token=' "$LOG" 2>/dev/null && break; done
else
  echo "engine already running: pid $(engine_pid)"
fi

T="$(token)"
echo ""
echo "published: https://$DNS/  ->  http://127.0.0.1:$PORT"
if [ -n "$T" ]; then
  echo ""
  echo "ON THE PHONE, open this once:"
  echo "  https://$DNS/?token=$T"
  echo "then https://$DNS/ is enough for 30 days. Add to Home Screen from Safari for the standalone app."
else
  echo "(no token yet — check $LOG, or re-run --status in a moment)"
fi
