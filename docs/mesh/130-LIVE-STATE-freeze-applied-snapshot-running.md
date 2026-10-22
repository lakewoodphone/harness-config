# 130 — LIVE STATE: the freeze is applied and held; the snapshot is being taken

**Written 2026-10-11 04:22Z from ZABZ-YOGA. Journal: `H3406` (the 502 incident), `P2936` (the rule
that is a list). Update this file, do not replace it.**

---

## WHERE WE ARE, IN ONE PARAGRAPH

**The office box is FROZEN and the company API is DARK — it has been since 03:04Z, and that is
deliberate.** The freeze is the real one: cron is stopped **and masked**, every writer unit is
stopped **and disabled**, every watchdog timer and its `.service` sibling is stopped and disabled, and
`lsof` on `/home/zabz/personal-secretary-mvp/data/secretary.db` is **0**. A consistent
`sqlite3 .backup` of the 23,622,823,936-byte database is being written to
`secratary-ts:/home/zabz/cutover/office-frozen.db` and is about 14 GB through. **Nothing points at
the cloud box yet. The DNS CNAMEs are untouched. The office database has never been written to by
this work.**

---

## WHAT WENT WRONG BEFORE THAT, AND THE MEASUREMENT THAT DECIDED IT

1. **02:17Z — a self-inflicted outage.** My `data/` pre-stage (14 GB, ~200k files, a bulk read) ran
   on the office box while it was still serving. Load 52 on 4 threads, 77-99 % iowait, sshd silent
   while `tailscale ping` answered, API 502 for 20 minutes. See `H3406` / `P2936`.
2. **The office box was restarted by the owner at ~02:40Z** and came back healthy; that cleared the
   stuck processes.
3. **The freeze then failed FOUR times, each for a different reason, all now fixed in
   `scripts/mesh/cutover-cloud.sh`:**
   - `systemctl mask secretary-api.service` → `Failed to mask unit: File '/etc/systemd/system/
     secretary-api.service' already exists`. **`mask` symlinks the unit NAME in /etc/systemd/system
     and cannot shadow a unit file that already lives there.** `disable` is what works.
   - The **watchdogs restarted the services 90 s after the stop**: `secretary-api` came back
     `ActiveState=active` with a new MainPID. All three timers AND their `.service` siblings must be
     stopped and disabled.
   - **The units are NOT the writer set.** After every unit was down, four free-standing jobs still
     held the database: `presence-runtime/sampler.py`, `store-write-check.py`,
     `/tmp/dialpad-harvest-*.py`, `dialpad-call-fresh.py`. They are spawned by the **crontab — ~90
     jobs whose commands are base64 blobs**, which is also why `cron-target-guard.py` reports
     "ok / 0 missing": it never decodes them. **Stopping cron is the actual boundary.**
   - A `sqlite3 .backup` **wedged**: its output stopped growing at 4,741,529,600 B while its mtime
     kept advancing, because the backup API restarts from the beginning whenever the source changes
     under it, and a new cron writer appeared every few minutes.
4. **Speed, measured, not assumed (this is why the drive question was answered with a number):**
   | measurement | rate |
   |---|---|
   | 2 GB off the office disk, sustained, no network | **98 MB/s** |
   | 500 MB office → Ashburn | **9.8 MB/s** |
   The disk is 10× the wire, so pulling the drive cannot make the crossing faster. The owner chose to
   ship over the wire.

---

## THE EXACT STATE, FOR RESUMPTION

| what | value |
|---|---|
| office frozen at | **03:04Z** first, re-frozen cleanly **04:03:33Z** (`/home/zabz/cutover/snapshot3.log`) |
| freeze proof | `lsof` 0; marker `/home/zabz/cutover/FROZEN` (note: written 03:52:27Z by the earlier run — **regenerate it after the clean snapshot**) |
| snapshot | `secratary-ts:/home/zabz/cutover/office-frozen.db`, in progress, ~14 GB / 23.6 GB |
| cron | **stopped and MASKED** — `systemctl is-active cron` = inactive, `is-enabled` = masked |
| units | `secretary-api`, `dialpad-sms-ws`, `secretary-dashboard`, `phone-engine`, `mesh-broker` — all **stopped and disabled** |
| timers | all three stopped and disabled, with their `.service` siblings |
| crontab | saved at `/home/zabz/cutover/crontab.before`; the `secretary-startup` line stripped |
| cloud box | `company-api` **inactive + disabled**; `cloudflared` active (1 connector, 4 colos); `phone-redirector` active; `secretary-dashboard` active |
| cloud disk | 49 GB free; `DATABASE_URL=sqlite:////root/authority.db` pinned in `/opt/company/.env` |
| DNS | **untouched** — all four hostnames still on `829bc0fb-…` (the office tunnel) |
| rollback | `scripts/mesh/cutover-cloud.sh --stage rollback --confirm` — **it must also stop+unmask cron and re-enable the three timers, or the office box comes back without its clocks** |
| the executor | `secratary-ts:/home/zabz/cutover-cloud.sh` (and `harness-config/scripts/mesh/cutover-cloud.sh`) |

## NEXT, IN ORDER

1. Wait for `snapshot3.log` to print `backup rc=0`, `SIZES EQUAL`, an `integrity_check` line and a
   `max rowid`. **If sizes differ, stop — the snapshot is not the database.**
2. `bash /home/zabz/cutover-cloud.sh --stage copy --confirm` on the office box. It reuses the
   existing snapshot, ships it with **rsync `--partial`** (resumable — do NOT use the gzip|ssh pipe
   for the long haul), and compares byte counts. Expect **~40 minutes** and do not run anything else
   on the office box while it runs.
3. `--stage verify` — read-only, compares the cloud copy to the office snapshot.
4. `--stage switch --confirm` — installs the copy at `/root/authority.db`, starts and enables
   `company-api`, probes loopback.
5. The DNS move, **by hand, on the office box** (it holds the CF credentials), with the token CRLF
   check first (`L3454`):
   ```bash
   cd /home/zabz/cutover-tools
   export CF_API_TOKEN=$(grep -m1 '^CF_API_TOKEN=' /home/zabz/personal-secretary-mvp/.env | cut -d= -f2-)
   export CF_ZONE_ID=$(grep -m1 '^CF_ZONE_ID='         /home/zabz/personal-secretary-mvp/.env | cut -d= -f2-)
   export CF_ACCOUNT_ID=$(grep -m1 '^CF_ACCOUNT_ID='   /home/zabz/personal-secretary-mvp/.env | cut -d= -f2-)
   python3 company-promote.py --to 3e62916c-04ac-421b-b4a4-9af0852d8024 \
     --hostnames ai.abletelsolutions.com,api.abletelsolutions.com --seed-stamp "" --apply
   ```
6. Post-switch: office DB size identical across two readings 10 min apart; then +1h, +24h, +7d.
7. **Only then** the leftover `data/` from the office box, in bounded batches.

## THE OUTAGE, STATED PLAINLY

The company API has been unreachable through `api.abletelsolutions.com` since **03:04Z**, and the
cause is this cutover — first a self-inflicted saturation outage (`H3406`, 02:14–02:40Z), then the
deliberate freeze. The freeze is longer than the runbook's 45-minute ceiling because four failed
attempts had to be diagnosed one at a time. **I will report the final dark window with the exact
timestamps rather than an estimate.**
