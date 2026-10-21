#!/usr/bin/env python3
"""Sample the live player once a minute and infer what actually happened to each track.

Spotify exposes no skip events and no completion percentage, so this reconstructs them:
every sample records the furthest point a track reached. When the track changes we compare
that maximum against the track's duration.

  completed  - reached >= 92% of its length
  skipped    - left before 35% of its length
  partial    - anything in between
  idle       - nothing was playing when the sample ran

It is a sampler: a skip faster than the interval reads as a gap, and a device that goes
offline looks idle. That limitation is real and is why the verdicts are bucketed, not scored
as seconds.
"""
import json, os, sqlite3, urllib.request, urllib.error, urllib.parse, datetime, sys, time

BASE = "/opt/company/music"
TOK = os.path.join(BASE, "spotify-token.json")
DB = os.path.join(BASE, "taste.db")
CID = "8ecbe0880e6e40d187cbe0b177fb43e4"


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


def save_tok(t):
    tmp = TOK + ".new"
    with open(tmp, "w") as f:
        json.dump(t, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TOK)


def refresh(t):
    body = urllib.parse.urlencode({"grant_type": "refresh_token",
                                   "refresh_token": t["refresh_token"],
                                   "client_id": CID}).encode()
    req = urllib.request.Request("https://accounts.spotify.com/api/token", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    r = json.loads(urllib.request.urlopen(req, timeout=25).read())
    t["access_token"] = r["access_token"]
    if r.get("refresh_token"):
        t["refresh_token"] = r["refresh_token"]
    save_tok(t)
    return t


def get_player(t, tries=0):
    req = urllib.request.Request("https://api.spotify.com/v1/me/player",
                                 headers={"Authorization": "Bearer " + t["access_token"]})
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        if resp.status == 204:
            return None, t
        raw = resp.read()
        return (json.loads(raw) if raw else None), t
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return get_player(refresh(t), tries)
        if e.code == 403:
            print("SCOPE_MISSING user-read-playback-state", file=sys.stderr)
            sys.exit(0)
        if e.code == 204:
            return None, t
        if e.code == 429 and tries < 2:
            wait = int(e.headers.get("Retry-After") or 5)
            time.sleep(min(wait, 20))
            return get_player(t, tries + 1)
        raise


def verdict(top, dur):
    if not dur:
        return "unknown"
    if top >= int(dur * 0.92):
        return "completed"
    if top < int(dur * 0.35):
        return "skipped"
    return "partial"


def main():
    t = json.load(open(TOK))
    con = sqlite3.connect(DB)
    c = con.cursor()
    c.executescript("""
      CREATE TABLE IF NOT EXISTS listens(
        id INTEGER PRIMARY KEY, track_id TEXT, artist TEXT, title TEXT, device TEXT,
        started_at TEXT, last_seen TEXT, max_progress_ms INTEGER, duration_ms INTEGER,
        ended_at TEXT, verdict TEXT);
      CREATE INDEX IF NOT EXISTS idx_listens_track ON listens(track_id);
    """)
    state, t = get_player(t)
    open_row = c.execute("SELECT id, track_id, max_progress_ms, duration_ms FROM listens "
                         "WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    cur_id = None
    cur_prog = 0
    cur_dur = None
    cur_dev = None
    if state and state.get("item"):
        it = state["item"]
        cur_id = it.get("id")
        cur_prog = state.get("progress_ms") or 0
        cur_dur = it.get("duration_ms")
        cur_dev = (state.get("device") or {}).get("name")

    if open_row:
        oid, otrack, oprog, odur = open_row
        if cur_id != otrack:
            c.execute("UPDATE listens SET ended_at=?, verdict=? WHERE id=?",
                      (now(), verdict(oprog or 0, odur), oid))
            open_row = None

    if cur_id:
        if open_row and open_row[1] == cur_id:
            c.execute("UPDATE listens SET last_seen=?, max_progress_ms=MAX(COALESCE(max_progress_ms,0),?), duration_ms=COALESCE(?,duration_ms) WHERE id=?",
                      (now(), cur_prog, cur_dur, open_row[0]))
        else:
            it = state["item"]
            c.execute("INSERT INTO listens(track_id,artist,title,device,started_at,last_seen,max_progress_ms,duration_ms) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (cur_id, ", ".join(a["name"] for a in it.get("artists", [])), it.get("name"),
                       cur_dev, now(), now(), cur_prog, cur_dur))
    elif open_row:
        c.execute("UPDATE listens SET ended_at=?, verdict=? WHERE id=?",
                  (now(), verdict(open_row[2] or 0, open_row[3]), open_row[0]))
    con.commit()
    n = c.execute("SELECT COUNT(*) FROM listens").fetchone()[0]
    closed = c.execute("SELECT COUNT(*) FROM listens WHERE ended_at IS NOT NULL").fetchone()[0]
    print(f"{now()} playing={cur_id is not None} listens={n} closed={closed}")
    con.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("SAMPLER_FAIL", repr(e)[:250], file=sys.stderr)
        sys.exit(1)
