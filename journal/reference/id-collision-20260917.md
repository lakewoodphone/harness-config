# The 2026-09-17 id collision: two machines, eighteen contested ids, and the tools that cannot see it

**Written by:** a delegated session on **ZABZ-YOGA**, 2026-09-17 16:0x–16:4xZ (12:0x–12:4x local).
**Why it is a reference document and not a log entry:** every id-bearing kind whose next number this machine would
mint is *contested right now* — measured, the other machine's untracked set already holds `H469`, `L1913`, `L1914`,
`D255`, `P247`, and its next mints are `H479`, `L1918`, `D256`, `P248`. Adding an entry would create another
collision while this document exists to remove them. Only `W` (wins) was uncontested, and that entry was written
separately. **When the collision below is resolved, this file should be promoted into the log.**

**Provenance convention.** **MEASURED** = run in this session, command and raw output given. **READ** = out of source.
**REFUSED** = asked for and not obtained.

---

## 1. The headline: the collision is not latent, it is live against `origin/master`

The brief described this as two machines' *untracked* entries colliding. That is true and it is **the smaller half**.
The larger half is that `origin/master` already carries a *different entry* under ten of the ids this laptop's worktree
holds, so the collision is not waiting for a merge — it is in the tree now.

MEASURED, `python journal/tools/idguard.py`, ZABZ-YOGA, 16:2xZ:

```
COLLISION  H464 on origin/master: host ZABZ-YOGA vs zabz-tech, heading '… LPT full build COMPLETE AND PUSHED …' vs '… Weitman laptop case recovered to origin/main …'
COLLISION  H465 on origin/master: host ZABZ-YOGA vs ZABZ-YOGA, heading '… 104: the linux node is enabled …' vs '… lpt-hub lineages unified + pushed …'
COLLISION  H466 on origin/master: host ZABZ-YOGA vs zabz-tech, heading '… Fishman case record pushed to lpt-hub origin …' vs '… Customer-data plane: the authority corpus was 46h wedged …'
COLLISION  L1906 on origin/master: host ZABZ-YOGA vs zabz-tech, heading '… A node capability must live in ONE module …' vs '… dialpad_sms_cache.created_at is the sync time …'
COLLISION  L1907 on origin/master: host ZABZ-YOGA vs ZABZ-YOGA, heading '… Junction-mounted packages resolve relative imports …' vs '… A mesh-synced repo can DIVERGE, not just lag …'
COLLISION  L1908 on origin/master: host ZABZ-YOGA vs zabz-tech, heading "… A child's MESH-HOST line is a claim …" vs '… A refresh job that fast-forwards to a stale ref …'
COLLISION  L1909 on origin/master: host ZABZ-YOGA vs zabz-tech, heading '… Correction to L1896 …' vs '… Two real customers are silently dropped by the sync-record reader …'
COLLISION  P242 on origin/master: host ZABZ-YOGA vs zabz-tech, heading '… A child that runs on zabz-tech-linux …' vs '… lpt-hub on ZABZ-TECH is a diverged branch …'
COLLISION  P244 on origin/master: host ZABZ-YOGA vs ZABZ-YOGA, heading '… zabz-tech boots a 0.1.0 provider plugin …' vs '… An inbound customer enquiry can sit unanswered …'
collisions: 9   divergences: 0
```

and this session's own content comparison — the same nine **plus `D254`** (§3 explains why `idguard` misses it):

