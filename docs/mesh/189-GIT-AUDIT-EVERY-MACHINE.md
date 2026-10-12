# 189 — GIT AUDIT: EVERY MACHINE

**Audit time:** 2026-10-12, ~16:10–16:45 UTC.
**Auditor:** DSH child agent (mesh thread `remote-c48005c6-db47-4153-bb69-e0b475d8b0bb`).
**Execution host:** `zabz-tech-linux` (alias `linux-pc-ts`, tailscale `100.105.248.90`) — **not** the cloud authority.
**Posture:** strictly READ-ONLY on every audited machine. No `fetch`, `push`, `commit`, `merge`, `stash`, `branch`, `reset`, `clean`, `gc`, `prune`, or delete was run against any audited repository. The only write is this document and its commit on `secratary-cloud`.

> **Moving target note.** On the authority, `/root/code/harness-config` has a `journal-commit` cron that autocommits and pushes to the vault every 15 minutes. Its `main` SHA therefore advances during the audit (`1a5c2fe` → `31c650a` → `0ba429d`). SHAs below are labelled with the moment they were read.

## 0. Machines and reachability

| alias | hostname / IP | reached? | how | notes |
|---|---|---|---|---|
| `secratary-cloud` | `secratary-cloud` / 178.156.194.1 | YES | `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` (the alias `secratary-cloud` itself is **not** in `~/.ssh/config`; default user/key fails) | the authority; root |
| `secratary-ts` | `secratary` | YES | `ssh secratary-ts` (user zabz) | **FROZEN office box — touched read-only** |
| `desktop-ts` | `ZABZ-TECH` | YES | `ssh desktop-ts` (Windows, user ezabz) | audit delegated; see §1.D |
| `laptop-ts` | `ZABZ-YOGA` | YES | `ssh laptop-ts` (Windows, user ezabz) | audit delegated; see §1.D |
| `linux-pc-ts` | `zabz-tech-linux` | YES (local) | local shell (user zabz) | the execution host |
| `mac-mini-ts` | `LakewooechsMini` | **NO** | tailscale `Connection timed out`; LAN `192.168.50.45` `No route to host`; `tailscale status` says `offline, last seen 2m ago` | **UNKNOWN, never "clean"** |
| `lpt-apps` | `lpt-apps-01` / 2.28.33.58 | YES | `ssh lpt-apps` (root) | Caddy front door / vault |
| `survivor` | `lpt-survivor-01` / 2.31.18.142 | YES | `ssh -i ~/.ssh/id_ed25519_hetzner root@2.31.18.142` (alias `survivor` does not resolve) | Hetzner standby |

**Noise excluded from untracked/status counts (and stated here):** `__pycache__`, `node_modules`, `.pnpm-store`, `.cache`, `.pytest-tmp-next`, `tmp-rescue-20261002`, `wt-562`/`wt-563`, and on `secratary-ts` 40 pytest/scratch fixture repos (0 bare). On `secratary-cloud:/opt/company`, the directory `archive/lpt-transcripts/` (46,897 untracked files, 6.3 GB) was **not** enumerated file-by-file; it is reported as one data item.

**Read commands are cited inline. `git fsck` was run as `git fsck --no-progress` (there is no `-q` flag; `-q` errors).**

---

## 1. Every repository found

### 1.A `secratary-cloud` — the authority (root)

| path | bare? | branch@HEAD | dirty (M/U) | local br | unique-work br | stashes | unique stashes | remotes |
|---|---|---|---|---|---|---|---|---|
| `/opt/company` | no | `master@adecfd56` | 32 M / 46 U (+46,897 under `archive/`) | 6 | 1 (`preserve/…42109f4a`) | 0 | 0 | `origin`=GitHub `lakewoodphone/personal-secretary-mvp` (ls-remote OK) |
| `/opt/company/data/harness-config.bak-20260915T0200Z` | no | `master@5f59cee` | 5 M / 2 U | 3 | 0 | 0 | 0 | `origin`=`/home/zabz/harness-config.git` (unreachable from cloud) |
| `/root/ceo-kernel` | no | `main@7be7fde` | 1 M / 1 U (`.runtime/`) | 1 | 0 | 0 | 0 | `origin`=`/root/kernel.bundle` (OK) |
| `/root/code/harness-config` | no | `main@0ba429d`* | 10 M / 10 U | 1 | 0 | 0 | 0 | `origin`=`/root/hc-main.bundle` (stale, `ee3a7e2`); `vault`=lpt-apps (OK) |
| `/root/code/unified-search` | no | `main@e4b9d46` | 0 / 0 | 1 | 0 | 0 | 0 | `origin`=`/root/repos/unified-search.git` (OK) |
| `/root/repos/noson-yanofsky-profile.git` | **BARE** | `main@1d489a0` | 0 / 0 | 1 | **1 (4 commits)** | 0 | 0 | **none** |
| `/root/repos/unified-search.git` | **BARE** | `main@e4b9d46` | 0 / 0 | 1 | 0 | 0 | 0 | none |

