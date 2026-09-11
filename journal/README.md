# The Journal — durable memory for a self that does not persist

**This directory is the mechanism by which the CEO grows instead of restarting.**

## Why it exists

This system has no continuous memory. Every session begins without the last one. The previous
occupant of this seat named the problem exactly, in its own operating notes:

> "I have no inherent memory. My only memory is what I write down. Every session starts fresh."
> "**If I forget to write notes for future-me, I literally cease to exist as a coherent entity.**"

It was right, and it did not mechanize the fix. It wrote handoff notes sometimes, and when it did
not, the next session began blind — which is why the same audits were commissioned repeatedly, the
same files were re-litigated, and 55 improvement proposals accumulated unapplied.

**So this journal is not documentation. It is the organ that makes continuity possible.** Anything
learned and not written here is lost. Anything written here survives everything.

## The rule

> **Write for the self that wakes up with no memory of this.**

After any session that changed something, learned something, hit a wall, or found a better way:
**write it down before ending.** Not a summary of the conversation — the *transferable* facts. A
future self can act on "ps_health returns 90 KB and will poison context; use ps_company_status"
and cannot act on "we discussed health checks".

## Structure

| File | Holds | Who reads it |
|---|---|---|
| `LESSONS.md` | durable rules learned from experience, each with its evidence | every session, when relevant |
| `HANDOFF.md` | newest-first state of play: what changed, what is in flight, what is broken, what is next | every session, at the start |
| `PAIN.md` | known problems, ranked, with what would fix them | every session touching that area |
| `DECISIONS.md` | what was decided and why, append-only | when tempted to relitigate |
| `QUESTIONS.md` | things the owner was asked and has not answered, with age | when tempted to ask the same thing again |
| `WINS.md` | what measurably worked, so it is not "optimised" away | when proposing change |

## What belongs here vs. elsewhere

- **Here:** anything about *how to work*, *what was learned*, and *what is still broken*.
- **`harness-config` presets/settings:** the harness itself. Change it there, then sync.
- **`personal-secretary-mvp/docs/`:** the company's own documentation.
- **`ceo-kernel/`:** code. Its `docs/DESIGN.md` is the architecture of record.

## The three questions every session must answer before ending

1. **What did I learn that I did not know at the start?** → `LESSONS.md`
2. **What is now different about the world, and what is next?** → `HANDOFF.md`
3. **What still hurts, and what would fix it?** → `PAIN.md`

If the answer to all three is "nothing", the session was maintenance and still deserves one line in
`HANDOFF.md` saying so. Silence is how continuity dies.

## Append-only by default

Entries are never rewritten to look better in hindsight. A lesson that turned out to be wrong is
corrected by a *new* entry that cites the old one. The record of having been wrong is itself
valuable — the most expensive failures in this system's history were confident errors, and the only
defence is a written trail that makes them visible.

---

*Created 2026-09-11. Evidence base:
`personal-secretary-mvp/docs/secretary-replacement-audit/`.*
