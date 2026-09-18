# Agent brief template

Copy this into a subagent prompt and fill every field. **Do not leave a field out** — a subagent does
not see the conversation it was spawned from, and each field exists because its absence caused a
specific failure. Rationale: `docs/parallel-agent-orchestration.md`. Operational rules:
`presets/zabz/skills/parallel-agent-orchestration/SKILL.md`.

---

You are working in an isolated git worktree. **Your repo root is `<ABSOLUTE PATH>`** and your branch is
`agent/<slug>`. Work ONLY in that directory.

## Shared context

`<Three sentences: what the product is, what the main components are, which language/runtime.>`

**Running tests:** `<exact command, e.g. cd server && python -m pytest <files> -q
--basetemp=./_pt_<unique-slug> -p no:cacheprovider>`. The `--basetemp` flag is **mandatory and unique
to you** — pytest's own temp-dir cleanup fails on this machine and truncates the result summary, so a
colliding temp dir means neither of us can tell whether it passed. `<If a full suite is impractical,
say which files and why.>`

**Git rules — absolute:** commit to your own branch only. **NEVER push. Never touch `main`. Never
`git reset --hard`, never `git checkout .`, never `git clean`, never delete files, never `rm -rf`.**
Commit with:
`git -c user.name="zabz-agent" -c user.email="agent@lakewoodphoneandtech.com" commit -q -F <message-file>`
Explain *why* in the message, and state honestly anything you could not verify.

`<Any house rules that matter: audits that fail on undeclared routes/SQL/settings; prefer static SQL;
a missing config value must close a door, never open one; money as integer micro-dollars;
never claim configured == working.>`

## Your task

`<The task, in plain language, with the problem it solves. If there is a defect, state the exact
evidence for it — file and line — so the agent does not have to take it on faith.>`

**Read first, in this order:**
1. `<decision / doc — and say which section matters>`
2. `<doc>`
3. `<code entry point, with line numbers>`

**Build:**
- `<requirement>`
- `<requirement>`
- `<explicitly: what must NOT be created / what already exists and must be reused>`

**Scope rules — another agent may be working nearby:**
- Put new routes/functions in **new files** where possible.
- In shared files, add `<the minimum>`. Do not restructure or reformat shared files.
- `<paths explicitly forbidden to this workstream>`

**Tests:** `<new test file path>`. Cover at minimum: `<behaviour 1>`; `<behaviour 2>`; the failure
case `<behaviour 3 — especially the fail-closed one>`; and `<the "no side effect" assertion, e.g. no
account was created>`.

**Definition of done:** `<command>` passes, **and** these audits still pass: `<audit test files>`. If
your change would move an audited baseline, prefer rewriting the query/route so it does not; if it
genuinely must, update the baseline and add a dated history entry explaining what moved and why.

**Report back:** files changed; the exact test command and its result line; anything the audits forced;
what you deliberately did not do; **and anything you could not verify.** Be blunt — a confident claim
you did not earn is worse than an honest gap, because a gap is recoverable and a false claim is not.
