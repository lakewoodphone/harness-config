# 185 — SSH connection reuse (ControlMaster), and the real LAN-vs-Tailscale answer

**Measured 2026-10-12 by a mesh child running on `ZABZ-TECH` (`zabz-tech`).**
The configuration change was made on **`secratary-cloud`, the authority** — that is where the
per-dispatch cost lives and where the fan-out happens.

---

## 0. The answer in six lines

1. Multiplexing **works on the authority and is a large win for the Linux worker**: cold ssh to
   `linux-pc-ts` **409 ms → 38–43 ms** on every later connection, about **10×**.
2. It is only **2.1×** to `desktop-ts` (557 → 246–268 ms) and **1.4×** to `laptop-ts`
   (1676 → 1025–1268 ms) — and the reason is **neither the network nor ssh**.
3. Transport RTT is **13–14 ms** to `zabz-tech-linux` and `zabz-tech`, **27 ms** to `zabz-yoga-1`,
   all **direct** (none DERP-relayed). What is left on the Windows hosts is **remote shell
   startup**: `HKLM:\SOFTWARE\OpenSSH\DefaultShell` on both is `pwsh.exe`, and a bare
   `pwsh -NoProfile -Command 'echo .'` costs **189–232 ms** on ZABZ-TECH before ssh does anything.
   **Multiplexing cannot remove the far side's process spawn.**
4. **Preferring the LAN is not the fix here.** Raw RTT `linux-pc → desktop`: LAN **0.600 ms** avg vs
   tailnet **0.963 ms** avg, a **0.36 ms** difference — and `tailscale ping` proves the tailnet path
   is already riding the LAN (`via 192.168.50.138:41641`). The authority has **no route to
   192.168.50.0/24 at all**.
5. Failure behaviour is **bounded, not hung**. A new session reusing a wedged master failed after
   **74,678 ms**, bounded by `ServerAliveInterval 15 × ServerAliveCountMax 4`; the master then
   removed its own socket and a fresh ssh worked immediately. A *cold* connection to a blackholed
   peer is bounded by `ConnectTimeout` at **8114 ms**.
6. **The Windows hosts get no multiplexing, deliberately.** Win32-OpenSSH 10.0p2 cannot do it:
   `ControlMaster=yes` dies with `getsockname failed: Not a socket` and creates no socket on disk.

---

## 1. What was already in the estate (read before building)

`000-SYSTEMS-REGISTER.md` §2.3 and `143-TRANSPORT-POLICY.md` were read **before** anything changed.

* **Nothing in this estate manages ssh multiplexing.** A grep of the whole `harness-config` repo for
  `ControlMaster|ControlPath|ControlPersist` returns **only journal entries** — `L3391`, `P2251`,
  `H2406`, `H3334`. There is no script, no profile, no wrapper, and no `ControlPath` anywhere in
  `/root`, `/home`, `/etc`, `/opt` or `/usr/local`. `scripts/mesh/` — ten files
  (`cutover-authority.sh`, `Get-NodeSample.ps1`, `guard-service-state.sh`, `mesh-node-probe.sh`,
  `port-140-run-sentinel-install.sh`, `Reload-DshEngine.ps1`, `Resolve-MeshPath.ps1`, `route.sh`,
  `Start-AgentFleet.ps1`, `zabz-tech-boot-watch.ps1`) — contains **no** ssh-transport management. So
  there was nothing to reuse and nothing to duplicate: this had to be written.
* **`scripts/mesh/route.sh` was left alone, deliberately.** `143-TRANSPORT-POLICY` requires transport
  selection to be *measured*, and §6 measures it: LAN vs tailnet to an on-LAN peer differ by
  **0.36 ms**. Teaching `route.sh` a LAN preference would add a code path and a failure mode for no
  measurable gain, so the policy is satisfied by leaving the measurement in the record instead.
* **`L3391` (2026-10-07) already recorded the Windows half of this story** — *"Win32-OpenSSH
  multiplexing is broken here"*, `getpeername failed: Not a socket`, measured on ZABZ-YOGA. §9 below
  **reproduces it on a second machine**, which is what turns it from a machine quirk into a platform
  property.
