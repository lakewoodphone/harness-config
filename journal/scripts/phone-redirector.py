#!/usr/bin/env python3
"""phone-redirector.py — make the URL the owner already has land in the harness.

The owner's phone has `https://ai.abletelsolutions.com/phone` on its home screen — the old single-turn
"Secretary Chat" PWA. He asked for that link to open the harness instead, and he should not have to
learn a new URL or re-add an icon.

So the tunnel routes that one path here, and this returns a 302 to the harness on the tailnet. It used
to put the launch token in that Location; it does not any more. As of 2026-09-11 the gate in front of the
engine signs a visitor in on the spot (it exchanges the token internally and returns the page with the
session cookie), so a bare URL is enough — and a bare URL means the token is never in a link the owner can
save, a browser can keep in history, or anyone can read out of a Location header.

Why a redirect and not a proxy: the harness refuses to be exposed (its own CLI rejects a public bind
because it "would expose remote code execution to the network"), and proxying would put that capability
on the public internet. Redirecting keeps the app reachable only by tailnet devices, which is the whole
point of Tailscale Serve. A phone that is not on the tailnet gets a clear page saying so instead of a
browser error.

usage:  phone-redirector.py [--port 3087] [--host 127.0.0.1]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATE_DIR = Path(os.environ.get("PHONE_STATE", Path.home() / ".dsh-phone"))
PORT = int(os.environ.get("PHONE_REDIRECT_PORT", "3087"))


def tailnet_name() -> str:
    """This node's tailnet DNS name, or '' when Tailscale cannot say."""
    override = os.environ.get("PHONE_TAILNET")
    if override:
        return override.strip()
    try:
        raw = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10).stdout
        return str((json.loads(raw).get("Self") or {}).get("DNSName", "")).rstrip(".")
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def live_token() -> str:
    """The newest launch token printed by the engine, read fresh on every request."""
    best = ""
    for log in sorted(STATE_DIR.glob("engine-*.log"), key=lambda p: p.stat().st_mtime):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = re.findall(r"token=([A-Za-z0-9_-]+)", text)
        if found:
            best = found[-1]
    return best


class Handler(BaseHTTPRequestHandler):
    server_version = "phone-redirector"

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        host = tailnet_name()
        token = live_token()

        if not host:
            return self._page(503, "Tailscale is not answering on this host",
                              "The phone link needs the tailnet name. Run `serve-phone.sh --status` on secratary.")
        if not token:
            return self._page(503, "The harness engine is not running",
                              "Start it with `serve-phone.sh` on secratary, then tap this link again.")

        # 302, not 301: cached as permanent, this link would survive a change of address.
        # No token: the gate in front of the engine signs the visitor in on arrival.
        target = f"https://{host}/"
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def _page(self, code: int, title: str, detail: str) -> None:
        body = (
            f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title>"
            f"<body style='font:16px/1.5 -apple-system,system-ui;padding:2rem;max-width:32rem'>"
            f"<h1 style='font-size:1.25rem'>{html.escape(title)}</h1>"
            f"<p style='color:#555'>{html.escape(detail)}</p></body>"
        ).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # keep the journald log quiet
        return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--host", default=os.environ.get("PHONE_REDIRECT_HOST", "127.0.0.1"))
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"phone-redirector listening on {args.host}:{args.port} -> tailnet harness", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
