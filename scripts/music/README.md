# music curator

The owner's daily playlist. Built 2026-10-21 from a conversation with him; every number in it is
quoted from his answers and stored in the `prefs` table, not in this file and not in the code.

**What it does:** once a day it assembles 100 tracks to his stored spec, writes them into one private
Spotify playlist (`Daily for Zabz`, id `7ln4sb9XuMXy4Q5zMIIjyn`), and watches what he actually plays
so the next build is better than the last.

---

## Where it runs

| piece | path on `secratary-cloud` | when |
|---|---|---|
| builder | `/opt/company/music/build_v2.py` | cron `30 13 * * *` UTC = **09:30 Eastern** |
| learning | `/opt/company/music/learn.py` | cron `0 13 * * *` — runs before the builder, writes `weights` |
| play poller | `/opt/company/music/poll.py` | cron `*/30` — Spotify only ever returns the last 50 plays |
| skip sampler | `/opt/company/music/sampler.py` | cron `* * * * *` — infers skip vs completion |
| snapshot | `/opt/company/music/snapshot.sh` | cron `5 4` — local + offsite-staged copy, 14-day rotation |

The authority is WRITABLE (the sole writer of `authority.db`); the office box `secratary` is the
frozen rollback anchor and is not involved in any of this.

The repo copy of these three scripts is the source of truth. Deploy with:

```bash
scp scripts/music/{poll,sampler,build_v2}.py secratary-cloud:/opt/company/music/
ssh secratary-cloud 'chmod 700 /opt/company/music/*.py'
```

## The spec — everything here came from him

| pref | value | his words |
|---|---|---|
| `daily_composition` | 100 = 50 familiar + 35 adjacent new + 10 one-genre-over + 5 way out | "50 new 50 familiar" |
| `familiar_artist_definition` | >= 3 distinct tracks played, last play within 90 days | "only familiar if i play a few of their songs, not just one" |
| `familiar_max_played_7d` | 2 | "only 2 that played in the last 7" |
| `familiar_max_played_21d` | 10 | "only 10 songs that played in the last 21 days" |
| `familiar_remainder` | deep cuts by those artists, or tracks last played 21+ days ago | "the rest can either be before 21 days or very similar songs from the same artists" |
| `novelty_ratio` | 0.50 | "50 new 50 familiar" |
| `new_adjacent` / `new_step_out` / `new_wild` | 35 / 10 / 5 | "35 adjacent 10 step one genre over and 5 way out there" |
| `jewish_share` | 15 of 100 | "it should probably be about 15 percent of the songs" — confirmed as an evening mood too |
| `order_policy` | none — do not sequence | "i shuffle it" |
| `exclusions_policy` | none | "don't ditch anybody" |
| `familiar_pool` | derived from plays, 90-day rolling | "over time as you introduce me to new things my familiar artists will change" |
| `skip_drivers` | 1 tempo, 2 recognition | "tempo then recognition i think" |
| `daytime_lane` | office account (Duo second seat) plays jewish music all day for customers; not this account | "the office spotify which is only jewish music to keep customers happy" |
| `playlist_scope` | evening / personal only | "it's mostly at night" |
| `rebuild_policy` | owner decides when it rebuilds | "don't rebuild it after every answer" |

Directions chosen by the agent after he said "you decide": americana fills the 10 step-outs
(Zach Bryan, Tyler Childers, Noah Kahan), neo-soul/jazz-vocal fills the 5 wild (Leon Bridges,
Michael Kiwanuka, Black Pumas, Yola, Durand Jones).

## How it gets better — `learn.py` and the `weights` table

`learn.py` runs before the builder and turns behaviour into numbers. It knows three things and
deliberately ignores everything else:

1. **closed listen verdicts** — `completed` +1.0, `partial` +0.3, `skipped` -0.7, per artist;
2. **a track deleted from the playlist that was never played since we served it** — a real negative;
3. **bucket yield** — of the N tracks served in a bucket, how many were played *after* serving.

It never treats "not reached" as a rejection. That is the owner's explicit rule: a track he never got
to was not disliked, so it carries no signal at all.

Output is `weights(key, value, updated_at, why)`, where `why` holds the raw counts so a score can be
audited instead of trusted. The builder reads it in one narrow way: an artist with two or more
observations and a score of -0.4 or worse is skipped **only if he does not already play that artist**.
His answer to exclusions was "don't ditch anybody", so no familiar artist is ever dropped on the
strength of two skips.

Day one is honestly empty: one closed listen (a skipped track), every bucket at 0/N.

## Data model (`taste.db`)

- `plays(track_id, played_at, artist, title, context, source, captured_at)` — unique on
  `(track_id, played_at)`. The only complete record of his history: the API shows 50 plays and no more.
- `listens(track_id, artist, title, device, started_at, last_seen, max_progress_ms, duration_ms, ended_at, verdict)`
  — the sampler's reconstruction. `verdict` is `completed` (>=92% of duration), `skipped` (<35%),
  `partial`, or `unknown`.
- `runs(id, kind, created_at, playlist_id, prompt, n_tracks, note)` — one row per build.
- `served(run_id, track_id, served_at, artist, title, src)` — exactly what was put in front of him,
  with its bucket. This is what makes "did it work" answerable later.
