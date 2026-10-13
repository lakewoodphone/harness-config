# The owner-attention pipeline

**What it is.** One job: find everything that genuinely needs Eliyahu's decision or money,
and put it in front of him once, in one numbered list, without asking him to read a document.

**Why it exists.** Six subsystems were each keeping their own private claim on his attention —
email triage, the `gv_daily_digest` work order, the waiting-comms sweep, the owner decision
queue, the books obligations, and the task board — and none of them knew about the others. His
own words, 2026-10-10: *"This does not look like a unified brain. It looks like scattered and
split up."*

The measured consequence, 2026-10-13: **1,113 emails in ten days had never been read end to end.**
`email_catalog` held only ~100-character Gmail snippets, its newest `internal_ts` was 2026-10-11
19:07 while Gmail held mail to 2026-10-13 00:42, **121 rows were flagged `needs_owner=1` and not
one of them had been put in front of him**, and the same three questions resurfaced repeatedly
while roughly thirty real items sat invisible.

A snippet cannot decide whether a message needs a person. The body can.

---

## 1. The flow

```
five Gmail accounts ──▶ lpt-email-sweep ──▶ JSONL corpus, full bodies
                                              │
owner_decision_queue ─────────────────────┐   │
books.db obligations ──▶ books_mirror ────┤   │
waiting-comms index ──────────────────────┼───┴──▶ owner_attention.py build
other digests' memory rows ───────────────┘              │
                                                         ▼
                              one numbered digest  +  one ≤320-char text
                                                         │
                                              memories(category='owner_attention')
```

## 2. Where it runs — TWO boxes, and this is the part that gets people

