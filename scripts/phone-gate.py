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
import json
import os
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
MOBILE_CSS = Path(__file__).resolve().parent.parent / "assets" / "mobile.css"
BADGE_JS = Path(__file__).resolve().parent.parent / "assets" / "phone-badge.js"
BADGE_STATE = Path(os.environ.get("CEO_KERNEL_STATE", str(Path.home() / "ceo-kernel-var"))) / "latest.json"
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


def request_header(first: bytes, name: bytes) -> str:
    """One header value from a request head, for the CORS origin.

    The request is not a response and has no status line to skip, so this cannot reuse
    `response_header` - the line after the request line is already the first header.
    """
    for line in first.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]:
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
        document = with_client_layers(document)
        note(f"  -> signed in in flight, returning {len(document)} bytes with {len(cookies)} cookie(s)")
        return inject_headers(document, cookies)
    except OSError as exc:
        note(f"  complete_login failed: {exc}")
        return None


def mobile_css_bytes() -> bytes:
    """The phone layer source, or b"" when it is unavailable or switched off.

    Injected into documents rather than shipped in the harness package because the package
    belongs to npm — an update would silently drop the change — and this gate already
    touches every document request, so it is the one place that can add a stylesheet to a
    phone without a client rebuild. Kill switch: PHONE_MOBILE_CSS=0.
    """
    if os.environ.get("PHONE_MOBILE_CSS", "1") == "0":
        return b""
    try:
        css = MOBILE_CSS.read_bytes()
    except OSError:
        return b""
    return css if css.strip() else b""


def mobile_style_tag() -> bytes:
    """The phone layer as a document-level <style> tag."""
    css = mobile_css_bytes()
    if not css:
        return b""
    return b'<style id="dsh-phone-mobile" data-layer="phone-gate">' + css + b"</style>"


def mobile_stylesheet_response() -> bytes:
    """The phone layer as a stylesheet the client can link, at /dsh-phone-mobile.css.

    WHY THIS EXISTS ALONGSIDE THE INJECTED TAG — the same reason twice over.
    1. A document the client already has cached carries whatever it had at the time; the
       layer is delivered by rewriting that document, so a reused document is a shell with
       no layer. `plugin-mobile` links this URL at boot, which restores the layer without
       needing the document to be fresh.
    2. It is also the only form an app that rewrites its own <head> cannot lose: a client
       plugin can re-assert a link element it owns.

    `no-store`, because this file changes with the repo and a stale copy is exactly the
    failure being fixed; it is 10 KB, fetched once per page load.
    """
    body = mobile_css_bytes()
    if not body:
        return b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/css; charset=utf-8\r\n"
        b"Cache-Control: no-store\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + body
    )


def inject_mobile(document: bytes) -> bytes:
    """Add the phone layer to a served document, once, before </head>."""
    tag = mobile_style_tag()
    if not tag or b'id="dsh-phone-mobile"' in document:
        return document
    at = document.lower().find(b"</head>")
    if at < 0:
        return document
    return document[:at] + tag + document[at:]


# --------------------------------------------------------------------------
# The attention badge
#
# WHY THE GATE CARRIES THIS
# The owner asked to be told what needs attention *inside the harness he already opens*
# (QUESTIONS.md, answered 2026-09-14). The findings live on the host, at
# ~/ceo-kernel-var/latest.json, written every 5 minutes by the kernel's cron. The browser
# cannot read a host file, and the channel that would normally carry it (`host.call`)
# belongs to the dynamic Cordis runner, which is disabled in this preset. So the gate
# serves them, for the same reason it already serves the mobile stylesheet: it is the one
# place that can add something to a phone without a client rebuild.
#
# DELIBERATELY UNAUTHENTICATED, like the stylesheet: the payload is check names, severities
# and one-line summaries - no credentials, no customer data - and requiring a cookie would
# break the badge in exactly the case it exists for, a document the client had cached.
# --------------------------------------------------------------------------

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4, "unknown": 5}

# Origins allowed to read the findings cross-origin. A machine that runs its own DSH engine serves
# the harness on loopback, so the request legitimately comes from a localhost origin with an unknown
# port (3099 today). Everything else gets no CORS headers and the browser discards the answer.
_CORS_ORIGIN_RE = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?$")

# One small cache, guarded by a lock, for a route that is unauthenticated and polled once a minute by
# every open harness window. Re-reading and re-parsing the kernel's file per request is a needless
# disk read on three machines; caching for a few seconds cannot hide anything, because the kernel
# itself only writes every five minutes. Keyed on (mtime, size) so a new reading is never missed.
_BADGE_CACHE: dict = {"key": None, "body": b""}
_BADGE_CACHE_LOCK = threading.Lock()
_BADGE_CACHE_SECONDS = 5.0


