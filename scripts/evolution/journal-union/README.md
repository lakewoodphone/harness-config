# journal-union — the cross-tree journal union: how to run it, and what it has already cost

This directory holds the tooling that builds ONE journal tree out of the estate's many forked ones.
It is here because round 6 ran it from `/root/work/r7` — a scratch directory — and shipped only its
*result*. When round 7 tried to re-run it on the authority, the tools were not in the checkout
(`scripts/evolution/r7-restore-archived.py: No such file or directory`) and the union could not be
reproduced. **Ship the generator, not the artefact** (`D3723`).

## Why a union, and not a verdict

`journal.py` is one-tree by construction. `check` exits 0 on a forked store because it has no
cross-tree rule; `repair-ids` prints `no id collides with different content — nothing to do` because
one working tree cannot produce a group of two (`docs/mesh/117-journal-divergence.md` measured both).
So neither tool can see the defect, and neither can repair it.

When two trees hold **one id with two different bodies**, one of them must lose the id. The union
keeps **both bodies**: the loser is written as `<ID>b.md`, `<ID>c.md`, … and `journal.py repair-ids`
renumbers it to a fresh id. Nothing is adjudicated and nothing is deleted. The alternative —
deciding which body *deserves* the number — needs a human authority on every colliding id; doc 117
prices that at a human per collision.

## The pipeline, in order

| step | tool | what it does |
|---|---|---|
| 1 | `r8-pipeline.sh` | collects every source, merges, repairs, verifies — the whole run, end to end |
| 1a | `10-collect.sh` | reads each machine's `journal/` over ssh into `trees/<name>/`. **Read-only on every source.** |
| 1b | `r7-journal-source-census.py` | finds EVERY tree on a machine and reports which holds bodies no other tree has. Run this before choosing sources — see "the source set" below. |
| 2 | `20-manifest.py`, `r7-journal-collisions.py` | one `id<TAB>sha` manifest per tree; sizes the fork: collisions, coverage, the merge plan |
| 3 | `30-merge.py` | the union. Base = `yoga`; every other tree is overlaid; a colliding body takes `<ID>b.md`. Nothing overwritten, nothing deleted. |
| 4 | `50-preflight.py`, `40-clobber-proof.py`, `51-dedupe-sim.py` | prove the merge lost nothing and that the repairs will land as predicted, BEFORE anything writes |
| 5 | `60-run.sh` | `check` → `dedupe` (dry, then `--apply`) → `repair-ids` (dry, then `--apply`) → `check` → `verify` |
| 5a | `65-normalise-stems.py` | **NOT OPTIONAL.** `repair-ids` renumbers the surplus copy of an id but does not care what FILE NAME the survivor has, so when the earliest copy was a suffixed one, X's survivor is left in `<X>b.md` and `check` reports `id in the file name (<X>b) disagrees with the marker (X)`. Measured: **94** such files, `check` exiting 1 with 96 errors. This is a pure rename — 0 bytes changed — and it refuses if any id is still carried by two files. After it: 94 stem mismatches → 0, errors 96 → 2. |
| 6 | `70-acceptance.py`, `71-noloss.py`, `r7-verify-body-loss.py` | the acceptance gate. `verify` is per-tree and blind across trees; these are the cross-tree version |
| 7 | `r7-restore-archived.py` | **NOT OPTIONAL.** `dedupe`/`repair-ids` retire a colliding body to `archive/` instead of leaving it live under a renumbered id, so bodies that were LIVE in a source tree leave the live view. Round 6 hardcoded the seven it found. **Use `--from-sources <treesdir>`**: the general rule is "every archived body that is present in a source tree and is not live", by the same `body_sig` the gate uses. Measured 2026-10-16: with nine sources the hardcoded seven were NOT the whole set — seven more (`hcd` H369–H374, H3576) were sitting in `archive/duplicates/` and `archive/collided-ids-2026-10-16/`, and the gate reported exactly those seven as lost. **A list of ids cannot survive a change of source set; a criterion can.** |
| 7a | `journal.py check --fix` | **NOT OPTIONAL** for the same seven. Two of them carry their own id in their BODY, and the restore rewrote that body, so the `sha=` metadata went stale — `metadata sha=… does not match the body (…)`. `check --fix` re-emits through the writer a normal write uses, recomputing sha, meta line and line endings together. The tool's own comment explains why a bare text replace is wrong: *"fixed the CRLF and left the sha stale, which turned one ERROR into another."* Do not write a second tool for this. |

**Measured 2026-10-16** (`/root/work/r8/`, six sources: cloud, yoga, tech, mac, `wt-item221`, and
`linux-r6capture` because `zabz-tech-linux` was offline):

```
source files 21,322   distinct source bodies 5,037
merged files  5,037   distinct merged bodies 5,037
BODIES MISSING from merged : 0        BODIES INVENTED in merged : 0
journal.py check            : 0 error(s), exit 0
```

## The two things that make the acceptance test honest

**Compare BODIES, never file bytes.** An entry file's first line carries its own id, and several
kinds repeat the id in the body, so renumbering changes the bytes while the entry is unchanged. A
whole-file sha comparison reported 403 lost / 377 invented on a merge that lost nothing. `body_sig`
— header and `<!-- j2 -->` stripped, every id token normalised to `<ID>`, whitespace collapsed —
is the definition "a body" that every tool here shares, so a census finding and a merge verdict
cannot disagree.

**`verify.py`'s negative is a claim.** Round 6's first `brokerSsh` repair matched nothing and
printed "nothing to repair" while the defect was live (`L4577`). Every step here prints what it
read, not that it succeeded.

## The source set is the part that goes wrong

Five machine checkouts is not the set. Measured 2026-10-16: the authority alone holds **21**
directories containing a `journal/entries`, and one of them — `/root/work/wt-item221`, the worktree
of branch `hk/221-live-wake-reconcile` — holds **234 entry ids the canonical checkout does not
have**. A five-source union reported `BODIES MISSING 0` while blind to all 234. ZABZ-YOGA holds ~40
such directories. So: run `r7-journal-source-census.py` first, and add every tree it names as a
source. **A source you could not re-read must be labelled** (`r8-pipeline.sh` keeps an offline
machine's previous capture as `linux-r6capture`, so nobody mistakes it for a fresh read).

## Traps this pipeline has already paid for

* **`comm` needs `LC_ALL=C` on BOTH sides.** `sort` is locale-collated, `comm` is byte-ordered. A
  plain `sort` invented 42–130 "unique" ids for eleven trees; with `LC_ALL=C` ten had zero. `comm`
  prints `file 1 is not in sorted order` — its stderr is part of its output.
* **`ssh` without `-n` eats the rest of a script fed on stdin.** Inside a `ssh host 'bash -s'`
  heredoc, a bare inner `ssh otherhost` consumes the remaining lines. The run ends silently,
  mid-file, with no error.
* **`repair-ids` mints fresh ids without consulting the cross-host reservation ledger.** The
  renumbering is lossless but it is not coordinated with `refs/heads/alloc/<host>`.
* **Never `git add -A`** in this estate: other sessions commit to these repos concurrently. Stage
  explicit paths.
