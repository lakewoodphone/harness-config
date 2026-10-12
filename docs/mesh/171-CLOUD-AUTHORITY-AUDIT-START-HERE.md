# 171 — CLOUD AUTHORITY AUDIT: START HERE

**The one page for the cloud-vs-office question.** Written 2026-10-12 04:00–04:30Z on **ZABZ-YOGA** by the session
that performed the audit. It answers, with references, three things: **what was done**, **the state of things**,
and **what to do next**. The measurements live in one document; this page is the map to everything else.

> **Owner's question, verbatim, 2026-10-12:** *"we finished the migration from the office secretary server to the
> cloud secretary server because the office secretary server was getting throttled… seriously audit now and see if
> on every single metric the Cloud Secretary is an order of magnitude faster and more robust. Did we stop… old
> journal / database problems… is every single one of those things way faster and fully fixed or not?"*

---

## 1. THE ANSWER IN FIVE LINES

1. **Three real wins, and they are the ones the migration was bought for:** the disk-starvation outage class has not
   recurred (19 h 09 m of production, zero API restarts, one boot); `database is locked` fell from **657 events in
   the office's last 10 days to 2 in 19 h**; and the 23.6 GB consistent backup now runs at **139 MB/s, verified end
   to end**, where the office's chain had two newest snapshots with no `COMPLETE` marker.
2. **Not faster on every metric.** On the same O_DIRECT harness the office box is *faster*: 3,851 MB/s write and
   578k IOPS against the cloud's 1,323 MB/s and 401k. **The cloud's win is throughput under production load and
   availability, not raw speed** — the office ran at 2–7 MB/s and lost sshd three times under its own load.
3. **One metric got worse and it is the binding constraint: memory.** Office 23,421 MB with **0 OOM kills ever**;
   cloud 7,742 MB with **3 kernel OOM kills of `company-api` on 2026-10-11**, 2,558 MB of 4,095 MB swap in use now,
   and `MemoryMax=infinity` so the *kernel* picks the victim. The app's peak is ~7.4–7.5 GB and the box is 7.7 GB.
4. **The safety net did not move, and one invariant broke.** **59 of 93** office cron jobs have no cloud
   counterpart — including **`deadman`** and the **6-hourly `company-offsite-push` restic chain** — and the
   **rollback anchor is contaminated**: the office database grew **393 MB after the freeze** and a `mesh-broker`
   process is running there that *started after* the freeze.
5. **The journal was never a server problem.** It was the old flat-file tooling (8.9 s, exit 1), rebuilt to
   one-file-per-entry *before* the migration; tonight's read is 598 ms against a 400 ms target purely because the
   repo reached 3,489 entries. Do not attribute it to the migration, in either direction.

---

## 2. WHAT WAS DONE (2026-10-12 03:15–04:30Z)

All of it read-only on both hosts, except **one** crontab line (item 4 below). Nothing was started, stopped,
enabled, disabled or restarted anywhere.

| # | action | result |
|---|---|---|
| 1 | Wrote and ran the **same** measurement harness on both boxes: `storage-bench.py` (O_DIRECT, cache-defeating write + 16 KiB/4 KiB random read), `host-metrics.sh`, `db-metrics.py` (read-only SQLite probe). Staged to `secratary-cloud:/root/audit/` and `secratary-ts:/home/zabz/audit/`. | §2 and §5 of the audit doc |
| 2 | Collected the **live** facts: CPU/RAM/swap/disk/PSI/load, `journalctl -k` OOM records, `journalctl -u company-api` lock records, `systemctl list-timers --all`, `crontab -l` on both boxes, `cron-wrap.sh` run ledgers (cloud 3,152 runs/24 h; office 96,078 runs all-time), `sar -r/-S` for the kill window | audit doc §1, §3, §5, §6 |
| 3 | Compared the **cron inventories** job by job (93 office names from `.cron-status/runs.tsv` vs 34 cloud wrapper names from `crontab -l`) | audit doc §6 — the full missing list |
| 4 | **FIXED** (the only state change anywhere): removed the redundant `*/30 … cron-wrap.sh report-offsite-age` cron line on the cloud box. It ran the office build of the script, whose default interpreter `$HOME/personal-secretary-mvp/.venv/bin/python` **does not exist there**, so it failed `no boto3` every other run and **still reported "reported to the vault"**. Crontab backed up to `/root/crontab.before-audit-20261012T04.bak`; one-line removal, diff-verified; the working `authority-report-offsite-age.timer` is now the single mechanism. Verified: **03:43:01Z run, 03:43:04Z real object reading, 03:43:06Z "reported to the vault"**. Cloud cron jobs now number 33. | audit doc §5.1 |
| 5 | Found (not fixed) a second defect: the offsite backup streams the live 24 GB database in **4 KiB pages**, spending 13 m 12 s of gzip CPU in a 23 m 43 s run (run total 1858 s) and competing with the API for the one disk every night. | audit doc §5.2 |
| 6 | Wrote the record: this page, the audit document, and five journal entries. | §8 below |

