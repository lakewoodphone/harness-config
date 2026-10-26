# 2026-10-26 — a policy refusal is no longer booked as a failure

Deployed to `/opt/company` on `secratary-cloud` at 02:49–03:0xZ on 2026-10-26 and verified live in the
running process. Journal: **H13362** (handoff) · **L13515** (lessons) · findings doc §10.

## What these files are

The four files here are the **exact bytes running on the authority** after the change, and
`policy-refusal-20261026.patch` is the unified diff from the pre-change files (the `.bak-refusal-*`
backups) to these. They exist because the authority's working tree is **329 files dirty** and on a
different lineage from any local checkout — so the change is recorded here, where it can be reviewed,
rather than inferred from a host.

| file | what changed |
|---|---|
| `chat_action_runtime.py` | refusal branch sets `data["policy_refused"]`, logs `POLICY_REFUSED`, dedupes the approval task on `policy-refusal:<kind>:<action>:<agent>:<resource>`; `_is_policy_refusal()` + `_policy_refusal_key()`; `execute_actions()` breaks instead of retrying a refusal; the circuit breaker skips one; every genuine failure now logs the reason it was recorded |
| `chat_action_notifications.py` | `_create_approval_task(..., dedupe_key=)`; `dedup_threshold=0` when a key is given (the fuzzy title match otherwise wins and the exact key is never written); a non-positive id from `create_task` (`-1` = task ceiling) returns `None` instead of `"approval task -1"` |
| `chat_action_policy.py` | deterministic policy denials carry the same `policy_refused` marker and their own per-resource key |
| `agent_worker.py` | `_execute_tool_dispatch` returns the refusal's approval task id as a third element; `_execute_tool_with_autonomy` does not count a refusal as a tool strike (`is not None`, because `""` means "refused, no task") and returns the id so the step suspends as `approval_pending` |

## To re-apply on a host that does not have them

```bash
cd /opt/company
cp -p app/chat_action_runtime.py app/chat_action_runtime.py.bak-manual
# then apply the patch against the matching lineage, or copy the four files in:
#   cp <this dir>/chat_action_runtime.py app/chat_action_runtime.py.new
#   .venv/bin/python -c "import sys;compile(open(sys.argv[1],'rb').read(),sys.argv[1],'exec')" app/chat_action_runtime.py.new
#   mv app/chat_action_runtime.py.new app/chat_action_runtime.py   # new inode, never rewrite in place
#   systemctl restart company-api
```

**Do not** apply these blindly to a checkout on a different branch: diff the target first
(`harness-config/AGENTS.md` §6.1). The patch was generated against the authority's files as they stood
at 02:49Z.

## Verification that was actually run

Three `POST /api/v1/actions/execute` of `repo_map` (L0_SHADOW) against the live server: one
`POLICY_REFUSED` per request, zero retry lines, zero real-failure recordings, zero deadlocks, zero
demotions; same resource → same task, different resource → a different key. Five consecutive worker
refusals → zero `_note_tool_failure` calls, zero strikes against a limit of 3. A genuine failure
(`repo_read_file` on a nonexistent path) still counts one strike. `system_health` still executes.
