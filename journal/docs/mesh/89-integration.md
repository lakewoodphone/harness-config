# 89 — Verification of the `harness-config` fork integration

**Who did what.** Stream **O6** executed the integration (merge commits `c4b1b57` and the two
`docs/mesh/87` commits after it). This file is the **independent verification**, written by the
verifier, which did **not** perform the merge, did not resolve any conflict, did not commit, did not
push and did not write to the repository at all. Every number below was produced by a command in
this file, run against **git objects** — never against the working tree — so a live writer on the
laptop could not contaminate a reading.

* Verified 2026-09-17 04:11–04:25 UTC, from `ZABZ-YOGA` (`C:\Users\ezabz\code\harness-config`) and
  on the authority (`secratary`, `/home/zabz/harness-config`).
* `origin` is the bare repo `secratary-ts:/home/zabz/harness-config.git`. **Verified, not assumed:**
  `remote -v` on the authority resolves to `/home/zabz/harness-config.git`, so the authority's
  `pull --ff-only` is a real test of a real remote and not a repository fetching from itself.
* `origin/master` moved **three times while this verification ran** — `c4b1b57` (the merge) →
  `756affe` → `7708e2d`. Verdict 1 was re-derived at `7708e2d`; counts are stable at 1,576.

---

## 1. What landed, and the shape of the collision

```
$ git cat-file -p origin/master | head -4      # at c4b1b57, the merge commit
tree d8af3bb8eb86eb45c5939703de17857b7212ae67
parent d09163a8dcca9ccd32a48a457983e6382261c517
parent c05773873dbb2b6c78675bf7250cbbdcfec6eb16
author secratary <secratary@local> 1789618288 +0000
```

Both lines branched from the **same** merge-base, `2ce3ad9`, so both allocated the same next ids
from the same view. The collision was not the 3 ids the brief guessed at — it was **13**, and
**every one of them was the dangerous class**:

```
$ git diff --name-only --diff-filter=A 2ce3ad9 c057738   # 20 paths, 13 under journal/entries/
$ git diff --name-only --diff-filter=A 2ce3ad9 d09163a   # 41 paths, all under journal/entries/
$ <intersection>                                          # 13
journal/entries/{decisions/D234,D235,D236,handoff/H424,H425,
                 lessons/L1832,L1833,L1834,L1835,L1836,L1837,pain/P223,P224}.md
```

| split | count |
|---|---|
| add/add conflicts at the same path | **13** |
| of those, **byte-identical** on both sides (the safe case) | **0** |
| of those, **differing content, same id** (the dangerous case) | **13** |

Same id, different entry — e.g. `D234` was "Supplier orders get a ledger row" (2026-09-14,
SECRATARY) on the landed line and "Shlock's canonical design sources committed to git"
(2026-09-16, zabz-yoga) on the authority line. **The resolution used was the one `87-harness-fork.md`
§3 prescribes:** the landed line keeps the id at the path, and the authority's thirteen texts were
carried in through `journal.py append` — the only sanctioned writer — which allocated fresh ids.
No text was dropped and no text was hand-merged.

Also present and verified: **no marker line reached a committed file.**

```
$ git grep -e '^<<<<<<<' origin/master | wc -l   →  0
$ git grep -e '^>>>>>>>' origin/master | wc -l   →  0
```

---

## 2. Entry counts, before and after, accounted for

| tree | rev | entries | arithmetic |
|---|---|---|---|
| merge-base | `2ce3ad9` | **1,541** | the shared starting point |
| authority line | `c057738` | **1,554** | 1,541 + 13 new entry files |
| landed line | `d09163a` | **1,563** | 1,541 + 41 carried in − 19 collapsed by `dedupe` |
| laptop working tree (live, uncommitted) | HEAD `c057738` | 1,554 tracked + **18 untracked** = 1,572 | at 04:25Z — and *moving*: 17 untracked at 04:23Z, 18 at 04:25Z, a stream is writing here right now |
| **merged `origin/master`** | **`7708e2d`** | **1,576** | **1,563 + 13** — the thirteen texts arrived under fresh ids and **nothing was collapsed**, because no two of them share an identity |
| authority, after `pull --ff-only` | `7708e2d` | **1,576** | `journal.py stats` agrees |

