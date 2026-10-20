# DELIVERY — how an engine update reaches a machine, and why it is shaped this way

Written 2026-10-19, after reading the whole history of this pipeline (`README.md`, `RUNBOOK.md`,
`SPEC.md`, `FINDINGS.md`, `STATE-COMPAT.md`, `state/history/events.tsv`, the four `state/switch-*`
directories, and the journal's ten handoffs from 2026-10-05). Every claim about the present is a
measurement taken that night; the episode references are the records themselves.

---

## 0. The one rule this document exists to enforce

> **One install root per machine. `~/.dsh/engine`. The vendor prefix is a STAGING area.**

For eight days this estate had two: the pin named `dsh-update/vendor/prefix/0.2.0-rc.2`, and the
engine every process actually loaded was `~/.dsh/engine`. Measured 2026-10-19, `dsh-update status` on
ZABZ-TECH printed both, with `contract sha256 MISMATCH` and `tree sha256 MISMATCH`. Three independent
things point at the home tree: `multi-window/dshw.ps1:309` probes it before the npx cache,
`packages/plugin-remote-fanout/lib/nodes.js:84,98` names it as the bin for mesh children, and both
machines' engines are running from it (YOGA pid 11640, TECH pid 8068).

A `promote` in that state would have written `dshInstall` to the vendor prefix and swapped the estate,
at the next boot, onto a tree carrying none of the hand patches below. That is the seam this
document's rule closes.

## 1. Who owns what

| thing | owner | location |
|---|---|---|
| **staging**: fetch a candidate, judge it | `dsh-update` verbs | `dsh-update/vendor/prefix/<ver>` |
| **judgment**: is this candidate safe for THIS config | `analyze`, `patch-effect`, `preset-gate`, `verify`, `settings-effective`, `preflight` | `dsh-update/state/candidates/<ver>/` |
| **delivery**: put the proven bytes where the machine runs | `tools/install-engine.mjs` | `~/.dsh/engine` |
| **state**: pin, launcher knob, audit trail | `promote` (pipeline) | `dsh-update/state/pin.json`, `multi-window/windows.json`, `state/history/events.tsv` |
| **patches to package files** | `patches/registry.json` + `lib/patches.mjs` | any tree, before it goes live |

`install-engine.mjs` resolves the live root through `lib/live-root.mjs`, and `promote` now resolves it
through the same module, so the pin can no longer name a different tree from the one that boots.

## 2. The operation, in order, with the commands

```powershell
J = pwsh -NoProfile -File dsh-update\bin\dsh-update.ps1

$J check                                   # what the registry offers; classifies against the pin
$J snapshot                                # describes the PINNED engine -> state/baseline
$J fetch <ver>                             # the only npm install; into vendor/prefix/<ver>
node dsh-update\lib\stage-home.mjs --from <liveHome> --candidate dsh-update\vendor\prefix\<ver> `
     --out C:\Users\<you>\.dsh-staged\<ver> --profiles-from profiles
node dsh-update\tools\link-anchors.mjs --staged C:\Users\<you>\.dsh-staged\<ver> --from <liveHome>
$env:DSH_HOME='C:\Users\<you>\.dsh-staged\<ver>'; $env:DSH_STATE_HOME='C:\Users\<you>\.dsh'
$J preflight <ver> --full --accept-session-format-upgrade   # one GO/NO-GO over every blocking guard
node dsh-update\tools\backup-state.mjs      # BACKUP-REPORT.json, ok:true, younger than 12h
node dsh-update\tools\install-engine.mjs --version <ver> --dry-run   # prints every step, writes nothing
node dsh-update\tools\install-engine.mjs --version <ver>             # stages, patches, audits, swaps
# restart applies it — the next engine start, not this session
$J status                                   # the measured engine must report <ver>
```

### The step that is not obvious, and cost a NO-GO on 2026-10-19

`link-anchors.mjs` is not decoration. `stage-home.mjs` copies 44 config files and deliberately skips
`node_modules`, but OUR OWN plugin bundles resolve from the profile's anchors, and the engine **skips an
unresolvable bundle without failing** (exit 0):

```
dsh: skipping profile bundle "dsh-plugin-attention": cannot resolve profile bundle
     "dsh-plugin-attention" from the dsh installation or ...\profiles\web
```

Measured that night on ZABZ-TECH: without the anchors the staged home composed **410** rows instead of
the live home's **421**, and `remote-fanout`, `tool-subagent-remote` and `spend-guard` were absent — so
`patch-effect` said BREAKS=3 and `verify` G2 said "a patch target is not a row in the composed tree",
three findings about the 0.2.1 candidate that were artifacts of the staging. With both anchors present:
421 rows, our ids present, 0 bundles skipped, on the same engine. `preflight` then went from NO-GO (3 of
7 blocking guards) to **GO, 7 of 7**.

Related, and the reason the anchors are not enough on their own: `profiles\<profile>\package.json` — the
list of 11 bundles this profile mounts — exists **only on the live machine**; the repo has no such file,
and `stage-home` writes a 207-byte stub naming only the two upstream bundles. The live one was copied in
by hand that night (706 bytes, 11 bundles). Until the roster is committed and `sync.py` publishes it,
every staged home has to be given it explicitly.

`preflight` is the only gate that matters for the decision; it re-runs `analyze`, `patch-effect`,
`preset-gate`, `verify` and `settings-effective` itself, and its GO is what `install-engine` reads back
from the history.

## 3. What `install-engine.mjs` refuses on, and why each refusal exists

| refusal (exit 2, nothing written) | the episode behind it |
|---|---|
| the candidate prefix is absent or its `package.json` disagrees with `--version` | the 0.1.7 fetch that was judged against a stale prefix |
| no verified `BACKUP-REPORT.json` younger than 12h | 2026-10-05: the crash that bracketed the switch, with no verified backup underneath the work |
| `verify.json` not bound to the contract on disk | `promote` condition 1's own rule; a re-resolved dependency invalidates a pass |
| the last `preflight` row for the version is not GO | **the 2026-10-05 04:06:35Z anomaly**: a NO-GO row followed by a successful promote 2.4 s later, unexplainable from the record because the switch wrote its preflight JSON to `%TEMP%` and none survives |
| the staged copy does not run its own `--version` | 2026-09-28: a verdict about a fixture presented as this machine's state |
| any registered patch does not apply or does not verify | P3170: a hand patch silently lost by the next install |
| any `.bak-harness-*` pair in the OLD tree is neither registered nor already matched byte-for-byte by the new tree | P3170 again, measured: 6 patched files, only 4 with a patcher |

Exit codes: `0` installed and verified · `2` a precondition refused, nothing written · `3` a step failed
and the previous state was restored · `4` the swap could not be done under a running engine — the staged
tree is left in place and the live tree untouched, do it in a quiet window · `5` a step failed and the
restore could not be verified, attention required.

## 4. The swap is a rename, and the old tree is kept

`<live>` → `<live>.prev-<oldver>-<stamp>`, then `<live>.staged-<ver>` → `<live>`. Nothing is deleted at
any point: the previous tree is the way back, and the receipt names it. If Windows refuses the rename
because the running engine holds a file, the tool refuses with exit 4 **and writes nothing** rather
than repointing the launcher at a half-built tree — a failed swap must leave the machine exactly as it
was, which is the rule the previous switch's own header states and this one inherits.

## 5. The patch registry — the thing that was missing

`dsh-update` has always tracked patches to the *cordis composition* (`SPEC.md` B3/B4, G2/G6). It never
tracked a patch to a package file, and on 2026-10-13 that was filed as P3170. Measured on ZABZ-YOGA
2026-10-19, the live tree carries six patched files, each with a `.bak-harness-*` sibling as evidence:

| file | patcher | registered |
|---|---|---|
| `dsh-llm-deepseek/lib/index.js` | `scripts/patch-dsh-malformed-tool-input.py` | yes |
| `dsh-subagent/lib/index.js` | `scripts/patch-dsh-settlement-crash.py` | yes |
| `dsh-web-frontend/dist/assets/vendor-*.js` | `scripts/patch-dsh-web-currency-math.py` | yes (resolved by glob — the filename is hashed) |
| `dsh-client-ui-workspace/lib/client.js` | `multi-window/tools/patch-window-blank-isolation.mjs` | yes |
| `dsh-session-persistence-jsonl/lib/index.js` | *none — four hand patches, 2026-10-05* | **no** |
| `dsh-client-ui-primitives/lib/StateDot.module.css` | *none — one hand patch, 2026-10-05* | **no** |

The two unregistered ones are not silently carried: `lib/patches.mjs` compares the new tree's file to
the old **patched** file, and if it differs the install fails and names the file. What closes them
properly is a patcher each, which is a small, named piece of work rather than a blind spot.

## 7. What 0.2.1 changed that our config had assumed — measured, 2026-10-19

Three things broke **after** a GO preflight and a clean compose test, in the owner's hands. Each is now either
fixed in config or checked by a tool, and each is written down here because no gate in the pipeline could see it.

| what broke | the assumption | the 0.2.1 reality | how it was caught | the control now |
|---|---|---|---|---|
| `web boot: 20 entries did not activate … pending (waiting for service: remoteAccess)` | our `connection` row config carried `trustedHosts: !!js ctx.webRuntime.trustedHosts` | the row injects `[webStartup]`, not `[webRuntime]`; the loader throws and the REQUIRED `dsh-client-connection` plugin never activates | the owner's screen | `tools/config-assumptions.mjs` (A) — every `ctx.<svc>` must be in that row's `inject` list in the candidate's own default tree |
| every turn: `unknown prompt variable "{{cwd}}"` | each preset's persona suffix said `Your working directory is {{cwd}}` | only `provider` and `model` are registered prompt variables | the owner's screen | `tools/config-assumptions.mjs` (B) — every `{{token}}` must be one this line registers |
| headless turns and every mesh child: `MISSING_CREDENTIAL … route "deepseek-official"` | the engine reads `~/.dsh/.credentials.yaml` (a 2026-09-11 nested shape) | that shape is no longer read; the engine names its two supported routes in the error | a failed `subagent` dispatch | `DEEPSEEK_API_KEY` at user scope, and a headless turn as a **post-install check** (below) |

Two of those were config we own that **restated an upstream fact** — the classic B11 shape from `SPEC.md`. The
lesson is not "read the changelog": it is that an expression or a token referring to an upstream surface is an
assumption, and assumptions must be checked against the candidate, not against our own text.

## 8. After any install: four checks, in this order

A GO preflight is not an upgrade. All three failures above happened *after* one.

```powershell
node dsh-update\tools\config-assumptions.mjs --engine $env:USERPROFILE\.dsh\engine --home $env:USERPROFILE\.dsh   # A+B
node <engine>\node_modules\@deepseek-ai\dsh\lib\bin.js --profile headless "Reply with exactly: OK"   # credential path
# boot the web profile on a spare port and LOAD THE PAGE with its token; a boot alone proves nothing, because the
# client UI is composed when a page is requested — that is where 20 entries "did not activate" appeared.
# then: a NEW session mounts on EACH preset, and a pre-upgrade session still opens (RUNBOOK §7).
```

The third check is the one that misled me tonight: a spare-port boot with an empty log looked clean, while the
client request against the same tree produced the activation failure. **A boot is not a boot test.**

## 9. What is still open (and is not a surprise)

0. **A config change applied while an engine is running is REVERTED, not raced.** The running engine owns
   `profiles/<p>/cordis.patch.yml` as its settings document and rewrites it from memory on its own cadence
   (measured 2026-10-19: two correct fixes were gone within minutes, twice). The order is: stop every engine →
   edit → verify the file on disk → compose-check with the target binary → start one engine → verify again.
   Journal `L10302`.

1. **The switch's preflight JSON is not kept** (`switch-engine.ps1:1218` writes it to `%TEMP%`). The
   2026-10-05 anomaly cannot be settled from the record because of it. Fix: write it under
   `state/logs/`.
2. **`settings-effective` was reported as "no usable artifact" on both machines — FIXED 2026-10-19.** The module
   was working; the verb overwrote its `ran:false` record with a stub whose reason was a JSON preview, destroying
   the diagnostic. The verb now keeps the module's record (`lib/cli.mjs`, journal `L10369`). It reports
   `present=17 absent=0 different=0 BREAKS=0` on ZABZ-YOGA.
3. **`stage-home.mjs` does not recreate the module anchors** and writes a stub `package.json`, so it
   cannot build a home that is judged fairly without the two manual steps in §2. That is a defect in the
   tool, not in this document.
4. **`profiles/<profile>/package.json` is not in the repo.** The 11-bundle roster that decides what this
   machine mounts exists only at `~/.dsh/profiles/web/package.json`.
5. **Two patches have no patcher** (§5).
6. **`switch-engine.ps1` has not been run since its `expectRoot` was re-pointed** at the live root
   (2026-10-19). It is edited and syntax-checked, not exercised; the switch suite is the way to
   exercise it before anyone uses `-Rollback` or a real switch again.
7. **`~/.dsh/engine/package.json` on ZABZ-YOGA carries the floating range `^0.2.0-rc.2`** (mtime
   2026-09-30) — the same shape that let `npx` float 0.1.5-rc.1 to 0.2.0-rc.2 on 2026-09-30. An
   `npm install` in that directory could move the engine without any gate. Pin it exactly.