---

## 3. STATE OF THINGS — the numbers, one table

Full provenance (machine, command, UTC time) for every row is in `169-CLOUD-VS-OFFICE-AUDIT.md`, measured
2026-10-12 03:15–04:30Z.

| metric | office `secratary` (frozen anchor, idle) | cloud `secratary-cloud` (THE AUTHORITY, in production) |
|---|---|---|
| CPU / RAM | i5-4570, 4c/4t, 3.2 GHz / **23,421 MB** | EPYC-Milan, **2 vCPU** / **7,742 MB** |
| swap | 995 MB | **2,558 MB of 4,095 MB (62 %)** |
| kernel OOM kills of the API (all time) | **0** | **3 on 2026-10-11** (05:47:24Z, 07:10:45Z, 15:17:30Z), all global OOM |
| cgroup ceiling on the API | `MemoryMax=8G` | **`MemoryMax=infinity`**, `MemoryHigh=infinity` |
| disk | 467 GB, **93 % used**, consumer SATA SSD behind LUKS | 75 GB, 77 % used, QEMU/NVMe, 18 GB free |
| raw write / 4 KiB IOPS (O_DIRECT, same script) | **3,851 MB/s / 578,365** | 1,323 MB/s / 400,972 |
| 23.6 GB consistent `.backup` + verify | never reliable; 2 newest snapshots lack `COMPLETE` | **139 MB/s, sha256 verified both ends** |
| throughput under its own load | **2–7 MB/s**, sshd down 3× | ~21 MB/s source; **no outage in 19 h** |
| API restarts | **215** `secretary-api` starts in the retained month | **`NRestarts=0`**, one boot ever |
| `database is locked` events | **657** over Oct 1–11 (295, 254, 75… per day) | **2** in 19 h (21:08:47Z, 01:10:03Z) |
| live DB journal mode / freelist churn | `delete` / 13,070 free pages | **`wal`** / 652 free pages |
| scheduled jobs | **93** names | **34** (was 35 before the fix in §2.4; after the removal, 33 wrapper names) |
| cron non-zero rate | 9.1 % of 96,078 runs | **15.1 %** of 3,152 runs (24 h) |
| journal retention on the box | 1.7 GB | **102 MB / 32 h** — a diagnostic regression |
| mesh placement broker | **running** (`mesh-broker.mjs`, started **after** the freeze) | not present |
| the anchor's database | 23,691,915,264 B, mtime **2026-10-11 22:33:19Z** (cutover value: 23,622,823,936 B) | `/root/authority.db`, 24,233,500,672 B, 231 tables |

**Read the columns with the comparison rule:** the office column is an **idle** machine whose disk is 93 % full; the
cloud column was measured while it was *simultaneously* running the API, streaming a 23 GB backup and ingesting a
3.5 GB transcript tarball. An idle machine beating a busy one at a microbenchmark is not a win for the idle one.

---

## 4. WHAT IS FIXED, WHAT MOVED, WHAT BROKE

**FIXED (real, measured):** the disk-starvation outage class; the lock storm (30x); WAL on the live database;
backup verification end-to-end; continuous API uptime.

**NOT FIXED, ONLY MOVED:**
- **Concurrency pressure.** The cloud runs 34 cron jobs + a 3.5 GB daily ingest + a 31-minute nightly backup on
  **2 vCPU**; `psi io full avg10=24–34 %` at rest and load 4.9–5.4 on 2 cores. The office's constraints (one disk,
  one box doing everything) were *reproduced at smaller scale*, not removed.
- **Chronic cron failures.** Same leaders on both sides (`dialpad-recording-gap`, `cron-target-guard`,
  `guard-registry`, `ai-gateway-health`, `production-comms-freshness`), and the rate did not improve (15.1 % vs
  9.1 %).
