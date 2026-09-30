# Wake sources — the judges that decide what deserves a session

**Owner's ask:** *"make certain things that the secretary [sees] flags … make sure it
doesn't sit there spawning hundreds of DSH sessions for no reason."*

A source is a judge. It reads ONE signal on the authority and either calls the frozen
`flag` CLI (see `../CONTRACT.md` §5) or stays quiet. A source that fires on the normal,
healthy case has failed even if it "works" — so every threshold below is a measured
number with the healthy value written next to it, and every source was run against the
live authority to show what it does when nothing is wrong.

## The sources

| source | signal it reads | threshold, and why THAT is abnormal | what a human would do about it | what it must never do |
|---|---|---|---|---|
| **`txt-lost-webhook.py`** | `journalctl -u secretary-api --grep 'Unhandled error on /webhook/twilio/sms'` — a request from Twilio the app answered with HTTP 500. | **≥1 occurrence in the last 24 h.** Measured over the whole journal, 2026-08-25→09-18: 13 occurrences on 5 days, and **all 13 map to a real inbound text** whose Twilio `date_sent` is within 60 s and whose `app_has_it=0` — the app never recorded it. There is no acceptable rate at which a customer's text is silently dropped, and Twilio never retries a 5xx, so the threshold is one. | Fix the write path so the webhook cannot lose a text under SQLite contention: bounded `SQLITE_BUSY` retry plus a durable spool of the raw payload. Then prove it under a held write transaction. | fire when the window holds no such line; report a number it did not read; read the whole journal (18 MB/128 k lines per 24 h) and filter in Python; send anything to anyone. |
| **`txt-stranded-inbound.py`** | `messages` where `direction='inbound' AND state='new' AND first_seen < now-6h` in `~/.sms-inbox/inbox.db` — a text the router has not decided. | **≥1 older than 6 h.** Measured healthy value: **0** (2026-09-18 03:15 UTC, with 4 inbound texts arriving in the preceding hour, all decided within ~2 min). `sms-responder.py` runs every 5 min with `--limit 25`, so 6 h is ~72 runs and 144 messages of drain capacity for a line that gets a handful a day. Only a dead consumer or a repeatedly-failing send reaches it. | Read the `reason` column first: `NULL` = the router is not running (check cron + `responder.log`); `send failed:` = Twilio is rejecting our replies. Fix, re-run the router, confirm the rows leave `new`. | fire on outbound rows or on inbound rows another state has claimed; fire on merely recent `new` rows; reply, delete or rewrite anything in the inbox. |
| **`decision-queue-stale.py`** | `owner_decision_queue WHERE status='pending' AND asked_at < now-7d`. | **>7 days pending.** Measured over all 18 rows the queue has ever answered: lag min 0.10 h, **median 1.70 h, worst 57.31 h**. 168 h is 2.9× his worst and 99× his median, so the row is not "he has not got to it yet" — it is either an engineering fault mis-filed as his decision, a question that is now moot, or genuinely his. | Triage: fix and `resolve` (a), `resolve` with the superseding evidence (b), or **leave it exactly as it is** (c). Never answer on his behalf. | treat a pending row as agent work on the strength of its age; `answer` a row; `resolve`/`dismiss` a row that is genuinely his (that hides his question from him, which is worse than the nag). |
| **`decision-answer-unconsumed.py`** | `owner_decision_queue WHERE status='answered' AND resolved_at IS NULL AND answered_at < now-6h`. | **≥1 older than 6 h.** The healthy resting state is closed: 2 of the 8 answered rows have `resolved_at` **equal to** `answered_at` to the second. The other 6 sat at 52.3, 52.3, 50.7, 50.1, 9.2 and 1.4 h and their `answer` text orders real work ("Dismiss him in Gusto", "fix only the spoken message", "tell the customer straight"). The zero-second healthy figure is only n=2 and that is thin evidence, so the threshold is deliberately generous rather than tight. | Per row: verify whether the action was done (i) and close it, do it (ii), or — if it needs a person — write what should be said and leave it (iii). **Verify before acting**: re-doing a finished action is worse than doing nothing. | fire when every answered row is resolved; re-do work that is already done; **contact any customer or vendor** (outbound needs the owner's explicit per-message instruction, without exception); use `answer`. |
| **`comms-freshness.py`** | `~/.lpt-recon/production-comms-freshness.json` — the verdict written every 15 min by `~/bin/production-comms-freshness.py`. | **A: `problems` non-empty on a verdict checked_at <45 min ago. B: no fresh verdict in 45 min.** Measured healthy 2026-09-18 03:15 UTC: `ok: true, problems: []`, cursors 0.6 h / 0.59 h, website newest 0.03 h. A `problems` entry means a measured clock is behind its own 2 h gate — the shape that hid an 11.5-hour customer-comms silence on 2026-09-15. 45 min = three missed 15-min runs; one miss can be transient, three cannot. | Run the check by hand (`rc=1` stale, `rc=2` could-not-measure). Find which clock moved: the push (`website-comms-push-cron.sh`, crontab 9,39) or the site ingest (`comms-refresh.py`, 7,37). Fix, then confirm `rc=0` and the website's newest message age back under 2 h. | fire off a stale verdict (that is finding B, a different job); fire while the verdict is ok and current; run the monitor or repair anything itself. |

### How they stay quiet, and what bounds a bad day

* **Subject = the dedup key.** Three sources bucket the subject by the UTC day
  (`sms-webhook-lost:<day>`, `sms-stranded:<day>`, `comms-freshness:<day>`), so a
  condition that is *not* fixed costs **at most one session per day** rather than one per
  occurrence — 2026-09-18 had six webhook failures and one text in the same two minutes,
  and 96 freshness checks a day must not be 96 sessions. The two queue sources key on a
  row **identity** (`odq-stale:<oldest id>`, `odq-answer-open:<oldest id>`) so they fire
  exactly **once per row**, ever.
* **No source keeps state.** The wake store is the only state; dedup, the cooldown, the
  daily cap, the per-source hourly cap, the night gate and the kill switch are all the
  store's, not the source's (`../CONTRACT.md` §4). A source never invents its own dedup.
* **An unreadable signal is never healthy.** A missing database, a unit systemd does not
  know or a missing verdict file prints the reason on **stderr** and exits **1** — never
  the word `quiet`. This is the one place these scripts go beyond the contract's written
  exit codes, deliberately: an empty result must not be reported as health.
* **`quiet` means "this source filed nothing"**, not "the world is healthy". If the store
  refused the row (cap, cooldown, pause file) stdout still says `quiet` and stderr names
  the refusal — `wake.py stats` is where caps are read.

### Rejected signals — a well-argued "no" is a result

* **Inbound texts the responder marked `queued` — REJECTED (covered elsewhere).**
  `state='queued'` means the responder already raised an owner-decision row for that
  correspondent (`_open_queue_row_for` dedups it against the queue itself). Verified
  2026-09-18: all 5 queued rows have their row in `owner_decision_queue`. A `queued` text
  is an **owner decision**, not agent work, so a wake on it would be a second session for
  a question that is already waiting in the right place.
* **Inbound texts in `state='woken'` — REJECTED (already handled).** The responder files
  the wake row itself, in the same turn that it sets `woken`
  (`sms-responder.py` → `wake_mod._file_wake`, then `_record(..., "woken", ...)`). A source
  watching for `woken` would duplicate the responder's own flag; the safety net for a
  missing row belongs in the dispatcher, not here.
* **`database is locked` as a general signal — REJECTED (no defensible threshold).**
  Measured 2026-09-18: 1,351 lock lines in 24 h, 6 h→281, 12 h→656, 48 h→2,729. That is
  the steady state of this deployment, not an anomaly, and the app writes only 75
  unhandled exceptions to `error_log` in the same 24 h while the journal records 1,351
  events — a 27× undercount, so there is no trustworthy population to threshold against.
  The one consequence worth a session is the SMS webhook, and `txt-lost-webhook.py` reads
  exactly that signal instead.
* **The family-chat watchdog (`~/family-chat-watchdog.log`) — rejection STALE as of
  2026-09-30; not yet re-registered.** The original verdict was right when written: 19 of
  19 runs reported `PROBLEM`, because the instrument compared a whole day of carrier
  messages against a six-hour window (Twilio's `DateSent` filter is DATE-granular and its
  date-only upper bound reads as 00:00 of that day). Measured 2026-09-30: the alarm that
  said `179 of 179 messages missing` was **100% false** — every row it named was in our
  own table, marked delivered. That is fixed: ISO bounds plus a client-side check against
  the carrier's own `date_sent`, and a **healthy run now prints one `quiet` line** (it used
  to print nothing at all, which made "quiet" indistinguishable from a dead cron). It also
  gained a check for outbound rows stuck in `queued`/`sent` past 20 minutes — the shape
  that hid 18 phantom rows for six weeks.
  So the source's own rule now says it is *eligible*: it has a healthy state to return to,
  it exits non-zero only on a real finding (`1` drift/stuck, `2` webhook wrong, `3` could
  not check), and it never sends anything to anyone. **Re-registering it is a deliberate
  change, not a side effect of the fix** — an adapter must treat a non-zero exit or a
  missing `quiet` line as the signal, and must not fire per row. Not done on 2026-09-30.
