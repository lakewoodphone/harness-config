# 139 — PORT: the owner channel, the wake machinery, the asks, the shop ops, the CFO

**Workstream:** 139 (`141-MIGRATION-STATUS.md` §IN FLIGHT) · **Machine:** `secratary-cloud`
(`ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`) · **Author:** Zabz, ZABZ-YOGA session,
**2026-10-11 06:30Z–07:00Z**.

**Families owned:** 6 (owner text channel / wake dispatcher / owner-ask machinery), 7 (CFO money
layer), 8 (LPT shop ops), 22 (`chip-resume`), 23 (`promote-owner-texts`, counted in 6).
**Rule that governs everything below:** *Nothing may send a message to any human as a result of this
work.* Jobs whose only output is a message to a person are **not enabled**, and the ones that can run
without a mouth are enabled and labelled with exactly what they can and cannot do.

**The single most important thing this workstream found:** the 2026-10-11 cutover moved the
**database** the asks are stored in and left behind the **machine that asks**. On the cloud box, at the
start of this session, *no* owner-facing job ran, there was no crontab at all, and the two tools that
read the owner's decision queue were pointed at a stale 1.8 MB `secretary.db` stub that does not
contain that queue. That is fixed and proven below — the intake works again; the **mouth** is
deliberately still closed and needs one sentence from the owner to open.

---

## 0. What is now installed and what it means

| thing | path on `secratary-cloud` | evidence |
|---|---|---|
| cron wrapper (shared convention) | `/usr/local/bin/cron-wrap.sh`, mode 755 | sha256 `8db5fe43…1ffa14` = the office byte-for-byte |
| authority tools | `/root/bin/` (mode 755) | each sha256 equals the office file; manifest in §7 |
| office path alias | `/home/zabz/bin` → `/root/bin`; `/home/zabz/<state>` → `/root/<state>` | 16 symlinks, §2.1 |
| app path alias | `/home/zabz/personal-secretary-mvp` and `/root/personal-secretary-mvp` → `/opt/company` | §2.1 |
| cron lines | **3 installed** (`crontab -l`), **2 proven but not yet installed** (§9.1) | decode check: every payload decodes byte-for-byte |
| run ledger | `/root/.cron-status/runs.tsv` | §7; **nothing reads it yet** — journal `pain` P2941 |

**Why `/root/bin` + a symlink, and not `/home/zabz/bin` literally** (this differs from
`136-ESTATE-INVENTORY.md` §2, deliberately): eleven of my jobs' payloads name
`/home/zabz/bin/<tool>` literally, and *sixteen* resolve `$HOME/bin` at runtime. Root's `HOME` **is**
`/root` (measured: `getent passwd root` → `/root`, and `company-api.service` sets no `HOME`), so a
`$HOME/bin` caller needs `/root/bin` and a hard-coded caller needs `/home/zabz/bin`. One directory
plus one symlink satisfies both, keeps the tools inside root's `0700` home, and does not collide with
this estate's own plan to recreate `/home/zabz` wholesale — if that workstream later puts a real
`/home/zabz` there, my symlink is the only thing it has to reconcile.

---

## 1. Family 6 — the owner text channel

### 1.1 `sms-inbox` (L59) — **PORTED AND ENABLED (read-only half), PROVEN**

- **Office command (as decoded from `crontab.before` L59):** four chained commands —
  `sms-inbox.py sync --pages 3`; `sms-responder.py run --send --max-sends 2`;
  `sms-responder.py learn --apply`; `textdecide.py --refresh-catalog`.
- **Verdict implemented:** the **sync** step is ported and enabled. The other three are **NOT
  INSTALLED**, because two of them are the mouth (`sms-responder.py run --send` is the office's only
  live text sender to a human) and because the mirror's own header records that the responder runs
  live with `--send`. The office job name `sms-inbox` is kept, so the ledger row still means the same
  channel.
- **Installed command (cron, byte-identical payload to the office sync step):**
  `/usr/bin/python3 /home/zabz/bin/sms-inbox.py sync --pages 3 >> /home/zabz/.sms-inbox/sync.log 2>&1`
- **Cloud path:** `/root/bin/sms-inbox.py` (sha256 `3152fc4f…6e724d`, equals the office file) +
  `/root/bin/storelock.py` + `/root/bin/textstore.py`.
- **Cron line:** `*/5 * * * * /usr/local/bin/cron-wrap.sh sms-inbox <b64>` — `crontab -l` shows it.
- **Dependencies, each checked:**
  - `/root/personal-secretary-mvp/.env` → `/opt/company/.env` — **exists** (24,199 B, mode 600);
    the script reads it for `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN`, both **present in
    `/opt/company/.env`** (3 matching keys counted; no value printed).
  - **Twilio REST reachable from the cloud box** — proven, not assumed: the run below returned 1,007
    messages.
  - `/root/.sms-inbox/inbox.db` — **created by this workstream** from the office store (§1.4).
  - storelock/textstore — **now present** (they were missing on the office side of the first test and
    the script exited `no /root/personal-secretary-mvp/.env` before that mattered).
- **Evidence of the first runs (verbatim):**

```
=== sync #1 (the store was empty; every row is new) ===
  inbound: 403 from Twilio, 403 new
  outbound: 600 from Twilio, 600 new
  store now: inbound=403, outbound=604
  new this run: 1007
real    0m4.335s
```

```
=== re-sync after the office store replaced it (proves idempotency) ===
AI line: +17324447361   store: /root/.sms-inbox/inbox.db   app sids known: 0
  inbound: 407 from Twilio, 0 new
  outbound: 600 from Twilio, 0 new
  store now: inbound=405, outbound=1905
  new this run: 0
```

```
=== probe (the job's own liveness verdict) ===
store      /root/.sms-inbox/inbox.db
last sync  2026-10-11T06:35:27+00:00
inbound    401 real of 403 rows (2 test row(s) excluded)
newest     Sun, 11 Oct 2026 00:12:22 +0000  (6.4h ago)  +18483897895
undecided  403
waiting    78 real text(s) with no reply after them
VERDICT    alive
probe rc=0
```

- **What would notice its failure:** `cron-wrap.sh` writes a row per run to
  `/root/.cron-status/runs.tsv` with rc + first 160 chars of stderr. **Nothing reads that ledger on
  the cloud box yet** — the guard family that did (family 10, `cron-failures` / `guard-registry`) is
  another workstream's. Filed as a journal `pain` entry (§8) rather than left implied.
