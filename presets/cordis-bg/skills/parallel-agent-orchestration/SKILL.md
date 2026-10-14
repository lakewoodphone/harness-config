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

### The host's disk is a fleet resource, and measure it FIRST (L3932)

**Check free disk on every node before a fleet, and again after it.** A fleet's copies are
measured in tens of GB, not MB: a `cp -a` of this estate's company repo is **23 GB** (its `.git`
alone is 7.6 GB). Eight copy-making children in one day took the host to **97 % full with 4.9 GB
free** — and the failure that produced was not a slow agent, it was a **wedged service**:

    host 97 % full -> SQLite writes become waits -> `database is locked`
      -> the service's runs exceed their 600 s ceiling -> threads are abandoned while still
         holding the DB lock -> the loop wedges and stops ticking entirely

Freeing that one tree took the host to 81 % and `/health` from **alternating 2.000 s timeouts to
a flat 0.007 s**, with the loop advancing for the first time in 44 minutes. **Disk pressure looks
exactly like a software defect and is diagnosed as one.**

So, before the fleet:

    df -h / /tmp                                  # on every node that will hold a copy
    agent-fleet.sh status -r /path/to/repo        # disk per worktree, mid-run

1. **Prefer `git worktree` to `cp -a`.** A worktree shares the object store; a copy duplicates
   it. If a child needs to *read* code, it does not need a copy of the repo at all.
2. **State a disk budget in every brief** — one copy of a large repo per child, and no child
   running two.
3. **Never `git format-patch --all --stdout` on a large repo**: `--all` walks the whole history,
   and on this estate it wrote **4.78 GB** in one command — into `/tmp`, which is **tmpfs**, so
   RAM-backed. A branch's change is a patch of its diff, not of its history.
4. **Clean copies at teardown, and read the host's disk after the fleet**, not only the
   worktrees' — the leak this rule exists for was on the host, where nobody was looking.
5. **Reclaiming is not deleting.** Before removing a child's tree: confirm the artifacts exist
   outside it (`diff -q`), confirm the original is intact, and capture anything that exists only
   there — an unpushed branch, a report — as a small artefact. **Never remove a store you did
   not create:** a 26 GB pre-remediation database backup on this estate is the owner's call.

## Failure handling

| Failure | Response |
|---|---|
| Agent fails mid-run | the **workstream** returns to the queue; keep the branch if it has commits |
| Success claimed without running tests | treated as failure — verify |
| Touched a forbidden file | revert that branch |
| Cannot verify (no dependency, no device, no network) | **"not verified"** is the correct answer; record it, never claim it |
| Integration would break `main` | revert and re-queue with a smaller scope |

## What each host can actually take — measured, 2026-09-15/16

Fan the fleet **off** the machine the owner is sitting in front of when it is heavy. These are
measurements, not rules of thumb; method and raw counters are in `_dsh-scale/`.

| Host | What it is | Measured | Rule |
|---|---|---|---|
| `ZABZ-YOGA` | laptop, 22 logical cores, 31.61 GB physical | commit 20.6-22.9 GB with the fleet quiet and **28.7 GB at ten running turns**; pagefile 16 MB; hard page faults 145-2,400/s depending on load; ~892 MB private per window before the 2026-09-17 shared-profile change and 60-296 MB after it | **0.403 GB per running turn (measured 2026-09-17: 403 MiB, CI 270-533; the 0.81 figure was falsified twice and is retained here only as a warning)**, so roughly 111 turns before it pages (CI 93-136), and cores bind before memory does, and ~46 windows before windows bind. Keep fleets here small, or run them elsewhere |
| `ZABZ-TECH` | office desktop, 32 cores, 63.6 GB physical | measured 2026-09-16: commit **44.5 GB**, 38.1 GB free, **19.1 GB headroom**, 28 page-ins/s, 518 processes, 50 node, 1 engine on :3099 | at the laptop's 0.403 GB per running turn (measured 2026-09-17: 403 MiB, CI 270-533; the 0.81 figure was falsified twice and is retained here only as a warning) this is ~23 turns of headroom — but it is **not yet fixed** (46 MCP server processes, 15 npx shims, no `NODE_COMPILE_CACHE`, no reaper, `maxParallelToolCalls` unset). Measure again after it is brought level |
| `secratary-cloud` | **Linux authority** — company DB, API, mesh broker | — | prefer it for anything that must not depend on a laptop being awake. **`secratary` (the office box) is NOT the authority and must never be used** — since the 2026-10-11 cutover it is the FROZEN rollback anchor with `cron` masked on purpose, so it still *answers* and is a decade-stale reading waiting to happen. Aliases: `secratary-ts` is the office box; `secratary-cloud` is the authority. `settings/machines/host-posture.tsv` decides, not memory |

