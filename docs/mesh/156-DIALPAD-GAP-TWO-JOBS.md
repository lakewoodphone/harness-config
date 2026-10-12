# 155 — dialpad-recording-gap and dialpad-transcript-gap: live diagnosis

Written 2026-10-11 by the mesh child dispatched on this thread (host ZABZ-TECH, working on
`secratary-cloud` = root@178.156.194.1). Written **as the work happened**, per the rule that
this estate's ssh may never exit and the final message may be lost.

## 0. FIRST: A CONCURRENT WRITER IS ALREADY ON THESE FILES (read this before editing anything)

Measured at 2026-10-11T21:22Z and confirmed at 21:25Z:

```
2026-10-11 21:13:30.619717698 +0000 /root/deploy/dialpad-recording-gap.py
2026-10-11 21:13:30.819716541 +0000 /root/deploy/dialpad-transcript-gap.py
2026-10-11 21:13:32.571706409 +0000 /opt/company/scripts/dialpad-recording-gap.py
2026-10-11 21:13:32.576706381 +0000 /opt/company/scripts/dialpad-transcript-gap.py
```

A directory `/root/backups/cloudfix-20261011T211332Z/` was created at that same second and holds:

```
crontab.before          7182 bytes
crontab.new             7270 bytes
dialpad-recording-gap.py  10988 bytes  (mtime 2026-10-07 16:07, owner 1000:1000)
dialpad-transcript-gap.py 11494 bytes  (mtime 2026-10-07 16:07, owner 1000:1000)
```

So a workstream calling itself **cloudfix** had already, seven minutes before this thread
started, taken a crontab backup and replaced BOTH scripts. The prose copies it saved are dated
2026-10-07, not 2026-10-11 — i.e. the backup captured a *staged* pair, not the pair that was
live in `/opt/company/scripts` at 21:12:59Z. The live script's content at 21:12Z is therefore
**not preserved anywhere I could find**, which is itself a finding.

md5 of the file actually installed now vs. the cloudfix backup:

```
79e4d7d16ec53dedb36c9571741a1df3  /opt/company/scripts/dialpad-recording-gap.py   <-- live now
79e4d7d16ec53dedb36c9571741a1df3  /root/deploy/dialpad-recording-gap.py          <-- same
ac219dcea1249d9da04adf675c1c2e4a  /root/backups/cloudfix-20261011T211332Z/dialpad-recording-gap.py
```

**The cloudfix edit did not fix anything.** `/root/.cron-status/runs.tsv` after the change:

```
2026-10-11T21:10:01Z  dialpad-recording-gap  1  3  ... line 199, in main  todo = select_gap(a.limit) ...
2026-10-11T21:15:01Z  dialpad-recording-gap  1  2  ... line 224, in main  todo = select_gap(a.limit) ...
2026-10-11T21:20:01Z  dialpad-recording-gap  1  3  ... line 224, in main  todo = select_gap(a.limit) ...
```

`grep -n` on the file installed at 21:13:32 shows the frame the traceback names:

```
75:DB = _resolve_db_path()
125:def select_gap(limit: int, voicemail_first: bool = True) -> list[dict]:
214:def main() -> int:
224:    todo = select_gap(a.limit)
```

Line 224 is the current, post-cloudfix location of `todo = select_gap(a.limit)`; 199 was the
pre-cloudfix location. The traceback is *tracking the new file* and still failing at the same
statement. Whatever is raised is raised inside or under `select_gap`.

**Consequence for the rules I was given:** I am not the only writer on `scripts/dialpad-*.py`.
I will not overwrite either file until I can show the cloudfix workstream is done. Continue to
section 1 for the actual defects.

## 1. How the two jobs are actually invoked (decoded from root's crontab)

`crontab -l` lines 28-31, each wrapped in `/usr/local/bin/cron-wrap.sh <name> <base64>`:

```
*/30 * * * *  dialpad-harvest-cron        -> cd /opt/company && scripts/dialpad-harvest-cron.sh
15,45 * * * * dialpad-sms-harvest-cron    -> cd /opt/company && scripts/dialpad-sms-harvest-cron.sh
*/5  * * * *  dialpad-recording-gap       -> SECRETARY_DB=/root/authority.db cd /opt/company && \
                                             flock -n /tmp/dialpad-dl.lock .venv/bin/python \
                                             scripts/dialpad-recording-gap.py --limit 300 --json
*/10 * * * *  dialpad-transcript-gap      -> SECRETARY_DB=/root/authority.db cd /opt/company && \
                                             flock -n /tmp/dialpad-ts.lock .venv/bin/python \
                                             scripts/dialpad-transcript-gap.py --limit 400 \
                                             --retry-failed --max-minutes 600
```

The two producers above them — `dialpad-harvest-cron` and `dialpad-sms-harvest-cron` — are
**rc=0 and have been all evening** (e.g. 20:30Z rc=0 227 s, 21:00Z rc=0 57 s). See section 3
for whether they are the producers these two jobs actually depend on.

## 2. How errors are recorded (why the quoted error is truncated)

`cron-wrap.sh` runs the command under `sh -c` with **stderr redirected to a mktemp file**, then
writes one line to `runs.tsv`:

```
ERRTAIL="$(tail -c 400 "$ERRFILE" 2>/dev/null | tr '\n\t' '  ' | cut -c1-160)"
printf '%s\t%s\t%s\t%s\t%s\n' "$STAMP" "$NAME" "$RC" "$((END - START))" "$ERRTAIL" >> "$STATE_DIR/runs.tsv"
```

`tail -c 400` keeps the LAST 400 bytes of the traceback and `cut -c1-160` then shows only the
**first 160 of those 400** — so the line the traceback *ends* on, which is the actual exception,
is always the part that is thrown away. `runs.tsv` alone can never give the real error. The
full stderr is deleted (`rm -f "$ERRFILE"`) and the job's crontab line redirects nothing, so
the real error survives only wherever the script itself logs.

## 3. THE REAL ERRORS, VERBATIM

The truncated `runs.tsv` line can never show these (see §2). Both were reproduced by running
the job's **exact crontab command** with `--dry-run` appended, which stops after the selector
and downloads nothing.

### 3.1 `dialpad-recording-gap` — the actual traceback

```
$ sh -c 'SECRETARY_DB=/root/authority.db cd /opt/company && flock -n /tmp/dialpad-dl.lock \
         .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json --dry-run'
Traceback (most recent call last):
  File "/opt/company/scripts/dialpad-recording-gap.py", line 262, in <module>
    raise SystemExit(main())
                     ~~~~^^
  File "/opt/company/scripts/dialpad-recording-gap.py", line 224, in main
    todo = select_gap(a.limit)
  File "/opt/company/scripts/dialpad-recording-gap.py", line 148, in select_gap
    rows = con.execute(
           ~~~~~~~~~~~^
        f"""
        ^^^^
    ...<25 lines>...
        (20000,),
        ^^^^^^^^^
    ).fetchall()
    ^
sqlite3.OperationalError: no such table: dialpad_call_full
rc=1
```

This matches, frame for frame, the `runs.tsv` prefix
`File ".../dialpad-recording-gap.py", line 224, in main     todo = select_gap(a.limit)`
— including the 199→224 move, so the failing code path is unchanged by the cloudfix edit.

### 3.2 `dialpad-transcript-gap` — the actual traceback and the failing SQL

```
$ sh -c 'SECRETARY_DB=/root/authority.db cd /opt/company && flock -n /tmp/dialpad-ts.lock \
         .venv/bin/python scripts/dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600'
Traceback (most recent call last):
  File "/opt/company/scripts/dialpad-transcript-gap.py", line 273, in <module>
    raise SystemExit(main())
                     ~~~~^^
  File "/opt/company/scripts/dialpad-transcript-gap.py", line 211, in main
    row = con0.execute(
          ~~~~~~~~~~~~^
        "SELECT COALESCE(SUM(c.duration_seconds),0) FROM dialpad_call_retranscript r "
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        "JOIN dialpad_call_full c ON c.call_id = r.call_id WHERE r.status='success'"
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ).fetchone()
    ^
sqlite3.OperationalError: no such table: dialpad_call_retranscript
```

So the "SQL error joining `dialpad_call_retranscript`" is not a join defect, not a missing row,
and not a constraint violation. It is **`no such table`** — the statement is fine and the table
is fine; the connection is pointed at a database that has never had it. The join itself
(`select_gap`, lines 115-126) is:

