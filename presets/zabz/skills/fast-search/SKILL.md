---
name: fast-search
description: Use BEFORE any file or content search, and whenever a search feels slow. Covers finding a string, symbol, or file across this estate's ~4 million files without a multi-minute recursive walk — the `fa` command on Linux nodes and the `ps_action("search")` MCP tool from any agent on any OS. Triggers on "search for", "find the file", "where is X defined", "grep for", "glob for", a search that is taking more than a few seconds, a search that returned nothing useful after a long wait, or any question about why searches are slow. Read this instead of reaching for an unscoped recursive grep.
---

# Searching this estate in milliseconds instead of minutes

## The one thing to know

**A search that takes a minute is not slow software — it is a search pointed at four million files that
cannot contain the answer.** Measured on this estate, same query, same machine:

| | |
|---|---|
| journal FTS (pre-built index) | **6 ms** |
| `rg` scoped to `app/` | **107 ms** |
| `rg` scoped, over the whole tree with defaults | 4,095 ms |
| `rg -uuu`, unscoped | **311,589 ms** |

That is a **2,912×** spread from *scope alone*, before any index. The estate holds ~3.9M files, mostly
`.git` objects, `node_modules`, `.venv` and a 20 GB `data/` directory. None of them can hold the function
you are looking for.

## Use these, in this order

**1. From any agent, on any OS — the MCP tool.** This is the cross-platform surface (Windows, Linux,
macOS) and it is the one to reach for first:

```
ps_action("search", {"what": "code",    "query": "_owner_sms_allowed"})
ps_action("search", {"what": "symbol",  "query": "create_task"})
ps_action("search", {"what": "journal", "query": "journal lock"})
ps_action("search", {"what": "files",   "query": "database.py"})
```

**2. On a Linux node — the `fa` command.** Same engine, same grammar, no MCP required:

```bash
fa code   "_owner_sms_allowed"     # content, ripgrep, .gitignore-aware, derived dirs excluded
fa symbol "create_task"            # where is it DEFINED (always live - you may be about to edit it)
fa symbols "create_task"           # browse ALL matches from the ctags index (~6 ms)
fa files  "database.py"            # filename/path, from the path index (~8 ms)
fa journal "journal lock"          # the harness journal's FTS index (~6 ms)
fa stats                           # how searching is actually going
```

## The flags, and what they mean

| flag | effect |
|---|---|
| `--limit N` | max hits (default 8) |
| `--json` | machine-readable, includes `source`, `ms`, `index_age_s`, `stale` |
| `--fresh` | bypass every index — **use when you are about to edit the file** |
| `--max-age SEC` | refuse an index older than SEC (default 300). A stale index answers with exit **3** and `"stale":true` |
| `--scope DIR` | add a search root |
| `--all` | opt OUT of the curated scope. **This is the slow one and it is logged. You almost never want it.** |

## What must NEVER come from an index

**Symbols, and anything about the file you are about to edit.** `fa symbol` is deliberately live, always,
for exactly this reason. An index can be minutes behind, and an edit made against a stale definition is
the one failure a search tool must not cause. Use `fa symbols` to *browse*; use `fa symbol` or `--fresh`
before you *write*.

## Before you type any of these

- **Never** `grep -r` or `rg -uuu` without a path. `-uuu` is `grep -a -r`: it turns a 4-second query into
  a 5-minute one and reads binaries nobody wanted.
- **Never** point a search at a whole drive, a home directory, or a repo root when you know the
  subdirectory. Scope is the single biggest lever you have.
- **Never** accept a long-running search as normal. If it is not answering in a second, it is aimed
  wrong — say so and re-aim it.

## Derived directories are already excluded

`node_modules`, `.venv`, `venv`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox`,
`dist`, `build`, `.next`, `.nuxt`, `.svelte-kit`, `target`, `.gradle`, `coverage` and `vendor` are
excluded by the `glob` and `grep` tools too, at the engine level. If you genuinely need to search inside
one, name it explicitly in the path.

## If a search is slow anyway

Run `fa stats`. It reports median latency, how many searches exceeded the tripwire, how many were
unbounded, and how many were served by an index — from a log every search writes. That is how this
becomes measurable instead of anecdotal, and how the habit gets found rather than denied.
