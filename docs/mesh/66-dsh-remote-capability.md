# 66 — Remote capability in the shipped DSH tree: what exists before Phase 3 is built

**Program:** `docs/mesh/`. **Depends on:** `20-placement.md` (read in full, §1–§9), `50-transport.md` §2.
**Date:** 2026-09-16. **Author:** one of eight parallel research agents; not the owner.
**Read-only:** no engine started, stopped, reconfigured or contacted. No git state changed. This is the only file this session wrote.

**The mandate:** `20-placement.md` §8 Phase 3 commissions a placement service (a broker that decides which node runs a fleet) because the design assumes *(i)* a session is pinned to one engine and *(ii)* there is no way to place work on another node. This document attacks both assumptions from the shipped source.

**Provenance convention.** Two roots, used everywhere below:

| alias | real path |
|---|---|
| `NM/` | `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\` |
| `HC/` | `C:\Users\ezabz\code\harness-config\` |

`dsh` is version **0.1.5-rc.1** (`NM/dsh/package.json`); every other package in the tree is **0.1.5-rc.2**. Every claim below carries `file:line` read in this session. Where a thing was *searched for and not found*, the search is stated — an empty search is not evidence of absence.

**Amended 2026-09-16 — the transient-session trap (§4.3).** Two of this document's four transports are blocked by the same shipped defect: the launch token is a **per-process in-memory value**, so *every engine restart mints a new one* and every cookie minted against the old one is dead for 401. The first draft of this document recommended an unattended cookie harvest as the cheapest path. **It is not safe unattended**: an engine restart silently invalidates the harvested cookie, and the failure mode is a 401 the caller cannot distinguish from a permission error. §2(c) and §4.3 carry the correction, and §4's verdict is stated in terms that survive it. This is the one place where reading the source after writing the first draft changed a recommendation.

---

## 1. Inventory: what actually ships

### 1.1 The packages that touch networking, a remote host, a gateway, a worker, a scheduler, a queue, a lease, or an attach

This is the subset the mandate asks to hunt. **Ten packages** out of ~240 are in scope, and the important finding is what is *absent*: there is **no** `dsh-remote`, `dsh-cluster`, `dsh-worker`, `dsh-fleet`, `dsh-queue`, `dsh-lease`, `dsh-broker` or `dsh-scheduler` package. A directory listing of `NM/` (240 directories, read this session) contains none of those names.

| package | one line | why it is in scope |
|---|---|---|
| `dsh-host-webserver` | Web route-registration plugin: HTTP and upgrade routes, index transform taps, static dist fallback; *"knows no harness concepts"* | **the cheapest placement transport in the tree** — `ctx.webServer.register()` (§2e) |
| `dsh-client-connection` | Authenticated RPC transport, generation lifecycle, browser fixture | the `/api` carrier, the Host/Origin fence, the authority-bound cookie (§2c); also `connection.rpc` / `connection.fetch` registries |
| `dsh-api-gateway` | *"Typert Remote Host dispatcher and Client API endpoint"* | the dispatcher that turns an HTTP path into a method call on a live service; the WebSocket mux. **"Remote" here means the browser is remote from the host** — not a second machine |
| `dsh-api-remotes` | Remote BFF assembly for application-selected Host capabilities | client-side assembly only |
| `dsh-api-session-controller` | Session Remote commands, cold reads, and live control transport | **16 HTTP-reachable methods including `session/create`, `session/prompt`, `session/cancel`, `session/fork`** (§2a) |
| `dsh-webhook` | Fire-and-forget webhook rule runtime that creates Workspace-backed Sessions | external HTTP event → **a real preset-mounted session** (§3.1) |
| `dsh-webhook-github` | Signed GitHub HTTP webhook adapter | the **worked example of a plugin-owned HTTP ingress route** (§3.1) |
| `dsh-jobs` / `dsh-jobs-local` | Background job registry; process-local implementation | the only "job queue" in the tree; **in-process, `new Map()`, not durable** (§2d) |
| `dsh-subagent` | Abstract subagent seam: **named-provider registry** for delegating to child agents | the one extension point designed for a *remote* provider — and its README names exactly what blocks it (§3.4, §4) |
| `dsh-host-open-in-app` | Host half of open-in-app: catalog, icons, launch endpoint **as three webServer routes** | a second shipped proof that plugins own HTTP routes, including a **prefix** route |

Adjacent, and worth naming because they are the pieces Phase 3 would otherwise reinvent:

| package | one line | relevance |
|---|---|---|
| `cordis-plugin-timer` | Timer service for cordis | the primitive any polling design would use; **no mesh poller ships** |
| `dsh-schedule` | Agent-scoped durable after/at/fixed-rate reminders **over the session event log** | needs a live session in that engine's log — not a mesh scheduler |
| `dsh-mcp-client` | MCP client bridge | outbound only; the engine as client |
| `dsh-http-proxy` | Process-wide **outbound** HTTP proxy policy | egress, not ingress |
| `dsh-terminal` / `dsh-subprocess` | local PTY / managed process groups | a worker node's *executors*, all local |
| `dsh-cordis-host-runner` | Dynamic package definition registry, host-half sandbox lifecycle, invoke handler table | **a model can mount a plugin at runtime** — so a placement route can be added without restarting the engine (contrast `--trusted-host`, which is startup-only) |
| `dsh-tool-cordis` | Self-referential cordis toolset: inspect the live runtime, **mount and dispose model-written plugins** | same |

### 1.2 The full shipped inventory

One line each, grouped. Purposes are the packages' own `package.json` `description` fields, trimmed (read from all 240 `package.json` files this session).

**Framework (7).** `cordis` Meta-framework for modern JavaScript applications · `cordis-plugin-group` Nested plugin group · `cordis-plugin-hmr` Hot Module Replacement · `cordis-plugin-include` Include files in cordis configurations · `cordis-plugin-loader` Plugin loader · `cordis-plugin-timer` Timer service · `cosmokit` Common utilities.

**Launcher & boot (6).** `dsh` dsh CLI: profile boot, plugin management, and the browser UI alias · `dsh-app-boot` Shared boot glue: .env loading, fail-loud Loader guards, snapshot-aware config resolution · `dsh-cmdline` Immutable command-line handoff from a launcher to app plugins · `dsh-launch-environment` Immutable launch environment recording which layer supplied each value · `dsh-home-paths` Shared filesystem path helpers · `dsh-package-manifest` Shared type declarations for `package.json.dsh`.

**Surface bundles (6).** `dsh-base` The shared core as a profile bundle (first patch layer) · `dsh-web-app` The browser-surface bundle (web patch layer + runtime glue) · `dsh-headless` The one-shot bundle: direct Agent/Session runner over dsh-base, **no Host, HTTP or browser layer** · `dsh-sdk-app` SDK profile bundle: stdio JSON-RPC serving · `dsh-sdk-minimal` Standalone minimal SDK bundle · `dsh-acp-app` ACP profile bundle: automation-only JSON-RPC stdio.

**Transport, auth, routing (6).** `dsh-host-webserver` route registration · `dsh-client-connection` authenticated RPC transport + browser fixture · `dsh-api-gateway` Typert Remote Host dispatcher + Client API endpoint · `dsh-api-remotes` Remote BFF assembly · `dsh-client-file-upload` Agent-scoped browser file upload, streaming intake · `dsh-host-frontend-static` SPA dist server owning the fallback seat.

**Remote API surface (4).** `dsh-api-session-controller` · `dsh-api-settings-controller` Remote owner for configuration surfaces · `dsh-api-workspace-controller` Workspace Remote commands and reconnect-safe state · `dsh-api-workspace-files` Workspace file service and Client resource provider.

**External event intake (2).** `dsh-webhook` · `dsh-webhook-github`.

**Typert reflection (3).** `dsh-typert-protocol` Compiler-independent Remote metadata + Typert provider protocols · `dsh-typert-registry` Runtime registry for generated reflection and Zod schemas · `dsh-typert-loader` Loader integration for generated Typert contributions.

**Agent core (8).** `dsh-agent` Agent interface, registry, initiator scope, event vocabulary · `dsh-agent-loop` The concrete agent loop · `dsh-agent-default-model` Default model selection · `dsh-agent-instructions` AGENTS.md/CLAUDE.md loader · `dsh-agent-presets` Per-session agent composition from preset cordis.yml files · `dsh-agent-tool-presentation` Agent-plane presentation selector (PTC / native / both) · `dsh-persona` Composition-authored deployment persona section · `dsh-system-prompt` System prompt assembly registry.

**Delegation (7).** `dsh-subagent` named-provider registry · `dsh-subagent-spawn-in-process` · `dsh-subagent-fork-in-process` · `dsh-subagent-in-process-driver` · `dsh-tool-subagent` model-facing delegation tool · `dsh-tool-subagent-control` send_message / interrupt_agent / list_agents · `dsh-workflow` Workflow capability seam · `dsh-workflow-worker-thread` worker-thread workflow engine · `dsh-tool-workflow` · `dsh-tool-ralph` Ralph loop over the workflow and subagent seams.

**Sessions (22).** `dsh-session` event-sourced store · `dsh-session-persistence` / `-jsonl` durability seam and JSONL backend · `dsh-session-format` + `-catalog` + `-v0-to-v1` + `-v1-to-v2` + `-v2-to-v3` format migration · `dsh-session-projection` + `-cache` · `dsh-session-query` + `-sqlite` (FTS5 search) · `dsh-session-reference` cross-session snapshot references · `dsh-session-stats` · `dsh-session-turn-outline` · `dsh-session-title` + `-llm` + `-first-prompt-llm` · `dsh-session-telemetry` + `-otel` · `dsh-session-log-deepseek` · `dsh-session-log-export` · `dsh-session-checkpoint-policy`.

**LLM (5).** `dsh-llm` provider-neutral seam · `dsh-llm-deepseek` chat-completions adapter · `dsh-llm-pi-ai` pi-ai-backed twin · `dsh-llm-retry` retry policy · `dsh-deepseek-llm-api-extensions` additive request-field registry.

**Tools (25).** `dsh-tools` registry + execution pipeline · `dsh-tool-bash`, `-bash-persistent`, `-pwsh`, `-pwsh-persistent` · `dsh-tool-fs`, `-fs-search` · `dsh-tool-str-replace-editor` · `dsh-tool-web` · `dsh-tool-jobs` · `dsh-tool-goal` · `dsh-tool-todo` · `dsh-tool-skill` · `dsh-tool-ask-user` · `dsh-tool-present` · `dsh-tool-cordis` · `dsh-tool-call-timeout-policy` · `dsh-repeat-tool-reminder` · `dsh-mcp-client`.

**Capability seams and local backends (30).** `dsh-fs` + `-local` + `-sandbox` + `-observation-policy` · `dsh-shell` + `dsh-bash-local` + `dsh-bash-sandbox` · `dsh-pwsh-local` + `dsh-pwsh-sandbox` · `dsh-sandbox` + `-local` + `-policy` + `-windows-acl` · `dsh-subprocess` + `-local` · `dsh-code-runtime` + `-worker-thread` · `dsh-spill` + `-local` + `-policy` · `dsh-storage` + `-domain` + `-json` · `dsh-attachment` + `-local` · `dsh-credentials` + `-local` · `dsh-settings` + `-file` · `dsh-authorization` · `dsh-permission-presets` · `dsh-user-approval` · `dsh-user-questions` · `dsh-web` + `-fetch-http` + `-search-deepseek` · `dsh-file-reference` + `-local` · `dsh-skill` + `-badge` + `-filesystem` · `dsh-jobs` + `-local` · `dsh-schedule` · `dsh-goal` + `-goal-round-driver` · `dsh-plan-mode` · `dsh-compaction` + `-basic` + `-tool-result-pruner` · `dsh-token-meter` · `dsh-output-retention` · `dsh-chunked-list` · `dsh-atomic-write` · `dsh-deque` · `dsh-invariants` · `dsh-scope` · `dsh-command-*` + `dsh-commands` · `dsh-time-context` · `dsh-tmux-context` · `dsh-native-command` · `dsh-host-directory-picker` + `-auto` + `-browse` + `-native` · `dsh-host-open-in-app` · `dsh-host-plugin-inventory`.

**Hooks & bridging (3).** `dsh-hook-protocol` Shared Claude Code / Codex hook wire protocol · `dsh-hooks-claude-code` · `dsh-hooks-codex`.

**Client shell and UI (~65).** `dsh-client-modules`, `-connection`, `-hmr`, `-locale`, `-resources`, `-file-upload`, `-ui-*` (44 surfaces: layout, sidebar, chat, conversation, trajectory, tool, jobs, goal, plan, settings, models, plugins, approval, user-questions, workflow-run, …). Presentation only; none of them is a transport.

**Util & platform (8).** `dsh-util-crypto`, `-time`, `-values`, `-workspace-path`, `dsh-brand`, `dsh-timeout`, `dsh-win32-process`, `node-addon-system` (Linux Landlock launcher + POSIX `flock`) · `schemastery` schema validator.

---

## 2. The six questions, answered from source

### (a) What do the `/api` paths actually reach?

The `/api` prefix is registered once, by `dsh-client-connection`, as a **prefix** route and every request is fenced before dispatch (`NM/dsh-client-connection/lib/index.js:767-781`; fence call at `:772`). Behind the fence sits a fetch handler with two layers (`:570-585`): (**1**) a table of *exact* Fetch routes registered by other plugins, tried first; (**2**) an RPC **interceptor** on the `/api` channel.

The interceptor is installed by `dsh-api-gateway` (`NM/dsh-api-gateway/lib/index.js:454-456`) and claims any `namespace/method` pair that a live Cordis service exports (`:510-517`). Dispatch resolves the receiver, validates arguments and calls the method (`:728-737`, `:738-757`). So:

> **Every `@typert`-marked method on a live service is an HTTP endpoint at `POST /api/<namespace>/<method>`.**

The wire shape is small and confirmed three times over: `POST`, `content-type: application/json` required (`:641`), the body must match `clientRequestSchema` `{type:"client-request", rpcId, method, payload}` (`:648`, schema at `NM/dsh-client-connection/lib/index.js:502-515`), the `method` field must equal the endpoint derived from the path (`:651-655`), and `payload` must contain exactly one field `args` (`NM/dsh-api-gateway/lib/index.js:925-936`).

**What is on that surface today, from `dsh-api-session-controller` alone** (`method:` lines in `NM/dsh-api-session-controller/lib/typert.remote-client.js`): `session/list` `:896` · `session/create` `:819` · `session/prompt` `:989` · `session/cancel` `:762` · `session/fork` `:871` · `session/rename` `:1015` · `session/search` `:1040` · `session/page` `:963` · `session/attachment` `:737` · `session/selectModel` `:1066` · `session/updateQueue` `:1091` · `session/modelCatalog` `:922` · `session/openWorkspacePath` `:937` · `session/canOpenWorkspacePath` `:787` · `session/control` (**stream**, `:802`) · `session/follow` (**stream**, `:845`) — plus an unrelated `fileReferences/list` `:696` and `skills/list` `:1116`.

`session/create` takes a `request` object and resolves+mounts the agent preset (`NM/dsh-api-session-controller/lib/types/agent.js:381-394` — `presets.resolve(presetId)` then `presets.mount(agentCtx, resolvedId)` at `:391`; the default is used when omitted). `commands.js:105` calls `agents.ensureSession(sessionId, cwd, request.sessionId !== undefined, request.agentPreset)` — so the same call **adopts or resumes** a caller-named session rather than only minting a new one.

**This is the finding that attacks the mandate's premise.** A turn can already be placed on another node, over plain HTTP, into a named existing session, with the full persona and toolbelt, **using zero new code** — provided three conditions hold: the node's engine is reachable, it was launched with `--trusted-host <its authority>`, and the caller holds a cookie for that authority.

### (b) `dsh web --host`, and what `--host 0.0.0.0` does

The web app's flag family is exactly `--host`, `--port`, `--trusted-host <authority...>` (repeatable) and `--no-open` (`NM/dsh-web-app/lib/startup.js:22`; the docstring at `:5-7` names the same four).

`--host 0.0.0.0` is **refused at parse time**, before any socket exists:

```js
// NM/dsh-web-app/lib/startup.js:40
if (options.host === "0.0.0.0") program.error("error: --host 0.0.0.0 is intentionally not supported yet for safety: it would expose remote code execution to the network; use 127.0.0.1 instead");
```

Three precisions the placement design needs, none of which are in `20-placement.md` §2(a):

1. **The block is a CLI check, not a schema rule.** The webserver's own schema accepts exactly two literals — `z.union([z.const("127.0.0.1"), z.const("0.0.0.0")])` (`NM/dsh-host-webserver/lib/index.js:141`). So `0.0.0.0` is *schema-legal* and only the commander action refuses it.
2. **A patch layer can therefore set it.** The web composition takes the host from the startup service with an explicit deployment fallback — `host: !!js ctx.webStartup.host ?? '127.0.0.1'` (`NM/dsh-web-app/cordis.patch.yml:139`) — and that same file's header states that later layers override earlier rows by id, with `--patch` overlays applied last (`:1-3`). A `--patch` naming the `webserver` row with `host: 0.0.0.0` is not blocked by the CLI check at all.
3. **No third host is possible.** `--host 192.168.50.138` passes the CLI (the check is the literal `0.0.0.0` only) and then **fails the webserver schema**, because the union has no such member. So "bind to the LAN IP instead" is not an available move; the choice is loopback, all-interfaces, or a proxy in front.

`--port` must match `/^\d+$/` (`NM/dsh-web-app/lib/startup.js:41`), and port `0` means an OS-assigned port (`:22`).

### (c) Can a client attach to a REMOTE engine — and what does it need?

**The browser client auto-targets whatever engine served it, and nothing in the shipped client can be pointed at another.** `remoteStreamUrl()` derives the WebSocket origin from the page:

```js
// NM/dsh-api-gateway/lib/client.js:541-547
function remoteStreamUrl() {
  const location = globalThis.location;
  const base = location?.origin !== void 0 && location.origin !== "null" ? location.origin : INTERNAL_BASE;
  const url = new URL(REMOTE_STREAM_MUX_PATH, base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.href;
}
```

with the path a constant, `/api/remote.mux` (`NM/dsh-api-gateway/lib/client.js:49`; host side `NM/dsh-api-gateway/lib/index.js:11`), and the socket opened at `NM/dsh-api-gateway/lib/client.js:402`. The same page-origin rule holds on the unary side (`NM/dsh-client-connection/lib/client.js:6255`). **`20-placement.md` §1.3 is exactly right**, and it is right for the reason it gives: there is no configurable engine host anywhere in the browser half. `INTERNAL_BASE` is the worker/SSR fallback, not a routing option.

**So the unit of "attaching to a remote engine" is an HTTP client, not the GUI.** The requirements are three, and each is a hard gate:

| requirement | evidence |
|---|---|
| The engine accepted the authority | `isTrustedApiRequest` accepts loopback, or a configured `trustedHosts` entry, and rejects `sec-fetch-site: cross-site` and mismatched `Origin` (`NM/dsh-client-connection/lib/index.js:201-215`). `trustedHosts` is assembled from `--trusted-host` (`NM/dsh-web-app/cordis.patch.yml:184-188`). |
| The request carries a valid cookie | `requestRejection` returns **403** for a failed fence and **401** for a fence pass without authentication (`NM/dsh-client-connection/lib/index.js:553-556`). |
| The cookie exists *for that authority* | The cookie's **name** is `"dsh-auth-" + base64url(sha256(authority))` and its payload is HMAC-signed over `{authority, issuedAt, expiresAt}` (`:280-282`, `:298-320`). A cookie from `127.0.0.1:3099` is *invisible* to `secratary.tail93e6e6.ts.net` — not merely invalid: the name does not match, so `isAuthenticated` returns false at `:436` before any signature check. |

Getting a cookie is a **one-time token exchange per origin**: `GET /?token=<launch token>`, exactly one `token` parameter, `pathname === "/"`, which answers `303 → /` with `set-cookie: dsh-auth-<sha256(authority)>=…; HttpOnly; SameSite=Strict; Max-Age=30d` (`NM/dsh-client-connection/lib/index.js:386-425`).

**And here is the constraint the placement design does not yet account for.** The launch token is `randomBytes(32)` generated **per process** and kept in a `WeakMap` keyed on the application root context (`:227`, `:240-246`):

```js
const PROCESS_LAUNCH_TOKENS = /* @__PURE__ */ new WeakMap();
function processLaunchToken(owner) { … encodeBase64Url(randomBytes(SECRET_BYTES)) … }
```

It is **never persisted**. It is printed once, as part of the URL line, to the engine's stdout (`NM/dsh-web-app/lib/index.js:203` — `console.log(\`dsh web: ${authenticatedUrl}…\`)`; the token is appended by `authenticatedUrl` at `NM/dsh-client-connection/lib/index.js:370-377`). The clean URL handed to the model's shell is token-free (`NM/dsh-web-app/lib/index.js:94-99` — `http://127.0.0.1:<port>` — published as `DSH_WEB_URL` at `:189-190`).

**Consequence, and it is the crux of this whole document:** every `GET /?token=` cookie harvest requires reading the **target engine's stdout or its captured log on that node**, and the token changes on every engine restart. A broker on `secratary` cannot mint a cookie for `ZABZ-TECH`'s engine by itself. Something on the target node must either keep the token, or the request must not need a cookie at all. That single sentence decides the ranking in §3.

### (d) Is there any notion of a second engine, a worker, or a job queue?

**No — and this was searched hard rather than assumed.** I grepped every `.js` file in `NM/` for `\b(cluster|worker|fleet|broker|scheduler|second engine|remote engine|other node|placement)\b` — 379 matches, of which the tool returned 250 inline. **Every one I inspected is in-process vocabulary**, and the coincidences are instructive:

- **`worker`** = a Node `worker_thread`. `NM/dsh-code-runtime-worker-thread/lib/index.js:453-501` (spawns `Worker`, `worker.terminate()`), `NM/dsh-workflow-worker-thread/lib/index.js:276-386`, `NM/dsh-client-file-upload/lib/types/client/runtime.js:164`. Nothing named `worker` refers to a machine.
- **`placement`** = where a *message* sits in one session's input queue: `z.union([z.literal("queued"), z.literal("steering"), z.literal("context")])` (`NM/dsh-api-session-controller/lib/typert.host.js:83`, mirrored `:189`; produced at `NM/dsh-api-session-controller/lib/index.js:1154-1162`). It is a UI concept about queue-or-steer, **not a node scheduler**.
- **`scheduler`** = the tool-call scheduler inside a single agent loop (`NM/dsh-agent-loop/lib/index.js:485-499, 621, 1222, 1422`).
- **`cluster`** = the in-memory `Map<SessionId, Session>` on the client (`NM/dsh-api-session-controller/lib/types/client/sessions/manager.js:1`, `:17`).
- **`fleet` / `broker`** = zero hits outside this document's own vocabulary.

The two things that *sound* like a queue are both per-process:

- `dsh-jobs-local` — `store = /* @__PURE__ */ new Map()` (`NM/dsh-jobs-local/lib/index.js:105`). The registry is a process singleton keyed by owning agent; the dsh-web-app patch states its ownership rule explicitly (`NM/dsh-web-app/cordis.patch.yml:374-382`). **Nothing durable, nothing cross-process.**
- `dsh-schedule` — *"Agent-scoped durable after, at, and fixed-rate reminders **over the session event log**"* (`NM/dsh-schedule/package.json`). It needs a session in that engine's log; it is not an external work intake.

**And the harness states the limit in its own words, twice**, in the subagent seam:

> *"**Process-local residency** — the Activation inbox and ownership graph do not coordinate two harness processes; concurrent access to one persistence store needs a durable mailbox and cross-process lease protocol."* — `NM/dsh-subagent/README.md:175`

> *"**Cross-process continuation** — a durable mailbox and lease protocol would let two harness processes share one persistence store."* — `NM/dsh-subagent/README.md:188`

That is an independent, upstream confirmation of `20-placement.md` §1.1: **one engine per `DSH_HOME` is not merely a good idea, it is the only shape the shipped code supports.** It also names the missing piece for anything more ambitious — a durable mailbox plus a cross-process lease, which is precisely what Phase 3's `jobs`/`leases` table is.

### (e) Can a plugin register an HTTP route another machine could call? **Yes — and this is the cheapest transport in the tree.**

The API is `dsh-host-webserver`, and it is four methods on one service:

```js
// NM/dsh-host-webserver/lib/index.js — the service is provided as "webServer" (:157)
webServer.register({ kind: "exact" | "prefix", path, handler })  // :176-183
webServer.registerUpgrade({ path, handler })                      // :190-196   (WebSocket)
webServer.registerFallback(handler)                               // :205-211   (one owner only)
webServer.tapIndex(transform)                                     // :219-225
```

Handler ownership is total: *"Route handlers retain direct response ownership"* (`:101`). Matching is exact-table first, then longest prefix (`:322-331`), and the package *"knows no harness concepts"* (`:98`) — so a placement route is an ordinary HTTP handler, not a protocol participant.

**Critically: a route registered this way is NOT fenced.** The Host/Origin fence and browser authentication live in `dsh-client-connection` and are applied by *that* package to the `/api` prefix (`:767-781`) and by `connection.rpc.register` to its own channels (`:602-619`, fence at `:609`). A plugin calling `ctx.webServer.register` directly **chooses** its own auth. Three shipped routes prove the three available choices:

| shipped route | auth it chose | evidence |
|---|---|---|
| `plugin-health` → `GET /healthz` | **Opt-in fence**: calls `connection.requestRejection(req)` when the service exists, else refuses any non-loopback peer | `HC/packages/plugin-health/lib/index.js:752-803`; `ROUTE = '/healthz'` at `:85`; fence at `:766-781` |
| `dsh-webhook-github` → configured path | **Its own HMAC**: verifies `x-hub-signature-256` against a credential, 401 on failure. **No `requestRejection` call at all** | `NM/dsh-webhook-github/lib/index.js:181-190` (registration); `:118-127` (signature) |
| `dsh-host-open-in-app` | three routes, one of them a **prefix** (`OPEN_IN_APP_ICON_PREFIX`) | `NM/dsh-host-open-in-app/lib/index.js:1324-1375` |

There is a fourth registry worth knowing, for routes that *want* the fence: `connection.fetch.register({path, methods, requestBody, fetch})` for an exact path under `/api` (`NM/dsh-client-connection/lib/index.js:548-551`, validation `:696-700`), and `connection.rpc.handle(channel, handler)` for a whole new fenced RPC channel at any `/[A-Za-z0-9._~-]+` path other than the reserved `/api` (`:540-546`, `:602-619`, pattern at `:520`, reservation at `:693-695`).

**The only remaining obstacle is publication, not capability.** A plugin route lands on the same `node:http` server as everything else, so it inherits the bind host. Loopback by default (`NM/dsh-web-app/cordis.patch.yml:139`), and `0.0.0.0` only via a patch (§2b). But loopback plus a proxy is exactly the shape already proven on `secratary` — `tailscale serve` → `127.0.0.1:3086` gate → `127.0.0.1:3089` engine (`20-placement.md` §1.0, MEASURED). **A plugin route behind `tailscale serve` needs no token, no cookie, no client change, and no broker.** Tailscale is already the only path between the two buildings.

### (f) Can an agent turn run with no browser? Yes — four ways, with different agents.

| route | evidence | what it is | the catch |
|---|---|---|---|
| `dsh --profile headless "<task>"` | `NM/dsh/lib/bin.js:37` (help example); `NM/dsh-headless/lib/startup.js:21`; `NM/dsh/README.md:14` | *"Run one fresh persisted session, print the final answer, and exit."* Streams reasoning to stderr, prints the final assistant text to stdout | **A different, weaker agent — confirmed at the source, not from a secondary doc.** `NM/dsh-headless/cordis.patch.yml` mounts exactly three rows over `dsh-base` (`code-runtime`, `headless-startup`, `headless-runner`) and **no `agent-presets` row**, so no persona, no preset toolbelt, no MCP. It also **cannot be given an existing session**: it mints `session-${randomUUID()}` (`NM/dsh-headless/lib/index.js:135`) and its config is `{ task }` only (`:26`) |
| `dsh --profile sdk` | `NM/dsh/README.md:15`; `NM/dsh-sdk-protocol/README.md:36-46` | newline-delimited JSON-RPC 2.0 over **stdio**: `initialize`, `session/prompt` (a durable-enqueue receipt), `shutdown`; notifications `session.event`, `session.status`, `subagent.started/finished` | stdio, so it needs a process spawn (hence ssh); *"**No cancel or session-close methods** — a client abandons a turn by closing the runtime process"* (`README.md:114`); sessions are created by the runtime (`NM/dsh-sdk-jsonrpc-server/lib/index.js:47-62`, `initialize` at `:110-120`) |
| `dsh --profile acp` | `NM/dsh/README.md:13`; `NM/dsh-acp/package.json` | Agent Client Protocol over JSON-RPC stdio, for editor hosts | same stdio shape; automation-only profile |
| **the `/api` Remote RPC** | §2(a) | **the only headless route that can prompt an *existing, named* session with the full preset**, and the only one that is pure HTTP | needs the fence + a cookie (§2c) |

`dsh/README.md:44` adds a fifth possibility that does not ship: a **custom profile** is a name under `$DSH_HOME/profiles/` whose `dsh.profile.bundles` may name any of the shipped bundles plus its own `node_modules`. So a node could run a profile that composes `dsh-base` + `dsh-agent-presets` + a custom one-shot runner — a headless node *with* the persona. That is configuration and a small plugin, not a fork.

**Subcommands of `dsh`, exhaustively** (`NM/dsh/lib/bin.js:82-116`): the root takes `--profile <name>`, `--from-default-profile <name>`, `--patch <path>` (repeatable), `--dump-config`, `--dump-default-config`, `--version`, and passes every unrecognised token through to the booted app. Exactly **two subcommands** are declared: **`web`** (`:100`, an alias of `--profile web`) and **`plugin`** (`:105`, forwarding the rest to pnpm in the profile directory). Dispatch has three modes — `profile`, `plugin`, `dump-config` (`:143-166`). Profile `desktop` is refused everywhere as Electron-owned (`:29`). **`dsh` is the only `@deepseek-ai` package with a `bin`** — a scan of all 240 `package.json` files returned only `dsh` and `cordis` (the framework's own `bin.js`); no `dsh-worker`, `dsh-node`, or second launcher exists.

---

## 3. The four candidate transports, cheapest first

### 3.1 An HTTP route provided by a plugin on the target node — **exists in pieces; ~150 lines to close**

**What exists today.** The route API (§2e). A worked template for a *signed external ingress that creates a real preset-mounted session*: `dsh-webhook` + `dsh-webhook-github`. The template matters because it already solves the two hard parts:

- **The session it creates is a first-class session, not a degraded one.** `createWebhookSession` resolves the preset, mounts it before publication, creates the canonical workspace, attaches the session, sets the permission preset, titles it, and prompts it (`NM/dsh-webhook/lib/index.js:90-148`; preset mount at `:93-94` and `:108`; prompt at `:120-134`).
- **The route is authenticated by the plugin, not by the browser fence.** `Config = { source, path, secretEnv, maxBodyBytes }` (`NM/dsh-webhook-github/lib/index.js:167-172`), route registered at `:190`, `POST` only, JSON content-type required, bounded body, HMAC over the raw body against a credential, **401** on bad signature, **202** accepted after in-memory dispatch (`:112-145`).

**What is NOT mounted.** Neither package appears in any shipped composition: a grep for `webhook` across **every** `.yml` in the whole DSH tree returned **0 matches**, and `NM/dsh-web-app/cordis.patch.yml` has no webhook row. `dsh/README.md:52` says it plainly — *"`config/examples/` ships opt-in overlays for GitHub review webhooks … They are never part of a default profile."* So today, on the owner's nodes, **the capability exists and is switched off.**

**What would have to be written.** A placement route, not a GitHub adapter. Concretely: one host-plane plugin registering one exact route (say `/mesh/place`) that (1) authenticates a shared secret from `ctx.credentials`, (2) validates a bounded JSON body `{job_id, kind, workspacePath, prompt, agentPreset, permissionPreset, needs}`, (3) resolves the preset and **asks the node's own admission governor whether it can take a slot now**, (4) returns `200 {state:"PLACED", …}` or `200 {state:"QUEUED", position:N}`, and (5) creates the session exactly as `dsh-webhook` does. Steps (1)–(4) are new; step (5) is a copy of a shipped 60 lines.

**Why it is the cheapest.** It needs **no cookie, no token, no gate, no second engine, and no client change**. It is reachable the moment the node's port is published, and `tailscale serve … 127.0.0.1:<port>` is already the proven publication shape on `secratary` (`20-placement.md` §1.0). It also gives the honest refusal semantics the owner's rule demands for free, because it calls the node's own governor before answering.

**The three real caveats**, all from the source: the webhook runtime is *"Process-local fire-and-forget only — a crash loses rule calls that have not admitted a prompt; there is no queue, replay, or retry"*, with *"No built-in deduplication"* and *"No completion result — HTTP acceptance and rule settlement do not report Agent success, idle, or output"* (`NM/dsh-webhook/README.md:71-73`). A placement route inherits all three unless it writes its own idempotency and completion path. **That is precisely the part of Phase 3 that is genuinely new work** — the *decision*, the *idempotency key*, the *queue* and the *heartbeat* — and it is exactly the part that cannot be borrowed from a shipped package.

**Smallest experiment that proves it.** On one node, add a `--patch` overlay mounting `dsh-webhook` plus a ~20-line rule plugin and `dsh-webhook-github` pointed at a path of your own, with a shared secret in credentials. Then from the *other* machine, over the tailnet, `POST` a signed body to `https://<node>.tail93e6e6.ts.net/<path>` and observe a **202** and a new session appearing in that node's session list. That is one evening's work and it proves the entire transport, the auth model and the session-creation path at once — with no new package.

### 3.2 ssh invoking a headless run — **exists; wrong agent, and splits the record**

**What exists.** `ssh <node> 'dsh --profile headless "<task>"'` works today: the subcommand exists (`NM/dsh/lib/bin.js:37`), it runs one task and exits (`NM/dsh-headless/lib/startup.js:21`), and it prints the final answer to stdout. `20-placement.md` §2(c) already accepts ssh *as a launcher* and rejects it *as the work*; that reading survives this audit.

**What would have to be written.** Nothing to prove it; a great deal to use it well. The blocking facts are all in §2(f): `--profile headless` mounts no presets, so the work is done by a different agent than the one whose session asked for it; there is no way to name an existing session, so **the durable record stays on the origin node while the work runs on the target** — `20-placement.md` §2(c)(iii) — and a fresh random session id is minted per invocation (`NM/dsh-headless/lib/index.js:135`) so a crashed run cannot be resumed. The alternative — a custom profile composing `dsh-base` + `dsh-agent-presets` — is available (`dsh/README.md:44`) but is new configuration on every node.

**Caveat on cost that the design already has right:** each ssh is a tool call on the origin node, so it serialises against every other tool call in that step and costs the origin ~160 MB (`20-placement.md` §1.5).

**Smallest experiment.** `ssh <node> 'dsh --profile headless "echo hi"'` and read the exit code and stdout; then repeat with `--profile sdk` and drive `initialize`/`session/prompt` over the pipe to prove a *programmatic* remote turn. Both are five minutes and both will succeed — which is exactly why this is not the answer: they prove the transport, not the agent.

### 3.3 A shared queue table on the authority, polled by each node's engine — **nothing exists; must be written, and the poller is the new part**

**What exists.** Nothing that polls. The authority's `next_stage_node_reports` table already records per-node facts (`20-placement.md` §4.3, READ), the journal is already replicated by `autosync`, and `cordis-plugin-timer` provides a timer service. There is **no** engine-side poller, no external work intake, no lease, no heartbeat anywhere in the tree (§2d). `dsh-schedule` cannot serve: it is scoped to a session's own event log (`NM/dsh-schedule/package.json`).

**What would have to be written.** A plugin on each node that, on a timer, reads the authority's job table, claims a row with an atomic conditional update, heartbeats a lease, and runs the job by creating a session — i.e. **§3.1's route body, invoked from a loop instead of from a request.** So this is *not* an alternative to §3.1; it is §3.1 plus a scheduler and minus the network call. Its advantage is that it needs no inbound reachability at all, which matters for a node that is behind NAT or asleep. Its cost is a second writer against the authority's SQLite and the authority's own measured contention (`20-placement.md` §1.6: 4 cores, swap 100 % used).

**Smallest experiment.** One node, one plugin, one table: an INSERT from anywhere followed by the node picking it up within one poll interval and writing back `running` + a heartbeat, with the row visible via `ps_db_query`. That proves the claim-lease-heartbeat loop, which is the only novel mechanism.

### 3.4 A real broker — **nothing exists; this is the most expensive option and the least necessary**

**What exists.** Nothing. No `dsh-broker`, no `dsh-scheduler`, no node registry, no capacity federation (§1.1, §2d). `20-placement.md` §4.3 is right that the queue is genuinely new work and the *registry* is not.

**And the harness already anticipates the piece that a broker at the *tool* level would need — with the blocker named.** `ctx.subagents` is a **named-provider registry**: *"**One service, many providers.** The service is a named-provider registry; each backend registers under a unique name and a request picks one by name."* (`NM/dsh-subagent/README.md:69`), and *"A composition can offer in-process, ACP, SDK, Codex, or Claude Code children side by side"* (`:12`). The contract is public and small — `SubagentProvider` requires `name`, `capabilities`, `inheritsParentContext`, `start()`, and optional `prepareContinuable()` (`NM/dsh-subagent/lib/types/types.d.ts:320-376`). A **remote subagent provider** is therefore a *supported extension point*, and the shipped README states exactly what stops it:

> *"**ACP children remain one-shot and are not trace-enumerable** — an ACP run has no local child session in the parent's session corpus, and **remote providers need an Activation ownership contract before they can support continuable children**."* — `NM/dsh-subagent/README.md:170`

> *"**Continuable ACP children** — requires persisting the remote session id and a per-child continuation advertisement."* — `NM/dsh-subagent/README.md:189`

Two more limits that a broker must not pretend away: *"**A direct parent must remain live for child-to-parent delivery** — the service has no durable parent mailbox"* (`:172`) and *"**Process-local residency**"* (`:175`). **This is the sharpest single finding in the audit for Phase 3's shape:** the cheapest place to put cross-node placement is **the subagent provider seam, which already exists and is already pluggable**, and the *one-shot* case is buildable today while the *continuable* case is blocked on a contract the harness itself names as missing. A broker that duplicates the provider registry without adding that contract would be building a parallel system next to an extension point.

**Smallest experiment.** A ~one-file provider registering under name `remote` whose `start()` issues §3.1's HTTP call to a chosen node and whose returned `SubagentRun` resolves with the remote session's final assistant message, then mounting it alongside `spawn` in the `zabz` preset. If a `subagent` tool call can be routed to another node by name, the placement decision has somewhere to live — and it is the broker's decision, not the model's, as long as the *provider* chooses the node.

### 3.5 Ranking, with the blocker for each

| rank | transport | exists today | new code | blocked by |
|---|---|---|---|---|
| **1** | plugin HTTP route on the target (§3.1) | route API, a full template, publication shape | ~150 lines: route + shared-secret auth + governor call | nothing architectural — only the write |
| **2** | `session/*` Remote over `/api` (§2a) | **fully shipped, zero new code** | a client that holds the cookie | **the per-process launch token** (§2c) — a cookie cannot be minted or kept valid across an engine restart without reading that node's stdout |
| **3** | ssh + headless/SDK stdio (§3.2) | fully shipped | a node-selection policy | the agent is not the same agent, and the durable record is on the wrong machine |
| **4** | shared queue table + poller (§3.3) | nothing | plugin + table + lease loop | the authority is a 4-core box; a second writer is a new failure mode |
| **5** | real broker (§3.4) | nothing | all of the above plus a decision service | the subagent README's missing *Activation ownership contract* for continuable remote children |

---

## 4. VERDICT

**Phase 3 must change — not because its goal is wrong, but because two of its five items are already shipped and a third has a cheaper home.**

`20-placement.md` §6.4 states the premise in the document's own words: *"an agent that fans out a fleet today fans it out locally … That is why §8 Phase 3 is not load-bearing polish; it is the load-bearing change."* **That premise is half wrong, and the half that is wrong is the expensive half.** The *decision* — which node should run this — genuinely does not exist anywhere in the tree, and Phase 3 item 2 is correct that it is new work. But **the mechanism does not need to be invented, and item 1 as written is unnecessary.** DSH already ships *(i)* a plugin route API that any machine can call with handler-chosen auth (§2e, proven by three shipped routes including one that mints a real preset-mounted session), *(ii)* a complete HTTP RPC surface — `POST /api/session/create|prompt|cancel|fork` — that can **place a turn into a named existing session on a remote node with the full persona**, requiring zero new code on either end (§2a), and *(iii)* a **pluggable named subagent provider seam** that is the natural home for a placement decision and whose own README names the exact missing contract (`NM/dsh-subagent/README.md:170`, `:189`).

**What Phase 3 should say instead, item by item:**

- **Item 1 — "federate the capacity surface … each node's plugin-health publishes to the authority on a heartbeat" — DROP the federation, keep the surface.** `/healthz` is already live on the engine (`20-placement.md` §1.6, MEASURED) and is already an HTTP route a plugin registered (`HC/packages/plugin-health/lib/index.js:752-803`). A placement service that can *call* it does not need it *pushed* to a table first. **Replace item 1 with: "the placement service reads each candidate node's `/healthz` directly, over the tailnet, with a bounded timeout; the authority stores only the decision."** That removes the heartbeat, the PUBLISH verb, the node-report column-add, and 15 seconds of staleness from every decision — and it removes the authority as a *writer* of node state, which is the right call for a 4-core box with swap at 100 %. The one thing that must be added is the missing `/healthz` field the document already identifies (disk headroom, D6), which is a change to one shipped plugin, not a new protocol.

- **Item 2 — "the placement service: PLACE / OFFER / COMPLETE + computed-position queue" — KEEP, but re-scope it as a *decision service with one write path*.** Its first job is not to invent a transport; it is to **(a)** resolve `job_id → node` from live `/healthz` readings and the node's own governor answer, **(b)** write the §5.2 handoff to the journal, and **(c)** then act on the target node by exactly one mechanism: the §3.1 plugin route. The `PLACE`/`QUEUED` reply shape, the computed `position_seq`, the no-refusal rule and the heartbeat-not-pid lease are all worth keeping verbatim — they are the genuinely new, genuinely load-bearing part, and the harness has nothing like them (§2d). **But `OFFER` should be deleted as a distinct verb**: with a plugin route on the target, the request *is* the offer, and the target's governor answers in the response body.

- **Item 3 — "wire `agent-fleet` to the broker" — KEEP, and add the item the audit says is missing.** The integration point is `agent-fleet`, and the honest cheapest first version is not a broker call at all: it is **a remote `SubagentProvider`** registered alongside `spawn` in the `zabz` preset, whose `start()` issues the §3.1 call to the node the broker chose (`NM/dsh-subagent/lib/types/types.d.ts:320-376`). That is one file, it uses a public extension point, it inherits the delegation tool the preset already mounts, and it keeps the model's `subagent` call unchanged. **New item 3b: adopt the §3.1 route as the mesh's one placement transport, and state explicitly that the launch token's per-process lifetime (`NM/dsh-client-connection/lib/index.js:240-246`) is why the mesh does NOT route through `/api/session/prompt`** — because a cookie harvested once dies on the next engine restart, and a 401 is indistinguishable from a permission error.

- **Item 4 — "the §5.2 pre-work handoff as a required argument" — unchanged, and now more important.** With work placed on a node the owner is not holding, the handoff stops being a recovery nicety and becomes the *only* record that a job exists. Its branch + base commit + `session_id` is what lets a second node resume it.

- **Item 5 — "disk headroom into the placement inputs (D6)" — unchanged, and it is now the first thing the placement service should read**, because the only transport this document recommends is a route on the target node, and a node that cannot write a worktree must not be chosen in the first place.

**And one structural correction that follows from all of it: the mesh should be specified as a *decision service plus one plugin-installed route per node*, not as a broker that owns transport.** That is a smaller thing than Phase 3 describes, it needs no second daemon, it uses two extension points the harness already provides and documents, and it leaves the one genuinely-missing mechanism — a durable, idempotent, heartbeated job record — as the only thing that has to be invented. On that narrower reading, the cheapest proof of the whole design is one evening: mount `dsh-webhook` on one node behind the tailnet, `POST` it from another, and watch a preset-mounted session appear in the target's session list. **If that POST lands, the mesh's transport problem is solved and Phase 3 is a scheduler; if it does not, the reason will be the bind host or the publication, and both are already solved on `secratary`.**

---

## 5. Method, and what was searched for and not found

**Read in full or in the cited regions (this session, read-only):** `NM/dsh/lib/bin.js`; `NM/dsh-host-webserver/lib/index.js` + `lib/types/injections.d.ts`; `NM/dsh-client-connection/lib/index.js` (788 lines, all) + grep of `lib/client.js`; `NM/dsh-api-gateway/lib/index.js` (1108 lines, all) + three regions of `lib/client.js`; `NM/dsh-web-app/lib/startup.js` (all) + `lib/index.js:92-141` + `cordis.patch.yml` (all 484 lines); `NM/dsh-headless/lib/startup.js` (all) + `lib/index.js` (all 187) + `cordis.patch.yml` (all); `NM/dsh-webhook/lib/index.js:1-160` + README (all); `NM/dsh-webhook-github/lib/index.js` (all 193); `NM/dsh-sdk-protocol/README.md` (all); `NM/dsh-sdk-jsonrpc-server/lib/index.js:1-120`; `NM/dsh-subagent/README.md` (all 192) + `lib/types/types.d.ts:320-377`; `NM/dsh-jobs-local/lib/index.js` (grep); `NM/dsh-api-session-controller/lib/typert.remote-client.js:730-849` + method-line grep + `lib/types/agent.js:360-404` + `lib/types/commands.js` (grep); `NM/dsh-host-open-in-app/lib/index.js` (grep); `NM/dsh/README.md` (grep); `HC/packages/plugin-health/lib/index.js:1-40, 735-804`; `HC/docs/mesh/20-placement.md` (all 859 lines); `HC/docs/mesh/50-transport.md` (all 518).

**Enumerated mechanically:** all 240 directories under `NM/`; all 240 `package.json` files for `name`/`version`/`bin`/`description`; every `cordis.patch.yml` in the tree (6 files: `dsh-acp-app`, `dsh-base`, `dsh-headless`, `dsh-sdk-app`, `dsh-sdk-minimal`, `dsh-web-app`); every package exposing a `bin` (result: **`dsh` and `cordis` only** — no second launcher anywhere under `@deepseek-ai`); all 8 `HC/packages/*` for `webServer.register` / `createServer`.

**Searched for and NOT found — stated as searches, not as proofs of absence:**

- A package, directory or symbol named `remote`, `cluster`, `worker`, `fleet`, `queue`, `lease`, `broker` or `scheduler` **at or above the node level**. Grep `\b(cluster|worker|fleet|broker|scheduler|second engine|remote engine|other node|placement)\b` over **every `.js` in `NM/`** → 379 matches, 250 returned; **every inspected match is in-process** (`worker_thread`, message-queue placement, the agent-loop tool-call scheduler, the client session Map). No match refers to a second machine.
- `webhook` in **any `.yml` in the DSH tree** → **0 matches**. `dsh-webhook` and `dsh-webhook-github` ship but are mounted by no shipped profile (`NM/dsh/README.md:52` confirms the overlays are opt-in).
- A health endpoint in the tree: `HC/packages/plugin-health/lib/index.js:5-13` states it directly — *"There is no health endpoint anywhere in DSH: `GET /healthz` is a static fallback miss and returns 404."* The `/healthz` that exists is the harness's own plugin.
- A durable or cross-process job queue: `NM/dsh-jobs-local/lib/index.js:105` is `new Map()`; the subagent README states the absence of a durable mailbox and cross-process lease as a known limitation (`:175`, `:188`).
- A headless route that can prompt an **existing** session: `--profile headless` takes only `{ task }` and mints a random session id (`NM/dsh-headless/lib/index.js:26`, `:135`); `--profile sdk` creates its own sessions (`NM/dsh-sdk-jsonrpc-server/lib/index.js:47-62`). The only such route is the `/api` Remote surface.

**Not measured (this contract forbade it):** no engine was started, stopped or contacted; no `curl`, no `Invoke-WebRequest`, no ssh. **Every claim above is READ from source or from `HC/docs/mesh/`. The two experiments §3.1 and §3.2 describe were not run** — they are named as the smallest thing that would settle each transport, and the one measured data point that supports §3.1's reachability is already on the record: `HC/docs/mesh/` and journal **H411** note that `ZABZ-TECH`'s engine *"is up and `/healthz` answers **401**"* — a **401, not a connection failure and not a 403**, which is a plugin-registered HTTP route on that node having been reached across the tailnet and refused only for want of a cookie. **That is the transport this document recommends, already answering from another machine.**
