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

**L32 · A process survey matches its own command line — twice over. (Extends L28, which was not enough.)**
After L28 I re-ran the MCP count and got "8 DSH servers" and "3× every bridge". Both were false again,
by the same mechanism in a new place: the survey's own command line contains the strings it searches
for, **and** that text is copied into the `dsh-subprocess-local/runner.js` wrapper that runs the
survey — so the query matches itself through two different processes. Filtering by *name* alone does
not save you; the wrapper is a `node.exe` too.
*Correct method:* filter on process **Name** *and* on a pattern that can only appear in the real
target (here: a command line whose final argument is `dsh/lib/bin.js`, not one that merely mentions
it), and state the number you expect before you count.
*Learned:* L28 said "count the thing you meant". This one adds the reason it recurs: **a survey is
part of the system it surveys.** Expect to match yourself, and design the filter to exclude you
explicitly. Three false counts on one trivial question is the cost of not doing that.

**L33 · In a shared working tree, stage explicit paths — never `git add -A`.**
Eight DSH sessions were live in one project directory at once. Another session wrote a legitimate file
into `harness-config/journal/reference/` while this session was editing the journal, and
`git add -A` **committed it under someone else's commit message**, unmentioned.
*Learned:* `git add -A` asserts "everything in this tree is mine and belongs in this commit", which is
false the moment a second agent can write there. Stage the paths you actually changed. It costs one
line and it preserves the difference between what you did and what merely happened next to you.
*Cost of learning it:* an unattributed file in a commit, and the diff no longer explains itself.

**L39 · To date an outage, use append-only evidence. A file that is overwritten has no history.**
Investigating the 2026-07-22 → 08-04 silence, the first instinct was `find -newermt <window>` to see
whether the host had been alive. **That test is unusable for the question asked**: every file that is
continuously rewritten — the cron health file, the heartbeat, the API log truncated on each start —
carries today's mtime and hides its own past. A host that is *dead* and a host that is *writing to
files we overwrite* look identical.
*What actually settled it:* (1) `find` counts **per day** — not "did anything write", but "which days
had writes at all", which showed every one of the twelve days had activity; (2) `logrotate`'s rotated
files, whose mtimes are frozen at rotation time, proving cron ran on Jul 23; (3) the database itself,
whose append-only tables date the last tick and the first one after to the second.
*Learned:* before asking a question of the filesystem, ask which files *can* answer it. Frozen and
append-only artefacts (rotated logs, database rows, git objects) record history; live-state files
record only the present. Reaching for mtime first cost the most time in this investigation.

**L40 · An outage can be invisible in the data that describes work, because absence has no rows.**
Closely related to L31 and kept separate because it is the *detection* half rather than the *counting*
half: the 13-day silence was absent from `tick_telemetry` not as a gap but as nothing at all — no rows,
no error, no interruption to see. `GROUP BY` over existing rows reported a clean series. The company
was dead for two weeks and every reading of the database was technically correct.
*Learned:* the question "what should be here and isn't?" cannot be asked of a table. It has to be asked
of a calendar — and only a check that expects absence will ask it. See L31 and `telemetry_gaps`.

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

**L34 · A job can succeed, log success, and write into a file nobody reads. Ask where the write landed.**
The daily Telnyx snapshot on the Waze MDM host ran at 04:30, exited 0, and logged
`Persisted 2 per-SIM usage rows` — every single day, for at least a week. It was writing to
`/data/fleet.db`, a **SQLite** file, while the `fleet_api` it exists to feed reads **PostgreSQL**.
Both `fleet_telnyx_*` tables in Postgres were at **0 rows** and always had been.
*Two mechanisms, both worth naming:* (1) `_connect_db()` preferred SQLite unconditionally — a
migration left the old path in the code as the default; (2) the per-SIM insert named a `customer`
column that Postgres never received (`CREATE TABLE IF NOT EXISTS` cannot alter an existing table), and
that failure was caught by a bare `log.warning` inside a `try` — so the ledger row landed, the usage
rows silently did not, and the log still said success.
*Learned:* for any pipeline crossing a storage boundary, "did it run" is the wrong question and "did
it exit 0" is a worse one. The only question is **"which store did the write reach, and can I read the
row back from the store a consumer actually queries?"** Read the row back. A `try/except` around a
write that only logs is a decision to lie about failure. This is L1/L2 — provenance and refusals —
arriving through a cron job instead of a database read.
*Cost:* vendor billing history for a launched product, including a period where the Telnyx balance ran
**negative (−$9.61)**, existed nowhere the business could see it. Recovered by migration the same day
(12 usage + 18 ledger rows, 2026-09-06 → 09-11); the freshness assertion that now guards it would have
caught this on day one.

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

---

## On reading other people's systems

**L35 · "Loaded" is not "working", and the entity state is not the failure surface.**
Home Assistant reported the Dahua camera integration at config-entry state **`loaded`** while **100%**
of its snapshot calls failed (365 errors in one log span), and reported a `zha` entry `not_loaded`
for a dongle that has carried nothing for months. Neither fact is visible in the entity state list.
The surfaces that told the truth were the **config-entry state** (integration health), the **error
log** (functional failure) and the **device registry** (which integration actually owns a device).
*Rule:* for a system you did not build, collect at least four surfaces before believing any of them —
declared config, registry ownership, live state, and the log — and treat their agreement as the claim,
not each one alone.
*Cost of learning it:* the first draft of the `ha-config` live audit called the security system
"partially degraded" when it is **blind on its primary trigger and cannot produce evidence at all**.

**L36 · A refusal must name the thing that was refused.**
On the first end-to-end run of the new collector, `/api/error_log` returned plain text while the shared
REST helper assumed JSON. The tool refused to report and said exactly why —
`expected JSON … got non-JSON … first 120 bytes: '…'`. That refusal found a real bug in its own tool in
one run, instead of producing an empty log section that would have read as "no errors".
*Rule:* a refusal that omits the failing call and the raw leading bytes is half a refusal. The primitive
that says "I cannot read this" is worth more than the one that says "0".

**L37 · Read the neighbouring evidence before naming a root cause.**
Three Home Assistant door sensors looked like a dead Zigbee coordinator. Other devices on the same mesh
were reporting live data at that moment, and the bridge's `connection_state` was `on`, so the truthful
reading was "three devices failed to rejoin at boot" — a different diagnosis with a different fix.
*Rule:* before naming a cause, name one measurement that would come out **differently** if that cause
were true, and go take it.

**L38 · Read the log span's clock before trusting a correlation.**
The HA error log's timestamps are host-local and its host clock reads exactly 4 hours behind the
company's UTC hosts (a `12:49` entry is the same event as `16:49Z`). An "is this recent?" judgement
made without noticing the offset is wrong by four hours — enough to invent or miss an incident.
*Rule:* state which clock a timestamp came from before comparing it to anything.


---

## On extending a system you did not write

**L39 · Read the extension seam before deciding whether a change is a patch or a plugin.**
"Add cost to the chat footer" looked like it needed a patched bundled file, because the footer's
numbers are rendered inside `dsh-client-ui-chat`. Reading the seam showed the opposite: `StatsPills`
is one cell in the list Slot `conversation.composer.dock`, declared with `replaceRisk: "none"`, so a
fresh `id` lands beside it and replaces nothing. The same question applied to the per-turn figures
resolved to `conversation.chat.turnTail` (a chain Slot) and to the fact that the session-level
`tokenUsage` projection carries **no** provider or model — so a footer price is inherently an
assumption, while the log is exact.
*Cost of learning it:* none, because the seam was found first. The cost was one recon pass, paid
knowingly.
*Rule:* before editing a shipped artifact, spend the time to find out whether the thing is already a
plug-in point. A patch to `node_modules` is reverted by the next install, cannot be reviewed, and
silently becomes a lie about what the system does.

**L40 · A generated file must be generated from the tested file, or the tests are theatre.**
The plugin's host half is one module — a Cordis plugin is a single module — while the rate card, the
log reader and the command each deserve to be readable and testable apart. Concatenating them in a
build script, and running the *sources* through the test suite, keeps "tested" and "shipped" the same
code. `scripts/build.mjs --check` fails the build when `lib/` drifts from `src/`.
*Failure this caught immediately:* the flattener's `stripImports` used `^import` without the `m`
flag, so a multi-line `import { a, b, c } from '...'` left its tail behind and the generated module
redeclared `PRICING` and `join`. The build "succeeded"; the import failed. A generator that is not
itself checked produces a file that looks right and does not run.

**L41 · "The bundle is on disk" is not "the loader can use it".**
Two separate facts had to be established for the browser half, and neither was visible from the file
existing: the client bundle must be a **plain script** calling
`window.__ModuleLoader__.load({ id, factory })` — an ES module is loaded and silently contributes
nothing — and its registration `id` must equal the **package name**. `test/client-smoke.mjs`
reproduces the loader's contract with a fake `window.__ModuleLoader__` and a stub React, which is what
turned an unverifiable claim into a check.

**L42 · Quote the number, or the region is unpriced.**
The DeepSeek pricing card has exactly three line items and no cache-write row. The tempting move is to
price `cacheWriteTokens` at the miss rate so the column is never blank. That invents a charge the
provider does not make and can double-count tokens the harness also reports as uncached input.
Unpriced is a real answer: the surfaces say "unpriced" and the rate card says which routes have no
published price, rather than filling the gap with a neighbouring model's rate.

**L43 · On a time-of-day rate card, a timestamp is part of the price.**
`deepseek-official` bills 01:00-04:00 and 06:00-10:00 UTC Mon-Fri at exactly 2x off-peak. One constant
would be wrong roughly half the time, so the cost of an attempt is a function of the attempt's own
clock — which meant the durable log, not the projection, had to become the pricing input: the
projection carries four integers and no time and no route.

**L44 · Never put a secret in an exception message.**
Reading the credential store, I failed to resolve a ref and threw ``record <id> has no secret`` — where
`<id>` *was the API key*. It went into the transcript before I noticed. A thrown error is the single
easiest place for a secret to escape, because it is written to be read.
*Rule:* credential-handling code may print lengths and booleans and nothing else; the failure path is
part of the code that has to be designed, not the afterthought.

---

## On reading other people's systems (Home Assistant, 2026-09-11)

**L45 · Count the artefacts, not the complaints.**
The first version of the Home Assistant audit declared the camera evidence path "fails on every
trigger" because the log held 365 snapshot errors. It does not: `/config/www/snapshots` held **3034
JPEGs**, written continuously — 146 on 08-31, 98 on 09-10, **52 that same day**, including a 319 KB
control-room still 20 minutes before I wrote the claim. The errors were real; the conclusion was wrong.
*Mechanism:* a script failing in a retry loop collapses into one loud signature, and the loud signature
drowns out the quiet successes. The log lists what is *complaining*; the output lists what is *working*.
*Rule:* for any "is this pipeline working?" question, inventory the artefacts first and read the log
second, and report both counts together — the pair is the finding, and either alone is a misreading
waiting to happen.
*Cost:* I told the owner his security system could not produce evidence at all. Corrected within the
hour, in the document itself, with the correction left visible rather than the claim quietly edited.

