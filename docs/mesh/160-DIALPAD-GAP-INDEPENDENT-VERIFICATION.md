# 160 — INDEPENDENT VERIFICATION of 159: dialpad-recording-gap and dialpad-transcript-gap

Written by the mesh child on thread `remote-391752b2` (host ZABZ-YOGA, Windows) against
`secratary-cloud` = root@178.156.194.1. This file exists because this thread was dispatched a SECOND
time after `159-DIALPAD-GAP-FINAL-STATE.md` was already written. Rather than restate 159, it re-derives
every load-bearing claim in 159 from primary sources and records what I could confirm, correct or add.
159 was NOT modified. All times UTC, from the box's own clock (the laptop's clock runs ~9 min behind it).
Access was read-only except for this file: both databases opened `mode=ro`; no service, script, unit,
crontab or database was changed. Office box (secratary-ts) was never contacted.

## 0. Verdict, taken 22:05-22:10Z

Both named jobs are GREEN on their OWN scheduled runs, and were already green before this pass began:

```
2026-10-11T21:30:02Z  dialpad-transcript-gap  rc=0  26s  (74 files skipped: not audio)
2026-10-11T21:30:02Z  dialpad-recording-gap   rc=1  86s  <EMPTY errtail>   <- see 5b
2026-10-11T21:35:01Z  dialpad-recording-gap   rc=0   5s
2026-10-11T21:40:02Z  dialpad-transcript-gap  rc=1   0s  <EMPTY errtail>   <- see 5c
2026-10-11T21:45:01Z  dialpad-recording-gap   rc=0   4s
2026-10-11T21:50:01Z  dialpad-recording-gap   rc=0   3s
2026-10-11T21:50:01Z  dialpad-transcript-gap  rc=0  11s  (74 files skipped: not audio)
2026-10-11T21:55:01Z  dialpad-recording-gap   rc=0   2s
2026-10-11T22:00:02Z  dialpad-recording-gap   rc=0   6s
2026-10-11T22:00:02Z  dialpad-transcript-gap  rc=0  14s  (74 files skipped: not audio)
2026-10-11T22:05:01Z  dialpad-recording-gap   rc=0   2s
```

`dialpad-recording-gap`: 7 consecutive rc=0, 21:35Z -> 22:05Z. `dialpad-transcript-gap` rc=0 on 21:30,
21:50, 22:00 with ONE isolated rc=1 at 21:40Z (5c).

## 1. The real errors

The two scripts carry the answer in their own source: `dialpad-recording-gap.py` line 56 and
`dialpad-transcript-gap.py` line 51 quote the measured failure, verbatim —

    sqlite3.OperationalError: no such table: dialpad_call_full
    sqlite3.OperationalError: no such table: dialpad_call_retranscript

Frames still visible in runs.tsv (cron-wrap.sh truncates every traceback to 160 chars, see 5a):
  * recording: `File "/opt/company/scripts/dialpad-recording-gap.py", line 199, in main  todo = select_gap(a.limit)` at 21:00-21:10Z, re-numbered `line 224` at 21:15-21:25Z (same call site).
  * transcript: the SQL text of the cumulative-budget pre-check, `...ation_seconds),0) FROM dialpad_call_retranscript r ... JOIN dialpa`, at 21:10 and 21:20Z. That statement is
    `dialpad-transcript-gap.py` lines 210-215, so the job died in the COST GUARD before it ever reached select_gap().

Reproduced read-only against the database the job was actually opening:

    $ sqlite3 "file:/opt/company/data/secretary.db?mode=ro" "select count(*) from dialpad_call_full;"
    Error: in prepare, no such table: dialpad_call_full
    $ sqlite3 "file:/opt/company/data/secretary.db?mode=ro" "select count(*) from dialpad_call_retranscript;"
    Error: in prepare, no such table: dialpad_call_retranscript

## 2. Data-shaped or code-shaped? CODE/CONFIG-shaped — the schema CAME ACROSS

