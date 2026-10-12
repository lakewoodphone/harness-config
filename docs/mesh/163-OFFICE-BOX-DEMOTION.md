# 163 — DEMOTING THE FROZEN OFFICE BOX `secratary`: guard + rule, one connector, masked writers

**Run from:** `zabz-tech` (Windows workstation), over ssh to `secratary-ts` and to the cloud.
**Started:** 2026-10-11T22:26Z.  **Written as the work happens** (estate defect: ssh does not
reliably exit, so a final message can be lost).

## 0. Why this file is numbered 163

`/root/out/migration-review/` already held 131–162. Next free number is 163.

## 1. Access — established, not re-litigated

* `ssh secratary-ts` lands as `zabz`; `sudo -n true` → **SUDO_OK** (passwordless sudo works).
  Every privileged operation below uses `sudo -n`.
* Cloud reached at `root@178.156.194.1` with `~/.ssh/id_ed25519_hetzner`.

### The ssh defect, measured again, and the workaround

Both hosts printed their output and then **hung**; the first two calls died at the harness
timeout after printing `secratary` / `secratary-cloud`. So the harness for this job pipes the
remote script to `bash -s` on stdin, appends `echo __DSH_DONE__` to it, waits for that sentinel
on stdout, then kills the ssh client. **`COMPLETE: True` — not the exit code — is the completion
signal used throughout this artifact.** Every command below was confirmed by that sentinel.

## 2. FIRST FINDING — the frozen database is NOT at the briefed path

The brief says to verify `/home/zabz/.lpt-verify/office-frozen.db`. **That path does not exist.**
`/home/zabz/.lpt-verify/` exists and contains the Sep-15 audit tooling plus `audit.log`,
`four-surface.json`, `stripe-watch.*` — **no `office-frozen.db`**.

The 23,622,823,936-byte file with the briefed mtime is at:

```
/home/zabz/cutover/office-frozen.db          23622823936  2026-10-11 04:27
/home/zabz/cutover/office-frozen.db-shm         32768     2026-10-11 20:42
/home/zabz/cutover/office-frozen.db-wal             0     2026-10-11 20:42
```

This is corroborated by the box's own freeze records, which name the same file:
`/home/zabz/cutover/FROZEN` reads
`frozen 2026-10-11T04:46:27Z lsof=0 size=23622823936 snapshot=23622823936`, and
`snapshot3.log` records `sqlite3 .backup`, `integrity_check: ok`, `max rowid: 1856458`,
`page geometry: 4096x5767291`, `snapshot bytes: 23622823936 source bytes: 23622823936 SIZES EQUAL`.

**I verified the real path and touched nothing.** `-wal` is 0 bytes and the db mtime is 04:27 —
the 20:42 stamps on `-shm`/`-wal` are from the 19:04Z incident's aftermath, not from a committed
write. The briefed path is recorded here as a discrepancy for the record; it is NOT created.

## 3. The four writer units — identified, not guessed

Evidence, in order:

1. `/home/zabz/cutover/finish-freeze.log` — the freeze script's own "stop every writer unit"
   section names: `secretary-api`, `dialpad-sms-ws`, `secretary-dashboard`, `phone-engine`,
   and `mesh-broker`.
2. `/home/zabz/MISSION-READ-FIRST.md` §3 — the rule the machine carries names the same four as
   the units the 19:04Z agent wrongly started: `secretary-api`, `dialpad-sms-ws`,
   `secretary-dashboard`, `phone-engine`.
3. `docs/mesh/126-authority-cutover-runbook.md` on the cloud (the brief is **not** on the office
   box — confirmed, consistent with MISSION-READ-FIRST §6) states the writer row explicitly:

   > `| writers | secretary-api.service (uvicorn 0.0.0.0:8002), dialpad-sms-ws.service,
   > secretary-dashboard.service (:3000), phone-engine.service (DSH engine 127.0.0.1:3089) |`

   and its own freeze stage masks only two and stops two:
   `sudo systemctl mask --now secretary-api.service dialpad-sms-ws.service; sudo systemctl stop
   secretary-dashboard.service phone-engine.service`

That last line is the whole defect: the runbook named four writers and **masked two**. Measured
on the box, all four were still `disabled` but **not masked**, so a plain `systemctl start` works.

`mesh-broker` is **not** a database writer (it is a broker) and is **not** one of the four; it is
left exactly as found and is reported, not changed.

## 4. BEFORE state, measured on the office box

