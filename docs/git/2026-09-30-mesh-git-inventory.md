# Mesh git inventory and preservation — 2026-09-30

**Owner's instruction (verbatim):** *"get to work getting the git and remotes of the machines organized and
synced and pushed reconciling everything and making sure not to lose any work and saving all stashes into
the main properly after analyzing it all … do this slowly and methodically, don't mess up any work or lose
any work … across the whole mesh and all repos carefully."*

This document is the **inventory and the safety net**, not the reconciliation. It records: what exists on
each machine, what is at risk, where the snapshot lives, and the order the work will be done in. Nothing in
it authorises a destructive step.

---

## 0. The rules this work is being done under

1. **Preserve before touching.** Every working tree on every reachable machine was snapshotted first -
   refs, reflogs, stash lists, stash patches, dirty-tree patches, untracked listings, and a pinned ref for
   every stash - before any branch, merge, rebase or push is attempted.
2. **No `git reset --hard`, no force push, no `git stash drop`, no branch deletion, no repo deletion.** Not
   for tidiness, not to "clean up". If work looks redundant it is proven redundant first and left in place.
3. **Nothing is judged by its name.** Directories called `.bak`, `pre-unify`, `_converge-*`, `_verify*` may
   hold unique commits; they are treated as unknown until their refs are read.
4. **Additive only in the preservation pass.** The only writes are: `refs/lpt-backup/stash/<n>` (pinning a
   stash so gc can never collect it) and files under the backup root. No working tree was modified.
5. **Remote work is serialised.** Hammering sshd with parallel connections trips the server (measured twice
   today: `scp: Connection closed`, then `Connection timed out`). One connection at a time, with retries.
6. **Fetching is not free of side effects for the user.** `git fetch --all` on a machine with a
   `heroku` HTTPS remote and no stored credential makes Git Credential Manager pop a dialog on the owner's
   desktop. Fixed this session (see §6) and all fetches now skip heroku and run with prompting off.

---

## 1. Where the snapshots live

