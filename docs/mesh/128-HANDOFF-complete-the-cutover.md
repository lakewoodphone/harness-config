# 128 — HANDOFF: finish the authority cutover

> **You are taking over from a session that ran out of context. Read this whole file before you run
> anything. It contains everything needed to finish, including the decisions already made, so you do
> not need to ask the owner anything except where this file explicitly says to.**

**Written** 2026-10-11 ~00:1xZ from ZABZ-YOGA. **Journal entry for this state: `H3403`.
`journal.py check` = 0 errors.**

---

## 0. READ FIRST: the rule that this whole task exists to honour

**Before you design or build ANYTHING, read `docs/mesh/000-SYSTEMS-REGISTER.md`.** This estate
already contains a proven failover system, an offsite backup chain, a mesh, and a journal. An agent
(me) designed and started a cutover before surveying, and the owner paid **$51.59/month and hours of
work** before a pre-existing tool was found. Do not repeat that. The register also carries a skill
(`estate-systems`) and `AGENTS.md §0`.

---

## 1. The mission, and what "done" looks like

**Move the company's authority off an unreliable 2013 office desktop and onto a fast, always-on
cloud box — without losing data, with a tested rollback, and without leaving the old system wired in.**

Done means ALL of:
1. `api.abletelsolutions.com` and `ai.abletelsolutions.com` serve from `secratary-cloud`.
2. The database serving them is the company's real, current database (not the stale copy, not a
   rehearsal).
3. The office database is **frozen, not deleted**, and is a working rollback.
4. The row count on the office box has stopped moving (proving no writer survived the freeze).
5. The 90-day retention + FTS conversion is done **after** the switch (see §6).
6. `000-SYSTEMS-REGISTER.md` is updated to say the authority is `secratary-cloud`.

---

## 2. What is ALREADY DONE — do not redo any of this

| # | done | evidence |
|---|---|---|
| 1 | **The new box exists and is fast.** `secratary-cloud`, Hetzner CCX13, Ashburn, `178.156.194.1`, Ubuntu 26.04, 2 vCPU, 7.7 GB, 75 GB **NVMe (~1.1 GB/s write, 813 MB/s read)** | `dd` measured |
| 2 | **It is fully provisioned.** 13 packages, 4 G `/swapfile`, `sshd passwordauthentication no`, `ufw` active (22 only), fail2ban active; `/opt/company` at commit `006cde5a8772848a00c85653a7d2ff9233a51b1d` on `master` (3091 files); venv Python 3.14.4; `pip check` clean; **`import app.main` → `IMPORT_OK`**; `company-api.service` present and its exact ExecStart returned `{"ok":true,…,"database":{"ok":true}}` HTTP 200 in 10 s against a scratch DB | the provisioning workstream's report; re-verify in §5 |
| 3 | **The two-writer hazard is DEFUSED.** `company-api` on the new box is **stopped and DISABLED** (it was `enabled`, so a reboot would have started a writer on a stale copy) | `systemctl is-enabled company-api` → `disabled`, `is-active` → `inactive` |
| 4 | **The offsite backup chain is repaired and guarded.** `push-db-offsite.sh` no longer stages in `/tmp` (RAM tmpfs); the cron path was repointed; a dead 23-day restic lock was cleared; and **a `COMPLETE` marker is now written last by `backup-data.sh` and REQUIRED by both pushers** (9 existing snapshots verify-then-marked) | journal `L3453`, closed pain `P2931` |
| 5 | **The ship rate is measured: 39.7 MiB/s** → the full 23.5 GB ships in **~10 minutes**, so the whole freeze is **~25 min** and the RPO is **~18 MB** | 1024 MiB in 25.73 s |
| 6 | **A cutover executor exists:** `scripts/mesh/cutover-authority.sh` (397 lines, `bash -n` clean). `--stage status` is read-only and WORKS — it confirms the authority is the office box, with 53 `lsof` writer lines. Mutating stages print what they would do and change nothing without `--confirm` | run `--stage status` yourself |
| 7 | **The FTS conversion is proven** (on a throwaway copy): `dsh_session_events_fts` → external-content FTS5 plus `VACUUM` took **21.4 GiB → 13.06 GiB (−39 %)**, `integrity_check` ok, and the search fingerprint was **identical** before and after (`hits('the')=618059`, sample rowids `8,10,11,12,15`). The script is at `secratary-cloud:/root/fts-convert.sh` | its log `/root/fts-convert.log` |
| 8 | **The public door and the switch mechanism are understood** (see §4) | measured |

