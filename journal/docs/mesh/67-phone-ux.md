# 67 — The iPhone path, end to end, and the smallest set of changes that makes it work

**Written:** 2026-09-16 21:40–22:05 UTC · ZABZ-YOGA (Windows laptop, home network) · one of 8 parallel
mesh agents; this is the only file this session wrote.
**Scope:** the owner's iPhone 15 Pro (`iphone-15-pro`) reaching a DSH engine on a *desktop* node, and
Phase 1's single acceptance test: *take the phone, open a session that lives on a desktop node, start a
fleet in it, and watch the laptop stay flat.*

**Every number below carries its source and the date/time it was read.** A reading I did not take says
so. Anything I could not verify is listed in §7 rather than smoothed over.

## 0.0 Provenance, and a warning about revision drift

`scripts/phone-gate.py` **changed twice while this document was being written.** Two revisions matter:

| Revision | Size | sha256 | Read at |
|---|---|---|---|
| **A** — the one the brief pointed at | 40,206 B, 919 lines | not taken | full read, 21:45Z |
| **B** — the one now live and tested here | 48,008 B, 1,058 lines | `0ed2b027af9ad51d95fdb1810b9ac4fa5d76415ffb74e1df9cfa4536c616ff5b` | full read of `handle`/`main`/`live_token`/`rewrite_authority`, 21:58Z |

*(Source: `Get-Item` on `C:\Users\ezabz\code\harness-config\scripts\phone-gate.py`, and `certutil -hashfile`
on the same file on ZABZ-TECH, 21:56:5xZ. The hash is **identical on both nodes** — the desktop's copy is
the laptop's copy, so the Windows publish path is not running a different gate.)*

Revision B is another agent's in-flight work (it appeared at 21:48:06Z with `rewrite_authority()` and
`--engine-authority`; the file grew again at 21:53:44Z with `--log-file` and a multi-directory token
search). **Everything I describe below is revision B unless it says otherwise; every measurement was
taken against revision B running.** §1 names the delta from A, because the brief described A.

---

## 1. `scripts/phone-gate.py`, function by function

It is a **raw TCP relay, not an HTTP proxy** (`phone-gate.py:133-163`, `relay()`; docstring at the top of
A:15-18). It inspects the *first* request on each connection and then becomes a pipe — which is why the
WebSocket upgrade survives untouched and nothing about the RPC protocol is reimplemented.

### 1.1 What it does, in order (revision B, `handle()` at :854)

| Step | Lines | What it actually does |
|---|---|---|
| read the request head | :876-881, `read_request_head` :809 | up to `BUF*8` (512 KB) or until `\r\n\r\n` |
| **present a different authority** | :885, `rewrite_authority` :179 | if `--engine-authority` is set, **every** upstream request gets `Host:` and `Origin:` rewritten to it. `Origin` is rewritten to `http://<authority>`; an absent `Origin` is left absent |
| parse the target | :887-897 | splits the request line on whitespace (A:773-776 records the bug where `partition(" ")` made the gate match nothing and silently relay for a day) |
| decide if this is a document | :898 | `GET`/`HEAD` on `/` or `/index.html` |
| read the engine's live token | :901, `live_token` :81 | **only for a document request** |
| log the decision | :906-908, `note` :780 | method, path, `cookie=`, `token_offered=`, `token_live=`, proto. **Never the token.** Writes to stdout *and*, with `--log-file`, to a file |
| three routes it answers itself | :915-938 | `/dsh-phone-mobile.css` (`mobile_stylesheet_response` :387), `/dsh-attention.js` (:637), `/dsh-attention.json` (:582) — all **without auth**, deliberately (styling and one-line check names, no credentials; a badge that needs a cookie vanishes on exactly the cached document it exists to fix) |
| cold-visitor sign-in | :943-951 | `needs_token` is true when there is no cookie *or* the offered token is not the live one; then `complete_login()` |
| proxy or buffer | :953-981 | documents are **buffered** (`read_all`), everything else is relayed byte-for-byte |
| second chance at sign-in | :968-975 | if the engine answers a document request **401**, sign in in flight and return the document instead |

### 1.2 How a cold visitor is signed in (`complete_login` :289)

Not by redirecting. The measured reason (A:198-205, and this is the whole design): any shape that asks the
*client* to follow a redirect to `/?token=` can be looped by a client that keeps a bad cookie — **50 hops
and a curl abort** were measured on 2026-09-11. So the gate does the exchange itself:

1. `GET <path>?token=<live>` to `127.0.0.1:<engine-port>` over **loopback**, with the rewritten `Host`;
2. keep the `Set-Cookie` the engine answers (303) and discard the client's stale one;
3. re-fetch the document with that cookie;
4. return the document to the client **with `Set-Cookie` injected** — one response, no redirect chain, no
   token in the URL or browser history, and no loop that can be constructed.

The client's `Origin` is irrelevant to this exchange because it never leaves the gate. This is also why
the gate defeats the two things that break every other shape on iOS: **a Home Screen Web App has no
address bar** in which to paste `?token=…`, and it has its own cookie jar (§5.3).

### 1.3 Where it reads the engine's startup token (`live_token` :81)

- **Exact port first**: for each directory in `ENGINE_LOG_DIRS` it tries `engine-<port>.log`, then
  `<port>.log`, then the newest `<port>-*.log` — and takes the **last** `token=([A-Za-z0-9_-]+)` in the
  file it finds.
- `ENGINE_LOG_DIRS` (:48-52) = `~/.dsh/multi-window/logs`, then `~/.dsh-phone`, then
  `%LOCALAPPDATA%\dsh-phone`.
- Where the laptop's token actually is: `C:\Users\ezabz\.dsh\multi-window\logs\3099.log`, **82 bytes,
  written 2026-09-16 15:49:37 local** — the multi-window launcher's log for the engine pid 1784. I read it
  (token present, 43 chars, never printed).
- **This was the Windows bug in revision A.** A used `STATE_DIR = Path.home()/".dsh-phone"` only; the
  Windows launcher writes to `%LOCALAPPDATA%\dsh-phone`, and the multi-window launcher writes to
  `~/.dsh/multi-window/logs`. On Windows the gate therefore found **no token at all** and a cold visitor
  got the engine's plain-text 401. Revision B fixes it.

### 1.4 What it does about `Host` and `Origin`

