# Memory & continuity audit — v2

Measured 2026-10-14, on host **zabz-tech-linux** (Ubuntu 6.8.0-111, x86_64), against the
authority **secratary-cloud** (`ssh secratary-cloud`, hostname `secratary-cloud`, root) and every
reachable mesh node.

> **Node note.** The dispatch contract said this audit would run on the Windows node ZABZ-TECH
> (no bash, PowerShell only). It did not. It ran on **zabz-tech-linux**, which has bash/uname and
> reaches ZABZ-TECH over `ssh desktop-ts`. The Windows repo paths in the brief (`C:\Users\ezabz\code\...`)
> were reached by ssh where needed. Yoga (`192.168.50.244`) is **not reachable** (no route).
> `secratary-ts` resolves to the **frozen office box** `secratary`; it was read only.
>
> **Round-1 documents are missing.** `docs/dsh-evolution/20-memory-continuity-audit.md`,
> `docs/dsh-evolution/08-changes-made.md`, and `docs/dsh-evolution-v2/PROGRAM.md` do **not exist**
> on zabz-tech-linux, on secratary-cloud, or on the Windows checkout, and `git log --all` finds no
> such paths. I could not read them. I used the journal's own `SPEC-v2.md`/`AUDIT.md` and
> `docs/dsh-at-scale/PROGRAM.md` instead. This is itself a continuity finding (see §8).

---

## 1. Journal health, measured

The agent's journal is a v2 record store: one file per entry under `journal/entries/<kind>/<id>.md`,
with `index/` as a disposable cache and `state/status.tsv` as the append-only status-correction
layer. All commands below were run in the always-read checkout
`/home/zabz/code/harness-config/journal` (host ZABZ-TECH-LINUX) unless stated.

### 1.1 Raw command output

`python3 tools/journal.py status` (exit 0):

```
JOURNAL 2026-10-14 01:03 UTC · ZABZ-TECH-LINUX · format 2 · index/entries.tsv
ENTRIES handoff:954  lessons:1364  pain:453  decisions:391  wins:278   (total 3440)
OPEN PAIN 344
OWNER QUESTIONS 143 open · mirror generated 2026-10-14 01:03 UTC · authoritative: owner_decision_queue on the authority
  (mirror age 0 min -- refresh with: journal.py questions)
LEGACY DRIFT 0 — everything in log/** and the flat files is absorbed
CACHE fresh · stamp 2026-10-12 16:22 UTC · 3440 entries
CHECK 0 error(s) on the cheap rules (duplicate id, malformed entry, sha) — `journal.py check` adds dangling refs and legacy drift
```

`python3 tools/journal.py doctor` (exit 0):

```
root            /home/zabz/code/harness-config/journal
format          2 (entries/ present: True)
entries         3440 file(s), 3440 in the last cache build
cache           fresh · stamp 2026-10-12 16:22 UTC
legacy drift    0 — {}
lock            free
writable        True
python/sqlite   3.12.3 / 3.45.1 · fts5 yes
git             @985f9378, origin reachable
```

`python3 tools/journal.py check` — tail (exit 0):

```
WARN  H83 (handoff) has an empty body
WARN  dangling ref D103 (cited by D104) — nothing in entries/ has that id
...  (dangling refs; first 20 shown)
WARN  ... and 166 more warning(s) (--max-warn N)
INFO  entries/decisions/D105.md: heading carries the legacy id D67; this entry is filed as D105 (recorded in metadata)
INFO  ... and 73 more info line(s)
-- 0 error(s), 186 warning(s), 83 info
```

Machine-readable summary (`check --json`): `{"errors":0,"warnings":186,"info":83}`.

`python3 tools/journal.py costs`:

```
# read-path cost · 3440 entries · cache fresh
command               bytes       ms  byte target ms target  ok
status                 4956    151.9         6000       400  yes
list                   8115    129.6        12000       300  yes
show H3502             2205     28.1        12000        30  yes
search journal        10173    380.4        12000       300  NO
newest handoff         2204    118.5        12000       200  yes
kinds                   300    116.6         4096       200  yes
# entries/ 9589102 B · index/ README.md:2628 aliases.tsv:63242 entries.tsv:842995 journal.db:19030016 stamp.json:673 · frozen log/** 1417411 B
```

`python3 tools/journal.py stats`:

```
  per kind:  decisions:391  handoff:954  lessons:1364  pain:453  wins:278
  per month: (undated):245  2026-09:2713  2026-10:482
  open 3298 / closed 142
  tags: legacy-import:643  lpt:172  mesh:158  verification:105 ...
```

### 1.2 Counts by kind; open/closed pain; open owner questions

| Quantity | Value | Command |
|---|---|---|
| Entries, total | **3440** | `journal.py doctor` / `stats` |
| handoff / lessons / pain / decisions / wins | 954 / 1364 / 453 / 391 / 278 | `journal.py kinds` |
| All entries open / closed | 3298 / 142 | `journal.py stats` |
| **Open pain** | **344** (`status`), 345 by `status.tsv` reconciliation | `journal.py status`; see below |
| Pain effectively closed | 108 (96 done + 9 superseded + 3 retracted) | last-row-per-id in `state/status.tsv` |
| **Open owner questions (mirror)** | **143** | `journal.py status` |
| Open owner questions (authority DB) | **155 pending** | `sqlite3 -readonly /root/authority.db` |

