# Search & memory: audit before design

Session 2026-09-14 (this turn began 2026-09-11 18:20 EDT; it is now 2026-09-14 ~03:2x UTC).

## The complaint, in the owner's words

> "the memory files and repo indexes and finding and recording info … now when you search, you many times do
> recursive searches that take a few minutes and still don't find what you need … audit, research and fix from
> the ground up after serious web research and analysis, and install all the needed packages scripts and tools
> and make search retrieval way faster and more robust, and memories and topics way better indexed and
> recorded … we have repos and repos and probably a year of vscode chats and more that contain goldmines of
> info about me and what i need and my systems"

Two distinct failures are being described, and they need separate fixes:

1. **Latency.** Searches walk the filesystem every time, so a query costs minutes.
2. **Recall.** Even after spending those minutes, the answer is often absent — because the corpora that
   contain the answer were never ingested.

## Measured baseline (read, not assumed)

| Fact | Value | Source |
|---|---|---|
| ripgrep on ZABZ-TECH | **15.1.0** (`rev af60c2de9d`), at `…\WinGet\Packages\BurntSushi.ripgrep…\rg.exe` | `rg --version` |
| ripgrep on secratary | **14.1.0** | `rg --version` |
| Everything (voidtools) | **absent** on ZABZ-TECH | `Get-ChildItem 'C:\Program Files\Everything*'` |
| ollama | **absent** on both hosts | `ollama list` / `command -v ollama` |
| Vector DB (qdrant/meilisearch/tantivy) | **absent** on secratary | `command -v` sweep |
| `~/repos` | **10 GB** | `du -sh` |
| `personal-secretary-mvp` | **21 GB** | `du -sh` |
| `vscode_chat_messages` | **4,368** rows (of 1,592 sessions, 281 exports) | `sqlite3` |
| `memories` | 18,256 rows, FTS present (`memories_fts`) | `sqlite3` |
| `memory_vectors` | **UNUSABLE** — `no such module: vec0` | `PRAGMA`/count probe |
| Existing services that *sound* relevant | `unified_memory.py`, `semantic_memory.py`, `workspace_search.py`, `project_memory.py`, `procedural_memory.py`, `memory_consolidation.py` | `ls app/services` |
| DSH session archive | `dsh_sessions` / `dsh_session_events` / FTS — 2.6 GB DB | previous audit |

## Why it is slow, and why it will stay slow

`rg` is already the right primitive; the problem is that **nothing is indexed**, so every query re-walks
the tree. On this fleet a walk has to cross `node_modules`, `.git`, `.venv`, `__pycache__`, `dist`, `.next`,
and a 21 GB project directory before it matches anything. That is the cost the owner is paying, every time.

It is also why the *same* cost is paid per host and per session: no result is remembered.

## Why it is incomplete

The corpora that plausibly hold the "goldmine" are not all being searched:

- **VS Code chats**: only 4,368 messages are in the DB, from 1,592 sessions / 281 exports. A year of chat
  suggests far more on disk than that.
- **Android Studio / Copilot / Cursor histories** — other tools the owner has used (the audit corpus mentions
  Copilot usage collapsing after April 2026). Are these present on disk at all?
- **Git history**: commit messages and diffs are a rich record of decisions and are not indexed anywhere.
- **Documents**: `docs/` trees across ~28 repos, PDFs, spreadsheets.
- **Email/SMS/calls**: in the company DB, but not reachable by a text query from my side.
- **`memory_vectors` is dead** (`vec0` missing), so the vector half of memory has never run.

## Design direction (to be validated by research, not asserted)

- **One index, not many readers.** A SQLite database (already the fleet's storage idiom, no new daemon,
  2.6 GB instances already proven at this size) using **FTS5** for lexical search, plus vectors if and only
  if embeddings can be produced reliably.
- **Instant filename search** needs a file-name index (MFT on Windows; a prebuilt path table on Linux),
  because the cheapest query is the one that never touches content.
- **Never re-walk.** Incremental updates keyed on (path, size, mtime, content hash).
- **Measurable target.** Every claim about speed must be a before/after with the same query, in milliseconds —
  not an adjective.

## Open questions for research

1. What is the current best practice for local hybrid (lexical + semantic) code/docs retrieval in an agent
   harness? Trigram vs porter FTS5, reranking, chunking strategy for code.
2. Which local embedding model gives usable quality at acceptable speed on this hardware (i9/64 GB desktop,
   22 GB RAM server), and can it run offline?
3. Zoekt vs ripgrep vs a prebuilt path index — what actually wins on 10–20 GB corpora with repeated queries?
4. How to ingest a year of VS Code chat history robustly, including other tools' session stores.
