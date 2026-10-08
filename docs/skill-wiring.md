# Skill wiring — where a skill has to be for an agent to see it

**Measured 2026-10-08 on ZABZ-YOGA. Written because a skill that no session can see is the same as a
skill that does not exist, and this one cost a whole session of hunting.**

## The rule

`presets/*/skills/` in this repo is the **source**. `$DSH_HOME/skills/` (i.e. `~/.dsh/skills/`) is the
**generated install target**, written by `scripts/sync.py` (`plan_skills`). Nothing else is required,
and no session has to know any of it: the estate's skills are in every agent's catalog because sync put
them where the agent reads.

```
presets/zabz/skills/<name>/SKILL.md      source of truth (repo, reviewed, diffed)
        │  scripts/sync.py  →  plan_skills()
        ▼
$DSH_HOME/skills/<name>/SKILL.md         what the session catalog is built from (watched live)
```

Precedence: `zabz` → `cordis-bg` → `yocheved`. A name shipped by two presets with identical content is
one skill; identical names with different content are reported as a CONFLICT and the higher-precedence
copy wins. Skills are additive — one we did not install is never deleted, only reported.

## Why not the preset's own `skills/` directory

The composition registers the preset's directory with the skill provider:

```yaml
- id: skill-filesystem
  name: '@deepseek-ai/dsh-skill-filesystem'
  config:
    customSkillDirs:
      - !!js "…new URL('skills/', baseUrl)…"      # the preset's own skills/ dir
```

**In this deployment that row registers nothing.** The evidence, all on the same machine, same engine,
same hour:

| probe | result |
|---|---|
| `zz-preset-probe/SKILL.md` placed **only** in `~/.dsh/.agent-presets/zabz/skills/` | never appears — not in the running session's catalog, not in a fresh local agent's catalog |
| the same file placed **only** in `~/.dsh/skills/` | appears in the running session's catalog **within seconds**, no restart (that root is watched) |
| the preset's `customSkillDirs` rewritten from the `!!js` expression to a literal absolute path | still nothing |
| `!!js process.platform !== 'win32'` in the *same file* | works — the MCP rows for that platform are mounted |

So it is not the expression: the evaluator (`new Function("ctx","expr","with (ctx) { return eval(expr) }")`
in `@deepseek-ai/cordis-plugin-loader`) resolves `baseUrl` correctly when `ctx.baseUrl` is set, and the
same file's other `!!js` rows evaluate. The preset's skill *provider* simply does not activate in this
composition — an open question, tracked in the journal, not a mystery worth blocking on, because the
user root works and is watched.

**What that cost, concretely:** `fast-search` — the skill that tells every agent to search the indexed
estate instead of walking four million files, and the tool the owner asked about — was in the repo, in
three presets, and in **no agent's catalog**. The session that was asked to test it had to go looking
through the journal, git history and the filesystem to work out what "the faster search tools" even
were.

## Checking it

```bash
python scripts/sync.py --dry-run        # reports + new / ~ changed / - removed, writes nothing
python scripts/sync.py                  # applies settings, presets, then this
```

A fresh agent's `<available_skills>` block is the acceptance test. If a skill is missing there, it is
missing, whatever the repo says.
