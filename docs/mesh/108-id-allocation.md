# 108 — ID allocation: the reservation ledger that makes a cross-machine collision impossible

**Program:** `journal/**` — the allocator in `journal/tools/journal.py`, the new
`journal/tools/verify-alloc.py`, and this file.
**Date:** 2026-09-17, 16:4x–17:2xZ. **Author:** a delegated session on **ZABZ-YOGA**.
**Predecessor:** `docs/mesh/107-journal-convergence.md`, which resolved the **instance** and
named the generator as the highest-value follow-up. This is that follow-up.

**Read §5 first if you read nothing else.** §5 is the incident: an earlier version of this change
had `append` claim-and-push inline, and recording a journal lesson therefore reverted the fleet's
`origin/master` by 1,249 paths, exit 0, nothing visibly wrong. The auto-push is gone, the shape
is now strictly separated, and `verify-alloc.py` asserts the separation so it cannot come back
silently.

**Staged paths were `journal/**` and `docs/mesh/**` only** — never `git add -A`. Other streams'
mid-flight work (`packages/plugin-cost/**`, `presets/zabz/agent.cordis.yml`,
`settings/base.yaml`, `scripts/**`) was left exactly as found.

**What was NOT done.** No history was rewritten except the one authorised rewind in §5.4, which
restored a ref to a commit it had pointed at minutes earlier and destroyed nothing. No entry file
was edited or renamed. No existing id changed meaning.

**Provenance convention.** **MEASURED** = run in this session, command and raw output given.
**READ** = out of source. **NOT VERIFIED** = asked for and not obtained, stated as a refusal.

---

## 1. Headline

1. **The generator is fixed, and the fix is proved by simulation rather than asserted.** Two
   isolated trees that cannot see each other's uncommitted work, minting concurrently from one
   committed base: the pre-change tool (taken out of git at `622876e`, never retyped) mints
   **`L2` on both machines**; the new rule has the first machine claim `L2..L65`, the second
   fetch that published claim and mint **`L66`**. §6.1–6.2.
2. **`append` can no longer move any ref.** Measured: the remote ref is byte-identical before and
   after three appends, and no local ref moves either. Publishing is a separate explicit command.
   §5, asserted by `verify-alloc.py` check C.
3. **The chosen shape is (c), a monotonic window reserved in the repo and published**, not a
   per-host suffix. Existing ids keep their exact format and meaning, so every existing parser
   and the frozen v1 reader needed no change. §3, §4.
4. **A machine that cannot publish cannot extend its window — but it is not bricked.** Inside a
   window it already holds it keeps writing offline; at the window edge with no reachable ref it
   refuses, exits non-zero, and writes nothing. §7.
5. **Two smaller defects fixed and proved:** every mutating command leaked `journal/.lock`, and
   `note_git_ceiling()` was dead code. §8.
6. **`verify-alloc.py`: 21 checks, 0 failures.** `selftest`: 239/240 → **240/240**. `check`:
   **0 errors** before and after.

---

## 2. The requirement, stated plainly

Two machines that cannot see each other's uncommitted work must never mint the same id, and a
reader must be able to tell which machine minted which id and in what order, **without a central
allocator**.

The measured mechanism, unchanged across all four incidents: `append` allocated
`max(everything it can see) + 1`, and it cannot see another machine's uncommitted files. The 107
convergence resolved 18 contested ids and left the allocator untouched, so after that push both
machines computed the same next free number — `D259, H485, L1927, P252, W204` — on **both**
(`journal.py next-id`, this worktree, 2026-09-17; the frozen v1 reader agreed).

---

## 3. The three candidate shapes, with their trade-offs

### (a) A reserved band per host, raised by a shared file when it runs out

Each machine owns a contiguous range; a shared file records how far the bands reach.

* **For:** simple; the id is still a plain number; one file to read.
* **Against:** the band width is a guess, and it still needs the shared file to be *readable* to
  be safe — so it inherits the coordination requirement anyway and differs from (c) only in being
  coarser.
* **Why not chosen:** it buys nothing over (c) except that the claim happens less often, and that
  saving is available inside (c) by choosing the window size. Sizing bands from each host's
  historical write rate would make the safety property depend on a predictor, which is the kind
  of thing that silently stops being true.

