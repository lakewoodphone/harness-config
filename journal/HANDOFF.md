# HANDOFF — state of play, newest first

**Rule:** newest entry at the top. Every session that changed anything writes one before ending.
Format is fixed so a future self can skim it in seconds:

```
## YYYY-MM-DD HH:MM · <host> · <one-line title>
CHANGED     what is now different in the world
IN FLIGHT   what is unfinished, and where the thread is
BROKEN      what is known-broken right now
NEXT        the single most useful next action
EVIDENCE    files, commits, or commands that prove the above
```

---

## 2026-09-11 20:30 UTC · ZABZ-YOGA · The owner's phone now reaches the harness — and the gate meant to do that had never fired once

*(timestamps marked UTC are verified against the authority's clock; other entries on this page use local time)*

**CHANGED**
- `scripts/phone-gate.py` — the cold-visitor redirect now actually fires. The bug was mine and total:
  `request_line.partition(" ")` left `path = "/ HTTP/1.1"`, which matched nothing, so the gate relayed every
  request untouched and the owner's 401 *was* the bare engine. Its token now comes from `engine-<engine-port>.log`
  rather than newest-mtime across `engine-*.log`.
- `scripts/probe-phone.py` — **new**. Seven checks: cold visitor gets a link, the link redeems to a cookie, the
  document loads, **the websocket upgrades (101)**, the engine still fences a foreign Host, the same chain over
  real HTTPS through Tailscale Serve, and the public `/phone` link. Writes `~/.dsh-phone/probe.json` atomically
  and runs from cron every 5 minutes.
- `scripts/serve-phone.sh` — engine on **3089** behind the gate on **3086** (Serve publishes 3086; the public
  redirector is on 3087). Also stopped mislabelling the engine's port in its own output.
- `ck/sentinel.py · check_phone_endpoint` — rewritten to read the probe's verdict instead of dialing a socket. It
  used to dial the *gate's* port, so a dead engine behind a live gate measured healthy, and it never tested the
  behaviour that was broken. Missing or stale probe = absent evidence (medium), never green; a failing public
  link = medium; anything else failing = high.
- Exec bits for the python phone helpers moved into git — the third occurrence of L132.
- Journal: L130–L133, P40–P41, W20–W21, D30–D33.

**IN FLIGHT**
- The last unverified step is the owner's own iPhone: everything below is verified between machines, plus a real
  393×852 render. His confirmation is the only thing that closes it.
- `dsh_session_ingest.py` still has no application-level retry-on-locked. The observed `database is locked` was
  fixed by committing after the existence SELECT; the retry loop was planned and never written.
- `ps_mcp_server.py` still opens the company database read-write.

**BROKEN**
- Nothing on the phone path. Kernel: 12 checks, 5 needing attention — all five pre-existing
  (`tick_completion`, `attention_debt`, `agent_dead_weight`, `evolution`, `comms_freshness`).
- **P40 stands:** a phone outage is now *detected* and reaches nobody. Absent an inbox, the owner remains the
  sensor of last resort — which is how this was found.

**NEXT**
- `probe-phone.py` → a general `probe-endpoint.py` over a small registry (P41), so the API, Home Assistant, the
  Gmail bridge and the tunnel hosts get behavioural proof instead of layer checks.
- Give kernel findings a consumer (P40). Detecting a phone outage and the owner discovering it are different
  things, and only one of them is worth having.

**EVIDENCE**
- Commits: `389cd90` (gate parse — the fix that mattered), `b447bfb` / `0f0b422` / `22de4d3` / `2941c09`
  (probe, status file, token source), `408426e` / `353ece3` (kernel check).
- `python3 scripts/probe-phone.py` on the authority → **7/7 passed**, including `101 Switching Protocols` and
  `real HTTPS … 27,724 bytes, <title>DeepSeek Harness</title>`.
- Negative test, on purpose: engine killed → probe writes failures and `exit 1`; kernel reads
  `phone_endpoint ok=False severity=high needs_attention=True`, failing checks `2, 3, 4, 6`. Engine restarted →
  7/7, `severity=info`, `exit 0`.
- Outside-in from a different machine: `https://secratary.tail93e6e6.ts.net/` cold → 302 → cookie → 200; and
  `https://ai.abletelsolutions.com/phone` → 302 into the tailnet → 200, same title.
- A session created from the phone viewport then landed in the authoritative database:
  `dsh_sessions` = `secratary / c7de045c-4876… / preset zabz / 19 events / 7 frames / torn_tail 0`, FTS-searchable.
- Screenshots of the real 393×852 render: `docs/dsh-mobile/evidence/phone-{notice,app,session}-393.png`.

---

## 2026-09-11 20:45 · ZABZ-YOGA · The kosher filter's whole visual architecture is now designed and decided

**CHANGED**
- Five design documents in `kosher-filter-ai/docs/research/`: **015** (do we still need a custom modesty
  model — no), **016** (every on/off-device option + the decision agenda), **017** (cascade, deny-first,
  escalation, spot checking), **018** (per-region pixel hiding), **019** (supremely fast AND accurate).
  Sixteen verbatim evidence reports under `docs/research/responses/0*`.
- **Two decision documents: `decisions/33` (8 decisions) and `decisions/34` (23 decisions)** — 29 taken as
  engineering calls, 4 reserved for the owner. `docs/README.md` now indexes 015–019 so the record is navigable.
- **Verified from the code, which reframed everything:** the proxy classifies **no images at all**. It rewrites
  HTML only, forwards every image untouched, and the sole web-side hiding is an injected CSS rule blurring
  *every* image on a non-bypassed host at a global setting. The fast half of "supremely fast and accurate" is
  already maximal; **the accurate half is missing, not slow — there is no reveal path.**
- **Owner decisions taken (journal D22, repo `modesty-baseline-owner-decisions` §6):** Level 3 means **hide
  women**; who counts as a woman = **any female figure including girls**; **every policy is a configurable
  knob and a Level is only a default bundle**; and **cover on uncertainty, reveal on verification** with
  **per-region, never whole-picture** hiding.
- **Four research corrections to my own designs, all recorded rather than quietly edited:** the accessibility
  tree cannot enumerate un-laid-out content (so discovery moved to the proxy); token pruning is measured to
  destroy region-localization (−86% to −91%) while VQA barely moves; crop-*only* is worse than crop + whole
  frame (+8.7 points measured the other way); and `dHash` alone is the wrong cache key (PDQ-256 now).

**IN FLIGHT**
- **Two research streams still running:** overlay blur performance (sets `decisions/34` D34-07's API
  thresholds) and early-exit cascade curves with calibrated thresholds. Both are the last unclosed items in the
  objective, and both are "fold in when they land" rather than "blocked".
- The two owner questions queued but **not yet asked** (ask one at a time, per his instruction): how long a
  visible hold may last before it is a defect (recommend 150ms target / 400ms ceiling), and how much battery
  speculative prefetch may spend (recommend ~2–3%/hour, off below 30%).

**BROKEN**
- Nothing from this work. Carried over: three divergent `secretary.db` copies (P3), evolution loop (P4),
  `engineering_indexer` (P5), held messages (P6), manual `harness-config` sync.

**NEXT**
- Fold the last two streams in, then ask the owner's two questions one at a time. After that the buildable
  order is: invert the overlay TTL (a live safety hole where a blur expires and releases), build the
  perceptual-hash verdict cache (≈1 in 5 images is already decided), then the reveal path on the web.

**EVIDENCE**
- Commits on `kosher-filter-ai` main: `e0fef29` … `d0fae14`. Journal: D22, L57–L60.
- Owner decisions: `docs/modesty-baseline-owner-decisions-2026-09-09.md` §6.
- The four corrections: `019` §4, §10.1, §10.2 and `decisions/34` D34-03/19/20/16.

---

## 2026-09-11 20:32 · ZABZ-YOGA · Named callers' voicemails no longer vanish — and the drop was proven, not inferred

**CHANGED — the voicemail drop is fixed, deployed, and the running app is confirmed to have it.**

The defect was stated last round as a diagnosis. This round turned it into evidence and a fix:
`_DIALPAD_SUBJECT_RE` requires literal `(NNN) NNN-NNNN` digits, so a Dialpad notification reading
*"…has a new voicemail from **Caller Wireless** - 0:15"* returned `phone_e164 = None` and
`build_caller_card` returned `None`, discarding the whole notification. Corporate, toll-free and
some carrier callers present as names — the class we are least able to recognise — so the class
being thrown away was the worst one to lose.

**Proven both directions, not asserted** (`_scratch/comms-verify/prove_drop.py`, a probe using only
pre-existing imports so it isolates the bug rather than a missing symbol):
```
PRE-FIX  :  card is None : True    -> VERDICT: the voicemail was DROPPED
FIXED    :  card is None : False   -> card survives, PARTIAL, phone_e164 None,
                                      phone_display 'Caller Wireless'
```
*(My first attempt at this proof was worthless: I ran the new test file against the old code and it
failed with ImportError, not with the real defect. A test that fails for the wrong reason proves
nothing. The probe above is the corrected version.)*

**The fix.** `CallerCard.phone_e164` is now `str | None`; a new `parse_voicemail_caller_label()`
extracts a name when Dialpad sent no number; `build_caller_card` keeps the card, skips the
phone-keyed DB lookups, marks it **PARTIAL (never BLOCKED — a voicemail exists even when we cannot
call back)** and records exactly what is missing; `summary()` says "NO PHONE NUMBER in the
notification". 15 new tests in `tests/test_voicemail_named_caller.py`; **79 email/voicemail tests
pass**, and **95 pass** across department-tools, phone-tech, action-contract and the new file.

**Deployed and verified in the running process.** The first restart silently did nothing — I killed
pid `13760`, which did not exist; the real API was `2489011`, running code older than my edit. After
restarting the correct process (new pid `2504157`, health `ok=true`), a live action call proves the
new code is loaded, because the reply text changed:
> *"Fetched 2 session(s) (2 unhandled) — **session metadata only; message bodies are not available
> from this action** (read dialpad_sms_cache for conversation text)"*

**Also changed, same honesty problem:** `dialpad_pull_sms` is named for messages but returns
voice-bot **session metadata** — Dialpad's REST API has no SMS-body endpoint, so bodies live in
`dialpad_sms_cache`, filled by the Playwright crawler. The name stays (four call sites and a test
depend on it) but the tool description and the returned detail now say what it really returns and
name the table that has the text. That misnaming is precisely how the SMS gap stayed invisible.

**NOT DONE, and why — this is the honest remainder:**
- **`gmail_search` retry.** It failed twice with `Connection refused`, then succeeded on an identical
  call; it has not recurred in 8 subsequent calls, including after an API restart. I could not
  reproduce it and therefore could not verify a fix. Unverified change is worse than no change, so
  it is written down rather than guessed at. The `_api` helper already retries 3× over ~1.5s.
- **Scheduling the Playwright SMS crawl.** Requires a logged-in browser profile on a live business
  account; refreshing that auth is a risk I should not take unattended. SMS bodies remain
  fetch-on-demand. Recorded in `PAIN.md` P29.
- **Committing the three changed files.** They are live in the authority's working tree, which
  already carries someone else's uncommitted work (Shabbat/Shelly). I did not add to that tangle or
  `git pull` over it. Backups exist at `~/voicemail_handler.py.HEAD-backup` (pre-fix, 853 lines) and
  `~/voicemail_handler.py.fixed-copy`. **These should be committed by whoever owns that tree.**

**NEXT**
1. Get the three files committed (`voicemail_handler.py`, `chat_action_phone_tech.py`,
   `department_tools.py`) plus `tests/test_voicemail_named_caller.py`.
2. The 36 pending drafts remain the owner's call — asked, unanswered (`QUESTIONS.md`).
3. Watch `comms_freshness`: the 30-day lag median (17.5h) should fall over the next few days as the
   `*/30` harvest replaces the old once-a-day cadence.

**EVIDENCE**
- `python3 -m pytest tests/test_d014_email_triage.py tests/test_email_intake.py
  tests/test_voicemail_named_caller.py` → **79 passed** (authority, py3.14)
- `… tests/test_department_tools.py tests/test_chat_action_phone_tech.py tests/test_action_contract.py`
  → **95 passed**
- live `ps_action dialpad_pull_sms` → new wording present, so pid `2504157` runs the new code
- probe output above; `_scratch/comms-verify/{prove_drop.py,prove_drop_runner.py,prove_regression.py}`
- **Full-suite note:** a whole-suite run aborts in deepeval's `pytest_sessionfinish` with
  `OSError: Too many open files`. That is an environment/plugin limit, **not** a test failure —
  unaffected by this change. Targeted suites are the reliable signal until it is fixed.

---

## 2026-09-11 20:07 · ZABZ-YOGA · The call harvest now runs by itself — 17.5h → under 30 minutes

**CHANGED — the root cause is fixed and running unattended.**
`dialpad-harvest-cron.sh` is installed on the authority and fires `*/30`. Confirmed by an
**autonomous run at 20:01:36Z**: `read 236, stored 236, errors 0, 93.3s`, heartbeat written, nobody
touching it. Median call capture lag had been **17.5h**; call staleness went **10.0h → 21m**.

The harvester was never broken — a manual pass always read 236 calls with 0 errors in ~90s.
**Nothing was ever scheduled to run it**, and no CLI existed: it was reachable only as Python
`harvest_*` functions. That is the whole of P29.

**Four bugs I hit and fixed, every one of which only appears when the thing actually runs:**
| Bug | Symptom | Fix |
|---|---|---|
| CRLF in a `.sh` | `$'\r': command not found` on one line | strip CR + a guard that refuses to run on CRLF (L21) |
| `timeout N cmd <<EOF` | heredoc becomes **stdin**, so `timeout` waits on stdin and cannot kill a hang; run sat past 150s | worker written to a `mktemp` file, stamping progress per stage (L116) |
| SQLite contention | 21 × `database is locked`, 306s run — `busy_timeout=10000` means each contended write burns 10s (L115) | retry the idempotent pass: attempt 1 → 4 errors, attempt 2 → **0 errors** |
| `MAX(fetched_at)` as freshness | `fetched_at` is **INSERT-only**; 4 runs reported `stored 236` while no row carried a `fetched_at` past 19:31:32 | read the harvest's own heartbeat file (L114) |

That last one mattered most: it made a working job look dead *and* would have made a dead job look
fresh after any single insert. A staleness metric built on an upserted table is measuring the wrong thing.

**The check now reads honestly.** `comms_freshness` on the authority:
> *email 39m · sms 2.1h · call harvest 2m · capture lag 17.5h (30d median)* — the **only** remaining
> complaint is the draft queue.

**Alarm verified in all three states** (`_scratch/comms-verify/verify_heartbeat.py`): fresh → passes;
backdated 4h → `HIGH` *"call harvest has not completed in 4.0h (expected < 1.5h)"*; marker absent →
*"not configured here"*, **not** a false alarm (the `phone_endpoint` pattern). Two metrics are
deliberately reported-not-enforced with an explicit `*_budget_enforced=false` flag so a reader can see
they are context rather than health: the manual Playwright voicemail crawl, and the 30-day lag median,
which still carries the old once-a-day cadence and should converge over the next few days.

**BROKEN — found and diagnosed, NOT yet fixed: named callers' voicemails are silently dropped.**
`_DIALPAD_SUBJECT_RE` requires explicit `(NNN) NNN-NNNN` digits, so a subject ending in
"from **Caller Wireless**" yields `phone_e164 = None`, and `build_caller_card` returns `None` at
`voicemail_handler.py:653` — discarding the whole voicemail instead of degrading. Traced through
`email_actions.py:203`. Seen on 3 voicemails (09-08, 09-10, 09-11) against 6 that did create tasks.
Corporate and toll-free callers are exactly the ones that show up as names, and they are low-volume
callers we would not otherwise recognise — the worst class to drop. Fix sketch: add a `caller_label`
field to `CallerCard`, keep the card with no phone, skip the phone-keyed DB lookups, rate it `PARTIAL`,
and still create the task. **Wants tests before it lands.**

**Also not done, deliberately:** SMS bodies still come only from the manual Playwright crawl
(`dialpad_sms_cache` newest 17:50Z, no browser running). Scheduling the crawler needs a logged-in
profile and is a riskier change than the REST harvest, so it stays separate. `dialpad_pull_sms` still
returns voice-bot sessions rather than message bodies — misnamed, and that misnaming is how the gap
stayed invisible.

**NEXT**
1. Fix the named-caller voicemail drop (above) with tests — highest customer impact of what remains.
2. Schedule the Playwright SMS crawl, or state plainly that SMS bodies are fetch-on-demand.
3. The 36 pending drafts are the owner's call; asked, unanswered. See `QUESTIONS.md`.

**EVIDENCE**
- kernel commits `96406d9`, `75fdd32`, `7b63525`, `97cfe81`, `d69958d`, `b6fce71`
- `crontab -l` on `secratary`: `*/30 * * * * .../scripts/dialpad-harvest-cron.sh`
  (backup: `~/crontab.backup-20260911-193640.txt`); `~/dialpad-harvest.log` shows the 20:01:36Z
  autonomous ok; `~/.dialpad-harvest.last_run` = `2026-09-11T20:01:36Z`
- `python3 -m ck status --no-colour` on `secratary` → `[! ] comms_freshness`, 7 AUTHORITATIVE refs
- verifiers: `_scratch/comms-verify/{verify_heartbeat.py,run_on_authority.py,verify_comms_freshness.py}`

---

## 2026-09-11 20:00 · ZABZ-YOGA · His existing phone link now opens the harness — and my link never could have

**THE ERROR I MADE, worth writing down before the fix.** I designed the phone path around Tailscale Serve
and handed the owner a tailnet link — **without ever verifying his phone is on the tailnet.** It isn't.
`tailscale status` lists five devices: `secratary`, `lakewooechsmini`, `zabz-tech-linux`, `zabz-tech`,
`zabz-yoga-1`. **No iPhone.** So my link had nowhere to land, and my "verified end to end" was verified from
a *workstation on the tailnet*, never from the device it was for. `QUESTIONS.md` still had
"Tailscale-only, or a public login-gated endpoint?" open, and I built on the un-answered assumption.
*Rule this earns:* an endpoint's acceptance test has to be run from the client that will use it, or it is
not an acceptance test — it is a test of the path I happen to be standing on.

**WHAT HE ASKED FOR, and it is done:** his home-screen link should open the harness. It does.
`https://ai.abletelsolutions.com/phone` → **302** → `https://secratary.tail93e6e6.ts.net/` →
**HTTP 200, title "DeepSeek Harness"**, cookie minted, no reference to the old "Secretary Chat". Verified by
following the old URL with a cookie jar from the Yoga.

**How, in three pieces:**
1. `phone-redirector.py` — a loopback service that 302s into the harness and **reads the launch token from
   the engine log at request time**, so the link keeps working after the engine restarts and mints a new
   one. A static redirect would have broken the first time the engine bounced. 302 (not 301) for the same
   reason: the target must never be cached.
2. `serve-phone.sh` now starts it and the 10-minute cron watchdog keeps it alive.
3. The cloudflared ingress gained a path-scoped rule (`^/phone(/.*)?$` → `127.0.0.1:3087`) **before** the
   host-wide catch-all. Config backed up twice (`config.yml.bak-<stamp>`, `config.yml.pre-phone-route`),
   `tunnel ingress validate` → OK, and all three hostnames re-checked after the restart: `/phone` 302,
   `/` still 307 (dashboard untouched), `api /health` 200.

**Deliberately a redirect, not a proxy.** The harness refuses to be exposed — its own CLI rejects a public
bind because it *"would expose remote code execution to the network"* — and proxying would put that
capability on the public internet. Redirecting keeps the app reachable only by tailnet devices. The token
rides in the Location header so his first tap works; it is a bearer secret but **not a public capability**,
because the harness's host fence accepts it only on the tailnet authority.

**BUG CAUGHT WHILE BUILDING IT, the fleet's oldest trap:** the redirector never started, because
`pgrep -f "phone-redirector[.]py"` matched **the command line of the shell running the deploy itself**. The
guard concluded "already running" and skipped it. Fixed with a pidfile — *the fix is not a cleverer
pattern, it is not asking the question that way* (L28/L32, third occurrence in this fleet).

**WHAT THE OWNER NEEDS TO DO (his words: "besides the phone i can look at"):** add the iPhone to the
tailnet — Tailscale app, sign in as the tailnet account, VPN on. Nothing else. After that his existing
icon works; re-adding it from the tailnet URL gives a cleaner standalone app.

**STILL MINE, not his — and queued:** the 55+-commit production drift with ~510 lines of live uncommitted
work; `ps_mcp_server.py` opening the company database read-write; the leaked `DEEPSEEK_API_KEY` mitigation
(rotation itself needs his provider account); and the mobile-ergonomics pass on the harness UI.

**EVIDENCE**
- redirector: `curl -D- http://127.0.0.1:3087/phone` → `302` + `Location: https://secratary.tail93e6e6.ts.net/?token=…`
- tunnel: `cloudflared tunnel ingress validate` → OK; post-restart codes above
- the followed link: final URL `https://secratary.tail93e6e6.ts.net/`, title `DeepSeek Harness`, 27,724 bytes
- `tailscale status` on `secratary` (five devices, no phone) — the fact that invalidated my earlier claim

---

## 2026-09-11 19:45 · ZABZ-YOGA · The DSH session archive is in the authoritative database — the objective is closed

**CHANGED — the last item of the owner's three-part ask is delivered.**
Every DSH conversation, from all three machines, now arrives in `secretary.db` through the company's own
ingest endpoint. Verified end to end:

| Layer | Evidence |
|---|---|
| endpoint live | `401` without a token, `200` with — loopback **and** the public URL |
| backfill | **83 sessions, 19,866 stored rows, all FTS-indexed**; a search for `ticks_today` returns the phone engine's own *"200 ticks today (Sep 11, through 18:54…"* answer |
| three machines | `zabz-yoga` 68 sessions/18,472 rows · `zabz-tech` 11/1,268 · `secratary` 4/126 |
| scheduled | Windows tasks unchanged (the shipper's default transport is now `http`); the authority's cron runs `--transport http` against **loopback** |
| kernel | `session_archive` now reads the authoritative store: *"83 session(s) / 19,866 event(s) from 3 machine(s); newest 72s ago"* — it followed the data instead of going quiet and then crying wolf |

**Deployed WITHOUT the 55-commit reconciliation**, which was the point of asking. The owner answered *"you
are in charge, this is your decision"*, so the smallest reversible change was taken: the service module came
from `origin/master`, and the auth helper + three routes were **appended** to the production `main.py` —
one insertion point rather than two anchor matches inside someone else's 735 KB file — with the original
backed up and `py_compile` as the gate. Two restarts, ~15 s each, health verified after both.

**FOUR DEFECTS FOUND BY RUNNING IT — none by reading it, and the first one was misdiagnosed once:**

1. **`database is locked` ×4** (`error_log` 809–812), and **`busy_timeout` did not fix it** — I raised it,
   redeployed, and it failed again. The real cause is the *transaction shape*: Python's `sqlite3` opens a
   deferred transaction on the `SELECT` that checks whether a session changed, and the following `INSERT`
   must **upgrade** a read transaction to a write one, which fails instantly with `SQLITE_BUSY` if another
   connection committed in between. Waiting cannot refresh a stale snapshot; committing after the read
   fixes it. *The diagnosis came from the gap between two measurements:* an independent writer got the lock
   in **0.01 s** when the database was calm, yet the ingest failed under load — so the lock was never held
   long. **L52 candidate: when a timeout-shaped fix doesn't work, the problem is not timing.**
2. **One 2,384-row / 10 MB session** could not finish inside a single HTTP deadline → 300 rows per request
   (the protocol already carried `start_row`), with the cursor advancing only on a session's last fragment.
3. **A backfill stampede**: a hundred inserts back to back while the company writes continuously. The WAL sat
   at exactly its 64 MiB limit — the signature of checkpoint starvation. Now paced, with one retry on 5xx.
4. **A statistic of mine that lied**: the per-machine event figure summed *declared* row counts and read
   31,251 against 19,866 stored. It now counts what is stored.

**Left in place, deliberately:** the standalone archive at `/home/zabz/dsh-archive/dsh-archive.db` is a
frozen copy of what shipped before the endpoint existed. Nothing deleted.

**STILL OPEN, and it is now the biggest standing risk in the fleet:** the production checkout is **55+
commits behind with nine uncommitted files including ~510 lines of live work** (Shabbat/Shelly). Tonight's
change was additive; that reconciliation is still nobody's job. Also open: `ps_mcp_server.py` opens the
company database **read-write** (`sqlite3.connect(DB_PATH)`, no `mode=ro`) while every tool it exposes is
read-only SQL — three such connections were holding it open during this work.

**EVIDENCE**
- `harness-config/docs/dsh-mobile/01-DESIGN-AND-PLAN.md` Phase 3 "Resolved"; commits `ee2f61e`, `bc7fb6d`,
  `b6a77e239`, `52d96870a` (company repo); `error_log` rows 809–812; the stats/search output above

---

## 2026-09-11 19:55 · ZABZ-YOGA · Audited all four comms channels; the boss's drafts are 22/22 unanswered

**CHANGED — one new kernel check, `comms_freshness`, live on the authority's scheduled run.**
It asks the only question an empty queue cannot fake: what is the *newest row timestamp* in each
channel that carries customers. It immediately reported HIGH, and was right to:

| Signal | Measured on the authority |
|---|---|
| email triage | 13m — healthy |
| Dialpad SMS harvest | 1.6h — healthy, but **nothing is scheduled to crawl it** |
| **call capture lag (median)** | **17.5h** — half of all calls reach the DB most of a day late |
| **email drafts pending review** | **36 recent / 60 total, oldest 97d** |
| voicemail crawl (Playwright) | 2,139h — a metric, deliberately **not** a budget (see below) |

**Three self-corrections made before trusting it, all found by running it, not reading it:**
1. The voicemail probe reads `dialpad_ui_voicemail_row`, the **manual Playwright crawl that last ran
   2026-06-14**. As a budget it was a permanent false alarm — and a surface that cries wolf gets
   ignored (P6). It is now a reported metric only.
2. "Calls stale 10h" measured age-of-newest-row, which **a quiet night fakes**. Replaced with capture
   lag: how long after a call ends its row arrives. Cannot be faked by silence.
3. The lag SQL compared a REAL column to a TEXT `strftime()` result, so it silently matched zero rows
   and read `None`. Cast explicitly. (This is the *second* time this session a silent-empty query
   looked like a healthy answer — see L-note below.)

**THE FINDING THAT MATTERS MOST: the email reply loop has never worked.**
292 drafts have been generated and **3 have ever been sent — none in the last 30 days.** 36 sit in
`pending_review` right now. Nothing surfaces them to the owner, so every proposed reply has died in
the queue. Two drafts contain the literal placeholder *"I'll draft a reply matching the owner's
style."* instead of a reply. Reported to the owner as a boss question, because what to do with a
97-day-old backlog is his call.

**Verified channel state (all read from `/home/zabz/personal-secretary-mvp/data/secretary.db`):**
- **Gmail: working.** 4/4 accounts authenticated, `gmail_list`/`gmail_read`/`gmail_search` return live
  data. `gmail_search` failed twice with `Connection refused` then succeeded on the identical call —
  flaky, not broken; worth a retry-in-action fix later.
- **SMS: fresh data, late arrival.** `dialpad_sms_cache` holds 127,632 messages and 37 in the last
  24h, but records arrive ~8h+ behind. **No harvester is scheduled anywhere** — not in the crontab,
  not as a work order. This is the single highest-value gap.
- **Calls/voicemail: working, late.** 12,445 calls, 5,644 with transcripts. Voicemail notification
  emails *are* intercepted and largely get tasks — but `Caller Wireless` entries return no card and
  are skipped at `email_actions.py:203`.
- **Google Voice: dead and unmonitored.** 6,062 consecutive 401s, last OK 2026-07-02. Not raised on,
  because the number is documented as retiring.
- **`sms_log` is not a record of outbound texts.** 1 row since Sep 7, while the crawl shows real
  outbound replies that day. Texts sent from the Dialpad app never enter it, so the `sms_log`-based
  duplicate guard cannot see them.

**NEXT**
1. **Ask the owner** what to do with the 36-draft backlog (boss question — it is his voice going out).
2. Schedule the Dialpad SMS/call harvest — it is the root cause of the 17.5h lag and the 8h SMS lag.
3. Only after (2): flip the voicemail crawl and SMS budgets from metrics to enforced.

**EVIDENCE**
- kernel commits `96406d9`, `75fdd32`, `7b63525`, `97cfe81` (pushed to `secretary-ts:/home/zabz/ceo-kernel.git`)
- `python3 -m ck status --no-colour` on `secratary` → `[! ] comms_freshness` with 8 AUTHORITATIVE refs
- `email_drafts`: 292 total / 3 sent / 0 sent in 30d; `dialpad_sms_cache`: 37 msgs in 24h
- verifier: `_scratch/comms-verify/run_on_authority.py`
- **A refusal that was correct:** the Yoga replica has only 173 tables, so the kernel refused to read
  it (`< 190 tables; structurally old`). The check reported `unknown`, not health. Provenance held.

---


**CHANGED — Phase 5 delivered: three absence-shaped checks in the CEO kernel.**
The kernel asked whether the *company* was working; it now also asks whether the machinery around it is.
All three are about silence, because that is how each one fails — a job that stops running looks exactly
like a job with nothing to say (L11/L12/L30).

| Check | What it asks | Verified on the authority |
|---|---|---|
| `config_sync` | has this host's config converged recently, and cleanly? | *"config converged 1s ago at 988b244"* |
| `session_archive` | are every machine's sessions still arriving? | *"91 session(s) / 30,730 event(s) from 3 machine(s); newest 3m ago"* |
| `phone_endpoint` | is the endpoint his phone uses actually serving? | *"engine on 3086, published on the tailnet"* |

**The checks were made to fail on purpose before being trusted** — a check that has only ever passed is
unproven. `config_sync` with its record removed → `[??]` refusal; with the record backdated 2 h →
`[! ] "has not run in 2.0h (expected every 15m) — this host may be drifting"`; then restored → `[ok]`. That
was the check catching my own test record in the scheduled run at 19:13:55, which is exactly the behaviour
wanted. **The scheduled kernel now reports 11 checks**, up from 8, and `latest.json` carries all of them.

**A design detail worth keeping:** `phone_endpoint` only raises when the host actually has phone state
(`~/.dsh-phone`). On a workstation "no endpoint here" is normal, and reporting it as a fault is the false
alarm that teaches a reader to ignore the surface (P6). Verified off-authority: it says
*"not configured here"* rather than crying wolf.

**Also this round:** the kernel's own runner was confirmed end to end (`run.log` → `history.jsonl` →
`latest.json`), so the new checks are not just runnable by hand but shipped on the 5-minute cron.

**NEXT — and it is now a decision, not work**
The only item left in the objective is moving the archive's tables from the standalone database into the
authoritative `secretary.db`. That needs a change on the company's production host, and the host's checkout
is **55 commits behind with nine uncommitted files, including ~510 lines of someone's live work** (the
Shabbat/Shelly automation, "owner spec 2026-09-11"). I have not touched it: deploying 55 commits of other
people's code to the app that runs the business, at night, is not a call to make alone. The owner is being
asked, with options.

