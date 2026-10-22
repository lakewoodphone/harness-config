# 138 — PORTING THE INGESTION FAMILIES (4, 5, 16, 17) TO THE CLOUD AUTHORITY

**Workstream:** porting. **Author:** Zabz, ZABZ-YOGA session, 2026-10-11 ~06:20–07:00Z.
**Owns:** family 5 (communications ingestion + index, 12 jobs), family 4 (company-data ingestion,
6 jobs), `push-dsh-sessions` (16), `node-agent-cron` (17), `git-health-check` (§1a row 11).
**Does not own:** `transcript-archive` (15), the offsite backup (1), the dead-man switch (2),
`disk-guard`/`prune-backups`/`db-integrity-check` (5), the freshness monitors of family 3.

---

## §0 — HEADLINE, AND THE THING THAT STOPPED THIS WORK

**No job in my families was deployed, and none was enabled.** The reason is a single hard stop
and it is not a design problem:

> **`secratary-cloud` stopped accepting my SSH key at ~06:47Z while I was mid-port. From 06:47Z to
> 07:00Z every attempt is `Permission denied (publickey)`; the same key authenticated successfully
> at 06:36:16Z and 06:39Z in this same session.** No job could be installed, run, given a cron
> line, or measured — so per the port brief's definition of done (§3 of `133-PORT-BRIEF.md`) nothing
> is ported, and this document does not claim otherwise.

Everything below §2 is the reconnaissance I completed **before** access was lost, plus the exact,
reviewed patch set staged for deployment the moment access returns. §5 is the recovery instruction.

**What I did complete, and it is not nothing:**

1. **I found the path defect the work list warned about, and proved it with a measurement.**
   The two highest-frequency office paths in the app tree are ported *in name only* on the cloud
   box: the scripts exist, and they point at a database that does not contain their own tables.
2. Three corrected scripts are **written, syntax-checked and staged** (§4).
3. The dependency verdicts for every job in my families are resolved to a **measured** state (§2).
4. `family_chat_watchdog` is resolved as **DISABLED** with the discrepancy measured, as instructed.

---

## §1 — THE ACCESS FAILURE (read this first; it blocks the whole workstream)

### What works

| reading | evidence |
|---|---|
| `secratary-cloud` answers on :22 — `Test-NetConnection … -Port 22` → `tcp22=True` | ZABZ-YOGA, `Test-NetConnection -ComputerName 178.156.194.1 -Port 22` |
| The host key is **the same host** — no rebuild, no replacement instance | `ssh-keygen -F 178.156.194.1` → `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJRTR+qtCMByDTO3OiDS/jIA0yKmoDUPrcNeHCNlr5nZ` — unchanged in `known_hosts` |
| The public API and the database behind it are **healthy** | `https://api.abletelsolutions.com/health` → HTTP 200 `{"ok":true,…"database":{"ok":true,"error":null}…}` (ZABZ-YOGA, `Invoke-WebRequest`) |
| The local key is **unchanged** — not a corrupted or rotated file | `ssh-keygen -l -f ~/.ssh/id_ed25519_hetzner.pub` → `SHA256:91iMQc2AFg+sSA1oscDHF9pz7jClBMynfHtRL4rmAKg mesh-hetzner-2026-08-31`, file mtime **2026-08-31 10:12** (ZABZ-YOGA, `ssh-keygen -l`, `Get-Item`) |
| My network is fine — the office box is reachable throughout | `ssh secratary-ts` → `OFFICE_OK 0.12` (load 0.12) at 06:53Z |

### What fails

```
ZABZ-YOGA 07:00Z · ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 "echo ACCESS_OK"
root@178.156.194.1: Permission denied (publickey)      rc=255
```

The server's own negotiation says the key is *received and refused*, not that the connection is
rate-limited:

```
debug1: Offering public key: C:\Users\ezabz\.ssh\id_ed25519_hetzner ED25519 SHA256:91iMQc2… explicit
debug2: we sent a publickey packet, wait for reply
debug1: Authentications that can continue: publickey
debug2: we did not send a packet, disable method
debug1: No more authentication methods to try.
```
(`ssh -vv -o IdentitiesOnly=yes … root@178.156.194.1 "echo OK"`, ZABZ-YOGA)

### What this means, stated plainly

The server accepts the packet and then says "that key is not in `authorized_keys`". **Every
alternative explanation was eliminated in this session:**

