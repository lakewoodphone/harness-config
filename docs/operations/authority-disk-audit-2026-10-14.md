# Authority disk audit — 2026-10-14

**Commissioned by the owner, verbatim:** *"analyze and audit and research this disk issue because we
literally have 150 gigabyte of space on the cloud server. How could it have gone and filled up so fast?
Are we doing like backups to the server itself or something or too many backups? Didn't we set this up in
a way that we shouldn't have these problems and dealt with it robustly? So you have to analyze what went
wrong, had prevented in the future and general had to optimize it."*

**Run as a five-stream fleet on the mesh** (all five children executed on `ZABZ-TECH`, verified by each
child's own `MESH-HOST` line and the broker's placement record — no result here is local):

| stream | question | child | report |
|---|---|---|---|
| A | the guards that should have caught it | `subagent-2` | §4 |
| B | the 27.5 GB on-server database copy | `subagent-3` | §3.2 |
| C | is offsite backup real? | `subagent-4` | §5 |
| D | git object-store / clone / bundle sprawl | `subagent-5` | §3.5 |
| E | scratch sprawl + measured growth | `subagent-6` | §6 |

Baseline at audit time: `df -Pk /` → `/dev/sda1 157149496 total / 132000849 used / 18731132 avail / 88%`
(17.9 GiB free), measured 2026-10-14 ~23:30 UTC.

---

## 1. THE HEADLINE

**It did not fill up "fast". It had already hit zero-free twice that day before the copy that broke it,
and the machine could not tell anyone either time.**

Measured, from `disk-guard`'s own log and the estate monitor:

| time (UTC) | reading | source |
|---|---|---|
| 2026-10-13 20:15 → 2026-10-14 00:45 | **a zero-free window** | `disk-guard` |
| 2026-10-14 00:15:03 | **CRITICAL `/` at 98.5%, 0.0 GB free** | `/root/.disk-guard/guard.log` |
| 2026-10-14 01:00:02 | ALARM `/` at 90.5%, 4.0 GB free | same |
| 2026-10-14 05:49 | a large cleanup — 8.77 GiB → **30.28 GiB free** | `/var/lib/authority-backup/last-run.*` |
| 2026-10-14 07:58 | **33.63 GiB free** | preservation marker's own measurement |
| 2026-10-14 14:42 | **11.01 GiB free** | estate-monitor |
| 2026-10-14 14:45:04 | **CRITICAL `/` at 97.6%, 0.0 GB free** | `/root/.disk-guard/guard.log` |
| 2026-10-14 22:50 | **0.22 GiB free** | estate-monitor |
| 2026-10-14 23:00:02 | CRITICAL `/` at 99.9%, `free_bytes: 0` | `disk-guard status.json` |

Steepest measured bracket: **33.63 GiB → 11.01 GiB in 6.733 hours = −3,440 MiB/h (−3.36 GiB/h).** The
whole day moved **−30.06 GiB over 17.013 h (−1,809 MiB/h)**.

**The 29.4 GB copy taken at 22:39 UTC was the third fill of the day, not the first.** It was the one that
happened while a human was watching, which is the only reason it looked like the cause. Per the owner's
rule, I own my share: I added 24 GiB to a disk at 84 % without running `df`. That was the straw. **The
bale was already there, and nothing was delivering the alarm.**

---

## 2. WHAT THE AUDIT CHANGED ABOUT MY OWN EARLIER REPORT

Two corrections to `docs/handoff/2026-10-14-comms-sweep-and-payments-HANDOFF.md` §1:

1. **"already ~84 % full" understated the day.** 84 % was the *recovered* reading. Earlier the same day
   the disk read 98.5 % and 97.6 % with **zero bytes free**, twice.
2. **"the disk monitor dies of the same condition it watches" was right but incomplete.** It is worse:
   the disk metric **can never escalate by design** (see §4), and there is a second, independent break —
   a hardcoded path — that had been failing every 30 minutes for four hours before the incident.

---

## 3. WHAT ACTUALLY CONSUMES THE DISK

One filesystem, no quota, for the live database and every copy of it. 126 GiB used.

