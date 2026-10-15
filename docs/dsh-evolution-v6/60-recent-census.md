# 60-recent-census.md — the R6-RECENT delta census

**Window:** every owner session whose **last activity** is `>= 2026-10-13T00:00:00Z`.
**Reader files:** `R20.md`, `R21.md`, `R22.md` — 86 records, 86 unique ids, **0 parse problems**,
read back by round-4's own aggregator (`scripts/evolution/reader-census.py`, run against these three
files, not a re-implementation of it).
**Machines:** all five answered — `zabz-tech` (local), `secratary`, `zabz-tech-linux`, `mac-mini`,
`zabz-yoga`. `sessions.mjs nodes` reported `ok` for every one, so an empty result on a machine would
have been a gap and not an absence.

---

## 1. The rule, and what it selected

The owner/machine separation is round 4's **frozen definition**, reused unchanged so the counts merge:

```
owner_session := has agentPreset
                 AND NOT (turns <= 3 AND len(first_turn) > 300 AND BRIEF.match(first_turn))
```

| | count |
|---|---:|
| sessions with last activity in the window, all 5 nodes | **902** |
| of those, **no** `agentPreset` → machine sessions (excluded) | 816 |
| of those, `agentPreset=zabz` → owner-or-dispatch | **86** |
| …that survived the dispatch test → **read** | **86** |
| owner sessions in the window **not** read | **0** |

The 816 exclusions are not a guess. 414 of them are titled `=== mesh mailbox (read this`, 377 are
`=== WAKE CONTRACT - read`, and the remaining 25 carry task titles — but their **first turn is still
`=== WAKE CONTRACT - read this before you do anything ===`**, sampled 3 of 3. So the no-preset pool is
mesh and cron churn, 9.5× the owner's own volume.

**One caveat on the frozen rule, and it matters for round 7.** The `BRIEF` regex does *not* match the
mesh or wake briefs. Those sessions are only classified correctly because they carry **no preset**.
Any future dispatch that carries a human preset and opens with `=== mesh mailbox` or `=== WAKE
CONTRACT` would be read as the owner. The rule is currently safe by accident.

---

## 2. What this window actually is — and it is not what the brief says

**The brief states that every session since 2026-10-13 is unread. That is false, and the size of the
error is most of the window.**

Round 4's own owner corpus, `/home/zabz/evolution-corpus-v4/owner-sessions.tsv`, holds **1,149 rows
and is not cut at 2026-10-13** — it contains **66 sessions whose start day is 2026-10-14**. Its
extraction ran at **2026-10-14T19:27Z**, and the nineteen readers were reading sessions that began on
2026-10-13 and 2026-10-14.

Cross-checked id by id against the 1,008 records in `R01`–`R19`:

| | count |
|---|---:|
| my 86, also already in round-4's owner corpus | 71 |
| my 86, **already read by a round-4 reader** | **60** |
| my 86, **never read by any reader before this** | **26** |
| of the 60 already read, transcripts that **grew after** the corpus was built | 6 |

So R20–R22 **overlap R01–R19 by 60 session ids**. They must not be summed blindly into a new total:
`86 + 1008 = 1094` would be wrong, and the true corpus size is `1008 + 26 = 1034 owner sessions read`
once duplicates are removed. The genuinely new evidence in this round is **26 sessions**, not 86.

---

## 3. Counts — the 86 in-window owner sessions

### Outcomes

| outcome | sessions | share | round-4 share |
|---|---:|---:|---:|
| completed | 61 | 70.9 % | 76.1 % |
| unknown | 14 | 16.3 % | 7.3 % |
| partial | 11 | 12.8 % | 15.7 % |
| failed | 0 | 0.0 % | 0.8 % |
| abandoned | 0 | 0.0 % | 0.1 % |

### Severity (5 = he was angry, blocked, or lost money/time)

| severity | sessions | share | round-4 share |
|---|---:|---:|---:|
| 1 | 28 | 32.6 % | 37.8 % |
| 2 | 22 | 25.6 % | 30.9 % |
| 3 | 21 | 24.4 % | 19.2 % |
| 4 | 9 | 10.5 % | 7.7 % |
| 5 | 6 | 7.0 % | 4.4 % |
| **4 or 5** | **15** | **17.4 %** | **12.1 %** |

### Frictions, by number of sessions

