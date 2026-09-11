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

