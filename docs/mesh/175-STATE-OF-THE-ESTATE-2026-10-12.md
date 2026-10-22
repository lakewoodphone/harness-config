# 175 — THE STATE OF THE ESTATE, 2026-10-12: what is true, what is broken, and what is actually the owner's to decide

**Session:** 2026-10-12 05:00Z–05:40Z. **Author:** Zabz, `ZABZ-YOGA`. **Written after reading the four
master records** (`160` mesh, `170` attention badge, `171` cloud authority, `172` search) plus `000`
systems register, `173` durability/Chip, `174` cron inventory, `169` cloud-vs-office, `168` attention
authority and `PROGRAM.md` — and then **re-measuring every load-bearing claim live** rather than
quoting the documents.

**Machines touched:** `secratary-cloud` (THE AUTHORITY — reads only, no service state changed);
`secratary` / `secratary-ts` (FROZEN anchor — `systemctl is-active`, `crontab -l`, read-only);
`ZABZ-YOGA` (this seat). Nothing was started, stopped, enabled, disabled or restarted anywhere.

**Why this document exists.** Four master records were written within one night by four concurrent
sessions. Each is excellent and each is partial, and **they disagree with each other in three places**
(§7.1). Nobody had stood back and said what the estate *is* now. That is this file.

---

## 0. IF YOU READ ONLY ONE SCREEN

| | |
|---|---|
| **the estate's real state** | **Working, and better than it was 48 hours ago.** The authority is live (3 h 55 m up, one boot ever), the badge reads a live sentinel, search works in every mode, the database is backed up offsite and sha-verified at both ends, the deadman pings healthchecks.io every 5 min and gets 200, three of five mesh nodes answer in 73–195 ms, and the frozen office box can no longer fire a single company job (0 real crontab lines). |
| **the one thing that will bite** | **Memory on the authority.** 7.7 GB box, `company-api` at 4.5 GB RSS / 5.7 GB peak, 2.0 GB of 4.0 GB **swap in use**, `MemoryMax=infinity`, and one kernel OOM kill in the last 24 h. This is the only recurring failure that is *not* engineering — it is a 20–30 USD/month instance resize, and it is the owner's. |
| **the biggest real defect found tonight** | **The record is single-copy and its citations only resolve on one machine.** 49 files in `docs/mesh/` exist on this laptop and nowhere else (the authority has 83, this laptop 131) — and **276 journal entries**, including every one the master records cite, exist only here too; all five ids tested (`H3568`, `L3736`, `P3139`, `W2738`, `D3050`) are ABSENT on the authority, whose own ids sit in a different range. §4.1, §4.3. |
| **the queue is the other defect** | `owner_decision_queue` holds **162 pending**. **118 of them (73 %) come from three automated generators** — 90 from one night's work-order sweep, 10 from a board walk, 6 asking the same low-balance question six times. Triage in §5 finds **9–10 items that are genuinely his.** He said "you are being annoying"; this is the mechanism. |
| **what is mine to do next** | 12 items, ordered, in §6 — led by the durability of those 49 docs, the mesh's two dead roster rows, and the two kernel checks that still measure the wrong thing. |
| **what is his** | **One question tonight** (§5.1): the authority's memory — resize the instance, or keep it and cap the app. |

---

## 1. WHAT IS VERIFIED WORKING, WITH ITS EVIDENCE

Every row measured this session, 2026-10-12 05:05–05:20Z, from the authority or from this laptop.

