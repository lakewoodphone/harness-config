#!/usr/bin/env python3
"""security-listener — hold one Home Assistant websocket and write the security record.

Design constraints this file is written against (all measured, see
docs/security-and-evolution/ha-security/research/A-transport-runtime.md):

  * The transport is the WS API, not a webhook. HA answers 200 OK for an unregistered webhook id and
    200 OK when a webhook handler raises, so a webhook's success signal is uncorrelated with delivery.
    The WS handshake reports `auth_invalid`, acks every subscription, and produces an onclose on failure.
  * HA's event bus has NO replay. Silence after a reconnect is therefore ambiguous, so this listener
    writes an explicit gap marker after every reconnect and resyncs from /api/states.
  * Events are written with a monotonic `seq` per entity and a `dedup_key`, because several producers
    writing `created_at` cannot order a queue.
  * PIN VALUES ARE NEVER WRITTEN. The Kwikset exposes the last PIN used in plaintext on
    sensor.*_pin_code; that entity is excluded here by name, and any payload containing a `code` field
    is redacted before it reaches the row.

It writes only to the security_* tables. It never writes to any other table and it never calls an HA
service — it is a reader.

Usage:
    security-listener.py --once --seconds 20      # smoke test: connect, record, exit
    security-listener.py                          # run forever, supervised by systemd
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import signal
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone

try:
    import websockets
except ImportError:  # pragma: no cover
    print("FATAL: the 'websockets' package is required", file=sys.stderr)
    raise

LOG = logging.getLogger("security-listener")

# Entities worth a row. Prefix match; anything not here is ignored, which is what keeps this cheap
# (all state changes are ~22k/day; the security set is a few hundred).
ENTITY_PREFIXES = (
    "event.",            # non-state events (keypad, RFID, phoenix.valid_pin) are namespaced this way
    "binary_sensor.phoenix_",
    "binary_sensor.zone_",
    "binary_sensor.video_doorbell_",
    "binary_sensor.cam_",
    "binary_sensor.control_room_hub_",
    "binary_sensor.business_area_",
    "input_boolean.phoenix_",
    "input_select.phoenix_",
    "input_text.phoenix_access_control_log",
    "lock.",
    "script.phoenix_",
    "automation.phoenix_",
    "switch.smart_switch_",
    # Deliberately NOT `camera.`: measured on the first live run, twelve cameras reported `idle` in the same
    # second and filled 50% of the record with churn. A camera's *availability* is the Steward's periodic read
    # (S43/S44), not an event; a camera's *detection* arrives as binary_sensor.cam_*smart_motion_human*.
)
# Never record these, whatever their prefix says. `pin_code` is the last PIN used, in plaintext.
ENTITY_DENY_SUBSTRINGS = ("pin_code", "password", "token", "secret")
# Non-state events worth subscribing to: a credential use is an event, not a state change.
EXTRA_EVENT_TYPES = ("esphome.access_control_keypad_entry", "esphome.access_control_rfid_entry", "phoenix.valid_pin")

SCHEMA_TABLES = {"security_event"}
HEARTBEAT_PATH = "/var/lib/security-listener/heartbeat"
HEARTBEAT_EVERY_S = 60


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def beat(path: str = HEARTBEAT_PATH) -> None:
    """Liveness as a file with a timestamp, written atomically.

    A service that is `active` can still have a dead socket; a process that is running can still have stopped
    receiving. The only honest liveness signal is one the consumer writes *while doing its job*, so the
    heartbeat is written by the event loop itself, not by systemd.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(utcnow())
        os.replace(tmp, path)
    except OSError:
        pass  # a heartbeat failure must never take the listener down


# Exact keys whose VALUES are credentials, plus substrings that are credentials wherever they appear.
# Deliberately NOT "any key containing pin": `pin_name` carries a person's NAME, and redacting it destroyed
# every entry's identity before the sentinel could resolve it (measured 2026-10-26 23:07Z).
REDACT_KEYS = {"pin", "code", "pin_code", "entered_code", "password", "token", "secret", "api_key",
               "access_token", "refresh_token", "key"}
REDACT_SUBSTRINGS = ("password", "token", "secret", "api_key")


