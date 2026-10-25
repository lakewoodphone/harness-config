---
name: estate-sourcing-and-search
description: "Use BEFORE answering 'what do we know about X' or 'what does this cost / can we buy this'. Two entry points: esearch (ps_action search / ps_search) for what the estate already knows, and shop_sourcing.py for sourcing a laptop or a part for a customer. Covers the what= modes, the rule that searched:false is a refusal and never a negative, fa symbol / --fresh being mandatory before editing a definition, the exit codes of both tools, the one customer-facing rule, and the sourcing request format that works first time. Triggers on 'what do we know', 'did we ever', 'find the session/doc/email/text about', 'where is X defined', 'I need a laptop for a customer', 'a screen for this part', 'a charging port for this laptop', 'what would it cost us', or any question about buying, quoting or pricing hardware."
---

# Two doors: what we know, and what it costs

There are two questions that look alike and are not. Pick the door before you pick the tool.

| the question | the door | first command |
|---|---|---|
| **"what do we know"** — a document, a session, an email, a customer's words, a definition | **estate search** (`esearch`) | `ps_action("search", {"what": "all", "query": "..."})` |
| **"what does this cost / can I buy this"** — a laptop, a screen, a charging port, a quote | **sourcing** | `python scripts/sourcing/shop_sourcing.py "..."` |

Estate search answers from an index. Sourcing answers from the live market and spends money. Do not
point one at the other's question: the index does not hold today's prices, and the sourcing tool
does not know what this shop decided last month.

---

## Door 1 — estate search, from any agent on any OS

`ps_search` (or `ps_action("search", {…})`) is the cross-platform surface: sessions, texts, calls,
email, documents, code and filenames from **every** machine, including the phone.

```
ps_action("search", {"what": "sessions", "query": "the laptop quote we lost"})
ps_action("search", {"what": "data",     "query": "battery"})      # customer texts/calls/voicemail
ps_action("search", {"what": "journal",  "query": "journal lock"})
ps_action("search", {"what": "docs",     "query": "sourcing guide"})
ps_action("search", {"what": "files",    "query": "shop_sourcing.py"})
ps_action("search", {"what": "code",     "query": "create_task"})
ps_action("search", {"what": "symbol",   "query": "create_task"})  # a definition - always live
ps_action("search", {"what": "all",      "query": "..."})          # default: fused
```

`what="all"` costs the most time. If you know it is a document or a file, say so — `docs` and `files`
answer in tens to hundreds of milliseconds.

### The rule that makes the answer honest

**`searched:false` is a refusal, and a refusal is never a negative.** A store that did not answer is
unread, not empty — the same as a witness who did not show up. The response also carries
`did_not_answer` and per-store `age_s`. Read them, and say which one you got.

Live example — same tool, same minute, two different truths:

- `"5 hit(s) in 736 ms · scope=docs · live=false"` — `estate:docs` answered, `did_not_answer: []`.
  Real answer.
- `"0 hit(s) in 4003 ms · scope=all · live=false"` with `estate REFUSED — did not answer within 4s`
  and `DID NOT ANSWER (a refusal, not a negative)`. **Zero hits, but the corpus that would have held
  the answer never replied.** Reporting that as "we have nothing" is the failure this skill exists to
  stop. Re-run it narrower (`what="docs"`, `what="files"`), or say it is unread.

### Before you EDIT a definition

An index can be minutes behind. `what="symbol"` is live, always — use it, or rerun the query with
`fresh: true`, before you change anything a definition governs. Browsing may use the index; writing
may not.

### On a Linux node only: `fa`

`fa` is the same surface, node-local. It exists for the modes where an index must not be trusted:
`fa symbol "name"` and `fa anything --fresh`. Full detail — every mode, flag, and the seven defects
that were found in it — is in the **`fast-search`** skill. Read that rather than re-deriving it.

Search exit codes: **0** hits · **1** no match (a real negative) · **2** bad usage · **3** answered
but the index may be stale · **4** **nothing was searched** · **5** the index failed.
`1` that actually meant `4` is how a search tool lies — check `searched`, not just the text.

---

## Door 2 — sourcing, for a customer or the shop

