# 129 — HANDOFF: the authority cutover to `secratary-cloud`, Stages 0–2 done, 3–6 ready to run

> **Supersedes nothing. Complements `128-HANDOFF-complete-the-cutover.md`, whose §5 stage order is
> still authoritative.** This file is what a session that ran out of context on 2026-10-11 needs:
> what is now DONE that 128 said was not, what was WRONG in 128, and the exact next command.

**Written** 2026-10-11 ~00:45Z from ZABZ-YOGA. **Journal: `L3454` (the token defect), `D3040` (the
subset decision), `H3404` (state of play).** Read 128 first, then this.

---

## 0. THE ONE-LINE STATE

The new box is **fully ready to be the authority except that it does not hold the database yet**, and
the office box is **still serving and still writing**. Nothing is pointing at the new box. The next
irreversible-ish step is the **freeze**, and it has not been started.

---

## 1. WHAT 128 SAID WAS OPEN, AND WHAT IT ACTUALLY WAS

### §4.1 — "the two tokens differ" — WRONG, and the truth is simpler and more dangerous

128 concluded the survivor's `CF_API_TOKEN` and the office's were different tokens. **They were the
same token.** The survivor's `/opt/company/.env` was **CRLF** (254 CR bytes). `grep -m1 '^CF_API_TOKEN='`
+ `cut -d= -f2-` therefore produced a **41-character** string whose last byte was `\r`, against the
office's **40**. Cloudflare answered *"not found in this account"* for the 41-char string — an
error that reads like an account or permission problem and is neither.

**FIXED**: `sed -i 's/\r$//' /opt/company/.env` on `lpt-survivor-01`, backup at
`/opt/company/.env.bak-crlf-20261011T001627Z`. That file is now LF, and **every value in it is
correct for the first time** — the CR was on all 254 lines.

**Lesson recorded as `L3454`.** The general rule: when a credential is rejected as *unknown* rather
than *forbidden*, compare its LENGTH against a copy that works before assuming it is a different
credential. Same token + `\r` is indistinguishable from a wrong-account token until you count.

### §4 "use the existing tool, do not hand-roll" — RIGHT, and the tool needed one thing

128 and plan 127 both say to promote through `company-promote.py`. Correct. **But it moves ALL FOUR
public hostnames in one act**, and MEASURED from the office box's `/etc/cloudflared/config.yml`,
those four are a path-based dispatcher onto four backends and **two of them cannot leave the office
box**:

| hostname | origin | moves? |
|---|---|---|
| `api.abletelsolutions.com` | `localhost:8002` company API | **YES** |
| `ai.abletelsolutions.com` | `localhost:3000` dashboard | **YES** |
| `ai.abletelsolutions.com` `^/phone` | `127.0.0.1:3087` phone redirector | **YES** (copied) |
| `dialer.abletelsolutions.com` | `127.0.0.1:8899` live-voice dialer | **NO — backend is office-bound** |
| `secretary-ssh.abletelsolutions.com` | `ssh://localhost:22` ssh escape hatch | **NO — must stay usable for rollback** |

A move-all points the last two at a tunnel with no ingress rules for them, and **Cloudflare answers
403** for a hostname with no ingress rule — the exact failure `company-dns-failover.py`'s own header
records from its round-4 test. So the subset is not a nicety; **moving `dialer.` before its backend
has moved is a certain outage of the dialer.**

**DONE**: two files in `harness-config/scripts/mesh/`, derived from the survivor's proven copies,
**default behaviour unchanged**:
- `company-dns-failover.py` — gained `--hostnames`, validated against the known four (a typo cannot
  point a hostname this tool was never written for at a new tunnel). Default: all four.
- `company-promote.py` — gained `--hostnames` (passed through) and `--seed-stamp ""`.

`--seed-stamp ""` skips the two seed checks, which exist because `lpt-survivor-01` was once seeded
from a development snapshot. `secratary-cloud` is not a recovered standby; it is the new primary
carrying the live database, so it has no seed stamp. **The skip announces itself in the output**,
because a check that disappears silently is how a guard becomes decoration, and it is only safe when
the operator has just shipped a compared copy of the live database — which Stages 4–5 do. **Never use
it for a failover onto a standby.** Both files were deployed to `secratary-ts:/home/zabz/cutover-tools/`
(`py_compile` OK), because that is where the Cloudflare credentials are.

### NEW — §5's "copy the database" has a path the handoff got wrong

