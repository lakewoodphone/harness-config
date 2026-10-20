# 189 — GIT AUDIT: EVERY MACHINE

**Revision 2.** Audit window 2026-10-12 ~16:30–17:25 UTC.
**Auditor:** DSH child agent, mesh thread `remote-c48005c6-db47-4153-bb69-e0b475d8b0bb`.
**Execution host:** **`ZABZ-TECH`** (Windows desktop, alias `desktop-ts`) — **not** the cloud authority and **not** `linux-pc-ts`.
**Posture:** strictly READ-ONLY on every audited machine. No `fetch`, `push`, `merge`, `rebase`, `stash`, `branch`, `reset`, `clean`, `gc`, `prune`, `checkout` or delete was run against any audited repository. `GIT_OPTIONAL_LOCKS=0` was exported for every read so that even `git status` could not rewrite an index (important on the frozen office box). The only durable writes are this document and its commit.

> **Relationship to revision 1.** Revision 1 of this file was written at 16:20:39Z by the previous turn of this same mesh thread, running on `zabz-tech-linux`, and is committed as `b11b196`. It is a good audit and revision 2 keeps its findings, marked **[v1]**, wherever revision 2 did not re-measure them. Revision 2 adds what revision 1 could not: the **Windows fleet** (its §1.D was explicitly "not established"), the **survivor standby repo** (invisible to v1 because git refused it, see below), and fresh readings of every moving target. Where a number changed, the new number is given with the time it was read.
>
> **Method note — a read that silently returns nothing is a wrong answer.** Two traps were hit and are recorded because they will bite the next auditor:
> 1. `git` refuses repositories whose files are owned by another user (`fatal: detected dubious ownership`). `survivor:/opt/company` is owned `company:company` and the auditor is root, so the whole repo was **skipped in silence** until `-c safe.directory='*'` was added to every invocation. Every repo below was then re-read with that flag.
> 2. On Windows, PowerShell fed to `powershell -Command -` over ssh must be **ASCII**; a UTF-8 file made the remote script produce zero output and exit 0. All Windows scripts here were written ASCII.

---

## 0. Machines and reachability (measured from `ZABZ-TECH`, 16:39–16:44Z)

| alias | hostname / address | reached | how | notes |
|---|---|---|---|---|
| `secratary-cloud` | `secratary-cloud` / 100.73.176.126 / 178.156.194.1 | YES | `ssh secratary-cloud` (root, hetzner key) | the authority |
| `secratary-ts` | `secratary` | YES | `ssh secratary-ts` (user zabz) | **FROZEN office box — read-only commands only** |
| `desktop-ts` | `ZABZ-TECH` | YES | *this machine* | the execution host |
| `laptop-ts` | `ZABZ-YOGA` | YES | `ssh laptop-ts` (Windows, user ezabz) | drops long sessionless runs — see §5 |
| `linux-pc-ts` | `zabz-tech-linux` | YES | `ssh linux-pc-ts` | host of revision 1 |
| `mac-mini-ts` | `LakewooechsMini` / 100.126.146.121 | **NO** | `ssh: connect to host ... port 22: Connection timed out` (name **and** tailnet IP) | **UNKNOWN — never "clean"** |
| `lpt-apps` | `lpt-apps-01` / 2.28.33.58 | YES | `ssh lpt-apps` (root) | Caddy front door + vault |
| `survivor` | `lpt-survivor-01` / 2.31.18.142 | YES | `ssh -i ~/.ssh/id_ed25519_hetzner root@2.31.18.142` (no alias exists) | Hetzner standby |
| *(bonus)* `hetzner` | `waze-mdm-01` / 87.99.141.172 | YES | `ssh hetzner` (root) | not in the task list; no git repos found under `/root /opt /srv /home` |

**Noise excluded from every dirty/untracked count and stated here:** `__pycache__`, `node_modules`, `.venv`, `venv`, `.next`, `.pytest_cache`, `.mypy_cache`, `.pnpm-store`, `.DS_Store`, `*.pyc`. Windows also excluded the `harness-config/_scratch/autosync-verify-*` fixture trees, `.pytest-tmp-next`, `wt-562*`, `wt-563*` (counted, not enumerated), and on the authority `/opt/company/archive/` (46,963 files, 9.0 GB) is reported as one data item, not 46,963 rows.

---

## 1. Every repository found

Totals: **≈170 git repositories enumerated** across the reachable machines — about **118 working repositories** and about **52 test/fixture/throwaway repositories**. `mac-mini-ts` contributes zero only because it could not be reached.

### 1.A `secratary-cloud` — the authority (root) — 7 repos

Re-measured 16:41Z (v2) and 16:43Z (deep dive).

| path | kind | branch@HEAD | dirty M/U | local br | unique-tip br | stashes | remotes |
|---|---|---|---|---|---|---|---|
| `/opt/company` | worktree | `master@98c0595b` | 33 M / 47,001 U (46,955 under `archive/`) | 6 | 1 (`preserve/uncommitted-20261012-unreviewed@42109f4a`) | 0 | `origin`=GitHub `lakewoodphone/personal-secretary-mvp` (ls-remote OK, 114 heads) |
| `/root/ceo-kernel` | worktree | `main@91c6f2ea` | 0 M / 1 U | 1 | 1 (`main`, 1 ahead of origin) | 0 | `origin`=`/root/kernel.bundle` (local, OK) |
| `/root/code/harness-config` | worktree | `main@d05105f9` | 4 M / 9 U | 1 | 1 (`main`, **73 ahead / 0 behind `origin/main`**) | 0 | `origin`=`/root/hc-main.bundle` (**stale**: bundle main = `ee3a7e2f`, 2026-10-10); `vault`=`root@2.28.33.58:/srv/git/harness-config.git` (OK) |
| `/root/code/unified-search` | worktree | `main@e4b9d46f` | clean | 1 | 0 | 0 | `origin`=`/root/repos/unified-search.git` (OK) |
| `/root/repos/noson-yanofsky-profile.git` | **BARE** | `main@1d489a03` | – | 1 | 1 | 0 | **none** (but the same SHA is on `laptop-ts`, see 1.E — so no longer single-copy) |
| `/root/repos/unified-search.git` | **BARE** | `main@e4b9d46f` | – | 1 | 0 | 0 | none |
| `/home/zabz/code/.dsh-mesh-mailboxes/...` | not a repo | – | – | – | – | – | – |

