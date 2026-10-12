# 180 — THE MIGRATION PLAYBOOK AND REUSABLE RULEBOOK

**Authority cutover, 2026-10-11 05:43:36Z: `secratary` (office) → `secratary-cloud` (Hetzner, Ashburn).**
Consolidated 2026-10-12 by a mesh child running on **`zabz-tech`** (Windows), which reached the authority
over ssh as `root@secratary-cloud`. The task named `/root/code/harness-config` as if the reader were on the
box; the reader was not, and that fact is itself finding **M-01** in §6.

> **Provenance convention used throughout.**
> `[doc §section]` = a document in the estate's `docs/mesh/` or `/root/out/migration-review/`.
> `[journal ID]` = an entry in the estate's journal.
> **MEASURED-HERE** = a command this session ran; the command is given.
> **QUOTED** = a number copied verbatim out of a document, with the document named.
> Nothing in this file is asserted without one of those three.

---

## 0. HOW TO READ THIS, AND THE ONE THING TO KNOW FIRST

§1 is what actually happened, including what was improvised. §2 is every problem I could substantiate,
grouped into classes. §3 is what was deliberately left behind. **§4 is the rulebook and it is the part worth
keeping** — a numbered, imperative list a fresh session can follow without rediscovering anything. §5 is the
reverse migration. §6 is what I could not establish.

### 0.1 The source corpus is not in one place — check this before you trust any citation

`175-STATE-OF-THE-ESTATE-2026-10-12.md` §2.6 and `171` §4.1 record that `docs/mesh/` is **split across
machines**, and that 49 of the migration's documents existed on ZABZ-YOGA only. I re-measured this before
reading anything, and the split is **worse than "two copies"**:

| machine | `docs/mesh` files | holds, uniquely | how measured (MEASURED-HERE) |
|---|---|---|---|
| `zabz-yoga` (Windows laptop) | **138** | `129`, `130`, `133-OFFSITE-BACKUP`, `142-RECOVERY-RUNBOOK`, `169-CLOUD-VS-OFFICE-AUDIT`, `150`, `155`–`167` | `ssh laptop-ts` → `(Get-ChildItem C:\Users\ezabz\code\harness-config\docs\mesh -File).Count` |
| `secratary-cloud` (authority) | **84 entries incl. `preserve/`** (`171` §2.6 says 83 `.md`) | `168`, `170`, `171`, `172`, `173`, `174`, `175` | `tar -cf - -C /root/code/harness-config/docs/mesh .` → extracted file count |
| `zabz-tech` (this host) | ~110 `.md` | `134-ARCHIVE-CONTINUITY`, `134-PORT-GUARDS-BACKUP`, `137-PORT-SYSTEMD-TIMERS`, `139-PORT-OWNER-CHANNEL`, `140-PORT-CORE-AND-GAPS`, `142-ANCHOR-WRITE-NOTICE`, `143-TRANSPORT-POLICY` | `git log -- docs/mesh/140-PORT-CORE-AND-GAPS.md` → `5f48f639 … 140: port core report` |
| `secratary-cloud` `/root/out/migration-review/` | **72 files** | a **staged, unversioned** copy of `131`–`167` | `tar -cf - -C /root/out/migration-review .` → 72 files, dir mtime `2026-10-11 23:13` |

**Consequence, stated as a rule:** a reader standing on the authority, following the task's instructions
literally, **cannot open `129`, `130`, `142-RECOVERY-RUNBOOK`, `140`, `142-ANCHOR-WRITE-NOTICE`, `143` or
`169`**. Four of the documents this playbook is built from are on this host only because I mirrored them
(`Get-Tar` of yoga's and the authority's `docs/mesh` plus `/root/out/migration-review` into a scratch
directory on the session host — **read-only on every estate host; nothing outside
`/root/code/harness-config/docs/mesh/180-*.md` was written anywhere in the estate**).

### 0.2 Corrections to the record, made here

| # | the claim | what I measured | which governs |
|---|---|---|---|
| C-1 | `175` §4.1: the 49 laptop-only docs are "**in no copy that survives this laptop**" on the authority | **Most of them ARE on the authority**, at `/root/out/migration-review/` (72 files, mtime `2026-10-11 23:13Z`). They are not in `docs/mesh/` and not in git there. | Both are true of different things: `175` is right about the **clone**, wrong about the **box**. The durable defect (unversioned, unfindable by a docs/mesh reader) stands. |
| C-2 | `175` §2.6 counts three copies of the corpus | There are **four** — `zabz-tech`'s checkout carries the PORT family the authority does not. | my measurement |
| C-3 | `173` §8.8 / `171` §7.1: office cron jobs "59 of 93" | `174` §A classifies all 93; `174` carries the per-row evidence | **`174` governs** (already stated by `173` §8.8) |
| C-4 | `169` §0: "1 kernel OOM kill" | `171` §3: "**3** on 2026-10-11 (05:47:24Z, 07:10:45Z, 15:17:30Z)"; `175` §0: "**one** kernel OOM kill in the last 24 h" | `171` for the 2026-10-11 count; `175` for the trailing 24 h. Both are consistent with `169` being written earlier. |
| C-5 | `L3505`/L3612 (2026-10-11): "the working broker is on the **OFFICE** box … now `enabled` … a deliberate, documented exception to the freeze" | `154` banner, `159` §2.1, `160` §1 (2026-10-12): the authority's broker was started at **03:18Z** and made able to read; the office copy is still `active`/`enabled` and is **owner question #447** | **`159`/`160` govern** — later, and measured; `L3505`'s exception was overtaken within hours and is now the two-broker hazard. |
| C-6 | `132` §0: cloud disk "68G used, 4.4G avail, 94 %" | `136` §0: "46G used / 27G avail / 64 %" (06:22Z) | **unresolved — `136` itself says so**: "Re-measure `df -h /` immediately before starting and believe the fresh number." |
| C-7 | `132` §5b: cloud `accounting.db` is "0 bytes" | `136` §0: "16 KB stub, 2 tables"; `138` §2.4: `18,476 B` vs office `21,995,520 B` | unresolved; three different paths are being described (`/opt/company/data/accounting.db`, `/root/accounting-data/live/`, and the R2 object). |
| C-8 | `136` §0: "176 lines, **87** decoded payloads" | `132` §0: "**92 of 92**, zero failures" | unresolved; `174` §A reads the **loaded** crontab and gets 93 jobs. |

---

## 1. THE MIGRATION AS IT ACTUALLY HAPPENED

Every time below is UTC. "Planned" facts come from the runbooks; "actual" facts come from the live-state
documents, the audit documents and the journal. **The improvised parts are marked IMPROVISED.**

### 1.1 Before the cutover

| when | what happened | source |
|---|---|---|
| 2026-10-06 | the estate's **failover/promotion machinery already existed and was proven** on `lpt-survivor-01` (`company-promote.py`, `company-dns-failover.py`, `survivor-bootstrap.sh`) with five pre-flight refusals, one of which is *"the primary is NOT serving"* — the two-writer hazard | `128` §5; `000` §2.1; `129` §5 |
| 2026-10-09 ~21:50Z | `126-authority-cutover-runbook.md` written **from `zabz-tech`**, superseding `122`; it kills `122` line by line with measurements (no docker anywhere; the box has no `/home/zabz`; `systemctl stop` does not stop writes; a table-count check "would falsely halt the cutover") | `126` §0 |
| 2026-10-10 23:5xZ | CORRECTION added to `127`: the plan to build a tunnel and hand-edit DNS is **superseded** — the estate already had `company-promote.py`. *"This is the same class of mistake as the Hetzner Storage Box: proposing to build something the estate already had."* | `127` §5 |
| 2026-10-11 ~00:1xZ | `128-HANDOFF-complete-the-cutover.md` — a session ran out of context; 8 stages, 9 traps, rollback table | `128` |
| 2026-10-11 ~00:45Z | `129-HANDOFF-stages-0-2-done` — 128's §4.1 was **WRONG**: the CF token was not different, the survivor's `/opt/company/.env` was **CRLF** (254 CR bytes), so `grep … | cut -d= -f2-` produced a **41-character** token against the office's **40**. Cloudflare answered *"not found in this account"*. Fixed with `sed -i 's/\r$//'`, backup `/opt/company/.env.bak-crlf-20261011T001627Z`. **IMPROVISED.** | `129` §1, journal `L3454` (cited by `129`; **not resolvable on the authority** — see §6.2) |
| 2026-10-11 | second improvisation in `129`: `company-promote.py` moves **all four** public hostnames, and two of them (`dialer.abletelsolutions.com` → office `:8899`, `secretary-ssh.abletelsolutions.com` → office `:22`) **cannot leave the office box**. A move-all points them at a tunnel with no ingress rule and Cloudflare answers **403**. Two files were amended to take `--hostnames` + `--seed-stamp ""`. | `129` §1; `127` §4.1 |
| 2026-10-11 | third improvisation: the app on the office box was **three days ahead** of the cloud's (`ddf242a4` on branch `hk/item642…` vs `006cde5a` on `master`) and the office's deployed truth was its **working tree** (47 dirty paths). `sync-running-code.sh` rsyncs the running tree. | `129` §1 |

### 1.2 The cutover itself — 2026-10-11

| when | what happened | source |
|---|---|---|
| ~02:14Z | **self-inflicted outage.** A 14 GB / ~200k-file `data/` pre-stage ran on the still-serving office box: load **52 on 4 threads**, **77–99 % iowait**, `sshd` silent while `tailscale ping` answered, API **502 for 20 minutes**. | `130` §"WHAT WENT WRONG"; `H3406`, `P2936` |
| ~02:40Z | the **owner restarted** the office box; it came back healthy. | `130` §1 |
| 03:04Z | the company API goes dark — the freeze begins (the runbook had not budgeted the four failures below). | `130` §"THE OUTAGE" |
| 03:04Z → 04:03:33Z | **the freeze failed FOUR times**, each for a different reason, all now fixed in the executor: (1) `systemctl mask` cannot shadow a unit file already in `/etc/systemd/system` — `disable` is what works; (2) the **watchdogs restarted the services 90 s after the stop**, so all three timers **and their `.service` siblings** must be stopped; (3) **the units are not the writer set** — four free-standing jobs (`presence-runtime/sampler.py`, `store-write-check.py`, `/tmp/dialpad-harvest-*.py`, `dialpad-call-fresh.py`) kept holding the DB, spawned by a crontab of ~90 **base64** commands; **stopping cron is the actual boundary**; (4) a `sqlite3 .backup` **wedged** at 4,741,529,600 B because the backup API restarts whenever the source changes, and a new cron writer appeared every few minutes. **IMPROVISED, one diagnosis at a time.** | `130` §1 |
| 03:04Z → 05:43:36Z | **the planned 45-minute window became 2 h 40 m.** Stated plainly by the operator: *"I will report the final dark window with the exact timestamps rather than an estimate."* | `130` §"THE OUTAGE" |
| 04:03:33Z | clean re-freeze, `/home/zabz/cutover/snapshot3.log`. Freeze proof: `lsof` on the DB = **0**, `cron` masked, units stopped+disabled, timers stopped+disabled. | `130` table |
| 04:22Z | `130-LIVE-STATE-freeze-applied-snapshot-running.md` written; the consistent snapshot is ~14 GB of 23.6 GB through | `130` |
| **04:27:31Z** | **`/home/zabz/cutover/office-frozen.db` — 23,622,823,936 B. This is THE ROLLBACK ANCHOR.** | `142-ANCHOR-WRITE-NOTICE` CORRECTION; journal `L3611` |
| 04:28:35Z | the "database untouched since" instant that `131` quotes | `131` |
| **05:43:36Z** | **THE CUTOVER.** DNS switched to the cloud tunnel `3e62916c-04ac-421b-b4a4-9af0852d8024`; `api.` and `ai.abletelsolutions.com` answer 200 from `secratary-cloud`; `/root/authority.db` is the authority. The office box is **FROZEN as the rollback anchor** — cron masked, writers stopped, DB untouched. | `131` "What happened"; `settings/machines/host-posture.tsv` |
| 06:00Z | `H3408` — the cutover's live state | `131` "Key paths" |
| 06:01Z | `/root/.lpt-r2.env` lands on the authority (643 B, mode 600 root) | `173` §1.3 |
| 06:18:04Z → 06:49:06Z | the new authority offsite backup service runs, **rc 0** | `173` §1.3 |
| 06:29Z | the **accounting ledger** is moved to the authority: `/root/accounting-data/live/accounting.db`, sha256 `55a9801a…`, `integrity_check` ok, 24 tables, 8,490 transactions, 1,783 balance_snapshots; the 16 KB stub kept as `accounting.db.stub-empty-16384-20261011T062757Z.bak` | `141` |
| 06:30Z | the manager session writes `141-MIGRATION-STATUS.md`; `132` (92 jobs decoded), `136` (estate inventory), `135` (parity) are the parallel workstreams' artifacts | `141` |
| 06:40Z → 07:3xZ | **the authority's ssh stops accepting the estate's key** — `Permission denied (publickey)` from every source; `authorized_keys` is 105 bytes and was overwritten. `142-RECOVERY-RUNBOOK.md` is written **while ssh is refusing**. Recovery path: Hetzner rescue system + a **second** key in `authorized_keys`. **IMPROVISED.** | `142-RECOVERY-RUNBOOK` §0 |
| 07:30Z | the `HETZNER_API_TOKEN` on ZABZ-YOGA is found valid; server id `169556315`, ccx13, **no cloud firewall, zero snapshots** | `142-RECOVERY-RUNBOOK` §0 |
| ~15:17:30Z | **kernel OOM kills `company-api`** — `constraint=CONSTRAINT_NONE`, `task_memcg=/system.slice/company-api.service`, `anon-rss:7544976kB` (~7.19 GiB) on a **7,742 MB** box, `MemoryMax=infinity` | `151` §3; `137` §2.1; `169` §3 |
| 15:11:48Z | **`website_sync_cursor.last_synced_at` freezes** inside `/root/authority.db` — the clock the ported freshness monitor watches | `155` §1, §2 |
| 17:30:02Z | `production-comms-freshness` goes red for the first time and **never comes back** — a pure function of the freeze time + the 2.0 h threshold | `155` §2 |
| 18:51Z | commit `d143fb7a` retargets the broker's ssh default — **half-applied**: the provider row names `secratary-cloud` while `bin/mesh-run.mjs` still names `secratary-ts` | `160` §2; `000` §4 trap 9 |
| **19:04Z** | **AN AGENT UN-FREEZES THE ROLLBACK ANCHOR.** It found `cron.service` **masked**, read a masked unit as "something broke", concluded the company had been down 15 hours, and ran `systemctl unmask cron.service cron.socket`, `enable --now cron`, then started `secretary-api`, `dialpad-sms-ws`, `secretary-dashboard`, `phone-engine`, then ran a Dialpad SMS harvest and a DSH session push at that box's loopback. | `142-ANCHOR-WRITE-NOTICE`; `AGENTS.md` §5; `151` §2 |
| 19:04–20:23Z | **the damage:** `dsh_session_events` **+5,129 rows** in the agent's window against **0** for the entire preceding frozen window; 30 `dsh_sessions`; ~31 Dialpad SMS rows; cron ran 1 h 19 m 18.473 s producing **622 ledger rows across 64 jobs**. The office working copy grew **+69,091,328 B**. | `142-ANCHOR-WRITE-NOTICE`; `151` §2 |
| 20:23:26Z | re-frozen. The **frozen anchor itself is intact**: `office-frozen.db` size, mtime and inode unchanged; the writes went to the *working* copy `…/personal-secretary-mvp/data/secretary.db`. | `142-ANCHOR-WRITE-NOTICE` CORRECTION; `163-OFFICE-BOX-DEMOTION` §10 |
| ~20:35Z | `143-TRANSPORT-POLICY.md` — the authority **has no private path**; its API is reachable only through the public Cloudflare tunnel, inverting the intended LAN→tailnet→Cloudflare order | `143` |
| ~20:50Z | **RESOLVED by improvisation**: `tailscale serve --bg --https=8443 http://127.0.0.1:8002` on the authority; verified from ZABZ-TECH: HTTP 200, `ok=True`, `db_ok=True`. Measured tailnet avg **0.058 s** vs public **0.067 s**. `company-api` was not restarted (`ActiveEnterTimestamp` unchanged at `2026-10-11 15:17:41Z`). | `143` "RESOLVED" |
| 20:53:20Z | a **live `ps_mcp_server.py` stdio bridge over ssh** appears on the office box from ZABZ-TECH (PID 373763), resolving `ROOT/"data"/"secretary.db"` — the **working** copy. It writes at **22:33:19Z**. | `164` §1, §2, §6; `163-OFFICE-BOX-DEMOTION` §11 |
| 21:09Z / 21:15Z | `155` diagnoses the red comms-freshness job: *"a real fact about the wrong object"* — the website's own newest row is **1.865 s NEWER** than the local store's, while the cursor it compares against is frozen | `155` §1, §2 |
| 21:29Z | `website-comms-push` ported; its first tick at 21:39:01Z exits **rc=1** | `158` |
| ~21:35Z | `154-MESH-BROKER-MOVE.md` — the placement broker is running on the **frozen** office box; the move is staged and needs one owner decision | `154` |
| 22:30Z | `162-MESH-SYNC-WHAT-MOVED-AND-WHAT-COULD-NOT.md`: ZABZ-TECH **could not be synced** (241 untracked paths, 59 of them added upstream, **47 with the same id and different content**); the cloud is already current (its `vault` remote `0bfc69fc` == its HEAD); `origin` itself is a 16-hour-old snapshot | `162` |
| 22:40–22:50Z | `163-journal-repair-crossmachine-ids`: **47 cross-machine id collisions** repaired in two passes on ZABZ-TECH (the brief said 12); pass 2 was needed because **16 of the 47 new ids landed inside another host's reserved window** | `163-journal-repair` §3, §5, §6 |
| 22:33:19Z | last non-unit write to the office **working** copy | `164` §6 |
| 22:45–22:50Z | `164` — the last non-unit writer identified, and **four live config layers still facing the old world** (§2, class C) | `164` |
| **23:34:48Z** | **`mesh-broker.mjs` is started on the FROZEN office box** — *after* the freeze. Nobody stopped it. | `171` §3, §4.3 |
| 23:55:34Z | **the anchor gets a second home**: `scripts/mesh/anchor-to-r2.py` streams `office-frozen.db` gzip → 64 MiB multipart to R2 with **zero local copy and without ever opening the database** → `anchor/office-frozen.db.gz`, **6,282,136,085 bytes**, `source_mtime 2026-10-11T04:27:31Z`. It happened because **no machine had room for 23.6 GB** (authority ~20 GB free, vault 4.6 GB, office disk 34 GB *against the file itself*). **IMPROVISED.** | `L3505`/`L3611` |
| 23:13Z | `/root/out/migration-review/` last written — the staged, unversioned copy of the migration docs | MEASURED-HERE |

