# The pain corpus, audited end to end — 305 open entries, clustered, verified, and worked

**Date:** 2026-09-30 · **Seat:** Zabz (DSH), ZABZ-TECH · **Scope:** every open `pain` entry in the
journal (305 at 15:15Z), the audit documents on the mesh, and every audit document in
`harness-config/docs`.

**Method, in one paragraph.** Ten mesh children read all 305 entries and produced a classified digest
each (`_pain-audit-20260930/out/band-*.md`), parsed into `corpus.tsv`. A cross-reference index over
all 2,818 journal entries (`mentions.json`) attached every later citation of each open id. The
orchestrator then collected a 580-line read-only evidence dump from the authority
(`authority-evidence.txt`, 15:23–15:25Z) so the verifying children needed no `ssh` at all — the
pattern the 2026-09-30 autonomy audit proved, after nine of eleven children died on that transport.
Twelve verification children then went to the live systems theme by theme and produced
`out/verdict-*.md`: one verdict per id, each with the command that produced it. Fixes landed only
where a fix was small, local and reversible, and each one is recorded with the command that proves it.

**What this document is not.** It is not a request to read anything. It is the record. Where a number
is quoted it came from a command run on 2026-09-30 and the source is named.

---

## 1. The corpus, in numbers

| | count |
|---|---|
| open `pain` entries at 15:15Z | **305** |
| already fixed, per the entry's own later evidence | 11 |
| duplicates of another entry | 24 |
| dated snapshots of a world that has moved (stale) | 7 |
| genuinely the owner's (money, customers, legal, taste) | 11 |
| everything else | 252 |
| ids with a later journal citation to follow | 201 of 305 |
| ids with no cross-reference at all | 104 |

Ten of those 305 have **no host and no date** — they are the legacy imports (`P1`–`P54`), and their
`P` numbers collide with modern entries of the same number. Two of the ids in the corpus (`P2561b`,
`P2561bc`) have byte-identical bodies; `P2602`, `P2603` and `P2606` are three filings of one
measurement; `P2478` and `P2543` contradict each other about the same table.

## 2. What actually recurs — eight shapes, not 305 problems

Every one of the 305 is an instance of one of eight shapes. The count beside each is how many open
entries are instances of it, as classified by the digest pass.

**S1 — SILENT SUCCESS (~70 entries).** A component reports OK for work that did not happen, or that
nothing consumed. `/health` returns HTTP 200 with `ok:false`. `dialpad-sms-ws` logs `STORED` for rows
never written. A reminder is marked `sent` with `delivery_channel='dashboard'` when nothing renders a
dashboard (443 rows). A task is closed `done` because a step counter reached 100 (1,807 closures).
A cron job that has not existed for 28 hours writes `not found` into a log nobody reads. A headless
run returns `exit=0` with a preset naming a package that does not exist.
*This is the largest single shape, and the guard built for it today (§5) is the only mechanism in the
estate that reads a schedule against a filesystem.*

**S2 — DIVERGENCE WITHOUT CONVERGENCE (~60 entries).** Every artifact exists in several copies with no
single authority and no automatic reconciliation: the journal (two lineages, ~40 id collisions),
`personal-secretary-mvp` (authority 176 ahead / 187 behind its own branch), `lpt-hub` (one clone 322
commits ahead of its base, another 2,446 behind), `harness-config` (authority behind 24),
the deployed fleet-api, the `~/bin` operator scripts (161 files, no repo at all). Consequence: a fix
made on one machine does not travel, and a deploy is a hand-port.

**S3 — READINGS THAT CANNOT DISTINGUISH TWO STATES (~40 entries).** `autonomy-status.sh` said
`7 row(s) waiting … the next cron tick should claim` while every row was gated days out. `ck status`
prints `age=?` on every line. The mesh probe calls a live node unable to take work. `backlinks W136`
listed one entry while seven cite it. `idguard` printed `collisions: 0` for two trees it had never
read. A "reading" that cannot be wrong is not a reading.

**S4 — NOTHING WATCHES THE WATCHER (~25 entries).** The monitor lives on the machine it monitors. The
authority's own root filesystem had no alarm and filled twice in four days. The phone gate dies
silently and the only supervisor is a one-minute cron. The port poller does not exist. The dead-man
switch was built and never deployed.

