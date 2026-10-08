# The wake system — frozen contract

**Owner's ask, 2026-09-18:** *"this might be one of the final pieces in making you actually
autonomous … the secretary server [becomes] your brain when you are not alive, because no one typed into
the GUI … and then when it needs to fully reactivate you in a full dsh session, it could run you in
headless mode back on the desktop … make certain things that the secretary [sees] flags, either for
incoming texts that were flagged as important, or for other things, [and then] it can actually run a
DSH session … just raise a flag … make sure it doesn't sit there spawning hundreds of DSH sessions for
no reason."*

This document is the contract every workstream builds against. It is frozen for this fleet: if you
believe it is wrong, implement to it and say so in your report — do not change it unilaterally,
because three other streams are compiled against these names.

---

## 1. The three layers, and which one is which

| layer | what it is | state |
|---|---|---|
| **CAPTURE** | `~/bin/sms-inbox.py` reconciles every inbound/outbound text from Twilio into its own SQLite store. | DONE |
| **ROUTE** | `~/bin/sms-responder.py` answers (allow=auto) or files one owner-decision row (allow=queue). | DONE |
| **FLAG → WAKE** | anything on the authority raises a **flag**; a dispatcher turns a flag into **a real headless DSH session** on the always-on desktop. | **THIS FLEET** |

The primitive is verified: `dsh --profile headless "<task>"` answers one task and exits, and
`secratary → ssh → ZABZ-TECH → wake-run.ps1 → dsh` was proven end to end on 2026-09-18 (`WAKE_HOP_OK`,
exit 0, result copied back, wake row closed `done`).

## 2. The rule that keeps this from becoming a session factory

> **A wake row is only ever filed by something that knows there IS work.**
> **Nothing on a timer may file work.** A dispatcher releases; it never invents.

Everything in §4 exists to make that rule hold under failure, not to make it optional.

## 3. Store and DDL (authoritative)

Same SQLite file as the inbox: `~/.sms-inbox/inbox.db`, overridable by `SMS_INBOX_DB` for tests.
`wake.py` owns these tables. Others read them only through the CLI or read-only SQL.

```sql
CREATE TABLE IF NOT EXISTS wake (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    subject      TEXT NOT NULL UNIQUE,        -- dedup key; one live row per issue
    kind         TEXT NOT NULL DEFAULT 'task',
    source       TEXT NOT NULL DEFAULT 'manual',
    prompt       TEXT NOT NULL,
    context      TEXT NOT NULL DEFAULT '',
    priority     TEXT NOT NULL DEFAULT 'normal',   -- high|normal|low
    created_at   TEXT NOT NULL,
    not_before   TEXT,                             -- cooldown gate, ISO8601
    state        TEXT NOT NULL DEFAULT 'new',      -- new|claimed|done|failed|cancelled|expired
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    claimed_by   TEXT, claimed_at TEXT, lease_until TEXT,
    finished_at  TEXT, outcome TEXT, cost_usd REAL
);
CREATE INDEX IF NOT EXISTS idx_wake_state ON wake(state);

CREATE TABLE IF NOT EXISTS wake_budget (
    day      TEXT PRIMARY KEY,      -- UTC YYYY-MM-DD
    released INTEGER NOT NULL DEFAULT 0,
    failed   INTEGER NOT NULL DEFAULT 0
);

-- existing, unchanged
CREATE TABLE IF NOT EXISTS awaited (phone TEXT PRIMARY KEY, name TEXT, what TEXT NOT NULL,
    sent_at TEXT NOT NULL, until TEXT, created_by TEXT DEFAULT 'zabz',
    state TEXT NOT NULL DEFAULT 'active');
```

## 4. The safety envelope (all of it is required)

Defaults are env-overridable; the names are fixed.

| # | guard | behaviour | env |
|---|---|---|---|
| 1 | **Dedup** | `subject` is UNIQUE. Filing a subject that already has a row in `new`/`claimed` is a no-op and prints `deduped`. | — |
| 2 | **Cooldown** | A subject filed again after a release within `WAKE_COOLDOWN_SEC` is suppressed: row goes in with `not_before = now + cooldown`. | `WAKE_COOLDOWN_SEC` (default 1800) |
| 3 | **Daily cap** | At most `WAKE_MAX_PER_DAY` releases per UTC day. Over the cap the row stays `new` and `claim` returns nothing. | `WAKE_MAX_PER_DAY` (default 8) |
| 4 | **Per-source cap** | At most `WAKE_MAX_PER_SOURCE_PER_HOUR` releases per `source` per rolling hour. | `WAKE_MAX_PER_SOURCE_PER_HOUR` (default 3) |
| 5 | **Night gate** | `low` priority releases only between 13:00 and 03:00 UTC (≈ 9am–11pm ET). `normal`/`high` always release. | `WAKE_NIGHT_QUIET` (default `1`) |
| 6 | **Kill switch** | If `~/.sms-inbox/WAKE_PAUSED` exists, `claim` returns nothing and `flag` prints `suppressed:paused`. Never delete this file automatically. | `WAKE_PAUSE_FILE` |
| 7 | **Lease** | `claim --lease-seconds N` (default 1200) sets `lease_until`. A dispatcher that dies leaves the row `claimed` until a lease expires. | `WAKE_LEASE_SEC` |
| 8 | **Reaper** | `reap` returns rows whose `lease_until` has passed to `new`; rows with `attempts >= max_attempts` become `failed`; rows older than 30 days in `new` become `expired`. | — |
| 9 | **Attempt cap** | `attempts` increments on every claim. A subject that failed `max_attempts` times is never retried automatically. | `WAKE_MAX_ATTEMPTS` (default 2) |
| 10 | **Cost log** | `finish --cost-usd X` records spend; `stats` reports the day's total. A day over `WAKE_MAX_USD_PER_DAY` stops releases like the daily cap does. | `WAKE_MAX_USD_PER_DAY` (default 3.0) |

