# 94 — Routing by default: the mesh is what `subagent` means

**Program:** `docs/mesh/`. **Depends:** `90-provider-mount.md` (how the provider is mounted),
`91-resident-dispatch-proof.md` (proof a dispatched child lands on another node),
`82-e2e-run.md` §3.2 (the measurement that produced this change).
**Date:** 2026-09-17, 09:00–09:30 local (13:00–13:30Z). **Author:** a delegated build session, not the owner.
**Owns:** `scripts/make_zabz_preset.py` (the SOURCE of truth), the preset it generates
(`presets/zabz/agent.cordis.yml`), and this file. Nothing else was written.

**What was NOT done:** no engine was restarted anywhere. This laptop's engine, **pid 4880**, booted
08:51:07 and was the same process before and after — a preset change needs no restart, and §6 proves
that from the loader's own source. Nothing was committed, pushed, branched, reset or reverted;
nothing under `packages/` was touched; the owner's live sessions were never prompted, interrupted or
read.

---

## 1. The defect, in his own fleet's words

The mesh was mounted as a **separate tool**, so the choice of where work ran belonged to the model,
and the model chose wrong. Measured, before this session:

* `docs/mesh/82-e2e-run.md` §3.2: *"a parent told to **'fan the work out and report' chose the local
  tool**; a parent told to call `subagent_remote` by name produced six remote children on the named
  node, three times in a row … a **prompt-contract fragility**."* The run's evidence is a child that
  reported `MESH-HOST: zabz-yoga` — its own hostname, i.e. the *client*.
* `journal/entries/wins/W196.md`: the same, framed as a win, because naming the tool by hand fixed
  it — `0-of-1` → `6-of-6` three times.
* `scripts/mesh-e2e.ps1:1451-1457` carries the workaround as a permanent comment: *"a parent told only
  to 'fan the work out' [chose the local tool] … The parent MUST be told to call `subagent_remote`
  by name."*

**That is a routing defect, not a prompt-contract fragility.** The owner should not have to name a
tool to get the behaviour he asked for, and his prompts say "spawn subagents". A tool is chosen by
**NAME**; the fix is therefore to change which provider the name resolves to — not to write a better
sentence.

---

## 2. The options, established from the composed configuration and the shipped source

Three shapes were possible. Every claim below was read this session, on ZABZ-YOGA.

### (a) Disable the local `subagent` row by id, from the preset — **AVAILABLE, and the mechanism is already exercised twice in this very group**

The preset's `delegation` group is a `cordis:group` whose `config:` is a list of loader rows. A
group's list is an ordinary loader entry tree — `cordis-plugin-group` → `EntryGroup.update()` →
`Entry.create()` — and the loader honours `disabled` **per entry, including the `!!js` form**:

> *"Effective disabled state: a `!!js` expression evaluates against the loader context."*
> — `cordis-plugin-loader/src/config/entry.ts:100-108`; the field is declared at `:19`,
> and `Entry.refresh()` returns early when disabled (`:126`).

Two rows in the group already rely on it: `tool-subagent-codex` / `tool-subagent-claude-code` carry
`disabled: true`, and `tool-subagent-list-agents` carries
`disabled: !!js process.platform === 'win32'` — both in the file under review, both shipped and
working.

**And the host plane does not offer the local tool as a backstop.** The `web` profile's own patch
layer disables the HOST copy of the same row for the same reason — delegation tools in `web` are
granted per *agent*, by the preset. Measured this session with
`node …/dsh/lib/bin.js --profile web --dump-config` (exit 0, 620 lines):

```
279: - id: tool-subagent
280:   name: '@deepseek-ai/dsh-tool-subagent'
281:   config:
282:     provider: spawn
283:     toolName: subagent
284:     backgroundMode: continuable
285:   disabled: true
```

So a session's `subagent` tool comes from the preset **alone**, and disabling it there is total.

