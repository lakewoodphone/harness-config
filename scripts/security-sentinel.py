#!/usr/bin/env python3
"""security-sentinel — turn recorded events into episodes and decisions.

This is the first piece of the mind, and it is deliberately the *deterministic* piece. It runs in SHADOW:
it reads `security_event`, groups what it finds into episodes, applies the reflex rules, and writes
`security_decision` rows saying what it would have concluded. It writes NO `security_action` row and
calls no Home Assistant service. Nothing here can sound a siren, page a phone, or unlock anything.

Why shadow first: the building's arming model is currently broken (see 05-LIVE-FINDINGS L1 — presence
credit clears the alarm), so a rule that trusted `everyone_away` would be reasoning from a lie. Shadow mode
lets the rules be measured against reality before anything acts on them, and it is what
50-BUILD-PLAN.md stage 2 requires before the reflex changes.

Rules (v0 — the two that need no context):
  R_DOOR     a perimeter door contact going `on` opens an episode
  R_CRED     a credential used within CREDENTIAL_WINDOW_S of the door edge explains it
  R_CRED_ONLY a credential with no door (someone badging before opening) is level 0, recorded, no episode
  R_GAP      a recorder gap inside the window makes the episode inconclusive, never benign

A verdict is written PER EPISODE, not per event, and it carries the evidence it used.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone

LOG = logging.getLogger("security-sentinel")

CREDENTIAL_WINDOW_S = 120
EPISODE_SETTLE_S = 125          # door edge + window + 5 s of slack
POLL_S = 2.0
RULE_VERSION = "v0-shadow"
DOORS = {
    "binary_sensor.phoenix_control_room_interior_door_contact": "shop_door",
    "binary_sensor.phoenix_control_room_exterior_door_contact": "apartment_door",
}
CREDENTIAL_ENTITIES = {
    "event.esphome.access_control_keypad_entry",
    "event.esphome.access_control_rfid_entry",
    "event.phoenix.valid_pin",
}
CURSOR_PATH = "/var/lib/security-sentinel/cursor.txt"
HEARTBEAT_PATH = "/var/lib/security-sentinel/heartbeat"
HEARTBEAT_EVERY_S = 60


def beat(path: str = HEARTBEAT_PATH) -> None:
    """Written by the loop itself, so a hung process is visible as a stale heartbeat, not as 'active'."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(utcnow())
        os.replace(tmp, path)
    except OSError:
        pass


# Occupancy, computed here and NOT from Home Assistant's sticky booleans. The rule that produced thirteen
# false alarms was `everyone_away`, a motion-gap template that goes false 0.13 s after a radar sees someone
# and declares the shop empty 9.77 times a day. This replaces it with a 600-second latch over the presence
# sensors plus credentials, and it deliberately never reads a device_tracker: the ghost that disarmed the
# alarm is a tracker, and nothing in this file will ever be persuaded by one.
PRESENCE_ENTITIES = {
    "binary_sensor.zone_control_room_occupied": "control_room",
    "binary_sensor.business_area_occupied": "business_area",
    "binary_sensor.control_room_hub_control_room_presence": "control_room",
    "binary_sensor.zone_control_room_active": "control_room_motion",
}
INSIDE_LATCH_S = 600

# Name -> subject. Only names that appear in the estate's own credential config; anything else is
# "unknown holder", which is a legitimate answer and must never be guessed at.
SUBJECT_BY_NAME = {
    "eliyahu": "owner", "eli": "owner", "boss": "owner", "admin": "owner", "owner": "owner",
    "yocheved": "wife", "chevy": "wife", "wife": "wife",
    "mother": "parent", "father": "parent", "mom": "parent", "dad": "parent", "parent": "parent",
    "guest": "guest", "house": "guest", "house access": "guest",
    "tenant": "tenant",
}


class Occupancy:
    """The building is 'inside' until 600 s pass with no presence, credential or door activity."""

    def __init__(self, last_activity: float | None = None):
        self.last_activity = last_activity

    def mark(self, when: float) -> None:
        if self.last_activity is None or when > self.last_activity:
            self.last_activity = when

    def is_inside(self, now: float) -> bool:
        return self.last_activity is not None and (now - self.last_activity) <= INSIDE_LATCH_S

    def quiet_seconds(self, now: float) -> float | None:
        return None if self.last_activity is None else round(now - self.last_activity, 1)