### 3.1 The live database
`/root/authority.db` — **29,432,315,904 B (27.4 GiB)**, plus a 64 MiB `-wal`. This grows and is not the
problem; it is the thing that must never be blocked from writing.

### 3.2 A whole second copy of that database, on the same disk — **25.63 GiB**
`/root/lpt-sweep-20261014/authority.db.pre-remediation-20261014T034251Z` (27,515,334,656 B). The
directory is 26 GB and the artefact is 99.95 % of it.

- **Provenance:** made 2026-10-14 04:06Z by "the LPT stalled-approval sweep", pinned by ledger item 176,
  project `prod-db-sync`. The copy spanned 03:42:51–04:06, straddling its own commit at **03:53:26**.
  **The producing script or session was NOT found** (journal `search "pre-remediation"` → no match;
  `.bash_history` → no hits).
- **It is consistent, not torn:** header arithmetic `4096 × 6,717,611 = 27,515,334,656` exactly, same as
  the live file. But its `change_counter=1` / `schema_version=1` against live `8481` / `11` shows page 1
  was written fresh — a rewritten logical snapshot.
- **ITS OWN "DO NOT DELETE" MARKER IS WRONG.** The marker says it is the pre-remediation rollback point.
  Its content is **post**-remediation: tasks 3132/27907/28550 read `done`, identical to live. **The real
  revert source is `rows-before-remediation-….json` (32 KB), which is present and intact.**
- **Nothing executable reads it.** The exact path + directory name were grepped across
  `/etc/systemd/system`, `/etc/cron.d`, `/etc/crontab`, `/root/bin`, `/opt/company` and `crontab -l`;
  the only hits are two *policy comments* forbidding removal without the owner. No cron, timer or script.
- **A verified offsite copy of the post-remediation database already exists** — R2
  `database_verified=ok`, `source_bytes=27623084032`, `reader_sha256=bb2a6f66…`, uploaded 2026-10-14
  05:49Z, after the remediation.
- **The one caveat:** only a `.sha256.partial` sidecar is present, no full `.sha256`, so per its own README
  the *local* copy is unverified. That does not matter for reclaiming it, since it is unverified *and*
  superseded by the verified offsite object.

### 3.3 The alarm's own evidence, on the same filesystem
`/root/.disk-guard/{status.json,guard.log}`, `/root/.cron-status/runs.tsv`, `/root/.estate-monitor/state.json`
— every one on `/`. At zero free, writing the alarm fails. Measured: `status.json.tmp` **0 bytes at 23:15**,
no `guard.log` line for 22:45 or 23:15, no `runs.tsv` row for either.

### 3.4 Copy-producing paths with no retention
- **`VACUUM INTO` whole-DB copies.** Found the producers: `/root/bin/cfo209-dedupe.py:188`,
  `cfo210-adjudicate.py:250`, `cfo132-reclass.py:173`, `cfo73-reclass.py:204`, `cfo74-fix.py:173`,
  `cfo164-dedupe.py:90` — each writes an **uncompressed** `accounting.db.bak-<label>-<ts>` with a
  hardcoded per-task label. **185 files, 1.3 GiB** in `~/.cfo/backups`, and `cfo_backup.py`'s own
  docstring says: *"NOTHING prunes this directory… on this host, it is the owner's to answer."*
  Plus 19 `accounting.db.bak-*` (423 MB) in `/root/accounting-data/live/`.
- **`/home/zabz/checkout-health-preserved/`** — **33 timestamped directories, 1.1 GiB**, one per run, up to
  10 runs/day on 10-14. Named in the preservation register.
- **51 linked git worktrees = 14,079,279,104 B (13.1 GiB) of working trees** (company 43, harness 7,
  ptf 3, lpt-hub 2), and `/root/work` is 14 GB of session scratch (`evolve2-*`, `evolve3-*`, `esc-*`,
  `c7fl-psm`).

