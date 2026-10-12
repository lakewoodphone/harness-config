#!/usr/bin/env bash
# port-kernel-to-cloud.sh -- runs ON secratary-cloud as root.
#
# WHY: the attention badge in every machine's Web GUI, and the phone's pill, read
# /dsh-attention.json from the phone gate, which projects ~/ceo-kernel-var/latest.json.
# That file is written by the ceo-kernel sentinel. After the 2026-10-11 cutover the
# sentinel only exists on the FROZEN office box, so the badge has been reading a report
# whose last row is 2026-10-11T20:20:06Z -- a stopped clock. This installs the sentinel
# on the authority, where the live database is.
#
# SAFETY: reads /root/authority.db mode=ro only; starts/stops/restarts NOTHING (the gate
# already reads the state path below, so it picks this up with no restart); touches only
# the root crontab, /root/ceo-kernel* and /root/kernel.bundle. Idempotent.
set -uo pipefail

KREPO=/root/ceo-kernel
KSTATE=/root/ceo-kernel-var
SEED=/root/ceo-kernel-var-seed
BUNDLE=/root/kernel.bundle
export CEO_KERNEL_STATE="$KSTATE"
export CEO_KERNEL_DB=/root/authority.db
export CEO_KERNEL_AUTHORITY_HOST=secratary-cloud

say() { printf '\n===== %s\n' "$*"; }

say "0. who / when / disk"
hostname -f; date -u; df -h / | tail -1

say "1. checkout from the bundle (offsets preserved: modes, LF bytes, history)"
if [ -d "$KREPO/.git" ]; then
  echo "already a git checkout"
else
  git clone -q "$BUNDLE" "$KREPO" || { echo "FAILED: clone"; exit 1; }
fi
cd "$KREPO" || exit 1
git log --oneline -1
echo "--- porcelain (empty = tree == HEAD):"
git status --porcelain
mkdir -p .runtime/deploy-backups
ls -l scripts/run-sentinel.sh

say "2. patch ck/sources.py: the authority moved to the cloud"
python3 - <<'PY'
import pathlib
p = pathlib.Path('/root/ceo-kernel/ck/sources.py')
s = p.read_text()
a = 'AUTHORITATIVE_DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"'
c = 'AUTHORITATIVE_HOST = "secratary"'
b = ('AUTHORITATIVE_DB = os.environ.get("CEO_KERNEL_DB",\n'
     '                    "/home/zabz/personal-secretary-mvp/data/secretary.db")')
d = 'AUTHORITATIVE_HOST = os.environ.get("CEO_KERNEL_AUTHORITY_HOST", "secratary")'
if 'CEO_KERNEL_DB' in s:
    print('already patched')
else:
    assert a in s, 'DB anchor not found'
    assert c in s, 'HOST anchor not found'
    p.write_text(s.replace(a, b).replace(c, d))
    print('patched')
PY
git diff --stat
git diff -- ck/sources.py | head -20

say "3. seed the state from the frozen anchor (trend continuity), then move marker"
mkdir -p "$KSTATE"
for f in latest.json history.jsonl run.log run.err; do
  if [ -f "$SEED/$f" ] && [ ! -f "$KSTATE/$f" ]; then cp -p "$SEED/$f" "$KSTATE/$f"; echo "seeded $f"; fi
done
if [ -d "$SEED/ha" ] && [ ! -d "$KSTATE/ha" ]; then cp -rp "$SEED/ha" "$KSTATE/ha"; echo "seeded ha/"; fi
printf '%s run-sentinel MOVED to the authority: state seeded from the frozen office box (secratary), which last wrote 2026-10-11T20:20:06Z\n' \
  "$(date -Is)" >> "$KSTATE/run.log"