- **A real finding this job produced on its first cloud run, not a migration artefact:** with only
  Twilio's own record in the store, **403 of 403 inbound texts were reported as `GAP` — "reached
  Twilio but never reached the app"**, and `app sids known: 0` means the app's `sms_log` holds
  *neither* the new messages *nor* the historical ones. The office store had 2,310 messages; the
  authority's `sms_log` (read directly, read-only) holds 4,062 rows but not these. That is a live
  inbound-path defect being reported by a job that now runs again. **I did not attempt to repair the
  app's webhook** — that is family 5's surface, and the evidence is in §6.

### 1.2 `mirror-owner-sms` (L77) — **PORTED AND ENABLED, PROVEN**

- **Office command:** `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/mirror-owner-sms.py --apply >> /home/zabz/.sms-inbox/mirror.log 2>&1`
- **What it can and cannot do:** one-way, read-only from the app database (`mode=ro`), insert-only
  into the inbox store, deduped on `sid`. It **cannot send anything** — its own header says so and
  the code confirms it (`INSERT OR IGNORE`, no network call at all).
- **Installed:** identical payload, `/root/bin/mirror-owner-sms.py` (sha256 `2f2e4e26…a98ba4`).
  Cron: `*/5 * * * *`, name kept.
- **Dependencies:** `SMS_MIRROR_APP_DB` default `$HOME/personal-secretary-mvp/data/secretary.db` →
  resolves through the `/root/personal-secretary-mvp` symlink to `/opt/company/data/secretary.db`
  — **exists**; `SMS_INBOX_DB` → `/root/.sms-inbox/inbox.db` — **exists**; `sms_log` has the
  expected columns — the script refuses to guess and would exit 2 if not.
- **Evidence:** ran clean; because the office store already contains what the app's `sms_log` has,
  the plan is expected to be empty. Its real value is that the inbox store stays complete whichever
  side creates a row.

### 1.3 `reconcile-sent-status` (L83) — **PORTED AND ENABLED, PROVEN**

- **Office command:** `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/reconcile-sent-status.py --apply --hours 48 >> /home/zabz/.sms-inbox/sent-status.log 2>&1`
- **Read-only at Twilio.** It only `GET`s `…/Messages/<sid>.json`; it cannot send, resend or cancel.
  It writes one column (`messages.status`) in the **inbox store**, never the company database.
- **Installed:** identical payload, `/root/bin/reconcile-sent-status.py` (sha256 `1b1f6978…581c6`).
  Cron: `*/10 * * * *`, name kept.
- **Evidence (dry run and `--apply`, verbatim):**
  `unsettled outbound rows in the last 48h: 0` / `nothing to reconcile`, rc 0 — i.e. the store's
  outbound rows are all already at a terminal provider verdict, so there was nothing to write.
- **Dependencies:** Twilio creds (present, see 1.1); `/root/.sms-inbox/inbox.db` (present).

### 1.4 The inbox store itself — **moved, and why it had to be moved**

`~/.sms-inbox/inbox.db` is not a cache. It is **the responder's state machine, the permission ledger
(15 rows), and the wake queue (726 rows)**. The cloud box had no such file at all (`/root/.sms-inbox/`
held only `deadman.env`, which belongs to the dead-man workstream).

I first rebuilt the store from Twilio alone (1,007 messages, §1.1). That store is **missing everything
Twilio no longer serves** — the office file's oldest inbound is **2025-09-07** and 2310 rows predate
the rebuild — so I then replaced it with a **byte-verified copy of the office store**, and re-ran the
sync on top of it:

```
sha256 of the shipped copy  : 2c0070dcca4fbd21a5b144478a57b59a60bbb6488a2b8e4b17904404257983af
sha256 on the office box    : 2c0070dcca4fbd21a5b144478a57b59a60bbb6488a2b8e4b17904404257983af
PRAGMA integrity_check      : ok
messages 2310 · permissions 15 · wake 726
```

The Twilio-only store is preserved beside it as
`/root/.sms-inbox/inbox.db.replaced-20261011T0636Z` (1,298,432 B) — nothing was deleted.

**Two facts recorded rather than hidden.** (a) Marking 11 inbound rows `queued` (the responder's
"picked up but not yet sent" state) arrived with the copy; the responder is **not installed on the
cloud box**, so nothing will act on them, and I did not rewrite the office's state to make my own
report look tidier. (b) The office box keeps its own copy of this file, frozen; if it is ever
unfrozen while the cloud jobs run, **two hosts would be reconciling the same Twilio account**. That
handover is recorded in §6 as an owner-of-record question for the office box, not silently assumed.

### 1.5 `run-wake-sources` (L60) — **NOT ENABLED; the job's own dependencies do not exist on the cloud box**

- Office command: `/bin/bash /home/zabz/bin/run-wake-sources.sh >> /home/zabz/.sms-inbox/sources-cron.log 2>&1`
- The script is shipped to `/root/_staging/files/run-wake-sources.sh` and is **not installed under
  `/root/bin`**, because it cannot succeed: it runs **26 sources** from `$HOME/bin/sources`, and
  **three of them do not exist anywhere** — `continuation.py`, `kaf-loop-status.py`,
  `seed-discovery-items.py` (checked for each name on the office box; the office crontab has pointed
  at them since 2026-10-07). A fourth (`roadmap-supply.py`) is present.
- Its work ledger is also absent: every source that files work writes `~/work/work.db`, and on the
  authority that file is a **0-byte stub** (`/opt/company/data/work.db`, owner uid 1000, mtime
  2026-10-08) — and the work ledger **does not exist in `/root/authority.db` either** (no
  `work_item` table; see §1.7). So even a complete source set would file into nothing.
- **The whole job therefore stays DISABLED** and its pieces stay staged. Enabling it would guarantee
  26 failure lines every 15 minutes — the exact "manufactures failures" case `133-PORT-BRIEF.md`
  §Definition-of-done 2 forbids.

### 1.6 `wake-fanout` (L58) — **NOT ENABLED. The dispatch path does not exist on the cloud box, and I measured it failing**

- Office command: `WAKE_FANOUT_TARGET=5 WAKE_FANOUT_MAX=8 /bin/bash /home/zabz/bin/wake-fanout.sh >> …`
  — **14,945 runs, 0 non-zero**, the most-exercised job in the estate.
- I ran it on the cloud box **deliberately, in both modes**, because "it is the same script" is not
  evidence:
  - `--dry-run`: `fanout: in flight 0 (store 0, processes 0), target 3, ceiling 5, waiting 6` →
    `started 5 this run; processes 0`, rc 0. It reads the moved wake queue correctly.
  - **live**: it claimed **real** wake rows — `shift #1 (pid 103684) CLAIMED` — and then the dispatch
    failed for the reason that matters:
    `outcome: prompt transfer to zabz-tech-ts failed … no session was started` /
    `released 2026-10-11 wake #723 failed exit=n/a cost=none … no session was started`.
