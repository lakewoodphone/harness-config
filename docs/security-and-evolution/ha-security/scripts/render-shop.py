#!/usr/bin/env python3
"""Screenshot the Shop dashboard at phone size, using a headless browser on the host.

Why here and not from the agent's own browser tools: Home Assistant requires authentication
(measured: /api/states answers 401 from the office network, so there is no trusted-network
bypass). Rendering the dashboard therefore needs a token, and a credential value must never be
printed into a session transcript. Running the browser ON the host lets it read HA_TOKEN from
/opt/company/.env directly, so the secret never leaves this machine.

The output is a PNG at a 390x844 viewport -- the phone size the layout was measured against --
which is the only way to check what the owner will actually see.

usage:  PYTHONPATH=/opt/company python3 render-shop.py [--url-path shop-view] [--width 390]
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


async def main() -> int:
    from playwright.async_api import async_playwright

    argv = sys.argv[1:]
    url_path = argv[argv.index('--url-path') + 1] if '--url-path' in argv else 'shop-view'
    width = int(argv[argv.index('--width') + 1]) if '--width' in argv else 390
    height = 844

    ha = (env('HA_URL') or '').rstrip('/')
    token = env('HA_TOKEN')
    if not ha or not token:
        print('HA_URL or HA_TOKEN missing')
        return 2
    print('rendering %s/%s at %dx%d' % (ha.split('//')[-1], url_path, width, height))

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path='/usr/bin/google-chrome',
            args=['--no-sandbox', '--disable-dev-shm-usage', '--hide-scrollbars'])
        ctx = await browser.new_context(viewport={'width': width, 'height': height},
                                        device_scale_factor=2, is_mobile=True,
                                        has_touch=True)
        page = await ctx.new_page()
        _log = []
        page.on('console', lambda m: _log.append((m.type, m.text[:200])))
        page.on('pageerror', lambda e: _log.append(('pageerror', str(e)[:200])))
        page.on('requestfailed', lambda r: _log.append(('reqfail', (r.url[:90] + ' ' + str(r.failure)))))

        # seed the auth store the way the companion app does, from the host's own env
        await page.goto(ha + '/', wait_until='domcontentloaded')
        tokens = {
            'access_token': token,
            'token_type': 'Bearer',
            'expires_in': 315360000,
            'refresh_token': '',
            'expires': int(time.time() * 1000) + 315360000000,
            'hassUrl': ha,
            'clientId': None,
        }
        await page.evaluate(
            "t => { localStorage.setItem('hassTokens', t); }", json.dumps(tokens))

        await page.goto('%s/%s' % (ha, url_path), wait_until='domcontentloaded')
        # the frontend renders cards asynchronously; wait for a card to exist, then settle
        try:
            await page.wait_for_selector('ha-card, .card', timeout=45000)
        except Exception:
            print('warning: no card appeared within 45 s')
        await page.wait_for_timeout(25000)

        # SCROLL THE WHOLE PAGE BEFORE JUDGING IT (2026-10-28). Cards below the fold had
        # never been looked at by a headless page that does not scroll: the logbook and the
        # camera tiles both rendered as an empty box and four spinners in the first capture,
        # with zero console errors. Scrolling forces every card's data subscription to start.
        await page.evaluate('''async () => {
            const step = window.innerHeight * 0.8;
            for (let y = 0; y < document.body.scrollHeight; y += step) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 700));
            }
            window.scrollTo(0, 0);
            await new Promise(r => setTimeout(r, 1500));
        }''')

        title = await page.title()
        login = await page.query_selector('ha-authorize, ha-auth-flow, form[action*="auth"]')
        print('page title: %r | login form present: %s' % (title, bool(login)))

        cards = await page.query_selector_all('ha-card')
        print('ha-card elements rendered: %d' % len(cards))
        for i, c in enumerate(cards[:12], 1):
            box = await c.bounding_box()
            text = (await c.inner_text())[:70].replace('\n', ' ')
            print('  %2d. %4.0fx%-4.0f  %s' % (i, (box or {}).get('width', 0),
                                               (box or {}).get('height', 0), text))

        print('--- browser console (errors and failures) ---')
        for kind, text in _log[-25:]:
            print('  [%s] %s' % (kind, text))
        out = '/root/shop-%d.png' % width
        await page.screenshot(path=out, full_page=True)
        print('screenshot: %s' % out)
        await browser.close()
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
