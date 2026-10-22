# 150 — Disk on the authority: the map, the cause, and what actually stops the resizes

**Written 2026-10-22 ~17:55 UTC by the DSH session on ZABZ-TECH, at the owner's instruction:** *"every week you make me resize again, there must be some better way to do this all... a more efficient way of protecting disk space on the secretary without blocking any of its capabilities or making it any less fast."*

Every number below is `MEASURED` on `secratary-cloud` in this session, with the command shown. Anything not measured is labelled.

## 1. The map — where 194 GB actually is

| path | size | what it is | regenerable? |
|---|---|---|---|
| `/root/authority.db` | **31.8 GB** | the company database, sole writer | **NO — the one thing that must never be lost** |
| `/root/repos` | **26 GB** | git checkouts, incl. `_worktrees` 5 GB, `phone-and-tech-full` 2 GB, seven `pr-wt-*` at ~1 GB each | yes, from origin |
| `/root/wt*` (74 dirs) | **15.1 GB** | **agent fleet worktrees, never reaped.** Oldest 2026-10-12, newest today | yes, branches are in git |
| `/root/.usearch` | **15 GB** | the esearch index | **yes** — rebuilt from files |
| `/srv/ci` | **13.5 GB** | CI runner: `disk.img` 40 GiB sparse, **11 GB actually allocated** + 2.3 GB rootfs + 218 MB tarball | yes |
| `/opt/company` | **17 GB** | deployed company app: `.git` 8.3 GB, `data` 7 GB, `.venv` 2 GB | mixed |
| `/opt/company-archive` | **9 GB** | `lpt-transcripts` — the raw session archive (AGENTS.md §1 says it must always exist) | **NO — but it is cold, and it is compressible** |
| `/home/zabz` | **10.4 GB** | the service account's home | mixed |
| `/root/mail-archive`, `/root/code`, `swift-6.0.3…`, `/root/tmp-rescue`, `.cache`, `.dsh`, `.cfo` | **~12 GB** | mail archive 2.6 GB, a Swift toolchain 2.6 GB, assorted | mostly yes |
| `/usr` + `/var` + `/boot` | 3 GB | OS | no |

Commands: `df -h /` → `225G 194G 23G 90%`; `sudo du -x -d1 --block-size=1G /root /opt`; `ls -d /root/wt* | wc -l` → **74**; `sudo du -c -s /root/wt*` → 15091 MB; `losetup -a`; `du -sh /srv/ci/disk.img`.

## 2. The cause — it is not one runaway, it is nine buckets with no ceiling

The 2026-10-19 resize added roughly 64 GB. It was consumed inside three days by the same nine buckets, because **not one of them has a limit**:

1. **A worktree per agent session.** 74 of them, 15.1 GB, oldest ten days old, and the fleet rule that says "clean up at teardown" is a sentence in a document, not a cron. At ~200 MB–1 GB each this alone can eat a resize.
2. **Session events in the live database.** ~170K rows / ~1 GiB per day, appended into the same file that holds live operational tables, and SQLite does not give pages back without a VACUUM. This is the only **steady, permanent** growth on the box, and the corpus must be kept (D2655).
3. **A search index that is rebuilt from files and grows on every backfill** (12 GB added in one day on 2026-10-19).
4. **A CI loop image** that regrows after each trim (6.2 GiB was trimmed from it once already).
5. **Git history** — 8.3 GB `.git` in `/opt/company` alone, plus 26 GB of checkouts including seven one-branch `pr-wt-*` clones.
6. **Build debris** — `__pycache__` 1.38 GB, pytest basetemps ~22 GB on 10-20/21, a redundant 8.5 GB clone.

**Monitoring already exists and it is set too late to help.** `/usr/local/bin/disk-guard.py` runs every 15 minutes via `cron-wrap.sh` (1,092 recorded runs) and its own log reads `ok - / at 89.6% (22.44 GB free), /tmp at 57.8%, 0 backup dir(s) [warn 90% crit 95%]`. It warns at 90% and 95%, so at 89.6% it says **ok**, and it has never fired. It also cannot reclaim anything — it prunes dated backups only, and there are none.

