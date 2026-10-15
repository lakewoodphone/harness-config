# PROGRAM v6 — DSH + AI-company evolution, round 6

**Opened 2026-10-15 14:0xZ on ZABZ-YOGA.** Round 6. The owner has now issued this command **four times**
(rounds 1–3, 4, 5, 6) — most recently 2026-10-15 with *"start again… it's never a problem to do the
whole thing again… make it even better."*

Rounds 4 and 5 are the spine. **Read, in this order, before touching anything:**

1. `docs/dsh-evolution-v4/HANDOFF-ROUND4.md` — the spine (§7 traps, §9 how to work with him, §10 what it got
   wrong).
2. `docs/dsh-evolution-v4/HANDOFF-ROUND5.md` — the delta.
3. This file — what round 6 adds, and what it deliberately does **not** redo.

---

## 1. What is genuinely done (verified by a command, not by a handoff)

| # | claim | the command that settles it | verdict |
|---|---|---|---|
| 1 | The live company tree is preserved in git | `ssh secratary-cloud 'git -C /root/work/r4-preserve log --oneline -1'` | `14ebb2322`, branch `preserve/live-tree-20261014` — **never delete** |
| 2 | Four workstreams (loop / transport / model / memory) are deployed | `ExecMainStartTimestamp` on `company-api.service` | deployed 2026-10-14T20:16:07Z |
| 3 | Corpus v4 + 19 readers + census exist | `/home/zabz/evolution-corpus-v4/` — 241 MB, `CENSUS-v4.{md,json}`, `readers/R01..R19.md` | **1,008 sessions read, 0 parse problems** |
| 4 | The pain register is built | `docs/dsh-evolution-v4/07-pain-register-v4.md` (995 lines) | built 2026-10-14T23:41Z |
| 5 | The journal id allocator no longer mints duplicates | `journal.py next-id pain` on the authority | **P3865** |
| 6 | The company is running | `company-api.service` active, `:8002` `/health` `{"ok":true,"database":{"ok":true}}` | **live, 2026-10-15T14:06:02Z** |

**Do not re-derive any of these.** Three rounds were spent re-deriving things that already existed;
that is the most expensive habit in this estate's history.

---

## 2. THE HEADLINE DEFECT, READ FRESH ON 2026-10-15 (this is the owner's #1 ask, still open)

The owner's words: *"I want the instructions and identities changed to better match what we really
need."* Round 5 fixed the instruction **chain** on ZABZ-YOGA only. Read again today, marker by marker:

| machine | live layer `<home>/.dsh/profiles/web/cordis.patch.yml` | mtime | `7b. When he corrects you` | `measurement rule, extended` | `read the failure before` | OLD `On any larger job` | `secratary-cloud` | `secratary-ts` |
|---|---|---|---|---|---|---|---|---|
| **ZABZ-YOGA** | live | 2026-10-15T14:04:12Z | ✅ | ✅ | ✅ | gone | 14 | 5 |
| **ZABZ-TECH** | live | 2026-10-15T01:39:12Z | ❌ | ❌ | ❌ | **present** | 11 | 5 |
| **ZABZ-TECH** | committed in repo | 2026-10-13T15:59:00Z | ❌ | ❌ | ❌ | **present** | 11 | 5 |
| **secratary-cloud** | live | 2026-10-12T00:19:10Z | ❌ | ❌ | ❌ | **present** | **3** | **3** |
| **secratary-cloud** | committed in repo | 2026-10-13T14:49:50Z | ❌ | ❌ | ❌ | **present** | **0** | **5** |

**One machine of three has the current instructions, and the machine that does not is the one the AI
company runs on.** The authority's *committed* persona names the frozen office box `secratary-ts`
five times and the authority `secratary-cloud` **zero** times.

That is a fact about what the AI company is instructed to do, not a cosmetic drift. It is round 6's
**first deliverable** and it is M6-A below.

---

## 3. Round 6 workstreams

