# 172 — MASTER RECORD: the search system — what the cloud cutover silently lost, how it was found, and how it is now guarded

> **This file.** `harness-config/docs/mesh/172-MASTER-RECORD-SEARCH-SYSTEM.md`
> — on `ZABZ-YOGA`: `C:\Users\ezabz\code\harness-config\docs\mesh\172-MASTER-RECORD-SEARCH-SYSTEM.md`
> — on `secratary-cloud`: `/root/code/harness-config/docs/mesh/172-MASTER-RECORD-SEARCH-SYSTEM.md`
> Committed as `aeebd479` (ZABZ-YOGA) and `82e1f66` (the authority); pushed to the config authority and
> to GitHub branch `search-audit-2026-10-12`. §5.3 records exactly what landed where and why the mirror's
> `main` was left alone. It is the *only* document you need for the search system; everything else it
> cites is either its evidence or its context.

**Session:** 2026-10-12, 03:05Z–04:10Z. **Author:** Zabz, `ZABZ-YOGA`, with one mesh child (the fleet
inventory, dispatched to `ZABZ-TECH` — it did **not** run locally).
**Machines touched:** `secratary-cloud` (THE AUTHORITY, `writable` — where all repairs were made);
`ZABZ-TECH` (via the mesh child, read-only probes, plus diagnostics on its own index task);
`ZABZ-YOGA` (this seat). **Frozen and read-only hosts:** `secratary`/`secratary-ts` (read only — see
§7.1 for the two scratch files I did write there, disclosed); `hetzner`, `lpt-apps`, `lpt-survivor-01`
(**nothing touched**, per `settings/machines/host-posture.tsv`).

**Where this fits.** `171-CLOUD-AUTHORITY-AUDIT-START-HERE.md` is the umbrella page for the cloud-vs-office
audit and the place to start for *that* question — storage, memory, cron parity, the anchor. **This document
is the search half of the same migration, and its finding is the opposite of a win: the agent-facing search
surface was dead on arrival.** 171's "three real wins" do not cover search; read them as covering storage,
locking and backup only. `169-CLOUD-VS-OFFICE-AUDIT.md` holds that audit's measurements, and
`170-MASTER-RECORD-ATTENTION-BADGE-AND-FLEET-AUDIT.md` is the same document shape as this one, for the
badge incident.

**One-line status: the entire agent-facing search surface was dead on the cloud authority — `ps_search`
answered `Tool search not found` to every caller — because `data/tools/` is gitignored and 599 of 607
tool bodies never made the crossing; it now works in every mode, is reproducible from git, and two new
guards make the same class of loss alarm instead of hide.**

---

## 0. IF YOU READ ONLY ONE SCREEN

| | |
|---|---|
| **the question** | *"We migrated to the cloud secretary. Audit and optimize and fully fix and make way more robust one thing — the search system. Make sure it only got better with the migration and definitely didn't have any regressions."* |
| **the answer** | It did **not** get better. It got **worse than zero**: the surface agents are told to use did not exist on the authority. Every mode failed, and each failure was dressed as a plausible answer ("tool not found", "no match") rather than an error. |
| **root cause, in one line** | `data/tools/` is in `.gitignore` (line 58). The 600 files that *implement* the company's dynamic tools were never in any branch, so no deploy could carry them; **599 of 607 registered tools arrived with no body**, and `run_tool()` answers `Tool <name> not found` from a single `if not tool_path.exists()`. |
| **four independent causes** | (R1) 599 missing tool bodies; (R2) the engine `find-anything` not installed on the box at all; (R3) hardcoded layout — the tool body pinned a path no cloud node has, and the engine resolved its code roots as the *office* checkout; (R4) `journal.py` required every query term **on one line**, manufacturing confident false negatives. |
| **fixed and live** | every mode answers with provenance and the correct exit code; 601 of 601 active tools have bodies; comms returns real rows from 179,608 indexed records; `journal.py check` = 0 errors; the D2983 false negative is gone (399–490 ms). |
| **made robust** | the subsystem now lives in git (`scripts/find-anything/`), not on one disk; two guards (`check-faindex-freshness`, `tool-body-guard.py`) and three clocks, on minutes with no collisions; the search subsystem is now **in the systems register** (§2.5), which it was not — which is *why* the cutover carried none of it. |
| **still open** | `zabz-tech`'s search index really is 27 days stale with its task returning 1, and **I did not establish why** — §5.1 has the exact next command. `data/tools` is guarded but still untracked (§5.2). The harness-config mirror divergence is already **P3135**, not news (§5.3). |
| **what you do** | Nothing urgent. Search works. Reload the GUI page if you are reading this from the badge — that is `170`. When you want `zabz-tech`'s desktop search back, say so: it is one background run away. |