### (b) A host-derived suffix or prefix — the id carries the minting machine

* **For:** collision-proof **by construction**. No shared file, no fetch, no push, no network: a
  machine that cannot reach anything still mints safely because its namespace is disjoint by
  definition. The only shape needing no coordination at all.
* **Against:** every existing id is bare (`L1927`, `D259`). `L1927-ZY` splits the id space into two
  populations, and every consumer must accept both: the marker regex, filename↔marker agreement,
  `num_of`/`suffix_of`, sorting, `refs=`, the frozen v1 reader, `idguard`, `pairs`, the state tier.
  A mis-parse in any of them produces an id that means two things — the outcome being fixed.
* **Why not chosen:** the compatibility surface is the whole tree, and "existing ids keep their
  meaning" across five heterogeneous nodes makes it the most expensive option rather than the
  cheapest. **It remains the right answer for a future that can break the id format deliberately.**

### (c) A monotonic window reserved in the repo — each machine takes a block and raises the shared ceiling

* **For:** id format untouched, so every existing id and parser keeps working; the reservation is
  visible through the one channel the machines already share; the ledger names the minting machine
  and the moment, so the reader requirement is met without a central allocator.
* **Against:** the claim must be **published** to be worth anything, so a machine with no route to
  origin cannot extend its window; and it costs one publish per 64 ids per kind.
* **Chosen.** §4.

**A fourth shape was considered and rejected without building it: a host-derived *numeric*
offset** (each machine owns `[base + index*stride, …)`). It keeps the bare-number format and needs
no shared state, but the offset table must be a constant known to every reader, and two machines
that both believe they are index 0 collide as surely as before. Making it safe means publishing
the index map — a shared file again, only one that can go stale **silently**, which is the failure
this whole document is about. Rejected as "safety that depends on a convention nobody re-checks".

---

## 4. What was implemented

### 4.1 The ledger

`journal/alloc/bands.tsv`, six columns:

```
kind	reserved_from	reserved_through	host	stamp	rev
lessons	2	65	ZABZ-YOGA	2026-09-17 17:16 UTC	-
lessons	66	129	ZABZ-TECH	2026-09-17 17:16 UTC	-
```

A row means: **this host may write any id of this kind from `reserved_from` to
`reserved_through` inclusive.** Rows are never edited or removed; the union of the local file and
the file at the published ref is the truth, read on every allocation.

**Both bounds are load-bearing, and the floor was the last bug found.** MEASURED: with only a
ceiling, a machine whose window moved up (because another machine had taken the numbers below)
still appeared to cover all the lower numbers, so it minted `L2` out of a window that really began
at `L66` — colliding with the machine that had published `L2`. A four-column row is still accepted
and read as `reserved_from = 1`, so pre-existing rows keep their literal meaning.

### 4.2 The rule at mint time

```
claim   (explicit, may publish):   cover this host's next free id; union with the published
                                   ledger; move the window above every other host's; publish
append  (frequent, LOCAL ONLY):    next = max(entries, index, log/**, flats, ceiling, this
                                   host's window floor) + 1
                                   inside this host's window       -> write it
                                   window spent, local ledger      -> extend LOCALLY, write
                                   window spent, no local ledger   -> REFUSE
                                   no ledger and no origin ref     -> write (fixture/scratch tree)
```

`append` never touches a network or a ref. The window is extended locally and stays local until an
operator publishes it. **The cost of that separation, stated plainly: while a machine is holding a
local window whose top is beyond the published ledger, that window is not yet visible to anyone
else, so another machine could have published the same numbers in the meantime.** Publishing
reconciles exactly that case — it unions, detects the overlap, and moves the window above — and it
does so *before* anything is written into those numbers. That is why `publish` is a first-class
step and not an afterthought.

### 4.3 Why the second machine lands above the first

`reservation_base` is the maximum over the local tree, the refs, **and every reservation any host
holds**. A claim that cleared only the local maximum would hand the second machine the same window
as the first — measured, §6.3, where both machines reserved `L2..L65` and collided while every
individual call looked correct.