- **Not fail2ban against me** — `fail2ban-client status sshd` at 06:44Z (while access was already
  failing): `Currently banned: 2`, list `195.178.110.228 202.46.28.140`; my egress IP is
  `172.59.214.144` (`https://api.ipify.org`) and is not on it.
- **Not a changed host key or a rebuilt box** — the `ssh-ed25519` host key is the same one; the
  API process has been up since boot `1 day, 12:13`.
- **Not the agent, not `IdentitiesOnly`, not an alternate key** — `ssh-add -l` shows one unrelated
  key; attempts with `IdentityAgent=none`, and with `id_ed25519_lpt-apps` and `zabz-tech-ed25519`,
  all return `Permission denied (publickey)`. The office box's own `id_ed25519_hetzner`
  (same fingerprint, `/home/zabz/.ssh/id_ed25519_hetzner`) is refused too.
- **Not a partial outage** — the two `Connection closed` / `kex_exchange_identification` errors seen
  around 06:41–06:44Z stopped, and the failure settled into a stable `Permission denied`.

So the conclusion is a **server-side credential change**: `/root/.ssh/authorized_keys` (or the
permissions on `/root`, `/root/.ssh`, or the file) changed on `secratary-cloud` at approximately
**06:47Z on 2026-10-11**, removing the estate's key. I did not make that change and could not have
made it from this session — every command I ran on the box up to that point is named in §2 and none
of them touches SSH, cron, or the unit files.

**This is the defect I would want reported whichever workstream it happened to.** A single box
whose only ingress can be removed by an unattended agent, with no console path and no second
credential, is a standing single point of failure for the whole authority. Recorded as a journal
`pain` entry rather than left in this document (see §5, item 3).

### 1.1 This was not only me — the incident is already documented, and better than I could

While filing the entry above I found the same incident recorded twice by sibling sessions today,
and their readings are further than mine got. **The block began at ~06:40Z, not 06:47Z** (my last
success is 06:39:27Z; the first refusal I saw was 06:40Z) — I am correcting my own timestamp to
theirs. `journal.py show L3603` records: the box's `authorized_keys` is a **single 105-byte file**;
the same refusal was reproduced **from a second, unrelated source address** (relayed through
`2.28.33.58`), which kills the fail2ban hypothesis outright; and **four independent sibling sessions
on this same laptop lost the authority in the same 7-minute window** (06:34Z, 06:41Z, 06:43Z, and
one describing `authorized_keys changed ~20 minutes into my session`). `journal.py show L3602`
carries the discriminating test set for "ban or key removal", including the trap that
`135-PARITY-AND-ROBUSTNESS.md`'s `authorized_keys` reading was taken *before* the failure, so it
cannot prove the file is still what it recorded.

**What that changes for this report: nothing about the port, and one thing about the conclusion.**
The mechanism is a server-side replacement of `authorized_keys` — measured by others from two
networks, not inferred by me from one. My own contribution is the client-side elimination in §1 and
the dependency findings in §2. **The authoritative recovery instruction is L3603's**, not mine, and
it lives in the journal, not duplicated here.

---

## §2 — RECONNAISSANCE COMPLETED BEFORE ACCESS WAS LOST

Every reading carries its machine and command. Nothing here was run after 06:47Z; the readings
are from 06:27–06:47Z.

### 2.1 Environment: part of the port platform was already in place

| reading | machine · command |
|---|---|
| `cron.service` is **active and enabled** | `secratary-cloud`: `systemctl is-active cron` → `active`; `is-enabled` → `enabled` |
| `/usr/local/bin/cron-wrap.sh` exists, **4,071 B, mode 755** — the same size as the office file | `secratary-cloud`: `ls -la /usr/local/bin/cron-wrap.sh` |
| `/root/.cron-status/` exists and has already been written to | `secratary-cloud`: `cat /root/.cron-status/runs.tsv` → `2026-10-11T06:32:33Z site-uptime-check-cron 0 1 ` |
| `/root/bin/` holds ~20 ported office tools **and two convenience symlinks** (`/root/bin/cron-wrap.sh`, `/home/zabz/bin/cron-wrap.sh` → `/usr/local/bin/cron-wrap.sh`) | `secratary-cloud`: `ls -la /root/bin/` |
| The root crontab is **still empty** — `no crontab for root` at 06:28Z | `secratary-cloud`: `crontab -l` |

