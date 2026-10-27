# D — The learning loop for security, and why it cannot lie to itself

**Lane:** D (learning loop) · **Host:** `zabz-tech` · **Date:** 2026-10-26 · **Mode:** read-only throughout
**Inputs:** `HANDOFF-TO-NEXT-AGENT.md` (cited as **H**), `ha-security/from-zabz-tech/security-system-design-2026-10-26.md` (**DD**), `R4-ground-truth.md` (**R4**), `W8-maintenance.md` (**W8**); code at `C:\Users\ezabz\code\personal-secretary-mvp`; live `/opt/company` on `secratary-cloud`; `/root/authority.db` read with `sqlite3 -readonly`.
**Convention:** a factual sentence carries `file:line`, `table: count`, or `command → output`. **UNVERIFIED** = this lane did not measure it.

---

## 1. What the existing machinery actually is

### 1.1 The ledger: `evolution_log` — 186 rows, and no outcome

Schema, read from the authority (`sqlite3 -readonly /root/authority.db '.schema evolution_log'`):

```
id, agent_id, change_type, description, files_changed, proposal_id,
applied, rollback, created_at, status, status_note
```

Raw counts:

| Query | Output |
|---|---|
| `SELECT COUNT(*) FROM evolution_log` | **186** |
| `GROUP BY status` | `applied 103`, `dismissed 74`, `open 9` |
| `GROUP BY applied` | `0 → 83`, `1 → 103` |
| `change_type` | `proposal 186` (only value ever written) |
| `description LIKE '%long function%'` | **137 of 186** |
| `MIN/MAX(created_at)` | `2026-02-19T02:06:24Z` → `2026-10-14T22:30:54Z` |
| `rollback=1` | **0** |

Three facts follow, and they are the whole problem in one table:

1. The ledger records a **proposal** and whether a patch was written, never whether anything got better. `change_type` is always `proposal` — there is no `outcome` row type (`evolution_log: change_type`).
2. Most of what it "evolved" is a linter: 137 of 186 descriptions are `Improve <file>: fix N long functions. Add proper error handling…` (e.g. id 152, `2026-07-04`). A generator that can only see code shape can never propose a security rule, a threshold, or a label policy.
3. It has been silent for 12 days: newest row `2026-10-14T22:30:54Z` against a run at `2026-10-26 21:2xZ` → the engine is not currently producing proposals at all, while the 9 `open` ones (oldest id 227, `2026-09-15`) sit unactioned.

### 1.2 The verdict table: `evolution_verification` — 128 rows, one metric, 103 tautologies

Schema (`sqlite3 -readonly /root/authority.db '.schema evolution_verification'`):

```
id, proposal_id, evolution_log_id, target_metric, baseline_value,
target_value, post_value, measurement_ticks, status, rollback_reason,
created_at, completed_at, snapshot_id
CHECK(status IN ('pending','measuring','passed','failed','rolled_back'))
```

Raw counts:

| Query | Output |
|---|---|
| `SELECT COUNT(*)` | **128** |
| `GROUP BY status` | `passed 114`, `failed 14`, `rolled_back 0` |
| `COUNT(DISTINCT target_metric)` | **1** — the value is `error_count` in all 128 |
| `target_value IS NULL` | **128 of 128** — no proposal ever named a target |
| `snapshot_id IS NOT NULL` | **0 of 128** — no rollback target was ever stored |
| rows with `measurement_ticks = 3` | **103** |
| those 103: `post_value = baseline_value` | **103 of 103, exactly** |
| those 103: `proposal_id IS NULL`, `evolution_log_id` set | 103 |
| legacy 25: `proposal_id = 0`, ticks ≥ 10 | 11 passed, 14 failed |
| `failed` rows where `post_value <= baseline_value` | **5 of 14** |

The 103 are the 2026-10-26 backfill. They were not measured one at a time: one baseline was read, one later value was read, and all 103 rows carry the same comparison. `post_value = baseline_value` in every one is not a coincidence of 103 independent changes — it is one batch compared with itself.

That is what H §4.4 admits in prose ("`103 of 103 passed` is exactly as uninformative as `0 of 0`") and what the table now proves numerically: **the passing rows satisfy `post <= baseline` by equality, so `passed` means "did not get worse in a 24-hour window", not "worked".**

Worse, 5 of the 14 `failed` rows also satisfy `post <= baseline` (e.g. id 7: baseline `0.0`, post `0.0`, status `failed`; id 4: `1.0 → 1.0`, `failed`). A verdict column that contradicts its own two numbers cannot be used as a label by anything downstream.

### 1.3 The code path: the gate is real, the wiring is not

- `app/services/evolution_verifier.py:582-594` — `gate_proposal()` refuses a proposal with no `target_metric` or no `baseline_value`. This is the right rule and it exists.
- `app/evolution.py:1016-1021` — the only caller passes `target_metric="error_count"` and a fresh `_get_error_baseline()`. So the rule is satisfied cosmetically; **every proposal claims the same metric**.
- `app/evolution.py:1136-1141` — after an auto-apply it calls `create_verification(proposal_id=0, evolution_log_id=None, target_metric="error_count", baseline_value=<fresh read>)`. The gated metric and baseline are **discarded**, and the row is not linked to the proposal or the log row.
- `app/evolution.py:1274-1299` — `_get_error_baseline()` returns `0` on any exception. A failed measurement is indistinguishable from a clean baseline of zero.
- `app/services/evolution_verifier.py:400-404` — `improved` requires `current < baseline`; at `:414` `regressed` is `current > baseline * 1.05`; at `:452-460` a row that is neither improved nor regressed for 50 ticks is written **`passed`, reason `timeout_neutral`**. Flat is a pass.
- `/opt/company/app/services/evolution_loop.py` (live) — `TICKS_BEFORE_VERDICT = 3`, `FAILURE_MARGIN = 1.25`; `_current_metric` is `COUNT(*) FROM error_log WHERE created_at > datetime('now','-24 hours')`; the backfill inserts `baseline = current` **and `target_value = baseline`**, then passes a row when `base > 0 and current <= base`. Because the metric is a rolling 24-hour count, it falls on its own; because `base = 0` is excluded, a genuinely zero-error week can never pass.

