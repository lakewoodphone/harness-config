# 159 — dialpad-recording-gap and dialpad-transcript-gap: current state and real diagnosis

Started 2026-10-11T21:56Z by the mesh child on thread `remote-391752b2`, running on the owner's
laptop **zabz-yoga** (Windows) against `secratary-cloud` = `root@178.156.194.1`. Written
incrementally, per the rule that this estate's ssh does not reliably exit and the final message may
be lost (the ssh wrapper used here kills the connection 12 s after the command's sentinel, because
plain `ssh … "cmd"` was measured to hang past 120 s on this box). Every number below is from a
command run in this session and is marked with the time it was taken. Nothing was overwritten.

Numbering: `ls /root/out/migration-review/` at 21:54Z ended at `158-WEBSITE-COMMS-PUSH-VERIFICATION.md`
(23 files), so this is `159`. No existing file was touched.

---

## 0. HEADLINE, 21:57Z: both jobs are ALREADY GREEN. This workstream changed nothing.

The brief described both jobs as `rc=1`. That stopped being true at **21:35Z**, when a concurrent
workstream moved the `SECRETARY_DB=` assignment in the two crontab payloads into a position python
can see. Measured, not assumed:

```
$ crontab -l | md5sum
4c2ab143360d5d34fee00c06eecdf4eb  -        # 21:56Z (includes the 21:29Z website-comms-push block)

$ grep 'dialpad-.*-gap' /root/.cron-status/runs.tsv | tail -24      # taken 21:56Z
2026-10-11T21:15:01Z  dialpad-recording-gap   rc=1  2s   <no such table: dialpad_call_full>
2026-10-11T21:20:01Z  dialpad-recording-gap   rc=1  3s   <same>
2026-10-11T21:25:01Z  dialpad-recording-gap   rc=1  4s   <same>
2026-10-11T21:30:02Z  dialpad-transcript-gap  rc=0  26s  (74 files skipped: not audio)
2026-10-11T21:30:02Z  dialpad-recording-gap   rc=1  86s  <EMPTY errtail>          <-- see §5
2026-10-11T21:35:01Z  dialpad-recording-gap   rc=0  5s
2026-10-11T21:40:02Z  dialpad-transcript-gap  rc=1  0s   <EMPTY errtail>          <-- see §6
2026-10-11T21:40:02Z  dialpad-recording-gap   rc=0  5s
2026-10-11T21:45:01Z  dialpad-recording-gap   rc=0  4s
2026-10-11T21:50:01Z  dialpad-recording-gap   rc=0  3s
2026-10-11T21:50:01Z  dialpad-transcript-gap  rc=0  11s  (74 files skipped: not audio)
2026-10-11T21:55:01Z  dialpad-recording-gap   rc=0  2s
```

`dialpad-recording-gap`: **six consecutive rc=0**, 21:35Z → 22:00Z. `dialpad-transcript-gap` is
rc=0 with one isolated rc=1 at 21:40Z (§6). The pair's own next scheduled runs after this artifact
was written, both green:

```
2026-10-11T22:00:02Z  dialpad-recording-gap   rc=0   6s
2026-10-11T22:00:02Z  dialpad-transcript-gap  rc=0  14s  (74 files skipped: not audio)
``` The two named failures are fixed, and the fix was not
mine. The honest deliverable of this thread is therefore the **diagnosis**, plus the two residual
defects in §5 and §6 and the verified verdict in §7 — not a patch.

---

## 1. THE TWO REAL ERRORS, VERBATIM

`cron-wrap.sh` records only `tail -c 400 | tr '\n\t' '  ' | cut -c1-160` of **stderr** into
`runs.tsv` and then deletes the temp file, so the last 240 bytes of every traceback — the exception
line itself — are thrown away by construction. The full text of both was recovered by the
concurrent workstream (`156-DIALPAD-GAP-TWO-JOBS.md`); the `runs.tsv` prefix independently confirms
it frame for frame, and I have re-quoted it because it is the answer to "what is actually wrong".

