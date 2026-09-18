# DSH on the iPhone — every system in the path, and how to check it

Read `00-RESEARCH.md` for why each choice was made and `01-DESIGN-AND-PLAN.md` for the phases.
This file is the **inventory**: what exists, where it lives, how it is kept alive, and the exact
command that proves each part. Verified end to end on **2026-09-14** from a real browser at
393x852 through the real URL, and by `probe-phone.py` **15/15**.

```
iPhone (Safari, or Home Screen)
   │  https://secratary.tail93e6e6.ts.net/            <- Tailscale Serve, TLS, tailnet-only
   │  https://ai.abletelsolutions.com/phone  ->302    <- the owner's existing icon
   ▼
127.0.0.1:3086   phone-gate.py        signs a cold visitor in, injects the phone layer,
   │                                  serves /dsh-phone-mobile.css, relays /api + WS verbatim
   ▼
127.0.0.1:3089   dsh web (engine)     --trusted-host secratary.tail93e6e6.ts.net, loopback only
   │
   ├── preset `zabz`  -> mcp-secretary as a LOCAL stdio child -> authoritative secretary.db
   ├── ~/.dsh/sessions            shipped every 30 min -> dsh_sessions / dsh_session_events
   └── client layer               /dsh-phone-mobile.css + dsh-plugin-mobile + dsh-plugin-cost
```

## 1. The host and the engine

| Thing | Where | How to check |
|---|---|---|
| Host | `secratary` (`100.84.72.88`), the always-on office box | `ssh secretary-ts 'uptime'` |
| Node | `/home/zabz/node/bin/node` (22.23.2 — 20 fails silently) | `/home/zabz/node/bin/node -v` |
| Harness | `/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh` **0.1.5-rc.1** | `node -e "console.log(require('/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/package.json').version)"` |
| Engine | `dsh web --port 3089 --no-open --trusted-host secratary.tail93e6e6.ts.net`, owned by **`phone-engine.service`** | `systemctl status phone-engine` · `ss -ltn \| grep 3089` · `journalctl -u phone-engine -n 40` |
| Harness home | `~/.dsh` — applied from the checkout by `scripts/autosync.sh`, cron `*/15` | `cat ~/.harness-config-autosync/status.json` |

**The two long-lived processes are systemd units, and that is load-bearing.** They were first started
from an SSH session, with `setsid nohup` — which detaches a terminal but does **not** move a process
out of its cgroup, so they lived inside `session-NNNNN.scope`. systemd-logind reaps a session's
processes when the session ends, silently (a signal leaves no traceback), and the phone simply
stopped answering; measured three times on 2026-09-14 before the cause was found:

```
/proc/<gate>/cgroup -> 0::/user.slice/user-1000.slice/session-25033.scope
14:47:06 systemd-logind: Session 25028 logged out. Waiting for processes to exit.
14:47:16 systemd-logind: Removed session 25028.
```

`phone-engine.service` and `phone-gate.service` put them in `/system.slice/`, which no login can
reap, with `Restart=always` (2–3 s) — and `serve-phone.sh` now defers to them instead of starting its
own, because two supervisors for one process is its own outage.

**Loopback-only is deliberate.** `dsh web` refuses `--host 0.0.0.0` because it would expose
remote code execution to the network. The way in is a reverse proxy that preserves `Host`
(Tailscale Serve) plus `--trusted-host`, which is exactly what the `/api` browser-trust fence
reads. **Never drop `trustedHosts` from `profiles/web/cordis.patch.yml`** — a patch replaces the
targeted row's whole `config`, and without that key every `/api` call and WebSocket upgrade is
`403 forbidden` while documents still serve. That was PAIN **P48b**, fixed 2026-09-14.

## 2. The path from the tailnet to the engine

