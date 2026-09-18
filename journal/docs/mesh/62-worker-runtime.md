# 62 — Worker runtime: what it actually takes to make a Linux or macOS node a usable worker

**Program:** `docs/mesh/` (the series' runtime volume; it depends on `20-placement.md` §1/§3/§4/§8 and
`50-transport.md` §2, and nothing depends on it being read first).
**Date:** 2026-09-16 late / 2026-09-17 early UTC. **Author:** a delegated research session (agent 62), not the
owner. **Status:** analysis + a decision. **No install was run on any node. No engine was started,
stopped, restarted or reconfigured. No git command that changes state was run. This is the only file this
session wrote.**

---

## 0. The premise this document corrects

The brief behind this volume says *"the fleet is effectively two Windows machines because the other nodes
have no Node runtime, and `20-placement.md` defers 'worker nodes' to Phase 2/3 without saying what to
install."* Two of those three clauses are true and one is not, and the correction changes the answer:

1. **It is not "what to install" that was missing — the fleet already has a working, measured Linux
   runtime recipe, on `secratary`.** It is a nodejs.org tarball at `/home/zabz/node/bin/node`
   (**v22.23.2**), a plain `npm install` into `~/dsh-engine`, and a systemd unit. §1.2 and §3.4 read it
   out. The work is **copying** that recipe, not designing one.
2. **The decisive question — is there a way to run DSH without a browser — has an unqualified yes**, and it
   is a shipped, documented one-shot mode: `dsh --profile headless "<task>"`. Two further stdio protocols
   exist. **§2 is the answer, quoted from source.** This is the finding that most changes the placement
   design, because it means a worker node does not need a browser, a phone, a Serve entry, or a human.
3. **`mac-mini` is not a bare node.** MEASURED this session: it has `node` v24.19.0 at `/usr/local/bin`,
   v24.12.0 at `~/.local/node-v24.12.0-darwin-arm64`, `~/.dsh-install/node_modules/@deepseek-ai/dsh` at
   **0.1.5-rc.1**, and **a DSH web engine running right now** on `127.0.0.1:3099`. `10-inventory.md` §8
   and the brief's own context block both record it as having no runtime; that reading came from a
   non-interactive `PATH` of `/usr/bin:/bin:/usr/sbin:/sbin` and is wrong. Conversely
   `zabz-tech-linux` has no Node *and* no `~/.dsh`, exactly as recorded.

Every number below carries a **SOURCE** and a **DATE**. Where a check failed or was not run, it says
**could not verify** — an empty result is a refusal, not health.

---

## 1. The minimum that must exist on a node

### 1.1 The runtime floor: Node **>= 22**, and why a lower one fails *silently*

