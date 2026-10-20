#!/usr/bin/env bash
# Before swapping a 0.1.5 engine for 0.2.1 on a POSIX worker: does the profile anchor carry its own copies of the
# engine's packages (the "TWO COPIES" refusal that stopped the phone engine), and what actually starts 3099?
echo "=== profile anchors ==="
for d in "$HOME/.dsh/profiles/node_modules" "$HOME/.dsh/profiles/web/node_modules"; do
  if [ -d "$d" ]; then
    n=$(ls -1 "$d" 2>/dev/null | wc -l)
    deep=$(ls -d "$d"/@deepseek-ai 2>/dev/null | wc -l)
    echo "  $d : $n entries, @deepseek-ai present=$deep"
    ls -1 "$d" 2>/dev/null | head -6 | sed 's/^/      /'
  else
    echo "  $d : absent"
  fi
done
echo
echo "=== what starts the engine on 3099? ==="
pgrep -af 'bin\.js web' | head -3
echo "--- cron entry that may start it ---"
crontab -l 2>/dev/null | grep -iE 'dsh|engine' | head -5
echo "--- the mesh cron script, engine bits only ---"
grep -nE 'bin\.js|dsh-engine|nohup|systemctl' "$HOME/personal-secretary-mvp/scripts/mesh/node-agent-standalone-cron.sh" 2>/dev/null | head -8
echo
echo "=== backup verdict from the last run ==="
ls -dt "$HOME"/dsh-backup-* 2>/dev/null | head -1 | while read -r d; do
  python3 -c "import json,sys; j=json.load(open('$d/BACKUP-REPORT.json')); print(' ok=', j.get('ok'), 'files=', j.get('totalFiles') or j.get('files'), 'finishedAt=', j.get('finishedAt'))" 2>/dev/null || echo "  (no parseable report)"
done
