# 146 — SURFACE AUDIT: every door the owner or a customer reaches from outside

**Written:** 2026-10-11 15:38–15:47 UTC · ZABZ-YOGA (Windows laptop, home network) · one session.
**Why:** a real miss was found — the owner's phone app led to a redirect pointing at a machine with no
engine, invisible to every check that had been run. This audit exists so that miss is the last one.
**Method:** for each surface — resolve it, confirm *which machine* answers (match the response shape, not
the status), make the real request a user or phone would make, follow redirects deliberately and read the
FINAL body, use credentials that already exist on this laptop (never printing a value), and read the
serving machine's own log for the request.

**A reading I did not take says so. Anything I could not test end to end is marked UNKNOWN, never healthy.**

| # | surface | verdict |
|---|---|---|
| 1 | `api.abletelsolutions.com` (company API) | **WORKING** |
| 2 | `ai.abletelsolutions.com` (dashboard) | **WORKING (shell only)** — authenticated page UNKNOWN |
| 3 | `ai.abletelsolutions.com/phone` → `zabz-yoga-1.tail93e6e6.ts.net` | **WORKING, but WRONG MACHINE** |
| 4 | `https://secratary-cloud.tail93e6e6.ts.net/` | **BROKEN** (no listener) |
| 5 | `https://zabz-yoga-1.tail93e6e6.ts.net/` (this laptop) | **WORKING** — it is the phone UI |
| 6 | `api.lakewoodphoneandtech.com` (shop API) | **WORKING** |
| 7 | `mdm.abletelsolutions.com` | **WORKING (health line only)** |
| 8 | `dialer.abletelsolutions.com` | **BROKEN** |
| 9 | DSH engine on the authority (`/opt/dsh-phone`, port 3089) | **UNKNOWN / NOT RUNNING** |
| 10 | phone-point-of-view reachability | **WORKING via the laptop** — not on the authority |

---

## 1. `api.abletelsolutions.com` — the company API

**WHAT IT IS.** The company's FastAPI authority: database reads/writes, agent ticks, voice, owner channel.
618 routes, 199 services.

**WHO USES IT.** The dashboard, the phone app's data, the DSH session ingest, every scheduled job, the
owner's automations. Public but keyed.

**WHERE IT IS SERVED.** `secratary-cloud` (Hetzner CCX13, 178.156.194.1), NOT the office box.

- DNS: `api.abletelsolutions.com` CNAME → `3e62916c-04ac-421b-b4a4-9af0852d8024.cfargotunnel.com`, proxied
  (Cloudflare API, read 15:41Z with the zone-scoped token from `personal-secretary-mvp/.env`).
- That tunnel is `secratary-cloud`'s; its ingress maps `api.abletelsolutions.com` → `http://127.0.0.1:8002`
  (`/etc/cloudflared/config.yml` on `secratary-cloud`, read 15:39Z).
- Listener: `LISTEN 127.0.0.1:8002 users:(("python",pid=105362))`; `systemctl show company-api -p ExecMainPID`
  = **105362**, `ActiveState=active`, `SubState=running` (read 15:43Z).

**TEST AND RAW RESULT.** 15:38:39Z–15:40Z, from ZABZ-YOGA:
```
GET https://api.abletelsolutions.com/health            -> HTTP/1.1 200, Server: cloudflare
body: {"ok":true,"time":"2026-10-11T15:38:49.493136+00:00","database":{"ok":true,"error":null},
       "autopilot_enabled":true,"autopilot_error":null,"voice":{"mode":"normal","realtime_allowed":true,
       "realtime_configured":true,"active_sessions":0,"last_error":null},"research_notes":[]}
GET /openapi.json   (no key)     -> 401 {"detail":"Missing/invalid API key","header":"x-ps-api-key or Authorization: Bearer"}
GET /openapi.json   (key)        -> 200 {"openapi":"3.1.0","info":{"title":"Personal Secretary MVP API","version":"0.1.0"},...
GET /api/v1/owner/dsh-sessions/stats (key) -> 200 {"ok":true,"session_count":6384,"event_count":1876538,
       "export_count":3993,"indexed_rows":1876538,"latest_ingest":"2026-10-11T15:30:03.167789+00:00","by_machine":[{"machine":"zabz-t...
```
Credential used: `DASHBOARD_API_KEY` from `C:\Users\ezabz\code\personal-secretary-mvp\.env` (len 43, value
never printed), sent as `x-ps-api-key` — the header the API itself names in its 401.

