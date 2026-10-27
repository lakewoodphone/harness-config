# A — Transport and always-on runtime for HA events reaching an agent

**Research lane A of the estate-wide security redesign.** Read-only: nothing on a live system was changed, no
message was sent, no credential value appears below.

**Ran on:** `zabz-tech` (the shop Windows desktop — which turns out to be the subject of the main finding, not a
neutral vantage point). **Date:** 2026-10-26, ~21:20–21:40 UTC.
**Extends, does not repeat:** `docs/HANDOFF-2026-10-26-security-audit.md` §4 (access routes), §9 (traps);
`docs/security-system-design-2026-10-26.md` Round 5 (the split) and Round 11 (availability);
`_scratch/audit-2026-10-26/W6-observability.md` §2 (the page that never ran) and `W3-response-chain.md` §6–7
(siren listener, HA restart).

Every claim below carries `file:line`, a command with its raw output line, or a source path inside the HA
container for 2025.10.3. Where a thing was not verified it says **UNVERIFIED** and what would settle it.

---

## 1. The binding constraint, found before any transport question

The brief describes the company's HA path as "the tailnet at `http://zabz-tech.tail93e6e6.ts.net:8123`
(an HTTP proxy on the shop Windows desktop)". Two measurements change that description in a way that decides
most of this document.

**1.1 The Raspberry Pi is not a tailnet node.** `tailscale status` on the desktop lists eleven peers; none is
the Pi.

```
100.85.153.96    zabz-tech              lakewoodphoneandtech@  windows  -
100.73.176.126   secratary-cloud        lakewoodphoneandtech@  linux    active; direct 178.156.194.1:41641
100.105.248.90   zabz-tech-linux        lakewoodphoneandtech@  linux    idle
100.126.146.121  lakewooechsmini        lakewoodphoneandtech@  macOS    idle
100.72.162.5     zabz-yoga-1            lakewoodphoneandtech@  windows  active; direct 172.59.214.144:24939
```

**1.2 The "proxy" is `tailscaled` itself, doing a TCP forward.** It is not an HTTP proxy and it is not a
separate service; it is a `tailscale serve` rule owned by the Tailscale daemon on this workstation:

```
$ tailscale serve status
|-- tcp://zabz-tech.tail93e6e6.ts.net:8123 (tailnet only)
|-- tcp://100.85.153.96:8123
|-- tcp://[fd7a:115c:a1e0::b337:9960]:8123
|--> tcp://192.168.50.34:8123
```

and the process holding 8123 is `tailscaled` (pid 10632,
`"C:\Program Files\Tailscale\tailscaled.exe" /subproc …`), confirmed by
`Get-NetTCPConnection -LocalPort 8123 -State Listen` → `100.85.153.96  8123  10632`.

**1.3 The authority has no other way in.** From `secratary-cloud`:

```
$ ssh secratary-cloud "curl -s -o /dev/null -w '%{http_code} %{time_total}\n' http://192.168.50.34:8123/api/"
unreachable
$ ssh secratary-cloud "curl -s -o /dev/null -w '%{http_code} %{time_total}\n' http://zabz-tech.tail93e6e6.ts.net:8123/api/"
401 0.228687
```

So every cloud→HA request today is a four-hop chain: **authority → Tailscale → `tailscaled` on a Windows
workstation → LAN → Pi**. The workstation is not an optimisation detail; it is the only bridge, and it is a
desktop the owner uses, logs out of, and reboots.

*Consequence for the rest of this document:* no transport choice can be more available than that chain, so
§4 (runtime placement) answers a question §2 cannot. This is consistent with design Round 11's "network
partition (HA up, server up, path broken) → page fails, nobody knows", and it is the concrete instance of it.

**1.4 HA itself is directly reachable from the shop LAN.** From the desktop:
`GET http://192.168.50.34:8123/api/` → `401` (auth challenge, i.e. HA answering), not a connection failure.
From `zabz-tech-linux`: `HA 401 0.040745s` (curl, 6 s cap). Both are on `192.168.50.0/24`.

---

## 2. HA 2025.10.3's own delivery options, with mechanism and guarantees

Version read from the live system, not from memory:

```
$ . ha.ps1 -Path /api/config  → version: 2025.10.3
$ ssh … root@192.168.50.34 "ha core info" → version: 2025.10.3
  image: ghcr.io/home-assistant/raspberrypi4-64-homeassistant
  ssl: false, port: 8123, machine: raspberrypi4-64, update_available: true (latest 2026.10.4)
```

Everything in this section is read from the running container's own source at
`/usr/src/homeassistant/homeassistant/…` inside `docker exec homeassistant`, i.e. the code that is actually
executing, not the docs for a different release.

### 2.1 REST webhooks — `POST /api/webhook/<webhook_id>`

**Mechanism.** A component registers a handler under a random id; HA exposes one view for all of them.
`DEFAULT_METHODS = (METH_POST, METH_PUT)` (`components/webhook/__init__.py:31`); `SUPPORTED_METHODS` adds GET
and HEAD (`:32`). GET is refused with 405 for a *registered* webhook (`:160-162`, `METHOD_NOT_ALLOWED`), except
HEAD which is always 200 so link-checkers work (`:153`).

**Auth: there is none, by design.** The view is declared `requires_auth = False`
(`components/webhook/__init__.py:216`) and `cors_allowed = True` (`:217`). The `webhook_id` *is* the
credential. This is the standard HA webhook contract, but the consequences for a security system are severe and
are not usually spelled out:

- **An unregistered id returns 200 OK.** `:148` `return Response(status=HTTPStatus.OK)` after logging
  "Received message for unregistered webhook". Measured on the live system with a fresh GUID, no auth header:

  ```
  POST status=200 body=''
  GET  status=200 body=''
  PUT  status=200 body=''
  ```

  Note the GET returning 200: for an unknown id the unknown-branch runs *before* the method check, so a wrong
  method is indistinguishable from a right one. `local_only` and `allowed_methods` never get a chance to speak.

- **A handler exception also returns 200.** `:196-199` — `except Exception: _LOGGER.exception(…); return
  Response(status=HTTPStatus.OK)`. So a webhook that crashes inside HA reports success to its sender.

- **Therefore a 200 from a webhook carries no information at all.** It means "a TCP connection reached HA and
  was closed". It does not mean the id exists, the method was allowed, the origin was permitted, or the
  handler ran. This is the single most important fact in this document: any design whose delivery guarantee is
  "HA got a 200" has no guarantee.

**`local_only` and `allowed_methods`.** Both are real, and both are weaker here than they look.
`local_only` rejects a non-private `request.remote` (`:164-182`), and `network_util.is_local` is what decides.
But the request arrives from the *proxy host*, whose address is `192.168.50.138` — private. And
`192.168.50.138` is **not** in `trusted_proxies` (`config/configuration.yaml:18-23` lists `127.0.0.1`, `::1`,
`192.168.50.34`, `172.30.32.0/23`, `172.30.33.0/24`, then Cloudflare ranges), so HA ignores
`X-Forwarded-For` and uses the socket address. The result:

> `local_only: true` passes for **anything on the tailnet**, because everything arrives from a private proxy
> address. It is not a security boundary behind this forward; it is a boundary against the public internet only.

**Ordering / delivery / reconnect.** None apply. It is a bare request/response with no queue, no ack and no
retry. If the sender dies mid-request the event is gone and HA logs nothing that anything reads (W6 §2.5: the
HA error log is a ring buffer, erased on restart, read by no consumer).

**Verdict.** Not usable as the primary event transport. It remains usable as an *inbound trigger into HA*
(§2.5), where the caller can at least observe the automation's side effects.

### 2.2 WebSocket API — `/api/websocket`

**Mechanism and measured handshake.** One socket, JSON frames, a mandatory auth frame first:

```
tcp open → {"type":"auth_required"} → {"type":"auth","access_token":…} → {"type":"auth_ok"}
```

Measured from the authority through the whole chain: `auth_ok` **18 ms** after `auth_required`; the
`subscribe_events` result is acked **36 ms** after socket open. This is the exact handshake the brief asks
about, and it works over today's proxy without change.

**Commands that matter.**
- `subscribe_events` with no `event_type` subscribes to everything; with `event_type: state_changed` to the
  state bus (`components/websocket_api/commands.py:158-199`).
- `subscribe_trigger` takes a full automation-style `trigger:` config and evaluates it **server-side**
  (`commands.py:834-841`), so the agent receives only matching events. Measured: a trigger on one busy entity
  plus a full `state_changed` subscription in the same 40 s window produced **7 trigger events vs 26
  state_changed events** — i.e. per-entity filtering works and cuts the firehose by ~73 % for *one* entity out
  of 1,037. A six-entity security filter reduces the stream to near-nothing.

**Auth and the non-admin token the audit wants.** `commands.py:170`:
`if event_type not in SUBSCRIBE_ALLOWLIST and not connection.user.is_admin: raise Unauthorized`. So a
non-admin token (audit §8.8, the "single highest-value fix") **can** subscribe to the allowlisted
`state_changed` and to triggers, which is all this design needs. It cannot subscribe to arbitrary bus events.
That is a reason the WS design is compatible with the token hardening rather than blocked by it.

**Ordering.** One TCP connection, one writer, HA appends to a single deque (`components/websocket_api/http.py`
`_message_queue.append`), so frames for one subscriber are delivered in the order HA fired them. Ordering is
per-connection and is *not* preserved across a reconnect.

**Delivery guarantee, precisely.** There is no replay. `connection.subscriptions[msg["id"]] =
hass.bus.async_listen(event_type, forward_events)` (`commands.py:194`) registers the listener at subscribe
time, so anything fired while disconnected is not queued for you. Backpressure is bounded, not silent:
`MAX_PENDING_MSG = 4096` (`components/websocket_api/const.py:31`) and on overflow HA logs "Client unable to
keep up with pending messages" and calls `self._cancel()` (`http.py:215-225`) — it disconnects the client
rather than dropping frames quietly. So while connected: no silent loss; on overflow or network loss: an
explicit close, then a gap.

**Reconnect, measured.** Full cycle — TCP, auth, resubscribe — is **105 ms** (tcp 69 / `auth_ok` 89 /
`subscribe` result 105). Reconnect is not a problem; the *gap* is, because nothing replays it.

**Verdict.** This is the transport.

### 2.3 MQTT

The estate does run a broker, and it runs on the HA host:

```
$ ssh … root@192.168.50.34 "docker ps --format '{{.Names}}'"
app_core_mosquitto
app_45df7312_zigbee2mqtt
$ docker port app_core_mosquitto
1883/tcp -> 0.0.0.0:1883
1884/tcp -> 0.0.0.0:1884
8883/tcp -> 0.0.0.0:8883
8884/tcp -> 0.0.0.0:8884
$ netstat -tlnp | grep 1883   → tcp 0.0.0.0:1883 LISTEN
```