| | Behaviour |
|---|---|
| Host | **Preserved by Serve, and preserved by the gate when `--engine-authority` is unset** (revision A behaviour, still the default). With `--engine-authority 127.0.0.1:3099` it is **rewritten** to that value on everything the gate sends upstream |
| Origin | Rewritten to `http://<engine-authority>` when one was present; **not invented** when absent |
| The client's own headers | Untouched for the three routes the gate answers itself |
| Does the gate itself refuse a foreign Host? | **No.** It never inspects Host for trust. `docs/mesh/20-placement.md` §3.3 item 4 says it does — that is wrong, and I corrected it here: the **engine's fence** is what refuses, and the gate's job is to decide what the engine is allowed to see |

### 1.5 Failure modes, stated plainly

| Failure | Where it shows | Evidence |
|---|---|---|
| Engine not started with `--trusted-host` **and** no `--engine-authority` | every `/api` → **403**, documents still 401/200 | measured 21:47:02Z on this laptop |
| Stale cookie + no live token readable | 401 plain text, which iOS offers as a download | A:4-8 |
| Gate process dies | Serve answers **502**, nothing else | measured 21:49:13Z–21:52:5xZ (§3.1) |
| `--log-file` omitted and no inherited stdout | decisions are lost; the process is invisible | :1023-1026 |
| Two engines on one `DSH_HOME` | session-log corruption | `multi-window/windows.json:5` |
| A `tailscale serve` reconfig while a tailnet client is connected | that connection ends | reasoned from `serve` semantics; not separately measured |

### 1.6 What is platform-specific, and what must change for Windows

**The logic is already portable.** `select.select` on sockets, `socket.create_connection`, threads with
`daemon=True`, and byte-level parsing are all fine on Windows; there is no `fork`, no signal handling, no
`fcntl`, and no `/proc`. Measured today: revision B **ran on Windows** and served a real document, a
stylesheet, an authenticated RPC and a WebSocket upgrade (§3.4). Specific points:

| Concern | macOS/Linux | Windows | Status |
|---|---|---|---|
| token location | `~/.dsh-phone/engine-<port>.log` (systemd redirects there) | `%LOCALAPPDATA%\dsh-phone\engine-<port>.log` (old launcher) and `~/.dsh/multi-window/logs\<port>.log` (the real launcher) | **fixed in B** (:48-52) |
| `tailscale` on PATH | yes | yes — `tailscale.exe` answers `status --json` | measured 21:47Z |
| keeping it alive | `phone-engine.service`/`phone-gate.service` (systemd, `/system.slice/`) | **nothing** — a scheduled task exists as a script but is not installed | §3.2, §6 item 2 |
| starting it detached | `setsid nohup`, or a unit | `Start-Process` inherits the caller's stdout and dies with the caller's process tree; the current workaround is a generated `.vbs` run by `wscript` | `scripts/phone-gate-ensure.ps1:120-142` |
| line endings / encoding | — | reads logs with `encoding="utf-8", errors="replace"`; writes CRLF-terminated HTTP itself | no change needed |
| shebang `#!/usr/bin/env python3` | used | ignored — invoked as `python.exe phone-gate.py` | no change needed |

---

## 2. The trust problem, solved concretely

### 2.1 What the fence actually checks (read from the shipped code)

`@deepseek-ai/dsh-client-connection/lib/index.js`, `isTrustedApiRequest` **:201-215**:

```
Host must be loopback OR match a trustedHosts entry   (:206)
sec-fetch-site: cross-site  -> refuse                 (:207)
Origin, when present, must have .host === Host's host (:208-211)
```

