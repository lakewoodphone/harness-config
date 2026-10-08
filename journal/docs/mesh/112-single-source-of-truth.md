# 112 — Single source of truth and disk-write distribution — design

Produced 2026-09-18 by workstream C of the mesh programme, running on `ZABZ-TECH`. Deliverable 3 of the
mesh goal. It observed **only the machine it ran on** and ran no `ssh` to a peer, deliberately; every
claim therefore carries an evidence marker:

| Marker | Meaning |
|---|---|
| `[M]` | **Measured by the child on ZABZ-TECH** — command run, output read. |
| `[R]` | **Read from source/config on ZABZ-TECH** — a file's actual contents. |
| `[D]` | **Asserted in a document, journal entry or config comment** on ZABZ-TECH — a prior session's claim, not re-measured. Evidence-of-a-record, not a live fact. |
| `[G]` | **Given in the brief**, unverified here. |
| `[U]` | **Unknown — needs measurement.** |

**The mesh as seen from `zabz-tech`** (`tailscale status`, `[M]`): `zabz-tech` (self, 100.85.153.96),
`zabz-yoga-1` 100.72.162.5 **relayed via DERP "nyc" — no direct connection**, `secratary` 100.84.72.88
direct 1 ms, `zabz-tech-linux` 100.105.248.90 direct 1 ms, `lakewooechsmini` 100.126.146.121 direct
1 ms, `iphone-15-pro` present and not an agent node. `tailscale` 1.102.2. **The laptop being
DERP-relayed rather than direct is load-bearing for §5: it is the node with the worst convergence
latency, so it must be a pusher, never a node others wait on.**

## 1. Inventory of the state kinds

| # | Kind | Where it lives | Who writes it | What reads it |
|---|---|---|---|---|
| 1 | Authoritative business database | authority on `secratary` `[D]`; a **1.79 GB local copy** on ZABZ-TECH `[M]` | the FastAPI app on `secratary` `[D]` | on ZABZ-TECH: **nothing holds it open** (no `-wal`/`-shm`) `[M]` |
| 2 | Session transcripts | `~/.dsh/sessions/--<slug>--/<id>/session.v3.jsonl.zstd` `[M]` | one engine per `DSH_HOME`; 16 `node.exe` on this node `[M]` | the local engine; the hourly archiver `[R]` |
| 3 | Session projection cache | `~/.dsh/storages/session_projcache/sessions/<id>.json` `[M]` | the engine, atomic whole-file rewrite | tooling that greps transcripts `[R]` |
| 4 | The journal | `journal/entries/<kind>/<id>.md` + `state/` + `index/` `[M]` | only `journal.py append`, under an OS file lock `[M]` | every session on three machines |
| 5 | Harness config and presets | source `harness-config` repo; applied `~/.dsh/settings.yaml` (932 B, mtime 2026-09-16 11:02) `[M]` | `autosync` → `sync.py`, scheduled every 15 min `[M]` | the engine at session start `[D]` |
| 6 | Credentials | `~/.dsh/.credentials.yaml` (plaintext key) `[M]`; `personal-secretary-mvp/.env` (~250 keys, gitignored) `[M]` | human, per node | the engine and scripts on that node |
| 7 | Build artefacts and caches | npm-cache 3.5 GB / 110k files; `chromadb` 3.56 GB; `node_modules` 496 MB; pnpm store 374 MB `[M]` | package managers, the app | package managers, the app |
| 8 | Placement ledger | `~/.dsh/mesh/placements/<child-id>.json`, 25 files `[M]`; dispatch logs `~/.dsh/mesh/logs/*.jsonl` `[M]`; roster `packages/mesh-broker/nodes.json` in git `[R]` | the dispatching engine | the dispatching engine; `mesh-e2e` `[D]` |

Also classified (so that nothing is left unclassified): `workspace.json` (3,872 B `[M]`), attachments
(670 files / 214 MB `[M]`), the archive cursor, governor leases, health readings, journal derived caches,
push bookkeeping, mesh reachability readings.

### 1.2 The findings that matter (each measured)

- **The local database copy is ~3 days stale and indistinguishable from the authority.** 1,790,009,344 B,
  mtime **2026-09-15 16:59:17** `[M]`, with no `-wal`/`-shm` sidecar. Four other candidate databases sit
  beside it (`secretary_pre_prune_backup.db` 861 MB, `secretary_test.db` 79 MB, `test_secretary.db`,
  `family_chat.db`). **Nothing on that node tells a reader which of the five is the company.** This is the
  exact failure class of the recorded stale-database incident.