- **Home Assistant and the office LAN** stay unreachable from Ashburn (they were private-LAN/DDNS on the office
  network); the tailnet that would fix it now exists on the authority — see `159-MESH-POST-MIGRATION.md`.

**BROKE / IS BROKEN:**
1. **Memory** (§1.3). One kernel OOM kill of the API; 62 % swap; no ceiling.
2. **The safety net.** No `deadman` in the cloud's cron; no counterpart to the office's 6-hourly
   `company-offsite-push`; no `push-dsh-sessions`, `nightly-plaid-sync`, `daily-finance-sync-cron`,
   `run-sentinel`/`sampler`, `mesh-health`, `mesh-placement-monitor`, `run-ha-*`, the `wake-*` family and the
   `cfo-*`/`owner-ask` family. The full 59-name list is in the audit doc §6.
3. **The rollback anchor is contaminated.** 393 MB of post-cutover rows; `family_chat.db-wal` written
   2026-10-12 00:00Z; `phone-gate.py`, `phone-redirector.py`, a GitHub Actions runner and a **`mesh-broker.mjs`
   started 2026-10-11 23:34:48Z** are live on the "frozen" host. Cron itself is still correctly masked. A rollback
   to this anchor now returns the cutover state **plus** divergence — the `142-ANCHOR-WRITE-NOTICE` shape,
   recurred.
4. **The authority's journal holds 32 h.** Anything older is un-diagnosable from the box.

---

## 5. WHAT TO DO NEXT — ordered, with the owner's part marked

| # | action | owner or mine | where |
|---|---|---|---|
| 1 | **Memory.** Either upgrade the instance (CCX23, 4 vCPU / 16 GB — my recommendation, ~20–30 USD/month) **or** cap the app and find its ~3 GB: single uvicorn process, `/opt/company/data/chromadb` 2.9 GB + `mem0` 1.1 GB on the same disk. **ASKED — awaiting the answer.** Until it is answered do not raise tick rate or add work to this box. | **OWNER (money)** | this page §6; audit doc §3 |
| 2 | **Re-freeze or formally retire the office anchor.** If it stays an anchor: stop the surviving processes, record exactly which rows are extra, re-take the `FROZEN` marker with `lsof <db>` = 0 as the acceptance test. If it is superseded by R2, say so in `host-posture.tsv` and stop treating it as a rollback point. | mine (needs the owner only if the anchor is being dropped) | `142-ANCHOR-WRITE-NOTICE.md`, `163-OFFICE-BOX-DEMOTION.md`, `AGENTS.md` §5 |
| 3 | **Port the safety net first, then the rest:** `deadman` + the offsite-push cadence, then the finance family, then the mesh/sentinel probes. The list is already verdict-ready in `132-CRON-INVENTORY.md` and `153-LOST-JOBS-WORKLIST.md`. | mine | audit doc §6; `153-LOST-JOBS-WORKLIST.md` |
| 4 | **Verify the two timers actually fire**: `authority-offsite-backup.timer` next **2026-10-12 05:29:33Z** (its first scheduled run; `last-run` still reads 2026-10-11 06:49:06Z from the manual run) and `authority-deadman.timer` (every 5 min). Then stream the next backup with a 1–4 MiB read buffer instead of 4 KiB pages. | mine | audit doc §5.2, §3 |
| 5 | **Give the authority a longer journal** (`SystemMaxUse` is unset → 102 MB / 32 h). One line in `/etc/systemd/journald.conf`. | mine | audit doc §7 |
| 6 | **Reconcile the installed scripts back into the repo**: `/usr/local/bin/report-offsite-age.sh`, `authority-report-offsite-age.sh`, `authority-offsite-backup.sh` (three on-box copies exist: `.new`, `.v1-20261011`) versus `scripts/mesh/`. The installed `report-offsite-age.sh` is byte-identical to the office file, so the *only* difference is the environment — record that. | mine | `scripts/mesh/authority-*` |
| 7 | **Do not re-audit the raw-speed question.** It is answered: office faster raw, cloud faster under load, cloud available. | — | `169-CLOUD-VS-OFFICE-AUDIT.md` §2, §3 |

---

## 6. THE ONE OPEN OWNER QUESTION

Reproduced verbatim for the record; it was asked once, in the conversation, with the free alternative named.

> The authority box must hold a working set of ~7.5 GB and has 7.7 GB. **Upgrade the instance to 4 vCPU / 16 GB
> (my recommendation — removes the OOM and the swap immediately, roughly 20–30 USD a month)**, or keep the size and
> instead cap the app and move the nightly transcript ingest off that box (free, slower, and it will still OOM
> under a migration-scale burst)?

