# DSH on the phone, and DSH sessions in the secretary — design and ordered plan

Read `00-RESEARCH.md` first; every decision here rests on a fact recorded there with its evidence.
This document is the ordered build. Each phase ships something runnable and independently testable, and
each names its acceptance test. Nothing here depends on a later phase.

**Owner's ask → deliverables**

| His words | Deliverable | State |
|---|---|---|
| "the yoga and desktop have to stay in sync … properly" | Unattended sync on both machines, verified, never destructive | **built and installed 2026-09-11** (Phase 1) |
| "the same script that takes the VS code copilot chat sessions and always brings them to the secretary … Should do the same for the DSH harness" | Every DSH session from every machine shipped into the authoritative store, with its events, searchable, idempotent | designed (Phase 3) |
| "adapt that to be able to speak to the DSH harness through my iphone app" | The phone reaches the real harness agent: full toolbelt, persisted sessions, the same `zabz` | designed, path **proven by experiment** (Phase 2) |
| "we'll be the same you and the chat sessions will be saved and have all the tools" | Same preset everywhere; sessions archived centrally | Phases 2 + 3 |

---

## The one architectural rule that shapes everything

> **Only the web profile has the full agent.** `agent-presets` is not mounted by the headless, SDK or ACP
> profiles, and there is no CLI flag to select a preset for them (`00-RESEARCH.md` §5). So the phone must
> reach a **`dsh web` engine** — anything else is a weaker agent with the same name.

And from the same section: the engine is **loopback-only by design**, with
`--host 0.0.0.0` refused *because it would expose remote code execution to the network*. The supported way
in is a **loopback-side reverse proxy that preserves `Host`, plus `--trusted-host <that authority>`** —
verified working in six probes (`00-RESEARCH.md` §2).

---

## Phase 1 — Unattended, non-destructive sync between the workstations ✅ **DONE**

**Shipped:** `harness-config/scripts/autosync.ps1` (worker) + `scripts/Install-Autosync.ps1` (registers
`PersonalSecretary-HarnessSync`: at logon, every 15 minutes, interactive user, `runLevel: Limited`).
Commits `c7faeb4`, `e57230d`.

**Design invariants** (each one a lesson already paid for):

- never commits, never merges/rebase, never stash/reset/clean/force-push (this business has lost data twice);
- the **pull** is attempted even when tracked files are modified, because `git pull --ff-only` refuses by
  itself to overwrite local modifications — git is the safety, not a heuristic of mine;
- the **apply** to `~/.dsh` is **skipped** while tracked files are modified, so a half-written preset can
  never be published into the live config; `~/.dsh` stays on the last good state and self-corrects;
- the apply is **verified** by a second `--dry-run`: `WOULD CHANGE` means it did not converge → reported as
  *attention*, never as success;
- divergence is reported, never resolved by guesswork;
- commits already made but never pushed are sent (fast-forward only);
- every run writes `%LOCALAPPDATA%\harness-config-autosync\status.json` + `autosync.log`, so drift is
  visible instead of silent (`-Status` prints the record).

**Verified:** clean path end-to-end in a throwaway clone with a throwaway `DSH_HOME`
(`{"result":"clean","converged":true}`, exit 0, settings + both presets applied); both tasks registered and
fired (ZABZ-TECH result 0 / `clean`; ZABZ-YOGA fired and honestly reported `dirty` because another session
had a tracked file open).

**Acceptance test (met):** after a change is committed and pushed from either machine, the other machine's
`~/.dsh` matches within 15 minutes without anyone running anything — or the status record says exactly why
it did not.

**Residual gap, stated rather than hidden:** on a machine where several sessions keep files modified, the
apply can be deferred indefinitely. The status record makes that visible; nothing yet pages anyone about it.
Folding that record into the CEO kernel's sentinel is the natural next step (Phase 5).

---

## Phase 2 — The phone reaches the real harness

### 2a. Transport: Tailscale Serve in front of loopback

**Prerequisite — one owner action, verified 2026-09-11.** Serve is a tailnet-level feature and is
**not enabled on this tailnet**. `tailscale serve --bg 3099` answers:

> `Serve is not enabled on your tailnet. To enable, visit: https://login.tailscale.com/f/serve?node=<nodeid>`

That link is account-scoped, so **only the owner can click it**; no CLI can enable it. Everything else in
Phase 2a is already proven, so this single click unblocks the phase. Until it is enabled, the same design
still works through an SSH tunnel for manual testing, but not for a phone. The design was otherwise
verified end to end with `Host`-header probes and, before that, six authenticated `curl` probes
(`00-RESEARCH.md` §2).

