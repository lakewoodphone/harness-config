# W1 — Adversarial review of the three Phoenix fixes (commit eb57dd8)

**LOCAL (zabz-tech)** — every fact below was read in this session on `ZABZ-TECH` (Windows, PowerShell) from the working tree at `C:\Users\ezabz\code\ha-config`, from the live HA REST API (GET only), or from the Home Assistant source at tag `2025.10.3` (the version the host reports running). Nothing was edited, no HA service was called.

## STEP 0 — identity of what I reviewed

```
C:\Users\ezabz\Code
exists_sec=True   exists_evi=True
h1=e6b45f6b1c04   (phoenix_security.yaml)
h2=6ff9a7142d0d   (phoenix_intrusion_evidence.yaml)
```
Both match the expected values, so this is **not** a revision mismatch. `git show eb57dd8` = `security(phoenix): make the evidence verify+prune commands actually run, and stop the siren after a disarm`, 2 files, +47 / -7.

Live facts used below: `GET /api/config` → `{"version":"2025.10.3", "config_dir":"/config", "time_zone":"America/New_York"}`. `GET /api/states/...` → `automation.phoenix_extreme_intrusion_trigger last_triggered=10/26/2026 2:03:15 PM`, `automation.phoenix_extreme_intrusion_disarm last_triggered=2:03:29 PM`, `script.phoenix_intrusion_loop last_triggered=2:03:43 PM`, `script.phoenix_intrusion_evidence_and_page last_triggered=2:16:35 PM state=off mode=queued`, `input_boolean.phoenix_intrusion_active state=off changed=2:17:21 PM`, `binary_sensor.phoenix_everyone_away state=off`, `input_text.phoenix_door_activity_log` exists, and all four roster cameras (`video_doorbell_fluent`, `cam_front_hallway_main`, `cam_deserted_interior_main`, `cam_larry_s_interior_main`) exist and are `idle`.

---

## 1. FATAL — the new retry loop runs backwards: it re-sends the page while it is succeeding and aborts the script the moment it fails

`phoenix_intrusion_evidence.yaml:329-351` is `repeat: count: 4` whose body ends with

```yaml
                - if:
                    - condition: template
                      value_template: >-
                        {{ not (page_result is mapping and ... and (page_result.get('content') | default({}, true)).get('ok')) }}
                  then:
                    - stop: "page not confirmed - retrying"
```

`stop` inside a `repeat` ends the **entire script**, and it is recorded as a *finished* run, not an error. Proof, HA 2025.10.3 `homeassistant/helpers/script.py`: `_prep_repeat_script` builds the loop body as a sub-script with `top_level=False` (lines 1870-1884); the sub-script run does `except _StopScript as err:` → `script_execution_set("finished")` (line 470, 462) → `# Let the _StopScript bubble up if this is a sub-script` (line 473) → re-raised into the parent, which catches it the same way and ends. There is no `break`, and the count loop (`for iteration in range(1, count + 1)`) has no other exit.

Two consequences, both live now:

- **Every failure is silent again.** `stop` fires exactly when the page is *not* confirmed, so iterations 2-4 never happen (max 2 attempts, not 5), and everything after the loop is skipped — the fail-loud `persistent_notification.create` (lines 356-380), the `logbook.log` audit line (387-391) and the prune (392-393). The script reports `finished` (line 462), so there is not even an error state. This is the same "0 SMS, nothing visible in HA" class the commit was fixing, reintroduced one step later.
- **Duplicate pages when it works.** If a retry *succeeds*, the `if` is false, no `stop`, and the loop keeps iterating: iterations 2, 3 and 4 send the same page again. Worst case 1 initial + 4 = **5 SMS+MMS to every roster recipient per intrusion**, and `phoenix_intrusion_evidence_and_page` is `mode: queued, max: 5` (lines 96-97), so 5 queued intrusions can produce 25 sends.

Smallest fix — use the loop primitive that ends the *loop* instead of the script, and delete the `stop` entirely:

```yaml
      - repeat:
          while:
            - condition: template
              value_template: >-
                {{ not (page_result is mapping and page_result is not none
                        and (page_result.get('status') | int(0)) < 400
                        and (page_result.get('content') is mapping)
                        and page_result.get('content').get('ok')) }}
            - condition: template
              value_template: "{{ attempts < 4 }}"
          sequence:
            - variables: {attempts: "{{ attempts + 1 }}", page_result: {}}
            - delay: {seconds: 12}
            - service: rest_command.phoenix_security_page
              ...
```
A `while` condition that goes false ends the loop normally and does not abort the sequence, so the notification, the audit line and the prune stay reachable.

## 2. FATAL — the new condition silences the *page*, not just the siren, and the disarm it trusts has non-credential triggers

`phoenix_security.yaml:180-182` aborts the sequence **before** the page at `:209`:

```yaml
      - condition: state
        entity_id: input_boolean.phoenix_intrusion_active
        state: "on"
```

The disarm that clears that flag (`:82-96`):

```yaml
  - alias: "Phoenix: Extreme Intrusion Disarm"
    trigger:
      - platform: event
        event_type: phoenix.valid_pin
      - platform: state
        entity_id: binary_sensor.phoenix_everyone_away
        to: "off"
    action:
      - service: input_boolean.turn_off
        target:
          entity_id: input_boolean.phoenix_intrusion_active
      - service: script.phoenix_intrusion_reset
```

So the flag goes off on **any** `phoenix.valid_pin` event (family, worker, guest, or a coerced PIN at the keypad) **and** on any transition of `binary_sensor.phoenix_everyone_away` to off, which the template at `:12-15` makes true when *any one* of `phoenix_user_is_here`, `phoenix_worker_is_here` or `phoenix_house_guest_mode_active` turns on. One of those writers needs no credential at all — `packages/presence_architecture.yaml:287-313`:

```yaml
  - id: phoenix_passive_arrival_bluetooth_worker
    alias: "Phoenix: Passive Arrival (Montrose Phone + Room Occupied)"
    trigger:
      - platform: state
        entity_id: binary_sensor.zone_control_room_occupied
        to: 'on'
    condition:
      - condition: state
        entity_id: device_tracker.monty
        state: 'home'
      ...
    action:
      - service: input_boolean.turn_on
        target:
          entity_id: input_boolean.phoenix_worker_is_here
```

The discriminator between "a worker arrived" and "someone is in the control room" is *a phone being on the premises*. A phone left charging inside, a stale `device_tracker.monty`, or the phone arriving with the intruder all produce the same signal — and it is the same physical event that trips the intrusion trigger. Combined with the 6 s grace delay (`:69-78`) and the ~22 s of snapshot work before the siren step, any such credit inside that window now suppresses **siren, loop and page**.

This is not hypothetical: it is the measured 14:03 event the commit itself cites (`:166-179`), whose own words are "14:03:29 passive arrival credited (Montrose phone + control room occupied)". I confirmed the timing live: trigger 2:03:15 PM, disarm 2:03:29 PM, loop (siren) 2:03:43 PM. Under the new file that same event would now produce **no siren and no page** — and the owner would be told nothing. If that event had been a burglary with a worker's phone still inside, nobody would be paged.

Secondary loss in the same path: the evidence is still captured at `:125-138` but the sequence aborts before `phoenix_intrusion_evidence_and_page`, so the files are never verified, never named in the payload, and the `captured N image(s)` audit line never runs. Evidence exists on disk with no log entry, and the prune never runs (see finding 7).

Smallest fix: keep the abort for the noisy half, move the page **above** the condition. A page on a false alarm costs one SMS; a real intrusion that pages nobody costs the business. Concretely: call `script.phoenix_intrusion_evidence_and_page` between the snapshot block and the condition, and leave the condition guarding only `rest_command.phoenix_alarm_mac_on` / `script.phoenix_intrusion_loop`.

## 3. SEVERE — the abort path still has a window where the siren sticks: nothing re-checks the flag after `phoenix_alarm_mac_on`

`:184-189`:

```yaml
      - if:
          - condition: template
            value_template: "{{ not test_mode }}"
        then:
          - service: rest_command.phoenix_alarm_mac_on
          - service: script.phoenix_intrusion_loop
```

`phoenix_alarm_mac_on` is an HTTP POST with `timeout: 5` (`packages/secretary.yaml:37-40`). If the disarm lands *after* the condition at `:180` passes but *before/while* that call is in flight, the sequence still switches the Mac overhead alarm on — while `phoenix_intrusion_reset` (which ran at disarm, `:249-258`, calling `phoenix_alarm_mac_off`) has already been and gone. Then `script.phoenix_intrusion_loop` starts with the flag already off: its `repeat while` (`:219-224`) is false on the first evaluation, the loop exits immediately, and it never calls `phoenix_alarm_mac_off`. Result: the original 14:03:43 defect, ~5 s wide instead of 22 s.

Smallest fix: re-check immediately after the call, e.g.

```yaml
          - service: rest_command.phoenix_alarm_mac_on
          - if:
              - condition: state
                entity_id: input_boolean.phoenix_intrusion_active
                state: "off"
            then:
              - service: rest_command.phoenix_alarm_mac_off
```
and add `rest_command.phoenix_alarm_mac_off` as the last step of `phoenix_intrusion_loop` so the loop can never exit leaving audio on.

## 4. SEVERE — the page is judged on `ok` alone: a page with no picture counts as success, and a non-JSON 2xx kills the fail-loud path before it runs

The success predicate (`:322-327`) only tests `status < 400` and `content.ok`. The backend's own contract (`personal-secretary-mvp/app/main.py:8547-8564`) is explicit that `ok` "means the SMS was sent, NOT that the picture was attached", and `main.py:8669-8678` returns `ok` and `media_ok` as independent fields. So the defect this file exists to fix — "the owner's SMS said Extreme intrusion and carried NO picture" (`phoenix_intrusion_evidence.yaml:4`) — can recur with `ok: true`, no retry, no notification, and a cheerful `captured N image(s)` audit line.

Second, sharper half: `rest_command` in 2025.10.3 parses `_content = await response.json()` **only** when `response.content_type == "application/json"`, else `_content = await response.text()`. So any 2xx that is not JSON (proxy/CDN interstitial, a NextAuth sign-in page, a WAF page) leaves `page_result['content']` a **string**, and `(page_result.get('content') | default({}, true)).get('ok')` raises `'str' object has no attribute 'get'` inside an `if` condition. That is not caught (no `continue_on_error` on a condition), so the script fails there and the `persistent_notification` at `:363-373` is never created — again silently, in a different place.

Smallest fix, for both halves: test the type before calling `.get`, and treat `media_ok` as a visible (non-retryable) failure:

```yaml
          - condition: template
            value_template: >-
              {% set c = page_result.get('content') if page_result is mapping else none %}
              {{ not (page_result is mapping and page_result is not none
                      and (page_result.get('status') | int(0)) < 400
                      and c is mapping and c.get('ok')) }}
```
plus, after the page settles, a `logbook.log`/notification when `c.get('media_ok')` is false ("paged, but with no picture — <media_error>").

## 5. MODERATE — `bash` is an unverified runtime dependency, and if it is missing the failure is byte-for-byte the one just fixed

Both shell_commands now depend on `bash` existing on the HA container's PATH: `phoenix_intrusion_evidence.yaml:59-60` and `:89-90`. HA 2025.10.3 `shell_command/__init__.py` splits the command as `[prog, *shlex.split(rendered_args)]` and calls `create_subprocess_exec` — `argv[0]` is looked up on PATH by `execvp`, so a missing `bash` raises `FileNotFoundError: [Errno 2] No such file or directory: 'bash'` from inside the service, exactly as `'for'` did, and (per this file's own comment at `:55`) that aborts the script before the page.