`DATABASE_URL` is set on **neither** box. `app/config.py:942` defaults to `sqlite:///data/secretary.db`,
and `SettingsConfigDict(env_file=(".env", ".env.local"))` is resolved against the unit's
`WorkingDirectory=/opt/company`. **So the app opens `/opt/company/data/secretary.db`** — and that is
the only path the authority database may be installed at. The 14 GB stale copy 128 names at
`/root/authority.db` was **never the path the app reads**. `cutover-cloud.sh` now defaults to the
correct path.

### NEW — the application code on the two boxes is THREE DAYS APART

| | office (`secratary-ts`) | cloud (`secratary-cloud`) |
|---|---|---|
| commit | `ddf242a4` (2026-10-10) | `006cde5a` (2026-10-07) |
| branch | `hk/item642-gate-retry-after-20261010` | `master` |
| tracked files | 3126 | 3091 |
| dirty paths | **47** (19 under `app/services/`) | 11 |

**The office box's deployed truth is its WORKING TREE, not its commit.** A `git push` ships the
commit; a `git checkout master` ships a different commit. Either would change the application during
a database move. **DONE**: `sync-running-code.sh` rsyncs the running tree (`app/`, `scripts/`,
`requirements.txt`, `pytest.ini`, `web/`) to the cloud box. Verified on arrival: **318 `app/*.py`,
155 `scripts/*.py`, `app/main.py` 775,410 bytes, 239 files in `app/services`, 46 web app dirs.**

---

## 2. WHAT IS DONE AND VERIFIED (do not redo)

| # | done | evidence |
|---|---|---|
| 1 | `CF_API_TOKEN` defect fixed (CRLF) | token now lists all 6 tunnels; `L3454` |
| 2 | **New tunnel `personal-secretary-cloud` = `3e62916c-04ac-421b-b4a4-9af0852d8024`** | created via the API with `CF_ZERO_TRUST_TOKEN` |
| 3 | **`cloudflared` installed and RUNNING on the cloud box** | `2026.10.0`; **1 connector, 4 colos** (`iad17/iad05/iad02/iad20`) confirmed through the Cloudflare API — *this is the check that would have caught the 403* |
| 4 | Ingress on the cloud box = `ai./phone -> :3087`, `ai. -> :3000`, `api. -> :8002`, `http_status:404` | `/etc/cloudflared/config.yml`, `ingress validate` OK. **`dialer.` and `secretary-ssh.` have NO rule here, on purpose.** |
| 5 | **`/phone` redirector running on the cloud box** | `phone-redirector.service` active; loopback `GET /phone` → **302 → `https://secratary.tail93e6e6.ts.net/`** |
| 6 | **Node 20.20.2 + the dashboard built and running** | `secretary-dashboard.service` active; loopback `:3000` → **307** (the auth redirect, which is the correct pre-login answer) |
| 7 | Running application code synced | §1 above |
| 8 | `.env` on the cloud box **already carries the same 283 non-empty values** | `diff` of non-empty lines = 0; `comm` finds no key unique to either side. The provisioner reproduced the real file, not the example. |
| 9 | `secratary-cloud` can reach the office box | its own keypair is in the office's `authorized_keys`; `secretary-ssh.abletelsolutions.com` did not resolve for it, so the **office box still PUSHES** |
| 10 | Two new executor scripts, `bash -n` clean | `scripts/mesh/cutover-cloud.sh`, `scripts/mesh/prestage-cloud.sh`, `scripts/mesh/sync-running-code.sh` |

**Still true, unchanged:** `company-api` on the cloud box was `disabled`/`inactive` — **but it is now
STARTED-and-serving-its-own-loopback?** NO. Re-check it before the freeze (see §3 step 0). It must not
be a second writer.

---

## 3. THE NEXT COMMANDS, IN ORDER

### Step 0 — confirm no second writer exists on the cloud box (30 s)
```bash
ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 \
  'systemctl is-enabled company-api; systemctl is-active company-api'
```
**Must be `disabled` / `inactive`.** If `company-api` is active, stop it before the freeze.

### Step 1 — wait for the two transfers to finish (they were in flight at this writing)
```bash
ssh secratary-ts 'cat /home/zabz/prestage-data.log | tail -3; cat /home/zabz/stage1-snapshot.log'
ssh secratary-ts 'pgrep -af "prestage-cloud|stage1-snapshot" | head'
```
- `prestage-data.log` — `data/` minus the database, ~14 GB, `rsync --partial` (resumable). **It is
  already past 42 %.** If it died, re-run `bash /home/zabz/prestage-cloud.sh --stage data`.