| system | state | how it was measured |
|---|---|---|
| **the authority** `secratary-cloud` | up, `company-api` active since 01:22:01Z, **3 h 55 m**, one boot | `systemctl status company-api` |
| **the placement broker** | `active`, uptime 7,110 s, started 03:18:07Z, `nodes: 5`, `leases.live: 0` | `curl :3091/healthz` |
| **`zabz-tech`** | **ok**, 86 ms, 32 cores, 39.7 GiB free RAM, 0 % swap, 224.9 GiB disk free | broker `nodes?fresh=1` |
| **`zabz-yoga-1`** (this laptop) | **ok**, 195 ms | same |
| **`zabz-tech-linux`** | **ok**, 73 ms — and it is the node that answers 404 on `/mesh/health` while answering `capacity` 200, which is exactly what `node-probes.js` now handles | same |
| **`secratary`** (frozen) | `excluded: true` in the roster; broker still probes it and gets `unreachable` in 89 ms | `nodes.json`, broker |
| **`lakewooechsmini`** | `unreachable`, **4,001 ms** — still the single largest cold-placement term (P3134) | broker |
| **the attention badge's producer** | **live**: `/root/ceo-kernel-var/latest.json` written 05:15:08Z, host `secratary-cloud`, `read: true`, `age 0.3 s`, 19 checks, `attention: 4`, `dropped: 0` | `curl :3086/dsh-attention.json` |
| **the sentinel's absence monitor** | `state: ok`, `newest row 294 s old`, 8,547 rows, threshold 1,200 s, `alarm: not needed` | `/root/.sentinel-freshness/status.json` |
| **the scheduler** | 34 wrapped cron jobs on the authority + **18 systemd timers**; `run-sentinel`, `sentinel-freshness`, `config-sync-status` all present | `crontab -l`, `systemctl list-timers --all` |
| **the external deadman** | firing every 5 min, **`ping http 200`**, `offsite=ok`, `db_tables=654`, `verified=ok` | `journalctl -u authority-deadman` 05:11 and 05:16 |
| **the offsite database copy** | **fresh and verified both ends**: `finished_at=2026-10-12T03:49:48Z`, `status=ok`, `database_verified=ok`, `remote_last_modified=03:47:07Z` | `/var/lib/authority-backup/last-run` |
| **the offsite age reporter** | `authority-report-offsite-age.timer` fired 05:13:55Z, next 05:43:55Z | `systemctl list-timers` |
| **search — every mode** | `check-faindex-freshness` → **`verdict: OK — 3 index(es) present and current`**; paths index age 660 s, 3,259 journal entries indexed = 3,259 on disk | run on the authority |
| **the tool-body guard** | **601 active tools, 601 with a body, 0 without** | `/root/bin/tool-body-guard.py` |
| **the API's own catalogue** | `/v1/models` → **HTTP 200 in 0.011 s** (it was 4.1 s with a 60 s stall four hours ago — §7.2) | `curl` |
| **the frozen office box** | `cron` **inactive**, `secretary-api` **inactive**, `phone-gate` active, `mesh-broker` **active**; crontab = **0 real lines** | `systemctl is-active`, `crontab -l` |

**Read the negative rows carefully.** An empty result is a refusal, not health: `secratary` and
`lakewooechsmini` are *unreachable from the broker*, which is what is claimed — not "down".

---

## 2. WHAT IS GENUINELY BROKEN OR AT RISK, BY DOMAIN

### 2.1 Money and the company — the authority's binding constraint is memory

| what | the measurement | who |
|---|---|---|
| `company-api` memory | **4.5 GB RSS, 5.7 GB peak, 1.4 GB swapped, swap peak 2.2 GB**; box total 7,742 MB | — |
| box swap | **2,000 MB of 4,095 MB in use (49 %)**; `available` 5,353 MB | — |
| OOM kills | **1 kernel OOM in the last 24 h** (3 on 2026-10-11). `MemoryMax=infinity`, so the kernel picks the victim | — |
| the cause | not established. Candidates named in `171` §9: `/opt/company/data/chromadb` 2.9 GB + `mem0` 1.1 GB, single uvicorn process, RSS climb while idle | — |
| disk | 55 G of 75 G used (77 %), 18 G free — the 24 GB database lives here | — |
| **the decision** | **resize the instance (CCX23, 4 vCPU / 16 GB, ~20–30 USD/month, `171` §6) or cap the app and move the nightly ingest off the box.** Until answered, do not add work or raise tick rate here | **OWNER** |

Also open and genuinely his, from the same queue: `lpt-apps-01` **disk at 90 %** (`PROGRAM`/`000`
says 90 % full, "do NOT add load"; the queue has five flagged readings 85 % → 96 %), the **prepaid AI
balance** (six duplicate rows), the **Amex decline**, **Deep Infra dead since 2026-10-02 (402)**, and
**Chip's four unanswered family messages** — no, that last one is done (§3).

