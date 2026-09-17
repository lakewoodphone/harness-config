# 107 — the journal convergence: 18 contested ids, and the three instruments that could not see them

**Program:** `journal/**` (the collision named by `journal/reference/id-collision-20260917.md`, which
`journal/state/in-flight.md` §A told every machine to treat as a stop-work condition).
**Date:** 2026-09-17, 16:2x–16:4xZ (12:2x–12:4x local). **Author:** a delegated session on **ZABZ-YOGA**.
**Owns:** the convergence on this machine, this file, and `journal/state/in-flight.md` §A.
**Staged paths were `journal/**` and `docs/mesh/**` only** — never `git add -A`. Other streams' staged
work (`scripts/lpt-hub-refresh.sh`, `scripts/lpt-recon-check.sh`) was deliberately left staged and
**uncommitted**; a pathspec-limited commit (`git commit -F msg -- journal docs/mesh`) was used because a
plain `git commit` would have swept those two files in.

**What was NOT done.** No history was rewritten anywhere: no `reset`, no `rebase`, no `--force`, no
`clean`. `secratary` was not touched. The other machine's checkout was **not** touched, read or queried
— only the snapshot that machine's own session had already taken was used. The owner's laptop engine
(pid 4880) was never signalled, restarted or queried. No entry file was hand-edited and no file was
hand-renamed; every id was allocated by `journal.py append`.

**Provenance convention.** **MEASURED** = run in this session, command and raw output given. **READ** =
out of source. **REFUSED** = asked for and not obtained, stated as a refusal rather than a silence.

---

## 1. Headline

