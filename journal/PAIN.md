# PAIN — what hurts, ranked, with what would fix it

**Rule:** every entry names the symptom, the evidence, the cost, and the fix. Ranked by what
actually costs the owner most. This file is how a problem stops being rediscovered.

Updated: 2026-09-11

---

## P1 — The owner's attention is spent on questions that are not his

**Symptom.** ~25% of all 26,950 measured turns were a single letter — `a`, `b`, `yes`, `ok`. Median
turn length 62 characters. 966 turns said "one at a time"; 2,283 said "keep going"; 227 said "stop
reporting back".

**Evidence.** `01-copilot-corpus-audit.md` §3–4, derived from every session on both machines.

**Cost.** The owner is the scarcest resource in the system and he was acting as a decision router
for questions the agent should have decided. It is also why the workflow was abandoned: usage
collapsed 75% in May and 78% again in June.

**Fix.** Encoded in the `zabz` persona: finish the work, never ask permission already held, one
question at a time with options and a recommendation, and never route development decisions up.
Remaining work: make it *measurable* — count questions per session and flag sessions that exceed a
threshold.

---

## P2 — Nothing watches outcomes, so failures are silent

**Symptom.** 8–13 August 2026: six consecutive days, 3,246 ticks, **zero completions**, one dead
model id. Nobody was told. 24 August: 597 ticks, 84% failure. Also silent.

**Evidence.** `04-autonomous-system-postmortem.md` §2.1–2.2, live database.

**Cost.** ~6 days of a company that exists to work while the owner sleeps, plus an unknown number of
missed finance syncs, sensor checks, inbox triage, and follow-ups.

**Fix.** The `ceo-kernel` sentinel — done and verified. It retrospectively detects both windows and
refuses to report when it cannot see.

**DONE 2026-09-11 (later session).** The sentinel now runs *unattended*: `ceo-kernel` is a git repo
(deployed as a checkout on `secratary`), and cron runs `scripts/run-sentinel.sh` every 5 minutes,
recording `latest.json` + `history.jsonl` in `/home/zabz/ceo-kernel-var/`. The gap named here — "not
dependent on anyone remembering to run it" — is closed for Phase 1. What is *not* yet closed: nothing
routes a finding to a human (that is the inbox, Phase 2), and nothing reads the history as a trend.
Recording without alerting is deliberate; see `ceo-kernel/docs/OPERATIONS.md`.

---

## P3 — Reading the wrong data and believing it

**Symptom.** The CEO reported a **45-day outage that never happened**, by reading a stale local copy
of the database. Three copies of `secretary.db` exist — 203 / 194 / 173 tables, tick histories ending
on three different dates — and none declares which is authoritative.

**Evidence.** `04-...` §0; `06-decision-log.md` D5.

**Cost.** A false crisis report to the owner. If it had been acted on, real systems would have been
"fixed" that were not broken.

**Fix.** Provenance layer — done. Every reading carries source, authority, and age; a consumer that
cannot establish them refuses. Remaining: **collapse the three copies** into one authority plus
explicitly-marked replicas, and stop anything writing to a stale replica.

---

## P4 — The improvement loop does not close

**Symptom.** 56 proposals unapplied; **30 identical proposals to fix the same file**; 13 targeting
files inside `node_modules`; 51 generated in September, 0 applied. Last successful application:
4 July 2026.

**Evidence.** `04-...` §2.3; live `evolution_log`.

**Cost.** Real tokens spent every day generating improvements that structurally cannot land — which
looks like progress and is worse than doing nothing.

**Fix.** Design exists (path filter, dedup, real apply path, verify-then-keep-or-revert). Not built.
This is the highest-value unbuilt subsystem, because it is the mechanism of self-improvement.

---

## P5 — Work assigned to agents that do not exist

**Symptom.** `engineering_indexer` has run **172 ticks and never completed one**. 34 `ghost_agent`
errors: `goal_steps` assigned to names like `engineering_floor_manager`, `finance_clerk`,
`world_index_indexer` — twenty-plus phantom names, each appearing twice.

**Evidence.** Sentinel finding `agent_dead_weight`; `error_log`.

**Cost.** Work silently vanishing. The blueprint and reality disagree and nothing reconciles them.

**Fix.** A reconciliation check comparing `company_blueprint.py` against live agent ids, plus routing
orphaned steps. Not built.

---

## P6 — Held messages and unanswered questions rot silently

**Symptom.** **7 `critical` and 46 `urgent` messages held undelivered.** 313 questions pending, none
created since 19 July, oldest **131 days** old. Three competing dismissal schemes suggest repeated
ad-hoc noise suppression rather than fixing the cause.

**Evidence.** Sentinel finding `attention_debt`, live data.

**Cost.** The system detected real problems and buried them. Some were customer-facing.

**Fix.** Inbox with ageing, escalation ladder (24h→48h→72h), and an interrupt quota — designed, not
built. Note the 144 sync-breaker alerts in one month are almost certainly why the dismissal schemes
appeared: fix the noise source first or the inbox becomes noise too.

---

## P7 — Context poisoning

**Symptom.** 41,522 tool-leak events across the corpus. Sessions of 4 MB of output per owner turn;
one session reached 399 MB for two messages. `ps_health` alone returns **90,891 bytes** in a single
result.

**Evidence.** `01-...` §5.3; MCP validation report.

**Cost.** Compaction discards the decisions the owner cares about, which is the real cause of "you
forgot what we decided".

**Fix.** Pruning and spill policy exist in the harness. The specific trap is the MCP bridge returning
huge payloads — needs a wrapper that truncates and summarises before it reaches the model.

---

## P8 — Harness configuration drifts between machines

**Symptom.** Desktop had authored a background-first shell preset and **never switched it on**;
Yoga did not have it at all; neither was version-controlled; settings differed in both directions.

**Evidence.** `06-decision-log.md` D7.

**Fix.** `harness-config` source of truth — done, with sync, remote on `secratary`, and LF
normalisation. Remaining: no scheduled sync, so drift resumes the moment someone forgets.

---

## P9 — The CEO stops when it owns the decision

**Symptom.** Four consecutive turns ended with "say go and I'll proceed" for work already delegated.

**Evidence.** `06-decision-log.md` D8.

**Fix.** Rules recorded in the persona. Monitoring it is the honest test: if it recurs, the rule is
insufficient and the harness needs to enforce it rather than the prompt.

---

## P10 — ~~Repeated mount-validation spawns duplicate MCP servers~~ **RETRACTED 2026-09-11 — see the correction at the end of this entry. There is no duplication.**

**Symptom.** After several `standingKeyFor` calls, **four** `ps_mcp_server.py` processes were running
as children of the DSH process, plus **three** `mcp_launcher.py` processes — one per validation call.
A standing mount persists for the life of the process, so each check adds a live server rather than
reusing the existing one.

**Evidence.** Process tree on `ZABY-YOGA`, 2026-09-11: DSH pid 11744 had children 57252 / 37548 /
60428 / 24148 all running `ps_mcp_server.py`, and 30716 / 4184 / 49292 running `mcp_launcher.py`.

**Cost.** Wasted memory and duplicate subprocess trees, each holding its own connection to the
secretary API. On a machine with six MCP bridges this compounds. It also makes process evidence
harder to read — "is the bridge up?" returns four answers.