`origin.bundle` facts: `/root/hc-main.bundle` 145 MB (2026-10-11 06:35Z), `/root/kernel.bundle` 138 KB, `/root/psm-master.bundle` 285 MB. `git ls-remote origin` → `refs/heads/main = ee3a7e2f`; `git ls-remote vault` → `HEAD=refs/heads/main = a692ecd8`, i.e. **the vault is exactly one commit behind the authority's main and the bundle is 73 commits behind**. `journal-commit` cron: `*/15 * * * * /usr/local/bin/cron-wrap.sh journal-commit ...` — the vault is a *rolling* mirror, not a backup.

### 1.B `secratary-ts` — FROZEN office box — 37 real + 41 fixture repos

Re-measured 16:44Z with a light pass (74 candidates). v1 measured fsck/dangling in depth; those counts are marked [v1].

| path | kind | branch@sha | dirty M/U | local br | unique-tip br | stash | remotes |
|---|---|---|---|---|---|---|---|
| `harness-config.git` | **BARE** | `master@1245e54d` | – | **97** | **25** | 0 | **none** |
| `code/harness-config` | worktree | `main@f1713ce1` | 38 entries | 16 | 3 (`agent/ownertext-flood`, `agent/ws-orderfeed`, `hk/sms-inbox-condition-exit-20261006T191710Z`) | 0 | `origin`=local bare OK |
| `personal-secretary-mvp` | worktree | `hk/item642-gate-retry-after-20261010@26678993` | 62 entries | 99 | 1 | **33** | GitHub OK; `delivery`=local |
| `bin` | worktree | `shift/traffic-eta-20261009T0045Z@a53e10b4` | 274 entries | 51 | 11 | 0 | `origin`=local `bin.git` OK |
| `bin.git` | **BARE** | `master@f08a5c4` | – | 41 | **13** | 0 | **none** |
| `mesh-security.git` | **BARE** | `main@09fd362f` | – | 1 | 1 (19 unique commits [v1]) | 0 | **none** |
| `home.git` | **BARE** | unborn HEAD | – | 1 | 1 (86 commits [v1]) | 0 | none |
| `ceo-kernel.git` | **BARE** | `main@c1f6082` | – | 4 | 1 (`hk/item231-kernel-gitignore-20261008`) | 0 | none |
| `repos/halacha.git` | **BARE** | `master@840c99b` | – | 1 | 1 (tip mirrored in `repos/halacha`) | 0 | none |
| `repos/lpt-books.git` | **BARE** | `master@3a2e75d6` | – | 12 | 3 (`ws8-automate-20261007`, `hk/item231-clarification-record-20261008`, `hk/item231-nullcat-classified-20261008`) | 0 | none |
| `phone/yitz-insurance-2026-10-06` | worktree | `master@fe61463a` | 70 entries | 1 | 1 | 0 | **none** |
| `code/unified-search` | worktree | `main@3d34c249` | clean | 2 | 1 | 0 | `origin=/tmp/unified-search.bundle` — **bundle gone, ls-remote FAILS** |
| `repos/kosher-filter-ai` | worktree | `kf530/ios-cascade-escalate-20261010@7983eaff` | 1 | 10 | 1 | **1** | GitHub OK |
| `repos/lpt-hub` | worktree | `main@738d78f7` | 8 | 33 | 0 | 0 | GitHub OK |
| `repos/phone-and-tech-full` | worktree | `project-keepalive/item-466-husky-phantom-20261005@7734e1c8` | 1 | 54 | 0 | 0 | GitHub OK |
| `repos/personality-test`, `repos/quickbooks-agent`, `code/lpt-ops` | worktree | various | 0–3 | 2–8 | 0–1 | 0 | GitHub OK |
| `harness-config.pre-unify-20260922`, `hc-fork-lab-20260917T033457Z` | worktree | `master`/`reconcile/lab` | 0 | 5 each | 1 each (`journal-migration-20260915`) | 0 | local OK |
| `code/home`, `repos/chumash-timeline`, `repos/ha-config`, `repos/kyocera-escalator`, `repos/lpt-flip-phone`, `repos/research-knowledge-base`, `ha-config-live`, `phone/live-voice-dialer`, `checkout-health-test`, `_converge-*`, `harness-config.bak-20260915T0200Z` | worktree | various | 0–7 | 1–5 | 0 | 0 | mostly GitHub/local |
| `tmp-rescue-20261002/*` (18), `wt-562-baseline/.pytest-tmp-next/*` (5), `wt-563-master/.pytest-tmp-next/*` (5), `owner-alert-build/pristine/.pytest-tmp-next/*` (2) | worktree | fixture | 0–7 | 1–99 | 0–2 | 0–33 | fixtures |
| `/opt/actions-runner/_work/phone-and-tech-full/phone-and-tech-full` | worktree | `test@df104409` | clean | 1 | 0 | 0 | GitHub OK (owner `ghrunner`) |

`fsck` [v1]: dangling — `phone-and-tech-full` 272, `lpt-hub` 204, `actions-runner` 143, `personal-secretary-mvp` 81, `kosher-filter-ai` 31, `code/harness-config` 19, `harness-config.pre-unify` 8.

**Push capability:** the office box **cannot reach the vault** (`root@2.28.33.58` → `Permission denied (publickey)` [v1]). It can read GitHub. It cannot push anywhere useful without credentials it does not have.

### 1.C `linux-pc-ts` / `zabz-tech-linux` (host of revision 1) — 9 repos

Re-measured 16:44Z.

| path | kind | branch@sha | dirty | local br | unique-tip br | stash | remotes |
|---|---|---|---|---|---|---|---|
| `~/code/harness-config` | worktree | `main@d5621aa2` (was `6d057fec` in v1) | 4 | 6 | 3 (`main`, `meshfix/mfx-provider`, `meshfix/mfx-transport`) | **1** (`presync-bench-20261011-2226`, in no ref [v1]) | `origin`=`secretary:/home/zabz/harness-config.git` OK; `mirror`=`/home/zabz/harness-config-mirror.git` OK |
| `~/harness-config-mirror.git` | **BARE** | `master@1b921d70` | – | 1 | 1 | 0 | none |
| `~/work/ceo-kernel` | worktree | `main@7be7fded` | 4 | 1 | 0 | 0 | `origin=/root/kernel.bundle` — **does not exist on this host** |
| `~/personal-secretary-mvp` | worktree | `master@696e5e25` | 0 | 1 | 0 | 1 (empty [v1]) | GitHub OK (230 behind) |
| `~/mtkclient`, `~/edl_case/edl` | worktree | third-party | 1 / 70 | 1 | 0 | 0 | GitHub public |
| `~/hk367-consumer`, `~/hk367-node2-20261002T0837Z` | worktree | `master` | 0 | 1 | 0 | 0 | `mirror` / local |
| `~/hk367-consumer-autosync-20261002T0856Z` | worktree | `master@84ea4301` | 1 | 1 | 0 | 0 | `origin=file:///home/zabz/NONEXISTENT-secratary/harness-config.git` (**broken by name**), `mirror` |

