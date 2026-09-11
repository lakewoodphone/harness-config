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

# 1. resolve by name
mkdir -p "$PROFILE/node_modules"
link="$PROFILE/node_modules/$PKG"
if [ -L "$link" ] && [ "$(readlink "$link")" = "$HERE" ]; then
  echo "ok: $link already points at $HERE"
else
  rm -rf "$link"
  ln -s "$HERE" "$link"
  echo "linked: $link -> $HERE"
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