**Fix.** Do not mount-validate repeatedly. Validate once, then rely on it. Longer term: the
mount-validate path should detect an existing standing generation and reuse it rather than
re-composing. Needs investigation in the roster service, not a workaround here.

**CORRECTED 2026-09-11 (later session) — the symptom above is not real. This entry was wrong.**
The "four `ps_mcp_server.py`" count came from matching process command lines against
`personal-secretary-mvp` — a **directory** — which matches every script inside it. Counted by exact
script name on a live session: **exactly one** `ps_mcp_server.py`, plus 3× `mcp_launcher.py`
(firecrawl, jina, context7), one per bridge. There is no duplication, and the "each check adds a live
server" mechanism is unsupported.
What *is* real, and what produced the illusion: **every venv-python launch appears as two processes** —
a ~4 MB parent (the venv shim) and the real payload child (14 MB launcher, 63 MB `ps_mcp_server.py`).
Reproduced independently with a `time.sleep(20)` payload containing no process-spawning code, so it is
a property of the interpreter launch, not of the MCP scripts. A naive process count therefore
**double-counts every python-based bridge**.
*Kept as written, not deleted*, because the error is instructive: this is L2 — reading the wrong thing
confidently — committed inside the very journal created to prevent it. See LESSONS L28.
**Confirmed a second time with eight sessions open (2026-09-11 12:58).** Measured precisely — by
exact process name and script basename, and excluding the survey's own command line — there is
**one** DSH server process (`dsh web`, hosting ~8 sessions) with exactly **one** `ps_mcp_server.py`
shim per external bridge. The bridges are composed **once per process, not once per session**: opening
seven more sessions added no bridges. So the original worry was doubly wrong, and the design is
better than the entry assumed.
Measured as a side note: the whole DSH process tree with six bridges holds **721 MB** across 12
processes, and that number is real, unlike the one above. The dominant cost is not the bridges — it is
**one `dsh-subprocess-local/runner.js` shell per concurrent command at ~58 MB each**, so the memory
story on this machine is driven by how many sessions run shells at once, not by MCP.

**AMENDED AGAIN 2026-09-11 17:55 — the sentence above about "once per process" is wrong, and the
correction matters more than the original error.** Creating a *second* session on the same engine
(`:3085`) mounted a **second complete set** of bridges: the listing showed 2× `mcp_launcher.py` for
firecrawl, 2× jina, 2× context7, 2× `mcp-fetch-server`, 2× playwright, and the secretary row twice —
once as the old local `python ps_mcp_server.py` and once as the new `ssh … ps_mcp_server.py`. So:

> **Bridges are composed per SESSION, not per process.** Two sessions, two sets.

Why the earlier count misled me: the first session's bridge set was the only one *I* had created, and
the seven other sessions were other people's — their bridges existed, but my filter (exact name plus
script basename, excluding my own command line) still matched only the set I was looking at. A count
that confirms what you expect deserves the same suspicion as a count that surprises you (L28).
*Consequence, and the reason this is a PAIN entry rather than trivia:* the cost model in
`docs/multi-window/` — which sizes a fleet of 8–12 windows — assumes one bridge set per engine. If it is
one per session, then 8–12 sessions is **48–72 bridge processes**, and the ~1.4 GB per-engine figure is
really ~1.4 GB *per active session*. That is the difference between "12 windows fit" and "12 windows do
not", so the multi-window sizing needs re-measuring before the owner leans on it.

---

## P13 — Concurrent sessions share one repo, and `git add -A` sweeps each other's work

**Symptom.** Eight DSH sessions were live in one project directory at once (`session_projcache`,
2026-09-11 12:53–12:58), all on preset `zabz`, several of them editing the same working tree —
`harness-config`, and other repos under `C:\Users\ezabz\code`. While this session was writing the
journal, another session ("Add per-turn chat cost estimates") wrote
`journal/reference/deepseek-token-pricing-2026-09-11.md` into the same repo, and this session's
`git add -A` **committed it**, under a message that does not mention it.

**Evidence.** `git log --oneline -- journal/reference/` → the file arrives in commit `4becfa4`, a
commit whose message describes only journal corrections. File mtime 12:55:41, between two of this
session's own edits.

**Cost.** Small this time — the file was legitimate and correctly placed, and nothing was lost. The
failure class is not small: two agents staging a shared tree means one can commit, attribute, or
revert another's half-finished work, and neither can tell from the diff. It also produces exactly the
phantom-difference confusion of P8/L21, with a new cause.

**Fix.** Adopted rule: **in a shared working tree, stage explicit paths — never `git add -A` or
`git add .`** (LESSONS L33). Longer term, concurrent sessions should not share a mutating repo at all:
either serialise on it, or give each session its own clone and let the remote be the meeting point.
Not built; the rule is the cheap half.

---

## P14 — The real memory cost of a session is the shell, not the tools

**Symptom.** Six MCP bridges looked like the memory story. They are not. Measured on ZABZ-YOGA with
eight sessions live: a DSH server at **678 MB**, six bridges as direct children at **4–63 MB**
(the venv shim is ~4 MB; the real payload is its child), and then **each concurrent shell command at
~58 MB** for its `dsh-subprocess-local/runner.js`.

**Evidence.** Process survey at 12:58, counting by exact name and script basename: 16 direct children
of the one DSH server, of which 10 were `runner.js` at ~58 MB and 6 were bridges.

**Cost.** Roughly ten concurrent shell commands is ~580 MB before the sessions themselves. With eight
parallel sessions on an i9/64 GB desktop that is affordable; on the Yoga it is the number that decides
how much parallel work is safe, and nothing tracks it.

**Fix.** Not urgent and not yet a problem — recorded so a future self sizes parallel work from the
right variable instead of blaming MCP bridges, and so the "eight sessions" habit is a known cost.
If it becomes a constraint, the lever is limiting concurrent shells per machine, not reducing bridges.

---

## P11 — The preset default is chosen at session start, so changes need a restart

**Symptom.** `self_audit` reported this session running preset `cordis` while `settings.yaml` said
`zabz`. The DSH process started at **12:32:28** and the settings file was written at **12:32:29**.

**Evidence.** `self_audit` output; `HANDOFF.md` entry for 2026-09-11.

**Cost.** A change can be "made" and reported as done while having no effect at all. The model
namespace re-reads per request, which makes the difference easy to miss: one setting applied live and
the other silently did not.

**Fix.** After changing `agent-presets.default`, **restart the profile and verify with `self_audit`
before claiming anything.** The rule is now: no claim about a preset without a live agent reporting
that preset.

---

## P12 — Freshness is asserted but not measured, so every reading says `age=?`

**Symptom.** Every provenance line the sentinel prints ends `age=?` — e.g.
`daily_completion: ok  AUTHORITATIVE  age=?  src=sqlite:…secretary.db@secratary`. The source and the
authority are established; **the age of the data is not**.

**Evidence.** `ck status` on `secratary`, 2026-09-11T16:50Z, all seven checks. Same in
`/home/zabz/ceo-kernel-var/latest.json`.

**Cost.** Rule 1 of the kernel is "no trend without freshness" — and the kernel currently reports
trends (a 30-day collapse window) whose underlying data age it cannot state. It is *honest* about this,
which is why it is a medium and not a crisis: `?` is better than a fabricated number. But a reading
that cannot say how old it is cannot distinguish "healthy" from "the pipeline died three days ago",
which is the exact failure the whole kernel exists to catch (L12, P2).

