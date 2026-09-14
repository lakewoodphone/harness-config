# Yocheved's laptop (`DESKTOP-FGV6KMH`) — access, filter, and assistant setup

Everything needed to work on her machine without rediscovering it. Verified **2026-09-14**; each
fact says how it was measured. Update this file rather than re-deriving it.

---

## 1. Reaching the machine

| Thing | Value |
|---|---|
| Host | `DESKTOP-FGV6KMH` (Windows 11 Home), user `cheve` |
| Exec API | `https://yocheved-cmd.abletelsolutions.com` — `/health`, `/exec`, `/write`, `/read` |
| Auth | Cloudflare Access **service token** (`CF-Access-Client-Id` / `CF-Access-Client-Secret` from `personal-secretary-mvp/.env`) **plus** header `X-Auth-Token: 81c7964f032db5ae` |
| Helper | `personal-secretary-mvp/scripts/yocheved-exec.ps1` — `-Health`, `-Cmd`, `-Script`, `-Write`, `-Read`, `-Raw` |
| Runs as | `nt authority\system` |
| Local port | Exec server `7682`; ttyd web shell `7681` (`YochevedShell` service, also SYSTEM) |

**The "Cloudflare Access blocks the tunnel" entry in `docs/handoff/yocheved-progress/2026-08-25-v31-stable-cloudflare-access.md`
is a FALSE ALARM.** A request *without* the service token correctly lands on the Access login; that is the
security layer working. With the headers it returns `{"host":"DESKTOP-FGV6KMH","ok":true,...}`. Do not act on
that handoff. Verified 2026-09-14.

### Two hard-won operational rules

1. **Never build an inline `&&` / `&` command chain for the exec API.** It cannot be quoted through
   PowerShell → HTTPS → server → cmd, and a local `&` is reinterpreted as a background job by the caller's
   shell. Always upload with `-Script`.
2. **The exec server is single-threaded with a hard 60 s per-command cap** (`taskkill /T /F` on the tree).
   Anything longer returns **HTTP 500** and is killed. Two probes in the 2026-09-14 session died this way.
   A long job must be detached (scheduled task) or split across calls.
3. **Never run credential-requiring git through the exec API.** It runs as SYSTEM, has no GitHub credential,
   hangs on the prompt, and wedges the single-threaded server. This has already happened once.
4. `git` on `C:\Users\cheve\personal-secretary-mvp` fails with **`detected dubious ownership`** because the
   clone is `cheve`-owned while exec is SYSTEM. Not a fault to fix blindly — remember the identity.

---

## 2. What the Techloq filter actually does

**It is a full TLS man-in-the-middle, not a DNS filter.** Verified by certificate inspection from her box:

```
api.deepseek.com    issuer = CN=env1.dc3.us.techloq.com, OU=Cloud Security, O=Techloq Ltd, S=London, C=GB
api.deepinfra.com   issuer = CN=env1.dc3.us.techloq.com, ...   (same)
registry.npmjs.org  issuer = CN=env1.dc3.us.techloq.com, ...   (same)
```

So **every** HTTPS connection is intercepted. TCP 443 is open to everything, which means port checks prove
nothing about reachability of a *service*.

### Block behaviour is the trap

A blocked destination is answered with an HTML page carrying a **success status**:

| Client | `https://api.deepseek.com/v1/models` |
|---|---|
| `Invoke-WebRequest` | HTTP **200**, `text/html`, 2498 bytes |
| `node:https` | HTTP **302**, `text/html` |

A status-code check therefore reports a blocked endpoint as healthy. **Judge by content-type and
parseability, never by status.**

### Measured allow/deny (2026-09-14)

| Destination | Verdict |
|---|---|
| `api.deepseek.com` | **BLOCKED** (HTML block page) |
| `api.deepinfra.com` | **ALLOWED** (real JSON, and a real completion) |
| `registry.npmjs.org` | ALLOWED |
| `github.com` | reachable |
| `cdn.playwright.dev`, `storage.googleapis.com` | category-blocked — see `knowledge/techloq-blocks.md` on her box |

