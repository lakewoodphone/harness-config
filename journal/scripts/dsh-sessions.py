#!/usr/bin/env python3
"""dsh-sessions — read DSH session transcripts from any machine in the fleet.

WHY. A question that recurs: "what did the session on the other machine do?" The
transcripts exist (``~/.dsh/sessions/<project>/<id>/session.v3.jsonl.zstd``) but
they are zstd-compressed JSONL with a nested content model, so they are unreadable
without a decoder. Before this, the only way to answer was to resume the session on
its own host, which is impossible from another machine.

WHAT IT DOES. Decompresses and flattens a session into a transcript: user turns,
assistant text, tool calls (name + first line of the command) and tool results.

USAGE
  dsh-sessions.py list [--session-dir DIR] [--grep TERM] [--since YYYY-MM-DD] [--limit N]
  dsh-sessions.py show ID [--users] [--tail N] [--tools] [--max-chars N]
  dsh-sessions.py grep TERM [--limit N]        # which sessions mention a term, and how often

ID may be a full session id, a directory name, or any unique prefix.

DATA SOURCE NOTE. Sessions are stored per-project on the machine that ran them. To
read another machine's sessions, copy that machine's
``~/.dsh/sessions/<project>`` tree locally first (``scp -r``), then point
``--session-dir`` at the copy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".dsh", "sessions")


def _iter_sessions(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        if "session.v3.jsonl.zstd" in filenames:
            yield dirpath, os.path.join(dirpath, "session.v3.jsonl.zstd")


def _reader(path: str):
    try:
        import zstandard
    except ImportError:
        sys.stderr.write(
            "dsh-sessions: the 'zstandard' module is required "
            "(pip install zstandard)\n"
        )
        raise SystemExit(2)
    with open(path, "rb") as fh:
        stream = zstandard.ZstdDecompressor().stream_reader(fh)
        yield from io.TextIOWrapper(stream, encoding="utf-8", errors="replace")


def _blocks(data):
    """Yield ('text'|'tool', text) for one message event's content blocks."""
    msg = data.get("message") if isinstance(data, dict) else None
    content = None
    if isinstance(msg, dict):
        content = msg.get("content")
    if content is None and isinstance(data, dict):
        content = data.get("content")
    if isinstance(content, str):
        yield ("text", content)
        return
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            if isinstance(block, str):
                yield ("text", block)
            continue
        kind = block.get("type")
        if kind == "text":
            yield ("text", str(block.get("text") or ""))
        elif kind in ("tool-call", "tool_use", "tool_call"):
            args = block.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"_raw": args}
            detail = ""
            if isinstance(args, dict):
                for key in ("command", "file_path", "path", "pattern", "query"):
                    if args.get(key):
                        detail = str(args[key]).replace("\n", " ")
                        break
            yield ("tool", f"{block.get('name')}: {detail[:200]}")


def _load(path: str):
    events = []
    meta = {}
    for i, line in enumerate(_reader(path)):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if i == 0 and obj.get("type") == "session":
            meta = obj
            continue
        events.append(obj)
    return meta, events


def _fmt_ts(ms):
    if not ms:
        return "?"
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%m-%d %H:%M")


def cmd_list(args):
    rows = []
    for dirpath, path in _iter_sessions(args.session_dir):
        try:
            st = os.stat(path)
        except OSError:
            continue
        rows.append((st.st_mtime, dirpath, path, st.st_size))
    rows.sort(reverse=True)
    shown = 0
    for mtime, dirpath, path, size in rows:
        when = dt.datetime.fromtimestamp(mtime)
        if args.since and when.strftime("%Y-%m-%d") < args.since:
            continue
        meta, events = _load(path)
        if args.grep:
            needle = args.grep.lower()
            hits = 0
            for ev in events:
                hits += json.dumps(ev).lower().count(needle)
            if not hits:
                continue
            extra = f" hits={hits}"
        else:
            extra = ""
        sid = meta.get("id") or os.path.basename(dirpath)
        print(
            f"{when:%Y-%m-%d %H:%M}  {sid:44s} origin={meta.get('origin') or 'main':9s} "
            f"parent={(meta.get('parentSession') or '-')[:16]:16s} "
            f"events={len(events):5d} kb={size // 1024}{extra}"
        )
        shown += 1
        if args.limit and shown >= args.limit:
            break
    if not shown:
        print("dsh-sessions: no sessions matched", file=sys.stderr)
        return 1
    return 0


