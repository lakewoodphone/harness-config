# Premise freshness — re-measuring a decision before it reaches the owner

**Built 2026-10-16 on `secratary-cloud`.** `~/bin/premise-check.py`, tests at
`~/bin/tests/test_premise_check.py`, cron every 30 minutes, and a hook in `owner-queue.py`.

## The problem, measured rather than asserted

`owner-queue.py amend` already carried the rule, in its own docstring:

> *"an item is a statement about the world at FILING time. When the measurement moves, the item
> moves with it, or the next shift spends its opening minutes chasing a ghost."*

**`amend` is the mechanism. Nothing ever ran it.** Over one session on 2026-10-15, across a queue
that had just been cut from 127 rows to 24, five premises had moved:

| row | what it said | what was true |
|---|---|---|
| **#448** | approve 20–30 USD/month to resize the box to a 4 vCPU / 16 GB CCX23 | **it already was one** — `nproc` 4, `MemTotal` 15.2 GiB, `SwapTotal` 8 GiB, and `docs/mesh/188` names it |
| **#514**, **#449** | fund a balance / top up a card | **already resolved by reality** (AI credit 261; Telnyx 10,597 cents, 6 active SIMs) |
| **#492** | "76 days late" | 78, and **+1 every day** |
| **#512** | "the 23 recording names" | its own amendment says **30 files and neither card is his** |
| **#465** | tax 25,671.84 / 1,700.76 | reproduced **to the cent** — which was only knowable by re-running it |

**A queue row decays, and a row whose premise is a live number has a shelf life of hours.** Two of
those rows had already been handed to the owner before anyone noticed.

## What it does

A named **probe** re-measures one row's premise and returns a verdict:

| verdict | meaning |
|---|---|
| `fresh` | the premise still holds; the measurement is recorded, nothing else changes |
| `changed` | the premise has **moved**; the row is amended with the fresh measurement |
| `unprobed` | no probe speaks to this row — honest, and counted, never silently "fresh" |
| `unknown` | a probe applies but could not run (no source, unreadable store) |

## The design decisions that matter, each forced by a real failure

**1. `auto` versus `explicit`, and it is the most important line in the file.** Only probes that
re-measure **what the row itself asserts**, with no external lookup, may fire automatically:
`elapsed` and `deadline`. Everything else — `provider`, `merchant`, `balance`, `flag`,
`repo-citation` — fires **only** when a row says `[probe:NAME]`.

This exists because heuristic detection produced *adjacent-question matches* within the first hour:
the word "balance" made a family-tuition row (#169) and a Chase-card row (#482) both report the **AI
credit** balance; the word "stripe" made the sales-tax row (#465) report Stripe's last ledger charge
instead of its own deadline. **Every one of those answers is true and irrelevant, which is worse than
answering nothing — it looks like evidence.**

**2. Not found is `unknown`, never `changed`.** The repo-citation probe's first version hard-coded
three repository paths, and on its first real run declared row 465's cited file "NOT found" — because
the file lives in a repository that was not on the list. That is the estate's own recorded trap (*a
path you did not check is not an absence*) and the same error I made by hand with a camera citation.
It now enumerates every repository the host can see (bounded at 60) and returns `unknown` when it
finds nothing, because absence from a search is not evidence about the thing searched for.

**3. A probe failure is never `fresh`.** Empty or failed results become `unknown`, because an empty
result is a refusal, not health.

**4. Idempotent by budget.** A probe is only re-run when its recorded check is older than
`expected_max_age_hours` — the shape `finance_source_registry` already uses for data sources. A second
sweep immediately after the first reports `due for re-measurement: 0`.

**5. Read-only, and it writes through the queue's own tool.** No probe writes to any system. An
amendment goes through `owner-queue.py amend` as a subprocess argument list, never a shell, so the
queue's own P265 guard still applies.

**6. The delivery hook is guarded.** `owner-queue.py next` now prints, before the row:

```
  1 pending row(s) have a premise that MOVED since filing - the row is not wrong, it is OUT OF DATE:
     #492   stated 75 days late, measured 78 days as of today (due 2026-07-30) - the row's figure has DRIFTED
```

with the whole thing wrapped so a missing or broken checker cannot break the queue tool — verified by
hiding the tool and re-running `next` (rc=0, no traceback).

**And it warns about *any* moved row, not just the one chosen.** The first version only spoke about
the row `next` happened to pick, and the genuinely moved row (#492) was **deferred** — so it was never
chosen and its drifted count would have gone unseen. A warning that only appears when you are already
looking at the right thing is not a warning.

## Usage

```bash
python3 /root/bin/premise-check.py probes              # what probes exist, and which are AUTO
python3 /root/bin/premise-check.py check 465           # one row, writes nothing
python3 /root/bin/premise-check.py sweep --dry-run     # what is due, and what each would say
python3 /root/bin/premise-check.py sweep --apply       # re-measure, record, amend where moved
python3 /root/bin/premise-check.py gate 492            # exit 0 = safe to present, 10 = premise moved
```

State lives in `owner_premise_check` on the authority (`row_id, probe, checked_at, verdict, detail,
expect_max_h`). The sweep runs every 30 minutes under `cron-wrap.sh premise-check`, logging to
`~/.sms-inbox/premise-check.log`.

## How to extend it

**Tag a row** — put `[probe:merchant]` (or any probe name) in its context, and say what you are
declaring. Only tag when the probe measures *that row's own premise*: a wrong tag recreates the
adjacent-question problem the auto/explicit split exists to remove. Tagging the seven obvious rows
took the `unprobed` count from 31 to 24 and made `[probe:NAME]` the queue's own way of recording how a
decision should be re-checked.

**Add a probe** — one function returning `(verdict, detail, max_age_hours)`, or `None` when it does
not apply; register it in `PROBES` with `auto=False` unless it re-measures the row's own text; add a
test that pins the shape it must **not** match.

## What it does not do

It cannot know how to re-measure a premise nobody has described — **24 of 32 pending rows are honestly
`unprobed`**. It does not decide anything: a moved premise becomes a `changed` verdict and an amended
row, never a resolved one. And it does not replace judgement: it tells you the number moved; whether
the decision still stands is still the reader's.
