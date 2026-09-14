#!/usr/bin/env bash
# verify-autosync.sh — the Linux half of the divergence proof, for scripts/autosync.sh.
#
# Run this ON A LINUX BOX (secratary). It needs bash + git + python3 with PyYAML, and it never
# touches anything outside the sandbox directory it creates:
#
#     HARNESS_REPO=/tmp/hc/autosync.sh HARNESS_STATE=/tmp/hc/state ... (all redirected per test)
#
# Tests, all against a scratch bare remote:
#   1  OLD (pre-fix) script + diverged clone  -> refuses, preserves nothing        (the defect)
#   2  NEW script + diverged clone            -> local commit preserved on refs/heads/diverged-*
#   2a NEW script + ahead but fast-forwardable-> plain push accepted, no side ref invented
#   3  NEW script + clean clone behind origin -> still fast-forwards and applies   (normal path)
#
# Usage:  bash _scratch/verify-autosync.sh [path-to-repo] [sandbox-root]
set -uo pipefail

REPO="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
ROOT="${2:-$REPO/_scratch/autosync-verify-linux-$(date -u +%Y%m%d-%H%M%S)}"
NEW="$REPO/scripts/autosync.sh"
FAIL=0

say()  { printf '   %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
ok()   { printf '   PASS  %s\n' "$*"; }
bad()  { printf '   FAIL  %s\n' "$*"; FAIL=$((FAIL+1)); }
head_() { printf '\n%s\n== %s\n%s\n' "==============================================================================" "$*" "=============================================================================="; }
check() { # check <condition-0|1> <message>   (0 = true)
  if [ "$1" -eq 0 ]; then ok "$2"; else bad "$2"; fi
}

mkdir -p "$ROOT"
printf 'repo:     %s\nsandbox:  %s\n' "$REPO" "$ROOT"

# ── the pre-fix script, exactly as it was before this change ────────────────────────────────────────
# Preferred source: a file dropped beside this harness (HARNESS_OLD_SCRIPT), because the pre-fix text is
# no longer in the history of a repo that only ever saw the new version. Fallback: the oldest commit
# touching scripts/autosync.sh that does not carry the fix marker.
OLD="${HARNESS_OLD_SCRIPT:-$ROOT/autosync-OLD.sh}"
if [ ! -s "$OLD" ]; then
  git -C "$REPO" show HEAD:scripts/autosync.sh > "$OLD" 2>/dev/null
  if grep -q 'PRESERVE FIRST' "$OLD" 2>/dev/null; then
    base="$(git -C "$REPO" log --format=%H --reverse -- scripts/autosync.sh | head -5 | while read -r c; do
              git -C "$REPO" show "$c:scripts/autosync.sh" 2>/dev/null | grep -q 'PRESERVE FIRST' || { echo "$c"; break; }
            done | head -1)"
    if [ -n "$base" ]; then git -C "$REPO" show "$base:scripts/autosync.sh" > "$OLD" 2>/dev/null; else : > "$OLD"; fi
  fi
fi
if [ -s "$OLD" ] && ! grep -q 'PRESERVE FIRST' "$OLD"; then
  say "pre-fix script recovered: $(wc -c < "$OLD" | tr -d ' ') bytes"
else
  bad "could not recover the pre-fix scripts/autosync.sh — TEST 1 will be skipped"
  OLD=""
fi

seed_repo() { # seed_repo <path>
  local p="$1"
  mkdir -p "$p/scripts" "$p/settings"
  cp "$REPO/scripts/sync.py" "$p/scripts/sync.py"
  printf '# synthetic seed for verification\nagent-default-model:\n  provider: deepseek-official\n  model: deepseek-flash\n' > "$p/settings/base.yaml"
  git -C "$p" init -q --initial-branch=master
  git -C "$p" add -A
  git -C "$p" -c user.name=verify -c user.email=verify@localhost commit -q -m seed
}

sandbox() { # sandbox <name> -> sets SB_REMOTE SB_CLONE SB_STATE SB_HOME
  local name="$1" root="$ROOT/$1"
  SB_ROOT="$root"; SB_REMOTE="$root/remote.git"; SB_CLONE="$root/clone"
  SB_STATE="$root/state"; SB_HOME="$root/home"
  mkdir -p "$SB_HOME/.dsh/.agent-presets"
  git init -q --bare --initial-branch=master "$SB_REMOTE"
  seed_repo "$root/seed"
  git -C "$root/seed" remote add origin "$SB_REMOTE" 2>/dev/null
  git -C "$root/seed" push -q origin master
  git clone -q "$SB_REMOTE" "$SB_CLONE"
  git -C "$SB_CLONE" branch --set-upstream-to=origin/master master >/dev/null 2>&1
}

