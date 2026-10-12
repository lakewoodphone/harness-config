# 164 — `production-comms-freshness` WAS FAILING ON A FROZEN WRITER: DIAGNOSIS, AND THE FIX PROVEN AT 22:45:01Z

**Author:** mesh child agent on **ZABZ-YOGA** (Windows), thread `remote-bd0c2c32-a8f3-4de8-9094-d95eaf2c794b`,
2026-10-11 22:20Z–22:50Z. **Companion to `155`** (same conclusion on the crux; `155` stopped before naming the
lost job or testing a fix). All commands read-only against `secratary-cloud`. `/root/authority.db` was opened
**only** as `file:…?mode=ro, uri=True`. Nothing was restarted, stopped, enabled, disabled or masked on any
machine; the office box (`secratary-ts`) was not touched at all in this workstream.

> **File-number note.** Two agents wrote a `164-*` file at ~22:43Z (I saw
> `164-FROZEN-OFFICE-LAST-WRITER-AND-THE-CONFIG-THAT-FACED-THE-OLD-WORLD.md` appear beside mine). Nothing was
> overwritten — distinct filenames. The `164-live-state*.txt` files are my raw command output.

**Subject:** `production-comms-freshness`, cron `*/15`, `rc=1` every run from `2026-10-11T17:30:02Z` to
`22:30:01Z`.

**VERDICT.** The check was **not** broken and the website was **not** stale. It was correctly reporting the
absence of the job that advances `website_sync_cursor` — **`website-comms-push-cron`, one of the ~40 jobs in
`153-LOST-JOBS-WORKLIST.md` that never moved in the cutover.** That job was ported and its first successful
scheduled run was **`2026-10-11T22:39:01Z` rc=0**. The very next tick of the monitor,
**`2026-10-11T22:45:01Z`, is rc=0** with `"problems": []`. **The monitor's code was not changed and must not
be.** The fix was never in the monitor.

---

## 1. What the check compares, and the real numbers

Script `/usr/local/bin/production-comms-freshness.py` (read in full on the box). Per `sync_type`:

```
behind_local_hours = (MAX(local row) - website_sync_cursor.last_synced_at) / 3600     # fails if > 2.0
```

| side | what it is | where it lives |
|---|---|---|
| **A, "the local store"** | `MAX(created_at)` of `dialpad_sms_cache` (pushable filter) · `MAX(date_started_ms)` of `dialpad_call_full` | **`/root/authority.db`** (cron sets `FRESHNESS_SECRETARY_DB=/root/authority.db`) |
| **B, "the website"** | `website_sync_cursor.last_synced_at` — **the last time the push completed**: not a reading of the website, but the pusher's own bookkeeping | **the same `/root/authority.db`** |
| (C, the real website) | `COUNT(*), MAX("createdAt")` of the website's Postgres `communications` | website Postgres via `PHONE_TECH_FULL_*`, opened `readonly=True` |

**Both sides are in `/root/authority.db`.** The check was **not** comparing against the frozen office box and
**not** against the 1.8 MB `/opt/company/data/secretary.db` cutover stub. The "pre-cutover path" hypothesis is
false for the *store* and true for the *writer* (§3).

Measurement C can only ever **add** a problem (it is gated on the website itself being stale), which is why it
stayed silent the whole time the website was in fact fresh.

**Numbers at the last red tick, `2026-10-11T22:30:02Z`** (`/root/.lpt-recon/production-comms-freshness.json`):

| | value |
|---|---|
| `dialpad_calls.cursor` | `2026-10-11T15:11:48.403398+00:00` (frozen since 15:11:48Z) |
| `dialpad_sms.cursor` | `2026-10-11T15:11:53.128402+00:00` (frozen since 15:11:53Z) |
| `cursor_age_hours` | **7.3** |
| `behind_local_hours` | **6.78 h** (calls) · **6.29 h** (sms) |
| `local_newest_call` | `2026-10-11T21:58:32.366000+00:00` |
| `local_newest_sms` | `2026-10-11T21:29:21.719000+00:00` |
| **`website.newest`** | **`2026-10-11 21:29:21.719000`** — *exactly equal to the local newest sms* |
| **`website.newest_age_hours`** | **1.01 h** at that tick, and 0.01 h at 21:15Z |
| `website.rows` | 126 117 |
| `problems` | 2 × "the website is Xh behind the local store … **this is the 2026-09-15 failure shape**" |

`151`'s quoted message *"website 5.25 h behind local store"* is `behind_local_hours` from the **20:30:01Z**
tick. It is not a statement about the website's contents, and reading it as one is how this job was mis-triaged
for four hours.

