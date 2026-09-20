# 63 — Security audit of the mesh: what is actually exposed, and the fix for each

**Status:** audit only. **Nothing was changed, rotated, stopped or deleted on any node to produce this
document.** Every claim carries a `SOURCE` and a time. Labels: **MEASURED** (I ran it, on the node and
at the time named, output quoted), **READ-FROM-CODE/DISK** (a real file, cited by path and line),
**READ-FROM-DOCS** (official URL), **COULD NOT VERIFY** (with the exact reason), **PROPOSED** (not
applied).

**Written:** 2026-09-16 ~21:44–22:05 UTC from **ZABZ-YOGA** (this laptop). All times UTC unless marked.
**Prerequisite reading:** this document continues `50-transport.md` §2/§4/§5 and `30-truth-and-disk.md`;
where it contradicts them it says so explicitly.

**Secrets:** no live secret value appears in this file. Credentials are shown as **a masked fingerprint
(prefix6 + length)** plus where it lives. Two live-looking values are named in full *only* because the
audit mandate requires readable evidence and they are already published in the owner's own tracked
files — the Twilio account SID `AC274c…` (a 34-char identifier, not a secret) and the Google API key in
`lpt-hub`. The Twilio **auth token**, the AWS key, the Twilio API-key SIDs and every database password
are fingerprinted, never printed.

---

## 0. The headline, in five lines

1. **Any device on the tailnet can sign itself into the owner's DSH engine on `secratary` and on
   ZABZ-YOGA with one unauthenticated HTTPS GET, and get a 30-day cookie that controls the engine —
   which runs shell commands as the owner.** No token, no password, no user interaction. (MEASURED,
   §3.3.)
2. **The tailnet's packet filter is default allow-all**: every tailnet node may open **any TCP/UDP port**
   on every other node. Measured from the node itself, not inferred. (§2.4.)
3. **PostgreSQL on this laptop listens on `0.0.0.0:5432` and answers tailnet peers over the network.**
   The only thing refusing them is a `pg_hba.conf` line. (§1.)
4. **Live-looking credentials are committed in plain text** — Twilio account SID + auth token, two
   Twilio API-key SIDs, an AWS access key id, and two LPT service tokens. The Twilio **auth token has
   already been rotated** (proved by hash, §4.3); the account SID and phone number are still the live
   ones. None of the repos is anonymously readable. (§4.)
5. **CVE-2026-11822 is real**, confirmed from NVD and MITRE, and all five nodes run an affected SQLite
   (3.45.1–3.51.0, fixed in 3.53.2). Real risk here: **low** — no path exists to run an FTS5 `MATCH`
   against a database someone else supplied. (§5.)

Ranked table with proving commands and effort: **§6**.

---

## 1. PostgreSQL on the laptop

### 1.1 What it is

| Fact | Value | Source |
|---|---|---|
| Service | `postgresql-x64-16`, **Running**, StartMode **Auto**, account `NT AUTHORITY\NetworkService` | `Get-Service` / `Get-CimInstance Win32_Service`, 2026-09-16 21:47Z |
| Version | **PostgreSQL 16.13** (`psql (PostgreSQL) 16.13`) | `psql --version`, 21:47Z |
| Binaries / data | `C:\Program Files\PostgreSQL\16\bin`, `C:\Program Files\PostgreSQL\16\data` (`PG_VERSION` = 16) | 21:47Z |
| Cluster state | `in production`; latest checkpoint `9/16/2026 3:53:40 PM` local | `pg_controldata`, 21:48Z |
| Processes | 7 `postgres.exe` + 1 `pg_ctl.exe`; the listener is **PID 8596** | `Get-Process`, 21:47Z |
| Listening | `0.0.0.0:5432` **and** `[::]:5432`, both `Listen`, owner PID 8596 | `Get-NetTCPConnection -LocalPort 5432`, 21:47Z |
| Established connections | **none** — zero rows with `RemotePort -ne 0` | same command, 21:47Z |
| `listen_addresses` | `'*'` (explicit, uncommented) | `postgresql.conf`, read 21:50Z |
| `ssl` | **off** (commented default; confirmed live — see 1.3) | `postgresql.conf` + the server's own FATAL text |
| `password_encryption` | `scram-sha-256` (commented default) | `postgresql.conf` |

`listen_addresses = '*'` was **not** what the version's installer does by default — the 0.0.0.0 bind is
a deliberate edit, and it is the reason every other finding in this section is possible.

### 1.2 What it requires to authenticate

`pg_hba.conf`, non-comment lines, verbatim (read 21:50Z):

```
local   all             all                                     scram-sha-256
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
local   replication     all                                     scram-sha-256
host    replication     all             127.0.0.1/32            scram-sha-256
host    replication     all             ::1/128                 scram-sha-256
```

There is **no `host … 0.0.0.0/0` line and no tailnet/LAN line at all.** So the security boundary is a
single default-deny in `pg_hba.conf` — not the network, and not the firewall (§1.4). Anyone who can edit
this file, or who finds an `md5`/`trust` line in a later hand-edit, is one line from a network-exposed
database.

Local authentication is verified, not assumed: `psql -U postgres -w -h 127.0.0.1` returns
`fe_sendauth: no password supplied` (21:52Z), and there is **no `%APPDATA%\postgresql\pgpass.conf`** and
**no `PGPASSWORD`** in the environment. So a password is genuinely required; I did not have it (§1.5).

### 1.3 It IS reachable from the tailnet — proof

This is the part that contradicts "it is only a dev database". From **secratary** (100.84.72.88), with a
raw PostgreSQL v3 startup packet (no driver, no credentials) sent to the laptop's tailnet address:

```
100.72.162.5 5432 REPLY b'E\x00\x00\x00\xa2SFATAL\x00VFATAL\x00C28000\x00Mno pg_hba.conf entry
for host "100.84.72.88", user "probe_user", database "probe_db", no encryption\x00Fauth.c\x00L550\x00
RClientAuthentication\x00\x00'
```

MEASURED 2026-09-16 21:52Z, run over `ssh secratary-ts`. Read it carefully, because both halves matter:

- **`SFATAL` is a reply.** The TCP connection completed and the PostgreSQL server parsed the packet and
  answered it. `cat < /dev/null > /dev/tcp/100.72.162.5/5432` returned **OPEN** from **both** `secratary`
  and `zabz-tech-linux` (21:53Z, 4 s timeout each). So the laptop's PostgreSQL is **reachable from the
  tailnet**, on the public-facing side of the tailnet's encryption, from at least two other machines.
- **`C28000` / `no pg_hba.conf entry`** is the only thing that stopped it. Not the firewall, not
  `listen_addresses`, not a bind to loopback.
- **`no encryption`** confirms `ssl = off`: a legitimate client would send its SCRAM exchange — and
  consequently anything it authenticates with — over the tailnet's WireGuard tunnel but with no
  PostgreSQL-layer TLS.

**Counter-measurement, so this is not over-read:** the laptop's **home-LAN** address `192.168.12.104:5432`
was **closed** from the two office probes (21:53Z) — but that is expected and proves nothing, because
192.168.12.0/24 is the laptop's home network and the office nodes cannot route to it. **The LAN-side
exposure is COULD NOT VERIFY**: no second device on 192.168.12.0/24 was available to test from, and a
connection from the laptop to its own LAN address is not a remote test.

### 1.4 Why the Windows firewall did not stop it

| Check | Result | Source |
|---|---|---|
| Any firewall rule whose `LocalPort` contains `5432` | **none**, out of every enabled rule on the host | `Get-NetFirewallRule` + `Get-NetFirewallPortFilter`, 21:49Z |
| `netsh advfirewall firewall show rule name=all` filtered for `5432` or `postgre` | **no match** | 21:52Z |
| Profiles | Domain/Private/Public all Enabled, `DefaultInboundAction NotConfigured` | `Get-NetFirewallProfile`, 21:49Z |
| Rules named `Tailscale*` | `Tailscale-Process` — Inbound, **Allow**, Profile Any, LocalPort **Any**, RemoteAddress **Any**; `Tailscale-In` (×2) — Inbound, **Allow**, Profile Domain,Private, LocalPort **Any** | same, 21:51Z |

