# 01 — The DSH corpus, measured

**Prepared:** 2026-10-13 · **Corpus:** `secratary-cloud:/root/authority.db` → `dsh_sessions`, `dsh_session_events`
**Artifacts:** `/home/zabz/evolution-corpus/` on the authority — `owner-analysis.json`, `OWNER-ANALYSIS.md`,
`owner-turns-final.jsonl`, `owner-sessions.tsv`, `machine-sessions.tsv`, `dispatch-sessions.tsv`,
`sessions-index.tsv`, `stats.json`, `tool-reliability.json`, `shards/`
**Scripts:** `~/code/_evolve/{extract_corpus,extract_tools,finalize_corpus}.py` — rerunnable, read-only.

**Predecessor for comparison:** `personal-secretary-mvp/docs/secretary-replacement-audit/01-copilot-corpus-audit.md`
(2026-09-11): 1,642 Copilot sessions, 26,950 owner turns, 593,203 tool calls, 14 months, 31.58 GB.

---

## 0. The headline

The DSH corpus is **6,927 sessions, ~2.03M events, ~1,300,000 tool calls, one month old**
(2026-09-11 → 2026-10-13). Three findings dominate everything else:

1. **Only 15.3% of it is the owner.** 1,059 of 6,927 sessions are sessions in which Eliyahu actually
   typed. 4,570 are headless sessions the mesh, cron and health probes create; **1,298 more are
   dispatches launched with his own interactive profile** (98.7% of them carry the `zabz` preset).
   The archive kept "for training data" is 85% machine noise, and any measurement of him taken
   without separating these three actors is wrong — including the first version of this one.

2. **The migration fixed the approval loop and made the churn worse.** Approval-shaped turns fell
   from 25% to **2.4%** — a 10× reduction, and the single clearest win of the move. But tool calls
   **per owner turn rose from 22.0 to 38.2** (+74%). He no longer has to answer a questionnaire;
   the machine now spends nearly twice as many actions per thing he says.

3. **17.09% of tool calls in his sessions come back as a failure signal.** 28,524 of 166,910. The
   dominant tool is the shell: `pwsh` alone is **40.65% of all calls** (67,851).

---

## 1. The three actors

| actor | sessions | turns | how identified |
|---|---:|---:|---|
| **the owner** | **1,059 (15.3%)** | **4,372** | `metadata_json.header.agentPreset` present, and the first turn is not a role brief |
| dispatches that borrowed his profile | 1,298 (18.7%) | 1,299 | first turn > 300 chars and opens `You are…` / `Your job…` / `READ-ONLY reconnaissance…`; **98.69% carry `zabz`** |
| headless (mesh child, cron, probe) | 4,570 (66.0%) | 4,569 | no `agentPreset` in metadata; 2,738 turns are probe-shaped (`reply with exactly …`) |

**Why this had to be measured rather than assumed.** The obvious filter — `source.kind == 'user'` —
returns 9,807 "turns" whose most repeated phrase is `reply with exactly meshprobeok and nothing else`
× 1,009, and in which 46% exceed 2,000 characters. `source.kind` cannot tell a person from a
dispatch; the session can. Frozen definition and evidence: header of `_evolve/finalize_corpus.py`.

**Defect this exposes:** `--profile zabz` is being used as a dispatch profile. 1,281 dispatched
children carry the owner's own interactive preset into the permanent archive. Nothing distinguishes
them from his sessions except the shape of their first message.

---

## 2. The owner, measured

| | DSH (2026-09-11 → 10-13) | Copilot (14 months) | |
|---|---:|---:|---|
| sessions | 1,059 | 1,642 | |
| owner turns | **4,372** | 26,950 | |
| owner turns per active day | **168.2** | 149.7 | ↑ |
| median turn length | **114 chars** | 62 chars | ↑ |
| **approval-shaped turns** | **105 = 2.4%** | 6,152 = 25% | **↓↓ the win** |
| **tool calls per owner turn** | **38.18** | 22.0 | **↑↑ the regression** |
| failure-signal tool results | **28,524 = 17.09% of calls** | (leak events 41,522) | new measure |

