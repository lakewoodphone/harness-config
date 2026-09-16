#!/bin/bash
# Correction: the frontend is on Cloudflare Pages, not Netlify. Fold three rows into one ask.
# 2026-09-16 ~02:4xZ, ZABZ-YOGA. Evidence: docs/operations/FRONTEND_HOSTING_CLOUDFLARE.md,
# netlify.toml header, wrangler.jsonc header, scripts/deploy-frontend-cloudflare.mjs.
Q="python3 $HOME/bin/owner-queue.py"

$Q resolve 71 --dismissed "Wrong provider, and the correction came from the owner challenging it. The frontend has been served by CLOUDFLARE PAGES since 2026-09-14 - docs/operations/FRONTEND_HOSTING_CLOUDFLARE.md says Status: LIVE, and netlify.toml's own header says ROLLBACK PATH ONLY as of 2026-09-14. The Netlify belief came from a stale comment in .github/workflows/deploy-staging.yml and was carried into older queue rows. Replaced by the Cloudflare access row."

$Q resolve 38 --dismissed "Same missing credential as the Cloudflare access row: the filterapp A record is one Zone DNS edit, and a single scoped token clears it together with the Pages deploy and the R2 bucket. Folded so he answers once."

$Q resolve 47 --dismissed "Same missing credential as the Cloudflare access row: the photos-only R2 bucket needs R2:Edit on the same token. Folded."

$Q add --severity high --age-days 0 --source "Owner challenge 2026-09-16; docs/operations/FRONTEND_HOSTING_CLOUDFLARE.md" \
  --question "May I have one Cloudflare API token for the lakewoodphoneandtech.com zone and account - Pages:Edit, Zone DNS:Edit, R2:Edit? The fleet currently cannot deploy its own customer-facing site at all: the frontend moved to Cloudflare Pages on 2026-09-14 and the token that did the migration was never stored on any machine, so every frontend change since then has been stuck - including the fix for the site telling customers you are open Wednesday." \
  --recommendation "One token, all three scopes. It clears four separate blockers in one go: the Wednesday hours fix can ship, the filterapp A record gets created, the photo app's key stops being able to read the nightly database backups, and PR #142 stops being stuck. Cloudflare lets you scope a token to exactly this zone and these permissions, so it is not a master key." \
  --options "One token with Pages:Edit, Zone DNS:Edit and R2:Edit (recommended)|A Pages:Edit token only - you add the DNS record yourself|No token - you will run the deploys yourself when I prepare them" \
  --context "Measured 2026-09-16 02:2x-02:4xZ. LIVE HEADERS: lakewoodphoneandtech.com and www both return 200 from Server: cloudflare, NS aron/patryk.ns.cloudflare.com, A records are Cloudflare anycast. REPO: wrangler.jsonc says Cloudflare Pages is the frontend's hosting target and gives the reason - Netlify charged 15 credits per deploy against a 300-credit allowance, about 37 deploys a month were attempted, the allowance ran out and no frontend change could ship at all (HTTP 403 Account credit usage exceeded). netlify.toml is retained only as the rollback path. DEPLOY: node scripts/deploy-frontend-cloudflare.mjs --env production, which requires CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID in the environment. Neither is stored on the authority, this laptop, or in any env file I can reach (searched 02:4xZ)." \
  --blocks "Public hours fix, filterapp DNS record, R2 backup isolation, PR 142"

echo "== FINAL =="
$Q stats
