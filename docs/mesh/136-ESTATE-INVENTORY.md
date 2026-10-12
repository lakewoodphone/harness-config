# 136 — ESTATE INVENTORY: what the office box has that the cloud box does not

**Workstream:** migration inventory (the estate/dependency workstream). **Author:** Zabz, ZABZ-YOGA
session, 2026-10-11 ~06:30Z. **Scope:** the definitive inventory of everything the OFFICE box holds
that the 2026-10-11 cloud cutover did **not** bring, restricted to what the COMPANY actually uses,
each with a migration verdict and an ordered move list.

**This is an inventory and an analysis. Nothing was moved, nothing was written, no machine was
modified.** Every reading below carries the machine and the command that produced it. Where I could
not measure something I say *unmeasured* rather than guessing.

**Primary evidence:** `/home/zabz/cutover/crontab.before` on `secratary-ts` (176 lines, 87 decoded
`cron-wrap.sh` payloads); `/home/zabz/personal-secretary-mvp/.env` on `secratary-ts` (301 keys) vs
`/opt/company/.env` on `secratary-cloud` (302 keys); `grep -rn "/home/zabz" /opt/company/app
/opt/company/scripts`; `/opt/company/data/autopilot_state.json`.

**Office box discipline:** every office command in this workstream was a `wc`, `ls`, `stat`, `grep`,
`cut`, `readlink` or a bounded `du -sh` on a single directory. Load was checked around each pass and
never exceeded **0.58** (`secratary-ts: cut -d' ' -f1 /proc/loadavg`). No recursive read of the
23 GB database and no deep `du` was run.

**A correction I owe, recorded here rather than buried.** My first path-extraction helper
over-matched its key filter and printed *values* for keys whose names merely contained `FILE`, `URL`,
`DB`, `API_KEY` and similar — including live API keys and database passwords — into this session's
transcript. That is a real credential exposure caused by my own tool, on a workstream whose whole
point was to avoid exactly that. I stopped it immediately, rewrote the helper to select only keys
whose *name* ends in `_PATH`/`_DIR`/`_REPO`/`_ROOT`/`_FILE`/`_STORE`, re-ran only the corrected
version, and **no value appears anywhere in this document**. The exposure is reported in §5 and should
be treated as an incident: the session transcript is in the DSH archive, and the affected keys should
be rotated. The tool as first written must not run again.

---

## §0 — HEADLINE

| reading | value | evidence (machine · command) |
|---|---|---|
| office `/home/zabz/repos` | **15 GB, 14 repos** | `secratary-ts: du -sh /home/zabz/repos` |
| office `/home/zabz/bin` | **25 MB, 427 files** (137 `.py`, 48 `.sh`) | `secratary-ts: ls /home/zabz/bin \| wc -l` |
| office `/home/zabz/code/harness-config` | **1.6 GB** | `secratary-ts: du -sh /home/zabz/code/harness-config` |
| office `/home/zabz/lpt-transcripts` | **2.6 GB** | `secratary-ts: du -sh /home/zabz/lpt-transcripts` |
| office `/home/zabz/accounting-data` | **6.3 GB** (ledger itself 48 MB) | `secratary-ts: du -sh /home/zabz/accounting-data` |
| office `/home/zabz/secretary-backups` | **199 GB** | `secratary-ts: du -sh /home/zabz/secretary-backups` |
| cloud `/home/zabz` | **one directory: `outbound-drafts`** | `secratary-cloud: ls -la /home/zabz/` |
| cloud `/opt/company` | present, app + scripts + 14 GB `data/` | `secratary-cloud: ls -la /opt/company` |
| cloud crontab | **empty — "no crontab for root"** | `secratary-cloud: crontab -l` |
| cloud `accounting.db` | **16 KB stub, 2 tables, no `transactions`** | `secratary-cloud: sqlite3 schema query` |
| cloud disk (first reading, 06:10Z) | **68G used / 4.4G avail / 94%** | `secratary-cloud: df -h /` |
| cloud disk (later reading, 06:22Z) | **46G used / 27G avail / 64%** | `secratary-cloud: df -h /` |
| cloud memory | 7.7 GB total, swap 1.6/4.0 GB used | `secratary-cloud: free -m` |
| cloud `company-api` RSS | **5.4 GB peak 6.6 GB** | `secratary-cloud: systemctl status company-api` |