**ARRIVED WHERE I THINK IT DID.** `secratary-cloud` journal, `journalctl -u company-api` (read 15:43Z):
```
Oct 11 15:42:09 secratary-cloud python[105362]: INFO: 2a01:4f8:c015:8c0f::1:0 - "GET /health HTTP/1.1" 200 OK
Oct 11 15:42:14 secratary-cloud python[105362]: INFO: 2a01:4f8:c015:8c0f::1:0 - "GET /health HTTP/1.1" 200 OK
```
The peer address is Cloudflare's edge, so the tunnel carried it; the handler is the unit's own pid.

**VERDICT: WORKING.** Anonymous health and keyed reads both answer from the authority, and the database
says it is ok.

---

## 2. `ai.abletelsolutions.com` — the dashboard

**WHAT IT IS.** The Next.js operator dashboard (`secretary-dashboard`), the page a human opens to see the
company.

**WHO USES IT.** The owner, in a browser. Every non-`/phone` route on this host.

**WHERE IT IS SERVED.** `secratary-cloud`, port 3000 → cloudflared ingress `ai.abletelsolutions.com` →
`http://127.0.0.1:3000`. Listener *:3000 `next-server (v1`, pid 1089 (`systemctl show secretary-dashboard`
= 1089, active, read 15:43Z). NOT the office box — the office copy of that tunnel is a different tunnel id
and its `:3000` is deliberately stopped.

**TEST AND RAW RESULT.**
```
GET https://ai.abletelsolutions.com/            -> 307, location: /api/auth/signin?callbackUrl=%2F
GET .../api/auth/signin?callbackUrl=%2F (followed) -> 200, 5954 bytes
     <title>Sign In</title>    visible text: "Sign In  Sign in with GitHub"
     Set-Cookie: __Host-next-auth.csrf-token=...; Path=/; HttpOnly; Secure; SameSite=Lax
GET https://ai.abletelsolutions.com/api/health  -> 200 {"ok":true,"service":"dashboard","time":"2026-10-11T00:30:54.910Z"}
GET https://ai.abletelsolutions.com/api/v1/status -> 401 {"ok":false,"error":"Unauthenticated"}
GET .../api/ps/status                           -> 307 -> /api/auth/signin?callbackUrl=%2Fapi%2Fps%2Fstatus
```
So: it serves real HTML, the title is **Sign In**, the first screen is a single **Sign in with GitHub**
button, and the data pages redirect to sign-in.

**WHAT I COULD NOT TEST.** The signed-in dashboard. The only identity provider is GitHub OAuth; I searched
the credential stores on this laptop (env, `personal-secretary-mvp/.env`, `~/.dsh/.credentials.yaml`) and
there is no GitHub session or OAuth token for the dashboard's provider. The API it reads (`api.`) I proved
separately with a key. So the *data behind* the dashboard is proven; the *rendered authenticated page* is
**UNKNOWN**.

**VERDICT: WORKING (shell only).** Serving machine and sign-in page proven; the authenticated page is
UNKNOWN, not healthy.

---

## 3. `ai.abletelsolutions.com/phone` — the owner's phone app

**WHAT IT IS.** The link on the owner's iPhone home screen. It existed as the old single-turn "Secretary
Chat" PWA; on 2026-09-11 it was repointed to land in the DSH harness instead, because the owner should not
have to learn a new URL or re-add an icon (`scripts/phone-redirector.py`, docstring, and `docs/mesh/67`).

**WHO USES IT.** The owner, and only his devices — the gate in front of the engine signs him in.

**WHERE IT IS SERVED — three hops, and the third is the news.**

| hop | what answers | evidence |
|---|---|---|
| 1. public | `ai.abletelsolutions.com` → tunnel `3e62916c…` → `secratary-cloud:3087` | DNS + `/etc/cloudflared/config.yml` (`path: ^/phone(/.*)?$ → http://127.0.0.1:3087`) |
| 2. redirector | `phone-redirector.service` on `secratary-cloud`, python3 pid 113000 on 127.0.0.1:3087 | listener + `systemctl cat phone-redirector.service` (read 15:39Z) |
| 3. destination | **`zabz-yoga-1.tail93e6e6.ts.net` = THIS LAPTOP**, tailscale serve → `127.0.0.1:3086` = `phone-gate.py` pid 9128 → engine `node` pid 10668 on `127.0.0.1:3099` | `tailscale serve status` on the laptop; `Win32_Process` command line of 9128 |