The loop is running and doing nothing, which is a different failure from being dead:

```
/var/log/evolution-loop.log → 19 lines, every one
  "evolution-loop: backfilled=0 measured=0 passed=0 failed=0"
mtime 2026-10-26 21:17:01Z   (cron :17 hourly, /etc/cron.d/evolution-loop)
```

It is a no-op because there are no new applied changes and no `measuring` rows — the 9 open proposals were never applied, and nothing has been proposed since 2026-10-14.

### 1.4 The supporting desks

- `app/services/mashgiach.py:475` — the repo copy still writes the **literal `0`** for `findings_count`. The authority copy is patched (`/opt/company/app/services/mashgiach.py:479` reads the real count): `mashgiach_dept_scores` now has **6,244 rows, `SUM(findings_count)=3,481`**, up from 0 (H §3.4). But `SUM(auto_fixes)=0` and `SUM(escalations)=0` across all 6,244 rows — it finds and cannot fix.
- `dept_security` in that table: **2 rows, `SUM(findings_count)=1`**, latest week `2026-10-19`. In `mashgiach_audit_log`: **42,078 rows total, 6 mention security**.
- `/opt/company/app/services/stagnation_detector.py` — one real idea worth keeping: **SILENT** (no tick in 7 days) is tested before **IDLE** (ticking, zero findings), because a desk that never ran cannot be judged on findings. It writes a deduplicated `mashgiach_audit_log` row; it fixes nothing. Last runs: `stagnation: checked=19 silent=4 idle=0 logged=0` (`/var/log/stagnation-sweep.log`, 20:47Z).
- `app/services/autonomy.py:376-377` — **an action not in `DEFAULT_MATRIX` returns `L4_AUTONOMOUS`**, with the comment "bias towards action". `:482` gives such an action `max = 2`, so it starts at the top and can never be promoted — but it *executes immediately*. This is the single most dangerous line for a promotion pipeline (§6.3).

### 1.5 Reusable vs trap

| Piece | Verdict | Why |
|---|---|---|
| `evolution_verification` **schema** (metric, baseline, target, post, ticks, status, `rolled_back`, `rollback_reason`, `snapshot_id`) | **Reusable** | The columns a learning loop needs already exist. `snapshot_id` and `rolled_back` were designed and never used. |
| `gate_proposal()` mandatory metric+baseline (`evolution_verifier.py:582-594`) | **Reusable as a shape** | Correct refusal; must *persist* the values it validates instead of returning them to a caller that discards them. |
| `evolution_loop.py`'s "leave it open rather than flatter it into a pass" | **Reusable instinct** | The comment is right; the implementation then passes on equality. |
| Mashgiach's single-transaction, batched-insert discipline (`mashgiach.py:121-187`) | **Reusable engineering** | Solves real `SQLITE_BUSY_SNAPSHOT` loss; measured 62 lock errors/minute before it (comment at `:130-131`). |
| Stagnation SILENT/IDLE split | **Reusable concept** | Applies directly to sensors: silent ≠ busy-but-useless. |
| One global `error_count` metric | **Trap** | Cannot attribute effect to a change; a rolling 24 h count falls by itself. |
| Baseline re-read at verification time | **Trap** | The proposal-time number is the only one that can be honest; re-reading lets a change be graded against a different world. |
| `passed` on timeout / equality | **Trap** | Produces H §4.4's `103/103`. |
| `proposal_id=0, evolution_log_id=None` (`evolution.py:1137-1138`) | **Trap** | The verdict cannot be joined to the change. |
| Static-analysis generator (137/186 "long functions") | **Trap for security** | It cannot express a rule change, so "evolution" can never touch the alarm. |
| `_get_error_baseline() → 0` on failure | **Trap** | Failure looks like a perfect baseline. |
| `autonomy.py` unknown → L4 | **Trap** | A new action introduced by a promotion is autonomous unless someone remembers the matrix. |
| `evolution_log` as the change ledger | **Partially reusable** | Keep it as the append-only *what changed* log; add the outcome table beside it, do not overload `description`. |

---

## 2. The measurement rule

### 2.1 The rule, stated so it can be enforced

> **At proposal time, a change must write down (a) the one metric it expects to move, (b) that metric's value on a named window ending at the proposal timestamp, (c) the direction and the minimum effect worth caring about, and (d) the paired metrics it must not degrade. The verification row stores those frozen values; it never re-derives them.**

Today's system violates (b) at `evolution.py:1139-1140` (fresh baseline at verification), (a) at `:1019` (constant metric), and (d) nowhere (no paired metrics at all). `target_value` is NULL in 128/128 rows (`evolution_verification`), so (c) has never existed.

### 2.2 The two classes of security metric

The design already names the distinction — DD:266, "pair every such metric with a coverage metric that cannot improve by doing less" — but does not enumerate them. Here is the enumeration, with the measured starting point where one exists.

**Class A — cannot be improved by doing less. These are invariants, not objectives.**

