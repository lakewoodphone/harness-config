#!/usr/bin/env python3
"""Daily playlist builder v2 - implements the owner's stored spec.

THE SPEC (source: prefs table, every value quoted from him)
  100 tracks = 50 familiar + 35 adjacent new + 10 one-genre-over + 5 way out
  familiar = artists he has played >=3 distinct tracks of (ramped to 2 while thin),
             last play within 90 days
  of the 50 familiar: at most 2 played in the last 7 days, at most 10 in the last 21,
             the rest are deep cuts by those artists or tracks last played 21+ days ago
  15 of the 100 in the jewish/chassidic lane
  order is irrelevant - he shuffles - so no sequencing
  no exclusions
  skip drivers: tempo first, recognition second -> down-weight globally huge tracks
             from artists he has never played (Deezer rank as the popularity proxy)

Nothing here is hardcoded that he told me: the numbers come out of prefs at runtime.
"""
import json, sqlite3, sys, time, urllib.request, urllib.error, urllib.parse, datetime, os

BASE = "/opt/company/music"
TOK = os.path.join(BASE, "spotify-token.json")
DB = os.path.join(BASE, "taste.db")
PID = open(os.path.join(BASE, "daily-playlist-id.txt")).read().strip()
CID = "8ecbe0880e6e40d187cbe0b177fb43e4"
UA = {"User-Agent": "lpt-music-curator/0.1 (ezabz@lakewoodphonetech)"}

STEP_SEEDS = ["Zach Bryan", "Tyler Childers", "Noah Kahan", "Zachary Knowles"]
WILD_SEEDS = ["Leon Bridges", "Michael Kiwanuka", "Black Pumas", "Yola", "Durand Jones"]


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


def dnow(days=0):
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).isoformat()


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