run_autosync() { # run_autosync <script>
  HARNESS_REPO="$SB_CLONE" HARNESS_STATE="$SB_STATE" \
  HARNESS_SYNC_STATUS_DIR="$SB_HOME/.dsh-sync-status" DSH_HOME="$SB_HOME/.dsh" \
    bash "$1" > "$SB_ROOT/run.out" 2>&1
  RUN_CODE=$?
  cat "$SB_ROOT/run.out"
}

show_status() {
  note "per-host record  $SB_STATE/status.json"
  [ -f "$SB_STATE/status.json" ] && cat "$SB_STATE/status.json" || echo "   (absent)"
  note "monitor record    $SB_HOME/.dsh-sync-status/status.json"
  [ -f "$SB_HOME/.dsh-sync-status/status.json" ] && cat "$SB_HOME/.dsh-sync-status/status.json" || echo "   (absent)"
}

jget() { # jget <file> <key>  — tiny JSON reader, no jq dependency
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); v=d.get(sys.argv[2]); print(json.dumps(v) if not isinstance(v,str) else v)' "$1" "$2" 2>/dev/null
}

diverge() { # make clone ahead 1 and origin ahead 1
  git -C "$SB_CLONE" -c user.name=verify -c user.email=verify@localhost commit -q --allow-empty -m "$1 local (must survive)"
  git -C "$SB_ROOT/seed" -c user.name=verify -c user.email=verify@localhost commit -q --allow-empty -m 'upstream moved (must not be lost)'
  git -C "$SB_ROOT/seed" push -q origin master
  note "clone counts (behind/ahead): $(git -C "$SB_CLONE" rev-list --left-right --count origin/master...HEAD)"
}

# ════════════════════════════════════════════════════════════════════════════════════════════════════
head_ 'TEST 1 — PRE-FIX script, diverged clone: the defect'
if [ -n "$OLD" ]; then
  sandbox t1-old-diverged
  diverge old
  run_autosync "$OLD"
  echo "   exit code: $RUN_CODE"
  show_status
  refs="$(git -C "$SB_REMOTE" for-each-ref --format='%(refname)')"
  note "remote refs after run: $(echo "$refs" | tr '\n' ' ')"
  check "$([ "$RUN_CODE" -eq 1 ]; echo $?)" 'pre-fix script exits 1 (attention)'
  case "$refs" in *diverged*) check 1 'pre-fix script pushed NO side ref — nothing preserved';;
                *) check 0 'pre-fix script pushed NO side ref — nothing preserved';; esac
  [ -f "$SB_HOME/.dsh-sync-status/status.json" ] && check 1 'pre-fix script writes no monitor status file' \
                                                 || check 0 'pre-fix script writes no monitor status file'
fi

# ════════════════════════════════════════════════════════════════════════════════════════════════════
head_ 'TEST 2 — NEW script, same divergence: preserve first'
sandbox t2-new-diverged
diverge new
LOCAL_SHA="$(git -C "$SB_CLONE" rev-parse HEAD)"
REMOTE_MASTER_BEFORE="$(git -C "$SB_REMOTE" rev-parse master)"
run_autosync "$NEW"
echo "   exit code: $RUN_CODE"
show_status
note 'remote refs after run:'
git -C "$SB_REMOTE" for-each-ref --format='   %(refname) %(objectname)'
SAFE_HOST="$(hostname | tr -d '\n' | tr -c 'A-Za-z0-9._-' '-')"
EXPECTED_REF="refs/heads/diverged-$SAFE_HOST-$(date -u +%Y%m%d)"
SIDE_SHA="$(git -C "$SB_REMOTE" rev-parse "$EXPECTED_REF" 2>/dev/null || echo none)"
SYNC_JSON="$SB_HOME/.dsh-sync-status/status.json"
check "$([ "$RUN_CODE" -eq 1 ]; echo $?)" 'new script still exits 1 — divergence is reported, not hidden'
check "$([ "$SIDE_SHA" != none ]; echo $?)" "side ref $EXPECTED_REF exists on the remote"
check "$([ "$SIDE_SHA" = "$LOCAL_SHA" ]; echo $?)" 'the local commit is ON the remote under the side ref (same object)'
check "$([ "$(jget "$SYNC_JSON" local_commits_preserved)" = true ]; echo $?)" 'monitor status: local_commits_preserved = true'
check "$([ "$(jget "$SYNC_JSON" ahead)" = 1 ] && [ "$(jget "$SYNC_JSON" behind)" = 1 ]; echo $?)" 'monitor status: ahead/behind = 1/1'
check "$([ "$(jget "$SYNC_JSON" preserved_ref)" = "$EXPECTED_REF" ]; echo $?)" 'monitor status carries the recovery ref'
check "$([ "$(jget "$SYNC_JSON" result)" = attention ]; echo $?)" 'monitor status: result = attention'
check "$([ "$(jget "$SYNC_JSON" updated)" != '' ]; echo $?)" 'monitor status: updated stamp present'
check "$([ "$(jget "$SYNC_JSON" branch)" = master ]; echo $?)" 'monitor status: branch present'
check "$([ "$(jget "$SB_STATE/status.json" result)" = attention ]; echo $?)" 'per-host record still says attention (unchanged shape)'
check "$([ "$(git -C "$SB_CLONE" rev-parse HEAD)" = "$LOCAL_SHA" ]; echo $?)" 'clone HEAD still holds the local commit'
check "$([ "$(git -C "$SB_REMOTE" rev-parse master)" = "$REMOTE_MASTER_BEFORE" ]; echo $?)" 'origin/master was NOT rewritten on the remote (no force, no reset)'