### (b) Make the remote provider the *default provider*, leaving the tool's name alone — **NOT AVAILABLE: there is no such thing**

`ctx.subagents` is a *named-provider registry*; there is no default and no precedence rule.
`dsh-subagent/README.md:69` — *"One service, many providers. The service is a named-provider
registry; each backend registers under a unique name and a request picks one **by name**"* — and the
tool's own config makes the provider mandatory: `provider: z.string().required()`
(`dsh-tool-subagent/lib/index.js:252-254`). A tool row is the only place a name is bound to a
provider.

**And keeping both rows under one name is not an option either:** two registrations of one tool name
in one scope throw —

> `tool "subagent" is already registered in this scope`
> — `dsh-tools/lib/index.js:2538`

so "leave the local one alone and add the remote one beside it" fails loudly at preset mount, which
takes session creation down with it.

**(b) therefore collapses into (a)**: the way to make the remote provider serve the name `subagent`
is to bind the row named `subagent` to it. The difference between (a) and (b) was never a mechanism;
it was whether the name is given away or shared, and sharing it is impossible.

### (c) A prompt-level norm — **REJECTED AS THE MECHANISM, because it was already tried and measured to fail**

§1 *is* the trial. A norm the agents ignore is not an implementation; it survives here only as the
*complement* to (a) — the sentence an agent follows when the mesh is unreachable (§4.3).

### The hard constraint that decided the final shape

**A single point of failure is worse than local execution.** Disabling the local tool outright would
mean that a session with the office desktop unreachable — or on a node where the bundle is not
mounted, or on Linux — cannot spawn a child by any route. That is one machine holding every fleet in
the house, and it is the failure class this harness has paid for before.

So the local capability is **renamed, not deleted**: `subagent_local`, the same `spawn` provider
under a name that carries its own warning. A fallback taken under a *different tool name* is visible
in the transcript by construction; a fallback taken under the *same* name would be invisible — and an
invisible fallback is a claim about where work ran that is not true.

---

## 3. What was implemented

`scripts/make_zabz_preset.py` (the source of truth; the generated preset is never hand-edited) now
rewrites the local delegation row instead of appending a second one. The `zabz` preset's delegation
group composes as:

| tool name | provider | where the child runs | why |
|---|---|---|---|
| **`subagent`** | `remote-ssh` | **another node** (ZABZ-TECH by default) | the name an agent reaches for; the default by construction |
| `subagent_remote` | `remote-ssh` | another node | the same provider under its old name — a deliberate alias, §3.1 |
| `subagent_local` | `spawn` | **this machine** | the named fallback; label its results LOCAL |
| `subagent_fork` | `fork` | this engine's process | unchanged; continuation with this conversation's history, not fan-out |

The generator's anchor is checked, not assumed: if the local row can no longer be found exactly once
it exits 2 rather than generating a preset whose `subagent` is still local (`--check` cannot see a
silent no-op).

The persona gained rule **1c**, which is the only *sentence* in the change — it exists for the
failure path, not for the happy one:

> **1c. The fleet runs on the MESH — `subagent` is a child on another machine.** … The local ones say
> so in their own names: `subagent_local` runs the child on THIS machine, and `subagent_fork` runs it
> in this engine's own process … **Never fan out locally while the mesh is reachable.** When a
> `subagent` call fails — ssh, the target node, the provider — quote the provider's own diagnostic,
> say in one line that the mesh was unreachable, and then choose explicitly: do the work yourself, or
> fall back and mark every result that came from `subagent_local` or `subagent_fork` as LOCAL in your
> report. A fallback nobody can see is a claim about where work ran that is not true. If your tool
> list has no `subagent` at all, the mesh provider is not mounted on this machine: say so in one line
> and carry on with what you have.

### 3.1 The alias, and why it is deliberate rather than sloppy

