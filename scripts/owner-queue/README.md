# Owner-queue intake patches (W6) — deliverable, NOT installed

> **2026-10-18 — read this first.** This directory now also holds the **full current source** of the
> owner queue, not only patches:
>
> | file | what it is |
> |---|---|
> | `owner-queue.py` | the whole tool as deployed on the authority (`/root/bin/owner-queue.py`): `queue`, `card`, `show`, `knock`, `ingest gv|mail|all`, `health`, `learning`, `answer`, `resolve`, `defer` |
> | `owner-queue-ingest-gv.py` | the Google Voice → queue ingest (`/root/bin/owner-queue-ingest-gv.py`) |
> | `owner-queue-ingest-mail.py` | **the email channel** (`/root/bin/owner-queue-ingest-mail.py`): reads every authenticated inbox, judges each message against a written rubric with a model resolved at runtime, stores every verdict and its reason in `owner_mail_verdict`, and writes only what survives |
> | `owner-queue-ingest-mail.py.experimental` | **SUPERSEDED, do not run.** The first attempt, which reused `owner_attention.from_email_catalog` and produced 25 items over 3 days of mostly marketing. Kept only as history |
> | `0004-gmail-cc-metadata-header.patch` | one line in `app/services/gmail_service.py`: request the `Cc` metadata header, so the envelope rule can see a Cc. Apply to the app snapshot beside the ingest |
| `lpt-owner-queue.{service,timer}` | the 20-minute ingest of **both** channels plus the health check (`/etc/systemd/system/`). `lpt-owner-queue-gv.{service,timer}` is the retired GV-only pair |
>
> The rule set the tool implements is **`docs/owner-queue.md`** — read that before changing a rule.
> The live authority copy is what runs; this is the reviewable source and the recovery copy.
> **Deploy by atomic rename, never in place** (AGENTS.md §8):
> `scp owner-queue.py secratary-cloud:/root/bin/owner-queue.py.new &&
>  ssh secratary-cloud 'python3 -m py_compile /root/bin/owner-queue.py.new && mv /root/bin/owner-queue.py.new /root/bin/owner-queue.py'`
>
> Note on patch 0001 below: the live `owner-queue.py` already carries an equivalent duplicate-add guard
> inside `cmd_add` ("Duplicate check (added 2026-09-29)", overridable with `OWNER_QUEUE_ALLOW_DUPLICATE=1`),
> so the 2026-10-18 rebuild inherited that protection rather than losing it.

Three patches against the authority `secratary-cloud`'s live files. They were
produced against the exact bytes fetched read-only at 2026-10-12 21:1xZ and
verified with `patch --dry-run` against a pristine copy of each target (both
printed `P1_APPLIES` / `P2_APPLIES`; patch 0003 is a new-file diff).

| file | target on `secratary-cloud` | target sha256 (pristine) |
|---|---|---|
| `0001-owner-queue-hard-pending-dedupe.patch` | `/root/bin/owner-queue.py` | `183beb4731d7d3b205c053ebb253f2f15c220f54c8cf02e5e99e3cda262cf572` |
| `0002-wake-balance-pending-guard.patch` | `/root/bin/wake-balance.py` | `66c5892d79fe564323e9125209472fad140d7b9875711ea8d69c83603fba5732` |
| `0003-owner-queue-sweep.patch` | new `/root/bin/owner-queue-sweep.py` | (new file) |

`owner-queue-sweep.py` is the same file as patch 0003's result, committed
separately so it can be read and run without applying a patch.

## Install (when approved — do NOT run now)

```
cd /root/bin
cp owner-queue.py owner-queue.py.bak-$(date -u +%Y%m%dT%H%M%SZ)
cp wake-balance.py wake-balance.py.bak-$(date -u +%Y%m%dT%H%M%SZ)
patch -p1 < <this repo>/scripts/owner-queue/0001-owner-queue-hard-pending-dedupe.patch
patch -p1 < <this repo>/scripts/owner-queue/0002-wake-balance-pending-guard.patch
patch -p1 < <this repo>/scripts/owner-queue/0003-owner-queue-sweep.patch
chmod 755 owner-queue-sweep.py
```