| Thing | Where | How to check |
|---|---|---|
| Serve | `tailscale serve` → `https://secratary.tail93e6e6.ts.net/` → `127.0.0.1:3086` | `tailscale serve status` |
| Gate | `scripts/phone-gate.py` on `127.0.0.1:3086`, owned by **`phone-gate.service`** | `systemctl status phone-gate` · `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3086/ -H 'Host: secratary.tail93e6e6.ts.net'` → 200 |
| Redirector | `scripts/phone-redirector.py` on `127.0.0.1:3087` — the public `/phone` icon | `curl -s -D- -o /dev/null http://127.0.0.1:3087/phone` → 302 |
| Workspace | `/home/zabz/phone`, title **Phone**, kept by `scripts/ensure-phone-workspace.py` | `python3 scripts/ensure-phone-workspace.py --check` → exit 0 |

The **workspace** line is the answer to "why is the workspace on the phone called scratch?". It was
deliberate that a phone session does not run in a git checkout of the company's code — a
conversation from the owner's pocket can run shell commands in its working directory. The *name* was
the accident: `/home/zabz/_scratch` was registered as the only workspace, so every phone session
landed in a junk-drawer directory. `/home/zabz/phone` is now first in the order, and the older
`_scratch` record is deliberately left alone: **nine sessions store it as their cwd, and DSH refuses
to attach a session whose directory no longer resolves**, so renaming it would make the owner's own
history unopenable.

The gate does four things and nothing else: signs a cold visitor in *in flight* (token → cookie,
one response, no redirect chain that a bad cookie can loop), injects the phone layer into
documents, serves `/dsh-phone-mobile.css`, and relays everything else byte-for-byte. It never
sees or logs a token.

## 3. The phone layer — delivered twice, on purpose

| Delivery | What it is | Why |
|---|---|---|
| Injected `<style id="dsh-phone-mobile">` | `assets/mobile.css`, inserted before `</head>` on every document the gate serves | It reaches a phone with no rebuild of the harness package (npm would overwrite it) |
| Linked stylesheet | `/dsh-phone-mobile.css`, linked by `dsh-plugin-mobile` at boot and re-asserted if the app rewrites `<head>` | A document served from the client's own cache carries no layer at all; a link the plugin owns cannot be cached away or dropped |

**The gate also marks its document `Cache-Control: no-store`.** The engine sends its document
with no cache directives at all, which a phone is free to reuse without asking — measured
2026-09-14: a warm browser rendered the app with the layer absent while a cold one in the same
minute rendered it correctly.

What the layer does, all measured at 393x852 on the live app:

- the sidebar becomes an off-canvas **drawer** (`fixed`, -340px closed, width `min(86vw,340px)`),
  and the frame is forced to one column so the conversation keeps the full 393px;
- the drawer's own toggle is **pinned to the top-left of the screen** at 44x44, and the
  conversation header is inset so nothing sits under it;
- `html, body` do not scroll, and momentum is contained in the app's own scrollers — this is the
  "funny scroll" where the panel under the finger stays put while the page moves;
- controls are at least 44px (icon buttons by `aria-label`, text-labelled ones by container,
  `[role=tab]`, and buttons inside `[role=dialog]`), and text fields compute to 16px so iOS does
  not zoom the page on focus;
- safe-area insets are honoured top and bottom.

## 4. The client plugins the phone loads

| Package | What the owner sees | How to check |
|---|---|---|
| `dsh-plugin-mobile` | the drawer closes on an action taken in it; the layer stylesheet is linked | `curl -s http://127.0.0.1:3086/ -H 'Host: <authority>' \| grep -o dsh-plugin-mobile` |
| `dsh-plugin-cost` | the **cost pill** in the composer footer (`$0.09` on a session with usage) plus `/cost` | the same command for `dsh-plugin-cost` |
| `dsh-plugin-attention` | the attention badge ("6 needing attention") | present in the bundle list; confirm the roster before relying on it |
| `dsh-plugin-windows` | **not installed here, on purpose** — its `+`/`⧉` controls open a new DSH window through a Windows protocol, and neither renders below 768px anyway | `grep dsh-plugin-windows ~/.dsh/profiles/web/package.json` → absent |

The phone engine mounts the same `zabz` preset and the same default model as both workstations.
The plugin set differs only where the platform differs (above), plus `plugin-attention`, which is
another lane's in-flight work.

## 5. What keeps it alive, and what watches it

