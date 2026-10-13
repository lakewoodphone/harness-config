#!/usr/bin/env python3
"""weekly-evolution-audit -- what actually CHANGED on this estate in the last 7 days.

WHY THIS EXISTS
---------------
The owner asked (2026-10-13): "once a week or whatever ... You should do a full
audit in figure out, how are you wildly evolving this week." A promise is not a
ritual and a prose document is not a measurement. This script is the MEASUREMENT
half: it produces a machine-readable record of the window and a diff against the
previous run, so "we evolved" becomes a number with a source and a freshness.

THE ONE RULE
------------
Every number carries the exact command that produced it and how fresh that
source is. A file's mtime is not content freshness. If a source cannot be read,
the metric is `COULD NOT ASK` with the reason and the probe list -- never 0,
never a guess. A blank is never a NO.

Output
------
    <out>/run-<UTC-stamp>.json   one record per run
    <out>/latest.json            a copy of the newest record
    stdout                       a one-screen human digest

Usage
-----
    python3 scripts/self-audit/weekly-evolution-audit.py --repo <repo> \\
        [--out DIR] [--window-days 7] [--json-only] [--quiet]

Exit 0 when the record was produced (even with COULD NOT ASK cells).
Exit 1 only when nothing could be written at all.
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

HOME = Path.home()
NOW = lambda: datetime.now(timezone.utc)  # noqa: E731

# Candidate locations, in order, for the stores this estate already owns.
WAKE_CLI_DEFAULT = Path(os.environ.get("WAKE_PY") or (HOME / "bin" / "wake.py"))
WAKE_DB_DEFAULT = Path(os.environ.get("SMS_INBOX_DB") or (HOME / ".sms-inbox" / "inbox.db"))
WORK_DB_DEFAULT = Path(os.environ.get("WORK_DB") or (HOME / "work" / "work.db"))
WORK_CLI_DEFAULT = Path(os.environ.get("WORK_CLI") or (HOME / "bin" / "work.py"))
SOURCES_DIR_DEFAULT = Path(os.environ.get("WAKE_SOURCES_DIR") or (HOME / "bin" / "sources"))
APP_DB_CANDIDATES = [
    os.environ.get("OWNER_QUEUE_DB"), os.environ.get("SMS_INBOX_APP_DB"),
    str(HOME / "personal-secretary-mvp" / "data" / "secretary.db"),
    "/root/authority.db", "/opt/company/data/authority.db",
    "/opt/company/data/secretary.db",
]


# --------------------------------------------------------------------------- #
# small helpers -- every one of them reports failure, never invents a value
# --------------------------------------------------------------------------- #
def run_cmd(cmd: list[str], timeout: int = 60) -> dict:
    """Run a command; return {rc, out, err, cmd}. Never raises."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"rc": proc.returncode, "out": proc.stdout or "",
                "err": proc.stderr or "", "cmd": " ".join(cmd)}
    except FileNotFoundError as exc:
        return {"rc": 127, "out": "", "err": f"not found: {exc}", "cmd": " ".join(cmd)}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "out": "", "err": f"timeout after {timeout}s", "cmd": " ".join(cmd)}
    except Exception as exc:  # noqa: BLE001
        return {"rc": 125, "out": "", "err": f"{type(exc).__name__}: {exc}", "cmd": " ".join(cmd)}


def ro_db(path: Path) -> sqlite3.Connection | None:
    """Read-only connection, or None. A sensor must not be able to write."""
    try:
        if not Path(path).is_file():
            return None
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    except sqlite3.Error:
        return []


