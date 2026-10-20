#!/usr/bin/env python3
"""session-sweep.py — turn the day's finished chats into work, or decide they need none.

THE GAP THIS CLOSES, and it is the owner's own words (2026-10-18): the autonomous system must
"go through that day's sessions and previous day sessions and find goals and work on projects".
Measured that night: **239 DSH sessions ran in 48 hours and ZERO handoffs were written.** Nothing
anywhere maps a session to an obligation. `dormant-handoff.py` reads journal handoffs and archive
freshness; `continuation.py` exists but its database holds 0 rows; there is no session-end hook in
the harness at all. So a session that ends with "I'll do X next" or an unanswered question simply
evaporates, and the only way it comes back is if the owner remembers and says so.

WHAT IT READS, AND WHY THAT IS CHEAP. Not the transcript files, and not a table scan. The session
archive is already on this box: `/root/authority.db` tables `dsh_sessions` (8,326 rows, real
`updated_at`) and `dsh_session_events`, indexed on `(source_machine, session_id, seq)`.
  * candidate sessions : one scan of the SMALL table, bounded by `updated_at`;
  * the final answer   : ONE index probe per session (`... order by seq desc limit 1`);
  * assistant text     : `data.message.content` is a list of parts; `type == "text"` is the ANSWER
                         and `type == "reasoning"` is the model thinking. Only `text` is read, so
                         this never grades chain-of-thought as if it were a report.
MEASURED WARNING: `select count(*) from dsh_session_events where created_at > ...` DOES NOT
FINISH on this host (it ran > 3 minutes and had to be killed — the column is unindexed and the
table is millions of rows). Never write that query. Always enter by session id.

WHAT IT DOES WITH A HIT. It files at most `--max-flags` wake rows (default 3) per run and per day,
subject `session-sweep:<session_id>` — stable, so `wake.py` dedupes and a re-run cannot double-file.
The prompt QUOTES the session's own closing words verbatim and asks the session to verify before it
believes them. That ordering matters: a regex is a CANDIDATE, not knowledge, and the wake rule says
a flag may only be raised by something that knows there is work. So the flag says "here is what was
said; confirm it and do it, or close it as nothing" — and "nothing here" is an allowed outcome that
must carry its reason.

It never sends anything, never writes to the ledger itself, never touches the authority's tables.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SOURCE = "session-sweep"

# --- classification -------------------------------------------------------
# These are deliberately NARROW. A broad pattern ("I'll" anywhere in 40 KB of prose) cried wolf in
# the measurement: on a sample of 21 human sessions the loose test produced ~5 clean cases against
# 63 raw hits. So the tail is short, the phrases are explicit, and the session decides.
COMMITMENT_RE = re.compile(
    r"(?:\bnext i will\b|\bnext step\b|\bi will (?:now |then )?\w+|\bi'll \w+"
    r"|\bstill need(?:s)? to\b|\bremains? to be\b|\bnot yet\b|\bleft to do\b"
    r"|\bunfinished\b|\bwant me to\b|\bsay the word\b|\bshall i\b|\blet me know\b)",
    re.IGNORECASE,
)
HANDOFF_WRITTEN_RE = re.compile(r"\b(?:handoff|H\d{4,})\b", re.IGNORECASE)
REMIND_RE = re.compile(r"\bremind me\b[^.\n]{0,120}", re.IGNORECASE)
# A wake/mesh session is machine work, not an owner commitment. Its prompt carries these banners,
# and its cwd is the npx cache. Both are cheap to test and neither can be a false positive.
MACHINE_BANNERS = ("=== WAKE CONTRACT", "=== mesh mailbox", "SHIFT PACKET")

TAIL_CHARS = 1400          # enough for the closing paragraph, small enough to quote verbatim
LOOKBACK_HOURS = 48


def now() -> datetime:
    return datetime.now(timezone.utc)


def db_path() -> Path:
    p = Path(os.environ.get("DSH_ARCHIVE_DB") or "/root/authority.db")
    if not p.is_file():
        raise SystemExit(f"session-sweep: no session archive at {p} (set DSH_ARCHIVE_DB)")
    return p


def wake_cli() -> Path:
    for c in (os.environ.get("WAKE_PY"), "/home/zabz/bin/wake.py", "/root/bin/wake.py"):
        if c and Path(c).is_file():
            return Path(c)
    raise SystemExit("session-sweep: no wake.py found")


def parse_iso(s: str):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def answer_text(raw: str) -> str:
    """The assistant's ANSWER: the `text` parts only, never the `reasoning` parts."""
    try:
        d = json.loads(raw)
    except ValueError:
        return ""
    msg = (d.get("data") or {}).get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    out = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            t = part.get("text")
            if isinstance(t, str):
                out.append(t)
    return "\n".join(out).strip()