* **`143-TRANSPORT-POLICY` set the terms and two of its traps fired on this work.** The policy says
  *"the selection must be MEASURED, not configured"* and warns that *"a fast failure is not a fast
  path. Time only successful calls, and say how many succeeded."* My first LAN-vs-tailnet run
  returned **rc=255 on both paths in ~122 ms each** — which reads as a perfect tie and was in fact a
  double *failure*: I had targeted `ezabz@192.168.50.138` directly, which bypasses linux-pc's
  `Host desktop` block and the `IdentityFile` in it, so no key was offered. Re-run with
  `-i ~/.ssh/id_ed25519_mesh -o IdentitiesOnly=yes`: **both paths rc=0**. Every number below is from
  a successful call.
* The policy also states the authority is in Ashburn and *"LAN can never apply to it."* **Confirmed
  by measurement, not by geography** (§6).

---

## 2. The "before" — measured on the authority, no multiplexing at all

`ssh -G` on the authority resolves all three targets to `*.tail93e6e6.ts.net`, i.e. Tailscale.
`ls -d /tmp/ssh-*` → **0 control sockets**; `grep -i control /root/.ssh/config /etc/ssh/ssh_config`
→ **nothing**. Probe used for every timing: `ssh -o BatchMode=yes -o ConnectTimeout=10 <host> 'echo .'`,
timed with `date +%s%N` around the whole ssh process.

**5 sequential, cold (5 separate full connections per host):**

| target | individual ms | median | total for 5 |
|---|---|---|---|
| `linux-pc-ts` | 415, 410, 410, 417, 417 | 415 | 2069 |
| `desktop-ts` | 530, 552, 509, 530, 525 | 530 | 2646 |
| `laptop-ts` | 1979, 1840, 1605, 1505, 2270 | 1840 | 9199 |

**5 concurrent, cold:**

| target | individual ms | wall ms |
|---|---|---|
| `linux-pc-ts` | 416, 416, 490, 492, 489 | 503 |
| `desktop-ts` | 581, 579, 583, 585, 595 | 607 |
| `laptop-ts` | 2088, 2096, 2142, 2146, 2249 | 2265 |

Two things this already shows. Concurrency does **not** inflate each connection much (416→490,
530→585, 1979→2140), so the target hosts are not the bottleneck and the fan-out is not saturating
anything — but each connection still pays a full TCP handshake, key exchange and authentication, so
a **sequential** fan-out of N pays N times over, and the laptop pays ~2 s a time.

The brief's figures (421 / 630 / 1746 ms) and these (415 / 530 / 1840 ms) agree within run-to-run
variance. `laptop-ts` is the noisy one (1505–2270 ms across five runs).

---

## 3. What was configured, and why it is NOT on `Host *`

Edited `/root/.ssh/config` on `secratary-cloud` — **client-side only**.

* **Backed up first**: `/root/.ssh/config.bak-ssh185-20261012T160156Z` (3936 bytes, mode 600).
  `sha256 before = 24d1d5cf9be10d74e074daceb40bb0d27ce4004293f7ae9f25cb816719a3c440`
  `sha256 after  = 9b663c45522cbcc949d23307ca14056115e126354f2e259db6ea5c7a0be6745a`
* **Control directory**: `/root/.ssh/cm`, created `mode=700 owner=root`. It survives because it is a
  real directory on disk, not `/tmp` (which is tmpfs on some hosts in this estate — register §4.3).
* The block is inserted **at the top** of the file, because ssh takes the **first** value obtained
  for each keyword; a block lower down would have been shadowed by the existing `Host *`.

```
Host linux-pc-ts zabz-tech-linux desktop-ts zabz-tech-ts zabz-tech secratary-ts secratary \
     laptop-ts zabz-yoga-ts zabz-yoga-1 mac-mini-ts lakewooechsmini
    ControlMaster auto
    ControlPath /root/.ssh/cm/%C
    ControlPersist 10m
    ServerAliveInterval 15
    ServerAliveCountMax 4
    ConnectTimeout 10
```