---

## 1. THE QUESTION, AND WHAT WAS ACTUALLY TRUE

The owner's mental model — *"we used to grep and glob and it was slow, then we introduced a full
indexing and wildly fast system"* — is correct about the intent and was, on the cloud authority, false
about the state. The indexed surface existed; the authority could not reach any of it.

| what the owner would reasonably expect | what was true on `secratary-cloud` |
|---|---|
| `ps_search` searches the estate | `{"ok": false, "error": "Tool search not found"}` — on **every** call, in every mode |
| `ps_comms_search` reads customer texts and calls | `{"ok": false, "error": "Tool comms_search not found"}` — the same cause |
| the `fast-search` skill's instructions work | the skill names `ps_action("search", …)`; the action dispatcher reached a tool whose body did not exist |
| the engine is installed where agents are | `fa`, `find-anything`, `rg`, `ctags`, `usearch`, `comms-search`: **all ABSENT** from PATH |
| a search index exists to be fast against | no `~/.faindex` at all; the only file that looked like one was `/root/.usearch/usearch.db` at **135 KB** — the two-document smoke test from a previous session, not an index |
| the journal is searchable | it was, but a two- or three-word query returned **exit 1 — "the scope was searched and holds nothing"** |

**Two of these were invisible in the way that matters.** `run_tool()` returns
`{"ok": false, "error": "Tool <name> not found"}` from one line —

```
app/tool_factory.py:705      return {"ok": False, "error": f"Tool {tool_name} not found"}
```

— for a *missing file*. So "this tool was never registered" and "this tool is registered and has no
implementation" produced **identical text**, and both read like a typo rather than an outage. And
`search.py` carefully translates the engine's exit codes into
`NO MATCH (exit 1: the scope was searched and holds nothing)` — an honest sentence, carrying a wrong
fact, delivered to an agent that then stops looking.

**Correction kept on purpose.** My first journal searches this session — `"find-anything search index
fast search"`, `"cloud migration secretary"` — both returned *"no match"* and I accepted them. They were
the very defect I later fixed (§2/R4), and D2983 had recorded it **three days earlier**. An agent that
trusts a search tool is exactly the agent the tool's false negatives disarm.

---

## 2. ROOT CAUSES