| constraint | evidence | consequence if unmet |
|---|---|---|
| `import.meta.main` must exist | READ, `@deepseek-ai/dsh/lib/bin.js:168` — `if (import.meta.main) await runCli();`; the same idiom at `dsh-subprocess-local/lib/runner.js`. **PUBLISHED**: *"`import.meta.main` … Added in: v24.2.0"* — [Node.js v24.x ESM docs](https://nodejs.org/docs/latest-v24.x/api/esm.html) (fetched 2026-09-16); backported to the 22 LTS line as **v22.18.0** — [node v22.18.0 LTS release](https://github.com/nodejs/node/releases/tag/v22.18.0) (2025-07-31). | **Total silent no-op.** `undefined` is falsy, so `runCli()` is never called: the process exits **0** having done nothing, printed nothing, and listened on nothing. This is the single worst failure shape in the whole pipeline and it is why "Node 18 from apt" must never be used. |
| `node:zlib` zstd must exist | READ, `dsh-session-persistence-jsonl/lib/index.js:15` imports `zstdCompress, zstdDecompress, zstdDecompressSync` from `node:zlib`, called at `:1263` on the **session-log read path**. **PUBLISHED**: zstd in `node:zlib` landed in **v23.8.0**, backported to **v22.15.0** — [node v23.8.0 release](https://github.com/nodejs/node/releases/tag/v23.8.0) (2025-02-13). | Every session load throws. Hard failure, not silent. |
| the repo already states the floor | READ, `scripts/serve-phone.sh:230` — `[ -x "$NODE" ] || { echo "node not found at $NODE (the harness needs Node >= 22)"; exit 2; }` | — |
| a **measured** known-good runtime | MEASURED 2026-09-16 21:5xZ, `ssh secratary-ts '/home/zabz/node/bin/node -v'` → **v22.23.2**, and that exact binary is the one running the live `phone-engine` process (pid 906634, up 15 h 37 m). | 22.23.2 is proven. It is the version to replicate. |

**Not verified:** I did not *execute* Node 20 or Node 18 against this build — the mandate forbids installing
anything anywhere, and no node older than 22 exists on any node in the mesh. The floor above is inferred
from published API availability plus the in-repo `>= 22` assertion plus one measured good version. If a
node is ever built with 22.x, use **>= 22.18.0**, not 22.15–22.17.

**Ubuntu 24.04's own `nodejs` package is 18.19.1 and cannot run this build.**
MEASURED 2026-09-16 21:52Z on `zabz-tech-linux`: `apt-cache policy nodejs` → `Candidate: 18.19.1+dfsg-6ubuntu5`
(noble/universe:500), and `dpkg -l | grep nodejs` → empty (not installed). `apt install nodejs` is the wrong
answer and should not be used anywhere in this fleet.

### 1.2 What a DSH install *is* — three shapes, all measured

There is no `dsh` on any node's `PATH` (MEASURED: `Get-Command dsh` empty on ZABZ-YOGA; `10-inventory.md`
§2.5/§3.5 record the same on secratary and ZABZ-TECH). Every node invokes `lib/bin.js` explicitly. Three
shapes exist in this fleet:

| shape | node | exact path | MEASURED |
|---|---|---|---|
| `npx` cache | ZABZ-YOGA | `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js` | running engine pid 1784; the cache's own `package.json` pins `"@deepseek-ai/dsh": "^0.1.5-rc.1"` |
| dedicated npm install + systemd | secratary | `/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js` | `~/dsh-engine/package.json` = `{"@deepseek-ai/dsh": "^0.1.5-rc.1"}`; `package-lock.json` 343,702 B resolves **0.1.5-rc.1** with `integrity sha512-rmNmzQCg3oIc1z8xH7izRSOuy1TNzq+/NILyfM+7e8DKOyV+yBtg47WEsqR2SiIe1ATec3L/rUa1YhIcfQ2XEg==` |
| dedicated npm install, launcher-script | mac-mini | `/Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js` | install dir holds `node_modules`, `npm-cache`, `package.json`, `package-lock.json`; version **0.1.5-rc.1** |

**A worker node wants shape 2 or 3 — never `npx`.** `npx`-run invocations resolve from a cache keyed by a
hashed argv, are not lockfile-pinned, and on Windows were already measured to re-hit the registry
(`presets/zabz/agent.cordis.yml:586-590`, the `npx.cmd` → direct-node change).

### 1.3 What must exist in `~/.dsh` before first start

**Nothing.** A fresh `DSH_HOME` is self-initializing, and this is READ, not assumed:

- `dsh-app-boot/lib/index.js:886-892` — `loadProfile` calls `initProfile(dir, template.bundles, template.patchReload)`
  when `<DSH_HOME>/profiles/<name>/package.json` is absent. The shipped template for `web` is
  `["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"]` with `patchReload: "live"`
  (`dsh-app-boot/lib/index.js:333-336`); for `headless` it is `["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"]`
  with `"startup"` (`:337-340`).
- `dsh-app-boot/lib/index.js:379-397` — `initProfile` writes `package.json`, an empty `cordis.patch.yml`, and
  `pnpm-workspace.yaml`, and **never overwrites an existing file**, so it is idempotent.
- The home itself is resolved `configured → $DSH_HOME → ~/.dsh` (`dsh-home-paths/lib/index.js:73-76`);
  a blank `$DSH_HOME` is treated as unset (`:74-75`). **No configuration is required for a node to be correct**
  — which is the same conclusion `20-placement.md` §1.1 reached from the persistence side.

What is created *by* running, in order:

| artefact | created by | evidence |
|---|---|---|
| `<DSH_HOME>/sessions/--<cwd>--/<id>/session.v3.jsonl.zstd` | first session | `dsh-base/cordis.patch.yml:110-113` — `session-persistence-jsonl` with `root: !!js dshHomePath('sessions')` |
| `<DSH_HOME>/storages/**` (projection cache, workspace) | first session | `dsh-base/cordis.patch.yml:145-166` — `root: !!js dshHomePath('storages')` |
| `<DSH_HOME>/settings.yaml` | only if you write one | `dsh-base/cordis.patch.yml:87-91` |
| `<DSH_HOME>/.anonymous-user-id` | telemetry resource id | `dsh-base/cordis.patch.yml:173-175` |
| **`<DSH_HOME>/.credentials.yaml`** | first `dsh web` boot — see §1.5 | `dsh-client-connection/lib/index.js:219, 326-332` |
| `<DSH_HOME>/profiles/<name>/` | first boot of that profile | `dsh-app-boot/lib/index.js:886-892` |

There is **one POSIX permission trap**, and it is a boot-stopper, not a warning:
`dsh-credentials-local/lib/index.js:92-105` — `assertOwnerOnly` refuses to start if
`<DSH_HOME>/.credentials.yaml` exists with any group or other permission bit set
(`throw new Error('credentials-local: <path> is readable beyond its owner (mode X)…')`). The provider
creates and replaces it at `0600` (`:557-560`, mode `384` = `0o600`), but a hand-copied file carries the
umask. On Linux/macOS, **`chmod 600 ~/.dsh/.credentials.yaml` is a prerequisite**, not a cleanup.

### 1.4 Does `dsh web` need a display, a browser, a TTY, or a logged-in session?

**No to all four**, and each has direct evidence rather than reasoning:

| question | answer | evidence |
|---|---|---|
| **a display?** | No. The server is `node:http` `createServer` + `listen(port, host)` — a plain socket. No window, no X, no Wayland. | READ, `dsh-host-webserver/lib/index.js:1, 296-301`. The only display-aware code in the tree is *UI* code: `dsh-host-directory-picker-auto/lib/index.js:57-69` picks a native picker only when `DISPLAY`/`WAYLAND_DISPLAY` is present and otherwise falls back to an in-page browser picker; `dsh-native-command/lib/index.js:168` gates `xdg-open`. Neither is on the engine path. |
| **a browser?** | No, and this is explicitly handled. | READ, `dsh-web-app/lib/index.js:174` — `const handoffBrowser = config.openBrowser && !launchedThroughSsh(launchEnvironmentOf(ctx));` and `dsh-web-app/README.md:45` — *"Open the default browser after startup; SSH launches suppress it."* `--no-open` forces it off (`dsh-web-app/lib/startup.js:22, 43`). The opener is a spawned child (`lib/index.js:116-160`) whose failure is a **warning**, not a fault: *"web-app: could not open the default browser because …; use the dsh web URL printed at startup"* (`:208`). |
| **a TTY?** | No. `> /dev/null < /dev/null` is what the fleet already uses. | READ, `scripts/serve-phone.sh:296` — `setsid nohup "$NODE" "$BIN" web --port "$ENGINE_PORT" --no-open --trusted-host "$DNS" >"$LOG" 2>>"$ERR" < /dev/null &`. A grep for `isTTY\|isatty\|DISPLAY\|Wayland\|xdg-open` across every `.js` file in the installed `@deepseek-ai` tree returned **no engine-path use** — the only hits are the browser bundle (`dsh-web-frontend/dist`), the UI directory-picker's display probe (`dsh-host-directory-picker-auto/lib/index.js:57-69`) and the platform command resolver (`dsh-native-command/lib/index.js:147-168, 238`). The `headless` mode reads its task from **argv**, not stdin (`dsh-headless/lib/startup.js:35`), and the `sdk`/`acp` modes *do* use stdin — as a protocol channel, not a terminal. |
| **a logged-in session?** | No. The reference implementation runs with **zero console logins**, under systemd. | READ, `/etc/systemd/system/phone-engine.service` on secratary (MEASURED 2026-09-16 21:5xZ via `systemctl cat`): `[Service] Type=simple / User=zabz / Environment=HOME=/home/zabz / Environment=NODE_ENV=production / Restart=always / RestartSec=3 / StandardOutput=append:/home/zabz/.dsh-phone/engine-3089.log`. No `PAMName`, no `TTYPath`, no `StandardInput=tty`. `10-inventory.md:190` records `who` on that host returning **empty — 0 console logins**, and the engine has been up **15 h 37 m** there. |

**One thing the engine *does* need from the OS that a naive systemd unit omits: `HOME`.** systemd does not
set it. The reference unit sets it explicitly, and without it `~/.dsh` resolves to `/` or fails —
`resolveDshHome` falls back to `homedir()` (`dsh-home-paths/lib/index.js:50, 75`). Either set
`Environment=HOME=/home/<user>` **or** `Environment=DSH_HOME=/home/<user>/.dsh`. The reference unit does not
set `DSH_HOME` at all and is correct because `HOME` alone is enough — which is also why `20-placement.md` §1.0
found `phone-engine.service` with no `DSH_HOME` and one engine on the default home.

### 1.5 Credentials, tokens and the session store on a headless box

Three separate secrets, three separate mechanisms. Confusing them is how a headless node ends up either
locked out or over-exposed.

**(a) The model credential.** `dsh-base/cordis.patch.yml:93-98` mounts `dsh-credentials-local`, whose
precedence is fixed and documented in its own header (`dsh-credentials-local/lib/index.js:14-21`):

```
inherited process environment      (read-only, wins)      DEEPSEEK_API_KEY=… dsh
> $DSH_HOME/.credentials.yaml      (provider-managed, writable)
> <invocation cwd>/.env            (read-only fallback)
> $DSH_HOME/.env                   (read-only fallback)
```

An **absent** `.credentials.yaml` is an empty store, not an error (`:647-655`). A **present but unparseable**
one fails the plugin's activation — *"must never be treated as 'no credentials stored'"* (`:638-646`). The
document is a strict `<CredentialRef> → string` mapping with a `records:` section for tagged records
(`:136-157`).

**For a systemd worker the environment variable is the right layer, not the file**: it is read-only from
inside the process, so no agent can write it (`:636-638` refuses a write that the environment would shadow),
and it never lands on disk. A plain `EnvironmentFile=/etc/dsh-worker.env` with `DEEPSEEK_API_KEY=…` and
`0600` root ownership is simpler and safer than copying a `.credentials.yaml` between nodes — and
`scripts/sync.py:42` already refuses to sync that file (`PROTECTED = {"sessions", ".credentials.yaml",
".anonymous-user-id", "profiles", "storages"}`), so the fleet has already decided this.

**(b) The browser-session token.** The `/api` fence authenticates with a per-authority cookie, and the
cookie's HMAC secret is a **generated grant record stored in the same `.credentials.yaml`**:
`dsh-client-connection/lib/index.js:219` — `AUTH_RECORD_KEY = credentialKey("client-connection", "browser-session")`;
`:324-332` mints a 32-byte secret (`SECRET_BYTES = 32`, `:221`) and writes it as `{ kind: "grant", payload: … }`
through `credentials.modifyRecord`. The cookie name is `dsh-auth-<base64url(sha256(authority))>`
(`:223, 281`). **So `dsh web` needs `<DSH_HOME>/.credentials.yaml` to be *writable* on first boot even if the
model key comes from the environment** — on a headless box, make sure the unit's `User` owns the file's
directory, or the first boot fails and the reason looks like an auth problem.

The one-time `?token=` URL is **printed, never persisted** by the app: `dsh-web-app/lib/index.js:203` —
`console.log('dsh web: ' + authenticatedUrl)` — and it is single-process. On a headless node that stdout line
**is** the handoff, which is why the reference unit captures it with
`StandardOutput=append:/home/zabz/.dsh-phone/engine-3089.log` and why `scripts/phone-gate.py` scrapes the token
from that file at request time. Measured instance of the artefact: mac-mini's
`~/.dsh/logs/engine.out.log` holds **nine** such lines (`dsh web: http://127.0.0.1:3099/?token=…`), i.e. nine
engine starts. **Treat that log as a secret**, exactly as `serve-phone.sh:295` says.

**(c) The session store.** Local, unordered by anything, created on demand at
`dshHomePath('sessions')` (`dsh-base/cordis.patch.yml:110-113`). MEASURED on mac-mini: two cwd-keyed
directories (`--Users-lpt--`, `--Users-lpt-lpt-hub--`) — the directory name is derived from the **working
directory the engine was started in**, so *where you `cd` before starting the engine determines where that
node's sessions live*. On `secratary` the unit sets `WorkingDirectory=/home/zabz`. A worker node should do the
same and always same, or its session list fragments across cwds.

---

## 2. Non-interactive execution — the decisive question

### 2.1 It exists. It is shipped, documented, and three separate modes are available.

**`dsh --profile headless "<task>"` is a one-shot task runner: one prompt in, final answer out, process exits.**
This is not inferred; it is the bin's own help text and the package's stated contract:

- READ, `@deepseek-ai/dsh/lib/bin.js:32-42` (the launcher's help, verbatim):
  ```
  Examples:
    dsh --profile web                          boot the web profile (same as: dsh web)
    dsh --profile rescue --from-default-profile web
                                               create rescue from the shipped web template, then boot it
    dsh --profile headless "run the tests"     answer one task, print the result, and exit
    dsh --profile tui --patch ./extra.yml      boot a custom profile with one extra overlay
    dsh --profile tui --resume <session>       arguments after the launcher flags reach the app
    dsh --profile web --help                   the web app's own flags and help
    dsh plugin --profile tui add <package>     install a plugin into the tui profile
  ```
- READ, `@deepseek-ai/dsh-headless/lib/startup.js:20-24`, the app's own command:
  `new Command().name("dsh --profile headless").description("Answer one task, stream reasoning to stderr, print the final assistant message, and exit.")` with `argument("[task...]", "the task text; multiple words are joined by spaces")`.
- READ, `@deepseek-ai/dsh-headless/README.md:12` (Summary, verbatim):
  > *"`dsh-headless` runs one dsh task from the command line and prints the final answer, then exits — no GUI,
  > no server, no browser. … The process opens no ports and leaves nothing running behind. The exit code tells
  > you the outcome — **0** when the task completed, **1** when it aborted or errored. The main boundary: one
  > task per invocation, with no interactive follow-up."*
- READ, `@deepseek-ai/dsh-headless/README.md:36` — the output contract: reasoning deltas go to **stderr**
  under a `dsh: reasoning:` heading; the **final answer goes to stdout**; a failure writes
  `dsh: <code>: <message>` to stderr and exits 1.
- READ, `@deepseek-ai/dsh-headless/README.md:123` — *"Runs through the `dsh` launcher — starting the headless
  profile another way fails at startup, because only the launcher can request the process exit."*

**Two further non-browser modes exist**, both stdio JSON protocols, both base-backed:

| mode | transport | methods | evidence |
|---|---|---|---|
| `dsh --profile sdk` | **newline-delimited JSON-RPC on stdin/stdout** | `initialize`, `session/prompt` → `{messageId}`, `session.event`, `session.status`, `shutdown` | READ, `dsh-sdk-app/README.md:26,48`; `dsh-sdk-jsonrpc-server/README.md:12,42-52` — *"Stdout carries only JSON-RPC frames"*, handshake identity `deepseek-harness-sdk-runtime`, EOF on stdin is a bounded successful shutdown. |
| `dsh --profile acp` | ACP v1 JSON-RPC on stdio | `session/new` (absolute `cwd`), prompt + semantic updates, `session/close`, `session/list`, `session/resume` | READ, `dsh-acp-app/README.md:12,36-38` |

**There is no fourth mode.** `lib/bin.js` declares exactly two subcommands — `web` and `plugin` — plus the
root `--profile <name>` form and the `--dump-config` / `--dump-default-config` diagnostics
(READ, `lib/bin.js:100-116, 143-166`). There is **no `run`, `exec`, `-p`, or `--print` flag**; the app flags
belong to the booted profile and are parsed by that profile's own provider (`lib/bin.js:6-22`, and
`dsh-cmdline`). There is **no plugin in this repo that exposes an HTTP endpoint for running a prompt** — the
six local plugins are `plugin-cost`, `plugin-windows`, `plugin-mobile`, `plugin-attention`,
`plugin-attention-badge`, `plugin-health` (glob of `harness-config/packages/*/package.json`), and the only
HTTP surface among them is plugin-health's read-only `/healthz`.

### 2.2 The exact command that runs one prompt headlessly

On a Linux worker with the deployment from §3.4, from the repo whose code the work touches:

```bash
cd /home/zabz/code/harness-config
/home/zabz/node/bin/node /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js \
  --profile headless "Reply with exactly: ENGINE OK"
```

→ expected: **stdout is the single line `ENGINE OK`**, stderr may carry reasoning, and the **exit code is 0**.
Nothing listens on any port; nothing is left running.

For a long-lived, scriptable channel instead, the same install boots a JSON-RPC peer:

```bash
/home/zabz/node/bin/node /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js --profile sdk
```
then write `{"jsonrpc":"2.0","id":1,"method":"initialize",…}` followed by `session/prompt` frames on stdin and
read NDJSON frames on stdout. **Only one of these per process**, and one task per headless invocation.

### 2.3 What headless is **not** — the correction to `20-placement.md` §2(b)

`20-placement.md:279-282` says `--profile headless`/`sdk`/`acp` *"do not mount `agent-presets`, so the `zabz`
persona, **the toolbelt** and the MCP bridges are all absent."* The first and third clauses are exactly right;
**"the toolbelt" is wrong as written**, and the distinction matters because it decides whether a headless
worker is a real worker or a cripple.

Read the mechanism directly. `dsh-base` mounts the process-wide agent plane — `tool-bash` / `tool-pwsh`,
`tool-fs`, `tool-fs-search`, `tool-jobs`, `tool-goal`, `tool-subagent` ×2, `tool-subagent-control`,
`workflow-worker-thread`, `tool-workflow`, `tool-ralph`, `tool-todo`, `tool-web`, `tool-skill`,
`agent-instructions`, `compaction-basic` + `command-compact`, `plan-mode` (`dsh-base/cordis.patch.yml:199-487`).
Then **the web bundle is the only thing that turns that plane OFF**:

- READ, `dsh-web-app/cordis.patch.yml:443-471` — `tool-subagent-control`, `tool-subagent-list-agents`,
  `tool-subagent`, `tool-subagent-fork`, `workflow-worker-thread`, `tool-workflow`, `tool-ralph`,
  `agent-instructions`, `tool-todo`, `tool-web` are each `disabled: true`;
- READ, `dsh-web-app/cordis.patch.yml:473-484` — and only there is the roster inserted:
  `- id: agent-presets / name: '@deepseek-ai/dsh-agent-presets' / config: { default: standard }`.

A grep across all 242 `package.json` files under the installed `@deepseek-ai` tree finds the
`@deepseek-ai/dsh-agent-presets` **row mounted by exactly one file**: `dsh-web-app/cordis.patch.yml:481-482`.

**So the accurate statement is:** headless/sdk/acp carry the **same tools** as the web surface (the base
rows are active, not shadowed by a preset realm), and the platform gate hands a Linux node `bash-sandbox` +
`tool-bash` where a Windows node gets the PowerShell twins (`dsh-base/cordis.patch.yml:214-221`;
`dsh-base/README.md:64`). What they lack is the **preset composition**: the `zabz` persona, the per-preset
realm, the `parallel-agent-orchestration` skill directory, and the MCP bridges
(`presets/zabz/agent.cordis.yml:487-619` — `mcp-secretary`, `mcp-secretary-linux`, `mcp-firecrawl`,
`mcp-jina`, `mcp-context7`, `mcp-fetch`, `mcp-playwright`). **A headless worker is the tools without the
persona and without `ps_*`.** The second half is the real loss: on the authority itself, where the Linux MCP
row is active, the absence of `presets/zabz` means no `ps_db_query`, no `ps_ceo_chat`, no company reach.

That is a *solvable* gap and it is not this document's to close — but it is now precisely scoped: what a
worker wants is `dsh-base` + a **custom profile** whose patch re-inserts the rows the web bundle disables,
or a preset-aware non-web surface. **Not** `--profile headless` with the persona bolted on, and **never**
`20-placement.md` §2(b)'s rejected shape (`--profile headless` *as a substitute for* `web`).

**One more measured detail that decides how a headless node is driven:** the `headless` profile is
`patchReload: "startup"` (`dsh-app-boot/lib/index.js:337-340`), so its composition is read **once per process**.
An engine that is to serve a *changing* persona/tool configuration must be `web` (`patchReload: "live"`,
`:333-336`). Headless is a **job runner**, not an engine.

### 2.4 The one historical trap, so it is not re-introduced

`INSTALLATION_OWNED_PROFILE_TUPLES` in `dsh-app-boot/lib/index.js:350-355` normalizes a profile whose bundle
list is exactly `["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "@deepseek-ai/dsh-headless"]` **back**
to `["dsh-base", "dsh-headless"]` — i.e. an **earlier build shipped headless *with* the web bundle**, and the
current one deliberately does not. Anyone who "fixes" headless by adding the web bundle to it will have that
edit silently reverted on the next boot. The right way to give a non-web surface presets is a **patch layer**,
not a bundle list.

---

## 3. The two candidate nodes

All readings below are **MEASURED read-only over ssh on 2026-09-16, 21:47–21:53Z** from `ZABZ-YOGA`, with
`ssh -o BatchMode=yes -o ConnectTimeout=8`. Nothing was installed, started, stopped or written on either
machine.

### 3.1 `zabz-tech-linux` (Linux, office LAN) — alias `linux-pc-ts`

```
hostname            zabz-tech-linux
os-release          Ubuntu 24.04.3 LTS (Noble Numbat)        kernel 6.8.0-111-generic
arch                x86_64        glibc 2.39-0ubuntu8.7
cpu                 12 × 11th Gen Intel Core i5-11400 @ 2.60GHz
memory              MemTotal 11,673 MB · available 10,530 MB · swap 4,095 MB total, 632 MB used, 3,463 MB free
disk                /dev/nvme0n1p2  468G  423G used  22G avail  96%  /   (single volume; /home is on it)
node / npm / nvm    NO_NODE  NO_NPM  NO_NVM        snap: /usr/bin/snap present
~/.dsh              absent ("NO_DSH_HOME")
network             192.168.50.23/24 on enp1s0  ·  tailscale0 100.105.248.90/32  ·  tailscale CLI at /usr/bin/tailscale
office LAN          ping 192.168.50.77 (secratary) → 0.210 ms, 0% loss
tailnet             up; `tailscale status` lists the tailnet name lakewoodphoneandtech@; BackendState not re-read
tailscale serve     "No serve config"
listening ports     0.0.0.0:22, 127.0.0.1:631, 127.0.0.54:53, 127.0.0.53:53, 100.105.248.90:64226
sudo                `sudo -n true` → SUDO_NOPASS (passwordless sudo works for user zabz)
user                uid=1000(zabz) gid=1000(zabz) groups=zabz,adm,cdrom,sudo,dip,plugdev,users,lpadmin
uptime              36 days, 5 h 34 m; load average 0.07 0.04 0.01; 10 login sessions
readiness (read-only HTTP HEAD, no install):
                    nodejs.org/dist/v24.12.0/node-v24.12.0-linux-x64.tar.xz → HTTP/2 200  application/x-xz
                    api.deepseek.com/                                        → HTTP/2 401  (reachable)
                    deb.nodesource.com/setup_22.x                            → HTTP/2 200
                    registry.npmjs.org/@deepseek-ai%2fdsh                     → HTTP/2 200  application/json
```

**Assessment.** The best *unoccupied* capacity in the roster: 12 cores at load 0.07, 10.5 GB genuinely
available, **swap only 15 % used** (against secratary's 99.99 % and mac-mini's 92 %), and 0.21 ms to the
authority on the office LAN — meaning a worker here can reach the authoritative DB without paying the
DERP-relay tax the laptop pays. Its two real problems are that it has **no Node at all**, and that its root
filesystem is **96 % full with 22 GB free**, on the same volume that would hold `<DSH_HOME>` and any worktree.
It also carries a large amount of other people's data — `10-inventory.md:459-460` records four external
volumes mounted for customer image recovery (a 5.5 TB and a 931 GB SSD among them) — so anything placed here
shares a spindle with storage work, and `mount.ntfs-3g` was already the top CPU consumer at the time
`10-inventory.md` sampled it.

**Verdict: the better *first worker*, conditional on two prerequisites it does not yet meet** — a Node
runtime, and a disk-space decision (§3.4, §5).

### 3.2 `mac-mini` (`LakewooechsMini`, macOS, office LAN) — alias `mac-mini-ts`

```
hostname            LakewooechsMini
os                  macOS 26.5.2 (build 25F84) · Darwin 25.5.0 · arm64 · Mac16,10 (Apple M4)
cpu                 10 cores (hw.ncpu 10, no SMT)
memory              hw.memsize 17,179,869,184 B (16.00 GB)
                    vm_stat page size 16,384 B · Pages free 4,083 · active 231,876 · inactive 225,986
                    vm.swapusage  total 6,144.00 M · used 5,627.94 M · free 516.06 M   (92 %)
disk                /dev/disk3s1s1  228Gi  16Gi used  17Gi avail  49%  /
                    /dev/disk3s5 (Data)  228Gi  169Gi used  17Gi avail  91%
node -- TWO installs /usr/local/bin/node  → /usr/local/lib/nodejs/node-v24.19.0-darwin-arm64/bin/node   v24.19.0
                    ~/.local/node-v24.12.0-darwin-arm64/bin/node                                    v24.12.0
npm                 /usr/local/bin/npm → …/node-v24.19.0-darwin-arm64/bin/npm (symlink exists)
                    NOTE: non-interactive ssh PATH is /usr/bin:/bin:/usr/sbin:/sbin, so `command -v node`
                    returns NOTHING. This is the exact misreading that produced "no Node runtime".
brew / port         NO_BREW (no /opt/homebrew) · no MacPorts
DSH install         ~/.dsh-install/node_modules/@deepseek-ai/dsh  version 0.1.5-rc.1
~/.dsh              present and populated: .agent-presets/{zabz,yocheved,cordis-bg}, .credentials.yaml
                    (0600, 277 B), .anonymous-user-id, attachments/, bin/, browser-profile(s)/, logs/,
                    profiles/{headless,web,node_modules}, sessions/{--Users-lpt--,--Users-lpt-lpt-hub--},
                    settings.yaml, settings.machine.yaml, storages/
~/.dsh/profiles/web/package.json
                    bundles = dsh-base, dsh-web-app, dsh-plugin-attention, dsh-plugin-attention-badge,
                              dsh-plugin-cost, dsh-plugin-health, dsh-plugin-mobile, dsh-plugin-windows
~/.dsh/bin          deploy-session-sync.sh, new-window.command, yocheved-assistant.command
~/.dsh/logs         engine.out.log (738 B, 9 token lines), engine.err.log (25,786 B, last write 2026-09-16
                    14:01 local), launcher.log, windows.log, session-sync-deploy.log
ENGINE RUNNING NOW  pid 2944, started 18:52 local,
                    /Users/lpt/.local/node-v24.12.0-darwin-arm64/bin/node
                    /Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js web --port 3099 --no-open
                    lsof → node PID 2944 TCP 127.0.0.1:3099 (LISTEN)
network             192.168.50.45/24 and 192.168.50.73/24 · utun 100.126.146.121 (tailnet IP)
tailscale           CLI not on the non-interactive PATH; the app binary is at
                    /Applications/Tailscale.app/Contents/MacOS/Tailscale (invoking `version` over ssh
                    HUNG and had to be killed — see §6)
tailscale serve     could not run the CLI; NOT VERIFIED
uptime              43 days, 18 h 58 m; 2 console users (moshemontrose since Aug 11, lpt since Aug 12)
```

**Assessment.** Far readier than the brief records, and structurally the *wrong* first worker. It is an
employee's logged-in desktop (`10-inventory.md:507`; `~/.dsh/settings.machine.yaml` is explicitly *"Yocheved's
manager workstation"* with `permission.defaultPreset: workspace-write` for exactly that reason), it is
starting from ~64 MB of genuinely free RAM with 92 % of swap consumed, and its Data volume is 91 % full.
`20-placement.md` §8 already rules it out as a worktree host on the disk number alone; the memory number
makes it worse, and `50-transport.md` §6 says in terms that the employee's node should be kept off the
owner-access path entirely.

**Its launcher works today and is brittle, not broken** — the distinction matters because I first read it as
broken and was wrong. `~/.dsh/bin/yocheved-assistant.command` (read in full, 2026-09-16) sets
`NODE_DIR="$HOME/.local/node-v24.12.0-darwin-arm64"`, `NODE="$NODE_DIR/bin/node"`,
`DSH_BIN="$HOME/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js"`, `DSH_HOME="$HOME/.dsh"`,
`PORT=3099`, `WORKSPACE="$HOME/lpt-hub"`, and starts the engine as
`nohup env DSH_HOME="$DSH_HOME" "$NODE" "$DSH_BIN" web --port "$PORT" --no-open` — which is **byte-for-byte
what pid 2944 is running** (MEASURED, §3.2). Both paths exist. What is fragile is that it hardcodes a
**version-stamped** node directory: `/usr/local/bin/node` on that machine is a *different* version
(v24.19.0) from the one the launcher and the running engine use (v24.12.0), so a future `brew`/pkg upgrade
that replaces the versioned directory turns this launcher into an `[ -x "$NODE" ] || FATAL` on a machine
nobody is watching. A worker node's launcher should resolve the interpreter rather than name a version.

**Verdict: not the first worker.** It is a *demonstration that the architecture is already proved on macOS*,
and it is the natural second node once its memory and disk are addressed and after the employee-machine
boundary is respected.

### 3.3 Side by side, on the numbers that decide it

| | `zabz-tech-linux` | mac-mini | which matters |
|---|---|---|---|
| Node runtime | **none** | **v24.19.0 + v24.12.0** | mac-mini |
| DSH installed | **none** | 0.1.5-rc.1, `~/.dsh` populated | mac-mini |
| engine running today | no | **yes, 127.0.0.1:3099** | mac-mini |
| cores | 12 @ load 0.07 | 10 @ load ~1.6–2.0 (1-min) | linux-pc |
| RAM available | **10,530 MB** | ~64 MB free pages | **linux-pc, decisively** |
| swap in use | **632 MB of 4,095 (15 %)** | **5,628 MB of 6,144 (92 %)** | **linux-pc, decisively** |
| disk free for worktrees | 22 GB (96 % used) | 17 GB (91 % used) | neither is good |
| whose machine | nobody's (office box) | an employee's logged-in desktop | **linux-pc** |
| path to the authority | **0.21 ms on the office LAN** | ~1 ms on the office LAN (via tailnet direct per `10-inventory.md:254`) | tie |
| already carrying someone else's work | customer recovery images on 4 external volumes | the employee's desktop session + 2 console users | linux-pc |
| what it costs to make it a worker | install Node + DSH (≈ 200 MB, §3.4) | nothing to run an engine; a disk + memory decision to run *work* | mac-mini |

### 3.4 The install commands — **stated, not run**

The mandate forbids installing on either machine, so nothing below was executed. Every URL and repository
referenced was verified reachable **read-only** from the target node where noted (§3.1).

**Choice of runtime, and why.** The OS package manager is rejected on evidence, not taste:
`apt-cache policy nodejs` on `zabz-tech-linux` → **18.19.1** (§1.1 — cannot run this build). `nvm` is
rejected because it puts the interpreter inside a shell-startup file, and **a systemd unit does not read your
shell startup** — the engine would work when a human logged in and fail at boot, which is the worst possible
failure shape for an always-on worker. The fleet's own convention is the third option and it is the right
one: **a nodejs.org tarball extracted under `$HOME/.local`**. Six files in this repo already reference exactly
`$HOME/.local/node-v24.12.0-darwin-arm64/bin/node` — four times as a **candidate probe** before falling back
to `command -v node` (`scripts/harness-autosync.sh:46`, `scripts/journal-daily.sh:37`,
`scripts/install-manager-tasks-macos.sh:45`, `scripts/install-manager-macos-extras.sh:41`) and three times as
a **launchd `PATH` entry** (`scripts/install-manager-tasks-macos.sh:98`,
`scripts/install-manager-macos-extras.sh:89`, `scripts/install-harness-autosync-macos.sh:81`). So the path is
already load-bearing in this repo, and a Linux worker that uses `~/.local/node-v24.12.0-linux-x64` is the
same convention one platform over.

**Version: pin v24.12.0**, because it is the version the mac-mini engine is *measurably running right now*
on this exact DSH build, it is what the scripts above name, and it is not subject to the `^0.1.5-rc.1`
range-drift problem of §4. The proven floor is 22.18.0 (§1.1) if 24 ever needs to be avoided.

**`zabz-tech-linux` — the exact commands (NOT RUN):**

```bash
# 1. Node, from the official tarball, into ~/.local (no sudo, no apt, no nvm, reversible).
mkdir -p "$HOME/.local" && cd "$HOME/.local"
curl -fsSLO https://nodejs.org/dist/v24.12.0/node-v24.12.0-linux-x64.tar.xz
tar -xJf node-v24.12.0-linux-x64.tar.xz          # extracts to ./node-v24.12.0-linux-x64/
"$HOME/.local/node-v24.12.0-linux-x64/bin/node" -v      # expect: v24.12.0

# 2. DSH 0.1.5-rc.1, from secratary's lockfile so the version is PINNED, not ranged.
#    Run this ON the linux box, which is on the office LAN, so the office alias `secratary` resolves.
mkdir -p "$HOME/dsh-engine" && cd "$HOME/dsh-engine"
scp secratary:/home/zabz/dsh-engine/package.json      .
scp secratary:/home/zabz/dsh-engine/package-lock.json .
"$HOME/.local/node-v24.12.0-linux-x64/bin/npm" ci --omit=dev     # `ci` honours the lock and its integrity hash
```

**`mac-mini` — the exact commands (NOT RUN):**

```bash
# Nothing to install: node v24.12.0 and DSH 0.1.5-rc.1 are already present and the engine is already
# running. The only work is to stop depending on a hardcoded ~/.local path in a launcher script:
ls -l "$HOME/.local/node-v24.12.0-darwin-arm64/bin/node" \
      "$HOME/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js"   # both must exist (they do, measured)
```

*(A macOS arm64 tarball, if a reinstall is ever needed, is
`https://nodejs.org/dist/v24.12.0/node-v24.12.0-darwin-arm64.tar.gz` — same shape, `.tar.gz` not `.tar.xz`.)*

**The exact command that verifies the install succeeded** — for either node, one line, exit code is
the answer:

```bash
"$HOME/.local/node-v24.12.0-linux-x64/bin/node" "$HOME/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js" --version
```
→ expect a version string (`0.1.5-rc.1`). **This is deliberately `--version`, not a smoke prompt**: it proves
the binary resolves and `runCli()` was reached (i.e. `import.meta.main` is defined — the §1.1 failure would
print *nothing* and exit 0). The full end-to-end check is §5's command.

**One prerequisite that is easy to miss and is ours, not his:** `scripts/sync.py:253-255` merges
`settings/base.yaml` with `settings/machines/<HOSTNAME>.yaml` and warns `MISSING -- only base will apply`
when the machine file is absent. `harness-config/settings/machines/` currently holds `ZABZ-YOGA.yaml`,
`SECRATARY.yaml`, `ZABZ-TECH.yaml`, `LAKEWOOECHSMINI.yaml`, `DESKTOP-FGV6KMH.yaml` — **there is no
`ZABZ-TECH-LINUX.yaml`**. A linux-pc worker without one inherits base settings only, which on a machine whose
job is agent work means the wrong sandbox preset and no per-machine model route. That file is a development
change and is in scope for whoever deploys this node.

---

## 4. Version, port, `DSH_HOME`, and the trust fence on a headless node

### 4.1 The version in use, and whether the two nodes would get the same one

| where | `@deepseek-ai/dsh` | `@deepseek-ai/dsh-headless` | runtime | SOURCE / DATE |
|---|---|---|---|---|
| `ZABZ-YOGA` (the surface this session runs on) | **0.1.5-rc.1** | 0.1.5-rc.2 | Node v24.12.0, npm 11.6.2 | READ, `dsh/package.json:4`, `dsh-headless/package.json:4`; MEASURED `node -v` 2026-09-16 |
| `secratary` | **0.1.5-rc.1** | 0.1.5-rc.2 | Node v22.23.2, npm 10.9.8 | MEASURED `ssh secratary-ts` 2026-09-16 21:5xZ |
| mac-mini | **0.1.5-rc.1** | 0.1.5-rc.2 | Node v24.12.0 (engine) / v24.19.0 (/usr/local) | MEASURED `ssh mac-mini-ts` 2026-09-16 21:5xZ |

**All three are on the same build today — and that is partly luck.** The declared dependency on every node is
the *range* `"^0.1.5-rc.1"` (ZABZ-YOGA's npx cache `package.json`; `secratary:~/dsh-engine/package.json`;
the same in mac-mini's `~/.dsh-install/package.json`). A caret range over a prerelease admits any later
`0.1.x`, and the release train in use already contains at least two revisions —
`dsh` at `-rc.1` and `dsh-headless` at **`-rc.2`** ship inside the same install. **A fresh `npm install
@deepseek-ai/dsh@^0.1.5-rc.1` on a new node can therefore resolve to a different build than the one the owner
is already running**, and a "worker that behaves differently" is a bug that looks like a model problem.
secratary mitigates this by having a `package-lock.json` that pins `0.1.5-rc.1` with an integrity hash
(§1.2). **Do the same: install with `npm ci` from secratary's lockfile** (§3.4), or pin the exact version
with no caret. Do not rely on the range.

### 4.2 Port

- **The shipped default is `3080`, not 3099.** READ, `dsh-web-app/cordis.patch.yml:139-140` —
  `host: !!js ctx.webStartup.host ?? '127.0.0.1'` and `port: !!js ctx.webStartup.port ?? 3080`.
- In practice every node overrides it: ZABZ-YOGA **3099**, ZABZ-TECH 3099, secratary **3089** (with the gate
  on 3086), mac-mini **3099**. `--port 0` asks the OS for a free port (`dsh-web-app/lib/startup.js:22`) —
  **do not use that on a worker**, because the port is the only thing that names the engine, and the printed
  URL is the only way to reach it.
- **A worker node should keep the fleet-wide 3099** unless it shares a host with another engine. The port is
  node-local; what matters is that it is *constant per node*, because the browser's "current session" pointer
  and the auth cookie are both keyed by origin (`20-placement.md` §1.2/§1.3).
- `--host` is defaulted to loopback and `--host 0.0.0.0` is **refused at startup**:
  *"error: --host 0.0.0.0 is intentionally not supported yet for safety: it would expose remote code
  execution to the network; use 127.0.0.1 instead"* (READ, `dsh-web-app/lib/startup.js:40`). The webserver
  schema would allow it (`dsh-host-webserver/lib/index.js:141`, `z.union([z.const("127.0.0.1"),
  z.const("0.0.0.0")])`) — the CLI check is the only thing stopping it. Do not route around it.

### 4.3 `DSH_HOME`

`configured → $DSH_HOME → ~/.dsh` (READ, `dsh-home-paths/lib/index.js:73-76`), blank treated as unset (`:74`).
For a headless node the rule from `20-placement.md` §1.1 stands unchanged — **one `DSH_HOME` per node,
unfailingly** — and the only headless-specific addition is that **the unit must set `HOME`** (§1.4). Setting
`DSH_HOME` explicitly as well is harmless and is what I would do, because it makes the unit independent of
whatever `User=` resolves its home to:

```ini
Environment=HOME=/home/zabz
Environment=DSH_HOME=/home/zabz/.dsh
```

### 4.4 The trust fence — and when a headless node needs *no* fence at all

`--trusted-host <authority...>` is a **startup** flag on the web profile
(`dsh-web-app/lib/startup.js:22, 46`), passed to the composed config
(`dsh-web-app/cordis.patch.yml:161`, `:188`) and resolved by `resolveLanTrust` into the `/api`
browser-trust fence: `trustedHosts: [...lanAddresses, ...extra]`, with **`lanAddresses` non-empty only when
`bindHost === "0.0.0.0"`** (READ, `dsh-web-app/lib/index.js:83-89`).

Three consequences, and they compose into the headless rule:

1. **Loopback needs no fence.** With the default bind `127.0.0.1` the derived list is **empty**, and loopback
   is the implicit trusted authority. MEASURED against the live engine in this session
   (`50-transport.md` §2): `GET /api` with `Host: 127.0.0.1:3099` → **401** (accepted, unauthenticated);
   with `Host: zabz-yoga-1.tail93e6e6.ts.net` → **403** (refused, because this engine has no
   `--trusted-host`). **A loopback-only worker needs no `--trusted-host` at all** — which is the cleanest
   configuration for a node whose job is to execute work handed to it, not to be browsed.
2. **The moment you publish it with `tailscale serve`, you need the flag**, the exact tailnet FQDN, and an
   engine restart (`--trusted-host` is read at boot). The measured reference does it right:
   `phone-engine.service` `ExecStart=… web --port 3089 --no-open --trusted-host secratary.tail93e6e6.ts.net`.
3. **A `cordis.patch.yml` that restates the `connection` row's `config` must restate `trustedHosts` too**, or
   the fence silently becomes empty and every `/api` call from a non-loopback Host gets 403 while documents
   keep serving. That is `harness-config/profiles/web/cordis.patch.yml:45-62`, PAIN P48, and it is a
   live-landmine for any new node whose patch file is written from scratch.

**The `headless`/`sdk`/`acp` profiles have no webserver and therefore no fence at all** — `dsh-headless`'s
patch mounts no Host, HTTP server or browser plugin (READ, `dsh-headless/cordis.patch.yml:2-5`),
and its README states the process *"opens no listening port"* (`dsh-headless/README.md:46`). This is another
reason a *job-runner* worker and a *browsable* worker are different objects: only the second one has an
authority to defend.

---

## 5. The decision

**`zabz-tech-linux` is the better first worker, and the single command that starts an engine there is the
fleet's own shape, unchanged:**

```bash
# 1. one-time, from §3.4: Node v24.12.0 tarball into ~/.local + `npm ci` of DSH 0.1.5-rc.1 into ~/dsh-engine
# 2. the engine itself, loopback-only, so it needs no --trusted-host and no gate:
set -a; . /etc/dsh-worker.env; set +a          # DEEPSEEK_API_KEY, owned 0600 by root
exec /home/zabz/.local/node-v24.12.0-linux-x64/bin/node \
     /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js \
     web --port 3099 --no-open < /dev/null
```
run under `systemd` (`Type=simple`, `User=zabz`, `Environment=HOME=/home/zabz`,
`Environment=DSH_HOME=/home/zabz/.dsh`, `WorkingDirectory=/home/zabz/code`, `Restart=always`,
`RestartSec=3`, `StandardOutput=append:/home/zabz/.dsh-worker/engine-3099.log`) — the reference unit is
`secratary:/etc/systemd/system/phone-engine.service`, read verbatim in §1.4, and this is a copy of it with
the gate and the fence removed because a loopback worker needs neither.

**The one measurement that proves it is serving work** is not an HTTP probe — a 200 on `/` proves a document
was served, and a 401 on `/api` proves only that the fence works. It is **one headless prompt through the
same install, on the same node, whose exit code and stdout are the verdict**:

```bash
cd /home/zabz/code/harness-config && \
/home/zabz/.local/node-v24.12.0-linux-x64/bin/node \
  /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js \
  --profile headless "Reply with exactly: ENGINE OK"; echo "exit=$?"
```
→ **`ENGINE OK` on stdout and `exit=0`** proves, in one shot: the interpreter is new enough that
`import.meta.main` is defined (§1.1 — the failure mode prints nothing and exits 0, so the *string on stdout*
is the discriminating part, not the exit code alone); the credentials resolve; `api.deepseek.com` is
reachable from that node (§3.1 — HTTP 401 read-only); the full base toolbelt mounts; and the session store
is writable. If that line comes back, the node can take agent work. If it does not, nothing else about the
node is worth measuring yet.

**Why not mac-mini first.** It is *readier* — Node v24.19.0 and v24.12.0 both present, DSH 0.1.5-rc.1
installed, and an engine already listening on `127.0.0.1:3099` (MEASURED, pid 2944) — but readiness is the
wrong axis for the *first* worker. It is an employee's logged-in desktop (2 console users,
`~/.dsh/settings.machine.yaml` is Yocheved's), it has ~64 MB of genuinely free RAM and 92 % of a 6 GB swap
consumed, its Data volume is 91 % full, and `20-placement.md` §8 plus `50-transport.md` §6 both already say
not to put fleet work or owner access there. Placing the first fleet on the employee's machine to save a
200 MB install on an idle 12-core office box is trading a five-minute install for a memory-exhausted host and
a boundary the owner has not been asked about. **mac-mini is the second node** — and it is far better
positioned for that than the brief believed; it needs a memory and disk decision, not a runtime.

**What this decision costs, stated plainly:** `zabz-tech-linux` is **96 % full with 22 GB free**, so a worker
there can hold an engine (~250 MB with `node_modules`) and a *small* number of worktrees, and it cannot hold
a build tree plus a fleet's worth of worktrees at once. That is a real ceiling and it is the same
disk-headroom input `20-placement.md` D6 says must become a first-class placement field. It does **not**
change the ranking — mac-mini's 17 GB is *less*, on a volume that is *more* full and on a machine whose RAM
is already spent — but it does mean the correct sized job for this node today is *a fleet of sessions and
agent turns*, not *a fleet plus a monorepo build*.

---

## 6. What I could not verify

Stated as refusals, not as health.

1. **The exact minimum Node version, by execution.** The floor is inferred from published API availability
   (`import.meta.main` → v24.2.0 / v22.18.0; zstd in `node:zlib` → v23.8.0 / v22.15.0), the repo's own
   `serve-phone.sh:230` assertion `(the harness needs Node >= 22)`, and one measured known-good runtime
   (secratary, v22.23.2). I did not install Node 18/20/22 anywhere, so the floor is **not established by
   running it per version**. The command that would settle it, on a throwaway box only:
   `for v in 18.20.8 20.19.5 22.14.0 22.18.0; do … ; done` against `bin.js --version`.
2. **`import.meta.main` on the Node 22 line, from the primary source.** The official v24 docs page gives
   `Added in: v24.2.0`; the ≥22.18.0 backport is from a third-party issue
   ([tschaub/es-main#161](https://github.com/tschaub/es-main/issues/161)) and the v22.18.0 LTS release page,
   not from the v22 docs page (which I did not fetch). It is corroborated empirically — secratary's engine
   runs on v22.23.2 — but I am flagging the sourcing rather than presenting it as a single clean citation.
3. **`tailscale serve` on mac-mini.** The Tailscale CLI is not on the non-interactive `PATH`; invoking
   `/Applications/Tailscale.app/Contents/MacOS/Tailscale version` over ssh **hung** and the job had to be
   killed (§3.2). Serve status on that node is **NOT VERIFIED**. Command that would settle it, with a bound:
   `ssh -o BatchMode=yes -o ConnectTimeout=8 mac-mini-ts '/Applications/Tailscale.app/Contents/MacOS/Tailscale serve status'`
   with a local timeout — the hang is the reason I did not retry it inside this session.
4. **Whether `zabz-tech-linux`'s 10 login sessions are people or stale ssh sockets.** `uptime` reports
   `10 users`; `who` was not read. It matters only for how much of the 12 cores is really spare, and the
   measured `load average 0.07 0.04 0.01` says "spare" either way. Command:
   `ssh linux-pc-ts 'who; w'`.
5. **What exactly occupies the 423 GB on `zabz-tech-linux`'s root volume.** `10-inventory.md:459-460`
   attributes large recovery images to *external* volumes (`/mnt/atlas-recovery`, `/mnt/abramczyk-img`), which
   does not explain 96 % of the 468 GB internal. Not investigated; a `du -xh --max-depth=1 /` would. It is a
   prerequisite for any reclaim decision and therefore for how many worktrees this node can host.
6. **Whether mac-mini's running engine (pid 2944) is still healthy.** It is *listening* (lsof, MEASURED);
   its `/api` fence status, its live session count and its loop lag were **not** probed, because probing it
   would have meant issuing HTTP requests to another machine's engine. `curl -s -o /dev/null -w '%{http_code}'
   http://127.0.0.1:3099/api -H 'Host: 127.0.0.1:3099'` on that node would answer it (expect 401).
7. **Whether a `headless` run has ever actually completed on any node in this mesh.** No headless session
   directory was found under `~/.dsh/sessions` on mac-mini (its two session dirs are cwd-keyed to
   `/Users/lpt` and `/Users/lpt/lpt-hub`), and the mode's README documents the contract but this session did
   not run it. It is the §5 acceptance test precisely because it is unproven here.
8. **The `dsh --profile tui` and `--profile rescue` profiles named in the launcher's own help text
   (`lib/bin.js:32-42`) do not exist in `PROFILE_TEMPLATES`** (`dsh-app-boot/lib/index.js:328-349` lists only
   `acp`, `web`, `headless`, `sdk`, `sdk-minimal`). `--profile tui` would therefore require a pre-created
   custom profile directory. Irrelevant to this volume — there is no TUI app package installed — but it is a
   documentation/reality gap in the source, recorded rather than acted on.