The authority moved from the office box to the cloud at **2026-10-11T05:43:36Z** and the office
box was frozen as the rollback anchor (`sentinel-freshness-check.py`'s own header records it).
The pipeline therefore runs on both, and they are not interchangeable.

| | office `secratary` (`secratary-ts`) | cloud `secratary-cloud` (LIVE) |
|---|---|---|
| role | frozen rollback anchor | the live company |
| `cron.service` | **masked** 2026-10-11T20:23Z | running |
| work loop | last tick 2026-10-11T20:17Z — dead | ticking |
| comms index | stale (frozen) | fresh |
| company SQLite | `/home/zabz/personal-secretary-mvp/data/secretary.db` (231 tables) | **`/root/authority.db`** (231 tables) |
| books store | **`/home/zabz/accounting-data/books.db`** (28 MB) | absent — reads the office's over ssh |
| app venv | `/home/zabz/personal-secretary-mvp/.venv` | `/root/personal-secretary-mvp/.venv` |

**Do not pick the box named in an instruction. Find who writes, and read the writer's clock:**
`systemctl list-timers --all`, the newest row in the busiest table, and any script whose own
header describes the migration. The cloud has no books store, so `books_mirror.py` pulls the
`obligations` table from the office box over ssh and rebuilds it on every digest run.

## 3. Install

Scripts live in this repo at `scripts/owner-attention/` and are installed to:

| file | office | cloud |
|---|---|---|
| `owner_attention.py` | `/home/zabz/personal-secretary-mvp/scripts/` | `/root/personal-secretary-mvp/scripts/` |
| `lpt-email-sweep.py` | `/home/zabz/bin/` | `/root/bin/` |
| `books_mirror.py` | — (owns the store) | `/root/bin/` |

```bash
# office box
sudo cp deploy/lpt-books-nightly.{service,timer} /etc/systemd/system/      # the books pipeline
sudo systemctl daemon-reload && sudo systemctl enable --now lpt-books-nightly.timer

# cloud box (the live authority)
sudo cp <units> /etc/systemd/system/                                       # sweep + digest
sudo systemctl daemon-reload
sudo systemctl enable --now lpt-email-sweep.timer lpt-owner-attention.timer
sudo systemctl start lpt-email-sweep.service      # seed the corpus once
```

## 4. Schedule

| unit | host | when (UTC) |
|---|---|---|
| `lpt-email-sweep.timer` | cloud | 04:40, 16:40 |
| `lpt-owner-attention.timer` | cloud | 14:10 — one message a day, not four |
| `lpt-books-nightly.timer` | office | 07:20 (`Persistent=true`) |

## 5. Traps already paid for — do not repeat them

1. **The Gmail client segfaults under threads.** `Fatal Python error: Segmentation fault` after
   ~30 messages at `workers=1`, 3 and 8. The same 181 messages fetched **serially** complete with
   zero errors, twice. Fetch on ONE thread; parallelise by ACCOUNT. (`lpt-email-sweep.py` does.)
2. **Use the app venv, not `/usr/bin/python3`.** `app.config` imports `pydantic_settings` and
   `app.sms_service` imports `twilio`; the system interpreter has neither. Hit twice.
3. **`systemctl enable` alone leaves a timer with an EMPTY `NEXT`** and it never fires. Always
   `enable --now`, then prove it: `systemctl list-timers '<name>' --all`.
4. **One `OnCalendar` line per time.** `OnCalendar=*-*-* 00:10,06:10:12:10 UTC` is an invalid
   spec and the unit refuses to start.
5. **The owner surface has three gates** and each refuses silently: the interpreter (needs the
   venv), the urgency threshold (`owner_sms_min_urgency` is **`urgent`** here), and the length
   (**320 characters** — one text). A fourth trap: `rate_floor` refuses a second send within
   seconds. `send_owner_update` returns a dict; **read it and report what actually happened.**
   An earlier version printed "sent" while the row went to `owner_message_queue` as `held`.
6. **`SuccessExitStatus=0 2 3`** on the digest unit, or a healthy refusal is reported by systemd
   as a unit failure.
7. **Never copy the 18.5 GB `secretary.db` as a pre-change backup.** It filled a box with 20 GB
   free to 97% in under two minutes. Take a ROW-LEVEL backup:
   `/home/zabz/accounting-data/backups/attention-debt-rows-*.json`.
8. **`comms-search.py --json` goes BEFORE the subcommand** (`--json waiting`). After it, the call
   exits 2 and a caller that swallows that reports an empty world instead of a broken call.
9. **The books `obligations` date column is `due_on`** — not `due_date`, not `due`. A guessed
   column name returns "no obligations", a silent zero that looks like health.
10. **Do not put the sweep's stdout in journald.** Its JSON summary is ~45 KB of message bodies
    per run. `StandardOutput=truncate:.../email-sweep/last-run.json`.
11. **A `systemd-run` unit named with a space** (`--unit=lpt-sweep-\x20`) leaves a service that
    cannot be started and pollutes `list-units`.

## 6. Verify it is actually working

```bash
# office box
cd ~/ceo-kernel && python3 -m ck status 2>&1 | sed 's/\x1b\[[0-9;]*m//g'

# cloud box — the kernel needs to be told which database is the truth
cd /root/ceo-kernel && CEO_KERNEL_DB=/root/authority.db python3 -m ck status
```

The checks this pipeline owns must read:

```
[ok] attention_debt  --  attention debt within bounds (0 recent question(s), 0 held, none fresh)
[ok] delivery        --  owner delivery flowing (newest 0.0h ago, ...)
```

**Delivery is proved from the provider, never inferred.** `sms_log.status` is written by the SMS
webhook, and when that path is frozen a delivered message stays `queued` — which is exactly how
the kernel came to report "the owner cannot be reached" about a delivered text. Reconcile against
Twilio:

```
GET https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages/{twilio_sid}.json
  -> status: delivered   to: +18483897895
```
Credentials are `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` in the app `.env`. Note Twilio only
retains messages for a limited window; older SIDs return 404 and must be left alone.

## 7. Where the output lands

| artefact | path |
|---|---|
| numbered digest (newest, human) | `<app>/data/owner-attention/latest.txt` |
| dated digests | `<app>/data/owner-attention/<YYYY-MM-DD-HHMM>.txt` |
| durable copy for later sessions | `memories(category='owner_attention')` |
| full-body email corpus | `<host>/accounting-data/email-sweep/accounts/<account>.jsonl` |
| books mirror (cloud) | `/root/accounting-data/books.db` (`obligations`, 21 rows) |
| row-level backups | `/home/zabz/accounting-data/backups/attention-debt*-rows-*.json` |

## 8. Known-open

- **The owner queue is the largest remaining defect.** 141 pending with six expired deferrals.
  An audit on 2026-10-13 found only ~30 distinct questions genuinely his; the rest is engineering
  that should never have reached him. See `/tmp/owner-queue-audit.md` on either box.
- **593 of 646 production orders carry no `SUCCEEDED` payment row** and 289 carry a "paid"/"zelle"
  note with none. The queue described this as "about thirty orders". A books defect, not his.
- **`sms-responder.py` is not scheduled and three of its five modules are missing**, so customer
  texts sit undecided for hours while a canned hours reply is sent to every inbound message
  (113 measured sends). Highest-value customer-facing fix outstanding.
- **The cloud kernel needs `CEO_KERNEL_DB=/root/authority.db`.** Run bare it reports "no usable
  database found" and refuses every number. Whether the deployed runner sets it is unverified.
- **The office box's `ck` still claims authority** over a fork silent since 2026-10-11T20:17.
- `frontier_risk_board`'s metric was corrected (an escalation carrying a written reason is a routed
  decision, not dead weight); the seat was not retired and no history row was deleted.

## 9. Provenance

Built 2026-10-13. Journal: **H3403**, **H3404** (handoffs); **L3421**–**L3425** (lessons: the Gmail
thread segfault, the timer traps, one writer for owner attention, the three-gate owner channel, and
the two-box authority split). Scripts and this document are committed in `harness-config` and
pushed to the vault.