```
SET A -- live collision: this worktree vs origin/master (10 ids)
  D254  laptop[ZABZ-YOGA] **D254 · Repair the junction from inside ssh; refuse the restart; leave 106 uncommitted.**
        origin[ZABZ-TECH] **D254 · 82XM00LMUS duplicate pair: the conforming case file wins …**
  H464  laptop[ZABZ-YOGA 14:52 UTC] LPT full build COMPLETE AND PUSHED      origin[zabz-tech 15:14 UTC] Weitman laptop case recovered
  H465  laptop[ZABZ-YOGA 15:04 UTC] 104: the linux node is enabled         origin[ZABZ-YOGA 15:21 UTC] lpt-hub lineages unified
  H466  laptop[ZABZ-YOGA 15:08 UTC] Fishman case record pushed             origin[zabz-tech 15:27 UTC] Customer-data plane
  L1906 laptop[ZABZ-YOGA] A node capability must live in ONE module        origin[zabz-tech] dialpad_sms_cache.created_at
  L1907 laptop[ZABZ-YOGA] Junction-mounted packages resolve …              origin[ZABZ-YOGA] A mesh-synced repo can DIVERGE
  L1908 laptop[ZABZ-YOGA] A child's MESH-HOST line is a claim              origin[zabz-tech] A refresh job that fast-forwards …
  L1909 laptop[ZABZ-YOGA] Correction to L1896                              origin[zabz-tech] Two real customers silently dropped
  P242  laptop[ZABZ-YOGA] A child on zabz-tech-linux dies MISS…            origin[zabz-tech] lpt-hub on ZABZ-TECH is diverged
  P244  laptop[ZABZ-YOGA] zabz-tech boots a 0.1.0 provider plugin          origin[ZABZ-YOGA] An inbound customer enquiry …
```

**Every pair is two genuinely different entries by two different sessions** — different topics, different moments,
different hosts. This is a real collision, not the encoding-only "false collision" `D200` describes (there, the
host/date/heading agreed and only the bytes differed; here nothing agrees).

## 2. The other half: eight more ids are contested by the other machine's *uncommitted* work

The other machine's checkout was snapshotted at **12:14:45 local** with its own `HEAD = 8875e22`, and its 21 untracked
entry files were preserved byte-for-byte (see §5). Eight of them wear ids this laptop's worktree also holds:

```
SET B -- latent collision: this worktree vs the other machine, both unpushed (8 ids)
  D252  laptop[ZABZ-YOGA] zabz-tech-linux v1 restored to true        desk[ZABZ-TECH] Video8/Hi8 players: recommend transfer
  D253  laptop[ZABZ-YOGA] Broker-driven placement is committed       desk[ZABZ-TECH] Owner declined the Sony 8mm player job
  H467  laptop[ZABZ-YOGA 15:28 UTC] H467 (placeholder body)          desk[ZABZ-TECH 15:32 UTC] Levi / Sony Video8-Hi8
  H468  laptop[ZABZ-YOGA 16:01 UTC] The desktop's junction is repaired from an ssh context
                                                                     desk[zabz-tech 15:34 UTC] Customer-data plane 2
  L1910 laptop[ZABZ-YOGA] Windows: copying a profile node_modules duplicates junctions
                                                                     desk[ZABZ-TECH] Ask what failed, not what the customer felt
  L1911 laptop[ZABZ-YOGA] The untrusted-mount-point discriminator is the reparse point's ACL OWNER
                                                                     desk[ZABZ-TECH] Windows file-lock primitives: four gotchas
  L1912 laptop[ZABZ-YOGA] A profile check is evidence only for the logon class that ran it
                                                                     desk[ZABZ-TECH] LPT customer texts are signed '- Daniel'
  P246  laptop[ZABZ-YOGA] zabz-tech cannot ssh to itself             desk[zabz-tech] A second Zabz session moved lpt-hub main under me
```

**Total: 18 contested ids** (10 live against `origin/master`, 8 latent against the other machine; `D254` moved from the
latent set to the live set *during this session*, when the other machine committed it at `e1c9aa2`).

**Why they collided, measured rather than argued.** Both machines minted from the same base: the committed maximum
before either wrote was `H466`-adjacent and `L1909`, so `next-id` on both machines returned `H467…`, `L1910…`, `D252…`,
`P246…` independently. This is `D191`'s recorded defect, re-observed: *"`next-id` reads the local index and local refs,
so it is collision-proof only after a successful push — offline or merely unpushed, two machines pick the same number
with confidence."*

## 3. What the tools actually do — all three measured, all three short of the brief's premise

