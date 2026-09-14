# IN FLIGHT — work that is open right now

Updated: 2026-09-14 (HA estate, ZABZ-TECH session H93)
Rewritten, not appended. An item leaves this file by being finished (a `log/handoff/` entry) or by
becoming a `state/open-pain.md` row.
## Mine, being worked

| Item | Where | Next concrete step |
|---|---|---|
| Pin Git's `ssh.exe` ahead of the broken Windows one | `harness-config` | `C:\Program Files\OpenSSH\ssh.exe` hangs after every remote command *while still printing output*, so a timeout reads as a short answer (L232). Until pinned, treat any timed-out remote read as an unread surface. |
| The retired Keymaster generation | HA host + `ha-config/docs/DISPOSAL-PLAN-2026-09-11-dead-generations.md` | 82 unavailable automations, 41 entities, the `_2` twins. Disposal pass, provable delete by delete; until then every count from that estate is inflated (P76). |
| The journal rebuild itself | this tree | Import the flat files until they go quiet (`journal.py import-flat`), then retire them completely. |
| Kosher filter: audit ledger for third-party verdicts | `kosher-filter-ai` (`decisions/36`, research `022` §1) | Append a decisions row on every human review instead of updating in place, so per-provider accuracy becomes computable. Then the dry-run mode (D36-10). |
| Kosher filter: browsing escalation route | `kosher-filter-ai` | `escalateToServerThreshold` is read by nothing; every `Decision.ESCALATE` still ends as block/cover. |
| Search index | `harness-config/scripts/fsearch.py` | Recorded 45.34 s → 0.075 s; re-measure after any index change. |
| Bound the camera scripts' internal retries | HA `packages/phoenix_snapshot_cameras.yaml` | ~500 failed NVR logins/hour is probably keeping the NVR account locked out and hiding whether the stored password is even wrong (P75). Do it *after* the owner answers queue #23, so the two causes are not confused. |
| The HA version backlog | HA host, measured 2026-09-14 | Core **2025.10.3** -> 2026.9.2, Zigbee2MQTT 2.6.2 -> 2.14.1, ESPHome 2025.10.2 -> 2026.8.2, nut 0.16.1 -> 0.18.1, configurator 5.8.0 -> 6.1.0. Not a chore: a year of Core upgrades on a live security system needs a rollback plan, and the newest full backup on that host is **2026-05-11**. Mine to plan into a yes/no; his to accept the risk. |
| The phone's gate died once, unexplained (P59) | cadence cut to `*/2`; evidence in the entry | Record the gate's exit status in a wrapper, and give it a heartbeat the probe alarms on a *gap* from — absence, not current state. |
| A first phone run lands with no session (P46) | `assets/mobile.css` and `plugin-mobile` are done | Read the workspace controller's client half, then seed a default session the way `plugin-windows` clears `dsh.sessions.current`. |

## Mine, waiting on a measurement before I claim it

| Item | What would settle it |
|---|---|
| Whether the open-pain list is really 58 live problems | Nothing in the record marks old entries done; only 1 of 59 carries a completion marker. `journal.py resolve <id> --status done --why ...` is now the way to say so, and every closure needs its evidence. |
| Per-machine journal divergence | `journal.py check` warns when a flat file holds entries the log lacks, and `audit` proves a merge lost nothing. It already found three entries written on `ZABZ-TECH` that existed nowhere else (L185, L186, D58). |

## His, queued (see `state/owner-questions.md`)

**HA queue #23 (high)** — the Dahua NVR rejects the credentials HA holds, so the six camera
snapshots and the timeline clips have all been failing. Needs him to log into the NVR and confirm
or reset the admin password. Recommendation is recorded on the row.

**HA, physical, no decision needed** — two of three Zigbee door contacts are off the mesh since the
2026-09-13 21:49 ET host reboot (last batteries 21% and 8%). Replace the cells and re-pair while he
is in the office.

## Broken, as last measured

- The camera evidence half of the intrusion response (P75): 535 of the loudest log errors, one
  credential.
- The company has delivered nothing to the owner since 2026-07-19 while its sensors fired into a dead
  channel (**P55**, measured 2026-09-14: 296 `held`, 2 `queued`, newest `sent` 2026-07-19T02:32Z).
  The SMS kill-switch is his decision and is being honoured. The replacement channel is his to choose;
  nothing outbound is sent without his explicit word.

## MUST BE UNDONE — changes made live that are still in place

**These are deliberate and temporary. Nothing else in this file is an outstanding live change.**

1. **The six Dahua config entries are DISABLED** (`disabled_by: user`, done ~12:29 ET) so the NVR
   would stop being sent failed logins. The owner's 6 camera entities are therefore
   `unavailable`, and `ha_truth.py` is *correctly* reporting them as a degraded security
   integration. **Re-enable all six** once the lockout question is settled. Entry ids are in
   `ha-config/_scratch/dahua_entry_ids.json`; re-enable via the WebSocket
   `config_entries/disable` counterpart used to disable them.
2. **Three automations are OFF** (via `automation.turn_off`, ~13:12 ET) so the RTSP clip path
   stopped authenticating to the same NVR account during the lockout test:
   - `automation.timeline_person_at_doorbell_clips_regen`
   - `automation.timeline_front_door_activity_clips_regen`
   - `automation.timeline_periodic_regeneration`

   **Turn all three back on.** `automation.turn_off` is not restored by a restart unless the
   automation has `initial_state: true`; do not assume it self-heals.

**Why they are listed here rather than left to memory:** I disabled one path to the NVR, called
the result quiet, and drew a wrong conclusion from it (L248). Leaving live changes unrecorded is
the same failure one step further on.


- UPS monitoring on the HA host (W48) — the `nut` app's password was in HaveIBeenPwned, so it never
  listened on 3493 and HA reported a connection failure three layers away from the cause.
- The false `SECURITY_INTEGRATION_DEGRADED — zha` CRITICAL that fired every 30 minutes for three days
  about a discovery dismissed in 2025 (L230, D85).

## Fixed this session, so it is not re-opened
