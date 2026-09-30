Decided 2026-09-30 by the dev seat on the owner's instruction: he was asked whether the machine may merge
its own finished work to main, and he answered that this is a dev question and the seat in charge decides
it. So it is decided here, and the reasoning is recorded rather than assumed.

## The decision

An **integrator shift may merge reviewed work to main by itself.** Scope, and each clause exists because
of something already measured:

- **Reviewed only.** The item must carry a review that passed: the branch's own test command green and a
  clean merge tree. Item 82 is the model case — 264/264 tests, tsc clean, merge-tree exits 0.
- **Merges to main, and nothing else.** No force-push, no history rewrite, no branch deletion, no rebase of
  published history. This system has never had a rewrite and does not start now.
- **Every merge is logged** with the item id, the branch, the base, the test command and its result line,
  into the ledger attempt — the same standard as every other closed item.
- **Revertible by default.** The merge is a `--no-ff` merge commit, so a revert is one command; the
  previous head is recorded on the item before the merge runs.
- **Bounded.** Merging is what an integration *item* does. It is not a licence for any shift to touch main
  for any other reason; the prohibition stays in the shift contract for every other item type.

## What I verified before deciding

`/home/zabz/bin/work-integrator.py` (12,815 bytes) **never edits a repo, never merges and never pushes** —
its own header says so and the code agrees. It is a *source*: it scans for branches not contained in the
integration base and files integration items for a shift to pick up. So scheduling it is safe; the merge
happens later in a shift under the scope above.

## Why it is NOT scheduled yet — the measured blocker

`work-integrator.py --dry-run --days 3 --json`, run cold:

| project | recent unmerged | older unmerged |
|---|---|---|
| kosher-ai-filter | 12 | 0 |
| lpt-website | 9 | 12 |
| lpt-sync | 5 | 3 |

and the same shape for cfo, personality-system, chumash and prod-db-sync. It has `--days` and `--project`
but **no per-run limit**, so a single scheduled run would file every one of those at once — dozens of
items, many of them stale `origin/agent/*` and `origin/integrate/*` branches rather than work anyone
intends to merge. That is exactly the "27 work orders that will never run" failure the 2026-09-28 design
recorded, rebuilt by a different route.

**So the next concrete step is a `--limit N` argument and a default of a handful, verified by a dry run
that files nothing.** Then schedule it hourly. Deciding the authorization now and scheduling the source
carelessly would trade one stall for a flood.

## What this unblocks

Four ledger items are blocked on merges a shift was forbidden to do — 82 (chumash), 83 and 111
(rental-system), 124 (housekeeping). Their text currently routes the decision to a human: "a person with
main-branch access", "only a person may commit to main". After this decision they route to an integration
item instead.