**EVIDENCE**
- `ck status` on `secratary` (three checks above); `latest.json` = 11 checks; `run.log`/`history.jsonl` lines
- the fire/stale/restore sequence above; kernel commit `f263cdd` deployed by `git pull` on the authority

---

## 2026-09-11 19:15 · ZABZ-YOGA · The phone now talks to an engine that never sleeps — and the fleet's credential had forked

**CHANGED — Phase 4 delivered: the harness runs on the always-on host.**
- **`https://secratary.tail93e6e6.ts.net/`** is now the phone's endpoint, served by an engine on `secratary`
  itself (`serve-phone.sh`, port 3086, `tailscale serve` → loopback). One canonical URL; the Yoga's endpoint
  was **retired** (serve config cleared, engine stopped), so the phone no longer depends on a laptop being
  awake or on its network being kind.
- **The secretary bridge there is a LOCAL child of the engine** — verified: the session's `ps_mcp_server.py`
  is a direct child of the engine, and there are now **0** bridges parented to a remote ssh session on that
  host. That removes the network hop PAIN P23 recorded spawning processes on the company host.
- **It answers correctly:** *"**200 ticks today (Sep 11, through 18:54 UTC), read from
  `/home/zabz/personal-secretary-mvp/data/secretary.db`** — via `ps_db_query` on `tick_telemetry` … and
  independently confirmed by a read-only `sqlite3` count on that same file."*
- **Survival:** `@reboot` + a 10-minute idempotent watchdog, cron `autosync.sh` every 15 min, and the
  archive shipper every 30 min with a new `local` transport (write beside the importer, import in place).
  Archive now covers **three machines: 91 sessions, 30,730 events, all indexed.**

**THE FINDING THAT MATTERS MOST, and it is not about the phone: the fleet holds three different
`DEEPSEEK_API_KEY` values, and the one on the always-on host is invalid.**
Fingerprints (values never printed): `1b6e…` harness store — **HTTP 200 against the API**; `f097…` Yoga repo
`.env`; `646b…` authority repo `.env` — **HTTP 401, invalid**. My first attempt to give the Linux engine a
credential copied the authority's `.env` value and every model call failed with `Authentication Fails`.
So a credential forked exactly like the three databases of P3, and **anything on the always-on host reading
`DEEPSEEK_API_KEY` from `.env` is broken and silent about it.** The working key was installed from the
harness's own store, fingerprinted before and after.

**FIXED WHILE DEPLOYING — all three found by running it, none by reading**
1. **Node 20 fails SILENTLY** on this harness: no output, no listen, exit 0. `commander` needs ≥22.12 and
   `undici` ≥22.19. Installed a user-owned Node 22.23.2 at `/home/zabz/node` (no sudo, no system change).
2. **`tailscale serve` needs root on Linux**, and the first version of `serve-phone.sh` printed a
   working-looking phone link anyway. It now escalates with passwordless sudo, or refuses with the exact
   command, and verifies `serve status` before claiming anything.
3. **A hand `chmod +x` on one host became a local modification that blocked its `git pull`.** The exec bit
   now lives in git (`100755`), same class of mistake as CRLF (L21) — and the same lesson: a platform
   attribute belongs in git or every host fights the others.
   *(Also: the new `local` transport called `spawnSync` after the helper moved to async `spawn` — caught by
   running it, fixed in `e2b596a`.)*

**WHAT STILL STANDS — unchanged from the last round, and it is the last thing in the objective**
The in-app archive path (`POST /api/v1/owner/dsh-sessions/ingest` + `app/services/dsh_session_ingest.py` +
tables in the authoritative `secretary.db`) is written and committed (`92b82c351`) but **not deployed**: the
authority's company checkout is **55 commits behind with nine uncommitted files**, including ~510 lines of
someone's live work (Shabbat/Shelly automation, "owner spec 2026-09-11"). The archive runs standalone with
identical tables; the move is a one-step follow-up once that checkout is safe.

**NEXT**
1. Get that uncommitted production work committed (owner's call or the author's) — it is unbacked on the box
   that runs the business.
2. Then move `dsh_session_*` into `secretary.db` and let the dashboard and the CEO see it.
3. Phase 5: make the kernel watch the sync record, the archive's freshness and the Serve endpoint — all
   absence-shaped, which is what it was built for.

**EVIDENCE**
- `serve-phone.sh --status`: engine 2470590 on 3086, serve active, tailnet URL answering
- session `7a44807a` transcript on `secratary`; `crontab -l` (4 entries); archive `--stats` (three machines)
- credential fingerprints + the 401/200 API probes above

---

## 2026-09-11 15:10 · ZABZ-YOGA · Every sensor audited; the boss beacon is the fault, not the BLE system

**THE BEACON — answered with evidence, not inference.**
Owner: *"I haven't seen the boss beacon in a few months, I think I lost it."* He is right, and it is
**four months**, to the day.
- The device still exists in Home Assistant: **`BCPro_207463 11AA`**, MAC `dd:88:00:00:11:aa`, iBeacon
  entry *loaded*, area `control_room`, registered 2025-12-27. All five of its entities are
  `unavailable` with `restored: true` — restored from the registry, with nothing advertising.
- **Its presence automations last fired 2026-05-15 17:44 UTC.** `phoenix_boss_is_here_sync_from_ble`
  has *never* fired. Zero of the last 2471 logbook rows mention it.
- **The receiving side is proven healthy**, which is what makes the conclusion safe: bluetooth,
  bermuda, ibeacon, esphome all *loaded*; four BLE scanners up (Pi adapter + three ESPHome hubs);
  52 BLE devices in the registry; **10 trackers reporting real values right now.** So the mesh hears
  other devices and not this one → **the beacon is dead, out of battery, or physically lost.**
- Its tuning and automations are still in place (arrive 15 ft / leave 20 ft, Bermuda wiring), so a
  replacement only needs its MAC registered with the iBeacon integration.
- Also dark because of it: `sensor.bcpro_207463_estimated_distance` + 2m/5m filters,
  `sensor.boss_beacon_distance_fast/_slow`, Bermuda's `_distance/_area/_floor/_distance_to_*_hub`,
  `device_tracker.bcpro_207463_bermuda_tracker`.

**FLEET BEHAVIOUR — what the owner asked for (always on / always off / flapping).**
- **ZERO entities whose only recorded value is `off`.** There is no never-firing pile. The system's
  failure mode is **absence and silence**, not stuck-off.
- **ONE flapping entity in 1068:** `binary_sensor.control_room_hub_control_room_moving_target` —
  **525 transitions in 48 h**, one every ~5.5 minutes around the clock, driving the presence
  snapshot automations. That is the radar chattering, and it is a real defect.
- **157 security/access-named entities unavailable** (415 total absent), including the whole 31-slot
  apartment-deadbolt control surface, `script.access_control_operate_strike/_maglock/_open_locks`
  (the manual buzz-in scripts), and the recent-entry displays.
- **82 automations unavailable:** four abandoned generations of access control and presence still
  registered beside the live one (`keymaster_*` 37, presence 15, `access_control_*` 13, `phoenix_v2_*` 3).
- **17 entities recorded only `on`, and most are scripts that never finish** — read this as
  *being started repeatedly*, not as running: **`script.snapshot_latest_with_retries` = 15,682 rows,
  ~1,568 runs/day (one every 55 seconds, all day)**; `script.buzz_in_maglock` and
  `script.buzz_in_interior_maglock` — the scripts that **open the doors** — ~712 runs each in 10 days
  with **no activity reporting anywhere**.
- 11 entities effectively absent, incl. `person.klein` and a Shelly plug that wrote one row and stopped.

**I MEASURED THE WRONG SURFACE, AGAIN — corrected in its own document.**
My first behaviour audit claimed the recorder keeps ~2 days. **Wrong.** That was the *logbook API*.
Read directly with SQLite: `states` **1,239,866 rows / 10.45 days**, and **`statistics` 326,810 rows /
394.5 days across 116 entities** — statistics reach back to **2025-08-13**, which contains the beacon's
May sighting. Third instance today of the same error (log vs artefacts; port 22 vs 2222; logbook vs
database). Correction kept visible in
`ha-config/docs/CORRECTION-2026-09-11-retention-and-behaviour-from-db.md`, not quietly edited.
Second ceiling found: **only 89 of 1068 entities have more than one state row at all**, because
recorder writes only on change — so "is it stuck?" is unanswerable for 979 entities until the recorder
is configured properly.

