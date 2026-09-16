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
import html
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
# Where an engine's startup line — and therefore its one-time token — may be written.
# systemd owns the Linux engines, so there the log is under `~/.dsh-phone`. Windows has no
# systemd, and its launchers redirect the engine's stdout to a file instead. Measured
# 2026-09-16 on ZABZ-YOGA: the running engine's `dsh web: http://127.0.0.1:3099/?token=…`
# line was in `~/.dsh/multi-window/logs/3099.log` (82 bytes) and this gate, which looked
# only under `~/.dsh-phone`, found no token at all — so a cold visitor got the engine's
# plain-text 401 rather than a sign-in. The multi-window launcher's own log is the one
# that exists on every Windows node, so it is searched first.
ENGINE_LOG_DIRS = [Path.home() / ".dsh" / "multi-window" / "logs", STATE_DIR]
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA")
if _LOCALAPPDATA:
    # what serve-phone.ps1 used, kept so an engine started by the old path is still readable
    ENGINE_LOG_DIRS.append(Path(_LOCALAPPDATA) / "dsh-phone")
MOBILE_CSS = Path(__file__).resolve().parent.parent / "assets" / "mobile.css"
# The phone layer is these files concatenated, in this order: `mobile.css` is the base layer and
# the others are scoped additions. One URL, one injected tag and one client-plugin link, so adding
# a rule to the phone never means adding a delivery path (the composer's own fix and the question
# card's live here — see the comments in each file for what they measured).
LAYER_FILES = [
    MOBILE_CSS,
    Path(__file__).resolve().parent.parent / "assets" / "question-card.css",
]
BADGE_JS = Path(__file__).resolve().parent.parent / "assets" / "phone-badge.js"
BADGE_STATE = Path(os.environ.get("CEO_KERNEL_STATE", str(Path.home() / "ceo-kernel-var"))) / "latest.json"
COOKIE_PREFIX = b"dsh-auth-"
BUF = 65536
# Set by --log-file. `note()` writes here as well as to stdout, so a gate started with no
# inherited stdout still leaves a record of every decision it made.
LOG_PATH: "Path | None" = None
_LOG_LOCK = threading.Lock()