| Metric | Definition | Starting point (measured) | Why it cannot be gamed by silence |
|---|---|---|---|
| `credential_coverage` | door-open edges with a granted `entry_event` in the prior 120 s ÷ all door-open edges | **87/286 = 30 %** in 28.76 days (DD:915-916) | suppressing alarms does not create credentials |
| `tier_a_alive_minutes` | armed minutes in which all three door contacts + the doorbell reported | 6 camera human sensors: **0 transitions in 4.8 days** (R4:42) | a quieter system has fewer armed minutes, not more live sensors |
| `sensor_roster_alive` | named roster entities reporting (not `unavailable`/`unknown`/`idle`) | **35.7 % of the estate unavailable** and nothing alerts (W8:168) | removing an entity from the roster must fail the check, not pass it |
| `door_to_page_p50/p95` | seconds from the Tier-A edge to the page attempt | **never measured** (DD:676 says "measured for the first time ever") | fewer pages do not make each page faster |
| `page_to_ack_p50` | seconds from page to a recorded human action | **never measured** (R4:252: "nobody noticed" and "noticed and ignored" are the same observation) | silence cannot improve acknowledgement |
| `drill_pass` | 4/4 stills present, page delivered to every recipient, ack recorded | a drill **"would have passed" with a quarter of the evidence missing** (W8:184) | skipping the drill is the only way to "improve" it, so it is scheduled |
| `labels_per_week` | confirmed labels written in the last 7 days | 0 security labels exist (no `security_*` table on the authority) | a system that stops recording stops learning (DD:186-187) |
| `replay_corpus_episodes` | episodes in the frozen corpus the current rules were replayed against | 15 episodes, 13 fully covered (R4:129) | a smaller corpus makes replay easier, so the corpus is versioned and append-only |

**Class B — can be improved by doing less. These are the objectives, and each is only allowed to move with Class A held.**

| Metric | Definition | Starting point (measured) |
|---|---|---|
| `false_pages_per_week` | pages whose settled label is not an intrusion/drill | target **≤ 1/week** (DD:673); current **~3.5/week, all false** (DD:673) |
| `alarm_episodes_per_week` | `intrusion_active` on-edges | **15 in 30 days** (R4:129) |
| `median_armed_seconds` | median time armed per episode | **223 s; max 43,323 s** (R4:129) |
| `pages_per_event` | page attempts ÷ events | **0 intrusion pages in 4,507 `sms_log` rows**, 2025-09-02 → 2026-10-26 (W5:165-167) |
| `suppressed_events` | events closed without a page | 11 of 19 candidate triggers in 4.8 days (R4:183) |
| `disarms_per_week` | manual/soft disarms | **0 manual disarms exist** — the only paths are `valid_pin` and `everyone_away→off` (R4:35, R4:154) |

The pairing rule, enforceable in one predicate:

```
PROMOTE only if
  Δ(false_pages_per_week) < 0
  AND Δ(credential_coverage)      >= -0.02
  AND Δ(tier_a_alive_minutes)     >= -0.02
  AND Δ(door_to_page_p95)         <= +5 s
  AND drill_pass                  = true
  AND Δ(labels_per_week)          >= -0.20
  AND replay.missed_real          = []
```

Note what is **not** in Class B: "detection rate" and "precision". With 0 positives in 30 days, detection rate is undefined and any confusion matrix built on 15 false alarms is theatre (DD:678-681). Until a positive exists, the honest claim is coverage plus the replay gate, not accuracy.

### 2.3 Worked example — the proposal the current system would happily pass

Proposal: *"remove `video_doorbell_person` from `zone_hallway_active`"*.

- It targets a real defect: that zone is fed by a **public hallway** and produced **13 of 13 alarms** (DD:881), and `zone_hallway_active` is literally `doorbell OR outside-door OR control-room-exterior-door` (R4:46).
- Under today's rules it passes: metric is `error_count` (unchanged), baseline re-read at verification, and after 3 ticks the 24 h error count is not higher → `passed` (`evolution_loop.py`, `TICKS_BEFORE_VERDICT = 3`).
- Under the rule in §2.2: Class B improves (`alarm_episodes_per_week` falls, `false_pages_per_week` falls), Class A is unchanged, **but `replay.missed_real` is not empty** once the labels are corrected — because 7 of the 13 "worker arriving" episodes are, on the owner's own statement, *not workers* (DD:851-860). The proposal suppresses the only class of event the system exists for. It must fail.

That single case is why §3 and §4 are not optional decoration.

---

## 3. The label problem

### 3.1 What actually settles "who was that" in this building

Ranked by what the signal can prove, not by how easy it is to collect. The measured state is in DD:500-512: two live RFID tags, four live PINs, a keypad handler that is switched off so `phoenix.valid_pin` **never fires**, and a "credential log" that is a 255-character rolling string holding six entries.

| Rank | Evidence | What it proves | What it does not prove | Measured basis |
|---|---|---|---|---|
| 1 | **Granted `entry_event`** (subject_id, door, direction, timestamp) | a specific credential was granted at a specific door | that the holder is the person — tailgating defeats it; shared codes name a role | DD:522-535; the rule "door with no granted entry_event in N s is an alarm" |
| 2 | **Camera frame + a human naming it** | a face/parcel was present; a human asserts who | identity by itself — no machine vision exists on the estate at all | DD:396-400 ("no `image_processing` component; nothing classifies a frame"); R4:252 (a clear still exists, "the label does not exist") |
| 3 | **Owner statement** | the owner's assertion, with author/time | reproducibility; it is retrospective and may itself be wrong | DD:838-848 — one sentence ("montrose hasn't worked here in months") explained thirteen alarms |
| 4 | **Named keypad slot** (a PIN/tag mapped 1:1 to a person) | which code was used | who typed it; role codes (`house access`) name a role, not a person | DD:553-556 — whether roles stay shared is an open owner decision |
| 5 | **Phone presence** (`device_tracker`) | a phone is within a 100 m zone | a person is in the building; that the phone's owner still works here | DD:842-848 — `device_tracker.monty` reported `home` months after Montrose left; DD:225 ("leave a phone inside" defeats it) |
| 6 | **Disarm** (`everyone_away → off`, siren reset) | a human or a presence rule stopped the noise | anything about who was there, or whether the alarm was right | R4:154 — **13 of 15 episodes ended this way, 0 by PIN, 0 by manual disarm** |

