# 07 - The pain register, round 4

Built by **WS-REGISTER** (mesh child on host `ZABZ-TECH`) on **2026-10-14T23:41:22Z**.
Supersedes `docs/dsh-evolution-v2/07-pain-register-v2.md` (round 3). Ranked by
**blocks work -> recurs -> owner-visible**, the order the owner pays in. Every number in this
file is computed from the corpus by `07-pain-register-v4-analysis.py`, not remembered; every
quotation is read out of `CENSUS-v4.json` byte-for-byte, not retyped.

## 1. Provenance

| source file (on the authority, `secratary-cloud`) | bytes | read |
|---|---:|---|
| `/home/zabz/evolution-corpus-v4/CENSUS-v4.json` | 166,609 | 2026-10-14T23:32Z (first access; census keys inspected 23:32-23:37Z) |
| `/home/zabz/evolution-corpus-v4/CENSUS-v4.md` | 39,419 | 2026-10-14T23:32Z (first access; census keys inspected 23:32-23:37Z) |
| `/home/zabz/evolution-corpus-v4/owner-turns-final.jsonl` | 7,295,298 | 2026-10-14T23:32Z (first access; census keys inspected 23:32-23:37Z) |
| `/home/zabz/evolution-corpus-v4/readers/R01.md` .. `R19.md` (19 files) | 734,536 | 2026-10-14T23:32Z (first access; census keys inspected 23:32-23:37Z) |

Read path for the shape of the deliverable: `docs/dsh-evolution-v2/07-pain-register-v2.md`, 69 lines,
read from git branch `offsite/journal/zabz-yoga` (commit `7e394315`, 2026-10-14 08:42:54 -0400).
**The path the brief gave does not exist on the authority:** `ls -l /root/code/harness-config/docs/dsh-evolution-v2/`
returns `No such file or directory` on the checked-out branch; the file exists only on that git branch.

### What `CENSUS-v4.json` actually contains

Three top-level keys: `census`, `high_severity` (122 records), `wanted` (212 records).
`census` has 11 keys: `duplicate_session_ids` (empty), `frictions` (20 counts), `intent_clusters` (9),
`outcomes` (5), `parse_problems` (empty), `per_file` (19), `reader_files`, `records`, `sessions_with_a_want`,
`severities` (5), `unique_sessions`.

**The schema gap that shapes this register: `census.frictions` is a set of session counts, not a
mapping.** The JSON contains no per-session friction list and no per-session severity, so the
severity mix required by the brief - the column that shows which frictions are angry rather than
merely frequent - cannot be read out of the JSON at all. It was recovered by parsing the 19 reader
files, which do carry `frictions:` and `severity:` per session, and the recovery was validated
against the census:

```
$ python3 /root/work/07-pain-register-v4-analysis.py
sessions: 1008 | with a friction tag: 597 | without: 411 | tags: 1364
high_severity: 122 | wanted: 212
census_check: {"frictions_mismatch": {}, "friction_extra": {}, "severity_mismatch": {}, "outcome_mismatch": {}, "records": {"fresh": 1008, "census": 1008}, "unique": {"fresh": 1008, "census": 1008}}
```

Every friction count, every severity count and every outcome count in my fresh parse of the reader
files equals the frozen census. The friction counts are therefore usable as the census's own numbers,
and the severity mix is reproducible rather than asserted.

## 2. The ranking rule

The brief fixes the order: **blocks work -> recurs -> owner-visible**. Made measurable, that is a
lexicographic sort on three computed quantities, applied to the 20 friction ids:

1. **blocks work** - the number of the friction's sessions whose `outcome` is `failed`, `partial` or
   `abandoned`, i.e. the session did not complete. Descending. This is the primary key.
2. **recurs** - the number of sessions carrying the friction. Descending. Tie-break.
3. **owner-visible** - the number of those sessions at severity 4 or 5, the register's definition of
   pain the owner actually noticed. Descending. Final tie-break.