### 4.4 Fail-closed, stated precisely

| situation | behaviour | why |
|---|---|---|
| candidate inside this host's window, no network | **writes** | a reserved region is provably out of everyone else's reach — the brief's second permitted branch |
| window spent, local ledger present, ref reachable | **extends locally, then publishes** | one publish per 64 ids; the publish reconciles any overlap before use |
| window spent, ref unreachable, local ledger present | **extends and writes locally, publish refused** | it can still prove its window; it must not claim a number outside it |
| window spent, no local ledger, ledger on the remote | **REFUSES** | it cannot see what is free |
| no ledger anywhere, no origin ref | **writes** | fixture/scratch tree, single machine by construction |

### 4.5 Reversibility

* The allocation code is one contiguous block in `journal/tools/journal.py` (the `ID ALLOCATION,
  2026-09-17` section) plus the `claim` subcommand and one call site in `cmd_append`. Reverting
  the commit restores the old behaviour exactly.
* `journal/alloc/bands.tsv` is advisory data, not log data: deleting it makes machines re-claim
  from scratch, which is safe (higher numbers, never lower) and costs only skipped ids.
* **No entry id was renumbered, no entry file was touched**, so nothing here must be undone in
  the record. The one exception is the ref restore in §5.4.

---

## 5. The incident: an append reverted `origin/master`, and the fix is a separation

This is the most important part of this document. It is recorded with hashes because the failure
is silent and the shape of it is what generalises.

### 5.1 What happened

While recording the lesson for the allocator change, `journal.py append` was run. The version of
`append` at that moment claimed a window and **pushed** it inline. It pushed:

```
79efb088c78ff5a14541227a2418f44ff884e473   journal(alloc): ZABZ-YOGA reserves lessons<=1990
  parent: 53cf517c61ce83f1426e096458e9e5d338cf8770   (the correct, converged tip)
  diff against that parent: 2425 files changed, 1176 remaining -> 1249 PATHS DELETED
  journal/entries/**/*.md in the committed tree: 0    (all 1728 journal entries gone)
  exit code: 0
```

Every stream's shared branch was pointing at a pre-convergence tree, and nothing in the output
said so.

### 5.2 Mechanism — a tree and a parent read from two different names

```
622876e tree : 36ec672cde068fc005ca13c42e9b095b0805616f   <- what the claim tree was BUILT from
79efb088 tree: db4298514a11547d6c3aac7f88c9cff19b44696a   <- what was COMMITTED
53cf517 tree : 5684ffdb0f294fa2737bb9716844d144581c030c   <- what the parent actually holds
```

The parent **commit** was resolved from the just-fetched remote tip (correct). The parent **tree**
was resolved from the mutable local name `refs/remotes/origin/master`, which in that worktree was
`622876e` — **13 commits behind**, pre-dating the whole 107 convergence, because this worktree had
never been fast-forwarded. A commit whose tree is not its parent's tree **is** a mass deletion.
The two reads had to come from one immutable hash, and they did not.

### 5.3 The generalisation, which is the actual lesson

This is the same class as five previously-measured failures: five contested ids git called clean
because it compared the working tree against an unchanged upstream path; 23 entries that existed
in no commit because an untracked file is not a committed one; `--dump-config` returning 0 locally
and 1 over ssh; and the 107 convergence's own near-miss, where a deletion upstream had never
touched would have been honoured silently.

**The rule: prefer an immutable identifier — a commit hash, a blob id, a sha256 — over a mutable
name, and when the two must be mixed, resolve the whole unit from the same reading.**

### 5.4 The restore (authorised explicitly, for that exact command on that exact ref)

```
$ git push origin 53cf517:refs/heads/master
 ! [rejected]  53cf517 -> master (non-fast-forward)                        <- a plain push refuses

$ git push --force-with-lease=refs/heads/master:79efb088c78ff5a14541227a2418f44ff884e473 \
      origin 53cf517:refs/heads/master
 + 79efb08...53cf517 53cf517 -> master (forced update)                     exit=0

$ git ls-remote origin master
 53cf517c61ce83f1426e096458e9e5d338cf8770   refs/heads/master
```

