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
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REDIRECT_PORT="${PHONE_REDIRECT_PORT:-3087}"
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

redirector_pid() {
  # A pidfile, not `pgrep -f`: the pattern matched the command line of whatever shell was running this
  # script, so a deploy whose command line mentioned the redirector's own filename concluded it was
  # already running and never started it. Matching a process list is self-matching by construction
  # (LESSONS L28/L32) — the fix is not a cleverer pattern, it is not asking the question that way.
  local pidfile="$STATE/redirector.pid"
  [ -f "$pidfile" ] || return 1
  local pid; pid="$(cat "$pidfile" 2>/dev/null)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && { echo "$pid"; return 0; }
  return 1
}

ensure_redirector() {
  # The owner's phone already has https://ai.abletelsolutions.com/phone on its home screen. The tunnel
  # routes that path here, and this 302s into the harness so his existing icon opens the new app.
  local pid; pid="$(redirector_pid)"
  if [ -n "$pid" ]; then echo "redirector already running: pid $pid"; return 0; fi
  if [ ! -f "$REPO_DIR/scripts/phone-redirector.py" ]; then echo "redirector script missing"; return 1; fi
  setsid nohup python3 "$REPO_DIR/scripts/phone-redirector.py" --port "$REDIRECT_PORT" \
    >>"$STATE/redirector.log" 2>&1 </dev/null &
  echo $! > "$STATE/redirector.pid"
  sleep 1
  pid="$(redirector_pid)"
  [ -n "$pid" ] && echo "redirector started: pid $pid on 127.0.0.1:$REDIRECT_PORT" || echo "redirector failed to start (see $STATE/redirector.log)"
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
if echo "$SERVE_OUT" | grep -qi 'denied'; then
  # On Linux the serve config belongs to root unless the tailnet node has an operator set. The first
  # version of this script printed the phone link regardless, which is a lie of exactly the kind this
  # fleet keeps paying for: a success message for an action that did not happen.
  if sudo -n true 2>/dev/null; then
    SERVE_OUT="$(sudo -n tailscale serve --bg "$PORT" 2>&1)"
  else
    echo "$SERVE_OUT"
    echo ""
    echo "Serve needs root on this host. Either run:  sudo tailscale set --operator=$USER   (once)"
    echo "or run this script with sudo. Refusing to print a link that does not work."
    exit 3
  fi
fi
if echo "$SERVE_OUT" | grep -qi 'not enabled'; then
  echo "$SERVE_OUT"
  echo ""
  echo "Serve is not enabled on this tailnet. Only the owner can enable it:"
  echo "  https://login.tailscale.com/f/serve"
  exit 3
fi

# Prove the proxy exists before claiming anything. `serve status` is the effect, not the intent.
if ! tailscale serve status 2>/dev/null | grep -q "$PORT"; then
  echo "$SERVE_OUT"
  echo ""
  echo "serve did not take effect for port $PORT — refusing to print a phone link. Current status:"
  tailscale serve status 2>&1 | head -5
  exit 1
fi
echo "serve active: https://$DNS/ -> 127.0.0.1:$PORT"

if [ -z "$(engine_pid)" ]; then
  echo "starting the engine on :$PORT (trusting $DNS)"
  rm -f "$LOG" "$ERR"
  # setsid + nohup so it survives this shell; the log carries the one-time token, so treat it as a secret.
  setsid nohup "$NODE" "$BIN" web --port "$PORT" --no-open --trusted-host "$DNS" >"$LOG" 2>>"$ERR" < /dev/null &
  for _ in $(seq 1 30); do sleep 3; grep -q 'token=' "$LOG" 2>/dev/null && break; done
else
  echo "engine already running: pid $(engine_pid)"
fi

ensure_redirector

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
