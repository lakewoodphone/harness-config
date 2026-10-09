# 122 — Provisioning the always-on authority box (`CCX13`, Ashburn)

**Owner decision, 2026-10-09:** provision the `CCX13` recommended in `121-always-on-server.md` §6.
**This document is the runbook.** Every command is meant to be copy-pasteable, and every step says what
success looks like, because a step with no check is a step nobody can trust.

**Nothing in this runbook destroys data.** The office `secretary.db` is never deleted, never overwritten,
and stays the authority until §5 says otherwise.

---

## 0. Prerequisites

| # | what | why | done by |
|---|---|---|---|
| P1 | the box exists: Hetzner Cloud → Ashburn (`ASH1`), Ubuntu 24.04, type `CCX13`, name `secratary-cloud`, the estate's ssh key installed | it is the whole subject | **the owner** (console login) |
| P2 | its public IPv4 written down | every step below needs it | the owner, or `hcloud server list` |
| P3 | an ssh alias `secratary-cloud` in `~/.ssh/config` | so nothing below hardcodes an IP | me |
| P4 | the tailnet auth key for a `tag:mesh-node` device, **key expiry disabled** | a node whose auth key expires silently leaves the mesh forever (`79` §1.3 step 7) | me, from the Tailscale admin console |

**A note on P4 that has already bitten this estate:** `79` §1.3 records that the provisioning script's
step 2 fetches `package-lock.json` **from the authority over the tailnet**, and a brand-new VPS is on
neither the LAN nor the tailnet yet. **So the order below is deliberate: join the tailnet FIRST, then
provision.** Getting this backwards is the failure the doc names explicitly.

---

## 1. First contact (5 minutes)

```bash
# 1a. the box answers, and it is the box we think it is
ssh -o ConnectTimeout=15 secratary-cloud "hostname; lsb_release -ds; nproc; free -m | head -2; df -h / | tail -1"
```
**Success:** `secratary-cloud`, Ubuntu 24.04, `2` cores, ~`7900` MB total, ~`75G` on `/`.
**If it says something else:** stop. Every later number is sized against those.

```bash
# 1b. baseline before anything is installed - so "it got slower" is measurable later
ssh secratary-cloud "cat /proc/loadavg; ss -ltn | head; systemctl list-units --type=service --state=running --no-legend | wc -l"
```

---

## 2. Join the tailnet BEFORE provisioning

```bash
ssh secratary-cloud "curl -fsSL https://tailscale.com/install.sh | sh"
ssh secratary-cloud "sudo tailscale up --authkey=<P4-KEY> --hostname=secratary-cloud --accept-routes=false"
```
**Success, checked from this laptop (not from the box):**
```bash
tailscale status | grep secratary-cloud         # present, and NOT "offline"
tailscale ping --timeout 5s -c 3 secratary-cloud
```
**Why this order matters:** §3 needs the authority's lockfile, and the only authenticated path to the
authority is the tailnet.

**Also set, while we are here:** key expiry **disabled** for this device in the Tailscale admin console.
That is not optional — an expiring key is how a node leaves the mesh permanently and quietly.

---

## 3. Prove the remote-provision path, then run it

`scripts/provision-mesh-node.sh` is the proven provisioner (`73-linux-pc-node.md` §1.2, proved on
`zabz-tech-linux`). It has a `local` half and a `--remote` half, is idempotent, and exits with typed codes
(`0` ok, `2` preflight refused, `3` a step failed, `4` verification failed, `20` <20 GiB free).

```bash
# 3a. preflight only - read what it wants to do without doing it
bash scripts/provision-mesh-node.sh --check secratary-cloud
```

```bash
# 3b. the real run, as its own node user
bash scripts/provision-mesh-node.sh secratary-cloud
```
**Success:** exit `0` **and** the headless turn returns its expected string. `73` §1.2 measured this whole
sequence at **~10 minutes** wall clock, dominated by the Node tarball (~29 MiB) and `npm ci` (524 packages,
~11 s).

**The credential step, which is the part that must not be got wrong** (`79` §3.2, `73` §1.2 step 4):
the model key goes in **`/etc/dsh-worker.env`, mode `0640 root:zabz`** — **never**
`~/.dsh/.credentials.yaml`, which is in `scripts/sync.py`'s `PROTECTED` set and which makes the engine
**refuse to start** if it ever has group/other bits.

---

## 4. The authority's own services

Only after §3 is green. Install, in this order, because each one's check needs the previous one up:

| # | what | how | check |
|---|---|---|---|
| 4a | Docker + Compose | `apt install docker.io docker-compose-v2` | `docker ps` works |
| 4b | `mesh-broker` | `mesh-broker.service` — the unit in `packages/mesh-broker/deploy/`, and `nodes.json` | `systemctl is-active mesh-broker`; `curl -s http://127.0.0.1:3091/healthz` |
| 4c | the broker's roster | `packages/mesh-broker/nodes.json`, with this box added as a node | `GET /nodes?fresh=1` names every node that answers |
| 4d | `secretary-api` + dashboard | `personal-secretary-mvp` deploy (its own `docker-compose.yml`) — **the DB comes in §5, not here** | `curl -s http://127.0.0.1:8002/health` answers `{"ok":true,…}` |
| 4e | the DSH engine's v2 route | mount `plugin-mesh-http`, `mesh-http.mjs secret`, then the installer | `GET https://secratary-cloud.tail93e6e6.ts.net/mesh/health` → 200 with `secretConfigured: true` |

