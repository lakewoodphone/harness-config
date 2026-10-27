-- 01-security-record.sql — the security record, version 1
-- Applied to /root/authority.db on secratary-cloud. Idempotent: every statement is IF NOT EXISTS.
--
-- Why these tables exist: today the system forgets in about four weeks (HA recorder ~28 days) and records
-- nothing at all about why a decision was made. A learning security system cannot start without a past, and
-- every day without these rows is a day that can never be learned from. Schemas follow
-- doc/security-and-evolution/ha-security/research/D-learning-loop.md, reconciled with 25-MIND-CONTRACT.md.
--
-- Rules this schema enforces:
--   * append-only: nothing here is ever UPDATEd to look better; a correction is a new row with `supersedes_id`
--   * one writer: only the security runtime writes these tables
--   * every row carries the build that produced it (`build_sha`), so a decision from an unknown build is not learnable
--   * a label is never invented by a disarm: `evidence_class` records what actually settled it

BEGIN;

-- 1. Every signal edge that could matter, one row per leaf trigger (not the fused zone).
CREATE TABLE IF NOT EXISTS security_event (
    id            TEXT PRIMARY KEY,
    occurred_at   TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    domain        TEXT,
    old_state     TEXT,
    new_state     TEXT,
    area          TEXT,
    leaf_trigger  TEXT,
    door_id       TEXT,
    episode_id    TEXT,
    recorder_gap  INTEGER NOT NULL DEFAULT 0,
    build_sha     TEXT NOT NULL,
    raw           TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sec_event_time    ON security_event(occurred_at);
CREATE INDEX IF NOT EXISTS ix_sec_event_episode ON security_event(episode_id);
CREATE INDEX IF NOT EXISTS ix_sec_event_entity  ON security_event(entity_id, occurred_at);

-- 2. One row per decision: what fired, what was considered, what was decided, what went out.
CREATE TABLE IF NOT EXISTS security_decision (
    id            TEXT PRIMARY KEY,
    event_id      TEXT REFERENCES security_event(id),
    episode_id    TEXT,
    rule_id       TEXT NOT NULL,
    rule_version  TEXT NOT NULL,
    decided_by    TEXT NOT NULL,
    considered    TEXT NOT NULL,
    decision      TEXT NOT NULL CHECK (decision IN ('ALARM','NO_ALARM','SUPPRESSED','ERROR','ESCALATE')),
    avs_level     INTEGER,
    confidence    REAL,
    reason_one_line TEXT,
    page_text     TEXT,
    paged_at      TEXT,
    acked_at      TEXT,
    ack_channel   TEXT,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    build_sha     TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sec_dec_created ON security_decision(created_at);
CREATE INDEX IF NOT EXISTS ix_sec_dec_episode ON security_decision(episode_id);

-- 3. What actually happened. Append-only. This is the training set.
CREATE TABLE IF NOT EXISTS security_label (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    TEXT NOT NULL,
    label         TEXT NOT NULL CHECK (label IN
                    ('owner','parent','wife','guest','tenant','customer','passer_by','courier',
                     'worker','drill','unknown','infrastructure_false','DISARM_ONLY')),
    evidence_class TEXT NOT NULL CHECK (evidence_class IN
                    ('credential','camera_frame','owner_statement','keypad_slot','disarm','none','NO_ANSWER')),
    confidence    REAL NOT NULL DEFAULT 0.0,
    basis         TEXT,
    labelled_by   TEXT NOT NULL,
    supersedes_id INTEGER REFERENCES security_label(id),
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sec_label_episode ON security_label(episode_id);

-- 4. What was done and by whom: siren, page, call, silence, disarm, drill.
CREATE TABLE IF NOT EXISTS security_action (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id   TEXT REFERENCES security_decision(id),
    episode_id    TEXT,
    action        TEXT NOT NULL CHECK (action IN
                    ('SIREN_ON','SIREN_OFF','PAGE','PAGE_FAILED','CALL','SILENCE','DISARM','ARM',
                     'DRILL','RETRY','ASK_OWNER','ANSWER_RECEIVED')),
    actor         TEXT NOT NULL,
    attempted_at  TEXT NOT NULL,
    result        TEXT NOT NULL CHECK (result IN ('ok','failed','refused','timeout')),
    recipient     TEXT,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS ix_sec_action_episode ON security_action(episode_id);

-- 5/6. Replay: every proposed change is evaluated against all stored history before it may be promoted.
CREATE TABLE IF NOT EXISTS replay_run (
    id            TEXT PRIMARY KEY,
    corpus_version TEXT NOT NULL,
    proposal_id   TEXT,
    created_at    TEXT NOT NULL,
    episodes_evaluated INTEGER NOT NULL DEFAULT 0,
    missed_real   INTEGER NOT NULL DEFAULT 0,
    false_added   INTEGER NOT NULL DEFAULT 0,
    verdict       TEXT NOT NULL CHECK (verdict IN ('pass','fail','inconclusive')),
    notes         TEXT
);
CREATE TABLE IF NOT EXISTS replay_episode (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES replay_run(id),
    episode_id    TEXT NOT NULL,
    expected      TEXT,
    actual        TEXT,
    missed_real   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_replay_ep_run ON replay_episode(run_id);

-- 7/8/9. Identity: five subjects, their credentials, and every credential use.
CREATE TABLE IF NOT EXISTS subject (
    id            TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL,
    rank          INTEGER NOT NULL DEFAULT 9,
    page_targets  TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credential (
    slot          TEXT NOT NULL,
    system        TEXT NOT NULL,
    kind          TEXT NOT NULL,
    subject_id    TEXT REFERENCES subject(id),
    value_hash    TEXT,
    issued_at     TEXT,
    rotated_at    TEXT,
    revoked_at    TEXT,
    revoked_why   TEXT,
    PRIMARY KEY (slot, system)
);
CREATE TABLE IF NOT EXISTS entry_event (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at   TEXT NOT NULL,
    door_id       TEXT NOT NULL,
    system        TEXT NOT NULL,
    slot          TEXT,
    source        TEXT,
    subject_id    TEXT REFERENCES subject(id),
    confidence    REAL NOT NULL DEFAULT 0.0,
    raw_hash      TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_entry_event_time ON entry_event(occurred_at);

COMMIT;

-- The five subjects, from the owner's own statement and the live slot map
-- (live/apartment_deadbolt_codes.LIVE.yaml:7-36). Mother and father SHARE slot 4 by his instruction, so
-- they are one identity for alarm purposes and must never be logged as individuals.
INSERT INTO subject (id, display_name, role, rank, active, created_at) VALUES
  ('owner',    'Eliyahu',            'owner',    1, 1, datetime('now')),
  ('parent',   'Mother and Father',  'parent',   2, 1, datetime('now')),
  ('wife',     'Yocheved',           'wife',     3, 1, datetime('now')),
  ('guest',    'House access (shared)', 'guest', 4, 1, datetime('now')),
  ('tenant',   'Tenant',             'tenant',   5, 1, datetime('now'))
ON CONFLICT(id) DO NOTHING;

INSERT INTO credential (slot, system, kind, subject_id, issued_at) VALUES
  ('1',  'kwikset_apartment', 'pin', 'owner',  datetime('now')),
  ('4',  'kwikset_apartment', 'pin', 'parent', datetime('now')),
  ('5',  'kwikset_apartment', 'pin', 'wife',   datetime('now')),
  ('6',  'kwikset_apartment', 'pin', 'guest',  datetime('now')),
  ('11', 'kwikset_apartment', 'pin', 'tenant', datetime('now'))
ON CONFLICT(slot, system) DO NOTHING;
