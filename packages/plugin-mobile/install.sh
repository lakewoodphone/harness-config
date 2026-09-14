#!/usr/bin/env bash
# Install dsh-plugin-mobile into a DSH web profile, idempotently.
#
# Does the two things the harness requires and nothing else:
#   1. the package must resolve by name from the profile directory, so a symlink into this
#      checkout is created — a symlink rather than a copy because this repo is the source of
#      truth and a copy would drift the moment the plugin is edited;
#   2. the package name must appear in the profile's `dsh.profile.bundles`, which is the
#      list read when the profile boots.
#
# Usage:  bash packages/plugin-mobile/install.sh [profile-dir]
#         (default profile dir: ${DSH_HOME:-$HOME/.dsh}/profiles/web)
#
# After running, the profile must reload for the plugin to mount. With
# `"patchReload": "live"` this is usually a page reload; otherwise restart the engine.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${1:-${DSH_HOME:-$HOME/.dsh}/profiles/web}"
PKG="dsh-plugin-mobile"

[ -d "$PROFILE" ] || { echo "no profile at $PROFILE" >&2; exit 1; }

# 1. resolve by name.
#
# A symlink needs a privilege on Windows that a normal shell does not have, so this falls back
# to a directory junction (which needs none) and only then to a copy. Measured 2026-09-14: the
# local profile on ZABZ-YOGA carries `dsh-plugin-cost (Junction)` and `dsh-plugin-windows
# (Junction)` — evidence that `ln -s` alone is not enough on this fleet. A copy is the last
# resort and says so, because a copy drifts from the checkout the moment either side is edited.
mkdir -p "$PROFILE/node_modules"
link="$PROFILE/node_modules/$PKG"
already=""
if [ -L "$link" ] && [ "$(readlink "$link")" = "$HERE" ]; then already="symlink"
elif [ -d "$link" ] && [ -f "$link/package.json" ] && [ ! -L "$link" ]; then already="maybe-junction"
fi

if [ -n "$already" ]; then
  echo "ok: $link already resolves (${already})"
else
  rm -rf "$link"
  if ln -s "$HERE" "$link" 2>/dev/null; then
    echo "linked: $link -> $HERE"
  elif command -v cmd.exe >/dev/null 2>&1; then
    wtarget="$(cygpath -w "$HERE" 2>/dev/null || printf '%s' "$HERE")"
    wlink="$(cygpath -w "$link" 2>/dev/null || printf '%s' "$link")"
    if cmd.exe //c mklink /J "$wlink" "$wtarget" >/dev/null 2>&1; then
      echo "junctioned: $link -> $HERE"
    else
      cp -r "$HERE" "$link"
      echo "WARNING: copied instead of linked — this copy WILL drift from the checkout"
    fi
  else
    cp -r "$HERE" "$link"
    echo "WARNING: copied instead of linked — this copy WILL drift from the checkout"
  fi
fi

# 2. add to the bundle list, in place, without a YAML/JSON dependency
node - "$PROFILE/package.json" "$PKG" <<'JS'
const fs = require('fs')
const [file, name] = process.argv.slice(2)
const text = fs.readFileSync(file, 'utf8')
const config = JSON.parse(text)
config.dsh = config.dsh || {}
config.dsh.profile = config.dsh.profile || {}
const bundles = config.dsh.profile.bundles || []
if (bundles.includes(name)) {
  console.log('ok: bundle list already contains ' + name)
  process.exit(0)
}
bundles.push(name)
config.dsh.profile.bundles = bundles
fs.writeFileSync(file, JSON.stringify(config, null, 2) + '\n')
console.log('added: ' + name + ' -> ' + file)
JS

echo "installed. Restart or reload the profile, then confirm the client roster contains $PKG:"
echo "  curl -s http://127.0.0.1:3089/ -H 'Host: <authority>' | grep -o '$PKG/client.js' | head -1"