**L46 · A port mismatch reads exactly like a dead machine.**
`ha-config`'s scripts default to SSH port 22. The Home Assistant host's SSH add-on listens on **2222**,
and tcp/22 refuses. So `check.ps1`, `deploy.ps1`, `backup.ps1` and the inventory scripts had *never*
run — not because the host was down but because they knocked on the wrong door — and "connection
refused" reads as an outage to anyone who takes it at face value. I then made the same mistake in
reverse: concluding "SSH is closed, so the toolchain is blocked" and writing it into a delivered audit
before probing a handful of neighbouring ports.
*Rule:* before declaring a host unreachable, probe the neighbouring ports and read the banner. Four
`/dev/tcp` checks take ten seconds. This is L37 applied to ports instead of devices.
*Cost:* a wrong section in a delivered document, and a wrong question to the owner — the question he
answered with "you are in charge, you make the decisions", which is not the answer a good question
should have produced.
**L47 · A script that has never run against its real target is not a script.**
`scripts/verify_on_device_ml.ps1` was committed on 2026-09-10 and recorded in that day's handoff as
verified: "with no device attached it exits 1 with a clear 'No device/emulator attached' message (no
crash, no false pass)." It printed that message because `Invoke-Adb` declares `-AdbArgs` and all **16**
call sites passed `-Args` — in a non-advanced PowerShell function an unknown parameter name is silently
swallowed into `$args` and the declared parameter stays empty, so `adb` ran with **no arguments**,
printed its help text, and the script matched none of it. Five contract tests, a model-spec drift check
and a CI job all passed the whole time, because they read the script's *text* and never its behaviour.
*Rule:* "verified" means an observation from the real target — a device, a server, a live call. An exit
code is not an observation when the command it wrapped never ran. When the only case a script has ever
been run in is its failure path, the failure path is the only thing that was tested.
*Cost:* a day of believing a harness that could not do the one thing it existed for. `LESSONS` L41 is
this same error one layer down.

**L48 · `catch (Exception)` does not catch `Error`, and that is how a `compileOnly` dependency crashes an app.**
The GPU delegate in the Kosher filter is `compileOnly`, so it is absent at runtime. Constructing it
throws `NoClassDefFoundError` — an `Error`, not an `Exception` — so `catch (e: Exception)` around it
caught nothing, the error escaped the model loader, escaped the cascade, and killed the host activity on
the main thread the first time a user shared an image. The build had been kept green by adding R8
`-dontwarn` for exactly that class, which is how the problem stayed invisible: the suppression that made
it compile removed the signal that it could not run.
*Rule:* any code path that touches an optional or `compileOnly` dependency catches `Throwable` and
degrades explicitly (here: fall back to CPU; and a load failure reads as "model unavailable", never as
a throw into a UI thread). A `-dontwarn` is a decision to run without the class, so it belongs beside a
runtime guard, not instead of one.

**L49 · A test that passes before and after the fix has no teeth — check it against the broken revision.**
I wrote `MlCascadeErrorResilienceTest` to lock the crash fix, reverted the fix, re-ran it: still green.
Robolectric never reproduces the device-only linkage error, so the test locks "a load failure reads as
unavailable" and *not* the bug it was named for — which I recorded in the code comment and the backlog
rather than claiming coverage I do not have. The PowerShell regression test in the same session *was*
checked against the pre-fix file (`git show HEAD:scripts/verify_on_device_ml.ps1`, 32 problems found,
verdict "test has teeth"), which is why that one can be trusted.
*Rule:* a new test is unproven until it has been seen to fail. Two cheap ways: revert the fix, or run
the same assertion against the old revision from git. Also: when the only reproduction needs real
hardware, say so and let the on-device run be the proof instead of dressing a unit test up as it.

**L50 · Never let a long job stream its progress UI into the conversation.**
`sdkmanager` writes a ~200-line progress bar. Captured into a background job's output it consumed most of
a context window and told me nothing a `tail` would not have. Same for any noisy installer or build.
*Rule:* redirect long-running commands to a log file and read the tail; if the tool has a quiet flag, use
it. This is PAIN P7 applied pre-emptively instead of after the loss.

**L34 · A log file that the child process owns cannot be cleared by the parent.**
Symptom: `dshw up` reported "no URL within 180s" while the server was demonstrably up and its log held
the URL line. Cause: the parent deleted `<port>.log` and then read appends at an offset, but the server
had inherited the handle from the launching child, recreated the file, and the parent's offset no longer
described what it was reading. Fix: one log file **per launch** (`<port>-<stamp>.log`), created by the
parent, never deleted; a stable `<port>.log` is a copy. *Lesson:* when two processes touch one file,
give each launch its own file rather than negotiating offsets.

**L35 · Readiness needs three conditions, and each one alone has produced a false positive here.**
A stale log line says "up" for a dead server; a bound port says "up" for a half-built tree; a live pid
says "up" for a server that never finished booting. `dshw` now requires an alive process **and** a
listening port **and** a URL line appended since this launch.

---

## On verifying an answer rather than a pipeline

**L51 · A successful tool call is not a correct answer. Verify the claim, not the plumbing.**
The first end-to-end run of the phone path was, by every mechanical measure, a **success**: the session was
created with the right preset, all six MCP bridges mounted, the model called `mcp__secretary__ps_db_query`
three times, the turn completed, and the prose was fluent and well-structured. It was **wrong** — *"13 ticks
today"*, against the authority's **197** — because the bridge reads a **local replica**
(`ps_mcp_server.py:65`). Worse than the wrong number: the model noticed a suspicious artefact (a gap in the
data) and **invented an explanation for it** ("telemetry has been down for about three weeks") instead of
doubting its source.
*Rule:* when the thing being instrumented produces **claims about the world**, the acceptance test must
check the claim against a source you already trust. "It called the tool", "it streamed", "the session
persisted" are all equally true of a confidently wrong answer — and this system has already reported a
45-day outage that never happened (L1).
*Corollary:* a component that reads a **copy** without declaring it is a provenance bug waiting to happen,
no matter how new the feature that exposed it. The kernel refuses this exact file as *"only 173 tables
(< 190); structurally old"*; nothing else in the fleet checks.
*Cost of learning it:* none, because the answer was checked against the authority before it was believed.
That check took one query.

**L36 · A measurement that returns HTTP 200 is not a measurement that did work.**
`dshw-perf` posted `{}` to the DSH `/api/*` endpoints. Every call answered **200** with
`gateway/bad-request: invalid client-request message`, and the reported latencies were of schema rejection
— not the boot path. A conclusion ("no degradation at 12 windows") was published from it and had to be
withdrawn an hour later. The real envelope is
`{type:"client-request", rpcId, method, payload:{args}}`, and the fix was to **capture one real request
from a live client and replay that**, not to guess the shape. Corollary: when an API can answer 200 with a
semantic error, parse the body and assert success — never infer success from the status.

**L37 · Killing my own throwaway test process is not a question for the owner.**
I finished a portability test that left a disposable engine running on port 3097 and asked him whether to
kill it. His answer: *"totally your decision you should not have bothered me to decide this for you."* He
is the scarcest resource in this system and that question spent him on nothing. **Rule:** anything I
created, anything reversible, anything inside the work I was already told to do — decide it. Escalate only
money, customers, legal posture, family, genuine taste, or the irreversible. Housekeeping is mine.
**L51 · A tracker row saying "waiting on the owner" is a claim, not evidence — check the decisions log before asking.**
Two of the four "owner decisions" I was about to put to him had been **answered two days earlier**: the
modesty halacha baseline (five attributes × three neutrally-named Levels, override inside a hard floor)
and the billing party (LPT bills the family directly, per device). The backlog and the previous handoff
both still listed them as open, and I had already copied one of the stale rows into my own handoff —
inheriting an error by trusting a summary instead of the decision document it summarised. Three rows
were stale (the third was an SDK path resolved on 2026-09-08).
*Rule:* before asking the owner anything, resolve every "owner decision" row against the decisions file
that would have recorded it. A stale row is cheap to write and expensive to act on: it makes me ask a
question he has already paid attention to once, which is the exact behaviour the persona exists to stop.
*Cheaper than reading:* strike the row and cite the document, so the next reader sees why it is closed.
This is L47 one layer up — an artefact's *label* ("verified", "blocked on owner") is not its state.

**L52 · A fix verified through one entry point is not verified. Test the path the user actually takes.**
Within an hour of fixing L34 I broke the same subsystem again, in the opposite direction. I made
`telnyx_billing._connect_db()` prefer PostgreSQL and validated it by running the snapshot command in the
container: it printed `Connected to PostgreSQL` and `Persisted Telnyx snapshot to postgres (balance=5.22,
2 per-SIM usage rows, 1 ledger row)`. I called it verified and moved on.
It was not. `_PgConn.execute()` creates a **fresh cursor per query**, and the row factory had been set as
`raw.cursor(row_factory=dict_row)` — which applies to that *one* cursor, not the connection. So every
query returned plain tuples and every `row["column"]` access raised
`tuple indices must be integers or slices, not str`. Three live endpoints
(`/fleet/telnyx/usage`, `/customers`, `/billing`) returned 500, and `r["column_name"]` inside the connect
path itself raised, so `_connect_db()` silently returned `None` and **every write fell back to SQLite** —
meaning the PostgreSQL fix was never actually in effect on the endpoint paths at all.
*What made it survive my verification:* my test drove the **write** path, where the shim's tuple-vs-dict
distinction does not surface, through a **command** entry point rather than through the HTTP service the
business uses. And the error message actively misled me — "tuple indices must be integers or slices, not
str" reads like a SQLite problem while actually being a PostgreSQL row-shape one, which is why I looked in
the wrong place twice before instrumenting the container and printing `type(connection)` and `type(row)`.
*Rule:* verify through the **same entry point the consumer uses** — for a service, that means the endpoint,
not the CLI or the module. Concretely: (1) after any change to a shared data-access layer, hit every
endpoint that reads through it and check the status code, not just the one path you were working on;
(2) a library-level unit test proves the library, not the wiring; (3) when an exception message names one
technology and the stack you are debugging is another, **print the actual types** instead of reasoning
about it — `type(conn).__name__` and `type(row).__name__` located this in one command after two wrong
guesses.
*Cost:* three live endpoints down, a fix I had reported as verified that was not, and a wrong cause written
into a code comment (the `customer` column, which turned out to be present) that I then had to go back and
correct. Caught only because I went looking for something else and happened to call the endpoint.

---

## ⚠ ID allocation — read before adding an entry (2026-09-11)

**Seven lesson numbers are duplicated** in this file (L34, L35, L36, L37, L39, L40, L51) because several
sessions ran concurrently and each took "the next number" from whatever it saw. That is a race, not five
mistakes: **a monotonic ID cannot be allocated by reading a file and incrementing**, and any append-only
ledger shared by more than one writer has this failure built in.

**Do this instead.**

1. **Never guess the next number.** Run:
   `Select-String -Path journal/LESSONS.md -Pattern '^\*\*L(\d+)'` and take **max + 1**. Not the last line.
2. **Take a big step.** Numbers already jump (…49, 50, 51, 52). Allocate in the **100s** for new entries
   (`L100`, `L101`, …) so a concurrent writer cannot collide with you. Gaps cost nothing; collisions cost
   a corrupted reference, because "see L35" now points at two different lessons.
3. **Never renumber someone else's entry.** The duplicates above are left in place deliberately — this
   file is append-only, and quietly fixing the number would erase the evidence that two writers raced.
   Reference duplicates explicitly when you cite one: "L35 (the entry-point one)".
4. **Prefer a timestamp over an ID for a new entry.** With concurrent writers, a timestamp is unique by
   construction and a counter is not. Use `**L<max+1> · YYYY-MM-DD HH:MM · <claim>**`.