| Machine | Backup root | Contents |
|---|---|---|
| **zabz-tech** (this desktop) | `C:\Users\ezabz\_git-backup-20260930\` | **DONE** — 21 repo dirs, **77 worktree captures**, 1.55 GB, 8 stash patches |
| **secratary** (authority) | `/home/zabz/_git-backup-20260930/` | **DONE** — 33 repo dirs, **23 worktree captures**, **50 stash patches**, 4.8 GB; `personal-secretary-mvp`'s **16 stashes pinned** as `refs/lpt-backup/stash/*` and **all 16 still listed** (nothing dropped). Tools and path lists in `_tools/` |
| **zabz-tech-linux** (macOS mini) | `/home/zabz/_git-backup-20260930/` | **DONE** — all 4 repos captured |
| **hetzner** | n/a | one clean stale checkout, nothing at risk — see §4 |

Each repo dir contains:

| File | What it is |
|---|---|
| `state.txt` | repo path, branch, HEAD, upstream, git dir/common dir, bundle size |
| `refs.tsv` | **every ref and its SHA** - the map that makes any lost branch recoverable |
| `reflog.txt` | every reflog entry (the last-resort recovery path) |
| `stashes.tsv` | each stash with its SHA, date and subject |
| `pinned.txt` | `stash@{n} <sha>` for every stash, and each was also written as `refs/lpt-backup/stash/<n>` |
| `stash-<n>.patch` | the stash's full diff **including untracked files** |
| `stash-<n>-tree.txt` | the file list of the tree the stash holds |
| `remotes.txt` | every remote and URL |
| `count-objects.txt` | object counts (a completeness check for a later restore) |
| `wt-<slug>/` | **per working tree**: `state.txt`, `status.txt`, `worktree-tracked.patch`, `worktree-staged.patch`, `untracked-listing.txt` |
| `full.bundle` | a full-repo bundle from `--all` - created for `lpt-hub` only (1.42 GB), **skipped elsewhere** see §5 |

**The pinned refs are the important part.** A stash is reachable only through `refs/stash` and its reflog;
once that reflog expires, `git gc` can collect it and the work is gone. Writing each stash SHA to
`refs/lpt-backup/stash/<n>` makes it a normal ref, so it can never be collected, is visible to
`git for-each-ref`, and travels in a bundle or a push.

---

## 2. zabz-tech (the office desktop) — 77 working trees, 21 distinct repositories

The biggest exposure on the mesh, and the one that is now **fully preserved**.

**Diverged or dirty clones (a real clone, not a worktree):**

| Repo | Branch | State | Risk |
|---|---|---|---|
| `personal-secretary-mvp` | `master` | **ahead 66, behind 98**, 10 tracked modified, 34 untracked | **The largest single pile of unpushed work seen today.** Needs per-commit review before it touches any remote |
| `_fleet\phone-and-tech-full` | `test` | 10,827 modified files, behind 171 | Almost certainly generated output; **must be read, not assumed** - a stale fleet clone |
| `harness-config` | `hk/20260928-journal-utf8-complete` | 6 modified, 7 untracked, 2 stashes | On a feature branch, not `master` |
| `harness-config-mesh` | `mesh/placement-nonce-r3-20260919` | 9 modified, 4 untracked, 2 stashes | feature branch |
| `lpt-flip-phone` | `main` | 10 modified, 7 untracked | small |
| `_chumash_build` | `agent/chumash-deploy` | 30 modified, 1 stash | |
| `hc-origin-fix` | `fix/origins-proxy-restart-20260919` | ahead 1, **behind 361** | one unpushed commit |
| `lpt-hub` | `main` | 62 untracked (`_scratch`), **4 stashes** | the stashes are the interesting part |
| `ha-config`, `home`, `reports` | | 1-5 modified | small |

**Worktrees (77 captures total, sharing 21 repos):** the `_fleet\*`, `_fleet2\txt-*`, `_worktrees\psm-*`,
`_worktrees\lpt-*`, `_cfo-fleet\ws*` trees. Most are clean and many are **behind by 165-352 commits**;
several hold stashes (shared with their parent repo, so counted once per repo, not once per worktree).
The `personal-secretary-mvp` worktrees carry large untracked trees (1775, 1640, 524 files) - generated
artifacts from fleet runs.

**Stashes on this machine: 8 patch files across 4 repositories** - `lpt-hub` (4), `harness-config` (2),
`phone-and-tech-full` (1), `chumash-timeline` (1). All eight are pinned as `refs/lpt-backup/stash/*` and
captured as patches.

---

## 3. secratary (the authority) — 50 working trees found, snapshot **complete**

The first attempt died with the mesh link (`Connection timed out`, twice: `scp: Connection closed` then
`client_loop: send disconnect: Connection reset`). It was completed by running it **detached on the server**
(`setsid nohup … < /dev/null &`) and polling the log, so a dropped connection can no longer lose the run.
**Verified after the fact:** 33 repo dirs, 23 worktree captures, 50 stash patches, 4.8 GB, and
`personal-secretary-mvp`'s **16 stashes both pinned and still present**.

**The at-risk items there, by name:**

| Path | State | Why it matters |
|---|---|---|
| `/home/zabz/repos/lpt-hub` | **detached HEAD** at `51f492ca6`, 11 dirty, 6 untracked, 17 branches | a detached HEAD with dirty state is the single easiest way to lose commits |
| `/home/zabz/personal-secretary-mvp` | **ahead 6**, 4 dirty, 17 untracked, **16 stashes** | the authority's own checkout, 16 stashes |
| `/home/zabz/bin` | `master` **ahead 1**, 5 dirty, 3 untracked | `owner-queue.py` and the other operator scripts live here |
| `/home/zabz/harness-config.bak-20260915T0200Z` | **ahead 12**, behind 806, 5 dirty | a `.bak` directory holding 12 commits that may exist nowhere else |
| `/home/zabz/_converge-all-20260930T170223Z` | **ahead 81** | an integration tree with 81 commits |
| `/home/zabz/_converge-authority-20260930T161751Z` | behind 81, 1 dirty | its counterpart |
| `/home/zabz/harness-config.pre-unify-20260922` | behind 167, 5 branches | |
| `/home/zabz/hc-fork-lab-20260917T033457Z` | 5 branches, no upstream | a fork lab |
| `/home/zabz/checkout-health-test` | **detached HEAD**, 1 dirty | |
| `~/_verify2`, `~/_verify_base`, `~/_verify_co_20260928`, `~/_fcwt/probe`, `~/_worktrees/lpt-dialpad-fallback` | each reports **16 stashes** and 41 branches | these are worktrees: they share `personal-secretary-mvp`'s stash list, so the 16 stashes are counted once per repo, not five times |
| `/home/zabz/code/unified-search` | `main`, **fetch failed (exit 128)** | remote unreachable or credential missing |
| `~/code/home` | behind 7 | two remotes: `authority`, `origin` |
| `/home/zabz/repos/ha-config`, `repos/lpt-flip-phone` | behind 34 / 7 | stale |

---

## 4. The other machines

| Machine | Root | Working trees found | Backup root | State |
|---|---|---|---|---|
| **zabz-yoga** (laptop) | `C:\Users\ezabz\Code` | 101 top-level dirs → **34 git working trees = 23 distinct repos** | `C:\Users\ezabz\_git-backup-20260930\` | **FROZEN** — 14 MB of refs, reflogs and patches; **24 stashes in 4 repos, all pinned** |
| **zabz-tech-linux** (macOS mini, Yisroel) | `/home/zabz` | 4 | `/home/zabz/_git-backup-20260930/` | **FROZEN** — all 4 captured. `harness-config` 675 behind (3 dirty, 2 untracked); `personal-secretary-mvp` 230 behind, 1 stash (pinned); `mtkclient` 20 behind, 193 untracked; `edl_case/edl` 70 dirty, 3 untracked |
| **hetzner** (`waze-mdm-01`) | `/root` (depth 5), `/opt`, `/srv`, `/var/www` | 1 checkout | n/a | **NOTHING AT RISK.** `/opt/personal-secretary-mvp`: clean, 1 branch, **0 stashes**, HEAD `26f256c` (2026-07-28) — and that commit **exists in the desktop clone**, so it is not unique work. Its fetch fails (exit 128): there is **no GitHub credential on that box**. `/root` holds no repositories |

**Every reachable machine is now frozen.** Nothing was merged, rebased, pushed, checked out, dropped or
deleted anywhere.

**Yoga's own at-risk list (different repos from this desktop — it is not a copy of it):**

| Repo | Branch | State |
|---|---|---|
| `phone-and-tech` | `docs/ux-simplification-v2-decisions` | **15 stashes** — the largest single stash pile on the whole mesh |
| `personal-secretary-mvp` | `feat/owner-text-gate` | 38 dirty, 66 untracked, 3 stashes |
| `research` | `master` | 26 dirty, **505 untracked** |
| `lpt-schematics` | `main` | 17 dirty, 5 untracked |
| `lpt-hub` | `main` | 7 dirty, 17 untracked, **3 stashes** (this clone's stashes are not the desktop's) |
| `harness-config` | `agent/capability-registry-20260930` | 18 dirty, 14 untracked, 3 stashes |
| `phone-and-tech-full` | `fix/hours-walkin-20260916` | 13 dirty, 13 untracked — plus a worktree with **1,124 untracked** |
| `_lpt-w6-wt`, `_yoga-merge-wt` | **detached HEAD** | `_yoga-merge-wt` also holds 3 stashes |

Yoga also carries repos that do not exist on this desktop (`lpt-schematics`, `phone-and-tech`, `research`,
`tutor`, `yocheved-staging`, `ceo-kernel`, `unified-search`, `_njpa-photo-review`), so its work cannot be
assumed to be a copy of anything here.

---

## 5. What was deliberately NOT done, and why

- **No bundles except `lpt-hub`.** A `--all` bundle of `lpt-hub` is **1.42 GB**; doing that for every repo
  would spend tens of GB for redundancy that the ref map plus pushing already provides. **Durability comes
  from pushing unpushed commits to a remote**, which is the reconciliation step - not from local bundles.
  Repos that turn out to have no remote will get a bundle individually.
- **Nothing was merged, rebased, pushed, checked out, or dropped.** The preservation pass does not
  reconcile. That is deliberate: the owner asked for method, and reconciliation on top of an unverified
  snapshot is how work gets lost.
- **The stale backup clones were not deleted.** `harness-config.bak-*`, `harness-config.pre-unify-*`,
  `hc-fork-lab-*`, `_converge-*`, `_verify*` are all still on disk. Several hold commits that exist
  nowhere else. Their disposition is a later, explicit decision.

---

## 6. The credential-dialog fix (done this session, owner-visible bug)

**Symptom:** Git Credential Manager kept opening a dialog on the owner's desktop asking for
`https://git.heroku.com/` credentials, while he was not using git at all.

**Cause:** `personal-secretary-mvp` and `phone-and-tech-full` carry `heroku`, `heroku-test` and
`heroku-prod` remotes at `https://git.heroku.com/lakewood-phone-backend-{test,prod}.git`. My recon ran
`git fetch --all`, there is no stored credential for that host, so GCM prompted - repeatedly, from a
background job.

**Fix (reversible, no effect on the Heroku apps or on deploying):**
- `git config --global credential.https://git.heroku.com.helper ''` - no helper is consulted for that
  host, so nothing can prompt. Verified: `git fetch heroku` now exits 128 with *"unable to get password
  from user"* and **no dialog**.
- `git config --global credential.interactive false` - no helper may open a dialog on any host.
- Every recon/preserve run sets `GIT_TERMINAL_PROMPT=0` and `GCM_INTERACTIVE=never`, and **fetches only
  non-heroku remotes**.

---

## 7. The reconciliation plan, in the order it will be done

Per repo, always in this order, and always one repo at a time:

1. **Read before writing.** `refs.tsv`, `reflog.txt`, `stashes.tsv`, the stash patches and the dirty-tree
   patches from the snapshot. For each stash: what does it contain, is it already in the branch, does it
   conflict, is it still wanted. **No stash is dropped, ever** - at most it is turned into a commit on a
   named branch and pushed, leaving the stash in place.
2. **Rank risk.** Unpushed commits on branches with no remote are the highest risk; then dirty trees; then
   stashes; then stale clones that are merely behind.
3. **Land work on a branch, never on the default branch directly.** A stash or a dirty tree becomes a
   commit on a descriptively-named branch, pushed to the remote. That converts "at risk, one disk, one
   machine" into "safe, on the remote, on every machine".
4. **Then, and only then, reconcile branches:** merge or rebase deliberately, resolving conflicts by hand,
   never by `-X ours/theirs`, never by force.
5. **Verify after every step:** re-run the recon for that repo, confirm ahead/behind and dirty counts, and
   record the before/after in this file.
6. **Never delete.** Stale clones and duplicate directories stay until their uniqueness is proven, and
   proven in writing.

**Risk order for the reconciliation itself (highest first):**
1. `personal-secretary-mvp` on this desktop (**ahead 66 / behind 98**) - the biggest single pile of work.
2. `secratary: /home/zabz/bin` (ahead 1) and `secratary: personal-secretary-mvp` (ahead 6, 16 stashes).
3. `harness-config.bak-20260915T0200Z` (ahead 12) on secratary, and `_converge-all-*` (ahead 81).
4. `secratary/repos/lpt-hub` - detached HEAD with dirty files: give it a branch, push it.
5. The 8 stashes on this desktop, one at a time, each analysed before it is turned into a commit.
6. `harness-config` on this desktop (on a feature branch with stashes) - reconcile to `master` and push.
7. The stale-behind clones on the mini and the fleet worktrees - fast-forward only, no rewriting.

---

## 8. How to verify this document

```bash
# the pinned stash refs (should list every stash that existed at snapshot time)
git for-each-ref refs/lpt-backup

# the ref map of any repo, as captured
cat <backup>/<repo>/refs.tsv

# what a stash held
cat <backup>/<repo>/stash-0.patch

# the per-worktree dirty state at snapshot time
cat <backup>/<repo>/wt-<slug>/status.txt
```

On this desktop: `C:\Users\ezabz\_git-backup-20260930\`. On secratary:
`/home/zabz/_git-backup-20260930/` (with the tools and path lists in `_tools/`).

**Scripts used (in `C:\Users\ezabz\Code\_scratch\git-recon\`):** `recon-remote.sh` (read-only recon, one
machine), `recon-any.ps1` (same for Windows), `preserve3.sh` (the additive snapshot, works under git-bash
on Windows and under bash on Linux/macOS), `sizecheck.sh`.