**Fix.** Give each check a declared freshness basis: the timestamp column that proves it is current
(`tick_telemetry.created_at`, `activity_log.created_at`, …), pass it as `newest_row`, and let
`provenance.build()` compute the age. Where no timestamp exists, assert **"age not applicable"**
explicitly rather than leaving `?`, so an unresolved `?` becomes a bug rather than the normal state.
Belongs in `ck/sentinel.py` + `ck/sources.py`; not started.

---

## P17 — The Home Assistant security system has been blind for a day and nothing told anyone

> **ID note (same session, later):** first written as "P15". A concurrent session committed its own
> P15/P16 (WAZE/Telnyx) minutes before, and neither of us could see the other's numbering. Kept
> append-only: renumbered here, with the collision recorded rather than silently corrected. P13 is the
> same failure class — two sessions, one tree — and this is its cost in the record itself.
> **Fix direction, not yet done:** reserve IDs by appending a placeholder line *before* writing the
> body, or number from the clock (`P-20260911-1305`) instead of a sequence.

**Symptom.** Three Zigbee devices — the outside-door contact, the interior control-room contact and
the apartment deadbolt's old entity — went `unavailable` at **2026-09-11 01:48 local** and were still
unavailable 11 hours later, when this session first looked. `binary_sensor.phoenix_outside_door_contact`
is the canonical trigger named in `docs/SECURITY_DECISIONS.md` for the highest-severity scenario the
business recognises: *door opened without an official unlock*. Separately, the camera snapshot step of
the intrusion response fails 100% of the time (Dahua `192.168.50.170:80` unreachable, 365 errors), so
a real intrusion would page the owner, strobe the lights and leave **no evidence**.

**Evidence.** `ha-config/docs/AUDIT-2026-09-11-live-systems.md` §2 F1–F2; live reads via
`scripts/ha_truth.py` at 2026-09-11 16:55–17:00 UTC; `docs/SECURITY_DECISIONS.md` for the trigger
definition; commit `98f6235` for the intent of the snapshot step.

**Cost.** The difference between a security system and a sense of security. Both failures were
invisible in the Home Assistant UI summary: the sensors read `unavailable` on a dashboard nobody was
looking at, and the integration that fails every call reports `loaded`.

**Fix.** (1) Make this surface a *scheduled* reading with an alarm on **absence**, not a manual audit —
the collector exists; nothing runs it yet. The `ceo-kernel` cron on `secratary` is the natural home.
(2) The physical root causes are an owner action at the office: re-pair three devices, and bring the
camera host back. (3) The HA SSH add-on is off, so nothing that needs the host can run at all.

---

## P18 — Home Assistant is on the office LAN and reachable from exactly one machine

**Symptom.** The Home Assistant host answers only on the office LAN (`192.168.50.34`). From
`ZABZ-YOGA` — where the owner works at night — nothing reaches it. Tailscale carries the workstations
and `secratary`, not HA.

**Evidence.** Direct probes from the Yoga at 2026-09-11 12:50 ET: HA tcp/22 and tcp/8123 unreachable,
`secratary` via its Tailscale IP reachable, HA reachable **from** `secratary`.

**Cost.** Every HA task either runs through an SSH hop that must be set up each time, or silently
becomes impossible. It is why the overhaul's own Part 1 scripts have never been run: they assume
`homeassistant.local` resolves. Nothing in the repo or the journal said this before this session, so
each new self would have rediscovered it.

**Fix.** Keep the collector's `-ViaSshHost` path (done, verified). Longer term: advertise the office
subnet over Tailscale from `secratary` (`--advertise-routes=192.168.50.0/24`) with the route approved
in the admin console, which makes HA directly reachable from both workstations and removes the hop
entirely. Needs the owner's Tailscale admin action; not started.

---

## P19 — The audit that this whole role is built on is **untracked** in git

**Symptom.** `personal-secretary-mvp/docs/secretary-replacement-audit/` — the seven documents that are
the evidence base for the persona, for the kernel's design, and for most of what is in this journal —
is **untracked**. It exists only in one working tree on one laptop.

**Evidence.** `git status --porcelain` in `personal-secretary-mvp`, 2026-09-11 13:0x, while committing
the thirteen-day-silence postmortem: `?? docs/secretary-replacement-audit/`.

**Cost.** Nearly every rule in `LESSONS.md` cites these documents by name. Losing a laptop loses the
evidence for *why* the rules exist, leaving rules nobody can re-derive and therefore nobody can
correctly revise — the same failure as an unapplied proposal (L16), one level up.

**Fix.** Commit it to the repo it belongs to, or to `harness-config` if it is meant to travel with the
persona. Deliberately **not done in this session**: other sessions were actively writing in that repo,
and an audit captured mid-write is worse than one not yet captured. Cheap to do when the tree is quiet.

---

## P20 — The monitor lives on the machine it monitors

**Symptom.** The kernel's sentinel, its schedule and its history all live on `secratary` — the same
host as the database and the company. If that host dies, the evidence of its death dies with it, and
nothing else knows to be worried.

**Evidence.** `ceo-kernel/docs/OPERATIONS.md`;
`personal-secretary-mvp/docs/postmortem/2026-07-22-thirteen-day-silence.md`, action item 6.

**Cost.** Not theoretical: the 2026-07-22 incident shows this system can be silent for two weeks. The
sentinel catches that class *while it is running* — and the failure being watched for is one that could
also stop the watcher. A watched-host monitor is a real improvement over nothing (it found the 13-day
gap) and is still incomplete.

**Fix.** A heartbeat in the other direction: the host emits a timestamp it cannot silently stop
emitting, and something **off-host** (desktop, Yoga, or the Hetzner VPS) alarms when it *fails to
arrive*. The check must expect absence and be surprised by it, rather than reading a file the host
wrote. Not built. Highest-value remaining piece of Phase 1's honesty story.


---

## P13 — *I leaked a live API key into the session transcript*

**Symptom.** While writing a reader for `~/.dsh/.credentials.yaml`, my own error path threw
``record <id> has no secret``, where `<id>` **was the DEEPSEEK_API_KEY value** — the reader had matched
a `records:` key against the ref's scalar because the regex assumed nested indentation. The secret was
printed to stderr, and therefore into this session's durable log and into the owner's screen, before I
noticed and rewrote the module.

**Evidence.** This session's own log, and `harness-config/packages/plugin-cost`'s `L44` in LESSONS.
The rewritten `dsh-cost/lib/credentials.mjs` now prints only lengths and booleans.

**Cost.** A live provider credential is in a stored transcript. Rotation is the owner's call and costs
his time; not rotating leaves a key exposed in a file that is backed up and synced.

**Fix — two parts, one mine and one his.**
1. *Mine, done:* credential-handling code may not put a secret into an exception, a log line, or stdout.
   The failure path is part of the design, not an afterthought (LESSONS L44).
2. *His:* rotate `DEEPSEEK_API_KEY`. Nothing detects this class of leak, and the transcript is durable.

**Not yet built.** A scan that looks for key-shaped strings in new session logs and refuses to leave
them there. The logs are local and compressed, so this is a small job — and it is the difference between
"we learned the lesson" and "the lesson cannot recur".
## P21 — The last mile of verification is skipped when its dependency is not installed