---

## 3. The machines you will touch

| machine | how to reach it | what it is |
|---|---|---|
| **`secratary-cloud`** | `ssh -i ~/.ssh/id_ed25519_hetzner -o BatchMode=yes root@178.156.194.1` | **the new authority-to-be** |
| **`secratary`** (office) | `secratary-ts` | **the CURRENT authority** — DB, API, dashboard, broker. Be gentle: see §7 trap 2. |
| **`lpt-survivor-01`** | `survivor` | holds the **failover tooling** (`/opt/company/deploy/hosting-migration/scripts/`) and runs the standby |
| **`lpt-apps`** | `lpt-apps` | the vault: R2 credentials, restic "Box 2", the Caddy front door for `*.lakewoodphoneandtech.com` |

⚠️ **The new box has NO tailnet and NO ssh alias on other nodes.** Reach it by public IP with that key.
Adding it to the tailnet is desirable (§8) but is **not** required for the cutover.

---

## 4. The switch mechanism — USE THE EXISTING ONE, DO NOT HAND-ROLL

The company's public door is a Cloudflare tunnel on the office box (`829bc0fb-30f9-4244-b2ea-14fbb61a2753`):

| hostname | origin | moves? |
|---|---|---|
| `api.abletelsolutions.com` | `localhost:8002` — **company API** | **YES** |
| `ai.abletelsolutions.com` | `localhost:3000` — dashboard | **YES** |
| `ai.abletelsolutions.com` `^/phone` | `127.0.0.1:3087` | no |
| `secretary-ssh.abletelsolutions.com` | `ssh://localhost:22` | no |
| `dialer.abletelsolutions.com` | `127.0.0.1:8899` | no |

**The estate already has the tool** — on `lpt-survivor-01`, `/opt/company/deploy/hosting-migration/scripts/`:

- **`company-dns-failover.py`** — `status` (read-only) / `plan --to <tunnel>` / `apply --to` / `revert`.
  Dry-run by default; it saves the previous target **before** its first change; `revert` refuses if
  there is no saved state; `apply` refuses while a previous promotion is unreverted.
- **`company-promote.py`** — the decision layer, with five pre-flight refusals: target tunnel exists;
  it has an ACTIVE CONNECTOR; the standby answers 200 `"mode":"survivor"`; **the primary is NOT
  serving** (two writers); no unreverted prior promotion, plus seed-recency and seed-not-rehearsal.

**⚠️ NEVER run the same tunnel id on two boxes.** Cloudflare would load-balance one hostname across
two different SQLite databases — corruption dressed as redundancy. The scripts exist partly to
prevent this.

### 4.1 ⚠️ THE ONE OPEN DEFECT THAT BLOCKS A PROMOTION

Measured 2026-10-11: the `CF_API_TOKEN` in **`lpt-survivor-01:/opt/company/.env`** reports the standby
tunnel `b69e2492-…` as **"not found in this account"** → 0 connectors, and the promotion therefore
refuses. The token in **`secratary:/home/zabz/personal-secretary-mvp/.env`** listed that same tunnel
as healthy with 4 connectors. **The two tokens differ.**

**Resolve this first**, then re-run `company-promote.py` dry. A token that cannot see its own target
tunnel cannot promote.

**How to load the env without breaking Python** (a real trap — the `.env` contains a malformed
`PYTHONUTF8` that makes Python fail to start if you `source` it):
```bash
export CF_API_TOKEN=$(grep -m1 '^CF_API_TOKEN=' /opt/company/.env | cut -d= -f2-)
export CF_ZONE_ID=$(grep -m1 '^CF_ZONE_ID=' /opt/company/.env | cut -d= -f2-)
export CF_ACCOUNT_ID=$(grep -m1 '^CF_ACCOUNT_ID=' /opt/company/.env | cut -d= -f2-)
```
Then diagnose with the read-only verb only:
```bash
cd /opt/company/deploy/hosting-migration/scripts && python3 company-dns-failover.py status
```

