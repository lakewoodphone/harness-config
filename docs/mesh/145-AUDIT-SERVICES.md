# 145 — SERVICE AUDIT: every long-running thing the office box ran, and whether the cloud authority runs it

**Workstream:** measurement only. **Nothing was fixed, nothing was started or stopped, no unit was
enabled, no database was written.**
**Written:** 2026-10-11, 15:38–15:45 UTC, from ZABZ-YOGA (Windows laptop).
**Authorities measured:**
- office box `secratary` = `ssh secratary-ts` — **READ-ONLY**, bounded commands only (load checked around
  every pass: `0.00 0.02 0.00` at 15:38:20Z, never above 0.02)
- cloud box `secratary-cloud` = `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` — THE AUTHORITY

**Why this audit exists.** The owner's phone app stopped working. The outage was not a configuration
error and not a missing file: it was a *service* that ran on the office box, was never migrated, and
whose cloud-side replacement **looks equivalent and proxies to nothing**. Every "the phone is fine"
claim made before that was based on config presence and `systemctl is-active`. So the standard here is
**prove behaviour or say UNKNOWN** — and a running process with no data behind it is not migrated.

**Reading key.** Every row carries the machine and the command that produced it. Verdict vocabulary:

| verdict | meaning |
|---|---|
| **MIGRATED-AND-WORKING** | a real request through it was observed to succeed on the cloud box |
| **MIGRATED-BUT-UNPROVEN** | the unit and its dependencies are present; no end-to-end request was proven |
| **NOT-MIGRATED** | it worked on the office box and does not exist or does not run here — a **regression** |
| **ALREADY-BROKEN-THERE** | it was already failed/absent on the office box before the freeze — not a regression |
| **OFFICE-HARDWARE-BOUND** | it reads a LAN device or a machine-local resource and cannot move |

**Headline.** The unit layer did **not** move wholesale — it was rebuilt, and the rebuild used systemd
timers instead of cron. Most of the estate's scheduled work is therefore genuinely alive (§1.2). But
**four long-running services did not move at all**, and one of them is served to the owner by a decoy
that reports health it does not have (§3.1). Separately, **doc 135 §2.1 is now stale in the estate's
favour**: `secratary-cloud` **is** on the tailnet (installed since that document was written) and
resolves every peer; the remaining `403`s are the mesh gate refusing an unsigned request, not
unreachability.

---

## §1 — THE UNIT-BY-UNIT TABLE

### §1.1 The estate's own units (the ones that matter)

Office state read 15:38–15:41Z; cloud state read 15:38–15:41Z. Both `systemctl list-units --all`,
`systemctl show <unit> -p UnitFileState -p ActiveState`, `systemctl cat`, and — where a verdict says
WORKING — a live request.