**Why it matters here specifically:** this is the file whose whole purpose is to stop the same problem
being rediscovered. A lesson that cannot be cited unambiguously is a lesson that will be re-learned. The
previous occupant of this seat left 55 improvements unapplied precisely because records that cannot be
referenced do not get acted on.
**L52 · A number in an internal document is a claim, not a measurement — and an unmeasurable band is a warning sign.**
The Feb-2026 research asserted per-attribute ceilings ("precise sleeve length <0.60", "collarbone <0.60") that
had **no external referent**: no published accuracy exists for hemline-at-landmarks, collarbone coverage or
tight-but-covered for *any* model, so those bands could never have been tested, only repeated. Six months later
the numbers had drifted in both directions — sleeve length looks *better* than claimed (supervised 0.9118 clean),
tightness *worse* (no benchmark above ~55%, DeepFashion Fit 0.45 / Skinny 0.35). The owner's instruction to
"re-analyze fully" was correct, and the tell was available in February: a figure with no source and no
benchmark behind it should have been marked as an assumption.
*Rule:* when inheriting a number, ask whether anything outside the document can confirm it. If not, label it an
assumption and treat re-testing as scheduled work rather than as a surprise.

**L53 · The most convenient library is usually the one you cannot ship.**
I recommended a geometric coverage method built on **DensePose** in the first draft of the re-analysis, before
an agent verified the licence: **DensePose is CC BY-NC 4.0 — non-commercial.** The same pass found ModaNet
("non-commercial research only"), FASHN Human Parser and `segformer_b2_clothes` (NVIDIA SegFormer terms) and
MobileCLIP-S0 (`apple-amlr`) all unusable for a paid product. The Apache-2.0 route to the same capability
(MediaPipe pose + selfie-multiclass + hair segmenter, ~22MB) was available the whole time.
*Rule:* licence-clear the **mechanism and the dataset** before the architecture is written, not before release.
Tech-report PDFs and blog posts never mention this; the `LICENSE` file does. Corrected in the document itself
with the correction left visible.

**L54 · A model's self-reported confidence is not a failure signal — never gate a fail-closed system on it.**
Measured calibration error for frontier vision models reached **ECE 0.496**, and under underexposure accuracy
fell **0.99 → 0.22 while stated confidence stayed flat at 0.87–0.90** (AUROC ≈ 0.50). Internal token
probability is better (AUROC 0.92–0.99) but no verifiable frontier API exposes multimodal logprobs. So the
design the Feb-2026 research implied — blur above a confidence threshold, escalate below it — **cannot be built
on model confidence at all**.
*Rule:* a fail-closed gate must key on a signal that is *falsifiable by construction* — a landmark that is
present or absent, a mask that exists or does not — not on a number the model chooses to say about itself.
This is the same shape as P3 (believing a stale database) one layer down: the artifact's own claim is not
evidence about its state.

**L55 · The cheapest technical option can be the one the vendor forbids — read the terms before the price.**
The cost analysis for server-side screenshot classification ended with a finding bigger than any price: **every
surveyed vendor's terms restrict this use case regardless of retention settings.** Google and Anthropic on the
relevant tiers are "not for consumer use"; xAI is 18+; DeepSeek disclaims children's data; **OpenAI retains
image inputs for manual CSAM review even under Zero Data Retention**; Anthropic mandates 30-day retention even
for ZDR organisations. A family content filter uploads bath-time and bedroom photos — precisely the distribution
that trips a CSAM classifier. So the "cloud is cheapest, so the only question is privacy" framing I had written
was wrong twice over: it was priced too optimistically, and it treated a contractual hazard as a preference.
*Rule:* for anything touching a customer's private data, the terms of service are an architectural constraint
with the same force as memory or latency, and they belong in the first feasibility pass — not discovered after
the design is chosen. Self-hosting stopped being a values choice and became the only defensible one.

**L56 · "Cheapest" ranking is mostly an artifact of input tokenisation, not of the vendor.**
Gemini 3 lets you choose **280 / 560 / 1,120 / 2,240 tokens for the same image at an identical rate** — a 4x
swing on one model. OpenAI charges **1,104 tokens at 720p but 2,448 at 1080p**, and **173 with `detail:low`**.
Image-resolution choices therefore move cost more than switching providers does.
*Rule:* before comparing vendors, fix the input. Downscale, choose the cheapest sufficient tokenisation, then
compare — and note that a vision cost table built without stating the image size and tokenisation is not
comparable to anything else. This is L42's "quote the number" applied to model inputs.

---

## On configuration that lies (Home Assistant, 2026-09-11 late)

**L100 · A nested key at the wrong indentation is a silent no-op, and the reload will still say success.**
Three files in `ha-config` contained YAML that was **valid YAML and structurally wrong**. The worst one:
`phoenix_alarm_mac_on` and `_off` were indented with a **single space**, which put them at the same level as
`rest_command:` rather than inside it. Home Assistant parsed the file, found no such commands, and carried on.
Nothing errored. `rest_command.reload` returned success. A comment in the file said the siren was wired.
*What was actually true:* `rest_command.phoenix_alarm_mac_on` and `_off` were **absent from the live service
list** while `script.phoenix_intrusion_reset` called one of them — so the audible alarm had had nothing to call
since the Alexa announcements were removed, and no one could see it from either side.
The same session found `configuration.yaml`'s entire `http:` block mis-indented (so a brute-force IP ban added
2026-09-05 had *never once* been active, while a comment claimed the hardening was in place) and
`phoenix_security.yaml` failing to parse outright.
*Rule:* for configuration that gets deployed, **validate the artefact before shipping it** — parse it with the
target system's own tags registered, then assert the specific things it is supposed to define
(`rest_command` names, sequence shape), not merely that it parsed. "It parsed" and "the system has it" are
different claims. And on the reading side: **a green reload is not evidence the configuration loaded** — ask the
system for the name the config was supposed to create. That question takes one call and would have caught this
months earlier.
*Cost:* an alarm the owner believed was audible, and a brute-force ban he believed was on. Both were in git,
both looked finished, neither existed at runtime.

**L101 · Two generations of one thing is worse than none, and the cheap way to find it is to ask what already exists.**
Before deploying the repo's `automations/` tree — which the live host does **not** load — the question that
mattered was not "is this file valid" but "does the live system already define these ids". The repo's
`access_control.yaml` alone carries 38 automation ids, and the system already runs a Phoenix access-control
master controller from its packages. Merging blind would have produced two live access-control generations on
the same doors: precisely the defect pattern already measured here (41 orphaned Keymaster entities, 114
collision-suffixed entities, `_2` and `_10` twins).
*Rule:* before adding configuration to a running system, enumerate what the running system already has and diff
the **names**, not the contents. A duplicate key is not a syntax error — it is a behavioural one, and it is
silent.
*How this was avoided:* the check exists (`check_dup_autos.py` logic) and I ran it before copying, which is why
one directory of the deploy was stopped and the rest was not.

**L102 · When a fix is a one-line structural change, deploy it and observe the specific service — not the summary.**
`rest_command.reload` was accepted, returned success, and the service list afterwards contained
`phoenix_alarm_mac_on` and `_off`. That is the observation. By contrast, the earlier restart "verification" —
`/api/config` answering 200 after a few seconds — proved only that a process answered HTTP. It took reading the
service list and grepping the log for `invalid config|failed to parse` (0 hits) to know the deploy was clean.
*Rule:* verify a change by reading the exact thing the change was supposed to create, and by reading the
negative space around it (no new parse errors, no missing chain members). This is L46/L52 one layer up again:
the summary is fine, the specific is proof.

**L57 · When two independent agents disagree about a number, fetch the source — do not pick the convenient one.**
One stream reported the applicability figures (24.7% mean NA-F1, 70.8% given-visible) from a WACVW paper. A second
stream, searching independently, reported it had found **no published source** for that split and advised treating
it as an internal benchmark. Both were acting in good faith; one was wrong. I fetched the paper and the exact
sentence was there: *"All VLMs struggle with applicability detection (mean Tier 2 NA-F1: 24.7%)"* — and the same
paragraph showed the figure I had been *repeating* was wrong: the best model is GPT-5 at **37.1%**, not "34.1% for
the best", and the benchmark covers **nine** VLMs, not seven. So the disagreement was productive: it forced a
primary-source check that confirmed one number and corrected another.
*Rule:* a second opinion's value is not its conclusion, it is the prompt to look. When sources conflict, the
resolution is the primary document — and the cost of fetching it is one tool call. Two independent agreements
would have left the 34.1% error in place indefinitely, in five documents, including one where I had called it
"the most important number in this document".

**L58 · Price the labour, not the tooling.**
I estimated the eval-set bake-off at "under $500" because I priced it from model-assisted pre-labelling costs
($0.0005–0.005/image). Real labelling for these attributes needs annotators from the target community, and the
researched figures are **$4,000–8,000 for 1,000 images** (~3 weeks, five domestic annotators at $15/h) — an order
of magnitude more. The cheap version exists (community volunteers, $0 cash) but costs auditability instead, and
the middle version (teacher-model pre-label + correction, $400–800) carries anchoring bias where humans rubber-stamp
the model and agreement *inflates* while quality does not.
*Rule:* when estimating the cost of producing ground truth, price the people who know the subject, not the
automation that guesses at it. This is also why "the model can label our training data" is the wrong answer for
fine-grained attributes (DECISIONS D21) — the label is the product.

**L103 · In the DSH browser loader, a wrong dependency name breaks the whole UI, not the plugin.**
`packages/plugin-cost` declared `dsh.client.inject: ["@deepseek-ai/dsh-api-session-controller",
"@deepseek-ai/dsh-client-ui-conversation"]` and, later, `exports.inject = { required: [], optional: ['slots'] }`.
The loader resolves **every name in both places as a SERVICE** through the client context and holds the entry
at `pending` until each one exists. None of those three names ever resolved, so the entry never activated and
**every window rendered "Failed to load plugins" instead of the app** — a broken cost pill took the whole
interface down. Fix: declare nothing, read optional capabilities with `ctx.get('slots')`, and if a dependency
is genuinely required use a service name the shipped client plugins use (`slots`, `locale`, `connection`,
`remote`). The diagnostic to look for is the shell bundle's `assertEntriesActive`, which prints the offending
entry and the names it is waiting on — that is the fastest path to the cause.

**L104 · `$pid` is reserved and read-only, and PowerShell matches it case-insensitively.**
`Stop-ServerTree` did `$pids = @()`. PowerShell resolved that to the automatic `$PID` and threw
"cannot overwrite variable PID because it is read-only", so the function died before stopping anything and
`dshw restart` hung — twice, for seven minutes each, with no output. Rename such a local (`$serverIds`). The
same trap bit a loop variable earlier in this repo's history.

---

## On calling a working thing broken (Home Assistant, 2026-09-11 evening)

**L110 · A short record is not an absent device — check `created_at` before calling anything missing.**
I audited Home Assistant by counting state rows per entity and reported that a Shelly plug "returned
exactly one row and then stopped — either unplugged or off-network." The owner pushed back; he was
right. The plug was `on`, drawing 27 W, pingable, cloud-connected, uptime 72.5 h, with a live schedule.
**`recorder` writes a row only when a state changes**, so a device continuously on has exactly one row.
*Mechanism:* I compared a **new** device's record length to an **old** device's record length and read
the difference as a fault. Its config entry was created three days earlier; a three-day-old entity is
*supposed* to have almost no history.
*The tell I walked past:* the same entity showed **8,655 rows** in one pass and **1 row** in the next.
Two of my own numbers disagreed by four orders of magnitude and I published the second without asking
why. **That disagreement was the finding.**
*Rule:* before an absence finding, read the registry's `created_at` and exclude anything created inside
the measurement window — its record length says nothing about its health. And when two of your own
readings of the same thing differ wildly, explain the difference before reporting either number.
*Cost:* ten of my eleven "effectively absent" entities were this one working device, and the claim sat
inside a section that also held true findings — which is what makes it expensive, because it audits the
credibility of everything beside it.