Two measured consequences that must shape the schema:

- The **ghost worker** is not an edge case, it is the modal case: the disarm path credited a person who left months ago, so the *only* label the system produced for 13 episodes was "the presence system noticed someone entitled to be there" — and for 7 of those, the owner says that person was not a worker at all (DD:851-860). A label derived from the disarm is therefore not merely weak; here it was **wrong in the same direction 7 times**.
- **The design document disagrees with itself about those 7 episodes.** DD:690-702 (Round 18) scores them "worker arriving → correct, silent"; DD:858-860 (Addendum II, later the same day) re-opens them as `UNKNOWN_PERSON / unbadged door` and says "the new rule *would* fire on those doors". Both cannot be the training set. The later, owner-sourced one wins, and Round 18's replay is stale.

### 3.2 Label schema

```sql
CREATE TABLE security_label (
  id                 INTEGER PRIMARY KEY,
  event_id           TEXT NOT NULL,          -- security_decision.id (one alarm) or security_event.id
  label              TEXT NOT NULL CHECK (label IN (
                       'OWNER_ARRIVAL','WORKER_ARRIVAL','TENANT_ARRIVAL','CUSTOMER_ENTRY',
                       'DELIVERY_NO_ENTRY','PASSER_BY_NO_ENTRY','UNKNOWN_PERSON_NO_ENTRY',
                       'UNAUTHORISED_ENTRY','FORCED_ENTRY','INFRASTRUCTURE_FALSE','DRILL',
                       'SYSTEM_ERROR','NO_ANSWER')),
  subject_id         INTEGER REFERENCES subject(id),   -- NULL for roles/unknown
  evidence_class     TEXT NOT NULL CHECK (evidence_class IN (
                       'CREDENTIAL','CAMERA_FRAME_NAMED','OWNER_STATEMENT',
                       'NAMED_KEYPAD_SLOT','PHONE_PRESENCE','DISARM_ONLY','NONE')),
  evidence_ref       TEXT,                   -- entry_event.id | snapshot path + sha | statement id
  evidence_strength  INTEGER NOT NULL,       -- derived from evidence_class, see below
  confidence         REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  labelled_by        TEXT NOT NULL,          -- 'human:eliyahu' | 'agent:dept_security' | 'system:rule'
  labelled_at        TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'provisional'
                       CHECK (status IN ('provisional','confirmed','rejected','superseded')),
  supersedes_label_id INTEGER REFERENCES security_label(id),
  note               TEXT
);
CREATE INDEX ix_label_event ON security_label(event_id, status);
```

`evidence_strength` is **derived, never typed**: `CREDENTIAL=3`, `CAMERA_FRAME_NAMED=3`, `OWNER_STATEMENT=3`, `NAMED_KEYPAD_SLOT=2`, `PHONE_PRESENCE=1`, `DISARM_ONLY=1`, `NONE=0`. Storing it makes the quorum query trivial and stops an optimistic labeller from asserting strength.

Append-only: a correction is a new row with `supersedes_label_id` and the old row moved to `superseded`. Never `UPDATE … SET label=`. The ghost-worker re-label is exactly this operation, and if it had been an update the 13 alarms would have lost the evidence that the old label existed.

### 3.3 The rule: a disarm is a weak label and may never delete a rule on its own

Formally:

> **A `DISARM_ONLY` label may open a proposal. It may never close one.**
>
> A proposal that removes a term, widens a window beyond its pre-approved band, disables a rule, mutes a zone, or adds an allow-list ("any change that reduces firing power", DD:270) is promotable only if **every episode it would newly suppress** has a `confirmed` label with `evidence_strength = 3`. `DISARM_ONLY` and `PHONE_PRESENCE` labels contribute **zero** to that quorum, and one strength-3 label is mandatory even when all others are strength 2.

Why equality with "every episode", not a majority: the failure mode is not "we suppressed slightly too much", it is "the fifth time it is a burglar and the pattern is suppressed" (DD:265). A single suppressed real event is the whole loss.

Why the disarm is nevertheless recorded: it is the only signal that says "a human was annoyed at 14:03". That is a legitimate *complaint* and a good source of proposals. It is not evidence about the world. H's own instruction to the next agent — "Verify by reading the system back, never by trusting that a change is live" (H:79-81) — is the same epistemology one level up.

The counter-test to run before any such promotion: take the proposal's suppression set and ask, for each episode, "what would a burglar have had to do differently to be in this set?" If the answer is "nothing", the label is not evidence.

---

## 4. Replay

### 4.1 What is stored

The premise in the brief is correct, and it corrects Round 8: the recorder holds **~28 days**, not 44 hours — `states` holds **2,335,006 rows across 26 distinct days back to 2026-09-28** (DD:413-415), and an independent probe found the retention edge between 27 and 30 days (`video_doorbell_person`: 435 rows on 2026-10-05, 182 on 2026-09-29, 0 on 2026-09-26 — R4:20).

The corpus must therefore be four things, not one:

1. **Signal timeline** — `states` for the named security roster, 28 days, exported with `last_changed`/`last_updated` (not `state` alone) and a per-entity row count so density can be distinguished from depth (R4:20).
2. **Episode set** — 15 episodes, 13 fully covered, each with a frozen label row (§3.2) and its evidence manifest. R4's per-episode second-by-second record (R4:56-127) is the template.
3. **Gaps as first-class rows** — the **30 h 41 min** hole from 2026-10-23 13:03:09 to 2026-10-24 19:44:43 (R4:22) and the fact that `binary_sensor.phoenix_outside_door_contact` recorded **no transitions before 2026-10-21** (R4:24). A replay that treats a silent gap as "no event" will "prove" a rule is safe on 15 days where its input did not exist. This is exactly the error R4 measured: month-wide 11 % doorbell→door, restricted to the covered window 62 % (R4:24).
4. **Build identity** — the running sha of the backend that produced each decision (DD:271; H §6.6 records that `/opt/company` is 329 files dirty and a different lineage from the repo). A decision from an unnamed build is not learnable.

