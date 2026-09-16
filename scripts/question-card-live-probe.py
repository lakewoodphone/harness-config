#!/usr/bin/env python3
"""Diagnose the phone question card IN THE REAL APP, not in a replica.

WHY THIS EXISTS
    `question-card-check.py` measures a replica it builds from the app's CSSOM plus the card's
    own class map. That is enough to test the card's internals, and it is why the owner's
    Submit-button complaint was fixed. It is NOT enough for the failure he reported next
    (2026-09-14 23:2x UTC): "I can't scroll up enough to see the actual question. I just see
    the options for responses."

    The card is not a top-level element. `dsh-client-ui-user-questions` injects it into the
    chain slot `conversation.composer`, which `dsh-client-ui-conversation` renders with
    `overlay: true` INSIDE `.wSkVaW_composerSeat` - the last box in `.wSkVaW_scrollBody`, i.e.
    the bottom of the conversation. Whether `position: fixed` on its frame reaches the
    viewport therefore depends on the real ancestor chain (a `transform`, `filter`,
    `will-change` or `contain` above it becomes the containing block), and the replica cannot
    see that chain at all.

WHAT IT DOES, against the running app at a phone viewport
    1. loads the app and reports where the card would live - the composer seat and the
       ancestor chain above it, which is what decides whether `position: fixed` escapes to the
       viewport or gets trapped by an ancestor;
    2. mounts the card's real markup, with the real class names, where the app mounts it;
    3. waits, then reports the geometry - card, QUESTION TITLE, options, Submit - and whether
       the question is inside the band the reader can see;
    4. reads back `window.__dshPhoneCard`, the measurement `dsh-plugin-mobile` leaves behind
       when it pins the sheet to that band, so the repair is proved and not assumed.

USAGE
    python3 scripts/question-card-live-probe.py --url http://127.0.0.1:3086/
    python3 scripts/question-card-live-probe.py --url ... --band 240,420      # keyboard-band
    python3 scripts/question-card-live-probe.py --url ... --json /tmp/live-card.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_spec = importlib.util.spec_from_file_location(
    "qcc", str(Path(__file__).resolve().parent / "question-card-check.py"))
qcc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qcc)

CARD = qcc.CARD_HTML.replace("probe-", "live-")

MOUNT = r"""
(() => {
  const seat = document.querySelector('[data-composer-seat]');
  if (!seat) return {ok: false, error: 'no composer seat - is the app loaded and a session open?'};
  const holder = document.createElement('div');
  holder.innerHTML = (window.__probeCard || '').trim();
  const frame = holder.firstElementChild;
  seat.prepend(frame);
  window.__probeFrame = frame;
  return {ok: true, seat: seat.getBoundingClientRect().toJSON(),
          ancestors: (() => { const out = []; let el = seat;
            while (el && el !== document.documentElement) { const s = getComputedStyle(el);
              out.push({cls: String(el.className || el.tagName).slice(0, 50), position: s.position,
                        transform: s.transform === 'none' ? null : 'transform',
                        contain: s.contain === 'none' ? null : s.contain,
                        overflow: s.overflow}); el = el.parentElement; } return out; })()};
})()
"""

READ = r"""
(() => {
  const frame = window.__probeFrame;
  if (!frame) return {ok: false, error: 'no card mounted'};
  const r = el => { if (!el) return null; const b = el.getBoundingClientRect();
    return {y: Math.round(b.y), bottom: Math.round(b.bottom), h: Math.round(b.height), w: Math.round(b.width)}; };
  const title = frame.querySelector('[class*="_title"]');
  const vv = window.visualViewport || {offsetTop: 0, height: innerHeight, scale: 1};
  const band = {top: Math.round(vv.offsetTop), height: Math.round(vv.height), scale: vv.scale};
  const titleBox = r(title);
  const inline = {};
  for (const name of ['position', 'top', 'height', 'max-height', 'z-index']) {
    const v = frame.style.getPropertyValue(name);
    if (v) inline[name] = v + (frame.style.getPropertyPriority(name) ? ' !important' : '');
  }
  return {
    ok: true,
    band,
    viewport: {innerWidth, innerHeight},
    frame: Object.assign(r(frame), {position: getComputedStyle(frame).position}),
    card: r(frame.firstElementChild),
    title: titleBox,
    options: r(frame.querySelector('[class*="_options"]')),
    submit: r(frame.querySelector('[class*="_submit"]')),
    questionVisibleInBand: titleBox === null ? null
      : (titleBox.y >= band.top - 1 && titleBox.bottom <= band.top + band.height + 1),
    inlineRepair: inline,
    pluginMeasurement: window.__dshPhoneCard || null,
    documentScroll: Math.round((document.scrollingElement || {}).scrollTop || 0),
  };
})()
"""


def drive(url, width, height, port, steps, wait_s=12.0):
    """Open the live app at a phone viewport and run each (expression, settle-seconds) step."""
    profile = Path("/tmp/live-card-probe-%dx%d" % (width, height))
    subprocess.run(["rm", "-rf", str(profile)], check=False)
    proc = subprocess.Popen([qcc.CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
                             "--remote-debugging-port=%d" % port,
                             "--user-data-dir=%s" % profile,
                             "--window-size=%d,%d" % (width, height),
                             "--hide-scrollbars", "--no-first-run",
                             "--no-default-browser-check", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        target = None
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json" % port, timeout=2) as r:
                    tabs = json.load(r)
                target = next((t for t in tabs if t.get("type") == "page"), None)
                if target:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not target:
            raise RuntimeError("no Chrome debug target")
        s = qcc.ws_connect(port, target["webSocketDebuggerUrl"].split("127.0.0.1:%d" % port, 1)[1])
        qcc.rpc(s, 1, "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": height, "deviceScaleFactor": 2, "mobile": True})
        qcc.rpc(s, 2, "Page.enable")
        qcc.rpc(s, 3, "Page.navigate", {"url": url})
        time.sleep(wait_s)
        i = 10
        for expr, settle in steps:
            i += 1
            res = qcc.rpc(s, i, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
            if res.get("result", {}).get("exceptionDetails"):
                out["step%d" % i] = {"error": json.dumps(res["result"]["exceptionDetails"])[:400]}
            else:
                out["step%d" % i] = res.get("result", {}).get("result", {}).get("value")
            if settle:
                time.sleep(settle)
        return out
    finally:
        proc.terminate()


def main():
    ap = argparse.ArgumentParser(description="Probe the phone question card inside the live app.")
    ap.add_argument("--url", default="http://127.0.0.1:3086/")
    ap.add_argument("--heights", default="852,640")
    ap.add_argument("--band", help="simulate the visible band as top,height (a keyboard up)")
    ap.add_argument("--json", dest="json_path")
    ap.add_argument("--assert", dest="do_assert", action="store_true",
                    help="exit non-zero unless the question is inside the band at every height")
    args = ap.parse_args()

    band_expr = "null"
    if args.band:
        top, hgt = (int(v) for v in args.band.split(","))
        band_expr = json.dumps({"top": top, "height": hgt})
    steps = [("window.__probeCard = " + json.dumps(CARD), 0.0),
             ("window.__probeBand = " + band_expr, 0.0)]
    if args.band:
        steps.append((r"""
          (() => { const b = window.__probeBand; const vv = window.visualViewport;
            if (!vv) return 'no visualViewport';
            try { Object.defineProperty(vv, 'offsetTop', {get: function () { return b.top; }, configurable: true});
                  Object.defineProperty(vv, 'height', {get: function () { return b.height; }, configurable: true});
                  vv.dispatchEvent(new Event('resize'));
                  return 'band forced to ' + JSON.stringify(b); }
            catch (e) { return 'could not force the band: ' + String(e); } })()""", 0.3))
    steps += [(MOUNT, 1.5), (READ, 0.0)]

    everything = {}
    for height in [int(h) for h in args.heights.split(",") if h.strip()]:
        got = drive(args.url, 393, height, 9600 + (height % 100), steps)
        everything[str(height)] = got
        print("=== 393x%d%s ===" % (height, (" (band %s)" % args.band) if args.band else ""))
        mount = next((v for v in got.values() if isinstance(v, dict) and "ancestors" in v), {})
        read = next((v for v in reversed(list(got.values())) if isinstance(v, dict) and "band" in v), {})
        if not mount.get("ok"):
            print("  mount failed:", mount or got)
            continue
        print("  seat ancestors: " + "; ".join(
            "%s[%s%s%s]" % (a["cls"], a["position"], ",transform" if a["transform"] else "",
                            (",contain:" + a["contain"]) if a["contain"] else "")
            for a in (mount.get("ancestors") or [])[:5]))
        print("  band=%s viewport=%s" % (read.get("band"), read.get("viewport")))
        print("  frame=%s" % (read.get("frame"),))
        print("  card=%s  title=%s  submit=%s" % (read.get("card"), read.get("title"), read.get("submit")))
        print("  QUESTION VISIBLE IN BAND: %s" % (read.get("questionVisibleInBand"),))
        print("  inline repair on the frame: %s" % (read.get("inlineRepair") or {},))
        print("  plugin measurement: %s" % json.dumps(read.get("pluginMeasurement")))
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(everything, indent=1))

    if args.do_assert:
        problems = []
        for height, got in everything.items():
            read = next((v for v in reversed(list(got.values()))
                         if isinstance(v, dict) and "band" in v), None)
            if read is None:
                problems.append("%s: the card could not be mounted or read" % height)
                continue
            if read.get("questionVisibleInBand") is not True:
                problems.append("%s: the question is NOT inside the band (title=%s band=%s)"
                                % (height, read.get("title"), read.get("band")))
            expected_repair = args.band is not None and read.get("pluginMeasurement", {}).get("fits") is False
            if expected_repair and not read.get("inlineRepair"):
                problems.append("%s: the band is offset but the repair was not applied (%s)"
                                % (height, read.get("pluginMeasurement")))
            if not expected_repair and read.get("inlineRepair"):
                problems.append("%s: a fitting card carries a repair" % height)
        if problems:
            print("FAIL — " + "; ".join(problems))
            return 1
        print("PASS — the question is inside the visible band at every size tried.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
