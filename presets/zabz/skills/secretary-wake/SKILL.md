---
name: secretary-wake
description: Use when work has to happen while no session is open, when you are waiting on a reply from anyone (a customer, a vendor, the owner, a colleague), when something on the secretary server detects a problem that needs real work rather than a decision, or when the owner asks how you stay alive / how you get reactivated / how a reply reaches you. Also use BEFORE sending a message that expects an answer, so the await is registered. Explains the flag store, the safety envelope, and the one rule that keeps it from becoming a session factory.
---

# The secretary is the always-on half

You have no continuous memory and no continuous existence. A DSH session starts when a human types, and
ends when it stops. **Everything between those moments was, until 2026-09-18, nothing.** The owner put
it exactly: *"this may be the final piece in the puzzle to making you truly autonomous."*

The secretary server (`secratary`) is now the half of you that never sleeps. It watches, it decides
small things itself, and — this is the new part — **it can raise a FLAG that revives a full DSH session
on the always-on desktop with nobody at a keyboard.**

```
CAPTURE   sms-inbox.py       every inbound/outbound text, reconciled from Twilio every 5 min
BRIDGE    mirror-owner-sms.py the OWNER's live texts from the app's sms_log into the inbox store
ROUTE     sms-responder.py   answer it (allow=auto), or file it as a ledger item
LEDGER     work.py           ~/work/work.db - the durable record of what each project owes, and where
                             a woken shift ACTUALLY gets its work (see "the project loop" below)
FLAG      wake.py            anything that KNOWS there is work raises a flag
WAKE      wake-dispatch.sh   claims one flag -> ssh -> ZABZ-TECH -> dsh --profile headless -> result back
FAN-OUT   wake-fanout.sh     keeps N shifts in flight at once, counted by live PROCESS not by claims
STATUS    autonomy-status.sh ONE read-only command that answers "what is the system doing" - run it first
```

The reactivation primitive is `dsh --profile headless "<task>"` — answer one task, print the result,
exit. **A session can only be started on a machine that has DSH**; the server drives it over ssh.

### The responder read the wrong store for months

Worth knowing because it is the archetype of a silent failure. The owner's texts ARRIVE — the Twilio webhook
writes them to the **app's** `sms_log` (982 rows, 228 from his iPhone, newest today) — but `sms-responder.py`
read `~/.sms-inbox/inbox.db`, whose newest inbound row was **2026-04-29**. So every tick printed
`0 to decide` and looked like a broken responder, when it was an EMPTY INPUT: it had been looking in the
wrong place since April and nobody noticed, because a silent responder and a bored responder print the same
line.

`mirror-owner-sms.py` (cron `*/5`) now copies inbound rows from the app store into the inbox store, so the
responder sees him. It reads the app DB **read-only**, dedupes on `twilio_sid`, is **insert-only**, and is
**limited to the last 7 days on purpose** — an unbounded first run would have mirrored 27 rows back to
2026-03-23 including test messages, and every one would have become a ledger item.

It is a separate process rather than a change to the responder's worklist, and that was deliberate: the
responder runs LIVE every five minutes with `--send`, so new code there sits directly in the path that texts
a human. With a mirror, the worst case is that no rows appear. **Prefer a separate process over editing the
live send path.**

The other half — the path from a finished shift BACK to his phone — is item #8 in the ledger.

### Start here, always

```bash
/home/zabz/bin/autonomy-status.sh          # or --json for a machine
```

One call, read-only, exit 0 always. It prints releases vs the backstop, failures, spend vs the ceiling,
caps in force, both stores' states, todo by priority, **proofs (settled attempts carrying one)**, in-flight
dispatcher processes, **both heartbeat ages**, per-project todo/running/done, the last releases, an explicit
`PROBLEMS` list, and an `IDLE` line that says WHY nothing is running — and says `healthy` when the reason is
a guard doing its job, so nobody "fixes" a working system. Before it existed, driving this took ~90
throwaway probe scripts per session; each answered one question and was abandoned, and the next session had
to write them all again.