### 🚩 Node TLS: the inheritance trap

Node **fails every TLS handshake** unless it is told to trust the Techloq CA:

```
node, ambient env                        → unable to get local issuer certificate
node, NODE_EXTRA_CA_CERTS set explicitly → 200 application/json
```

`NODE_EXTRA_CA_CERTS` **is** set at Machine scope to `C:\Users\cheve\certs\techloq-ca.pem` (file exists,
1290 bytes) — but a process spawned by the NSSM service **did not inherit it**, because that service started
before the variable existed. **Any launcher on this box must set `NODE_EXTRA_CA_CERTS` explicitly**, and must
set `NODE_OPTIONS=--dns-result-order=ipv4first` because IPv6 is blackholed on her network.

---

## 3. Services and scheduled tasks on the box

| Name | Kind | State (2026-09-14) | Purpose |
|---|---|---|---|
| `YochevedExec` | NSSM service | Running | v3.1 exec API, port 7682 |
| `YochevedShell` | NSSM service | Running | ttyd web terminal, port 7681 (`-p 7681 -a cmd`, SYSTEM) |
| `cloudflared` | service | Running | tunnel, token-based |
| `sshd` | service | Running | port 2222 — **useless: Techloq resets SSH pre-auth even on loopback** |
| `YochevedExecWatchdog` | scheduled task | Ready | restarts the exec service after 2 consecutive health failures |
| `YochevedRepoBackup` | scheduled task | — | git add/commit/push of `C:\Users\cheve\yocheved` |
| `YochevedTtyd` | scheduled task | Ready | keeps ttyd alive |

---

## 4. Her workspace and what is on it

| Path | What |
|---|---|
| `C:\Users\cheve\yocheved` | Her assistant workspace, git → `github.com/lakewoodphone/yocheved` (private), branch `master` |
| `C:\Users\cheve\personal-secretary-mvp` | A clone of the company repo, `cheve`-owned, unusable from exec without `safe.directory` |
| `C:\Users\cheve\node-v22.14.0-win-x64` | Portable Node **v22.14.0** + npm 10.9.2 |
| `C:\Users\cheve\certs\techloq-ca.pem` | Techloq MITM CA (also `.der`, and `verify-node-tls.js`) |
| `C:\Users\cheve\.npm-cache\_npx\*` | Pre-warmed MCP packages (firecrawl, playwright, …) |
| `C:\Users\cheve\AppData\Local\ms-playwright` | Chromium 1234, headless shell, ffmpeg, winldd |
| `C:\Users\cheve\personal-secretary-ai-gateway-0.5.0.vsix` | Her BYOK VS Code extension package |
| **No `lpt-hub` clone and no `C:\Users\cheve\code`** | Her customer-data workspace does not exist yet |

Her repo's `.env` holds 16 keys including `DEEPINFRA_API_KEY`, `GOOGLE_API_KEY`, `QWEN_API_KEY`,
`FIRECRAWL_API_KEY`, `JINA_API_KEY`, `FIREWORKS_API_KEY` and the Cloudflare set.

**Her work went quiet after 2026-08-30** (last artifacts written that day); the VS Code session that began
2026-08-31 stayed open until 2026-09-13 with a broken chat (see §6).

---

## 5. The old VS Code assistant: what broke, and the fix

Measured state at 2026-09-14:

* Only **one** extension installed — `ezabz.personal-secretary-ai-gateway-0.5.0`. The other three the
  handoff says were installed (`ms-vscode.vscode-websearchforcopilot`, `pkief.material-icon-theme`,
  `upstash.context7-mcp`) **are not present**, and the registry manifest confirms only the gateway.
  `extensions.ignoreRecommendations: true`, so VS Code never prompts her to reinstall them.
