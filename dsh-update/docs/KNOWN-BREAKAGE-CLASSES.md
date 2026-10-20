# KNOWN-BREAKAGE-CLASSES — read this BEFORE touching an engine, a profile patch or a preset

Every row is something this estate has already paid for in an outage. The point of the table is that a session
arriving with a *plan* can search for the *failure* instead of re-learning it.

**How to use it.** `journal.py search "<search words>" --kind lessons` for the row you are about to touch, and
read the entry. Then run the gate. If a row has no gate, treat that as an open item, not as permission.

| class | how it presents | record | the gate that catches it now | search words |
|---|---|---|---|---|
| connection injection renamed (`webRuntime` → `webStartup`) | required plugin `connection` fails: `cannot get property "webStartup" without inject`; client UI shows entries "pending (waiting for service)" | L10238, L10367 | `node dsh-update/tools/config-assumptions.mjs --engine <root> --home <cfg>` (A: `ctx.<svc>` vs the row's `inject`); blocking in `preflight` and in `install-engine` | `webRuntime webStartup connection inject` |
| prompt-variable token an engine does not register (`{{cwd}}`) | every turn dies: `unknown prompt variable "{{cwd}}" in section "deployment:persona-suffix"; registered variables: provider, model` | L10238, L11646 | same tool, check (B); blocking in `preflight`, `install-engine`, and switch STEP 2.5 | `cwd persona-suffix prompt variable` |
| a live fix undone by its generator | the breakage returns after a regeneration, with no edit by anyone | L11646 | grep the generator in the same hour you fix the live file | `generator preset rows regenerate` |
| hand patches lost on install (P3170) | install refuses: "the install would silently lose N hand patch(es)" | P3170, `registry.json` | `install-engine` patch audit; a genuinely-needed patch must become a patcher in `scripts/` | `P3170 unregistered patch bak-harness` |
| the audit itself is separator-blind on Windows | the same refusal, naming files that the registry already covers | L11646 | fixed in `lib/patches.mjs` (`relNorm`); regression test: audit rows must read `registered` on a Windows host | `audit covers path.relative separator` |
| session format one-way door (v4) | `verify` G8 not ok; a pre-v4 session opens but is rewritten | `promote-reading.mjs`, G8 | `preflight --accept-session-format-upgrade` records the decision; never accept silently | `G8 session format v4 door` |
| settings no longer read (0.1.7+) | settings silently ignored: provider, permission posture, spend ceilings | `settings-effective`, L on 2026-10-05 | `dsh-update settings-effective <ver>` (blocking when it ran) | `settings-effective settings.yaml 0.1.7` |
| the rename seam (0.1.5 → 0.1.7+) | `dsh-agent-presets` / `dsh-workflow-worker-thread` exist on one side only | `switch-engine.ps1`, STATE-COMPAT.md | `preset-gate` + the coupled `switch-engine.ps1`, engine and config in one step | `rename seam preset package 0.1.5` |
| credential store shape changed | `MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official"` | L10238 | export `DEEPSEEK_API_KEY` at user scope; a headless turn is the only check | `credentials deepseek-official MISSING_CREDENTIAL` |
| staged home loses our bundles | composition is short (410 vs 422 rows) and every gate on it lies | L10367, `link-anchors.mjs` | `tools/link-anchors.mjs` after `stage-home`; compose-row count compared to live | `stage-home anchors bundles roster skipped` |
| a corrupt junction Node cannot follow | boot dies before the port binds: `UNKNOWN: unknown error, realpath '...node_modules/<pkg>'`, errno −4094 | L11646 | `link-anchors --verify` (open); today: `node -e "fs.realpathSync(<each profile link>)"` | `realpath UNKNOWN junction reparse` |
| `dshw ensure` refuses while the engine is down | "origins proxy is not answering on :19200 … REFUSING", on a machine whose engine is simply stopped | L11646 | start the engine directly, then `dshw ensure` to reconcile (open: reorder the checks) | `origins proxy 19200 ensure refusing` |
| baseline drift after an install | next `preflight`: `baseline fresh` FAIL, `pin.contractSha256=… on disk=…` | L11646 | `dsh-update snapshot` as a post-install step | `baseline fresh snapshot pin contractSha256` |
| a stale backup blocks the install | `the newest verified backup … is 23.2h old` | `install-engine.mjs` | `node dsh-update/tools/backup-state.mjs` (29 s on ZABZ-YOGA) | `verified backup 12h BACKUP-REPORT` |
| a preset carrying another machine's absolute path | a child process dies at every boot: `Cannot find module 'C:\Users\<other>\...\server.mjs'` | L11646 | `config-assumptions` does not cover paths yet; grep presets for `C:\Users\` | `preset absolute path other machine MODULE_NOT_FOUND` |
| one version's upstream surface hardcoded in a control | the control itself becomes the outage, silently, on the next version | L11646 (F10) | version-keyed tables that refuse an unmeasured version (exit 3) | `hardcoded registered variables prompt set version` |
