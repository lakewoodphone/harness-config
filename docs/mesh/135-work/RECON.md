# 135 work notes — port log (append-only as I go)

Workstream: **135-PORT-FRESHNESS**. Families 3 (service/pipeline freshness monitors) and 9 (AI
gateway / model registry). Machine I work from: ZABZ-YOGA (this laptop). Target: `secratary-cloud`
(root@178.156.194.1). Office box `secratary-ts` is READ-ONLY (load 0.01 when read).

**Deliverable: `docs/mesh/135-PORT-FRESHNESS.md`.** This file is the working log behind it.

## Recon (every reading carries machine + command)

Cloud box at 2026-10-11T06:26-06:33Z:
- `ssh root@178.156.194.1 'df -h /'` -> `/dev/sda1 75G 46G 26G 65% /` (the inventory's "4.4G free"
  was stale; `statvfs` reads 62.3% used / 25.12 GB free)
- `crontab -l` -> `no crontab for root`; `/root/.cron-status/` did not exist
- custom services running: company-api, cloudflared, secretary-dashboard, phone-redirector,
  tailscaled, fail2ban, atd
- `ss -ltnp` -> `127.0.0.1:8002` (company-api), `*:3000` (dashboard); **nothing on 3091**
- `tailscale status` -> **"Logged out."** => no MagicDNS => `ssh lpt-apps-01` etc. fail to resolve
- `/opt/company/.env` -> `DATABASE_URL=sqlite:////root/authority.db`
- **`/opt/company/data/secretary.db` EXISTS, 1,827,816 B, mtime 06:27… 2026-10-11 01:18** vs
  `/root/authority.db` 23,707,291,648 B. THE STUB TRAP: every monitor that defaults to a
  repo-relative DB path would measure it. Drove every port below.
- `/root/.ssh/authorized_keys` holds exactly ONE key per 135-PARITY-AND-ROBUSTNESS.md §… :
  `SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg mesh-hetzner-2026-08-31` — which is this
  laptop's key and the one now being refused. So the loss of access is NOT a key change.
- Authority tables: `website_sync_cursor` 3, `dialpad_sms_cache` 135421, `dialpad_call_full` 13995,
  `model_usage` 255123, `owner_decision_queue` 444 (cols incl. options_json, recommendation, source)
- Harvest markers `/root/.dialpad-harvest.last_run`, `/root/.dialpad-sms-harvest.last_run` ABSENT
- Missing: `/root/.dsh/.credentials.yaml`, `/root/code/harness-config/.git`, `/root/code/lpt-ops`,
  `/root/.fsearch/`, `/root/bin/owner-queue.py`, `/home/zabz/node/bin/node`, `phone-engine.service`

## What I changed on the cloud box (all before 06:35Z; nothing restarted)

| change | evidence |
|---|---|
| `/usr/local/bin/cron-wrap.sh` installed from the office source | sha256 `8db5fe43…ffa14`, byte-identical |
| `/root/.cron-status/`, `/root/.lpt-recon/`, `/root/.lpt-ops/dialpad/`, `/root/.lpt-reports/`, `/root/.disk-guard/` created | `mkdir -p` |
| `/root/port135/` staging dir with 5 ported files (+ the pre-promotion health script) | `sha256sum` matched local for every push |
| `pip install psycopg2-binary` 2.9.13 into `/opt/company/.venv` (psycopg3 only, before) | `Successfully installed psycopg2-binary-2.9.13`; 3 monitors import it |

## Ported and proven (evidence quoted in the report §4)

- `site-uptime-check-cron` — 4/4 endpoints HTTP 200, ledger row
  `2026-10-11T06:32:33Z<TAB>site-uptime-check-cron<TAB>0<TAB>1`
- `disk-guard` — selftest OK; reading `/ at 62.3%, 25.12 GB free, findings []`; ALARM path proven by
  lowering `DISK_WARN_PCT` to 60 for one run (`findings: ["/ at 62.3% … warn threshold 60%"]` plus the
  consumer breakdown)
- `lpt-freshness-watchdog` — `calls OK lag=0.0s` against Dialpad's live API, `sms UNKNOWN` (refused to
  call it OK without psycopg2), `repo=/opt/company db=/root/authority.db`, rc=3
- `production-comms-freshness` — `fresh`, rc=0, `db=/root/authority.db`, read-only
- `ai-gateway-health` — `SELF-TEST PASSED`; live `tier-collapse` reported; catalogue 35 routes

## Staged locally, NOT deployed (in `135-work/port/`)

- `ai-gateway-health.py` — adds the catalogue probe (90 s timeout) and the
  `AI_GATEWAY_HEALTH_TIER_COLLAPSE_IS_CONDITION` promotion (collapse -> exit 3). The cloud copy is the
  pre-promotion revision, sha256 `9ddc3b2d…`.
- `lpt-deploy-drift.py` — `LPT_REPO` / `LPT_DEPLOY_SERVICES` / `LPT_DEPLOY_STATE` overrides.
- `cron-wrap.sh`, `disk-guard.py`, `site-uptime-check-cron.sh`, `lpt-freshness-watchdog.py`,
  `production-comms-freshness.py` — all five are ON the box AND in this repo.

## THE ACCESS LOSS — read this, it is the one open problem

At **06:34Z** every ssh to `root@178.156.194.1` began returning
`Permission denied (publickey)` after ~20 short invocations in ~10 minutes from this laptop.
`ssh -vv` shows the key being offered (`SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg`) and
refused; `PreferredAuthentications=password` gives the same line, which is expected
(`PasswordAuthentication no` is provision-by-design). The key is still the ONE key in the box's
`authorized_keys` per this workstream's own 06:2xZ measurement, so **the loss is a per-source block,
not a key change.** Most likely fail2ban (installed; the 06:27-06:33 burst produced
`kex_exchange_identification` errors before the denials) and possibly `MaxStartups 10:30:100`.

**The mistake that made it last:** I retried every 1-3 minutes. Each denied connection is a restart of
the fail2ban window, so the ban kept renewing. Back off for 15 minutes or more and do NOT retry inside
the window. Read `/etc/fail2ban/jail.local` and `sshd -T | grep -i maxstartups` on the first successful
reconnect, and note the settings in this file.

**Everything the last mile needs is in the report §9**: the seven cron lines with their full
environment, the two staged files, and the base64 recipe. `crontab -l` was still empty at 06:27Z.
