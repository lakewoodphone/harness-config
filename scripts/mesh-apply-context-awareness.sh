#!/usr/bin/env bash
# mesh-apply-context-awareness.sh — install the context-awareness capability on ONE host.
#
# WHY A SCRIPT AND NOT A LIST OF COMMANDS. This runs on five machines with four different
# Python/Node/DSH layouts, and 2026-10-26 showed the cost of doing it by hand: the first
# attempt edited the DEPLOYED profile patch with the repo's rule, put straight double quotes
# inside a double-quoted YAML scalar, and `dsh: failed to parse overlay` would have stopped
# the web profile booting on the owner's own laptop. One reviewed procedure, run identically
# everywhere, verified by reading the result, is the only version of this that is safe to
# repeat.
#
# WHAT IT DOES, IN ORDER (the order matters):
#   1. install the package into <repo>/packages/ (a NEW path — nothing is overwritten)
#   2. mirror persona rule 8 into <repo>/presets/zabz/agent.cordis.yml, ONLY when the old rule
#      is present verbatim (a host on a different lineage is reported, never guessed at)
#   3. run harness-sync: it installs presets, links packages/* into the profile's
#      node_modules and NAMES every package that declares dsh.bundle.patch in
#      dsh.profile.bundles — which is what makes the engine load it
#   4. verify by READING: the installed preset, the link, the composed profile tree
#
# It never deletes, never force-pulls, never restarts a service and never touches a frozen host.
#
# INPUTS (scp'd by the caller): /tmp/ca-pkg, /tmp/ca-rule8.txt, /tmp/ca-mirror.py
# USAGE: bash /tmp/ca-apply.sh            (REPO/DSH_HOME may be overridden by env)
set -uo pipefail

REPO="${REPO:-$HOME/code/harness-config}"
DSH_HOME_DIR="${DSH_HOME:-$HOME/.dsh}"
PKG=/tmp/ca-pkg
RULE=/tmp/ca-rule8.txt
MIRROR=/tmp/ca-mirror.py
INSTALLED="$DSH_HOME_DIR/.agent-presets/zabz/agent.cordis.yml"
PRESET="$REPO/presets/zabz/agent.cordis.yml"

echo "host=$(hostname) repo=$REPO dsh_home=$DSH_HOME_DIR"

# 1 — the package itself. A new directory on every host measured 2026-10-26.
#
# `scp -r <src> host:/tmp/ca-pkg` puts the package INSIDE /tmp/ca-pkg, so the source is
# /tmp/ca-pkg/plugin-context-awareness and a naive `cp -R /tmp/ca-pkg/. dest/` nests it one
# level too deep — measured on secratary-cloud and zabz-tech-linux as `link=no bundle=absent`
# with the directory present and `package.json` missing from it. Resolve the real source.
SRC="$PKG"
[ -d "$PKG/plugin-context-awareness" ] && SRC="$PKG/plugin-context-awareness"
if [ -d "$SRC" ] && [ -f "$SRC/package.json" ] && [ -d "$REPO/packages" ]; then
  mkdir -p "$REPO/packages/plugin-context-awareness"
  cp -R "$SRC/." "$REPO/packages/plugin-context-awareness/"
  # Repair a nested copy from an earlier run of this same script, without deleting anything.
  if [ -d "$REPO/packages/plugin-context-awareness/plugin-context-awareness" ]; then
    mv "$REPO/packages/plugin-context-awareness/plugin-context-awareness" "/tmp/ca-nested-$(date +%s)" 2>/dev/null || true
  fi
  echo "pkg=installed files=$(find "$REPO/packages/plugin-context-awareness" -type f | wc -l | tr -d ' ')"
else
  echo "pkg=SKIPPED (no package.json at $SRC, or $REPO/packages missing)"
fi

# 2 — rule 8, surgically. The old text must be there verbatim, or this host is not touched.
if grep -q 'The window gets thrown away' "$PRESET" 2>/dev/null; then
  if python3 "$MIRROR" --rule 8 --from "$RULE" --only-targets --target "$PRESET"; then
    echo "mirror=ok"
  else
    echo "mirror=FAILED"
  fi
elif grep -q 'You can see your own context' "$PRESET" 2>/dev/null; then
  echo "mirror=already"
else
  echo "mirror=skipped (neither rule present — this host's preset is a different lineage)"
fi

# 3 — harness-sync installs the preset and names the bundle.
#
# TWO ENVIRONMENT FIXES, both measured 2026-10-26 rather than guessed:
#   * `merge-settings.mjs` resolves `yaml` from `DSH_INSTALL/node_modules` first. On a host whose
#     profile has the module (`~/.dsh/profiles/web/node_modules/yaml`) and whose repo does not,
#     setting DSH_INSTALL is what makes the FIRST step of harness-sync succeed — and every later
#     step (presets, links, bundle names) is skipped when that one throws.
#   * the candidate list also includes `$PWD/node_modules`, so running from the repo fixes the
#     opposite case (repo has yaml, profile does not).
NODE_BIN="$(command -v node || true)"
if [ -n "$NODE_BIN" ] && [ -f "$REPO/scripts/harness-sync.mjs" ]; then
  cd "$REPO" 2>/dev/null || true
  if [ -f "$DSH_HOME_DIR/profiles/web/node_modules/yaml/package.json" ]; then
    export DSH_INSTALL="$DSH_HOME_DIR/profiles/web"
  fi
  "$NODE_BIN" "$REPO/scripts/harness-sync.mjs" >/tmp/ca-sync.log 2>&1
  echo "sync_rc=$?"
  grep -E 'preset zabz|profile bundles|settings' /tmp/ca-sync.log | sed 's/^ */sync: /'
else
  echo "sync=SKIPPED (node: ${NODE_BIN:-none})"
fi

# 4 — verify by reading what the engine will load.
echo "installed_new=$(grep -c 'You can see your own context' "$INSTALLED" 2>/dev/null || echo 0)"
echo "installed_old=$(grep -c 'The window gets thrown away' "$INSTALLED" 2>/dev/null || echo 0)"
if [ -e "$DSH_HOME_DIR/profiles/web/node_modules/dsh-plugin-context-awareness" ]; then
  echo "link=yes"
else
  echo "link=no"
fi
grep -o 'dsh-plugin-context-awareness' "$DSH_HOME_DIR/profiles/web/package.json" >/dev/null 2>&1 \
  && echo "bundle=named" || echo "bundle=absent"
if [ -f "$DSH_HOME_DIR/profiles/web/cordis.patch.yml" ] && grep -q 'The window gets thrown away' "$DSH_HOME_DIR/profiles/web/cordis.patch.yml" 2>/dev/null; then
  echo "deployed_profile=carries_old_rule"
else
  echo "deployed_profile=clean_or_absent"
fi
