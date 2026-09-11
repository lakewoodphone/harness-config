# DSH on the phone, and DSH sessions in the secretary — the evidence base

**Written:** 2026-09-11 · ZABZ-YOGA · for the work requested that afternoon.
**Ask, in the owner's words:**

> "the yoga and desktop have to stay in sync … changes to the deep sea harness configuration will have
> to be synced with each other properly and the same script that takes the VS code copilot chat sessions
> and always brings them to the secretary to always have them traced. Should do the same for the DSH
> harness and once that's all robustly and properly set up I need you to look at the scripts that on my
> iphone. I have a little web app for this secretary server to be able to talk to. I don't like it so
> much and it doesn't work so well. I want you to adapt that to be able to speak to the DSH harness
> through my iphone app. So again we'll be the same you and the chat sessions will be saved and have all
> the tools and all that."

Everything below was **read in code, run, or delegated and cross-checked**. Where something is inferred
rather than measured, it says so. The design that follows from it is `01-DESIGN-AND-PLAN.md`.

---

## 0. Method

| Source | How it was obtained |
|---|---|
| DSH itself | Installed packages under `C:\Users\ezabz\AppData\Local\npm-cache\_npx\<id>\node_modules\@deepseek-ai\` (~230 packages, v0.1.5-rc.2) and the public repo `deepseek-ai/deepseek-harness` (MIT) |
| The harness's live behaviour | **A throwaway engine started on `:3099` and probed with `curl`, then killed** — §2 is the result of that experiment, not of a README |
| The existing trace pipeline | `personal-secretary-mvp` scripts + the live server DB read read-only over `ssh secretary-ts` |
| The phone app | `web/app/phone/*`, `web/app/api/phone/*`, the live URLs, and `data/phone_chat_history.db` read read-only |
| The rest of the fleet's work | `harness-config/docs/multi-window/` (another session's session-URL research) — cross-checked, and one of its conclusions is corrected below |
| External practice | Tailscale Serve/Funnel/Cloudflare docs, iOS Safari backgrounding behaviour, log-shipper cursor design (cited inline) |

---

## 1. The harness is public and partly documented

`@deepseek-ai/dsh`, repo `https://github.com/deepseek-ai/deepseek-harness.git`, **MIT**, monorepo
(`apps/cli`, `packages/…`). Docs at the repo and a generated site. Roughly 230 `@deepseek-ai/dsh-*`
packages are installed locally.

Surfaces that exist, and what they are good for:

| Surface | Command / artefact | Reachable from a phone? |
|---|---|---|
| Web app | `dsh web` (alias of `--profile web`), GUI on `127.0.0.1:3080` | **Yes, via a loopback-side proxy** — §2 |
| Client RPC | `POST /api/<namespace>/<method>` + one WebSocket at `/api/remote.mux` | Yes, with the cookie (§2, §3) |
| SDK | `dsh --profile sdk` — newline-delimited JSON-RPC **over stdio** | No |
| ACP | `dsh --profile acp` — Agent Client Protocol v1 **over stdio** | No |
| Headless | `dsh --profile headless "<task>"` — one turn, printed, exits | No |

---

## 2. The load-bearing finding: the web app is loopback-only **by design**, and a trusted proxy is the supported way in

**It cannot bind to a LAN address.** The CLI refuses outright (`dsh-web-app/lib/startup.js:40`):

> `error: --host 0.0.0.0 is intentionally not supported yet for safety: it would expose remote code execution to the network; use 127.0.0.1 instead`

This is a deliberate security posture, not a limitation to work around. The refusal lives in the CLI
argument parser while the webserver schema is `127.0.0.1 | 0.0.0.0` (`dsh-host-webserver/…/index.d.ts:50`),
so a profile patch *could* force it — **treat that as a trap, not an option.**

**Auth is real, and it runs in two stages** (`dsh-client-connection/lib/index.js`):

1. A **Host/Origin fence** before auth: untrusted Host → **403**; `sec-fetch-site: cross-site` refused;
   `Origin` must equal `Host` (`:201–215`).
2. A **signed cookie**: a random per-process launch token is accepted **only on `GET /`**, exchanged for
   `dsh-auth-<base64url(sha256(authority))>` — `HttpOnly`, `Path=/`, `SameSite=Strict`, 30-day absolute
   expiry, signing secret in `$DSH_HOME/.credentials.yaml`, **deliberately no `Secure`** because the
   shipped server is loopback HTTP. Missing/expired/wrong-authority cookie → **401**
   (`:552–556`). There is **no method-specific loopback tier and no trusted-network tier**.

`--trusted-host <host or host:port>` (`:22`) is what widens the fence — "exact on `host:port`, **any port
on port-less entries**".

### The experiment that decided the design

A throwaway engine was started with `--trusted-host dsh.test` on port 3099 and probed directly. One
subagent read the code and concluded *"a tailnet address can never complete the token exchange"*; the
other read the docs and said it would. **The experiment says the docs are right:**

| # | Request | Result | What it proves |
|---|---|---|---|
| 1 | `GET /?token=<tok>` with `Host: dsh.test` | **303** + `set-cookie: dsh-auth-aNEtQgzI…=v1.…` whose payload decodes to `{"authority":"dsh.test"}` | **A non-loopback-but-trusted authority CAN complete the exchange, and the cookie is minted for that authority.** The code-reading conclusion was wrong |
| 2 | `GET /?token=<tok>` with `Host: 127.0.0.1:3099` | **303** + cookie with `{"authority":"127.0.0.1:3099"}` | The mechanism is authority-generic; loopback is not special-cased |
| 3 | `POST /api/session/list` with the `dsh.test` cookie and `Host: dsh.test` | **200** + a real gateway JSON-RPC response | The authenticated API is fully reachable from a trustied non-loopback authority |
| 4 | Same cookie, `Host: evil.test` | **403** | The fence refuses an untrusted host **even with a valid cookie** |
| 5 | `Host: dsh.test`, no cookie | **401** | Fence ≠ auth; both must pass |
| 6 | The `dsh.test` cookie presented with `Host: 127.0.0.1:3099` | **401** | The authority binding is real: a cookie is worthless on another authority |

*(Row 3's body was malformed, so the server answered `gateway/bad-request`. That is the point — it
**parsed and answered** the call, which only happens after the fence and the cookie both pass.)*

**Conclusion: `dsh web` + a reverse proxy that preserves `Host` + `--trusted-host <that host>` is the
supported, no-patch way to put this harness on the phone.** Tailscale Serve gives exactly that: an
HTTPS URL on the tailnet, valid certificate, **no public exposure**, no domain to buy, and identity
headers should the proxy layer ever want to enforce its own policy.

Rejected, with reasons:

| Option | Why not |
|---|---|
| `--host 0.0.0.0` (CLI or patched) | Discards the RCE guarantee deliberately built into the CLI |
| Tailscale Funnel | Public by design, and drops the identity headers that make Serve worth having |
| Cloudflare Tunnel for the phone | Needs a domain, public hostname, and its own auth layer — more moving parts than Serve for one phone |
| SDK/ACP stdio bridge | Cheapest to write, **worst fidelity**: those profiles do **not** mount `agent-presets`, so `zabz` — the toolbelt, the persona, the MCP bridges — is absent (§5) |

---

## 3. What the client API can do (so a custom client is *possible* if ever needed)

Wire shape (`dsh-client-connection/lib/client.js:6206`): `POST /api/<namespace>/<method>` with
`{"type":"client-request","rpcId":…,"method":…,"payload":…}`; streams over one gateway-owned WebSocket at
`/api/remote.mux`, gated by the same check, with ping/pong and a `ready`-framed generation lifecycle
(jittered backoff 500 ms → 10 s; `ctx.connection.reconnect()` resets it).

The `session` namespace exposes **everything a chat client needs**:

| Need | Method |
|---|---|
| list sessions | `session/list` |
| create / adopt a session | `session/create` (`agentPreset` may be set **per session**) |
| send a user message | `session/prompt` → `messageId` |
| stream assistant deltas | `session/follow` with `assistantStream:true` → `start`/`chunk` frames |
| tool calls / results | ordinary durable session events in the same journal |
| history | `session/page`, or `follow`'s opening frame |
| others | `session/fork`, `rename`, `cancel`, `search`, `selectModel`, `modelCatalog`, `control` |

---

## 4. Session storage, and three traps that would silently lose data

- Location: `<DSH_HOME>/sessions/--<normalized-cwd>--/<session-id>/session.vN.jsonl.zstd`; the live files
  are `session.v3.jsonl.zstd`, one **independent zstd frame per durable append batch**, plus a checksummed
  header frame. (This is why a one-shot `zstdDecompress` on a 2.4 MB session returns 202 readable bytes —
  the mistake `read-session.js` was written to avoid.)
- **Trap 1:** one-shot decompression reads only the **first** frame → an archiver would silently drop
  everything after the header.
- **Trap 2:** rows can be *packed* (`text-chunks`, `reasoning-chunks`, `tool-call-chunks`) carrying `seq0`,
  not `seq` → a parser keyed on `row.seq` drops most assistant output.
- **Trap 3:** a torn final frame is a normal crash boundary, not corruption.
- The official decoder is `decodeStorageRecord` from `@deepseek-ai/dsh-session`. **Use it; do not hand-roll.**
- `dsh-session-query-sqlite` is a **derived FTS index, not a mirror** — and the shipped web profile pins
  it to `path: ':memory:'` (`dsh-web-app/cordis.patch.yml:27`). **There is no persistent local search
  index to reuse.** Building the archive's own index is therefore required, not optional.
- `session-log-export` is a *browser download*, not a host-side write.

---

## 5. Presets — the reason only the web profile is acceptable

`agent-presets.default` in `~/.dsh/settings.yaml` is **`zabz`** (set 2026-09-11, applied on both
workstations). It is read at session creation, and `SessionCreateRequest.agentPreset` can override it per
session.

**But `dsh-base` has no `agent-presets` row, and the headless, sdk and acp patches do not add one.** So a
headless/SDK/ACP run does not mount `zabz` at all — no toolbelt, no MCP bridges, no persona. There is also
**no CLI flag** to select a preset for those profiles.

→ Any design whose agent is not the **web profile** is a second, weaker agent wearing the same name.

---

## 6. No session is addressable by URL (and what that means for a phone)

Verified by another session (`harness-config/docs/multi-window/research-session-urls.md`) and consistent
with everything read here: zero `pushState`/`replaceState`/`popstate`/`location.hash`/`sessionId` in all 65
client bundles; the server matches pathname only and the SPA fallback serves `index.html` **only at `/`**;
the `?token=` exchange 303s to literal `/` and drops other parameters. Session selection lives in
**`localStorage["dsh.sessions.current"]`, keyed by origin (scheme+host+port)**.

Consequences for the phone:

- The UI is **installable** — `/manifest.webmanifest` returns 200, `content-type: application/manifest+json`.
- But a phone browser has its own origin, so its "current session" is its own; it will not inherit the
  desktop's selection. For a single-window phone that is exactly what the owner described wanting.
- Deep-linking a session is not possible today, on any device. Don't design around it.

---

## 7. The existing trace pipeline — the proven pattern to mirror

`scripts/vscode_chat_extractor.py` (parse only, no network) → `scripts/push_vscode_chats.py` (shipper) →
`POST https://api.abletelsolutions.com/api/v1/owner/vscode-chats/ingest` (`app/main.py:21116`) →
`app/services/vscode_chat_ingest.py` → three tables + FTS5 in the authoritative `secretary.db`.

| Aspect | As built |
|---|---|
| Auth | header `x-ps-vscode-chat-ingest-token` (fallback `x-ps-api-key`), server-side `hmac.compare_digest`; verified live: no token → **401** |
| Body | `{source_machine, exported_at, schema_version:1, sessions:[…], content_hash}` — **plain JSON**; gzip/zstd is the client's problem |
| Batching | ≤100 sessions, ≤4 MB, 2 retries |
| Required per session | `session_id` **only** (others are silently skipped); server derives `indexed_text` if absent |
| Dedupe | PK `(source_machine, session_id)` + `ON CONFLICT DO UPDATE`; server-computed `sha256(indexed_text + json(user_messages))` compared to short-circuit unchanged; messages deleted-and-reinserted |
| Client state | `data/vscode_chat_sync_state.json` (gitignored, load-bearing) — written **only if zero errors** |
| Schedule | two Windows Scheduled Tasks, hourly, `PersonalSecretary-PushVSCodeChats` (yoga :26, desktop :30), last result 0 |
| Scale | 281 exports, **1,592 sessions**, 4,368 messages, 957 FTS rows; both machines arriving |

Known gaps in it, which the DSH version should not inherit:

1. **`GitHub.copilot-chat\transcripts\*.jsonl` is read by nothing** — sessions living only there never reach
   the server.
2. **635 sessions predate the FTS backfill** and are invisible to `/search`.
3. `--days 1` + an mtime filter means anything missed for more than a day is lost unless `--force --all` runs.
4. Only **user** messages are stored — no assistant content.
5. `_MAX_JSONL_BYTES = 50 MB` silently skips larger sessions.

---

## 8. The phone app as it exists today

**It is the `/phone` PWA ("Secretary Chat") inside the Next.js dashboard** — the only PWA manifest anywhere
in `C:\Users\ezabz\code`. Not a separate repo.

| Aspect | Today |
|---|---|
| Files | `web/app/phone/page.tsx`, `PhoneChat.tsx` (1,075 lines), `phone.css`, `web/app/api/phone/chat/{route.ts,history/route.ts,sessions/route.ts}`, `web/public/phone/manifest.webmanifest` |
| Reachability | **public internet** — `https://ai.abletelsolutions.com/phone`, `cloudflared` → `localhost:3000`, `next-server`, `secretary-dashboard.service` |
| Auth | NextAuth JWT 30 days, **GitHub OAuth only** in production; backend key added server-side, never on the phone |
| Features | streaming, collapsible reasoning, 4-model picker, sessions drawer, stop, retry, copy, markdown; `100dvh` + safe-area; **no voice at all** |
| Path to the engine | `POST /api/phone/chat` → **`POST /api/v1/owner/phone-chat/stream` (`app/main.py:14743`)** → one LLM call → tools → forced second synthesis |
| Storage | its own `data/phone_chat_history.db` (3 sessions, 22 messages) |
| **Usage** | **3 sessions, 22 messages, last used 2026-09-08 16:16 UTC.** He barely uses it |

Why he dislikes it is already diagnosed in his own repo — `docs/operations/assistant-architecture-audit-2026-09-02.md`
quotes him at `:5`:

> "it has to actually be you"

with a symptom table (*"Who is Yocheved → no answer"*, *"Contact lens → found nothing"*, *"red stop button
stays red"*) and the root cause at `:11–21`: **four divergent chat paths on a single-turn engine that never
executes tools.** `phone-chat-token-streaming.md` §12 records that **tools silently never ran on the phone
until 2026-09-02** (a swallowed `TypeError`).

**This is the same failure the whole kernel exists to answer: the phone was talking to a different,
weaker agent than the desktop.** "Make the phone reach the DSH harness" is precisely the fix.

His own stated intent, from the audit:

- `docs/secretary-replacement-audit/07-console-architecture.md:146–160` — "one window, same full agent";
  the exposure choice (Tailscale vs Cloudflare Access) is listed as **his** open decision.
- `06-decision-log.md:179` — *"on the desktop, yoga, and iphone i am always talking to the same you"*.
- Voice is an open question (`05-question-register.md:353` Q15) and is not in the app today.

---

## 9. External research, condensed

| Topic | Finding | Source |
|---|---|---|
| Private access from one phone | **Tailscale Serve** is the only option giving HTTPS with a valid cert, tailnet-only, **no public exposure and no domain**; it emits identity headers; a missing tailnet ACL grant for tcp/443 fails *silently* as a timeout | [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) |
| Funnel | Public by design; **"Funnel traffic … does not include identity headers"** — so it is strictly worse for this use | [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel) |
| Cloudflare Tunnel | Fine, but needs a domain and a second auth layer | [CF Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) |
| iOS Safari streaming | Renderer suspended and TCP dropped after **~5 s in the background**; `EventSource` auto-reconnect is unreliable on iOS 18. The robust pattern: `close()` on `visibilitychange→hidden`, reopen on visible and **resume from a stored cursor** (the browser will not send `Last-Event-ID` for a stream you closed deliberately) | [SSE mobile handling](https://www.server-sent-events.com/frontend-consumption-client-patterns/mobile-background-tab-handling/), [WebKit 282526](https://wiki.webkit.org/show_bug.cgi?id=282526) |
| Transport choice | Providers stream with `fetch` + `getReader()`. `EventSource` cannot set headers (forcing tokens into URLs) and caps at 6 connections/origin on HTTP/1.1. WebSocket adds bidirectionality — which matters because the harness **asks for tool approval mid-stream** | [AI streaming patterns](https://websocket.org/guides/use-cases/ai-streaming/) |
| Mobile layout | Use `100dvh` not `100vh`, respect `env(safe-area-inset-*)`, drive the composer from `window.visualViewport` rather than fixed positioning | [visualViewport keyboards](https://fwdtools.com/ui-snippets/visual-viewport-keyboard-safe-input-bar/) |
| Transcript cursor design | **Never** use a wall-clock cursor (skew, missed in-place rewrites, NTP steps). Use a monotonic per-session sequence **and** a byte offset over an append-only file, persisted durably — the Fluent Bit `tail` model: *"you can use a database file … history of tracked files and a state of offsets … resume if the service is restarted"* | [Cursors and their lies](https://learn.padho.ai/wiki/cursors-updated-at-columns-and-their-lies), [Fluent Bit tail](https://docs.fluentbit.io/manual/data-pipeline/inputs/tail) |
| Idempotency | At-least-once delivery + an upsert on `(machine, session, seq)`. Do not chase exactly-once | as above |

A third-party plugin, [`NewSpringWei/dsh-biz-bridge`](https://github.com/NewSpringWei/dsh-biz-bridge),
already implements an HTTP+SSE front for DSH. Verified real, but **v0.1.0, one star, self-described as
unsuitable for critical paths** — reference material for a future custom client, **not a dependency**.

Two threads could not be resolved and are recorded rather than glossed: `@creait/dsh-tailnet-gateway` and
`SummerSec/dsh-web-auth` are real repos but npm returned 403, so their contents are unread — a tailnet
gateway plugin is *exactly* this problem, so it is worth a look later. And no credible "best minimal
open-source chat UI" was found; that specific question has no reliable answer.

---

## 10. What was actually built and verified while writing this

**Unattended sync between the two workstations** (`scripts/autosync.ps1` + `Install-Autosync.ps1`,
commit `c7faeb4`+`e57230d`):

- Registered on both machines as `PersonalSecretary-HarnessSync`, at logon and every 15 minutes.
- ZABZ-TECH: fired by Task Scheduler, **result 0**, record `{"result":"clean","converged":true,"commit":"e57230d"}`.
- ZABZ-YOGA: fired, recorded `dirty` — another session had a modified tracked file, so it **pulled but
  deliberately did not publish** into `~/.dsh`. That is the designed behaviour, and it is the honest state.
- The clean path (pull → apply → verify → converge) was proven end to end in a **throwaway clone with a
  throwaway `DSH_HOME`**, not on the live config: `{"result":"clean","converged":true}`, exit 0, settings +
  both presets applied.
