# POSTMORTEM — ZABZ-YOGA, 0.2.0-rc.2 → 0.2.1-rc.2, 2026-10-20

Written by the session that did it, the same night, from the transcript, the switch log, the install receipt
and the journal. Every claim below has the reading it came from.

**The one-sentence version.** The version was fine and the staged plan was fine; the machine had been
unbootable since the night before, the pipeline had three defects that the plan could not see, and the
session's own documentation already contained the fix for the failure that took it down in the owner's hands.

---

## 1. What was asked

He rebooted ZABZ-YOGA for a clean stop-window and asked for the prepared 0.2.1 update to run the moment it
came online. The prepared artefacts: `dsh-update/tools/switch-yoga.ps1` (dry-run proven 2026-10-19 23:55,
H10220), a preflight GO on 8/8 guards (history row `2026-10-20T00:09:47.779Z`), and a verified backup
(`dsh-backup-20261019T235737Z`).

## 2. Timeline, measured

| UTC | what happened | reading |
|---|---|---|
| 22:50:24 | machine boots | `win32_operatingsystem.LastBootUpTime` |
| 22:56:24 | first probe: **2 engine processes** on 3099, live tree 0.2.0-rc.2, newest backup **22.95 h old**, C: 32.7 GB free, repo head `761b20e28`, 194 dirty files | `probe-yoga.ps1` |
| 22:57:53 | fresh backup taken (29 s, 0.47 GB) — required, `install-engine` refuses a backup older than 12 h | `BACKUP-REPORT.json finishedAt` |
| 22:58:21 | switch run 1: all four entry gates PASS, then **install-engine REFUSED, exit 2** — "the install would silently lose 4 hand patch(es)" | `switch-yoga-20261020T225821Z.log` |
| 22:58–23:01 | the abort path restarted the **old 0.2.0 engine against the 0.2.1-shaped config** it had just written; the engine cannot boot (`cannot get property webStartup without inject`); watchdog crash-looped it | `3099-*.err.log` |
| 23:03 | patch restored by hand from `.bak-switch-20261020T225821Z`; origins proxy found wedged; engine still died — now in `realpath` on `profiles/web/node_modules/research-offload` (`UNKNOWN`, errno −4094) | `3099-20261020-190122.err.log` |
| 23:06 | junction recreated (`cmd /c rmdir` + `mklink /J`); target fingerprint identical before/after (2 files, same sha256) | link test + `fsutil reparsepoint query` |
| 23:07 | engine still fails: the **live patch had carried `ctx.webStartup` since 2026-10-19 23:37** — i.e. this machine could not boot for 22 hours, and nothing said so | `cordis.patch.yml` lines 61–63, mtime 2026-10-19T23:37 |
| 23:09–23:19 | root cause of the refusal found in `dsh-update/lib/patches.mjs:audit()`; two patchers written and proven on a scratch copy (`check` 1 → `apply` 0 → `recheck` 0 → idempotent 0) | audit rows before/after |
| 23:20:48 | second fresh backup |  |
| 23:21:13 | switch run 2 | `switch-yoga-20261020T232113Z.log` |
| 23:24:29 | **install-engine exit 0**; receipt `0.2.1-rc.2-20261020T232121Z.json`; previous tree kept at `engine.prev-0.2.0-rc.2-20261020T232121Z` |  |
| 23:27:02 | `dshw ensure` → "engine is answering on 3099" |  |
| ~23:30 | **his turn failed**: `unknown prompt variable "{{cwd}}" in section "deployment:persona-suffix"; registered variables: provider, model` (his screenshot) |  |
| 23:32 | live patch: 3 persona suffixes corrected; 0 `{{cwd}}` left; preset row and `make_zabz_preset.py` corrected | `fixcwd.py` output |
| 23:34 | engine restarted; `config-assumptions` **PASS**; compose **421 rows, 0 `{{cwd}}`, 0 `ctx.webRuntime`** |  |
| 23:37 | the yocheved preset's `C:\Users\cheve\...` path replaced (every boot had been spawning a failing child) |  |
| 23:41–23:43 | my manual start raced the **DSH Engine Watchdog (1m)** scheduled task → 3 processes; stopped all, let the watchdog do it, settled to **one** (pid 28364, HTTP 200 / 38,512 B) | `Get-CimInstance Win32_Process`, `Get-ScheduledTask` |
| 23:47–23:52 | ESTATE.md updated; commits pushed | yoga `1c0420f07`, `712ebaba5`; tech `6e99f847` |
| 23:55–00:15 | postmortem code: preflight guard, install-engine gate, version-keyed prompt set; proven both ways; `snapshot` run; `status` clean | this document §6 |

## 3. The findings, each with its root cause

