# Owner decision queue — triage report, and the action-tier design
Workstream: queue triage. Run: **2026-09-18T02:08Z → ~03:0xZ** (authoritative host clock).
Host path: `ssh secretary-ts` (Tailscale) — see §9. Scope: **classification + queue edits. No code changed.**
Database treated as read-only for every read; writes went only through the queue CLI or an equivalent bound write.

## 1. Counts

Triage pass — `python3 ~/bin/owner-queue.py stats`:

```
BEFORE                          AFTER (triage)
  answered: 7                     answered: 8
  dismissed: 31                   dismissed: 31
  pending: 28                     pending: 16
  resolved: 32                    resolved: 43
```

Re-classification pass (the owner's change of verb), same command:

```
BEFORE                          AFTER (re-classified)
  answered: 8                     answered: 8
  dismissed: 31                   dismissed: 42
  pending: 16                     pending: 17
  resolved: 43                    resolved: 32
  oldest pending: 2026-09-14T15:46   newest: 2026-09-18T02:25
```

Two movements are **not mine**, and I am stating them rather than smoothing them:

- **#80 was answered by another workstream at `2026-09-18T02:04:35Z`** while I worked (the owner
  chose the brace-and-through-bolt retrofit with the 40 mph rule). That is why the triage pass shows
  `answered 7 → 8` and pending fell by 12, not 11. I did not touch an answered row.
- **#99 was added by another workstream at `2026-09-18T02:25:07Z`**, which is the whole of
  `pending 16 → 17`. It is classified in §2; I did not touch it.

Net across both passes: **pending 28 → 17**, with `resolved 32 → 32` and `dismissed 31 → 42`.

## 2. Classification — all 29 rows

`HIS` = money, customers, legal or contractual posture, family, irreversible, genuine taste.
`ENGR` = a fault, a config question, a measurement, or a dev decision.

| id | one-line summary | class | evidence used |
|----|------------------|-------|---------------|
| 80 | Sukkah frame fails an independent wind check (118 mph site design) | HIS | Owner's property, liability, money. **Answered by him 2026-09-18T02:04Z** — accept retrofit + 40 mph rule. |
| 88 | Order the $130 Latitude 5490 for Weitman, send the $189 quote | HIS | Money + outbound message. **Another agent is handling it — see §4a. Do not re-surface.** |
| 99 | AI text line swallowed 70 of 325 inbound texts | HIS | A standing outbound authorisation: which correspondents we may answer without asking each time. Names family and self. |
| 79 | Sukkah frame built without a permit | HIS | Legal exposure on his property: per-week accrual, removal order, insurance. Row's dollars are **corrupted in storage** (§7, P265). |
| 42 | What to charge for a documents-only USB recovery | HIS | Price against a customer promise; $500 lab cost. |
| 20 | Bulk iPhone sourcing: domestic-only or offshore | HIS | Money + 47 CFR 2.803(b) import law + sourcing taste. |
| 75 | Dialpad may train its AI on our customer calls | HIS | Privacy/legal posture over customer conversations. |
| 17 | OUTWORQ Twilio SID/token/number committed to the repo | HIS | Rotation needs the account owner; the account is a **third party's** (Shimon Vogel). |
| 84 | Spend ceilings for the 55-agent plan | HIS | Dollar ceilings are money. |
| 78 | Port of his mother's line needs 4 fields from US Mobile | HIS | Family. |
| 41 | CHEMED results + 2 radiology reports on his portal | HIS | His own medical records. An action of his, not a system decision. |
| 93 | E4610 shipped today was staged, never finalized | HIS | Customer-facing recall + outbound message. |
| 96 | Weinberg WhatsApp page needs 3 facts about her | HIS | Reaching a customer; outbound is a hard stop requiring him. |
| 98 | GenTech paid filter as a sellable service, or free fix only | HIS | Service mix, price, vendor relationship. |
| 35 | Second account `moshemontrose` on Yocheved's Mac mini | HIS | Irreversible deletion of another person's home directory. |
| 65 | Deposits: `payment_transactions` row (PENDING) or case file only | **ENGR** | Data-representation choice; no money moves, no customer contacted. **Dismissed.** |
| 72 | Retire 4 exposed infrastructure credentials in one pass | **ENGR** | Our own AWS/Stripe/gateway accounts = ops. Third-party half split to #17. **Dismissed.** |
| 76 | Every inbound customer text delivered twice | **ENGR** | Both endpoints are the shop's own domains (DNS verified) — a duplicate webhook. **Dismissed.** |
| 83 | MDM enrolment profile served with no authentication | **ENGR** | Config on our own MDM host. **Reproduced by me. Dismissed.** |
| 73 | Shop alarm cannot arm itself (stuck boolean) | **ENGR** | Stuck helper + untested notification path. **Dismissed.** |
| 82 | Node-hygiene job scope | **ENGR** | Ops default; the conservative branch leaves his machines untouched. **Dismissed.** |
| 24 | HA Spotify lost its refresh token, 650 errors/window | **ENGR** | Dead OAuth + retry loop. **Dismissed.** |
| 92 | 5 divergences in the four-surface verifier | **ENGR** | 3 linker data errors, 2 a mirror/calibration measurement. **Dismissed.** |
| 89 | `personal-secretary-mvp` diverged into two branches | **ENGR** | Safe action is inaction; nothing blocked, nothing losable. **Dismissed.** |
| 95 | Netlify out of credits for 3 secondary sites | **ENGR** | Free migration to Cloudflare Pages. **Verified headers myself. Dismissed.** |
| 90 | 5 customer-credential files tracked in `lpt-hub` | **ENGR** | Repo is **private** (verified) and files are tracked (verified); no force-push needed. **Dismissed.** |
| 74 | One Cloudflare API token for the shop zone | ENGR (**action**) | The design is ours; needs a credential only he can mint. **Left pending** (§6). |
| 77 | Google still shows Wednesday 10:30 opening | ENGR (**action**) | Confirmed defect; fix needs his Google login. **Left pending** (§6). |
| 81 | DRN AT&T lines still allow calls | ENGR (**action**) | Method is ours; we hold no AT&T account number at all. **Left pending** (§6). |