### 2.2 Durability and memory — the estate's institutional memory is thinner than it looks

Three separate findings, all measured, all the same shape:

1. **49 migration documents are single-copy.** §4.1.
2. **`data/tools/` is guarded but still untracked** (`172` §5.2). 601 tool bodies were restored from
   the frozen box and are guarded hourly — but they are still outside version control, so the guard
   *catches* a loss and cannot *prevent* one.
3. **Yisroel's Mac has never contacted the transcript archive.** Zero rows, ever (`170` §4). Its fix
   is staged, not applied, and needs a credential on an employee's machine — the owner's to name.

### 2.3 The mesh — healthy, with two dead roster rows and one missing channel

- **Proven to work**: a broker that reads nodes, a fallback that no longer discards a node for a
  missing health route, and two real children placed on two nodes with `MESH-HOST` matched (`160` §2.6).
- **Two roster rows cannot be read**: the frozen box (deliberate, `excluded: true`, costs 89 ms) and
  **the Mac mini (4,001 ms on every cold placement)**. Listing the authority in that machine's
  `phone-gate-allow.txt` removes the tax *and* returns a 10-core worker — it needs the Mac awake.
- **Parent → child while it works does not exist** for a mesh child, and the mailbox thread directory
  is not created at dispatch, so a child's report says `0 message(s)` into a conversation that is
  silently empty (`160` §4, `000` §2.3).
- **The office broker is still running** and enabled while the authority runs its own — two lease
  ledgers, so two dispatches could both fill one machine. It is a **one-line state change on a frozen
  host**, and this estate's own guard refuses it without the owner: question **#447**.

### 2.4 Search — fixed, guarded, and one real hole left

`172` is the record. What is still open, in the order I would do it:

1. **`zabz-tech`'s desktop index is 27 days stale and its task returns 1 — the cause is NOT
   established** (`172` §5.1, `H3574` has what is ruled out and the exact 20-minute run).
2. `data/tools/` untracked (§2.2).
3. The cold first touch after an index rebuild is still unmeasured (`172` §5.4).
4. Nothing asserts the MCP server's **tool list** actually contains `ps_search` (`172` §5.7).

### 2.5 The kernel — two checks still measure the wrong thing

Both diagnosed in `170` §5 and deliberately not patched, because each needs a threshold:
`liveness` prints a constant (`None → 0`, so it cannot go stale — it said "0.0m ago" against a true
3,059 s), and `db_writable` escalates HIGH on a **6-second** probe while **30/30** acquires succeed
at 25 s. Two of tonight's four badge findings are these. **They are mine and they are small.**

### 2.6 Documentation — the corpus is fragmented across machines

| machine | mesh docs | note |
|---|---|---|
| this laptop (`ZABZ-YOGA`) | **131** | holds `131`, `142-ANCHOR-WRITE-NOTICE`, `132`, `135`–`160`, `174` and **not** `173`, `174`-as-committed |
| the authority (`secratary-cloud`) | **83** | holds `173`, `174`; missing the 49 above |
| the frozen office box | — | holds the migration set, which is *why* an agent unbroke the freeze on 11 October (`142`) |

`000-SYSTEMS-REGISTER.md` §1 still says the agent roster is 18 when the measured figure is 126, and
§2.2 still names the office box's pushers as the offsite mechanism (`173` §8.5). `AGENTS.md` §1 still
names the frozen box as the archive host (`170` §6.3.9).

### 2.7 The queue — an intake defect, quantified

`owner_decision_queue`, read 05:20Z: **446 rows all-time — 190 resolved, 59 dismissed, 35 answered,
162 pending.** Triage of all 162:

| source | n | verdict |
|---|---|---|
| `lpt-work-order-sweep` (2026-10-09, one night) | **90** | per-order "was this paid?" questions. Mostly answerable from the comms archive and the order DB; the rest collapse into ~3 shop rules |
| `lpt-board-walk-20261008` | **10** | board hygiene; several merge with the above |
| `wake-balance` | **6** | **one question asked six times** |
| **everything else** | **56** | of which **14 are high**, and of those **9–10 are real** (§5) |