```sql
SELECT c.call_id,
       COALESCE(c.duration_seconds, 0) AS duration_seconds,
       datetime(c.date_started_ms/1000,'unixepoch') AS started,
       COALESCE(m.local_path, '') AS local_path
FROM dialpad_call_full c
JOIN dialpad_media_file m ON m.call_id = c.call_id
     AND (m.kind LIKE 'recording%' OR m.kind = 'voicemail')
WHERE TRIM(COALESCE(c.transcription_text,'')) = ''
  AND NOT EXISTS (
        SELECT 1 FROM dialpad_call_retranscript r
        WHERE r.call_id = c.call_id AND r.status IN ('success','failed')
  )
ORDER BY c.date_started_ms DESC
LIMIT ?
```

## 4. DATA-SHAPED OR CODE-SHAPED? — CODE/CONFIG-SHAPED, and here is the proof

**Code-shaped.** Specifically a shell-semantics defect in the cron payload. Three measurements:

**(a) The database the job opens does not have the tables. The database that has them is a
different file.**

```
$ ls -la /opt/company/data/secretary.db*          # the fallback default in _resolve_db_path()
-rw-r--r-- 1 root root 1826816 Oct 11 01:18 /opt/company/data/secretary.db
-rw-r--r-- 1 root root   32768 Oct 11 21:20 /opt/company/data/secretary.db-shm
-rw-r--r-- 1 root root       0 Oct 11 06:31 /opt/company/data/secretary.db-wal

$ sqlite3 "file:/opt/company/data/secretary.db?mode=ro" \
    "SELECT name FROM sqlite_master WHERE type='table' AND name IN
     ('dialpad_call_full','dialpad_call_retranscript','dialpad_media_file','dialpad_media_download_attempt');"
                                   <-- EMPTY. It has only dialpad_sms_cache and dialpad_transcript_cache.

$ ls -la /root/authority.db
-rw-r--r-- 1 root root 24068325376 Oct 11 21:15 /root/authority.db

$ sqlite3 "file:/root/authority.db?mode=ro" \
    "SELECT name FROM sqlite_master WHERE type='table' AND name IN
     ('dialpad_call_full','dialpad_call_retranscript','dialpad_media_file','dialpad_media_download_attempt');"
dialpad_call_full
dialpad_media_file
dialpad_media_download_attempt
dialpad_call_retranscript
```

The schema **was** created on this box during the cutover. All four tables exist, in the
23.6 GB store, and `company-api` is actively writing it (mtime 21:15Z, mid-evening). Nothing is
missing from the cloud authority.

**(b) The environment variable cloudfix added to the crontab never reaches python.** This is the
whole defect. In POSIX `sh`, a variable assignment prefixed to a *simple command* applies to
**that command only**, and `cd` is a regular built-in, not a special one — so
`SECRETARY_DB=/root/authority.db cd /opt/company` sets the variable for `cd` and then discards
it. `python` in the next command of the `&&` list never sees it:

```
$ sh -c 'SECRETARY_DB=/root/authority.db cd /opt/company && .venv/bin/python -c \
         "import os;print(\"SECRETARY_DB seen by python:\", repr(os.environ.get(\"SECRETARY_DB\")))"'
SECRETARY_DB seen by python: None

$ sh -c 'cd /opt/company && SECRETARY_DB=/root/authority.db .venv/bin/python -c \
         "import os;print(\"SECRETARY_DB seen by python:\", repr(os.environ.get(\"SECRETARY_DB\")))"'
SECRETARY_DB seen by python: '/root/authority.db'
```

and therefore the module resolves the wrong store:

```
$ sh -c 'SECRETARY_DB=/root/authority.db cd /opt/company && .venv/bin/python -c "<load the script>; print(m.DB)"'
DB resolved to: /opt/company/data/secretary.db
```

`_resolve_db_path()` (lines 61-72 of both scripts) is correct and is doing exactly what it was
written to do: honour `SECRETARY_DB` first, then `DATABASE_URL`, then fall back to
`ROOT/data/secretary.db`. The variable is simply not in the environment, so the fallback is
taken every single run. This is the same trap in both jobs, from one flaw in one crontab edit.

