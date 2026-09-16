# 73 — `zabz-tech-linux` as a mesh node: what was installed, and the raw output that proves it

**Program:** `docs/mesh/` stream **S2** (`docs/mesh/71-mesh-program.md` §3 — "linux-pc as a node").
**Date:** 2026-09-16 23:14–23:24Z (19:14–19:24 EDT on the node). **Author:** a delegated S2 session, not
the owner. **Status:** provisioned and verified; **not committed** (the manager integrates).
**Files owned and written by this stream:** `scripts/provision-mesh-node.sh`, this file.
`scripts/phone-gate.py` is **S1's** and was copied verbatim, never edited.

**What was executed, in one line each:** a nodejs.org tarball was installed under `~/.local`; DSH was
installed with `npm ci` from the authority's lockfile; the gate was deployed and started under systemd;
one engine was started **loopback-only** under systemd with `HOME` and `DSH_HOME` set; `tailscale serve
--bg 3086` published the gate. No engine on any other machine was touched, no tailnet ACL was changed,
and nothing was written into the harness-config checkout on the node.

---

## 0. The node, as it now stands (all measured on the node, 2026-09-16 ~23:23Z)

| | |
|---|---|
| hostname / tailnet FQDN | `zabz-tech-linux` · `zabz-tech-linux.tail93e6e6.ts.net` |
| ssh alias | `linux-pc-ts` |
| OS / arch | Ubuntu 24.04.3 LTS (noble) · kernel 6.8.0-111-generic · x86_64 |
| Node | **v22.23.2** at `~/.local/node/bin/node` (`~/.local/node` → `~/.local/node-v22.23.2-linux-x64`), plus `/usr/local/bin/{node,npm,npx,corepack}` |
| DSH | **0.1.5-rc.1** at `~/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js` |
| launcher | `/usr/local/bin/dsh` — resolves the interpreter, exports the credentials env, execs bin.js |
| engine | `dsh-engine.service` — `web --port 3099 --no-open --trusted-host zabz-tech-linux.tail93e6e6.ts.net`, loopback only |
| gate | `phone-gate.service` — `/usr/bin/python3 …/phone-gate.py --listen-port 3086 --engine-port 3099` |
| door | `tailscale serve`: `https://zabz-tech-linux.tail93e6e6.ts.net/` → `http://127.0.0.1:3086` |
| credentials | `/etc/dsh-worker.env`, mode `640 root:zabz` (the model key is **not** in `~/.dsh/.credentials.yaml`) |
| one-shot transport | `ssh linux-pc-ts 'cd ~/code && dsh --profile headless "<task>"'` — measured, `MESH-HOST:` verified |
| disk | **20.8 GiB free** on `/` (96 % used) — see §3 |
| RAM / swap | 11 673 MiB total, ~10 120 MiB available, swap 631 of 4 095 MiB used (15.4 %) |
| CPU | 12 logical / 6 physical (i5-11400), load1 ≈ 0.2 |

Nothing listens on a routable interface except ssh and Tailscale's own 443:

```
LISTEN 0 4096  100.105.248.90:443    0.0.0.0:*      <- tailscale serve
LISTEN 0 4096           0.0.0.0:22   0.0.0.0:*
LISTEN 0 128        127.0.0.1:3086   0.0.0.0:*      <- phone-gate
LISTEN 0 511        127.0.0.1:3099   0.0.0.0:*      <- the engine, loopback only
```

---

## 1. The commands, and their raw output

### 1.1 Before: `provision-mesh-node.sh --check`

```
$ scripts/provision-mesh-node.sh -H linux-pc-ts --check
--- runtime ---
node: NOT ON PATH
~/.local/node*: absent
--- dsh ---
~/dsh-engine: absent
~/.dsh: absent
--- apt nodejs (must NOT be used) ---
  Installed: (none)
--- tailscale ---
zabz-tech-linux.tail93e6e6.ts.net.
No serve config
--- units ---
inactive
inactive
--- authority ---
secratary
v22.23.2
--- work root ---
/: 21 GiB free
```

`apt-cache policy nodejs` → `Candidate: 18.19.1+dfsg-6ubuntu5`, and 62 §1.1 is why that candidate must
never be used: `@deepseek-ai/dsh/lib/bin.js:168` is `if (import.meta.main)`, which does not exist below
Node 22.18 — the process would **exit 0 having done nothing**.