**Symptom.** `A-BACK-011` ("verify the ML cascade on a real device") sat PARTIAL for five days with the
note *"blocked on this node: no emulator package / no system image / no attached device"*. The emulator
package and an `android-34` system image were a **free, one-command, 15-minute install** on a machine
with 110 GB free and WHPX already available. Nobody ran it. And when it finally ran, the harness that
had been waiting for it turned out never to have worked at all.

**Evidence.** `docs/IMPLEMENTATION_BACKLOG.md` A-BACK-011 history; `docs/HANDOFF_2026-09-10.md` §4.3
("STILL BLOCKED on this node"); LESSONS L47; the first real run on 2026-09-11.

**Cost.** A user-facing crash — the app died on the *first* image classification, from 2026-09-06 until
2026-09-11 — plus a day of believing a broken harness, plus the 2026-09-10 session's own conclusion that
"nothing is blocked on the codebase itself" when the verification it had just written had never executed.

**Fix.** Two habits, both cheap:
1. **Clear free blockers by installing the tool**, and do it in the same session that discovers them —
   record a blocker only when clearing it costs money, hardware, or the owner's decision. (DECISIONS D20)
2. **When a blocker clears, re-run the thing that was waiting before trusting it.** A harness that has
   been waiting for a device has never been exercised; its first run is a test of the harness, not of
   the product, and it should be expected to fail for its own reasons.

**Not yet built.** Nothing detects the first case — a task marked blocked on an install that is free.
A standing check that lists "blocked" items whose blocker has no cost attached would do it.

## P14 — Nothing watches the windows, so a dead engine is silent until the owner notices

**Symptom.** The supervisor can start, stop and restart the fleet, and a Task Scheduler task brings it
back at logon, but **no running process polls the ports**. If the engine dies at 2am, the windows sit
there showing a reconnect loop and nothing says why. The same class as P2 (nothing watched outcomes),
one layer down.

**Evidence.** `multi-window/dshw.ps1` has `status` and `doctor` but no loop and no scheduled health task;
the only automation registered is an At-logon task (verified: "DSH Multi-Window Launcher", task state
Ready). Observed twice in this session: an engine died and `status` reported "recorded, not listening"
with nothing to raise it.

**Cost.** Up to a full night of dead windows, discoverable only by looking.

**Fix (not built).** A second scheduled task, every 5 minutes, running `dshw doctor`-shaped health:
probe each enabled port, restart only the dead index, and append one line per action to a health log —
never restart a port whose bind succeeded, never fight another supervisor (the port bind is the lock).
15 minutes of work; the reason it is not done is that it needs the owner's `windows.json` to be final.

## P15 — Window layout is not remembered between launches

**Symptom.** Every window opens where `windows.json` says, not where the owner last dragged it. Geometry
is passed explicitly at launch (`--window-size`, `--window-position`), so a drag is lost on the next
`up`. Edge does store app-window placement internally, in an undocumented key, but it is keyed by the app
URL and is not something to depend on.

**Evidence.** `docs/multi-window/research-windows-multiwindow.md` §Q1 (measured: geometry takes effect
only because each window has its own profile; `--window-name` is a no-op on Windows).

**Cost.** Small — one drag per window per restart — but it is the kind of papercut that makes a person
stop using a tool.

**Fix (not built).** At `up`, read each window's current rect via Win32 `GetWindowRect`, match the window
by its browser profile in the command line, and write position/size back into `windows.json`. Then the
layout is self-healing and the manifest stays the one source of truth.

---

## P22 — The secretary bridge reads a **stale replica**, and answers confidently about a company it cannot see