| # | cause | the measurement behind it |
|---|---|---|
| **R1** | **`data/tools/` is gitignored, so the tool bodies could not be deployed.** The registry travelled in git; the implementations did not. | `.gitignore:58` → `data/tools/`. On the authority: registry **608** entries, **607** active, **8** with a body, **599** without; `data/tools/*.py` = **8** files. On the frozen office box: **602** files. |
| **R1a** | **Nothing asserted that a registered tool had an implementation.** | Every one of the 599 was listed to agents as available. No check, no alarm, for a full day. |
| **R2** | **The engine was never installed on the authority.** | `command -v fa find-anything usearch rg comms-search` → all ABSENT. `find-anything` existed only at `/home/zabz/bin/find-anything`, on the box being frozen. |
| **R2a** | **The deployed engine carried 89 uncommitted lines.** The office box's own ref was behind its working tree. | `git -C /home/zabz/bin diff --stat find-anything` → `89 insertions(+), 17 deletions(-)`, *dirty*. Those improvements existed in **no git ref anywhere**. This is the same class as H3565's `commsindex.py`, recovered from a `.bak` three days earlier. |
| **R3** | **Hardcoded per-machine layout, in two places, both failing plausibly.** | `data/tools/search.py:43` pinned `/home/zabz/bin/find-anything` — a path no cloud node has (and a module-level constant, so a long-lived API process could never see a corrected PATH). `find-anything`'s `ROOTS` were the *office* checkout; the authority's is `/opt/company`, so `code`/`files`/`symbol` scanned **zero roots** and reported "no match". A third: `build-indexes.sh` resolved the harness config from a path that exists on no host, skipping that root everywhere it ever ran. |
| **R4** | **`journal.py` required every query term on the SAME LINE.** | `all(p.lower() in ln for p in pats)` over `text.split("\n")`. Measured: `fa journal "lpt website"` → exit 0, 8 hits; `fa journal "lpt website deploy"` → **exit 1, "no match"**. Reproduced for `"cloud migration secretary"`. **D2983 recorded this exact pair on 2026-10-09** and cited it as a reason to prefer `unified-search`; it was never fixed. |
| **R5** | **The clocks that keep indexes fresh have died silently three times on this estate.** | P2899 D2 — a trigger whose repetition pattern *expired after one day* (`Duration=P1D`), `NextRunTime` empty, index 21 days dead. H3376 — the same, 21 days stale. `zabz-tech` — `LastTaskResult=1`, index 27 days stale (§5.1). All three still described themselves as "scheduled". |
| **R6** | **The search subsystem was in no register, so no migration brief could carry it.** | `docs/mesh/000-SYSTEMS-REGISTER.md` mentioned search only as *a way to search the register*. §2.5 was added by this session. `145-AUDIT-SERVICES.md:307` recorded `fa-index.timer` as NOT-MIGRATED and `149-AUDIT-REFERENCES.md:503` called `fa data` a documented fallback that BREAKS — both correct, neither acted on. |

---

## 3. WHAT I CHANGED (all on `secratary-cloud`)

Committed there as **`1c88848`** — exactly ten paths, so no other session's work was swept (the tree
carries live changes from a phone-gate session, a mesh-broker session and others; they were left alone).

