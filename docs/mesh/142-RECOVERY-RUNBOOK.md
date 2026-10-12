# 142 — RECOVERY RUNBOOK: the one pass that finishes the migration

**Written 2026-10-11 06:58Z by the manager session, while ssh to `secratary-cloud` was refusing the
estate's key from every source.** Read this with `141-MIGRATION-STATUS.md`. Each workstream's own
report and its own finish script are named here; this file is the ORDER, so that eleven scripts written
in parallel do not collide when they finally run.

## 0. First: prove access, once, without a retry loop

**UPDATE 2026-10-11 07:30Z — the console is no longer the only route.** The `HETZNER_API_TOKEN` in
`~/code/personal-secretary-mvp/.env` on ZABZ-YOGA is **valid** (the revoked token is only in
`secratary-cloud:/opt/company/.env`); a read-only call lists all four servers. The account shows
`secratary-cloud` id **169556315** (ccx13, Ubuntu 26.04, running, **no cloud firewall attached**,
**zero snapshots**, never rebuilt — its action log holds only `create_server` and `start_server` on
2026-10-09) and **one** registered key, `mesh-hetzner-2026-08-31`. Fail2ban is ruled out from the jail
itself. So: the box is healthy and the estate's one 105-byte `/root/.ssh/authorized_keys` was
overwritten on the box.

**RECOMMENDED RECOVERY — one reboot into the provider's rescue system** (owner's word required: it is
~2 minutes of public-API downtime, the office rollback copy is untouched, and the offsite backup of the
authority is current):

```bash
# 1. enable rescue with the account's own key (no effect until the boot)
#    POST /v1/servers/169556315/actions/enable_rescue {"type":"linux64","ssh_keys":[{"name":"mesh-hetzner-2026-08-31"}]}
#    (this returned 422 once; read the body and try {"ssh_keys":[<numeric key id>]} or the name form again)
# 2. reboot: POST /v1/servers/169556315/actions/reboot
# 3. ssh root@178.156.194.1  (rescue root, account key)
mount /dev/sda1 /mnt
install -d -m 700 /mnt/root/.ssh
printf '%s\n' 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHS/d3PK5rIZqVN+/NARxQeWBxkjlvzauXzcZkAHY4Je mesh-hetzner-2026-08-31' >> /mnt/root/.ssh/authorized_keys
# ALSO install the SECOND key so one file is never the only way in:
cat /mnt/root/.ssh/authorized_keys        # verify both lines
chmod 600 /mnt/root/.ssh/authorized_keys && chmod 700 /mnt/root/.ssh
# 4. reboot into normal boot and verify both keys
```

**Alternative, no downtime:** the web console (`console.hetzner.cloud`) with the root password reset at
07:0xZ and stored at `~/.secrets/hetzner-root-reset-20261011.txt`. The box is key-only over ssh, so the
password is only useful at the console.

**Also check while in there:** `/etc/ssh/sshd_config.d/*` for a stray `Match`/`AllowUsers`, and
`grep -n MARK /root/company-heartbeat.sh` style sanity on anything a burst could have changed.

A connection burst from this estate tripped the authority's per-source defence and then every retry
re-armed it, which turned a couple of minutes into an hour. So:

```
ssh -i ~/.ssh/id_ed25519_hetzner -o ConnectTimeout=10 -o BatchMode=yes root@178.156.194.1 'echo ACCESS-OK; date -u'
```

If that fails: **stop.** Do not retry for at least 15 minutes. `C:\Users\ezabz\code\harness-config\scripts\mesh\cloud-access-watch.ps1`
exists to poll slowly and tell you when it opens (a completed workstream left it). If it stays shut with
the key unchanged, the box needs the provider console — the estate's `HETZNER_API_TOKEN` is a revoked
token (401), so there is no API path in.

**The very first change once access works is to stop this recurring**: add the estate's own addresses to
fail2ban's `ignoreip` and to any ufw allow rule, so legitimate agent traffic can never be mistaken for
the brute-force this box is genuinely under (11,671 failed password attempts in 24 h).

## 1. Install the crontab fragments — in this order, by one process only

`/usr/local/bin/install-crontab-fragment.sh` (source `scripts/mesh/install-crontab-fragment.sh`) appends
to root's crontab under a lock, de-duplicates by job NAME, refuses a payload that does not round-trip,
and keeps a timestamped before-image. Use it for every fragment; never `crontab -` with a whole file.