The profiles' default inbound action resolves to Block, and there is no 5432-specific rule — yet the
connection succeeded. The only rules that explain that are the Tailscale ones, which allow **all ports
from all addresses on that interface**. `50-transport.md` §4 assumed the ACL would have to carry the
`5432 only between secratary and ZABZ-TECH` rule; the measurement here says the firewall is not currently
carrying anything at all on the tailnet interface, so the ACL would be the *only* control there.

### 1.5 What data it holds

I could **not** authenticate, so this is read from disk rather than from SQL. Say that plainly: **the
row contents are COULD NOT VERIFY.**

What the repository believes the credential is (READ-FROM-CODE): the tracked file
`phone-and-tech/backend/eslint-results.json` line 78 embeds

```
process.env.DATABASE_URL = 'postgresql://postgres:<25-char password>@localhost:5432/phonetech_dev'
```

**That credential does not authenticate today** (MEASURED 21:56Z):
`psql -U postgres -h 127.0.0.1 -d phonetech_dev` → `FATAL: password authentication failed for user
"postgres"`. So the committed password is stale and could not be used to enumerate the cluster either.

What the cluster **does** hold, read from the data directory (READ-FROM-DISK, 21:57–22:01Z):

| Evidence | Value |
|---|---|
| `data/base` sizes | OID **16395 = 1025.6 MB**; 1 = 7.6 MB; 4 = 7.5 MB; 5 = 7.5 MB (template1/template0/postgres) |
| Whole data dir | **1496.9 MB** |
| `base/16395` | **372 files**; newest write `2026-06-28 00:17:15` |
| Database names in the on-disk `global/1262` (`pg_database`) byte scan | exactly one non-template name: **`personality_test`** |
| Relations found in `base/16395/1259` (`pg_class`) | `assessment_ai_events`, `assessment_ai_events_id_seq`, `assessment_libraries`, `assessment_library_history`, `assessment_library_snapshots`, `assessment_live_caches`, `assessment_record_participants`, `assessment_session_records`, plus their `_pkey`/`_idx` objects |
| Write activity | hourly checkpoints write **0 buffers** (`postgresql-2026-09-16_122908.log`, 21:50Z) |

**Reading:** this is the `personality_test` database of a **personality/assessment application** — AI
event rows, session records, library snapshots and "live caches" — 1 GB of it, **untouched since
2026-06-28**, in a cluster that starts automatically at every boot and listens on every interface.

So the honest version of "it is only a dev database" is: *the name and the table shape say dev/assessment,
the cluster is idle, and it serves nothing today — but nobody has enumerated its rows, and 1 GB of
`assessment_session_records` could contain real people's answers.* Treat that as **unproven**, per the
mandate.

### 1.6 The exact commands, and the exact fix

**Proving reachability from a remote node** (run on `secratary-ts`; the laptop is named by its tailnet IP
because the laptop moves networks):

```bash
# 1. Is the port open across the tailnet?
timeout 4 bash -c 'cat < /dev/null > /dev/tcp/100.72.162.5/5432' && echo OPEN || echo closed

# 2. Does the server answer?  (no driver, no credentials — reads the FATAL text)
python3 - <<'EOF'
import socket,struct
s=socket.create_connection(("100.72.162.5",5432),timeout=5)
p=b"user\x00probe_user\x00database\x00probe_db\x00\x00"
s.sendall(struct.pack("!i",len(p)+8)+struct.pack("!i",196608)+p)
print(repr(s.recv(4096)[:300]))
EOF
# expect: FATAL ... 28000 ... no pg_hba.conf entry for host "100.84.72.88"
```

**Closing it — the config change, in preference order (all PROPOSED, none applied):**

1. **Bind to loopback and nothing else** — the correct fix, because nothing on this machine connects
   (zero established connections, §1.1). In `C:\Program Files\PostgreSQL\16\data\postgresql.conf`:

   ```conf
   listen_addresses = 'localhost'      # was: '*'
   ```

   then restart the service (elevated): `Restart-Service postgresql-x64-16`.
   Verify: `Get-NetTCPConnection -LocalPort 5432 -State Listen | Select LocalAddress` must show only
   `127.0.0.1` and `::1`.
2. **If `'*'` must stay** — add an explicit inbound block, because the Tailscale interface currently
   allows everything:

   ```powershell
   New-NetFirewallRule -DisplayName 'PostgreSQL 5432 - deny from tailnet' -Direction Inbound `
     -Action Block -Protocol TCP -LocalPort 5432 -Profile Any
   ```

   Verify from `secratary-ts`: the `/dev/tcp` test in step 1 must time out.
   **Note the ordering hazard:** Windows evaluates Block rules before Allow rules, which is why this
   works despite `Tailscale-In` allowing any port — but it is a second control layered over a service
   that should not be listening at all.
3. **Decide the cluster's fate.** It is 1.5 GB of idle PostgreSQL on a roaming laptop with a
   start-at-boot service. Either `pg_dump` it to the authority and `Set-Service postgresql-x64-16
   -StartupType Manual`, or uninstall it. That is a data-deletion decision → the owner's, and PROPOSED
   here, not done.

---

## 2. Tailnet posture

All measurements 2026-09-16 21:47–22:04Z. Self-view = `tailscale status --json` / `tailscale debug prefs`
run **on that node**; peer-view = read from ZABZ-YOGA's own `tailscale status --json`.

### 2.1 Per-node table

| Node | DNSName | tailnet IPv4 | KeyExpiry | advertises an exit node | advertises routes / is a subnet router | tags | `RouteAll` | ExitNode armed? | Serve | Funnel |
|---|---|---|---|---|---|---|---|---|---|---|
| **ZABZ-YOGA** (self) | `zabz-yoga-1.tail93e6e6.ts.net` | 100.72.162.5 | **2027-02-26T03:54:29Z** | no | none | none | **true** | **no** — `ExitNodeIP ""` | `https://zabz-yoga-1.tail93e6e6.ts.net` → `127.0.0.1:3099` | **off** |
| **ZABZ-TECH** (self, over ssh) | `zabz-tech.tail93e6e6.ts.net` | 100.85.153.96 | **2027-01-18T22:41:06Z** | no | none | none | **true** | **no** — `ExitNodeIP ""` | `No serve config` | `No serve config` |
| **secratary** (self, over ssh) | `secratary.tail93e6e6.ts.net` | 100.84.72.88 | **2027-02-26T03:58:06Z** | no | none (`PrimaryRoutes []`) | none | false | no | `https://secratary.tail93e6e6.ts.net` → `127.0.0.1:3086` | **off** |
| **zabz-tech-linux** (self, over ssh) | `zabz-tech-linux.tail93e6e6.ts.net` | 100.105.248.90 | **2027-02-26T04:01:16Z** | no | none | none | false | no | `No serve config` | `No serve config` |
| **lakewooechsmini** (peer-view only) | `lakewooechsmini.tail93e6e6.ts.net` | 100.126.146.121 | **2027-02-26T04:07:09Z** | no | none | none | **COULD NOT VERIFY** | **COULD NOT VERIFY** | **COULD NOT VERIFY** | **COULD NOT VERIFY** |
| **iphone-15-pro** (peer-view only) | `iphone-15-pro.tail93e6e6.ts.net` | 100.85.105.93 | **2027-03-10T19:54:30Z** | no | none | none | n/a | n/a | n/a | n/a |
| Hetzner VPS | not a tailnet node | — | — | — | — | — | — | — | — | — |