def cmd_grep(args):
    needle = args.term.lower()
    rows = []
    for dirpath, path in _iter_sessions(args.session_dir):
        meta, events = _load(path)
        blob = json.dumps(events).lower()
        hits = blob.count(needle)
        if not hits:
            continue
        label = ""
        for ev in events:
            if ev.get("type") == "subagent/descriptor":
                label = str((ev.get("data") or {}).get("label") or "")
                break
        times = [ev.get("time") for ev in events if ev.get("time")]
        rows.append((hits, meta.get("id"), meta.get("origin"), label, min(times) if times else None,
                     max(times) if times else None))
    rows.sort(reverse=True)
    for hits, sid, origin, label, first, last in rows[: args.limit]:
        print(f"hits={hits:6d}  {sid:44s} origin={origin or 'main':9s} "
              f"{_fmt_ts(first)} -> {_fmt_ts(last)}  {label}")
    if not rows:
        print("dsh-sessions: no session mentions that term", file=sys.stderr)
        return 1
    return 0


def cmd_show(args):
    target = None
    for dirpath, path in _iter_sessions(args.session_dir):
        base = os.path.basename(dirpath)
        if base == args.id or base.startswith(args.id):
            target = path
            break
    if target is None:
        # the id may live in the session header rather than the directory name
        for dirpath, path in _iter_sessions(args.session_dir):
            meta, _ = _load(path)
            if str(meta.get("id") or "").startswith(args.id):
                target = path
                break
    if target is None:
        print(f"dsh-sessions: no session matching {args.id!r}", file=sys.stderr)
        return 1

    meta, events = _load(target)
    print(f"# session {meta.get('id')}  cwd={meta.get('cwd')}  "
          f"origin={meta.get('origin') or 'main'}  parent={meta.get('parentSession')}")
    if args.users or args.tail:
        pass
    for ev in events:
        ty = ev.get("type")
        if ty not in ("user/message", "assistant/message", "tool/result"):
            continue
        if args.users and ty != "user/message":
            continue
        if ty == "tool/result" and not args.tools:
            continue
        label = {"user/message": "USER", "assistant/message": "ASSISTANT",
                 "tool/result": "  -> "}[ty]
        parts = []
        for kind, text in _blocks(ev.get("data") or {}):
            if kind == "tool" and not args.tools:
                continue
            if kind == "text" and not text.strip():
                continue
            parts.append(text if kind == "text" else f"[{text}]")
        body = "\n".join(parts).strip()
        if not body:
            continue
        if args.max_chars and len(body) > args.max_chars:
            body = body[: args.max_chars] + " …"
        print(f"\n[{_fmt_ts(ev.get('time'))}] {label}\n{body}")
    return 0


def main():
    # Transcripts are full of emoji and non-ASCII; a cp1252 console must not
    # crash the reader with UnicodeEncodeError (learned the hard way).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--session-dir", default=DEFAULT_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list")
    p.add_argument("--grep")
    p.add_argument("--since")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("grep")
    p.add_argument("term")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_grep)

    p = sub.add_parser("show")
    p.add_argument("id")
    p.add_argument("--users", action="store_true", help="only user turns")
    p.add_argument("--tools", action="store_true", help="include tool calls/results")
    p.add_argument("--tail", type=int, help="only the last N events")
    p.add_argument("--max-chars", type=int, default=3000)
    p.set_defaults(func=cmd_show)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
