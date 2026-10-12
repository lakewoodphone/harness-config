# MIGRATION BRIEF — 2026-10-11 — the authority cutover and everything it left behind

READ THIS FIRST. It is the shared context for every workstream fixing the 2026-10-11 authority
cutover. It is written down because each of you starts blank.

## What happened

At **2026-10-11 05:43:36Z** the company's authority was cut over from the **office box** to a new
**cloud box**:

| | office box | cloud box |
|---|---|---|
| ssh | `ssh secratary-ts` (Tailscale, `secratary.tail93e6e6.ts.net`) | `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` |
| identity | `secratary`, i5-4570, 4c/4t, 23 GB, 192.168.50.77 | `secratary-cloud`, Hetzner CCX13, Ashburn VA, 2 vCPU, 7.7 GB RAM, 75 GB NVMe, 27 GB free |
| state | **FROZEN, not deleted — it is the rollback anchor** | **THE AUTHORITY now** |
| what runs | cron MASKED, `secretary-api` / `company-api` / `presence-sampler` inactive+disabled, all writer units stopped, database untouched since 04:28:35Z | `company-api` (FastAPI, `/opt/company`, venv `/opt/company/.venv`, 127.0.0.1:8002), `secretary-dashboard` (:3000), `cloudflared`, `phone-redirector` |
| database | `/home/zabz/personal-secretary-mvp/data/secretary.db` — frozen anchor, 23,622,823,936 B | `/root/authority.db` — the live authority, same size at the copy, WAL moving |
| crontab | 168 lines, preserved at `/home/zabz/cutover/crontab.before` | **cron enabled, crontab EMPTY** |

The public doors `https://api.abletelsolutions.com` and `https://ai.abletelsolutions.com` both answer
HTTP 200 from the cloud box. The company app's own autopilot loop (`AUTOPILOT_INTERVAL_SEC=900`) is
running **inside the API process** on the cloud box, so the company's agent ticks are alive. What did
not move is the **entire cron layer**, and with it: the offsite backups, the freshness monitors, the
external dead-man switch, the transcript archive, and every other scheduled job.

## THE RULES THAT ARE NOT NEGOTIABLE

1. **The office box is READ-ONLY.** Do not enable, start, unmask, disable or restart anything on it.
   Do not write to its database. Do not run a long or bulk operation on it — ANY operation that keeps
   its disk queue busy for more than a few seconds (a multi-GB rsync, a recursive `du`, a full-table
   scan, `.backup`) stalls its disk, kills sshd, and takes the company down while `tailscale ping`
   still answers. That is measured, three times. Small, bounded commands only, and check
   `cut -d' ' -f1 /proc/loadavg` (stop above ~8) around anything that touches its disk.
2. **Only ONE writer may exist for the company database, and it is `/root/authority.db` on the cloud
   box.** Never start a second API, never point a job at both databases, never "sync" the office
   database over the cloud one.
3. **NEVER DELETE `/root/authority.db`.** The old handoff recorded a stale 14 GB copy at that exact
   path as safe to delete; after the cutover that path holds the REAL authority database. Any
   instruction that says to delete it is now a company-ending instruction.
4. **Disk on the cloud box is the binding constraint:** 75 GB total, database 23.6 GB,
   `/opt/company/data` another 14 GB, so free space hovers around 4-27 GB. Nothing may leave a second
   full copy of the database on that disk. Check `df -h /` before and after anything you write there.
5. **Do not restart the DSH engine on this laptop** and do not restart `company-api`, `cloudflared`,
   `secretary-dashboard` or `phone-redirector` on the cloud box without saying so in your report.
6. **Provenance:** every number you report must carry the machine and the command that produced it.
   An empty result is not health — say "unmeasured" rather than guessing. A confident wrong number is
   the worst outcome in this estate's history.
7. **Write down what you did**, in your own artifact file, as you go. Sessions end without warning.

## Key paths and facts

- Journal tool: `python ~/code/harness-config/journal/tools/journal.py` — `status`, `show <id>`,
  `search "<words>"`, `list --kind pain --status open`. Read `show H3407` (the cutover) and
  `show H3408` (the cutover's live state, written 06:00Z), `show H3406` (the 02:14Z outage).
- Ops repo: `~/code/harness-config` (git, remote on the authority). Systems register:
  `docs/mesh/000-SYSTEMS-REGISTER.md`. Cutover docs: `docs/mesh/126-` through `130-`.
- Offsite backup (R2, bucket `lakewood-rentals-media`): office script `/home/zabz/bin/push-db-offsite.sh`,
  credentials `/home/zabz/.lpt-r2.env` (mode 600) which **is now also installed on the cloud box at
  `/root/.lpt-r2.env`, mode 600, root**. It defines `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ENDPOINT`,
  `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. System python on the cloud box has `boto3` 1.40.72;
  the app venv does not.
- The new offsite script (mine, 2026-10-11): `~/code/harness-config/scripts/mesh/authority-offsite-backup.sh`,
  deployed to `secratary-cloud:/usr/local/bin/authority-offsite-backup.sh`. It takes a consistent
  `.backup` of the live database, checks its integrity, streams it gzipped to
  `authority/secretary.db.gz` with a sha256 sidecar and `authority/accounting.db.gz` beside it, and
  writes `/var/lib/authority-backup/last-run`. It refuses to run when the credential is missing or not
  mode 600.
- The public API needs no token for anonymous reads but 401s on `/openapi.json`.
- DSH session ingest endpoint: `POST https://api.abletelsolutions.com/api/v1/owner/dsh-sessions/ingest`;
  the pusher is `~/code/harness-config/scripts/push-dsh-sessions.mjs`. Measured working 2026-10-11
  06:04Z from this laptop: 14 sessions, 1544 new rows.
- Copilot chat pusher: `~/code/personal-secretary-mvp/scripts/push_vscode_chats.py`, run on this
  laptop by the scheduled task `PersonalSecretary-PushVSCodeChats` (which reports success while
  shipping nothing — a known trap).
- Mesh fan-out: the `subagent` tool is the mesh provider, and it is **currently broken** —
  `broker-unreachable ... curl: (7) Failed to connect to localhost:3091` because the placement broker
  is loopback-only on `secratary-ts` and no broker process exists there (or anywhere) any more. Node
  side: the broker package is `~/code/harness-config/packages/mesh-broker/` with
  `deploy/install-authority.sh` and `deploy/mesh-broker.service` (a unit that expects user `zabz` and
  `/usr/bin/node`). Node `/mesh/health` over the tailnet answers 200 on `zabz-tech` (limit 8) and
  `zabz-yoga-1` (limit 5); `zabz-tech-linux` 404s and `secratary` 502s.
- A fleet of migration workstreams runs **LOCALLY** right now (`subagent_local`), because the mesh is
  unreachable. Every report that came from a local child must be labelled LOCAL in any summary.

## The standard of success for this whole program

The owner, verbatim, 2026-10-11: the cloud authority must be "a better version by orders of magnitude
over the office one, not missing anything or doing anything less in any way… everything and more it
should do even faster and more robustly." So a job ported unchanged is the floor, not the goal: where
you port something, ask what made it fragile on a 2013 desktop with a flaky NIC and a single disk, and
fix that while you move it — independent failure, real freshness evidence, and a monitor that reports
absence instead of silence.
