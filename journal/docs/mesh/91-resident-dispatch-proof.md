# 91 — The resident-engine dispatch proof: a child from the owner's own kind of session, landing on another node

**Program:** `docs/mesh/`, the acceptance step `90-provider-mount.md` §7 left open and §8 named as the
one command that closes it: *"Call `subagent_remote` once … then report its raw output. The child's own
`MESH-HOST:` line is the proof."*
**Date:** 2026-09-17, 12:55Z–13:05Z. **Author:** a delegated acceptance session, not the owner.
**Owns exactly one file:** this one. No script, plugin, preset or profile was edited.

**What was NOT done:** no engine was restarted on any node (this laptop's engine, pid **4880**, booted
08:51:07 and is still the same process at the end); nothing on `zabz-tech` was touched beyond two
dispatched children and the reads used to corroborate them; nothing was committed, pushed, branched or
reset; the owner's own session in that engine was never prompted, interrupted or read.

---

## 1. The claim, and the result

**Claim:** a child dispatched by a `subagent_remote` tool call **from a RESIDENT engine session** — the
configuration the owner actually works in — runs a real agent turn on a **different machine**, and the
machine it ran on is the one the provider configured.

**Result: PROVEN, twice, on two independent sessions, with the target's own filesystem as the witness.**

| | run 1 | run 2 (the discriminating run) |
|---|---|---|
| session (resident engine, pid 4880, port 3099, `agentPreset: zabz`) | `session-a0c11144-aba9-400e-a169-fb98a5acf958` | `session-80c0abb7-a1f4-4f02-ab44-74db6e10bb69` |
| `subagent_remote` calls made | 1 | 1 |
| tool result's `MESH-HOST:` | `zabz-tech` | `zabz-tech` |
| node the child ran on | **ZABZ-TECH** (the office desktop) | **ZABZ-TECH** |
| child's own headless session on the target | `session-9975ea6e-e0cb-43a6-9784-0c119ee9b030` | `session-e72cf1c7-04ab-4ca3-b0d2-7cc26d53b760` |
| the file the child read | `C:\Windows\win.ini` | `C:\Windows\System32\drivers\etc\hosts` |
| that read, as the target independently confirms it | identical on both machines → **not discriminating** | desktop `5166116D…ACC47C7` vs laptop `8474E69D…420B9CB` → **discriminating, and the child reported the desktop's** |
| child wall time | 15,464 ms | 35,624 ms |
| `exit` / location check | `0` / `matched configured target host (zabz-tech)` | `0` / `matched configured target host (zabz-tech)` |

Nothing in this document is a model's claim about itself: every location claim was read from the
**target's own** session store, from the **target's own** sshd log, or from a **hash computed on the
target's own disk** by a process that did not run there.

---

## 2. The configuration that was exercised, read from the running engine's own composed tree

The mount itself is `90-provider-mount.md`'s subject; what matters here is that **these are the values
the running engine has**, not what a configuration file intended. Read from
`C:\Users\ezabz\.dsh\profiles\web\cordis.patch.yml` — the layer the loader applies after every bundle
layer, i.e. the layer the running pid 4880 read at boot:

```yaml
[id: 'remote-fanout', config: {
   providerName: 'remote-ssh',
   target:       !!js "process.env.MESH_TARGET_NODE ?? 'desktop-ts'",
   sshExe:       'C:/Program Files/OpenSSH/ssh.exe',
   sshArgs:      ['-o','BatchMode=yes','-o','StrictHostKeyChecking=accept-new','-o','ConnectTimeout=10'],
   remoteShell:  'powershell'          (win32)
   remoteNodeExe:'C:/Program Files/nodejs/node.exe'
   remoteDshBin: '…/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/dsh/lib/bin.js'
   remoteProfile:'headless'
   remoteCwd:    'C:/Users/ezabz'
   targetHosts:  !!js "… : ['zabz-tech']",
   verifyMeshHost: true,
   timeoutMs: 300000, maxOutputBytes: 200000 }]
[id: 'tool-subagent-remote', disabled: true]     # granted per agent, by the `zabz` preset
```