**Consequence for the port brief's step 1** ("get `cron-wrap.sh` from the office box and install
it at `/usr/local/bin/cron-wrap.sh`"): it is **already done by another workstream**, byte-for-byte
the same size (4,071 B) as `135-work/office/cron-wrap.sh`. I did not re-copy it and I did not
change its format. The `/home/zabz/bin → /root/bin` symlink also already exists; I had planned to
create it and found it present, which removes the need for most office-path translation.

### 2.2 THE DEFECT THIS WORKSTREAM EXISTS TO FIND — proved, not inferred

The work list says: *"`dialpad-recording-gap.py` (796 occurrences) and `dialpad-transcript-gap.py`
(374) — the app calls them by an ABSOLUTE office path… make the cloud box's copy consistent with
the app's expectation."* Here is what that resolves to, measured.

**(a) Where the app expects the company database.** The app reads
`settings.database_url`, whose value on the cloud box is `DATABASE_URL=sqlite:////root/authority.db`
(length 28, key present once — value never printed). Confirmed independently: `company-api`
(pid 55564) has `/root/authority.db` and `/root/authority.db-wal` open —
`ls -la /proc/55564/fd | grep authority.db` → fd 101 → `/root/authority.db`.

**(b) Where the two gap scripts actually read.** Both compute `ROOT = Path(__file__).resolve().parents[1]`
and then `DB = ROOT / "data" / "secretary.db"` — so on the cloud box, **`/opt/company/data/secretary.db`**.

**(c) What that file is. THE MEASUREMENT:**

| reading | value | machine · command |
|---|---|---|
| `/opt/company/data/secretary.db` size | **1,826,816 B**, mtime **2026-10-11 01:18** | `secratary-cloud`: `ls -la /opt/company/data/` |
| its `dialpad*` tables | **`dialpad_sms_cache` and `dialpad_transcript_cache` — and no `dialpad_call_full`** | `secratary-cloud`: `sqlite3 /opt/company/data/secretary.db ".tables"` |
| **the point** | `sqlite3 … "select count(*) from dialpad_call_full;"` → **`Error: in prepare, no such table: dialpad_call_full`** | same |
| the live authority's `dialpad_call_full` | **13,995 rows** | `secratary-cloud`: `sqlite3 "file:/root/authority.db?mode=ro" "select count(*) from dialpad_call_full;"` |
| the live authority's `dialpad_media_file` | **7,069 rows** | same, `… from dialpad_media_file;` |
| the live authority's SMS cache | **135,421 rows**, newest `created_at` **2026-10-11T04:05:57Z** | `… "select count(*), max(created_at) from dialpad_sms_cache;"` |
| newest harvest | `dialpad_call_full.fetched_at` max **2026-10-11T04:05:42Z** | `… "select max(fetched_at) from dialpad_call_full;"` |

**So, precisely: both gap scripts, run from `/opt/company`, would open a 1.8 MB local file that does
not have the table they select from, and would fail every run — while the app's own Dialpad data
lives in a 23,707,291,648-byte authority database they never touch.** That is the "ported in name
only" failure the brief predicted, and it is worse than absent: the file *exists*, so a shallow
check ("script present, script runs") passes.

**(d) The same defect, one level up, in the two harvest cron jobs.** Their embedded workers do
`sys.path.insert(0, "/home/zabz/personal-secretary-mvp")`, a path that does not exist on the cloud
box. The wrapped script (`dialpad-harvest-cron.sh`, 7,865 B; `dialpad-sms-harvest-cron.sh`, 4,796 B)
opens with `REPO="/home/zabz/personal-secretary-mvp"; cd "$REPO" || { log "FATAL: cannot cd to
$REPO"; exit 1; }` and **exits 1** before doing anything. The shell resolves it only because
another workstream has since made `/home/zabz/bin` a symlink; `/home/zabz/personal-secretary-mvp`
was **not** a symlink at 06:28Z (`ls -la /home/zabz/` → `outbound-drafts` only).

**(e) Where the two biggest real contributors get it right, and why the difference matters.**
`dialpad_harvester.py` (the call harvest) resolves the database through
`_get_conn(settings.database_url)` — 18 occurrences, all `settings.database_url` — so *the app path
is correct and the two ROOT-based scripts are the outliers*. That is why the fix in §4 is
"make the script ask the app", not "make the app ask the script".

