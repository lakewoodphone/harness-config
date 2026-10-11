# 135 work notes — port log (append-only as I go)

Workstream: **135-PORT-FRESHNESS**. Families 3 (service/pipeline freshness monitors) and 9 (AI
gateway / model registry). Machine I work from: ZABZ-YOGA (this laptop). Target: `secratary-cloud`
(root@178.156.194.1). Office box `secratary-ts` is READ-ONLY (load 0.01 when read).

## Recon (all readings carry machine + command)

Cloud box at 2026-10-11T06:26-06:33Z:
- `ssh root@178.156.194.1 'df -h /'` -> `/dev/sda1 75G 46G 26G 65% /` (inventory's 4.4G figure was stale)
- `crontab -l` -> `no crontab for root`; `/root/.cron-status/` did not exist
- `systemctl list-units` custom services: company-api, cloudflared, secretary-dashboard,
  phone-redirector, tailscaled, fail2ban, atd
- `ss -ltnp` -> `127.0.0.1:8002` (company-api), `*:3000` (dashboard); **nothing on 3091** (mesh broker dead)
- `tailscale status` -> **"Logged out."** => no MagicDNS on the cloud box => every tailnet hostname and
  every ssh alias (`lpt-apps`, `hetzner`, `survivor`) fails to resolve from there. Measured:
  `ssh lpt-apps-01 hostname` -> `Could not resolve hostname`
- `/root/.ssh/id_ed25519_hetzner` present 419 B mode 600 (so the offsite/vault ssh path works)
- `/root/.lpt-r2.env` present 643 B mode 600
- `/opt/company/.env` -> `DATABASE_URL=sqlite:////root/authority.db` (the API uses the authority)
- **`/opt/company/data/secretary.db` EXISTS and is 1,827,816 B (mtime 2026-10-11 01:18)** against a
  23,707,291,648 B authority. A cutover stub. Every monitor that defaults to a repo-relative DB path
  would measure THAT. This is the single most dangerous thing I found and it shaped every port below.
- `/root/code/harness-config/` exists but holds only 4 transcript scripts and is NOT a git checkout
- No `/root/.dsh/.credentials.yaml`; no `/root/.fsearch/`; no `/root/bin/`; no `~/code/lpt-ops`
- Authority tables present and populated: `website_sync_cursor` 3, `dialpad_sms_cache` 135,421,
  `dialpad_call_full` 13,995, `model_usage` 255,123, `owner_decision_queue` 444
- Harvest heartbeat markers `/root/.dialpad-harvest.last_run`, `/root/.dialpad-sms-harvest.last_run`
  both ABSENT

Office box script sources (mode/size/mtime read 2026-10-11T06:26Z):
`/home/zabz/bin/cron-wrap.sh` 4071 2026-10-02 · `production-comms-freshness.py` 15010 2026-10-05 ·
`lpt-freshness-watchdog.py` 15836 2026-10-07 · `disk-guard.py` 11273 2026-09-30 · `box-health-check.sh`
5197 · `lpt-audit-freshness.py` 7825 · `lpt-deploy-drift.py` 8333 · `monitor-hetzner-backups.sh` 1897 ·
`site-uptime-check-cron.sh` 2305 · `ai-gateway-health.py` 37258 · `lpt-report-freshness.py` 35582 ·
`model-failover-watch.py` 21828 · `/home/zabz/.lpt-reports/tracking.db` 7,061,504 B.

## What I changed on the cloud box (each named, each reversible)

| change | why | evidence |
|---|---|---|
| installed `/usr/local/bin/cron-wrap.sh` from the office source, mode 755 | the port brief's scheduling contract | `sha256sum` = 8db5fe43… matches the office file byte for byte |
| created `/root/.cron-status/`, `/root/.lpt-recon/`, `/root/.lpt-ops/dialpad/`, `/root/.lpt-reports/`, `/root/.disk-guard/` | log/state targets the ported scripts write | `ls -ld` |
| `pip install psycopg2-binary` 2.9.13 into `/opt/company/.venv` | 3 ported monitors import psycopg2 (the website read); the venv had psycopg3 only | `Successfully installed psycopg2-binary-2.9.13`; `import psycopg2` -> 2.9.13 |
| `/root/port135/` staging dir for the ported copies | so every ported file is auditable in one place | `ls -la /root/port135/` |

**Nothing was restarted.** company-api, cloudflared, secretary-dashboard and phone-redirector were
never touched.

## Ported and proven (run deliberately)

| job | cloud path | first-run evidence |
|---|---|---|
| `cron-wrap.sh` (shared) | /usr/local/bin/cron-wrap.sh | ledger row written for site-uptime-check-cron |
| `site-uptime-check-cron` | /root/port135/site-uptime-check-cron.sh | 4/4 endpoints HTTP 200; ledger `2026-10-11T06:32:33Z site-uptime-check-cron 0 1` |
| `disk-guard` | /root/port135/disk-guard.py | selftest OK; real reading `/ at 62.3%, 25.12 GB free`; ALARM path proven by lowering the threshold for one run |
| `lpt-freshness-watchdog` | /root/port135/lpt-freshness-watchdog.py | calls OK lag 0.0s against the live Dialpad API; sms UNKNOWN (refused to call it OK) |
| `production-comms-freshness` | /root/port135/production-comms-freshness.py | `fresh` rc=0 on /root/authority.db, read-only |
| `ai-gateway-health` | /root/port135/ai-gateway-health.py | self-test PASSED (28 checks); detects the live `tier-collapse`; catalogue 35 routes |

## Incident during the work
A burst of ~12 quick ssh calls tripped a rate limit / fail2ban on the cloud box:
`kex_exchange_identification: read: Unknown error` / `Permission denied (publickey)`. I backed off
rather than retrying. Recorded because the next session must not read it as "the key is broken".