### 1.3 After the cutover — 2026-10-12 (the audit night)

| when | what happened | source |
|---|---|---|
| 00:00Z | `family_chat.db-wal` written on the frozen box | `171` §3 |
| 03:05–03:40Z | `159-MESH-POST-MIGRATION`: the authority's broker is started and **found blind** — 5/5 nodes `HTTP 403`, `/place` answering `position 1, blockedBy ["unreachable","no-free-slots"]`. Fixed by adding the authority to every node's `phone-gate-allow.txt`. Also: `lib/node-probes.js` now falls back to `/mesh/capacity`; both dispatch paths now name the authority | `159` §2; `160` §2 |
| 03:12:40Z | the office crontab — **177 lines / 26,321 B, sha256 `47f5ab72defd8238…`** — saved to `/home/zabz/cutover/crontab.frozen-20261012T031240Z` and replaced with a **banner-only crontab: 0 real job lines**; `company-outcome-monitor.timer` disabled and stopped; four node-local timers kept | `173` §2.7 |
| 03:15–04:30Z | `169` + `171`: the cloud-vs-office audit. Three real wins, one regression (memory), the safety net not moved, the anchor contaminated | `169`, `171` |
| 03:18Z | authority `mesh-broker.service` **enabled + started** | `160` §1 |
| 03:45:22Z | first live `run-sentinel` on the authority — the badge's producer had been left behind entirely | `170` §3.1 |
| 04:00–04:45Z | `170`: badge v4 (data origin is a **list**, freshest readable wins) + `sentinel-freshness-check.py` (absence monitor). Found en route: **root's crontab is a shared read-modify-write** — the new line was deleted **11 seconds** after install by another session's `crontab -l … crontab -` | `170` §2 R4, §3.1 |
| 05:00–05:40Z | `175`: the state of the estate, the 49 single-copy docs, the 276 laptop-only journal ids | `175` |
| 05:20Z | `authority-offsite-backup.timer` — the daily offsite backup, `RandomizedDelaySec=600`, `Persistent=true` | `173` §1.3; `000` §2.2 |
| 2026-10-12 | the authority publishes its own repo daily with a divergence refusal and **no force path** | `173` §2.5; `000` §2.2 |

### 1.4 The improvised parts, collected (this is the honest list)

1. `--hostnames` + `--seed-stamp ""` added to the proven promotion tooling mid-cutover (`129` §1).
2. `sync-running-code.sh` written because the office's deployed truth was its working tree, not its commit (`129` §1).
3. The freeze re-run four times, each fix derived from a measurement, not from the runbook (`130` §1).
4. The cutover executor was **rewritten between documents** (`cutover-authority.sh` in `128`, `cutover-cloud.sh` in `130`); `130` records the live one as `secratary-ts:/home/zabz/cutover-cloud.sh`.
5. `tailscale serve --https=8443` used to give the authority a private path after `143` measured that it had none.
6. `scripts/mesh/anchor-to-r2.py` written because **no host had room** for the anchor.
7. The whole Hetzner-rescue recovery of ssh access (`142-RECOVERY-RUNBOOK` §0).
8. `scripts/mesh/163-journal-repair-crossmachine-ids.py` written because `journal.py repair-ids` **cannot see** the defect class (`163` §4).
9. The crontab emptied to a banner on a frozen host (`173` §2.7) rather than a timer-level fix.
10. `phone-gate-allow.txt` edited **per node** to un-blind the broker (`159` §2.1).
11. The `ceo-kernel` sentinel installed on the authority from a git bundle, with `ck/sources.py` patched by two env overrides (`170` §3.1; `140` §A1).

---

## 2. EVERY PROBLEM, CATEGORISED

One hundred and thirty-two (132) problems. Each row: **what · how discovered · measured symptom · fix ·
verified?**

### Class A — "state moved but the reader did not" (producer/consumer split)

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| A-01 | The **attention badge's producer never moved**. `ceo-kernel`/`run-sentinel` only ever ran on the office box; the cutover moved the DB, API and dashboard and left the sentinel behind, then froze the box | the owner asking *"why does it say stale?"* (`170` §1) | `~/ceo-kernel-var/latest.json` mtime **`2026-10-11T20:20:06Z`**, `host: secratary`; the authority answered `{"read": false, "error": "…No such file or directory"}` | `run-sentinel` installed on the authority from a bundle; state seeded so the 3,007-row trend survives; scheduled every 5 min | **YES** — first run 15 s, `host secratary-cloud`, `db /root/authority.db`; ledger `2026-10-12T03:45:22Z run-sentinel 0 17` |
| A-02 | **The badge's client bundle hardcoded the old host.** `BADGE_AUTHORITY` named the office box and client bundles are served immutable for a year | reading `packages/plugin-attention-badge/lib/client.js`; `grep` for the office FQDN → **242 hits** | the office gate kept answering `/dsh-attention.json` to a laptop browser: **115,737** requests in its log | badge **v4**: the data-origin attribute is a **list**, candidates asked in order, freshest readable reading wins | **YES** — `verify-badge.js` **181/181**, `verify-badge-gate.py` **55/55** |
| A-03 | A frozen producer is a **stopped clock**, and a stopped clock is stable — so it **hides** live emergencies | comparing the frozen report to the live one | the frozen report named `config_sync` + `session_archive` HIGH (both artifacts of the stopped box); the live one named **`db_writable`** (reproducible: 4/4 write probes refused at 5 s) and `web_currency_math` | live sentinel + absence monitor | **YES** — badge `read:true, host secratary-cloud, attention: 3` |
| A-04 | The **family-chat watchdog** never moved; the office one was masked at the freeze, so the live hub spent a day with no detection | grepping the authority's crontab for a family-chat entry | the authority's crontab had **no family-chat entry at all** | ported (`family_chat_watchdog.py`), cron `*/30`, previous crontab saved | **YES** — observed firings 00:55:33Z, **01:00:01Z (a real 30-min tick)**, 01:06:03Z, 01:08:48Z all rc 0; main-DB sha256 identical |
| A-05 | The **placement broker's control plane stayed on the frozen box** while the dispatcher's default moved | `154` (measured, nothing changed) | office `mesh-broker.service` `active`/`enabled` holding `127.0.0.1:3091` (pid 105841); authority `inactive/disabled`, nothing on `:3091` | authority copy started 2026-10-12 03:18Z | **PARTIAL** — see B-01, D-01 |
| A-06 | A ported freshness monitor was **watching a clock that never moves** | `155`, from the ledger transition | cursor frozen at `15:11:48Z`; first failure `17:30:02Z`; a **pure function of freeze time + the 2.0 h threshold** | diagnosis only | **NO** (see I-06) |
| A-07 | The **accounting-ledger consumers** were reading a stub | `139` §1.9 | `owner-queue.py next` → `no such table: owner_decision_queue`; `owner-ask.py --status` → `nothing to ask` **while the queue held 160 pending / 444 total** | default changed to `/root/authority.db` | **YES** — `pending: 160`, `oldest pending: 2026-09-16T19:40` |
| A-08 | **`ps_search` was dead on arrival on the authority.** `data/tools/` is gitignored (`.gitignore:58`), so no deploy could carry the tool bodies | the owner asking for a search audit (`172` §1) | `{"ok": false, "error": "Tool search not found"}` on **every** call, every mode; `ps_comms_search` → `Tool comms_search not found`; **599 of 607** registered tools arrived with no body | bodies restored from the frozen box; engine installed; guards added | **YES** — **601 of 601** active tools have bodies; comms returns real rows from **179,608** indexed records; `journal.py check` = 0 errors |

### Class B — "a control plane that reads nothing still answers"

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| B-01 | The authority's broker was **reachable and blind**. Every node's `phone-gate.py` refuses any tailnet device not in `phone-gate-allow.txt`, and the authority was never listed | `curl /nodes?fresh=1` from the cloud | **5/5 nodes `HTTP 403 "Not signed in"`**; broker `reads 5 failures 5`; `/place` answered `node=zabz-tech position=1 tier=highest-slots blockedBy=["unreachable","no-free-slots"]` — **well-formed and blind** | authority listed in the allow-list on `zabz-tech`, `zabz-yoga-1`, `zabz-tech-linux`, with the cost and two one-line reverts written into the file | **YES** — after: `reads 20 failures 17` (the 17 are pre-fix), three nodes `ok` with slots 18/12/4, and a real placement `position=0 tier=fits … released ok` |
| B-02 | A **blind broker is worse than a missing one**: a provider asks the broker first, so a reachable-but-blind broker returns no eligible node and the dispatch dies, where an absent broker triggers direct-probe failover | `L3505`/`L3612`, measured | `install-authority-cloud.sh` refuses to leave a blind broker enabled **for exactly this reason** | the refusal was kept rather than worked around | **YES** — the installer's refusal "earned its keep" |
| B-03 | `cron-script-guard` reported a **green light** while decoding nothing | `151` §1; `L3608` | `watched=0 present=0 decoded=0 ok=True`, while measured on the authority **24 of 24** crontab lines are `cron-wrap.sh`-wrapped | fixed: search the whole token list for the wrapper and re-base on that index | **YES** — now `wrapped_cron_lines: 24, payloads_decoded: 24, cron_scripts_watched: 4, present: 4` |
| B-04 | `cron-target-guard` had the same defect: it never decoded the crontab's base64, so **~60 of its targets resolved to one always-present program** | `128` §8; `134-PORT-GUARDS` §2.3 | **247 runs, 1 non-zero**, while two crontab targets were **genuinely absent for weeks** | rewritten with recursive payload decode, `decode_stats`, and `undecoded_payloads` failing the run | **YES (self-test)** — but "never run against a real cloud crontab" (`134-PORT-GUARDS` §2.3) |
| B-05 | A guard run with its **twin's flags** writes nothing and exits 2, leaving a stale status file that reads as current | `L3609` | `cron-script-guard.py` accepts `--json`; `cron-target-guard.py` accepts `--write-status`; the wrong flag → `unrecognized arguments`, `/root/.cron-scripts/status.json` stale for hours | rule adopted: run a guard the way its **own** crontab line runs it | **YES** |
| B-06 | `lpt-deploy-drift` printed a **false green** | `151` §1 | `fetch succeeded : False` then `VERDICT: IN SYNC`, `dirty files: 126` | NOT FIXED | **YES** (the defect is measured) |
| B-07 | `report-offsite-age` **exited 0 while broken** | `151` §1 | `{"error": "no boto3: No module named 'boto3'"}` at 20:00:02Z and 20:30:01Z — the cron copy ran the **office** build whose default interpreter does not exist on the cloud | the redundant cron line was removed; the working `authority-report-offsite-age.timer` is now the single mechanism | **YES** — 03:43:01Z run, 03:43:04Z real object reading, 03:43:06Z "reported to the vault" |
| B-08 | `site-uptime-check` **always exited 0**, so the ledger could not distinguish an outage from a clean hour | `135-PORT-FRESHNESS` §3 | rc vocabulary was absent | fixed to `0 clean / 1 down / 2 fault` | **YES** — 4/4 up, ledger row `2026-10-11T06:32:33Z 0 1` |
| B-09 | An `estate-monitor` baseline **reset itself unconditionally**, so one metric could never be computed | `137` §2.1 | `age=140038s` = **38.9 hours permanently unmeasurable** | baseline advanced only on collector success | **YES** — `disk_util_pct = 56.54 %` |
| B-10 | `company-outcome-monitor` read a **hardcoded office unit**, so it fabricated a zero | `137` §2.2 | `journal_command = journalctl -u secretary-api …`; `journal_events = 0`; `undercount_factor = 0.0`, while `journalctl -u company-api` held **2,615 lines** | unit resolved at runtime by probing `systemctl cat company-api`; UNREADABLE if none | **YES** — `journal_lock_unit()` → `('company-api', …)`; `grep -c 'database is locked'` = 0 |
| B-11 | **Two of three CEO-kernel checks went permanently `unknown`** because a ported check asked systemd for the office unit name | `L3613` | `app_voice` asked for `secretary-api` on a host where the API is `company-api` | unit resolved from `ExecStart`; `unknown → info`, `unknown: 0` | **YES** |
| B-12 | `config_sync` was **blind** and then, when fixed, **sampled a concurrent subject** | `170` §3.2; `175` §4.2 | at 05:15:08Z it read `DIVERGED: local main is d3740df but vault … is 5ae9f77`; measured at 05:17:33Z: **clean**, `git rev-list --count vault/main..HEAD` = **0** | a status writer was added; the *sampling* defect (15-min cache vs instant sample) is a named fix shape, not applied | **PARTIAL** — the check is correct; "a HIGH that is usually wrong is worse than no check" (`175` §4.2) |
| B-13 | **Four of six ported monitors' alerts reach no person** — they write only to `runs.tsv` | `135-PORT-FRESHNESS` §2, §8 | `site-uptime-check-cron`, `disk-guard`, `production-comms-freshness`, `ai-gateway-health` | pain filed (`P-135-1`); NOT FIXED | **NO** |
| B-14 | `run-sentinel.sh` **always exits 0 on purpose**, so `cron-wrap`'s ledger reads identically for "senses nothing wrong" and "never ran" | `170` §2 R3, predicted by `140` §A1 the day before and it happened the next day | the ledger's only row was a manual test | `sentinel-freshness-check.py` — 20-min threshold on the newest `history.jsonl` row, **exit 2 (never 1)**, `--expect-cron` so a **lost schedule** is an absence finding | **YES** — detector proved against the real machine (`unscheduled … the schedule is GONE`, rc=2) before re-install |
| B-15 | `get_status`-style surfaces reported **health while the thing they watch is broken**: four instances, each diagnosed to a line number (`liveness` prints a constant; `db_writable` escalates on a 6-second probe while 30/30 acquires succeed at 25 s; the archive `--check` measures staleness not completeness; the API serialises all connections behind one process-wide lock) | `170` §5.1–5.4 | `liveness` printed `0.0m ago` against a true **3,059 s**; `_db_lock contended` **71 times in 30 minutes** | NONE — deliberately not patched, each needs a threshold | **YES** (diagnosed) |