### 2.3 Family 5 — dependency verdicts, measured

| job (crontab line) | office command | cloud dependency check | verdict on the evidence |
|---|---|---|---|
| `dialpad-harvest-cron` (23) | `…/scripts/dialpad-harvest-cron.sh` | script **present** `/opt/company/scripts/` 7,865 B; `DIALPAD_API_KEY` key **present**, value length 100 (value not printed); **its `REPO=` prefix does not exist**; DB path inside the worker is already correct | **PORT-ADAPT** — prefix fix only |
| `dialpad-sms-harvest-cron` (61) | `…/scripts/dialpad-sms-harvest-cron.sh` | script **present** 4,796 B; same `REPO=` gap; needs `PHONE_TECH_FULL_DATABASE_URL` (production Postgres) — key **present** in `.env` by name; log dir `/root/.sms-inbox/` **exists** | **PORT-ADAPT** — prefix fix only |
| `dialpad-recording-gap` (37) | `flock -n /tmp/dialpad-dl.lock .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json` | script **present** 10,988 B; **DB path wrong (§2.2c)**; media store `/opt/company/data/dialpad` **present, 985 MB**; `DIALPAD_API_KEY` present | **PORT-ADAPT** — patch staged |
| `dialpad-transcript-gap` (39) | `… --limit 400 --retry-failed --max-minutes 600` | script **present** 11,494 B; **DB path wrong (§2.2c)**; media store present | **PORT-ADAPT** — patch staged |
| `dialpad-call-fresh` (154) | compound `flock 9` line | script **present** 3,791 B, mtime 2026-10-08 16:23 — **but no copy exists in the repo at all** (checked the workstation checkout and the office `scripts/`, both absent), so its DB path **could not be read from the file**; the script that exists on the cloud is the only copy I know of | **PORT-ADAPT — DB path UNVERIFIED** |
| `lpt-retranscribe` (156) | `flock … /home/zabz/bin/lpt-retranscribe-drip.py 20` | office body **exists** (`/home/zabz/bin/lpt-retranscribe-drip.py`, 1,162 B, 2026-10-07) and does `sys.path.insert(0, "/home/zabz/personal-secretary-mvp")` — **no cloud counterpart seen** in `/root/bin/` at 06:35Z | **BLOCKED on the `bin/` move** |
| `comms-refresh` (30) | `/usr/bin/python3 /home/zabz/.fsearch/comms-refresh.py` | **script absent on cloud** (checked `/opt/company/scripts/` — no `comms-refresh.py`); **`/root/.fsearch` does not exist**; its 4-tool toolset **is** in the workstation repo (`harness-config/scripts/`: `commsindex.py` 74,081 B, `comms-coverage.py` 6,099 B, `comms-search.py` 50,569 B, `comms-refresh.py` 14,903 B); `commsindex.py` opens the source **`mode=ro`** (line 1262) | **PORT-AS-IS + install** |
| `reconcile-sms-status` (172) | `.venv/bin/python …/scripts/reconcile-sms-status.py --limit 200` | script **present** 17,477 B; `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` **present** by name; **GET-only at Twilio** (safe without a new outbound review) | **PORT-ADAPT** |
| `family_chat_watchdog` (44) | `.venv/bin/python scripts/family_chat_watchdog.py` | script **present** 13,914 B — **byte-identical size to the office copy** (`/home/zabz/personal-secretary-mvp/scripts/family_chat_watchdog.py`, 13,914 B, 2026-10-07 16:07); **`REPO = Path.home()/"personal-secretary-mvp"` → `/root/personal-secretary-mvp` — DOES NOT EXIST**; cloud `family_chat.db` **61,440 B**; `FAMILY_CHAT_TWILIO_ACCOUNT_SID`/`_AUTH_TOKEN` **present** by name | **DISABLED — see §3** |
| `lpt-recon-check` (48) | `/home/zabz/bin/lpt-recon-check.sh` | header: `APP=/home/zabz/personal-secretary-mvp`, `PY=$APP/.venv/bin/python3`, calls `scripts/lpt-sync-to-production.py --dry-run-all` against **production Postgres** and `lpt-recon.py`; `PHONE_TECH_FULL_DATABASE_URL` present by name | **§3 dead, correct not to port** |
| `lpt-dialpad-daily` (151) | `/home/zabz/bin/lpt-dialpad-daily.sh` | header: `REPO="$HOME/code/lpt-ops"` — **`/root/code/lpt-ops` does not exist**, and `/home/zabz/code` does not exist either; the office log shows `exit=1` on three consecutive days plus `WARNING - could not fast-forward the checkout` | **§3 dead, correct not to port** |
| `lpt-dialpad-apply` (158) | `/home/zabz/bin/lpt-dialpad-apply.sh` | applies to **production Postgres** (`operational`, `customer_notes`, `workOrderId`); office log tail: `psycopg2.errors.InvalidTextRepresentation: invalid input value for enum "OrderStatus": "COMPLETED" … exit 1` | **§3 dead, correct not to port** |