| office unit | state there | cloud counterpart | state here | verdict | evidence |
|---|---|---|---|---|---|
| `phone-engine.service` (DSH engine :3089, `--trusted-host secratary.tail93e6e6.ts.net`) | **loaded, enabled-state `disabled`, `inactive dead`**; ran 02:42→04:03 and was **stopped on purpose 04:03:34Z** | **none** — no unit, no `dsh-current`, no `.dsh-phone`, no `node/bin/node` | absent | **NOT-MIGRATED — REGRESSION** | office `systemctl cat phone-engine`; office journal `phone-engine` last line `2026-10-11T04:03:34 Deactivated successfully`; cloud `systemctl show phone-engine` → `UNIT-ABSENT`; cloud closure check: `/home/zabz/dsh-current` MISSING, `/home/zabz/.dsh-phone` MISSING, `/home/zabz/node/bin/node` MISSING |
| `phone-gate.service` (signs a cold visitor in, injects the phone layer, relays `/api` + WebSocket, :3086→:3089) | **enabled, active running**, MainPID 1366 since 2026-10-11 02:42:03Z | **none** — no unit, and `/opt/company/scripts/phone-gate.py` MISSING | absent | **NOT-MIGRATED — REGRESSION** | cloud `systemctl show phone-gate` → `UNIT-ABSENT`; cloud `ss -lntp` has **no :3086**; cloud port sweep `for p in 3086 3089; ss -lntH` → empty |
| `phone-redirector.service` (:3087 → tailnet) — *office ran it as a bare process, not a unit* | process pid 1816, started 02:42:14Z, `python3 .../phone-redirector.py --port 3087`; **no unit file on the office box** | `phone-redirector.service` | **enabled, active running**, pid 113000 | **MIGRATED-BUT-WORKING-ONLY-AS-A-DECOY — see §3.1** | cloud `curl -D- http://127.0.0.1:3087/phone` → `302 Location: https://zabz-yoga-1.tail93e6e6.ts.net/`; cloud `/etc/cloudflared/phone-redirector.env` → `PHONE_TAILNET=zabz-yoga-1.tail93e6e6.ts.net`; cloud `/var/lib/phone-redirector/engine-3087.log` → `phone redirector on secratary-cloud: marker only, the link target is the tailnet harness` / `token=cloud-marker-not-a-credential` |
| `tailscale serve` on the office box (proxies `/` → `127.0.0.1:3086` — **the phone's actual door**) | `tailscale serve status` → `https://secratary.tail93e6e6.ts.net (tailnet only) \|-- / proxy http://127.0.0.1:3086` | `tailscale serve status` on the cloud → **`No serve config`** | absent | **NOT-MIGRATED — REGRESSION** (the front half of the phone path) | office `tailscale serve status`; cloud `tailscale serve status` → `No serve config`; cloud `ss -lntp` → no listener on `100.73.176.126:443` |
| `mesh-broker.service` (placement broker, loopback `:3091`, `--config /home/zabz/mesh-broker/nodes.json`) | **enabled, active running**, pid 105841, started **09:29:14Z** (after the freeze) | `mesh-broker.service` at `/etc/systemd/system/`, `ExecStart=… /opt/mesh-broker/bin/mesh-broker.mjs --host 127.0.0.1 --port 3091 --config /opt/mesh-broker/nodes.json` | **`disabled`, `inactive dead`, `ConditionResult=no`** | **NOT-MIGRATED — REGRESSION** | cloud `systemctl show mesh-broker -p UnitFileState -p ActiveState -p ConditionResult` → `disabled / inactive / no`; cloud `ss -lntp \| grep 3091` → **nothing**; office `curl http://127.0.0.1:3091/nodes` → **200**, body `"reads": 20, "readFailures": 1`, `zabz-tech … "state": "ok", "latencyMs": 28` |
| `actions.runner.lakewoodphone-phone-and-tech-full.secratary-lpt.service` (GitHub Actions runner) | **enabled, active running**; `.runner` → repo `lakewoodphone/phone-and-tech-full`, agentId 21 | **none** — `/opt/actions-runner` MISSING | absent | **NOT-MIGRATED — REGRESSION** | office `systemctl list-units`; office `cat /opt/actions-runner/.runner`; cloud `ls -d /opt/actions-runner` → `No such file or directory` |
| `vscode-tunnel.service` (`code tunnel --name ezabz-secretary`, "personal secretary phone access") | **enabled, active running** | **none** — `code` NOT-FOUND on the cloud box | absent | **NOT-MIGRATED — REGRESSION** | office `systemctl cat vscode-tunnel`; cloud closure: `/home/zabz/.local/bin/code` MISSING, `command -v code` → NOT-FOUND, no `code`/`tunnel` process in `ps` |
| `xvfb-login.service` (`Xvfb :99` — "headed browser automation (finance sync)") | **enabled, active running** | **none** | absent | **NOT-MIGRATED** (impact gated on whether cloud browser automation needs a display — §4.4) | office `systemctl cat xvfb-login`; cloud `ps -eo … \| grep -E "Xvfb\|Xorg"` → nothing |
| `secretary-backup.service` (runtime backup, `backup-data.sh`) | **static, `failed`**; drop-ins date it 2026-09-30/10-07 | **none** | absent | **ALREADY-BROKEN-THERE** (it was in `failed` state on the office box) | office `systemctl show secretary-backup -p ActiveState` → `failed`; cloud `systemctl show secretary-backup` → `UNIT-ABSENT` |
| `secretary-access-watchdog.service` (oneshot) | static, inactive | none | absent | **NOT-MIGRATED** (low impact) | cloud closure → `UNIT-ABSENT` |
| `secretary-api-watchdog.service` (oneshot; alerts + one-shot recovery when the API unit exhausts its start burst) | static, inactive | none | absent | **NOT-MIGRATED** | cloud `UNIT-ABSENT`. The equivalent concern is live on the cloud — its own unit's `Restart=` behaviour was not measured (§4.5) |
| `secretary-api.service` (the old company API) | **`disabled`, `inactive dead`** | replaced by `company-api.service` | **enabled, active running** | **MIGRATED-AND-WORKING** | cloud `curl http://127.0.0.1:8002/health` → **200** in 0.229 s; `https://api.abletelsolutions.com/health` → **200** |
| `secretary-dashboard.service` | disabled, inactive | `secretary-dashboard.service` (Next.js) | **enabled, active running**, `*:3000` | **MIGRATED-AND-WORKING** | cloud `curl http://127.0.0.1:3000/health` → **200** in 0.254 s |
| `cloudflared.service` | enabled, active (tunnel `829bc0fb-…`) | `cloudflared.service` | **enabled, active running** (tunnel `3e62916c-…`) | **MIGRATED-AND-WORKING** | both `systemctl list-units`; `/etc/cloudflared/config.yml` read on both; cloud public doors answer (§2) |
| `estate-monitor.timer`/`.service` | **timer active, fires every 2 min** (last 15:38:04Z), service static/oneshot | `estate-monitor.timer`/`.service` at `/usr/local/bin/estate-monitor.py` (69,337 B, a real port of the office 56,417 B file) | **timer active**, last run 15:38:17Z | **MIGRATED-AND-WORKING** | cloud `journalctl -u estate-monitor -n 3` → `estate-monitor: NODATA offsite_object_age_h=8.684h … age=617s`; office same job at 15:38:06Z reported `offsite_r2_authority_age_h=8.685h` |
| `company-outcome-monitor.timer`/`.service` | timer active (last 12:07:03Z) | `company-outcome-monitor.timer`/`.service` → `/usr/local/bin/run-company-outcome-monitor.sh`, which execs `.venv/bin/python -m app.services.company_outcome_monitor` with `COMPANY_OUTCOME_JOURNAL_UNIT=company-api` | **timer active**, last run 12:07:01Z, **exit successful**, 3.4 s CPU | **MIGRATED-AND-WORKING** | cloud `journalctl -u company-outcome-monitor` → `Finished … Consumed 3.406s CPU time over 9.315s wall clock time`; cloud `grep -nE "python\|exec"` on the wrapper |
| `transcript-archive-pull.timer`/`.service` (**office had no such unit — it was cron**) | cron job `transcript-archive`, last ran 2026-10-10T22:23:01Z **exit 3** | `transcript-archive-pull.timer`/`.service` → `/usr/local/bin/transcript-archive-pass.sh` | **timer active**, last run 15:34:56Z, 6 m 45 s CPU / 11 m 29 s wall | **MIGRATED-AND-WORKING** | cloud closure: archive at `/opt/company/archive/lpt-transcripts` with `manifest.sqlite` **16,134,144 B, mtime 15:34**; `transcript-archive-server.py --check` output shows fresh arrivals (`zabz-tech dsh-sessions last_arrival 14:42:02Z`, `zabz-yoga copilot-chats 14:51:47Z`) |
| `authority-deadman.timer`/`.service` (**office had `deadman` as a cron job**) | cron `deadman` last ran **2026-10-10T22:45:02Z** and then stopped ~63 runs short of its schedule | `authority-deadman.timer` every 5 min → `/usr/local/bin/authority-deadman.py` | **timer active**, last run **15:39:29Z** | **MIGRATED-AND-WORKING** | cloud `journalctl -u authority-deadman -n 3` → `ping http 200 :: offsite=ok age=31823s sent=yes verified=ok db_tables=654 offsite=fresh` |
| `authority-offsite-backup.timer`/`.service` | office equivalent was cron `push-db-offsite` | `/usr/local/bin/authority-offsite-backup.sh` | **timer active**, last run **06:49:06Z**, 20 m 25 s CPU / 31 m wall | **MIGRATED-AND-WORKING** (its own success record includes a verified round trip) | cloud `/var/lib/authority-backup/last-run`: `status=ok database_sent=yes database_verified=ok sidecar_sent=yes ledger_sent=yes`, `source_bytes=23707291648`, `gz_bytes=6278791492`, `remote_bytes=6278791492` |
| `authority-report-offsite-age.timer`/`.service` | office equivalent was cron `report-offsite-age` | `/usr/local/bin/authority-report-offsite-age.sh` | **timer active**, fires every 30 min, last run 15:40:20Z | **MIGRATED-AND-WORKING** | cloud `journalctl -u authority-report-offsite-age` (4 runs logged, 15:40:20Z the newest) |
| `authority-data-offsite.timer`/`.service` | none (new) | `/usr/local/bin/authority-data-offsite.sh` | timer active; `data-last-run` written **09:44Z** | **MIGRATED-AND-WORKING** | cloud `ls -la /var/lib/authority-backup/` → `data-last-run` 312 B, mtime Oct 11 09:44 |
| `trunk-check.timer`/`.service` | **timer active, fires every 30 min**, last 15:14:44Z | **none** | absent | **NOT-MIGRATED** | office `systemctl list-timers` row for `trunk-check.timer`; cloud `systemctl show trunk-check` → `UNIT-ABSENT` |
| `tmp-reaper.timer`/`.service` (reap stale `/tmp` so TMPDIR writes cannot fail) | **timer active**, last 15:30:02Z | **none** | absent | **NOT-MIGRATED** (rationale is office-specific — §4.6) | office `systemctl list-timers`; cloud `UNIT-ABSENT` |
| `fa-index.timer`/`.service` (rebuild find-anything search indexes) | **timer active**, last 15:32:13Z | **none** | absent | **NOT-MIGRATED** | office `systemctl list-timers`; cloud `UNIT-ABSENT` |

### §1.2 The scheduled layer: cron → systemd timers (the rebuild is real, and it is not 92 jobs)

The office box's cron is **masked** (`/etc/systemd/system/cron.service -> /dev/null`, verified
15:41Z) and its preserved crontab holds **92 live jobs** (`grep -vcE "^\s*(#|$)"
/home/zabz/cutover/crontab.before` → `92`; `runs.tsv` last line `2026-10-11T04:00:02Z`).