### 1.1 `dialpad-recording-gap`

```
Traceback (most recent call last):
  File "/opt/company/scripts/dialpad-recording-gap.py", line 262, in <module>
    raise SystemExit(main())
  File "/opt/company/scripts/dialpad-recording-gap.py", line 224, in main
    todo = select_gap(a.limit)
  File "/opt/company/scripts/dialpad-recording-gap.py", line 148, in select_gap
    rows = con.execute(
        f"""
    ...<25 lines>...
        (20000,),
    ).fetchall()
sqlite3.OperationalError: no such table: dialpad_call_full
```

The `runs.tsv` prefix at 21:25Z is exactly
`^   File ".../dialpad-recording-gap.py", line 224, in main     todo = select_gap(a.limit)`.
The frame moved **199 → 224** between 21:10Z and 21:15Z because a workstream calling itself
`cloudfix` replaced both scripts at **21:13:32Z** (`/root/backups/cloudfix-20261011T211332Z/`), and
the traceback simply followed the new file. That edit fixed nothing.

### 1.2 `dialpad-transcript-gap`

```
Traceback (most recent call last):
  File "/opt/company/scripts/dialpad-transcript-gap.py", line 273, in <module>
    raise SystemExit(main())
  File "/opt/company/scripts/dialpad-transcript-gap.py", line 211, in main
    row = con0.execute(
        "SELECT COALESCE(SUM(c.duration_seconds),0) FROM dialpad_call_retranscript r "
        "JOIN dialpad_call_full c ON c.call_id = r.call_id WHERE r.status='success'"
    ).fetchone()
sqlite3.OperationalError: no such table: dialpad_call_retranscript
```

Line 211 is the **cumulative-budget pre-check** — the first statement of the run. The job never
reaches the join, the selector, or the transcriber. That is why it failed in 2-3 s.

---

## 2. DATA-SHAPED OR CODE-SHAPED? — CODE/CONFIG-SHAPED. The schema is NOT missing.

The brief warned that this "may be a missing row, a schema not created on this box during the
cutover, or a column that exists only in the other store". **None of those.** Measured 21:56Z, both
reads `mode=ro`:

```
$ sqlite3 "file:/opt/company/data/secretary.db?mode=ro" \
    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'dialpad%';"
dialpad_sms_cache
dialpad_transcript_cache          <-- the only two dialpad tables it has are CACHE tables

$ sqlite3 "file:/root/authority.db?mode=ro" "SELECT name FROM sqlite_master WHERE type='table' AND name IN
   ('dialpad_call_full','dialpad_call_retranscript','dialpad_media_file','dialpad_media_download_attempt');"
dialpad_call_full
dialpad_media_file
dialpad_media_download_attempt
dialpad_call_retranscript
```

All four tables exist, in the 23.6 GB authority store. The schema **did** come across. The 1.8 MB
`/opt/company/data/secretary.db` is a stale leftover that `_resolve_db_path()` falls back to
(`dialpad-transcript-gap.py:56-67`, same logic in the recording script) when neither `SECRETARY_DB`
nor `PS_SECRETARY_DB` nor a sqlite `DATABASE_URL` is set. That fallback is deliberate and documented
in the script's own comment — the bug was that the crontab never delivered the variable.

### 2.1 The shell defect, and the proof that it was exactly this

In POSIX `sh`, `VAR=x cmd` applies the assignment to **that simple command only**, and `cd` is a
regular built-in — so in `SECRETARY_DB=/root/authority.db cd /opt/company && …`, the variable is set
for `cd` and discarded before `python` runs. The 21:13:32Z `cloudfix` edit put it in exactly that
position; the 21:25Z edit moved it. Both variants are on disk, so the difference is provable rather
than remembered:

