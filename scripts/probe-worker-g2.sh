#!/usr/bin/env bash
# Read the worker's remaining G2 finding and the ids its own patch declares.
cd /home/zabz/code/harness-config/dsh-update || exit 2
node -e '
const fs = require("fs");
const p = process.env.HOME + "/code/harness-config/dsh-update/state/candidates/0.2.1-rc.2/verify.json";
const j = JSON.parse(fs.readFileSync(p, "utf8"));
for (const g of (j.gates || [])) {
  if (g.id === "G2") console.log("G2 :: " + String(g.detail || "").slice(0, 700));
}
'
echo
echo "=== ids declared by the LIVE web patch ==="
grep -oE "id: '[a-z0-9-]+'" "$HOME/.dsh/profiles/web/cordis.patch.yml" 2>/dev/null | sort -u | tr '\n' ' '
echo
echo "=== rows in the candidate's composed tree (count) ==="
node -e '
const fs = require("fs");
const p = process.env.HOME + "/code/harness-config/dsh-update/state/candidates/0.2.1-rc.2/tree.json";
const j = JSON.parse(fs.readFileSync(p, "utf8"));
const rows = j.rows || j.tree?.rows || [];
console.log(Array.isArray(rows) ? rows.length : "no rows array");
'