`desktop-ts` is the ssh alias for the office desktop, whose Tailscale DNS label is `zabz-tech` — so
`target` and `targetHosts` agree, and the location check compares the child's reported host against
`zabz-tech`.

---

## 3. How the sessions were created, exactly

Through the **phone gate on loopback**, which is the only door (`71` §0), with the proxy off
(`81` §2 standing rule: *"this laptop's .pac proxy invents 502s"*):

```powershell
# 1. sign in: the gate mints the cookie. A cold read of the engine directly is a 401.
$s2 = $null
$r = Invoke-WebRequest -Uri 'http://127.0.0.1:3086/' -MaximumRedirection 0 -SkipHttpErrorCheck -NoProxy -SessionVariable s2
#    -> 200, Set-Cookie: dsh-auth-<hash>=v1.eyJ2ZXJzaW9uIjoxLCJhdXRob3JpdHkiOiIxMjcuMC4wLjE6MzA5OSIs…; Max-Age=2592000
# 2. the proven RPC shape (scripts/mesh-restart-at-0700.ps1:159-171):
#    POST /api/<method>  {type:'client-request', rpcId:<uuid>, method:'session/create',
#                         payload:{args:<hashtable>}}      # args maps by PARAMETER NAME
```

```
REQUEST  {"payload":{"args":{"request":{"cwd":"C:\\Users\\ezabz\\code","agentPreset":"zabz"}}},
          "method":"session/create","rpcId":"b1d0ff22-…","type":"client-request"}   -> /api/session/create
RESPONSE {"type":"server-response","rpcId":"b1d0ff22-…","result":{"ok":true,
          "value":{"sessionId":"session-a0c11144-aba9-400e-a169-fb98a5acf958","agentPreset":"zabz"}}}

REQUEST  {"…","method":"session/prompt","payload":{"args":{"request":{"requestId":"<uuid>",
          "sessionId":"session-a0c11144-…","mode":"queue","content":[{"type":"text","text":"…"}]}}}}
RESPONSE {"result":{"ok":true,"value":{"accepted":true}}}
```

Two endpoint-shape facts worth carrying, both from error messages rather than from reading a route
table: the request body key must be exactly `request` (the parameter name — `session/create` and
`session/prompt` take `request`, `session/list` takes `_request`), and `/api/session/list` has **no GET
form** — `GET /api/session/list` and `GET /api/tools` both answer `404 not found` from the engine.

Both sessions confirmed `agentPreset: zabz` in the session list before anything was dispatched, and
`/healthz` on the same engine reported the provider's runtime state while they ran.

---

## 4. Run 1 — the raw tool call and its result

The prompt asked the session for **exactly one** `subagent_remote` call and nothing else. From the
session store `…\sessions\--C-Users-ezabz-code--\session-a0c11144-…\session.v3.jsonl.zstd` (10/10 zstd
frames decoded, 165,373 bytes), verbatim:

```json
{"type":"tool/call","seq":17,"time":1789649858854,"data":{"turn":1,"step":1,
 "callId":"call_00_ET_3Ey3uewx0LT9a2S8rGha4909","name":"subagent_remote",
 "arguments":"{\"description\": \"Mesh host probe\", \"prompt\": \"reply with exactly MESH-HOST: <your hostname>, then read one file that exists on your filesystem (for example C:\\\\Windows\\\\win.ini on Windows) and quote its first line verbatim\"}"}}
```

