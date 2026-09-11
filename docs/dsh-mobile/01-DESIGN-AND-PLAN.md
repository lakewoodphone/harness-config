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

---

## Phase 3 — Every DSH session traced into the secretary

**The contract mirrors the proven Copilot pipeline** (`00-RESEARCH.md` §7) with a purpose-built endpoint and
tables, because DSH sessions are seq-ordered events with assistant and tool content, a preset and a project
slug — reusing `vscode_chat_*` would be a semantic lie and would pollute the existing search.

**Client** (each machine, one Node shipper `scripts/push-dsh-sessions.mjs` in `harness-config`, launched by a
`PersonalSecretary-PushDSHSessions` scheduled task, hourly — the same idiom as the Copilot pusher):

| Concern | Decision |
|---|---|
| Decoding | **`decodeStorageRecord` from `@deepseek-ai/dsh-session`** — never hand-rolled. Three silent-data-loss traps are documented in §4: one-shot zstd reads only the first frame; packed rows carry `seq0` not `seq`; a torn final frame is a normal crash boundary |
| Cursor | `(machine, project, session, last_seq)` in a persisted state file — **per-session monotonic seq, never a wall-clock cursor** (§9). Whole-file re-decode per run is deliberate: sessions are ~183 KB, and re-reading is cheaper than getting byte-offset arithmetic wrong |
| Delivery | at-least-once + **upsert on `(machine, session, seq)`**. Re-delivery is free; exactly-once is not attempted |
| Payload | plain JSON (the server has no transport compression — that is the client's job); ≤100 sessions / ≤4 MB per batch |
| Auth | a distinct token header, server-side `hmac.compare_digest`, mirroring `x-ps-vscode-chat-ingest-token` |
| Failure | the state file is written **only if zero errors** — the existing pipeline's rule, kept |

**Server** (`personal-secretary-mvp`): `POST /api/v1/owner/dsh-sessions/ingest` →
`app/services/dsh_session_ingest.py` → `dsh_session_exports`, `dsh_sessions`, `dsh_session_events` + an FTS5
table, in the authoritative `secretary.db`. Idempotent by upsert; messages are reinserted per session like
the existing ingest does.

**Acceptance test:** a session started on each workstation — including one from the phone — appears in
`secretary.db` within the hour with its events intact and searchable via FTS; running the shipper twice
changes nothing (idempotence proven by row counts and by the second run's exit).

**Explicitly not repeated from the old pipeline:** the `--days 1` window that silently loses anything missed
for a day; the 50 MB skip that hides large sessions; storing only user messages.

---

## Phase 4 — Move the phone's engine to the always-on host

The phone should not depend on a laptop being awake. `secratary` already runs Node 20, Python 3.14, the
secretary API (loopback-fast MCP bridge) — and it is where the archive coordinator lives.

Work required, and it is not free: install DSH there; give it a Linux autosync (the same
`autosync`/`sync.py` contract, cron instead of Task Scheduler); add the Linux variant of the secretary MCP
row in the `zabz` preset (the current row is gated `disabled: !!js process.platform !== 'win32'`, so Linux
gets no secretary bridge today — the preset needs a per-platform path, which is what
`settings/machines/*.yaml` exists for); then Serve + `--trusted-host` on that box.

**Acceptance test:** with both workstations shut down, the phone still opens the harness, runs a tool that
touches the secretary, and the session is archived.

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
