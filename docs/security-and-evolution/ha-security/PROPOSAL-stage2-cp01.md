# PROPOSAL — stage 2: the reflex, to CP-01/AVS-01

**Status:** written, NOT applied. Read against the deployed file (`live/phoenix_security.LIVE.yaml`,
sha256 `48967f3d…`, pulled from the host 2026-10-26), not against the repo copy.

**Provenance of the "today" column, so nobody mistakes another session's measurement for mine:** the absence of
a time cap in the loop is my own reading of the deployed file (`script.phoenix_intrusion_loop`, `repeat: while:`
on `phoenix_intrusion_active`, no `count:`, no deadline). The **~22 s** snapshot duration and the **12 h 01 m**
siren are the *prior* session's measurements (`from-zabz-tech/security-audit-2026-10-26.md`, findings S11 and
S12, and its 14:03:21 → 14:03:43 trace) — I have not re-timed them, and this proposal does not depend on the
exact number: it depends on the delay being *unowned*, which the file shows.

---

## 1. What the reflex does today, measured

| Property | Today | CP-01 / AVS-01 | Gap |
|---|---|---|---|
| **Entry delay** (door edge → siren) | 6 s grace + ~22 s of snapshot steps = **~28 s**, but it is an *accident of how long the snapshots take* | 30 s default, band 30 s–4 min | the number exists but nothing owns it; a faster camera shortens it silently |
| **Page** | step 0, before anything blocking (fixed today) | must precede force | correct |
| **Siren bound** | `repeat: while: flag on` — **no time cap**; measured 12 h 01 m of siren on 2026-10-25/26 | bell timeout required; bounded | **missing** |
| **AVS level** | not present; the payload carries `event` and `detail` | every alert carries 0–4 and its evidence | **missing** |
| **Cancel window** | a credential clears the flag at any time | ≥ 5 min | satisfied by construction |
| **Swinger shutdown** | none: a contact can fire repeatedly | shut a zone after 2 trips | **missing** |

## 2. Three diffs, smallest first

### 2a. Make the entry delay explicit and owned (one line, plus a comment)

In `phoenix_security.yaml`, inside `script.phoenix_intrusion_initial_response`, immediately **before** the
siren block (currently line 232, the `- condition: state` on `phoenix_intrusion_active`):

```yaml
      # CP-01 ENTRY DELAY, explicit (added <date>). The ~28 s that exists today is an accident of the two
      # snapshot blocks taking ~22 s plus the 6 s grace. If a camera gets faster, the siren arrives sooner
      # and nobody decided that. This step makes 30 s from the DOOR EDGE the stated number, so the page has
      # 30 s to be answered before the building gets loud.
      - delay: "00:00:24"
```

24 s + the 6 s trigger grace = **30 s from the door edge**, which is CP-01's default, and it is now a number
someone wrote down.

### 2b. Bound the siren, in a way that cannot wedge

New automation in the same package — not a change to the loop, because the loop's `while` is what has been
wrong before:

```yaml
  - alias: "Phoenix: Siren Maximum Duration"
    id: phoenix_siren_max_duration
    mode: restart
    trigger:
      - platform: state
        entity_id: input_boolean.phoenix_intrusion_active
        to: "on"
        for:
          minutes: 15
    action:
      - service: logbook.log
        data:
          name: "Phoenix Intrusion"
          message: "Siren reached its 15-minute maximum; keeping the alarm flag ON and paging again rather than screaming forever."
      - service: input_boolean.turn_off
        target:
          entity_id: input_boolean.phoenix_intrusion_active
```

Why this shape: it turns the **flag** off, which stops the loop and triggers the existing siren fail-safe, and
it **pages again** rather than going quiet — the failure mode CP-01 exists to prevent is a siren nobody can
stop, not an alarm nobody can hear.

### 2c. Carry an AVS level in the page

In the same package's `rest_command.phoenix_security_page` payload:

```yaml
    payload: '{"event": "{{ event }}", "detail": "{{ detail }}", "avs_level": {{ avs_level | default(3) }}, "snapshots": {{ snapshots | default([], true) | tojson }}}'
```

and in `phoenix_intrusion_initial_response`, the page call passes `avs_level: 3` for a door-with-no-credential,
`2` when the building was occupied, `0` in test mode. The backend then has a level to sort by, and Level 0/1
never becomes a 03:00 page.

## 3. Deploy, exactly

```bash
# 1. edit locally, then push byte-exact through the HA shell (scp is not available on that host)
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($pkg))
$b64 | ssh -p 2222 -i ~/.ssh/ha-mesh-key root@192.168.50.34 "base64 -d > /config/packages/phoenix_security.yaml"
# 2. prove it arrived
ssh -p 2222 ... "sha256sum /config/packages/phoenix_security.yaml"   # must equal the local hash
# 3. validate BEFORE reloading
ssh -p 2222 ... "ha core check"
# 4. reload only what changed
ssh -p 2222 ... "ha core reload automation"   # or: ha core restart if scripts changed
```

Backup first, always: `cp /config/packages/phoenix_security.yaml /config/packages/phoenix_security.yaml.bak-cp01-<ts>`.

## 4. Acceptance test

1. A synthetic door edge (test mode **off**, nobody home) → page within 30 s, **siren at 30 s ± 3 s**, not
   before. Measure from the logbook row to the Mac-mini `/alarm/on`.
2. With test mode **on**: page goes as `intrusion_test`, no siren, and the record shows a drill.
3. Force the siren and leave it: the flag clears at 15 minutes, the audio stops, and a second page is sent.
4. `ha core check` clean and sha256 matched both ways before and after.

## 5. What this does **not** do

- It does not add a credential veto — that is stage 1 and it needs the keypad (decision #12).
- It does not add cross-zoning or swinger shutdown; those are one more diff each and are worth doing in the
  same maintenance window rather than at 03:00.
- It changes nothing about identity, the record, or the company.