\* `main` moved during the audit (`31c650a` when the branch was first read, `0ba429d` at last read).

**Bundles on the same disk (not repos, but load-bearing "remotes"):** `/root/hc-main.bundle` (`main=ee3a7e2`, stale by 68 commits), `/root/kernel.bundle` (`main=7be7fde`), `/root/psm-master.bundle` (`origin/master=006cde5`, stale). There is no GitHub remote on the authority's harness-config.

### 1.B `secratary-ts` / `secratary` — FROZEN office box (read-only)

`find /root /opt /home /srv -maxdepth 6 -type d -name .git` and `-name '*.git'` found **37 real repos + 40 fixture repos** (fixtures excluded: `.pytest-tmp-next`, `tmp-rescue-20261002`, `wt-562`, `wt-563`, `owner-alert-build/pristine/.pytest-tmp-next`).

| path | bare | branch@sha | dirty M/U | #local br | #uniq br (uc>0) | #stash | remotes |
|---|---|---|---|---|---|---|---|
| `code/harness-config` | no | `main@f1713ce1` | 3/35 | 16 | 6 (3) | 0 | `origin`=`/home/zabz/harness-config.git` OK |
| `harness-config.git` | **YES** | `master@1245e54d` | 0/0 | **97** | 70 (25) | 0 | **none** |
| `bin` | no | `shift/traffic-eta-…@a53e10b` | 20/254 | 51 | 15 (11) | 0 | `origin`=local OK |
| `bin.git` | **YES** | `master@f08a5c4` | 0/0 | 41 | 39 (13) | 0 | none |
| `ceo-kernel` | no | `main@7be7fde` | 1/1 | 3 | 0 | 0 | local OK |
| `ceo-kernel.git` | **YES** | `main@c1f6082` | 0/0 | 4 | 4 (1) | 0 | none |
| `code/home` | no | `main@31e31aa` | 0/0 | 1 | 0 | 0 | `origin/authority` ssh OK |
| `home.git` | **YES** | (no HEAD) | 0/0 | 1 | 1 (86) | 0 | none |
| `code/lpt-ops` | no | `main@71813b6` | 2/1 | 2 | 2 (1) | 0 | GitHub OK |
| `code/unified-search` | no | `main@3d34c24` | 0/0 | 2 | 2 (1) | 0 | `origin=/tmp/unified-search.bundle` **FAIL** (bundle gone) |
| `mesh-security.git` | **YES** | `main@09fd362` | 0/0 | 1 | **1 (19)** | 0 | **none** |
| `lpt-books` | no | `ws8-automate-20261007@326a6ae` | 0/6 | 5 | 2 (1) | 0 | local OK |
| `repos/lpt-books.git` | **YES** | `master@3a2e75d` | 0/0 | 12 | 9 (3) | 0 | none |
| `repos/chumash-timeline` | no | `main@375a1e7` | 0/0 | 1 | 0 | 0 | GitHub OK |
| `repos/ha-config` | no | `main@24044a0` | 0/0 | 1 | 1 (0) | 0 | GitHub OK |
| `repos/halacha` | no | `master@840c99b` | 0/0 | 1 | 0 | 0 | local OK |
| `repos/halacha.git` | **YES** | `master@840c99b` | 0/0 | 1 | 1 (8) | 0 | none |
| `repos/kosher-filter-ai` | no | `kf530/ios-cascade-escalate-20261010@7983eaf` | 0/1 | 10 | 3 (1) | 1 | GitHub OK |
| `repos/kyocera-escalator` | no | `main@8a3314574` | 0/0 | 1 | 0 | 0 | GitHub OK |
| `repos/lpt-flip-phone` | no | `main@5ca50797` | 0/0 | 1 | 1 (0) | 0 | GitHub OK |
| `repos/lpt-hub` | no | `main@738d78f7f` | 0/8 | 33 | 2 (0) | 0 | GitHub OK |
| `repos/personality-test` | no | `agent/remove-dead-model-policy@887265a` | 0/0 | 8 | 2 (0) | 0 | GitHub OK |
| `repos/phone-and-tech-full` | no | `project-keepalive/item-466-husky-phantom-20261005@7734e1c88` | 1/0 | 54 | 44 (0) | 0 | GitHub OK |
| `repos/quickbooks-agent` | no | `fix/hk127-posted-date-fallback@430bcdf` | 1/0 | 8 | 1 (0) | 0 | GitHub OK |
| `repos/research-knowledge-base` | no | `master@7c3e7a4` | 0/0 | 1 | 0 | 0 | GitHub OK |
| `personal-secretary-mvp` | no | `hk/item642-gate-retry-after-20261010@26678993` | 7/55 | 99 | 1 (1) | **33** | GitHub OK; `delivery`=local |
| `phone/live-voice-dialer` | no | `main@0cc314f` | 0/0 | 1 | 0 | 0 | GitHub OK |
| `phone/yitz-insurance-2026-10-06` | no | `master@fe61463` | **68/2** | 1 | 1 (2) | 0 | **none** |
| `ha-config-live` | no | `main@cc41ea5` | 2/0 | 1 | 0 | 0 | GitHub OK |
| `ha-config-live.partial` | no | (empty) | 0/0 | 0 | 0 | 0 | none |
| `checkout-health-test` | no | `HEAD@e02538f` | 1/0 | 1 | 1 (0) | 0 | local OK |
| `_converge-all-20260930T170223Z` | no | `integrate/all-…@1b921d7` | 0/0 | 2 | 0 | 0 | local OK |
| `_converge-authority-20260930T161751Z` | no | `integrate/authority-master-…@3cd9f81` | 1/0 | 2 | 0 | 0 | local OK |
| `harness-config.bak-20260915T0200Z` | no | `master@5f59cee` | 5/2 | 3 | 0 | 0 | local OK |
| `harness-config.pre-unify-20260922` | no | `master@b7885ca` | 0/0 | 5 | 3 (1) | 0 | local OK |
| `hc-fork-lab-20260917T033457Z` | no | `reconcile/lab@4e5b947` | 0/0 | 5 | 2 (1) | 0 | local OK |
| `opt/actions-runner/_work/phone-and-tech-full/phone-and-tech-full` | no | `test@7734e1c88` | 0/0 | 1 | 0 | 0 | GitHub OK |