and `requestRejection` **:554-555** turns that into **403**, then `BrowserAuth.isAuthenticated` **:431-441**
turns a missing/wrong-authority cookie into **401**. The README (§"Browser authentication and request
trust") states the same, including the two facts the whole design turns on: *"A failed Host/Origin check
returns 403, while a trusted but unauthenticated request returns 401"* and *"An attached `Origin` must
equal that Host"*.

**The index route is not fenced.** `authorizeIndex` (:386-425) is called by the static frontend without
`requestRejection`, which is why `/` answers 401 (not 403) on an untrusted Host while `/api` answers 403.
I confirmed both this asymmetry and the cookie shape live (§3.3).

### 2.2 Measured: the four probes that decide the fix

All against the running engine **pid 1784** (`node …bin.js web --port 3099 --no-open`, started
2026-09-16 15:49:10 local, i.e. **no `--trusted-host`**), 21:48–21:49Z, `curl.exe`:

| # | Request | Result |
|---|---|---|
| A | `POST /api/session/list`, `Host: 127.0.0.1:3099`, no `Origin` | **401** — fence passes, only auth missing |
| B | same + `Origin: https://zabz-yoga-1.tail93e6e6.ts.net` | **403** — *this is why rewriting Host alone is not enough* |
| C | same + `Origin: http://127.0.0.1:3099` | **401** — rewriting Origin works as well as dropping it |
| D | `Host: zabz-yoga-1.tail93e6e6.ts.net`, no `Origin` | **403** — the tailnet name is genuinely untrusted by this engine |

### 2.3 Option (a) — restart the engine with `--trusted-host`

```powershell
# ONE engine per DSH_HOME. Never a second one (multi-window\windows.json:5).
$bin = "$env:LOCALAPPDATA\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js"
node $bin web --port 3099 --no-open --trusted-host zabz-yoga-1.tail93e6e6.ts.net
# then the phone must do ONE token exchange on that authority:
#   open  https://zabz-yoga-1.tail93e6e6.ts.net/?token=<token printed at startup>
tailscale serve --bg 3099
```

Proof it worked: `curl -s -o NUL -w '%{http_code}' http://127.0.0.1:3099/api -H 'Host: zabz-yoga-1.tail93e6e6.ts.net'`
→ **401** (was 403), and through the tailnet `/api` → 401.

**Cost, and it is the decisive cost: this ends every live session on that node.** `--trusted-host` is a
**startup** setting (`dsh-web-app` argues it at launch; `dsh-client-connection:739-757` reads it as
plugin config, and the profile patch's `trustedHosts: !!js ctx.webRuntime.trustedHosts` is applied at
boot). Restarting kills every open WebSocket and every turn in flight in every window on that machine —
and on this laptop one of those sessions is the one doing the work. It also **widens** the engine's trust
surface: after it, any process that can reach :3099 with `Host: zabz-yoga-1.tail93e6e6.ts.net` is inside
the fence. On a loopback-only bind that is not a large exposure, but it is strictly more than today.

**So: (a) cannot be applied without ending the owner's live sessions. No.**

### 2.4 Option (b) — put the gate in front, presenting loopback

```powershell
# on the node (this is what phone-gate-ensure.ps1 -Publish runs), 3086 -> engine 3099:
python scripts\phone-gate.py --listen-port 3086 --engine-port 3099 `
       --engine-authority 127.0.0.1:3099 `
       --log-file "$env:LOCALAPPDATA\dsh-phone\gate-3086.log"
tailscale serve --bg 3086
```

`rewrite_authority()` (:179-232) rewrites **both** `Host:` and `Origin:` on everything the gate sends
upstream. The fence then sees the authority it already trusts (`127.0.0.1:3099`), so:

* **the engine is untouched** — pid 1784 keeps running, no launch flag changes, **no live session ends**;
* the fence stays **closed** to the network name — measured control at 21:57:5xZ:
  `curl http://127.0.0.1:3099/api -H 'Host: zabz-yoga-1.tail93e6e6.ts.net'` → **403**;
* **only `tailscale serve`'s target changes** (3099 → 3086). That reconfig affects the tailnet path only;
  the owner's windows are at `127.0.0.1:3099` and are not in it.

**The Origin question, answered:** the gate must **rewrite or drop** it. Probe B above is the proof —
Host alone turns every *browser* POST into a 403 while `curl` stays green, which is exactly the shape of
bug that made earlier phone work look finished. Revision B rewrites it to `http://<engine-authority>`;
`https:` vs `http:` does not matter because the fence compares `new URL(origin).host`, not the scheme.

**The cookie question, answered:** the cookie the engine mints is
`dsh-auth-<base64url(sha256(authority))>` — the **name itself** is authority-derived
(`cookieName` :280, `sessionCookie` :292-293). Rewriting to loopback therefore mints a cookie *named for
loopback* and hands it to a browser whose origin is the tailnet name. That is fine and is why the
exchange must use the same rewritten authority end to end; the browser stores it **host-only** under the
tailnet origin (`Domain` is absent) and sends it back on every request, and the gate presents the same
loopback authority again. Verified independently: I computed `base64url(sha256(authority))` in python and
it matches the served cookie names for both authorities —
`127.0.0.1:3099` → `dsh-auth-3BwAN0JzQ…`, FQDN → `dsh-auth-L3C5muENT…` (21:55:54Z, values never
printed).

### 2.5 Recommendation

**Option (b), the gate, and it is not close.** Three reasons, in order of weight:

1. **It is the only option that signs a cold visitor in.** A home-screen Web App has no address bar and
   its own cookie jar (§5.3), so a `?token=` URL is not something the owner can type there. Option (a)
   plus a cold visit is a 401 dead page; option (b) returns the document and the cookie in one response.
2. **It ends nobody's sessions.** `--trusted-host` ends all of them, every time it is applied.
3. **It keeps the fence closed.** No network name ever enters `trustedHosts`.

Both can be *tried* without an engine restart only in the (b) sense; (a) is by construction a restart. And
(b) is already implemented and already answering on both nodes as I write (§3.4).

---

## 3. What I tested from here, and exactly what I saw

### 3.1 The live state moved under me — timeline (all UTC, 2026-09-16)

| Time | Reading | Source |
|---|---|---|
| 21:47:02Z | `serve status` → laptop `/ -> http://127.0.0.1:3099` (straight at the engine). `GET /` → **401** plain text; `GET /api` → **403**; `POST /api/session/list` → **403** | `curl.exe`, `tailscale serve status` |
| 21:48:14Z | a gate appears on 3086 (pid 19592), serve re-pointed to 3086. Log: `signed in in flight, returning 54698 bytes with 1 cookie(s)` | `%LOCALAPPDATA%\dsh-phone\gate-3086.log` |
| 21:49:00Z | through the tailnet: `/assets/index-BKQ_L1z6.js` **200**, `/manifest.webmanifest` **200** `application/manifest+json`, `/` **200** (signed in in flight), `/dsh-phone-mobile.css` **200, 25,894 B** | same log + my `curl` |
| **21:49:13Z–21:52:5xZ** | **`GET /` and `GET /api` → 502 Bad Gateway. Nothing listening on 3086.** The gate had died, twice (pid 19592 after serving; pid 7248 printed only its banner at 21:49:45Z). `gate-3086.err` = **0 bytes** both times | `curl.exe`, `Get-NetTCPConnection`, the log, `~/.dsh-sync-status/phone-gate.json` |
| 21:52:47Z | `phone-gate-ensure.ps1` recorded `result=attention`, `"the gate did not come up on 3086"`; `Get-ScheduledTask 'DSH Phone Gate'` → **NOT installed** | `~/.dsh-sync-status/phone-gate.json`, `Get-ScheduledTask` |
| 21:56:4xZ | ZABZ-TECH is **published**: `https://zabz-tech.tail93e6e6.ts.net (tailnet only) |-- / proxy http://127.0.0.1:3086`, its engine on `127.0.0.1:3099` (pid 23188, LISTENING) | `ssh desktop-ts` |
| **21:57:21Z** | **laptop, end to end through the tailnet name: `GET /` → 200 with `Set-Cookie`; `/api` → 401; WS upgrade with the cookie → 101** | `curl.exe` |

### 3.2 The gate dies on Windows and nothing restarts it

Revision A's `main()` is an infinite `accept()` loop and the banner proves the import succeeded, so a gate
that prints its banner and then vanishes with a **0-byte stderr** was **killed, not crashed**. The same
file, same python, ran fine on the desktop minutes later — so it is not the code. `phone-gate-ensure.ps1`
already documents this ("a nested `pwsh -File …` whose `Start-Process` started the gate never returned —
the tool running it hit its 120 s ceiling and killed the whole process tree, taking the gate with it") and
tries to escape it by launching through `wscript`/VBS. **That did not work either**: pid 7248 was started
by exactly that VBS (`%LOCALAPPDATA%\dsh-phone\phone-gate-3086.vbs`, arguments correct:
`--listen-port 3086 --engine-port 3099 --engine-authority 127.0.0.1:3099`) and died the same way.
*Inference, not measurement:* a detached child is still inside the runner's job object, so a job-object
tree kill takes it regardless of `wscript`, `Start-Process` or `NoNewWindow`. The durable answer is a
supervisor that is not a descendant of the agent's process tree — a **scheduled task**, which is written
(`scripts/Install-PhoneGate.ps1`) but was **not installed** at 21:52:47Z.

### 3.3 The engine, directly (no gate, no tailnet) — 21:55:54Z

| Request | Result |
|---|---|
| `GET /?token=<live>`, `Host: 127.0.0.1:3099` | **303**, `location: /`, `set-cookie: dsh-auth-3BwAN0JzQ…; Max-Age=2592000; Path=/; Expires=Fri, 16 Oct 2026 21:55:54 GMT; HttpOnly; SameSite=Strict` |
| same, `Host: zabz-yoga-1.tail93e6e6.ts.net` | **303**, same attributes, **different cookie name** (`dsh-auth-L3C5muENT…`) — the authority binding, proven |
| `?token=WRONG` | **401** |
| `?token=<live>` on `/api` | **401** (the token is accepted only on `GET /`) |
| `?token=<live>&token=<live>` | **401** (exactly one token parameter, per :392) |

**Cookie attributes, as served:** `Max-Age=2592000` (30 days) · `Path=/` · `Expires` 30 days out ·
`HttpOnly` · `SameSite=Strict` · **no `Secure`** · **no `Domain`** (host-only). This matches
`sessionCookie()` :292-293 exactly, and the two README limitations are live here: *"the browser cookie is
not marked `Secure`"* — so the bearer token would be exposed if the same authority were ever reached over
plaintext (it is not: Serve is HTTPS-only) — and there is **no logout operation**.

### 3.4 The whole path through the tailnet name — 21:57:21Z–21:58Z (the acceptance-relevant reading)

```
GET https://zabz-yoga-1.tail93e6e6.ts.net/
    HTTP/1.1 200 OK
    Cache-Control: no-store          <- the gate's own framing (reframe(..., no_store=True))
    Content-Length: 54512            <- de-chunked and re-framed, not the engine's chunked body
    Content-Type: text/html; charset=utf-8
    Set-Cookie: dsh-auth-<sha256(127.0.0.1:3099)>=<redacted>; Max-Age=2592000; Path=/;
                Expires=Fri, 16 Oct 2026 21:57:21 GMT; HttpOnly; SameSite=Strict
```

* the document **carries the phone layer**: `<style id="dsh-phone-mobile">` present, badge loader present,
  `dsh-plugin-mobile` present, `phone-layer-version: 2026-09-16.3`;
* `GET /dsh-phone-mobile.css` → **200, 25,769 B, `text/css; charset=utf-8`**;
* `GET /dsh-attention.json` → **200, `application/json`**;
* `POST /api/session/list` **with the cookie the gate just handed back** → **HTTP 200**, body
  `{"type":"server-response","rpcId":"probe-1","result":{"ok":false,"error":{"code":"gateway/internal",…}}}`
  — the gateway *parsed and dispatched* it (my payload shape was wrong; 200 is the point, not the error);
* `POST /api/session/list` **without a cookie** → **401**;
* WebSocket upgrade `GET /api/remote.mux` **with the cookie** → **`101 Switching Protocols`**;
  **without it** → **401**;
* control: the engine refuses the same tailnet Host directly → **403**.

**Redirect behaviour of a cold visit: there is none, and that is the design.** Through the gate, `GET /`
is answered **200 in one response** with the cookie attached. Without the gate (Serve straight at the
engine) it is **401 plain text** — which iOS offers as a download — and the only way in is
`GET /?token=<live>`, which is **303 → `location: /`** and **discards every other query parameter**.

### 3.5 The transport underneath (21:47Z–21:56Z)

| Reading | Value |
|---|---|
| FQDN resolution from the laptop | `zabz-yoga-1` → 100.72.162.5 · `zabz-tech` → 100.85.153.96 · `secratary` → 100.84.72.88 — all resolve (`Resolve-DnsName`) |
| `tailscale ping zabz-tech` | **pong via 71.104.140.242:41641 in 169 ms** — a **direct** path (an `ip:port` here means direct; a relayed path says `via DERP`) |
| `tailscale ping secratary` | **pong via 71.104.140.242:3270 in 206 ms** — direct |
| `tailscale status` | `zabz-tech` `active; direct …:41641`; `secratary` `active; direct …:3270`; **`lakewooechsmini` `active; relay "nyc"`**; `zabz-tech-linux` idle |
| Serve on the laptop | `/ -> http://127.0.0.1:3086` (tailnet only) |
| Serve on the desktop | `/ -> http://127.0.0.1:3086` (tailnet only) |
| Desktop engine | `127.0.0.1:3099` LISTENING (pid 23188); python present (`python` → Python 3.13.5, `py` → 3.13.14) |

The home→office hop is **direct**, not DERP, at ~170–206 ms — that is the latency the phone pays per
round trip, and it is why the client must be a viewer that reconnects rather than something that holds
state in the socket (§5.2).

---

## 4. Session deep-linking: `https://<node>.tail93e6e6.ts.net/#session=<id>`

### 4.1 Was such a plugin ever shipped? No.

* **In this repo:** zero hits for `location.hash`, `hashchange`, `#session=`, `popstate`, `pushState` in
  `packages/` (the six client plugins) — `plugin-mobile/lib/client.js` reads no fragment, and its only URL
  work is `ensureStylesheet()`/`keepLayerCurrent()` on `/dsh-phone-mobile.css`.
* **In the installed preset** (`~/.dsh/profiles/web/package.json`, bundles = `dsh-base`, `dsh-web-app`,
  `dsh-plugin-cost`, `-windows`, `-mobile`, `-attention-badge`, `-health`, `-attention`): no session-link
  plugin. All six package junctions point at `harness-config/packages/*`, so what is in the repo is what
  loads.

### 4.2 Does the client already read a fragment or a query parameter? Read the code: no, with one caveat.

I scanned **317** client bundles (`@deepseek-ai/*/lib/client.js` + `dist/assets/*.js`, read 21:57Z):

| Pattern | Hits | What they are |
|---|---|---|
| `location.hash` | **0** | — |
| `hashchange` | 3 | React's own discrete-event list (`case"hashchange":…`) in the vendored bundles, not a listener |
| `URLSearchParams(location` | **1** | `dsh-client-connection/lib/client.js` — `fixtureOptionsFromLocation()`, which reads `?fixture=`, `?fixturePrompt=`, `?fixtureAttach`… **a test-fixture transport**, not session selection |
| `dsh.sessions.current` | 1 | the session controller's persisted selection |

Session selection is `localStorage["dsh.sessions.current"]`, read once at page load
(`dsh-api-session-controller/lib/client.js` ~:3058-3060). So the earlier conclusion
(`00-RESEARCH.md` §6) stands for the *shipped* client:

> Deep-linking a session is not possible today, on any device.

**Two things that follow, and one that is new:**

* a **path** route is a 404 (no SPA catch-all), and a **query** parameter cannot survive the `?token=`
  exchange, which 303s to the literal `/` (`authorizeIndex` :401-406). The **fragment** is the only
  position the client keeps;
* **new, and it changes the calculus:** with the **gate** in front there is **no redirect at all** on a
  cold visit (measured: one 200, §3.4), so a fragment survives even the *first* visit. Without the gate,
  a cold visitor is redirected and the fragment is lost.

### 4.3 The smallest change that makes it work: one client plugin, ~30 lines

The service and the call both exist. `Sessions` is provided to the client as
`rootCtx.reflect.provide("sessions", this)` (`dsh-api-session-controller/lib/client.js:3087`), it exposes
**`open(id)`** (:3093-3095, which calls `manager.select(id)`), and a plugin consumes it the way
`dsh-client-ui-conversation` does — declare the dependency, then read it —
`inject: [..., "sessions"]` plus `this.ctx.get("sessions")` (same file, `requireSessions()`).

```
packages/plugin-session-link/
  package.json          { "name": "dsh-plugin-session-link" }
  lib/index.js          host half: inert, exactly like plugin-mobile/lib/index.js
  lib/client.js         read location.hash, wait for the id, call sessions.open(id)
  cordis.patch.yml      - insert: [{ id: plugin-session-link, name: dsh-plugin-session-link }]
  install.sh            exec bash scripts/install-client-plugin.sh "$HERE" "$1"   (already generic)
```

Client half, in outline: parse `#session=<id>` at boot → `exports.inject = ['sessions']` → poll/await the
projected list (the same "list is loading" state the UI already handles) → `sessions.open(id)` → clear the
fragment with `history.replaceState` so a reload does not fight the owner's later click. If the id never
appears, leave the default selection and say so in one line — **never a blank window**. The delivery path
needs no invention: `scripts/install-client-plugin.sh` already does the two things a client plugin
requires (resolve by name from the profile dir, and appear in `dsh.profile.bundles`), and it is idempotent.
**Measured trap to respect:** reaching a service without declaring it in `inject` refuses the plugin at
activation — *"cannot get property slots without inject"* — which is the exact failure the repo already
paid for once (`packages/plugin-cost/lib/client.js` ~:377-419).

Whether this is *needed* for Phase 1's acceptance test depends on the reading: picking the session from
the drawer needs no plugin; "open **that** session" needs it.

---

## 5. The phone itself — an iPhone 15 Pro

### 5.1 What the served PWA actually declares (read from the installed package, 21:52Z)

`~/.dsh/profiles/node_modules/@deepseek-ai/dsh-web-frontend/dist/manifest.webmanifest`:

```json
{ "id": "/", "name": "DeepSeek Harness", "short_name": "DSH",
  "start_url": "/", "scope": "/", "display": "fullscreen",
  "icons": [ { "src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any" } ] }
```

and `dist/index.html`'s whole head: `charset`, `<meta name="viewport" content="width=device-width,
initial-scale=1" />`, `<link rel="manifest" href="./manifest.webmanifest" />`, `<link rel="icon" …>`,
title, and the bundle tags.

**What that means for iOS, concretely:**

| Thing | Reading | Consequence |
|---|---|---|
| `display: "fullscreen"` | not `standalone` | Apple's documented iOS mode is **`standalone`**; `fullscreen` is a manifest mode whose iOS behaviour I did **not** verify. If iOS ignores it, the home-screen icon opens **with** Safari chrome — still usable, just not app-like |
| no `apple-mobile-web-app-capable` meta | absent | the legacy switch that made icon-opens-chromeless on older iOS is not set; there is no fallback path |
| no `apple-touch-icon` | absent | iOS uses a screenshot of the page as the icon |
| no `theme-color`, no `background_color` | absent | white/unspecified splash and status bar; cosmetic only |
| one **SVG** icon, `sizes: any`, `purpose: any` | SVG only | iOS home-screen icons want a PNG (180×180 is the usual size); an SVG may be ignored → screenshot icon |
| `start_url: "/"`, `scope: "/"` | correct | the whole app is in scope, so links stay inside the Web App |
| `viewport-fit=cover` | **absent** | `env(safe-area-inset-*)` evaluates to **0** on iOS, so `assets/mobile.css`'s insets (:222-328) are inert there. A real, measured-in-code gap — and an easy fix (§6 item 5) |

### 5.2 Backgrounding, sleep, and a suspended renderer

* **What I did not measure on the device, and will not claim:** I have no iPhone here. The claim in
  `00-RESEARCH.md` §9 — the renderer is suspended and TCP dropped after **~5 s** in the background, and a
  deliberately-closed `EventSource` will not resume from `Last-Event-ID` — is a **read-from-docs** claim
  (WebKit bug 282526 and an SSE-patterns article, cited there), not a measurement of this app.
* **What follows from the code I did read:** the client is built for exactly that. The Connection
  generation has a jittered retry ladder (500 ms, 1 s, 2 s, 4 s, 8 s, then a 10 s cap), `offline` aborts
  active work and suspends attempts, and the next `online` **resets the ladder to the 500 ms tier**
  (`dsh-client-connection/README` §"Connection generation"). So the phone re-attaches by itself within
  roughly one ladder step of coming back; worst case ~10 s if iOS never fired `offline` while suspended.
* **Nothing on the server stops.** The turn runs in the engine on the node; the phone is a viewer. This is
  the property that makes the iPhone viable at all, and it is why the acceptance test's "start a fleet and
  put the phone in your pocket" is sound.
* **Sleep/lock:** a locked phone is a backgrounded app — same story. The visible symptom is a transcript
  that is stale for a few seconds after unlock, then catches up from the journal when the generation
  reopens.

### 5.3 Home-screen Web App: its own cookies and storage — and why the gate makes that harmless

Apple's own session (*"What's new in web apps"*, WWDC 2023 session 10120) states it plainly: on
iOS/iPadOS, `display: standalone` **"opens as a Home Screen Web App with isolated cookies and storage,
separate from the browser"**; cookies from Safari are **copied at creation**, **localStorage is not**.

Applied here:

* **Auth survives** — the session cookie is an `HttpOnly` cookie (not localStorage), and it is copied when
  the Web App is created. Even if it were not, **the gate mints a fresh cookie on the first request**, so
  the isolated jar is refilled automatically on the very first launch. This is the decisive practical
  advantage over option (a), where the Web App would get a 401 and have no address bar in which to paste
  `?token=…`.
* **The session selection does not survive** — `dsh.sessions.current` lives in **localStorage**, which is
  not copied. So the first launch of the Home-Screen app lands on a default/empty selection and the owner
  picks from the drawer. That is precisely the §4 argument for the fragment plugin: a home-screen app has
  no address bar, so a `#session=` link is the only way to arrive *at a session* on it.
* Apple's recommendation — keep auth in cookies, not localStorage — is already what the harness does, by
  construction.

### 5.4 Touch targets, viewport, and the injected layer

The layer is delivered and verified (§3.4: style tag + stylesheet route + `phone-layer-version:
2026-09-16.3`). Its own measurements, read from `assets/mobile.css`:

* every primary control **≥ 44 px** (`min-height/min-width: 44px`, :63-98) and text fields forced to
  `font-size: 16px` so iOS does not zoom on focus (:111);
* the drawer is off-canvas with a 44×44 pinned toggle (:296-299);
* **the `env(safe-area-inset-*)` rules are inert on iOS** because the served document's viewport meta has
  no `viewport-fit=cover` (§5.1). On a notched iPhone that means the top-left drawer toggle sits at a flat
  `14px` from the top edge and the composer can sit under the home indicator. The CSS is right; the
  document it lands in is missing one token.

### 5.5 Does the tailnet have to be up on the phone for any of this? Yes.

The URL is a MagicDNS name (`.tail93e6e6.ts.net`), and `tailscale serve`'s config lives in the daemon's
state: with the tailnet down the name **does not resolve at all** and nothing answers on it
(`docs/mesh/50-transport.md` §2.1, and the same effect measured on this laptop when its daemon was found
stopped on 2026-09-16). On the iPhone that means **the Tailscale app must be connected** (it is a VPN
extension, so it stays up in the background once enabled). The engine, the gate and the work are
unaffected by the phone's state — the phone simply cannot see them.

---

## 6. The smallest set of changes that makes the acceptance test pass

The test: *phone → a session on a desktop node → start a fleet in it → the laptop stays flat.*
Ordered by dependency. Each line names the file, who can do it, and the command that proves it.

**1. A gate in front of the desktop node's engine, presenting loopback.** — `scripts/phone-gate.py`
(`--engine-authority`) + `tailscale serve`. **Both nodes already satisfy this** (measured 21:57:21Z on the
laptop, 21:56:4xZ on the desktop). Owner: nobody. Proof:
`curl -s -o NUL -w '%{http_code}\n' https://zabz-tech.tail93e6e6.ts.net/` → **200**;
`…/api` → **401** (not 403); and the control
`curl -s -o NUL -w '%{http_code}\n' http://127.0.0.1:3099/api -H 'Host: zabz-tech.tail93e6e6.ts.net'`
(still **403** pins the fence closed). *Shape of the "me" work here: none — it is running.*

**2. Keep that gate alive on Windows.** — `scripts/Install-PhoneGate.ps1` (registers the `DSH Phone
Gate` scheduled task: at logon + every 5 min, running `phone-gate-ensure.ps1 -Publish`). **Who: me.**
Currently **NOT installed** (21:52:47Z) and the gate died twice today (§3.2), so this is the single
highest-value remaining item on the Windows side. Proof: `Get-ScheduledTask -TaskName 'DSH Phone Gate'`
→ `Ready`; then kill the gate process and within ≤5 min
`Get-NetTCPConnection -LocalPort 3086 -State Listen` is non-empty again, with
`~/.dsh-sync-status/phone-gate.json` showing `"result": "repaired"`.

**3. Point the phone at the desktop's URL, once.** — nothing to install. Owner: **the owner** (only he can
touch the phone; Tailscale app connected, open `https://zabz-tech.tail93e6e6.ts.net/`, optionally Add to
Home Screen). The gate signs him in with **no token in the URL**, which is what makes it work from a
home-screen icon. Proof: the session list renders on the phone; and from any node, a *cookie-less* request
returns 200 + `Set-Cookie` (measured 21:57:21Z).

> **Expect one extra click the first time, and do not read it as a failure.** The desktop's FQDN is a
> **new origin** on his phone, and the workspace/session selection is per-origin localStorage, read once at
> page load. A device whose origin has no stored selection can show the "Choose workspace" row until one is
> picked — the known first-run gap in `docs/dsh-mobile/02-SYSTEMS.md` §7 (P46: a session created outside
> the workspace picker has a directory but no membership, and the app resolves
> `workspaceId ?? currentWorkspaceId ?? recent`). His phone does not hit it on `secratary` because that
> origin has history; it can on `zabz-tech` the first time. One tap, then it never appears again on that
> node. *(Not measured on a phone — reasoned from the code path named in 02-SYSTEMS §7.)*

**4. Open the session, by click or by link.** A click in the drawer needs nothing. "Open *that* session"
needs the fragment plugin of §4.3 — `packages/plugin-session-link/*` plus the bundles list in
`~/.dsh/profiles/web/package.json`, installed by `scripts/install-client-plugin.sh`. **Who: me.**
Proof: `https://zabz-tech.tail93e6e6.ts.net/#session=<id>` lands on that session; with the plugin
disabled, the same URL lands on the default and the fragment is cleared.

**5. One token to make the safe-area rules real.** — `scripts/phone-gate.py`, one more injection next to
`inject_mobile`/`inject_badge`: rewrite/insert the viewport meta as
`width=device-width, initial-scale=1, viewport-fit=cover`. **Who: me.** Proof:
`curl -s https://zabz-yoga-1.tail93e6e6.ts.net/ | grep -c 'viewport-fit=cover'` → 1, and on the phone the
drawer toggle no longer sits at a flat 14 px from the top edge. *(Alternative, if the gate is ever out of
the path: the same one-liner in `packages/plugin-mobile/lib/client.js`.)*

**6. Run the acceptance test itself, and measure the laptop, not the phone.** No new file: on the laptop
take a baseline, then start the fleet **in the desktop's session from the phone**, then re-read.
Suggested probes — laptop: `(Get-Process node | Measure-Object WorkingSet64 -Sum).Sum/1GB`,
`(Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average`, and this engine's
own `engine_health` (event-loop lag / free memory); desktop: the same plus process count. **Who: me**, with
the owner only to hold the phone. Proof: the desktop's node/process count and commit rise, the laptop's
stay flat, and the transcript on the phone shows the fleet's turns as they stream.

**7. (Only if the fleet itself has to be started *by* the phone from a cold, locked device.)** The
turn lives server-side, so nothing is needed. If the phone is expected to observe the fleet **after** a
long lock, the existing 500 ms→10 s reconnect ladder already covers it; no change.

**Nothing in this list requires restarting any engine, and therefore nothing in it ends a live session on
either node.**

---

## 7. What I could not verify, and where I could be wrong

1. **Anything on the actual iPhone.** No device here. The iOS-specific claims in §5 are either read from
   the served files (manifest, index.html, mobile.css), read from the client code, or read from Apple's
   own session (cited). Specifically **not** verified: whether iOS honours `display: "fullscreen"` from
   the manifest; whether the home-screen cookie jar really is isolated on this iOS version; the ~5 s
   background suspension.
2. **That a fragment survives a *real browser* cold visit through the gate.** I proved there is no
   redirect (200 in one response) and that the shipped client reads no fragment; the retention is then
   arithmetic, not a measurement on a browser.
3. **`sec-fetch-site` under a real browser.** The fence refuses only `cross-site`, and a page at the
   tailnet origin fetching the tailnet origin sends `same-origin` — but I sent no browser header. If a
   future client fetches the gate's `/api` from a *different* origin (e.g. a localhost harness window),
   the browser will send `cross-site` and get **403** by design.
4. **Whether the current gate survives.** It is revision B, another agent is editing it, and it has died
   twice today. Everything in §3.4 is a snapshot at 21:57:21Z.
5. **The 502 window's exact start.** I saw 200s at 21:49:00Z and 502s at 21:49:13Z; the death is bounded
   between those, not pinned.
6. **`tailscale serve` surviving a reboot.** Not measured (`50-transport.md` §2.1 flags the same gap).
   Until it is, a rebooted node may be silently unpublished — which is one of the reasons item 6.2 exists.
7. **Wrongness I already found and corrected in place:** `20-placement.md` §3.3 item 4 says the gate
   "refuses a foreign Host" — it does not, and never did; it is the engine's fence. The gate's real
   security property is different and better: it decides what the engine sees, and the fence stays closed.

---

## 8. For the record: three corrections to the earlier documents

* **`docs/mesh/50-transport.md` §2.1** proposes adding `--trusted-host <node FQDN>` to each node's primary
  launcher. That works, and it costs every live session on the node. The gate with
  `--engine-authority 127.0.0.1:<port>` reaches the same end with **no engine change, no restart, and the
  fence still closed**, and it is the only shape that signs a cold visitor in. §2.5 of this file supersedes
  it; `phone-gate-ensure.ps1` and `Install-PhoneGate.ps1` implement the superseding shape.
* **`docs/mesh/20-placement.md` §3.3** says the gate "refuses a foreign Host": corrected above.
* **`docs/dsh-mobile/00-RESEARCH.md` §6** — *"Deep-linking a session is not possible today, on any device.
  Don't design around it."* Still true of the shipped client, and the reason given (the token exchange
  discards the query) is exactly right. What changed tonight is that **the gate removes the redirect**, so
  the fragment now survives even a cold visit — which makes the §4.3 plugin sufficient rather than
  theoretical.