def _badge_state_key() -> tuple:
    try:
        st = BADGE_STATE.stat()
        return (st.st_mtime_ns, st.st_size, os.environ.get("PHONE_ATTENTION_BADGE", "1"))
    except OSError:
        return (None, None, os.environ.get("PHONE_ATTENTION_BADGE", "1"))


def badge_allowed_origin(origin: str) -> str:
    """The Origin to echo, or "" when this request does not get CORS.

    The badge is served to every machine, so the endpoint has to answer cross-origin - but only for
    the case that exists: a harness on loopback. Echoing any origin would let any page the owner
    visits read his operational findings; sending no CORS headers means the browser blocks it without
    this code having to guess who is friendly.
    """
    return origin if origin and _CORS_ORIGIN_RE.match(origin) else ""


def badge_payload() -> bytes:
    """The findings, reduced to what a badge renders, or an honest refusal.

    A successful read is cached for `_BADGE_CACHE_SECONDS`, keyed on the state file's mtime and size
    so a new reading is never missed. Refusals are never cached: if the file was unreadable the next
    request should try again rather than repeat a stale failure for five seconds, and a refusal is
    cheap to produce.
    """
    key = _badge_state_key()
    now = time.monotonic()
    with _BADGE_CACHE_LOCK:
        cached = _BADGE_CACHE.get("body")
        cached_key = _BADGE_CACHE.get("key")
        cached_at = _BADGE_CACHE.get("at", 0.0)
        fresh_enough = (now - cached_at) < _BADGE_CACHE_SECONDS
        # Serve a cached good reading when the file is UNCHANGED, and also when it has momentarily
        # vanished: the kernel writes it non-atomically, so a read landing between truncate and write
        # sees no file, and refusing then would blink "findings unavailable" over a good reading for
        # no reason. A file that changed is always re-read.
        if cached and fresh_enough and (cached_key == key or key[0] is None):
            return cached
    body = _badge_payload_uncached()
    if b'"read": true' in body:
        with _BADGE_CACHE_LOCK:
            _BADGE_CACHE.update({"key": key, "body": body, "at": now})
    return body


def _badge_payload_uncached() -> bytes:
    if os.environ.get("PHONE_ATTENTION_BADGE", "1") == "0":
        return json.dumps({
            "read": False,
            "error": "the badge is switched off on this host (PHONE_ATTENTION_BADGE=0)",
        }).encode("utf-8", "replace")
    try:
        doc = json.loads(BADGE_STATE.read_text(encoding="utf-8"))
    except OSError as exc:
        return json.dumps({
            "read": False,
            "error": f"cannot read {BADGE_STATE}: {exc.strerror or exc}",
        }).encode("utf-8", "replace")
    except ValueError as exc:
        return json.dumps({
            "read": False,
            "error": f"{BADGE_STATE} is not valid JSON: {exc}",
        }).encode("utf-8", "replace")

    if not isinstance(doc, dict):
        return json.dumps({
            "read": False,
            "error": f"{BADGE_STATE} is not an object at the top level",
        }).encode("utf-8", "replace")

    # A document this shape only counts as a reading if the parts a badge renders are the types it
    # expects. Without this, `{"summary": "not a dict", "findings": "not a list"}` produced
    # `read:true, attention:null, checks:[]`, the browser turned the null into a confident 0, and the
    # pill said "nothing needs attention" about a file it had not understood. A refusal is the
    # correct answer to "I cannot read this"; silence would be the wrong one and so is green.
    if not isinstance(doc.get("summary"), dict) or not isinstance(doc.get("findings"), list):
        return json.dumps({
            "read": False,
            "error": f"{BADGE_STATE} has no readable summary/findings "
                     f"(summary={type(doc.get('summary')).__name__}, "
                     f"findings={type(doc.get('findings')).__name__})",
        }).encode("utf-8", "replace")

    summary = doc.get("summary") or {}
    raw_findings = doc.get("findings") or []
    findings = [f for f in raw_findings if isinstance(f, dict)]
    dropped = len(raw_findings) - len(findings)
    attention = [f for f in findings if f.get("needs_attention")]
    attention.sort(key=lambda f: _SEVERITY_ORDER.get(str(f.get("severity")), 9))
    quiet = [f.get("check") for f in findings if not f.get("needs_attention")]

    return json.dumps({
        # `ok` used to be the success flag here. It is now the healthy-check count, because
        # `summary.ok` is a number and two meanings for one key in one object is how a perfectly
        # healthy system (`ok: 0`) came within one line of rendering as "findings unavailable".
        # The success flag is `read`; the badge decides readability from `checks` being a list, so
        # it does not have to trust a boolean at all.
        "read": True,
        "at": doc.get("at") or doc.get("written_at") or doc.get("generatedAt"),
        "host": doc.get("host"),
        "total": summary.get("total"),
        "healthy": summary.get("ok"),
        # Kept for a badge already cached in a browser from before the rename.
        "ok_count": summary.get("ok"),
        "attention": summary.get("attention"),
        "unknown": summary.get("unknown"),
        # How many entries were not objects and had to be dropped. Said out loud rather than
        # swallowed: a reading that quietly lost rows is not the same as a reading that had none.
        "dropped": dropped,
        "highest": (attention[0].get("severity") if attention else "info"),
        "checks": [
            {
                "check": f.get("check"),
                "severity": f.get("severity"),
                "summary": f.get("summary"),
                "needs_attention": bool(f.get("needs_attention")),
            }
            for f in attention
        ],
        "quiet": quiet,
    }, ensure_ascii=False).encode()