Every count is accounted for by construction, not by plausibility.

---

## 3. VERDICT 1 — the history: **clean**. Both bodies of work survive.

### 3.1 The thirteen texts, by text, under the ids they now hold

Matched with the journal's **own** `norm_body` + kind (not a re-implementation, not an id count):

```
D234 → D241      D235 → D242      D236 → D243
H424 → H433      H425 → H434
L1832 → L1848    L1833 → L1849    L1834 → L1850
L1835 → L1851    L1836 → L1852    L1837 → L1853
P223 → P229      P224 → P230
      => master originals intact: 13/13     local texts present: 13/13
```

Sample of the raw per-entry evidence (kind, date, host, status, and byte-level body equality):

```
H424.md  local id=H424 -> final id=H433
   landed: kind=handoff date=2026-09-17 03:49 UTC host=ZABZ-YOGA status=open body-identical=True
   meta={'tags': 'mesh,o5,handoff', 'refs': '', 'alias_of': '', 'legacy_id': ''}
P224.md  local id=P224 -> final id=P230   body-identical=True
```

and master's originals were confirmed **byte-identical to `d09163a`'s blobs**, 13/13:

```
D234 master's D234 byte-identical to d09163a: True      (… and 12 more, all True)
```

A **second, independent** instrument (`verify-89.py`, identity-from-git-objects) reported the same
mapping from the other direction — `lost.master_before = []`, `lost.local = []`, i.e. **not one
entry of either side is missing by the tool's own identity function.**

### 3.2 Structure: no id means two things, and no text has two ids

```
final_dup_id    = {}      # every id maps to exactly one entry
final_dup_ident = {}      # no two ids hold the same text
```

The structural result was taken at the merge commit `c4b1b57` and carries to the tip, proven rather
than assumed: the two later commits touch **only** `docs/mesh/87-harness-fork.md`, and the
`journal/entries` tree object is **identical** at both revisions
(`d35c20f94cd7e2cb3bc1bd0f711e101786e37b41`).

`journal.py check` on the merged tree, run against an extraction of the rev's objects:

```
$ python journal/tools/journal.py --root <export>/journal check
-- 0 error(s), 60 warning(s), 80 info
```

and on the authority's own pulled checkout, which is the same tree as deployed:

```
-- 0 error(s), 60 warning(s), 80 info        # 1,576 entries
```

### 3.3 The warning count went 59 → 60, and the reason is benign

The brief flagged a jump in warnings as a signal. The full warning **set** was diffed, not just
counted. Exactly **one** warning is new, and it is **inherited from the authority's own text**, not
damage from the merge:

```
NEW warnings (+1):
  WARN  dangling ref personal-secretary-mvp@47c3db250 (cited by D243) — nothing in entries/ has that id
GONE warnings (-0):
```

`c057738`'s `D236` already carried `refs=personal-secretary-mvp@47c3db250` (the string appears twice
in its body) — the journal's checker reads a `repo@sha` citation as an id. It became *visible* only
because the text is now in the tree at `D243`. Nothing about the merge produced it.

### 3.4 The thirteen non-journal files of `c057738`: all present

Blob-hash comparison (`git rev-parse <rev>:<path>`), not a glance:

| path | tip vs `c057738` |
|---|---|
| `docs/mesh/71-mesh-program.md` | identical (`f99b12e7…`) |
| `docs/mesh/86-authority.md` | identical (`21184335…`) |
| `docs/mesh/88-elastic-build.md` | identical (`54450860…`) |
| `packages/mesh-broker/deploy/authority-swap-fix.py` | identical (`a8b2ff7f…`) |
| `packages/mesh-broker/deploy/authority-swap-probe.py` | identical (`1351cb31…`) |
| `packages/mesh-broker/deploy/install-authority.sh` | identical (`89a9ced8…`) |
| `packages/mesh-broker/deploy/verify-deploy.sh` | identical (`30d82e24…`) |
| `packages/mesh-broker/deploy/mesh-broker.service` | identical |
| `packages/mesh-broker/deploy/secratary-smoke.sh` | identical |
| `packages/mesh-broker/lib/broker.js` | identical |
| `packages/mesh-broker/lib/scoring.js` | identical |
| `packages/mesh-broker/test/scoring.test.mjs` | identical |
| `docs/mesh/87-harness-fork.md` | **differs — expected and benign** |

