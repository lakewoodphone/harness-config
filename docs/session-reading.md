# Reading DSH sessions — the store, the tool, and why it used to fail

**Tool:** `scripts/sessions.mjs` (node, one file, synced to every machine).
**First thing to run on a new machine:** `node scripts/sessions.mjs doctor`.
**Rule:** a session id is resolved and read from the FILE, never from the authority
database, and every reading prints where it came from and how old it is.

---

## 1. Where sessions actually live

Each machine keeps its own sessions. They are **not** replicated; the authority's
copy is an ingest, not the original.

```
$DSH_HOME/sessions/<slugified-cwd>/<session-dir>/session.v<N>.jsonl.zstd     live
$DSH_HOME/sessions-archive/<slugified-cwd>/<session-dir>/session.v<N>.jsonl.zstd   moved here by session-corpus.mjs
$DSH_HOME/storages/session_projcache/sessions/<session-dir>.json             title, preset, cwd, createdAt
```

* `<slugified-cwd>` for `/home/zabz/phone` is `--home-zabz-phone--`; for
  `C:\Users\ezabz\code` it is `--C-Users-ezabz-code--`. **The same cwd slug appears
  on both a Linux box and a Windows box with different content** — always read the
  host, never just the slug.
* The current format version is `v4` on some machines and `v3` on others. Match
  `/^session\.v\d+\.jsonl\.zstd$/`; never hardcode `v3`.
* A directory named `session-<uuid>` is a chat the owner had; a bare `<uuid>` is a
  subagent. That is a **convention**, and the transcript header (`origin`,
  `parentSession`) is the authority — `sessions show` prints the header value.
* Sessions do **not** live in the web UI's database, and they are not gone when the
  window closes.

## 2. Why a naive read fails — seven measured reasons

Each one is why the tool is written the way it is.

1. **The file is not one zstd stream.** It is one independent frame per appended
   event — a 1.4 MB session here is **1,083 frames**. `zlib.zstdDecompressSync(buf)`
   and Python's `ZstdDecompressor().stream_reader(f)` both stop at the first frame
   and return ~200 bytes, so the session renders as empty. The tool splits on the
   zstd magic `28 b5 2f fd` and decodes every frame, widening the window when a
   magic sequence occurs by chance inside compressed data.
2. **The decoding machine is not the storing machine.** Measured 2026-10-09:
   `secratary` runs **node v20.20.2**, where `zlib.zstdDecompressSync` is
   `undefined` (it needs node ≥ 22.15), and a Python with **no `zstandard`
   module**. So decoding is always done locally, on the caller's machine, and the
   remote host is never asked to decode. `zstd` is not a remote dependency.
3. **A binary `cat` through PowerShell corrupts bytes.** `pwsh` decodes a native
   command's stdout to text. The fetch path lives inside node's `spawn` with raw
   `Buffer` capture for exactly this reason. Never pipe a session file through a
   shell.
4. **Not every node has a POSIX shell.** `ssh zabz-tech-ts head -c 4096 …` answers
   *"The term 'head' is not recognized"* — a Windows node's ssh shell is
   PowerShell, so `cat`/`head`/`grep` do not exist. All remote work is therefore a
   **node program sent over stdin** (node is guaranteed: DSH runs on every node),
   which also removes every shell-quoting problem — the remote path is a JSON
   string literal inside the program.
5. **One ssh per session is a connection storm.** Measured 2026-10-09: with 16
   concurrent ssh sessions to one host, **103 of 107 reads failed** with
   `connect to host … port 22: Connection timed out`. A whole-host search now
   reads **every candidate over one connection** as a framed stream
   (`@@SEG <i> <len> <size> <err>\n` followed by exactly `len` raw bytes).
   After that change: **107 of 107 read**. Length-delimited framing, not a magic
   marker, so a frame can never be found by accident inside compressed data.
6. **ssh to a Tailscale host is not cheap.** Measured on ZABZ-YOGA:
   `ssh secratary-ts hostname` = **1,441 / 9,224 / 11,038 ms** on three consecutive
   attempts; `node -e 0` over the same link adds 1,300–2,100 ms. So: one inventory
   per fleet (cached), a 5-minute TTL for listings and a **6-hour TTL for
   id→file resolution** (a mapping is stable; `latest` always takes the short TTL),
   and never re-inventory to resolve an id we have already seen.
7. **A transcript read can poison a context.** A 1,716-event session is mostly
   runtime-context snapshots, skill catalogs and tool noise; four human turns are
   the actual conversation. Default output is the human conversation only;
   `--tools`, `--reasoning` and `--all-user` opt into the rest, and every omitted
   class is reported as a count.

## 3. The tool

```
node scripts/sessions.mjs doctor                          prove the reader works end to end
node scripts/sessions.mjs nodes                           fleet, reachability, live/archive counts
node scripts/sessions.mjs list  [--since 7d] [--limit 30] [--sub] [--project phone]
node scripts/sessions.mjs find  <words…> [--since 30d] [--scan N] [--scan-all] [--full]
node scripts/sessions.mjs show  <id|latest> [--user] [--turn N] [--tools] [--reasoning] [--out FILE]
node scripts/sessions.mjs grep  <regex> <id>
node scripts/sessions.mjs resolve <id>

common:  [--host NODE|all] [--all] [--refresh] [--json] [--max-chars N]
```

* `<id>` accepts a full id, any unique prefix, a substring, `latest`,
  `latest@host`, `host:id`, or the `session-<uuid>` directory name.
* `--host` takes a configured node name **or any ssh alias**, so a machine can be
  read before it is in the config file.
* `--json` gives provenance and rows for an agent; `--out FILE` writes a rendered
  transcript for a human.
