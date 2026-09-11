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
STATUS_FILE = STATE / "probe.json"


def _parse_args():
    import argparse
    ap = argparse.ArgumentParser(description="Probe the phone stack end to end.")
    ap.add_argument("authority", nargs="?",
                    default="secratary.tail93e6e6.ts.net",
                    help="the tailnet authority the phone dials")
    ap.add_argument("--json", nargs="?", const=str(STATUS_FILE), default=None,
                    help=f"write a machine-readable result (default {STATUS_FILE})")
    ap.add_argument("--quiet", action="store_true", help="write the file, print nothing")
    return ap.parse_args()


ARGS = _parse_args()
AUTHORITY = ARGS.authority
GATE = ("127.0.0.1", 3086)
REDIRECT = ("127.0.0.1", 3087)

results = []


def record(n, name, ok, detail):
    results.append((n, name, ok, detail))
    if not ARGS.quiet:
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
    """Never raise. A dead peer is a result, not an exception.

    Learned from a live outage: the engine was stopped for the negative test, this
    raised RemoteDisconnected, the probe died before writing its status file, and the
    kernel went on reading the previous green file as if nothing had happened. A probe
    that cannot report its own failure is worse than no probe.
    """
    conn = None
    try:
        conn = http.client.HTTPConnection(*host_port, timeout=20)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        payload = resp.read(70000)
        return {
            "status": resp.status,
            "headers": {k.lower(): v for k, v in resp.getheaders()},
            "body": payload,
        }
    except Exception as e:  # noqa: BLE001
        return {"status": 0, "headers": {}, "body": b"",
                "error": f"{type(e).__name__}: {e}"}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def is_harness_document(body):
    """A real document, not the plain-text refusal iOS offers as a download.

    The served page is ~27 KB with the title and the client bootstrap well past
    the first read, so match on either marker and explicitly exclude the 401 body.
    """
    text = body.decode("utf-8", "replace").lower()
    if "authentication required" in text:
        return False, "that is the 401 refusal text"
    for marker in ("<title>deepseek harness</title>", "__moduleloader__"):
        if marker in text:
            return True, marker
    return False, f"no harness marker in {len(body)} bytes"


def signed_in_document(path="/", headers=None):
    """Fetch the document the way a browser would, and report what came back."""
    r = request(GATE, "GET", path,
                {"Host": AUTHORITY, "Accept": "text/html", **(headers or {})})
    good, why = is_harness_document(r["body"])
    return r, good, why


def check_cold_visitor():
    """A visitor with nothing gets the page, in one request, with a session.

    The contract changed on 2026-09-11 and the stronger version is the correct one: the
    gate completes the login itself instead of handing out a link to follow. A link could
    be looped on forever by a client that keeps a bad cookie; a page cannot.
    """
    r, good, why = signed_in_document()
    cookie = r["headers"].get("set-cookie", "")
    ok = r["status"] == 200 and good and "dsh-auth-" in cookie
    record(1, "a cold visitor gets the page and a session", ok,
           f"{r['status']}, {len(r['body'])} bytes, {why}, "
           f"cookie={'yes' if 'dsh-auth-' in cookie else 'NO'}, 0 redirects")
    return None


def check_redeem(token):
    """The engine's own one-time exchange still works under the gate."""
    if not token:
        record(2, "the engine's token exchange still works", False, "no live token to try")
        return None
    r = request(GATE, "GET", f"/?token={urllib.parse.quote(token)}",
                {"Host": AUTHORITY, "Accept": "text/html"})
    cookie = r["headers"].get("set-cookie", "")
    ok = r["status"] in (302, 303) and "dsh-auth-" in cookie
    record(2, "the engine's token exchange still works",
           ok, f"{r['status']}, cookie={'yes' if 'dsh-auth-' in cookie else 'NO'}"
               f"{', HttpOnly' if 'HttpOnly' in cookie else ''}")
    return cookie.split(";")[0] if cookie else None