def is_machine_session(conn, machine: str, sid: str, cwd: str) -> bool:
    """Wake and mesh children are not owner commitments. Two independent tells, cheapest first."""
    if cwd and "_npx" in cwd:
        return True
    row = conn.execute(
        "select raw from dsh_session_events where source_machine=? and session_id=? "
        "and type='user/message' order by seq asc limit 1",
        (machine, sid),
    ).fetchone()
    if not row:
        return False
    head = (row["raw"] or "")[:4000]
    return any(b in head for b in MACHINE_BANNERS)


def classify(text: str) -> tuple[bool, str, str]:
    """(interesting, reason, reminder_phrase). Narrow by design; see COMMITMENT_RE."""
    tail = text[-TAIL_CHARS:]
    if not tail.strip():
        return False, "", ""
    # A fenced block is QUOTED text -- a draft the assistant was writing, not its own
    # promise. MEASURED 2026-10-18: this is where row 1184's "I'll f" came from.
    tail = re.sub(r"```.*?```", " ", tail, flags=re.DOTALL)
    # Typographic apostrophes are what real prose carries; COMMITMENT_RE spells "i'll"
    # with an ASCII quote and therefore misses "I\u2019ll bring you the answer".
    # Found by this patch's own test, which failed on its first run because of it.
    tail = tail.replace("\u2019", "'").replace("\u2018", "'")
    # A session that already wrote a handoff has been captured by the mechanism we already trust.
    # MEASURED 2026-10-18: the old test collapsed to "mentions an H-number" (see the
    # module docstring) and skipped 50 sessions that never wrote one. Require the act.
    if re.search(r"\bappend\s+handoff\b", tail, re.IGNORECASE):
        return False, "already recorded a handoff", ""
    rem = REMIND_RE.search(tail)
    if rem:
        return True, "explicit reminder request", rem.group(0).strip()
    m = COMMITMENT_RE.search(tail)
    if m:
        # Quote the sentence, not the span: a reason nobody can judge without opening
        # the session is the same defect as a monitor that cannot tell two states apart.
        _s = max(0, m.start() - 70)
        _snip = " ".join(tail[_s:m.end() + 110].split())
        return True, f"commitment phrase: ...{_snip}...", ""
    # An unanswered question in the closing paragraph is the other shape of the same thing.
    last_q = tail.rfind("?")
    if last_q != -1 and (len(tail) - last_q) < 320:
        return True, "closing question", ""
    return False, "", ""


def state_file() -> Path:
    return Path(os.environ.get("SESSION_SWEEP_STATE") or "/root/.sms-inbox/session-sweep-state.json")


def load_state() -> dict:
    try:
        return json.loads(state_file().read_text())
    except Exception:                                            # noqa: BLE001
        return {}


def save_state(st: dict) -> None:
    try:
        state_file().parent.mkdir(parents=True, exist_ok=True)
        state_file().write_text(json.dumps(st, indent=1, sort_keys=True) + "\n")
    except Exception as exc:                                     # noqa: BLE001
        print(f"session-sweep: could not write state ({exc}) - daily cap not recorded",
              file=sys.stderr)


def build_prompt(cand: dict) -> str:
    return "\n".join([
        f"A chat session ended on {cand['machine']} about "
        f"{cand['age_h']:.1f} h ago and NOTHING was recorded about what it left unfinished.",
        f"The sweep noticed: **{cand['reason']}**.",
        "",
        "Its own closing words, quoted verbatim and unedited:",
        "",
        "```",
        cand["tail"].strip(),
        "```",
        "",
        f"Read the whole session before you judge it:",
        f"  node ~/code/harness-config/scripts/sessions.mjs show {cand['session_id']} --host {cand['machine']}",
        "",
        "WHAT TO DO, IN THIS ORDER",
        "1. Decide whether that work is REAL AND STILL OPEN. A closing phrase can be politeness, a",
        "   question the owner already answered in the same session, or work another session has",
        "   since done. Check the ledger and the repo before believing the quote.",
        "2. If it IS open: file it where work actually lives, in the right project, with a provable",
        "   definition of done —",
        "     python3 ~/bin/work.py add --project <project> --title '<one line>' \\",
        "       --why '<the measurement>' --dod '<the command that would prove it>' --priority 3",
        "   — then do it if it fits in the shift. One item, not a wish list.",
        "3. If it is NOT open, or it is really the owner's decision, file ONE owner-queue row",
        "   (never a text) and say which.",
        # A REMINDER IS SCHEDULED, NOT FILED (added 2026-10-18). Until /root/bin/reminder-add.py
        # existed, this source detected "remind me ..." and had nowhere to put it — the sink was
        # missing and the detection was dead data. It inserts one row into the dashboard reminder
        # queue that `process_due_reminders` already drains; it never sends a text.
        "3b. If the session asked for a REMINDER at a time (a deadline, a callback, a payment), do not",
        "   file it as work — schedule it:",
        "     python3 /root/bin/reminder-add.py --message \"<one line>\" --at \"tomorrow 9am|in 2h|ISO8601\" \\",
        "       --source-ref \"" + str(cand.get("session_id") or "") + "\"",
        "   Use the session id as --source-ref: the same key twice is a no-op, so a re-run cannot",
        "   double-schedule. Anything the CLI cannot parse it REFUSES rather than guessing, and a",
        "   refusal is a correct outcome — say so instead of filing an approximate reminder.",
        "4. Then close this wake row with `work.py`-style evidence in your final answer: what you",
        "   found, what you filed, what you did, and the command that shows it.",
        "",
        "DO NOT quote the session back as if it were evidence of work; do not file a second item",
        "for work that is already in the ledger; do not invent work to look busy. 'Nothing here,'",
        "with the reason you ruled it out, is a correct and complete outcome.",
    ])