### 1.2 The provisioning run

```
$ scripts/provision-mesh-node.sh -H linux-pc-ts
   pinned to the authority's own version: v22.23.2
   v22.23.2 is >= 22.18, so import.meta.main exists
+ curl -fsSL -o /home/zabz/.local/node-v22.23.2-linux-x64.tar.xz https://nodejs.org/dist/v22.23.2/node-v22.23.2-linux-x64.tar.xz
+ curl -fsSL -o /home/zabz/.local/SHASUMS256.txt https://nodejs.org/dist/v22.23.2/SHASUMS256.txt
   sha256 verified: d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307
+ tar -xJf /home/zabz/.local/node-v22.23.2-linux-x64.tar.xz -C /home/zabz/.local
+ ln -sfn /home/zabz/.local/node-v22.23.2-linux-x64 /home/zabz/.local/node
+ /home/zabz/.local/node/bin/node -v
v22.23.2

== 3. DSH install (npm ci from the authority's package-lock.json — pinned, not ranged)
+ ssh secratary "cat dsh-engine/package-lock.json" > /home/zabz/dsh-engine/.incoming/package-lock.json
   @deepseek-ai/dsh pinned by the lock to 0.1.5-rc.1 (lock sha256 b6bf70b058d0cc67…)
+ env PATH=… /home/zabz/.local/node/bin/npm --prefix /home/zabz/dsh-engine ci --omit=dev --no-audit --no-fund
npm warn deprecated node-domexception@1.0.0: Use your platform's native DOMException instead
added 524 packages in 11s
+ /home/zabz/.local/node/bin/node …/dsh/lib/bin.js --version
0.1.5-rc.1
   headless + base + web bundles present in the install

== 4. credentials -> /etc/dsh-worker.env (0640 root:zabz)
wrote 2 credential(s): DEEPSEEK_API_KEY DEEPINFRA_API_KEY
+ sudo -n install -m 0640 -o root -g zabz /home/zabz/.dsh-mesh/worker.env.new /etc/dsh-worker.env
   wrote 640 root zabz; no value is ever printed

== 5. launcher /usr/local/bin/dsh
+ env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin /usr/local/bin/dsh --version
0.1.5-rc.1

== 6. systemd units
   FQDN: zabz-tech-linux.tail93e6e6.ts.net
+ sudo -n systemctl enable dsh-engine.service phone-gate.service
+ sudo -n systemctl restart dsh-engine.service
+ sudo -n systemctl restart phone-gate.service
   dsh-engine.service active
   phone-gate.service active

== 7. tailscale serve: https 443 -> 127.0.0.1:3086
+ sudo -n tailscale serve --bg 3086
Available within your tailnet:
https://zabz-tech-linux.tail93e6e6.ts.net/
|-- proxy http://127.0.0.1:3086
Serve started and running in the background.
   PUBLISHED: https://zabz-tech-linux.tail93e6e6.ts.net/ -> 127.0.0.1:3086
```

`npm ci` took **11 s** and added **524 packages** (the lockfile describes 583, of which the rest are
root-less platform variants). It is the slow step; every other step is seconds.

### 1.3 The verification commands — the ones that matter

**`node --version` on that machine (the interpreter is new enough):**

```
$ ssh linux-pc-ts 'node --version'
v22.23.2
```

**One completed headless turn (this single command proves the interpreter, the credentials, the API and
the toolbelt all at once):**

```
$ ssh linux-pc-ts 'cd ~/code && dsh --profile headless "Reply with exactly: NODE OK"; echo "exit=$?"'
NODE OK
exit=0
```

Reasoning goes to stderr (a `dsh: reasoning:` block), the final answer to stdout, exit 0. Elapsed
**3 s** in the run above and 3–5 s across every repeat. The *string on stdout* is the discriminating
part, not the exit code: a too-old Node also exits 0, having printed nothing.

**The same thing through the v1 mesh transport, from the laptop, with the `MESH-HOST:` proof that
71 §2.4 requires:**

```
$ ssh linux-pc-ts 'cd ~/code && time dsh --profile headless "Run the bash tool: hostname. Then reply
  with exactly one line and nothing else: MESH-HOST: followed by that hostname."'
MESH-HOST: zabz-tech-linux
exit=0
real    0m4.868s
```

