# 08 — What was changed, and how each change was checked

**Prepared:** 2026-10-13 · **30 commits** on `harness-config` `main`, **305 files**, +16,131 / −368 lines.
Pushed to `evolution/dsh-audit-20261013`. The first commit is `75ffbeef`; the last before this file
is `5909162d`.

This is the record of the work, not a summary of the conversation. Every row names what changed and
**how it was verified** — and where a thing was *not* verified, it says so.

---

## 1. The documents

| file | bytes | what it is |
|---|---:|---|
| `00-SYNTHESIS.md` | 9,047 | the one-page answer: four numbers, three live breakages, one question that is his |
| `01-corpus.md` | 10,625 | 6,927 sessions measured; the three actors; the delta against Copilot |
| `05-instruction-redesign.md` | 19,615 | the design: two tiers, byte budget, rules to add, identity, the 30-day test |
| `07-pain-register.md` | 12,636 | the ranked friction from 945 sessions beside 393 open pains clustered |
| `07-target-system.md` | 8,401 | what the system is FOR, eight needs, six explicit *not*-needs |
| `10-instruction-surface-audit.md` | 13,225 | what the prompt says, duplicates, and is missing |
| `20-memory-continuity-audit.md` | 15,998+ | whether the journal can be trusted; the exact divergence measurement |
| `30-systems-and-autonomy-audit.md` | 13,681 | what runs, what is silently dead, what fails to alert |
| `PROGRAM.md` | 6,301 | the program, its method, its state log |
| `READER-BRIEF.template.md` | 5,187 | the contract used for the 18 reading children |

**Measured, not narrated.** Every number in the corpus document comes from one streaming pass over
`dsh_session_events` with `PRAGMA query_only=ON`, recomputable by
`~/code/_evolve/finalize_corpus.py`. Every qualitative claim comes from one of 18 mesh children that
read a shard and published its finding to the authority; `aggregate_readers.py` folds them and reports
`missing` and `suspiciously_short` rather than silently under-counting.

---

## 2. The instruction surface — changed and **verified loaded on every machine**

