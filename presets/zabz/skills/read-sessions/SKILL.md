---
name: read-sessions
description: Use whenever a session, chat, transcript or "conversation I had" is asked for — pull one up, find which session it was, read what a session on another machine did, or quote it later. Covers one tool, `scripts/sessions.mjs`, that reads any DSH session on any machine in the fleet, live or archived. Triggers on "pull up the session", "the chat I had", "what did that session do", "find the session about X", "read the session on the phone/desktop", "the long session I just had", a session id, or any attempt to open `~/.dsh/sessions` by hand. Read this BEFORE touching the session store, `Dsh_session_events`, or ps_db_query for a transcript.
---

# Reading a session — one tool, any machine, first try

**`node scripts/sessions.mjs <cmd>`** from `~/code/harness-config` (on Linux:
`~/harness-config`). Diagnose a new machine once with `sessions doctor`.

## The four commands that answer almost everything

```bash
node scripts/sessions.mjs list --since 2d --sub              # what happened, newest first, with titles
node scripts/sessions.mjs find "the topic" --since 30d       # which session was it
node scripts/sessions.mjs show <id> --host <host> --user     # the owner's own turns — read this first
node scripts/sessions.mjs show <id> --host <host> --max-chars 6000 --tools --out /tmp/x.md
```

`<id>` takes a full id, a prefix, a substring, or `latest`. `--host` takes a node
name or any ssh alias. `--all` searches the whole fleet.

## The three mistakes that make this look broken

1. **Decoding it yourself.** The file is one zstd frame **per event** — 1,083 frames
   in a 1.4 MB session. A single `zstdDecompressSync` or Python `stream_reader`
   returns the ~200-byte header and the session renders empty. Use the tool.
2. **Fetching it through a shell.** `pwsh` mangles binary stdout, and a Windows
   node's ssh shell is PowerShell — there is no `cat` or `head` there. The tool
   sends a node program over ssh stdin and captures raw Buffers.
3. **Looking in one place.** Sessions are in `~/.dsh/sessions/` **and**
   `~/.dsh/sessions-archive/` (moved by `session-corpus.mjs`), on the machine that
   ran them. The authority DB is a 30-minute-lagged copy.

## Non-negotiables

* **A transcript read is a context read.** Default output is the human conversation;
  `--user` is the fastest way into a long session. Never dump a whole session into
  a context — write it to a file with `--out` and grep the file.
* **Quote the provenance.** Every read prints host, absolute path, file mtime, size,
  events, frames decoded, frames **failed**, and the inventory's age. If frames
  failed, the transcript has a gap — say so. Never report a session's contents
  without the id and host they came from.
* **A head read is partial.** `find` reads the first 256 KB and prints
  `read first X of Y`. `--full` reads whole files. Say which one you did.
* **"No match" is a refusal, not evidence.** It prints what it actually searched and
  how to widen. Before telling the owner a session is gone, re-run with
  `--since 90d --scan-all --sub`, and `sessions nodes` to prove the machine answered.
* **The session you are in is not the session he means.** `find` excludes
  `$DSH_SESSION_ID` by default because a search for the topic under discussion
  otherwise returns itself at the top.
* **Never read the store by hand** and never `ps_db_query` `dsh_session_events` for a
  transcript: `created_at` there is ingest time, the table can time out, and its FTS
  rowids disagree with the base table in 23.5 % of rows.

## Finding the session he means, when the topic is not in the title (2026-10-14)

A session titled **"Set up iPhones in Apple Business Manager"** is the one that turned Bluetooth on
for the Waze kiosks. Searching for the topic — `waze`, `bluetooth` — did not lead there, and that cost
hours. The work was turn 18 of a 2,398-event, 2.7 MB session titled after its *first* request.

* **Search for a string that must appear in the work, not the topic.** A filename, a profile key, a
  script name. `find "verify_pushed_bluetooth check_kiosk_keys" --full` found it in one shot; the
  topic word did not.
* **`--full` is not optional when the answer matters.** The default reads the first 256 KB and says so
  on every line. A long session's decision is usually past that.
* **A long session is titled after its opening request.** When `find` gives nothing on the topic, run
  `list --since 3d --sub` and read the *titles of long sessions* — a 2.7 MB session that does not
  mention your topic in its title is the most likely suspect, not the least.
* **Do not dismiss a low score as noise.** `find` ranks by term presence damped by repetition
  (changed 2026-10-14, because raw counts let a 1 MB runtime-context dump outrank the real session
  300-to-1). If a session is in the list at all, read its header and its `--user` turns before
  deciding it is not the one.
* **If `doctor` reports a missing decoder, the fix is printed with it.** The tools now self-elevate
  onto any capable node they can find; if you see that message, set `DSH_NODE` to a node ≥ 22.15.

Full detail, measurements and the predecessor tools' defects:
`~/code/harness-config/docs/session-reading.md`.