### Class C — "config, paths and code still facing the old world"

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| C-01 | `bin/mesh-run.mjs` still defaulted to `secratary-ts` while the provider row already named `secratary-cloud` — **two dispatch paths, two brokers, one on a box declared inert** | `160` §1 | `profiles/web/cordis.patch.yml` retargeted at `d143fb7a` (18:51Z); `bin/mesh-run.mjs` not | both now name the authority | **YES** |
| C-02 | The **live `headless` profile — the profile every mesh subagent runs — had its linux row pointing at the frozen box** | `164` §4 | `mcp-secretary-linux` gate is `process.platform !== 'linux'` (**"am I Linux"**, not **"am I the authority"**), so on the frozen box it resolves a real file and opens the frozen local store; on the cloud it fails silently (`failOnStartupError: false`) and headless children get no `ps_*` tools | linux row retargeted to `/opt/company/.venv/bin/python` + `/opt/company/scripts/ps_mcp_server.py`; on the frozen box that now **fails closed** | **YES** — `ls -ld /opt/company` on `secratary` → *No such file or directory* |
| C-03 | The **frozen box carried its own two live profiles** naming its own store | `164` §5b (not known before this session) | `mcp-secretary`/`mcp-secretary-linux` rows in `/home/zabz/.dsh/profiles/{headless,web}/cordis.patch.yml` | both `disabled: true`, backups taken, files re-parsed as valid YAML | **YES** |
| C-04 | The frozen box's copy of the bridge **served the local store** | `164` §5c | `DB_PATH = ROOT / "data" / "secretary.db"` (hardcoded; env not consulted) | `_resolve_db_path()` with a **hard refusal** on the frozen host | **YES** — behaviour test `exit_code=78` (EX_CONFIG), `stdout_bytes=0`, stderr `REFUSED: this is the FROZEN office box and no store is declared` |
| C-05 | `ck/sources.py` **hardcodes the old authority** | `140` §A1 | `AUTHORITATIVE_DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"`, `AUTHORITATIVE_HOST = "secratary"` — *"no symlink can make the kernel report honestly"* | two-line env override (`CEO_KERNEL_DB`, `CEO_KERNEL_AUTHORITY_HOST`) on the cloud copy | **PARTIAL** — upstream change recommended |
| C-06 | **The repo still re-introduces the old world.** `profiles/web/cordis.patch.yml` lines **1515–1517** and **962–964** (`secretary-ts` + `/home/zabz/personal-secretary-mvp/…`, gated `win32`, not commented out), `profiles/web/presets.generated.patch.yml` **862–864**, `journal/presets/{zabz,yocheved}/agent.cordis.yml` **529–552 / 466–468** | `164` §7 | the source preset `presets/zabz/agent.cordis.yml` line 609 **is** correct and the live `~/.dsh/profiles/web/cordis.patch.yml` **is** correct — so the risk is specifically that **re-applying the repo's generated artifacts re-introduces `secretary-ts`** | NOT HAND-EDITED (they are generated) — fix belongs in the generator | **NO** |
| C-07 | **Two hardcoded paths broke at the cutover** in the search subsystem | `000` §2.5 trap 3; `172` R3 | the engine resolved code roots as `$HOME/personal-secretary-mvp` (the checkout is `/opt/company` on the authority) and the tool body hardcoded `/home/zabz/bin/find-anything` | both now resolve by probe with an env override | **YES** |
| C-08 | A **cutover stub** `secretary.db` sits exactly where monitors default | `135-PORT-FRESHNESS` §1 | `/opt/company/data/secretary.db` = **1,827,816 B, mtime 2026-10-11 01:18Z** vs `/root/authority.db` = **23,707,291,648 B** | every port sets its DB path explicitly in its cron line | **PARTIAL** — paths set; the stub is **not deleted** |
| C-09 | Ported gap scripts pointed at a DB **without their tables** | `138` §2.2 | `sqlite3 /opt/company/data/secretary.db ".tables"` → `Error: in prepare, no such table: dialpad_call_full` | three patched files staged (`_secretary_db()` resolver) | **NO** — nothing ported |
| C-10 | Harvest wrappers `exit 1` on an absent `REPO=` prefix | `138` §2.2(d) | `REPO="/home/zabz/personal-secretary-mvp"; cd "$REPO" \|\| { log "FATAL…"; exit 1; }` | a symlink staged, not created | **NO** |
| C-11 | `chrome/phone` bundles typeset money as LaTeX | `170` §3.2 | `web_currency_math` HIGH | **both** copies patched (the one the check names and the one `phone-engine` actually serves) | **YES** — verified over the phone URL with a fresh cookie session |
| C-12 | `AUTHORITATIVE_DB`-class hardcoding is a **class**, not an instance | `164` §7; `000` §4 trap 9 | after the cutover the provider row already named the cloud while `bin/mesh-run.mjs` named `secratary-ts` | the rule: when a default moves, grep for **every** place that names the old one and move them in the same commit | **YES** (rule adopted) |

### Class D — "two writers"

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| D-01 | **Two mesh brokers for one mesh** — two lease ledgers, so two dispatches could both fill one machine | `154` (measured); `160` §1 | authority broker started 03:18Z; office `mesh-broker.service` still `active`/`enabled` (pid 409399) | **NOT FIXED** — it is a state change on a frozen host, therefore owner question **#447** | **NO** |
| D-02 | **`store-write-check` is a second writer** against the company DB, every 5 minutes | `134-PORT-GUARDS` §2.3 | `CREATE TABLE IF NOT EXISTS _write_check_scratch`, `INSERT`, `DROP` | redirected to `/root/.store-write-check/scratch.db` — deliberately weaker; the live-store check is a **named gap** | **NO** |
| D-03 | **The agent un-froze the rollback anchor and became a second writer** | the agent itself, then `142-ANCHOR-WRITE-NOTICE` | `dsh_session_events` **+5,129** rows in 19:00–20:26Z against **0** for the whole frozen window; 30 `dsh_sessions`; ~31 Dialpad SMS; 622 cron ledger rows / 64 jobs; working copy **+69,091,328 B** | re-frozen 20:23:26Z | **YES** — no cron process; ledger frozen at 20:23:01Z; zero rows in ten minutes; frozen anchor size/mtime/inode unchanged |
| D-04 | `prune-backups`' office invocation would **delete the rollback anchor's snapshots** | `134-PORT-GUARDS` §2.2 | office budget `205 GiB` vs cloud disk `75G / 26G free / 65 %`; live DB `23,707,291,648 B` | ported with `PRUNE_MAX_TOTAL_KB=4194304`, `PRUNE_MIN_FREE_KB=12582912`, allowlist exits 3 | **PARTIAL** — deployed, **first run blocked** |
| D-05 | `disk-guard` invoked a **retention deleter** pointed at the rollback anchor | `135-PORT-FRESHNESS` §3 | inventory §5 | `DISK_GUARD_INVOKE_RETENTION` defaults to `0` | **YES** — `"invocation_allowed": false` |
| D-06 | `tmp-reaper` **does not exclude `*.lock`**; reaping one admits a second writer (ported jobs use `flock /tmp/<name>.lock`, and `flock` does not touch mtime, so an old lock is a candidate) | `137` §3 | script read | **RETIRED**; visibility ported as `tmp_used_pct` | N/A |
| D-07 | A `secretary-backup.service` in `failed` state with a **disabled** timer is "the second writer, if anyone 'fixes' the failed unit" | `132` §4 note | unit `failed`, timer `disabled` | left alone, documented | N/A |
| D-08 | `db-integrity-check` **cannot run on the cloud box** and would have been a second heavy writer | `134-PORT-GUARDS` §3.3 | `31.6 GiB required vs 25.7 GiB free → it refuses … exit 2` | `--preflight-only` added; real fix = hook it into the offsite script | **NO** — first run blocked |
| D-09 | The **never-merge rule**: the nightly `lpt-apps` job runs `restic forget` with no tag filter and would evict the company's copy | `000` §2.2 | — | rule recorded | N/A |
| D-10 | `company-offsite-push.sh` pushes the office's **frozen snapshots** into the restic repo `psm-backups/company-offsite` — a **different location** from the verified object `lpt-authority-backups/authority/secretary.db.gz`, so it would pollute the lineage rather than overwrite the restore source | `173` §8.3 (a correction of the session's own subagent) | — | impossible now that its cron line is gone | **YES** |

### Class E — "undocumented deployed artefacts"

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| E-01 | **`data/tools/` is gitignored** (`.gitignore:58`) — 599 of 607 registered tool bodies arrived with no body, and `run_tool()` answers `Tool <name> not found` from a single `if not tool_path.exists()` | `172` §0 | `{"ok": false, "error": "Tool search not found"}` on every call | bodies restored from the frozen box; `tool-body-guard.py` added | **YES** — 601/601; **the directory is STILL untracked** (`172` §5.2) |
| E-02 | **28 KB of working, sha-verified infrastructure existed only at `/usr/local/bin/` on one box** | `173` §2.8 | `authority-repo-push.sh`, `authority-offsite-backup.sh` were live and in **no repository** | committed and pushed to the vault (`486bef5..472fc1d main -> main`) | **YES** |
| E-03 | The **authority could not `git push` at all** — no credential; 15 commits sat on one NVMe | `173` §0 | — | credential installed; daily push with a divergence refusal and **no force path** | **YES** — `origin == the authority`, 0 ahead |
| E-04 | **~30 office scripts staged in `/usr/local/bin/` on the cloud with no schedule, including every human-contact and money script** | `174` top; §C | "**Largest unowned risk in this section**" | inventoried as `HAZARD-IF-UNMASKED` 13 / `MUST-NEVER-RUN-AGAIN` 27 | **YES** (inventoried) — the payload is still there |
| E-05 | Three on-box copies of one script (`report-offsite-age.sh`, `.new`, `.v1-20261011`) vs the repo's `scripts/mesh/` | `171` §5 item 6 | the installed copy is **byte-identical to the office file** — the only difference is the environment | recorded; reconcile outstanding | **NO** |
| E-06 | The **authority's own published repo has a stale `origin`**: its `origin` is `/root/hc-main.bundle`, a **bundle on its own disk**, 39 commits behind its own HEAD | `175` §4.1; `162` | `git bundle list-heads /root/hc-main.bundle` → `refs/heads/main = ee3a7e2f`, an **ancestor** of cloud HEAD; nothing regenerates the bundle | `vault` remote is the canonical one; nothing changed | **YES** |
| E-07 | **`origin` is stale for the whole mesh**: `git ls-remote origin` (the shared server) = `ee3a7e2f`, the same 16-hour-old snapshot the bundle was cut from, while `vault` = `0bfc69f` | `162` | a sync that only moves machines toward `origin` keeps pulling them onto a stale ref | reported | **YES** |
| E-08 | A second offsite mechanism the register did not name: the office pushers source **frozen office state** and their cron lines had to be removed | `000` §2.2; `173` §1.4 | `secratary-ts:~/bin/push-db-offsite.sh` → bucket `lakewood-rentals-media`; `~/bin/company-offsite-push.sh` → restic `psm-backups/company-offsite` | removed 2026-10-12; office crontab now empty | **YES** |
| E-09 | The **Hetzner API token is invalid (401)** and the value has the same sha256 on both boxes — there is no API path to the provider | `140` §B2 | `http=401 {"error":{"code":"unauthorized" …"the token you have provided is invalid"}}` | **NOT FIXED** — owner mints a Read & Write token | **YES** (diagnosed) |
| E-10 | A handoff "recorded a stale 14 GB copy at `/root/authority.db` as safe to delete" — **after the cutover that path holds the REAL database** | `131` Rule 3 | — | rule recorded: "Any instruction that says to delete it is now a company-ending instruction" | **YES** |

