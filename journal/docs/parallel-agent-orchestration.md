# Parallel agent orchestration — the fleet design

**Written 2026-09-15.** This is the design for running many coding agents at once on one repository
and landing all of their work, and it exists because the alternative was observed: an agent working
serially on a large backlog stops after every increment, and 2,283 turns in this system's history
were the owner saying *"keep going"*.

**The owner's instruction, verbatim:**

> "anyways get to work desiging this concept for larger projects so you shouldn't get stuck, and you
> can just manage, not just for this time, analyze this concept research it well online and desigin
> the best setups and docuemtn this fully in your instructions and work docuements"

So the deliverable is **not** this one fleet. It is a repeatable capability, documented in the harness
itself so every future session on every machine starts with it.

---

## 1. What was researched, and what the sources actually say

Four sources, read 2026-09-15. The value in all of them is the *failure* list, not the happy path.

- **[Git worktrees for parallel AI coding agents](https://developer.upsun.com/posts/ai/git-worktrees-for-parallel-ai-coding-agents)** —
  worktrees share one object database, so N worktrees cost working files only, not N clones. Names six
  ways it breaks: **port conflicts** between dev servers; **dependencies not carried over**
  (`node_modules`, gitignored `.env`); inconsistent IDE support; **no database isolation** (worktrees
  share the local DB, Docker daemon and caches, so two agents mutate the same state); **disk growth
  from build artifacts** (9.82 GB in a 20-minute session on a ~2 GB repo, and 15 forgotten worktrees
  found "consuming gigabytes"); and the one that matters most —
- **[GitButler, quoted there](https://developer.upsun.com/posts/ai/git-worktrees-for-parallel-ai-coding-agents)**:
  *"You'll create merge conflicts with yourself."* Separate worktrees do not stop two agents editing
  the same file, and **no tool warns you when they might.**
- **[pact](https://github.com/zekariasasaminew/pact)** — a multi-agent orchestration CLI. Its most
  important sentence is about what is *not* a guarantee: the file-lease and messaging layer is
  **"advisory, not enforced — it doesn't stop an agent that never checks it from editing a file
  another agent already claimed. Worktree isolation and merge-all's conflict handling are the parts
  that are real guarantees; coordination is a convention agents opt into."** It also ranks the four
  pains in order: shared dependency installs, agents unable to tell each other anything, agents
  stepping on each other's files, and integration. And its merge is **sequenced by risk (small,
  low-risk changes first)**, uses **structural merges** for known formats (JSON dependency blocks,
  `pyproject.toml` tables), and **gates any AI-proposed conflict resolution on a real test command
  before accepting it**.
- **[parallel-worktrees skill](https://github.com/SpillwaveSolutions/parallel-worktrees/blob/main/SKILL.md)** —
  a designed worktree skill (the closest prior art to this document). Its patterns are worth stealing
  outright: run the *same* prompt N times and pick the best; **explore → plan → code → commit**
  (read-only reconnaissance before any write); test-first parallel; and **dual verification** — a
  second, fresh context reviews what the first produced, because a fresh pass catches what the author
  session missed.

**The synthesis.** Worktree isolation is real and cheap. Coordination between agents is a fiction.
**Therefore the isolation must be created by the manager, in advance, by assignment** — not
negotiated between agents at runtime. That single conclusion drives the whole design below.

---

## 2. The design

### 2.1 The one rule everything else follows from

> **Isolation is created by the manager before agents start, never negotiated by agents while they run.**

Every failure the sources describe comes from agents sharing something the manager did not partition:
a file, a port, a database, a cache, a generated artefact. The fix is to partition them up front and
**assign** ownership, because a claim an agent is trusted to respect is advisory, and advisory is not
a guarantee.

### 2.2 Partitioning: what each workstream owns

Before spawning anything, build the list and give each workstream:

1. **Its own git worktree and branch** — real filesystem isolation. `agent/<slug>` on a branch cut
   from the current `main`.
2. **An exclusive file scope** — the set of paths it may touch. If two workstreams need the same file,
   either merge them into one workstream or **reserve the file for one and forbid the other**. The
   second option is usually right: one agent adds a route, another adds a template, and only one of
   them touches the shared registry.
3. **A reserved shared resource** if it needs one — the next migration number, the config file, the
   generated doc. **Reserved, not shared.** One owner per shared resource per fleet.

### 2.3 The four things worktrees do *not* isolate, and the rule for each

| Shared by default | Why it bites | Rule for this fleet |
|---|---|---|
| **Ports** | every dev server wants 3000/8080/5432 | agents must not bind ports; tests must not either |
| **Databases / files on disk** | worktrees share the local DB and caches | tests use in-memory or their own temp path; never write the real database |
| **Test temp directories** | pytest's own tmpdir collides and, on this fleet's boxes, its cleanup failure *truncates the summary* | **`--basetemp=./_pt_<unique-per-agent>` is mandatory in every brief.** This is not a style rule; it is the difference between a green suite and a missing result line |
| **Build artifacts and caches** | the measured 9.82 GB case | clean `_pt_*` and per-worktree caches at teardown; a forgotten worktree is a slow disk leak |

### 2.4 What is a guarantee and what is a convention

Say this out loud in every brief, and never confuse the two:

| Guarantee | Convention (advisory) |
|---|---|
| Worktree isolation — an agent cannot write outside its tree | Exclusive file scope — an agent *can* ignore it |
| The manager re-runs the tests before merging | An agent's report that tests passed |
| Green `main` after every merge | An agent's claim that its branch is mergeable |

**The manager's entire job is to convert the right-hand column into the left one.**

### 2.5 The brief: eight mandatory parts

A brief is not context, it is a contract. Every one must carry all eight, because a subagent does not
see the conversation it was spawned from:

1. **Repo root and branch** — the absolute path of its worktree, stated first.
2. **Shared context** — what the product is, in three sentences.
3. **Read-first list** — the decisions, docs and code to read before writing, so it re-derives nothing.
4. **Exclusive file scope, plus what is forbidden.**
5. **Absolute git rules** — commit to your own branch only; **never push; never touch `main`; no
   `reset --hard`, no `clean`, no deletes, no `rm -rf`.**
6. **The test command, including the unique `--basetemp`**, and the audits that must stay green.
7. **Definition of done** — stated as commands whose output can be read, not as adjectives.
8. **Report format, and the honesty clause**: files changed; the exact command and its result line;
   what you deliberately did not do; **what you could not verify**. A confident claim the agent did not
   earn is worse than an honest gap, because the gap is recoverable and the false claim is not.

### 2.6 Integration: the manager's serial work

Agents run in parallel. **Integration is strictly serial, and it is where the value is realised or
lost.**

1. **Merge in risk order**, lowest first: docs-only → new isolated files → edits to shared files →
   migrations and schema. A conflict resolved early is cheap; the same conflict after five merges is
   not.
2. **After each merge, run the touched tests plus the audits** named in that brief. Green or it does
   not stay.
3. **Never merge a generated file from a branch.** If two workstreams both regenerate
   `config-reference.md` or a docs index, regenerate it *once* on `main` after both land. Merging a
   generated file is merging a stale artefact of a different base.
4. **Hand-resolve conflicts, then gate the resolution on the test command** before accepting it — the
   `pact` rule, and it is the right one. An AI-proposed resolution is not verified by looking correct.
5. **A branch that breaks `main` is reverted, not repaired forward**, unless the repair is trivial and
   verified. `main` being green is the invariant that makes the whole method safe.
6. **The agent's report is a claim, not evidence.** Re-run before believing. This is the single
   highest-value rule in the document: the measured failure mode in this system's history is a
   confident report that was never checked.

### 2.7 The ledger, and why it is not optional

Agents can finish at any time and a session can end at any point. So state lives outside the
conversation:

- **A todo row per workstream**, status-tracked, so the fleet's state is readable at a glance.
- **A journal handoff when the fleet settles**, naming each branch, what merged, what did not, and why.
  A future session that inherits ten branches with no ledger will re-do the work.

### 2.8 When *not* to parallelise

Parallelism is not free; integration cost is real. Do not spawn a fleet when:

- **The work is on a dependency chain.** If B needs A's interface, A is built first, serially. Only
  the genuinely independent work fan out.
- **Two workstreams want the same file.** Combine them.
- **You cannot state the definition of done as a command.** An agent without a checkable finish line
  will report success it cannot substantiate.
- **Fewer than three independent streams.** The overhead of isolation and integration is not worth it
  below that; just do it.
- **You will not have capacity to integrate.** Concurrency is capped by **integration capacity, not by
  tooling**. Ten agents whose branches nobody merges is ten times the work, not ten times the output.

**A practical ceiling:** aim for as many workstreams as there are *disjoint file sets* — typically
3–8. Ten is achievable (it has been done) but it is near the point where integration dominates.

### 2.9 Failure handling

| Failure | Response |
|---|---|
| Agent fails mid-run | The **workstream** returns to the queue, not to oblivion. Keep the branch if it has commits; salvage later |
| Agent reports success without running tests | Treated as failure. Verify; if the tests were not run, the workstream is not done |
| Agent touches a forbidden file | Revert that branch. The scope existed for a reason |
| Agent cannot verify (missing dependency, no device, no network) | **Correct answer is "not verified"**, recorded as such. Never a claim |
| Integration would break `main` | Revert. Re-queue the workstream with a smaller scope |

---

## 3. The mechanics on this fleet

- **Python repos:** system Python 3.13, no venv, no install step — dependency pain (the #1 pain in the
  sources) does not apply. The binding constraint instead is the shared pytest temp dir, hence the
  mandatory `--basetemp`.
- **Android:** Gradle work is expensive and may be offline-only. Treat "the agent ran Gradle" as
  unverified by default and say so. Two machines in this mesh have **no Android SDK at all**, so a
  Kotlin test run there is impossible — an agent on such a machine must say "not executed" rather than
  imply a green suite.
- **Disk:** worktrees share the object database. Measured on `kosher-filter-ai`: a **35.8 MB** working
  tree, so ten worktrees is roughly 360 MB before artifacts. Artifacts are not — a ten-agent fleet
  measured **393 MB** after Gradle and pytest caches, one worktree alone at 120 MB. Run
  `agent-fleet.sh clean` at teardown.
- **The tooling:** `scripts/agent-fleet.ps1` (Windows) and `scripts/agent-fleet.sh` (Linux/macOS) —
  same commands on both, because a capability that exists on one platform is not a capability.

## 3a. Deploying the capability across the mesh

The harness is authoritative **here**, and every machine must be brought to it. Writing the skill
does not deploy it, and a capability that lives on one machine is the exact problem this repo was
created to solve.

What "deployed" means on each machine:

1. `~/code/harness-config` exists, is current with the remote, and `scripts/agent-fleet.*` is present.
2. `python scripts/sync.py` (or `harness-autosync.sh`, which fetches, applies and writes a status
   file) has run, so `~/.dsh/.agent-presets/<preset>/skills/parallel-agent-orchestration/SKILL.md`
   exists. The skill is in **all three presets** — `zabz`, `yocheved`, `cordis-bg` — so any agent on
   any machine gets it, not just the one that happens to read `zabz`.
3. `agent-fleet.sh doctor` (or `.ps1 doctor`) reports **READY** for the repo the fleet will run on.

**Verified per-machine state on 2026-09-15, which is why `doctor` exists:** no `pwsh` on `secratary`,
`zabz-tech-linux` or `LakewooechsMini`; `~/code/harness-config` absent on `secratary` and
`zabz-tech-linux`; the mac mini's checkout stale and its Python missing `yaml` (so the Python sync
path cannot run there — use `harness-sync.mjs`, which is Node); `laptop-ts` is a Windows host
(`ZABZ-YOGA`) and answers PowerShell, so a POSIX probe against it is meaningless.

**Verification is by execution, not by presence.** After deploying, run `doctor`, then `status`
against a real repo. A skill file sitting in a directory is not a working capability; a fleet script
that has cut and reported a real worktree is.

## 4. The one-paragraph version

Partition the work into independent streams with disjoint file sets. Give each stream its own
worktree and branch, cut from a known-clean `main`, and tell it exactly which files it owns and which
it may not touch. Write the brief as a contract with a checkable definition of done, a unique test
temp directory, and an explicit demand for what it could not verify. Merge back **serially, in risk
order**, re-running the tests yourself after every merge and never accepting a generated file from a
branch. Keep `main` green as an invariant, revert rather than repair, and treat every agent report as
a claim until you have reproduced it. Then write down what happened, because the next session has no
memory of any of it.