def archive_lag_hours(conn) -> float:
    """How far behind live the archive is: now minus its own newest row.

    THE DEFECT THIS EXISTS FOR, reported by wake row 1175 itself (2026-10-18, a real shift):
      "ROOT CAUSE OF THE FALSE '27.7 h': session-sweep read the authority copy, whose last row was
       27.7 h old, while the live file had resumed 31 min before the sweep (mtime 01:23Z) and was
       still growing"
    `dsh_sessions` is a PROJECTION pushed hourly, not the live session store, so a session's age read
    from it is an age-plus-ingest-lag. Treating that number as the truth made the sweep flag a
    conversation the owner had already answered and that was still being written. Returns -1.0 when
    the archive cannot be dated at all, which callers must treat as "cannot judge".
    """
    row = conn.execute("select max(updated_at) m from dsh_sessions").fetchone()
    newest = parse_iso(row["m"]) if row and row["m"] else None
    if newest is None:
        return -1.0
    return (now() - newest).total_seconds() / 3600.0


def owner_spoke_last(conn, machine: str, sid: str) -> bool:
    """True when the NEWEST event in the session is the owner's, not the assistant's.

    Same defect, second half. Row 1175's finding was that the owner answered the question *inside the
    same session* (turn 36) — so the assistant's closing "want me to … or will you?" was no longer an
    open commitment by the time the sweep read it. When the owner spoke last the ball is with the
    assistant, the conversation is unfinished in a different sense, and that case belongs to the
    owner-channel sources, not here. Two index probes, no scan.
    """
    a = conn.execute(
        "select max(seq) s from dsh_session_events where source_machine=? and session_id=? "
        "and type='assistant/message'", (machine, sid)).fetchone()
    u = conn.execute(
        "select max(seq) s from dsh_session_events where source_machine=? and session_id=? "
        "and type='user/message'", (machine, sid)).fetchone()
    a_seq = a["s"] if a and a["s"] is not None else -1
    u_seq = u["s"] if u and u["s"] is not None else -1
    return u_seq > a_seq


