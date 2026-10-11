# 126 — Cutting the authority over to `secratary-cloud`: the runbook

**Written 2026-10-09 ≈21:50Z from `zabz-tech`** (hostname `ZABZ-TECH`), branch `main` at `b84fa97`.
**This document SUPERSEDES `122-cloud-authority-provision.md`.** Where the two disagree, this one is right;
§0 says why, item by item, with the measurement that killed each line. **Provenance:** **MEASURED** = I ran
the command in this session, and the command is given. **READ** = read from a file or git object, with the
path. **ASSERTED** = from the brief, not independently verified. Nothing is carried over without saying so.
**How to run these commands from this node:** on Windows `ssh <host> "<command>"` whose stdout is *piped*
never returns (`PROGRAM.md:100-103`), and Windows quoting mangles a remote script — my own first attempt died
with `bash: -c: line 1: syntax error near unexpected token '('`. Every remote command below was run as
`Start-Process ssh -ArgumentList @(…,'<host>',"echo <base64> | base64 -d | bash") -RedirectStandardOutput <f>`.
**Quote them that way or they will lie to you.**

## 0. Why `122` is stale — one row per claim

| `122` says | true today | how I know |
|---|---|---|
| P1/§1a: Ubuntu **24.04**, and the success check requires it | **Ubuntu 26.04.1 LTS**, kernel `7.0.0-30-generic` | MEASURED `head -3 /etc/os-release; uname -r` on the cloud box |
| §4a: `apt install docker.io docker-compose-v2`, "`docker ps` works"; §4d: deploy from "its own `docker-compose.yml`" | **`docker` is ABSENT on BOTH boxes.** The app is not containerised anywhere: on the office box it is **systemd units + a Python venv** | MEASURED `command -v docker` on both; `systemctl cat secretary-api.service` |
| §5d/§5e: promote to `/home/zabz/personal-secretary-mvp/data/secretary.db` | the cloud box **has no `/home/zabz`**; the copy is `/root/authority.db` | MEASURED `ls -la /root`; `getent hosts` shows only `127.0.1.1` |
| §5e step 1: "stop writers" = `systemctl stop secretary-api` | **that does not stop writes.** A `*/5` cron re-starts the API, and a watchdog timer re-recovers it | MEASURED crontab `*/5 … pgrep -f "uvicorn app.main" \|\| …/secretary-startup.sh`; `secretary-api-watchdog.timer` `OnUnitActiveSec=5min` |
| §5e: the writer is `secretary-api` | **at least two** writer processes hold the file, and a third transient PID appeared between two reads | MEASURED `sudo lsof -nP …/secretary.db`; `cat /proc/1607/cgroup` → `/system.slice/dialpad-sms-ws.service` |
| §4b: `mesh-broker` on the new box "removes today's outage class" | the broker is still **only** on the office box, loopback `:3091`; `122` never says the broker's `nodes.json` roster must move with it | MEASURED `ss -lntp` on both; broker `/healthz` |
| §5c: verify by `integrity_check` **and an equal table count** | an equal table count is now **impossible and would falsely halt the cutover** — the conversion legitimately removes one table | MEASURED: office **231** tables, `authority.db` **230**; the missing name is `dsh_session_events_fts_content` |
| §7: "`db-growth.mjs` is sampling it" | no such script here and no sampler observed; `123 §4.4` could not confirm it either — **treat the growth rate as unmeasured** | MEASURED: absent from this checkout |
| §2: "join the tailnet BEFORE provisioning" | still not joined — `tailscale` is ABSENT on the cloud box, and no `secratary-cloud` ssh stanza exists on this node | MEASURED `command -v tailscale`; `ss -lntp` shows only `22`,`53`; `~/.ssh/config` |
| — (absent from `122`) | `122` never mentions the new box's **swap**, which is **zero** | MEASURED `free -m` → `Swap: 0 0 0` |

**What is NOT stale in `122`, and is kept:** the order (tailnet first), the rule that the office DB is never deleted, the four-part writer switch, and §6's "make it survive" list. Only their commands were wrong.

## 1. The state this runbook starts from (all MEASURED 2026-10-09, 21:30–21:45Z)

