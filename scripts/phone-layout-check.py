#!/usr/bin/env python3
"""Assert the phone composer stays on ONE line, in the states a real session reaches.

WHY THIS EXISTS
    On 2026-09-14 the owner photographed his phone's composer showing two rows of controls —
    `+` / attach / cost pill above, model / context meter / send below — *after* the commit
    that claimed to fix exactly that. The earlier change removed two controls, which lowered
    how often the row overflows but left the overflow possible: the shipped row is
    `display:flex; flex-wrap:wrap` with the trailing group carrying `margin-left:auto`, so
    the moment `tools + trailing + gap` exceeds the card the RIGHT group drops to its own
    line. An empty session never shows it (its row needs 232 px of 351 px); a session with
    usage always does. Reading the CSS did not find that. Measuring boxes did. This is that
    measurement, kept as a check so the next change to the layer cannot regress it silently.

WHAT IT DOES
    Drives headless Chrome over the DevTools Protocol (standard library only, no driver), at
    each width in WIDTHS, and at each state in STATES composes the row's real markup — the
    cost pill from `plugin-cost` (20 px tall, LEFT group) and the context meter plus the stop
    control of an active turn (trailing group) — then asserts:

      * every control inside the composer sits on ONE vertical band, and
      * the composer's row does not overflow its card, and
      * the two groups do not overlap.

    Exit code 0 only if every width/state passes. `--json PATH` writes the measurements.

USAGE
    python3 scripts/phone-layout-check.py                       # http://127.0.0.1:3086/
    python3 scripts/phone-layout-check.py --url https://secratary.tail93e6e6.ts.net/
    python3 scripts/phone-layout-check.py --widths 320,393,430 --states pill,meter,stop
    CHROME=/usr/bin/google-chrome python3 scripts/phone-layout-check.py

NOTES
    * Point it at the GATE (the port `serve-phone.sh` publishes), not the engine: the gate is
      what injects the phone layer and serves /dsh-phone-mobile.css.
    * `Emulation.setDeviceMetricsOverride` is the only way to change the viewport; resizing
      from inside the page does not work and produced a false pass once.
    * A synthetic click cannot start a real turn here (the composer input is a contenteditable
      div and a headless focus does not take), so states are composed from the app's own
      markup rather than driven through the UI. That measures the LAYOUT, which is the thing
      that regressed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:3086/"
DEFAULT_WIDTHS = [320, 358, 375, 393, 430]
DEFAULT_STATES = ["pill", "meter", "stop"]
CHROME = os.environ.get("CHROME", "google-chrome")

PROBE = r"""
(() => {
  try {
  const opts = __OPTS__;
  const row = [...document.querySelectorAll('[class*="composer"] [class*="_row"]')].find(r => r.querySelector('button'));
  if (!row) return {error: 'no composer control row in the document'};
  const tools = row.querySelector('[class*="_tools"]');
  const trailing = row.querySelector('[class*="_trailing"]');
  if (!tools || !trailing) return {error: 'composer row has no _tools/_trailing group'};
  const seat = document.querySelector('[class*="composerSeat"]');
  const rect = el => { const r = el.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
            right: Math.round(r.right), bottom: Math.round(r.bottom)}; };
  const clear = () => [...row.querySelectorAll('[data-layout-probe]')].forEach(e => e.remove());
  const pill = () => {  // plugin-cost, conversation.input.left: height 20, LEFT group
    const s = document.createElement('span');
    s.dataset.layoutProbe = 'pill';
    s.style.cssText = 'position:relative;flex:none;display:inline-flex';
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = '$0.0049';
    b.style.cssText = 'display:inline-flex;align-items:center;gap:4px;padding:0 8px;height:20px;border:1px solid currentColor;border-radius:10px;font-size:12px;white-space:nowrap';
    s.appendChild(b); return s;
  };
  const meter = () => {  // ContextMeter: 28x28, trailing group
    const s = document.createElement('span');
    s.dataset.layoutProbe = 'meter';
    s.style.cssText = 'display:inline-flex;position:relative;flex:none';
    const b = document.createElement('button');
    b.type = 'button'; b.setAttribute('aria-label', 'Context: 1000 of 128000 tokens');
    b.style.cssText = 'display:inline-flex;align-items:center;width:28px;height:28px';
    s.appendChild(b); return s;
  };
  const stop = () => {  // an active turn swaps Send for Stop
    const b = document.createElement('button');
    b.dataset.layoutProbe = 'stop';
    b.setAttribute('aria-label', 'Stop generating');
    b.style.cssText = 'width:44px;height:44px;flex:none';
    return b;
  };
  const preexisting = {
    pills: [...row.querySelectorAll('span, button')].filter(e => /^\$\d/.test((e.textContent || '').trim())).length,
    meters: row.querySelectorAll('button[aria-label^="Context"]').length,
    rowHTMLLen: row.innerHTML.length,
  };
  clear();
  if (opts.pill) tools.appendChild(pill());
  if (opts.meter) trailing.insertBefore(meter(), trailing.lastElementChild);
  if (opts.stop) trailing.insertBefore(stop(), trailing.lastElementChild);

  const visible = el => { const r = el.getBoundingClientRect(); return r.height > 0 && r.width > 0; };
  const buttons = [...row.querySelectorAll('button, [data-layout-probe]')].filter(visible);
  /* A ROW is judged by each control's VERTICAL CENTRE, not its top edge: a 20 px pill and a
   * 44 px send button share a line but not a `y`, and comparing tops reported two bands for a
   * correct layout (measured 2026-09-14 — the first version of this check failed itself). */
  const centres = buttons.map(b => { const r = b.getBoundingClientRect(); return r.y + r.height / 2; })
                        .sort((a, b) => a - b);
  let bands = [];
  for (const c of centres) {
    if (!bands.length || c - bands[bands.length - 1] > 12) bands.push(c);
  }
  bands = bands.map(Math.round);
  const rowBox = rect(row), toolsBox = rect(tools), trailingBox = rect(trailing), seatBox = rect(seat || row);
  const out = {
    row: rowBox, tools: toolsBox, trailing: trailingBox, seat: seatBox,
    bands, bandCount: bands.length, preexisting,
    controls: buttons.map(b => ({label: b.getAttribute('aria-label') || (b.textContent || '').trim().slice(0, 12), ...rect(b)})),
    overlap: toolsBox.right > trailingBox.x,
    rowOverflowsCard: trailingBox.right > rowBox.right + 1 || toolsBox.x < rowBox.x - 1,
    seatHeightOfScreen: seat ? +(seatBox.h / window.innerHeight).toFixed(3) : null,
  };
  clear();
  return out;
  } catch (e) { return {error: String((e && e.stack) || e)}; }
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
            raise RuntimeError("closed during WebSocket handshake")
        buf += chunk
    if b"101" not in buf.split(b"\r\n")[0]:
        raise RuntimeError("handshake refused: " + buf.split(b"\r\n")[0].decode(errors="replace"))
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


def evaluate(s, msg_id: int, expression: str):
    res = rpc(s, msg_id, "Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return res.get("result", {}).get("result", {}).get("value")


def main() -> int:
    ap = argparse.ArgumentParser(description="Assert the phone composer stays on one line.")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"gate URL (default {DEFAULT_URL})")
    ap.add_argument("--widths", default=",".join(str(w) for w in DEFAULT_WIDTHS))
    ap.add_argument("--states", default=",".join(DEFAULT_STATES),
                    help="comma list of pill,meter,stop — each is added cumulatively")
    ap.add_argument("--height", type=int, default=852)
    ap.add_argument("--settle", type=float, default=11.0, help="seconds to let the app boot")
    ap.add_argument("--port", type=int, default=9411, help="CDP port for the throwaway browser")
    ap.add_argument("--json", dest="json_path", help="write measurements here")
    ap.add_argument("--keep-open", action="store_true", help="leave the browser running for a screenshot")
    args = ap.parse_args()

    widths = [int(w) for w in args.widths.split(",") if w.strip()]
    wanted = [s.strip() for s in args.states.split(",") if s.strip()]
    for s in wanted:
        if s not in ("pill", "meter", "stop"):
            print(f"unknown state {s!r}; expected pill, meter, stop", file=sys.stderr)
            return 2

    # each state is cumulative: pill alone, then pill+meter, then pill+meter+stop
    combos = []
    for i in range(len(wanted)):
        opts = {k: k in wanted[: i + 1] for k in ("pill", "meter", "stop")}
        combos.append((("+".join(k for k in ("pill", "meter", "stop") if opts[k])), opts))

    profile = Path("/tmp/phone-layout-check-profile")
    subprocess.run(["rm", "-rf", str(profile)], check=False)
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", f"--remote-debugging-port={args.port}",
         f"--user-data-dir={profile}", f"--window-size={widths[0]},{args.height}", "--hide-scrollbars",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failures, results = [], []
    try:
        target = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/json", timeout=2) as r:
                    tabs = json.load(r)
                target = next((t for t in tabs if t.get("type") == "page"), None)
                if target:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not target:
            print("could not reach a Chrome debug target — is CHROME installed?", file=sys.stderr)
            return 2
        s = ws_connect(args.port, target["webSocketDebuggerUrl"].split(f"127.0.0.1:{args.port}", 1)[1])

        booted = False
        mid = 0
        for width in widths:
            mid += 1
            rpc(s, mid, "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": args.height, "deviceScaleFactor": 2, "mobile": True})
            if not booted:
                mid += 1
                rpc(s, mid, "Page.enable")
                mid += 1
                rpc(s, mid, "Page.navigate", {"url": args.url})
                time.sleep(args.settle)
                booted = True
            else:
                time.sleep(0.6)
            for label, opts in combos:
                mid += 1
                got = evaluate(s, mid, PROBE.replace("__OPTS__", json.dumps(opts)))
                results.append({"width": width, "state": label, **(got or {})})
                if not got or got.get("error"):
                    failures.append(f"w={width} {label}: {(got or {}).get('error', 'no result')}")
                    continue
                if got["bandCount"] != 1:
                    failures.append(f"w={width} {label}: {got['bandCount']} control bands at y={got['bands']} "
                                    f"(controls: {[c['label'] for c in got['controls']]})")
                if got["rowOverflowsCard"]:
                    failures.append(f"w={width} {label}: row overflows its card "
                                    f"(trailing right {got['trailing']['right']} > row right {got['row']['right']})")
                if got["overlap"]:
                    failures.append(f"w={width} {label}: the two groups overlap "
                                    f"(tools right {got['tools']['right']} > trailing x {got['trailing']['x']})")

        if args.json_path:
            Path(args.json_path).write_text(json.dumps({"url": args.url, "results": results}, indent=1))
        print(f"phone composer layout — {args.url}")
        print(f"  widths {widths} · states {[c[0] for c in combos]}")
        for r in results:
            flag = "ok " if r.get("bandCount") == 1 and not r.get("rowOverflowsCard") and not r.get("overlap") \
                else "FAIL"
            print(f"  {flag} w={r['width']:>3} {r['state']:<18} bands={r.get('bandCount')} "
                  f"row h={r.get('row', {}).get('h')} seat={r.get('seatHeightOfScreen')} of screen")
        if failures:
            print("\nFAILURES")
            for f in failures:
                print("  -", f)
            return 1
        print("\nPASS — one control band, no overflow, no overlap, at every width and state.")
        return 0
    finally:
        if not args.keep_open:
            proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
