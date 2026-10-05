#!/usr/bin/env bash
# deploy-lpt-frontend.sh — the ONE way to deploy the shop's frontend, so nobody has to
# rediscover where the Cloudflare credential lives.
#
# WHY THIS EXISTS (2026-10-05)
# The token was never lost: it was written to `~/.secrets/cloudflare.env` on 2026-09-18 and
# verified working at the time. But nothing said so, nothing sourced it, and a non-interactive
# shell (`ssh host "cmd"`, cron, a scheduled shift) does not read a login profile — so every
# automated attempt found `CLOUDFLARE_API_TOKEN` unset and the work queue recorded "blocked on
# a credential" for weeks. The credential was fine; the *path to it* did not exist.
#
# This script is that path. It is deliberately the only documented way in.
#
# USAGE
#   scripts/deploy-lpt-frontend.sh --env test                    # build + deploy to test
#   scripts/deploy-lpt-frontend.sh --env test --dry-run          # prove it, change nothing
#   scripts/deploy-lpt-frontend.sh --repo /path/to/checkout --env test
#
# It NEVER deploys to production. Production is a separate, deliberate act by the owner.
set -euo pipefail

SECRETS="${LPT_CLOUDFLARE_SECRETS:-$HOME/.secrets/cloudflare.env}"
REPO_DEFAULT="/home/zabz/repos/phone-and-tech-full"
ENV_NAME="test"
REPO="$REPO_DEFAULT"
EXTRA=()

while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --dry-run) EXTRA+=(--dry-run); shift ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

if [ "$ENV_NAME" = "production" ]; then
  echo "REFUSING: this wrapper deploys to the TEST environment only." >&2
  echo "Production is a deliberate owner action; ask before you take it." >&2
  exit 2
fi

# 1. the credential, from its one home
if [ ! -f "$SECRETS" ]; then
  echo "FAIL: no Cloudflare credential at $SECRETS" >&2
  echo "  It should hold CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID (mode 600)." >&2
  echo "  If it is missing, the token creator is a Cloudflare User API token; see" >&2
  echo "  docs/operations/CREDENTIALS-WHERE-THEY-LIVE.md" >&2
  exit 2
fi
# shellcheck disable=SC1090
. "$SECRETS"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN missing from $SECRETS}"
: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID missing from $SECRETS}"
echo "credential: $SECRETS  (token len ${#CLOUDFLARE_API_TOKEN})"

# 2. prove the token is alive BEFORE a build, so a dead token fails in seconds not minutes
code=$(curl -s -o /tmp/cf-verify.$$ -w '%{http_code}' \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  https://api.cloudflare.com/client/v4/user/tokens/verify || true)
rm -f /tmp/cf-verify.$$
if [ "$code" != "200" ]; then
  echo "FAIL: the Cloudflare token did not verify (HTTP $code). It may be expired or revoked." >&2
  exit 2
fi
echo "token: active"

# 3. the deploy itself
cd "$REPO"
export PATH="/home/zabz/node/bin:/usr/lib/node_modules/corepack/shims:$PATH"
echo "deploying from $REPO ($(git rev-parse --short HEAD)) to --env $ENV_NAME"
exec node scripts/deploy-frontend-cloudflare.mjs --env "$ENV_NAME" "${EXTRA[@]}"
