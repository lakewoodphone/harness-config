# The 15-minute text-channel safety check

Runs `/root/bin/text-health.py` — read-only, it never sends a text — every 15 minutes and
writes `/var/lib/text-health/status.json`. Installed on the cloud authority 2026-10-20 for
ledger items 97 and 312 (owner decision `owner_decision_queue` #489, answered 2026-10-15:
"restore it; it only reads and it never sends").

Why a systemd timer and not cron: a wake shift may not touch cron, and the comparable estate
check (`esearch-health.timer`) uses the same `OnCalendar=*:0/15` shape. Nothing here sends.

## Install

```bash
install -m 0755 text-health-check.sh /usr/local/bin/text-health-check.sh
install -m 0644 text-health.service text-health.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now text-health.timer
systemctl start text-health.service
```

## Prove

```bash
cat /var/lib/text-health/status.json
systemctl list-timers text-health.timer --no-pager
systemctl is-active text-health.timer
```

Status-file fields: `checked_at`, `ok`, `exit_code`, `result` (`RESULT: N check(s), M FAIL`),
`checks`, `fail`, `failed_checks[]`, `duration_s`, `stale_after_minutes` (20), `cmd`, `host`.

Exit contract: `0` every invariant passes; `1` any FAIL, so the unit fails and
`systemctl --failed` carries the alarm; `2` could not run (missing interpreter, or a 200 s
timeout) — never a silent pass. Overlapping runs are skipped by `flock` on
`/run/text-health.lock`; the skip is recorded in `runs.log`.