---

## 3. WHAT CLOSED SINCE THE MASTER RECORDS WERE WRITTEN

Recorded so nobody re-opens them:

- **Chip is fixed, measured, and deployed** — rulebook 6,455 → 7,653 chars, `chip_direct_max` 30 → 6,
  a burst ceiling of 2/30 min, a dismissal gate above the addressed branch, secretary tools off.
  Measured on the family's own messages: **answered 6 of 7 → 2 of 7**, self-register lines **13 of 18
  → 1 of 6** (`173` §2). The observation window opens the next time someone addresses him.
- **The authority publishes its own repo**, daily, and the job **refuses on divergence with no force
  path** (`173` §2.5).
- **The offsite database backup was never missing** — `173` §1.3 corrects a finding I had repeated;
  it is verified live above.
- **The office box is inert, not masked** — 0 real crontab lines, 177 saved (`173` §2.7), confirmed
  read-only by me at 05:19Z.
- **`config_sync` diverged for ~2 minutes and healed itself** (§7.2).

---

## 4. THE FINDINGS THIS SESSION ADDS

### 4.1 The migration's governing documents exist on one laptop only — and the laptop cannot push them

**The measurement.** The authority's `docs/mesh/` holds **83** files; this laptop's holds **131**. The
49 that are on the laptop and nowhere else include `131-MIGRATION-BRIEF.md`,
`142-ANCHOR-WRITE-NOTICE.md`, `132-CRON-INVENTORY.md`, `135`–`160`, and `174`. They are *committed*
— `131-MIGRATION-BRIEF.md`'s last commit is `3d071e40`, "the migration record, complete" — so they are
not uncommitted work. They are simply **in no copy that survives this laptop**:

| copy | holds them? | measured how |
|---|---|---|
| this laptop's clone | **yes** | `git log -1 -- docs/mesh/131-MIGRATION-BRIEF.md` |
| the bare repo on the **frozen** office box (`origin`) | **yes**, via the laptop's push | `git remote -v`, this laptop |
| the vault (the declared canonical remote) | **no** | `git ls-remote vault main` → the laptop has no vault credential at all (`170` §4) |
| the authority's clone | **no** | the 49-file diff, both machines |
| GitHub `offsite` | **no** (and its `main` is behind by design, P3135) | `172` §5.3 |

**Why it matters, in the estate's own words.** `142-ANCHOR-WRITE-NOTICE` records that the 11 October
incident happened *because* "the migration's six governing documents existed only on ZABZ-YOGA. The
machine they governed carried none of them." That condition is **still true for 49 documents**, and
one of the two copies that does exist is the frozen box this estate is trying to retire.

**It is not a pull problem.** The authority's `origin` is `/root/hc-main.bundle` — a bundle on its own
disk — and it is **39 commits behind its own HEAD**; the vault is current because `journal-commit`
pushes it every 15 minutes. So the fleet's topology now has three remotes that disagree by design, and
**no single machine holds the union of the documentation**.

**Fix shape** (mine, §6.1): push this laptop's `main` to the vault from a machine that has the
credential, verify the 49 paths exist on the authority, then make `config_sync` measure the *content*,
not just HEAD equality.

### 4.2 `config_sync` raised DIVERGED and was right for 2 minutes — then healed silently

At 05:15:08Z the badge read `DIVERGED: local main is d3740df but ... vault ... refs/heads/main is
5ae9f77`. I measured it at 05:17:33Z: **`clean`, local HEAD `e962a7b` = vault `5ae9f77`'s descendant,
`git rev-list --count vault/main..HEAD` = 0.** The two SHAs were simply two concurrent sessions'
commits landing in either order inside one `ls-remote` window. The check is correct and its subject is
genuinely concurrent — **but a 15-minute cache plus an instant-sampled comparison means a healthy repo
will periodically report HIGH**, and a HIGH that is usually wrong is worse than no check. Fix shape:
require the disagreement to persist across two consecutive samples before it escalates (§6.3).