- **The journal is measurably divergent on ZABZ-TECH.** `master` = `f356be14…`, `origin/master` =
  `d530b1cf…`, autosync reports `ahead 7, behind 52`, `result: "attention"`,
  `preserved_ref: refs/heads/diverged-ZABZ-TECH-20260918`, **`id_collisions: 39`** `[R]`. **Nine entry ids
  mean two different entries right now** — `L1920`–`L1928` exist on both `master` and `origin/master` with
  different blob hashes `[M]`; `L1920` is `07963d0a…` locally and `f476355a…` on origin. Origin already
  carries seven `diverged-*` branches as scar tissue `[M]`.
- **Root cause, and it is mechanical:** ZABZ-TECH's clone is 52 commits behind because autosync refuses to
  fast-forward a diverged history, so its id ceiling cannot see the remote refs it has not fetched, so
  `journal.py append` reuses numbers. The journal's own rule is "reuse is forbidden, gaps are free" `[D]`.
- **That node is running 52-commits-old configuration** and cannot tell: the applied `settings.yaml` has
  mtime 2026-09-16 11:02 and carries **no commit sha, no `Updated:` field, no provenance at all** `[M]`.
- **The session store is not quiescent:** 727 `.zstd` files / 244 MB across 718 directories, and the count
  grew by 18 files during measurement — because the measuring session was writing into it `[M]`. No reader
  can take a consistent snapshot by listing.
- **Attachments grew 24×** since a prior document: now 670 files / 214,187,974 B `[M]` `[D]`.
- ZABZ-TECH holds **7.5 GB of disposable cache** in six trees against 161.5 GB free `[M]`.

## 2. Classification — exactly one per kind

| # | Kind | Class | Authority / merge rule / why-safe |
|---|---|---|---|
| 1 | Business database | **(a)** | Authority: `secretary.db` on `secratary`. Every other `*.db` on any node is a read-only replica or scratch, and a replica is *replaced*, never merged. **Merge rule: none — a replica that can write has become a second company.** |
| 2 | Session transcripts | **(c)** | Node-local, explicitly not shared. One engine writes a session for its whole life; two writers on one `DSH_HOME` have been observed writing duplicate sequence numbers into one session log `[D]`. The *archive* of closed sessions is (a). |
| 3 | Projection cache | **(c)** | Derived, disposable, rebuilt from #2. |
| 4 | Journal entries | **(b), but only after Phase 1** | Convergent through git. Authority of record: `master` on origin. Ids are handles, never renumbered; one id meaning two entries is repaired by `repair-ids --apply` which renumbers the later one **and leaves an alias**; exact duplicates go to `archive/duplicates/`. Offline a machine cannot see unfetched refs, so **conflict is possible by construction** — hence "reuse is forbidden, gaps are free". |
| 5 | Harness config + presets | **(a)** | Authority: the `harness-config` repo at a commit on origin. Convergence: autosync fast-forwards and applies **the HEAD snapshot**, never the working tree. Deliberately not convergent-replicated: two machines must not each merge their own `settings.yaml`. |
| 6 | Credentials | **(c)** | Node-local, never a git-tracked or sync-carried artefact (`sync.py` PROTECTED list; `.env` gitignored). Sharing is done by **issuing the same credential to two nodes**, never by copying a file. |
| 7 | Build artefacts and caches | **(c)** | Disposable, never replicated. Truth is the lockfile and the source. |
| 8 | Placement ledger | **(c) today, and this is a defect** | Per-child records are node-local and **nothing aggregates them** `[U]`. The roster is (a): a configuration, explicitly not a state store. |
| 9–16 | scratch, attachments, cursor, leases, health, derived caches, bookkeeping, reachability | (c), except | #10 attachments is **(b)** by content address (identical bytes merge trivially; differing bytes are two attachments, never a conflict); #11 archive rows is **(a)** — the DB rows on the authority; #13 health readings is **(b)** — last-writer-wins per `(node, check, checked_at)`. |

**The two classes that must never blur: #1 must never be (b), and #2/#6 must never be (a).**

## 3. The unreachable-authority rule, per kind

**Either refuse and say so, or serve a copy labelled with its age. Never serve a copy as if it were
current.**

