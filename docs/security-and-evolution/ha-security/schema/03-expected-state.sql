-- 03-expected-state.sql — what a decision must carry now that the building has three states.
--
-- Why. On 2026-10-27 the owner answered two questions that change what a decision row MEANS:
--   Q3 + D8: the shop and the apartment share one basement, so there are three declared states —
--            shop_closed | apartment_occupied | nobody_here — and a body moving at night is a resident
--            in one state and an intruder in another.
--   Q9 (choice B): residents are recorded like anyone else, but marked EXPECTED, so their movement never
--            raises an alarm or a page while still being in the record.
--
-- Without these columns a later reader cannot tell "nobody was there, so nothing fired" from "a resident
-- was there and we deliberately did not alarm", which is the difference between a record and a rumour.
-- It is also the only way the learning loop can be trained without teaching itself that residents are
-- intruders: an EXPECTED row is a labelled negative, and it must be labelled by the decision, not guessed
-- later from the subject alone.
--
-- SQLite cannot ALTER a CHECK constraint and cannot add a column idempotently, so this file is ONE-SHOT.
-- Apply it only if the columns are absent:
--
--   sqlite3 /root/authority.db "pragma table_info(security_decision)" | grep -q expected \
--     || sqlite3 /root/authority.db < 03-expected-state.sql
--
-- Verified after applying (2026-10-27): the three columns are present and every existing row reads
-- expected=0, declared_state=NULL — which is honest, because every decision taken before this moment was
-- taken without a declared state and therefore cannot be reinterpreted as if it had one.

ALTER TABLE security_decision ADD COLUMN declared_state TEXT;   -- shop_closed | apartment_occupied | nobody_here | NULL (unknown, pre-2026-10-27)
ALTER TABLE security_decision ADD COLUMN expected INTEGER NOT NULL DEFAULT 0;  -- 1 = a person we expected, in the state then declared
ALTER TABLE security_decision ADD COLUMN subject_id TEXT;       -- who, when the record can honestly say; NULL is a correct answer
ALTER TABLE security_decision ADD COLUMN evidence_id TEXT;      -- the security_evidence row with the picture, when one was taken

CREATE INDEX IF NOT EXISTS ix_sec_dec_subject  ON security_decision(subject_id);
CREATE INDEX IF NOT EXISTS ix_sec_dec_expected ON security_decision(expected, created_at);
