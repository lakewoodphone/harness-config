#!/usr/bin/env python3
"""End-to-end probe for the phone stack.

Run this ON the machine that hosts the stack (default: the authority).
It answers one question: can a cold visitor with nothing but a URL reach a
working harness, and does the document they land on actually authenticate.

Six checks, in the order a real phone walks them:

  1. cold visitor        GET / with no cookie and no token   -> 302 with a token
  2. redemption          GET that redirect                   -> 303 + dsh-auth cookie
  3. document            GET / with the cookie               -> 200, harness HTML
  4. websocket           upgrade on /api/remote.mux          -> 101
  5. fence               foreign Host header                 -> not 200
  6. outside-in          real HTTPS through Tailscale Serve  -> 302 -> 303 -> 200

Check 4 is the one that matters most and is easiest to fake: a page that loads
but cannot open its socket looks broken on the phone and fine in curl.

Usage:  python3 scripts/probe-phone.py [authority-hostname]
Exit code 0 only if every check that can run passed.
"""
import http.client
import json
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

STATE = Path.home() / ".dsh-phone"
AUTHORITY = sys.argv[1] if len(sys.argv) > 1 else "secratary.tail93e6e6.ts.net"
GATE = ("127.0.0.1", 3086)
REDIRECT = ("127.0.0.1", 3087)

results = []


def record(n, name, ok, detail):
    results.append((n, name, ok, detail))
    print(f"  {n}. {'PASS' if ok else 'FAIL'}  {name}: {detail}")


