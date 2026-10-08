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

Re-measured end to end on `secratary` 2026-10-08, cold caches (`fa` itself, not the micro-bench):

| | |
|---|---|
| `fa journal "journal lock"` | 317–544 ms — the index is real, the 6 ms figure was a warm bench |
| `fa files database.py` (path index) | **40–51 ms** |
| `rg` scoped to `app/` | 20 ms |
| `rg -uuu` over `/home/zabz` | **100,075 ms** (100 s, 49 files) |

Every mode was exercised for the first time on 2026-10-08; five defects came out of it, four of them
silent (a `data` mode that was a stub, `symbols` that never matched, `ask`/`look`/`find` that ran the
wrong search, an age read off a file mtime, and a `--max-age` shorter than the refresh clock).
All five are fixed and re-verified.

## Use these, in this order

**1. From any agent, on any OS — the MCP tool.** This is the cross-platform surface (Windows, Linux,
macOS) and it is the one to reach for first:

```
ps_action("search", {"what": "code",    "query": "_owner_sms_allowed"})
ps_action("search", {"what": "symbol",  "query": "create_task"})
ps_action("search", {"what": "journal", "query": "journal lock"})
ps_action("search", {"what": "files",   "query": "database.py"})
ps_action("search", {"what": "data",    "query": "battery"})   # customer texts/calls/email
```

**2. On a Linux node — the `fa` command.** Same engine, same grammar, no MCP required:

```bash
fa code   "_owner_sms_allowed"     # content, ripgrep, .gitignore-aware, derived dirs excluded
fa symbol "create_task"            # where is it DEFINED (always live - you may be about to edit it)
fa symbols "create_task"           # browse ALL matches from the ctags index (~300 ms)
fa files  "database.py"            # filename/path, from the path index (~40 ms)
fa journal "journal lock"          # the journal index, with the newest entry it covers
fa data   "battery"                # business data: texts, calls, voicemails, email (comms FTS)
fa stats                           # how searching is actually going
```

`ask`/`look`/`find` are aliases of the bare form / `files` / `symbol`, so
`fa look database.py` and `fa find create_task` do what they look like. (Before 2026-10-08 they were
advertised but not implemented: each fell through to a live *code* search for the literal words.)

## The flags, and what they mean

| flag | effect |
|---|---|
| `--limit N` | max hits (default 8) |
| `--json` | machine-readable, includes `source`, `ms`, `index_age_s`, `stale` |
| `--fresh` | bypass every index — **use when you are about to edit the file** |
| `--max-age SEC` | refuse an index older than SEC (default 1200 — the path and ctags indexes are rebuilt every 15 min and the comms index every 30 min, so a 300 s ceiling marked every indexed answer stale and taught readers to ignore the banner). A stale index answers with exit **3** and `"stale":true` |
| `--scope DIR` | add a search root |
| `--all` | opt OUT of the curated scope. **This is the slow one and it is logged. You almost never want it.** |

**Read the exit code, not just the text.** `0` = hits, `1` = no match (a real negative), `3` = answered
but the index may be stale, `4` = nothing was searched (no index on this node), `5` = the index failed
or timed out. A `1` that actually meant `4` is how a search tool lies.

**Provenance is on every indexed answer.** `fa journal` reports the index's age *and* the newest entry it
covers (`covers_through`, `index_entries`): measured 2026-10-08, a 29-minute-old index on a checkout that
was behind still read as "minutes fresh" while silently stopping at September. If `covers_through` is not
today, the answer may be missing today's entries — check `git -C ~/code/harness-config log --oneline -1`
before believing a "no match".

**`data` needs the comms index, which lives on `secratary` only.** On any other node `fa data` refuses
with exit 4 and says so, rather than answering "no match" from an index that is not there; from a laptop,
reach business data through `ps_comms_search` / `ps_comms_person` instead.

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