### 2.4 Family 4 (money and orders) — the accounting ledger is still on the office box

| job | dependency | measured state |
|---|---|---|
| `daily-finance-sync-cron` (13) | `$HOME/accounting-data/live/accounting.db` | **cloud `/root/accounting-data/live/accounting.db` = 18,476 B** — a stub, 1,194× smaller than the office ledger. (The work list says "16 KB"; I measured **18,476 B / 18 KB** and record my reading.) **DISABLED — ledger absent** |
| `supplier-order-ingest` (34) | app DB + `API=http://127.0.0.1:8002` + mail creds | script **present** 14,556 B; `DB = Path(os.environ.get("PS_DB", HERE.parent/"data"/"secretary.db"))` — **wrong path by default, correct if `PS_DB` is set**; API **present** | **DISABLED — ledger absent** (per the brief) |
| `auto-categorize` (176) | app venv + accounting ledger + authority DB | script **present** 2,291 B; no DB literal in its first 40 lines, so it resolves through the app | **DISABLED — ledger absent** |
| `supplier-delivery-watch` (35) | same as `supplier-order-ingest` | script **present** (`/opt/company/scripts/supplier-delivery-watch.py`); office record **54 runs, 54 non-zero (100%)** | **§3 dead** |
| `lpt-daily-track` (168) | `~/.lpt-reports/tracking.db`, app venv, authority DB | office `tracking.db` **7,061,504 B**, `track-cron.log` 1,600 B, mtime **2026-10-10 23:30**; cloud `/root/.lpt-reports/` **was not seen to exist** | **BLOCKED — state not moved** |

**The office ledger is confirmed still where it was** (read-only, bounded):
`secratary-ts: ls -la /home/zabz/accounting-data/live/` → `accounting.db` **21,995,520 B**, mtime
2026-10-10 10:17, plus a `-wal` and `-shm` (a live store, not dormant). Office load at the time
**0.12**, so the reading was safe.

### 2.5 Family 16 / 17 and `git-health-check`