The cloud box runs **`cron.service` active** but `crontab -l` → `no crontab for root`, and **7 estate
timers**:

| cloud timer | cadence | office cron family it replaces |
|---|---|---|
| `authority-deadman.timer` | 5 min | `deadman` |
| `estate-monitor.timer` | 2 min | `estate-monitor` (office ran it as a timer, not cron) |
| `authority-report-offsite-age.timer` | 30 min | `report-offsite-age` |
| `transcript-archive-pull.timer` | hourly | `transcript-archive` |
| `company-outcome-monitor.timer` | 4 h | `company-outcome-monitor` (office timer) |
| `authority-offsite-backup.timer` | daily (~05:23) | `push-db-offsite` / `company-offsite-push` |
| `authority-data-offsite.timer` | daily (~06:36) | none (new — `data/` had no scheduled offsite before) |

**Verdict: PARTIAL — the highest-consequence families moved and are firing, and ~85 of the 92 cron
jobs have no cloud counterpart.** That gap is already inventoried job-by-job in `132-CRON-INVENTORY.md`
and is not restated here. What this audit adds is that the gap is **not** 92 missing *mechanisms*: the
mechanism (cron) was replaced by one that fires on evidence (§1.1), so the residual work is porting the
**job bodies**, not rebuilding a scheduler.

### §1.3 Things on the cloud that were not on the office box (not regressions, recorded so the diff is honest)

`company-api.service` (the API itself, `enabled/active`, `127.0.0.1:8002`), the four new
`authority-*` units, and `transcript-archive-pull` are cloud-side creations rather than moved office
units. The office box's own `secretary-api` is `disabled`/`inactive` **and was already so before the
freeze** — its API had been replaced by `company-api` at cutover, so this is not a regression.

### §1.4 The two things the office box was serving that have no cloud equivalent at all, in any form

