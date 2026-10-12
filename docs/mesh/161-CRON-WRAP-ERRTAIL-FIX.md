# 161 — cron-wrap.sh: make a failing job's error survive in the ledger

Author: DSH child agent on `zabz-tech` (Windows), working the cloud authority over ssh.
Started: 2026-10-11T22:2xZ. Target host: `secratary-cloud` (Hetzner 178.156.194.1, also
`secratary-cloud` in ~/.ssh/config, root only).

## Why

`cron-wrap.sh` is the estate's scheduling contract: every wrapped cron job on the authority
writes one row per run to `/root/.cron-status/runs.tsv`. Several monitors read that file. The
row's 5th field is the only place a failed job's reason is recorded. Today's failures
(`dialpad-recording-gap` twice, and a job that exited rc=1 with its reason on **stdout**)
could not be diagnosed from the ledger. This artifact is the fix, its proof and its rollback.

## 1. The defect, quoted exactly

Live file: `/usr/local/bin/cron-wrap.sh`, 66 lines, 2836 bytes,
mtime `2026-10-08 00:20:32 +0000`, sha256 `f7945803c2a96cb3f367b99b23516fadf749fde1050df33b57c426e247c76b10`.

Line 51 — stderr is captured to a temp file:

```bash
sh -c "$CMD" 2>"$ERRFILE"
RC=$?
```

Line 55 — **the defect**, with the byte arithmetic spelled out:

```bash
ERRTAIL="$(tail -c 400 "$ERRFILE" 2>/dev/null | tr '\n\t' '  ' | cut -c1-160)"
```

Reading that left to right:

| stage | window | bytes kept out of the original stderr |
|---|---|---|
| `tail -c 400` | the **last 400 bytes** | `[N-400, N]` |
| `tr '\n\t' '  '` | newlines and tabs become spaces | same window, flattened to one line |
| `cut -c1-160` | the **first 160 characters of that flattened tail** | `[N-400, N-240]` |

So the field records bytes `N-400 … N-240` of stderr and **discards the final 240 bytes
outright**. A Python traceback ends with the exception line — `ValueError: ...`, the only line
that names the cause — and that line sits in exactly the 240 bytes thrown away. What survives
is the middle of the traceback: the tail of the last `File "...", line N, in f` frame. The
ledger therefore preserves *where* and loses *what*.

Line 58 — the row, 5 tab-separated fields:

```bash
printf '%s\t%s\t%s\t%s\t%s\n' "$STAMP" "$NAME" "$RC" "$((END - START))" "$ERRTAIL" >> "$STATE_DIR/runs.tsv"
```

Measured against the live ledger on 2026-10-11:

```
/root/.cron-status/runs.tsv   142778 bytes   2302 rows
field-count distribution:     NF=5 rows=2302          <- shape is stable today
rc != 0 with field5 EMPTY:    count=143               <- the blind spot, quantified
```

One of those 143 is live right now — `cron-target-guard` at `22:25:02Z` recorded `rc=1` with a
blank reason. The task's "a job exited rc=1 while printing its reason to stdout" is not an
anecdote; it is 143 rows, 6% of the ledger.

## 2. A second, silent defect found while reading: the authority is running a STALE copy

The brief says to take `cron-wrap.sh` from the office box. The authority did not get the newest
one. Two other copies of the same file are on this box, both newer, both identical:

| path | lines | mtime | sha256 (12) | writes a row on its own refusal? |
|---|---|---|---|---|
| `/usr/local/bin/cron-wrap.sh` (**LIVE**) | 66 | 2026-10-08 00:20 | `f7945803c2a9` | **no** |
| `/root/_staging/files/cron-wrap.sh` | 85 | 2026-10-11 06:34 | `8db5fe432914` | yes |
| `/root/port135/cron-wrap.sh` | 85 | 2026-10-11 06:32 | `8db5fe432914` | yes |
| `/root/code/harness-config/scripts/guards/cron-wrap.sh` | 66 | 2026-10-11 08:33 | `f7945803c2a9` | **no** |

The 85-line version adds a `refuse()` function whose whole point is:

```bash
printf '%s\t%s\t2\t0\tcron-wrap REFUSED: %s\n' "$stamp" "$NAME" "$why" >> "$dir/runs.tsv" 2>/dev/null || true
```

**Consequence on the live authority:** the 66-line wrapper exits 2 *before* writing any row when
a crontab line is malformed. The job produces no ledger row at all, so "this job has never run"
is indistinguishable from "this job is fine" — the precise 2026-10-02 failure the comment block
describes, in which the pain-check suite was silently dead for 37 hours.

**And the downstream reader is live and expecting it.** `/root/bin/sources/cron-failures.py`
defines

```python
REFUSED = "cron-wrap REFUSED"
```