So a broker exists, is LAN-exposed, and `zigbee2mqtt` already publishes to it. Its semantics would be
genuinely stronger than a webhook's: QoS 1 gives broker-acknowledged at-least-once (with duplicates), and a
retained message gives a new subscriber the last value without asking HA.

**Why it is still rejected for the agent path.** Three measured reasons, one design reason:

1. **No route.** The tailnet forwards on this host are only 8080, 8123 and 3086 (`tailscale serve status`
   above). 1883 is not among them, so the authority cannot reach the broker at all today — it would need a
   second `tailscale serve` rule, i.e. a second hole in the same single point of failure.
2. **A second credential store.** The broker has its own users; the audit already records that the maglock is
   opened by publishing to `zigbee2mqtt/Smart Switch/set` under "one shared broker user" (handoff §5.10).
   Adding the event path to that broker widens an existing weak credential rather than reducing it.
3. **It duplicates HA's own bus.** Every MQTT state topic is a re-publication of a state change HA has already
   emitted on its bus, with *less* structure: no `old_state`/`new_state`, no `context`, no `user_id`. The WS
   `state_changed` event carries all of that (`data.old_state.state` → `data.new_state.state`, observed in the
   sample below), which the security rules need in order to say "the door went open→closed with no credential".
4. **QoS 0 is the z2m default for state topics** — UNVERIFIED for this install; settling it needs
   `/addons/zigbee2mqtt` options read on the host (`qos` key). Even if it is 1, (1)–(3) stand.

MQTT stays where it already is: the actuator path for the maglock (`home_assistant.py:65-71`), which is a
command with a retained-state readback, not an event stream.

### 2.4 `rest_command` — HA calling the company

The one direction that exists today. `config/packages/phoenix_security.yaml:349-357`:

```yaml
rest_command:
  phoenix_security_page:
    url: "https://ai.abletelsolutions.com/webhook/ha/security-alert"
    method: POST
    content_type: application/json
    headers:
      x-ps-api-key: !secret secretary_security_api_key
    payload: '{"event": "{{ event }}", "detail": "{{ detail }}", "snapshots": {{ snapshots | default([], true) | tojson }}}'
    timeout: 15
```

**It is synchronous inside the calling script, and it raises on failure.** In
`components/rest_command/__init__.py` the call is awaited and a non-2xx or a timeout raises
`HomeAssistantError` (`:215`, `:225`, `:240`, `:248`). That is the mechanism behind W6's finding that the page
step could not be attempted until the blocking siren loop ended, and why `continue_on_error` mattered. It also
means a dead company API **stalls the HA script for up to 15 s** per attempt — a real cost inside a 5-second
budget, and a reason the page must not share a sequence with anything time-critical.

**Guarantee: at-most-once, and the "success" is the company's, not the recipient's.** HA retries nothing. The
company's handler writes no row of its own unless it actually sends (W6 §3), so a refused or suppressed page
leaves no trace on either side.

### 2.5 `trigger: webhook` automations — the inbound direction, with no token

An automation declares `trigger: platform: webhook, webhook_id: …` and HA registers a webhook for it; the
automation then runs when that id is POSTed. This is the **only** way to make HA *do* something without
presenting a bearer token, which makes it the right shape for a fallback trigger (a "the company is alive"
ping, a dead-man's-handle from a host that holds no HA token).

**Current state: none exist.** `Select-String -Path config\*.yaml, config\packages\*.yaml,
config\automations\*.yaml -Pattern 'webhook_id'` returns nothing. So this capability is available and unused —
and by §2.1's finding, a caller still cannot tell whether its POST did anything.

---

## 3. What survives which failure

"Today" = no listener at all (the company is REST-only, synchronised, poll-driven:
`app/services/home_assistant.py:4-5` "All calls are HTTP-based (no websocket)"; `:120` `requests.get`;
`:32` `_HARD_CALL_TIMEOUT = 25`). The comparison columns assume the same listener code and differ only in
*where it runs*.

| Failure | Today (REST-only, no listener) | WS listener on the **authority** | WS listener on **zabz-tech-linux** |
|---|---|---|---|
| **company-api restart** | Nothing is lost that was ever captured — there is no capture. An in-flight REST call raises `ConnectionError`; the caller sees an exception. | Socket dies with the process. systemd `Restart=always`, `RestartUSec=10s` (`systemctl show company-api`) → ~10 s blind, then 105 ms to resubscribe. **Events in that window are lost** — no replay. What notices: the listener's own liveness row stops advancing; a supervisor sees `NRestarts` increment. | Same 10 s blind window; the *gap* is identical, because the gap is a property of HA's bus, not of the host. |
| **the shop desktop off** | **Total blindness.** The authority cannot reach `192.168.50.34` at all (measured, §1.3). Every HA read, every `call_service`, every maglock release fails. | **Same total blindness** — the listener's socket is through that desktop too. | **Events keep flowing.** linux-pc talks to the Pi on the LAN (40 ms, measured) and to the authority on the tailnet. What still dies: any *other* company code that uses `HA_URL` and therefore still goes through the desktop. What notices: `tailscale status` shows the peer offline; the desktop's absence is directly observable. |
| **network partition (both ends up, path broken)** | Nothing notices. W6 §4 established there is no heartbeat for any of this; `ha-watch` checks reachability every 30 min but nothing consumes the result as an alarm. | Socket closes (TCP), `onclose` fires, client reconnects with backoff. Gap lost. What notices: `onclose` in-process; nothing *outside* notices unless a heartbeat row is written and checked elsewhere. | Identical — partition is partition. The difference is only how many links can break. |
| **HA restart** | Any in-flight call fails; the next poll succeeds. `last_triggered` resets (handoff §9), so nothing about the restart is recorded. | All sockets drop. On reconnect the listener must **resubscribe and reconcile**: `GET /api/states` (73 ms, 468 KB) to resynchronise, because state changes during the restart were never emitted. What notices: the new socket's `auth_required`; on the bus, `homeassistant_start`. | Same, and the same reconcile is required. |

**Two facts that set the size of the HA-restart gap.** The Pi's uptime is **1 day 21 h** (`uptime` on the
host) against 8 days for `zabz-tech-linux` and 11 days for the desktop (booted 2026-10-15 19:49) — HA restarts
more often than anything else in the estate, which matches the handoff's "8 restarts in 28 days" (§9) and the
30-hour recorder hole (§8.4). And `homeassistant_v2.db` is **542.6 MB** on a 28.5 GB disk with 10.2 GB free
(63 % used), so recorder growth is a slow but real pressure on the same host.