**L111 · "Double-check that" means test my own error first.**
*"Hold on the Shelly plug better be there… double analyze if it's actually lost, or if you just went
crazy."* Both branches were on offer; settling it took two queries — ask the device for its own status,
then ask the registry when it was created. Both were available before the first claim was written.
*Rule:* a finding that a working device is broken is a claim about the measurement at least as much as
about the device. Test it against the device first. Pushback is a signal to re-measure, not to
re-explain the original reasoning more confidently.
**L112 · A query that silently matches zero rows returns the same shape as a healthy answer.**
Building `comms_freshness` I wrote a capture-lag probe comparing a REAL column to a TEXT
`strftime()` result. SQLite did not error — it matched nothing — and the check reported
`call_capture_lag_hours = None` while every provenance line read `ok AUTHORITATIVE`. Had I trusted
the absence of an exception, I would have shipped a check that could never fire.
*Mechanism:* comparing REAL to TEXT in SQLite never coerces, so the predicate is just false. The
aggregate over an empty set is `NULL`, which is indistinguishable from "no data yet".
*Rule 1:* every new SQL predicate gets its own printed count before it is trusted. `SELECT COUNT(*)
WHERE <predicate>` — if the number is 0 and you expected rows, **the query is the suspect, not the
world**. The correct form here was `CAST(strftime('%s', ...) AS INTEGER)`.
*Rule 2:* for a "healthy?" check, `None` must never be rendered as silence. Distinguish
"no rows" from "cannot tell", and make the latter a refusal.
*This is L110 again in a different costume:* a short record read as an absence, this time produced
by my own query rather than by the recorder. Two data points now make it a pattern worth naming —
**suspect the measurement before the subject.**
*Cost:* none, because I ran it against the authority and read the `None` instead of assuming it
passed. That is the only reason this is a lesson and not an incident.

**L113 · A check whose input is a manual, long-stale path is a permanent false alarm.**
The first version of `comms_freshness` raised HIGH on voicemail because it read
`dialpad_ui_voicemail_row`, the Playwright crawl, which last ran 2026-06-14. The alert would have
been *true* and permanently so — 2,139 hours and not moving.
*Mechanism:* I picked the table whose name matched the concept instead of the path that actually
carries the data. The REST harvester already covers voicemail capture, so the crawl's staleness
measures a known, accepted gap rather than a regression.
*Rule:* before wiring a signal to `needs_attention`, ask "can this ever go green without someone
scheduling work?" If no, it is a metric, not a check. Report it, do not raise on it — because the
surface that cries wolf is the one a reader learns to skip, and then the real finding is invisible
beside it (P6).

**L59 · He does not read documents. A deliverable is for the record, not a reading assignment.**
I ended three consecutive turns with some version of "here are the docs, D33-07 and D33-08 are yours to review".
He answered plainly: *"i don't review things, if you have important questions for me, ask them clearly and
explained and i'll answer one at a time."* This is a category error I was making about the purpose of writing.
The documents exist so a decision survives past this session and so the next session does not re-litigate it —
they are not how the owner receives information. He receives information in the conversation, one question at a
time, with the consequences explained.
*Rule:* write the document, then ask the question. Never end a turn by handing him something to read. If a
document contains four owner decisions, that is four future questions asked one at a time — not a review task.
Encoded in the `zabz` persona as rule **2b** so it survives me (and note: the preset is read at session start, so
that edit only takes effect in the next session — P11/LESSONS already says a change can look done while having no
effect, so the rule is also here where I will actually read it).
*Cost:* three turns where the owner had to correct the form rather than answer the question, on a thread he had
opened himself.

**L60 · When a delivered figure is disputed, find the longest matching prefix — the difference is usually formatting.**
A patch script asserted on a note line in a document I had written, and failed. The text looked identical.
Comparing code points found that my own document had a **hard line wrap** where my search pattern had a space:
`recalibrate\nanything` versus `recalibrate anything`. Binary-searching for the longest matching prefix located
the divergence in one step instead of rewriting the pattern by eye.
*Rule:* when a literal replacement fails on text you are certain about, do not re-type it — bisect it. The
mismatch is almost always invisible whitespace, a hard wrap, or a different dash. Cheap, and it stops a
five-edit script from silently half-applying (which is what happened: the first three edits landed, the last
three did not, and only the assertion caught it).

**L114 · A column named `fetched_at` may record when a row was first SEEN, not when you last looked.**
`dialpad_call_full.fetched_at` is set on INSERT only. The `ON CONFLICT(call_id) DO UPDATE`
clause refreshes `updated_at` and deliberately leaves `fetched_at` alone. I built call freshness
on `MAX(fetched_at)` and it silently meant "newest row *first inserted*."
*Mechanism:* four harvest runs after 19:31 all reported `stored: 236`, yet **no row carried a
`fetched_at` past 19:31:32**. The job was running perfectly and the metric said it was 10 hours
stale; had a single call arrived, the same metric would have called a dead job fresh. It was wrong
in both directions at once.
*Rule:* before treating a timestamp as a freshness signal, read the write path and ask what the
column records on **update**, not just on insert. If the table upserts, prefer an explicit
heartbeat the job writes itself — "the job ran" is a different fact from "the job found something",
and only the first one is what a staleness check wants.
*Cost:* nearly shipped an alarm that would have gone green on a dead harvester. Caught by asking
why `stored: 236` left `MAX(fetched_at)` unmoved — **the disagreement between two of my own
numbers was again the finding** (L110, L112).

**L115 · A 10-second lock timeout is 30x the transaction time and still 300 seconds of wall clock.**
The scheduled harvest began failing with `database is locked`. 21 failed writes and a **306s** run —
because `_get_conn` sets `busy_timeout=10000` (app/database.py), so each contended write burned its
full 10s before giving up.
*Mechanism:* the harvester is a batch writer against a database a live FastAPI app is also writing.
SQLite WAL allows one writer; a batch of 236 upserts commits per row, so it collides constantly.
*Rule:* a per-row retry budget multiplies. `timeout × rows` is the real exposure, so a "safe-looking"
10s in a single-request handler becomes 5 minutes in a batch job — which then overlaps its own cron
interval. Fix at the batch layer (retry the idempotent pass, verify completeness) rather than by
widening the global timeout of a running application.
*Cost:* one wasted round trip; the retry wrapper cut it to 4 errors then 0 on the second attempt.

**L116 · `timeout N cmd <<EOF` gives the heredoc to the command's STDIN, so the timeout waits on stdin.**
The first scheduled-harvest wrapper hung past 150s and sat there with a 600s `timeout` that could
never fire. The worker never even started useful work — `timeout` was waiting for the heredoc's
stdin to close.
*Rule:* never feed a here-doc to a process you intend to bound with `timeout`. Write the worker to a
real file (`mktemp`) and run `timeout N python file.py`. This also lets the worker write progress
markers itself, so a later hang still leaves evidence of which stages completed.
*Cost:* one hung run and a stale lock that blocked two subsequent runs. The `flock` guard behaved
correctly throughout, which is why the damage was bounded — **the lock was working and told me.**

---

## On verifying a working thing rather than a configured one (phone link, 2026-09-11 20:30 UTC)

**L130 · 2026-09-11 20:30 UTC · A component that is configured and a component that works are different readings.**
The gate that signs the owner's phone in was running, listening on the right port, and relaying every request
untouched, because `request_line.partition(" ")` on `"GET / HTTP/1.1"` yields `path = "/ HTTP/1.1"` — so none of
its conditions could ever match. Every check that existed passed while his phone showed a 401: the socket was
open, `tailscale serve status` named the port, and the token URL answered 200 — but that 200 was the *engine*,
never the gate. *Rule:* a component is proven by the behaviour a human experiences, not by its process being
alive; and the quickest way to find out is to break the thing on purpose and watch the check fail.
*Cost:* a broken link hours in his hand, and a second "it doesn't work so well" report.

**L131 · 2026-09-11 20:35 UTC · A probe that cannot report its own failure is worse than no probe.**
Negative test: engine stopped, `request()` raised `RemoteDisconnected`, the probe died before writing its status
file, and the kernel went on reading the previous green file — up to 20 minutes of confident wrongness while the
phone was genuinely broken. *What any probe must therefore have:* network helpers that never raise (return a
status-0 result), every check under a guard that records a crash as that check failing, a status file written on
every path including failure, and a consumer freshness window of about twice the producer's interval.
Absence has to read as absent, never as green — L1 in a new costume.

**L132 · 2026-09-11 20:40 UTC · A platform attribute that lives only in the working tree is a local modification.**
Third occurrence of the same lesson: a host `chmod +x`'d a script (L21), git then refused the pull — *"Your local
changes to the following files would be overwritten by merge"* — and because the deploy was chained with `&&`,
the **old** script quietly ran instead: the engine came up on the wrong port and the new gate never started at
all. It reported success while deploying nothing. *Rule:* exec bits belong in git (`git add --chmod=+x`, or
`git update-index --chmod=+x`); no host may chmod by hand; and a chained deploy must be structurally unable to
fall through to the previous version without saying so.

**L133 · 2026-09-11 20:45 UTC · When you know the exact key, do not sort by mtime.**
The gate picked its token by newest-mtime across `engine-*.log`, while a stale `engine-3086.log` sat beside the
live one — so the day that file is touched last, the gate hands a visitor a token no engine accepts, silently
reproducing the exact dead end it exists to prevent. It already knew its engine port from `--engine-port`.
*Rule:* a heuristic for identity is a future wrong answer; use the exact key, and keep the heuristic only as a
fallback that the code names as a fallback.

**L61 · Do not flag. Solve, or ask exactly one question and move on.**
Owner, 2026-09-11: *"you dont just flag things for me randomly or tell me things, or stop working. You always work.
And when something needs to be clarified by me to make a decision for you, you ask me that one question very
clearly explained, get the answer and then you move on. Always finding solutions for things."*
Three specific failures in one session, all mine:
1. **"Two things I want you to know plainly"** — a risk list is not a deliverable. A discovered problem is work to
   be done, not news to be delivered.
2. **Queuing my own parameters as owner decisions.** I promoted the hold budget and the prefetch battery cap to his
   desk when measurements already justified defaults (CHI 2015 latency thresholds; a whole-app battery budget
   already set in `decisions/28`). He has told me three times now that development decisions are mine.
3. **Warning about a gap instead of closing it.** I reported that Level 3's female-figure detection had no
   supporting evidence. The solution existed and I found it once I looked: do not use a gender classifier, use the
   policy-adaptive guard, whose whole design is a natural-language policy evaluated in one forward pass — "is a
   female-presenting person visible?" is precisely its shape — gate it on-device with person detection, and measure
   it in the calibration harness before selling it.
*Rule:* for every problem, the question is "what is the solution, and can I do it now?" If yes, do it. If it needs
one fact from him, ask **one** clear question and then continue working — the answer is an input, not a stopping
point. Encoded as persona rule 2c so it outlives this session. This is the same error as L59 (handing him
documents) in a different costume: both are me treating the owner as the audience for my work instead of the
customer of it.