| unit | active | enabled |
|---|---|---|
| `cloudflared` | **active** | **enabled** |
| `secretary-api` | inactive | disabled |
| `dialpad-sms-ws` | inactive | disabled |
| `secretary-dashboard` | inactive | disabled |
| `phone-engine` | inactive | disabled |
| `mesh-broker` | inactive | disabled |
| `cron` / `cron.socket` | inactive | **masked** (deliberate — untouched) |
| `secretary-api-watchdog.timer` | inactive | disabled |

`masked=0` for all four writers. Nothing listens on :8002 or :3000 (only `tailscaled` on :443).
Cloud side, to be re-checked after the change: `cloudflared` **active + enabled**.

## 5. Source files — provenance proven byte-for-byte

The three files delivered are the versions already verified on other machines:

```
sha256 77df75b7b1ddeb32248e37147479ca6e660eb9334ada7a22b59e52d389a6bb40  scripts/mesh/guard-service-state.sh
sha256 1891d96e528b29135c3d294eabcab2a7ec14f849eeecd92d875977171e0e5ed3  settings/machines/host-posture.tsv
sha256 dba00cd3cbf8c6f710c71387384790db870c82100692fc68de265f4dca0d0f2c  tests/test_guard_service_state.sh
```

The same three hashes were measured on `/root/code/harness-config` (the cloud) and its
`bash tests/test_guard_service_state.sh` returned **35 passed, 0 failed**. So the copies being
carried to the office box are that revision, not a stale one.

The office box's checkout has **none** of the three files and **no `docs/mesh/131` or `142`**.
Its `AGENTS.md` ends at §4: it has **no `## 5.` at all** and none of the rule's marker strings.

## 6. Delivered: the guard + the rule, by direct copy (step 1) — DONE

Stamp `20261011T223203Z`. Written on the office box, into its **existing diverged checkout** at
`/home/zabz/code/harness-config` (no `git pull`, no `rebase`, no `git reset` — the divergence was
left exactly as found). All three source files were **new** to the box (it had none of them):

| what | written where | mode | sha256 after write |
|---|---|---|---|
| guard | `/home/zabz/code/harness-config/scripts/mesh/guard-service-state.sh` | 0755 | `77df75b7…a6bb40` |
| designation | `/home/zabz/code/harness-config/settings/machines/host-posture.tsv` | 0644 | `1891d96e…0e5ed3` |
| regression test | `/home/zabz/code/harness-config/tests/test_guard_service_state.sh` | 0755 | `dba00cd3…0d0f2c` |
| the rule (§5) | appended to `/home/zabz/code/harness-config/AGENTS.md` | 0644 | (file now 11371 bytes, was 7008) |

Every installed hash **equals** the hash of the same file on the cloud, which is the copy that
returns 35 passed / 0 failed. The box's `AGENTS.md` had **no `## 5.` at all** (it ended at §4), so
section 5 was appended verbatim from the same revision — a guard without its rule gives a machine
enforcement it cannot read.

### Backups taken (named for what they were)

* `/home/zabz/code/harness-config/AGENTS.md.before-anchor-demotion-20261011T223203Z`
  — the only pre-existing file of the four; the other three were new, so there was nothing to back up.

### Why direct copy and not scp

`scp` rides the same ssh client that does not exit on this estate. Each file was carried as a
base64 heredoc inside one `bash -s` script, so the whole delivery is a single bounded write with
no port to hang on.

## 7. The guard's exit codes ON THIS BOX (step 1) — proven, not asserted

`cd /home/zabz/code/harness-config && bash scripts/mesh/guard-service-state.sh …`

| command | exit | result |
|---|---|---|
| `--host secratary --op unmask` | **2** | REFUSED — FROZEN; prints WHAT IT IS FOR / WHO DECIDED / SINCE / designation file |
| `--host secratary-ts --op start` | **2** | REFUSED — FROZEN |
| `--host secratary-cloud --op restart` | **0** | ALLOW — WRITABLE, THE AUTHORITY, `/root/authority.db` |
| `--host 178.156.194.1 --op restart` | **0** | ALLOW — WRITABLE |
| `--host some-new-box --op restart` | **4** | REFUSED — undesignated; "NOT permission" |
| `--list` | 0 | 21 designations read from the installed `host-posture.tsv` |

The designation file it resolved to is the one just installed:
`/home/zabz/code/harness-config/settings/machines/host-posture.tsv`.

**Full regression test on the office box: `35 passed, 0 failed` (rc=0).**

So the office box is now a fourth machine carrying the working guard and the rule.

