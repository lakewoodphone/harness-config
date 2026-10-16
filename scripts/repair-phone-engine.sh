#!/bin/bash
# repair-phone-engine.sh — re-assert the two things a package install silently breaks.
#
# WHY THIS EXISTS
# On 2026-10-12, the morning after the company moved from the office box to
# `secratary-cloud`, the owner's phone could not send a single message. Two
# independent defects, both from an install layout rather than from any code:
#
# 1. TWO COPIES OF @deepseek-ai/dsh-scope WERE LOADED IN ONE ENGINE.
#    The engine binary runs from the flat npm tree at /opt/dsh-phone, so the agent
#    loop is loaded from there and stamps the agent's context with the
#    `Symbol("dsh.scope")` of *that* copy. The profile at
#    ~/.dsh/profiles/web has its own pnpm tree, so `dsh-client-file-upload` was
#    loaded from there and read a *different* symbol. `scopeOf(agent.ctx)` came
#    back undefined, `assertAgentScope` threw
#    "file-upload: operation requires the Agent's own scope", and
#    `dsh-api-session-controller` relayed it to the phone as
#
#        prompt rejected (session/agent-busy)
#
#    — which is the "agent busy" the owner saw on every send, on every device.
#    The fix is one symlink, so that both trees resolve the module to ONE file
#    and therefore to ONE symbol. Proven by measurement, not by reasoning:
#    the constructor log named /opt/dsh-phone/.../dsh-agent-loop as the copy that
#    stamped, and the SCOPE5 log named ~/.dsh/profiles/web as the copy that
#    could not read it; with the symlink in place the same prompt returned "pong".
#
# 2. THE PHONE LAYER WAS NOT DEPLOYED, SO IT WAS SERVED AS 0 BYTES.
#    phone-gate.py resolves `assets/mobile.css` and `assets/question-card.css`
#    relative to itself. Run from a checkout that is <repo>/scripts/phone-gate.py;
#    deployed it is /usr/local/bin/phone-gate.py, so the path becomes
#    /usr/local/assets/ — a directory the install step has to create. It did not
#    exist on the cloud box, so `/dsh-phone-mobile.css` returned 404 and every
#    document went out with no layer at all: no drawer, no 44px controls, no
#    safe-area insets. The owner's words: "the interface is not optimized".
#    `resolve_asset()` in phone-gate.py now searches for the files, and this
#    script keeps a copy where it looks.
#
# WHEN TO RUN IT
#   * before the phone engine starts (systemd ExecStartPre on phone-engine.service)
#   * after any `npm install` / `pnpm install` in the engine or profile trees,
#     because an install re-creates the flat copy of dsh-scope and breaks (1)
#     again — silently, and only on the phone
#   * by hand, any time the phone is reported broken
#
# It is idempotent, writes nothing but a one-line summary, and never removes data:
# the disowned copy is moved aside with a timestamp, not deleted.
#
# Usage: repair-phone-engine.sh [--check] [--quiet]
#   --check  report what is wrong and exit non-zero; change nothing
# Exit: 0 healthy / repaired, 1 something could not be repaired, 2 wrong (--check)

set -uo pipefail

ENGINE_TREE="${PHONE_ENGINE_TREE:-/opt/dsh-phone}"
PROFILE_TREE="${PHONE_PROFILE_TREE:-$HOME/.dsh/profiles/web}"
ASSET_DIR="${PHONE_ASSET_DIR:-/usr/local/assets}"
REPO="${PHONE_REPO:-$HOME/code/harness-config}"
PKG="@deepseek-ai/dsh-scope"

CHECK=0
QUIET=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --quiet) QUIET=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

say() { [ "$QUIET" = 1 ] || echo "$@"; }
problems=0
repaired=0

# ---------------------------------------------------------------- 1. one scope
# The canonical copy is the profile's: it is the tree the profile's own packages
# resolve, and the engine reaches it through the symlink we are about to assert.
canonical="$(ls -d "$PROFILE_TREE"/node_modules/.pnpm/"@deepseek-ai+dsh-scope"@*/node_modules/"$PKG" 2>/dev/null | head -1)"
flat="$ENGINE_TREE/node_modules/$PKG"

if [ -z "$canonical" ]; then
  say "NO CANONICAL dsh-scope under $PROFILE_TREE — cannot unify; engine may reject every prompt"
  problems=$((problems + 1))
elif [ ! -e "$flat" ] && [ ! -L "$flat" ]; then
  say "dsh-scope missing from $ENGINE_TREE — engine cannot start"
  problems=$((problems + 1))
else
  # same file? compare resolved device+inode, which is what Node's module cache keys on
  flat_real="$(readlink -f "$flat")"
  canon_real="$(readlink -f "$canonical")"
  if [ "$flat_real" = "$canon_real" ]; then
    say "scope: one copy ($canon_real)"
  elif [ "$CHECK" = 1 ]; then
    say "scope: TWO COPIES — $flat_real vs $canon_real (every prompt will be rejected as session/agent-busy)"
    problems=$((problems + 1))
  else
    aside="$flat.npm-copy-$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "$(dirname "$flat")"
    if [ -L "$flat" ]; then
      rm -f "$flat"                       # a symlink is not data; the canonical copy is intact
    else
      mv "$flat" "$aside"                 # a directory is moved aside, never deleted
      say "scope: disowned copy moved to $aside"
    fi
    ln -s "$canonical" "$flat"
    say "scope: unified -> $canonical"
    repaired=$((repaired + 1))
  fi
fi

# ------------------------------------------------------------- 2. phone layer
for asset in mobile.css question-card.css phone-badge.js; do
  src="$REPO/assets/$asset"
  dst="$ASSET_DIR/$asset"
  if [ ! -f "$src" ]; then
    say "asset: $src is absent — nothing to deploy for $asset"
    problems=$((problems + 1))
    continue
  fi
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    continue
  fi
  if [ "$CHECK" = 1 ]; then
    say "asset: $dst is missing or stale"
    problems=$((problems + 1))
  else
    mkdir -p "$ASSET_DIR"
    install -m 0644 "$src" "$dst"
    say "asset: deployed $dst ($(stat -c %s "$dst") bytes)"
    repaired=$((repaired + 1))
  fi
done

if [ "$CHECK" = 1 ]; then
  [ "$problems" -eq 0 ] && { say "phone engine: healthy"; exit 0; }
  exit 2
fi

if [ "$problems" -gt 0 ]; then
  say "repair-phone-engine: $repaired repaired, $problems could not be repaired"
  exit 1
fi
say "repair-phone-engine: healthy, $repaired repaired"
exit 0