* The gateway extension is **pinned and stale**: deployed `0.5.0` (56714 bytes) versus `0.5.4` in the repo.
* `~/.vscode/extensions/extensions.json` is a **valid bare array** — the "wrapped registry" bug fixed in
  commit `a61d3fda5` is **not** present here, so that is not her fault line.
* `NODE_EXTRA_CA_CERTS` / `NODE_OPTIONS` set; `techloq-ca.pem` present and correct.

### The failure she actually hit

`renderer.log` for the session that ran 2026-08-31 → 2026-09-13:

```
2026-09-02 10:49:34 … 10:50:10  [error] [CHAT] extension request ERRORED in STREAM
Missing API key for DeepSeek V4 Flash (default). Add DEEPINFRA_API_KEY to the repo .env file and reload.
```
(11 occurrences.)

**The key is not missing.** Her `DEEPINFRA_API_KEY` is byte-identical to the owner's (32 chars, same sha256
prefix), and a live `POST https://api.deepinfra.com/v1/openai/chat/completions` **from her own machine**
returns HTTP 200 with a real completion. The real cause is in the extension:

```js
function repoEnvPath() {
    for (const folder of vscode.workspace.workspaceFolders ?? []) { ... }
    // fallbacks omitted ~/yocheved
}
```

Activation is `onStartupFinished`, which **can fire before workspace folders are restored**, so the lookup
found nothing and the error blamed the key. Upstream had added two fallback locations but **not
`~/yocheved`**, which is where her repo actually is.

**Fix (applied 2026-09-14, in `personal-secretary-mvp/src/vscode-extension/extension.js`):** remember the
last `.env` that yielded a key, honour `PERSONAL_SECRETARY_ENV_PATH`, and add `yocheved` /
`code/yocheved` / `yocheved-staging` to the location list. Also added a
`personalSecretaryGateway.selfTest` command that prints the resolved `.env` path and per-key
presence/length — so the next occurrence is one command, not a log excavation.

**Lesson:** "missing credential" is a claim about a *lookup*, not a value. Print the resolved path.

---

## 6. The DeepSeek Harness migration (design and status)

Full design: `personal-secretary-mvp/docs/engineering/2026-09-14-yocheved-dsh-manager-workstation.md`.

Established facts that shape it:

* DSH runs from an npm package, `@deepseek-ai/dsh` (currently **0.1.5-rc.1**).
* The **host composition is `@deepseek-ai/dsh-base/cordis.patch.yml`** and mounts ~130 plugin rows —
  `llm`, `llm-deepseek`, `llm-pi-ai`, `credentials`, `sandbox`, `sandbox-policy`, `permission`,
  `web`/`web-search-deepseek`, the tool set, goals, subagents, workflow.
  **A plain `npm install @deepseek-ai/dsh` does NOT give a working harness**: most of those packages are
  `devDependencies` of `dsh`, so the install resolves only the ~65 runtime deps. The referenced plugin names
  must be installed explicitly — deriving them from the shipped `cordis*.yml` files is the reliable way.
* **Permission presets** are `read-only` / `workspace-write` / `danger-full-access`, and the base composition
  defaults `sandbox-policy.mode` to `workspace-write` with `workspaceRoot: process.cwd()`; **`base.yaml` in
  `harness-config` overrides `permission.defaultPreset` to `danger-full-access`.**
* **The per-machine settings mechanism already exists**: `harness-config/settings/machines/<HOSTNAME>.yaml`,
  deep-merged over `settings/base.yaml` (machine wins) by `scripts/sync.py`, delivered by
  `scripts/autosync.ps1`. Her file is `settings/machines/DESKTOP-FGV6KMH.yaml` — written 2026-09-14 — and it
  **must** set `workspace-write` explicitly or she inherits full access.
* Her model route is **DeepInfra**, not `deepseek-official`, because DeepSeek's API is blocked (§2).
  Verified capability: all three DeepSeek models on that route return `finish_reason: tool_calls`.
  `DeepSeek-V4-Flash-0731` = 1,048,576 ctx, **$0.06/M in, $0.18/M out, $0.015/M cache-read**.

### Install plan (detached)