```json
{"type":"tool/result","seq":18,"time":1789649874361,"data":{"turn":1,"step":1,
 "message":{"source":{"kind":"tool","callId":"call_00_ET_3Ey3uewx0LT9a2S8rGha4909"},"content":[
  {"type":"tool-result","toolCallId":"call_00_ET_3Ey3uewx0LT9a2S8rGha4909","content":[{"type":"text","text":
"MESH-HOST: zabz-tech
[remote-ssh] child ran on node \"ZABZ-TECH\" via C:/Program Files/OpenSSH/ssh.exe -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 desktop-ts
transport host = ZABZ-TECH  (recorded by the target shell before the agent started)
transport cwd  = C:\\Users\\ezabz
target profile = headless
location check = matched configured target host (zabz-tech)
exit = 0 in 15464 ms (ssh client terminated after the completion frame)
--- child final message ---
MESH-HOST: zabz-tech

First line of `C:\\Windows\\win.ini`, verbatim:

```ini
; for 16-bit app support
```"}],"isError":false}]...}},"turn":1,"step":1}
```

The session's own final answer, verbatim (assistant message, turn 1 step 2):

```
1. `subagent_remote`

2. Raw tool result text:
```
MESH-HOST: zabz-tech
[remote-ssh] child ran on node "ZABZ-TECH" via C:/Program Files/OpenSSH/ssh.exe -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 desktop-ts
transport host = ZABZ-TECH  (recorded by the target shell before the agent started)
transport cwd  = C:\Users\ezabz
target profile = headless
location check = matched configured target host (zabz-tech)
exit = 0 in 15464 ms (ssh client terminated after the completion frame)
--- child final message ---
MESH-HOST: zabz-tech

First line of `C:\Windows\win.ini`, verbatim:

```ini
; for 16-bit app support
```
```

3. `MESH-HOST: zabz-tech`
```

It called the tool **once** (`tool/call` count in the store: 1), and `agentLoopsRunning` never went
above 2 while it ran — there is no second local child hiding behind it.

**Why `win.ini` was the wrong witness, recorded because it nearly produced a false "different
machine" reading.** The file exists on both machines and is **byte-identical**:
`6B3D6E268DCB76E175A7DB3D9E031349AB2C32654C7E57581A851E64DD6214AB` on ZABZ-YOGA and on ZABZ-TECH
(both `Get-FileHash -Algorithm SHA256`). Quoting its first line therefore proved **nothing** about
location — it only proves the child read a file. Run 2 exists because of this.

---

## 5. Run 2 — the discriminating test, and the target's own record of it

The child's task was changed to a file the two machines **do not share a hash for**, and to print the
hash rather than quote prose (so no model can paraphrase the evidence):

```
C:\Windows\System32\drivers\etc\hosts
  ZABZ-YOGA  (this laptop)     8474E69DEE07BBD794B55947E3817D87C94380D15630FF87DF74D9847420B9CB
  ZABZ-TECH  (the desktop)     5166116D27139C237F6558B328AAAAD93816BB2491E44034D64A9B305ACC47C7
```

The tool result, verbatim from `session-80c0abb7-…`:

```
MESH-HOST: zabz-tech
[remote-ssh] child ran on node "ZABZ-TECH" via C:/Program Files/OpenSSH/ssh.exe -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 desktop-ts
transport host = ZABZ-TECH  (recorded by the target shell before the agent started)
transport cwd  = C:\Users\ezabz
target profile = headless
location check = matched configured target host (zabz-tech)
exit = 0 in 35624 ms
--- child final message ---
MESH-HOST: zabz-tech
HOSTS-SHA256: 5166116D27139C237F6558B328AAAAD93816BB2491E44034D64A9B305ACC47C7
HOSTS-COUNT: 33
```

**The child's independent read matches the desktop's disk and differs from this laptop's.** That is the
assertion no reporter can fake: the machine that printed the hash is the machine whose filesystem
produced it.

### 5.1 From the other side — three independent target-side confirmations

**(a) The target wrote its own session store for the child.** Pulled from `zabz-tech` over ssh
(base64 over an `-EncodedCommand`, then decoded: 13/13 zstd frames), path
`C:\Users\ezabz\.dsh\sessions\--C-Users-ezabz--\session-e72cf1c7-04ab-4ca3-b0d2-7cc26d53b760\session.v3.jsonl.zstd`:

```json
{"type":"session","version":3,"id":"session-e72cf1c7-04ab-4ca3-b0d2-7cc26d53b760",
 "createdAt":1789650071934,"cwd":"C:\\Users\\ezabz","isSeeded":false,"delegationDepth":0}
{"type":"tool/call","data":{"name":"pwsh","arguments":
 "{\"command\": \"hostname; (Get-FileHash -LiteralPath C:\\\\Windows\\\\System32\\\\drivers\\\\etc\\\\hosts -Algorithm SHA256).Hash; (Get-Content … | Measure-Object -Line).Lines\"}"}}
{"type":"tool/result","data":{"message":{"content":[{"content":[{"text":
 "zabz-tech\n5166116D27139C237F6558B328AAAAD93816BB2491E44034D64A9B305ACC47C7\n30"}]}]}}}
{"type":"assistant/message","data":{"turn":1,"step":2,"message":{"content":[{"text":
 "MESH-HOST: zabz-tech\nHOSTS-SHA256: 5166116D27139C237F6558B328AAAAD93816BB2491E44034D64A9B305ACC47C7\nHOSTS-COUNT: 33"}]}}}
```

`cwd: C:\Users\ezabz` is the provider's configured `remoteCwd`, `delegationDepth: 0` is a fresh
headless root, and the session was **created at 09:01:11.934 local**, inside the dispatch window. Run
1's child left the same shape: `session-9975ea6e-e0cb-43a6-9784-0c119ee9b030`, `cwd: C:\Users\ezabz`,
`createdAt` 08:57:51.410 local — containing the two tool calls the brief's own words
produced, `pwsh {"command":"hostname"}` and `read {"file_path":"C:\\Windows\\win.ini","limit":5}`, and
the reply `MESH-HOST: zabz-tech`.

**(b) The target's sshd log records the connection, from this laptop's tailnet address.**

```
# Get-WinEvent -LogName OpenSSH/Operational on zabz-tech, 09:00:40 .. 09:01:40
9/17/2026 9:00:48 AM  4 sshd: Accepted publickey for ezabz from 100.72.162.5 port 1077 ssh2: ED25519 SHA256:l5dDkcKHjGIz1JaT5APz6iONDTuM4McDzYl8Zb7qWtc
9/17/2026 9:01:23 AM  4 sshd: Received disconnect from 100.72.162.5 port 1077:11: disconnected by user
9/17/2026 9:01:23 AM  4 sshd: Disconnected from 100.72.162.5 port 1077
```

`tailscale ip -4` on this laptop is **100.72.162.5** — the source of that connection. Run 1's window
holds the matching record (`8:57:39 AM … from 100.72.162.5 port 1051`). The three clocks agree:
my prompt at **09:00:44.746**, the ssh connection at **09:00:48.281**, the child's session store
created at **09:01:11.934**, final message at **09:01:22.9**, `exit = 0 in 35624 ms`.
*(A timing note stated as a measurement, not a claim: the provider's own report says 35,624 ms, while
the sshd connection it reported "terminated after the completion frame" spans 09:00:48→09:01:23 =
35.1 s. The provider settles on the completion frame and then kills the client.)*

**(c) The target's OpenSSH log is complete for the window.** A confidence check on the log source
itself: sampling the desktop's own records between 08:50:00 and 09:03:30 returns every timestamp in
that span including the 08:57:39 and 09:00:48 connections — i.e. the window that contains our evidence
is within the log's retention, so the absence of *other* dispatch records in it is a real absence.

---

## 6. Flatness and the loop counter, measured

**Method.** One sampler, one counter set, samples at a fixed period, `Get-Counter
'\Memory\Committed Bytes'` (the quantity the broker reasons about — `84-calibration.md` §1.3), plus
`\Memory\Available MBytes`, the `node.exe` process count and working set, the engine's own working set,
and `GET /healthz` → `sessions.agentLoopsRunning` / `sessions.subagents` / `sessions.live`.
Two windows per run: **CONTROL** (immediately before the prompt) and **FLEET** (from the prompt until
the session settled), same period, same rig. A third **IDLE** window was taken afterwards for the
control comparison §6.3 uses.