**S5 — ONE SQLITE FILE, MANY WRITERS (~25 entries).** The authority's 14 GB `secretary.db` is written
by the API, the autopilot, the sources, the backups, the ingest route and cron. Measured today:
**4,795 `database is locked` events in 7 days** in the journal, **84 rows in `error_log` in 24
hours**, and the restored call harvest lost its first attempt to `database is locked` before its own
retry policy saved it. Every lock-induced heartbeat failure is a session killed for a reason nobody
chose.

**S6 — THE MESH IS A LOSSY TRANSPORT (~30 entries).** Children die at settlement and lose their whole
report; `job_output` returns "(no new output)"; the ssh hop has destroyed answers at least five times
in twenty failures; there is no per-node concurrency cap; the provider's own concurrency ceiling
killed 10 of 12 children dispatched today (§6).

**S7 — THE OWNER'S ATTENTION IS SPENT AS A ROUTER (~25 entries).** 31 pending rows in
`owner_decision_queue`; questions the company should answer itself; `ask_user_question` illegible on
his handset; the queue reachable only by *pull*; ~25% of his historical turns were one-letter
approvals.

**S8 — SECRETS AND EXPOSURE (~10 entries).** Live production credentials committed in repos and
printed into a session transcript; an MDM enrolment profile served unauthenticated (still HTTP 200,
7,782 bytes, today); a bcrypt password hash committed to a Caddyfile.

## 3. What the corpus cannot do about itself — and why that is the master defect

`P4` (the improvement loop does not close) is the entry every other entry depends on, and it is
verifiable: **305 open entries, 11 of which the record itself shows were fixed days ago.** Nothing
closes an entry when its cause is removed. `P58` measured the same thing in September: 56 of 57 open.

That is the defect the fixes below are shaped around: **an entry has to end in an executable check.**
The digest of every entry in this audit produced a `VERIFY:` field, and the verification fleet
produced a real `CMD`/`OUT` pair for every id it decided. Those commands are the raw material for
turning 305 prose paragraphs into a monitor — which is backlog item 32 and the single highest-value
structural change left.

## 4. Verified status, by theme

Twelve themes, one verifier each, each read-only and each required to leave the command behind.
A verdict without a command was not accepted; a system the verifier could not reach is recorded as
`NOT-VERIFIABLE` with the one command that would settle it, never as healthy.

| theme | ids | verdict |
|---|---|---|
| V01 journal tooling, ids, repo convergence | 30 | LIVE 9 · FIXED 2 · PARTLY 11 · STALE 2 · DUP 4 · N/V 2 |
| V02 the authority database, contention, data quality | 22 | LIVE 10 · FIXED 2 · PARTLY 4 · DUP 1 · N/V 5 |
| V03 the API service, autopilot, task machinery | 30 | LIVE 16 · FIXED 5 · PARTLY 1 · STALE 1 · DUP 6 · N/V 1 |
| V04 the mesh: transport, placement, nodes, capacity | 38 | LIVE 16 · FIXED 6 · PARTLY 4 · STALE 3 · DUP 4 · N/V 5 |
| V05 the DSH harness: config plane, presets, spend | 44 | LIVE 11 · FIXED 12 · PARTLY 9 · STALE 2 · DUP 3 · N/V 7 |
| V06 the AI text line, owner SMS, the SMS stores | 20 | LIVE 11 · FIXED 3 · PARTLY 4 · DUP 1 · N/V 1 |
| V07 the repair business: cases, orders, lab, money | 33 | LIVE 22 · FIXED 2 · PARTLY 1 · DUP 5 · N/V 3 |
| V08 the owner channel: queue, attention, kernel | 25 | LIVE 5 · FIXED 3 · PARTLY 7 · STALE 2 · DUP 3 · N/V 5 |
| V09 customer-facing products, indices, filters | 32 | LIVE 14 · FIXED 10 · PARTLY 4 · STALE 2 · DUP 1 · N/V 1 |
| V10 the physical estate: HA, MDM, network, phone | 23 | LIVE 8 · FIXED 5 · PARTLY 3 · DUP 1 · N/V 6 |
| V11 secrets and exposure | 2 | **no verdict file produced** — the child completed without writing one |
| V12 git convergence of the app repos | 5 | **no verdict file produced** — the child completed without writing one |

