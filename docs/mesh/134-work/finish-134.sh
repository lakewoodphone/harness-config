set -u
say() { printf '\n=== %s ===\n' "$1"; }

say "0. install the crontab (exactly as generated, from docs/mesh/134-work/cloud-crontab.txt)"
cp /root/cloud-crontab.txt /root/crontab.candidate
crontab /root/crontab.candidate
crontab -l | grep -c cron-wrap.sh
crontab -l

say "1. prove cron-wrap.sh is byte-identical to what the local machine shipped"
sha256sum /usr/local/bin/cron-wrap.sh
printf 'expect f7945803c2a96cb3f367b99b23516fadf749fde1050df33b57c426e247c76b10\n'

say "2. deadman: the external switch. First: my key stays OUT of the pulse."
/usr/bin/python3 /usr/local/bin/authority-deadman.py; echo "authority-deadman rc=$?"
# A ledger name that has never existed before: this ping measures whether the AUTHORITY can reach
# the external service, and it deliberately carries no wake-queue context, so nothing about a
# different workstream's edits can make it report a number that is not mine.
/usr/local/bin/cron-wrap.sh deadman-witness-LOCAL "$(printf '%s' 'curl -sS -o /dev/null -w "%{http_code}" "$(grep -E "^HEALTHCHECKS_PING_URL=" /root/.sms-inbox/deadman.env | cut -d= -f2-)"' | base64 -w0)"; echo "witness rc=$?"

say "3. deadman: the external service's own record of this authority's pings"
python3 - <<'PY'
import json, os, urllib.request, datetime
env = {}
for line in open("/root/.sms-inbox/deadman.env"):
    if "=" in line:
        k, v = line.rstrip("\n").split("=", 1); env[k] = v
api = env.get("HEALTHCHECKS_API_KEY", "")
req = urllib.request.Request("https://healthchecks.io/api/v3/checks/",
                             headers={"X-Api-Key": api})
with urllib.request.urlopen(req, timeout=25) as r:
    d = json.load(r)
for c in d.get("checks", []):
    print(json.dumps({k: c.get(k) for k in
                      ("name", "status", "period", "grace", "last_ping", "n_pings", "ping_url")},
                     indent=1))
PY

say "4. prune-backups: refuse the anchor, prove the budget, then run it for real"
/usr/local/bin/prune-backups.sh /home/zabz/secretary-backups; echo "refusal rc=$? (3 expected)"
mkdir -p /var/lib/authority-snapshots/20260101T000000Z /var/lib/authority-snapshots/20260201T000000Z
/usr/local/bin/prune-backups.sh /var/lib/authority-snapshots --dry-run; echo "dry-run rc=$?"
echo "--- and for real (the two empty dirs above are the fixture; they are removed either way) ---"
/usr/local/bin/prune-backups.sh /var/lib/authority-snapshots; echo "apply rc=$?"
rmdir /var/lib/authority-snapshots/20260101T000000Z /var/lib/authority-snapshots/20260201T000000Z 2>/dev/null
ls -la /var/lib/authority-snapshots/; df -h / | tail -1

say "5. prune-backups: it must never touch the live database or its WAL"
ls -l /root/authority.db /root/authority.db-wal | awk '{print $5, $9}'

say "6. db-integrity-check: the gate, the selftest, and a real check on a tiny database"
/usr/bin/python3 /usr/local/bin/db-integrity-check.py --selftest; echo "selftest rc=$?"
/usr/bin/python3 /usr/local/bin/db-integrity-check.py --preflight-only --json; echo "preflight rc=$?"
python3 - <<'PY'
import sqlite3, subprocess, os, tempfile
d = tempfile.mkdtemp(prefix="dbic-proof-")
p = os.path.join(d, "tiny-authority.db")
c = sqlite3.connect(p); c.execute("CREATE TABLE t(a TEXT)"); c.execute("INSERT INTO t VALUES('x')")
c.commit(); c.close()
r = subprocess.run(["/usr/bin/python3", "/usr/local/bin/db-integrity-check.py",
                    "--snapshot", p, "--json"], capture_output=True, text=True)
print("rc=%d" % r.returncode); print(r.stdout.strip()); print(r.stderr.strip()[:400])
os.unlink(p); os.rmdir(d)
PY

say "7. nothing database-sized was left behind"
du -sh /root/.db-integrity 2>/dev/null; ls -la /root/.db-integrity/work 2>/dev/null; df -h / | tail -1

say "8. cron-target-guard: does it see the PAYLOAD, or only the wrapper?"
/usr/bin/python3 /usr/local/bin/cron-target-guard.py --selftest; echo "selftest rc=$?"
/usr/bin/python3 /usr/local/bin/cron-target-guard.py --json; echo "live rc=$? (1 = a finding)"
echo "--- and the same guard against a crontab with a deliberately dead target ---"
cp /root/crontab.candidate /root/crontab.broken
sed -i 's#/usr/local/bin/prune-backups.sh#/usr/local/bin/does-not-exist-4f2a.sh#' /root/crontab.broken
/usr/bin/python3 /usr/local/bin/cron-target-guard.py --crontab /root/crontab.broken; echo "fixture rc=$? (1 = it CAUGHT the dead target)"
rm -f /root/crontab.broken

say "9. cron-script-guard"
/usr/bin/python3 /usr/local/bin/cron-script-guard.py; echo "rc=$?"
cat /root/.cron-scripts/status.json 2>/dev/null | head -20

say "10. guard-registry / tree-integrity / tmpfs-reaper / store-write-check"
/usr/bin/python3 /usr/local/bin/guard-registry-check.py --write-status --json 2>&1 | head -25; echo "guard-registry rc=$?"
grep -E "cron_scripts_watched|present|ok" /root/.cron-scripts/status.json 2>/dev/null | head -5
/usr/local/bin/tmpfs-reaper.sh; echo "tmpfs-reaper rc=$?"; tail -2 /root/tmp-rescue/reaper.log 2>/dev/null
DF_TMP=$(df -Pm /tmp | awk 'NR==2{print $4}')
echo "cloud /tmp free = ${DF_TMP} MB (floor 600, target 1500) -- /tmp opts:"
findmnt -no FSTYPE,SIZE,OPTIONS /tmp
TREE_INTEGRITY_DRY_RUN=1 /bin/bash /usr/local/bin/tree-integrity-check.sh; echo "tree-integrity(dry-run) rc=$? (1 means the gate found something; see the log)"
tail -3 /root/.tree-integrity/check.log 2>/dev/null

say "11. every job through the wrapper, so the ledger has one row each"
for n in cron-target-guard cron-script-guard guard-registry report-offsite-age deadman prune-backups tmpfs-reaper tree-integrity-check db-integrity-check store-write-check; do
  /usr/local/bin/cron-wrap.sh "$n"; echo "  $n rc=$?"
done

say "12. THE LEDGER"
cat /root/.cron-status/runs.tsv

say "13. the authority is still serving after all of it"
systemctl is-active company-api cloudflared secretary-dashboard phone-redirector
curl -s -o /dev/null -w "local /health http=%{http_code}\n" -m 10 http://127.0.0.1:8002/health
curl -s -o /dev/null -w "public /health http=%{http_code}\n" -m 15 https://api.abletelsolutions.com/health
df -h / | tail -1