* **`~/.lpt-recon/check.log` and `~/.lpt-verify/*` — REJECTED (already notifying).**
  `lpt-recon` logged `1 FAIL`/`2 FAIL` on 9 of 21 runs, and `~/.lpt-verify/four-surface.json`
  is chronically at 6 errors against a baseline that keeps drifting (315→317 schema-invalid
  of 388). Neither has a healthy state to return to, so neither can be a threshold.
  `~/.lpt-recon/production-comms-freshness.json` was accepted instead **because it has a
  reachable healthy value** (`ok: true, problems: []`), which is the property that separates
  a usable signal from a permanent alarm.
* **`/var/log/box-health.log`, `~/phoenix-evidence-health.log` — REJECTED (wrong shape or
  already healthy by design).** `box-health.log` did not exist on 2026-09-18 (cron entry
  `15 5 * * *`, so it is written once a day and I could not read it in the window I had);
  `phoenix-evidence-health.log` is `ok=True` in 111 of 113 lines, and its only two failures
  are 2026-09-15, i.e. it is not a live risk and one bad line per hour is not a wake.
* **`~/.fsearch/comms-check.log` — REJECTED (a second source on the same question).**
  `comms-refresh --check` logs `ok — …, 0 missing` twice an hour and has no verdict file and
  no timestamp inside each line, so freshness would have to come from the file mtime.
  `comms-freshness.py` answers the same "is customer comms flowing" question with a
  structured, timestamped verdict; one source per failure class is the rule, and a second
  would mean a second session for one problem.
