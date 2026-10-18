# `live/` — the copies that are actually running, captured because they existed only on one server

These are not the repo's own forks of these scripts. They are **snapshots of the files running on
`secratary-cloud` at 2026-10-18 ~16:30 EDT**, taken with `scp`, because the running copies had no
version in any git repo — a rebuilt authority would have lost them, including the two repairs made that
day.

| file | live bytes | repo fork at `scripts/wake/…` | note |
|---|---|---|---|
| `work-integrator.py` | 32 126 | 13 411 | completely different lineage; the repo fork is months behind and would re-introduce the bug fixed on 2026-10-18 |
| `run-wake-sources.sh` | 21 692 | 2 979 | same — the repo copy is a stub by comparison |
| `sources/wake-progress.py` | 9 035 | — | new on 2026-10-18, no repo copy existed |

This is the drift `scripts/wake/deploy.sh` already documents in its own header ("wake-dispatch.sh 579
lines vs 1351 live"). It is recorded here rather than silently resolved, because overwriting the repo
forks with a 2.4× larger file is a change nobody has reviewed, and because the opposite mistake —
assuming the repo copy is live and editing it — is how a fix gets reverted.

## What was changed on 2026-10-18, and why (read before touching either copy)

1. **`work-integrator.py`**
   - `DEFAULT_INCLUDE` widened from `(agent|kf[0-9]*|integrate|rescue)/` to also match `item-`, `fix`,
     `guard`. Measured: 18 of 72 unmerged refs in `kosher-filter-ai` were `item-<n>-<slug>`, 3 more were
     `fix/`/`guard/` — 21 branches of finished work invisible to the tool.
   - An absent or non-git registry `repo` now appends a `skipped: "no-repo"` report row and prints
     `SKIPPED (no-repo): …` to stderr, instead of a bare `continue`. Measured: the kosher registry pointed
     at `/home/zabz/repos/kosher-filter-ai`, which did not exist on the authority, so the project was
     dropped from every report and the tool printed `0 integration item(s) filed` for 27 consecutive runs.
   - The checkout now exists there (cloned 2026-10-18, not shallow), so the project is measured locally.
2. **`run-wake-sources.sh`** — one new block, after the integrator's, running
   `sources/wake-progress.py` with `timeout 120` and logging `FAILED rc=` or its one-line verdict.
3. **`sources/wake-progress.py`** — the progress deadman. Files one ledger item when no wake release has
   succeeded for 6 h (or every release in the window failed), and exits 4 with a `REFUSED` line when the
   dispatch log is missing or unparsable. It never restarts, retries or re-dispatches anything.

## The reconciliation this snapshot does not perform

The repo forks and the live files must be brought back to one lineage. Until that happens, the rule for
the next session is: **hash the file you are about to edit against the host that runs it** (`md5sum`), and
edit the live copy through an atomic `mv` (new inode) as `AGENTS.md` §8 requires. Filed as housekeeping
work rather than done here, because the right direction of the merge is a decision — and because
`work-integrator.py`'s live version is the one with the 2026-10-18 repairs in it.