**Turn length distribution:** `<=20` 320 · `21-60` 910 · `61-200` 1,626 · `201-600` 644 ·
`601-2000` 236 · `>2000` 636. Median 114; p90 3,722; max 634,321.
The `>2000` bucket is dominated by **pasted web pages** (Amazon, Walmart, eBay listings) — he works
by pasting the page and asking for a judgement. That is a workflow the harness should support
natively and currently does not.

**Sessions by turn count:** 1-3 turns **798 (75%)** · 4-10 **173** · 11-30 **72** · 31-100 **14** ·
>100 **2**. Turns per session p50 = 1, p90 = 9, p99 = 44, max 245.
**Half his sessions are a single instruction.** The long ones are where the value and the misery are:
the 16 sessions over 30 turns are the ones to read.

**By machine:** `zabz-yoga` 585 · `zabz-tech` 257 · `secratary` 202 · `lakewooechsmini` 10 ·
`desktop-fgv6kmh` 5.
**By preset:** `zabz` 1,036 · `yocheved` 16 · `standard` 4 · `cordis` 2 · `cordis-bg` 1.

**By UTC hour and by day:** every day in the window except 09-12, 09-13, 09-19, 09-21, 09-26, 09-27,
10-03, 10-04. Peak days: 10-05 (441), 09-14 (412), 09-15 (408), 10-07 (365).

---

## 3. What he keeps asking for — intent signals on 4,372 clean turns

Rule-based, so reproducible; a turn can match more than one signal.

| signal | turns | share |
|---|---:|---:|
| `analyze` — analyse / investigate / find the root cause | 444 | 10.16% |
| **`keep_going`** — keep going, continue, don't stop, why did you stop | **321** | **7.34%** |
| **`frustration`** — again, still not, why do you keep, seriously | **285** | **6.52%** |
| **`correction`** — you missed, I said, that's not what, you forgot | **254** | **5.81%** |
| `options_rec` — recommend / what do you think / which is better | 249 | 5.70% |
| `document` — document this, write it down, update the docs | 184 | 4.21% |
| `remember` — remember, don't forget, next time | 130 | 2.97% |
| `explain` | 111 | 2.54% |
| `restart_agent` — you stopped, not to report back, keep working | 93 | 2.13% |
| `one_at_a_time` | 77 | 1.76% |
| `dont_edit` — hold on, wait, don't touch | 64 | 1.46% |
| `stop_reporting` | 7 | 0.16% |

**Reading.** `keep_going` fell from 9.9% to 7.34% — better, but **321 turns in 32 days is still
~10 restarts a day**, and it is still the largest owner-initiated corrective signal.
`stop_reporting` collapsed to 0.16%, which says the harness now reports far less.

**The new number is `frustration` + `correction` = 539 turns (12.3%).** The complaint changed shape:
he is no longer stopping an agent that halted, he is telling it that it got something *wrong* —
used the wrong data, misread him, or forgot. That is what the next evolution has to fix.

**Most repeated exact phrases (>=4), after cleaning:**

| phrase | n |
|---|---:|
| `keep going` | 64 |
| `send it` | 26 |
| `check on it now` | 10 |
| `i unplugged teh secretary server form the internet before is it back online now` | 7 |
| `seei if you can get them to turn back on or reconnect` | 7 |
| `send it and next` | 6 |
| `i think you froze` | 5 |
| `check on things now` | 4 |
| `did you freeze` | 4 |
| `okay next` | 4 |

`i think you froze` / `did you freeze` — **9 turns asking whether the agent is still alive.** That is
a hang, not a halt. It is a different defect from `keep going` and it is not in the persona at all.

---

## 4. Tools — 166,910 calls in his sessions

