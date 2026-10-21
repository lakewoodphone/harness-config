# 143 — Integrator fast-forward policy (a development decision, made 2026-10-21)

**Who decided:** Zabz, not the owner. He was asked on 2026-10-21 and answered, correctly, *"This
sounds 100 percent, like a developer question, and not a question you are supposed to be posing to
me"*. Queue rows 868, 810 and 865 were filed as owner decisions; they never were. This document is
the decision, so the question is not asked again.

## The rule

An integrator shift **may** fast-forward `origin/master` to a tested integration branch, without
asking, when **all three** of these hold:

1. **It contains current master.** The branch is master plus work — never a lineage that would drop
   anything master has.
2. **It deletes nothing.** No paths removed, no files dropped.
3. **It adds no test failure.** Where the full suite fails on the branch, every one of those failures
   also fails on current master. The count of failures must not rise, and the branch should reduce it.

And it is **fast-forward only**:

* `git push origin <sha>:master` where `<sha>` is a descendant of master. **Never `--force`, never a
  rewrite, never a reset.** A rejected push means the branch is not a descendant — stop and redo the
  merge, do not force it.
* The evidence for the three conditions is written on the ledger item, with the numbers: tests passed
  on the branch, tests passed on master, and the list of failures that are common to both. A claim
  without the numbers is not a check.

## What still comes back to the owner

Nothing about merging. Everything about the **content** that reaches production: what the site says to
a customer, what a message says, a price, a promise, a legal posture. Those are his, per the standing
rule, and they are decided before the branch is written, not at merge time.

## Why the three conditions, and not a lighter rule

The estate has already paid twice for a merge nobody checked — the Weinberg arrears banner and the
`origin` two-URL remote (AGENTS.md §6.1). The conditions above are the part of a review that a machine
can actually perform, so they are the part that is delegated; everything a machine cannot judge stays
with a human.

## The rows this settles

* **#868** — `integrate/pt708-stale-sms-trim-tests-20261020` at `6c6693eb8`: contains master, deletes
  nothing, full suite 17 failed / 3,761 passed against master's 40 failed / 3,723 passed with every
  one of the 17 also failing on master. **Meets all three. Land it.**
* **#810** — seven `integrate/*` branches for kosher-filter-ai, green PRs. Same rule applies; a shift
  lands each one that meets the three conditions and reports the numbers.
* **#865** — the lpt-sync 659 reconciliation fix, 3 files, 12 tests. Same rule.
