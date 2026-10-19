# Handoff — cheap-hour scheduling and provider routing for the autonomous company

**Written** 2026-10-19 by the owner's session on ZABZ-YOGA, from the cloud/storage audit of the same
day and from the owner's own words in the conversation that followed.
**For** an orchestrating agent who owns this end to end and is expected to spend many hours on it,
fanning out, in rounds — not to close it in one pass.
**Owner's instruction, verbatim (2026-10-19):**

> "So I want you to write a handoff document… I'll give it to another agent who should sit there
> fanning out, orchestrating and engineering this. It's a massive job because I want to be done well.
> Not like half were done. So I want it to build a system for the autonomous company to prioritize
> inexpensive hours. And then separately do full research on windows inexpensive hours are and route
> and enter that into environment variables. That's probably a very good idea. Also, maybe during the
> expensive times, see if there's other companies like deep infra that during the expensive times,
> they would be cheaper and maybe route to them. Then we need a way smarter timing and routing model
> and then environment variables to fill it in."

---

## 0. The one sentence

**The same work, done at the cheapest hour and on the cheapest provider that is good enough, decided by
configuration rather than by code, and measured in money.**

Nothing about the company's capability changes. No model is silently downgraded, no work is dropped,
no customer-facing sentence changes. The only things that change are *when* a tick runs and *which
provider* answers it — and both of those live in environment variables that an operator can edit
without touching a line of code.

## 1. Why this is worth many hours — the measurement that started it

> **CORRECTION, 2026-10-19T22:15Z, by the agent this handoff was given to — read this before §1's
> numbers.** DeepSeek's peak window is **Mon–Fri 01:00–04:00 and 06:00–10:00 UTC** (35 of 168 hours,
> 20.8 % of the week), off-peak being exactly half. The 00:30–16:30 window below is the *retired*
> scheme. Measured against the real window: peak share of input is **27.7 %**, not 84 %; the week costs
> **105.18** = **450.8/month**, not 650; and the scheduling prize is **97.7/month, 21.7 %**, not 310.
> The bank's 636 is top-ups, not consumption — the account held an unconsumed 145.77 balance.
>
> **And the larger lever is not the clock at all.** DeepInfra Flex serves the same model generation at
> **0.112 in / 0.336 out with no hour dependency**, which is below DeepSeek's own off-peak rate; routing
> there is **41.4 %**, with nothing delayed. Fireworks Standard is 0.30/1.20 — exactly DeepSeek peak, so
> it is worth no key at all. That reverses the round order in §6: routing pays first.
>
> Evidence, all dated: `personal-secretary-mvp/docs/cost/PRICES.md`, `prices.json`, and journal
> `L10047`. Everything below is retained unedited as the record of the brief as it was given.

From `docs/cloud-audit/2026-10-19-cloud-and-storage-audit.md` section 4, and the owner-queue row #830
built from it (re-verify all of it in rounds 1–3; do not take it on trust, and do not quote it as
yours until you have):

- DeepSeek prices by UTC hour. Peak (00:30–16:30 UTC) is 0.30 in / 1.20 out per million tokens;
  off-peak (16:30–00:30 UTC) is 0.15 / 0.60. **Peak is exactly double.**
- Over 7 measured days, **449.2 M of 534.5 M input tokens — 84 percent — were spent in the peak
  window**, because the departments tick around the clock and nothing in the system knows or cares
  what time it is.
- Priced by the hour each token was actually spent in, that week cost **151.70, which is about 650 a
  month**. The bank agrees: **636 in debits over 31 days, within 5 percent.**
- The same tokens, moved into the cheap window, cost **about half — roughly 310 a month saved** with
  no capability lost.

That is the prize. It is not a trick and it is not a one-off: the company will keep spending this
every month until scheduling knows what a cheap hour is.

## 2. What must exist at the end — five artefacts, all verified

1. **A price and window table that is data, not code.** Every provider and model the company actually
   uses, with its per-hour price bands, its unit (per million tokens, in and out), the source URL, and
   **the date the price was read**. Held in configuration. A price change is an env-var edit.