### Why not `Host *` — the deliberate decision

A control master is **not a cache**. It is a **persistent, pre-authenticated channel** plus a
**unix socket that any local process able to reach it can use to get a session without
re-authenticating**. Putting that on `Host *` means:

1. **Blast radius.** A stale or wedged socket is not a slow connection, it is a *hang* (measured:
   74 s, §7). On `Host *` that hang is available for every host this box ever touches — Hetzner,
   `lpt-apps`, `survivor`, one-off debug targets, anything in `known_hosts`. The fleet hosts are
   known, finite and ours. They get the master; everything else keeps paying full price, which is
   the correct default.
2. **It would open authenticated channels nobody asked for.** Any script that ssh's once to a
   third-party host would leave an authenticated connection to that host sitting open for
   `ControlPersist` afterwards.
3. **The scoping is verifiable, so it is not a claim.** `ssh -G` proves it per host:

   ```
   linux-pc-ts   controlmaster auto   controlpath /root/.ssh/cm/9fb557340f254f7557be93671f29f3bb8b20ccae  controlpersist 600
   desktop-ts    controlmaster auto   controlpath /root/.ssh/cm/6b18f98c29f3d6ac746234a09396cb0bff1c0a65  controlpersist 600
   laptop-ts     controlmaster auto   controlpath /root/.ssh/cm/0d545696835676be6315d45669738d2b92bdb064  controlpersist 600
   hetzner       controlmaster false  controlpersist no
   ```

   `hetzner` is a real alias this box uses and it is **correctly excluded**.

### Why `%C` in the ControlPath

`%C` is a **fixed-length hash** of `(%l, %h, %p, %r)`. `ControlPath /root/.ssh/cm/%C` is therefore a
constant **54 bytes** (`/root/.ssh/cm/` = 14, plus 40 hex), comfortably inside the 108-byte
`sun_path` limit, and it **cannot collide** between two different remote users or two different
ports on the same host. A hand-written `%h-%r` style path both grows unbounded with the hostname and
can collide.

### Why those keepalive values

`ServerAliveInterval 15` / `ServerAliveCountMax 4` is what bounds the wedged-master hang to ~60 s of
keepalive failure. It is not decoration — §7 shows a new session failing at 74.7 s **because** of it
rather than hanging forever. `ConnectTimeout 10` is what bounds a *cold* connection to a dead peer —
measured at 8114 ms with `ConnectTimeout=8` in §8.

---

## 4. The "after"

**5 sequential — first connection cold, the rest reuse the master:**

| target | cold (creates master) | muxed, connections 2–5 | speedup | total for 5 (was) |
|---|---|---|---|---|
| `linux-pc-ts` | 409 | 43, 42, 38, 38 | **~10×** | 570 (2069) |
| `desktop-ts` | 557 | 246, 264, 262, 268 | **2.1×** | 1597 (2646) |
| `laptop-ts` | 1676 | 1219, 1025, 1054, 1268 | **1.4×** | 6242 (9199) |

**5 concurrent with a warm master:**

| target | individual ms | wall ms (was) |
|---|---|---|
| `linux-pc-ts` | 48, 48, 50, 51, 55 | **71** (503) |
| `desktop-ts` | 268, 268, 272, 272, 285 | **299** (607) |
| `laptop-ts` | 1385, 1389, 1390, 1408, 1526 | **1539** (2265) |

**Proof the master exists and is being reused, not re-created:**

```
$ ssh -O check linux-pc-ts
Master running (pid=44632)
$ ssh -O check desktop-ts
Master running (pid=44652)
$ ssh -O check laptop-ts
Master running (pid=44672)

$ ls -la /root/.ssh/cm
drwx------ 2 root root 4096 .
srw------- 1 root root    0 0d545696835676be6315d45669738d2b92bdb064   <- laptop-ts
srw------- 1 root root    0 6b18f98c29f3d6ac746234a09396cb0bff1c0a65   <- desktop-ts
srw------- 1 root root    0 9fb557340f254f7557be93671f29f3bb8b20ccae   <- linux-pc-ts
```

