# 117 — The journal divergence on ZABZ-TECH: what is actually true, and the reap plan

Diagnosed 2026-09-18 by workstream J, read-only, on `ZABZ-TECH`. **Nothing was merged, no id was repaired,
nothing was tidied.** The one mutation performed was a preservation push, which was a no-op.

This document exists because three separate claims about this clone were circulating, **two of them were
wrong**, and a reaping session that trusted any of them would damage the shared record.

## 1. The three claims, and which survive

| claim | verdict |
|---|---|
| "**nine** ids mean two different entries — `L1920`–`L1928`" | **WRONG.** It is **ten**: `L1920`–`L1929`. Re-checked against both the pre-fetch and post-fetch `origin/master`; the answer is ten in both states, so fetch staleness does not explain the difference. |
| "`id_collisions: 39`" | **NOT REPRODUCED.** A `git ls-tree` join over `journal/entries` present in both trees with different blobs yields **10**. The 39 came from a status file, its definition was never read, and it is now an unsupported number. |
| "the id ceiling cannot see unfetched refs, so the allocator reuses numbers" | **TRUE OF THE CAUSE, FALSE OF TODAY.** The mechanism is real and is documented in the source as the 2026-09-15 fault; **it has since been fixed** (§4), and the live allocator would not reuse these ids. The collisions are **pre-fix residue**, all dated 2026-09-17. |

## 2. The collision table — ten ids, ten pairs, all `zabz-tech` against `ZABZ-YOGA`

Every one is HEAD = this machine against origin = `ZABZ-YOGA`, and every pair is two *substantively
different* lessons, not an edit of one:

| id | this machine (HEAD) | origin (`ZABZ-YOGA`) |
|---|---|---|
| `L1920` | *The dangerous writer was the third one…* | *A node capability must live in ONE module…* |
| `L1921` | *The local lpt-hub checkout is the owner's live work surface…* | *Junction-mounted packages resolve relative imports…* |
| `L1922` | *The bench's /usr/local/bin engine can silently lag the repo…* | *A child's MESH-HOST line is a claim, not a measurement…* |
| `L1923` | *Never run a markdown-emphasis stripper over a machine-readable field…* | *Correction to L1896: the … non-refundable down payment…* |
| `L1924` | *Unihertz Jelly Max screen jobs: the power and volume flexes…* | *Windows: copying a profile node_modules duplicates junctions…* |
| `L1925` | *I overwrote the live production sync tool with a 33KB stale copy…* | *The untrusted-mount-point discriminator is the reparse point's ACL OWNER…* |
| `L1926` | *A card reporting a tiny capacity is a controller FIRMWARE FALLBACK…* | *A profile check is evidence only for the logon class that ran it…* |
| `L1927` | *The schema was 82 percent wrong and nothing said so…* | *The journal id allocator now requires a reserved window…* |
| `L1928` | *Dead-card vs formatted-card: five cheap checks…* | *Never build a commit on a ref you have not just read…* |
| `L1929` | *CORRECTION to L1926/L1928: a USB power-cycle does NOT isolate…* | *A generated file that conflicts in a cherry-pick is the collision reappearing…* |

**Resolving any of these is a semantic, citation-dependent decision** — which side's *meaning* keeps the
number — and no command on either machine can see who cites which. That is why this is not a mechanical
repair, and why the design's rule ("a machine that cannot see both sides must not repair the record") is
doing real work here rather than being ceremony.

## 3. Two tools that answer "fine" and mean "I cannot see it"

**`repair-ids` is structurally incapable of this repair.** Verified in the source, not inferred:
`cmd_repair_ids` calls `load_entries()` — **one working tree** — then groups by `(kind, id_full)` and
reports only groups with more than one distinct hash. One tree cannot produce a group of two, so it prints
**`no id collides with different content — nothing to do`** and **exits 0**. The prior session's report of
that behaviour is confirmed on this machine.

**`journal.py check` also exits 0 with the collision live.** It prints `0 error(s), 99 warning(s)` while ten
ids mean two different entries, because it scans one tree and has no concept of a second. **Its exit code is
not evidence about cross-branch health**, and a reaping session that trusts it will conclude the record is
clean. Only a merge attempt, or the `git ls-tree` join, detects this class.

Neither tool is broken. Both are answering a question about one tree. **The mistake would be to read their
answers as being about two.**

## 4. The cause is real, historical, and fixed — with two live weaknesses left

The id ceiling lives in `git_max` (`journal.py:2810-2873`), and its own comment records the 2026-09-15
fault: `git grep` with no ref greps the *working tree*, the second call greps `HEAD`, and neither can see a
number that exists only on `origin` — so `append` fetched and then ignored what it fetched. **Lines
2861-2872 are the fix**: it now loops `for-each-ref refs/remotes/origin` and greps each ref.

Empirically today, on this machine: `journal.py next-id lessons` → **`L2064`**, with `highest seen: L2063`.
`L2063 ≫ L1929`. **The live allocator would not reuse the colliding ids**, so nothing here is actively
corrupting the record while the repair waits.