`--force-with-lease` naming the exact old value is what makes a rewind safe: it would have
refused if anything else had moved the ref. Nothing was destroyed — no commit was deleted, and
the bad commit is kept as local-only evidence at `broken/alloc-claim-20260917`.

**Content-verified, not hash-verified**, because a matching hash I typed proves only that I typed
it:

```
journal/entries/**/*.md on the restored 53cf517 : 1728   <- the figure the 107 convergence recorded
3568d39 (107 merge) ancestor of 53cf517         : True
cf61988 (107 doc)   ancestor of 53cf517         : True
checked out into a throwaway worktree:
  journal.py check -> -- 0 error(s), 85 warning(s), 80 info
```

### 5.5 The fix, and it is a separation rather than a patch

**`append` writes locally and is incapable of moving any ref. Publishing is separate and
explicit.** Measured, and asserted by `verify-alloc.py` check C:

```
remote master before three appends: 5755d581f724
remote master after  three appends: 5755d581f724
local refs before == local refs after: True
```

A claim that cannot confirm the ref is current **refuses** rather than building on it, and the
local ledger is written only on a successful publish, so a failed publish cannot leave a row
claiming numbers no other machine can see.

### 5.6 Three plumbing failures that were each silent, and one more

Recorded because each produced a *working-looking* result that could have shipped:

1. **`git mktree` refuses any entry whose name contains a slash** — `fatal: path
   journal/alloc/bands.tsv? contains slash`. A nested path needs one call per level.
2. **A temporary index silently drops the new file.** `GIT_INDEX_FILE` + `read-tree` +
   `update-index --index-info` + `write-tree`: `update-index` printed `Ignoring path
   journal/alloc/bands.tsv` and `write-tree` returned the **parent tree unchanged**. The claim
   "succeeded", the commit landed, and the file was not in it: exit 0, nothing written, the worst
   possible shape for a safety mechanism. Cause: `update-index` refuses a path whose intermediate
   directory does not exist in the worktree.
3. **`git_max()` returns `(number, rev)`, and the tuple went straight into `max()`.** The
   `TypeError` was raised inside a guarded call, so `reserved_through` was computed and then
   silently ignored: both machines reserved `L2..L65` and collided while every individual call
   looked correct.
4. **Publishing only the local file replaced the shared ledger.** Each machine's local ledger holds
   only its own row — the rows the *append* path saw came from the ref, not the file — so the
   second machine's publish overwrote the first machine's reservation with a single row that
   re-used its numbers. The shared ledger is now built as the union, with an overlap moved up.

### 5.7 Dependency this had to fix on the way

`_git_repo()` assumed the journal's parent was the repository. For a `journal/` directory inside a
clone that is false, so `hash-object` returned an **empty blob** and the claim died as
`tree-build-failed` with nothing to explain it. It now asks git for the enclosing repository
(`rev-parse --show-toplevel`) and keeps the old answer only as a fallback.

---

## 6. The proof

`journal/tools/verify-alloc.py` — the permanent, repeatable form. **21 checks, 0 failures.** The
baseline rule is read out of git (`622876e`) and never retyped, so the test carries a demonstrated
failure mode.

### 6.1 Run A — the CURRENT rule collides

```
baseline rule taken from git 622876e (never retyped)
  m1 rc=0 minted ['L2']
  m2 rc=0 minted ['L2']
PASS A. the PREVIOUS rule mints the same id on both machines
```

Two machines, one committed base, neither seeing the other's uncommitted work, each writing `L2`
with a different body.

### 6.2 Run B — the new rule does not

```
-- new rule, neither machine has a window --
  m1 rc=4 minted []          PASS B. no id is minted by both
  m2 rc=4 minted []          PASS B. the machine refuses rather than minting blind
-- new rule, each machine claims first (the real workflow) --
  m1 rc=0 minted ['L2']
  m2 rc=0 minted ['L66']
PASS B. no id is minted by both
PASS B. the second machine landed ABOVE the first window
```

Both halves matter: "it refused" alone would also be true of a tool that had simply stopped
working, so the test also proves the workflow that is supposed to work still does.

### 6.3 The reader-facing half