### 3.5 Git: the pack is not garbage — the archive is in it
- `/opt/company/.git` — **7.50 GiB of packs**, 2,050 commits, **222 branches**, 163 dirty files.
  Object-byte reachability: **9,142,611,883 of 9,147,283,416 reachable = 99.95 %**; unreachable ≈ 4.7 MB.
  **Do not propose a repack to reclaim 7.7 GB — it is not there.** What fills it is
  **`archive/lpt-transcripts` at 8,275,360,838 B = 90.5 % of reachable bytes**, committed INTO git. The
  largest single blob, **1,049,538,560 B (`archive/lpt-transcripts/incoming/zabz-tech.tar`), now exists
  ONLY in git** — it is off disk. A ~1 GB blob is in a git object store on the sole-writer volume.
- `/root/code/harness-config/.git` — 486 MB packs **plus 1.14 GiB of loose objects** (3,422) plus a
  20 MiB interrupted-repack temp pack. Reclaim unknown: needs `git gc` (not run — a write op).
- `/root/work/lpt-hub/.git` (1.60 GB) is a **shallow clone whose 5/5 refs all exist in the full clone** —
  genuinely redundant. `/home/zabz/phone/lpt-hub/.git` (1.63 GB) is the live one, 1,385 dirty files.
- **Bundles: 3.18 GB.** `/root/git-rescue-20261012` (2.56 GB, 21 bundles) is a **documented, verified
  rescue set** — MANIFEST, journal `W2737b`/`P3163`, 21/21 verified by cloning, replicated to
  `lpt-survivor-01` in another region. **`P3163` records that owner-queue #484 recommended deleting it as
  "already-on-origin scratch" and that obeying would have destroyed uniquely-held work.** #484 was
  amended. **Move it off this disk; never delete it.**
- **Do not touch:** `hc-main.bundle` — it *is* harness-config's `remote.origin.url`. Bundles r2/r13/r14/
  r15/r16 (stash-only) hold refs that exist **nowhere else**. `/root/work/ptf` (7/9 refs) and
  `evolve3-wedge` (47/49) hold unpushed ref objects.

### 3.6 The honest total
**~44.5 GiB of the 126 GiB used is copies, rescue sets, scratch and orphaned stores — not company data.**
The single largest is §3.2 at 25.63 GiB, written in one go, by a sweep nobody could later identify.

---

## 4. WHY NOBODY WAS TOLD — the alarm chain is broken in four places

The estate did not lack a disk alarm. It has **`disk-guard`, running every 15 minutes**, with WARN 90 % /
CRIT 95 %. It fired. Three separate breaks stopped it reaching a human.

1. **`disk-guard` only measures and records.** `disk-guard.py:90-92` holds the thresholds; `:107`
   `INVOKE_RETENTION` defaults to `"0"`; the only write is `--write-status` to `~/.disk-guard/`. **It has
   no prune, no reclaim and no owner page.** Its output is a log line nobody reads.
2. **The escalation path points at a file that does not exist.** `cron-failures.py:104` deliberately does
   *not* file `disk-guard`'s `rc=1` as a fault — it defers to `sources/disk-space.py`, whose
   `GUARD = ~/bin/disk-guard.py`. **The real binary is `/usr/local/bin/disk-guard.py`, and `DISK_GUARD` is
   set nowhere.** So since 19:37 it fails every 30 minutes with
   `SIGNAL UNREADABLE -- the disk guard itself is missing at /root/bin/disk-guard.py`. **The thing watching
   the disk was reporting that it could not find itself — and nothing read that either.**
3. **By design, disk can never escalate.** `estate-monitor`'s state records
   `"conditions_allowed_to_escalate": ["public_health_status"]` and `disk_used_pct` `mode="log"`. Its
   transport is `syslog + alerts.jsonl + ESCALATED file — NO outbound message of any kind`. **Only public
   health can page a human. A full disk cannot, as configured.**
4. **Every stage of the alarm must write to the filesystem whose exhaustion it is alarming about**
   (`status.json`, `guard.log`, `runs.tsv`, and `estate-monitor`'s `save_json` at `:1432`, which runs
   *before* the verdict is rendered and has no `try/except`). At zero free the write raises `ENOSPC` and
   the alarm is lost. **Measured:** `status.json.tmp` 0 bytes at 23:15; no `guard.log` line for 22:45 or
   23:15; no `runs.tsv` row for either.