One front door, run from the `lpt-hub` repo root:

```bash
python scripts/sourcing/shop_sourcing.py "laptop for a customer, 16gb, max 400" --target-sell 550
```

**Today `shop_sourcing.py` is not on the mesh yet.** What runs is the fan-out behind it:
`python scripts/sourcing/sourcing_fanout.py "dell latitude 5420 16gb" --no-google --class whole`
— no `--budget`, no `--target-sell`, so the ceiling is yours to enforce. Guide §0 has the
verified output, including the `NOT ANSWERED (not 'nothing found')` line.

**The request format that works first time — four things, in this order:**

1. **the model** (`dell latitude 5420`, `hp elitebook 840 g5`) — without it a part cannot be matched;
2. **what it is** (whole laptop / screen / charging port / battery / keyboard);
3. **the ceiling**, as `--budget` — **all-in: price + shipping**;
4. **for a part, the spec word that decides fit** — panel size, resolution, **touch or non-touch**,
   connector; barrel jack vs USB-C; the exact generation.

`"screen for a dell latitude 5420" --budget 80` — not `"i need a screen"`.
`"charging port for an hp elitebook 840 g5" --budget 30` — not `"charger for hp"` (a charger is an
accessory, a port is a part).

Other flags: `--target-sell`, `--kind auto|whole|part|accessory`, `--model`, `--per-source`, `--sites`,
`--dry-run` (plan only, no spend), `--json`, `--save`. **`--dry-run` first** on any unfamiliar request.

Sourcing exit codes: **0** answered (read the blocks) · **1** nothing matched (a real negative) ·
**3** **no credentials** · **4** **every source failed** · **5** bad request.

**`3` and `4` are refusals.** Nothing was read. "We couldn't look" is not "there is nothing there" —
and a source showing `FAILED` in the `MARKET` block is not a source with zero results.

**A sample of three offers is not a market.** Three picks prove three things exist at that price; they
do not give you a floor, a ceiling, or the next-best machine. A verdict built on fewer than five
observations is not a verdict. When the answer will become a price the shop charges, escalate a tier
(API → aggregator → stealth scrape → browser) and check the site's rung with
`python scripts/sourcing/fetch_ladder.py --status` — do not average what you happen to have.

The money: `customer_total = all_in × 1.36 × 1.06625` (36 % markup, 6.625 % NJ tax — recorded in
`lpt-hub/docs/customer-operations/sourcing/laptop-buying-knowledge.json`). **Shipping is inside
`--budget` because it is inside the cost.** Work backwards before sourcing: `all_in_max = sell ÷
(1.36 × 1.06625)`, so a $400 customer price caps the buy at **$275.84** and $550 at **$379.28**.

**Grade and price are not monotonic in the used market.** Sweep the grades (`2000` Certified,
`2010` Excellent, `2020` Very Good, `2030` Good) and record each, rather than assuming a better grade
costs more — measured 2026-09-14, Very Good/Good refurbished sat at $128–$150 while Excellent was
$317–$323 and genuinely new was $323, and the owner rejected the cheap grade on sight.

Full operator path, including what each output block means and when **not** to buy:
`lpt-hub/docs/customer-operations/sourcing/SOURCING-GUIDE.md`.

---

## The one customer-facing rule

**Never send a customer a marketplace link, a source price, a seller name, an item id, ASIN, SKU or
margin — the customer sees brand + broad product family + new/refurb + the LPT total + what is
included, signed `- Daniel`.** Authority: `lpt-hub/docs/customer-operations/CUSTOMER-SMS-RUNBOOK.md`
(hard rule §0a) and `personal-secretary-mvp/AGENTS.md` §"NEVER Share Sourcing Details". A near-miss
in 2026-06-19 would have revealed a $169 cost on a $245 sale. Nothing outbound without a per-message
yes in the current conversation.

---

## Two failure modes worth naming

- **Answering from an index you were about to write against.** Search first, edit second — `symbol` /
  `fresh`, not `all`.
- **Reporting a refusal as an empty result.** `searched:false`, `did_not_answer`, `FAILED`,
  exit `3`/`4`: all of these mean *unread*. Say unread.