- `prefs(key, value, updated_at, source)` — the spec above. The builder reads it at runtime; change a
  preference here, not in the code.
- `lane_artists(artist, lane)` — the jewish-lane seed list.
- `cache` / `resolve_cache` — MusicBrainz MBIDs and ISRC -> Spotify track ids, so resolution is paid for once.

## Auth — how to re-authorise when it eventually breaks

App: "personal playlist curator", client id `8ecbe0880e6e40d187cbe0b177fb43e4`, PKCE only.
**No client secret is stored anywhere and none is needed.** Redirect URI is
`http://127.0.0.1:8888/callback` (Spotify rejects `localhost`; loopback IP only).

The flow: generate a verifier + S256 challenge, open
`https://accounts.spotify.com/authorize?...scope=...&code_challenge_method=S256`, catch the code on a
loopback listener, exchange it at `/api/token`. Scopes in use:
`user-read-playback-state user-read-currently-playing user-read-recently-played user-top-read
user-library-read user-library-modify user-follow-read playlist-read-private playlist-read-collaborative
playlist-modify-private playlist-modify-public`.

Deliberately NOT requested: `user-modify-playback-state` — nothing here needs to pause or skip his music.
Refresh tokens live 180 days but are refreshed on every use, so the loop keeps it alive while it runs.

## Failure modes already met — read before debugging

- **429** — a few hundred requests in a burst trips it. Both scripts honour `Retry-After`; a sampler
  that dies on 429 looks like a broken feature.
- **403 `Insufficient client scope`** on `GET /me/playlists` means `playlist-read-private` is missing.
- **Feb 2026 API changes**: playlist writes survive as `POST /me/playlists` and
  `POST|PUT /playlists/{id}/items`; the playlist **entry field is `item`, not `track`**;
  `GET /me` no longer returns `product` or `country`; search caps at 10 results per page.
- **Spotify `/audio-features` answers 403 for this app** — no tempo, energy or danceability. Tempo is
  learned from skip behaviour instead. AcousticBrainz is a frozen 2015–2022 archive with holes.
- **Deezer `/artist/{id}/top` does not include `isrc`** — the track object must be fetched per track.
  This cost a debugging round; do not "optimise" it away.
- **Deezer `rank`** (popularity, higher = more popular) is the only popularity signal available and is
  used to down-weight globally familiar tracks from unknown artists.

## Offsite — how the ledger actually leaves the box

**Corrected 2026-10-21 03:25Z.** An earlier version of this file said nothing shipped
`/opt/company/music` offsite and that the authority had no offsite path. Both statements were wrong,
and were made from one grep instead of a look at the timers.

What exists: **`authority-data-offsite.timer`** runs daily at ~06:37 UTC and archives
`/opt/company/data` to the R2 bucket `lpt-authority-backups` as
`authority/data/authority-data.tar.gz` (measured 2026-10-20T06:50Z: 4,051,091,403 bytes, 112,159
entries, upload rc=0), through boto3 with credentials at `/root/.lpt-r2.env` (mode 600). A separate
`authority-offsite-backup.timer` ships `/root/authority.db` itself.

So `snapshot.sh` writes its verified sqlite copy into **two** places: `/var/lib/authority-snapshots/music`
(local, fast restore) and **`/opt/company/data/music`** (rides tomorrow's archive to R2). Both are
pruned at 14 days. The archiver's own required-file assertion now includes `music`, so every daily run
prints `present: music` in `/var/log/authority-data-offsite.log` — coverage is asserted every day, not
remembered.

The token file is deliberately **not** staged there. A credential inside a tar on R2 is a leaked
credential; `auth.py` is the recovery path instead.

## Known gaps, stated so nobody assumes otherwise

1. **Offsite coverage of the ledger is one day old at worst, and was only wired on 2026-10-21.** The
   first archive containing `music/` is the 06:37 UTC run on 2026-10-21; before that date the ledger
   had no off-machine copy at all. Verify with
   `grep "present: music" /var/log/authority-data-offsite.log`.
2. **Adaptation exists but is data-starved.** `learn.py` writes weights nightly; with one closed
   listen the only weight so far is a single -0.70 for one artist, so the builder's choices are
   unchanged. It needs a week of listening before anything in it counts as evidence.
3. **The familiar half undershoots on a thin ledger.** With 7 familiar artists and a 6-deep-cuts
   cap, day one produced 38 familiar + 12 extra adjacent. It grows to 50 as the ledger fills.
4. **The step-out bucket started homogeneous** — all Tyler Childers on the first build. Seed order now
   rotates daily; the fix is in, the evidence is tomorrow's list.
5. **Carry-over is not implemented in v2.** v1 held unreached tracks over; the current builder
   assembles a fresh 100 each time. The spec is compatible with carrying over; the code is not there yet.
6. **Tempo cannot be measured.** Skip-driven learning is the substitute until a BPM source is added.
7. **`authority-data-offsite.sh --dry-run` still builds the whole 4 GB archive.** Run it without a
   generous timeout and you are left with a partial tar in `/var/tmp` — I did exactly that on
   2026-10-21 and had to clear 215 MB by hand. Kill it only via the timeout *after* checking
   `/var/tmp/authority-data-*.tar.gz`.