### 4.2 The harness

Two tables, one CLI, deterministic execution:

```sql
CREATE TABLE replay_run (
  id              TEXT PRIMARY KEY,          -- uuid
  proposal_id     TEXT NOT NULL,
  corpus_version  TEXT NOT NULL,             -- sha256(episode set + signal extract + gap list)
  code_sha        TEXT NOT NULL,
  rules_sha       TEXT NOT NULL,             -- sha256 of the candidate rule file(s)
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  episodes        INTEGER NOT NULL,
  suppressed      INTEGER NOT NULL,          -- episodes that went ALARM -> NO_ALARM
  added           INTEGER NOT NULL,          -- NO_ALARM -> ALARM
  missed          INTEGER NOT NULL,          -- suppressed AND label requires an alarm
  missed_list     TEXT NOT NULL DEFAULT '[]',-- JSON; the gate is missed_list = '[]'
  verdict         TEXT NOT NULL CHECK (verdict IN ('pass','fail','inconclusive'))
);
CREATE TABLE replay_episode (
  run_id          TEXT NOT NULL REFERENCES replay_run(id),
  episode_id      TEXT NOT NULL,
  label_id        INTEGER REFERENCES security_label(id),
  old_decision    TEXT NOT NULL,
  new_decision    TEXT NOT NULL,
  delta_seconds   REAL,
  missed          INTEGER NOT NULL DEFAULT 0,
  note            TEXT,
  PRIMARY KEY (run_id, episode_id)
);
```

The run itself is an **event-sourced simulation**, not a rule trace. Round 18 is honest that it is "a rule trace, not an execution" and that the real test is a shadow run (DD:710-711); the harness must close that gap:

- Feed the recorded `(timestamp, entity, old_state, new_state)` stream into the candidate rule evaluator in timestamp order, with the same 6-second grace and the same latch semantics as the live scripts. No wall clock, no `now()`.
- Emit one decision row per would-be alarm, with the leaf trigger, the signals considered, and the reason string.
- Compare against the frozen episode set by `episode_id`, not by fuzzy time matching.
- Store the whole per-episode table, not just the summary — the reviewer needs to see *which* episode changed.

### 4.3 The gate

```
PASS iff missed_list = '[]'
     AND suppressed_count <= proposal.expected_suppression   -- pre-registered
     AND every suppressed episode has label.evidence_strength = 3
```

**The gate is vacuous today and must be made non-vacuous before it is trusted.** With 0 unauthorised entries in 30 days (R4:152), "the list of real events it would have missed" is empty for *any* change. So the corpus must include a **synthetic-positive suite**: a door opens with no granted credential, a person is inside while the shop is closed, a door is forced, at every hour × weekday combination, injected into the real signal stream at a timestamp where the surrounding signals are real. The gate then means: *the candidate still fires on every synthetic positive, and suppresses no labelled real episode.* That is weaker than detection — say so in the report, in the same sentence as the pass — but it is not vacuous.

Second gate, cheap and decisive: **mutation check on the diff itself.** If the diff removes a term from a trigger, assert that removing the same term from the *baseline* rule also removes N alarms; if the candidate's improvement does not depend on the removed term, the change is not doing what it claims.

### 4.4 Avoiding overfitting 28 days

Six defences, in order of how much they cost to skip:

1. **Time split.** Tune on days 1–21, test on days 22–28, report both. A threshold that only works on the last week is a fit to the last week.
2. **Leave-one-episode-out.** Re-run 15 times, each with one episode removed. If the chosen threshold moves by more than the band width when any single episode is dropped, it is fitted to that episode.
3. **Plateau, not peak.** Choose the midpoint of the widest interval of thresholds that give the same decisions, and require the plateau to be at least 30 s wide. A peak at the edge of the observed range (e.g. N = 120 s because the largest observed gap was 119 s) is an extrapolation, not a tuning.
4. **Minimum support.** A rule may be changed only with ≥ 5 episodes or ≥ 3 distinct weeks of evidence. Otherwise it is a `note`, not a promotion. With 13 usable episodes, this permits at most two independent changes per quarter.
5. **Pre-register the acceptance numbers** before the replay is run — the design already does this (DD:672-676: ≤ 1 false alarm/week, 100 % of door-without-credential, ≤ 30 s door→page). Write them into the proposal row; a number chosen after seeing the replay is not a criterion.
6. **Re-replay on corpus roll.** The window is 28 days and rolls. When a day leaves the corpus, re-run every promoted rule against the new corpus; if a rule now fails, it rolls back automatically. This is the only defence against a rule that was correct for a month that no longer exists.

One more, specific to this building: **the weekly rhythm is not the same as the weekly schedule.** The shop is closed on different days, Monday arrivals differ, and the 30 h gap sits mid-week (R4:22). Stratify the split by weekday, not by row count, or the test week will contain five Sundays.

---

## 5. Drift and poisoning

### 5.1 Drift: what changes, how it is detected, what it does

