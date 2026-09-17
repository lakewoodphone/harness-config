# dsh-plugin-mesh-http — transport v2: a route on the node instead of an ssh session into it

One host-plane row. It owns two HTTP routes on the engine that mounts it:

| route | auth | what it is |
|---|---|---|
| `POST /mesh/run` | its own HMAC-SHA256 over the body + a timestamp + a nonce | run ONE agent turn on this node and answer with `{exitCode, stdout, stderr, host, ms}` |
| `GET /mesh/health` | none, deliberately | how a dispatcher learns — before it spends a prompt — whether this node has the route and a usable secret |

Reached through the gate that already runs on every node: `tailscale serve` publishes
`https://<node>.tail<tailnet>.ts.net/`, the gate answers its own routes and relays everything else to
the engine on loopback, and the gate's device allow-list refuses a device it would not sign in at
all *before* it relays anything. So there are two independent controls in front of the run, and the
route's own MAC is the one that authenticates the CALLER rather than the device.

## Why it exists

Transport v1 is `ssh <node> dsh --profile headless`. It works and it is fragile in three measured
ways, each of which has already cost a night:

* a Windows node's sshd session could not read through its own profile junctions until they were
  recreated **inside an ssh session** (`docs/mesh/70-remote-fanout-proof.md` §4.4);
* Win32-OpenSSH's client does not exit when its stdout is a pipe (§4.1) and can hold a session open
  after the work is done (§4.2);
* the Mac Mini's tailnet path is relayed and flaky (`docs/mesh/81-overnight-program.md` §2).

A child started by this route is a child of **the engine**, whose own logon session is the one that
already resolves the profile's bundles — which is exactly why the reparse-point failure cannot
happen to it. The full argument, the contract, the auth limits and the raw proof are in
`docs/mesh/83-http-transport.md`.

## Install on a node

```powershell
node packages/plugin-mesh-http/bin/mesh-http.mjs secret      # create the shared secret (0640 / ACL)
node packages/plugin-mesh-http/bin/install-mesh-http.mjs     # junction + one name in dsh.profile.bundles
node packages/plugin-mesh-http/bin/mesh-http.mjs check       # prove it is ready
# then RESTART that node's engine: a mounted bundle cannot hot-load (P210)
```

`mesh-http.mjs` is also the keeper: `clean` ages out run artifacts, `serve` mounts exactly what the
engine mounts on a bare HTTP server (no engine required), and `probe` asks every node in the roster
whether it answers.

## Files, and what each one is for

| file | what it is |
|---|---|
| `lib/index.js` | the Cordis row: config, `createMeshHttp`, route registration when `webServer` exists |
| `lib/auth.js` | the MAC (`mesh-http-v1`), the constant-time compare, and the bounded replay ledger |
| `lib/secret.js` | the secret file: `KEY=VALUE`, re-read when it changes so rotation needs no restart |
| `lib/body.js` | bounded raw intake — the ceiling is checked against the declared length and the running total |
| `lib/runner.js` | one run at a time, a hard wall clock, capped output, and the `MESH-HOST` preamble |
| `lib/handler.js` | the whole request contract, in the order it happens |
| `lib/node-identity.js` | the name this node reports — never the caller's |
| `bin/mesh-dispatch.mjs` | the client: v2 first, then an EXPLICIT AND LOGGED v1 fallback |
| `bin/install-mesh-http.mjs` | the keeper for the junction and the bundle list |
| `bin/mesh-http.mjs` | the keeper CLI: `secret`, `check`, `clean`, `serve`, `probe` |
| `ssh-run.ps1` | run a program on another Windows node with no quoting surface (`-EncodedCommand`) |
| `ship-to-node.ps1` | deliver this directory to another node over an ssh stdin pipe |
| `probe-posix.ps1`, `probe-node-posix.sh`, `probe-node.ps1`, `who-is-working.ps1`, `restart-readiness.ps1` | read-only reconnaissance on a node |

## Deliberate limits, stated so nobody has to rediscover them

* **One run at a time per node.** A second request answers `429` with a position, never a queue and
  never a crash. One generating turn costs ~0.81 GB commit and ~1 core (`71` §2.2); a route that
  accepted a fleet would be an uncapped fleet, which is the failure the admission governor exists to
  stop.
* **No continuable children.** One prompt, one final message — the same limit transport v1 has.
* **Not encryption.** The MAC authenticates; it does not hide. The threat model is written as what
  an attacker can and cannot do in `docs/mesh/83-http-transport.md` §4.
* **A resident engine must restart to mount it.** That is P210, not a choice this package makes.
