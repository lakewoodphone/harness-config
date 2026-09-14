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

PORT="${PHONE_PORT:-3086}"                 # the port Tailscale Serve publishes (the gate)
ENGINE_PORT="${PHONE_ENGINE_PORT:-3089}"   # the harness itself, behind the gate
STATE="${PHONE_STATE:-$HOME/.dsh-phone}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REDIRECT_PORT="${PHONE_REDIRECT_PORT:-3087}"
NODE="${PHONE_NODE:-/home/zabz/node/bin/node}"
BIN="${PHONE_BIN:-/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js}"
LOG="$STATE/engine-$ENGINE_PORT.log"
ERR="$STATE/engine-$ENGINE_PORT.err"

mkdir -p "$STATE" 2>/dev/null || exit 2

gate_pid() {
  # pidfile, for the same reason as the redirector below: never ask a process list a question about
  # yourself.
  local pidfile="$STATE/gate.pid"
  [ -f "$pidfile" ] || return 1
  local pid; pid="$(cat "$pidfile" 2>/dev/null)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && { echo "$pid"; return 0; }
  return 1
}

ensure_gate() {
  # Sits between Serve and the engine so that ANY URL which reaches this host signs the visitor in.
  # Without it, a first visit to the bare address returns the harness's plain-text "authentication
  # required" — which iOS offers to download as a document (measured 2026-09-11).
  local pid; pid="$(gate_pid)"
  if [ -n "$pid" ]; then echo "gate already running: pid $pid"; return 0; fi
  if [ ! -f "$REPO_DIR/scripts/phone-gate.py" ]; then echo "gate script missing"; return 1; fi
  setsid nohup python3 "$REPO_DIR/scripts/phone-gate.py" \
    --listen-port "$PORT" --engine-port "$ENGINE_PORT" >>"$STATE/gate.log" 2>&1 </dev/null &
  echo $! > "$STATE/gate.pid"
  sleep 1
  pid="$(gate_pid)"
  [ -n "$pid" ] && echo "gate started: pid $pid on 127.0.0.1:$PORT -> engine $ENGINE_PORT" \
    || echo "gate failed to start (see $STATE/gate.log)"
}

tailnet_name() {
  tailscale status --json 2>/dev/null | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
    print((d.get("Self") or {}).get("DNSName","").rstrip("."))
except Exception:
    print("")'
}

engine_pid() {
  pgrep -f "dsh/lib/bin.js web --port $ENGINE_PORT" 2>/dev/null | head -1
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

ensure_client_plugin() {
  # The phone's client layer lives in packages/*, and each package reaches the browser
  # through two things that are not in git and can vanish without a trace: a symlink in the
  # profile's node_modules and the package name in that profile's `dsh.profile.bundles`. An
  # npm command run inside the profile, or a rebuilt node_modules, silently takes the
  # behaviour away — and the phone is merely annoying again, which is the hardest kind of
  # regression to notice. So the same script that keeps the gate and the redirector alive
  # keeps these too: check each, and reinstall only when something is actually missing.
  #
  # BOTH packages, and that is the point of the loop: `plugin-mobile` has been kept alive
  # here since 2026-09-11 while `plugin-cost` — installed by hand on Windows only — was
  # absent from this host entirely, so the owner's phone had no cost pill and nothing said
  # so (measured 2026-09-14: the bundle list was [dsh-base, dsh-web-app, dsh-plugin-mobile]).
  # A keeper that watches one of two things is the trap; it must watch the list.
  local profile="${DSH_HOME:-$HOME/.dsh}/profiles/web"
  [ -d "$profile" ] || return 0
  local pkgdir name rc=0
  for pkgdir in "$REPO_DIR/packages/plugin-mobile" "$REPO_DIR/packages/plugin-cost"; do
    [ -d "$pkgdir" ] || continue
    name="$(basename "$pkgdir")"
    [ -e "$profile/node_modules/$name" ] && grep -q "\"$name\"" "$profile/package.json" 2>/dev/null && continue
    if bash "$REPO_DIR/scripts/install-client-plugin.sh" "$pkgdir" "$profile" >>"$STATE/plugin-install.log" 2>&1; then
      PLUGINS_CHANGED=1
      echo "client plugin (re)installed: $name -> $profile"
    else
      rc=1
      echo "client plugin install failed: $name (see $STATE/plugin-install.log)"
    fi
  done
  return $rc
}

port_open() {
  # Is something accepting on this loopback port? Used to tell "booting" apart from "dead".
  timeout 2 bash -c "exec 3<>/dev/tcp/127.0.0.1/$1" 2>/dev/null
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

# BEFORE the engine decision, so a plugin that had to be (re)installed is in the bundle list
# the engine reads at boot. Installing afterwards means it mounts only at some future,
# unrelated restart — which is how a keeper that runs every ten minutes can still leave a
# feature missing for days.
PLUGINS_CHANGED=""
ensure_client_plugin

if [ -z "$(engine_pid)" ]; then
  echo "starting the engine on :$ENGINE_PORT (trusting $DNS; the gate publishes :$PORT)"
  rm -f "$LOG" "$ERR"
  # setsid + nohup so it survives this shell; the log carries the one-time token, so treat it as a secret.
  setsid nohup "$NODE" "$BIN" web --port "$ENGINE_PORT" --no-open --trusted-host "$DNS" >"$LOG" 2>>"$ERR" < /dev/null &
  for _ in $(seq 1 30); do sleep 3; grep -q 'token=' "$LOG" 2>/dev/null && break; done
  # The token appears BEFORE the socket binds — measured 2026-09-14: token at ~18s, listening
  # later. This script used to return at the token, so it reported success during a boot, and
  # the five-minute probe then saw a closed port and wrote a phone outage that was really a
  # boot in progress. I diagnosed a plugin as the culprit on that reading. Wait for the socket.
  for _ in $(seq 1 60); do port_open "$ENGINE_PORT" && break; sleep 2; done
  if port_open "$ENGINE_PORT"; then
    echo "engine listening on :$ENGINE_PORT"
  else
    echo "engine did NOT bind :$ENGINE_PORT within 120s — see $ERR"
  fi
else
  echo "engine already running: pid $(engine_pid)"
  # A bundle list is read when the profile boots, so an install that happened while this
  # engine was up is NOT in the running process. Say so instead of letting the pill be
  # silently absent: this is the same class of claim as "config changed" without a restart.
  if [ -n "$PLUGINS_CHANGED" ]; then
    echo "NOTE: a client plugin was (re)installed while this engine was running."
    echo "      The engine mounts the bundle list at boot — restart it to pick the plugin up:"
    echo "      bash $0 --stop && bash $0"
  fi
fi

ensure_gate
ensure_redirector

# ...and the gate has to be accepting too, or "published" is a claim about Serve only.
for _ in $(seq 1 15); do port_open "$PORT" && break; sleep 1; done
if ! port_open "$PORT"; then
  echo "gate is not listening on 127.0.0.1:$PORT — the phone link cannot work; see $STATE/gate.log"
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