### 1.D `desktop-ts` / `ZABZ-TECH` — **NEW: 43 repositories** (revision 1 left this UNKNOWN)

Full per-repo read at 16:47–17:0xZ. Roots scanned: `C:\Users\ezabz`, `C:\opt`, `C:\home\zabz`, `C:\srv`, `C:\root`, `C:\LPT`, `C:\memories`, `C:\primary-profile`, `C:\data`, `C:\tools`, depth 5. `git version 2.52.0.windows.1`.

**Machine-level capability defect (measured, blocks all sync from this box):**
- `git ls-remote` over ssh fails for **every** ssh remote: `/c/Users/ezabz/.ssh/config: line 1: Bad configuration option: \357\273\277#` → `fatal: Could not read from remote repository`. A **UTF-8 BOM on line 1 of `C:\Users\ezabz\.ssh\config`** breaks Git-for-Windows' MSYS `ssh` (Windows OpenSSH itself tolerates it, which is why interactive ssh works and git does not). **Therefore `desktop-ts` cannot fetch or push anything over ssh until that BOM is removed.**
- No GitHub credential is present for `git` (all `https://github.com/...` `ls-remote` calls return FAIL with an empty message under `GIT_TERMINAL_PROMPT=0`).

**Working repositories (19):**

| path | branch@HEAD | dirty M/U | unique-tip br | stash | remotes (state) |
|---|---|---|---|---|---|
| `Code\harness-config` | `main@512a7fb0` | 12 M / 16 U (ahead **4**, behind **22** of `origin/main`) | 1 | **4** | `origin`=`secretary-ts:...harness-config.git`, `mirror`=`linux-pc:...mirror.git` — **both FAIL (BOM)** |
| `Code\phone-and-tech-full` | `test`-lineage, many | 0 | **~150** | 1 | `origin`=GitHub (**FAIL**), `old-org`=`lakewoodphoneandtech/phone-and-tech-full` → **404 Repository not found**, `heroku*` → **no password** |
| `Code\personal-secretary-mvp` | `integrate/dialpad-reconcile-20261007` | 8 M / 41 U | **17** (`agent/w1..w6`, `fix/fleet-*`, `fix/proxy-auth`, `waze/usage-ledger`, …) | 1 | GitHub + `secratary` |
| `Code\lpt-hub` | `main` | 3 M / 9 U | 0 | 0 | GitHub (FAIL) |
| `Code\lpt-ops` | `main@7ac128ea` | 3 M / 9 U (1 ahead / 2 behind) | 1 | 0 | GitHub (FAIL) |
| `Code\mesh-security` | `main` | 1 M / 1 U | 1 (`secmesh-backup@e2e02e3f`) | 0 | local |
| `Code\reports` | `master@5cda3aaa` | 1 M | 1 | 0 | **none** |
| `Code\yitz-insurance-case` | `master@bd9e2cb6` | 0 | 1 | 0 | **none** |
| `Code\phone and tech revenue and ads` | `main` | 0 | 0 | 0 | – |
| `Code\personality-system` | `main` | 0 | 0 | 0 | – |
| `Code\chumash-timeline`, `ha-config`, `home`, `kosher-filter-ai`, `lpt-flip-phone`, `quickbooks-agent`, `tesla-lin-chip`, `xiao-lin-bench`, `yitzchak-zabrowsky`, `tools\edl_tool`, `tools\edl_tool\Loaders_temp` | various | 0–2 | 0 | 0 | GitHub/third-party (FAIL) |
| `Code\lpt-hub\tmp\android_kernel_kyocera_afp`, `tmp\edl` | `master` | 0 | 0 | 0 | third-party |

**Scratch / throwaway repositories (24)** — each cheap to lose, listed so nothing is invisible: `_fc\fleet`, `_kx\kosher-filter-ai`, `AppData\Local\Temp\gt`, `_archive\personality test`, `_audit-20261007\scratch\hc`, `_autonomy-audit\extracted\ceo-kernel`, `_cfo-fleet\{ws3,ws4,ws8}`, `_customer-plane-build\lpt-hub`, `_fleet\{lpt-base,phone-and-tech-full}`, `personal-secretary-mvp\_scratch\{smartswitch-explorer,whatsapp-key-extractor}`, `hk367-proof\repo`, `hk367-ps-consumer-20261002T0900Z\{consumer,consumer-orig,mirror.git}`. Two of these are **not** throwaway — see R6.

Not deep-audited (depth > 5, all under `%TEMP%` / `_worktrees`): ~30 further `.git` directories from short-lived agent runs (`d1probe`, `ghpages-*`, `i367-*`, `pds287tmp`, `scratch-*`, `_worktrees\psm-w2|w3`). Settling command in §5.

### 1.E `laptop-ts` / `ZABZ-YOGA` — **NEW: 26 repositories in `C:\Users\ezabz\code`** (revision 1 left this UNKNOWN)

Per-repo read at 17:1xZ. The laptop also holds ~60 `harness-config\_scratch\autosync-verify-14*` fixture repos (bare+clone+seed triples); counted, not enumerated.