| | value | command |
|---|---|---|
| authority | **`secratary` (office) still is.** `uptime` = **3:57** — on for under four hours | `ssh secratary-ts "uptime"` |
| live DB | `…/personal-secretary-mvp/data/secretary.db` = **23,217,270,784 B (21.62 GiB)** + 64 MiB WAL | `stat -c "%s %y %n" …/secretary.db*` |
| live DB internals | `page_size 4096`, `page_count 5,668,279`, **231** tables, `max(rowid) dsh_session_events` = **1,821,128** | `sqlite3 … "PRAGMA page_size; PRAGMA page_count; SELECT max(rowid) FROM dsh_session_events;"` |
| the big table | `dsh_session_events(source_machine, session_id, ordinal, seq, type, raw, created_at, PRIMARY KEY(source_machine,session_id,ordinal))`; **`created_at` is nullable and has NO index** | `SELECT sql FROM sqlite_master WHERE name='dsh_session_events'` |
| live FTS | `USING fts5(source_machine UNINDEXED, session_id UNINDEXED, ordinal UNINDEXED, raw)` — **contentless**, keeps its own `_fts_content`. **No triggers on `dsh_session_events`** | same |
| writers | `secretary-api.service` (uvicorn `0.0.0.0:8002`), `dialpad-sms-ws.service`, `secretary-dashboard.service` (`:3000`), `phone-engine.service` (DSH engine `127.0.0.1:3089`) | `systemctl list-units --state=running`; `sudo lsof` |
| restart paths that defeat a freeze | the `*/5` `secretary-startup` cron, `secretary-api-watchdog.timer` (5 min), `secretary-access-watchdog.timer`, `secretary-backup.timer` (00:00) | `crontab -l`; `systemctl list-timers --all` |
| public ingress | `cloudflared.service`, tunnel `829bc0fb-30f9-4244-b2ea-14fbb61a2753`, `/etc/cloudflared/config.yml`: `ai.abletelsolutions.com`→`:3000`, `api.`→`:8002`, `secretary-ssh.`→`:22`, `dialer.`→`:8899` | `systemctl cat cloudflared`; `cat /etc/cloudflared/config.yml` |
| tailnet ingress | `tailscale serve`: `https://secratary.tail93e6e6.ts.net` → `/` `:3086`, `/vehicle` `:8002` | `tailscale serve status` |
| **WoL** | `ethtool eno1` prints **Speed** and **Link detected** and **no `Wake-on:` line at all**; driver `e1000e`, NIC `Intel I217-LM`. `ethtool -s eno1 wol g` is a silent no-op (ASSERTED) | `ethtool eno1 \| grep -iE "wake\|nic\|link"` |
| R2 | bucket **`lpt-authority-backups`**, creds `~/.lpt-r2.env` (600), objects `authority/secretary.db.gz` + `authority/accounting.db.gz`, pushed daily 05:10 by `~/bin/push-db-offsite.sh` (`python3.14` + `boto3 1.40.72`) | `grep ^R2_BUCKET ~/.lpt-r2.env`; `head -40 ~/bin/push-db-offsite.sh` |
| **target DB** | `/root/authority.db` = **14,023,524,352 B (13.06 GiB)**, `page_size 4096`, `page_count 3,423,712`, **230** tables, `max(rowid)` = **1,797,992**, **no WAL** | `ls -la /root/authority.db*`; `sqlite3 /root/authority.db "PRAGMA page_size; PRAGMA page_count;"` |
| target conversion | **finished 20:05:27Z, verdict `ok`**, fingerprints identical (`rows=1797992 fts_docs=1797992 hits(the)=618059 ids=8,10,11,12,15`), `VACUUM` reclaimed to 13.06 GiB, `integrity_check` = `ok` | `cat /root/fts-convert.out` |
| target box | 2 vCPU, **7742 MiB**, `/dev/sda1` 75 G, **15 G used / 58 G avail / 21 %**, **no swap**, `ufw` **inactive**, `sshd -T` reports **`passwordauthentication yes`** | MEASURED this session |
| **the delta** | target is the 12:00Z snapshot (`max(rowid)` 1,797,992) against the office's **1,821,128**: **≈23,136 new event rows**, plus every other table's ~10 h of change | the two `max(rowid)` readings |

**The composition defect this plan exists to fix:** the corpus was stored **twice** — `dsh_session_events.raw` 7.28 GB *and* the contentless FTS's `fts_content` 7.20 GB — because the virtual table was created without `content=` (READ, `fts-convert.sh` header). That is why the converted copy is 13.06 GiB against the source's 21.62 GiB. **The 10 GB difference is reclaimed duplication, not missing data.**

## 2. Safety properties — non-negotiable

1. **The office database is FROZEN, never deleted, and is the rollback for at least seven days.** No
   `VACUUM`, prune, `DROP` or overwrite on `secratary` until the new box has served a week cleanly. *A
   replica that can write has become a second company* (`112-single-source-of-truth.md`).
2. **Exactly one writer at a time; during the freeze, zero.** "I stopped the unit" is not the test —
   **`lsof` on the file is**, and it must be empty *after one full cron period*.
3. **Nothing points at the copy until it has been compared to the source** on three axes: the table-list
   diff (with the one expected difference named), the page geometry, and the search fingerprint.
4. **Never two tunnel connectors.** A second `cloudflared` while the first is up round-robins the public
   hostname between two databases. Stop the office connector, verify it stopped, *then* start the new one.
