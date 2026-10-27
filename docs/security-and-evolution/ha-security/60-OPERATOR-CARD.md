# Operator card — what to do tonight, before the rebuild

One page, for the period between now and stage 3. It assumes the system is the one measured in
`05-LIVE-FINDINGS.md`, not the design.

---

## Is the building armed right now?

Three entities, in this order. **All three must be:** `everyone_away = on`, `intrusion_active = off`,
and `worker_is_here = off` **plus** `user_is_here = off`.

| Reads | Meaning | What to do |
|---|---|---|
| `worker_is_here = on` while the room is empty | the ghost has latched it; the building **is not armed** and will not arm | turn `input_boolean.phoenix_worker_is_here` off, then confirm `everyone_away` flipped to `on` |
| `everyone_away = on`, `intrusion_active = off` | armed correctly | nothing |
| `intrusion_active = on` | an alarm is live | see below |

## The siren is sounding

1. **Silence it first** — `script.phoenix_intrusion_reset`. That single action now clears the alarm flag,
   posts the Mac-mini siren off three times, and restores the lights. It used to leave the strobe running.
2. **If the Mac mini is unreachable**, the siren is a latch in a separate Python listener. It has no
   timeout. `POST http://192.168.50.45:8128/alarm/off` is the only thing that clears it.
3. **Then read what fired**: `input_boolean.phoenix_intrusion_active` and the logbook entry, and the
   entity that opened — the trigger list is now only the apartment door and the shop door.
4. **Assume nothing about the page.** No intrusion page has ever been delivered
   (`sms_log`: 4,507 sends, 0 with `LPT-SECURITY`). If it mattered, tell someone yourself.

## A drill

- Turn on `input_boolean.phoenix_intrusion_test_mode` **first**. It suppresses lights, siren and overhead
  audio, and changes the page event to `intrusion_test`, which the company skips.
- **Turn it off afterwards, by hand.** Nothing in any YAML clears it (finding S40). Leaving it on means the
  next real alarm is silent — the worst state the system can be in, because it looks armed.
- Check `PHOENIX_EVIDENCE_OK` afterwards: `POST /api/services/shell_command/phoenix_verify_evidence_files?return_response`.
  It returns in about a second, changes no state, and proves the evidence path still writes files.

## What not to do

- **Do not walk in to check whether the alarm works.** Walking in disarms it — that is the defect, not the
  test.
- **Do not restart Home Assistant on a hunch.** A restart flaps entity availability, and one historical
  episode was six sensors going unavailable and restoring four times in three minutes, each one re-arming.
  If you restart, check `intrusion_active` afterwards.
- **Do not trust `last_triggered`** as history: it resets on every restart, and there were eight restarts
  in 28 days.
- **Do not judge a camera by its entity state.** A Dahua camera can report `idle` and fail every snapshot.
  The only proof is a file on disk — which is what the verify command above does.

## The one number to remember

The building's alarm currently disarms itself for anyone who walks in, because a departed worker's GPS
tracker still reports `home` and presence credit clears the alarm. Until stage 1.3 of `50-BUILD-PLAN.md`
lands, **treat the alarm as a loud notification, not as protection** — and say so to anyone who asks.