def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_ts(value: str) -> float:
    """HA sends ISO with an offset; fall back to now rather than crash on one bad row."""
    if not value:
        return time.time()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


class Episode:
    __slots__ = ("door_id", "opened_at", "opened_wall", "events", "credential_at", "gap",
                 "expected_empty_at_open", "quiet_at_open")

    def __init__(self, door_id: str, opened_at: str, opened_wall: float,
                 expected_empty_at_open: bool, quiet_at_open: float | None):
        self.door_id = door_id
        self.opened_at = opened_at
        self.opened_wall = opened_wall
        self.events: list[str] = []
        self.credential_at: str | None = None
        self.gap = False
        # captured BEFORE the door itself counts as activity, or every verdict would see 0 s of quiet
        self.expected_empty_at_open = expected_empty_at_open
        self.quiet_at_open = quiet_at_open


class Sentinel:
    def __init__(self, db_path: str, cursor_path: str = CURSOR_PATH, settle_s: float = EPISODE_SETTLE_S,
                 seed_from_rest: bool = True):
        self.conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.cursor_path = cursor_path
        self.settle_s = settle_s
        self.cursor = self._load_cursor()
        self.open: dict[str, Episode] = {}
        self.decisions = 0
        self._stop = False
        self.occupancy = Occupancy()
        if seed_from_rest:
            self._seed_occupancy()

    def _seed_occupancy(self) -> None:
        """One REST read at startup: the event stream only carries changes, so the present is needed."""
        try:
            import requests  # present in the company venv
            url, token = os.environ.get("HA_URL", ""), os.environ.get("HA_TOKEN", "")
            if not url or not token:
                for line in open("/opt/company/.env", errors="ignore"):
                    if line.startswith("HA_URL=") and not url:
                        url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if line.startswith("HA_TOKEN=") and not token:
                        token = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not url or not token:
                LOG.warning("no HA_URL/HA_TOKEN: occupancy starts unknown")
                return
            h = {"Authorization": "Bearer " + token}
            now = time.time()
            checked = on = 0
            for entity in PRESENCE_ENTITIES:
                checked += 1
                r = requests.get(url.rstrip("/") + "/api/states/" + entity, headers=h, timeout=10)
                if r.status_code == 200 and r.json().get("state") == "on":
                    on += 1
                    self.occupancy.mark(now)
                    LOG.info("seed: %s is ON at startup -> building occupied", entity)
            LOG.info("seed: %d presence entities read, %d on -> occupancy %s",
                     checked, on, "occupied" if on else "empty until something moves")
        except Exception as exc:  # noqa: BLE001 - a failed seed must not stop the sentinel
            LOG.warning("occupancy seed failed (%s): %s", type(exc).__name__, exc)

    # ---- cursor -------------------------------------------------------
    def _load_cursor(self) -> int:
        try:
            with open(self.cursor_path) as fh:
                return int(fh.read().strip() or 0)
        except (OSError, ValueError):
            row = self.conn.execute("SELECT COALESCE(MAX(rowid),0) FROM security_event").fetchone()
            return int(row[0] or 0)  # start at the end: never re-judge history on first boot

    def _save_cursor(self, value: int) -> None:
        os.makedirs(os.path.dirname(self.cursor_path) or ".", exist_ok=True)
        tmp = self.cursor_path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(str(value))
        os.replace(tmp, self.cursor_path)
        self.cursor = value

    # ---- main loop ----------------------------------------------------
    def run(self) -> None:
        LOG.info("sentinel shadow running (rule %s), cursor=%d", RULE_VERSION, self.cursor)
        last_beat = 0.0
        while not self._stop:
            if time.monotonic() - last_beat >= HEARTBEAT_EVERY_S:
                beat()
                last_beat = time.monotonic()
            try:
                self._tick()
            except sqlite3.Error as exc:
                LOG.warning("db error: %s", exc)
            except Exception as exc:  # noqa: BLE001 - never die on one bad row
                LOG.warning("tick error: %s", exc)
            time.sleep(POLL_S)

    def stop(self, *_a) -> None:
        self._stop = True

    def _tick(self) -> None:
        rows = list(self.conn.execute(
            "SELECT rowid, occurred_at, entity_id, old_state, new_state, recorder_gap, raw "
            "FROM security_event WHERE rowid > ? ORDER BY rowid LIMIT 500", (self.cursor,)))
        for rowid, occurred_at, entity_id, old, new, gap, raw in rows:
            self._ingest(rowid, occurred_at, entity_id, old, new,
                         bool(gap) if gap is not None else False, raw)
            self._save_cursor(rowid)
        self._settle()

    def _ingest(self, rowid: int, occurred_at: str, entity_id: str, old, new, gap: bool,
                raw_json: str | None = None) -> None:
        if gap:
            for ep in self.open.values():
                ep.gap = True
            return
        when = parse_ts(occurred_at)
        if entity_id in PRESENCE_ENTITIES and str(new).lower() == "on":
            self.occupancy.mark(when)
            return
        if entity_id in CREDENTIAL_ENTITIES:
            self.occupancy.mark(when)
            self._record_entry(rowid, occurred_at, entity_id, raw_json)
            for ep in self.open.values():
                if ep.credential_at is None:
                    ep.credential_at = occurred_at
            # a credential with no open episode is still worth a row: it proves who can get in
            if not self.open:
                self._decide(None, entity_id, occurred_at,
                             decision="NO_ALARM", avs=0, confidence=0.9,
                             reason="credential used with no door event in window",
                             considered={"credential": occurred_at, "door": None, "mode": "shadow"})
            return
        door_id = DOORS.get(entity_id)
        if door_id and str(new).lower() == "on":
            if door_id in self.open:
                self.open[door_id].events.append(f"reopen@{occurred_at}")
                self.occupancy.mark(when)
                return
            # ask the building "were you empty?" BEFORE this door counts as activity
            ep = Episode(door_id, occurred_at, when,
                         expected_empty_at_open=not self.occupancy.is_inside(when),
                         quiet_at_open=self.occupancy.quiet_seconds(when))
            ep.events.append(f"door_on@{occurred_at}")
            self.open[door_id] = ep
            self.occupancy.mark(when)
            LOG.info("episode opened: %s at %s (expected_empty=%s quiet=%s)",
                     door_id, occurred_at, ep.expected_empty_at_open, ep.quiet_at_open)

    def _record_entry(self, rowid: int, occurred_at: str, entity_id: str, raw_json: str | None) -> None:
        """One row per credential use. The PIN itself is never stored — only the resolved subject.

        This is the only place identity may be granted, and it grants it from a *name the event carried*.
        No tracker, no presence, no inference. If the event does not name a person, the subject is null and
        the row says confidence 0 — which is the honest answer, not a failure.
        """
        marker = f"ev:{rowid}"
        if self.conn.execute("SELECT 1 FROM entry_event WHERE raw_hash = ? LIMIT 1", (marker,)).fetchone():
            return
        data: dict = {}
        try:
            obj = json.loads(raw_json or "{}")
            if isinstance(obj.get("data"), dict):
                data = obj["data"]
        except (ValueError, TypeError):
            data = {}
        def _usable(v):
            v = str(v or "").strip()
            return "" if v in ("[REDACTED]", "None", "unknown") else v
        name = (_usable(data.get("name")) or _usable(data.get("pin_name"))
                or _usable(data.get("user"))).lower()
        subject = SUBJECT_BY_NAME.get(name)
        door = str(data.get("door_name") or "").strip().lower() or "unknown"
        if door in ("strike", "maglock", "interior"):
            door = "shop_door"
        system = ("esphome_keypad" if "keypad" in entity_id
                  else "esphome_rfid" if "rfid" in entity_id else "phoenix")
        self.conn.execute(
            "INSERT INTO entry_event (occurred_at, door_id, system, slot, source, subject_id, "
            "confidence, raw_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (occurred_at, door, system, None, str(data.get("source") or "keypad"),
             subject, 0.9 if subject else 0.0, marker, utcnow()),
        )
        LOG.info("entry: door=%s system=%s subject=%s", door, system, subject or "unknown")

    def _settle(self) -> None:
        now = time.time()
        for door_id in list(self.open):
            ep = self.open[door_id]
            if now - ep.opened_wall < self.settle_s:
                continue
            del self.open[door_id]
            self._verdict(ep)

    def _verdict(self, ep: Episode) -> None:
        expected_empty = ep.expected_empty_at_open
        quiet = ep.quiet_at_open
        considered = {
            "door": ep.door_id, "opened_at": ep.opened_at, "credential_at": ep.credential_at,
            "gap": ep.gap, "events": ep.events[:20], "mode": "shadow",
            "window_s": CREDENTIAL_WINDOW_S,
            "expected_empty": expected_empty, "quiet_s_before_door": quiet,
            "occupancy_source": "presence sensors + credentials, 600 s latch; no device_tracker",
        }
        if ep.gap:
            self._decide(ep, f"R_GAP/{ep.door_id}", ep.opened_at, decision="ESCALATE", avs=2,
                         confidence=0.2, reason="door opened but the record has a gap in the window",
                         considered=considered)
            return
        if ep.credential_at:
            delta = round(parse_ts(ep.credential_at) - ep.opened_wall, 1)
            self._decide(ep, f"R_DOOR+CRED/{ep.door_id}", ep.opened_at, decision="NO_ALARM", avs=0,
                         confidence=0.9,
                         reason=f"{ep.door_id} opened, credential within {delta}s",
                         considered=considered)
            return
        quiet_text = "no activity on record" if quiet is None else f"quiet {quiet}s"
        if expected_empty:
            self._decide(ep, f"R_DOOR/{ep.door_id}", ep.opened_at, decision="ESCALATE", avs=3,
                         confidence=0.6,
                         reason=f"SHADOW: {ep.door_id} opened with no credential within "
                                f"{CREDENTIAL_WINDOW_S}s while the building was expected empty "
                                f"({quiet_text}) — a real deploy would page at level 3",
                         considered=considered)
            return
        self._decide(ep, f"R_DOOR_OCCUPIED/{ep.door_id}", ep.opened_at, decision="ESCALATE", avs=2,
                     confidence=0.3,
                     reason=f"SHADOW: {ep.door_id} opened with no credential, but the building was "
                            f"occupied ({quiet_text} before it) — a note, not a page",
                     considered=considered)

    def _decide(self, ep: Episode | None, rule_id: str, occurred_at: str, *, decision: str, avs: int,
                confidence: float, reason: str, considered: dict) -> None:
        import uuid
        self.conn.execute(
            "INSERT INTO security_decision (id, event_id, episode_id, rule_id, rule_version, decided_by, "
            "considered, decision, avs_level, confidence, reason_one_line, fallback_used, build_sha, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex[:24], None, (ep.door_id + "@" + ep.opened_at) if ep else None,
             rule_id, RULE_VERSION, "fallback:shadow", json.dumps(considered), decision, avs, confidence,
             reason, 1, os.environ.get("SECURITY_BUILD_SHA", "unrecorded"), utcnow()),
        )
        self.decisions += 1
        LOG.info("verdict %s avs=%s %s", decision, avs, reason[:90])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/root/authority.db")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--once", action="store_true", help="one tick then exit (for tests)")
    ap.add_argument("--cursor", default=CURSOR_PATH, help="cursor file (tests use a temp one)")
    ap.add_argument("--settle", type=float, default=float(EPISODE_SETTLE_S),
                    help="seconds before an episode is judged (tests use 0)")
    ap.add_argument("--no-seed", action="store_true", help="skip the startup REST read (tests)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    s = Sentinel(args.db, args.cursor, args.settle, seed_from_rest=not args.no_seed)
    if args.once:
        s._tick()
        s._settle()
        LOG.info("once: decisions=%d open=%d", s.decisions, len(s.open))
        return 0
    signal.signal(signal.SIGTERM, s.stop)
    signal.signal(signal.SIGINT, s.stop)
    s.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