**And the monitor itself was blind for eight hours across the fill.** `estate-monitor` verdict lines per
hour on 2026-10-14: `14 → 22`, then **nothing until `22 → 5`** — it stopped ~14:44Z and resumed ~22:40Z,
exactly spanning the 33.63 → 11.01 GiB burn. Verdict `gap=656.8s` was observed on its recovery run.

**Also unenforced:** the one cron pruner, `prune-backups.sh` (05:45 daily), operates on **one root**,
`/var/lib/authority-snapshots`, which contains **1.4 MB and 1 entry**. Its own log says
`0 backup(s) present, keeping 0, removing 0`. On 2026-10-13 it returned `rc=4`,
`FLOOR BREACHED - only 8057340 KB free … Pruned NOTHING`. Meanwhile `prune-backups.sh`'s header carries a
**preservation register** forbidding removal of `/root/lpt-sweep-20261014`,
`/root/checkout-health-preserved` and `/home/zabz/checkout-health-preserved` without the owner — **which is
exactly why the 25.63 GiB survived its own pruner.** The pruner is not broken; it is scoped away from
everything that matters.

---

## 5. THE OWNER'S THREE QUESTIONS, ANSWERED

**"How could it have filled up so fast?"**
Not growth. `authority.db` grows at **51.9 MiB/h over four days** (98.8 MiB/h most recently) — that alone
is 185 hours to fill the current free space. **The fills are discrete large writes.** Measured rates:
−3,440 MiB/h at the steepest, −1,809 MiB/h across the day, against a ~381 MiB/h weekly background. **A
single 25.63 GiB write is 18.4 % of the whole disk in one operation.**

**"Are we doing backups to the server itself?"**
**Not the offsite job — that one is clean.** `authority-offsite-backup.sh` streams page-reader → gzip →
64 MiB multipart straight to R2 and records **`peak_extra_disk_bytes=0`**; two earlier designs that wrote
a 23.6 GB local snapshot first were deliberately removed for this reason. One same-filesystem write does
exist — `authority-data-offsite.sh:68` stages a 4.03 GB tar in `/var/tmp` and removes it at line 163 —
transient staging, not a backup.
**But copies ARE being written onto the server, by three other paths:** whole-DB `VACUUM INTO` rollback
copies (§3.2, §3.4), git repacking and bundle creation (§3.5), and un-pruned accumulating directories.

**"Too many backups? Didn't we set it up robustly?"**
**Offsite is real and current: Cloudflare R2, bucket `lpt-authority-backups`**, verified by a live
read-only listing — `authority/secretary.db.gz` 7,390,573,886 B at 2026-10-14T05:46:57Z (**17.6 h old**),
`authority/accounting.db.gz` 5.83 MB, `authority/data/authority-data.tar.gz` 4.03 GB, plus three
`.sha256` sidecars. One generation per key. **So the answer is not "too many backups". It is copies with
no retention, written onto the same filesystem, one of which was 18 % of the disk.**
The robustness gaps that matter:

- **One generation, overwrite in place, daily.** A bad write propagates offsite within 24 h. There is no
  second generation to fall back to. R2 versioning/lifecycle is **`AccessDenied`** to the object-scoped
  token, so older generations may exist invisibly — unverifiable from here.
- **~11.4 GB offsite against ~55 GB of on-host state.** Not covered: **`chromadb` 2.4 GB
  (explicit `--exclude` at line 60)**; **`archive/lpt-transcripts` 7.1 GB (no mechanism found)** — the same
  data whose 1.05 GB blob lives only inside `/opt/company`'s git; **`mail-archive` 2.6 GB**;
  **`.usearch` 741 MB**; `.fsearch` 227 MB (regenerable).
- **The restic pushers named by the systems register live on the frozen office box with cron masked**, and
  the register still points there. `command -v restic` on the authority is empty; no `/root/.restic*`.
  The register's §2.2 also names the wrong bucket (`lakewood-rentals-media` vs the live
  `lpt-authority-backups`).

---

## 6. WHAT TO DO — in risk order