2. **A scheduler that prefers the cheap windows** and can prove it: the share of tokens spent in each
   provider's cheap band, per day, measured — with a target the owner set by policy, not hardcoded.
3. **A router that picks the cheapest adequate provider for a given request**, with a quality floor
   that is explicit and testable, a fallback chain, and a published record of which provider/model
   actually served every request and at which price.
4. **A kill switch**: one variable restores today's behaviour exactly (flat schedule, current
   provider), without a deploy. If the new system is wrong, the company reverts in one edit.
5. **A one-page state file and a document** that let a fresh agent resume mid-flight, plus a
   regression test that fails when the price table goes stale.

## 3. Non-goals — do not drift into these

- **Not a model-quality project.** You are not changing which model is "best". You are choosing the
  cheapest provider that passes the quality floor that already exists.
- **Not a rewrite of the company.** Do not replace the tick loop, the work-order engine or the agent
  framework. Add scheduling policy and routing policy to what runs today.
- **No new accounts, no purchases, no signups.** If a cheaper provider needs an account or a key the
  estate does not have, that is a one-line item for the owner — see §7. Never create an account, never
  enter a card, never accept terms on his behalf.
- **No customer-facing change.** No email, SMS or call goes out because of this work. None.
- **Do not delete or rewrite telemetry.** The old numbers are the baseline you will be judged against.

## 4. Ground truth — read these before you design anything