```
iPhone  ──Tailscale──▶  https://<host>.<tailnet>.ts.net   (Tailscale Serve, TLS)
                              │  preserves Host
                              ▼
                        http://127.0.0.1:3080            (dsh web, loopback only)
                        started with --trusted-host <host>.<tailnet>.ts.net
```

Why Serve and not the alternatives: it is the only option with **valid HTTPS, tailnet-only, no public
exposure, no domain to buy**, and it emits identity headers (`00-RESEARCH.md` §9). Funnel is public by
design *and* drops those headers. Cloudflare Tunnel needs a domain plus a second auth layer, and is how the
existing phone app is exposed today.

**Bootstrap:** the engine prints one tokenized URL at startup. Reached through the proxy with the tailnet
`Host`, that URL **303s and mints a cookie bound to the tailnet authority** (probe 1) which then authenticates
every API and WebSocket call (probe 3) for 30 days. It is useless on any other authority (probe 6).

**Where it runs first:** the workstation, as a proof, because it needs no new install — the plumbing will be
`harness-config`-managed and identical on both machines. **End state: `secratary`**, the always-on host, so
the phone works when the workstations are asleep (Phase 4).

### 2b. The experience: the harness's own UI first, then fix what the phone hates

The harness already serves a **PWA manifest** (`/manifest.webmanifest` → 200), so the phone can install it
to the home screen. It already has reconnect/retry with jittered backoff, session management, tool
approval, and a trajectory view. Writing a parallel chat UI would mean reimplementing all of that, worse.

So the order is deliberate: **prove the real UI on the phone first, then fix its mobile ergonomics with a
client-side plugin** — the harness supports client plugins, and this repo already carries one
(`packages/plugin-cost`, built hours ago by another session, which is the proof the pattern works here).

Candidate fixes, to be chosen from what the device actually shows: composer hidden by the keyboard
(`window.visualViewport`), `100dvh` instead of `100vh`, `env(safe-area-inset-*)`, tap-target sizing, and a
session switcher reachable one-handed. These ship from `harness-config` so both machines get them.

**Rejected for now, and why:** rebuilding the existing `/phone` PWA as a custom client of the harness RPC.
It is *possible* — `session/list`, `session/create`, `session/prompt`, `session/follow{assistantStream}`,
`session/page` cover the whole need (`00-RESEARCH.md` §3), and a third-party bridge proves it is done in the
wild — but it means hand-writing cookie custody, WebSocket relay semantics, journal gap repair and
reconnect bookkeeping, to arrive at less than the shipped UI already does. **It stays the fallback if the
harness UI turns out to be genuinely unusable one-handed on a phone**, and its transport would then be
`fetch`-streaming or WebSocket, never `EventSource` (§9: iOS kills background connections in ~5 s).

### 2c. Acceptance test