### 4.2 What the dry run said on 2026-10-11 (so you know the baseline)
```
[FAIL] target tunnel exists: b69e2492-… not found in this account          <- §4.1, fix this
[FAIL] target has an active connector: 0 connector(s)
[PASS] no promotion in flight: clean
[FAIL] primary not serving: http 200 - IT IS SERVING                       <- CORRECT, will pass after the freeze
[FAIL] the seed is recent enough: seeded 2026-10-06 (108.9h, limit 26.0h)
[FAIL] the seed is NOT a rehearsal copy: REHEARSAL SEED (company-offsite-drill)
REFUSED. Nothing was changed.
```
**The last two mean the STANDBY was never production-ready** — it runs a rehearsal database. That is
why the office box going off on 2026-10-09 meant a drive to Lakewood despite a "failover system"
existing on paper. It is also why promoting to `secratary-cloud` (which will hold the REAL, current
database) is the right move, and it is NOT a duplicate of the standby.

---

## 5. THE EXECUTION SEQUENCE

Run in this order. **Do not start a stage until the previous stage's SUCCESS test has printed.**

### Stage 0 — Re-verify the handoff is still true (read-only, ~3 min)
```bash
# the office box is still the authority and is serving
ssh secratary-ts 'curl -s --max-time 8 http://127.0.0.1:8002/health | head -c 120; echo; stat -c%s /home/zabz/personal-secretary-mvp/data/secretary.db'
# the new box is provisioned and NOT writing
ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 'systemctl is-enabled company-api; systemctl is-active company-api; df -h / | tail -1; ls -la /root/authority.db'
# the executor's own read-only view
bash scripts/mesh/cutover-authority.sh --stage status
```
**SUCCESS:** the office API answers `{"ok":true…}`; `company-api` is `disabled`/`inactive` on the new
box; the new box has ≥40 GB free.
**If any of that is false, STOP** and re-read `H3403`.

### Stage 1 — Resolve §4.1 (the token), and re-run the promotion dry
**SUCCESS:** `company-promote.py` (dry) no longer fails *"target tunnel exists"* or *"has an active
connector"*. It may still refuse on "primary is serving" and the seed checks — that is expected and
correct at this point.

### Stage 2 — Point the new box's tunnel at itself (do not move DNS yet)
Create/choose a tunnel for `secratary-cloud` with ingress `api. → localhost:8002`,
`ai. → localhost:3000`; run it as a service there; **do not touch DNS**. Verify that tunnel shows an
**active connector** in the Cloudflare API. This is the check that would have caught the 403.

### Stage 3 — FREEZE (the clock starts; target ≈25 min, hard ceiling 45)
Stop **every** writer, then **PROVE IT WITH `lsof` — never with a `systemctl` exit code.**
```bash
bash scripts/mesh/cutover-authority.sh --stage freeze --confirm
```
Then, independently of the script:
```bash
ssh secratary-ts 'sudo lsof /home/zabz/personal-secretary-mvp/data/secretary.db | wc -l'
```
**SUCCESS = 0.** Then **wait one full cron period (6 min) and check again** — `secretary-startup`
runs `*/5`, and `secretary-api-watchdog.timer` + `secretary-access-watchdog.timer` +
`secretary-backup.timer` can restart a writer underneath a naive "stop the unit". On 2026-10-11 the
measured writer set was: `secretary-api`, `dialpad-sms-ws`, `secretary-dashboard`, `phone-engine`,
`mesh-broker`, `cloudflared` (leave `cloudflared` and `tailscaled` up), and the units held the DB with
distinct PIDs; **discover the set by `lsof`, never assume it.**
**If `lsof` is not 0 after the 6-minute re-check: ABORT (§9) — do not continue.**

### Stage 4 — The copy (~10 min at 39.7 MiB/s)
A **consistent** snapshot, never a raw `cp` of a live SQLite file:
```bash
ssh secratary-ts "sqlite3 /home/zabz/personal-secretary-mvp/data/secretary.db \".backup '/home/zabz/cutover-final.db'\""
```
Ship it office → new box (the office box holds `id_ed25519_hetzner` and the new box accepts it):
```bash
ssh secratary-ts "cat /home/zabz/cutover-final.db | gzip -1 | \\
  ssh -i /home/zabz/.ssh/id_ed25519_hetzner -o BatchMode=yes root@178.156.194.1 \\
  'gunzip > /root/authority.db.new'"
```
**The office box must PUSH** — the new box has no tailnet and no key for the office box.