# ════════════════════════════════════════════════════════════════════════════════════════════════════
head_ 'TEST 2a — NEW script, AHEAD but fast-forwardable: plain push, no side ref invented'
sandbox t2a-new-ahead-only
git -C "$SB_CLONE" -c user.name=verify -c user.email=verify@localhost commit -q --allow-empty -m 'local only, upstream has nothing new'
run_autosync "$NEW"
echo "   exit code: $RUN_CODE"
show_status
REFS_2A="$(git -C "$SB_REMOTE" for-each-ref --format='%(refname)' | tr '\n' ' ')"
note "remote refs: $REFS_2A"
check "$([ "$RUN_CODE" -eq 0 ]; echo $?)" 'ahead-but-ff is not treated as divergence (exit 0)'
case "$REFS_2A" in *diverged*) check 1 'no diverged- ref created when the branch push succeeded';; *) check 0 'no diverged- ref created when the branch push succeeded';; esac
check "$([ "$(git -C "$SB_REMOTE" rev-parse master)" = "$(git -C "$SB_CLONE" rev-parse HEAD)" ]; echo $?)" 'the commit landed on origin/master'

# ════════════════════════════════════════════════════════════════════════════════════════════════════
head_ 'TEST 3 — NEW script, clean clone behind origin: normal path unchanged'
sandbox t3-new-ff
printf '# upstream change that must arrive\nagent-default-model:\n  provider: deepseek-official\n  model: deepseek-v4-pro\n' > "$SB_ROOT/seed/settings/base.yaml"
git -C "$SB_ROOT/seed" add -A
git -C "$SB_ROOT/seed" -c user.name=verify -c user.email=verify@localhost commit -q -m 'upstream: model flip'
git -C "$SB_ROOT/seed" push -q origin master
BEFORE="$(git -C "$SB_CLONE" rev-parse HEAD)"
run_autosync "$NEW"
echo "   exit code: $RUN_CODE"
show_status
AFTER="$(git -C "$SB_CLONE" rev-parse HEAD)"
check "$([ "$RUN_CODE" -eq 0 ]; echo $?)" 'clean behind clone still exits 0'
check "$([ "$BEFORE" != "$AFTER" ]; echo $?)" 'HEAD fast-forwarded to origin/master'
check "$([ "$(git -C "$SB_CLONE" rev-parse origin/master)" = "$AFTER" ]; echo $?)" 'HEAD is exactly origin/master'
check "$([ "$(jget "$SB_HOME/.dsh-sync-status/status.json" result)" = clean ]; echo $?)" 'monitor status: clean'
check "$([ -f "$SB_HOME/.dsh/settings.yaml" ]; echo $?)" 'sync.py applied into the sandboxed DSH_HOME'
[ -f "$SB_HOME/.dsh/settings.yaml" ] && { note 'applied settings.yaml:'; sed 's/^/   /' "$SB_HOME/.dsh/settings.yaml"; }

head_ 'RESULT'
if [ "$FAIL" -eq 0 ]; then echo 'ALL CHECKS PASSED'; exit 0; else echo "$FAIL CHECK(S) FAILED"; exit 1; fi