### 4.3 The journal's ids mean different things on different machines — so the master records' own citations do not resolve

**Measured by hashing every entry on both machines** (`journal/entries/**/*.md`, sha256, both sides):

| reading | value |
|---|---|
| entries on this laptop | **3,511** |
| entries on the authority | **3,262** |
| filenames present on **both** | **3,235** — and **every one of them has an identical heading and different bytes** |
| **on this laptop only** | **276** |
| **on the authority only** | **27** |

**What that means, precisely, and what it does not.** The bytes differ because the two trees were
written by different paths (240 of this laptop's entries carry CRLF; the authority's are LF). The
content is the *same content* — `P1` on both machines is the same `P1`. **This is not the two-entries-
one-id catastrophe the check exists to prevent**, and the laptop's `journal.py check` reports 0 errors.

**The part that does hurt.** The 276 laptop-only entries are precisely **the entries every master
record from tonight cites**: `journal.py show H3568` (173), `L3736` / `D3050` / `P3139` (170, 171),
`L3743`–`L3746` / `W2739` / `P3138` (172) — **all five I tested are ABSENT on the authority**, whose own
counter sits in a different range (`L3620`, `P2936` for entries I wrote an hour ago). So:

- every `docs/mesh/*` record written on this laptop cites ids a reader on the authority cannot open;
- the authority's own fast-search index covers its 3,259 entries — **not** the 276 that carry tonight's
  reasoning;
- and the same document reads differently depending on which machine you are standing on.

**It is a known class with tooling already built for it** — `journal.py repair-ids --apply`,
`dedupe --apply`, `import-legacy --apply`, and the cross-machine repair record in `163`. **What is
missing is the convergence itself**, and a decision only the estate can make: *which machine is the
one allocator of journal ids.* Every machine currently allocates its own, which is why the two spaces
drifted apart while both stayed internally consistent.

### 4.4 The broker's own counters say what the documents do not

`reads: 40, readFailures: 25` — a **62 % read-failure rate** — while three of five nodes answer in
under 200 ms. The failures are the two unreadable rows (§2.3) multiplied by retries, and they are
*counted, not hidden*, which is the right design. Recorded so nobody reads "62 % failure" as a broken
mesh.

---

## 5. THE QUEUE, REORGANISED: WHAT IS ACTUALLY HIS

His standing rule, in his words: *"you work on all of them as they come up, and the ones that
absolutely need me and you can't solve you bring up with me one at a time."* Of 162 pending items,
this is the honest split.

### 5.1 His, and I recommend an answer to each — the only ones that should reach him

| # | ask | my recommendation |
|---|---|---|
| **228** | The business takes ~4,500/month out of your personal accounts (deferral expired 2026-10-09, **blocking, 10.6 days**) | **Set the 90-day test: zero subsidy by 1 January 2027.** The subsidy has already roughly halved without a decision (6,608 → 3,987/month) |
| **444 / 442 / 440 / 433 / 429** | *six identical rows*: prepaid AI balance is low, top it up? | **One question, one number.** Merge to one row; see §7.3 — I could not read a balance this session |
| **the memory question** (not yet in the queue) | Resize the authority to 4 vCPU / 16 GB, or cap the app | **Resize.** The box's working set is 7.5 GB against 7.7 GB of physical with the kernel choosing OOM victims (§2.1) |
| **#207** | T-Mobile home internet never cancelled, 85/month, next debit ~19 Oct; **deferral expires 2026-10-14** | **Cancel it.** It fires in two days if unanswered |
| **#284** | The Android release signing key exists on one laptop only | **Put the second copy on the vault** — it is the one place this estate already treats as canonical |
| **#279** | Amex: `welcome.americanexpress.com` "Future Transactions May Be Declined" | Money and credit standing, his to name |
| **#261** | Deep Infra dead since 2026-10-02, 402; traffic failing over to DeepSeek direct | **Drop Deep Infra and make the failover explicit** rather than silent |
| **#303** | The shop's phone line: fast Dialpad→Twilio unification, or a longer migration | His taste and his customers |
| **#439** | `lpt-apps-01` disk at 90–96 %, five flagged readings | A cleanup plan exists to be written; the box hosts the R2 credential |