**The disk reading moved during this work (68G→46G used) and I did not cause it.** A large temporary
file left the cloud box between my two readings; `authority.db` was 23,707,291,648 B at both and its
WAL was live. So the binding constraint recorded in the migration brief — a few GB free — **was true
at the cutover and is not true now**. This changes what is affordable, so every size in §2 is stated
against whichever budget is real at the time of the move, and §2 flags what will not fit either way.

---

## §1 — THE ITEM TABLE

Verdict key:
**MUST-MOVE** the company breaks or degrades today without it ·
**SHOULD-MOVE** used, and its absence degrades slowly ·
**LEAVE** never used by the company, or bound to office hardware/LAN ·
**RETIRE** dead — evidence it has not worked or been used in weeks.

| # | item | type | size | only copy? | user evidence (what reaches for it) | verdict | symptom if absent |
|---|---|---|---|---|---|---|---|
| 1 | `/home/zabz/repos/quickbooks-agent` | code | **282 MB** (275 MB `node_modules`; ~7 MB tracked) | no — GitHub `lakewoodphone/quickbooks-agent` | `.env:QB_AGENT_REPO_PATH`; 5 services call `_qb_repo()` (`amex_bank_service.py:67`, `amazon_bank_service.py`, `boa_bank_service.py`, `ebay_bank_service.py`, `chase_bank_service.py`) | **MUST-MOVE** | `quickbooks-agent repo not found at /opt/company/domains/finance/quickbooks-agent` — ×9 in `autopilot_state.json`; `paypal_sync`, `amazon_sync`, `ebay_sync` all `failed` at 2026-10-11T05:41:19Z |
| 2 | `/home/zabz/accounting-data/live/accounting.db` + `books.db` | data | **22 MB + 26 MB** | **yes** (off-box copies are 18-19 MB, Jun-Sep) | `~/accounting-data/live/accounting.db` is the CFO ledger; `cfo-ask`, `cfo-scoreboard`, `daily-finance-sync-cron`, `auto-categorize`, `lpt-daily-track`, `owner-ask` | **MUST-MOVE** | cloud holds a 16 KB stub with 2 tables and **no `transactions` table**; `financial_alert_sweep` reports `Local ledger DB not available`; `cfo-ask`/`cfo-scoreboard` filed DEAD in `132-CRON-INVENTORY.md` for exactly this |
| 3 | `/home/zabz/personal-secretary-mvp/scripts/` | code | 13 shell + 300+ py (**delta ~5 MB**) | no — app git on cloud | 87 cron payloads call these paths (16 refs to `personal-secretary-mvp/scripts`) | **MUST-MOVE** (delta only) | 92 scheduled jobs have no body to run; `dialpad-recording-gap.py`/`dialpad-transcript-gap.py` are the 2 highest-frequency office paths in the app tree (796 + 374 hits) |
| 4 | `/home/zabz/bin/` | code | **25 MB**, 427 files | partly — `bin.git` bare repo; 71 **unpushed commits** | 87 cron payloads wrap through `bin/cron-wrap.sh`; ~60 distinct `bin/*` tools are the job bodies (`deadman.py`, `owner-ask.py`, `wake-fanout.sh`, `disk-guard.py`, …) | **MUST-MOVE** | every cron job dies at its first hop; **the external dead-man switch stops**, so a dead authority rings nobody |
| 5 | `/home/zabz/code/harness-config/` | code | **1.6 GB** | no — remote `/home/zabz/harness-config.git`; **71 unpushed commits** | 8 cron payloads (`push-dsh-sessions.mjs`, `serve-phone.sh`, `probe-phone.py`, `lpt-hub-refresh.sh`, `profile-gate.mjs`, `order-feed-refresh.sh`, `text-line-check.sh`, `autosync.sh`) | **MUST-MOVE** | the journal, the session archive pusher, the phone server and the ops docs all stop; `journal-commit` (the 15-minute autosync) has nowhere to run |
| 6 | `/home/zabz/lpt-transcripts/` | data | **2.6 GB** (manifest 1.5 MB, 256 object shards) | **yes, this is the archive** | AGENTS.md §1 standing rule: the raw transcript archive "must always exist" | **MUST-MOVE** | the company's training data has no live home; `transcript-archive-run.sh --check` has nothing to report against |
| 7 | `data/{briefings,waze-mdm,voice_recordings,voice_tts,code_snapshots,skills,tools}` | data | 113 MB + 86 MB + ~3 MB | **yes** for waze-mdm | app `data/` roots; `waze-mdm/wallpapers` is device MDM payload; `briefings` are generated owner briefings | **SHOULD-MOVE** | cloud `data/waze-mdm` and `data/voice_recordings` are **empty stubs (4 KB)**; owners' briefings have no history |
| 8 | `/home/zabz/ceo-kernel/` + `ceo-kernel-var/` + `ceo-kernel.git` | code+data | ~50 MB est. (**unmeasured**) | no — bare repo present | 2 cron payloads: `run-sentinel.sh` (*/5), `run-ha-truth.sh` (*/30); 15 refs to `ceo-kernel-var/` in the app tree | **MUST-MOVE** | the CEO kernel's sensing loop never runs; `ceo-kernel-var/latest.json` (10 app refs) is never written |
| 9 | `/home/zabz/repos/lpt-hub` | code | **3.7 GB** | no — GitHub `lakewoodphone/lpt-hub` | cron `audit`: `cd /home/zabz/repos/lpt-hub && … tools/customer/audit.py --write-report`; `lpt-hub-refresh`; 14 app refs | **SHOULD-MOVE** | the four-surface customer audit stops producing `~/.lpt-verify/four-surface.json`; note it is **already DEAD (100% failure)** before the cutover, so this is a SHOULD not a MUST |
| 10 | `/home/zabz/accounting-data/browser-auth/` | data (credentials, live cookies) | **5.7 GB** | **yes** | the 5 `*_bank_service.py` modules drive Playwright against logged-in bank sessions | **SHOULD-MOVE** | every bank re-authentication from scratch → MFA/OTP loops; the QB repo alone is not enough to make a sync succeed |
| 11 | `/home/zabz/.secrets/` (8 files) | credentials | 36 KB | **yes** | Cloudflare, Twilio-Escape101, Dialpad UI headers, NJ employer access, BitLocker recovery | **MUST-MOVE (by name, §3)** | dependent jobs fail on missing credential; see §3 for which |
| 12 | `/home/zabz/.ssh/` (keys + config) | credentials | ~300 KB | partly copied | `LINUX_PC_SSH_KEY_PATH=/home/zabz/.ssh/id_rsa_linux_pc` is **ABSENT on cloud** | **MUST-MOVE (by name, §3)** | `LINUX_PC_*` jobs cannot authenticate; the key path in `.env` points at nothing |
| 13 | `/home/zabz/.git-credentials` | credential | 1.1 KB | **yes** | git clone/push of `lakewoodphone/*` | **MUST-MOVE** | **measured now: cloud cannot clone — `git ls-remote` → `could not read Username for 'https://github.com'`** |
| 14 | `/home/zabz/node/` (`bin/node`) | runtime | unmeasured | no (apt `node v20.20.2` on cloud) | `push-dsh-sessions` cron calls `/home/zabz/node/bin/node`; `profile-gate` too | **SHOULD-MOVE** or repoint | 2 cron jobs fail on a missing interpreter; cloud node is v20, office unmeasured vs it |
| 15 | `/home/zabz/.lpt-r2.env` | credential | 1.6 KB | **no — already on cloud** at `/root/.lpt-r2.env` | `push-db-offsite.sh`, `company-offsite-push.sh`, `report-offsite-age.sh` | **LEAVE** | already satisfied; verify mode 600 and owner root |
| 16 | `/home/zabz/secretary-backups/` | data (backups) | **199 GB** | **yes** | `prune-backups` retention; every DB snapshot since Aug | **LEAVE on this disk — see §4** | cannot fit: 199 GB into 27 GB. Retention is R2's job now |
| 17 | `/home/zabz/repos/{phone-and-tech-full, kosher-filter-ai, research-knowledge-base, chumash-timeline, personality-test, kyocera-escalator, lpt-flip-phone, ha-config, halacha}` | code | 2.1 G + 581 M + 2.1 G + 685 M + 693 M + 3.2 G + 1.0 G + 77 M + 848 K | no — all have GitHub origins | 10 app refs to `phone-and-tech-full`, 10 to `kosher-filter-ai`, 9 to `research-knowledge-base`; `kyocera-escalator` 3.2 GB has **no app ref** | **SHOULD-MOVE (selective)** / **RETIRE (`kyocera-escalator`)** | nothing breaks today; these are desk-scoped checkouts. `kyocera-escalator` total 3.2 GB with no caller is the largest pure dead weight found |
| 18 | `/home/zabz/wt-562-*`, `/home/zabz/wt-563-*` (worktrees under `/home/zabz/`) | code (stale worktrees) | unmeasured | no | 30+12+18+8 app-tree refs each, **all in test files** | **RETIRE** | nothing; these are abandoned parallel-agent worktrees whose paths leaked into tests |
| 19 | `/home/zabz/.config` (4.3 GB), `.dsh` (820 MB), `.cache`, `.npm`, `.vscode-server`, `.platformio`, `.swiftpm` | data/caches, machine-bound | 5-6 GB | no | office desktop session state | **LEAVE** | office-hardware/session bound; not company function |
| 20 | the tail of `/home/zabz/` — `_scratch`, `_mig_*`, `_hc_*`, `_verify*`, `_worktrees`, `_converge-*`, `_git-backup-*`, `_lpt447_wt`, `_kaf*_wt`, odd files (`300`, `NUL`, `SELECT 1;`, `]*`, `C:\Users\ezabz…` copies) | scratch (junk) | large, **unmeasured** | no | none — scratch from ended sessions | **RETIRE** | nothing |
| 21 | `personal-secretary-mvp/domains/finance/quickbooks-agent/` | dead artifact | **272 MB** | no | looks like a QB repo but holds **only `node_modules`, no `package.json`** | **RETIRE** | it is the trap: `_qb_repo()` resolves to this shape of path and reports "repo not found" because `package.json` is missing |
| 22 | `/etc/dsh-worker.env` | — | — | — | named as a candidate root in the brief | **NOT PRESENT** | `secratary-ts: ls -la /etc/dsh-worker.env` → `No such file or directory`. Nothing to move |
| 23 | `/home/zabz/lpt-books`, `lpt-db-dumps`, `lpt-rebuild`, `lpt-sweep`, `lpt-w12`, `lpt-device-owner`, `lpt-hub-shadow-artifact-20260914` | data/scratch | 153 M + 88 M + 524 K + 4.6 M + 36 K + 24 K + 28 K | no | no cron payload and no app ref reaches any of them | **RETIRE** | nothing |