| Mechanism | Where | How to check |
|---|---|---|
| **systemd** owns the engine and the gate | `phone-engine.service`, `phone-gate.service` | `systemctl is-active phone-engine phone-gate` |
| Watchdog | crontab `*/2 * * * *` → `scripts/serve-phone.sh` (also `@reboot`) — **defers to the units** and never restarts a healthy one | `crontab -l \| grep serve-phone` |
| What it repairs | Serve, the redirector, **both** client plugin installs, and the phone workspace | `./scripts/serve-phone.sh` prints what it found; silence = nothing to do |
| Probe | crontab `*/5` → `scripts/probe-phone.py --quiet --json` → `~/.dsh-phone/probe.json` | `python3 -c "import json;d=json.load(open('$HOME/.dsh-phone/probe.json'));print(d['ok'],d['passed'],d['total'],d['failed'])"` |
| What the probe covers | 15 checks: cold visitor, token exchange, document, **WebSocket upgrade 101**, foreign-Host fence, real HTTPS through Serve, stale cookie, dead link, connection reuse, layer delivery, roster, **an authenticated RPC (`session/list`)**, **layer cannot be cached away**, **stylesheet route**, public `/phone` | `python3 scripts/probe-phone.py` |
| Kernel | `ceo-kernel` sentinel check `phone_endpoint` reads that verdict | `ck status` on the authority |
| Session archive | `scripts/push-dsh-sessions.mjs`, cron `*/30`, `--transport local` → `dsh_sessions` / `dsh_session_events` in the authoritative DB | `python3 scripts/server/check-dsh-freshness.py` |

**Findings still reach nobody** (PAIN P40/P55): the kernel detects an outage and the owner learns
about it by holding the phone. The in-harness attention badge is the piece being built for that.

## 6. The acceptance test, and where its evidence is

From the phone page at 393x852, in a **new** session created from the drawer:

> "Using your secretary tools, how many ticks today? One line, with the source file."

Measured 2026-09-14: the session called `mcp__secretary__ps_db_query`
(`SELECT COUNT(*) AS ticks_today … FROM tick_telemetry WHERE date(started_at)=date('now')`),
and answered

> **62 ticks today — `/home/zabz/personal-secretary-mvp/data/secretary.db`, table `tick_telemetry`
> … 2026-09-14 00:06:18 → 05:52:39 UTC; verified by direct sqlite read**

That is the whole point of the path: the same agent, the same toolbelt, reading the
**authoritative** database, with provenance and freshness stated. Acceptance is not "the tool was
called" — it is that the number is the authority's (PAIN P22, Phase 2.5).

Screenshots: `docs/dsh-mobile/evidence/phone-live-20260914-*.png` (boot timeline, drawer, session
with the cost pill, the tool answer, the drawer closing itself).

## 7. What is still rough, stated rather than hidden

- **First run on a brand-new client.** A browser with no history shows a "Choose workspace" row
  until one is picked, because the app resolves a session's workspace by *membership* and a session
  created outside the workspace picker has a directory but no membership
  (`dsh-client-ui-workspace`: `workspaceId ?? currentWorkspaceId ?? recent`). The owner's phone does
  not see it — his existing sessions already belong to a workspace — but a fresh device does. P46.
- **In-transcript disclosures are 40px tall** and some path chips are 24px. Deliberate: 44px on
  inline transcript rows distorts the whole message. Every *primary* control is >= 44px, and the
  composer's own row is now one line with no control under 44px.
- **The composer used to wrap onto two lines with the cost pill present** (232px of the screen for
  the whole composer). Fixed by removing the two controls that were redundant here — access mode
  (`danger-full-access` is pinned on this host) and the shipped stats strip — not by shrinking the
  remaining 44px targets. Measured after: one control row.
- **A phone cannot be identified.** Serve rewrites every visitor to 127.0.0.1 and the gate logs no
  User-Agent, so "the owner is on his phone" is inference, not a reading (PAIN P43).
- **Two other services on this host have more than one supervisor.** The cron API watchdog and the
  `secretary-api.service` unit both start uvicorn, which produced four restarts in one hour and a
  `kill -9` path in `secretary-startup.sh`. Not this path, and not touched tonight — the phone units
  deliberately give each process exactly one owner. Recorded in `journal/PAIN.md`.