From the phone, **not** from a workstation: open the tailnet URL, complete the token exchange once, add to
home screen, start a new chat, ask a question that *requires a tool* (e.g. "what did the company do in the
last hour" — which must hit the secretary MCP bridge), and see the tool call and its result in the
transcript. Then confirm the session appears in `~/.dsh/sessions` on the engine's host — which is what makes
it archivable by Phase 3.

**And the answer has to be RIGHT, not merely tool-shaped.** The first end-to-end run through the tailnet
(2026-09-11) called the bridge three times, answered fluently, and was **wrong** — because the bridge on a
workstation reads a **local replica** of the database. See Phase 2.5, which is the real gate: "the tool was
called" is not an acceptance test.

### 2d. Risks, stated plainly

- **This exposes an RCE-capable agent to anything holding that cookie.** Mitigations: tailnet-only, no public
  exposure, cookie authority-bound and `HttpOnly`, Tailscale device identity as the outer layer, and one
  device. It is still a real capability — it has to be, since the point is to give the phone the full agent.
- A tailnet ACL that does not grant tcp/443 makes Serve **time out silently** — the failure looks like a
  dead server. Check the grant first if the URL does not answer.
- The engine's startup token is in its log; treat that log as a secret.

---

## Phase 2.5 — The bridge must read the authority, not a copy (found by the phone work)

**Found by verifying an answer instead of admiring a successful call.** The first tailnet run created a
session (`agentPreset: zabz`), mounted all six MCP bridges, called `mcp__secretary__ps_db_query` three times,
and reported:

> "13 ticks today … nothing logged between 08-21 and 09-10, so 13 is likely an undercount"

The authoritative database says **197 ticks today** and **no gaps**. The replica the bridge actually read says
**13 today, 93 yesterday, then a jump to 08-21** — the agent's answer, exactly.

**Cause.** `personal-secretary-mvp/scripts/ps_mcp_server.py:65` — `DB_PATH = ROOT / "data" / "secretary.db"`.
On a workstation that is `…\personal-secretary-mvp\data\secretary.db`: **173 tables**, last written 00:57
today, against the authority's **203 tables**. This is PAIN P3 — *reading the wrong data and believing it* —
reappearing at a new layer. The kernel already refuses this exact file as *"structurally old"*. **The bridge
has no such check**, and the model, finding an artefact, invented a plausible explanation for it ("telemetry
has been down for about three weeks") rather than doubting its source.

**Why it is urgent:** every workstation session *and* every phone session gets the same wrong answers about
the company, stated confidently. That is the most expensive failure class in this system's history (L1/L2,
P3), and the phone makes it reachable from his pocket.

**Fix, in order of preference:**

1. **Run the bridge on the authority.** The preset row becomes a stdio command that runs `ps_mcp_server.py`
   on `secratary` over SSH, so there is one copy and it is the real one (L13).
2. **Gate on provenance.** Port the kernel's rule into the bridge: a reading whose source is structurally
   old, or whose age cannot be established, is **refused** rather than returned.
3. **Label, never silently.** If a replica must be read, every packet says which file, which host and how
   old — exactly as `ck` already does.

Do 1 and 2. 3 alone is insufficient, because the failure is *confident wrongness*, not missing metadata.

**Acceptance test:** from the phone, ask for today's tick count and get either the authoritative number or an
explicit refusal — never a plausible number from a stale file.

### Built and verified, 2026-09-11 17:55

The `mcp-secretary` row in the `zabz` preset now runs the bridge **on the authority**, over SSH stdio, and
the Windows-only gate is gone (so Linux hosts get it too). Row shape:

```
command: ssh
args: -T -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=10
      -o ServerAliveInterval=30 -o ServerAliveCountMax=3
      secretary-ts /home/zabz/personal-secretary-mvp/.venv/bin/python
      /home/zabz/personal-secretary-mvp/scripts/ps_mcp_server.py
```

`-T` so nothing but JSON-RPC reaches stdout, `BatchMode` so it can never sit at a password prompt, and
keepalives so a long session does not hang on a dropped network.

**Verified in four steps, each against the real thing:**

| Step | Result |
|---|---|
| Authority can host it | `ps_mcp_server.py` present; venv `mcp` imports; `.env` present; local API `200`; DB is the 2.4 GB authority |
| Raw SSH stdio handshake | `initialize` → `serverInfo personal-secretary 1.27.0`, protocol `2025-11-25`, **14 tools**, and `ps_db_query` for today's ticks → **197** |
| Preset mounts it | a new session on the phone engine spawned `ssh.exe … secretary-ts …ps_mcp_server.py` as its bridge |
| **Same question, same path** | the phone-path session answered **"197 ticks today (2026-09-11 UTC) — read from `tick_telemetry` on secratary's authoritative DB at 17:56 UTC, newest tick started 17:50 UTC, so the count is current as of ~6 minutes ago."** |

That last line is the whole point: the number is the authority's, the provenance is stated, the freshness is
stated, and the agent verified the database's clock before answering. Before the change, the same question
produced *"13 ticks today … telemetry has been down for about three weeks"* — confidently wrong, from a
173-table replica.

**One tool changes meaning here, recorded rather than glossed:** `ps_open_loops` mines *local* VS Code
conversations. On the authority there are none, so it returns nothing. It is a VS Code-era tool; expect
nothing rather than something wrong.

---

## Phase 3 — Every DSH session traced into the secretary

**The contract mirrors the proven Copilot pipeline** (`00-RESEARCH.md` §7) with a purpose-built endpoint and
tables, because DSH sessions are seq-ordered events with assistant and tool content, a preset and a project
slug — reusing `vscode_chat_*` would be a semantic lie and would pollute the existing search.

**Client** (each machine, one Node shipper `scripts/push-dsh-sessions.mjs` in `harness-config`, launched by a
`PersonalSecretary-PushDSHSessions` scheduled task, hourly — the same idiom as the Copilot pusher):

| Concern | Decision |
|---|---|
| Decoding | **Rows are shipped verbatim** — see "Built and verified" below. The upstream research recommended `decodeStorageRecord`, but **that function does not exist in the installed build**: the persistence package exports only its Cordis plugin, and `zstd`/`scanLog` helpers live in bundles the package does not expose. Interpreting the format here would be a confident guess about a format we do not own (P22, L51) |
| Frame reading | the three byte-level traps *are* handled, because they are about bytes rather than meaning: every zstd frame is decoded in order (a one-shot decompress reads only the first), a torn final frame is skipped and reported, and the headless profile's uncompressed `.jsonl` is read as-is |
| Cursor | `(rowsShipped, bytes)` per session in `~/.dsh/dsh-archive-state.json` — never a wall-clock cursor. Whole-file re-read per run is deliberate: sessions are small, and re-reading is cheaper than getting byte-offset arithmetic wrong |
| Delivery | at-least-once + **upsert on `(machine, session_id, ordinal)`**. A durable row's ordinal never moves because the journal is append-only, so re-delivery is free; exactly-once is not attempted |
| Payload | plain JSON; ≤100 sessions / ≤4 MB per batch |
| Failure | the cursor advances **only after the batch containing it was accepted** — advancing early is how a shipper silently loses data it believes it sent |

**Server** — and here the plan met reality, so the deviation is recorded rather than papered over.
The intended home is in-app: `POST /api/v1/owner/dsh-sessions/ingest` →
`app/services/dsh_session_ingest.py` → `dsh_session_exports`, `dsh_sessions`, `dsh_session_events` + FTS5 in
the authoritative `secretary.db`. **That module and route are written, committed (`92b82c351`) and NOT
deployed**, because the authority's checkout of `personal-secretary-mvp` is **51 commits behind origin with
nine uncommitted local modifications, including `app/main.py`** — so deploying means either merging on a
running company or hand-patching that deepens the drift. Neither is acceptable for a feature nobody is
waiting on tonight.

What runs instead: `scripts/dsh-archive-import.py`, the same tables and semantics in its own SQLite database
on the authority (`/home/zabz/dsh-archive/dsh-archive.db`), invoked over SSH by the shipper. When the
company checkout is reconciled the tables move into `secretary.db`, and the importer doubles as the test
harness for that move.

### Built and verified, 2026-09-11 18:10

| Step | Result |
|---|---|
| Importer alone | import → `sessions_created: 1`; **same batch again → `sessions_unchanged: 1`, `sessions_reindexed: 0`**; `--stats` correct; `--search` finds text that only existed in the payload |
| Real run, ZABZ-YOGA | **42 sessions, 16,466 rows, 73 MB** in 186 s |
| Second run (idempotence) | 1 session (one being written live), 5 new rows, 41 skipped by cursor, 3 s — and the authority's event count moved **exactly +5, 16,468 → 16,473**. Nothing duplicated |
| Archive state | 43 sessions / 16,473 events / **16,473 indexed rows**, searchable |
| Scheduled | `PersonalSecretary-PushDSHSessions` hourly at logon on **both** workstations — same idiom as `PersonalSecretary-PushVSCodeChats` |

**A transport defect found and fixed while doing this, worth knowing:** the desktop's first run hung for ten
minutes having shipped nothing. Node-spawned ssh does not reliably exit after the remote command completes
when a large payload is fed on stdin — my first reading blamed the desktop, and the Yoga then showed the same
behaviour on 5 of its batches. The shipper now kills the child the moment the importer's reply parses (the
reply is printed only after `conn.commit()`, so it means the rows are durable), with a 240 s hard timeout as
the outer bound. That is the difference between an hourly run taking seconds and taking eight minutes.

