set -u
ENVF=/home/zabz/personal-secretary-mvp/.env
KEY='sk-82d12148-630f-455a-aa8d-7dd10e08a758'

echo "=== 1. store it where the other provider keys already live, mode 600 ==="
if [ -f "$ENVF" ]; then
  if grep -q '^SPIDER_API_KEY=' "$ENVF"; then
    sed -i "s|^SPIDER_API_KEY=.*|SPIDER_API_KEY=$KEY|" "$ENVF"
    echo "updated the existing SPIDER_API_KEY line"
  else
    printf '\n# spider.cloud - metered scraping for bot-walled and JS pages (added 2026-09-30)\nSPIDER_API_KEY=%s\n' "$KEY" >> "$ENVF"
    echo "appended SPIDER_API_KEY"
  fi
  chmod 600 "$ENVF"
else
  umask 077; printf 'SPIDER_API_KEY=%s\n' "$KEY" > "$ENVF"; echo "created $ENVF"
fi
ls -la "$ENVF"
echo "occurrences of the key value in the repo tree: $(grep -rl "$KEY" /home/zabz/harness-config 2>/dev/null | wc -l)  (must be 0)"

export SPIDER_API_KEY="$KEY"
URL='https://www.ebay.com/sch/i.html?_nkw=iphone+14+screen+replacement'

echo
echo "=== 2. SPIDER on the page that beats us today: an eBay search for a part we actually buy ==="
CODE=$(curl -s -o /tmp/spider.out -w '%{http_code}' -X POST https://api.spider.cloud/scrape \
  -H "Authorization: Bearer $SPIDER_API_KEY" -H 'Content-Type: application/json' \
  -d "{\"url\":\"$URL\",\"return_format\":\"markdown\"}" --max-time 60)
echo "http $CODE, bytes $(wc -c < /tmp/spider.out)"
echo "--- first 400 bytes of what came back ---"
head -c 400 /tmp/spider.out
echo

echo "=== 3. JINA on the same URL, for comparison ==="
JCODE=$(curl -s -o /tmp/jina.out -w '%{http_code}' "https://r.jina.ai/$URL" --max-time 60)
echo "http $JCODE, bytes $(wc -c < /tmp/jina.out)"
echo "--- first 300 bytes ---"
head -c 300 /tmp/jina.out
echo

echo "=== 4. does the response contain real listing text, or a wall ==="
grep -ci 'iphone' /tmp/spider.out 2>/dev/null | sed 's/^/spider mentions iphone: /'
grep -ci 'iphone' /tmp/jina.out 2>/dev/null | sed 's/^/jina mentions iphone: /'