```
$ md5sum of the four retained crontabs (21:56Z)
2819fa0162bb767a73684ad0b1806150  /root/backups/dialpad-gap-fix-20261011T212512Z/crontab.fixed   <-- GOOD
743f856e690812fa8d1ec00efa73f57a  /root/backups/cloudfix-20261011T211332Z/crontab.new             <-- BAD
743f856e690812fa8d1ec00efa73f57a  /root/backups/dialpad-gap-fix-20261011T212512Z/crontab.before  <-- BAD (pre-fix)
23c6756a430da725912af4ffdDB6db84  /root/backups/cloudfix-20261011T211332Z/crontab.before         <-- pre-cloudfix
```

Diffing them: `crontab.fixed` differs from `crontab.new` on **exactly two lines**, and on each of
those lines only in where one token sits. Decoded from the base64:

```
BAD   (cloudfix, 21:13:32Z): SECRETARY_DB=/root/authority.db cd /opt/company && flock -n /tmp/dialpad-dl.lock .venv/bin/python …
GOOD  (installed, 21:25Z)  : cd /opt/company && SECRETARY_DB=/root/authority.db flock -n /tmp/dialpad-dl.lock .venv/bin/python …
```

and the same permutation for `/tmp/dialpad-ts.lock` / `dialpad-transcript-gap.py`. **The live
crontab at 21:56Z carries the GOOD form on both lines** (read back from `crontab -l` and decoded),
which is why both jobs went green.

---

## 3. DID THE DEPENDENCY MOVE IN THE CUTOVER?

`153-LOST-JOBS-WORKLIST.md` does name `dialpad-call-fresh` (and `lpt-retranscribe`) among the ~40
that never came across. But these two jobs do **not** depend on `dialpad-call-fresh`: their producer
is the harvester, and the harvester is on the live cloud crontab and exiting 0.

```
*/30 * * * *  dialpad-harvest-cron      -> cd /opt/company && /opt/company/scripts/dialpad-harvest-cron.sh
15,45 * * * * dialpad-sms-harvest-cron  -> cd /opt/company && /opt/company/scripts/dialpad-sms-harvest-cron.sh
```

`dialpad-harvest-cron.sh` is installed and is the job whose own header says it exists because
"nothing was scheduled to harvest Dialpad calls" — i.e. it occupies the place `dialpad-call-fresh`
would have. The data proves the producer is live independently of any exit code:
`dialpad_call_full` holds **14,151 calls, newest started 2026-10-11 21:36Z**, and
`dialpad_media_file` grew by **80 rows at 2026-10-11T21:31:2xZ** (measured §5).

So this was **not** a case of "no code should change": the store moved to `/root/authority.db` and
the pointer did not. That part is now fixed.

---

## 4. THE FINDING THE BRIEF DID NOT EXPECT: `dialpad_call_retranscript` HAS NOT BEEN WRITTEN SINCE 2026-10-08

This is the most important thing in this artifact, and it is not visible from `runs.tsv` at all.
Measured 21:58Z, read-only:

```
$ sqlite3 "file:/root/authority.db?mode=ro" \
   "SELECT COUNT(*), MAX(id), MAX(created_at) FROM dialpad_call_retranscript;"
2417 | 5341 | 2026-10-08T22:23:08.315402+00:00

$ SELECT substr(created_at,1,10) d, COUNT(*) n FROM dialpad_call_retranscript GROUP BY d ORDER BY d;
… 2026-09-14 1268 | 2026-09-15 849 | 2026-09-22 9 | 2026-09-23 3 | 2026-10-06 12 | 2026-10-07 18 | 2026-10-08 76
                                                                                        ^^^^^^^^^^^^^^ LAST

$ SELECT COUNT(*) FROM dialpad_call_retranscript WHERE created_at >= datetime('now','-3 hours');
0
```