**Explicitly not repeated from the old pipeline:** the `--days 1` window that silently loses anything missed
for a day; the 50 MB skip that hides large sessions; storing only user messages.

### Resolved, 2026-09-11 19:40 — the archive is in the authoritative store

The endpoint went live, additively, without deploying the 55 stale commits: the service module was taken
from `origin/master` and the auth helper + three routes were **appended** to the production `main.py` (one
insertion point instead of two anchor matches inside someone else's 735 KB file, with the original backed
up first and `py_compile` as the gate). The owner's answer to the deployment question was *"you are in
charge, this is your decision"*, so the smallest reversible change was taken, and the 55-commit
reconciliation stays a separate decision.

| Layer | Verified |
|---|---|
| route | `401` without a token, `200` with — on loopback **and** on the public URL |
| tokens | its own name, `DSH_SESSION_INGEST_TOKEN`, issued on the authority and placed in each machine's `.env` (never in a task argument, where any process could read it — L44) |
| backfill | all three machines re-shipped: **83 sessions, 19,866 stored rows, all indexed**, and a search for `ticks_today` returns the phone engine's own *"200 ticks today (Sep 11, through 18:54…"* answer |
| schedule | both Windows tasks unchanged (the default transport is now `http`); the authority's cron runs `--transport http` against **loopback** |
| kernel | `session_archive` follows the data into `authoritative` and reports *"83 session(s) / 19,866 event(s) from 3 machine(s); newest 72s ago"* |