| id | workstream | output | owner | done means |
|---|---|---|---|---|
| **M6-A** | the instruction & identity surface v6: rewrite the persona against the *measured* frictions, deliver it to **all three machines**, and make the delivery unable to silently skip | `presets/zabz/agent.cordis.yml` (regenerated), `profiles/web/*`, `scripts/sync.py`, `scripts/harness-verify.ps1` | **the manager (this session)** | the composed dump (`--dump-config`) on each of the three machines carries the new rules and none of the compressed ones, sha-verified |
| **M6-B** | integration, record, handoff | this file, `HANDOFF-ROUND6.md`, journal | **manager** | a fresh session can act from it |
| **R6-WANTS** | the owner's 212 "wanted and did not get" records + 122 severity-4/5 records → durable requirement classes, each checked against the live system today | `docs/dsh-evolution-v6/20-owner-wants.md` + `.json` | mesh child | every class has a verification command and a verdict: **still open / delivered / no longer wanted** |
| **R6-FRICTION** | evidence pack for the frictions the persona does not serve — `wrong-data` 116, `correction` 132, `repeated-work` 102, `restart-agent` 73, `tool-failure` 302, `no-verification` 76, `ignored-instruction` 53, `context-loss` 56, `env-hostile` 74, `format-unreadable` 40 — 3 verbatim quotes each + the mechanism in the harness | `docs/dsh-evolution-v6/30-friction-evidence.md` | mesh child | feeds M6-A; every quote has session id + reader file |
| **R6-COMPANY** | the company measured today: sessions by status 24 h / 7 d, failures classified by reason, marker counts, spend, cost per proven outcome; then `round4-loop-baseline.sh after` | `docs/dsh-evolution-v6/40-company-baseline.md` | mesh child | numbers only, each with the command and the window |
| **R6-JOURNAL** | the **453 open pain entries** and the **127 pending owner questions**: read each, test it against the live artefact, close the provably-dead, rank the live, and identify what is genuinely the owner's | `docs/dsh-evolution-v6/50-journal-hygiene.md` + `journal.py resolve` calls | mesh child | every open pain has a verdict; the owner queue holds only what is his |
| **R6-RECENT** | the corpus's blind spot: every owner session from **2026-10-13 to now** was never read by a reader. Read them with the same contract | `readers/R20..` + a delta census | mesh child | the newest sessions — the ones he was angriest about — are classified |

### The measured baseline round 6 is judged against

| measure | round-4 baseline (7 d, to 2026-10-14) | read fresh 2026-10-15T14:06Z (7 d) |
|---|---:|---:|
| work sessions | 578 failed / 259 completed / 33 paused | **487 failed / 294 completed / 50 paused** |
| 24 h | — | **44 failed / 77 completed / 20 paused** |

**Round 6 does not get to call the company "an order of magnitude better" on a 7-day trend it did not
move.** The number that has to move is `completed / (completed + failed)` and the cost per proven
outcome.

---

## 4. What round 6 deliberately does NOT do

* **Does not re-read the Copilot corpus.** The predecessor audit (`personal-secretary-mvp/docs/secretary-replacement-audit/`,
  git commit `51e2d32d`) read 1,642 Copilot sessions and this persona was written from it; rounds 1–3
  re-read them. The parsed copy is `authority.db` → `vscode_chat_sessions` (1,608 sessions / 4,373
  messages, newest 2026-09-18 — frozen because Copilot was retired). Round 6 reads it only to extract
  requirements the DSH-era work has **not** addressed.
* **Does not rebuild the corpus.** v4 exists and is good. Round 6 adds only the recent delta (R6-RECENT).
* **Does not rebuild the autonomy gate** — it is live and genuinely fails closed (round 4 §2.2).
* **Does not re-do the pain register** — it is built; round 6 acts on it.
* **Does not touch `secratary`.** `settings/machines/host-posture.tsv` decides; it is FROZEN.

---

## 5. Evidence rules round 6 holds itself to

1. **A claimed fix is a command and its output line.** Not a diff, not an mtime, not "should now".
2. **An mtime is not a deployment.** The process that loaded the code is (`ExecMainStartTimestamp`).
   And **a composed config dump is the only proof the surface the engine actually loads is right** —
   round 5 proved `--check` exit 0 can sit on top of a stale persona.
3. **A refusal is a correct answer; a confident wrong number is not.** `searched:false`, "no match" and
   "not verified" are three different sentences and must never collapse into one.
4. **A child's report is a claim.** The manager reproduces it before merge.
5. **The authority is read-only for analysis** and writable only for a deliberate, backed-up, verified
   deploy. No builds, no test suites, no corpus scans there.
6. **Danger-full-access is on in this session** — which removes a safety net, not a rule. Never
   `rm -rf`, never `git reset --hard`, never `git add -A`, never push `main`, never force.

---