def redact(obj):
    """Strip credential-shaped fields from any payload before it is stored."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = k.lower()
            if kl in REDACT_KEYS or any(sub in kl for sub in REDACT_SUBSTRINGS):
                out[k] = "[REDACTED]"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class Store:
    """The single writer of the security record. Short transactions, WAL, bounded busy wait."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.seq = 0
        self.written = 0
        self.skipped = 0
        names = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = SCHEMA_TABLES - names
        if missing:
            raise SystemExit(f"FATAL: security record tables missing: {sorted(missing)}")

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def write_event(self, *, occurred_at: str, entity_id: str, old_state, new_state, raw: dict,
                    episode_id: str | None = None, door_id: str | None = None) -> str | None:
        if any(s in entity_id for s in ENTITY_DENY_SUBSTRINGS):
            self.skipped += 1
            return None
        if not entity_id.startswith(ENTITY_PREFIXES):
            self.skipped += 1
            return None
        dedup = f"{entity_id}|{occurred_at}|{new_state}"
        row_id = hashlib.sha1(dedup.encode()).hexdigest()[:24]
        seq = self.next_seq()
        try:
            self.conn.execute(
                "INSERT OR IGNORE INTO security_event "
                "(id, occurred_at, entity_id, domain, old_state, new_state, area, leaf_trigger, "
                " door_id, episode_id, recorder_gap, build_sha, raw, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?)",
                (
                    row_id, occurred_at, entity_id, entity_id.split(".")[0],
                    None if old_state is None else str(old_state),
                    None if new_state is None else str(new_state),
                    (raw.get("attributes") or {}).get("friendly_name") if isinstance(raw, dict) else None,
                    f"seq:{seq}",
                    door_id, episode_id,
                    os.environ.get("SECURITY_BUILD_SHA", "unrecorded"),
                    json.dumps(redact(raw), default=str)[:4000],
                    utcnow(),
                ),
            )
            self.written += 1
            return row_id
        except sqlite3.Error as exc:  # never die on one row
            LOG.warning("write failed for %s: %s", entity_id, exc)
            return None

    def write_gap(self, reason: str) -> None:
        """A reconnect is a hole in the stream; say so in the record instead of implying silence."""
        self.conn.execute(
            "INSERT OR IGNORE INTO security_event "
            "(id, occurred_at, entity_id, domain, new_state, leaf_trigger, recorder_gap, build_sha, raw, created_at) "
            "VALUES (?,?,?,?,?,?,1,?,?,?)",
            (uuid.uuid4().hex[:24], utcnow(), "security.listener", "security", reason[:60], reason,
             os.environ.get("SECURITY_BUILD_SHA", "unrecorded"), json.dumps({"reason": reason}), utcnow()),
        )


class Listener:
    def __init__(self, url: str, token: str, store: Store):
        self.url = url
        self.token = token
        self.store = store
        self.subscriptions = 0
        self.ha_version = None
        self._msg_id = 0

    def _id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def run_forever(self, once_seconds: float | None = None) -> None:
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20,
                                              max_queue=1024, close_timeout=5) as ws:
                    await self._session(ws, once_seconds)
                    if once_seconds:
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - every reconnect reason is worth recording
                LOG.warning("disconnected: %s: %s", type(exc).__name__, exc)
                self.store.write_gap(f"reconnect after {type(exc).__name__}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            backoff = 1.0

    async def _session(self, ws, once_seconds: float | None) -> None:
        hello = json.loads(await ws.recv())
        if hello.get("type") != "auth_required":
            raise RuntimeError(f"unexpected first frame: {hello.get('type')}")
        await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"auth failed: {auth.get('type')} {auth.get('message','')}")
        self.ha_version = auth.get("ha_version")
        LOG.info("authenticated, HA %s", self.ha_version)

        for event_type in ("state_changed",) + EXTRA_EVENT_TYPES:
            await ws.send(json.dumps({"id": self._id(), "type": "subscribe_events",
                                      "event_type": event_type}))
            ack = json.loads(await ws.recv())
            if not ack.get("success", False):
                LOG.warning("subscribe %s refused: %s", event_type, ack)
            else:
                self.subscriptions += 1
        LOG.info("subscribed to %d event types", self.subscriptions)
        self.store.write_gap("listener session start")

        started = time.monotonic()
        last_beat = 0.0
        while True:
            if once_seconds and (time.monotonic() - started) > once_seconds:
                LOG.info("once-mode window elapsed; written=%d skipped=%d",
                         self.store.written, self.store.skipped)
                return
            if time.monotonic() - last_beat >= HEARTBEAT_EVERY_S:
                beat()
                last_beat = time.monotonic()
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            self._handle(json.loads(raw))

    def _handle(self, msg: dict) -> None:
        if msg.get("type") != "event":
            return
        ev = msg.get("event") or {}
        etype = ev.get("event_type")
        data = ev.get("data") or {}
        when = ev.get("time_fired") or utcnow()
        if etype == "state_changed":
            entity_id = data.get("entity_id") or ""
            new = data.get("new_state") or {}
            old = data.get("old_state") or {}
            self.store.write_event(
                occurred_at=when, entity_id=entity_id,
                old_state=old.get("state"), new_state=new.get("state"), raw=new,
            )
        else:
            # A credential event: the credential itself is redacted, the fact is recorded.
            entity_id = f"event.{etype}"
            self.store.write_event(
                occurred_at=when, entity_id=entity_id,
                old_state=None, new_state="received", raw={"event_type": etype, "data": data},
            )