`C:\Users\cheve\dsh-setup\install-dsh2.ps1` — npm prefix `C:\Users\cheve\dsh`.
**A scheduled task (`YochevedDshInstall`) is used because the exec server's 60 s cap kills the install.**
A caution learned the hard way: a scheduled task can report `LastTaskResult: 0` while writing nothing, so
**verify by the artifact** (`node_modules/@deepseek-ai/<pkg>/package.json`), never by the task's exit code.

---

## 7. Provenance and safety posture (the requirements)

Her machine is powerful but must not cause breaking changes, and anything from it must be attributable.

| Layer | Mechanism |
|---|---|
| Sandbox | `permission.defaultPreset: workspace-write` in her machine settings (never `danger-full-access`) |
| Git identity | Her GCM currently holds an **account-wide `gho_` OAuth token** (`x-access-token`, 40 chars) — it can push to *every* repo the owner can reach, which would make her commits indistinguishable from his. **Replace with repository-scoped credentials** (read-only to the company repo, read/write to `lpt-hub` only) |
| Attribution | Server-side `prepare-commit-msg` hook with `core.hooksPath` **outside the workspace** appending `Dsh-Actor` / `Dsh-Machine` / `Dsh-Session` / `Dsh-At` trailers |
| Business records | A named field (`source: yocheved-laptop`) in the `lpt-hub` conventions |

---

## 8. Reproducing any of this

```powershell
cd C:\Users\ezabz\code\personal-secretary-mvp
.\scripts\yocheved-exec.ps1 -Health
.\scripts\yocheved-exec.ps1 -Script <probe.ps1> -Raw -TimeoutSec 115
```

Probes used for this file live in `_scratch/yocheved/` on `ZABZ-YOGA`:
`blocktest.ps1` (filter allow/deny), `nodetls.ps1` (Node trust + per-endpoint behaviour),
`toolcall.ps1` (DeepInfra tool-calling), `gitaccess.ps1` (credential scope), `apikey.ps1`,
`usage.ps1`, `envtest.ps1` (replicated `.env` parse), `install-dsh2.ps1` (the installer).

---

## 9. Build status (2026-09-14) — what exists, and what still does not

### Done and verified by artifact

| Item | Evidence |
|---|---|
| Node upgraded to **24.12.0** | `node-upgrade.log` → `installed: v24.12.0`. Old tree kept as `node-v22.14.0-win-x64.bak-v22` (rollback) |
| DSH installed, full plugin set | `C:\Users\cheve\dsh` — `dsh-run.log` → `missing count: 0`, `=== END OK ===`. 240/240 `@deepseek-ai` packages carry their `package.json` |
| DSH CLI functional | `dsh -V` → `0.1.5-rc.1`; `--profile web --dump-config` → 539 lines |
| `web` profile initialised | `C:\Users\cheve\.dsh\profiles\web\` (cordis.yml, cordis.patch.yml, package.json) |
| Credential store | `C:\Users\cheve\.dsh\.credentials.yaml` — 6 refs written **from her own `.env`** (no secret crossed the wire) |
| Settings with her model route | `C:\Users\cheve\.dsh\settings.yaml` — `deepinfra` / `deepseek-ai/DeepSeek-V4-Flash-0731`, `permission.defaultPreset: workspace-write` |
| Engine boots | printed `dsh web: http://127.0.0.1:3099/?token=…` and answered on the port |
| Provenance | commit on her box carried `Dsh-Actor: SYSTEM` / `Dsh-Machine: DESKTOP-FGV6KMH` / `Dsh-At: …` — `RESULT: hook FIRED` |

### Not done — the honest list

1. **Nothing runs persistently.** The engine was started, probed and stopped. It must become an NSSM
   service (the pattern that works on this box) or her box boots with no harness.
2. **No `lpt-hub` clone and no customer-data workspace.** The manager capability is configured but the
   data access the owner asked for is not delivered.
