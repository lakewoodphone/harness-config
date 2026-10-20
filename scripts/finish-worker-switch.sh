#!/usr/bin/env bash
# After the successful switch: the pin recorded the STAGING prefix instead of the live root. Correct that one field
# (with a backup and a history row), confirm the launcher knob, and remove only the junk this work created.
set -uo pipefail
U=/home/zabz/code/harness-config/dsh-update
LIVE=/home/zabz/dsh-engine
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

echo "=== windows.json dshInstall ==="
python3 - <<'PY'
import json
p = "/home/zabz/code/harness-config/multi-window/windows.json"
try:
    d = json.load(open(p))
    print("  dshInstall:", d.get("dshInstall", "(absent)"))
except Exception as e:
    print("  could not read:", e)
PY

echo "=== pin before ==="
python3 -c "import json;d=json.load(open('$U/state/pin.json'));print(' ',d['version'],'|',d['installRoot'])"

echo "=== repairing installRoot -> $LIVE (the tree the unit actually runs) ==="
cp -p "$U/state/pin.json" "$U/state/pin.json.bak-pinrepair-$STAMP"
python3 - "$U/state/pin.json" "$LIVE" <<'PY'
import json, os, sys
p, live = sys.argv[1], sys.argv[2]
d = json.load(open(p))
before = d.get("installRoot")
d["installRoot"] = live
d["enginePath"] = os.path.join(live, "node_modules/@deepseek-ai/dsh/lib/bin.js")
json.dump(d, open(p, "w"), indent=2)
open(p, "a").write("\n")
h = os.path.join(os.path.dirname(p), "..", "history", "events.tsv")
with open(h, "a") as fh:
    fh.write("\t".join([__import__("datetime").datetime.utcnow().isoformat() + "Z", os.uname().nodename.upper(),
                        "pin-repair", d["version"], "", "ok",
                        f"installRoot {before} -> {live}; promote() wrote the staging prefix"]) + "\n")
print("  installRoot now:", d["installRoot"])
PY

echo "=== pin after / status ==="
python3 -c "import json;d=json.load(open('$U/state/pin.json'));print(' ',d['version'],'|',d['installRoot'])"
cd "$U" && DSH_CONFIG_ROOT=/home/zabz/.dsh DSH_HOME=/home/zabz/.dsh DSH_LIVE_INSTALL=$LIVE \
  /home/zabz/.local/node/bin/node lib/cli.mjs status 2>&1 | head -8 | sed 's/^/  /'

echo "=== removing ONLY the junk this work created ==="
for d in /home/zabz/code/harness-config/dsh-update.from-engine-* \
         /home/zabz/code/harness-config/dsh-update.staged-0.2.1-rc.2* \
         /home/zabz/dsh-engine.staged-0.2.1-rc.2* ; do
  [ -e "$d" ] || continue
  echo "  rm -rf $d ($(du -sh "$d" 2>/dev/null | cut -f1))"
  rm -rf --one-file-system "$d"
done
echo "=== disk after ==="
df -Pk / | tail -1 | sed 's/^/  /'
echo "=== engine still serving ==="
systemctl is-active dsh-engine.service | sed 's/^/  unit: /'
curl -s -o /dev/null -w '  http -> %{http_code}\n' --max-time 6 http://127.0.0.1:3099/ || true
