#!/usr/bin/env bash
# Install one client plugin from this checkout into a DSH web profile, idempotently.
#
# Usage:  scripts/install-client-plugin.sh <package-dir> [profile-dir]
#         profile default: ${DSH_HOME:-$HOME/.dsh}/profiles/web
#
# WHY THIS IS ONE SCRIPT AND NOT ONE PER PACKAGE
# The harness needs exactly two things and neither is specific to a package:
#   1. the package must RESOLVE BY NAME from the profile directory, and
#   2. its name must appear in that profile's `dsh.profile.bundles`.
# Both were previously hand-done per package, and the cost pill never reached the
# always-on host at all — the phone engine's bundle list was `[dsh-base, dsh-web-app,
# dsh-plugin-mobile]` and nothing on that host could install `plugin-cost`, because only
# `plugin-mobile` had an installer and no one noticed the asymmetry (measured 2026-09-14).
# A package that can only be installed by the machine it was written on is the same class
# of gap as a component with no keeper: it works everywhere its author looked.
#
# Link, never copy: this checkout is the source of truth, and a copy drifts from it the
# moment either side is edited. Falls back to a Windows directory junction (needs no
# privilege), and only then to a copy, which says out loud that it will drift.
set -euo pipefail

HERE_SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="${1:-}"
PROFILE="${2:-${DSH_HOME:-$HOME/.dsh}/profiles/web}"

[ -n "$PKG_DIR" ] || { echo "usage: $(basename "$0") <package-dir> [profile-dir]" >&2; exit 2; }
[ -d "$PKG_DIR" ] || { echo "no package directory at $PKG_DIR" >&2; exit 2; }
[ -f "$PKG_DIR/package.json" ] || { echo "no package.json in $PKG_DIR" >&2; exit 2; }
[ -d "$PROFILE" ] || { echo "no profile at $PROFILE" >&2; exit 1; }

PKG_DIR="$(cd "$PKG_DIR" && pwd)"
NODE_BIN="${PHONE_NODE:-$(command -v node || true)}"
[ -n "$NODE_BIN" ] || { echo "node not found; set PHONE_NODE" >&2; exit 2; }
PKG="$("$NODE_BIN" -e "process.stdout.write(require(process.argv[1]).name)" "$PKG_DIR/package.json")"
[ -n "$PKG" ] || { echo "$PKG_DIR/package.json carries no name" >&2; exit 2; }

# 1. resolve by name.
mkdir -p "$PROFILE/node_modules"
link="$PROFILE/node_modules/$PKG"
already=""
if [ -L "$link" ] && [ "$(readlink "$link")" = "$PKG_DIR" ]; then already="symlink"
elif [ -d "$link" ] && [ -f "$link/package.json" ] && [ ! -L "$link" ]; then
  # A junction reads as a directory on this platform, so compare what it points at when
  # the OS can tell us; otherwise accept a package.json bearing the same name.
  already="junction-or-copy"
fi

if [ -n "$already" ]; then
  echo "ok: $link already resolves (${already})"
else
  rm -rf "$link"
  if ln -s "$PKG_DIR" "$link" 2>/dev/null; then
    echo "linked: $link -> $PKG_DIR"
  elif command -v cmd.exe >/dev/null 2>&1; then
    wtarget="$(cygpath -w "$PKG_DIR" 2>/dev/null || printf '%s' "$PKG_DIR")"
    wlink="$(cygpath -w "$link" 2>/dev/null || printf '%s' "$link")"
    if cmd.exe //c mklink /J "$wlink" "$wtarget" >/dev/null 2>&1; then
      echo "junctioned: $link -> $PKG_DIR"
    else
      cp -r "$PKG_DIR" "$link"
      echo "WARNING: copied instead of linked — this copy WILL drift from the checkout"
    fi
  else
    cp -r "$PKG_DIR" "$link"
    echo "WARNING: copied instead of linked — this copy WILL drift from the checkout"
  fi
fi

# 2. add to the bundle list, in place, without a YAML/JSON dependency.
"$NODE_BIN" - "$PROFILE/package.json" "$PKG" <<'JS'
const fs = require('fs')
const [file, name] = process.argv.slice(2)
const config = JSON.parse(fs.readFileSync(file, 'utf8'))
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

echo "installed $PKG. Restart or reload the profile, then confirm the client roster carries it:"
echo "  curl -s http://127.0.0.1:<engine-port>/ -H 'Host: <authority>' | grep -o '$PKG/client.js' | head -1"