and files work on any `rc=2` row carrying that token, *bypassing its 10-consecutive-failure
threshold*, on the reasoning that a refusal needs no streak because the job provably never ran.
On this box that branch can never fire: **the refusal signal is dead on the new authority.**
(`grep -rln 'cron-wrap REFUSED' /root/bin /usr/local/bin` returns exactly one file —
`/root/bin/sources/cron-failures.py`. It is a reader with nothing to read.)

The 85-line copy still contains the *same* `tail -c 400 … cut -c1-160` defect on its line 74, so
"install the newer copy" is not the fix by itself. The fix must be the union of both.

## 3. What the ledger contract actually is (so the fix cannot break a reader)

`/root/bin/sources/cron-failures.py` is the only real parser, at lines 192–197:

```python
for line in text.splitlines():
    parts = line.rstrip("\n").split("\t")
    ...
    err = parts[4] if len(parts) > 4 else ""
```

Two hard constraints follow, and they are the whole reason this fix is shaped the way it is:

1. **Exactly 5 tab-separated fields, same order, unchanged.** All 2302 existing rows have
   `NF=5`. Field 5 must never contain a raw tab or newline, or a row would silently become 6+
   fields and `parts[4]` would truncate the reason.
2. Field 5 is *displayed*, not matched (except the one literal `cron-wrap REFUSED` token in the
   refusal path, which is why that token is preserved verbatim rather than reworded).

So: the column shape stays byte-for-byte the same, and only the *content* of field 5 changes —
from "the wrong 160 characters" to "the 160 characters that are the reason".

## 4. Backup (rollback, step 5)

Original preserved before any edit, mode/timestamps kept with `cp -p`, sha256 verified equal:

```
/usr/local/bin/cron-wrap.sh.PRE-lastlines-fix-20261011T222157Z.bak
  sha256 f7945803c2a96cb3f367b99b23516fadf749fde1050df33b57c426e247c76b10   (== the live file)
```

Rollback is one command:

```bash
cp -p /usr/local/bin/cron-wrap.sh.PRE-lastlines-fix-20261011T222157Z.bak /usr/local/bin/cron-wrap.sh
```

## 5. Plan of the change

* field 5 = the **last** lines of stderr, not a window that cuts them off;
* the final non-empty line (the Python exception line) is always kept **whole** when it fits in
  160 characters, and when it does not fit we keep its **front**, because `ValueError: ` is at
  the front and that is the token that matters;
* preceding lines are back-filled in front of it, space-joined and prefixed `...` when
  something was dropped — a traceback then reads `...line 212, in main ValueError: bad thing`;
* `rc != 0` with an empty stderr records an explicit marker instead of a blank field;
* still ≤160 characters, still one flattened line, still 5 fields, still the same `printf`;
* the `refuse()` row from the 85-line copy is restored, so a refused job is visible again.

## 6. The fix, as installed

Installed 2026-10-11T22:28:44Z. `/usr/local/bin/cron-wrap.sh` is a **symlink target** — and
`/root/bin/cron-wrap.sh` is a symlink *to* it (`lrwxrwxrwx ... -> /usr/local/bin/cron-wrap.sh`),
so the fix is in force on both paths from one file.

```
/usr/local/bin/cron-wrap.sh
  mode 755 root:root   8027 bytes   156 lines
  mtime 2026-10-11 22:28:44 +0000
  sha256 be544850d2168403b498a8af93e1026ad78c2667cae53e886db51fdc1110290e
```

A copy is preserved beside this artifact, so the fix survives a rebuild of `/usr/local/bin`:

```
/root/out/migration-review/161-cron-wrap.sh.fixed    sha256 be544850d216...  (identical)
```

What changed, by line number in the installed file:

| line | what |
|---|---|
| 39 | the OLD defective expression, now retained **as a comment** with the byte arithmetic explained |
| 110 | the new field-5 extraction: `tail -c 8000` + `awk` |
| 120 | `anchor = lines[n]` — the last non-empty stderr line is the anchor |
| 145 | the empty-stderr marker for a non-zero exit |
| 77–92 | the restored `refuse()` row (the 85-line contract) |

The 5-field `printf` on line 149 is **byte-for-byte the same statement as before**, which is what
keeps every existing parser working.

## 7. Proof

### 7a. Old vs new on fixtures (the real script, scratch ledger)

`/root/_dsh/test-errtail.sh` drives the installed wrapper with `CRON_STATUS_DIR` pointed at a
scratch ledger, so the live ledger is not involved. Fixture 1 is a genuine Python traceback from a
real module at a realistic path (1147 bytes of stderr); fixture 8 is a traceback whose exception
line is short, to show the back-fill.

