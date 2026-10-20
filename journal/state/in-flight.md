Updated: 2026-10-20

# In flight

## kosher-filter-ai - roadmap programme (ledger 861, last fanned-out thread)

Everything the objective named is merged on `main` (26 PRs, #64-#89). Verified on `075913b`:
`docs_check.py` 18 of 18, `check_roadmap.py` 56 items / 22 blocked / 34 done, citations 0 dead of 3235.

**The exact next action**, so it does not need rediscovering:

1. `roadmap-supply.py` (authority, /root/bin/sources) should report **ledger rows with no register item** - the
   direction nothing checks. Target: `unmapped=0`. It must treat ledger 204 as covered because
   `docs/roadmap/items/W-P3-01.md` records that it supersedes it; today that relation lives in prose, so the checker
   needs a machine-readable form of it (a small TSV beside the items, e.g. `superseded-ledger.tsv` with
   `<ledger id>\t<item id>\t<reason>`).
2. After that, `check_roadmap.py` should read the same TSV so the repo and the supply agree on what "covered" means -
   otherwise the two will drift the way the state file did.
3. Then ledger 861 closes and the "0 unmapped" line joins the supply's dry-run output beside `uncovered=0`.

## Blocked on the owner, not on work
- `ignore_blocked_ledger` for kosher-ai-filter (ledger 820): the mechanism half.
- The modesty model and WHQL signing (money).
- PR #40 merge (ledger 620).
- A sacrificial handset for the five anti-reset tests (ledger 662).
- A console run for the duplication capture - no code, just a session with a real display.