**L105 · `Process.HasExited` on a detached child can block for the child's whole lifetime.**
`dshw`'s readiness loop sampled `$proc.HasExited` every 500 ms to notice a dead engine. On Windows, against a
process started detached, that property call blocked instead of returning — so `dshw up` sat there until its
outer timeout (420 s, then 600 s) while the engine was up, serving, and had written its state. The script
looked broken and was not. Readiness is now **the log's URL line plus a listening port**; a child that dies
fails the timeout and the error path prints its stderr, so nothing is lost by not asking the process object.
Corollary: prefer observable facts a child publishes (a bound port, a log line) over handle-derived state,
because a handle can be a place where the caller blocks rather than a place where it reads.

**L53 · Read the authoritative deploy doc before escalating an infrastructure blocker.**
I told the owner staging was "blocked, needs you" and asked him to recreate a Heroku app. It was wrong twice
over: `phone-and-tech-full/docs/operations/DEPLOY_ARCHITECTURE_REALITY.md` opens with **"Heroku is DEAD"**
and states plainly that `.github/workflows/deploy-staging.yml` **"is not the working path"**. The real path —
Netlify for the frontend, Hetzner `lpt-apps` for the backend — was documented, and I deployed to test myself
in about an hour once I read it.
*What I actually did wrong:* I treated a **failing CI workflow** as ground truth about infrastructure. A
workflow is a script someone wrote once; it can point at hostnames that were deliberately retired, and it
will keep failing loudly forever without meaning anything. I also had the evidence in-session: the same repo
contained a doc whose own header says it wins over other docs. I read the workflow instead of the doc.
*Rule:* before reporting an infrastructure blocker, read the deploy/deployment doc — not the CI workflow —
and prove the target is actually gone (the Heroku API 404 proved the *app* was gone; it did **not** prove a
deployment path was gone). Then try the documented path. Escalate only what is still blocked after that.
*Cost:* one round of autonomous time spent asking the owner to resurrect something intentionally dead, plus a
false "Blocked" goal state that had to be retracted. The retraction is kept in `QUESTIONS.md` rather than
deleted, because the record of having been confidently wrong is the useful part.
**L117 · Checking one channel and escalating is not diligence — it is a guess with a citation.**
I read the SMS history for a customer, saw her ask to be called about payment and no reply after it, and
escalated to the owner: *"11 days of silence on $780, she's chasing by text and email, call her today."*
He pushed back — *"did you check the dialpad context... or are you flagging something for me by being
lazy?"* He was right. There were **11 calls** on that number, and the answers were in them: the order
shipped Aug 31 (he called her at 6:16pm to say so, hours after her worried email), and payment was
deliberately deferred to the following Monday with her agreement, in a 51-second call **the day before
I escalated**.
*Mechanism:* I stopped at the first source that returned a plausible story. The SMS table supported
"unanswered customer", so I reported it without asking what the *other* channels said. The resolution
was in a table I had already queried that same session for other purposes.
*Rule 1:* before escalating anything about a person, read **every** channel for them — SMS, calls,
transcripts, email — and reconcile them. A fact from one channel is a hypothesis until the others agree.
*Rule 2:* the owner asking "did you check X?" is a report that I did not, and the correct response is to
go and look, not to defend the original reading. My instinct was to re-explain; his question was the
finding.
*Rule 3, the one that matters:* when the answer *existed but was not practically readable*, fixing the
readability is the real work — not escalating and not apologising. Dumping a raw column full of
`action_item_v2` into a prompt does not count as having checked.

**L118 · When a data source embeds its vendor's internals, the fix is a reader, not a warning.**
`dialpad_call_full.transcription_text` interleaves real dialogue with Dialpad's own AI analytics *field
names* — `whole_call_summary`, `action_item_v2`, `ai_csat_reboot_ineligible`, `call_purpose_category`,
`ner`, `monologuing`. Measured: **5,362 of 5,644 stored transcripts (95%)** carry them, presented
identically to speech. Every call is also stored twice, once per leg.
*Mechanism:* the list-calls feed returns whatever the vendor produced, and the harvester stored it
faithfully. Nothing was "broken" — the data was simply unusable in the form it arrived, and no code
existed whose job was to make it usable.
*Rule:* a source that is retrievable but unreadable will be misread, and the misreading will look like
diligence (L117). Strip the artifacts, keep speaker attribution, collapse the duplicated legs, and
**report how much was removed** so a reader can see the cleaner worked instead of trusting it.
*Cost of not having it:* one wrong escalation to the owner, and an unknown number of quiet
misreadings in the company's own agents, which read the same column.

**L119 · Write the regression test in the direction that protects the real world, then run it before believing it.**
The transcript cleaner's tests caught **two over-reach bugs in my own code**: `"mm -hmm"` survived as a
turn, and `"Uh-huh"` slipped through because normalisation turns it into `uh huh` and `huh` was not on
my filler list. Neither was visible by reading the code; both appeared the moment a test asserted on
real stored lines.
*Rule:* for a filter, test **both** directions — the noise must go, and genuine content must survive.
A cleaner that deletes a sentence someone actually said is worse than the noise it removed. My file
includes `"Hmm, I'm not sure about that."` and `"I have a question about my bill."` specifically so a
future tightening cannot quietly start censoring customers.

---

## On the difference between my client and his (phone link, second pass, 2026-09-11 20:35 UTC)

**L134 · 2026-09-11 20:35 UTC · A proxy pools connections; one inspection per connection is not one inspection per request.**
The gate inspected the first request on a connection and then became a raw byte pipe — and Tailscale Serve, which proxies
every visitor to it, reuses one connection for request after request. So the returning visitor's request went straight to
the engine, uninspected, and never even appeared in the gate's decision log. Every curl test opened a fresh connection and
therefore passed. *Evidence:* the gate log showed one request for a browser navigation that made four. *Rule:* when you sit
behind a proxy, "once per connection" is a fiction; force `Connection: close` upstream (upgrades excepted) so each request
arrives on its own socket and gets its own decision. *Cost:* two rounds of telling the owner it was fixed when it was not.

**L135 · 2026-09-11 20:35 UTC · A test client that opens its own connection cannot see a pooling bug.**
My probe passed 7/7, then 9/9, while his phone still showed the 401. Both my client and the bug were about connections: mine
were fresh, his were pooled. *Rule:* an acceptance test for anything user-facing must run through the same proxy and the same
path the user's device uses, and must be dirty the way a real client is dirty — a stale cookie, a dead token, a
previously-cached response. A clean client through a side door proves nothing about a dirty client through the front door.

**L136 · 2026-09-11 20:40 UTC · Never hand a struggling client a task; finish the task for it.**
The design was: give the visitor a 302 to `/?token=<live>` and let their browser follow it. Any client that keeps a cookie the
engine will never accept then loops for ever — measured: 50 hops and a curl abort, and the "already repaired" query marker
cannot survive the engine's own 303 back to `/`. *Rule:* when the client is in a state it cannot diagnose (stale credential,
half-broken configuration), do the repair server-side and return the finished result. The gate now performs the whole login
itself — exchange, cookie, document — and returns the page with the session cookie attached. One request, no redirect chain
to loop on, and the bearer token never appears in a URL or in browser history.

**L137 · 2026-09-11 20:45 UTC · A limit keyed on the client's IP is worthless behind a proxy.**
I bounded the loop with an eight-second per-IP cooldown. Behind Serve, *every* visitor arrives from 127.0.0.1, so a single
repair locked out all comers for eight seconds — and my own probe failed within a minute of the deploy, which is the only
reason it lasted a minute. *Rule:* behind a proxy, the socket peer is the proxy, not the person; never key a policy on it.
*Also worth noting:* the probe caught its author's regression twice in one session, having first caught the bug it was
written for. That is the entire argument for building it, and it is now the strongest artefact from this work.

**L150 · 2026-09-11 20:40 · One successful measurement of a flaky-by-design signal is not a generalisation.**
I ran `tailscale ping` from the office **once**, got a direct path (`via 172.59.215.73:45261`), and concluded that an
office observer could always see which WAN the owner's phone was behind — then reported "he is at home" with
two-observer confidence. Re-measuring gave `via DERP(nyc)` + `direct connection not established` on **3/3** attempts: from
a *different* network the phone is usually reachable **only through a relay**, and no endpoint is reported at all. The same
signal from the *same* LAN was 3/3 reliable. *Rule:* before turning a reading into a claimed capability, repeat it and vary
the one thing that might matter — here, the observer's network. iOS suspends Tailscale in the background, so this failure
mode is silent and routine, which is exactly what makes n=1 dangerous on this signal specifically.

**L151 · 2026-09-11 20:40 · `ipaddress.is_private` does not mean "local LAN address".**
Measured on this repo's own interpreter (CPython 3.12.10): `is_private` is **True** for documentation (`203.0.113.0/24`),
benchmarking (`198.18.0.0/15`) and reserved (`240.0.0.0/4`) space — none of which any host can dial as a LAN — and
**False** for CGNAT (`100.64.0.0/10`), which is a real carrier WAN address and also Tailscale's own range. Using it as the
"same-LAN dialable" test reported an unroutable address as an *unrecognised local network*. A unit test caught it, and my
first explanation of the bug was itself wrong (I blamed CGNAT; CGNAT is the opposite case) — corrected in the same session
rather than left in a comment. *Rule:* test RFC1918 membership explicitly (`10/8`, `172.16/12`, `192.168/16`); give CGNAT
its own guard that answers "unknown, and here is why" instead of a confident "elsewhere". Generally: a stdlib predicate
that *sounds* like your question is not your question — read its actual table.