| Input | Drift signal (measurable) | Measured example | Action on detection |
|---|---|---|---|
| Camera resolution / encoding | `(width, height, bytes)` fingerprint per entity, weekly | the doorbell has a 2560×1920 stream **and a 640×480 twin**, and the evidence path uses the 640×480 one (DD:438, DD:459-461) | freeze learning for that camera; re-baseline only after a human confirms the new stream |
| Camera identity / role | OSD text and pixels, never the entity name | "Waiting Room" is the drop-off door, "Front Hallway" is the main entrance (DD:444-447); `cam_larry_s_exit_main_2` is "Deserted House Exit" (DD:410-412) | role map keyed by pixel fingerprint; a name change alone does not re-map |
| Camera "present but broken" | `snapshot_count == roster_size` per drill, not `state != unavailable` | a camera returning HTTP 400 is `idle`, passes the `not in ['unknown','unavailable']` guard, writes no file, and the drill "passes" 3 of 4 (W8:184) | fail the drill; never let a drill pass on a count it did not assert |
| Clock | offset vs NTP per camera, every hour | Reolink **~67 min slow**, NVR **~51 min**; one courier run reads 13:21:03 / 13:37:21 / 13:37:26 (DD:456-458) | any offset > 60 s freezes cross-camera features and raises a note; ordering two detections for direction is invalid until fixed |
| Credential roster | `credential.revoked_at` swept at the door, the `input_text` helper and the role map | revocation touching one of three places leaves a working code (DD:540-541) | treat a partial sweep as a security event, not a config task |
| Person ↔ phone | tracker recency and entity id | `device_tracker.monty` = `home` months after the person left (DD:842-848) | phone presence expires after N days without a credential event; a new tracker id is a new feature, not the same person |
| Device re-pair | entity-id fingerprint of every lock/sensor | a replaced deadbolt changes `0x002446…` and **8 call sites silently no-op on a non-existent target** (W8:206) | entity-id diff freezes the affected rules; a missing target is an alarm, not a no-op |
| Backend build | running sha recorded in every decision row | `/opt/company` is 329 files dirty on a different lineage from the repo (H:363-369) | decisions from an unnamed build are excluded from the training set |

The rule that ties them together: **the feature set is versioned, and a change in any input's shape invalidates the model and raises an owner-visible note** (DD:268). "Invalidate" means the replay corpus version changes and every promoted rule is re-replayed — not that the agent silently re-fits.

### 5.2 Poisoning: stopping the agent's own confident mistakes

The failure is concrete: the agent labels a real event `CUSTOMER_ENTRY` because it looked like one, the label is trusted, and the next real customer-shaped intrusion is suppressed (DD:269). Six defences, all cheap:

1. **Provisional by default.** An agent-written label is `status='provisional'` and has `evidence_strength ≤ 2` regardless of its confidence. Only a human confirmation raises it to `confirmed` / strength 3.
2. **Separation of powers.** `security_decision.decided_by` must differ from `security_label.labelled_by` for any automatic label. The agent that decided may not grade itself.
3. **Evidence-class gate.** A label with `DISARM_ONLY`, `PHONE_PRESENCE` or `NONE` is never used to suppress; it is only counted and sampled.
4. **Corrections are new rows.** `supersedes_label_id`; no overwrite. The ghost-worker relabel is the canonical case and must remain visible.
5. **Quarantine.** A proposal derived from any label with `status='provisional'` is held, not replayed. The monthly audit is the release valve.
6. **Confidence is not evidence.** `confidence` is stored for ranking and audit, never summed into a quorum. A confident wrong label and an unconfident right one must not be tradeable.

### 5.3 The human audit sample

- **Monthly**, stratified random: `n = max(20, 10 % of the month's labels)`, plus **100 %** of (a) every label used to suppress a rule, (b) every `UNKNOWN_PERSON_NO_ENTRY` / `NO_ANSWER`, (c) every label written by the agent with no human confirmation, (d) at least one episode per week.
- **Weekly**, a 5-minute spot check of 3 recent events, to catch a systematic error before a month of it accumulates.
- **What the reviewer sees, one page per event:** timestamp; the leaf trigger and the signals that were true; the decision and the one-line page text; the candidate label with its evidence ref (the `entry_event` row, or the snapshot path + sha); three boxes — `agree` / `disagree` / `cannot tell`; and a mandatory evidence-class re-pick. The `cannot tell` box is load-bearing: it produces `NO_ANSWER`, which is a real label (R4:277-299), not a failure to label.
- **Disagreement is a metric.** If the reviewer disagrees with > 10 % of the sample, the month's labels are not used for promotion and the disagreement reasons are appended to the proposal that would have used them.

Twenty events is about twenty minutes. That is the entire ongoing human cost of the loop, and it buys the only ground truth the building will ever have.

---

## 6. The promotion pipeline

### 6.1 What a committed diff looks like

A promotion is a directory and a commit, not a chat message:

```
security/promotions/2026-11-03-doorbell-zone/
  proposal.md        # what, why, the metric, the FROZEN baseline, target, direction, band
  change.diff        # the exact YAML/code diff; applies cleanly to the named base sha
  replay.json        # corpus_version, code_sha, rules_sha, per-episode table, missed_list
  metrics.json       # Class B before/after + Class A invariants, over the named window
  approvals.json     # tier, approver, timestamp, owner line if tier >= 2
  rollback.sh        # one command, tested in staging
```

The commit message carries `proposal_id`, `corpus_version`, `replay_run_id`, and `missed=0`. If any of those is missing, the promotion tool refuses. H's own lesson applies: "every promotion is a committed diff with a replay report attached" (DD:270) and "verify by reading the system back" (H:79-81).

### 6.2 Who may promote

| Tier | Change | Who | Owner? |
|---|---|---|---|
| 0 | logging, retention, dashboards, a new sensor **read** (never a trigger) | security agent, replay not required, one-line record | no |
| 1 | threshold **inside** the pre-approved band (e.g. credential window 60–180 s), page routing, a new corroborating signal | security lead + replay gate + 24 h owner veto window | notified, may veto |
| 2 | **any reduction in firing power**: remove a term, widen beyond band, disable/mute a rule, add an allow-list, change a label policy | security lead + replay gate + **owner's explicit line in `approvals.json`** | **yes, always** |
| 3 | a new action/tool, or a change to `autonomy.py` | owner + a `DEFAULT_MATRIX` entry in the same commit | **yes** |