3. **Her Git credential is still the account-wide `gho_` OAuth token.** Until it is replaced with scoped
   credentials, she can push to every repo the owner can reach.
4. **`harness-config` does not reach her box.** Its origin is `secretary-ts:/home/zabz/harness-config.git`,
   not GitHub, so `git clone` fails with "Repository not found". Her settings are currently written
   directly rather than converging via `autosync.ps1`.
5. **No end-to-end turn verified.** The engine serves, but no model completion has been driven through
   her engine yet — the DeepInfra route was proven with a raw API call from her box, not through DSH.

### The two commands that cost the most time, so they are not repeated

* `dsh --help` and `dsh -V` are **not** the checks they look like. `--help` is deliberately disabled
  (`.helpOption(false)`), and only `-V` prints the version. An invocation that exits **0 with empty
  output** means the entry point no-opped — see `journal/LESSONS.md` **L173**.
* **Windows Task Scheduler is inert on this host**: a task reports `LastTaskResult: 0` and runs nothing,
  including a trivial `cmd` marker. Use **NSSM** for any detached work. See **L174**.
  Also: `nssm set <svc> AppExit Default Exit` makes a one-shot service **restart** on clean exit, so
  remove the service when the job is done.

---

## 10. FINAL STATE (2026-09-14) — provisioned and verified

### Working, with the evidence for each

| Item | Evidence |
|---|---|
| **Node 24.12.0** (was 22.14, too old for DSH) | `node --version` → `v24.12.0`; old tree kept as `node-v22.14.0-win-x64.bak-v22` |
| **DSH 0.1.5-rc.1, full plugin set** | `dsh -V` → `0.1.5-rc.1`; 240/240 `@deepseek-ai` packages carry a `package.json`; 17/17 required packages present |
| **`web` profile boots clean** | engine starts, prints its token URL, **zero stderr**, port 3099 listening, shell returns **200 (28,297 bytes)** |
| **Client plugins served to her browser** | served shell references `plugin-cost`, `plugin-windows`, `plugin-attention`, `plugin-mobile` — this *is* the cost pill and the new-window `+` |
| **Model route** | `settings.yaml` → `deepinfra` / `deepseek-ai/DeepSeek-V4-Flash-0731`; the route itself was proven with real tool-calls from this machine (3/3 models, `finish_reason: tool_calls`) |
| **Her persona** | `~/.dsh/.agent-presets/yocheved/` (18,571 chars), `agent-presets.default: yocheved` |
| **Sandbox posture** | `permission.defaultPreset: workspace-write` (never `danger-full-access`) |
| **Customer data** | `C:\Users\cheve\code\lpt-hub` — 11,740 tracked files, HEAD `af119319`, `docs/customer-operations` present |
| **Second repo** | `C:\Users\cheve\code\personal-secretary-mvp` cloned |
| **Scoped credentials** | deploy key `id_ed25519_lpthub` authenticates as **`lakewoodphone/lpt-hub` only** — proven by `ssh -T` |
| **Provenance** | `bootstrap.ps1` → `RESULT: hook FIRED`, commit carried `Dsh-Actor` / `Dsh-Machine: DESKTOP-FGV6KMH` / `Dsh-At` |
| **Execution policy** | was effectively Restricted (what she hit); now `RemoteSigned` at CurrentUser **and** LocalMachine, and a fresh shell runs a `.ps1` with no `Bypass` → `NOPOLICY_OK` |
| **Desktop shortcut** | `Yocheved AI Assistant.lnk` on both `Desktop` and `OneDrive\Desktop`, targeting `cmd.exe /c` on her machine-specific launcher with the RunAs-user flag set, so it raises the UAC prompt |
| **`+` new-window button** | `dsh-new://` protocol registered per machine |
| **config sync without Python** | `scripts/sync.ps1` + `scripts/merge-settings.mjs`; ran to convergence on her box |

### Bugs in MY OWN tooling, found and fixed — keep these in mind