**30 ssh invocations produced exactly 3 TCP connections**, one per host, held by pids 44632 / 44652 /
44672, and the master pids are unchanged after the concurrent burst:

```
ESTAB  100.73.176.126:36384 -> 100.85.153.96:22   users:(("ssh",pid=44652))   desktop-ts
ESTAB  100.73.176.126:41598 -> 100.72.162.5:22    users:(("ssh",pid=44672))   laptop-ts
ESTAB  100.73.176.126:xxxxx -> 100.105.248.90:22  users:(("ssh",pid=44632))   linux-pc-ts
```

---

## 5. Where the remaining time actually goes — the useful finding

Multiplexing removes **TCP handshake + key exchange + authentication**. It does **not** remove the
**round trip** or the **remote shell spawn**. Separating those explains the uneven table above.

Transport RTT, measured with `tailscale ping` (which reports the WireGuard peer and the path):

```
zabz-tech-linux   pong via 71.104.140.242:41646                     in 14ms
zabz-tech         pong via 71.104.140.242:45767                     in 13ms
zabz-yoga-1       pong via [2607:fb90:2e04:...]:41641               in 27ms
```

All three are **direct** — not relayed through a DERP server. So:

| target | muxed ms | network RTT | remainder = remote session |
|---|---|---|---|
| `linux-pc-ts` | ~40 | 14 ms | **~26 ms** (bash + channel) |
| `desktop-ts` | ~263 | 13 ms | **~250 ms** |
| `laptop-ts` | ~1143 | 27 ms | **~1116 ms** |

The remainder on the Windows hosts is **PowerShell starting up**, and it is not an inference:
`HKLM:\SOFTWARE\OpenSSH\DefaultShell` on ZABZ-TECH is
`C:\Program Files\PowerShell\7\pwsh.exe`, and measured **on ZABZ-TECH itself**:

```
powershell -NoProfile -Command "echo ."   ms=232
powershell -NoProfile -Command "echo ."   ms=189
powershell -NoProfile -Command "echo ."   ms=191
powershell -NoProfile -Command "echo ."   ms=191
```

So **most of the brief's 630 ms (`desktop-ts`) and 1746 ms (`laptop-ts`) was never network and never
ssh handshake — it is the far side spawning a shell per command.** That is the honest limit of this
fix, and it means the next win on the Windows hosts is not an ssh setting at all: it is **not
spawning a pwsh per command** — batching several commands into one ssh invocation, or using the
already-live HTTP mesh (`POST /mesh/run`, `packages/plugin-mesh-http`) which register §2.3 and
`L3391` both name as the transport for agent dispatches.

---

## 6. LAN vs Tailscale — measured, and it is not the fix

### The authority cannot use the LAN, ever (measured, not asserted)

```
$ ip route
default via 172.31.1.1 dev eth0 proto dhcp src 178.156.194.1 metric 100
$ ip -4 -o addr show
lo 127.0.0.1/8 | eth0 178.156.194.1/32 | tailscale0 100.73.176.126/32
$ ssh -o ConnectTimeout=5 zabz@192.168.50.23 'echo .'
ssh: connect to host 192.168.50.23 port 22: Connection timed out      rc=255  ms=5112
```

There is **no `192.168.50.0/24` interface and no route to one**. `143-TRANSPORT-POLICY`'s statement
that LAN can never apply to the authority is correct, and the only two transports it has are
Tailscale and the public internet.

### Between two office-LAN machines the LAN is already in use

```
# from ZABZ-TECH (192.168.50.138 LAN / 100.85.153.96 tailnet)
ping 192.168.50.23            -> 0ms, <1ms, <1ms, 1ms, <1ms   (avg 0 ms, 0% loss)
tailscale ping zabz-tech-linux -> pong via 192.168.50.23:41641 in 2ms

# from linux-pc (192.168.50.23 LAN / 100.105.248.90 tailnet)
ping 192.168.50.138                    -> rtt min/avg/max = 0.389/0.600/0.922 ms
ping zabz-tech.tail93e6e6.ts.net       -> rtt min/avg/max = 0.725/0.963/1.241 ms
tailscale ping zabz-tech               -> pong via 192.168.50.138:41641 in 0s
```