Evidence that it is probably present: `home-assistant/docker-base`, `alpine/Dockerfile`, final stage does `apk add ... bash ... tzdata`. I did **not** verify `bash` on the running container (that needs a command executed on the host, which this review is not allowed to do). Note also this same code path shows the fix is *robust* to the mechanism change you asked about: the shell/exec choice is `if rendered_args == args` — a command with no template runs under `create_subprocess_shell`, one with a template runs under `create_subprocess_exec`, and `bash -c '...'` works under both. What breaks under neither is the dependency itself.

Smallest fix: use `sh -c` instead of `bash -c`. Nothing in either command needs bash — `[ -s ]`, `find`, `sort`, `tail`, `while read` are all POSIX, and `sh` is BusyBox, which is guaranteed present (the file itself documents BusyBox 1.37 on this host).

## 6. MODERATE — `-mtime +14` deletes older than **15** days, not 14, and the prose in the same file says 14

`:63` "delete anything older than 14 days" vs `:90` `-mtime +14`. `find` compares the *truncated* 24-hour age: `+n` matches when `floor(age_days) > n`, so `+14` matches files of 15 days and older; the 14-day-old file survives. Retention is one day looser than documented, in a file whose comments are the only specification this system has. Smallest fix: `-mtime +13` (keep the comment) or change the comment to "15 days" (change nothing else).

## 7. MODERATE — retention is not retention: the count cap only sees files older than a day, and the whole prune is hostage to a completed page

`:90` second command: `find ... -mtime +0 | sort -r | tail -n +121 | while read -r f; do rm -f "$f"; done`.

- `-mtime +0` means `floor(age_days) > 0`, i.e. **24 hours or older**. So "keep only the newest 120 files" (`:64`) is really "keep the newest 120 files that are at least a day old". A burst that writes more than 120 files inside 24 h (15 intrusions x 8 images) is not capped at all, and today's files are invisible to the cap. The stated ceiling (`:69-71`) is therefore not enforced.
- The prune is the last step of `phoenix_intrusion_evidence_and_page` (`:392`) and has no other caller — `grep -n phoenix_prune_intrusion_evidence` over `config/` returns only the definition (`:89`) and that one call (`:392`). So retention only runs when a page run *reaches* the end. With finding 1 (`stop` on failure) and finding 2 (condition abort), a failed or disarmed alarm prunes nothing, indefinitely.
- The 120/121 boundary can split one event: all four images of a run share the same `stamp` and differ only by role (`intrusion_<stamp>_<role>.jpg`), so the cut can delete `..._larry_interior.jpg` and keep `..._doorbell.jpg` from the same intrusion.

The ordering itself is **correct** — `%f` is zero-padded microseconds, so reverse lexicographic on `intrusion_<YYYYMMDD>_<HHMMSS>_<ffffff>_<role>.jpg` is newest-first for any two different runs, and the pattern `intrusion_*.jpg` cannot match the `latest_intrusion_*.jpg` tiles. A concurrent intrusion cannot lose a fresh file to this pass either: the list is a snapshot taken before the `while`, and the `-mtime +0` filter excludes anything under a day old. Those two fears are unfounded.

Smallest fix: replace `-mtime +0` with `-mmin +60` (protect only the run in flight), so the 120 cap applies to everything else; and call the prune from a daily automation rather than only from the page path, so retention does not depend on a successful page. Optionally cut on a run boundary by grouping on the stamp prefix (keep/discard whole `intrusion_<stamp>_` sets).

## 8. MINOR — `files` is now shell code, and the single quotes do not contain it

