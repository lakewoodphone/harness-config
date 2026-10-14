# 07 — The ranked pain register, round 3

**2026-10-14.** Supersedes `docs/dsh-evolution/07-pain-register.md` (round 1). Ranked by
**blocks work → recurs → owner-visible**, which is the order the owner pays in. Every row carries the
measurement that ranks it; every row names the number that must move to close it.

**Two corrections to the round-2 census that this register is built on, both measured this round:**
`tool-failure` at 67.3 % is an **upper bound on a mislabelled corpus** — `failures.jsonl` marks 2,716
rows `exit_nonzero` whose matched text reads *"exit code: 0"* and 2,282 `rate_limit` quoting a
successfully fetched page; the honest count is `err:true` = 7,491 of 54,730 (`L3798`). And every
rolling-window figure used below is taken from a **day-grouped** query, because
`> datetime('now','-N days')` against a `T`-format column silently covers N+1 days (`L3801`).

---

## The register

| # | pain | measured | blocks | owner | closes when |
|---|---|---|---|---|---|
| **1** | **Two always-alive agents, and the expensive one cannot prove its work.** CRON ledger loop: **0.0900 USD per closed-with-proof item**, 136 releases in a day, hard 150/day and 25 USD/day ceilings that demonstrably stop it. `/opt/company`: **~17.5 USD/day**, 533 of 786 work sessions failing in 7 days, and **242 of 266 "completions" fired because the task row was already closed**. `[ARTEFACT:]`/`[OUTBOUND:]` appear **0 times in 78,649 sessions**. | `09-wake-loop.md`, `company-truth.md` | everything in the company | me | ≥ 80 % of sessions close with a `proof`, or the direction is abandoned after 50 measured sessions |
| **2** | **The autonomy gate is fail-open.** `autonomy.py:376` returns **L4 (execute, no human)** for anything unclassified. 147 dispatcher names, 56 matrix rows. `hire_department`, `fire_agent`, `delete_tool`, `gv_send_sms` and the whole `shop_*`/`website_*` family run unattended. The built fix does not close it — **134 of its 150 rows are `default: 4`** and every name now has a row, so the fail-closed branch is unreachable. | `build-gate.md`, verified by subagent-10 | safety | me | **0** dispatcher names resolving to L4 without a named allow-list entry; asserted by a test |
| **3** | **The instruction surface has no source of truth.** `preset-drift.py` existed on **1 machine of 4**; **5 distinct revisions** of the `zabz` persona across repo+loaded trees; 9 of 13 files have more than one revision; the repo is **internally divergent** (`parallel-agent-orchestration` 10,802/7,852/13,275). The machine `host-posture.tsv` designates **primary loaded the oldest text of all four** — fixed this round (`W2814`), and **transiently**: `autosync.ps1` ships `git archive HEAD`, so the next pass restores it (`L3807`). | `11-instruction-convergence-plan.md`, `W2814` | every rule ever written | me | `preset-drift.py` exits 0 on every machine, and the correction is **committed** on each machine's sync lineage |
| **4** | **The journal has no source of truth either, and is diverging faster than it can be unioned.** 4 trees (4051 / 4037 / 3907 / 3440 entries); **63 ids mean two different entries**, every one minted today; `journal-union.py` **refuses** (exit 3) and is right to; a citation of `D3147` is ambiguous. **Neither available automatic rule can repair it** — mtime is a bulk-rewrite artefact on the authority and the body's first date is often a date the entry *mentions*; the two rules disagree on **27 of 63** and **13 tie** (`L3806`). | `12-journal-convergence-plan.md`, `L3806`, `P3181` | continuity, and every count of "open pain" | me | `journal-union.py` runs without refusing; ids host-banded so collision is impossible |
| **5** | **The tool-failure and env-hostile classes have no rule at all.** They are #2 and #4 of the measured frictions (round 1: 10.2 % and 7.2 %), and the live surface has **nothing** that says what to do when a command exits non-zero, times out, or returns garbage. Real failure families: `web` 4,204 (56.1 %), `edit` 816 (10.9 %). | `03-machine-sessions.md`, `10-instruction-surface-audit.md` §7 | every session that touches a tool | me | rules present, and the `web`/`edit` families falling |
| **6** | **The instructions spend their words on the failures that already improved.** `frustration` (6.58 %), `correction` (5.74 %) and `restart_agent` (2.05 %) appear **nowhere** in the persona or `AGENTS.md`, while the longest paragraphs serve "do not ask" — `asked-unnecessarily` 2.7 % + `asked-badly` 2.6 %, the **two least frequent** frictions measured, against approval-shaped turns falling 25 % → 2.38 %. Five of the predecessor audit's ten behaviours got **worse** across the migration. | `census-v2.json`, `05-copilot-delta.md`, `L3804` | every turn he spends correcting | me | `correction` + `frustration` below 6 % of his turns |
| **7** | **A fifth of the machine fleet does nothing and still pays.** **1,382 of 6,103** non-owner sessions made **zero tool calls**; **1,342 of those still billed a title-generation LLM call**. **165 of 690** mesh children produced `deliverables = 0`. | `03-machine-sessions.md` | cost, and the fleet's credibility | me | zero-tool share below 5 %; every child brief carries an output path and a checkpoint |
| **8** | **Silent failure has no transport.** `company-api` was **`active`, `NRestarts=0`, and answered nothing for 50+ minutes**; it was found only because the API was wanted for something else. `estate-monitor` computes `crit=5` every two minutes with **`escalated=0`**. 13 subsystems report `ok` with ≥ 500 consecutive empty ticks, and the counter increments on a blank-detail *success*, so it cannot mark anything failing. | `H3660`, `company-deadweight.md` | finding anything else | me | a deadline-checked probe against the service's own endpoint, and an escalation that fires |
| **9** | **Every rolling-window number in the estate is one day too long.** `created_at` is stored `…T11:05:01+00:00` (262,424 rows with `T`, **0** with a space) while `datetime('now','-1 days')` returns a **space**-separated string, and `'T'` sorts after `' '`. Same column, same minute: literal → 3,218 calls / 33.03 USD; `datetime()` → 5,023 / 45.45 USD. | `L3801`, and my own four corrected numbers | every report about cost or rate | me | one shared helper; a boundary test |
| **10** | **`wrong-data` remains the #1 measured failure and I committed it four times in one session.** 12.0 % of 961 sessions. My four: a predicate that matched the *denial* (`L3796`), a window straddling two timestamp formats (`L3801`), a measurement split on a file mtime instead of a process start (`L3803`), and a renumbering rule resting on a rewrite timestamp (`L3806`). **None was a wrong opinion; every one was a number that looked right.** | `census-v2.json`, `L3796` `L3801` `L3803` `L3806` | trust in everything reported | me | the rule is in the surface; the four held as the worked examples |
| **11** | **The open-work queues are not queues.** 162 pending owner rows, of which **80 come from one bulk job** (`lpt-work-order-sweep`) and **~120 are the agent's work wearing the owner's name**; two rows carry deferral notes reading *"SEAT-OWNED, not an owner decision"* and were left in his queue anyway. Separately: **344 / 437 / 453 / 568** "open pain" depending on which journal tree answered, **all four correct**. | `H3660`, `40-pains-triage.md`, `P3181` | his attention, which is the scarcest thing here | me | < 20 pending, 0 mis-filed; one journal tree |
| **12** | **Dead weight that is retried rather than retired.** `fleet_location_poll` dead since **2026-09-29** (414 consecutive failures). `amazon_sync`/`ebay_sync` fail `rc=127` — and that is a **missing `npm install` of a declared devDependency, so it is REPAIR not retire**; calling it dead would be wrong. | `company-deadweight.md` | the tick's signal-to-noise | me | the register shows it stopped retrying |
| **13** | **`git worktree`/fleet hygiene keeps costing real work.** Two children were killed mid-run this round and **lost everything they learned**; one died because **my own brief told it to stop if it landed on Windows**; and a child found that on ZABZ-YOGA **capturing `ssh.exe` output through a PowerShell pipe hangs forever** (only `Start-Process` with redirected stdio works). | this round's failures | the fleet | me | every brief carries the node contract and a checkpoint file |
| **14** | **Capability that exists on one machine only.** `journal-union.py`, `resolve-journal-merge.py` and `preset-drift.py` were each reachable from one checkout. A tool nobody has is not a guard. | `11-…plan.md`, `W2814` | detecting anything | me | each tool installed and runnable on every node |
| **15** | **The record's own health is unmonitored.** `journal.py check` = **0 errors, 261 warnings, 83 info**; `idguard` reports **0 collisions because it compares generated indexes in refs** while 63 exist in working trees. A guard answering about the wrong artifact. | `journal.py check`, `12-…plan.md` | the memory pillar | me | `idguard` reads working trees; warnings triaged |