## 6. Definition of done for round 6

Round 6 is done when **all** of the following are true, and not before:

1. The composed config on ZABZ-YOGA, ZABZ-TECH **and** `secratary-cloud` carries the v6 instruction
   surface, sha-verified, with the engine that loads it restarted or a named reason it was not.
2. `sync.py` **cannot** skip the profile layer with exit 0.
3. The composed-config check runs as a routine in `harness-verify.ps1`.
4. Every one of the 20 register pains has a verdict: fixed with a command+output, or filed with the
   reason it is not.
5. The 453 open journal pains have been read and either closed or re-filed as live, and the owner
   queue contains only what is genuinely his.
6. The company has a measured before/after with `completed/(completed+failed)` and cost per proven
   outcome, and at least one **deployed** change that moves a named row.
7. `HANDOFF-ROUND6.md` exists and a fresh session could start from it alone.
8. `journal.py check` is 0 errors.

---

## 7. ROUND 6 OUTCOMES — written 2026-10-15 15:2xZ, and this section SUPERSEDES §3's status column

**Read this against the file and the surface, never against §3's table.** A stale status line in a plan
document — round 4 §5 calling the instruction surface "not started" when it had been started and never
reached him — cost round 5 its first ten minutes. This section exists so that mistake is not repeated in
the other direction.

| workstream | outcome | the command that proves it |
|---|---|---|
| **M6-A** instruction & identity surface v6 | **DONE.** Ten numbered, checkable rules on all three machines; the authority's `brokerSsh` no longer defaults to the frozen office box; the authority can run its row generator at all. | `dsh --profile web --dump-config` on each machine, four v6 markers present and two compressed-away markers absent — `CURRENT` on ZABZ-YOGA, ZABZ-TECH and `secratary-cloud` |
| **M6-B** integration, record, handoff | **DONE.** `HANDOFF-ROUND6.md`, `90-what-is-needed-and-what-is-not.md`, journal `D3723 L4577 L4578 L4579 P4185 W3070 H4617`. | `journal.py check` → 0 errors |
| **R6-WANTS** owner wants | **DONE.** 212 wants → 25 clusters + an honest 2-want tail, each cluster carrying a verdict and the command behind it. Refuted a premise in its own brief. | `20-owner-wants.md` sha256 `db3ebe7c9133662a…`, byte-identical local and remote |
| **R6-FRICTION** evidence pack | **DONE.** 11 frictions (the brief said ten and listed eleven), 33 quotations verified by script, and the mechanism for the largest one found. | `30-friction-evidence.md` sha256 `2c3752d60ec25d4a…`; `30-proposed-rules.md` `8042659683d89523…` |
| **R6-COMPANY** measurement | **DONE.** Matched 18 h pre/post: **38.5 % → 54.9 % completed**; cost per completed session **0.6253 → 0.4172 USD (−33 %)**. n=113 clears §8's 50-session threshold, so the abandon condition is decidable and the answer is: the convergence change moved the number. | `40-company-baseline.md` sha256 `aafabeb8f2a62fae…`; every table carries its SQL and its window |
| **R6-JOURNAL** hygiene | **DONE, and it hit its own STOP condition deliberately.** 364 colliding ids measured; **it wrote nothing**, because converging five trees is a merge, not a sweep. Owner queue classified: 127 pending → **26 his / 101 ours**. | `50-journal-hygiene.md` sha256 `af84c85f82b471d9…` |
| **R6-RECENT** newest sessions | **DONE, and the brief was wrong.** Only **26** sessions in the window were genuinely new, not 86 — round 4's extraction ran past its own stated cut. True corpus total **1,008 + 26 = 1,034**, not 1,094. | `readers/R20..R22` (86 records, 0 parse problems, mergeable — proved by running round 4's own `reader-census.py`) |
| **C4** the company's architecture | **OPEN.** Two instrument defects have tested patches in flight; nothing was deployed in round 6. | `HANDOFF-ROUND6.md` §3 |

**Against §6's eight conditions: 2, 6, 7 and 8 are met; 1 is met with one caveat (the composed config is
verified on all three machines, but a RUNNING engine still holds the persona it booted with); 3 is
unmet; 4 is met in the only honest sense — all twenty frictions are disposed of, fourteen by a rule and
six by a filed reason; 5 is unmet by design** — the journal fork is round 7's first job, with the union
plan measured and a non-destructive merge in flight.

