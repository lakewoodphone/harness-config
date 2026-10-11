#!/usr/bin/env bash
# 140-PORT-CORE install + proof script -- runs ON secratary-cloud as root.
# Idempotent. Does not restart anything. Does not touch /root/authority.db.
set -u

echo "===== 0. WHO / WHEN / DISK"
hostname; date -u; id -un; df -h / | tail -1

echo "===== 1. WHY THE LAPTOP SOURCE IP WAS REFUSED (evidence, not theory)"
sshd -V 2>&1 | head -1
grep -rhiE "^[[:space:]]*(persource|maxstartups|maxauthtries|authorizedkeysfile|pubkeyauthentication|permitrootlogin|allowusers|denyusers|port )" /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ 2>/dev/null | head -20
echo "--- auth.log evidence"
grep -hoE "Not allowed at this time|PerSource|penalty|refused connection|Disconnected from (invalid|authenticating)[^,]*|Accepted publickey for root[^ ]*" /var/log/auth.log 2>/dev/null | sort | uniq -c | sort -rn | head -8
grep -hE "Accepted publickey for root" /var/log/auth.log 2>/dev/null | tail -3 | cut -c1-140

echo "===== 2. cron-wrap.sh"
ls -la /usr/local/bin/cron-wrap.sh 2>&1
printf '%s' 'IyEvdXNyL2Jpbi9lbnYgYmFzaAojIGNyb24td3JhcC5zaCAtLSBydW4gb25lIGNyb24gam9iIGFuZCBSRUNPUkQgV0hBVCBJVCBESUQuCiMKIyBXSFkgVEhJUyBFWElTVFMKIyAtLS0tLS0tLS0tLS0tLS0KIyBPbiAyMDI2LTA5LTMwIGZpdmUgY3JvbiBqb2JzIG9uIHRoaXMgaG9zdCBjYWxsZWQgcHJvZ3JhbXMgdGhhdCBoYWQgbm90IGV4aXN0ZWQgZm9yIDI4IGhvdXJzLCBhbmQKIyB0d28gbW9yZSBoYWQgbG9zdCB0aGVpciBleGVjdXRlIGJpdCB3ZWVrcyBlYXJsaWVyLiBOb3RoaW5nIG5vdGljZWQuIGNyb24ncyBvbmx5IG91dHB1dCBpcyBhIGxpbmUgaW4KIyBhIHBlci1qb2IgbG9nIHRoYXQgbm8gcmVhZGVyIG9wZW5zLCBhbmQgdGhpcyBob3N0IGhhcyBubyBgbWFpbGAgYmluYXJ5IGF0IGFsbCwgc28gYSBqb2IgdGhhdCBmYWlscwojIGV2ZXJ5IHNpbmdsZSBydW4gaXMgaW5kaXN0aW5ndWlzaGFibGUgZnJvbSBhIGpvYiB3aXRoIG5vdGhpbmcgdG8gZG8uIFRoZSBleGlzdGVuY2UgaGFsZiBpcyBub3cKIyBjb3ZlcmVkIGJ5IGBjcm9uLXRhcmdldC1ndWFyZC5weWA7IFRISVMgaXMgdGhlIG90aGVyIGhhbGY6IGEgam9iIHRoYXQgZXhpc3RzIGFuZCBmYWlscy4KIwojIFdIQVQgSVQgRE9FUywgYW5kIG5vdGhpbmcgbW9yZQojICAgKiBydW5zIHRoZSBjb21tYW5kIGl0IGlzIGdpdmVuLCB3aXRoIGl0cyBvcmlnaW5hbCBzaGVsbCwgcmVkaXJlY3Rpb25zIGFuZCBhbGw7CiMgICAqIGFwcGVuZHMgb25lIGxpbmUgcGVyIHJ1biB0byB+Ly5jcm9uLXN0YXR1cy9ydW5zLnRzdjoKIyAgICAgICAgIDxJU08tODYwMSBVVEM+XHQ8bmFtZT5cdDxyYz5cdDxzZWNvbmRzPlx0PGZpcnN0IDE2MCBjaGFycyBvZiBzdGRlcnIsIGlmIGFueT4KIyAgICogYXBwZW5kcyBub3RoaW5nIGVsc2UgYW55d2hlcmU7IHRoZSBqb2IncyBvd24gc3Rkb3V0L3N0ZGVyciBnbyBleGFjdGx5IHdoZXJlIHRoZXkgd2VudCBiZWZvcmUsCiMgICAgIGJlY2F1c2UgdGhlIGNvbW1hbmQgc3RyaW5nIGlzIHBhc3NlZCB0aHJvdWdoIHVudG91Y2hlZC4KIwojIFRoZSBjb21tYW5kIGlzIHBhc3NlZCBCQVNFNjQtRU5DT0RFRC4gTm90IGZvciBzZWN1cml0eSAtLSBmb3IgcXVvdGluZzogdGhlc2UgbGluZXMgY29udGFpbiBzaW5nbGUKIyBxdW90ZXMsIGJhY2t0aWNrcywgYCRgLCBgJWAgYW5kIG5lc3RlZCBxdW90ZXMsIGFuZCBldmVyeSBuYWl2ZSByZS1xdW90aW5nIG9mIGEgY3JvbnRhYiBsaW5lIGlzIGEKIyBjaGFuY2UgdG8gc2lsZW50bHkgY2hhbmdlIHdoYXQgaXQgcnVucy4gQmFzZTY0IGNhbm5vdCBiZSBtaXNxdW90ZWQsIGFuZCB0aGUgaW5zdGFsbGVyIHZlcmlmaWVzIHRoYXQKIyBkZWNvZGluZyBlYWNoIHdyYXBwZWQgcGF5bG9hZCByZXByb2R1Y2VzIHRoZSBvcmlnaW5hbCBsaW5lIGJ5dGUgZm9yIGJ5dGUuCiMKIyBVU0FHRQojICAgICBjcm9uLXdyYXAuc2ggPG5hbWU+IDxiYXNlNjQtb2YtdGhlLWNvbW1hbmQ+CiMKIyBFWElUIENPREU6IHRoZSBjb21tYW5kJ3Mgb3duIGV4aXQgY29kZSwgYWx3YXlzLiBBIHdyYXBwZXIgdGhhdCBzd2FsbG93ZWQgaXQgd291bGQgYmUgYSBuZXcgaW5zdGFuY2UKIyBvZiB0aGUgcHJvYmxlbSBpdCBleGlzdHMgdG8gZml4LgpzZXQgLXVvIHBpcGVmYWlsCgojIFRIRSBXUkFQUEVSJ1MgT1dOIEZBSUxVUkUgTVVTVCBCRSBBUyBWSVNJQkxFIEFTIFRIRSBKT0InUy4KIyBNZWFzdXJlZCAyMDI2LTEwLTAyOiB0aGUgcGFpbi1jaGVjayBsaW5lIHdhcyB3cml0dGVuIHdpdGggaXRzIGNvbW1hbmQgUkFXIGluc3RlYWQgb2YgZW5jb2RlZAojIChgY3Jvbi13cmFwLnNoIHBhaW4tY2hlY2sgL2hvbWUvemFiei9iaW4vcGFpbi1jaGVjay5weSAtLXdyaXRlLXN0YXR1c2ApLiBgYmFzZTY0IC1kYCByZWZ1c2VkIGl0LAojIHRoaXMgc2NyaXB0IGV4aXRlZCAyIEJFRk9SRSB3cml0aW5nIGEgcnVuIHJlY29yZCwgYW5kIGNyb24ncyBvbmx5IG91dHB1dCB3ZW50IHRvIGEgbG9nIG5vYm9keQojIHJlYWRzIC0tIHNvIHRoZSBwYWluIGNoZWNrIHN1aXRlIGhhZCBub3QgcnVuIGZvciAzNyBoLCBpdHMgd2F0Y2hkb2cgc291cmNlIHJlcG9ydGVkICJzaWduYWwKIyB1bnJlYWRhYmxlIiByYXRoZXIgdGhhbiBmaWxpbmcgd29yaywgYW5kIHRoZSBsb29wIHRoYXQgY2xvc2VzIGZpeGVkIGRlZmVjdHMgd2FzIHNpbGVudGx5IGRlYWQuCiMgQSByZWZ1c2FsIG5vdyBsZWF2ZXMgYSByb3cgaW4gdGhlIHNhbWUgcnVucy50c3YgZXZlcnkgb3RoZXIgam9iIHdyaXRlcywgd2l0aCByYz0yLCBzbwojICJ0aGlzIGpvYiBoYXMgbm90IHJ1biIgaXMgYSB0aGluZyB0aGF0IGNhbiBiZSByZWFkIGluc3RlYWQgb2YgaW5mZXJyZWQuCnJlZnVzZSgpIHsKICBsb2NhbCB3aHk9IiQxIiBkaXIgc3RhbXAKICBkaXI9IiR7Q1JPTl9TVEFUVVNfRElSOi0kSE9NRS8uY3Jvbi1zdGF0dXN9IgogIG1rZGlyIC1wICIkZGlyIiAyPi9kZXYvbnVsbCB8fCB0cnVlCiAgc3RhbXA9IiQoZGF0ZSAtdSAnKyVZLSVtLSVkVCVIOiVNOiVTWicpIgogIHByaW50ZiAnJXNcdCVzXHQyXHQwXHRjcm9uLXdyYXAgUkVGVVNFRDogJXNcbicgIiRzdGFtcCIgIiROQU1FIiAiJHdoeSIgPj4gIiRkaXIvcnVucy50c3YiIDI+L2Rldi9udWxsIHx8IHRydWUKICBlY2hvICJjcm9uLXdyYXA6ICR3aHkiID4mMgogIGV4aXQgMgp9CgpOQU1FPSIkezE6LXVubmFtZWR9IgpQQVlMT0FEPSIkezI6LX0iCmlmIFsgLXogIiRQQVlMT0FEIiBdOyB0aGVuCiAgcmVmdXNlICJubyBwYXlsb2FkIGZvciAkTkFNRSAtLSB0aGUgY3JvbnRhYiBsaW5lIGlzIG5vdCB3cmFwcGVkIChydW4gfi9iaW4vd3JhcC1jcm9udGFiLnB5IC0taW5zdGFsbCkiCmZpCgpDTUQ9IiQocHJpbnRmICclcycgIiRQQVlMT0FEIiB8IGJhc2U2NCAtZCAyPi9kZXYvbnVsbCkiIHx8IHsKICByZWZ1c2UgInBheWxvYWQgZm9yICROQU1FIGlzIG5vdCB2YWxpZCBiYXNlNjQgLS0gdGhlIGNyb250YWIgbGluZSBpcyBub3Qgd3JhcHBlZCAocnVuIH4vYmluL3dyYXAtY3JvbnRhYi5weSAtLWluc3RhbGwpIgp9CmlmIFsgLXogIiRDTUQiIF07IHRoZW4KICByZWZ1c2UgInBheWxvYWQgZm9yICROQU1FIGRlY29kZWQgdG8gbm90aGluZyAtLSByZWZ1c2luZyB0byBydW4gYW4gZW1wdHkgY29tbWFuZCIKZmkKClNUQVRFX0RJUj0iJHtDUk9OX1NUQVRVU19ESVI6LSRIT01FLy5jcm9uLXN0YXR1c30iCm1rZGlyIC1wICIkU1RBVEVfRElSIgpTVEFNUD0iJChkYXRlIC11ICcrJVktJW0tJWRUJUg6JU06JVNaJykiClNUQVJUPSIkKGRhdGUgKyVzKSIKCkVSUkZJTEU9IiQobWt0ZW1wICIke1RNUERJUjotL3RtcH0vY3Jvbi13cmFwLVhYWFhYWCIpIgojIFRoZSBjb21tYW5kIHJ1bnMgd2l0aCBpdHMgT1JJR0lOQUwgdGV4dCwgdW5kZXIgYHNoIC1jYCwgc28gZXZlcnkgcmVkaXJlY3Rpb24gYW5kIGV2ZXJ5IHNoZWxsCiMgY29uc3RydWN0IGluIHRoZSBjcm9udGFiIGxpbmUgYmVoYXZlcyBleGFjdGx5IGFzIGl0IGRpZCB1bndyYXBwZWQuCnNoIC1jICIkQ01EIiAyPiIkRVJSRklMRSIKUkM9JD8KCkVORD0iJChkYXRlICslcykiCkVSUlRBSUw9IiQodGFpbCAtYyA0MDAgIiRFUlJGSUxFIiAyPi9kZXYvbnVsbCB8IHRyICdcblx0JyAnICAnIHwgY3V0IC1jMS0xNjApIgpybSAtZiAiJEVSUkZJTEUiCgpwcmludGYgJyVzXHQlc1x0JXNcdCVzXHQlc1xuJyAiJFNUQU1QIiAiJE5BTUUiICIkUkMiICIkKChFTkQgLSBTVEFSVCkpIiAiJEVSUlRBSUwiID4+ICIkU1RBVEVfRElSL3J1bnMudHN2IgoKIyBLZWVwIHRoZSBsb2cgZnJvbSBncm93aW5nIHdpdGhvdXQgYm91bmQ6IGl0IGlzIG9uZSBsaW5lIHBlciBydW4sIGFuZCB0aGUgZmFuLW91dCBydW5zIGV2ZXJ5IG1pbnV0ZS4KU0laRT0iJChzdGF0IC1jJXMgIiRTVEFURV9ESVIvcnVucy50c3YiIDI+L2Rldi9udWxsIHx8IGVjaG8gMCkiCmlmIFsgIiR7U0laRTotMH0iIC1ndCA1MDAwMDAwIF07IHRoZW4KICB0YWlsIC1uIDIwMDAwICIkU1RBVEVfRElSL3J1bnMudHN2IiA+ICIkU1RBVEVfRElSL3J1bnMudHN2LnRtcCIgJiYgbXYgIiRTVEFURV9ESVIvcnVucy50c3YudG1wIiAiJFNUQVRFX0RJUi9ydW5zLnRzdiIKZmkKCmV4aXQgIiRSQyIK' | base64 -d > /usr/local/bin/cron-wrap.sh
chmod 755 /usr/local/bin/cron-wrap.sh
sha256sum /usr/local/bin/cron-wrap.sh
echo "expected 8db5fe43291405dcc5ed26736e5ac2b02466ba7d2ef51c6aa9a04e88ec1ffa14"
mkdir -p /root/.cron-status