*(ID checked at write time. Numbering collides often now that several sessions write this file at once —
an earlier P13/P14/P15 collision and a duplicate P21 are both in this file. A clock-based scheme would fix
it; see the multi-window session's note under P17.)*

**Symptom.** The first end-to-end run of the phone path (2026-09-11, through Tailscale) created a session on
preset `zabz`, mounted all six MCP bridges, called `mcp__secretary__ps_db_query` **three times**, and
answered:

> "13 ticks today (2026-09-11 …) — but telemetry has gaps: 93 on 09-10, then nothing logged between 08-21
> and 09-10, so 13 is likely an undercount of what actually ran."

The authoritative database on `secratary` says **197 ticks today** and **no gaps at all**. The replica the
bridge actually read says **13 today, 93 yesterday, then a jump to 08-21** — the agent's answer, exactly.

**Evidence.** `personal-secretary-mvp/scripts/ps_mcp_server.py:65` → `DB_PATH = ROOT / "data" / "secretary.db"`.
On ZABZ-YOGA that file is 485 MB / **173 tables** / mtime `2026-09-11 00:57`; the authority is 2.4 GB /
**203 tables**. Both measured the same hour. Transcript:
`~/.dsh/sessions/--C-Users-ezabz-code--/session-cf3cf7e8-…/session.v3.jsonl.zstd`.

**Cost.** This is PAIN P3 — *reading the wrong data and believing it* — at a new layer, and it is the failure
class that already produced one fabricated outage report. Every workstation session, and now every phone
session, reads it. Worse than a missing answer: the model found a suspicious artefact and **invented an
explanation for it** ("telemetry has been down for about three weeks") instead of doubting its source. The
phone puts confident wrongness about the business in the owner's pocket.

**Fix.** (1) Run the bridge **on the authority**: the preset row becomes a stdio command that runs
`ps_mcp_server.py` on `secratary` over SSH, so there is one copy and it is the real one (L13). (2) Port the
kernel's provenance rule into the bridge — a reading whose source is structurally old, or whose age cannot be
established, is **refused**, not returned. The kernel already refuses this exact file as *"only 173 tables
(< 190); structurally old"*; the bridge performs no such check. Designed in
`docs/dsh-mobile/01-DESIGN-AND-PLAN.md` Phase 2.5; not built.

**Acceptance test.** From the phone, ask for today's tick count: the authoritative number, or an explicit
refusal. Never a plausible number from a stale file.

## P16 — A backgrounded window can grow host memory without bound

**Symptom.** One engine serves every window over a single WebSocket mux. The project reports the downlink
has per-frame but no byte-level backpressure, so a throttled or backgrounded tab lets `bufferedAmount`
grow on the **host** side. With 8–12 windows, one forgotten background window can quietly consume the
engine's heap. Reported upstream with the repository's own discussion as the source
(`docs/multi-window/research-dsh-perf-config.md` §5).

**Evidence.** Not reproduced here; it is a code property of the installed version and there is nothing to
configure. It is recorded because it is the most plausible remaining cause of "it got slow overnight" now
that the browser-side cost is fixed.

**Cost.** An unexplained memory climb, then a stalled or OOM engine, with no obvious trigger.

**Fix (not available as config).** Operational: keep the number of *actively streaming* windows modest,
and treat engine RSS climbing without a burst as this symptom. What can be done here: the supervisor's
`status` already prints whole-tree memory per engine, so a rise is visible — what is missing is anything
that *watches* it (P14).

## P17 — Agent fan-out is capped in depth and uncapped in breadth

**Symptom.** `dsh-subagent` caps `maxDepth` (default 3) and has **no** `maxTotal` / `maxConcurrent`. A single
session that fans out — a workflow, a wide research sweep — can start unbounded subagents in one engine.
One reported case: 56 subagents in one `dsh web` process → ~2.2 GB, one core saturated for 20 minutes, and
the GUI unresponsive until it was killed by hand
(`docs/multi-window/research-dsh-perf-config.md` §7).

**Evidence.** Upstream discussion, cited in the report; the config surface confirms depth-only limits.

**Cost.** The exact failure the owner cares about — "no slowdowns" — caused by one session, not by window
count. It also compounds: fan-out inside a session that is itself one of twelve windows.

**Fix.** Budget subagent breadth per session (the workflow plane already has `maxConcurrentAgents` and
`maxTotalAgents`; the plain subagent plane has neither), and have the supervisor treat a sudden engine
tree growth as this symptom. Not built.

---

## P23 — A remote stdio MCP bridge spawns a process on the authority every time the network blinks

**Symptom.** After P22 was fixed by running the secretary bridge **on** `secratary` over SSH stdio, a
transient Tailscale outage (a few minutes, relay path dead, host up the whole time) turned that bridge into a
respawn cycle: the Yoga's `ssh.exe` bridge was killed and replaced roughly every 30 seconds, and each cycle
created an **SSH session and a `ps_mcp_server.py` process on the company's authoritative host**.

**Evidence.** Measured 2026-09-11 18:01–18:04: on the Yoga the `ssh.exe` child of the phone engine had age
31 s and was replaced repeatedly; on `secratary`, `sshd-session: zabz@notty` ×4 with ages 20–50 s and two
`ps_mcp_server.py` processes appearing fresh. When the path recovered (`tailscale ping` → pong in 51 ms,
ssh handshake 1.3 s), the bridge **stabilised immediately** — same pid, age climbing 85 s → 131 s.

**What it is NOT, and this matters because I nearly wrote it down wrongly.** I first attributed an elevated
load average (5.68) on the authority to this, and that was **false**. The load was a **scheduled snapshot**:
at `18:00:01` a `tar … -czf personal-secretary-runtime.tgz` with a `gzip` at **81% CPU** was running, and the
two bridge pythons were at **0.4% CPU each**. Two processes appearing twice a minute cannot produce load 5.7.
*Rule applied too late:* L51 again — check the claim, not the plumbing. I raised an alarm about my own change
before looking at `ps` output for what was actually burning CPU.

**Bounded, not runaway** — and this is documented client behaviour, not a defect in the row:
`dsh-mcp-client` reconnects with delays doubling 500 ms → **30 s ceiling**, keeps the last known tools listed
during the outage (calls fail rather than disappear), and after **ten consecutive failed attempts** removes
the tools and stops until the config is reloaded. A server that stays connected resets the counter. So a
short outage costs ~2 SSH connections and ~2 process spawns per minute, then gives up cleanly.

**Cost.** Small per incident, but it is load on the *authoritative company host caused by a client outside
it*, invisible to the owner, and it recurs whenever the Yoga is on a flaky network — which is normal for it.
The deeper cost is architectural: the correct-data fix put a network hop in the critical path of the
company's own tools.

**Fix, in order.**
1. **Move the phone's engine onto `secratary`** (Phase 4, already planned) — then the bridge is a **local
   stdio child** and there is no network hop at all. The only network element left is the phone's connection
   to the engine, which cannot spawn anything on the host if it drops.
2. **For workstation sessions, use Streamable HTTP, not ssh stdio.** `dsh-mcp-client` supports a
   `StreamableHttp` transport, and its documented behaviour is the discriminator: *"an unreachable HTTP server
   is retried per call rather than respawned by the supervisor."* An outage then costs failed calls, not
   processes on the server. This needs the MCP server to serve HTTP (FastMCP supports it) and a small
   always-on unit on the authority — a real but contained piece of work.
3. Until (1) or (2): know that a network blip from a workstation spawns short-lived processes on the
   authority. Not dangerous, not silent, but not something to leave in place once the owner depends on it.

## P18 — A broken plugin in the composer takes the entire interface down

**Symptom.** Every DSH window showed `HARNESS / Failed to load plugins / web boot: 1 entry did not activate /
dsh-plugin-cost: pending (waiting for services: ...)` — no composer, no session list, no app. The plugin that
broke was a **cost pill**, which nobody needed in that moment.

**Evidence.** 2026-09-11, both the fleet engine on 3099 and the desktop's own engine. Root cause: the client
half declared dependencies the browser context never provides (two package ids in `dsh.client.inject`, then
`exports.inject = { required: [], optional: ['slots'] }`), and the loader holds an entry at `pending` until
every declared name resolves. See L38.

**Cost.** The owner's working interface, for hours, because of an optional decoration.

**Fix applied.** `plugin-cost` now declares no client dependencies and reads the Slot registry with
`ctx.get('slots')`. Its client entry is rebuilt; the cost bundle is unmounted in the local profile until the
pill is re-verified, because the interface had to work before the decoration did.

**Fix not applied (the real lesson).** Nothing warns a plugin author that a wrong name is fatal. The two
cheap guards: a build-time assertion that every name in `dsh.client.inject` is a service some shipped client
package actually provides, and treating a plugin entry as **non-fatal at boot** — a pending or failed entry
should surface a notice in that plugin's own surface, not an assertion that blanks the page. The second one
is an upstream change; record it as such rather than working around it.
---

## P29 — Every customer channel is harvested by hand, so it all arrives a day late

**Symptom.** Texts and calls reach the database long after they mattered. Median call capture lag
**17.5 h**; SMS rows observed **8 h** behind; the newest SMS at one point was 17:50 while the clock
read 19:30. The owner is answering customers from his phone, so the *business* is fine — but every
system that is supposed to help him is reading yesterday.

**Evidence.** `comms_freshness` on the authority (kernel commits `96406d9`..`97cfe81`):
`call_capture_lag_hours = 17.5`, `sms_stale_hours = 1.6` (and 8 h earlier the same day).
`crontab -l` on `secratary` contains **no** Dialpad entry; `standing_work_orders` has none either.
`dialpad_sms_cache` has 127,632 rows, so the crawler works — nothing calls it.

**Cost.** A live example from the crawl: customer `(848) 480-5115` asked *"Did you order the screen?
Because otherwise it will for sure not come until the end of the [week]"* — and the owner's own reply
in the same thread reads *"I still can't get through to my boss"*. The relationship is real and
current; the tooling sees it eight hours late, if at all.

**Fix — HALF APPLIED 2026-09-11 20:30.** The call half is done: `scripts/dialpad-harvest-cron.sh`
runs `*/30` on the authority under `flock`, verified by an autonomous run at 20:01:36Z (236 calls,
0 errors, 93s). Call staleness **10.0h → 21m**. `comms_freshness` enforces it via a heartbeat file
(`~/.dialpad-harvest.last_run`), because `dialpad_call_full.fetched_at` is INSERT-only and cannot
report a healthy pass (L114).

**Still open: the SMS half.** `dialpad_sms_cache` message bodies come only from
`dialpad_webcrawler` (Playwright, logged-in profile). Nothing calls it, and it was NOT scheduled,
because refreshing a live business account's browser auth unattended is a risk that should be taken
deliberately rather than by a scheduler. The 30-day lag median will keep showing ~17.5h until the new
cadence works through; it is reported, not enforced, so it cannot raise a false alarm while converging.


## P40 — A broken phone link is detected but routed to nobody
**Symptom.** `check_phone_endpoint` now fails loudly (HIGH) when the phone path breaks, and `run-sentinel.sh`
records it — but nothing delivers a finding to a human. The runner is explicit that routing findings is "the
inbox's job (design §3.3), and Phase 2 is not built yet", and it deliberately never mails, to avoid recreating
the alert fatigue that buried the 7 held critical messages. So the owner still learns about a broken phone by
holding the phone — which is exactly how he learned tonight.
**Evidence.** His two messages tonight ("it doesn't work so well", "how do i use it") were both questions a
machine already had the answer to, hours before he asked. Kernel: `/home/zabz/ceo-kernel-var/latest.json`,
`summary.attention = 5`, `phone_endpoint` present and green only after the fix.
**Cost.** The one channel that matters — him — is the one channel the sensing does not reach.
**Fix.** Phase 2 inbox: findings to a single digest, deduplicated by check+severity, escalated only when a check
stays failing across N samples. The honest intermediate is one line in whatever summary he already reads.

## P41 — Only the phone path has behavioural proof; every other endpoint has layer checks
**Symptom.** `probe-phone.py` asks the questions that matter (does a cold visitor get signed in, does the
document load, does the websocket upgrade, does real HTTPS work from outside). Everything else in the fleet is
still judged by proxies: a process is listening, a config file exists, a service is "active". Tonight proved
that class of check can be green through a total functional failure.
**Cost.** Unknown, and that is the point — the other endpoints have never been tested the way this one now is.
**Fix.** Generalise `probe-phone.py` into `probe-endpoint.py` over a small registry (the API on :8002, Home
Assistant, the Gmail bridge, the public tunnel hosts), each entry declaring its own cold path and expected
shape, all writing the same status-file contract the kernel already reads.

## P42 — I verified the phone with my client, not his
**Symptom.** Twice I reported the phone link working, with evidence: a 7/7 probe, an outside-in HTTPS check, a hand-driven
session. Twice he came back with the same 401. Every one of my checks ran from a terminal, on a fresh connection, through a
path his browser does not use — while the real failure lived in the two things every one of those checks bypassed: Tailscale
Serve's pooled connection to the gate, and the stale cookie/token his Safari actually carries.
**Evidence.** `gate.log` shows one request for a navigation that made four; the same navigation through Serve returned 200
for a clean client and 401 for a dirty one; after the fix, 10/10 plus a real browser landing the page on all four paths.
**Cost.** Two rounds of "it's fixed" that were not, and a visibly annoyed owner — the exact failure mode this system's
provenance rules exist to prevent, applied to myself instead of to a database.
**Fix.** Already partly mechanised: the probe now carries a dirty-client check, a reused-connection check, and an
outside-in check through Serve. The standing rule is the durable part: **an acceptance test for anything the owner touches
must run through the same proxy, on the same path, with the same dirty state his device has** — and passing from a clean
terminal client is not evidence.

## P43 — Nothing could name where the owner is, and the entity that should have looked broken looked normal
**Symptom.** Asked to know when he is home and when he is at the office, the company had a genuinely good *office* presence
system (BLE triangulation, mmWave occupancy, PIN entry, cameras — all real, fused into `input_boolean.phoenix_user_is_here`)
and **no way at all to name "home"**. HA's `zone.home` is centred on the **shop**, so HA's most authoritative-sounding
reading, `person.eliyahu_zabrowsky = not_home`, means only "not at the shop" — and even that is fed by a **LAN-MAC tracker**
(`device_tracker.00_08_22_c8_b2_fb`, his flip phone) which goes blind the moment he leaves the office Wi-Fi.
**Evidence.** `sensor.iphone_15_location_permission = 'Not determined'` and `device_tracker.iphone_15_2` with
`source_type: gps`, `state: unknown` and **no coordinates** — while `sensor.iphone_15_battery_level` and `app_version` read
fine, i.e. the app was connected and healthy and the tracker was *silently* empty. His other device has the permission
(`sensor.zabz_waze_location_permission = 'Authorized when in use'`) and reports a real fix.
**Cost.** Every presence-driven behaviour — quiet hours, notification timing, "is he in the shop" autonomy — has been blind
to the half of his life that is not the shop, for as long as the app has been installed. Nothing alarmed, because an empty
tracker raises no error and looks like any other entity.
**Fix.** (1) The permission (owner action, one tap); `external_url = https://ha.abletelsolutions.com` is already live, so
the fix reports from anywhere. (2) Treat **absence of a GPS fix as the alarm**, not its value — a `device_tracker` with
`source_type: gps` and no coordinates is a fault, and this is P2's "nothing watches outcomes" precisely. (3) The home zone
is **learned** from the first real fix, so the harness never has to ask the owner for his address.
**Ranking note.** Appended at the tail for consistency with P41/P42, but it belongs high, beside **P2**: it is the same
failure (a silent empty reading) and it disabled a whole class of behaviour rather than one feature.

## P44 — The live checkout on the authority is diverged, so nothing can be deployed safely
**Symptom.** `~/personal-secretary-mvp` on `secratary` — the host running `secretary-api.service` — is not a clean
follow of `origin/master`. Measured 2026-09-11: local HEAD `99738ebe` is **69 commits behind** `origin/master`
(`fbf73b672`) and **3 commits ahead** (unpushed: `99738ebe`, `603e49ed`, `ca893e4b`), with **15 locally-modified files
that overlap the incoming changes** — `app/main.py`, `app/services/home_assistant.py`, `app/agent_bus.py`,
`app/services/agent_worker.py`, `app/services/unified_memory.py`, `scripts/server/backup-data.sh` and more.
**Evidence.** `git rev-list --count HEAD..origin/master` → 69; `origin/master..HEAD` → 3; `git merge-base --is-ancestor
HEAD origin/master` → NO; the overlap set from `comm -12`. Found only because I checked *before* pulling rather than after.
**Cost.** No change can be shipped to the authority without either a merge that may mix another session's uncommitted
work into the live host, or a reset that would destroy it. So every new capability stalls at "verified from `/tmp`" —
including the presence resolver, which is verified running on the host from a temp path and is not deployed. This is the
deployment equivalent of P3's divergent copies, and it silently caps what the whole system can deliver.
**Fix.** Needs care and a decision, not a script: (1) on `secratary`, get the 3 unpushed commits' intent reconciled —
either pushed or discarded *by whoever authored them*; (2) stash named by session, never a bare `git checkout .`; (3) then
`git pull --ff-only` and restart `secretary-api.service` under observation. **Not attempted in this session** because
`git checkout`/`reset` on that host is exactly the class of action that destroys other people's work, and I cannot tell
which of those 15 modified files are deliberate in-flight edits.

## P45 — Every threshold in the kosher filter's visual path is a guess, because no labelled frames exist
**Symptom.** The five modesty attributes (sleeves, hemline, neckline, hair covering, tight fit) and the cascade's
escalation band are all decided by thresholds chosen from research, not from measurement. There is **no labelled set of
frames**, so no threshold can be shown to hold a risk level, and the gate has no finite-sample floor to stand on.
**Evidence.** 2026-09-11 research (`kosher-filter-ai/docs/research/015`, `016`, `017`): raw model softmax is an *invalid*
gate (ECE up to 0.496; accuracy collapsing 0.99 → 0.22 while stated confidence stays flat at 0.87–0.90), which is what
makes calibration mandatory rather than optional. Conformal risk control gives a guarantee only against labelled data —
`1/(n_pos+1)` is the floor, so **under 1% risk needs ≥100 positive examples per attribute** and an α below the floor has
no power at all. Cost of real labelling, researched: **$4,000–8,000 per 1,000 images** with domestic annotators (L58).
The company has **zero labelled frames today**.
**Cost.** The product's central claim — "we catch it and we do not miss it" — is unfalsifiable as built, and the failure
mode it creates is the expensive one: a confident wrong number shipped to a customer (the class P3 exists to prevent).
It costs nothing *yet* only because no customer is running it.
**Fix.** Cheapest honest path first, and it needs no cash: build the labelling harness, then have ~200 real frames
labelled in-house — about an hour of a person's time, and the shop's own traffic is the distribution that matters, since
no public dataset matches it. 200 frames with ~40 positives per attribute puts the floor near 2.4%, enough to learn
whether the cascade can hold a usable risk level at all: evidence before a purchase order. Decide about a paid
1,000-frame round only after that. Needs **one owner answer** (money) — asked 2026-09-12, see `QUESTIONS.md`.


## P43 — The phone path cannot say which device connected
**Symptom.** The owner asked, on 2026-09-11, whether the phone work was finally live. I could prove *what* happened — the gate
signed a cold visitor in at 20:29:32 and the prompt I was answering was posted through the gate at 20:29:52 — and could not
prove *which device* did it. Serve rewrites every tailnet visitor to 127.0.0.1, `phone-gate.py` logs no User-Agent, and there
is no second source: `grep -rln userAgent` across the engine's server and web sources returns nothing, and a session file's
`request/header` is the LLM request config, not the client.
**Evidence.** `~/.dsh-phone/gate.log` (no UA field in any line); the greps above; `journalctl -u tailscaled | grep
connsInFlightByClient` showing the iPhone's own IP reaching Serve at the same minutes — which is corroboration, not identity.
**Cost.** The phone stream's last acceptance step — *the owner's own phone* — stays unverifiable by me three sessions running
(P42), and every future "is it my phone or my laptop?" question is answered by inference.
**Fix.** (1) `phone-gate.py` records User-Agent and what Serve forwards (`Tailscale-User-Login`, `X-Forwarded-For`, if
present) on every request it decides on — five lines, no new dependency. (2) Apply it with a restart **only when no socket is
established on :3086**: the page holds `/api/remote.mux` open and the dsh web client has no reconnect logic, so restarting
under the owner silently kills his page. (3) `probe-phone.py` then drives an iPhone User-Agent through Serve, so the probe's
pass statement is about his device class rather than my curl.

## P44 — Two sessions can rewrite the same file inside the same minute, and neither can see the other
**Symptom.** While answering a question about the phone, another session committed to `scripts/phone-gate.py` at 20:31:43 and
again at 20:32:24, having rewritten the file at 20:31:46 in this checkout; the only signal available to me was git (reflog
pulls at 20:31:06, 20:31:46, 20:32:27 and the file's mtime). Nothing in the journal said the file was held.
**Evidence.** `git -C ~/harness-config reflog --date=iso`; `ls --time-style=full-iso scripts/phone-gate.py` → 20:31:46; the
three commit subjects landing "mobile layer / re-frame the document / keep the rail".
**Cost.** A five-line change to that file was ready and would have raced a live writer — the real cost is not the lost edit
but a conflict or a blocked `--ff-only` pull on the *other* session, which stalls work I cannot see.
**Fix.** Before touching a shared artefact, read the reflog (L139). Then claim it in one line at the top of `HANDOFF.md` —
`<path> — held by <session/host> until <time>` — and release it when done. Same failure class as P13 (`git add -A` sweeping
another session's work); this is its file-level twin and the claim line is the cheap half of a fix.

## P45 — The harness ships a desktop layout and the phone gets it shrunk
**Symptom.** At 393px the app renders its desktop composition: nine controls below the 44px touch minimum (rail icons
36x36, Commands and Add-attachment 28x28, Send 34x34, Choose-workspace 162x28), a composer field computed at 13.33px
(iOS Safari auto-zooms the whole page when it takes focus), zero `safe-area-inset` rules anywhere in the shipped CSS, and
a sidebar that in flow squeezes the content column from 337px to 113px when opened.
**Evidence.** Measured on the live app; the fixes and the before/after are in `journal/WINS.md` W23 and
`docs/dsh-mobile/evidence/phone-mobile-*`.
**Cost.** The owner's own words: *"since it's a chrome window, it's not optimized for a phone interface."* He is the only
user of this surface and it was designed for a desktop.
**Fix, partial.** `assets/mobile.css`, injected by the gate, fixes tap size, the zoom trigger, safe areas and the open
drawer. What it cannot fix is state: selecting a session in the drawer leaves the drawer open (the app's own behaviour),
and a phone-first composition wants the rail gone and the drawer to close on navigation. The honest fix is a proper
client plugin inside the DSH package — blocked only on tooling: the `cordis_*` tools are not in this session's toolset,
so that work needs a session that has them.

## P46 — The phone still has no default workspace, and the rail costs 14%
**Symptom.** Two things the mobile layer deliberately did not solve. A conversation started from a fresh phone asks the user
to choose a workspace before the composer accepts a message (his sessions land in `/home/zabz/_scratch` once chosen, and the
harness remembers it afterwards). And the 56px rail costs 14% of a 393px screen.
**Evidence.** Measured at 393x852: rail 56px, content column 337px; the composer's send control stays disabled until a
workspace is picked. Hiding the rail was tried and reverted — it collapsed the content column to 56px (L142).
**Cost.** One extra tap on first use, and a permanently narrower transcript.
**Fix, in order.** (1) A default workspace so a new phone session is immediately usable — the harness stores the remembered
workspace client-side per profile, so this is a client-plugin job like the drawer was, not a config value. (2) Only then
revisit the rail: it needs the app's own layout to give the width back, which may mean the plugin asks the sidebar to
collapse rather than a stylesheet hiding it.

## P47 — Code the business depends on lives untracked on the box that runs it

**Symptom.** The Shabbat/Yom Tov power automation — the thing that releases the office door and cuts HA + all
cameras for every Shabbos and Yom Tov — existed only as untracked files on `secratary`. `git ls-files | grep -i
shabbat` returned nothing. Same class as the nine other modified-but-uncommitted files and the 71-commit gap.

**Evidence.** 2026-09-11: `git ls-files` empty for all five paths; `git status --porcelain` showing them as `??`;
HANDOFF 19:45 entry recording the same checkout as "55 commits behind with nine uncommitted files, 510 lines of
someone's live work".

**Cost.** One disk failure or one careless `git clean` and the automation is gone, on a night when it is running
for the first time. The archive carries a second-order cost too: nobody can review, diff or test what is not
committed, which is how 55 improvements stayed unapplied.

**Fix.** Done for this one case — commit `8490d137` on `origin/shabbat-automation-20260911`, pushed, working tree
untouched (D39). Still open as a class: the five files should land on `master` (or be merged from the side branch)
on a quiet day, and the general habit is to commit *someone else's* in-flight work to a side branch rather than
leave it as the only copy. Detect it cheaply: the CEO kernel could flag any `??` file older than a week under
`app/` on the authority, since that is exactly the shape of the loss.

## P48 — Something holds the write lock on the company database for longer than 30 seconds

**Symptom.** `POST /api/v1/owner/dsh-sessions/ingest` answered `500 {"ok":false,"error":"internal_error"}` for
about two and a half hours tonight (runs at 20:05, 21:05, 21:45), and the same class of failure hits
`/api/v1/next-stage/systems-custody/node-report`. The underlying error is `sqlite3.OperationalError: database is
locked`, raised after the connection had already waited `PRAGMA busy_timeout = 30000`.

**Evidence.** `journalctl -u secretary-api` at 21:45 →
`app/services/dsh_session_ingest.py:200` `INSERT OR REPLACE INTO dsh_session_exports` → `database is locked`.
`error_log` has 12 such rows in 21 hours; ~5 of them are this ingest route. The database
(`personal-secretary-mvp/data/secretary.db`, 2.7 GB, journal_mode `wal`) carries a `-wal` file of exactly
67,108,864 bytes (64 MiB) — the signature of checkpoint starvation, i.e. a reader or a long transaction that keeps
checkpoints from completing. `lsof` shows one python process holding ~24 file descriptors to the same database,
so a single process has many connections and `_db_lock` is only a per-process lock.

**Cost.** Silent, invisible, and it looks like health: the scheduled task exits 0, the cursor is current, and the
machine's conversations simply stop being archived until someone diffs the store against the cursor. Tonight it
cost 2.5 hours (recoverable — see L160); the same lock can fail a *user-facing* company action.

**Fix (proposed, not yet done).** 1) Find the long holder rather than guessing: log the wait time and the
`sqlite3` error on every ingest attempt (one line to `error_log`), then correlate lock windows against
`PRAGMA journal_size_limit` / checkpoint activity and the six-hourly `secretary-backup.timer`. 2) If the holder is
a backup or a maintenance job, make it WAL-aware (`.backup` API or `VACUUM INTO`, never a raw copy) so it cannot
block writers. 3) If the holder is inside the app, cut the number of write connections and make every write
transaction short — a long write transaction on a 2.7 GB database with ~300 ticks/day is the real defect.
Do **not** reach for a datastore migration on the strength of 12 errors in 21 hours.


## P49 — The machine that serves the API runs a checkout GitHub has moved 71 commits past

**Symptom.** `secratary:/home/zabz/personal-secretary-mvp` is **71 behind / 3 ahead** of `origin/master` and
carries **30 dirty files**, while `secretary-api.service` serves from exactly that directory
(`WorkingDirectory=/home/zabz/personal-secretary-mvp`, `ExecStart=.venv/bin/python -m uvicorn app.main:app`).
In the same hour, `ZABZ-TECH` committed `3bf24ea0` — "merge: origin/master (22 commits: presence, waze-mdm, dsh
ingest…)" — so the Windows host is merging and pushing work that the authority's runtime has never seen.