1. **`sync.ps1` destroyed a YAML list and duplicated a key.** A hand-rolled PowerShell YAML parser
   emitted `llm-pi-ai.models` as a map instead of a list, and the block appeared **twice**; the engine
   then refused to boot with `DUPLICATE_KEY at line 21`. **`dsh --dump-config` did not catch it**,
   because dumping the composed profile never reads the user's settings document — a green dump is
   not evidence the engine can start. Fixed by delegating the merge to `scripts/merge-settings.mjs`,
   which uses the harness's own `yaml` package and **re-parses its own output** before writing.
2. **`merge-settings.mjs` first resolved the wrong `yaml`.** A bare `require('yaml')` found a package
   with no `parse` → `YAML.parse is not a function`. It correctly refused to write. Now it probes
   candidate `node_modules` directories (DSH install, profile, npx cache) and validates the import by
   shape before using it.
3. **`sync.ps1` called `pwsh`, which is not on SYSTEM's PATH.** The exec server runs as SYSTEM, so the
   settings merge silently never ran and her box kept the broken file. Call PowerShell 7 by absolute
   path; a `C:\ProgramData\dsh-shims\pwsh.cmd` shim is now on Machine PATH.
4. **A one-shot NSSM service with `AppExit Default Exit` restarts on clean exit**, so it re-ran and
   deleted a *finished* 2 GB clone on its last loop. Make such scripts idempotent, and remove the
   service when the job is done.

### Still open

1. **Nothing starts the engine automatically yet.** The desktop shortcut is the intended path
   (`dshw ensure` → `dshw restore`), and it is written but was not clicked by a human.
2. **`harness-config` does not reach her box from git.** Its origin is
   `secretary-ts:/home/zabz/harness-config.git`; the files were transferred directly and
   `HARNESS_CONFIG_COMMIT.txt` records the commit they came from. Until a transport exists, `autosync`
   cannot converge her machine — re-run a transfer instead.
3. Her code-changing work should stay outside the default workspace (`lpt-hub`) so a mistake cannot
   reach the machine's own harness configuration; the other repos remain readable and usable.

### 11. The acceptance test, stated exactly

**A real model completion through her engine PASSED:**

```powershell
# on her box, with NODE_EXTRA_CA_CERTS + NODE_OPTIONS + DSH_HOME set
node <dsh>\lib\bin.js --profile headless 'Reply with exactly this and nothing else: MANAGER_READY'
# -> exit 0, 7 seconds, output: MANAGER_READY
```

That single result proves the whole chain at once: the Techloq filter is traversed, Node trusts the
interception CA, the `deepinfra` route is selected, `DEEPINFRA_API_KEY` resolves from the credential
store, and the model answers. Every earlier blocker in this file is downstream of that one fact.

**What is NOT yet proven, and must not be claimed:**

* **Her persona has NOT been shown reaching the model.** Two attempts hit the wrong surface and I did
  not substitute a weaker check for the real one:
  - `--profile headless` carries its **own** inline persona (`personaPrefix: You are a coding agent…`)
    and does not consult the `.agent-presets` roster at all, so it can prove the model path and cannot
    prove the preset. That is exactly the trap this file's own §10 warns about in another form: a green
    result on a surface that does not exercise the thing under test.
  - Passing her preset as a `--patch` layer composes cleanly (exit 0, 564 lines, every row resolving)
    but does **not** replace the `persona` row in the dumped tree, because presets are mounted by the
    agent-preset machinery after the profile is composed. A clean composition is evidence the preset is
    *valid*, not that it *lands*.
* Her preset is nonetheless registered exactly as the preset mechanism documents: the files are at
  `~/.dsh/.agent-presets/yocheved/`, `USER_PRESET_DIR = ".agent-presets"` and
  `COMPOSITION_FILE = "agent.cordis.yml"` match, and `settings.yaml` sets `agent-presets.default: yocheved`.

**The one check that would settle it:** open the desktop shortcut and ask her assistant what its job is.
If it answers as the Lakewood Phone & Tech shop manager rather than a coding agent, the preset landed.