| order | fragment | workstream | covers |
|---|---|---|---|
| 1 | `docs/mesh/135-work/port/135-crontab.txt` | 135 (freshness) | `site-uptime-check-cron`, `disk-guard`, `lpt-freshness-watchdog`, `production-comms-freshness`, `ai-gateway-health`, `lpt-deploy-drift` |
| 2 | `docs/mesh/139-install-cron.sh` | 139 (owner channel) | `cfo-scoreboard`, `hours-drift` (the other three are already installed and running) |
| 3 | `scripts/mesh/cloud-crontab.txt` (from 134) | 134 (guards/backup) | `db-integrity-check`, `prune-backups`, `report-offsite-age`, `deadman`, the guards, `journal-commit` |
| 4 | whatever 138 and 137 leave | 138 (ingestion), 137 (timers) | dialect/comms ingestion, the five systemd timers |
| 5 | `scripts/mesh/port-140-run-sentinel-install.sh` | 140 (core) | `run-sentinel` |

Load `crontab -l` after EVERY fragment and record the line count, so a fragment that silently did
nothing is visible immediately.

## 2. The systemd side

- `transcript-archive-pull.timer` is already installed and its first fire is 07:23Z (workstream 216).
  Witness it: `systemctl list-timers transcript-archive-pull.timer` and `journalctl -u
  transcript-archive-pull.service -n 40`. Its first run is expected to fail on machines that are off;
  what matters is that it runs, pulls what it can, and records the failure rather than silence.
- The five ported timers from the office box (`estate-monitor`, `company-outcome-monitor`,
  `tmp-reaper`, `trunk-check`, `fa-index`) come from workstream 137's report `137-PORT-SYSTEMD-TIMERS.md`.
- The mesh broker: `packages/mesh-broker/deploy/install-authority-cloud.sh` — **but only after the
  tailnet join**, because the installer refuses to leave a blind broker enabled, and a blind broker is
  worse than none (the dispatcher asks it first and then has nowhere to place).

## 3. Then, and only then, the mesh

1. Tailnet join for `secratary-cloud` — needs the owner's auth key (owner question 445).
2. `install-authority-cloud.sh` (it will refuse to enable a blind broker; that refusal is the test).
3. The profile is already repointed (`brokerSsh` → `secratary-cloud`, repo and live copy in sync).
4. The engine on ZABZ-YOGA restarts at the 0700 local window (task `DSH Mesh 0700 Restart`), which also
   loads the placement failover committed 2026-10-09 and absent from the running process.
5. Prove it with a real dispatch, not a log line: a `subagent` child must come back with a
   `MESH-HOST:` line naming a machine other than this laptop, and the ledger under
   `<DSH_HOME>/mesh/placements/` must record `source: broker`.

## 4. What is deliberately NOT in this runbook

- **The memory limit for `company-api`** (`MemoryHigh=5500M`, `MemoryMax=6800M`, `MemorySwapMax=3072M`
  — 140's measurement: normal cgroup peak 4.78 GB, the fatal event 7.19 GiB of anon on a 7,742 MB box).
  Staged as a drop-in, not applied: it costs one restart of the public API, which is the owner's call to
  schedule. The next size up (CCX23, 4 vCPU / 16 GB) is a money decision, also his.
- **Anything that sends.** `sms-responder run --send`, `owner-ask --send`, `cfo-ask --send` are all
  staged and none enabled. The estate's rule is a per-message yes in the conversation it was asked in.
- **The family-chat data move.** The cloud copy holds a NEWER single row (05:41:32Z) than the office's
  newest (02:45:22Z), so it is not a copy — it is a merge. Command and sizes: `140-PORT-CORE-AND-GAPS.md` §B3.
- **`lpt-report-freshness`** (one file to move, then it would report STALE forever because nothing on
  the cloud writes `capture_run`) and **`chip-resume`** (it would restart the family SMS bot, which the
  owner did not ask for here).

## 5. The five things this run must leave TRUE, or the migration is not done

1. `api.` and `ai.abletelsolutions.com` answer 200 and `/root/authority.db` is the only writer.
2. An offsite copy of that database exists in R2, dated within 24 h, with a monitor that reports its
   age and an external dead-man switch that would notice the whole authority going silent.
3. Every job on the port list either runs and records a run, or is DISABLED with a written reason.
4. The raw transcript archive has a second copy and a pull that runs without a human.
5. `root@178.156.194.1` is reachable by the estate from a stable address, and the estate's own traffic
   cannot be locked out by the defence that exists to stop the internet.