def token_in(path: Path) -> str:
    """The last `token=` in one file, or "" when there is none (or it cannot be read)."""
    try:
        found = re.findall(r"token=([A-Za-z0-9_-]+)", path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""
    return found[-1] if found else ""


def live_token(engine_port: int | None = None) -> str:
    """The token the engine is actually serving.

    Prefer the log of the engine we are wired to (`--engine-port`): picking a token by
    newest file mtime is a heuristic, and the day an older log is touched last it would
    hand a visitor a token that no engine accepts. The port is known, so use it, and
    keep the mtime sweep only as a fallback for a renamed log.

    The exact-port lookups come in two shapes because the launchers differ: systemd
    (Linux) writes `engine-<port>.log`, and the Windows multi-window launcher writes
    `<port>.log` plus a timestamped `<port>-<date>.log` per start. The timestamped file
    is what a restarted engine writes, and the newest of those carries the live token —
    measured 2026-09-16, `~/.dsh/multi-window/logs/3099-20260916-154910.log`.
    """
    if engine_port is not None:
        for directory in ENGINE_LOG_DIRS:
            for name in (f"engine-{engine_port}.log", f"{engine_port}.log"):
                found = token_in(directory / name)
                if found:
                    return found
            try:
                candidates = sorted(directory.glob(f"{engine_port}-*.log"),
                                    key=lambda p: p.stat().st_mtime, reverse=True)
            except OSError:
                candidates = []
            for path in candidates:
                found = token_in(path)
                if found:
                    return found
    best = ""
    for directory in ENGINE_LOG_DIRS:
        try:
            logs = sorted(directory.glob("engine-*.log"), key=lambda p: p.stat().st_mtime)
        except OSError:
            continue
        for log in logs:
            found = token_in(log)
            if found:
                best = found
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


def rewrite_authority(head_bytes: bytes, authority: str) -> bytes:
    """Present this request to the engine as if it came from `authority`.

    WHY THE GATE HAS TO DO THIS, measured 2026-09-16 on ZABZ-YOGA. `tailscale serve`
    preserves the client's Host header — proven by the reading itself: with
    `tailscale serve --bg 3099` and no `--trusted-host`, `GET /api` through
    `https://zabz-yoga-1.tail93e6e6.ts.net` returned **403**, the fence refusing a Host
    it does not trust, while `/` returned 401. So publishing a loopback engine exposes
    nothing but a 403 to every /api call: the phone loads a shell that cannot talk.

    The alternative was `--trusted-host <node FQDN>` on the engine — but that is a
    **startup** setting (dsh-web-app/lib/index.js:37, dsh-client-connection:739), so
    applying it means restarting the engine, and the engine is where the owner's live
    sessions are. One of them is this session. An engine restart is therefore not a
    cost the gate may impose; it is a cost it exists to avoid.

    Rewriting to a loopback authority instead keeps the fence CLOSED and makes the gate
    the only door: the engine trusts exactly what it already trusted (`127.0.0.1`), no
    network name is ever added to `trustedHosts`, and a request that reaches the engine
    without passing this gate is still refused.

    BOTH Host and Origin must be rewritten. The fence requires
    `new URL(origin).host === hostUrl.host` (dsh-client-connection/lib/index.js:208-211),
    so rewriting Host alone turns every browser POST into a 403 while leaving curls
    green — the exact shape of bug that made the earlier phone work look done. An
    ABSENT Origin is accepted (`origin === undefined -> true`), so a request without one
    is forwarded as-is rather than given a fabricated value.

    The cookie the engine mints is named for the authority it saw
    (`cookieName(authority)`, :280), which is why the sign-in exchange must use the same
    rewritten authority: mint for one authority and reload for another and every later
    request 401s.
    """
    if b"\r\n\r\n" not in head_bytes:
        return head_bytes
    head, sep, rest = head_bytes.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    if not lines:
        return head_bytes
    encoded = authority.encode()
    out = [lines[0]]
    saw_host = False
    for line in lines[1:]:
        low = line.lower()
        if low.startswith(b"host:"):
            out.append(b"Host: " + encoded)
            saw_host = True
        elif low.startswith(b"origin:"):
            out.append(b"Origin: http://" + encoded)
        else:
            out.append(line)
    if not saw_host:
        out.insert(1, b"Host: " + encoded)
    return b"\r\n".join(out) + sep + rest


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


def complete_login(engine_port: int, first: bytes, token: str, path: str, authority: str = "") -> bytes | None:
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

        host = authority or response_header(first, b"host") or tailnet_name() or "localhost"
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
    parts = []
    for path in LAYER_FILES:
        try:
            body = path.read_bytes()
        except OSError:
            continue
        if body.strip():
            # a marker per file, so a served layer can say which files produced it
            parts.append(b"/* " + path.name.encode() + b" */\n" + body)
    return b"\n".join(parts)


def layer_report() -> str:
    """Which files the served layer is made of, and how big each is (for /dsh-phone-layer)."""
    rows = []
    for path in LAYER_FILES:
        try:
            rows.append(f"{path.name}={len(path.read_bytes())}B")
        except OSError:
            rows.append(f"{path.name}=missing")
    return " ".join(rows)


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


_BADGE_JS_CACHE: dict = {"key": None, "body": b""}


def badge_script_bytes() -> bytes:
    """The badge source, cached on (mtime, size).

    Read once per document request otherwise, and a document request happens on every page load, on
    every machine. A few tens of KB of JavaScript re-read from disk per load is not a crisis; doing
    it twice per load to decide whether to write a tag is just waste.
    """
    try:
        st = BADGE_JS.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        _BADGE_JS_CACHE.update({"key": None, "body": b""})
        return b""
    if _BADGE_JS_CACHE.get("key") == key:
        return _BADGE_JS_CACHE["body"]
    try:
        body = BADGE_JS.read_bytes()
    except OSError:
        return b""
    body = body if body.strip() else b""
    _BADGE_JS_CACHE.update({"key": key, "body": body})
    return body


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
    """Add the badge to a served document, once, before </head>.

    The "once" test is scoped to the head, not the whole document: `inject_badge` searches the whole
    document for its own marker, so a page whose body merely *mentions* the marker would silently
    get no badge. Looking only where the tag is actually inserted removes that failure mode.
    """
    tag = badge_script_tag(available=bool(badge_script_bytes()))
    if not tag:
        return document
    at = document.lower().find(b"</head>")
    if at < 0:
        return document
    if b'id="dsh-attention-badge-loader"' in document[:at]:
        return document
    return document[:at] + tag + document[at:]


# --------------------------------------------------------------------------
# The iOS head
#
# WHY THE GATE CARRIES THIS, AND WHY IT IS NOT A CLIENT PLUGIN
# `assets/mobile.css` spends a whole section on `env(safe-area-inset-*)` (:222-328), and as served
# every one of those rules evaluates to 0 on iOS: the document the engine ships declares
# `<meta name="viewport" content="width=device-width, initial-scale=1" />` and nothing else, and
# `env(safe-area-inset-*)` is only non-zero when that meta carries `viewport-fit=cover`. Measured
# 2026-09-16 by reading the served head in full (`.../dsh-web-frontend/dist/index.html`, 25 lines):
# no `viewport-fit`, no `apple-mobile-web-app-*`, no `theme-color`, and no `apple-touch-icon`.
#
# It lives here rather than in `plugin-mobile` because it must reach a browser that has no plugin
# loaded yet (a cold Home Screen launch), and because the manifest is a separate HTTP response that
# never passes through a document at all. Same reason as the stylesheet and the badge: the gate is
# the one place that changes what a phone is given without a rebuild of the npm package.
#
# WHAT EACH TAG IS FOR
#   viewport-fit=cover  makes `env(safe-area-inset-*)` real. With the status-bar style below the
#                       gain is the BOTTOM inset — the composer clears the home indicator, which is
#                       the inset the layer's own composer rule actually needs.
#   apple-mobile-web-app-capable=yes
#                       the legacy switch; iOS before 16.4 needs it to open a Home Screen icon
#                       without Safari chrome. Harmless where the manifest is honoured.
#   apple-mobile-web-app-status-bar-style
#                       `default` ON PURPOSE, see `status_bar_style()`.
#   theme-color         the harness's own boot background tokens, so browser chrome matches the app:
#                       light `#fff`, dark `#151517`, read from
#                       `.../dsh-web-frontend/dist/assets/index-DPX2bQLO.css` (`.boot{--dsh-boot-bg:
#                       #fff}` and `body[data-ds-dark-theme] .boot{--dsh-boot-bg: #151517}`). The
#                       app's dark theme is a `data-` attribute the client sets, NOT the OS media
#                       query, so these two track the OS scheme and can disagree with the app's own
#                       theme. Cosmetic, and the alternative is no theme color at all.
#   apple-touch-icon    NOT INJECTED, DELIBERATELY. iOS does not accept an SVG for this rel, and
#                       this repo contains no PNG that is an icon: the only PNGs are UI screenshots
#                       under `docs/dsh-mobile/evidence/`, and a screenshot of the app is worse than
#                       the screenshot iOS takes for itself. The real fix is a PNG upstream in
#                       `dsh-web-frontend`, whose dist ships `favicon.svg` only. Recorded rather
#                       than faked — a tag pointing at the SVG would look like the fix and do
#                       nothing.
#
# KILL SWITCH: PHONE_HEAD=0, the same shape as PHONE_MOBILE_CSS=0 and PHONE_ATTENTION_BADGE=0. It
# turns off this whole section, the manifest rewrite included.
# --------------------------------------------------------------------------

PHONE_HEAD_MARKER = b"<!-- dsh-phone-head -->"
# A viewport meta tag, and the same shape as a lookahead so `name="viewport-x"` is not one.
_META_VIEWPORT_RE = re.compile(rb"""<meta\b[^>]*\bname\s*=\s*["']?viewport["']?(?=[\s/>])[^>]*>""", re.I)
_VIEWPORT_NAME_RE = re.compile(rb"""\bname\s*=\s*["']?viewport["']?(?=[\s/>])""", re.I)
_VIEWPORT_CONTENT_RE = re.compile(rb"""\bcontent\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
_STATUS_BAR_STYLE_RE = re.compile(r"^[a-z][a-z-]{0,30}$")


def head_enabled() -> bool:
    """PHONE_HEAD=0 switches the whole iOS-head delivery off."""
    return os.environ.get("PHONE_HEAD", "1") != "0"


def status_bar_style() -> str:
    """The `apple-mobile-web-app-status-bar-style` value, `PHONE_STATUS_BAR_STYLE` to override.

    DEFAULT `default`, NOT `black-translucent`, and that is a deliberate refusal to guess.
    `black-translucent` also hands the top band to the page and makes `env(safe-area-inset-top)`
    non-zero (which `assets/mobile.css` :286-299 is written for), but it draws the status glyphs in
    WHITE over whatever the page paints. On a light harness theme the clock and the battery become
    invisible, and nobody here can see the owner's phone to check which theme it is in. `default`
    cannot produce that defect, and it still gives the bottom inset, which is the one the composer
    needs. Flip it with `PHONE_STATUS_BAR_STYLE=black-translucent` once someone has looked at the
    phone. The value is validated because it is injected into a document verbatim.
    """
    value = os.environ.get("PHONE_STATUS_BAR_STYLE", "default").strip().lower()
    return value if _STATUS_BAR_STYLE_RE.match(value) else "default"


def _viewport_fixed(tag: bytes) -> bytes:
    """One viewport `<meta>` with `viewport-fit=cover`, keeping every directive it already carried."""
    if b"viewport-fit" in tag.replace(b" ", b"").lower():
        return tag                      # already correct: this document is not touched
    content = _VIEWPORT_CONTENT_RE.search(tag)
    default = b"width=device-width, initial-scale=1, viewport-fit=cover"
    if content is None:
        body = tag.rstrip()[:-1].rstrip()
        if body.endswith(b"/"):
            body = body[:-1].rstrip()
        return body + b' content="' + default + b'>'
    existing = (content.group(1) if content.group(1) is not None else content.group(2) or b"")
    existing = existing.strip().rstrip(b";,").strip()
    merged = (existing + b", viewport-fit=cover") if existing else default
    return tag[:content.start()] + b'content="' + merged + b'"' + tag[content.end():]


def head_metas(head: bytes) -> bytes:
    """The metas this head does not already have, behind one marker; b"" when it has them all.

    Every tag is guarded on its own name, so a document that grows one of these upstream keeps its
    own and this injects nothing for that name. The marker guards the block as a whole, so a second
    pass over a document this gate already served changes nothing.
    """
    style = status_bar_style().encode("ascii")
    wanted = [
        (b"mobile-web-app-capable", b'<meta name="mobile-web-app-capable" content="yes">'),
        (b"apple-mobile-web-app-capable", b'<meta name="apple-mobile-web-app-capable" content="yes">'),
        (b"apple-mobile-web-app-status-bar-style",
         b'<meta name="apple-mobile-web-app-status-bar-style" content="' + style + b'">'),
        (b"theme-color", b'<meta name="theme-color" content="#fff" media="(prefers-color-scheme: light)">'),
        (b"theme-color", b'<meta name="theme-color" content="#151517" media="(prefers-color-scheme: dark)">'),
    ]
    tags = [tag for (name, tag) in wanted if (b'name="' + name + b'"') not in head]
    if not tags:
        return b""
    return PHONE_HEAD_MARKER + b"".join(tags)


def inject_head(document: bytes) -> bytes:
    """The iOS head: rewrite the viewport meta in place, add the missing metas before `</head>`."""
    if not head_enabled():
        return document
    at = document.lower().find(b"</head>")
    if at < 0:
        return document
    if PHONE_HEAD_MARKER in document[:at]:
        return document
    head = _META_VIEWPORT_RE.sub(lambda m: _viewport_fixed(m.group(0)), document[:at])
    return head + head_metas(head) + document[at:]


def manifest_response(engine_port: int, engine_authority: str = "") -> bytes:
    """The PWA manifest with the display mode iOS documents, or b"" to relay the engine's own.

    `display` is rewritten from `fullscreen` to **`standalone`**, which is the value Apple documents
    for this platform: "display: standalone … iOS/iPadOS: opens as a Home Screen Web App with
    isolated cookies and storage, separate from the browser" (Apple, WWDC 2023 session 10120, "What's
    new in web apps", 5:01-5:53; read 2026-09-16). `fullscreen` is a valid manifest value whose iOS
    behaviour nobody here has observed. On iOS a Home Screen Web App is the mode that removes Safari
    chrome — which is what "installable" has to mean if it is to mean anything on the phone.

    REWRITTEN AT THE GATE, not upstream, on purpose: this response is only in the path of a tailnet
    client, so the owner's desktop windows keep `fullscreen` — which
    `docs/multi-window/research-desktop-app.md` B6 already records as an upstream bug of its own.

    `theme_color`/`background_color` are deliberately NOT added. iOS ignores both (its splash comes
    from `apple-touch-startup-image`), and the document's two `theme-color` metas already track the
    OS scheme, which a single-valued manifest field cannot. Icons are left alone: no PNG exists in
    this repo to point an iOS icon at (see the section note above).

    A manifest the gate could not read is not a manifest to invent: any failure returns b"" and the
    caller relays whatever the engine said.
    """
    if not head_enabled():
        return b""
    host = engine_authority or f"127.0.0.1:{engine_port}"
    try:
        up = socket.create_connection(("127.0.0.1", engine_port), timeout=10)
        up.sendall((f"GET /manifest.webmanifest HTTP/1.1\r\nHost: {host}\r\n"
                    f"User-Agent: phone-gate\r\nAccept: application/manifest+json,*/*\r\n"
                    f"Connection: close\r\n\r\n").encode())
        raw = read_all(up)
        try:
            up.close()
        except OSError:
            pass
    except OSError as exc:
        note(f"  manifest fetch failed: {exc}")
        return b""
    head, sep, body = raw.partition(b"\r\n\r\n")
    if not sep or status_of(raw) != 200:
        note(f"  manifest upstream answered {status_of(raw)}; relaying it")
        return b""
    if b"transfer-encoding: chunked" in head.lower():
        body = dechunk(body)
    try:
        doc = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        note(f"  manifest is not JSON ({type(exc).__name__}); relaying it")
        return b""
    if not isinstance(doc, dict):
        note("  manifest is not a JSON object; relaying it")
        return b""
    if doc.get("display") == "standalone":
        return b""                       # already what iOS documents: the response is not touched
    doc["display"] = "standalone"
    out = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/manifest+json; charset=utf-8\r\n"
        b"Cache-Control: no-store\r\n"
        b"Content-Length: " + str(len(out)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + out
    )


def inject_all(document: bytes) -> bytes:
    """All three layers, in one pass: the phone stylesheet, the iOS head, the attention badge."""
    return inject_badge(inject_head(inject_mobile(document)))


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
    """Say what this gate decided, on stdout and (if asked) in a file.

    Added after a confusing hour: curl through this gate behaved differently from a real
    browser through Tailscale Serve, and with no record of the gate's own decisions there
    was nothing to reason from but the client's symptom. Never log a token.

    `--log-file` exists so the gate can be started with NO inherited stdout at all. On
    Windows the detached launcher (`phone-gate-ensure.ps1` via VBScript) deliberately gives
    its child no handle on anyone's stdout — which is what stops a launcher from being left
    holding a pipe open — so the gate has to be able to write its own record. Measured
    2026-09-16: routing that through `cmd /c ... >> log` instead produced an empty log and a
    gate that never started, because cmd's quote handling around a quoted program plus
    redirection is not worth trusting.
    """
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    with _LOG_LOCK:
        try:
            print(line, flush=True)
        except OSError:
            pass
        if LOG_PATH is not None:
            try:
                with LOG_PATH.open("a", encoding="utf-8", errors="replace") as handle:
                    handle.write(line + "\n")
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


# --------------------------------------------------------------------------
# WHO MAY BE SIGNED IN
#
# THE HOLE THIS CLOSES, measured 2026-09-16 21:58Z by the security audit of this same program: a cold
# `GET /` through a node's tailnet name came back **200 with a working session cookie and no
# credential of any kind**, because `complete_login` performs the engine's token exchange on the
# visitor's behalf. That cookie drives `/api` and the WebSocket mux — full engine control, a shell as
# the owner; on `secratary` that is RCE as `zabz` on the company authority. The only thing bounding it
# was tailnet membership, and that tailnet's ACL is default allow-all with nothing tagged.
#
# THE CONTROL IS THE DEVICE, NOT THE IDENTITY. `tailscale serve` forwards the caller's identity:
#
#     Tailscale-User-Login: lakewoodphoneandtech@gmail.com
#     Tailscale-User-Name: Eliyahu
#     X-Forwarded-For: 100.72.162.5
#
# (captured from a loopback listener behind Serve, 2026-09-16 18:06:48 local). The LOGIN does not
# discriminate: every device on this tailnet is enrolled under the same Google identity — all six
# peers, user 2701425880688073 — including `lakewooechsmini`, the employee's Mac. So the login header
# cannot be the check; the device address can, and `X-Forwarded-For` is the header that names it.
#
# WHY THE LAST ENTRY AND NOT THE FIRST. A proxy that APPENDS to an incoming `X-Forwarded-For` lets a
# caller prepend anything it likes; the entry the proxy itself added is the LAST one. Reading the
# first would let a foreign device present itself as the owner's laptop by sending that header. Read
# through the closest trusted proxy, the last entry is the one a caller cannot forge. (Measured
# 2026-09-16: a `curl -H 'X-Forwarded-For: 8.8.8.8'` through Serve arrives as
# `8.8.8.8, 100.72.162.5` — see the `xff=` field this gate logs.)
#
# WHAT IS DELIBERATELY NOT CHANGED. A request with no `X-Forwarded-For` did not come through Serve:
# it is a loopback client on this machine, which the engine already trusts by itself. That path is
# left exactly as it was — no sign-in added, none removed. The gate's own sign-in path is untouched,
# and no credential is required that a Home Screen Web App could not supply (it has no address bar in
# which to type a `?token=`, which is the entire reason this gate exists). The Tailscale ACL is not
# touched by this program at all.
#
# FAIL-OPEN ON A MISSING OR EMPTY LIST, DELIBERATELY. A missing file, or a file with no usable lines,
# means "no restriction" and says so once, loudly, in the log. That is the behaviour as it was before
# this section existed, and it keeps a mis-edit from locking the owner out of his own node from his
# phone — where he cannot open a terminal to fix it. The restrictive direction is what happens the
# moment the file names devices and none of them is yours.
# --------------------------------------------------------------------------

ALLOW_FILE = Path(__file__).resolve().parent / "phone-gate-allow.txt"
_FORWARDED_MAX = 256
_ALLOW_CACHE: dict = {"key": None, "ips": frozenset()}
_ALLOW_NOTED: set = set()


def _log_text(value: str, limit: int = 64) -> str:
    """Header text made safe for a line-oriented log: no control characters, bounded length.

    A header is text an attacker chooses. Letting it through raw would let a caller forge log lines
    (and, since `note()` writes a line per call, could also break the file's shape).
    """
    cleaned = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(value)[:limit])
    return cleaned or "-"


def _normalise_address(value: str) -> str:
    """One device address, comparable: trimmed, lowercased, no `::ffff:` prefix, no brackets."""
    text = str(value).strip().lower()
    if text.startswith("::ffff:"):
        text = text[7:]
    if text.startswith("[") and "]" in text:
        text = text[1:text.index("]")]
    return text.strip()


def forwarded_device(first: bytes) -> str:
    """The device address Serve reports, or "" when this request did not come through Serve."""
    raw = request_header(first, b"x-forwarded-for")[:_FORWARDED_MAX]
    if not raw:
        return ""
    return _normalise_address(raw.split(",")[-1])


def allowed_devices() -> tuple[frozenset, bool]:
    """(the allow-list, whether it restricts anything). Re-read whenever the file changes."""
    try:
        stat = ALLOW_FILE.stat()
        key = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = None
    if key is not None and _ALLOW_CACHE.get("key") == key:
        return _ALLOW_CACHE["ips"], bool(_ALLOW_CACHE["ips"])
    ips = set()
    if key is not None:
        try:
            text = ALLOW_FILE.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for line in text.splitlines():
            entry = line.split("#", 1)[0].strip()
            if entry:
                ips.add(_normalise_address(entry))
    if not ips and "unrestricted" not in _ALLOW_NOTED:
        _ALLOW_NOTED.add("unrestricted")
        note(f"  phone-gate: NO DEVICE RESTRICTION — {ALLOW_FILE} "
             + ("does not exist" if key is None else "lists no devices")
             + "; every device on the tailnet will be signed in automatically. Add one tailnet "
               "address per line to restrict it (see the file's own header).")
    if ips and "restricted" not in _ALLOW_NOTED:
        _ALLOW_NOTED.add("restricted")
        note(f"  phone-gate: sign-in restricted to {len(ips)} device(s) by {ALLOW_FILE.name}")
    _ALLOW_CACHE.update({"key": key, "ips": frozenset(ips)})
    return frozenset(ips), bool(ips)


def forbidden_response(device: str) -> bytes:
    """A short HTML refusal that names the device, so the owner can allow it in one line.

    HTML, not the engine's `text/plain`: iOS offers plain text as a download, which is the dead end
    this gate was built to remove (its own header, 2026-09-11). The address is HTML-escaped because
    it arrives in a header — attacker-chosen text must not become markup here.
    """
    who = html.escape(_log_text(device, 64))
    name = html.escape(ALLOW_FILE.name)
    body = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Not signed in</title></head>"
        "<body style=\"font:16px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "margin:2rem;max-width:34rem\">"
        "<h1 style=\"font-size:1.15rem;margin:0 0 .75rem\">This node does not sign in this device</h1>"
        "<p>Only the owner's own devices are signed in automatically. This request came from "
        f"<code>{who}</code>.</p>"
        f"<p>To allow it, add that address on one line to <code>{name}</code>, beside "
        "<code>phone-gate.py</code>, then reload this page.</p>"
        "</body></html>"
    ).encode("utf-8")
    return (
        b"HTTP/1.1 403 Forbidden\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"Cache-Control: no-store\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + body
    )


def handle(client: socket.socket, engine_port: int, engine_authority: str = "") -> None:
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
        # What the engine will see. Everything the gate sends upstream uses this, and
        # everything it answers the client uses `first`; the only exceptions are the
        # routes the gate answers itself, where the client's own headers are the truth.
        forward = rewrite_authority(first, engine_authority) if engine_authority else first
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

        # Who is asking, decided by the one header a caller cannot forge through Serve: the address
        # the proxy itself appended. A request with no X-Forwarded-For never went through Serve, so it
        # is loopback on this machine — the path the engine already trusts, left alone here.
        # A caller that SUPPLIED an X-Forwarded-For of its own makes the raw header carry more than
        # one entry; that is recorded (`xff=`) because it is both a spoof attempt and the reason the
        # parser reads the LAST entry. It is silent otherwise, so ordinary lines stay readable.
        device = forwarded_device(first)
        allow, restricted = allowed_devices()
        if device and restricted and device not in allow:
            note(f"{method} {path} client={_log_text(device)} peer={client_ip} -> REFUSED: not in "
                 f"{ALLOW_FILE.name}; this node signs in its owner's own devices only")
            try:
                client.sendall(forbidden_response(device))
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
            return

        offered_forward = request_header(first, b"x-forwarded-for")
        spoof = (f" xff={_log_text(offered_forward, 96)}"
                 if "," in offered_forward else "")
        note(f"{method} {path}{'?' + query[:24] if query else ''} "
             f"client={_log_text(device) if device else 'loopback'} peer={client_ip}{spoof} "
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

        # The PWA manifest, rewritten so the Home Screen Web App opens without Safari chrome
        # (`display: standalone`, the mode Apple documents for iOS). Answered here rather than
        # relayed because the engine serves the shipped manifest, which says `fullscreen`.
        # Deliberately WITHOUT auth, like the stylesheet: a manifest is not data, and the engine
        # itself serves it publicly. `b""` means "could not read it" - then the engine's own
        # answer is relayed unchanged rather than replaced with something invented.
        if method == "GET" and path == "/manifest.webmanifest":
            body = manifest_response(engine_port, engine_authority)
            if body:
                note(f"  -> manifest (iOS head): {len(body)} bytes")
                client.sendall(body)
                client.close()
                return

        # A document request that cannot be authenticated as sent: no cookie at all, or a
        # token the engine no longer honours (a saved link, a replayed redirect, an engine
        # restart). The gate signs the visitor in itself and returns the page.
        needs_token = bool(token) and ((not offered and not has_cookie) or (bool(offered) and offered != token))
        if needs_token:
            note("  -> not authenticated as sent: signing in in flight")
            signed_in = complete_login(engine_port, forward, token, path, engine_authority)
            if signed_in is not None:
                client.settimeout(None)
                client.sendall(signed_in)
                client.close()
                return

        client.settimeout(None)
        upstream = socket.create_connection(("127.0.0.1", engine_port), timeout=10)
        upstream.sendall(force_close(forward))

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
                signed_in = complete_login(engine_port, forward, token, path, engine_authority)
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
    ap.add_argument("--engine-authority", default="",
                    help="host:port to present to the engine as Host AND Origin (e.g. 127.0.0.1:3099). "
                         "Required when the engine was NOT started with --trusted-host for the name this "
                         "gate is published under: the fence refuses an untrusted Host with 403, and "
                         "Tailscale Serve preserves the client's Host. Setting it to the engine's own "
                         "loopback authority keeps the fence closed and needs no engine restart.")
    ap.add_argument("--log-file", default="",
                    help="append this gate's own decision log here (in addition to stdout). Needed when "
                         "the launcher gives the process no inherited stdout, which is how it stays "
                         "detached on Windows.")
    args = ap.parse_args()

    global LOG_PATH
    if args.log_file:
        LOG_PATH = Path(args.log_file)
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            # One rotation, at start: a phone gate left running for months must not fill a disk,
            # and the interesting lines are always the recent ones.
            if LOG_PATH.exists() and LOG_PATH.stat().st_size > 4 * 1024 * 1024:
                LOG_PATH.replace(LOG_PATH.with_suffix(LOG_PATH.suffix + ".1"))
        except OSError:
            LOG_PATH = None

    # WHO AM I, BEFORE ANYTHING CAN FAIL. Measured 2026-09-16: this gate has died silently four
    # times, twice with a 0-byte stderr and once after ~7 minutes of normal service (it served
    # requests at 18:01:04, 18:02:08 and 18:02:44 local and was gone by 18:03). main() is an
    # infinite accept loop and the listening banner proves the import succeeded, so a process that
    # stops leaving only a banner was killed, not crashed — the leading hypothesis is a console-close
    # event against a child started with `Start-Process -WindowStyle Hidden`, which still owns a
    # console (the launcher now uses pythonw.exe). This line and the `finally` below are what make
    # the next death readable instead of inferred: a start with no matching "exiting" line means it
    # was terminated from outside, and an "exiting" line means it stopped on its own.
    # argv carries no secret by construction — the token is read from the engine's log, never passed.
    note(f"phone-gate starting pid={os.getpid()} parent={getattr(os, 'getppid', lambda: '?')()} "
         f"argv={' '.join(sys.argv[1:])}")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # ONE LISTENER PER PORT, ENFORCED BY THE OS. Measured on this host 2026-09-16, because the
    # module name is not the behaviour: with SO_REUSEADDR on Windows a SECOND socket binds the same
    # 127.0.0.1:port and both listen (two `--listen-port 3086` gates were caught alive in the same
    # second, pids 28108 and 17776, splitting incoming connections), while SO_REUSEADDR on POSIX
    # only means "a restart may reuse a TIME_WAIT port". Four probes on this machine:
    #   two SO_REUSEADDR sockets          -> the second bind SUCCEEDS      (the bug)
    #   SO_EXCLUSIVEADDRUSE then REUSEADDR -> the second bind is refused    (WinError 10013)
    #   REUSEADDR then SO_EXCLUSIVEADDRUSE -> the second bind is refused    (WinError 10048)
    #   exclusive rebind right after a kill, with a real TIME_WAIT entry on the port
    #                                     -> SUCCEEDS on the first attempt  (a restart stays instant)
    # So exclusivity costs nothing here; it only removes the split-brain listener.
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("127.0.0.1", args.listen_port))
    except OSError as exc:
        # A duplicate start is not a failure. The watchdog (`phone-gate-ensure.ps1`) and
        # `serve-phone.ps1` can both decide to start the gate, and the loser must leave quietly:
        # one line saying who owns the port, exit 0, no traceback. Any OSError here is treated the
        # same way — Windows reports the refusal as 10013 in one direction and 10048 in the other,
        # so matching on an errno would be guessing.
        note(f"phone-gate: 127.0.0.1:{args.listen_port} is already owned by another process "
             f"({exc}); this duplicate start is exiting 0 and leaving it alone")
        try:
            srv.close()
        except OSError:
            pass
        return 0
    srv.listen(128)
    note(f"phone-gate listening on 127.0.0.1:{args.listen_port} -> engine 127.0.0.1:{args.engine_port}"
         + (f" (presenting authority {args.engine_authority})" if args.engine_authority else ""))
    accept_failures = 0
    try:
        while True:
            try:
                client, _ = srv.accept()
            except OSError as exc:
                # Logged once, then left alone: a socket that fails accept() forever would
                # otherwise spin at full CPU with no record of why.
                accept_failures += 1
                if accept_failures == 1:
                    note(f"phone-gate: accept() failed ({exc}); continuing")
                continue
            threading.Thread(target=handle, args=(client, args.engine_port, args.engine_authority),
                             daemon=True).start()
    finally:
        # Reached on a clean stop and on a KeyboardInterrupt; NOT reached when the process is
        # terminated from outside, and that absence is the diagnosis (see the starting line above).
        note(f"phone-gate exiting (pid={os.getpid()}, accept failures={accept_failures})")
        try:
            srv.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