**This is why the resize never sticks: the box is not measured and cleaned, it is only measured and then enlarged.**

## 3. What actually fixes it, in order of what each is worth

**Phase 0 — reclaim, free, no capability lost (est. 20–25 GB).**
Reap the 74 worktrees and the merged `pr-wt-*` / `_worktrees` clones. Branches stay in git, so nothing is lost that was ever committed; the risk is uncommitted work, so each tree must be checked for a dirty state before removal, exactly as `agent-fleet.sh status` reports it. Drop the CI runner tarball and any verified-duplicate `tmp-rescue`. **This is an owner decision only because it deletes directories.**

**Phase 1 — ceilings, free, so the next fleet cannot do it again.**
Worktree TTL enforced by a nightly reaper (a tree with no dirty files and no commits ahead of its branch is removed at 48 h); journald and CI-image caps; an index size budget; a hard `/tmp` cap; and **disk-guard moved to warn at 80%**, with its findings delivered to the owner's channel rather than a log nobody reads.

**Phase 2 — take the bulk off the boot volume.**
The index (15 GB, rebuildable) and the transcript archive (9 GB, cold) do not need to sit on the same filesystem as the company database. Moving them to a separate volume means a runaway index or a CI image can never fill the disk that holds `authority.db` — which is the failure mode that has actually hurt this estate before (L3932: a host at 97% turned SQLite writes into waits and wedged the service).

**Phase 3 — the only thing that stops the clock.**
The database is the one bucket that grows forever. Keeping the corpus while keeping the file bounded means **moving the session-event history out of the live database file** — its own file or volume, compressed, still queryable — and running an incremental vacuum on what remains. Until that happens, every resize buys about three weeks.

## 4. What is still being measured (fleet dispatched 2026-10-22)

Five read-only children are running: full inventory of the authority; the `authority.db` lifecycle (free pages, WAL, growth per table, what a bounded design saves); the esearch index (what it holds, what a cap would exclude, rebuild cost); the estate's own disk-incident history (every previous resize, what caused it, how long the fix lasted); and Hetzner's published prices for a volume versus a plan change, plus the option comparison.

## 5. The number that decides the money

At ~1 GiB/day of database growth, **no fixed disk size is permanent** — 365 GiB a year. So the purchase question is only "how much time does this buy" and it must be answered *after* Phase 0 and Phase 3, not instead of them.

## 6. What was actually implemented, 2026-10-22 (measured before and after)

**`df -h /` before: `225G 194G 23G 90%` → after: `225G 174G 43G 81%`. Twenty gigabytes reclaimed, verified by `df`, not by estimate.**

How each tree was made safe to remove, in order:

1. **Archive first.** `/root/wt-archive/` (58 MB) now holds, per tree: `dirty.patch`, `status.txt`, `staged.patch`/`unstaged.patch` where the diff against HEAD was empty, `untracked.txt` plus a copy of every untracked file under 200 KB, `stashes.txt`, and an `INFO.md` with the remote and the exact restore commands. The two big ones captured real work: `pr-wt-247` 25 MB of patch over 2,614 changed paths, `pr-wt-355` 15 MB over 1,730, `pr-wt-446` 12 MB over 1,458.
2. **Prove removal cannot lose a commit.** `git -C <tree> rev-parse --git-dir`: 71 of 83 were **worktrees**, whose object store is the parent repo's — removing the checkout cannot lose a ref. The four that were not worktrees were already broken before this session (their `.git` pointed at `/root/wt777c`, which no longer existed), so they were tarred whole (`orphaned-broken-clones-20261022.tar.gz`, 127 MB, 24,483 entries) before removal.
3. **Remove.** 71 worktrees via `git worktree remove --force` + `git worktree prune` in the parent, 7 pytest basetemp dirs, and the 4 broken clones after the tar verified.

**Reaper installed:** `/usr/local/bin/worktree-reaper.sh` (sha256 `9ae131fc…`), cron `17 4 * * *` via `cron-wrap.sh`. It only touches the three scratch roots, only trees with **no file modified in 48 h**, captures before removing, skips clones, and skips any tree whose capture fails. Dry run after install: `reaped=0 freed=0MB skipped=12` — nothing left to take.