- `stage1-snapshot.log` — a consistent `sqlite3 .backup` of the live database to
  `/home/zabz/cutover/office-warm.db`, taken **outside** the freeze so the dark window ships a delta
  rather than 22 GB. It must print `integrity_check: ok` and a `max(rowid)`.

### Step 2 — the freeze (THE DARK WINDOW STARTS; target ≈15 min now, ceiling 45)
```bash
bash scripts/mesh/cutover-cloud.sh --stage freeze --confirm
```
Success test is **`lsof` empty on the office database file, twice, one full cron period apart, with an
unchanged `stat`** — never a `systemctl` exit code. `cloudflared` and `tailscaled` stay UP.

### Step 3 — copy and verify
```bash
bash scripts/mesh/cutover-cloud.sh --stage copy --confirm
bash scripts/mesh/cutover-cloud.sh --stage verify
```
`verify` is read-only and compares bytes, page geometry, table list, row count, `max(rowid)` and the
FTS fingerprint of `MATCH 'the'`. **All must be equal** — the copy is UNCONVERTED, so unlike runbook
126 there is no expected page-count difference and no `diff_check`.

### Step 4 — switch
```bash
bash scripts/mesh/cutover-cloud.sh --stage switch --confirm
```
This installs the copy at `/opt/company/data/secretary.db`, removes any `-wal`/`-shm`, starts and
enables `company-api`, and probes loopback health. Then, **by hand, on the office box** (it holds the
credentials):
```bash
cd /home/zabz/cutover-tools
export CF_API_TOKEN=$(grep -m1 '^CF_API_TOKEN=' /home/zabz/personal-secretary-mvp/.env | cut -d= -f2-)
export CF_ZONE_ID=$(grep -m1 '^CF_ZONE_ID='         /home/zabz/personal-secretary-mvp/.env | cut -d= -f2-)
export CF_ACCOUNT_ID=$(grep -m1 '^CF_ACCOUNT_ID='   /home/zabz/personal-secretary-mvp/.env | cut -d= -f2-)
python3 company-promote.py --to 3e62916c-04ac-421b-b4a4-9af0852d8024 \
  --hostnames ai.abletelsolutions.com,api.abletelsolutions.com \
  --seed-stamp "" --apply
```
Confirm on that box that **`grep -c $'\r'` of the `.env` is 0** before trusting the token — that is
`L3454`, and this is the second box it applies to.

### Step 5 — post-switch
```bash
curl -s https://api.abletelsolutions.com/health
curl -s https://ai.abletelsolutions.com/health
ssh secratary-ts 'stat -c%s /home/zabz/personal-secretary-mvp/data/secretary.db'   # twice, 10 min apart
```
**The office size must be IDENTICAL across the two readings.** Re-check at +1 h, +24 h, +7 d.

---

## 4. ROLLBACK

| stopped at | do |
|---|---|
| freeze | `bash scripts/mesh/cutover-cloud.sh --stage rollback --confirm` (restores units, timers and the crontab, unmasking both) |
| copy/verify | nothing to undo; the office database was never written to |
| after DNS moved | `python3 company-dns-failover.py revert` on `secratary-ts` — it restores the saved previous target and refuses with no state file |
| anything | **the office database was never modified at any stage.** That is the design. |

**The office box is not to be deleted, wiped or "cleaned up" for at least a week.**

---

## 5. STILL OPEN, DELIBERATELY

- **`dialer.` and `secretary-ssh.` remain office-dependent** after this cutover. That is `D3040`, it
  is a smaller and more honest dependency than the API having one, and it is the next piece of work.
- **`secratary-cloud` is not on the tailnet.** It has no ssh alias on any node, is reachable only by
  public IP, and is not in the mesh's reach — so **no fan-out can land on it** and its `/phone`
  redirector works only because `PHONE_TAILNET` is set explicitly. Needs an auth key **with expiry
  disabled**. Desirable per 128 §8; **not blocking**.
- **The 14 GB stale `/root/authority.db`** on the cloud box is dead weight and should go — but it is
  a delete, so it waits for an explicit per-action yes.
- **`data/google_voice_profiles` is an actively-written Chromium profile** (54,271 files, newest write
  during the transfer). Its copy may need the Google Voice session re-established. Recorded, not
  worked around.
- `mesh-broker` and the placement failover (128 §8) are not installed on the cloud box.
- The `docs/mesh/` double-119 and the two cron jobs pointing at missing files (128 §8) are untouched.