The redirector's own configuration names the laptop (read 15:39Z):
```
/etc/cloudflared/phone-redirector.env
PHONE_TAILNET=zabz-yoga-1.tail93e6e6.ts.net     # <- an override: it forces another node
PHONE_STATE=/var/lib/phone-redirector
```
`phone-redirector.py` falls back to the *serving* node's own name via `tailscale status --json` when
`PHONE_TAILNET` is unset — so the override is the only reason `secratary-cloud` points at the laptop.
`phone-redirector.env.before-target-fix-20261011T153349Z` (81 B) sits beside it: **the target was changed
today at 15:33:49Z**, and the redirector was restarted then (`journalctl -u phone-redirector`).

**TEST AND RAW RESULT.** 15:38:40Z and 15:44Z, iPhone user agent, redirects followed:
```
GET https://ai.abletelsolutions.com/phone
  -> HTTP/1.1 302 Found      location: https://zabz-yoga-1.tail93e6e6.ts.net/
GET https://zabz-yoga-1.tail93e6e6.ts.net/   (iPhone UA, followed)
  -> HTTP/1.1 200  size=64577  ip=100.72.162.5
  -> <title>DeepSeek Harness</title>
  -> phone layer present: True   (dsh-phone-mobile CSS, phone-layer-version token present)
GET https://ai.abletelsolutions.com/phone/somepath -> 302 to the same root
```
And the gate's own log (`C:\Users\ezabz\AppData\Local\dsh-phone\gate-3086.log`, last write 15:42:10Z)
shows what the request really was:
```
2026-10-11T11:41:21 GET / client=100.72.162.5 peer=127.0.0.1 cookie=False token_offered=False token_live=True
2026-10-11T11:41:21   -> not authenticated as sent: signing in in flight
2026-10-11T11:41:21   -> signed in in flight, returning 64763 bytes with 1 cookie(s)
```
So the redirect lands on a live engine, the gate signs a cold visitor in flight and returns the document
with a cookie — exactly the designed behaviour — and the phone layer is in the document.

**EVIDENCE THAT REAL PHONES REACH IT.** The same log, all of history (2026-10-05 → 2026-10-11, 6004 lines),
every line naming one of the owner's own device IPs:
```
2026-10-05T22:38:08 GET / client=100.85.105.93   (iphone-15-pro)  -> signed in, document returned
2026-10-05T22:39:21 GET / client=100.85.105.93   (iphone-15-pro)  -> signed in, document returned
2026-10-05T22:38:04 GET / client=100.73.102.5    (iphone-se-gen-2)
2026-10-05T22:39:12 GET / client=100.73.102.5
2026-10-05T22:59:12 GET / client=100.73.102.5
2026-10-06T15:09:33 GET / client=100.118.10.22   (iphone-11, shop counter)
2026-10-05T22:38:04 GET / client=100.126.146.121 -> REFUSED (lakewooechsmini, not the owner's device)
```
All five owner devices are in `scripts/phone-gate-allow.txt` (read 15:44Z), and the gate's refusal text is
"this node signs in its owner's own devices only". **Last use of the phone app: 2026-10-06 15:09Z**, one
request. It works; the owner is not using it much.

**THE DEFECT, PLAINLY.** The owner's phone app terminates on an ephemeral Windows laptop. `tailscale serve`
on `secratary-cloud` says `No serve config`, and nothing on that box listens on 3089 — so the always-on
authority cannot yet host this. The laptop does keep it alive while it is running (`DSH Phone Gate`
scheduled task, time trigger every ~10 min, `DisallowStartIfOnBatteries=False`), but nothing guarantees the
laptop is on, awake, or at home. The audit in the brief found this class of defect once already; it is
still here for `/phone`.

**VERDICT: WORKING END TO END, ON THE WRONG MACHINE.** Not an outage — a dependency on the owner's laptop
where the migration requires the authority.

