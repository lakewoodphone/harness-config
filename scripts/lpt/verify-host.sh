#!/usr/bin/env bash
# Verify a DEPLOYED host - production by default, or any host passed as the first argument.
#
# Written for production after the first promotion, and now parameterised so the same nine claims can be
# checked against test after a landing. Every line prints the reading next to the expectation.
set -uo pipefail
P="${1:-https://lakewoodphoneandtech.com}"
ALLOW_OLD="${2:-}"
ok=0; bad=0
chk() { # label, got, want-regex
  if printf '%s' "$2" | grep -qE "$3"; then printf '  PASS  %-44s %s\n' "$1" "$2"; ok=$((ok+1));
  else printf '  FAIL  %-44s %s (wanted %s)\n' "$1" "$2" "$3"; bad=$((bad+1)); fi
}

echo "HOST CHECK  $P  $(date -u +%Y-%m-%dT%H:%M:%SZ)"

stamp=$(curl -s -m 30 --retry 3 --retry-delay 1 --retry-all-errors "$P/" | grep -o '/assets/index-[A-Za-z0-9._-]*\.js' | head -1)
entry=$(curl -s -m 60 --retry 3 --retry-delay 1 --retry-all-errors "$P$stamp" | grep -o 'lpt-build-commit[^0-9a-f]\{0,12\}[0-9a-f]\{7,40\}' | head -1 | grep -o '[0-9a-f]\{7,40\}$')
echo "  entry asset : $stamp"
echo "  build commit: ${entry:-unknown}"
# A MISSING STAMP IS NOT A PASS (2026-10-28). The bundle did not answer with a commit, so this line can say
# nothing about which build is being served - and calling that PASS is the "an answer that never closed" mistake.
if [ -z "$entry" ]; then
  printf '  UNVERIFIED  %-40s the entry bundle did not report a commit\n' "host build commit"; bad=$((bad+1))
elif [ -n "$ALLOW_OLD" ] && [ "${entry#$ALLOW_OLD}" != "$entry" ]; then
  printf '  FAIL  %-44s still the old build %s\n' "host is serving the new build" "$ALLOW_OLD"; bad=$((bad+1))
else
  printf '  PASS  %-44s %s\n' "host reports its build commit" "$entry"; ok=$((ok+1))
fi

code=$(curl -s -o /dev/null -m 30 --retry 3 --retry-delay 1 --retry-all-errors -w '%{http_code}' "$P/status")
chk "GET /status answers 200" "$code" "^200$"

html=$(curl -s -m 30 --retry 3 --retry-delay 1 --retry-all-errors "$P/status")
chk "/status title is its own" "$(printf '%s' "$html" | grep -o '<title>[^<]*</title>' | head -1)" "Repair Status"
chk "/status canonical is /status" "$(printf '%s' "$html" | grep -o 'rel="canonical" href="[^"]*"' | head -1)" "/status"
chk "/status is noindex" "$(printf '%s' "$html" | grep -o 'name="robots" content="[^"]*"' | head -1)" "noindex"

n=$(curl -s -m 30 --retry 3 --retry-delay 1 --retry-all-errors "$P/kosher-waze" | grep -o '\$[0-9]' | wc -l)
chk "raw /kosher-waze carries no dollar figure" "$n" "^0$"

code=$(curl -s -o /dev/null -m 30 --retry 3 --retry-delay 1 --retry-all-errors -w '%{http_code}' "$P/assets/index-DOESNOTEXIST.js")
chk "a missing asset answers 404 (F1-17)" "$code" "^404$"

code=$(curl -s -o /dev/null -m 30 --retry 3 --retry-delay 1 --retry-all-errors -w '%{http_code}' "$P/definitely-not-a-route-xyz")
chk "an unknown path answers 404" "$code" "^404$"

sm=$(curl -s -m 30 --retry 3 --retry-delay 1 --retry-all-errors "$P/sitemap.xml" | grep -c '<loc>')
chk "sitemap lists the public pages" "$sm" "^[5-9]$|^[1-9][0-9]$"

echo "  ----"
echo "  $ok passed, $bad failed"
exit 0