| what | before | after | how checked |
|---|---|---|---|
| `{cwd}` templating bug | live in every prompt, on every machine | gone | `(?<!\{)\{cwd\}(?!\})` = 0 in the **loaded** file |
| authority named | `secratary` (the frozen box) in 3 places | `secratary-cloud` | read back from `~/.dsh/.agent-presets/zabz/` |
| machine list | `zabz-tech-linux` = "a macOS mini for his employee Yisroel" | correct roles, posture file named | grep |
| the #1 failure | **no rule at all** | "The one you must not get wrong" | present in the loaded file |
| `repeated-work` (#3) | no rule | "look before you redo" | present |
| nine journal-proven rules | in **no** surface | in `AGENTS.md` §6–7, three skills | present in the loaded catalog |
| persona size | 28,697 B | 25,531 B **with two rules added** | byte count of the compiled prefix |

**Verified per machine, by reading the loaded file on each box:**

| machine | loaded `zabz` | `{cwd}` bug | wrong-data rule | skills |
|---|---|---:|---|---:|
| ZABZ-YOGA | 56,297 B | 0 | ✓ | 9 |
| ZABZ-TECH | 56,297 B | 0 | ✓ | 9 |
| secratary-cloud | 54,915 B | 0 | ✓ | 9 |
| lakewooechsmini | 54,915 B | 0 | ✓ | 9 |

(The Linux hosts read 54,915 where Windows reads 56,297 for identical content — CRLF vs LF.)

**Deliberately unchanged:** `zabz-tech-linux` (459/459 sessions carry no preset; it runs headless
children only — adding a preset would change a deliberate configuration) and `secratary` (the frozen
rollback anchor).

---

## 3. The fixes — and what is actually running

**Running in production, verified:**

| # | fix | where it runs | proof |
|---|---|---|---|
| 1 | **owner-question mirror** read from the FROZEN office box: 143 open where the authority held 162, with 11 answered rows shown as pending | `journal.py` on every machine | `questions` → **162/326**, matching a read-only count on the authority exactly |
| 2 | **`sessions.mjs`** had no `secratary-cloud` node — the session reader could not see the authority's 571 sessions | every machine | `nodes` now lists six, including the authority |
| 3 | **archive free-space guard** — the script's own defaults describe a 9 GB pass on a 75 GB disk with 6 GB free | `/opt/company/archive/tools/` | unit triggered: **exit 0**, ingested, 465 MB peak, disk steady; refuses at exit 3 on an absurd budget (stub test) |
| 4 | **answer path writes its own journal copy** — 14 of 67 answered rows had NO copy anywhere | `/root/bin/owner-queue.py` | isolated test in a throwaway DB + journal tree; **real journal unchanged at 378** |
| 5 | **estate monitor's critical conditions reach someone** — `oom_kills_24h` at a streak of 708 (23.6 h) told nobody | systemd timer, every 10 min | `P3021`–`P3024` filed; first scheduled run reports "nothing to file" (idempotent) |
| 6 | **`sync.py`'s refusal is audible** — the guard that hid two days of staleness now files a journal entry | each machine's checkout | 4-case isolated test; real journal entry count unchanged |

**Committed and verified, not deployed (they are tools a session runs):**

| # | thing | verified by |
|---|---|---|
| 7 | `preset-drift.py` — compares what a machine LOADS against the repo | 15 surfaces, 15 match, 0 drift on both machines |
| 8 | `reconcile-owner-answers.py` — backfills answers into the append-only record | 14 written as D3129–D3142; re-run reports **0 missing** |
| 9 | `test_mirror_freshness.py` / `test_sync_alarm.py` | both assert the real store is untouched |

**Journal, consolidated:** the union of the two largest trees — **3,664 → 3,813 entries**, 149 merged
from the authority, **0 modified, 0 overwritten, 0 duplicate ids**, `journal.py check` exit 0. Then
five `P316x` entries, ten `W27xx` wins, `L3771`/`L3773`/`L3774` lessons, and `D3127`–`D3142`.

---

## 4. Where I was wrong, kept in the record on purpose

Two wrong readings, both the failure this audit ranks **first** (`wrong-data`, 11.4% of sessions),
committed in the same session that wrote the rule against it. Both are in `AGENTS.md`, in `L3774`,
and corrected in every surface they reached.

1. **"The transcript archive has been dead since the cutover."** False. The store is at
   `/opt/company/archive/lpt-transcripts`, re-hosted 2026-10-12, and its 13:39Z pass had succeeded
   twenty minutes before I said otherwise. I checked two guessed paths and concluded from absence;
   `systemctl list-timers` would have answered it.
2. **"Alive but flapping."** Also false — the empty-name alarm I quoted came from a 13:23Z pass, and
   `04661ae` fixed it at 13:40:15, between that pass and the next.

And one partial-sample error: I reported the first 9 of 18 reading shards as if it were the census,
and `shop` moved from fifth to first when the rest landed (`L3773`).

**A pattern worth more than any single fix.** Four times, "correct in the repo" was not "correct where
it runs": the archive script, two `main` lineages, `owner-queue.py` 8.7 KB behind its deployed copy,
and — the worst — **the instructions themselves, two days stale on every machine**. That is now a rule
in `AGENTS.md` §6.1 and a checker in `scripts/preset-drift.py`.

---

## 5. What is still open, and none of it is blocked on information

| item | why it matters | next action |
|---|---|---|
| **the authority's checkout is on a feature branch** (`hk/28-refresh-deployed-sources-20261013`) | anything merged to `main` since that branch was cut is not on the always-on machine | converge it onto `main`; the union made this a fast-forward question, not a merge |
| **`preset-drift.py` is not scheduled** | the class it detects can recur silently; `sync.py`'s guard is now audible, but a machine whose *checkout* is stale has no detector | fold `--check` into an existing job, or add a timer |
| **the queue's filing guard** | ~137 of 162 pending rows are engineering; the queue's own doctrine says a row is "an admission that I could not", and nothing enforces it | a check at `add`, not a mass-close |
| **the desktop's engine version mismatch** | its sync reports "the RUNNING engine is 0.2.0-rc.2 but configuration names 0.1.5-rc.1" | re-pin or regenerate; found on the way, not part of this job |
| **capacity** | the authority is at 91–92% with ~7 GB free above a 25.9 GB database growing ~2.3 MB/h; reclaiming is much smaller than believed (`/root/git-rescue-20261012` is irreplaceable) | **row #473 — his to decide**, one question, with a recommendation |

---

## 6. Reproducing any of it

```
# the corpus
~/code/_evolve/{extract_corpus,extract_tools,finalize_corpus,aggregate_readers}.py
  on secratary-cloud; artifacts in /home/zabz/evolution-corpus/

# the journal and the owner queue
python journal/tools/journal.py status|check|list
python journal/tools/reconcile-owner-answers.py          # dry run by default
python journal/tools/test_mirror_freshness.py

# the loaded instruction surface, on any machine
python scripts/preset-drift.py

# the deploy path
python scripts/sync.py --dry-run
node scripts/make-preset-rows.mjs --check
python scripts/test_sync_alarm.py
```
