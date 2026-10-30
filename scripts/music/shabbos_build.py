#!/usr/bin/env python3
"""shabbos_build.py — build the "Erev Shabbos" playlist on the owner's Spotify account.

WHY THIS FILE EXISTS SEPARATELY FROM build_v3.py
    build_v3.py is the *daily* engine and obeys the prefs table (50 familiar / 35 adjacent /
    10 step-out / 5 wild, 21-day blacklist, era floor 1996, shuffle-safe). None of that is
    right for a themed Shabbos playlist: Carlebach died in 1994, so an era floor of 1996
    deletes the well this list is drawn from. Different brief, different tool.

WHAT THE FEBRUARY 2026 API PURGE LEFT US, MEASURED 2026-10-30 (this file's reason to exist)
    * `q=track:"X" artist:"Y"` returns **0 items** — the combined field filter is dead.
      An earlier version of this script built entirely on that shape and resolved 2 of 9.
    * `q=Lecha Dodi Carlebach` (plain keywords) works, `total=305`.
    * `q=artist:"Carlebach"` works AND **`&offset=10,20` pages correctly**. That is the
      missing `artist top-tracks` endpoint, reconstructed: 40 ranked songs per artist.
    * `total` in the response is unreliable (reported 0 on pages that returned 10 items),
      so this code never trusts it — it pages until a page comes back short.
    * Titles differ by apostrophe ("L'cha Dodi" vs "Lecha Dodi"), so matching is fuzzy.

COST MODEL
    Search is the scarce resource: ~600 searches in 5 min earned a 12-hour app ban on
    2026-10-26 (retry_after 44141). prefs say pace 2.0 s, budget 220 per build. Catalogues
    are cached forever in this directory, so a re-run pays only for what changed.

THREE PHASES, ON PURPOSE
    --catalogue  page each artist's ranked catalogue (the expensive, cached part)
    --plan       match the wanted titles against real catalogue entries, select per cap,
                 write plan.json. Nothing touches Spotify, so a bad match is inspectable.
    --write      create/refill the playlist and read it back. Idempotent by name.
"""
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

HERE = "/opt/company/music/shabbos"
CAT = os.path.join(HERE, "catalogue.json")
PLAN = os.path.join(HERE, "plan.json")
CACHE = os.path.join(HERE, "resolve.json")     # targeted one-off keyword searches
TOKEN = "/opt/company/music/spotify-token.json"
CLIENT_ID = "8ecbe0880e6e40d187cbe0b177fb43e4"
PLAYLIST_NAME = "Erev Shabbos"
PLAYLIST_DESC = "150 heartfelt - Carlebach, Yehuda Green, Zusha, Eitan Katz, Shwekey and more."
TARGET = 150
PACE = 2.0
SEARCH_CAP = 210


def A(name, aliases, cap, songs):
    return {"name": name, "aliases": aliases, "cap": cap, "songs": songs}