**L152 · 2026-09-11 20:40 · A self-satisfying guard will write a confident wrong answer to disk.**
`presence.py` records the office WAN so it can match the phone's endpoint against it. Its "am I at the office?" test was
`egress in office_wans` — but the same block had just *added* `egress` to `office_wans`, so the test was true by
construction on every host. It therefore wrote the **home** WAN (`172.59.215.73`) into `office_wans`, from the Yoga, at
rest, formatted exactly like learned knowledge. Found by reading the **state file** rather than the code. *Rule:* a guard
whose inputs are produced by the thing it guards is not a guard. Derive the fact from an independent observation (here the
host's own interface address, via a connected UDP socket) **and** scrub the invariant on every load, not only on the write
path — a poisoned cache is worse than a missing one, because the next reader has no reason to doubt it.

**L153 · 2026-09-11 20:45 · A one-packet probe of a sleeping peer manufactures false negatives.**
`probe_endpoint()` used `tailscale ping --c 1`. From the home LAN it then reported "no endpoint observed" on a cold call, and
the *very next identical* call succeeded; after that, **8/8** direct endpoints (`192.168.12.249`). An idle iOS peer has to be
woken, so one packet converts a wake-up cost into a silent empty reading — precisely the failure class (`P2`, `P43`) this
module exists to eliminate, reproduced inside the tool built to fix it. Changed to `--c 3 --timeout 5s`: **5/5** consecutive
runs resolve `HOME [high]`, including the first, cold one. *Rule:* when a probe of a phone, radio or sleeping daemon returns
nothing, re-send before believing it; and when a probe *is* the product, test its first call, not its steady state —
steady-state-only testing is what hid this, and the two earlier "verified" claims in this same session (L150) were the same
mistake in a different costume.

**L154 · 2026-09-12 01:05 · A per-item verdict cached against a group key is not a cache bug — it is an unverified allow.**
`MitmWsBridgeServer` stored the ML verdict for one image in `DecisionCache`, whose key is the **domain**, and returned
`safe` early on a hit. On any image CDN that means the first SAFE picture flips the whole host to ALLOW for five minutes,
and every later picture is revealed **without being classified at all**. The mirror failure is just as bad: one false DENY
blacks out the host, and that DENY feeds the DNS router. *Rule:* when caching a judgement, the key must be the thing the
judgement is about. Pixels are judged by content hash, hosts by hostname, pages by URL, and none of them may stand in for
another. Check every cache for this shape — *is the key coarser than the claim?* A cache hit is only safe when the key is
at least as specific as the thing being asserted.

**L155 · 2026-09-12 01:05 · A record with no content yet is pending, not stale.**
`ProxyImageStore.await` registers an empty slot for a URL and `put` swept "expired" slots on every store. An empty slot has
`storedAtMs == 0`, so it looked ancient and was deleted mid-wait: the waiting thread timed out *after the bytes had
arrived*. In production that would have silently disabled the whole optimisation on exactly the race it exists to win — the
page announcing an element before its download finishes — while looking like it worked. *Rule:* never age-test a field you
have not written; give placeholders their own clock. And when a concurrency test fails, extract the state from it
(`writerRan=true size=1 peek=32` proved the data was there and the *waiter* was broken) rather than re-running and hoping:
two earlier print-based attempts found nothing because Gradle swallows stdout, and a diagnostic `assertNotNull` message
found it in one run.

**L156 · 2026-09-12 01:05 · Verify a platform API exists before designing around it — the SDK jar settles it in one command.**
D34-29 was written as "read absolute `scrollX`/`scrollY` **from the scrolled node**". `AccessibilityNodeInfo` has no public
`getScrollY()` at all — the signal lives on `AccessibilityEvent`/`AccessibilityRecord`. The design survived, but the entry
would have sent the next reader to an API that does not compile, and the compiler was the only thing that caught it.
*Rule:* for any Android/DOM/system API you are about to build on, look at the actual artifact before writing the design
around it (`[System.IO.Compression.ZipFile]` over `platforms/android-34/android.jar`, search the class bytes for the method
name) — ten seconds, and it separates "I remember this API" from "this API exists". Correct the record by **appending** a
correction entry, never by editing the old one.


**L138 · 2026-09-11 20:37 UTC · "Who is visiting" cannot be recovered after the fact if the front door never recorded it.**
The owner asked whether the phone work was finally live. Everything about *what* happened was readable — the gate's own
decision log showed a cold visit signed in at 20:29:32 and the prompt I was answering posted at 20:29:52 — and nothing about
*who* did it: Tailscale Serve rewrites every tailnet visitor to 127.0.0.1, the gate logs no User-Agent, and client identity
does not exist anywhere else to recover it (`grep -rln userAgent` over the engine's server and web sources → nothing; the
session file's `request/header` is the LLM request config, not the client). What remained was timing plus the tailnet's own
per-peer counters: inference dressed as a reading. *Rule:* capture identity **at the point of entry**, because a proxy
destroys it and no downstream record will have it. Any front door built for a user's device logs the device (User-Agent) and
whatever identity the proxy forwards (`Tailscale-User-Login`, `X-Forwarded-For`) on every request it decides on — and the
acceptance test drives that same device class through the same door. *Cost:* the phone workstream's final step, the owner's
own confirmation from his phone, has been "the last unverified step" for three sessions (P42), and I still cannot tell his
iPhone from a laptop on the tailnet.

**L139 · 2026-09-11 20:37 UTC · Read the reflog before editing a shared file; a commit minutes old means a live writer.**
Asked about the phone, I found its gate script rewritten at 20:31:46 — four minutes before, by another session — and this
checkout had pulled three of that session's commits inside four minutes (reflog: 20:31:06, 20:31:46, 20:32:27). I had a
five-line change ready for that exact file. *Rule:* before touching anything under `harness-config`, `git reflog --date=iso`
plus `ls --time-style=full-iso` on the target file, both read as *now minus a few minutes*; a commit or mtime inside that
window means a live writer, and the correct move is to write the intent into the journal and let its owner apply it — not to
race it. *Cost:* the change is deferred by one session, which is cheap; a conflict or a stalled `--ff-only` pull on the other
session is not (P13, P44).

---

## On changing an interface you do not own (phone UI, 2026-09-11 21:30 UTC)

**L140 · 2026-09-11 · A rule that sizes a box must not size its contents.**
I wrote `button[aria-label] > * { min-height: 44px; min-width: 44px }` to make icon buttons thumb-sized. The box grew
as intended; the *glyph inside* grew with it, and every icon on the page — the rail, copy, feedback, the composer
controls — rendered enormous. *Rule:* when a selector's job is to enlarge a target area, it must stop at the element the
finger touches. *Cost:* one visibly wrecked screen on the owner's live device, caught by a screenshot, not by a number.

**L141 · 2026-09-11 · A measurement is not a look.**
My audit said `tooSmall: 0` — every control at least 44px — while the page was rendering as giant icons. Both readings
were true: the counts were right and the interface was broken. *Rule:* for anything visual, the numbers tell you what to
fix and the screenshot tells you whether you broke something else. Every layout change ends with an image, not a diff.

**L142 · 2026-09-11 · Do not remove a part of a layout you do not own.**
Hiding the collapsed rail looked like a free 14% of width. `display: none` on it collapsed the content column to 56px
and clipped every heading, because the app sizes its own layout around that element. *Rule:* adjust around a product's
layout, never delete a part of it — the 14% was the product's decision, and its cost is smaller than the coupling.

**L143 · 2026-09-11 · Injecting bytes into a served response means re-framing it.**
The engine serves its document chunked. Inserting 4.4 KB of CSS corrupted the chunk sizes and every client got
`IncompleteRead` — the probe failed six checks within a minute. *Rule:* if you modify a response body, you own its
framing: de-chunk, inject, recompute `Content-Length`, drop `Transfer-Encoding`.

**L157 · 2026-09-12 01:05 · An entry number is not a key: two machines mint the same next number, and the log merges by union.**
Merging `origin/master` on 2026-09-12 combined two machines' journals. Nothing was lost — the union driver kept both
sides — but the *numbers* collided: `P43`, `P44`, `P45` now name two different problems each, and `D37` two different
decisions, because both sessions took "the next free number" from a file they had each read before the other pushed.
Earlier collisions (`L34/35/36/37/39/40/51/52/53`, `W5`, `D17/18/19`) are already in both branches from the same
mechanism. *Rules:* (1) an entry is identified by its **title**, so cite `P45 (every threshold … is a guess)`, never
`P45` alone; (2) after any pull, take numbers from `max+1` of the **merged** file, not the local one; (3) the journal is
configured `merge=union` in `.gitattributes`, because picking a side on an append-only log silently deletes another
session's memory — the tempting resolution is the dangerous one. Merged tails can end up slightly out of timestamp
order; entries carry their timestamps, so order is cosmetic and reordering them is not worth the risk of mangling one.

---

## On deploys that do nothing (phone plugin, 2026-09-11 22:00 UTC)

**L144 · 2026-09-11 · Check the exit code of the command you think you ran.**
I wrote a commit, then branched on `$LASTEXITCODE` — which was still the *commit's* status, because the push line was simply
missing from the script. It printed "pushed from local master" and the remote never moved. The next run on the authority
therefore had neither the new probe check nor the self-healing install, and reported 11/11 while I was reading it as
confirmation of a 12-check file. *Rule:* after any deploy, compare the two hashes — local HEAD against the remote's — rather
than trusting an exit code, and prefer a verification that reads the far side (`git log` there, `grep` the deployed file).
*Cost:* one false "verified" in a report, caught only because a check count did not add up.

**L145 · 2026-09-11 · A monitor that is not deployed is not a monitor.**
The whole point of probe check 11 is that it fails when the phone silently loses its plugin. It could not fail: it did not
exist on the machine that runs it. The count (11 vs 12) is the only reason I noticed. *Rule:* when adding a check, prove it
by running it on the host that will run it, and read its line in the output — never infer it from a green summary.

**L146 · 2026-09-11 · A lowercase `grep` on `.env` certifies an absence that is not there.**
Asked to confirm tonight's Shabbat automation was configured, I ran `grep "shabbat" ~/personal-secretary-mvp/.env`
and got nothing — and was one sentence from telling the owner the automation was unconfigured on the night it
mattered most. The file contains `SHABBAT_AUTOMATION_ENABLED=true` and `SHELLY_PLUG_HOST=192.168.50.103`. Env keys
are upper-case by convention; a case-sensitive pattern over a settings file is not a search, it is a coin flip.
*Rule:* always `grep -i` for settings, and never report a negative ("not configured", "not set", "no such entry")
from a single pattern — re-run with `-i` or read the section before believing an absence.
*Cost:* one nearly-published false statement about a security system, on Erev Rosh Hashana.

**L147 · 2026-09-11 · Verify the device the code actually actuates, not the entity whose name matches it.**
`shabbat_interior_lock_entity = lock.0x002446fffd0a4705` reads like the interior door, and I read that entity
(and watched it) as proof the pre-power-down unlock would work. The code never touches it: `unlock_interior_door()`
publishes MQTT `{"state_l4":"OFF"}` to `zigbee2mqtt/Smart Switch/set`, which is HA entity `switch.smart_switch_l4`.
The config key is dead, and the named lock is a different physical device (the Kwikset apartment deadbolt) that
stays `locked` through the whole power-down. Had the fallback fired on my first check it would have acted on the
wrong door. *Rule:* for anything safety-relevant, follow the call to the wire — read the function, then assert on
the exact entity or topic it publishes to — and treat a config key the code never reads as a lie with a friendly
name. *Cost:* the first version of tonight's watchdog watched a dead entity; caught only by reading the source.

**L148 · 2026-09-11 · Never ask the owner for a fact that is already written down.**
He sent a photo of a young woman and said "that's my wife", and offered a photo of himself. I replied by asking
**her name**. It was on disk the whole time: `docs/family/2026-08-19-yitz-engagement.md` line 28 ("Eliyahu's wife
is ALSO named Yocheved ('Dr Yocheved' in the chat)") and `docs/wedding/aygestin-after-effects.md` ("Yocheved
('Cheved') — wife of Eliyahu Zabrowsky", married 2026-08-16). He answered: *"You should know her name already
that was a bad question."* He is right, and the cost is not the wording — it is that a question spent on a lookup
is a question not spent on a decision only he can make, and it reads as an agent that does not hold his context.
*Rule:* before asking him anything factual about a person, place, device, account or number, search
`personal-secretary-mvp/docs/{family,wedding,handoff}` + `journal/` + the `contacts` table, and keep the answer in
`journal/reference/people.md` so the lookup is never needed twice. Ask him only what is genuinely his: money,
customers, legal posture, family, taste, and anything irreversible.

**L148 · 2026-09-11 · Editing a Python file does not reach a running scheduler — and the proof it took is behavioural, not a restart banner.**
I changed how Shabbat/Yom Tov power-down runs are computed, then found the running uvicorn process had already cached
both modules (my own `/shabbat/status` call had imported them). A restart was required, but the restart itself proves
nothing: systemd reports `active` long before the app's lifespan has registered the jobs, and the app's own daily job
would have gone on re-programming the device from the *old* code — silently reverting the change tomorrow morning.
*Rule:* after restarting a scheduled app, verify three separate things — the health endpoint returns 200, the
scheduler's boot thread exists in the **new** pid (`/proc/<pid>/task/*/comm`), and the *behaviour* changed (here:
`curl 192.168.50.103/rpc/Schedule.List` showed 8 jobs with the split, where the old code produced 6 with the merge).
Then run the idempotent operation a second time and require byte-identical output.
*Cost if skipped:* a change that looks deployed, a green `systemctl status`, and a device that quietly reverts at 10:00.
**L158 · 2026-09-11 · A second copy of a thing is not a second reading of it.**
Asked whether the yoga conversations are readable from ZABZ-TECH, I went looking in
`/home/zabz/dsh-archive/dsh-archive.db` on secratary: 91 sessions, yoga's newest `updated_at` 19:06Z, the file
last written 19:10Z — which reads as "yoga's archiving died two and a half hours ago". **False.** The
authoritative store for DSH sessions is `/home/zabz/personal-secretary-mvp/data/secretary.db`, written by the
app's own route `POST /api/v1/owner/dsh-sessions/ingest` (transport `http`, the shipper's default since
2026-09-11 19:16); in *that* store yoga is current to `21:06:32Z` and this machine to `21:47:02Z`. The standalone
DB is the interim `scp` store, correctly frozen when the HTTP path went live — two stores for one thing, and only
one of them has a writer.
*Rule:* before reporting any staleness, name the store and name the process that writes it. A copy nobody writes
is not evidence of a gap; it is evidence of a migration. Same failure class as the stale-database crisis that
never existed, and it nearly happened again from a reading that was fresh and correct about the wrong artefact.

**L159 · 2026-09-11 · A 500 from your own API can be a write lock, and the client's retry budget must outlast
the server's patience.**
The shipper got `500 {"ok":false,"error":"internal_error"}` from the ingest endpoint at 20:05, 21:05 and 21:45
tonight. The app's own journal held the cause the whole time: `sqlite3.OperationalError: database is locked` at
`app/services/dsh_session_ingest.py:200`, on the export row's `INSERT OR REPLACE`. The route sets
`PRAGMA busy_timeout = 30000`, so **one** attempt can sit for 30 s before failing; the shipper's policy was 2
attempts 3 s apart — about 63 s of patience — so a writer holding the lock for a minute aborted the whole run.
Two rules came out of it:
(a) **arithmetic, not superstition** — the retry budget must be ≥ (server patience + backoff) × attempts, or the
retries are theatre. It is now 4 attempts at 5/15/45 s with a 120 s per-request timeout: ~3 minutes of tolerance,
enough to outlast a checkpoint or a long transaction.
(b) **fit the fix to the measurement.** `error_log` shows ~12 `database is locked` errors in 21 hours app-wide, on
this route and one node-report endpoint. That justifies patience in the client; it does not justify rebuilding
the ingest path — and a 2.7 GB production database is the wrong place to be clever late on a Friday night.

**L160 · 2026-09-11 · Fail-closed cursors make a silent outage recoverable — which is not the same as noticing
it.**
The shipper advances a session's cursor only after the server *accepts* the batch (its own comment: "advancing a
cursor before the server holds the rows is how a shipper silently loses data it believes it already sent"), so
2.5 hours of 500s cost **nothing**: when the endpoint recovered at 21:47, this machine's 244 new rows went up in
one batch against an intact cursor. Verified directly — a forced failure against a fake 500 endpoint left
`~/.dsh/dsh-archive-state.json` byte-identical (SHA-256 `F684653F…`).
But nothing *told* anyone for two and a half hours. A scheduled task reporting `LastTaskResult = 0`, a cursor
that looks current, and a store that quietly stopped growing is a shape that hides itself.
*Rule:* fail-closed protects the data; the alarm is a separate mechanism, and this machine still has none.


**L161 · 2026-09-11 · A check you have never seen fire is not a check — and the failure mode belongs IN the test.**
Building the archive-silence alarm, I wrote the thresholds first and the self-test second. The self-test failed the
case that mattered: I had set the Windows hosts a 180-minute window, so **the exact outage I was building the alarm
to catch — this machine's real 2.5 hours of silence on 2026-09-11 — evaluated as healthy.** A plausible-looking
number, chosen by feel, would have shipped an alarm that could not fire on the one event that had actually
happened.
*Rule:* for any threshold, alarm or guard, encode the historical failure as a test case and watch it fire before
keeping the number. A self-test that only asserts the happy path proves the code runs, not that the alarm works.
Corollary of L160: the previous session correctly named the missing alarm as NEXT and correctly did not build it
in the same breath; this is what building it properly costs — one deliberately-failing case.

**L162 · 2026-09-11 · Working production code can exist outside version control, and only the *deployment host*
knows it does.** The Shabbat/Tov split that fired at 18:46:53 tonight existed **only as uncommitted working-tree
files on secratary**. `origin/master` still carried the pre-split version, so every other machine in the fleet —
and every future reader of the repo — believed the old behaviour was current. A `git status` on any other host
reports clean. The generalizable shape: when the service runs from a checkout, that checkout is part of the
running system, and *dirty* there means *unreproducible* everywhere else.
*Rule:* before diagnosing "the deployment is behind", diff the **working tree** against the remote, not just the
branch pointer. Rescue the dirty state into a real commit first (`git read-tree` into a temp index +
`commit-tree` + `update-ref` a new branch leaves the working tree, index and HEAD untouched), push it, and only
then reason about fast-forwarding.



**L163 · 2026-09-11 · Measure the size of a lie before you fix it — and beware a metric that counts the
*failure handler* as success.** The company reported "82.8% of ticks completed today". `work_sessions.status`
was set to `completed` on four code paths for sessions that had *not* finished, because reaching a step budget,
a hard ceiling, or a repetition guard was treated as a graceful completion rather than as the failure it is.
The scale only became visible once measured: 74,610 sessions, 19,685 ever containing `[FORCE-COMPLETED]`,
6,132 `[AUTO-COMPLETED]`, and only **6,506** ever containing a real `[WORK_DONE]`. In the last 24 hours,
**182 of 329 "completions" were hollow (55%)**.
*Rule:* when a system has a "graceful degradation" path, ask what the degradation is *recorded as*. If the
answer is "success", every downstream metric, alarm and postmortem built on it is worthless — and the more
sensible the degradation looks in code review, the more damage it does. Fix the recording first; the metrics
correct themselves.
*Corollary:* the repository already contained the honest idiom (`_fail_artifact_required_work_session` →
`failed` / `[COMPLETION BLOCKED]`, 808 rows). The defect was not ignorance of the right pattern; it was one
pattern applied in one place and not the other three.

**L164 · 2026-09-11 · A structural guard must check *control flow*, not *text presence*.** The AST guard I
wrote to stop the above returning first matched `update_work_session` by `getattr(node.func, "attr")` — but
the calls in that file are bare `Name` nodes, so it matched nothing and passed on an empty set. Fixed to
accept both `Name` and `Attribute`, it then flagged a line I believed was correct. It was right: my rule
looked for `[WORK_DONE]` *anywhere* in a parent subtree, and the enclosing `for` loop body mentions it, so an
ungated 100% write "passed". Tightening the rule to accept only the condition of an enclosing `if`/`while`
(`ast.Compare` inside `cur.test`) both fixed the guard and produced better code — the completion write now
sits lexically inside `if "[WORK_DONE]" in accumulated_output:`, which a human can verify at a glance.
*Rules:* (a) a matcher that finds nothing looks exactly like a matcher that passed — assert the match count
is non-zero; (b) if a test is written to detect a class of bug, seed it with a real instance of that bug and
watch it fail before trusting it to pass.



**L165 · 2026-09-11 · A blunt suppression fix outlives its incident, and the silence it creates is invisible
because it looks like calm.** To stop the CEO sending 28+ "URGENT" texts, the previous agent created
`data/OWNER_SMS_KILL_SWITCH` — a file that blocks **every** owner SMS. It was honoured in four modules, and for
**54 days** the owner received nothing: 595 messages held, including a payroll-blocked notice and two account
security alerts. Nothing detected the silence; the queue simply filled, and its status field said `held`, which
reads like a deliberate decision rather than a total outage of the owner channel.
*Rules:* (a) when suppressing a *symptom*, write down the trigger that un-suppresses it, and put it somewhere
the system checks — an unused kill switch is an outage waiting for a date; (b) suppress with a **rate limit**,
not a switch, whenever the symptom is "too many" rather than "wrong"; (c) the cheapest detector for this class
is a freshness check on the channel itself (`MAX(sent_at)`) — the same shape as the archive alarm (L160) and
exactly as absent.

**L166 · 2026-09-11 · Distinguish the gate from the transport before naming a cause.** I first attributed 54
days of silence to the urgency threshold and was about to fix that. Measuring the transport separately — Twilio
`status: active` with the same credentials, and a per-month count of actual sends (May 402 → August 0) — showed
two independent blockers: the threshold explains why `normal` messages cannot pass, the kill switch explains why
*nothing* passed after 20 July. Fixing the one I noticed first would have changed nothing.
*Rule:* for a "nothing is happening" symptom, measure each stage in order (trigger → gate → transport →
delivery) and find the **first** stage that is empty. A plausible cause found early is not a cause confirmed.



**L167 · 2026-09-11/13 · An alarm must distinguish "the machine stopped" from "there was nothing to say".**
I built the archive-silence alarm (L160) to catch the real 2026-09-11 outage, where sessions existed and the
shipper failed for 2.5 h. Two days later it fired **3/3 and was wrong**: `secratary` had no DSH activity at all,
so it had nothing to ship, and `zabz-tech`/`zabz-yoga` were simply idle. v1's rule was "the archive has not
advanced in N minutes", which cannot tell a broken shipper from a quiet machine.
*Rules:* (a) for any "no data" alarm, the signal must be **"data exists and did not arrive"**, not "data did not
arrive" — measure the producer's own state (here, the shipper cursor versus the newest local session file),
because that is the only thing that distinguishes silence from failure; (b) a false alarm is not a neutral
error: it teaches the reader to ignore the alarm, which destroys the value of the true positives; (c) when you
fix an alarm, add the case that fooled it to the self-test, not just the case it was built for.

**L168 · 2026-09-11/13 · Do not confuse "I have been working for a while" with "no time has passed".** This turn
ran from 2026-09-11 18:20 to 2026-09-13 21:57 EDT. I read a three-day-old digest, saw timestamps 2.5 days
older than the clock, and first narrated it as "three days have passed" with no idea what happened in them —
then nearly went the other way and called it a clock fault. Both hosts agreed and were NTP-synchronised, so the
elapsed time was real and the fleet had simply kept working.
*Rules:* (a) timestamp your own observations and re-read the clock before summarising; an in-session snapshot
is never evidence about the present; (b) when a long turn resumes, the first question is not "where was I" but
**"what changed while I was away"** — read the journal, the digest and `MAX(updated_at)` before reporting
anything as current; (c) if clocks are suspected, prove it with two independent hosts and NTP status before
naming a clock fault, because a wrong clock claim is a confidently-wrong number.

**L·new · A vendor's "we'll let you know" is a promise that needs a watcher, not a memory.**
ALCO's Mark wrote on 2026-08-29 "Usual lead time is 3-4 weeks. We'll let you know soon as a tracking
number is available." Nothing arrived, and for 16 days nothing in this system noticed — the durable
records still ended at Aug 28, with the Aug 29/30 exchange missing entirely.
*Cost:* a paid $615.44 order for a fixed-deadline holiday item sat unmonitored until the owner asked
about it 11.5 days before Sukkos.
*Rule:* when an outbound promise has a date attached ("we'll let you know", "ship date", "by Friday"),
that date becomes a watcher on the authority — not a line in a doc. If the promise is a status, look
for the vendor's own status source before assuming there is none.

**L·new · The vendor's own tracking backend is often a public JSON endpoint sitting in the page JS.**
ALCO's "Track Your Order" form runs a client-side gviz query against a public Google Sheet
(`/gviz/tq?sheet=<Month YYYY>&tq=select C,D,E,F`) — the sheet ID was in a comment block in the page's
inline JS. One `curl` returned the live order status, which no email would have told us.
*Rule:* before concluding "we can't know the status", read the page's JavaScript for the data source.
Never trust a UI when the data behind it is fetchable directly. Cite the endpoint, the tab, the row
and the read timestamp as provenance.

**L·new · When drafting in the owner's name, the register is his, not mine.**
Two rejections on one email in the same session: (1) "Why are you writing such a long and complex
email? … He doesn't care about our actual holiday"; (2) "don't write so strong as I'm not used to me.
It sounds like you're threatening him." My v1 was a 200-word status report; my v2 was 4 sentences but
opened with "I need it in hand by Tuesday, September 22; after that it's no use to me this year."
*Rule:* for outbound in the owner's voice — read his last 3 sent messages to that counterparty and match
them (short declaratives, "just checking in", "I'm hoping", "if that's possible"). State constraints as
hopes, never as deadlines. A constraint the *vendor* reads as pressure costs the outcome it was meant to
protect. Do not explain our reasons to the vendor; they are ours, not his problem.
*Applies to:* every email drafted for approval. Draft, then re-read as the recipient before showing it.

**L·new · A named date is a target a vendor negotiates down to; "sooner the better" plus a reason pushes up.**
Third revision of the same email. v2 said "I need it in hand by Tuesday, September 22; after that it's no
use to me this year" — owner: "don't write September 22. Write the sooner the better cause as soon as it
comes, we can start building it. If it comes a day before the holiday, we can't use it."
*Rule:* when the goal is speed and there is no genuinely fixed date, do not name a date. A stated deadline
tells the counterparty the minimum that satisfies us, so the best case becomes that date. "Sooner the
better for me — I need a few days with it once it arrives" leaves the whole window open and gives a reason
that costs them nothing. Reserve stated dates for the rare case where late is fatal *and* the counterparty
must also plan around it.
*Applies to:* all deadline-bearing outbound drafts. Ask: does naming this date raise or lower the ceiling?

**L·new · Iterate a deliverable in the owner's name until it is final — never make him the review loop.**
Four rejections of one email in one session, each returned to him: too long → too strong → no date → no
reason. He ended it with: "write it again then order it yourself a few times before giving me the final
version. I don't need to keep checking you."
*Rule:* when the owner rejects a draft, do not hand back v2 with one change and ask again. Take the stated
principle, generate 3–5 variants against it, critique each as the recipient, and present **one** final
version plus what changed. His corrections are constraints, not a merge request. Reserve his attention for
the one thing that is genuinely his — here, the per-message send approval.
*Corollary — an ask with no reason reads as impatience.* "Sooner is better for me — I need a few days with
it once it arrives" explained nothing. The version that worked named why early delivery has value (a large
cover rigged by hand onto a frame: sleeves, body grommets, tie-downs) — a reason that costs the counterparty
nothing but makes the request legitimate.


