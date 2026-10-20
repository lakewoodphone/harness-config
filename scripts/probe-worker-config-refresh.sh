#!/usr/bin/env bash
# Read-only: does anything on this box republish ~/.dsh config (which would undo a local patch edit)?
echo "=== crontab (non-comment) ==="
crontab -l 2>/dev/null | grep -vE '^[[:space:]]*#' | grep -vE '^[[:space:]]*$' | head -10
echo "=== systemd timers (all) ==="
systemctl list-timers --all --no-legend 2>/dev/null | head -8
echo "=== processes mentioning sync ==="
pgrep -af 'sync\.py|autosync|harness-sync' 2>/dev/null | head -5
echo "=== profile patch mtime / size ==="
stat -c '%y  %s bytes  %n' "$HOME/.dsh/profiles/web/cordis.patch.yml" 2>/dev/null
echo "=== three patch targets in that file ==="
for id in remote-fanout tool-subagent-remote spend-guard; do
  printf '  %-24s %s\n' "$id" "$(grep -c "id: '$id'" "$HOME/.dsh/profiles/web/cordis.patch.yml" 2>/dev/null)"
done