**The mac mini could not be verified from itself**: `/usr/local/bin/tailscale status --json`,
`debug prefs`, `serve status` and `funnel status` each **timed out after 10 s** (a Python
`subprocess.run(..., timeout=10)` wrapper, run twice — once via a bare CLI call that hit the 120 s shell
cap, once bounded). The macOS CLI is a GUI-app shim and blocks without a logged-in session. Its row is
therefore peer-view data (real, from the laptop's own netmap) and its **self-reported prefs are unknown**.
Anything that needs the employee's node audited must be done from the console or on the machine.

**Serve vs Funnel.** On ZABZ-YOGA, secratary and linux-pc, `tailscale funnel status` printed the **same
output as `tailscale serve status`**, with the `(tailnet only)` annotation and **no Funnel marker**:
`grep -c Funnel` over both outputs is 0. Funnel is **off everywhere it could be read**. That is the same
conclusion `50-transport.md` §1.2 reached for secratary and extends it to ZABZ-YOGA. (ZABZ-TECH and the
mac mini print `No serve config` / could-not-verify, so there is nothing to expose.)

### 2.2 Is an exit node armed — settling the `RouteAll: true` contradiction

**Both reports were right, about different things, and neither described a blackhole.** MEASURED
2026-09-16 21:48Z:

| Node | `RouteAll` | `ExitNodeIP` | `ExitNodeID` | default route actually in the routing table |
|---|---|---|---|---|
| ZABZ-YOGA | **true** | `""` | `""` | `0.0.0.0/0 → 192.168.12.1 via Ethernet, metric 0, NetMgmt` (`Get-NetRoute`) |
| ZABZ-TECH | **true** | `""` | `""` | (not measured on that host this session) |
| secratary | false | `""` | `""` | `default via 192.168.50.1 dev eno1 proto static` + a dhcp copy, metric 100 |
| zabz-tech-linux | false | `""` | `""` | `default via 192.168.50.1 dev enp1s0 proto dhcp`, metric 100 |

So: `RouteAll: true` is **real and readable on two nodes** (`50-transport.md` §4 measured it on
ZABZ-YOGA; it is also true on ZABZ-TECH — new in this audit). With `ExitNodeIP` empty, `RouteAll` is
**inert**: the operating system's own default route is untouched on every node where it was measured.
`50-transport.md` §4's claim that a report "could not reproduce it" was a measurement-scope difference,
not a disagreement — the field is readable via `tailscale debug prefs` and is true on the two Windows
nodes.

**It is still worth clearing**, because `RouteAll: true` + one `tailscale set --exit-node <ip>` is a
one-command blackhole on the roaming laptop. PROPOSED, one minute per node:
`tailscale set --exit-node=` on ZABZ-YOGA **and ZABZ-TECH** (the transport doc named only the laptop).

### 2.3 Key expiry — every node can be silently deleted

Every node's key expires between **2027-01-18** (ZABZ-TECH, the earliest) and **2027-03-10** (iPhone).
An expired key removes the node from the tailnet **with no notification anywhere in the mesh** — the
failure class `50-transport.md` §5.4 names. ZABZ-TECH is first, on **2027-01-18**, 18 days before the
others. PROPOSED: disable key expiry on the five always-on nodes (secratary, ZABZ-TECH, linux-pc, mac
mini, Hetzner); leaving it on for the laptop and the phone is correct and desirable. That is a click per
machine in the admin console, which this audit has no access to.

### 2.4 The packet filter is **default allow-all** — measured on the node

This is the fact that makes §3 dangerous, so it is quoted from the machine rather than inferred:

```
$ tailscale debug netmap            # on ZABZ-YOGA, 2026-09-16 22:02Z
"PacketFilter": {
  "Dsts":      [ {"Net":"0.0.0.0/0","Ports":{"First":0,"Last":65535}},
                 {"Net":"::/0",     "Ports":{"First":0,"Last":65535}} ],
  "IPProto":   [6, 17, 1, 58],                      # TCP, UDP, ICMP, ICMPv6
  "Srcs":      ["100.115.94.0/23","100.115.96.0/19","100.115.128.0/17","100.116.0.0/14",
                "100.120.0.0/13","100.64.0.0/11","100.96.0.0/12","100.112.0.0/15",
                "100.114.0.0/16","100.115.0.0/18","100.115.64.0/20","100.115.80.0/21",
                "100.115.88.0/22","fd7a:115c:a1e0::/48"],
  "Caps": [], "SrcCaps": null
}
```

Read it as one sentence: **any address in the entire tailnet CGNAT space may open any TCP or UDP port,
0–65535, on this laptop** — and, because every node's filter is the same shape, on every other node.
`AdvertiseTags` is `null` on every node that could be read (secratary, laptop, linux-pc, ZABZ-TECH), and
`Caps` is empty — i.e. the "tag is a permission boundary" proposal in `50-transport.md` §4 is not merely
unapplied, **there is currently no boundary at all**.

**COULD NOT VERIFY:** the tailnet **policy file text**. This audit has no admin-console/API token, so the
ACL source cannot be read. The `PacketFilter` above *is* the compiled policy the node is enforcing, which
is why it is quoted instead — but "is there a policy file with rules that merely happen to be permissive"
cannot be distinguished from "there is no policy file" from here.

### 2.5 What this means, concretely

Every node on this tailnet — including **the employee's macOS mini**, which the
`50-transport.md` §6 table wants kept off the owner's access path — can reach:
`tcp/5432` on the laptop (§1), `tcp/443`+`3086` on secratary (the phone gate, §3), `tcp/3086` on the laptop
(the phone gate, §3), `tcp/3089` on secratary, the SSH port (22) everywhere, and the Chroma/DB/vector
files' host services. The design doc's own words apply: *"a shared GUI authority is a shared cookie
jar"* — and the measurement is that the cookie jar is currently open to the whole tailnet.

---

## 3. The phone gate and the engine token flow

### 3.1 What runs, and where

| Node | Process | Listens | Log |
|---|---|---|---|
| secratary | `phone-gate.service` → `/usr/bin/python3 /home/zabz/harness-config/scripts/phone-gate.py --listen-port 3086 --engine-port 3089` (User=zabz, started **Mon Sep 14 21:43:48 2026**, PID 3660824) | `127.0.0.1:3086` only | `~/.dsh-phone/gate.log` (append, `StandardOutput=`) |
| secratary | `phone-engine.service` → `dsh web` on **3089**, loopback only (node, PID 906634) | `127.0.0.1:3089` only | `~/.dsh-phone/engine-3089.log` |
| ZABZ-YOGA | `python.exe C:\Users\ezabz\code\harness-config\scripts\phone-gate.py --listen-port 3086 --engine-port 3099 --engine-authority 127.0.0.1:3099 --log-file %LOCALAPPDATA%\dsh-phone\gate-3086.log` (PID 17312) | `127.0.0.1:3086` only | `%LOCALAPPDATA%\dsh-phone\gate-3086.log` (5,755 B) |
| ZABZ-YOGA | the session engine: `node …\dsh\lib\bin.js web --port 3099 --no-open` (PID 1784) | `127.0.0.1:3099` only | `~/.dsh/multi-window/logs/3099.log` (82 B) |

Both gates bind **loopback only** — good, and it means the only door is `tailscale serve`, which is the
right shape. The live gate source on secratary is
`/home/zabz/harness-config/scripts/phone-gate.py`, **919 lines, sha256 prefix `8ef819be3b193633`**, and
the copy at `/home/zabz/code/harness-config/scripts/phone-gate.py` is byte-identical (same length, same
hash, MEASURED 21:55Z). The laptop's copy is a **newer 1,022-line variant** (it adds
`--engine-authority` and `--log-file`); the two are not the same file, which matters for any fix.

### 3.2 Where the startup token is written, and with what mode

**The token is never written to a file the gate creates.** It exists in exactly one place per node: the
engine's **stdout**, redirected to a log by the service manager (READ-FROM-CODE + MEASURED):

| Node | Path | Content | Mode / ACL |
|---|---|---|---|
| secratary | `~/.dsh-phone/engine-3089.log` | **four** lines `dsh web: http://127.0.0.1:3089/?token=<43 chars>` — one per engine start | **664** `zabz:zabz`; dir `~/.dsh-phone` **775**; home `/home/zabz` **750** |
| ZABZ-YOGA | `~/.dsh/multi-window/logs/3099.log` | one line `dsh web: http://127.0.0.1:3099/?token=<43 chars>` | ACL: `SYSTEM` FC, `Administrators` FC, `zabz-yoga\ezabz` FC — no other principal |

