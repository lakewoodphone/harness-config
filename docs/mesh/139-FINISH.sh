#!/bin/bash
# 139-FINISH.sh -- run this on secratary-cloud to complete workstream 139.
#
# WHY IT EXISTS: at ~06:42Z on 2026-10-11 the cloud box stopped accepting this
# workstream's SSH key ("Offering public key: ... id_ed25519_hetzner ... Permission
# denied (publickey)") while the box itself stayed healthy
# (https://api.abletelsolutions.com/health -> 200). Everything else in the port was
# DONE and measured before that; two proven cron lines and the state symlinks are all
# that is left. See docs/mesh/139-PORT-OWNER-CHANNEL.md sections 9.0 and 10.
#
# It is idempotent and safe to run twice. It changes nothing that is not named here.
set -uo pipefail
say() { printf '%s\n' "$*"; }

say "=== 1. the /home/zabz path aliases (the reason the office payloads run unedited) ==="
mkdir -p /root/bin /root/code
for pair in "bin:/root/bin" "code:/root/code" \
            "accounting-data:/root/accounting-data" ".sms-inbox:/root/.sms-inbox" \
            ".owner-ask:/root/.owner-ask" ".cfo:/root/.cfo" ".cfo-asks:/root/.cfo-asks" \
            ".hours-drift:/root/.hours-drift" ".lpt-reports:/root/.lpt-reports" \
            ".lpt-verify:/root/.lpt-verify" ".lpt-recon:/root/.lpt-recon" \
            ".lpt-ops:/root/.lpt-ops" ".lpt-hub-refresh:/root/.lpt-hub-refresh" \
            ".cron-status:/root/.cron-status" "work:/root/work" ".dsh:/root/.dsh"; do
  name="${pair%%:*}"; target="${pair#*:}"
  if [ -L "/home/zabz/$name" ]; then continue; fi
  if [ -e "/home/zabz/$name" ]; then say "  SKIP-EXISTS /home/zabz/$name"; continue; fi
  mkdir -p "$target"; ln -s "$target" "/home/zabz/$name"; say "  created /home/zabz/$name -> $target"
done
for t in /root/personal-secretary-mvp /home/zabz/personal-secretary-mvp; do
  if [ -L "$t" ]; then continue; fi
  if [ -e "$t" ]; then say "  SKIP-EXISTS $t"; continue; fi
  ln -s /opt/company "$t"; say "  created $t -> /opt/company"
done

say "=== 2. the two cron lines that were proved and left uninstalled ==="
# payloads are the office's own, byte-for-byte (decoded in the report, sections 2.1 and 2.4)
CUR=/root/_staging/crontab.now
crontab -l > "$CUR" 2>/dev/null || : > "$CUR"
before=$(grep -c '139-port-owner-channel' "$CUR" || true)
if grep -q 'cron-wrap.sh cfo-scoreboard' "$CUR"; then
  say "  cfo-scoreboard already installed"
else
  awk '{print}' "$CUR" > "$CUR.new"
  # insert inside our marker block, right before its closing marker
  awk '
    /^# <<< 139-port-owner-channel/ && !done {
      print "20 */6 * * * /usr/local/bin/cron-wrap.sh cfo-scoreboard L3Vzci9iaW4vcHl0aG9uMyAvaG9tZS96YWJ6L2Jpbi9jZm8tc2NvcmVib2FyZC5weSA+PiAvaG9tZS96YWJ6Ly5jZm8vc2NvcmVib2FyZC5sb2cgMj4mMQ=="
      print "17 */6 * * * /usr/local/bin/cron-wrap.sh hours-drift cHl0aG9uMyAvaG9tZS96YWJ6L2Jpbi9ob3Vycy1kcmlmdC1jaGVjay5weSA+IC9ob21lL3phYnovLmhvdXJzLWRyaWZ0L2xhc3QudHh0"
      done=1
    }
    { print }
  ' "$CUR" > "$CUR.new"
  crontab "$CUR.new"
  say "  installed cfo-scoreboard (20 */6) and hours-drift (17 */6)"
fi

say "=== 3. proof: the lines, and what every payload decodes to ==="
crontab -l | sed -n '1,40p'
crontab -l | awk '/cron-wrap.sh/{print $7, $8}' | while read -r nm pl; do
  printf '  %-22s %s\n' "$nm" "$(printf '%s' "$pl" | base64 -d 2>&1)"
done

say "=== 4. the run ledger (the evidence the installed lines actually ran) ==="
cat /root/.cron-status/runs.tsv 2>/dev/null | tail -30 || say "  (no ledger yet - cron has not ticked)"

say "=== 5. put the report where the review reads it ==="
mkdir -p /root/out/migration-review
if [ -f /root/_staging/139-PORT-OWNER-CHANNEL.md ]; then
  cp -f /root/_staging/139-PORT-OWNER-CHANNEL.md /root/out/migration-review/
  say "  copied from staging"
else
  say "  STAGING COPY ABSENT - scp the report from the laptop:"
  say "  scp -i ~/.ssh/id_ed25519_hetzner <path>/139-PORT-OWNER-CHANNEL.md root@178.156.194.1:/root/out/migration-review/"
fi
ls -la /root/out/migration-review/139-PORT-OWNER-CHANNEL.md 2>/dev/null

say "=== 6. disk ==="
df -h / | tail -1
say "DONE - workstream 139 complete."