**The tailnet path to an on-LAN peer *is* the LAN path**, with WireGuard on top: the extra cost is
**~0.36 ms** of encapsulation, not distance. On the ssh timescale that is invisible:

| from → to | over LAN | over tailnet |
|---|---|---|
| ZABZ-TECH → linux-pc (5 cold ssh) | 303, 297, 277, 275, 291 (avg **289**) | 295, 287, 292, 289, 290 (avg **291**) |
| linux-pc → desktop (5 cold ssh, correct key) | 458, 432, 484, 444, 439 (avg **451**) | 467, 461, 485, 509, 523 (avg **489**) |

Conclusion: **"prefer the LAN" buys ~1 ms and is not the fix.** Both paths work, both are direct,
and 450 ms of that linux-pc→desktop number is Windows pwsh startup. Where the LAN *would* matter is
if the tailnet path were relayed — it is not, on any of these peers — so a LAN-preference rule would
add a second code path and a second failure mode for no measurable gain. This is the same conclusion
`143` reached about the API (`0.058s` tailnet vs `0.067s` public): **at this distance the transport is
not the bottleneck.**

---

## 7. Failure behaviour — this is the part that matters

All tests are client-side only. **No service was started, stopped, restarted or reconfigured on any
host**; no remote host was rebooted. A real remote reboot could not be performed under the task's
rules, so it was **emulated** two ways, and both are labelled as emulation below.

### F1 — clean stop

```
$ ssh -O exit linux-pc-ts      ->  Exit request sent.
$ ls /root/.ssh/cm | wc -l     ->  0
```

### F2 — STALE MASTER: socket file left on disk, no master behind it

The master was `kill -9`ed, which leaves the socket file behind (no chance to unlink it):

```
socket files after SIGKILL: 1        <- stale file left on disk
$ ssh -v ... linux-pc-ts 'echo recovered'
debug1: Stale control socket /root/.ssh/cm/9fb557...ccae, unlinking
debug1: mux_client_request_session: master session id: 2
recovered                     rc=0  ms=399
$ ssh -O check linux-pc-ts  ->  Master running (pid=45288)
```

**Recovers automatically**, in one cold round trip (399 ms), and it does not need a human or a
cleanup script: ssh detects the stale socket, unlinks it, and creates a fresh master *within the same
invocation*. This is the case the office box's `P2251` ("a ControlMaster socket that got wedged")
feared, and it is handled.

### F3 — NETWORK DROP / REMOTE REBOOT: master alive, transport blackholed

A local TCP relay in front of `linux-pc-ts` was used as the fault injector. "Frozen" means the relay
**accepts and holds the sockets open but forwards no bytes** — a black hole, not a closed port, so
**no RST is ever sent and the only thing that can detect the failure is a keepalive.** This is the
client-side signature of a network drop or a peer that has stopped answering.

```
--- establish a control master THROUGH the relay ---
master_over_relay            rc=0  ms=369
check: Master running (pid=45972)

--- FREEZE ---  frozen at 16:03:11Z

(1) ssh -O check linux-pc-ts   ->  rc=0  ms=10   "Master running (pid=45972)"
    ^ the check answers instantly: it talks to the LOCAL unix socket and never
      touches the network, so it CANNOT tell you the transport is dead.

(2) ssh linux-pc-ts 'echo .'   ->  rc=255  ms=74678
    ^ the new session reused the wedged master and HUNG for 74.7 seconds.
      It was NOT killed by my own 120 s timeout (that would be rc=124) - it
      failed on its own when the master died underneath it.

(3) master socket GONE after 74s from freeze
    socket files: 0
    ^ the master noticed via ServerAliveInterval 15 x ServerAliveCountMax 4
      and removed its own socket. Nothing stale was left behind.

(4) ssh linux-pc-ts 'echo .'   ->  rc=0  ms=408     (fresh ssh, no master: works)
(5) after unfreezing            ->  rc=0  ms=107     "Master running (pid=47332)"
```

