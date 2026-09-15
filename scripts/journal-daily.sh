#!/usr/bin/env bash
# journal-daily.sh — the macOS twin of scripts/journal-daily.ps1.
#
# THE OWNER'S REQUIREMENT (2026-09-15): her machines must keep their own journal, handoff notes and
# pain points, evolving, and hold whatever needs HER attention -- not merely be able to read the
# owner's. This is that mechanism for the Mac, and it is a scheduled job on purpose: a journal that
# depends on the model choosing to write it stops existing the first busy day.
#
# WHY A SEPARATE FILE RATHER THAN THE POWERSHELL ONE
# macOS ships bash and Python but not PowerShell. The two scripts do the same job in the two idioms the
# machines actually have; the entry format and the provenance are deliberately identical, so the
# journal reads the same whichever machine wrote it.
#
# Each entry answers:
#   CHANGED         -- what moved in the shop's repos in the last day, read from git so it is evidence
#                      rather than a claim.
#   NEEDS ATTENTION -- the contents of journal/attention/, which is how work that needs HER (not the
#                      agent) surfaces instead of being buried in a chat.
#   OPEN PAIN/NEXT  -- left for the agent, with the command shown so it knows how.
#
# PROVENANCE: the entry carries the hostname it was written on, which is the labelling the owner asked
# for and what keeps her notes distinguishable from his.
set -uo pipefail

H="$HOME"
REPO="${HARNESS_REPO:-$H/code/harness-config}"
JOURNAL_PY="$REPO/journal/tools/journal.py"
MACHINE="$(hostname)"
QUIET="${QUIET:-}"

if [ ! -f "$JOURNAL_PY" ]; then
  echo "journal-daily: journal.py not found at $JOURNAL_PY; nothing written"
  exit 1
fi

NODE=""
for c in "$H/.local/node-v24.12.0-darwin-arm64/bin/node" "$(command -v node 2>/dev/null)"; do
  [ -n "$c" ] && [ -x "$c" ] && NODE="$c" && break
done

TMP="$(mktemp -t journal-daily)"
trap 'rm -f "$TMP"' EXIT

{
  echo "## Changed"
  echo
  any=0
  for r in "$H/lpt-hub" "$H/code/lpt-hub" "$H/code/personal-secretary-mvp"; do
    [ -d "$r/.git" ] || continue
    recent="$(git -C "$r" log --since='26 hours ago' --format='- %h %s' 2>/dev/null | head -5)"
    if [ -n "$recent" ]; then
      any=1
      echo "- $(basename "$r"):"
      printf '%s\n' "$recent" | sed 's/^/  /'
    fi
  done
  [ "$any" -eq 0 ] && echo "- no commits in the shop repos in the last day"

  echo
  echo "## Needs attention"
  echo
  ATT="$REPO/journal/attention"
  if [ -d "$ATT" ] && [ -n "$(ls -A "$ATT" 2>/dev/null)" ]; then
    ls -1t "$ATT" 2>/dev/null | head -15 | sed 's/^/- /'
  else
    echo "- nothing filed for her attention"
  fi

  echo
  echo "## Open pain"
  echo
  echo "- (agent: append with  python3 journal/tools/journal.py append pain --title \"...\" --body-file <file>)"
  echo
  echo "## Next"
  echo
  echo "- (agent: fill this in as you work)"
} > "$TMP"

[ -n "$QUIET" ] || echo "journal-daily: appending 'Daily note from $MACHINE'"
python3 "$JOURNAL_PY" append handoff --title "Daily note from $MACHINE" --body-file "$TMP" 2>&1 | tail -3

# Publish if the remote is reachable. If not, the entry stays local and that is acceptable -- it is
# still there for the next session on this machine.
cd "$REPO" || exit 0
if [ -n "$(git status --porcelain -- journal 2>/dev/null)" ]; then
  git add journal 2>/dev/null
  git -c user.name='Yocheved (manager)' -c user.email='yocheved@abletelsolutions.com' \
      commit -q -m "journal: daily handoff from $MACHINE" 2>&1 | head -2
  if git push origin HEAD 2>&1 | tail -2; then :; else
    echo "journal-daily: entry committed locally (remote not reachable)"
  fi
else
  echo "journal-daily: nothing new to publish"
fi