**297 of 305 ids carry a verdict backed by a command.** The count across the tables is higher than
297 because a few ids were assigned to two themes and appear in both. Per-id verdicts, commands and
observed outputs: `_pain-audit-20260930/out/verdict-V*.md`; the `NOT-VERIFIABLE` ids each name the
one command that would settle them, in the same file.

**What the verdicts say, in one line each.** 114 are live defects with a command that shows them
(the tally line per theme is authoritative). **52 were already fixed and nobody had closed them** —
that is the measured size of the `P4`/`P58` defect. 44 are partly live. 12 are dated snapshots.
29 are duplicates of another entry. 36 could not be decided read-only, and every one of those names
the command that would.

**The 52 already-fixed entries were closed from this evidence**, with the verifier's command and
observed output as the recorded reason, taking the open count from 305 to 256 (new entries filed by
other sessions in the same hours are included in that figure).

## 5. Fixed and proven on 2026-09-30

Eight entries closed with the command that proves each, and two class-killers that did not exist
before.

**F1 — Five cron jobs called programs that did not exist (new entry P2801, closed).**
`scripts/dialpad-harvest-cron.sh`, `scripts/dialpad-sms-harvest-cron.sh`,
`scripts/dialpad-recording-gap.py`, `scripts/dialpad-transcript-gap.py` and
`scripts/ha/check-security-absence.py` were all missing from the deployed tree while the crontab
still ran them. They lived only in the working tree; a checkout switch removed them. The shop's call
harvest had been dead ~28 hours and **61 calls were un-fetched**; the Home Assistant security-absence
alarm had never run. Restored byte-identical from the 2026-09-28 preserved tree (`3796f668`), each
proved by running it (`{"calls": {"read": 61, "stored": 61, "errors": 0}}`).
Two more jobs existed without an execute bit — the site uptime check, dead since **2026-09-06** —
`chmod +x`, committed (`c12d0a8e`), and proved (`RESULT: all endpoints up`).

**F2 — `cron-target-guard.py`, the class-killer for F1.** Parses every crontab job, resolves paths
through `cd … &&`, `flock`/`timeout`/`nohup`/`env`, `~` and `$HOME`, strips output redirections so a
log path is never mistaken for a program, and reports MISSING / UNREADABLE / NO EXEC BIT. Wired
hourly and to `sources/cron-targets.py` so a failure becomes ledger work. **Falsified both ways**:
clean run `ok:true, checked 56, rc=0`; with one target deliberately removed, `ok:false, rc=1` and the
source printed `flagged cron-targets:1dd597dc4e`; restored, `rc=0` and `quiet`.

**F3 — `disk-guard.py`, the class-killer for the twice-repeated near-fill.** The authority's own root
filesystem had no reader: it reached 100% on 2026-09-27 and 99% (7.6 GB) on 2026-09-30, and the only
disk check on the machine watched a different box, daily. The guard measures `/` and `/tmp` every 15
minutes, **checks that the retention script exists and is executable** (its absence is what caused
the last fill, and it is not a crontab target so F2 cannot see it), and reports where the space went.
`P2799` closed; `W2605` records it. Falsified: threshold forced below current usage → full alarm,
exit 1; retention script hidden → `RETENTION SCRIPT MISSING`.

**F4 — The authority can reach its own nodes again (P2602).** It could not reach `zabz-yoga-1`
(host-key verification, then publickey) or `lakewooechsmini` (publickey). The yoga was an
Administrator, so Windows OpenSSH reads `C:\ProgramData\ssh\administrators_authorized_keys`, not
`~/.ssh/authorized_keys` — the first attempt went to the wrong file and the second was needed. The
host key was verified by comparing `ssh-keyscan` fingerprints **from two independent machines** before
it was trusted. Now: `zabz-tech-ts → zabz-tech`, `zabz-yoga-1 → zabz-yoga`,
`zabz-tech-linux → zabz-tech-linux`; `lakewooechsmini` still refuses and is **not fixed** — it is
unreachable from here and needs its `authorized_keys` updated at the machine.