| path (`C:\Users\ezabz\code\…`) | branch@HEAD | branches | stashes | dirty | remotes |
|---|---|---|---|---|---|
| `harness-config` | `main@04459547` | **36** | **5** | 50 | `origin`=`secretary-ts:...harness-config.git` (OK) **and** GitHub; `offsite`=`https://github.com/lakewoodphone/harness-config.git` (OK) — **this is the only host that can still reach the GitHub mirror** |
| `phone-and-tech` | `docs/ux-simplification-v2-decisions@50e33fd17` | **284** | **15** | 0 | GitHub (46 ahead of upstream) |
| `phone-and-tech-full` | `fix/card-data-scrub-20261009@3de71d18d` | **215** | 0 | 17 | GitHub |
| `personal-secretary-mvp` | `fix/mcp-launcher-never-die-on-log-write@fc65be23d` | **44** | **3** | 53 | GitHub |
| `kosher-filter-ai` | `kf1005/postgres-job-timeout@492e89c` | 47 | 0 | 0 | GitHub |
| `ha-config` | `main@39f1369` | 7 | 0 | 0 | GitHub (14 ahead / 17 behind) |
| `lpt-hub` | `main@a463a2387` | 3 | **3** | 9 | GitHub (2 ahead) |
| `lpt-books` | `master@2b63bc5` | 12 | 0 | 1 | `authority` (no upstream) |
| `"personality test"` | `integrate/identity-staging@56847e6` | 12 | 0 | **165** | GitHub |
| `research` | `master@7c3e7a4` | 1 | 0 | 26 | GitHub |
| `lpt-schematics` | `main@8db2773` | 1 | 0 | 17 | GitHub |
| `lpt-ops` | `main@77ff93e` | 1 | 0 | 1 | GitHub (7 ahead) |
| `unified-search` | `main@e4b9d46` | 9 | 0 | 0 | GitHub |
| `ceo-kernel` | `main@51dc851` | 1 | 0 | 0 | `origin` (1 ahead / 25 behind) |
| `noson-yanofsky-profile` | `main@1d489a0` | 1 | 0 | 0 | `origin` — **mirrors the authority's "remote-less" bare repo** |
| `book`, `chumash-timeline`, `halacha`, `home`, `lpt-flip-phone`, `personality-test-db-backups`, `quickbooks-agent`, `tesla-lin-chip`, `tutor`, `xiao-lin-bench`, `yocheved-staging` | various | 1–2 | 0 | 0–2 | GitHub |

Laptop `harness-config` stashes: `stash@{0} coordinator-presync-20261011-2155`, `{1} autostash`, `{2} session-churn: journal index + archive script (restored after rebase)`, `{3} WIP on master: 1b325f0 journal: in-flight …`, `{4} On master: wip-before-rebase`. Local branches that matter: `backup-main-20261008T0130@f38366f` (= the GitHub mirror tip the authority tracks as `ghprobe/main`), `meshfix/mfx-broker@1b921d70` (= the "converge all three journal lineages" base), `alloc/zabz-yoga@1245e54d`, `migration/pre-trunk-ZABZ-YOGA`, `zabz-yoga-local-preserve-20260915`.

### 1.F `lpt-apps` / `lpt-apps-01` — 6 repos

Re-measured 16:41Z.

| path | kind | branch@sha | dirty | br | unique-tip br | stash | remotes |
|---|---|---|---|---|---|---|---|
| `/srv/git/harness-config.git` | **BARE (= the vault)** | `main@a692ecd8` | – | 1 | 1 | 0 | **none** |
| `/opt/lpt/src` | worktree | **UNBORN — 0 commits, 0 objects** | 0 M / 75,282 U (incl. `.pnpm-store`) | 0 | n/a | 0 | `origin`=`lakewoodphoneandtech/phone-and-tech-full` → **404, ls-remote FAIL** |
| `/opt/lpt-test/src` | worktree | `test@d39c7750` | 0 M / 1 U (`jwt.ts.bak-jti`) | 2 | 0 | **2** (`c17bb9f7` in no ref; `23e749ab` in no ref) | GitHub OK |
| `/opt/chumash-timeline` | worktree | `main@375a1e7a` | clean | 1 | 0 | **1** (`bd12b0c2`, `docker-compose.yml` +22/−17, in no ref) | GitHub OK |
| `/opt/personality-test` | worktree | detached | clean | 1 | 0 | 0 | GitHub OK; **91 dangling blobs** |
| `/opt/personality-test-test/src` | worktree | detached | clean | 2 | 0 | 0 | GitHub OK |

### 1.G `survivor` / `lpt-survivor-01` — 1 repo (**missed by revision 1**)

| path | kind | branch@sha | dirty | br | stashes | remotes |
|---|---|---|---|---|---|---|
| `/opt/company` | worktree (owner `company:company`) | `feat/owner-text-gate@52dc8b0a` | 3 M / 13 U | 1 | 0 | `origin`=GitHub `lakewoodphone/personal-secretary-mvp` with **a PAT embedded in the URL** (redacted; rotate) |

`find / -xdev -maxdepth 9` found **no other repository** on this host; `/srv` and `/opt` hold only the company tree and `/backups`. This is a **third live copy of the production application** and it is on a non-default branch.

---

## 2. Items at risk, ranked (each exists in exactly one place)

"One place" = one machine + one repo + one ref. Nothing here was preserved by this audit; the commands are for a human or the owner to run. **24 ranked items; 16 of them are the single-copy subset.**

**R1 — `secratary-cloud:/opt/company` — 9 files / 3,890 lines of LIVE code in no git ref (was 8 / 3,539 at 16:20Z).** Re-verified 16:43Z by hashing each working file and testing membership in `git rev-list --all --objects`:
`app/owner_question_dedupe.py` (351), `scripts/dialpad-recording-gap.py` (262, cron */5), `scripts/dialpad-transcript-gap.py` (273, cron */10), `scripts/ps_mcp_server.py` (864 — **three running processes**: PIDs 1474, 1789, 14441 `/opt/company/.venv/bin/python /opt/company/scripts/ps_mcp_server.py`), `scripts/server/backup-data.sh` (193), `tests/test_smart_router.py` (1174), `tests/test_utility_roles.py` (226), `tests/test_board_seat_goal_coverage.py` (268), `tests/test_lane_health_gate.py` (279).
**The 9th file is new since revision 1**: `app/owner_question_dedupe.py` was edited at ~16:11Z (`app/owner_question_dedupe.py.bak-sqliteprefix-20261012T161113Z` sits beside it) and its working blob `e7cca1fb` is now in no ref.
*Preserve:* `git -C /opt/company stash push -u -m "audit-preserve-$(date -u +%Y%m%dT%H%M%SZ)"` — or better, because the service keeps running: `git -C /opt/company checkout -b preserve/live-$(date -u +%Y%m%dT%H%M%SZ) && git -C /opt/company add -A && git -C /opt/company commit -m preserve-live && git -C /opt/company push origin HEAD`.

