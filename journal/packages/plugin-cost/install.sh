#!/usr/bin/env bash
# Install dsh-plugin-cost into a DSH web profile, idempotently.
#
# Usage:  bash packages/plugin-cost/install.sh [profile-dir]
#         (default profile dir: ${DSH_HOME:-$HOME/.dsh}/profiles/web)
#
# Thin delegate: the two things a profile needs are package-independent, so the logic
# lives once in scripts/install-client-plugin.sh. Before this existed, the cost pill was
# installable only by hand on Windows — which is why the always-on host that serves the
# owner's phone carried no cost pill at all.
#
# The browser half is a `dsh.client` entry assembled from the package manifest, so there is
# nothing else to copy. After running, the profile must reload for the plugin to mount:
# with `"patchReload": "live"` that is usually a page reload, otherwise restart the engine.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
exec bash "$REPO/scripts/install-client-plugin.sh" "$HERE" "${1:-}"
