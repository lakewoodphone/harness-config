# The shop's security system — audit, design and decisions (2026-10-26)

Read in this order. Everything below was written in one session on ZABZ-YOGA, with the live system read
read-only throughout; nothing on the building was changed.

> **READ THIS FIRST (2026-10-27).** The owner has answered Q1, and the answer inverts this folder's priority:
> what he wants is **the record** — every person who came, a picture or video, when they came and when they
> left — and that ranks above the burglary alarm, which he wants kept and does not fear. The consequence for
> the build is `55-OBSERVATION-FIRST.md`; the re-ranked order is Part 5 of `SECURITY-DISCUSSION.md`. Everything
> below was written alarm-first and is **still correct as engineering** — only its ordering is superseded.

| # | File | What it answers |
|---|---|---|
| 1 | `55-OBSERVATION-FIRST.md` | **Start here now.** What "every person, pictured, timed, kept" requires, the six measured blockers, the acceptance tests O1–O4, and the build order they force |
| 2 | `05-LIVE-FINDINGS.md` | What is broken on the running system right now, measured: the alarm disarms for anyone who walks in (L1), no page has ever been sent (L5), and the company's own event path has never carried one event (L6) |
| 3 | `10-ARCHITECTURE.md` | The design: reflex in Home Assistant, mind in the company, memory in the database, a constitution in code. The seam that lets an agent manage security without being able to silence it |
| 4 | `25-MIND-CONTRACT.md` | What the agent is given, what it must return, when it is forbidden to think, and the fifteen-episode test that judges it |
| 5 | `20-OPERATIONS.md` | The building's state machine, the escalation ladder by hour and evidence, AVS-01 levels, the autonomy table, the real cost arithmetic, the four KPIs |
| 6 | `30-IDENTITY.md` | Who the five subjects are, what each credential actually proves, and why presence is never identity |
| 7 | `40-SAFETY.md` | Fourteen attacks, the fail-safe ladder, the code-level allow-list, and the two things the industry refuses |
| 8 | `50-BUILD-PLAN.md` | Eight stages, each with an acceptance test, in the order that removes risk first. The first stage is fifteen minutes |
| 9 | `OWNER-DECISIONS.md` | Eleven decisions that are the owner's, each with the evidence and one recommendation |
| 10 | `SECURITY-DISCUSSION.md` | **The document to work through with him**: 10 questions only he can answer (Q1 now answered), 22 decisions, 8 clarifications, and the re-ranked order to take them in |
| 11 | `60-OPERATOR-CARD.md` | What to do **tonight**, before any of this is built — how to check whether the building is armed, how to stop the siren, and the three things not to do |
| 12 | `45-FINDING-COVERAGE.md` | The check that nothing was dropped: where each of the 84 prior findings ended up, and the seven that this design explicitly does not fix |
| 13 | `OPEN-THREAD-nonblocking-evidence.md` | The one piece of unfinished engineering, with the measured answer and a safe procedure |
| 14 | `00-WORKLOG.md` | The rounds, in order, with what each produced |

**Applied to the building, with the diffs and the evidence**

| File | What it proposes |
|---|---|
| `PROPOSAL-stage1-credential-and-ghost.md` | **applied 22:24Z** — the four calls that made the alarm disarm on a credential instead of a ghost |
| `PROPOSAL-stage2-cp01.md` | **applied** — owned entry delay, bounded siren, AVS level; the delay was later superseded by a 30 s timer on the flag |
| `schema/01-security-record.sql` | **applied** — the nine tables, idempotent, the file is the source of truth rather than the database |
| `corpus/replay-corpus-v1.json` | the twelve documented episodes plus one synthetic intrusion, built from the prior session's ledger |

**Supporting material**

| Folder | What it is |
|---|---|
| `live/` | The **deployed** HA config, pulled byte-exact and sha256-matched against the host: `phoenix_security`, `phoenix_intrusion_evidence`, `presence_architecture`, `access_control`, `phoenix_core`, `apartment_deadbolt_codes`. The repo copy is **not** what runs |
| `research/` | Five lanes, each with evidence per claim: **A** transport/runtime, **B** vision and costs, **C** the company's agent runtime, **D** the learning loop, **E** external practice and adversarial |
| `from-zabz-tech/` | The prior session's work, preserved: the 84-finding audit (`S1`–`S84`), the 20-round design, the handoff, and twelve workstream reports |

**The one paragraph, if you read nothing else.** The current system is not badly tuned, it is aimed at the
wrong thing: it arms and disarms on the same presence signal, so a person walking in turns it off; it has
never delivered a page; and the platform that is supposed to add judgement cannot see the event because its
event path has never run. The redesign keeps a small, deterministic reflex in Home Assistant — a door with
no credential alarms, and nothing a model says can remove that — and moves everything that requires context,
memory or language into the company, where it can be wrong without being dangerous.