Seven of those were **absent** from `d09163a` and would have been silently dropped had the merge not
run; six were modified on the authority's line while `master` had no edit of its own, so taking
`c057738`'s side lost nothing. This was the finding that made the difference between a merge and a
loss, and it was reported to O6 before the merge was executed.

`docs/mesh/87-harness-fork.md` is the one file that differs, because **it is the stream's own doc and
O6 updated it to record what happened**:

```
$ git diff --stat c057738 origin/master -- docs/mesh/87-harness-fork.md
 docs/mesh/87-harness-fork.md | 227 +++++++++++++++++++++++++++++++++--------
 1 file changed, 186 insertions(+), 41 deletions(-)
```

Its section list at the tip contains every section `c057738` had (`## 0` … `## 6`) **plus** the new
`### 4.7` and `## 7` with its subsections (`7.1`–`7.5`). Supersession by the document's owner, not
loss.

### 3.5 Ancestry — the thing the merge had to achieve

```
$ git merge-base --is-ancestor c057738 origin/master   → exit 0   (TRUE)
$ git merge-base --is-ancestor d09163a origin/master   → exit 0   (TRUE)
$ git rev-list --left-right --count c057738...origin/master
     → 0   2   at the merge commit c4b1b57
     → 0   4   at the tip 7708e2d, 04:25Z — the two later commits are the stream's own docs/mesh/87 records
```

Both lines are ancestors of the merged tip. **No history was rewritten and nothing was force-pushed:**
`c057738` still exists under `refs/heads/stream-c057738` and as a parent of the merge, and
`d09163a` remains reachable under `refs/heads/reconcile/secratary-20260917` and as the other parent.

---

## 4. VERDICT 2 — the working tree of the laptop: **refused, as predicted, and not a defect**

Run separately from Verdict 1, so that a working-tree block can never be read as a broken history:

```
$ git pull --ff-only                    # on ZABZ-YOGA, HEAD c057738
Updating c057738..7708e2d
error: Your local changes to the following files would be overwritten by merge:
	docs/mesh/87-harness-fork.md
	journal/index/entries.tsv
Please commit your changes or stash them before you merge.
error: The following untracked working tree files would be overwritten by merge:
	journal/entries/handoff/H433.md
	journal/entries/lessons/L1848.md
	journal/entries/lessons/L1849.md
	journal/entries/lessons/L1850.md
	journal/entries/lessons/L1851.md
	journal/entries/lessons/L1852.md
	journal/entries/pain/P229.md
	journal/entries/pain/P230.md
Please move or remove them before you merge.
Aborting

pull-exit=1
HEAD after: c05773873dbb2b6c78675bf7250cbbdcfec6eb16      # unchanged
```

