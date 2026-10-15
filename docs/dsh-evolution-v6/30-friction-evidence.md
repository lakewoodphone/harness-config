# 30 — Friction evidence, round 6

Built by mesh child **R6-FRICTION** on host `zabz-tech` (Windows NT 10.0.26200),
**2026-10-15**, dispatched by the manager session on ZABZ-YOGA.

This file supplies, for each of the eleven frictions named in the round-6 brief, four things the
round-4 register does not carry: three verbatim owner quotations (instead of one), **the mechanism
in this harness that produces the friction**, whether the instruction surface has a rule today, and
the measurement that would show it had fallen. `30-proposed-rules.md` is the paste-ready rule block.

---

## 0. Provenance, and what was re-derived

| what | where it was read | how |
|---|---|---|
| the 19 reader files | `/home/zabz/evolution-corpus-v4/readers/R01.md`..`R19.md` (734,536 B) | copied to `_scratch/r6-friction/readers/` with `scp -r`; parsed by `count_frictions.py` |
| the round-4 register | `/root/work/07-pain-register-v4.md` (69,564 B) | copied to `_scratch/r6-friction/` |
| the round-4 handoff | `/root/work/HANDOFF-ROUND4.md` (19,211 B) | copied |
| the census | `/home/zabz/evolution-corpus-v4/CENSUS-v4.md` (39,419 B) | copied |
| the reader brief | `/home/zabz/evolution-corpus-v4/READER-BRIEF.md` (5,946 B) | copied |
| the persona | `C:\Users\ezabz\code\harness-config\presets\zabz\agent.cordis.yml` (54,551 B) | `read` |
| the loader | `scripts/make_zabz_preset.py` (50,000 B) | `read`, and imported with `importlib` (its `main()` is behind `__main__`) by `persona_drift.py` |
| the engine tool-result path | `~/.dsh/engine/node_modules/@deepseek-ai/dsh-tool-pwsh/lib/index.js`, `dsh-tool-bash/lib/index.js`, `dsh-shell/lib/index.js`, `dsh-compaction-tool-result-pruner/lib/index.js` | `read` / `grep` |
| the harness checks | `scripts/harness-verify.ps1` (19,821 B), `scripts/sync.py` (41,017 B) | `read` / `grep` |

### 0.1 The paths the brief gave do not exist

The brief says to read `docs/dsh-evolution-v6/PROGRAM.md` §2 and §5, and
`docs/dsh-evolution-v4/07-pain-register-v4.md`, `CENSUS-v4.md`, `HANDOFF-ROUND4.md`.
**None of `docs/dsh-evolution-v4/` or `docs/dsh-evolution-v6/` exists on this node or on the
authority.** The evidence:

```
$ ls /home/zabz/evolution-corpus-v4/                      # on secratary-cloud
CENSUS-v4.json  CENSUS-v4.md  OWNER-ANALYSIS.md  READER-BRIEF.md  ...  readers/ ...

$ find / -name '*pain-register*' 2>/dev/null              # on secratary-cloud
/root/work/07-pain-register-v4-analysis.py
/root/work/07-pain-register-v4.md
/root/work/07-pain-register-v4-build.py
...

$ grep -rl 'dsh-evolution-v6' /root /home/zabz --include='*.md' --include='*.py' --include='*.json'
(no output)
```

`docs/` in the harness-config checkout has no `dsh-evolution-v4` or `dsh-evolution-v6` directory on
**any** branch; it holds `dsh-evolution-v2/` only, and that is untracked on this node
(`?? docs/dsh-evolution-v2/`). The round-6 brief's §2/§5 of a v6 PROGRAM could therefore not be read
at all — **that is a gap in this deliverable, not a thing I worked around.** The register itself
records the same failure one round earlier: "The path the brief gave does not exist on the
authority" (register §1, line 20).

### 0.2 The brief says "ten frictions" and lists eleven

> "For each of these ten frictions — `tool-failure` 302, `correction` 132, `wrong-data` 116,
> `repeated-work` 102, `frustration` 96, `no-verification` 76, `env-hostile` 74,
> `restart-agent` 73, `context-loss` 56, `ignored-instruction` 53, `format-unreadable` 40"

That is **eleven** ids. I did all eleven.

---

## 1. The numbers, re-derived

I re-derived **all eleven counts myself**, not three. Parser: `_scratch/r6-friction/count_frictions.py`
(reads only `readers/R01.md`..`R19.md`; one session record per `## <uuid>` heading; frictions read
from the `frictions:` line, severity from `severity:`, outcome from `outcome:`).

The command and its output, verbatim:

```
$ python count_frictions.py
readers=19 sessions=1008 tagged_sessions=623
friction                  n blocking   sev4-5  sev 1/2/3/4/5
tool-failure            302       76       66  10/149/77/39/27
correction              132       32       43  1/39/49/28/15
wrong-data              116       38       44  0/24/48/23/21
repeated-work           102       30       39  1/24/38/26/13
frustration              96       43       70  0/2/24/34/36
no-verification          76       25       26  0/20/30/12/14
env-hostile              74       22       14  3/29/28/12/2
restart-agent            73       34       34  0/12/27/20/14
context-loss             56       23       26  0/10/20/14/12
ignored-instruction      53       26       38  0/2/13/18/20
format-unreadable        40       15       16  0/10/14/5/11
```

Every count, every blocking count and **every severity mix matches the round-4 register line for
line** (§3 table and §4 sections). The register also reports `sessions: 1008 | with a friction tag:
597 | without: 411 | tags: 1364`; a second pass shows why my first figure of 623 disagrees — it did
not exclude the literal `none`:

```
$ python -c "...token census..."
sessions 1008 tags 1364 blank 311 dash 74 literal-none 26
tagged_sessions(excl none/dash/blank) 597
  tool-failure 302 ... bad-prioritisation 9     (exactly 20 ids, no extras)
```