Three measured facts that change how a fleet is briefed:

- **A shell tool call costs ~700 ms** (trivial `pwsh`: start-up 78 %, the Job-owner runner 19 %,
  everything else under 3 %) while `read` is **0.76 ms** and `stat` **0.11 ms**. No shipped tool
  declares `isConcurrencySafe`, so parallel calls in one step run **in series** — N shell calls
  cost N x ~700 ms. Put "use the file tools, batch shell work" in every worker's brief.
- **Sessions and subagents are not processes.** A subagent runs in-process; the process cost is
  per *tool call* (~160 MB in flight: a ~57 MB Job-owner runner plus the shell).
- **On the laptop the binding resource is memory commit, not CPU** — measured at 36-39 GB against
  31.6 GB physical with hard faults at 2,400/s while CPU sat near 65 %. A fleet can be "only"
  65 % busy and still be paging.

Records (in the repo, so they reach every machine): `docs/dsh-at-scale/PROGRAM.md` is the spine;
`10-dsh-source-audit.md` (process model), `50-implementation.md` (what changed and what it bought),
`80-windows-and-parity.md` (window budget; count browser memory by private bytes, never
`WorkingSet`), `70-toolcall-latency.md` (per-call cost and why the persistent shell was refused),
`60-cost-audit.md` (the money). `scripts/harness-verify.ps1` checks these invariants and exits
non-zero when one is false.

## Off-limits

Never let an agent push. Never let an agent touch `main`. Never merge a branch whose tests you have not
run yourself. Never accept "it works" as a result — the result is the command's output line.

## Three rules this skill was missing, each learned the hard way

### Never `git add -A` in a working tree another session can reach

Pain `P13`, lesson `L33`. Eight concurrent sessions each ran `git add -A` and committed **each other's**
work: changes appeared in commits by people who never made them, and the audit trail of who did what
stopped being true. **Stage explicit paths, always** — `git add -- path/a path/b`, never a wildcard, and
never from a repository root when more than one session is live. This is not a style rule; it is the
difference between a commit you can describe and one you cannot.

### A `git worktree` is not a copy of your checkout

Lesson `L217`. A worktree shares the object store and the working tree *of tracked files* — **untracked
files stay behind**, and so do most of `/tmp`, the shell environment, and anything a process wrote outside
the tree. So a worktree isolates *committed source*, and is the **wrong control** for anything
environment-sensitive: a test reading an untracked fixture, a build writing beside the repo, a script
resolving a path relative to its own checkout. If behaviour depends on the environment rather than the
source, give that workstream its own clone or explicit paths — do not assume the worktree carried it.

### Check where a child will LAND, not just what you asked it to do

Pains `P3141` and `P3139`. Three of four children the broker placed landed on machines **without the
repository**, so nothing that builds could be delegated — and the failure was invisible, because a child
that cannot find the repo reports on the task it was given, in whatever tree it found, which may be a
different tree on a different commit.

Before delegating anything that edits code:

1. **Know which node the work needs**, and whether that node has the checkout, the repo path and the
   branch.
2. **Put the expected revision IN THE BRIEF**, and have the child report the `git log -1` it actually read.
   On this estate `harness-config` has had two `main` lineages at once that were **not supersets of each
   other** — see `P3164`, where a fix was edited against a stale base and nearly reverted the version that
   runs. A child that does not report its revision cannot be told apart from one that read the wrong tree.
3. **Research delegates well; builds need the repo.** If the fleet is landing on machines without the
   checkout, use it for reading and analysis and do the edits where the code is.

Full rationale, the research this is based on, and the measured failure modes:
`docs/parallel-agent-orchestration.md`.