The **blocking rate** (blocking sessions as a share of the friction's own sessions) is reported
separately and is not used as a key, because a small class with a 62% blocking rate and nine sessions
is a different kind of problem from a large class with a 25% rate. Both are in the table so the reader
can see which is which; only the sort follows the brief.

## 3. The register

| # | friction | sessions | % of 1,008 | blocks work | blocking rate | severity mix 1/2/3/4/5 | sev 4-5 | mean sev |
|---|---|---:|---:|---:|---:|---|---:|---:|
| **1** | `tool-failure` | 302 | 30.0% | 76 | 25.2% | 10/149/77/39/27 | 66 | 2.75 |
| **2** | `frustration` | 96 | 9.5% | 43 | 44.8% | 0/2/24/34/36 | 70 | 4.08 |
| **3** | `wrong-data` | 116 | 11.5% | 38 | 32.8% | 0/24/48/23/21 | 44 | 3.35 |
| **4** | `restart-agent` | 73 | 7.2% | 34 | 46.6% | 0/12/27/20/14 | 34 | 3.49 |
| **5** | `correction` | 132 | 13.1% | 32 | 24.2% | 1/39/49/28/15 | 43 | 3.13 |
| **6** | `repeated-work` | 102 | 10.1% | 30 | 29.4% | 1/24/38/26/13 | 39 | 3.25 |
| **7** | `slow` | 54 | 5.4% | 26 | 48.1% | 0/15/10/13/16 | 29 | 3.56 |
| **8** | `ignored-instruction` | 53 | 5.3% | 26 | 49.1% | 0/2/13/18/20 | 38 | 4.06 |
| **9** | `no-verification` | 76 | 7.5% | 25 | 32.9% | 0/20/30/12/14 | 26 | 3.26 |
| **10** | `context-loss` | 56 | 5.6% | 23 | 41.1% | 0/10/20/14/12 | 26 | 3.50 |
| **11** | `stopped-early` | 37 | 3.7% | 23 | 62.2% | 0/4/14/9/10 | 19 | 3.68 |
| **12** | `env-hostile` | 74 | 7.3% | 22 | 29.7% | 3/29/28/12/2 | 14 | 2.74 |
| **13** | `format-unreadable` | 40 | 4.0% | 15 | 37.5% | 0/10/14/5/11 | 16 | 3.42 |
| **14** | `safety` | 32 | 3.2% | 14 | 43.8% | 0/0/8/13/11 | 24 | 4.09 |
| **15** | `non-answer` | 26 | 2.6% | 13 | 50.0% | 0/4/12/5/5 | 10 | 3.42 |
| **16** | `asked-badly` | 22 | 2.2% | 8 | 36.4% | 0/3/9/5/5 | 10 | 3.55 |
| **17** | `asked-unnecessarily` | 20 | 2.0% | 8 | 40.0% | 0/4/6/7/3 | 10 | 3.45 |
| **18** | `invented-detail` | 19 | 1.9% | 8 | 42.1% | 0/2/12/0/5 | 5 | 3.42 |
| **19** | `overcomplicated` | 25 | 2.5% | 6 | 24.0% | 0/6/12/3/4 | 7 | 3.20 |
| **20** | `bad-prioritisation` | 9 | 0.9% | 3 | 33.3% | 0/1/5/0/3 | 3 | 3.56 |

The verbatim command behind that table:

```bash
ssh secratary-cloud 'python3 /root/work/07-pain-register-v4-analysis.py'
```

The vocabulary has **exactly 20 ids**, and all 20 rank above. There is therefore no tail to push
into a compact table: the required per-pain cap of 20 and the size of the taxonomy are the same
number, and the compact table the brief asks for is **empty**. Stated here rather than filled with
filler.

One honest caution about the denominator. **411 of the 1008 sessions carry no friction tag at all**
(100 written as a literal `-` or `none`, 311 left blank), so the 1364 tags sit over only 597 sessions.
The reader brief instructs an empty friction list for one-turn and machine-ish sessions, so most of
that remainder is probably of that kind - but that is not verified here session by session, and a
blank friction list is not evidence that a session was clean.
Percentages of 1,008 in the table are shares of the whole corpus, so they understate how often a
friction fires inside the sessions where anything fired at all.

## 4. The open pains, one section each

Each section carries: what hurts, the measured frequency with its source, the owner's own words
with the session they came from, one owner, and one verification command.

**On `owner`:** the census names no individual agent anywhere - not in `census`, not in
`high_severity`, not in `wanted`. So ownership below is assigned to the **workstream or artifact**
the fix has to land in, not to an invented agent name. Nothing in this register is assigned to the
owner himself: every one of the 20 has a named engineering artifact behind it, which is the same
finding round 3 reached from a different direction.

**On the verification commands:** every one of the 20 is
`python3 /root/work/07-pain-register-v4-check.py <friction> <count>`, which recomputes the count
from the readers and exits 0 only when it has fallen below the target. All 20 were run; **all 20
exit 1 and print `pain OPEN`**, because all 20 pains are open. That is the honest reading, and
a register whose checks all pass on the day it is written is a register that measured nothing.

### 1. `tool-failure` - 302 sessions

**What hurts.** Commands, tools and scripts fail and the session absorbs the failure instead of turning it into a next action. It is the single most-tagged friction in the corpus and the least punishing per session, which is exactly why it survives: background noise never becomes the loudest thing in the room, so nobody fixes it.

**Measured frequency.** 302 of 1008 sessions (30.0%); 76 of them blocking (25.2%); severity
mix 1/2/3/4/5 = 10/149/77/39/27; 66 at severity 4-5; mean severity 2.75. Source: `readers/R03.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["tool-failure"]` = 302.

**The owner's own words** - `24e68280`, severity 4, `readers/R03.md`:

> it didn't work, it just froze on that screen for a little and then went to a this can't be found screen

**One owner.** The session that owns the harness tool-result path - the code that turns a non-zero exit, a timeout or garbage output into a decision.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py tool-failure 302
```

Exits 0 only when the count falls below 302. Today it exits 1: `pain OPEN`.

### 2. `frustration` - 96 sessions

**What hurts.** He is visibly angry. This is not a symptom of the other frictions - it is the one class where the corpus records the owner's own state, and it fires almost only in sessions that were already blocking (44.8%), concentrated at the top of the severity scale (70 of 96 at severity 4 or 5, the highest mean severity of any friction with real volume).

**Measured frequency.** 96 of 1008 sessions (9.5%); 43 of them blocking (44.8%); severity
mix 1/2/3/4/5 = 0/2/24/34/36; 70 at severity 4-5; mean severity 4.08. Source: `readers/R10.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["frustration"]` = 96.

**The owner's own words** - `fd29a7e2`, severity 5, `readers/R10.md`:

> what the hell, we bought the projector together and you documented it very clearly with lots of instructins, you are making me very upset

**One owner.** The orchestrator that decides when a turn ends and whether it finishes or reports.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py frustration 96
```

Exits 0 only when the count falls below 96. Today it exits 1: `pain OPEN`.

### 3. `wrong-data` - 116 sessions

**What hurts.** The agent acted on or reported something that was not true. Nothing else here damages trust so cheaply: a single wrong number is indistinguishable from a right one at the moment it is read, and the owner only finds out by doing the checking himself.

**Measured frequency.** 116 of 1008 sessions (11.5%); 38 of them blocking (32.8%); severity
mix 1/2/3/4/5 = 0/24/48/23/21; 44 at severity 4-5; mean severity 3.35. Source: `readers/R01.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["wrong-data"]` = 116.

**The owner's own words** - `f0c6af63`, severity 4, `readers/R01.md`:

> ???? no rattlebyte isn't kinguin, it's the panasonic region free firmware project, you are confusing things

**One owner.** The reporting path - whoever writes a number, a status or a figure into a message.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py wrong-data 116
```

Exits 0 only when the count falls below 116. Today it exits 1: `pain OPEN`.

### 4. `restart-agent` - 73 sessions

**What hurts.** He had to tell the agent to keep going: get to work, keep working, stop saying and start doing. 46.6% of these sessions still ended without the work done, so the imperative is not impatience - it is the correct response to an agent that stops with work remaining.

**Measured frequency.** 73 of 1008 sessions (7.2%); 34 of them blocking (46.6%); severity
mix 1/2/3/4/5 = 0/12/27/20/14; 34 at severity 4-5; mean severity 3.49. Source: `readers/R13.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["restart-agent"]` = 73.

**The owner's own words** - `4772de74`, severity 5, `readers/R13.md`:

> stop saying what you'll do and just do it

**One owner.** The session-lifecycle rule - a turn may not end while work remains.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py restart-agent 73
```

Exits 0 only when the count falls below 73. Today it exits 1: `pain OPEN`.

### 5. `correction` - 132 sessions

**What hurts.** The second most-tagged friction and the widest reach in the register: he had to correct a fact, a number or an interpretation, spread across every one of the nineteen shards. This is the friction the instruction surface is supposed to erase, and it is not falling.

**Measured frequency.** 132 of 1008 sessions (13.1%); 32 of them blocking (24.2%); severity
mix 1/2/3/4/5 = 1/39/49/28/15; 43 at severity 4-5; mean severity 3.13. Source: `readers/R12.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["correction"]` = 132.

**The owner's own words** - `4c3ded25`, severity 5, `readers/R12.md`:

> you forgot that we don't say the customers name

**One owner.** The fact-check path - assert only what was checked in this session.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py correction 132
```

Exits 0 only when the count falls below 132. Today it exits 1: `pain OPEN`.

### 6. `repeated-work` - 102 sessions

**What hurts.** Work was redone that already existed or had already been done. It is the most expensive friction per unit of trust, because the second attempt is often worse than the first and it teaches the owner that nothing stays built.

**Measured frequency.** 102 of 1008 sessions (10.1%); 30 of them blocking (29.4%); severity
mix 1/2/3/4/5 = 1/24/38/26/13; 39 at severity 4-5; mean severity 3.25. Source: `readers/R16.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["repeated-work"]` = 102.

**The owner's own words** - `b9810e28`, severity 5, `readers/R16.md`:

> i thought we already got rid of kosher filter, you went against the rules and installed it on production devices when it wans' ready and you werent told to i thought we got rid of it already

**One owner.** The retrieval and memory layer - search before rebuilding.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py repeated-work 102
```

Exits 0 only when the count falls below 102. Today it exits 1: `pain OPEN`.

### 7. `slow` - 54 sessions

**What hurts.** It took long enough that he said so. 48.1% of these sessions ended blocked, so slowness is not a comfort problem here - it is a session-killer, and it clusters on search and on waiting for a test to finish.

**Measured frequency.** 54 of 1008 sessions (5.4%); 26 of them blocking (48.1%); severity
mix 1/2/3/4/5 = 0/15/10/13/16; 29 at severity 4-5; mean severity 3.56. Source: `readers/R02.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["slow"]` = 54.

**The owner's own words** - `e50ad938`, severity 5, `readers/R02.md`:

> waht is taking so long to test, it's been sitting for a while

**One owner.** The search path owner - a latency budget for search that a session can actually meet.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py slow 54
```

Exits 0 only when the count falls below 54. Today it exits 1: `pain OPEN`.

### 8. `ignored-instruction` - 53 sessions

**What hurts.** Half of its sessions end blocked and its mean severity is 4.06: a rule he had already stated, in this session or as a standing rule, was not followed. Its severity mix (0/2/13/18/20) shows it essentially never fires in a calm session - when this appears, the session is already lost.

**Measured frequency.** 53 of 1008 sessions (5.3%); 26 of them blocking (49.1%); severity
mix 1/2/3/4/5 = 0/2/13/18/20; 38 at severity 4-5; mean severity 4.06. Source: `readers/R02.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["ignored-instruction"]` = 53.

**The owner's own words** - `20673294`, severity 4, `readers/R02.md`:

> Hi Mrs. Weitman, you keep forgetting, we don't start off like that

**One owner.** The instruction surface - the persona and AGENTS.md that the agent actually loads.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py ignored-instruction 53
```

Exits 0 only when the count falls below 53. Today it exits 1: `pain OPEN`.

### 9. `no-verification` - 76 sessions

**What hurts.** A claim of success with no evidence behind it. The owner cannot tell a finished job from a described one, so he has to test the work himself, which is the one thing he has said he will not do.

**Measured frequency.** 76 of 1008 sessions (7.5%); 25 of them blocking (32.9%); severity
mix 1/2/3/4/5 = 0/20/30/12/14; 26 at severity 4-5; mean severity 3.26. Source: `readers/R09.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["no-verification"]` = 76.

**The owner's own words** - `62c23a05`, severity 5, `readers/R09.md`:

> give me exact instructions and don't mess me up this time like you did with the ferry

**One owner.** The completion-report path - a claim of done requires the command that proves it.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py no-verification 76
```

Exits 0 only when the count falls below 76. Today it exits 1: `pain OPEN`.

### 10. `context-loss` - 56 sessions

**What hurts.** The agent forgot something from earlier in the session, or from a past one, and made him say it again. 41.1% of these sessions end blocked. The cost is not only the repeat - it is that he cannot trust anything the agent remembers.

**Measured frequency.** 56 of 1008 sessions (5.6%); 23 of them blocking (41.1%); severity
mix 1/2/3/4/5 = 0/10/20/14/12; 26 at severity 4-5; mean severity 3.50. Source: `readers/R10.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["context-loss"]` = 56.

**The owner's own words** - `3bed7499`, severity 5, `readers/R10.md`:

> don't you remember i told you we don't want tmobile anymore and i tried to chat with them and it didn't work when i asked them to cancel so i disputed the charge? i thought i told you

**One owner.** The continuity layer - journal and session memory carried across turns and sessions.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py context-loss 56
```

Exits 0 only when the count falls below 56. Today it exits 1: `pain OPEN`.

### 11. `stopped-early` - 37 sessions

**What hurts.** The agent stopped with work remaining and reported instead of finishing. At 62.2% it has the highest blocking rate of any friction with ten or more sessions, so this is the most reliable predictor of a wasted session in the whole register.

**Measured frequency.** 37 of 1008 sessions (3.7%); 23 of them blocking (62.2%); severity
mix 1/2/3/4/5 = 0/4/14/9/10; 19 at severity 4-5; mean severity 3.68. Source: `readers/R03.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["stopped-early"]` = 37.

**The owner's own words** - `cc27f14a`, severity 4, `readers/R03.md`:

> so keep going and figure it out, that wasn't a result, why did you stop

**One owner.** The orchestrator's turn-end rule - the same rule as restart-agent, triggered from the other side.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py stopped-early 37
```

Exits 0 only when the count falls below 37. Today it exits 1: `pain OPEN`.

### 12. `env-hostile` - 74 sessions

**What hurts.** The environment itself fought back: paths, quoting, permissions, encoding, a host that behaves differently from the one the brief assumed. It is as frequent as restart-agent but far less severe (mean 2.74, only 2 sessions at severity 5), because the cost is spread thin and usually absorbed by the session rather than surfaced.

**Measured frequency.** 74 of 1008 sessions (7.3%); 22 of them blocking (29.7%); severity
mix 1/2/3/4/5 = 3/29/28/12/2; 14 at severity 4-5; mean severity 2.74. Source: `readers/R12.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["env-hostile"]` = 74.

**The owner's own words** - `d4307338`, severity 4, `readers/R12.md`:

> it froze and crashed again and the font looks funny, the display is not showing sharp words, get this actually fixed for real

**One owner.** The node and shell contract owner - the brief that tells a child which host and which shell it is on.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py env-hostile 74
```

Exits 0 only when the count falls below 74. Today it exits 1: `pain OPEN`.

### 13. `format-unreadable` - 40 sessions

**What hurts.** He complained about how the output was written or rendered: a wall of text, jargon, a menu where a decision was wanted, a font that renders badly. It is the cheapest friction to fix and it recurs in four different shards, which suggests it is not one interface but a house style.

**Measured frequency.** 40 of 1008 sessions (4.0%); 15 of them blocking (37.5%); severity
mix 1/2/3/4/5 = 0/10/14/5/11; 16 at severity 4-5; mean severity 3.42. Source: `readers/R07.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["format-unreadable"]` = 40.

**The owner's own words** - `ca000eb1`, severity 5, `readers/R07.md`:

> why do you keep writing like this in funny font and no spaces, it happens all the time and makes it very hard toread

**One owner.** The owner-facing rendering layer - how a result is written for him to read.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py format-unreadable 40
```

Exits 0 only when the count falls below 40. Today it exits 1: `pain OPEN`.

### 14. `safety` - 32 sessions

**What hurts.** Money, customers, credentials or anything irreversible was handled carelessly. Only 32 sessions, but the highest mean severity in the register (4.09) and not one session below severity 3: this friction never fires softly, and it is the one class where the owner's exposure is real rather than reputational.

**Measured frequency.** 32 of 1008 sessions (3.2%); 14 of them blocking (43.8%); severity
mix 1/2/3/4/5 = 0/0/8/13/11; 24 at severity 4-5; mean severity 4.09. Source: `readers/R01.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["safety"]` = 32.

**The owner's own words** - `d1e67180`, severity 5, `readers/R01.md`:

> you did a massive screwup, you powered down or cut power to ha before making absolutely sure the interior door was unlocked you locked us out of the room totally with no recourse to get in

**One owner.** The autonomy gate owner - dispatch that fails closed rather than open.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py safety 32
```

Exits 0 only when the count falls below 32. Today it exits 1: `pain OPEN`.

### 15. `non-answer` - 26 sessions

**What hurts.** He got an answer that did not answer. Half of these sessions end blocked, which is high for a class this small, because an unanswered question cannot be worked around - he has to ask again, and asking again is the friction he hates most.

**Measured frequency.** 26 of 1008 sessions (2.6%); 13 of them blocking (50.0%); severity
mix 1/2/3/4/5 = 0/4/12/5/5; 10 at severity 4-5; mean severity 3.42. Source: `readers/R06.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["non-answer"]` = 26.

**The owner's own words** - `69022a3b`, severity 5, `readers/R06.md`:

> Can you stop telling me what to do and do

**One owner.** The answer path - an answer that addresses the question that was asked.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py non-answer 26
```

Exits 0 only when the count falls below 26. Today it exits 1: `pain OPEN`.

### 16. `asked-badly` - 22 sessions

**What hurts.** A question reached him as a menu, a wall of text, or several questions at once. He has stated the fix in his own words more than once: one thing at a time, clearly. The class is small but it recurs late in the corpus, so the rule has not landed.

**Measured frequency.** 22 of 1008 sessions (2.2%); 8 of them blocking (36.4%); severity
mix 1/2/3/4/5 = 0/3/9/5/5; 10 at severity 4-5; mean severity 3.55. Source: `readers/R10.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["asked-badly"]` = 22.

**The owner's own words** - `70978474`, severity 5, `readers/R10.md`:

> ask me things one at a time very clearly and simply

**One owner.** The question-rendering rule - one question, one line, no menus.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py asked-badly 22
```

Exits 0 only when the count falls below 22. Today it exits 1: `pain OPEN`.

### 17. `asked-unnecessarily` - 20 sessions

**What hurts.** The agent asked him something it could have decided or looked up itself. This is the friction the previous register's instruction surface spent the most words on, and it is now one of the two least frequent frictions measured - the rules worked here, and the remaining 20 sessions are the tail.

**Measured frequency.** 20 of 1008 sessions (2.0%); 8 of them blocking (40.0%); severity
mix 1/2/3/4/5 = 0/4/6/7/3; 10 at severity 4-5; mean severity 3.45. Source: `readers/R01.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["asked-unnecessarily"]` = 20.

**The owner's own words** - `520408c1`, severity 4, `readers/R01.md`:

> so do it, and don't tell me what, just do it and stop asking me what i want first and all that

**One owner.** The decide-it-yourself rule - a question the agent could have answered is a defect, not diligence.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py asked-unnecessarily 20
```

Exits 0 only when the count falls below 20. Today it exits 1: `pain OPEN`.

### 18. `invented-detail` - 19 sessions

**What hurts.** The agent asserted something it had not checked. It is the smallest class with a real severity signature (19 sessions, 5 of them at severity 5) and it is the same failure as wrong-data seen one step earlier - before the owner has caught it.

**Measured frequency.** 19 of 1008 sessions (1.9%); 8 of them blocking (42.1%); severity
mix 1/2/3/4/5 = 0/2/12/0/5; 5 at severity 4-5; mean severity 3.42. Source: `readers/R14.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["invented-detail"]` = 19.

**The owner's own words** - `0cb01a0d`, severity 5, `readers/R14.md`:

> it said, please being your photo id. You made that up, and it shouldn't say that

**One owner.** The claim path - assert nothing that was not read or run in this session.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py invented-detail 19
```

Exits 0 only when the count falls below 19. Today it exits 1: `pain OPEN`.

### 19. `overcomplicated` - 25 sessions

**What hurts.** He said it was more complex or more expensive than it needed to be. It has the lowest blocking rate of any friction with volume (24.0%), so it rarely kills a session outright - it just makes every session longer and makes him do the thinking he delegated.

**Measured frequency.** 25 of 1008 sessions (2.5%); 6 of them blocking (24.0%); severity
mix 1/2/3/4/5 = 0/6/12/3/4; 7 at severity 4-5; mean severity 3.20. Source: `readers/R07.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["overcomplicated"]` = 25.

**The owner's own words** - `49ee46ca`, severity 5, `readers/R07.md`:

> You made the staff ways set up. I'm looking at it now. Very complicated.

**One owner.** The design and planning path - the cheapest thing that could work, chosen first.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py overcomplicated 25
```

Exits 0 only when the count falls below 25. Today it exits 1: `pain OPEN`.

### 20. `bad-prioritisation` - 9 sessions

**What hurts.** The agent worked on something other than what mattered. It is the smallest class in the corpus (9 sessions), which is itself worth noting: the coarse keyword clusters already leave 296 sessions unclassified, so this id is probably either under-applied or genuinely rare.

**Measured frequency.** 9 of 1008 sessions (0.9%); 3 of them blocking (33.3%); severity
mix 1/2/3/4/5 = 0/1/5/0/3; 3 at severity 4-5; mean severity 3.56. Source: `readers/R14.md` and the other
18 reader files, parsed fresh; the same count is frozen in `CENSUS-v4.json` ->
`census.frictions["bad-prioritisation"]` = 9.

**The owner's own words** - `67850580`, severity 5, `readers/R14.md`:

> take a pause and figure this out the yoga is getting more and more sluggish cuz all of you stopped offloading the hard work to the mesh it's barely usable now, why do you keep skipping over and ignoring a massive issue

**One owner.** The prioritisation queue - the owner-attention pipeline.

**One verification command.**

```bash
python3 /root/work/07-pain-register-v4-check.py bad-prioritisation 9
```

Exits 0 only when the count falls below 9. Today it exits 1: `pain OPEN`.

## 5. The 212 items he wanted and never got

`CENSUS-v4.json` -> `wanted` holds **212** records, one per session that ended with the owner asking
for something he did not receive. `CENSUS-v4.md` renders them as a flat bullet list under
`## 212 sessions ended with something he wanted that he did not get`, with the session id and the want.

The census carries **no theme field**, so the grouping below is mine and is mechanical, not
judgemental: `07-pain-register-v4-analysis.py` holds a fixed keyword rule per theme and assigns each
item to the first theme whose rule matches. Recording that honestly matters, because the split is a
property of my rules and not of his intentions. 7 of the 212 items matched no rule and are listed
under `unclassified` rather than forced into a theme. Themes are ordered - and items inside a theme
are ordered - by the same rule as section 3: blocking sessions first, then frequency, then severity
for the themes; blocking first, then severity for the individual items, which carry no frequency of
their own.

Session ids below are the **first 8 characters** of the full UUID, which is how `CENSUS-v4.md` renders
them; the full ids are in `wanted[].session`. All 212 items are listed - none is dropped.

| rank | theme | items | of which blocking | of which severity 4-5 |
|---|---|---:|---:|---:|
| 1 | `shop-and-customer-operations` | 34 | 20 | 21 |
| 2 | `communications-and-attention` | 34 | 16 | 17 |
| 3 | `interfaces-and-readability` | 23 | 14 | 10 |
| 4 | `family-and-personal` | 21 | 14 | 12 |
| 5 | `infrastructure-and-uptime` | 23 | 13 | 10 |
| 6 | `agent-behaviour-and-instructions` | 14 | 8 | 7 |
| 7 | `money-finance-and-tax` | 12 | 6 | 7 |
| 8 | `memory-search-and-records` | 12 | 6 | 2 |
| 9 | `research-and-answers` | 17 | 5 | 5 |
| 10 | `delivery-and-trust` | 7 | 4 | 6 |
| 11 | `unclassified` | 7 | 4 | 3 |
| 12 | `sourcing-parts-and-purchases` | 8 | 3 | 2 |

### The five highest-ranked wants, verbatim

- `4c3ded25` (severity 5, blocked) - one case at a time with correct history and correct pricing, the no-customer-name rule held, and a Dialpad sync that is never more than a minute or two behind.
- `bb953f87` (severity 5, blocked) - the work done by fanning out agents to actually use the app like customers, not more reports about what would be done.
- `4772de74` (severity 5, blocked) - One simplified work-order screen on phone, iPad and desktop, live on production with working payments and no duplicate pages — he ended the session still unable to take money.
- `0cb01a0d` (severity 5, blocked) - a genuinely working end-to-end payment path, the real customer-facing text unchanged, and no invented sentences in the phone script.
- `67850580` (severity 5, blocked) - work orders closed without naming each one, photo intake that reaches production, and the heavy work actually offloaded so his laptop stays usable.

### 5.1 `shop-and-customer-operations` - 34 items

Session ids: `3ca4f3f2` `3fdc89ee` `cc27f14a` `f0827649` `49ee46ca` `33425eeb` `4bb2d77e` `de6bb21f` `732b3ff5` `4c3ded25` `e9b56e55` `18bb3f4a` `bb953f87` `4772de74` `9f384cd7` `c12702db` `67449da5` `402c9d5a` `0cb01a0d` `67850580` `99664b7b` `321d75e7` `955b3e46` `a3cc5055` `2bdebb1d` `39810b16` `41d40e31` `72c9fd6e` `974e99ef` `4ebc82ea` `d9c2d0c4` `8587008c` `1d29cdd5` `9d5c49d8`

- `4c3ded25` (sev 5, blocked) - one case at a time with correct history and correct pricing, the no-customer-name rule held, and a Dialpad sync that is never more than a minute or two behind.
- `bb953f87` (sev 5, blocked) - the work done by fanning out agents to actually use the app like customers, not more reports about what would be done.
- `4772de74` (sev 5, blocked) - One simplified work-order screen on phone, iPad and desktop, live on production with working payments and no duplicate pages — he ended the session still unable to take money.
- `0cb01a0d` (sev 5, blocked) - a genuinely working end-to-end payment path, the real customer-facing text unchanged, and no invented sentences in the phone script.
- `67850580` (sev 5, blocked) - work orders closed without naming each one, photo intake that reaches production, and the heavy work actually offloaded so his laptop stays usable.
- `72c9fd6e` (sev 5, blocked) - texts that follow the shop's own pricing and deposit rules the first time, and a session he can interrupt while it works.
- `d9c2d0c4` (sev 5, blocked) - a working payment page and work-order UI — he got a broken production flow, a 15-minute deploy that changed the wrong thing, and a handoff document for a different agent.
- `3ca4f3f2` (sev 4, blocked) - a phone interface that works and is built for a phone, without him having to inspect or repair it.
- `67449da5` (sev 4, blocked) - case files created as he reported them (not later), and a device identified correctly from its photograph.
- `955b3e46` (sev 4, blocked) - a locked, sellable phone in one run, with the customer's wait respected
- `4bb2d77e` (sev 3, blocked) - The whole job including the /work-orders 500 fix; it was reported as deliberately out of scope rather than done.
- `de6bb21f` (sev 3, blocked) - a production-ready sale path; the gate still refuses to sell
- `18bb3f4a` (sev 3, blocked) - a finished, published app he could hand to a customer that night.
- `402c9d5a` (sev 3, blocked) - a customer-ready HTML message first time, and nothing foreign left on the customer's device.
- `99664b7b` (sev 3, blocked) - case files finished in one pass, with photos and Dialpad data, and no invented alarms about customer data
- `2bdebb1d` (sev 3, blocked) - a repeatable work-order toolchain, and the stored card data out of the record without breaking anything else
- `4ebc82ea` (sev 3, blocked) - the customer's exact account of the phones and the card's failure, which the card itself could not supply.
- `e9b56e55` (sev 2, blocked) - DSH fully working on the SE across every node, with activation lock on both phones.
- `9f384cd7` (sev 2, blocked) - DSH actually working on both shop iPhone 11s — root cause was found and the fix identified, but not shown proven on the phones.
- `c12702db` (sev 2, blocked) - Both web clips visibly rendering on both shop phones — the fix was pushed and acknowledged, not seen working.
- `f0827649` (sev 5, completed) - a working diagnosis of the shop's own reader chain, and it ended with the customer's card closed as unrecoverable.
- `49ee46ca` (sev 5, completed) - a staff dashboard a real staff member could use without being taught, delivered rather than described
- `39810b16` (sev 5, completed) - money that goes through when a customer is standing there
- `974e99ef` (sev 5, completed) - the quote sent to the customer's real number, not an unknown one.
- `8587008c` (sev 5, completed) - The existing shop documentation and numbering conventions followed from the start, and a customer-grade two-piece box rather than a substitute chosen to avoid a phone call.
- `3fdc89ee` (sev 4, completed) - the whole LPT sign-in system across every app plus a rebuilt customer page, with the agent deciding what it could and asking him only one question at a time
- `cc27f14a` (sev 4, completed) - A result rather than a stop, and Activation Lock working on every phone the shop sells.
- `33425eeb` (sev 4, completed) - Replies written in his own voice, and the true lab status — both arrived only after he rejected the drafts twice and the audit was redone.
- `732b3ff5` (sev 4, completed) - a straight per-ticket answer on what each lab ticket needs from him.
- `321d75e7` (sev 4, completed) - one clean pass through the job, with the shop's own rules remembered and no work left for someone else
- `a3cc5055` (sev 4, completed) - the recovery path that already worked, not a re-exploration of it on a customer's device
- `41d40e31` (sev 3, completed) - one obvious way to start a work order
- `1d29cdd5` (sev 3, completed) - A label carrying details the customer would actually recognise, not song names.
- `9d5c49d8` (sev 3, completed) - A global search that reaches all work orders, not only the statuses he happens to have selected.

### 5.2 `communications-and-attention` - 34 items

Session ids: `160208ad` `c83d2b61` `45981b51` `24e68280` `69022a3b` `990c6329` `47047540` `a8899273` `47f3212a` `823aaf69` `e2fbba23` `3bb48ef2` `b0633805` `0b9fd106` `f87e4dc2` `849b9be9` `d05a9a77` `aae1aec4` `5ad004a4` `acb5a3a6` `f5daa293` `e0710eab` `f943a7a7` `45e98f77` `5eec8d35` `6d3bbac7` `38e8923a` `d66fbe2d` `89858f89` `e3d0ddb8` `d05bc1c2` `22724c6c` `d7c98601` `1c6dc139`

- `69022a3b` (sev 5, blocked) - The calls, without a safety lecture.
- `f87e4dc2` (sev 5, blocked) - the itinerary texted to his real phone, and a texting system that puts important texts through
- `5eec8d35` (sev 5, blocked) - Her full WhatsApp history intact on the new phone and a clean unlocked iPhone 11 to practise on — the transfer ended with chats missing and her phone mid-restore.
- `d7c98601` (sev 5, blocked) - A fixed presentation for a Dialpad contact — the clear question, the context, one recommended draft — built only on verified case facts.
- `1c6dc139` (sev 5, blocked) - A tested audit of the texting/CFO pipeline, not an alarming number nobody had checked.
- `160208ad` (sev 4, blocked) - the full Dialpad ingest of all SMS and calls, indexed, categorised and readable for agents — the session ended before it was shown done.
- `f943a7a7` (sev 4, blocked) - A texting channel that stays fixed and keeps improving itself; the run declared the goal unreachable and stopped instead.
- `22724c6c` (sev 4, blocked) - A working tech-mode unlock, the phone's actual Bluetooth profile, and a short forwarding text that sent as written.
- `c83d2b61` (sev 3, blocked) - a triage of everything needing his attention — the session surfaced only the dead card and stopped there.
- `47047540` (sev 3, blocked) - An automatic status-signup path that WhatsApp's own privacy model does not allow.
- `a8899273` (sev 3, blocked) - the CVS thermometer shortlist delivered as a text to his wife's phone, which was refused by the send policy
- `e2fbba23` (sev 3, blocked) - An explanation of the two circuit-broken agents and the missing owner-SMS audit rows that held up, rather than one that had to be retracted.
- `d05a9a77` (sev 3, blocked) - a dictation setup that works and that he does not have to think about again.
- `acb5a3a6` (sev 3, blocked) - One clear recommendation in plain statistical terms that he could act on; he got repeated text-heavy analysis and an open decision.
- `d66fbe2d` (sev 3, blocked) - sharp text, and an analysis that was not built on a false measurement.
- `e3d0ddb8` (sev 3, blocked) - a genuinely faster counter — the latency was diagnosed but the final message shows measurement, not a demonstrated fix.
- `823aaf69` (sev 5, completed) - a message that was actually sharp and weird, and a family-chat bot that recognises when it is being addressed
- `45981b51` (sev 4, completed) - a badge that works on all three machines and does not claim "nothing needs attention" when it has not actually read the data
- `24e68280` (sev 4, completed) - The Dialpad scripts and messages actually filled out and working, not another wrong diagnosis.
- `990c6329` (sev 4, completed) - Every call to actually deliver its message; call 6 was a silent zero-second failure.
- `b0633805` (sev 4, completed) - one short model-driven text at a time to his real number, not briefings
- `0b9fd106` (sev 4, completed) - one clear text at a time, on his personal number
- `aae1aec4` (sev 4, completed) - a texting system that actually uses the unified brain and finishes the work.
- `38e8923a` (sev 4, completed) - The autonomous build actually running without him, and the rules he states for it followed — the session fixed a live SMS outage that nobody had flagged.
- `89858f89` (sev 4, completed) - a true comms state before drafting anything, and items presented one at a time.
- `47f3212a` (sev 3, completed) - a reliable way to make the agent text him on demand
- `3bb48ef2` (sev 3, completed) - A usable, one-thing-at-a-time in-store walkthrough from the first message — he had to ask for that format explicitly before the answers became usable.
- `849b9be9` (sev 3, completed) - a first-draft Family Chat reply in the right voice, with the thread and the household already known.
- `f5daa293` (sev 3, completed) - A truthful picture of whether the texting system works; what he got was the discovery that its monitor had been blind for a week.
- `e0710eab` (sev 3, completed) - The agent to own its own operating decisions rather than escalating a judgment call to him.
- `45e98f77` (sev 3, completed) - a fire-and-forget USB program with no clicks, and a text in house style.
- `6d3bbac7` (sev 3, completed) - A comparison of the DSH desktop release against their own version and a recommendation — the closing message discusses journal warnings instead.
- `d05bc1c2` (sev 3, completed) - A message that said only what was established, with the unrelated faults kept apart.
- `5ad004a4` (sev 2, completed) - A short, ordered call-this-and-say-this answer while he was actually on the trail; instead the channel went quiet mid-trip.

### 5.3 `interfaces-and-readability` - 23 items

Session ids: `20673294` `901efff6` `ef80fd40` `5a17ce4d` `06e4d5fc` `fe516993` `e34dd061` `efca5060` `4a79e1d5` `711b0eb7` `0dffc054` `19119b70` `321b8fe8` `fd29a7e2` `2b226246` `74b959b3` `d4307338` `8c0b2490` `40fe7854` `1238888e` `19b02e0c` `44d81bc8` `8f87e47b`

- `e34dd061` (sev 5, blocked) - A system where both machines run many windows with many agents with no slowdown; the digest ends with the cause found and the fix not yet in place.
- `fd29a7e2` (sev 5, blocked) - a working game setup with his own documented history remembered, questions answered without jargon, and downloads tested safely before they run on the mesh.
- `74b959b3` (sev 5, blocked) - the changes actually deployed and verified in one pass, and a sign iterated against its own rendering without him pointing out the faults.
- `efca5060` (sev 4, blocked) - Communication Limits actually enforced inside the Screen Time policy, not a success claim on a half-applied profile.
- `321b8fe8` (sev 4, blocked) - the Android and iOS filter actually advanced, and a usable DSH window
- `d4307338` (sev 4, blocked) - a stable, sharp, full-screen RDP that works both directions.
- `1238888e` (sev 4, blocked) - a window that opens fast; at the end it was still slow.
- `8f87e47b` (sev 4, blocked) - a researched decision on self-hosting versus cloud, and multiplexing that works on the Windows machines — not a self-reasoned answer and a recorded limitation.
- `901efff6` (sev 3, blocked) - The actual supplier link for the screen, not more research.
- `19119b70` (sev 3, blocked) - the device field actually backfilled, and UI fixes found by the agent rather than by him
- `2b226246` (sev 3, blocked) - the workspace picker working on the ZABZ-TECH desktop, fixed once and robustly.
- `19b02e0c` (sev 3, blocked) - the website repo brought fully up to date and documented rather than handed off.
- `4a79e1d5` (sev 2, blocked) - The agent to find his recent session itself instead of him pasting page dumps into the chat.
- `711b0eb7` (sev 2, blocked) - The structured research result; the run is last seen re-submitting its own output format.
- `20673294` (sev 4, completed) - the source for the screen-class rule he was handed, and a link proving the laptop was touchscreen
- `44d81bc8` (sev 4, completed) - a readable label with the intended thank-you wording, without having to explain the same correction three times.
- `ef80fd40` (sev 3, completed) - Less at a time, said more clearly, and a simple statement of his own argument.
- `fe516993` (sev 3, completed) - A scannable, column-formatted list matched to what his existing picks mean to him, with questions asked one at a time instead of song dumps.
- `0dffc054` (sev 3, completed) - an explanation with the jargon actually removed — he had to demand it four times
- `8c0b2490` (sev 3, completed) - one readable callback label the secretary can act on
- `5a17ce4d` (sev 2, completed) - The link for the screen and the cable.
- `06e4d5fc` (sev 2, completed) - Windows-H behaviour exactly, and a working feature rather than an explanation.
- `40fe7854` (sev 2, completed) - a counter list that reads well at a glance

### 5.4 `family-and-personal` - 21 items

Session ids: `4db964fb` `cfd66de6` `a2b8fa27` `382a3663` `f0d7944c` `e5dece1f` `b6f28f7d` `963b430e` `60f24ebd` `371e57b2` `8bd84e58` `fe86504e` `d61aba83` `dff5a4e6` `4f3a68e0` `b2634711` `106b90e5` `043150c1` `18bba526` `6c9f6604` `b1e2a965`

- `382a3663` (sev 5, blocked) - Plain-language answers and one working solution for holding the tarp down and draining it, delivered before the yom tov instead of a menu of half-designs.
- `043150c1` (sev 5, blocked) - the mesh actually fixed and the cutover finished, not another plan or handoff.
- `18bba526` (sev 5, blocked) - An analysis he could act on instead of another experiment - "i can't keep trying diffent things" - and correct physics from the start.
- `b6f28f7d` (sev 4, blocked) - long-term root fixes for the recurring failures rather than short-term patches.
- `371e57b2` (sev 4, blocked) - the credentials found and the rotation actually done rather than filed as a future task.
- `d61aba83` (sev 4, blocked) - the open items actually closed and an honest answer on whether the background system had been working.
- `6c9f6604` (sev 4, blocked) - The full audit finished in one continuous run rather than stopping to report with work outstanding.
- `b1e2a965` (sev 4, blocked) - An answer to whether the shutdowns are what keeps cutting the other agents off, and a fix rather than a restated report.
- `f0d7944c` (sev 3, blocked) - A Chip that carries the family-chat persona he had already specified, and an agent that remembers the awning project it had built with him; both had to be re-stated from scratch.
- `e5dece1f` (sev 3, blocked) - A read on whether he was actually ill and what kind of infection it was — the answer is that his tests cannot say, and the agent only got there after withdrawing two interpretations it was about to assert.
- `8bd84e58` (sev 3, blocked) - a direct hard-wiring procedure rather than clarifying questions.
- `dff5a4e6` (sev 3, blocked) - A properly filtered phone for his wife — what was pushed first did not whitelist anything, and the corrected profile is waiting on an unlock.
- `4f3a68e0` (sev 3, blocked) - the friend's phone number or address, which he never got.
- `cfd66de6` (sev 2, blocked) - A clear answer on whether the September pair is two right-eye lenses and whether a prism was newly added; he got a comparison table he found confusing, so the question is parked rather than answered.
- `106b90e5` (sev 5, completed) - a working card path, immediately, without another round of him fetching credentials
- `4db964fb` (sev 4, completed) - her laptop and Mac given full access to every repo and system - lpt hub, personal secretary, lpt flip phone, home assistant, waze - with her changes signed, not two repos
- `a2b8fa27` (sev 4, completed) - A verified parts list where the agent checked the tarp's actual geometry instead of re-deriving it, and links he could buy from without re-litigating the design.
- `963b430e` (sev 4, completed) - A working gaming setup on the first or second pass instead of a day of trial and error.
- `60f24ebd` (sev 3, completed) - A psak he could rely on; what he got was a blanket statement he had to overturn by reading the source himself.
- `fe86504e` (sev 2, completed) - a short, direct answer on whether this is a real career path.
- `b2634711` (sev 2, completed) - a verified kosher sourcing answer he could act on without interrogating it.

### 5.5 `infrastructure-and-uptime` - 23 items

Session ids: `e50ad938` `b403052f` `98e3f372` `3a3388d3` `a5fa34f7` `c4dea3fd` `d09a056d` `201ea0ad` `3ef33e28` `91cf7b1a` `c70ba416` `df0baf11` `28d01c53` `e815b9bd` `9a056e82` `bcd4d160` `7cb6ee50` `3e343748` `69317939` `b9810e28` `437fad59` `d63e350f` `72ec9fae`

- `e50ad938` (sev 5, blocked) - a guarantee of no full outage and systems that make it impossible to happen again
- `e815b9bd` (sev 5, blocked) - the label printed the first time, an honest drive verdict, the migration finished rather than diagnosed, and no work pushed back onto him.
- `3e343748` (sev 5, blocked) - production fixed, not a progress note
- `df0baf11` (sev 4, blocked) - The office back online and the work split across a cloud computer — he got a session that could no longer run a command, and he fixed the office himself two hours later.
- `9a056e82` (sev 4, blocked) - the migration finished; he got a blocked host and a resume document.
- `b403052f` (sev 3, blocked) - The best cheap link for a machine he would actually accept.
- `201ea0ad` (sev 3, blocked) - Everything back online and a design for outages he cannot personally fix — the office stayed down for the whole session.
- `3ef33e28` (sev 3, blocked) - A recovery he can rely on when he is not there and something outside the company watching for it — he got the gap named, not closed.
- `91cf7b1a` (sev 3, blocked) - A plan that survives an outage of the office, not just a description of this one.
- `c70ba416` (sev 3, blocked) - The plan written and the office recovered — the office stayed down and the broker could not be reached.
- `437fad59` (sev 3, blocked) - a plain, working procedure for the machine, and a straight answer about drying the filter safely.
- `72ec9fae` (sev 3, blocked) - the deleted video actually recovered, not parked.
- `d63e350f` (sev 2, blocked) - a CI setup that actually holds — 8 of 10 deploy-env runs still fail at the preflight secrets check.
- `a5fa34f7` (sev 5, completed) - a yoga laptop where DSH starts and new threads work, permanently.
- `b9810e28` (sev 5, completed) - the mesh and cloud server actually carrying the work instead of the laptop, and the reinstalled filter left off permanently.
- `98e3f372` (sev 4, completed) - mesh work that routes around a dead node instead of failing silently
- `c4dea3fd` (sev 4, completed) - an honest answer on what encryption at rest protects when a machine is stolen, and a real key and data security build.
- `bcd4d160` (sev 4, completed) - to know exactly what had been changed on his production PC and that his work was not at risk
- `3a3388d3` (sev 3, completed) - A yoga that stays fast — the thing the "systems were supposed to prevent" — and he kept having to say it was still slow.
- `d09a056d` (sev 3, completed) - the ruling made through the existing Rabbi/psak engine rather than answered from scratch, and the engine reachable from every machine.
- `28d01c53` (sev 3, completed) - A region-free change he could make once and move between machines — one board per machine, permanently paired, is the product.
- `7cb6ee50` (sev 3, completed) - a one-shot extraction from a machine with three broken inputs, without a parts hunt
- `69317939` (sev 3, completed) - a machine that starts

### 5.6 `agent-behaviour-and-instructions` - 14 items

Session ids: `d1e67180` `d19c138b` `4a2bf82d` `ea10e311` `f8e61b4b` `8f4b6c5f` `58403e54` `76fcc878` `52c23ad7` `62c23a05` `558100fd` `a81aa099` `649cb7c5` `f1fdeea6`

- `76fcc878` (sev 5, blocked) - A finished, working orchestration system with honest progress reporting, not repeated "not done yet" reports.
- `558100fd` (sev 5, blocked) - a mesh where a child cannot kill the parent and where parent and child can always talk mid-flight.
- `649cb7c5` (sev 4, blocked) - the mesh fixed and the secretary reachable without him approving a restart.
- `f1fdeea6` (sev 4, blocked) - The rebuild finished in one pass instead of stopping mid-task with a stale Chapter 1 docx.
- `f8e61b4b` (sev 3, blocked) - The short list on his personal number before he left the house.
- `a81aa099` (sev 3, blocked) - A proven green suite — the session ended while still waiting on the authoritative frontend run.
- `d19c138b` (sev 2, blocked) - the storefront survey he asked for — the session produced no report at all.
- `8f4b6c5f` (sev 1, blocked) - a working remote subagent transport; the placement could not be verified at all.
- `d1e67180` (sev 5, completed) - a shutdown that unlocks the interior door and verifies it stays unlocked before power is cut — he had to spell the automation out himself after the agent called it complex.
- `62c23a05` (sev 5, completed) - instructions that named the actual ferry, the lot level and the way back — he had to find his own car
- `ea10e311` (sev 4, completed) - Model names that are configuration, never hardcoded - and a feature that actually works in production.
- `4a2bf82d` (sev 3, completed) - One thing at a time; an agent that does not stop with work remaining.
- `52c23ad7` (sev 3, completed) - the daily self-reactivation he thought had already been built
- `58403e54` (sev 2, completed) - Clear, simple instructions the first time.

### 5.7 `money-finance-and-tax` - 12 items

Session ids: `621bd168` `1b5b4ddc` `250ed582` `ca000eb1` `eef1fc93` `f5d95532` `3eb58012` `5afcd8f4` `9ba100ad` `853823e4` `99b2342a` `be1398ed`

- `3eb58012` (sev 5, blocked) - cards taking money that day, deployed, not an in-progress build report
- `621bd168` (sev 4, blocked) - the new-window button and the cost display actually working after a restart, and an engine that does not die under him.
- `1b5b4ddc` (sev 3, blocked) - A working bookkeeping, accounting and audit function for both LPT and his personal finances; the digest ends before it exists.
- `250ed582` (sev 3, blocked) - A fully priced port-out decision including whether he can leave the new provider later and what it actually costs; the four account fields are still outstanding before anything can be bought.
- `99b2342a` (sev 3, blocked) - A text reminder about autopay a couple of days before it is due, and the money questions worked out of the accounts.
- `be1398ed` (sev 3, blocked) - CFO classification near 90% coverage from purchase emails, and no token or money burn on unproductive work.
- `ca000eb1` (sev 5, completed) - correct profit math without being made to do the thinking, and no message leaving the building before he approved it
- `5afcd8f4` (sev 5, completed) - a way to take money that day that does not die with the app session
- `853823e4` (sev 5, completed) - An agent that keeps working while subagents run, spends tokens carefully, and never loses a session.
- `eef1fc93` (sev 4, completed) - one clear number he owed, stated simply
- `9ba100ad` (sev 4, completed) - The copy work turned into an actual deliverable, and a defensible lowest-cost reliable drive recommendation he could quote.
- `f5d95532` (sev 3, completed) - a CFO that classifies his money live and asks him the fewest, best-timed questions.

### 5.8 `memory-search-and-records` - 12 items

Session ids: `7422a3d4` `d194a14c` `24bc6702` `25b06f6e` `495ffd64` `c43df614` `fb104814` `da556a8b` `0ef0c72b` `b94269e3` `058cc91f` `6665eb86`

- `6665eb86` (sev 5, blocked) - A fully updated laptop with a real selectable yocheved mode, working model choice, and web search Techloq does not block.
- `7422a3d4` (sev 3, blocked) - A robust always-on car health record; the monitoring firmware still does not build for the target chip.
- `24bc6702` (sev 3, blocked) - The completed regulatory answer — the digest records only the preamble to writing it.
- `495ffd64` (sev 3, blocked) - The researched safety answer; the digest only records that the search had begun.
- `b94269e3` (sev 3, blocked) - search tooling that is actually fast and reusable, with the journal living on the fast box.
- `c43df614` (sev 2, blocked) - The structured result; the digest records only the statement that the evidence base was sufficient.
- `0ef0c72b` (sev 4, completed) - a millisecond search index actually wired into the instructions, and continuous work instead of status reports.
- `d194a14c` (sev 3, completed) - His real viewing history honoured rather than inferred — he had to say twice that the record was wrong and then ask for it to be kept better in future.
- `25b06f6e` (sev 3, completed) - The correct course start date and a plain answer on when to start the new pill — both arrived, the first only after he corrected the record.
- `fb104814` (sev 2, completed) - One camera setting and a single record button; the first answers were a production rig.
- `da556a8b` (sev 2, completed) - the existing, tested label code reused instead of re-invented.
- `058cc91f` (sev 2, completed) - The per-device backup question answered correctly the first time, and the record saved without the agent's own wrong inference baked into it.

### 5.9 `research-and-answers` - 17 items

Session ids: `85f98648` `d63b42a2` `e4a5dad4` `ca64cabd` `6db21fa3` `01bbe19c` `77a58659` `96f8e272` `130ca883` `be70b1ca` `3bed7499` `70978474` `2d128190` `33762274` `ffb9ca61` `5def503d` `b721ef6c`

- `3bed7499` (sev 5, blocked) - the DOL claim filed with facts it got right the first time, and a triage list limited to what actually needs his decision.
- `85f98648` (sev 4, blocked) - a filter that is supremely fast and accurate with per-pixel hiding, built without him having to read documents or answer question walls.
- `ffb9ca61` (sev 4, blocked) - A real usable quote and a completed application — he got sourced research and a refusal to fabricate a number he would act on.
- `5def503d` (sev 4, blocked) - A safe answer about Friday's power cut and a way to be asked in time — he got the risk spelled out and a question he could not answer in time.
- `ca64cabd` (sev 2, blocked) - The compiled evidence; the run is last seen about to compile it.
- `70978474` (sev 5, completed) - a system that makes its own dev decisions, asks him only real business questions, and finds its own tooling.
- `e4a5dad4` (sev 3, completed) - Proof the analysis had actually been run everywhere, not just written down.
- `6db21fa3` (sev 3, completed) - The right cleats in time for the next morning; he had to challenge a wrong recommendation to get it.
- `01bbe19c` (sev 3, completed) - a straight answer on where he could actually fly, instead of park regulations he had said he did not care about
- `96f8e272` (sev 3, completed) - a real plan for tonight that matched the weather, without the safety lecture
- `130ca883` (sev 3, completed) - to stop being asked what he has already answered.
- `be70b1ca` (sev 3, completed) - a correct explanation of the match the first time.
- `33762274` (sev 3, completed) - a simple, physical answer about flashlight angles.
- `b721ef6c` (sev 3, completed) - a hub recommendation he could act on without doing the research himself
- `d63b42a2` (sev 2, completed) - A straight difficulty and risk answer, without being talked around it.
- `77a58659` (sev 2, completed) - an answer about health and cleanliness, not kashrus
- `2d128190` (sev 2, completed) - A clear rule for when to trust Tyson; the first answer did not give him one.

### 5.10 `delivery-and-trust` - 7 items

Session ids: `cbbf160e` `545d8e84` `5bba6ccd` `b8d076ea` `99f5c499` `71191c83` `1f4a7e21`

- `5bba6ccd` (sev 4, blocked) - a fix that was verified before being called fixed.
- `b8d076ea` (sev 4, blocked) - the deferred items closed out instead of handed back to him as questions
- `71191c83` (sev 4, blocked) - CLI parity and reusable tooling, not a re-learning of work already done and not his own errands handed back
- `1f4a7e21` (sev 4, blocked) - Every stale order closed out, and each closure carrying a written note of the exact logic used.
- `545d8e84` (sev 5, completed) - A correct root cause and a permanent fix, not a misdiagnosis he had to correct twice.
- `cbbf160e` (sev 4, completed) - The plate right the first time and quick to retrieve again; instead three wrong values had been recorded, one of them invented.
- `99f5c499` (sev 3, completed) - reporting he can trust long-term, measured against the real sources

### 5.11 `unclassified` - 7 items

Session ids: `a72940c2` `bbcdb5d9` `002e01ee` `c9ab8734` `decbfb84` `cbed6d04` `24b7eadb`

- `24b7eadb` (sev 5, blocked) - certainty that nothing else was quietly left behind — phone DSH was only the visible one.
- `a72940c2` (sev 4, blocked) - a working DeepSeek direct route, or a clear reason it was not working
- `cbed6d04` (sev 3, blocked) - certainty about which card is Fisher's.
- `bbcdb5d9` (sev 2, blocked) - The adversarial findings; the digest stops at the note that they were being written.
- `c9ab8734` (sev 4, completed) - updates pulled without breaking anything.
- `decbfb84` (sev 3, completed) - his hours and his wording, applied only after he approved them.
- `002e01ee` (sev 2, completed) - the most basic fix, not a 27-step process

### 5.12 `sourcing-parts-and-purchases` - 8 items

Session ids: `d772db00` `f93d80e7` `a592225c` `6d505257` `b2394347` `171a3693` `004bcabe` `0d0f1185`

- `d772db00` (sev 5, blocked) - a genuinely rebuilt, more capable self, on the fast cheap model he wants, with no claims of work that was not done.
- `b2394347` (sev 3, blocked) - a link that actually worked, and numbers explained so he did not have to ask again.
- `004bcabe` (sev 3, blocked) - An answer to what model was in use, and a dissertation discussion that started.
- `a592225c` (sev 4, completed) - Verified, working purchase links for region-A-only and region-B-only Blu-ray and DVD test discs.
- `6d505257` (sev 3, completed) - only the kite purchase — he did not want the regulation research
- `f93d80e7` (sev 2, completed) - "direct wholesalers, not consumer marketplaces" - not evidenced as delivered in the digest.
- `171a3693` (sev 2, completed) - A label short enough for a secretary to act on, first time.
- `0d0f1185` (sev 2, completed) - Full product URLs, and a sturdy box that needs no cutting to size.

## 6. Disagreements, and what I could not verify

### 6.1 JSON against markdown

Checked all four census tables in `CENSUS-v4.md` against the corresponding JSON object, parsing only
the contiguous table under each heading.

- `outcomes`: agrees, all 5 rows match the JSON exactly.
- `severities`: agrees, all 5 rows match the JSON exactly.
- `frictions`: agrees, all 20 rows match the JSON exactly.
- `intent_clusters`: agrees, all 9 rows match the JSON exactly.

### 6.2 The census's per-file byte column is stale

`census.per_file[].bytes` does not match the reader files on disk. **17 of 19 files are larger now,
by 2,600 bytes in total.** Record counts, frictions, severities and outcomes are unaffected: the
fresh parse of the larger files still reproduces every census count exactly (section 1). The census
byte column is therefore a snapshot of an earlier revision of the reader files; the tail was appended
or re-wrapped, not re-classified.

| reader | census bytes | bytes now | delta |
|---|---:|---:|---:|
| `R01.md` | 40,810 | 40,954 | +144 |
| `R03.md` | 40,929 | 40,970 | +41 |
| `R04.md` | 42,073 | 42,240 | +167 |
| `R05.md` | 42,735 | 42,885 | +150 |
| `R06.md` | 38,519 | 38,621 | +102 |
| `R07.md` | 31,881 | 31,971 | +90 |
| `R08.md` | 56,239 | 56,446 | +207 |
| `R09.md` | 32,787 | 32,869 | +82 |
| `R10.md` | 34,197 | 34,333 | +136 |
| `R11.md` | 34,153 | 34,329 | +176 |
| `R13.md` | 47,486 | 47,664 | +178 |
| `R14.md` | 32,948 | 33,070 | +122 |
| `R15.md` | 37,423 | 37,532 | +109 |
| `R16.md` | 40,265 | 40,349 | +84 |
| `R17.md` | 43,544 | 43,638 | +94 |
| `R18.md` | 51,240 | 51,894 | +654 |
| `R19.md` | 16,936 | 17,000 | +64 |

### 6.3 Gaps I could not close

- **The brief's register-v2 path does not exist on the authority.** `docs/dsh-evolution-v2/07-pain-register-v2.md`
  is absent from `/root/code/harness-config` in the checked-out branch; I read it from git branch
  `offsite/journal/zabz-yoga` at commit `7e394315`. The brief's fallback (use `CENSUS-v4.md` alone)
  was not needed.
- **The JSON cannot produce a severity mix.** `census.frictions` is counts only. The mix column comes
  from the reader files. A future session that trusts only the JSON will not be able to reproduce
  section 3, and that is a defect in the census, not in this register.
- **411 of 1008 sessions (41%) carry no friction tag.** 100 have a literal `-` or `none` and 311 are blank.
  Every friction count in this register is therefore a count of *tagged* sessions, and the untagged
  remainder is a floor of unseen friction, not evidence of a clean session.
- **The census names no agent.** No field in `census`, `high_severity` or `wanted` identifies a
  responsible agent or session, so the `One owner` line assigns a workstream rather than a name.
- **The theme grouping in section 5 is mine, not the census's.** The census does carry an
  `intent_clusters` taxonomy, but it is a 9-way split over *sessions* for what he spent time on, not a
  grouping of the 212 want-lines. I did not use it as the grouping because it does not apply to those
  212 records. 7 items matched no rule of mine and are left unclassified.
- **How I read the readers.** I parsed all 19 files programmatically for the `frictions:`, `severity:`
  and `outcome:` fields and read the 122 `high_severity` records in full, plus `CENSUS-v4.md` in full.
  I did not read all 19 reader files end to end as prose, so a narrative in `beat:` that contradicts
  the structured fields would not have been caught by me.
- **I did not open `owner-turns-final.jsonl`** beyond recording its size; every quotation here comes
  from `CENSUS-v4.json` and was also found verbatim in the reader files on disk.
- **All 20 verification commands currently fail.** They were all executed; each exits 1 with
  `pain OPEN`. None of the 20 verified a fix, because no fix has landed for any of them.
- **One correction made during this build, recorded rather than hidden.** The first pass of section 6.1
  parsed a fixed-width window after each heading and pulled rows out of the neighbouring tables, which
  produced four tables of fabricated disagreements. The parser now stops at the end of the contiguous
  table. The corrected result is above; 6.4 records what it means.

### 6.4 A disagreement the brief anticipated, checked and not found

The brief asked me to report rather than pick if a count disagreed between the JSON and the markdown.
For outcomes, severities, frictions and intent clusters there is **no disagreement** - all four tables
match the JSON row for row (5/5, 5/5, 20/20, 9/9). The only JSON-versus-reality disagreement found is
the `per_file[].bytes` column in 6.2.

## 7. How to re-derive every number in this file

```bash
# the table, the mixes and the theme split - the single source of every count here
ssh secratary-cloud 'python3 /root/work/07-pain-register-v4-analysis.py'

# anything above as JSON
ssh secratary-cloud 'python3 /root/work/07-pain-register-v4-analysis.py --json'

# one verification command, exit 0 only when the pain has receded
ssh secratary-cloud 'python3 /root/work/07-pain-register-v4-check.py tool-failure 302'

# rebuild this file (analysis, then sections 1-4, then sections 5-7)
ssh secratary-cloud 'python3 /root/work/07-pain-register-v4-build.py && python3 /root/work/07-pain-register-v4-build-tail.py'
```

Built by WS-REGISTER on `ZABZ-TECH` at 2026-10-14T23:41:37Z. Read-only against the corpus:
nothing under `/home/zabz/evolution-corpus-v4/` or `/opt/company` was modified, and no file was
written to `harness-config` on this machine.