```
FIXTURE              OLD    NEW    VERDICT
fx1-traceback        161    149    ok
   OLD: [ng_gap.py", line 10, in _run_pass     cur = _load_cursor(cursor_path); batch = ...]
   NEW: [...with open(path) as fh: return json.load(fh) ~~~~^^^^^^ FileNotFoundError: [Errno 2] No such file or directory: '/root]
fx2-longexc          161    160    ok
   OLD: [xxxxxxxxxxxxxxxxxxxxxxxxx...]                     <- the BACK of the message, "RuntimeError: " gone
   NEW: [RuntimeError: xxxxxxxx...]                        <- the FRONT, where the failure token is
fx3-emptystderr        0     64    ok
   NEW: [[no stderr; rc=1 -- reason is on stdout or in the job's own log]]
fx4-tabs              72     73    ok      (tabs collapsed; still one field)
fx5-single            18     16    ok
fx6-rc0-empty          0      0    ok      (rc=0 stays empty -- no noise added for healthy runs)
fx7-rc127              0     40    ok      [sh: 1: nonexistent-binary-xyz: not found]
fx8-short-exc        161    144    ok
   OLD: [Traceback (most recent call last):   File "/opt/company/scripts/dialpad_recording_gap.py", line 118, ...]
   NEW: [...sys.exit(main(sys.argv)) File "/opt/company/scripts/dialpad_recording_gap.py", line 96, in main return _persist(batch) KeyError: 'recordings']
```

Assertions:

```
fixture's own exception line: [FileNotFoundError: [Errno 2] No such fil]
PASS fx1: the exception line IS in field 5, verbatim
PASS fx1: the OLD window LOST that same exception line; NEW keeps it
PASS fx3: rc=1 with empty stderr is now EXPLICIT, not blank
PASS fx6: rc=0 with empty stderr stays empty (no noise added for healthy runs)
```

All 8 rows: `NF=5`, none over 160 characters, longest row 197 bytes. fx8 is the summary of the
whole fix — the old window returns the *frames* and drops `KeyError: 'recordings'`; the new one
returns the last frame **and** the exception inside the same 160 characters.

The fixed script also passes `bash -n`, and it prints nothing on the happy path (wrapper stderr was
empty across every case).

### 7b. In situ, the same failing command through both wrappers

`/root/_dsh/install-161.sh`, one command, OLD backup vs NEW installed, sentinel
`ERRTAIL-TEST-161-MARKER` in the exception message:

```
--- OLD (66-line .bak) field 5 ---
 File "/root/_dsh/errtail-test-161.py", line 8, in main     return outer(cfg)   File "/root/_dsh/errtail-test-161.py", line 5, in outer     return inner(payload
--- NEW (installed)   field 5 ---
...ValueError: ERRTAIL-TEST-161-MARKER sentinel that must appear in the ledger field 5

old  sentinel MISSING      old  fields=5 rc=1 len(field5)=160
new  sentinel PRESENT      new  fields=5 rc=1 len(field5)=86
```

### 7c. Through the REAL scheduler, in the LIVE ledger, then removed

A clearly-marked test crontab line was appended (`cron-wrap-errtail-test-161`, every minute). It
fired after ~60 s and wrote to the live ledger:

```
fields=5  2026-10-11T22:30:01Z  cron-wrap-errtail-test-161  rc=1
          [...ValueError: ERRTAIL-TEST-161-MARKER sentinel that must appear in the ledger field 5]

PASS: the live ledger row now contains the exception line (impossible under the old window)
PASS: no test row has a blank field 5
```

The line was then removed, and the crontab verified **byte-identical** to the pre-test backup
(`sha f6cba2705d66`, 44 lines, 0 occurrences of the test name). One test row remains in the
append-only ledger — deliberately: `runs.tsv` is never rewritten, and the name says what it is.

### 7d. Real scheduled jobs after the swap

```
rows added since install: 9        NF=5 rows=9
rows with rc!=0 and a BLANK field 5: 0
rows with field-5 length over 160  : 0
```

Three genuinely-failing real jobs are now self-describing where they were blank minutes earlier:

```
2026-10-11T22:25:02Z  cron-target-guard           rc=1  []
2026-10-11T22:30:01Z  cron-target-guard           rc=1  [[no stderr; rc=1 -- reason is on stdout or in the job's own log]]
2026-10-11T22:30:01Z  guard-registry               rc=2  [[no stderr; rc=2 -- reason is on stdout or in the job's own log]]
2026-10-11T22:30:01Z  production-comms-freshness   rc=1  [[no stderr; rc=1 -- reason is on stdout or in the job's own log]]
```

### 7e. The reader still parses, and nothing else was touched

`/root/_dsh/verify-161.sh` re-implements `cron-failures.py`'s own loop (`split("\t")`, `parts[4]`)
over every live row:

```
rows the cron-failures.py algorithm reads        : 2321
rows NOT exactly 5 fields (must be 0)            : 0
rows with field5 longer than 160 (must be 0)     : 0
rows with rc!=0 and a BLANK field5 (historical)  : 143
rows carrying the 'cron-wrap REFUSED' token      : 0
```

The marker deliberately does **not** contain `cron-wrap REFUSED`, so the new blank-stderr text
cannot be mistaken for a wrapper refusal and cannot make `cron-failures.py` file work it should not.

Nothing was restarted, and the database was never opened by this work:

```
company-api            active  since Sun 2026-10-11 15:17:41 UTC
cloudflared            active  since Sun 2026-10-11 08:25:06 UTC
secretary-dashboard    active  since Sun 2026-10-11 08:25:04 UTC
phone-redirector       active  since Sun 2026-10-11 15:53:55 UTC
```

Every timestamp predates this work (22:20Z onward). `/root/authority.db`, `-wal` and `-shm` were
only read by `ls -l`; no cron script here opens the database at all.

## 8. Rollback

The original is preserved with its mode and timestamps, and hash-verified equal to what was live
before the change:

```
/usr/local/bin/cron-wrap.sh.PRE-lastlines-fix-20261011T222157Z.bak
  sha256 f7945803c2a96cb3f367b99b23516fadf749fde1050df33b57c426e247c76b10
```

One command restores it:

```bash
cp -p /usr/local/bin/cron-wrap.sh.PRE-lastlines-fix-20261011T222157Z.bak /usr/local/bin/cron-wrap.sh
```

Rollback needs no crontab change and no restart: the wrapper is executed fresh by cron on every
run, so the next tick picks up whichever version is in place. The pre-test crontab is also saved at
`/root/_dsh/crontab-backups/root-crontab.PRE-161-test-line.20261011T222844Z.txt` (sha `f6cba2705d66`).

## 9. Follow-ups this exposed (not done here — each needs an owner)

1. **A stale copy could reintroduce the defect.** No installer on this box copies `cron-wrap.sh`
   into place (the scripts that mention it only write *crontab lines*), so the fix will not silently
   revert. But three independent copies remain, two of which are the broken window:

   | copy | lines | sha (12) | writes refusal row | bad stderr window |
   |---|---|---|---|---|
   | `/root/code/harness-config/scripts/guards/cron-wrap.sh` | 66 | `f7945803c2a9` | no | yes |
   | `/root/_staging/files/cron-wrap.sh` | 85 | `8db5fe432914` | yes | yes |
   | `/root/port135/cron-wrap.sh` | 85 | `8db5fe432914` | yes | yes |

   The harness-config copy is the dangerous one: it is the repo's guard copy, it is the *oldest*
   contract (no `refuse()`), and it sits in a git repo that is already dirty with unrelated changes
   (`M AGENTS.md`, modified presets, untracked files), so it was left untouched rather than mixed
   into someone else's uncommitted work. Whoever owns that repo should replace it with
   `/root/out/migration-review/161-cron-wrap.sh.fixed`.

2. **The refusal signal was dead on the authority and is now live.** `sources/cron-failures.py`
   files work on any `rc=2` row carrying `cron-wrap REFUSED`, bypassing its 10-failure threshold.
   The 66-line wrapper never wrote that row, so a malformed crontab line was completely invisible.
   Restored. Any deployment of a stale copy from row 1 above would silently kill it again.

3. **143 rows of history have an unrecoverable cause.** The ledger is append-only and the stderr
   was never stored, so those runs cannot be diagnosed retroactively. The count is only of
   *recorded* blanks; a further unknown number lost their cause to the discarded-240-bytes bug
   while still having a non-empty field 5 (fx8 is exactly that shape).

4. **Three real jobs fail with no stderr at all** — `cron-target-guard` (rc=1, twice today),
   `guard-registry` (rc=2), `production-comms-freshness` (rc=1). They were invisible in the ledger
   until the marker landed. The marker says *that* they are silent, not *why*; whoever owns them
   still has to look at their stdout. `guard-registry` at rc=2 is worth a second look because rc=2
   is also the wrapper's own refusal code.

5. **The task statement says 41 wrapped crontab lines; the authority has 25** (44 crontab lines
   total, 25 non-comment; `/etc/cron.d/` holds only `e2scrub_all`, unwrapped). Everything here is
   nonetheless estate-wide on this box, because all 25 wrapped lines share this one wrapper.

## 10. Re-running this work

The scripts are left in place, all safe to re-run:

```
/root/_dsh/test-errtail.sh          OLD-vs-NEW fixture comparison (scratch ledger only)
/root/_dsh/install-161.sh           install + in-situ old/new proof (idempotent)
/root/_dsh/test-and-verify-161.sh   live scheduler test, restores the crontab itself
/root/_dsh/verify-161.sh            reader-compatibility + redeploy-risk + service check
/root/_dsh/gather-final.sh          final state
```