5. **The new API binds loopback only.** The office unit says `--host 0.0.0.0`; copying it verbatim onto a box
   with a public IPv4 publishes the company API to the internet.
6. **Prune only after the cutover, never before.** Pruning the office DB destroys the rollback while the new
   box is unproven. The 90-day prune is a *post-cutover* stage **on the new box**.

## 3. RPO / RTO, honestly

| moment | data at risk | rollback time |
|---|---|---|
| today | everything since the 12:00Z R2 push — **up to 24 h** (`push-db-offsite.sh` header states the RPO) | n/a |
| after Stage 3 (seed verified) | still everything since 12:00Z; the new box is a copy, not authority | n/a, nothing changed |
| during the freeze (Stage 4) | **writes that arrive while writers are stopped are lost.** At the measured **≈0.70 MB/min** (23,217,270,784 − 23,138,103,296 over ≈113 min), a 45-min freeze defers **≈30 MB** of events | ≤5 min of commands **plus however long a human needs to reach the office** — the NIC reports no `Wake-on:` at all, so a powered-off box is a drive to Lakewood |
| at the switch instant | **≈0**: writers are frozen, so source and target hold the same rows | stop the cloud units, restart the office ones, revert ingress: **2–5 min** (`secretary-api` boot is 2–4 min by its own unit comment, `TimeoutStartSec=600`) |
| **during Stage 9 (archive-and-prune)** | **the only step that can lose data permanently.** Rows are deleted from live; recovery depends entirely on the R2 object | restore from R2 + re-import: **hours** (13 GB object) — so the archive is verified *by restore* before the first `DELETE` |
| after one clean week | the office DB may be repurposed; the R2 nightly dump becomes the only history | days if the office disk is wiped |

**The unmeasured number that decides the freeze window: the office→Ashburn ship rate.** I did not measure it (a probe writes a file to the cloud box, which this workstream may not do). **Measure it with a 1 GB `rsync --progress` probe before scheduling the freeze** and compute the window as `23.3 GB ÷ measured rate`.

## 4. Stages

Each stage has commands, a **SUCCESS** test on raw output, and a **ROLLBACK**. Do not start stage *n+1* until
stage *n*'s success test passes.

### Stage 0 — Pre-flight refusals (nothing is changed)

```bash
ssh secratary-ts "hostname; uptime; df -h / | tail -1"                                  # office is up, and since when
ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 \
  "hostname; nproc; free -m|head -2; df -h /|tail -1; tail -3 /root/fts-convert.out"     # target, and its verdict
ssh secratary-ts "head -c 1073741824 /dev/zero | ssh root@<cloud-ts-ip> 'cat >/root/.probe && rm -f /root/.probe'"   # time this
```
**SUCCESS:** `secratary` reachable; the cloud prints `secratary-cloud`, 2 cores, ≈7742 MiB, ≥40 G avail and
`verdict=ok`; a human is on site for the rollback window; the probe gives a rate you can divide into 23.3 GB.
**ROLLBACK:** nothing changed — stop here.

### Stage 1 — Provision: tailnet, packages, runtime, app tree, units

The order is forced: the tailnet first, because the provisioner fetches `package-lock.json` *from the authority* and a brand-new VPS is on neither the LAN nor the tailnet (`122 §2`, still correct).

```bash
# 1a. tailnet (authkey; key expiry DISABLED in the admin console - 79 §1.3 step 7)
ssh root@178.156.194.1 "curl -fsSL https://tailscale.com/install.sh | sh && \
  tailscale up --authkey=<KEY> --hostname=secratary-cloud --accept-routes=false"
# 1b. the ssh alias 122 P3 promised and never created: Host secratary-cloud / HostName <ts-ip> / User root
# 1c. base packages, hardening, and SWAP (the box has none, and the DB is 13 GB)
ssh secratary-cloud "apt-get update && apt-get install -y python3-venv python3-pip sqlite3 rsync zstd gzip fail2ban ufw && \
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile"
ssh secratary-cloud "sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && systemctl reload ssh"
ssh secratary-cloud "ufw allow 22/tcp; ufw allow in on tailscale0; ufw --force enable"
# 1d. worker runtime + DSH engine + gate, from the proven provisioner (73 §1.2)
bash scripts/provision-mesh-node.sh --check secratary-cloud
bash scripts/provision-mesh-node.sh secratary-cloud
# 1e. the app: venv + tree + env, mirroring the office systemd deploy (NOT docker)
ssh secratary-cloud "git clone <app-repo> /home/zabz/personal-secretary-mvp && cd /home/zabz/personal-secretary-mvp && \
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
# 1f. the units, copied from the office and AMENDED: --host 127.0.0.1 (not 0.0.0.0), DB path /root/authority.db until Stage 6
scp secratary-ts:/etc/systemd/system/{secretary-api,secretary-dashboard,mesh-broker}.service /tmp/
# 1g. the broker, via its own idempotent installer (it hashes the deployed copy, not the exit code)
sudo bash packages/mesh-broker/deploy/install-authority.sh
```
**SUCCESS:** `tailscale status | grep secratary-cloud` present and not offline; `dsh --version` runs; the
provisioner exits `0`; `systemctl is-active mesh-broker` = active and `curl -s 127.0.0.1:3091/healthz` reports
the roster; `sshd -T | grep passwordauthentication` = **no**; `swapon --show` non-empty.
**ROLLBACK:** `hcloud server delete secratary-cloud` — Hetzner bills hourly and a rebuild is ~3 min ≈1¢
(`79 §3.1`). Nothing on the office box was touched.