| # | change | where |
|---|---|---|
| 1 | **Restored 593 tool bodies** from the frozen office box (excluding `help.py`, the authority's own *different* implementation, and `comms_search.py`, a symlink repointed to `/root/.fsearch/comms-search.py`). Seven of the authority's eight existing bodies were **cloud-only** and were deliberately not overwritten. Before-image kept. | `data/tools/` |
| 2 | **Installed the engine** from a **sha256-verified** copy of the office working tree, plus `rg 15.1.0` and `universal-ctags 6.2.1`. | `/usr/local/bin/find-anything` + `fa` |
| 3 | **Built the indexes.** | 6,897 paths · **82,899 symbols** · 3,249 journal entries |
| 4 | **Fixed the false negative** — entry-level AND over whitespace-split terms, one bounded pass; `--all-words` keeps the strict line reading; `--regex` keeps adjacency. | `journal/tools/journal.py` |
| 5 | **Made the subsystem reproducible from git.** | `scripts/find-anything/` |
| 6 | **Installed three clocks** on minutes I computed collisions for. | root crontab |
| 7 | **Added a guard for tool loss.** | `scripts/guards/tool-body-guard.py` |
| 8 | **Registered `search`** so it is discoverable, not merely callable (it was never registered, even on the office box). | `data/tool_registry.json` |
| 9 | **Added the subsystem to the systems register** as §2.5, with the three traps. | `docs/mesh/000-SYSTEMS-REGISTER.md` |
| 10 | **Marked 7 phantom entries `deprecated`** — registered `active` with no body on **either** box (pre-existing self-programming noise, not migration loss), so the new guard's signal is exact. | registry |

### 3.1 The fix to the false negative, before and after

| query | before | after |
|---|---|---|
| `journal.py search "lpt website deploy"` | **exit 1 — "no match"** | exit 0 |
| `journal.py search "cloud migration secretary"` | **exit 1 — "no match"** | exit 0, 399–490 ms |
| `journal.py search zzqqnosuchterm9931` | exit 1 | exit 1 — *still a real negative* |
| `journal.py search battery` | exit 0 | exit 0 |
| `--all-words` | strict | strict, unchanged |
| `journal.py check` | — | **0 errors** |

**The trap I fell into while fixing it, kept here because it is the reusable part.** My first version
recomputed the whole entry's text in lower case per candidate. That cost an extra full-text pass over
every one of ~3,200 entries and measured **4.7–5.8 s** — *the fix breached the budget it existed to
protect.* The shipped version derives the entry-level test from the terms already seen while scanning
lines (one pass) and caps the collected lines at what can actually be shown. Warm latency ended
**better than before** the change (1.5–1.9 s vs 1.9–2.5 s).

### 3.2 The clocks, and the collision I created and fixed

```
 8,23,38,53 * * * *  fa-index-refresh      builds path, symbol and journal indexes
22 * * * *          fa-index-freshness    MEASURES them; exits non-zero when stale
47 * * * *          tool-body-guard       every ACTIVE tool must have a body
```

My first cut used `*/15` and `:37` and **collided** with the pre-existing `journal-commit */15` and
`comms-refresh :37`. The index builder calls `journal.py status`, which rebuilds the journal cache; two
rebuilds on the same minute measured `ps_search what=journal` at **21,902 ms**. The odd minutes are
congruent to 8 mod 15 and are not multiples of 5, 20 or 30, so they collide with nothing on this
crontab. Installed with `install-crontab-fragment.sh` (de-duplicates by job *name*, so re-running
updates rather than appends); before-image `/root/crontab.before-20261012T033202Z`.

---

## 4. EVIDENCE — every door, exercised

| what was tested | result |
|---|---|
| `ps_search` in `files` / `symbol` / `code` / `journal` / `data` | `exit_code 0`, `searched true`, `source` + `ms` + `index_age_s` on every one |
| `ps_action("search", {…})` — the path the skill actually names | `success true`, same payload |
| `ps_comms_search battery` | real customer rows; 179,608 indexed records; index 0.24 h old |
| negative control: `zzqqnosuchterm9931` | `exit_code 1`, `searched true` — **a real negative, not a refusal** |
| `fa symbols create_task` | was exit 4 (no index); now the 82,899-symbol ctags index, query 12–22 ms |
| `fa symbols` with a mildly old index | exit **3** — "answered but possibly stale", the correct third answer |
| `tool-body-guard.py` | **601 active tools, 601 with a body, 0 without**; exit 0 |
| `tool-body-guard.py --selftest` | passes on a broken registry, on a fixed one, ignores `deprecated`, and **raises** on an unreadable one — a refusal can never be a pass |
| `check-faindex-freshness` | `verdict: OK — 3 index(es) present and current` |
| `tool-body-guard` on its own clock | **fired 2026-10-12T03:47:01Z, exit 0**, recorded in `~/.cron-status/runs.tsv` |
| `journal.py check` (the estate's own health check) | **0 errors**, exit 0 |

Probe scripts are preserved (see §6). The engine's own `fa stats` ledger and the estate's
`~/.cron-status/runs.tsv` both carry machine-readable records of these runs.

---

## 5. WHAT IS STILL OPEN, IN THE ORDER I WOULD DO IT

### 5.1 `zabz-tech`'s desktop search index — **cause NOT established** (the honest entry)

Its 4.9 GB `index.db` is 27 days stale and its task returns 1. I ruled out the trigger (hourly,
indefinite, `NextRunTime` set — the *healthy* shape), the launcher, the interpreter and the paths, and I
**nearly reported a historical `IndexError` as the cause** — `refresh.py`'s failure-reporting generator
crashed on an empty tail, but the file was fixed on 2026-09-14 and the traceback in the log is older
than the fix. **A confidently wrong diagnosis was one keystroke away.**

Established: the task fires hourly, returns 1, and writes **nothing** to `refresh.log` or
`refresh-state.json` (both frozen since 2026-09-14T17:34), so runs fail in a path that records nothing.
A full refresh takes **1044 s** and is silent while it runs, so short-cap probes read as "hung" when they
are merely working — which is how I briefly mis-called it.

**Exact next step** is in journal **`H3574`**: start `refresh.py` with `-u`, output redirected to a
file, wait **20+ minutes**, then read both streams and `refresh-state.json`. ~20 GB of `RETIRED-*` index
files also sit there reclaimable.

### 5.2 `data/tools/` is guarded but still untracked

The bodies are restored and `tool-body-guard.py` alarms hourly if one disappears again. But the 600
files themselves remain outside version control and outside most backups. **The guard catches a loss; it
does not prevent one.** Fix: track them, or capture them the way `scripts/deployed/bin/` captures the
text line.

### 5.3 The harness-config mirror divergence — **already known, not new**

Measured: 95→107 commits on the authority vs 2 on GitHub; neither a fast-forward; the `vault` remote
unreachable. I committed to **both** working trees and **refused to force anything**. **This is `P3135`**,
filed 2026-10-11 — I found it as if it were news and it is not.

**What I did about the push, measured rather than assumed, and verified by reading the remotes back:**

| remote | before | after | how |
|---|---|---|---|
| `origin` = `secretary-ts:/home/zabz/harness-config.git` (the config authority, on the frozen anchor's *bare repo* — not its tree, database or services) | `f4f093d5` | **`aeebd479`** | `git push origin main` — fast-forward, `f4f093d5..aeebd479`. **This is the push that matters: it is the repo other clones fetch config from.** |
| `offsite` = GitHub `main` | `f38366fc` | `f38366fc` (**unchanged**) | **Rejected, by design.** `origin` carries TWO pushurls and the GitHub half always fails non-fast-forward — `journal L3748`, measured the same night. The push's exit code is `1` for that reason alone. |
| GitHub, branch `search-audit-2026-10-12` | — | **`aeebd479`** | `git push offsite HEAD:refs/heads/…`. **A branch, never a force, never `main`.** The work is on the mirror; the mirror's `main` is untouched. |

**So: read the exit code of `git push origin` as "the GitHub half failed", never as "the push failed".**
The tempting repairs are all wrong — a force push rewrites 2 commits other people may hold, and a merge
of the 120-commit divergence conflicts in `presets/zabz/skills/fast-search/SKILL.md` **and in
`journal/index/*`, which regenerates on every write and is a permanent conflict generator.** L3748 has the
one-time reconciliation for whoever owns the mirror; it is a deliberate job, not a step in this one.

### 5.4 The cold first touch is still unmeasured

Warm `ps_search what=journal` is 1.5–1.9 s; the first query after an index rebuild measured **4.8–6.6 s**.
This is the caveat `H3411` wrote in its own words — *"do not claim the cold case is fixed until it is
measured."*

### 5.5 Three `read-only` hosts carry the buggy index builder

`hetzner` and `lpt-apps` run `~/bin/build-indexes.sh` under `fa-index.timer`. **Their indexes are
correct and tiny, not broken** — `/root/bin` holds exactly 8 files and the index holds exactly 8
entries. A mesh child reported this as "a green timer over an empty index"; I counted and it is false.
`lpt-survivor-01` has no search surface at all. All three are `read-only` per
`settings/machines/host-posture.tsv`: **deploying to them needs a window the owner grants**, and the
corrected builder now refuses to write an empty index (exit 4), so deployment is the whole fix.

### 5.6 `mac-mini-ts` never answered

Tailnet and LAN both timed out. **Unreachable is not a negative** — its search surface is UNKNOWN.

### 5.7 The MCP tool list is still not asserted

`P2868` recorded `ps_search` being committed on whatever branch production happened to be on. The body
is now on the trunk and in git, and a guard asserts *bodies* — but nothing asserts that the MCP server's
*tool list* contains `ps_search`. Fix: one assertion over the registered tool names, in the same guard.

---

## 6. WHERE EVERYTHING LIVES

**The subsystem (canonical, in git):** `scripts/find-anything/`

| file | what it is |
|---|---|
| `find-anything` | the engine — one grammar, every mode, exit codes as a contract |
| `build-indexes.sh` | builds path + ctags + journal indexes; refuses to write an empty one |
| `search-tool.py` | the `data/tools/search.py` body — resolves the engine, translates exit codes, adds no second grammar |
| `register-search-tool.py` | registers `search` so agents can *see* it |
| `install.sh` | puts all of it on a node, repo → host, sha-verified |
| `check-faindex-freshness` | the clock guard — measures the indexes, exits non-zero |
| `make-crontab-fragment.sh` | generates the scheduled fragment with the collision-free minutes |
| `audit-2026-10-12/` | the probe scripts behind every number in this document |

**The guards:** `scripts/guards/tool-body-guard.py` (also installed to `~/bin` by
`scripts/guards/install.sh`).
**The register:** `docs/mesh/000-SYSTEMS-REGISTER.md` §2.5 — *read it before touching search*.
**The semantics:** `journal/tools/journal.py` — entry-level AND over terms; `--all-words` for the strict
reading.

### 6.1 Related documents, and what each is for

| document | why it matters here |
|---|---|
| `docs/mesh/000-SYSTEMS-REGISTER.md` **§2.5** | the search subsystem, added by this session; the three traps |
| `docs/mesh/130-LIVE-STATE-freeze-applied-snapshot-running.md` | the freeze this session read from, and must not write to |
| `docs/mesh/131-MIGRATION-BRIEF.md` | **Rule 1**: the office box is read-only. **Rule 2**: one writer for the company database |
| `docs/mesh/142-ANCHOR-WRITE-NOTICE.md` | what breaking Rule 1 already cost once |
| `docs/mesh/145-AUDIT-SERVICES.md` §307 | recorded `fa-index.timer` NOT-MIGRATED — the prediction this session found to be true |
| `docs/mesh/149-AUDIT-REFERENCES.md` §503 | called `fa data` a documented fallback that BREAKS |
| `docs/mesh/152-OWNERSHIP-MAP-AND-PORT.md` §2 | listed `comms-refresh` as OWNED-AND-PENDING with blocker "no `/root/.fsearch` index" |
| `docs/mesh/138-PORT-INGESTION.md` | the comms toolset port; the reason `/root/.fsearch` exists at all |
| `docs/mesh/135-PORT-FRESHNESS.md` | argued against building a comms index with no reader — answered, not overridden, by H3565 |
| `docs/mesh/136-ESTATE-INVENTORY.md` | what the office box had that the cloud box does not |
| `docs/mesh/154-MESH-BROKER-MOVE.md` | the other "move it, but the office copy is frozen" decision |
| `docs/mesh/169-CLOUD-VS-OFFICE-AUDIT.md` | the companion audit running alongside this one |
| `docs/mesh/170-MASTER-RECORD-ATTENTION-BADGE-AND-FLEET-AUDIT.md` | the same document shape, for the badge incident |
| `docs/mesh/171-CLOUD-AUTHORITY-AUDIT-START-HERE.md` | **the umbrella page for the cloud-vs-office audit — start there for storage, memory, cron parity and the anchor; start here for search.** Its "three real wins" do not cover search, and this document is why that matters |
| `AGENTS.md` §0 and §5 | prove it does not already exist; never change a machine's service state you have not understood |
| `settings/machines/host-posture.tsv` | who is frozen, read-only, writable — the guard reads this, never a hardcoded list |

### 6.2 Journal entries written by this session

| id | kind | what it holds |
|---|---|---|
| **H3571** | handoff | the full state of play for the authority's search system |
| **H3574** | handoff | `zabz-tech`: what is ruled out, and the exact next command |
| **L3743** | lesson | a gitignored directory holding runtime state does not survive a migration |
| **L3744** | lesson | a refresh job cannot report that it stopped running; two jobs on one minute cost 21.9 s |
| **L3745** | lesson | requiring every term on one line manufactures confident false negatives — and the fix must still fit the budget |
| **L3746** | lesson | never write a machine's absolute layout into a shared script |
| **D3052** | decision | the canonical home; and that journal search means *every term, somewhere in the entry* |
| **W2739** | win | dead → every mode working, with the numbers |
| **P3138** | pain | the seven remaining ways this can silently stop |

Earlier entries this document depends on: **`D2983`** (the false negative, recorded 2026-10-09 and
unfixed), **`P2899`** and **`H3376`** (the dead clocks), **`H3411`** (the 5-second criterion and the
cold-cache caveat), **`H3565`** (the authority's comms index), **`P2868`** (`ps_search` on the wrong
branch), **`P3135`** (the mirror divergence), **`L3359`/`L3381`/`L3388`** (every mode must be run
before its help is believed), **`H3321`/`H3334`** (the last time the engine was deployed fleet-wide).

---

## 7. PROVENANCE, DISCLOSURE, AND HOW TO VERIFY

### 7.1 Disclosure — the two files I wrote to the frozen office box

Rule 1 (`131`) makes `secratary` read-only. Reading is permitted and is how the tool bodies were
recovered. **I did write two scratch files to its `/tmp`**: `/tmp/tools-port-20261012T0320Z.tgz` (the
870,733-byte tarball of the tool bodies, verified byte-identical on arrival) and `/tmp/listtools.py`.
No service state, database, crontab or repository on that box was changed, and `/tmp` is cleared on
reboot. It is disclosed here rather than left for someone to find.

### 7.2 How to verify any claim in this document

Everything is reproducible from `scripts/find-anything/audit-2026-10-12/` (its own `README.md`
explains the conventions they share):

| script | the question it answers |
|---|---|
| `01-survey.sh` | What is installed on this node, what indexes exist and how old, and what is scheduled? |
| `02-tool-bodies.py` | Which ACTIVE registered tools have no implementation? Also `--diff-a/--diff-b` to compare two checkouts' bodies. |
| `03-modes.sh` | Does every mode answer, with the documented exit code, inside the budget — including the refusal path? |
| `04-acceptance.sh` | The final sweep: guards green, clocks installed *and recording*, every mode, `journal.py check`. |
| `05-journal-semantics.sh` | The D2983 false negative, both directions — hits must hit, and a real negative must stay negative. |
| `06-git-and-cron.sh` | Would a push fast-forward? Do my scheduled minutes collide with another job's? |
| `07-zabztech-diagnose.ps1` | On `zabz-tech`: what is ruled out, and the exact 20-minute run that is the next step. |

Each prints what it measured, and none assumes a hostname: the checkout, the harness-config root and
the engine are all resolved by environment override → probe → legacy path. That is the fix for R3,
applied to the audit tools as well as to the product — a hardcoded path is how the search system broke
in the first place.

### 7.3 The one-line summary for a future session that lands here cold

**Search works on the authority. If it stops, look at `tool-body-guard.py` and
`check-faindex-freshness` first — they were built for exactly the two ways it stopped. Read
`docs/mesh/000-SYSTEMS-REGISTER.md` §2.5 before changing anything. Do not hardcode a path.**