**11 of 29 pending rows (38%) were engineering** — the same shape as the historical 595-vs-383 finding.

## 3. What the triage resolved

11 rows closed, each `--how` stating the closure and who does it. Three verified at source:

- **#83** — I reproduced it: `https://mdm.abletelsolutions.com/enrollment.mobileconfig` returns
  `HTTP/1.1 200 OK`, no auth, served by `WazeRestore/1.0 Python/3.13.13`.
- **#95** — `pricing.`/`admin.`/`gifter.` all carry Netlify's `x-nf-request-id`; the main site does not.
- **#90** — closed the one fact the row said it could not establish: `lpt-hub` is **private**
  (unauthenticated GitHub API 404; public control `torvalds/linux` 200 on the same instrument), and
  `git ls-files` yields exactly **5** tracked `_credentials-*` paths.

Others: **#65** (standing PENDING-never-CAPTURED payment policy, with the #92 link fix as a
precondition), **#72**, **#76**, **#73**, **#82**, **#24**, **#92**, **#89**.

**Two corrections I owe.** (1) My first pass dated my own verifications `2026-09-17`; the host clock
said `2026-09-18`. (2) #89's text asserted a dirty-file count I had not measured — re-measured
(176 behind / **119** ahead / **166** dirty; the row said 116/169). I re-resolved the five affected
rows; `resolve` overwrites by id, so re-resolving is the correct repair.

## 4a. #88 — another agent holds it. Do not re-surface.

The owner's words: *"Skip this another agent is currently dealing with it."* **#88 stays pending, is
not re-asked, and is excluded from the ordered list in §8.** Recorded here because a row another
agent is working is **invisible to the queue**, and the cost of that invisibility is his attention
spent on something already in motion. #79 is therefore the first decision still actually waiting on
him.

## 4. Re-classification to `dismissed` — done, with proof

All 11 are now `status='dismissed'` and **every resolution text is preserved byte-for-byte**.
`_close()` does `UPDATE … SET status=?, resolved_at=?, resolution=? WHERE id=?` — it **overwrites**
`resolution`, so the existing text was read first and passed back verbatim, guarded by
`AND status='resolved'` (so a concurrent writer cannot cause a clobber) and proved by sha256.

**Proof, both directions.** Each row's stored text was hashed before and after the write (equal for
all 10 written; #72 was already dismissed and untouched), *and* independently hashed from the source
scripts that originally authored it — 10 of 11 from `_fix_provenance.py`, #72 from `_resolve_queue.py`:

| id | sha256 (DB and source, equal) | len |
|----|-------------------------------|-----|
| 65 | `ad9d0e2f3daf728e` | 1127 |
| 72 | `edf327ad08f8dd94` | 926 |
| 76 | `cb45ae4945eb713c` | 1030 |
| 83 | `711f56bd7f14f0d5` | 1129 |
| 73 | `6f6a2f424eff7e25` | 808 |
| 82 | `94d5caa62e8d52bf` | 698 |
| 24 | `796c56ef4acfd96f` | 605 |
| 92 | `e7fd20869c692bf8` | 1223 |
| 89 | `1398c826aee4fb47` | 1451 |
| 95 | `915e17d9147b5f3f` | 1100 |
| 90 | `38ec7255a8c2a3cb` | 1395 |

**One thing that went wrong, and how it was fixed.** The first attempt called the CLI, which connects
with `sqlite3.connect(path, timeout=20)`. Under the live API's write load that is too short: it sat in
20 s lock waits, got **one** row through in 300 s, and the ssh client was cut off, leaving the remote
process orphaned (found and killed at 331 s). I rewrote it to write directly with `timeout=180` plus
`PRAGMA busy_timeout=180000`, replicating `_close()` step for step (commit the read snapshot *before*
the UPDATE, or the deferred read transaction cannot upgrade to a write and SQLite returns
`SQLITE_BUSY` immediately), and ran it detached. All 11 then completed with no contention at all.
This is my brief's documented case: `database is locked` here is transient contention, not failure.

## 5. The action tier — a design, not an install

**Read this first: the brief's premise is wrong in one respect.** There is **no `check_owner_queue`
in `~/ceo-kernel/ck/sentinel.py`**. The checks that exist are `check_attention_debt` (line 622),
`check_delivery` (704), `check_liveness`, `check_completion`, `check_evolution`, `check_replication`,
`check_config_sync`, `check_model_failover`, `check_session_archive`, `check_phone_endpoint`,
`check_comms_freshness`, `check_telemetry_gaps`, `check_empty_ticks`, `check_dead_weight`. Neither
`check_attention_debt` nor `check_delivery` reads `owner_decision_queue` at all — they read
`agent_questions` and `owner_message_queue`, which are different tables answering a different
question. So this is not a parameter change to an existing check; it is a **new check**.

### 5.1 The column

```sql
ALTER TABLE owner_decision_queue ADD COLUMN kind TEXT NOT NULL DEFAULT 'decision';
-- values: 'decision' | 'action'
```

`action` = waits on his **hand** (a login, an account number, a credential mint). `decision` = waits
on his **judgement** (money, customers, legal, family, irreversible, taste). #74/#77/#81 are the test
case. The default is `decision` so every existing row keeps its meaning and no writer changes
behaviour until it opts in.

### 5.2 Migration risk — corrected

- **The app does NOT read this table.** `grep -rn "owner_decision_queue"` over the authority's
  `personal-secretary-mvp` checkout returns **0 occurrences** (`.py` and `.js/.ts/.mjs`). The claim
  that the live application reads it is not supported. The consumers are `~/bin/owner-queue.py`
  itself, `journal.py questions` (over ssh), and `journal/tools/reconcile-questions.py`.
