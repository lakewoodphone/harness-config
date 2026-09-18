# 83 — Transport v2: an HTTP route on the node, and what dispatch does when the node does not answer

**Stream:** O2 of the overnight program (`81-overnight-program.md` §1). **Owns:**
`packages/plugin-mesh-http/**`, `docs/mesh/83-http-transport.md`. **Depends on:** `71` §1/§2.3/§2.4,
`70` §2.6/§4, `66` §2e/§3.1.
**Date:** 2026-09-17, 03:35–04:15Z. **Author:** a delegated build session, not the owner.

**Claim this document proves, with raw output in §6:** one dispatched child ran a real agent turn on
`zabz-tech` over `POST /mesh/run`, with **ssh disabled for that test**, and the node's own route log
records the request arriving with a valid HMAC and the child's `MESH-HOST: zabz-tech` line. The same
dispatcher, against a node with no route, falls back to v1 **explicitly and in its own record**.

**What was NOT done:** no engine on `ZABZ-YOGA` was touched (pid 1784, the owner's live session); no
file outside this package and this document was written; nothing was committed; no node was
restarted except `zabz-tech`, whose engine was idle and which is named in §7.

---

## 1. The result in one table

| node | transport v2 reachable? | evidence | cost of full deployment |
|---|---|---|---|
| `zabz-tech` | **YES — live now** | §6: an ssh-disabled child ran over the route; route log shows `verdict":"hmac-valid"` and `verdict":"ran"` | engine restarted once (idle: 0 connections, 401 on its own `/healthz`), 23188 → 23164 |
| `zabz-yoga-1` (this laptop) | **YES — CORRECTED 2026-09-17 13:06Z** | `GET http://127.0.0.1:3099/mesh/health` **and** `http://127.0.0.1:3086/mesh/health` both answer **200**, `secretPath C:/ProgramData/dsh-mesh.env`, `secretConfigured: true`. The engine restarted at 08:50 and the bundle loaded; this row said "no — and it must not be restarted" and that is **STALE** | one engine restart, which has now happened. **`nodeSource` on this node still lies**: its route reports `node: "zabz-yoga"`, `fqdn: ""` while naming `tailscale status --json Self.DNSName` as the source, because the engine booted at 08:51:07 — **52 s before `tailscale-ipn` started at 08:51:59** — read an empty `Self.DNSName`, and cached it for the life of the process. Fixed in the package (`lib/node-identity.js`, §2 defect 1 of `93-transport-concurrency.md` §5); it takes effect on this node's next restart, which this stream did not make |
| `lakewooechsmini` (Mac) | **no** | §5 and §11: the machine answers, its engine has been up **4 h 30 min** (pid 12458, `etime 04:30:20` at 04:14:56Z) with **2 session files touched in 30 min and one live session**, 16 GiB total with **swapUsedPct 58**, and it is an employee's machine | one engine restart. **Refused tonight** — see §11 |
| `secratary` (authority) | unknown | not attempted: not in this stream's brief and the authority's swap is a separate stream's problem (`81` §3.5) | unchanged |

---

## 2. What was built

| file | what it is |
|---|---|
| `packages/plugin-mesh-http/package.json` | the package; `dsh.bundle.patch → cordis.patch.yml`; **zero runtime dependencies**, so it resolves from a profile whose bundles come through junctions (`plugin-remote-fanout`'s README makes the same argument) |
| `packages/plugin-mesh-http/cordis.patch.yml` | one `insert` row, no id target, disablable by id. Carries no config on purpose: a node with no secret answers 503 to every run and says so |
| `lib/index.js` | the Cordis row: every key optional with a default; `createMeshHttp` builds the routes; `ctx.inject(['webServer'], …)` rather than a declared `inject`, so this row can never make a node unbootable (`plugin-health`'s reasoning, `lib/index.js:575-583`) |
| `lib/auth.js` | the MAC, the constant-time compare, and the replay ledger |
| `lib/secret.js` | the secret file: `KEY=VALUE`, comments, re-read when the file's identity changes |
| `lib/body.js` | bounded raw intake: 413 against the declared length **and** against the running total |
| `lib/runner.js` | the single run slot, the wall clock, the output caps, and the `MESH-HOST` preamble |
| `lib/handler.js` | the request contract, in the order it happens; every refusal is a value a caller can branch on |
| `lib/node-identity.js` | the name this node reports — hostname, tailnet DNS label, FQDN, and the source of each |
| `bin/mesh-dispatch.mjs` | the client: v2 first, then an **explicit and logged** v1 fallback (§8) |
| `bin/install-mesh-http.mjs` | the keeper for the junction and the bundle list; `--check` changes nothing; it proves the bundle resolves **before** naming it |
| `bin/mesh-http.mjs` | the keeper CLI: `secret`, `check`, `clean`, `serve`, `probe` |
| `ssh-run.ps1`, `ship-to-node.ps1`, `probe-*.ps1`, `probe-node-posix.sh`, `who-is-working.ps1`, `restart-readiness.ps1` | the tooling this work needed, kept because the next node's deployment needs all of it (§3.4) |
| `test/mesh-http.test.mjs` | 29 tests: the MAC, replay, bounded intake, the run slot, the timeout, and the wire contract of every refusal |
| `test/dead-target-fallback.mjs` | the measurement behind §8, run against the real transport and the real provider |

---

## 3. The contract

### 3.1 `POST /mesh/run`

Request (JSON, `content-type: application/json`):

| field | required | meaning |
|---|---|---|
| `prompt` | yes | the task. Bounded by `maxPromptChars` (default 32000) **because it travels as one argv entry**, so the platform's own command-line ceiling is the binding limit |
| `meshHost` | no | the node the caller believes it is reaching. **Echoed in the log, never trusted** — refusals do not depend on it and the response names this node |
| `timeoutSec` | no | clamped to `maxTimeoutSec` (default 3600) |
| `workdir` | no | refused with 403 unless the node sets `allowRequestWorkdir` |

Headers: `x-mesh-timestamp`, `x-mesh-nonce`, `x-mesh-signature`, optional `x-mesh-request-id`.

Answer (200):

```json
{ "ok": true, "exitCode": 0, "timedOut": false, "spawnError": null,
  "stdout": "MESH-HOST: zabz-tech\n…", "stderr": "dsh: reasoning:\n…",
  "stdoutBytes": 381, "stderrBytes": 337, "truncated": false,
  "host": "zabz-tech", "node": "zabz-tech", "nodeSource": "tailscale status --json Self.DNSName",
  "fqdn": "zabz-tech.tail93e6e6.ts.net", "ms": 7075,
  "requestId": "dispatch-mu507prp-u2vasg", "artifacts": "…\\.dsh\\mesh\\http\\…", "viaGate": "100.72.162.5" }
```

Every refusal, with what it means to a dispatcher:

| status | `reason` | is the MAC valid? | what a dispatcher should do |
|---|---|---|---|
| 401 | `bad-timestamp-header`, `bad-nonce-header`, `bad-signature-header`, `bad-signature`, `outside-window`, `replayed` | no | **do not retry elsewhere**: the secret or the clock is wrong |
| 503 | `node-has-no-secret` | — | this node is not deployed; fall back to v1 if the caller allows it |
| 503 | `node-workdir-unusable` | yes | the node's own configuration is wrong; fall back |
| 405 / 415 / 400 / 413 | method, content type, `prompt-required`, `prompt-too-large`, `workdir-*` | only after 405/415 | the caller's fault; fix the call |
| **429** | `node-busy` | yes | the node is running another turn. **A refusal with a position, never a queue** |
| 504 | (a run, not a refusal) | yes | the child was killed at the wall clock. The node answered |
| 500 | `node-error` | — | a bug in this plugin; the text names it |

### 3.2 `GET /mesh/health`

Unauthenticated and deliberately dull: `service`, `protocol`, `version`, `route`, the node's own
identity (`host`, `node`, `nodeSource`, `fqdn`, `platform`), `auth.secretConfigured` (+ the path and
the byte length — never the value), `limits`, and the runner's counters.

**Why it is worth its own route:** the alternative is spending a real prompt and a three-minute
timeout to discover a 401. This is what makes the fallback a fallback instead of a failure.

### 3.3 It never trusts the caller for the host name

`host` is `os.hostname()`; `node` is the tailnet DNS label from `tailscale status --json
Self.DNSName` (or `MESH_NODE_NAME`, or `os.hostname()` when tailscale cannot name the machine — and
`nodeSource` says which of the three it was). Nothing the caller sent can change either, and the
child's `MESH-HOST:` preamble is built from the measured hostname. A test asserts this by asking
with `meshHost: 'a-node-that-does-not-exist'` and checking the answer still names this node.

### 3.4 Deploying it to a node — the exact four commands

```powershell
node C:/path/harness-config/packages/plugin-mesh-http/bin/install-mesh-http.mjs   # junction + bundle name
node C:/path/harness-config/packages/plugin-mesh-http/bin/mesh-http.mjs secret    # the shared secret
node C:/path/harness-config/packages/plugin-mesh-http/bin/mesh-http.mjs check     # prove it is ready
#   then restart that node's engine — a mounted bundle cannot hot-load (P210)
```

`mesh-http.mjs check` on this laptop, **before** deployment, read:

```
mesh-http 0.1.0 on zabz-yoga (node zabz-yoga-1, tailscale status --json Self.DNSName)
  route            /mesh/run  +  /mesh/health
  secret           NOT USABLE: cannot stat the secret file (ENOENT)
  dsh entry point  C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js
  verdict          NOT ready
```

**CORRECTED 2026-09-17 13:52Z — the paragraph that used to follow this is now false.** It said
*"Nothing about that changes on the laptop until a restart window exists"*. The laptop's engine was
restarted at **08:50** by another stream; the junction and the bundle name took effect, and this
same command now reads, at 13:52Z with the package at v0.2.0 (`93-transport-concurrency.md`):

```
mesh-http 0.2.0 on zabz-yoga (node zabz-yoga-1, tailscale status --json Self.DNSName)
  secret           64 bytes at C:/ProgramData/dsh-mesh.env ({"mode":"ACL","acl":[…Administrators:(F), SYSTEM:(F), ZABZ-YOGA\ezabz:(R)]})
  concurrency      5 at once, 780s queue budget — cpu term binds: 5. 9.2 logical CPUs of budget ÷ 1.68 per tool-heavy turn.
  identity         corroborated by the tailnet
  verdict          ready to accept v2 work
```

and `mesh-http.mjs probe` — the roster walk this document asked for in §6.7 — reports it as
`ACCEPTS v2` beside `zabz-tech`. **The claim that there is no partial deployment still holds**: the
junction alone was inert for four and a half hours, and only the restart made the route exist. What
was wrong was the assumption that the restart had not happened.

**One defect this exposes on the running laptop engine, and it is not fixed there:** its route answers
`node: "zabz-yoga"`, `fqdn: ""`, while naming `tailscale status --json Self.DNSName` as the source
that produced that name. The engine booted at 08:51:07, `tailscale-ipn` started at 08:51:59, the boot
read saw an empty `Self.DNSName`, and `createNodeIdentity` cached it for the life of the process. A
fresh process on the same machine reading the same file returns `zabz-yoga-1.tail93e6e6.ts.net`.
Fixed in `lib/node-identity.js`; on this node it takes effect at the **next** restart, which this
stream deliberately did not make (pid 4880 serves the owner's live work).

---

## 4. The auth design, and what it actually limits

**Scheme, exactly.**

```
POST <path>
x-mesh-timestamp: <unix seconds>
x-mesh-nonce:     <8..64 chars of [A-Za-z0-9_-]>
x-mesh-signature: <lowercase hex hmac-sha256>

message   = "mesh-http-v1\n" + timestamp + "\n" + nonce + "\n" + <the exact request body bytes>
signature = hmac_sha256(secret, message)
accept    = |now − timestamp| ≤ skewSeconds (120)  AND  the nonce has not been seen in that window
```

* the raw bytes are signed, so a JSON round-trip anywhere in the path breaks the MAC rather than
  silently changing what was authorised (`dsh-webhook-github` reads its body the same way);
* the timestamp and nonce are inside the MAC, so neither can be moved;
* the compare is `crypto.timingSafeEqual` after a length check — a byte-by-byte `==` is the classic
  oracle that turns "cannot forge" into "can forge one byte at a time";
* the nonce is consumed **only after** the MAC verifies, so an unauthenticated caller cannot burn
  nonces and deny service to the real dispatcher;
* the ledger is bounded (8192 entries, pruned by the same window), so it is not a memory-growth
  surface.

**The secret lives outside every repository:** `/etc/dsh-mesh.env` on Linux/macOS,
`C:/ProgramData/dsh-mesh.env` on Windows, `MESH_HTTP_SECRET=<≥16 bytes>` (48 random bytes by
default), mode `0640`, or on Windows the equivalent ACL — measured on `zabz-tech`:

```
C:/ProgramData/dsh-mesh.env BUILTIN\Administrators:(F)
                            NT AUTHORITY\SYSTEM:(F)
                            zabz-tech\ezabz:(R)
```

The file is re-read when its `mtime`/`size`/`inode` changes, so **rotation takes effect on the next
request instead of on the next restart**. The value is never logged, never returned, and never put in
a response; `mesh-http secret` prints the byte length and the path and says why it will not print
more.

### An attacker who can reach the gate — what they CAN and CANNOT do

The gate is the only door (`71` §0: `tailscale serve` → `phone-gate` → the engine on loopback), and
its device allow-list refuses a device it would not sign in **before it relays anything**. So the
attacker classes are:

| attacker | CAN | CANNOT |
|---|---|---|
| a tailnet device **not** in `phone-gate-allow.txt` | nothing: the gate answers 403 before the route exists in the conversation | reach `/mesh/run` or `/mesh/health` at all |
| a device that **is** allowed, with no secret (a phone, the employee's Mac, a stolen tailnet node) | `GET /mesh/health` — the node's name, its limits, and the secret file's path; and `POST /mesh/run` only to be refused 401 | run a prompt; read the secret; forge a MAC; learn the secret from any response |
| a **passive** reader of the traffic (there is none on the tailnet: WireGuard between peers, loopback behind the gate) | if it existed: replay a captured request **inside the 120 s window** — and the nonce ledger refuses even that, unless it wins the race with the real dispatcher | read or modify anything if it cannot also touch an endpoint |
| someone who can **modify** traffic | nothing useful: changing any byte of the body, timestamp or nonce breaks the MAC, and the refusal does not text `mesh-http-v1\n` distinctions back to the caller beyond the reason name | choose what a child runs |
| **root/admin on any node** | read that node's secret file, and therefore sign requests **to that node**, and run any prompt they like there | sign requests to any **other** node: each node has its own secret, and a node accepts only its own. Escalation across the mesh needs one compromise per node |
| a caller who holds **one node's** secret and wants a **different** node to run the work (a confused deputy) | nothing: the signature is over bytes, but the *route* it opens is the route on that node. A signed request stolen from node A replayed at node B fails the MAC | redirect work to a node they cannot sign for |

**What is deliberately NOT a control.** The route does not sit behind the engine's cookie fence, and
that is the point: the fence needs a launch token that is minted per process and never persisted
(`66` §2c), so a dispatcher could never mint one for another node and a harvested one dies on the
next restart with a 401 indistinguishable from a permission error. The gate's device identity is not
used as a credential either — all six peers on this tailnet are enrolled under one Google identity
(`scripts/phone-gate.py:2029-2032`, measured), so it cannot discriminate devices. The MAC is the
credential, and the header the gate adds (`x-forwarded-for`) is recorded as provenance only.

**The honest residual risk:** anyone with code execution as the engine user on a node can read that
node's secret and then issue authenticated runs **to that node**. That is not a hole in this design;
it is the same authority they already have (they can run `node …/bin.js --profile headless` directly,
and they can read every session on the machine). What the MAC buys is that this authority does **not**
spread: no device on the tailnet, and no other node, gains it by being reachable.

---

## 5. Bounds, and the three refused operations

| bound | value | why |
|---|---|---|
| body | 256 KiB (`maxBodyBytes`) | checked against the declared length **and** the running total; either 413s and resumes the stream |
| prompt | 32000 chars | it is one argv entry; the platform's command-line ceiling is the real limit |
| wall clock | default 900 s, max 3600 s | the child is killed; the answer carries `timedOut: true` and the status is 504 |
| output | 2 MiB per stream | a runaway child cannot grow the engine's heap through this route |
| concurrency | **1** — **SUPERSEDED, see `93-transport-concurrency.md`** | one generating turn ≈ 0.81 GB commit and ≈ 1 core (`71` §2.2); a second request gets 429 with a position. `84` §3/§4.3 then measured both halves of that sentence: commit is **403 MiB**/turn, not 810, and CPU is 0.62-1.68 logical CPUs depending on the turn. The ceiling is now derived from the node's own capacity (`lib/concurrency.js`) and a request beyond it **queues with a visible position instead of being refused** |
| nonce ledger | 8192 entries, window-pruned | bounded memory |

**Refused, deliberately:**

1. **A second concurrent run.** 429 + `node-busy` + `retryAfterSec`. "Prove concurrency is safe" was
   not attempted and the reason is stated rather than hidden: the governor's own measurement is that
   this host pages at 13–14 concurrent turns, and this route's job is to be the boring half of the
   mesh, not a second admission system. That is a **design choice with a measurable cost** (a busy
   node is a queued dispatch), and it is the safe direction.
2. **A caller-chosen `workdir`**, unless the node opts in. The prompt is the caller's; the machine's
   filesystem layout is not.
3. **Deploying to the Mac Mini tonight.** Measured (`probe-posix.ps1`, 2026-09-17T04:14:56Z):
   `UNAME=Darwin 25.5.0`, engine pid 12458 up `04:30:20` with one live session (and only 2 session
   files touched in 30 minutes, so the session is real, not a scan), `mem.totalMiB 16384`,
   `mem.freeMiB 6976`, `swapUsedPct 58.0`, `load1 1.41`, `disk.freeGiB 46.0`, and its own gate
   answering `/mesh/capacity` with schema 1. The engine restart that mounting requires would end
   that session on someone else's computer, for a node this document does not need to prove
   anything. **What it needs is the same four commands in §3.4 plus a restart window — the runtimes
   are already there**: `/Users/lpt/.local/node-v24.12.0-darwin-arm64/bin/node` (the interpreter its
   engine runs), `/Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js`,
   `/Users/lpt/.dsh-gate/scripts/phone-gate.py --listen-port 3086 --engine-port 3099`, and
   `tailscale serve → 127.0.0.1:3086`. Its `~/.dsh` is `/Users/lpt/.dsh`.

---

## 6. The raw proof

### 6.1 The sabotage, exactly, and how it was restored

**ssh was disabled for the test in the way the brief allows** — it was never enabled, and nothing on
the target was touched:

```
$env:MESH_SSH_EXE = 'C:/definitely/not/ssh.exe'
Test-Path $env:MESH_SSH_EXE   ->  False
```

`MESH_SSH_EXE` is the client transport v1 spawns (`bin/mesh-dispatch.mjs`, `SSH_EXE`). Pointing it at
a program that does not exist makes the v1 path **unrunnable in that process**, so a green result
cannot be v1 in disguise. The dispatcher was additionally run with **`-RequireV2`**, which makes a v2
refusal terminal — the fallback could not silently rescue the run even if the sabotage leaked.
**Nothing was restored because nothing was changed:** no sshd config, no service, no firewall rule,
no PATH, and no file on `zabz-tech` outside this plugin's own artifacts. The environment variable
died with the process that set it. (Sabotaging the sshd *service* on the target would have made the
node unreachable for everyone mid-run, and disabling it inbound-only is not possible with a
per-process env var — this is strictly stronger for the claim and strictly weaker in blast radius.)

**The one place ssh WAS used in this proof:** to reach `zabz-tech` at all, because that is the only
path to the office. The dispatched child did not use it, and the `-RequireV2` run's record contains
no `fallback` phase (§6.3).

### 6.2 The child, dispatched over the route, ssh disabled

```powershell
# run ON zabz-tech, over its own ssh, with the v1 client sabotaged and v2 required
node .../bin/mesh-dispatch.mjs -Node zabz-tech -Prompt $task -TimeoutSec 240 -RequireV2 -Json
```

```
SABOTAGE: MESH_SSH_EXE=C:/definitely/not/ssh.exe ; Test-Path=False
marker exists before the run: False
DISPATCH BEGIN
{"phase":"result","runId":"2026-09-17T04-02-50-991Z","node":"zabz-tech","transport":"http",
 "url":"https://zabz-tech.tail93e6e6.ts.net/mesh/run","httpStatus":200,"ok":true,"childExitCode":0,
 "timedOut":false,"host":"zabz-tech","childHosts":["zabz-tech"],"disagreements":[],
 "meshHostLines":1,"ms":7075,
 "stdout":"MESH-HOST: zabz-tech\n\nRead attempt: `C:/ProgramData/o2-mesh-proof.txt` did **not exist** …\n\nI then wrote the exact text into that file, and re-read it to verify. Its entire current contents are:\n\nO2-PROOF-MARKER written by the dispatched child on ZABZ-TECH at 2026-09-17T04:02:50Z\n\nCHILD-HOST=ZABZ-TECH\n\nO2-HTTP-CHILD-OK\n",
 "stderr":"dsh: reasoning:\nRead the file first.\n…"}
marker exists after the run: True
marker contents: O2-PROOF-MARKER written by the dispatched child on ZABZ-TECH at 2026-09-17T04:02:50Z
```

Why each line is evidence:

| line | what it proves |
|---|---|
| `transport":"http"` + `-RequireV2` | this run **is** the HTTP route; a fallback would have been terminal, and the record has no `fallback` phase |
| `Test-Path $env:MESH_SSH_EXE = False` | v1 could not have run even if it had been reached |
| `marker exists before the run: False` / after: `True` | the file on `zabz-tech` did not exist and the **child created it with the child's own text** — the machine that ran the work is the machine that wrote the file. This is the assertion no reporter can fake |
| `MESH-HOST: zabz-tech` (×1, `disagreements: []`) | the child reported the node the route is on, and it matches |
| `host: "zabz-tech"` from the route | the node's own answer, not the caller's `meshHost` |
| `ms: 7075` | a real turn, not a stub |

### 6.3 The node's own log — the request arrived, the HMAC was valid, the child ran

`C:\Users\ezabz\.dsh\multi-window\logs\3099-20260916-235902.log` on `zabz-tech` (read back over ssh
with `ssh-run.ps1`, verbatim):

```
mesh-http {"at":"2026-09-17T04:02:51.104Z","requestId":"dispatch-mu507prp-u2vasg","host":"zabz-tech","node":"zabz-tech","nodeSource":"tailscale status --json Self.DNSName","fqdn":"zabz-tech.tail93e6e6.ts.net","platform":"win32","verdict":"hmac-valid","bodyBytes":398,"nonce":"HxDGDOMoyiet"}
RUN dispatch-mu507prp-u2vasg node-exe=C:\Program Files\nodejs\node.exe profile=headless cwd=C:\Users\ezabz\code timeoutMs=240000 artifacts=C:\Users\ezabz\.dsh\mesh\http\2026-09-17T04-02-51-107Z-dispatch-mu507prp-u2vasg
END dispatch-mu507prp-u2vasg exit=0 timedOut=false spawnError=none ms=7075 stdoutBytes=381 stderrBytes=337
mesh-http {"at":"2026-09-17T04:02:58.187Z","requestId":"dispatch-mu507prp-u2vasg","host":"zabz-tech",…,"verdict":"ran","exitCode":0,"timedOut":false,"ms":7075,"stdoutBytes":381,"meshHostLineSeen":true}
```

`verdict":"hmac-valid"` is the node stating that the MAC verified against **its own** secret file.
The three artifacts are on disk (`task.txt 485 B`, `stdout.txt 381 B`, `stderr.txt 337 B`) with their
hashes, and `task.txt` is the exact task the node ran.

### 6.4 An INDEPENDENT observer: the laptop dispatched, `-RequireV2`, and it worked

So the proof does not rest on code that ran on the node it is proving:

```
# on ZABZ-YOGA, with zabz-tech's secret in a local file (the dispatcher reads ITS OWN node's file)
node bin/mesh-dispatch.mjs -Node zabz-tech -PromptFile … -TimeoutSec 180 -RequireV2 -Json -SecretFile C:\Users\ezabz\o2-secret.env
{"phase":"result","runId":"2026-09-17T04-03-23-370Z","node":"zabz-tech","transport":"http",
 "url":"https://zabz-tech.tail93e6e6.ts.net/mesh/run","httpStatus":200,"ok":true,"childExitCode":0,
 "timedOut":false,"host":"zabz-tech","childHosts":["zabz-tech"],"disagreements":[],
 "meshHostLines":1,"ms":3419,
 "stdout":"MESH-HOST: zabz-tech\nDISPPROOF=o2-laptop-dispatcher-observed\nO2-DISPATCH-FROM-LAPTOP-OK\n"}
```

and the node's log for that same request:

```
mesh-http {"at":"2026-09-17T04:03:23.330Z","requestId":"dispatch-mu508f2v-8ptbsn",…,"verdict":"hmac-valid","bodyBytes":188,"nonce":"nTL8i48FRl_d"}
RUN dispatch-mu508f2v-8ptbsn … timeoutMs=180000
END dispatch-mu508f2v-8ptbsn exit=0 timedOut=false spawnError=none ms=3419 stdoutBytes=88 stderrBytes=271
mesh-http {"at":"2026-09-17T04:03:26.754Z","requestId":"dispatch-mu508f2v-8ptbsn",…,"verdict":"ran","exitCode":0,"ms":3419,"meshHostLineSeen":true}
```

The path taken is `https://zabz-tech.tail93e6e6.ts.net/mesh/run` — i.e. **through the gate**, over
the tailnet, from a different machine, with `-RequireV2`. The gate relayed it; the route
authenticated it; the child ran on `zabz-tech` in 3.4 s.

### 6.5 A wrong secret is refused, from the laptop

```
GET https://zabz-tech.tail93e6e6.ts.net/mesh/health   ->  HTTP 200 (no auth needed, by design)
POST /mesh/run with the LAPTOP's secret (this node has none)  ->  401 bad-signature
```

### 6.6 The v1 fallback, on a node with no route

```
node bin/mesh-dispatch.mjs -Node lakewooechsmini -PromptFile … -TimeoutSec 180 -Json -SecretFile C:\Users\ezabz\o2-secret.env
```
```
{"at":"2026-09-17T04:03:46.743Z","phase":"probe","transport":"http","ok":false,
 "url":"https://lakewooechsmini.tail93e6e6.ts.net/mesh/health","reason":"no route on this node (…)"}
{"at":"2026-09-17T04:03:46.753Z","phase":"fallback","outcome":"using ssh",
 "reason":"no route on this node (…)",
 "note":"explicit and logged: this run is NOT the HTTP transport, and the record says so",
 "ssh":"mac-mini-ts"}
{"at":"2026-09-17T04:03:51.028Z","phase":"run","transport":"ssh","ok":true,"exitCode":0,
 "timedOut":false,"ms":4274,"meshHostLines":1,"childHosts":["LakewooechsMini"],"disagreements":[]}
```

The child genuinely ran on the Mac (`childHosts: ["LakewooechsMini"]`, 4.3 s). **The transport is
named in every record**, and the fallback has its own phase with its own reason — a fallback nobody
can see is the failure mode this program exists to stop. The probe's error field was empty on the
first attempt (`no route on this node (undefined)`), which is a defect this stream fixed in the same
session: an unreachable node must say *why*, not print `undefined`.

### 6.7 How to reproduce every claim here, from any node

```powershell
cd packages/plugin-mesh-http
node --test test/mesh-http.test.mjs                    # 29 tests: the MAC, replay, bounds, the run slot
node test/dead-target-fallback.mjs                     # §8: a dead ssh transport runs the child NOWHERE
node bin/mesh-http.mjs check                           # is THIS node ready to accept v2 work?
node bin/mesh-http.mjs probe                           # does every roster node answer /mesh/health?
# a real dispatch to a deployed node, with v1 provably unrunnable:
$env:MESH_SSH_EXE = 'C:/definitely/not/ssh.exe'
node bin/mesh-dispatch.mjs -Node zabz-tech -Prompt "Reply with exactly: MESH-HOST: zabz-tech" -RequireV2
```

The third and fifth commands are the two that decide deployment state; the fourth is the one to run
before anything else, because it tells you which nodes have the route at all. Run from this laptop at
04:18Z, it printed exactly this (exit 1, because not every node has the route yet — which is the
point of asking):

```json
{"node":"zabz-tech","url":"https://zabz-tech.tail93e6e6.ts.net/mesh/health","status":200,"ms":321,"service":"mesh-http","secretConfigured":true,"busy":false,"nodeSaysItIs":"zabz-tech","host":"zabz-tech","verdict":"ACCEPTS v2"}
{"node":"zabz-yoga-1","url":"https://zabz-yoga-1.tail93e6e6.ts.net/mesh/health","status":404,"ms":1859,…,"verdict":"not v2 (HTTP 404)"}
{"node":"secratary","url":"https://secratary.tail93e6e6.ts.net/mesh/health","status":404,"ms":147,…,"verdict":"not v2 (HTTP 404)"}
{"node":"lakewooechsmini","url":"https://lakewooechsmini.tail93e6e6.ts.net/mesh/health","status":404,"ms":142,…,"verdict":"not v2 (HTTP 404)"}
{"node":"zabz-tech-linux","url":"https://zabz-tech-linux.tail93e6e6.ts.net/mesh/health","status":404,"ms":188,…,"verdict":"not v2 (HTTP 404)"}
```

A **404** is the honest answer for a node without the plugin: the route is not mounted, the engine
says so, and no part of this design invented a different status for it. A node whose gate is down or
unreachable reports a transport error instead, and the two are distinguishable in the record.

---

## 7. What it cost, and what was left behind

| what | where | evidence |
|---|---|---|
| **One engine restart.** Old pid 23188 (started 12:31:41, 65 MiB working set, 13 threads) → new pid 23164 (started 23:59:02). | `zabz-tech` | Before the restart: **0** established connections on 3086 and on 3099, `/healthz` → 401 (alive, unauthenticated), no `--profile` child processes, nothing of the owner's running. After: `port 3099 LISTEN pid=23164`, the gate answers `/mesh/capacity` with schema 1, and all 452 session files are intact |
| The engine's stdout log moved to `3099-20260916-235902.log` | `zabz-tech` | the log this document quotes |
| `…/profiles/web/package.json.bak-*` | `zabz-tech` | written by the installer before it added one name to `dsh.profile.bundles` |
| `C:/ProgramData/dsh-mesh.env` (345 B, ACL above) | `zabz-tech` | §4 |
| `C:/ProgramData/o2-mesh-proof.txt` | `zabz-tech` | the child's own artifact; leave or delete, it is the proof |
| `~/.dsh/mesh/http/<run>/` + `~/.dsh/mesh/logs/*-dispatch.jsonl` | `zabz-tech` | the node's own record; `mesh-http clean --days N` ages them |
| **Nothing** | `ZABZ-YOGA` | engine pid 1784 untouched; the only files written here are in this package, the two dispatch logs under `~/.dsh/mesh/logs/`, and two temp `o2-*.log` files under `C:\Users\ezabz\` |
| **Nothing** | `lakewooechsmini`, `secratary` | read-only probes only |

**A restart is the entire cost of deploying this to a node, and that is a P210 fact, not a choice
this stream made.** It is why the laptop is not deployed tonight and why the Mac was refused.

---

## 8. What the transport does when the target is unreachable — the manager's question, answered

**The question.** If the ssh transport to the node the broker named fails, does anything run the child
locally or on another node?

**The answer, read from the source and measured: NO. There is no fallback of any kind, and the
failure is loud.** `packages/plugin-remote-fanout` (read-only, not this stream's to edit):

* `lib/ssh-transport.js` — one `ssh` per child, both streams to files, settled on the completion
  frame. A destination that refuses the connection produces a `close` with exit 255; there is **no
  other branch** in that file that starts anything anywhere else;
* `lib/provider.js:251-283` — a `spawnError`, a timeout, a non-zero exit, a missing frame, or a
  location mismatch each set `stopReason: 'error'` with a diagnostic and return. No code path reaches
  the built-in in-process provider, and the provider is not given the local-execution seam at all.

**Measured against the real transport** (`test/dead-target-fallback.mjs`, run 2026-09-17T03:45:22Z;
the real `createSshTransport` and the real `RemoteOneShotProvider`, only the destination sabotaged):

```
sabotage            ssh -p 1 -o BatchMode=yes -o ConnectTimeout=5 ezabz@127.0.0.1   (nothing listens)
stopReason          "error"
diagnostic          "the remote one-shot exited 255 and produced no final message; stderr tail:
                     banner exchange: Connection to UNKNOWN port -1: Connection refused"
providerText        MESH-HOST: (not reported)
                    child ran on node "UNKNOWN" via ssh -p 1 …
                    transport host = (not reported)  (recorded by the target shell before the agent started)
                    exit = 255 in 2095 ms
ms                  2100
```

**Where the child ran: nowhere.** Nothing was executed on the target (the client never connected),
and nothing was executed locally. The `MESH-HOST: (not reported)` line is the placeholder a failed
child produces, which is why `mesh-run`'s verifier filters `(not reported)` out of its host tokens.

So the premise behind the concern — *"maybe it runs work where it likes while reporting where the
broker said"* — is **not** how this system fails. The real hazard found while checking it is the
opposite and worth stating plainly: **a report with `meshHostLines: 0` is a run whose children did
not report, and `mesh-run` already fails such a run** (`phase: "result"`, `only N MESH-HOST lines for
M`). Two smaller traps that produce the same shape:

* **The verification only reads the PARENT's final message.** The parent is an agent; whether its
  children's reports survive into its own final answer is a property of how that parent summarised
  them, not of the transport. A correct placement can therefore fail verification
  (`meshHostLines: 0 of 6`) with every child having run. That is the failure to watch for in the
  `03-37-48-965Z` fleet run, and the fix belongs in the parent's task, not in the transport.
* **`zabz-yoga-1` vs `zabz-yoga`**: the broker names the tailnet DNS label, and a child running
  there prints `ZABZ-YOGA` (or the *older* DNS label `zabz-yoga`). `mesh-run`'s `hostMatchesNode` and
  the provider's `sameNode` both normalise case, domain and a `-ts` suffix, and `mesh-run`'s node
  table lists `zabz-yoga-1` beside `ZABZ-YOGA` and `zabz-yoga` on purpose. A `childHosts
  ["zabz-yoga"]` on a run placed on `zabz-tech` is therefore a **real** disagreement — the child
  genuinely ran elsewhere — and the same string on a run placed on `zabz-yoga-1` is a **match**.

### What transport v2 changes about this

1. **A route that answers is the node's own assertion that it accepted the job.** `GET /mesh/health`
   is answered by the node with its own name, and a `200` from `POST /mesh/run` means a child ran
   **there** — the body carries the node's own `host`/`node`, and the child's preamble was built
   from that hostname. There is no shell, no sshd session, no reparse point and no remote shell
   dialect between the decision and the run.
2. **"Cannot reach the named node" is a FAILED RUN, never a reason to run elsewhere.** In
   `bin/mesh-dispatch.mjs` the fallback exists for one case only — *the node has not been deployed*
   (or is busy) — and:
   * it happens **before anything runs**: a cheap `GET /mesh/health` decides it, never a prompt;
   * **once the route has accepted a prompt (HTTP 200 or 504) there is no fallback at all** — the
     node has the work, and running it again elsewhere would be the duplicate the owner must never
     get;
   * it is its own `phase: "fallback"` record with a reason, and the run's `transport` field says
     `ssh` instead of `http`, so the host a caller reads is the host that ran it;
   * `-RequireV2` makes even that impossible, which is what every proof run in §6 used.
3. **The dispatcher refuses to guess a node.** An unknown name exits 2 with the known list
   (`mesh-run` does the same, `70` §2.6: the `-Exclude "zabz-yoga"` lookup-miss).

**Recommendation to the streams that own that code** (not mine to edit): in `mesh-run`, report the
count and the child hosts even when verification fails, and say in the failure whether the parent
printed no reports at all or printed reports naming the wrong node. Those are different faults with
the same exit code today.

---

## 9. What could not be verified, stated as refusals

* **The Mac Mini's route.** Not deployed (reason in §5), so "the route works on macOS" is **not**
  claimed. What *is* measured: its engine answers on 3099, its gate answers `/mesh/capacity` with a
  schema-1 document, it has no `dsh` route today, and v1 ssh to it completes a real child in 4.3 s.
* **`secratary`.** Not attempted; it is not in this stream's brief and the broker already reaches it
  over ssh for `/place`.
* **Concurrent runs on one node.** Refused by design (§5), so "two runs at once is safe" was neither
  claimed nor disproved here. **Now measured — `93-transport-concurrency.md` §6.** Twelve concurrent
  v2 requests on `zabz-tech` were all served: eight admitted immediately, four queued at positions
  1-4 and served in arrival order, with the node's own counters recorded alongside.
* **The Windows engine log's exact encoding.** The JSONL records from the dispatcher contain one
  mojibake sequence where the child's output had a non-ASCII character; the **artifacts on disk are
  correct** (`stdout.txt 381 B`, sha256 `6342E361594B635D…`, read back verbatim). The corruption is
  in the display path of the PowerShell reader used to fetch it, not in the route's response — the
  laptop-side run's stdout came through byte-clean.
* **Rotation without a restart** is unit-tested (§2, `loadSecret` re-reads on a changed file) but has
  not been exercised against a live engine.
* **The `429` busy path against a live node.** Unit-tested; producing it live would have needed two
  dispatches inside one turn. **Superseded by `93` §6/§7:** the queue was produced live, the node's
  engine log carries the four `QUEUE` lines with their positions and the four `DEQUEUE` lines in
  arrival order, and the only `429` left in the contract is `node-queue-wait-exceeded` — a wait
  budget, not a capacity refusal.
* **The laptop's identity on its RUNNING engine.** Degraded until that engine is next restarted;
  no restart of it was made (§3.4, corrected).
* **`zabz-tech` after a reboot.** The engine there is hand-started, like the authority's broker
  (`81` §0.8). Nothing about this stream makes that worse, and nothing about it makes it better.

---

## 10. What the other streams should take from this

1. **`zabz-tech` can now take v2 work.** `GET https://zabz-tech.tail93e6e6.ts.net/mesh/health`
   answers `secretConfigured: true`. A dispatcher that runs on `zabz-tech` uses its own secret file;
   a dispatcher elsewhere needs that node's secret file copied (or a per-node file in each
   dispatcher's own home) — the design is deliberately **one secret per node**, so no node's
   compromise signs for another.
2. **The laptop needs one restart window, and nothing else** (§3.4, proven on the desktop). Until
   then it is a v1-only node, which is a fact the broker's `dispatch` column should carry.
3. **The gate needs no change.** `/mesh/run` is relayed byte-for-byte like every other engine path,
   and the device allow-list is the outer control. What the gate does **not** do is authenticating the
   caller — that is the MAC, and it is why this is safe even though the gate signs a cold visitor in.
4. **`packages/plugin-mesh/` in `71` §3's table does not exist**: the O2 brief names
   `packages/plugin-mesh-http/**`, and `scripts/mesh-e2e.ps1:1005` still checks for
   `packages\plugin-mesh`. Whoever owns that harness should look for `plugin-mesh-http` (a
   one-line change in a file this stream does not own).