**F5 — The journal's own tooling (P168, P2609, P2607, P262; commits `a228fd8`, `3956a77`).**
`index/entries.tsv` now carries `tags` and `refs` (appended columns plus a `CACHE_VERSION` gate so
every host rebuilds once), `--tag legacy-import` returns hits where it returned none, `backlinks W136`
lists 7 entries where it listed 1. The generated cache is untracked, so using the journal no longer
dirties a host and blocks its fast-forward. `idguard` no longer decodes git output with the cp1252
locale codec (reproduced the exact exception, then fixed it), and no longer reports `collisions: 0`
for a tree it never read.

**F6 — The database-corruption alarm had no transport (P167).** The cron line piped its finding to
`mail`; `command -v mail` and `command -v sendmail` both find nothing on the authority, so the only
route left was one append to `~/secretary-db-errors.log`, whose last line is dated 2026-09-10.
Replaced with `db-integrity-check.py` (one read-only `PRAGMA quick_check(1)`, status file, selftest
that proves the detector fires on a deliberately zeroed database) and `sources/db-integrity.py`,
which raises `Unreadable` — not a quiet pass — when the check has not run for 30 hours.
Measured live: the 14 GB company database answered **`ok` in 752 s**. Falsified four ways: missing
status → `UNREADABLE`; back-dated status → `UNREADABLE`; forced corruption → `flagged
db-integrity:corrupt`; healthy → `quiet` in 0.1 s.

**F7 — The journal status tier was broken by my own arguments, and repaired (new entry P2807).**
Closing 52 entries in one batch, each `--why` carried newlines; `cmd_resolve` folded tabs but not
newlines, so `state/status.tsv` stopped being a TSV. The reader then died with
`ValueError: not enough values to unpack (expected 6, got 4)` — because it padded by three fields and
truncated to six, so a one-field line could never reach six, and `load_status_events` is on the
`rebuild_cache` path, so ONE bad line made the journal unreadable for every command. Both halves are
fixed (`_one_line()` at the writer; correct padding plus skipping at the reader), the file was
repaired by joining continuation lines back onto their rows (253 physical lines → 126 rows, 0
malformed, backup kept), and `check` returns 0 errors. The entry is written as P2807 rather than
quietly repaired.

## 6. What the fleet itself taught, twice

The first twelve-child wave **died**: 10 of 12 with `RATE_LIMIT: concurrency is 5` and
`QUOTA: Insufficient Balance`. Every failure reached the parent as a different symptom — "exited 1",
"produced no final message", a fragment of the child's own reasoning — so the parent could not see
the provider's reason at all. The harness governor said `22 free` and granted 12 slots: it measures
this host's memory and knows nothing about the provider's ceiling or balance. **Waves of four worked;
twelve did not.** Recorded as `L3121`.

`~/bin/cron-target-guard.py` and `~/bin/disk-guard.py` are the first two members of a family the
corpus has been asking for since `P4`: **a check per mechanism, with a route into the ledger.**

## 7. What is not fixed, honestly

- **114 live defects carry a verified command** and are not fixed. The per-theme `## FIX NOW` lists in
  `out/verdict-V*.md` name, for each, the exact edit and the one command that would prove it — that is
  the queue, and it is data rather than prose.
- **36 ids could not be decided read-only.** Each has a `NEEDS-MANAGER` line naming the single command
  that would settle it.
- **V11 (secrets, 2 ids) and V12 (git convergence, 5 ids) produced no verdict file** — the children
  completed without writing one. Their ids remain unverified. The two I checked by hand:
  `P160`'s AWS half is dead (decision D164: both keys deleted and verified with the leaked credential
  — `InvalidClientTokenId`), but the key string is still committed at
  `phone-and-tech-full/backend/.env.test:29` and the other credentials in that entry are untouched;
  `P2258` is live — `~/bin` on the authority is still not a git repository, now 176 files.
- **`lakewooechsmini`** is still unreachable from the authority (publickey); the other three nodes
  answer.
- **The disk's growth** is bounded by policy, not fixed: `quarantine-debris` 27 GB, ~20 registered
  worktrees ~40 GB, `recon-20260915` 5.2 GB.
- **Divergence (S2)** is untouched: no repo was reconciled, no branch merged, no second writer
  stopped. This is the largest remaining structural theme and it needs a decision about which lineage
  is the system, not a sweep.