### 5.2 Mine — resolve out of his queue without asking him

- **#445** — *"the cloud authority is not on the tailnet"*. **False when written.** `000` §1: the
  authority has been on the tailnet since before 21:35Z on 11 October (`100.73.176.126`, direct), and
  a private API path works end to end. **Resolve it, citing §1.**
- **#283** — *"the broker runs two instances against one SQLite file — one writer, or Postgres?"*
  A development decision. The estate already has a one-writer rule; decide, record, move on.
- **The 90 `lpt-work-order-sweep` rows and the 10 `lpt-board-walk` rows** — §6.2. Most are answerable
  from the comms archive (`ps_comms_search`, 179 k indexed records) or collapse into three shop rules.
  **Asking the owner 90 times a question his own database answers is the defect itself.**
- **`wake-balance` × 6** — a duplicate-emitter bug. Fix the emitter, merge to one row.

### 5.3 Also his, but not tonight

`#284`, `#207` and the Mac archive credential (`170` §6.2) are the three with a date attached. Nothing
else here should be read to him before §5.1 is answered.

---

## 6. WHAT I DO NEXT, IN ORDER

### 6.1 Durability (highest value — the estate's memory is the asset)

1. Get this laptop's 49 missing mesh docs **into the vault and the authority**, from a machine that
   holds the credential. Verify by counting files, not by reading a push's exit code (§7.2).
1b. **Converge the journal (§4.3)** — the 276 laptop-only entries onto the authority, with the
   cross-machine alias/repair tooling `163` describes, and then decide the one allocator of journal
   ids. **This is the item that makes every other document's evidence readable.**
2. Make `config_sync` measure content coverage, not HEAD equality (§4.2), so a document or an entry
   that exists on one machine is a finding, not silence.
3. Track `data/tools/` (`172` §5.2) — the guard catches a loss; nothing prevents one.
4. The Mac's push mechanism (`170` §6.2) — needs the owner to name a credential on an employee's box.

### 6.2 The queue's intake (the second-highest)