---

## 9. What was built after this report (2026-09-16 22:00–22:10Z, ZABZ-YOGA)

Items 5 and 4 of §6 are no longer proposals. Everything below was run, and the readings are the ones I
took, not the ones I expected.

### 9.1 Item 5 — the iOS head, shipped and live in `phone-gate.py`

`inject_head()` + `head_metas()` + `_viewport_fixed()` + `manifest_response()`, wired into the existing
`inject_all()` and a new self-answered `/manifest.webmanifest` route — so they sit beside the stylesheet
and badge injections and follow their kill-switch idiom: **`PHONE_HEAD=0`** turns off the whole section,
`PHONE_STATUS_BAR_STYLE` overrides the status-bar value with a validated fallback.

**Served bytes, quoted from the gate running the finished file** (`GET https://zabz-yoga-1.tail93e6e6.ts.net/`,
22:06:5xZ, 54,839 B):

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<!-- dsh-phone-head -->
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#fff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#151517" media="(prefers-color-scheme: dark)">
```

and the manifest: **200**, `application/manifest+json`, 266 B, `"display": "standalone"`, icons left as
the shipped SVG. Regression check in the same minute: `/dsh-phone-mobile.css` **200 / 25,769 B**,
`/dsh-attention.json` **200**, `/api` without a cookie **401**, and the fence control (tailnet Host
straight at the engine) still **403**.

In-process checks on the same file: injection is **byte-identical on a second pass**; a document that
already carries its own `theme-color` keeps exactly one; a document with no `</head>` is returned
unchanged; `PHONE_HEAD=0` returns the document and the manifest untouched.

**Two things deliberately NOT done, with the reason in the code:** no `apple-touch-icon` (iOS rejects an
SVG for that rel and this repo's only PNGs are app screenshots — the real fix is a PNG upstream), and no
`theme_color`/`background_color` in the manifest (iOS ignores both; its splash comes from
`apple-touch-startup-image`, and a single-valued manifest field cannot track the OS colour scheme the way
the two `<meta>` tags do).

**`apple-mobile-web-app-status-bar-style` is `default`, not `black-translucent`, and that is a refusal to
guess.** `black-translucent` is what makes `env(safe-area-inset-top)` non-zero — and it draws the status
glyphs in white over whatever the page paints, so on a light harness theme the clock and battery become
invisible. Nobody here can see the owner's phone to check. `default` cannot produce that defect and still
gives the bottom inset (the composer clearing the home indicator), which is the inset the layer needs
most. One env var flips it once someone has looked.

### 9.2 Item 4 — `packages/plugin-session-link/`, written, not installed

Four files, the minimum the convention defines (`packages/<name>/` + `package.json` +
`cordis.patch.yml` + `lib/index.js` + `lib/client.js`, exactly as `plugin-mobile` and
`plugin-attention-badge` are shaped): `dsh-plugin-session-link`. A single file cannot be a bundle — the
loader resolves a package **by name** from the profile's `node_modules` and reads its manifest for the
patch and the client entry — so "one new file" is one new package.

`scripts/install-client-plugins.ps1 -Check` (read-only, 22:08Z) reports it as
`dsh-plugin-session-link  MISSING  not mounted (repo-only; -RequireAll to install)` and exits **0** — the
package is discoverable by the installer and deliberately **not** installed into `~/.dsh`. `node --check`
passes on both halves, and all four loader-facing fields (`main`, `exports["./client"]`,
`dsh.bundle.patch`, `dsh.client.platform`) resolve on disk.

**The logic was tested without an engine**, by loading `lib/client.js` in a `vm` sandbox with a stubbed
loader/`window`/`sessions` service and collapsing the retry ladder — **11 of 11 checks pass**: no fragment
→ completely inert; session present → `open(id)` once, one info line, fragment cleared; list settled
without the id → **nothing selected**, one line, fragment cleared; list never settles → best-effort
selection at the deadline plus one line; service never appears → one line, no throw; an unrelated fragment
(`#tab=settings`) and a malformed id are both ignored.