**Evidence.** `git rev-list --left-right --count origin/master...HEAD` → `71  3`; `systemctl cat
secretary-api.service` → the WorkingDirectory above; `git log --oneline -1` on ZABZ-TECH →
`3bf24ea0 2026-09-11 18:22:52 -0400`.

**Cost.** This is P3 for code instead of data: the same divergence that once produced a reported 45-day outage
that never happened. Two concrete harms. (a) A fix verified on the Windows host can be absent from the running
API, and nothing states which checkout is authoritative. (b) Code that is live exists nowhere but a dirty working
tree — tonight's Shabbat fix was in that state until it was rescued to `deployed-truth-20260911` (`6784354c`).
The blast radius grows with every tick the company runs from a tree nobody can reproduce.

**Fix (proposed).** Decide and record which checkout is the deployment source, then make it reproducible:
capture the deployed tree as a commit (done — `deployed-truth-20260911`), bring `master` level with
`origin/master`, and restart in a calm window. The calm-window constraint is real: a restart re-registers
`apscheduler`, and the Shabbat block is mid-holy-day with a live watchdog. Not a datastore migration and not an
emergency — a scheduled, verified reconciliation.



## P50 — `work_sessions.status` holds 40 non-status values, and nobody noticed

**Symptom.** The column is read as a status enum — completion rates, the sentinel's `tick_completion` check, and
the new honest metric all filter on it — yet it contains values that are not statuses at all: `5` (21 rows),
`2.5` (11), `4.5` (2), `3.67`, `4.43`, `4.56`, `4.81`, `4.9` (1 each), and a single `active` row created
2026-09-11T22:30:10Z. Several junk rows have `NULL` timestamps, so they predate the current writer.

