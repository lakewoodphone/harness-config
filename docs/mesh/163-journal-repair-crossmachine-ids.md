# 163 — cross-machine duplicate-id collision repaired on ZABZ-TECH, then the checkout brought into sync

**Machine:** ZABZ-TECH (Windows). **Repo:** `C:\Users\ezabz\code\harness-config`.
**Written as the work happened** — this file is the durable record; the mesh outbox on a child agent
is a second copy. Started 2026-10-11T22:40Z.

---

## 1. Pre-state (captured 2026-10-11T22:40:46Z, before anything was touched)

| fact | value |
|---|---|
| HEAD | `7c82d2d4588a705469dbea17a67bde011c5e353b` — *AGENTS.md §5 + a service-state guard…* |
| divergence | `main...origin/main [ahead 5, behind 48]` |
| origin/main | `313c8b0560a93ff768552f894c97c2b3f72a0a65` (fetched; was `ahead 5, behind 47` before the fetch added one commit) |
| tracked-modified | 7 files: `journal/alloc/bands.tsv`, `journal/index/{entries.tsv,journal.db,stamp.json}`, `journal/state/{absorb-stamp.json,owner-questions.md,status.tsv}` |
| entry files in `journal/entries/` | **3450** |
| untracked entry files | **239** |
| stashes (pre-existing, not mine) | `stash@{0}` `presync-zabz-tech-20261011-222023`, `stash@{1}` `autostash`, `stash@{2}` `owner-attention-digest.sh WIP held across the 2026-09-20 reconcile fast-forward` |
| outside-repo backup | `C:\Users\ezabz\harness-config-presync-backup-zabz-tech-20261011\` — PRESENT (`entries/` 3442 files, `plugin-remote-fanout/`, `scripts-mesh/`, `PRE-HEAD.txt`, `stash-list.txt`, `untracked-list.txt`) |
| `journal.py check` | `0 error(s), 187 warning(s), 83 info` |

**The local commits are not journal commits.** `origin/main..main` is 5 commits touching only
`AGENTS.md`, `docs/mesh/151-*`, `presets/*`, `scripts/mesh/guard-service-state.sh`,
`settings/machines/*`, `tests/test_guard_service_state.sh`. Nothing in `journal/` is committed
locally, which is why the whole journal divergence is untracked-file-shaped.

---

## 2. THE LIVE WRITER IS NOT A BACKGROUND PROCESS — IT IS A SESSION WRITING NOW

This is the fact the previous attempt was defeated by, and it is worth stating with numbers. Entry
files created by another live session on this machine, from mtimes:

```
18:17:27 handoff/H3533.md      18:29:06 pain/P3021.md
18:21:09 lessons/L3526.md      18:29:56 pain/P3022.md
18:26:15 lessons/L3527.md      18:30:47 lessons/L3528.md
18:28:59 handoff/H3534.md      18:31:55 lessons/L3529.md
                               18:32:58 wins/W2739.md
                               18:37:36 wins/W2740.md   <-- 30 s before my first measurement
```

`journal/alloc/bands.tsv` shows the same process reserving fresh windows for this host minutes
before I started: `lessons 3526–3589 ZABZ-TECH 22:21 UTC`, `handoff 3534–3597 22:28`,
`pain 3021–3084 22:29`, `wins 2739–2802 22:32`. There is **no git hook** (`.git/hooks` holds
samples only) — the writer is another DSH session appending through `journal.py`, and its appends
are what rewrite `bands.tsv`/`index/*`/`state/*`. It does not stop for this task, so the repair is
run under the journal's own lock and the git step is kept tight and verified afterwards.

---

## 3. The briefed scope was understated — measured, not derived

The task said *12 collisions + 1 exact duplicate*. Measured with the journal's own parser plus git
blob shas (`docs/mesh/163-journal-repair-crossmachine-ids.py`):

```
untracked entry files : 239
also on origin/main   :  51
  different body      :  47
  byte-identical      :   4
```

**47 collisions, not 12.** The briefed list covered `decisions` and `handoff` only; it missed
`lessons`, `pain` and `wins`:

| kind | count | ids |
|---|---|---|
| decisions | 10 | D3032, D3033, D3039–D3046 |
| handoff | 2 | H3501, H3502 |
| lessons | 29 | L3440–L3468 |
| pain | 3 | P3003–P3005 |
| wins | 3 | W2732–W2734 |

**4 byte-identical**, not 1: `H3500`, `L3510`, `P3017`, `P3018`.

This matters operationally rather than pedantically: `git` refuses a checkout over an untracked file
**even when the bytes are identical** — verified in a scratch repo with git 2.52.0:

```
$ git checkout HEAD~1     # untracked f is byte-identical to the checked-out f
error: The following untracked working tree files would be overwritten by checkout:
	f
Aborting
```

So **all 51** overlapping paths have to leave the working tree before `origin/main` can be checked
out. Repairing only the briefed 12 would have left 39 blockers and the rebase would have failed.

---

## 4. `repair-ids` cannot do this job — and that is a tool gap, not a usage error

```
$ python journal/tools/journal.py repair-ids
no id collides with different content — nothing to do
```

`cmd_repair_ids` decides what to renumber from `load_entries()`, which walks `entries/<kind>/*.md`
and nothing else. Within one checkout each id maps to exactly one file, so the local view is
consistent and the tool reports a clean tree. `dedupe` is the same shape: it groups entries **found
in `entries/`** by identity, so an upstream counterpart it cannot read is not a duplicate.

Neither command reads a git ref. `next-id`, `claim`, `ensure_reservation` and `git_max` are the only
places that look at `origin/main`. So the collision class this task exists to fix is exactly the
class the repair tool is blind to.

`repair-ids` is also **unsafe for this rule even when it does fire**: it sorts the colliding group by
`(date, file)` and keeps the earliest-dated copy. The rule here is *the published copy keeps the id*,
which is not a date ordering — in 2 of the 12 briefed pairs the local copy is the earlier one
(D3032, D3033 are same-day ties; D3040–D3046 local copies are dated 2026-10-11 against upstream
2026-10-10, so `repair-ids` would have kept the **local** body at the published path).

### What was done instead — the journal's own code paths, no hand-edited ids

`docs/mesh/163-journal-repair-crossmachine-ids.py` replicates `cmd_repair_ids`' per-duplicate body
verbatim — `parse_entry` → rewrite the id token **in the heading only** → `entry_hash` →
`entry_bytes` → `atomic_write` → `shutil.move` the original into
`archive/collided-ids-<today>/<kind>/` → `record_alias` — with two deliberate changes:

1. **`keep` is forced to the published copy** rather than chosen by date;
2. **the new id is allocated against every git ref**: `taken` is seeded with every filename visible
   in `git ls-tree -r origin/main journal/entries`, so `_next_free` cannot hand back an id that
   already exists upstream, and the number is passed through the journal's own
   `ensure_reservation()` so a mint outside this host's reserved window is **refused, not
   performed**.

The byte-identical four are handled as `cmd_dedupe` handles an identity duplicate: moved to
`archive/duplicates/<kind>/` and `record_alias(id, kind, id, …)` — the published copy keeps the id
and the path.

The whole pass holds `acquire_lock("repair-ids")` (what every blanket-lock command does), so a
concurrent append **defers** (`exit 5`, nothing written) instead of writing into a tree being
renumbered.

Three gates stop a write rather than risk a loss:

* `entry_bytes(parse_entry(f))` must equal the file's bytes **exactly** (round-trip fidelity);
* the new heading must be the old heading with exactly one id-token substitution;
* the renumbered file, re-parsed, must carry an **identical body**.

---

## 5. Root cause — the reservation ledger double-grants one window to two machines

`journal/alloc/bands.tsv` is the cooperative allocator, and it contains rows granting the **same
number range to two different hosts**:

```
lessons   2126  2247  ZABZ-TECH   2026-09-20 18:39 UTC
lessons   2126  2247  SECRATARY   2026-09-20 17:50 UTC
decisions 2325  2388  ZABZ-YOGA   2026-09-22 08:44 UTC
decisions 2325  2388  ZABZ-TECH   2026-09-22 15:00 UTC
lessons   3351  3439  SECRATARY   2026-10-08 00:40 UTC
lessons   3351  3439  ZABZ-YOGA   2026-10-08 00:46 UTC
```

`is_reserved(kind, number)` asks only *"is there a row for my host covering this number"*, so a
double-granted window answers **True on both machines** and both mint the same ids. The `decisions`
case is exactly this task's collision: `ZABZ-YOGA` holds `decisions 2929–3031`; the local
`D3032…D3046` were minted by ZABZ-TECH on top of that window, and ZABZ-YOGA published its own
`D3032…D3046`. The ledger also carries rows with stale stamps (`2026-09-17` repeated on `10-08`
rows), so it is a record that has been edited by more than one writer without a merge rule.

This is **not fixed here** — see §8. It is the reason collisions will recur.

---

## 6. The repair (as it happened)

Measured at 2026-10-11T22:43Z. Two passes were needed; the second is a correction of my own first.

### Pass 1 — the briefed job

```
ceiling decisions  D3046   ceiling handoff  H3534   ceiling lessons  L3529
ceiling pain       P3022   ceiling wins       W2740
renumbered D3032 -> D3047  ... D3046 -> D3056      (10 decisions)
renumbered H3501 -> H3535   H3502 -> H3536          ( 2 handoff)
renumbered L3440 -> L3530  ... L3468 -> L3558      (29 lessons)
renumbered P3003 -> P3023  ... P3005 -> P3025      ( 3 pain)
renumbered W2732 -> W2741  ... W2734 -> W2743      ( 3 wins)
-- 47 renumbered, 0 refused
```

The 4 byte-identical paths (`H3500`, `L3510`, `P3017`, `P3018`) were moved to
`journal/archive/duplicates/<kind>/` with `record_alias(id, kind, id, …)`, the way `cmd_dedupe`
treats an identity duplicate.

**Two of the three gates fired and refused all 47 on the first attempt, before a byte was written.**
That was the gates working and my expectation being wrong, and both corrections are facts about the
format worth keeping:

* `handoff` headings carry **no id** — `## <stamp> · <host> · <title>`. The id lives only in the
  marker line `<!-- e:<kind>|<ID>|… -->`. `cmd_repair_ids` substitutes in the heading and correctly
  leaves it alone when the id is absent; I had required the id to be present.
* The trailing `<!-- j2 … sha=<16 hex> -->` line is `entry_hash(heading, body)`, so **it must change
  when the heading changes**. The legal delta between the two files is exactly three token
  substitutions: the id in the marker, the id in the heading, the `sha=`. The driver now proves that
  identity rather than assuming it, and re-parses the written file to confirm an identical body.

### Pass 2 — my own defect, found by the ledger the rebase made visible

`allocation_ceiling(kind)` is `max(max_number(kind), stamp.json:git_ceiling[kind])` — the **id space**
(entries plus git refs). It does **not** read `journal/alloc/bands.tsv`, and `next_writable()` returns
`max(max_number, allocation_ceiling) + 1` with the host's own window contributing only its
`reserved_from`. **A host therefore mints from the FLOOR of its window and walks upward**, so a
number inside another host's window is not merely reserved — it is the number that host writes next.

Pass 1 allocated above everything *this checkout could see*. It could not see
`decisions 3039–3102 ZABZ-YOGA`, published 2026-10-10, still 48 commits away. The rebase brought that
row in and it covers `D3047–D3056` exactly. ZABZ-YOGA's own `max_number` is `D3046`, so its next
decisions mint is `D3047` — my id. Measured at risk, by ledger row rather than by assumption:

```
16 of 47 pass-1 ids sit inside another host's window
  D3047-D3056  covered by ZABZ-YOGA 3039-3102
  P3023-P3025  covered by ZABZ-YOGA 3002-3065
  W2741-W2743  covered by ZABZ-YOGA 2733-2796
```

(`L3530–L3558` and `H3535–H3536` are covered only by **this** host's windows, so they were already
safe and were left alone.)

Pass 2 moved those 16 above the maximum `reserved_through` for the kind across **all** hosts, taking a
fresh ZABZ-TECH reservation and recording a chained alias:

```
D3047-D3056 -> D3111-D3120      P3023-P3025 -> P3130-P3132      W2741-W2743 -> W2803-W2805
```

A reader follows `D3032 -> D3047 -> D3111`; `journal.py show D3032` prints the alias note.

### Verification (all measured, non-zero where it matters)

| claim | evidence |
|---|---|
| no body lost | `163-verify.py`: 47/47 original archive bodies sha256-equal to the final files' bodies; `journal.py check` exit **0**, **0 errors** |
| no id means two things | `check` reports 0 errors; all 47 final ids resolve to exactly one entry |
| the rule was applied | 47/47 old ids now have their **published** copy back in the tree holding a **different** body |
| the repair caused no breakage | dangling refs targeting any id this repair touched: **0** (of 198 total) |
| nothing left blocking | untracked paths that `origin/main` wants to create: **0** |

`check` went `0/187/83` → `0/217/83`. +30, and each part is accounted for: **16** are
`alias D3047 -> D3111 (decisions): canonical id is missing` — the honest cost of a two-pass repair,
where the alias chain has a middle link (the original row still points at the pass-1 id, which no
longer exists as a file; `index/aliases.tsv` is append-only and generated, so it was **not** hand-edited).
The remaining ~14 are inherited: the rebase brought origin/main's tree, and **none** of the 198
dangling refs targets an id this repair touched.

## 7. The sync

| | |
|---|---|
| HEAD before | `7c82d2d4588a705469dbea17a67bde011c5e353b` |
| HEAD after | `074bac9fadb276a215cbd9199222e741692eec79` |
| ahead / behind after | **0 / 0** — fully in sync |
| `origin/main` | `074bac9…` (same commit) |

**Two things had to move out of the working tree first, and only one of them was in the brief.**
Besides the 239 untracked entries, **8 non-journal untracked files were paths that `origin/main`
wants to create** and each would have aborted the checkout *even though all 8 were byte-identical to
upstream* (verified in a scratch repo with git 2.52.0: `error: The following untracked working tree
files would be overwritten by checkout`). They were moved aside with a sha256 manifest to
`harness-config-presync-backup-…/presync-blockers-20261011T2245Z/` and the rebase restored the
identical bytes from `origin/main` (all 8 re-verified `OK`).

**Rebase, attempt 1 — aborted, per the brief.** `add/add` conflict in `AGENTS.md`. Aborted, never
resolved blindly. Then measured: upstream's `AGENTS.md` is byte-identical to ours except that ours
carries a redundant `---` separator, and the other 4 files our commit adds
(`scripts/mesh/guard-service-state.sh`, `settings/machines/host-posture.tsv`,
`tests/test_guard_service_state.sh`, `docs/mesh/151-*`) are **identical** to upstream's. Our commit
was already upstream. So the conflict was a formatting difference, not a disagreement.

**Rebase, attempt 2 — completed.** The only tree change was taking `origin/main`'s proven-superset
`AGENTS.md` for that one path; `git rebase --continue` then reported *"Successfully rebased and
updated refs/heads/main"*. No force-push, no `reset --hard`, no `clean`, no entry deleted, no stash
of anyone else's dropped.

**`git stash pop` conflicted, as predicted (all 7 files had also changed upstream), and the stash was
left on the list** — `stash@{0}: On main: post-repair-20261011T2250Z` is still there. The tree was
then made usable without a blind merge, because a conflicted `alloc/bands.tsv` is a live hazard for
the session still appending:

* `journal/alloc/bands.tsv` (reservation ledger) and `journal/state/status.tsv` (append-only status
  tier) — **union of rows, deduplicated**. Upstream 119 + ours 116 → **126** unique rows; every row
  from both sides is present and asserted so. This is the only resolution that loses nothing: it
  keeps upstream's 10 new windows *and* this host's 7.
* `journal/index/{entries.tsv,journal.db,stamp.json}`, `journal/state/absorb-stamp.json`,
  `journal/state/owner-questions.md` — published version, then `journal.py index` rebuilds the cache
  from the merged tree. No conflict markers remain anywhere (verified, all 0).

**An unexplained push happened while this ran, and it was not mine.** `refs/remotes/origin/main@{0}:
update by push` moved `origin/main` from `313c8b0` to `074bac9` between 22:46 and 22:49Z. I ran no
`git push`. It was a clean **fast-forward** (`313c8b0` is an ancestor), so no force-push occurred and
no rule was broken, but the reader should know the repaired commits are now published by something
other than the agent doing the repair — consistent with the live-writer session on this host, which
is also committing journal work (`6d057fe … (L3667)`).

### The 239 local entries, accounted for

```
239 untracked entry files at the start
 -47 renumbered (original bytes now in archive/collided-ids-2026-10-11/<kind>/<old_id>.md)
 - 4 byte-identical (original bytes now in archive/duplicates/<kind>/<id>.md)
+47 renumbered copies exist under their new ids in entries/
== 239
entries/ at 22:49Z: 3677 .md  |  untracked entries: 237 (= 235 after the repair + 2 the live writer
appended during it: L3668, W2806)  |  archive/collided-ids-2026-10-11: 63 .md (47 originals +
16 pass-1-id files)  |  aliases.tsv: 574 rows
```

Every one of the 239 is present either at its path or in the archive beside its renumbered twin, and
no original body was mutated: the driver's three gates plus the archive/final sha256 comparison above.

## 8. Open items — not done, on purpose

1. **The reservation ledger double-grants windows, and that is the root cause.** `bands.tsv` still
   contains rows granting one range to two hosts (`decisions 2325–2388` to both ZABZ-YOGA and
   ZABZ-TECH; `lessons 3351–3439` to both SECRATARY and ZABZ-YOGA; `lessons 2126–2247` likewise).
   `is_reserved()` asks only *"is there a row for my host covering this number"*, so a double-granted
   window answers True on both machines and both mint. **Not fixed here** — it needs a merge rule for
   the ledger, which is an estate-level decision, not a repair.
2. **A reservation taken on this host is LOCAL, not published.** `ensure_reservation` reserves in
   `alloc/bands.tsv` and says so: *"reserved … LOCALLY and NOT published; run `journal.py publish`
   before another machine can see it."* The new windows for `D3111–`, `P3130–`, `W2803–` are
   therefore invisible to other machines. `journal.py claim <kind>` / `publish` is the documented
   next step and needs a working connection to `origin`. Until then another host with a stale
   checkout can still mint into them.
3. **`repair-ids` cannot see this defect class, and pass 2 should not have been necessary.** The
   concrete tool change: `is_reserved` / `ensure_reservation` / `repair-ids` should read the ledger
   **as published on `origin/main`** (`git show origin/main:journal/alloc/bands.tsv`), not only the
   working copy. Had pass 1 done that, it would have allocated above `decisions 3102` in the first
   place and the 16 chained aliases and their 16 warnings would not exist.
4. **The 16 chained-alias warnings.** Clearing them means pointing the original alias rows straight
   at the final ids. `index/aliases.tsv` is generated and the hard rule forbids editing it by hand,
   so it is left as `check` correctly reports it.
5. **The 8 non-journal blockers and both stashes are recoverable** and were left in place:
   `presync-blockers-20261011T2245Z/` (8 files + SHA256SUMS), `presync-tracked-20261011T2250Z/`
   (the 8 pre-rebase tracked-modified files + SHA256SUMS), and `stash@{0}`.
6. `stash@{1} presync-zabz-tech-20261011-222023` (the previous attempt) is **untouched** — not
   dropped, not popped. Whoever resumes this should know it is still there.