---

## What is NOT a pain, stated so it is not "fixed"

* **The transcript archive.** Hourly systemd timer, gap and silence distinguished, credentials refused by
  name, redaction re-verified on arrival, 43,497 copilot-chat objects / 26.85 GB. It is the best-built
  thing here. **Leave it alone.** (Its `AGENTS.md` note says "14 chat files over 50 MB on ZABZ-YOGA";
  measured **5**, with 47 on ZABZ-TECH — the trap is real, the count is wrong.)
* **The journal's read path.** `status` 97 ms, `check` 0 errors, `search` refuses a short `journal.db` and
  falls back to files. It is not slow and it does not silently miss. **The defect is allocation, not
  reading.**
* **The approval loop.** 25 % → 2.38 %. The rules worked. Spending more words on it is the #6 error.
* **`lpt-production-case-work` on ZABZ-TECH** (18,009 B). Not drift: a **strict superset** of the reference,
  +79/−0. Take it.

---

## Who owns what

**Mine, and in this order:** #2 (safety, build in flight) → #3 (commit the correction so it survives)
→ #1 (the bridge: prove-or-measure) → #9 (reporting, zero risk) → #5 and #6 (the instruction build)
→ #4 (repair 63 by reading both sides) → #8 → #12 → #7 → #13/#14.

**His, and only his:** money, customers, legal posture, family, and anything irreversible. **Nothing in
this register is his** — every row has a named next action and a measurable close — which is itself the
finding: the previous three rounds pushed 595 things at him of which 383 were engineering faults.