**4b is the one that removes today's outage class.** With the broker on a box that is always on, and with
`119`'s failover placer in the provider, neither the broker's absence nor this box's absence can stop a
fan-out from the two Windows nodes.

---

## 5. Move the data (the one irreversible-feeling step, done reversibly)

**`112-single-source-of-truth.md` is unambiguous: a replica that can write has become a second company.**
So the copy is **read-only until §5e flips the writer, and the office DB is frozen — not deleted — as the
rollback.**

```bash
# 5a. a consistent snapshot from the LIVE database (never cp a hot SQLite file)
ssh secratary-ts "sqlite3 /home/zabz/personal-secretary-mvp/data/secretary.db \
  \".backup '/home/zabz/secretary-cloud-seed.db'\"" 
```
```bash
# 5b. send it (22.9 GB - expect minutes, run it in the background)
scp secratary-ts:/home/zabz/secretary-cloud-seed.db /tmp/seed.db   # via the laptop, or node-to-node over the tailnet
scp /tmp/seed.db secratary-cloud:/home/zabz/seed.db
```
```bash
# 5c. verify the COPY against the original, before anything is pointed at it
ssh secratary-ts  "sqlite3 .../secretary.db 'PRAGMA integrity_check; SELECT count(*) FROM sqlite_master WHERE type=\"table\";'"
ssh secratary-cloud "sqlite3 /home/zabz/seed.db 'PRAGMA integrity_check; SELECT count(*) FROM sqlite_master WHERE type=\"table\";'"
```
**Success = both print `ok` and the same table count.** Anything else: stop, and re-copy. A copy that has
not been compared to its original is not a copy.
```bash
# 5d. promote it, read-only, and SERVE NOTHING from it yet
ssh secratary-cloud "mv /home/zabz/seed.db /home/zabz/personal-secretary-mvp/data/secretary.db"
```
```bash
# 5e. THE SWITCH - all four together, or not at all
#    1. stop writers on the office box
ssh secratary-ts "systemctl stop secretary-api"
#    2. final dump from the now-quiet office DB, and move ONLY that
ssh secratary-ts "sqlite3 .../secretary.db \".backup '/home/zabz/final.db'\""
scp secratary-ts:/home/zabz/final.db secratary-cloud:/home/zabz/personal-secretary-mvp/data/secretary.db
#    3. start the API on the cloud box, and check ITS OWN loopback (its health shape, not Caddy's)
ssh secratary-cloud "systemctl start secretary-api; curl -s http://127.0.0.1:8002/health"
#    4. repoint the public hostname, LAST
```
**Rollback, if any check fails:** restart `secretary-api` on the office box. It is untouched and its data
is intact, so this returns the estate to today's behaviour in one command.
**The office DB is then left frozen for at least a week.** Not deleted.

---

## 6. Make it survive (this is the part that keeps it from being another version of today)

| # | what | why | check |
|---|---|---|---|
| 6a | nightly `VACUUM INTO` dump → object storage | a backup you have not restored is a hope | the file appears, with a date |
| 6b | **a restore drill, actually run** | the only proof | restore into a scratch dir and count rows |
| 6c | `fail2ban` + key-only ssh (`PasswordAuthentication no`) | this box has a **public IP** | `ssh -o PreferredAuthentications=password` is refused |
| 6d | a watchdog **outside the office** that reports **which host answered** | today's error was reading the wrong host's uptime (`120` §0) | it fires within a minute of a node leaving the tailnet |
| 6e | unattended upgrades, or a pinned kernel + a reboot plan | `86-authority.md`'s reboot was never performed — do not inherit that | `uptime` shows a reboot that happened on purpose |
| 6f | the rebuild script, timed | Hetzner bills hourly; a rebuild is ~3 min = **~1¢** (`79` §3.1) | a fresh box reaches `/mesh/health` 200 from scratch |

---

## 7. What this runbook does NOT decide, and must not be assumed

- **The database is 22.9 GB and its growth rate is unknown** (`121` §2). `db-growth.mjs` is sampling it.
  If it is a runaway writer, **fix that before moving it**, or the new box inherits the problem.
- **`CCX13` gives 80 GB.** Live DB **22.9 GB** + vectors **3.9 GB** + WAL and growth + ~25 GB of recent
  snapshots lands near **55–60 GB**, i.e. workable but **not roomy**. If the growth measurement says the DB
  is growing fast, the honest move is `CPX42` (8 / 16 GB / **320 GB**, $81.99) instead — and that is a
  decision to take *with the measurement in hand*, not now.
- **The 201 GB in `~/secretary-backups` does not move to this box.** It goes to object storage. Putting it
  on an 80 GB boot volume is the mistake that produced today's 86 %-full office disk.
- **Nothing here makes the office box redundant as a *worker*.** It stays useful; it just stops being the
  thing whose failure stops the company.
