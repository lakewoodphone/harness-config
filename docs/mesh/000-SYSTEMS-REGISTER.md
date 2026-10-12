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
| **`secratary-cloud`** | `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` | **THE AUTHORITY (primary)** — company DB, API, dashboard (**not the broker** - see the placement-broker row) | Hetzner CCX13, Ashburn VA, 2 vCPU, 7.7 GB, 75 GB NVMe (~1.1 GB/s). **ON the tailnet since before 21:35Z 2026-10-11**: `100.73.176.126`, `active; direct 178.156.194.1:41641`, seen in the office box's own `tailscale status`. A private API path exists and works - `tailscale serve --bg --https=8443 http://127.0.0.1:8002`, giving `https://secratary-cloud.tail93e6e6.ts.net:8443/health` -> 200 `ok=True db_ok=True`, and `scripts/mesh/route.sh` chooses it FIRST. **Any 'blocked on a Tailscale auth key' note is stale - no owner action is needed for this.**  |
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
| **promote the company to the standby** | `lpt-survivor-01:/opt/company/deploy/hosting-migration/scripts/company-promote.py` | `--dry-run` by default; `--apply` to act. Refuses unless: target tunnel exists; it has an ACTIVE CONNECTOR; standby answers 200 `"mode":"survivor"`; **the primary is NOT serving** (two writers); no unreverted prior promotion. Exit 1 = refused, 2 = promoted but unhealthy → revert. |
| **move the public hostnames** | `…/company-dns-failover.py` | the mechanism `company-promote.py` drives. **Do not hand-edit the CNAMEs.** |
| **make a host a survivor** | `…/survivor-bootstrap.sh` (+ `survivor-preflight.sh`, `survivor-seed.sh`) | preflight refuses a box that cannot host it; bootstrap is idempotent and by stage |
| **the proof, and its corrections** | `…/docs/operations/resilience/M-standby-surface-and-failover-proof.md` | read before touching any of the above |
| standby tunnel | `secretary-standby` = `b69e2492-7e32-4a3b-9874-befb38ab7a5c` | healthy, 4 connectors |

### 2.2 Backups — **ALREADY EXISTS. R2 and restic. NO STORAGE BOX IS NEEDED.**
| what | where / how |
|---|---|
| **raw DB → R2** | `secratary-ts:~/bin/push-db-offsite.sh` → `authority/secretary.db.gz` in bucket `lakewood-rentals-media`, plus a `.sha256` sidecar. Creds `~/.lpt-r2.env` (mode 600, token scoped to ONE bucket). |
| **6-hourly snapshot tarball → restic → R2** | `secratary-ts:~/bin/company-offsite-push.sh` → streams to Box 2, written into **`psm-backups/company-offsite`** by `/root/company-offsite-backup.sh` on `lpt-apps`. |
| **NEVER MERGE THE TWO RESTIC REPOS** | the nightly `lpt-apps` job runs `restic forget` with no tag filter and would evict the company's copy |
| **freshness monitor** | `~/bin/report-offsite-age.sh` (every 30 min) → reports newest TRUSTED copy to the vault |
| **local snapshots** | `secratary-ts:/home/zabz/secretary-backups/<stamp>/`, pruned by `prune-backups.sh` |
| **completeness** | **`COMPLETE` marker** written LAST by `backup-data.sh`; both pushers REQUIRE it and refuse a directory without one. Added 2026-10-10 (P2931). |

