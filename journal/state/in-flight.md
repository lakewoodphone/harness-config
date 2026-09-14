# IN FLIGHT — work that is open right now

Updated: 2026-09-14 (evening session, ZABZ-YOGA)

Rewritten, not appended. An item leaves this file by being finished (a `log/handoff/` entry) or by
becoming a `state/open-pain.md` row. Full handoff: **H93**. Fixes this session: **W53–W61**, **L229–L232**.

## The one thing to measure first

| Item | Where | The measurement |
|---|---|---|
| **Whether the STOP SEARCHING correction works** | `app/autopilot.py` (`_actions_are_read_only`, `_build_work_prompt`) | Read `[ACTIONS:]` in the next sessions. A **mutating** name (`update_task`, `code_edit`, `create_task`, `close_task`, `save_memory`) after a `STOP SEARCHING` correction means it worked; another read-only step means it did not. Deployed 17:09:44Z; session 75343 was still at step 1 when this file was written. |

## Mine, measured and waiting on a trigger

| Item | What would show it |
|---|---|
| **The evolution-health fix** (`_evolution_health_from_result`) | `autopilot_state.json` → `subsystem_health.evolution.last_detail`. Still **empty** with `last_ran_at` 14:03, so the fix has **not been observed**; it corrects itself at the next evolution cycle. |
| **The evolution dedup + vendor exclusion** (W57) | Kernel `evolution` check: duplicates are bounded to 7 days, so the alarm should **clear on its own after 7 clean days** and return if they come back. Reads 22 recent duplicates (was 38 all-time). |
| **The kernel's false alarm** (W59) | `check_evolution` no longer counts unapplied proposals as a fault while `CODE_EDIT_AUTO_APPLY=false`. Verified in the live payload. |
| **The sync-login notification** (W55) | `owner_message_queue` holds `sync_needs_login:amazon_sync` and `:ebay_sync`, **held, urgent, repeat_count 1**. At 04:00/04:15 the syncs run again and should bump `repeat_count`, not add rows. |

## Broken, as last measured

- **The authority's checkout is 87 commits behind and 16 ahead**; `deploy.sh` cannot run. Hand-porting is
  proven but the reconcile is undone (**P49**).
- **`~/bin/owner-queue.py` is tracked in no repository** (**P47**). Left in place deliberately — a copy in
  `harness-config` would drift from the live one.
- **The journal still has two writers**: all five flat files carry an mtime of 2026-09-14 16:00 (**P57**).
  `import-flat` keeps the sharded log complete.
- **The work loop still failed at 5/5** at the last measurement, for the reconnaissance reason above.

## His, waiting

- **Amazon and eBay logins.** Both need an interactive browser session;
  `cd /home/zabz/repos/quickbooks-agent && npm run amazon:download` — and it needs a visible browser, which
  the headless authority cannot provide. Surfaced on his badge as two urgent held rows.
- **The BoA password rotation** — the credential leaked into the 2026-09-14 transcript by a diagnostic of
  mine (new instance of **P13b**).
- **Owner question #19 answered**: pass on lot 67654. Recorded as **D85** with the standing device-sourcing
  policy. Nothing was bought and no account exists.

## Deliberately not done

- **`code_edit_auto_apply` is still off.** Enabling it means letting the company edit its own code
  unattended — a governance decision, not an engineering one, and off is the safe configured state. The 72
  unapplied proposals are now recorded as *queued for review* rather than as a fault.
- **The 37 numeric values in `work_sessions.status` were not deleted.** They are test pollution and the only
  evidence of the class; the missing guard is the real residual (**P50**).