def live_token():
    """Newest engine log wins. Returns (token, log) or (None, why)."""
    logs = sorted(STATE.glob("engine-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return None, f"no engine-*.log under {STATE}"
    log = logs[-1]
    for path in logs:
        text = path.read_text(errors="replace")
        idx = text.rfind("?token=")
        if idx >= 0:
            token = text[idx + 7:].split()[0].strip()
            if token:
                age = int(time.time() - path.stat().st_mtime)
                return token, f"{path.name} ({age}s old)"
    return None, f"{log.name} carries no token"


def request(host_port, method, path, headers=None, body=None, family=socket.AF_INET):
    conn = http.client.HTTPConnection(*host_port, timeout=20)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    payload = resp.read(4000)
    out = {
        "status": resp.status,
        "headers": {k.lower(): v for k, v in resp.getheaders()},
        "body": payload,
    }
    conn.close()
    return out


def check_cold_visitor():
    """No cookie, no token: the gate must hand back a redeemable link itself."""
    r = request(GATE, "GET", "/", {"Host": AUTHORITY, "Accept": "text/html"})
    loc = r["headers"].get("location", "")
    tok = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query).get("token", [""])[0]
    ok = r["status"] in (301, 302, 303, 307) and tok
    record(1, "cold visitor gets a link",
           ok, f"{r['status']} -> {loc[:70] or '(no Location)'}")
    return tok


def check_redeem(token):
    if not token:
        record(2, "token redeems to a cookie", False, "no token from check 1")
        return None
    r = request(GATE, "GET", f"/?token={urllib.parse.quote(token)}",
                {"Host": AUTHORITY, "Accept": "text/html"})
    cookie = r["headers"].get("set-cookie", "")
    ok = r["status"] in (302, 303) and "dsh-auth-" in cookie
    record(2, "token redeems to a cookie",
           ok, f"{r['status']}, cookie={'yes' if 'dsh-auth-' in cookie else 'NO'}"
               f"{', HttpOnly' if 'HttpOnly' in cookie else ''}"
               f"{', SameSite=' + cookie.split('SameSite=')[1].split(';')[0] if 'SameSite=' in cookie else ''}")
    return cookie.split(";")[0] if cookie else None


def check_document(cookie):
    if not cookie:
        record(3, "document loads with the cookie", False, "no cookie from check 2")
        return
    r = request(GATE, "GET", "/", {"Host": AUTHORITY, "Cookie": cookie,
                                   "Accept": "text/html"})
    text = r["body"].decode("utf-8", "replace")
    ok = r["status"] == 200 and ("harness" in text.lower() or "<div id=" in text)
    record(3, "document loads with the cookie", ok,
           f"{r['status']}, {len(r['body'])} bytes"
           + (f", title={text.split('<title>')[1].split('</title>')[0]!r}"
              if "<title>" in text else ""))


def check_websocket(cookie):
    """A raw upgrade handshake. The page loading proves nothing about this."""
    if not cookie:
        record(4, "websocket upgrades", False, "no cookie from check 2")
        return
    raw = (
        f"GET /api/remote.mux HTTP/1.1\r\n"
        f"Host: {AUTHORITY}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"Origin: https://{AUTHORITY}\r\n"
        f"Cookie: {cookie}\r\n\r\n"
    ).encode()
    try:
        s = socket.create_connection(GATE, timeout=20)
        s.sendall(raw)
        s.settimeout(10)
        head = s.recv(400).decode("latin-1").split("\r\n")[0]
        s.close()
        ok = "101" in head
        record(4, "websocket upgrades", ok, head or "(connection closed, no response)")
    except Exception as e:  # noqa: BLE001 - a probe reports, it does not raise
        record(4, "websocket upgrades", False, f"{type(e).__name__}: {e}")


def check_fence():
    """The gate relays to the engine; the engine must still refuse a foreign Host."""
    try:
        r = request(GATE, "GET", "/", {"Host": "evil.example.com"})
        ok = r["status"] != 200
        record(5, "engine still fences a foreign Host", ok,
               f"{r['status']} (a 200 here means the gate punched through the fence)")
    except Exception as e:  # noqa: BLE001
        record(5, "engine still fences a foreign Host", True,
               f"connection refused/dropped ({type(e).__name__}) - also acceptable")


def check_outside_in():
    """The only check the phone would actually notice: real HTTPS, real certificate."""
    url = f"https://{AUTHORITY}/"
    try:
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(AUTHORITY, 443, timeout=25, context=ctx)
        conn.request("GET", "/", headers={"User-Agent": "probe-phone/1"})
        r = conn.getresponse()
        status = r.status
        loc = r.getheader("Location") or ""
        cookie = r.getheader("Set-Cookie") or ""
        body = r.read(4000).decode("utf-8", "replace")
        conn.close()
        if status in (301, 302, 303, 307) and "token=" in loc:
            # cold over the wire: follow it, as a phone would
            q = urllib.parse.urlparse(loc).query or urllib.parse.urlparse(url + loc).query
            conn = http.client.HTTPSConnection(AUTHORITY, 443, timeout=25, context=ctx)
            conn.request("GET", "/" + ("?" + q if q else ""),
                         headers={"User-Agent": "probe-phone/1"})
            r2 = conn.getresponse()
            cookie = r2.getheader("Set-Cookie") or cookie
            loc = r2.getheader("Location") or ""
            r2.read(1000)
            conn.close()
        conn = http.client.HTTPSConnection(AUTHORITY, 443, timeout=25, context=ctx)
        conn.request("GET", "/", headers={"User-Agent": "probe-phone/1",
                                          "Cookie": cookie.split(";")[0]})
        r3 = conn.getresponse()
        status, body = r3.status, r3.read(4000).decode("utf-8", "replace")
        conn.close()
        ok = status == 200 and "harness" in body.lower()
        record(6, "real HTTPS through Tailscale Serve", ok,
               f"final {status}, {len(body)} bytes"
               + (f", title={body.split('<title>')[1].split('</title>')[0]!r}"
                  if "<title>" in body else ""))
    except Exception as e:  # noqa: BLE001
        record(6, "real HTTPS through Tailscale Serve", False,
               f"{type(e).__name__}: {e} (Serve or the tailnet is down)")


def check_redirector():
    """The public link a human may still have in their hand."""
    try:
        r = request(REDIRECT, "GET", "/phone", {"Host": "ai.abletelsolutions.com"})
        loc = r["headers"].get("location", "")
        ok = r["status"] in (301, 302, 303, 307) and "token=" in loc
        record("6b", "public /phone redirects into the tailnet", ok,
               f"{r['status']} -> {loc.split('?')[0] or '(no Location)'}"
               + (" +token" if "token=" in loc else " NO TOKEN"))
    except Exception as e:  # noqa: BLE001
        record("6b", "public /phone redirects into the tailnet", False,
               f"{type(e).__name__}: {e}")


def main():
    print(f"probing the phone stack for {AUTHORITY}")
    token, how = live_token()
    print(f"  token source: {how}")
    if not token:
        print("  no live token; checks 2-4 cannot run")
    try:
        cold_token = check_cold_visitor()
    except Exception as e:  # noqa: BLE001
        record(1, "cold visitor gets a link", False, f"{type(e).__name__}: {e}")
        cold_token = None
    # the cold path is the real test; the engine's own one-time token is the fallback,
    # so checks 3-4 still run (and still mean something) when check 1 fails.
    cookie = check_redeem(cold_token or token)
    check_document(cookie)
    check_websocket(cookie)
    check_fence()
    check_outside_in()
    check_redirector()

    bad = [r for r in results if not r[2]]
    print(f"\n  {len(results) - len(bad)}/{len(results)} passed")
    if bad:
        print("  failed: " + ", ".join(str(r[0]) for r in bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