**The honest reading: a multiplexed connection that is wedged is worse than a slow one that
works — but only for a bounded window, and it self-heals.** Three things follow:

* **The window is set by the keepalives.** A reuse of the wedged master cost **74.7 s**. Without
  `ServerAliveInterval`/`ServerAliveCountMax` the master would not have noticed, and neither the
  client nor the master has any other deadline for a channel on an established transport. This is
  the entire justification for those two settings.
* **`ConnectTimeout` does NOT protect a muxed session.** It bounds connection setup; a session
  joining an existing master does no setup. 74 s ≫ the 10 s `ConnectTimeout`, and the measured
  cold-blackhole case below is bounded at 8 s. Two different deadlines for two different code paths.
* **`ssh -O check` is not a health check for the transport.** It answered "Master running" in 10 ms
  while the transport was a black hole. Anything that uses it as a liveness probe is wrong.

### F7 — does a master ever linger at a host that no longer exists?

With `ControlPersist` overridden to 15 s:

```
master up: Master running (pid=52661)
socket GONE after 16s of idleness
```

The master reaps itself and unlinks its socket. So the answer to *"never leave a control master
pointing at a host that does not exist"* is: it cannot persist — `ControlPersist 10m` bounds an idle
master to 10 minutes, and F3 shows an unreachable peer kills it in ~74 s regardless of the persist
window. **Final state verified: `ls /root/.ssh/cm | wc -l` → 0, no leftover helper processes.**

### F5 / F6 — the cold cases (bounded, and these bound *any* ssh, mux or not)

```
F5  cold connection to a BLACKHOLED peer, ConnectTimeout=8
    rc=255  ms=8114       <- bounded by ConnectTimeout, which covers the initial
                             SSH protocol handshake and key exchange, not just TCP

F6  peer reachable, sshd NOT listening (the "just rebooted / not yet up" case)
    ssh: connect to host ... port 2298: Connection refused
    rc=255  ms=108        <- fast, unambiguous, nothing hangs
```

F6 is the realistic post-reboot signature: while the host is up but sshd is not, you get an
immediate refusal; a new connection succeeds as soon as sshd is back, with no cleanup.

---

## 8. The Windows hosts — what was done there, exactly

**Nothing was changed in `C:\Users\ezabz\.ssh\config` on `ZABZ-TECH`, and the reason is that adding
these options there actively breaks ssh.** Reproduced on this machine (client
`OpenSSH_for_Windows_10.0p2 Win32-OpenSSH-GitHub`, `C:\Program Files\OpenSSH\ssh.exe`):

```
$ ssh -o ControlMaster=yes -o ControlPath=C:\Users\ezabz\.ssh\cm\mux-test.sock secratary-cloud "echo MASTER_UP"
getsockname failed: Not a socket
<hung>
$ ls C:\Users\ezabz\.ssh\cm
<empty - no socket file was ever created>
```

`L3391` reported this on **ZABZ-YOGA** as `getpeername failed: Not a socket`; I get
`getsockname failed: Not a socket` on **ZABZ-TECH** with the same client generation, and **no socket
file is created**. Same failure, same place in the code, two different machines — this is a
**Win32-OpenSSH platform limitation** (`AF_UNIX` socket handling in the multiplex client), not a
quirk of one laptop.

**On the ControlPath length limit and the `/tmp` equivalent, which the brief asks about
specifically:** neither is reachable, because **no control socket is ever created on Windows**. There
is no length to stay under and no directory to create. I created
`C:\Users\ezabz\.ssh\cm` while testing and it stayed empty; the `%TEMP%` variant fails identically
(`L3391` tested both). The Windows half of a multiplexing policy is therefore: **do not configure
it**, and route around it.

### A second, independent Windows defect found while doing this — and it is the bigger one

While measuring, the *very first* ssh call hung. Not the network — **the ssh client never exited**:

```
$ ssh -o BatchMode=yes secratary-cloud "echo A"
A
<hung; killed at 120 s>
```