**Zero-risk, unblocks the whole existing chain (do first):**
1. **Point `DISK_GUARD` at `/usr/local/bin/disk-guard.py`** (or symlink `/root/bin/disk-guard.py`).
   0 bytes, one line, restores the escalation that has been failing every 30 minutes since 19:37.
2. **Move the alarm's verdict off the threatened filesystem.** Emit to syslog / an already-open fd / a
   tmpfs path **before** any write to `/`. Wrap `estate-monitor.py`'s `save_json` (`:1432`) in
   `try/except`. Without this, every future full disk loses its own alarm — by construction.
3. **Let disk escalate.** Add `disk_used_pct` (or a `disk_critical` derived condition) to
   `conditions_allowed_to_escalate`. Right now a full disk cannot page anyone by design.
4. **Guard the large-write paths with a `df` headroom check** — one check per writer, refusing a write
   that would take free space below a floor. Cheapest possible version of the rule I broke.

**Owner decisions (money / irreversible / policy):**
5. **Reclaim 25.63 GiB** by removing `/root/lpt-sweep-20261014/authority.db.pre-remediation-*`. The case
   for it: no executable consumer (grepped); the marker's stated reason is **false** (it is post-
   remediation); the true revert source is a 32 KB JSON that stays; and a **verified** offsite copy exists
   from 05:49Z. Estimated result: **~70 % used**. This needs the owner because the file carries a
   DO-NOT-DELETE marker.
6. **Set a retention policy for the copy producers** — `~/.cfo/backups` (185 files, 1.3 GiB) has no
   pruner by its own admission; `checkout-health-preserved` (1.1 GiB, 33 dirs) and `/root/work` scratch
   (~12 GiB) grow per session. The producer exists; only the policy is missing.
7. **Move, do not delete, `/root/git-rescue-20261012`** (2.56 GB) off the authority — `P3163` is the
   record of what happens when someone deletes it.
8. **Bound the filesystem structurally.** Recommended: an **ext4 project quota on `/root`**. The
   incident was a second 29.4 GB copy into `/root` while a 27.5 GB copy already sat there; a quota
   returns `EDQUOT` to the copy and leaves the live database writing. Needs `mount -o remount,prjquota /`
   and the `quota` package, so it is a real change to the sole-writer volume and is the owner's call.
   Rejected alternatives, with reasons: a **cgroup/IO limit** bounds bandwidth, not bytes (wrong unit);
   a **separate volume** is unavailable without LVM and ext4 cannot shrink online, so it is riskier than
   the disease; ext4's 5 % reserve is invisible to root, which every guard runs as.

**Optimisation, lower risk:**
9. **Delete the redundant shallow clone** `/root/work/lpt-hub/.git` (1.60 GB) — 5/5 of its refs are in the
   full clone. **Keep** `/home/zabz/phone/lpt-hub` (live, 1,385 dirty files).
10. **`git gc` on `/root/code/harness-config`** to clear **1.14 GiB of loose objects** and a 20 MiB
    interrupted-repack temp pack. Reclaim not measured — `gc --dry-run` was not run.
11. **Get `archive/lpt-transcripts` out of git.** It is **90.5 % of `/opt/company`'s reachable object
    bytes (8.28 GB)** including a **1.05 GB blob that exists nowhere else**. This is not a disk fix; it is
    a "a 1 GB binary does not belong in a git object store on the sole-writer volume" fix, and it must be
    done with an offsite copy taken first.
12. **Correct the systems register** (`docs/mesh/000-SYSTEMS-REGISTER.md`): the authority's spec is stated
    as **2 vCPU / 7.7 GB / 75 GB** against a live **4 vCPU / 15 GB / 150 GB**; `secratary-cloud` §2.2 names
    offsite scripts and a bucket that are not what is deployed; §4 trap 2 still says to
    *"do that work on the idle cloud box"* when the cloud box is now the sole writer.

---

## 7. WHAT MUST NOT BE TOUCHED WITHOUT THE OWNER