**(c) Put the variable where python can see it and both jobs stop failing** — against the same
data, the same DB, the same scripts, nothing else changed:

```
$ sh -c 'cd /opt/company && SECRETARY_DB=/root/authority.db flock -n /tmp/dialpad-dl.lock \
         .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json --dry-run'
{
  "selected": 78,
  "audio_minutes": 168.0,
  "future_transcription_cost_usd": 1.01,
  "oldest": "2026-10-11 15:39:45",
  "newest": "2026-10-11 20:28:46"
}

$ sh -c 'cd /opt/company && SECRETARY_DB=/root/authority.db flock -n /tmp/dialpad-ts.lock \
         .venv/bin/python scripts/dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600 --dry-run --json'
  (74 files skipped: not audio)
{
  "selected": 0,
  "deferred_over_budget": 0,
  "audio_minutes": 0.0,
  "estimated_cost_usd": 0.0,
  "oldest": null,
  "newest": null
}
```

Both selectors run to completion. `recording-gap` finds **78 calls / 168 audio-minutes** waiting
to be downloaded. `transcript-gap` finds **0** — correctly, because its input is the output of
the recording leg, which has not been fetching. There is no data gap being reported wrongly and
no constraint being violated.

## 5. DID THE DEPENDENCY MOVE IN THE CUTOVER? — YES. The producers are on this box and green.

`153-LOST-JOBS-WORKLIST.md` does name `dialpad-call-fresh` in its list of the ~40 jobs that
never came across. But the two jobs in hand do **not** depend on it: their producers are the
harvesters, and both harvesters are on the live cloud crontab and exiting 0:

```
$ crontab -l | decode payloads
dialpad-harvest-cron      cd /opt/company && /opt/company/scripts/dialpad-harvest-cron.sh       rc=0  (227 s at 20:30Z, 57 s at 21:00Z)
dialpad-sms-harvest-cron  cd /opt/company && /opt/company/scripts/dialpad-sms-harvest-cron.sh   rc=0  (3 s at 20:15Z, 5 s at 20:45Z, 3 s at 21:15Z)
```

And the data proves it independently: `dialpad_call_full` holds 78 calls with a recording URL
and no local audio, and `dialpad_media_download_attempt` rows already exist to be joined. A job
that is "correctly reporting that nothing is producing input" would select 0 with the right DB
as well; `recording-gap` selects 78.

**So this is not a gap that should be left red, and it is not a case where no code should
change.** The dependency moved; the pointer to it did not.

### 5b. Proof the producer is live, independent of any cron exit code

`dialpad_call_full` in the authority store is being written *tonight*, minutes before this check:

```
$ sqlite3 "file:/root/authority.db?mode=ro" "SELECT COUNT(*), datetime(MAX(date_started_ms)/1000,'unixepoch') FROM dialpad_call_full;"
14133|2026-10-11 21:23:37
$ sqlite3 "file:/root/authority.db?mode=ro" "SELECT COUNT(*) FROM dialpad_media_file;"
7069
```

and the stale fallback store is not merely old, it is **empty of production data**:

```
$ sqlite3 "file:/opt/company/data/secretary.db?mode=ro" "SELECT COUNT(*) FROM dialpad_sms_cache;"
0                       <-- by contrast, /root/authority.db holds 135515 rows
```

A 1.8 MB file with 0 rows in the only dialpad table it has, sitting where a 24 GB store should
be, is what both jobs have been querying on every run.

## 6. THE FIX — narrowest form, and why it is unambiguous

The defect is not in either python script. `_resolve_db_path()` in both files is correct and
deliberate. The defect is that **the crontab payload puts the assignment where it decorates
`cd` instead of the job**, so the documented, intended mechanism never fires. The narrowest real
fix is to move one token in each of two crontab lines and change nothing else — no script edit,
no service restart, no database write, no change to the schedule, the limits, the lock files or
the `--json` flags.

**What changed (only the position of `SECRETARY_DB=…`):**

```
 OLD: SECRETARY_DB=/root/authority.db cd /opt/company && flock -n /tmp/dialpad-dl.lock .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json
 NEW: cd /opt/company && SECRETARY_DB=/root/authority.db flock -n /tmp/dialpad-dl.lock .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json

 OLD: SECRETARY_DB=/root/authority.db cd /opt/company && flock -n /tmp/dialpad-ts.lock .venv/bin/python scripts/dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600
 NEW: cd /opt/company && SECRETARY_DB=/root/authority.db flock -n /tmp/dialpad-ts.lock .venv/bin/python scripts/dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600
```