| tool | calls | share |
|---|---:|---:|
| `pwsh` | **67,851** | **40.65%** |
| `edit` | 18,118 | 10.85% |
| `read` | 17,575 | 10.53% |
| `write` | 12,714 | 7.62% |
| `bash` | 10,730 | 6.43% |
| `job_output` | 9,268 | 5.55% |
| `grep` | 7,586 | 4.54% |
| `web_fetch` | 2,312 | 1.39% |
| `mcp__secretary__ps_db_query` | 2,243 | 1.34% |
| `web_search` | 1,933 | 1.16% |
| `subagent` | 1,648 | 0.99% |
| **`subagent_local`** | **716** | 0.43% |
| `list_agents` | 594 | 0.36% |
| `job_kill` | 543 | 0.33% |
| `send_message` | 537 | 0.32% |
| `job_list` | 511 | 0.31% |
| `ask_user_question` | 332 | 0.20% |

Three things fall out of this table:

1. **The shell is the single largest cost in the system.** 67,851 `pwsh` calls. The persona's own
   measured figure is ~700 ms per trivial `pwsh` call — **≈13 hours of pure process start-up** in one
   month, before any command ran. 40% of the work of a "smarter than an IDE" harness is spent
   launching PowerShell.
2. **The agent polls its own job machinery 10,916 times** (`job_output` 9,268 + `list_agents` 594 +
   `job_kill` 543 + `job_list` 511). The Copilot era's `sleep`-in-a-chat-turn became `job_output`
   polling. Same anti-pattern, new costume.
3. **716 local fan-outs** against 1,648 mesh dispatches — 30% of fan-outs ran on this laptop despite
   the standing instruction to use the mesh. And `ask_user_question` at 0.20% confirms the
   questionnaire era is over.

---

## 5. Failures

28,524 failure-signal tool results inside the owner's sessions = **17.09% of his tool calls**. Per-tool
attribution, error kinds and the worst sessions are in `tool-reliability.json` and `failures.jsonl`;
the per-tool breakdown is folded in by `extract_tools.py`.

**Caveat, stated because it matters:** the count uses `isError` from the event plus a regex set
(exit code, not-found, timeout, sandbox-denied, connection, tool-error, rate-limit, overloaded). A
non-zero exit from `grep` with no match counts. So 17.09% is an upper bound on *real* failure and a
lower bound on *friction*: a tool that returns exit 1 correctly still cost a round trip.

---

## 6. The fleet's own corpus (4,570 sessions, 4,569 turns)

One turn each, mean 3,968 chars, p50 2,816 — a task brief. By cwd: `C:\Users\ezabz` 2,417 ·
the npx cache `…\_npx\1e7f6d9597241db0` 1,248 · `/home/zabz` 485 · `/Users/lpt` 230.
Peak days: 10-08 (484), 10-09 (375), 10-10 (375), 09-18 (357), 09-30 (334).

The dispatches: 1,298 sessions, mean 4,694 chars, p50 4,131, **98.69% on the `zabz` preset**.

---

## 7. Method, and what is not measured

* One streaming pass over `dsh_session_events` from `file:/root/authority.db?mode=ro` with
  `PRAGMA query_only=ON`. The authority database is never written.
* Every count recomputable: `_evolve/finalize_corpus.py` prints its own definition and gaps.
* **Not measured, and stated as a gap rather than a zero:**
  - token counts and true cost (no tokenizer was run over the corpus);
  - wall-clock latency per step (`step-timing.tsv` exists but has not been analysed);
  - the Copilot corpus was **not** re-parsed — its figures are the published ones from the
    2026-09-11 audit, and the raw JSON in `~/code/_audit/` was not re-derived.
* **Coverage of the qualitative layer:** 945 of 1,059 owner sessions (**89.24%**) are in the reading
  sample, across 18 shards (`shards/MANIFEST.json`). The remaining 10.76% are covered by the
  deterministic layer only. This is a stated sample, not "we read everything".