**R2 — `secratary-ts:/home/zabz/personal-secretary-mvp` — 33 stashes, none reachable from any ref, office-only, 39 GB repo.** [v1 measured `stash list` = 33 and `for-each-ref --contains` empty for `{0}…{4}`; v2 re-read 33.] Largest `stash@{25}` = 137 files, +39,367/−3,781; `stash@{0}` 15 files +2,981; `stash@{1}` 35 files +5,858; only `stash@{27}` is empty.
*Preserve:* `git -C /home/zabz/personal-secretary-mvp bundle create /safe/psm-stashes.bundle refs/stash`.

**R3 — `secratary-ts:/home/zabz/harness-config.git` — bare hub, 97 branches, 25 with tips in no other ref, NO remote.** Re-verified 16:44Z (`master@1245e54d`, 391 MB, fsck dangling = 1). Biggest carriers [v1]: `fix/mesh-provider-dispatch` 44 unique commits, `hk/367-mirror-propagation` 40, `zabz-audit-20260914-r25` 29, `main` 15, `agent/roadmap-supply-kosher` 15, `zabz-audit-20260914` 9, `master` 2.
*Preserve:* `git clone --mirror /home/zabz/harness-config.git /safe/harness-config.git` (or `git -C … bundle create /safe/office-hc.bundle --all`).

**R4 — `harness-config` is not three divergent lineages, it is SIX, and they are still diverging.** Measured 16:41–17:1xZ:

| lineage | tip | relation |
|---|---|---|
| authority/vault | `secratary-cloud main d05105f9`; vault `a692ecd8` | **canonical trunk**, 1 publish behind, 73 ahead of the bundle |
| office bare | `secratary-ts harness-config.git master 1245e54d`, 97 branches | no remote at all |
| office worktree | `secratary-ts code/harness-config main f1713ce1` | 16 branches, 3 unique, 38 dirty |
| linux-pc worktree | `zabz-tech-linux main d5621aa2` | 3 unique tips + 1 unique stash |
| **ZABZ-TECH worktree** | `main 512a7fb0` | **4 ahead / 22 behind its own origin (the office bare)**; 4 stashes |
| **ZABZ-YOGA worktree** | `main 04459547` | **same SHA as the office bare's `main`**; 36 branches, 5 stashes, 50 dirty; the only host that can still reach the GitHub mirror |
| GitHub mirror | `f38366f` (`offsite/main`, `ghprobe/main`, laptop `backup-main-20261008T0130`) | 2 commits that are in no vault/bare lineage; recoverable from the laptop |

Cross-machine ancestry still cannot be proven without a fetch (the objects are not co-located). **Merge is NOT a fast-forward in any direction**, and both sides journal-autocommit the same index files, so a merge will conflict on `journal/index/entries.tsv`, `journal/index/journal.db`, `journal/index/stamp.json`.
*Preserve / settle:* `git -C <repo> fetch --all` (a fetch, not a merge) into a scratch clone, then `git merge-base --is-ancestor <a> <b>` for every pair above; the convergence base `1b921d70` lives on the office/local side and is carried by the laptop as `meshfix/mfx-broker`.

**R5 — `desktop-ts:Code\phone-and-tech-full` carries roughly 150 branch tips that exist in no reachable ref. Its only non-GitHub remote `old-org` is dead (`remote: Repository not found`, `lakewoodphoneandtech/phone-and-tech-full`), and `origin` cannot be reached from this box at all (BOM defect + no credential).** This is the largest single concentration of unique work found. Examples: `guardian/*` (≈25 branches), `copilot/ai-workspace-*` (≈20), `rescue/postcss-8.5.10-clean@101ef670`, `rescue/pr9293-pricing-walkthrough-v2@d7092338`, `rescue/pr9313-decision-docs@589ca076`, `rescue/pr9374-customer-notes@af8e64b6`, `wip/passcode-encryption@40654675`, `wip/waze-bridge-cherrypicks@1d0d20a9`, `secretary-orphan-decisions-2026-04-23@ac391897`, `fix/portal-ui-robustness@b82d9c2e`, `promote/test-to-main-2026-05-25@ae37faa9`.
*Preserve:* `git -C "C:\Users\ezabz\Code\phone-and-tech-full" bundle create C:\backup\ptf-all.bundle --all` then copy the bundle off-box. **Do not prune `old-org/*` remote-tracking refs first — they are the only map back to the branch names.**

**R6 — `desktop-ts:mesh-n\wt` and `mesh-n\applytest` — uncommitted plugin work in no ref.** `mesh-n\wt` `master@84c26b23` has 5 modified files (`packages/plugin-remote-fanout/lib/{index,provider,remote-script}.js`, `test/{provider,remote-script}.test.mjs`) plus `packages/mesh-broker/nodes.json`; `mesh-n\applytest` is a detached worktree with **24 untracked files** that are the whole `plugin-remote-fanout` package (`lib/{broker-client,index,nodes,placement,pressure,provider,remote-script,ssh-transport}.js`, `bin/mesh-{run,placement-proof,pressure,pressure-proof}.mjs`, tests, `package.json`, `cordis.patch.yml`). They exist on this desktop and nowhere else.
*Preserve:* `git -C C:\Users\ezabz\mesh-n\wt stash push -u -m audit-preserve-<ts>` and `robocopy C:\Users\ezabz\mesh-n\applytest C:\backup\mesh-n-applytest /E`.

**R7 — `laptop-ts:code\phone-and-tech` — 284 branches and 15 stashes, one copy, home network.** Also `phone-and-tech-full` 215 branches / 17 dirty, `personal-secretary-mvp` 44 branches / 3 stashes / 53 dirty, `kosher-filter-ai` 47 branches, `"personality test"` 165 dirty, `research` 26 dirty, `lpt-schematics` 17 dirty.
*Preserve:* `git -C C:\Users\ezabz\code\phone-and-tech bundle create C:\backup\pt.bundle --all refs/stash` and the same for the other four; copy the bundles off the laptop.

**R8 — `lpt-apps:/opt/lpt/src` — UNBORN repository, 0 commits, 14 real source trees untracked, remote 404.** *Preserve:* `tar czf /safe/lpt-src-$(date -u +%Y%m%dT%H%M%SZ).tgz -C /opt/lpt/src backend frontend packages python-printer-service shared package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json turbo.json`.

**R9 — `secratary-ts:/home/zabz/mesh-security.git` — bare, `main@09fd362f`, 19 unique commits, no remote.** *Preserve:* `git clone --mirror /home/zabz/mesh-security.git /safe/mesh-security.git`.