**What is lost in every reconnect case, restated plainly:** HA's bus has no replay log. The only reconstructable
record is the recorder DB (state history, ~28 days per handoff §5.11), and only for entities the recorder does
not exclude — and it excludes two mmWave channels by config (handoff §9). So a listener gap is recoverable for
*state* by querying the recorder, and unrecoverable for *events* (a door that opened and closed inside the gap
leaves two state rows and no event).

---

## 4. Where the always-on listener should run

The candidates, measured. "Direct HA" means no dependency on the desktop.

| Host | CPU / RAM / disk | Uptime | Direct HA? | Supervision available | Evidence |
|---|---|---|---|---|---|
| `secratary-cloud` (authority) | 8 vCPU, 30 GB, `/` 225 G with **37 G free (83 %)** | — | **no** (unreachable, §1.3) | systemd; `company-api` `Restart=always`, `RestartUSec=10s`, `MemoryMax=21474836480`, `NRestarts=0` | `nproc`→8; `free -g`; `df -h /`; `systemctl show company-api` |
| `zabz-tech-linux` | 12 threads, 11 GB, **105 G free**, load 0.88 | 8 d 5 h | **yes — 40 ms** | systemd 255; Python 3.12, Node 22 | `nproc`→12; `df -h /`; `uptime`; `curl`→`HA 401 0.040745s` |
| `zabz-tech` (desktop) | — | 11 d (since 2026-10-15 19:49) | yes (it *is* the path) | Windows service / scheduled task | `(Get-CimInstance Win32_OperatingSystem).LastBootUpTime` |
| HA Pi itself (add-on / custom component) | 3.7 GB RAM (2.6 GB available), 28.5 G with 10.2 G free | **1 d 21 h** | local, zero network | HA add-on supervisor only — no systemd, no journal the company reads | `free -m`; `df -h /`; `uptime` |

**4.1 The authority's OOM history is real but is not the API's.** The brief warns of "OOM history under load",
and the kernel agrees in volume — 69 `oom-kill:` lines in 30 days — but the victim is overwhelmingly one batch
job, and `company-api` has never been killed:

```
$ journalctl -k --since '30 days ago' | grep -o 'oom_memcg=/system.slice/[a-zA-Z0-9_.-]*' | sort | uniq -c
     66 oom_memcg=/system.slice/transcript-archive-pull.service
$ journalctl -k --since '30 days ago' | grep -c 'oom_memcg=/system.slice/company-api'
0
$ systemctl show company-api -p NRestarts -p ExecMainStartTimestamp
NRestarts=0
ExecMainStartTimestamp=Mon 2026-10-26 03:22:44 UTC
```

A representative kill: `Killed process 54455 (python3) total-vm:9260160kB, anon-rss:6271796kB` in
`transcript-archive-pull.service` at 14:31, and again at 16:31 — a 6.2 GB job, killed by its own cgroup
(`constraint=CONSTRAINT_MEMCG`). So the authority is a noisy neighbour machine, not a machine that drops its
API. That weakens, but does not remove, the case against putting the listener there.

**4.2 The decisive point is not RAM — it is the single bridge.** A listener on the authority is behind the
desktop. A listener on `zabz-tech-linux` is not. Since the estate's entire HA event path is currently one
workstation, moving the listener is the only change in this whole area that removes a single point of failure
rather than adding one.

**4.3 But the listener's output must land locally in the authority's database.** `company-api` listens on
**loopback only**:

```
$ ss -lntp | grep 8002
LISTEN 0 2048 127.0.0.1:8002 0.0.0.0:* users:(("python",pid=3852236,fd=40))
$ (from linux-pc) curl http://100.73.176.126:8002/health  → api 000 0.014042s
```

So an off-box listener cannot post to the API over the tailnet today. Two ways to close that, in preference
order:

1. **A tailnet-only forward on the authority**, exactly the pattern already proven on the desktop:
   `tailscale serve --bg --tcp 8002 tcp://127.0.0.1:8002` — loopback origin, no new listener, reachable only
   from the tailnet, and the ingest endpoint keeps its own API key. This is the same mechanism whose behaviour
   is already characterised in §1.2 and measured at 18 ms.