---

## §2 — THE ORDERED MUST-MOVE LIST

Ordered by **how loud the absence is today**. Every entry carries the exact source path, the exact
recommended destination on `secratary-cloud`, the measured size, and the command I would use —
**stated, not run.**

**On destination paths.** The code does not care where the cloud box keeps things; it cares where
`.env` and the scripts say things are. Two consistent answers exist, and mixing them creates the
exact class of fault this document is about. I recommend **preserving the `/home/zabz/...` shape
verbatim on the cloud box**, because it is the only shape that requires **zero edits** to 87 cron
payloads, 128 app files and 301 `.env` keys, and because those strings are already written into the
authority database's own history. `/home/zabz` is a single directory on the cloud box today with one
subdirectory in it, so nothing collides. Where a move *must* differ (the QB repo) I say so and give
the reason.

| # | what | exact source (office) | exact destination (cloud) | size | command I would use (STATED, NOT RUN) |
|---|---|---|---|---|---|
| **1** | **quickbooks-agent repo** — unblocks 3 failing syncs and 5 services | `secratary-ts:/home/zabz/repos/quickbooks-agent` | `/home/zabz/repos/quickbooks-agent` **and** set `.env:QB_AGENT_REPO_PATH` to that path | **282 MB** (275 MB of it `node_modules`) | `rsync -a --info=progress2 --exclude '.git/' --exclude 'node_modules/' secratary-ts:/home/zabz/repos/quickbooks-agent/ /home/zabz/repos/quickbooks-agent/` then `npm ci` **on the cloud box** (do not ship `node_modules` built for the office box). **Blocker:** cloud cannot authenticate to GitHub today — copy `.git-credentials` first (§3) or rsync the working tree. |
| **2** | **the CFO ledger** — the money record | `secratary-ts:/home/zabz/accounting-data/live/accounting.db` (+ `books.db`) | `/root/accounting-data/live/accounting.db` — resolving `~` to the API's `HOME` | **22 MB + 26 MB** | Take a **consistent** copy, never a hot file: on the office box `sqlite3 accounting.db ".backup /tmp/acc.db"` is a *read* but is a full-table copy — **do it only if the office load is under 1**, else stop. Prefer: `rsync -a secratary-ts:/home/zabz/accounting-data/live/accounting.db /root/accounting-data/live/accounting.db.new` then verify with `PRAGMA integrity_check` before replacing. **Back up the cloud's existing 16 KB stub first** — it has been receiving `balance_snapshots` writes since 05:41Z. |
| **3** | **the app's own scripts delta** | `secratary-ts:/home/zabz/personal-secretary-mvp/scripts/` | `/opt/company/scripts/` (same repo) | **~5 MB delta** | `rsync -a --exclude '__pycache__' secratary-ts:/home/zabz/personal-secretary-mvp/scripts/ /opt/company/scripts/` — but prefer `git fetch` on the cloud's own `/opt/company` clone so the tree stays a git checkout. Cloud currently has 359 files in `/opt/company/scripts`; the office has more. |
| **4** | **`bin/` — the 427 tools every cron job wraps** | `secratary-ts:/home/zabz/bin/` | `/home/zabz/bin/` | **25 MB**, 427 files | `rsync -a --exclude '__pycache__' --exclude '*.bak-*' secratary-ts:/home/zabz/bin/ /home/zabz/bin/`. **71 unpushed commits** in `bin.git` — check those land before treating the office copy as backup. |
| **5** | **harness-config** — journal, archive, phone, ops | `secratary-ts:/home/zabz/code/harness-config/` | `/home/zabz/code/harness-config/` | **1.6 GB** | `git clone` from the remote if reachable, else `rsync -a --exclude '.git/objects/pack' …`. **71 unpushed commits** — those must be pushed to `harness-config.git` or carried in the rsync; losing them loses the estate's memory. |
| **6** | **the raw transcript archive** | `secratary-ts:/home/zabz/lpt-transcripts/` | `/home/zabz/lpt-transcripts/` | **2.6 GB** | `rsync -a --info=progress2 secratary-ts:/home/zabz/lpt-transcripts/ /home/zabz/lpt-transcripts/` — 256 object shards + `manifest.sqlite`; run it **once, not on a schedule against the office box** (RULE 1). |
| **7** | **`.secrets/`** | `secratary-ts:/home/zabz/.secrets/` | `/home/zabz/.secrets/`, mode 700 | **36 KB** | `scp -p secratary-ts:/home/zabz/.secrets/* /home/zabz/.secrets/`; verify `chmod 700` on the dir and `600` on each file. Names and consumers in §3. |
| **8** | **ssh keys + config** | `secratary-ts:/home/zabz/.ssh/` | `/home/zabz/.ssh/`, mode 700 | ~300 KB | Copy only what the company uses: `id_rsa_linux_pc` (`.env` demands it at exactly that path), `id_ed25519_hetzner`, `ha-mesh-key`, `id_ed25519_mesh`, `config`. **Do not** copy `authorized_keys` wholesale without review. |
| **9** | **git credentials** | `secratary-ts:/home/zabz/.git-credentials` | `/home/zabz/.git-credentials`, mode 600 | **1.1 KB** | `scp -p` then `chmod 600`; verify with `git ls-remote` — **this is the item that currently blocks item 1's clone**. |
| **10** | **ceo-kernel + its var store** | `secratary-ts:/home/zabz/ceo-kernel`, `/home/zabz/ceo-kernel-var`, `ceo-kernel.git` | same paths | ~50 MB est. (**unmeasured**) | `rsync -a secratary-ts:/home/zabz/ceo-kernel/ /home/zabz/ceo-kernel/` and the same for `ceo-kernel-var/` and `ceo-kernel.git/`. |
| **11** | **the missing app `data/` subdirectories** | `secratary-ts:/home/zabz/personal-secretary-mvp/data/{briefings,waze-mdm,voice_recordings,voice_tts,code_snapshots,skills,tools}/` | `/opt/company/data/` (same names) | **113 M + 86 M + ~3 M** | `rsync -a secratary-ts:/home/zabz/personal-secretary-mvp/data/waze-mdm/ /opt/company/data/waze-mdm/` and so on per subdir. Cloud's `waze-mdm`/`voice_recordings` are 4 KB empty stubs — rsync decides per file. |
| **12** | **`node/` runtime** (or repoint two cron jobs) | `secratary-ts:/home/zabz/node/` | `/home/zabz/node/` | **unmeasured** | Cheaper: point `push-dsh-sessions` and `profile-gate` at the cloud's own `/usr/bin/node` (v20.20.2, measured) and **do not move a runtime**. If parity matters, `rsync -a` the tree. |
| **13** | **bank browser sessions** | `secratary-ts:/home/zabz/accounting-data/browser-auth/` | `/root/accounting-data/browser-auth/` | **5.7 GB** | `rsync -a --info=progress2 secratary-ts:… /root/accounting-data/browser-auth/`. **Requires headroom and the move is all-or-nothing:** a partial profile set is worse than none — it produces silent login failures instead of a clean re-auth. Only do this once disk is verified above ~15 GB free. |
| **14** | **`lpt-hub` checkout** | `secratary-ts:/home/zabz/repos/lpt-hub` | `/home/zabz/repos/lpt-hub` | **3.7 GB** | Prefer `git clone https://github.com/lakewoodphone/lpt-hub.git` on the cloud box (needs item 9). 8 dirty files and 0 unpushed commits on the office copy — the dirty files must be carried or reviewed. |

