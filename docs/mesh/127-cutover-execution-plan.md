# 127 — Cutover execution plan: authority moves to `secratary-cloud`

**Written 2026-10-10 23:5xZ.** This is the EXECUTION plan, derived from
`126-authority-cutover-runbook.md` (the detailed runbook, written 2026-10-09) plus facts measured
tonight that the runbook did not have. Where this plan and 126 disagree, **this plan is newer** and
says which measurement decided it.

---

## 0. The measurements that set the schedule (all MEASURED tonight)

| fact | value | how |
|---|---|---|
| **office → Ashburn ship rate** | **39.7 MiB/s** | 1024 MiB of the real DB piped over ssh, timed: `25.73 s` |
| full 23.5 GB ship time | **≈ 10 minutes** | 23,500 ÷ 39.7 MiB/s |
| DB size, live | 23,519,150,080 B (23.5 GB) | `stat` on `secratary-ts` |
| DB growth | ~0.5 GB/day; ≈0.70 MB/min | snapshot sizes vs row counts |
| **RPO during the freeze** | **≈18 MB** deferred at a 25-min freeze | 25 min × 0.70 MB/min |
| new box free disk | **57 GB** (of 75 GB) | `df -h /` |
| new box already holds | `/root/authority.db`, 14,023,524,352 B — **the CONVERTED 13 GB DB from 2026-10-09** | `ls -la` |

**CONCLUSION: the freeze is ~25 minutes, not hours.** That is what makes this cutover easy, and it
came from one measurement the runbook explicitly said was missing.

---

## 1. THE SWITCH MECHANISM — resolved tonight, and it is a DNS edit

The company's public door is a Cloudflare tunnel, and **the hostnames are split across two different
backends**. Measured on `secratary-ts` (`/etc/cloudflared/config.yml`, tunnel `829bc0fb-…`):

| hostname | origin | must move to the new box? |
|---|---|---|
| `api.abletelsolutions.com` | `localhost:8002` — **the company API** | **YES** |
| `ai.abletelsolutions.com` | `localhost:3000` — the dashboard | **YES** |
| `ai.abletelsolutions.com` `^/phone` | `127.0.0.1:3087` — phone redirector | no |
| `secretary-ssh.abletelsolutions.com` | `ssh://localhost:22` | no |
| `dialer.abletelsolutions.com` | `127.0.0.1:8899` — dialer UI | no |

**WHY THE TUNNEL CANNOT SIMPLY BE COPIED.** Running the *same* tunnel id on both boxes makes
Cloudflare **load-balance one hostname across two different SQLite databases**. That is silent
divergence, and it is the single most dangerous mistake available here.

**THE SWITCH, therefore:**
1. Run a **second tunnel** on `secratary-cloud`, ingress `api. -> localhost:8002`,
   `ai. -> localhost:3000`.
2. Edit **only** the two DNS CNAMEs (`api.`, `ai.`) to point at the second tunnel.
   `dialer.`, `secretary-ssh.` and `/phone` deliberately stay on `829bc0fb` and the office box.
3. **ROLLBACK = point those two CNAMEs back at `829bc0fb-….cfargotunnel.com`.** Seconds, and the
   office database was never modified.

**Access exists** (names only, values never printed): `personal-secretary-mvp/.env` holds
`CF_API_TOKEN`, `CF_ZONE_ID`, `CF_ACCOUNT_ID`, `CLOUDFLARE_TUNNEL_NAME` (= `personal-secretary-ai`),
`CLOUDFLARE_TUNNEL_TOKEN`; and `/home/zabz/.cloudflared/cert.pem` exists, so a NEW tunnel can be
created without a browser login.

**Existing tunnels (names + ids, via the API):**

| name | id | status |
|---|---|---|
| `personal-secretary-ai` | `829bc0fb-30f9-4244-b2ea-14fbb61a2753` | healthy — the live one, office box |
| **`secretary-standby`** | `b69e2492-7e32-4a3b-9874-befb38ab7a5c` | **healthy — check whether this is already the intended target** |
| `home-services`, `homeassistant`, `personal-secretary-desktop-ssh`, `yocheved-ssh` | — | down |

---

## 2. THE SEQUENCING DECISION (new; 126 converted during the freeze — do not)

126's Stage 4 runs the FTS conversion inside the freeze. **The conversion measured 38 minutes**
(19:27→20:05 on 2026-10-09). Putting it in the freeze would take the window from ~25 min to ~63 min
for an optimisation that is **not required for correctness**.

**So: convert AFTER the switch, not during it.** The new box serves the unconverted 23.5 GB database
first; the conversion happens afterwards on idle NVMe with no freeze at all. This is strictly better
on every axis: shorter freeze, smaller RPO, and the conversion gets a machine with nothing else to do.

---

## 3. THE STAGES, in order

### Stage 0 — Pre-flight (read-only, no changes)
Prove: the office DB is intact and the API serves; the new box has ≥50 GB free and is reachable; the
tunnel/DNS facts above still hold; the ship rate is still ≥30 MiB/s. **If any fails, stop.**