| path | bytes | why |
|---|---|---|
| `/root/lpt-sweep-20261014/authority.db.pre-remediation-*` | 25.63 GiB | DO-NOT-DELETE marker + preservation register; reason is falsified but the marker is the owner's |
| `/root/git-rescue-20261012` | 2.56 GB | `P3163`: deleting it was already recommended once and would have destroyed unique work |
| `hc-main.bundle` | 145 MB | it **is** harness-config's `remote.origin.url` |
| git-rescue bundles r2/r13/r14/r15/r16 | (inside the above) | stash-only refs exist **nowhere else** |
| `/root/work/ptf`, `evolve3-wedge` | 82 MB | unpushed ref objects found only there |
| the 51 linked worktrees | 13.1 GiB | uncommitted work; the same unstaged edit to `scripts/ha/check-security-absence.py` appears in **8** of them |
| `/home/zabz/checkout-health-preserved` | 1.1 GiB | named in the preservation register |

---

## 8. NOT VERIFIED — do not treat as established

- **`PRAGMA quick_check` on `authority.db` was never run** after the ENOSPC. Reads and writes work and the
  counts are sane; **integrity is unproven.** Recommended at a quiet time.
- **`git gc --dry-run` / `git bundle list-heads` were not run** (write ops / budget), so every git
  reclaim figure is "likely", never "safe to delete".
- **The producer of the 25.63 GiB copy was not found** — journal `search` returned no match (a refusal,
  not health) and `.bash_history` had no hits.
- **What removed ~83 GB at ~01:15Z and ~18 GB at ~23:22Z is unattributed.** No large deleted-but-open file
  was found in `/proc/*/fd`.
- **R2 versioning/lifecycle is `AccessDenied`** to the object-scoped token — older generations may exist
  invisibly, or may not.
- **The offsite copy of the 1.05 GB `incoming/zabz-tech.tar` is unknown** — it is off disk, so if no `.zst`
  or offsite copy holds it, git is its only home.
- `sar` filesystem history is **absent** (`SADC_OPTIONS="-S DISK"`), so there is no independent
  free-space series for the first two-thirds of the burn.
- The disk filling was observed on the authority. **I did not audit the other hosts** — `lpt-apps-01` is
  documented at **90 % full**, and `waze-mdm-01` / `lpt-survivor-01` were not examined at all.

---

## 9. EVIDENCE INDEX

| claim | where it was read |
|---|---|
| inventory (310 lines) | `/tmp/disk-inventory-20261014.txt` on the authority; local copy `_work/disk-inventory-20261014.txt` |
| disk-guard thresholds, `INVOKE_RETENTION=0` | `disk-guard.py:90-92`, `:107`, `:315-329`, `:335` |
| disk-guard firing 98.5 % / 97.6 % / 99.9 % | `/root/.disk-guard/guard.log`, `/root/.disk-guard/status.json` |
| the wrong-path break | `cron-failures.py:104`, `sources/disk-space.py:47`, `sources.log` |
| escalation allow-list and log-only disk | `/root/.estate-monitor/state.json`, `alerts.jsonl` |
| monitor 8-hour blind spot | `journalctl -u estate-monitor.service \| grep disk_used_pct` |
| authority.db size series | `/var/lib/authority-backup/last-run.*` field `source_bytes` |
| free-space series | same manifests + `df`, cross-checked against `disk_free_kb_before` |
| the 25.63 GiB copy's nature | its own `DO-NOT-DELETE-*.md`, `COMMON.md`, `remediation-run.log`, header page arithmetic |
| `prune-backups` scope and its `rc=4` | `prune-backups.sh:61,101-104`, `/var/log/authority-backup-prune.log` |
| offsite reality | live read-only R2 listing, 6 objects; `/var/lib/authority-backup/last-run` |
| R2 coverage gaps | `authority-offsite-backup.sh` line 60 `--exclude`; `authority-data-offsite.sh:68,163` |
| copy producers with no pruner | `cfo209-dedupe.py:188` etc.; `cfo_backup.py` docstring |
| git reachability 99.95 % | `git count-objects -vH`, index-level object-byte scan in `/opt/company` |
| transcript archive inside git | `archive/lpt-transcripts` 8,275,360,838 B reachable; blob 1,049,538,560 |
| git-rescue is deliberate | `MANIFEST-README.txt`, journal `W2737b`, `P3163` |
