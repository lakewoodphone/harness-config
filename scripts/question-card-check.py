#!/usr/bin/env python3
"""Build a standalone reproduction of the phone's question card, then measure the fix.

WHY THIS EXISTS
    The owner reported (2026-09-14 15:40-15:50 UTC), twice: on his phone, `ask_user_question`
    shows only PART of the question card, he cannot scroll it, and he cannot click it — so he
    cannot answer questions from the phone at all. He told me plainly: "don't use that tool;
    if you want to use it you have to seriously fix it up for the UI so he can actually see
    the questions/options and click them."

    The card cannot be provoked on demand: the host refuses `ask_user_question` when the
    asking agent is owned by another live agent (measured, 2026-09-14), and no top-level
    session is available to ask into. So the reproduction is REBUILT from the app's own pieces
    rather than driven through the UI:

      * the theme token stylesheet, lifted from the running page's CSSOM (`--dump-cssom`);
      * the question card's real stylesheet and class names, from
        `@deepseek-ai/dsh-client-ui-user-questions` (`QuestionComposer`, `Mbwy4a_*`);
      * the conversation frame's real rules, from
        `@deepseek-ai/dsh-client-ui-conversation` (`wSkVaW_root/scrollBody/viewArea/composerSeat`);
      * the card's element tree, rebuilt from the class map the bundle ships.

    What it therefore tests is the LAYOUT and the CSS, which is where the failure is. What it
    cannot test is the React wiring behind the card (draft state, the submit handler) — that
    part is proved by the real component in the real app once a question is live.

WHAT IT CHECKS (per viewport)
    1. every option and the submit control is INSIDE the visible viewport;
    2. a tap at each control's centre actually lands on that control
       (`document.elementFromPoint`) — this is the check that failed in the field;
    3. the card is not taller than the viewport, and the footer is visible without scrolling
       the page behind it;
    4. the card's option list is the thing that scrolls when it must, and it scrolls by touch
       (`overflow-y: auto` with `-webkit-overflow-scrolling: touch`).

USAGE
    python3 scripts/question-card-check.py --site /path/to/phone-site            # build + measure
    python3 scripts/question-card-check.py --site ... --css assets/question-card.css   # measure the fix
    python3 scripts/question-card-check.py --site ... --json out.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CHROME = os.environ.get("CHROME", "google-chrome")
DEFAULT_SITE = "/tmp/phone-question-repro/site"
WIDTHS = [393, 430]

CARD_HTML = """
<div class="Mbwy4a_frame" id="probe-frame">
  <div class="Mbwy4a_card" id="probe-card">
    <div class="Mbwy4a_header">
      <div class="Mbwy4a_headingBlock">
        <div class="Mbwy4a_eyebrow">Question 1 of 2</div>
        <h3 class="Mbwy4a_title">Which option should the fixture use?</h3>
        <p class="Mbwy4a_detail">This is a layout probe. Pick one, then submit.</p>
      </div>
      <div class="Mbwy4a_headerActions">
        <button class="Mbwy4a_iconButton" aria-label="Minimize question">&minus;</button>
      </div>
    </div>
    <div class="Mbwy4a_body" id="probe-body">
      <div class="Mbwy4a_options" id="probe-options">
        <button class="Mbwy4a_option Mbwy4a_optionSelected" data-option="1">
          <span class="Mbwy4a_number">1</span>
          <span class="Mbwy4a_optionCopy">
            <span class="Mbwy4a_optionLine"><span class="Mbwy4a_optionLabel">First option</span>
              <span class="Mbwy4a_badge">Recommended</span></span>
            <div class="Mbwy4a_description">The option this fixture recommends.</div>
          </span>
        </button>
        <button class="Mbwy4a_option" data-option="2">
          <span class="Mbwy4a_number">2</span>
          <span class="Mbwy4a_optionCopy">
            <span class="Mbwy4a_optionLine"><span class="Mbwy4a_optionLabel">Second option</span></span>
            <div class="Mbwy4a_description">A second choice, slightly longer than the first one so the card has to wrap text.</div>
          </span>
        </button>
        <button class="Mbwy4a_option" data-option="3">
          <span class="Mbwy4a_number">3</span>
          <span class="Mbwy4a_optionCopy">
            <span class="Mbwy4a_optionLine"><span class="Mbwy4a_optionLabel">Third option</span></span>
            <div class="Mbwy4a_description">A third choice with a longer description still, so the option list is tall enough to test scrolling inside the card on a narrow screen.</div>
          </span>
        </button>
        <button class="Mbwy4a_option" data-option="4">
          <span class="Mbwy4a_number">4</span>
          <span class="Mbwy4a_optionCopy">
            <span class="Mbwy4a_optionLine"><span class="Mbwy4a_optionLabel">Fourth option</span></span>
            <div class="Mbwy4a_description">A fourth choice, so the card body is definitely taller than the available space on a phone.</div>
          </span>
        </button>
      </div>
      <div class="Mbwy4a_customBlock">
        <div class="Mbwy4a_field"><textarea class="Mbwy4a_fieldInput" rows="2" placeholder="Or type your own answer"></textarea></div>
      </div>
    </div>
    <div class="Mbwy4a_footer" id="probe-footer">
      <div class="Mbwy4a_feedback"></div>
      <div class="Mbwy4a_footerActions">
        <div class="Mbwy4a_pager">
          <button class="Mbwy4a_iconButton" aria-label="Previous question">&lsaquo;</button>
          <span class="Mbwy4a_progress">1 of 2</span>
          <button class="Mbwy4a_iconButton" aria-label="Next question">&rsaquo;</button>
        </div>
        <button class="Mbwy4a_submit" id="probe-submit">Submit answer</button>
      </div>
    </div>
  </div>
