# 152 — OWNERSHIP MAP FOR THE 27 UNPORTED JOBS, AND THE TWO NOBODY OWNED

**Author:** mesh child session on host **`zabz-yoga`** (Windows laptop), 2026-10-11 **20:54–21:12Z**.
**Scope:** build the ownership map for the 27 jobs `151-VERIFY-CLOUD-AUTHORITY.md` §5 reports as having
no home (plus the office timers `trunk-check`/`fa-index`), then port only the ones no workstream owns.
**Office box was READ-ONLY**: the only things read there were two files (`ls -la` + `cat`, 1 897 B and
9 032 B); load stayed **0.22** (`secratary-ts: cut -d' ' -f1 /proc/loadavg`). Nothing on it was started,
stopped, enabled, disabled, unmasked or restarted.
**Nothing on the cloud box was restarted.** `secratary-cloud: systemctl show <unit> -p ActiveEnterTimestamp`
→ `company-api` 15:17:41Z / `cloudflared` 08:25:06Z / `secretary-dashboard` 08:25:04Z /
`phone-redirector` 15:53:55Z — identical to `151` §4's readings.
**Standard:** every number carries its machine and the command that produced it.

---

## 0. HEADLINE

1. **The parent's hypothesis is right in shape and wrong in detail.** Of the 27 jobs, **25 are owned**
   by a named workstream and merely not done yet. **Two are genuinely UNOWNED:**
   `monitor-hetzner-backups` and `stripe-key-watch`.
2. The parent's guessed residue was **7 of 8 wrong**: `lpt-daily-track`, `lpt-business-report`,
   `lpt-report-freshness`, `node-agent-cron`, `lpt-retranscribe`, `dialpad-call-fresh` and
   `lpt-hub-refresh` are each named by their owning workstream's own artifact; only `stripe-key-watch`
   from that list was unowned — and `monitor-hetzner-backups`, which the guess did not include, was the
   other one.
3. **Both unowned jobs are now ported, scheduled at the office cadence, and proven by real cron ticks**
   (§3) — `runs.tsv` rows at 21:06:01Z and 21:08:01Z (monitor) and 21:07:01Z (stripe), all rc 0.
4. `trunk-check` and `fa-index` are owned by workstream 137, **which RETIRED both** — they need no port.

---

## 1. HOW OWNERSHIP WAS DECIDED (the rule applied, so it can be re-checked)

Ownership needed a **chain of three artefacts, each naming the job**:

1. `132-CRON-INVENTORY.md` §1 family table (lines 46–71) — gives **job → family**; §1b (lines 188–200)
   for the office timers.
2. `141-MIGRATION-STATUS.md` lines 30–37 — gives **family → workstream** (and, at line 37, names four
   jobs directly: `run-sentinel`, `converge-authority`, `chip-resume`, and the gaps).
3. The workstream's own artifact (133/134/134-PORT/135/137/138/139/140) must **name the job**.

Applied strictly, as instructed: *a family allocation with no artifact naming the job is not ownership.*
Both jobs below fail step 3, and `stripe-key-watch` fails step 1 as well — it has **no row at all** in
`132`'s §1 family table (it appears only as §1a row 46, line 128, and §2 entry 42, line 580).

---

## 2. DELIVERABLE 1 — THE MAP

"Installed?" and "run?" were measured before any port: `secratary-cloud: crontab -l` (21 wrapped jobs),
`systemctl list-timers --all`, and `cut -f2 /root/.cron-status/runs.tsv | sort -u` →
**2 074 rows, 19 distinct names** at 21:02Z. **None of the 27 had a crontab line, a timer, or a ledger
row** — which is what "no home" means, confirmed rather than assumed.

