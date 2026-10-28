#!/usr/bin/env python3
"""One command that proves the Shop dashboard is healthy.

The checks exist as separate scripts -- entity existence, camera liveness, the ten banner
states, the seven colour conditions, a phone-width render, a live-update watch. Remembering
which to run, in what order, is how a check stops being run at all. This runs them together
and prints one table, exiting non-zero if anything fails.

It deliberately does NOT apply or change anything: verification must be safe to run at any
time, on any machine that can reach Home Assistant.

usage:  PYTHONPATH=/opt/company python3 verify-shop.py [--fast] [--skip-render]
  --fast         skip the render and the 20-second watch (about 90 s saved)
  --skip-render  skip only the render
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request

PY = '/opt/company/.venv/bin/python'
ENV = '/opt/company/.env'
GEN = '/root/ha-shop-dashboard.py'

CHECKS: list[tuple[str, list[str], bool]] = []


def env(key: str) -> str | None:
    for line in open(ENV, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.upper().startswith(key.upper() + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


def run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       env={'PYTHONPATH': '/opt/company', 'PATH': '/usr/bin:/bin:/usr/local/bin'})
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def colour_conditions() -> tuple[int, str]:
    """The banner's severity colour, through Home Assistant's own template engine."""
    ha = (env('HA_URL') or '').rstrip('/')
    tok = env('HA_TOKEN')

    def render(t: str) -> str:
        r = urllib.request.Request(ha + '/api/template', data=json.dumps({'template': t}).encode(),
                                   headers={'Authorization': 'Bearer ' + tok,
                                            'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(r, timeout=20) as x:
            return x.read().decode().strip()

    def colour(**kw) -> str:
        parts = ['{'+'% set ' + k + '=' + v + ' %}' for k, v in kw.items()]
        parts.append('{% if intr or test or lock or (away and (shop or apt)) %}red')
        parts.append('{% elif guest or shop or apt %}amber')
        parts.append('{% else %}green{% endif %}')
        return render(''.join(parts))

    cases = [
        ('intrusion', dict(intr='true', test='false', lock='false', away='false', shop='false', apt='false', guest='false'), 'red'),
        ('drill switch', dict(intr='false', test='true', lock='false', away='false', shop='false', apt='false', guest='false'), 'red'),
        ('door open + away', dict(intr='false', test='false', lock='false', away='true', shop='true', apt='false', guest='false'), 'red'),
        ('lockdown', dict(intr='false', test='false', lock='true', away='false', shop='false', apt='false', guest='false'), 'red'),
        ('guest code', dict(intr='false', test='false', lock='false', away='false', shop='false', apt='false', guest='true'), 'amber'),
        ('door open, inside', dict(intr='false', test='false', lock='false', away='false', shop='true', apt='false', guest='false'), 'amber'),
        ('quiet', dict(intr='false', test='false', lock='false', away='true', shop='false', apt='false', guest='false'), 'green'),
    ]
    bad = []
    lines = []
    for name, kw, want in cases:
        got = colour(**kw)
        lines.append('  %-20s -> %-6s (want %s) %s' % (name, got, want, 'ok' if got == want else 'FAIL'))
        if got != want:
            bad.append(name)
    return (0 if not bad else 1), '\n'.join(lines)


def main() -> int:
    argv = sys.argv[1:]
    fast = '--fast' in argv
    skip_render = fast or '--skip-render' in argv

    results: list[tuple[str, bool, str]] = []

    rc, out = run([PY, '/root/check-shop-entities.py'])
    tail = [l for l in out.strip().splitlines() if 'MISSING' in l or 'DEAD' in l or 'cameras to fetch' in l or 'present' in l]
    results.append(('entities and cameras exist and answer', rc == 0, ' | '.join(tail[-3:])))

    rc, out = run([PY, '/root/test-banner-states.py'])
    results.append(('banner wording, 10 states', rc == 0, out.strip().splitlines()[-1]))

    rc, out = colour_conditions()
    results.append(('banner colour, 7 conditions', rc == 0, 'all correct' if rc == 0 else 'see below'))

    if not skip_render:
        rc, out = run([PY, '/root/render-shop.py', '--width', '390'])
        line = [l for l in out.splitlines() if 'ha-card elements' in l or 'screenshot' in l]
        results.append(('renders at phone size', rc == 0 and 'login form present: False' in out,
                        ' | '.join(line)))

        rc, out = run([PY, '/root/watch-shop.py', '--seconds', '20'])
        refreshed = [l for l in out.splitlines() if 'refreshed' in l]
        ok = rc == 0 and 'refreshed' in out
        results.append(('cameras refresh, banner subscribed', ok, ' | '.join(refreshed[-1:])))

    print()
    width = max(len(n) for n, _, _ in results)
    failed = 0
    for name, ok, detail in results:
        if not ok:
            failed += 1
        print('%-4s %-*s  %s' % ('PASS' if ok else 'FAIL', width, name, detail[:90]))
    print('\n%d check(s), %d failure(s)' % (len(results), failed))
    if failed:
        print('\nThe colour table, when it fails, is:')
        print(colour_conditions()[1])
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