* `--user` is the fastest way to understand a long session: the owner's own turns,
  in order, nothing else.

### Cookbook

*"Pull up the session I just had on my phone about X"* — three commands:

```bash
node scripts/sessions.mjs list  --since 2d --sub          # what happened, newest first
node scripts/sessions.mjs find  "the topic words" --since 30d
node scripts/sessions.mjs show  <id from the hit> --host <host> --user
node scripts/sessions.mjs show  <id> --host <host> --max-chars 6000 \
     --tools --out ~/code/phone-transcripts/<date>-<id>.md
```

Then read the file with `grep`/`read` rather than re-reading the session.

## 4. Honesty rules the tool enforces

* **Every reading carries its source**: host, absolute file path, file mtime and
  age, byte size, live-or-archive, `origin` (main vs subagent), event count, zstd
  frames decoded, frames that **failed**, unparseable lines, and the age of the
  cached inventory. A partially decoded session announces its gap.
* **A head read says so.** `find` reads the first 256 KB of each candidate by
  default, and each hit prints `read first X of Y — mentions later in the file are
  NOT visible`. `--full` reads whole files.
* **Coverage is printed, not implied.** `find` says how many sessions it read,
  how many were candidates, and how many in the window were **not** scanned.
* **An empty result is a refusal.** "No match" prints what was actually searched
  and how to widen it, because a search that skimmed one machine and answered
  "nothing" is how a session gets declared lost when it exists.
* **No number without a source.** Do not quote a session count, a newest-session
  time, or a title without saying which node and how old the inventory is.
* **A session in progress is not a session at rest.** The session you are standing
  in contains your own words; `find` excludes `$DSH_SESSION_ID` by default and says
  so, or a search for the topic under discussion returns itself at the top.

## 5. The authority database is a copy, not the original

`secratary` ingests every machine's sessions every 30 minutes
(`scripts/push-dsh-sessions.mjs` → `app/services/dsh_session_ingest.py` →
`dsh_sessions` / `dsh_session_events` + FTS5). Useful, with three traps:

* **`dsh_session_events.created_at` and the table's freshness are INGEST time, not
  event time** — one session carries 24 distinct values. Ingest also lags: on
  2026-10-09 at 02:15Z the DB's newest phone session started 01:27Z while the file
  store already had one at 01:42Z. **Ground truth is the file.**
* The search endpoint requires the ingest token
  (`x-ps-dsh-session-ingest-token`, env `DSH_ARCHIVE_TOKEN`); without it every
  call returns `Missing/invalid DSH session ingest key`, which looks like an empty
  result and is not one.
* `dsh_session_events_fts.rowid` disagreed with the base table's rowid in **23.5 %
  of 407,866 rows** (audit 2026-09-17). Do not join them by rowid.

Use the DB for *"which session mentioned X anywhere in history"* when you have the
token; verify the hit against the file before reporting it.

## 6. Predecessors, and what was wrong with them

| file | state |
| --- | --- |
| `scripts/read-session.js` | correct multi-frame decoder, but local only, no fleet, no archive, no cache. **Superseded** — its decoder is the one this tool uses. |
| `scripts/dsh-sessions.py` | local only, and uses Python `zstandard.stream_reader`, so it silently returns the header frame of a multi-frame session. Needs `zstandard`, absent on `secratary`. **Superseded.** |
| `scripts/session-corpus.mjs` | not a reader: it measures and archives the corpus. It is why `sessions-archive/` must be searched. |
| `scripts/push-dsh-sessions.mjs` | the shipper to the authority; correctly handles frames. |
| `ps_db_query` on `dsh_session_events` | can time out on the 800k-row table, and reports ingest time. Not a reader. |

## 7. Known limits — do not oversell it

1. A title comes from `session_projcache` when the session has one; archived or
   very old sessions may have none, in which case the title is empty and the first
   user turn is the only label.
2. `find` is lexical, not semantic: it counts term occurrences. Words that are
   spelled differently, or a topic expressed as a paraphrase, will not be found.
   Widen with `--full` and `--scan N` before concluding a session does not exist.
3. The full-fleet `find` window defaults to 30 days and the newest 200 sessions;
   older history needs `--since` and `--scan N` explicitly.
4. The index cache is per-machine and per-user (`$DSH_HOME/session-index.json`).
   It is a cache of *inventory*, never of transcript content.
5. Nothing prunes sessions, and `session-corpus.mjs archive` moves them without
   telling this tool — the archive root is read, but a session archived under a
   *different* `DSH_HOME` is invisible. If a machine is missing sessions, run
   `nodes` and compare the live/archive counts against what the owner expects.

## 8. Configuring a new machine

`~/.dsh/session-nodes.json` (optional; built-in defaults cover the current fleet):

```json
{ "nodes": { "secratary": "secratary-ts", "zabz-tech": "zabz-tech-ts" } }
```

The value is an ssh alias. `local` always exists and needs no entry. A node whose
reported hostname equals this machine's is folded into `local`, so a machine never
reads itself over ssh. `--host <alias>` works with no config at all — that is the
fastest way to read a machine that is not yet listed.

Measured on 2026-10-09 (ZABZ-YOGA): 5 nodes, 5,553 session files, full doctor check
**all passed**, one inventory per node, `list` 37 ms from cache, a 107-candidate
whole-host content search in **46 s over one connection per host**.

Recorded in the journal alongside this file: **L3429** and **L3430** (the store /
decoder facts, and the transport facts, each with its measurements) and **W2674**
(the verified build). The tool exists because the owner said, on 2026-10-09:
*"when i ask you to read sessions you many times have problems, that is not good at
all, you should anywyas build robust tooling and docs for this to be set up
properly."*