| job | family per `132` | owner (artifact:line that NAMES it) | installed on cloud? | ever run? | verdict |
|---|---|---|---|---|---|
| `comms-refresh` | f5 (132:52) | 138 `138-PORT-INGESTION.md:195` | no | no | OWNED-AND-PENDING |
| `lpt-hub-refresh` | f8 (132:55) | 139 `139-PORT-OWNER-CHANNEL.md:444` | no (script present, unscheduled — 151:147) | no | OWNED-AND-PENDING |
| `wake-fanout` | f6 (132:53) | 139 `:186` | no | no | OWNED-AND-PENDING |
| `run-wake-sources` | f6 (132:53) | 139 `:170` | no | no | OWNED-AND-PENDING |
| `wake-cost` | f6 (132:53) | 139 `:215` | no | no | OWNED-AND-PENDING |
| `wake-balance` | f6 (132:53) | 139 `:228` | no | no | OWNED-AND-PENDING |
| `owner-ask` | f6 (132:53) | 139 `:239` | no | no | OWNED-AND-PENDING |
| `dialpad-call-fresh` | f5 (132:52) | 138 `:193` | no | no | OWNED-AND-PENDING |
| `reconcile-sms-status` | f5 (132:52) | 138 `:196` | no | no | OWNED-AND-PENDING |
| `comms-refresh-2` | f3 (132:50) | 135 `135-PORT-FRESHNESS.md:6, :301` | no | no | OWNED-AND-PENDING |
| `family_chat_watchdog` | f5 (132:52) | 138 `:197, :229` | no | no | OWNED-AND-PENDING (138 disabled it) |
| `supplier-order-ingest` | f4 (132:51) | 138 `:207` | no | no | OWNED-AND-PENDING |
| `auto-categorize` | f4 (132:51) | 138 `:208` | no | no | OWNED-AND-PENDING |
| `lpt-daily-track` | f4 (132:51) | 138 `:210` | no | no | OWNED-AND-PENDING (blocked: `tracking.db`) |
| `lpt-business-report` | f8 (132:55) | 139 `:435` | no | no | OWNED-AND-PENDING |
| `lpt-report-freshness` | f3 (132:50) | 135 `:6, :69` | no | no | OWNED-AND-PENDING |
| **`monitor-hetzner-backups`** | f3 (132:50) | **NONE** — 135 `:303` explicitly disclaims it ("NOT mine; left to the backup workstream"); 133 and 134 never name it | no → **yes 21:05:37Z** | no → **yes** | **UNOWNED → PORTED §3.1** |
| `tree-integrity-check` | f10 (132:57) | 134 `134-PORT-GUARDS-BACKUP.md:291` | no (dry-run line prepared) | no | OWNED-AND-PENDING |
| `work-integrator` | f8 (132:55) | 139 `:462` | no | no | OWNED-AND-PENDING |
| `chip-resume` | f22 (132:69) | 140 `140-PORT-CORE-AND-GAPS.md:215` (141:37 names it) | no (script staged) | no | OWNED-AND-PENDING (140 disabled it) |
| `run-sentinel` | f13 (132:60) | 140 `:93` (141:37 names it) | no | no | OWNED-AND-PENDING |
| `model-failover-watch` | f9 (132:56) | 135 `:306` | no | no | OWNED-AND-PENDING |
| **`stripe-key-watch`** | **none — no §1 family row** (132:128 only) | **NONE** — no artifact in 133–140 names it | no → **yes 21:05:50Z** | no → **yes** | **UNOWNED → PORTED §3.2** |
| `node-agent-cron` | f17 (132:64) | 138 `:5, :222` | no | no | OWNED-AND-PENDING |
| `push-dsh-sessions` | f16 (132:63) | 134 (141:31 names it) `134-ARCHIVE-CONTINUITY.md:309, :355` | no | no | OWNED-AND-PENDING (140 `:241` disabled it) |
| `lpt-retranscribe` | f5 (132:52) | 138 `:194` | no | no | OWNED-AND-PENDING (blocked: `bin/` move) |
| `website-comms-push-cron` | f8 (132:55) | 139 `:419` | no | no | OWNED-AND-PENDING |
| `trunk-check` (office timer) | §1b (132:193) | 137 `137-PORT-SYSTEMD-TIMERS.md:483` | no | no | OWNED — **RETIRED by 137** |
| `fa-index` (office timer) | §1b (132:195) | 137 `:447` | no | no | OWNED — **RETIRED by 137** |

---

## 3. DELIVERABLE 2 — THE TWO JOBS NOBODY OWNED