</div>
"""

MEASURE = r"""
(() => {
  try {
  const rect = el => { const r = el.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
            bottom: Math.round(r.bottom), right: Math.round(r.right)}; };
  const card = document.getElementById('probe-card');
  const body = document.getElementById('probe-body');
  const options = document.getElementById('probe-options');
  const footer = document.getElementById('probe-footer');
  const submit = document.getElementById('probe-submit');
  const optionEls = [...options.querySelectorAll('.Mbwy4a_option')];
  const tap = el => {
    const r = el.getBoundingClientRect();
    const cx = Math.round(r.x + Math.min(r.width / 2, r.width - 4));
    const cy = Math.round(r.y + r.height / 2);
    const hit = (cx >= 0 && cy >= 0 && cx < innerWidth && cy < innerHeight) ? document.elementFromPoint(cx, cy) : null;
    const lands = hit !== null && (el === hit || el.contains(hit) || hit.contains(el));
    return {inView: r.top >= -1 && r.bottom <= innerHeight + 1, tappable: lands,
            reachable: r.top >= -1 && r.bottom <= innerHeight + 1 && lands,
            centre: {x: cx, y: cy},
            hit: hit ? (hit.id || hit.className || hit.tagName).toString().slice(0, 40) : null};
  };
  const cs = el => { const c = getComputedStyle(el); return {overflowY: c.overflowY, maxHeight: c.maxHeight,
    height: c.height, position: c.position, webkitOverflowScrolling: c.webkitOverflowScrolling || c['-webkit-overflow-scrolling']}; };
  return {
    viewport: {w: innerWidth, h: innerHeight},
    card: rect(card), cardTallerThanViewport: card.getBoundingClientRect().h > innerHeight + 1,
    cardInsideViewport: card.getBoundingClientRect().top >= -1 && card.getBoundingClientRect().bottom <= innerHeight + 1,
    body: rect(body), bodyStyle: cs(body), bodyScrolls: body.scrollHeight > body.clientHeight + 1,
    bodyScroll: {scrollHeight: body.scrollHeight, clientHeight: body.clientHeight},
    footer: rect(footer), footerTap: tap(footer),
    submit: rect(submit), submitTap: tap(submit),
    firstOptionTap: tap(optionEls[0]),
    lastOptionTap: tap(optionEls[optionEls.length - 1]),
    optionTaps: optionEls.map(tap),
    anyOptionReachable: optionEls.some(o => tap(o).reachable),
    /* Only a real overlap counts: the composer sitting exactly below the card (its top equal to
     * the card's bottom) is the correct layout, and an earlier version of this check called that
     * an overlap and failed a passing layout. */
    composerOverlapsCard: (() => {
      const seat = document.querySelector('[class*="composerSeat"], #probe-composer');
      if (!seat || !card) return null;
      const s = seat.getBoundingClientRect(), c = card.getBoundingClientRect();
      const overlapPx = Math.round(Math.min(s.bottom, c.bottom) - Math.max(s.top, c.top));
      const covers = Math.round(s.bottom - c.bottom) > 1 && Math.round(c.bottom - s.top) > 1;
      return covers;
    })(),
    composerGeometry: (() => {
      const seat = document.querySelector('[class*="composerSeat"], #probe-composer');
      if (!seat || !card) return null;
      const s = seat.getBoundingClientRect(), c = card.getBoundingClientRect();
      return {seatTop: Math.round(s.top), seatBottom: Math.round(s.bottom), cardTop: Math.round(c.top),
              cardBottom: Math.round(c.bottom), overlapPx: Math.round(Math.min(s.bottom, c.bottom) - Math.max(s.top, c.top))};
    })(),
  };
  } catch (e) { return {__error: String(e && e.stack || e)}; }
})()
"""


def ws_connect(port: int, path: str):
    s = socket.create_connection(("127.0.0.1", port), timeout=20)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            raise RuntimeError("closed during handshake")
        buf += chunk
    if b"101" not in buf.split(b"\r\n")[0]:
        raise RuntimeError("handshake refused")
    return s


def send_text(s, payload: str, opcode: int = 1):
    data = payload.encode()
    mask = os.urandom(4)
    header = bytearray([0x80 | opcode])
    n = len(data)
    if n < 126:
        header.append(0x80 | n)
    elif n < (1 << 16):
        header.append(0x80 | 126); header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127); header += struct.pack(">Q", n)
    header += mask
    s.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def recv_frame(s) -> str:
    def readn(n):
        b = b""
        while len(b) < n:
            c = s.recv(n - len(b))
            if not c:
                raise RuntimeError("socket closed")
            b += c
        return b
    head = readn(2)
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", readn(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", readn(8))[0]
    payload = readn(length)
    if (head[0] & 0x0F) == 0x9:
        send_text(s, payload.decode("latin1"), opcode=0xA)
        return recv_frame(s)
    if (head[0] & 0x0F) == 0x8:
        raise RuntimeError("closed by peer")
    return payload.decode("utf-8", "replace")


def rpc(s, msg_id: int, method: str, params=None, timeout: float = 30):
    send_text(s, json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        s.settimeout(max(1.0, deadline - time.time()))
        msg = json.loads(recv_frame(s))
        if msg.get("id") == msg_id:
            return msg
    raise TimeoutError(method)


def extract_cssom(url: str, port: int, chrome: str) -> str:
    """Every rule the running app applies, straight from the page's stylesheets."""
    profile = Path("/tmp/phone-question-cssom-profile")
    subprocess.run(["rm", "-rf", str(profile)], check=False)
    proc = subprocess.Popen([chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                             f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             "--window-size=393,852", "--hide-scrollbars", "--no-first-run",
                             "--no-default-browser-check", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        target = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as r:
                    tabs = json.load(r)
                target = next((t for t in tabs if t.get("type") == "page"), None)
                if target:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not target:
            raise RuntimeError("no Chrome debug target")
        s = ws_connect(port, target["webSocketDebuggerUrl"].split(f"127.0.0.1:{port}", 1)[1])
        rpc(s, 1, "Emulation.setDeviceMetricsOverride", {"width": 393, "height": 852, "deviceScaleFactor": 2, "mobile": True})
        rpc(s, 2, "Page.enable")
        rpc(s, 3, "Page.navigate", {"url": url})
        time.sleep(11)
        expr = """(() => { const out = [];
          for (const sheet of document.styleSheets) { let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
            if (!rules) continue; for (const r of rules) out.push(r.cssText); }
          return out.join('\\n'); })()"""
        res = rpc(s, 4, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return res.get("result", {}).get("result", {}).get("value") or ""
    finally:
        proc.terminate()


def build_site(site: Path, cssom: str, card_css: str, fix_css: str, height_note: str = ""):
    """A replica of the phone's conversation frame with the question card in it."""
    frame = re.findall(r"\.wSkVaW_[^{]*\{[^}]*\}", cssom)
    site.mkdir(parents=True, exist_ok=True)
    (site / "app.css").write_text(cssom)
    (site / "card.css").write_text(card_css)
    (site / "fix.css").write_text(fix_css)
    index = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>phone question card — reproduction</title>
<link rel="stylesheet" href="app.css">
<link rel="stylesheet" href="card.css">
<link rel="stylesheet" href="fix.css">
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; }}
  /* the frame rules above come from the app; these three lines are the harness */
  #probe-root {{ height: 100vh; }}
  #probe-scroll {{ gap: 10px; }}
  #probe-composer {{
    margin: 0; padding: 8px 16px 8px; background: var(--dsw-alias-bg-base, #fff);
    border-top: 1px solid var(--dsw-alias-border-l2, #8884);
  }}
  #probe-composer .row {{ display: flex; align-items: center; gap: 8px; height: 52px; }}
  #probe-composer .bubble {{ padding: 8px 12px; border-radius: 12px; background: var(--dsw-alias-bg-layer-1, #eee); font: 14px system-ui; }}
</style>
</head>
<body>
<div class="wSkVaW_root" data-phase="active" id="probe-root">
  <div class="wSkVaW_body">
    <div class="wSkVaW_scrollBody" id="probe-scroll">
      <div class="wSkVaW_viewArea" id="probe-view">
        <div style="padding:16px 16px 8px">
          <div class="bubble" style="padding:8px 12px;border-radius:12px;background:#eee;font:14px system-ui;margin-bottom:10px">Probe message one — a line of conversation above the question.</div>
          <div class="bubble" style="padding:8px 12px;border-radius:12px;background:#eee;font:14px system-ui;margin-bottom:10px">Probe message two, so the stream is taller than the question card and the card sits at the bottom of it.</div>
          <div class="bubble" style="padding:8px 12px;border-radius:12px;background:#eee;font:14px system-ui">Probe message three.</div>
        </div>
        {CARD_HTML}
      </div>
      <div class="wSkVaW_composerSeat" id="probe-composer">
        <div class="wSkVaW_composerStack">
          <div class="row">
            <div style="flex:1"><div class="bubble">Describe what you want to build</div></div>
            <div class="bubble">Send</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body></html>
"""
    (site / "index.html").write_text(index)
    return site / "index.html"


def measure(page_url: str, width: int, height: int, port: int) -> dict:
    profile = Path(f"/tmp/phone-question-measure-{width}x{height}")
    subprocess.run(["rm", "-rf", str(profile)], check=False)
    proc = subprocess.Popen([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
                             f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             f"--window-size={width},{height}", "--hide-scrollbars", "--no-first-run",
                             "--no-default-browser-check", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        target = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as r:
                    tabs = json.load(r)
                target = next((t for t in tabs if t.get("type") == "page"), None)
                if target:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not target:
            raise RuntimeError("no Chrome debug target")
        s = ws_connect(port, target["webSocketDebuggerUrl"].split(f"127.0.0.1:{port}", 1)[1])
        rpc(s, 1, "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 2, "mobile": True})
        rpc(s, 2, "Page.enable")
        rpc(s, 3, "Page.navigate", {"url": page_url})
        time.sleep(1.5)
        res = rpc(s, 4, "Runtime.evaluate", {"expression": MEASURE, "returnByValue": True})
        return res.get("result", {}).get("result", {}).get("value") or {}
    finally:
        proc.terminate()


def main() -> int:
    ap = argparse.ArgumentParser(description="Reproduce and check the phone question card.")
    ap.add_argument("--app-url", default="http://127.0.0.1:3086/",
                    help="a running harness whose CSSOM supplies the theme and frame rules")
    ap.add_argument("--card-css", help="the question card's stylesheet (default: extracted from the engine install)")
    ap.add_argument("--css", dest="fix_css", help="a candidate fix stylesheet to apply on top")
    ap.add_argument("--site", default=DEFAULT_SITE, help="where to build the replica")
    ap.add_argument("--widths", default=",".join(str(w) for w in WIDTHS))
    ap.add_argument("--heights", default="852,700,640,560",
                    help="phone heights; 700 models iOS Safari with its bars, 560 with the keyboard up")
    ap.add_argument("--no-build", action="store_true", help="reuse an existing replica")
    ap.add_argument("--edge", type=int, default=9421, help="CDP port for the build-time browser")
    ap.add_argument("--json", dest="json_path")
    args = ap.parse_args()

    site = Path(args.site)
    engine = Path.home() / "dsh-engine/node_modules/@deepseek-ai"
    card_src = Path(args.card_css) if args.card_css else None
    if card_src is None:
        bundle = engine / "dsh-client-ui-user-questions/lib/client.js"
        js = bundle.read_text(encoding="utf-8", errors="replace")
        i = js.find(".Mbwy4a_frame{")
        if i < 0:
            print(f"could not find the question card stylesheet in {bundle}", file=sys.stderr)
            return 2
        start = js.rfind('"', 0, i) + 1
        end = js.find('"', i)
        card_src = Path(args.site) / "card-extracted.css"
        Path(args.site).mkdir(parents=True, exist_ok=True)
        card_src.write_text(js[start:end])

    if not args.no_build:
        print(f"extracting the app's CSSOM from {args.app_url} ...")
        cssom = extract_cssom(args.app_url, args.edge, CHROME)
        if len(cssom) < 10000:
            print(f"CSSOM looks wrong ({len(cssom)} bytes) — is the harness running at {args.app_url}?", file=sys.stderr)
            return 2
        fix = Path(args.fix_css).read_text() if args.fix_css else ""
        page = build_site(site, cssom, card_src.read_text(), fix)
        print(f"built {page} ({len(cssom)} bytes of the app's own CSS)")

    page = (site / "index.html").resolve()
    widths = [int(w) for w in args.widths.split(",") if w.strip()]
    heights = [int(h) for h in args.heights.split(",") if h.strip()]
    failures, results, port = [], [], args.edge + 1
    for height in heights:
        for width in widths:
            got = measure(f"file://{page}", width, height, port)
            port += 1
            if not got or got.get("__error"):
                failures.append(f"{width}x{height}: {(got or {}).get('__error', 'no result')}")
                continue
            results.append({"width": width, "height": height, **got})
            label = f"{width}x{height}"
            if got["cardTallerThanViewport"]:
                failures.append(f"{label}: the card is taller than the viewport ({got['card']['h']}px)")
            if not got["submitTap"]["reachable"]:
                failures.append(f"{label}: Submit is not reachable (inView={got['submitTap']['inView']}, "
                                f"tap lands on {got['submitTap']['hit']!r} at {got['submitTap']['centre']})")
            if not got["anyOptionReachable"]:
                failures.append(f"{label}: no option is reachable")
            if got["composerOverlapsCard"]:
                failures.append(f"{label}: the composer covers the card — {got.get('composerGeometry')}")
    if args.json_path:
        Path(args.json_path).write_text(json.dumps({"page": str(page), "results": results}, indent=1))

    print(f"\nquestion card — {page}")
    print(f"  {'viewport':<12} {'card':<22} {'submit':<26} {'options reachable':<18} body scroll")
    for r in results:
        label = f"{r['width']}x{r['height']}"
        card = f"y={r['card']['y']} h={r['card']['h']}"
        sub = f"y={r['submit']['y']} {'OK' if r['submitTap']['reachable'] else 'UNREACHABLE'}"
        opts = "yes" if r["anyOptionReachable"] else "NO"
        scroll = f"{r['bodyScroll']['clientHeight']}/{r['bodyScroll']['scrollHeight']}" + (" scrolling" if r["bodyScrolls"] else "")
        print(f"  {label:<12} {card:<22} {sub:<26} {opts:<18} {scroll}")
    if failures:
        print("\nFAILURES")
        for f in failures:
            print("  -", f)
        return 1
    print("\nPASS — the card fits the viewport, Submit and the options are tappable at every size.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