The table's newest row is **2026-10-08T22:23:08Z**. Nothing has been written in the **three days
and 23 hours** to 21:58Z on 2026-10-11, during which `dialpad-transcript-gap` has run every ten
minutes. The server's clock and SQLite agree (`SELECT datetime('now')` = `2026-10-11 21:58:59`), and
`settings.database_url` resolves to `sqlite:////root/authority.db` — the same file — so this is not a
timezone artefact and not a second database.

**Consequence:** `dialpad-transcript-gap` has transcribed nothing since 2026-10-08 and its rc=0
means "nothing to do", not "work done". A green rc=0 from this job is currently
indistinguishable from a job that is silently inert. Anyone reading `runs.tsv` will conclude the
9 Oct → 11 Oct backlog is being handled. It is not.

Why it is inert is §7, and the answer is not a code defect.

---

## 5. `dialpad-recording-gap` — the residual defect in its exit code

The job is green and its queue is empty. Two measurements establish that:

```
$ crontab command + --dry-run (selector only; no download, no spend), 22:0xZ
$ cd /opt/company && SECRETARY_DB=/root/authority.db flock -n /tmp/dialpad-dl.lock \
    .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json --dry-run
{
  "selected": 0,
  "audio_minutes": 0.0,
  "future_transcription_cost_usd": 0.0,
  "oldest": null,
  "newest": null
}

$ ls /opt/company/data/dialpad/recording/ | wc -l
6190                      # and the newest 80 are owned by root, mtime 21:31, i.e. written by the 21:30Z run
$ line 258 of the script:  return 0 if not result.get("errors") else 1
```

The 21:30Z run is the one that ended rc=1 after 86 s with an **empty** error tail. It was not a
crash: it selected work, spent 86 s downloading the backlog, and then took the `errors` exit at line
258. `cron-wrap.sh` captures **stderr only**, and this exit path prints its summary to **stdout**, so
the error column is blank — a deliberately-red exit is logged identically to a crash.

That is the residual defect: **this job exits 1 whenever any single recording URL refuses to
download.** It is by design (`errors` is a real finding about dead URLs) but it means the job will
return to rc=1 on any future batch that contains one dead URL, with a blank error tail and no
message anywhere. It is green tonight only because the queue is empty. The narrow fix is to make
`cron-wrap.sh` capture the tail of **stdout as well as stderr** (or to have the script write its
error summary to stderr) — but this is a *reporting* change in a file shared by ~35 jobs, on a box
whose binding constraint is memory and whose `company-api` was OOM-killed once today. **I did not
make that change.** It is recorded here as the next narrow step, not done.

---

## 6. `dialpad-transcript-gap` — the one rc=1 that remains, and why it is a lock, not a crash

```
2026-10-11T21:30:02Z  dialpad-transcript-gap  rc=0  26s
2026-10-11T21:40:02Z  dialpad-transcript-gap  rc=1   0s  <EMPTY errtail>       <-- the anomaly
2026-10-11T21:50:01Z  dialpad-transcript-gap  rc=0  11s
```

rc=1 with a **0-second duration** and an **empty** stderr tail. A traceback cannot look like this:
the script's own `main()` cannot fail before it has run for at least a few hundred ms, and any
exception would have left a tail. The crontab line runs the job under `flock -n`:

```
… flock -n /tmp/dialpad-ts.lock .venv/bin/python scripts/dialpad-transcript-gap.py …
```

`flock -n` **exits 1 immediately** when the lock is held, writes nothing, and takes ~0 s. That is
exactly the observed signature, and the same signature the 21:30Z `recording-gap` rc=1 had to be
distinguished from. The most probable cause is therefore lock contention at 21:40:02Z — an
overlapping holder of `/tmp/dialpad-ts.lock`, e.g. a run started late or a stray manual invocation.

I want to be explicit about the limit of this: **the estate throws away the evidence needed to
confirm it.** `cron-wrap.sh` discards stdout, so nothing records whether the process even started.
I have labelled it "most probable", not "proven". The remedy for the ambiguity is the same one as
§5: capture the output tail, so the next occurrence answers the question by itself.