2. The existing public tunnel (`https://ai.abletelsolutions.com`), which is what the HA `rest_command` uses and
   which was measured working (W6 §2.3: `200 OK` at 18:16Z). Rejected as the primary because it puts the
   public internet, Cloudflare and a DNS name inside a 5-second security path.

**4.3a The mechanism is already proven on that host, and nothing already does this job.** `zabz-tech-linux`
already runs a `tailscale serve` rule, so adding a TCP forward there is not a new pattern on that machine:

```
$ ssh linux-pc "tailscale serve status"
https://zabz-tech-linux.tail93e6e6.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:3086
$ ssh linux-pc "ss -lntp | grep 8123"   → none
$ ssh linux-pc "systemctl list-units --all --type=service | grep -iE 'homeassist|ha-bridge|ha-event'"  → (nothing)
```

And per this repo's rule 0 ("prove it does not already exist"), the register has no HA bridge to reuse:
`docs/mesh/000-SYSTEMS-REGISTER.md` mentions HA in no row — its only relevant row is the authority itself
(`:22`). Combined with §5.3 (nothing enqueues `source="home_assistant"`) and §2.5 (zero `webhook_id`s in the
HA config), the listener described here does not exist in any form today.

**4.4 Why not on the Pi.** It is the least available host in the estate by its own uptime (1 d 21 h vs 8 d),
it has the least headroom (2.6 GB available, 10 GB disk), and — the part that matters for an alarm — a failure
inside an add-on or a custom component is invisible from outside: there is no systemd unit to `is-active`, no
`NRestarts` to read, and no journal the company already collects. The company would be depending on the health
of the very box whose failure it is trying to detect. The Pi's correct role is to *emit* events, which it
already does well.

**4.5 Why not on the desktop.** It is the current single point of failure, it is a workstation (the owner logs
in, reboots and updates it), and putting the listener there concentrates both directions of the HA path on one
machine that is not managed as infrastructure. Its 11-day uptime is respectable but it is not a server.

**4.6 What supervises it, and what its failure tells you.** On `zabz-tech-linux`: a systemd unit with
`Restart=always`, `RestartUSec=5s`, a `MemoryMax` (Node/Python WS client is tens of MB; a cap makes an
unbounded-queue bug a restart instead of an OOM), and `After=network-online.target tailscaled.service`. Three
distinct failure signals, each meaning something different:

| Signal | What it actually tells you |
|---|---|
| unit `failed` / `NRestarts` climbing | the *process* is broken (code, TLS, auth) — HA is probably fine |
| unit `active` but no heartbeat row for N minutes | the *path* is broken (tailnet, LAN, proxy, HA restart) — this is the one that matters for security |
| `auth_invalid` in the log | the token was rotated or revoked — a credential event, not a network event |

The second row is the whole point: a listener that is running but receiving nothing is the exact failure mode
that produced "the pager has never run" (W6 F1). Liveness must be **absence-based** — a row that must keep
appearing — not a process check.

---

## 5. Queuing and delivery into the company database

### 5.1 What exists, and the one thing that is broken

`app/services/event_queue.py` is a SQLite-backed queue with priority, atomic claim, dedup key, exponential
backoff and a dead-letter state. It is good raw material and it is **not** at-least-once as written.

- **Dedup is global and permanent, but the code only upserts *pending* rows.** The schema declares
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedup ON events(dedup_key) WHERE dedup_key IS NOT NULL;`
  (`app/database.py:2478-2479`) — a unique index over the whole table. But `enqueue` looks only for a
  **pending** duplicate (`event_queue.py:98-102`), updates it in place if found (`:103-115`), and otherwise
  inserts. So the second time the same key arrives *after the first was processed*, the `INSERT` violates the
  unique index, falls into `except Exception: … return None` (`:145-147`), and the caller is told the same
  thing it is told when the database is down: `None`.

  This matters directly for HA: the natural dedup key is `(entity_id, time_fired)`, and a reconnect that
  re-reads recent state will re-present keys that were already processed. Today those are dropped — which is
  *almost* right — but the caller cannot distinguish "already have it" from "broken", so a retry loop either
  spins or gives up on real failures. Fixing it is small: `INSERT … ON CONFLICT(dedup_key) DO UPDATE`, and
  return the existing id with an `already_present` flag.

- **Ordering is destroyed by the claim.** `claim()` orders by `priority ASC, created_at ASC`
  (`event_queue.py:166-173`) and then re-sorts the batch the same way (`:186-189`). `created_at` is
  `datetime.now(timezone.utc).isoformat()` (`:43-44`, `:89`) — microsecond ISO strings from *multiple
  producers*, so it is neither monotonic nor globally ordered. A door `open` and a door `closed` 200 ms apart
  can be claimed in either order if their priorities differ. For security events the order is the meaning: a
  credential followed by a door-open is benign; the same two reversed is an alarm. So the queue must carry a
  listener-assigned monotonic `seq` and the *consumer* must order by `(entity_id, seq)`, not the queue by
  priority.

- **Backoff does not match its own comment.** Comment says "30s, 120s, 480s" (`:247`); the code computes
  `delay_sec = 30 * math.pow(2, attempts)` (`:248`) where `attempts` was already incremented at claim
  (`:165`), so the real sequence is 60, 120, 240, 480. Harmless, but it is the kind of thing that makes a
  retry timeline impossible to predict from the comment.

- **No replay API.** `complete()` sets `status='processed'` (`:195-210`) and nothing re-opens a processed row.
  `list_events()` is read-only (`:311+`). So "replay yesterday against a new rule" — which design Round 10
  requires for every threshold change — has to be a query over the tables, not a queue operation. That is fine,
  but it means the `events` table is the record of truth and the queue is only a transport; they should be
  distinguished in the schema rather than sharing one table.

### 5.2 What the drain actually costs you today

`app/autopilot.py:7113-7127`:

```python
wake_signals = wake.wait_or_timeout(1.0)
if wake_signals:
    logger.info("CEO woken by %d signal(s): …")
    self._process_event_queue()
