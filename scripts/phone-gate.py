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


def header_value(head: bytes, name: bytes) -> str:
    for line in head.split(b"\r\n")[1:]:
        if line.lower().startswith(name + b":"):
            return line.split(b":", 1)[1].strip().decode("latin-1")
    return ""


def auth_cookie_name(host: str) -> str:
    """The cookie the engine will look for: dsh-auth-<base64url(sha256(authority))>.

    Verified against a live browser cookie on 2026-09-11 (base64url, no padding, port
    stripped from the Host). Naming it lets this gate delete a stale one, which is the
    only way out for a client whose bad cookie shadows the good one it is being given.
    """
    authority = host.split(":")[0].strip().lower()
    if not authority:
        return ""
    digest = base64.urlsafe_b64encode(hashlib.sha256(authority.encode()).digest()).decode().rstrip("=")
    return "dsh-auth-" + digest


def send_login(client: socket.socket, token: str, cookie_to_clear: str = "") -> None:
    """302 to a freshly minted link, and clear any cookie that might shadow it.

    `gate=1` marks the link as already-repaired, so a client that comes back still
    carrying a broken cookie is shown the engine's answer instead of being redirected
    again — the second request is never redirected, which is what bounds this to one
    self-heal per navigation. Measured: without both of these, a client that pins a
    stale cookie loops until its redirect limit (50 hops for curl -L, forever for a
    browser that keeps refollowing).
    """
    lines = [
        b"HTTP/1.1 302 Found",
        b"Location: /?token=" + token.encode() + b"&gate=1",
        b"Cache-Control: no-store",
        b"Content-Length: 0",
        b"Connection: close",
    ]
    if cookie_to_clear:
        lines.insert(3, f"Set-Cookie: {cookie_to_clear}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict".encode())
    client.sendall(b"\r\n".join(lines) + b"\r\n\r\n")
    client.close()


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

    So: presence is not validity, and one inspection per connection is not one
    inspection per request.
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
        repaired = dict(parse_qsl(query)).get("gate", "") == "1"
        token = live_token(engine_port) if document_request else ""
        # Clear the cookie when handing out a link: if this client's bad cookie
        # shadows the good one it is about to receive, deleting it is the only exit.
        clear = auth_cookie_name(header_value(head, b"host")) if document_request else ""
        note(f"{method} {path}{'?' + query[:24] if query else ''} "
             f"cookie={has_cookie} token_offered={bool(offered)} token_live={bool(token)} "
             f"repaired={repaired} proto={request_line.split(' ')[-1]}")

        if document_request and token:
            if offered:
                if offered != token:
                    note("  -> 302: offered token is not the engine's current one")
                    send_login(client, token, clear)
                    return
            elif not has_cookie:
                note("  -> 302: no cookie, no token")
                send_login(client, token, clear)
                return

        client.settimeout(None)
        upstream = socket.create_connection(("127.0.0.1", engine_port), timeout=10)
        upstream.sendall(force_close(first))

        if document_request and not offered and has_cookie:
            # The visitor brought only a cookie, and a cookie can be stale. Ask the
            # engine, and self-heal a refusal instead of passing the dead end through.
            upstream_head = read_response_head(upstream)
            status = status_of(upstream_head)
            note(f"  peeked upstream: {status}")
            if status == 401 and token and not repaired:
                note("  -> 302: cookie was refused, minting a live link and clearing it")
                try:
                    upstream.close()
                except OSError:
                    pass
                send_login(client, token, clear)
                return
            if status == 401 and repaired:
                note("  -> relaying the 401: already repaired once, not looping")
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