say "4. FIRST DELIBERATE RUN, timed"
S=$(date +%s)
/root/ceo-kernel/scripts/run-sentinel.sh
RC=$?
DUR=$(( $(date +%s) - S ))
echo "wrapper_rc=$RC first_run_seconds=$DUR"
tail -2 "$KSTATE/run.log"
ls -la "$KSTATE" | head -12
python3 - <<'PY'
import json
d = json.load(open('/root/ceo-kernel-var/latest.json'))
db = d.get('database') or {}
s = d.get('summary') or {}
print('generatedAt      ', d.get('generatedAt'))
print('host             ', d.get('host'))
print('db.selected      ', db.get('selected'))
print('db.authoritative ', db.get('authoritative'))
print('db.host          ', db.get('host'))
print('db.tables        ', db.get('tables'))
print('summary          ', json.dumps(s))
att = [f for f in (d.get('findings') or []) if f.get('needs_attention')]
for f in att:
    print('  %-8s %-22s %s' % (f.get('severity'), f.get('check'), str(f.get('summary'))[:110]))
print('attention checks ', len(att))
PY

say "5. the gate already reads this path -- prove it serves a live reading, no restart"
curl -s http://127.0.0.1:3086/dsh-attention.json | head -c 500; echo
curl -s -o /dev/null -w 'tailnet_http=%{http_code}\n' https://secratary-cloud.tail93e6e6.ts.net/dsh-attention.json
python3 - <<'PY'
import json, urllib.request, datetime
raw = urllib.request.urlopen('http://127.0.0.1:3086/dsh-attention.json', timeout=10).read()
d = json.loads(raw)
age = None
try:
    t = datetime.datetime.fromisoformat(d['at'].replace('Z', '+00:00'))
    age = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()
except Exception:
    pass
print('gate read=%s age_seconds=%s host=%s total=%s attention=%s' %
      (d.get('read'), None if age is None else round(age, 1), d.get('host'), d.get('total'), d.get('attention')))
PY

say "6. schedule it (name unchanged: run-sentinel), cadence from the measured run"
if [ "$DUR" -gt 45 ]; then CRONSPEC="*/15"; else CRONSPEC="*/5"; fi
echo "measured ${DUR}s -> cadence $CRONSPEC"
CMD="CEO_KERNEL_STATE=$KSTATE CEO_KERNEL_DB=/root/authority.db CEO_KERNEL_AUTHORITY_HOST=secratary-cloud nice -n 10 $KREPO/scripts/run-sentinel.sh"
PAYLOAD=$(printf '%s' "$CMD" | base64 -w0)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
crontab -l > "/root/crontab.before-sentinel-port-$STAMP" 2>/dev/null
echo "crontab backed up to /root/crontab.before-sentinel-port-$STAMP ($(wc -l < /root/crontab.before-sentinel-port-$STAMP) lines)"
{
  crontab -l 2>/dev/null | grep -v 'run-sentinel'
  echo "# 168-attention-authority: run-sentinel ported from the frozen office box (docs/mesh/168-*)"
  echo "$CRONSPEC * * * * /usr/local/bin/cron-wrap.sh run-sentinel $PAYLOAD"
} | crontab -
echo "--- payload decodes to:"; printf '%s' "$PAYLOAD" | base64 -d; echo
echo "--- crontab tail:"; crontab -l | tail -4

say "7. prove the CRON path end to end (same wrapper, same payload, ledger row)"
/usr/local/bin/cron-wrap.sh run-sentinel "$PAYLOAD"
echo "--- ledger tail:"; tail -2 /root/.cron-status/runs.tsv
echo "--- state after the wrapper run:"; ls -l --time-style=full-iso "$KSTATE/latest.json" "$KSTATE/history.jsonl"
tail -2 "$KSTATE/run.log"

say "8. what the badge will now read (freshness is the whole point)"
python3 - <<'PY'
import json, datetime
d = json.load(open('/root/ceo-kernel-var/latest.json'))
t = datetime.datetime.fromisoformat(d['generatedAt'].replace('Z', '+00:00'))
now = datetime.datetime.now(datetime.timezone.utc)
print('report age = %.1f s  host=%s  attention=%s/%s' %
      ((now - t).total_seconds(), d.get('host'), (d.get('summary') or {}).get('attention'), (d.get('summary') or {}).get('total')))
PY

say "9. disk after"
df -h / | tail -1
echo "DONE"