| # | Kind | Rule |
|---|---|---|
| 1 | Business database | **Refuse**, for anything that is a fact about the business. A number that cannot name its source and its age is not evidence. A replica served at all must be served as *"a copy of the authority as of authority-epoch N"*, and the epoch must be a value **written by the authority inside the data**, never stamped on by the copier. |
| 2 | Session transcripts | Not applicable — no remote authority. If the local `DSH_HOME` is unreadable, **refuse**; never fall back to a peer's copy of a session with a different id. |
| 3 | Projection cache | Serve, labelled. Stale is acceptable **only** as a cache. |
| 4 | Journal | **Serve the local checkout labelled with the last-fetched `origin/master` ref**, and say the ref is from a fetch, not from now. **Never claim the local `master` is the record.** `append` may proceed but must **report loudly that its id ceiling could not see remote refs**. |
| 5 | Harness configuration | **Refuse to apply a merge it cannot attribute.** Today the applied file has no commit field `[M]`, so "refuse" is the only honest option until Phase 2 lands. |
| 6 | Credentials | **Refuse.** A missing key is a clear failure; a borrowed key is an unattributable action. |
| 7 | Caches | Serve, unlabelled. Age is irrelevant; only corruption is. |
| 8 | Placement ledger | **Refuse to place** if the broker or roster is unreachable — already the built behaviour, with a `state: "placement-failed"` record written. Keep it. |
| 10 | Attachments | **Refuse to serve a truncated or partially-replicated attachment.** If the hash cannot be verified, refuse. |
| 11 | Archive cursor / rows | Serve the local cursor **and say it is local**. Never infer "everything is archived" from an absent cursor row — **an empty result is a refusal, not a health check**. |
| 13 | Health readings | Serve, labelled with `generated_at`; the consumer drops anything older than the check's own cadence. |

## 4. Staleness must be visible — and verifiable without trusting a label

A label a copier writes about itself proves nothing: a stale copier stamps a stale label, and a lying one
stamps a fresh label. So the currency token **must be authored by the authority and carried inside the
data**.

```
source_id       : which copy was read (node, absolute path, format)
authority_epoch : a monotonically increasing value WRITTEN BY THE AUTHORITY
written_at      : when the authority wrote that epoch
read_at         : when this reading was taken (reader's clock)
age_ms          : read_at - written_at, computed not claimed
proof           : how a consumer re-derives currency without the label
```

| Kind | Authority-authored epoch | How the consumer verifies without a label |
|---|---|---|
| DB | a single-row `write_epoch` bumped in the same transaction as every write | ask the authority; a replica answers with the epoch *inside its own data* — it cannot forge what it did not author; equal ⇒ current, unequal ⇒ stale by exactly that many writes |
| Journal | the **commit sha of `origin/master`**, authored by git | `git merge-base --is-ancestor` when origin is reachable; offline, compare against a separately obtained sha |
| Config | the commit sha of `harness-config` HEAD at apply time | re-render from that commit and compare (`sync.py` already proves apply convergence) |
| Sessions / archive | the **highest `seq` present**, authored by the writing engine | count rows and compare to `lastRow` — arithmetic, not a claim |
| Placement | the **child's own `MESH-HOST:` line** | already implemented: the dispatcher compares the child's self-report against the broker's named node and records `disagreements: []` `[M]` — **this is the pattern to copy for everything else** |

**One rule that makes this survive contact with reality:** a consumer must never invent a fresh reading
from a stale one. A silent wrong number is a **test failure, not a warning**.

## 5. Disk-write distribution

### 5.1 The two measured constraints that bound the answer

