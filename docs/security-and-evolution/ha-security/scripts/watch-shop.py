#!/usr/bin/env python3
"""Watch the live Shop view: does the banner re-render on a state change, and do the cameras refresh?

A screenshot proves a page rendered once. It says nothing about the two behaviours that decide
whether the page is any use at 3am:

  1. **Does the banner update on its own?** A markdown card subscribes to the entities its
     template uses and re-renders on change -- but only if the template really touches them. A
     card that renders once and then freezes looks perfect in a screenshot and is worthless.
  2. **Do the camera tiles keep refreshing?** A `picture-entity` with `camera_view: auto` is
     supposed to poll roughly every 10 seconds. If it fetches once, every tile becomes a
     photograph of a moment that has passed -- the exact failure the estate keeps paying for.

Both are checked by sampling the live DOM twice, 15 seconds apart, without touching any entity.

usage: PYTHONPATH=/opt/company python3 watch-shop.py [--url-path shop-view] [--seconds 15]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

ENV = '/opt/company/.env'


def env(key: str) -> str | None:
    for line in open(ENV, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.upper().startswith(key.upper() + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


# HOME ASSISTANT CARDS LIVE IN SHADOW DOM (2026-10-28). `document.querySelectorAll('ha-card')`
# and `ha-card img` return nothing from page.evaluate -- the first run measured 0 images and an
# empty banner and looked like a dead dashboard. Playwright LOCATORS pierce open shadow roots,
# so the sampling goes through them instead of raw DOM queries.


WALK_CARD = '''(el) => {
  function text(node, depth) {
    if (depth > 12) return '';
    let out = '';
    if (node.nodeType === 3) out += node.textContent;
    if (node.shadowRoot) out += text(node.shadowRoot, depth + 1);
    for (const c of (node.childNodes || [])) out += text(c, depth + 1);
    return out;
  }
  return text(el, 0).replace(/\\s+/g, ' ').trim();
}'''


async def sample(page) -> dict:
    try:
        # nested shadow roots (ha-card -> ha-markdown -> ...) defeat both document queries and
        # a single-level locator, so the tree is walked explicitly
        banner = await page.locator('ha-card').first.evaluate(WALK_CARD)
    except Exception as exc:  # noqa: BLE001
        banner = '(banner unreadable: %s)' % type(exc).__name__
    srcs = await page.locator('ha-card img').evaluate_all(
        "els => els.map(e => e.getAttribute('src') || '')")
    return {'banner': ' '.join(banner.split()), 'images': srcs}


async def main() -> int:
    from playwright.async_api import async_playwright

    argv = sys.argv[1:]
    url_path = argv[argv.index('--url-path') + 1] if '--url-path' in argv else 'shop-view'
    gap = int(argv[argv.index('--seconds') + 1]) if '--seconds' in argv else 15

    ha = (env('HA_URL') or '').rstrip('/')
    token = env('HA_TOKEN')
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/usr/bin/google-chrome',
                                          args=['--no-sandbox', '--disable-dev-shm-usage'])
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                        device_scale_factor=2, is_mobile=True, has_touch=True)
        page = await ctx.new_page()
        await page.goto(ha + '/', wait_until='domcontentloaded')
        tokens = {'access_token': token, 'token_type': 'Bearer', 'expires_in': 315360000,
                  'refresh_token': '', 'expires': int(time.time() * 1000) + 315360000000,
                  'hassUrl': ha, 'clientId': None}
        await page.evaluate("t => localStorage.setItem('hassTokens', t)", json.dumps(tokens))
        await page.goto('%s/%s' % (ha, url_path), wait_until='domcontentloaded')
        try:
            await page.wait_for_selector('ha-card', timeout=45000)
        except Exception:
            print('no cards appeared')
            return 1
        await page.wait_for_timeout(6000)
        # scroll once so every card below the fold has started its data subscription -- a card
        # that was never on screen has nothing to refresh, and measuring it proves nothing
        await page.evaluate('''async () => {
            const step = window.innerHeight * 0.8;
            for (let y = 0; y < document.body.scrollHeight; y += step) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 600));
            }
            window.scrollTo(0, 0);
            await new Promise(r => setTimeout(r, 1200));
        }''')

        first = await sample(page)
        print('t=0   banner: %s' % first['banner'][:90])
        print('t=0   images: %d' % len(first['images']))
        await page.wait_for_timeout(gap * 1000)
        second = await sample(page)
        print('t=%ds  banner: %s' % (gap, second['banner'][:90]))

        # 1. does the banner text track the live state?
        changed = first['banner'] != second['banner']
        print('\nbanner changed on its own in %ds: %s' % (gap, changed))
        if changed:
            print('   (a state change reached the card -- it is subscribed, not frozen)')

        # 2. do the image sources rotate? a cache-busting token in the src is the signature of
        #    a polling card; an unchanged src over 15 s means a still that never refreshes.
        a = first['images']
        b = second['images']
        common = min(len(a), len(b))
        if common == 0:
            print('camera images present: 0 (nothing to measure)')
        else:
            same = sum(1 for i in range(common) if a[i] == b[i])
            print('camera images: %d, unchanged src after %ds: %d' % (common, gap, same))
            print('   refreshed: %d of %d' % (common - same, common))
        await browser.close()
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