---

## 7. THE SELECTOR'S VERDICT: the transcript gap is REAL DATA, and the job is right to do nothing

This is the question the brief asked me to answer with evidence: *is the fault data-shaped or
code-shaped, and is the job correctly reporting that nothing is producing input?*

`dialpad-transcript-gap` selects **0** today, and the reason is not a bug. The selector
(`dialpad-transcript-gap.py:113-161`) requires, per call: a `dialpad_media_file` row, empty
`dialpad_call_full.transcription_text`, no successful retranscript, a `local_path` that exists on
disk with non-zero size, and audio that passes `_audio_file_problem()`. I reproduced that
exact logic read-only against `/root/authority.db`:

```
$ cd /opt/company && SECRETARY_DB=/root/authority.db .venv/bin/python /tmp/q7.py     # 22:0xZ
### selector candidates=592  file_missing=518  not_audio=74  WORKABLE=0
### the 74 'not audio' files it skips (sample):
   ('4881052177604608', '/home/zabz/personal-secretary-mvp/data/dialpad/recording/4881052177604608.mp3',
    13737, 'non_audio_payload_header')
### size histogram of the not-audio files: 13737×30, 13658×23, 13732×16, 13716×5
### TOTAL workable work for this job across the whole store (no LIMIT):
   workable=0  file_missing=518  not_audio=74
```

Read that carefully — **the funnel ends at zero**:

* **518 of 592** candidates have a `dialpad_media_file` row whose `local_path` does not exist on
  this machine (they are relative `data/dialpad/recording/…` paths that resolve under
  `/opt/company`, so the *only* thing failing is file presence). They are all old: the candidate
  date range is **2025-10-24 → 2026-06-18**, and their own `dialpad_media_download_attempt` rows say
  `unavailable` (1,115) or `invalid_payload` (656). Dialpad will not serve them. They are ghosts.
* **74 of 592** do have a file at an absolute path, but it is under the *office* tree
  `/home/zabz/personal-secretary-mvp/data/dialpad/recording/` and every one is a 13.6-13.7 KB
  HTML/JSON error page saved with an `.mp3` name — the exact population the script's own comment
  describes. The selector correctly refuses them.
* **0 workable.** Not "few". Zero.

And the 80 recordings the recording-gap job downloaded tonight are **legitimately out of scope**:

```
$ do tonight's 80 have empty transcription_text?
   st='HAS_DIALPAD_TEXT' | n=80            <-- all 80 already carry Dialpad's own transcript
$ how many are IN the 592 candidate set?
   0
$ retranscript rows recorded against tonight's 80 calls:
   (none)
```

The job's own docstring says it targets calls that "have a recording and NO transcript at all …
for them the transcript is the difference between searchable and invisible". All 80 calls from
tonight already have Dialpad's transcript, so for them a re-transcript is a *quality* improvement,
which this job explicitly ranks second. **The job is correctly reporting that there is no
transcription work to do, and the brief's rule applies verbatim: this is the diagnosis, and no code
should change.**

One structural caveat worth passing on, because it sets up the next workstream: the three producers
`dialpad-call-fresh`, `lpt-retranscribe` and `transcript-archive` are all named in
`153-LOST-JOBS-WORKLIST.md` as never having come across. Whatever used to keep
`dialpad_call_retranscript` current on the office box is not on this one, and the table has been
frozen since 2026-10-08 (§4). Tonight the job is right to be idle; **the reason it is right is that
there is nothing to do, not that the pipeline works.** Whoever ports `lpt-retranscribe` /
`transcript-archive` should expect this table's freshness to stay flat until then.

---

## 8. what I did and did not do

