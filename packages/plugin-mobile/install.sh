#!/usr/bin/env bash
# Install dsh-plugin-mobile into a DSH web profile, idempotently.
#
# Usage:  bash packages/plugin-mobile/install.sh [profile-dir]
#         (default profile dir: ${DSH_HOME:-$HOME/.dsh}/profiles/web)
#
# Thin delegate: the harness needs exactly two things from any client plugin — that the
# package resolves by name from the profile directory, and that its name appears in that
# profile's `dsh.profile.bundles` — and neither is specific to this package. Both live once
# in scripts/install-client-plugin.sh so a second plugin cannot be written with half of it;
# that asymmetry is exactly how `plugin-cost` ended up with no installer at all.
#
# The installer links rather than copies (this checkout is the source of truth, and a copy
# drifts), falling back to a Windows directory junction, and only then to a copy that warns.
#
# After running, the profile must reload for the plugin to mount. With
# `"patchReload": "live"` this is usually a page reload; otherwise restart the engine.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
exec bash "$REPO/scripts/install-client-plugin.sh" "$HERE" "${1:-}"