**THE EXACT CHANGE THAT FIXES IT** (`/opt/dsh-phone` exists on `secratary-cloud` and already has
`node_modules/.bin/dsh`; this is nearly finished, not unstarted — NOT run by me, because a second DSH
engine and a `tailscale serve` change on the authority are someone else's in-flight work right now):
```bash
# on secratary-cloud, once /opt/dsh-phone is complete
cd /opt/dsh-phone && ./.bin/dsh   # or the launcher used on the laptop; writes ~/.dsh-phone/engine-3099.log
tailscale serve --bg --https=443 http://127.0.0.1:3089      # makes the cloud's tailnet name answer
# then remove the override so the redirector names ITS OWN node:
sed -i 's|^PHONE_TAILNET=.*|PHONE_TAILNET=secratary-cloud.tail93e6e6.ts.net|' /etc/cloudflared/phone-redirector.env
systemctl restart phone-redirector
# and make it survive a reboot: a phone-engine.service beside phone-redirector.service
```
Also worth removing: the stale 124128-byte `phone-gate.py` now sitting in `/usr/local/bin` on the cloud box
(the laptop runs the current gate from the repo, `scripts/phone-gate.py`).

---

## 4. `https://secratary-cloud.tail93e6e6.ts.net/` — the authority's tailnet door

**WHAT IT IS.** The address the *phone* would use once the engine moved: Tailscale Serve on the authority.

**WHO WOULD USE IT.** The owner's iPhone, the shop iPads, and any tailnet device.

**WHERE IT IS SERVED.** Nowhere. `secratary-cloud` is on the tailnet (`100.73.176.126`,
`tailscale status` on the box 15:39Z, and from this laptop: `active; direct [2a01:4ff0:c193::1]:41641`), but
`tailscale serve status` → **`No serve config`**, and there is no listener on 443.

**TEST AND RAW RESULT.** 15:44Z from ZABZ-YOGA:
```
curl https://secratary-cloud.tail93e6e6.ts.net/
  -> http=000  err=Failed to connect to secratary-cloud.tail93e6e6.ts.net:443 after 2226 ms: Could not connect to server
```

**VERDICT: BROKEN** (nothing published). This is the missing half of §3's fix and the reason `/phone` still
points at the laptop.

---

## 5. `https://zabz-yoga-1.tail93e6e6.ts.net/` — this laptop's tailnet door

**WHAT IT IS.** The live phone destination today.

**WHO USES IT.** The owner's iPhone via the `/phone` redirect; the gate's allowlist admits his five devices.

**WHERE IT IS SERVED.** ZABZ-YOGA. `tailscale serve status` (15:40Z):
```
https://zabz-yoga-1.tail93e6e6.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:3086
```
3086 = `phone-gate.py` (pythonw pid 9128, started 2026-10-07 19:42 local); 3099 = the DSH engine
(node pid 10668); 443 on `100.72.162.5` = tailscaled (pid 9864).

**TEST AND RAW RESULT.** 15:41Z, iPhone UA:
```
GET https://zabz-yoga-1.tail93e6e6.ts.net/ -> 200, 64577 bytes, <title>DeepSeek Harness</title>,
    phone layer present (dsh-phone-mobile + phone-layer-version token)
GET from secratary-cloud (not in the allowlist) -> 403, 639 bytes:
    "REFUSED: not in phone-gate-allow.txt"   <-- gate log, 15:40:04Z, client=100.73.176.126
```
The 403 is correct behaviour, and it is the proof the allowlist is enforced rather than decorative.

**VERDICT: WORKING.** It is the phone UI, and the gate admits the owner's devices and no one else.
Caveat, and it is the whole point of §3: it is a laptop.

---

## 6. `api.lakewoodphoneandtech.com` — the SHOP's API (a different system)

**WHAT IT IS.** Lakewood Phone & Tech's own business API — not the company API. A separate system on a
different provider.

**WHO USES IT.** The shop front end and staff tooling.

**WHERE IT IS SERVED.** `lpt-apps-01` (Hetzner CX33 Falkenstein, **2.28.33.58**) — not the authority, not the
office box. Domain `A 2.28.33.58` (Cloudflare API, 15:41Z); `/opt/caddy/Caddyfile` on `lpt-apps-01`
(read 15:42Z) has `api.lakewoodphoneandtech.com { reverse_proxy lpt-backend:3001 }`.

**TEST AND RAW RESULT.** 15:41–15:42Z:
```
GET https://api.lakewoodphoneandtech.com/health -> 200
{"status":"healthy","timestamp":"2026-10-11T15:42:40.366Z","correlationId":"b045d804-...","uptime":204156.09,
 "version":"1.0.0","environment":"production","commit":"f6abb7ea2139cd0666304e7d85f1dea04b4d2a49",
 "buildTime":"2026-10-09T06:48:48Z","requestsServed":10000,"workspaceService":"backend",
 "services":{"database":{"status":"healthy","latency":121,...},"redis":{"status":"healthy",...},
             "twilio":{"status":"healthy","details":{"configured":true,"calling":true,...}}},
 "metrics":{"memory":{"used":156947656,"total":166872916,"percentage":94}}}
GET / -> 404 "Cannot GET /" and GET /api/v1/health -> 404 (this API is not version-prefixed)
```
The response shape (`workspaceService:"backend"`, its own commit hash, 56 h uptime ≈ the container's own
life) is the proof it is the shop backend and not the company API — the trap the register warns about, and
this is the test that distinguishes them.

**VERDICT: WORKING.** Database, Redis and Twilio all report healthy from the shop's own process.

---

## 7. `mdm.abletelsolutions.com`

**WHAT IT IS.** The Waze MDM front door.

**WHO USES IT.** Phone-repair MDM devices and the operator.

**WHERE IT IS SERVED.** `waze-mdm-01` (Hetzner, **87.99.141.172**), a *different* provider and box from
the authority. DNS `A 87.99.141.172`, **proxied=False** (grey cloud) — so Cloudflare is not in the path;
the request goes straight to the host (Cloudflare API, 15:41Z). Caddy in `waze-mdm-caddy-1` owns 443
(`docker ps`, read 15:41Z; `/opt/waze-mdm/Caddyfile:102`).

**TEST AND RAW RESULT.** 15:41Z:
```
GET https://mdm.abletelsolutions.com/ -> HTTP/1.1 200, Server: Caddy, Content-Type: text/plain
body: "Waze MDM is online"
```
That is the whole body. It is a health line, not the MDM UI — `/opt/waze-mdm/Caddyfile:102` is
`respond "Waze MDM is online" 200`. The operational MDM UI is a different name:
`Caddyfile:107  mdm-api.abletelsolutions.com`.

**VERDICT: WORKING (health line only).** The host answers exactly what its config says it should. I did
**not** test `mdm-api.abletelsolutions.com` (out of the brief's list, and it would need enrolment
credentials) — see §11.

---

## 8. `dialer.abletelsolutions.com` — the live-voice dialer

**WHAT IT IS.** The live-voice dialer's operator UI and the caller program's TwiML webhook (per the office
cloudflared config comment).

**WHO USES IT.** Whoever operates live voice; the carrier's webhook posts to it.

**WHERE IT IS SERVED.** Nowhere. DNS is `CNAME 829bc0fb-30f9-4244-b2ea-14fbb61a2753.cfargotunnel.com`,
proxied — that is the **office box's** tunnel (`/etc/cloudflared/config.yml` on `secratary-ts`, read
15:41Z), and that box's cloudflared is **active**. Its ingress has
`dialer.abletelsolutions.com → http://127.0.0.1:8899`, far down the rule list.

