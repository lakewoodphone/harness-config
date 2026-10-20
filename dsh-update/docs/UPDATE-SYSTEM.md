# THE UPDATE SYSTEM — what it is, what it must be, and where each part lives

Written 2026-10-20 after the ZABZ-YOGA window (see `POSTMORTEM-2026-10-20-ZABZ-YOGA.md`). This is the design,
not an aspiration: every phase named here either exists and is named by file, or is listed in §5 as open with
the reason.

## 1. The shape that failed

The pipeline is good at judging a **candidate** and blind to **us**. `analyze`, `patch-effect`, `preset-gate`
and `verify` all answer "is this version safe to run". None of them answers "does our own config name something
this version does not offer", "is the machine we are about to touch currently able to boot", or "did the step
that writes need an undo". Preflight said GO 8/8 on a machine that had been unbootable for 22 hours, and the
GO was honest: it was answering the question it was asked.

The second failure is structural rather than analytical: **knowledge lives in journal entries and handoffs,
which are indexed by when it was learned, not by what it guards.** A session that starts from a plan recalls the
plan. That is why the same two classes (`ctx.webRuntime`, `{{cwd}}`) took two machines down one day apart.

## 2. The phases, in order, with the gate that owns each

Every phase is a program with an exit code. A non-zero stops the chain; nothing "continues best-effort".

| # | phase | who owns it | refuses when |
|---|---|---|---|
| 0 | **read the record** | the session | it has not read `docs/KNOWN-BREAKAGE-CLASSES.md` rows for the version's moving parts, and searched the journal for each class's words |
| 1 | **is this machine able to boot now?** | `dshw ensure` + (open) an anchor check | the pre-change engine does not answer on its port, or a profile anchor cannot be `realpath`-ed |
| 2 | **preflight** | `dsh-update preflight <ver>` | any blocking guard fails: baseline fresh, analyze, patch-effect, preset-gate, verify, G8, settings-effective, **our config assumptions**, artifact provenance |
| 3 | **backup** | `tools/backup-state.mjs` | no verified backup younger than 12 h |
| 4 | **mutate the live config** (last possible moment) | the switch | the assumption check against the **candidate** fails → restore, start the old engine, exit 5 |
| 5 | **install** | `tools/install-engine.mjs` | candidate/version mismatch, patch apply or audit, **our config assumptions**, swap unproven, restore unverifiable |
| 6 | **start one engine** | `dshw ensure` | the port is not bound, or a second engine is racing the watchdog |
| 7 | **prove it** | the switch's step 5 + this doc | version, compose row count, `ctx.` token count, `{{token}}` count, HTTP on the tokenised URL, `config-assumptions` against the **live** root, and one real turn |
| 8 | **snapshot** | `dsh-update snapshot` | the pin and `state/baseline` disagree (they will, until this runs) |
| 9 | **record** | receipt + `ESTATE.md` + journal | the receipt is missing a phase's exit code or its reason |

## 3. The three properties a phase must have

1. **An undo, registered before it writes.** `switch-yoga.ps1` step 2 copies the live patch to
   `.bak-switch-<stamp>` before touching it; the failure path must *run* that copy back (it did not on
   2026-10-20, and the machine crash-looped). `install-engine` swaps by rename and keeps `engine.prev-*`; it
   restores on a failed `--version` proof.
2. **A written reason for every refusal.** A refusal that says "4 hand patches would be lost" must say which
   and why; a refusal whose real cause is a path separator is a defect in the gate, not in the machine.
3. **Both-ways proof in the repo.** A gate is not trusted until a positive and a negative case exist, recorded:
   `config-assumptions` PASS on 0.2.1-rc.2 and exit 1 with `cordis.patch.yml:4 row "preset-zabz" {{cwd}}` on a
   scratch home; `audit()` 4/4 `registered` on the same trees that previously reported 4/4 `NEEDS-PATCH`.

## 4. What "prove it" means, concretely

A boot is not a turn (L10238). The post-install proof, in order, all of which must be printed:

```powershell
# 1 the tree the port is serving
Get-NetTCPConnection -LocalPort 3099 -State Listen           # <- one pid, not zero and not two
(Get-Content ~/.dsh/engine/node_modules/@deepseek-ai/dsh/package.json -Raw | ConvertFrom-Json).version

# 2 what the composed tree says about the three token classes
node dsh-update/vendor/prefix/<ver>/node_modules/@deepseek-ai/dsh/lib/bin.js --profile web --dump-config
#    rows (expect the live count), ctx.webRuntime=0, {{cwd}}=0

# 3 our config against the LIVE root
node dsh-update/tools/config-assumptions.mjs --engine ~/.dsh/engine --home ~/.dsh     # exit 0

# 4 the page, with the token the engine printed
Invoke-WebRequest <the dsh web: URL from the engine log>                             # 200

# 5 ONE REAL TURN — the only step that proves the prompt assembly, the credentials and the model route
#    (a headless turn needs the key in ITS environment; from an ssh shell it fails with MISSING_CREDENTIAL)

# 6 the record now describes the machine
node dsh-update/lib/cli.mjs snapshot
```

## 5. Open, with the reason each is open

| item | why it matters | what it needs |
|---|---|---|
| config mutation on the **staged** home, applied with the tree swap | today a failed install leaves the live config implying a version that is not installed (F6) | `install-engine` to own the profile patch when it owns the tree |
| `dshw ensure` checks the origins proxy before the engine | a stopped engine makes `ensure` refuse to start it (F8) | reorder: bind the engine, then reconcile the proxy |
| boot-time verification of profile anchors | a corrupt junction cost 22 h of "it will come online in a minute" (F7) | `link-anchors --verify` called from `ensure` and from preflight |
| presets carrying machine-specific absolute paths | a failing child at every boot, invisible because it is non-fatal (F9) | paths resolved at generation time, or `disabled` when absent |
| two branches on the two workstations | every pipeline fix must be applied twice; divergence is how the generator stayed stale | one branch, or a cherry-pick list in ESTATE.md |
| one command for all of it | the phases exist as verbs and scripts; no single entry point enforces the order | `dsh-update switch <ver>` wrapping phases 1-9 with the receipt |

## 6. The rule that would have saved this window

Not a gate: a habit. **The plan is the least reliable document in the estate**, because it was written by a
session that was inside the work and describes the next action. The reliable documents are the lessons entries,
and they are only findable by the words of the failure. So: before the first write, search for the failure
classes, not for the task.
