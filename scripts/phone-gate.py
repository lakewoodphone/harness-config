#!/usr/bin/env python3
"""phone-gate.py — any URL that reaches the harness signs you in, first time, by itself.

The problem this solves, measured 2026-09-11: the harness authenticates with a one-time `?token=` on `GET /`
only. A first-time visitor who reaches the root *without* that token — a typed address, a browser
autocomplete, an old bookmark — gets a **plain-text 401** (`dsh web authentication required; reopen the URL
printed by dsh web`). iOS then offers that text as a download, so the owner saw "a document it wants me to
download". A dead end, caused by which URL he happened to use.

So this sits between Tailscale Serve and the engine and peeks at the first request:

  * a browser asking for the document (`/`) with no harness cookie and no token  ->  302 to `/?token=<live>`
  * everything else (the token exchange, assets, the REST API, the WebSocket)     ->  relayed byte-for-byte

It is a raw TCP relay, not an HTTP proxy, and that is the point: WebSocket upgrade (`/api/remote.mux`,
which carries every streamed reply) passes through untouched because the bytes are never parsed. Only the
first request line and headers are inspected; after that the connection is a pipe.

The token is read from the engine's log at request time, so it survives engine restarts.

usage: phone-gate.py [--listen-port 3086] [--engine-port 3089]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import re
import select
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

STATE_DIR = Path.home() / ".dsh-phone"
COOKIE_PREFIX = b"dsh-auth-"
BUF = 65536


def live_token(engine_port: int | None = None) -> str:
    """The token the engine is actually serving.

    Prefer the log of the engine we are wired to (`--engine-port`): picking a token by
    newest file mtime is a heuristic, and the day an older log is touched last it would
    hand a visitor a token that no engine accepts. The port is known, so use it, and
    keep the mtime sweep only as a fallback for a renamed log.
    """
    if engine_port is not None:
        exact = STATE_DIR / f"engine-{engine_port}.log"
        if exact.exists():
            try:
                found = re.findall(r"token=([A-Za-z0-9_-]+)",
                                   exact.read_text(encoding="utf-8", errors="replace"))
                if found:
                    return found[-1]
            except OSError:
                pass
    best = ""
    for log in sorted(STATE_DIR.glob("engine-*.log"), key=lambda p: p.stat().st_mtime):
        try:
            found = re.findall(r"token=([A-Za-z0-9_-]+)", log.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if found:
            best = found[-1]
    return best


def tailnet_name() -> str:
    try:
        import json
        raw = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10).stdout
        return str((json.loads(raw).get("Self") or {}).get("DNSName", "")).rstrip(".")
    except Exception:
        return ""


def relay(a: socket.socket, b: socket.socket) -> None:
    """Pipe bytes both ways until either side closes. No parsing, so upgrades survive."""
    socks = [a, b]
    try:
        while True:
            readable, _, errored = select.select(socks, [], socks, 300)
            if errored:
                break
            if not readable:
                break  # idle timeout: the harness's own keepalives are shorter than this
            for src in readable:
                dst = b if src is a else a
                try:
                    chunk = src.recv(BUF)
                except OSError:
                    return
                if not chunk:
                    return
                try:
                    dst.sendall(chunk)
                except OSError:
                    return
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


def rewrite_target(first: bytes, new_target: bytes) -> bytes:
    """Replace the request target in an already-received request. Headers untouched."""
    head, sep, rest = first.partition(b"\r\n\r\n")
    if not sep:
        return first
    lines = head.split(b"\r\n")
    parts = lines[0].split(b" ")
    if len(parts) < 3:
        return first
    lines[0] = b" ".join([parts[0], new_target, parts[2]])
    return b"\r\n".join(lines) + sep + rest


def read_all(sock: socket.socket, limit: int = 4_000_000, timeout: float = 20.0) -> bytes:
    """Everything the peer sends until it closes. Upstream is forced to close per request."""
    sock.settimeout(timeout)
    buf = b""
    while len(buf) < limit:
        try:
            chunk = sock.recv(BUF)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
    return buf


def response_header(response: bytes, name: bytes) -> str:
    for line in response.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]:
        if line.lower().startswith(name.lower() + b":"):
            return line.split(b":", 1)[1].strip().decode("latin-1")
    return ""


def set_cookies(response: bytes) -> list[bytes]:
    """Every Set-Cookie header value, verbatim, as a browser would see them."""
    out = []
    for line in response.split(b"\r\n\r\n", 1)[0].split(b"\r\n"):
        if line.lower().startswith(b"set-cookie:"):
            out.append(line.split(b":", 1)[1].strip())
    return out


def inject_headers(response: bytes, names_and_values: list[bytes]) -> bytes:
    """Add headers to a complete response without touching its body."""
    head, sep, body = response.partition(b"\r\n\r\n")
    if not sep:
        return response
    lines = head.split(b"\r\n")
    for item in reversed(names_and_values):
        lines.insert(1, b"Set-Cookie: " + item)
    return b"\r\n".join(lines) + sep + body


def complete_login(engine_port: int, first: bytes, token: str, path: str) -> bytes | None:
    """Sign the visitor in and return the document, all in one client response.

    The whole reason this function exists, measured twice on 2026-09-11: any design where
    the *client* is asked to follow a redirect to `/?token=` can be driven into a loop by
    a client that keeps a bad cookie (curl with a pinned header; a browser refusing
    cookies) - 50 hops and an abort. So the gate does the login itself:

      1. ask the engine for the document with the live token appended,
      2. keep the session cookie the engine hands back (not the client's stale one),
      3. fetch the document with that cookie,
      4. return the document to the client, with the Set-Cookie injected.

    The client gets a working page in one request, no redirect chain, no token in its URL
    or its history, and no loop is constructible. If step 1 does not produce a session,
    return None and the caller relays whatever the engine said.
    """
    try:
        up = socket.create_connection(("127.0.0.1", engine_port), timeout=10)
        up.sendall(force_close(rewrite_target(first, path.encode() + b"?token=" + token.encode())))
        exchange = read_response_head(up)
        status = status_of(exchange)
        cookies = set_cookies(exchange)
        try:
            up.close()
        except OSError:
            pass
        if status not in (301, 302, 303, 307) or not cookies:
            note(f"  login exchange answered {status} with {len(cookies)} cookie(s); relaying it")
            return None

        host = response_header(first, b"host") or tailnet_name() or "localhost"
        cookie_header = b"; ".join(c.split(b";", 1)[0] for c in cookies)
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
            f"Cookie: {cookie_header.decode('latin-1')}\r\n"
            f"User-Agent: phone-gate\r\nAccept: text/html,*/*\r\n"
            f"Connection: close\r\n\r\n"
        ).encode()
        up2 = socket.create_connection(("127.0.0.1", engine_port), timeout=10)
        up2.sendall(request)
        document = read_all(up2)
        try:
            up2.close()
        except OSError:
            pass
        if status_of(document) != 200:
            note(f"  signed-in fetch answered {status_of(document)}; relaying the exchange instead")
            return None
        note(f"  -> signed in in flight, returning {len(document)} bytes with {len(cookies)} cookie(s)")
        return inject_headers(document, cookies)
    except OSError as exc:
        note(f"  complete_login failed: {exc}")
        return None


def read_response_head(sock: socket.socket, limit: int = 65536, timeout: float = 20.0) -> bytes:
    """Read until the end of the upstream response headers (may include some body)."""
    buf = b""
    sock.settimeout(timeout)
    while b"\r\n\r\n" not in buf and len(buf) < limit:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf


def status_of(response: bytes) -> int:
    try:
        return int(response.split(b" ", 2)[1])
    except (IndexError, ValueError):
        return 0


def note(msg: str) -> None:
    """Say what this gate decided, on stdout (serve-phone.sh sends it to gate.log).

    Added after a confusing hour: curl through this gate behaved differently from a real
    browser through Tailscale Serve, and with no record of the gate's own decisions there
    was nothing to reason from but the client's symptom. Never log a token.
    """
    try:
        print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", flush=True)
    except OSError:
        pass


def read_request_head(client: socket.socket, first: bytes) -> bytes:
    """The complete request head, however many reads it takes."""
    buf = first
    client.settimeout(20)
    while b"\r\n\r\n" not in buf and len(buf) < BUF * 8:
        chunk = client.recv(BUF)
        if not chunk:
            break
        buf += chunk
    return buf


def force_close(head_bytes: bytes) -> bytes:
    """Rewrite `Connection:` to close, unless this is a websocket upgrade.

    This is the fix for the bug that actually broke the owner's phone, after two
    earlier fixes that were real but not the cause. Tailscale Serve pools its
    connection to this gate: it sends request after request down one socket. The gate
    inspected the first request and then became a raw pipe, so every later request on
    that reused socket reached the engine uninspected — a stale cookie or a dead token
    sailed straight through to the 401 that iOS offers as a text download. Every
    curl-based test opened a fresh connection and therefore passed, which is exactly
    why those tests kept lying. Forcing close means one request per connection, so
    every request is inspected; the upgrade case is left alone because the websocket
    carries every streamed reply and must survive.
    """
    if b"\r\n\r\n" not in head_bytes:
        return head_bytes
    head, sep, rest = head_bytes.partition(b"\r\n\r\n")
    if b"upgrade:" in head.lower():
        return head_bytes
    lines = head.split(b"\r\n")
    out = [lines[0]]
    replaced = False
    for line in lines[1:]:
        if line.lower().startswith(b"connection:"):
            out.append(b"Connection: close")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(b"Connection: close")
    return b"\r\n".join(out) + sep + rest


def handle(client: socket.socket, engine_port: int) -> None:
    """Relay, except where a visitor would hit a dead end we can remove.

    Two bugs lived here, both of the same family — trusting a proxy-shaped assumption
    instead of the thing itself.

    1. The first version checked whether credentials were *present*: a `dsh-auth-`
       cookie or a `token=` in the query meant "authenticated, relay it". Both are
       worthless when stale, and stale is the normal state of a link saved on a phone.
    2. It inspected only the first request on a connection. Serve pools connections,
       so later requests bypassed every check here.

    And one design correction, forced by a measurement: redirecting the visitor to
    `/?token=<live>` cannot be made safe. A client that keeps a bad cookie - curl -H,
    or a browser refusing cookies - refollows for ever: measured 50 hops and a curl
    abort. The engine accepts a live token even when a stale cookie is present, so
    instead of redirecting, the gate now adds the token to the request it forwards and
    passes the engine's own 303 through. One hop, no client-visible token in the URL or
    the browser's history, and a per-client cooldown bounds the case where even that
    cannot converge.
    """
    try:
        client.settimeout(20)
        first = client.recv(BUF)
        if not first:
            client.close()
            return
        first = read_request_head(client, first)
        head = first.split(b"\r\n\r\n", 1)[0]
        request_line = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        # Split on whitespace, not on the first space: partition(" ") on
        # "GET / HTTP/1.1" yields path="/ HTTP/1.1", which matches nothing, and the
        # gate silently relays everything. It did exactly that until 2026-09-11 - the
        # 401 the owner saw was the untouched engine, not this gate.
        parts = request_line.split()
        method = parts[0] if parts else ""
        raw_target = parts[1] if len(parts) > 1 else ""
        split_target = urlsplit(raw_target)      # tolerates absolute-form targets too
        path = split_target.path or "/"
        query = split_target.query
        document_request = method in ("GET", "HEAD") and path in ("/", "/index.html")
        has_cookie = COOKIE_PREFIX in head
        offered = dict(parse_qsl(query)).get("token", "")
        token = live_token(engine_port) if document_request else ""
        try:
            client_ip = str(client.getpeername()[0])
        except OSError:
            client_ip = "?"
        note(f"{method} {path}{'?' + query[:24] if query else ''} "
             f"cookie={has_cookie} token_offered={bool(offered)} token_live={bool(token)} "
             f"proto={request_line.split(' ')[-1]}")

        # A document request that cannot be authenticated as sent: no cookie at all, or a
        # token the engine no longer honours (a saved link, a replayed redirect, an engine
        # restart). The gate signs the visitor in itself and returns the page.
        needs_token = bool(token) and ((not offered and not has_cookie) or (bool(offered) and offered != token))
        if needs_token:
            note("  -> not authenticated as sent: signing in in flight")
            signed_in = complete_login(engine_port, first, token, path)
            if signed_in is not None:
                client.settimeout(None)
                client.sendall(signed_in)
                client.close()
                return

        client.settimeout(None)
        upstream = socket.create_connection(("127.0.0.1", engine_port), timeout=10)
        upstream.sendall(force_close(first))

        if document_request and has_cookie and not offered:
            # The visitor brought only a cookie, and a cookie can be stale. Ask the engine
            # first; a refusal becomes a real sign-in rather than a dead end he cannot
            # diagnose from a phone.
            upstream_head = read_response_head(upstream)
            status = status_of(upstream_head)
            note(f"  peeked upstream: {status}")
            if status == 401 and token:
                note("  -> cookie refused: signing in in flight")
                try:
                    upstream.close()
                except OSError:
                    pass
                signed_in = complete_login(engine_port, first, token, path)
                if signed_in is not None:
                    client.sendall(signed_in)
                    client.close()
                    return
                upstream = socket.create_connection(("127.0.0.1", engine_port), timeout=10)
                upstream.sendall(force_close(first))
                upstream_head = read_response_head(upstream)
            if upstream_head:
                client.sendall(upstream_head)

        upstream.settimeout(None)
        relay(client, upstream)
    except OSError as exc:
        note(f"  OSError: {exc}")
        try:
            client.close()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen-port", type=int, default=3086)
    ap.add_argument("--engine-port", type=int, default=3089)
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", args.listen_port))
    srv.listen(128)
    print(f"phone-gate listening on 127.0.0.1:{args.listen_port} -> engine 127.0.0.1:{args.engine_port}", flush=True)
    while True:
        try:
            client, _ = srv.accept()
        except OSError:
            continue
        threading.Thread(target=handle, args=(client, args.engine_port), daemon=True).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
