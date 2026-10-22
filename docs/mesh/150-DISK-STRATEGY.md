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