### 6.1 The samples

**Run 1** — 8 control + 8 fleet samples, ~3 s period (3.07 s actual), 2026-09-17T08:56:55–08:58:14 local:

| window | n | first commit (B) | last (B) | delta | min → max (B) | range | node.exe | agentLoopsRunning |
|---|---|---|---|---|---|---|---|---|
| CONTROL | 8 | 17,903,235,072 | 17,618,812,928 | −284,422,144 (−0.265 GiB) | 17,486,032,896 → 17,903,235,072 | 0.389 GiB | 11–12 | 1 (one sample 2) |
| FLEET | 8 | 17,548,656,640 | 17,279,078,400 | −269,578,240 (−0.251 GiB) | 17,116,688,384 → 17,548,656,640 | 0.402 GiB | **11 only** | 2 (last sample 1) |

**Run 2** — 10 control + 12 fleet samples, 2.03 s period, 2026-09-17T09:00:03–09:01:37 local:

| window | n | first commit (B) | last (B) | delta | min → max (B) | range | node.exe | agentLoopsRunning |
|---|---|---|---|---|---|---|---|---|
| CONTROL | 10 | 17,388,691,456 | 17,422,192,640 | +33,501,184 (+0.031 GiB) | 17,249,992,704 → 17,422,192,640 | 0.160 GiB | 11–12 | 1 throughout |
| FLEET | 12 | 17,502,052,352 | 18,453,237,760 | **+951,185,408 (+0.886 GiB)** | 17,248,731,136 → 18,979,143,680 | **1.612 GiB** | **11 only** | 2,2,3,3,3,3,3,3,2,2,1,1 |

**Idle control window** — 15 samples, 2.03 s period, 09:02:31–09:03:29 local, after both children:

| window | n | first (B) | last (B) | delta | min → max (B) | range | node.exe | agentLoopsRunning |
|---|---|---|---|---|---|---|---|---|
| IDLE | 15 | 18,559,782,912 | 17,606,750,208 | −953,032,704 (−0.888 GiB) | 17,381,257,216 → 18,716,995,584 | **1.244 GiB** | **11 only** | 1 (last two 2) |

### 6.2 What the loop counter says, and its known blindness

`agentLoopsRunning` **did** move during a dispatch: 1 → 2 → 3 in run 2, and it stayed at 2 for the
whole of run 1's fleet window (run 1's prompt was a single tool call; run 2's child re-derived the line
count with a second tool call, which is the extra loop). It fell back to 1 as the turn settled.

**`sessions.subagents` read 0 in every one of the 45 samples**, including the samples with
`agentLoopsRunning: 3`, which confirms `84-calibration.md` §5.2's finding directly: the engine's
session store is **blind to the remote child** — the child is a separate `--profile headless` process
on another machine, and the number the contract publishes as "subagents" is a count of the *resident*
engine's own subagent rows, not of dispatched work. Equally important for anyone reading 84 §5.2
literally: `agentLoopsRunning` is **not** blind to a dispatch, but what it rises by is **the parent's
own loop**, not the child's.

### 6.3 Flatness: what is proven, and what is not

**Proven, and it is the criterion that matters:**

* **Zero new `node.exe` processes on this laptop during either dispatch.** 11 in every single FLEET
  sample of both runs (run 1 control had one 12-sample). The child's whole agent turn — its own node
  process, its own profile boot — happened on the target. This is `81` §0.4's *"no new agent loops on
  the client"* in its measurable form, and it is exactly the structural claim `70-remote-fanout-proof.md`
  §2.4 made for the `mesh` profile: *the parent spawns nothing but an ssh client, and each child's whole
  turn happens in the target's process.*