5. Classify the **90 + 10** sweep rows: answer from the comms archive and the order DB what is
   answerable; collapse the rest into three rules (*"a finished order in READY_FOR_PICKUP with no
   payment row is collected unless the case file says otherwise"*, and the two like it); escalate only
   what truly needs his memory of the shop.
6. Fix the `wake-balance` duplicate emitter (6 rows → 1).
7. Resolve `#445` and `#283` with the record, not with a question.

### 6.3 The engineering residue

8. **`liveness` and `db_writable`** (`170` §5.1, §5.2) with thresholds derived from the measurements —
   `170` names both fix shapes.
9. **The Mac mini's `phone-gate-allow.txt` line** (removes the 4,001 ms tax, returns a worker).
10. **The mailbox thread directory at dispatch** (`160` §5 step 3) — restores the only cross-turn
    channel the engine allows.
11. **`company-api` restart** to load the tested lane-health gate and board-seat guard (`170` §6.3.1).
12. **`zabz-tech`'s stale search index** — the 20-minute diagnostic run `H3574` specifies.

---

## 7. WHAT I CORRECTED, AND WHAT I COULD NOT VERIFY

### 7.1 The three places the master records disagree

| disagreement | resolution |
|---|---|
| **how many office jobs never reached the cloud**: `171` §1.4 says **59 of 93**; `174` §A classifies all 93 and says **64 are neither ported nor provably dead** | **`174` governs — it carries the per-row evidence.** `173` §8.8 already says so; the headline number should be reconciled rather than quoted. A method difference (a job-name match versus reading each script), not a disagreement about any job |
| **whether the offsite backup exists**: my own earlier finding said no; `173` §1.3 says it was built before I said that | **`173` is right**, and it is verified live in §1 above |
| **whether the authority is on the tailnet**: `#445` still says it is not | **It is** (`000` §1). Close it |

### 7.2 Two claims I nearly made and did not

- **"The GitHub mirror is diverged and every push fails"** — true (`172` §5.3, L3748), and **not news**.
  `git push origin` exits 1 while the push that matters succeeds. I read the exit code as a failure
  before checking, which is the exact trap L3748 was written about.
- **"`config_sync` is broken"** — I caught it mid-transient (§4.2) and verified it clean two minutes
  later. The defect is the *sampling*, not the check.

### 7.3 What I could not read

- **A prepaid AI balance.** Six queue rows say it is low and none carries the number; the database and
  the gateway were checked and hold no balance. **That is a finding**: a money question with no
  measured figure behind it cannot be answered by the owner either. Fix before re-asking — the emitter
  must record the balance it measured.
- **Whether the OOM of the last 24 h was `company-api`** — one kernel OOM was counted; the victim was
  not named this session (`171` names three on 11 October, all the API).
- **The Mac mini's search surface** — unreachable is not a negative (`172` §5.6).

---

## 8. HOW TO REPRODUCE EVERY NUMBER HERE

```bash
A='ssh secratary-cloud'
# the badge and its producer
$A "curl -s http://127.0.0.1:3086/dsh-attention.json | head -c 400"
$A "ls -l --time-style=full-iso /root/ceo-kernel-var/latest.json; cat /root/.sentinel-freshness/status.json"

# money: memory, swap, OOM, disk
$A "systemctl status company-api --no-pager | head -12; free -m; journalctl -k --since '-24 hours' | grep -ci 'Out of memory'; df -h / | tail -1"

# the broker, and whether it can SEE the fleet (every node 'unreachable' = blind)
$A "curl -s http://127.0.0.1:3091/healthz; curl -s 'http://127.0.0.1:3091/nodes?fresh=1' | python3 -c \"import json,sys;[print(n['node'],n['state'],n.get('latencyMs')) for n in json.load(sys.stdin)['nodes']]\""

# search, and its guards
$A "/usr/local/bin/check-faindex-freshness; python3 /root/bin/tool-body-guard.py | tail -3"

# the offsite copy and the deadman
$A "grep -E '^(finished_at|status|database_verified)=' /var/lib/authority-backup/last-run; systemctl list-timers authority-* --no-pager"
$A "journalctl -u authority-deadman --since '-10 min' --no-pager | grep 'ping http'"

# the frozen anchor, read-only
ssh secratary-ts 'systemctl is-active cron secretary-api mesh-broker phone-gate; crontab -l | grep -vE "^#|^$" | wc -l'

# the documentation split (§4.1)
ls -1 docs/mesh/*.md | wc -l                                   # this laptop: 131
$A "ls -1 /root/code/harness-config/docs/mesh/*.md | wc -l"     # authority: 83
git log --oneline -1 -- docs/mesh/131-MIGRATION-BRIEF.md        # committed here, absent there

# the queue's composition (§2.7)
$A "python3 /root/bin/owner-queue.py stats"
```

**Guard rails, unchanged:** `secratary-ts` is the FROZEN rollback anchor — `131` Rule 1 says do not
start, stop, enable, disable, unmask or restart anything on it, and `scripts/mesh/guard-service-state.sh
--host secratary --op <op>` refuses for you (exit 2). `ZABZ-YOGA` has **no vault credential** and its
`origin` is the frozen box, so a push from this laptop cannot reach the canonical remote (§4.1).

---

## 9. THE ONE QUESTION

Everything in §6 is mine and needs nobody. One thing is not, it is the estate's single recurring
failure, and no engineering in `171`, `173` or this document can substitute for it:

> **The authority box holds a 7.5 GB working set in 7.7 GB of memory. It has killed its own API
> three times, it is using half its swap right now, and the kernel — not the app — chooses the victim
> because `MemoryMax=infinity`. Resize the instance to 4 vCPU / 16 GB (my recommendation; roughly
> 20–30 US dollars a month, and it removes the OOM and the swap immediately), or keep the size and
> have me cap the app and move the nightly transcript ingest off that box (free, slower, and it will
> still OOM under a migration-scale burst)?**

<!-- tags=estate-state,master-record,memory,durability,queue,mesh,search,cloud-authority refs=000,131,142,160,168,169,170,171,172,173,174,P3134,P3135,P3136,P3137,P3139,447,445,283,228 -->