**Total for items 1–13, excluding `browser-auth`:** ≈ **4.7 GB**. **With** `browser-auth`: ≈ **10.4 GB**.
Against the 27 GB measured free at 06:22Z that fits. Against the 4.4 GB measured at 06:10Z **it does
not** — items 13, 14 and 6 would have to wait. **Re-measure `df -h /` immediately before starting and
believe the fresh number.**

**What will not fit on this disk under any reading:** `/home/zabz/secretary-backups` at 199 GB, and
`/home/zabz/repos` in full at 15 GB if `browser-auth` also moves. Both are addressed in §4.

---

## §3 — CREDENTIALS AND SECRETS (names and locations only — never a value)

Every entry: **name · location · mode · what depends on it.** No value is reproduced anywhere in this
document.

### Already satisfied on the cloud box — verify, do not re-copy

| name | office location | cloud location | depends |
|---|---|---|---|
| R2 offsite credential (`R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`) | `/home/zabz/.lpt-r2.env` 600 | **`/root/.lpt-r2.env` 600** | `authority-offsite-backup.sh`, `report-offsite-age.sh`, `company-offsite-push.sh` |
| the app's whole environment | `/home/zabz/personal-secretary-mvp/.env` 600, **301 keys** | `/opt/company/.env` 600, **302 keys** | everything |
| Google Calendar / Gmail token dirs | `data/calendar_tokens`, `data/gmail_tokens` | **present, 24 KB each** | calendar + Gmail decision queue |