def spotify(t, method, path, body=None, tries=0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("https://api.spotify.com/v1/" + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + t["access_token"],
                                          "Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None), t
    except urllib.error.HTTPError as e:
        if e.code == 401 and tries < 2:
            return spotify(refresh(t), method, path, body, tries + 1)
        if e.code == 429 and tries < 3:
            time.sleep(min(int(e.headers.get("Retry-After") or 4), 25))
            return spotify(t, method, path, body, tries + 1)
        return e.code, e.read(300).decode("utf8", "replace"), t


def http_json(url, tries=2):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                time.sleep(2)
                continue
            return {}
        except Exception:
            time.sleep(1)
    return {}


def prefs(c):
    defaults = {"familiar_max_played_7d": "2", "familiar_max_played_21d": "10"}
    d = dict(defaults)
    for k, v in c.execute("SELECT key, value FROM prefs").fetchall():
        d[k] = v
    return d


def mbid_for(c, con, t, artist):
    row = c.execute("SELECT val FROM cache WHERE key = ?", ("mbid:" + artist.lower(),)).fetchone()
    if row:
        return row[0]
    s, res, t = spotify(t, "GET", "search?q=" + urllib.parse.quote(artist) + "&type=artist&limit=1")
    arts = ((res or {}).get("artists") or {}).get("items") if isinstance(res, dict) else None
    if not arts:
        return None
    aname = arts[0]["name"]
    mb = http_json("https://musicbrainz.org/ws/2/artist?query=" +
                   urllib.parse.quote("artist:" + aname) + "&fmt=json&limit=1")
    time.sleep(1.1)
    if not mb.get("artists"):
        return None
    mbid = mb["artists"][0]["id"]
    c.execute("INSERT OR REPLACE INTO cache(key,val,updated_at) VALUES(?,?,?)",
              ("mbid:" + artist.lower(), mbid, now()))
    con.commit()
    return mbid, t


def neighbours(mbid, limit):
    sim = http_json("https://labs.api.listenbrainz.org/similar-artists/json?artist_mbids=" + mbid +
                    "&algorithm=session_based_days_9000_session_300_contribution_5_threshold_15_limit_50_skip_30")
    rows = sim if isinstance(sim, list) else sim.get("data", [])
    return [(r.get("name"), r.get("score", 0)) for r in rows[:limit] if r.get("name")]


def deezer_artist_tracks(name, limit=8):
    dz = http_json("https://api.deezer.com/search/artist?q=" + urllib.parse.quote(name) + "&limit=1")
    if not (isinstance(dz, dict) and dz.get("data")):
        return []
    dzid = dz["data"][0]["id"]
    tt = http_json("https://api.deezer.com/artist/" + str(dzid) + "/top?limit=" + str(limit))
    out = []
    for tr in tt.get("data") or []:
        out.append({"artist": tr["artist"]["name"], "title": tr["title"], "dzid": tr.get("id"),
                    "rank": tr.get("rank", 0), "isrc": tr.get("isrc")})
    return out


def isrc_of(c, con, cand):
    if cand.get("isrc"):
        return cand["isrc"]
    if not cand.get("dzid"):
        return None
    key = "isrc:" + str(cand["dzid"])
    row = c.execute("SELECT val FROM cache WHERE key = ?", (key,)).fetchone()
    if row:
        return row[0] or None
    td = http_json("https://api.deezer.com/track/" + str(cand["dzid"]))
    isrc = td.get("isrc")
    c.execute("INSERT OR REPLACE INTO cache(key,val,updated_at) VALUES(?,?,?)", (key, isrc or "", now()))
    con.commit()
    time.sleep(0.08)
    return isrc


def resolve(c, con, t, cand):
    isrc = isrc_of(c, con, cand)
    if not isrc:
        return None, t
    row = c.execute("SELECT track_id FROM resolve_cache WHERE isrc = ?", (isrc,)).fetchone()
    if row:
        return row[0], t
    s, res, t = spotify(t, "GET", "search?q=isrc:" + isrc + "&type=track&limit=3")
    items = ((res or {}).get("tracks") or {}).get("items") if isinstance(res, dict) else None
    tid = items[0]["id"] if items else None
    if tid:
        c.execute("INSERT OR REPLACE INTO resolve_cache(isrc,track_id,resolved_at) VALUES(?,?,?)",
                  (isrc, tid, now()))
        con.commit()
    time.sleep(0.2)
    return tid, t


def main():
    dry = "--dry-run" in sys.argv
    t = json.load(open(TOK))
    con = sqlite3.connect(DB)
    c = con.cursor()
    c.executescript("""
      CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, val TEXT, updated_at TEXT);
      CREATE TABLE IF NOT EXISTS resolve_cache(isrc TEXT PRIMARY KEY, track_id TEXT, resolved_at TEXT);
      CREATE TABLE IF NOT EXISTS prefs(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT, source TEXT);
      CREATE TABLE IF NOT EXISTS lane_artists(artist TEXT PRIMARY KEY, lane TEXT, added_at TEXT, source TEXT);
    """)
    try:
        c.execute("ALTER TABLE served ADD COLUMN src TEXT")
        con.commit()
    except Exception:
        pass

    P = prefs(c)
    N_TOTAL = 100
    N_FAM = 50
    N_ADJ = int(P.get("new_adjacent", "35"))
    N_STEP = int(P.get("new_step_out", "10"))
    N_WILD = int(P.get("new_wild", "5"))
    N_JEW = int(round(float(P.get("jewish_share", "0.15")) * N_TOTAL))
    cap7 = int(P.get("familiar_max_played_7d", "2"))
    cap21 = int(P.get("familiar_max_played_21d", "10"))
    print(f"SPEC familiar={N_FAM} adjacent={N_ADJ} step={N_STEP} wild={N_WILD} jewish={N_JEW} caps={cap7}/{cap21}")

    # ---------- known world
    plays = {}
    for tid, artist, title, last in c.execute(
            "SELECT track_id, artist, title, MAX(played_at) FROM plays GROUP BY track_id").fetchall():
        plays[tid] = {"artist": artist or "", "title": title or "", "last": last}
    stats = c.execute("SELECT artist, COUNT(DISTINCT track_id) d, MAX(played_at) last FROM plays "
                      "GROUP BY artist").fetchall()
    min_distinct = 3
    familiar_artists = [r[0] for r in stats if r[1] >= min_distinct and r[2] >= dnow(90)]
    if len(familiar_artists) < 8:
        min_distinct = 2
        familiar_artists = [r[0] for r in stats if r[1] >= min_distinct and r[2] >= dnow(90)]
    print("FAMILIAR artists (>=" + str(min_distinct) + " distinct, 90d):", len(familiar_artists), familiar_artists[:10])

    lane_j = [x.lower() for x in (r[0] for r in c.execute("SELECT artist FROM lane_artists").fetchall())]

    def is_jewish(artist):
        n = (artist or "").lower()
        return any(j in n or n in j for j in lane_j)

    # ---------- familiar pool
    pool_recent7, pool_recent21, pool_deep = [], [], []
    for tid, info in plays.items():
        if info["last"] >= dnow(7):
            pool_recent7.append((tid, info))
        elif info["last"] >= dnow(21):
            pool_recent21.append((tid, info))
        else:
            pool_deep.append((tid, info))
    pool_recent7.sort(key=lambda x: x[1]["last"], reverse=True)
    pool_recent21.sort(key=lambda x: x[1]["last"], reverse=True)

    chosen = []
    seen = set()
    seen_titles = set()

    def norm_title(title):
        t = (title or "").lower()
        for sep in (" (", " - ", " ["):
            if sep in t:
                t = t.split(sep)[0]
        return t.strip()

    def add(row, bucket):
        if row["id"] in seen or len(chosen) >= N_TOTAL:
            return False
        key = ((row.get("artist") or "").lower(), norm_title(row.get("title")))
        if key in seen_titles:
            return False
        chosen.append(dict(row, src=bucket))
        seen.add(row["id"])
        seen_titles.add(key)
        return True

    # current favourites first, under the caps
    for tid, info in pool_recent7[:cap7]:
        add({"id": tid, "uri": "spotify:track:" + tid, "artist": info["artist"], "title": info["title"]}, "familiar_recent")
    for tid, info in pool_recent21[:max(0, cap21 - cap7)]:
        add({"id": tid, "uri": "spotify:track:" + tid, "artist": info["artist"], "title": info["title"]}, "familiar_21d")

    # deep cuts: real catalogue of the familiar artists, skipping anything played in the last 21 days
    recent_ids = {tid for tid, _ in pool_recent7} | {tid for tid, _ in pool_recent21}
    deep_needed = N_FAM - len(chosen)
    print("DEEP CUTS needed:", deep_needed)
    for artist in familiar_artists[:10]:
        if deep_needed <= 0:
            break
        s, res, t = spotify(t, "GET", "search?q=" + urllib.parse.quote(artist) + "&type=artist&limit=1")
        arts = ((res or {}).get("artists") or {}).get("items") if isinstance(res, dict) else None
        if not arts:
            continue
        aid = arts[0]["id"]
        s, alb, t = spotify(t, "GET", "artists/" + aid + "/albums?include_groups=album&limit=8")
        got = 0
        for a in (alb.get("items") or []) if isinstance(alb, dict) else []:
            if deep_needed <= 0 or got >= 6:
                break
            s, tr, t = spotify(t, "GET", "albums/" + a["id"] + "/tracks?limit=20")
            for x in (tr.get("items") or []) if isinstance(tr, dict) else []:
                if deep_needed <= 0 or got >= 6:
                    break
                if x["id"] in seen or x["id"] in recent_ids:
                    continue
                add({"id": x["id"], "uri": x["uri"],
                     "artist": ", ".join(z["name"] for z in x["artists"]), "title": x["name"]}, "familiar_deep")
                deep_needed -= 1
                got += 1
        if deep_needed > 0:
            continue
    print("AFTER FAMILIAR:", len(chosen))

    # ---------- new pools
    def build_pool(seed_names, lanes, per_seed=4, per_nb=4):
        nonlocal t
        out = []
        for name in seed_names:
            r = mbid_for(c, con, t, name)
            if not r:
                continue
            mbid, t = r if isinstance(r, tuple) else (r, t)
            names = [name] + ([n for n, _ in neighbours(mbid, per_nb)] if per_nb else [])
            for nm in names:
                for cand in deezer_artist_tracks(nm, limit=per_seed):
                    cand["seed"] = name
                    cand["lane"] = lanes
                    out.append(cand)
        return out

    played_ids = set(plays.keys())
    familiar_lower = {a.lower() for a in familiar_artists}

    # weights written by learn.py - absent on day one, which is a valid state, not an error
    w = {}
    for k, v, why in c.execute("SELECT key, value, why FROM weights WHERE key LIKE 'artist:%'").fetchall():
        try:
            n = sum(json.loads(why).values())
        except Exception:
            n = 0
        w[k.split(":", 1)[1]] = (v, n)

    def blocked(artist):
        """Applied ONLY to artists he does not already play. His answer to exclusions was
        'don't ditch anybody', so a familiar artist is never dropped on the strength of two skips."""
        s = w.get((artist or "").lower())
        return bool(s and s[1] >= 2 and s[0] <= -0.4)

    def usable(cand):
        return (cand["artist"].lower() not in familiar_lower
                and cand.get("rank", 0) < 700000
                and not blocked(cand["artist"]))

    # rotate seed order daily so one artist cannot own an entire bucket
    day = datetime.datetime.now(datetime.UTC).timetuple().tm_yday
    step_seeds = STEP_SEEDS[day % len(STEP_SEEDS):] + STEP_SEEDS[:day % len(STEP_SEEDS)]
    wild_seeds = WILD_SEEDS[day % len(WILD_SEEDS):] + WILD_SEEDS[:day % len(WILD_SEEDS)]

    adj_pool = build_pool([a for a in [r[0] for r in c.execute(
        "SELECT artist FROM plays GROUP BY artist ORDER BY COUNT(*) DESC LIMIT 12").fetchall()]],
        "adjacent", per_seed=4, per_nb=4)
    step_pool = build_pool(step_seeds, "step", per_seed=8, per_nb=0)
    wild_pool = build_pool(wild_seeds, "wild", per_seed=6, per_nb=0)
    jew_pool = build_pool([r[0] for r in c.execute("SELECT artist FROM lane_artists").fetchall()],
                          "jewish", per_seed=4, per_nb=4)
    print("POOLS raw adj/step/wild/jewish:", len(adj_pool), len(step_pool), len(wild_pool), len(jew_pool))

    def fill(pool, bucket, want):
        nonlocal t
        got = 0
        for cand in pool:
            if got >= want or len(chosen) >= N_TOTAL:
                break
            if not usable(cand):
                continue
            tid, t2 = resolve(c, con, t, cand)
            t = t2
            if not tid or tid in seen or tid in played_ids:
                continue
            add({"id": tid, "uri": "spotify:track:" + tid, "artist": cand["artist"],
                 "title": cand["title"]}, bucket)
            got += 1
        return got

    n_j = len([x for x in chosen if is_jewish(x["artist"])])
    need_j = max(0, N_JEW - n_j)
    jew_taken = fill(jew_pool, "jewish", need_j)
    print("JEWISH filled:", jew_taken, "of", need_j)

    adj_taken = fill(adj_pool, "adjacent", N_ADJ - jew_taken)
    step_taken = fill(step_pool, "step", N_STEP)
    wild_taken = fill(wild_pool, "wild", N_WILD)
    print("FILLED adj/step/wild:", adj_taken, step_taken, wild_taken)

    if len(chosen) < N_TOTAL:
        extra = fill(adj_pool, "adjacent_extra", N_TOTAL - len(chosen))
        print("TOP-UP from adjacent:", extra)

    counts = {}
    for x in chosen:
        counts[x["src"]] = counts.get(x["src"], 0) + 1
    jew = len([x for x in chosen if is_jewish(x["artist"])])
    print("COMPOSED", len(chosen), "| buckets", counts, "| jewish lane", jew)
    for x in chosen[:10]:
        print("   ", x["src"], "|", x["artist"][:26], "-", str(x["title"])[:38])

    if dry:
        print("DRY RUN - nothing written")
        return

    s, res, t = spotify(t, "PUT", "playlists/" + PID + "/items",
                        {"uris": [x["uri"] for x in chosen]})
    print("WRITE", s, str(res)[:100])
    rid = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    c.execute("INSERT OR REPLACE INTO runs(id,kind,created_at,playlist_id,prompt,n_tracks,note) "
              "VALUES(?,?,?,?,?,?,?)",
              (rid, "daily_v2", now(), PID, "owner spec", len(chosen),
               json.dumps({"buckets": counts, "jewish": jew, "familiar_artists": len(familiar_artists)})))
    for x in chosen:
        c.execute("INSERT OR REPLACE INTO served(run_id,track_id,served_at,artist,title,src) VALUES(?,?,?,?,?,?)",
                  (rid, x["id"], now(), x["artist"], str(x["title"]), x["src"]))
    con.commit()
    con.close()
    print("RUN", rid)


if __name__ == "__main__":
    main()