def tables(conn: sqlite3.Connection) -> list[str]:
    try:
        return [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
    except sqlite3.Error:
        return []


def pick(cols: list[str], *cands: str) -> str | None:
    for c in cands:
        if c in cols:
            return c
    return None


def metric(name, value, source, cmd, method, *, unit="count",
           freshness="live", as_of=None, status="measured", reason=None,
           extra=None) -> dict:
    """One measured number with its provenance. The whole point of this file."""
    return {
        "name": name, "value": value, "unit": unit,
        "source": source, "command": cmd, "method": method,
        "freshness": {"kind": freshness,
                      "as_of": as_of or NOW().strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "age_seconds": 0 if freshness == "live" else None},
        "status": status, "reason": reason, "extra": extra or {},
    }


def cannot_ask(name, source, probes, reason, *, cmd="", method="") -> dict:
    return metric(name, None, source, cmd or "; ".join(probes), method or "probe list",
                  status="COULD NOT ASK", reason=reason, freshness="unreadable",
                  extra={"probes": probes})


# --------------------------------------------------------------------------- #
# collectors
# --------------------------------------------------------------------------- #
def collect_journal(repo: Path, since: datetime) -> dict:
    """Journal entries added by kind, via journal.py ONLY (never by reading files)."""
    j = repo / "journal" / "tools" / "journal.py"
    if not j.is_file():
        return {"by_kind": cannot_ask("journal_entries_by_kind", str(j), [str(j)],
                                      "no journal.py at that path")}
    since_s = since.strftime("%Y-%m-%d")
    res = run_cmd([sys.executable, str(j), "list", "--since", since_s, "--json"], 120)
    if res["rc"] != 0 or not res["out"].strip():
        return {"by_kind": cannot_ask("journal_entries_by_kind",
                                      "journal.py list --since %s --json" % since_s,
                                      [res["cmd"]], f"rc={res['rc']} {res['err'][:160]}")}
    try:
        entries = json.loads(res["out"]).get("entries", [])
    except ValueError as exc:
        return {"by_kind": cannot_ask("journal_entries_by_kind", res["cmd"], [res["cmd"]],
                                      f"unparseable JSON: {exc}")}
    by_kind: dict[str, int] = {}
    for e in entries:
        by_kind[e.get("kind", "?")] = by_kind.get(e.get("kind", "?"), 0) + 1
    m = metric("journal_entries_by_kind", len(entries),
               "journal.py list --since %s --json" % since_s, res["cmd"],
               "entries[] grouped by .kind; the tool is the only door to the tree")
    m["extra"] = {"by_kind": by_kind}
    # open pain -- the estate's own open-pain count
    res2 = run_cmd([sys.executable, str(j), "list", "--kind", "pain", "--status", "open",
                    "--json"], 120)
    if res2["rc"] == 0 and res2["out"].strip():
        try:
            pain = len(json.loads(res2["out"]).get("entries", []))
            pain_m = metric("open_pain_count", pain,
                            "journal.py list --kind pain --status open --json", res2["cmd"],
                            "count of open pain entries in the index")
        except ValueError:
            pain_m = cannot_ask("open_pain_count", res2["cmd"], [res2["cmd"]], "unparseable JSON")
    else:
        pain_m = cannot_ask("open_pain_count", res2["cmd"], [res2["cmd"]],
                            f"rc={res2['rc']} {res2['err'][:160]}")
    return {"by_kind": m, "open_pain": pain_m}


def collect_wake(since: datetime) -> dict:
    """Wake releases in the window, from the wake store, READ-ONLY."""
    db = WAKE_DB_DEFAULT
    conn = ro_db(db)
    if conn is None:
        return {"releases": cannot_ask("wake_releases", str(db), [f"read-only open {db}"],
                                       "wake store not readable"),
                "stats": cannot_ask("wake_stats", str(WAKE_CLI_DEFAULT),
                                    [str(WAKE_CLI_DEFAULT)], "wake CLI/store absent")}
    out: dict = {}
    if "wake" in tables(conn):
        cols = columns(conn, "wake")
        status_col = pick(cols, "status", "state")
        ts_col = pick(cols, "released_at", "claimed_at", "updated_at", "created_at")
        by_status: dict[str, int] = {}
        for row in conn.execute(f"SELECT {status_col}, COUNT(*) c FROM wake GROUP BY 1"):
            by_status[str(row[0])] = row[1]
        released = None
        if ts_col:
            try:
                released = conn.execute(
                    f"SELECT COUNT(*) FROM wake WHERE {ts_col} >= ?",
                    (since.strftime("%Y-%m-%dT%H:%M:%S"),)).fetchone()[0]
            except sqlite3.Error:
                released = None
        out["releases"] = metric(
            "wake_releases", released if released is not None else by_status,
            f"read-only SQL on {db} table wake", f"SELECT COUNT(*) FROM wake WHERE {ts_col} >= since",
            f"columns {cols}; timestamp column={ts_col}",
            extra={"by_status": by_status, "timestamp_column": ts_col})
    notes = []
    if WORK_CLI_DEFAULT.is_file():
        s = run_cmd([sys.executable, str(WAKE_CLI_DEFAULT), "stats"], 90)
        if s["rc"] == 0:
            notes = [ln for ln in s["out"].splitlines()
                     if re.search(r"spend|released today|rows:", ln)]
            out["stats"] = metric("wake_stats", len(notes), str(WAKE_CLI_DEFAULT),
                                  s["cmd"], "first lines of `wake.py stats`",
                                  extra={"lines": notes})
        else:
            out["stats"] = cannot_ask("wake_stats", str(WAKE_CLI_DEFAULT), [s["cmd"]],
                                      f"rc={s['rc']} {s['err'][:120]}")
    else:
        out["stats"] = cannot_ask("wake_stats", str(WAKE_CLI_DEFAULT), [str(WAKE_CLI_DEFAULT)],
                                  "wake CLI not found")
    conn.close()
    return out


def collect_ledger(since: datetime) -> dict:
    """Ledger items closed WITH PROOF vs left open, READ-ONLY.

    Measured schema on secratary-cloud 2026-10-13: `work_item(..., state, ...)` and
    `attempt(..., item, proof, ...)` -- the proof of closure lives on the ATTEMPT, not
    on the item, so "closed with proof" is an EXISTS over attempt, and a done item
    with no attempt proof is a closure nobody can check.
    """
    db = WORK_DB_DEFAULT
    conn = ro_db(db)
    if conn is None:
        return {"closed_with_proof": cannot_ask("ledger_closed_with_proof", str(db),
                                                [f"read-only open {db}"],
                                                "work ledger not readable"),
                "left_open": cannot_ask("ledger_left_open", str(db), [f"read-only open {db}"],
                                        "work ledger not readable")}
    tbls = tables(conn)
    item_table = "work_item" if "work_item" in tbls else None
    if item_table is None:
        for t in tbls:
            if pick(columns(conn, t), "state", "status") and t != "sqlite_sequence":
                item_table = t
                break
    if item_table is None:
        conn.close()
        return {"closed_with_proof": cannot_ask("ledger_closed_with_proof", str(db),
                                                [f"tables: {tbls}"], "no item table with state/status"),
                "left_open": cannot_ask("ledger_left_open", str(db), [], "no item table with state/status")}
    cols = columns(conn, item_table)
    state_col = pick(cols, "state", "status")
    by_state = {str(r[0]): r[1] for r in conn.execute(
        f"SELECT {state_col}, COUNT(*) FROM {item_table} GROUP BY 1")}
    done_states = ("done", "closed", "complete", "completed")
    open_n = sum(v for k, v in by_state.items() if k not in done_states + ("cancelled", "expired"))
    with_proof = None
    proof_col = None
    if "attempt" in tbls and "proof" in columns(conn, "attempt"):
        proof_col = "attempt.proof"
        try:
            with_proof = conn.execute(
                f"SELECT COUNT(*) FROM {item_table} w WHERE w.{state_col} IN "
                f"('done','closed','complete','completed') AND EXISTS (SELECT 1 FROM attempt a "
                f"WHERE a.item = w.id AND a.proof IS NOT NULL AND TRIM(a.proof) <> '')"
            ).fetchone()[0]
        except sqlite3.Error:
            with_proof = None
    conn.close()
    return {
        "closed_with_proof": metric(
            "ledger_closed_with_proof", with_proof, f"read-only SQL on {db} ({item_table} x attempt)",
            f"COUNT {item_table} WHERE {state_col} done AND EXISTS attempt.proof non-empty",
            f"proof column={proof_col}; proof lives on the attempt row",
            extra={"by_state": by_state}),
        "left_open": metric("ledger_left_open", open_n, f"read-only SQL on {db} table {item_table}",
                            f"COUNT(*) WHERE {state_col} NOT IN done/cancelled/expired",
                            f"state column={state_col}", extra={"by_state": by_state}),
    }


def collect_queue(since: datetime) -> dict:
    """Owner decision queue's filed-vs-resolved counts.

    Several databases on this estate carry an `owner_decision_queue`. The authority
    one (AGENTS.md §3) is `/root/authority.db`; the mvp one can be an older copy. So
    we read every candidate and report from the one with the MOST rows -- a queue
    that is empty in one copy and populated in another must not read as zero.
    """
    probes = [p for p in APP_DB_CANDIDATES if p]
    best = None
    for cand in probes:
        conn = ro_db(Path(cand))
        if conn is None:
            continue
        if "owner_decision_queue" not in tables(conn):
            conn.close()
            continue
        try:
            n = conn.execute("SELECT COUNT(*) FROM owner_decision_queue").fetchone()[0]
        except sqlite3.Error:
            conn.close()
            continue
        if best is None or n > best[1]:
            if best is not None:
                best[0].close()
            best = (conn, n, cand)
        else:
            conn.close()
    if best is None:
        return {"filed": cannot_ask("queue_filed", "owner_decision_queue", probes,
                                    "no readable app DB with owner_decision_queue"),
                "resolved": cannot_ask("queue_resolved", "owner_decision_queue", probes,
                                       "no readable app DB with owner_decision_queue"),
                "pending": cannot_ask("queue_pending", "owner_decision_queue", probes,
                                      "no readable app DB with owner_decision_queue")}
    conn, total, cand = best
    cols = columns(conn, "owner_decision_queue")
    asked = pick(cols, "asked_at", "created_at", "filed_at")
    resolved = pick(cols, "resolved_at", "closed_at")
    status = pick(cols, "status", "state")
    filed_n = resolved_n = None
    if asked:
        try:
            filed_n = conn.execute(
                f"SELECT COUNT(*) FROM owner_decision_queue WHERE {asked} >= ?",
                (since.strftime("%Y-%m-%dT%H:%M:%S"),)).fetchone()[0]
        except sqlite3.Error:
            filed_n = None
    if resolved:
        try:
            resolved_n = conn.execute(
                f"SELECT COUNT(*) FROM owner_decision_queue WHERE {resolved} >= ?",
                (since.strftime("%Y-%m-%dT%H:%M:%S"),)).fetchone()[0]
        except sqlite3.Error:
            resolved_n = None
    by_status = {}
    if status:
        by_status = {str(r[0]): r[1] for r in conn.execute(
            f"SELECT {status}, COUNT(*) FROM owner_decision_queue GROUP BY 1")}
    conn.close()
    pending = sum(v for k, v in by_status.items() if k in ("pending", "open", "filed", "new"))
    return {
        "filed": metric("queue_filed", filed_n, f"read-only SQL {cand} owner_decision_queue",
                        f"COUNT(*) WHERE {asked} >= since", f"columns {cols}; rows={total}",
                        extra={"by_status": by_status}),
        "resolved": metric("queue_resolved", resolved_n,
                           f"read-only SQL {cand} owner_decision_queue",
                           f"COUNT(*) WHERE {resolved} >= since", f"columns {cols}; rows={total}"),
        "pending": metric("queue_pending", pending,
                          f"read-only SQL {cand} owner_decision_queue",
                          f"COUNT(*) WHERE {status} IN pending/open/filed/new",
                          "the owner's live queue depth", extra={"by_status": by_status}),
    }
    return {"filed": cannot_ask("queue_filed", "owner_decision_queue", probes,
                                "no readable app DB with owner_decision_queue"),
            "resolved": cannot_ask("queue_resolved", "owner_decision_queue", probes,
                                   "no readable app DB with owner_decision_queue")}


def collect_commits(repo: Path, since: datetime) -> dict:
    rng = f"--since={since.strftime('%Y-%m-%dT%H:%M:%S')}"
    n = run_cmd(["git", "-C", str(repo), "log", rng, "--pretty=%H"], 60)
    if n["rc"] != 0:
        return cannot_ask("commits_landed", f"git -C {repo} log", [n["cmd"]],
                          f"rc={n['rc']} {n['err'][:160]}")
    shas = [s for s in n["out"].split() if s]
    files = run_cmd(["git", "-C", str(repo), "log", rng, "--name-only", "--pretty=format:"], 90)
    changed = len({f for f in files["out"].splitlines() if f.strip()})
    head = run_cmd(["git", "-C", str(repo), "rev-parse", "HEAD"], 20)
    head_t = run_cmd(["git", "-C", str(repo), "log", "-1", "--pretty=%cI"], 20)
    m = metric("commits_landed", len(shas), "harness-config git history", n["cmd"],
               "git log --since over the window", freshness="git",
               as_of=(head_t["out"].strip() or None),
               extra={"head": head["out"].strip(), "distinct_files_touched": changed})
    return m


def collect_capabilities(repo: Path, since: datetime) -> dict:
    """New capabilities: sources, scripts, docs/skills, routes, services."""
    rng = f"--since={since.strftime('%Y-%m-%dT%H:%M:%S')}"
    added = run_cmd(["git", "-C", str(repo), "log", rng, "--diff-filter=A",
                     "--name-only", "--pretty=format:"], 90)
    files = [f for f in added["out"].splitlines() if f.strip()]
    buckets = {
        "sources_added": [f for f in files if "/sources/" in f and f.endswith(".py")],
        "scripts_added": [f for f in files if f.startswith("scripts/")],
        "skills_added": [f for f in files if "skill" in f.lower()],
        "routes_added": [f for f in files if "route" in f.lower()],
        "docs_added": [f for f in files if f.startswith("docs/")],
    }
    out = {}
    for k, v in buckets.items():
        out[k] = metric(k, len(v), "git log --diff-filter=A (additions only)",
                        added["cmd"], "new paths matching the bucket over the window",
                        freshness="git", extra={"sample": v[:8]})
    sources_dir = SOURCES_DIR_DEFAULT
    live = sorted(p.name for p in sources_dir.glob("*.py")) if sources_dir.is_dir() else None
    if live is None:
        out["sources_registered"] = cannot_ask("sources_registered", str(sources_dir),
                                               [f"ls {sources_dir}"], "sources dir not readable")
    else:
        out["sources_registered"] = metric("sources_registered", len(live), str(sources_dir),
                                           f"ls {sources_dir}/*.py",
                                           "live source files on the authority",
                                           extra={"files": live})
    # services/timers -- live systemd counts
    svc = run_cmd(["systemctl", "list-units", "--type=service", "--state=running",
                   "--no-legend", "--no-pager"], 30)
    tmr = run_cmd(["systemctl", "list-timers", "--no-legend", "--no-pager"], 30)
    if svc["rc"] == 0:
        out["services_running"] = metric("services_running", len(
            [ln for ln in svc["out"].splitlines() if ln.strip()]), "systemd", svc["cmd"],
            "list-units --type=service --state=running")
    else:
        out["services_running"] = cannot_ask("services_running", "systemd", [svc["cmd"]],
                                             f"rc={svc['rc']} {svc['err'][:120]}")
    if tmr["rc"] == 0:
        out["timers_registered"] = metric("timers_registered", len(
            [ln for ln in tmr["out"].splitlines() if ln.strip()]), "systemd", tmr["cmd"],
            "list-timers")
    else:
        out["timers_registered"] = cannot_ask("timers_registered", "systemd", [tmr["cmd"]],
                                              f"rc={tmr['rc']} {tmr['err'][:120]}")
    return out


def collect_sessions_agents() -> dict:
    """Sessions/agents run. Probed, never guessed."""
    probes = [
        "ls -d ~/.dsh ~/.dsh-sessions",
        "python3 scripts/dsh-sessions.py --help",
        "ls ~/.sms-inbox/wake-instances",
        "docker ps --format {{.Names}}",
    ]
    found = {}
    d = HOME / ".dsh"
    if d.is_dir():
        found["dsh_dir_entries"] = len(list(d.iterdir()))
    wi = HOME / ".sms-inbox" / "wake-instances"
    if wi.is_dir():
        found["wake_instances"] = len(list(wi.rglob("*")))
    if not found:
        return {"sessions_marker": cannot_ask(
            "sessions_agents_run", "dsh session store", probes,
            "none of the probed session stores exist on this host")}
    return {"sessions_marker": metric(
        "sessions_agents_run", sum(found.values()), "local dsh/session stores",
        "; ".join(probes), "counts of session artifacts present", extra=found)}


def collect_spend() -> dict:
    """Spend for the week against its ceiling. Unmeasured is COULD NOT ASK, not 0."""
    conn = ro_db(WAKE_DB_DEFAULT)
    ceiling = None
    if conn is not None and "wake_budget" in tables(conn):
        try:
            rows = conn.execute("SELECT * FROM wake_budget").fetchall()
            ceiling = len(rows)
            conn.close()
        except sqlite3.Error:
            conn.close()
    cost_log = HOME / ".sms-inbox" / "wake-cost.jsonl"
    if cost_log.is_file():
        lines = [ln for ln in cost_log.read_text(errors="replace").splitlines() if ln.strip()]
        return {"spend": metric("spend_records", len(lines), str(cost_log), f"wc -l {cost_log}",
                                "cost ledger rows", freshness="file",
                                as_of=datetime.fromtimestamp(cost_log.stat().st_mtime,
                                                             timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))}
    return {"spend": cannot_ask("spend_measured", str(cost_log),
                                [f"read {cost_log}", "wake.py stats spend line"],
                                "no wake-cost.jsonl: the store itself reports spend UNMEASURED, "
                                "so the USD cap cannot fire",
                                cmd="wake.py stats", method="spend line of stats")}


# --------------------------------------------------------------------------- #
# assembly / diff / digest
# --------------------------------------------------------------------------- #
def load_previous(out_dir: Path, this_path: Path) -> dict | None:
    runs = sorted([p for p in out_dir.glob("run-*.json") if p != this_path],
                  key=lambda p: p.stat().st_mtime)
    if not runs:
        return None
    try:
        return json.loads(runs[-1].read_text())
    except (OSError, ValueError):
        return None


def numeric_metrics(record: dict) -> dict:
    flat: dict[str, object] = {}
    def walk(prefix, obj):
        if isinstance(obj, dict):
            if obj.get("status") in ("measured",) and "value" in obj and isinstance(obj["value"], (int, float)):
                flat[prefix] = obj["value"]
            else:
                for k, v in obj.items():
                    walk(f"{prefix}.{k}" if prefix else k, v)
    walk("", {k: v for k, v in record.items() if k not in ("diff_vs_previous",)})
    return flat


def build_diff(previous: dict | None, current_flat: dict) -> dict:
    if previous is None:
        return {"previous_run": None, "deltas": {}, "changed": None,
                "note": "no previous run: this is the baseline"}
    prev_flat = numeric_metrics(previous)
    deltas = {}
    for k, v in current_flat.items():
        if k in prev_flat and isinstance(prev_flat[k], (int, float)):
            d = v - prev_flat[k]
            if d:
                deltas[k] = {"previous": prev_flat[k], "current": v, "delta": d}
    return {"previous_run": previous.get("run_id"), "deltas": deltas,
            "changed": bool(deltas)}


def digest(record: dict) -> str:
    lines = [
        f"SELF-AUDIT {record['run_id']}  host={record['host']}  window={record['window']['since'][:10]}..{record['window']['until'][:10]}",
        f"  repo={record['repo']['path']} head={record['repo']['head'][:12]}",
    ]
    for section in ("journal", "wake", "ledger", "queue", "capabilities", "sessions", "spend"):
        block = record.get(section) or {}
        if not isinstance(block, dict):
            continue
        for key, m in block.items():
            if not isinstance(m, dict) or "status" not in m:
                continue
            if m["status"] == "measured":
                extra = ""
                # The by-kind breakdown is the point of this line: "50 entries" is not
                # "what KIND moved". Keyed off the metric's own extra, not the dict key,
                # because the dict key is the short name while the metric name is long.
                by_kind = m.get("extra", {}).get("by_kind")
                if by_kind:
                    extra = " " + json.dumps(by_kind, sort_keys=True)
                lines.append(f"  {key:28s} {m['value']!s:>8s}  [{m['freshness']['kind']}]  {m['source'][:52]}{extra}")
            else:
                lines.append(f"  {key:28s} {'COULD NOT ASK':>8s}  reason={m.get('reason','')[:60]}")
    od = record.get("diff_vs_previous", {})
    if od.get("previous_run") is None:
        lines.append("  DIFF vs previous: baseline (no previous run)")
    else:
        lines.append(f"  DIFF vs {od['previous_run']}: changed={od['changed']} "
                     f"{json.dumps({k: v['delta'] for k, v in od['deltas'].items()})[:120]}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="weekly evolution audit measurement")
    ap.add_argument("--repo", default=os.environ.get("HARNESS_REPO") or str(Path.cwd()))
    ap.add_argument("--out", default=os.environ.get("SELF_AUDIT_OUT")
                    or str(HOME / ".self-audit" / "runs"))
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    until = NOW()
    since = until - timedelta(days=args.window_days)

    record = {
        "schema": "self-audit/1",
        "run_id": until.strftime("run-%Y%m%dT%H%M%SZ"),
        "generated_at": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "?"),
        "window": {"days": args.window_days, "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "until": until.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "repo": {}, "journal": {}, "wake": {}, "ledger": {}, "queue": {},
        "commits": {}, "capabilities": {}, "sessions": {}, "spend": {},
    }
    head = run_cmd(["git", "-C", str(repo), "rev-parse", "HEAD"], 20)
    br = run_cmd(["git", "-C", str(repo), "branch", "--show-current"], 20)
    record["repo"] = {"path": str(repo), "head": head["out"].strip(),
                      "branch": br["out"].strip(), "exists": repo.is_dir()}

    record["journal"] = collect_journal(repo, since)
    record["wake"] = collect_wake(since)
    record["ledger"] = collect_ledger(since)
    record["queue"] = collect_queue(since)
    record["commits"] = {"commits_landed": collect_commits(repo, since)}
    record["capabilities"] = collect_capabilities(repo, since)
    record["sessions"] = collect_sessions_agents()
    record["spend"] = collect_spend()

    path = out_dir / f"{record['run_id']}.json"
    record["diff_vs_previous"] = build_diff(load_previous(out_dir, path), numeric_metrics(record))
    try:
        path.write_text(json.dumps(record, indent=1, sort_keys=True))
        (out_dir / "latest.json").write_text(json.dumps(record, indent=1, sort_keys=True))
    except OSError as exc:
        print(f"cannot write {path}: {exc}", file=sys.stderr)
        return 1
    if args.json_only:
        print(json.dumps(record, sort_keys=True))
    elif not args.quiet:
        print(digest(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