**Key-name diff result: the two `.env` files have IDENTICAL key names; the cloud adds exactly one,
`DATABASE_URL=sqlite:////root/authority.db`.** So **no credential name was lost in the cutover** — the
gap is entirely in *path values* and in *files that never moved*. That is a materially different and
much better starting position than "credentials went missing", and it means the fix is rsync plus one
`.env` value, not re-provisioning secrets.

### Must be brought over

| name | location (office) | mode | what depends on it |
|---|---|---|---|
| `cloudflare-api-token`, `cloudflare.env` | `/home/zabz/.secrets/` | 600 | `cloudflare` DNS/tunnel jobs; `CF_*` keys already present in cloud `.env` |
| `escape101-twilio.env`, `twilio-lakewood.json` | `/home/zabz/.secrets/` | 600 | Escape101 line; the SMS/Twilio surface |
| `dialpad-ui-headers.b64` | `/home/zabz/.secrets/` | 600 | Dialpad UI crawl (`RECONCILIATION_DIALPAD_UI_CRAWL_MODE`) |
| `lpt-nj-employer-access.env` | `/home/zabz/.secrets/` | 600 | NJ employer payroll access |
| `desk-2026-09-25-documents.env` | `/home/zabz/.secrets/` | 600 | desk document automation — **consumer unconfirmed (§5)** |
| `bitlocker-ZABZ-TECH-C.recovery.txt` | `/home/zabz/.secrets/` | 600 | recovery of the office desktop C: volume — **this is office-hardware custody, not company function**; decide deliberately |
| `.git-credentials` | `/home/zabz/` | 600 | every `lakewoodphone/*` clone and push; **currently blocking the QB clone** |
| `id_rsa_linux_pc` (+ `.pub`) | `/home/zabz/.ssh/` | 600 | `LINUX_PC_SSH_KEY_PATH` in cloud `.env` — **measured ABSENT on cloud** |
| `id_ed25519_hetzner`, `id_ed25519_lpt-apps`, `id_ed25519_mesh`, `ha-mesh-key` | `/home/zabz/.ssh/` | 600 | Hetzner/lpt-apps/survivor SSH; mesh; Home Assistant |
| `/home/zabz/.dsh/.credentials.yaml` | `/home/zabz/.dsh/` | — | the DSH engine's own provider credentials. **Name recorded; contents not read.** Whether the cloud box needs a DSH engine at all is a design question, not an inventory one |