**Four defects found by running it, none by reading it:**

1. **`database is locked`, four times** (`error_log` 809–812), and `busy_timeout` did **not** fix it. The
   cause was the *transaction shape*: Python's `sqlite3` opens a deferred transaction on the `SELECT` that
   checks whether a session changed, and the following `INSERT` has to upgrade a read transaction to a write
   one — which fails with `SQLITE_BUSY` **immediately** if any other connection committed in between.
   Waiting cannot make a stale snapshot current. Committing after the read fixes it properly. The diagnosis
   came from the gap between two measurements: an independent writer got the lock in **0.01 s** when the
   database was calm, yet the ingest failed under load, so the lock was never held long.
2. **One 2,384-row, 10 MB session** could not finish inside a single HTTP deadline → the shipper now sends
   **300 rows per request** (the protocol already carried `start_row`, so nothing new was needed), and the
   cursor advances only with a session's *last* fragment so an interrupted session is re-sent whole.
3. **A backfill stampede** — a hundred inserts back to back while the company writes continuously; the WAL
   sat at exactly its 64 MiB limit, the signature of checkpoint starvation. Now paced at 250 ms, with one
   retry after a 5xx, because a batch that throws is a batch the cursor refuses to skip.
4. **An ambiguous statistic of my own**: the per-machine event figure summed each session's *declared* row
   count (including rows not yet shipped from live sessions) and read 31,251 against 19,866 stored rows. It
   now counts what is actually stored. Two numbers claiming to count the same thing and disagreeing are
   worse than one number.

The standalone archive at `/home/zabz/dsh-archive/dsh-archive.db` is left in place as a **frozen copy** of
what shipped before the endpoint existed. Nothing is deleted.

**Explicitly not repeated from the old pipeline:** the `--days 1` window that silently loses anything missed
for a day; the 50 MB skip that hides large sessions; storing only user messages.

**Deliberately not done:** routing sessions to Project Hub projects. The Copilot ingest auto-creates a project
when nothing matches, and DSH sessions are scoped by a raw cwd slug — that would sprinkle junk projects into
the owner's hub before anyone decided the mapping. `cwd` is stored instead; the link can be added
deliberately later.

---

## Phase 4 — Move the phone's engine to the always-on host

**This was sequenced last for convenience. A live failure has since made it the fix, not an optimisation.**
See PAIN P23: with the (correct) bridge running on the authority over SSH stdio, a transient Tailscale
outage turned it into a respawn cycle — every ~30 s a new SSH session and a new `ps_mcp_server.py` process
**on the company's authoritative host**. Bounded (the client backs off to 30 s and stops after ten failures)
and self-healing, but load on the company host caused by a client outside it, recurring whenever a
workstation is on a flaky network.

→ Run the engine **on `secratary`**, where the bridge is a **local stdio child** with no network hop at all.
The only network element left is the phone's connection to the engine, and if that drops nothing is spawned
on the host.

**And change the workstation bridge to Streamable HTTP** rather than ssh stdio: `dsh-mcp-client` supports it,
and its documented behaviour is the discriminator — *"an unreachable HTTP server is retried per call rather
than respawned by the supervisor"*. An outage then costs failed calls instead of processes. That needs the
MCP server to serve HTTP (FastMCP supports it) and a small always-on unit beside the API.

The phone should not depend on a laptop being awake. `secratary` already runs Node 20, Python 3.14, the
secretary API (loopback-fast MCP bridge) — and it is where the archive coordinator lives.

Work required, and it is not free: install DSH there; give it a Linux autosync (the same
`autosync`/`sync.py` contract, cron instead of Task Scheduler); add the Linux variant of the secretary MCP
row in the `zabz` preset (the current row is gated `disabled: !!js process.platform !== 'win32'`, so Linux
gets no secretary bridge today — the preset needs a per-platform path, which is what
`settings/machines/*.yaml` exists for); then Serve + `--trusted-host` on that box.

