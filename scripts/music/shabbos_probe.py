#!/usr/bin/env python3
"""shabbos_probe.py — candidate catalogue for a themed playlist (Erev Shabbos).

WHY DEEZER IS HERE AT ALL
    Spotify removed `artist top-tracks` and the `popularity` field in the February 2026
    API purge (see README §5 and the 2026-10-21 session). So "what are this artist's real,
    popular songs" cannot be asked of Spotify any more. Deezer answers it with no key, no
    account and no music: /search/artist -> /artist/{id}/top returns titles ordered by
    their own popularity rank. That is candidate GENERATION only.

    Resolution to a Spotify id is a separate, expensive step (search is the scarce
    resource: ~600 searches in 5 min earned a 12h app ban on 2026-10-26, prefs
    search_pace_seconds=2.0). Candidate generation must therefore never touch search.

Writes  /opt/company/music/shabbos/candidates.json
        {artist: {"dz_id","fans","tracks":[{"title","rank","album"}]}}
and prints a compact per-artist table so a human (or the agent) can choose songs.

Usage:  python3 shabbos_probe.py [--per-artist 25]
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

OUT_DIR = "/opt/company/music/shabbos"
OUT = os.path.join(OUT_DIR, "candidates.json")
DZ = "https://api.deezer.com"
UA = {"User-Agent": "lpt-music/1.0 (+lakewoodphonetech)"}

# (display name, [query variants tried in order]).  Variants exist where the catalogue
# spelling differs from how the name is spoken — L'Chaim OG vs LChaim, MBD vs Mordechai.
ROSTER = [
    ("Shlomo Carlebach", ["Shlomo Carlebach", "Carlebach"]),
    ("Yehuda Green", ["Yehuda Green"]),
    ("Zusha", ["Zusha"]),
    ("Eitan Katz", ["Eitan Katz"]),
    ("Yaakov Shwekey", ["Yaakov Shwekey"]),
    ("Thank You Hashem", ["Thank You Hashem", "TYH Nation"]),
    ("Shulem", ["Shulem", "Shulem Lemmer"]),
    ("Mordechai Shapiro", ["Mordechai Shapiro"]),
    ("L'Chaim OG", ["L'Chaim OG", "LChaim OG", "Lchaim"]),
    ("Ishay Ribo", ["Ishay Ribo"]),
    ("Akiva", ["Akiva"]),
    ("Benny Friedman", ["Benny Friedman"]),
    ("Avraham Fried", ["Avraham Fried"]),
    ("Mordechai Ben David", ["Mordechai Ben David", "MBD"]),
    ("Moshav Band", ["Moshav Band", "Moshav"]),
    ("Meilech Kohn", ["Meilech Kohn"]),
    ("Yosef Karduner", ["Yosef Karduner", "Karduner"]),
    ("Shlomo Katz", ["Shlomo Katz"]),
    ("Baruch Levine", ["Baruch Levine"]),
    ("Yonatan Razel", ["Yonatan Razel"]),
    ("Ari Goldwag", ["Ari Goldwag"]),
    ("Motty Steinmetz", ["Motty Steinmetz"]),
    ("Naftali Kempeh", ["Naftali Kempeh"]),
    ("Simcha Leiner", ["Simcha Leiner"]),
    ("Levy Falkowitz", ["Levy Falkowitz"]),
    ("Beri Weber", ["Beri Weber"]),
    ("Eli Schwebel", ["Eli Schwebel"]),
    ("Chaim Dovid", ["Chaim Dovid"]),
    ("Reva L'Sheva", ["Reva L'Sheva", "Reva LSheva"]),
    ("8th Day", ["8th Day"]),
    ("Miami Boys Choir", ["Miami Boys Choir"]),
    ("Yeedle", ["Yeedle"]),
    ("Mendy Wald", ["Mendy Wald"]),
    ("Shmueli Ungar", ["Shmueli Ungar"]),
    ("Joey Newcomb", ["Joey Newcomb"]),
    ("Sruly Green", ["Sruly Green"]),
    ("Dedi", ["Dedi", "Dedi Graucher"]),
    ("Ohad Moskowitz", ["Ohad Moskowitz"]),
    ("Yisroel Werdyger", ["Yisroel Werdyger"]),
    ("Shlomo Simcha", ["Shlomo Simcha"]),
    ("Nemouel", ["Nemouel"]),
    ("Uzia Tzadok", ["Uzia Tzadok"]),
    ("Shmuel Brazil", ["Shmuel Brazil"]),
    ("Freilach Band", ["Freilach Band", "Freilach"]),
    ("Neshama Carlebach", ["Neshama Carlebach"]),
    ("Shloime Gertner", ["Shloime Gertner"]),
    ("Yonina", ["Yonina"]),
    ("Yitzchak Meir Helfgot", ["Yitzchak Meir Helfgot", "Helfgot"]),
]


def dz(path, tries=3):
    """GET a Deezer path. Deezer allows ~50 req / 5 s; back off on 429/quota."""
    url = DZ + path
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:                                  # noqa: BLE001
            body = getattr(e, "read", lambda: b"")()[:200]
            wait = 2 * (attempt + 1)
            print(f"    deezer retry {attempt+1}/{tries} {path[:60]} :: {e} {body!r}", file=sys.stderr)
            time.sleep(wait)
    return {"__err": True}


def find_artist(variants):
    for q in variants:
        d = dz("/search/artist?q=" + urllib.parse.quote(q) + "&limit=5")
        for a in (d.get("data") or []):
            name = (a.get("name") or "").strip()
            # exact-ish match only: Deezer happily returns "Sasha" for "Zusha"
            if name.lower() == q.lower() or q.lower() in name.lower():
                return a
        time.sleep(0.15)
    return None


def main():
    per = 25
    if "--per-artist" in sys.argv:
        per = int(sys.argv[sys.argv.index("--per-artist") + 1])

    os.makedirs(OUT_DIR, exist_ok=True)
    out = {}
    for display, variants in ROSTER:
        a = find_artist(variants)
        if not a:
            print(f"!! {display}: NO DEEZER ARTIST MATCH")
            continue
        top = dz(f"/artist/{a['id']}/top?limit={per}")
        rows = []
        for t in (top.get("data") or []):
            rows.append({
                "title": (t.get("title") or "").strip(),
                "rank": t.get("rank"),
                "album": (t.get("album") or {}).get("title"),
            })
        out[display] = {"dz_id": a["id"], "dz_name": a.get("name"), "fans": a.get("nb_fan"), "tracks": rows}
        print(f"\n### {display}  (deezer: {a.get('name')} id={a['id']} fans={a.get('nb_fan')}) {len(rows)} tracks")
        for r in rows:
            print(f"   {r['title']}   [rank {r['rank']}]")
        time.sleep(0.15)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nwrote {OUT}  artists={len(out)} tracks={sum(len(v['tracks']) for v in out.values())}")


if __name__ == "__main__":
    main()