### Stage 2 — The seed: consistent snapshot, then ship

```bash
# 2a. a CONSISTENT copy of a HOT sqlite database - never `cp`
ssh secratary-ts "mkdir -p /home/zabz/cutover && sqlite3 -cmd '.timeout 60000' \
  /home/zabz/personal-secretary-mvp/data/secretary.db \".backup '/home/zabz/cutover/seed.db'\" && \
  sqlite3 /home/zabz/cutover/seed.db 'PRAGMA integrity_check;'"
# 2b. ship node-to-node over the tailnet (NOT through this laptop - that is two hops)
ssh secratary-ts "rsync -a --partial --info=progress2 /home/zabz/cutover/seed.db root@secratary-cloud:/root/cutover/seed-src.db"
```
**SUCCESS:** `integrity_check` = `ok`; rsync exits `0` **and** the byte size matches on both ends —
`scp -r` exits 0 on a no-op and this estate lost an hour to exactly that (`76 §6.4`).
**ROLLBACK:** delete `/home/zabz/cutover/seed.db` on the office box. It is a copy; the live DB is untouched.

### Stage 3 — Verify the seed has the shape you think

```bash
ssh secratary-ts    "sqlite3 /home/zabz/cutover/seed.db \"PRAGMA integrity_check; PRAGMA page_size; PRAGMA page_count; \
  SELECT count(*) FROM sqlite_master WHERE type='table'; SELECT count(*) FROM dsh_session_events; SELECT sum(length(raw)) FROM dsh_session_events;\""
ssh secratary-cloud "sqlite3 /root/cutover/seed-src.db \"PRAGMA integrity_check; PRAGMA page_size; PRAGMA page_count; \
  SELECT count(*) FROM sqlite_master WHERE type='table'; SELECT count(*) FROM dsh_session_events; SELECT sum(length(raw)) FROM dsh_session_events;\""
ssh secratary-ts    "sqlite3 /home/zabz/cutover/seed.db \"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;\"" > $env:TEMP\tbl.a.txt
ssh secratary-cloud "sqlite3 /root/cutover/seed-src.db \"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;\"" > $env:TEMP\tbl.b.txt
diff $env:TEMP\tbl.a.txt $env:TEMP\tbl.b.txt      # both sides are PRE-conversion: expect NO difference
```
**SUCCESS:** `integrity_check` = `ok` both sides; `page_size` 4096 both; **equal** `count(*)` and **equal**
`sum(length(raw))` on `dsh_session_events` — a content fingerprint, stronger than a row count because it
catches truncated text; and the table lists compare equal, since neither side is converted yet.
**ROLLBACK:** re-ship. Nothing has been converted in place.

### Stage 4 — The DELTA: freeze writers, re-copy, prove the freeze held

The target is the **12:00Z** snapshot: `max(rowid)=1,797,992` against the office's `1,821,128` (§1). Ten
hours of history are missing — and **freezing is harder than it looks**: five separate things restart a
writer behind the operator's back. Freeze all of them, prove it, then wait a full cron period.