### Stage 1 — Provision the new box **(RUNNING NOW, background workstream)**
packages, app tree, venv, `.env` from the template (no real secrets copied), systemd unit with the
uvicorn security flags preserved verbatim (`--proxy-headers --forwarded-allow-ips=127.0.0.1`),
fail2ban/ufw. **Blocker: the box has no Tailscale — it is reached by public IP. Not required for the
cutover, required for fleet reachability afterwards.**

### Stage 2 — Freeze (the clock starts)
Stop **every** writer, then **prove** it with `lsof` on the database file — not with a `systemctl`
exit code. Then wait one full cron period and re-check, because `secretary-startup` runs `*/5` and
two watchdogs run every 5 minutes and will restart a writer underneath a naive "stop the unit".

### Stage 3 — The delta copy (~10 min)
Consistent snapshot via `sqlite3 .backup` — **never** a raw `cp` of a live SQLite file — shipped
straight to the new box (`39.7 MiB/s`).

### Stage 4 — Verify BEFORE anything points at it
Compare, and require all to pass: byte count, `PRAGMA page_count`, table count, and the FTS search
fingerprint (`SELECT count(*) FROM dsh_session_events_fts WHERE dsh_session_events_fts MATCH 'the'`).
**A copy that has not been compared to its source is not a copy.**

### Stage 5 — Switch (seconds)
Start the API on the new box, confirm it answers **on its own loopback**, then edit the two DNS
CNAMEs. Then unfreeze the office box as a read-only spectator.

### Stage 6 — Post-switch verification (+1 h, +24 h, +7 d)
The API answers on the public hostname; the row count only moves on the NEW box; the office DB stops
changing. **A changed office row count means a writer survived the freeze — stop and investigate.**

### Stage 7 — The office box becomes the rollback anchor
**Frozen, never deleted, for at least a week.**

### Stage 8 — Then, and only then, the conversion
The 90-day archive-and-prune plus the external-content FTS conversion — on the new box, no freeze,
reusing the proven `fts-convert.sh` (which measured **21.4 GiB → 13.06 GiB, −39 %, fingerprints
identical**).

---

## 4. What is NOT yet true, stated so nobody assumes it

- The app is **not installed** on the new box as of this writing (workstream running).
- The new box has **no tailnet**.
- The second tunnel is **not yet created** and the DNS CNAMEs are **unchanged**.
- The authority is still the office box and still serving.
- **`secretary-standby` has not been investigated** — it is healthy, and it may already be the
  intended target for exactly this cutover. Check it BEFORE creating a third tunnel.

---

## 5. CORRECTION (2026-10-10 23:5xZ) — the failover machinery ALREADY EXISTS. Do not hand-roll §1.

While checking `secretary-standby`, I found that the estate already has a **complete, documented,
proven** failover system, built 2026-10-06, living on `lpt-survivor-01` (2.31.18.142, Hetzner CX33,
Falkenstein):

| file | what it is |
|---|---|
| `/opt/company/deploy/hosting-migration/scripts/company-dns-failover.py` | the MECHANISM: moves the four public hostnames between tunnels |
| `/opt/company/deploy/hosting-migration/scripts/company-promote.py` | the DECISION: pre-flight refusals, dry-run by default, `--apply` to act |
| `/opt/company/deploy/hosting-migration/scripts/survivor-bootstrap.sh` | turn a fresh host into the survivor |
| `/opt/company/docs/operations/resilience/M-standby-surface-and-failover-proof.md` | the proof, with the corrections it earned |

**`company-promote.py` refuses, in this order:** the target tunnel exists; it has an ACTIVE CONNECTOR;
the standby answers 200 with `"mode":"survivor"`; **the primary is NOT serving** (else two writers);
and no previous promotion is left unreverted. Exit `1` = refused, nothing changed. Exit `2` = promoted
but unhealthy, revert immediately. `DEFAULT_STANDBY_TUNNEL = b69e2492-7e32-4a3b-9874-befb38ab7a5c` —
the tunnel this plan found healthy. It carries `PRIMARY_HEALTH = https://ai.abletelsolutions.com/health`
and checks BOTH `ai.` and `api.` after a promotion.

**Refusal 4 is the two-writer hazard this plan's §1 derived independently. They already solved it,
in code, four days before this plan was written.**

### What this changes

- **§1's "run a second tunnel and edit two CNAMEs by hand" is superseded.** Use `company-promote.py`.
  A hand-rolled DNS edit has none of the five refusals, and the failure mode it invites — names moved
  to a tunnel with no connector — was measured on 2026-10-06 to return **403, not 200**.
- `secretary-standby` is **healthy with 4 active connectors**, created 2026-10-06T04:37Z, from a
  Hetzner IPv6. So a standby surface exists and is live.
- The new Ashburn box should therefore be provisioned as **a promotable target** (app + `.env` + a
  cloudflared connector on its own tunnel), and then promoted **through the existing script**, which
  will refuse if anything is wrong.
- The remaining question is a DESIGN one, not a mechanism one: does `secratary-cloud` become the new
  PRIMARY (and `lpt-survivor-01` stays the standby), or does it become the standby? Given it is the
  faster box and the intent is to stop depending on office power, **it should be the primary**, and
  the office box becomes the thing that no longer matters.

**This is the same class of mistake as the Hetzner Storage Box: proposing to build something the
estate already had.** The rule that would have caught both: before designing a mechanism, search the
estate for the mechanism.
