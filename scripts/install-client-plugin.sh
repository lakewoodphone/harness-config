#!/usr/bin/env bash
# Install one client plugin from this checkout into a DSH web profile, idempotently.
#
# Usage:  scripts/install-client-plugin.sh <package-dir> [profile-dir]
#         profile default: ${DSH_HOME:-$HOME/.dsh}/profiles/web
#
# Exit:   0 installed (linked, and named in dsh.profile.bundles when it IS a bundle)
#         1 no profile directory at the path given
#         2 usage / no package / no node
#         3 REFUSED -- the package declares no `dsh.bundle.patch`, so it is linked but never
#           named; a name that was already in the list has been removed. See "THE GATE" below.
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
# THE GATE, ADDED 2026-09-17 BECAUSE THIS SCRIPT STILL CARRIED THE DEFECT THAT WAS FIXED ON WINDOWS
# `dsh.profile.bundles` is not a dependency list. Every name in it is mounted as a patch LAYER, and
# the loader THROWS on a name whose package declares no `dsh.bundle.patch`:
#
#     Error: dsh: profile bundle "dsh-mesh-broker" declares no dsh.bundle in its package.json
#         at dsh-app-boot/lib/index.js:852
#
# so ONE such name stops the engine booting at all -- while the engine that is already running
# looks perfectly healthy, because an engine reads its profile at start. `packages/` holds both
# kinds of thing: bundles (`dsh-plugin-*`) and plain programs with a `bin` started as their own
# process (`mesh-broker`, `deepseek-proxy`). `install-client-plugins.ps1` was repaired for exactly
# this on 2026-09-17, after it made two Windows machines unable to boot (docs/mesh/90-provider-mount.md
# §3, journal pain/lessons L1865); this script kept the pre-fix behaviour -- it pushed the name in
# with no test at all (old lines 77-85) -- until now.
#
# It is worse here than it was on Windows. This is the installer the macOS node is provisioned with,
# and that node's engine is a LaunchDaemon with `RunAtLoad` + `KeepAlive{SuccessfulExit:false}`
# (docs/mesh/97-fleet-repairs.md §1.5): a profile that cannot boot is not a node that goes quiet,
# it is a crash loop the node's own supervisor sustains. So the rule is the loader's own, enforced
# before the list is touched: **never name a bundle you have not just proved declares one.**
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

# 2. name it in the bundle list ONLY if its manifest declares a bundle, in place, without a
# YAML/JSON dependency. A package that declares none is left linked and reported as refused.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
refused=0
"$NODE_BIN" - "$PROFILE/package.json" "$PKG" "$PKG_DIR/package.json" "$STAMP" <<'JS' || refused=$?
const fs = require('fs')
const [file, name, pkgJsonPath, stamp] = process.argv.slice(2)
const declared = JSON.parse(fs.readFileSync(pkgJsonPath, 'utf8')).dsh?.bundle?.patch
const config = JSON.parse(fs.readFileSync(file, 'utf8'))
config.dsh = config.dsh || {}
config.dsh.profile = config.dsh.profile || {}
const bundles = config.dsh.profile.bundles || []

// The loader's own test, exactly: dsh-app-boot reads `dsh?.bundle?.patch` and throws when it is
// `undefined`. An empty string is refused too -- the loader would try to read a directory as the
// patch layer and fail on the next boot instead.
if (!declared) {
  if (!bundles.includes(name)) {
    console.log('declares no dsh.bundle -- linked, never named as a bundle: ' + name)
  } else {
    const kept = bundles.filter((n) => n !== name)
    const backup = file + '.bak-' + stamp
    fs.copyFileSync(file, backup)
    config.dsh.profile.bundles = kept
    fs.writeFileSync(file, JSON.stringify(config, null, 2) + '\n')
    console.log('declares no dsh.bundle -- REMOVING from the bundle list (naming it stops the engine booting): ' + name)
    console.log('removed: ' + name + ' | bundles now: ' + kept.length + ' | backup: ' + backup)
  }
  process.exit(3)
}

if (bundles.includes(name)) {
  console.log('ok: bundle list already contains ' + name)
  process.exit(0)
}
const backup = file + '.bak-' + stamp
fs.copyFileSync(file, backup)
bundles.push(name)
config.dsh.profile.bundles = bundles
fs.writeFileSync(file, JSON.stringify(config, null, 2) + '\n')
console.log('added: ' + name + ' -> ' + file)
console.log('backup: ' + backup + ' | bundles now: ' + bundles.length)
JS

if [ "$refused" -eq 3 ]; then
  echo "REFUSED: $PKG declares no dsh.bundle.patch in its package.json, so it is NOT named in" >&2
  echo "         dsh.profile.bundles -- naming it would stop the engine booting (dsh-app-boot:852)." >&2
  echo "         It resolves by name (linked above) and anything that runs it by its bin still can." >&2
  exit 3
elif [ "$refused" -ne 0 ]; then
  echo "the bundle list could not be updated (node exit $refused); $PROFILE/package.json is untouched" >&2
  exit "$refused"
fi

echo "installed $PKG. Restart or reload the profile, then confirm the client roster carries it:"
echo "  curl -s http://127.0.0.1:<engine-port>/ -H 'Host: <authority>' | grep -o '$PKG/client.js' | head -1"