**The estate's rules (binding, and they are not suggestions):**
- `~/code/harness-config/AGENTS.md` — every section, especially §0 (prove it does not already exist),
  §5 (a machine's posture is decided by `settings/machines/host-posture.tsv`, not by memory), §6.1
  (never `git pull --rebase`; push your own commit), §8 (never rewrite a running script in place —
  `cp -p`, validate, `mv`).
- `~/code/harness-config/journal/README.md` and `journal.py status` — the memory that outlives you.
- Skills: `parallel-agent-orchestration` (the fleet procedure and the brief contract) and
  `estate-systems` (read before designing anything that already exists).

**The systems you are changing:**
- `personal-secretary-mvp` — the autonomous company: FastAPI, ~618 routes, ~199 services, ~203 tables,
  the tick loop, the workflow engine, the graduated-autonomy framework. On `secratary-cloud`.
- Authority database: **`/root/authority.db` on `secratary-cloud`, the sole writer of it.** Tables to
  start from: `tick_telemetry`, `model_usage`, `agent_budgets`, `routing_log`, `work_sessions`,
  `activity_log`, `operation_journal`, `circuit_breaker_state`. Read them; do not restructure them
  without a migration and a reason.
- The AI gateway. The company reaches models through `$SECRETARY_API_BASE`; the catalog is
  `GET $SECRETARY_API_BASE/v1/models`. **Models are never hardcoded in application code** (journal
  lesson L1606): prefer the route aliases (`secretary-auto`, `secretary-fast`, `secretary-smart`);
  never `secretary-genius` (measured 502 on 2026-09-15); allow an operator override per tier as a
  comma-separated env chain; validate every configured id against the catalog and drop what is not
  listed; cache with single-flight; fail soft; and **publish which model actually served a request**.
  An AI outage must never be silent.

**The prior work:** `docs/cloud-audit/2026-10-19-cloud-and-storage-audit.md` (sections 1 and 4), and
the five queue rows that came from it (#717, #719, #720, #721, #830). A journal search for prior
cheap-hour scheduling work on 2026-10-19 returned **no match** — there is no earlier implementation to
reuse, and you should confirm that yourself before you start writing code (§0).

## 5. The shape of the solution — the interface, not the implementation

The implementation is yours. The **interface** must satisfy these, because they are what the owner
asked for in his own words ("those could just be like environment variables that you could change
without changing any of the code"):

**Windows are data.** Something equivalent to:

```
SCHEDULE_PROVIDER_WINDOWS="deepseek=00:30-16:30:peak,16:30-00:30:cheap"
SCHEDULE_CHEAP_SHARE_TARGET=0.8           # policy: what fraction of ticks must land in a cheap band
SCHEDULE_MODE=legacy|cheap-first|cheap-only
SCHEDULE_CLOCK=UTC                         # never the host's local time; DST must not move a window
```

**Prices are data.** Something equivalent to a table keyed by provider+model+tier, carrying
`in`, `out`, `unit`, `currency`, `source_url`, `read_at` — validated at startup, so a typo or a missing
band fails loudly at boot rather than silently mis-routing at 03:00.

**Routing is policy.** Something equivalent to:

```
ROUTING_MODE=fixed|cheapest-adequate|cheap-window-first
ROUTING_QUALITY_FLOOR=<the existing tier that must still be met>
ROUTING_FALLBACK_CHAIN=<provider,provider,...>
ROUTING_KILL_SWITCH=...
```

Rules for that interface:
1. **No code edit to change a window, a price, a provider order or the policy.** If an operator must
   open a file other than an env/config file, the design is wrong.
2. **Loud validation at startup.** Unknown provider, unparseable window, a window that does not
   cover 24 hours, a price with no `read_at`, a model id not in the gateway catalog → refuse to start
   in the new mode, or fall back with a counter and a log line that a human will actually see.
3. **One kill switch, tested.** You will prove it works by flipping it, measuring, and flipping back.
4. **Every decision is recorded**: which provider, which model, which price, which window, and why —
   in a row you can query later. "Why did July cost more" must be answerable from the database.

## 6. The round plan — 30 rounds, each with a definition of done

Thirty rounds is a **budget, not a target**: if it is finished and proven in twelve, stop and say so.
Never mark a round done on "it should work". Each round ends with evidence in the state file, and
each round must leave the system running.

**Rounds 1–3 — truth.** Re-derive the numbers yourself: read `tick_telemetry` and `model_usage` for
30 and 90 days, reconstruct the peak/cheap split, and reconcile against the bank debits. Read DeepSeek's
publish**ed** price page yourself on the day and record URL + date + the exact bands. Then survey the
real alternative providers for the models the company actually calls (DeepInfra, Fireworks, Together,
Groq, OpenRouter and anything else that offers the same weights) — **prices with source and timestamp,
capability notes, rate limits, and whether the estate already has a key**. Nothing is "cheaper" until
two dated numbers are side by side. Output: `PRICES.md` + the machine-readable table, both in the repo.

**Rounds 4–6 — baseline and instrumentation.** Establish the before-numbers: tokens, cost, ticks per
hour, work completed per token, and the peak share. Make sure the instrumentation you need already
exists or add it — you cannot prove a saving you did not measure. Freeze the baseline in the state file.

**Rounds 7–12 — the scheduler.** Ticks prioritised into cheap bands; queue depth, starvation and
fairness designed for; work that must be timely (a customer reply, a payment) explicitly exempt and
listed; per-agent budgets respected; restart-safe (a restart must not lose the plan); idempotent; and
a dry-run mode that prints what it *would* do for a day before it does it.

**Rounds 13–18 — the router.** Cheapest-adequate selection with an explicit quality floor, a fallback
chain, per-provider rate-limit awareness, and single-flight catalog caching. Quality guardrail: the
same eval or a fixed battery of representative tasks run against the candidate providers, recorded, so
"adequate" is a measurement and not an opinion. Publish the served model per request.

**Rounds 19–24 — robustness.** Design against, and test: everything piling into one window and hitting
rate limits; a provider outage during the cheap window; a clock/timezone/DST error (the window is UTC —
prove it); a stale price table; a window that covers 24 hours; an operator typo; a tick that must run
now and cannot wait; a restart in the middle of the plan; and the kill switch. Each of these gets a test
that fails before the fix.

**Rounds 25–27 — the money proof.** Run for a full week at target settings against a comparable prior
week. Report: tokens (input/output), cost, cost per completed work unit, peak share, failures, and
quality guardrail results. **If it is not cheaper, say so plainly and revert.** A change that costs the
same and is more complex has failed.

**Rounds 28–30 — durability.** The doc, the state file, the runbook ("how to change a price", "how to
add a provider", "how to revert"), the regression test that fails on a stale price table, and a final
pass by a second agent that did not write the code.

## 7. What stops and goes to the owner

Stop and ask — one question, with a recommendation — only when:
- **money leaves the estate**: a new paid account, a top-up, a plan change;
- **a provider needs a key or an account the company does not already have**;
- **the only way to save the money is to accept a visibly worse answer** for something a customer sees;
- **the cheap window would delay something with a deadline** (a customer reply, a filing, a payment).

Everything else is yours: naming, layout, library choice, table shape, scheduling algorithm,
round boundaries. Do not bring a document for review and do not bring a menu.

## 8. Records and reporting

- **Journal** (`journal.py append lessons|decisions|handoff`) after every round that changed something
  or learned something. Transferable facts only — "the DeepSeek window is 00:30–16:30 UTC and the
  gateway catalog caches for 300 s" beats "we discussed scheduling".
- **State file** in the repo, rewritten each round: what is built, what is measured, what is next, what
  is blocked, and the exact command to reproduce the last measurement. Assume the next reader has no
  memory of you.
- **To the owner**: one page per milestone, numbers first, no tables of flags, no "please review".
  He reads results, not plans.

## 9. Guardrails that must not be broken while you work

- **Nothing outbound.** No email, SMS, call or supplier message, ever, as part of this work.
- **`secratary` is a FROZEN rollback anchor.** Read only: nothing started, stopped, enabled, unmasked
  or restarted there. Before touching any host's service state, read
  `settings/machines/host-posture.tsv` — it decides.
- **The authority database is written only by `secratary-cloud`.** One writer.
- **Never rewrite a running script in place** — `cp -p`, validate, `mv`.
- **Git**: your own branch, your own commit, never `git add -A` (other sessions share these checkouts),
  never force-push, never `git pull --rebase` to make a push fast-forward.
- **Restart discipline**: a running service holds the old inode. Measure, restart deliberately, verify
  the new behaviour, and say which unit and when.
- **Never print a credential.** Names only.
- **Every claim carries its source** — command and output line, table and row, file and timestamp. If
  you cannot say where you read it, write NOT VERIFIED and move on.

## 10. The fleet

Fan out with the `parallel-agent-orchestration` skill: one worktree per stream, briefs that are
self-contained (the child sees none of your context), and a merge order you state in advance. Useful
split for the middle rounds: (a) price research and the data table, (b) scheduler, (c) router,
(d) instrumentation and the money proof, (e) adversarial testing. Rounds 1–3 should be one agent —
the truth must be one voice before five people build on it.

Use the `admission_governor` before a burst: it answers GRANTED or QUEUED and its budget comes from the
host's free memory at call time. Queue rather than amputate.

---

## 11. Definition of done, stated as measurements

The work is done when all of these are true and have been shown, not asserted:

1. **Peak share** of input and output tokens below the configured target (default 20 percent) for a
   full week, per provider, from `tick_telemetry`/`model_usage` — with the query in the report.
2. **Monthly spend** on model tokens at least 40 percent below the 650 baseline, **with tokens per
   completed work unit unchanged within noise** — same work, less money.
3. **Every routing decision** traceable to a provider, a model, a price and a `read_at` date.
4. **The kill switch** demonstrated: flip it, observe the old behaviour return, flip it back.
5. **The stale-price test** fails when a price entry is older than its configured tolerance, and passes
   when it is refreshed.
6. **A week of running** with no increase in failed ticks, no work starvation, and the quality
   guardrail at or above its baseline.
7. **One command** on a fresh machine reproduces the week's numbers.

If any of those is not true, the work is not done — and saying so is a success, not a failure.