### F1 — I read the plan, not the record (the expensive one)
I searched the journal for *the plan* (`yoga update dsh engine upgrade`) and got H10220, H10350 and L10367.
L10238 — the entry that names **both** `ctx.webRuntime` and `{{cwd}}` as the two classes already paid for, and
that names `config-assumptions.mjs` as the control — did not surface, because I searched for the plan's words
rather than the failure's words (`{{cwd}}`, "prompt variable", "assumption", "persona-suffix").

Consequence: the documented fix existed, the control existed, and I ran the switch without either. The
`{{cwd}}` outage cost the owner a failed turn in his hands, after a GO preflight.

**The deeper mechanism:** this estate stores knowledge by *when it was learned* (a journal entry) and the
handoff by *what to do next*. Neither is indexed by *what it guards*. Recall therefore depends on the exact
words a later session happens to type — and a session that arrives with a plan types the plan's words.

### F2 — my own verification printed the answer and I consumed nothing from it
Before the first switch I ran the composed-tree check and it printed `cwd_tokens=3`. I read it as a baseline
number and moved on. There was no rule of the form "a non-zero in a check I just ran is a blocker", and no
gate consuming my own output. **A number I print and do not judge is not a check.**

### F3 — the abort path was worse than the failure
`switch-yoga.ps1` step 2 rewrites the live profile patch into the new version's shape, then installs. When
`install-engine` refused, the failure branch restarted the **old** engine against that patch. The `.bak` copy
had been made ten lines earlier and was never used. The result was a crash loop on a machine that had been
healthy ten minutes before.
**Rule now:** a phase that mutates state must register its own undo, and the failure path runs it before any
restart.

### F4 — the patch audit was separator-blind on Windows
`audit()` tested registry `covers` globs (written `dsh-client-ui-primitives/lib/StateDot.module.css`) against
`path.relative()`, which returns backslashes on Windows. No cover could ever match, so **every** patch read as
unregistered, and the refusal named four files, three of which that same registry covers.
**Shape:** a content-shaped refusal caused by a one-line platform bug. Fixed by normalising the relative path
before the substring test; the four then report `registered`.

### F5 — the switch never ran the assumption checker
`config-assumptions.mjs` shipped on 2026-10-19 with the lesson that produced it. Nothing in the update path
called it — the identical shape recorded in `cli.mjs` for `settings-effective`: *"A detector no verb can reach
is not a gate; it is a document."* It is now STEP 2.5 in the switch (before anything is written), a blocking
guard in `preflight`, and a refusal inside `install-engine` (the one path every route passes through).

### F6 — live config was mutated to the new version's shape with no install
The live patch was rewritten at **2026-10-19 23:37** and the install never ran. From that moment the 0.2.0
engine could not boot — and the handoff described the machine as "one stop-window away". A *precondition* was
violated silently: nothing asserted "the config on disk boots the engine on disk".
**Still open (design):** the config mutation should be applied to the *staged* home and copied into place by
the same step that swaps the tree, or the switch must refuse to leave the machine in a state where the config
implies a version that is not installed.

### F7 — a corrupt junction nothing could see
`profiles/web/node_modules/research-offload` printed correctly under `fsutil reparsepoint query` and could not
be `stat`-ed by Node (`UNKNOWN`, errno −4094). Every boot died in `realpath` before the port bound. No gate
looks at profile anchors; `link-anchors.mjs` exists for the *staged* home only.
**Fix now:** recreated, provable. **Next:** an anchor check in preflight and at boot.

### F8 — `dshw ensure` cannot start a machine whose engine is down
`ensure` verifies the origins proxy (`:19200`) before it starts the engine, and the proxy's health probe
depends on the engine. Two recovery attempts in this session were refused by that ordering. Worked around by
starting the engine directly (WMI, the same way `dshw` does) and letting `ensure` reconcile. **Open item.**

### F9 — generated config carried another machine's absolute path
The yocheved preset's MCP row pointed at `C:\Users\cheve\...` on a machine whose user is `ezabz`; every boot
spawned a child that died with `MODULE_NOT_FOUND` (non-fatal, so it hid in a log). And the *generator* of the
persona rows (`scripts/make_zabz_preset.py`) still emitted `{{cwd}}` on ZABZ-TECH even though its live patch
had been fixed by hand — so a regeneration would reintroduce the outage. **Fixed on both branches.** The
machine-specific path is fixed on this host; making presets machine-neutral is still open.

### F10 — the control carried the very class it guards
`config-assumptions.mjs` had `REGISTERED_PROMPT_VARS_0_2_1 = new Set(['provider','model'])` — one hardcoded
upstream surface applied to every version. That is the same mistake as `{{cwd}}`, one level up. Now keyed by
*measured* version, and an unmeasured version is a refusal (exit 3), not a guess.