Both were absent from the cloud box entirely (`ls` → *No such file or directory* for
`/root/bin/`, `/usr/local/bin/` and `/opt/company/scripts/monitor-hetzner-backups.sh` and
`/root/bin/stripe-key-watch.py`), so moving the script was part of the port. Both were fetched from the
office box as base64 and verified by sha256 before and after the move; every `/home/zabz/...` path was
translated through `133-PORT-BRIEF.md`'s mapping table, never copied.

**One shared dependency was missing and is now fixed.** Both scripts `ssh` to the Hetzner boxes **by
alias** (`hetzner`, `lpt-apps`) as the office box did. The authority had no such aliases, and an
alias-less `ssh root@87.99.141.172` fails `Permission denied (publickey)` (measured — the wrong identity
is offered first). `/root/.ssh/config` now carries both aliases (`IdentityFile
/root/.ssh/id_ed25519_hetzner`, `IdentitiesOnly yes`); the previous config is at
`/root/.ssh/config.bak-port152-20261011T210507Z`. Proof: `ssh -n hetzner hostname` → `waze-mdm-01`,
`ssh -n lpt-apps hostname` → `lpt-apps-01`.

### 3.1 `monitor-hetzner-backups` — family 3, **UNOWNED**, now PORTED

- **What it is:** checks both Hetzner boxes' restic backup freshness every 6h and alerts the CEO via
  `POST http://localhost:8002/ceo/chat` on >26h staleness (route exists: `GET /ceo/chat` → **405**).