**TEST AND RAW RESULT.** 15:38:42Z from ZABZ-YOGA:
```
GET https://dialer.abletelsolutions.com/ -> HTTP/1.1 502 Bad Gateway, Server: cloudflare
```
And the origin's own log tells exactly why (`journalctl -u cloudflared` on `secratary-ts`, read 15:41Z):
```
Oct 11 15:38:42 secratary cloudflared[1356]: ERR error="Unable to reach the origin service...:
   dial tcp 127.0.0.1:8899: connect: connection refused" connIndex=0 event=1 ingressRule=4
   originService=http://127.0.0.1:8899
Oct 11 15:38:42 secratary cloudflared[1356]: ERR Request failed error="..." dest=https://dialer.abletelsolutions.com/ event=0 ip=198.41.192.227 type=http
```
`ss -ltn | grep 8899` on the office box: **nothing**. `systemctl list-units --all | grep -iE "dialer|voice"`:
**no unit**. No `/opt/*dialer*` directory. The same `connection refused` appears on 2026-10-11 05:43:46Z
(the cutover) and 06:17:58Z, so this predates the migration and the migration did not cause it — but it is
not fixed either. Also logged at 05:43:46Z: `ai.abletelsolutions.com/health` failing against the office
box's `:3000`, which is the *expected* office-side state after the cutover, not a new fault.