`subagent_remote` is kept, bound to the same provider, because three scripts this change does not own
assert on that string — `mesh-provider-install.ps1:239`, `mesh-restart-at-0700.ps1:706`,
`mesh-e2e.ps1:1457` — and because every prompt or document written before today that says "call
`subagent_remote`" still means the mesh. Retiring it belongs to whoever updates those three callers;
until then it is one redundant tool row, and it is the reason this change breaks nothing.

### 3.2 Two config details that are load-bearing, not taste

* **`maxDepth: provider-managed` on both remote rows** — required: an out-of-process child advertises
  no capabilities and `dsh-tool-subagent` refuses a numeric maxDepth on a provider without
  `depthLimit` (`lib/index.js:377`). `backgroundMode` must stay `one-shot` on them: the provider has
  no `prepareContinuable`, and `continuable` would fail the mount-time assertion at `:380` and take
  the whole preset down.
* **`backgroundMode: one-shot` on the local fallback, changed from `continuable`** — the shipped row
  emits a *system-prompt section* reading "Use \<toolName\> in the background by default" whenever it
  is both background-enabled and continuable (`lib/index.js:576-580`). Left continuable, the fallback
  would put a prompt in front of every agent telling it to prefer `subagent_local` — a sentence
  fighting the whole change. One-shot silences that section and still leaves `run_in_background: true`
  available for a parent that wants a job id.
* **No parallelism was lost.** The remote rows stay foreground
  (`enableRunInBackground: false`, the shape `90` §2 chose so a parent collects each child's result
  instead of polling a job), and that costs nothing across a fleet: the tool declares
  `isConcurrencySafe: () => true` (`lib/index.js:489`), so several `subagent` calls in one assistant
  message are dispatched together rather than in series.

---

## 4. The failure mode, designed rather than hoped for

The mesh is now the default, so its absence must be a *stated* state, not a silence. Three cases,
what the agent sees, what it reports, and what it may do.

### 4.1 The provider is mounted and a dispatch fails (ssh, target node, broker)

* **What it sees.** The tool exists. The call returns an **error carrying the provider's own
  diagnostic** — `remote-fanout` settles every transport fault as `stopReason: 'error'` with a
  diagnostic (`packages/plugin-remote-fanout/lib/provider.js:252-281`: *"could not launch the ssh
  transport …"*, *"the remote turn did not finish within … ms"*, *"the transport reported host …, which
  is not one of the configured target hosts"*), and the shipped tool turns a non-`completed` stop
  reason into a thrown error (`dsh-tool-subagent/lib/index.js:287-296, 315-317`). This path has been
  exercised for real: `_scratch/o1/kill-test` ran a dispatch at a dead node and the parent reported
  *"failed, exit 255, hostname mesh-dead-node-1 unresolvable … report the result honestly, not
  fabricate success."*
* **What it reports.** Rule 1c: the diagnostic verbatim, one line saying the mesh was unreachable,
  and then an explicit choice.
* **Can it fall back?** Yes — `subagent_local` (this machine) or `subagent_fork` (this process), and
  every result from them must be marked `LOCAL`.
* **Is the fallback visible and logged?** The tool **name** is in the session store's own `tool/call`
  record — `docs/mesh/91-resident-dispatch-proof.md` §4 shows the shape (`"name":"subagent_remote"`) —
  so which tool ran is a fact of the log, not a claim in a summary.

### 4.2 The provider is not mounted on this machine

A node where `dsh-plugin-remote-fanout` is not in the profile's bundle list (a Linux or macOS node, or
a Windows node before the install). The shipped row logs *"subagent provider \"remote-ssh\" not
registered yet; the \"subagent\" tool will register when it appears"* and waits
(`lib/index.js:565-575`) — the preset still mounts and **`subagent` is simply absent from the tool
list**. There is no local tool wearing the name, so nothing can be mistaken for the mesh.
*What the agent sees:* `subagent_local`, `subagent_fork`, and no `subagent`.
*What it reports:* one line saying the mesh is not mounted here, then it works with what it has.

