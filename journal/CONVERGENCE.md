# How the record converges — for any session on any machine

**A machine's `journal/` is a contributor, not the record.** The record is the canonical tree on
`secratary-cloud`:

```
/root/code/harness-config/journal          <- THE RECORD. 5,143 entries, check 0 errors (2026-10-16)
~/code/harness-config/journal              <- what your sessions write to, on whichever machine you are
```

Read this before trusting your own tree for anything older than today, and before repairing anything.

## Reading the canonical record from another machine

```
ssh secratary-cloud "python3 /root/code/harness-config/journal/tools/journal.py \
    --root /root/code/harness-config/journal --no-color search '<what you want>'"
```

Everything `journal.py` does works over that path — `show`, `list`, `newest handoff`, `search`. It needs
the authority reachable; when it is not, read your own tree and say so, rather than implying you read the
record. **Your own tree is missing whatever this machine has not written and the pull has not carried in
yet** — measured 2026-10-16: 5–6 entries of drift per 35 minutes of machine writing.

## How an entry gets from a machine into the record

```
python3 /root/code/harness-config/scripts/evolution/journal-union/converge-pull.py \
    --canonical /root/code/harness-config/journal --trees <dir of collected trees>     # measure
    ... --apply                                                                        # write
```

**It is additive.** It never edits, renumbers, moves or removes an entry already in the canonical tree.
For each source entry whose BODY is not present, it copies it in under its own id — and if that id is
taken by a different entry, it gives the INCOMING one a fresh id. Only the arrival can change, so no
existing citation can break.

The whole loop is `scripts/journal-converge.sh`: single-flight, refuses below 2 GB free, runs `check`
afterwards and exits non-zero on any error, writes `/root/.journal-converge/status.json`, cleans its
staging in a trap.

**IT IS NOT ON A CLOCK.** It has been verified end to end (7 trees, +5 entries, check 0 errors, exit 0)
and the cron line is written in its own header, commented out. Until it is scheduled, run it by hand.

`journal-commit.sh` IS on a clock — every 15 minutes it commits `journal/` and publishes it to the vault
as `refs/heads/journal`, verified by reading the remote ref back.

## The instruments, and what each one actually answers

| question | instrument |
|---|---|
| is THIS tree internally sound? | `journal.py check` — one tree, so it cannot see a fork |
| does another tree disagree with this one? | `journal.py check --cross-tree <dir>` — DIR holds one subdir per tree |
| how many ids carry two bodies across the trees? | `fork-size.py --trees <dir> [--skip <names>]` |
| did anything get LOST? | `r7-verify-body-loss.py --trees <dir> --merged <root>` — decides on the journal's own identity |

**A reading is only a reading against a stated baseline.** `check --cross-tree` on a tree that has just
been REPAIRED counts the repair's own renumbering (measured: 587 on the canonical tree against its
pre-landing snapshots). The fork between the eight machine trees was **336 and frozen** over 35 minutes;
the divergence from the canonical tree grows with every write. Those are different numbers.

## Traps this work has already paid for — do not re-learn them

* **`dedupe` MOVES what it collapses**, into `archive/`. It is not the inverse of the no-loss gate, and
  it should not be the last step run over a union. Re-run the identity gate after it.
* **A file's mtime is not evidence of change.** `check --fix` re-emits entries byte-identically; `find
  -newermt` showed ~150 touched files where `git status` showed none. Use git for "did this change".
* **`rc=0` does not mean a push succeeded.** `journal-commit.sh` prints `[failed]` and can still exit 0
  when there is nothing staged. Verify a push by reading the remote ref back.
* **A directory of five machine checkouts is not the source set.** The authority alone carries 21
  directories with a `journal/entries`, and one worktree held 234 ids the canonical checkout lacked.
  Widening the source set moved a gate from `BODIES MISSING 0` to `62`. Run the source census first.
* **`ssh` without `-n` eats the rest of a script fed on stdin**, silently.
* **`comm` needs `LC_ALL=C` on both inputs**; a locale-collated `sort` invented eleven phantom forks.
* **A "negative control" that was not a control is how a test gets credited for proving nothing** —
  check that the number you got is the number the design predicts.

## What is NOT done

1. **The convergence job is not scheduled.** One cron line, in the job's own header.
2. **`vault/main` is a divergent work lineage**, unreconciled (`P6475`). Publication uses
   `refs/heads/journal` instead, and `main` has been left alone rather than forced.
3. **The reservation ledger on the canonical `journal.py` reads a ref that stopped advancing on
   2026-10-11** (`origin` on the machines is the frozen office box). Until that is repointed, the pull
   renumbers an incoming id now and then instead of never.