The ledger at `journal/alloc/bands.tsv` names the host and the moment for every window, so
"which machine minted this, and in what order" is answered from the repo with no central
allocator: a window's host is the minter of every id inside it.

---

## 7. Fail-closed, measured

```
window end 4; origin refs now ''
wrote offline, inside its window: ['L3', 'L4']
refused rc=4: REFUSING to write L5: no origin ref and L5 is outside this host's reserved
              window; the local ledger covers L2..L4.
PASS C. it REFUSES at the edge of that window
PASS C. the refusal exits non-zero
PASS C. the refusal wrote NO entry file
recovery with a fresh origin: claim rc=0, append rc=0, ['L2','L3','L4'] -> ['L2','L3','L4','L5']
PASS E. it recovers and mints again once origin is back
```

The machine was cut off completely — origin deleted **and** its remote-tracking refs removed — so
"offline" means genuinely nothing left to read. It wrote inside its own window, stopped at the
edge with nothing written, and resumed after a fresh origin appeared. **A rule that could wedge a
machine forever would be an outage, not a safety property**, which is why recovery is its own
check.

---

## 8. The two smaller defects

### 8.1 Every mutating command left `journal/.lock` behind — two causes, both measured

The brief named `questions` and `import-legacy`. MEASURED (`_scratch/108/lock-repro.py`, each
command against a throwaway tree): **every** mutating command leaked it — `questions --offline`,
`questions --from-json`, `import-legacy` (dry and `--apply`), `index`, `state`, `append --dry-run`,
`append`. The file always contained the process's **own** token and its pid was always dead.

```
questions --offline     rc=0  lock=True  holder=DEAD  'questions 27248@zabz-yoga:1789663807'
import-legacy --apply   rc=0  lock=True  holder=DEAD  'import-legacy 18588@zabz-yoga:1789663808'
index                   rc=0  lock=True  holder=DEAD  'index 12776@zabz-yoga:1789663809'
append                  rc=0  lock=True  holder=DEAD  'append 1192@zabz-yoga:1789663810'
```

**Cause 1 — the ownership test could not read its own lock file.** `release_lock` decided
ownership with `token in _rl(lock)`. On Windows `msvcrt.locking` makes the locked byte range
unreadable from **any other handle**, so `_rl` raised `PermissionError`, the `except OSError:
held = ""` swallowed it, `token in ""` was False for every command, and the unlink never ran.

**Cause 2 — the unlink came before the close.** With cause 1 fixed the file *still* leaked:

```
unlink while holding  : FAILED 13 [WinError 32]
unlock, then unlink   : FAILED 13 [WinError 32]     <-- still fails after the byte lock is gone
unlock, close, unlink : OK, file exists: False
```

`os.open` takes no `FILE_SHARE_DELETE`, so the **handle itself** blocks the delete, not the byte
range. The order is now: prove ownership → drop the OS lock → close the fd → unlink. All eleven
repro rows read `lock=False`, including the read paths that never took it.

### 8.2 `note_git_ceiling()` was dead code

`allocation_ceiling()` trusted `stamp.json:git_ceiling`, and its only writer
`note_git_ceiling()` was **called from nowhere**, so the field was `{}` on every machine and the
ceiling was always just `max_number()`. On 2026-09-17 a human had to raise the field by hand to
255 for the 107 renumber to reproduce the right numbers.

**Wired, not removed**, because the field's stated purpose — "a ceiling measured from git refs, so
reads do not need a subprocess" — is real and the measurement was already being taken and thrown
away. `git_max()` now records what it measured, and only when it measured something (`if nums:`,
so an empty read cannot lower a ceiling to zero). It never lowers a value and never raises an id
past what the same run already saw.

---

## 9. The live tree, and what this session did not do

**The live journal on this laptop has no published reservation of its own from this change.** Its
next ids were `H485, L1927, P252, D259, W204` before and `H484..., L1928...` only because the
lesson in §5.3 was written (an entry, not a claim). `journal.py check` is `0 error(s), 79
warning(s), 80 info`.