**NEW INSTRUMENTS (committed, not in /tmp)**
- `scripts/ha_behaviour.py` + `ha-behaviour.sh` — domain-aware verdicts (a light that is off is off;
  a security-named `binary_sensor` that is unavailable is a broken sensor).
- `scripts/harvest_behaviour.py` — reads the recorder DB **read-only on the host that owns it**, so the
  measurement is reproducible and cannot silently regress to the API.
- `scripts/run-ha-behaviour.sh` — both stages + a trend line. **Cron installed: daily 04:20**
  (beside `run-sentinel.sh` every 5 min and `run-ha-truth.sh` every 30 min).
- Fixed a hops-failure class: `~/bin/run.sh` on `secratary` takes `HOSTPY=1` to run a pushed script
  with python3 (the old helper always used bash, so a `.py` died on `def main():`).

**NEXT (mine, no owner input needed)**
1. `script.snapshot_latest_with_retries` at 1,568 runs/day — legitimate watchdog cadence or a failure
   loop? Its name and 276 log errors say loop.
2. Give the two `buzz_in_*` door scripts an activity log — they open doors and nothing reports them.
3. `recorder:` — exclude the noise, raise `purge_keep_days`, so history exists for what matters.
4. The chattering radar signal; the Shelly plug that vanished; `person.klein`.

**NEXT (owner, when he is at the office)**
- The beacon: replace, or drop the BLE presence path.
- The four dead automation generations: retire, or keep any?
- `phoenix_customer_pin_enabled` (shared customer PIN): live is `off`, the repo said `true`.

**EVIDENCE**
- `ha-config`: `fcc0f58`, `cf81732`, `0649bef` (+ `5e3006f`, `d3f59f1`, `16c24f9`, `581fef3`) — all pushed
- `docs/AUDIT-2026-09-11-sensor-behaviour.md`, `docs/CORRECTION-2026-09-11-retention-and-behaviour-from-db.md`
- `secratary:/home/zabz/ceo-kernel-var/ha/behaviour-history.jsonl` (the trend row), `behaviour-raw.json`
  (database view), `behaviour.json`/`behaviour.md` (API view)

---

## 2026-09-11 19:40 · ZABZ-YOGA · The visual-modesty options space and the decision agenda are written

**CHANGED**
- Two deliverables for the kosher filter, committed and pushed:
  `kosher-filter-ai/docs/research/016-options-on-device-and-off-device-2026-09-11.md` (**10 on-device,
  9 off-device, 6 cross-cutting options**, a per-tier composition table, the off-device arithmetic, 7 unmeasured
  items, a dependency map) and `016-clarifications-and-questions-2026-09-11.md` (**14 clarifications +
  20 questions** in dependency order, each with options, a recommendation and what it blocks).
- **14 verbatim evidence reports** now live in `docs/research/responses/`; eight were collected out of `~/code`
  so the evidence sits beside the documents that cite it.
- **Two corrections to things already told to the owner.** (1) The applicability figure: two research streams
  disagreed on whether it was published, so I fetched the source — confirmed *"mean Tier 2 NA-F1: 24.7%"*, but
  the **best** model is GPT-5 at **37.1%**, not the "34.1% for the best" I had repeated, and it is nine VLMs, not
  seven. Corrected in five places. (2) The three-arm bake-off is **not "under $500"** — that priced
  model-assisted pre-labelling; real labelling is **$4,000–8,000 per 1,000 images** with domestic annotators.
- **Verified what we own** instead of assuming: broker container is **512MB / 1 vCPU** and **no GPU is recorded
  on any of the six tailnet nodes** (two queries against the authoritative memories/knowledge tables). Every
  off-device option is therefore rented or CPU-only.
- Off-device arithmetic shown: cheapest rentable L4 **$0.2022/hr → $147.61/mo floor → $0.0225 per 1,000 frames**
  → break-even **21,513 frames/day**; and at the only published 2B-class throughput self-hosting **ties** the
  API. Per-second serverless dominates 24/7 rental at every volume we can imagine.
- Legal spine is now a constraint, not a preference: **COPPA's amended rule is in force** and NJ **A.5328** bans
  selling sensitive data with **no consent exception at $50,000 per record** → staff phones and licensed adult
  model photography only, plus a new question (C4) listing four items that need a lawyer.

**IN FLIGHT**
- Nothing. **Two research streams were stopped deliberately, not lost:** self-host/serverless economics and
  on-device runtimes per tier. Both were re-covering ground already evidenced (the 015 on-device feasibility
  report; the 016 self-host-vs-API cost report with first-party GPU prices), and their findings were folded in
  from those reports instead.
- The one remaining gap **cannot be closed by research at all**: throughput and memory of anything on a real
  SD835-class phone. It needs the one-day physical measurement in questions doc **D2**.

**BROKEN**
- Nothing. Carried over: three divergent `secretary.db` copies (P3), evolution loop (P4), `engineering_indexer`
  (P5), held messages (P6), manual `harness-config` sync.

**NEXT**
- Walk the agenda with the owner, one at a time, starting at **A1: may family screenshots leave the phone at
  all?** (on-device only / self-hosted arbiter — recommended / third-party cloud, terms-blocked).

**EVIDENCE**
- Commits `85c32ec`, `94e742f`, `416ccb9`, `065428b`, `8c7f603` on `kosher-filter-ai` main; tree clean.
- Company DB queried 2026-09-11 for the GPU/hardware question.

---

## 2026-09-11 18:50 · ZABZ-YOGA · Every DSH session on both machines is now archived and searchable

**CHANGED — requirement 2 of the owner's ask is delivered end to end.**
- **The archive holds both machines.** 74 sessions, **25,631 events, 25,631 indexed rows** —
  `zabz-yoga` 63 sessions / 24,368 events, `zabz-tech` 11 / 1,263. Searchable by FTS; searching
  `ticks_today` returns the phone session's own *"197 ticks today (2026-09-11 UTC"* answer, so the
  conversation that proved the bridge works is itself traced.
- **Scheduled hourly on both workstations** as `PersonalSecretary-PushDSHSessions` (at logon, interactive
  user — the same idiom as `PersonalSecretary-PushVSCodeChats`), state `Ready` on both.
- Files: `harness-config/scripts/push-dsh-sessions.mjs` (client), `scripts/dsh-archive-import.py` (server),
  `scripts/Install-DshArchive.ps1` (scheduler). Authority store: `/home/zabz/dsh-archive/dsh-archive.db`.
- **The authority now has a git checkout of `harness-config`** (`/home/zabz/harness-config`), so harness
  code reaches it through git like everything else — and Phase 4 will need exactly that.

**TWO TRANSPORT DEFECTS, both found by running it and both fixed**
1. **ssh does not reliably exit** after the remote command completes. The desktop's first run hung 10
   minutes having shipped nothing; I first recorded this as desktop-specific, then the Yoga showed the
   same on 5 of its batches. Fixed by killing the child the moment the reply parses — safe because the
   importer prints its summary only *after* `conn.commit()`.
2. **A 4 MB stdin payload stalls indefinitely over the desktop's ssh** (300 s timeout, three orphaned
   shippers, nothing shipped) while the *same* payload from the Yoga ships 73 MB fine. Not the config,
   not the binary, not the network: **scp moves that identical file from that same machine in 0.3 s with a
   matching checksum.** So the batch now goes as a *file* and the importer reads it with `--file`. The
   Yoga's run went from 186 s to 27 s, and the desktop's from *never* to **2 s**.

**IDEMPOTENCE, PROVEN ON THE REAL PATH** — second run shipped only rows that were genuinely new: 1 session,
5 rows, 41 unchanged by cursor, and the authority's event count moved by exactly **+5** (16,468 → 16,473).
Nothing duplicated. PK is `(machine, session_id, ordinal)` and an ordinal never moves because the journal
is append-only.

**AND REQUIREMENT 1 WAS ONLY HALF-WORKING UNTIL THIS ROUND — found by checking it instead of assuming**
ZABZ-YOGA's autosync had been reporting `dirty` and **applying nothing**, because four files belonging to
other agent sessions were modified. Committed config changes reached the *repo* and never reached the live
`~/.dsh` — the exact drift the job exists to remove. Fixed: the apply now runs against a **snapshot of HEAD**
(`git archive`), not the working tree. Proven in an isolated clone with both a committed and a dirty change
present — committed marker landed (**1**), dirty marker did not leak (**0**), a dirty settings edit did not
leak (**0**), and the dirty edit survived in the tree (**1**), `converged: true`. The Yoga now reports
`clean, converged: true` where it previously reported `dirty`.

**WHAT WAS *NOT* DONE, AND WHY — this is the one deviation from the objective**
The intended home is in-app: `POST /api/v1/owner/dsh-sessions/ingest` + `app/services/dsh_session_ingest.py`
+ tables in the authoritative `secretary.db`. **Written, committed (`92b82c351`), NOT deployed**, because the
authority's checkout of `personal-secretary-mvp` is **51 commits behind origin with nine uncommitted local
modifications, including `app/main.py`**. Deploying that means merging on a running company or hand-patching
that deepens the drift — neither is a call to make unilaterally at the end of a long day. The standalone
importer carries the same tables and semantics, and doubles as the test harness for the move.

**NEXT**
1. Decide the `personal-secretary-mvp` checkout: reconcile it (backup first) or get the owner's call — this
   is now the blocker for the in-app path *and* a standing risk in its own right (the running company's code
   is hand-edited and 51 commits stale).
2. Then move `dsh_session_*` into `secretary.db` and have the dashboard/CEO see it.
3. Phase 4 (phone engine on `secratary`) still stands, and PAIN P23's fix depends on it.

**EVIDENCE**
- `--stats` output above; `--search "ticks_today"` returning three real rows
- runs: yoga 42 sessions/16,466 rows/73 MB first, then 27 s incremental; desktop 11/1,263/4.9 MB in 2 s
- `HANDOFF` transport defects above; `docs/dsh-mobile/01-DESIGN-AND-PLAN.md` Phase 3 "Built and verified"

---

## 2026-09-11 14:45 · ZABZ-YOGA · The intrusion siren was never wired — one space of indentation

**THE FINDING OF THE DAY, and it was invisible from both sides.**
`config/packages/secretary.yaml` had `phoenix_alarm_mac_on` and `phoenix_alarm_mac_off` indented with **one
space**, making them siblings of `rest_command:` instead of entries inside it. Home Assistant parsed the file,
saw no such commands, and continued. **Confirmed live before the fix:** both were ABSENT from the service list
while `script.phoenix_intrusion_reset` called one of them. The audible Mac-mini siren has had nothing to call
since the Alexa announcements were removed — and an earlier commit message claimed it was restored.
Two more of the same class: `configuration.yaml`'s whole `http:` block was mis-indented, so the brute-force IP
ban and login threshold added 2026-09-05 had **never been active** while a comment said the hardening was in
place; and `packages/phoenix_security.yaml` did not parse at all, so the repo's intrusion response was
undeployable.

**CHANGED (deployed and verified)**
- Three YAML files repaired; two host-only helper additions merged in. Committed `5e3006f`, pushed.
- Deployed to the live host: all five files backed up to `/config/packages/.backups-20260911-183834/`, hashes
  verified after copy, **`ha core check` → "Command completed successfully."**
- **`rest_command.reload` restored the two dead commands with no downtime**, then an `ha core restart` loaded
  the `http:` block (integration settings only load at core start).
- **Verified after:** all four `rest_command`s LIVE · 1068 entities (unchanged) · 150 automations, 64 on,
  82 unavailable (unchanged) · `grep -icE 'invalid config|failed to parse|setup failed'` → **0**.
- The siren endpoint was checked *before* wiring it in: `POST /alarm/on` → `200 {"ok": true, "alarm": "on"}`.
- New tool `scripts/validate_ha_yaml.py` (`d3f59f1`) — parses with HA's tags registered and fails loudly on a
  parse error, a `rest_command` ownership mistake, or an intrusion sequence whose first step is not the
  evidence-snapshot block. **Run it before committing any HA change.**
- Deployment record: `docs/DEPLOYMENT-2026-09-11-security-chain.md`.

**THE OWNER-FACING ONE THING**
`phoenix_customer_pin_enabled` ("Business Access Enabled") — the shared long-term customer PIN on the outside
door. The repo said `initial: true`, the live entity has been **`off`** since 2026-09-11T01:48:01Z, and I
adopted `false` to preserve running behaviour. It is a **business posture, not a bug**; flipping it back is one
line.

**STILL OPEN**
- **The two door contacts are still dark** (outside + interior, since 01:48) — battery devices, need a physical
  wake. The restart did not and could not bring them back.
- 22 of 25 cameras still fail `camera.snapshot` on the Dahua NVR; needs a power cycle at the office.
- The repo's `automations/` tree (38 ids in `access_control.yaml` alone) is **deliberately not deployed yet** —
  the live system runs a Phoenix access-control master from its packages, and merging without a name diff would
  put two live generations on the same doors. That diff is the next task.
- 41 orphaned Keymaster entities, 82 unloaded automations, Core 11 months behind, Spotify loop (the only error
  left in the log).

**NEXT**
- Diff the repo's automation ids against the live ones, decide which generation is canonical, then deploy or
  delete. Then Part 1 (`check.ps1` → `backup.ps1` → `refresh-runtime-truth.ps1`) from `ZABZ-TECH`, which is now
  expected to pass for the first time.

**EVIDENCE**
- `ha-config`: `d3f59f1`, `16c24f9`, `5e3006f`, `f45f21c`, `27cac54` (all pushed)
- live service list before/after; `ha core check` output; host backups at `.backups-20260911-183834/`
- journal LESSONS L100 (wrong indentation is a silent no-op), L101 (two generations of one thing), L102
  (observe the specific service, not the summary)

---

## 2026-09-11 20:05 · ZABZ-YOGA · Both machines run the fleet, and the `+` control is deployed

**CHANGED**
- **ZABZ-TECH is deployed and verified, over `ssh desktop-cf`:** `harness-config` pulled, the two local
  packages installed into `~/.dsh/profiles/web` with `pnpm install` (local `file:` deps, no network), both
  mounted as bundles, the `dsh-new` protocol registered, both scheduled tasks imported and `Ready`, and the
  engine up on 3099 with the patched profile. **It serves `plugin-windows` and `dsh-plugin-cost`.**