### 9.3 Two defects found in the gate while doing this, both fixed in the same file

1. **Two gates could bind the same port.** Measured on this host: with `SO_REUSEADDR` on Windows a second
   socket binds the same `127.0.0.1:port` and both listen — pids 28108 and 17776 were caught alive in the
   same second, splitting incoming connections. Four probes decided the fix rather than the
   documentation: two `SO_REUSEADDR` sockets → the second bind **succeeds** (the bug);
   `SO_EXCLUSIVEADDRUSE` then `SO_REUSEADDR` → refused (**WinError 10013**); `SO_REUSEADDR` then
   `SO_EXCLUSIVEADDRUSE` → refused (**WinError 10048**); and an exclusive rebind immediately after a kill,
   with a real `TCP 127.0.0.1:3333 → …:3334 TIME_WAIT 0` entry on the port, **succeeded on the first
   attempt** — so exclusivity costs nothing and a restart stays instant. The gate now sets
   `SO_EXCLUSIVEADDRUSE` where it exists and `SO_REUSEADDR` only on POSIX, and the losing side of the race
   logs one line and **exits 0** instead of raising. Verified live against the running gate: the second
   process printed `[WinError 10048] … already owned by another process`, exited 0, exactly one gate
   process remained, and the incumbent still answered 200.