The assignment now prefixes `flock`, which execs python and passes its environment on. This was
measured to work in §4(c) before it was installed.

**Safety of the edit, checked before installing:**

* The change is token-for-token a permutation — an `assert` in the staging script required
  `sorted(old.split()) == sorted(new.split())` for each line, so no argument could be dropped,
  added or reordered. It passed.
* Line count of the crontab is unchanged (38 → 38); only two lines differ.
* Each new payload was **base64-decoded and compared byte-for-byte to the intended command**
  before install (both `roundtrip=OK`).
* The previous crontab was preserved to a **new, never-overwritten** path
  `/root/backups/dialpad-gap-fix-20261011T212512Z/crontab.before`
  (md5 `743f856e690812fa8d1ec00efa73f57a` — identical to what was live at staging time).
* After install, the live crontab md5 equals the staged fixed file md5
  (`2819fa0162bb767a73684ad0b1806150`) — the install is byte-exact.
* Nothing was started, stopped, enabled, disabled, unmasked or restarted. `company-api`,
  `cloudflared`, `secretary-dashboard` and `phone-redirector` were not touched. No database,
  `-wal`, `-shm` or backup was deleted or overwritten. Every read of `/root/authority.db` in
  this workstream used `file:…?mode=ro`.

**To revert, one command:**

```
crontab /root/backups/dialpad-gap-fix-20261011T212512Z/crontab.before
```

**One caveat, said out loud:** this was never a pure "make it green" fix. `recording-gap`
selecting 78 calls means the next scheduled run will begin **downloading** those recordings, and
the run after that will let `transcript-gap` start **transcribing** them at ~$0.006/audio-minute.
The measured batch is 168 audio-minutes, i.e. about **$1.01**, and `--max-minutes 600` bounds a
single run. That is the job's designed purpose and it is why it exists; it is recorded here so
that the spend is not a surprise.

**A second caveat, for whoever reads this next:** the two scripts on disk were replaced at
21:13:32Z by a workstream calling itself `cloudfix` (§0), and the prose copies it saved to
`/root/backups/cloudfix-20261011T211332Z/` are dated 2026-10-07 rather than 2026-10-11. The
content of the two scripts as they were at 21:12:59Z is therefore **not preserved**. If cloudfix
runs again and re-installs from `crontab.new`, it will reintroduce the assignment-in-the-wrong-
position defect and both jobs will go back to rc=1 — the symptom of that is the `runs.tsv` error
tail returning to `no such table`, and the remedy is the two-line permutation in this section.

## 7. PROOF — each job's OWN next scheduled run, not a hand-run

Nothing below was produced by running a job by hand. These are the lines `cron-wrap.sh`
appended to `/root/.cron-status/runs.tsv` from cron's own dispatch, with the crontab fix
installed at ~21:27Z:

```
2026-10-11T21:10:01Z  dialpad-transcript-gap  1   3   <SQL error tail>
2026-10-11T21:20:01Z  dialpad-transcript-gap  1   3   <SQL error tail>
2026-10-11T21:30:02Z  dialpad-transcript-gap  0  26            <-- FIXED, next scheduled run after the fix

2026-10-11T21:15:01Z  dialpad-recording-gap   1   2   <traceback tail>
2026-10-11T21:20:01Z  dialpad-recording-gap   1   3   <traceback tail>
2026-10-11T21:25:01Z  dialpad-recording-gap   1   4   <traceback tail>
2026-10-11T21:30:02Z  dialpad-recording-gap   1  86            <-- ran for real; downloaded the backlog; per-URL errors
2026-10-11T21:35:01Z  dialpad-recording-gap   0   5            <-- FIXED, next scheduled run
```

`dialpad-transcript-gap` went green on its **first** scheduled run after the fix.
`dialpad-recording-gap` needed **two**, and the reason is worth recording rather than hiding:

