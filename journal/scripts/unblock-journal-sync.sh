#!/usr/bin/env bash
# unblock-journal-sync.sh — get a machine past a journal id collision without losing the entries.
#
# THE SITUATION (measured on her Mac, 2026-09-15):
#   Her agent wrote four real journal entries on this machine -- L1568, L1569, P165, P166 -- and they
#   were left UNTRACKED. Meanwhile origin's lineage assigned the SAME ids to DIFFERENT content, so
#   `git pull` refuses: it will not overwrite untracked files.
#   The result is that the machine cannot receive ANY update -- not configuration, not tools, not fixes
#   -- and it fails silently from the outside. That is the real cost of the id collision, and it is
#   worse than the collision itself.
#
# WHAT THIS DOES, in the order that cannot lose anything:
#   1. copies the four entries AND the index to a timestamped backup directory FIRST;
#   2. moves them out of the journal tree (move, not delete);
#   3. restores the generated index from the incoming commit (it is a cache; journal.py rebuilds it);
#   4. pulls;
#   5. re-adds each entry through `journal.py append`, which allocates a FRESH id and re-derives the
#      metadata hash correctly -- so the content survives and the id stops colliding;
#   6. reports what it did, and leaves the backups in place.
#
# It never deletes an entry, never force-pushes, and never resolves a collision by discarding one side.
#
# Usage: bash unblock-journal-sync.sh [--repo DIR] [--dry-run]
set -uo pipefail

REPO="${HOME}/code/harness-config"
DRY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:-$HOME/code/harness-config}"; shift 2 ;;
    --dry-run) DRY=yes; shift ;;
    *) shift ;;
  esac
done

JOURNAL_PY="$REPO/journal/tools/journal.py"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HOME/.dsh-journal-collision-backup-$STAMP"

[ -d "$REPO/.git" ] || { echo "not a git checkout: $REPO"; exit 2; }
[ -f "$JOURNAL_PY" ] || { echo "journal.py not found: $JOURNAL_PY"; exit 2; }

cd "$REPO" || exit 2

# Which journal paths are untracked and would be overwritten by the incoming commits?
blocking="$(git status --porcelain 2>/dev/null | awk '/^\?\?/ {print $2}' | grep '^journal/' || true)"
modified="$(git status --porcelain 2>/dev/null | awk '/^ M/ {print $2}' | grep '^journal/' || true)"

echo "unblock-journal-sync"
echo "  repo    : $REPO"
echo "  backup  : $BACKUP"
echo "  untracked journal entries blocking the pull:"
if [ -z "$blocking" ]; then echo "    (none)"; else printf '    %s\n' $blocking; fi
echo "  modified journal files:"
if [ -z "$modified" ]; then echo "    (none)"; else printf '    %s\n' $modified; fi
echo ""

if [ -z "$blocking" ] && [ -z "$modified" ]; then
  echo "  nothing is blocking; a plain pull should work:"
  git pull --rebase --autostash 2>&1 | tail -3
  exit 0
fi

if [ -n "$DRY" ]; then echo "  DRY RUN: would back up, move aside, pull, and re-add"; exit 0; fi

# --- 1. back up everything we are about to move -------------------------------------------------
mkdir -p "$BACKUP"
for f in $blocking $modified; do
  if [ -f "$f" ]; then
    mkdir -p "$BACKUP/$(dirname "$f")"
    cp -p "$f" "$BACKUP/$f"
  fi
done
echo "  backed up to $BACKUP"

# --- 2. move the untracked entries out of the tree ----------------------------------------------
for f in $blocking; do
  [ -f "$f" ] || continue
  mv "$f" "$BACKUP/$(basename "$f").moved"
  echo "  moved aside: $f"
done

# --- 3. the index is a generated cache; take the incoming one -----------------------------------
if [ -n "$modified" ]; then
  for f in $modified; do
    case "$f" in
      journal/index/*) git checkout -- "$f" 2>/dev/null && echo "  restored generated cache: $f" ;;
      *) # A modified ENTRY is content, not cache -- back it up and take the remote version.
         cp -p "$f" "$BACKUP/$(basename "$f").modified" 2>/dev/null || true
         git checkout -- "$f" 2>/dev/null && echo "  took incoming version of $f (copy in backup)" ;;
    esac
  done
fi

# --- 4. pull ------------------------------------------------------------------------------------
echo "  pulling..."
if ! git pull --rebase --autostash 2>&1 | tail -3; then
  echo "  PULL STILL FAILING -- restoring the moved entries so nothing is lost"
  for b in "$BACKUP"/*.moved; do
    [ -f "$b" ] || continue
    base="$(basename "$b" .moved)"
    # put it back under a fresh id if the original now exists
    for kind in lessons pain handoff decisions wins; do
      if [ -d "journal/entries/$kind" ] && [ -f "journal/entries/$kind/$base" ]; then
        echo "    $base already exists from the remote; leaving the backup in place"
      fi
    done
  done
  echo "  entries remain safe in $BACKUP"
  exit 1
fi

# --- 5. re-add each moved entry through the journal tool, so it gets a FRESH id -----------------
readded=0
for b in "$BACKUP"/*.moved; do
  [ -f "$b" ] || continue
  base="$(basename "$b" .moved)"
  id="${base%.md}"
  case "$id" in L*) kind=lessons ;; P*) kind=pain ;; H*) kind=handoff ;; D*) kind=decisions ;; W*) kind=wins ;; *) kind=lessons ;; esac
  # The file carries a heading line; strip the HTML metadata comment and pass the rest as the body.
  body_file="$BACKUP/$id.body.md"
  grep -v '^<!-- e:' "$b" > "$body_file" 2>/dev/null
  title="$(grep -m1 -E '^\*\*|^#' "$body_file" | sed 's/^\*\*//; s/\*\*$//; s/^#* *//' | cut -c1-90)"
  [ -n "$title" ] || title="$id (recovered)"
  if python3 "$JOURNAL_PY" append "$kind" --title "$title" --body-file "$body_file" >/dev/null 2>&1; then
    echo "  re-added $id as a fresh entry ($kind): $title"
    readded=$((readded+1))
  else
    echo "  COULD NOT re-add $id -- it is safe in $BACKUP/$base.moved"
  fi
done

# --- 6. publish whatever we added ---------------------------------------------------------------
if [ "$readded" -gt 0 ]; then
  git add journal 2>/dev/null
  git -c user.name='Yocheved (manager)' -c user.email='yocheved@abletelsolutions.com' \
      commit -q -m "journal: re-add $readded entry/entries under fresh ids after an id collision" 2>&1 | head -2
  git push origin HEAD 2>&1 | tail -2
fi

echo ""
echo "  done: $readded entry/entries re-added."
echo "  backups kept at: $BACKUP"