**R10 — `secratary-ts:/home/zabz/bin.git` — bare, `master@f08a5c4`, 41 branches, 13 with tips in no other ref, no remote** (`fix/integrator-artifact-only-debt-i567`, `hk/147-sentinel-supply`, `hk/151-wake-single-writer`, `hk/153-cache-telemetry`, `hk/238-delivered-sms-count`, `hk/585-ghost-record-lost-20261010T0150Z`, `hk/633-verify-backoff-loaded`, `lpt-sync/357-tmp-hygiene-consumers`, `lpt-sync/358-tmp-hygiene-sqlite-artifacts`, `shift/214-claimnext-due-blocks`, `shift/lpt274-rebase-preflight`, `hk/20261001-i174-outcomes`, `hk/20261001-i184-cap-cost`). Parent worktree `/home/zabz/bin` adds 254 untracked files. *Preserve:* `git clone --mirror /home/zabz/bin.git /safe/bin.git` + `rsync -a /home/zabz/bin/ /safe/bin/`.

**R11 — `secratary-ts:/home/zabz/phone/yitz-insurance-2026-10-06`** — 70 dirty entries, `master` has unique commits, **no remote**. *Preserve:* `git -C … bundle create /safe/yitz.bundle --all` + `rsync` of the worktree.

**R12 — `secratary-ts:/home/zabz/code/unified-search`** — unique commits whose only other copy was `/tmp/unified-search.bundle`, now gone (`ls-remote origin` fails). *Preserve:* `git -C … bundle create /safe/unified-search.bundle --all`.

**R13 — `secratary-ts:/home/zabz/repos/kosher-filter-ai`** — one unreachable non-empty stash (`stash@{0}`, "WinDivert licensing decision (owner-queue #139)", +4/−1) [v1] plus one unique branch. *Preserve:* `git -C … bundle create /safe/kosher.bundle --all refs/stash`.

**R14 — `lpt-apps:/opt/lpt-test/src`** — `stash@{0}` `c17bb9f7` and `stash@{1}` `23e749ab` (Dockerfile.production) in no ref, plus 2 dangling commits `655655b9e0`, `fbb276eea1`. *Preserve:* `git -C /opt/lpt-test/src branch preserve/stash0 c17bb9f7` and `… preserve/stash1 23e749ab`.

**R15 — `lpt-apps:/opt/chumash-timeline` `stash@{0}` `bd12b0c2`** (`docker-compose.yml` +22/−17), in no ref. *Preserve:* `git -C /opt/chumash-timeline branch preserve/stash0 bd12b0c2`.

**R16 — `linux-pc-ts:~/code/harness-config`** — stash `presync-bench-20261011-2226` (6 files, +629) in no ref; `meshfix/mfx-provider` and `meshfix/mfx-transport` are unique local branches the office hub does not have. *Preserve:* `git -C ~/code/harness-config bundle create /safe/lpc-hc.bundle --all refs/stash` and push both `meshfix/*` branches to a mirror.

**R17 — `desktop-ts:Code\personal-secretary-mvp`** — 17 branches with tips in no other ref, 8 modified / 41 untracked files, and one stash (`764835d7`, "churn while landing backfill fix 2026-10-07", 12 files +14,407/−12,263) that is in no ref. The box cannot reach GitHub or its `secratary` remote. *Preserve:* `git -C C:\Users\ezabz\Code\personal-secretary-mvp bundle create C:\backup\psm-desktop.bundle --all refs/stash`.

**R18 — `desktop-ts` repos with no remote at all**: `Code\reports` (`master@5cda3aaa`, 1 modified `lpt-overhaul/LPT-WEBSITE-AND-ACCOUNT-OVERHAUL-MASTER.md`), `Code\yitz-insurance-case` (`master@bd9e2cb6`). *Preserve:* bundle both (`--all`) to `C:\backup\`.

**R19 — `desktop-ts:hk367-ps-consumer-20261002T0900Z\mirror.git`** — bare `master@f1b1b5c7` in no other ref, and its `consumer` worktree is 3 ahead of a `origin` that points at `file:///C:/NONEXISTENT-secratary/harness-config.git`. *Preserve:* `git --git-dir=… bundle create C:\backup\hk367-mirror.bundle --all`.

**R20 — `desktop-ts:Code\mesh-security` branch `secmesh-backup@e2e02e3f`** and `Code\lpt-ops` `main@7ac128ea` (1 ahead of GitHub) — unique tips on a host that cannot push. *Preserve:* bundle `--all`.

**R21 — the stale bundle `secratary-cloud:/root/hc-main.bundle`** is itself the only copy of `ee3a7e2f`'s position *as a ref*, but its content is 73 commits behind the authority's own `main`, so it is a backup of nothing current. Do not "fix" it by force-updating; re-create it after R4 is resolved.

**R22 — `secratary-cloud:/opt/company/archive/` — 9.0 GB / 46,963 untracked transcript objects, not gitignored, no copy on `lpt-apps`.** (Was 6.3 GB / 46,897 at 16:20Z — it is growing.) *Preserve (owner chooses destination):* `rsync -a /opt/company/archive/ lpt-apps:/srv/backups/company-archive/`.

**R23 — `secratary-ts` bares with unique commits but mirrored tips**: `ceo-kernel.git` (`hk/item231-kernel-gitignore-20261008`), `home.git` (`main`, 86 commits, tip mirrored in `code/home`), `repos/halacha.git` (`master`, mirrored), `harness-config.pre-unify-20260922` and `hc-fork-lab-20260917T033457Z` (`journal-migration-20260915`). *Preserve:* one `git clone --mirror` per repo to `/safe/`.

**R24 — `survivor:/opt/company`** — `feat/owner-text-gate@52dc8b0a`, 3 modified (`app/main.py`, `deploy/hosting-migration/scripts/company-dns-failover.py`, `company-promote.py`) + 13 untracked (`.cache/`, `.mem0/`, `data/.seed-stamp`, `data/leadership.json`). The standby is *ahead of or equal to* nothing in particular and nobody knows which copy the failover would use. *Preserve:* `git -C /opt/company bundle create /root/survivor-company.bundle --all` + `tar czf /root/survivor-untracked.tgz data/leadership.json .mem0`.

**Security findings (not git-work loss, but data risk):** a GitHub PAT is embedded in `survivor:/opt/company/.git/config` (`origin` URL, redacted here); `/root/.git-credentials` on the authority holds GitHub PATs in plaintext [v1]; `/opt/company/postgres:/ueohoi…:pba408…@…rds.amazonaws.com:5432/…` is a **directory name containing a live-looking Postgres DSN** (still present 16:43Z). **Rotate, do not merely delete.**