* **21:25Z, 4 s, rc=1** — still the old defect (`no such table: dialpad_call_full`).
* **21:30Z, 86 s, rc=1 and an EMPTY error tail** — the fix worked: the job got past the
  selector, spent 86 seconds downloading the 78-call / 168-audio-minute backlog, and then took
  its exit at `scripts/dialpad-recording-gap.py:262`:
  `return 0 if not result.get("errors") else 1`.
  rc=1 here is **not a failure of the job**; it is the job reporting that some individual
  recordings would not download. `runs.tsv`'s error column is empty because that exit path
  prints to **stdout**, which `cron-wrap.sh` does not capture (§2) — so a job exiting 1 on a
  *reported* download error is indistinguishable in `runs.tsv` from a job that crashed. That is
  a real reporting gap in this estate and is called out here rather than papered over.
* **21:35Z, 5 s, rc=0** — the queue is now empty, the failed URLs having been recorded in
  `dialpad_media_download_attempt` and excluded by `_terminal_urls()` on the next pass. Clean
  exit, and the shape every subsequent run will now have.

**Independent evidence that the 21:30Z run did real work and did not merely go quiet:**

```
$ find /opt/company/data/dialpad/recording -newermt '2026-10-11 21:29' -type f | wc -l
80
$ find ... -printf '%s\n' | awk '{s+=$1} END {printf "%.1f MB across %d files\n", s/1048576, NR}'
16.9 MB across 80 files
$ ls /opt/company/data/dialpad/recording | wc -l          # whole directory
6190

$ sqlite3 -header "file:/root/authority.db?mode=ro" \
  "SELECT status, COUNT(*) FROM dialpad_media_download_attempt GROUP BY status ORDER BY 2 DESC;"
status|n
downloaded|5178
invalid_payload|4262
unavailable|1172
failed|1
```

80 audio files, 16.9 MB, written to `/opt/company/data/dialpad/recording/` in the ten minutes
after the fix. The store's own `invalid_payload` (4262) and `unavailable` (1172) counts are the
dead-URL population the selector's terminal guard exists to keep out of the queue — the
mechanism the script documents at length and which is now actually reachable.

**Condition at the end of the workstream, for the next reader:**

```
/dev/sda1   75G  53G  19G  74%  /            # 19G free; 16.9 MB was added tonight
Mem:  7742 total, 3101 used, 274 free, 4678 buff/cache, 4640 available
```

`company-api`, `cloudflared`, `secretary-dashboard` and `phone-redirector` were **not** started,
stopped, restarted, enabled, disabled or unmasked. No database, `-wal`, `-shm` or backup was
deleted or overwritten. `company-api` is still the only writer of `/root/authority.db`; every
read this workstream made of it used `file:/root/authority.db?mode=ro`.

## 8. What is NOT fixed here

* **Out of scope, still red at 21:30Z and NOT touched:** `production-comms-freshness` rc=1,
  `ai-gateway-health` rc=3, `guard-registry` rc=2 (`/root/bin/guards.yaml` missing),
  `lpt-freshness-watchdog` (flapping rc=0/1 between runs).
* **The spend now starts.** Because `transcript-gap` and `recording-gap` fire in the same
  second, the 21:30Z transcription run selected 0 — the 80 files landed *after* it looked. The
  next `dialpad-transcript-gap` run (21:40Z) will see them and begin transcribing, at
  ~$0.006/audio-minute over a measured 168 audio-minutes, i.e. roughly **$1.01**, bounded per
  run by `--max-minutes 600`. This is the designed purpose of the pair, and it is recorded so
  the charge is expected rather than discovered.
* **`cron-wrap.sh` cannot distinguish "crashed" from "exited 1 deliberately".** It captures
  stderr only. A job that reports a problem on stdout (`recording-gap` above) logs a blank
  error field. Worth fixing once, separately — it cost this diagnosis a round, and it will cost
  the next one more, because a blank tail reads as "no error".
* **A ~1.8 MB stale `/opt/company/data/secretary.db` still sits in the fallback position** that
  `_resolve_db_path()` uses when the environment variable is absent. The two jobs in hand no
  longer touch it, but any *future* job that copies this pattern without an explicit
  `SECRETARY_DB` will silently read that file and fail the same way. The durable fix is either
  removing that leftover or making the fallback loud; neither was done, because both are wider
  than the two tasks and the narrower change is proven.