### 4.3 Nothing else is reachable

`subagent_local` and `subagent_fork` need no network, so "cannot spawn a child at all" is not a state
this design can reach while the engine is alive. If even those are refused, rule 1 still applies: the
agent does the work itself and says why. **Halt-to-report is not one of the four permitted endings.**

---

## 5. The checks, and what they actually measured

Run on ZABZ-YOGA, 2026-09-17, with the owner's engine (pid 4880) untouched.

| # | claim | command | result |
|---|---|---|---|
| 1 | the generator and the generated preset agree | `python scripts/make_zabz_preset.py --check` | `zabz: in sync with the generator`, exit 0 (it printed `DRIFT` before the regeneration — the failure was demonstrated, not assumed) |
| 2 | every harness invariant still holds | `pwsh scripts/harness-verify.ps1` | **13 ok, 0 failed**, exit 0 — including `preset deployed to ~/.dsh: preset hash match=True; skills match=True` |
| 3 | the composed profile still composes | `node …/dsh/lib/bin.js --profile web --dump-config` | exit 0, 620 lines; rows `remote-fanout` (with its `remote-ssh` deployment config), `tool-subagent-remote (disabled)` at the host plane, `plugin-mesh-http` |
| 4 | the deployed copy is the repo copy | `Get-FileHash` on both | identical, `AD69A4BC…05C2C52` |
| 5 | the preset parses in the **Loader's own dialect** | `js-yaml load(…, {schema: entryListSchema})` (`cordis-plugin-include`, the exact call `fileComposition` makes) | repo and live both parse; **41 rows, no duplicate loader ids**; the four delegation rows present with the intended `provider`/`toolName` |
| 6 | every `tool-subagent` row satisfies the **shipped** config schema | `Config(...)` from `@deepseek-ai/dsh-tool-subagent` on each row's config | all four accepted: `subagent`→`remote-ssh`, `subagent_remote`→`remote-ssh`, `subagent_local`→`spawn` (one-shot), `subagent_fork`→`fork` (continuable) |
| 7 | the mesh install's own invariants | `pwsh scripts/mesh-provider-install.ps1 -Check` | **1 problem, and it is not this change** — see §7 |

Checks 5 and 6 are the cheap gate this change made available: they read the deployed file with the
Loader's dialect and the plugin's own schema, start nothing, spend nothing, and would have caught a
typo in a key, a duplicate row id, or a `toolName` collision. What they cannot do is prove the
composition *mounts*, because mounting needs the host services — that is §8.

---

## 6. Does the owner need to restart the engine? **No.**

The question is decided by the loader, not by convention, and it was read this session:

1. **Discovery is unmemoized.** *"`list()` and `resolve()` re-read the roots on every call so a preset
   authored while the process runs is visible immediately"* — `dsh-agent-presets/lib/index.js:1152-1158`.
2. **A session resolves its preset when the session is created.** `session/create` →
   `presets.mount(agentCtx, resolvedId)` — `dsh-api-session-controller/lib/types/agent.js:382-391`;
   `mount()` re-resolves and composes — `dsh-agent-presets/lib/index.js:1499-1506`.
3. **A changed composition file forces a re-composition.** The standing mount is keyed by the file's
   `mtimeMs` + `size` stamp and re-created when it differs — `ensureStanding` at `:1767-1776`,
   `compositionStamp`/`sameStamp` at `:1806-1820`.

So the next session the owner opens gets the new composition, and the sessions already running keep
the composition they mounted under. **The change is therefore live now for new sessions and required
no restart — which is also why `pid 4880` was never touched.**

*Honest limit on (2)*: `ensureStanding` is single-flight per preset id, and a child agent binds to its
parent's standing composition rather than re-resolving (`:1507-1521`), so a child created by an *old*
session inherits the old tool set. New sessions, which is what the owner opens, get the new one.