`ssh <host> <cmd>` prints its output and then **never exits** when its stdin is an inherited pipe.
`-n` does **not** fix it (tested: same hang). Giving ssh a **real, immediately-EOF stdin handle**
does — every measurement in this document was taken through a harness that passes
`Start-Process -RedirectStandardInput <empty file>` with a wall-clock timeout:

```
secratary-cloud  exited=True rc=0  559 ms
secratary-lan    exited=True rc=0  223 ms
linux-pc         exited=True rc=0  303 ms
linux-pc-ts      exited=True rc=0  326 ms
```

This is a distinct mechanism from the ControlMaster failure, and it matters more for automation: it
is a *client-side* hang that any agent harness on Windows will hit the moment it runs ssh
non-interactively. It is consistent with the "stuck ssh processes" symptom in `P2251` — offered as
an additional candidate, **not** as a proven re-diagnosis of that entry. Any Windows-side wrapper
should pass an explicit empty stdin **and** a timeout; nothing in `ssh_config` does it.

---

## 9. What I broke, and what I could not do

* **Nothing was made worse and nothing was reverted.** Before/after are both from successful calls;
  the `hetzner` alias still resolves with `controlmaster false`.
* **No service state was touched anywhere.** `sshd` on the authority:
  `ActiveEnterTimestamp=Mon 2026-10-12 13:13:16 UTC` — **~3 hours before my first edit at 16:01Z**,
  so it was not restarted by this work. `sshd_config` mtime unchanged at `2026-10-10 23:52:35Z`.
  No `sshd_config` was edited on any host, and no host was rebooted.
* **A real remote reboot was not performed** (forbidden). The network-drop/reboot case was emulated
  with a local TCP black-hole relay (F3) and with a `Connection refused` on a dead port (F6). Both
  are labelled as emulation; neither required a change on the far side.
* **Not applied to the other Linux nodes.** `linux-pc`, `lpt-apps` and `hetzner` would take the same
  block (as user `zabz`/`root`, at the top of their `~/.ssh/config`, with a per-user control dir).
  I did not do it: the measured problem is the authority's, the office box `secratary` is explicitly
  **frozen / read-only / the rollback anchor** in register §1 and must not be edited, and every extra
  node multiplies the blast radius of a change that only the authority is actually paying for.
* **`laptop-ts` is the weak case at 1.4×** and I could not improve it: ~1.1 s of its ~1.2 s is
  `pwsh.exe` starting on the owner's machine, which is out of reach of any ssh client setting.
* The task asked for `/root/code/harness-config/docs/mesh/185-...`; this file was authored on
  **ZABZ-TECH** (the machine this session ran on) and committed there **and** on the authority. Both
  entries are named in the reply, because a commit on one machine is invisible on another.

---

## 10. Reproduce, roll out, revert

**Reproduce the measurement** (on the authority; anything with mux will be fast, so clear masters
first):

```bash
for H in linux-pc-ts desktop-ts laptop-ts; do ssh -O exit $H; done
for H in linux-pc-ts desktop-ts laptop-ts; do
  echo "### $H"
  for i in 1 2 3 4 5; do
    s=$(date +%s%N); ssh -o BatchMode=yes "$H" 'echo .' </dev/null >/dev/null 2>&1; rc=$?
    e=$(date +%s%N); echo "  seq$i rc=$rc ms=$(( (e-s)/1000000 ))"
  done
  ssh -O check $H
done
```

Note `</dev/null` on every ssh: on Windows clients it is *required* (§8), and it is harmless
everywhere.

**Verify the setting is live:** `ssh -G <host> | grep -i control` and `ssh -O check <host>`.
**Inspect what exists:** `ls -la /root/.ssh/cm`.
**Clear masters:** `ssh -O exit <host>` per host, or `pkill -f 'ssh:.*ControlPath'`.

**Revert completely:**

```bash
cp -a /root/.ssh/config.bak-ssh185-20261012T160156Z /root/.ssh/config
ssh -O exit linux-pc-ts; ssh -O exit desktop-ts; ssh -O exit laptop-ts
rmdir /root/.ssh/cm 2>/dev/null
```

Nothing outside `/root/.ssh/config` and `/root/.ssh/cm` was changed, so this is the whole revert.