1. **The DSH engine for the phone (:3089) and the gate in front of it (:3086).** See §3.1.
2. **The live-voice dialer (`dialer.abletelsolutions.com`).** The office tunnel ingress has
   `hostname: dialer.abletelsolutions.com → http://127.0.0.1:8899`, and the cloud tunnel's own config
   says in a comment that the dialer "deliberately [has] NO rule here … their backends stay on the
   office box until they are moved". **Measured: nothing ever listened on `:8899` on the office box**
   (`ss -lntp | grep 8899` → no listener; no `/opt/dialer*` or `/home/zabz/dialer*`), and
   `https://dialer.abletelsolutions.com/` returned 502 in doc 135. So the *rule* was office-bound, the
   *backend* was already dead, and the verdict is **ALREADY-BROKEN-THERE**, not a regression.

---

## §2 — THE LISTENING-SOCKET COMPARISON

Both boxes, `ss -lntp` / `ss -lnup`, taken 15:38–15:41Z. Only *estate-owned* listeners are shown;
kernel/system listeners (`:22`, `:53`, `:323`, dbus, udev, snapd, resolv) are identical on both and are
not itemised.

| port | office `secratary` | cloud `secratary-cloud` | why it matters |
|---|---|---|---|
| **3086** | `127.0.0.1:3086` — `python3 phone-gate.py --listen-port 3086 --engine-port 3089` (pid 1366) | **nothing listens** | The phone gate. This is the service the owner's phone is served by today (office side). |
| **3087** | `127.0.0.1:3087` — `python3 phone-redirector.py --port 3087` (pid 1816, **no unit**) | `127.0.0.1:3087` — `phone-redirector.service` (pid 113000) | Present on both. On the cloud it 302s to `zabz-yoga-1.tail93e6e6.ts.net` because of a stale `PHONE_TAILNET` override, and the `503` guard is defeated by a marker file (§3.1). |
| **3089** | **nothing listens** (the engine was stopped at 04:03:34Z) | nothing listens | The engine itself. A gate without an engine is a door onto a wall; this was already true on the office box from 04:03Z. |
| **3091** | `127.0.0.1:3091` — `node /home/zabz/mesh-broker/bin/mesh-broker.mjs` (pid 105841, **started 09:29:14Z**) | **nothing listens**; unit `disabled`, `ConditionResult=no` | The mesh's placement broker. **The office box — the frozen rollback anchor — is the only machine running the mesh's control plane.** |
| **443 on the tailnet** | `100.84.72.88:443` + `:50101` (tailscale serve → `127.0.0.1:3086`) | `tailscale0` present (`100.73.176.126`) but **no serve config**, no `:443` | The phone's inbound door. Tailscale is installed and up on the cloud; the **serve** rule is what is missing. |
| **8002** | nothing (office `secretary-api` inactive) | `127.0.0.1:8002` — `python` (pid 105362) | The company API. **MIGRATED**; `GET /health` → 200. |
| **3000** | nothing (office dashboard inactive) | `*:3000` — `next-server` (pid 1089) | The dashboard. **MIGRATED**; `/health` → 200. |
| **20241** | `127.0.0.1:20241` (cloudflared, no owner shown in `ss -lntp`) | `127.0.0.1:20241` — `cloudflared` (pid 1068) | Tunnel metrics. Parity. |
| **8899** | **nothing** (no listener, ever) | nothing, and no tunnel rule | The dialer. Dead on both sides. |

**Public doors (behaviour, measured from the cloud box 15:41Z):**

| URL | result |
|---|---|
| `https://api.abletelsolutions.com/health` | **200** |
| `https://ai.abletelsolutions.com/phone` | **302** (to `https://zabz-yoga-1.tail93e6e6.ts.net/`) |
| `https://zabz-yoga-1.tail93e6e6.ts.net/` (the redirect target) | **403** |
| `https://<node>.tail93e6e6.ts.net/mesh/health` for `zabz-tech`, `zabz-yoga-1`, `secratary`, `zabz-tech-linux`, `lakewooechsmini` | **403 for all five** — the mesh gate refusing an unsigned request, **not** unreachability. Doc 135 §2.1 measured `000`/no-resolution; that is now stale: `getent hosts secratary.tail93e6e6.ts.net` → `100.84.72.88`, exit 0. |

**Ports on the office box with no counterpart on the cloud box — the headline list:**

1. **`:3086`** — the phone gate (NOT-MIGRATED, and the one the owner feels)
2. **`:3091`** — the mesh placement broker (installed on the cloud but disabled, `ConditionResult=no`)
3. **`:443` on the tailnet** — `tailscale serve` publishing the gate (tailscale itself *is* installed here now)

---

## §3 — THE REGRESSION LIST

Ordered by how badly the absence is felt. Each entry: what depends on it, and the exact way to restore
it. **Nothing in this section was executed.**

### §3.1 — `phone-engine.service` + `phone-gate.service` + `tailscale serve`: **the owner's phone app is broken, and a decoy on the cloud reports it healthy**