# cap = slots this artist gets. `songs` is priority order AND the wanted list; a title that
# does not exist under that artist is simply skipped, and the next one takes the slot.
ARTISTS = [
 A("Shlomo Carlebach", ["shlomo carlebach"], 16, [
   "L'cha Dodi", "Bo'i V'shalom", "Mimkomcho", "Esah Einai", "Od Yishama", "Am Yisrael Chai",
   "Ki Va Moed", "Shalom Aleichem/Eyshet Chayil", "Haneshama Lach", "Nachamu Nachamu Ami",
   "Eliyahu Hanavi", "Mizmor Shir", "Shrei Shabbos", "Od Avinu Chai", "Ya Ribon Olam",
   "Ahavas Olam", "Meloch", "Yism'chu", "Melech Rachaman", "V'eneynu Tirena",
   "Pischu Li", "Kol Ha'olam Kulo", "Tov Lehodos", "Shabbos HaMalka", "Hinei Ma Tov"]),
 A("Yehuda Green", ["yehuda green"], 10, [
   "Nishmas Kol Chai", "Hashiveinu", "Nigun Moshe", "Rebi Rebi", "The Barditchever Nigun",
   "Bnei Beischa", "Reb Shlomo's Havdallah", "Yedid Nefesh", "Im Eshkachech", "Mimkomcha",
   "Shema Koleinu", "Haneshama", "Nigun Neshama", "Shuvu Eilai", "Aneinu Avinu",
   "Baruch Kel Elyon", "Vetaher Libeinu", "L'Dovid Mizmor", "Keil Adon", "Shiru LaMelech"]),
 A("Zusha", ["zusha"], 11, [
   "Lecha Dodi", "Pischu Li", "Yoel's Niggun", "Hareini Mechavein", "Baruch Hashem", "Shuva",
   "Karov", "Mi LaShem Elai", "All Worlds", "Ad Shetehe", "Melech Malchaya", "Ashrei",
   "Tree of Life", "Choose Life", "Everything Can Change", "Brighter", "Roof Over My Head",
   "From the Narrow Place"]),
 A("Eitan Katz", ["eitan katz"], 11, [
   "Ki Karov", "L'maancha", "Ashrey", "Ani L'dodi", "Yom Shabboson", "Podah B'Shalom",
   "Nigun Neshama", "The Dminor Nigun", "Barcheinu Avinu", "Karvah", "Achoseinu", "V'nacha",
   "Elul Nigun", "K'moifes", "Eishes Chayil", "Boruch Hu"]),
 A("Yaakov Shwekey", ["shwekey"], 8, [
   "Yedid", "Im Eshkocheich", "Shomaati", "Shema", "Malachim", "Rochem", "Tefilat Kallah",
   "Chasoif", "Elul", "Kolot", "Sameach"]),
 A("Yosef Karduner", ["karduner"], 7, [
   "Mikimi", "Hashem Melech", "Adon Olam", "Tzaddik Katamar", "Shir L'maalot",
   "V'taher Libeinu", "Kavei", "Shir LaMelech", "Mekimi"]),
 A("Thank You Hashem", ["thank you hashem", "tyh"], 6, [
   "Mizmor Letoda", "Hashivenu", "Spread Light", "Thank You Hashem", "Yismach Moshe",
   "Chassidus", "Father", "Stars", "Billionaire"]),
 A("Ishay Ribo", ["ishay ribo", "ריבו"], 7, [
   "הלב שלי", "זוכר אני", "הבוקר יעלה", "יגדל", "כל הזמן", "קול דודי", "בן אדם", "לולא היותך",
   "מקשה אחת זהב", "נפשי", "סיבת הסיבות"]),
 A("Avraham Fried", ["avraham fried"], 5, [
   "Shalom Aleichem", "Ani Maamin", "Modeh Ani", "Ribono Shel Olam", "Yevarechecha",
   "Tzomo Tzomo", "Avinu Malkeinu Medley", "Baishanim", "On Giants' Shoulders"]),
 A("Mordechai Ben David", ["mordechai ben david", "mbd"], 5, [
   "Tov Lehodos", "Yibane Hamikdash", "Hinei Mah Tov", "Moshaich", "Ashrei Ha'ish", "Rachem",
   "Muvdulim", "Lo Omus", "Machnisei Rachamim"]),
 A("Baruch Levine", ["baruch levine"], 5, [
   "Vezakeini", "Kavei", "Ki Anu Amecha", "Haneshomo", "Emes Malkeinu", "Chazeik",
   "Shema Koleinu", "Achas Shoalti", "Ochila La'kel"]),
 A("Benny Friedman", ["benny friedman"], 4, [
   "Tatty My King", "Toda", "Kulanu Nelech", "Kol Haneshama", "Homeward Bound",
   "Mamleches Kohanim", "Yama"]),
 A("Mordechai Shapiro", ["mordechai shapiro"], 5, [
   "L'chai Olamim", "Ein Od Milvado", "Avinu Malkeinu", "יש בי אמונה", "Lecha", "Ani Maa'min",
   "Hakol Mishamayim", "Machar", "B'yachad"]),
 A("Shlomo Katz", ["shlomo katz"], 4, [
   "Niggun of the Birds", "Kol Rina", "Nachamu", "An Everlasting Love", "Berosh Hashana"]),
 A("Meilech Kohn", ["meilech kohn"], 4, [
   "Hareyni", "Gedavent", "Yoimom", "Ein Trop Vaaser", "Likvod Shabbat", "VeUhavtu", "Menagen"]),
 A("Naftali Kempeh", ["kempeh"], 4, [
   "L'maancha", "Menucha V'simcha", "Ochila", "Anim Zmirot", "Lecha Dodi", "Kodesh",
   "Toameha", "V'chol Maminim", "Chamol"]),
 A("Shulem", ["shulem", "lemmer"], 3, [
   "October Rain", "Esa Einai", "Avinu Malkeinu", "Hineni", "Kol Zman"]),
 A("Akiva", ["akiva"], 3, ["Vehi She'amda", "יש בך הכל", "Irreversible", "ניגון השתטחות"]),
 A("Motty Steinmetz", ["steinmetz"], 3, [
   "Beshem Hashem", "כאייל תערוג", "אנא בכח", "K'ayal Ta'arog"]),
 A("Simcha Leiner", ["leiner"], 3, [
   "Tefilas Haneiros", "Mi Bon Siach", "Kol Hakavod", "Mi Adir", "Nafshi"]),
 A("Shmueli Ungar", ["ungar"], 3, ["Shulem", "Kol Dodi", "Bnei Heichala", "Mach A Bracha", "Koily"]),
 A("8th Day", ["8th day"], 3, [
   "It's Shabbos Now", "One of a Kind", "By My Side", "Slow Down", "Ya'alili"]),
 A("Joey Newcomb", ["joey newcomb"], 3, ["Thank You Hashem", "Toi'ameha", "Just Love Them"]),
 A("Shloime Gertner", ["gertner"], 3, ["Shabbos Hayom", "Kol Haolam", "Ata Echad", "Kodesh"]),
 A("Yonatan Razel", ["yonatan razel"], 2, ["והיא שעמדה", "אחת שאלתי", "קטנתי"]),
 A("Eli Schwebel", ["schwebel"], 2, ["Shabbos Takes Me Home", "Nodeh Lecha"]),
 A("Neshama Carlebach", ["neshama carlebach"], 2, [
   "B'shaim Hashem", "Ani Ma'amin", "Vaishmeru"]),
 A("Beri Weber", ["beri weber"], 2, ["Rabi Shimon", "ואני אבטח בך", "Didan Netzach"]),
 A("Ari Goldwag", ["goldwag"], 2, ["Am Echad", "Zeh Hazman", "Moshe"]),
 A("Ohad Moskowitz", ["ohad moskowitz"], 2, ["Malchutcha", "Etz Chaim", "Shalom Aleichem"]),
 A("Sruly Green", ["sruly green"], 2, ["מה רבו מעשיך", "Veiter", "ושמחת בחגך"]),
 A("Moshav Band", ["moshav"], 2, ["Lecha Dodi", "Come Be My Friend", "Breishit", "Shabbos"]),
 A("Yeedle", ["yeedle"], 1, ["Lev Echad", "Sma Beni", "Aneinu"]),
 A("Mendy Wald", ["mendy wald"], 1, ["Amcha"]),
 A("Miami Boys Choir", ["miami boys"], 1, ["Shabbos Medley", "Hinei Ma Tov", "V'nisgav"]),
 A("Chaim Dovid", ["chaim dovid"], 1, ["Yom Zeh Mechubad", "Bo'ee B'Shalom"]),
 A("Dedi", ["dedi"], 1, ["Moshiach", "Beni"]),
 A("Yitzchak Meir Helfgot", ["helfgot"], 1, ["Mizmor L'Dovid", "Le'olam Yehe Adam"]),
 A("L'Chaim OG", ["l'chaim og", "lchaim"], 1, ["Big Kedusha", "Shabbos"]),
 A("Yonina", ["yonina"], 1, ["Shalom Aleichem", "Bo'i Kallah"]),
 A("Freilach Band", ["freilach"], 0, ["S'ee Einayich"]),
]

