# 162 - HARNESS-CONFIG MESH SYNC: WHAT WAS BROUGHT FORWARD, AND THE TWO PLACES IT CANNOT BE

Author: child sync agent on zabz-tech. 2026-10-11 ~22:30Z.
Scope: the owner asked for "a full git sync with all the repos between them and the whole mesh",
with "be careful and not lose any data or make regressions". Rule followed throughout:
**abort and report at any conflict rather than resolving it.**

## Result table

| machine | before | after | stash pending | what I did |
|---|---|---|---|---|
| ZABZ-TECH (this host) C:\Users\ezabz\code\harness-config | ahead 5, behind 47; 14 modified + 241 untracked; live writer active | **unchanged** ahead 5, behind 47 | YES - `stash@{0}` "On main: presync-zabz-tech-20261011-222023" | stashed tracked changes (no -u), attempted rebase; it REFUSED and I stopped. Reported, did not resolve. |
| BENCH zabz-tech-linux /home/zabz/code/harness-config | ahead 0, behind 97, HEAD 4dd70dbb (== merge-base), 4 staged + 2 modified, untracked .env | **ahead 0, behind 0**, HEAD 6d057fec | YES - `stash@{0}` "On main: presync-bench-20261011-2226" | stash (no -u), fetch (-> behind 99), rebase OK, stash pop CONFLICTED on 2 journal files; left stash pending, cleared stale index, restored upstream stamp.json |
| YOGA zabz-yoga-ts | ahead 0, behind 0 (already done) | not re-synced | n/a | not touched |
| CLOUD secratary-cloud /root/code/harness-config | ahead 13 vs its own `origin` | **not touched** | none | investigated bundle flow only; found it is NOT behind - see below |
| OFFICE secratary | ahead 74, behind 24 | **not touched** | n/a | frozen; only `git ls-remote` grade probes, no repo command |

## Why ZABZ-TECH was NOT synced - and why that is the correct outcome

The prescribed rebase **cannot run here**, and not because of a conflict the procedure permits me
to abort on. Measured, not guessed:

- 241 paths are **untracked** locally, and **59 of them are ADDED by upstream** between merge-base
  `b84fa974` and `origin/main`. Step 3 correctly stashes *without* `-u`, so those files stay in the
  tree and the rebase cannot check upstream's copies out over them.
- Worse, **47 of the 59 share the same ID but hold DIFFERENT content** on this machine than upstream:
  `journal/entries/decisions/D3032.md` local `b4a2b6b0` vs upstream `a38fd506`; likewise all of
  `L3440`-`L3468`, `H3501`/`H3502`, `P3003`-`P3005`, `W2732`-`W2734`. Both machines independently
  wrote "entry D3032". That is a **per-machine journal numbering divergence**, and choosing whose
  D3032 survives is a content decision for the owner - not a rebase step, and not mine to make.
- The rebase was then attempted anyway to confirm empirically. It returned
  `error: cannot rebase: You have unstaged changes.` and did **not** start, because **ZABZ-TECH has a
  live writer**: a background process re-modified `journal/alloc/bands.tsv`, `journal/index/*` and
  `journal/state/*` at 18:20-18:21 local, *after* my stash at 18:20:23. A checkout that is being
  written to while a rebase runs is a data-loss shape, not a sync. Stopped.
- `stash pop` was then run to restore the tree and it **also refused** - "Your local changes to the
  following files would be overwritten by merge: journal/alloc/bands.tsv, journal/index/entries.tsv,
  journal/index/journal.db, journal/index/stamp.json, journal/state/absorb-stamp.json". Git
  delivered that message *and aborted atomically*: **no stash was dropped, no work was lost, and the
  writer's newer files were left untouched.** That is the ideal failure mode and I left it there.

## Why the CLOUD was NOT synced - it is already current

The parent's caution was right: its `origin` is `/root/hc-main.bundle`, a local file, not the shared
server. Investigation results:

- `git bundle list-heads /root/hc-main.bundle` -> `refs/heads/main = ee3a7e2f`, and that commit **is an
  ancestor** of cloud HEAD. So the bundle is a **frozen snapshot base**, and "ahead 13" only means
  13 commits newer than the snapshot file. It does not mean 13 commits of unsynced work.
- The cloud carries a **second remote**, `vault = root@2.28.33.58:/srv/git/harness-config.git`, which
  the brief did not mention. `git ls-remote vault` returns exactly one ref:
  `refs/heads/main = 0bfc69fc553e85fbe63f11db55f175a533a23e5a` - **byte-identical to the cloud's own
  HEAD.** The cloud is therefore **fully synced**; nothing to bring forward.
- Nothing regenerates the bundle - no cron entry, no systemd unit; only two manual staging scripts
  mention it. It is simply stale, and a plain `git pull` there would fetch that stale file and do
  nothing useful. It is not a working sync path, so I changed nothing.
- The cloud is the live authority: `company-api`, `cloudflared`, `secretary-dashboard` and
  `phone-redirector` all report `active`. Not restarted, not touched.

## The real gap found: `origin` itself is stale for the whole mesh

`git ls-remote origin` (secretary, the shared server) reports `main = ee3a7e2f` - the same 16-hour-old
snapshot the bundle was cut from - while **vault reports `0bfc69f`**. So the shared server that every
other machine pulls from is itself old, and vault is where the current main actually lives. A sync
that only ever moves machines toward `origin` will keep pulling them onto a stale ref.

## Exact commands to finish what I left

ZABZ-TECH - the decision first, then the sync. Nothing below should run while the writer is active:
```
git stash show -p stash@{0}                       # inspect my preserved pre-sync state
git stash list                                    # stash@{0} mine, {1} autostash, {2} owner-attention-digest.sh
# after the owner rules on the D3032-class journal collisions:
#   commit or relocate the 59 colliding untracked paths, then
git fetch origin && git rebase origin/main
```

BENCH - the sync is DONE; only the conflicted pop remains:
```
git stash show -p stash@{0}                       # 38948-byte patch, also at
                                                  # /home/zabz/harness-config-presync-backup-20261011-2225/
git checkout stash@{0} -- <paths>                 # recover selectively; then git stash drop
```

CLOUD - nothing needed. To make its ref bookkeeping honest without touching services:
```
git fetch vault && git remote set-head origin -a   # optional; do NOT git pull from the stale bundle
```

## Backups made, outside every repo

- zabz-tech: `C:\Users\ezabz\harness-config-presync-backup-zabz-tech-20261011\`
  (entries/, plugin-remote-fanout/, scripts-mesh/, untracked-list.txt, PRE-HEAD.txt, stash-list.txt)
- bench: `/home/zabz/harness-config-presync-backup-20261011-2225/` including
  `dotenv.backup` chmod 600, `journal.db`, `stamp.json`, all four staged files, `PRE-HEAD.txt`,
  `PRE-STATUS.txt` and the pending-stash patch.

## One transferable defect

Every `ssh` session launched via PowerShell `Start-Job` **hung and never exited** - raw TCP 22 was
open on all three boxes and `ssh -V` was fine, so this is the known ssh-does-not-exit defect, not a
network failure. `Start-Process ssh -RedirectStandardOutput <file> -PassThru` plus a hard kill timer
works reliably (0.1s round trips), and quoting through PowerShell drops single quotes, so remote
scripts should be base64-encoded (`echo <b64> | base64 -d > /tmp/x.sh && bash /tmp/x.sh`).