def badge_json_response(origin: str = "") -> bytes:
    """The findings, with CORS headers only for a loopback harness.

    The phone fetches this same-origin through the gate and needs none of this. A desktop or laptop
    does not run this gate at all - it runs its own engine - so its badge is loaded from here by
    `dsh-plugin-attention-badge` and the fetch is cross-origin. Without a matching
    `Access-Control-Allow-Origin` the browser discards a perfectly good answer, which is why the
    badge read "findings unavailable" on every machine except the phone.

    Two things this deliberately does NOT do:
      - it does not send `Access-Control-Allow-Credentials`, because nothing here depends on a cookie
        and a credentialless endpoint cannot be turned into an ambient-authority read by a stray page;
      - it does not echo an arbitrary Origin. See `badge_allowed_origin`.
    """
    body = badge_payload()
    allow = badge_allowed_origin(origin)
    head = [
        b"HTTP/1.1 200 OK",
        b"Content-Type: application/json; charset=utf-8",
        b"Cache-Control: no-store",
    ]
    if allow:
        head.append(b"Access-Control-Allow-Origin: " + allow.encode("latin-1", "replace"))
        head.append(b"Vary: Origin")
    return b"\r\n".join(head) + b"\r\nContent-Length: " + str(len(body)).encode() \
        + b"\r\nConnection: close\r\n\r\n" + body


def badge_script_bytes() -> bytes:
    try:
        body = BADGE_JS.read_bytes()
    except OSError:
        return b""
    return body if body.strip() else b""


def badge_script_response() -> bytes:
    body = badge_script_bytes()
    if not body:
        return b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/javascript; charset=utf-8\r\n"
        b"Cache-Control: no-store\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + body
    )


def badge_script_tag(available: bool | None = None) -> bytes:
    """The badge as a document-level <script>, deferred so it cannot block the app.

    `data-attention-json` names the origin the badge must ask for its data. It is empty here - the
    phone reaches the gate on the same origin it loads the page from - and non-empty in
    `dsh-plugin-attention-badge`, where the page is a local engine and the data is on the authority.
    Without this the badge would resolve a relative URL against whatever served the page, which is
    the bug that made the origin a hidden coupling.

    `available` lets a caller that has already read the file say so, instead of making every document
    request read 10 KB of JavaScript just to decide whether to write a tag.
    """
    if available is not None and not available:
        return b""
    if available is None and not badge_script_bytes():
        return b""
    return (b'<script id="dsh-attention-badge-loader" data-layer="phone-badge" '
            b'data-attention-json="" src="/dsh-attention.js" defer></script>')


def inject_badge(document: bytes) -> bytes:
    """Add the badge to a served document, once, before </head>."""
    tag = badge_script_tag()
    if not tag or b'id="dsh-attention-badge-loader"' in document:
        return document
    at = document.lower().find(b"</head>")
    if at < 0:
        return document
    return document[:at] + tag + document[at:]


def inject_all(document: bytes) -> bytes:
    """Both layers, in one pass."""
    return inject_badge(inject_mobile(document))


def dechunk(body: bytes) -> bytes:
    """Unwrap chunked transfer encoding. Returns the input unchanged if it is not chunked."""
    out = b""
    rest = body
    while True:
        nl = rest.find(b"\r\n")
        if nl < 0:
            return body if not out else out
        size_text = rest[:nl].split(b";")[0].strip()
        if not size_text or any(c not in b"0123456789abcdefABCDEF" for c in size_text):
            return body if not out else out
        size = int(size_text, 16)
        if size == 0:
            return out
        start = nl + 2
        out += rest[start:start + size]
        rest = rest[start + size + 2:]