This is the `owner_decision_queue`-class item from this audit. Memory is the **only** recurring thing here that
cannot be fixed by moving scripts around, and it is the difference between "robust" and "restarted by the kernel
every few hours".

---

## 7. HOW TO REPRODUCE ANY OF IT

```bash
# hosts
ssh secratary-cloud                    # 178.156.194.1, THE AUTHORITY (also the tailnet name)
ssh secratary-ts                       # office box, FROZEN ANCHOR, read-only
# the harness (already staged on both boxes)
scp .audit/host-metrics.sh .audit/storage-bench.py .audit/db-metrics.py secratary-cloud:/root/audit/
ssh secratary-cloud 'cd /root/audit && python3 storage-bench.py CLOUD --size-mb 1024 --reads 3000'
ssh secratary-cloud 'cd /root/audit && python3 db-metrics.py /root/authority.db ro CLOUD_AUTHORITY'
ssh secratary-ts    'cd /home/zabz/audit && python3 db-metrics.py /home/zabz/personal-secretary-mvp/data/secretary.db immutable OFFICE_ANCHOR'
# the readings that matter
ssh secratary-cloud 'journalctl -u company-api --since 24\ hours\ ago | grep -c "database is locked"'
ssh secratary-cloud 'journalctl -k | grep -c "Out of memory: Killed process"; free -m; cat /proc/pressure/io'
ssh secratary-cloud 'crontab -l | grep -oE "cron-wrap.sh [A-Za-z0-9_.-]+" | wc -l; systemctl list-timers --all --no-legend'
ssh secratary-ts    'stat -c "%y %s" /home/zabz/personal-secretary-mvp/data/secretary.db; systemctl is-enabled cron'
```
**Guard rails:** do not start/stop/enable/disable/restart anything on `secratary-ts` (`131` Rule 1); never run a
multi-GB rsync, recursive `du`, full-table scan or `.backup` on it; `scripts/mesh/guard-service-state.sh --host
<host> --op <op>` refuses for you. On the cloud box, `df -h /` before and after anything you write — the database
is 24 GB on a 75 GB disk.

---

## 8. REFERENCES — every document this audit touches

**The audit itself**
- **`docs/mesh/169-CLOUD-VS-OFFICE-AUDIT.md`** — the measurements, in full. Start at §0 for the verdict table.
- `docs/mesh/169`-companion raw outputs: not committed as a file; the commands are §7 above.

**The migration it audits**
- `docs/mesh/131-MIGRATION-BRIEF.md` — the cutover's shared context, the seven non-negotiable rules, and the
  owner's "orders of magnitude" success standard.
- `docs/mesh/122-CLOUD-AUTHORITY-PROVISION.md`, `126-authority-cutover-runbook.md`, `127-cutover-execution-plan.md`,
  `128-HANDOFF-complete-the-cutover.md`, `129-HANDOFF-…-freeze.md`, `130-LIVE-STATE-freeze-applied…md`
- `docs/mesh/141-MIGRATION-STATUS.md` — what the manager session had done and in flight at 06:30Z Oct 11.
- `docs/mesh/135-PARITY-AND-ROBUSTNESS.md` — the first parity audit; its §5.3 (office SSD, not spinning) and §5.2
  (the first OOM) are the two findings this audit extends.
- `docs/mesh/136-ESTATE-INVENTORY.md`, `132-CRON-INVENTORY.md` (92 jobs, verdicts), `133-OFFSITE-BACKUP.md`,
  `134-*` (archive continuity, guards, port brief), `137-140` (systemd timers, ingestion, owner channel, core+gaps),
  `133/140/142-RECOVERY-RUNBOOK.md`, `143-TRANSPORT-POLICY.md`, `152-OWNERSHIP-MAP-AND-PORT.md`,
  `153-LOST-JOBS-WORKLIST.md`, `154-MESH-BROKER-MOVE.md`.
- `docs/mesh/142-ANCHOR-WRITE-NOTICE.md` + `AGENTS.md` §5 — the rule the anchor has now broken twice, and
  `settings/machines/host-posture.tsv` + `scripts/mesh/guard-service-state.sh` (the mechanism).
- `docs/mesh/000-SYSTEMS-REGISTER.md` — the machines, what is authoritative, the eight traps. **Its agent count
  ("18") is wrong — the measured roster is 126** (`135` §1.2).