**What worked on the office box, proven end to end.** For 12 h 57 min the office box was serving the
owner's phone traffic:
- `phone-gate.service` — `enabled`, `active running`, pid 1366 since 2026-10-11 02:42:03Z
- `tailscale serve` — `https://secratary.tail93e6e6.ts.net (tailnet only) |-- / proxy http://127.0.0.1:3086`
- `/home/zabz/.dsh-phone/gate.log` — **599,405 lines** ending `2026-10-11T15:40:55`, with live GETs at
  15:39:55Z. Distinct tailnet clients over the life of that log, with their tailnet identities
  (resolved from `tailscale status` on the cloud box): `100.72.162.5` `zabz-yoga-1` 66,344 reqs ·
  `100.84.72.88` `secratary` 29,890 · `100.85.105.93` `iphone-15-pro` **18,472** ·
  `100.85.153.96` `zabz-tech` 16,605 · `100.126.146.121` `lakewooechsmini` 254 ·
  `100.76.204.64` `ipad-air-5th-gen-wifi` 50 · `100.118.10.22` `iphone-11` 43 ·
  `100.119.73.69` `iphone-11-1` 7 · `100.73.102.5` `iphone-se-gen-2` 1.
  So the gate has **not** been idle: an `iphone-15-pro` has made 18,472 requests through it and two
  more handset identities have reached it — which is what "the owner uses this" looks like in a log,
  and it is the strongest available evidence that this path was live work and not an abandoned script.
  The log's span could not be read from its first line (§4.11).
- `phone-engine.service` ran 02:42:03→04:03:34Z in a **manual start/stop series** (03:26:23, 03:28:01,
  03:39:15, 03:40:02, 03:44:30, 03:46:01, 04:03:33) — the last stop is 1 h 40 min before the freeze.

**The live failure, measured.** At 15:39:44Z the gate itself logged the failure the owner experiences:
```
GET / client=100.72.162.5 peer=127.0.0.1 cookie=False token_offered=False token_live=True
  -> not authenticated as sent: signing in in flight
  complete_login failed: [Errno 111] Connection refused
  OSError: [Errno 111] Connection refused
```
`phone-gate.py` connects to `127.0.0.1:<engine_port>` (lines 499, 520, 1482, 1851, 2349), and nothing
listens on `:3089` on the office box. And separately, at 15:40:16Z the **cloud** box probed the gate:
`GET /mesh/health client=100.73.176.126 -> REFUSED: not in phone-gate-allow.txt`.

**The trap, and it is exactly the shape the brief warned about.** The cloud box runs a *different*
service that looks equivalent:
- `phone-redirector.service` is `enabled`/`active`, `:3087` answers **302** — a live redirect, so
  `systemctl is-active` and a `curl` both say "fine"
- its target is `https://zabz-yoga-1.tail93e6e6.ts.net/`, taken from
  `/etc/cloudflared/phone-redirector.env` → `PHONE_TAILNET=zabz-yoga-1.tail93e6e6.ts.net` — **the
  laptop**, not the authority, and not this host's own name
- that target answers **403** (the mesh gate, not a phone gate)
- the process's own liveness guard (`live_token()` reads `engine-*.log` for `token=…`) is satisfied by
  `/var/lib/phone-redirector/engine-3087.log`, whose entire content is
  **`marker only, the link target is the tailnet harness` + `token=cloud-marker-not-a-credential`** —
  a 125-byte file that exists so the guard passes. There is **no engine** behind it.
- `tailscale serve status` on the cloud → **`No serve config`**, so even the front door is missing.

**Net effect for the owner:** the home-screen link `https://ai.abletelsolutions.com/phone` now lands on
the laptop's root, which answers 403. On the office box the same link would land on the gate — but the
gate cannot sign anyone in either, because the engine has been down since 04:03:34Z. **The phone app has
been broken since at least 04:03:34Z and the cutover made it unrecoverable rather than repaired.**

**What depends on it:** the owner's phone home-screen icon; `docs/dsh-mobile/02-SYSTEMS.md` (the units'
own Documentation= target); the `/api` and WebSocket relay; the attention feed
(`/dsh-attention.json`, still answering from the gate's own cache on the office box).

**To restore (not executed):**
1. Bring the engine's dependency closure to the cloud box — measured MISSING there:
   `/home/zabz/dsh-current` (office: a 33 B pointer), `/home/zabz/node/bin/node` (office: 124,836,408 B),
   `/home/zabz/.dsh-phone`, `/home/zabz/.dsh-tmp`, and the `@deepseek-ai/dsh` package tree.
2. Port the two units with their ExecStart repointed: `/usr/local/bin/phone-gate.py` (from
   `/home/zabz/harness-config/scripts/phone-gate.py`, 124,128 B), and the engine unit with
   `--trusted-host` set to **this host's** tailnet name, not `secratary.tail93e6e6.ts.net`.
3. `tailscale serve --bg --https=443 http://127.0.0.1:3086` on the cloud box.
4. Fix the redirector's target: `/etc/cloudflared/phone-redirector.env` →
   `PHONE_TAILNET=secratary-cloud.tail93e6e6.ts.net`, and delete or document the
   `token=cloud-marker-not-a-credential` marker so a future session is not misled by it again.
5. Stop the office box's `phone-gate.service` (it is serving a dead engine and it is on a box that is
   supposed to be inert) — **a separate decision, because it is currently the only thing the phone can
   reach.**

### §3.2 — `mesh-broker.service`: the mesh's control plane runs on the frozen office box, not the authority

**Measured.** Office: unit `enabled`, process pid 105841 started **09:29:14Z** (i.e. long after the
freeze), `:3091` listening, and it **answers**: `curl http://127.0.0.1:3091/nodes` → **200** with a fresh
roster (`"at": "2026-10-11T15:41:19.942Z"`, `"reads": 20, "readFailures": 1`, `zabz-tech … "state": "ok",
"latencyMs": 28`). Cloud: the package **is** present (`/opt/mesh-broker`, 13:27Z, with `bin`,
`lib`, `nodes.json` 14,335 B, `PROVENANCE.md`), the unit **is** installed with a correct ExecStart — and
the unit is **`disabled` / `inactive` / `ConditionResult=no`**, with **no `:3091` listener**.

