# VS Code / Copilot chat history: the format, verified

Researched 2026-09-14 for the search-and-memory build. Sources are third-party replayers and
VS Code issue reports, because **the format is officially undocumented** — the entire
`code.visualstudio.com/api/references/vscode-api` page describes `chat.createChatParticipant` and
nothing about the session files. `chatSessionsProvider` is a *producer* API (how an extension supplies
sessions to the Sessions view) and says nothing about `kind:0/1/2`. Treat the schema below as strong
empirical evidence, not a spec: re-verify on every VS Code major.

## The file

`%APPDATA%\Code\User\workspaceStorage\<hash>\chatSessions\<uuid>.jsonl` — an append-only patch log.
Also: `…\User\globalStorage\emptyWindowChatSessions\*.jsonl` (untitled-window sessions), and
`…\workspaceStorage\<hash>\GitHub.copilot-chat\transcripts\*.jsonl` (Agent Debug Logs, **opt-in**, so
sparse; currently 111 files here).

Records, one JSON object per line:

| record | meaning |
|---|---|
| `{"kind":0,"v":{…}}` | session header: `sessionId`, `creationDate`, `requests[]`, `inputState` |
| `{"kind":1,"k":[path],"v":val}` | set a value at `path` |
| `{"kind":2,"k":["requests"],"v":[…]}` | **append** request objects |
| `{"kind":3,…}` | **delete** patch — ignoring it resurrects deleted values |

**Measured on our own corpus, not taken on faith.** Patch paths seen in the real files:

```
requests.0.response            37
requests.2.response             5
requests.1.responseMarkdownInfo 1
requests.2.result               1
requests.2.followups            1
requests.0.modelState           1
```

So the assistant's answer usually arrives as a **field patch onto an existing request**
(`{"kind":1,"k":["requests",N,"response"]}`), not inside the request object. A parser that only reads
the initial `kind:2` records silently drops most of the conversation — which is exactly the bug the
first version of `chatindex.py` had, and why it found ~15k turns where the corpus holds far more.

Inside a request: `message.text` is the human turn (5,717 chars in one sample), `response` the
assistant's (str, list of str, or list of objects with `value`/`text`/`content`), plus `requestId`,
`timestamp` (ms), `modelId`, `modeInfo`, `agent`, `contentReferences[].reference.fsPath`, and
`metadata.toolCallRounds`/`toolCallResults` (megabytes of tool output — index the tool *names*, not
the dumps).

## Size, measured here

| fact | value |
|---|---|
| `chatSessions/*.jsonl` | **737 files, 16.97 GB**, 42 over 100 MB, largest **1,050 MB** |
| line length | median **15 KB**, p90 **49 MB**, max **419 MB in a single line** |
| `~/.copilot/pkg` | 1,736 MB — **the CLI's own versioned runtime, not history; exclude it** |
| `~/.copilot/session-state` | 528 MB, 4,956 files — real history (`events.jsonl` per session) |

The 419 MB single line is the reason the reader must bound line length and skip rather than buffer.

## Corruption modes that must be handled

1. **Truncation to an empty `kind:0`** — closing VS Code with a chat open can leave a log containing
   only `{"kind":0,…,"requests":[]}`. Silent and intermittent. Measured here: **81 of 381 sessions**
   parsed as `torn_tail`.
2. **BOM + missing base record** — `ChatSessionStore: Malformed session data … Unexpected token ''`.
3. **Near-empty sessions** — many files legitimately hold zero or one exchange; that is data, not loss.
4. **VS Code 1.109 split the format**: pre-1.109 a single full-JSON `<uuid>.json`; 1.109+ the `.jsonl`
   patch log. Old files are never migrated. When both exist, **`.jsonl` wins**.

Design consequence: if a later `kind:0` has fewer requests than the replayed state, **keep the replay
and flag it** — preferring the last `kind:0` silently deletes conversations.

## Copilot CLI (`~/.copilot`), which *is* documented

`session-state/<id>/events.jsonl`, envelope `{type,data,id,parentId,timestamp}` ISO-8601. Types include
`session.start`, `user.message` (`data.content`), `assistant.message` (`content` + `toolRequests[]`),
`tool.execution_start/complete`, `assistant.reasoning`, `assistant.turn_start/end`, `session.shutdown`.
Layout moved from flat `<id>.jsonl` to `<id>/events.jsonl` in CLI 1.0.11 — handle both.
`workspace.yaml` carries the cwd/branch, because the events themselves do not know their project.
`session-store.db` is SQLite with an FTS5 index over turns only, and `/chronicle reindex` **syncs
session data to the GitHub account** — worth knowing before running it.

## Engineering rules adopted

- Stream: binary mode, 1 MB reads, never `readlines()`, never `json.load()` on the whole file.
- Bounded line guard; on breach, record and skip forward, never raise.
- Checkpoint the byte offset **in the same transaction** as the rows it describes.
- Resume needs more than size: `kind:0` is rewritten in place, so a shrink or older mtime forces a
  full re-parse.
- Identity is `(session_id, request_id)`, not line numbers, so `INSERT OR REPLACE` is idempotent.
- A `parser_version` column, or stale extractions accumulate silently when the parser improves.
- **Do not chunk for search.** The turn is the atomic unit; chunking dilutes BM25 and breaks phrase
  search. Record `char_start`/`char_end` per message — 16 bytes now — so semantic chunks can be added
  later without re-reading 15 GB.
- Capture per message now, because it is impossible later: session, request_id, role, ts, model
  (**per turn** — sessions switch models mid-conversation), workspace, tool names, quality flags.

## Tools worth evaluating before writing more

- `vscode-chat-export` (ChrisMayfield, MIT) — a working `kind:0/1/2` replayer; copy its
  longest-suffix-overlap idea for streaming overwrites. **Do not copy its I/O** (`[json.loads(l) for l in f]`
  will OOM on a 1 GB file).
- `copilot-session-tools` (Arithmomaniac, PyPI, MIT) — already parses `session-state` + `workspaceStorage`
  into an FTS5 store and is incremental by default. **Evaluate before extending our own indexer.**
- `codeburn` — the clearest prose description of the delta journal.

There is **no supported export interface above the raw format**. `Chat: Export Chat…` is official but
manual and per-session — useful as ground truth to validate the parser, not as a pipeline.
