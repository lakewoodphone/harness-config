-- 02-evidence.sql — the tenth table: where a picture of a person is recorded.
--
-- Why this exists, in one paragraph. The record today can say "a door opened at 14:33 and the
-- credential was not recognised". It cannot show who, because the nine tables in 01-security-record.sql
-- have no column that can hold or reference an image (measured 2026-10-27: grep for
-- image|file|path|snapshot|photo|jpeg|media over that file returns nothing). This table is that column,
-- and it is built around the three things the 2026-10-27 measurements proved:
--
--   1. TWO CLOCKS. Home Assistant's clock is right to the second; the cameras' burned-in stamps were
--      51-67 minutes wrong and are now a constant one hour behind. So captured_at (host) is the
--      authoritative time and the OSD is a second opinion that is stored WITH its measured offset.
--   2. A CAMERA CAN FAIL AND STILL LOOK HEALTHY. cam_larry_s_interior_main reports state=idle and
--      returns HTTP 500 on every channel. So a failure to capture is written as a ROW WITH A RESULT,
--      never as silence: an absent row and a row saying "http_500" are different facts.
--   3. THE SUBSTREAM LIES BY FIVE MINUTES. The 640x480 "fluent" entity of the doorbell served a frame
--      five minutes older than its own snapshots_clear entity at the same instant. So the row records
--      WHICH entity was asked, and capture must prefer the snapshot/clear entity.
--
-- Idempotent: safe to run repeatedly. Additive only; it does not touch any existing table.

CREATE TABLE IF NOT EXISTS security_evidence (
    id                TEXT PRIMARY KEY,      -- ev-<captured_at>-<camera>-<seq>: stable, sortable by time
    event_id          TEXT,                  -- security_event.id when an event triggered the capture
    entry_id          INTEGER,               -- entry_event.id when a credential event triggered it
    door_id           TEXT,                  -- the door this picture is meant to answer for
    camera_id         TEXT NOT NULL,         -- the Home Assistant entity asked, e.g. camera.cam_front_hallway_main
    captured_at       TEXT NOT NULL,         -- HOST clock, ISO-8601 UTC, authoritative
    captured_at_local TEXT NOT NULL,         -- host clock in the building's timezone, for humans
    osd_offset_s      INTEGER,               -- that camera's measured offset; NULL = never measured
    osd_measured_at   TEXT,                  -- when the offset last agreed with a picture
    path              TEXT,                  -- absolute path of the stored image; NULL when result != 'ok'
    sha256            TEXT,                  -- of the stored image; NULL when result != 'ok'
    bytes             INTEGER,
    width             INTEGER,
    height            INTEGER,
    source_host       TEXT NOT NULL,         -- which machine fetched it (a claim about where work ran)
    result            TEXT NOT NULL,         -- ok | http_500 | timeout | no_frame | too_small | wrong_camera
    detail            TEXT,                  -- the exact error text, never a paraphrase
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_evidence_captured  ON security_evidence(captured_at);
CREATE INDEX IF NOT EXISTS ix_evidence_event     ON security_evidence(event_id);
CREATE INDEX IF NOT EXISTS ix_evidence_entry     ON security_evidence(entry_id);
CREATE INDEX IF NOT EXISTS ix_evidence_camera    ON security_evidence(camera_id, captured_at);

-- The offset register: one row per camera per measurement, so the record can answer "when did we last
-- check that this camera's stamp was honest, and how wrong was it". A round hour is a timezone; a ragged
-- one is a dying clock; they need different repairs, and only the history distinguishes them.
CREATE TABLE IF NOT EXISTS camera_clock (
    camera_id         TEXT NOT NULL,
    measured_at       TEXT NOT NULL,         -- host clock at the moment of measurement
    osd_time          TEXT,                  -- what the picture said, as read
    offset_s          INTEGER,               -- host minus OSD, in seconds; positive = camera is behind
    verdict           TEXT NOT NULL,         -- clean | whole_hour | ragged | unreadable
    method            TEXT NOT NULL,         -- osd_ocr | manual_read | none
    note              TEXT,
    PRIMARY KEY (camera_id, measured_at)
);

CREATE INDEX IF NOT EXISTS ix_camera_clock_camera ON camera_clock(camera_id, measured_at);