* **The client's commit behaviour is not separable from the client's own work, and this rig cannot
  separate it.** Run 1's two windows are indistinguishable (−0.265 vs −0.251 GiB). Run 2's fleet window
  (+0.886 GiB, range 1.612 GiB) is **larger than** the post-dispatch idle window's range over the same
  period (1.244 GiB) but **comparable to its net movement** (−0.888 GiB) — i.e. the machine moves that
  much when nobody dispatches anything. **The honest reading is "consistent with the machine's own
  noise", not "flat".**

**Why the residual movement is not the child.** The window was not clean, and the reason is in the
engine's own session list: at 09:00:54, mid-run-2, the most recently updated session in that engine was
`session-e34dd061-…` — **this acceptance session's own parent**, which was generating agent steps,
tool calls and a status check inside the same window, on the same machine, in the same engine. The
sampler itself contributes too (`Get-Counter`, `Get-Process`, one `/healthz` + one `session/list` per
sample). A resident-engine acceptance test is structurally unable to leave the resident engine idle,
and that is a **measurement gap, stated rather than worked around**: the correct control would be a
resident engine with exactly one loop running *neither* dispatching nor being sampled, which is not the
machine this test had.

**Deliberately not claimed:** any absolute ±1 GiB flatness figure. `90` §7 retires that criterion —
an *idle* laptop was measured moving 0.416–1.203 GiB per 30–176 s — and the idle window here measured
**1.244 GiB of range in 58 s** with nothing dispatched at all, which is the same verdict from a third
independent night. The criterion that survives is the one in §6.3's first bullet: **process count, not
commit.**

---

## 7. Cost, and what was left behind

| what | where | detail |
|---|---|---|
| 2 sessions created on the owner's engine, on the `zabz` preset | ZABZ-YOGA (pid 4880) | `session-a0c11144-…` ("Run single remote subagent test", 1 turn, 2 steps) and `session-80c0abb7-…` ("Remote subagent run for hosts hash check", 1 turn, 2 steps) — both idle, neither of the owner's |
| 2 real agent turns on the target | ZABZ-TECH | 15.5 s and 35.6 s; 4 model calls total across both children (2 steps each) |
| the only writes outside `%TEMP%`-style scratch | ZABZ-YOGA, `C:\Users\ezabz\mesh91\` | this session's scratch: `rpc.ps1`, `driver.ps1`, `driver2.ps1`, `samples*.csv`, `driver*.log`, `session*.jsonl`, `child*-desktop.*`, `cookie.*`. Nothing in a repository, nothing under `.dsh` |
| the target's own artifacts | ZABZ-TECH, `C:\Users\ezabz\.dsh\sessions\…` | two headless child session stores — the target's *normal* record of work it was given, not something this test installed |
| **engine restarts** | none, anywhere | this laptop's pid 4880 booted 08:51:07 and served every request in this document; the desktop's pid 26140 booted 08:50:35 and was never touched |

Spend: two child turns plus three short parent turns at `deepseek-flash`, a few thousand tokens each —
the smallest shape that answers the question.

---

## 8. What could not be verified, stated as refusals

* **A perfectly clean flatness window.** §6.3. The parent session this test runs in cannot be switched
  off while the test runs, and no other idle resident engine exists to run it from. What would answer
  it: run the same dispatch from a resident engine whose only other session is a passive observer on a
  *third* machine, sampling ZABZ-YOGA's commit over the wire.
* **`agentLoopsRunning` as a per-child counter.** It moved, but the movement is the parent's loop; no
  sample in either run distinguishes "parent waiting on a child" from "parent thinking". §6.2.
* **The provider's own log line for these two runs.** `90` §4.1 records that host-plane plugin log
  lines are not durable in the `web` profile, and nothing here contradicts it: the evidence is by
  effect (the tool result, the target's session store, the target's sshd log, the target's disk hash),
  not by a provider log.
* **The v2 HTTP transport from a resident engine.** Not in scope and not attempted: this provider row
  dispatches over **ssh** (`[remote-ssh]` … `C:/Program Files/OpenSSH/ssh.exe … desktop-ts`), as
  configured. The route (`plugin-mesh-http`) is mounted on both nodes and answers on both — see §9.
* **Anything at all about `secratary` or the Mac Mini.** Not touched.

---

## 9. One incidental finding, and it is a real one

**This laptop is now a deployed v2 node, and `83-http-transport.md` §1 and §9 are stale about it.**
Measured 13:00:05Z, through the gate and on loopback, byte-identical:

```
GET http://127.0.0.1:3099/mesh/health  -> 200
GET http://127.0.0.1:3086/mesh/health  -> 200
{"ok":true,"service":"mesh-http","protocol":"mesh-http-v1","version":"0.1.0","route":"/mesh/run",
 "host":"zabz-yoga","node":"zabz-yoga","nodeSource":"tailscale status --json Self.DNSName",
 "fqdn":"","platform":"win32",
 "auth":{"scheme":"hmac-sha256-over(timestamp,nonce,body)","secretConfigured":true,
         "secretPath":"C:/ProgramData/dsh-mesh.env","secretReason":null,"skewSeconds":120,"secretBytes":64},
 "limits":{"maxBodyBytes":262144,"maxPromptChars":32000,"maxTimeoutSec":3600,"defaultTimeoutSec":900,
           "oneRunAtATime":true},
 "runner":{"busy":false,"inFlight":null,"started":0,"completed":0,"failed":0,"refusedBusy":0,
           "timedOut":0,"lastStartAt":null,"lastEndAt":null},"at":"2026-09-17T13:00:05.661Z"}