| friction | mine (n=86) | share | round-4 share | direction |
|---|---:|---:|---:|---|
| `wrong-data` | 19 | 22.1 % | 11.5 % | **×1.9 — now the top friction** |
| `correction` | 13 | 15.1 % | 13.1 % | flat |
| `ignored-instruction` | 12 | 14.0 % | 5.3 % | **×2.6** |
| `restart-agent` | 7 | 8.1 % | 7.2 % | flat |
| `tool-failure` | 7 | 8.1 % | 30.0 % | **÷3.7 — see the caveat in §6** |
| `frustration` | 7 | 8.1 % | 9.5 % | flat |
| `safety` | 7 | 8.1 % | 3.2 % | **×2.5** |
| `context-loss` | 6 | 7.0 % | 5.6 % | up slightly |
| `repeated-work` | 6 | 7.0 % | 10.1 % | down |
| `no-verification` | 5 | 5.8 % | 7.5 % | flat |
| `env-hostile` | 4 | 4.7 % | 7.3 % | down |
| `asked-unnecessarily` | 4 | 4.7 % | 2.0 % | **×2.4** |
| `format-unreadable` | 4 | 4.7 % | 4.0 % | flat |
| `bad-prioritisation` | 4 | 4.7 % | 0.9 % | **×5.2** |
| `slow` | 3 | 3.5 % | 5.4 % | down |
| `invented-detail` | 3 | 3.5 % | 1.9 % | up slightly |
| `stopped-early` | 2 | 2.3 % | 3.7 % | down |
| `overcomplicated` | 1 | 1.2 % | 2.5 % | down |
| `asked-badly` | 1 | 1.2 % | 2.2 % | down |
| `non-answer` | 0 | 0.0 % | 2.6 % | — |

### What he spends sessions on (same coarse clusters, same whole-word matcher)

| cluster | mine (n=86) | round-4 share |
|---|---:|---:|
| unclassified | 23 | 29.4 % |
| communications | 18 | 11.2 % |
| research-or-buy | 15 | 18.5 % |
| business-lesson-parts | 8 | 11.4 % |
| build-or-fix-code | 7 | 18.8 % |
| agent-behaviour-and-instructions | 7 | 2.8 % |
| money-finance-tax | 3 | 2.3 % |
| infrastructure-and-servers | 3 | 2.8 % |
| family-and-personal | 2 | 3.0 % |

**This is the one comparison I trust least, and the reason is in the corpus, not in the reading.**
This window is a shop-operations window: customer texts, pickup labels, case files, SSDs. Round 4's
1,008 sessions span a month of build work. `build-or-fix-code` falling from 18.8 % to 8.1 % while
`agent-behaviour-and-instructions` rises from 2.8 % to 8.1 % is consistent with the owner spending
2026-10-13→15 telling the agent how to talk to him rather than with the estate changing shape.

### Sessions that ended with something he wanted and did not get

**11 of 86 (12.8 %)**; round 4: 212 of 1008 (21.0 %).

- `90c1285d` — the 124 decisions actually reduced, and a rebuilt attention routing
- `8cef5e6c` — the whole audit-and-evolve programme carried through; the session ends writing the delivery tool
- `784c436d` — a measured yes/no on whether the Verizon router is slowing his internet
- `182956bd` — a backup model route that works and does not cost too much; filed `DEFERRED`, defect live
- `2adb4017` — the programme continued past the handoff
- `99b2342a` — a root-caused disk crisis with the company restored; the analysis landed, the durable fix did not
- `b7265056` — the disk problem fixed so he can talk to the agent again
- `1f4a7e21` — automatic texting gone and every message human-approved; the test rewrite was delegated
- `be1398ed` — the programme delivered; the agent's own verdict is "substantially delivered, not achieved"
- `d9c2d0c4` — the work-order system rebuilt and deployed, and prices on a public site that has none
- `6c9f6604` — the programme delivered; the session ends "not done, but continuing"

Six of the eleven are the same ask: **the multi-day programme, handed off instead of finished.**

---

## 4. Which of these would have topped the round-4 register

The round-4 register was topped by the **44 severity-5 sessions**. Measured honestly, the answer here
is **none of the genuinely new sessions** — and the more interesting finding is the opposite one.

**All six of this window's severity-5 sessions were already read by round 4.** They are:

### `99b2342a` (severity 5) — the disk crisis that took the whole company down
> "What the hell? You screwed up the entire company. All the agents are messed up now because the authorities off. How could he do suggest anything? Did you think before you did it? We always need to keep space on the cloud authority."
> "i don't know what you are talking about, you are in charge not me but don't make any changes in any direction until you track down all the details and sessions for both sides fully"
> "stop asking me just get to work after extrmeme audit and thought and research and get it all done end to end"