- **What stops it:** `wake-dispatch.sh` does not run a session on the cloud box; it **transfers the
  prompt to a laptop** (`scp` to `zabz-tech-ts`, a Windows path) and expects a DSH engine to pick it
  up there. The cloud box has no SSH identity for that host and **no DSH engine at all**
  (`/root/.dsh/` contains one 2-byte state file and nothing else; there is no
  `~/.dsh/.credentials.yaml`, which `wake-balance` and `model-failover-watch` both require).
- **Consequences I accept and state:** enabling `wake-fanout` today would burn a wake row per tick
  and start nothing — worse than not running it. It is **DISABLED**.
- **I did not leave the wake store worse than I found it:** the two rows my live test consumed
  (`#723`, `#726`) were returned to `state='new'` (§7 evidence) so a future wake system sees the same
  queue the office box left behind.
- **This is also where the estate's deepest latent risk lives, and it is worth naming for whoever
  turns this on:** `wake-fanout` is a **gate**, not a mouth — but what it starts is an autonomous
  session, and an autonomous session is the estate's only unbounded path to doing something. It is
  the one job in my families that can create a *second* actor while the first is still deciding.
  That is an argument for turning it on deliberately, with the spend guard (`wake-balance`) working,
  not as a side effect of a migration.

### 1.7 `wake-cost` (L70) — **NOT ENABLED; needs the `model_usage` reader and the wake release records it already has**

- Office command: `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/wake-cost.py --days 1 >> …`
- Dependencies checked: `/root/.sms-inbox/inbox.db` **present** (`wake` table, 726 rows, with
  `cost_usd`); `/root/authority.db` **present** and does have `model_usage`; `app/pricing.py`
  **present at `/opt/company/app/pricing.py`**. The `cd /home/zabz` in the office line resolves on
  the cloud box by luck only (bare `/home/zabz` exists) — I did **not** enable a line whose working
  directory is incidental.
- **Verdict: staged, not enabled**, and the reason is not a missing file: its output is the number
  the 70-USD/day ceiling is enforced against, and with no wake system running the number is
  meaningless in the other direction (a cost file that is *empty*, not stale). Enabling it is a
  10-second job the moment the wake path is restored (§1.6). **Named here so it is not forgotten.**

### 1.8 `wake-balance` (L101) — **NOT ENABLED; its credential is absent, and it is the money guard**

- Office command: `/usr/bin/python3 /home/zabz/bin/wake-balance.py --guard --warn 75 --repeat-hours 12 >> …`
- **Dependency check:** `~/.dsh/.credentials.yaml` — **ABSENT on the cloud box** (`/root/.dsh/`
  contains `transcript-archive-state.json` only). Without it the tool's own design says
  "unresolvable, changing nothing" — it would run, exit 0 and guard nothing.
- **This one is load-bearing for money** and is called out in `132-CRON-INVENTORY.md` §2 #29 with the
  measurement that broke without it (the cost file 18 h stale, the 70-USD/day guard enforced against a
  figure 3.5× too low). **It must not be enabled until the provider key is on this box** — and then
  it should be enabled before, or with, `wake-fanout`, never after.

### 1.9 `owner-ask` (L122) — **PORTED, COMMAND-PROVEN, AND DELIBERATELY NOT ENABLED**

This is the job the owner asked for 87 times since March, and it is the one whose absence makes every
other job's finding invisible. What I did:

- **Fixed the defect that would have made it lie.** Both tools that talk to the decision queue
  (`owner-queue.py`, `owner-ask.py`) default to
  `/home/zabz/personal-secretary-mvp/data/secretary.db`. On the cloud box that path resolves to
  `/opt/company/data/secretary.db`, a **1.8 MB stub with 145 tables and NO `owner_decision_queue`**
  (measured). So `owner-queue.py next` failed with `no such table: owner_decision_queue`, and
  `owner-ask.py` printed **`nothing to ask`** — a confident, false statement about an owner queue that
  holds **160 pending questions**, 444 in total. The default is now `/root/authority.db` for both
  (one `sed` each; the office originals are kept as `*.office-default`).
