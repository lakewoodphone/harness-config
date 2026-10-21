#!/usr/bin/env python3
"""Re-authorise the Spotify app (PKCE, no client secret).

Run this when the refresh token finally dies (they live 180 days, and the daily loop keeps it alive,
so this should be rare). It prints a URL, opens a loopback listener for the redirect, exchanges the
code, and writes the token file.

    python3 auth.py --print-url          # just show the URL (no listener)
    python3 auth.py                      # URL + listen on 127.0.0.1:8888 + write the token file

The redirect URI registered on the Spotify app must be http://127.0.0.1:<port>/callback.
Spotify rejects `localhost` and only permits plain HTTP on a loopback IP.
"""
import argparse, base64, hashlib, json, os, secrets, threading, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

CLIENT_ID = "8ecbe0880e6e40d187cbe0b177fb43e4"
SCOPES = ("user-read-playback-state user-read-currently-playing user-read-recently-played "
          "user-top-read user-library-read user-library-modify user-follow-read "
          "playlist-read-private playlist-read-collaborative playlist-modify-private "
          "playlist-modify-public")


def verifier_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def auth_url(client_id, port, challenge):
    q = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": f"http://127.0.0.1:{port}/callback",
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(q)


class Catcher(BaseHTTPRequestHandler):
    code = None
    error = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            Catcher.code = qs["code"][0]
            body = b"<h2>Authorized.</h2><p>Close this tab and go back to the terminal.</p>"
        else:
            Catcher.error = qs.get("error", ["unknown"])[0]
            body = f"<h2>Denied: {Catcher.error}</h2>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def exchange(client_id, port, code, verifier):
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": f"http://127.0.0.1:{port}/callback",
        "client_id": client_id,
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request("https://accounts.spotify.com/api/token", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", default=CLIENT_ID)
    ap.add_argument("--port", type=int, default=8888)
    ap.add_argument("--out", default="/opt/company/music/spotify-token.json")
    ap.add_argument("--print-url", action="store_true")
    args = ap.parse_args()

    verifier, challenge = verifier_pair()
    url = auth_url(args.client_id, args.port, challenge)
    print(url)
    if args.print_url:
        return

    server = HTTPServer(("127.0.0.1", args.port), Catcher)
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    print(f"listening on 127.0.0.1:{args.port} - open the URL above and press Agree", flush=True)
    t.join(timeout=600)
    server.server_close()

    if not Catcher.code:
        raise SystemExit(f"no code received (error={Catcher.error})")
    tok = exchange(args.client_id, args.port, Catcher.code, verifier)
    tmp = args.out + ".new"
    with open(tmp, "w") as f:
        json.dump(tok, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, args.out)
    print("TOKEN_OK scope=" + str(tok.get("scope")) +
          " refresh_token_present=" + str(bool(tok.get("refresh_token"))))


if __name__ == "__main__":
    main()