### F11 — nothing re-snapshots the baseline after an install
After the install, `preflight` reported **NO-GO: baseline fresh** — `pin.contractSha256` matched the new tree
while `state/baseline` still described 0.2.0. Correct behaviour, missing step: `dsh-update snapshot` was not in
the switch's plan. Run it here (pin and baseline now agree, `status` shows `contract sha256 match`, `tree
sha256 match`); it belongs in the post-install phase.

## 4. What it cost

One owner's machine down from 2026-10-19 23:37 until 2026-10-20 23:27 (≈ 24 h, of which ≈ 35 min was this
session actively working it); one failed turn in his hands; two full switch attempts; one crash loop; three
engine restarts; four commits. The version install itself took **4 minutes** — exactly as staged.

## 5. The mechanisms that would have prevented it (now the rule)

1. **Search for the failure, not the plan.** Before touching a version-sensitive config, search the journal for
   every class in `docs/KNOWN-BREAKAGE-CLASSES.md` (the exact words are listed there), not for the task name.
2. **A phase that writes must register its undo**, and the driver runs it on any non-zero exit before it
   restarts anything.
3. **Every documented breakage class must have a gate, and every gate must be reachable from the one command.**
   A detector with no caller is a document; a class with no detector is the next outage.
4. **Every gate is proven both ways** — a positive and a negative test, recorded in the repo, not just observed
   once by hand.
5. **My own verification output is input to the next decision.** Any non-zero count in a check block is a
   blocker until it is explained in writing.

## 6. What changed in code tonight (all committed)

| file | change | proof |
|---|---|---|
| `lib/patches.mjs` | `audit()` normalises the relative path to `/` before the `covers` test | the same old/new trees now report `registered` 4/4 |
| `tools/config-assumptions.mjs` | prompt-variable sets keyed by **measured** version; an unmeasured version refuses (exit 3) | PASS on 0.2.1-rc.2; `{{cwd}}` in a scratch home → exit 1 naming `cordis.patch.yml:4 row "preset-zabz" {{cwd}}` |
| `tools/switch-yoga.ps1` | STEP 2.5 runs the assumption check against the **candidate** before writing; the abort path restores the live patch before restarting the old engine | `config-assumptions` PASS against the candidate; parse-checked under pwsh 7 (0 errors) |
| `lib/cli.mjs` | `preflight` gains a **blocking** guard "our config assumptions (prompt tokens, ctx injections)"; a candidate that is absent or a tool that cannot start is a GAP, not a pass | `preflight` prints `PASS our config assumptions ... 6 file(s), 4 prompt token(s), 1 ctx reference(s)` |
| `tools/install-engine.mjs` | refuses **before staging** when the assumption check finds anything | exercised in a dry run against the previous tree: `PASS our config assumptions (6 file(s), 4 prompt token(s), 1 ctx ref(s)) against 0.2.1-rc.2` |
| `scripts/patch-dsh-web-spinner-containment.py` | new patcher; finds `dist/assets/index-*.css` by glob and reads the spinner classes out of it | check 1 → apply 0 → recheck 0 → idempotent 0 |
| `scripts/patch-dsh-jsonl-frozen-clone.py` | new patcher; closes P3170 for the session store | same |
| `patches/registry.json` | spinner patcher registered; session-store entry promoted from `informational` to `script` | `audit()` reports 4/4 `registered` |
| `scripts/make_zabz_preset.py` (both branches) | stops emitting the `{{cwd}}` persona suffix | grep: 0 `{{cwd}}` in the generator |

## 7. Still open

- **His one turn** on the yoga is the only missing proof that turns work (a headless turn from ssh cannot run:
  `MISSING_CREDENTIAL ... deepseek-official`). Everything up to the turn is proven: 200 on the tokenised URL,
  421 composed rows, 0 `{{cwd}}`, `config-assumptions` PASS.
- **Two branches.** ZABZ-YOGA is on `cloud-audit/20261019`, ZABZ-TECH on `fleet/search-api-20261019`; every
  pipeline fix must be applied twice until they converge. That divergence is itself a finding.
- **`artifact provenance` is NO-GO** on the next preflight until the artifacts stamped against
  `%TEMP%/…/.dsh-staged/0.2.1-rc.2` are re-produced by the judging verbs (they were written by the 2026-10-19
  staging run).
- **`dshw ensure` ordering** (F8), **boot-time anchor verification** (F7), **machine-neutral presets** (F9),
  **config mutation on the staged home** (F6).
- **`lakewooechsmini`** remains unmeasured (`publickey denied`, ESTATE.md).