`:59-60` passes `{{ files }}` inside `bash -c '...'`. `shlex.split` (HA's exec path) strips the single quotes and hands bash one argv element, and bash then **re-parses that element**. So a value containing a quote or `;` escapes the quoting at the bash level: `files: "x'; reboot; '"` becomes part of the script text. There is no live injection path today — `files` is `expected_files | join(' ')` built from a static roster of four roles plus `now().strftime('%Y%m%d_%H%M%S_%f')` (`:120-133`, `:245-255`), so nothing user- or device-supplied reaches it. But `shell_command.phoenix_verify_evidence_files` is a callable service, so anything that ever calls it with a variable becomes a shell sink. Smallest fix: pass the paths as positional parameters so bash never parses them — `bash -c 'for f in "$@"; do [ -s "$f" ] && echo "PHOENIX_EVIDENCE_OK $f"; done' _ {{ files }}` — and keep `files` config-only.

## 9. MINOR — the "flash & audio loop" has no audio, and self-terminates

`phoenix_intrusion_loop` (`:215-248`) ends at the comment `# B. Periodic Audio Overlay (Every ~15s)` with no steps after it: the sequence contains only the strobe. The audible half of a real alarm is therefore exactly one thing — `rest_command.phoenix_alarm_mac_on` posting to `http://192.168.50.45:8128/alarm/on` (`secretary.yaml:37-40`), a single macOS listener on one machine. If that machine is off or the port is closed, an intrusion is strobe plus (now conditional) SMS. Separately, a `while` repeat is terminated by HA itself after `REPEAT_TERMINATE_ITERATIONS = 10000` iterations, so at ~1 s per iteration the loop dies on its own after ~2.8 h even with the flag still on (at ~2 service calls per second while it runs). Smallest fix: add the audio overlay steps the comment promises, and reset the flag from the loop's exit path so the state matches reality.

## 10. MINOR — the condition sits *below* the lights, so a disarmed alarm still blacks the house out; the comment claiming otherwise is wrong

`:176-179` says "Everything above it is evidence capture and must always run". That is false: lines `142-160` (inside `if: not test_mode`) turn `switch.deserted_house_lights` and `switch.control_room_strip_lights` **off**, wait 1 s, then on again — at 03:00 that is a blackout of the property, not evidence capture. It still runs after a disarm. Smallest fix: move the condition above the lights block, or move the lights block below it with the siren.

---

## What I could not verify

- **`bash` on the running HA container.** Confirmed present in the published `home-assistant/docker-base` Alpine Dockerfile (`apk add ... bash ...`), not confirmed by executing anything on the host — that would require a command on HA, which this review forbids. One command on the host (`docker exec homeassistant command -v bash`, or a throwaway `shell_command: 'bash -c "command -v bash"'`) settles it.
- **That the deployed files are byte-identical to the working tree.** The commit says so; `GET /api/config` exposes no file contents and I did not read the host filesystem.
- **Whether the 14:16 drill ran with the new condition already loaded** (commit timestamp 14:18:20; `script.phoenix_intrusion_initial_response last_triggered=2:16:10 PM`). `ha core check` being clean also does not prove the condition is what ran.
- **The page has still never executed against a real event.** The only known 200 was `{ok:true, paged:false}` on an `intrusion_test` event, which returns at `main.py:8594-8596` *before* `prepare_security_alert_media` — so the whole media path (fetch from `/local/snapshots`, rehost, public verify) is untested. On inspection it is at least coherent: bare filenames are accepted and mapped to `<ha_url>/local/snapshots/<name>` (`sms_service.py:1608-1638`, `SECURITY_MEDIA_DEFAULT_HA_SNAPSHOT_PATH = "/local/snapshots"`, `:1568`), which is where `camera.snapshot` wrote them.
- **The list-vs-string question for `snapshots`.** I suspected `snapshots: "{{ snapshot_urls }}"` would arrive as the string `"['a.jpg']"` and silently kill the MMS. Reading HA's `helpers/template/__init__.py` shows `render_complex(..., parse_result=True)` by default, which literal-evals a single-expression render back into a real list, so this is probably fine — but I could not exercise it, and if it ever *is* a string the backend wraps it (`main.py:8578-8580`) and the media lookup produces a 404 name, i.e. a text-only page reported as success.
- **Whether `input_boolean.phoenix_intrusion_active` restores as `on` across an HA restart mid-intrusion.** Not tested; if it restores off, the new condition converts a mid-intrusion restart into a silent alarm.
- **Whether the retention arithmetic in the commit holds** ("48 files to 42, none older than 14 days"). I have no filesystem access to `/config/www/snapshots` and did not reproduce it.
- **`attempts` accumulation across repeat iterations.** Only cosmetic here (it feeds a message that finding 1 proves is unreachable), so I did not chase HA's variable scoping.