### Not a secret but written as one — a defect worth naming

`/home/zabz/.ssh/` contains **two files both named `authorized_keys`** (`ls -la` shows two identical
names in one directory, 1544 B and 10 B). That is only possible if one of them contains a character
that renders identically but is not the same byte. A file whose name is not what it appears to be is
a trap for whoever migrates this directory next.

---

## §4 — WHAT SHOULD BE LEFT OR RETIRED

**LEAVE — the 199 GB of `secretary-backups`.** Not "leave permanently": **leave off this disk.**
Evidence: 199 GB against a 75 GB volume is arithmetically impossible, and R2 already holds
`authority/secretary.db.gz` plus `authority/accounting.db.gz` with a sha256 sidecar
(`docs/mesh/131-MIGRATION-BRIEF.md`). The office copies are the *second* copy, not the only one —
the only-copy question applies to `lpt-transcripts`, not to snapshots. **This is a real continuity
decision and it is the owner's, not mine:** today the company's retention lives on a box it is
forbidden to touch, and a retention story that depends on a frozen machine is not a retention story.
The question is put once, at the end of this document, in the owner's own terms.

**RETIRE — 3.2 GB `kyocera-escalator`.** Zero references anywhere in `/opt/company/app` or
`/opt/company/scripts`, no cron payload, no `.env` key. It is the single largest item I can prove is
unused. Has a GitHub origin, so retiring the local copy costs nothing recoverable.