The 344-vs-status.tsv reconciliation: `state/status.tsv` has 227 rows, of which the **last** row per
pain id is 96 `done`, 9 `superseded`, 3 `retracted` = 108 closed; 453 − 108 = **345 open**, and the
tool prints 344 (one id is `blocked`/`open`). The naive "count `done` rows" gives 183 because the file
is append-only and carries older transitions for the same id. **The entry bodies themselves are not
the status**: 452 of 453 pain files carry `|open` in their embedded header even though 108 are
closed by `status.tsv`. Body text is a historical claim; `status.tsv` is the correction.

### 1.3 Every checkout on every reachable machine — they do not agree

`find … -path '*/journal/tools/journal.py'`, then count `journal/entries/**/*.md`:

| Machine | Checkout | Entries | HEAD |
|---|---|---|---|
| **zabz-tech-linux** | `/home/zabz/code/harness-config/journal` | **3440** | 985f9378 |
| zabz-tech-linux | `code/_worktrees/harness-config/project-loop/journal` | 3440 | fedaa936 |
| zabz-tech-linux | `code/harness-config/_fleet/owner-queue/journal` | 3440 | 985f9378 |
| zabz-tech-linux | `code/harness-config/_fleet/project-loop-w5/journal` | 3440 | 846bd195 |
| zabz-tech-linux | `code/_meshfix/wt/mfx-transport/journal` | 2932 | b6b501d1 |
| zabz-tech-linux | `code/_meshfix/wt/mfx-provider/journal` | 2932 | 4f4d0145 |
| zabz-tech-linux | `hk367-consumer/journal` | 2958 | aaa7470 |
| zabz-tech-linux | `hk367-node2-20261002T0837Z/journal` | 2932 | 1893dc1 |
| zabz-tech-linux | `hk367-consumer-autosync-20261002T0856Z/journal` | 2932 | 84ea430 |
| **secratary-cloud (authority)** | `/root/code/harness-config/journal` | **4006** | 37c62333 |
| secratary-cloud | `/root/work/wt-cfo43-clean/journal` | 3348 | 317fe970 |
| secratary-cloud | `/root/work/wt-cfo43/journal` | 3348 | 17e7fa63 |
| secratary-cloud | `/opt/company/data/harness-config.bak-20260915T0200Z/journal` | 1316 | — |
| **secratary (office, frozen)** | `/home/zabz/code/harness-config/journal` | **3489** | a51a5565 |
| secratary | `harness-config.pre-unify-20260922/journal` | 2697 | b7885ca |
| secratary | `_converge-all-20260930T170223Z/journal` | 2932 | 1b921d7 |
| secratary | `_dsh020/repo.retired-20261005T064607Z/journal` | 2827 | — |
| secratary | plus 11 more migration/staging checkouts (640–2760 each) | | |
| **LakewooechsMini (mac-mini)** | `/Users/lpt/code/harness-config/journal` | **1644** | — |
| LakewooechsMini | `code/_worktrees/harness-config/{project-loop,frontier-gap,weekly-evolution}/journal` | 3550 each | — |
| LakewooechsMini | `code/_worktrees/harness-config/owner-queue/journal` | 1643 | — |
| LakewooechsMini | `code/_worktrees/harness-config/authority-order/journal` | 3550 | — |
| **ZABZ-TECH (Windows)** | `C:\Users\ezabz\Code\harness-config/journal` | **3905** | — |
| ZABZ-TECH | `.dsh\tmp\hc-origin\journal` | 3429 | — |
| ZABZ-TECH | 28 further clones/worktrees under `C:\Users\ezabz\Code\...` | 1850–3440 each | — |
| ZABZ-YOGA | unreachable — no route | | |

**They agree nowhere.** The five "main" checkouts alone read **3440 (linux) / 3905 (Windows) / 4006
(authority) / 3489 (office) / 1644 (mac-mini)**, a spread of 2,362 entries. The authority is **566
entries ahead** of the linux mesh checkout and ~100 ahead of the Windows main checkout; the mac-mini's
main checkout is 1,900+ behind the authority. A session's view of "the record" depends entirely on
which box it opened.

The authority's journal is one branch, `hk/28-refresh-deployed-sources-20261013` (HEAD 37c62333), whose
git remotes are **`origin = /root/hc-main.bundle` (a bundle on the same disk)** and
`vault = 2.28.33.58:/srv/git/harness-config.git`. The linux checkout's remotes are
`origin = secretary:/home/zabz/harness-config.git` (the office box) and `mirror`. There is no single
shared remote between them.

### 1.4 Divergent git refs; base-id collisions

* Local checkout: **107 refs**; **101 of them carry `journal/entries` content that differs from
  `main`** (`git diff --name-only main <ref> -- journal/entries | wc -l > 0`). 36 refs are explicitly
  named `diverged-<HOST>-<date>` (7 ZABZ-TECH, 14 ZABZ-YOGA, 15 secratary).
