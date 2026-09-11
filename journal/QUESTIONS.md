# QUESTIONS — asked of the owner, not yet answered

**Rule:** when you ask the owner something, it goes here with the date. When he answers, the answer
is recorded in `DECISIONS.md` and the line here is marked answered. This file exists so the same
question is never asked twice — the previous system accumulated **313 pending questions, none created
after 19 July, the oldest 131 days old**, because nothing tracked them.

Check this file before asking anything. If the question is already here unanswered, the correct move
is usually to decide it yourself (see the persona: development questions are yours) or to escalate it
loudly rather than re-ask quietly.

| Asked | Question | Status |
|---|---|---|
| 2026-09-11 | The HA security system is blind: two door contacts are offline (since 2026-09-11 01:48) and every camera snapshot fails. Attempt a remote recovery now (reload Zigbee, retry the devices), or wait until someone is at the office on Sunday? | **open** — recommendation: remote recovery attempt now, because the failure is device-level and a reload is reversible; physical re-pair on Sunday if it does not take |
| 2026-09-11 | Phone access: Tailscale-only, or a public login-gated endpoint as well? | **open** — recommendation given (Tailscale); no answer needed until the console is reachable |
| 2026-09-11 | At the office on `ZABZ-TECH`, is it one long session per day or many short ones? | **open** — shapes how continuity should behave |
| 2026-09-11 | Why did Copilot usage collapse after April 2026 (May −75%, June −78%, July ≈0)? | **open** — never answered; the single most informative unknown about what he actually needs |
| 2026-09-11 | The company recorded **zero ticks for twelve consecutive days, 2026-07-23 .. 2026-08-03**. Was that a deliberate shutdown, or an outage nobody noticed? | **open** — asked in session; the kernel now flags this gap on every run, and if it was intentional the kernel needs a *maintenance window* concept instead of a permanent alarm |

**Answered and recorded elsewhere:**
- 2026-09-11 · Who the CEO is and what it owns → `DECISIONS.md` D1
- 2026-09-11 · Where the CEO sits relative to the secretary → D2
- 2026-09-11 · Sync architecture → D4
- 2026-09-11 · Deployment placement → D6
- 2026-09-11 · Harness source of truth → D7
