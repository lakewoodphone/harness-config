# 000 — SYSTEMS REGISTER: what exists, what is authoritative, and what to use

> **READ THIS BEFORE DESIGNING ANYTHING ON THIS ESTATE.**
>
> **AUTHORITY STATUS, 2026-10-11 09:35Z — THE CUTOVER IS COMPLETE.** `secratary-cloud` is the
> authority and now runs everything the office box ran, verified item by item rather than asserted:
> 22 cron jobs (each proven by a row in `/root/.cron-status/runs.tsv`), four systemd units all
> `ExecMainStatus=0`, the offsite database backup plus a new offsite job for the 13 GB of
> non-database state, an external dead-man switch that pings healthchecks.io every 5 minutes, the
> journal publishing itself to a bare repo on the vault (`2.28.33.58`, a different provider), and a
> guard over 12 critical paths including `authorized_keys`. Full record: journal `H3444` (the finish)
> and `H3407` (the cutover itself); the port list is `docs/mesh/132-CRON-INVENTORY.md` and the ordered
> finish is `docs/mesh/142-RECOVERY-RUNBOOK.md`.
>
> **HOW THIS BOX WAS LOCKED OUT, AND WHY IT MATTERS TO YOU.** On 2026-10-11 `/root` was left mode
> **777**. With `StrictModes` on (the default), sshd then refuses *every* authentication — key and
> password alike — from a world-writable home directory, and it says so in its own log:
> `Authentication refused: bad ownership or modes for directory /root`. The estate lost ssh to its own
> authority for over an hour while the API stayed up and the key sat in `authorized_keys` unchanged.
> **So: `/root` must be 700, and `cron-target-guard`'s critical list now checks it.** Two keys are
> installed (the estate's and `authority-recovery-2026-10-11`, held only on ZABZ-YOGA), and fail2ban's
> `ignoreip` carries the estate's own /24s so ordinary agent traffic cannot be mistaken for the
> brute-force this public host receives.
>
> **A frozen office box means: cron MASKED, all five writer units stopped AND disabled, all three
> watchdog timers and their `.service` siblings stopped and disabled.** Anything that restarts one of
> them creates a SECOND WRITER against a database the cloud box is now serving — the one condition
> this whole design exists to prevent. Before touching that box, read `H3407` §ROLLBACK.
> **One exception is now running there deliberately and is NOT a writer:** `mesh-broker.service`, a
> loopback-only placement service that reads node health surfaces and touches no database. It is what
> makes `subagent` fan-out work today; it belongs on `secratary-cloud` and moves there as soon as that
> box is on the tailnet (owner question 445 — the estate's stored auth key is dead).
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
| **`secratary-cloud`** | `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` (or the alias `secratary-cloud`) | **THE AUTHORITY (primary)** — company DB, API, dashboard, the offsite backups, the dead-man switch, the journal publisher and every ported cron job (22) | Hetzner CCX13, Ashburn VA, 2 vCPU, 7.7 GB, 75 GB NVMe. **No tailnet yet** (Tailscale 1.104.1 installed, `tailscaled` running, the join is blocked on a dead auth key - owner question 445). **`/root` must be mode 700**: at 777 sshd refuses every authentication. Two keys installed; `authorized_keys` is on the guard's critical list. |
| **`secratary`** | `secratary-ts` | office box — was the authority until the cutover; becomes a compute worker and the **rollback anchor** | i5-4570 (2013), 4c/4t, 23 GB, 467 GB SATA+LUKS. **Unreliable: goes off, and its NIC CANNOT wake it** (`ethtool eno1` reports no `Wake-on:` line at all; `ethtool -s eno1 wol g` is a silent no-op). |
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
| **promote the company to the standby** | `lpt-survivor-01:/opt/company/deploy/hosting-migration/scripts/company-promote.py`; **and the subset-capable copy in this repo at `scripts/mesh/company-promote.py`** | `--dry-run` by default; `--apply` to act. Refuses unless: target tunnel exists; it has an ACTIVE CONNECTOR; standby answers 200 `"mode":"survivor"`; **the primary is NOT serving** (two writers); no unreverted prior promotion. Exit 1 = refused, 2 = promoted but unhealthy → revert. |
| **move the public hostnames** | `…/company-dns-failover.py`; **and `scripts/mesh/company-dns-failover.py`** | the mechanism `company-promote.py` drives. **Do not hand-edit the CNAMEs.** |
| **⚠️ THE FOUR HOSTNAMES ARE NOT ONE SURFACE** | `scripts/mesh/company-dns-failover.py` gained `--hostnames` 2026-10-11 | `api.` and `ai.` live on the company app and can move; **`dialer.` (`:8899`) and `secretary-ssh.` (`:22`) are office-bound** — pointing them at a tunnel with no rule for them answers **403**. Default is still all four, so a failover is unchanged. See journal `D3040`. |
| **make a host a survivor** | `…/survivor-bootstrap.sh` (+ `survivor-preflight.sh`, `survivor-seed.sh`) | preflight refuses a box that cannot host it; bootstrap is idempotent and by stage |
| **the proof, and its corrections** | `…/docs/operations/resilience/M-standby-surface-and-failover-proof.md` | read before touching any of the above |
| standby tunnel | `secretary-standby` = `b69e2492-7e32-4a3b-9874-befb38ab7a5c` | healthy, 4 connectors — **but its seed is a REHEARSAL copy 109h stale, so it cannot serve customers** (`P2934`) |
| **the new authority's tunnel** | `personal-secretary-cloud` = `3e62916c-04ac-421b-b4a4-9af0852d8024` | created 2026-10-11; connector live on `secratary-cloud` with **4 colos**; ingress `ai./phone -> :3087`, `ai. -> :3000`, `api. -> :8002` |

### 2.2 Backups — **ALREADY EXISTS. R2 and restic. NO STORAGE BOX IS NEEDED.**
| what | where / how |
|---|---|
| **raw DB → R2** | **now `secratary-cloud:/usr/local/bin/authority-offsite-backup.sh`** (daily `authority-offsite-backup.timer` 05:20Z; streams the SQLite page-stream through gzip into a 64 MiB multipart upload, so no second database-sized file touches the disk) → `authority/secretary.db.gz` plus a `.sha256` sidecar. Creds `/root/.lpt-r2.env` (mode 600, scoped to ONE bucket). The office version (`secratary-ts:~/bin/push-db-offsite.sh`) is the retired original and must NOT be run: it would publish the FROZEN office database over the live object. |
| **6-hourly snapshot tarball → restic → R2** | `secratary-ts:~/bin/company-offsite-push.sh` → streams to Box 2, written into **`psm-backups/company-offsite`** by `/root/company-offsite-backup.sh` on `lpt-apps`. **This job did NOT move with the cutover** and its office copy would ship a frozen database, so it is disabled until re-pointed; in the meantime the non-database state has its own new job: `authority-data-offsite.timer` on the authority archives `/opt/company/data` to `authority/data/authority-data.tar.gz` daily at 06:30Z. |
| **NEVER MERGE THE TWO RESTIC REPOS** | the nightly `lpt-apps` job runs `restic forget` with no tag filter and would evict the company's copy |
| **freshness monitor** | `~/bin/report-offsite-age.sh` (every 30 min) → reports newest TRUSTED copy to the vault |
| **local snapshots** | `secratary-ts:/home/zabz/secretary-backups/<stamp>/`, pruned by `prune-backups.sh` |
| **completeness** | **`COMPLETE` marker** written LAST by `backup-data.sh`; both pushers REQUIRE it and refuse a directory without one. Added 2026-10-10 (P2931). |

### 2.3 The mesh (fan-out + orchestration)
| what | where / how |
|---|---|
| **fan out to another machine** | the `subagent` tool = the mesh provider (`remote-ssh`). `subagent_local` runs HERE; `subagent_fork` runs in this process WITH this history. **Never fan out locally while the mesh is reachable.** |
| placement broker | `mesh-broker.service` on the authority, loopback `:3091` |
| **placement failover** | `packages/plugin-remote-fanout/lib/failover-placer.js` — if the broker is UNREACHABLE, the dispatcher reads every node's `/mesh/health` directly and ranks. The broker is an optimisation, not a veto. |
| per-node surface | `GET /mesh/health` (unauthenticated, rich) and `POST /mesh/run` (HMAC) — `packages/plugin-mesh-http` |
| **run a long child** | `run_in_background: true`. **`subagent` defaults to FOREGROUND and blocks the turn.** `subagent_fork` defaults to background. |

### 2.4 The journal (continuity)
`python ~/code/harness-config/journal/tools/journal.py status` — then `list --kind pain --status open`,
`show <id>`, `search`, `newest handoff`. **Never read the tree end to end.** `append lessons|handoff|pain|decisions|wins`.

---

## 3. Which system is authoritative for what

| the question | the answer |
|---|---|
| the company database | `secretary.db` on the **authority** (`secratary-cloud` after the cutover; `secratary` before). A replica that can WRITE has become a second company. |
| the company API (public) | `https://api.abletelsolutions.com` |
| the dashboard (public) | `https://ai.abletelsolutions.com` |
| the phone-and-tech business API | `https://api.lakewoodphoneandtech.com` → **NOT the company API**; Caddy on `lpt-apps` → `lpt-backend:3001` |
| the offsite backup | Cloudflare R2, bucket `lakewood-rentals-media` |
| code + the journal | the git repo `harness-config` (remote on the authority) |

---

## 4. Traps that have already cost this estate

1. **A public hostname is not the machine you think.** `api.lakewoodphoneandtech.com` is the *business* API on Hetzner; the company API is `api.abletelsolutions.com`. Resolve the name and match the response shape before reporting a machine's health. Reading the wrong host's `uptime` sent the owner to the office.
2. **NEVER run `dbstat`, a recursive `du`, a full-table scan, or `.backup` of a large DB on the OFFICE box.** It saturates the disk, stalls sshd, and takes the machine off the network. It was done three times and each time broke it. Do that work on the idle cloud box.
   - **⚠️ THE PROPERTY, NOT THE LIST. Measured again 2026-10-11 02:17Z, from a command that is on none of the four in the list above:** a 14.2 GB / ~200,000-file `rsync` **of the app's `data/` directory** — pure READS, never touching the database — took the box to load **52 on 4 threads**, 22,000 blocks/s of disk writes, 3.1 GB of 4 GB swap in use, sshd silent on the tailnet, and `api.abletelsolutions.com` to **HTTP 502 for 20+ minutes**. The rule is not "do not run these four commands". It is: **this box's only path to the world is a disk-starved sshd, so ANY operation that keeps its disk queue busy for more than a few seconds is forbidden while it is the authority — reads included, and the test is not whether it touches the database.** Check `cut -d' ' -f1 /proc/loadavg` (stop above ~8) and `wa` in `vmstat` (stop above ~10 %) *during* anything long, and prefer running the work from the other end. See journal `P2936` and `H3406`.
   - **The corollary, and it has now been observed three times:** sshd stops answering while `tailscale ping` still replies. **That is I/O starvation, not a powered-off box.** Wait and retry. Do not conclude it is down, and do not drive to Lakewood on that reading.
   - **Do the non-database data move AFTER the DNS switch**, in bounded batches, from the box that no longer has anything depending on it. It is not on the critical path to "the authority is reachable".
3. **`/tmp` is a RAM tmpfs on some hosts** (12 GB on the office box). Never stage a multi-GB file there. (P2892.)
4. **A `Wake-on` that has never been fired is not a wake path.** On the office box it is not merely unproven — the NIC reports no `Wake-on:` at all.
5. **Exit 127 from a cron job means the SCRIPT MOVED.** Check the path before believing anything about the job's logic.
6. **A guard whose failure has never been seen cannot be trusted.** `cron-target-guard.py` reports `ok / 0 missing` because it never decodes the base64 in the crontab; ~60 of its "checked" targets are the one wrapper.
7. **Byte-count verification proves the TRANSPORT, never the CONTENT.** A corrupt source uploads faithfully and reports OK. Open the artifact.
8. **An interrupted backup leaves a directory that looks like a backup.** Hence the `COMPLETE` marker.

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