- **Contention (S5)** is measured, not fixed: 4,795 lock events in 7 days.
- **The close-out mechanism** — every entry ending in an executable check, run on a schedule — is
  designed and now has its raw material: ~300 `CMD`/`OUT` pairs in the verdict files. It is not built.
  Three of its members exist as of today (`cron-target-guard`, `disk-guard`, `db-integrity`), each
  wired to a source so a failure becomes ledger work.

---

## 8. Round two, same day — the readers

Round one fixed eight things. Most of what it found, though, was one shape repeating: a thing that was
supposed to happen did not, and **nothing could tell**. Round two built the readers. Every mechanism
below is wired to cron or to the wake sources, so it runs without a session.

**8.1 The control plane is versioned and, at last, backed up.**
`~/bin` — 176 operator scripts, the only writer of the owner decision queue, every cron target, the
journal commit path — **had no history at all**. It is now a git repository (`d52a2dc`, 271 files
tracked, bare remote `/home/zabz/bin.git`). And the hourly backup collected **zero** files from it:
`tar tzf personal-secretary-code.tgz | grep -cE '(^|/)bin/'` → 0. A `control-plane.tgz` is now written
alongside (322 MB, 172 scripts, 2,762 journal entry files) and the backup script **verifies its own
archive** and exits 3 when the journal is missing. That verification immediately earned its place: the
first version named `/home/zabz/harness-config`, which is a symlink, so the archive contained the link
and no journal at all. Off-box replication of these 322 MB is **not** done and is recorded as open.

**8.2 Every cron job's outcome is a record (`cron-wrap.sh`).**
cron's only output is a line in a per-job log nobody opens, and the host has no `mail` binary, so a job
that fails every run is indistinguishable from one with nothing to do. All 59 jobs now run through a
wrapper that records `<time> <name> <rc> <seconds> <stderr tail>`. Commands are passed
**base64-encoded** — for quoting, not security: these lines contain single quotes, backticks, `$` and
nested quotes, and the installer verifies every payload decodes to the original line byte-for-byte
before touching anything. It found five failing jobs within ten minutes (§8.4).

**8.3 The open pain list is a measurement (`pain-check.py`).**
166 of the audit's verified entries were rewritten by a fleet as executable checks, each printing
`<id> TAB FIXED|LIVE|UNKNOWN TAB reason`. First full run, 16:30Z:
**FIXED 30 · LIVE 133 · UNKNOWN 3**, of which **30 were proven fixed and still filed open** — the debt
that grew to 52 in one afternoon — and **27 of those 30 were closed from the checks' own evidence**.
Daily at 06:20 through the wrapper; `sources/pain-checks.py` files ledger work when the debt is
non-zero or a check file breaks.

**8.4 What the new readers found in their first hour.**
`converge-authority` exiting 1 every 15 minutes with `[diverged] behind=38 ahead=26`;
`dialpad-recording-gap` with its own JSON reporting `errors: 4`; `mesh-placement-monitor` still turning
`lakewooechsmini`'s unreachability into owner messages (P2260), some of which are answered `HTTP 500` by
the notify endpoint; `journal-commit` failing on its autosync half; the `sync` chain returning 1 after
189 s. Not one of those was visible an hour earlier.

**8.5 The authority's journal lineage converged — verified, on a branch, not yet live.**
Merge-tree named exactly seven conflicting paths: three generated index files, `alloc/bands.tsv`, and
three real wake-source mirrors. Resolution rules, each with a check: the generated paths take
origin/master (they rebuild); `bands.tsv` is **unioned** because it records which host claimed which id
range; the mirrors take the authority's copy and are then **diffed against the live files they mirror**
— which caught that the mirror in git was a 2026-09-29 snapshot, 15 KB behind `checkout-health.py`
alone. Result: **2,760 entries (more than either side), `check` 0 errors, `idguard` 0 collisions**,
pushed as `integrate/authority-master-20260930T161751Z` (`afbe6eb`, `3cd9f81`). **The live checkout was
not moved**: advancing the trunk is a separate decision, and the branch is the deliverable.

**8.6 The queue from here, in order.**
1. Land the integration branch (or decide not to).
2. The five failing jobs in `runs.tsv`, each with a recorded exit code and duration.
3. The 133 checks that report LIVE and open — the `## FIX NOW` lists name the edit and the proving
   command for every one.
