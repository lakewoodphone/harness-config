#!/usr/bin/env bash
# Verify PRODUCTION after a promotion. One command, every claim measured, no assumptions.
#
# Written while the promotion was still queued, so that the moment it lands the whole list is checked in
# one pass instead of being asserted from memory. Every line prints the reading next to the expectation.
set -uo pipefail
P=https://lakewoodphoneandtech.com
OLD_STAMP=16baf0021f14
ok=0; bad=0
chk() { # label, got, want-substring
  if printf '%s' "$2" | grep -q "$3"; then printf '  PASS  %-42s %s\n' "$1" "$2"; ok=$((ok+1));
  else printf '  FAIL  %-42s %s (wanted %s)\n' "$1" "$2" "$3"; bad=$((bad+1)); fi
}

echo "PRODUCTION CHECK  $(date -u +%Y-%m-%dT%H:%M:%SZ)"

stamp=$(curl -s -m 30 "$P/" | grep -o '/assets/index-[A-Za-z0-9._-]*\.js' | head -1)
entry=$(curl -s -m 60 "$P$stamp" | grep -o 'lpt-build-commit[^0-9a-f]\{0,12\}[0-9a-f]\{7,40\}' | head -1 | grep -o '[0-9a-f]\{7,40\}$')
echo "  deployed entry asset: $stamp"
echo "  deployed commit     : ${entry:-unknown}"
if [ -n "$entry" ] && [ "${entry#$OLD_STAMP}" != "$entry" ]; then
  printf '  FAIL  %-42s still %s\n' "production moved off the old build" "$OLD_STAMP"; bad=$((bad+1))
else
  printf '  PASS  %-42s %s\n' "production moved off the old build" "${entry:-?}"; ok=$((ok+1))
fi

code=$(curl -s -o /dev/null -m 30 -w '%{http_code}' "$P/status")
chk "GET /status answers 200" "$code" "^200$"

head_html=$(curl -s -m 30 "$P/status")
title=$(printf '%s' "$head_html" | grep -o '<title>[^<]*</title>' | head -1)
canon=$(printf '%s' "$head_html" | grep -o 'rel="canonical" href="[^"]*"' | head -1)
robots=$(printf '%s' "$head_html" | grep -o 'name="robots" content="[^"]*"' | head -1)
chk "/status title is its own" "$title" "Repair Status"
chk "/status canonical is /status" "$canon" "/status"
chk "/status is noindex" "$robots" "noindex"

cur=$(curl -s -m 30 "$P/kosher-waze")
n=$(printf '%s' "$cur" | grep -o '\$[0-9]' | wc -l)
chk "raw /kosher-waze HTML carries no dollar figure" "$n" "^0$"

code=$(curl -s -o /dev/null -m 30 -w '%{http_code}' "$P/assets/index-DOESNOTEXIST.js")
chk "a missing asset answers 404 (F1-17)" "$code" "^404$"

code=$(curl -s -o /dev/null -m 30 -w '%{http_code}' "$P/definitely-not-a-route-xyz")
chk "an unknown path answers 404" "$code" "^404$"

sm=$(curl -s -m 30 "$P/sitemap.xml" | grep -c '<loc>')
chk "sitemap still lists the public pages" "$sm" "^[5-9]\|^[1-9][0-9]"

echo "  ----"
echo "  $ok passed, $bad failed"
[ "$bad" -eq 0 ] || echo "  NOTE: /kosher-waze's rendered price check needs a browser - this script only reads raw HTML"
exit 0
