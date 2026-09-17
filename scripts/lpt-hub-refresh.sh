#!/usr/bin/env bash
# Keep the local lpt-hub clone fresh, because app/services/lpt_hub_sync.py reads that
# working tree (docs/customer-operations/sync-records/*.json) as the customer-case corpus.
#
# WHY THIS EXISTS (2026-09-14): the service could see 0 records because its GitHub path was
# dead (PyGithub missing) and its only local candidate path did not exist; a stray directory
# was masking that as "1 record". The fix pointed the service at /home/zabz/repos/lpt-hub,
# which makes that clone the SINGLE source of the corpus. Nothing refreshed it, so it would
# stale silently -- exactly the class of failure the fix removed.
#
# ---------------------------------------------------------------------------
# 2026-09-17 REWRITE -- WHY THE FAST-FORWARD-ONLY VERSION WAS WRONG
# ---------------------------------------------------------------------------
# The previous version did `fetch --quiet origin` then `merge --ff-only origin/main`, and
# recorded `ff=refused` when the merge failed. Measured on the authority, that combination
# cannot keep this clone fresh, for two independent reasons:
#
#   1. THIS CLONE'S OWN WRITES GUARANTEE THE FF WILL FAIL. The secretary commits to this
#      working tree (`chore(secretary): link <case> to WO<n>`), so `main` is permanently
#      ahead of origin by one or more of its own commits. `merge --ff-only` refuses by
#      definition as soon as that is true. Over the 957-line log: ff=ok 146, ff=refused 74,
#      first refusal 2026-09-15T17:15Z, latest 2026-09-17T15:15Z -- wedged for 46 hours.
#      Refs: git 2.53.0 `fatal: Not possible to fast-forward, aborting`.
#
#   2. THE FETCH'S FAILURE WAS INVISIBLE. `fetch` was run without checking its exit status,
#      so when the remote-tracking ref is not updated the `merge --ff-only origin/main` that
#      follows happily fast-forwards to a LOCAL, STALE ref. That is what happened: the
#      authority's `origin/main` was frozen at 12368820e (ref mtime 15:15:02Z) while the
#      true remote head was 811eca39d. The clone was 53 commits and 8 sync records behind
#      origin/main while this script reported `ff=ok`.
#
# The fix, without becoming destructive:
#   * check the fetch result, and verify the ref actually moved;
#   * fast-forward when possible (the normal, safe case);
#   * when it is not possible, REBASE our own commits onto origin/main with --autostash and
#     KEEP the stash result -- our commits are replayed, never dropped (on 2026-09-17 the
#     authority's single local commit replayed as a no-op because its content was already in
#     origin, and git auto-skipped it: "skipped previously applied commit 19231f213");
#   * never force, never reset --hard, never discard a local commit;
#   * write a machine-readable `status` so a checker can fail on it, instead of leaving a
#     `refused` string that nothing reads.
#
# Exit codes: 0 refreshed/up-to-date · 1 fetch failed · 2 could not reach origin/main cleanly.
# ---------------------------------------------------------------------------
set -u

REPO=${LPT_HUB_REPO:-/home/zabz/repos/lpt-hub}
RECORDS_DIR="$REPO/docs/customer-operations/sync-records"
STATE_DIR="${LPT_HUB_REFRESH_STATE:-$HOME/.lpt-hub-refresh}"
STATUS="$STATE_DIR/status.json"
LOG="$STATE_DIR/refresh.log"
mkdir -p "$STATE_DIR"

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
result="ok"
rc=0

# --- what we expect, so a stale REF cannot masquerade as success -----------------
before_ref=$(git -C "$REPO" rev-parse origin/main 2>/dev/null || echo "")

if ! git -C "$REPO" fetch --prune origin 2>>"$LOG"; then
    result="fetch-failed"
    rc=1
fi

after_ref=$(git -C "$REPO" rev-parse origin/main 2>/dev/null || echo "")

# --- advance --------------------------------------------------------------------
if [ "$result" = "ok" ]; then
    if git -C "$REPO" merge --ff-only origin/main --quiet 2>>"$LOG"; then
        result="ok"
    else
        # Divergence: this clone holds its own commits. Replay them on top of origin/main.
        # --autostash returns the working tree to its prior state; a conflict leaves the
        # rebase in progress and is REPORTED rather than forced through.
        if GIT_EDITOR=true git -C "$REPO" -c core.autocrlf=false \
               rebase --autostash origin/main >>"$LOG" 2>&1; then
            result="rebased"
        elif [ -d "$REPO/.git/rebase-merge" ] || [ -d "$REPO/.git/rebase-apply" ]; then
            result="rebase-conflict"
            rc=2
        else
            result="refused"
            rc=2
        fi
    fi
fi

# A fetch that succeeded but did not move the ref, while the remote has commits we lack,
# is the silent-staleness bug this rewrite exists to stop. Compare with ls-remote.
if [ "$result" = "ok" ] || [ "$result" = "rebased" ]; then
    if [ "$before_ref" = "$after_ref" ]; then
        remote_head=$(git -C "$REPO" ls-remote origin refs/heads/main 2>/dev/null | cut -f1)
        if [ -n "$remote_head" ] && [ "$remote_head" != "$after_ref" ]; then
            result="ref-stale"
            rc=2
            echo "$now STALE-REF: origin/main=$after_ref but remote head=$remote_head" >>"$LOG"
        fi
    fi
fi

# --- report ---------------------------------------------------------------------
counts=$(git -C "$REPO" rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo "?	?")
behind=$(printf '%s' "$counts" | cut -f1)
ahead=$(printf '%s' "$counts" | cut -f2)
branch=$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
head=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo "?")

records=$(find "$RECORDS_DIR" -name '*.json' 2>/dev/null | wc -l)
newest=$(ls -t "$RECORDS_DIR"/*.json 2>/dev/null | head -1 | xargs -r basename)

esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

printf '{"updated":"%s","status":"%s","rc":%s,"records":%s,"branch":"%s","head":"%s","behind":%s,"ahead":%s,"origin_main":"%s","newest_record":"%s"}\n' \
    "$now" "$result" "$rc" "$records" "$(esc "$branch")" "$head" "${behind:-0}" "${ahead:-0}" \
    "${after_ref:-}" "$(esc "$newest")" > "$STATUS"

echo "$now records=$records status=$result rc=$rc behind=${behind:-?} ahead=${ahead:-?} head=$head" >> "$LOG"
exit $rc