**Evidence.** `SELECT status, COUNT(*) FROM work_sessions WHERE status NOT IN
('paused','completed','failed','running','cancelled','expired') GROUP BY 1` on the authority, 2026-09-11.

**Cost.** Small in volume, large in kind: it means *something* writes into this column without going through
`update_work_session`, which is the same class of defect as the completion lie — an unguarded write to a
column every metric depends on. A future reader who filters `status='5'` infers nothing and cannot tell whether
those 40 sessions succeeded. `NULL` timestamps also mean they cannot be aged out.

**Fix (proposed, NOT yet done).** Find the writer rather than patching the rows: grep for every INSERT/UPDATE
touching `work_sessions.status` outside `app/database.py`, and add a CHECK-constraint or a single writer to make
the enum real. Do not delete the 40 rows — they are evidence of the defect, and the rule is never destroy data.



## P51 — The owner has been read nothing since 2026-07-19, because a spam fix blocked *all* of it

**Symptom.** `owner_message_queue` holds 595 undelivered rows and 742 ever-sent. The last successful send was
`2026-07-19T02:32:33Z`; sent per month is May **402**, June **283**, July **20**, August **0**, September **0**.
The cause is one file: `personal-secretary-mvp/data/OWNER_SMS_KILL_SWITCH` (mtime `Jul 20 17:57`), whose own
text reads *"Created 2026-07-14 by Copilot per owner request. While this file exists, ALL owner SMS are blocked.
The CEO was stuck in a loop sending 28+ 'URGENT' texts."* It is honoured in four modules, so it is not a stray
flag: it is the designed gate, and it was never lifted.

