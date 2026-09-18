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
CAPTURE   sms-inbox.py      every inbound/outbound text, reconciled from Twilio every 5 min
ROUTE     sms-responder.py  answer it (allow=auto), or raise ONE owner-decision row
FLAG      wake.py           anything that KNOWS there is work raises a flag
WAKE      wake-dispatch.sh  claims one flag -> ssh -> ZABZ-TECH -> dsh --profile headless -> result back
```

The reactivation primitive is `dsh --profile headless "<task>"` — answer one task, print the result,
exit. **A session can only be started on a machine that has DSH**; the server drives it over ssh.

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
  `filed` / `deduped` / `suppressed:<reason>` / `capped`. **`suppressed:error` means it did NOT file** —
  treat it as a failure and say so, never as quiet.
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

## The safety envelope (know what protects you)

Dedup by subject · cooldown per subject · daily release cap · per-source hourly cap · night gate ·
kill-switch file (`~/.sms-inbox/WAKE_PAUSED`) · a lease so a dispatcher that dies cannot strand a row ·
an attempts cap so a failing subject stops forever · **`WAKE_SESSION=1` refuses flags raised from
inside a woken session** · a heartbeat.

**Cost is unmeasured.** `dsh --profile headless` reports no usage or spend, so the dollar cap is inert
and the **release count** is what actually protects the machine. Never quote a per-release cost as if
it were known; say it is unmeasured.

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
- Do not treat a quiet queue as health. Check the heartbeat.
