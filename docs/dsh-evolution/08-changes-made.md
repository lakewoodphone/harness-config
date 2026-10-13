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

## 4b. The second pass — eight more rounds, and the theme became the finding

Everything below was found *by* the work above, and every one of them is the same defect: **a thing
that was correct in one place and wrong where it counted.**

| # | what was wrong | fixed by | how it was checked |
|---|---|---|---|
| 10 | the corrected presets were on **no machine** — the authority loaded a two-day-old file still shipping the `{cwd}` bug, and `/root/.dsh/skills/` **did not exist** | `scripts/preset-drift.py`, then deployed | read back per machine: `cwd_bug=0`, rule present, 9 skills, on ZABZ-YOGA / ZABZ-TECH / secratary-cloud / the Mac mini |
| 11 | `sync.py` was **refusing correctly** and printing one line nobody reads | `make-preset-rows.mjs --install`; refusal now files a journal entry | isolated test, 4 branches; real journal entry count asserted unchanged |
| 12 | the **journal was two records** that disagreed (three sessions quoted three different open-pain counts, all correctly) | union in both directions, 149 + 341 entries + 6 status rows | both trees now: 3,819 entries, 401 open pain, status set difference **0**, `check` exit 0 |
| 13 | the authority ran a **`journal.py` without the fixes**, called by four deployed tools | deployed and committed (`8375e5f`) | diffed first — the only thing unique to the old copy was the bug it fixed; `questions` → 162/326 |
| 14 | **52 of 61 files in `/usr/local/bin` were in no repository** — `cron-wrap.sh` (58 cron uses), `estate-monitor.py`, `db-integrity-check.py` | captured 41 byte-exact + `MANIFEST.json` | `deployed-drift`: 8 → **47 compared**, 52 → **14 only-deployed** |
| 15 | two scripts were **ahead in the running location** — real work only on the host | recovered into the repo | neither deployed copy lacked a function the repo had |
| 16 | **two drift checkers, neither scheduled** | `sync.py` now ends by verifying what it deployed | 5 branches in a throwaway repo; rides on the existing `PersonalSecretary-HarnessSync` |
| 17 | the queue's filing doctrine had **no enforcement** | *nothing* — two designs measured and rejected | 0/161 and 3/137 recall; a regex cannot carry a judgement |
| 18 | `phone-gate-allow.txt` drifted by one address | *nothing* — it is **another session's in-flight edit** | `AGENTS.md` §6.1: the host is right; recorded as `H3619` |

**The numbers that were measured rather than asserted:**

| | before | after |
|---|---:|---:|
| machines loading the corrected preset | 0 | **4 of 4** |
| files in `/usr/local/bin` with no repo path | 52 of 61 | **14 of 62** |
| journal entries (both trees) | 3,478 / 3,663, disagreeing | **identical** |
| open pain (both trees) | 402 / 405, neither authoritative | **401 both** |
| drift detected per `sync` run | none | **every run, alarmed** |

**And the honest entries — things that were measured and then abandoned, which is the part a
"what changed" document usually omits:**

- **The queue filing guard was not built.** Two designs, both run against the live 162 rows: one
  would have refused **0**, the other caught **3 of ~137**. The mis-filed rows and the legitimate ones
  use the same phrasing ("I recommend merging PR #1" vs "I recommend adding disk"). A judgement had
  been mistaken for a pattern, twice, until it was measured.
- **The phone-gate allow-list was not deployed.** It differs from the running copy by exactly one
  address, and that copy was written three minutes before I looked by a session still committing.
  Writing over it would have been this program's own defect, applied to a live session.
- **Three checkers were found to have a scope limit of their own** — `preset-drift.py` compares bytes
  where `sync.py` normalises line endings; `assert-bin-matches-repo.py` hardcodes its authority alias;
  `deployed-drift.py`'s verdict depends on which checkout runs it. All three now say so in their own
  docstrings, because a checker that lies is worse than no checker.

---

## 5. What is still open, and none of it is blocked on information

> **Superseded by §7, which is current.** This table is the round-10 snapshot, kept because what a
> session believed at the time is part of the record — notably, it lists `preset-drift.py` as
> "not scheduled" as a *finding*, which is exactly the defect §4b then went and fixed.

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

# the deployed script surface (needs ssh to the host)
python scripts/deployed-drift.py
python scripts/assert-bin-matches-repo.py \
    --manifest scripts/deployed/authority-bin/MANIFEST.json

# the deploy path
python scripts/sync.py --dry-run
node scripts/make-preset-rows.mjs --check
python scripts/test_sync_alarm.py
```

---

## 7. Assessment against the four deliverables

| deliverable | state | evidence |
|---|---|---|
| (1) an evidence-based audit doc set | **done** | 11 documents, ~120 KB under `docs/dsh-evolution/`; every corpus number from one streaming pass, recomputable by `finalize_corpus.py` |
| (2) changed instructions and identities | **done** | presets, 3 skills, `AGENTS.md` §6–7, 9 journal-proven rules; **verified loaded on all four machines that load one**, read back per box |
| (3) built, verified fixes for the top-ranked pains | **done** | 8 fixes; 6 running in production with proofs; 3 checkers built and committed; 2 designs measured and rejected |
| (4) a refreshed memory/continuity system | **done** | journal unioned to **one record both trees** (3,819 entries, 401 open pain, set difference 0); 14 stranded owner answers recovered; mirror freshness fixed; the answer path writes its own copy |

**What is *not* done — follow-on work the audit surfaced, not unfinished pieces of the ask:**

| item | why it matters | next action |
|---|---|---|
| **the authority's checkout is on a feature branch** (`hk/28-refresh-deployed-sources-20261013`) | its `scripts/` are an old lineage; the journal it carries is converged, the repository is not | converge onto `main` — the journal union made this a fast-forward question, not a merge |
| **`deployed-drift.py` is not scheduled** | the script half can drift silently; `sync.py` now covers the *instruction* half only | a timer on the authority, or fold into an existing job |
| **`phone-gate-allow.txt`, one address** | the running copy lacks the authority's own entry; a session is actively editing it | whoever owns that work decides; recorded as `H3619` |
| **the desktop's engine version mismatch** | its sync reports "the RUNNING engine is 0.2.0-rc.2 but configuration names 0.1.5-rc.1" | re-pin or regenerate; found on the way |
| **the queue's ~137 engineering rows** | they demote the rows that are genuinely his; no regex can separate them (measured) | a reader decides per row, at the moment it is written |
| **capacity** | the authority is at 91–92% with ~7 GB free above a 25.9 GB database growing ~2.3 MB/h | **row #473 — his to decide**, one question, with a recommendation |
