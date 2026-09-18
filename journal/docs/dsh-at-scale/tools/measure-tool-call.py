#!/usr/bin/env python3
"""Measure one tool's call duration from the authoritative session log.

WHY THIS EXISTS
`list_agents` had no deadline and no cache, so "how long did that call take" is
the only honest way to say whether replacing it helped. The engine records
`tool/call` and `tool/result` events with the same `callId` and an epoch-ms
`time`, so the duration is read from the record — not inferred, not timed by a
wrapper that would itself change the measurement.

    python measure-tool-call.py <session-id|latest|substring> <tool-name> [--tail N] [--json]

Sessions live in $DSH_HOME/sessions/<slug>/<id>/session.v3.jsonl.zstd and the
decoding is delegated to harness-config's own read-session.js (the transcript is
one zstd frame per event, which is easy to get wrong — see that file's header).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

READER = Path(os.environ.get("DSH_READ_SESSION", r"C:\Users\ezabz\code\harness-config\scripts\read-session.js"))


def raw_events(session: str) -> list[dict]:
    """Decode one session log through read-session.js.

    The transcript is written to a temp FILE rather than captured from a pipe:
    under this harness a program that captures another program's stdout through
    a pipe can fail with EPERM / `_readerthread` errors on Windows, and the
    failure is in Python's reader thread rather than in the reader itself.
    Redirecting to a file sidesteps the pipe entirely.
    """
    if not READER.exists():
        sys.exit(f"no session reader at {READER}; set DSH_READ_SESSION")
    import tempfile

    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False, encoding="utf-8") as handle:
        dump = Path(handle.name)
    try:
        done = subprocess.run(
            ["node", str(READER), "--raw", session],
            stdout=open(dump, "w", encoding="utf-8"),
            stderr=subprocess.PIPE,
            text=True,
        )
        if done.returncode != 0:
            sys.exit(f"read-session failed: {(done.stderr or '').strip()[:400]}")
        events = []
        with dump.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events
    finally:
        try:
            dump.unlink()
        except OSError:
            pass


def kind_of(event: dict) -> str:
    return str(event.get("type") or event.get("kind") or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("tool")
    ap.add_argument("--tail", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="emit one JSON object per call")
    args = ap.parse_args()

    events = raw_events(args.session)
    calls: dict[str, dict] = {}
    order: list[str] = []
    durations: list[dict] = []

    for event in events:
        kind = kind_of(event)
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        if kind == "tool/call":
            if data.get("name") != args.tool:
                continue
            call_id = str(data.get("callId"))
            calls[call_id] = {"start": event.get("time"), "seq": event.get("seq"), "step": data.get("step")}
            order.append(call_id)
        elif kind == "tool/result":
            message = data.get("message") or {}
            source = message.get("source") or {}
            call_id = str(source.get("callId"))
            record = calls.get(call_id)
            if record is None:
                continue
            record["end"] = event.get("time")
            text = ""
            for block in message.get("content") or []:
                for inner in block.get("content") or []:
                    if inner.get("type") == "text":
                        text = str(inner.get("text") or "")
            record["result"] = text[:120]
            record["resultChars"] = len(text)

    for call_id in order:
        record = calls[call_id]
        start, end = record.get("start"), record.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            durations.append({
                "callId": call_id,
                "startMs": start,
                "durationMs": int(end - start),
                "resultChars": record.get("resultChars", 0),
                "result": record.get("result", ""),
            })
        else:
            durations.append({"callId": call_id, "durationMs": None, "note": "no matching result event"})

    if args.json:
        for row in durations[-args.tail:]:
            print(json.dumps(row))
        return 0

    print(f"{len(events)} events, {len(durations)} {args.tool} call(s) with a matched result")
    for row in durations[-args.tail:]:
        if row.get("durationMs") is None:
            print(f"  {row['callId']}: {row.get('note')}")
        else:
            print(f"  {row['durationMs']:>7} ms  result {row['resultChars']:>6} chars  {row['result'][:60]!r}")
    measured = [row["durationMs"] for row in durations if row.get("durationMs") is not None]
    if measured:
        measured.sort()
        print(f"  n={len(measured)} min={measured[0]} ms median={measured[len(measured) // 2]} ms max={measured[-1]} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