- **Script:** office `/home/zabz/scripts/monitor-hetzner-backups.sh`, 1 897 B, sha256
  `9bac3b54eaa17ddb44ae803956f1e7784bbf193e57957469a567ddc5de5f368d` → cloud
  `/usr/local/bin/monitor-hetzner-backups.sh`, mode 755, **sha256 identical** (byte-identical port; it
  uses `$HOME`, so root's `$HOME=/root` gives the translated log `/root/monitor-hetzner-backups.log`).
- **Dependencies checked:** `hetzner` alias ✓ · `lpt-apps` alias ✓ · `/root/backup-status-check.sh` on
  both targets ✓ (991 B each) · `/ceo/chat` route ✓ · log path writable ✓.
- **Cron (office cadence kept exactly):**
  `0 */6 * * * /usr/local/bin/cron-wrap.sh monitor-hetzner-backups L3Vzci9sb2NhbC9iaW4vbW9uaXRvci1oZXR6bmVyLWJhY2t1cHMuc2g=`
- **Evidence — real cron ticks, not just a manual run:** ledger
  `/root/.cron-status/runs.tsv` → `2026-10-11T21:06:01Z monitor-hetzner-backups 0 12` and
  `21:08:01Z monitor-hetzner-backups 0 13`. Output (`/root/monitor-hetzner-backups.log`):
  `[2026-10-11 21:06:02] waze-mdm-01: rc=0 — OK: last backup 17h ago`,
  `lpt-apps-01: rc=0 — OK: last backup 17h ago`, `all backups fresh`.
- **First run due on the real cadence:** 2026-10-12 00:00Z (not yet reached at write time).
- **What would notice its failure: nothing.** No monitor reads its ledger row — filed as a gap in §5.

### 3.2 `stripe-key-watch` — **no family, UNOWNED**, now PORTED

- **What it is:** every 6h, tests the rolled Stripe keys from the `*.bak-striperoll-20260915` backups
  (read over ssh, so no extra copy of a live secret is created) and watches the account for a new
  terminal reader, unexpected refunds or disputes; anomalies go to `owner_decision_queue`.
- **Script:** office `/home/zabz/bin/stripe-key-watch.py`, 9 032 B, sha256
  `c5fc432b4ea767f7064565a019d56156b6b5167e7cb4b1c4063b2479c2847280` → cloud
  `/usr/local/bin/stripe-key-watch.py`, 9 125 B, sha256 `c701af3ee84d99626c0b6cdb0855338d14cc76af3b50eec22d1d97e3b5fd6f50`.
  **One line translated:** the office key-backup path `/home/zabz/personal-secretary-mvp/.env.bak-striperoll-20260915`
  → `/opt/company/.env.bak-striperoll-20260915`; no `/home/zabz/` literal remains
  (`[regex]::Matches(...,'/home/zabz').Count` → **0**). `python3 -c compile(...)` → `py syntax OK`.
- **Dependencies checked:** ssh alias `lpt-apps` ✓ (`/opt/lpt/.env.bak-striperoll-20260915` exists,
  7 248 B) · `/root/bin/owner-queue.py` ✓ (40 628 B — note `135-PORT-FRESHNESS.md:344` calls it
  missing; it is present) · state dir `/root/.lpt-verify` ✓ · log path ✓.
  **Missing, deliberately not moved:** `/opt/company/.env.bak-striperoll-20260915` does not exist. I did
  **not** copy the office secret: the script's own design says the backup is the only reason it can test
  the key and that it exists to avoid a second copy of a live secret. The script reports the absence
  instead of faking it — `could not read an old key from /opt/company/.env.bak-striperoll-20260915 - it
  cannot be tested`.
- **Cron (office cadence kept exactly):**
  `17 */6 * * * /usr/local/bin/cron-wrap.sh stripe-key-watch L3Vzci9iaW4vcHl0aG9uMyAvdXNyL2xvY2FsL2Jpbi9zdHJpcGUta2V5LXdhdGNoLnB5ID4+IC9yb290Ly5scHQtdmVyaWZ5L3N0cmlwZS13YXRjaC5sb2cgMj4mMQ==`
- **Evidence — real cron tick:** `2026-10-11T21:07:01Z stripe-key-watch 0 2` (plus the deliberate
  wrapper run at 21:05:50Z, rc 0). Output: `old key ...[MASKED]: HTTP 401 (dead)`,
  `watch clean and every old key is now dead - the grace period has ended; this watcher can be removed`.
- **First run due on the real cadence:** 2026-10-12 00:17Z.
- **What would notice its failure: nothing** — same gap.

### 3.3 Crontab integrity

`crontab -l | wc -l`: **31 → 37** (the 21 pre-existing jobs untouched; +4 comment lines +2 job lines).
Backup of the pre-change crontab: `/root/crontab.bak-port152-20261011T210537Z`. The temporary
`*/2` proof lines are gone (`crontab -l | grep -c TEMPORARY` → **0**; `grep -c 'cron-wrap.sh'` → 24 =
21 jobs + 2 new + 1 pre-existing comment).

---

## 4. WHAT REMAINS, AND WHO OWNS IT

- **25 jobs: OWNED-AND-PENDING**, each with its owner's named blocker in the artifact cited above — the
  seven that matter most are `comms-refresh`/`comms-refresh-2` (no `/root/.fsearch` index), the four wake
  jobs and `owner-ask` (139: needs the owner's word on the outbound words), `lpt-report-freshness`
  (no `~/.lpt-reports/tracking.db` writer), `monitor-hetzner-backups`' sibling `box-health-check`, and
  `lpt-daily-track` (state not moved).
- **`trunk-check` and `fa-index`: owned by 137 and RETIRED** — nothing to port; say so rather than
  re-adding them.
- **`run-sentinel`** is prepared and blocked only by 140's SSH-authorization break; **`push-dsh-sessions`**
  and **`chip-resume`** are deliberately disabled by their owners.
- **The Hetzner API token** (401, `147-AUDIT-INTEGRATIONS.md:41`) is owned by 140 and is **not** a
  dependency of the port I did: `monitor-hetzner-backups` reads restic freshness over ssh and never calls
  the Hetzner API.
- **Two residual gaps in my own work:** (a) nothing monitors the absence of either new job (§5);
  (b) the office-side Stripe key source is untested on the authority because I would not copy a live
  secret — if the owner wants both keys watched, that backup must be moved deliberately, or the job
  retired, since the key it *could* test is already dead.

## 5. COULD NOT VERIFY

1. **Nothing reads `monitor-hetzner-backups`' or `stripe-key-watch`'s ledger rows**, and no monitor
   exists for their absence. This is the estate's known dead-man gap, not one I introduced.
2. **The database effect of any job** — not measured (no `mode=ro` query was run against
   `/root/authority.db`), consistent with `151` §6.4.
3. Whether the office box's own `stripe-key-watch` log ever saw both keys: the script carries one office
   path and one remote path, so even on the office box at most two keys were testable.
4. The office crontab's post-re-freeze state — not re-read; `151` §2 owns that finding.