**L169 · 2026-09-14 · The cost of a search is the walk, not the match — so index once and never walk again.**
Measured on the primary machine before changing anything: `rg --files` enumerated **129,015 files in 0.41 s**,
while `rg -l payroll` took **45.34 s** for 100 files. The enumerator is instant because it is one syscall each;
the content search re-reads every byte of the tree for every question. After building a persistent SQLite FTS5
index, the same query returned in **0.075 s** — about **600×** — with better relevance, because the index
skips the trees nobody greps.
*Rules:* (a) when a tool "feels slow", separate enumeration cost from match cost before optimising anything,
because they fail for different reasons; (b) an index is only worth building if it is *incremental* — key it on
(size, mtime) so the second run is cheap, or it becomes a thing nobody runs; (c) index age must be **reported**,
not assumed, or a silently stale index is worse than no index (L167).

**L170 · 2026-09-14 · Two tokenizers, because one index cannot be good at both prose and code.** FTS5's
`porter` stems (`payroll`/`payrolls` collapse) but cannot match inside a word; `trigram` matches any substring
(`entication` inside `authenticationMiddleware`) but cannot stem. Code search needs the first for prose and the
second for identifiers, so the index carries both tables and the query picks. Verified on both hosts before
building on it (SQLite 3.49.1 / 3.46.1, all three tokenizers present).
*Corollary:* derive the plan from a **capability probe**, not from documentation about the version — my first
attempt to test this failed purely from shell quoting, and the second proved the capability on the real host.