```

The desktop answers the same shape with `"node":"zabz-tech","fqdn":"zabz-tech.tail93e6e6.ts.net"`.
**Two things in the laptop's own answer are worth a stream that owns that package:**

1. **`fqdn` is empty while `nodeSource` claims `tailscale status --json Self.DNSName`.** The value
   `zabz-yoga` is `os.hostname()`; `tailscale status` run from the engine's environment did not produce
   a DNS name, and the field that says which of the three sources was used *names the source that
   failed*. `nodeSource` is used by readers to decide whether to trust `node`; here it overstates.
   `tailscale ip -4` on this machine answers `100.72.162.5` and `tailscale status --json`'s
   `Self.DNSName` is `zabz-yoga-1.tail93e6e6.ts.net.`, so the data is available to a process that asks —
   the check itself is what is wrong. Not this file's to fix.
2. The docs above should stop saying this node is "v1-only" and needs "one restart window, and nothing
   else" (§3.4/§10 of `83`). It had that window, it took it, and it is now a v2 node.

**Also worth recording, since the broker keys on it:** this node's Tailscale DNS label is
**`zabz-yoga-1`**, its Windows hostname is **`zabz-yoga`**, and its `mesh-http` identity reports
`node: "zabz-yoga"` with an empty fqdn. That is the `zabz-yoga-1` vs `zabz-yoga` trap of
`70-remote-fanout-proof.md` §2.6 rule 1 and `83` §8, live, in a node's own capacity answer.

---

## 10. What this closes

`90-provider-mount.md` §7 listed *"a cross-node child from a resident engine"* as unverified, and §8
named the exact command that would close it. **It is closed:** from a session on the `zabz` preset in
the resident engine the owner works in, one `subagent_remote` call produced a real agent turn on
ZABZ-TECH, the child reported `MESH-HOST: zabz-tech`, the provider's location check matched
`targetHosts: ['zabz-tech']`, and the target's own session store, sshd log and filesystem hash all say
the same thing independently of the model that wrote the report.

The sentence *"the mesh routes your agents across the mesh"* is therefore a **measurement**, for the
configuration `profiles/web/cordis.patch.yml` now carries, on this engine, since its 08:51 boot.

**One residual, stated plainly rather than folded into the win:** the client's memory did not stay
provably flat, and §6.3 explains why that cannot be settled by a test that runs inside the client. The
process-count half of the flatness criterion — the half that is a claim about *where the work ran* — is
flat and unambiguous.