`#uniq br` = branches whose tip is in no other ref **or** which carry commits reachable from no other ref; `(n)` = those with `unique_commits>0` (substantive). fsck completed on all; dangling lines: `phone-and-tech` 272, `lpt-hub` 204, `actions-runner` 143, `personal-secretary-mvp` 81, `kosher-filter-ai` 31, office `code/harness-config` 19, `harness-config.pre-unify` 8.

### 1.C `linux-pc-ts` / `zabz-tech-linux` (local, executor)

| path | bare? | branch@HEAD | dirty M/U | local br | unique-work br | stashes | unique stashes | remotes |
|---|---|---|---|---|---|---|---|---|
| `~/code/harness-config` | no | `main@6d057fec` | 0/2 | 6 | 2 | 1 | **1** | `origin`=`secretary:/home/zabz/harness-config.git` OK; `mirror`=`~/harness-config-mirror.git` OK |
| `~/harness-config-mirror.git` | **BARE** | `master@1b921d70` | 0/0 | 1 | 0 | 0 | 0 | none |
| `~/work/ceo-kernel` | no | `main@7be7fde` | 0/1 | 1 | 0 | 0 | 0 | `origin`=`/root/kernel.bundle` **broken locally** |
| `~/personal-secretary-mvp` | no | `master@696e5e25` | 0/0 | 1 | 0 | 1 | 0 (empty) | GitHub OK (230 behind) |
| `~/mtkclient` | no | `main@a6a7147` | 0/1 | 1 | 0 | 0 | 0 | GitHub public (third-party, 20 behind) |
| `~/hk367-consumer` | no | `master` | 0/0 | 1 | 0 | 0 | 0 | `~/harness-config-mirror.git` |
| `~/hk367-consumer-autosync-20261002T0856Z` | no | `master` | 1/0 | 1 | **1** | 0 | 0 | `mirror` |
| `~/hk367-node2-20261002T0837Z` | no | `master` | 0/0 | 1 | 0 | 0 | 0 | `origin` |
| `~/edl_case/edl` | no | `master` | 2/0 | 1 | 0 | 0 | 0 | GitHub (third-party, 8 behind) |