**Its `IDLE: healthy - N row(s) waiting, every one gated by <cap>` line is the single most useful reading in
the system.** Healthy idleness and a stall look identical from every other angle.

### Two rules that decided real incidents

- **An item is a statement about the world at FILING time.** When the measurement moves, the item moves with
  it, or the next shift spends its opening minutes chasing a ghost. (A priority-1 "the authority is 4x
  oversubscribed" item stopped being true within two hours; the load had fallen 16.15 -> 1.69.)
- **A reading that cannot distinguish two different states is not a reading.** Six separate incidents in one
  evening: a doubled cap default (stats said 12, claim enforced 4); a money ceiling reading a measurement 18
  hours stale; 27 rows filed and never consumed; a discovery deadlock (`nothing-todo` -> no discovery ->
  nothing to claim); a ledger lease reaper that did not exist; and `wake.py claim` answering
  `blocked_by: null` on a queue that was FULL and merely gated (it now reports
  `blocked_by: "row-gates"` with a per-reason, per-source count).

## The one rule

> **A flag is raised only by something that knows there IS work. Nothing on a timer may raise one, and
> a session that was woken must not raise one.**

Break it and you get a session factory that burns money doing nothing — which is why the guards below
exist and why `WAKE_SESSION=1` makes `flag` refuse from inside a woken session.

## The flagship pattern: `await`

**Every time you send something and expect something back, register what to do when the answer
arrives.** That single habit is the difference between a reply being a notification and a reply being
work. A promised answer is the one signal that is unambiguously work; almost everything else is a
decision for the owner and belongs in the owner queue.

```bash
# on the authority
python3 ~/bin/wake.py await +18482102477 --name "Yisroel Weinberg" \
  --what "Take the business name and WhatsApp number, publish her page, reply with the URL." \
  --until 2026-10-05
```

When they reply, the responder matches the await, files a flag, and the flag becomes a session that is
told to **do the work AND reply to the person**. (Filing work and leaving a human waiting is a real
failure that happened on 2026-09-18 — the prompt now leads with it.)

## Raising a flag

```bash
# from anywhere (the store and the dispatcher live on the authority, so it must run there)
ssh secratary-ts "python3 ~/bin/wake.py flag \
  --subject 'sms-webhook-lost:2026-09-18' \
  --prompt 'The app answered HTTP 500 to inbound texts today. Fix the write path against the DEPLOYED tree.' \
  --kind sms-loss --source webhook-monitor --priority high"
```

- `--subject` is the DEDUP KEY. Make it stable and specific (`thing:date`), never a random string —
  the same issue must never file twice.
- `flag` **always exits 0**, so a broken flag can never break its caller. Read the printed result:
  `filed` / `deduped` / `suppressed:<reason>` / `capped`.
  `suppressed:*` is ALWAYS a real decision (dedup, cooldown, a cap, the pause file, or being inside a
  woken session) — it is never an error.
  A **broken store reports `error:<Class>: <message>`** on stdout (and `{"ok": false, …}` with
  `--json`). **Treat any `error:` as a failure and say so out loud** — never as quiet. A store that
  reports success while filing nothing is exactly how this system dies looking green.
- `capped` means the row WAS filed (you get an id) but a cap is in force, so it will not be released
  yet. That is not a failure.
- High priority bypasses the night gate. Low priority waits for 13:00–03:00 UTC.

## Seeing what is pending, and what happened

```bash
ssh secratary-ts "python3 ~/bin/wake.py list --json"
ssh secratary-ts "python3 ~/bin/wake.py stats --json"     # counts, today's releases, caps in force
ssh secratary-ts "python3 ~/bin/wake.py awaits"           # who we are waiting on, and for what
ssh secratary-ts "tail -20 ~/.sms-inbox/wake-dispatch.log"
```

The owner digest carries a **WAKE SYSTEM** section that reports liveness FIRST: dispatcher heartbeat
age, flags waiting, released today, who we are waiting on. If it says the dispatcher last ran hours
ago, nothing can revive you and **that is not peace, it is death** — the operation's oldest failure is
reading a live-looking thing as work-happening.

## The project loop — where its work actually lives

`ledger-keepalive` (a source in `run-wake-sources.sh`, every 15 min) files **one flag per project per day
for every project that has a TODO ITEM IN THE LEDGER** — that granularity matters, see below. Each release
is a real shift, headless, on ZABZ-TECH.

**NINE projects are registered as of 2026-09-28**, all named by the owner: `kosher-ai-filter`, `lpt-website`,
`lpt-sync`, `prod-db-sync`, `housekeeping`, `personality-system`, `rental-system`, `chumash`, `cfo`. (An
earlier version of this skill listed three and mentioned `waste-system`, which the owner has DISCLAIMED — do
not act on `waste-system`.) Registry: `/home/zabz/bin/sources/projects.json`.

**Where a shift's work actually comes from, and the deadlock that follows from forgetting it.** A woken
session calls `work.py claim-next` FROM THE LEDGER. If a project has no ledger item, the session gets
`nothing-todo` and stops — so the project is scheduled, woken, and advances nothing. That is what happened to
four of the nine: they had ZERO items, and the work that would have created one was itself the item that did
not exist. `seed-discovery-items.py` (registered in `run-wake-sources.sh`) now files a discovery item for any
enabled project with no items and no real repo, and a shift files its own follow-up items when it finishes.
**If you add a project, give it at least one ledger item or it will sit there being woken for nothing.**

Three things you must know before you judge a project idle:

- **A project's state is NOT in the journal.** The woken shift writes its plan, its evidence and the next
  worker's instructions to `/home/zabz/.wake-projects/<project>.json` on the authority, and the flag's
  outcome line lands in `~/.sms-inbox/wake-dispatch.log`. **Read both before saying a project has
  stalled.** Measured 2026-09-23: a full website shift (wake #26, 1426 s, exit 0) had run that morning
  and fixed three source defects, while the journal showed nothing — which is exactly how a live project
  reads as a dead one, and it produced a wrong answer to the owner.
- **A `new` project flag is queued, not lost.** Caps mean today's project flags may wait behind earlier
  releases. With the 500 backstop the usual reason for a quiet tick is the **per-source hourly cap**;
  `autonomy-status.sh` names it, and its `IDLE: healthy` line is the difference between "gated" and "stuck".
- **The ledger is the durable per-project state, not any JSON file.** `work.py list --project <id>`,
  `work.py show <id>`, and the `attempt` table are where a project's real history lives — including the
  definition of done, what was tried, the PROOF, and what was deliberately LEFT OVER.

```bash
ssh secratary-ts "cat ~/.wake-projects/lpt-website.json"          # the project's real state
ssh secratary-ts "grep -v 'daily cap reached' ~/.sms-inbox/wake-dispatch.log | tail -30"   # what ran
```

The standing failure of this loop is not waking up — it is **integration**. A shift ends with a pushed
branch and a "the next worker must merge this" line, and nothing merges it, so daily progress accumulates
as unmerged branches. When you are woken for a project, the first item of its state file is usually an
unmerged branch, and that IS the work.

## The safety envelope (know what protects you)

Dedup by subject · cooldown per subject · daily release cap · per-source hourly cap · night gate ·
kill-switch file (`~/.sms-inbox/WAKE_PAUSED`) · a lease so a dispatcher that dies cannot strand a row ·
an attempts cap so a failing subject stops forever · **`WAKE_SESSION=1` refuses flags raised from
inside a woken session** · a heartbeat · an absolute ceiling on concurrent dispatch processes.

**Cost IS measured now — this section used to say the opposite, and that was wrong for months.** Do not
repeat it. `wake-cost.py` prices `~/.sms-inbox/wake-cost.jsonl` from the provider's own figures, cron runs
it **every 15 minutes**, and `wake.py stats` reports `spend_today_usd` against a **70 USD/day** ceiling.
Measured per release: **0.036-0.068 USD** (3-5 M tokens, mostly cache-hit input). Measured 2026-09-28: 18
releases for 0.81 USD — against a former normal of 4 releases a day.

The lesson survives the correction: the ceiling spent months comparing against a hardcoded `0.0` (invoice
inert while looking present), and then against a cost file 18 hours stale (reading 0.135 when the true
figure was 0.468). **Verify the measurement is CURRENT before trusting a limiter that reads it.**

The daily release cap is now a **500 backstop**, not 4: the owner said volume is not the constraint —
*"There's no reason to limit how much you could do per day."* Throughput is instead shaped by the per-source
hourly cap (3), a per-project daily cap (3 with a 6 h cooldown), and the process ceiling on the fan-out.

### The ledger's own lease reaper

`~/.sms-inbox/inbox.db` (the wake store) and `~/work/work.db` (the ledger) are **two stores with two
separate lease mechanisms**. The dispatcher reaped the first; **nothing reaped the ledger's** until
2026-09-28, so a shift that died mid-run would leave its item `running` for ever — neither done nor
available, with no symptom except a backlog that quietly stops moving. `work.py reap` now runs in
`run-wake-sources.sh` on the same 15-minute schedule. A reaper that has never freed anything has been RUN,
not TESTED — it was proven with a planted expired lease (`prove-reaper.py`), which also checks that the
recovery is RECORDED so a reaped item does not look untouched.

## When you are the one woken

If you are reading a prompt that begins *"X has just replied to a message we sent them…"*, you are a
headless session that the server started. You have no conversation history. That is expected.
Read the flag's own context, do the work, **reply to the person if a person is waiting**, write the
outcome where it belongs (case file, journal), and finish. Do not raise flags.

## What NOT to do

- Do not raise a flag because something *might* be wrong; raise it because a human would otherwise do
  nothing and a session would actually change the outcome.
- Do not use a flag to ask the owner something. That is the owner queue's job — one question, one
  recommendation. A flag is work, not a question.
- Do not run a wake on a timer to "check". A dispatcher releases; it never invents.
- Do not send anything to a person without reading the case file and the standing style rules first.
  Everything sent from the AI line is signed `- Daniel`.
- Do not treat a quiet queue as health. Check the heartbeat — `autonomy-status.sh` prints both.
- **Do not end a shift with an item you did not do and no reason recorded.** A decline is often correct
  (four items tonight were correctly put back: a real 6-file content conflict that could not be merged on
  the live checkout, a suite that would not run, a merge already integrated). But it must carry the
  MEASUREMENT that justifies it, or the next shift re-derives it. Closed attempts carrying proof is a
  tracked number; keep it at 100%.
- **Do not leave a proof that pollutes the ledger.** `prove-inbound-path.py` inserts a synthetic owner text
  into a throwaway store copy but `work.py` writes PRODUCTION, so three runs filed three duplicate
  `owner asked by text:` items — the duplicate work this system exists to prevent, manufactured by its own
  test. A test that writes to a real store must clean up after itself.
- **Do not re-run a state-changing one-shot to "check state".** Scripts that claim, finish, flag or merge
  belong in the repo with a name that says so, not in `/tmp` where the next session runs them again.
- **Do not raise a cap to get more throughput before reading `autonomy-status`.** A quiet system is usually
  a guard working. Check which gate is in force and whether the volume is already far above the old normal.
- **Do not trust a `0` from a store written by writers.** The ledger's `reap` printed `count: 0` all evening
  and had never freed anything; `pgrep -f` counted the probe that asked it. Plant the condition and watch.
