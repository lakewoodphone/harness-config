# SIDE-CARS - what this seat added, and what must not be extended

Written 2026-09-29 03:26Z because the owner said, 2026-09-29:

> "you need over time to get better at unifying and making everything a holistic organized system, so
> when one thing gets improved all subsystems and parts now have a better system instead of dsh, ai
> company, secretary server, texting system and more all separate and building their own tools and
> reinventing the wheel"

## The rule this file exists to enforce

Before adding a script that talks to the model, sends a text, writes the owner queue, or reports
health: **find the thing that already does it and call that.** If it genuinely cannot be called, add
it to THAT thing - not beside it - so the next improvement reaches every caller.

## What the system already owns, and must not be reimplemented

| primitive | the owner of it | do not add |
|---|---|---|
| model choice | `app/services/ai_gateway.py` + `bin/textdecide.py` `PREFERRED` aliases, resolved
| | from `GET /v1/models` at runtime; `.env MODEL_TIER1/2/3=deepseek-v4-flash` | never a literal id |
| text transport | `bin/textsend.py` (`check`/`send`/`notify`/`history`) | no second Twilio client |
| owner decisions | `bin/owner-queue.py` (`add/next/list/answer/defer/resolve`) | no direct SQL on
| | `owner_decision_queue` | |
| live conversation | `bin/sms-responder.py` + `bin/textdecide.py` (the model decides) | no reply
| | | heuristics with thresholds |
| the AI server | `personal-secretary-mvp` on 127.0.0.1:8002 - 618 routes, 199 services, the same
| | gateway, the same agents | no parallel brain |
| health | `bin/autonomy-status.sh` for the wake system, `GET /health` for the app | no new reader |

## Kept in place (libraries - unify AROUND these)

- `autonomy-status.sh` - ONE status reading; candidate to replace the other status scripts
- `check-text-status.py` - the missing instrument: ask the provider about a sid
- `mirror-owner-sms.py` - bridges app sms_log -> inbox; candidate to fold into sms-inbox.py
- `promote-owner-texts.py` - DUPLICATES the responder's own priority-on-filing
- `reconcile-sent-status.py` - keeps sent status truthful; belongs IN textsend, not beside it
- `shift-report.py` - the gated path from a finished shift to the owner

## Moved to `_legacy-sidecars/` (one-shot patches and test harnesses)

These did their job exactly once. They are kept for the record and must not be run again: a one-shot
that changes state must never be re-runnable, which is a lesson already paid for once this session.

- `wire-queue-replies.py` - one-shot: added the queue-reply call

## Already absent

- `add-sms-plan-7-8.py`
- `apply-step7.py`
- `close-answered-questions.py`
- `correct-item1-premise.py`
- `file-owner-texts-first.py`
- `file-row89-tooling-merge.py`
- `fix-patcher-escaping.py`
- `fix-reply-stamp.py`
- `give-shifts-a-time-budget.py`
- `guard-repeat-asks.py`
- `note-bridge-proven.py`
- `note-sms-state-on-7-8.py`
- `prioritize-sms-7-8.py`
- `prove-inbound-path.py`
- `prove-owner-sms-bridge.sh`
- `prove-reaper.py`
- `prove-reply-path.py`
- `record-safe-path-for-30.py`
- `talk-to-him-with-the-brain.py`
- `unblock-channels.py`

## The unification work this records, not yet done

1. `reconcile-sent-status.py` and `check-text-status.py` belong INSIDE `textsend.py`, so every sender
   gets truthful status. Until then, two callers and one truth is the best available.
2. `mirror-owner-sms.py` should be a source inside `sms-inbox.py`, not a separate cron entry.
3. `autonomy-status.sh` should absorb the other status readers (box-health-check.sh, the two above),
   so there is one reading of the system rather than four.
4. The responder should reach the AI server's own brain and tools rather than loading a private copy
   of the decider - that is the real unification, and it is a design change, not a patch.
5. Sixteen dot-directories under /home/zabz each hold private state and a private tool. They should
   report through one status surface.