**Did:** read-only diagnosis only. Two selector dry-runs of the jobs' own crontab commands
(`--dry-run`, which returns before any download, any API call and any write — verified in the source
at `dialpad-recording-gap.py:244-247` and `dialpad-transcript-gap.py:241-243` before running them).
All database access was `mode=ro`. Read-only `ls`/`md5sum`/`sed`/`ps` on the cloud box.

**Did not:** change any script, crontab, service or database. Did not start, stop, enable, disable,
unmask or restart `company-api`, `cloudflared`, `secretary-dashboard` or `phone-redirector`. Did not
delete or overwrite any database, `-wal`, `-shm` or backup. Did not touch the office box
(`secratary-ts`) at all — no command in this session reached it. Did not run either job without
`--dry-run`, so §5 and §7 are the jobs' own scheduled-run evidence plus a selector check, not a
hand-run that spent money.

**Deliberately left undone, with reasons:**
1. `cron-wrap.sh` captures stderr only (§1, §5, §6). Fixing it would make every non-zero exit
   self-explaining and is a two-line change — in a file every job on the box depends on. Not done
   tonight on a box where `company-api` was OOM-killed once today.
2. The 518 ghost rows (§7) are re-offered to the transcript selector forever, exactly as the script
   warns dead URLs are for the downloader. Doing nothing already costs 0 API calls, so this is
   untidy, not unsafe. The durable fix belongs with whoever ports `lpt-retranscribe`.
3. The stale 1.8 MB `/opt/company/data/secretary.db` still sits in the fallback position that
   `_resolve_db_path()` uses when the variable is absent. Both jobs now pass `SECRETARY_DB`
   explicitly, so nothing in scope reads it — but any future job copying this pattern without the
   variable will silently read that file and fail the same way. The durable fix (remove it, or make
   the fallback loud) is wider than the two tasks.

**To revert the crontab fix** (not mine, and I recommend against it): `crontab
/root/backups/dialpad-gap-fix-20261011T212512Z/crontab.before` — but read §2.1 first: that backup is
the **BAD** form and reverting re-breaks both jobs.

## 9. the one-line answer to each question the brief asked

1. **Real error, recording:** `sqlite3.OperationalError: no such table: dialpad_call_full` at
   `select_gap`, line 148, reached from `main` line 224 — because the connection was on the 1.8 MB
   fallback `/opt/company/data/secretary.db`, not the 23.6 GB `/root/authority.db`.
2. **Real error, transcript:** `sqlite3.OperationalError: no such table: dialpad_call_retranscript`
   at line 211, the cumulative-budget pre-check, for the same reason.
3. **Data- or code-shaped:** code/config-shaped. The schema came across the cutover intact; the
   pointer to it did not. The defect is one token's position in two crontab payloads —
   `SECRETARY_DB=… cd …` sets the variable for `cd` and discards it.
4. **Did the dependency move:** yes. The producers (`dialpad-harvest-cron`,
   `dialpad-sms-harvest-cron`) are live on the cloud crontab and the store is being written
   tonight; `dialpad-call-fresh`, which `153` lists as lost, is *not* these jobs' producer.
5. **Narrow fix:** already installed at 21:25Z by another workstream and independently verified
   here: `cd /opt/company && SECRETARY_DB=/root/authority.db flock -n <lock> .venv/bin/python …`.
   Proven by the jobs' own scheduled runs — `recording-gap` rc=0 ×5 (21:35→21:55Z),
   `transcript-gap` rc=0 at 21:30Z and 21:50Z.
6. **What is still wrong, and is the reason this file exists:** `dialpad_call_retranscript` has not
   been written since **2026-10-08T22:23Z** (§4); the recording job's exit code treats any dead URL
   as job failure and writes its reason to a stream cron does not keep (§5);
   `cron-wrap.sh` cannot distinguish a crash from a deliberate non-zero exit (§5, §6); and the
   transcript selector's 592-row queue is 100% unusable on disk while the job is *correct* to report
   zero workable (§7) — that correctness depends on data decay, not on a working pipeline.