**What this is.** A live writer on this machine (the owner's Waze MDM agent) allocated the **same
eight ids** after the carry-in had provably taken them — a concurrent writer, not a merge fault.
The second id block is not a bug in the carry: those ids were free when it ran, and the other stream
took its view before the push. It is the **third** instance of the same disease tonight, and it is
the rule §7.5 of `87-harness-fork.md` records.

**Two blockers the prediction did not include**, both of them live streams' uncommitted work, both
left untouched: the **tracked** files `docs/mesh/87-harness-fork.md` and `journal/index/entries.tsv`
(the latter is the generated cache, rewritten by any append). A further **ten** untracked entries
(`H435–H437`, `L1854–L1858`, `P231`, `W196`) are present in this tree but do **not** block, because
master does not hold those ids yet. The blocking set was measured twice, 20 minutes apart, and was
**exactly the same eight** both times while the total untracked count grew 17 → 18: the writer keeps
adding ids, and master keeps not having them.

**Consequence, stated plainly:** the laptop cannot fast-forward until those ids are re-filed through
`append` (which bumps on collision) and the two tracked files stop being dirty. Until then, **an
uncommitted entry in a diverged tree must be treated as an id already spent** — which is the rule,
not the exception. The 07:00 window owns that re-test.

**The authority, by contrast, fast-forwarded for real**, from a clean and already-aligned checkout:

```
$ git pull --ff-only                    # on secratary, HEAD 756affe
From /home/zabz/harness-config
   756affe..7708e2d  master     -> origin/master
Updating 756affe..7708e2d
Fast-forward
 docs/mesh/87-harness-fork.md | 29 +++++++++++++++++++++++++++++
 1 file changed, 29 insertions(+)
pull-exit=0
$ git rev-list --left-right --count HEAD...origin/master   →  0   0
$ find journal/entries -name '*.md' | wc -l                →  1576
$ python3 journal/tools/journal.py check | tail -1         →  -- 0 error(s), 60 warning(s), 80 info
$ grep -c "PRESERVE FIRST, THEN REPORT" scripts/autosync.sh →  1
$ git status --porcelain | wc -l                           →  0
```

The `*/15` autosync anti-refreeze fix is **live on the authority** — without it, the authority
diverges again the first time an agent commits there.

One earlier measurement of the authority, taken before the merge landed, for the record: it was
**already aligned at `d09163a`**, `0 0`, clean, with `check` at `0 errors, 59 warnings` and the
autosync fix present, i.e. §4.5 of `87-harness-fork.md` had already been executed
(`preserve/secratary-worktree-20260917` = `1642d1a` is on origin).

---

## 5. A defect in my own first instrument — recorded, because a false defect is the worse error

My first deep-check script reported `local text MISSING AT BYTE LEVEL` for 10 of the 13 texts and
`MASTER-SIDE CONTENT EXISTS — review` for 7 of the 13 non-journal files. **Both were my bugs, and
both would have been a fabricated crisis** — the single most expensive failure in this system's
history. They were caught because they contradicted a second, independent instrument, and the
contradiction was resolved by measurement rather than by choosing the more alarming reading:

1. `blob()` called `git rev-parse <rev>:<path>` with the failure ignored and stdout captured; git
   **echoes the unresolvable argument to stdout** and exits 128, so a path absent from a rev
   returned a truthy string. Seven files that are simply *new* in `c057738` were reported as
   master-side content that had been overwritten. Fixed by resolving on the **return code**.
2. The landing match required the **heading** to be equal as well as the body, but `append`
   regenerates the heading from the title, so 10 of 13 texts were reported missing. Fixed by
   matching on the journal's own `norm_body` + kind.

The corrected script is `deep-89b.py`; §3 above is its output. The rule this earns: **a content
match must be made with the tool's own identity function, never with a hand-rolled equality on a
field the writer is free to rewrite.**

---

## 6. What I could not verify, stated as such

* **The laptop's fast-forward is not verified.** It is refused, for the reason in §4. Re-testing it
  needs the concurrent writer's eight entries re-filed and the two tracked files clean.
* **The identity of the live writer is inferred, not proven.** I verified that eight untracked
  working-tree files collide with ids master holds. That the owner's Waze MDM agent wrote them is
  the parent stream's attribution; I did not inspect the writer's process.
* **`scripts/git-health-check.sh` (`*/30`) was not read** — carried forward from
  `87-harness-fork.md` §6, still unknown whether it touches this repository.
* **Why `identity_of` and `dedupe` disagreed on one entry** in the earlier stream (§4.6 of 87) is
  still not established. It did not recur here: the merged tip's duplicate-identity set is **empty**.
* **The 60 warnings are not diagnosed.** Counted and set-diffed, not explained; 59 of them predate
  this merge, and the authority's tree reported 691 warnings at the start of the night.
* **This file is not committed.** The verifier was stood down from touching git state, and the
  laptop cannot fast-forward anyway. `docs/mesh/89-integration.md` exists **uncommitted** in the
  working tree; committing it needs the §4 blockers cleared first, so the record currently lives on
  one disk in one dirty tree.

---

## 7. Write discipline observed

No commit, no merge, no conflict resolution, no `git add`, no push, no branch or ref creation, no
`reset`, no `clean`, no `worktree` registered. The only writes to the repository were
`git fetch` (remote-tracking refs only) and the single new file this document. Other streams'
uncommitted edits — `docs/mesh/87-harness-fork.md`, `journal/index/entries.tsv`,
`packages/plugin-remote-fanout/bin/mesh-run.mjs`, `scripts/mesh-e2e.ps1` and 18 untracked entries —
were left exactly as they were found; `docs/mesh/82..85` and `scripts/mesh-e2e.ps1` were not touched.