### Class F — "single-copy data and single-copy documents"

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| F-01 | **49 migration documents were single-copy on one laptop** — including six that govern the box they govern nothing on | `171` §4.1; `175` §4.1 | `131`'s last commit is `3d071e40`, "the migration record, complete" — committed, but in **no copy that survives the laptop**: the authority's clone, the vault, and GitHub do **not** hold them | fix shape: push from a machine with a credential, then make `config_sync` measure **content**, not HEAD equality | **NO** — see §6.1 for my own correction |
| F-02 | The **raw transcript archive** existed on the frozen box only | `134-ARCHIVE-CONTINUITY` §1a, §2 | `1,652 files, 535,727,207 bytes` | copied to `secratary-cloud:/opt/company/archive/lpt-transcripts/` | **YES** — `objects verified by content hash: ok=1652 bad=0` |
| F-03 | The **company's training data** (`/home/zabz/lpt-transcripts`, 2.6 GB) had "no live home" | `136` §1 | `MUST-MOVE`; the cloud copies of `data/*` are "**empty stubs (4 KB)**" | moved (F-02) | **YES** |
| F-04 | The **raw archive has never held one byte of Copilot chat** | `134-ARCHIVE-CONTINUITY` §1a | source `copilot-chats` **193 files / 518 MB** → archive **0 — 0 %** | **NOT FIXED** (a truncated first backfill was never resumed) | **NO** |
| F-05 | The **frozen anchor was a single copy on one consumer SSD in a 2013 desktop with no UPS and no provider snapshot** (the host is physical) | `L3505`/`L3611` | every other copy had been overwritten: R2's office-era object was replaced in place by the authority's own daily backup; **no machine had room for 23.6 GB** (authority ~20 GB free, vault 4.6 GB, office disk 34 GB **against the file itself**) | streamed gzip → 64 MiB multipart to R2 with **zero local copy and without ever opening the database** | **YES** — `anchor/office-frozen.db.gz` **6,282,136,085 B**, `source_mtime 2026-10-11T04:27:31Z`, sidecar agrees on object size. **`--verify` states plainly it does NOT prove the compressed bytes decompress to that hash** |
| F-06 | **The journal's ids mean different things on different machines.** 276 entries exist on the laptop only; 27 on the authority only; filenames on both have **identical headings and different bytes** | `175` §4.3; `171` §4.3 | laptop 3,511 entries, authority 3,262, **3,235 in common**, 276 laptop-only, 27 authority-only; the difference is partly CRLF (240 of the laptop's entries) | **NOT FIXED** — the tooling exists (`repair-ids`, `dedupe`, `import-legacy`, `163`) but the **convergence and the one-allocator decision** do not | **PARTIAL** |
| F-07 | **Every id the master records cite cannot be opened on the authority** | `175` §4.3; **re-verified by me** | MEASURED-HERE (`journal.py show <id>` on `secratary-cloud`): `L3736`, `D3050`, `P3139`, `W2739`, `H3568`, `H3571`, `L3740`, `L3748`, `L3454`, `L3509`, `L3735`, `P3136`, `P3137`, `H3407` → **all "no entry"**; `H3574` and `P2937` **do** exist | filed as pain `P2937`; NOT FIXED | **YES** (reproduced) |
| F-08 | **The cross-machine id collision was real**: `journal/alloc/bands.tsv` grants the **same range to two hosts**, and `is_reserved()` asks only *"is there a row for MY host"* | `163-journal-repair` §5 | `lessons 2126-2247` to **both** ZABZ-TECH and SECRATARY; `decisions 2325-2388` to **both** ZABZ-YOGA and ZABZ-TECH; `lessons 3351-3439` to **both** SECRATARY and ZABZ-YOGA | **NOT FIXED** — needs a merge rule for the ledger, an estate-level decision | **NO** |
| F-09 | The repair was attempted three times because the tooling cannot see the defect class: `repair-ids` reported `no id collides with different content` (**0 errors, 47 collisions**) | `163-journal-repair` §4 | `cmd_repair_ids` walks `entries/<kind>/*.md` and nothing else; **neither `repair-ids` nor `dedupe` reads a git ref** | a purpose-written driver that seeds `taken` from `git ls-tree -r origin/main` | **YES** — 47/47 archive bodies sha256-equal to the final files'; `journal.py check` exit **0, 0 errors** |
| F-10 | **Pass 2 was needed because a reservation is local, not published**: `next_writable()` mints from the **floor** of a host's own window, so a number inside another host's window is the number that host writes next | `163-journal-repair` §6 | **16 of 47** pass-1 ids sat inside another host's window (`D3047-D3056` ⊂ ZABZ-YOGA `3039-3102`; `P3023-P3025` ⊂ `3002-3065`; `W2741-W2743` ⊂ `2733-2796`) | re-allocated above the maximum `reserved_through` for the kind across **all** hosts | **PARTIAL** — the 16 chained aliases leave 16 `check` warnings by design |
| F-11 | 199 GB of local snapshots **cannot** be moved and should not be: `199 GB against a 75 GB volume is arithmetically impossible` | `136` §1 | `LEAVE` | rule recorded: "the only-copy question applies to `lpt-transcripts`, not to snapshots" | **YES** |
| F-12 | **The Yisroel Mac has never contacted the transcript archive — zero rows, ever** | `170` §4; `134-ARCHIVE-CONTINUITY` §5.1 | `ssh mac-mini-ts` → `Connection timed out`; `tailscale status` → `offline`; the archive shows **0 rows** | fix staged, needs a credential on an employee's machine | **NO** |

### Class G — "schedules that were never inventoried / silently dead clocks"

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| G-01 | **The 90-day archive-and-prune and the FTS conversion were never run**; the conversion was re-done from scratch on the frozen snapshot instead | `128` §6, §2 item 7; `126` §4 Stage 9 | conversion measured **38 minutes wall clock** and **21.4 GiB → 13.06 GiB (-39 %)** with identical fingerprints | re-convert rather than a row-level FTS delta | **YES** |
| G-02 | **The entire cron layer did not move.** `131`: "What did not move is the **entire cron layer**, and with it: the offsite backups, the freshness monitors, the external dead-man switch, the transcript archive, and every other scheduled job." | `131` "What happened"; `141` | office **92–93** jobs, cloud crontab **empty** at 06:10–06:20Z on 2026-10-11 | ported piecemeal all night | **PARTIAL** |
| G-03 | **The external dead-man switch was DOWN** — not merely unported | `133` §5 | healthchecks.io `status: down, last_ping: 2026-10-11T04:00:06Z, grace: 300` | ported to the authority | **YES** — now `status: up`, `last_ping: 06:20:06Z`, and by 2026-10-12 firing every 5 min with `ping http 200`, `offsite=ok`, `db_tables=654` |
| G-04 | **Two scheduled jobs have never run at all** | `151` §1, §6.4 | `prune-backups` **NEVER** (first due 10-12); `db-integrity-check` **NEVER** (first due 10-18) | NOT FIXED | **NO** — "unproven, not merely untested" |
| G-05 | **The non-database offsite timer had never fired** | `151` §1b | `authority-data-offsite` `LastTriggerUSec` **unset**; one *manual* success `09:44:17Z`, `3,648,714,505 B` | NOT FIXED | **NO** |
| G-06 | `report-offsite-age` **logged one `no boto3` failure at 02:30Z between two successes** | `173` §4.1 item 4 | not diagnosed | NOT FIXED | **NO** |
| G-07 | **A refresh job cannot report that it has stopped running.** The estate has shipped a silently dead search clock at least three times | `000` §2.5 trap 2 | `P2899 D2` (a repetition pattern that expired after one day); `H3376` (**21 days stale**, `NextRunTime` empty); `zabz-tech`'s `DSH search index refresh` (`LastTaskResult=1`) — all still describing themselves as "scheduled" | the freshness **guard** job, which exits non-zero | **PARTIAL** — `zabz-tech`'s index is still 27 days stale and the cause is **not established** (`172` §5.1) |
| G-08 | The **systemd timer layer was frozen differently from cron**: the freeze stopped cron but not the timers, and one timer reported a **frozen company as its outcome** | `137` §0, §1 | five timers `enabled=enabled active=active`; `company-outcome-monitor.timer` `LAST 04:07:00Z` | two ported, four retired | **YES** — `systemctl list-timers` LAST/NEXT + journald |
| G-09 | `heartbeat.sh` **orphan keeps the cron cgroup alive**, so the freeze looked complete | `137` §6.2 | `ps -o pid,etime…` → `1673 03:52:56 00:00:00 0`; **1,440 forks a day**; the log's timestamp is hardcoded from **2026-06-27** | **RETIRED** (office-side, stated not run) | N/A |
| G-10 | `fa-index` would have run **`apt-get install` as root on a 15-minute timer** | `137` §4 | consumer `fa` MISSING; `universal-ctags` MISSING | **RETIRED** | N/A |
| G-11 | `trunk-check` could only ever print `UNREACHABLE` | `137` §5 | `tailscale status` → "Logged out."; no checkout on the authority | **RETIRED** | N/A |
| G-12 | The **office crontab was edited AFTER the freeze** — one added line, `plaid-sync-catchup` (`5,35 * * * *`) | `174` preamble | the loaded crontab differs from `crontab.before` by exactly one line | crontab emptied to a banner-only file on 2026-10-12 | **YES** — 0 real job lines; 177 saved |
| G-13 | **`secretary-startup` runs `*/5` and re-launches uvicorn itself** — it is not even a systemd restart, so `systemctl stop` is defeated within 5 minutes | `126` §0; `128` §3 Stage 3 | measured crontab `*/5 … pgrep -f "uvicorn app.main" \|\| …/secretary-startup.sh` | the crontab is the boundary, not the unit | **YES** |
| G-14 | **A reservation taken on one host is local, not published** — `ensure_reservation` says so in its own output: *"reserved … LOCALLY and NOT published; run `journal.py publish` before another machine can see it"* | `163-journal-repair` §8.2 | the new windows `D3111-`, `P3130-`, `W2803-` are invisible to other machines | NOT FIXED | **NO** |
| G-15 | **Root's crontab is a shared read-modify-write** across concurrent sessions | `170` §2 R4 | the new `run-sentinel` line was deleted **11 seconds** after install by another session's `crontab -l … crontab -`; the spool mtime was `03:15:47Z`; every individual edit verified its own line | the count was re-taken; the pattern is a named root cause | **YES** |

### Class H — "the frozen anchor was not actually frozen"

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| H-01 | **Masking the units does not stop the writers** — four free-standing jobs kept holding the DB, spawned by a crontab of ~90 base64 blobs | `130` §1 | `presence-runtime/sampler.py`, `store-write-check.py`, `/tmp/dialpad-harvest-*.py`, `dialpad-call-fresh.py` | stop cron | **YES** |
| H-02 | `systemctl mask` **cannot shadow a unit file that already lives in `/etc/systemd/system`** | `130` §1; `137` §6 | `Failed to mask unit: File '…/secretary-api.service' already exists` | `disable` (or `disable --now`) | **YES** |
| H-03 | **Watchdogs restarted the services 90 s after the stop** | `130` §1 | `secretary-api` came back `ActiveState=active` with a new MainPID | stop all three timers **and their `.service` siblings** | **YES** |
| H-04 | A `.backup` **wedged** because the backup API restarts whenever the source changes and a new cron writer appeared every few minutes | `130` §1 | output stopped growing at `4,741,529,600 B` while its mtime kept advancing | stop cron first; use `rsync --partial` for the long haul, not a gzip\|ssh pipe | **YES** |
| H-05 | **A masked unit reads as "something broke" on the host that has no copy of the mission** | `142-ANCHOR-WRITE-NOTICE` root cause | the migration's six governing documents (`122`, `126`, `127`, `128`, `131`, `141`) existed **only on ZABZ-YOGA**; the machine they governed carried **none** | put the mission on the machine it governs: `secratary:/home/zabz/MISSION-READ-FIRST.md` | **PARTIAL** |
| H-06 | **A fifth writer surface the masking does not close**: a live, resident, non-unit process pointed straight at the working DB | `163-OFFICE-BOX-DEMOTION` §11 | `ps_mcp_server.py` PID 373763 started 20:53:20Z; the DB mtime moved to **22:33:19Z**, 6000 s after the process started — **recorded as correlation, not proof** | **NOT FIXED** — it is another machine's live inbound ssh session; `sudo -n kill 373763` would close it | **PARTIAL** |
| H-07 | **The anchor has been contaminated twice**, the second time by a process nobody stopped | `171` §4.3; `142-ANCHOR-WRITE-NOTICE` | 393 MB of post-cutover rows in the working copy; `family_chat.db-wal` written `2026-10-12 00:00Z`; `mesh-broker.mjs` started `2026-10-11 23:34:48Z` — **after** the freeze | re-freeze or formally retire the anchor | **NO** |
| H-08 | **Reading a WAL database changes it** — a read-only inspection **checkpoints** the WAL into the main file | `142-ANCHOR-WRITE-NOTICE` final trap; `L3610` | the working copy's **size** did not change after the re-freeze while its **mtime** moved to `20:37:47Z` and its WAL went to **0 bytes** | verify a frozen copy **logically** (row counts, a dump hash) or by hashing the file **without opening it** — never both | **YES** |