4. 136 open entries still without a check; write one each.
5. Off-box replication of the control plane.

---

## 9. Round three, same day — the mechanisms get a home, and three lineages become one

**9.1 A three-state health gate (P170, P66).** Every gate that decided whether production was up used
`curl -fsS`, and `-f` fails on an HTTP error status while this API answers **HTTP 200 with `ok:false`**
when degraded. `scripts/server/health-gate.sh` now decides HEALTHY / DEGRADED / DOWN with exit codes
0/2/1 and an explicit rule that an unparseable or absent `ok` is DEGRADED, because an unknown health is
not health. `restart.sh`, `verify-production.sh` and `status.sh` ask it. Landed as the same anchored
edit on both sides of the app divergence (authority `9780dd8f`, repo `37a8ae6e`), scripts normalised to
LF.

**9.2 The API watchdog now judges health, not just liveness (P66).** It printed
`ok: secretary-api.service is active` every five minutes through twenty minutes of `ok:false`
("db check timed out (lock contention)"). It now counts consecutive bad observations, records the
third and tells the owner once, and recovers once at the sixth under the existing hourly cooldown.
Falsified on all three branches — and my own first version used `|| echo DOWN` on a command that exits
2 for DEGRADED, so a DEGRADED reading became `"DEGRADED\nDOWN"`: the exact defect class the gate exists
to catch, written twenty minutes later.

**9.3 The owner-message flood (P2260): 81 messages a day, from one line.** Measured from
`owner_message_queue`: 100 `proactive_update` rows in 24 hours, **81 identical** about one node, at
15–60 minute intervals against a 7200 s cooldown. Cause: `if ok: alerts.clear()` — `ok` is the
AGGREGATE, so a flapping node wiped every node's cooldown on each healthy pass. A node is now cleared
only when that node is good twice in a row, and repeats back off 2/4/8/16/24 h. Proven with a
closed-port notify sink: alert, quiet, quiet at 2 h, alert at 4 h, **3.0/day steady state**. The
reading half stays open (the probe still reports healthy nodes as unable to take work).

**9.4 Every guard has a home that reaches every machine.** `harness-config/scripts/guards/` is now the
source of truth for seven guards and four flag sources, with `install.sh` (sha-verified, CR-stripping,
dry-run) and the cron lines listed as notes rather than applied. Plus CRLF detection in the
cron-target guard for both crontab targets and critical paths.

**9.5 THE THREE JOURNAL LINEAGES ARE ONE, AND MASTER IS LANDED.**
The record existed in three lineages that could not see each other: origin/master 2,721 entries, the
authority's checkout 2,760 (38 behind / 26 ahead), ZABZ-TECH's branch 2,885. Merged in a throwaway
clone with a stated rule per conflict — and **five ids each named two different entries** (P2798,
P2799, H3061, L3052, L3105): the CFO/money-plane entries on the authority, the owner-text-channel and
disk-full entries on ZABZ-TECH. A live instance of P212/P184/P233 on the two newest lineages. The
newer entry was renumbered above every fetched ref and above the host band reservation
(H3061→H3088, L3052→L3142, L3105→L3143, P2798→P2812, P2799→P2813).

    entries              : 2932   (sides were 2760 / 2721 / 2885 — no entry lost)
    journal.py check     : 0 error(s)
    idguard              : collisions 0, divergences 0, uncomparable 0
    duplicate ids        : 0
    tracked journal/index: README.md alone

Landed as `1b921d7`, a **fast-forward of 109 commits**, with the old tip still an ancestor — nothing
dropped, no history rewritten, confirmed by reading it back from a second machine.

**Two of my own mistakes are on the record, both caught by checks rather than by me:** the first
resolver's id allocation used the local ceiling (which returned ids that already existed and
overwrote a real entry — `check` reported 4 errors and the clone was discarded), and renumbering
rewrote a heading without recomputing the `sha=` trailer (`check` reported it on all four; recomputed
with the tool's own `entry_hash`). Corrupting the record is the one thing this work must never do, and
the record's own integrity checks are what stopped it.

**Not done, deliberately:** the authority's LIVE checkout was not moved onto master. A
`git checkout -B master origin/master` returned nothing and exited non-zero; the branch and tree are
unchanged and intact. The trunk has converged; the host has not yet moved onto it.