- **The real risk is DDL under contention.** `owner-queue.py` calls `executescript(SCHEMA)` on
  **every** invocation (`connect()`, authority copy lines 82-87), so `CREATE TABLE IF NOT EXISTS`
  runs a write on every read — and `IF NOT EXISTS` **will not add a column to an existing table**.
  So the `ALTER TABLE` must be run **once, explicitly**, under `busy_timeout`, not left to the
  schema bootstrap. The locks audit already flags this as **F10** and recommends gating the schema
  behind `PRAGMA user_version` and opening read-only for `list`/`next`; this migration is the moment
  to do that, or every later read keeps taking a write lock on a 500 MB database that 18 agents and
  a live API are also writing (see #99, §7).
- **The live CLI is tracked in no repository (P47).** `~/bin/owner-queue.py` has no git history, and
  the repo copy at `harness-config/scripts/owner-queue.py` is a **stale 9,761 B pre-patch version**
  against the live **10,911 B** — it is not a usable rollback. Take a `cp` backup on the authority
  before editing.
- **The JSON contract is additive, so it is safe in both directions.** `journal.py questions` reads
  `id, asked_at, severity, question, recommendation, status`. An older mirror ignores a new `kind`
  key; a newer mirror must `r.get("kind") or "decision"` so it still works against an authority that
  has not been upgraded. Do not rename or reorder anything.

### 5.3 What each surface must do

**`~/bin/owner-queue.py` (authority)**
- `add`: `--kind decision|action`, default `decision`; bind it as a parameter like the rest.
- `next`: the sort key (lines 185-192) currently puts `critical` first, then blocking, then severity,
  then age. Add a **leading** element so `kind='decision'` sorts before `'action'`. That is the whole
  point: an action must never take the one-question slot. But it must not become invisible — `next`
  prints a one-line trailer, `N action(s) awaiting your hand: #74 #77 #81`.
- `next --kind action` / `next --actions`: the action list, ordered by severity then age.
- `list`: add a Kind column; default shows decisions, `--kind action` shows actions, `--all` shows both.
- `stats`: break the pending count down by kind —
  `pending: 17 (13 decisions, 1 in-flight elsewhere, 3 actions)`.
- `fmt`: print `ACTION` in the header instead of `QUEUE` when kind is `action`.

**`journal.py questions` (mirror, lines 2027-2084)**
- Split the single table at 2071-2072 into **two**: `## DECISIONS — waiting on you` and
  `## ACTIONS — waiting on your hand`, each with a Kind-free header (the section carries it).
- Header provenance (2068-2069) counts both: `N row(s) read, X decisions, Y actions`.
- The `status` page line 1495 (`OWNER QUESTIONS %s open`) splits to `%s decisions + %s actions open`,
  so the always-read page cannot imply 17 decisions when 3 are logins.
- Keep the "add it there, not here" line (2067) — it is doing real work.

**`ck/sentinel.py` — new `check_owner_queue`**
- Follow the house pattern exactly: `sources.scalar`/`sources.rows` with `name=`, collect
  `refusals`, build `provenance` packets, return
  `Finding(check=…, severity=…, ok=…, summary=…, metrics=…, refusals=…, provenance=…)`.
- **Rank decisions only.** Metrics: oldest pending *decision* age, count by severity, blocking count.
  Alarm on the oldest **decision**, the way `check_attention_debt` alarms on the oldest question.
- **Count actions separately** and never let them into the decision alarm — a login waiting 10 days
  must not read as "the owner is ignoring 14 decisions". But do surface them, or they rot: a
  `held`-style INFO/HIGH summary (`3 actions awaiting the owner's hand, oldest 2d`).
- A stale or unreadable queue is `UNKNOWN`/not-ok with the refusal recorded, not a green reading —
  the same discipline `check_attention_debt` already uses.
- Do **not** mirror the table into the kernel. Read it through the same `sources` layer.

**Prompts and presets** — `presets/zabz/agent.cordis.yml` (lines 121, 135) and its generator
`scripts/make_zabz_preset.py` tell every session the queue "holds only what is genuinely his" and to
read it at the start of substantial work. That text must describe the two kinds, or the next session
re-derives exactly the confusion this pass just cleaned up.

## 6. Left pending on purpose — 3 actions, not decisions

Resolving these would have deleted the only record that the action is outstanding; `--how` is not a
task tracker. Each is a **2-minute action**, not a question:

- **#74** Cloudflare API token — the highest-leverage item in the queue: it unblocks the resolved
  #95, the public-hours fix, the filterapp DNS record, the R2 backup isolation and PR 142.
- **#77** Google Business Profile hours — needs his login; the only surface still sending customers
  to a locked door on Wednesdays.
- **#81** AT&T voice bar — needs the carrier account, which our records do not even name.

## 7. What I could NOT verify

- **Row #79's amounts are corrupted in storage** (`\,000`, `\-300`, `min \ permit`, `\-75`), read via
  **read-only sqlite3**, so the loss predates my read. Filed as **pain P265**, which also found the
  same class in **#33** (price gone from `/device/mo`; `-10` band; a double space where `$N` was) and
  **#86** (`at \.00286/call` = `$0.00286`). Three rows, one class; `#38` is a cosmetic false
  positive. **I guessed no amounts**, so #79's legal exposure cannot be priced as written.
- **The kernel premise:** `check_owner_queue` does not exist and neither `check_attention_debt` nor
  `check_delivery` reads this table — verified by reading `sentinel.py`, not assumed.
- **The app-reads-the-table premise:** 0 occurrences of `owner_decision_queue` in the
  `personal-secretary-mvp` checkout on the authority.
- **#72 / #17 credential liveness:** I tested no credential, and did not verify the AWS IAM inventory
  or the Stripe 200 at source.
- **#80:** I did not re-derive the structural analysis; I confirmed the committed artifact
  (`lpt-hub` `e5795e2bf`) corroborates it verbatim.
- **#92:** I did not run `tools/customer/audit.py` to reproduce 5 ERROR / 66 WARN.
- **#88:** not re-checked at source — and it is in another agent's hands.
- **#99:** I did not verify the 70-of-325 loss, the recovered ledger, or the 5-minute reconciler; I
  classified it from the row's text plus the corroboration in the next bullet.
- **#74:** could not verify the *negative* that no Cloudflare token exists on any of four hosts.
- **#89 / #98:** verified the divergence and the Netlify headers, but not the 54-conflict per-path
  tally, nor GenTech's wiki claims.
- **#80's provenance:** something answered it at `02:04:35Z` and I did not witness it.
- **Corroboration on contention:** my own write hit `database is locked` exactly as **#99** describes
  (70 of 325 inbound texts lost to HTTP 500 on the same condition). Same cause, one with a retry and
  one without.

## 8. The rows genuinely his — ordered, one recommendation each

**#88 is excluded** (another agent holds it). 13 rows.

1. **#79** — Sukkah permit. *Recommend: the ~$75 facts-first route* (zoning determination + one
   neutral question to the Construction Official). Cheap, reversible, admits nothing — and on this
   code, volunteering is itself the discovery event. **Note the row's dollar figures are corrupted;
   the amounts must be re-derived before he prices the exposure.**