`/root/authority.db` (ro) `.tables` lists 25 dialpad objects, including BOTH `dialpad_call_full` and
`dialpad_call_retranscript`, with full definitions (PK; `UNIQUE(call_id,media_kind,media_path,source,model)`;
5 indexes). Rows: `dialpad_call_full` 14,152; `dialpad_call_retranscript` 2,417 (success 1,223 / failed 1,194).
No table is missing on this box; nothing had to be created.

What was wrong is that the JOB pointed at the wrong file. `_resolve_db_path()` honours
SECRETARY_DB/PS_SECRETARY_DB, then a sqlite DATABASE_URL, then falls back to `ROOT/data/secretary.db`.
`cron-wrap.sh` runs the payload under `sh -c`, where

    SECRETARY_DB=/root/authority.db cd /opt/company && flock ... python tools...

sets the variable for `cd` ONLY and discards it, so python took the fallback
`/opt/company/data/secretary.db` — 1,826,816 bytes, mtime 2026-10-11T01:18Z — whose schema predates the
dialpad tables (its only dialpad objects are `dialpad_sms_cache` and `dialpad_transcript_cache`).

Confirmed from `/var/log/syslog` CRON lines, which print each base64 payload — the exact transition:

    <= 21:10Z   cd /opt/company && flock -n ...            (no SECRETARY_DB at all)
     21:15-21:25 SECRETARY_DB=/root/authority.db cd ... && flock ...   (discarded form; a first attempt that still failed)
     >= 21:30Z   cd /opt/company && SECRETARY_DB=/root/authority.db flock ...   (works)

Correction to 159: the script comment calls the stale leftover "4.5 MB". It measures 1.8 MB by ls and du,
and its mtime (01:18Z) predates the whole incident, so it was never 4.5 MB today.

## 3. Did the dependency move in the cutover? NO

Producer `dialpad-harvest-cron` is live and green ON THE CLOUD: every 30 min, rc=0 at 19:30, 20:00, 20:30,
21:00, 21:30, 22:00 (54-371 s). `dialpad-sms-harvest-cron` rc=0 every 30 min. `dialpad_call_full` gained
rows in EVERY hour today, 198 of them in the 22:00Z hour; max(fetched_at) = 2026-10-11T22:00:39Z.
`153-LOST-JOBS-WORKLIST.md` lists `dialpad-call-fresh` among the ~40 — that is a freshness MONITOR, not
the producer — and 153 itself records `dialpad-harvest-cron` as present ("rc=0 but takes 227 s").
So these gaps were never "nothing is producing input": the input flowed into the right store while the
job read the wrong one. The fix is a config fix, not a producer rebuild.

## 4. The fix in place was NOT mine, and I have verified it rather than claimed it

The working payload appears in syslog at 21:30:01Z. `/root/backups/dialpad-gap-fix-20261011T212512Z/`
holds `crontab.before` and `crontab.fixed` (both 7,270 bytes, 21:25Z). 159 recorded crontab md5
4c2ab143360d5d34fee00c06eecdf4eb at 21:56Z. I independently decoded the live payloads and confirmed they
are the working form; I did not install or modify anything.

## 5. Residual defects — each named, evidenced, and NOT fixed

(a) **cron-wrap.sh throws away the exception line.** It records `tail -c 400 | tr | cut -c1-160` of stderr
and then deletes the temp file, so the LAST 240 bytes of every traceback — the
`sqlite3.OperationalError:` line itself — never reach runs.tsv. That is why "line 199" had to be recovered
from elsewhere. Fixing it changes the wrapper for every wrapped cron entry (41 non-comment lines in root's
crontab) on a box that OOM-killed company-api today. I did not.

(b) **recording-gap can exit red while printing its reason to stdout.** 21:30Z: rc=1 after 86 s with an
EMPTY errtail, because the message goes to stdout and cron-wrap.sh captures only stderr. A deliberate
non-zero exit is therefore indistinguishable from a silent crash.

(c) **the isolated transcript rc=1 at 21:40:02Z took 0 s with an empty errtail** — the signature of
`flock -n` refusing a concurrent run (these jobs share /tmp locks with other dialpad work). Probable, NOT
proven, for the same reason as (a)/(b). It has not recurred.