That is the transport `mesh-run` (S6) will use, working end to end, with a child that used the bash
tool and reported where it ran.

**The gate, and the capacity route S1 owns** (`71` §2.1), against gate revision `24b442ab…` — the
current one on this node and on secratary:

```
$ ssh linux-pc-ts 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3086/'
200
$ ssh linux-pc-ts 'curl -s http://127.0.0.1:3086/mesh/capacity'
{"schema": 1, "node": "zabz-tech-linux", "fqdn": "zabz-tech-linux.tail93e6e6.ts.net",
 "at": "2026-09-16T23:25:42Z",
 "cpu": {"logical": 12, "physical": 6, "load1": 0.08},
 "mem": {"totalMiB": 11673, "freeMiB": 10234, "swapUsedPct": 15.4},
 "disk": {"workRoot": "/home/zabz/code", "freeGiB": 20.8},
 "agents": null,
 "governor": {"budgetSlots": 24, "inUse": 0, "queued": 0},
 "accepts": {"oneShot": true, "fleet": true, "maxChildren": 12,
   "reason": "slot budget computed from memory; no governor lease directory on this node, so inUse is reported as 0 and is not measured"}}
```

The same route **from the laptop over the tailnet** — the path the broker will read it on — also answers
`HTTP 200` with the identical document, so `tailscale serve` preserves the path and the gate answers
before any sign-in logic.

**A live contract change S5 must know about.** On the previous gate revision (`ec17db22…`, deployed
here at 23:22Z and read at 23:23Z) this node answered `"governor": null` and
`"accepts": {"oneShot": true, "fleet": false, "maxChildren": 0, "reason": "no governor lease directory
on this node, so its slot budget cannot be measured: one-shot runs are accepted, fleets are not placed
here"}`. Under `24b442ab…` the same node, with no governor lease directory,
answers `fleet: true, maxChildren: 12`. Both were measured on this node within three minutes of each
other; S1 owns that change. **The node is now offered for fleets while its free space is 0.8 GiB above
the 20 GiB floor `71` §2.2 sets for exactly that kind of placement** — see §5.3.

**`tailscale serve status`:**

```
$ ssh linux-pc-ts 'tailscale serve status'
https://zabz-tech-linux.tail93e6e6.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:3086
```