The token is a **43-character base64url** value (`randomBytes(32)`, `dsh-client-connection/lib/index.js:221,
:243`), and the gate re-reads it at request time from that log, so it survives an engine restart
(`phone-gate.py:77–116`). File modes: on Linux `664` is group-writable and world-readable — the saving
grace is that `/home/zabz` is `750`, so no other local user can traverse in. On Windows the ACL is
correct. **PROPOSED:** `chmod 600` both files and `chmod 700 ~/.dsh-phone`; it costs nothing and removes
the group/world read bit as a second line of defence.

### 3.3 Does it leak into logs — yes, a **prefix**, 190 times over

MEASURED 2026-09-16 22:00Z, over ssh, with the values masked in transit:

```
gate.log size                    : 9,660,824 B        (mode 664)
"token=" occurrences             : 3,202
length histogram                 : {4:1, 12:3, 17:2, 18:3196}
18-char values, distinct         : 18   (flkQ2A…, XbAaHD…, DuWjQN…, EIQFmV…, GEMrsK…, …)
FULL 43-char engine token present : 0 occurrences
```

and the decisive comparison — the 18-character strings are **exactly the first 18 characters** of each
engine launch token:

```
engine tokens (43 chars) first18 : GEMrsK40kIdKUa9wgR, InnoA31Pk5GKqf7mzW,
                                   EIQFmVaiMnsPBmzBsk, DuWjQNGWU8BHqsDO5I
engine token #0..#3 first18 present in gate.log : True, True, True, True
occurrences of the CURRENT token's prefix       : 190
```

**Verdict:** the log leaks **18 of 43 characters** (≈108 of ~256 bits) of every token the engine has
issued, including the live one. That is **not** replayable and not brute-forceable — so it is not a
compromise in itself. It is a discipline failure: the shipped source carries the comment *"Never log a
token"* (`phone-gate.py` ~line 690 in the 1,022-line variant), and the log has also been used as a test
surface (`a-dead-token`, `an-old-dead-token`, `dead`, `token-from-an-engi` all appear as values). The
Windows gate log is clean by comparison — its lines read
`GET /api cookie=True token_offered=False token_live=False proto=HTTP/1.1` and carry no token material
at all. **PROPOSED:** delete the value from the log line entirely, `chmod 600`, and truncate the
existing 9.6 MB file.

### 3.4 The cookie: lifetime, binding, and the missing `Secure`

MEASURED 2026-09-16 21:58Z — an **anonymous** `GET https://secratary.tail93e6e6.ts.net/` (no cookie, no
token) returned:

```http
HTTP/1.1 200 OK
Set-Cookie: dsh-auth-<sha256(authority)>=v1.eyJ2ZXJzaW9uIjoxLCJhdXRob3JpdHkiOiJzZWNyYXRhcnkudGFpbDkz
ZTZlNi50cy5uZXQiLCJpc3N1ZWRBdCI6MTc4OTU5NTkzODI1MSwiZXhwaXJlc0F0IjoxNzkyMTg3OTM4MjUxfQ.
<HMAC>; Max-Age=2592000; Path=/; Expires=Fri, 16 Oct 2026 21:58:58 GMT; HttpOnly; SameSite=Strict
```

Decoded payload: `{"version":1,"authority":"secratary.tail93e6e6.ts.net","issuedAt":1789595938251,
"expiresAt":1792187938251}`. The laptop's gate returned the same shape with
`"authority":"127.0.0.1:3099"` (its gate was launched with `--engine-authority 127.0.0.1:3099`).

| Question | Answer | Source |
|---|---|---|
| **How long does the cookie live?** | **30 days** (`Max-Age=2592000`, `Expires` +30 d; payload `expiresAt − issuedAt` = 2,592,000,000 ms) | measured above; `dsh-client-connection/lib/index.js:740` `cookieMaxAgeDays: z.natural().min(1).default(30)`, `:753` `?? 30` |
| **Is it bound to an authority?** | **Yes, twice.** The cookie *name* is `dsh-auth-` + base64url(sha256(authority)) (`index.js:281`); the *value* is HMAC-signed over `{version, authority, issuedAt, expiresAt}` (`:318`) and rejected unless `payload.authority` matches (`:440`). A cookie minted for `127.0.0.1:3099` does not exist for `secratary.tail93e6e6.ts.net`. | READ-FROM-CODE, cited lines |
| **Flags** | `Max-Age`, `Path=/`, `Expires`, `HttpOnly`, `SameSite=Strict` — and **no `Secure`** | `sessionCookie()` at `index.js:292-293`, verbatim: `` `${name}=${value}; Max-Age=${…}; Path=/; Expires=${…}; HttpOnly; SameSite=Strict` `` |
| **How is the cookie minted?** | Only a root `GET /` carrying exactly one `?token=` equal to the process launch token mints it (`index.js:389-405`). The token is compared in constant time (`tokenMatches`, `:275`). | READ-FROM-CODE |

**The missing `Secure` is a real defect** even though the transport is HTTPS: the cookie is accepted on
any scheme, so any future plain-HTTP path to the same authority (a Tailscale serve rule on :80, a proxy,
a downgrade) sends a full-control session cookie in the clear. It is a one-word upstream fix in
`dsh-client-connection`.

### 3.5 The gate removes the token from the equation entirely

The gate's own logic (`phone-gate.py`, both variants) is:

```python
has_cookie = COOKIE_PREFIX in head
offered    = dict(parse_qsl(query)).get("token", "")
token      = live_token(engine_port) if document_request else ""
needs_token = bool(token) and ((not offered and not has_cookie) or (bool(offered) and offered != token))
if needs_token:
    signed_in = complete_login(engine_port, first, token, path)   # gate logs in ON THE VISITOR'S BEHALF
```

`complete_login()` (`:285–339` in the 1,022-line file) then appends the live token itself, keeps the
engine's `Set-Cookie`, fetches the document with it, **and returns the document together with that
cookie to the visitor**. So a visitor who presents **no credential whatsoever** is signed in — by the
gate, using the engine's own launch token, which the visitor never sees. The design note says this
explicitly: *"the client gets a working page in one request, no redirect chain, no token in its URL or
its history."* The author intended that, for the owner's phone.

**Verified live, both nodes** (MEASURED 21:58Z / 22:00Z):

| Test | ZABZ-YOGA | secratary |
|---|---|---|
| `GET /` with no cookie, no token | **200**, 54,512 B, 1 cookie set | **200**, 1 cookie set |
| `GET /api` **with that cookie** | **404** | **404** |
| `GET /api` without a cookie | **401** (documented in `50-transport.md` §2; fence accepted, unauthenticated) |

The 401 → 404 transition **is** the proof of authentication: the engine answers 401 for "no session",
and 404 only after the session is accepted and the route is looked up. (`/api` is not itself a route.)

**What an attacker on the tailnet who has the token URL can do — and the worse case:** they do not need
the token URL. One `curl -i https://secratary.tail93e6e6.ts.net/` from any tailnet node returns a
**validated, 30-day session cookie for an engine whose tools execute shell commands as the owner on that
host**. That is remote code execution as `zabz` on **the company authority** — 203 tables, 18 agents,
`secretary-api`, Gmail/Calendar, Twilio voice, Dialpad, and whatever credentials live in its environment
— and the same on the roaming laptop. The blast radius is bounded **only** by tailnet membership, and
§2.4 measured that membership as *every device on the tailnet, on every port, with no tags and no
boundary*, including the employee's mac mini.

### 3.6 The fix, in order (PROPOSED — nothing applied)

1. **Put the ACL in first; it is the only control that helps today and it needs no code change.**
   `50-transport.md` §4's policy shape, tightened for this finding: allow `tcp 443` and `tcp 3086` on
   `secratary` **only** from `iphone-15-pro` and `zabz-yoga-1`; allow `tcp 443`/`3086` on `zabz-yoga-1`
   only from `iphone-15-pro`; default deny. That removes the employee's node, and any future device, from
   the door in ~30 minutes of admin-console work.