Tier 2 is the one that matters. The design already says it (DD:270) and the 13-episode history is the argument: every one of those alarms was a Tier C/D signal acting alone (DD:645-646), so "reduce firing power" is the exact shape of every plausible bad change.

### 6.3 The `autonomy.py` interaction — the trap in the pipeline

`app/services/autonomy.py:376-377`:

```python
# Unknown actions default to L4 (autonomous) — bias towards action
return AutonomyLevel.L4_AUTONOMOUS
```

So if the promotion executor is given a new action name — `security_apply_rule`, `security_set_threshold`, `security_disable_zone` — it executes **immediately, with no approval**, because the name is not in `DEFAULT_MATRIX`. The security agent's charter says it "may not edit HA config directly, disable an automation, or silence anything" (DD:181-182), but that is a sentence in a document; `get_level()` is the code that decides.

Three concrete fixes, all required together:

1. **No apply action for the security department at all.** Its allow-list contains `security_propose_change`, `security_record_label`, `security_read_*` only. Promotion is performed by a separate executor identity.
2. **Every new action ships with its matrix row in the same commit**, `default: 1, max: 2` for anything that can change a rule. A CI test asserts that every action in the security allow-list has a `DEFAULT_MATRIX` entry — otherwise the L4 default silently reasserts itself on the next deploy.
3. **The executor's own actions are L2** (`L2_APPROVE`) for tier ≥ 1 and L1 for tier 2, so the approval is enforced by the same code path that gates every other action, not by the pipeline's own logic.

Note also `:482`: `_try_promote` uses `entry.get("max", 2)`, so an unknown action starts at L4 and can never be *promoted* past it — the missing matrix row does not make it safer, it makes it maximally autonomous and then pins it there.

### 6.4 Reverting a bad promotion in one line

Keep `/config/packages` a git checkout of the promotion repo, so the revert is the deploy:

```bash
ssh ha 'cd /config && git revert --no-edit "$(cat .promotion/last)" && ha core restart'
```

For automation-only changes, `ha core restart` can be `ha automation reload`; for template/sensor changes it cannot, because a template sensor's state is rebuilt at start. The `rollback.sh` in the promotion directory is the tested, literal command, and it must be **run once in staging before the promotion is allowed** — an untested rollback is not a rollback.

`evolution_verification.status` already permits `rolled_back` and `snapshot_id` already exists (`evolution_verification` schema; 0 rows used either). Use them: a rollback writes `status='rolled_back'`, `rollback_reason`, and the promotion id, so the next proposal can see that this idea already failed once.

---

## The loop, concretely

### Schemas (six tables, one writer, in the authority DB)

```sql
-- 1. Every signal edge that could matter. Cheap; impossible to reconstruct later.
CREATE TABLE security_event (
  id            TEXT PRIMARY KEY,            -- uuid, stable across retries
  occurred_at   TEXT NOT NULL,               -- to the second, UTC
  entity_id     TEXT NOT NULL,
  domain        TEXT,
  old_state     TEXT,
  new_state     TEXT,
  area          TEXT,
  leaf_trigger  TEXT,                        -- which input actually fired (not the fused zone)
  recorder_gap  INTEGER NOT NULL DEFAULT 0,  -- 1 if the preceding window has a hole
  build_sha     TEXT NOT NULL,
  raw           TEXT                         -- JSON attributes snapshot, no secrets
);
CREATE INDEX ix_event_time ON security_event(occurred_at);

-- 2. One row per alarm: what fired it, what was considered, what was done, why.
CREATE TABLE security_decision (
  id            TEXT PRIMARY KEY,
  event_id      TEXT NOT NULL REFERENCES security_event(id),
  rule_id       TEXT NOT NULL,
  rule_version  TEXT NOT NULL,
  decided_by    TEXT NOT NULL,               -- 'envelope' | 'agent:dept_security'
  considered    TEXT NOT NULL,               -- JSON: signal -> value at decision time
  decision      TEXT NOT NULL CHECK (decision IN ('ALARM','NO_ALARM','SUPPRESSED','ERROR')),
  confidence    REAL,
  page_text     TEXT,                        -- the exact one line that went out
  paged_at      TEXT,
  acked_at      TEXT,
  ack_channel   TEXT,
  build_sha     TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

-- 3. What actually happened. Append-only. This is the training set.
CREATE TABLE security_label ( ... );         -- full DDL in §3.2

-- 4. What was done and by whom: siren, page, call, silence, disarm, drill.
CREATE TABLE security_action (
  id            INTEGER PRIMARY KEY,
  decision_id   TEXT REFERENCES security_decision(id),
  action        TEXT NOT NULL CHECK (action IN
                  ('SIREN_ON','SIREN_OFF','PAGE','CALL','SILENCE','DISARM','DRILL','RETRY')),
  actor         TEXT NOT NULL,               -- 'system' | 'agent:…' | 'human:…' | 'credential:<id>'
  attempted_at  TEXT NOT NULL,
  result        TEXT NOT NULL,               -- 'ok' | 'failed' | 'refused'
  recipient     TEXT,                        -- per recipient, not one row per blast
  error         TEXT
);

-- 5/6. Replay, as in §4.2: replay_run, replay_episode.
```

Plus the three identity tables the design already specifies: `subject`, `credential` (`value_hash`, never plaintext), `entry_event` (append-only, one row per credential event) — DD:514-523.

### The ten steps, in order