`~/code/harness-config` unique local branches: `meshfix/mfx-provider` (`4f4d0145`, 2 unique commits), `meshfix/mfx-transport` (`b6b501d1`, 5 unique commits). Unique stash: `stash@{0}` `presync-bench-20261011-2226` (`a6463726`, 6 files, +629, reachable from **no** ref). `git count-objects -v` shows `garbage: 1` (57 KB) and 16 prune-packable.

### 1.D `desktop-ts` (ZABZ-TECH) and `laptop-ts` (ZABZ-YOGA) — Windows

**STATUS: audit in progress / not yet established at the time of writing.** Both hosts answer `ssh` and report `git version 2.52.0.windows.1`. A bounded repository scan was launched; a full `C:\` recursive scan times out (>60 s), so discoveries are limited to the scanned roots. **Until this section is filled in, treat Windows repo inventory as UNKNOWN, not clean.** Settling commands are in §5.

### 1.E `lpt-apps` / `lpt-apps-01` (root)

| path | bare? | branch@HEAD | dirty M/U | local br | unique-work br | stashes | unique stashes | remotes |
|---|---|---|---|---|---|---|---|---|
| `/opt/chumash-timeline` | no | `main@375a1e7` | 0/0 | 1 | 0 | 1 | **1** | GitHub OK |
| `/opt/lpt/src` | no | **UNBORN — 0 commits** | 0/14 | 0 | n/a | 0 | 0 | GitHub **404 / ls-remote FAIL** |
| `/opt/lpt-test/src` | no | `test@d39c775` | 0/1 | 2 | 0 | 2 | **2** | GitHub OK |
| `/opt/personality-test` | no | detached `e7ab460` | 0/0 | 1 | 0 | 0 | 0 | GitHub OK |
| `/opt/personality-test-test/src` | no | detached `56847e6` | 0/0 | 2 | 0 | 0 | 0 | GitHub OK |
| `/srv/git/harness-config.git` | **YES** | `main@1a5c2fe` | 0/0 | 1 | 1 | 0 | 0 | **none** (the vault) |

Dangling: `lpt-test/src` 2 commits + 1 tree; `personality-test` 91 blobs (no commits). No `/srv/backups`; **no copy of the authority `/opt/company` transcript archive was found here.**

### 1.F `survivor` / `lpt-survivor-01`

| path | bare? | branch@HEAD | dirty M/U | local br | unique-work br | stashes | remotes |
|---|---|---|---|---|---|---|---|
| `/opt/company` | no | `feat/owner-text-gate@52dc8b0` | 3 M / 4 U | 1 | 0 | 0 | `origin`=GitHub OK — **PAT embedded in remote URL** |

Dirty: `app/main.py`, `deploy/hosting-migration/scripts/company-dns-failover.py`, `.../company-promote.py`; untracked `.cache/`, `.mem0/`, `data/.seed-stamp`, `data/leadership.json`. Reflog = 1.

---

## 2. Items at risk, ranked (each exists in exactly one place)

> "One place" = one machine/repo/ref. Where a remote-tracking ref exists but the remote itself is gone or unverified, it is still called out. **Nothing here was preserved by this audit** — the commands are recommendations for a human/owner to run.

**R1 — `/opt/company` working tree, 8 files / 3,539 lines of LIVE code in no git ref (authority only).** `git -C /opt/company diff --name-only preserve/…` + filter-aware `git hash-object --path` + membership in `git rev-list --all --objects` proves these working blobs are in no ref:
`scripts/ps_mcp_server.py` (864 lines, **a running process**), `scripts/server/backup-data.sh` (193), `scripts/dialpad-recording-gap.py` (262, **cron */5**), `scripts/dialpad-transcript-gap.py` (273, **cron */10**), `tests/test_smart_router.py` (1174), `tests/test_utility_roles.py` (226), `tests/test_board_seat_goal_coverage.py` (268), `tests/test_lane_health_gate.py` (279).
*Preserve (non-destructive snapshot of tracked+untracked):*
`git -C /opt/company stash push -u -m "audit-preserve-$(date -u +%Y%m%dT%H%M%SZ)"`
*(alternative, branch form: `git -C /opt/company checkout -b preserve/live-$(date -u +%Y%m%dT%H%M%SZ) && git -C /opt/company add -A && git -C /opt/company commit -m preserve-live && git -C /opt/company push origin HEAD`)*

**R2 — `secratary-ts:/home/zabz/personal-secretary-mvp`, 33 stashes, none reachable from any ref (office only; 39 GB repo).** Verified `stash list` = 33 and `for-each-ref --contains` = empty for `stash@{0}…{4}`; the largest is `stash@{25}` = 137 files, +39,367/−3,781; `stash@{0}` = 15 files +2,981; `stash@{1}` = 35 files +5,858. Only `stash@{27}` is empty.
*Preserve:* `git -C /home/zabz/personal-secretary-mvp bundle create /safe/psm-stashes.bundle refs/stash` (or, per stash, `git -C … stash branch rescue/stash-N stash@{N}`).

**R3 — `secratary-ts:/home/zabz/harness-config.git` bare hub, 25 branches carry commits in no other ref, and the repo has NO remote (office only).** Biggest: `fix/mesh-provider-dispatch` 44 unique commits, `hk/367-mirror-propagation` 40, `zabz-audit-20260914-r25` 29, `main` 15, `agent/roadmap-supply-kosher` 15, `zabz-audit-20260914` 9, `master` 2, plus 18 more (see §1.B). `git fsck` dangling = 1.
*Preserve:* `git clone --mirror /home/zabz/harness-config.git /safe/harness-config.git` or `git -C /home/zabz/harness-config.git bundle create /safe/office-hc.bundle --all`.

**R4 — `harness-config` has FOUR divergent lineages (the "journal id divergence").** (a) authority/vault: `secratary-cloud main 31c650a` == published to vault `1a5c2fe`/`31c650a`; (b) office bare `main 04459547`, `master 1245e54d`; (c) office worktree `code/harness-config main f1713ce1`, **ahead 74 / behind 24** of its own `origin/main`; (d) GitHub mirror probe `refs/remotes/ghprobe/main f38366f`. `secratary-cloud` is **missing** office commits `6d057fec`, `04459547`, `1b921d70`, and the office bare is **missing** `31c650a`, `1a5c2fe`. Cross-machine ancestry cannot be computed without a fetch/merge. Journal ID collisions: 79 ID-like duplicate filenames exist on both authority and office, but all live under tracked `journal/archive/collided-ids-*/` (already recorded), not as active duplicate entries.
*Settle/reconcile:* `git -C <repo> fetch --all` then `git merge-base --is-ancestor <a> <b>`; the convergence commit `1b921d70` ("converge all three journal lineages") exists only on the office/local side.

**R5 — GitHub mirror `ghprobe/main` carries 2 commits not in the vault or the office bare** (`f38366f`, `864a565` "…entries from ZABZ-YOGA"), `git rev-list --left-right --count main...ghprobe/main` = `143  2`. They survive only on GitHub and in the authority's stale tracking ref (the `ghprobe` remote config was removed).
*Preserve:* `git -C /root/code/harness-config branch preserve/github-mirror-ghprobe refs/remotes/ghprobe/main`.

**R6 — `lpt-apps:/opt/lpt/src` is an UNBORN repo with 14 untracked source dirs and a 404 remote** (highest-value single-copy source). *Preserve:* `tar czf /safe/lpt-src-$(date -u +%Y%m%dT%H%M%SZ).tgz -C /opt/lpt/src backend frontend packages python-printer-service shared package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json turbo.json`.

**R7 — `secratary-ts:/home/zabz/mesh-security.git` bare, `main@09fd362` with 19 unique commits and no remote.** *Preserve:* `git clone --mirror /home/zabz/mesh-security.git /safe/mesh-security.git`.

**R8 — `secratary-ts:/home/zabz/phone/yitz-insurance-2026-10-06`**: 68 modified tracked files, no remote, `master` has 2 unique commits. *Preserve:* `git -C /home/zabz/phone/yitz-insurance-2026-10-06 bundle create /safe/yitz.bundle --all` and a physical `rsync` of the worktree.

**R9 — `secratary-ts:/home/zabz/code/unified-search`**: unique commits (`main` = 3) whose only other copy was `/tmp/unified-search.bundle`, now **gone** (`ls-remote origin` fails). *Preserve:* `git -C /home/zabz/code/unified-search bundle create /safe/unified-search.bundle --all`.

**R10 — `secratary-ts:/home/zabz/bin.git` (13 branches with unique commits) and `/home/zabz/bin` worktree (11 branches, 254 untracked files).** *Preserve:* `git clone --mirror /home/zabz/bin.git /safe/bin.git` + `rsync -a /home/zabz/bin/ /safe/bin/`.

**R11 — `secratary-ts:/home/zabz/repos/lpt-books.git`** (`ws8-automate-20261007` 5, `hk/item231-clarification-record` 2, `hk/item231-nullcat-classified` 1 unique commits). *Preserve:* clone --mirror / bundle.

**R12 — `secratary-ts:/home/zabz/repos/kosher-filter-ai`**: 1 UNREACHABLE non-empty stash (`stash@{0}`, "WinDivert licensing decision (owner-queue #139)", +4/−1) plus one unique branch. *Preserve:* `git -C /home/zabz/repos/kosher-filter-ai bundle create /safe/kosher.bundle --all refs/stash`.

**R13 — `secratary-ts:/home/zabz/code/harness-config` worktree**: 3 branches with unique commits — `agent/ownertext-flood` 8, `agent/ws-orderfeed` 2, `hk/sms-inbox-condition-exit-20261006T191710Z` 1; plus 3 M / 35 U.

**R14 — `lpt-apps:/opt/lpt-test/src`**: 2 stashes in no ref (e.g. `stash@{1}` `23e749ab` touches `backend/Dockerfile.production`) and 2 dangling commits (`655655b9e0`, `fbb276eea1`). *Preserve:* `git -C /opt/lpt-test/src branch preserve/stash1 <sha>` for each.

**R15 — `lpt-apps:/opt/chumash-timeline` stash@{0}** (`bd12b0c`, `docker-compose.yml` +22/−17), in no ref. *Preserve:* `git -C /opt/chumash-timeline branch preserve/stash0 bd12b0c`.

**R16 — `linux-pc-ts:~/code/harness-config`**: stash `presync-bench-20261011-2226` (6 files +629) is in no ref; `meshfix/mfx-transport` (5) and `meshfix/mfx-provider` (2) are unique local branches (office hub lacks their tips). *Preserve:* `git -C ~/code/harness-config bundle create /safe/lpc-hc.bundle --all refs/stash` + push the two `meshfix/*` branches to a mirror.

**R17 — `secratary-cloud:/root/repos/noson-yanofsky-profile.git`**: bare, `main@1d489a0`, 4 commits, **no remote** (only plain-directory copies of the content in `/root/backups/`). *Preserve:* `git -C /root/repos/noson-yanofsky-profile.git bundle create /root/noson.bundle --all` and add a real remote.

**R18 — `secratary-cloud:/opt/company/archive/`**: 6.3 GB / 46,935 untracked transcript objects; not gitignored; **no copy found on lpt-apps**. *Preserve (owner decides destination):* `rsync -a /opt/company/archive/ lpt-apps:/srv/backups/company-archive/`.

**R19 — `survivor:/opt/company`** dirty worktree (3 M + 4 U incl. `data/leadership.json`) on a non-default branch.

**R20 — `linux-pc-ts:~/hk367-consumer-autosync-20261002T0856Z`**: `scripts/autosync.sh` modified and its working blob is in no ref.

**R21 — `/opt/company/data/harness-config.bak-20260915T0200Z` (207 MB stale clone)** and **`/root/psm-master.bundle` (285 MB, `origin/master=006cde5`)** — stale backups that are themselves single-copy, but their content is largely on GitHub/office.

**R22 — Other `secratary-ts` bares with unique commits but mirrored tips:** `ceo-kernel.git` (`hk/item231-kernel-gitignore` 1), `home.git` (`main` 86, tip mirrored in `code/home`), `repos/halacha.git` (`master` 8, mirrored), `harness-config.pre-unify` & `hc-fork-lab` (`journal-migration-20260915` 1 each).

**At-risk items total: 22 ranked items**, of which the single-copy, no-remote, no-backup subset is R1, R2, R3, R5, R6, R7, R8, R9, R12, R14, R15, R16, R17, R20.

**Security findings surfaced by the audit (not git-work loss, but data risk):** authority `/root/.git-credentials` holds two GitHub PATs in plaintext; `survivor:/opt/company`'s `origin` URL embeds a PAT (`gho_8a0P5…`); `/opt/company/postgres:/ueohoi…:pba408…@…rds.amazonaws.com:5432/` is a directory name containing a live-looking Postgres DSN. **Rotate, do not just delete.**

---

## 3. Junk candidates (recommend, never auto-delete)

* **`/opt/company`**: 7 untracked `.env*` backups (`.env.before-*`, `.env.new`, `.env.provisioned-*`), 8 `data/crontab.bak-*`, `*.db-shm`/`*.db-wal`, `scripts/*.py.bak-*`, `scripts/*.sh.bak-*`, the literal `postgres:/` credential-dir, and the untracked 207 MB nested `data/harness-config.bak-20260915T0200Z` clone. Four `chip/2026-10-12-*` branches are fully merged into `master` (trees identical). `archive/` should be `.gitignore`d.
* **Authority `harness-config`**: stale `refs/remotes/ghprobe/main` (remote removed); untracked `*.pre-*` one-off backups.
* **`secratary-ts`**: `bin`'s 254 untracked files are overwhelmingly `*.bak-*`; fully-merged branch sets — all 33 `lpt-hub`, all 54 `phone-and-tech-full`, all 8 `quickbooks-agent`, all 8 `personality-test`, 98/99 `personal-secretary-mvp` (only `hk/item642…` is unique); duplicate-tip `diverged-ZABZ-*` date series (keep one per date only after confirming the 25 unique branches are rescued); `personal-secretary-mvp stash@{27}` (empty); untracked `NUL` (Windows artifact) and a literal `"\tmp\fanout-thread-*…jsonl"` filename; dangling blobs (phone-and-tech 272, lpt-hub 204, actions-runner 143, personal 81, kosher 31).
* **`lpt-apps`**: `/opt/lpt/src/node_modules` 1.4 GB + `.pnpm-store` 1.2 GB (regenerable); `/opt/personality-test` 91 dangling **blobs** from repeated detached checkouts; many `*.bak`/`*.sql`/`*.dump` under `/root`.
* **`linux-pc-ts`**: `mtkclient` (third-party, 20 behind), `personal-secretary-mvp` local clone (230 behind) with an empty stash, `edl_case/edl` (2 modified `.github` files), `harness-config` garbage object (57 KB) + 16 prune-packable; `migration/*` branches pointing at old `master`.
* **`survivor`**: `/opt/company/.cache`, `/opt/company/.mem0`.

---

## 4. Reconciliation plan (ordered, safe — nothing below executed by this audit)

**Phase 0 — capture before touching anything (do this first).** Every "Preserve" command in §2 writes a bundle/mirror to `/safe` (or `lpt-apps:/srv/backups/`). Do the at-risk captures *before* any merge/push. This is the no-loss guarantee.

**Phase 1 — make every single-copy item exist in two places.**
1. `/opt/company`: snapshot the 8-file live residual (R1) and push it as a `preserve/live-<ts>` branch to GitHub; rsync `archive/` (R18) to lpt-apps.
2. `secratary-ts`: mirror `harness-config.git` (R3), bundle the 33 `personal-secretary-mvp` stashes (R2), and mirror `mesh-security.git` (R7), `bin.git` (R10), `repos/lpt-books.git` (R11), plus `rsync` of `bin`, `yitz-insurance`, and rescue stashes (R12) — **but the office box is FROZEN and has no vault credential; it cannot push. Copy off-box with `rsync`/`scp` to a host that can, or have the owner run it.**
3. `lpt-apps`: bundle `/opt/lpt/src` (R6) and the lpt-test/chumash stashes (R14/R15).
4. `linux-pc-ts`: bundle the harness-config stash (R16), push `meshfix/*` branches.
5. Authority: bundle the noson bare repo (R17), preserve the GitHub-mirror 2 commits (R5).

**Phase 2 — reconcile the four `harness-config` lineages (needs a reviewer; NOT a fast-forward).**
- Canonical trunk = **authority/vault** (`secratary-cloud main` → `lpt-apps:/srv/git/harness-config.git`), because the 15-minute `journal-commit` publishes to it.
- From the office/local side, `1b921d70` ("converge all three journal lineages: master, the authority, and ZABZ-TECH") is the shared base; `secratary-cloud` does **not** have it. A merge of office `main 04459547` / `master 1245e54d` into the authority trunk will be a **true merge with conflicts** (both sides journal-autocommit the same index files). Do it on a scratch clone, resolve the journal index (`journal/index/entries.tsv`, `journal/index/journal.db`, `journal/index/stamp.json`) by regeneration, and never force-push.
- Office worktree (`f1713ce1`, ahead 74/behind 24 of its own bare) must first be reconciled with the office bare; 3 unique branches there (R13) need landing.
- After the merge, **fetch the GitHub mirror's 2 commits into a preserve branch before re-pointing/removing `ghprobe`** (R5).

**Phase 3 — `/opt/company` convergence (needs the owner/reviewer for the 26 non-unique modified files).** `master@adecfd56` tree == `preserve/…@42109f4a` tree (`6f7ed623…`), and `42109f4a` is pushed to GitHub. The remaining 32-file working divergence consists of 26 files whose working content exists only in *older* refs (so the running service is on an older version than `master`) and the 8 no-ref files. Decide which side is canonical (the running tree, presumably) and land it deliberately; do not `reset --hard`.

**Phase 4 — stale artifacts and credentials.** Retire stale bundles (`hc-main.bundle` re-point after Phase 2; `psm-master.bundle`; authority's nested 207 MB hc backup), rotate the three leaked GitHub/Postgres credentials, then delete only with a second confirmation.

**What needs a reviewer:** Phase 2 (harness-config merge — conflicting journal indexes), Phase 3 (which `/opt/company` version production should run), any `stash branch` that rewrites the index.
**What needs the owner:** credential rotation; the `archive/` backup destination; confirming the canonical harness-config lineage; authorising the frozen box to be copied off-box.

---

## 5. What was NOT reached or NOT established

* **`mac-mini-ts` (`LakewooechsMini`) — UNKNOWN, never "clean".** `ssh -o ConnectTimeout=8 mac-mini-ts hostname` → `Connection timed out`; `ssh lpt@192.168.50.45 hostname` → `No route to host`; `tailscale status` shows it `offline, last seen 2m ago`. Settle: bring it on the tailnet, then `ssh mac-mini-ts 'hostname; git --version'` and run this same audit.
* **Windows (`desktop-ts`, `laptop-ts`)** — inventory incomplete at write time (see §1.D). A full `C:\` scan cannot finish inside the command timeout. Settle (PowerShell over stdin): `ssh desktop-ts 'powershell -NoProfile -ExecutionPolicy Bypass -Command -'` with `Get-ChildItem -Path $env:USERPROFILE -Recurse -Depth 5 -Directory -Force -Filter .git`. Also test the laptop's vault credential: on `laptop-ts`, `GIT_TERMINAL_PROMPT=0 git ls-remote root@2.28.33.58:/srv/git/harness-config.git`.
* **`secratary-ts` fixture repos** — 40 pytest/scratch repos were excluded from deep audit and could still contain salvage. Settle with the same per-repo script.
* **fsck on huge repos** was counted, not enumerated; dangling objects are not listed. Settle per repo: `git fsck --no-progress 2>&1 | grep dangling`.
* **Committed-but-junk files** (`.bak`, `.pyc`, `node_modules`) inside HEAD trees were not inspected. Settle: `git ls-files | grep -Ei '\.bak|\.pyc|node_modules|__pycache__'`.
* **Non-`origin` remotes** not all tested: `repos/halacha` remote `yoga` (a Windows path), `personal-secretary-mvp` remote `delivery`, `code/home` remote `authority`.
* **Push capability was never exercised** (read-only audit). `ls-remote` proves read access only. Known: authority has GitHub + vault read; `secratary-ts` can read GitHub and reach the office bare but **cannot ssh to the vault** (`root@2.28.33.58: Permission denied (publickey)`); `linux-pc-ts` has GitHub + office credentials; laptop's vault credential unverified.
* **Cross-machine ancestry** of harness-config cannot be proven without a fetch (objects are not co-located). Settle on a scratch clone: `git fetch --all && git merge-base --is-ancestor <sha> <sha>`.
* **`/opt/company` untracked `archive/`** was not compared byte-for-byte to any backup; no copy was found on lpt-apps. Settle: `ssh lpt-apps 'find /srv -maxdepth 3 -iname "*transcript*"'`.

---

*End of audit. Read-only on all audited machines; the only durable write is this file and its commit on `secratary-cloud`.*