---

## 3. Junk candidates (recommend, never delete)

* **`desktop-ts` — the single biggest cleanup win.** ~30 `.git` trees under `%TEMP%` / `_worktrees` from one-off agent runs; the `_cfo-fleet\{ws3,ws4,ws8}`, `_fc\fleet`, `_fleet\*`, `_audit-20261007\scratch\hc`, `AppData\Local\Temp\gt` scratch clones; `Code\personal-secretary-mvp\_scratch\*`; `hk367-*` experiment trees. Also the 4 `diverged-ZABX-*`-style remote-tracking families that exist only in the office ZABZ-TECH refs (`diverged-ZABZ-YOGA-2026091[5-9]`, `diverged-secratary-2026*`) — keep one per date only after R3/R4 are rescued.
* **`desktop-ts:Code\phone-and-tech-full`** — `heroku`, `heroku-prod`, `heroku-test` remotes (`fatal: unable to get password from user`), the dead `old-org` remote, and 869 dangling objects (868 commits/trees/blobs listed at degree 1; 325 prune-packable).
* **`desktop-ts:Code\harness-config`** — stale `diverged-*` remote-tracking refs, `meshfix/*` branches all pointing at the same commit `ccb7eac6`, and 4 stashes (one is `autostash`).
* **`secratary-ts`** — `bin`'s 254 untracked files are overwhelmingly `*.bak-*`; fully-merged branch sets (all 33 `lpt-hub`, all 54 `phone-and-tech-full`, all 8 `quickbooks-agent`, all 8 `personality-test`, 98/99 `personal-secretary-mvp`); `personal-secretary-mvp stash@{27}` (empty); the `tmp-rescue-20261002` and `.pytest-tmp-next` fixture trees; dangling blobs (272/204/143/81/31).
* **`lpt-apps`** — `/opt/lpt/src/node_modules` (1.4 GB) and `.pnpm-store` (1.2 GB) are regenerable and should be gitignored; `/opt/personality-test` has 91 dangling blobs from repeated detached checkouts; many `*.bak-*` / `*.sql` / `*.dump` under `/root`.
* **`linux-pc-ts`** — `hk367-consumer-autosync-…` has an `origin` literally named `NONEXISTENT-secratary`; `~/work/ceo-kernel` points at a bundle that is not on that host; `mtkclient` and `edl` are third-party clones; `harness-config` has `garbage: 1` (57 KB) and 16 prune-packable.
* **`secratary-cloud:/opt/company`** — 7 untracked `.env*` backups, 8 `data/crontab.bak-*`, `*.db-shm`/`*.db-wal`, `scripts/*.py.bak-*`, the literal `postgres:` credential directory, and the nested 207 MB `data/harness-config.bak-20260915T0200Z` clone. Four `chip/2026-10-12-*` branches are fully merged into `master`. `archive/` should be gitignored **only after** R22 is copied off-box.
* **Committed-but-junk inside HEAD trees was not inspected** (`.bak`, `.pyc`, `node_modules`). Settle with `git ls-files | grep -Ei '\.bak|\.pyc|node_modules|__pycache__'` per repo.

---

## 4. Reconciliation plan (ordered and safe — nothing below was executed by this audit)

**Phase 0 — capture, before touching anything.** Run every "Preserve" command in §2 first. Write the bundles to a host that is *not* the one holding the repo, and verify each bundle with `git bundle verify`. This phase is the no-loss guarantee; everything after it is reversible.

**Phase 1 — make every single-copy item exist in two places.**
1. `secratary-cloud`: snapshot the 9-file live residual (R1) as `preserve/live-<ts>` and push it to GitHub; `rsync` `archive/` (R22) to `lpt-apps:/srv/backups/`.
2. `secratary-ts`: mirror `harness-config.git` (R3), bundle the 33 `personal-secretary-mvp` stashes (R2), mirror `mesh-security.git` (R9), `bin.git` (R10), `repos/lpt-books.git`, and rescue the `yitz-insurance` / `unified-search` / `kosher` items (R11–R13). **The office box is FROZEN and has no vault credential — it cannot push. Copy off-box with `rsync`/`scp`, or have the owner run it.** Read-only aside: `GIT_OPTIONAL_LOCKS=0` was used so that even `git status` did not rewrite its index.
3. `desktop-ts`: **first remove the UTF-8 BOM from `C:\Users\ezabz\.ssh\config` line 1** — until that is done this box can push nothing. Then bundle `phone-and-tech-full` (R5) and the two `mesh-n` trees (R6), `personal-secretary-mvp` (R17), `reports`/`yitz-insurance-case` (R18), `hk367-*` (R19), `mesh-security`/`lpt-ops` (R20). Copy the bundles to `lpt-apps` or the authority (they can be pushed from there).
4. `laptop-ts`: bundle `phone-and-tech`, `phone-and-tech-full`, `personal-secretary-mvp`, `kosher-filter-ai`, `"personality test"`, `research`, `lpt-schematics` (R7) and the 5 `harness-config` stashes; copy off-box. The laptop is the **only** host that can still `ls-remote` the GitHub harness-config mirror, so use it to re-seed that mirror if the owner wants it kept.
5. `lpt-apps`: bundle `/opt/lpt/src` (R8) and the `lpt-test`/`chumash` stashes (R14, R15).
6. `linux-pc-ts`: bundle the harness-config stash and land the two `meshfix/*` branches (R16).
7. `secratary-cloud`: bundle the noson bare repo (though the laptop now mirrors it); re-create `hc-main.bundle` only **after** Phase 2.