### 2.3 The mesh (fan-out + orchestration)
| what | where / how |
|---|---|
| **fan out to another machine** | the `subagent` tool = the mesh provider (`remote-ssh`). `subagent_local` runs HERE; `subagent_fork` runs in this process WITH this history. **Never fan out locally while the mesh is reachable.** |
| placement broker | **`mesh-broker.service` on the OFFICE box `secratary`, loopback `:3091`** (measured 2026-10-11 21:35Z: `ss -ltnp` shows `node` pid 105841 on `127.0.0.1:3091` there, and the cloud's `mesh-broker.service` is `inactive`/`disabled` with **nothing** on `:3091`). Staged but NOT started on the authority: `/opt/mesh-broker/{bin/mesh-broker.mjs,nodes.json}` exist and its unit is already rewritten for that box (`WorkingDirectory=/opt/mesh-broker`, `HOME=/root`). **Moving it needs the office copy stopped, which is a state change on a frozen host and therefore the owner's call** - see `154-MESH-BROKER-MOVE.md`. |
| **placement failover** | `packages/plugin-remote-fanout/lib/failover-placer.js` — if the broker is UNREACHABLE, the dispatcher reads every node's `/mesh/health` directly and ranks. The broker is an optimisation, not a veto. |
| per-node surface | `GET /mesh/health` (unauthenticated, rich) and `POST /mesh/run` (HMAC) — `packages/plugin-mesh-http` |
| **run a long child** | `run_in_background: true`. **`subagent` defaults to FOREGROUND and blocks the turn.** `subagent_fork` defaults to background. |

### 2.4 The journal (continuity)
`python ~/code/harness-config/journal/tools/journal.py status` — then `list --kind pain --status open`,
`show <id>`, `search`, `newest handoff`. **Never read the tree end to end.** `append lessons|handoff|pain|decisions|wins`.

### 2.5 Labels — the shop's tape printer — **ALREADY EXISTS: `lpt-label`**
| what | where / how |
|---|---|
| the printer | **Brother QL-820NWB**, serial `H3G354844`, on the OFFICE LAN. DHCP — `192.168.50.60` at the time of writing and **never trusted**: `lpt-label find` re-verifies the device identifies itself by model before printing. Loaded roll: **DK-2210 endless, 29 mm**. |
| **print a label** | **on the authority**: `ssh secratary-ts 'lpt-label …'`; the safe form for shop names (they contain apostrophes) is `echo '<json>' \| ssh secratary-ts "lpt-label print -"`. Installed `/usr/local/bin/lpt-label` → `~/.local/bin/lpt-label`; source `lpt-ops/bin/lpt-label` + `lpt-ops/lpt_ops/label_printer.py`; doc `lpt-ops/docs/label-printer.md`; lesson **L3534**. |
| the ONLY honest proof tape came out | the printer's own status page, read back with `lpt-label find`, going `READY → PRINTING → READY`. **`brother_ql`'s `did_print` is `false` by construction on this model** — it reads a status register over 9100 that this printer never answers (**L3484**). |
| always first | `lpt-label print - --dry-run --out /tmp/x.png`, copy the PNG back and **look at it** before spending tape (**L3486**). |
| the website's "Print Label" button | **still dead** — it posts to `PRINT_SERVICE_URL=http://localhost:8080` and the device does not answer IPP. Do not "fix" printing by wiring that path. |

**Do NOT print a shop label through a Windows printer driver.** The QL is driven as raw Brother
raster over **TCP 9100 from the authority**. A Windows queue reaches the same device over WSD, where
the driver's default page size is the **die-cut 28 × 90 mm** (`1.1" x 3.5"`) while the loaded roll is
29 mm **endless** — and sending it raised the printer's own media error and **froze the printer hard
enough that the owner had to power-cycle it** (measured 2026-10-12: 11 tool calls and a frozen
printer for a job `lpt-label` does in one).

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
2. **Never run `dbstat`, a recursive `du`, a full-table scan, or `.backup` of a large DB on the OFFICE box.** It saturates the disk, stalls sshd, and takes the machine off the network. It was done three times and each time broke it. Do that work on the idle cloud box.
3. **`/tmp` is a RAM tmpfs on some hosts** (12 GB on the office box). Never stage a multi-GB file there. (P2892.)
4. **A `Wake-on` that has never been fired is not a wake path.** On the office box it is not merely unproven — the NIC reports no `Wake-on:` at all.
5. **Exit 127 from a cron job means the SCRIPT MOVED.** Check the path before believing anything about the job's logic.
6. **A guard whose failure has never been seen cannot be trusted.** `cron-target-guard.py` reports `ok / 0 missing` because it never decodes the base64 in the crontab; ~60 of its "checked" targets are the one wrapper.
7. **Byte-count verification proves the TRANSPORT, never the CONTENT.** A corrupt source uploads faithfully and reports OK. Open the artifact.
8. **An interrupted backup leaves a directory that looks like a backup.** Hence the `COMPLETE` marker.
9. **A media mismatch on the QL-820NWB surfaces through Windows as "No Paper".** `Win32_Printer.DetectedErrorState=4` on that device means the job's page size does not match the loaded roll at least as often as it means an empty printer — and a wrong-size job can freeze the device until it is power-cycled. Ask the device (`lpt-label find`), not Windows. (2026-10-12.)

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