The brief asked for `journal.py repair-ids --apply`, *"renumbers a colliding entry and records an alias, so no id ever
means two things"*. On this tree it cannot, and the reason is worth keeping.

| tool | what it does | MEASURED on this tree, 16:2xZ |
|---|---|---|
| `journal.py check` | validates `entries/` **within one tree** | `-- 0 error(s), 80 warning(s), 80 info`, exit 0 — **before and after** every step. It cannot see this class at all, exactly as `D191` warned |
| `journal.py repair-ids` | groups loaded entries by `(kind, id)` and renumbers the later one when two **files in one tree** declare the same marker id | `no id collides with different content — nothing to do` — report-only *and* `--apply`. There is one file per id, so a cross-tree collision has no in-tree duplicate for it to find |
| `idguard.py` | compares `journal/index/entries.tsv` **on disk** against the same file committed at upstream; collision = same id, different host/date/heading | `collisions: 9 divergences: 0` — the right instrument, and it already reports into the sync keeper's status |

Two further measurements, because both are defects rather than preferences:

1. **`repair-ids --apply` does not close a duplicate-id tree, even in the shape it exists for.** MEASURED on a synthetic
   tree (`_scratch/106-closing/jtest`, two files declaring marker `L1999`, different bodies):
   ```
   check  before : ERROR duplicate id L1999 in lessons names 2 different entries: L1999.md, L1999b.md   (exit 1)
   repair-ids --apply : L1999 (entries/lessons/L1999b.md) -> L2000  (kept L1999 at entries/lessons/L1999.md)
   files after   : L1999.md (marker L1999), L1999b.md (marker L1999), L2000.md (marker L2000)
   check  after  : ERROR duplicate id L1999 in lessons names 2 different entries: L1999.md, L1999b.md   (exit 1)
   ```
   It writes the renumbered copy and **leaves the offending file behind**, so the invariant it is named for does not
   hold. Fixing it (move the original to `archive/duplicates/` and keep the alias) is a small, contained change —
   **deliberately not made here**, because it does not address the actual collision and an unverified edit to the
   sanctioned writer is worse than a recorded defect.
2. **`idguard` cannot see an id whose entry was committed without regenerating the cache.** MEASURED:
   ```
   id                      in_origin_cache   entry_committed_in_origin
   D254                    0                 1
   H474                    0                 1
   L1914                   0                 1
   P247                    0                 1
   H466                    1                 1
   L1908                   1                 1
   ```
   The other machine's commit `e1c9aa2` added `D254.md`, `H474.md`, `L1914.md`, `P247.md` and did **not** rewrite
   `journal/index/entries.tsv`, so the committed cache is stale and every consumer of it — `idguard`, its `--floor`,
   and the sync keeper's `id_collisions` field — undercounts by those four. **The gate is only as fresh as a generated
   file a writer has to remember to rebuild.** Rebuilding here did not change the count (9 → 9), which is how the
   undercount was found: `D254` is in this machine's cache and missing from upstream's.

The conclusion the three tools force: **`check` is blind to this class by design, `repair-ids` has no verb for it, and
`idguard` sees at most what the two caches happen to contain.** The verb `D191` asked for on 2026-09-15 — *"give the
tool a reconcile verb so a duplicate can be renamed, the index rebuilt, and the move reported"* — is still not built,
and this session did not invent a fourth path around it.

## 4. The renumber map — in the one order that converges