2. **Then make the gate identity-aware.** `tailscale serve` adds `Tailscale-User-Login`,
   `Tailscale-User-Name` and `Tailscale-User-Profile-Pic` headers; the gate already parses the first
   request's headers, so an allow-list check costs about ten lines. (READ-FROM-DOCS:
   <https://tailscale.com/kb/1312/serve>.) Until that exists, ACL is the whole boundary.
3. **Set `Secure` on the session cookie** upstream in `dsh-client-connection/lib/index.js:292` and ship it
   as a harness-config change so every node gets it.
4. **Stop the token prefix in the log**, `chmod 600 ~/.dsh-phone/engine-3089.log` and `gate.log`,
   `chmod 700 ~/.dsh-phone`, and truncate the 9.6 MB log.
5. **Reconcile the two gate variants.** `secratary` runs the 919-line file, the laptop the 1,022-line
   one. Any of fixes 2–4 must land in both, or the authority keeps the older behaviour.

---

## 4. Secrets in the repositories

Method: `git grep` over **tracked files only** in every repo under `C:\Users\ezabz\code` (22 dirs), for
Twilio SIDs/tokens, AWS key ids, Google API keys, Slack/GitHub tokens, PEM private keys and AI-gateway
keys; plus `git log --all -S <value>` for history. MEASURED 2026-09-16 21:56–22:04Z. **No secret was
used to authenticate to any service.**

### 4.1 The Twilio finding (owner question 17) — confirmed, with a correction

Tracked files, repo family `phone-and-tech` / `phone-and-tech-full` / `_pt_deploy` / `_pt_faqfix` /
`_pt_hours` / `_lpt-w6-wt` (all five worktrees carry the identical leaks):

| File | Line | Value (masked) |
|---|---|---|
| `backend/eslint-results.json` | 78 | `TWILIO_ACCOUNT_SID = 'AC274c…'` (**34**, prefix `AC274c`), `TWILIO_AUTH_TOKEN = '<32 hex>'`, `TWILIO_PHONE_NUMBER = '+17324447361'`, and `DATABASE_URL = 'postgresql://postgres:<25-char pwd>@localhost:5432/phonetech_dev'` — all four inside one embedded source string |
| `backend/.env.test` | 29 | `AWS_ACCESS_KEY_ID="AKIA4T4OBZYQJVFWTWXJ"` (20 chars, prefix `AKIA4T`) |
| `docs/features/twilio/TWILIO_CONFIGURATION_COMPLETE.md` | 90, 113, 136 | two Twilio **API key SIDs**: `SK7196c8…`, `SK8ece6e…` (34 chars each) |
| `docs/development/setup.md` | 82 | the SID again |
| `docs/reference/reports/SECURITY_AUDIT_ENV_VARIABLES.md` | 63 | the SID again |
| `archive/fixes/TWILIO_ACCESS_TOKEN_FIX_COMPLETE.md` | 108–109 | the SID + `SK8ece6e…` |
| `archive/fixes/TWILIO_CONFIGURATION_FIX.md` | 277 | the SID |
| `backend/simple-server.js` :29, `backend/archived-servers/simple-server.cjs` :12 | | the SID as a hardcoded fallback |
| `backend/.env.production` | — | **clean**: every value is a `${VAR}` placeholder of length 15–24 |

History: **15 commits** contain the auth-token value in each of `phone-and-tech` and
`phone-and-tech-full` (bounded `git log --all -S`; the `_pt_deploy` scan was not completed within its
time budget and is **COULD NOT VERIFY**).

### 4.2 Are they still live — answered **without** authenticating

The deployed environment on the authority (`/home/zabz/personal-secretary-mvp/.env`, read over ssh
22:03Z) was hashed with sha256 and **only the hash prefixes and lengths were printed**; the repo values
were hashed locally with the same scheme:

| Credential | Repo sha256[:12] | Deployed sha256[:12] | Verdict |
|---|---|---|---|
| `TWILIO_ACCOUNT_SID` | `548ec70275f4` (len 34, prefix `AC274c`) | `548ec70275f4` (len 34) | **SAME — the account is still the live one** |
| `TWILIO_PHONE_NUMBER` | `8eaefedefefe` (len 12) | `8eaefedefefe` (len 12) | **SAME — the number is still the live one** |
| `TWILIO_AUTH_TOKEN` | `19bd1cb96bc9` (len 32) | `5ec4d09b6741` (len 32) | **DIFFERENT — the committed token is NOT the deployed one** |

**So the owner question's premise is half right and the conclusion is better than feared:** the *account
SID* and *phone number* in the repo are the live ones (but a SID is an identifier, not a credential, and
the number is `+17324447361`, which is on the shop's website). The **auth token has already been
rotated** — which matches the journal's record of the 2026-09-15 ZABZ-TECH credential session (`D164`
AWS key killed, `D165` Twilio token rotated, handoff `H275`). From this evidence the committed auth
token is **dead**.

**COULD NOT VERIFY (would require authenticating, which the mandate forbids):**
- whether the two committed Twilio **API key SIDs** (`SK7196c8…`, `SK8ece6e…`) still exist in the
  account — these are the highest-value un-rotated items in the whole sweep, because an API key SID is
  useless without its secret, and I found no secret beside them;
- whether `AKIA4T4OBZYQJVFWTWXJ` is live (the journal says the AWS key was killed 2026-09-15; the file
  beside it sets `AWS_SECRET_ACCESS_KEY="test"`, so it may never have been a working pair — not
  verified).

### 4.3 Public exposure — none found, and that changes the remediation

| Target | Result (unauthenticated, 2026-09-16 22:04Z) |
|---|---|
| `api.github.com/repos/lakewoodphoneandtech/phone-and-tech-full` | **HTTP 404** |
| `api.github.com/repos/lakewoodphone/phone-and-tech-full` | **HTTP 404** |
| `lakewoodphone/personal-secretary-mvp`, `…/lpt-hub`, `…/lpt-flip-phone`, `…/kosher-filter-ai` | **HTTP 404** each |
| `raw.githubusercontent.com/lakewoodphone/phone-and-tech-full/main/backend/eslint-results.json` | **HTTP 404**, 14 B |

Note there are **two remotes**, not one: the worktree `phone-and-tech` pushes to
`github.com/lakewoodphoneandtech/phone-and-tech-full.git` (organisation `lakewoodphoneandtech`) while
`phone-and-tech-full` and its four siblings push to `github.com/lakewoodphone/phone-and-tech-full.git`
(user `lakewoodphone`). Both were tested. A 404 to an anonymous request means *private, renamed, or
non-existent* — **COULD NOT VERIFY which**, without authenticating. So the blast radius of the committed
secrets is **"anyone with repository access, including its entire history"**, not the internet.

### 4.4 The rest of the sweep