**Note for whoever picks this up:** a reservation for `ZABZ-YOGA` covering `lessons` up to
`L1990` **is** published on `origin/master`, created by the inline-push version during the
incident. It is correct and harmless — it is a window no one else may use — but it was created by
a version of the tool that no longer exists, and its commit is the one that was reverted off
`refs/heads/master`. It is still visible because the reverted commit's ledger is reachable; the
next successful publish will carry it forward from the current tip.

**The workflow from here, once per machine per window:**

```
journal.py claim lessons     # explicit; reserves and PUBLISHES; refuses if it cannot confirm the ref
journal.py append ...        # local only; never touches a ref
```

`claim` with no kind covers all five. `next-id KIND --plan` reports whether a write would be
allowed without performing one.

---

## 10. Records, without redesigning

### 10.1 `check` cannot see a cross-tree collision — single-tree by contract

`check` builds its world from `scan_tree()`, which is `load_entries()` plus `legacy_candidates()`.
Nothing asks what a **ref** holds, so an id that differs on `origin/master` is not merely
unreported: it is invisible. MEASURED 2026-09-17: `check` reported **0 errors** while all 18
collisions were live.

**The cheap fix, when someone builds it:** the local side is one subprocess —
`git hash-object --stdin-paths` over the entry paths; the upstream side is one subprocess —
`git ls-tree -r origin/master journal/entries`. Same path with a different blob id **is** the
collision, and a path on only one side is the missing/absent set.

**The right home is `idguard`, not `check`.** `check` is on the read path — every reader and the
gate call it — and giving it a subprocess and a ref would make the always-read surface slower and
dependent on a remote-tracking ref. `idguard` is the only instrument that already knows about
upstream and already feeds the sync keeper's `id_collisions` field; it needs its **input** changed.
**Recorded, not built.**

### 10.2 `idguard` undercounts because it reads a generated cache

MEASURED: `idguard` reported **9** collisions where the content comparison finds **10**, because
the other machine committed `D254`, `H474`, `L1914` and `P247` **without regenerating the
committed cache**:

```
id      in origin's COMMITTED entries.tsv   entry committed in origin/master
D254    False                              True
H474    False                              True
L1914   False                              True
P247    False                              True
```

**A gate is only as fresh as a generated file a writer has to remember to rebuild.** **Recorded,
not built.**

### 10.3 `append --alias-of` is accepted and ignored, and must stay ignored

It is declared and never read by `cmd_append`, which hardcodes `"alias_of": ""`. It must **not** be
"fixed" by writing it: `parse_entry` treats a live entry that declares `alias_of` as a problem, so
writing it would turn every renumbered entry into a `check` error. **Neither done here.**

---

## 11. Files, commands and what could not be verified

**Changed**

```
journal/tools/journal.py        the allocation block, cmd_claim, cmd_append's mint,
                                reserve_locally/publish_reservation, next_writable,
                                _held_lock_text/release_lock, note_git_ceiling wiring,
                                _git_repo walk-up, binary plumbing helpers
journal/tools/verify-alloc.py   new, 21 checks: the proof in §6 and §7
docs/mesh/108-id-allocation.md  this file
```

**Gates**

```
journal.py selftest     239 of 240 before  ->  240 of 240 after
                        (the one failure was `no lock file was left behind`)
journal.py check        0 error(s), 79 warning(s), 80 info   before AND after
verify-alloc.py         21 check(s), 0 failure(s)
append vs remote ref    identical before and after three appends
```

**NOT VERIFIED, stated as refusals:**

* **Not run on any other node.** `ZABZ-TECH`, `secratary`, `zabz-tech-linux` and the VPS have not
  executed this code; the two-machine behaviour is proved by simulation on this one. The mechanism
  is host-name-independent (it reads `host_tag()`), but that is an argument, not a measurement.
* **A genuinely rejected `git push` under two simultaneous publishes was not forced.** The retry
  loop is written to re-read the ref and rebuild, and it *was* exercised once for real — the
  rewind in §5.4 hit a rejection path — but not by two machines publishing at the same instant.
* **The publish path has never run against the live `origin/master` from this version of the
  tool.** The reserve → extend → publish cycle is measured only against throwaway bare origins.
* **`idguard` and `check` were not changed**, so §10.1 and §10.2 still stand.