### Class I — "verification that proves the wrong thing"

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| I-01 | **Byte-count verification proves the TRANSPORT, never the CONTENT** | `128` §7 trap 7; `000` §4 trap 7 | "An interrupted backup uploads faithfully and reports OK"; `scp -r` exits 0 on a no-op and "this estate lost an hour to exactly that" | the `COMPLETE` marker, written **last** by `backup-data.sh` and **required** by both pushers | **YES** |
| I-02 | **An interrupted backup leaves a directory that looks like a backup** | `128` §7 trap 7; `000` §4 trap 8 | the office's two newest snapshots lacked `COMPLETE` | the marker | **YES** |
| I-03 | The ported offsite script streams in **4 KiB pages**, spending **13 m 12 s** of gzip CPU in a **23 m 43 s** run (1858 s total) and competing with the API for the one disk every night | `171` §2 item 5, §5 item 4 | 4 KiB SQLite page reads | NOT FIXED — recommendation is a 1–4 MiB read buffer | **NO** |
| I-04 | Output stopped growing while the mtime kept advancing — the classic "looks alive, is wedged" | `130` §1 (the `.backup` wedge); `133` P-01 | `T (stopped)`, wchan `do_signal_stop`, `PPid: 1`, `rchar: 16486447588` **identical 8 s apart**; `20,066,811,904 of 23,622,823,936 B (85 %)` | `kill -CONT` then `kill -TERM`; `trap cleanup EXIT` | **YES** — `df -h /` went `4.4 G → 27 G free` |
| I-05 | **A guard whose failure has never been seen cannot be trusted** | `000` §4 trap 6 | `cron-target-guard.py` reports `ok / 0 missing` because it never decodes the base64; ~60 of its "checked" targets are the one wrapper | see B-04 | **PARTIAL** |
| I-06 | A ported freshness check decided freshness from a **heartbeat that had stopped** while the thing it heartbeats for had not | `155` §2 | website `MAX("createdAt")` **1.865 s NEWER** than the local store; `newest_age_hours 0.01` (36 s); website rows climbing `126101 → 126113` across five ticks — **only the cursor is frozen** | diagnosis only | **NO** |
| I-07 | `155`'s own docstring shows the **mirror image**: the 2026-09-15 defect was *watching a clock that always moves*; the 2026-10-11 defect is *watching a clock that never moves* | `155` §2 | — | rule: a freshness check must be able to fail in both directions | **YES** (named) |
| I-08 | **A fast failure is not a fast path.** A timing run reported "tailnet avg 0.044 s" for a route returning **HTTP 000** | `143` trap 1 | failed connections are fast | time only **successful** calls, and say how many succeeded | **YES** |
| I-09 | `Test-NetConnection` said TCP 443 on the tailnet IP was open **and it was**, but `https://<tailnet-ip>/health` still fails: the listener presents a certificate for the FQDN | `143` trap 2 | no route for a bare tailnet IP with a foreign SNI | **test the name, not the address** | **YES** |
| I-10 | The gateway's catalogue first call after idle takes **>90 s** and was read as a false negative | `135-PORT-FRESHNESS` §3 | `attempt 1: 90.07 s, http=000`; `attempt 2: 10.24 s, http=200` | default timeout raised to 90 s | **YES** |
| I-11 | `localhost` → `::1` reported the API down while it was up | `135-PORT-FRESHNESS` §3 (`H3407` §6) | 502 through the tunnel for **40 minutes** | IPv4 pin (`http://127.0.0.1:8002/health` + `curl --ipv4`) | **YES** — all endpoints HTTP 200 |
| I-12 | `--check` on the transcript archive **passed while 19.8 GB of Copilot chats were unarchived** — it measures staleness, not completeness | `P2935`; `170` §5.3 | 43,711 objects; `zabz-tech copilot-chats 32,103 files / 18.07 GB`, `zabz-yoga 8,184 / 5.00 GB`, `zabz-tech dsh-sessions 3,727 / 4.55 GB`, `zabz-tech-linux 434 / 0.05 GB`, `secratary 1,868 / 1.28 GB` | recorded, not fixed | **NO** |
| I-13 | **`--check`'s "ok" is partial by construction** — the archive pull blamed a machine's harness-config for its own thrown-away error | `P2934`; `134-ARCHIVE-CONTINUITY` §3.3 | `is harness-config synced there?` while the actual error was `ssh: Could not resolve hostname secratary.tail93e6e6.ts.net` | the probe now carries the transport's last line | **YES** |
| I-14 | A read could **invent the archive it reads** | `134-ARCHIVE-CONTINUITY` §3.3 | `--stats` on a non-existent path → `ok: true, objects: 0, arrivals: 0` | `{"ok": false, "error": "archive database does not exist … refusing to report an empty archive as health"}`, exit 3 | **YES** |
| I-15 | A **sidecar on R2 described the previous object for ~2 minutes** | `133` P-07 | `SIDECAR_TEXT=93751b09… MATCH=NO`; landed `06:49:05` `MATCH=YES` | cheap ETag fix suggested, **not done** | **YES** (re-read) |
| I-16 | The gzip `ISIZE` field **wraps**, so a naive verification reports a wrong size | `133` P-12 | `ISIZE 2,232,455,168` = `23,707,291,648 − 5 × 2³²` | a guard already in the v3 verify | **YES** |
| I-17 | **`chmod a-w` alone is not a freeze**; **`mask` alone is not a freeze**; **`lsof` = 0 is the freeze** | `126` §2.2; `128` Stage 3 | "I stopped the unit" is not the test | `lsof` on the file, then wait a full cron period and re-check | **YES** |
| I-18 | A **half-applied retarget is more dangerous than no retarget** | `000` §4 trap 9 | the provider row named the cloud while `mesh-run.mjs` named the office box | grep for every place that names the old one, move them in one commit | **YES** |
| I-19 | **A pinned comment is not a fix** | `000` §4 trap 11 | `154` said the move was staged and needed one decision; the broker was then started **without anyone proving it could read a node** | verify the **new** path end to end before retiring the old one | **YES** |
| I-20 | `verify-badge.js` **163 → 181** tests and `verify-badge-gate.py` **55/55** after v4 — the verification was extended, not just re-run | `170` §3.1 | — | — | **YES** |

### Class J — capacity, topology and the one regression

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| J-01 | **Memory is the one metric that got worse and it is the binding constraint** | `169` §3; `171` §1.3 | office **23,421 MB / 0 OOM ever**; cloud **7,742 MB** with **3 OOM kills of the API on 2026-10-11** (05:47:24Z, 07:10:45Z, 15:17:30Z), swap **2,558 of 4,095 MB (62 %)**, and **`MemoryMax=infinity`** so the *kernel* picks the victim | **NOT APPLIED** — a drop-in (`MemoryHigh=5500M`, `MemoryMax=6800M`, `MemorySwapMax=3072M`) is staged, unstowed, and costs one restart of the public API; the alternative (CCX23, 4 vCPU/16 GB, ~20–30 USD/month) is the **owner's** | **NO** — measured: ordinary cgroup peak **4,775,997,440 B**; the fatal event **7.19 GiB of anon on a 7,742 MB box** |
| J-02 | The cloud is **not faster on raw storage** | `169` §2 | office 3,851 MB/s write / 578,365 IOPS vs cloud 1,323 MB/s / 400,972 — on the same O_DIRECT harness | do not re-audit this; it is answered | **YES** |
| J-03 | **The cloud's win is throughput under load and availability, not speed** | `169` §1.3 | 23.6 GB `.backup` + verify at **139 MB/s verified both ends** vs the office's **2–7 MB/s** under its own load; **19 h 09 m** continuous production, `NRestarts=0`, one boot ever, vs **215** `secretary-api` starts in the office's retained month | — | **YES** |
| J-04 | **The lock storm was 30× better and it held under load** | `169` §1.2 | **657** `database is locked` events Oct 1–11 (295, 254, 7, 7, 5, 13, 83, 9, 49, 26, **75**) vs **2** in 19 h; journal mode `delete` → **`wal`**; freelist churn 13,070 → **652** free pages | — | **YES** |
| J-05 | **Concurrency pressure was reproduced at smaller scale, not removed** | `171` §4 "NOT FIXED, ONLY MOVED" | 34 cron jobs + a 3.5 GB daily ingest + a 31-minute nightly backup on **2 vCPU**; `psi io full avg10=24–34 %` at rest; load 4.9–5.4 on 2 cores | — | **YES** |
| J-06 | **Chronic cron failures did not improve** | `171` §3, §4 | office **9.1 %** of 96,078 runs; cloud **15.1 %** of 3,152 runs (24 h); **the same leaders** on both sides (`dialpad-recording-gap`, `cron-target-guard`, `guard-registry`, `ai-gateway-health`, `production-comms-freshness`) | — | **YES** |
| J-07 | **The authority's journal retention is 32 h** — a diagnostic regression | `171` §3, §5 item 5 | office **1.7 GB**; cloud **102 MB / 32 h**; `SystemMaxUse` is unset | one line in `/etc/systemd/journald.conf`; NOT DONE | **NO** |
| J-08 | **One dead-but-in-roster node costs ~4 s on every cold placement** | `159` §0 M6, §5.2 | broker `/healthz` 747 / 896 ms warm against `/place` **6,768 ms** cold; `lakewooechsmini: timed out after 4000 ms (hard wall-clock deadline)` | one line in that machine's `phone-gate-allow.txt`, or remove its row; recorded as `P3134` | **NO** |
| J-09 | `lib/node-probes.js` **threw working nodes away**: it read only `/mesh/health`, which two live nodes answer `404` / `502` | `159` §2.2 | before: those nodes printed `unreachable: … HTTP 404 / HTTP 502` and were absent from the ranking | fall back to `/mesh/capacity`; the node is usable over v1 with **slots UNMEASURED** (`freeSlots` stays `null`, `position` stays 0) | **YES** — `reached: 5, unreachable: (none)`; suite `222 tests, 220 pass / 0 fail / 2 skip`, broker `72/72` |
| J-10 | **The `data/` bulk read that caused the pre-cutover outage** | `130`; `H3406`, `P2936` | load **52 on 4 threads**, **77–99 % iowait**, API **502 for 20 minutes**, sshd silent while `tailscale ping` answered | do bulk work on the idle cloud box | **YES** |
| J-11 | **The office box cannot be woken** — there is no `Wake-on:` capability at all | `126` §5 item 6; `128` §7 trap 4 | `ethtool eno1` prints Speed and Link detected and **no `Wake-on:` line**; `ethtool -s eno1 wol g` is a silent no-op | if it powers off, **someone drives to Lakewood** | **YES** |
| J-12 | `/tmp` is a **RAM tmpfs** on some hosts (12 GB on the office box; on the cloud, `3.8G`) | `126` §3; `137` §2.3 | `findmnt`/`df -h /tmp` | never stage a multi-GB file there | **YES** |
| J-13 | **Scope reduction is migration work**: the mesh audit found the *ceiling* lower, not the floor | `159` §3 | ssh round trip laptop→office avg **790 ms** vs laptop→cloud avg **810 ms**; broker `/healthz` over ssh 747 / 896 / **8,845** ms | "No claim is made that a dispatch feels faster" | **YES** |

### Class K — access, credentials, identity

| # | what | discovered by | measured symptom | fix | verified? |
|---|---|---|---|---|---|
| K-01 | **The authority stopped accepting the estate's key** mid-recovery | `142-RECOVERY-RUNBOOK` §0 | `Permission denied (publickey)` from every source; `/root/.ssh/authorized_keys` **105 bytes**, overwritten; the box is under a genuine brute-force (noted at **11,671 failed password attempts in 24 h**) | Hetzner rescue system + **a second key** installed so one file is never the only way in; add the estate to `ignoreip` | **PARTIAL** — the second key is the fix; the *cause* is undetermined (`137` §11 records that a sibling's "per-source block" diagnosis is **wrong**: the same key was refused from two independent source addresses while kex completed and this session's calls at 06:34:35, 06:36:02, 06:40:03Z succeeded) |
| K-02 | `secratary-cloud` had **no tailnet and no ssh alias on any node**; it was reachable only by public IP | `128` §3, §8; `126` §2 | `tailscale` ABSENT on the cloud box at provisioning time | joined later; `secratary-cloud` is `100.73.176.126`, active, direct | **YES** |
| K-03 | A **`TAILSCALE_AUTH_KEY` in the checkout is dead** | `134-ARCHIVE-CONTINUITY` §5.2 | `tailscale up --authkey=…` → `backend error: invalid key: API key does not exist`; `tailscale status` → "Logged out" | needs a key minted in the admin console (owner question **445**) | **NO** |
| K-04 | `zabz-tech-linux` **refused every batch for six days** — no ingest token | `134-ARCHIVE-CONTINUITY` §4.3 | `REFUSED : 100 fragment(s) not accepted by the authority — no token`; `queued: 301 session(s), 6881 new row(s), 20612 KB`; the authority had **nothing since 2026-10-05T03:30:02Z** | `.env` (600) with `DSH_SESSION_INGEST_TOKEN` | **PARTIAL** — `shipped: 301 session(s), 6881 new row(s)`; the independent row count is **unmeasured** |
| K-05 | **The vault is a nearly-full VPS with no GitHub credential** | `134-PORT-GUARDS` §2.4, §10 | `lpt-apps-01` **94 % full, 4.8 GB free**; GitHub "**no** credential on the cloud box" | pushes go to `root@2.28.33.58:/srv/git/harness-config.git`; owner asked for a deploy key | **NO** |
| K-06 | **The GitHub mirror diverges and rejects push** | `160` §1; `P2870`, `P3135` | `git push origin` exits 1 while the push that matters succeeds — **read the exit code as a failure before checking, which is the exact trap `L3748` was written about** (`175` §7.2) | known, not fixed | **NO** |
| K-07 | `lpt-apps-01` **disk at 90–96 %**, five flagged readings, and it hosts the R2 credential | `175` §5.1 item #439 | — | owner | **NO** |
| K-08 | `vault harness-config.git` **HEAD points at `refs/heads/master` (missing)** — a fresh clone checks out nothing | `P2930` (open pain) | — | owner/estate | **NO** |
| K-09 | **Windows scheduled tasks were never inventoried by any of the four scheduler documents** | my reading of `132`, `136`, `153`, `174` (`174` §A source of truth is the *Linux* crontab) | the only Windows-scheduler datum in the corpus is `zabz-tech`'s `DSH search index refresh`, `LastTaskResult=1`, and `PersonalSecretary-PushVSCodeChats`, which "reports success while shipping nothing" (`131` Key paths) | **NOT DONE** | **NO** — see §6.4 |

**Total catalogued: 132 problems** across 11 classes (A 8 · B 15 · C 12 · D 10 · E 10 · F 12 · G 15 ·
H 8 · I 20 · J 13 · K 9).

---

## 3. WHAT WAS **NOT** MIGRATED, AND WHY

Sources: `174` §A/§C (the governing classification), `136` (estate inventory), `153`, `132` §1–§5b.

### 3.1 The governing schedule classification

`174-CRON-PORT-INVENTORY.md` §A, reading the **loaded** office crontab (177 lines = 93 real jobs / 76
comments / 8 blank): **PORTED 27 · MUST-NEVER-RUN-AGAIN 27 · STILL-NEEDED-UNPORTED 24 ·
HAZARD-IF-UNMASKED 13 · DEAD 2 = 93.** `173` §8.8 and `171` §7.1 both say `174` **governs** over `171`'s
"59 of 93". ("64 are neither ported nor provably dead.")

### 3.2 The 24 `STILL-NEEDED-UNPORTED`, by `174` §C family

| family (`174` §C, verbatim heading) | members |
|---|---|
| *"company jobs whose code is already on the authority, awaiting only a schedule (4 rows)"* — "**the cheapest real work on the list**" | `lpt-recon-check`, `sync` (usearch), `audit` (four-surface), `lpt-hub-refresh` |
| *"office-LAN services the cloud cannot reach (6 rows)"* — "the blocker is the network, not credentials" | `check-security-absence`, `run-ha-truth`, `run-ha-behaviour`, `backup-phoenix-evidence`, `check-phoenix-evidence`, `sampler` |
| *"the office phone gate / DSH phone surface (5 rows)"* | `serve-phone`, `serve-phone-2`, `probe-phone`, `check-phone-ui`, `push-dsh-sessions` |
| *"office-box and office-mesh instrumentation (9 rows)"* | `heartbeat`, `box-health-check`, `engine-watch`, `model-failover-watch`, `profile-gate`, `run-sentinel`, `mesh-health`, `mesh-node-probe.sh`, `mesh-placement-monitor`, `node-agent-cron`, `git-health-check` |

`174` §C: "**Nothing was ported.**" `173` §4.1 item 1 adds the ordering rule: four of them
(`wake-fanout`, `cfo-ask`, `owner-ask`, `deadman`) "**spend money or contact a human**" and must be ported
**one family at a time with their guard decided on the authority first — never in a sweep, and never by
unmasking the office crontab**."

### 3.3 Deliberately left behind, with the reason given

**Data stores and artefacts** (`136` §1, verbatim where quoted):