0. **Freeze the corpus.** Export 28 days of `states` for the named roster; write the gap list; freeze the 15 episodes with their labels and `corpus_version`. Nothing below works before this exists, and every day without it is a day that cannot be learned from (DD:210-213).
1. **Write the four event tables and the single writer.** One process writes `security_event` / `security_decision` / `security_label` / `security_action`; HA writes none of them directly. Acceptance: every event in a 24 h window has a row, every alarm has a decision row carrying the exact page text (DD:317).
2. **Label the 15 episodes by hand, to the schema in §3.2.** Use the owner's statement to settle the 7 disputed "worker" episodes; record the correction as a new row that supersedes, not an edit. Acceptance: 15 labels, each with a non-`NONE` evidence class or an explicit `NO_ANSWER`.
3. **Build the replay harness and run the *current* rules through it.** The first run is a calibration, not a gate: if it cannot reproduce the 15 known outcomes, the harness is wrong and nothing downstream is trustworthy.
4. **State the acceptance numbers and the metric pair** (§2.2) in the proposal template, before any proposal exists. Freeze them in the template, not in a document.
5. **Run the loop monthly, not continuously.** Proposal → replay → gate → tier decision → promote/rollback. A weekly cadence with 0 positives produces proposals fitted to noise; monthly matches the audit sample and the corpus roll.
6. **Audit 20 labels a month** (§5.3) and publish the disagreement rate next to the false-page rate. A system that reports its accuracy without its audit is reporting a number it cannot defend.
7. **Re-replay every promoted rule when the corpus rolls**, and auto-rollback on failure.
8. **Retire `error_count` as the evolution metric** for anything that is not a code-quality change; keep it only where it is genuinely the target (a change whose purpose is to reduce errors).
9. **Record, weekly, in one line:** false pages, alarms, median armed time, credential coverage, sensor roster alive, labels written, drill pass, replay corpus version. That line is the scorecard; everything else is commentary.

### What must be recorded for learning to be possible at all

The eight fields H/DD name as missing, plus R4's, with the honest status today:

| Field | Exists today? | Source |
|---|---|---|
| event id | **no** | DD:210-213 |
| credential (or its absence) at the event | **no** — `phoenix.valid_pin` never fires | DD:505-506 |
| person inferred, and how | **no** | R4:252 |
| siren start / stop | **partially** — a 255-char rolling string | DD:508; W8:116 |
| page attempt / result per recipient | **no** | DD:210-213; W8:43-49 |
| first human action + channel | **no** — "noticed and ignored" == "nobody noticed" | R4:252 |
| label | **no** — no `security_*` table exists | authority: `sqlite3 … "SELECT name FROM sqlite_master WHERE name LIKE 'security%'"` → 0 rows |
| leaf trigger (not the fused zone) | **no** — `zone_hallway_active` collapsed five inputs | R4:46, R4:299 |
| trigger→arm, arm→entry, arm→credit (seconds) | **no** | R4:266 |
| availability snapshot at trigger | **no** — E5 was invisible | R4:267 |
| canonical `door_id` | **no** — two sensors, same door, 246 same-second edges | R4:270 |
| snapshot manifest (OSD time + mtime) | **no** — they disagree by 67 min | R4:271 |
| `recorder_gap` marker | **no** — a 30 h 41 min hole, unmarked | R4:272 |
| build sha | **no** — `/opt/company` is not the repo | DD:271; H:363-369 |
| disarm as a distinct, weak action | **no** — 13/15 ended by `everyone_away→off`, recorded as nothing | R4:154 |

The design's retention plan is right and should be adopted unchanged: events 90 days, decisions 2 years, **labels forever**, evidence images 30 days with a nightly export — the label and the decision must outlive the image and the logbook (DD:207-208).

---

## Recommendation

1. **Do not build a learner yet.** Build the record first: the four event tables, the single writer, and 15 hand labels. H §6.3-6.4 is the same conclusion from the other direction — `dept_security` has produced no finding and there is nowhere for one to land. A model trained on this month learns "the alarm is a worker-arrival detector with a six-second handicap" (DD:575-578), which is the opposite of what the owner wants.
2. **Adopt the metric pair as a hard gate, not a dashboard.** Class B (`false_pages_per_week`) is the only thing allowed to move; Class A (coverage, latency, drills, labels) is the invariant set. With 0 positives, never report a detection rate; report coverage and the replay gate, in the same sentence (DD:678-681).
3. **Make the disarm a complaint, never evidence.** One rule — a `DISARM_ONLY` label may open a proposal and may never close one; suppression requires a confirmed strength-3 label on every episode it would suppress — prevents the specific unlearning that DD:265 describes and that this month's data already demonstrates seven times (DD:851-860).
4. **Fix the existing loop before extending it.** Three one-line defects make `103/103` possible: the baseline is re-read at verification instead of frozen (`evolution.py:1139-1140`), the verdict passes on equality or timeout (`evolution_verifier.py:400-460`), and the row is not linked to the change (`:1137-1138`). Until those are fixed, any new metric inherits the same non-discrimination.
5. **Gate promotions on a replay whose missed-list is empty, and make the gate non-vacuous with synthetic positives.** Round 18's 13/13 is stale twice over: the labels were corrected (DD:838-866) and the door-edge rule was withdrawn (DD:885-889). Re-run the corrected rules against the corrected labels before trusting any number in that table.
6. **Keep the human in the loop at exactly two points, and no more:** the monthly 20-label audit, and the owner's line for any Tier-2 (firing-power-reducing) change. Everything else — replay, metrics, rollback — should be mechanical, because a loop that needs a human at every step will be skipped, and a loop that needs one at no step will lie.

**The one guard that stops it unlearning the alarm:** *no change may remove or weaken a firing path unless every episode it would suppress carries a confirmed, non-disarm evidence label and the owner's line, and the replay's missed-real list is empty.* A disarm can open that conversation; it can never close it.