`D191`'s convention, unchanged: **upstream keeps every contested id; the local lineage moves above the merged
high-water mark; both sides are staged before anything moves.** MEASURED merged high-water mark from the three sources
(this worktree, the other machine's 21 untracked files, `origin/master`): **`D=255, H=478, L=1917, P=247, W=202`.**

```
  D252   -> D256    contested with other machine     H464   -> H479    contested with origin/master
  D253   -> D257    contested with other machine     H465   -> H480    contested with origin/master
  D254   -> D258    contested with origin/master     H466   -> H481    contested with origin/master
  H467   -> H482    contested with other machine     L1906  -> L1918   contested with origin/master
  H468   -> H483    contested with other machine     L1907  -> L1919   contested with origin/master
  L1910  -> L1922   contested with other machine     L1908  -> L1920   contested with origin/master
  L1911  -> L1923   contested with other machine     L1909  -> L1921   contested with origin/master
  L1912  -> L1924   contested with other machine     P242   -> P248    contested with origin/master
  P246   -> P250    contested with other machine     P244   -> P249    contested with origin/master
```

Machine-readable at `_scratch/106-closing/collision-map.tsv` (id, set, both hosts, both headings, both dates).

**And the reason this map is not applied here, which is the load-bearing part.** A renumber on one side only **cannot
converge**. The other machine mints from its *own* local index; its next ids are `H479`, `L1918`, `D256`, `P248` — the
first four numbers this map hands out. Renumbering here would therefore trade 18 collisions for 4, freshly minted ones,
unless the renumber happens where the merge happens: **whichever side pushes second renumbers its own lineage *after*
the first side's ids are in its merged high-water mark, which raises its own `next-id` above them.** That ordering is
the fix; the numbering is only its bookkeeping.

## 5. What the merge will need — the exact procedure, with the traps named

1. **Stage both sides first (already done for the cases that exist).** This machine's side is on disk; `origin/master`'s
   side is recoverable with `git show origin/master:<path>`; the other machine's 21 untracked files are preserved at
   `_scratch/106-closing/desktop-untracked-entries.zip` (`sha256 520A0BD07E2446C4…`, 50,047 B), taken from its checkout
   at `8875e22` at 12:14:45 local, with a per-file sha256 list in `_scratch/106-closing/collect-desktop-entries.ps1`'s
   output. **Nothing may be resolved before both versions exist somewhere** — and today they do.
2. **Do not take the fast-forward.** The read-only detector refuses, and the refusal is protecting real bytes:
   ```
   $ git read-tree -n -u -m HEAD origin/master
   error: Untracked working tree file 'journal/entries/decisions/D254.md' would be overwritten by merge.   exit=128
   ```
   A `checkout`/`clean`-shaped "fix" would destroy the laptop's `D254`, `H466`, `L1908`, `L1909`, `P244` (untracked) and
   the modified `H464`, `H465`, `L1906`, `L1907`, `P242` — **nine entries that exist in no commit anywhere.** The same
   trap in the other direction is live for the other machine: the six ids `origin/master` has that this worktree does
   not (`H474`, `L1914`, `L1915`, `P243`, `P245`, `P247`) are *absent* here, not deleted — `P243` is a real local
   deletion by another stream and needs no action.
3. **Apply §4's map on the side that merges second**, rewrite the id token in the marker *and* the heading, leave one
   audit comment naming the old id, and write the whole old→new map to a file — never into prose (`D191` step 3).
4. **Rebuild the generated index with the tool, never by hand** (`journal.py index`), and **regenerate the state tier**
   (`journal.py state`, `journal.py questions`) — a state file taken from upstream silently omits every local entry
   (`D191` step 5). `state/status.tsv` is append-only, so its conflict resolution is the union of both sides.
5. **Prove it**: `journal.py check` must be 0 errors, and `idguard.py` must be `collisions: 0`, **on both machines**.
6. **Then fix the mint**, or this happens again next week: `idguard --floor` exists and nothing calls it. A reserved
   band per machine, or a host suffix, is what `D191`/`D198` asked for and what is still missing.

## 6. What could not be verified

* **Whether the two machines' trees can be made to agree without a merge commit.** They cannot, by measurement: the
  incoming commits add paths this worktree already holds under the same ids with different content, and `git` has no
  verb that keeps both sides at one path.
* **The other machine's *current* untracked set.** The snapshot is 12:14:45 local and that checkout is live — it moved
  from `a85232c` to `8875e22` and its untracked count went 18 → 21 *during this session*. Any later reading must be
  re-taken; the map above is a moment, not a state.
* **Whether the other machine has its own copy of this collision.** It was not asked to run `idguard` — reading its
  checkout was in scope, running tools against its index was not. It should.