```

**The queue is drained only when a wake signal arrives.** Otherwise nothing drains it in this loop; a P2/P3
event waits for the next autopilot tick. The running tick interval on the authority is **900 s**:

```
$ grep -E '^AUTOPILOT_INTERVAL' /opt/company/.env   → AUTOPILOT_INTERVAL_SEC=900
$ (default in app/config.py:955)                     → autopilot_interval_sec: int = 300
```

So the honest statement of today's latency for a queued HA event is **up to 15 minutes**, not "seconds". The
one thing that rescues it is that `POST /events` signals the wake system for priority ≤ 1
(`app/main.py:10212-10224`), which makes `wake_signals` non-empty and triggers an immediate drain. **That is the
lever:** a HA event must be enqueued at P0/P1, not P2. `claim(batch_size=10)` (`autopilot.py:7144`) bounds each
drain to ten, which is fine at ~1 event/s and not fine during a burst.

### 5.3 The routing layer is ready and one rule is dead

`app/services/event_router.py:108-124` already has the rules this design needs:

```python
RoutingRule(rule_id="ha_state_change", source_pattern="^home_assistant$", type_pattern="^state_change$",
            action="ha_security_check", actor="dept_home_life", …)
RoutingRule(rule_id="ha_alarm", source_pattern="^home_assistant$", type_pattern="^alarm_triggered$",
            action="ha_security_check", actor="dept_home_life", priority_override=0, …)