Nothing here restarts a service, edits cron, or touches the database. The
patched files are loaded on the next invocation of each tool.

## What each patch changes

### 0001 — `/root/bin/owner-queue.py`, `cmd_add`

**Before.** Duplicate protection is delegated to
`app.owner_question_dedupe`, imported inside a `try` whose `except` **silently
skips the check** (`add: duplicate check skipped (…)`) and then inserts anyway.
That module is a fuzzy (0.75-similarity) matcher and only reached the authority
on 2026-10-12 16:11Z — after the six identical `wake-balance` rows and the
90-row sweep had already been filed. Nothing in `owner-queue.py` itself refuses a
question that is already `pending`.

**After.** An exact, local check runs before the insert: normalise the incoming
question (casefold, collapse all whitespace, strip CR/LF) and refuse with exit 4
if any `status='pending'` row normalises equal. It names the existing row id and
tells the caller to answer/resolve it first. `OWNER_QUEUE_ALLOW_DUPLICATE=1` and
`--force` still override, so the deliberate re-add path is preserved.

**Proof of the defect.** All six `wake-balance` rows normalise equal and were
`pending`; `INTAKE-QUANTIFIED.md` §D.

### 0002 — `/root/bin/wake-balance.py`, `escalate()`

**Before.** The 12-hour `warned_recently` marker is written by `mark_warned()`
only when `owner-queue.py add` returns 0. A refusal therefore left the marker
unset and the cron (`41 * * * *`) re-attempted on every tick. The guard never
looked at the queue before filing.

**After.** Before building the add call, the guard asks the queue read-only via
`find_open_duplicate("; /root/authority.db", question)`. If a `pending` row
matches at ≥ 0.75 similarity it calls `mark_warned(state, bal)` and returns
`already pending as #N - not re-asked`. The existing resolved-row recurrence path
(`allow_duplicate=True` only when the refusal says `(resolved`) is untouched, so
a genuinely new depletion after the owner answers still reaches him. The check
fails soft (writes one stderr line, never raises).

### 0003 — new `/root/bin/owner-queue-sweep.py`

**Before.** A sweep calls `owner-queue.py add` once per order, so one shop rule
becomes N owner questions. Measured: `lpt-work-order-sweep` 90,
`lpt-board-walk-20261008` 10 — 100 of 157 pending, 64 %.

**After.** A sweep hands JSON-line findings to this tool. Each finding must carry
a stable `subject` (the rule, or the smallest group that shares one answer).
Findings are grouped by normalised subject and the tool files **at most one**
`owner-queue.py add` per subject, with the subject as the question text and the
per-order detail in `context`. A finding without a `subject` is refused. A run
files at most `--max-rows` (default 3) distinct subjects; the rest print
`skipped`. The tool never sets `OWNER_QUEUE_ALLOW_DUPLICATE`, so the queue's own
pending check applies.

Smoke test (local, `--dry-run`, no authority call):

```
$ python3 owner-queue-sweep.py --findings demo.jsonl --source demo-sweep \
    --queue owner-queue.py --dry-run --max-rows 1
line 4: REFUSED - a finding needs a 'subject' (the rule or group); a raw per-order row may not be filed
filed      dry-run  Rule A
skipped    over --max-rows (1 distinct subjects)  Rule B
summary: 2 distinct subject(s); filed=1 refused=0 skipped=1 bad=1
```

## Residual — what these patches do NOT fix

* The two sweep **callers** are gone (one-shot sessions), so re-pointing them at
  `owner-queue-sweep.py` is a future change to whatever re-runs a sweep.
* The patch is not installed; the authority still runs the old bytes.
* Patch 0001 uses `lower(trim(question))` + CR/LF flattening, not full Unicode
  normalisation; two questions differing only by internal run-length whitespace
  are *not* caught by the SQL (the Python normaliser collapses the incoming text,
  so a difference in the stored row could still slip). This is a deliberate
  trade: it is exact enough for the measured cases and adds no dependency.