**RETIRE — `personal-secretary-mvp/domains/finance/quickbooks-agent` (272 MB).** It contains
`node_modules` and **no `package.json`** — the exact shape that makes `_qb_repo()`'s
`_has_npm_scripts()` check fail. Copying it would reproduce the current failure while looking like a
fix. Delete it on the office side only after the real repo is migrated and `QB_AGENT_REPO_PATH`
verified.

**RETIRE — the detached worktrees and scratch forest under `/home/zabz/`** (`wt-562-*`, `wt-563-*`,
`_mig_*`, `_hc_*`, `_verify*`, `_converge-*`, `_git-backup-*`, `_kaf*_wt`, `_lpt447_wt`, `_scratch`,
and files named `300`, `NUL`, `SELECT 1;`, `]*`, `\=ro`, `C:\Users\ezabz…`). Evidence: the only
app-tree references to the worktrees are inside **test files** (`test_work_generation.py`,
`test_lpt_sync_precreate_guard.py`, `test_cost_enforcement.py`, `test_department_tools.py`), i.e. the
paths leaked into tests rather than the tests depending on real state. These are the leavings of
ended sessions. Nothing schedules, reads or backs them up.

**LEAVE — office-hardware and session state:** `/home/zabz/.config` (4.3 GB), `.dsh` (820 MB),
`.cache`, `.npm`, `.vscode-server`, `.platformio`, `.swiftpm`, `.copilot`, `.local`, `.deployments`.
Bound to a desktop session that does not exist on the cloud box. Copying `.config` alone would move
4.3 GB of browser and editor profiles the company never reads.

**LEAVE — the office-only LAN surface.** Three cron jobs address `192.168.50.34`/`192.168.50.23`
directly (`check-security-absence`, `run-ha-truth`, `run-ha-behaviour`) and `HA_URL` is
`http://homeassistant.local:8123`. Home Assistant is physically at the office; a cloud job cannot
watch a LAN device over a tunnel that is itself the thing being monitored. These belong to a
different workstream than mine, and I flag them only so they are not silently "migrated" into jobs
that can never pass.

