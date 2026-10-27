# Open thread: making the evidence capture non-blocking (and why my first attempt failed)

**State when this was written:** `phoenix_security.yaml` is at sha `885cc460…` — the last version where
evidence capture demonstrably ran (three images at 22:46:10). The non-blocking experiment was **reverted**.
The building is armed; the alarm works; the entry delay is still dominated by the camera chain.

---

## What I was trying to fix

The snapshot chain inside `phoenix_intrusion_initial_response` ran **21 s and was still running at 80 s**
(logbook, 22:46:10 → 22:46:31, with "Latest (with retrieve)" retries after). Because that block is called as a
blocking `service:`, the siren cannot start until the cameras finish — so the "entry delay" is whatever the
cameras decide, not a number anyone chose. CP-01 wants a stated 30 s; today it is unbounded.

## What I tried, and exactly how it failed

Three call sites converted from blocking to `script.turn_on`:

1. `script.phoenix_intrusion_evidence_and_page` — converted, with the variables nested as
   `data: { variables: {...}, detail: ... }`. The `detail` line ended up as a **sibling of `variables` inside
   `data`**, because my rewrite pass moved one key and left the other behind.
2. `script.snapshot_entry_cameras` and `script.snapshot_control_room_cameras` — converted to `script.turn_on`
   but left with `data: { event_name: …, log_message: … }`, and `script.turn_on` has no `event_name` field.

Result at 22:53: `phoenix_intrusion_initial_response` ran and completed, but
`phoenix_intrusion_evidence_and_page`, `snapshot_entry_cameras` and `snapshot_control_room_cameras` all kept
`last_triggered` at 22:46 — **none of them started**. The sequence continued without any evidence capture at
all, and reached neither the page nor the snapshots.

Reverted from `.bak-nonblocking-20261026` within the minute; `ha core check` clean; both domains reloaded;
verified flags off, `everyone_away = on`, siren cap on, keypad handler on.

## What is actually unknown, stated so it is not guessed at

**PARTLY ANSWERED 2026-10-26 22:58Z with a scratch probe script (`zz_probe.yaml`, since removed):**

| Call form | Result |
|---|---|
| `script.zz_probe_var` with `data: {payload: …}` | **HTTP 200**, script started, `last_triggered` set |
| `script.turn_on` with **top-level** `variables: {payload: …}` | **HTTP 200**, script started, `last_triggered` set |
| `script.turn_on` with `data: { variables: {payload: …} }` | **HTTP 400 Bad Request** |

**So the nested form I deployed in the failed attempt is rejected outright** — that is exactly why the callee's
`last_triggered` never moved. The correct form for `script.turn_on` on this HA version is `variables` as a
**top-level key of the service data**, not inside `data:`.

**Still unknown:** the probe's own `logbook.log` step produced no entry in `/api/logbook` and no error in
`/api/error_log`, so I could not confirm that the *value* arrived — only that the script started. Before relying
on it, verify the value reaches the script (e.g. have the probe fire an `input_text.set_value` instead of a
logbook line, which is observable as state).

- Whether those snapshot scripts read their parameters as `fields` (service data) or as plain template variables
  is still unread, and the `turn_on` conversion still depends on knowing it.
- Whether the evidence script would still page correctly if started with `turn_on` — the page is inside it, and
  the page is the safety-critical path.

## The safe way to settle it (next session, ~15 minutes)

1. Add a **scratch package** `packages/zz_probe.yaml` containing one script that does nothing but
   `logbook.log` a variable it was given, and a second that logs a field it was given.
2. Call the first three ways — as `script.zz_probe_var` with `data:`, as `script.turn_on` with `data.variables`,
   and as `script.turn_on` with a step-level `variables:` — and read the logbook for each.
3. Call the second the same way to learn the field/variable distinction.
4. Only then convert the real calls, one at a time, drilling after each and checking `last_triggered` on the
   callee — the cheapest evidence that a call happened at all.
5. Remove the scratch package.

**Do not convert all three call sites in one deploy again.** Two unverified deploys in a row is what turned a
timing problem into a missing-evidence problem for four minutes on a live alarm.

## The alternative, if `turn_on` proves awkward

Move the entry delay and the siren **above** the snapshot block, so the siren is 30 s from the door edge by
construction, and let the evidence capture run after it. The cost is honest and small: the intruder hears the
siren before the last frames are taken, so the pictures are of someone leaving rather than arriving. That is a
trade to make explicitly, not by accident — and it needs no new HA mechanics at all.