TRIM_ORDER = [
 "Freilach Band", "Yonina", "L'Chaim OG", "Dedi", "Yitzchak Meir Helfgot", "Chaim Dovid",
 "Miami Boys Choir", "Mendy Wald", "Yeedle", "Moshav Band", "Sruly Green", "Ohad Moskowitz",
 "Ari Goldwag", "Beri Weber", "Neshama Carlebach", "Eli Schwebel", "Yonatan Razel",
 "Shloime Gertner", "Joey Newcomb", "8th Day", "Shmueli Ungar",
 "Simcha Leiner", "Motty Steinmetz", "Akiva", "Shulem", "Naftali Kempeh", "Meilech Kohn",
]


# --------------------------------------------------------------------------- plumbing
def access_token():
    tok = json.load(open(TOKEN))
    body = urllib.parse.urlencode({"grant_type": "refresh_token",
                                   "refresh_token": tok["refresh_token"],
                                   "client_id": CLIENT_ID}).encode()
    req = urllib.request.Request("https://accounts.spotify.com/api/token", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    r = json.load(urllib.request.urlopen(req, timeout=30))
    if r.get("refresh_token"):          # Spotify rotates it; persist or the chain dies
        tok["refresh_token"] = r["refresh_token"]
        tok["refreshed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(TOKEN, "w") as f:
            json.dump(tok, f)
        os.chmod(TOKEN, 0o600)
    return r["access_token"]


def api(path, at, method="GET", payload=None, tries=4):
    url = "https://api.spotify.com/v1" + path
    for attempt in range(tries):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + at, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body = e.read()[:400].decode("utf8", "replace")
            if e.code == 429:
                wait = int(e.headers.get("Retry-After") or 30)
                print(f"    429 limited, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            if e.code in (500, 502, 503) and attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            return {"__http": e.code, "__body": body}
        except Exception as e:                                   # noqa: BLE001
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            return {"__err": str(e)[:300]}
    return {"__err": "exhausted"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = re.sub(r"\([^)]*\)", " ", s)              # drop "(Live)", "(Ps. 122: 7)"
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = s.replace("'", "").replace('"', "").replace("`", "")
    s = s.lower()
    s = re.sub(r"[^0-9a-z\u0590-\u05ff ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def credit_of(t):
    return ", ".join(a["name"] for a in t.get("artists") or [])


def by_artist(blob, aliases):
    g = norm(blob)
    return any(norm(a) in g for a in aliases)


def title_hit(want, got):
    w, g = norm(want), norm(got)
    if not w or not g:
        return 0
    if w == g:
        return 100
    if w in g or g in w:
        return 85
    r = difflib.SequenceMatcher(None, w, g).ratio()
    if r >= 0.80:
        return int(70 + 10 * (r - 0.80) / 0.20)
    wt, gt = set(w.split()), set(g.split())
    if wt and gt and len(wt & gt) / len(wt) >= 0.66:
        return 60
    return 0


# --------------------------------------------------------------------------- catalogue
def cmd_catalogue():
    at = access_token()
    cat = json.load(open(CAT)) if os.path.exists(CAT) else {}
    spent = 0
    for art in ARTISTS:
        if art["cap"] == 0:
            continue
        if art["name"] in cat and cat[art["name"]].get("done"):
            print(f"cached  {art['name']} ({len(cat[art['name']]['tracks'])})", flush=True)
            continue
        want_pages = 4 if art["cap"] >= 4 else 3
        tracks, seen, done = [], set(), False
        queries = [f'artist:"{art["name"]}"'] + [f'artist:"{a}"' for a in art["aliases"]]
        for q in queries:
            if done:
                break
            for page in range(want_pages):
                if spent >= SEARCH_CAP:
                    done = True
                    break
                r = api("/search?q=" + urllib.parse.quote(q) +
                        f"&type=track&limit=10&offset={page*10}", at)
                spent += 1
                items = ((r.get("tracks") or {}).get("items") or []) if "__http" not in r else []
                if not items:
                    done = True
                    break
                for t in items:
                    if t["id"] in seen or not by_artist(credit_of(t), art["aliases"]):
                        continue
                    seen.add(t["id"])
                    tracks.append({"title": t["name"], "credit": credit_of(t),
                                   "uri": t["uri"], "id": t["id"],
                                   "album": (t.get("album") or {}).get("name")})
                if len(items) < 10:
                    done = True
                    break
                time.sleep(PACE)
            time.sleep(PACE)
        cat[art["name"]] = {"tracks": tracks, "done": True}
        with open(CAT, "w") as f:
            json.dump(cat, f, ensure_ascii=False, indent=1)
        print(f"paged   {art['name']}: {len(tracks)} tracks "
              f"({', '.join(t['title'] for t in tracks[:6])}...)", flush=True)
        time.sleep(PACE)
    print(f"\ncatalogue done: {len(cat)} artists, "
          f"{sum(len(v['tracks']) for v in cat.values())} tracks, {spent} searches this run")


# --------------------------------------------------------------------------- top-up
# The `artist:` field filter under-returns badly for split catalogues (measured 2026-10-30:
# "Yaakov Shwekey" 5 tracks across three artist ids, "Naftali Kempeh" 0, Carlebach 48 of a
# catalogue in the hundreds). A plain-keyword query pages deeper, and the local artist filter
# keeps the bleed out. Hebrew aliases exist because the credit is often the Hebrew spelling.
EXTRA_ALIASES = {
    "Naftali Kempeh": ["קמפה"], "Ishay Ribo": ["ריבו"], "Yaakov Shwekey": ["שוואקי"],
    "Yehuda Green": ["גרין"], "Meilech Kohn": ["קאהן"], "Motty Steinmetz": ["שטיינמץ"],
    "Baruch Levine": ["לוין"], "Shulem": ["למר"], "Akiva": ["עקיבא"],
    "Ohad Moskowitz": ["מוסקוביץ"], "Simcha Leiner": ["ליינר"], "Beri Weber": ["וובר"],
    "Shlomo Carlebach": ["קרליבך"], "Mordechai Shapiro": ["שפירא"], "Avraham Fried": ["פריד"],
}
TOPUP = [
 ("Shlomo Carlebach", "Shlomo Carlebach"), ("Shlomo Carlebach", "Carlebach Shabbos"),
 ("Yehuda Green", "Yehuda Green"), ("Yaakov Shwekey", "Yaakov Shwekey"),
 ("Naftali Kempeh", "Naftali Kempeh"), ("Naftali Kempeh", "נפתלי קמפה"),
 ("Thank You Hashem", "Thank You Hashem"), ("Ishay Ribo", "Ishay Ribo"),
 ("Baruch Levine", "Baruch Levine"), ("Mordechai Ben David", "Mordechai Ben David"),
 ("Simcha Leiner", "Simcha Leiner"), ("Shulem", "Shulem Lemmer"),
 ("Akiva", "Akiva"), ("Ari Goldwag", "Ari Goldwag"), ("Moshav Band", "Moshav Band"),
 ("Miami Boys Choir", "Miami Boys Choir"), ("Chaim Dovid", "Chaim Dovid"),
 ("Yonina", "Yonina"), ("Yeedle", "Yeedle"), ("Dedi", "Dedi Graucher"),
 ("Ohad Moskowitz", "Ohad Moskowitz"), ("Motty Steinmetz", "Motty Steinmetz"),
 ("L'Chaim OG", "L'Chaim OG"), ("Yitzchak Meir Helfgot", "Yitzchak Meir Helfgot"),
]


def cmd_topup():
    at = access_token()
    cat = json.load(open(CAT))
    spent = 0
    for name, query in TOPUP:
        art = next((a for a in ARTISTS if a["name"] == name), None)
        if not art:
            continue
        have = {t["id"] for t in cat.get(name, {}).get("tracks", [])}
        need = art["cap"] * 3 - len(have)
        if need <= 0:
            continue
        aliases = art["aliases"] + EXTRA_ALIASES.get(name, [])
        added = 0
        for page in range(4):
            if spent >= SEARCH_CAP:
                break
            r = api("/search?q=" + urllib.parse.quote(query) +
                    f"&type=track&limit=10&offset={page*10}", at)
            spent += 1
            items = ((r.get("tracks") or {}).get("items") or []) if "__http" not in r else []
            if not items:
                break
            for t in items:
                if t["id"] in have or not by_artist(credit_of(t), aliases):
                    continue
                have.add(t["id"])
                cat.setdefault(name, {"tracks": [], "done": True})["tracks"].append(
                    {"title": t["name"], "credit": credit_of(t), "uri": t["uri"],
                     "id": t["id"], "album": (t.get("album") or {}).get("name")})
                added += 1
            if len(items) < 10:
                break
            time.sleep(PACE)
        with open(CAT, "w") as f:
            json.dump(cat, f, ensure_ascii=False, indent=1)
        print(f"topup {name:22s} +{added:3d} -> {len(cat[name]['tracks'])}  ({query})", flush=True)
        time.sleep(PACE)
    print(f"\ntopup done: {spent} searches, catalogue now "
          f"{sum(len(v['tracks']) for v in cat.values())} tracks")


# --------------------------------------------------------------------------- hunt
# Songs that exist but that the paged catalogue never surfaced (Spotify's paged search
# returns a bounded slice of a large catalogue, and Carlebach's is hundreds of recordings).
# One targeted title query each; hits are merged into the catalogue permanently.
HUNT = [
 ("Shlomo Carlebach", "Pischu Li"), ("Shlomo Carlebach", "Kol Ha'olam Kulo"),
 ("Shlomo Carlebach", "Tov Lehodos"), ("Shlomo Carlebach", "Shabbos HaMalka"),
 ("Yehuda Green", "Baruch Kel Elyon"), ("Yehuda Green", "Vetaher Libeinu"),
 ("Yehuda Green", "L'Dovid Mizmor"), ("Yehuda Green", "Keil Adon"),
 ("Yehuda Green", "Shiru LaMelech"),
]


def cmd_hunt():
    at = access_token()
    cat = json.load(open(CAT))
    spent = 0
    for name, title in HUNT:
        art = next((a for a in ARTISTS if a["name"] == name), None)
        if not art:
            continue
        have = {t["id"] for t in cat.get(name, {}).get("tracks", [])}
        if any(title_hit(title, t["title"]) for t in cat.get(name, {}).get("tracks", [])):
            continue                                  # already have it
        aliases = art["aliases"] + EXTRA_ALIASES.get(name, [])
        found = 0
        for q in (title, f"{title} {name}"):
            r = api("/search?q=" + urllib.parse.quote(q) + "&type=track&limit=10", at)
            spent += 1
            for t in ((r.get("tracks") or {}).get("items") or []):
                if t["id"] in have or not by_artist(credit_of(t), aliases):
                    continue
                if not title_hit(title, t["name"]):
                    continue
                have.add(t["id"])
                cat.setdefault(name, {"tracks": [], "done": True})["tracks"].append(
                    {"title": t["name"], "credit": credit_of(t), "uri": t["uri"],
                     "id": t["id"], "album": (t.get("album") or {}).get("name")})
                found += 1
            time.sleep(PACE)
            if found:
                break
        print(f"hunt {name:20s} {title:22s} {'FOUND' if found else 'not on spotify'}",
              flush=True)
        with open(CAT, "w") as f:
            json.dump(cat, f, ensure_ascii=False, indent=1)
        time.sleep(PACE)
    print(f"\nhunt done: {spent} searches, catalogue {sum(len(v['tracks']) for v in cat.values())}")


# --------------------------------------------------------------------------- plan
def cmd_plan():
    cat = json.load(open(CAT))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    at = None
    hits, misses = {}, []
    spent = 0
    for art in ARTISTS:
        for song in art["songs"]:
            aliases = art["aliases"] + EXTRA_ALIASES.get(art["name"], [])
            pool = cat.get(art["name"], {}).get("tracks", [])
            best = None
            for t in pool:
                # re-check the credit here, not only when the catalogue was paged: the
                # catalogue is shared, and "Neshama Carlebach" must not fill Shlomo's slot
                if not by_artist(t["credit"], aliases):
                    continue
                s = title_hit(song, t["title"])
                if s and (best is None or s > best["score"]):
                    best = dict(t, score=s)
            if best is None and art["cap"] > 0:
                # not in the paged catalogue -> one targeted keyword search, cached forever
                key = art["name"] + "|" + song
                if key not in cache:
                    if at is None:
                        at = access_token()
                    if spent >= SEARCH_CAP:
                        cache[key] = {"score": 0, "note": "search cap"}
                    else:
                        r = api("/search?q=" + urllib.parse.quote(f"{song} {art['name']}") +
                                "&type=track&limit=10", at)
                        spent += 1
                        got = None
                        for t in ((r.get("tracks") or {}).get("items") or []):
                            if not by_artist(credit_of(t), aliases):
                                continue
                            s = title_hit(song, t["name"])
                            if s and (got is None or s > got["score"]):
                                got = {"score": s, "title": t["name"], "credit": credit_of(t),
                                       "uri": t["uri"], "id": t["id"],
                                       "album": (t.get("album") or {}).get("name")}
                        cache[key] = got or {"score": 0}
                        with open(CACHE, "w") as f:
                            json.dump(cache, f, ensure_ascii=False, indent=1)
                        time.sleep(PACE)
                c = cache.get(key) or {}
                if c.get("score"):
                    best = c
            if best:
                hits[(art["name"], song)] = best
            elif art["cap"] > 0:
                misses.append((art["name"], song))

    chosen, used = [], set()
    for art in ARTISTS:
        took, titles, skeletons = 0, [], set()
        for song in art["songs"]:
            if took >= art["cap"]:
                break
            b = hits.get((art["name"], song))
            if not b or b["uri"] in used:
                continue
            nt = norm(b["title"])
            # "Mikimi" and "Mekimi (Live)" are one song. Vowels are noise in transliteration,
            # so compare the consonant skeleton too — similarity alone scores it only 0.67.
            sk = re.sub(r"[aeiou]", "", nt)
            if any(difflib.SequenceMatcher(None, nt, x).ratio() >= 0.85 for x in titles) or \
               (len(sk) >= 3 and sk in skeletons):
                continue
            titles.append(nt)
            if len(sk) >= 3:
                skeletons.add(sk)
            used.add(b["uri"])
            chosen.append({"artist": art["name"], "song": song, "title": b["title"],
                           "credit": b["credit"], "album": b.get("album"), "uri": b["uri"],
                           "score": b["score"]})
            took += 1
    for name in TRIM_ORDER:                       # overshoot -> drop lowest-value first
        while len(chosen) > TARGET:
            i = next((i for i, c in enumerate(chosen) if c["artist"] == name), None)
            if i is None:
                break
            chosen.pop(i)
    if len(chosen) < TARGET:                      # undershoot -> backfill from reserves
        for art in ARTISTS:
            for song in art["songs"]:
                if len(chosen) >= TARGET:
                    break
                b = hits.get((art["name"], song))
                if not b or b["uri"] in used:
                    continue
                used.add(b["uri"])
                chosen.append({"artist": art["name"], "song": song, "title": b["title"],
                               "credit": b["credit"], "album": b.get("album"), "uri": b["uri"],
                               "score": b["score"], "reserve": True})

    plan = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "searches": spent, "tracks": chosen, "misses": misses}
    with open(PLAN, "w") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    by = {}
    for c in chosen:
        by[c["artist"]] = by.get(c["artist"], 0) + 1
    print(f"=== PLAN {len(chosen)}/{TARGET} · {spent} new searches this run ===")
    for k in sorted(by, key=lambda x: -by[x]):
        print(f"  {by[k]:2d}  {k}")
    if misses:
        print(f"\n=== not found under that artist ({len(misses)}) ===")
        print("   " + "; ".join(f"{a}: {s}" for a, s in misses))
    if len(chosen) < TARGET:
        print(f"\n!! SHORT BY {TARGET - len(chosen)}")


# --------------------------------------------------------------------------- write
def cmd_write(dry):
    plan = json.load(open(PLAN))
    tracks = plan["tracks"][:TARGET]
    print(f"plan built {plan['built_at']}: {len(tracks)} tracks")
    if dry:
        for i, t in enumerate(tracks, 1):
            print(f"{i:3d}. {t['artist']} - {t['title']}  [{t['credit']}]")
        return
    at = access_token()
    me = api("/me", at)
    print("account:", me.get("display_name"), me.get("id"))
    pid = None
    for it in ((api("/me/playlists?limit=50", at).get("items")) or []):
        if it and it.get("name") == PLAYLIST_NAME:
            pid = it["id"]
    if pid:
        print(f"reusing playlist {pid}; clearing so a re-run refills")
        # Page until empty. Deleting shifts the offsets, so always ask for offset 0 again.
        # A single 100-item page here is what left this playlist holding 300 tracks on
        # 2026-10-30 when --write ran twice: 100 cleared, 150 appended, next run doubled it.
        total_cleared = 0
        while True:
            page = api(f"/playlists/{pid}/items?limit=100&offset=0", at)
            old = [i["item"]["uri"] for i in (page.get("items") or []) if i.get("item")]
            if not old:
                break
            # NOTE the asymmetry, measured 2026-10-30: POST /items takes {"uris":[...]},
            # but DELETE /items takes {"items":[{"uri":...}]}. Sending "uris" to DELETE
            # answers 400 "No uris provided", and the old /tracks path answers 403.
            r = api(f"/playlists/{pid}/items", at, "DELETE",
                    {"items": [{"uri": u} for u in old]})
            if "__http" in r or "__err" in r:
                print("CLEAR FAILED", r)
                return
            total_cleared += len(old)
        print(f"cleared {total_cleared}")
    else:
        c = api("/me/playlists", at, "POST",
                {"name": PLAYLIST_NAME, "description": PLAYLIST_DESC, "public": False})
        if "__http" in c or "__err" in c:
            print("CREATE FAILED", c)
            return
        pid = c["id"]
        print(f"created {pid} public={c.get('public')}")
    uris = [t["uri"] for t in tracks]
    for i in range(0, len(uris), 100):
        r = api(f"/playlists/{pid}/items", at, "POST", {"uris": uris[i:i+100]})
        if "__http" in r or "__err" in r:
            print(f"ADD FAILED at {i}: {r}")
            return
        print(f"added {len(uris[i:i+100])}")
        time.sleep(1)

    got, offset = [], 0
    while True:
        page = api(f"/playlists/{pid}/items?limit=100&offset={offset}", at)
        items = page.get("items") or []
        if not items:
            break
        got.extend(i["item"] for i in items if i.get("item"))
        offset += len(items)
        if len(items) < 100:
            break
    print(f"\nREAD BACK: {len(got)} tracks")
    print("url: https://open.spotify.com/playlist/" + pid)
    uris_got = [t["uri"] for t in got]
    ok = len(got) == len(uris)
    dupes = len(uris_got) - len(set(uris_got))
    print(f"ASSERT expected={len(uris)} got={len(got)} duplicates={dupes} "
          f"-> {'PASS' if ok and dupes == 0 else 'FAIL'}")
    with open(os.path.join(HERE, "written.json"), "w") as f:
        json.dump({"playlist_id": pid, "count": len(got),
                   "tracks": [{"artist": credit_of(t), "title": t["name"], "uri": t["uri"]}
                              for t in got]}, f, ensure_ascii=False, indent=1)
    for i, t in enumerate(got, 1):
        print(f"{i:3d}. {credit_of(t)} - {t['name']}")


if __name__ == "__main__":
    if "--catalogue" in sys.argv:
        cmd_catalogue()
    elif "--topup" in sys.argv:
        cmd_topup()
    elif "--hunt" in sys.argv:
        cmd_hunt()
    elif "--plan" in sys.argv:
        cmd_plan()
    elif "--write" in sys.argv:
        cmd_write("--dry-run" in sys.argv)
    else:
        print(__doc__)