### Stage 5 — VERIFY BEFORE ANYTHING POINTS AT IT
Compare source and copy. **All must match** (the copy is of the UNCONVERTED database, so byte and page
counts are comparable — do NOT compare against the stale 14 GB `/root/authority.db`, which was
converted and is irrelevant):
| check | office | new copy |
|---|---|---|
| file bytes | | |
| `PRAGMA page_count` | | |
| table count | | |
| `SELECT count(*) FROM dsh_session_events` | | |
| **FTS fingerprint**: `SELECT count(*) FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH 'the'` | | |

```bash
bash scripts/mesh/cutover-authority.sh --stage verify
```
**A copy that has not been compared to its source is not a copy.** Any mismatch → §9 rollback.

### Stage 6 — SWITCH
```bash
mv /root/authority.db.new /root/authority.db        # only after Stage 5 passes
systemctl start company-api                          # (re-enable only after the switch is verified)
curl -s http://127.0.0.1:8002/health                 # its OWN loopback, its own {"ok":true} shape
```
Then move the names **through the existing script** — never by hand:
```bash
# on lpt-survivor-01, with the token from §4.1 resolved
python3 company-promote.py --to <new-tunnel-id> --standby-url http://127.0.0.1:8002 --apply
```
It will refuse if the primary is still serving — which is exactly why Stage 3 must have passed.

### Stage 7 — Post-switch verification
```bash
curl -s https://api.abletelsolutions.com/health    # 200, the company API's shape
curl -s https://ai.abletelsolutions.com/health
ssh secratary-ts 'stat -c%s /home/zabz/personal-secretary-mvp/data/secretary.db'   # run twice, 10 min apart
```
**The office size must be IDENTICAL across the two readings.** If it changed, a writer survived the
freeze — **stop and re-read §3**, then `company-promote.py` revert. Re-check at +1 h, +24 h, +7 d.

### Stage 8 — Leave the office box ALONE for a week
**Frozen, never deleted.** It is the rollback anchor. §9 is still valid for the whole week.

---

## 6. AFTER the switch (do this in a separate, calm session)

**Do NOT do this inside the freeze.** The conversion measured **38 minutes**; inside the freeze it
would take the window from ~25 to ~63 minutes for an optimisation that is not required for correctness.

On `secratary-cloud`, once it is serving and idle:
1. **90-day archive-and-prune** (owner decision, recorded): rows of `dsh_session_events` older than 90
   days are exported to Cloudflare R2 and pruned from the live table. **The owner's policy: keep ALL
   DSH and Copilot sessions FOREVER, but only 90 days live and indexed.** Nothing is ever deleted — the
   raw archive `/home/zabz/lpt-transcripts` and R2 hold everything.
2. **The FTS conversion** — `/root/fts-convert.sh` on the new box, proven: −39 %, identical
   fingerprints.

---

## 7. TRAPS — each of these has already cost this estate something

1. **A public hostname is not the machine you think.** `api.lakewoodphoneandtech.com` is the
   **phone-and-tech business** API (Caddy on `lpt-apps` → `lpt-backend:3001`), **NOT** the company API.
   The company's is `api.abletelsolutions.com`. Resolve the name and match the response shape before
   reporting a machine's health — a wrong-host `uptime` reading sent the owner to the office.
2. **NEVER run `dbstat`, a recursive `du`, a full-table scan, or `.backup` of the large DB on the
   OFFICE box.** It saturates the disk, stalls **sshd**, and takes the machine off the network while
   `tailscale ping` still answers. It has been done three times and broke it every time. All heavy DB
   work goes on `secratary-cloud`.
3. **`/tmp` on the office box is a 12 GB RAM-backed tmpfs.** Never stage a multi-GB file there. (P2892.)
4. **The office NIC CANNOT wake the machine.** `ethtool eno1` reports **no `Wake-on:` line at all**
   (Intel I217-LM / e1000e) and `ethtool -s eno1 wol g` is a silent no-op. **If it powers off, someone
   drives to Lakewood.** Never leave it as the only copy of anything.
