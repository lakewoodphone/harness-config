#!/usr/bin/env python3
"""Capture recently-played into the taste ledger. Runs every 30 min via cron.
The Spotify API only ever returns the last 50 plays, so anything not captured as it
happens is lost forever - which is why this runs often and inserts idempotently."""
import json, sqlite3, urllib.request, urllib.error, urllib.parse, datetime, os, sys

BASE = "/opt/company/music"
TOK = os.path.join(BASE, "spotify-token.json")
DB = os.path.join(BASE, "taste.db")
CID = "8ecbe0880e6e40d187cbe0b177fb43e4"

def load():
    return json.load(open(TOK))

def save(t):
    tmp = TOK + ".new"
    with open(tmp, "w") as f:
        json.dump(t, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TOK)

def refresh(t):
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": CID}).encode()
    req = urllib.request.Request("https://accounts.spotify.com/api/token", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    r = json.loads(urllib.request.urlopen(req, timeout=25).read())
    t["access_token"] = r["access_token"]
    t["expires_in"] = r.get("expires_in")
    if r.get("refresh_token"):
        t["refresh_token"] = r["refresh_token"]
    t["refreshed_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    save(t)
    return t

def api(t, path):
    req = urllib.request.Request("https://api.spotify.com/v1/" + path, headers={"Authorization": "Bearer " + t["access_token"]})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read()), t
    except urllib.error.HTTPError as e:
        if e.code == 401:
            t = refresh(t)
            req = urllib.request.Request("https://api.spotify.com/v1/" + path, headers={"Authorization": "Bearer " + t["access_token"]})
            return json.loads(urllib.request.urlopen(req, timeout=30).read()), t
        raise

def main():
    t = load()
    data, t = api(t, "me/player/recently-played?limit=50")
    items = data.get("items", [])
    con = sqlite3.connect(DB)
    c = con.cursor()
    now = datetime.datetime.now(datetime.UTC).isoformat()
    new = 0
    for i in items:
        tr = i.get("track") or {}
        if not tr.get("id"):
            continue
        c.execute("INSERT OR IGNORE INTO plays(track_id,played_at,artist,title,context,source,captured_at) VALUES(?,?,?,?,?,?,?)",
            (tr["id"], i["played_at"], ", ".join(a["name"] for a in tr.get("artists", [])), tr["name"],
             (i.get("context") or {}).get("type"), "poll", now))
        new += c.rowcount
    con.commit()
    total = c.execute("select count(*) from plays").fetchone()[0]
    print(f"{now} api_items={len(items)} new={new} total={total}")
    con.close()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("POLL_FAIL", repr(e)[:300], file=sys.stderr)
        sys.exit(1)