| what | size | verdict | the reason given |
|---|---|---|---|
| `/home/zabz/secretary-backups` | **199 GB** | LEAVE | "199 GB against a 75 GB volume is arithmetically impossible"; the only-copy question applies to `lpt-transcripts`, not snapshots |
| `/home/zabz/lpt-transcripts` | 2.6 GB | **MUST-MOVE** → done | "the company's training data has no live home" |
| `/home/zabz/.config`, `.dsh`, `.cache`, `.npm`, `.vscode-server`, `.platformio`, `.swiftpm`, `.copilot`, `.local`, `.deployments` | — | LEAVE | "Bound to a desktop session that does not exist on the cloud box" |
| `/home/zabz/accounting-data/browser-auth/` | 5.7 GB | SHOULD-MOVE | "a partial profile set is worse than none" |
| `data/{briefings,waze-mdm,voice_recordings,voice_tts,code_snapshots,skills,tools}` | — | SHOULD-MOVE | cloud copies are "**empty stubs (4 KB)**" |
| `kyocera-escalator` | 3.2 GB | RETIRE | no caller |
| `personal-secretary-mvp/domains/finance/quickbooks-agent` | 272 MB | RETIRE | "holds **only `node_modules`, no `package.json`**" |
| worktrees/scratch (`wt-562-*`, `_mig_*`, `_hc_*`, `NUL`, `SELECT 1;`) | — | RETIRE | — |
| `/opt/company/data` (chromadb + mem0) | ~14 GB | **NOT MIGRATED OFF-BOX** | `133` §6, §8.2–3 named it "the largest remaining hole"; `chromadb` alone `2,403,770,368 B` |

**Credentials never migrated** (`136` §3; all office locations `/home/zabz/.secrets/` or `/home/zabz/.ssh/`,
mode 600 except `.dsh`): `cloudflare-api-token`, `cloudflare.env`, `escape101-twilio.env`,
`twilio-lakewood.json`, `dialpad-ui-headers.b64`, `lpt-nj-employer-access.env`,
`desk-2026-09-25-documents.env`, `bitlocker-ZABZ-TECH-C.recovery.txt`, `.git-credentials` (*"measured now:
**cloud cannot clone**"*), `id_rsa_linux_pc` (*"**measured ABSENT on cloud**"*), `id_ed25519_hetzner`,
`id_ed25519_lpt-apps`, `id_ed25519_mesh`, `ha-mesh-key`, `/home/zabz/.dsh/.credentials.yaml`
("Name recorded; contents not read"). `136` §3 also records that these — "including live API keys and
database passwords" — were **printed into a transcript**, and that "the affected keys should be rotated".

**LAN-only and machine-bound services** (`136` §4; `174` §C Family 2): `check-security-absence`,
`run-ha-truth`, `run-ha-behaviour` address `192.168.50.34`/`192.168.50.23` directly and `HA_URL` is
`http://homeassistant.local:8123` — "**a cloud job cannot watch a LAN device over a tunnel that is itself
the thing being monitored**". `174` §C: "What does not exist on the cloud at all: the office LAN itself
(Family 2), the office loopback owner API on `127.0.0.1:8002` (Family 3), and the office hardware
(Family 4)."

**Live dependencies deliberately still on the frozen box** (the honest residue):

| what | state | why it is still there |
|---|---|---|
| office `mesh-broker.service` | `active`/`enabled`, pid 409399, `127.0.0.1:3091` | stopping it is a state change on a frozen host → **owner question #447** (`160` §1, §5.1) |
| office `phone-gate.service` | active | "relays to a local engine port and was not investigated" (`173` §8.6) |
| four node-local timers (`estate-monitor`, `trunk-check`, `fa-index`, `tmp-reaper`) | kept deliberately | `173` §2.7 — only the **company duplicate** (`company-outcome-monitor`) was disabled |
| `ps_mcp_server.py` PID 373763 | resident, 22:33:19Z write | another machine's live inbound ssh session; "not one of the four writer units" (`163-OFFICE-BOX-DEMOTION` §11) |

**Jobs deliberately never enabled**, because each spends money or contacts a human (`142-RECOVERY-RUNBOOK`
§4): `sms-responder run --send`, `owner-ask --send`, `cfo-ask --send` — "**staged and none enabled**. The
estate's rule is a per-message yes in the conversation it was asked in." Also: **`lpt-report-freshness`**
(it "would report STALE forever because nothing on the cloud writes `capture_run`") and **`chip-resume`**
("it would restart the family SMS bot, which the owner did not ask for here").

**One thing that was not a migration at all**: the journal's flat-file tooling was rebuilt *before* the
cutover, and `171` §1.5 says plainly *"Do not attribute it to the migration, in either direction."*

---

## 4. THE RULEBOOK

Numbered, imperative, in the order a fresh session must run them. **Every rule names the failure that
produced it.** This is the section to copy into the next cutover's brief unchanged.

### Phase 0 — before you touch anything

**R-01. Read `docs/mesh/000-SYSTEMS-REGISTER.md` before you design anything, and assume the estate already
has the mechanism.**
*Produced by:* an agent designed a cutover before surveying and the owner paid **$51.59/month and hours of
work** before a pre-existing tool was found (`128` §0). The same mistake was made twice — the "Hetzner
Storage Box" and the hand-rolled DNS edit that `company-promote.py` already implemented (`127` §5).

**R-02. Prove the standard of success with a number, and write it into the brief.** The owner's, verbatim:
*"a better version by orders of magnitude over the office one, not missing anything or doing anything less
in any way."* (`131`.) A job ported unchanged is the **floor**.
*Produced by:* the parity audit finding that the migration was **not** faster on every metric and that the
success standard had been read as "it runs" (`169` §0).

**R-03. Enumerate every scheduler. There are at least four, and they are not the same inventory.**
(a) Linux **crontab** — and it is **base64-wrapped**, so `crontab -l` is not an inventory;
(b) **systemd timers**, which are *invisible to `crontab -l`*;
(c) **`/etc/cron.d`**;
(d) **Windows scheduled tasks**.
*Produced by:* `173` §1.3 — a session ran `crontab -l`, grepped for `offsite`, found nothing, and reported
"there is still no offsite database backup" **while three systemd timers had been running it for eight
hours**; and by `132`/`136`/`153`/`174` each producing a different count for the same box.
*Command that would have settled the fourth:* `Get-ScheduledTask | Where-Object State -ne 'Disabled'` —
**never run by any document in this corpus (see §6.4).**

**R-04. Decode the crontab before you count it, and prove the decode by round-trip.**
*Produced by:* the office crontab holds **~90 jobs whose commands are base64 blobs**; `cron-target-guard`
resolved **~60 of them to one always-present program** and reported `ok / 0 missing` for weeks while two
targets were genuinely absent (`128` §8, `134-PORT-GUARDS` §2.3).

**R-05. Reconcile the counts before you quote one, and name which document governs.**
*Produced by:* four numbers for one crontab — **92** (`132`), **93** (`174`, the loaded file), **88**
(`153`), **87** (`136`) — and by `174` §A disagreeing with its own §C.

**R-06. Write the mission onto the machine it governs.** Every host that can be reached by an agent must
carry, locally, the document that says what it is for.
*Produced by:* **the anchor incident.** The six governing documents existed only on ZABZ-YOGA; the box they
governed carried none; an agent saw a masked unit, read it as breakage, and un-froze the rollback anchor
(`AGENTS.md` §5, `142-ANCHOR-WRITE-NOTICE`). The fix is
`secratary:/home/zabz/MISSION-READ-FIRST.md` plus `AGENTS.md` §5.

### Phase 1 — the frozen anchor

**R-07. A freeze is a test that keeps passing, not a verb you perform once. The acceptance test is `lsof`
on the database file = 0, re-taken after one full cron period.**
*Produced by:* "I stopped the unit" was defeated four separate ways in one night (`130` §1).

**R-08. `systemctl mask` cannot shadow a unit file that already lives in `/etc/systemd/system`. Use
`disable` — and stop the watchdogs' `.service` siblings, not only the `.timer`.**
*Produced by:* `Failed to mask unit: File '/etc/systemd/system/secretary-api.service' already exists`;
and `secretary-api` returning `ActiveState=active` with a new MainPID **90 seconds** after being stopped
(`130` §1, `137` §6).

**R-09. The units are not the writer set. Find the writers with `lsof`, never with `systemctl`.**
*Produced by:* four free-standing jobs (`presence-runtime/sampler.py`, `store-write-check.py`,
`/tmp/dialpad-harvest-*.py`, `dialpad-call-fresh.py`) held the database after every unit was down, spawned
by the crontab (`130` §1). And by a live `ps_mcp_server.py` over ssh writing at **22:33:19Z** with no unit
involved at all (`163-OFFICE-BOX-DEMOTION` §11).

**R-10. Stopping cron is the boundary that matters, and cron must be *emptied*, not merely masked.**
*Produced by:* `L3505`'s documented exception (the broker left enabled on a frozen host) and by **nobody
stopping `mesh-broker.mjs`, which started on the frozen box at 2026-10-11 23:34:48Z, after the freeze**
(`171` §4.3). On 2026-10-12 the office crontab was finally emptied to a **banner-only file, 0 real job
lines**, with the 177-line original saved (`173` §2.7).

**R-11. Make the freeze enforceable in code, from one file, and fail closed.**
*Produced by:* the anchor incident. The mechanism that exists is
`settings/machines/host-posture.tsv` (fields `host | posture | since | decided | reason`; posture ∈
`frozen` / `read-only` / `writable`; **every alias an agent might arrive as is a row, because `secratary` is
a prefix of `secratary-cloud`**), read by `scripts/mesh/guard-service-state.sh` (exit 2 for frozen) **and**
by `packages/plugin-remote-fanout/lib/posture.js` for **placement** (frozen → refused with no override;
undesignated → refused, exit 4; **re-read on every acquisition, never cached**; strictest match wins).
(`AGENTS.md` §5; `167` §2.)

**R-12. Gate the *answer*, not the *hint*.** A soft `exclude` list is not a guarantee — an exclusion that
names every node yields.
*Produced by:* `167` §2 — the broker's `exclude` is soft by contract, so the gate must sit on the node the
broker actually **names**, release the lease unspent, and record `state: posture-refused`.

**R-13. Never verify a frozen copy by file hash, and never open it to find out.**
*Produced by:* **reading a WAL database changes it.** The working copy's size did not change while its
mtime moved and its WAL went to 0 bytes — the read-only inspections **checkpointed** it
(`142-ANCHOR-WRITE-NOTICE` final trap, `L3610`). Verify **logically** (row counts, a dump hash) or hash the
file **without opening it** — never both.

**R-14. When the anchor is a single physical copy, give it a second home before you need it — and say what
the verification does not prove.**
*Produced by:* the anchor was 23.6 GB on one consumer SSD in a 2013 desktop with **no UPS and no provider
snapshot** (a physical host), while every other copy had been overwritten and **no machine had room**
(authority ~20 GB free, vault 4.6 GB, office disk 34 GB *against the file itself*). `anchor-to-r2.py`
streamed it without ever opening the database; `--verify` states plainly that it does **not** prove the
compressed bytes decompress to the stated hash (`L3505`/`L3611`).

**R-15. Re-freeze or formally retire the anchor; do not leave it in the middle.**
*Produced by:* the anchor contaminated twice — 5,129 rows and an unstopped broker — so "a rollback returns
the cutover state **plus** divergence" (`171` §4.3, `142-ANCHOR-WRITE-NOTICE`).

### Phase 2 — the copy and the move

**R-16. A consistent snapshot is `sqlite3 .backup` or a page stream — never `cp`, and never
`sqlite3 .backup` into a FIFO.**
*Produced by:* `sqlite3 /tmp/t.db ".backup /tmp/t.fifo"` → `Error: cannot open "/tmp/t.fifo"
backup_rc=1` (`133` §3); and a `.backup` wedging because the source changed under it (`130` §1).

**R-17. Stop the writers *before* the snapshot that matters, and re-take the snapshot after a clean
freeze.** The `FROZEN` marker must be regenerated after the final snapshot — an old marker is a lie.
*Produced by:* `130`'s table: "marker written 03:52:27Z by the earlier run — **regenerate it after the clean
snapshot**".

**R-18. Measure the ship rate before you schedule the freeze, and compute the window from it.**
`126` §3: *"The unmeasured number that decides the freeze window: the office→Ashburn ship rate."* The
measurement that ended up deciding it: **2 GB off the office disk at 98 MB/s sustained** vs **500 MB office
→ Ashburn at 9.8 MB/s** — *"the disk is 10x the wire, so pulling the drive cannot make the crossing
faster"*; the owner chose the wire (`130` §1 item 4). The later measured rate was **39.7 MiB/s** (`128`
§2 item 5).

**R-19. Verify BEFORE anything points at it, on four axes, and name the one expected difference.**
`126` §2.3, §4 Stage 5, `128` Stage 5: **`integrity_check`; `page_count`; the table-list diff *with the
one expected line named*; `count(*)` and `sum(length(raw))` on the big table; and the search fingerprint
(`MATCH 'the'` hit count **and sample rowids**).**
*Produced by:* `126` §0 — an equal table count is now **impossible and would falsely halt the cutover**,
because the conversion legitimately removes exactly one table (`dsh_session_events_fts_content`).

**R-20. `page_count × page_size` must equal the file size, on both files.**
*Produced by:* `126` §5 item 4 — that is how you detect a file truncated in transit.

**R-21. Prove the write landed on the new authority by writing a canary and reading the OLD box's number
back.**
`126` §4 Stage 6b: canary on the cloud advances `max(rowid)`; the office's `max(rowid)` is **unchanged**.
*Produced by:* the same shape as the anchor incident — a write that lands on the wrong box looks like
success.

**R-22. Never two tunnel connectors for one hostname.** A second `cloudflared` while the first is up
round-robins the public name between **two SQLite files**.
*Produced by:* `126` §2.4; `128` §4 — Cloudflare answers **403, not 200**, for a hostname with no ingress
rule, which is what a partial config move produces. That is why the hostname move was reduced to
`--hostnames ai.abletelsolutions.com,api.abletelsolutions.com` (`129` §1, `130` NExT item 5).

**R-23. When a default moves, grep for EVERY place that names the old one and move them in the SAME
commit. A half-applied retarget is more dangerous than no retarget.**
*Produced by:* after the cutover the provider row named `secratary-cloud` while `bin/mesh-run.mjs` still
named `secratary-ts` — two dispatch paths, two brokers, one on a box declared inert
(`000` §4 trap 9, `160` §1).