**Phase 2 — reconcile the six `harness-config` lineages (needs a reviewer; NOT a fast-forward anywhere).**
- Canonical trunk = **authority → vault** (`secratary-cloud main` → `lpt-apps:/srv/git/harness-config.git`), because the 15-minute `journal-commit` publishes to it. The vault is exactly 1 commit behind at 16:41Z; the `/root/hc-main.bundle` "origin" is 73 behind and must not be treated as a source.
- Do the merge in a scratch clone with `git fetch --all` from the office bare, the linux-pc mirror, the desktop `Code\harness-config`, the laptop `code\harness-config` and the GitHub mirror. Then `git merge-base --is-ancestor` every pair; expect **conflicts on the journal index** (`journal/index/entries.tsv`, `journal/index/journal.db`, `journal/index/stamp.json`) because both sides autocommit them. Resolve the index by **regeneration, never by force-push**.
- The convergence base `1b921d70` ("converge all three journal lineages: master, the authority, and ZABZ-TECH") exists on the office/local/laptop side and **not** on the authority. It is carried by the laptop as `meshfix/mfx-broker` and by `linux-pc:~/harness-config-mirror.git` as `master`.
- The office worktree `f1713ce1` must be reconciled with the office bare first; its 3 unique branches (R13-adjacent, listed in §1.B) need landing.
- **ZABZ-TECH is ahead 4 / behind 22 of the office bare**: its 4 commits are doc commits 187/185/184/181 whose *content* already exists on the authority with different SHAs — cherry-pick equivalence must be established before merging, or the same doc will land twice.
- **Preserve `ghprobe/main f38366f` (2 commits) from the laptop's `backup-main-20261008T0130` before re-pointing or deleting that ref anywhere.**

**Phase 3 — `/opt/company` convergence (needs the owner/reviewer).** `master` is at `98c0595b` (2 commits ahead of GitHub, moved since v1's `adecfd56`); the preserve branch `42109f4a` is pushed and its tree (`6f7ed623`) is **not** `master`'s tree (`a48934d1`). Of the 33 modified tracked files, 24 have working content that exists in *some* older ref (so the running service is on an older version than `master`) and 9 exist in none (R1). Decide the canonical side (presumably the running tree), then land it deliberately. Never `reset --hard`.

**Phase 4 — stale artifacts and credentials.** Retire the stale bundles (`hc-main.bundle`, `psm-master.bundle`, the nested 207 MB backup), rotate the leaked GitHub PATs and the Postgres DSN directory name, then delete only with a second confirmation.

**Needs a reviewer:** Phase 2 (six-lineage merge, conflicting journal indexes), Phase 3 (which `/opt/company` version production runs), any `stash branch` that rewrites an index.
**Needs the owner:** credential rotation; the `archive/` destination; confirming the canonical lineage; authorising the frozen office box to be copied off-box; deciding whether the GitHub harness-config mirror stays.

---

## 5. What could NOT be reached or could NOT be established

* **`mac-mini-ts` (`LakewooechsMini`) — UNKNOWN, never "clean".** `ssh mac-mini-ts` and `ssh mac-mini-ts-ip` (100.126.146.121) both return `Connection timed out` from `ZABZ-TECH` at 16:39Z. Settle: bring it on the tailnet, then `ssh mac-mini-ts 'hostname; git --version'`, then run the same per-repo read.
* **`laptop-ts` is only partially established.** It answers short commands, but a single long PowerShell enumeration **dropped the session** (`Timeout, server zabz-yoga-1.tail93e6e6.ts.net not responding`) and a UTF-8 script file returned empty output with exit 0. The inventory in §1.E is real (per-repo `git` reads) but **per-branch unique-commit counts and fsck were not run on the laptop** — the 284/215/44-branch counts are branch *labels*, only the tip test was applied where noted. Settle per repo: `git -C <path> for-each-ref --contains <sha> --format='%(refname)'` and `git fsck --no-progress`.
* **`desktop-ts` below depth 5 was not audited**: ~30 `.git` trees under `%TEMP%` and `_worktrees` were identified by name but not opened. Settle: `Get-ChildItem $env:TEMP,$env:USERPROFILE\Code\_worktrees -Recurse -Depth 8 -Directory -Force | Where-Object Name -eq '.git'` then the per-repo read.
* **`desktop-ts` and `laptop-ts` push capability is UNPROVEN and, on the desktop, proven broken.** `git ls-remote` failed for every remote on `desktop-ts` (BOM in `~/.ssh/config`; no GitHub credential). On the laptop, GitHub and the office bare both answer; the **vault credential was never tested** — settle with `git -C C:\Users\ezabz\code\harness-config ls-remote root@2.28.33.58:/srv/git/harness-config.git`.
* **`mac-mini-ts`, and therefore the whole "may be unreachable" column of the fleet, is not measured at all.**
* **Cross-machine ancestry of `harness-config` and of `/opt/company` cannot be proven without a fetch** (objects are not co-located). Settle on a scratch clone: `git fetch --all && git merge-base --is-ancestor <sha> <sha>` for every pair in R4.
* **fsck was skipped on `secratary-ts` in revision 2** — the v1 full run took >20 minutes and the office box is frozen, so re-running 37 fsck passes over a 39 GB repo was judged unacceptable load. v1's dangling counts stand; v2 ran a light pass only.
* **`archive/` (9.0 GB) was not compared byte-for-byte to any backup**; no copy was found on `lpt-apps` under `/srv`.
* **Committed-but-junk files inside HEAD trees, non-`origin` remotes (`delivery`, `authority`, `yoga`, `heroku*`, `offsite`) and stash *contents* beyond the top two changed files were not fully enumerated.** Settle per repo with `git stash show --stat <ref>`, `git ls-files | grep -Ei '\.bak|\.pyc'` and `git remote -v`.

---

## 6. Exact command set used (so the next audit is reproducible, not re-derived)

```
# Linux hosts — every call carried these two guards
export GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0
git -c "safe.directory=*" -C <path> …      # survives dubious-ownership refusals
git --git-dir=<bare.git> -c "safe.directory=*" …

# discovery
find /root /opt /srv /home /var/www /data /mnt /usr/local/src /var/git \
     -maxdepth 6 -type d \( -name .git -o -name '*.git' \) 2>/dev/null | sort -u
# status without noise
git -C <p> status --porcelain --untracked-files=all | grep -vE '__pycache__|node_modules|\.venv|\.pnpm-store|\.cache/'
# "does this branch tip exist anywhere else?"
git -C <p> for-each-ref --contains <sha> --format='%(refname)'
# "is this working blob in any ref?"
git -C <p> hash-object --path=<f> -- <f>    # then membership in: git rev-list --all --objects | cut -c1-40
# dangling, read-only, with no --lost-found
git -C <p> fsck --no-progress ; git -C <p> count-objects -v
# remote reachability (read-only; no fetch)
git -C <p> ls-remote --heads <remote>

# Windows hosts (fed to `ssh <host> "powershell -NoProfile -Command -"`, file must be ASCII)
git -c safe.directory=* -C <path> status --porcelain --untracked-files=all
```

*End of audit. Read-only on every audited machine; the only durable writes are this document and its commit.*
