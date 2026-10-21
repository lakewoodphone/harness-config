# SPEC v3 — the journal as a store for parallel agents

**Status:** stage A shipped (`e4f015308`, 2026-10-21). Stages B–E specified, not built.
**Written from measurement, not opinion.** Every number below was read on ZABZ-YOGA on
2026-10-21 between 02:30 and 03:40 UTC, with six live sessions on the same tree.

---

## 1. What was wrong (the P1)

Every agent reported "the journal is frozen". Nothing was corrupt and no id was lost. A write
did work that was not needed, at a cost that multiplied by the number of sessions doing it.

| step inside ONE append | cap in code | measured |
|---|---|---|
| `git fetch --quiet --all` | 25 s | never completed (repo 4,854 MB, 129 packfiles) |
| `git grep -E '^## L[0-9]+ '` over the working tree | 60 s | **332.6 s** — killed at cap, zero rows returned |
| `git grep … HEAD` | 60 s | killed at cap, zero rows returned |
| `git for-each-ref` + one `git grep` per ref, 25 refs | 60 s each | **15.1 s each → 377 s** |

≈ **9 minutes per append**, and six sessions were doing it at once. Two amplifiers:

* `subprocess.run(timeout=)` kills the child, not the tree. The 25 s cap killed `git.exe` and
  left the `ssh` and `git index-pack` beneath it running — **7 live `git.exe` and 129 packs**.
* the read fallback. `ensure_cache()` gave up the instant the lock file existed, and
  `catalog()` fell through to `load_entries()` — 4,762 markdown files, 15.4 s idle and
  **774 s measured for one `status`** while the appends were running. Readers and writers
  amplified each other, which is why it felt like everything at once.

**The ids were never in the file contents.** An entry's id is its filename
(`entries/lessons/L1776.md`), which `max_number()` already relied on locally. `ls-tree` answers
the same question in **0.20 s per ref** — 4.74 s for 25 refs, 75× cheaper than grep.

## 2. Stage A — shipped

| path | before | after |
|---|---|---|
| append, cold process | ~522 s | **4.3 s** |
| three concurrent appends | 16+ min, none finished | **26.2 s wall, 3 distinct ids, exit 0** |
| `status` | 774 s | **1.15 s** |
| `newest` / `show` / `list` / `search` | 15 s+ | **0.33–0.36 s** |
| `check` | 70 s | 16.4 s, 0 errors |
| `reserved_through_others` | 6.49 s | 0.67 s |

What changed, and the invariant behind each:

1. **A write never runs a repo-scale grep.** `git_max` reads filenames from a bounded tree
   listing per ref, memoised on a fingerprint of every ref (`stamp.json:remote_ids`). No ref
   moved → 0.13 s, no scan.
2. **A write never waits for the network.** `spawn_ceiling_refresh()` starts a detached
   `journal.py refresh` and returns. The refresh fetches the **coordination ref only** —
   measured **2.8 s, exit 0**, against `--all` which never finished in 25 s or 300 s — and is
   single-flight and rate-limited. It sleeps 20 s first so it does not compete with the write
   that spawned it (measured: without the delay a 15 s append took 30 s).
3. **Kill the tree, not the child** (`_kill_tree`: `taskkill /T /F`, `killpg` elsewhere).
4. **One row, not a rebuild.** `append_index_entry` inserts one `entries` row, one FTS row and
   one TSV line, then recomputes the tree fingerprint (1.4 s). Verified equal to a full
   rebuild: **4,759 = 4,759 rows, per-kind identical, 0 body-text mismatches.** Every
   precondition is checked and any doubt falls back to `rebuild_cache()`.
5. **Reads wait 3 s, then answer from SQLite.** The critical section is a file write, so the
   lock clears in milliseconds; the fallback tier is `index/journal.db` (one query), not a
   file walk, and the page says `CACHE stale` rather than claiming freshness.

**Latent bug found by the fix:** `rebuild_cache()` rebuilt `stamp.json` from a fresh dict and
carried forward only the keys it knew. One of the ones it silently deleted was
`ledger_ceiling` — the highest window **any other host** has claimed, which
`allocation_ceiling()` uses as a term. Every append was erasing other hosts' claims from the id
ceiling. The 2026-10-14 cross-host fix was being undone by the next write.

## 3. Why the repo itself is now the bottleneck