**Evidence.** The file and its text; the four call sites (`app/autopilot.py:7940`, `app/tool_factory.py:1772`,
`app/services/notification_manager.py:349`, `app/chat_action_owner.py:237,457`); the monthly send counts above.
A second, independent gate compounds it: `settings_overrides.owner_sms_min_urgency = "urgent"` (2026-05-04),
so `normal` messages can never pass even with the switch removed. Transport is healthy — Twilio answers
`status: active` with the same credentials.

**Cost.** Everything the company concluded for 54 days reached nobody: 167 held owner items, including a
**Gusto payroll notice saying payroll may be blocked for insufficient funds** (#1294, 2026-08-05), **7 critical
rows**, and two Google password-breach alerts. This is P2's worst instance — not "nothing watches outcomes" but
"outcomes are watched, recorded, and then swallowed". It is also the most plausible single explanation for the
Copilot usage collapse after April 2026: the owner was receiving nothing while the company believed it was
talking to him.

**Fix.** Do **not** simply delete the file — that restores the 28-text loop that caused it. Replace the
all-or-nothing switch with what the original fix should have been: a **rate limit plus dedup in front of the
queue** (at most N owner SMS per hour, identical bodies collapsed, `urgent` and above). That makes a loop
impossible *without* silencing payroll. Note the corrective logic already exists and is simply unused: the
flush marks a blocked message `held` rather than dropping it, so nothing is lost while the gate is shut.