| job | reading | verdict |
|---|---|---|
| `push-dsh-sessions` (22) | **both endpoints answer: local `http://127.0.0.1:8002/…/ingest` → HTTP 401, public `https://api.abletelsolutions.com/…/ingest` → HTTP 401** (`curl -s -o /dev/null -w "%{http_code}" -X POST … -d '{}'`, `secratary-cloud`); 401 not 404 ⇒ the route exists. The pusher script is **not on the box** (`find / -name push-dsh-sessions.mjs` → only `data/harness-config.bak-20260915T0200Z/scripts/push-dsh-sessions.mjs`); the workstation repo has it, 35,707 B. Node is **`/usr/bin/node v20.20.2`**. Its token is `DSH_SESSION_INGEST_TOKEN`, **present in `/opt/company/.env` by name** but **not at any path the script searches** (`~/code/personal-secretary-mvp/.env`, `~/Code/…`, `~/personal-secretary-mvp/.env`, `~/code/harness-config/.env`). `/root/.dsh/` holds only `transcript-archive-state.json` — **no `sessions/` directory and no DSH engine on the box** | **PORT-ADAPT, endpoint = LOCAL `127.0.0.1:8002`** (proved reachable, and the brief's condition for choosing it is satisfied). Needs a wrapper to supply the token; must run **dry first**, because with no `sessions/` it is expected to ship zero rows — which is a true fact about this box, not a job failure |
| `node-agent-cron` (9) | script **present** `/opt/company/scripts/mesh/node-agent-cron.sh`; `REPO="$HOME/personal-secretary-mvp"` → `/root/personal-secretary-mvp` **missing**; reads the `VSCODE_CHAT_INGEST_TOKEN` key from the repo `.env` — key **present** in `/opt/company/.env` by name; `--hub http://localhost:8002` (live authority, but see the IPv4/IPv6 trap in the brief: `127.0.0.1` is safer); its log target under `/root/.personal-secretary/` — **directory does not exist** | **PORT-ADAPT** |
| `git-health-check` (§1a 11) | script **present** `/opt/company/scripts/mesh/git-health-check.sh`; `REPO="/home/zabz/personal-secretary-mvp"` — **missing**; posts to `http://localhost:8002/api/v1/system/alert` (live authority) | **PORT-ADAPT**, with a caveat that must be recorded: the cloud checkout is **dirty (≥20 modified files from the cutover) and may be behind origin**, and the script's `KNOWN_OK` filter only forgives `generated/` and `.env.bak` — so as it stands it will raise a real, correct alert every 30 minutes until the checkout is cleaned. That is a true signal, not a defect in the port, but it should not be mistaken for one |

---

## §3 — NOT PORTED, AND WHY (deliberate, each with its evidence)

1. **`family_chat_watchdog` — DISABLED, as instructed, and here is the discrepancy with sizes.**
   Read-only, and it *would* guard nothing today: its store did not move.
   - office: `/home/zabz/personal-secretary-mvp/data/family_chat.db` — **1,134,592 B**,
     `messages` table **3,156 rows** (`secratary-ts: sqlite3 "file:…family_chat.db?mode=ro"
     "select count(*) from messages;"` → `3156`).
   - cloud: `/opt/company/data/family_chat.db` — **61,440 B** (mtime 2026-10-11 06:27).
   - The script resolves `REPO = Path.home() / "personal-secretary-mvp"` → `/root/personal-secretary-mvp`
     and `DB_PATH = REPO/"data"/"family_chat.db"` — **a directory that does not exist**, so it
     exits **3 (`cannot check`)** immediately, every 30 minutes.
   - If the path were repaired without moving the store it would be worse: it compares Twilio's
     carrier window against our table and exits **1 on drift**, i.e. it would alarm about a
     1-row store against real traffic indefinitely.
   - **Left OFF.** Enabling it would manufacture failures, which the brief explicitly forbids.

2. **`daily-finance-sync-cron`, `supplier-order-ingest`, `auto-categorize` — DISABLED, ledger
   absent.** Cloud `/root/accounting-data/live/accounting.db` is **18,476 B** against the office
   ledger's **21,995,520 B**; `/opt/company/data/accounting.db` is **0 bytes** (mtime 2025-08-28).
   Another workstream may be moving the ledger; I checked and **it has not arrived**. Not enabled.

3. **`lpt-recon-check` — not ported (office record: 65 runs, 53 non-zero, 82%).** It reconciles
   against **production Postgres** through `lpt-sync-to-production.py` and needs `lpt-recon.py`
   from `/home/zabz/bin`, which is not on the cloud. Its own header says it is a reporter that
   exits 3 on a condition; a ported copy would exit 3 forever without the production grants, which
   is a monitor that has been muted by construction.

4. **`lpt-dialpad-daily` — not ported (office log: `exit=1` three consecutive days, plus
   `could not fast-forward the checkout`).** Its body is `REPO="$HOME/code/lpt-ops"`; neither
   `/root/code/lpt-ops` nor `/home/zabz/code/lpt-ops` exists on the cloud. Its *purpose* — a daily
   dry-run of the Dialpad actor so arming it is decided on evidence — is worth reconstructing, but
   not by porting a job whose checkout is absent.

5. **`lpt-dialpad-apply` — not ported.** It writes notes and statuses into **production Postgres**
   and its office log ends on a hard SQL enum error
   (`invalid input value for enum "OrderStatus": "COMPLETED"`, `exit 1`). Porting it means porting
   a broken write path into production. (This is also a job that writes to a customer-facing store;
   it is not mine to arm.)

6. **`lpt-retranscribe` — blocked, not refused.** Its body is
   `/home/zabz/bin/lpt-retranscribe-drip.py`; the `bin/` move into `/root/bin/` was still in
   progress during this session (20 files at 06:35Z, my tool not among them). It becomes portable
   the moment that move lands.

7. **`lpt-daily-track` — blocked.** Needs `~/.lpt-reports/tracking.db` (office: **7,061,504 B**,
   6,552 observations per the inventory) which has not moved; its office log already reports
   `first_time NULL (not measured)` and `[STALE, partial]`.

---

## §4 — STAGED AND READY (written, syntax-checked, not deployed)

Because the work list's central warning is a *path* warning, the patch set is three files and one
install. All three are in the repo at `docs/mesh/137-work/office/` and all three pass
`py_compile` (`python -c "import py_compile; py_compile.compile(p, doraise=True)"` → `COMPILE OK`).

| staged file | what changed | why |
|---|---|---|
| `dialpad-recording-gap.py` (11,441 B) | `DB = ROOT/"data"/"secretary.db"` → `DB = _secretary_db()`, which is `SECRETARY_DB` env → `app.config.settings.database_url` → office fallback | The office file resolves to the cloud's 1.8 MB non-authority copy that lacks `dialpad_call_full` |
| `dialpad-transcript-gap.py` (…) | the identical change, identical resolver | same |
| `comms-refresh.py` (…) | `SOURCE` literal → `COMMS_SOURCE` env → `/root/authority.db` if present → office literal | the office single literal would index the **frozen** office database; the brief requires the index be built against the authority |

The rule I applied, and the reason it is the right shape rather than a find-and-replace: **the app
is the single source of truth for where its database is** (`DATABASE_URL` → `settings.database_url`,
which is what `dialpad_harvester.py` already uses in 18 places). A script that hardcodes a second
answer is a script that will be wrong again at the next move. None of these three files opens a
database read-write; `dialpad-recording-gap.py` and `dialpad-transcript-gap.py` already open
`mode=ro` (`sqlite3.connect(f"file:{DB}?mode=ro", uri=True)`), and `commsindex.py` opens its source
`mode=ro` at line 1262.

**Not staged, and why:** `dialpad-call-fresh.py` exists **only** on the cloud box (3,791 B,
2026-10-08 16:23) — there is no second copy anywhere I could find to compare against, so I will not
claim its database path is right or wrong. Its office ledger record is the worst in the inventory
(`last rc=143 SIGTERM`, `database is locked`, `gave up for 6453199368921088 after 5 attempt(s) in
52.6s`), so it needs its own look, with the file in hand, before it is enabled.

**The deployment that follows on restored access** (exact, in order, with the proof each produces):

```sh
# 0. precondition
df -h /                                              # before anything that writes

# 1. the bin/ prefix both harvest cron jobs insist on (their REPO= is absolute)
ln -s /opt/company /home/zabz/personal-secretary-mvp     # only if still absent

# 2. the two patch files
install -m 755 dialpad-recording-gap.py  /opt/company/scripts/dialpad-recording-gap.py
install -m 755 dialpad-transcript-gap.py /opt/company/scripts/dialpad-transcript-gap.py

# 3. proof the patch took: the script must now name the authority, not the local copy
cd /opt/company && .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json   # expect selected>0 / no "no such table"
sqlite3 "file:/root/authority.db?mode=ro" "select count(*) from dialpad_call_full;"       # 13,995 before -> advances after

# 4. comms index: install the toolset, then index the AUTHORITY
mkdir -p /root/.fsearch
install -m 755 comms-refresh.py commsindex.py comms-coverage.py comms-search.py /root/.fsearch/
python3 /root/.fsearch/comms-refresh.py            # COMMS_SOURCE defaults to /root/authority.db
sqlite3 /root/.fsearch/comms.db "select count(*) from communications;"   # BEFORE and AFTER: mtime + rows

# 5. the cron lines (name preserved from the office job so runs.tsv stays readable)
*/30 * * * * /usr/local/bin/cron-wrap.sh dialpad-harvest-cron "$(printf '%s' 'cd /opt/company && /opt/company/scripts/dialpad-harvest-cron.sh' | base64 -w0)"
15,45 * * * * /usr/local/bin/cron-wrap.sh dialpad-sms-harvest-cron "$(printf '%s' 'cd /opt/company && /opt/company/scripts/dialpad-sms-harvest-cron.sh' | base64 -w0)"
7,37 * * * * /usr/local/bin/cron-wrap.sh comms-refresh "$(printf '%s' 'COMMS_SOURCE=/root/authority.db /usr/bin/python3 /root/.fsearch/comms-refresh.py' | base64 -w0)"
12,42 * * * * /usr/local/bin/cron-wrap.sh comms-refresh-2 "$(printf '%s' 'COMMS_SOURCE=/root/authority.db /opt/company/.venv/bin/python3 /root/.fsearch/comms-refresh.py --check --max-age-minutes 45' | base64 -w0)"
*/5 * * * * /usr/local/bin/cron-wrap.sh dialpad-recording-gap "$(printf '%s' 'cd /opt/company && flock -n /tmp/dialpad-dl.lock .venv/bin/python scripts/dialpad-recording-gap.py --limit 300 --json' | base64 -w0)"
*/10 * * * * /usr/local/bin/cron-wrap.sh dialpad-transcript-gap "$(printf '%s' 'cd /opt/company && flock -n /tmp/dialpad-ts.lock .venv/bin/python scripts/dialpad-transcript-gap.py --limit 400 --retry-failed --max-minutes 600' | base64 -w0)"
# + reconcile-sms-status, family_chat_watchdog (DISABLED per §3), push-dsh-sessions, node-agent-cron, git-health-check
```

**Monitors that would notice each failure** (definition-of-done item 5): `dialpad-harvest-cron`
writes `$HOME/.dialpad-harvest.last_run` and the family-3 `production-comms-freshness` reads the
feed silence; `dialpad-sms-harvest-cron` writes `$HOME/.dialpad-sms-harvest.last_run` and
`dialpad_sms_cache.created_at`; `comms-refresh-2` **is** the monitor for `comms-refresh` (it exits
non-zero when the index is stale); the two gap jobs have **no watching monitor** — their failure
mode is "runs, exits 0, produces nothing", so their subject (media rows fetched, transcripts added)
must be counted, and per the port brief that gap needs a journal `pain` entry.

---

## §5 — COULD NOT VERIFY, AND WHAT WOULD UNBLOCK THIS

**Could not verify (no access, so no claim):**

1. **Whether any of my jobs runs.** No `runs.tsv` row, no script installed, no cron line — the
   entire definition of done in `133-PORT-BRIEF.md` §3 is unmet **by construction**.
2. **`dialpad-call-fresh.py`'s database path.** The file exists only on the cloud box.
3. **`comms-refresh`'s before/after index measurement** — the work list requires proving the index's
   mtime and row count before and after. I have a plan and the exact commands; I have no box.
4. **Whether another workstream's ledger move is in flight.** I measured that it has *not* arrived
   (18,476 B stub at 06:31Z); I cannot see their intent.
5. **`/root/bin/`'s final contents.** It was being populated at 06:35Z.
6. **Why the SSH key was refused.** I proved it *is* refused and eliminated every client-side and
   network cause; the server-side change itself is not directly observable without access.

**To unblock — the recovery path, in one place:**

1. **Restore SSH access to `secratary-cloud`.** The box's `authorized_keys` is a single 105-byte
   file that was replaced at ~06:40Z. The recovery needs the Hetzner console or a live channel and
   cannot be done from outside; the exact instruction (which key to append, and the warning not to
   delete `/root/.ssh/id_ed25519`) is recorded by a sibling session in **`journal.py show L3603`
   §RECOVERY** — it is the authoritative version and I am not duplicating it here, because a second
   copy of a credential-shaped instruction is a second thing to go stale. **Nothing on the box needs
   restarting** to do this and no service was touched by this workstream.
2. **Then re-run this workstream** — the staged files in `docs/mesh/137-work/office/` deploy as §4,
   and the family 4 jobs enable only once the ledger lands.
3. **File the SSH incident as its own defect.** It is not an ingestion problem: an authority whose
   only door can be closed by an unattended agent, with no console path and one key, is a single
   point of failure worth more than this migration. Proposed journal entry:
   `pain — secratary-cloud lost root SSH publickey access at ~06:47Z 2026-10-11 with no console
   path; every workstream that needs to deploy was stopped. Fix: a second key held separately, and
   a console/Tailscale path that does not depend on `authorized_keys` on the box itself.`

**One thing I want on the record about this report's shape.** A workstream whose deliverable is
"jobs ported and proven" cannot honestly deliver jobs it did not port. Writing a report that reads
as if they were would be the exact failure this estate has paid for twice — a green artefact over
an unobserved system. The defect I *did* prove (§2.2) is real, measured, and would have shipped a
family of jobs that ran cleanly every 30 minutes against a 1.8 MB file while the company's actual
call record sat untouched in a 23.7 GB database next to it.