```

The P0 override already exists. What does not exist is a producer: nothing in the company enqueues with
`source="home_assistant"` (grep over `app/*.py` and `app/services/*.py` returns only `event_triage.py:139,296`
reading the string, and `trigger_engine.py:714` writing it in a rule that cannot fire — below).

And `trigger_engine._check_ha_security` cannot fire, exactly as W6 §3 says:

```python
ha = ctx.get("home_assistant", {})     # trigger_engine.py:691
doors = ha.get("doors", [])            # :692
if not is_night or not doors:          # :697
    return []
```

The only caller builds `{"world_context": <text>, "tick": n}` (W6 §3, `autopilot.py:6060-6067`), so `doors` is
always `[]` and the rule returns `[]` at `:697`. It is a rule with no input, not a rule with a bug — which is
why the security path has never produced a `goal_plans` row.

### 5.4 The shape that gets at-least-once, with dedup, order and replay

Only the pieces that do not exist yet are listed; everything else is reuse.

1. **Listener assigns the key and the sequence.** `dedup_key = sha1(f"{entity_id}|{time_fired}|{new_state}")`,
   `seq` = a per-listener monotonic counter persisted alongside the socket so it survives a restart. HA's
   `time_fired` is the only trustworthy timestamp; the listener's arrival time is not, because a reconnect
   delays it.
2. **Insert into `events` with `ON CONFLICT(dedup_key) DO NOTHING`, at priority 0 or 1.** Priority 0/1 is not
   cosmetic — it is what fires `ceo_wake.signal` and gets the queue drained in ~1 s instead of 900 s
   (`main.py:10212-10224`, `autopilot.py:7119-7127`).
3. **The listener acks to itself, not to HA.** HA will not retry, so the durable write must happen before the
   listener advances its own `seq` checkpoint. If the write fails, do not advance — replay from the checkpoint.
4. **Backfill the gap on reconnect, explicitly and visibly.** On `auth_ok` after a drop: `GET /api/states`
   (73 ms) to resynchronise current values, then mark the interval `[last_seq_time, now]` as a gap row so the
   record can say "events are missing here" rather than implying silence. This is the same principle as the
   `recorder_gap` marker the design already asks for (Round 11, "Disk full").
5. **Replay is a query, not a queue feature.** Because `events` keeps every row, a rule change is replayed by
   re-running the rules over `events` in `(entity_id, seq)` order. Keep `events` immutable and let
   `security_decision` be the derived table.

---

## 6. Latency, measured

Two vantage points, five samples each, same instant, over the two available paths.

**Through the tailnet proxy, from the authority** (`base: http://zabz-tech.tail93e6e6.ts.net:8123`), wall-clock
ms from a Node `http` client, `Authorization: Bearer <HA_TOKEN from /opt/company/.env>`:

| Request | min | p50 | max | bytes | codes |
|---|---|---|---|---|---|
| `/api/` | 17.4 | **18.2** | 67.8 | 26 | 200 |
| `/api/states` | 58.0 | **73.2** | 100.6 | 468,628 | 200 |
| `/api/states/binary_sensor.phoenix_control_room_interior_door_contact` | 16.1 | **16.9** | 18.3 | 413 | 200 |
| `/api/camera_proxy/camera.cam_waiting_room_main` | 796.1 | **1128.1** | 1789.1 | 204,870 | 200 |

**Direct on the shop LAN, from the desktop** (`base: http://192.168.50.34:8123`), same four requests:

| Request | min | p50 | max | bytes |
|---|---|---|---|---|
| `/api/` | 4.7 | **5.0** | 71.2 | 26 |
| `/api/states` | 20.8 | **21.8** | 34.1 | 468,634 |
| `/api/states/<one entity>` | 4.2 | **4.6** | 32.9 | 413 |
| `/api/camera_proxy/camera.cam_waiting_room_main` | 991.8 | **1646.1** | 2144.3 | 205,177 |

**Reading these numbers.**

- **The proxy costs ~13 ms fixed and ~50 ms on a 468 KB payload.** 18.2 − 5.0 and 73.2 − 21.8. That is a fair
  price; the chain is not slow.
- **`/api/states` is 468 KB and 73 ms.** Fine for a resync on reconnect, wasteful as a poll: polling it at 1 Hz
  to approximate real time means ~470 KB/s and ~1,037 entity diffs computed by the client every second. This is
  the concrete argument against "just poll faster" — the payload is the problem, not the round trip.
- **`camera_proxy` is 0.8–2.1 s for one 205 KB JPEG, on both paths.** It is dominated by the camera and the
  snapshot pipeline, not by the network — the LAN path is no faster than the proxied one. **This is the latency
  tail that breaks a 5-second budget if evidence capture sits on the event path:** the current sequence takes
  4 + 4 snapshots (W6 §5.5, `phoenix_intrusion_evidence.yaml`), which at these numbers is 7–17 s before the
  page is even attempted. Capture must be asynchronous and must never gate the decision or the page.

**WebSocket, from the authority through the proxy.** Ping RTT (HA's own `{"type":"ping"}` → `pong`):
`[15.7, 17.5, 17.5, 15.8, 16.7, 16.3, 15.6, 17.2]`, **p50 16.7 ms**.

Event delivery, measured without needing the two clocks to agree. For each event, compare the arrival-time
delta to HA's own `time_fired` delta: any queueing, buffering or proxy stall shows up as drift, and clock
offset cancels out.

```
events 43 in 45 s (0.96/s)
delivery drift  n=43  min 0  p50 9  p90 23  max 26 ms
```

**No queueing, no backlog, ≤26 ms of variation across 45 s.** So the transport delivers an event to a waiting
client in roughly one RTT plus HA's own dispatch — call it **≤ 20 ms** in this direction, with a drift bound
of 26 ms. Reconnect is 105 ms. There is no transport-level obstacle to a 5-second budget; there is roughly two
orders of magnitude of headroom.

*Measurement caveats, stated because they matter:* the absolute one-way delay cannot be pinned better than
±500 ms from the authority, because HA's only exposed clock reference is the HTTP `Date` header with 1-second
granularity (the offset samples came out −994, −774, −555, −311, −213 ms — consistent with a sub-second real
offset plus quantisation). The clock-free drift figure above is the defensible one. One earlier probe of mine
reported 0 events in 20 s; it differed from the working probe by sending ping frames before subscribing and I
could not reproduce the zero, so I discarded it rather than explain it — the 45 s/43 event and 40 s/26 event
runs are the ones used here.

---

## 7. The thing that actually decides the five seconds

The transport is not the problem and never was: 18 ms + 9 ms drift. The budget is spent elsewhere, and the
numbers say where:

| Stage | Cost today | Evidence |
|---|---|---|
| physical event → HA state change | sub-second (HA bus) | drift measurement, §6 |
| HA → agent transport | **~20 ms** (WS) | ping p50 16.7, drift p50 9 |
| agent enqueues at P2 instead of P0/P1 | **up to 900 s** | `autopilot.py:7119-7127`, `AUTOPILOT_INTERVAL_SEC=900` |
| agent enqueues at P0/P1 | ~1 s (wake + drain) | `main.py:10212-10224` |
| any synchronous evidence capture | **7–17 s** | 4+4 snapshots × 0.8–2.1 s, §6 |
| an LLM agent turn in the decision path | seconds to a minute | design Round 5, "An agent turn costs seconds to a minute" |
| `rest_command` with a dead endpoint | up to 15 s, then raises | `phoenix_security.yaml:357`, `rest_command/__init__.py:240-248` |

So "under ~5 seconds" is achieved by a design that (a) uses the WS push, (b) enqueues at P0/P1, (c) keeps the
model and the images off the path, and fails if any one of those three is missed — regardless of transport.

---

## Recommendation

**Transport: the Home Assistant WebSocket API, one long-lived client, `subscribe_events` for
`state_changed` narrowed by `subscribe_trigger` per security entity. Not webhooks, not MQTT, not polling.**

Why, in the three facts that decide it:

1. **A webhook cannot report failure.** HA returns `200 OK` for an unregistered id (`webhook/__init__.py:148`)
   and `200 OK` when the handler raises (`:196-199`), and the endpoint is `requires_auth = False` (`:216`). A
   200 therefore means only that a socket was opened. A transport whose success signal is uncorrelated with
   delivery cannot carry an alarm. The WS handshake, by contrast, reports `auth_invalid`, the subscription is
   acknowledged, and a broken path produces an `onclose` the client can act on — measured at 18 ms to auth and
   105 ms to resubscribe.
2. **The socket costs ~20 ms and loses nothing while connected.** Ping p50 16.7 ms; delivery drift p50 9 ms,
   max 26 ms over 45 s; backpressure is a bounded 4096-message queue that *disconnects* rather than dropping
   silently (`const.py:31`, `http.py:215-225`). Polling `/api/states` to fake the same thing costs 468 KB and
   73 ms per pass; the answer to "faster polling" is that the payload, not the round trip, is the obstacle.
3. **Where the listener runs decides availability, and the desktop must leave the path.** The Pi is not a
   tailnet node and the authority cannot reach `192.168.50.34` at all; the only bridge is a `tailscale serve`
   TCP forward owned by `tailscaled` on the owner's Windows desktop. A listener on the authority inherits that
   single point of failure. `zabz-tech-linux` is the only always-on host that reaches HA directly on the LAN
   (40 ms) *and* sits on the tailnet, with 105 GB free, systemd 255 and 8 days of uptime.

**Runtime: a systemd service on `zabz-tech-linux`** — `Restart=always`, `RestartUSec=5s`, a `MemoryMax`, and a
liveness row written on a fixed cadence. Its *absence* is the alarm, not its exit code. The service holds the
only HA socket, stamps each event with `dedup_key = sha1(entity_id|time_fired|new_state)` and a monotonic
`seq`, and writes them into the authority's `events` table at **priority 0 or 1** so `ceo_wake` drains them in
about a second instead of waiting for the 900-second tick. Replace the desktop's 8123 forward with an
equivalent `tailscale serve` rule on `zabz-tech-linux` so the agent's *callback* into HA stops depending on the
workstation too, and expose `company-api` to the tailnet only via `tailscale serve --tcp 8002 → 127.0.0.1:8002`
(it binds loopback today, so nothing off-box can reach it otherwise).

**Four things must be fixed in the existing machinery or the transport is wasted:**
- `idx_events_dedup` is a global unique index but `enqueue` only upserts `pending` rows, so a repeat after
  processing fails the insert and returns `None` (`database.py:2478-2479`, `event_queue.py:95-115`, `:145-147`).
  Use `ON CONFLICT DO UPDATE` and return `already_present`.
- Drain is gated on a wake signal (`autopilot.py:7119-7127`); P2 events wait for a 900-second tick. HA events
  must be P0/P1.
- `created_at` timestamps from multiple producers cannot order a queue; carry the listener's `seq` and order by
  it per entity.
- On reconnect, resync with `/api/states` and write an explicit gap marker. HA's bus has no replay
  (`commands.py:194`), so silence after a reconnect is ambiguous unless the record says so.

### Rejected alternatives

| Rejected | Why | What would change the answer |
|---|---|---|
| **REST webhooks as the event transport** | 200 on unknown id and on handler exception; unauthenticated; no retry; `local_only` is satisfied by anything on the tailnet because the proxy's private address passes `is_local` | Nothing realistic. It is the right tool for inbound *triggers* into HA, not for events out of it. |
| **MQTT** | broker exists (`app_core_mosquitto`, 0.0.0.0:1883) but is not forwarded on the tailnet; needs a second credential store on a broker already shared for the maglock; re-publishes HA's bus with less structure (no `old_state`/`new_state`/`context`) | If the estate ever needs fan-out to several independent consumers, or HA itself is not the source of truth for a signal. |
| **Polling `/api/states`** | 468 KB and 73 ms per pass; to approximate 1 s latency that is ~470 KB/s, and the client still computes 1,037 diffs itself | Never for latency; it *is* the right tool for the post-reconnect resync. |
| **Listener on the authority** | inherits the desktop as a single point of failure; the authority is also the noisy-neighbour box (69 OOM kills/30 d, 66 in `transcript-archive-pull`) — though `company-api` itself has never been killed (`NRestarts=0`) | If linux-pc cannot be given a supervised unit, or if the DB write must be in-process for transactional reasons that outweigh availability. |
| **Listener on the HA Pi (add-on / custom component)** | least available host by its own uptime (1 d 21 h), least headroom (2.6 GB available, 10.2 GB disk), and an add-on failure has no `is-active` and no journal the company reads — the alarm system would depend on the health of the box it is watching | If HA were moved to supervised hardware with the same monitoring as the rest of the fleet. |
| **Listener on the desktop** | concentrates both directions on a workstation that is already the single bridge; not managed as infrastructure | Only as a temporary bridge while linux-pc is being set up. |
| **`rest_command` as the event path** | at-most-once, blocks the calling script up to `timeout: 15`, raises `HomeAssistantError` on failure, and its 200 is the company's handler returning, not a page delivered | Keep it for the paging fallback and for actuator commands, never for the event stream. |

### What is still UNVERIFIED, and what would settle it

- **z2m's MQTT QoS for state topics** on this install. Settle it by reading `qos` in the Zigbee2MQTT add-on
  options on the host. Does not change the recommendation (§2.3 stands on route, credentials and structure).
- **Whether HA's IP ban is permanent.** `ban.py` writes bans to `/config/ip_bans.yaml` (`:47`) and
  `IpBan(remote_addr)` is created with no expiry argument (`:250-251`); the file is currently empty. Settle it
  by reading the `IpBan` dataclass. This matters operationally: with `ip_ban_enabled: true` and a threshold of
  5 (`configuration.yaml:16-17`), five bad-token attempts *from the proxy* would ban `192.168.50.138` and cut
  every cloud→HA path at once — a token rotation mistake becomes a total outage.
- **How often HA actually restarts, from the host journal** rather than inferred from uptime and the handoff's
  "8 restarts in 28 days". Settle it with `journalctl` in the HA container or the supervisor log.
- **Whether `tailscale serve` on the authority for port 8002 is acceptable to the estate's network policy.**
  It is loopback-origin and tailnet-only, but it is a new listener and the owner's policy on that is not mine
  to assume.
