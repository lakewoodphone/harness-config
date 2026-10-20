# 190 — The wake sources: what runs, what is in git, and how to see the drift again

**Date:** 2026-10-20, ~16:00Z. **Host:** `zabz-tech`. **Branch:** `chore/wake-sources-import`, cut from `main` at
`1bd92a99`. **Authority host read:** `secratary-cloud`, read-only — nothing was written, restarted or re-enabled there.
**Owns:** `scripts/wake/sources/**` and this page. No other file was edited.

## 1. What was measured

The wake loop runs from **`/root/bin/sources` on `secratary-cloud`**. `crontab -l` carries:

```
7,37 * * * * /usr/local/bin/cron-wrap.sh run-wake-sources L2Jpbi9iYXNoIC9yb290L2Jpbi9ydW4td2FrZS1zb3VyY2VzLnNoID4+IC9yb290Ly5zbXMtaW5ib3gvc291cmNlcy1jcm9uLmxvZyAyPiYx
```

The decoded payload is `/bin/bash /root/bin/run-wake-sources.sh`, and that script does `cd /root/bin/sources || exit 1`
before calling each source. `/home/zabz/bin` is a symlink to `/root/bin` (`ls -ld` → `bin -> /root/bin`), so both
spellings reach one tree.

The comparison on 2026-10-20, before the import:

| set | count | identical to repo | differ | no repo copy |
|---|---|---|---|---|
| live `.py` files | 33 (0 `.sh`) | 1 | 9 | 23 |
| all active files (33 `.py` + 3 `.json` + `README.md`) | 37 | 1 | 11 | 25 |

So the brief's measurement reproduced exactly: **1 of 33 `.py` files matched, 32 differed or were absent, and 23 had
no copy in the repository at all.** The size gaps were not cosmetic: `project-keepalive.py` 33,682 B in the repo and
54,404 B live; `checkout-health.py` 43,915 → 106,848; `projects.json` 19,357 → 67,089; `README.md` 13,583 → 24,107;
`wake-tuner.py` 42,489 → 56,084. A deploy from the repository would have reverted roughly twenty kilobytes of live
behaviour in `project-keepalive.py` alone.

## 2. What was imported

Commit **`fb4ecd04`** copies the live working tree in: **25 files added, 11 updated, 36 changed, no logic edited**.
The after picture is **`37 identical of 37`**. Every imported `.py` was compiled and every imported `.json` parsed
(33 `.py`, 3 `.json`) before the commit.

Deliberately **not** imported:

- **310 `.bak-*` files under `/root/bin`** (68 of them inside `sources/`). They are the de-facto backup, not sources.
- **Two `tmp*.new` temporaries** in `sources/`, with the same byte counts as `pain-checks.py` and `cron-failures.py`.

`/root/bin` is itself a git repository, but its `.gitignore` tracks only `sources/*.py` and `sources/*.md`. The three
JSON files (`projects.json` and the two roadmap files) are ignored there — this repository is their only version
control.

## 3. The rule, stated plainly

**The live tree is the source of truth for behaviour.** It is what cron executes; the repository is a mirror that
exists so those bytes survive a disk and can be reviewed. This is not a preference — it is the only tree the scheduler
reads.

**A deploy is a repo → host copy.** `scripts/guards/install.sh:8` states that direction and names this tree as the
precedent: *"the same direction `scripts/wake/sources/` already uses for `~/bin/sources/`."* I found no script in the
repository that automates that specific copy (a search for `wake/sources` across `scripts/` returns no deploy wiring),
so today a deploy is a manual copy of these files to `/root/bin/sources/`. **Run the check below before and after it.**

## 4. How to see the drift again

Run from the repository root. One line:

```
$m=ssh secratary-cloud 'cd /root/bin/sources && sha256sum *.py *.json README.md';$h=@{};$m|%{if($_ -match '^([0-9a-f]{64})\s+(.+)$'){$h[$Matches[2]]=$Matches[1]}};$n=0;$h.Keys|sort|%{$p="scripts/wake/sources/$_";if((Test-Path $p) -and ((Get-FileHash $p).Hash.ToLower() -eq $h[$_])){"identical  $_";$n++}else{"DIFFERS    $_"}};"$n identical of $($h.Count)"
```

It prints one line per live file, `identical` or `DIFFERS`, and ends `N identical of M`. **The expected answer after
this import is `37 identical of 37`.** Any `DIFFERS` line is either an un-imported live edit (copy it in) or a
repository-only change waiting to be deployed (do not copy it in without deciding that first).

## 5. Two gaps this import did not close

1. **`_flag.py` is genuinely diverged, and was imported as the live file.** The repository had a saturation guard
   added on 2026-09-28 (commit `08f85e75`): `SATURATION_LOAD_PER_CORE`, `saturation_reason()`, and a refusal to add
   work in `run()`. The live file has **no `saturation` string anywhere** — the guard never reached the authority.
   The live file also carries fixes the repository lacked (owner DB is `/root/authority.db`, `app_unit()`
   auto-detection, journal-banner filtering, `defer_on_cooldown`). The import records what runs; the guard now exists
   only in git history. Whether to re-apply it live is a human decision — it was not merged by hand here.
2. **`run-wake-sources.sh` is outside this tree and also differs.** Repository: 2,979 B, `cd /home/zabz/bin/sources`.
   Live: 21,713 B, `cd /root/bin/sources`, with 2026-10-16 and 2026-10-18 fixes (the `WAKE_STATE_DIR` pin, the
   owner-escalation cooldowns, `CRON_TARGET_GUARD`). This task owned `scripts/wake/sources/**`, so it was **not**
   touched. A deploy that copies `sources/` and forgets the entry point still reverts the entry point.

`scripts/deployed/bin/sources/` is **not** a deploy copy: its `MANIFEST.json` describes a byte-truth capture taken
2026-09-29 from the then-authority `secratary`, and it was left untouched for that reason.

## 6. What this page does not establish

Nothing here was executed: no source was run, no cron job was triggered, and no service on `secratary-cloud` was
restarted or changed. The classification is by live mtime versus the last repository commit touching each file
(every repository commit predates the live file), plus a review of the removed lines in each diff — not a semantic
line-by-line audit of 10,000 inserted lines. The 33 `.py` files are the measured set; `run-wake-sources.sh` and
anything else outside `sources/` remain unmeasured beyond the one comparison noted in §5.