---

## On changing a layout you do not own (phone sidebar, 2026-09-14)

**L146 · 2026-09-14 · Read the layout mechanism before you style it.**
`display: none` on the sidebar collapsed the conversation to 56px and clipped every heading. The cause was invisible
from the outside: `.pI_x6G_frame` is `display: grid`, and **the app sets its columns inline from JavaScript** —
`grid-template-columns: 56px minmax(0px, 1fr) 0px`. Removing a grid child shifts the others into the wrong tracks, so the
conversation moved into the 56px track. *Rule:* before changing a layout's boxes, read the live CSSOM and the inline
styles on the container. Two minutes there replaced an afternoon of guessing, and the fix (`grid-template-columns:
minmax(0,1fr) !important` plus taking the sidebar out of flow rather than deleting it) could only have been found that way.

**L147 · 2026-09-14 · A transformed ancestor owns its fixed descendants.**
The first working version moved the drawer with `transform: translateX(-100%)`. That creates a containing block for
`position: fixed` descendants, so the sidebar's own toggle would have travelled off-screen with it — and that toggle is the
only control that opens the sidebar. `left: -340px` moves the same box without adopting its children. *Rule:* when you take
a container off-screen, check which of its children you are also removing from the user's reach; prefer `left`/`top` over
`transform` when something inside must stay pinned.

**L148 · 2026-09-14 · Before hiding a control, verify it is not the only one.**
I assumed the content header had its own "Open sidebar" button, as the rail's icons are duplicated there. It does not: the
only toggle lives inside the sidebar, at [10,14] 44x44. Enumerating every button whose accessible name mentions "sidebar",
with its parent and its box, took one call and prevented shipping a phone interface that could never switch conversations.

**L149 · 2026-09-14 · An uncommitted write on a deployment host blocks every deploy, silently.**
The authority's checkout was 5 commits behind and refused to fast-forward: an agent session running *on that host* had
written `journal/HANDOFF.md`, `LESSONS.md` and `PAIN.md` and never committed them. The work existed in no ref — a checkout
or stash would have destroyed it, and a snapshot-style autosync would have too. Resolved by backing the three files up,
committing them verbatim, rebasing onto `origin/master` (clean) and pushing. *Rule:* a host that both runs agents and
deploys from a checkout will eventually block itself this way; the deploy path needs a keeper that says "N behind and dirty"
rather than failing a pull into a log nobody reads.
**L169 · 2026-09-14 04:05 UTC · `ipaddress.is_private` is not "is a local LAN address".**
I used `is_private` to decide whether a Tailscale endpoint was dialable only from the same LAN. Measured on this
repo's own interpreter (CPython 3.12.10): `is_private` is **True** for documentation (`203.0.113.0/24`),
benchmarking (`198.18.0.0/15`) and reserved (`240.0.0.0/4`) space — none of which is a LAN — so an unroutable
address was reported as an *unrecognised local network*. It is **False** for CGNAT (`100.64.0.0/10`), which is a
real carrier WAN address and also Tailscale's own range. A unit test caught the first half.
*Rule:* test RFC1918 membership explicitly (`10/8`, `172.16/12`, `192.168/16`), and give CGNAT its own guard that
answers "unknown, and here is why" instead of a confident "elsewhere". Generally: a stdlib predicate that
*sounds* like your question is not your question — read its actual table.
*Also:* my first written explanation of this bug blamed CGNAT, i.e. it was wrong in the opposite direction from
the truth. Corrected in the code comment the same session rather than left standing, because a wrong rationale
outlives the fix and misleads the next reader.

**L170 · 2026-09-14 04:05 UTC · A one-packet probe of a sleeping peer manufactures false negatives — test the
cold call, not the steady state.**
`probe_endpoint()` sent `tailscale ping --c 1`. From the home LAN, on the same network as the owner's iPhone, it
reported "no endpoint observed" on a cold call and **succeeded on the very next identical call**; after warming,
**8/8** returned `192.168.12.249`. An idle iOS peer has to be woken, so one packet converted a wake-up cost into
a silent empty reading — the exact failure class (`P2`, `P43`) the module was built to eliminate, reproduced
inside the tool written to fix it. Changed to `--c 3 --timeout 5s`: **5/5** consecutive runs, including the
first, cold one.
*Rule:* when a probe of a phone, radio or sleeping daemon comes back empty, re-send before believing it. And when
the probe *is* the product, exercise its **first** call — steady-state-only testing is what hid this, and the two
earlier "verified" claims in the same session (L150) were the same mistake in a different costume.

**L171 · 2026-09-14 · A Techloq-class filter serves its block page with a SUCCESS status code, so a status check
reads a block as a pass.**
On Yocheved's box, `https://api.deepseek.com/v1/models` returned **HTTP 200 (`Invoke-WebRequest`) and HTTP 302
(`node:https`) — both with `text/html`**. TCP 443 was open. So every cheap liveness signal said "reachable" while
the endpoint was in fact filtered. The decisive evidence was not the status code but the **TLS issuer**:
`issuer=CN=env1.dc3.us.techloq.com, O=Techloq Ltd` — a full MITM, which also proves *all* her HTTPS is
intercepted, not just the blocked hosts.
*Rule:* on a filtered network, judge a call by **content type and parseability**, never by status — and read the
certificate issuer once to learn whether you are behind an interceptor at all. This is the same class as L150
and P2: a confident reading from the wrong signal.
*Second half, and the one that nearly cost a whole evening:* Node on her box **could not complete any TLS
handshake** (`unable to get local issuer certificate`) even though `NODE_EXTRA_CA_CERTS` was set at *Machine*
scope and the CA file existed. The probe process simply had not inherited it — it descended from an NSSM
service started before that variable existed. Setting it **explicitly** made the identical script succeed.
*Rule:* a machine-scoped environment variable is not evidence that a long-running service's children inherit
it. Set it in the launcher, and prove it from the process that will actually run the work.

**L172 · 2026-09-14 · A TLS-intercepting filter can make a working API key look broken.**
Her VS Code BYOK chat failed on 2026-09-02 with `Missing API key for DeepSeek V4 Flash (default)`, and the
reasonable reading was a bad key. It was not: the key in her `.env` is **byte-identical** (same 32 chars, same
sha256 prefix) to the owner's, and a live `POST` to DeepInfra **from her own machine** returned HTTP 200 with a
real completion. The actual cause was in the extension: `repoEnvPath()` searched only
`vscode.workspace.workspaceFolders`, and activation is `onStartupFinished` — which can fire **before** workspace
folders are restored, so the lookup found nothing and reported a missing key.
*Rule:* "missing credential" is a claim about a *lookup*, not about a *value*. Before believing it, run the
lookup the software runs and print the path it resolved. Fixing the error message to name the resolved path
would have collapsed this diagnosis to one line.
*Cost:* the failure sat in her logs since 2026-09-02 and her last real work was 2026-08-30 — thirteen days of a
broken assistant that nobody was told about, because the error was only ever visible in a log on her own box.