echo "===== 3. ceo-kernel checkout state"
find /root/ceo-kernel -type f | wc -l
find /root/ceo-kernel-var -type f | wc -l
cd /root/ceo-kernel && git log --oneline -1 && echo "--- porcelain:" && git status --porcelain | head -5

echo "===== 4. patch ck/sources.py: the authority moved to the cloud"
python3 - <<'PY'
import pathlib
p = pathlib.Path('/root/ceo-kernel/ck/sources.py')
s = p.read_text()
a = 'AUTHORITATIVE_DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"'
b = ('AUTHORITATIVE_DB = os.environ.get("CEO_KERNEL_DB",\n'
     '                    "/home/zabz/personal-secretary-mvp/data/secretary.db")')
c = 'AUTHORITATIVE_HOST = "secratary"'
d = 'AUTHORITATIVE_HOST = os.environ.get("CEO_KERNEL_AUTHORITY_HOST", "secratary")'
assert a in s, 'DB anchor not found'
assert c in s, 'HOST anchor not found'
if 'CEO_KERNEL_DB' not in s:
    s = s.replace(a, b).replace(c, d)
    p.write_text(s)
    print('patched')
else:
    print('already patched')
PY
cd /root/ceo-kernel && git diff --stat && git diff | head -30

echo "===== 5. FIRST DELIBERATE RUN, timed"
export CEO_KERNEL_STATE=/root/ceo-kernel-var
export CEO_KERNEL_DB=/root/authority.db
export CEO_KERNEL_AUTHORITY_HOST=secratary-cloud
S=$(date +%s)
/root/ceo-kernel/scripts/run-sentinel.sh
RC=$?
E=$(date +%s)
echo "wrapper_rc=$RC first_run_seconds=$((E-S))"
tail -2 /root/ceo-kernel-var/run.log
ls -la /root/ceo-kernel-var
python3 - <<'PY'
import json
d = json.load(open('/root/ceo-kernel-var/latest.json'))
print('report_time', d.get('generated_at') or d.get('at') or d.get('time'))
print('host', d.get('host'))
print('database', json.dumps(d.get('database'))[:300])
print('summary', json.dumps(d.get('summary'))[:300])
print('attention', [f.get('check') for f in d.get('findings', []) if f.get('needs_attention')][:25])
PY

