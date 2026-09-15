# The office Mac mini (`LakewooechsMini`) — Yocheved's manager workstation

Her second machine, replacing Weinberg. The Mac mini in the office, user `lpt`. Provisioned **2026-09-14**.

Read this instead of rediscovering it. Every fact says how it was measured.

---

## 1. The machine

| | |
|---|---|
| Host | `LakewooechsMini` (macOS 26.5.2, Darwin 25.5.0) |
| Hardware | **Apple M4**, 16 GB RAM, 228 GB disk (18 GB free) |
| User | `lpt` (uid 501), **in the admin group**, `sudo` without a password |
| Reachable from | `ssh mac-mini-ts` (Tailscale, `100.126.146.121`) |
| FileVault | **On** |

**It has no content filter**, so it reaches `api.deepseek.com` directly — verified `HTTP 200`. There is no
proxy and no Worker here, deliberately: the Cloudflare pass-through exists on her laptop only because
Techloq blocks the direct endpoint there, and carrying that machinery here would add a dependency for
nothing.

## 2. What was installed

| Component | Where | Note |
|---|---|---|
| **Node 24.12.0** | `~/.local/node-v24.12.0-darwin-arm64` | On PATH via `~/.zprofile` and `~/.zshrc`. **Not 22.x** — `bin.js` uses `import.meta.main`, which needs Node ≥ 24.2; on 22.x the CLI exits 0 and prints nothing. Verified in a login shell: `import.meta.main supported: true` |
| **DSH 0.1.5-rc.1** | `~/.dsh-install` | 241 `@deepseek-ai` packages, 289 MB, **18/18 required present**. A plain `npm install @deepseek-ai/dsh` is NOT enough — most mounted plugins are devDependencies, so the list is derived from the shipped `cordis*.yml` compositions |
| **Her persona preset** | `~/.dsh/.agent-presets/yocheved/` | **18,571 chars** — byte-identical size to her laptop's, as it should be |
| **Her settings** | `~/.dsh/settings.yaml` | `provider: deepseek-official`, `model: deepseek-flash`, `agent-presets.default: yocheved`, `permission.defaultPreset: workspace-write` |
| **Credentials** | `~/.dsh/.credentials.yaml` | mode **0600**, `DEEPSEEK_API_KEY` + `DEEPINFRA_API_KEY` |
| `harness-config` | `~/code/harness-config` | 176 files, transferred by tar over SSH (its origin is on `secratary` and is not reachable from here) |
| **Her workspace** | `~/lpt-hub` | The live 3.2 GB working clone — **not** `~/code/lpt-hub`, which does not exist |

**Model route: DeepSeek direct.** Measured from a neutral network, same prompt, `max_tokens=200`, 3 runs:
`deepseek-flash` direct **747 ms TTFT / 160 tok/s**, against DeepInfra at 1,693 ms / 24 tok/s. A real turn
on this machine returned `MAC_OK` in **2 seconds**. `deepinfra` is retained as an independent fallback,
one `agent-provider` line away.

## 3. The engine (persistent, single writer)

`~/Library/LaunchAgents/com.lakewoodphone.yocheved-harness.plist` — `RunAtLoad`, `KeepAlive` on non-zero
exit, working directory `~/lpt-hub`, logging to `~/.dsh/logs/engine.{out,err}.log`.

Verified: after killing every engine, `launchctl kickstart` brought up **exactly one** (pid 58317) on port
3099, and `GET /` answered **401** — which is the healthy answer, because the origin authenticates by
cookie.

**One engine per `DSH_HOME` is a hard rule**: two writers on one home can write duplicate sequence numbers
into a single session log and make the whole history unloadable. Two engines were briefly live here while
provisioning; the ad-hoc ones were killed and launchd's kept.

## 4. What she clicks

**`~/Desktop/Yocheved AI Assistant.app`** — a real app bundle (built with `osacompile`, quarantine flag
cleared) wrapping `~/.dsh/bin/yocheved-assistant.command`, which starts the engine if it is not answering
and then opens her window. A plain `~/Desktop/Yocheved Assistant.command` sits beside it as a visible
fallback.

**Why the token URL on first open:** the origin authenticates by **cookie**, so on a fresh browser profile
`/` answers 401 and the window renders an authentication notice instead of the app — that exact failure
cost hours on the Windows laptop. The launcher therefore opens the **token URL** when the profile has no
cookie yet, and the clean URL from then on (the clean URL is what preserves the window's remembered
session).

**Why the engine check is an HTTP request and not a TCP connect:** a bare TCP connect reported a live
engine for a dead one on the Windows box, which made the whole launcher silently do nothing — a port that
accepts but does not answer is not alive.

## 5. Provenance and credentials

**Repository-scoped deploy key.** `~/.ssh/id_ed25519_lpthub` is registered on **`lpt-hub` only**, with
write access, and `git ls-remote` proves it authenticates as `lakewoodphone/lpt-hub` and nothing else. The
machine's older `~/.ssh/id_ed25519_github` authenticates as the **account-wide** `lakewoodphone` account,
which can push to every repository the owner owns — that key is left in place (other tooling uses it) but
`lpt-hub` is wired to the scoped key, and `~/.ssh/config` carries a `github-lpthub` alias.

**Machine attribution is enforced, not requested.** `~/.githooks/prepare-commit-msg` with
`core.hooksPath` set globally. **Proven firing** on this box:

```
Dsh-Actor: lpt
Dsh-Machine: LakewooechsMini
Dsh-At: 2026-09-14T23:20:32Z
```

Outside the workspace on purpose: a hook she can edit is a convention, not a control.

## 6. Verified working

| Check | Result |
|---|---|
| Direct DeepSeek reachability | `api.deepseek.com/v1/models` → **HTTP 200** |
| A real model turn | **`MAC_OK` in 2 s**, exit 0, on the direct route |
| Composition composes | `--dump-config` **exit 0, 545 lines**, cost plugin present |
| Engine serves | port 3099 listening; `GET /` **401** (needs cookie); with cookie **200 / 27,928 bytes**, `<title>DeepSeek Harness</title>` |
| `lpt-hub` | **current** at `d682882f` (today), 11,742 files, 371 sync-records, 175 cases |
| Admin rights | in the `admin` group, passwordless `sudo`, FileVault on |
| Boot persistence | launchd job loaded and starts exactly one engine |

## 7. Traps hit while building this

1. **Plugin directory ≠ npm package name.** The packages live in `packages/plugin-cost`, `plugin-attention`,
   `plugin-windows`, `plugin-mobile`, and their package names are `dsh-plugin-*`. Symlinking by the npm
   name produces a bundle the engine cannot resolve, and the engine then **refuses to boot at all**.
2. **`set -o pipefail` killed scripts mid-run.** `ssh ... | head -2` makes the pipeline "fail", and with
   `pipefail` the whole script aborts — so a working step looked like a failure.
3. **`~/lpt-hub` was months stale and `origin/main` had moved.** The checkout was at a May commit while
   `origin/main` held today's. `git fetch` needs the scoped key wired via `core.sshCommand`, not just
   present in `~/.ssh`.
4. **`~/code/lpt-hub` did not exist.** The launcher was written to a guessed workspace path; the real repo
   is `~/lpt-hub`. The launcher now points at the repo rather than the repo being duplicated to match a
   guess.

## 8. The two controls beside the composer (cost pill + new window)

Both of the owner's controls are present and working on the Mac:

| Control | What it does | How it is served |
|---|---|---|
| **Cost pill** | session spend in USD in the composer, plus `/cost` | `dsh-plugin-cost` — client **and** host halves linked into the profile |
| **`+` new session** | blank conversation in this window | `dsh-plugin-windows` client half (clears `dsh.sessions.current`, reloads) |
| **`⧉` new window** | same conversation list, its own window | `dsh-plugin-windows` client half → `dsh-new://open` → the macOS handler below |

**`plugin-windows` is not Windows-only in its code.** Reading it settles this: the client half is plain
React that registers into `conversation.input.left`, and the only platform-specific thing in the whole
design is the **OS registration of the `dsh-new://` scheme**. So it was installed unchanged, and macOS got
its own handler rather than a forked plugin.

**The macOS handler:** `~/Applications/DSH New Window.app` — an `osacompile` bundle whose `Info.plist`
declares `CFBundleURLTypes` with scheme `dsh-new` (LaunchServices reads registrations from app bundles, not
from shell scripts) and which is marked `LSUIElement` so it has no Dock icon. Its AppleScript extracts the
action from the URL and runs `~/.dsh/bin/new-window.command`.

**Proven end to end**, by driving the protocol exactly as the control does:

```
$ open dsh-new://open
[21:30:48] === new window requested ===
[21:30:48] profile w1 is fresh -- opening the token URL to set its auth cookie
[21:30:48] opened Google Chrome window w1
[21:30:48] === done ===
```

Each window gets its **own browser profile** (`~/.dsh/browser-profiles/wN`), which is what makes it a
separate window with its own remembered conversation rather than a second tab on the same session, and the
token URL is used only when that profile has no cookie yet.

**The new-window script deliberately refuses to start an engine.** Its first run, while the engine happened
to be mid-restart, logged *"engine is not answering on 3099 -- refusing to start a second one"* and did
nothing — which is correct: two writers on one `DSH_HOME` can corrupt a session log, so the window control
may never be the thing that starts an engine.

**Verified on this box:**

| Check | Result |
|---|---|
| Served bundle ids | `dsh-plugin-cost` **1**, `dsh-plugin-windows` **1** in the page payload |
| Host + client halves linked | `lib/index.js` (25,965 B) and `lib/client.js` (16,646 B) both present |
| Rate card loadable | `pricing.json` parsed: `routes` + `unpriced` sections |
| Session-log reader works | `node:zlib.zstdDecompressSync` available — **yes**, which is what `/cost` needs to read a session log |
| A real turn | `PRICED`, and `session.v3.jsonl.zstd` written under `~/.dsh/sessions/--Users-lpt--/` |

## 9. Open — an owner decision

There is a **second account on this machine**: `moshemontrose` ("Moshe Montrose", uid 502, **not** an
admin, **no password set**, home directory with 11 entries, last console login **Aug 11**). `who` also
still lists him at the console, which is a stale entry rather than an active session.

Nothing was done to it: deleting or disabling a user account is irreversible and it is not mine to
decide, especially in a week where a shop employee is being let go. The question is queued as **#35** in
`owner_decision_queue`.

Note also that this machine was **Yisroel's** (there is a `com.personalsecretary.nodeagent` LaunchAgent and
his Chrome profile under `/Users/moshemontrose`), so it may hold other people's data. That is the same
question.