```bash
# 4a. neutralize the auto-restarter FIRST. `systemctl stop` alone is defeated within 5 minutes, and
#     secretary-startup.sh KILLS and re-launches uvicorn itself - it is not even a systemd restart.
ssh secratary-ts "crontab -l > /home/zabz/cutover/crontab.before; crontab -l | grep -v 'secretary-startup' | crontab -; \
  crontab -l | grep -c secretary-startup"
# 4b. stop and MASK the writers, plus the watchdogs whose whole job is to un-stop them
ssh secratary-ts "sudo systemctl stop secretary-api-watchdog.timer secretary-access-watchdog.timer; \
  sudo systemctl mask --now secretary-api.service dialpad-sms-ws.service; \
  sudo systemctl stop secretary-dashboard.service phone-engine.service"
# 4c. THE SUCCESS TEST - not the systemctl exit code, the file itself
ssh secratary-ts "sudo lsof -nP /home/zabz/personal-secretary-mvp/data/secretary.db | wc -l; pgrep -af 'uvicorn app.main|dialpad_sms_ws'"
# 4d. WAIT ONE FULL CRON PERIOD, then repeat 4c. A freeze that survives its own cron is a freeze.
sleep 360; ssh secratary-ts "sudo lsof -nP /home/zabz/personal-secretary-mvp/data/secretary.db | wc -l; \
  stat -c '%s %y' /home/zabz/personal-secretary-mvp/data/secretary.db"
# 4e. only now: the final consistent snapshot, and the row count at the freeze instant
ssh secratary-ts "sqlite3 /home/zabz/personal-secretary-mvp/data/secretary.db 'PRAGMA wal_checkpoint(TRUNCATE);'; \
  sqlite3 -cmd '.timeout 60000' /home/zabz/personal-secretary-mvp/data/secretary.db \".backup '/home/zabz/cutover/final.db'\"; \
  sqlite3 /home/zabz/cutover/final.db 'PRAGMA integrity_check; SELECT max(rowid) FROM dsh_session_events;'"
# 4f. ship it, then CONVERT IT with the proven script - never in place on the serving copy
ssh secratary-ts "rsync -a --partial --info=progress2 /home/zabz/cutover/final.db root@secratary-cloud:/root/cutover/final-src.db"
ssh secratary-cloud "DB=/root/cutover/final-src.db LOG=/root/cutover/final-convert.log bash /root/fts-convert.sh"
```
**SUCCESS:** 4c and 4d both show **no process holding the DB** and an **unchanged** `stat` size/mtime across
the 6-minute wait; `integrity_check` = `ok`; `max(rowid)` on `final.db` equals the live maximum; the rsync
sizes match; `fts-convert.log` ends `verdict=ok` with matching fingerprints.
**ROLLBACK:** `sudo systemctl unmask secretary-api.service dialpad-sms-ws.service && sudo systemctl start
secretary-api secretary-dashboard phone-engine dialpad-sms-ws && crontab /home/zabz/cutover/crontab.before`
— the estate is back on the office DB in **2–5 min** and no data moved.

**Why re-convert instead of a row-level delta.** Source and target differ *by schema*, not just by rows: the
target's FTS is external-content over `dsh_session_events` with **no sync triggers** (§1); the source's is
contentless with its own `_fts_content`. A row-level `ATTACH … INSERT … WHERE rowid > 1797992` delta is
possible but must also hand-maintain the FTS index, and be correct for **all 230 other tables**, several of
which are mutable (`tasks`, `memories`, `conversations`). Re-running the *proven, fingerprinted* converter on
a frozen snapshot is deterministic and cheap: **38 minutes wall clock on the real corpus**. Take the 38
minutes; do not improvise an FTS delta at 2 a.m.

### Stage 5 — Verify the final copy against the source, BEFORE anything points at it

```bash
ssh secratary-ts    "sqlite3 /home/zabz/cutover/final.db \"PRAGMA integrity_check; PRAGMA page_size; PRAGMA page_count; \
  SELECT count(*) FROM dsh_session_events; SELECT sum(length(raw)) FROM dsh_session_events; SELECT max(rowid) FROM dsh_session_events;\""
ssh secratary-cloud "sqlite3 /root/cutover/final-src.db \"PRAGMA integrity_check; PRAGMA page_size; PRAGMA page_count; \
  SELECT count(*) FROM dsh_session_events; SELECT sum(length(raw)) FROM dsh_session_events; SELECT max(rowid) FROM dsh_session_events;\""
# the SEARCH FINGERPRINT - identical, or the conversion is WRONG
ssh secratary-ts    "sqlite3 /home/zabz/cutover/final.db \"SELECT count(*) FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH 'the'; \
  SELECT group_concat(rowid) FROM (SELECT rowid FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH 'the' LIMIT 5);\""
ssh secratary-cloud "sqlite3 /root/cutover/final-src.db \"SELECT count(*) FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH 'the'; \
  SELECT group_concat(rowid) FROM (SELECT rowid FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH 'the' LIMIT 5);\""
# a hit must still return the RIGHT text, joined through the content rowid
ssh secratary-cloud "sqlite3 /root/cutover/final-src.db \"SELECT substr(e.raw,1,70) FROM dsh_session_events_fts f \
  JOIN dsh_session_events e ON e.rowid=f.rowid WHERE f.dsh_session_events_fts MATCH 'the' LIMIT 2;\""
# the ONE expected table-list difference, proven and named
ssh secratary-ts    "sqlite3 /home/zabz/cutover/final.db \"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;\"" > $env:TEMP\tbl.src.txt
ssh secratary-cloud "sqlite3 /root/cutover/final-src.db \"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;\"" > $env:TEMP\tbl.conv.txt
diff $env:TEMP\tbl.src.txt $env:TEMP\tbl.conv.txt     # exactly one line: < dsh_session_events_fts_content
# promote, and get the WAL out of the way
ssh secratary-cloud "sqlite3 /root/cutover/final-src.db 'PRAGMA journal_mode=DELETE;' && \
  mv /root/cutover/final-src.db /root/authority.db && ls -la /root/authority.db*"
```
**SUCCESS — all of these, or stop:** `integrity_check` = `ok`; **equal** `count(*)`, **equal**
`sum(length(raw))`, **equal** `max(rowid)`; **equal** MATCH hit count and **equal** sample rowids; the table
diff is one named line; and `page_count × page_size = file size` to the byte on both files.
**ROLLBACK:** `rm -f /root/authority.db` on the cloud. The office DB is untouched and still frozen.