echo "===== 6. schedule it (name unchanged: run-sentinel)"
CMD="CEO_KERNEL_STATE=/root/ceo-kernel-var CEO_KERNEL_DB=/root/authority.db CEO_KERNEL_AUTHORITY_HOST=secratary-cloud /root/ceo-kernel/scripts/run-sentinel.sh"
PAYLOAD=$(printf '%s' "$CMD" | base64 -w0)
echo "payload=$PAYLOAD"
{
  crontab -l 2>/dev/null | grep -v 'run-sentinel'
  echo "# 140-port-core: run-sentinel ported from office /home/zabz/ceo-kernel/scripts/run-sentinel.sh 2026-10-11"
  echo "*/5 * * * * /usr/local/bin/cron-wrap.sh run-sentinel $PAYLOAD"
} | crontab -
echo "--- crontab -l:"; crontab -l
echo "--- ls /etc/cron.d:"; ls /etc/cron.d/

echo "===== 7. STAGE the memory ceiling (NOT applied; company-api NOT restarted)"
cat > /root/company-api-memory.staged.conf <<'EOF'
# company-api memory ceiling -- STAGED 2026-10-11 by workstream 140, NOT APPLIED.
# Rationale and numbers: docs/mesh/140-PORT-CORE-AND-GAPS.md section B1.
# Apply with (this restarts the public API exactly once):
#   install -o root -g root -m 644 /root/company-api-memory.staged.conf \
#       /etc/systemd/system/company-api.service.d/30-memory.conf
#   systemctl daemon-reload && systemctl restart company-api
#   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8002/health
# Revert with: rm /etc/systemd/system/company-api.service.d/30-memory.conf && systemctl daemon-reload && systemctl restart company-api
[Service]
MemoryHigh=5500M
MemoryMax=6800M
MemorySwapMax=3072M
EOF
cat /root/company-api-memory.staged.conf
echo "--- current effective limits (unchanged):"
systemctl show company-api -p MemoryHigh -p MemoryMax -p MemorySwapMax -p MemoryPeak -p MemoryCurrent

echo "===== 8. disk after"
df -h / | tail -1
echo "===== DONE"