5. **`subagent` defaults to FOREGROUND and blocks the turn.** Pass `run_in_background: true`.
   `subagent_fork` defaults to background.
6. **Exit 127 from a cron job means the SCRIPT MOVED** — check the path before believing anything
   about the job.
7. **Byte-count verification proves the TRANSPORT, never the CONTENT.** An interrupted backup uploads
   faithfully and reports OK. Hence the `COMPLETE` marker.
8. **systemd `EnvironmentFile=` OVERRIDES `Environment=` by key.** A drop-in setting a var the
   `EnvironmentFile` also sets is dead code. Put it in the `.env`.
9. **The company repo is private.** A fresh box cannot clone it; use a git bundle from a workstation.

---

## 8. Desirable, not blocking

- **Join `secratary-cloud` to the tailnet** (needs an auth key, **key expiry disabled** — an expiring
  key silently leaves the mesh forever) and add the ssh alias to **every** node. Today the new box is
  reachable only by public IP and is not in the fleet's reach.
- **Move `push-db-offsite.sh` and `company-offsite-push.sh` to the new box** and remove them from the
  office box, so the backup runs where the data is.
- **Install the dashboard + `mesh-broker` units** on the new box (neither is there yet).
- **Deploy the placement failover** (`packages/plugin-remote-fanout/lib/failover-placer.js`) — proven
  by test and by a live dispatch with a dead broker, but the resident engines still run the old code
  because a mounted bundle loads at boot (P210). Needs one engine restart per node.
- **Seed `lpt-survivor-01` with REAL data** so the standby becomes a genuine second line rather than a
  rehearsal.
- **Open, unfixed, and found 2026-10-10:** two cron jobs point at files that no longer exist
  (`order-feed-refresh`, `text-line-check`); `cron-target-guard.py` reports `ok / 0 missing` because it
  never decodes the crontab's base64 (a guard that cannot fail); `docs/mesh/` has **two files numbered
  119**; P2934 (the standby's rehearsal seed).

---

## 9. ROLLBACK — valid from the moment you freeze, for a week

| if you stopped at… | do this | time |
|---|---|---|
| Stage 3 (freeze) | `ssh secratary-ts "sudo systemctl unmask secretary-api.service dialpad-sms-ws.service; sudo systemctl start secretary-api dialpad-sms-ws; systemctl list-timers --all \| grep secretary"` — restore every unit and timer you masked | ~1 min |
| Stage 5 (copy/verify failed) | `rm -f /root/authority.db.new` on the new box. The office DB was never touched. | seconds |
| Stage 6 (after DNS moved) | `python3 company-dns-failover.py revert` on `lpt-survivor-01` — it restores the saved previous target and refuses if there is no saved state | ~1 min |
| anything | **the office database was never modified at any stage.** That is the whole point of the design. | |

**The office box is not to be deleted, wiped, re-provisioned or "cleaned up" for at least a week
after a successful cutover.**

---

## 10. Where everything is written down

| what | where |
|---|---|
| **the survey rule + the systems register** | `docs/mesh/000-SYSTEMS-REGISTER.md` (**read first**); `presets/zabz/skills/estate-systems/SKILL.md`; `AGENTS.md §0` |
| the full cutover runbook (longer, older) | `docs/mesh/126-authority-cutover-runbook.md` |
| the execution plan, and the correction that supersedes its §1 | `docs/mesh/127-cutover-execution-plan.md` |
| the fan-out audit + the office outage | `docs/mesh/119-mesh-fanout-audit.md`, `docs/mesh/120-office-offline.md` |
| the hosting analysis and its recommendation | `docs/mesh/121-always-on-server.md` |
| the mesh state reconciliation / scripts audit | `docs/mesh/123-mesh-state-of-play.md`, `docs/mesh/124-mesh-scripts-audit.md` |
| **the state of play** | `journal.py show H3403`; also `H3401`, `H3402`; pains `P2931` (closed), `P2934` |
| the executor | `scripts/mesh/cutover-authority.sh` |
| the conversion (proven) | `secratary-cloud:/root/fts-convert.sh` |

**Run `python ~/code/harness-config/journal/tools/journal.py status` first, and
`journal.py check` before you finish.**