**Command** (`secratary-cloud`, read-only):

```
/opt/company/.venv/bin/python /usr/local/bin/production-comms-freshness.py     # writes the STATE json below
cat /root/.lpt-recon/production-comms-freshness.json
```

## 2. Real lag, or wrong measurement? — THE CRUX

**Wrong measurement, provable from the check's own output.**

- `website.newest` tracked live traffic within seconds on every tick: 20:09:26Z · 20:23:25Z · 20:38:11Z ·
  20:51:44Z · 21:14:44Z · 21:29:21Z, with `rows` climbing 126 101 → 126 104 → 126 108 → 126 110 → 126 113 →
  126 117. A store cannot be "5–7 h behind" a copy that is moving.
- At the 21:15Z tick the website's newest row was **1.865 s NEWER** than the local original
  (`21:14:44.814` vs `21:14:42.949`).
- At the 22:30Z tick `website.newest` was **byte-identical to `local_newest_sms`** — the website held the local
  original itself.

Meanwhile `behind_local_hours` grew **exactly 1 h per hour**, because the cursor it is subtracted from did not
move. The failure time is therefore a **pure function of the freeze time plus the 2 h threshold**:

```
cursor froze           2026-10-11T15:11:48Z
threshold              2.0 h
last green tick        17:15:02Z
FIRST FAILURE          17:30:02Z      <-- exactly 15:11:48Z + 2 h, to the tick
```

Four green ticks on the cloud, then red forever, with no intermittency — and the transition lands exactly on the
arithmetic. No other explanation is needed and none is available.

**This is the mirror image of the 2026-09-15 defect the script was written to prevent.** That one watched a
clock that **always moved** (the local webhook receive time) and so never noticed a silent website. This one
watched a clock that **stopped** and so alarmed forever about a website that was fine. Both are clock mistakes;
the second was introduced by the port meant to fix the first. The monitor was producing a **false alarm, not a
false negative** — it was loud while the website was fresh, for ~18 consecutive runs.

## 3. What was actually not syncing — and it is in the lost-jobs list

**The writer of `website_sync_cursor`.** That table is written **only** by `_update_sync_cursor(db_url, …)` in
`/opt/company/app/services/website_db.py` (called at lines 1892, 2006, 2112 from
`sync_dialpad_calls_to_website` / `sync_dialpad_sms_to_website` / `sync_dialpad_voicemails_to_website`). Those
three are reached from exactly two places on the cloud box:

1. `/opt/company/app/services/daily_reconciliation.py` (in-process, on the autopilot's own ~24 h interval), and
2. **`website-comms-push-cron`** — the scheduled clock.

**`website-comms-push-cron` never moved to the cloud.** On the office box it was crontab line 49,
`9,39 * * * *` → `/home/zabz/bin/website-comms-push-cron.sh` (480 runs, 69 non-zero, **last
`2026-10-11T03:39:04Z`**). It is named in:

- **`153-LOST-JOBS-WORKLIST.md`** line 31 — in the ~40 that "never ran on the cloud";
- **`151-VERIFY-CLOUD-AUTHORITY.md`** §5 — in the 27 with no cloud home, which draws the conclusion directly:
  *"the job that would close that gap — `website-comms-push-cron` — is one of the 27 missing"*;
- **`132-CRON-INVENTORY.md`** line 131 — classified **PORT-ADAPT**.

**So the check was correctly reporting the absence of a job that should have been ported. The finding was the
diagnosis, and no code in the monitor should change.** That is the answer to the question the dispatch asked.

**Why the website stayed fresh anyway:** the push is also reachable in-process via
`daily_reconciliation.py:1638/1647` and `:2211/2216` from `company-api`'s autopilot
(`AUTOPILOT_INTERVAL_SEC=900`) — the same cron-vs-autopilot overlap `132` §1c records for `plaid_sync` and
`owner_attention_sweep`. So the customer-facing data kept moving while the cron-side clock the monitor reads had
no writer. The monitor's invariant — *the cursor advances whenever the local store does* — held on the office box
because the cron job enforced it. On the cloud box nothing did.

## 4. The fix that landed, and the proof

| when (UTC) | event |
|---|---|
| 21:29:01Z | coordinator installed the cron line: `9,39 * * * * /usr/local/bin/cron-wrap.sh website-comms-push-cron …` → `/root/bin/website-comms-push-cron.sh`; backed up the crontab to `/root/crontab.before-website-comms-push-20261011T212901Z` |
| 21:39:01Z | `website-comms-push-cron` **rc=1, 90 s** — the wrapper's `PUSH=` target `/root/bin/website-comms-push.py` did not exist yet |
| 22:09:02Z | `website-comms-push-cron` **rc=1, 90 s** — still absent |
| 22:16 | `/root/bin/website-comms-push.py` installed, 15 788 B, sha256 `0bca268febecdb9630f4469b23bf19dee88e1202eff0b8f614a08eb78376fca9`; `sys.path.insert(0, "/opt/company")`, `ENV_FILE = "/opt/company/.env"` |
| **22:39:01Z** | **`website-comms-push-cron` rc=0, 9 s** |
| 22:39:05.830Z / 22:39:10.245Z / 22:39:10.334Z | **cursor advances**: `dialpad_calls` · `dialpad_sms` · `dialpad_voicemails` |
| **22:45:01Z** | **`production-comms-freshness` rc=0, 2 s** — `"problems": []`, `"ok": true` |

The 22:45:01Z state, verbatim from `/root/.lpt-recon/production-comms-freshness.json`:

```
"dialpad_calls": {"cursor": "2026-10-11T22:39:05.830259+00:00", "cursor_age_hours": 0.1, "behind_local_hours": 0.01}
"dialpad_sms":   {"cursor": "2026-10-11T22:39:10.245467+00:00", "cursor_age_hours": 0.1, "behind_local_hours": -0.13}
"website":       {"rows": 126211, "newest": "2026-10-11 22:39:10.323000", "newest_age_hours": 0.1}
"problems": []
"ok": true
```

and the job's own log: `production comms freshness — 2026-10-11T22:45:01+00:00 … fresh`.

**This is a proof by the job's own scheduled tick in `/root/.cron-status/runs.tsv`**, not a hand-run:
`…T22:39:01Z  website-comms-push-cron  0  9` and `…T22:45:01Z  production-comms-freshness  0  2`. The prediction
in §2 (cursor restored ⇒ green) is confirmed, which is what closes the diagnosis rather than merely asserting it.

The diagnosis I recorded before the fix landed is preserved verbatim as `164-PRODUCTION-COMMS-FRESHNESS-LOST-WRITER.md`
(uploaded 22:38Z, before the 22:39 tick) — so the fix is not a retrofit of the story to the outcome.

## 5. ONE RESIDUAL DEFECT IN THE PORTED WRAPPER — a false-green waiting to happen

**`/root/bin/website-comms-push-cron.sh` line 50 reads the wrong database:**

```
sqlite3 "file:$REPO/data/secretary.db?mode=ro"      # REPO=/opt/company
```

On the cloud box `/opt/company/data/secretary.db` is the **1.8 MB cutover stub** (145 tables). Measured
read-only at 22:46:40Z: it **has no `dialpad_call_full`** (it does have `dialpad_sms_cache`; it has **no
`website_sync_cursor`**). The wrapper's own sanity query therefore fails with
`Error: in prepare, no such table: dialpad_call_full` and `sqlite3 rc=1`; `2>/dev/null || echo "-1"` turns that
into `have=-1`, and the gate's condition `[ "$cand" = "0" ] && [ "${have:-0}" -gt 0 ]` is **never true**.

So the sanity gate — the whole reason the wrapper exists, per its own header: *"a green result that means 'I
could not read anything' … the signature defect of this system"* — **cannot fire on the cloud box.** A run whose
readers return an empty list because the authority is locked would report `ok: true, synced: 0` and `exit 0`,
and `production-comms-freshness` would report `fresh` off a cursor the same broken run had just advanced. It is
the same class as `cron-script-guard`'s "green while blind" in `151` §1.

The same query against the authority returns **1610**, i.e. the gate would work if pointed correctly.

**The one-line change, owned by the workstream that installed the wrapper (coordinator, 21:41Z):**

```
-  sqlite3 "file:$REPO/data/secretary.db?mode=ro" "
+  sqlite3 "file:/root/authority.db?mode=ro" "
```

(`/root/authority.db` is the only writer's database; this read stays `mode=ro`. Note the wrapper is currently a
plain `wc -c` 4187-byte file with mode 755 and is **not** the same bytes as
`/root/code/harness-config/scripts/website-comms-push-cron.sh`, so the change must be made on the installed file
and then reconciled back into the repo.)

**Not fixed here deliberately:** it is a second, independent defect in a job another workstream owns, the monitor
is green, and a change to the pusher while it is the only thing keeping the cursor moving would risk the green
state that is the deliverable of this workstream. Reported instead, with the exact diff and the measurement.

**Also unchanged and still holding:** the pusher's PCI exclusion — `dialpad_sms_cache` message_id
`6252044111880192` (full card number, expiry, CVV, ZIP) is withheld from production pending the owner's answer on
queue item 67. **Never pass `--include-pci` as part of any future work on this job.**

## 6. A CORRECTION I OWE THE RECORD — the "hung cloud box" I reported at 22:36Z was wrong

Mid-session I recorded that `secratary-cloud` had stopped running external commands (`echo` worked, `date`/`ls`
never returned) and that this blocked the fix. **That diagnosis was wrong and I withdrew it before it reached
this file as a finding.** An independent child agent probed the same host at 22:35–22:39Z:

- the exact command returned in **1.0 s** (`PING` / `Sun Oct 11 10:35:10 PM UTC 2026`), and `uptime`, `free -m`,
  `cat /proc/loadavg`, `ps`, `find` and an **80-iteration fork loop (`FORK_80_OK`)** all returned in 0.6–1.9 s;
- **0 zombies, no D-state, 0 failed units**, `ulimit -u` 26820, 274 threads, pid_max 4194304 — fork/pids
  starvation **disproven**;
- the hangs were **my client**: this estate's ssh channels do not reliably close after the remote command exits
  (the defect the dispatch itself warns about), and PowerShell buffers until exit. Every "partial output" I saw
  was a *client* being killed, not a server that could not fork. The successful reads in §1–§5 were obtained by
  reading the pipe directly and by staging work to a file on the box.

What *is* real on that host, measured by the child agent:

- **3 kernel OOM kills today, all killing `python` (`company-api`)**: `05:47:24Z` (anon-rss 7 544 976 kB),
  `07:10:45Z` (7 121 188 kB), `15:17:30Z` (7 457 924 kB) on a **7 742 MB / 2 vCPU** box. `MemoryMax=infinity`,
  so the system-wide killer, not a cgroup cap. `company-api` restarted 11 s after the last one.
- At 22:38Z the current API process was already back to **983 MB RSS + 2.14 GB swap (3.82 GB cgroup)** after
  7.35 h, with **2.77 / 4.10 GB swap in use** — a leak signature recurring every ~5–8 h.
- The host's own `estate-monitor` warns `WARN oom_kills_24h=1.0` every ~2 min.

**`company-api` was not restarted by this workstream, and must not be restarted casually** (`131` Rule 5): the
binding constraint is memory, not CPU or disk, and that box has already OOM-killed the API once today.
**This is the most serious thing in this file**, and it is a separate workstream's problem, not this job's.

## 7. What I did NOT do / could not measure

- I did **not** install the fix. It was installed and/or completed by another writer between 22:09Z and 22:16Z
  (the coordinator workstream and/or the `161` workstream, both active on that box tonight). I established the
  provenance of the artefact that mattered — the installed file's paths and sha256, and the ledger rows either
  side of the fix — but I did not author it.
- I did **not** change, restart, stop, enable, disable or mask anything, on any machine.
- I did **not** touch `secratary-ts` (the frozen office box) in this workstream at all — no command of mine ran
  there. I did not read `/root/bytes` history for the second `164-*` file, and I did not verify whether two
  workstreams are concurrently editing `/root/bin/` (they are, per §5's note that the installed wrapper is not
  the repo's bytes).
- I did **not** measure the database effect of the pusher beyond the cursor and the website's `MAX("createdAt")`.
- Everything above carries the machine and the command that produced it, per `131` Rule 6. Where I could not
  measure, I have said "not measured" rather than guessed.

## 8. One paragraph

`production-comms-freshness` exited 1 because `website_sync_cursor.last_synced_at` in `/root/authority.db` froze
at `2026-10-11T15:11:48Z` and the check subtracted it from a local clock that kept moving, so it went red exactly
2 h later and stayed red. The check was not measuring the wrong store — it was measuring a frozen *heartbeat*,
not the website — and the website was never stale: it tracked live traffic within seconds and at one tick its
newest row was newer than the local original. The frozen value had no writer because **`website-comms-push-cron`,
the job that advances it, is one of the ~40 in `153-LOST-JOBS-WORKLIST.md` that never moved in the cutover**; it
was ported tonight, `/root/bin/website-comms-push.py` was placed at 22:16Z, its first scheduled run
**22:39:01Z rc=0** advanced the cursor, and the monitor's next own tick **22:45:01Z is rc=0 with
`"problems": []`**. **The monitor's code was correct throughout and was not changed.** One residual defect is
reported, not fixed: the wrapper's sanity gate reads the 1.8 MB cutover stub instead of `/root/authority.db` and
so can never fire.