- **`secratary` has 216 kB of free swap** `[G]`, corroborated by its own roster ("swap is at 99.9 % …
  which halves its effective slots") and by a placement rationale ("swap 99.6 % used"). A prior finding
  records that the swap is `/tmp` — a **tmpfs**. **A large buffered write there is a write into RAM with
  216 kB of overflow.** It is not a scratch disk.
- **The macOS mini answers no capacity surface** — it is excluded from the roster because its gate does
  not answer `GET /mesh/capacity` (curl exit 7) `[R]`, and its non-interactive shell lacks `node` on PATH
  `[G]`. **No node-implemented writer may live there, and it must never be the only holder of anything**,
  because both the sync path and the archive path are Node programs.

### 5.2 The distribution

| Node | Holds | Why |
|---|---|---|
| **`secratary`** | **The authority database, and nothing else large.** All committed writes to the company's records. | The one always-on node, so single-writer costs nothing in availability. **Forbidden there:** build output, `node_modules`, package caches, transcripts, vector stores, scratch, anything buffered. |
| **`zabz-tech`** | **All high-inode-count generated artefacts** — npm cache (3.5 GB / 110k files), `node_modules`, pnpm store, the derived vector store (3.56 GB) — plus the bulk of session transcripts. | Most free space (161.5 GB), most cores (32), direct 1 ms links to every other node. Nothing here is authoritative, so losing this disk loses no truth. |
| **`zabz-yoga-1`** (the laptop) | Local transcripts and caches for work done there — **and it should be a pusher, never a pull-target.** | The only node reachable **only by DERP relay** `[M]`. Its writes must drain to the authority when it reconnects, never block a peer. |
| **`zabz-tech-linux`** | Local transcripts and small deterministic jobs. | Tightest disk on the mesh `[D]`; direct 1 ms link makes it a good small-work node. |
| **`lakewooechsmini`** | **Nothing any Node program must read or write, and nothing unique.** | Cannot run the sync or the archiver. It may hold data; it may not *own* a mechanism, until interpreter-form dispatch there is measured (§7 Phase 0). |

> **The rule underneath the table:** writes that must converge go to the authority. Writes that cannot
> converge stay local and are labelled with the epoch that produced them. The largest writes are the ones
> nobody needs to converge, and they go where the disk and the cores are. **A cache may be deleted at any
> moment without a reconciliation** — and that is the only reason a 3.5 GB cache is allowed on a node that
> also runs an engine.

## 6. Reconciling a node that was offline

Worked against the live state on ZABZ-TECH (diverged 7/52, 39 id collisions).

0. **Establish the epoch before touching anything** — record `HEAD`, `origin/master` and the mtimes of
   every file the operation will touch. *Refuse to proceed if you cannot state what the node looked like
   before.*
1. **Preserve, do not fix, first** — push local commits to `refs/heads/diverged-<HOST>-<YYYYMMDD>`. Cannot
   fail a fast-forward, destroys nothing. Already fired on that node.
2. **Detect collisions by identity, not by eye** — `idguard.py` for the cross-machine count, then a
   non-destructive `git merge-tree --write-tree <branch> origin/master`: a bare tree hash means clean,
   stage-2/3 blob lines name each conflicted path.
3. **Classify every divergence** — derived cache (delete, it rebuilds); append-only record (merge both,
   allocate fresh ids for the local side, leave aliases); **rewritten state** (`journal/state/*`,
   `settings.yaml`, `status.json`) — the local copy has **no standing**, it is regenerated.
4. **Repair ids, never numbers** — `repair-ids --apply` renumbers the later entry and leaves an alias;
   `dedupe --apply` for exact duplicates. **Never renumber downward to tidy up: a gap costs nothing and a
   reused number destroys every citation to it.**
5. **Re-fetch, then re-apply configuration** — fast-forward, then `sync.py`, and confirm the applied file
   now names its commit.
6. **Rebuild what is derived** — `journal.py index --force`; drop stale projection caches.
7. **Drain the write backlog** — re-run the session archiver; idempotent by design (at-least-once, upsert
   on `(machine, session, seq)`, cursor advances only on an accepted batch).
8. **Prove convergence and write the proof down** — equal or ancestor; 0 collisions; sync converged;
   applied settings name a commit that exists on origin.

### What the reconciler MUST REFUSE to do

1. Merge or rebase a shared clone out from under running sessions — that node has 16 live `node.exe`
   processes and a held `journal/.lock` `[M]`, and a prior session declined exactly this and was right.
2. Renumber another machine's entry ids blind.
3. Force-push, reset, clean or stash. *This business has lost data twice doing so.*
4. Make a replica authoritative because it is easier.
5. Declare success from an empty result.
6. Sweep untracked entries written by other sessions into a commit it does not own.
7. Reconcile a node whose pre-state it could not record.

**Ordering is not optional**: preserve → detect → classify → repair ids → re-fetch config → rebuild
derived → drain backlog → prove. Every step but the last is reversible, which is why the last is last.

## 7. Phased implementation — cheapest first, one checkable test each

- **Phase 0 — measure the two unknowns that gate everything** (read-only, zero cost): whether
  `lakewooechsmini` accepts interpreter-form dispatch with an explicit node path, and the authority's
  current swap and `/tmp` residency. *Test:* one probe per node printing `MESH-HOST:` and its own `node
  --version`. **Pass:** every node answers with its own hostname, or is recorded as *refused, by name*.
  No node may be silently absent.
- **Phase 1 — make id collisions impossible to create silently, and clear the 39 that exist.** Wire
  `idguard.py` into the *writer* path with no silent `--no-fetch`. *Test:* two clones from a common
  ancestor, 20 appends each with one never fetching, then merge. **Pass:** 0 collisions, *or* the second
  append exits non-zero naming the unfetched refs. A run that reuses a number and exits 0 is a failure.
- **Phase 2 — put an authority-authored epoch in the two places that have none.** (a) `sync.py` writes the
  applied commit sha into `~/.dsh/settings.yaml`; (b) the company DB gains a single-row `write_epoch`
  bumped in the same transaction as every write. *Test:* the applied file carries exactly one commit, and
  `git cat-file -e <sha>` succeeds; the DB's epoch reads as an integer from both authority and replica and
  the difference is reported as a number even when large.
- **Phase 3 — make the stale replica visibly a replica.** Every path that prints a business number from a
  local DB prints `(source, authority_epoch, age)` or refuses. *Test:* point the reporting path at the
  ~3-day-stale local copy and at the authority. **Pass:** the stale run refuses or prints the epoch and
  age; **no code path prints a bare number.** This is the direct test of the failure this design exists
  for.
- **Phase 4 — unfreeze configuration for diverged nodes.** Apply the **origin** snapshot even when
  diverged (never the local working tree), and mark the file
  `commit=<origin-sha> (diverged: local work preserved on <ref>)`. *Test:* on ZABZ-TECH (ahead 7 / behind
  52) autosync changes `settings.yaml`, it names an origin sha, and `local_commits_preserved` is still
  true.
- **Phase 5 — aggregate the placement ledger on the authority**, reusing the session archiver's pattern.
  *Test:* place one child on each of two nodes; the aggregate has two rows with two distinct `node` values,
  each with the child's own `MESH-HOST:` verification and `disagreements: []`.
- **Phase 6 — prove the offline round trip.** Take a node off the tailnet, let it write entries and place
  two children, bring it back, run §6. **Pass:** all §6 assertions hold *and* the reconciler's log shows it
  **refused at least one operation by name**. A reconciliation that never refuses anything has not been
  tested against the failure it exists to prevent.

## What this design does NOT know

1. Whether the authority DB is actually on `secratary` right now, its live size, WAL state, or
   `write_epoch`-equivalent — `secratary` was never contacted.
2. Which process, if any, writes the authoritative DB, and whether it is the only writer.
3. Whether anything other than an ad-hoc agent session reads the 1.79 GB local copy on ZABZ-TECH.
4. What `192.168.50.138:8002 → 127.0.0.1:8002` was meant to reach — the target has no listener and
   refuses connections.
5. `secratary`'s current swap, `/tmp` residency, commit headroom and free disk.
6. The other three nodes' current free disk, memory and session-store sizes.
7. Whether the macOS mini can run a `dsh` child in ANY invocation form, and whether `node` is reachable
   there by absolute path.
8. What the 52 unpulled origin commits change, and specifically whether any touch `settings/` — which
   would make that node's running configuration materially wrong, not merely old.
9. Whether `~/.dsh/profiles/**` is genuinely 0.1 MB or is under-reported by reparse points — the same tree
   contains **493 reparse points** `[M]`, so the figure is not trustworthy in either direction.
10. The true total size of `~/.dsh` (two prior methods disagreed by 10 %).
11. Whether the session archiver's hourly job actually succeeds — its state file is fresh, but **state
    freshness is not delivery proof**, and the recorded failure mode is a *silently stopped* archive.
12. Whether any mesh-wide reader exists for the placement ledger.
13. Whether the roster's `secratary.dispatch.v1: null` (never measured) is still accurate.
14. Whether a fresh `idguard.py` run reproduces the 39 collisions (that number comes from `status.json`,
    read not re-run).
15. Which node is the mesh's *de facto* config writer, given origin is 52 ahead of one node and 7 ahead of
    another with eight `diverged-*` branches outstanding.
16. Whether the modified-but-uncommitted `journal/state/*` and `index/entries.tsv` on ZABZ-TECH are another
    live session's work or stale churn.
17. The other nodes' credential-file locations.
18. Whether any credential on ZABZ-TECH is *also* present on another node as the same value — a real
    security question, unmeasured.