## 8. Step 2 — ONE connector. DONE and proven end to end

The office box's `cloudflared` was **active + enabled**, and its `config.yml` named tunnel
**`829bc0fb-30f9-4244-b2ea-14fbb61a2753`** — i.e. exactly the `"previous"` tunnel recorded in
`/home/zabz/cutover/failover-state.json`, whose `"target"` is `3e62916c-…` (the cloud's).

```
sudo -n systemctl stop cloudflared      -> STOP_RC=0
sudo -n systemctl disable cloudflared   -> Removed '/etc/systemd/system/multi-user.target.wants/cloudflared.service'; DISABLE_RC=0
```

| | before | after |
|---|---|---|
| office `cloudflared` active | `active` | **`inactive`** (rc=3), `SubState=dead` |
| office `cloudflared` enabled | `enabled` | **`disabled`** (rc=1), `UnitFileState=disabled` |
| office cloudflared process | pid 1356 | **none** |

**Cloud side verified afterwards — unchanged and still serving:**

* `cloudflared` `ActiveState=active` `SubState=running` `UnitFileState=enabled`.
* Tunnel `3e62916c-04ac-421b-b4a4-9af0852d8024`; hostnames `ai.` and `api.abletelsolutions.com`.
* **End-to-end from the cloud: `curl https://api.abletelsolutions.com/health` → `http_code=200`
  in 0.157 s**, body `{"ok":true,...,"database":{"ok":true}}`.

So the public hostname is now served by **exactly one** connector — the runbook's "never two
cloudflare connectors" is now a fact, not a rule.

## 9. Step 3 — the four writers MASKED. DONE and proven

### The obstacle (worth recording — the runbook's own command cannot have worked)

`sudo systemctl mask secretary-api.service …` **failed**:

```
Failed to mask unit: File '/etc/systemd/system/secretary-api.service' already exists
MASK_RC=1
```

`mask` must place its `/dev/null` symlink at `/etc/systemd/system/<unit>`, and these four units
live there as **real files** — unlike `cron.service`, whose file is in `/usr/lib/systemd/system`,
which is why `cron` masks cleanly. Measured: **none** of the four exists in `/usr/lib/systemd/system`.
So the runbook's `mask --now secretary-api dialpad-sms-ws` (Stage 4) could not have masked
anything either; that is consistent with the measured before-state — all four `disabled`,
**not masked**.

### The correction: back the unit file up under a name that says what it was, then mask

```
renamed secretary-api.service       -> secretary-api.service.before-anchor-demotion-20261011T223320Z
renamed dialpad-sms-ws.service      -> dialpad-sms-ws.service.before-anchor-demotion-20261011T223320Z
renamed secretary-dashboard.service -> secretary-dashboard.service.before-anchor-demotion-20261011T223320Z
renamed phone-engine.service        -> phone-engine.service.before-anchor-demotion-20261011T223320Z
Created symlink … -> /dev/null      (mask_rc=0 for each of the four)
sudo -n systemctl daemon-reload     -> reload_rc=0
```

### Verified

| unit | active before | enabled before | active after | enabled after |
|---|---|---|---|---|
| `secretary-api` | inactive | disabled | inactive | **masked** |
| `dialpad-sms-ws` | inactive | disabled | inactive | **masked** |
| `secretary-dashboard` | inactive | disabled | inactive | **masked** |
| `phone-engine` | inactive | disabled | inactive | **masked** |
| `mesh-broker` | inactive | disabled | inactive | disabled (left as found) |
| `cron` / `cron.socket` | inactive | masked | inactive | masked (**untouched**) |

Not asserted — measured. A start was attempted **only after all four reported `masked`**:

```
secretary-api        start_rc=1  Failed to start secretary-api.service: Unit secretary-api.service is masked.
dialpad-sms-ws       start_rc=1  Failed to start dialpad-sms-ws.service: Unit dialpad-sms-ws.service is masked.
secretary-dashboard  start_rc=1  Failed to start secretary-dashboard.service: Unit … is masked.
phone-engine         start_rc=1  Failed to start phone-engine.service: Unit phone-engine.service is masked.
```
and none is running. Nothing listens on :8002, :3000 or :3089.

## 10. Step 4 — the frozen database is untouched

**The briefed path is wrong and was NOT created.** `/home/zabz/.lpt-verify/office-frozen.db` does
not exist (`.lpt-verify/` holds only the Sep-15 audit tooling). The briefed artifact — same size,
same mtime — is **`/home/zabz/cutover/office-frozen.db`**, corroborated by `cutover/FROZEN`.

| | before all changes | after all changes |
|---|---|---|
| size | `23622823936` | `23622823936` |
| mtime | `2026-10-11 04:27:31.355878968 +0000` | **identical** |
| inode / mtime_epoch / ctime_epoch | `8694592 / 1791692851 / 1791692851` | **identical** |
| open holders (`lsof`) | 0 | **0** |
| `-wal` / `-shm` | `0` / `32768` @ 20:42 (incident, pre-existing) | unchanged |

Never deleted, never overwritten, never opened read-write. **No checksum was taken**: reading
23.6 GB is precisely the multi-second disk work that stalls this box's sshd. Identity is proven by
size + mtime + inode + ctime instead — all cheap.

## 11. RESIDUAL FINDING — a fifth writer surface the masking does NOT close

Measured while finishing: `/home/zabz/personal-secretary-mvp/data/secretary.db` — the office box's
**original** company database, a *different file* from the frozen snapshot — has size
`23691915264` and mtime **`2026-10-11 22:33:19Z`**, inside this session's window. It is stable
across 4 samples over 60 s, has no `-wal`/`-shm`/`-journal`, and **no holder** at any sample.

Nothing scheduled explains it: `cron` and `cron.socket` are inactive+masked, no cron process exists,
no docker, and no timer fires at that instant. What does exist is a **live, resident, non-unit
process pointed straight at that database**:

```
373715  sshd-session: zabz [priv]                  started 20:53:20
 373762 sshd-session: zabz@notty                   (from 100.85.153.96, tailnet)
  373763 /home/zabz/personal-secretary-mvp/.venv/bin/python scripts/ps_mcp_server.py
```

`ps_mcp_server.py` sets `DB_PATH = ROOT / "data" / "secretary.db"` and its own comment records
that on **this** host one `ps_mcp_server` PID held **151 open handles** on that database. It was
started 6000 s before the observed write (20:53:20 → 22:33:19) — **recorded as correlation, not
as proof**, and I did not trace it further because that means load on a box I have been told to
keep quiet.

**I did not kill it.** It is not one of the four writer units, it is another machine's live inbound
ssh session, and stopping it is a decision, not a command I hold — which is this migration's own
rule. `mask` closes the four *units*; it does not close an arbitrary process. The gap is real and
is reported, not papered over. The command that would close it, for whoever decides:
`sudo -n kill 373763` (and it will not come back unless something re-launches it).

## 12. REVERSE COMMAND for every change made

**1) The four files** (three were new; only `AGENTS.md` had a predecessor):