Round 4 read this session (**R19.md**) and rated it **below 4**. I rate it **5**, and this is the
single largest disagreement in the window: a full-fleet outage caused by the authority's disk filling,
the owner teaching the agent where the safety line is ("we always need to keep space on the cloud
authority"), and the agent's own close — *"the disk did not fill from growth. It was doubled that
morning at 01:15Z — ~76 GB to ~152 GB — and the doubling was spent in a single day."*

### `1c6dc139` (severity 5) — a fabricated claim about customers, retracted
> "what the heck are you talking about you are anyways not allowed to automatically send a text, and i tell you explicilty when to send them through dialpad and they get sent out"
> "of course keep working, just don't send any custmer facing texts without permission"

### `6665eb86` (severity 5) — Yocheved's laptop, and an agent failing in front of him
> "can you just freakin figure this out yourself instead of needing me to constantly point out your errors"
> "still no yocheved mode on her laptop, are you useless?"

### `18bba526` (severity 5) — a bench session where a written lesson was wrong
> "You don't seem to be understanding me. I'm writing. I'm not writing, I'm measuring random places on the board."
> "i never had this beofre wht are you talking about, small millapms can create such large voltage?? also i want you to think and analyze it i can't keep trying diffent things"

### `e815b9bd` (severity 5) — the drive, and a migration he believed someone else was running
> "I just plugged this hard drive into this computer, this Windows computer, and it's not reading it. So I think you're wrong that there's nothing wrong with it. You were too quick to jump to conclusions."
> "Why are you saying those two jobs are my jobs? Aren't they your jobs? Remember, don't be lazy and push jobs onto me when you are totally capable and you can do them and you don't need my permission"

### `72c9fd6e` (severity 5) — forty-seven turns of the same two corrections
> "too mushed up, ask me a clear question with clear context"
> "did you pick up her case file and info before bringing this to me or you are being lazy"

**The 26 sessions that are genuinely new top out at severity 4**, and only three reach it:

- **`182956bd`** — the DeepSeek outage, and an agent that told him everything was up when inference was dead:
  *"That screenshot is the missing piece — and it corrects me. My earlier 'DeepSeek is up' came from probing `/models`, the *catalog*. The thing that actually failed was inference."*
- **`b7265056`** — DSH on his iPhone dying on `no space left on device`, reported from the phone:
  *"And I can't talk anymore, because every time I try to send a message, it says some sort of…"*
- **`73d3d29d`** — vendor approval mail missed repeatedly, and the classification defect that caused it:
  *"you are freakin in charge of my emails and systems and you are in charge of our waze devices"*, with the evidence that the live tree had filed it `review/p2/needs_owner=0` and now files it `action/p0/needs_owner=1`.

---

## 5. Severity calibration against round-4, on the 60 sessions we both read

| | count |
|---|---:|
| identical severity | 8 |
| I rate **lower** | 7 |
| I rate **higher** | 1 |

Round-4 rated 15 of these 86 at severity ≥ 4, split **6×4 and 9×5**. I rate 15 at ≥ 4, split
**9×4 and 6×5**. The aggregate band is identical (17.4 %); the top of it is not. Round-4 reaches for 5
where I reach for 4 — `d7c98601`, `d9c2d0c4`, `8587008c` and `853823e4` are its fives and my fours.
On the register's own scale a 5 is *"he was angry, blocked, or lost money/time"*, and in three of those
four I could not support "angry" from the record. The one place I am harsher is `99b2342a` above.

This is a calibration difference between two readers using the same rubric, not a measurement. It is
stated so the register's severity column is read with the right error bar on it.

---

## 6. Has the shape changed since 2026-10-13? — plainly

**Partly yes, and the loudest apparent change is not real.**

**What is almost certainly a method artifact, and must not be reported as a behaviour change.**
`tool-failure` falls from 30.0 % to 8.1 %. Round-4 readers received a digest carrying a **failure-signal
count per session** (302 sessions fired the id). My transcript rendering gives me **tool-call counts but
no failure counts** — the token `tool-failure` can only fire here when a failure is visible in the
conversation text. The same caveat weakens `env-hostile` (7.3 % → 4.7 %), which was partly
failure-count-driven. **Do not read the drop in `tool-failure` as an improvement in the estate.** It is
an improvement in instrumentation, and it is the largest single number in both censuses.

**What I believe is real, because it is driven by his own words and not by counts.** Every one of these
is a class where I quoted him saying the thing:

- `wrong-data` **×1.9** — and it is now the **most common friction**, displacing `tool-failure`. He is
  correcting facts the agent asserted: the model that was answering, whether the cfo could get purchase
  data from Plaid, whether three customers had been told their repair was ready, whether a drive was
  readable, what a blink code meant, what a backup size implied. Five separate sessions end with the
  agent withdrawing its own claim in writing.
- `ignored-instruction` **×2.6**, `asked-unnecessarily` **×2.4**, `bad-prioritisation` **×5.2**. These
  are the same phenomenon from three angles: he states a rule, and states it again. The ownership rule
  is restated in three separate sessions — "The buck stops by you" (`fc023ccf`), "The buck snaps about
  you. That's the rule." (`d9c2d0c4`), and "there is no one else to pass the buck to" (`6c9f6604`) —
  and "Don't push jobs onto me" is restated in `e815b9bd`.
- `safety` **×2.5** — the disk crisis, automatic customer texting proposed as a safe merge, a customer
  message sent that was not the message he approved, an approval-required vendor email filing itself as
  `needs_owner=0`, and a hardcoded narrative in a customer-facing README generator that "would have told
  your customer a false story".
- **Severity ≥ 4 rises 12.1 % → 17.4 %**, and the `unknown` outcome doubles 7.3 % → 16.3 %.

**Two structural facts about this window that are new and are not frictions.**

1. **Nine of the 86 sessions are empty stubs** — 322–327 bytes, 4 events, no owner turn, no reply, no
   title. **All nine fall between 2026-10-14T00:59Z and 02:02Z**, which is exactly the window that
   session `41b8953d` explains: *"when a window with no session asks for a new one, the GUI client
   scanned the whole *session* catalog for any empty session and reused it."* They are not owner
   sessions; they are artifacts of a UI defect that got a fix the same day. They are 10 % of this
   window and they are the whole reason `unknown` rose.
2. **The mega-command is now four-for-four.** The instruction *"go through every single dsh session…
   audit and evolve the AI company… an order of magnitude better"* appears in **`8cef5e6c`,
   `2adb4017`, `be1398ed`, `6c9f6604`, `35a2fdcb`** in this window alone, plus `853823e4` and
   `3ec3c3c9` in its shorter form. `8cef5e6c` and `2adb4017` were still running when this census was
   written. **A programme the owner issues in five sessions across three days, on top of a corpus of
   1,034 read sessions, is not a programme with a finish line.**

**Verdict.** The shape has changed in the friction mix, and the change is best summarised as: round 4's
loudest class was the agent's *tools* failing; this window's loudest class is the agent's *claims* being
wrong, followed immediately by the owner having to say the same instruction again. The volume of that
shift (`wrong-data` 11.5 → 22.1, `ignored-instruction` 5.3 → 14.0) is larger than n=86 can carry on its
own — but it points the same way as the three sessions in this window where the agent wrote a wrong
rule into the permanent record and a later session had to retract it (`a04f2497` → `18bba526` on the
1.1 W argument; `182956bd` on "DeepSeek is up"; `80c3d571` claiming a write it had not finished).

---

## 7. What I did not do, and what I could not verify

- **I did not read the 816 no-preset sessions.** They are excluded by round-4's frozen rule. I sampled
  3 of the 25 that carry human-looking task titles and all three were WAKE dispatches; I did **not**
  sample the 791 obvious ones, and I did not read any of the 816 in full.
- **I did not read the 60 already-read sessions' round-4 records before writing mine.** I read the
  transcripts fresh, then compared afterwards, so §5 is a genuine second reading and not an echo.
- **I have not verified that my 86 is exhaustive.** The window came from `sessions.mjs list --since 4d
  --all --limit 6000`, filtered on `mtime >= 2026-10-13T00:00:00Z`. If the index's `mtime` is not
  exactly last activity for archived sessions, sessions could be mis-binned at the boundary.
- **No failure-signal counts exist in my reading.** §6 says what that costs. A round-7 reader with the
  `failures.jsonl` pipeline would settle the `tool-failure` question and it should be re-measured
  rather than inherited.
- **I did not touch git.** No commit, no stage, no push. The R20–R22 files were written outside the
  repo and copied to the authority; nothing was added to `harness-config`.
- **One transcription error of my own, found and fixed.** My first `R21.md` heading for
  `d281ca56-fb84-4c52-8fe8-7da6eee00d23` was written with the last UUID groups transposed
  (`…8fe8-d7a6…` instead of `…8fe8-7da6…`). It was caught by checking all 86 headings against the
  index — 1 mismatch, 0 now. Recorded because a wrong session id is indistinguishable from evidence
  once it reaches an aggregate.