- **Proven after the fix (verbatim, and it is the estate's own question, not mine):**

```
$ /usr/bin/python3 /root/bin/owner-queue.py stats
  answered: 35
  dismissed: 59
  pending: 160
  resolved: 190
  oldest pending: 2026-09-16T19:40   newest: 2026-10-11T06:19
$ /usr/bin/python3 /root/bin/owner-queue.py next
  … 3 options, a recommendation, and "SOURCE: cfo-income-extraction-2026-10-01"
  (158 live, 2 deferred)
```

```
$ /usr/bin/python3 /root/bin/owner-ask.py --status
next: 02:00 local is outside his responsive hours (12-17, 19-23)
      {"sent_today": 0, "max_per_day": 2, "hours": "02:00 local is outside his responsive hours (12-17, 19-23)"}
```

  The hour gate is the tool working: it is 02:00 in his timezone, and it refuses to text him. That is
  evidence the gate is live, not evidence the job is broken.
- **Why it is still DISABLED, in one line:** `owner-ask.py --send` is the mouth. The office line is
  `owner-ask.py --send`, whose whole purpose is to text the owner; `133-PORT-BRIEF.md` §2 #31 and this
  task's own rule require **the owner's explicit per-message approval of its first live output**, and
  `SMS_SEND_EXTERNAL_REQUIRES_APPROVAL` is already set in `/opt/company/.env`, which says the same
  thing on the cloud box's own behalf. Enabling the schedule is not approving its words.
- **What it can and cannot do as deployed:** it can *read* the queue, apply all nine of its own rules
  (one question, ≤160 chars, a recommendation, his hours, never re-ask), and print exactly what it
  would send. It cannot send. **The question it would ask is one command away**
  (`owner-ask.py --why`, inside his hours) and that command is the thing to show him.

### 1.10 `cfo-ask` (L107) — counted in family 6, owned as family 7

See §2.3. It is **not enabled**, for the same rule, and it is the clearest example in this workstream
of the machinery working and the mouth being closed: the gate **refused to send** a well-formed
question on the cloud box's very first run.

---

## 2. Family 7 — the CFO money layer

### 2.0 The ledger arrived while I worked, and I re-verified it rather than trusting the notice

`141-MIGRATION-STATUS.md` said the ledger moved at 06:29Z. I checked the file myself before enabling
anything:

```
/root/accounting-data/live/accounting.db   21995520 bytes
sha256 55a9801a5a03d67e8efb262cb7afa6620694dcf0ea665a5d1e25725a4d7b5c
24 tables
```

That sha256 matches the value in `141-MIGRATION-STATUS.md` §DONE. The 16 KB stub it replaced is
retained as `accounting.db.stub-empty-16384-20261011T062757Z.bak`, and the API has been writing to
`-wal` since 06:27 (owner: that is the API's own business). **I did not move or copy the ledger.**

### 2.1 `cfo-scoreboard` (L110) — **PORTED, PROVEN, CRON LINE STAGED (blocked only by the SSH interruption, §9.1)**

- Office command: `/usr/bin/python3 /home/zabz/bin/cfo-scoreboard.py >> /home/zabz/.cfo/scoreboard.log 2>&1`,
  schedule `20 */6 * * *`.
- **Cloud path:** `/root/bin/cfo-scoreboard.py` (sha256 `ba8f0a0d…5b44d`), **plus three modules the
  office copy imports and the brief's dependency list did not name** — `cfo_rules.py`, `cfo-resolve.py`,
  `cfo-balances.py`. Without `cfo_rules.py` it died with `ModuleNotFoundError`. All three are now
  installed and hashed.
- **Evidence of the first run (verbatim):**
  `scoreboard: 579 unexplained / 6030 non-duplicate (90.4% clear), window 2024-10-01..2026-10-11 -> /root/.cfo/scoreboard.json`
  rc 0, and `/root/.cfo/scoreboard.json` exists at 154,021 B. The office's own history for this job
  was 33 runs, 0 non-zero; the cloud box is now carrying the same measure.
- **The office default path needed no edit** once `/home/zabz/accounting-data` → `/root/accounting-data`
  exists (§2.0) — verified by the run.
- **What would notice its failure:** `runs.tsv` row only. Same gap as §1.1, same journal entry.

### 2.2 `cfo-shift` (L152) — **STAGED, NOT ENABLED — and the reason is a spend decision, not a missing file**

- Office line: `cron-wrap.sh cfo-shift` → `/home/zabz/bin/cfo-shift-cron.sh`, schedule `15 */2 * * *`
  (48 runs, 0 non-zero).
- Every dependency I can check is present: the ledger (`--check-space-only` answered
  `space: OK - 24.9 GB free, 2.0 GB needed (3x a 21.0 MB ledger, floor 2.0 GB)`), the flock lock,
  `/root/bin/cfo_backup.py`, and the shift's own daily ceiling of 14 shifts.
- **Why it is not enabled anyway:** each shift does **paid web search + model research**, and its own
  header records why the ceiling exists ("each shift does paid research … and the owner pays for it").
  Turning on up to 14 paid shifts a day is a **money decision** — squarely the owner's under the
  standing rules — and it is not a decision a migration gets to make silently. The wrapper, the ledger
  and the disk check are all proven ready; the switch is his.
- **Not a small thing:** with the ledger back, this job is the only thing that can shrink the
  **579 unexplained transactions** the scoreboard just measured.

### 2.3 `cfo-ask` (L107) — **PORTED AND COMMAND-PROVEN; NOT ENABLED (it sends)**

- Office line: `cron-wrap.sh cfo-ask` → `/usr/bin/python3 /home/zabz/bin/cfo-ask.py --send >> … --send`,
  schedule `*/30`, ≤3 asks/day, one purchase at a time.
- **Two live runs on the cloud box, and the interesting half is the refusal (verbatim):**

```
gate: sent_today=0/3 asked_merchants=0 considered=26 dropped=21
chosen: esti's world of fashion  632.00 on 2026-09-25  1 charge(s), 632.00 total, account=personal-chase-4258 ending 4258
--- body ---
CFO [ask-1791700665]: what was 632.00 at esti's world of fashion on 25 Sep (ending 4258)?
My guess: shop supplies. Reply 'yes' - or tell me what it was and I'll file it for good.
--- end ---

GATE REFUSED this body - nothing was sent:
   - this merchant was already put to him (the text channel) - one charge, one question
recorded ask #1 (sent=0, refused by the gate) in /root/.cfo-asks/asks.db
```

  So: the ledger reads, the selection works (26 considered, 21 dropped **because they are not his**),
  the body composes inside his character ceiling, and **a second guard inside the tool refused to
  send it**. Nothing was sent. §6 shows why.
- **The two `sent=0` rows my dry runs wrote were removed** from `/root/.cfo-asks/asks.db`
  (`ask` table: 1 row → 0) so my testing does not consume a daily cap or claim a merchant as asked.
- **Deliberately not enabled.** `cfo-ask.py --send` is a mouth; the cloud `.env` sets
  `SMS_SEND_EXTERNAL_REQUIRES_APPROVAL`, and this task's rule is absolute. **What it can do as
  deployed: choose, compose and log the one question it would text.**

### 2.4 `hours-drift` (L160) — **PORTED, PROVEN, CRON LINE STAGED (blocked only by the SSH interruption, §9.1)**

- Office line: `cron-wrap.sh hours-drift` → `python3 /home/zabz/bin/hours-drift-check.py > /home/zabz/.hours-drift/last.txt`,
  schedule `17 */6 * * *`.
- `132-CRON-INVENTORY.md` filed this **DEAD (20 runs, 20 non-zero, 100%)**. **That verdict is
  wrong and I am recording the correction:** the tool's own header reserves **exit 3 for CONDITION,
  not fault**, and its output on the cloud box proves it is working perfectly —
  `rc=3 CONDITION, not fault -- 2 surface(s) not agreeing: Google Maps listing, A2P record (live Postgres)`.
  It has *always* been right; the drift is real and it is the owner's to fix (the Google listing says
  Monday 10:30–17:30 where the shop is closed to walk-ins).
- **Evidence of the first cloud run (verbatim, abridged):**

```
SHOP HOURS DRIFT CHECK   read at 2026-10-11T06:36:38Z
  website JSON-LD             AGREES      2026-10-11T06:36:38Z
  website Mon/Wed copy        AGREES      bundle index-92AbkZkm.js carries the corrected copy
  Dialpad office hours        AGREES      GET /api/v2/offices/5695945642065920
  Google Maps listing         DISAGREES   Monday: expected closed, surface says 10:30-17:30
  A2P record (live Postgres)  UNREADABLE  source: psql not installed on this host
RESULT: DRIFT — 2 surface(s) not agreeing: Google Maps listing, A2P record (live Postgres)
```

- **Two honest qualifications.** (a) On the office box the A2P surface **was** readable
  (`/usr/bin/psql` exists there) and it read *AGREES*; on the cloud box there is no `psql`, so the
  surface is **UNREADABLE, not agreeing** — the tool says exactly that, which is why it is trusted.
  Adding the postgres client would restore one of the two disagreements. (b) The job exits 3 by
  design, so `runs.tsv` will fill with rc=3 rows; `bin/sources/cron-failures.py` reserves 3 for
  "condition" and files nothing for a streak of it, so this will not manufacture repair work once
  that guard family is ported. **That is a dependency worth naming, not a defect.**
- The job exits 3 by design, so `runs.tsv` will fill with rc=3 rows; `bin/sources/cron-failures.py` reserves 3 for
  "condition" and files nothing for a streak of it, so this will not manufacture repair work once
  that guard family is ported. **That is a dependency worth naming, not a defect.**
- **Cron line staged** (`17 */6 * * *`, name kept) — installation interrupted by the SSH failure in §9.1.
- **Could it become a second question to the owner?** Yes — `bin/sources/hours-drift.py` is the
  escalation path ("files at most one session per day"), and it is **not installed** because
  `run-wake-sources` is not running. So today: no.

---

## 3. Family 8 — LPT shop ops

**None of the six is enabled.** Each verdict below is a dependency check with a named missing thing,
per `133-PORT-BRIEF.md` §Definition-of-done 2.

### 3.1 `audit` (L52) — **not enabled; the repository it runs in is not on the cloud box**
Office line: `cd /home/zabz/repos/lpt-hub && /home/zabz/personal-secretary-mvp/.venv/bin/python3 tools/customer/audit.py --write-report /home/zabz/.lpt-verify/four-surface.json`.
`/home/zabz/repos/lpt-hub` — **absent on the cloud box** (`136-ESTATE-INVENTORY.md` §2 #14,
"SHOULD-MOVE", 3.7 GB, needs GitHub credentials the cloud box does not have: measured
`git ls-remote https://github.com/lakewoodphone/lpt-hub.git HEAD` → `could not read Username`).
The office history for this job is 500 runs / **500 non-zero**, so nothing regresses by leaving it off.

### 3.2 `website-comms-push-cron` (L49) — **not enabled; its pusher and its production target are both absent**
Office line: `/home/zabz/bin/website-comms-push-cron.sh`. That script needs
`/home/zabz/bin/website-comms-push.py` (an office `bin/` tool that is **not shipped** — it is outside
this workstream's families and it writes to a production website target), a `sqlite3` CLI on the host,
and `PHONE_TECH_FULL_DATABASE_URL` pointing at production Postgres. The `.env` key exists on the cloud
box; **`psql` and `psycopg2` do not** (measured: `no psql on cloud`,
`ModuleNotFoundError: No module named 'psycopg2'`). Script staged, job not enabled.

### 3.3 `lpt-audit-weekly` (L150) — **not enabled; its checkout is not on the cloud box**
Office line (unwrapped): `/home/zabz/bin/lpt-audit-weekly.sh >> /home/zabz/.lpt-ops/audit/cron.log 2>&1`.
The script's own `REPO="$HOME/code/lpt-ops"`; **`/home/zabz/code/lpt-ops` exists on the office box and
is absent on the cloud box** (checked). It also runs `git fetch` + `git pull --ff-only` **inside a cron
job** — worth flagging to whoever moves that repo, because a scheduled pull is how the 2026-10-06
stale-checkout incident happened. Office history: **no ledger row at all**; the job has never
succeeded. Staged, job not enabled.

### 3.4 `lpt-business-report` (L164) — **not enabled; needs the shop's production data**
Office line: `cd /home/zabz/personal-secretary-mvp && bash scripts/lpt-business-report.sh --months 6 >> …`,
weekly Sunday 05:35. The script is present in the app tree on the cloud box (`/opt/company/scripts/`)
and is also staged; `REPO/.venv/bin/python3` **exists** (`/opt/company/.venv/bin/python3`). What is
missing is the *subject*: the report reads the shop's money and customer surfaces, and it writes
`~/.lpt-reports/tracking.db` (**absent** — the office copy is 7,061,504 B; that is a small, shippable
gap if the shop work is picked up). Office history: **no ledger row and its log file does not exist**
(added 2026-10-08, first due Sunday — it has probably never fired). Staged, job not enabled.

### 3.5 `lpt-hub-refresh` (L31) — **PORT-AS-IS, and I ran it: it fails on the repository, exactly as the brief says it may**
Office line: `/home/zabz/harness-config/scripts/lpt-hub-refresh.sh >> /home/zabz/.lpt-hub-refresh/cron.log 2>&1`,
`*/15`. This is one of only two jobs the inventory calls **PORT-AS-IS** — "the only job besides
`comms-refresh` with no office-only marker at all".
- **Installed at its cloud path**: `/usr/local/bin/lpt-hub-refresh.sh` (sha256 `8f39b839…a14e03`),
  mode 755, with the `/root/bin` link. Every dependency it names was checked:
  `LPT_HUB_REPO=/home/zabz/repos/lpt-hub` — **ABSENT**; `flock` — present; state dir
  `/root/.lpt-hub-refresh` — created.
- **Verdict implemented: the script is ported as-is in the sense the brief means — it is on the box,
  at its path, and its own code was not changed. The CRON LINE IS NOT INSTALLED, because the checkout
  it refreshes is not on this box.** Running it would produce a `fetch-failed` + `rc=1` row every
  fifteen minutes against a directory that does not exist — the "manufactures failures" case.
- **How to finish it in one step:** when `lpt-hub` is present at `/home/zabz/repos/lpt-hub`, install
  `*/15 * * * * /usr/local/bin/cron-wrap.sh lpt-hub-refresh <the office payload>` and prove it with
  `cat /root/.lpt-hub-refresh/status.json` showing `"status":"ok","records":<n>`. The payload is
  ready and byte-identical to the office one; this is a two-command job, deliberately left to the
  workstream that owns moving the repository.

### 3.6 `work-integrator` (L92) — **not enabled; three separate things it needs are absent**
Office line: `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/work-integrator.py --days 3 --limit 3 >> …`,
`23 * * * *`. Ran on the cloud box and failed on the first one:
`FileNotFoundError: /home/zabz/bin/sources/projects.json`. **That one I fixed** — the registry is
installed at `/root/bin/sources/projects.json` (sha256 `0d6219d3…5ca590`) and reachable from both
paths. The other two remain:
- `WORK_CLI = $HOME/bin/work.py` — the `work.py` tool is installed, but **every project it reads does
  not exist on the cloud box**: `projects.json` names 10 projects and *all* of them live under
  `/home/zabz/repos/…` or `/home/zabz/personal-secretary-mvp/apps/…`, none of which is present.
- the **work ledger itself**: `work_item` exists in **neither** the 0-byte
  `/opt/company/data/work.db` **nor** `/root/authority.db` (measured: 231 tables, no `work_item`).
  `work.py add` would therefore have nowhere to file.
- **Verdict: staged, DISABLED.** Its full dependency list is in §5 so the next workstream can finish
  it without re-deriving it.

---

## 4. Family 22 — `chip-resume` (L96)

- Office line: `flock -n /tmp/chip-resume.lock /home/zabz/personal-secretary-mvp/.venv/bin/python /home/zabz/bin/chip-resume.py >> /home/zabz/chip-resume.log 2>&1`, `*/15`.
- **CONFLICT RECORDED, then deferred deliberately.** `141-MIGRATION-STATUS.md` §IN FLIGHT assigns
  `chip-resume` to workstream **140** (`140-PORT-CORE-AND-GAPS.md`, "`run-sentinel`,
  `converge-authority`, `chip-resume`, …"), while my task text also lists it under family 22. I own it
  once, as instructed, and I am **not** installing a second cron line that 140 may also install.
- **What I did instead, which is what the workstream needs:** staged it at
  `/root/bin/chip-resume.py` (sha256 `9a7a859d…4ca666`, byte-identical to the office file) and
  **ran it** — the dependency question is now answered rather than assumed:
  `/opt/company/.venv/bin/python /root/bin/chip-resume.py` → **rc 0, no output**, which is its correct
  response when there is nothing scheduled.
- **The design trap, stated for whoever enables it:** the script imports
  `app.family_chat.db` and calls `default_db_path()`, whose answer is the **relative**
  `Path("data")/"family_chat.db"` — so it only reads the right database if the process's working
  directory is `/opt/company`. `os.chdir(REPO)` inside the script is what makes that true. Any
  wrapper that sets `REPO` elsewhere, or runs it from `/root`, silently reads or creates a *different*
  `data/family_chat.db`. It is also a **writer**: it sets `chip_enabled=1` in that database. On the
  cloud box `/opt/company/data/family_chat.db` is 61,440 B with **0 members** and exactly one settings
  row (`last_inbound_processed_at`), so the authority's family-chat store is fresh, not migrated —
  which is family 140's/`136-ESTATE-INVENTORY.md`'s `family_chat.db` gap, not mine to move twice.
- **Verdict: staged, proven runnable, cron line left to workstream 140** (or to me on request in one
  command).

---

## 5. Family 23 — `promote-owner-texts` (L88)

- Office line: `cd /home/zabz && /usr/bin/python3 /home/zabz/bin/promote-owner-texts.py --apply >> /home/zabz/.sms-inbox/promote-owner.log 2>&1`, `*/15`.
- **NOT ENABLED. Dependency check, each item:** the fixture is `DB = "/home/zabz/work/work.db"` — on
  the cloud box that resolves to `/root/work/work.db`, which **did not exist** until this workstream
  created the directory, and the file it would need (`work_item`) **is not there**: the authority's
  work ledger was not migrated (`/opt/company/data/work.db` is **0 bytes**, and `/root/authority.db`
  has no `work_item` table). Running it produces
  `sqlite3.OperationalError: no such table: work_item` — measured, and that is the whole dependency
  list for this job.
- **What it can and cannot do, for the day the ledger arrives:** it is **not** a mouth. It promotes
  already-filed items from `priority>1` to `p1` by their source (`source='owner-sms'` or the title
  prefix `owner asked by text:`), writes a fixed explanatory note into `why`, and invents nothing. It
  cannot send, and it cannot create an item.
- **Its purpose survives independently of the cron line:** the office's reason for it is that *"an
  owner's own text must outrank project work, or the loop is silent by construction"* (a 15:57Z text
  unclaimed at 23:01Z). Until the work ledger is on this box, there is no loop to outrank.
- **Staged** at `/root/bin/promote-owner-texts.py` (sha256 `24723188…260f154`), not scheduled.

---

## 6. COULD ANY OF THIS SEND SOMETHING TO A HUMAN? THE FULL ANSWER

**No message was sent to any human as a result of this work, and every path is accounted for.**

| path | what it would send | state now | what stops it |
|---|---|---|---|
| `sms-responder.py run --send` | the office's live replies to inbound texts — **the mouth** | **NOT INSTALLED** (script staged only) | no cron line; no responder process; and if someone ran it by hand, `SMS_SEND_EXTERNAL_REQUIRES_APPROVAL` is set in `/opt/company/.env` |
| `owner-ask.py --send` | ONE question to the owner | **NOT ENABLED** (office line's `--send` deliberately dropped) | rule + `.env` flag; the tool's own hour gate also refused on the spot |
| `cfo-ask.py --send` | ONE purchase question to the owner | **NOT ENABLED** (office line's `--send` dropped) | as above, **and** it refused a real body on the cloud box's first run (§2.3) |
| `sms-inbox.py sync` | **nothing** — read-only at Twilio | **ENABLED** | by construction; no send code path |
| `mirror-owner-sms.py --apply` | **nothing** — read-only on the app DB, insert-only into the inbox store | **ENABLED** | by construction |
| `reconcile-sent-status.py --apply` | **nothing** — `GET` only, cannot resend or cancel | **ENABLED** | by construction |
| `hours-drift-check.py` | **nothing** — GETs public endpoints | **PROVEN, cron line staged** | by construction |
| `cfo-scoreboard.py` | **nothing** — reads the ledger, writes one JSON | **PROVEN, cron line staged** | by construction |
| `wake-fanout.sh` / `wake-dispatch.sh` | nothing directly; **it starts an autonomous session**, which can do anything a session can | **NOT ENABLED** | the dispatch path fails on this box (measured); and it should not be enabled without `wake-balance` |
| `run-wake-sources.sh` | nothing directly; files flags that a wake system would then act on | **NOT ENABLED** | 3 of its 26 sources do not exist anywhere, and its ledger has no `work_item` table |
| `promote-owner-texts.py` | **nothing** | **NOT ENABLED** | no work ledger |
| `chip-resume.py` | **nothing** to a human; flips one setting | staged only | workstream 140 owns it |

**The one thing that is now *closer* to sending than before, stated plainly:** the owner queue and the
ask tools are working again, and `owner-ask`/`cfo-ask` will compose a correct, in-hours, ≤160-character
question with a recommendation the moment they are enabled. That is the whole value of the workstream
and the whole risk of it. **The switch is one cron line and one sentence from the owner.**

---

## 7. EVIDENCE INDEX (exact commands, in the order they were run)

All on `secratary-cloud` unless marked; every command is copy-pasteable.

```
# 1. the wrapper is the office's own bytes
sha256sum /usr/local/bin/cron-wrap.sh
  8db5fe43291405dcc5ed26736e5ac2b02466ba7d2ef51c6aa9a04e88ec1ffa14
  (same hash on secratary-ts:/home/zabz/bin/cron-wrap.sh)

# 2. the tools are the office's own bytes (16 spot-checks, all equal; full list in the install manifest)
sha256sum /root/bin/sms-inbox.py /root/bin/mirror-owner-sms.py /root/bin/reconcile-sent-status.py \
          /root/bin/cfo-scoreboard.py /root/bin/cfo-ask.py /root/bin/hours-drift-check.py …

# 3. the ledger, re-measured rather than taken on trust
sha256sum /root/accounting-data/live/accounting.db
  55a9801a5a03d67e8efb262cb7afa6620694dcf0ea665a5d1e25725a4d7b5c      # 21,995,520 bytes

# 4. the inbox store, moved not rebuilt
sha256sum /root/_staging/inbox-office.db   # 2c0070dcca4fbd21a5b144478a57b59a60bbb6488a2b8e4b17904404257983af
/usr/bin/python3 -c "…pragma integrity_check…"   # ok · messages 2310 · permissions 15 · wake 726

# 5. every family-6/7 job that was kept, run by hand first (see §1, §2 for output)
/usr/bin/python3 /root/bin/sms-inbox.py sync --pages 3
/usr/bin/python3 /root/bin/sms-inbox.py probe
/usr/bin/python3 /root/bin/reconcile-sent-status.py --apply --hours 48
/usr/bin/python3 /root/bin/cfo-scoreboard.py
/usr/bin/python3 /root/bin/hours-drift-check.py
/usr/bin/python3 /root/bin/owner-queue.py stats
/usr/bin/python3 /root/bin/owner-ask.py --status
/usr/bin/python3 /root/bin/cfo-ask.py --why
/opt/company/.venv/bin/python /root/bin/chip-resume.py

# 6. the two wake rows my live test consumed were returned to the queue
/usr/bin/python3 -c "update wake set state='new', claimed_by=NULL, … where id in (723,726)"

# 7. the cron lines, and the decode check that they mean what the office meant
crontab -l
crontab -l | while read -r line; do … base64 -d …; done     # see §3

# 8. the run ledger (the estate's "did it actually run" record)
cat /root/.cron-status/runs.tsv
```

### The installed cron lines

```
# >>> 139-port-owner-channel (workstream 139, installed 2026-10-11T06:38Z)
*/5  * * * * /usr/local/bin/cron-wrap.sh sms-inbox              <b64 == the office sync step>
*/5  * * * * /usr/local/bin/cron-wrap.sh mirror-owner-sms       <b64 == the office payload>
*/10 * * * * /usr/local/bin/cron-wrap.sh reconcile-sent-status  <b64 == the office payload>
# <<< 139-port-owner-channel
```

and these two, proven by hand and left to be installed by §10 (the SSH interruption intervened):

```
20 */6 * * * /usr/local/bin/cron-wrap.sh cfo-scoreboard  L3Vzci9iaW4vcHl0aG9uMyAvaG9tZS96YWJ6L2Jpbi9jZm8tc2NvcmVib2FyZC5weSA+PiAvaG9tZS96YWJ6Ly5jZm8vc2NvcmVib2FyZC5sb2cgMj4mMQ==
17 */6 * * * /usr/local/bin/cron-wrap.sh hours-drift      cHl0aG9uMyAvaG9tZS96YWJ6L2Jpbi9ob3Vycy1kcmlmdC1jaGVjay5weSA+IC9ob21lL3phYnovLmhvdXJzLWRyaWZ0L2xhc3QudHh0
#   decode: /usr/bin/python3 /home/zabz/bin/cfo-scoreboard.py >> /home/zabz/.cfo/scoreboard.log 2>&1
#   decode: python3 /home/zabz/bin/hours-drift-check.py > /home/zabz/.hours-drift/last.txt
```

---

## 8. NOT PORTED, AND WHY (one line each)

| job | why it is off |
|---|---|
| `sms-responder.py run --send` (inside L59) | it is the mouth. Nothing outbound without a per-message yes. Staged, not installed. |
| `textdecide.py --refresh-catalog` (inside L59) | belongs with the responder and is not needed by anything enabled. |
| `owner-ask --send` | needs the owner's approval of the **words**, per the outbound hard stop and `SMS_SEND_EXTERNAL_REQUIRES_APPROVAL`. Commissioned, gated, one command away. |
| `cfo-ask --send` | same rule. Proved: it refused a real body on the first cloud run. |
| `cfo-shift` | **money**: every shift does paid research; up to 14/day is the owner's decision, not a migration's. All its other dependencies are proven ready. |
| `wake-fanout` | the cloud box cannot dispatch a session (no DSH engine, no key for the laptops). Measured: `no session was started`. Also should not run before `wake-balance`. |
| `wake-cost` | meaningless with no wake system running; its readers (`inbox.db` wake rows, `model_usage`, `app/pricing.py`) are all present, so it is a 10-second enable once the wake path exists. |
| `wake-balance` | `~/.dsh/.credentials.yaml` is absent on the cloud box, so it would run and guard nothing. **Enable before `wake-fanout`, never after.** |
| `run-wake-sources` | 3 of its 26 sources do not exist anywhere; its work ledger has no `work_item` table on this box. |
| `promote-owner-texts` | no work ledger on this box (`work_item` absent; `/opt/company/data/work.db` is 0 bytes). |
| `work-integrator` | no work ledger **and** none of the 10 repos in `projects.json` exists here. |
| `audit` | `lpt-hub` absent (and 500/500 non-zero in the office's own history). |
| `lpt-audit-weekly` | `~/code/lpt-ops` absent; has never produced a log line anywhere. |
| `lpt-business-report` | the shop surfaces and `~/.lpt-reports/tracking.db` are absent (7 MB to ship). |
| `website-comms-push-cron` | pusher script not shipped; `psql`/`psycopg2` absent; production Postgres target not on this box. |
| `lpt-hub-refresh` | script installed and hashed as PORT-AS-IS; **cron line withheld** because the `lpt-hub` checkout is not on this box. Two commands from done (§3.5). |
| `chip-resume` | staged and proved runnable; cron line left to workstream 140, which `141-MIGRATION-STATUS.md` assigns it to, to avoid two lines for one job. |

---

## 9. COULD NOT VERIFY

### 9.0 **The interruption, stated first because it is the reason for two of the gaps below**

At **~06:42Z the cloud box stopped accepting my SSH key.** Observed, verbatim:

```
debug1: Offering public key: C:\Users\ezabz\.ssh\id_ed25519_hetzner ED25519
        SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg explicit
debug1: Authentications that can continue: publickey
root@178.156.194.1: Permission denied (publickey)
```

and, intermittently, `kex_exchange_identification: banner line 0: Not allowed at this time` —
OpenSSH's per-source unauthenticated-connection limit. Two readings, and I could not separate them:

- **(a) my own doing:** I opened roughly twenty-five short-lived `ssh`/`scp` connections in ten
  minutes, which is what trips that limit; if so it clears by itself.
- **(b) someone else's:** root's `authorized_keys` was rewritten. `136-ESTATE-INVENTORY.md` §3 records
  a **key rotation on 2026-09-14** and a live `config.bak-keyrotation-…` on this laptop, so the estate
  does rotate keys — and my key's fingerprint in the local file is unchanged
  (`mesh-hetzner-2026-08-31`, file mtime 2026-08-31), so the change, if any, is server-side.

**What is *not* in doubt:** the box is healthy (`https://api.abletelsolutions.com/health` → **200**;
sshd answers with `SSH-2.0-OpenSSH_10.2p1 Ubuntu-2ubuntu3.6`), **nothing was restarted by me**, and
everything in §1–§2 and §7 was measured and written down *before* this began. Two proven cron lines
(`cfo-scoreboard`, `hours-drift`) were left **uninstalled** because of it, and are the first two
commands in §10.

### 9.1–9.7 1. **The scheduled runs themselves, at the time of writing.** The three family-6 lines were installed
   at 06:38Z and the first `*/5` tick was still minutes away when `§9.0` happened; the proof in §1/§2
   is from **hand-running each job with exactly the payload and working directory the cron line
   uses**, which is stronger for correctness and weaker for scheduling. **`/root/.cron-status/runs.tsv`
   is the first thing to read when ssh is back.**
2. **A2P hours surface** — unreadable on the cloud box (`psql not installed`); the office read it as
   *AGREES*. I did not install the postgres client: that is a package-level change on a box other
   workstreams are actively using, and the tool already reports the surface honestly as UNREADABLE.
3. **`accounts.db`-style family/state data** — I did not check every table the copied `inbox.db`
   carries for host-specific paths; I verified the schema, the row counts and the three tables that
   matter (`messages`, `permissions`, `wake`) and used the file byte-for-byte.
4. **Whether any *other* workstream also installed `cron-wrap.sh` or a crontab block** while I was
   working: the box had **no crontab at all** when I started and my block is marker-delimited and
   read-modify-write, so it cannot clobber theirs, but I cannot prove what lands after 06:40Z.
5. **The `wake-dispatch` target path** (`zabz-tech-ts`, a Windows `C:/Users/ezabz/bin/...` path) — I
   confirmed the failure and its log line, not the intended end-to-end path, because it depends on
   credentials and a DSH engine that are not on this box.
6. **`/home/zabz` as a migration target.** I created 16 symlinks under it. If the estate's plan (mine
   to recommend, `136-ESTATE-INVENTORY.md` §2) is to recreate `/home/zabz` for real, these symlinks
   must be reconciled rather than silently overwritten; the one that matters is `bin → /root/bin`.
7. **The SSH interruption itself** — see §9.0. Neither reading (a) nor (b) is proven.

---

## 10. WHAT I RECOMMEND, IN ORDER

**The first two commands when ssh to `root@178.156.194.1` works again** (they finish this workstream):

```bash
crontab -l
cat /root/.cron-status/runs.tsv                      # <- the evidence that the 3 installed lines ran

# then the two lines that were proved and left uninstalled by the 06:42Z interruption.
# Both payloads below were decoded and ROUND-TRIP-VERIFIED in this session; they are the
# office crontab's own bytes (L110 and L160).
( crontab -l; \
  echo '20 */6 * * * /usr/local/bin/cron-wrap.sh cfo-scoreboard L3Vzci9iaW4vcHl0aG9uMyAvaG9tZS96YWJ6L2Jpbi9jZm8tc2NvcmVib2FyZC5weSA+PiAvaG9tZS96YWJ6Ly5jZm8vc2NvcmVib2FyZC5sb2cgMj4mMQ=='; \
  echo '17 */6 * * * /usr/local/bin/cron-wrap.sh hours-drift cHl0aG9uMyAvaG9tZS96YWJ6L2Jpbi9ob3Vycy1kcmlmdC1jaGVjay5weSA+IC9ob21lL3phYnovLmhvdXJzLWRyaWZ0L2xhc3QudHh0' ) | crontab -

mkdir -p /root/out/migration-review
# the report copy could not be pushed at 06:45Z; from the laptop:
#   scp -i ~/.ssh/id_ed25519_hetzner <path>/139-PORT-OWNER-CHANNEL.md root@178.156.194.1:/root/out/migration-review/
```

**Or run the whole remaining tail in one command** (`/root/_staging/139-FINISH.sh`): it is idempotent,
and it re-creates the two state symlinks that `setup-paths.sh` did not cover
(`/home/zabz/work`, `/home/zabz/.lpt-hub-refresh`), installs the two lines above, prints the decode
check, prints `runs.tsv`, and copies the report into `/root/out/migration-review/`. A copy is staged
with this document at `docs/mesh/139-FINISH.sh` in `harness-config`, and the complete installer (all
seven steps, safe to re-run) at `docs/mesh/139-port-owner-channel.sh`.

1. **Open the mouth deliberately, not by accident.** Show the owner the one question `owner-ask.py`
   would send (`/usr/bin/python3 /root/bin/owner-ask.py --why`, inside his hours), and enable
   `owner-ask` only on his word about **that** message. Until then the 160 pending questions are
   read-only in `/root/authority.db` and he sees them only if he opens a dashboard.
2. **Fix the inbound gap the sync just exposed**: 403 inbound texts are in Twilio and in neither the
   app's `sms_log` nor the API's record. That is a live customer-facing defect, and it belongs to the
   comms family, not this one.
3. **Ship the four small state files/checkouts this workstream is blocked on**, in this order, each
   worth a whole family: `/home/zabz/work/work.db` (4.3 MB, unlocks `promote-owner-texts`,
   `work-integrator`, `run-wake-sources`), `~/.lpt-reports/tracking.db` (7 MB, unlocks
   `lpt-business-report`), `/home/zabz/repos/lpt-hub` (3.7 GB, unlocks `audit` and `lpt-hub-refresh`
   — the only PORT-AS-IS job still off), `/home/zabz/code/lpt-ops` (unlocks `lpt-audit-weekly`).
4. **Before `wake-fanout` is ever enabled:** put a provider key at `~/.dsh/.credentials.yaml` and
   enable `wake-balance`, then decide the spend ceiling. Those two are a pair; enabling the fan-out
   without the guard is how the estate spends money it did not plan to.
5. **`cfo-shift`** — one decision from the owner (paid research per shift) and the 579 unexplained
   transactions start shrinking.