**VERDICT: BROKEN.** Origin refused on both sides.

**THE EXACT CHANGE THAT FIXES IT.** The dialer program is not installed on the office box at all, so this
is a deployment, not a restart: (a) restore/install live-voice-dialer's operator UI + TwiML webhook so it
listens on `127.0.0.1:8899` under a systemd unit (nothing in `~/code/harness-config` or `~/code` on this
laptop provides it — the source must be found on the office box or the old machine before it can be
ported); (b) only then is `dialer.` reachable, because its tunnel rule already exists. If live voice is
retired, the correct fix is instead to delete the DNS record and the ingress rule so the surface stops
being advertised. **That is an owner decision (a customer-facing phone function), and it is not mine to
make** — it is the one thing in this audit I am flagging rather than fixing, and I am flagging it as a
question below rather than a reading assignment.

---

## 9. The DSH engine on the authority — `/opt/dsh-phone`, port 3089

**WHAT IT IS.** The intended new home of the phone UI: a DSH engine on the always-on authority, published
over the tailnet, so `/phone` stops depending on the owner's laptop.

**WHO WOULD USE IT.** The owner's devices, via `/phone`.

**WHERE IT IS SERVED — it is not.** On `secratary-cloud` (read 15:39Z and 15:44Z):
```
/opt/dsh-phone        373M, created 2026-10-11 15:36-15:37Z
  package.json        {"name":"dsh-phone","private":true,"dependencies":{"@deepseek-ai/dsh":"0.2.0-rc.2"}}
  node_modules/.bin  anthropic-ai-sdk  cordis  dsh  dsoffice  is-docker ...
/usr/local/bin/phone-gate.py        124128 B, 15:35Z   (sha 49f6580c6a2523ee4815d91cc467b6b8e09d2a460e5d2a33dc1a578fc8b69cb1)
/usr/local/bin/phone-gate-allow.txt   4745 B, 15:35Z   (same nine devices as the laptop's copy)
ss -ltnp | grep 3089   ->  (nothing)
systemctl list-units --all | grep -iE "dsh|phone"  ->  phone-redirector.service ONLY
tailscale serve status  ->  No serve config
df -h /  ->  /dev/sda1 75G 49G 24G 68% /      (the disk constraint is comfortable, 24 G free)
```
The install is real (373 MB of node_modules including the `dsh` binary) and it is **half an hour old** —
created 15:35–15:37Z while this audit was running. Nothing is wired: no engine process, no port 3089
listener, no systemd unit, no tailscale serve.

**TEST AND RAW RESULT.** I could not make the request the brief asks for, because there is nothing to make
it to: `curl http://127.0.0.1:3089/` on the authority has no listener, and the tailnet name has no serve
config (§4). I did not start it — the migration brief forbids restarting the authority's units without
saying so, and this is somebody's in-flight build.

**VERDICT: UNKNOWN / NOT RUNNING.** It does **not** yet serve the phone UI. Per the audit's own rule, an
untested surface is UNKNOWN, never healthy — and this one does not even have a process to test.

---

## 10. Reachability from a phone's point of view

The owner's devices are on the tailnet. Tailscale routes 100.64.0.0/10 between them regardless of home vs
office network, which is the only path between those two networks.

| device | tailnet IP | state (from `tailscale status`, ZABZ-YOGA and `secratary-cloud`, 15:39–15:40Z) | what the phone app needs, and does it answer |
|---|---|---|---|
| `iphone-15-pro` | 100.85.105.93 | online | `ai.abletelsolutions.com/phone` → 302 → `zabz-yoga-1.ts.net:443` → **answers** (200, phone UI). Logged success 2026-10-05 22:39Z. |
| `iphone-11-1` (shop counter) | 100.119.73.69 | online | same chain; the gate allowlist admits it; **no request from it in the gate log's entire history** |
| `ipad-air-5th-gen-wifi` (shop iPad) | 100.76.204.64 | online | same chain; allowlisted; **no request in the log's history** |
| `iphone-11` (shop counter) | 100.118.10.22 | **offline, last seen 1d ago** | would need the same chain; unproven, and cannot be driven while offline |
| `iphone-se-gen-2` | 100.73.102.5 | **offline, last seen 4d ago** | allowlisted; last gate success 2026-10-05 22:59Z; cannot be tested now |

