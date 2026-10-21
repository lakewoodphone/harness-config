#!/usr/bin/env python3
"""Turn what actually happened into weights - the "gets better over time" step.

The owner's rule that shapes all of this: a track he never reached is NEUTRAL. It was not rejected,
he just did not get to it. Only three things carry information:

  * a closed listen verdict from the sampler (completed / partial / skipped)
  * a track he deleted from the playlist  (served, gone, never played -> a real negative)
  * a replay (played again later -> a positive)

Write nothing destructive: weights are recomputed wholesale inside a transaction, and every row
carries the counts that produced it so a human can audit a score instead of trusting it.
"""
import json, os, sqlite3, time, urllib.request, urllib.error, datetime

BASE = "/opt/company/music"
TOK = os.path.join(BASE, "spotify-token.json")
DB = os.path.join(BASE, "taste.db")
PID = open(os.path.join(BASE, "daily-playlist-id.txt")).read().strip()
CID = "8ecbe0880e6e40d187cbe0b177fb43e4"

VERDICT_VALUE = {"completed": 1.0, "partial": 0.3, "skipped": -0.7, "unknown": 0.0, "idle": 0.0}


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


def refresh(t):
    import urllib.parse
    body = urllib.parse.urlencode({"grant_type": "refresh_token",
                                   "refresh_token": t["refresh_token"], "client_id": CID}).encode()
    req = urllib.request.Request("https://accounts.spotify.com/api/token", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    r = json.loads(urllib.request.urlopen(req, timeout=25).read())
    t["access_token"] = r["access_token"]
    if r.get("refresh_token"):
        t["refresh_token"] = r["refresh_token"]
    tmp = TOK + ".new"
    with open(tmp, "w") as f:
        json.dump(t, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TOK)
    return t


def playlist_track_ids(t):
    req = urllib.request.Request(
        "https://api.spotify.com/v1/playlists/" + PID + "/items?limit=100&fields=items(item(id))",
        headers={"Authorization": "Bearer " + t["access_token"]})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=25).read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return playlist_track_ids(refresh(t))
        raise
    out = set()
    for it in d.get("items") or []:
        tr = (it or {}).get("item") or {}
        if tr.get("id"):
            out.add(tr["id"])
    return out


def main():
    t = json.load(open(TOK))
    con = sqlite3.connect(DB)
    c = con.cursor()
    c.executescript("""
      CREATE TABLE IF NOT EXISTS weights(key TEXT PRIMARY KEY, value REAL, updated_at TEXT, why TEXT);
    """)
    current = playlist_track_ids(t)

    # ---- 1. closed listen verdicts, per artist
    rows = c.execute("SELECT artist, verdict, COUNT(*) FROM listens "
                     "WHERE ended_at IS NOT NULL AND verdict IS NOT NULL GROUP BY artist, verdict").fetchall()
    per_artist = {}
    for artist, verdict, n in rows:
        a = per_artist.setdefault(artist, {"completed": 0, "partial": 0, "skipped": 0, "unknown": 0, "idle": 0})
        a[verdict] = a.get(verdict, 0) + n

    # ---- 2. served but deleted from the playlist and never played -> a real negative
    served_latest = c.execute("SELECT src, track_id, artist, title, served_at FROM served "
                              "WHERE run_id = (SELECT id FROM runs ORDER BY rowid DESC LIMIT 1)").fetchall()

    def played_since(tid, served_at):
        """A play BEFORE we served it is history, not a response to this playlist."""
        return c.execute("SELECT 1 FROM plays WHERE track_id = ? AND played_at > ? LIMIT 1",
                         (tid, served_at)).fetchone()

    removed, carried = [], []
    for src, tid, artist, title, served_at in served_latest:
        if tid in current:
            carried.append((src, tid, artist, title))
        elif not played_since(tid, served_at):
            removed.append((src, tid, artist, title))
    for src, tid, artist, title in removed:
        a = per_artist.setdefault(artist, {"completed": 0, "partial": 0, "skipped": 0, "unknown": 0, "idle": 0})
        a["skipped"] = a.get("skipped", 0) + 1

    # ---- 3. bucket yield: of what was served in that bucket, how much got played at all
    bucket = {}
    for src, tid, artist, title, served_at in served_latest:
        played = played_since(tid, served_at)
        b = bucket.setdefault(src, [0, 0])
        b[1] += 1
        if played:
            b[0] += 1

    stamp = now()
    written = 0
    c.execute("BEGIN")
    for artist, counts in per_artist.items():
        total = sum(counts.values())
        if total == 0:
            continue
        score = sum(VERDICT_VALUE.get(k, 0) * v for k, v in counts.items()) / total
        c.execute("INSERT OR REPLACE INTO weights(key, value, updated_at, why) VALUES(?,?,?,?)",
                  ("artist:" + artist.lower(), round(score, 4), stamp, json.dumps(counts)))
        written += 1
    for src, (played, served) in bucket.items():
        c.execute("INSERT OR REPLACE INTO weights(key, value, updated_at, why) VALUES(?,?,?,?)",
                  ("bucket:" + src, round(played / served, 4), stamp,
                   json.dumps({"played": played, "served": served})))
        written += 1
    con.commit()

    print(f"{stamp} closed_listens={sum(1 for _ in rows)} artists={len(per_artist)} "
          f"deleted_unplayed={len(removed)} still_in_playlist={len(carried)} weights={written}")
    for src, (played, served) in sorted(bucket.items()):
        print(f"  bucket {src:16s} played {played}/{served}")
    for artist, counts in sorted(per_artist.items(), key=lambda x: -sum(x[1].values()))[:6]:
        total = sum(counts.values())
        score = sum(VERDICT_VALUE.get(k, 0) * v for k, v in counts.items()) / total
        print(f"  artist {artist[:24]:24s} n={total:3d} score={score:+.2f} {counts}")
    con.close()


if __name__ == "__main__":
    main()