| thing | size |
|---|---|
| the record (`journal/entries/`, 4,762 files) | **13.2 MB** |
| the derived index (`journal.db` + `entries.tsv`) | 28.2 MB, rewritten per write |
| `.git` | **4,854 MB**, 129 packfiles |
| distinct blobs under `journal/index` in history | **3,085 → 15.2 GB uncompressed** |

The ten largest objects in the entire repository are all `journal/index/journal.db` (33.7 MB
each). 751 commits touch it. Write rate is **117 entries/24 h, 19 in one hour**. So the
journal — a 13 MB record — is why a 4.85 GB repository has 129 packs, why `fetch` cannot
finish, and therefore why the cross-machine id ceiling had been silently stale (`git_ceiling`
lessons 10,177 vs local 11,968).

`journal/index/journal.db` and `entries.tsv` are now untracked (the ignore rule already
existed in `journal/.gitignore`; the files were tracked, so it never applied). New writes no
longer grow history. The existing history is untouched — see stage D.

## 4. Stages B–E

### B. Allocate ids from a counter, not from git refs — *recommended next*

Today an append can need: local `alloc/bands.tsv`, up to 25 `cat-file` reads of other refs'
`bands.tsv`, and a fetch that has not been completing. The authority is a single SQLite writer;
an id counter belongs there.

* `next-id` asks the authority for a block (`UPDATE counters SET n = n + 64 RETURNING n`), one
  round trip, atomic, no git, no ref scan, no fetch.
* Unreachable → reserve locally and do not publish (already the behaviour).
* Removes: `bands.tsv` replication, the 25-ref ledger read, the whole fetch dependency.
* Cost: ~0.1 s per append and one new failure mode to handle (authority down), which the
  reservation layer already models as "reserve locally, unpublished".
* Risk: medium. The band logic is the collision guarantee and it has 70-collision history.

### C. Move the journal out of the code repository — *the structural fix*

The journal writes 117 times a day; the code a few times a week. Sharing one object store means
every journal commit is packed against 4.85 GB of code history, so `fetch`, `gc` and `clone`
are all dominated by history the journal does not need.

* A separate `journal.git` holding only `entries/`, `alloc/` and `tools/` would be ~15 MB; a
  fetch would be sub-second, which is what makes stage B unnecessary rather than urgent.
* Keeps the record in git (append-only, diffable, one file per entry) — no loss of provenance.
* Cost: a new remote, a sync path, and every machine's `journal.py` `--root` pointing at the
  new checkout. Risk: medium-high; touches every host and every script that assumes
  `~/code/harness-config/journal`.

### D. Shrink the existing history — *the owner's call, destructive*

`git filter-repo --path journal/index --invert-paths` on a fresh clone would drop ~15 GB of
blobs. It rewrites every commit hash, so every machine must re-clone and every open branch is
invalidated. **Not done, and not to be done without an explicit yes.** The alternative is to
leave it: history costs nothing until someone clones or fetches, and stages B and C make those
rare.

### E. Small, cheap, worth doing when touched

* **`--batch`**: one `journal.py append --batch file.jsonl` doing N entries under one lock with
  one index update. A session that writes four entries pays the fixed cost once.
* **`recent.tsv`**: a tail of the last ~200 entries maintained incrementally so `newest`,
  `status` and `open pain` never read the whole index.
* **Lock sharding by kind**: the mint only needs a per-kind band counter; two appends of
  different kinds need not serialise at all. Small win now that the critical section is a file
  write (measured lock hold: milliseconds), so this is last.

### Not worth doing

* Replacing files with a pure database as the record. One file per entry is why `grep`, `git
  log -p`, code review and a corrupted-index rebuild all work. Keep the record as files.
* A daemon holding the index in memory. It adds a component to keep alive on six hosts to save
  1.4 s; the incremental path already removed the 23 s.

## 5. Rules this file exists to enforce

1. **A write path may not run a repo-scale grep.** If a number needs refs, read the tree, not
   the bytes.
2. **A write path may not wait for the network.** Move it to a detached child and record when it
   last succeeded (`stamp.json:fetched_at`, `fetch_rc`).
3. **A derived file is never tracked.** If it is rebuilt from the record, it does not belong in
   history; a 28 MB rewrite per write is a repo-sized defect, not a storage annoyance.
4. **One writer per fact.** `stamp.json` had two writers and one of them deleted the other's
   keys; a rebuild must carry forward every field it does not own.
5. **Every claim about speed carries a number and how it was read.** The numbers above are
   `Stopwatch` around the real command, or `cProfile` of it, on this tree.
