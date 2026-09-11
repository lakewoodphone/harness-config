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
import re
import select
import socket
import subprocess
import sys
import threading
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


def send_login(client: socket.socket, token: str) -> None:
    """302 to a freshly minted link. No body: the browser follows immediately."""
    client.sendall(
        b"HTTP/1.1 302 Found\r\n"
        b"Location: /?token=" + token.encode() + b"\r\n"
        b"Cache-Control: no-store\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    )
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


def handle(client: socket.socket, engine_port: int) -> None:
    """Relay, except where a visitor would hit a dead end we can remove.

    The first version of this gate only checked whether credentials were *present*:
    a `dsh-auth-` cookie or a `token=` in the query meant "authenticated, relay it".
    Both are worthless when they are stale, and stale is the normal state of a link
    saved on a phone — the engine answers 401 with "reopen the URL printed by dsh
    web", which iOS offers as a text download. Measured 2026-09-11: a stale cookie
    and a stale token each produced exactly that, while a clean client passed.
    So: presence is not validity. Compare the token to the engine's current one, and
    for a cookie-backed document request, look at what the engine actually answers.
    """
    try:
        client.settimeout(20)
        first = client.recv(BUF)
        if not first:
            client.close()
            return
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
        offered = dict(parse_qsl(query)).get("token", "")
        token = live_token(engine_port) if document_request else ""

        if document_request and token and offered != token:
            # No token, or one the engine no longer honours (saved link, replayed
            # redirect, half-refreshed bookmark). Hand back a link that works now.
            send_login(client, token)
            return

        client.settimeout(None)
        upstream = socket.create_connection(("127.0.0.1", engine_port), timeout=10)
        upstream.sendall(first)

        if document_request and not offered:
            # The visitor brought only a cookie, and a cookie can be stale. Ask the
            # engine, and self-heal a refusal instead of passing the dead end through.
            upstream_head = read_response_head(upstream)
            if status_of(upstream_head) == 401 and token:
                try:
                    upstream.close()
                except OSError:
                    pass
                send_login(client, token)
                return
            if upstream_head:
                client.sendall(upstream_head)

        upstream.settimeout(None)
        relay(client, upstream)
    except OSError:
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