**The living problems this audit measured**
- `docs/mesh/151-VERIFY-CLOUD-AUTHORITY.md`, `155`/`165` (production-comms-freshness: a frozen heartbeat, and the
  **1.8 MB cutover stub** that must never be trusted), `156`/`157`/`159` (the Dialpad gap jobs), `160` (its
  independent verification), `161` (`cron-wrap` ERRTAL fix), `162` (mesh sync), `163` (journal id repair;
  **office-box demotion**), `166`/`167` (AI-gateway health reclassified), `168` (**attention authority**),
  `170` (**master record: badge incident and fleet audit**).

**The other two live master records — read them if your question is not mine**
- **`docs/mesh/160-MESH-STATE-AND-NEXT.md`** — what was done for the *mesh*, its state, and its next steps.
- **`docs/mesh/170-MASTER-RECORD-ATTENTION-BADGE-AND-FLEET-AUDIT.md`** — the attention/badge incident and the fleet
  audit it triggered.
- This page (`171`) is the third: **cloud authority health, performance and migration parity.**

**The journal (continuity) — my entries from this session**
- `L3740` — *"faster" is meaningless without the operation and the load; the cloud box is 3x smaller on RAM and that
  is the one metric that got worse.*
- `L3741` — *a `-shm` mtime on a frozen database is not a write; prove a frozen DB by the data file's mtime+size
  over time.*
- `L3742` — addendum: single uvicorn process, no `MemoryMax`, and the `sar` anatomy of the 15:17:30Z kill.
- `P3136` — *the authority's binding constraint is memory* (open).
- `P3137` — *the rollback anchor is contaminated* (open).
- `H3572` — handoff: CHANGED / IN FLIGHT / BROKEN / NEXT / EVIDENCE for this audit.
- Read with: `python ~/code/harness-config/journal/tools/journal.py show P3136`, `… list --kind pain --status open`.
- Note: ids `L3742-L3747`, `P3138`, `W2739`, `H3571`, `H3573`, `D3052` were written by **other concurrent
  sessions** in the same window — the tree is shared, and this audit did not author those.

**The owner's queue**
- Table `owner_decision_queue` on the authority; from anywhere else `ssh secratary-ts "python3 ~/bin/owner-queue.py next"`;
  mirror at `journal/state/owner-questions.md`. The memory question in §6 belongs there if it is still unanswered
  next session.

**Artifacts left on the boxes** (harness + backups, safe to delete when superseded):
`secratary-cloud:/root/audit/{host-metrics.sh,storage-bench.py,db-metrics.py}`,
`secratary-cloud:/root/crontab.before-audit-20261012T04.bak`,
`secratary-ts:/home/zabz/audit/{host-metrics.sh,storage-bench.py,db-metrics.py}`,
local `C:\Users\ezabz\code\.audit\`.

**Companion master record — the SEARCH subsystem, `172-MASTER-RECORD-SEARCH-SYSTEM.md`**
A concurrent session (same night, 03:05–04:10Z) audited the *search* half of this same migration and
found it **was not a win at all: it was dead on arrival.** `ps_search` — the tool the `fast-search` skill
tells every agent to use — returned `Tool search not found` to every caller, because `data/tools/` is
gitignored and **599 of 607 registered tool bodies never made the crossing**; `find-anything`, `rg` and
`ctags` were installed nowhere on the authority; and `journal.py` answered multi-word queries with a
confident false negative. All of it is fixed, guarded and clocked. **This page's "three real wins" do not
cover search, and should not be read as covering it.** Search's own state, root causes, evidence and
open items are in `172`; it is summarised here in one line because a reader of *this* page would
otherwise reasonably assume search was audited and fine.

---

## 9. WHAT THIS PAGE DOES NOT CLAIM

- It does **not** claim the cloud box is faster on raw storage — it is not (§3).
- It does **not** claim the migration was a mistake — on the two things that were killing the company (disk
  saturation, lock storms) it is a clear win (§1.1, §1.2).
- It does **not** claim the 59 missing jobs are all needed — the office-vs-autopilot overlap is real; the ones
  named as critical in §4.2 are the safety net, and the rest need the port-by-family pass in `132`/`153`.
- It does **not** explain **why** the app reaches 7.5 GB. That is the open question behind §6, and the first probe
  is: what holds the 2.9 GB chromadb / 1.1 GB mem0 at runtime, and does the API's RSS climb while idle.