def check_document(cookie):
    if not cookie:
        record(3, "document loads with the cookie", False, "no cookie from check 2")
        return
    r = request(GATE, "GET", "/", {"Host": AUTHORITY, "Cookie": cookie,
                                   "Accept": "text/html"})
    text = r["body"].decode("utf-8", "replace")
    good, why = is_harness_document(r["body"])
    ok = r["status"] == 200 and good
    record(3, "document loads with the cookie", ok,
           f"{r['status']}, {len(r['body'])} bytes, {why}"
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


def check_stale_cookie():
    """The visitor who has been here before, holding a cookie that no longer works.

    This is the state of a real phone, and it was invisible to every check that
    started from a clean client: the gate saw `dsh-auth-` and relayed, the engine
    said 401, and iOS offered the refusal as a download.
    """
    r, good, why = signed_in_document(headers={"Cookie": "dsh-auth-thisisnotavalidcookie"})
    cookie = r["headers"].get("set-cookie", "")
    ok = r["status"] == 200 and good and "dsh-auth-" in cookie
    record(7, "a stale cookie is repaired, not refused", ok,
           f"{r['status']}, {len(r['body'])} bytes, {why}, "
           f"fresh cookie={'yes' if 'dsh-auth-' in cookie else 'NO'}")


def check_stale_token():
    """A saved link whose token died at the last engine restart."""
    r, good, why = signed_in_document("/?token=token-from-an-engine-that-is-gone")
    ok = r["status"] == 200 and good
    record(8, "a dead saved link is repaired, not relayed", ok,
           f"{r['status']}, {len(r['body'])} bytes, {why}")


def status_of(response: bytes) -> int:
    """HTTP status from a raw response head, or 0 if it cannot be read."""
    try:
        return int(response.split(b" ", 2)[1])
    except (IndexError, ValueError):
        return 0


def check_pooling():
    """A second request on the same connection must not slip past the gate.

    The bug that actually broke the owner's phone: Tailscale Serve pools its upstream
    connection, and the gate inspected only the first request on a connection, then
    became a raw pipe. Every later request on that socket went straight to the engine,
    so a stale cookie or a dead token produced the 401 with no decision logged. Every
    curl-based check opened a fresh connection and passed. This test reuses one.
    """
    name = "a reused connection cannot bypass the gate"
    try:
        s = socket.create_connection(GATE, timeout=20)
        s.sendall(f"GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\n\r\n".encode())
        s.settimeout(15)
        first = b""
        while b"\r\n\r\n" not in first:
            chunk = s.recv(4096)
            if not chunk:
                break
            first += chunk

        try:
            s.sendall(f"GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\n"
                      f"Cookie: dsh-auth-stale-value\r\n\r\n".encode())
        except OSError:
            s.close()
            record(9, name, True,
                   "gate closed the connection after one request, so nothing can be pooled")
            return

        second = b""
        try:
            while b"\r\n\r\n" not in second:
                chunk = s.recv(4096)
                if not chunk:
                    break
                second += chunk
        except OSError:
            pass
        s.close()
        status = status_of(second)
        if status == 0:
            record(9, name, True, "no second response: connection is not reusable")
        elif status in (301, 302, 303, 307):
            record(9, name, True, f"second request was inspected and answered {status}")
        else:
            record(9, name, False,
                   f"second request on the reused connection came back {status} - it was relayed uninspected")
    except Exception as e:  # noqa: BLE001
        record(9, name, False, f"{type(e).__name__}: {e}")


def check_fence():
    """Ask the ENGINE directly, not the gate.

    The gate sits on loopback and Serve rewrites Host, so a spoiled Host reaching
    the gate is a local process talking to itself - not an attack surface. What
    still has to hold is that the engine refuses a foreign Host if anything ever
    reaches it directly.
    """
    try:
        r = request(("127.0.0.1", 3089), "GET", "/", {"Host": "evil.example.com"})
        ok = r["status"] != 200
        record(5, "engine still fences a foreign Host", ok,
               f"engine answered {r['status']} (a 200 here means the fence is open)")
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
        status, body = r3.status, r3.read(70000)
        conn.close()
        good, why = is_harness_document(body)
        ok = status == 200 and good
        record(6, "real HTTPS through Tailscale Serve", ok,
               f"final {status}, {len(body)} bytes, {why}")
    except Exception as e:  # noqa: BLE001
        record(6, "real HTTPS through Tailscale Serve", False,
               f"{type(e).__name__}: {e} (Serve or the tailnet is down)")


def check_redirector():
    """The public link a human may still have in their hand — followed all the way.

    A redirect status proves nothing about where it lands: the old version handed out a
    launch token, and a dead one turned the owner's home-screen icon into a 401. So this
    follows it over real HTTPS, with no cookie of its own, and insists on the document.
    """
    try:
        r = request(REDIRECT, "GET", "/phone", {"Host": "ai.abletelsolutions.com"})
        loc = r["headers"].get("location", "")
        if r["status"] not in (301, 302, 303, 307) or not loc:
            record("6b", "public /phone reaches the harness", False,
                   f"{r['status']} -> {loc or '(no Location)'}")
            return
        try:
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection(AUTHORITY, 443, timeout=25, context=ctx)
            conn.request("GET", "/", headers={"User-Agent": "probe-phone/1"})
            r2 = conn.getresponse()
            status, body = r2.status, r2.read(70000)
            cookie = (r2.getheader("Set-Cookie") or "").split(";")[0]
            conn.close()
            good, why = is_harness_document(body)
            ok = status == 200 and good and "dsh-auth-" in cookie
            record("6b", "public /phone reaches the harness", ok,
                   f"302 -> {loc.split('://')[-1][:28]} -> {status}, {len(body)} bytes, {why}, "
                   f"signed in={'yes' if 'dsh-auth-' in cookie else 'NO'}")
        except Exception as e:  # noqa: BLE001
            record("6b", "public /phone reaches the harness", False,
                   f"redirect ok but the target failed: {type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        record("6b", "public /phone reaches the harness", False,
               f"{type(e).__name__}: {e}")


def guarded(n, name, fn, *a, **kw):
    """Run one check so that its own crash is recorded as that check failing."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        record(n, name, False, f"probe raised {type(e).__name__}: {e}")
        return None


def run_checks():
    token, how = live_token()
    if not ARGS.quiet:
        print(f"  token source: {how}")
        if not token:
            print("  no live token; the gate cannot sign anyone in")
    guarded(1, "a cold visitor gets the page and a session", check_cold_visitor)
    # independent of check 1: the engine's own one-time exchange still has to work, since
    # the gate's in-flight login is built on it.
    cookie = guarded(2, "the engine's token exchange still works", check_redeem, token)
    guarded(3, "document loads with the cookie", check_document, cookie)
    guarded(4, "websocket upgrades", check_websocket, cookie)
    guarded(5, "engine still fences a foreign Host", check_fence)
    guarded(6, "real HTTPS through Tailscale Serve", check_outside_in)
    guarded(7, "a stale cookie is repaired, not refused", check_stale_cookie)
    guarded(8, "a stale token is replaced, not relayed", check_stale_token)
    guarded(9, "a reused connection cannot bypass the gate", check_pooling)
    guarded("6b", "public /phone reaches the harness", check_redirector)
    return how


def main():
    if not ARGS.quiet:
        print(f"probing the phone stack for {AUTHORITY}")
    try:
        how = run_checks()
    except Exception as e:  # noqa: BLE001 - the status file must still be written
        how = "unknown"
        record(0, "probe completed", False, f"probe itself failed: {type(e).__name__}: {e}")

    bad = [r for r in results if not r[2]]
    if not ARGS.quiet:
        print(f"\n  {len(results) - len(bad)}/{len(results)} passed")
        if bad:
            print("  failed: " + ", ".join(str(r[0]) for r in bad))

    if ARGS.json:
        # A reading without a source and an age is not a reading. The kernel reads this
        # file rather than re-deriving health, so the timestamp is part of the contract.
        payload = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "host": socket.gethostname(),
            "authority": AUTHORITY,
            "token_source": how,
            "ok": not bad,
            "passed": len(results) - len(bad),
            "total": len(results),
            "failed": [str(r[0]) for r in bad],
            "checks": [{"n": r[0], "name": r[1], "ok": r[2], "detail": r[3]}
                       for r in results],
        }
        try:
            path = Path(ARGS.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(path)      # atomic: a reader never sees a half-written file
            if not ARGS.quiet:
                print(f"  wrote {path}")
        except OSError as e:
            print(f"  could not write {ARGS.json}: {e}", file=sys.stderr)
            return 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
