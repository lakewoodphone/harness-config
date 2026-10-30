# The themed playlist builder — `shabbos_build.py`

Built 2026-10-30 for one request: *"150 song shabbos playlist for erev shabbos… Yehuda Green,
Carlebach, Zusha, Eitan Katz, some Shwekey, and way way more… nice and heartfelt and very vibey."*

**Result:** `Erev Shabbos`, id `43slSkE2pOzuF4KupljN5W`, 150 tracks, private, on the account the
app is authorised for (`eliyahu zabrowsky`, user `31ixcz…`). Verified by reading the playlist back
through a second, independent client — `total 150`, 150 listed, 150 distinct.

There is a second script, `shabbos_probe.py`, which dumps Deezer's per-artist top tracks. It exists
because Spotify removed `artist top-tracks` and the `popularity` field in the February 2026 purge,
so "what are this artist's real songs" cannot be asked of Spotify any more. Deezer answers it with
no key and no account.

---

## Why this is a separate tool from `build_v3.py`

`build_v3.py` is the daily engine and obeys `prefs`: 50 familiar / 35 adjacent / 10 step-out / 5
wild, a 21-day blacklist, an era floor of **1996**. None of that fits a themed Shabbos list — Reb
Shlomo Carlebach died in 1994, so the era floor deletes the well the playlist is drawn from. A
different brief gets a different tool rather than a flag on the daily one.

One `prefs` row *does* apply unchanged: `order_policy` — *"owner shuffles — track order is
irrelevant"*. So this playlist has no deliberate arc; the effort went into per-track choice.

## What the API actually allows — measured 2026-10-30

Every line here was run against the live API, because the February 2026 migration guide and the
2026-10-21 session disagree with reality in places.

| Call | Result |
|---|---|
| `q=track:"X" artist:"Y"` | **0 items.** The combined field filter is dead. An earlier version of this script was built on it and resolved 2 of 9. |
| `q=Lecha Dodi Carlebach` (plain keywords) | works, `total=305` |
| `q=artist:"Carlebach"` + `&offset=10,20` | works and pages — this is the removed `top-tracks` endpoint, reconstructed. ~40 ranked songs per artist. |
| `total` in a search response | **unreliable** — reported `0` on pages that returned 10 items. Never page on it; page until a page comes back short. |
| `POST /me/playlists` | works |
| `POST /playlists/{id}/items` `{"uris":[…]}` | works, 100 max per call |
| `DELETE /playlists/{id}/items` `{"items":[{"uri":…}]}` | works |
| `DELETE /playlists/{id}/items` `{"uris":[…]}` | **400 "No uris provided"** |
| `DELETE /playlists/{id}/tracks` | **403** — the old path is gone |
| `artist:` filter for split catalogues | under-returns badly: "Yaakov Shwekey" 5 tracks across three artist ids, "Naftali Kempeh" 0, Carlebach 48 |

The POST/DELETE asymmetry is the trap: the same endpoint takes `uris` to add and `items` to remove.

## Phases, and why it is not one shot

```
python3 shabbos_build.py --catalogue   # page each artist's ranked catalogue (cached forever)
python3 shabbos_build.py --topup       # plain-keyword pages for thin/split catalogues
python3 shabbos_build.py --hunt        # one targeted query per song the catalogue never surfaced
python3 shabbos_build.py --plan        # match wanted titles -> plan.json, touches nothing
python3 shabbos_build.py --write       # create/refill the playlist, then read it back
```

`--plan` writes nothing to Spotify on purpose: a bad match is inspectable before it reaches the
account. `--write` is idempotent **by name** — it reuses `Erev Shabbos` and clears it rather than
creating a second one.

### Cost

Search is the scarce resource: ~600 searches in 5 min earned a 12-hour app ban on 2026-10-26.
This build spent ~330 searches at 2 s pacing across all phases, well under that rate, and every
result is cached in `catalogue.json` / `resolve.json` so a re-run pays only for what changed.

## Four defects found by looking at the output, not by trusting it

1. **Wrong artist filled a slot.** Carlebach's alias `carlebach` matched *Neshama Carlebach*, so her
   `Esah Einai` sat in his 16. Fixed by requiring `shlomo carlebach` and by re-checking the credit at
   plan time, not only when the catalogue is paged.
2. **One song, two entries.** Karduner's `Mikimi` and `Mekimi (Live)` both landed. Fuzzy title
   similarity scores them 0.67, so the fix compares the **consonant skeleton** (`mkm` = `mkm`) —
   vowels are noise in transliteration.
3. **A classical arrangement crept in.** Razel's `Lekha dodi` resolved to a Benedetto Marcello
   chamber piece. Dropped the title from his wanted list.
4. **`--write` was not idempotent.** Running it twice left the playlist at 300 tracks, because the
   clear step deleted one 100-item page and then appended 150. The clear now pages at offset 0 until
   empty, and `--write` asserts `expected == got` and `duplicates == 0`.

## How to make the next one

Edit `ARTISTS` in `shabbos_build.py`: each entry is `(name, aliases, cap, [titles in priority
order])`. Hebrew titles work as-is; add a Hebrew alias when the credit is spelled that way
(`EXTRA_ALIASES`). Then run the five phases in order. Nothing else needs changing to produce a
different 150-track list from the same machinery.
