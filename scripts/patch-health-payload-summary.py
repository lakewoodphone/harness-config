#!/usr/bin/env python3
"""A health check must return state, not 1,780 run records.

MEASURED on secratary 2026-09-15, and this is pain P7's specific trap:

  GET /autopilot/health     345,072 bytes
    health.subsystems       326,259 bytes
      recent_runs           295,615 bytes across 1,780 stored entries
      (the same subsystems WITHOUT recent_runs: 12,143 bytes)
    biggest offenders: boa_sync 32,166 bytes (50 runs), ebay_sync 27,275 (46),
                       amazon_sync 27,109 (45)

`ps_health` aggregates that endpoint, so ONE health call handed a model ~385 KB -- roughly
100k tokens, an entire context window. My note from an earlier session said ps_health returns
90 KB; it was four times worse than that by now, because each subsystem keeps a rolling 50 runs
and `_record_subsystem` appends on every record.

TWO FIXES, read path and write path:

  READ  `health()` now returns each subsystem's SUMMARY plus the single most recent run, and
        reports `recent_runs_total` so the history is visibly present-but-not-included rather
        than silently missing. The full history is still reachable by passing a larger value.
  WRITE the stored rolling log is capped at 10 per subsystem instead of 50. That is the same
        295 KB inside `data/autopilot_state.json` (386 KB), which `_save_state()` rewrites in
        full on every subsystem record -- so the cap is also a write-amplification fix.

Neither change loses information that is only available here: `scripts/sync-health-audit.py`
reads its own `recent_runs` from a `reconciliation_runs` table, not from this payload, and the
other callers (autopilot_contract, main.py) read the summary fields.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

OLD_HEALTH = '''    def health(self) -> dict[str, Any]:
        """Return detailed health of all subsystems."""
        with self._lock:
            return {
                "consecutive_failures": (self._consecutive_failures),
                "crash_count": self._crash_count,
                "last_crash_at": self._last_crash_at,
                "backoff_multiplier": self._backoff_multiplier,
                "subsystems": dict(self._subsystem_health),
            }'''

NEW_HEALTH = '''    # A health payload carries the STATE of each subsystem, not its history. Measured
    # 2026-09-15: /autopilot/health returned 345 KB, of which 295 KB was 1,780 stored run
    # records -- one ps_health call cost a model ~100k tokens. Pass recent_runs=N for the
    # history; the default is the summary plus the newest run.
    _HEALTH_RECENT_RUNS = 1
    # The stored rolling log per subsystem. Was 50, which put 295 KB into a state blob that
    # _save_state() rewrites in full on every record.
    _SUBSYSTEM_RECENT_RUNS = 10

    def health(self, recent_runs: int | None = None) -> dict[str, Any]:
        """Return the state of every subsystem, with a tail of its run history.

        Returns, per subsystem, the summary fields (`last_status`, `consecutive_failures`,
        `last_ran_at`, `last_error`, the counters) plus at most `recent_runs` of the newest
        run records -- 1 by default -- and `recent_runs_total` so a caller can see that more
        history exists without being handed all of it.
        """
        limit = (
            self._HEALTH_RECENT_RUNS if recent_runs is None else max(0, int(recent_runs))
        )
        with self._lock:
            subsystems: dict[str, Any] = {}
            for name, entry in self._subsystem_health.items():
                if not isinstance(entry, dict):
                    subsystems[name] = entry
                    continue
                view = dict(entry)
                runs = entry.get("recent_runs")
                if isinstance(runs, list):
                    view["recent_runs"] = runs[-limit:] if limit else []
                    if runs:
                        view["recent_runs_total"] = len(runs)
                subsystems[name] = view
            return {
                "consecutive_failures": (self._consecutive_failures),
                "crash_count": self._crash_count,
                "last_crash_at": self._last_crash_at,
                "backoff_multiplier": self._backoff_multiplier,
                "subsystems": subsystems,
            }'''

OLD_CAP = '''        if len(runs) > 50:
            runs = runs[-50:]'''
NEW_CAP = '''        if len(runs) > self._SUBSYSTEM_RECENT_RUNS:
            runs = runs[-self._SUBSYSTEM_RECENT_RUNS :]'''

TEST = '''"""A health payload must carry state, not the whole run history.

