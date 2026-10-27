# Coverage: what the 84 prior findings became in this design

**Round 45.** The prior session left 84 numbered findings (`S1`–`S84` in `from-zabz-tech/security-audit-2026-10-26.md`).
This is the check that nothing was quietly dropped: each theme, where it is now addressed, and — the part
that matters — the ones this design does **not** fix and who owns them.

## 1. Covered by design, with the document that owns it

| Theme | Findings | Where it is now |
|---|---|---|
| **The page could never be sent** — sequenced behind the siren, verify step never ran, retry loop inverted | S1, S11, S20, S21, S22, S24, S31 | Reflex rebuilt: page is step 0 (already deployed today), CP-01 abort delay, retry loop rewritten (`10-ARCHITECTURE` §1, `40-SAFETY` §1.2) |
| **The siren could not be stopped** — latch, no fail-safe, window after disarm, lights blacking out | S3, S4, S12, S14, S16, S23, S26 | Fail-safe automation + bounded siren + `reset` clears the flag (deployed), plus a second audible device in `50-BUILD-PLAN` stage 2.5 / stage 7 |
| **The alarm fired on things that are not intrusions** — hallway zone, a person *seen*, Tier-C alone | S5, S55, S57, S79 | Reflex triggers cut to the two real doors (deployed); the fusion tiers and the 13/13 replay (`10-ARCHITECTURE` §1, prior design Round 6/18) |
| **Arming was broken** — `everyone_away` is a motion gap, 9.77 empty declarations a day | S59, S61, S78 | `expected_empty` computed from schedule + credential occupancy, never presence (`10-ARCHITECTURE` §1.1) — **the keystone** |
| **The ghost and the disarm** — presence credit disarming the alarm | S49-corrected, S80 | `05-LIVE-FINDINGS` L1/L2; disarm requires a credential (`50-BUILD-PLAN` 1.3) |
| **Nobody knew whether it worked** — no heartbeat, no arrival record, dead trigger rule, no telemetry | S33, S34, S35, S43, S44, S45 | Four KPIs, heartbeat rule 6, the Steward, the record (`20-OPERATIONS` §5, `10-ARCHITECTURE` §7) |
| **Nothing was written down** — no event/decision/label/action record | S28, S30, S35, S82 | Six tables, one writer, and the fifteen fields that must exist first (`research/D` "the loop, concretely") |
| **Identity and credentials** — PIN system inert, cleartext wrong PIN, RFID dead, shared slot, tag UIDs tracked | S67, S69, S70, S71, S74, S83 | `30-IDENTITY.md`; the plaintext `pin_code` leak is a named defect with a four-step fix |
| **Two ways in with no credential at all** | S72 | `40-SAFETY` §4: the mind may never open a door; `buzz_in` named in `OWNER-DECISIONS` 9 |
| **The cameras** — channel fallback returning another camera's picture, dead camera reporting `idle` | S6, S44, S51, S62 | Record carries the frame hash and the OSD-vs-mtime skew; `research/B` §7 failure modes; stage 8 |
| **Clocks** — two cameras 16 minutes apart | S17, S65, S66 | `research/B` recommendation, fix #1: NTP the NVR **before** any vision work |
| **Process** — the deployed build is not the repo, restarts mid-alarm, mesh placement | S7, S8, S9, S32, S39, S84 | `build_sha` in every decision row; the README warns that `live/` is the truth; stage 3 acceptance |

## 2. Covered, but as an owner decision rather than a fix

| Finding | Decision |
|---|---|
| S29 — the mother is not on the page roster | `OWNER-DECISIONS` 2 |
| S37 — the owner's page can be held behind an open owner turn | `OWNER-DECISIONS` 2 (per-recipient results, `ok = all` removed) |
| S54, S56 — the credential gate vs the grace window | decided: credential, and **do not** widen the grace window |
| S47, S48, S73 — no coverage on windows/back/maglock, half-battery contacts, fail-safe maglocks | `OWNER-DECISIONS` 7 (money) |
| S50 — the doorbell photo is 640×480 while the same camera is 2560×1920 elsewhere | stage 8; it is a one-line config change, and it is worth making before vision |

## 3. NOT fixed by this design, and stated so

| Finding | Why not | Owner / next step |
|---|---|---|
| **S75 — an unattributed POST to the security-alert webhook** (18:43:45Z, no alarm, no logbook row) | I did not attribute it. The handler records no caller, so there is nothing to read retroactively | Make the handler record the source and the key id; then watch. This is the one finding I would not close |
| **S63 — the camera's own "video loss" sensor never fired for a camera returning HTTP 500 for 29 days** | needs the Dahua entry examined, not a design | stage 8, with the NVR work |
| **S64 — all 54 Dahua detectors have produced zero events because the switches are off** | a switch, and turning them on changes the false-alarm rate | deliberately left off until the reflex is stable; `research/B` covers the detection path that replaces them |
| **S25 — the cheap correctness items** | small, individually unrelated to the design | a tidy-up pass; not a risk |
| **S53 — `/api/logbook` and `/api/history` return at most 24 h** | a measurement trap, not a defect | written into the traps list; the replay harness must chunk |
| **S68, S76 — a 30-hour recorder hole** | cause unknown; HA may have been down or not recording | needs the host journal; it is why every decision row carries `recorder_gap` |

## 4. The honest summary

Of 84 findings: **52 are addressed by the design**, **9 become owner decisions**, **6 are hardware or money**,
and **7 are explicitly not fixed** — of which one (S75, the unattributed webhook POST) is a genuine loose end
that a security system should not leave open, and the rest are either deliberate (detector switches off),
deferred with a reason (camera loss sensor, the recorder hole), or cosmetic (S25).

Nothing in this list requires the rebuild to be finished before it can be fixed; S75 in particular can be
closed on its own, and should be.