**RETIRE — `financial_alert_sweep`'s current reading and 2 other stale states.** `balance_capture`
and `spending_report` are already `disabled` in `autopilot_state.json` and their commands reference
`/home/zabz/personal-secretary-mvp/C:/Users/ezabz/Code/personal-secretary-mvp/_scratch/one-shot-utils/…`
— a **Windows path concatenated onto a Linux path**, which can never resolve on either machine
(42 `No such file or directory` records in the state file). Do not migrate these entries; they are
already-broken history.

---

## §5 — WHAT I COULD NOT DETERMINE

1. **The credential exposure I caused is not fully bounded.** My first helper printed values for
   keys I had not intended to select. Those values are in this session's transcript. **I did not
   enumerate which keys leaked**, because enumerating them means printing them again. Recommended
   response: treat every secret in `/opt/company/.env` whose name does not end in `_PATH`/`_DIR`/
   `_REPO` as potentially exposed, and rotate. The specific families I saw pass by were provider API
   keys and at least one database DSN. **This is the most urgent thing in this document and it is not
   a migration item.**
2. **Exact sizes of `ceo-kernel`, `ceo-kernel-var`, `ceo-kernel.git`** — I did not run `du` on them.
   Estimated ~50 MB. **Unmeasured.**
3. **Total size of the `/home/zabz/` scratch forest.** Deliberately not measured: a `du` across the
   several hundred top-level entries would be the kind of long disk-touching pass RULE 1 forbids.
   The individual pieces I could see range from kilobytes to ~400 MB (`_worktrees`).
4. **Whether `mail`-style or other push channels still matter.** The preserved crontab carries the
   comment that a previous checker piped to `mail`, which does not exist on that host. There may be
   more scheduled jobs whose only effect was a log line nobody reads — that is a *value* judgement,
   not a mechanical one, and I can only see the commands, not their effect.
5. **`desk-2026-09-25-documents.env`** — which tool consumes it. It exists, is 600, and I found no
   reader in `/opt/company/app` or the cron payloads. Possibly a consumer on a different machine.
6. **Whether the cloud's `/root/accounting-data/live/accounting.db` stub has received writes that
   are NOT in the office ledger.** It has `balance_snapshots` and a `sqlite_sequence` row, and it was
   created at 05:41Z (three minutes after `company-api` started). If any snapshot was captured on the
   cloud since the cutover, a naive overwrite from the office would **destroy it**. I recommend
   diffing the two `balance_snapshots` tables before replacing, and I could not do that diff without
   reading both files, which is out of scope for an inventory.
7. **The office box's own `cron.service` state and its 5 active systemd timers.** Another workstream
   (`132-CRON-INVENTORY.md`) measured these. I did not re-measure them and I do not restate their
   numbers as mine.
8. **Whether `/home/zabz/node` differs in version from the cloud's `node v20.20.2`.** Not measured.
9. **`.dsh/.credentials.yaml` contents** — deliberately not read. Its existence is recorded, its
   consumer unknown.
10. **Why the cloud's free space moved from 4.4 GB to 27 GB during this work.** I observed it twice
    with `df -h /` and did not cause it. Until that is explained, any plan that assumed "4 GB free"
    is built on a number that has already changed once underneath it.

---

## §6 — THE ONE QUESTION THIS RAISES FOR THE OWNER

Everything in §2 is engineering, and I would execute it without asking. One thing in §4 is not mine:

**The company's 199 GB of database snapshots exist only on a machine we are forbidden to touch.**
R2 holds the two current copies, so nothing is lost *today* — but retention, pruning and the
ability to go back more than one snapshot now depend on a frozen 2013 desktop in an office.

The options are (a) extend retention in R2, which is cheap and removes the office box from the
retention story entirely; (b) keep the office copies as the long tail and accept that they are
unreachable and unmaintained; or (c) copy a bounded recent slice (say the last 14 days) to the cloud
box, costing roughly 20-30 GB of the 27 GB free and re-creating exactly the disk pressure the
cutover was meant to relieve.

**I recommend (a): extend retention in R2.** It is the only option that makes retention independent
of a machine nobody may touch, it costs storage rather than a server, and it is the one the estate's
own history already points at — the skill that exists because an agent once proposed buying a
Storage Box this estate did not need.
