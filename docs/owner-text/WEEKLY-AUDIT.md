# The owner-text weekly audit

`scripts/text-channel/owner-text-audit.py` — the instrument the weekly audit runs on.

## Why it exists

The owner asked, verbatim, that the texting back-and-forth system be **"constantly
learning and optimizing itself"**, and that the autonomous wake system **"every week or
two"** audit and evolve it.

That is a standing instruction to mutate the channel on evidence, not on vibes. This
script is the evidence. It reads the channel's own history and prints eight numbers and
a ranked defect list, so a woken session fixes the worst thing instead of re-reading 500
texts and guessing.

It is read-only. `--flag` is the only side effect, and it fires only on a breach.

## The eight metrics, their thresholds, and why those numbers

| # | metric | threshold | why that number |
|---|---|---|---|
| 1 | `delivered` / `refused` / `failed` / `inbound`, and `refusal_rate = refused/(delivered+refused+failed)` | `refusal_rate > 0.5` | `delivered` counts **distinct `twilio_sid`** because `sms_log` logs the same send twice; `refused` and `failed` count **rows** (a suppressed row has no sid at all). The denominator mixes the two on purpose — the output says so. Below half, suppression is doing its job; above half, the channel mostly manufactures text it then refuses to send. |
| 2 | `repeat_index` (top repeated bodies) and `max_repeat` | `max_repeat > 1` | A body sent more than once to him is noise he can see. One delivery is the healthy maximum, so anything above 1 is a defect. Counted on **distinct sids**, so the duplicate log cannot fake a repeat. |
| 3 | `double_sends` — same normalised body, distinct sids, ≤120 s apart | `> 0` | Zero tolerance: the same words twice inside two minutes is visible and embarrassing. Measured live 2026-10-18 — seven pairs, the tightest 0.188 s apart. |
| 4 | `silent_outcomes` — `relay.attempt` rows `pending`/`queued` older than 6 h | `> 0` | A message we believe we sent and did not. 6 h is long enough that no live send is still legitimately in flight, short enough that it is caught the same day. There is no acceptable number that vanished. |
| 5 | `unanswered_backlog` — `owner_text_turn` open, `sent_at` older than 48 h; plus `answered_after_expiry` (`answered_at > sent_at + 7 d`) | `> 0` | 48 h is two owner-days: past that, either the question should never have been asked or the gate is now blocking the channel. 7 d is the gate's own life; an answer after it answered a question nobody was still holding. |
| 6 | `answer_latency` — median minutes from `sent_at` to `answered_at` | none (reported) | Not a defect by itself; it is the cost of the gate, and the number the next fix is measured against. The exact SQL is printed. |
| 7 | `internal_asks` — a money question that was answered, where `answered_at` is later than `asked_at` by more than 0 min | `> 2` | The provable subset of "it asked him something it then answered itself". One or two is a legitimate fallback; a pattern means the ask should have been resolved before it reached him. 2 is the tolerated count. |
| 8 | `truncation` — bodies containing `cut short` / `[cut` / ending in `…`, and the original's length where recoverable | none (reported) | Every `[cut short - ask me to continue]` is a message that asked *him* for the rest. The original is recovered through `attempt.ref = owner_message_queue:<id>`; when it is not recoverable, that is reported as unrecoverable, not guessed. |

A ninth block, `owner_decision_queue` pending over 48 h, is printed as **supporting**
information with no threshold. A stale decision queue is the same disease as an
unanswered text, but it is not this channel's to threshold.

## How the flag is raised, and why it must be conditional

`--flag` evaluates `THRESHOLDS` (at the top of the script) and calls the frozen CLI
**only if a measured value breaches**:

```bash
python3 /home/zabz/bin/wake.py flag \
  --subject "owner-text-audit:2026-W42" --prompt "<the brief>" \
  --kind owner-text --source owner-text-audit --priority high
```

Nothing on a timer may file work merely because time passed — that is the one rule that
keeps the wake system from becoming a session factory. The subject is the **ISO week**
(`owner-text-audit:2026-W42`), so the same week cannot file twice: the store's `UNIQUE
subject` turns a second attempt into `deduped`. The brief carries the metric table, the
breached thresholds, the top three defects with ids and timestamps, and the standing
instruction.

When nothing breaches the script prints `no flag: all metrics within threshold` and files
nothing.

## Run it by hand

```bash
python3 ~/code/harness-config/scripts/text-channel/owner-text-audit.py            # 14 days, human
python3 ~/code/harness-config/scripts/text-channel/owner-text-audit.py --days 7   # shorter window
python3 ~/code/harness-config/scripts/text-channel/owner-text-audit.py --since 2026-10-01
python3 ~/code/harness-config/scripts/text-channel/owner-text-audit.py --json     # one JSON object
```

Exit codes: **0** every metric computed (defects found or not) · **2** a data source was
unreadable — the affected metric is `null` with a `reason` and is named on stderr, the
others still report · **3** usage error.

## Install

Deploy (the repo is the source of truth, `~/bin` is not):

```bash
install -m 0755 ~/code/harness-config/scripts/text-channel/owner-text-audit.py \
                /root/bin/sources/owner-text-audit.py
```

Crontab — weekly, Monday 06:17 UTC, one line:

```cron
17 6 * * 1 cd /root/bin/sources && /usr/bin/python3 owner-text-audit.py --flag >> /root/.sms-inbox/sources.log 2>&1
```

Test it without filing a flag — this prints the exact brief and writes nothing:

```bash
python3 /root/bin/sources/owner-text-audit.py --flag --dry-run
```

Offline tests (no network, no live database; builds temporary SQLite files from the live
`CREATE TABLE` statements and plants every defect shape):

```bash
python test-owner-text-audit.py
```

## What a woken session is expected to do

1. Read the brief's metric table before touching anything. The raw number is the claim.
2. Pick the **single worst defect** — the ranking is severity for him, not for the database.
3. Fix it at the **composer or the door that owns it** — not in this audit, and not by
   widening a threshold. If `double_sends` fires, the door that posts twice is the bug;
   if `silent_outcomes` fires, the door that leaves a row `pending` is the bug.
4. **Prove it against the live ledger**: re-run the audit, show the metric moved, and show
   the rows that prove it.
5. Record the decision (journal entry) and leave a note for next week's audit — what was
   fixed, what was measured, what is now the worst.
6. Do not send anything to anyone. Do not touch `secratary` (frozen). Do not un-break a
   metric by silencing it.
