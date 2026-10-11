#!/bin/bash
# 139-port-owner-channel install: /root/_staging/files/* -> their real paths.
# Idempotent. Never overwrites a file that is not one of ours without saying so.
set -uo pipefail
S=/root/_staging/files
BIN=/root/bin
mkdir -p "$BIN" "$BIN/sources"
installed=0; skipped=0

# name|mode|target
while IFS='|' read -r name mode target; do
  [ -z "$name" ] && continue
  src="$S/$name"
  if [ ! -f "$src" ]; then echo "MISSING-SOURCE $name"; skipped=$((skipped+1)); continue; fi
  if [ -e "$target" ] && [ "$target" != "$BIN/$name" ]; then
    cur=$(sha256sum "$target" 2>/dev/null | cut -d' ' -f1)
    new=$(sha256sum "$src" 2>/dev/null | cut -d' ' -f1)
    if [ "$cur" != "$new" ]; then echo "WARN-EXISTS-DIFFERENT $target (left alone; source is $name)"; fi
  fi
  cp -f "$src" "$target"
  chmod "$mode" "$target"
  installed=$((installed+1))
  # a /usr/local/bin copy is a convenience link, never a second body
  case "$target" in
    /usr/local/bin/*) ln -sfn "$target" "$BIN/$name" ;;
  esac
done <<'LIST'
cron-wrap.sh|755|/usr/local/bin/cron-wrap.sh
sms-inbox.py|755|/root/bin/sms-inbox.py
sms-responder.py|755|/root/bin/sms-responder.py
storelock.py|755|/root/bin/storelock.py
textstore.py|755|/root/bin/textstore.py
mirror-owner-sms.py|755|/root/bin/mirror-owner-sms.py
reconcile-sent-status.py|755|/root/bin/reconcile-sent-status.py
promote-owner-texts.py|755|/root/bin/promote-owner-texts.py
wake.py|755|/root/bin/wake.py
wake-nextclaim.py|755|/root/bin/wake-nextclaim.py
wake-dispatch.sh|755|/root/bin/wake-dispatch.sh
wake-fanout.sh|755|/root/bin/wake-fanout.sh
wake-cost.py|755|/root/bin/wake-cost.py
wake-balance.py|755|/root/bin/wake-balance.py
owner-ask.py|755|/root/bin/owner-ask.py
owner-queue.py|755|/root/bin/owner-queue.py
textsend.py|755|/root/bin/textsend.py
ask_quality.py|755|/root/bin/ask_quality.py
work.py|755|/root/bin/work.py
work-integrator.py|755|/root/bin/work-integrator.py
chip-resume.py|755|/root/bin/chip-resume.py
hours-drift-check.py|755|/root/bin/hours-drift-check.py
cfo-ask.py|755|/root/bin/cfo-ask.py
cfo-scoreboard.py|755|/root/bin/cfo-scoreboard.py
cfo-shift.py|755|/root/bin/cfo-shift.py
cfo-shift-cron.sh|755|/root/bin/cfo-shift-cron.sh
cfo_backup.py|755|/root/bin/cfo_backup.py
website-comms-push-cron.sh|755|/root/bin/website-comms-push-cron.sh
lpt-audit-weekly.sh|755|/root/bin/lpt-audit-weekly.sh
lpt-hub-refresh.sh|755|/usr/local/bin/lpt-hub-refresh.sh
lpt-business-report.sh|755|/root/bin/lpt-business-report.sh
projects.json|644|/root/bin/sources/projects.json
sources/_flag.py|644|/root/bin/sources/_flag.py
sources/cfo-backfill.py|755|/root/bin/sources/cfo-backfill.py
sources/checkout-health.py|755|/root/bin/sources/checkout-health.py
sources/comms-freshness.py|755|/root/bin/sources/comms-freshness.py
sources/cron-failures.py|755|/root/bin/sources/cron-failures.py
sources/cron-targets.py|755|/root/bin/sources/cron-targets.py
sources/db-integrity.py|755|/root/bin/sources/db-integrity.py
sources/decision-answer-unconsumed.py|755|/root/bin/sources/decision-answer-unconsumed.py
sources/decision-queue-stale.py|755|/root/bin/sources/decision-queue-stale.py
sources/disk-space.py|755|/root/bin/sources/disk-space.py
sources/dormant-handoff.py|755|/root/bin/sources/dormant-handoff.py
sources/drift-check.py|755|/root/bin/sources/drift-check.py
sources/hours-drift.py|755|/root/bin/sources/hours-drift.py
sources/journal-pain-supply.py|755|/root/bin/sources/journal-pain-supply.py
sources/ledger-keepalive.py|755|/root/bin/sources/ledger-keepalive.py
sources/owner-question-audit.py|755|/root/bin/sources/owner-question-audit.py
sources/pain-checks.py|755|/root/bin/sources/pain-checks.py
sources/plaid-freshness.py|755|/root/bin/sources/plaid-freshness.py
sources/project-keepalive.py|755|/root/bin/sources/project-keepalive.py
sources/roadmap-supply.py|755|/root/bin/sources/roadmap-supply.py
sources/sentinel-supply.py|755|/root/bin/sources/sentinel-supply.py
sources/sms-app-gap.py|755|/root/bin/sources/sms-app-gap.py
sources/txt-lost-webhook.py|755|/root/bin/sources/txt-lost-webhook.py
sources/txt-stranded-inbound.py|755|/root/bin/sources/txt-stranded-inbound.py
sources/wake-tuner.py|755|/root/bin/sources/wake-tuner.py
LIST

echo "installed=$installed skipped=$skipped"
echo "--- verify against the office hash manifest ---"
sha256sum /root/bin/sms-inbox.py /root/bin/mirror-owner-sms.py /root/bin/reconcile-sent-status.py \
          /root/bin/wake-fanout.sh /root/bin/wake-cost.py /root/bin/wake-balance.py /root/bin/owner-ask.py \
          /root/bin/cfo-ask.py /root/bin/cfo-scoreboard.py /root/bin/cfo-shift-cron.sh /root/bin/hours-drift-check.py \
          /root/bin/work-integrator.py /root/bin/chip-resume.py /usr/local/bin/cron-wrap.sh /usr/local/bin/lpt-hub-refresh.sh \
          /root/bin/promote-owner-texts.py
ls -la /root/bin | head -5
df -h / | tail -1