**A guard that cannot be exercised by a test does not exist.** Every row above needs a test in
`tests/test_guards.py` that fails if the guard is removed.

## 5. Frozen CLI — `wake.py`

Exit codes: **0 always** for `flag` (a flag must never break its caller), 0 on success for the rest,
2 on a usage/DB error it could not handle.

```
flag --subject S --prompt P
     [--kind K] [--source SRC] [--priority high|normal|low]
     [--context C] [--cooldown-seconds N] [--max-attempts N] [--json]
     -> prints exactly one of: filed / deduped / suppressed:<reason> / capped
        (with --json: {"ok":true,"result":"filed","id":12})

claim --by NAME [--lease-seconds N] [--json]
     -> {"ok":true,"row":{...}} or {"ok":true,"row":null}
        Selecting only state='new' AND (not_before IS NULL OR not_before<=now),
        respecting guards 3, 4, 5, 6, 10; increments attempts; sets claimed_*.

heartbeat ID --by NAME [--lease-seconds N]      -> extends lease_until
finish ID --outcome TEXT [--cost-usd X]         -> state=done
finish ID --failed --outcome TEXT               -> state=failed
reap [--json]                                   -> reclaims expired leases, fails over-attempted, expires old
list [--state S] [--json] [--limit N]
stats [--json]                                  -> counts by state, released today, spend today, caps in force
pause | resume                                  -> create/remove the kill-switch file
```

Existing verbs `await`, `awaits`, `add` keep working (`add` becomes an alias of `flag`).

Environment that MUST be honoured: `SMS_INBOX_DB`, `SMS_INBOX_APP_DB`, `SMS_INBOX_ENV`, and every
`WAKE_*` above. **No test may touch the real `~/.sms-inbox/inbox.db`.**

## 6. File ownership — one owner per path, no exceptions

| stream | owns (in its own worktree) | must not touch |
|---|---|---|
| **W1 core** | `scripts/wake/wake.py`, `scripts/wake/tests/test_guards.py` | anything else |
| **W2 release** | `scripts/wake/dispatch.sh`, `scripts/wake/runner.ps1` | `wake.py`, `sources/` |
| **W3 sources** | `scripts/wake/sources/*.py`, `scripts/wake/sources/README.md` | `wake.py`, `dispatch.sh` |
| **W4 audit** | `scripts/wake/README.md`, `scripts/wake/deploy.sh`, `scripts/wake/cron.txt` | everything else |

Nothing in this fleet writes to secratary's `~/bin` or to any cron. **Deployment is the manager's job.**

## 7. Definition of done, per stream

- **W1** — `SMS_INBOX_DB=/tmp/x.db python3 scripts/wake/wake.py <verb>` works for every verb in §5;
  `python3 scripts/wake/tests/test_guards.py` prints one line per guard, all `OK`, and exits 0. Every
  guard in §4 has a test that fails if the guard is deleted.
- **W2** — `bash -n scripts/wake/dispatch.sh` is clean; a `--dry-run` runs the whole decision path
  without ssh or dsh and prints the exact command it would run; the script takes a single-instance
  lock, heartbeats every N seconds while the session runs, calls `reap` at start, and always
  `finish`es the row (never leaves a claim dangling). Include the exact verification command you ran.
- **W3** — each source is a standalone `python3` script that calls the frozen `flag` CLI, is
  idempotent, and **does nothing when its signal is healthy** (a source that flags on the normal case
  is the session factory we are trying to avoid). Each source prints `flagged <subject>` or
  `quiet`, and has a `--dry-run`.
- **W4** — the audit: every plausible flag source on the authority, ranked, with what it would cost
  and what it must never do; the failure modes (runaway, double-release, stale claim, cost); the
  runbook (how to see the queue, pause it, read a release); the deploy script and the exact cron
  lines, not installed.

## 8. Report format (every stream)

1. Branch and worktree path.
2. Files changed, with line counts.
3. **The exact command you ran and its output line.** Not "tests pass".
4. What you deliberately did not do.
5. **What you could NOT verify.** Say it plainly — a confident claim you did not earn is worse than
   an honest gap.

## 9. Git rules (absolute)

Commit to your own branch only. **Never push. Never touch `main`.** No `reset --hard`, no
`checkout .`, no `clean`, no `rm -rf`. Do not run anything against secratary's `~/bin` or crontab.
