# 000 — SYSTEMS REGISTER: what exists, what is authoritative, and what to use

> **READ THIS BEFORE DESIGNING ANYTHING ON THIS ESTATE.**
>
> This file exists because of two failures, both in the same 48 hours, both the same shape:
> an agent proposed to BUILD something the estate already had. First a Hetzner Storage Box, when
> Cloudflare R2 already held the offsite backup. Then a hand-rolled Cloudflare DNS cutover, when
> `company-promote.py` already performed promotions with five pre-flight refusals — including the
> exact two-writer hazard the agent had "independently derived". The owner paid $51.59/month and
> hours of work on the second one before the existing system was found.
>
> **THE RULE: before designing a mechanism, SEARCH THE ESTATE FOR THE MECHANISM.** Budget 10
> minutes for this. It is cheaper than every alternative. Grep the repos, `ls` the hosts, read this
> file, and ask `journal.py search` before the first design sentence is written.

---

## 1. The machines, and what each is FOR

| machine | ssh | role | notes |
|---|---|---|---|
| **`secratary-cloud`** | `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` | **THE AUTHORITY (primary)** — company DB, API, dashboard, **and since 2026-10-12 the mesh placement broker** (`mesh-broker`, loopback `:3091`, enabled) | **Hetzner CCX33, Ashburn VA, 8 dedicated vCPU, 32 GB RAM, 240 GB NVMe → 225 GiB ext4** (rescaled from CCX13→CCX23→CCX33; measured 2026-10-19: 118 G used, 99 G free, 55%). **Disk, database, backup and retention facts live in `docs/mesh/000-DISK-AND-DATABASE.md` — that file is authoritative for them, not this row.** **ON the tailnet since before 21:35Z 2026-10-11**: `100.73.176.126`, `active; direct 178.156.194.1:41641`, seen in the office box's own `tailscale status`. A private API path exists and works - `tailscale serve --bg --https=8443 http://127.0.0.1:8002`, giving `https://secratary-cloud.tail93e6e6.ts.net:8443/health` -> 200 `ok=True db_ok=True`, and `scripts/mesh/route.sh` chooses it FIRST. **Any 'blocked on a Tailscale auth key' note is stale - no owner action is needed for this.**  |
| **`secratary`** | `secratary-ts` | office box — was the authority until the cutover; becomes a compute worker and the **rollback anchor** | i5-4570 (2013), 4c/4t, 23 GB, 467 GB SATA+LUKS. **Unreliable: goes off, and its NIC CANNOT wake it** (`ethtool eno1` reports no `Wake-on:` line at all; `ethtool -s eno1 wol g` is a silent no-op). **Its `mesh-broker` is STILL ACTIVE/ENABLED** (measured 2026-10-12) — the last live dependency on a frozen box, pending owner question #447. |
| **`zabz-tech`** | `desktop-ts` | the workhorse: agent compute, 32c, 52 GB free | also the fleet's landfall for mesh children |
| **`zabz-yoga-1`** | `laptop-ts` (this laptop's tailnet name) | the owner's machine; a dispatcher and a worker | |
| **`zabz-tech-linux`** | `linux-pc-ts` | compute worker + a **vault** | office Linux PC |
| **`lakewooechsmini`** | `mac-mini-ts` | compute worker (Yisroel's Mac) | |
| **`lpt-apps-01`** | `lpt-apps` | Hetzner CX33, Falkenstein. Caddy front door for `*.lakewoodphoneandtech.com`, the **R2 backup credential holder**, restic **"vault / Box 2"** | 14 containers, 90 % disk full — do NOT add load |
| **`waze-mdm-01`** | `hetzner` | Hetzner CPX11, Ashburn. Waze MDM production | |
| **`lpt-survivor-01`** | `survivor` | Hetzner CX33, Falkenstein. **THE STANDBY + the failover tooling live here** | `/opt/company`, runs the company API in `mode:"survivor"` |

---

## 2. The systems register — USE THESE, DO NOT REBUILD THEM

### 2.1 Failover and promotion — **ALREADY EXISTS, PROVEN 2026-10-06**
| what | where | how to use |
|---|---|---|
| **promote the company to the standby** | `lpt-survivor-01:/opt/company/deploy/hosting-migration/scripts/company-promote.py` | `--dry-run` by default; `--apply` to act. Refuses unless: target tunnel exists; it has an ACTIVE CONNECTOR; standby answers 200 `"mode":"survivor"`; **the primary is NOT serving** (two writers); no unreverted prior promotion. Exit 1 = refused, 2 = promoted but unhealthy → revert. |
| **move the public hostnames** | `…/company-dns-failover.py` | the mechanism `company-promote.py` drives. **Do not hand-edit the CNAMEs.** |
| **make a host a survivor** | `…/survivor-bootstrap.sh` (+ `survivor-preflight.sh`, `survivor-seed.sh`) | preflight refuses a box that cannot host it; bootstrap is idempotent and by stage |
| **the proof, and its corrections** | `…/docs/operations/resilience/M-standby-surface-and-failover-proof.md` | read before touching any of the above |
| standby tunnel | `secretary-standby` = `b69e2492-7e32-4a3b-9874-befb38ab7a5c` | healthy, 4 connectors |

### 2.2 Backups — **ALREADY EXISTS. R2 and restic. NO STORAGE BOX IS NEEDED.**
| what | where / how |
|---|---|
| **raw DB → R2** | `secratary-ts:~/bin/push-db-offsite.sh` → `authority/secretary.db.gz` in bucket **`lpt-authority-backups`**, plus a `.sha256` sidecar. Creds `~/.lpt-r2.env` (mode 600, token scoped to ONE bucket, identical file on the authority and on `lpt-apps`). **NAME CORRECTED 2026-10-19:** this row and §3 both said `lakewood-rentals-media`, which is the *rental listings* bucket, not the backup one — measured by `list_objects_v2` against the live credentials (`R2_BUCKET=lpt-authority-backups`, 22 objects, 33.9 GB). |
| **6-hourly snapshot tarball → restic → R2** | `secratary-ts:~/bin/company-offsite-push.sh` → streams to Box 2, written into **`psm-backups/company-offsite`** by `/root/company-offsite-backup.sh` on `lpt-apps`. |
| **NEVER MERGE THE TWO RESTIC REPOS** | the nightly `lpt-apps` job runs `restic forget` with no tag filter and would evict the company's copy |
| **freshness monitor** | `secratary-cloud:/usr/local/bin/authority-report-offsite-age.sh` (every 30 min, `authority-report-offsite-age.timer`) → HEADs the R2 object and writes `authority-push.json` to the vault, where the outside heartbeat alarms on the REAL object's age. **It reads ONE key, `authority/secretary.db.gz`** — see the next row. |
| **the authority's TWO daily legs — do not conflate them** | (1) `authority-offsite-backup.timer` → `/usr/local/bin/authority-offsite-backup.sh` → `authority/secretary.db.gz` + `authority/accounting.db.gz`; evidence `/var/lib/authority-backup/last-run`. (2) `authority-data-offsite.timer` (06:30 UTC + up to 10 min jitter) → `/usr/local/bin/authority-data-offsite.sh` → `authority/data/authority-data.tar.gz` (~4 GB); evidence `/var/lib/authority-backup/data-last-run`. **Every monitor watched leg (1) only until 2026-10-16**: on the 16th leg (2) refused to start (`exit 3`, "only 1582332 KiB free under /var/tmp") and its R2 object reached **38.16 h** stale while `estate-monitor` reported `offsite_object_age_h=14.952 st=ok`. |
| **what watches the legs NOW (2026-10-16)** | `authority-deadman.py` → the external healthchecks.io check "secratary authority alive" (its only notification channel is one `kind=email`) — it now ALSO fails on `systemctl is-failed` for either offsite unit, and on `data-last-run` older than 27 h. `estate-monitor.timer` carries `offsite_data_lastrun_age_h` / `offsite_data_lastrun_not_ok`. **Retry on transient failure**: drop-in `settings/authority-data-offsite-retry.conf` → `Restart=on-failure`, `RestartSec=900`, `StartLimitIntervalSec=3h`, `StartLimitBurst=5`. |
| **local snapshots** | `secratary-ts:/home/zabz/secretary-backups/<stamp>/`, pruned by `prune-backups.sh` |
| **completeness** | **`COMPLETE` marker** written LAST by `backup-data.sh`; both pushers REQUIRE it and refuse a directory without one. Added 2026-10-10 (P2931). |

### 2.3 The mesh (fan-out + orchestration)
> **Read first: `docs/mesh/160-MESH-STATE-AND-NEXT.md`** — one page with the mesh's measured state,
> what was done in the 2026-10-12 post-cutover audit, what to do next, and a reference to every other
> document. The rows below are the durable facts; 160 is the map.

| what | where / how |
|---|---|
| **fan out to another machine** | the `subagent` tool = the mesh provider (`remote-ssh`). `subagent_local` runs HERE; `subagent_fork` runs in this process WITH this history. **Never fan out locally while the mesh is reachable.** |
| placement broker | **`mesh-broker.service` on the AUTHORITY `secratary-cloud`, loopback `:3091`** — enabled and started 2026-10-12 03:18Z, roster `/opt/mesh-broker/nodes.json` (a copy of `packages/mesh-broker/nodes.json`, in which the frozen box is `excluded: true`). Reached by every dispatcher as `ssh secratary-cloud curl … localhost:3091/…` (`MESH_BROKER_SSH`, default in both `profiles/web/cordis.patch.yml` and `bin/mesh-run.mjs`). **The office box's copy is STILL RUNNING and enabled** — the one remaining step of the move, and it is the owner's (question #447): two brokers for one mesh keep two lease ledgers, so two dispatches could both fill one machine. See `159-MESH-POST-MIGRATION.md`. |
| **the broker can only read nodes whose gate allows it** | `scripts/phone-gate.py` refuses any tailnet device not listed in `phone-gate-allow.txt`, and that check runs BEFORE the mesh routes. **A broker whose host is not listed reads NOTHING and still answers** (measured 2026-10-12: 5/5 nodes `HTTP 403`, and `/place` returned a well-formed, blind `position 1 blockedBy ["unreachable","no-free-slots"]`). The authority is now listed; check with `curl -s http://127.0.0.1:3091/nodes?fresh=1` and never let "unreachable" be the answer for every node. The list is read per node from whichever checkout that node's gate was started from, so it must be deployed per node, not once. |
| **placement failover** | `packages/plugin-remote-fanout/lib/failover-placer.js` — if the broker is UNREACHABLE, the dispatcher reads every node's own surface directly and ranks. The broker is an optimisation, not a veto. **A node whose `/mesh/health` is missing is NOT dead**: since 2026-10-12 `lib/node-probes.js` falls back to `/mesh/capacity` and the node stays usable over v1 with slots UNMEASURED (`zabz-tech-linux` answers 404 on health and 200 on capacity; the office box 502/200). |
| per-node surface | `GET /mesh/health` (unauthenticated, rich) and `POST /mesh/run` (HMAC) — `packages/plugin-mesh-http`. **Not every node serves `/mesh/health`**: a node behind `phone-gate.py` may answer `/mesh/capacity` only. `secratary-cloud` answers 200 but advertises `auth.secretConfigured:false` (`/etc/dsh-mesh.env` absent), so it cannot sign a v2 run. |
| **parent ↔ child while a child works** | **Does not exist for a mesh child.** Measured 2026-10-12: `list_agents` → `(no subagents)` and `send_message` → `subagent "…" is unavailable` while the child was mid-turn. Parent → child is the dispatch; child → parent is the final report, plus the mailbox thread — and the thread directory is **not created for the child**, so it silently reports `0 message(s)` unless the child improvises it. |
| **run a long child** | `run_in_background: true`. **`subagent` defaults to FOREGROUND and blocks the turn.** `subagent_fork` defaults to background. |
| **the authority as a NODE (added 2026-10-19)** | roster row `secratary-cloud`, `maxChildren: 2`, `baseUrl: http://127.0.0.1:3086` (loopback on purpose — this node's gate does **not** allow its own tailnet address, so a tailnet read answers `403` while loopback answers 200). Executor `/usr/local/bin/dsh-mesh`, `DSH_HOME=/root/.dsh-worker`, runtime pinned at `/opt/dsh-mesh-runtime`, every turn inside `dsh-mesh.slice` (`MemoryMax=6G`). Proof: `dsh-mesh --profile headless …` → `MESH-HOST: secratary-cloud` exit 0; `POST /place` → position 0 `tier=fits`. **Never run `scripts/provision-mesh-node.sh` on this box**: it writes `Environment=DSH_HOME=$HOME/.dsh`, which collides with `phone-engine`'s home and is the exact state `docs/mesh/71` forbids. Full record: `docs/cloud-audit/2026-10-19-cloud-and-storage-audit.md` §3. |

### 2.4 The journal (continuity)
`python ~/code/harness-config/journal/tools/journal.py status` — then `list --kind pain --status open`,
`show <id>`, `search`, `newest handoff`. **Never read the tree end to end.** `append lessons|handoff|pain|decisions|wins`.

### 2.5 Search the estate — **ALREADY EXISTS. ONE engine. Do not grep -r, do not build a second one.**
Added 2026-10-12 (journal **H3571**). This section exists because the search surface was **not** in this
register, and so the cloud cutover carried none of it: `ps_search` — the tool the `fast-search` skill
tells every agent to use — answered `Tool search not found` on the authority for a full day.

**Updated 2026-10-18 (journal H7594, D6913, program `unified-search/docs/ESTATE-SEARCH-PROGRAM.md`):
the surface agents call is now `esearch`, and it answers over SESSIONS too.**

| what | where / how |
|---|---|
| **the one surface** | `ps_search(q, what=…)` → `esearch`, `https://secratary-cloud:8444` (tailnet) or `127.0.0.1:3095` on the authority. `systemctl status esearch` |
| **what it reads** | `authority.db` in place — `dsh_session_events_fts` (8,587 sessions / 2,640,513 events, 0.15 s to rank 6,831 matches), `memories_fts`, `vscode_chat_sessions_fts` — plus `/root/.usearch/usearch.db`: comms (180,930), journal, mail, and the documents/code each host pushes |
| **`what` now means** | `sessions` · `data` (comms) · `journal` · `docs` · `files` · `code` · `memory` · `chats` · `all`. Measured 2026-10-18: sessions 234 ms, comms 620 ms, journal 27 ms |
| **how hosts contribute** | each host's `sync.py --push https://…:8444/ingest` posts the adapter's own document stream; a failed push is spooled and retried, and `?heartbeat=1` records a host that ran and had nothing new |
| **freshness** | `esearch-health.timer` every 15 min → `/usr/local/bin/esearch-health-check.sh`; `/health` fails when the estate index, the session ingest, disk, or a host's last push (1.5× its interval) is out of bounds. **Proven both ways 2026-10-18:** exit 1 with the service stopped, exit 0 after it restarted |
| **`fa` is narrowed, not replaced** | `fa symbol` and `fa --fresh` remain the only correct answer for a definition you are about to edit; `fa` is also the fallback when esearch is unreachable, and the tool marks that answer `degraded:` |

| what | where / how |
|---|---|
| **the surface agents call** | `ps_search(query, what, limit, fresh)`, or `ps_action("search", {…})`. `what` ∈ `code` `data` `journal` `files` `symbol` `auto`. Returns `ok`, `source`, `ms`, `stale`, `exit_code`, `searched`. **`searched:false` is a REFUSAL, not a negative.** |
| **the engine** | `find-anything` (`fa` on PATH). Canonical source: `harness-config/scripts/find-anything/find-anything`. Installed by `scripts/find-anything/install.sh` to `/usr/local/bin/find-anything` + `fa` symlink. On Linux a node may also run `fa <mode> <query>` directly. |
| **the tool body** | `<checkout>/data/tools/search.py`, canonical at `scripts/find-anything/search-tool.py`. It shells out to the engine and translates exit codes; it adds **no second grammar**. Resolves the engine via `FIND_ANYTHING_BIN` → `fa` on PATH → two legacy paths. |
| **exit codes are the contract** | `0` hits · `1` a real negative · `2` bad usage · `3` answered but possibly stale · `4` **NOTHING was searched** · `5` the index failed. Only `3` used to be read, so `4`/`5` reached agents as `ok:true "(no hits)"` — the exact lie the tool exists to prevent. |
| **the indexes** | `~/.faindex/paths.txt` (filenames), `~/.faindex/tags` (ctags symbols), `~/.fsearch/comms.db` (business comms FTS), and the journal index at `harness-config/journal/index`. Built by `find-anything-build-indexes`; the journal index too, because nothing else owned "keep the indexes fresh". |
| **`symbol` is NEVER indexed** | you are about to edit that file. `fa symbol` is always a live scan. `fa symbols` is the browse-only ctags index. |
| **the clocks** | `*/15` `fa-index-refresh`, `22 * * * *` `fa-index-freshness`, `37 * * * *` `tool-body-guard`. Generated by `scripts/find-anything/make-crontab-fragment.sh`, installed with `install-crontab-fragment.sh`. |
| **the guard for tool loss** | `scripts/guards/tool-body-guard.py` — every ACTIVE registered tool must have a body at `data/tools/<name>.py`. `run_tool()` answers `Tool <name> not found` from a single `if not tool_path.exists()`, so a registered-but-absent tool is indistinguishable from a tool that does not exist. Exit `0` ok, `1` missing bodies, `2` could not check (never a pass). |

**THE THREE TRAPS THIS REGISTER ENTRY EXISTS TO PREVENT.**

1. **`data/tools/` IS GITIGNORED** (`.gitignore:58`). 599 of 607 registered tool bodies were lost at
   the cutover because no deploy from any branch could carry them and the only copy was on the box
   being frozen. Registering a tool does not create it, and nothing asserted that a registered tool
   had a body until `tool-body-guard.py` existed.
2. **A refresh job cannot report that it has stopped running.** This estate has shipped a silently
   dead search clock at least three times: journal **P2899 D2** (a trigger whose repetition pattern
   expired after one day), **H3376** (21 days stale, `NextRunTime` empty), and `zabz-tech`'s
   `DSH search index refresh` (`LastTaskResult=1`, measured 2026-10-12). Every one of them still
   described itself as "scheduled". Hence the freshness *guard* job, which exits non-zero.
3. **A hardcoded path is a fork waiting to happen.** Two separate hardcodings broke at the cutover:
   the engine resolved its code roots as `$HOME/personal-secretary-mvp` (the checkout is `/opt/company`
   on the authority) and the tool body hardcoded `/home/zabz/bin/find-anything` (a path no cloud node
   has). Both now resolve by probe with an env override. **Never write a node's absolute layout into a
   shared script.**

---

### 2.6 Online research and procurement — **ALREADY EXISTS, and half of it is a mirage**

Added 2026-10-23 (owner asked for the inventory after creating an eBay Production keyset). Full
detail, every measured number and every dead end: **`docs/mesh/150-RESEARCH-AND-PROCUREMENT.md`**.
The four things a session must know before it builds anything in this area:

| need | use | the trap |
|---|---|---|
| eBay listings, prices, conditions | **`lpt-hub/scripts/sourcing/ebay_api.py`** — Browse API client, `doctor` / `selftest` / `search` / `item`. Deployed to the authority as `/opt/company/data/tools/ebay_api.py` (+ `ebay_browse_search.py` for the dispatcher) | credentials are at `~/.secrets/ebay-personal.env`; on 2026-10-23 eBay answered **401 invalid_client**, so the client is proven (17/17 selftest) and the keyset is not yet accepted. `doctor` says which half it can and cannot localise |
| a web answer / a page | `ps_action("web_search")`, Firecrawl (`proxy: stealth` for eBay search+item), Jina `read_url` | eBay **sold/completed is login-gated**; Firecrawl JSON mode fails on eBay search pages — use markdown (`L2386`) |
| long multi-source research | `personal-secretary-mvp/app/services/research_dispatcher.py` | **idle since 2026-07-08** — `research_jobs` on the authority: newest `submitted_at` 2026-07-08T05:40:32Z, 70 queued, 3 stuck `running` since 2026-07-03. Check the table before commissioning a fourth pipeline |
| Alibaba/AliExpress and FB Marketplace | `lpt-hub/scripts/procurement-assistant/`, `.../marketplace-assistant/` | both need a one-time interactive `login` in their own Chrome profile |

**The mirage, measured 2026-10-23** — this is the part worth memorising:

* The sourcing README documented four scraper scripts (`find-flip-deals.py`,
  `ebay_laptop_search.py`, `laptop_sourcing.py`, `collect_ebay_listing_images.py`). **None exists** —
  not in `lpt-hub` git history on any ref, not in the estate file index. The README was corrected.
* `open.api.ebay.com` (legacy Shopping API, still called by
  `data/tools/laptop_sourcing_order_executor.py`) **does not resolve in DNS**.
  `api.ebay.com/ws/api.dll` (Trading XML) returns **410 Gone**.
* `data/tools/electronic_part_scout.py` returns **two hardcoded mock parts**; `source_auth_manager.py`
  reports `authenticated: True` unconditionally; `scraper_auth_manager.py` has **zero consumers** and
  its vault file does not exist. None of the three is a capability.



| the question | the answer |
|---|---|
| the company database | `secretary.db` on the **authority** (`secratary-cloud` after the cutover; `secratary` before). A replica that can WRITE has become a second company. |
| the company API (public) | `https://api.abletelsolutions.com` |
| the dashboard (public) | `https://ai.abletelsolutions.com` |
| the phone-and-tech business API | `https://api.lakewoodphoneandtech.com` → **NOT the company API**; Caddy on `lpt-apps` → `lpt-backend:3001` |
| the offsite backup | Cloudflare R2, bucket **`lpt-authority-backups`** (measured 2026-10-19; see §2.2) |
| code + the journal | the git repo `harness-config` (remote on the authority) |

---

## 4. Traps that have already cost this estate

1. **A public hostname is not the machine you think.** `api.lakewoodphoneandtech.com` is the *business* API on Hetzner; the company API is `api.abletelsolutions.com`. Resolve the name and match the response shape before reporting a machine's health. Reading the wrong host's `uptime` sent the owner to the office.
2. **Never run `dbstat`, a recursive `du`, a full-table scan, or `.backup` of a large DB on the OFFICE box.** It saturates the disk, stalls sshd, and takes the machine off the network. It was done three times and each time broke it. Do that work on the idle cloud box.
3. **`/tmp` is a RAM tmpfs on some hosts** (12 GB on the office box). Never stage a multi-GB file there. (P2892.)
4. **A `Wake-on` that has never been fired is not a wake path.** On the office box it is not merely unproven — the NIC reports no `Wake-on:` at all.
5. **Exit 127 from a cron job means the SCRIPT MOVED.** Check the path before believing anything about the job's logic.
6. **A guard whose failure has never been seen cannot be trusted.** `cron-target-guard.py` reports `ok / 0 missing` because it never decodes the base64 in the crontab; ~60 of its "checked" targets are the one wrapper.
7. **Byte-count verification proves the TRANSPORT, never the CONTENT.** A corrupt source uploads faithfully and reports OK. Open the artifact.
8. **An interrupted backup leaves a directory that looks like a backup.** Hence the `COMPLETE` marker.
9. **A half-applied retarget is more dangerous than no retarget.** After the 2026-10-11 cutover the provider row already named `secratary-cloud` while `bin/mesh-run.mjs` still named `secratary-ts` — two dispatch paths, two brokers, one of them on a box declared inert. When a default moves, grep for **every** place that names the old one and move them in the same commit (`grep -rn '<old-host>' --include=*.yml --include=*.mjs`).
10. **A control plane that reads nothing still gives a well-formed answer.** The mesh broker is built never to refuse, so with every node unreadable it answered `position 1, blockedBy ["unreachable","no-free-slots"]` — correct-looking and blind. Measured 2026-10-12: the node gates (`scripts/phone-gate.py` + `phone-gate-allow.txt`) refuse any tailnet device not listed, so the authority could not read a single node. **Never accept "the service is active" as evidence it works: make it read one real thing.**
11. **A pinned comment is not a fix.** `docs/mesh/154-MESH-BROKER-MOVE.md` said the move was staged and needed one owner decision; the broker was then started without anyone proving it could read a node. Verify the *new* path end to end before you retire the old one.

12. **Trap 10 RECURRED, and this is the record of it (2026-10-27).** The allow-list on `lakewooechsmini` still named `100.84.72.88` as *"the always-on company authority"* — true until 2026-10-11. The authority moved to `100.73.176.126`; the list did not. **The broker was blind to a 10-core worker for fifteen days**, every probe refused with 403, and the broker reported each one as `state=unreachable` — the wrong noun, so it read as a network fault rather than a list. Two lessons, both already written above and both ignored: trap 10 says make the control plane read one real thing, and **the comment that called the frozen box "the authority" is what made the missing line invisible** — a list that names *an* authority looks complete. Corrected; `harness-config-drift.timer` (05:20 UTC) now reports every node's branch.

13. **A backup is named for what it contains, not what you meant.** The nightly restic job on `lpt-apps` dumped the retired `lpt-postgres` container, restored to prove it (orders newest 2026-09-14), while the shop's **live** store was RDS and had **one 6-day copy on the same host that served it**. 62 snapshots, every one a success. **Restore the newest artefact and compare a row count against live before calling a backup a backup.**

14. **A file is only as current as the branch the reader tracks.** `lakewooechsmini` and `zabz-tech-linux` both fetch `harness-config` from the frozen office box — fine, that bare repo is a live push target — but the mac mini's checkout sits on **`master`** with 42 unpublished journal commits while fixes land on **`main`**. Every surface that said "synced to the nodes" was true about the *remote* and silent about the *checkout*. **Ask each node which branch it is on**; a file-comparison drift check would have missed it.

15. **A meter reading an unpopulated column is worse than no meter.** Pass one concluded `deepseek-flash` cached 1.13 % from `model_usage.cached_tokens` — a column nothing writes. The truth, from `dsh_session_events`, is **99.0 %**. The wrong figure produced a whole cost strategy. **When a number decides something expensive, check what WRITES the field before you check the number.**

---

## 5. Before you build: the 10-minute survey

```bash
# 1. does the estate already have it?
grep -ril "<the thing>" ~/code/harness-config ~/code/personal-secretary-mvp 2>/dev/null | head
# 2. is it documented?
python ~/code/harness-config/journal/tools/journal.py search "<the thing>"
# 3. is it running somewhere?
for h in secratary-cloud secratary-ts desktop-ts lpt-apps survivor; do
  echo "--- $h"; ssh -o ConnectTimeout=8 -o BatchMode=yes $h \
    'systemctl list-units --type=service --state=running --no-legend 2>/dev/null | head -20' 2>/dev/null
done
# 4. is there a script already?
ls ~/bin /opt/company/deploy/hosting-migration/scripts 2>/dev/null
```

**If the answer is "it exists", USE IT. If it exists but is broken, FIX IT. Do not build a parallel one.**