def collect(args) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    since = now() - timedelta(hours=args.hours)
    rows = conn.execute(
        "select source_machine, session_id, cwd, updated_at, event_count from dsh_sessions "
        "where updated_at >= ? order by updated_at desc",
        (since.strftime("%Y-%m-%dT%H:%M:%S"),),
    ).fetchall()
    lag_h = archive_lag_hours(conn)
    # A session must be quiet by the ARCHIVE's own clock before its closing words are evidence.
    # Quiet means: its newest archived row is older than the archive's newest row by a margin, so it
    # cannot be a conversation that is still growing. Without this the sweep reports an age that is
    # really age+lag and flags live conversations (measured: 27.7 h reported for a session that had
    # resumed 31 min earlier).
    if lag_h < 0:
        print("session-sweep: archive cannot be dated (no dsh_sessions rows) - refusing to judge",
              file=sys.stderr)
        return []
    quiet_before = now() - timedelta(hours=lag_h + args.quiet_margin)
    if args.verbose:
        print(f"session-sweep: archive is {lag_h:.1f} h behind now; a session counts as quiet only "
              f"if last updated before {quiet_before.strftime('%H:%MZ')}", file=sys.stderr)

    already = set()
    try:
        out = subprocess.run([sys.executable, str(wake_cli()), "list", "--limit", "400", "--json"],
                             capture_output=True, text=True, timeout=90).stdout
        payload = json.loads(out or "{}")
        already = {str(r.get("subject")) for r in (payload.get("rows") or [])}
    except Exception:                                            # noqa: BLE001
        pass

    cands: list[dict] = []
    machine_skipped = 0
    live_skipped = 0
    owner_last_skipped = 0
    for r in rows:
        machine, sid = r["source_machine"], r["session_id"]
        if is_machine_session(conn, machine, sid, r["cwd"] or ""):
            machine_skipped += 1
            continue
        upd = parse_iso(r["updated_at"])
        if upd is None or upd > quiet_before:
            # Not quiet yet: it may still be the conversation the owner is having right now.
            live_skipped += 1
            continue
        ev = conn.execute(
            "select raw from dsh_session_events where source_machine=? and session_id=? "
            "and type='assistant/message' order by seq desc limit 1", (machine, sid)).fetchone()
        if not ev:
            continue
        # The owner spoke last: the ball is with the assistant, and that case belongs to the
        # owner-channel sources. It is also how row 1175's false positive arose.
        if owner_spoke_last(conn, machine, sid):
            owner_last_skipped += 1
            continue
        text = answer_text(ev["raw"] or "")
        ok, reason, reminder = classify(text)
        if not ok:
            continue
        subj = f"{SOURCE}:{sid}"
        if subj in already:
            continue
        cands.append({
            "machine": machine, "session_id": sid, "reason": reason,
            "reminder": reminder, "tail": text[-TAIL_CHARS:], "subject": subj,
            "age_h": ((now() - upd).total_seconds() / 3600.0) if upd else -1.0,
        })
    conn.close()
    # Newest first, and never one candidate per session twice (the query already guarantees that).
    cands.sort(key=lambda c: c["age_h"])
    if args.verbose:
        print(f"session-sweep: {len(rows)} session(s) in {args.hours}h, "
              f"{machine_skipped} machine, {live_skipped} still-live, "
              f"{owner_last_skipped} owner-spoke-last, {len(cands)} candidate(s) after dedupe",
              file=sys.stderr)
    return cands


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Turn the day's finished sessions into filed work.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--hours", type=int, default=LOOKBACK_HOURS)
    # A session must be quiet by the ARCHIVE's own clock, not by ours: see archive_lag_hours().
    ap.add_argument("--quiet-margin", type=float, default=2.0,
                    help="extra hours of quiet required on top of the archive's lag (default 2)")
    ap.add_argument("--max-flags", type=int, default=3, help="rows filed per run AND per day")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    try:
        cands = collect(args)
    except SystemExit:
        raise
    except Exception as exc:                                     # noqa: BLE001
        # A source must never break its caller, and must never look quiet when it is broken.
        print(f"session-sweep: UNREADABLE ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1

    if not cands:
        print("quiet")
        return 0

    st = load_state()
    today = now().strftime("%Y-%m-%d")
    if st.get("date") != today:
        st = {"date": today, "filed": 0}
    budget = max(1, args.max_flags) - int(st.get("filed") or 0)
    if budget <= 0:
        print(f"(daily cap reached: {st.get('filed')} filed {today})")
        return 0

    filed = 0
    for cand in cands:
        if filed >= budget:
            break
        prompt = build_prompt(cand)
        if args.dry_run:
            print(f"(dry-run) would flag {cand['subject']} [{cand['reason']}] "
                  f"age={cand['age_h']:.1f}h machine={cand['machine']}")
            print(f"(dry-run) tail: {cand['tail'][-200:]!r}")
            filed += 1
            continue
        cmd = [sys.executable, str(wake_cli()), "flag",
               "--subject", cand["subject"], "--prompt", prompt,
               "--kind", "resume", "--source", SOURCE, "--priority", "normal",
               "--cooldown-seconds", "604800"]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except Exception as exc:                                 # noqa: BLE001
            print(f"session-sweep: flag failed ({exc})", file=sys.stderr)
            continue
        out = (p.stdout or "").strip().splitlines()
        verdict = out[-1] if out else "(no output)"
        print(f"flagged {cand['subject']} [{cand['reason']}] -> {verdict}")
        if verdict.startswith("error:"):
            print(f"session-sweep: the STORE said error, not quiet: {verdict}", file=sys.stderr)
            continue
        # ONLY A REAL FILING SPENDS THE DAILY BUDGET. Measured 2026-10-18: the state file said
        # `filed: 3` while the wake table held **2** rows with source=session-sweep, because
        # `suppressed:cooldown` was counted as a filing — the 02:07 log shows
        # `flagged session-sweep:90c1285d… -> suppressed:cooldown` on the same tick. A suppression
        # costs nothing and produces no row, so counting it silently shortened the day's quota for
        # real candidates. The cap must be spent by filings only.
        if verdict.startswith("filed"):
            filed += 1
        else:
            print(f"session-sweep: not a filing ({verdict}) - the daily budget is unchanged",
                  file=sys.stderr)

    if not args.dry_run and filed:
        st["filed"] = int(st.get("filed") or 0) + filed
        save_state(st)
    if args.json:
        print(json.dumps({"filed": filed, "candidates": len(cands), "budget": budget}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