1. **The brief's numbers are right, and they were re-derived from source rather than from the cache.**
   MEASURED: **10 live** collisions against `origin/master` (`D254, H464, H465, H466, L1906, L1907,
   L1908, L1909, P242, P244`) and **8 latent** against the other machine's unpushed set (`D252, D253,
   H467, H468, L1910, L1911, L1912, P246`) — 18, every pair two genuinely different entries. `check`
   reported **0 errors** while all 18 existed.
2. **The convergence is done and pushed.** The merge keeps origin's entry at every contested id; this
   machine's conflicting entry moved to a fresh id allocated by the sanctioned writer. `3568d39` is on
   `origin/master`, the converged tree is `0 0`, `check` = **0 errors**, `verify` = **FAIL=0 WARN=0**,
   and the no-loss gate reads **1728 = |L ∪ O| = 1728, delta 0**.
3. **Two of the three instruments that should have caught this cannot, and one of them lies.** `check`
   is single-tree by design; `idguard` reads a *generated cache* and therefore **undercounts** (9 when
   the answer is 10); and `repair-ids`, the command whose whole purpose is this class, **left the
   duplicate behind** — it is fixed here and the fix is proved.
4. **The collisions are resolved; the thing that generates them is not.** After this push, both
   machines mint from the same refs and the same "next free number" is the same in every kind. The
   next pair of concurrent writes recreates this exact defect. §7.
5. **One correction to the inherited analysis.** The reference document concluded that a one-sided
   renumber cannot converge and that the side which moves must be the side which pushes second. That
   is true only of a renumber done **before** the other side's ids are in the mover's merged
   high-water mark. Measured here: the laptop merged origin/master **first** (so origin's ids entered
   its refs), then renumbered **above** the maximum of *origin's ids and the other machine's recorded
   unpushed ids*. It pushed first and it converged. §4.3.

---

## 2. Preservation first, and the proof that it took

**MEASURED before anything moved.** Every path under `journal/**` and `docs/mesh/**` that was untracked
or modified relative to `HEAD` was copied to a location **outside the repo** —
`_scratch/107-convergence/preserve-worktree/` — with a manifest of id, size, sha256 and the re-hash of
the copy: `_scratch/107-convergence/preserve-manifest.tsv`.

```
manifest rows: 29
unverified   : 0
```

**23 of the 29 rows are entry files whose bytes existed in no commit anywhere** — five modified in
place (`H464, H465, L1906, L1907, P242`) and eighteen untracked (`D252, D253, D254, H462, H466, H467,
H468, L1902, L1908, L1909, L1910, L1911, L1912, P244, P246, W201, W202, W203`). All 18 contested
entries are in that set.

> **Correction to the inherited record.** `journal/state/in-flight.md` §A said *"nine of the colliding
> entries exist in no commit anywhere"* and the brief repeats it. MEASURED: it is **23 entry files**,
> and **all 18** of the contested ones. The "nine" figure listed ten files and undercounts the rest of
> the worktree.

The other machine's side was preserved by that machine's own session at
`_scratch/106-closing/desktop-untracked-entries.zip`, **sha256 `520A0BD07E2446C42CB5D0133A782043CD2D4CE8F89B99C6B0DB95BFE4307F5A`**
(50,047 B) — re-hashed here and matching the value the brief quoted, and copied again into
`_scratch/107-convergence/desktop-snapshot/` so both sides of every collision live outside one repo.

**The durable preservation is stronger than the file copies.** The at-risk bytes were committed as
`622876e` (`journal(107): commit this laptop's unpushed entries before any merge`), so they are now git
objects on `origin` — a `checkout`, `clean` or `pull` in this repository can no longer destroy them.
The file copies and the manifest are the belt; `622876e` is the braces.

---

## 3. The merge — and the wall that forced the throwaway worktree

**MEASURED, read-only detector, in the owner's working tree:**

```
$ git read-tree -n -u -m HEAD origin/master
error: Untracked working tree file 'journal/entries/decisions/D254.md' would be overwritten by merge.   exit=128
```

That is the refusal the brief predicted. Committing `622876e` removed it; the next refusal was **not**:

```
$ git read-tree -n -u -m HEAD origin/master          # after 622876e
error: Entry 'scripts/lpt-hub-refresh.sh' would be overwritten by merge. Cannot merge.   exit=128

$ git merge --ff-only origin/master
error: Your local changes to the following files would be overwritten by merge:
        scripts/lpt-hub-refresh.sh
        journal/state/absorb-stamp.json
Aborting
```

`scripts/lpt-hub-refresh.sh` is **another stream's staged, mid-flight work** (worktree and index both
`f458cef04dbd8daa0151d2dbbe77787051a86477`, where `HEAD` holds `dc4287e5…` and `origin/master` holds
`679e27a0…` — three different blobs, and the other stream's version is *not* origin's: 15 insertions /
117 deletions against it). Committing, stashing or resetting it was out of scope and would have
disturbed live work, so **the owner's working tree was left exactly as it was found** and the whole
operation was done in a throwaway `git worktree`, which is the pattern the brief prescribed.

```
$ git worktree add -b converge/107 _scratch/107-convergence/wt 622876e
$ git merge --no-commit --no-ff origin/master
CONFLICT (add/add): D254, H466, L1908, L1909, P244
CONFLICT (content): journal/index/entries.tsv
```

Five add/add conflicts — not ten, and that distinction matters. `H464, H465, L1906, L1907, P242` did
**not** conflict, because `origin/master` never modified those paths: the colliding bytes were *this*
machine's local modification of a file whose upstream copy was unchanged. Git would therefore have
silently kept the laptop's version and **replaced origin's entry at origin's own id**. That is the
trap the brief's rule ("origin/master's entry keeps the id") is for, and it had to be applied to five
paths git reported as clean.

Resolution, applied to all ten and verified per path:

```
$ for p in D254 H464 H465 H466 L1906 L1907 L1908 L1909 P242 P244; do git checkout origin/master -- journal/entries/*/$p.md; done
$ git ls-files -u          ->  none
$ git hash-object <path> == origin/master:<path>   ->  OK for all 10
```

**A further silent loss was caught by the gate, not by git.** `journal/entries/pain/P243.md` existed at
`HEAD` and on `origin/master` and had been **deleted in this working tree** (uncommitted, at the time
`622876e` was made). Because upstream had not touched it, the merge would have honoured the deletion
**silently** — no conflict, no message — and a unique entry ("the production-order linker attaches
housekeeping tasks to customer cases", 2,476 B) would have left the fleet's record. It carried **no
status event in `state/status.tsv`, no reference from any other entry, and no commit explaining it**.
Origin's copy was restored. The deletion remains visible in Git history, so a stream that meant it can
repeat it in one command; dropping a unique entry is the more expensive error. This is the one
judgement call in this document.

---

## 4. The renumber

### 4.1 Every id was allocated by the sanctioned writer

Eighteen entries were re-written with `journal.py append --body-file` — never `--body` — reading each
source body out of commit `622876e`. For each, the heading was reconstructed and asserted equal to the
original *before* writing (`build_heading(kind, old, title, date, host) == old_heading`), and after
writing the new file was asserted on nine properties: new id free against both other id sets, parses
with 0 problems, marker/filename id equal, **body normalized equal**, **body hash equal**, **body BYTES
equal**, heading equal to the old heading with the id token swapped, and date/host/status/tags/refs
identical.

```
  D252   -> D256   PASS     H467   -> H483   FAIL (title text only: see 4.4)
  D253   -> D257   PASS     H468   -> H484   PASS
  D254   -> D258   PASS     L1906  -> L1920  PASS
  H464   -> H480   PASS     L1907  -> L1921  PASS
  H465   -> H481   PASS     L1908  -> L1922  PASS
  H466   -> H482   PASS     L1909  -> L1923  PASS
                            L1910  -> L1924  PASS
                            L1911  -> L1925  PASS
                            L1912  -> L1926  PASS
                            P242   -> P249   PASS
                            P244   -> P250   PASS
                            P246   -> P251   PASS