**`mesh-health.ps1` (S2's acceptance command):**

```
$ pwsh -NoProfile scripts\mesh-health.ps1 -Nodes 'zabz-tech-linux' -TimeoutSec 25
zabz-tech-linux.tail93e6e6.ts.net degraded
    PASS: GET / (cold visitor with a cookie jar) -> 200
    PASS: GET /api (no cookie) -> 401
    WARN: GET /healthz -> 404 (plugin-health not mounted on this node)
```

Same three lines, word for word, that **`secratary` itself produces today**. §5.1 states plainly why
the word is `degraded` and not `healthy`, and why that is the *correct* word for this platform rather
than a fault I left behind.

### 1.4 Idempotency — the second and third runs

Re-running the script is a no-op except where something genuinely differs. From the second run:

```
   already installed and self-consistent: /home/zabz/.local/node-v22.23.2-linux-x64 (v22.23.2)
   already installed: @deepseek-ai/dsh 0.1.5-rc.1 — skipping npm ci
   already present (640 root zabz) — left untouched (--force to rewrite)
   unchanged — left in place                       <- the launcher
   /etc/systemd/system/dsh-engine.service unchanged
   /etc/systemd/system/phone-gate.service unchanged
   dsh-engine.service already running with this unit — not restarted
   phone-gate.service already running this exact file — not restarted
   already published                               <- tailscale serve
   ACCEPT /home/zabz/code/_worktrees: 20 GiB free >= 20
```

The gate restarts **only when the file's sha256 changes**, which is exactly the mechanism that lands a
new S1 revision: re-run the script and the new `phone-gate.py` is pushed and the unit restarted. That
happened twice during this session (S1 was editing the file live) and both times the node picked the
new revision up without any other action.

---

## 2. What was installed, and where

| path | bytes | mode / owner |
|---|---|---|
| `~/.local/node-v22.23.2-linux-x64/` | 204 MB | `zabz:zabz` |
| `~/.local/node` (symlink → the above) | — | stable interpreter path |
| `~/dsh-engine/` (DSH + 524 packages) | 324 MB | `zabz:zabz` |
| `~/dsh-mesh/repo/` (gate, assets, this script) | 484 KB | `zabz:zabz` |
| `~/.dsh/` (profiles, sessions, storages, `.credentials.yaml`) | 1.4 MB | `zabz:zabz` |
| `~/.dsh-phone/` (engine + gate logs, incl. the launch token) | 32 KB | `zabz:zabz` |
| `~/.dsh-mesh/` (`provisioned.json`, `workroot.json`, `provision-*.log`) | 88 KB | `zabz:zabz` |
| `/etc/dsh-worker.env` | 108 B | **`640 root:zabz`** |
| `/usr/local/bin/dsh` | 800 B | `0755 root:root` |
| `/usr/local/bin/{node,npm,npx,corepack}` | symlinks | into `~/.local/node/bin` |
| `/etc/systemd/system/dsh-engine.service` | | `0644 root:root`, enabled |
| `/etc/systemd/system/phone-gate.service` | | `0644 root:root`, enabled |

**Total ≈ 530 MB.** Nothing was installed with apt. Nothing from nodejs.org below v22.18 was installed.
`~/.dsh-phone/engine-3099.log` carries a one-time `?token=` per engine start — **treat that file as a
secret**, exactly as `scripts/serve-phone.sh` says; the gate reads the live token from it.

Deployed revisions, by content:

| file | sha256 | note |
|---|---|---|
| `~/dsh-mesh/repo/scripts/phone-gate.py` | `24b442abf5357a64…` | the repo working copy at 23:25Z; **also the revision secratary now runs** |
| `~/dsh-mesh/repo/provision-mesh-node.sh` | `f108326619b26dd1…` | byte-identical to the repo copy; the node can re-run it on itself |

The gate revision on the node moved twice during this session as S1 worked
(`d11d774f…` → `ec17db22…` → `24b442ab…`), and both moves were picked up by re-running
`provision-mesh-node.sh` — which is the whole reason that re-run path exists. Everything in §1.3 was
re-measured against `24b442ab…` after the last move.

### The credentials decision, because it is the one that could bite

The model key is **only** in `/etc/dsh-worker.env` (`640 root:zabz`), read by the engine through
`EnvironmentFile=`. It was **not** copied into `~/.dsh/.credentials.yaml`, and this was verified rather
than assumed — that file exists (the engine creates it for its browser-session grant, mode `0600`), and
it contains exactly one record and no model key:

```
1 version: <redacted>
2 records:
3   client-connection/browser-session:
4     kind: <redacted>
5     payload:
6       version: <redacted>
7       secret: <redacted>
$ grep -c "DEEPSEEK_API_KEY\|sk-" ~/.dsh/.credentials.yaml
0
```

So `dsh-credentials-local`'s precedence gives the environment the win, a write that the environment
would shadow is refused (62 §1.5(a)), and **an agent running on this node cannot rewrite its own model
credential**. `640 root:zabz` and not `0600 root:root` is deliberate: `/usr/local/bin/dsh` sources that
file for the `ssh … dsh --profile headless` transport, which runs as `zabz`, and any process running as
`zabz` could read the running engine's environment anyway.

The key never appeared on a command line and never appeared in this session's transcript: the script
pipes the authority's `refs:` block through a parser that prints **key names only**, writes the file
with `install -m 0640`, and shreds the intermediate. `--force` is required to overwrite an existing
env file, so a rotation is never silently clobbered.

---

## 3. Disk is the constraint, and this node sits on the threshold

62 §3.1 measured 22 GB free (`df -h`, rounded) before anything was installed. The honest figure from
`df -Pk`, and the one the capacity route reports, is **20.8 GiB** — after this install:

```
$ ssh linux-pc-ts 'df -Pk /home; df -Ph /home'
Filesystem     1024-blocks      Used Available Capacity Mounted on
/dev/nvme0n1p2   490048472 443257160  21824708      96% /
/dev/nvme0n1p2       468G     423G       21G      96% /
```

0.6 GB of the drop is this install (204 MB runtime + 324 MB `dsh-engine`). **The node is now 0.8 GiB
above the 20 GiB fleet floor, and nothing else has been written to it yet.**

`provision-mesh-node.sh` therefore:

* **refuses to establish a fleet worktree root** on a filesystem with `freeGiB < 20` (`--min-work-free-gib`,
  default 20), writing the verdict to `~/.dsh-mesh/workroot.json` and **never creating the directory**;
* exposes that judgement as a standalone, read-only gate any dispatcher can call:

  ```
  $ scripts/provision-mesh-node.sh -H linux-pc-ts --assert-work-root
  ACCEPT /home/zabz/code/_worktrees: 20 GiB free (>= 20)          exit 0
  $ scripts/provision-mesh-node.sh -H linux-pc-ts --assert-work-root --min-work-free-gib 25
  REFUSE /home/zabz/code/_worktrees: 20 GiB free (< 25) — not enough for a fleet worktree root   exit 20
  ```

  Both branches were run; the second is how the refusal path was exercised without waiting for the disk
  to fill up. **Exit code 20 is the refusal**, and it is distinct from 0/2/3/4 so a caller can branch.

Two safe reclaims exist and were **measured but deliberately NOT taken** (3.5 GiB of journald + 476 MB of
apt cache). They are opt-in behind `--reclaim`:

```
   reclaim available but NOT requested (--reclaim): journald 3.5G, apt cache 476M
```

They would move the node from 20.8 GiB to roughly 24.5 GiB — five extra worktrees' worth — and that is a
decision about a machine holding four external volumes of customer recovery data, not a provisioning
step. `journalctl --vacuum-size=500M` and `apt-get clean` are the two commands the flag runs.

**What this node is sized for, stated plainly:** a fleet of *agent turns* — `ssh + --profile headless`,
each of which writes only into `~/.dsh/sessions` and `~/.dsh/storages`. It is **not** sized for a fleet
that also materialises git worktrees, and it is not sized for a monorepo build. The gate's own disk
field (`"workRoot": "/home/zabz/code", "freeGiB": 20.8`) is what a placement decision should read before
choosing it.

---

## 4. The decisions this stream made

Development decisions, taken and recorded here rather than routed anywhere (rule: dev questions are not
boss questions).

1. **Runtime pinned to the authority's own version, resolved rather than hardcoded.** The script reads
   `node -v` from `secratary` and installs that (`v22.23.2`), so the two nodes cannot drift by accident;
   `--node-version` overrides, and `v22.23.2` is only the fallback when the authority is unreachable.
   It then **asserts the 22.18 floor and refuses to continue below it**, because below that floor the
   failure is a silent exit 0. Nothing was taken from `apt` (18.19.1) or from `nvm` (which lives in a
   shell-startup file a systemd unit never reads).
2. **A stable interpreter path, and a launcher that resolves it.** `~/.local/node` is a symlink and
   `/usr/local/bin/dsh` reads it, so no caller names a version — 62 §3.2 measured what a
   version-stamped path costs on mac-mini. `/usr/local/bin/{node,npm,npx,corepack}` are symlinks rather
   than copies so `node --version` works over a non-interactive ssh PATH of `/usr/bin:/bin:…`.
3. **`HOME` and `DSH_HOME` are both set in the engine unit**, `WorkingDirectory=/home/zabz/code` is
   fixed (it decides where this node's session directories live), and `Restart=always` with
   `RestartSec=3`. This is secratary's `phone-engine.service` with the fence kept and nothing else added.
4. **The gate is deployed, not checked out.** `~/dsh-mesh/repo/` holds `scripts/phone-gate.py` plus
   `assets/{mobile.css,question-card.css,phone-badge.js}` — the layout the gate itself resolves
   (`Path(__file__).parent.parent / "assets"`). **Nothing was written into the node's
   `~/code/harness-config` checkout**, which has diverged (`f14bfde`, 4 commits behind this session's
   origin) and would fail a pull. The node also keeps a re-runnable copy of the provisioning script.
5. **The engine is loopback-only and the gate is the only door.** `--host 0.0.0.0` is refused by DSH
   itself at startup, so loopback is the only shape. Because the node is published through
   `tailscale serve`, the engine **must** carry `--trusted-host zabz-tech-linux.tail93e6e6.ts.net`, or
   every `/api` call with a non-loopback Host gets 403 while documents keep serving (62 §4.4.3, PAIN
   P48). It does. Nothing was added to the tailnet ACL; `tailscale serve --bg 3086` is the only tailnet
   change and it publishes to the tailnet only.
6. **One engine, one `DSH_HOME`.** `~/.dsh` is the only home on this node, and the session store was
   created by the engine at first boot (62 §1.3: a fresh home is self-initialising; `.credentials.yaml`
   is created `0600` by the provider, so `chmod` is not needed and hand-copying it is not done).
7. **The headless profile is a job runner, not an engine, and this node uses it that way.** Its
   `patchReload: "startup"` means its composition is read once per process (62 §2.3), which is why the
   long-lived surface here is `web` (live reload) and the one-shot work goes through
   `--profile headless`.

### The one decision that was made, measured, and reversed

`dsh-plugin-health` was mounted into the web profile, and that made the node **worse**, so it was
reverted. The three reasons, all measured 2026-09-16 23:19–23:22Z:

1. Its process probe is **Windows-only by construction**. `packages/plugin-health/lib/snapshot.ps1`
   P/Invokes kernel32 `CreateToolhelp32Snapshot` and says in its own header that it uses "only what
   Windows already ships"; `lib/index.js:793` answers
   `processes.available && !processes.stale ? 200 : 503`. On Linux `available` is false forever, so
   `/healthz` is a **permanent 503** — measured, not inferred.
2. `scripts/mesh-health.ps1:130-134` maps **404 → WARN** but **anything else → FAIL**. Mounting it
   changed this node's line from the WARN that secratary also carries into
   `FAIL: GET /healthz (with the cookie from GET /) -> 503 (unexpected status)`.
3. Mounting it creates `$DSH_HOME/governor`, and on the gate revision deployed at 23:19Z
   (`ec17db22…`) `scripts/phone-gate.py:1068-1082` then reported
   `governor: {budgetSlots: 24, inUse: 0, queued: 0}` and **`accepts.fleet: true, maxChildren: 12`**
   where the same node answered `governor: null, fleet: false` without it — measured, same minute.
   That was fleet capacity nothing governs: a `--profile headless` child on this node mounts no
   plugin-health, so it never takes a lease and `inUse` can never move. **Under the current revision
   (`24b442ab…`) this third reason no longer applies**, because that revision computes the budget from
   memory and advertises `fleet: true` with no lease directory present at all. Reasons 1 and 2 stand on
   their own and are sufficient: the node is left without plugin-health, which also means the
   `~/.dsh/governor` directory is absent and the gate's `reason` field says honestly that `inUse` is
   not measured.

The honest state — the one secratary is in — is `plugin-health` not mounted, `/healthz` 404. The step
**reverts** any previous wiring idempotently (removing the bundle entry, the symlink, and the governor
directory **with `rmdir`, which refuses to touch anything non-empty**), and `--with-health-plugin`
exists for the day the probe grows a Linux path. Both states were run; the reverted one is the one the
node is in.

---

## 5. What I could not verify, stated as refusals

1. **`mesh-health.ps1` says `degraded`, not `healthy`.** 71 §3's acceptance line for S2 is "`mesh-health.ps1`
   reports it healthy". It cannot, on this platform, for any Linux node: `mesh-health.ps1` reaches
   `healthy` only when `/healthz` is 200, `/healthz` is 200 only when a Windows-only process probe has
   run, and the probe cannot run on Linux (§4, above). The node's line is identical to **secratary's**
   line, which is the fleet's authoritative node. Closing that acceptance gap needs a change in a file
   **this stream does not own**, and there are exactly two candidates:
   * `scripts/mesh-health.ps1:130-134` — treat a **503 from a node whose `platform` is not `win32`** as a
     WARN with the reason attached, rather than a FAIL (the `/healthz` body carries `identity.platform`,
     so the script can tell);
   * `packages/plugin-health/lib/index.js:793` — make the 200/503 decision depend on whether the probe is
     *supported* on this platform, rather than on whether it has produced a snapshot yet.
   Either one line closes it. I did not touch either file.
2. **`agents: null` in `/mesh/capacity`.** Same cause: that field is read from the engine's own
   `/healthz` document (the gate mints its own cookie for that read — `phone-gate.py:1157-1199`), so with
   no plugin-health mounted there is no `sessions.agentLoopsRunning` to report. `oneShot: true` and the
   `fleet: false` reason are unaffected, per 71 §2.1's own rule, so a one-shot placement still works.
3. **The node's name is not settled.** 71 §2.1 says `node` is the "short name, matches the ssh alias
   prefix", and the ssh alias is `linux-pc-ts` → `linux-pc`. S1's gate answers **`zabz-tech-linux`**,
   because that is the Tailscale DNS label — which is also what `mesh-health.ps1` needs
   (`<name>.tail93e6e6.ts.net`), since `mac-mini` is *unreachable* by its own short name and only
   `LakewooechsMini.tail93e6e6.ts.net` resolves. So the two conventions genuinely disagree, S1 and S7
   own both surfaces, and nothing in this stream depends on the answer.
4. **The 3.5 GiB of journald and 476 MB of apt cache are still there.** Measured, not reclaimed, on
   purpose (§3). `--reclaim` exists and has not been run.
5. **What occupies the other 423 GB is still unknown** (62 §6.5 left it open too), so how many worktrees
   this node could host *after* a reclaim is bounded by a measurement nobody has taken.
6. **The engine has never been through a reboot.** `systemctl enable` was run for both units, so both are
   `enabled`, but a cold boot has not been observed. The command that would settle it, when a reboot
   window exists, is `sudo systemctl reboot` and then `systemctl is-active dsh-engine phone-gate` — not
   run here, because the box carries other people's recovery work.
7. **`agents: null` and a fleet-eligible node with 0.8 GiB of headroom (added after the gate revision
   moved).** The current gate revision advertises this node as `fleet: true, maxChildren: 12` while its
   free space is `20.8 GiB` against `71` §2.2's `freeGiB < 20` fleet rule. The node therefore passes the
   rule with **0.8 GiB to spare**, and one large worktree would flip it. This stream's own contract is
   the mitigation and it is callable per dispatch:
   `scripts/provision-mesh-node.sh -H linux-pc-ts --assert-work-root` exits 20 the moment the filesystem
   is under 20 GiB. **Whether a fleet should be placed on this node at 20.8 GiB is S5's decision, not
   this stream's**, and the honest recommendation recorded here is: one-shot turns freely; a fleet only
   if the disk is first brought to a real margin, which `--reclaim` would do (+3.5 GiB of journald and
   +476 MB of apt cache, §3).

---

## 6. What a future session must know

**Re-provision / land a new gate revision (one command, safe to repeat):**

```bash
scripts/provision-mesh-node.sh -H linux-pc-ts
```

It re-pushes `scripts/phone-gate.py`, this script and `packages/plugin-health` only when asked, restarts
the gate **only if the gate file's sha256 changed**, and leaves a running engine alone. Every run writes
its full transcript to `~/.dsh-mesh/provision-<UTC>.log` on the node and a one-line summary to
`~/.dsh-mesh/provisioned.json`.

**Run work there, today, without any other stream:**

```bash
ssh linux-pc-ts 'cd ~/code && dsh --profile headless "<task>"'
```

**Check it from the laptop:**

```bash
pwsh -File scripts\mesh-health.ps1 -Nodes 'zabz-tech-linux'
curl -s https://zabz-tech-linux.tail93e6e6.ts.net/mesh/capacity
scripts/provision-mesh-node.sh -H linux-pc-ts --assert-work-root     # exit 20 = refuse a fleet
```

**Things that will surprise you if you do not know them:**

* `node`, `npm` and `dsh` are on the **non-interactive** ssh PATH because they are in `/usr/local/bin` —
  put a new tool anywhere else and `ssh linux-pc-ts <tool>` will not find it.
* The gate's capacity route is a `phone-gate.py` **route**, not a plugin, so it ships with the gate and
  needs no engine restart (71 §1, idea 1). Nothing about it lives in the engine.
* `~/.dsh-phone/engine-3099.log` contains live one-time tokens. Do not paste it anywhere.
* `~/.dsh-mesh/gate.sha256` is the stamp that decides whether the gate restarts; deleting it causes one
  harmless restart on the next run.
* `/etc/dsh-worker.env` is the only place the model key lives. `--force` overwrites it; nothing else
  does.
* If you ever mount plugin-health here, re-read §4 first. It is not a fix, it is a regression, and the
  reason is on this page.