Measured on secratary 2026-09-15: GET /autopilot/health returned 345,072 bytes, of which
295,615 was 1,780 stored run records across 37 subsystems. ps_health aggregates it, so one
health call handed a model ~385 KB -- about 100k tokens, an entire context window.
"""

import json
import threading

from app.autopilot import AutopilotController as AC


def _controller(subsystems):
    c = AC.__new__(AC)
    c._lock = threading.RLock()
    c._consecutive_failures = 0
    c._crash_count = 0
    c._last_crash_at = None
    c._backoff_multiplier = 1
    c._subsystem_health = subsystems
    return c


def _entry(n_runs):
    return {
        "successes": 5,
        "failures": 1,
        "last_status": "ok",
        "last_error": None,
        "last_ran_at": "2026-09-15T00:00:00+00:00",
        "consecutive_failures": 0,
        "consecutive_empty_ticks": 0,
        "last_detail": "fine",
        "recent_runs": [
            {"ran_at": f"2026-09-15T00:00:{i:02d}+00:00", "success": True, "detail": "x" * 120}
            for i in range(n_runs)
        ],
    }


def test_the_default_payload_is_a_summary_not_a_history():
    c = _controller({"boa_sync": _entry(50), "ebay_sync": _entry(46)})
    h = c.health()
    assert len(json.dumps(h)) < 4000, len(json.dumps(h))
    for name, e in h["subsystems"].items():
        assert len(e["recent_runs"]) == 1, (name, len(e["recent_runs"]))


def test_the_history_is_visibly_present_not_silently_missing():
    """A count, so nothing looks like 'this subsystem never ran'."""
    c = _controller({"boa_sync": _entry(50)})
    e = c.health()["subsystems"]["boa_sync"]
    assert e["recent_runs_total"] == 50
    assert len(e["recent_runs"]) == 1


def test_the_summary_fields_survive():
    c = _controller({"boa_sync": _entry(3)})
    e = c.health()["subsystems"]["boa_sync"]
    assert e["last_status"] == "ok"
    assert e["consecutive_failures"] == 0
    assert e["last_ran_at"]


def test_a_caller_can_ask_for_the_history():
    c = _controller({"boa_sync": _entry(50)})
    e = c.health(recent_runs=50)["subsystems"]["boa_sync"]
    assert len(e["recent_runs"]) == 50


def test_a_subsystem_with_no_runs_is_still_reported():
    """An empty history must not remove the subsystem from the payload."""
    c = _controller({"quiet": {**_entry(0), "last_status": "unknown"}})
    h = c.health()
    assert "quiet" in h["subsystems"]
    assert h["subsystems"]["quiet"]["recent_runs"] == []


def test_the_stored_rolling_log_is_capped():
    c = _controller({})
    for i in range(40):
        c._record_subsystem("x", success=True, detail=f"run {i}")
    runs = c._subsystem_health["x"]["recent_runs"]
    assert len(runs) == AC._SUBSYSTEM_RECENT_RUNS
    assert runs[-1]["detail"] == "run 39"      # newest kept


def test_the_caps_are_sane():
    assert 0 <= AC._HEALTH_RECENT_RUNS <= 3
    assert 5 <= AC._SUBSYSTEM_RECENT_RUNS <= 20
'''


def main() -> int:
    ap = pathlib.Path("app/autopilot.py")
    src = ap.read_text(encoding="utf-8")

    assert src.count(OLD_HEALTH) == 1, f"health: {src.count(OLD_HEALTH)}"
    assert src.count(OLD_CAP) == 1, f"cap: {src.count(OLD_CAP)}"
    assert "_HEALTH_RECENT_RUNS" not in src

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak15"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    src = src.replace(OLD_HEALTH, NEW_HEALTH)
    src = src.replace(OLD_CAP, NEW_CAP)
    ap.write_text(src, encoding="utf-8")
    print("patched app/autopilot.py")

    pathlib.Path("tests/test_health_payload_is_a_summary.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_health_payload_is_a_summary.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
