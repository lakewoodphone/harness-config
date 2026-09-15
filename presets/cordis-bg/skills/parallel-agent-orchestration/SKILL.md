---
name: parallel-agent-orchestration
description: Use as the DEFAULT for any larger job rather than iterating serially — running parallel subagents on one repository, splitting a backlog into simultaneous workstreams, managing a fleet of agents building at once, using git worktrees for agent isolation, integrating many agent branches back into main. Triggers on a big or large job, a backlog, "everything that needs doing", "build it all out", "work on all of them", a multi-repo or many-file build-out, or when the owner asks why progress keeps stalling after each increment. Also use when deciding whether work can be parallelised at all, and read it BEFORE starting to do a large job single-threaded.
---

# Running a fleet of agents on one repository

**This is the default for a larger job, not an optimisation to reach for later.** A serial agent stops
after every increment and needs restarting — that is the measured failure this exists to end. If a job
has more than one genuinely independent piece, fan it out first and manage; iterate serially only when
the work is genuinely sequential.

You manage; they build. The failure this prevents is real and measured: an agent working serially
stops after every increment, and 2,283 turns in this system's history were the owner saying *"keep
going"*. Parallelism is the fix — but only if the manager does the partitioning, because everything
that goes wrong in a fleet goes wrong where the manager left something shared.

## The one rule

> **Isolation is created by the manager before agents start, never negotiated by agents while they run.**

Multi-agent tools advertise file-lease and messaging layers. Those are **advisory**: they make
overlap visible, they do not stop an agent from editing a file another agent claimed. Worktree
isolation and the manager's merge discipline are the only real guarantees. So **you do the claiming,
centrally, in the brief.**

## Procedure

### 1. Decide whether to fan out at all

Do **not** parallelise if any of these is true:

- the work is on a dependency chain (B needs A's interface — build A first, serially);
- two workstreams want the same file (combine them, or reserve the file for one);
- you cannot state the finish line as a command that produces readable output;
- there are fewer than three genuinely independent streams;
- **you will not have capacity to integrate them.** Concurrency is capped by integration capacity,
  not by tooling. Ten branches nobody merges is ten times the work.

Aim for as many workstreams as there are **disjoint file sets** — typically 3–8, occasionally 10.

### 2. Partition by file, not by topic

Two tasks about the same subject are not two workstreams if they touch the same file. Write the list,
then for every shared path pick one owner and forbid it in the others. Also reserve shared resources
explicitly: the next migration number, the config file, any generated document. **One owner per shared
resource per fleet.**

### 3. Cut each workstream its own worktree and branch

Use `scripts/agent-fleet.ps1` on Windows or `scripts/agent-fleet.sh` on Linux/macOS — same commands,
same safety posture. Branch each from a **known-clean** `main`, never from another agent's branch.

```sh
agent-fleet.sh doctor                     # can this machine host a fleet at all? run it first
agent-fleet.sh new   -n lpt-route,egress-wiring -r /path/to/repo
agent-fleet.sh status -r /path/to/repo    # dirty / artifacts / disk per worktree, mid-run
agent-fleet.sh clean  -r /path/to/repo    # drop _pt_* / __pycache__ / .pytest_cache
agent-fleet.sh rm    -n lpt-route -r /path/to/repo
agent-fleet.sh rmall  -r /path/to/repo    # branches kept, so unmerged work stays salvageable
```

**`doctor` is not decorative.** On this mesh there is no `pwsh` on the Linux or macOS nodes, no Python
`yaml` on the mac mini, and `~/code/harness-config` is absent on two machines — a fleet that assumes
any of those works fails at the worst moment. Run `doctor`, read what it says, fix that first.

### 4. Write the brief as a contract — all eight parts

A subagent does not see your conversation. Every brief must carry:

1. **Repo root and branch** — the absolute worktree path, stated first.
2. **Shared context** — what the product is, in three sentences.
3. **Read-first list** — the decisions, docs and code to read before writing, so it re-derives nothing.
4. **Exclusive file scope, and what is forbidden.**
5. **Git rules, absolute:** commit to your own branch only; **never push; never touch `main`; no
   `reset --hard`, no `checkout .`, no `clean`, no deletes, no `rm -rf`.**
6. **The test command with a unique `--basetemp`**, plus the audits that must stay green.
7. **Definition of done as commands**, not adjectives.
8. **Report format, and the honesty clause:** files changed; the exact command and its result line;
   what you deliberately did not do; **what you could not verify**. Say plainly that a confident claim
   it did not earn is worse than an honest gap.

Start with `docs/agent-brief-template.md`.

### 5. Integrate serially, in risk order

Agents run in parallel; **integration is serial and is where the value is kept or lost.**

- Merge lowest risk first: **docs-only → new isolated files → edits to shared files → migrations and
  schema.**
- **After every merge, re-run the touched tests plus that brief's audits.** Green, or it does not stay.
- **Never merge a generated file from a branch.** If two workstreams both regenerate a config reference
  or a docs index, regenerate it **once** on `main` after both land.
- **Hand-resolve conflicts, then gate the resolution on the test command** before accepting it. A
  resolution that merely looks correct is not verified.
- **A branch that breaks `main` is reverted, not repaired forward**, unless the repair is trivial and
  verified. Green `main` is the invariant that makes the whole method safe.
- **An agent's report is a claim, not evidence.** Reproduce it. This is the highest-value rule here:
  the measured failure in this system's history is a confident report nobody checked.

### 6. Write the state down

A todo row per workstream while it runs; a journal handoff when the fleet settles, naming every branch,
what merged, what did not and why. Agents finish at arbitrary times and sessions end without warning,
so anything not written down is lost.

## The four things worktrees do *not* isolate

Fleets break on these, not on the code:

| Shared by default | The rule |
|---|---|
| **Ports** | agents and tests must not bind ports |
| **Databases / real files on disk** | tests use in-memory or their own temp path; never write the real store |
| **Test temp directories** | **`--basetemp=./_pt_<unique-per-agent>` is mandatory** — on these machines pytest's tmpdir cleanup fails and *truncates the result line*, so a colliding temp dir means you cannot tell whether it passed |
| **Build artifacts and caches** | clean them at teardown; a forgotten worktree is a slow disk leak |

## Failure handling

| Failure | Response |
|---|---|
| Agent fails mid-run | the **workstream** returns to the queue; keep the branch if it has commits |
| Success claimed without running tests | treated as failure — verify |
| Touched a forbidden file | revert that branch |
| Cannot verify (no dependency, no device, no network) | **"not verified"** is the correct answer; record it, never claim it |
| Integration would break `main` | revert and re-queue with a smaller scope |

## Off-limits

Never let an agent push. Never let an agent touch `main`. Never merge a branch whose tests you have not
run yourself. Never accept "it works" as a result — the result is the command's output line.

Full rationale, the research this is based on, and the measured failure modes:
`docs/parallel-agent-orchestration.md`.