### Stage 6 — The switch

```bash
# 6a. point the app at the new file, then start it - LOOPBACK, not 0.0.0.0
ssh secratary-cloud "sed -i 's|--host 0.0.0.0|--host 127.0.0.1|' /etc/systemd/system/secretary-api.service && \
  systemctl daemon-reload && systemctl start secretary-api && sleep 20 && curl -s -m 10 http://127.0.0.1:8002/health"
# 6b. a write on the new authority, and the proof it did NOT appear on the office box
ssh secratary-cloud "curl -s -m 10 -X POST http://127.0.0.1:8002/<a-real-write-endpoint>"
ssh secratary-cloud "sqlite3 /root/authority.db 'SELECT max(rowid) FROM dsh_session_events;'"
ssh secratary-ts    "sqlite3 /home/zabz/personal-secretary-mvp/data/secretary.db 'SELECT max(rowid) FROM dsh_session_events;'"   # OLD number
# 6c. publish on the tailnet first - DNS-free and instantly reversible
ssh secratary-cloud "tailscale serve --bg --https=443 http://127.0.0.1:8002"
curl -s -m 10 https://secratary-cloud.tail93e6e6.ts.net/health
# 6d. the Cloudflare tunnel LAST, and NEVER with two connectors up
ssh secratary-ts "sudo systemctl stop cloudflared && sudo systemctl is-active cloudflared"     # must say inactive
scp secratary-ts:/etc/cloudflared/config.yml /tmp/cloudflared.new.yml
scp secratary-ts:/home/zabz/.cloudflared/829bc0fb-30f9-4244-b2ea-14fbb61a2753.json root@secratary-cloud:/root/.cloudflared/   # tailnet only
ssh secratary-cloud "systemctl start cloudflared && curl -s -m 10 https://api.abletelsolutions.com/health"
```
**SUCCESS:** `/health` answers `{"ok":true,…}` **from the cloud's own loopback**; the canary write advances
the cloud's `max(rowid)` while the office's `max(rowid)` is **unchanged**; the tailnet URL answers; after the
tunnel move `https://api.abletelsolutions.com/health` answers **and** a fresh canary row is visible through
it, proving the public path lands on the cloud; `cloudflared` on the office is **inactive**.
**ROLLBACK:** `ssh secratary-cloud "systemctl stop secretary-api; systemctl stop cloudflared; tailscale serve --https=443 off"`,
then `ssh secratary-ts "sudo systemctl unmask secretary-api dialpad-sms-ws; sudo systemctl start cloudflared
secretary-api secretary-dashboard phone-engine dialpad-sms-ws; crontab /home/zabz/cutover/crontab.before"`.
**RTO 2–5 min**, because the office file never changed.

**The tunnel is the sharp edge, said plainly.** One tunnel, one connector, one database. Two connectors
load-balance the public hostname between two SQLite files and the company has two brains (§2.4). And because
one tunnel's ingress also serves `dialer.`, `secretary-ssh.` and the `/phone` redirector whose backends
**stay on the office box**, the honest options are: (a) keep the office connector up for those hostnames and
create a **second tunnel** for `api.`/`ai.`, which needs a DNS record change for those two names — the
owner's step, with the old record written down as the rollback; or (b) move those backends too, which is a
different project. **Do not do a partial config move and call it done.**

### Stage 7 — Post-switch verification (+1 h, +24 h, +7 d)

```bash
curl -s -m 10 https://secratary-cloud.tail93e6e6.ts.net/health                                          # it answers
ssh secratary-cloud "hostname; sqlite3 /root/authority.db 'PRAGMA integrity_check;'; systemctl is-active secretary-api mesh-broker"
ssh secratary-cloud "sqlite3 /root/authority.db \"SELECT count(*) FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH 'the';\""   # search still works
ssh secratary-cloud "curl -s http://127.0.0.1:3091/nodes?fresh=1 | head -c 300"                          # broker roster
ssh secratary-ts "stat -c '%s %y' /home/zabz/personal-secretary-mvp/data/secretary.db; sqlite3 /home/zabz/personal-secretary-mvp/data/secretary.db 'SELECT max(rowid) FROM dsh_session_events;'"
```
**SUCCESS:** `/health` ok; `integrity_check` = `ok`; the office `stat` mtime and `max(rowid)` are **identical
to the Stage 6b reading** at +1 h, +24 h and +7 d; the MATCH count is non-zero and stable; the broker names
every node that answers. **A changed office number means a writer survived the freeze: stop, re-read §2.2.**
**ROLLBACK:** Stage 6's rollback, still valid for the whole week.