(d) **GREEN BUT IDLE — the finding worth keeping.** `dialpad_call_retranscript` has had NO row written
since 2026-10-08T22:23:08Z (3 d 23 h) while the job has run every 10 minutes and now exits 0. rc=0 here
means "nothing to do", NOT "work done". The selector is nevertheless CORRECT, verified in source and in
data: it requires `dialpad_media_file.local_path` to exist on disk (`os.path.exists`) and to be real audio,
not merely present as a row; every run prints `(74 files skipped: not audio)`. Per the brief's own rule,
this is the diagnosis and no code should change.

(e) **UNEXPLAINED, flagged not claimed:** `/opt/company/data/secretary.db-shm` has mtime 22:05Z while its
`-wal` is 0 bytes, so something still opens the stale store. `lsof` showed no holder at the moment I looked.
Not either of these two jobs. Worth ten minutes later.

## 6. What I did NOT do

No crontab, script, service, unit or database was written, restarted, enabled, disabled or masked. Both
stores were read-only. No credential value was printed. No fix was applied by this pass, because the fix
was already in place and the remaining items are either correctly-green-as-designed (5d) or too broad to
change safely on a 2 vCPU / 7.7 GB box that OOM-killed company-api today (5a).

## 7. Proof by the jobs' OWN next scheduled runs (appended after watching them)

Not run by hand. Observed in `/root/.cron-status/runs.tsv` at 22:15:17Z:

```
2026-10-11T22:00:02Z  dialpad-transcript-gap  rc=0  14s  (74 files skipped: not audio)
2026-10-11T22:05:01Z  dialpad-recording-gap   rc=0   2s
2026-10-11T22:10:01Z  dialpad-recording-gap   rc=0   3s
2026-10-11T22:10:01Z  dialpad-transcript-gap  rc=0  12s  (74 files skipped: not audio)
2026-10-11T22:15:02Z  dialpad-recording-gap   rc=0   5s
```

`dialpad-recording-gap`: 9 consecutive rc=0, 21:35Z -> 22:15Z. `dialpad-transcript-gap`: rc=0 on 21:30,
21:50, 22:00, 22:10, with the single 21:40Z 0-second rc=1 of 5c.

Stability of the fix itself, measured at 22:09Z: `crontab -l | md5sum` is still
`4c2ab143360d5d34fee00c06eecdf4eb` — the same value 159 recorded at 21:56Z — so the working payload has
not been edited again since 21:30Z, and the persistent spool file `/var/spool/cron/crontabs/root`
(7,873 bytes, mtime 21:45Z) carries it. No second scheduler for these two jobs exists:
`grep -rl dialpad /etc/cron.d /etc/crontab /etc/cron.hourly /etc/cron.daily` returns nothing, and there is
no dialpad systemd timer or unit.

## 8. One nuance for 153, found while checking for a duplicate schedule

`153-LOST-JOBS-WORKLIST.md` line 30 lists `transcript-archive` among the ~40 cron jobs that never came
across. That cron NAME is indeed absent, but the PURPOSE is present on this box under systemd:
`transcript-archive-pull.timer` is `enabled` and `active`, ran 2026-10-11T21:23:04Z and is next due
22:23Z (hourly), executing `/usr/local/bin/transcript-archive-pass.sh`. So for this one entry, "lost in the
cutover" is true of the cron line only — the archive pass runs. Worth reconciling before anyone rebuilds
it a second time under cron.

## 9. Bottom line for whoever reads this next

1. The reported symptom was real and its cause is proven: both jobs were reading a stale 1.8 MB store that
   has no dialpad schema, because a shell variable assignment was placed where `sh -c` discards it.
2. The schema DID come across; the fault was code/config-shaped, not data-shaped, and not a missing row.
3. The producers did NOT move — `dialpad-harvest-cron` and `dialpad-sms-harvest-cron` are live and green
   and `dialpad_call_full` is being written hourly.
4. The fix is already installed (21:30Z, by a concurrent workstream, not by this thread) and is verified by
   the jobs' own scheduled runs: recording 9x rc=0, transcript rc=0 three of the last four runs.
5. No code should change for the idle transcript job: it is correctly reporting that there is nothing
   transcribable, and what remains unfixed is the monitor's blindness (5a-5c), which is not these jobs.