**Two weaknesses that are live, and both are worth fixing before a reap:**
1. **`allocation_ceiling()` takes its `remote` component from the stamp, and in this clone
   `journal/index/stamp.json` has `"git_ceiling": {}` — empty.** Only the live ref-grep inside `git_max`
   stands between the allocator and blindness. **Any path that uses `allocation_ceiling` without `git_max`
   is unprotected**, and that is one refactor away from a repeat.
2. **`git_max` caps remote refs at `[:25]`, and there are 22 under `refs/remotes/origin`.** Three more
   branches and refs start being **silently dropped** from the ceiling — a silent, proportional-to-growth
   failure. The number should be raised, or the truncation should announce itself.

## 5. The exposure that mattered most, and it is now closed

That clone's working tree had **139 dirty lines, of which 113 files under `journal/entries` were
UNTRACKED** — **in no commit and in no ref**. A preservation push cannot protect them: the push performed
today reported **`Everything up-to-date`** because `HEAD` was already on a `diverged-*` ref, and untracked
files are in no ref by definition. **Any `git clean`, `reset --hard` or rebase on that machine destroys 113
journal entries irrecoverably.**

They have been archived off that machine and committed to this repo as
**`docs/mesh/preserve/untracked-journal-ZABZ-TECH-20260918.tgz`** — 113 members, 175,175 bytes, verified
with `tar -tzf`. It is a **preservation artefact, not a resolution**: it claims nothing about which
colliding id is canonical and resolves nothing.

## 6. The reap plan

For a future session, **with a human authority on both machines**. Every step has a precondition and an
abort; the ordering is not optional.

0. **Freeze.** Precondition: both machines' owners agree a write window and `ZABZ-YOGA` confirms no writer
   is active. Run `journal.py doctor` and `git fetch --all`. **Abort** if any lock names a **live** PID on
   either host, or if the fetch does not advance `origin/master`.
1. **Secure the untracked entries first.** Precondition: the untracked count under `journal/entries` equals
   the recorded **113**. **Abort** on any other number — a different count means the size of the exposure
   is unknown. **Refuse** to assume a ref push covers them; it does not. (The archive in §5 is a copy, not
   a substitute for committing them on that machine.)
2. **Preserve both sides, non-destructively.** Push `HEAD` and `origin/master` to *new* `diverged-*` /
   `preserve/*` refs. **Abort** on any non-fast-forward — **use a new ref name, never `--force`.** Expect
   `Everything up-to-date`, as today.
3. **Compare in a scratch clone, never in the live one.** Clone to a temp dir, fetch all refs, materialize
   both versions of each of the ten ids side by side. **Abort** if any ref is unreachable — a partial view
   is exactly the state that must not repair the record.
4. **A human decides, per id, which side is canonical.** Record the decision as a **new** journal entry.
   **Refuse** to encode it by editing `journal/entries/**`.
5. **Renumber only through the tool, and only once it can see the collision.** Stage the losing side into
   the working tree so two entries share an id, then run `repair-ids` **dry**. Precondition: it prints a
   renumbering list. **Abort if it prints `nothing to do`** — that is proof the two-sided materialization
   failed and the tool is still blind. Then `--apply`. **Abort** if `check`'s error count rises above 0, and
   restore from the Step-2 refs.
6. **Verify.** `check` exit 0 with 0 errors; `doctor`; and re-run the `git ls-tree` join expecting **0**
   colliding paths.
7. **Publish to a new ref for humans to decide. Refuse to merge or rebase.**

**Unconditionally refused, in every step:** `git reset --hard`; `git checkout .`; `git clean`; `git stash
drop`; deleting anything under `journal/`; `git push --force` (or `--force-with-lease`) to any shared ref;
hand-editing or hand-renumbering an entry; `git merge`; `git rebase`; deleting an entry to resolve a
collision; and any repair while a live lock is held or before the 113 untracked entries are secured.

## 7. Two incidental findings worth keeping

- **A dry run of `repair-ids` takes `journal/.lock` and leaves it naming a dead PID.** Before: held by
  `append 56904` (PID dead, ~5.3 h old). After the dry run: held by `repair-ids 46120` (also dead).
  `journal/.lock` is untracked, so the repo record is not dirtied — but `check` still exits 0 with a lock
  held by a dead process. A writer is expected to self-heal via `_lock_holder_is_dead`; that reclaim was
  **not tested**, and the orphan is pre-existing rather than caused here.
- **`check` reports 99 warnings on this clone against 0 errors**, most of them dangling `refs=` — citations
  to entries that do not exist. Not part of this repair, but it is a measure of how much the record's
  cross-references have rotted.

## 8. Not verified

The `id_collisions: 39` metric's definition; whether autosync truly refuses to fast-forward a diverged
history (consistent with the observation, but no autosync code was read — that half is inference); whether
`repair-ids` leaving an orphan lock is by design; which of each pair `ZABZ-YOGA` considers canonical; and
whether the 113 untracked entries are backed up anywhere else. They are now backed up **here**.