**What depends on it:** every `subagent` dispatch whose placement resolves to `broker` mode
(`packages/plugin-remote-fanout/lib/index.js:71`); `lib/failover-placer.js`; the roster the whole fleet
is ranked from. Note the office broker's roster is `/home/zabz/mesh-broker/nodes.json` (15,217 B) while
the cloud's is `/opt/mesh-broker/nodes.json` (14,335 B) — **two different rosters**, and the office one
is the live one.

**To restore:**
1. `systemctl enable --now mesh-broker` on the cloud box (its own `ConditionResult=no` must be explained
   first — read `systemctl show mesh-broker -p Conditions` and the unit's `[Unit]` conditions).
2. Prove it reads a node: `curl -s "http://127.0.0.1:3091/nodes?fresh=1"` must show `state: ok` for at
   least one row, as the office broker does.
3. Repoint the mesh client (`MESH_BROKER_SSH` / `brokerSsh`) at the new authority.
4. Stop the office broker — it is a control plane on the rollback anchor.

### §3.3 — `vscode-tunnel.service`: the owner's named VS Code tunnel no longer exists anywhere

**Measured.** Office: `enabled`, `active running`, `ExecStart=/home/zabz/.local/bin/code tunnel --name
ezabz-secretary --accept-server-license-terms --cli-data-dir … --install-extension
…personal-secretary-ai-gateway-0.5.3.vsix`, `WorkingDirectory=/home/zabz/personal-secretary-mvp`;
the unit's own description is **"personal secretary phone access"**. Cloud: **no unit**, `code`
**NOT-FOUND**, `/home/zabz/.local/bin/code` **MISSING**, and no `code`/`tunnel` process in `ps`.

**What depends on it:** browser/mobile reach into the workspace without SSH; the
`personal-secretary-ai-gateway` extension that was installed by that command line.

**To restore:** install the VS Code CLI on the cloud box, copy the extension `.vsix`, and port the unit
with `--cli-data-dir` and `WorkingDirectory` repointed (`/opt/company` for the repo). The tunnel name
must be re-registered (a tunnel name is account-scoped, not host-scoped, so the old `ezabz-secretary`
may simply be reclaimed).

### §3.4 — `actions.runner.lakewoodphone-phone-and-tech-full.secratary-lpt.service`: the deployment pipeline for this business's main repo has no runner

**Measured.** Office: `enabled`, `active running`; `/opt/actions-runner/.runner` → agentId **21**,
`gitHubUrl: https://github.com/lakewoodphone/phone-and-tech-full`, `workFolder
/opt/actions-runner/_work`. Cloud: `/opt/actions-runner` **absent**, no runner unit.

**What depends on it:** any GitHub Actions workflow on `lakewoodphone/phone-and-tech-full` registered for
this runner — including anything the shop's own app repos expect to be executed on the estate's own
hardware rather than a GitHub-hosted runner.

**To restore:** install a runner on the cloud box and register it against the same repo (a fresh
registration token from GitHub is required — **that is a credential the owner must produce, one
question, not a task**). Note the runner is outbound-only, so no inbound port is needed; the office box
still has one registered and it is still online, which means **the two runners would both be eligible**
and jobs would land on whichever GitHub picks — decide whether to deregister the office one.

### §3.5 — `estate-monitor`'s offsite collector cannot read R2 (both boxes)

**Measured, on both machines, every 2 minutes.** Office:
`estate-monitor: NODATA offsite_r2_authority_age_h=8.685h … age=600s src=authority-push.json @
root@2.28.33.58 -- authority-push.json has no usable last_modified: {'key':
'authority/secretary.db.gz', 'error': "no boto3: No module named 'boto3'"}`. Cloud: the same line
with `offsite_object_age_h=8.684h`. Both report **NODATA**, and both cite `no boto3` — yet
`python3 -c "import boto3"` on the cloud box → **boto3 1.40.72** and `/usr/bin/python3` is the
interpreter. The monitor is therefore running under an interpreter that is not the one that has boto3,
and **the one number that says whether the company's offsite copy is fresh cannot be read on either
machine.** (The value it quotes, ~8.68 h, comes from a file, not from R2.)

**What depends on it:** `estate-monitor`, whose single allowed escalation is "the company being
unreachable from OUTSIDE this box"; the whole offsite-freshness story.

**To restore:** make the monitor's interpreter resolution explicit (it runs `ExecStart=/usr/local/bin/
estate-monitor.py` with `WorkingDirectory=/root` and no venv), or pre-resolve the object's
`LastModified` with the interpreter that *does* have boto3 and hand it the value. Note
`authority-report-offsite-age.service` **does** run successfully every 30 min (15:40:20Z) — so a working
reading exists; it is simply not where the monitor looks (`/var/lib/company-offsite/` does not exist on
the cloud box).

### §3.6 — Lower-consequence, recorded so the map is complete

| # | item | office state | cloud state | why it matters / to restore |
|---|---|---|---|---|
| a | `fa-index.timer` (`/home/zabz/bin/build-indexes.sh`) | timer active, last 15:32:13Z | absent | The `fa`/find-anything search index. Restore by porting `build-indexes.sh` (4,000 B) and its timer; until then fast search on the authority has no index. |
| b | `trunk-check.timer` (`trunk-check.sh`) | timer active, last 15:14:44Z | absent | Reports which machines' harness-config is on the trunk. Restore: port `trunk-check.sh` (2,836 B) + timer. |
| c | `secretary-api-watchdog.service` (`api-watchdog.sh`, 9,877 B) | static oneshot | absent | Alerts and recovers once when an API unit exhausts its start burst. The estate has no equivalent for `company-api`. Restore: port the unit with `WATCHDOG_UNIT=company-api.service`. |
| d | `tmp-reaper.timer` (`/home/zabz/bin/tmp-reaper.sh`) | timer active, last 15:30:02Z | absent | **Deliberately low priority**: its whole rationale is the office box's `/tmp` being a 12 GB `tmpfs` with `usrquota` (lpt-website item 450). The cloud box's `/tmp` is not that, so porting it verbatim would fix a disease the authority does not have. Measure before porting. |
| e | `xvfb-login.service` (`Xvfb :99`) | enabled, active | absent | Required only if cloud-side browser automation runs headed. **Whether any migrated finance job needs a display was not determined** (§4.4). |
| f | `secretary-backup.service` | **static, `failed`** | absent | Already failing there; the retention question it represents is doc 136's owner question, not a regression. |

### §3.7 — Reverse direction: things the cloud has that the office did not

`company-api`, `secretary-dashboard` and the four `authority-*` units are cloud-side creations. The
`phone-redirector` *unit* is cloud-only (the office ran the same script as an unsupervised process), and
`transcript-archive-pull` is a cloud-only unit replacing an office cron job. **None of these is a
regression of a service the office was running.**

---

## §4 — WHAT I COULD NOT DETERMINE

Stated plainly. An empty result is not health.

1. **Whether the phone path was working *at the moment of the cutover* (05:43:36Z).** Measured: the
   engine's last start was 03:46:01Z and its last stop 04:03:34Z; the gate has been up throughout; the
   office box was taking a manual start/stop series on `phone-engine` between 03:26 and 04:03. So the
   engine was **deliberately stopped 1 h 40 min before the cutover**, which means the phone was already
   down then — but **who stopped it and why is not determined**, and it changes whether the cutover
   *caused* the phone outage or merely failed to repair it. The answer is in the journal/session record
   around 03:26–04:03Z.
2. **Whether the `PHONE_TAILNET=zabz-yoga-1.tail93e6e6.ts.net` override was a deliberate
   out-of-the-way-hack or a mistake.** It is a `PHONE_TAILNET` env override in
   `/etc/cloudflared/phone-redirector.env`; the script would otherwise have reported its own
   `Self.DNSName` (`secratary-cloud.tail93e6e6.ts.net`). Given the marker file
   (`token=cloud-marker-not-a-credential`) I read this as deliberate — someone made the redirector
   *answer* and pointed it at a live machine. **Whether a gate is running on `zabz-yoga-1` was not
   measured**; if one is, the phone has a working door I have not seen.
3. **The remaining ~85 cron jobs with no cloud counterpart.** Their existence and classification are in
   `132-CRON-INVENTORY.md`; I did not re-derive them. **Do not read this audit as covering them.**
4. **Whether cloud-side browser automation needs `Xvfb`.** I did not run any finance job or read the
   Playwright launch path on the cloud box. So `xvfb-login` is "NOT-MIGRATED with unknown impact", not
   "proven harmful".
5. **Why the cloud's `mesh-broker` unit reports `ConditionResult=no`.** The unit file shows no explicit
   `Condition=` in the lines I read (`systemctl cat` printed `[Unit]` with only `After=`/`Wants=`), so the
   condition is either in a drop-in I did not enumerate or is an implicit one. **Unresolved**, and it is
   the first thing to check before `enable --now`.
6. **Whether the cloud's `company-api` has the start-burst cap the office's `secretary-api` had.** Doc
   135 quotes the office unit capping itself at "3 starts per 15 minutes" and the watchdog existing
   because of it. I read the cloud's unit but not its drop-ins for the same cap, and did not attempt to
   exhaust it. **Unmeasured.**
7. **The cloud's `authority-deadman` runs *on the authority it reports on*.** It is firing correctly and
   pinging healthchecks.io (`ping http 200 … sent=yes verified=ok`). What is **not** determined is
   whether the healthchecks.io check is configured to alarm on *absence of pings* — which is the only
   thing that makes a dead authority visible. If the check's grace period is wrong or the check is
   disabled, every "dead-man is green" claim in this audit is a claim about our own process, not about
   the owner being told.
8. **Who started the office brokers/timers that are still running after the freeze.** `mesh-broker`
   started 09:29:14Z and was installed 09:28:57Z on a box that is supposed to be read-only; a
   `phone-redirector` process was started 02:42:14Z. I did not attribute these.
9. **Whether the office box's `phone-gate` is reachable from the public internet.** It binds
   `127.0.0.1:3086` and is published only by `tailscale serve`. The office tunnel ingress shows **no
   rule for `:3086`** — but the gate log shows `peer=127.0.0.1` for everything, which is consistent with
   tailscale serve proxying. **I did not prove the path from the owner's device.**
10. **`secretary-dashboard`'s state on the office box only.** `disabled`/`inactive` there, active on the
    cloud — treated as a cloud-side creation, not a migration.
11. **The full time span of `/home/zabz/.dsh-phone/gate.log`.** The file is 599,405 lines and `head -1`
    returned binary content, so I established that its **last** line is `2026-10-11T15:40:55` and that an
    `iphone-15-pro` appears in 18,472 of its lines, but **not** the date the log opens. If those handset
    requests are all from before the freeze the "in use now" reading is weaker; the live GETs at
    15:39:44–15:39:55Z are the part I measured directly and they are from `zabz-yoga-1`.

---

## APPENDIX — every command behind a claim

`O` = `ssh secratary-ts` (office, read-only) · `C` = `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1`
· `Y` = this laptop. All readings 2026-10-11 15:38–15:45Z unless stated.

| claim | machine | command |
|---|---|---|
| office load at read time | O | `cut -d' ' -f1-3 /proc/loadavg` → `0.00 0.02 0.00` |
| full unit inventory, both boxes | O/C | `systemctl list-units --type=service --all --no-legend --plain` |
| enabled/static state, office | O | `for u in $(systemctl list-unit-files …); do systemctl is-enabled $u; done` |
| enablement of the outage units | O | `for u in phone-engine phone-gate mesh-broker …; do systemctl is-enabled $u; systemctl is-active $u; done` |
| the two phone units' full definitions | O | `systemctl cat phone-engine.service phone-gate.service` |
| office timers and their last/next fire | O | `systemctl list-timers --all --no-legend --plain` |
| phone client identity and the live failure | O | `grep -oE "client=[0-9.]+" /home/zabz/.dsh-phone/gate.log \| sort \| uniq -c`; `tail -12 /home/zabz/.dsh-phone/gate.log` |
| the engine's stop time | O | `journalctl -u phone-engine --since "2026-10-11 02:00" -o short-iso` → last `04:03:34 Deactivated successfully` |
| the phone's real door | O | `tailscale serve status` → `/ proxy http://127.0.0.1:3086` |
| office port owners and PIDs | O | `ss -lntp`; `ps -o pid,ppid,user,lstart,etime,args -p <pid>` |
| office tunnel ingress (incl. dialer :8899) | O | `cat /etc/cloudflared/config.yml` |
| nothing ever served :8899 | O | `ss -lntp \| grep 8899`; `ls -d /opt/dialer* /home/zabz/dialer*` |
| cron masked, 92 jobs preserved | O | `systemctl is-enabled cron` → `masked`; `ls -l /etc/systemd/system/cron.service` → `-> /dev/null`; `grep -vcE "^\s*(#\|$)" /home/zabz/cutover/crontab.before` → `92` |
| the runner's repo | O | `cat /opt/actions-runner/.runner` |
| the office broker answers | O | `curl -s http://127.0.0.1:3091/nodes` → 200; `?fresh=1` → `state: ok`, `latencyMs: 28` |
| cloud tailnet membership and name resolution | C | `which tailscale`; `tailscale status`; `getent hosts secratary.tail93e6e6.ts.net` → `100.84.72.88` |
| cloud has no serve config | C | `tailscale serve status` → `No serve config` |
| cloud has no :3086 / :3089 / :3091 | C | `ss -lntp`; `ss -lntH \| grep -E ":3086\|:3089\|:3091"` → empty |
| the redirector's target and its override | C | `curl -D- http://127.0.0.1:3087/phone` → `302 … zabz-yoga-1…`; `cat /etc/cloudflared/phone-redirector.env` |
| the decoy marker | C | `cat /var/lib/phone-redirector/engine-3087.log` → `marker only…` + `token=cloud-marker-not-a-credential` |
| redirector target logic | C | `sed -n '/^def tailnet_name/,/^def /p' /usr/local/bin/phone-redirector.py` |
| cloud broker unit+state | C | `systemctl show mesh-broker -p UnitFileState -p ActiveState -p ConditionResult` → `disabled / inactive / no` |
| cloud broker package present | C | `ls -la /opt/mesh-broker` (13:27Z; `bin`, `lib`, `nodes.json` 14,335 B) |
| dependency closure, both boxes | O/C | `bash -s < harness-config/scripts/mesh/145-closure-check.sh` — every path, `command -v` for 12 binaries, ExecStart-resolution for 19 units, timer journal tails |
| API/dashboard/redirect behaviour | C | `curl -w "code=%{http_code}" http://127.0.0.1:8002/health` → 200; `:3000/health` → 200; `:3087/phone` → 302 |
| the public doors | C | `curl https://ai.abletelsolutions.com/phone` → 302; `https://api.abletelsolutions.com/health` → 200 |
| tailnet probes are 403, not unreachable | C | `for n in zabz-tech zabz-yoga-1 secratary zabz-tech-linux lakewooechsmini; do curl -w "%{http_code}" https://$n.tail93e6e6.ts.net/mesh/health; done` → `403` ×5 |
| the dead-man is firing | C | `journalctl -u authority-deadman -n 3` → `ping http 200 … sent=yes verified=ok` |
| the offsite backup is verified | C | `cat /var/lib/authority-backup/last-run` → `database_verified=ok`, `gz_bytes=6278791492`, `remote_bytes=6278791492` |
| the archive is current | C | `transcript-archive-server.py --check` output shows arrivals 14:05–14:51Z; `manifest.sqlite` mtime 15:34 |
| the monitor cannot read R2 | O/C | `journalctl -u estate-monitor -n 3` on both → `NODATA … no boto3: No module named 'boto3'`; `python3 -c "import boto3"` on C → `1.40.72` |
| family chat was restored | C | `sqlite3 /opt/company/data/family_chat.db "select count(*) from messages;"` → **3155** (doc 135 §4.5 measured 1) |
| the authority's table count | C | `sqlite3 /root/authority.db "select count(*) from sqlite_master where type='table';"` → **231** |

**END OF 145.**