---

## 7. One thing found on the way, and it is not this session's to fix

`pwsh scripts/mesh-provider-install.ps1 -Check` reports **1 problem**: the live patch layer
`C:\Users\ezabz\.dsh\profiles\web\cordis.patch.yml` (10,928 bytes) differs from the repo's
(12,598 bytes) and would boot **without** the newest provider config.

* **It is not caused by this change.** `profiles/web/cordis.patch.yml` was not edited here, and
  `python scripts/sync.py` did not write it (this session's dry run and apply both reported
  `profile web: cordis.patch.yml up to date` at the time).
* **The repo copy is ahead**: it carries 22 lines the live copy lacks, describing `placement: broker`
  and `docs/mesh/92-provider-placement.md` — another session's in-flight edit to the provider row.
  Between this session's apply and a later dry run the file changed on disk, so **another session is
  writing it right now** (`git status` also shows uncommitted `packages/plugin-remote-fanout/lib/{nodes,placement,broker-client}.js`).
* **Consequence, stated precisely:** the live layer is the *old* provider config, so `desktop-ts`
  remains the target exactly as `91-resident-dispatch-proof.md` measured it. Whoever owns the
  placement work must deploy it; deploying it from here would push another session's half-finished
  edit into the owner's engine, which is not this session's to do.

---

## 8. What could not be verified, stated as refusals

* **That the changed preset mounts, and that a session on it sees the four tools.** The only reader of
  a session's tool catalog is a session (`90` §4.1: there is no remote surface that lists registered
  tools), so this needs one prompt. It was deliberately **not** spent — it is one command for a later
  session, and it is the same command `91` §7 used. In a **new** session on the `zabz` preset:
  *"Name every tool you have whose name contains `subagent` — names only, make no tool calls."*
  Expected: `subagent`, `subagent_remote`, `subagent_local`, `subagent_fork` (plus
  `list_agents`/`send_message` from the control tool). Then, to close routing: *"Call `subagent` once
  with the task `run hostname and reply MESH-HOST: <hostname>`, then report its raw output."* — the
  child's own `MESH-HOST: zabz-tech` line is the proof, exactly as `91` §10 accepted it.
  *Free variant, no model call:* the parse + schema checks 5 and 6 of §5 can be re-run as-is.
* **That an agent left to its own judgement picks `subagent` over `subagent_local`.** Nothing
  mechanical forbids the fallback while the mesh is up; the deterrent is the name plus rule 1c. If the
  measurement says otherwise, the next lever is a `!!js` gate on the fallback row — which is available
  (§2a) but was rejected here because changing it needs an engine restart, i.e. it would reproduce the
  very fragility this file is about.
* **That the alias is actually redundant.** It was kept for three callers that were read, not run;
  `mesh-e2e.ps1` was not executed against the new preset, and its prompt still says "never the plain
  `subagent` tool" — stale wording that now names the mesh. It should be re-run, and that prompt
  updated, by whoever owns that script.
* **Anything about ZABZ-TECH, `secratary`, the Mac Mini or Linux.** Not touched. The `zabz` preset is
  deployed per home, so this laptop is the only node known to have the new composition; the others get
  it at their next `sync.py`.

## 9. Where the next session starts

1. `python scripts/make_zabz_preset.py --check` → in sync; `pwsh scripts/harness-verify.ps1` → 13/13.
2. The two rows to change if the fallback ever has to be withdrawn or re-gated live in
   `scripts/make_zabz_preset.py` → `DELEGATION_ROWS` (never in the generated file).
3. The three callers that still name `subagent_remote` by string, for a follow-up that can retire the
   alias: `mesh-provider-install.ps1:239`, `mesh-restart-at-0700.ps1:706`, `mesh-e2e.ps1:1457`.
4. The `placement: broker` work in the repo's `profiles/web/cordis.patch.yml` is **undeployed** (§7).
