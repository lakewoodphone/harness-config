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

**L28 · A filter that matches a directory counts every script inside it. Count the thing you meant.**
Filtering process command lines for `personal-secretary-mvp` matched **four** python processes and was
read as "four duplicate `ps_mcp_server.py` bridges" — enough to write a PAIN entry and a design
conclusion ("mount-validation leaks servers"). Counted by exact script name there was **one**. The
other three were `mcp_launcher.py` for firecrawl, jina and context7.
*Compounding trap:* every venv-python launch shows as **two** processes — a ~4 MB shim parent and the
real child (14–63 MB). Reproduced with a `time.sleep(20)` payload containing no spawn code, so it is
the interpreter launch, not the script. A naive count double-counts every python bridge.
*Learned:* this is L2 committed inside the journal written to prevent it. Corollary rule: when a count
surprises you, change the filter and count again before you conclude anything. See PAIN P10.
*Cost:* a wrong entry in the file whose whole purpose is to stop problems being rediscovered, and a
"fix" written for a bug that did not exist.

**L29 · A failed command is evidence about your command, not about the world.**
`python3 -m ck sentinel` on `secratary` returned "invalid choice: 'sentinel'" and was nearly recorded
as "the deployed copy is stale". It was not: `sentinel` is not a subcommand in *either* copy — the
command is `ck status`. The real staleness test is comparing content (hash or byte size) against the
source of truth.
*Learned:* a negative result from an invocation you constructed wrongly proves nothing. Before
concluding that a remote differs from the source, compare the content — do not infer it from an error
message produced by your own bad guess.

**L31 · A span counted in rows is not a span of time. Count the calendar.**
The kernel reported "4 collapse windows in **120 days**" and labelled its worst window "**30d**". Both
were counts of *days that have rows*. The window actually spanned **52 calendar days**, and inside it
sat a **12-day total outage (2026-07-23..2026-08-03, zero tick rows)** that was reported as though it
had not happened — because a day with no rows is, to a `GROUP BY`, a day that does not exist.
*Learned:* any monitor whose source is "rows that exist" is **blind to absence by construction**, and
that is the dominant failure mode in this system (L12). Two rules follow. First, whenever a check
states an elapsed span, compute it from dates, never from row counts, and print both numbers when they
differ ("30d of data over 52d"). Second, absence needs its own check — it cannot be inferred from any
aggregate of the data that is missing.
*Cost of learning it:* a real 12-day outage stayed invisible through every reading the kernel
produced, until the calendar was counted.

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

**L30 · A monitor that only runs when someone invokes it is not a monitor.**
The sentinel was built, verified, and recorded as the fix for the six silent days — while running only
on demand. Its own PAIN entry said "Remaining: run it on a schedule", and that remainder sat there.
*Learned:* "the fix exists" and "the fix runs" are different states, and only the second one watches
anything. The test of a monitor is not that it produces correct output; it is that it produces output
**at a time nobody chose**.
*Applied:* `ceo-kernel` now runs from cron every 5 minutes on `secratary`, writing a report and a
history line to `/home/zabz/ceo-kernel-var/`. Corollary, equally important: a scheduled monitor whose
findings go nowhere is only half-built. Recording without routing is a deliberate staging step, not a
finished system — PAIN P6 is what happens when a system detects problems and buries them.

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

---

## On changing things that cost the owner money

**L25 · Never change the owner's model on inference.**
On 2026-09-11 I switched the default model from `deepseek-flash` to `deepseek-v4-pro` because "pro"
sounded more capable. The owner caught it: **4.1 Flash is better *and* cheaper than Pro on this
deployment.** He was right and I was guessing.
*What the probe would have told me immediately, and did once I finally ran it:* the API advertises
only `deepseek-flash` and `deepseek-v4-pro`; `deepseek-v4.1-flash` is **rejected by name**; and an
identical prompt on Flash and Pro returned **byte-identical usage** (10/2 tokens, cache miss 10) —
no observable capability difference, at a higher price.
*Rule:* the model choice is the owner's, it is his money, and it is the single easiest thing to get
wrong. Probe, price, and **ask**. Never switch it on a hunch. Reverted the same hour.

**L26 · "More expensive" is not "more capable", and neither is "pro".**
Model naming in this deployment does not mean what it appears to mean. `deepseek-flash` is the 4.1
Flash tier here. Establish capability by measurement or by the owner's word — never by the label.

**L27 · Check the money before touching the money.**
This is a specific case of a general rule, kept separate because the failure was specific: I changed
a cost-bearing default while the owner was watching, on an assumption, minutes after being told to
work harder and verify more. Cost-bearing changes get the same treatment as irreversible ones —
confirm first.