* **`~/.lpt-verify/stripe-watch.log` — REJECTED (it already files its own row).**
  It writes `ANOMALY filed to owner_decision_queue` when something changes, so the queue is
  its proper destination, and it is not agent work until the owner answers it.

## Files, deployment and verification

These five files are one unit — `_flag.py` is imported by all four sources, so they must be
copied together, and they read their signals with **`sqlite3` in read-only mode** and
`journalctl` only. They write nothing anywhere except through the frozen `flag` CLI.

```
sources/_flag.py                        shared plumbing (paths, read-only reads,
                                        journal access, the flag call, the runner)
sources/txt-lost-webhook.py             source 1
sources/txt-stranded-inbound.py         source 2
sources/decision-queue-stale.py         source 3
sources/decision-answer-unconsumed.py   source 5
sources/comms-freshness.py              source 4
```

Every source: `python3 sources/<name>.py [--dry-run]`. Run them at a modest interval — each
is cheap (journal `--grep` 381 ms; the queue sources read a few hundred rows) — but the
scheduling, the cron lines and the install path are **W4's and the manager's** (see
`../cron.txt`, `../deploy.sh`). Suggested order of introduction, cheapest risk first:
`decision-queue-stale`, `txt-stranded-inbound`, `decision-answer-unconsumed`,
`comms-freshness`, then `txt-lost-webhook`.

Thresholds are env-overridable so an operator can re-tune without editing code:
`LOST_TXT_HOURS`, `STRANDED_HOURS`, `ODQ_STALE_DAYS`, `ODQ_ANSWER_HOURS`,
`COMMS_FRESHNESS_STALE_MIN`, plus `WAKE_PY`, `SMS_INBOX_DB`, `SMS_INBOX_APP_DB`,
`OWNER_QUEUE_DB`, `SECRETARY_API_UNIT`.

Verification that was actually run (full transcript in the stream report):

```
# the healthy case, per source, against the live signals — must print `quiet`
python3 sources/txt-stranded-inbound.py
python3 sources/decision-queue-stale.py
python3 sources/comms-freshness.py

# filing and dedup, against a TEMP store
cp ~/.sms-inbox/inbox.db /tmp/t.db        # never the live store
SMS_INBOX_DB=/tmp/t.db python3 sources/txt-lost-webhook.py   # flagged …
SMS_INBOX_DB=/tmp/t.db python3 sources/txt-lost-webhook.py   # (…: deduped)
```