**Acceptance test:** with both workstations shut down, the phone still opens the harness, runs a tool that
touches the secretary, and the session is archived.

### Built and verified, 2026-09-11 19:10

| Step | Result |
|---|---|
| The harness runs there at all | **Node 20 fails silently** — no output, no listen. `commander` needs ≥22.12 and `undici` ≥22.19. Installed a user-owned **Node 22.23.2** at `/home/zabz/node` (no sudo, no system change) |
| Config discipline on that host | `scripts/autosync.sh` — the Linux twin of `autosync.ps1` — run from cron every 15 min. First run: `settings.yaml` written, both presets applied, `agent-presets.default: zabz` |
| The bridge is local | the engine's first session spawned `ps_mcp_server.py` as a **direct child of the engine**; **0** bridges parented to a remote ssh session on that host |
| The endpoint | `serve-phone.sh` → `https://secratary.tail93e6e6.ts.net/` → `127.0.0.1:3086`, verified with `tailscale serve status` |
| **The answer** | *"**200 ticks today (Sep 11, through 18:54 UTC), read from `/home/zabz/personal-secretary-mvp/data/secretary.db`** — via `ps_db_query` on `tick_telemetry` … and independently confirmed by a read-only `sqlite3` count on that same file"* |
| The laptop is out of the path | the Yoga's Serve config cleared and its phone engine stopped. One canonical URL, on the always-on host |
| The phone's own sessions are archived | a new `local` transport (write beside the importer, import in place — no ssh to itself). Archive now covers **three** machines |

**Survival:** `@reboot` + a 10-minute watchdog in cron, both idempotent, plus the shipper every 30 minutes
with `--transport local`.

**A fleet-wide credential problem found on the way, worth more than the phase itself.** The harness on the
authority failed every model call with `Authentication Fails`. The cause was not the code: the fleet holds
**three different `DEEPSEEK_API_KEY` values** — fingerprints `1b6e…` (the harness store that works),
`f097…` (the Yoga's repo `.env`), `646b…` (the authority's repo `.env`). Tested against the API:
**the authority's `.env` key returns 401** and the harness-store key returns 200. So a credential had
quietly forked exactly like the databases of PAIN P3, and the copy on the always-on host is invalid —
anything there reading `DEEPSEEK_API_KEY` from `.env` is broken and silent about it. The working key was
installed from the harness's own store, fingerprinted before and after, value never printed.

**Fixed while deploying, all found by running it:** `tailscale serve` needs root on Linux (the first
version of the script printed a working-looking phone link anyway — it now refuses); a hand `chmod +x` on
one host became a "local modification" that blocked its `git pull` (the exec bit now lives in git, the same
class as the CRLF lesson); and the new `local` transport called `spawnSync` after the transport helper had
moved to async `spawn`.

---

## Phase 5 — Make drift and silence visible to the kernel

The sync status record, the archive's freshness, and the Serve endpoint's liveness are all things the
`ceo-kernel` sentinel can watch — and *absence* is exactly what it was built for (a missed archive is
silence, not an error). Small, and it reuses the machinery that already exists rather than adding a
monitor.

---

## Open questions, and which are the owner's

| Question | Whose | Status |
|---|---|---|
| Phone exposure: Tailscale-only, or a public login-gated endpoint? | **His** — already in `QUESTIONS.md` | **Now answered by the design as far as it can be**: the plan uses Tailscale-only, which is his stated lean and the recommendation already recorded. Nothing blocks on it |
| Voice input on the phone | **His** (`05-question-register.md:353` Q15) | open; the harness UI has no dictation and the old `/phone` app has none either. Not in scope unless he wants it |
| Should the phone's engine live on `secratary` (Phase 4)? | Mine, with a visible cost | decided: yes eventually; it is sequenced last because it needs an install, and the workstation proof comes first |

## What is deliberately **not** being built

- A second, weaker agent surface over the SDK/ACP stdio profiles — it would lose `zabz`, the toolbelt, the
  persona and the MCP bridges.
- A patched `--host 0.0.0.0` — it discards a deliberate RCE guarantee to avoid writing a correct proxy.
- A hand-rolled session decoder — the official one exists and the format has three ways to lose data quietly.
- A new chat UI, until the phone has shown that the shipped one cannot be fixed cheaply.
- Any change to the owner's exposure without him: the plan is tailnet-only, and that is reversible.
