# Autonomy check-up — 2026-09-29

Two questions from the owner, answered from live evidence read on 2026-09-29 between 17:58Z and 18:25Z.
Every number below carries its source and the minute it was read. Nothing here is inferred from a log line
that claims something worked; where a claim rests on inference it says so.

Question 1: are DSH sessions getting triggered and worked on automatically?
Question 2: is the system that texts him and he texts back running full-DSH-like logic?

---

## Q1 — YES. Sessions are being triggered and worked, continuously and with real artefacts.

The chain is: a source on `secratary` raises a flag → `wake-dispatch.sh` claims one → ssh to ZABZ-TECH →
`dsh --profile headless <prompt>` runs a full session with no human present → the result comes back and the
row is marked.

**Liveness, read 17:59Z.** `wake-heartbeat` = `2026-09-29T17:55:02Z` (4 min old). `sources-heartbeat` =
`2026-09-29T17:45:10Z` (14 min old). `wake-dispatch.log` mtime `17:51:53Z`. Cron: fan-out every 5 min
(`WAKE_FANOUT_TARGET=5 WAKE_FANOUT_MAX=8`), sources every 15 min, responder every 5 min.

**Throughput today, from `~/.sms-inbox/wake-dispatch.log`.** 133 release lines and 133 completion lines.
Exit codes: **125 × exit=0**, 3 × exit=1 with runner_code=124, 1 × exit=124. Duration over 133 releases:
min 78 s, **median 554 s**, max 2,161 s. Releases per hour were 5–11 in every hour from 00:00Z to 17:00Z —
the machine did not idle. `wake_budget` (the store's own counter) agrees: day 2026-09-29, released 133.

**Read the headline number correctly.** `wake.py stats` reports `released_today: 132`. That counts
*sessions started*, not pieces of work: the dispatch log names only **41 distinct wake ids**, and the most
re-released subject — `project:lpt-website:20260929` — was released **20 times today, all 20 exit=0**.
`project:housekeeping:20260929` 17, `checkout-health:rental-system:20260929` 14,
`checkout-health:prod-db-sync:20260929` 13.

That repetition is **design, not a bug**, and the mechanism is in the code: `wake.py file_wake()` revives a
terminal row in place (`UPDATE wake SET ... state='new', attempts=?, created_at=? WHERE id=?`, `subject` is
UNIQUE), and each source re-files its subject once its own cooldown expires. So one subject row legitimately
becomes many shifts across a day. What follows is that "132 released" must never be reported to the owner as
"132 things done". The honest count of *work* is the ledger.

**The work is real.** From `~/work/work.db`, read 18:20Z:

| measure | value |
|---|---|
| ledger items closed `done` today | **52**, latest 17:51:27Z |
| attempts recorded today | **138**, across **10 distinct workers**, 00:22Z → 17:51Z |
| attempts carrying a `proof` command today | 133 of 138 (all-time 219 of 243) |

Commits inside repos on the authority, by committer date since 2026-09-28: `phone-and-tech-full` **58**,
`kosher-filter-ai` **46**, `lpt-hub` **5**, `quickbooks-agent` **2**, `personality-test` **2**. Sample HEADs:
`0efdc2dc7 fix(work-orders): block $0/unset labor tier submit without override (item 93)` and
`6f6ed6b7b test(customer): assert corpus LF, not the stale CRLF measurement` — each naming the ledger item
it closes.

**Failures today, named.** `project:prod-db-sync:20260929` failed twice: `ssh hop failed (rc=255) after 530s`
with `client_loop: send disconnect: Broken pipe`, and `lease heartbeat lost three times; session killed so
it could not be double-run (session ran 655s)`. The second is the safe failure — the lease stopped a
double-run rather than allowing one.

**Cost, measured, with its caveat.** `wake-cost.jsonl` last row (day 2026-09-29): 37 releases,
**36 priced**, `known_cost_usd 0.953266`, **52,852,900 tokens**, `no_usage_releases 0`. That is about
**0.026 USD per session**. `wake.py stats` separately reports `spend_today_usd 1.23149`. The cost row's own
field `cost_usd_or_unsourced` reads **`unsourced`**, so the day's total is not traceable to a single source —
treat it as approximately one dollar, not as an audited figure. Each dispatch log line says `cost=none`
because the headless surface reports no usage; that phrase is not a measurement.

**Caps actually in force** (`wake.py` live values, 18:20Z): max_per_day **500** (note the module docstring
still says 12 — the code default is `DEFAULT_MAX_PER_DAY = 500`), max_per_source_per_hour 3,
max_usd_per_day 70.0, cooldown 1800 s, lease 1200 s, max_attempts 2, night_quiet true, pause file absent.
Night quiet gates only low-priority releases.

**Ranked gaps in Q1.** (1) The cost for the day is marked `unsourced`; one cost path, one source. (2) The
docstring/code disagreement on the daily cap. (3) `released_today` is a session counter sitting in the same
output as work counters and reads like a productivity figure. (4) `wake-tuner` filed 14 of today's flags
(12 done, 2 new) — one session per tuning subject, where one session could read all of them.

---

## Q2 — The front door is a classifier. The back room is a real agent. The owner is on the front door.

### The decision layer is NOT an agent

`sms-responder.py` → `textdecide.choose()` (`textdecide.py:594`). For the owner's own number it takes the
branch that passes `force_answerable=True`. That path makes **exactly one** model call
(`textdecide.py:498`): `POST {base}/v1/chat/completions` with `{model, messages, temperature: 0.2,
max_tokens}` — **no `tools` key** — and expects one JSON object back. The action set is fixed:
`ACTIONS = ("reply", "work", "escalate", "ignore", "record")` (`textdecide.py:56`).

There is no tool loop. The one thing that looks like one is a decoy: `textdecide.py:540`
`for call in (msg.get("tool_calls") or [])` is *response parsing* for a gateway that sometimes answers a JSON
request with a native tool call. No tool result is ever fed back to the model.

Model choice obeys the standing rule and is worth keeping: resolved at runtime from the gateway catalogue
(`/v1/models`), preferring route aliases, refusing `FORBIDDEN_MODELS = ("secretary-genius",)`, cached in
`~/.sms-inbox/model-catalog.json`, with `None` → "record it as work rather than guess". No model name is
hardcoded.

### There IS a real tool loop — and the owner never reaches it

`textwork.py`: `MAX_STEPS = 3`, `MAX_TOOL_CALLS = 10`, tools = `web_search, memory_search, owner_state,
owner_profile, contacts, sms_thread, comms, app_db_query, queue_lookup`. The model emits `{"tools": [...]}`,
the results go back, and it continues until it emits `{"answer": ...}` or `{"blocked": ...}`.

It is reachable only through `_do_work` (`sms-responder.py:406`) — the **non-owner** branch. When the owner's
own text is judged `work`, `sms-responder.py:636` files a ledger item and stops. So the owner's question
never gets 3 steps and 10 tools; it gets a row in a queue.

### What that row becomes is the good part

Ten `work_item` rows carry `source='owner-sms'` (created 2026-09-28T19:45:45Z → 2026-09-29T03:20:05Z).
Six are `done`, three `dropped`, one `blocked`; attempts are attributed to `keepalive-housekeeping`,
`keepalive-cfo`, `keepalive-lpt-sync` and others. His 03:15:44Z text, "So I fill out the form file and
document it…", became `housekeeping#92`, claimed and closed `done` at **05:43:55Z**. So an owner text
*does* become real work done by a full woken session.

### Where it actually breaks

**1. He is not answered.** Newest outbound to `+18483897895` is **03:15:06Z**; his 03:15:44Z text produced
item #92 and silence. Count of outbound messages to him after 03:20Z today: **0** — while 52 ledger items
closed. His texts are filed, and he is not told anything. That is the named failure mode "filing work and
leaving a human waiting", and it is the one thing here he would notice.

**2. The texts he did get were cut mid-sentence at 300 characters.** Four messages sent by this path on
2026-09-29 (`decided_by=textsend`) were **exactly 300 characters**, three of them ending inside the
recommendation: `…I recommend: Pay the $597.29 in ca…`, `…It is four mont…`, `…the form a…`. Cause,
`~/bin/sms-responder.py` in `_reply_with_top_question`:

```python
body = question if not rec else f"{question} I recommend: {rec}"
if len(body) > 300:
    body = body[:297].rstrip() + "..."
```

He complains the texts are unreadable; the recommendation is the part he acts on and it was the part being
destroyed. **FIXED** — see below.

**3. `run --dry-run` could send.** Both owner-reply call sites hardcoded `textsend.send(..., dry_run=False)`,
and nothing in `cmd_run` gated them. A mode documented as "decide, send nothing" would really text his phone
whenever a row was claimable. **FIXED.**

### He was a stranger on his own line until 2026-09-28

Recorded, because it explains why he stopped reading the texts:

| when | his text | terminal state | reason |
|---|---|---|---|
| 2026-09-25 15:30Z | "The text you are sending me have way too much information at once. I don't read them. You only should text me when you have like a question one at a time…" | **ignored** | `policy` / **`allow=never`** |
| 2026-09-23 20:20Z | "What's up I'm sitting waiting for my X-ray tell me a good joke" | queued | gate closed: third-party sends are CLOSED |

His own number was stored as "Chips Zebrowski / friend / never". The row was corrected on 2026-09-28
(`relationship=owner`, `allow=auto`, note: *"the previous row said … catastrophic on allow (never = do not
answer him)"*). **The instruction he sent on 09-25 about how to text him was dropped as a stranger's message
and never became a rule.**

**A claim I made in this document and then refuted, recorded because the first version was in my own
notes:** I wrote that the `learned` table was a *residual landmine*, because it still holds
`question_id 146, phone +18483897895, allow='never'` from the period when he was a stranger, while
`permissions` says `auto`. Checked against the code: **it is inert, not a hazard.** `textctx.py:24`
declares the ledger authoritative for `allow` and `resolve()` takes it from `permissions` (`textctx.py:681`);
the only read of `learned` anywhere is `sms-responder.py:953`, `done = {question_id FROM learned}`, which
uses it purely as a *set of owner-queue answers already processed*. Nothing consults `learned.allow` or
`learned.phone`. So the row is a **misleading record, not a live failure path** — worth knowing because a
future session reading that table would draw exactly the wrong conclusion about the owner, which is how the
truncated-column measurement misread a row in H2987.

### Coverage, measured

Inbound from his numbers over 14 days, grouped by `first_seen`, is misleading because 332 rows were
backfilled on 09-18 with `date_sent` spanning 2025-09-02 → 2026-09-18. By real `date_sent` the 14 days hold
**12 texts**: 09-23 ×3, 09-25 ×1, 09-28 ×3, 09-29 ×5. All five from 09-29 reached `state='working'` with a
ledger item named. **Query for inbound with no decision returned nothing — zero undecided owner texts.**

The responder log is not a fault signal: 3,339 of its 3,492 lines read `0 to decide`, and that is a genuinely
empty worklist (`SELECT count(*) FROM messages WHERE direction='inbound' AND state='new'` → **0**), not a
dropped-message loop. The historical cause is documented in the crontab: the responder once read a store
whose newest inbound row was 2026-04-29.

### Powers, verified

| can | verdict |
|---|---|
| create a ledger item | **yes** — 10 rows, `source='owner-sms'` |
| get it executed by a full DSH session | **yes** — 6 done, one closed 05:43:55Z with proof |
| raise a wake flag directly | **no** — needs a pre-existing `awaited` row; none exists for his number |
| read the live company DB | read-only only (`_open_ro`) |
| send to a third party | **blocked** — `AITEXT_ALLOW_THIRD_PARTY_SENDS` not 1; only the owner's number is open |

### Divergence on this path — three different files

| file | where | bytes | sha256 (12) |
|---|---|---|---|
| `sms-responder.py` | `secratary:~/bin/` (the one that runs) | 70,228 | `dda178099128` |
| `sms-responder.py` | `secratary:~/harness-config/scripts/` | 38,917 | `b71e1f3a8a8f` |
| `sms-responder.py` | `ZABZ-YOGA:~/code/harness-config/scripts/` | 56,311 | (differs) |

None of the tracked copies contains the owner fast path. Ledger item **#124** ("Merge
housekeeping/121-track-sms-responder…") is `blocked` with the note that shift hard limits forbid committing.
This is the same class of failure as the stale `phone-and-tech-full` checkout that read an August tree for
weeks — **the file that runs is not the file in git.**

---

## What I changed, and how it was verified

`~/bin/sms-responder.py`, patched 2026-09-29 between 18:15:35Z and 18:22:59Z in four stages, each with its
own timestamped backup beside the file. Patchers: `_recon/fix-owner-text-path.py`,
`fix-owner-engagement-ask.py`, `fix-dryrun-consumes-question.py`, `fix-owner-uses-the-brain.py`. Each asserts
every anchor appears exactly once, compiles the result, and restores the backup if compilation fails.
Current sha read 18:29Z: `2ec96e4e213ed85d9edb4b90bdf5488e692938ad0a1703173728f8b23fb43046`.

1. `dry_run` threaded from `cmd_run` through `_maybe_ask_one` and `_reply_with_top_question` to both sends.
2. The 300-char truncation replaced: the **question** absorbs the trim, nothing is cut except at a sentence
   boundary, and the recommendation is never dropped.
3. The question path now prints `DRY-RUN, would reply` instead of claiming it replied.
4. **A dry run no longer consumes the question.** The `defer --until +7d` stamp and `_record_offered` ran
   regardless of mode, so a dry run marked a question asked — re-askable only in seven days — without ever
   putting it to him. Proven on the live store: `offered.db` before `[162,164,166,167,183]`, after
   `[162,164,166,167,183]`, `CONSUMED NOTHING: PASS`; the dry run correctly selected queue **#182**, the
   queue's own `next` once 162 had already been offered.
5. **The owner's own text is now worked by the brain.** The `work` verdict used to end in a bare
   `continue` — which is why his 03:20:01Z text produced no outbound at all. It now files the durable ledger
   item first, then runs `_do_work` (the only path carrying the real tool loop), with the holding receipt
   dropped because he called receipts pointless. `_do_work` reports its outcome, so the branch holds
   **exactly one outbound per owner text: the answer, or one question — never zero, never two.**

Verified against the **real** queue rows behind today's four texts, by extracting the patched block from the
installed file and running it (nothing sent):

| queue | old | new | new ends |
|---|---|---|---|
| #162 | 300c, cut inside `in ca…` | 584c | `…Do not use the superseded $2,318.73 run sheet.` |
| #166 | 245c, complete | 245c | unchanged |
| #167 | 300c, cut at `four mont…` | 303c | `…It is four months on.` |
| #183 | 300c, cut at `the form a…` | 597c | `…the redetermination request gets weaker the longer it waits.` |

`VERDICT: PASS on all 4 rows`. Module still loads (`sms-responder.py pending` → `0 inbound text(s) awaiting
a decision`).

The owner-brain change was verified by `_recon/test-owner-brain.py` with every side effect stubbed
(`safe_send`, `safe_can_send`, `_record` and `queue_for_owner` replaced in-process; in-memory sqlite), so no
production data was touched and nothing was sent. **The first version of that test failed, and the failure
was mine, not the patch's**: it fed `holding` straight into `_do_work`, bypassing the branch's own
transformation, so it measured the worker instead of the branch. Corrected, it reports
`A outcome=answered sends=1 it_is_the_answer=True`; a deliberate control case `A2 (holding NOT dropped)
sends=2` proves the drop is what makes it one message instead of two; `B blocked sends=0 queued=1`;
`C dry_run_passed_through=True`; plus static assertions that the installed branch runs `_do_work`, drops the
holding, and asks only when the brain did not answer. **`VERDICT: PASS`.**

The other four `dry_run=False` sites were checked and left alone: `_send_holding` (guarded at `:398`),
`_do_work` (guarded at `:419`), the non-owner reply (guarded at `:706`), and `_ack_owner_request`, which has
**no caller at all** — dead code whose unguarded send is a landmine for whoever wires it up.

---

## Still open, ranked

1. **`sms-responder.py` and `textdecide.py` are unmergeable.** `~/bin` is the truth and git is not. Until
   this closes, every future audit has to be told which file to read. Workstream WS-C builds the capture,
   the drift test and the deploy path; ledger item **#124** is the merge itself.
2. **32 owner-queue rows are pending and only 5 questions have ever been put to him by text.** The ask only
   fires when he engages, so his attention is both the trigger and the bottleneck while filing outpaces
   asking. **This is the one item that is genuinely his** — see the question below.
3. **`sent this run: 0`** is a false negative — the counter increments only in the non-owner branch
   (`sms-responder.py:720`), never at the owner reply or the question path.
4. **`released_today` reads like productivity and is not.** 132 reported against 41 distinct wake ids.
5. **`wake-tuner` costs one session per tuning subject.** 14 today. Workstream WS-B.
6. **The day's cost is flagged `unsourced`.** Two numbers for one day. Workstream WS-B.
7. **The `learned` table's stale `allow='never'` for the owner is inert but misleading** — see the refuted
   claim above. No code reads it; the record invites the wrong conclusion.

---

## The one question this left for the owner

32 questions are pending in his queue, with the oldest from 2026-09-16, and only 5 have ever been put to him
by text, because the ask only fires when he texts first. Filing outpaces asking, so most of those 32 will
never reach him.

Should the system put ONE pending question to him each day, even when he has not texted?

- **Recommended: yes, at most one per 24 h.** He asked for exactly this — *"one at a time for me to answer
  and I'll answer it"* — and the alternative is a silent backlog he never learns about. It is not a briefing
  (he has said briefings are useless): it is a single question with a recommendation, which is the only
  thing he has ever asked to receive.
- **Alternative: leave it.** The queue then drains only as fast as he starts conversations.