### Stage 8 — Keep the office box as the rollback anchor

```bash
ssh secratary-ts "sudo systemctl mask secretary-api.service dialpad-sms-ws.service; \
  sudo systemctl stop cloudflared secretary-dashboard phone-engine mesh-broker; \
  chmod a-w /home/zabz/personal-secretary-mvp/data/secretary.db; ls -la /home/zabz/personal-secretary-mvp/data/secretary.db"
```
**SUCCESS:** the office DB is present, its mtime is the Stage 6b instant, and it is not writable.
**ROLLBACK:** none needed — **this stage is the rollback.** Do not delete anything on this box for a week.

### Stage 9 — The 90-day archive-and-prune (on the NEW box, after the cutover)

Owner's decision: keep **all** sessions forever, but only **90 days live and indexed**. The archive target is
the bucket that already holds `authority/secretary.db.gz`: `lpt-authority-backups`, via the credentials and
the pattern of `~/bin/push-db-offsite.sh` (`boto3`, `~/.lpt-r2.env` mode 600).

```bash
# 9a. what WOULD be pruned - count it before deleting anything. NULL created_at rows are KEPT, not guessed at.
ssh secratary-cloud "sqlite3 /root/authority.db \"SELECT count(*) FROM dsh_session_events WHERE created_at IS NOT NULL AND created_at < datetime('now','-90 days');\""
ssh secratary-cloud "sqlite3 /root/authority.db \"SELECT count(*) FROM dsh_session_events WHERE created_at IS NULL;\""
# 9b. archive them as insert statements, compressed, BEFORE any DELETE
ssh secratary-cloud "sqlite3 /root/authority.db <<'SQL' | zstd -T0 -3 > /root/archive-90d.sql.zst
.mode insert dsh_session_events
SELECT * FROM dsh_session_events WHERE created_at IS NOT NULL AND created_at < datetime('now','-90 days');
SQL"
ssh secratary-cloud "sha256sum /root/archive-90d.sql.zst"
# 9c. THE RESTORE DRILL - a backup you have not restored is a hope.
ssh secratary-cloud "zstd -dc /root/archive-90d.sql.zst | sqlite3 /root/scratch-restore.db && \
  sqlite3 /root/scratch-restore.db 'SELECT count(*) FROM dsh_session_events;'"
# 9d. only if the restored count equals 9a: upload with boto3, key authority/archive/YYYY/MM/dsh_session_events-<count>-<sha256>.sql.zst
# 9e. the delete, in ONE transaction, and then REBUILD the index - never a per-row FTS delete
ssh secratary-cloud "sqlite3 /root/authority.db <<'SQL'
BEGIN IMMEDIATE;
DELETE FROM dsh_session_events WHERE created_at IS NOT NULL AND created_at < datetime('now','-90 days');
INSERT INTO dsh_session_events_fts(dsh_session_events_fts) VALUES('rebuild');
COMMIT;
SQL"
# 9f. reclaim, verify, record the new baseline
ssh secratary-cloud "sqlite3 /root/authority.db 'VACUUM; PRAGMA integrity_check; PRAGMA page_count;'; \
  sqlite3 /root/authority.db \"SELECT count(*) FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH 'the';\""
```
**SUCCESS:** the restored scratch count **equals** 9a; the R2 object exists with a matching `sha256`; after 9e
the `dsh_session_events` count dropped by exactly that number; `integrity_check` = `ok`; the MATCH count
changed only in the way the removed rows explain.
**ROLLBACK:** re-import the R2 object (`zstd -dc | sqlite3 authority.db`) and `rebuild`. **Hours** — which is
why 9c is mandatory and 9e must not run before 9c passes. **Why prune here and not on the office box:**
pruning the office DB deletes the rollback (§2.6); that copy stays full and frozen for the week.
**Two traps in this stage, both measured.** (1) `created_at` has **no index**, so 9a/9e are full scans of a
7 GB table — budget minutes, and add `CREATE INDEX idx_events_created_at ON dsh_session_events(created_at)`
first if this becomes recurring. (2) The target's FTS is external-content with **no triggers**: a bare
`DELETE FROM dsh_session_events` leaves the index pointing at rowids that no longer exist, so `MATCH` returns
phantom hits whose join is empty. The `'rebuild'` in 9e is what makes the delete correct; a per-row
`'delete'` command is only acceptable if it has been proven on a scratch copy first.

