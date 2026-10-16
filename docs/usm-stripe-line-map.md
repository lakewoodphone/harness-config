# US Mobile lines ↔ Stripe subscriptions — the mapping that nowhere held

**Built 2026-10-16.** `~/bin/line-map.py` on the authority, tests at `~/bin/tests/test_line_map.py`,
cron every 12 hours. Source in `harness-config/scripts/line-map.py`.

## Why it exists

The owner pasted the US Mobile line inventory and asked for it to be matched against Stripe. That
took a session of ad-hoc scripts, because **no store recorded which line a subscription pays for.**
The link lived in Stripe, in the US Mobile page, and in his head, and nothing joined them. That is
how a line can go active and unbilled, or a subscription keep billing after its line is gone,
without anyone noticing.

## The two errors that shaped it, both mine

**1. `unit_amount` is not the subscription amount.** I reported Heichal Hatorah as paying **11.00**
where the truth was **11.00 × 6 = 66.00**, and total recurring as **89.00** where it was **144.00** —
understated by exactly the quantity I had failed to count. The owner corrected me: *"doesn't heichal
pay 66 a month, get this straight."* I was one step from reporting a 55.00/month revenue leak and
asking him to authorise a billing correction to a customer already billed correctly.

> **Every money figure this tool prints is `unit x qty = total`, with all three terms visible.**
> `144.00 = (11.00 x 6) + 12.00 + (11.00 x 6)` is self-checking; `89.00` was confidently wrong.

**2. A phone number is not a join key.** I called Ahron Bodner a duplicate subscriber. He has **two
lines** — 845-558-1290 and 908-770-1707 — and two subscriptions, correctly. The Stripe customer's
phone is the customer's *personal* number, not the line being billed. Only **2 of 8** subscriptions
matched a line by number; the rest only by name.

## Design rules, each for a measured reason

- **`line_key`, not `line_number`, is the key.** The owner's own number **848-389-7895 carries two
  lines** — an Unlimited phone and an Apple Watch. A shared number is normal for a wearable. Keying
  on the number silently *dropped one*, so the page's 20 lines read as 19.
- **A mapping is never invented.** Matching proposes; a person asserts. Every row records **how** it
  was derived — `PHONE`, `NAME`, `ASSERTED` or `NONE` — so a guess is never mistaken for a fact.
  Heichal's six lines cannot be derived from any data; they are an assertion by the owner and stored
  as one.
- **The alarm is a count mismatch.** A subscription's `quantity` must equal the number of lines
  mapped to it. That is what would have caught six lines billed as one — and it catches the reverse.
- **A null never overwrites a stored value**, and **a weaker source never overwrites a stronger
  one.** Both rules exist because the first version broke both: a failed parse replaced nine good
  labels with nulls, and a re-seed reset `ASSERTED` links back to `NONE`.
- **Read-only against Stripe and Postgres.** The only thing written is this tool's own tables.
- **It refuses rather than guesses.** `sync-usm` refuses when the parsed line count changes, because
  a changed count is either a real change or a broken parse and only a person can tell which.

## The reconciliation, verified 2026-10-16

| customer | unit × qty | per month |
|---|---|---|
| Heichal Hatorah — covers `Line 15`–`Line 20` | 11.00 × **6** | **66.00** |
| zevi lefkowitz | 12.00 × 1 | 12.00 |
| Hess, mrs greenwood, avrohom newman, baruch ber svei, Ahron Bodner ×2 | 11.00 × 1 each | 66.00 |
| | | **144.00** |

**20 lines: 13 billed, 7 not.** The seven are the owner's own two (the same number twice) and five
shop lines — four test SIMs and one pending. **No customer line is unbilled.**

## What it cannot do, stated rather than glossed

Heichal Hatorah exists as customer 2551 with **zero orders**, and their six line numbers appear in
**no store at all** — their `stripeCustomerId` is NULL in the shop DB. The link between that
customer, their six lines and their subscription exists only in Stripe and in the owner's head. This
tool now records it, but it cannot *verify* it; only a person can.

Two customers (Hess, baruch ber svei) carry the **owner's own Google Voice number** and the shop's
Gmail as their Stripe contact, so their invoices go to the shop rather than to them — recorded by the
tool, not fixed by it.

## Usage

```bash
line-map.py sync-usm <page.txt>     # ingest a pasted US Mobile page (refuses on a count change)
line-map.py sync-stripe             # subscriptions + customers, quantity counted
line-map.py assert <number> --holder H --kind K --sub SUB --by WHO
line-map.py audit                   # the one query: billed, unbilled, unmatched, money
line-map.py check --flag            # exit 3 on drift; raises a wake flag
```

Cron runs `sync-stripe` then `check --flag` every 12 hours, logging to
`~/.sms-inbox/line-map-check.log`, because a mapping that is silently wrong is worse than no mapping.