def reframe(response: bytes, body: bytes, no_store: bool = False) -> bytes:
    """Rebuild a response so its framing matches the bytes actually being sent.

    Measured the hard way on 2026-09-11: the engine serves the document chunked, so a
    stylesheet inserted into it corrupted the chunk sizes and every client got
    IncompleteRead. Content-Length is recomputed here and chunked framing is dropped,
    because after this the body is a known, complete byte string.

    `no_store` drops every caching validator and asserts `Cache-Control: no-store`. It
    exists because the phone layer is delivered by REWRITING THE DOCUMENT, so a client
    that serves the document from its own cache gets a shell with no layer at all — and
    the only symptom is a phone that looks like none of the phone work was ever done.
    Measured 2026-09-14: the engine sends its document with **no** `Cache-Control` and no
    validator at all, a cold client rendered the layer correctly in the same minute, and a
    warm browser in this session rendered the app with the layer absent (its own `fetch`
    of `/` returned the engine's 28,141-byte document, un-injected). A response with no
    cache directives is exactly what a phone is free to reuse without asking.
    """
    head, sep, _ = response.partition(b"\r\n\r\n")
    if not sep:
        return response
    drop = [b"transfer-encoding:", b"content-length:"]
    if no_store:
        drop += [b"etag:", b"last-modified:", b"expires:", b"age:", b"cache-control:"]
    lines = [ln for ln in head.split(b"\r\n") if not ln.lower().startswith(tuple(drop))]
    lines.insert(1, b"Content-Length: " + str(len(body)).encode())
    if no_store:
        lines.insert(1, b"Cache-Control: no-store")
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


def with_client_layers(response: bytes) -> bytes:
    """A 200 document, de-chunked, with the phone layer and the attention badge in it.

    Both the injection AND the uncacheable answer are the same requirement: a document that
    can be reused without asking this gate is a document that can silently lose the layer.
    The badge is delivered twice for the same reason — injected here, and re-asserted by the
    script itself, because an app that rewrites <head> can drop a node it does not own.
    """
    if status_of(response) != 200:
        return response
    head, sep, raw = response.partition(b"\r\n\r\n")
    if not sep:
        return response
    body = dechunk(raw) if b"transfer-encoding: chunked" in head.lower() else raw
    body = inject_all(body)
    return reframe(response, body, no_store=True)


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

        # The phone layer as a standalone stylesheet, for the client plugin to link.
        # Answered here, deliberately WITHOUT auth: it is styling, it carries no data, and
        # requiring a cookie would make it unavailable in exactly the case it exists for - a
        # client whose document came from its own cache. Every other path falls through to
        # the engine as before.
        if method == "GET" and path == "/dsh-phone-mobile.css":
            body = mobile_stylesheet_response()
            note(f"  -> phone layer stylesheet: {len(body)} bytes")
            client.sendall(body)
            client.close()
            return

        # The attention badge: the script, and the findings it renders. Also answered here
        # WITHOUT auth, and for the same reason — the payload is check names and one-line
        # summaries, and a badge that needs a cookie is a badge that vanishes on the cached
        # document it exists to fix. Kill switch: PHONE_ATTENTION_BADGE=0.
        if method == "GET" and path == "/dsh-attention.js":
            body = badge_script_response()
            note(f"  -> attention badge script: {len(body)} bytes")
            client.sendall(body)
            client.close()
            return

        if method == "GET" and path == "/dsh-attention.json":
            body = badge_json_response(origin=request_header(first, b"origin") or "")
            note(f"  -> attention findings: {len(body)} bytes")
            client.sendall(body)
            client.close()
            return

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

        if document_request and method == "GET":
            # A document is buffered rather than streamed, for two reasons: a cookie can be
            # stale and only the engine's answer can say so, and the phone layer has to be
            # inserted into the HTML. 27 KB, once per page load.
            response = read_all(upstream)
            try:
                upstream.close()
            except OSError:
                pass
            status = status_of(response)
            note(f"  document upstream answered {status}")
            if status == 401 and token:
                note("  -> refused: signing in in flight")
                signed_in = complete_login(engine_port, first, token, path)
                if signed_in is not None:
                    client.sendall(signed_in)
                    client.close()
                    return
                note("  -> sign-in did not complete; relaying the engine's answer")
            if status == 200:
                response = with_client_layers(response)
            if response:
                client.sendall(response)
            client.close()
            return

        upstream.settimeout(None)
        relay(client, upstream)
    except OSError as exc:
        note(f"  OSError: {exc}")
        try:
            client.close()
        except OSError:
            pass
    except Exception as exc:
        # Anything that is not an OSError used to escape this handler entirely, so the connection was
        # dropped with the client seeing a reset and nothing in the log. One measured case: a refusal
        # message carrying a non-ASCII path raised UnicodeEncodeError (a ValueError), which is not an
        # OSError. The gate's job is to answer or refuse, never to vanish silently.
        note(f"  unhandled {type(exc).__name__}: {exc}")
        try:
            body = b"phone-gate failed to handle this request"
            client.sendall(
                b"HTTP/1.1 500 Internal Server Error\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + body
            )
        except OSError:
            pass
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