| Finding | Evidence | Risk |
|---|---|---|
| **Google API key** `AIzaSyA1FVCaYvO_NoyD6GggCvBHelINpUHLeMg` | tracked, `lpt-hub/legacy/kyocera-escalator-value/build-tools/waze-patch/waze-{check,json}/resources/resources.arsc.json` lines 154365 and 154389 (4 files) | Medium-low. It is a key lifted from a decompiled **Waze** APK resource dump. Google API keys are normally app/package-restricted; liveness **COULD NOT VERIFY** without a billed request. Delete it — it is build debris, not configuration. |
| **`LPT_WEBHOOK_SECRET` (26 chars) and `LPT_WS_AUTH_TOKEN` (25 chars) with real values** | tracked, `kosher-filter-ai/server/.env.production` | **Live-looking.** Every Twilio/SMTP/Telegram/FCM value in the same file is empty; these two are populated. Liveness **COULD NOT VERIFY**. These are the second-most-important rotation after the Twilio API keys. |
| `SECRETARY_API_KEY` | `personal-secretary-mvp/apps/rentals/.env.example` (commented), `docker-compose.yml` (`${SECRETARY_API_KEY:-}`) | Clean — placeholders only. |
| Trailing SIDs elsewhere | `personal-secretary-mvp/deploy/twilio-studio-flow/.env.vogel:3` `AC17e2845e090caac224ce14860d7b5b41`; `docs/family-chat/README.md:129` + `tests/test_family_chat.py:763` `AC6e036fd23774a9a22e0cb7e74cc9f292`; `docs/wedding/invite-campaign/wedding-campaign-log.txt` (~800 lines of `POST /Accounts/AC274c…` URLs) | Account **identifiers** in documentation and test fixtures. The `.env.vogel` and `README.md` ones are *different* accounts from the live one — verify in the console, but they are not credentials. |
| **PEM certificates** | `lpt-hub/docs/setup/certs/mosyle-apns-push-cert.pem` — 1,986 B, **one `BEGIN CERTIFICATE` block, `contains 'PRIVATE KEY': false`** | Low. A public certificate without its key. Keep, or move it out of the tree for tidiness. |
| **Android keystore** | `lpt-flip-phone/tools/debug.keystore` | Low. The standard shared Android *debug* keystore — publicly known, not a secret. |
| **SSH / PEM private keys in tracked files** | none. The only `BEGIN … PRIVATE KEY` hits are three **test fixtures** in `unified-search` (`adapters/localdb/redactor_demo.py:35`, `adapters/localdb/sync.py:274`, `tests/test_localdb_adapter.py:690`) | Clean. |
| **AI-gateway keys** | none live. Every `sk-`/`sk-ant-` hit is a placeholder (`sk-your_openai_api_key_here`), a redactor demo string, or a test assert (`harness-config/scripts/test_logging_configured.py:74` uses `sk-livekeyvalue1234567890`) | Clean. |
| **Tracked `.env*` files across all repos** | `phone-and-tech` family: `.env.e2e`, `.env.example`, `.env.production.template`, `.env.template`, `backend/.env.example`, **`backend/.env.test`**, **`backend/.env.production`**; `kosher-filter-ai/server/.env.production`; `personal-secretary-mvp/deploy/twilio-studio-flow/.env.vogel`; `scripts/netlify-config.env` | The tracked **`.env.test` is the leak** (AWS key id); `.env.production` in the phone-and-tech family is clean (placeholders) while `kosher-filter-ai`'s is not. |

### 4.5 Remediation plan — rotation order, and **no history rewrite**

**Rotation order, least blast radius first, each verified by the command that proves it took effect:**

1. **Revoke the two Twilio API key SIDs** `SK7196c8…` and `SK8ece6e…` (Twilio console → Account → API
   keys & tokens). This is first because they are the only *live-looking* Twilio credentials found and
   revocation is instant and reversible-by-issuance. Verify: `GET https://api.twilio.com/2010-04-01/
   Accounts/<SID>/Keys.json` no longer lists their SIDs.
2. **Deactivate `AKIA4T4OBZYQJVFWTWXJ`** if it is still `Active` (journal `D164` says it was killed
   2026-09-15 — confirm, do not assume). Verify with the AWS console key list, or
   `aws iam list-access-keys --user-name <user>`.
3. **Rotate `LPT_WEBHOOK_SECRET`, then `LPT_WS_AUTH_TOKEN`** in that order (the webhook secret authorises
   inbound requests to the edge relay; rotate it first or a stale token authenticates against a fresh
   secret during the window).
4. **Restrict or delete the Google API key** `AIzaSyA1FVCaYvO_NoyD6GggCvBHelINpUHLeMg` in the Google
   Cloud console. It is build debris; deletion is the fix.
5. **Do not rotate the Twilio auth token again.** The hash comparison in §4.2 proves the committed value
   is not the live one; rotating for this finding would be work with no security benefit.
6. **The `phonetech_dev` Postgres password** in `eslint-results.json` already fails (§1.5) — nothing to
   rotate. Delete the string.

**History rewrite vs rotation-only → rotation-only. No `git filter-repo`, no `git push --force`.**

The reasoning, stated so it can be argued with: (a) both remotes return 404 to anonymous requests, so the
secret material is not publicly readable; (b) the only genuinely sensitive value in the sweep — the
Twilio auth token — is **already rotated**, so its presence in the history is a record, not a
capability; (c) the repos carry 8,000+ commits and **five live worktrees** (`_pt_deploy`, `_pt_faqfix`,
`_pt_hours`, `_lpt-w6-wt`, `phone-and-tech-full`) on a machine where a `filter-repo` that goes wrong
destroys working trees and uncommitted work — which is the exact class of damage this business has
already suffered twice; (d) a rewrite requires force-pushing two remotes and would invalidate every
branch and every open PR. **The one condition that flips this decision: if any of these repos is ever
made public, the rewrite becomes mandatory before that happens.** Write that down where the person who
makes the repo public will read it.

**Files that must change** (delete the literal value, keep the key name — in **every one of the six
worktrees**, not just one):

```
phone-and-tech{,-full}/backend/eslint-results.json          # SID, auth token, phone number, DB password
phone-and-tech{,-full}/backend/.env.test                    # AWS_ACCESS_KEY_ID
phone-and-tech{,-full}/backend/simple-server.js             # hardcoded SID fallback
phone-and-tech{,-full}/backend/archived-servers/simple-server.cjs
phone-and-tech{,-full}/docs/development/setup.md
phone-and-tech{,-full}/docs/features/twilio/TWILIO_CONFIGURATION_COMPLETE.md   # 2 API key SIDs
phone-and-tech{,-full}/docs/reference/reports/SECURITY_AUDIT_ENV_VARIABLES.md
phone-and-tech{,-full}/archive/fixes/TWILIO_ACCESS_TOKEN_FIX_COMPLETE.md
phone-and-tech{,-full}/archive/fixes/TWILIO_CONFIGURATION_FIX.md
kosher-filter-ai/server/.env.production                     # LPT_WEBHOOK_SECRET, LPT_WS_AUTH_TOKEN
lpt-hub/legacy/kyocera-escalator-value/build-tools/waze-patch/waze-*/resources/resources.arsc.json
personal-secretary-mvp/docs/wedding/invite-campaign/wedding-campaign-log.txt   # or accept: identifiers only
```

Plus `.gitignore` entries (`backend/.env.test`, `backend/eslint-results.json`, `server/.env.production`,
`deploy/twilio-studio-flow/.env.vogel`) and one `gitleaks` pre-commit hook in each repo. Note that
`unified-search` already ships a working redactor (`adapters/localdb/sync.py`) that catches exactly these
patterns — reuse it rather than writing a new one.

**Verification that the fix took, per repo, must return nothing:**
`git -C <repo> grep -n -I -E 'AC[0-9a-f]{32}|SK[0-9a-f]{32}|AKIA[0-9A-Z]{16}|AIzaSy[A-Za-z0-9_-]{33}|LPT_WEBHOOK_SECRET=.{8,}'`

---

## 5. CVE-2026-11822 — SQLite FTS5 memory corruption

### 5.1 Is it real? **Yes — confirmed from two primary sources.**

| Source | What it says |
|---|---|
| **NVD** `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2026-11822` (fetched 2026-09-16 21:56Z) | `"vulnStatus":"Analyzed"`, `published 2026-06-09T20:16:32.150`, `lastModified 2026-07-23`, source `disclosure@vulncheck.com`. Description, verbatim: *"SQLite before 3.53.2 contains memory corruption vulnerabilities in the FTS5 full-text search extension … an out-of-bounds read in `fts5LeafSeek()` via an attacker-controlled loop bound and a heap buffer overflow write in `fts5ChunkIterate()` through a crafted continuation page causing an integer underflow, exploitable when an FTS5 MATCH query is executed against the malicious database."* CWE-122. CVSS 3.1 **7.8** HIGH `AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H`; CVSS 4.0 **8.5** `AV:L`. CISA ADP SSVC: `exploitation: none`, `automatable: no`, `technicalImpact: total`. Patch refs `sqlite.org/src/info/061febcf41ca`, `sqlite.org/src/info/4a5ad516ea93`; release notes `sqlite.org/releaselog/3_53_2.html`. |
| **MITRE** `https://cveawg.mitre.org/api/cve/CVE-2026-11822` (fetched 21:56Z) | `cveMetadata.state: PUBLISHED`, assigner **VulnCheck**, `datePublished 2026-06-09T19:08:31Z`, `dateUpdated 2026-07-14`. Title: *"SQLite before 3.53.2 Memory Corruption in FTS5 Extension"*. `cpeMatch: cpe:2.3:a:sqlite:sqlite:*` `versionEndExcluding: 3.53.2`. Finder credited: Ashish Kunwar (@D0rkerDevil). |