verified 18 of 18   archived 8   failures 1 (H467, heading title text; bodies byte-identical)
```

Machine-readable, in the repo: **`journal/reference/id-collision-20260917-renumber.tsv`** (old id, new
id, kind, which side keeps the old id, both headings, body sha256, verdict). `D191` step 3 asks for the
map as a file and not as prose; this is that file.

### 4.2 The eight whose old path held *this* machine's content were moved, not deleted

`D252, D253, H467, H468, L1910, L1911, L1912, P246` are the ids `origin/master` does not have, so the
merge left this machine's file at the old id. Those eight files were **moved** to
`journal/archive/collided-ids-2026-09-17/<kind>/` (sha256 re-verified after the move), freeing the old
id for the other machine's entry and losing no byte. The destination is the house convention created
for exactly this defect on 2026-09-15 (`archive/collided-ids-2026-09-15/` holds `D185, D186,
H322-H328, L1637-L1639, W149, W150`), and `tree_signature()` excludes `archive/`, so archived copies
cannot leak back into the cache or the log.

**No aliases were recorded for the 18, deliberately.** `aliases.tsv` means *"alias_id → canonical_id,
so a collapsed copy is still reachable"*. After this merge the old id **legitimately belongs to a
different entry** — origin's for the ten, the other machine's for the eight — so a row saying
`D254 -> D258` would be a permanent claim that is false, which is the exact failure `record_alias`'s own
comment warns about. The old→new relation lives in the map file, where it is a record rather than a
claim about the id space.

### 4.3 The one id the allocator could not see — `D255`

`append` allocates `max(entries/ + index + log/** + flats, allocation_ceiling, every origin ref) + 1`.
MEASURED after the merge, that is `D255, H480, L1920, P249, W204`. **`D255` is the other machine's**:
it holds a `D255` entry unpushed, in no ref and no file here, so `append` would have handed out the
same number again — a fresh collision created by the fix. The collision map skips `D255` for exactly
this reason (`D252→D256, D253→D257, D254→D258`), so the map and the allocator had to be reconciled.

`git_ceiling` is the field `allocation_ceiling()` (journal.py:2781) trusts and `rebuild_cache()`
carries forward (journal.py:1078, 1087). Its only writer, `note_git_ceiling()` (journal.py:2794), is
**dead code — nothing calls it**, which is why the field was `{}` on every machine. It was called once,
for one number:

```
allocation_ceiling now: {'handoff': 479, 'lessons': 1919, 'pain': 248, 'decisions': 255, 'wins': 203}
  D252 -> D256   D253 -> D257   D254 -> D258      # the map's own numbers, reproduced
```

One number, in a documented field, through the tool's own writer — not a hand-edited file. It buys the
gap the field's docstring says is free ("a gap costs nothing, a reused number destroys the meaning of
every citation to it"). §6.3 records what the durable version of this should be.

### 4.4 The one deviation, stated plainly

`H467 → H483`: the source entry's heading title was the **literal placeholder string `H467`** — the
session that wrote it never titled it. `append` reproduces a title verbatim, so `H483`'s heading still
ends `· H467`. The marker, the filename and the folder all say `H483`, the body is **byte-identical**,
and `check` is silent because a handoff heading carries no id token. Correcting the title would have
required a second append for one entry — a second id for one entry, which is worse than the untidy
title. The map file carries this as a NOTE.

**My own harness bug, recorded because it briefly looked like 18 tool failures.** The first run's report
said `FAIL D252 … cannot parse append output` for all 18. The appends had all succeeded; my driver was
parsing *pretty-printed* JSON with `stdout.splitlines()[-1]`, which is `}`. The 18 entries were then
verified by re-reading each file and comparing it against the source body — the assertions above —
rather than by trusting the run's own report, and no second set was minted to "fix" a failure that did
not exist.

---

## 5. The gates

**`journal.py check`, before and after.**

```
before (owner's working tree, HEAD e0dd07cac, all 18 collisions live):
  -- 0 error(s), 79 warning(s), 80 info          exit=0

after (converged tree, 3568d39):
  -- 0 error(s), 85 warning(s), 80 info          exit=0
```

A `check` that reports 0 in both states is the point: it cannot see this class. The 6 extra warnings
are origin's incoming entries carrying their own dangling refs; warnings are not errors and none is
new to this machine's content.

**`journal.py verify`** (the independent no-loss gate, frozen v1 parser):

```
## VERDICT   FAIL=0 WARN=0
   v1 next-id lessons -> L1927 (must be above the real maximum)
```

**Two entries were moved, one was re-added, two are the parents.** The content-level no-loss gate
compares `identity_of` values — body-normalised identity, the same comparison the 2026-09-15 fork
verification used — across both parents and the result:

```
entries:  L(parent, this laptop)      = 1702
          O(parent, origin/master)    = 1705
          R(result, merged+renumbered) = 1728
          |L union O| by identity      = 1728

GATE 1  every one of L's 1702 identities is present            PASS
GATE 2  every one of origin's 1705 identities is present       PASS   (includes restored P243)
GATE 3  |R| = 1728 = |L union O| = 1728, delta = 0             PASS
GATE 4  each of the 18: old id free, new file present, body present  PASS (18/18)
```

The arithmetic is checkable by hand: `1705 (origin) + 13 (ids only this machine had that origin
lacks) + 10 (this machine's content at the ten live contested ids, renumbered) = 1728`.

**`selftest`: 239 of 240, before and after the tool fix.** The single failure is
`no lock file was left behind`. It was reproduced with the **unpatched** tool in the owner's working
tree, so it is pre-existing and unrelated to the change (`cmd_repair_ids` acquires no lock) — and it is
**not a flake**: §6.6 reproduces the same leak directly, twice, on real trees.

---

## 6. The instruments

### 6.1 `check` cannot see a cross-tree collision — and where the fix belongs

MEASURED: `check` = **0 errors** with 10 live collisions. It is not broken; it is **single-tree by
contract**. It builds its world from `scan_tree()` (journal.py:3170), which is `load_entries()` (the
working tree's `entries/`) plus `legacy_candidates()` (`log/**` and the flats). Nothing in it ever asks
what a *ref* holds, so an id that is different on `origin/master` is not merely un-reported — it is
**invisible**.

**What it would take, precisely.** Both sides are already addressable in two subprocess calls with no
per-file cost:

* the local side: `git hash-object --stdin-paths` over the entry paths — one call, gives each file's
  blob id;
* the upstream side: `git ls-tree -r origin/master journal/entries` — one call, gives each path's blob
  id.

Same path + different blob id **is** the collision, and a path on one side only is the missing/absent
set that has to be reported too. No cache, no `idguard` staleness, no fetch (the ref is local).

**Which home.** *Not* `check`. `check` is on the read path — every reader and the gate call it, its
whole design is cheap and offline, and giving it a subprocess and a ref would make the always-read
surface slower and dependent on a remote-tracking ref. *Not* a new verb: `D191` asked for a `reconcile`
verb on 2026-09-15 and it still does not exist, but a fourth path around the same problem is how the
fleet got here. The right home is **`idguard.py`**, which is the only instrument that already knows
about upstream and already feeds the sync keeper's `id_collisions` field — it needs its *input* changed
from the generated `journal/index/entries.tsv` to the two calls above (§6.4 shows why the cache cannot
be trusted). A `reconcile` verb remains the natural place to *act* on what `idguard` reports; this
session did not build it.

### 6.2 `repair-ids --apply` left the duplicate behind — reproduced, cause, fixed, proved

**Reproduced on a synthetic tree** (two files declaring marker `L1999`, different bodies):

```
check BEFORE  ->  ERROR entries/lessons/L1999b.md: id in the file name (L1999b) disagrees with the marker (L1999)
                  ERROR duplicate id L1999 in lessons names 2 different entries: L1999.md, L1999b.md
                  -- 2 error(s), 0 warning(s), 1 info          exit=1
repair-ids --apply
                  L1999 (entries/lessons/L1999b.md) -> L2000  (kept L1999 at entries/lessons/L1999.md)
files after   ->  L1999.md (marker L1999), L1999b.md (marker L1999), L2000.md (marker L2000)
check AFTER   ->  -- 2 error(s), 0 warning(s), 1 info          exit=1
```

The command reports success and the invariant it is named for does not hold.

**One-line cause.** In `cmd_repair_ids` the renumbered copy was written and the file it replaced was
never vacated — `journal.py:3711` (pre-fix) `atomic_write(entries_dir() / kind / (new_id + ".md"),
entry_bytes(full))` with no move of `_path_of(dup["file"])` afterwards, where `cmd_dedupe` has done
exactly that since it was written (`journal.py:3672-3679`, `shutil.move` into
`archive/duplicates/<kind>/`).

**Fixed** — the renumbered copy is written first, then the replaced file is moved out of `entries/` to
`archive/collided-ids-<date>/<kind>/<id>.md` (collision-safe if the destination exists), and the alias
row now carries host, sha and source the way `dedupe`'s does. **Proved on the same synthetic tree with
the patched tool:**

```
check BEFORE  ->  -- 2 error(s)   exit=1
repair-ids --apply  ->  L1999 (entries/lessons/L1999b.md) -> L2000  (kept L1999 at entries/lessons/L1999.md)
entries/ after ->  L1999.md, L2000.md
archive after  ->  archive/collided-ids-2026-09-17/lessons/L1999.md
aliases        ->  L1999  lessons  L2000  id collided with different content; ...  2026-09-17  ZABZ-YOGA  1df38c4b7982ecfa  archive/collided-ids-2026-09-17/lessons/L1999.md
check AFTER   ->  -- 0 error(s), 0 warning(s), 1 info          exit=0
```

### 6.3 The ceiling field has no live writer

`note_git_ceiling()` (journal.py:2794) exists, is documented as the thing that records "a ceiling
measured from git refs, so reads do not need a subprocess", and **is called from nowhere** — `grep`
finds only its definition and `rebuild_cache`'s carry-forward. Consequence: `git_ceiling` is `{}` on
every machine, `allocation_ceiling()` is always just `max_number()`, and the only thing that saves
`append` from a stale number is the live `git_max(fetch=True)` subprocess in the write path. §4.3 used
the field for the one number no ref can express. **Durable fix, not made here:** call it from `git_max`
so a measured ceiling persists, and give allocation a way to record a claim that is not in a ref — a
`--floor`/reserve argument, or `idguard --floor` (which exists and nothing calls) wired to something.

### 6.4 `idguard` undercounts, and this was verified rather than inherited

`idguard.py` compares `journal/index/entries.tsv` **on disk** with the same file at upstream. MEASURED:
`idguard` reported **9** collisions while the content comparison finds **10**. The missing one is
`D254`, and the mechanism is that the other machine committed entries without regenerating the cache:

```
id      in origin's COMMITTED entries.tsv   entry committed in origin/master
D254    False                              True
H474    False                              True
L1914   False                              True
P247    False                              True
H464    True                               True   ... all nine others True/True
```

So the gate is only as fresh as a generated file that a writer has to remember to rebuild — and in this
window `D254` was the *live* collision, i.e. the undercount hid exactly the case that mattered. §6.1's
two-call comparison cannot exhibit this failure mode.

### 6.5 `append --alias-of` is accepted and ignored — and must stay ignored

`--alias-of` is declared for `append` (journal.py:3925) and is **never read** by `cmd_append`, which
hardcodes `"alias_of": ""` (journal.py:2945). The flag is therefore a silent no-op. It must **not** be
"fixed" by writing it: `parse_entry` treats a live entry that declares `alias_of` as a problem —
*"this file declares itself an alias of … and should not exist"* (journal.py:604-605) — so writing it
would turn every renumbered entry into a `check` error. The honest choices are to remove the flag or to
make it refuse loudly; this session did neither, and recorded it.

### 6.6 Two commands leave their `.lock` behind, and the tool's own selftest says so

Found because `doctor` refused to be quiet about it. MEASURED on the converged tree:

```
lock            HELD by questions 15240@zabz-yoga:1789663316 (206s)
writable        True
```

and the owner's working tree's journal held `import-legacy 6296@zabz-yoga:1789662393`. **Both holder
PIDs were dead** — `Get-Process -Id 15240` and `-Id 6296` return nothing, and neither appears in the
running Python process list — and both commands had **exited 0**. So this is not a crashed process.

Reproduced directly, one command each, lock file absent beforehand:

```
$ python journal/tools/journal.py --root <worktree>/journal questions
state/owner-questions.md: 24 open, 65 closed
lock before: False        lock after: True        content: questions 12764@zabz-yoga:1789663555
holder pid 12764 alive: False

$ python journal/tools/journal.py --root <synthetic>/journal import-legacy
-- dry run: identical 0 · aliased 0 · new 0  (entries/ 1 -> 1); re-run with --apply
lock before: False        lock after: True        content: import-legacy 23592@zabz-yoga:1789663577
```

**This is the assertion `selftest` fails** (§5), which means that failure is a real defect and not a
flake. It is **benign for the tool itself** — `_lock_holder_is_dead()` (journal.py:2538) recognises a
dead holder, which is why `doctor` printed `writable True` while the lock file was present — but every
later reader is made to ask whether a writer is live, and the tool's own integrity check fails.

Both stale locks found in this session were **removed** (they were this session's own artefacts, the
holders were provably dead, and a `.lock` is not data); `doctor` then reported `lock free`. The code
path that exits without releasing was **not** chased — this is a characterised defect, not a fixed one,
and it is the reason a fifth item belongs on the list above.

---

## 7. What this means for the other machine — the defect that is NOT fixed

The 18 collisions are resolved **because no id this machine now holds is one the other machine holds**:
the other machine's recorded unpushed maxes are `D255, H478, L1917, P246` and this machine moved to
`D256-D258, H480-H484, L1920-L1926, P249-P251`.

**But the generator of the collision is untouched.** `next-id` and `append` both compute
`max(visible ids) + 1`; after this push both machines see the same refs, so both will choose
`D259, H485, L1927, P252, W204`. MEASURED on the frozen v1 reader too: `v1 next-id lessons -> L1927`.
**The next pair of concurrent writes recreates this defect**, with the same tools unable to see it,
unless one of them fetches after the other pushes and before writing.

The obligation this creates is: **the other machine should merge `origin/master` before its next
journal write.** With `append`'s default fetch it will then mint above `L1926` rather than at `L1927`.
That is a timing obligation, not a mechanism, and it is why the reference document's §5.6 said the real
fix is still missing: **a reserved band per machine, or a host suffix on the id** — what `D191`/`D198`
asked for and what does not exist. This session did not design it, per the brief ("do not redesign the
journal's id model tonight"). It is the single highest-value follow-up.

`journal/state/in-flight.md` §A was rewritten with this state and this obligation, because the journal
is what a future session reads and no entry id was minted to say it (§7's own defect is why).

---

## 8. Commits, and what could not be verified

```
622876e  journal(107): commit this laptop's unpushed entries before any merge      (this laptop's parent)
45bc301  origin/master before the merge                                            (origin's parent)
3568d39  journal(107): merge origin/master and move THIS machine's lineage off the 18 contested ids
         $ git push origin converge/107:master   ->  45bc301..3568d39  converge/107 -> master   exit=0
         $ git ls-remote origin master           ->  3568d390f2b3fbf8834a77948181a229bb1f3b39  refs/heads/master
         converged tree: rev-list --left-right --count HEAD...origin/master  ->  0  0
```

**REFUSED / not verified, stated as refusals:**

* **The owner's working tree could not be brought to `0 0`.** MEASURED after the push:
  `0  11` (nothing unpushed; 11 commits behind), and both a read-only detector and a real
  `merge --ff-only` refuse on `scripts/lpt-hub-refresh.sh` (another stream's staged work) and on
  `journal/state/absorb-stamp.json` (a generated state file touched by the journal tools as other
  streams write). Git aborted **atomically** — `HEAD` is still `622876e` and the other stream's file is
  still `f458cef…`. Clearing this needs the other stream to commit its file; **nothing is at risk while
  it waits**, because `622876e` is on `origin` and every one of the 23 files is a git object.
* **The other machine's current untracked set.** The only evidence is the snapshot taken by that
  machine's own session at 12:14:45 local (21 files). That checkout is live and may have moved. Its ids
  were treated as authoritative for the purpose of *not* choosing them, which is the safe direction:
  if it has minted more since, the ids this machine moved to are still above what it held then.
* **Whether the other machine has its own copy of this collision.** It was never asked to run
  `idguard`, and it was not touched — reading its checkout was out of scope.
* **`idguard` was not run against the pushed tip on the other machine**, so `collisions: 0` is asserted
  on this machine's view only. What is proved here is that no id this machine holds is one the other
  machine's snapshot holds.
* **`repair-ids` was not exercised against a real cross-tree collision** — it still has no verb for
  one. §6.2's fix is proved on the shape it exists for (two files, one tree, one id); the class this
  document is about still has no tool.