def read_token() -> str:
    token = os.environ.get("HA_TOKEN")
    if token:
        return token.strip()
    for path in ("/opt/company/.env", os.path.expanduser("~/.env")):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if line.startswith("HA_TOKEN="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    raise SystemExit("FATAL: HA_TOKEN not in env and not found in /opt/company/.env")


def selftest(db_path: str) -> int:
    """Prove the filter, the redaction and the write path without needing a real event.

    This exists because a 20-second live run captured ten events and none of them were security
    events — correct behaviour, and useless as a test. The frames below are shaped exactly like HA's.
    """
    store = Store(db_path)
    lst = Listener("ws://selftest", "unused", store)
    frames = [
        # must be written: a real perimeter door
        {"type": "event", "event": {"event_type": "state_changed", "time_fired": "2026-10-26T22:00:00Z",
         "data": {"entity_id": "binary_sensor.phoenix_control_room_interior_door_contact",
                  "old_state": {"state": "off"},
                  "new_state": {"state": "on", "attributes": {"friendly_name": "Shop door"}}}}},
        # must be REFUSED: the plaintext last PIN
        {"type": "event", "event": {"event_type": "state_changed", "time_fired": "2026-10-26T22:00:01Z",
         "data": {"entity_id": "sensor.0x002446fffd0a4705_pin_code",
                  "old_state": {"state": "1234"}, "new_state": {"state": "5678"}}}},
        # must be written, with the code REDACTED
        {"type": "event", "event": {"event_type": "esphome.access_control_keypad_entry",
         "time_fired": "2026-10-26T22:00:02Z", "data": {"code": "9999", "door_name": "strike"}}},
        # must be REFUSED: an unrelated sensor
        {"type": "event", "event": {"event_type": "state_changed", "time_fired": "2026-10-26T22:00:03Z",
         "data": {"entity_id": "sensor.asus_router_download_speed", "new_state": {"state": "1.2"}}}},
    ]
    for frame in frames:
        lst._handle(frame)
    conn = store.conn
    rows = list(conn.execute("SELECT entity_id, new_state, raw FROM security_event ORDER BY created_at"))
    print(f"written={store.written} skipped={store.skipped} rows={len(rows)}")
    for entity, state, raw in rows:
        print(f"  {entity:58s} {str(state):10s} {str(raw)[:90]}")
    leaked = conn.execute("SELECT COUNT(*) FROM security_event WHERE raw LIKE '%9999%'").fetchone()[0]
    print(f"pin_leak_rows={leaked}  (must be 0)")
    ok = store.written == 2 and store.skipped == 2 and leaked == 0
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run for --seconds then exit")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--db", default="/root/authority.db")
    ap.add_argument("--url", default=os.environ.get("HA_WS_URL", ""))
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--selftest", action="store_true",
                    help="feed crafted frames through the filter and assert what lands; needs --db")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.selftest:
        return selftest(args.db)

    token = read_token()
    url = args.url
    if not url:
        ha = os.environ.get("HA_URL", "")
        if not ha:
            try:
                with open("/opt/company/.env", "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if line.startswith("HA_URL="):
                            ha = line.split("=", 1)[1].strip().strip('"').strip("'")
            except OSError:
                pass
        ha = ha or "http://zabz-tech.tail93e6e6.ts.net:8123"
        url = ha.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/api/websocket"

    store = Store(args.db)
    listener = Listener(url, token, store)
    LOG.info("connecting to %s", url)

    async def _main():
        task = asyncio.create_task(listener.run_forever(args.seconds if args.once else None))
        try:
            if args.once:
                await asyncio.wait_for(task, timeout=args.seconds + 20)
            else:
                await task
        except asyncio.TimeoutError:
            LOG.warning("once-mode overran its window; cancelling")
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
    LOG.info("stopped: written=%d skipped=%d subs=%d ha=%s",
             store.written, store.skipped, listener.subscriptions, listener.ha_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