**It is not a phantom CVE.** The version boundary in journal `P203` — *"3.49.1 (Yoga) and 3.46.1
(secratary); fixed in 3.53.2"* — is **correct**, and the CVSS 3.1 7.8 it quotes is correct. The brief's
phrasing "fixed in 3.53" is imprecise: the boundary is **3.53.2**, and `nvd` marks **every** version
`< 3.53.2` affected.

### 5.2 What exploitation requires

1. A **database file the attacker controls**, carrying malformed FTS5 page data (a crafted continuation
   page for the `fts5ChunkIterate()` heap overflow; an attacker-controlled loop bound for
   `fts5LeafSeek()`), **and**
2. an **`FTS5 MATCH` query executed against that database**, **and**
3. **user interaction** (CVSS `UI:R`) — someone has to open/index the file. `AV:L` means it is a *local*
   attack: the file has to arrive on the machine by some other means. No privilege required
   (`PR:N`), no network vector.

### 5.3 Actual exposure here

SQLite version in the Python on each node — `python3 -c "import sqlite3;print(sqlite3.sqlite_version)"`
(or `python -c …` on Windows), MEASURED 2026-09-16 21:53–22:00Z:

| Node | Python | `sqlite3.sqlite_version` | Below the fix (3.53.2)? |
|---|---|---|---|
| ZABZ-YOGA | 3.12.10 (`AppData\Local\Programs\Python\Python312`) | **3.49.1** | yes |
| ZABZ-TECH | 3.13.5 | **3.49.1** | yes |
| secratary | 3.14.4 | **3.46.1** | yes |
| zabz-tech-linux | 3.12.3 | **3.45.1** | yes |
| lakewooechsmini | 3.9.6 (CommandLineTools) | **3.51.0** | yes |

**All five nodes carry the vulnerable code.** That is not the same as being exploitable.

Which services use FTS5 (MEASURED: `sqlite_master` queried read-only, plus `grep -rl fts5` over the repos):

| Database | Size | FTS5 objects | Built by |
|---|---|---|---|
| `~/.usearch/usearch.db` (ZABZ-YOGA) | **2,247.9 MB** | 2 | `unified-search/scripts/usearch.py`, `scripts/sync.py` |
| `personal-secretary-mvp/data/secretary.db` (ZABZ-YOGA) | 492.2 MB | 2 | the app |
| `harness-config/journal/index/journal.db` | 7.4 MB | 1 | `journal/tools/journal.py` |
| `harness-config/scripts/fsearch.py`, `fsearch-refresh.py`, `commsindex.py`, `chatindex.py`, `dsh-archive-import.py` | — | — | present on **secratary and zabz-tech-linux too**, not only the laptop |

**Risk: LOW.** Every FTS5 index here is built by this system from corpora it already had; the attacker
must supply the *database file*, and **no path exists** by which a third party hands this stack an FTS5
database to run a `MATCH` against. `P203`'s reasoning holds. Two things keep it on the list anyway:
`unified-search` exists precisely to index local data, so the day someone points the localdb adapter at
a *customer-supplied* file this becomes live; and the surface is 2.7 GB across three databases, so a
memory-corruption bug there is a long-lived problem, not a curiosity.

### 5.4 Concrete upgrade path, per node

- **Windows (ZABZ-YOGA, ZABZ-TECH)** — CPython bundles SQLite, so there is no OS package to update.
  Either replace `DLLs\sqlite3.dll` under the CPython install with the official **sqlite.org win-x64
  3.53.2+** DLL, or move to a CPython whose bundled SQLite is already ≥ 3.53.2. Verify:
  `python -c "import sqlite3;print(sqlite3.sqlite_version)"` → ≥ `3.53.2`, then re-run the FTS5 read path
  (`journal.py status`, `usearch.py check`).
- **Linux (secratary 3.46.1, zabz-tech-linux 3.45.1)** — the low-risk route that needs no distro upgrade
  and survives reboots is the prebuilt wheel: `pip install pysqlite3-binary`, then `import pysqlite3 as
  sqlite3` in the FTS5 *writers and readers* (`fsearch*.py`, `commsindex.py`, `chatindex.py`,
  `dsh-archive-import.py`, `journal.py index`). Verify:
  `python3 -c "import pysqlite3;print(pysqlite3.sqlite_version)"`. The alternative — wait for a distro
  release carrying libsqlite3 ≥ 3.53.2 and `apt upgrade libsqlite3-0` — is cleaner long-term but slow.
- **macOS (3.51.0)** — same wheel route; the system SQLite is Apple's and not to be replaced.
- **Independent of version, keep `P203`'s other rule:** **one writer connection per FTS5 index
  database.** The WAL-reset corruption bug spans 3.7.0 → 3.51.2 (fixed 3.51.3) and needs two concurrent
  writer/checkpointer connections on one file; that is a live hazard for `usearch.db` and `secretary.db`
  today, at every version installed here.

---

## 6. Ranked table — by real exposure on this mesh

Ranked by *what an attacker actually gains tonight*, not by abstract severity. "Effort" is my estimate
for a competent operator with the access this audit had.