2. **The gate died silently four times.** It now writes a `starting pid=… parent=… argv=…` line before
   anything can fail, and an `exiting` line in a `finally` around the accept loop, so the next death is
   readable rather than inferred: a start with no matching `exiting` means it was terminated from outside.
   `accept()` failures are logged once (they used to spin in silence). No supervisor was added — that is
   the launcher's job.

**Final `scripts/phone-gate.py`:** 63,550 B, 1,318 lines,
**sha256 `C1DC930FCC4D7E59BFE888EC447800E56BB0D926CD4B3420C8FAFD2A52BED6B2`** (22:05:38Z). The gate
serving the §9.1 bytes is pid 11428, started 22:06:03Z, i.e. **after** that write. Every JOB A reading in
§9.1 was taken from that process.

**Still not verified, and the command that will:** the plugin needs
`pwsh scripts/install-client-plugins.ps1` plus an engine restart before a browser can load it — the engine
was deliberately not restarted (P210). After that restart the roster in the served document must contain
`dsh-plugin-session-link/client.js`, and a URL ending `#session=<id>` must open that session.

### 9.4 WHO MAY BE SIGNED IN — the hole the gate itself opened, closed

**The finding (another session's audit, 2026-09-16 21:58Z):** a cold `GET /` through a node's tailnet
name returned **200 with a working session cookie and no credential of any kind**, because
`complete_login()` performs the engine's token exchange on the visitor's behalf. That cookie drives
`/api` and the WebSocket mux — full engine control, a shell as the owner; on `secratary` that is RCE as
`zabz` on the company authority. The only thing bounding it was tailnet membership, and that ACL is
default allow-all with nothing tagged.

**The control is the device, not the identity.** `tailscale serve` forwards
`Tailscale-User-Login`/`Tailscale-User-Name`, but every device on this tailnet is enrolled under the same
Google identity (*all six peers, user 2701425880688073*), including the employee's Mac — so the login
cannot discriminate and `X-Forwarded-For` is the header that can.

**New file `scripts/phone-gate-allow.txt`** (3,051 B) lists five devices — `100.72.162.5` (this laptop),
`100.85.105.93` (the iPhone), `100.85.153.96` (zabz-tech), `100.84.72.88` (secratary), `100.105.248.90`
(zabz-tech-linux) — and **deliberately excludes `100.126.146.121` (lakewooechsmini, the employee's Mac)**,
with the reason written in the file itself, because a device on that list receives a 30-day cookie that is
a shell on the owner's engine, his mail and the company database. The gate re-reads the file when it
changes, so allowing a device is one line and no restart.

**Two things measured rather than assumed:**

* **Serve REPLACES a caller's `X-Forwarded-For`, it does not append.** Proved by sending
  `X-Forwarded-For: 8.8.8.8` through the tailnet: the gate logged `client=100.72.162.5` and **no**
  `xff=` anomaly field, which is only emitted when the raw header carries more than one entry. So a
  tailnet caller cannot present itself as another device. The parser still reads the **last** entry,
  which is the one a proxy appends — correct under either behaviour, and defensive if that ever changes.
* **A request with no `X-Forwarded-For` never went through Serve** and is loopback on this machine — the
  path the engine already trusts. It is left exactly as it was: `client=loopback`, still signed in.

**A refused device gets a 640-byte HTML 403** naming its own address and the file to add it to — not the
engine's plain text, because iOS offers plain text as a download and that dead end is the reason this
gate exists. The address is HTML-escaped (it arrives in a header). The rule is one rule for every path,
so a non-allowed device gets the same 403 on `/`, on `/api` and on the WebSocket upgrade. Log lines now
carry `client=<deciding device> peer=<socket peer>`, and never a token.

**Deliberate fail-open, stated so it can be overruled:** a missing file, or one with no usable lines,
means *no restriction* and says so once, loudly. That preserves the pre-existing behaviour and keeps a
typo from locking the owner out of his own node from a phone, where he has no terminal to fix it.

**Verified live (22:09–22:10Z), and the second one by header injection only:**

| Check | Result |
|---|---|
| owner's laptop through the tailnet (`client=100.72.162.5`) | **200** + `Set-Cookie`, signed in in flight |
| `X-Forwarded-For: 100.126.146.121` sent to `127.0.0.1:3086` | **403** `text/html`, names `100.126.146.121` — **no request was made from the employee's machine**, and none was necessary |
| the same address on `POST /api/session/list` | **403** |
| loopback with no XFF | **200**, unchanged |
| spoofed XFF through Serve | **200** and no anomaly logged (Serve replaced it) |
| **WebSocket upgrade** through the tailnet | **101** and the gate logged `client=100.72.162.5` — so Serve forwards the device header on the upgrade too, and the mux is inside the control rather than beside it |

**Final file:** 72,210 B, 1,484 lines,
**sha256 `CCEC6C517374981CD45DC8E3EC103089A0C734AC737C64FF60C339EE66D490C5`** (22:09:01Z), running as
pid 16156. Every reading above was taken from that process. Unit tests on the final file: 12 allow-list
checks (last-entry parsing, address normalisation, the shipped five, the employee's Mac excluded,
announce-once, fail-open on a missing and on a comment-only file) and 6 refusal-page checks (HTML,
escaped, names the device and the file, no token, `no-store`) all pass.