* Authority clone: only **13 refs** (fewer fetched).
* `journal.py pairs`: **121 historical base-id collisions** — exactly round 1's number. These are
  *base numbers* shared by distinct suffixed ids (`D17`, `D17b`, `D17c`), not duplicate ids.
  `journal.py check` today reports them as **INFO** ("heading carries the legacy id … recorded in
  metadata") and **0 errors**; `pairs` still lists them as historical. So the collision *count* is
  unchanged, but `check` no longer treats them as errors — it disambiguates by suffix and records the
  legacy id in metadata.

---

## 2. Can the journal be trusted? — a verified table

Ten things the record claims, each checked against the live system **today**. "Verified" means a
command printed the claimed fact; "contradicted" means it printed something else. The distinction
that matters throughout: a record can be *accurate when written* and *false now*, and it can be
*self-consistent* while the system is not.

| # | What the record says (entry / file) | What is true now | Command that showed it | Verdict |
|---|---|---|---|---|
| 1 | **H3637** (2026-10-14T00:24Z): one branch `waze-fleet-data-dns-and-roaming-20261014` @ `5fb760aa`, based on `origin/master` `24c7da84` | Both commits exist; that branch is the checked-out branch in `/opt/company` | `ssh secratary-cloud 'cd /opt/company && git rev-parse 5fb760aa 24c7da84; git branch'` | **VERIFIED** |
| 2 | **H3636**: DNS filter deployed at `/opt/waze-mdm/dns/doh_filter.py` on `waze-mdm-01`, installed sha `23434d4b…` | File present, `sha256sum` = `23434d4ba8fd40c6c299be2a36fc6fcb4f1200d42c914d5e8cbf4135fd87750c`; the two named backups exist | `ssh hetzner 'hostname; sha256sum /opt/waze-mdm/dns/doh_filter.py'` | **VERIFIED** |
| 3 | **P2539** (`FIXED 2026-09-25, code deployed`): `shutdown()` tries `homeassistant.stop` → `homeassistant.shutdown` | Code exists: `def shutdown(...)` at `home_assistant.py:396`, with `homeassistant.stop`/`homeassistant.shutdown` handling | `ssh secratary-cloud 'grep -n "def shutdown\|homeassistant.stop" /opt/company/app/services/home_assistant.py'` | **CODE VERIFIED; entry still open** |
| 4 | **P327** (`WHAT WOULD FIX IT: (a) DONE — a source-of-truth record now exists at docs/personal/health/`) | Directory exists on the authority `/opt/company/docs/personal/health` (+ `records/labs`) | `ssh secratary-cloud 'find / -maxdepth 5 -path "*docs/personal/health*"'` | **VERIFIED** |
| 5 | **P17c** (`done`, FIXED 2026-09-14): lock is a `journal/.lock` opened `O_CREAT|O_EXCL`, stale-broken at 600 s | Serialization exists, but the mechanism changed: it is now an **OS lock** (`flock` / `msvcrt.locking`); the source comment says the old create-with-`O_EXCL` path was removed because its stale rule unlinked a live lock. `LOCK_STALE_SEC = 600` remains | `grep -nE "O_CREAT\|O_EXCL\|flock\|msvcrt" journal/tools/journal.py` (lines 2771-2912) | **RESOLVED, but the documented mechanism is stale** |
| 6 | **NOW.md** (the always-read state page): "**707 entries** (23:38 UTC), 0 redundant copies, check **0 errors**" | 3440 entries today; `check` still 0 errors | `journal.py doctor`, `journal.py check` | **CONTRADICTED (entries); errors still 0** |
| 7 | **P10** is retracted in its own title, so it is not open work | It is counted open: no `status.tsv` row, `show P10` prints `open`, and it appears in the open-pain list / pain-check as `LIVE` | `grep -P '^pain\tP10\t' state/status.tsv` → none; `journal.py show P10` | **CONTRADICTED (retracted-but-open)** |
| 8 | **H3500**: "Committed **6be7f7370** and pushed (`abc18a2ce..6be7f7370 main -> main`)" — lpt-hub case file | The case file `docs/customer-operations/cases/sd-card-fisher-9145702075-2026-10-11.md` exists, but `6be7f7370` is **in no ref** of the reachable lpt-hub clone; the file's adding commit is `dc1d7d5` (2026-10-12) | `ssh secratary-cloud 'cd /root/work/lpt-hub && git log --all --oneline \| grep 6be7f73; git log -1 -- <case file>'` | **CONTRADICTED (commit not found)** |
| 9 | **P72** (`done`): "`git ls-tree` over origin/master's journal shards counts **723** entry markers and origin/master's index has 723 rows, exactly matching the local tree's 723" | Local mesh checkout has 3440; the authority 4006; office 3489. The claim was true of a 723-entry corpus and is meaningless now | `journal.py doctor`; `ssh secratary-cloud 'find …/entries -name "*.md" \| wc -l'` | **STALE (true then, false now)** |
| 10 | **P4/P58 class** ("nothing closes an entry when its cause is removed"): the pain-check runner exists to measure it | `pain-check.py --write-status` reports **45 FIXED, 112 LIVE, 25 UNKNOWN**, and a `fixed_and_still_open` list of **43 ids**. It did **not** close them (the cron runs without `--close`) | `cat ~/.pain-check/status.json` on secratary-cloud | **VERIFIED deb/mechanism; 43 fixed-but-open today** |

**How much "fixed-but-still-open debris" is there?** Two independent measures agree that it is real and
bounded:

* **Instrumented (authoritative):** the scheduled pain-check suite measured **43** open entries whose
  own executable check now says `FIXED` (45 `FIXED` verdicts total, 43 still open), 112 `LIVE`, 25
  `UNKNOWN`. status.json dated **2026-10-13T06:25:24Z**.
* **Text scan (this checkout only):** a tight scan of the 344 open pain entries for
  `RETRACTED/FIXED/RESOLVED/SUPERSEDED 20xx` in the first 2 KB returned **7** — P10, P234, P344,
  P2539, P2852, P2879 (partly fixed), P2926. A looser scan returns 106, almost all false positives
  ("a closed database", "closed / paid"), which is why the loose number is untrustworthy.

So the round-1 finding is **still true, and now measurable**: ~43 entries are known-fixed and still
counted open, and the suite that knows this runs daily but is not allowed to close them by default.

---

## 3. Does anything write itself?

### 3.1 Scheduled jobs that touch the journal

Decoded from the authority root crontab (`crontab -l`, base64 payloads) and systemd:

| Job | Schedule | Node | Last run / result | What it does |
|---|---|---|---|---|
| `journal-commit` (`/usr/local/bin/journal-commit.sh`) | `*/15 * * * *` | secratary-cloud | **rc=1 nearly every tick**; e.g. 01:00:06 "committed 1 path on main at 37c62333", 01:00:07 push **failed** | Commits `journal/` only, then pushes to `vault`; **every push is rejected non-fast-forward** |
| `estate-alerts-to-journal` (timer → oneshot) | every 10 min | secratary-cloud | 01:02:00 `Deactivated successfully`; verdict `{ok:22,info:5,warn:1,crit:3}`, "nothing to file" | Files estate-monitor criticals as journal entries (idempotent) |
| `pain-check` | `20 6 * * *` | secratary-cloud | 2026-10-13T06:20:01, **rc=1 (by design)**, 323 s | Runs C1-C5 + per-id checks, writes `~/.pain-check/status.json`; **does not close** unless `--close` |
| `PersonalSecretary-HarnessSync` | ~every 15 min | ZABZ-TECH | 2026-10-13 21:02:01, result **0** | Syncs `~/.dsh` from harness-config (does not, by its own design, commit the journal) |
| `PersonalSecretary-PushHarnessConfig` | ~every 15 min | ZABZ-TECH | 2026-10-13 21:12:41, result **0** | Pushes harness-config; the journal is a passenger |
| `wake-fanout` / `wake-balance` / `run-wake-sources` / `wake-cost` | 1 min / hourly / 6-hourly / 15 min | secratary-cloud | all **rc=0** | Wake queue (see §7) |
| local user crontab | — | zabz-tech-linux | `crontab -l` → *permission denied* (non-root) | none observed |

**The one job that is supposed to publish the journal is failing.** `journal-commit.sh` commits on the
authority (so the working tree is clean: `git status --porcelain journal` = 0) but the `vault` remote is
stuck at `8aa139f` while local `main` advanced `5bec464 → 37c62333`, and every push is refused:

```
[failed] push to vault main -- To 2.28.33.58:/srv/git/harness-config.git
 ! [rejected]  HEAD -> main (non-fast-forward)
```

It exits 1 on those ticks. Nothing else in the estate notices: `journal-commit` has no freshness
monitor I could find, and `authority-repo-push` (06:00 daily) pushes `/opt/company` to GitHub, not the
journal. If `journal-commit` stopped, entries written with `journal.py append` would still land as
local files, but nothing would commit or publish them — and the authority's `origin` is a bundle on
its own disk, so "committed" would again mean "on one NVMe".

### 3.2 `journal-union.py` — not found

The brief's round-1 finding was that `journal-union.py` exists and nothing schedules it. I could not
find `journal-union.py` on **zabz-tech-linux, secratary-cloud, under `C:\Users\ezabz` recursively on
ZABZ-TECH, or under `/Users/lpt` on the mac-mini**; `git log --all -- '*journal-union*'` in the linux
checkout is empty; and no cron line or systemd unit mentions `union`. Either it lives on Yoga (which
is unreachable) or it has been removed. **I cannot confirm it exists today.**

### 3.3 Does an ERROR get noticed?

`journal.py check` reports **0 errors** on the linux checkout (186 warnings, 83 info). Warnings are
dangling refs and legacy-id headings; INFO is the disambiguation. **No scheduler keys on
`journal.py check`'s exit code.** The nearest thing is `pain-check`'s C1.sh, which includes one
per-id check (P200) that asserts "`journal.py check` reports 0 errors" as *one line among ~34*; a
new error would be invisible unless a human reads `status`/`check` or that one assertion flips. So:
**an ERROR is not noticed by anything; it is noticed by a person, eventually.**

---

## 4. The owner decision queue

Authoritative table `owner_decision_queue` in `/root/authority.db` (26.9 GB; queries read-only,
small-table aggregates only).

### 4.1 Row counts, severity, age

| Status | Rows |
|---|---|
| resolved | 229 |
| **pending** | **155** |
| dismissed | 71 |
| answered | 38 |
| **total** | **493** |

Pending severity: **critical 2, high 38, medium 104, low 11**.

Oldest pending: **id 78, asked 2026-09-16T19:40:24Z — 28 days old** (mother's US-Mobile port fields).
Next: id 110 (2026-09-18, Elantra repair), id 169 (2026-09-25, Felician balance), id 206
(2026-09-30, NJ DOL), id 207 (2026-09-30, T-Mobile still billing).

### 4.2 Owner vs engineering — with the rule stated

**Rule used.** A pending row is **owner-only** if resolving it needs an authority or private fact this
seat does not have: a spending/charging/billing *decision*, outbound contact or customer-facing
wording, a legal/tax/regulatory filing or position, family/personal money, an irreversible action, or
a taste/policy call. Everything else is **engineering** — resolvable by inspecting systems,
reconciling records, writing code, merging, or changing configuration. "What was actually collected"
is engineering (the books can be read); "what should we charge" and "may I send this" are the owner's.

Applying that rule by keyword-assisted pass over the 155 pending questions:

* **Owner-only: 41** (e.g. 78 family line, 110 car spend, 169 who pays tuition, 206 NJ DOL call,
  207 T-Mobile, 228 personal funding, 261 Deep Infra card, 279 Amex decline, 290/307/312/323/325/330/332
  pricing & customer wording, 315 identity, 449 fund Telnyx, 463 Audible, 465 ST-50 tax, 482 Chase
  card, 490 customer outcome, 492 NJ payroll).
* **Engineering: 114** — dominated by the **84 rows dated 2026-10-09** that are production-record
  reconciliation ("was the $X collected", "is this order dead", "was the device returned"), plus merges,
  restores, schema/config and service items.

This is close to round 1's "~137 of 162 engineering"; the count moved with the queue (162 → 155) and
with the pass rule. The important structural fact is unchanged: **the queue is mostly production
reconciliation that this seat can do**, and the genuinely owner-gated items cluster in money, tax,
family, and customer-facing wording.

### 4.3 Top five by severity

| # | Id | Sev | Asked | Subject |
|---|---|---|---|---|
| 1 | **492** | critical | 2026-10-13 | NJ payroll returns have **no filer** since Gusto was cancelled 8 Oct — NJ-927 + WR-30 for 06/2026 is **75 days late**; 09/2026 due 30 Oct |
| 2 | **484** | critical | 2026-10-13 | Authorise reclaiming ~5 GiB of shift scratch on the authority (`/` 89% full, 8 GiB free, 26.9 GiB DB) |
| 3 | **471** | high | 2026-10-13 | 268 card-terminal payments worth **$28,142.70** cannot be tied to any work order/customer |
| 4 | **468** | high | 2026-10-13 | 20 orders totalling **$3,921.63** flagged CAPTURED with no payment row |
| 5 | **465** | high | 2026-10-13 | NJ sales-tax Q3 2026 (ST-50) due **2026-10-20**; portal last filed 2026-06-30 |

Also critical-adjacent: 449/493 (Telnyx account −$0.01, both SIMs blocked, fleet has no data).

### 4.4 The mirror — fresh, but only because someone read it

* Authority mirror `journal/state/owner-questions.md`: mtime **2026-10-14T00:53:03Z**.
* Linux mirror: mtime **2026-10-14T01:03:33Z** (it was 2026-10-12 before I ran `status`).
* **What refreshes it:** `journal.py status` calls `_maybe_refresh_questions()` — if the mirror is
  older than **60 minutes**, it spawns `journal.py questions`, which reaches the authority and
  **takes the journal's global write lock**. There is **no cron/systemd job** that runs `questions`.
  So the mirror is fresh exactly when a session has recently read the page; it is a side effect of a
  read, not a keeper. (The tool guards readers by skipping the refresh when the lock is held.)
* The local mirror says **143 open**; the authority DB says **155 pending**. A machine reading its
  local mirror can be 12 questions behind.

---

## 5. The company's memory, measured

Everything below lives on **secratary-cloud**; the authority is the sole writer, so all queries were
read-only.

### 5.1 ChromaDB and mem0

| Store | Path | Collections | Vectors | Last write |
|---|---|---|---|---|
| ChromaDB (active) | `/opt/company/data/chromadb/chroma.sqlite3` (2.4 GB; dir 2.9 GB) | **7** | **393,113** | — |
| ↳ `workspace_all` | | | 193,487 | **2026-06-12 00:07** |
| ↳ `company_data` | | | 176,036 | **2026-06-11 21:56** |
| ↳ `workspace_code` | | | 17,451 | **2026-06-11 19:56** |
| ↳ `memories` (384-d) | | | 6,139 | **2026-10-14 01:05** |
| ↳ `knowledge`, `vscode_chats`, `email_sent_history` | | | 0 | — |
| ChromaDB (stale duplicate) | `/opt/company/data/chromadb/chromadb/chroma.sqlite3` (11 MB, mtime May 4) | 2 | 2,092 | frozen |
| mem0 | `/opt/company/data/mem0/chroma.sqlite3` (311 MB; dir 1.1 GB) | 3 | **131,014** | — |
| ↳ `mem0_memories` (1536-d) | | | 123,873 | **2026-10-14 01:08** |
| ↳ `mem0_memories_entities` | | | 7,142 | **2026-10-14 01:06** |
| ↳ `mem0migrations` | | | 0 | — |

`MEM0_ENABLED=true` in `/opt/company/.env`. So **mem0 and the small `memories` collection are live**;
the three big workspace collections have not been written since **June 2026** — they are read
(see below) but frozen.

### 5.2 The authority DB memory tables

| Table | Rows | Newest write | Notes |
|---|---|---|---|
| `memories` | **25,049** (max id 25,056) | created/last-accessed **2026-10-14T01:05:48** | `active` 25,036, `superseded` 13 |
| `memory_vectors` (vec0, 1536-d) | not counted | — | `vec0` module unavailable to the CLI; shadow `memory_vectors_info` = 4 |
| `memory_entries` | **0** | — | dead table |
| `procedural_experiences` | **18,526** | **2026-10-14T01:07:11** | PRAXIS-style store |
| `memory_write_outcomes` | 4,087 | **2026-10-14T01:05:50** | written 3,218; skipped_policy 775; deduplicated 82; partial 11; **failed 1** |
| `project_knowledge` | not counted (scan avoided) | — | schema present, FTS triggers present |

**Read evidence inside `memories`:** cumulative `sum(access_count)` = **421,032**. Distribution:
`access_count = 0` → **22,401 (89.4%)**; 1-4 → 1,515; 5-19 → 654; ≥20 → 479. So ~2,648 memories
(10.6%) have ever been read, and recall is concentrated in a few hundred rows. (Caveat: new rows carry
`last_accessed_at = created_at` with `access_count = 0`, so `last_accessed_at` alone is not proof of a
read; the non-zero `access_count` values are.)

### 5.3 Does the company's memory change behaviour, or is it write-only?

**It changes behaviour — on one path.** Verified read call sites:

* `app/assistant_chat.py:5087` — `from app.services.semantic_memory import get_relevant_context` and the
  result is appended to `live_ctx_parts`; **:5111-5122** — when `mem0_enabled`, `get_relevant_memories`
  is called and formatted as `[Mem0 memories:]` into the same **live prompt**. So both ChromaDB's
  `memories` collection and mem0 are retrieved and injected into the assistant's reply context.
* `app/services/email_style.py:209/351` — queries the `email_sent_history` collection for style.
* `app/services/context_manager.py:351-364` — reads `procedural_memory.format_experiences_for_prompt`
  and puts it in the prompt sections.
* `app/services/workspace_search.py` — `collection.query(...)` over `workspace_code`,
  `vscode_chats`, `company_data`, `workspace_all`.
* `app/services/memory_consolidation.py` / `autopilot.py:8630` — consolidation every 4 h; last run
  `2026-10-13T21:53:17Z`.

**But it is also substantially write-only:**

* `memory_entries` has **0 rows** — any writer targeting it writes to a dead table.
* **89.4% of `memories` rows have never been read**; the live retrieval is a thin slice.
* Three of the seven Chroma collections — **386,974 of 393,113 vectors** — are frozen since June, so
  the assistant's "semantic memory" over company data is a snapshot of four months ago.
* The read path is confined to `assistant_chat`, `email_style`, `context_manager`, `workspace_search`.
  Agents writing memory from elsewhere (autopilot, dept agents) have no matching reader, so those
  writes are effectively **write-only**.

Verdict: **not a write-only store, but the write volume is ~9× the read volume, and the largest
store is stale.** The `memories` table and mem0 do feed the live chat prompt; the workspace
collections are read but frozen; `memory_entries` is dead.

---

## 6. Continuity across sessions

`journal.py newest handoff` is machine-relative. On the authority it returns **H3637** (2026-10-14
00:24Z); on this linux checkout it returns **H3502** (2026-10-11 22:00Z). The three real recent
handoffs are on the authority:

| Handoff | Claims | Picked up? |
|---|---|---|
| **H3637** | one branch `waze-fleet-data-dns-and-roaming-20261014` @ `5fb760aa` based on `origin/master` `24c7da84`; DNS filter live; DataRoaming route **built, not deployed** | **Live branch and both commits verified.** The named next action is still correct: `/opt/waze-mdm` on `waze-mdm-01` contains no `data-roaming` route (only dead `allowDataRoamingModification` profile keys). *Only visible from the authority checkout.* |
| **H3636** | `/opt/waze-mdm/dns/doh_filter.py` sha `23434d4b…` deployed and verified; test file restored to 11 cases | **File exists with that exact sha; both named backups exist.** Its open items (P3176 no data monitor, `live_data_session` lag) are still open. |
| **H3635** | DRN 2002 has Data Roaming off on a Telnyx eSIM; whole fleet WiFi-only; owner must tap the toggle | Names no branch or file to re-read; the device state could not be checked from here. **Not verified.** Its next action (owner taps, then confirm consumed-bytes move) is still the right shape. |

**What carries and what does not.** A new session gets (a) whatever `NOW.md` says, (b) the newest
handoff *in its checkout*, (c) the open-pain list, (d) the owner-question mirror. What does **not**
carry reliably:

* The **newest 566 entries** (H3635-H3637 included) live only on the authority's non-main branch;
  the linux mesh checkout cannot see them.
* **The plane has no shared remote.** The authority publishes to `vault` (rejected) and a local
  bundle; the linux checkout pulls from the office box.
* **`NOW.md` is three days stale** on the authority (mtime 2026-10-11T08:33Z) and older elsewhere,
  and it still advertises "707 entries".
* The **mirror** is fresh only if someone read it (§4.4).

So "what carries" is: a stale first page, a stale handoff, and a stale question list — from whichever
checkout the session happens to open. The three newest handoffs name a live branch and files that
exist, but a session on any machine other than the authority never reaches them.

---

## 7. The wake system

Wake is the path by which work happens with no session open: a flag is filed, `wake-fanout` keeps N
dispatcher shifts in flight, and a dispatcher releases a row into a headless DSH session.

**It is running.** `~/.cron-status/runs.tsv`, `wake-fanout` every minute, **rc=0**; `wake-cron.log`:

```
fanout: in flight 3 (store 3, processes 3), target 3, ceiling 8, waiting 170
fanout: 3 in flight, at target - starting nothing more
fanout: started 0 this run; processes 3
...
fanout: shift #1 (pid 1555652) CLAIMED; processes now 3
```

`wake.py stats` (2026-10-14T01:10:39Z):

```
states: new 179, claimed 3, done 554, failed 91, unverified 1, dropped 16
selftest: 157 rows (excluded from counts)
released_today 25 · failed_today 1 · spend_today_usd 1.752247
caps: max_per_day 500, max_per_source_per_hour 12, max_usd_per_day 25.0,
      cooldown_sec 1800, lease_sec 1200, max_attempts 2, night_quiet true, paused false
caps_in_force: ["source_cap: project-keepalive 12/12 in the last hour"]
```

**The round-1 baseline, re-measured.** `~/.sms-inbox/wake-failed/` holds **289 directories and 819
files** (round 1: 205 dirs). By cause: **`daily-cap` 197**, `row-gates` 38. By date: **288 on
2026-10-13**, 1 on 2026-10-11, **none after 14:32Z on 13 Oct**. The cluster is a single episode:

* Window 2026-10-13T10:45→14:32Z; every claim.json reads `{"ok": true, "row": null, "blocked_by":
  "daily-cap"}` while `spend_today` was a fraction of the $25 cap.
* `wake-dispatch.sh` and `wake-fanout.sh` were rewritten at **14:33:53-54Z**; the next tick's
  failures stopped. The dispatch script's own comment records the drift it was fixing: wake.py's
  release cap (500) versus cron's (150), "the looser value wins", and a string-vs-float compare that
  hid it.
* Today, the release cap is 500 and the cost cap $25, and **neither is in force**; the only cap
  tripping is `project-keepalive` at 12 releases in the hour.

**What it refuses, and why.** `wake.py` documents and enforces: a pause file; a release/day cap; a
USD/day cap; a per-source hourly cap; `night-quiet` (low-priority releases only 13:00-03:00 UTC);
session recursion (`WAKE_SESSION` set → every flag refused). The "nothing on a timer may file work"
rule is explicit in its docstring.

**If it stopped:** no headless sessions would start; flags and owner texts would pile up. The nearest
monitor is `wake-balance --guard --warn 75` (rc=0) and `sentinel-freshness`; I did not find a
freshness alarm that fires specifically when `wake-fanout` stops.

---

## 8. What is lost

### 8.1 The agent's memory (journal)

| Lost class | Evidence today | Smallest change that stops it |
|---|---|---|
| **Cross-machine divergence** — entries written on one node are invisible on another | main checkouts read 3440 / 4006 / 3489 / 1644; authority 566 ahead of the linux mesh checkout | One canonical checkout per node **plus** a scheduled `git fetch` into a read-only view; or a union index that reads every ref (what `journal-union.py` was presumably for) |
| **Unpublished journal commits** | `journal-commit` commits locally, but every push to `vault` is rejected non-fast-forward; remote stuck at `8aa139f` while local is `26aa61c`; `origin` is a bundle on the same disk | Reconcile `vault` **once**; the existing 15-min job then publishes with no new machinery |
| **Unpushed local entries on laptops** | pain-check measures ZABZ-TECH "ahead 211", with untracked entry files on no ref | Make the harness-sync task commit+push `journal/` (it currently syncs presets only) |
| **Status truth split from the body** | 452/453 pain bodies say `open`; `status.tsv` closes 108; a body-only reader sees phantoms | Have `show`/`status` print the effective status from `status.tsv` (the tool already does for `status`; the TITLE/body still says RETRACTED) |
| **Fixed-but-still-open debt** | pain-check: **43** open entries whose check says FIXED; `--close` is not in cron | Add `--close` to the scheduled run **or**, safer, have the existing freshness flag wake a session with the 43-id list |
| **Stale first page / mirror** | NOW.md "707 entries" (truth 3440); authority NOW.md 3 days old; mirror refreshed only by a read | Add a scheduled `journal.py questions` + a small `NOW.md` regeneration, or stop advertising the number |
| **`journal-union.py`** | not found on any reachable machine or in git history | If it is wanted, commit it and schedule it; if it is gone, delete the dangling reference |

### 8.2 The company's memory (authority)

| Lost class | Evidence today | Smallest change that stops it |
|---|---|---|
| **Dead writer target** | `memory_entries` = 0 rows while writers exist | Delete the dead writer, or repoint it at `memories` |
| **Frozen vector stores** | `workspace_all`/`company_data`/`workspace_code` = 386,974 of 393,113 vectors, unchanged since 2026-06-11/12, yet read by `workspace_search` | Schedule the workspace reindex that last ran in June |
| **Write-only memory** | 89.4% of `memories` (22,401/25,049) never read; only 4 read sites | Either add recall to the agents that write, or accept it as an archive and stop counting it as "memory in use" |
| **Uninspectable vectors** | `vec0` module unavailable to the CLI, so `memory_vectors` cannot be counted or verified | Ship the sqlite-vec extension with the ops tooling |
| **No freshness signal** | nothing alarms when a memory store stops being written | Reuse `estate-monitor`/`pain-check`: one threshold per store, filed as a journal entry |

---

## WHAT I COULD NOT DETERMINE

1. **The round-1 audit documents were not found.** `docs/dsh-evolution/20-memory-continuity-audit.md`,
   `docs/dsh-evolution/08-changes-made.md`, and `docs/dsh-evolution-v2/PROGRAM.md` do not exist on
   zabz-tech-linux, secratary-cloud, or under `C:\Users\ezabz\code` on ZABZ-TECH; `git log --all`
   finds no such paths. I could not read round 1's method, so §2's comparisons to "round 1" are to
   the brief's summary of it, not to the document.
2. **Windows entry counts — resolved.** A corrected PowerShell enumeration returned the counts in
   §1.3 (Windows main checkout = 3905). The first attempt had a path bug and is superseded.
3. **ZABZ-YOGA** is unreachable (`No route to host`), so its journal checkout count is unmeasured.
4. **`journal.py check` on the authority** was **not** run (to avoid any index/lock write on the
   26.9 GB-writer box). Its 0-error/186-warning figures are from the linux checkout only; the
   authority's `check` number is **not verified**.
5. **`memory_vectors` row count** is unknown (no `vec0` module). `project_knowledge` row count was
   skipped to avoid a full scan on a 95%-full/26.9 GB DB.
6. **H3635's device state** (DRN 2002 Data Roaming) could not be checked — no Telnyx API or device
   access. I did not `docker exec` the fleet-api container, so "the DataRoaming route is not deployed"
   rests on the filesystem grep, not the running container.
7. **`journal-union.py`** could not be found on any reachable machine (zabz-tech-linux,
   secratary-cloud, ZABZ-TECH recursive under `C:\Users\ezabz`, mac-mini under `/Users/lpt`) or in
   git history. It is not on a scheduler either.
8. **The local user crontab** on zabz-tech-linux is unreadable as non-root, so a user-level journal
   job there is not excluded.
9. **`memories.access_count`** may be incremented on write as well as read; I treat non-zero counts
   as evidence of reads, but I did not read the incrementing code path to prove it.
10. **The 41/114 owner-vs-engineering split** is a stated keyword-assisted rule, not manual review of
    all 155; borderline rows (pricing, identity, "delete the record") could move either way.

---

## EVIDENCE LOG

All timestamps UTC. Commands run as the invoking user; `secratary-cloud` over
`ssh -o BatchMode=yes`. Read-only on the authority except the single report file.

**Host / reachability**
- `hostname` → `zabz-tech-linux`; `uname -a` → Linux 6.8.0-111-generic x86_64.
- `ssh secratary-cloud 'hostname; whoami'` → `secratary-cloud`, `root`.
- `ssh desktop-ts 'powershell … hostname'` → `zabz-tech`; `ssh mac-mini 'hostname'` → `LakewooechsMini`;
  `ssh hetzner 'hostname'` → `waze-mdm-01`; `ssh yoga 'hostname'` → **No route to host**.

**Journal**
- `python3 tools/journal.py status` / `doctor` / `check` / `check --json` / `costs` / `stats` / `kinds`
  / `pairs` / `list --kind pain --status open --limit 1000 --json` (all in
  `/home/zabz/code/harness-config/journal`).
- `tail -n +2 state/status.tsv | awk -F'\t' '{print $1"\t"$3}' | sort | uniq -c`.
- Python reconciliation of last-status-per-id against `entries/pain/*.md`.
- `find /home/zabz -path '*/journal/tools/journal.py'` + per-root `find entries -name '*.md' | wc -l`.
- `ssh secratary-cloud 'find /root /opt/company -path "*/journal/tools/journal.py"; …'`.
- `ssh secratary-ts 'find /home/zabz -path "*/journal/tools/journal.py"; …'`.
- `ssh mac-mini 'find /Users/lpt -path "*/journal/tools/journal.py"; …'`.
- `git for-each-ref | wc -l`; loop of `git diff --name-only main <ref> -- journal/entries | wc -l`.
- `journal.py pairs` (121).
- Authority: `cat journal/index/stamp.json`, `git rev-parse HEAD`, `git remote -v`,
  `git for-each-ref | wc -l`, `find entries/<kind> | wc -l`, `ls -l NOW.md state/owner-questions.md`.

**Sections 2, 3**
- `ssh secratary-cloud 'cd /opt/company && git rev-parse 5fb760aa 24c7da84; git branch'`.
- `ssh hetzner 'sha256sum /opt/waze-mdm/dns/doh_filter.py; ls -la /opt/waze-mdm/dns/'`.
- `ssh secratary-cloud 'grep -n "def shutdown\|homeassistant.stop" /opt/company/app/services/home_assistant.py'`.
- `ssh secratary-cloud 'find / -maxdepth 5 -path "*docs/personal/health*"'`.
- `grep -nE "O_CREAT|O_EXCL|flock|msvcrt|LOCK_STALE" journal/tools/journal.py`.
- `grep -P '^pain\tP10\t' state/status.tsv`; `journal.py show P10`.
- `ssh secratary-cloud 'cd /root/work/lpt-hub && git log --all --oneline | grep 6be7f73; git log -1 -- <case file>'`.
- `cat /usr/local/bin/journal-commit.sh`; `tail -40 /root/.harness-config-autosync/journal-commit.log`.
- `grep journal-commit /root/.cron-status/runs.tsv`; same for wake-fanout, authority-repo-push, pain-check.
- `systemctl cat estate-alerts-to-journal.service`; `journalctl -u estate-alerts-to-journal -n 20`.
- `crontab -l | decode-base64` loop for journal/union/questions.
- `cat /root/.pain-check/status.json` (45 FIXED / 112 LIVE / 25 UNKNOWN; 43 fixed-and-still-open).
- `Get-ScheduledTask` / `Get-ScheduledTaskInfo` on ZABZ-TECH for HarnessSync / PushHarnessConfig.

**Sections 4, 5**
- `sqlite3 -readonly /root/authority.db "SELECT status,count(*) FROM owner_decision_queue GROUP BY status"`.
- severity / oldest / newest pending queries; full pending export parsed locally.
- `sqlite3 -readonly … "SELECT count(*),min(created_at),max(created_at),max(last_accessed_at),sum(access_count) FROM memories"`.
- access-count histogram, `memory_write_outcomes` breakdown, `procedural_experiences`, `memory_entries`.
- ChromaDB/mem0: `.schema embeddings`, per-collection `count(e.id)` and `max(e.created_at)` joins.
- `grep -rn "semantic_memory|mem0_service|FROM memories|collection.query" /opt/company/app`.

**Sections 6, 7**
- `ssh secratary-cloud 'sed -n … H3637/H3636/H3635'`; `git show --stat 5fb760aa`.
- `ssh hetzner 'grep -rn "data-roaming" /opt/waze-mdm'`.
- `cat /root/.sms-inbox/wake-cron.log`; `python3 /root/bin/wake.py stats --json`.
- `grep blocked_by /root/.sms-inbox/wake-failed --include=claim.json | sort | uniq -c`.
- `find … wake-failed -type d -printf '%TY-%Tm-%Td\n' | uniq -c`; `ls -lt wake-failed | head`.
- `tail -20 /root/.sms-inbox/wake-cost-cron.log`.

**Nothing was resolved, edited, appended, committed, or scheduled. The only write on the authority is
this file.**