| # | Risk | What an attacker gains | Proving command | Fix | Effort |
|---|---|---|---|---|---|
| **1** | **Phone gate auto-sign-in on the tailnet** — any tailnet device, no credential, 30-day cookie | **RCE as the owner on `secratary`** (203-table authority DB, 18 agents, Twilio/Dialpad/Gmail credentials) and on the roaming laptop; full engine control, shell included | From any tailnet node: `curl -i https://secratary.tail93e6e6.ts.net/ \| head -20` → `200` + `Set-Cookie: dsh-auth-…`; then `curl -b <cookie> …/api` → `404` (authenticated) vs `401` anonymous | 1) ACL: `tcp 443`/`3086` on secratary and laptop **only** from `iphone-15-pro` + `zabz-yoga-1`, default deny. 2) Gate accepts only `Tailscale-User-*` identities. 3) `Secure` on the cookie upstream | ACL 30 min; gate change ~1 day |
| **2** | **Tailnet packet filter is default allow-all; no tags anywhere** — includes the employee's mac mini | Lateral reach to **every TCP/UDP port** on every node: 5432, 3086, 3089, 22, everything. This is what makes #1 reachable by someone who should not be at the door | `tailscale debug netmap \| jq .PacketFilter` → `Srcs` = the whole tailnet CGNAT space, `Dsts` = `0.0.0.0/0` ports `0-65535`, `IPProto [6,17,1,58]`; `AdvertiseTags: null` on every node | Apply `50-transport.md` §4's tag policy with default deny and no internet ingress; tag the five servers, leave owner devices untagged | 1–2 h |
| **3** | **PostgreSQL on the laptop: `listen_addresses='*'`, TCP reachable from the tailnet, `ssl=off`.** Auth refused only by one `pg_hba` default | Nothing tonight (auth is refused). One careless `md5`/`trust` line — or one guessed password — from full network access to a 1 GB database, and the firewall will not help | From `secratary-ts`: `timeout 4 bash -c 'cat < /dev/null > /dev/tcp/100.72.162.5/5432'` → **OPEN**, then the startup-packet probe in §1.6 → `FATAL 28000 no pg_hba.conf entry for host "100.84.72.88"` | `listen_addresses = 'localhost'` + `Restart-Service postgresql-x64-16`; verify only `127.0.0.1`/`::1` listen. Fallback: inbound Block rule for 5432 | 10 min |
| **4** | **Committed credentials in the phone-and-tech family + kosher-filter-ai** | With repo access: the live Twilio account SID, the live phone number, **two un-revoked Twilio API key SIDs**, an AWS key id, and two real LPT service tokens. (The Twilio **auth token** is already rotated — hash-proved.) Repos are **not** anonymously readable | `git -C <repo> grep -n -I -E 'AC[0-9a-f]{32}\|SK[0-9a-f]{32}\|AKIA[0-9A-Z]{16}'`; history: `git log --all --oneline -S 'eb9a3d7846e48e1532bb48253aba1efa'` → 15 commits | Revoke the 2 Twilio API keys → deactivate the AWS key → rotate `LPT_WEBHOOK_SECRET` then `LPT_WS_AUTH_TOKEN` → delete the Google key. **Rotation-only, no history rewrite**; rewrite becomes mandatory only if a repo goes public | 3–4 h |
| **5** | **Session-hygiene defects around the cookie and the token log** — no `Secure` flag; token prefix in a mode-664 log | A 30-day full-control cookie with no scheme protection: any future plain-HTTP path to the same authority leaks it. The log leaks 18/43 chars of every engine token, 190 times for the live one — not replayable, but credential material in a plain file | `python3 -c "…print(re.findall(r'token=([A-Za-z0-9_-]+)', open('/home/zabz/.dsh-phone/gate.log').read()))"` → all 4 engine tokens' first 18 chars, full 43-char token absent | `Secure` in `dsh-client-connection/lib/index.js:292`; stop logging the prefix; `chmod 600` the logs and `700 ~/.dsh-phone`; truncate the 9.6 MB log; reconcile the two gate variants (919 vs 1,022 lines) | 1–2 h |
| **6** | **CVE-2026-11822 (SQLite FTS5)** on all five nodes; 2.7 GB of FTS5 indexes | Local memory corruption → crash / OOB read / heap overflow write, i.e. possible code execution, **but only** when a `MATCH` runs against an attacker-supplied FTS5 database. No such path exists here | `python3 -c "import sqlite3;print(sqlite3.sqlite_version)"` on each node → 3.45.1 / 3.46.1 / 3.49.1 / 3.49.1 / 3.51.0, all `< 3.53.2` | `pip install pysqlite3-binary` on Linux/macOS and switch the FTS5 code; official win-x64 `sqlite3.dll` ≥ 3.53.2 on Windows. Keep one writer per FTS5 DB | 2–3 h |
| **7** | `RouteAll: true` with an empty `ExitNodeIP` on **ZABZ-YOGA and ZABZ-TECH** | Nothing today — the OS default route is intact on every node measured. It is a pre-armed blackhole one command away on the machine the owner depends on | `tailscale debug prefs \| jq '{RouteAll,ExitNodeIP}'` → `true`/`""`; `Get-NetRoute -DestinationPrefix 0.0.0.0/0` → `192.168.12.1`, metric 0 | `tailscale set --exit-node=` on both Windows nodes | 1 min each |
| **8** | **Key expiry on every node** (earliest: ZABZ-TECH **2027-01-18**) | Nothing direct — an availability failure: an expired key removes a node from the tailnet and **nothing in the mesh notices** | `tailscale status --json \| jq '.Peer \| to_entries \| map({k:.key, exp:.value.KeyExpiry})'` | Disable key expiry for the five always-on nodes in the admin console; keep it on the laptop and phone | 10 min |
| **9** | **1 GB idle `personality_test` PostgreSQL cluster** on the laptop, auto-starting at boot | Nothing directly (auth refused, no connections, untouched since 2026-06-28). It is unexplained state — possibly real people's assessment answers — in a network-reachable service | `Get-ChildItem "<PGDATA>\base\16395"` → 372 files, newest `2026-06-28 00:17:15`; database name from an on-disk `global/1262` scan | `pg_dump` to the authority, then `Set-Service postgresql-x64-16 -StartupType Manual` (or uninstall). **Owner decision — it deletes data** | 1 h |

---

## 7. What was not verified, and why

| Question | Why it is open | What would settle it |
|---|---|---|
| Row contents of the laptop's 1 GB PostgreSQL cluster | No working credential: the repo's `postgres` password fails, there is no `pgpass.conf`, no `PGPASSWORD`, and `pg_hba` is `scram-sha-256` for local connections too | The owner supplies the password once, then: `psql -U postgres -d personality_test -c "\dt+"` and row counts per table |
| The mac mini's **own** tailnet prefs, serve and funnel state | `/usr/local/bin/tailscale status --json`, `debug prefs`, `serve status` and `funnel status` each **timed out at 10 s** (twice) — the macOS CLI is a GUI-app shim and blocks without a session | Run it from the console on `LakewooechsMini`, or read the state from the admin console's machine list |
| The tailnet **policy file text** | No admin-console/API token on this machine | Read the ACL in the admin console. What *is* proven is the compiled `PacketFilter` the node enforces (§2.4) |
| Whether the two committed Twilio API key SIDs and `AIzaSy…` still work | Verifying requires authenticating **with** them, which the mandate forbids | Twilio console → API keys & tokens; Google Cloud → Credentials |
| Whether `AKIA4T4OBZYQJVFWTWXJ` is live | Same reason; also journal `D164` (2026-09-15) says the AWS key was killed — believed dead, not proven | AWS IAM key list, or `aws iam list-access-keys` |
| Whether the committed Twilio auth token could be replayed anywhere else | Its hash differs from the authority's deployed token, so it is not the authority's; other consumers (the VPS, `lpt-apps-01`) were not enumerated | Compare hashes on the VPS the same way §4.2 compared them on secratary |
| The `phone-and-tech` vs `phone-and-tech-full` relationship | Both are separate clones with **different remotes** (two GitHub orgs); `git rev-parse --git-common-dir` returned `.git` for both, which does not distinguish clone from worktree | `git -C <dir> rev-parse --show-toplevel` + `ls <dir>/.git` (file vs directory) |
| The LAN-side exposure of 5432 on the laptop | No second device on 192.168.12.0/24 was reachable from this audit | One probe from any phone or laptop on the home network |

---

### Provenance summary

- **MEASURED on ZABZ-YOGA**, 2026-09-16 21:44–22:05Z: PostgreSQL service/version/config/`pg_hba`/PGDATA
  (§1); `tailscale status --json`, `debug prefs`, `debug netmap`, `serve status`, `funnel status`,
  `Get-NetRoute`, firewall rules (§2); listening sockets and process command lines for the gates and the
  engine, the tailnet GET/`/api` probes and the `Set-Cookie` values (§3); every `git grep` / `git log -S`
  result and the four unauthenticated GitHub API calls (§4); `python -c "import sqlite3"` and the
  `sqlite_master` FTS5 counts (§5).
- **MEASURED over ssh** (`-o BatchMode=yes -o ConnectTimeout=8`, all bounded, none left hung):
  `secratary-ts`, `desktop-ts`, `linux-pc-ts`, `mac-mini-ts` — the per-node tailnet sweeps (§2), the
  PostgreSQL reachability probe and the deployed-env hash comparison (§1.3, §4.2), and the gate log
  analysis (§3.3). Every ssh returned; the mac mini's Tailscale CLI was the only command that did not.
- **READ-FROM-CODE:** `@deepseek-ai/dsh-client-connection/lib/index.js` lines 221, 243, 265, 275, 281,
  292-293, 318, 324, 348-352, 389-405, 440, 740, 753; `harness-config/scripts/phone-gate.py` (1,022
  lines, laptop) and the live 919-line copy on secratary (sha256 prefix `8ef819be3b193633`).
- **READ-FROM-DOCS:** NVD and MITRE CVE records (§5.1); `sqlite.org/releaselog/3_53_2.html`;
  tailscale.com/kb/1242 (serve), /1312 (serve headers), /1223 (funnel).
- **Nothing was changed on any node.** No credential was rotated, revoked, deleted or used to
  authenticate. No file outside this document was created, edited, moved or deleted, and no
  state-changing git command was run.
