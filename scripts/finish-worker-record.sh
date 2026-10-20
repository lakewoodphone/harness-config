#!/usr/bin/env bash
# Finish the record: check which cli.mjs this host runs, point the launcher knob at the tree the unit runs, and
# append the pin-repair history row that the earlier attempt failed to write (wrong path).
set -uo pipefail
R=/home/zabz/code/harness-config
U=$R/dsh-update
LIVE=/home/zabz/dsh-engine
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

echo "=== which cli.mjs is here? ==="
echo "  size: $(stat -c%s "$U/lib/cli.mjs") bytes"
grep -c 'const newRoot = live.root' "$U/lib/cli.mjs" 2>/dev/null | sed 's/^/  live.root fix present: /'
grep -c 'installRoot: eff.pin.installRootNew' "$U/lib/cli.mjs" 2>/dev/null | sed 's/^/  pin-write fix present: /'
grep -c 'DSH_CONFIG_ROOT' "$U/lib/cli.mjs" 2>/dev/null | sed 's/^/  config-root fix present: /'

echo "=== windows.json dshInstall -> $LIVE ==="
cp -p "$R/multi-window/windows.json" "$R/multi-window/windows.json.bak-dshinstall-$STAMP"
python3 - "$R/multi-window/windows.json" "$LIVE" <<'PY'
import json, sys
p, live = sys.argv[1], sys.argv[2]
d = json.load(open(p))
before = d.get("dshInstall", "(absent)")
d["dshInstall"] = live
with open(p, "w") as fh:
    json.dump(d, fh, indent=2)
    fh.write("\n")
print(f"  dshInstall {before} -> {live}")
PY

echo "=== history row (state/history/events.tsv) ==="
python3 - "$U" "$LIVE" <<'PY'
import datetime, json, os, sys
u, live = sys.argv[1], sys.argv[2]
pin = json.load(open(os.path.join(u, "state/pin.json")))
h = os.path.join(u, "state/history/events.tsv")
row = "\t".join([datetime.datetime.utcnow().isoformat() + "Z", os.uname().nodename.upper(), "pin-repair",
                 pin["version"], pin.get("predecessor", {}).get("version", ""), "ok",
                 f"installRoot and dshInstall corrected to {live}; promote() had written the staging prefix"])
with open(h, "a") as fh:
    fh.write(row + "\n")
print("  appended:", row[:120])
PY

echo "=== final status ==="
cd "$U" && DSH_CONFIG_ROOT=/home/zabz/.dsh DSH_HOME=/home/zabz/.dsh DSH_LIVE_INSTALL=$LIVE \
  /home/zabz/.local/node/bin/node lib/cli.mjs status 2>&1 | head -10 | sed 's/^/  /'
echo "=== launcher knob + unit ==="
python3 -c "import json;print('  dshInstall:', json.load(open('$R/multi-window/windows.json')).get('dshInstall'))"
systemctl is-active dsh-engine.service | sed 's/^/  unit: /'
curl -s -o /dev/null -w '  http -> %{http_code}\n' --max-time 6 http://127.0.0.1:3099/ || true
