# 143 - INTEGRATOR FAST-FORWARD POLICY

A shift may land a tested integration branch on the repository's integration branch
(`master` in `personal-secretary-mvp`) by **fast-forward only**. It may never force,
never reset the base, and never land content it did not test.

This policy exists because the fleet kept producing branches that nothing merged, and
because the first attempts to fix that produced the opposite failure: shifts pushing
untested work straight at the base. Owner-queue row 868 asked the owner directly
(2026-10-20). He answered on 2026-10-21 that this is a developer decision, not an owner
question, and the resolution authorised shifts to fast-forward after a clean tested
integration. The rule was cited as written at this path before the document existed;
this file is that policy.

## The three conditions

A branch may be fast-forwarded onto the base only when **all three** hold:

1. **It contains the current base.** `git merge-base --is-ancestor origin/<base> <tip>`
   exits 0. If it does not, merge the current base into the integration branch first,
   resolve conflicts on the branch, and re-test. The base is never the place a conflict
   is resolved.
2. **It deletes nothing unintentional.**
   `git diff --diff-filter=D --name-only origin/<base> <tip>` is empty, except for the
   intentional credential-removal paths (`*_token.json`, `*tokens*.env`, `.env.vogel`,
   `*tunnel-token*.md`; master-33, commit 012f8a35, ledger item 287). A deletion that
   is not on that list is a stop, not a review note.
3. **It adds no test failure.** Run the project's own suite on the merged tree and quote
   its result lines. If the base is already red, record the base's failure count and the
   branch's, and prove every branch failure also fails on the base. A branch that fixes
   tests is welcome; a branch that adds one is not landable.

A merge that leaves the base's tree byte-identical is a legitimate no-op landing: it
records the branch as integrated without changing content. Compute it first
(`git merge-tree --write-tree origin/<base> <tip>`) and confirm the result tree equals
`origin/<base>^{tree}` before treating it as a no-op.

## The commands

```sh
cd <clean worktree of the integration branch>
git fetch origin
git merge-base --is-ancestor origin/integrate/<branch> origin/master; echo IN_MASTER_RC=$?
git diff --diff-filter=D --name-only origin/master HEAD | wc -l
# run the project's suite on this tree and keep the log
git push origin HEAD:refs/heads/integrate/<branch>   # fast-forward the branch
git push origin HEAD:refs/heads/master               # fast-forward the base
```

`git push` without `--force` is the gate: if the base has moved, the push is rejected
and the shift re-fetches and re-tests. Never `--force`, never `git reset --hard`, never
`git push --mirror`. Work in a dedicated worktree so a dirty live checkout is not
disturbed.

## What the record must contain

The ledger close (or attempt) must quote, not summarise:

- the tip SHA before and after, and the push range (e.g. `ce176de19..c09b2f46c`);
- `IN_MASTER_RC=0` from the ancestor test;
- the deletion-path count (0, or the named credential paths);
- the suite's own result lines (`tests N`, `pass N`, `fail N`) and the runtime version;
- the owner/development decision that authorises the landing (row 868).

A close without those lines is not evidence that the landing happened.

## Never

- Never land an integration branch that does not contain the current base.
- Never resolve a conflict on the base; resolve it on the branch and re-run the suite.
- Never force-push, reset, or rewrite the base to make a push fit.
- Never commit ordinary content directly to the base; the base moves only by
  fast-forward to a tested integration branch.
- Never land a red branch, and never report a test count that was not read from a log.

## Measured history

- 2026-10-22, ledger item 1109: `origin/master` fast-forwarded `111cc67a7..d6129c2aa`
  to a branch that contained master, deleted no paths, and passed 14/14 under Node
  24.22.0.
- 2026-10-22, ledger item 1126: `origin/integrate/rentals-93-94-20261022` merged into
  master as a content-neutral landing (`git diff ce176de19 c09b2f46c` empty, 0 deletion
  paths, 14/14 pass), fast-forwarding `ce176de19..c09b2f46c`.
- Before the policy, branches sat unmerged until a later shift redid the same work
  (measured on lpt-website: three shifts on one unmerged fix; `agent/windows-broker-channel`
  unmerged 2026-09-28).