### Stage 10 — Steady state (the part that stops this being another version of today)

```bash
scp secratary-ts:/home/zabz/bin/push-db-offsite.sh root@secratary-cloud:/home/zabz/bin/   # then edit paths
ssh secratary-cloud "systemctl is-active fail2ban ufw unattended-upgrades; swapon --show"
```
**SUCCESS:** a dated object appears in R2 nightly; a watchdog **outside the office** fires within a minute of
the node leaving the tailnet **and names which host answered** (`120 §0`'s error was reading the wrong host's
uptime); `uptime` shows a reboot that happened on purpose (`86`'s reboot never was); `fail2ban`, `ufw` and
unattended upgrades are active.
**ROLLBACK:** none — none of this is load-bearing for the switch.

## 5. WHAT WOULD MAKE ME STOP

1. **A process still holding the office DB after a full cron period** (§4c/4d). Freeze is not a verb you
   perform once; it is a test that keeps passing.
2. **A table-list diff with anything other than `< dsh_session_events_fts_content`.** That one line is
   expected and explained; a second line is an unexplained schema change.
3. **`integrity_check` anything but `ok`**, or **a fingerprint mismatch** — `count(*)`, `sum(length(raw))`,
   `max(rowid)`, MATCH hit count, or the sample rowids. `fts-convert.sh`'s verdict line is the standard.
4. **`page_count × page_size ≠ file size`** on any file: it was truncated in transit.
5. **A second `cloudflared` connector running while the office one is up.** Two connectors, two databases.
6. **The office box powered off with a rollback still owed, and nobody to drive to the office.** `ethtool
   eno1` reports **no `Wake-on:` capability at all** — measured this session — so the rollback is only as fast
   as a human reaching Lakewood. No human available ⇒ the rollback is fiction.
7. **Less than 2× the database size free on the target** before any `VACUUM` or `'rebuild'`. `VACUUM` needs a
   second copy of the file; 58 G avail against a 13 GB DB is fine *now*, and it is the first thing that stops
   being fine.
8. **The measured ship rate pushing the freeze past the agreed window.** Holding writers down for an hour to
   avoid a 40-minute conversion is not a trade; abort and come back in a window where the freeze fits.
9. **A material share of `created_at IS NULL`** in the prune candidate set (9a). If it is not a rounding
   error, the 90-day boundary is not well defined and the prune must not run.
10. **Any instruction to delete, `VACUUM` or prune the office DB before the new box has served seven clean
    days** (§2.6). That is the difference between a cutover and a loss.

## 6. What I could not verify — stated plainly

1. **The office→Ashburn ship rate.** Not measured (a probe writes a file to a box this workstream may not
   write to). The freeze window in §3 is a formula, not a number.
2. **The DB growth rate, and whether it is a runaway writer.** `122 §7` says fix it before moving. The
   `0.70 MB/min` in §3 is arithmetic on **two** of my own readings ≈113 min apart, one day. `121 §2`'s `47×
   in a month` is READ, not re-measured, and `db-growth.mjs` does not exist here.
3. **Whether `created_at` is populated for all recent rows.** I read the column and its nullability; I did
   not count NULLs across 1.8 M rows, because that is a full scan of the live box.
4. **A per-table delta-safe key for each of the other 230 tables.** I verified the diff mechanism on the
   table *list*, not table by table — which is exactly why the plan re-converts a frozen snapshot instead.
5. **Any bandwidth, latency or packet-loss measurement between the office and Ashburn**, including whether
   the tailnet path is direct or relayed.
6. **The Cloudflare DNS records** for `api.`/`ai.abletelsolutions.com` — I read the tunnel's ingress config,
   not the zone. That the move needs a DNS edit is a reasoned conclusion from the connector model (§6), not
   a measurement.
7. **`ethtool -s eno1 wol g` being a silent no-op** — ASSERTED. I verified the stronger fact myself: **no
   `Wake-on:` line is printed at all**, so there is nothing to enable. I did not run the `-s` write, because
   changing NIC settings is outside this task.
8. **The `dialpad-sms-ws` writer's volume, and whether `phone-engine.service` writes `secretary.db`.** I
   identified the former as a writer by `lsof` and its cgroup, and stop the latter in the freeze out of
   caution; I measured neither one's write volume nor its share of the delta.
9. **The identity of the transient third PID** (213082) that `lsof` showed holding the DB between two reads.
   That the writer set is *not fixed* is itself the finding; the freeze's `lsof` check is written to catch
   whatever it is rather than to assume it.
10. **`docs/mesh/119`–`122` are not in this checkout** — they exist on `origin/main` (local `main` is 0 ahead / 23 behind). I read them with `git show origin/main:<path>`; no branch was switched and no tree reset. The filename **`126`** was specified to me; **`125` appears unused in this tree**, so numbering has room to collide with a parallel workstream.