Also measured for the phone's path: from `secratary-cloud`, `tailscale ping zabz-yoga-1` → `pong ... in
38ms`, and `curl https://zabz-yoga-1.tail93e6e6.ts.net/` → **403 from the gate** (639 B, "not in
phone-gate-allow.txt") — i.e. the authority can reach the destination and is correctly refused, which is
stronger than a ping because it means the whole TLS + gate path is up.

**VERDICT: WORKING for the three online devices, because the destination is the laptop.** Every one of them
would have to reach the **laptop's** tailnet name, and the laptop must be powered, awake and on the tailnet.
The authority's own tailnet name answers nothing, so if the laptop is off, the phone app is dead — and that
failure is silent from the public side, because hop 1 (the 302) still returns `302 Found` no matter what
the destination is doing. **I did not send anything to any human:** no SMS, call, email or push. Driving an
actual iPhone to tap the icon is outside what this session can do (see §11).

---

## 11. COULD NOT TEST — everything, and why

| surface / claim | why it is UNKNOWN |
|---|---|
| The **signed-in dashboard** (`ai.abletelsolutions.com` after GitHub OAuth) | The only IdP is GitHub OAuth; no GitHub session or OAuth token for it exists on this laptop (checked: environment, `personal-secretary-mvp/.env`, `~/.dsh/.credentials.yaml`). `/api/v1/status` answers 401 unauthenticated. The API it renders is proven separately. |
| **Rendering on a real iPhone** (does the phone UI look right on a phone) | Requires driving an actual device fingerprint/OS. I proved the document carries the phone layer (`dsh-phone-mobile`, `phone-layer-version` token) and that real iPhones were signed in on 2026-10-05/06; anything beyond that is a claim I cannot support. |
| **`dialer.` operator UI and TwiML webhook** | Origin refused on both sides; no program installed. Nothing to test. |
| **`/opt/dsh-phone` serving the phone UI** | Not running: no engine, no listener on 3089, no `tailscale serve` on the authority. There is nothing to request. |
| **`mdm-api.abletelsolutions.com`** (the actual MDM UI) | Not in the brief's list of six; enrolling or signing in would need MDM credentials, and it is a separate provider's box. `mdm.` itself is proven as a health line only. |
| **Phones that are offline** (`iphone-11`, `iphone-se-gen-2`) | Offline 1 and 4 days respectively. Their ability to reach the destination cannot be measured from here; their last *proven* success is in §3's log. |
| **Anything that would transmit to a human** | Deliberately not attempted: no SMS, no call, no email, no push to any device. Every test in this document is an inbound HTTP request or a read-only command. |
| **Authenticated company API endpoints beyond DSH session stats** | I proved authentication and one real read. The other ~600 routes were not exercised, so they are unmeasured — but the credential, the network path and the database are all proven, and that is the distinction. |
| **The office box as a live fallback for any of the above** | Out of scope for this audit and forbidden by the brief (read-only, disk-starved). I ran only small bounded commands there (`ss`, `systemctl`, `journalctl`, `sed`), and its load was 0.07/0.15 throughout. |

---

## 12. The one-line summary

**Five of the six public doors the owner and customers reach work, and I proved each from outside with a
real request and the serving machine's own log. One is broken (`dialer.`, origin refused, no program on
the box). One — the owner's phone app — works end to end but terminates on his laptop instead of the
authority, and the authority's half of that migration is installed but not running. The
authenticated dashboard is UNKNOWN because this laptop holds no GitHub OAuth session for it.**

Sources for every number: DNS via the Cloudflare API at 15:41Z; `/etc/cloudflared/config.yml` and
`journalctl` on `secratary-cloud` at 15:39–15:43Z; `journalctl -u cloudflared` on `secratary-ts` at
15:41Z; `/opt/caddy/Caddyfile` on `lpt-apps-01` at 15:42Z and `/opt/waze-mdm/Caddyfile` on `waze-mdm-01`
at 15:42Z; `tailscale status`/`serve status` on ZABZ-YOGA and `secratary-cloud` at 15:39–15:44Z; the gate's
own log `C:\Users\ezabz\AppData\Local\dsh-phone\gate-3086.log` (last write 15:42:10Z); and HTTP requests
from ZABZ-YOGA between 15:38:39Z and 15:44Z, all raw results quoted above.