597 confirmed, 1364 tags confirmed, 311 blank / 74 `-` / 26 `none` confirmed (the register's "100
written as a literal `-` or `none`" is exactly 74 + 26).

### 1.1 Third independent check — the register's own script

```
$ ssh secratary-cloud 'cd /home/zabz/evolution-corpus-v4 && for p in tool-failure:302 repeated-work:102 format-unreadable:40; do f=${p%%:*}; n=${p##*:}; python3 /root/work/07-pain-register-v4-check.py "$f" "$n" >/dev/null 2>&1; echo "$f exit=$?"; done'
tool-failure exit=1
repeated-work exit=1
format-unreadable exit=1
```

Its printed output for one of them:

```
pain: tool-failure
target (count recorded in the register): below 302 sessions
measured now: 302 sessions, 76 of them blocking (outcome failed/partial/abandoned)
FAIL: tool-failure is still at or above target (302 >= 302) -- pain OPEN.
```

So **three independent parsers — the register's, the check script's, and mine — agree exactly.**
The register's §4 claim that all its checks exit 1 is also confirmed for the three I ran.

---

## 2. The eleven frictions

Each section: the numbers, three verbatim owner quotations, the mechanism, the rule that exists
today, the smallest change, and one measure. Quotations were mined from the reader files and then
**verified by me, byte-for-byte, by script** (`verify_quotes.py`, 33 records):

```
$ python verify_quotes.py
records=33  verified=33  failed=0
distinct sessions used: 25 of 33 records
sessions reused across frictions: 7
```

Each quotation was checked three ways: the exact string appears in the named file, the session it is
attributed to really carries that friction id, and its severity and outcome match. **33 of 33
passed.** Seven sessions legitimately supply more than one quotation, because 1,364 tags sit on only
597 sessions (2.3 tags per tagged session) — reuse across frictions is the corpus's own structure,
not padding.

### 2.1 `tool-failure` — 302 sessions (30.0%), 76 blocking (25.2%), severity 10/149/77/39/27, 66 at 4–5, mean 2.75

1. `558100fd-de2a-4b5d-a8c6-03510ca28f72` · `readers/R10.md` · severity 5 · partial
   > Spawning child agents and sub agents and the whole mesh agent thing is constantly failing whenever they try to spawn their own agents.
2. `545d8e84-2ca6-4182-a107-da4ed581ef09` · `readers/R11.md` · severity 5 · completed
   > Why do you keep crashing? What’s going on?
3. `e50ad938-dd58-4a3a-b88f-2f85eacb4a76` · `readers/R02.md` · severity 5 · partial
   > i think you froze

**THE MECHANISM.** The engine deliberately refuses to classify a failed command as a failure.
`dsh-tool-pwsh/lib/index.js` lines 129–136:

> "stdout, a marked stderr section, sandbox denial/runner-failure markers … then exit-status
> markers. **Non-zero exits are reported, not errored — the model decides how to react; only
> infrastructure failures (spawn errors, aborts) surface as isError results.**"

Line 172 is the whole of it: `else if (result.exitCode !== 0) markers.push(\`[exit code: ${result.exitCode}]\`);`
then line 175 returns it as the tool result text. **The tool call is a success as far as the harness
is concerned** — `isError` is false, no branch changes, no retry, no state. The only difference
between a passing and a failing command is one appended line at the end of the text. `dsh-tool-bash`
is byte-for-byte the same story (its own comment at lines 141–143).

That is the mechanism, and it is not incidental: everything else in this harness that it *does* care
about gets a *marker plus an action*. A sandbox denial gets a denial marker **and** an escalation
hint ("the same-turn escalation hint after a denial marker", lines 150–152, 165–168). An
infrastructure failure gets `isError`. A non-zero exit gets a string.

Two compounding facts make the string easy to miss:

- **The middle of the output is deleted.** The preset mounts
  `@deepseek-ai/dsh-compaction-tool-result-pruner` with `thresholdChars: 5000, headChars: 2500,
  tailChars: 700` (`presets/zabz/agent.cordis.yml` lines 358–363). The pruner's own marker is
  `"\n\n[... tool result middle pruned ...]\n\n"` (`dsh-compaction-tool-result-pruner/lib/index.js`
  line 8). For any tool result above 5,000 characters the middle is replaced by that literal string;
  a failing command whose error text sits between the head and the tail arrives as head, a prune
  notice, tail, and a bare exit code. The owner's surface prunes **sooner than stock** — the engine
  default is 8192/4096/1024 (lines 11–13), so the preset tightens the threshold by 39%.
- The same output is truncated to its tail with a spill path when it overflows the ring
  (`streamText`, lines 141–144), so the head can go too.

**Does the instruction surface have a rule today?** **Yes** — persona lines 120–128:

> "**When a tool fails, read the failure before you act on it.** Read the exit code and quote the
> tool's own diagnostic. A `[exit code: N]` marker is a report, not a verdict … A missing dependency
> (`rc=127`, `not found`, `not configured`) is not retryable: escalate with the exact stderr. Retry
> once with a different tool or host before falling back, and never report a command's failure as a
> fact about the system."

The rule is 788 characters long, is sixth-largest block in the persona, and is **asking the model to
read a diagnostic the harness has already deleted the middle of** — and it is attached to a tool
result that the harness has already marked as a success.

**Smallest change to the surface.** Make the exit code a *state the turn must discharge* rather than
a line the turn may read: require the exit code and the failing line in the agent's own next words
before the next tool call. That is one sentence added to the existing rule and it is self-measuring,
because the transcript either contains that sentence or it does not. (An engine change — never
middle-prune a result whose tail carries a non-zero exit marker — would be strictly better, and is
recorded here as the real fix; it is outside the surface.)

**The measure.**
`python3 /root/work/07-pain-register-v4-check.py tool-failure 302` (today: exit 1, `pain OPEN`).
Live proxy: count sessions in which a `[exit code: N≠0]` or `[timed out` appears and the *next*
assistant message contains neither `N` nor the failing line.

### 2.2 `correction` — 132 sessions (13.1%), 32 blocking (24.2%), severity 1/39/49/28/15, 43 at 4–5, mean 3.13

1. `72c9fd6e-26b8-4ca3-998e-4a9c559fd17a` · `readers/R17.md` · severity 5 · partial
   > actually it's 95 instead of the usual more like 65 or 70, we went up in price since yisroel left and i have to do the soldering also say that it doesn't always get fixed, but 50 non refundable is required deposit, you forgot that also
2. `d772db00-c884-48e1-acf2-cb95cad2992d` · `readers/R01.md` · severity 5 · partial
   > what the hell did you just do, 4.1 flash is better and cheaper than 4 pro
3. `18bba526-91c3-4904-82e1-547a17cd3be3` · `readers/R18.md` · severity 5 · partial
   > no silly i measured withthe battery out

**THE MECHANISM.** A correction is the owner supplying a fact the session asserted wrongly. The
harness produces this by having **no fact-check path at all** — there is no store of the shop's
prices, no schema the agent must read before quoting, and no gate between "the model believes X" and
"X is in the message". The two surfaces that could hold the fact both lose it:

- the conversation window, via `compaction-basic` at `thresholdRatio: 0.7` (preset lines 333–344),
  which replaces the history with a summary once the window is 70% full;
- the tool results, via the pruner above.

So a session that runs long enough to matter **forgets the price it was corrected on in the same
session** and can be corrected on it twice. The estate knows this failure class by name — the journal
carries 25+ entries tagged `wrong-data`, and `journal/entries/pain/P3798.md` says it plainly: "This is
the `wrong-data` failure (11.2% of sessions, the most …)". Nothing in the harness converts "the owner
corrected this" into "this is now a fact the next turn must read".

**Does the surface have a rule today?** **Yes** — rule **7b**, persona lines 60–64, added
2026-10-14:

> "**7b. When he corrects you, the correction is the requirement.** Restate it in one line, check
> whether the same error exists elsewhere and fix it there too, then continue. Do not defend, do not
> apologise twice, do not ask whether he is sure. … (Measured 2026-10-14: `correction` 5.74% +
> `frustration` 6.58% = 12.3% of his turns, and no rule addressed either.)"

Note what that citation does: it reports `correction` at **5.74%**, while the round-4 register
measures **13.1% of sessions**. The two numbers are not the same measurement (turns vs sessions, and
an older corpus), which is why the rule reads as smaller than the pain.

**Smallest change to the surface.** Rule 7b has the teeth ("check whether the same error exists
elsewhere and fix it there too") but no trigger. Give it one: the correction must be **written down**
— into the journal or the case file — in the same turn it is received, because the only thing that
survives a compaction is what went to disk.

**The measure.** `python3 /root/work/07-pain-register-v4-check.py correction 132` (today: exit 1).
Live proxy: sessions where the same correction is received twice, or where a fact is re-quoted after
a compaction event.

### 2.3 `wrong-data` — 116 sessions (11.5%), 38 blocking (32.8%), severity 0/24/48/23/21, 44 at 4–5, mean 3.35

1. `24b7eadb-888f-4ef8-8465-b3a29b451803` · `readers/R17.md` · severity 5 · partial
   > Okay, it's fixed. But the question is, if you miss this and claim that everything is migrated properly, what else did you miss?
2. `1c6dc139-3e45-433a-94b4-bd07e60cef09` · `readers/R19.md` · severity 5 · partial
   > what the heck are you talking about you are anyways not allowed to automatically send a text, and i tell you explicilty when to send them through dialpad and they get sent out
3. `62c23a05-b0ff-4f15-a4e7-648c249bba6b` · `readers/R09.md` · severity 5 · completed
   > give me exact instructions and don't mess me up this time like you did with the ferry

**THE MECHANISM.** The surface has the longest, most explicit rule in the persona for this one, and
the harness still has no mechanical path from a reading to a claim. Three concrete enablers:

- **`read`-shaped tools return content with provenance the model must volunteer.** Nothing in the
  tool result is labelled "this is a cached/mirrored/replicated copy". The persona has to warn that
  "a file's mtime is not its content's freshness" (line 94) — a warning that exists because the
  harness presents a stale copy and a fresh one identically.
- **The pruner deletes the provenance.** A row set larger than 5,000 characters loses its middle,
  which is usually where the header/count/timestamp lives.
- **`compaction-basic` rewrites the history into a summary without a provenance field.** A number
  that was read with its source at step 40 arrives after compaction as a number.

**Does the surface have a rule today?** **Yes, at length** — "The one you must not get wrong"
(lines 80–115), four bullets plus the measurement rule. Its key sentences:

> "**Every statement about what you did carries the command and its output line, or the file and its
> mtime, or the row and its timestamp.** 'Fixed' is not a result; the exit code is."
> "**A reading is not evidence until you know its source and its age.**"
> "**An empty result is a refusal, not health.**"
> "**Never complete something you have not run.** … the correct report is 'not verified'."

**Smallest change to the surface.** Nothing needs adding; something needs **removing**. The block is
860 + 108 + 115 + 117 + 120 characters spread across five separate places in the persona with
overlapping content ("Provenance, always", "Verify, do not assume", the measurement rule, and the
four bullets all say versions of the same thing). Collapse them to one rule with one test:
*every number in a message has its source in the same sentence.*

**The measure.** `python3 /root/work/07-pain-register-v4-check.py wrong-data 116` (today: exit 1).
Live proxy: count of numeric assertions per session with no adjacent command, path or row reference.

### 2.4 `repeated-work` — 102 sessions (10.1%), 30 blocking (29.4%), severity 1/24/38/26/13, 39 at 4–5, mean 3.25

1. `b9810e28-58db-409d-aec1-6edb7e553daf` · `readers/R16.md` · severity 5 · completed
   > i thought we already got rid of kosher filter, you went against the rules and installed it on production devices when it wans' ready and you werent told to i thought we got rid of it already
2. `8587008c-4778-4429-84fa-9827bd35285b` · `readers/R18.md` · severity 5 · completed
   > you didn't read teh docs and info, you don't write lpt number and you don't put on the drn screen, what the hell are you doing, can you analyze our actual sales info and docs and scripts for the lpt waze devices before doint all this
3. `4772de74-452e-493f-9528-d0a970851749` · `readers/R13.md` · severity 5 · partial
   > what the heck you've said this in the past, waze and dialpad we have vpp for and i just got vpp for tailscale, you don't need to be signed in for this this is one of the biggest mistakes you keep on making

**THE MECHANISM.** Every session starts blank (persona line 172: "You have no continuous memory.
Every session starts blank."). The only defence is that the agent *searches before building*, and the
rule names a search the agent must already know how to aim:

> "Before starting a piece of work, spend one read asking whether it has been done: `journal.py
> search "<the area>"` and `newest handoff`." (lines 102–105)

Two problems in that sentence. First, `"<the area>"` is the thing the agent does not yet know — an
agent that does not know the estate calls a thing will not find the audit that already exists.
Second, the persona's *general* search rule (lines 74, "Search with the estate's indexed surface,
never a recursive walk") points at a different tool (`ps_action("search")` / `fa`) and **the
repeated-work rule does not name it** — so the two rules do not reinforce each other. The owner's own
quotes are exactly this: "you didn't read teh docs and info … can you analyze our actual sales info
and docs and scripts … before doint all this".

**Does the surface have a rule today?** **Yes** — persona lines 102–105, italic-lead block:

> "**And look before you redo — `repeated-work` is the third most common failure, 9.3% of
> sessions.** Before starting a piece of work, spend one read asking whether it has been done:
> `journal.py search "<the area>"` and `newest handoff`. The estate has 3,600 journal entries and
> re-commissioning an audit whose findings already exist is the most expensive way to be wrong."

(The cited 9.3% is the older corpus; the round-4 register measures 10.1%. Journal size has also moved
on: 4,308 markdown files in `journal/` today against the "3,600 entries" in the rule.)

**Smallest change to the surface.** Name the indexed surface in this rule, and require a **positive
statement of what was searched for** — one line, before the work. A search nobody can see is
indistinguishable from no search.

**The measure.** `python3 /root/work/07-pain-register-v4-check.py repeated-work 102` (today: exit 1).
Live proxy: sessions where a build begins with no `journal.py search` / `newest handoff` /
`ps_action("search")` call in the preceding N steps.

### 2.5 `frustration` — 96 sessions (9.5%), 43 blocking (44.8%), severity 0/2/24/34/36, 70 at 4–5, mean 4.08

1. `6665eb86-969f-4b46-9f86-df2d6f4dd3da` · `readers/R19.md` · severity 5 · partial
   > can you just freakin figure this out yourself instead of needing me to constantly point out your errors
2. `382a3663-509a-462f-8394-793246ad93dd` · `readers/R06.md` · severity 5 · partial
   > can you actually damn think about this instead of proposing all different ideas and making me think for you
3. `e34dd061-3b51-41b1-aa7e-a66bfc5d4ce0` · `readers/R04.md` · severity 5 · partial
   > if more needs to be done why the hell did you just stop working again

**THE MECHANISM.** Frustration is the owner's state, not the agent's behaviour, so the mechanism is
whatever makes him repeat himself. It is the highest-mean-severity friction with real volume (4.08)
and 70 of 96 sessions sit at severity 4–5 — which is a measurement of *the second occurrence*:
frustration fires when a thing that was already said had to be said again. The harness's contribution
is that **nothing in it treats repetition as a signal.** A turn that ends badly looks exactly like a
turn that ended well: the engine ends the turn when the model stops calling tools, and there is no
counter of "he told you this already". The two largest text blocks in the persona — the compressed
ask-block (1,661 chars) and the outbound-comms block (1,564 chars) — are both *rule text*, so the
response to a frustrated owner has been to write more prose rather than to make the previous prose
fire.

**Does the surface have a rule today?** **Partial — one clause, inside rule 7b.** Persona lines
62–63:

> "When he is frustrated, the cause is usually a number or a claim you did not verify — check that
> first."

There is no rule that names frustration as a trigger in its own right, and no rule that makes a
repetition void the previous approach.

**Smallest change to the surface.** One sentence making repetition a hard trigger: if he has said it
before, the previous approach is void and the next message must say what is changing. Owner's
verbatim complaint "instead of needing me to constantly point out your errors" is the acceptance test.

**The measure.** `python3 /root/work/07-pain-register-v4-check.py frustration 96` (today: exit 1).
Live proxy: sessions in which the same complaint text appears in two owner turns.

### 2.6 `no-verification` — 76 sessions (7.5%), 25 blocking (32.9%), severity 0/20/30/12/14, 26 at 4–5, mean 3.26

1. `24b7eadb-888f-4ef8-8465-b3a29b451803` · `readers/R17.md` · severity 5 · partial
   > Okay, it's fixed. But the question is, if you miss this and claim that everything is migrated properly, what else did you miss?
2. `bb953f87-df3b-4b99-b196-dcae1f4bdbc9` · `readers/R12.md` · severity 5 · partial
   > you shouldve done full walkthroughs and figured this out yourself all these issues instead of making me find them
3. `5bba6ccd-e58f-4d10-aabb-05f18b09ef98` · `readers/R14.md` · severity 4 · partial
   > also the text still isn't sharp at all, it doesn't look like you fixed anythuing

**THE MECHANISM.** There is **no completion gate in the engine.** A turn ends when the model emits no
tool call; nothing checks that a claim of success is backed by a command. The only enforcement is
prose in the persona. This is not a gap the harness is unaware of — the estate has a real verification
instrument, `scripts/harness-verify.ps1` (11 numbered checks, `Check` returns `(ok, detail)`, non-zero
exit on failure) — but it verifies **the harness**, is invoked by hand or by timer, and no session is
gated on it. So the harness proves its own invariants with commands while accepting the agent's
claims about its work without any. The owner's second quote above is the cost of that asymmetry:
"you shouldve done full walkthroughs and figured this out yourself … instead of making me find them".

**Does the surface have a rule today?** **Yes** — twice. Persona lines 99–100 and 117–118:

> "**Never complete something you have not run.** If the check did not execute, the correct report is
> 'not verified', and that is a better answer than a green claim you did not earn."
> "**Verify, do not assume.** Nothing is 'working' because it was configured. Mount it, run it, call
> it, and read the result. When you claim something is fixed, say what you observed."

**Smallest change to the surface.** Both statements are correct and neither is checkable as written.
Make it one test the agent runs on its own message: **a sentence that says a thing is fixed must have
a command in it.** That is the whole change.

**The measure.** `python3 /root/work/07-pain-register-v4-check.py no-verification 76` (today: exit 1).
Live proxy: messages containing a completion word ("fixed", "done", "working", "deployed") with no
command, path or exit code in the same message.

### 2.7 `env-hostile` — 74 sessions (7.3%), 22 blocking (29.7%), severity 3/29/28/12/2, 14 at 4–5, mean 2.74

1. `c9ab8734-02ec-439a-9dd5-94d7c5ecdafc` · `readers/R12.md` · severity 4 · completed
   > i had to restart the computer, becuzse whatever you did crashed it or something and i started getting this messagge resume failed for session
2. `732b3ff5-7c02-44fa-a742-58f9d2f7c05a` · `readers/R10.md` · severity 4 · completed
   > what is this that keeps showing up, i don't use the git gui, you have all the creds
3. `9c8c2528-0afc-4de0-aaa3-08060bb1f374` · `readers/R17.md` · severity 4 · completed
   > every other agent has been printing labels for a few days, why are you the only one with issues? i just realized, printing the wrong one froze the printer, i had o press power to reset it

**THE MECHANISM.** The shell is chosen by the host the preset mounts on, and **the agent is not told
which one it got.** In the preset, the two shell tools are mutually exclusive by platform:

```
- id: tool-bash
  name: '@deepseek-ai/dsh-tool-bash'
  disabled: !!js process.platform === 'win32'      # lines 246-248
- id: tool-pwsh
  name: '@deepseek-ai/dsh-tool-pwsh'                # enabled only on win32
```

So a session's shell is a property of *where it landed*, and the persona's own fleet table
(lines 155–162) names the machines without naming their shells. The only place the contract is
written is inside the **tool description** in the engine (`dsh-tool-pwsh`, lines 255–257: "Each call
runs in a fresh pwsh process; pass `workdir` instead of using `cd`. Paths use native Windows form
(`C:\...`) … Commands may run under a file sandbox … Under the Windows sandbox, read-only pwsh runs
in PowerShell ConstrainedLanguage mode …"). An agent that reaches for `grep -r` on a Windows node and
a Linux agent that reaches for `Get-ChildItem` both get an *ordinary* tool result with an exit code,
because of §2.1 — so the environment fights back and the friction is absorbed rather than surfaced.

The strongest available evidence that the surface lacks this rule is **the round-6 brief itself**,
which had to write it out for me:

> "**On Windows nodes the shell is PowerShell** — `df`, `head`, `grep`, single-quoted heredocs and
> `/c/...` paths do not work there. Use PowerShell cmdlets and the read/grep/glob file tools for
> bytes (a shell call costs ~700 ms, a `read` under a millisecond)."

A dispatch brief should not have to carry a rule that every session already loads — the fact that it
does is the measurement.

**Does the surface have a rule today?** **No — `none`.** The fleet table gives OS-adjacent prose
("`ZABZ-YOGA` — Windows laptop"; "`secratary-cloud` — the cloud box") and no shell, no path form, no
encoding or sandbox contract. There is also no rule anywhere telling a mesh child to establish which
host and shell it is on before its first command.

**Smallest change to the surface.** One line per host in the fleet table naming its shell, plus the
requirement that the first command on an unfamiliar machine is preceded by a one-line statement of
the shell. The estate's own indexed search (`ps_action("search")`, the `fast-search` skill) is the
cross-OS surface and should be named there as the way to find files on either.

**The measure.** `python3 /root/work/07-pain-register-v4-check.py env-hostile 74` (today: exit 1).
Live proxy: pwsh results whose stderr matches a Linux-tool-not-recognised / path-not-found pattern
(`is not recognized`, `CommandNotFoundException`, `cannot find the path`).

### 2.8 `restart-agent` — 73 sessions (7.2%), 34 blocking (46.6%), severity 0/12/27/20/14, 34 at 4–5, mean 3.49

1. `d772db00-c884-48e1-acf2-cb95cad2992d` · `readers/R01.md` · severity 5 · partial
   > you just said you will do it and didn't, come on get to work
2. `49ee46ca-7be4-4b81-a6c7-fa5e067a4b55` · `readers/R07.md` · severity 5 · completed
   > just fix it instead of trying to keep reporting back, get to work
3. `4772de74-452e-493f-9528-d0a970851749` · `readers/R13.md` · severity 5 · partial
   > stop saying what you'll do and just do it

**THE MECHANISM.** The turn-end condition exists only in prose. The engine has **no model of
outstanding work**: a turn terminates when the model stops requesting tools, however much is
unfinished, and there is no check that the last message contains a result rather than an intention.
46.6% of these sessions still ended without the work done, which is the tell — the imperative is the
owner's correct response to a stop, not impatience. The same mechanism produces `stopped-early` (37
sessions, 62.2% blocking, the highest blocking rate in the register): one harness behaviour, seen
from the owner's side and from the transcript's side.

**Does the surface have a rule today?** **Yes** — rule 1 (lines 34–50) and lines 130–134:

> "A turn may end only when the work is done with evidence, you are genuinely blocked, the decision
> is genuinely his, or the action is irreversible."
> "**When something is supposed to be running, go and read that it ran.** … Write down what 'done'
> looks like before you start polling for it. … (Measured 2026-10-14: 93 `restart_agent` owner turns;
> 10,916 job-poll calls in one month.)"

Note the units again: **93 `restart_agent` owner turns** in the persona against **73 sessions** in the
register. The surface and the corpus do not share a denominator, so nobody can tell whether the rule
is working.

**Smallest change to the surface.** Compress: rule 1 is 1,661 characters and is doing eight jobs at
once because commit `ff39ba3c` merged rules 1b/1c/2/2b/2c/3/9 into it (§3.1). Replace it with one
short rule carrying the *test* — "if your next sentence begins 'I will', you have not finished".

**The measure.** `python3 /root/work/07-pain-register-v4-check.py restart-agent 73` (today: exit 1).
Live proxy: sessions whose final assistant message contains a future-tense commitment and no tool
call after it.

### 2.9 `context-loss` — 56 sessions (5.6%), 23 blocking (41.1%), severity 0/10/20/14/12, 26 at 4–5, mean 3.50

1. `4c3ded25-e075-4afa-a292-6bdf0610f8a7` · `readers/R12.md` · severity 5 · partial
   > you forgot that we don't say the customers name
2. `5eec8d35-9762-4d6b-a9ce-51e20d054c65` · `readers/R13.md` · severity 5 · partial
   > argggg did you read your own full chat history of this chat begnining to end, cuz you injected a bunch of times ther first time was without being signed in and then you did a few more times can you pull up all the data on this
3. `72c9fd6e-26b8-4ca3-998e-4a9c559fd17a` · `readers/R17.md` · severity 5 · partial
   > actually it's 95 instead of the usual more like 65 or 70, we went up in price since yisroel left and i have to do the soldering also say that it doesn't always get fixed, but 50 non refundable is required deposit, you forgot that also

**THE MECHANISM — the clearest one in this set, and it is a deliberate feature.** The preset mounts
the two components that throw the agent's memory away:

```
- id: compaction
  name: cordis:group
  isolate:
    compaction: true
    toolResultPruner: true
  config:
    - id: compaction-basic
      name: '@deepseek-ai/dsh-compaction-basic'
      config:
        thresholdRatio: 0.7                       # lines 333-344
    - id: tool-result-pruner
      name: '@deepseek-ai/dsh-compaction-tool-result-pruner'
      config:
        thresholdChars: 5000
        headChars: 2500
        tailChars: 700                            # lines 358-363
```

At 70% of the window the **entire conversation history is replaced by a summary**. Every tool result
over 5,000 characters has its **middle replaced by the literal string**
`[... tool result middle pruned ...]`. The owner's second quote above — "did you read your own full
chat history of this chat begnining to end" — is a request for something the harness had already
deleted, and the third quote is a rule he gave that compaction had summarised away.

This is not a defect to be removed: both components exist because the bill is `steps × mean context`
(persona line 78) and because a 256,000-token completion reservation once made the credential ceiling
*lower* than the compaction trigger, producing ten `CONTEXT_WINDOW_EXCEEDED` failures (preset
lines 335–342). It is a **tradeoff the instruction surface does not mention at all.**

**Does the surface have a rule today?** **Partial — and it addresses the wrong timescale.** Persona
lines 170–197 give the cross-session continuity discipline in detail ("You have no continuous memory.
Every session starts blank. Your only self is what you write down."), and line 78 tells the agent to
keep sessions short and hand off through the journal. **There is no sentence anywhere telling the
agent that its history can be pruned mid-session**, which is the failure the owner is actually
reporting. The agent is told it has no memory between sessions and is not told it loses memory inside
one.

**Smallest change to the surface.** One sentence: this harness prunes long tool output and replaces
the history with a summary when the window fills, so anything you will need again must be written to
a file or the journal the moment you get it. That converts an invisible loss into an instruction the
agent can act on, and it is measurable (does the decision appear on disk).

**The measure.** `python3 /root/work/07-pain-register-v4-check.py context-loss 56` (today: exit 1).
Live proxy: count of `[... tool result middle pruned ...]` and compaction events per session, against
sessions where the owner has to repeat a fact he already gave.

### 2.10 `ignored-instruction` — 53 sessions (5.3%), 26 blocking (49.1%), severity 0/2/13/18/20, 38 at 4–5, mean 4.06

1. `f87e4dc2-549a-4451-9ab8-4bfdf31c5abf` · `readers/R09.md` · severity 5 · partial
   > how many times do i have to tell you i won't see texts to 1594, that's an inbox that only you monitor
2. `1c6dc139-3e45-433a-94b4-bd07e60cef09` · `readers/R19.md` · severity 5 · partial
   > what the heck are you talking about you are anyways not allowed to automatically send a text, and i tell you explicilty when to send them through dialpad and they get sent out
3. `bb953f87-df3b-4b99-b196-dcae1f4bdbc9` · `readers/R12.md` · severity 5 · partial
   > are you doing it or do you keep just saying what you will do eventually one day

**THE MECHANISM — this one is measured, and it is the most actionable finding in this file.**

The rules being ignored in the two strongest quotes **are already in the persona**, at length.
Persona lines 143–149 are the outbound-comms block, 1,564 characters: "Never send anything outbound
without an explicit per-message instruction in the current conversation", per-message approval, "a
task-level directive is not approval", read the `To` header back. The owner's complaint is that the
agent auto-sent a text. **The rule exists, is the second-longest block in the persona, and was
broken anyway.**

Why: **the instruction surface has been growing by merging, and merged rules lose their teeth.**
Commit `ff39ba3c` (2026-10-14 09:14:24 -0400, "presets(zabz): compress the do-not-ask block") replaced
eight separate rules — 1, 1b, 1c, 2, 2b, 2c, 3 and 9 — with **one** paragraph, and did not renumber:

```
$ git show ff39ba3c -- presets/zabz/agent.cordis.yml
-      **1. Do not stop to ask permission you already have.** 9.9% of his messages were ...
-      **1b. On any larger job, orchestrate — do not grind serially.** ...
-      **1c. The fleet runs on the MESH — `subagent` is a child on another machine.** ...
-      **2. Ask rarely, ask well, ask one at a time, and always recommend.** ...
-      **2b. He does not review documents — never end a turn by handing him one.** ...
-      **2c. Never flag. Solve — or ask one question and move on.** ...
-      **3. Do not route development decisions to him.** ...
-      **9. Do not make him think for you.** ...
+      **1. Do not stop to ask permission you already have; ask once only when the call is genuinely his.**
+      ... (12 lines, 1,661 characters)
```

The consequence is visible in the file today:

```
$ python persona_drift.py
generator PERSONA  chars=23783 lines=133
committed persona  chars=22867 lines=209
generator rule numbers : 1, 1b, 1c, 2, 2b, 2c, 3, 4, 5, 6, 7
committed rule numbers : 1, 4, 5, 6, 7, 7b, 8
```

**The committed persona's rules are numbered 1, 4, 5, 6, 7, 7b, 8. Rules 2 and 3 do not exist.**
Rules 2, 2b, 2c and 3 were argued into rule 1; rule 9 was deleted outright (it survives only as the
clause "Do not make him think for you" inside rule 1). The list now advertises that two of its rules
were lost, and rule 1 is a 1,661-character paragraph — **2.1× the next-longest business rule** — doing
the work of eight, with no checkable prohibition in it. That is how a surface gets to 22,867
characters of prefix plus up to 65,536 bytes of `AGENTS.md` while the rules that matter stop firing.

**Does the surface have a rule today?** **Partial.** `AGENTS.md` opens "These are rules, not notes"
and the persona says "These are not style preferences" — but nothing ranks a standing rule above an
inferred preference, and nothing states that *a rule given in this session is binding on every later
turn*. The persona's own memory section says only that decisions must be recorded (rule 5).

**Smallest change to the surface.** Do not add. **Repair:** renumber the rules so the list has no
holes, and split rule 1 back into its two load-bearing halves — "decide the development questions"
and "one question, with your recommendation, only when it is mine" — each one sentence, each with a
test. The surface is long; length is how rules die.

**The measure.** `python3 /root/work/07-pain-register-v4-check.py ignored-instruction 53` (today:
exit 1). Live proxy: sessions with an outbound send that no preceding owner turn approved, and
`journal.py check` on the session's own handoff.

### 2.11 `format-unreadable` — 40 sessions (4.0%), 15 blocking (37.5%), severity 0/10/14/5/11, 16 at 4–5, mean 3.42

1. `ca000eb1-2e20-4fb6-8334-17d25809d1a9` · `readers/R07.md` · severity 5 · completed
   > why do you keep writing like this in funny font and no spaces, it happens all the time and makes it very hard toread
2. `72c9fd6e-26b8-4ca3-998e-4a9c559fd17a` · `readers/R17.md` · severity 5 · partial
   > okay one thing at a time clearly with the full context also you keep making unreadable lines like in this pic
3. `382a3663-509a-462f-8394-793246ad93dd` · `readers/R06.md` · severity 5 · partial
   > terrible confusing bad pictures oh my gosh

**THE MECHANISM.** The rendering path is the Web GUI, and the persona names exactly one way it
mangles text — the two-dollar-sign inline-maths case — while the owner's complaints cover at least
three: a font/spacing failure, "unreadable lines", and images. So the rule covers roughly one of the
observed causes, and the surface has no notion of "the artefact must arrive readable" beyond that one
case. The register's own reading is the same: "It is the cheapest friction to fix and it recurs in
four different shards, which suggests it is not one interface but a house style."

Note the second quote is the *same session* (`72c9fd6e`) that also carries `correction` and
`context-loss` — one session, three frictions, which is why a rule aimed at one friction rarely fixes
the session.

**Does the surface have a rule today?** **Yes, but narrow** — rule 8, persona line 66 (723 chars),
written 2026-09-24 from the owner's own verbatim complaint:

> "**8. Write money so it survives the renderer.** The Web GUI renders a PAIR of dollar signs in one
> paragraph as inline maths: serif font, spaces eaten, word-joined … So in prose, write amounts as
> plain numbers with the unit once … or at most ONE dollar sign per paragraph, never two."

**Smallest change to the surface.** Generalise the rule from *dollar signs* to *the artefact*: never
send a rendering you have not seen. The dollar-sign clause stays as the worked example, which is what
makes it stick.

**The measure.** `python3 /root/work/07-pain-register-v4-check.py format-unreadable 40` (today:
exit 1). Live proxy: count of owner-facing messages with two or more `$` in one paragraph.

---

## 3. The single table

| friction | sessions | existing rule today (persona line) | proposed rule | measure |
|---|---:|---|---|---|
| `tool-failure` | 302 | **yes**, lines 120–128 ("read the failure before you act on it") | **R3** — a non-zero exit is an open item | `07-pain-register-v4-check.py tool-failure 302` |
| `correction` | 132 | **yes**, rule 7b, lines 60–64 | **R1** — every fact carries where you read it | `...-check.py correction 132` |
| `wrong-data` | 116 | **yes**, lines 80–115 (four overlapping statements) | **R1** (collapse the five into one) | `...-check.py wrong-data 116` |
| `repeated-work` | 102 | **yes**, lines 102–105 | **R5** — before you build, spend one read proving it is not there | `...-check.py repeated-work 102` |
| `frustration` | 96 | **partial**, one clause inside rule 7b, line 62 | **R4** — a turn does not end while work remains | `...-check.py frustration 96` |
| `no-verification` | 76 | **yes**, lines 99–100 and 117–118 | **R1** — a sentence saying "fixed" must contain a command | `...-check.py no-verification 76` |
| `env-hostile` | 74 | **none** — the shell contract lives only in the engine's tool description | **R7** — know your shell before you type | `...-check.py env-hostile 74` |
| `restart-agent` | 73 | **yes**, rule 1 lines 34–50 + lines 130–134 | **R4** — "I will" is not a result | `...-check.py restart-agent 73` |
| `context-loss` | 56 | **partial** — cross-session continuity only (170–197); **nothing about mid-session pruning** | **R6** — the window gets thrown away, write it down now | `...-check.py context-loss 56` |
| `ignored-instruction` | 53 | **partial** — the rules exist and are the longest blocks; nothing binds a prior turn | **R2** — a rule stated once binds the rest of the session | `...-check.py ignored-instruction 53` |
| `format-unreadable` | 40 | **yes but narrow**, rule 8, line 66 (dollar signs only) | **R8** — the artefact has to arrive readable, and you have to have seen it | `...-check.py format-unreadable 40` |

All eleven measures currently exit **1** (`pain OPEN`).

---

## 4. What contradicts the brief, and the round-4/5 documents

**4.1 The brief says ten frictions and lists eleven.** §0.2. I did all eleven.

**4.2 The brief's own paths do not resolve.** §0.1. `docs/dsh-evolution-v6/PROGRAM.md` does not exist
anywhere on this node or the authority, so §2 and §5 of it could not be read. `docs/dsh-evolution-v4/`
does not exist either; the register and handoff survive as files in `/root/work/` on the authority.
The register records the same failure for round 3/4, so this is a recurring defect in the dispatch
briefs, not a one-off.

**4.3 The brief's headline — "the persona spends its longest paragraphs on the two rarest" — is true
today, was made worse yesterday, and is about to be undone by the generator.** Measured block sizes
in the committed persona: the compressed do-not-ask rule is **1,661 chars**, the outbound-comms block
**1,564**, the AI-models rule **1,120**. The two rarest frictions are `asked-unnecessarily` (20) and
`asked-badly` (22). So the brief is right — but three things follow that it does not say:

- The compression happened on **2026-10-14 09:14**, i.e. the day before this round, in commit
  `ff39ba3c`, and it merged eight rules into one without renumbering. **The persona now numbers its
  rules 1, 4, 5, 6, 7, 7b, 8.** Rules 2 and 3 are gone from the list; rule 9 was deleted.
- **`python scripts/make_zabz_preset.py --check` FAILS on this machine**:
  `DRIFT: the committed preset does not match this generator: presets\zabz\agent.cordis.yml`
  (exit 1). The generator still emits the **uncompressed** persona — rule numbers
  `1, 1b, 1c, 2, 2b, 2c, 3, 4, 5, 6, 7`, 23,783 chars — against the committed 22,867 chars with
  `1, 4, 5, 6, 7, 7b, 8`. **Running the generator reverts the compression and restores the long
  ask-block.** The generator's own docstring says this is how rules die: "NEVER hand-edit that file:
  a rule that lives only there is deleted the next time anyone runs this … which is exactly how
  persona rules 2b and 2c were lost on 2026-09-11."
  **Consequence for the manager: a proposed rule pasted only into `presets/zabz/agent.cordis.yml` is
  temporary. It must go into `PERSONA` in `scripts/make_zabz_preset.py` and be regenerated.** I am
  forbidden to edit `scripts/`, so I have not done it.
- The generator is stale in a second, safety-relevant way: it still contains the pre-fix outbound
  handling, and its fleet list is written as it was before the 2026-10-11 cutover. Regenerating
  without reconciling will ship an older safety posture, not just an older rule set.

**4.4 The persona's own numbers and the register's numbers do not share a denominator.** The persona
cites `tool-failure` in "989 of 1,093 owner sessions, 90.5%" (line 126–128) where the register
measures **302 of 1,008 (30.0%)**; `wrong-data` at 11.2% of 935 sessions against 11.5% of 1,008;
`repeated-work` at 9.3% against 10.1%; `correction` at 5.74% of turns against 13.1% of sessions;
`restart-agent` at 93 owner turns against 73 sessions. Some of that is turns-vs-sessions, some is a
different corpus, and at least one — tool-failure, 90.5% vs 30.0% — is a **3× disagreement about the
same friction**. A rule justified by a number that contradicts the register cannot be evaluated.

**4.5 `harness-verify.ps1` check 1 is currently false.** Its first check runs
`make_zabz_preset.py --check` and asserts "preset in sync with generator". That check fails today
(§4.3), so the harness's own verifier reports the instruction surface as broken — and, per §2.6,
nothing gates a session on it.

**4.6 The engine classifies a failed command as a successful tool call, by design.** §2.1,
`isError` false. This is the single largest mechanism finding in this file: the most-tagged friction
in the corpus (302 sessions, 30%) is produced by a deliberate rendering decision, and the surface's
answer is a 788-character paragraph asking the model to read a marker the harness has already
demoted.

**4.7 The two components that delete the agent's memory are configured on this surface and are
mentioned nowhere in the instruction surface.** §2.9. `compaction-basic` at 0.7 and
`tool-result-pruner` at 5000/2500/700 — the pruner **39% more aggressive than the engine default**.

**4.8 Small correction to the register's own §1 provenance note.** It says the census's `frictions`
key is "a set of session counts, not a mapping". True and confirmed from the SQL-free side: I did not
need `CENSUS-v4.json` at all, because the reader files carry `frictions:` and `severity:` per session
and reproduce the census exactly. The register's recovery was sound.

**4.9 The journal does not carry this vocabulary.** `wrong-data` **is** a live journal tag (25+
entries — `P3161`, `P3798`, `P3802`, `L3729`, `L3732`, `L3740`, `L3787`, `L3803` …). `tool-failure`,
`repeated-work` and `format-unreadable` appear as tags in **none** of the 4,308 markdown files in
`journal/`. So three of these eleven frictions have no home in the estate's own memory system, which
is why nothing reports them between audit rounds.

---

## 5. What I did not do, and what I could not verify

**Deliberately not done.**

- I did not edit `presets/`, `profiles/` or `scripts/` — the brief forbids it, and §4.3 means an edit
  to the preset alone would have been reverted anyway. The proposed rules are a proposal.
- I did not run `make_zabz_preset.py` without `--check`. It rewrites `presets/zabz/agent.cordis.yml`
  wholesale (§4.3); running it would have destroyed the compressed persona I was sent to measure.
- I did not run the full `harness-verify.ps1`. Check 1's result was obtained directly from the
  command that check wraps, which is the narrower and sufficient evidence for §4.5.
- I did not push, touch `main`, reset, clean, or stage anything. The harness-config checkout here is
  on branch `mesh/broker-host-cloud-default-20261013` at `2d01206f` and already carried 20 modified
  files before I arrived; I added nothing to git.
- I did not rebuild the count by any route other than the 19 reader files, because that is the frozen
  corpus the register is defined over.

**Could not verify.**

- **§2 and §5 of a v6 PROGRAM.** The document does not exist on either machine (§0.1).
- **`CENSUS-v4.md`** was copied but not read line by line; every number I report is from the reader
  files, which is the stronger source.
- **The share of each friction actually caused by the mechanism I name.** I can show the mechanism
  exists, is configured on this surface, and has the right shape for the friction. I **cannot**
  show what fraction of the 302 `tool-failure` sessions hit the pruner, or what fraction of the 56
  `context-loss` sessions lost the fact to compaction rather than to a fresh session. That would need
  per-session compaction and prune events, which the corpus does not carry. Treat "the mechanism" as
  *the harness behaviour that makes this friction possible and cheap*, not as an attribution share.
- **Whether these configurations were active when the corpus sessions ran.** The corpus spans
  1,008 sessions on several machines and predates some of the preset edits. The mechanisms are read
  from the checkout today; the counts are from the corpus. I have not joined them per session.
- **`env-hostile` root causes at the three quotes.** Two of the three quotes (a crash, and a git-GUI
  credential prompt) are environment failures I can classify but not reproduce from the corpus.
- **The mean severities in the register's §3 table.** I verified the counts, blocking counts and
  severity mixes exactly; I did not independently recompute the means (2.75, 3.13, 3.35, …).
- **That any proposed rule will survive its first regeneration.** Per §4.3 the opposite is true until
  the generator is reconciled.

**One correction to my own first pass, stated for the record.** My first parser reported
`tagged_sessions=623` against the register's 597; the difference was that it did not exclude the
literal `none`, which 26 sessions carry. Corrected, the register's 597 reproduces exactly. I am
recording the error rather than the clean number, because the two disagreeing is more useful to the
next reader than a figure that was right the first time.