2. **#99** — AI text line swallowed 70 texts. *Recommend: approve the three he already treats as
   family-or-self and queue everyone else.* Real people are still sitting in silence, including
   someone whose car won't start.
3. **#41** — Your CHEMED results and 2 radiology reports. *Recommend: read them yourself.* Waiting
   since 09-14.
4. **#75** — Dialpad AI training on customer calls. *Recommend: turn it off at company level.* Costs
   us nothing we use; we record and transcribe every call.
5. **#42** — Documents-only USB recovery charge. *Recommend: option A — show the file listing and let
   the customer define "success".* Keeps the promise intact without eating a $500 lab bill; lands in
   about a week.
6. **#17** — OUTWORQ Twilio token. *Recommend: rotate it (or authorise the drafted Shimon message).*
   Live, and in git history twice on origin.
7. **#93** — E4610 recall for finalize. *Recommend: ask for it back.* Without finalize it is not a
   finished filtered phone.
8. **#20** — Bulk iPhone sourcing. *Recommend: dual-track* — one small domestic lot now, offshore
   quotes as a price ceiling only.
9. **#78** — Your mother's US Mobile port fields. *Recommend: send the four values, or let me call
   her.* Needed in about a week.
10. **#84** — Agent spend ceilings. *Recommend: 35/80/150 with a 12-agent cap per machine.* Your
    current $50 stop is hit in 44 minutes at 55 agents.
11. **#96** — Weinberg WhatsApp page. *Recommend: get the three facts in one message.* Unfilled rather
    than guessed, because a wrong number sends strangers to a stranger's WhatsApp.
12. **#98** — GenTech reseller question. *Recommend: ship the free fix now, revisit on a second request.*
13. **#35** — The `moshemontrose` account on Yocheved's Mac mini. *Recommend: archive, then delete,
    once you confirm whose data it is.* Low consequence today.

## 9. Journal and infrastructure

- **Appended without a claim, as instructed** — `journal.py append` did **not** refuse for a missing
  fresh claim. Two entries: lesson **L1969** (the transport finding) and pain **P265** (the
  corruption). I did not run `journal.py claim` and merged nothing; `journal.py check` exits **0
  errors** (88 pre-existing warnings, all dangling refs).
- **`secretary-cf` (Cloudflare tunnel) is unreliable**: ~1 call in 3 failed with *"Connection timed
  out during banner exchange"*, serialised and parallel, while **`secretary-ts`** never failed.
  Every command here ran over `secretary-ts`. A timeout there is **transport**, not evidence about
  the thing measured — three verifications in this pass would have been falsely reported as
  unverifiable had I accepted the first failure.
