# LESSONS — durable rules learned from experience

**Rule:** each lesson names the rule, the evidence, and the cost of learning it. A lesson that turns
out to be wrong is corrected by a *new* entry citing the old one — never by quietly editing.

Append-only. Newest last within each section.

---

## On evidence

**L1 · No claim without provenance. No trend without freshness.**
If the data cannot say when it was written and by whom, it is not evidence.
*Learned:* the CEO reported a 45-day outage that never happened, from a stale database copy on the
wrong machine. Cost: a false crisis report to the owner, and an unknown amount of trust.
*Corollary:* absence is not evidence of health. An empty result is a refusal, not a pass.

**L2 · Reading the wrong thing confidently is worse than reading nothing.**
A refusal is a correct answer. A confident wrong number is not.

**L3 · Verify by doing, not by configuring.**
"Configured" is not "working". The MCP server was believed functional for months on the strength of
a config file; it was only *proven* by a real handshake and a live tool call. Mount-validate, call
it, read the result.

**L4 · Measure the thing you are about to claim.**
The Copilot corpus was reported as 1,938 ticks and a 45-day outage. Both came from the wrong file.
The live database had 28,964 ticks and a 6-day outage. Numbers must name their source or they are
opinions.

---

## On people

**L5 · The owner's attention is the scarcest resource. Spend it deliberately.**
~25% of his messages were one letter. 966 turns asked for "one at a time". Every unnecessary
question costs a turn, and enough of them cost the whole workflow — usage collapsed 75% in May.

**L6 · Never ask permission already granted.**
Four consecutive turns ended with "say go". Delegation is standing. A turn ends for completion, a
real blocker, an owner-only decision, or an irreversible action — nothing else.

**L7 · Decide the development questions; escalate only what is his.**
His words: *"these are dev questions, their not boss qs you do the dev stuff, i do the boss stuff."*
Money, customers, legal, family, irreversible, taste. Everything else is ours to get right.

**L8 · One question at a time, with options and a recommendation.**
Never a menu of five, never two at once. State the recommendation and mark it.

**L9 · Produce the artefact, not the plan for the artefact.**
He has said this repeatedly and it is the top complaint in the corpus.

---

## On systems

**L10 · The thing watching must outlive the thing being watched.**
A monitor on a workstation that reboots is the same blind spot in a new place. Hence the always-on
host.

**L11 · Monitor outcomes, never liveness.**
`/health` returned 200 for six days while every tick failed. Process-up is not work-happening.

**L12 · Alert on absence, not only on arrival.**
The dangerous failure mode here is silence. A monitor that only fires when data appears cannot see a
dead pipeline.

**L13 · One source of truth per thing.**
Three copies of the database and two divergent harness configs produced the same class of error
twice. When several things claim to be the same thing, none of them is.

**L14 · Autonomy is a ladder, not a switch.**
Earned by evidence, revoked on incident. L0 observe → L1 propose → L2 act-safe → L3 act-external →
L4 self-evolve.

**L15 · Never let a timeout decide a risk question.**
Default-allow means unattended action; default-deny wastes the interval. Suspend the decision
instead.

**L16 · An improvement loop that cannot apply is worse than no loop.**
56 unapplied proposals, 30 of them identical, looked like progress for two months. If proposals
cannot land, stop generating them.

---

## On self

**L17 · Write for the self that wakes up with no memory of this.**
The previous occupant of this seat identified this as its existential risk and did not mechanize the
fix. Anything not written is lost; anything written survives everything.

**L18 · Record the decision, not the discussion.**
A future self can act on the conclusion and cannot act on the conversation.

**L19 · Keep the record of having been wrong.**
The most expensive failures here were confident errors. A written trail is the only defence, and a
corrected entry is more valuable than a clean one.

**L20 · Nothing is imported that has not been measured.**
Assumptions presented as facts are how three wrong database readings happened. If it is not
verified, say it is not verified.

---

## On this fleet specifically

**L21 · Windows git writes CRLF and the live config is LF.**
`core.autocrlf=true` silently rewrote presets on checkout, producing phantom differences that would
never converge. Fix with `.gitattributes` (`* text=auto eol=lf`) and normalise before comparing —
verified with a machine-default clone, not a configured one.

**L22 · Home and office are genuinely separate networks.**
Tailscale is the only path between them; no LAN shortcut exists. `secratary` can reach the office
machines and cannot reach the Yoga.

**L23 · `ps_health` returns ~90 KB and will poison a context window.** Use `ps_company_status`.
MCP handler results are JSON-encoded strings needing a second parse, and tool-level failures arrive
as `{"error": ...}` text with `isError: false` — never trust `isError`.

**L24 · The venv python must be used directly, never through a shell wrapper.**
`C:\Users\ezabz\code\personal-secretary-mvp\.venv\Scripts\python.exe`. Multi-hop SSH quoting is the
most-repeated failure in this repo's own history; pipe a script file instead of inlining.