```
rm -f /home/zabz/code/harness-config/scripts/mesh/guard-service-state.sh \
      /home/zabz/code/harness-config/settings/machines/host-posture.tsv \
      /home/zabz/code/harness-config/tests/test_guard_service_state.sh
mv /home/zabz/code/harness-config/AGENTS.md.before-anchor-demotion-20261011T223203Z \
   /home/zabz/code/harness-config/AGENTS.md
```

**2) `cloudflared`** (this restores the SECOND connector — do not run it unless you mean to):

```
sudo -n systemctl enable cloudflared && sudo -n systemctl start cloudflared
```

**3) The four writer units** — `unmask` alone is NOT enough, because mask replaced a real unit
file; the file must come back too. This restores them exactly as found: **present and disabled,
not started**:

```
sudo -n systemctl unmask secretary-api.service dialpad-sms-ws.service \
                       secretary-dashboard.service phone-engine.service && \
sudo -n mv /etc/systemd/system/secretary-api.service.before-anchor-demotion-20261011T223320Z \
           /etc/systemd/system/secretary-api.service && \
sudo -n mv /etc/systemd/system/dialpad-sms-ws.service.before-anchor-demotion-20261011T223320Z \
           /etc/systemd/system/dialpad-sms-ws.service && \
sudo -n mv /etc/systemd/system/secretary-dashboard.service.before-anchor-demotion-20261011T223320Z \
           /etc/systemd/system/secretary-dashboard.service && \
sudo -n mv /etc/systemd/system/phone-engine.service.before-anchor-demotion-20261011T223320Z \
           /etc/systemd/system/phone-engine.service && \
sudo -n systemctl daemon-reload
```

Nothing else on the box was started, enabled, unmasked or masked. `cron`, `cron.socket` and
`mesh-broker` are exactly as found. No database, `-wal`, `-shm` or backup was deleted or
overwritten. The diverged checkout was neither pulled, rebased nor reset.