- **Deployment runbook** is now a real script (`_scratch` is scratch, so the durable copy lives in this
  journal entry and the README): declare the deps, `pnpm install`, mount the bundles, register the protocol,
  import the tasks, restart the engine. Four traps are written into it, every one of them hit today:
  1. the package NAME is `dsh-plugin-x` but the DIRECTORY is `packages/plugin-x` — mixing them produced
     `cannot resolve profile bundle`, and because the bundle list is read at boot that took the engine down
     on the desktop until it was reverted;
  2. `pnpm install` in the profile IS required — copying files into `node_modules` is not the same thing;
  3. `-UserId "$env:USERDOMAIN\$env:USERNAME"` is not portable (ZABZ-TECH: "No mapping between account names
     and security IDs") — register by SID;
  4. base64 the script through `ssh`, because a here-string does not survive the remote shell and a truncated
     deploy is easy to miss.

**THE LAUNCH QUESTION IS NOW EXPLICIT**
`dshw` has two launch paths, and the difference matters:
- **default (direct spawn):** the engine's pid, its log files and a URL line from *this* launch — the
  strongest readiness signal. An engine started this way from an agent/tool shell can die with that shell's
  job object (measured: ~110 s, silently).
- **`-Detached` (through Task Scheduler):** the engine cannot die with the caller, but a task action cannot
  redirect stdout, so readiness falls back to the bound port. Use it when the caller is not a real terminal.
Either way the **watchdog task is the real protection**: it restarts a missing engine every five minutes, and
that is the only mechanism here that has to survive a crash rather than an accident.

**VERIFIED TODAY, END TO END**
- Engine on the laptop: up, serving `plugin-windows` (and `dsh-plugin-cost`); `up` opens no windows; `dshw new`
  opens exactly one; `health` is idempotent and took 4.5 s; `up`/`health` can no longer hang.
- Engine on the desktop: up on 3099 with both plugins in the payload; both tasks `Ready`; protocol registered.
- `plugin-cost` passes its own suite: client smoke OK (including the new regression check that it declares NO
  dependencies), `25/25` cost-logic checks, `build --check` clean.

**BROKEN / KNOWN**
- `dshw down` and `stop` were never re-tested after the `$pids` rename; the lifecycle test script exists at
  `_scratch/dshw-lifecycle/` and is the place to do it.
- The stranded engines on 3080 (both machines) and 3085 still exist beside the fleet.
- A window opened before an engine restart keeps losing its session; the app reconnects but the page must be
  reloaded. Nothing in the launcher can fix that — it is the missing session deep link (question 3).

**NEXT**
Re-test `down`/`stop`, then decide question 3 (session addressability), which is the last real gap in the
window experience.

**EVIDENCE**
- commits `872230e`→`0bd3da7` (readiness + SID), `f6a8f5e` (sequential launch), `d68c380` (+ control)
- desktop: `~/.dsh/profiles/web/package.json` bundles = base, web-app, dsh-plugin-cost, dsh-plugin-windows;
  `Get-ScheduledTask` both `Ready`; engine pid 52380 on port 3099
- laptop: `dshw status` → 1 engine live, 170 MB RSS, 863 MB whole tree

---
## 2026-09-11 19:05 · ZABZ-YOGA · The modesty model question was re-analysed from scratch — and the answer is "don't buy the programme"

**CHANGED**
- New audit: `kosher-filter-ai/docs/research/015-ai-capability-reanalysis-2026-09-11.md` (478 lines) plus
  **four verbatim evidence reports** in `docs/research/responses/015-evidence-*.md`. Commits `86674ff`, `bdfd936`.
- **The $850–1,600 / 5–6-week training programme no longer prices anything real.** Fine-tuning a small model is
  $1–10 of rented GPU and hours; labelling is $10–100 for 20k images; Fashion Florence hit 94.6% category
  accuracy from 3,688 examples / 3 epochs.
- **But "no training needed" is also wrong.** Best zero-shot VLMs: 64.0% macro-F1 on garment attributes, only
  **24.7%** at detecting whether an attribute is *visible at all* (70.8% given visible). **Model confidence is
  unusable for fail-closed gating** — ECE up to 0.496; under underexposure accuracy fell 0.99 → 0.22 with stated
  confidence flat at 0.87–0.90.
- **Three of five attributes are better solved by measurement than classification**: a verified ~22MB Apache-2.0
  MediaPipe stack (pose 5.51MB + selfie-multiclass 15.61MB + hair 0.75MB), no training, and it *fails visibly*
  on out-of-frame body parts. Validated in direction by LaGPS (NeurIPS 2025, +19.4% mIoU over CLIPSeg).
- **No VLM fits the device**: floor ~200MB on disk / 350–420MB resident vs a ~512MB Android per-app ceiling; the
  SD835 has no INT8 tensor unit, NNAPI is deprecated, driver frozen at Android 11 — which **voids directive
  009's Hexagon-for-INT8 decision on that hardware**.
- **"Married women's hair" is not a visual attribute** (hair *covered* is a solved binary at 99.1% acc / 5.7%
  EER supervised). **Tight/clingy fit has no benchmark above ~55%** and is the one attribute that needs a probe.
- Licence traps verified and recorded: DensePose (CC BY-NC), ModaNet (non-commercial), FASHN Human Parser,
  `segformer_b2_clothes`, MobileCLIP-S0 (`apple-amlr`). An early draft of the audit recommended DensePose and
  **I corrected it in the document** rather than quietly editing (LESSONS L53).

**IN FLIGHT**
- One research stream (2026 API cost detail) is still running; its findings are largely covered by official
  pricing pages I read directly, so the audit stands without it.
- A-BACK-014's replacement plan is written but **not started**: one-day physical-835 measurement, then a
  one-week three-arm bake-off (~1,000 hand-labelled screenshots) using the existing Phase 13 harness.

**BROKEN**
- Nothing from this work. Carried over: three divergent `secretary.db` copies (P3), evolution loop (P4),
  `engineering_indexer` (P5), held messages (P6), manual `harness-config` sync.

**NEXT**
- Ask the owner **one** question: may family screenshots leave the device at all (cloud / our own server /
  on-device only)? It decides whether the arbiter layer for attributes 3–5 is buildable, and it is the one
  decision the re-analysis created that is genuinely his.

**EVIDENCE**
- `docs/research/015-ai-capability-reanalysis-2026-09-11.md`; four `015-evidence-*.md` reports; A-BACK-014
  rewritten in `docs/IMPLEMENTATION_BACKLOG.md`.
- Journal: LESSONS L52–L54, DECISIONS D21.

---

## 2026-09-11 14:35 · ZABZ-YOGA · Home Assistant reads itself now, and the timeline system came back into git

**CHANGED**
- **The HA estate is on a schedule.** `ceo-kernel/scripts/run-ha-truth.sh` (`0ec7104`) deployed to
  `secratary`, cron `*/30 * * * *`. It regenerates `ha_truth.py` from the ha-config mirror each run, so
  a collector fix lands without a second deploy. *Observed, not assumed:* `ha/run.log` holds
  `18:21:43` (by hand — proves nothing) and **`18:30:01` (the cron tick — proves the schedule)**.
  It writes `ha/latest.json` + `ha/latest.md` and one trend line per run to `ha/history.jsonl`; keeps
  the last good reading when a run produces nothing (an empty file is not evidence of health); exits 0
  and routes nothing on purpose — alerting is the inbox's job and is not built.
- **Recovered work that existed only on the HA host and is now in git** (`f45f21c`):
  `config/packages/phoenix_timeline.yaml` — a complete timeline-capture system (RTSP clips off the NVR,
  doorbell-person and front-door triggers, regen to `/local/timeline/index.html`, and the channel map
  Front Hallway=ch5 / Waiting Room=ch4 / doorbell=Reolink .50.231) — plus `config/timeline_tools/`
  (20 files: capture scripts, the generator, RFID repair tools, timeline health checks). The YAML calls
  that directory by absolute path, so committing one without the other would have been a dangling
  reference. It is also the source of the `timeline_person_at_doorbell_clips_regen` errors.
- **`ha-config` is pushed to GitHub** (was 6 commits ahead, now clean at `f45f21c`).
- Hash inventory of `/config/packages` vs repo: **8 files identical, 4 different, 1 host-only.**
  The conflating live copies are preserved as evidence in
  `docs/live-config-snapshots/2026-09-11/*.live` rather than merged blind, and the repo stays the
  deployment source.

**THE FOUR DIFFERENCES, AND WHY THEY MATTER**
| file | live vs repo | consequence |
|---|---|---|
| `secretary.yaml` | live is the **older 41-line** version | `rest_command.phoenix_alarm_mac_on/off` and `rest_command.phoenix_security_page` were confirmed absent from HA's service list — the 2026-09-06 Mac siren and owner-SMS paging are **in git but not live** |
| `phoenix_helpers.yaml` | live is **newer** | Worker Weinberg + Yitz/wife PIN and RFID helpers, `wife` added to the worker list; `Business Access Enabled` initial flipped true→false |
| `presence_architecture.yaml` | live is newer by one line | `'Weinberg', 'Worker Weinberg'` added to the worker-name filter |
| `phoenix_security.yaml` | live is **machine-reformatted** | comments stripped, templates folded into escaped single-line strings — same logic, nothing human-readable, and the shape a UI round-trip or a rewriting tool produces |

**STILL DARK / BROKEN**
- Two door contacts `unavailable` since 01:48 — battery devices, **not remotely recoverable**; recorded
  posture is "not a trustworthy intrusion trigger today".
- **22 of 25 cameras fail** `camera.snapshot`; the Dahua NVR answers ping/RTSP/web/37777 but returns
  500 on `/cgi-bin/snapshot.cgi` for every channel, one request at a time. Needs an NVR power cycle.
- 41 Keymaster entities with no config entry; 82/150 automations unloaded; Core 11 months behind;
  Spotify retry loop (683 identical lines).

**NEXT**
- Reconcile the four divergent files — repo's `secretary.yaml` (newer, and the missing siren/SMS path)
  versus the host's newer helper/presence additions — then deploy from `ZABZ-TECH`: `check.ps1` →
  `backup.ps1` → `refresh-runtime-truth.ps1`. Part 1 still has never executed.
- Then the dead-generation deletions, per-action yes, and an NVR restart at the office.

**EVIDENCE**
- `ha-config`: `f45f21c`, `27cac54`, `6e89501`, `7be821d` (all pushed); `ceo-kernel`: `0ec7104` (pushed)
- `secratary:/home/zabz/ceo-kernel-var/ha/{latest.json,latest.md,history.jsonl,run.log}`
- `secratary:/home/zabz/ha-config-live` (git clone of the repo, the collector's source)
- journal: LESSONS L45/L46, WINS W15 (+ correction note on W11)

---

## 2026-09-11 13:35 · ZABZ-YOGA · Kosher Waze unblocked: owner answered, cap bands built and live

**CHANGED**
- **THE KOSHER WAZE GATE IS OPEN.** The plan had 21 questions (Q8–Q28) gating the build. Only **four**
  were ever the owner's. He answered **three** this session; the fourth (location/compliance) is
  recommended nav-local-store-nothing and is unopposed.
- **His answers, recorded in `kosher-waze-customer-integration-plan.md`:**
  1. **Billing is postpaid, metered by usage — not prepaid top-up.** *"they pay per usage they don't pick
     an amount, they just change the cap, and the customer or staff should be able to do that."*
     ⇒ **Q10 is moot: there is no top-up flow.** P4 loses its top-up component.
  2. **Data STOPS at the cap**; customer or staff raise the cap to continue. Chosen from three options.
  3. **Pause = cut cellular entirely** (Telnyx standby). See the analysis below — this was decided by
     engineering, not handed back, because option B was self-defeating.
- **Built and deployed: cap bands.** `_customer_view` now returns `usage.cap_band`
  (`ok|warning|blocked`), `cap_message`, `percent_used_raw`, `warn_at_percent`, plus
  `service.data_stops_at_cap` and `cap_editable_by`. The portal no longer re-derives thresholds.
  Commit `072f636a9`.
- **Corrected a docstring that stated the opposite policy.** The cap endpoint claimed the cap was
  *"a guardrail, not a wall"* and raising it meant *"paying overage"* — the reverse of the decision. On
  the one endpoint that controls customer spend, that is how a wrong policy gets built against.
- **Fixed a bug that silently disabled the warning the owner's choice depends on.** The cap floor was a
  hard `0.25 GB`, so a low-usage device could never hold an allowance small enough to reach 80% of it —
  the warning band was **unreachable** and the only notice before Waze dies mid-trip could never fire.
  Floor is now `CAP_MIN_GB = 0.05`. A test asserts the band stays reachable.
- **Found and fixed broken dead code:** `create_usage_notification` took `threshold_gb` but sent
  `int(threshold_gb * 100)` as a percentage, so a GB-scaled caller produced 200 → clamped to 100 → the
  alert fired only at the cap. Now `threshold_percentage`, validated not clamped. It was **never called
  from anywhere**; now wired into the cap endpoint behind `WAZE_USAGE_NOTIFICATIONS` (**default OFF** —
  the account has never held a notification, and a live cap change must not break on an unproven call).
- 10 new tests → **56 passing**. Then a further 10 → **66 passing** (see the correction below).

**⚠ CORRECTION — I BROKE THIS SUBSYSTEM AN HOUR AFTER FIXING IT, AND CAUGHT IT ONLY BY LUCK**
My PostgreSQL fix (commit `6f2a5195b`) set the psycopg row factory as
`raw.cursor(row_factory=dict_row)` — which applies to that **one cursor**, not the connection.
`_PgConn.execute()` creates a **fresh cursor per query**, so every query returned plain tuples, every
`row["column"]` raised `tuple indices must be integers or slices, not str` (a message that reads like
SQLite while being a PostgreSQL row-shape problem), and `r["column_name"]` raised inside the connect path
itself — so `_connect_db()` silently returned `None` and **every write fell back to SQLite**. My
"verified to Postgres" claim was true only for the standalone `--snapshot` command I tested, not for the
HTTP endpoints the company uses.
**What was actually down:** `/fleet/telnyx/usage`, `/fleet/telnyx/customers`, `/fleet/telnyx/billing`
— all three 500. Fixed in `3a228f959` (row factory now set on the connection). **All three now HTTP 200,
verified.** Also corrected a code comment of mine that blamed a missing `customer` column for the
unpersisted rows — the column is present; the row-shape bug was the cause.
*The lesson is L52 and it is the important one:* verify through the consumer's entry point (the endpoint),
not through a CLI or the module, and when an exception names one technology while you are debugging
another, **print the actual types** — `type(conn).__name__` located this in one command after two wrong
guesses.

**FINAL VERIFIED STATE** (after commit `3a228f959`, all read back live)
- `/fleet/telnyx/usage`, `/customers`, `/billing` → **HTTP 200**, real data, DRN↔ICCID mapping intact.
- Ledger reads back **19 rows**; a row inside the container is `dict {'n': 19}`.
- `telnyx_usage_freshness.py` → `OK: 14 usage rows, newest 1.6h old (limit 26.0h)`, exit 0.
- Snapshot still persists: `Persisted Telnyx snapshot to postgres (balance=5.14, 2 per-SIM usage rows,
  1 ledger row)`.
- `fleet-health`: 65 devices, 55 healthy, alerts 0, alerts_aged 87, alert_age_days 61.0.
- Container `healthy`. **66 tests passing.**

**VERIFIED LIVE** (all read back from the running API, not assumed)
- `POST /waze/device/{serial}/cap` works. `0.2` and `-5` both clamp to the floor; `data_limit_gb` and
  `percent_used` recompute on read. Both test devices restored to the **0.8 GB product cap**.
  DRN 2001 = 5.6 MB (0.7%), DRN 2002 = 185.3 MB (23.2%), both `cap_band: "ok"`, `state: active`.
- OTA diagnose both DRNs: `state=deployed`, wallpapers rendered, `pending=0 notnow=0`.
- **NOT verified end-to-end: the `warning` and `blocked` bands on real hardware.** They are unit-tested
  including boundaries, and the plumbing that computes them is proven live — but reaching 80% needs a
  device at ≥200 MB of a 0.25 GB cap, and no test device is. Do not claim it is proven.

**IN FLIGHT**
- **Pause semantics — decided, not built.** Pause is already `telnyx_standby` (off-network, IP preserved,
  $0.20/mo). Option B ("pause Waze data, keep Find My") was ruled out as incoherent: standby is
  off-network so MDM cannot reach the device to deliver a Waze-level block, and keeping the SIM on-network
  to preserve Find My means paying the full $2/mo — which is the entire thing pausing exists to save.
  Only addition needed: a one-line warning on the pause button that Find My stops working.
- **Second-order scope finding:** with postpaid per-usage billing *and* stop-at-cap, pause is **not** the
  lever that saves a customer money — a parked phone already costs nothing in usage. Pause is really a
  returned-device / dispute-hold / long-term-parking control. Don't spend much build effort on it.
- **Still unbuilt (unchanged, all mine):** portal-side tRPC (P2), customer + staff UI (P3), feature flags
  and test→prod (P5). P4 is now much smaller than planned.

**BROKEN / KNOWN**
- **`installed_profiles()` still lies** — `device_profiles` is always empty, so `diagnose` reports
  "no profiles installed" regardless of reality. Unchanged this session.
- **The 87 stale July `fleet_alerts`**: `fleet-health` now reports `alerts: 0`, `alerts_aged: 87`,
  `alert_age_days: 60.9`, `alerting_ever_fired: true`. The alerting pipeline has been silent for two
  months and **nothing has been created since**, which is either a quiet fleet or a dead path — unknown.
- **`data_limit_gb` in the DB / `TELNYX_DEFAULT_DATA_LIMIT_GB=2`.** Code now defaults to 0.8 GB, but the
  env var and any stored overrides still carry 2.0. The two test devices were set to 0.8 by hand; the
  env var is untouched because it governs new SIMs and changing it affects provisioning.
- Unchanged: `fleet.ps1 sql` broken; `docs/drn/generated/` (8,206 empty files, loop has stopped on its
  own, now gitignored, exporter refuses zero-row writes); three divergent `secretary.db` copies (P3).

**NEXT**
Build the customer + staff portal surfaces (P2/P3) against the endpoints that now exist and are live:
`GET /waze/device/{serial}`, `POST .../pause`, `.../resume`, `.../cap`. The contract is settled and the
server states the policy — no further owner input is required to build.

**EVIDENCE**
- `deploy/waze-mdm/docs/holdings-2026-09-11.md` — verified inventory of the whole WAZE/MDM/DRN/LPT stack
- `deploy/waze-mdm/docs/kosher-waze-customer-integration-plan.md` — the ANSWER LOG with his three answers
- Commits `6f2a5195b` (Telnyx data loss), `3ba33b23d` (honest fleet health), `072f636a9` (cap bands),
  **`3a228f959` (row-factory fix — the correction above)**
- `deploy/waze-mdm/fleet-api/fleet_api.py`, `telnyx_client.py`, `telnyx_billing.py`,
  `test_waze_customer_portal.py`, `test_telnyx_billing_db.py` (66 tests)
- LESSONS **L52** (verify through the consumer's entry point) + **L34**; PAIN **P15**, **P16**, **P17**;
  DECISIONS **D17**, **D18**

---

## 2026-09-11 18:05 · ZABZ-YOGA · The phone tells the truth now; the session shipper is ready to ship


**CHANGED**
- **The phone's answers are correct, and this is the whole point of the round.** The `mcp-secretary` row in
  the `zabz` preset now runs `ps_mcp_server.py` **on `secratary`** over SSH stdio, and the Windows-only gate
  is gone. Before: the bridge read a local 173-table replica and the phone answered *"13 ticks today …
  telemetry has been down for about three weeks"*. After, the same question on the same path:
  > **"197 ticks today (2026-09-11 UTC) — read from `tick_telemetry` on secratary's authoritative DB at
  > 17:56 UTC, newest tick started 17:50 UTC, so the count is current as of ~6 minutes ago."**
  Right number, provenance, freshness, and it verified the database's clock before answering. Commit
  `50d8561`; applied on both machines.
- **The session shipper's client half is built and verified** (`scripts/push-dsh-sessions.mjs`, `a539a37`).
  Dry run on this machine: **42 sessions, 16,031 rows, ~70 MB**, every zstd frame decoded, torn tails
  reported, nothing written in dry-run, and a real cursor entry skips its session on the next pass.
- **Two of my own claims corrected**, both append-only in `PAIN.md`:
  - **Bridges are composed per SESSION, not per process.** A second session mounted a second complete set
    (2× launcher, 2× fetch, 2× playwright, and the secretary row twice — once local python, once ssh). This
    **changes the multi-window cost model in `docs/multi-window/`** from ~1.4 GB per engine to ~1.4 GB per
    *active session*, which is the difference between "12 windows fit" and "they do not". Needs
    re-measuring before the owner leans on it.
  - PAIN P10's retraction needed a second amendment for the same reason (a count that confirms what you
    expect deserves the same suspicion as one that surprises you).

**VERIFIED, step by step** (nothing here is assumed)
1. The authority can host the bridge: `ps_mcp_server.py` present, venv `mcp` imports, `.env` present, local
   API `200`, DB is the 2.4 GB authority.
2. Raw SSH stdio handshake: `initialize` → 14 tools, protocol `2025-11-25`; `ps_db_query` for today's ticks
   → **197** (the replica said 13).
3. A new session on the phone engine mounted `ssh.exe … secretary-ts …ps_mcp_server.py` as its bridge.
4. The same question through the phone path → the authoritative number, with provenance and freshness.

**IN FLIGHT — the remaining half of Phase 3**
- The **server side of the archive is not built**: `POST /api/v1/owner/dsh-sessions/ingest` +
  `app/services/dsh_session_ingest.py` + `dsh_session_exports`/`dsh_sessions`/`dsh_session_events` + FTS in
  the authoritative `secretary.db`, mirroring `vscode_chat_ingest.py`. Then the token, the hourly scheduled
  task (per machine), and the idempotence proof. **Deliberately not started at the end of a long round: it
  is a production change to the running company and it deserves a clean context.** Size to expect: ~70 MB of
  rows from this machine alone, so the tables will be substantial.

**DESIGN DECISION made this round, and the reason**
The shipper **ships durable rows verbatim and interprets nothing**. The format's interpretive structure
(packed `*-chunks` rows, folded surfaces) is understood only by code this build does **not** export — the
persistence package exposes its Cordis plugin and nothing else, and the `decodeStorageRecord` named in the
upstream research does not exist here. Re-implementing the projection would be the same confident-wrongness
the journal keeps paying for (P22, L51). Verbatim rows are **lossless**; the official fold can run over them
later, in one place, on the authority. A guess would not be recoverable.

**NEXT**
Build the server half and finish Phase 3 end to end: service + route + tables + token, deploy, restart via
the watchdog, ship for real, then prove idempotence by row counts across two runs.

**EVIDENCE**
- `harness-config/scripts/push-dsh-sessions.mjs` (`a539a37`); `scripts/make_zabz_preset.py` + preset (`50d8561`)
- `docs/dsh-mobile/01-DESIGN-AND-PLAN.md` Phase 2.5 "Built and verified"
- the four verification steps above; `journal/PAIN.md` P10 amendment + P22; `journal/LESSONS.md` L51

---

## 2026-09-11 13:45 · ZABZ-YOGA · Closed the Kosher filter's on-device ML verification, and found a crash in it

**CHANGED**
- `kosher-filter-ai` `A-BACK-011` is **DONE** — verified on a real android-34 runtime for the first
  time. New `docs/HANDOFF_2026-09-11.md`; backlog A-BACK-011 and its blocker row updated.
- **Fixed a user-facing crash.** `GantManNsfwClassifier.load` caught only `Exception` around the
  `compileOnly` GPU delegate, so the `NoClassDefFoundError` escaped the loader, escaped the cascade and
  killed the host activity on the main thread the first time any image was shared. Now `Throwable` at
  three levels, and `CascadeOrchestrator.classify` fails closed (`ESCALATE`) instead of throwing.
- **Fixed the verification harness.** `Invoke-Adb` declares `-AdbArgs`; all 16 call sites passed
  `-Args`, which a non-advanced PowerShell function swallows into `$args` — so `adb` ran with no
  arguments and the script always reported "no device attached". Added `-DriveShare` (drives a real
  image share: nothing else makes the ML tags fire), per-file hiding in the fail-closed probe, and
  stopped the "fail-closed observed" check matching the benign `GPU delegate unavailable` line.
- Installed the Android `emulator` package + `system-images;android-34;google_apis;x86_64`, created AVD
  `lpt-ml-verify`; recipe recorded in `kosher-filter-ai/docs/DEVELOPMENT.md`.

**IN FLIGHT**
- Nothing outstanding. The commit and push described below landed, and CI is green on it.

**BROKEN**
- Nothing known-broken from this session. Carried over unchanged: three divergent `secretary.db` copies
  (P3), the evolution loop (P4), `engineering_indexer` (P5), held messages (P6), manual
  `harness-config` sync.

**NEXT**
- What is left in the Kosher filter is owner or hardware: modesty-model spend (on HOLD), halacha tiers,
  seat price points, billing party; a **physical** Android phone (an emulator has no GpuDelegate and no
  NNAPI, so the GPU/NNAPI paths and the "GPU delegate is optional" fix are unverified on silicon); and
  macOS + iPhone for all of iOS.

**EVIDENCE**
- `scripts/verify_on_device_ml.ps1` → **pass=16 warn=0 fail=0** on emulator-5554.
- Device logcat: `GantManNsfw: Model loaded successfully`, `NudeNet: Model loaded from
  .../files/models/nudenet_320n.onnx`, and with every model hidden
  `Blocked uncertain image share: No local classifiers available`.
- Commit **`e0fef29`**, pushed; **Server CI ✅ (8m), Android CI ✅ (3m21s), Server ARM64 Image ✅ (5m)**.
- Android unit suite **362 tests / 0 failures**; harness contract tests 8 passed, with the new one
  verified to fail against the pre-fix script from git.
- Full server suite **1035 passed / 17 skipped / 7 failed**; 4 of the 7 were real drift from `853addc`
  (now fixed), 2 are the known env-only Windows failures, 1 was a test file mid-edit.
- Journal: LESSONS L47–L50, WINS W14, DECISIONS D20, PAIN P21.

**CORRECTION TO THE ENTRY ABOVE (same session, 15:58 UTC).** The "IN FLIGHT" line I first wrote said
the commit was pending. It is not: `e0fef29` is committed, pushed, and all three CI runs are green.
Left visible rather than edited, per the append-only rule.

---

## 2026-09-11 13:40 · ZABZ-YOGA · Home Assistant: got into the host, and corrected two of my own wrong claims

**CHANGED**
- **The HA host is reachable — SSH is on port 2222, not 22.** `tcp/2222 → SSH-2.0-OpenSSH_10.3`,
  `root@192.168.50.34` key auth succeeds (`hostname` = `a0d7b954-ssh`, the add-on container).
  Every script in `ha-config` defaulted to 22, so `check/deploy/backup/inventory` had **never once
  worked**, and "connection refused" read as a dead host. Fixed: `$script:DefaultHaSshPort = 2222` in
  `part1-common.ps1` plus all nine scripts, syntax-checked. Commit `27cac54`.
- Installed a reusable hop-through tool on `secratary`: `~/bin/ha-run.sh <script-on-secratary>` pushes a
  script to the HA host over stdin (the add-on refuses sftp/scp) and runs it with bash. It strips CRLF,
  because three attempts today died on that.
- **Corrected two wrong claims in my own audit, visibly, in the document.** (a) "camera snapshot
  capture fails on every trigger" — false. `/config/www/snapshots` holds **3034 JPEGs**, written
  continuously: 146 on 08-31, 98 on 09-10, **52 today**, including a 319 KB control-room still 20
  minutes before I wrote the claim. I read the loudest surface (1105 log lines) and called it the whole
  truth. (b) "SSH is closed, toolchain blocked" — false, see above.
- Probe artifacts my camera tests wrote into `/config/www/snapshots` (4 files) were deleted; the 3034
  real evidence files were not touched, verified after.

**WHAT IS ACTUALLY TRUE ABOUT THE CAMERAS** (measured per entity, `camera.snapshot`, 2026-09-11 13:24)
- **22 of 25 cameras fail, 3 work** (`cam_waiting_room_sub`, `cam_waiting_room_sub_2`,
  `video_doorbell_fluent` — the last is Reolink, so the HA feature and file paths are sound).
- The Dahua NVR `192.168.50.170` answers ping (2 ms), RTSP 554, web UI 200 and the SDK port 37777 —
  but **redirects the snapshot API HTTP→HTTPS and then returns 500 for every channel**, tested one
  request at a time 3 s apart, including the channel HA had just succeeded on.
- Installed integration is a custom fork `dahua` **0.9.76** that already retries on 500 and follows the
  redirect by hand. It is doing everything right and still gets 500.
- **Evidence capture is degraded, not dark** (~50–100 stills/day instead of a complete set), and which
  cameras fire varies call to call — the worst property for evidence.
- **Not fixed, honestly.** Remaining candidates are NVR-side (restart, firmware, session limit) and an
  NVR change cannot be verified from here because nothing on the NVR answers authenticated.

**WHAT IS STILL TRUE AND STILL DARK**
- The outside-door and interior-door contacts are still `unavailable` since 01:48. **Remote recovery is
  impossible**: battery end devices sleep until a physical event wakes them; neither an integration
  reload nor a coordinator restart reaches them, and a restart would return the same result either way
  (LESSONS L37). The recorded posture is therefore *"the outside-door contact is not a trustworthy
  intrusion trigger today"*, not a to-do.
- 41 Keymaster entities with no config entry and no device; 82/150 automations unloaded; Core 11 months
  behind; Spotify looping on a revoked token (683 identical log lines).
- **Real repo-vs-host drift found:** `/config/packages/` holds `phoenix_timeline.yaml` plus a pile of
  hand-made backups (`phoenix_helpers.yaml.bak-yitz-*` ×6, `bak-rfidfix-20260910-214534`,
  `bak-custoff-*` ×3, `phoenix_security.yaml.pre-h4a-broken`, …) — work from 09-08..09-10 that only
  exists on the host. `/config` also contains two leftover **Windows staging directories whose names
  are literal `C:\Users\ezabz\AppData\Local\Temp\ha-config-staging-…` paths** (2026-04-17, 04-26),
  each a full config copy. Junk, and proof a deploy once wrote to the wrong place.

**NEXT**
- From `ZABZ-TECH` on the office LAN (the Yoga has no route to 192.168.50.34): run `check.ps1`, then
  `backup.ps1`, then `refresh-runtime-truth.ps1` — Part 1 has never executed, and the port fix is what
  unblocks it.
- Schedule `ha_truth.py` on `secratary`'s cron beside the sentinel, and alert on the **absence** of a
  fresh reading. The instrument exists and finds everything above; nothing runs it.
- Recover the host-only package backups into git **before** tidying them, then restart the NVR at the
  office and re-run the per-camera probe against the 22-of-25 baseline.

**EVIDENCE**
- `ha-config` commits `7be821d`, `6e89501`, `27cac54`; `docs/AUDIT-2026-09-11-live-systems.md` (with the
  corrections left in), `docs/DISPOSAL-PLAN-2026-09-11-dead-generations.md`
- `~/.ssh/ha-mesh-key` on `secratary`; `~/bin/ha-run.sh` on `secratary`
- Journal: LESSONS L45 (count the artefacts, not the complaints), L46 (a port mismatch reads like a
  dead machine)

---

## 2026-09-11 13:45 · ZABZ-YOGA · Sync runs itself · the phone path is proven · the archive is designed

**The owner's ask, in three parts:** workstations stay in sync; DSH sessions get traced into the secretary
like the VS Code ones; his iPhone talks to the DSH harness — "the same you … all the tools". Researched,
documented, and started.

**CHANGED**
- **The machines now sync themselves.** `scripts/autosync.ps1` + `scripts/Install-Autosync.ps1`
  (`c7faeb4`, `e57230d`) registered as `PersonalSecretary-HarnessSync` on **both** workstations: at logon
  and every 15 minutes, interactive user, Limited. It **pulls even when tracked files are modified** (git
  refuses by itself to overwrite local edits — git is the safety, not a heuristic of mine) but **skips the
  apply** while tracked files are modified, so a half-written preset can never reach `~/.dsh`. The apply is
  **verified** by a second `--dry-run`: `WOULD CHANGE` = did not converge = reported as attention. Never
  commits, merges, stashes, resets or force-pushes. Every run writes a status record + a log line.
  *Verified:* clean path end to end in a **throwaway clone with a throwaway `DSH_HOME`**
  (`{"result":"clean","converged":true}`, exit 0); ZABZ-TECH fired by Task Scheduler → **result 0, clean**;
  ZABZ-YOGA fired and honestly reported `dirty` because another session had a tracked file open.
- **Engineering docs written**: `harness-config/docs/dsh-mobile/00-RESEARCH.md` (evidence base) and
  `01-DESIGN-AND-PLAN.md` (design + ordered phases + acceptance tests), committed `44e5401`.

**VERIFIED BY EXPERIMENT — the disagreement that mattered**
Two agents disagreed about whether a non-loopback authority can authenticate to `dsh web`. One read the code
and said **never**; the docs said it works. I started a throwaway engine on `:3099` with
`--trusted-host dsh.test` and probed it with `curl`:
`GET /?token=…` with `Host: dsh.test` → **303** + a cookie minted **for authority `dsh.test`**; the API then
answered **200** with that cookie; an untrusted `Host` got **403 even with a valid cookie**; no cookie → 401;
and the cookie was **dead on any other authority** (401).
→ **The docs were right and the code-reading conclusion was wrong.** So the phone path needs **no patch and
no fork**: `dsh web` stays loopback-only, a reverse proxy that preserves `Host` (Tailscale Serve) sits in
front, `--trusted-host <tailnet name>` admits it, and the cookie is authority-bound. Test engine killed,
no serve config left behind, the real engine on 3080 untouched.

**BLOCKED ON THE OWNER — one click, his account only**
`tailscale serve --bg 3099` → *"Serve is not enabled on your tailnet. To enable, visit
https://login.tailscale.com/f/serve?node=…"*. Account-scoped; no CLI can do it. **This single click is the
only thing between the design and a working phone.** Everything else in Phase 2a is proven.

**DESIGNED, NOT BUILT**
- **Phone** (Phase 2): Serve + `--trusted-host` + install the harness's own PWA to the home screen, then fix
  mobile ergonomics with a **client-side plugin** shipped from this repo (`packages/plugin-cost` proves the
  pattern works here). Rebuilding his `/phone` PWA as a custom client is *possible* — `session/list`,
  `session/create`, `session/prompt`, `session/follow{assistantStream}` cover it — but it means hand-writing
  cookie custody and gap repair to arrive at less than the shipped UI already does. It stays the fallback.
- **Archive** (Phase 3): a Node shipper per machine using the **official `decodeStorageRecord`** (never
  hand-rolled — three silent-data-loss traps confirmed), cursor `(machine, project, session, last_seq)`,
  at-least-once delivery + **upsert on `(machine, session, seq)`**, to a new
  `POST /api/v1/owner/dsh-sessions/ingest` + `dsh_session_*` tables in the authoritative DB. Mirrors the
  proven Copilot pipeline and deliberately does **not** inherit its five gaps.
- **End state** (Phase 4): move the phone's engine to `secratary` so it works when the workstations sleep —
  needs a Linux autosync and a Linux variant of the secretary MCP row (today it is gated
  `disabled: !!js process.platform !== 'win32'`, so Linux gets no secretary bridge).

**WHAT THE PHONE APP ACTUALLY IS** (found, not assumed): the `/phone` PWA **"Secretary Chat"** in the
Next.js dashboard, public at `ai.abletelsolutions.com/phone` via cloudflared, NextAuth GitHub-only, its own
`phone_chat_history.db` — **3 sessions and 22 messages ever, last used 2026-09-08**. Its own audit already
diagnosed why: *"it has to actually be you"* — four divergent chat paths on a **single-turn engine that never
ran tools** (tools silently failed on the phone until 2026-09-02).

**NEXT**
When the owner enables Serve: publish the engine, send him the one-time token URL rewritten to the tailnet
host, install to his home screen, and make a tool-using request from the phone. Then Phase 3.

**EVIDENCE**
- `harness-config/scripts/autosync.ps1`, `scripts/Install-Autosync.ps1`, `scripts/sync.py`
- `harness-config/docs/dsh-mobile/00-RESEARCH.md`, `01-DESIGN-AND-PLAN.md`
- `%LOCALAPPDATA%\harness-config-autosync\status.json` on both machines
- the six probes in `00-RESEARCH.md` §2; tailnet name `zabz-yoga-1.tail93e6e6.ts.net`

---

## 2026-09-11 17:30 · ZABZ-YOGA · The harness shows money now — a cited rate card, `/cost`, and a footer cost pill

**CHANGED**
- **The GUI can show cost, and the seam was already there.** The footer's stats row is an additive
  `list` Slot (`conversation.composer.dock`, declared `replaceRisk: "none"`), so a cost pill is a fresh
  `id` beside the shipped pill — **no patching of `dsh-client-ui-chat`, no patching of any bundle.**
  Recon also established what does *not* exist: the session-level `tokenUsage` projection carries four
  integers and **no provider, no model, no time**, and there is **no money anywhere** in `@deepseek-ai/*`
  (every `price` hit is image *visual-token* pricing; the only real USD rates ship in upstream
  `@earendil-works/pi-ai` catalogs, which `dsh-llm-pi-ai` zeroes with `NO_COST`).
- **New package:** `harness-config/packages/plugin-cost` — its own `dsh.bundle` patch, its own
  `dsh.client` half, and the project's **authoritative `pricing.json`** (every rate carries its URL and
  read date). `src/*.mjs` are real testable modules; `lib/*` is generated from them by
  `scripts/build.mjs`, so the tested code and the shipped code are the same bytes.
- **New tool:** `~/code/dsh-cost` — a standalone analyzer (`session`, `list`, `latest`, `pricing`,
  `--json`), plus `validate.mjs` (proves our totals against the harness's own projection) and
  `pricing-drift.mjs` (proves the two rate cards agree). It reads the package's card, falling back to its
  own copy only when the checkout is absent.
- **Installed** into the web profile on this machine (`pnpm add file:…`), and `dsh-plugin-cost` added to
  `dsh.profile.bundles` in `~/.dsh/profiles/web/package.json`.

**VERIFIED — measured, not assumed**
- **The totals reconcile with the harness.** `node lib/validate.mjs --verbose` and
  `node test/analyze.test.mjs` replay the harness's own `tokenUsage` projection over every
  session log here: **24/24 logs, our total == the GUI's total, zero differences** (56/56
  assertions). This is the check that matters, because the footer's number and ours are now
  the same quantity by construction.
- **The arithmetic is exact.** Integer micro-dollars, so `sum(turns) === session` exactly (asserted on
  every log); the peak-rate upper bound is never below the actual cost; an unpriced route returns
  `undefined` rather than a neighbour's rate.
- **The plugin resolves and renders.** `node test/verify.mjs` → 4/4: generated files current; rates +
  peak/off-peak + sample validation + the fold against real logs; the browser half registering and
  rendering under a reproduction of the module-loader contract (fake `window.__ModuleLoader__`, stub
  React); and the package resolving **by name from the profile directory** with a usable `dsh.client`
  and `dsh.bundle`.
- **The rate card is live-confirmed.** `GET https://api.deepseek.com/models` → HTTP 200 returning exactly
  `deepseek-flash` and `deepseek-v4-pro`. So `deepseek-v4-flash` / `-vision-exp` are retired aliases (the
  pricing page's footnote 1 confirms they are served by DeepSeek-V4.1-Flash at the Flash price), and the
  card needs only two official rows. Card re-read from the live page, not from a report.

**THE NUMBERS, on real sessions**
- The 22-turn session of 2026-09-11 (`session-d772db00…`, 2.4 MB): **135,686,313 billed tokens, 97% cache
  hit, `$1.36` off-peak (upper bound `$2.19` at peak rates).** The most expensive single turn was **$0.33**
  — one turn, a third of the session. A footer-sized session is ~`$0.01`–`$0.16`.
- All 17 local sessions: **`$2.20`** total.

**IN FLIGHT**
- **Nothing is mounted in the running process.** The bundle list is read at profile boot, so the cost pill
  and `/cost` appear **after the owner restarts the web profile.** This is the honest state: installed,
  resolvable, tested — **not yet observed on screen.**
- The pill is a **client half**, and approval prompts are disabled in this session, so I did not attempt
  to mount it live. A first run in his session asks for one approval click; `/cost` is host-only and
  needs none.
- The pill's session figure is an **assumption** (deployment default route) because `tokenUsage` has no
  route; `/cost` is exact because it prices the log. The popover says so. Making the pill exact needs a
  host RPC that returns the real route — not built.

**BROKEN / KNOWN**
- **I leaked a live `DEEPSEEK_API_KEY` into this session's transcript** while writing the credential
  reader: my own error message interpolated the ref id, which *was* the key. Rewritten to print only
  lengths and booleans; recorded as **PAIN P13** and **LESSONS L44**. **Rotation is the owner's call and
  is not done.** A log scanner for key-shaped strings is not built.
- `dsh-cost` carries a **copy** of the rate card next to the authoritative one. `pricing-drift.mjs`
  detects divergence (exit 1) but nothing runs it on a schedule, so this is manual, like `sync.py` (P8).
- `~/code/dsh-cost` is **not a git repo** — it is local to ZABZ-YOGA, while the plugin that matters is
  version-controlled here and on the remote. That asymmetry is deliberate for now and is the first thing
  to fix if the fleet should have this on every machine.
- Pre-2026-09-10 sessions cannot be repriced from primary sources — that rate card is gone from the
  pricing page. Anything before that is priced with today's card and is an estimate.

**NEXT**
Restart the web profile and confirm two things on screen: the pill appears beside the stats pill, and
`/cost` prints a table. Then wire `pricing-drift.mjs` and `verify.mjs` into the same cron discipline the
sentinel has — a rate card that silently becomes two rate cards is exactly the P3/P8 class of failure, and
the checker already exists.

**EVIDENCE**
- projection agreement: `node dsh-cost/test/analyze.test.mjs` → 24/24 logs, 56/56 checks
- plugin suite: `node harness-config/packages/plugin-cost/test/verify.mjs` → ALL CHECKS PASSED
- live model list: `node dsh-cost/lib/probe-models.mjs deepseek` → HTTP 200, 2 ids
- money: `node dsh-cost/lib/cli.mjs session <log>` → `$1.36` upper `$2.19`; `list` → **`$2.96` grand
  total across all 24 session logs on this machine**
- card sources: `packages/plugin-cost/pricing.json` (DeepSeek pricing page, DeepInfra model pages)
- install state: `~/.dsh/profiles/web/package.json` lists the dependency **and** the bundle
- commit: `f349b05` pushed to `secretary-ts:/home/zabz/harness-config.git`

---

## 2026-09-11 13:12 · ZABZ-YOGA · The thirteen-day silence, investigated and labelled

**CHANGED**
- The owner was asked whether the zero-tick window was deliberate. **He did not know and asked for an
  investigation.** Done, from evidence rather than inference.
  **The host was up and healthy every single day; the work loop was dead.**
  - Last tick `2026-07-22T00:21:02Z` → first tick back `2026-08-04T18:06:44Z` = **13 days 17 hours**.
  - The machine was demonstrably alive throughout: files written on **every** day of the window
    (1992/17/12/88/40/13/45/34/24/24/3/2 per day), `logrotate` ran 2026-07-23 06:02, hundreds of
    writes into `~/.local/lib/python3.14/site-packages`, 101 under `/var/lib/dpkg/info`, and git
    operations on the app repo on Jul 26, Jul 29 and Aug 3.
  - The database is silent in **every** table, not just `tick_telemetry`: no work sessions, no model
    usage, no errors, no delegations. Three `activity_log` rows in twelve days. A dead *loop*, not a
    failing one.
  - `secretary-api.log` records the mechanism that kept it down: `Stale autopilot thread detected
    (last_run_at=2026-07-21T06:00:51…) — exiting`, after **six restarts in twelve minutes** on the
    evening of Jul 21, the last of which logged **"Startup complete (autopilot disabled)"**.
- Written up as a postmortem: `personal-secretary-mvp/docs/postmortem/2026-07-22-thirteen-day-silence.md`
  (commit `f25d8d333`), including three things that remain **unknown** rather than glossed.
- The kernel now **names this gap instead of re-discovering it**: `KNOWN_GAPS` in `ck/sentinel.py`
  reports *"largest historical gap 12d (2026-07-22 -> 2026-08-04) — known: thirteen-day silence…"*
  (commit `3778bac`, deployed and verified live on `secratary`). An answered question stops being
  re-opened every five minutes, which is the failure mode that produced P6's dismissal schemes.

**IN FLIGHT**
- **The kernel is doing its job unattended**: cron fires every 5 minutes; runs at 16:55, 17:00, 17:05
  all landed with provenance (`authoritative:true`, 203 tables). Latest: 4 findings need attention.
- Three postmortem action items are **open and unfixed**: the autopilot's stale-guard **disables instead
  of re-arming** (`app/autopilot.py`); the cron watchdog asserts process liveness, not outcomes; and the
  monitor lives on the machine it monitors (PAIN P20 — the heartbeats must go off-host).
- `latest.json` still prints `age=?` (PAIN P12); `ck trend` still unbuilt; kernel Phases 2–7 unbuilt.

**NEXT**
Fix the two liveness-shaped holes the postmortem names — the autopilot stale-guard re-arming itself, and
an off-host heartbeat that alarms on **absence** — because those are the exact conditions that produced
this outage, and they are still in place today. Then `ck trend` over the accumulating `history.jsonl`.

**EVIDENCE**
- `ssh secretary-ts`: `find` histogram per day; `logrotate` mtimes; `sqlite3 -readonly` last/first tick
- `~/secretary-api.log`, `~/secretary-startup.log` (the six restarts and the autopilot refusal)
- postmortem `f25d8d333`; kernel `3778bac`; `ck status` on `secratary` showing the labelled gap

---

## 2026-09-11 13:05 · ZABZ-YOGA · Home Assistant: audited live, and the security system is blind

**CHANGED**
- `ha-config` has a **live truth surface** now: `scripts/ha_truth.py` (read-only collector over
  HA's own REST **and** WebSocket-admin surfaces, with provenance packets and deterministic severity
  findings) plus `scripts/ha-truth.ps1` (runs locally or on an always-on host over SSH). Verified
  end-to-end three times from the Yoga against the live system via `secratary`; JSON + Markdown land
  in `.runtime/` (git-ignored by design).
- `docs/AUDIT-2026-09-11-live-systems.md` — the first live-grounded audit since 2026-04-17. Committed
  as `7be821d`; `ha-config` is now **7 commits ahead of `origin/main`**, still unpushed.
- `docs/DISPOSAL-PLAN-2026-09-11-dead-generations.md` (`6e89501`) — removal plan for the four piles of
  dead logic, deliberately *not* the removal: manifest → repo-wide reference grep → backup → batches of
  ten with exact-count verification → regression assertion using the collector's own finding codes.
  Key numbers: **42 orphaned Keymaster entities with no config entry and no device**, **390 registry
  entities with a collision suffix (only 18 live, and 12 of those are legitimate Dahua sub-streams that
  must not be touched)**, **82 unloaded automations** (`disabled_by=null`, so the question is whether
  their YAML still exists), **834 entities disabled by their own integration — no registry surgery**.
- Raw evidence persisted on the always-on host (not just in a session's `/tmp`):
  `/home/zabz/ceo-kernel-var/ha/truth-20260911T1701Z.json` and
  `…/disposal-evidence-20260911T1705Z.json`.
- The collector's first run found a bug in itself and refused correctly (`/api/error_log` is text, not
  JSON) — fixed, re-run, verified. That refusal is why the log section is real instead of empty.
- Journal IDs collided with a concurrent session's (both wrote P15/P16). Mine are now **P17/P18**,
  append-only with the collision recorded in P17. See P13 — same cause.

**FOUND** (reads dated 2026-09-11 16:55–17:00 UTC; HA Core 2025.10.3)
- **CRITICAL — the intrusion system's primary trigger is blind.** `binary_sensor.phoenix_outside_door_contact`,
  its interior sibling, and the raw contacts went `unavailable` at **01:48 local** and have not
  recovered. Three Zigbee devices failed to rejoin at boot; the mesh is otherwise healthy
  (`zigbee2mqtt_bridge_connection_state = on`, v2.6.2, other nodes reporting live), so this is
  device-level, not a dead coordinator.
- **CRITICAL — evidence capture fails on every trigger.** The Dahua integration is config-entry
  `loaded` while `192.168.50.170:80` is unreachable: **365 snapshot errors** in one log span
  (`snapshot_latest_with_retries` 276, `snapshot_control_room_cameras` 48, `snapshot_entry_cameras` 41).
  The intrusion chain's "critical evidence" step cannot succeed.
- **HIGH — 41 Keymaster entities still loaded** beside the documented Phoenix path (April: 37; it grew).
  82 of 150 automations `unavailable`. 114 entities carry registry collision suffixes (`_2`…`_10`).
- **HIGH — Core is 11 months behind**; the `spotify` entry loops on a revoked refresh token
  (**683 log lines**), ~4 errors/minute of pure noise.
- **MEDIUM** — dead `zha` config entry (0 devices in the registry), `ipp` printer not loaded,
  `tplink` device unreachable, NUT flapping; 834 integration-disabled registry entities; **all 1895
  registry entities have no area**.
- **Verified healthy, for balance:** intrusion scripts and automations all present,
  `rest_command.phoenix_security_page` and `secretary_ptt` registered, phone notify targets present,
  apartment deadbolt `locked`, and the repo's newest five commits **are** live (every snapshot script
  exists on the host).

**IN FLIGHT**
- **`ha-config` Part 1 is code-complete but has never actually run**: `.runtime/`,
  `docs/PART1_RUNTIME_SUMMARY.md` and the inventory documents do not exist anywhere, because every one
  of those scripts needs SSH.
- Parts 2–7 of the overhaul (access control, presence, cameras/evidence, notifications, climate,
  security response, data hygiene) have **no roadmap documents** — the master plan names them, nothing
  specifies them.

**BROKEN**
- **SSH to the HA host is closed** (tcp/22 refused on `192.168.50.34` while 8123 answers; verified from
  `secratary`, office LAN, 2026-09-11 16:52 UTC). Consequence: `check.ps1`, `deploy.ps1`, `backup.ps1`,
  `prune-backups.ps1`, `inventory.ps1` and `refresh-runtime-truth.ps1` **cannot run at all**, and
  repo-vs-host `/config` drift cannot be proven. Worked around, not solved — the audit says so.
- Add-on versions/states, HAOS version and the update backlog are **unverified**: they live on the
  Supervisor API, which the Core token does not reach.

**NEXT**
- The owner's decision on the security blind spot: attempt a remote recovery of the three unjoined
  Zigbee devices (reload the integration / re-pair), or leave it until someone is physically at the
  office on Sunday. Everything else on the list is mine and proceeds read-only regardless.
- Independently: ask for the HA SSH add-on to be restarted so Part 1 can actually run once.

**EVIDENCE**
- `~/code/ha-config/docs/AUDIT-2026-09-11-live-systems.md` (§8 lists every read with its time)
- `~/code/ha-config/scripts/ha_truth.py`, `scripts/ha-truth.ps1` (commit `7be821d`)
- `~/code/ha-config/.runtime/ha-truth.json` + `.runtime/ha-truth.md` (git-ignored; regenerate with
  `scripts/ha-truth.ps1 -ViaSshHost 100.84.72.88 -SshAcceptNewHostKey`)
- Live reads: `/api/config`, `/api/states`, `/api/services`, `/api/error_log`, WS `config_entries/get`,
  WS `config/entity_registry/list`, WS `config/device_registry/list`

---

## 2026-09-11 13:02 · ZABZ-YOGA · Inventoried the WAZE/MDM/DRN/LPT stack and fixed a silent billing data loss

**CHANGED**
- **Fixed a real, ongoing data loss.** The daily `telnyx_billing.py --snapshot` cron wrote to an
  orphaned SQLite file (`/data/fleet.db`) while `fleet_api` reads PostgreSQL, so **both**
  `fleet_telnyx_*` tables in Postgres were permanently at 0 rows while every log line said success.
  Two defects: `_connect_db()` preferred SQLite unconditionally, and the per-SIM insert named a
  `customer` column Postgres never got, with the failure swallowed by a bare `log.warning`.
- `_connect_db()` now **prefers Postgres when `PG_DSN` is set**, via a small sqlite3-compatible shim
  (`?` → `%s`, dict rows) so the two dialects cannot drift. `persist_snapshot()` returns success/
  failure, rolls back on error, and the CLI **exits 2** instead of printing success when nothing landed.
- **Recovered the stranded history into Postgres:** 12 usage + 18 ledger rows, 2026-09-06 → 09-11.
  Proved idempotent (re-run inserted 0, skipped 30).
- **Installed a regression guard:** `operator-tools/telnyx_usage_freshness.py` refuses (exit 2) when it
  cannot see the data and fails (exit 1) if the newest usage row is >26 h old. In cron at **05:00
  daily**, after the 04:30 snapshot. Currently: `OK: 2 usage rows, newest 0.0h old`.
- `deploy/waze-mdm/docs/holdings-2026-09-11.md` — a verified inventory of the whole WAZE/MDM/DRN/LPT
  stack and exactly where it is holding. Commit `6f2a5195b`.
- Crontab backed up to `/root/crontab.bak-20260911` before editing.

**VERIFIED STATE (read live, not assumed)**
- Hetzner fleet-api: `{"status":"ok","nanomdm":{"version":"v0.9.0"},"mode":"direct"}`; container
  `healthy` after rebuild. 11 containers up.
- Fleet: **65 devices** (63 `lakewood` + 2 `lpt`), 55 deployed / 9 retired / 1 deploying,
  55 healthy / 1 warning / 0 critical / 0 offline / 0 stale.
- **The ~19,300-command backlog from the previous handoff is GONE** — `avg_queue_depth=0`, per-device
  `pending=0 notnow=0`. The queue reads 114/91 residual rows on the two LPT devices, not pending work.
- LPT devices DRN **2001**/`FFYGNQ8AN72J` and **2002**/`FFXGT23HN72J` both `deployed`, wallpapers
  rendered, last MDM check-in **2026-09-11 01:27 UTC** (~15 h before this read).
- Live portal endpoint works: 2001 = 5.6 MB / 2.0 GB (0.3%), 2002 = 183.1 MB / 2.0 GB (9.2%), both
  `state=active`. The customer-facing usage number is correct — **it calls Telnyx live**.
- `lpt-flip-phone` working tree **clean**, last commit `84e42d53` **2026-07-20**.

**IN FLIGHT**
- **Kosher Waze customer integration is gated on owner decisions, not engineering.** Q1–Q7 answered,
  **Q8–Q28 unanswered**, and the plan doc frames all 21 as owner questions. **They are not.** Only
  **four** are genuinely his: (1) billing shape — is `$9/mo · 250MB · 800MB cap · $18/GB` final, and does
  the portal *collect* money or only *show* it? (2) self-serve line — do customers get pause/resume, and
  is customer-triggered lost mode allowed? (3) cap behaviour — pause, throttle, or throttle+upsell at cap?
  (4) location/compliance — do we store any trip data, and any constraint before payments? The rest are
  factual or engineering calls that are mine. **This is the next thing to do.**
- Only the daily cron snapshot path is asserted. A manual `--report` also persists and is unguarded.

**BROKEN / KNOWN**
- **`docs/drn/generated/` holds 8,182 files and grows ~2,800/day** — a 463-byte JSON+CSV pair written
  every ~30 s by `scripts/drn-export-live-phone-source.py`, **always empty** (`rows_total: 0`). The
  invoker is not on this host (no process, no scheduled task) — **driven from elsewhere in the mesh,
  unidentified**. Pure waste; safe to clean since every file is empty.
- **87 `fleet_alerts` rows are all stale noise**, every one a `warning` timestamped **2026-07-12**
  reading "last seen: never". They inflate `fleet-health` and mask real alerts.
- `installed_profiles()` is structurally useless — `device_profiles` is always empty, so it reports
  "none" regardless of reality. **It lies to an operator.** Reimplement via `ProfileList` or delete it.
- `fleet.ps1 sql` is broken (`Unknown command: Invoke-SqlOnHetzner`). Use
  `scripts/Invoke-SqlOnHetzner.ps1` directly, or pipe SQL over ssh on stdin.
- `data_limit_gb` reads **2.0** on both LPT devices; intended default is **0.8**.
- Unchanged: three divergent `secretary.db` copies (P3), evolution loop not closing (P4),
  `engineering_indexer` dead weight (P5), 7 critical + 46 urgent messages held (P6).

**NEXT**
Answer the **four** owner questions above — one at a time, with a recommendation — and record each in
the plan doc's ANSWER LOG. Do not route the other 17 to him; answer them from the live config and the
findings in `holdings-2026-09-11.md`.

**EVIDENCE**
- `deploy/waze-mdm/docs/holdings-2026-09-11.md` (this session's inventory, every reading sourced+aged)
- `deploy/waze-mdm/fleet-api/telnyx_billing.py` (dual-dialect `_connect_db`, honest `persist_snapshot`)
- `deploy/waze-mdm/operator-tools/telnyx_usage_freshness.py`, `telnyx_migrate_sqlite_history.py`
- Commit `6f2a5195b`; crontab backup `/root/crontab.bak-20260911` on Hetzner
- Postgres now: `usage|14| 2026-09-07 02:05 → 2026-09-11 16:57`, `ledger|19| 2026-09-06 23:18 → 2026-09-11 16:57`
- LESSONS **L34** (a job can succeed and write nowhere anyone reads)

---

## 2026-09-11 19:05 · ZABZ-YOGA · The `+` control exists, and the app no longer opens eight windows at you

**CHANGED**
- **`packages/plugin-windows`** (new): a `+` control beside the composer. Clicking it navigates the page to
  `dsh-new://open`, which Windows hands to `dshw.ps1 new` — one new window, one new conversation. The host
  half is deliberately inert, so the engine is never a process-spawning pipe for a page and `dshw new` stays
  the single implementation of "open another window". Protocol registered in `HKCU\Software\Classes\dsh-new`.
  Verified present in the payload the engine serves (`plugin rows in the payload: dsh-plugin-windows`).
- **`dshw up` no longer opens windows.** Starting the engine and opening windows are separate intentions; the
  default is engine-only. Windows come from `dshw new`, the `+` control, or the desktop shortcut
  (`-WindowsMode yes`). The logon task was re-registered with `-WindowsMode no`.
- Restarted the fleet engine with state recorded, and taught `_scratch/start-fleet-engine.ps1` + `verify-boot.ps1`
  to bring an engine up and read back exactly what it serves.

**ROOT CAUSE of the screen he sent**
`HARNESS / Failed to load plugins / web boot: 1 entry did not activate / dsh-plugin-cost: pending (waiting for
services: …)`. The browser loader resolves **every** name in a plugin's `inject` and in the package's
`dsh.client.inject` as a *service*, and holds the entry at `pending` until each one exists. `plugin-cost`
declared two package ids and later `optional: ['slots']`; none ever resolved, so the entry never activated and
the loader **asserted, blanking the entire UI** (shell bundle `assertEntriesActive`). A broken cost pill took
the whole interface down. Fixed in the package (declares nothing; reads slots with `ctx.get('slots')`,
rebuilt and verified byte-for-byte). **The cost bundle is unmounted in the local profile for now** — the
interface had to work before the decoration, and the pill has not been re-verified. L103, P18.

**ALSO FIXED**
- `Stop-ServerTree` assigned `$pids`; PowerShell's read-only `$PID` is the same name case-insensitively, so the
  function threw and `dshw restart` **hung for seven minutes with no output** — twice. Renamed. L104.
- `dshw up`'s summary printed the number of windows it *considered*, not opened.

**BROKEN / KNOWN**
- The cost pill is unmounted (above). `/cost` is gone until it is re-verified.
- The stranded engines on 3080 and 3085 still exist beside the fleet on 3099; the eight old fleet windows lost
  their session when the engine was restarted, so their pages need a reload.
- `dshw down/stop` must be re-tested now that `$pids` is fixed; the path was never exercised after the rename.

**NEXT**
Re-verify the cost pill, remount it, then re-test `down`/`stop`, then deploy `plugin-windows` + the protocol
registration to ZABZ-TECH (pull, copy the package into the profile, `dshw tasks-import`).

**EVIDENCE**
- commits `d68c380` (button + three fixes), `01debd2` (L103/L104), `513e1ab` (P18)
- `C:\Users\ezabz\.dsh\profiles\web\package.json` (bundles: base, web-app, plugin-windows)
- `HKCU:\Software\Classes\dsh-new\shell\open\command`
- `verify-boot.ps1` output: index 27,879 bytes, `mentions plugin-windows: True`, `mentions plugin-cost: False`

---
## 2026-09-11 18:10 · ZABZ-YOGA · The fleet heals itself, and the ninth window is one shortcut away

**CHANGED** (commits `6f3bf38`, `dbc4e01`)
- **`dshw health` — the missing watchdog.** Idempotent, additive, and deliberately narrow: it starts
  **only** a server that should be listening and is not. It never stops or restarts a live engine, never
  opens a window, and writes to `health.log` only when it acts. Safe to run twice at once — the port bind
  *is* the lock, and the loser dies on `EADDRINUSE` instead of becoming a second writer on one `DSH_HOME`.
- **`dshw watchdog on|off`** — Task Scheduler, every 5 minutes, this user, hidden. Registered and verified
  (`DSH Window Fleet Watchdog`, repetition `PT5M`).
- **Verified self-healing end to end:** killed the engine on 3099 → `dshw health` rebuilt it in **23.9 s**
  → a second call was a clean no-op ("healthy: all 1 enabled engine(s) listening"). Cold start from a
  non-default state dir and profile root also worked (23.6 s), which is the portability evidence for the
  desktop.
- **One-click new window:** `%USERPROFILE%\Desktop\DSH Windows.lnk` → `dshw.cmd up`, Edge icon, minimised.
  `dshw new` opens a ninth window on demand and does not require the slot to be `enabled`.
- **`sync.py` now manages `profiles/<name>/cordis.patch.yml`** — the profile patch layer belongs to
  harness-config, not to the local `~/.dsh`. First payload: the WebSocket heartbeat raised
  2 s → 15 s, because that value is both the ping cadence *and* the pong deadline, so a 2 s stall used to
  kill all twelve windows' sockets in the same tick.
- **README documents the fleet and the profile-patch layer**; a new session no longer has to read the
  journal to find out what `dshw` is.
- Landed the **single-engine scaling audit** (`docs/multi-window/research-single-engine-scaling.md`, 709
  lines, code-level): the strongest structural findings are unbounded per-client stream Deques, one
  cross-session serialized projection-cache write chain, and a durable session flush before every request,
  tool dispatch and pre-step. None measured — structural only, and the report says so.

**CORRECTED (again, in the same direction)**
The first performance measurement POSTed `{}` to the API; every call answered **HTTP 200 with
`gateway/bad-request`**. The conclusion drawn from it was withdrawn (L36), and the fleet was re-measured
with real payloads. Real numbers: `settings/describe` 145 ms and `agentPresets/list` 98 ms carry the whole
per-window boot cost; 12 simultaneous windows cost 1.36 s each with 125 ms median event-loop lag, knee at
4. The larger number was never the engine — **nine windows at default Edge flags cost 6,951 MB across 97
processes** while the engine sat at 229 MB. Lean flags cut that 41% (770 → 454 MB/window).

**IN FLIGHT**
- **ZABZ-TECH is unverified.** The launcher resolves node, the dsh bin, the browser and `DSH_HOME` per
  machine, and the README records the two shell commands that install the autostart and watchdog tasks
  there; but nothing has been run on that box, and it is on the other network.
- **The engine on 3080 is still the owner's hand-started GUI**, not managed by the fleet (fleet is 3099).
  Two origins, two cookie jars, one session store. Adopting it means restarting the session he is talking
  to, so it is his call, not a silent change.

**BROKEN / KNOWN**
- `dshw down` stops engines, never windows — deliberate, because the only way to force-close them is to
  kill every Edge process whose command line carries the profile path.
- **PAIN P16 remains:** a backgrounded window can grow host-side buffers without bound (upstream: no
  byte-level backpressure on the downlink). Now *detectable*: the watchdog restarts a dead engine and
  `status` prints whole-tree memory, but nothing watches memory as a trend.

**NEXT**
Adopt the fleet port on ZABZ-TECH, then decide question 3 (session addressability) — the highest-value
remaining UX gap, and the same client-plugin work as question 7 (a fleet panel).

**EVIDENCE**
- `multi-window/dshw.ps1` (`health`, `watchdog`), `multi-window/windows.json`, `README.md`
- `Get-ScheduledTask -TaskName 'DSH Window Fleet Watchdog'` → State `Ready`, repetition `PT5M`
- `Get-ScheduledTask -TaskName 'DSH Multi-Window Launcher'` → State `Ready`, At-logon
- `C:\Users\ezabz\.dsh\multi-window\health.log`, `state.json`, `logs\<port>-<stamp>.log`
- `docs/multi-window/PERFORMANCE-MEASURED.md`, `research-single-engine-scaling.md`

---
## 2026-09-11 14:00 · ZABZ-YOGA · Twelve DSH windows are now a supervised thing, not a hope

**CHANGED**
- **`multi-window/dshw.ps1` + `multi-window/windows.json` are in `harness-config`** (commits `f40579e`,
  `6ceffe5`). Commands: `up`, `down`, `restart`, `status`, `windows`, `new`, `open <slot>`,
  `stop <slot>`, `logs <slot>`, `autostart on|off`, `doctor`. One engine, many windows.
- **Verified live, not asserted:** engine on port 3099 (pid 5756 at the time of writing) with **8 Edge
  app windows open at once**, one browser profile each, all 8 with their own cookie jar and Local Storage
  (which is what makes each window's session choice its own). `dshw status` reads
  `1 engine(s) live, 8 window(s) open, 196 MB engine RSS, 206 MB whole engine tree`.
- **Autostart registered and verified:** scheduled task `DSH Multi-Window Launcher`, At-logon, this user,
  runs `dshw.ps1 up`. State `Ready`. That is the "close DSH, reopen it, the windows come back" answer.
- **The official DSH desktop app is not the answer and must not be planned around.** It exists as source
  only (`apps/desktop`, `"private": true`, no release assets, npm E404, CDN 404) and
  `src/single-instance.ts` calls `requestSingleInstanceLock()` — **one window per machine by design**.
- **A DSH session is not addressable by URL.** Zero `pushState`/`location.hash`/`sessionId` in all 65
  installed client bundles; the SPA is served only at `/`; the chosen session is
  `localStorage["dsh.sessions.current"]`, keyed by origin, read once at page load. Proven from the
  LevelDB of two window profiles. Restoring a window to a specific session needs a client-side UI
  change — open question 3 for the owner.
- Research is committed under `docs/multi-window/` (analysis, questions, four research reports, brief).

**CORRECTED (this session, before it could spread)**
The first design put each window on its own engine and port. **Wrong economics.** Each engine eagerly
starts its own five stdio MCP bridges: measured **~1.4 GB of tree per engine** (26 descendants), so
8 engines ≈ 11 GB and 12 ≈ 17 GB, against **7.7 GB free** on this laptop. One engine with N windows is
~2.7–3.1 GB. Also corrected: a *window* is not a session and a session is not an engine; conflating them
is what made the original plan look cheap.

**IN FLIGHT**
- The 8 open windows on port 3099 **do not have their intended geometry** (7 of them are at 0,0): the
  layout is in `windows.json` now, so `dshw restart` fixes it. Latent until then.
- `dshw new` opened slot 9 as a ninth window during testing; slots 9–12 are still `enabled: false`, which
  does not stop `new` (deliberate: `new` means "give me another window").
- **No health watchdog** (PAIN P14): nothing polls the ports, so a dead engine is silent until looked at.
  The At-logon task only fires at logon.
- **No layout memory** (PAIN P15): a dragged window returns to `windows.json` coordinates on the next up.

**BROKEN / KNOWN**
- `dshw down` does not close browser windows — it stops engines. Closing windows stays a human action,
  deliberately, because the only way to force-close them would be to kill every Edge process with the
  profile path, which is one bad pattern away from killing the owner's own browser.
- The engine started by hand on **3080 remains the owner's working GUI** and is untouched by the fleet;
  `primaryPort` is 3099 so the two cannot fight over a port.

**NEXT**
Ask the owner question 1 (topology) from `docs/multi-window/QUESTIONS.md`, then restart the fleet on the
real port and confirm the 4×2 layout.

**EVIDENCE**
- `multi-window/dshw.ps1`, `multi-window/windows.json` (commits `f40579e`, `6ceffe5`)
- `docs/multi-window/ANALYSIS-AND-DECISION.md`, `QUESTIONS.md`, `research-*.md` (4 reports)
- `C:\Users\ezabz\.dsh\multi-window\state.json`, `logs\<port>-<stamp>.log`, `windows.log`
- `Get-ScheduledTask -TaskName 'DSH Multi-Window Launcher'` → State `Ready`, trigger At-logon
- Per-profile proof: `...\multi-window\browser\w1..w8\Default\{Cookies,Local Storage\leveldb,Preferences}`

---
## 2026-09-11 12:55 · ZABZ-YOGA · The open verification is closed, and the kernel now runs by itself


**CHANGED**
- **The one unproven thing is proven.** This session runs preset `zabz` — read from the harness's own
  session record, not asserted — and the secretary bridge is live: the 14 `mcp__secretary__ps_*` tools
  are registered, and `ps_company_status` returned real company data (6 active goals, today's model
  usage). Previous HANDOFF's NEXT is done.
- `ceo-kernel` is now a **git repo with a remote on `secratary`**
  (`secretary-ts:/home/zabz/ceo-kernel.git`), mirroring `harness-config`: LF policy, `.gitignore` for
  runtime state, and the server is a **checkout, never edited in place**.
- Deployed to `/home/zabz/ceo-kernel` from git (pre-git copy moved aside, not deleted), and **the
  sentinel now runs on cron every 5 minutes**. `scripts/run-sentinel.sh` writes `latest.json` and
  `history.jsonl` to `/home/zabz/ceo-kernel-var/` — outside the working tree, because a scheduled job
  must never dirty the repo it lives in. **PAIN P2's remaining item is closed.**
- First authoritative reading, `secratary`, 2026-09-11T16:50Z: **4 findings need attention**
  - `tick_completion` — 4 collapse windows in 120 days with data; worst `2026-06-14..2026-08-04`,
    10,355 ticks, 32% complete
  - `attention_debt` — 7 critical + 46 urgent held; oldest question 131d
  - `agent_dead_weight` — **5 agents** completing ~nothing, worst `engineering_indexer` 172 ticks / 0
  - `evolution` — 56 unapplied; 30 duplicate offers on `app/services/activity_sync.py`
- **The kernel can now see absence, which it could not before.** Every check grouped rows that
  exist, so a day on which nothing ran was invisible by construction — the exact failure the kernel
  exists to catch. Added `check_telemetry_gaps`, and fixed every span to count calendar days rather
  than rows (see the correction below).
- **NEW FINDING, from that check: a 12-day total outage nobody had flagged.**
  `2026-07-23 .. 2026-08-03` — **zero tick rows for twelve consecutive days.** Cause unknown, not
  investigated. It is now permanently visible in every report (`telemetry_gaps`). The last 30 days
  are fully covered, so this is historical, not live.

**CORRECTED (this session, before it could mislead anyone)**
The first reading said "4 collapse windows in **120 days**" and labelled the worst "**30d**" while it
spanned `2026-06-14..08-04`, 52 calendar days. Both were counting **days that have rows**, not elapsed
time — so the 12-day hole above sat inside the quoted window and was reported as if it had not
happened. Spans now read `120 days with data across 148 calendar days` and `30d of data over 52d`.
Found by reading live data, not by review.

**FOUND BY ACCIDENT, AND IT MATTERS: seven other sessions were running in this same directory**
At 12:58 there were **eight live DSH sessions** on one DSH server process, all preset `zabz` — cost
estimates, Home Assistant audit, Waze MDM status, extension mapping, three read-only recon sessions,
and this one. One of them wrote `journal/reference/deepseek-token-pricing-2026-09-11.md` into
`harness-config` while this session was editing the journal, and this session's `git add -A` committed
it (in `4becfa4`) under a message that does not mention it.
**That file is not mine, and I have not verified its numbers.** It appears legitimate and well-sourced,
and its headline claim — every `deepseek-official` id is served by V4.1-Flash at Flash price — is
consistent with the owner's own statement recorded in L26. Treat it as a claim from another session
until checked.
Consequences recorded: PAIN P13 (shared tree + `git add -A`), LESSONS L33 (stage explicit paths).
Also measured and worth knowing: the MCP bridges compose **once per process, not once per session** —
seven extra sessions added no bridges — and the real memory cost per concurrent session is its shell
runner at ~58 MB, not the tools (PAIN P14).

**CORRECTED — PAIN P10 was wrong, and it was wrong in the exact way this journal exists to catch**
P10 claimed repeated mount-validation spawns duplicate MCP servers ("four `ps_mcp_server.py`"). **It
does not.** The number came from filtering process command lines for `personal-secretary-mvp` — a
*directory* — which matches every script in it: 1× `ps_mcp_server.py` plus 3× `mcp_launcher.py`
(firecrawl, jina, context7). Counted by script name: **one bridge per server, exactly.** Separately,
every venv-python launch appears as two processes (a ~4 MB parent and the real 14–63 MB child),
reproduced with a `time.sleep` payload containing no spawn code — so a naive process count
double-counts every python bridge. LESSONS L28/L29.

**IN FLIGHT**
- **The cron job is verified firing unattended:** runs at 16:51:24 (by hand) and **16:55:02 (by cron,
  nobody asked)**. Two history lines, both authoritative, `total:8` checks.
- `latest.json` packets print **`age=?`** — the freshness assertion exists but is unmeasured for most
  checks. Recorded as PAIN P12. This is the largest remaining honesty gap in Phase 1.
- ceo-kernel **Phases 2–7 unbuilt** (inbox, ledger, gate, preset tools, daemon, evolution). The cron
  job is the **interim** form of Phase 6 and must be replaced, not duplicated, when the daemon lands.

**BROKEN / KNOWN** (unchanged unless noted)
- **12-day total outage `2026-07-23..2026-08-03`, cause unknown** (new, above) — historical.
- **Seven other sessions share this project directory** and may write into any repo under it (P13).
- Three divergent `secretary.db` copies (P3); evolution loop not closing (P4); 7+46 held messages
  (P6); `harness-config` sync still manual (P8); 5 dead-weight agents (P5, up from 1).

**NEXT**
`history.jsonl` now accumulates a line every 5 minutes and **nothing reads it**. The smallest useful
step is `ck trend` — read those lines, say what changed since yesterday. Then Phase 5: expose
`ck status` to the face as a tool, so the CEO reads its own kernel in one call instead of an SSH round
trip. Third: close P12 (`age=?`) so a reading can prove it is current.

**EVIDENCE**
- preset: `~/.dsh/storages/session_projcache/sessions/session-3ca4f3f2-….json` → `"agentPreset":"zabz"`
- bridge: live `ps_company_status` returned 6 active goals + 8 models of today's usage
- kernel: `/home/zabz/ceo-kernel` @ `496899f`; `ck doctor` → `AUTHORITATIVE`, 203 tables, 2.4 GB
- schedule: `crontab -l` on secratary ends with the `*/5` entry; backup `~/crontab.bak-20260911-165133`
- state: `/home/zabz/ceo-kernel-var/run.log` → `16:51:24 exit=1` (by hand) and **`16:55:02 exit=1`
  (by cron)**; `history.jsonl` holds both lines, `authoritative:true, tables:203`
- absence: `telemetry_gaps` → *"a tick row exists for every day in the last 30; largest historical gap
  12d (2026-07-22 -> 2026-08-04)"*

---

## 2026-09-11 · ZABZ-YOGA · Built the conversational CEO and its memory

**VERIFIED STATE (both workstations, checked not assumed)**
- `zabz` is the default preset on **ZABZ-YOGA and ZABZ-TECH**; second sync run on each is fully clean.
- Model is **`deepseek-flash`** on both (reverted; see the correction below).
- `zabz` is **25 rows**: full toolbelt + background-first shell policy + **6 MCP bridges**
  (secretary, firecrawl, jina, context7, fetch, playwright).
- Mount validation: **`mounted OK: zabz`**.
- **The MCP servers genuinely spawn** — proven by process tree, not assumption. DSH pid 11744 had
  children running `ps_mcp_server.py`, `mcp_launcher.py`, `mcp-fetch-server` and the Playwright MCP.
- `ceo-kernel` Phase 1 runs on `secratary` and its sentinel found two things manual analysis missed.

**CHANGED, THEN REVERTED — read before touching model settings**
The default model was briefly switched to `deepseek-v4-pro` on the assumption that "pro" meant more
capable. **The owner corrected it: 4.1 Flash is better and cheaper.** Verified afterwards: the API
advertises only `deepseek-flash` and `deepseek-v4-pro`, `deepseek-v4.1-flash` is rejected by name,
and Flash and Pro returned byte-identical usage on an identical probe. Reverted. LESSONS L25–L27:
do not change a cost-bearing default on a hunch.

**THE ONE THING STILL UNPROVEN**
The preset default is chosen **at session start**, so `settings.yaml` saying `zabz` does not mean any
running session uses it. `self_audit` showed the live session on `cordis` because the DSH process
started one second before the settings were written. **A profile restart is required**, and a real
session on `zabz` has still never been observed. First check after restarting: `self_audit` should
report the agent's preset as `zabz`, and the tool catalog should include `mcp__secretary__ps_*`.

**ALSO FOUND — the running process does not hot-reload the preset default**
The model namespace *does* re-read per request (a model change applied live), but the **preset** is
fixed at session start. Recorded as PAIN P11: a change can be reported as done while having no
effect. Rule adopted: no claim about a preset without a live agent reporting that preset.

**IN FLIGHT**
- `zabz` is installed and defaulted on **both** workstations (Yoga and desktop), each verified with a
  clean second sync run. A **profile restart** is required for the default to take effect.
- **The one unproven thing: the secretary MCP row's 14 tools have not been observed registering in a
  live session.** What *is* proven: the preset mounts (`mounted OK: zabz`); the row resolves
  **enabled** on win32 (`disabled: !!js process.platform !== 'win32'` evaluates false); both paths
  exist; the venv python imports the `mcp` SDK; the `dsh-mcp-client` package is present (0.1.5-rc.2);
  and an independent handshake against `ps_mcp_server.py` returned all 14 tools. What is *not* proven
  is that the client completes that handshake at preset mount time and registers them. **First session
  on `zabz` should list its tools** — if `mcp__secretary__ps_*` is absent, this is the thread to pull.
- `ceo-kernel` is staged on `secratary` at `/home/zabz/ceo-kernel` and runs, but **not scheduled** —
  it only runs when invoked. Phase 1 is complete; Phases 2–7 (inbox, ledger, gate, preset tools,
  daemon, evolution loop) are designed in `ceo-kernel/docs/DESIGN.md` and not built.

**BROKEN / KNOWN**
- Three divergent `secretary.db` copies; nothing yet prevents writes to a stale replica (PAIN P3).
- Evolution loop still not closing: 56 unapplied, 30 duplicates, 13 node_modules targets (PAIN P4).
- `engineering_indexer`: 172 ticks, 0 completions (PAIN P5).
- 7 critical + 46 urgent messages held undelivered (PAIN P6).
- `harness-config` sync is **manual**. Nothing schedules it, so drift resumes the moment someone
  forgets to run it. A scheduled pull is a small, high-value fix.

**NEXT**
Open a session on `zabz` and confirm the tool list — specifically whether `mcp__secretary__ps_*`
appears. That closes the only open verification, and it is the difference between a CEO that can talk
and one that can act on the company.

**EVIDENCE**
- `~/code/harness-config/presets/zabz/agent.cordis.yml` (20 rows)
- `~/code/ceo-kernel/ck/{provenance,sources,sentinel,cli}.py`
- `~/code/personal-secretary-mvp/docs/secretary-replacement-audit/` (7 documents)
- Sentinel run on `secratary`: 4 findings, including `engineering_indexer` dead weight and a
  131-day-old question — both new discoveries

---

## ⚠ ID allocation — read before adding an entry (2026-09-11)

(UNCHANGED HEADER — see the lessons file for the allocation rule.)

## 2026-09-11 · Fleet monitoring was dead for 67 days; now it is not

**This is the headline of the session.** Every monitoring signal for the Kosher Waze / LPT fleet was
blind, and no alert ever fired. Established by direct measurement, not inference:

- `fleet_devices.last_seen` is **NULL for all 65 devices**, always, and **no code path writes it**.
  Anything reading it concludes every device is stale — which is why an earlier "stale devices" reading
  was meaningless.
- `/fleet/sweep` runs from cron **every minute** but selects only `state = 'registered'`. There are
  **zero** such devices, so it selected nothing and wrote nothing. Forever.
- `fleet_queue_snapshots` last received a row **2026-07-05**; `fleet_device_health_history` **2026-07-06**.
- `fleet_alerts` had **no staleness producer at all** — the only insert in the module is an `info` note
  when Activation Lock is enabled. Hence silence since 2026-07-12.
- The real liveness source is `enrollments.last_seen_at` (NanoMDM's own check-in), which IS current and
  simply isn't what `last_seen` reads. **62 of 65 devices have not checked in for over a week; only 3
  in the last 24h.** That is the state the fleet was actually in while everything reported healthy.

**Built:** `/fleet/monitor/run` (+ `GET /fleet/monitor`), on cron every 30 minutes. Liveness from
`enrollments.last_seen_at`; 48h warning / 168h critical staleness; cap-proximity alerts at 80%/100%;
per-(device, category) alert de-duplication; and it **refuses** (`ok:false`) when no device has any
recorded check-in rather than reporting health from blindness. Verified: 62 alerts persisted, idempotent
across runs, health history growing again (980 frozen since July → 1175 and current).

**Root cause of four separate-looking 500s, and one silent failure.**
`fleet_api.py` was written for SQLite, where rows are `sqlite3.Row` and support **both** `row[0]` and
`row["col"]`. PostgreSQL returns plain tuples, so every name access raised
`tuple indices must be integers or slices, not str`. Measured: **~73 positional vs ~88 name accesses**,
so switching to dict rows globally would have broken the other half. `compat_row.py` implements
`sqlite3.Row` semantics and is wired once in `get_db()`. This fixed `/fleet/telnyx/usage`,
`/customers`, `/billing` and the monitor.
*And a schema drift that ate every alert:* the live `fleet_device_health_history` has a **`NOT NULL
serial`** column the app's `SCHEMA_SQL` never declares. Every history insert failed; because PostgreSQL
**aborts the whole transaction** on a failed statement (25P02), all 62 subsequent alert inserts failed
too — while the endpoint returned **200** with `created: 1`. Fixed by dropping the NOT NULL, backfilling,
declaring it in the schema, and committing **per device** so one bad write cannot strand the rest. The
monitor now reports `history_errors`/`failed_devices`/`complete`.

**Also fixed:** psycopg parses placeholders from the whole query text, so a literal `%` inside
`LIKE '%stale%'` is a syntax error. The converter now escapes `%` inside string literals (tracking `''`
escapes) while leaving real placeholders and bound values alone.

**Commits:** `c74395942` (monitoring + CompatRow), plus earlier `6f2a5195b`, `3ba33b23d`, `072f636a9`,
`3a228f959`. **103 tests passing** (was 66). Eight endpoints return 200.

**LESSONS LANDED THIS SESSION:** L34 (a job can succeed and write nowhere anyone reads), **L52** (a fix
verified through one entry point is not verified — test the path the consumer takes), plus an
ID-allocation rule for the lessons file after finding **seven duplicated lesson numbers** from
concurrent sessions. **PAIN P15, P16, P17.**

**NEXT:** the customer + staff portal surfaces. The contract is corrected and settled
(`deploy/waze-mdm/docs/customer-portal-waze-module.md`); the endpoints are live and verified. Blocked on
one question: which portal app and repo serves LPT customers in production.
---

## 2026-09-11 · ZABZ-YOGA · Kosher Waze portal built (customer + staff); staging is a dead target

**CHANGED (all pushed to `phone-and-tech-full` `test`, commit `d80e49d75`)**
- **Customer "My Waze Device"** at `/customer-portal/device`, in the portal nav. Live usage bar,
  `cap_message` from the server, and change-allowance / pause / resume. Renders nothing but a short
  message when the account has no Waze device, so it is safe to link for every customer.
- **Staff "Waze Fleet"** at `/admin/waze-fleet` (ADMIN + MANAGER). Fleet health, **alert freshness as a
  first-class figure**, device lookup by DRN, and cap/pause/resume. Deep MDM work (profiles, kiosk,
  wallpaper, renumber) deliberately stays in the fleet dashboard rather than being half-duplicated.
- **Backend `WazeDeviceService`** — server-to-server only, bounded timeout, and it **degrades to
  "not linked"** on 404 / outage / unconfigured so a fleet-api problem can never break a portal page
  that also shows orders and backups. The bearer token never reaches the browser.
- Customer procedures are customer-scoped; staff procedures sit behind `adminProcedure` and are
  **DRN-addressed with no customer input**. Mutations take a device **UUID, never a serial**, and an
  unowned UUID is rejected before any fleet-api call.
- `FLEET_API_URL` / `FLEET_API_TOKEN` are **optional**, documented in `.env.example`, `.env.template`,
  `.env.production.template`, so every environment without Waze devices still boots.

**VERIFIED**
- Backend + frontend **typecheck clean**. The only remaining errors are **two pre-existing ones on
  `test`** (`FAQSection.tsx` unused import, `useFaqs.ts` arg count) — proved pre-existing by stashing my
  changes and re-running: identical failures.
- **eslint clean** on every new and changed file, after splitting one component that tripped the repo's
  500-line rule (split into `components/waze/*`, not suppressed).
- **20/20** new service tests pass. Backend suite: **6107 passed, 24 failed** — all 24 pre-existing
  (timeouts + one Date-vs-string assertion in `customerPortal.debug-logging`), the latter also proved by
  stash-and-rerun.

**BROKEN — and it blocks the last step**
- **STAGING DOES NOT EXIST.** `Deploy to Staging (Test Branch)` has failed on **every** push since at
  least 2026-09-09 (8/8 consecutive). Root cause: `curl: (22) ... 404` from
  `https://api.heroku.com/apps/lakewood-phone-backend-test/config-vars` — the Heroku app is gone, so the
  workflow dies in "Validate Staging Configuration" before deploying anything.
  **The integration is therefore NOT verified on staging, and I am not claiming it is.**
- The frontend deploys **manually** via Netlify (`netlify deploy --no-build`), not by the workflow. Even
  with a healthy backend workflow, a UI change needs that manual step — see
  `docs/operations/DEPLOY_ARCHITECTURE_REALITY.md`.
- `FLEET_API_URL` / `FLEET_API_TOKEN` are **not set on the staging app**. Until they are, the panel
  degrades to "not linked" there by design, so staging would show nothing even once the app exists.

**NEXT**
Recreate/point staging, set the two secrets, re-run, and verify the panel against the live fleet. Then the
owner promotes `test` → `main` (his step, by agreement).

**ALSO FIXED THIS SESSION (fleet host)** — commit `b86cdbca8`
- Staff cap endpoint `POST /fleet/devices/{drn}/telnyx/cap` clamped the SIM to a **0.5 GB floor** while the
  customer endpoint used **0.05**, and it **stored the unclamped value**: asking for 0.1 stored 0.1 but
  enforced 0.5, so the database disagreed with the device. Now clamps once and stores exactly what it
  enforces. Verified live: 0.001 → clamped to 0.05 **and stored** 0.05.
- Added `GET /fleet/staff/device?serial=|drn=` sharing the customer view contract, because
  `/fleet/devices/{drn}/telnyx` returns a different shape that would have forced the portal to
  reimplement the cap-band logic. Verified: 200 by DRN, 200 by serial, 404 unknown, 400 for both/neither.

**EVIDENCE**
- `phone-and-tech-full` `d80e49d75`; `personal-secretary-mvp` `b86cdbca8`
- `backend/src/services/waze/waze-device.service.ts` (+ `.test.ts`), `backend/src/trpc/routers/wazeFleet.ts`
- `frontend/src/features/customer-portal/pages/WazeDevice.tsx`
- `frontend/src/features/admin/pages/WazeFleetPage.tsx` + `components/waze/*`
- `gh run view 34638668756 --log-failed` — the 404 that proves staging is gone
---

## 2026-09-11 · ZABZ-YOGA · All three named defects closed; only the staging verification remains

**CLOSED THIS ROUND**

1. **`installed_profiles()` reported falsely — and the real damage was in a safety check.**
   It read `public.device_profiles`, which is **always empty** in this deployment. So `diagnose` printed
   "(none)" for devices with a full kiosk profile set. Worse, `diagnose lockdown` derives its verdict from
   that list, so it printed **"✗ MISSING" for every expected profile on every device** — a safety check
   reporting the exact opposite of the truth on correctly-locked hardware.
   Replaced with `profile_report()`, which parses the device's own **ProfileList** result from
   `command_results` and returns `determination: known|unavailable`, so "no profiles" and "could not
   determine" can never again look alike. **Verified against DRN 2001:** all three lockdown profiles now
   read ✓ (was: all ✗ MISSING), and 4 real profiles with their inner payloads are listed.
   Two further bugs fell out: matching had to strip separators (`layered-kiosk` vs `layeredkiosk`), and
   the expectation `siri-dns` matched **nothing** because the real profile is `sirifilterdns`.
   *Also:* `_common` mutated `sys.stdout` at import time, which made the module **unimportable under
   pytest** (capture died, zero tests collected). That is now an explicit `force_utf8_console()` call from
   each CLI's `main()`. 9 new tests.

2. **The silent alerting pipeline.** Root-caused and rebuilt earlier in the session (67 days unwatched;
   `last_seen` NULL for all 65 devices and written by nothing; `/fleet/sweep` selecting a state with zero
   members; telemetry frozen since 2026-07-05). Now verified **both directions**: the monitor writes, and
   `/fleet/alerts` reads 50 alerts with real messages while `/fleet/health` reports
   `alerts=62, alerts_aged=87, alert_age_days=0.0`.
   **Then I found a false positive in my own monitor:** all 9 `retired` devices were being reported as
   "unreachable over the air", which for decommissioned hardware is permanently false, and a standing
   9-item false alarm is how an operator learns to ignore the list. Retired devices are now exempt, a new
   `retired_exempt` counter makes that explicit rather than silent, history is still recorded, and the 9
   false alerts were auto-resolved with a note. Monitor now reports `retired_exempt=9,
   stale_critical=53` (was 62) with `complete=true`. 3 new tests.

3. **Pause/lost-mode wiring.** Pause was done; **Lost Mode was not.** Added staff-only Lost Mode
   (`setLostMode` + `/fleet/devices/{drn}/lost-mode[/disable]`), requiring the literal token
   `LOST MODE` to enable, so a stray click cannot remotely lock a customer's phone. Disabling needs no
   token — un-locking is the safe direction. **Staff-only deliberately:** the owner has not decided
   whether customers may trigger it, and the plan flags that as a fraud/abuse risk on a resold device.
   *Not verified against hardware* — proving it would mean actually locking the owner's test device.

**STILL BLOCKED — unchanged, and it is the only thing between this and "done"**
**Staging does not exist.** `Deploy to Staging` has failed on every push since at least 2026-09-09; the
Heroku app `lakewood-phone-backend-test` returns 404 from the Heroku API. So the surfaces are built,
typechecked, linted, tested and **pushed**, but not verified on staging, and not in production. The owner
promotes to production by agreement, so this is his call: recreate the app (recommended), verify behind a
flag in production, or go without.

**EVIDENCE**
- `personal-secretary-mvp` `79f397013` (profile truth), `d810d1161` (retired exemption)
- `phone-and-tech-full` `f4c1f0e7e` (lost mode), plus `d80e49d75`, `5491311cb`
- `scripts/waze/test_profile_report.py` (9), `deploy/waze-mdm/fleet-api/test_fleet_monitor.py` (+3)
- Live: `/fleet/alerts` 50 rows w/ messages; monitor `retired_exempt=9 stale_critical=53 complete=true`
---

## 2026-09-11 · ZABZ-YOGA · Unverified-default risk: the OTA ack timeout was a guess

**CHANGED**
- `DEFAULT_ACK_TIMEOUT = 900`, replacing an unexplained `180`. Measured rather than chosen:
  across acknowledged commands (2026-09-11, `command_results.updated_at - commands.created_at`)
  **Settings median 4 s but p95 ~4.5 days and max 6.3 days**; **InstallProfile median 340 s, p95 6.5 h**;
  EnableLostMode/DeviceLocation median ~84 min. So 180 s sat *above* the median of ordinary commands and
  *far below* the p95 of profile work, and could not distinguish "slow" from "dead". The constant now
  carries those measurements inline instead of being a number nobody can justify.
  It deliberately does **not** cover the multi-day tail: when a device is simply offline the right answer
  is to stop and say so, not to block.
- `await_command_result` now returns **`timed_out` separately from `ok`**. No terminal status means *we*
  stopped waiting, not that the device refused. `ota.py` previously printed
  "NOT confirmed applied" with no hint that the command is still queued and may land later — which is how
  an operator re-issues a change that already took effect. It now says exactly that, and the `--timeout`
  help carries the same warning.
- 5 new tests (14 in `test_profile_report.py`). CLI help verified to render.

**NOTE ON MY OWN DATA** — the raw `command_results.id` is the enrollment id, so "Settings" above mixes
devices; a per-device latency would need `commands` grouped by enrollment. The conclusion is unaffected
(all rows are real acknowledgements and the tail spans days), but I am not claiming a per-device figure
I did not compute.

**STILL BLOCKED, UNCHANGED** — staging does not exist (Heroku app 404 since at least 2026-09-09), so the
portal remains built/tested/pushed but unverified on staging and not in production. Owner action, recorded
in `QUESTIONS.md`.

**EVIDENCE** — `personal-secretary-mvp` `90810c593`
---

## 2026-09-11 · ZABZ-YOGA · Two more silent-lie fields removed; the queue backlog cleaned safely

**CHANGED — both are instances of the same pattern: a thing that reports success while doing nothing useful.**

1. **`fleet_devices.last_seen` was NULL for all 65 devices and written by nothing.**
   No code read it (everyone correctly uses `enrollments.last_seen_at`), so it was not an *active* bug — but a
   column named like liveness that always returns NULL is a trap for the next reader, and this project has a
   documented history of exactly that shape producing a confident false report. The monitor now fills it from
   the source of truth, and a failed write reports `complete: false`.
   **Verified: non_null 0 → 63 of 65, and `fd.last_seen IS DISTINCT FROM e.last_seen_at` returns 0
   mismatches.**

2. **`/clean-queue` was a no-op that claimed success.** It deletes `.plist` files from a filekv store this
   deployment does not use (`NANOMDM_STORAGE=pgsql`; `/srv/queue` does not exist). It returned
   `{"ok": true, "cleaned": 0, "message": "No queue directory found"}` — which reads as "already clean" —
   while the real queue held 5,468 rows for that device. It now returns `ok:false, no_op:true`, the actual
   Postgres row count, and points at the real fix.

3. **Added `POST /fleet/devices/{drn}/prune-queue`** — status-aware, **dry run by default**, `?apply=true`
   to delete. It removes only entries whose command already reached a terminal status and preserves
   genuinely-pending work, reporting both counts.
   **Applied to DRN 26: 5,469 → 4 entries.** The 4 preserved are all
   `Settings-PersonalHotspot-off-sweep` with no result yet — exactly the pending work that must survive.
   Fleet queue 19,541 → 14,078. Nothing with a recorded result was lost.

**WHAT THE QUEUE ACTUALLY WAS** — DRN 26 held 4,615 `DeviceLocation` commands with status `Error`. Those are
residue of the **2026-08-28 incident**: iOS refuses that command unless the device is in Lost Mode
(`MDMErrorDomain/12067`), so each failed permanently and then sat in the queue being **re-offered to the
device on every check-in, for weeks**, on a device that was still checking in daily. A device retrying
thousands of permanently-failed commands is wasted work and it made real queue depth unreadable.

**A BUG I MADE AND CAUGHT IN MY OWN DRY RUN.** The first version counted with a plain
`JOIN command_results` — and a command can have several result rows, so it fanned out to
**"14,695 removable" out of a 5,469-row queue with a negative "preserved" count.** The delete used a
subquery and was never affected, so only the *reported* numbers were nonsense. That matters more than it
sounds: a dry run is what an operator decides from, so a wrong dry run is worse than none. Fixed with
`DISTINCT command_uuid`. **This is the second time today that a fan-out in a `command_results` join produced
a wrong number** — treat any count over that table as suspect until it is de-duplicated.

**VERIFIED** — 6 endpoints 200; monitor `complete=true, retired_exempt=9, stale_critical=53,
last_seen_write_errors=0`; `last_seen` 63/65 with 0 mismatches; container healthy. 108 tests passing.

**STILL BLOCKED, UNCHANGED** — staging does not exist (Heroku app 404), so the portal remains
built/tested/pushed but unverified on staging and not in production. Owner action; `QUESTIONS.md`.

**EVIDENCE** — `personal-secretary-mvp` `fdbf9b615`, `a55e374d0`
---

## 2026-09-11 · ZABZ-YOGA · Live-verified against the real fleet (11/11); only the deployment step remains

**THE KEY RESULT OF THIS ROUND**

Staging cannot verify this work, so I verified it a different way: `scripts/waze-live-check.ts` runs the **real
`WazeDeviceService`** — not a mock, not a copy — against the **live fleet-api** at Hetzner, using the repo's
own credentials, and asserts the contract the portal depends on. Read-only (GET only), because the write
paths would change the owner's hardware.

**11/11 passed**, against DRN 2001 on the live fleet: linked device returned (LPT 2001, `state=active`);
immutable derived name present; all usage numbers finite (nothing can render NaN); `cap_band` a known value
with a consistent `cap_message`; the **server** states the policy (`data_stops_at_cap`, `cap_editable_by`) so
the client is not hardcoding it; unknown serial degrades to `not_provisioned` (panel hides, no error); blank
serial short-circuits without an API call; `getStaffDevice(drn)` returns the **same** contract as the
customer path; an unconfigured service degrades instead of throwing.

Exit code 0 on success so it can gate CI. It sets `process.exitCode` rather than calling `process.exit()`:
a hard exit while fetch handles close trips a libuv assertion on Windows and reports non-zero even when
every check passed — which would make the signal worthless.

This is **stronger than a unit test and weaker than a staging deploy.** It proves the code that talks to the
fleet works against the fleet. It does **not** prove the portal renders in a browser, and I am not claiming
it does.

**KNOWN COUPLING, NOTED NOT HIDDEN** — importing the service requires the full `env.config` validation, so
`DATABASE_URL` / `JWT_SECRET` / `JWT_REFRESH_SECRET` must be present even for a fleet-only check. That is
why the runner needs dummies. Worth decoupling; recorded rather than silently worked around.

**OBJECTIVE STATUS — everything except deployment and in-browser verification**

| Objective item | State |
|---|---|
| Customer "My Waze Device" surface | **built, pushed, service live-verified** |
| Staff fleet surface | **built, pushed, service live-verified** |
| `installed_profiles()` reporting falsely | **fixed + verified on real hardware** |
| Silent alerting pipeline | **rebuilt, verified both directions** |
| pause / lost-mode wiring | **done (lost mode staff-only, token-gated)** |
| Unverified-default risks | **removed** (`last_seen`, ack timeout, clean-queue, DRN exporter, health alerts) |
| Deployed to staging | **BLOCKED — the Heroku app does not exist** |
| Verified through real entry points in a browser | **not done** — needs staging |

**EVIDENCE** — `phone-and-tech-full` `a77ff7f30`; `personal-secretary-mvp` `fdbf9b615`, `a55e374d0`
---

## 2026-09-11 · ZABZ-YOGA · DEPLOYED TO TEST — the real deploy path was Netlify + Hetzner, not Heroku

**I WAS WRONG, AND THE CORRECTION IS THE POINT.** I had reported staging as "blocked, needs the owner" because
`deploy-staging.yml` fails with a 404 for Heroku app `lakewood-phone-backend-test`. The repo's own
authoritative doc — `phone-and-tech-full/docs/operations/DEPLOY_ARCHITECTURE_REALITY.md` —
says in bold: **"Heroku is DEAD. Any doc/workflow referencing Heroku backends is obsolete."** and
"`.github/workflows/deploy-staging.yml` etc. target Heroku and are **not the working path**."

The real path, documented and working:
- **Frontend** → **Netlify** (origin) behind Cloudflare. TEST site `lakewood-phone-test`,
  id `99e0273a-9f51-42c2-8a98-4485892629ba`. Deploy is **manual**, via a token at
  `~/.personal-secretary/secure/netlify-auth.txt`, with `--no-build` + `--filter` (both mandatory).
- **Backend** → **Hetzner `lpt-apps`** (2.28.33.58), SSH alias `lpt-apps`, key `~/.ssh/id_ed25519_hetzner`.
  Test stack is `/opt/lpt-test` (isolated, own DB `lpt_test`, container `lpt-test-backend`, port 3002,
  `test-api.lakewoodphoneandtech.com` via Caddy).

I had spent a round asking the owner to recreate a Heroku app that is deliberately retired. **Read the
authoritative deploy doc before declaring an infrastructure blocker.**

**WHAT I DEPLOYED (all of it myself, test only — production untouched)**
1. **Backend**: `/opt/lpt-test/src` was at `3f8aa02` (2026-09-10); fast-forwarded to `a77ff7f` (my work).
   **Preserved a local, uncommitted `backend/Dockerfile.production` fix** ("could never build … FIXED
   2026-08-31") by stashing it across the merge — it is load-bearing and not in git.
2. **Wired the fleet credentials onto test.** Neither prod nor test `.env` had `FLEET_API_URL` /
   `FLEET_API_TOKEN`, and the test env is *generated from prod's*, so I added them to `/opt/lpt-test/.env`
   directly (backed up first). Without this the panel silently degrades to "not linked" and staging would
   have proved nothing.
3. **Built and recreated** `lpt-test-backend` — healthy.
4. **Frontend**: built with the TEST env from the doc (`VITE_API_URL=https://test-api…`,
   `VITE_FEATURE_CUSTOMER_PORTAL=true`, …) and deployed to the Netlify TEST site.

**VERIFIED — OBSERVED, NOT ASSUMED**
- Live bundle hash from `test.lakewoodphoneandtech.com/customer-portal/login` is
  **`index-Bcqvjq-v.js`, byte-identical by name to my build** — so the deployed frontend is mine.
- That live bundle contains `My Waze Device` (3), `Waze Fleet` (3), `capBand` (6), `dataStopsAtCap`,
  `capMessage` (4), `Find My` (2), `Plenty left`, `Nearly used up`, `Data stopped`,
  `Your data allowance`, `Pausing turns the device off the network…`, `Lost Mode` (6), `run monitor` (2).
- `/api/trpc/wazeFleet.status` → **HTTP 401** (registered and auth-gated). 404 would mean missing; 401
  means present. `customerPortal.getMyProfile` also 401, so the mount is right.
- **From inside the deployed container**: `GET $FLEET_API_URL/waze/device/FFYGNQ8AN72J` → **HTTP 200** with
  real fleet data (`LPT 2001`, `state: active`, `cap_editable_by: customer`). The credential wiring works.
- Browser: login page renders, **0 console errors**; `/customer-portal/device` correctly redirects to login
  (the route guard works).

**THE ONE REMAINING GAP, STATED PLAINLY**
I have **not** seen the panel render with data in a browser, because that needs an authenticated customer
whose `Device.serialNumber` exactly equals a live fleet serial. **In `lpt_test`, only 1 device has any
serial and neither Waze device is linked to any customer** — so the panel cannot appear there without test
data that does not exist. I did not create customer accounts or insert customer rows for this: that is the
owner's data model and his call.

**COMMITS / EVIDENCE** — `phone-and-tech-full` `a77ff7f30`; deploy logs `/opt/lpt-test/build-waze.log`;
env backups `/opt/lpt-test/.env.bak-20260911`, `.env.bak-prepull`