**R-24. What must move in the same commit as the authority, without exception:**
(i) every **schema/path constant** in the deployed app (`ck/sources.py`'s `AUTHORITATIVE_DB` /
`AUTHORITATIVE_HOST`, `ps_mcp_server.py`'s `DB_PATH`) — `140` §A1, `164` §2;
(ii) **every dispatcher/placer default and roster** (`bin/mesh-run.mjs`, `lib/nodes.js`, both roster
copies) — `167` §1, `159` §2.1;
(iii) **every profile and generated preset** — `profiles/web/cordis.patch.yml`, `profiles/headless/…`,
`profiles/web/presets.generated.patch.yml`, `journal/presets/*` — `164` §4, §7;
(iv) **the cross-node allow-lists** (`phone-gate-allow.txt`) — `159` §2.1;
(v) **the search/tool install path** (`FIND_ANYTHING_BIN`, code roots) — `000` §2.5 trap 3;
(vi) **the systemd unit's `Environment=` vs `EnvironmentFile=`** — `128` §7 trap 8 (`EnvironmentFile=`
**overrides** `Environment=`, so a drop-in setting a var the file also sets is dead code).

**R-25. Do not ship the office unit verbatim. The new API binds loopback, not `0.0.0.0`.**
*Produced by:* `126` §2.5 — copying the office unit to a box with a public IPv4 publishes the company API
to the internet.

**R-26. Never write a node's absolute layout into a shared script.**
*Produced by:* two hardcodings broke at the cutover — the engine resolved code roots as
`$HOME/personal-secretary-mvp` (the checkout is `/opt/company` on the authority) and the tool body
hardcoded `/home/zabz/bin/find-anything` (`000` §2.5 trap 3).

### Phase 3 — the safety net (do this BEFORE the polish)

**R-27. Port the safety net first: the external dead-man switch, then the offsite-backup cadence, then the
freshness monitors.**
*Produced by:* the dead-man switch was **`status: down` with `last_ping 2026-10-11T04:00:06Z`** — not merely
unported (`133` §5) — and the audit's headline was *"the safety net did not move"* (`171` §1.4).

**R-28. Stream the backup on the box that holds the database, verify it end to end, and mark completeness
LAST.**
*Produced by:* the office chain had **two newest snapshots with no `COMPLETE` marker**; the cloud copy is
**139 MB/s, sha256 verified at both ends** (`169` §1.1; `128` §2 item 4). Byte-count verification proves the
**transport, never the content** (`000` §4 trap 7).

**R-29. A backup you have not restored is a hope. Restore the archive to a scratch DB and compare counts
before the first `DELETE`.**
*Produced by:* `126` §4 Stage 9c — the prune is "**the only step that can lose data permanently**", and its
RTO is **hours** from a 13 GB object.

**R-30. Never merge two restic repos; never let a `forget` with no tag filter run against the company's.**
*Produced by:* `000` §2.2 — the nightly `lpt-apps` job would evict the company's copy. And `173` §8.3 —
`company-offsite-push.sh` points at `psm-backups/company-offsite`, a **different location** from the verified
`lpt-authority-backups/authority/secretary.db.gz`, so it would pollute the lineage rather than overwrite the
restore source.

**R-31. Put the real ledger, not the stub, in the path the jobs read — and prove it by row count.**
*Produced by:* `/opt/company/data/accounting.db` was **0 bytes** (`138` §2.4) / a **16 KB stub with 2 tables
and no `transactions` table** (`136` §0), and `owner-queue.py next` answered `no such table` **while the
queue held 160 pending** (`139` §1.9).

**R-32. Move a store by MERGE, not by overwrite, when the two sides have diverged.**
*Produced by:* the family chat — office `3,156 messages / 1,134,592 B` ending `2026-10-11 02:45:22Z`, cloud
`1 / 61,440 B` with a single row dated `2026-10-11 05:41:32` — **newer than the office's newest**, so *"it is
not a copy — it is a merge"* (`140` §B3, `142-RECOVERY-RUNBOOK` §4).

**R-33. Put the mission on the machine it governs, and put the rule in the enforcement path, not in prose.**
*Produced by:* `142-ANCHOR-WRITE-NOTICE` — a rule that lives only in a document on a laptop is not a rule.

### Phase 4 — acceptance tests (run these; they are the "done" definition)

**R-34. Acceptance test 1 — the public doors answer, from the public internet, with the new box's own
response shape.** `curl -s https://api.abletelsolutions.com/health` and `…/ai…` → 200. Do **not** confuse
`api.lakewoodphoneandtech.com` (the *business* API, Caddy on `lpt-apps` → `lpt-backend:3001`) with the
company API. *Produced by:* `128` §7 trap 1 — "a wrong-host `uptime` reading sent the owner to the office."

**R-35. Acceptance test 2 — the office row count is IDENTICAL at +10 min, +1 h, +24 h, +7 d. A changed
number means a writer survived the freeze: STOP.**
*Produced by:* the 19:04Z un-freeze, which produced 5,129 rows in 79 minutes and was invisible to any check
that only asked `systemctl` (`142-ANCHOR-WRITE-NOTICE`; `126` §4 Stage 7).

**R-36. Acceptance test 3 — one writer, proved from the other side.** `sqlite3`/API read of the new box
advances; the same read of the old box does not. *Produced by:* R-21 and R-35.

**R-37. Acceptance test 4 — the safety net is demonstrably ALIVE, not merely scheduled.** The deadman must
have `ping http 200` logged in the last 10 minutes; the offsite object must be dated within 24 h with a
sha256 sidecar; the age reporter must have fired. A job that has **never run** is *unproven*, not *fine*.
*Produced by:* `prune-backups` and `db-integrity-check` **NEVER** run (`151` §1, §6.4);
`authority-data-offsite` **TIMER HAS NEVER FIRED** (`151` §1b); a **stopped** deadman (`133` §5).

**R-38. Acceptance test 5 — every ported agent-facing surface returns a REAL reading, and a refusal is not
a negative.** `ps_search` must return hits with provenance; `searched:false`/`exit 4` is a **refusal**.
*Produced by:* `ps_search` answering `Tool search not found` on the authority for a full day while agents
were told to use it (`000` §2.5); and `searched:false` being read as "(no hits)" — "the exact lie the tool
exists to prevent".

**R-39. Acceptance test 6 — count the registered tools and assert every one has a body.**
*Produced by:* **599 of 607** tool bodies arrived with no body because `data/tools/` is gitignored
(`.gitignore:58`), and `run_tool()` cannot distinguish "registered but absent" from "does not exist"
(`172` §0, `000` §2.5 trap 1). Acceptance value today: **601/601**.

**R-40. Acceptance test 7 — place a real child on a real node and require the child's `MESH-HOST` line to
name a machine other than the dispatcher.**
*Produced by:* `142-RECOVERY-RUNBOOK` §3 item 5 — "Prove it with a real dispatch, not a log line."
Observed: two children, two different nodes, `MESH-HOST` matched, exit 0 (`160` §1).

**R-41. Acceptance test 8 — every guard that reports green must be shown to be able to report red.**
*Produced by:* `cron-script-guard` at `watched=0 present=0 decoded=0 ok=True` (`151` §1);
`cron-target-guard` at `ok / 0 missing` (`000` §4 trap 6); `lpt-deploy-drift` printing
`fetch succeeded : False` then `VERDICT: IN SYNC` (`151` §1); `liveness` printing a constant against a true
3,059 s (`170` §5.1).

**R-42. Acceptance test 9 — measure the schedule, not the producer.** An absence monitor must exit non-zero
when the *schedule* disappears, not only when the data goes stale.
*Produced by:* `run-sentinel.sh` **always exits 0 on purpose**, so the ledger reads identically for "senses
nothing wrong" and "never ran" (`170` §2 R3, `140` §A1).

### Phase 5 — hygiene that stops the next incident

**R-43. Write the operation down as you go, in your own artifact file. Sessions end without warning.**
*Produced by:* `131` Rule 7; every handoff in this corpus (`128`, `129`, `141`, `142`) exists because a
session ran out of context mid-cutover.

**R-44. Classify every job you did not port, in writing, with a verdict and a reason — and let one document
govern.**
*Produced by:* four inventories producing four different counts and ~12 per-job verdict conflicts (`132` vs
`174`); `173` §8.8 and `171` §7.1 both had to designate `174` as the governing one.

**R-45. Do not enable anything that contacts a human or spends money without a per-message yes in the
conversation it was asked in.** `sms-responder run --send`, `owner-ask --send`, `cfo-ask --send` are staged
and **must stay disabled**; `tree-integrity-check` texts the owner, so its staged cron uses
`TREE_INTEGRITY_DRY_RUN=1`.
*Produced by:* `142-RECOVERY-RUNBOOK` §4; `AGENTS.md` §4; `134-PORT-GUARDS` §2.3.

**R-46. Nothing with an unbounded concurrency and no cgroup ceiling runs on the authority. Set
`MemoryHigh`/`MemoryMax`/`MemorySwapMax` before you raise the tick rate.**
*Produced by:* `MemoryMax=infinity` on a 7,742 MB box with a ~7.5 GB working set; the kernel chose the
victim and killed the company API (`169` §3, `171` §1.3, `140` §B1).

**R-47. Do the heavy work on the idle box. Never run `dbstat`, a recursive `du`, a full-table scan, a bulk
rsync or a `.backup` of the large DB on the box that is serving.**
*Produced by:* the **02:14Z outage** — load 52 on 4 threads, 77–99 % iowait, API 502 for 20 minutes, while
`tailscale ping` still answered. *"It has been done three times and broke it every time."* (`128` §7 trap 2,
`126` §0, `130`.)

**R-48. `/tmp` is a RAM tmpfs on some hosts. Never stage a multi-GB file there.**
*Produced by:* `P2892`; office box 12 GB tmpfs; cloud `3.8G tmpfs` (`128` §7 trap 3, `137` §2.3).

**R-49. `ethtool` reports the wake path; a `Wake-on` that has never been fired is not a wake path.**
*Produced by:* the office NIC prints **no `Wake-on:` line at all** — so the rollback is only as fast as a
human reaching Lakewood, and *"no human available ⇒ the rollback is fiction"* (`126` §5 item 6).

**R-50. Exit 127 from a cron job means the SCRIPT MOVED.** Check the path before believing anything about
the job's logic. *Produced by:* `128` §7 trap 6; `order-feed-refresh` and `text-line-check` are the two
`174` §A `DEAD` jobs for exactly this reason.

**R-51. A repository is not a deploy, and a commit is not a deployment unit.** `data/tools/` is gitignored;
28 KB of working infrastructure lived only in `/usr/local/bin/` on one box; the authority's own `origin` is a
stale bundle on its own disk.
*Produced by:* E-01, E-02, E-06 (`172` §5.2, `173` §2.8, `175` §4.1).

**R-52. Before you retire the old path, prove the NEW path end to end — reading one real thing.**
*Produced by:* `000` §4 trap 11 — `154` said the move was staged and needed one decision; the broker was
then started **without anyone proving it could read a node**, which is how the estate got a blind control
plane that still answered.

**R-53. Never accept "the service is active" as evidence. Make it read one real thing, and never let
"unreachable" be the answer for every target.**
*Produced by:* `000` §4 trap 10 — measured 2026-10-12: 5/5 nodes `HTTP 403`, and `/place` returned a
well-formed, blind `position 1 blockedBy ["unreachable","no-free-slots"]`.

**R-54. Close the loop on the reader: when a producer moves, its consumer and its consumer's *cached client
bundle* move with it.**
*Produced by:* the badge — the producer stayed on the office box, and the client bundle hardcoded the office
hostname with a **one-year immutable cache**, so a loaded browser asked the wrong host silently
(`170` §2 R1, R2).

**R-55. Do not confuse two hosts whose names share a prefix.** `secratary` is a prefix of `secratary-cloud`,
and confusing those two **is the whole incident**.
*Produced by:* `167` §2 — the posture file lists every alias and the strictest match wins.

---

## 5. THE REVERSE MIGRATION: `secratary-cloud` → an office machine

**The claim this section has to justify: the reverse direction is materially easier.** It is, for four
concrete reasons, and each is a measurement already in the corpus rather than an opinion:

1. **The mechanism already exists and is symmetric.** `company-dns-failover.py` has `status` / `plan --to` /
   `apply --to` / **`revert`**, and `company-promote.py` refuses unless *"the primary is NOT serving"* — the
   exact two-writer check. `revert` **restores the saved previous target and refuses if there is no saved
   state** (`128` §4, §9). A reverse move is a **promotion of the office box to a tunnel that already exists**
   — you do not invent a mechanism, you point an existing one the other way (`128` §5, `129` §5).
2. **The destination is not blank.** `secratary` still holds the pre-cutover application tree, the venv, the
   units (present and disabled), the Cloudflare credentials and the tunnel id `829bc0fb-30f9-4244-b2ea-14fbb61a2753`,
   and the **frozen anchor** `/home/zabz/cutover/office-frozen.db` (`142-ANCHOR-WRITE-NOTICE`;
   `163-OFFICE-BOX-DEMOTION` §12).
3. **The transfer is one-way and small.** The authority's live database was **24,233,500,672 B** and the
   anchor **23,622,823,936 B** (`171` §3) — so the *delta* is a few hundred MB, not a 23.6 GB re-ship. Ship
   it **cloud → office** over the tailnet, where `secratary-cloud` is `100.73.176.126` and the private path
   `:8443` is proven (`143` RESOLVED).
4. **The rules are already written and already enforced.** `host-posture.tsv` needs **one row changed**, and
   `guard-service-state.sh` + `lib/posture.js` will then refuse the wrong host for you (`167` §2).

### 5.1 What is genuinely different in this direction — the four real asymmetries

| # | asymmetry | what it changes |
|---|---|---|
| **A1** | **The destination is a physical box with no provider console.** There is **no `Wake-on:` capability at all**, and `lpt-survivor-01` (the Hetzner standby) is a *different machine* (`126` §5 item 6; `L3611`). | **This is the single biggest difference.** A cloud box can be rescued out-of-band; this one cannot. **A resident human who can physically power-cycle the box is a hard precondition**, and the cutover window must be scheduled around them. Budget a Lakewood drive. |
| **A2** | **The destination is LAN-only for half its consumers.** `HA_URL` is `http://homeassistant.local:8123`; three jobs address `192.168.50.34`/`192.168.50.23` directly; `dialer.` and `secretary-ssh.` backends live there (`136` §4, `174` §C Family 2, `128` §4). | This is a **feature** in this direction: the six office-LAN jobs in `174` §C Family 2 become placeable again, and `143`'s rule applies — **LAN is fastest, and `LAN cannot ever apply` to the cloud box** (`143`). The *public* doors must therefore still go through Cloudflare; the office box has no private path *from off-site* except the tailnet. |
| **A3** | **The disk is the binding constraint in the opposite direction.** Office: **467 GB, 93 % used, 35 GB free**; cloud: **75 GB, 77 % used, 18 GB free** (`169` §1.1; `171` §3). | A 24 GB database arriving at a box with ~35 GB free **and** `/home/zabz/secretary-backups` at **199 GB** on the same filesystem (`136` §1) is not obviously possible. **Decide what leaves the office disk *before* the reverse migration starts**, not during. This is the one place the reverse direction is *harder*, and it is a scheduling problem, not a mechanism problem. |
| **A4** | **A resident human who can unplug things, and who is the owner.** | Two consequences: (i) the rollback is **a plug and a boot**, which is faster than any scripted revert — but only if someone is on site; (ii) the office box is a place where sessions *sit down*, so the "put the mission on the machine" rule (`R-06`) matters more, not less — the anchor incident happened on this exact box. |