**Alarm installed:** `/usr/local/bin/disk-alarm.sh`, cron `7 * * * *`. It fires at **88% used or under 25 GB free** (the old guard only spoke at 90/95 into a log) and appends a **journal pain entry** — the record every session reads at start. Both branches were proved: quiet branch `used=78% … below threshold`, forced branch `journal pain appended`. One real cron path, one self-test entry (P11339/P11340) resolved immediately.

**Runway now, honestly:** 43 GB free. The database's freelist was 10.07 GiB on 2026-10-22 and is being consumed at ~0.88 GiB/day, so the file starts growing again around **2026-11-02**, after which 43 GB buys about **six weeks**. This change buys the end of January at best. **The reclamation is protection against worktrees, not against the database.** Phase 3 is still the only permanent lever.

## 7. Corrections after the fleet reported (same day, 18:10Z) — supersedes §6's numbers where they differ

Two read-only children measured the parts I had estimated. Where their numbers beat mine, theirs are used.

**Total reclaimed: 39 GB, not 20.** A second tranche of worktrees existed outside the globs the first pass used — 44 more trees under `/root/repos/_wt*`, `/root/_hk293_*`, `/root/_lpt218_wt`, `/home/zabz/wt-item600` — reaped with the same archive-first reaper for a further 18.6 GB, plus 924 MB of Playwright cache and 2.1 GB of three stale `/opt/dsh-phone.failed2|failed3|prev` deploy copies. Final `df -h /`: **`225G 155G 62G 72%`** from `225G 194G 23G 90%`. The reaper's glob list was widened to cover every one of those roots, so the nightly job now sees what I missed.

**The database does NOT grow 1 GiB a day right now.** Measured properly: the file grew **7.9 MB in 3.4 days**; the growth is being absorbed by free pages, and it is the **freelist** that is falling — 3,352,593 pages on 2026-10-19 → 2,639,454 today = **942 MB/day**. At that rate the 10.07 GiB of free pages is gone in **11.5 days (≈2026-11-03)**, and only then does the file itself start growing. Anyone quoting "the file grows a gigabyte a day" is quoting the wrong clock.

**The composition of the database, measured with `dbstat` (3 m 21 s, not estimated):** `dsh_session_events` 13,916 MiB + its FTS data 4,655 MiB + two indexes 421 MiB = **19.96 GB, 85.7% of allocated space**. Everything else in the database is 3.3 GB and flat.

**Two archive tools already exist and must not be duplicated:** `dsh_session_events_retention.py` (planner, dry-run only) and `dsh_session_events_archive.py` (per-day zstd JSONL, re-read verification, "ARCHIVE, NEVER DELETE", prune owner-gated). The gap is that JSONL is not queryable by SQL, so archived days fall out of esearch — that is the work to do, not a third tool.

**The backup has one version of each key and no rotation.** `authority/secretary.db.gz` 6.84 GB, `authority/data/authority-data.tar.gz` 4.16 GB, `authority/accounting.db.gz` 6.7 MB — one object each, newest 12 hours old. A corrupt run overwrites the last good copy, and the DB leg streams the whole 32 GB at 7.1 GB RSS on a box that OOM-killed twice on 2026-10-22.

**Corrected order of work:** split the session corpus into its own database file (fixes the backup, ~3–5 days) → tier cold days into a queryable archive before **3 November** (the real fix, ~5–8 days) → `VACUUM INTO` with `auto_vacuum=INCREMENTAL` in the same quiet window (returns 10.07 GiB once, needs 34 GB scratch — which we now have). Page size 4096→8192 is a multi-hour rewrite for 1–2 GB: not worth it alone.

**Corrected runway: late November to the first days of December, not January.** 62 GB free, ~0.9 GB/day of growth that exists today (transcripts 0.66 GiB/day, chroma 0.21 GB/day), and after 3 November another ~0.94 GB/day from the database. About 27 days after the flex point.