### 5.2 The reverse runbook

**Step 0 — decide, in writing, and record who decided.** Reverse migration is a **promotion**, not a
failover; write the reason into `settings/machines/host-posture.tsv` (`decided` field) **before** any command.

**Step 1 — pre-flight, read-only, exactly as `128` Stages 0–3, in reverse.**
```bash
# the SOURCE (the authority) is healthy and is the only writer
ssh secratary-cloud 'hostname; uptime; systemctl is-active company-api; \
  sqlite3 /root/authority.db "PRAGMA integrity_check; SELECT max(rowid) FROM dsh_session_events;"'
# the DESTINATION is reachable, has room, and has a human
ssh secratary-ts 'hostname; uptime; df -h / | tail -1; free -m | head -2; \
  ls -la /home/zabz/cutover/office-frozen.db; systemctl is-enabled cron secretary-api'
# the mechanism, dry
ssh survivor 'cd /opt/company/deploy/hosting-migration/scripts && python3 company-dns-failover.py status'
```
**SUCCESS:** the source answers on loopback **and** on the public name; the destination has ≥ **2× the
database size** free after the incoming copy is counted (`126` §5 item 7); `office-frozen.db` is present
with **size + mtime + inode** recorded (do **not** hash it and do **not** open it — `R-13`); the human is
named and on site. **If the destination's disk cannot hold the database plus the existing 199 GB of
snapshots, STOP and prune the destination first** (asymmetry A3).

**Step 2 — freeze the SOURCE.**
```bash
ssh secratary-cloud 'crontab -l > /root/cutover/crontab.before-reverse; \
  systemctl stop mesh-broker; systemctl disable mesh-broker'          # see step 8 for the broker
ssh secratary-cloud 'systemctl stop company-api secretary-dashboard phone-redirector'
# THE TEST — not the exit code, the file
ssh secratary-cloud 'lsof -nP /root/authority.db | wc -l'
sleep 360 && ssh secratary-cloud 'lsof -nP /root/authority.db | wc -l'
```
**SUCCESS = 0 twice, 6 minutes apart** (`R-07`, `R-08`, `R-09`, `R-10`). The authority's writer set is
**smaller** than the office's was — `company-api` plus the cron layer — but do **not** assume: take it from
`lsof`, exactly as `128` Stage 3 says. **Also stop the authority's `mesh-broker` and empty its crontab**
(step 8), or you reproduce the office box's mistake in the other direction.

**Step 3 — the consistent snapshot, on the SOURCE.**
```bash
ssh secratary-cloud 'sqlite3 -cmd ".timeout 60000" /root/authority.db ".backup /root/cutover/reverse.db"'
ssh secratary-cloud 'sqlite3 /root/cutover/reverse.db "PRAGMA integrity_check; PRAGMA page_count; \
  SELECT count(*) FROM dsh_session_events; SELECT sum(length(raw)) FROM dsh_session_events; \
  SELECT count(*) FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH (char(39)||char(116)||char(104)||char(101)||char(39));"'
```

**Step 4 — ship it cloud → office, over the tailnet, with `rsync --partial`.** The direction is now
`secratary-cloud` → `secratary`, both on the tailnet (`143` RESOLVED), so this is a **private** transfer and
does not touch Cloudflare.
```bash
ssh secratary-ts 'rsync -a --partial --info=progress2 --rsh=ssh \
  root@secratary-cloud:/root/cutover/reverse.db /home/zabz/cutover/reverse-incoming.db'
```
**Note the asymmetry that helps you:** the office box has **no `Wake-on`**, so this transfer must not be so
long that a power blip matters. The delta is small (§5 reason 3), so it will not be.

**Step 5 — verify BEFORE anything points at it** — the same four axes as `R-19`, run on both files, plus
the `page_count × page_size = file size` identity (`R-20`).

**Step 6 — install and start, on the DESTINATION, loopback-first.**
```bash
ssh secratary-ts 'mv /home/zabz/cutover/reverse-incoming.db /home/zabz/personal-secretary-mvp/data/secretary.db'
ssh secratary-ts 'systemctl start secretary-api && sleep 20 && curl -s -m 10 http://127.0.0.1:8002/health'
```
**The destination's `secratary-api.service` was masked by `mask`, which replaced a real unit file** — so
`unmask` alone is NOT enough; the unit file itself must come back. `163-OFFICE-BOX-DEMOTION` §12 gives the
exact four `mv` commands from the saved `.before-anchor-demotion-20261011T223320Z` copies **and** the
`daemon-reload`. **Run that restore BEFORE step 6, not after.**

**Step 7 — switch the names through the existing tool, never by hand.**
```bash
ssh survivor 'cd /opt/company/deploy/hosting-migration/scripts && \
  python3 company-promote.py --to 829bc0fb-30f9-4244-b2ea-14fbb61a2753 --apply'
```
It refuses if the primary is still serving — which is exactly why step 2 must have passed. **Restrict the
hostnames** to the two that actually move (`--hostnames`), as `129` §1 established: `dialer.` and
`secretary-ssh.` never left, so in the reverse direction they must **not** be re-pointed at a tunnel whose
ingress rules do not include them.

**Step 8 — the two things the forward migration got wrong; do not repeat them.**
* The **broker**: stop the authority's `mesh-broker` **and** re-enable the office one, in the same change,
  and prove the live one can read a node before you call the move done (`R-52`, `R-53`, `#447`).
* The **config layers**: `grep -rn 'secratary-cloud'` across every profile, preset, roster, `nodes.js` row,
  allow-list and script, and move them **in one commit** (`R-23`, `R-24`). The evidence that this is the
  real risk: four live config layers were still facing the *old* world days after the forward cutover
  (`164` §4, §5b, §7).

**Step 9 — acceptance, unchanged.** `R-34` through `R-42`. **In this direction the +10 min / +1 h / +24 h /
+7 d row-count check runs against `secratary-cloud`**, and the number that must not move is the **cloud's**.

**Step 10 — do not delete the cloud box.** It becomes the rollback anchor, and the same rule applies: for a
week, frozen, never deleted, with its own anchor given a second home (`R-14`).

### 5.3 What is materially easier, stated as a checklist a fresh session can rely on

1. The **mechanism** (`company-promote.py` / `company-dns-failover.py`) reverses without modification.
2. The **destination is not blank**: tree, venv, units, Cloudflare credentials and tunnel id are all still
   there; `163-OFFICE-BOX-DEMOTION` §12 has the exact reverse command for every change made to it.
3. The **private path now exists** (`tailscale serve --https=8443`), so the transfer does not need the public
   internet (`143`).
4. The **corpus of rules exists** — this document. The forward migration **discovered** all 55 rules above the
   hard way, across roughly 36 hours and the 132 catalogued problems in §2.
5. The **enforcement exists**: change one row in `host-posture.tsv` and both the service guard and the
   placement gate flip for you (`167` §2).
6. The **rollback is a plug and a boot**, if a human is on site (asymmetry A4) — versus the forward
   direction, where the rollback was 2–5 minutes of commands plus *however long a human needs to reach
   Lakewood* (`126` §3).

**And the one thing that is not easier: the disk** (asymmetry A3). Resolve it before step 1, not during.

---

## 6. HONEST GAPS

Everything I could not establish from the documents, and **the command that would settle it**.

### 6.1 The corpus itself

| # | gap | the command that settles it |
|---|---|---|
| GAP-01 | **`175` §4.1's "single-copy" claim is wrong about the box and right about the clone.** I found most of the 49 at `/root/out/migration-review/` (72 files, mtime `2026-10-11 23:13Z`), unversioned. **I did not establish whether that directory is on any other machine, or what created it.** | `ssh secratary-cloud 'ls -la /root/out/migration-review \| wc -l; stat -c "%y" /root/out/migration-review'` and the same on `zabz-yoga` and `zabz-tech` |
| GAP-02 | **I did not reconcile which of the task's 26 named documents are genuinely absent everywhere.** `129`, `130`, `142-RECOVERY-RUNBOOK` and `169` were reachable **only** on `zabz-yoga` (and `169` also nowhere else). | `for h in <all hosts>; do ssh $h "ls docs/mesh/<n>*"; done` |
| GAP-03 | **The frozen office box's `docs/mesh/` was never listed by me.** `171` §2.6 says it "holds the migration set, which is *why* an agent un-broke the freeze" — I did not verify that, because Rule 1 and `host-posture.tsv` say read-only and I chose not to contact it at all. | `ssh secratary-ts 'ls -1 /home/zabz/code/harness-config/docs/mesh/*.md \| wc -l'` (a single bounded `ls`; still a decision, not an oversight) |
| GAP-04 | **I could not read `173` or `174` from `zabz-yoga`** (they are not in its 138), nor `134`/`137`/`139`/`140`/`142-ANCHOR-WRITE-NOTICE`/`143` from the authority. Every cross-machine citation in this file therefore rests on a **mirror**, not the original. | `git ls-tree -r origin/main --name-only \| grep docs/mesh` on a machine with a current `origin` |

### 6.2 The journal

| # | gap | the command that settles it |
|---|---|---|
| GAP-05 | **14 of the ids I tested do not resolve on the authority.** MEASURED-HERE: `journal.py show` on `secratary-cloud` returned *"no entry"* for `L3736, D3050, P3139, W2739, H3568, H3571, L3740, L3748, L3454, L3509, L3735, P3136, P3137, H3407`; `H3574` and `P2937` **do** exist. **I did not establish whether those 14 exist on `zabz-yoga` under different ids, or at all.** | `ssh laptop-ts 'python journal/tools/journal.py show <id>'` for each, plus `journal.py pairs` |
| GAP-06 | **I did not count the two id spaces.** `175` §4.3 measured laptop 3,511 / authority 3,262 / 3,235 common / 276 + 27 unique; I re-measured none of it. | `journal.py stats` on both, and a filename-set diff |
| GAP-07 | **`P2937` (the two-namespace pain) is open and I did not read its body**, only that it exists. | `ssh secratary-cloud 'python3 journal/tools/journal.py show P2937'` |
| GAP-08 | **I did not read the journal tree beyond bounded searches**, per the brief. Everything journal-sourced here is either quoted from a document or one of the ~30 ids I probed directly. | `journal.py search "<topic>" --kind lessons --since 2026-10-01` per topic |

### 6.3 Facts the documents themselves label unverified

| # | gap | the command that settles it |
|---|---|---|
| GAP-09 | **Why the application reaches ~7.5 GB is not established by anyone.** `171` §9: *"the first probe is: what holds the 2.9 GB chromadb / 1.1 GB mem0 at runtime, and does the API's RSS climb while idle."* | `ssh secratary-cloud 'systemctl status company-api; cat /proc/$(systemctl show -p MainPID --value company-api)/smaps_rollup'` over an hour, idle |
| GAP-10 | **Whether the KB `175` cites as "the 276 laptop-only entries" includes the ones master records cite** — she tested five; I tested fourteen; **neither of us enumerated all 276**. | the diff of `journal/entries/**` filenames between the two hosts |
| GAP-11 | **The office→Ashburn ship rate was unmeasured when the window was set** (`126` §6 item 1); later measured at 39.7 MiB/s (`128`). **Not re-measured by me.** | `ssh secratary-ts 'head -c 1073741824 /dev/zero \| ssh secratary-cloud "cat >/dev/null"'`, timed |
| GAP-12 | **The DB growth rate and whether it is a runaway writer** — `126` §6 item 2 calls `0.70 MB/min` *"arithmetic on two of my own readings ≈113 min apart, one day"*, and `db-growth.mjs` **does not exist**. | `stat -c %s` on the authority's DB twice, 60 min apart, plus the write-path p99 |
| GAP-13 | **The identity of the transient third PID (213082)** that `lsof` showed holding the office DB (`126` §6 item 9). | not settleable now — the process is gone; `sudo lsof` at the time was the only window |
| GAP-14 | **The cause of the ssh lockout is undetermined.** `137` §11 states plainly that *"a sibling report's 'per-source block' diagnosis is wrong"* — the same key was refused from two independent source addresses while kex completed, and this session's calls at `06:34:35`, `06:36:02`, `06:40:03Z` succeeded. `140` §1 saw a transient `Not allowed at this time` (`PerSourcePenalties`) that cleared. | `sshd -T \| grep -i persource` plus `journalctl -u ssh` for the window |
| GAP-15 | **Whether the 4 KiB-page offsite stream was ever changed to a 1–4 MiB buffer.** `171` §5 item 4 lists it as next; no later document reports it done. | `grep -n 'chunk\|read(' /usr/local/bin/authority-offsite-backup.sh` |

### 6.4 The gap that matters most for a **future** migration, and that no document closes

| # | gap | the command that settles it |
|---|---|---|
| GAP-16 | **No document inventories the Windows scheduled tasks.** All four scheduler documents (`132`, `136`, `153`, `174`) read a **Linux crontab**; `132` §0 counts office timers; **none** lists `schtasks`. The corpus's only Windows-scheduler data are two incidental mentions: `zabz-tech`'s `DSH search index refresh` with `LastTaskResult=1` (`172` §5.1) and `PersonalSecretary-PushVSCodeChats`, which *"reports success while shipping nothing"* (`131` Key paths). **This estate's own fleet is half Windows.** | On every Windows node: `Get-ScheduledTask \| Where-Object State -ne 'Disabled' \| Select TaskPath,TaskName,State` and `Get-ScheduledTaskInfo \| Select TaskName,LastRunTime,LastTaskResult,NextRunTime` |

### 6.5 My own limitations, stated

* I **ran nothing that changed state on any estate host.** Every command I issued was `ls`, `cat`, `grep`,
  `journal.py show/list/search`, `hostname`, `tar -cf -` (to stdout) or `git log`/`git remote -v`. I created
  no file on any estate host except the one this document is.
* I **did not contact the frozen office box at all**, on purpose (`host-posture.tsv`: `secratary|frozen`,
  `131` Rule 1).
* I **mirrored** the source corpus into a scratch directory **on the session host** to read it without the
  transport truncating the heads of large documents. That is a read of the estate and a write **outside** it;
  it is disclosed here because the brief said "your only write is the one new document", and a reader is
  entitled to know the difference.
* **Where two documents disagree I have said so and named which governs** (C-1 … C-8, and in-table). Where I
  could not tell, I wrote **unresolved** rather than choosing.
* **I did not verify any of the environment's numbers myself.** Every number in §1–§3 is QUOTED with its
  source; the only numbers I MEASURED are: the file counts and mtimes in §0.1, the journal id probes in
  GAP-05, `hostname = zabz-tech`, and the reachability of `secratary-cloud` and `zabz-yoga`.

---

<!-- tags=migration,playbook,rulebook,cutover,authority,frozen-anchor,runbook refs=000,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,151,152,153,154,155,156,157,158,159,160,162,163,164,167,169,170,171,172,173,174,175,AGENTS.md,host-posture.tsv -->
