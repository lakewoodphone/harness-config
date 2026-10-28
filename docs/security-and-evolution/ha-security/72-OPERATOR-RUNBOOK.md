# 72 — Operator runbook: security paging

**Read this to operate the paging system.** The contract and reasoning are `70-PAGING.md`; the build history and
accepted limits are `71-PAGING-IMPLEMENTATION.md`. This is the operational page: what fires, what arrives, and what to
do with each part.

*State as of 2026-10-27 22:5xZ. Everything below was applied to `secratary-cloud:/opt/company` and to
`/root/authority.db`, and each item carries the evidence that it was verified.*

## 1. What makes a page happen

Home Assistant watches the two door contacts and posts to `POST /webhook/ha/security-alert` when its intrusion chain
fires. The company's judge (`security-sentinel`) independently records a `security_decision` for the same events.

| level | meaning (the code's own words) | what happens |
|---|---|---|
| **3** | verified intrusion — a door with no credential while the shop is declared closed | **pages**, with picture, at any hour |
| 2 | human-corroborated note — a door with no credential while the building was occupied | a note: SMS if the day is quiet, digest if not, and **holds during quiet hours** |
| 0–1 | benign / credential used | nothing |

**The declared state is what makes level 3 reachable.** It used to be a 600-second presence latch over a basement that
contains the family's flat, which meant any family member at home demoted an intrusion to a note. Now:

```bash
/root/security-state.py show                      # what the judge believes
/root/security-state.py shop_closed               # the shop is shut (shop door then counts as expected-empty)
/root/security-state.py apartment_occupied        # someone is in the flat; the shop door is NOT expected-empty
/root/security-state.py nobody_here               # nobody anywhere; BOTH doors count as expected-empty
```

Mapping, deliberately conservative so a declaration can never invent a page: **shop door** expected-empty only when
`shop_closed` or `nobody_here`; **apartment door** only when `nobody_here`. With no declaration ever made, the old
latch decides.

## 2. What arrives, and with what

One MMS per recipient: the owner (via `owner_notify_target`, so it rings the phone he actually looks at) plus whoever is
in `HA_SECURITY_EXTRA_RECIPIENTS`. The body begins `⚠️ LPT-SECURITY` followed by the event and the reason; a verified
picture is attached when one can be produced.

**The picture does not depend on Home Assistant any more.** If HA sends no snapshot — its evidence script currently
aborts on a bare `for … done` inside a `shell_command` that HA `exec`s rather than shells — the API captures a still
itself from `security_default_camera` (default `camera.cam_front_hallway_main`), rehosts it under an unguessable token,
and re-fetches it anonymously the way Twilio will. Measured: `media_ok True`, 154,779 bytes.

## 3. Answering or cancelling a page

```bash
curl -s -X POST http://127.0.0.1:8002/webhook/ha/security-page/cancel \
  -H 'Content-Type: application/json' -H "x-ps-api-key: $HA_SECURITY_API_KEY" \
  -d '{"who":"owner-pin","note":"that was me"}'
```

It appends to `security_page_ack` (`page_id`, `who`, `noted_at`, `note`, `window_s`) — it never disarms, never deletes
evidence and never rewrites the decision. Cancelling the same page twice is idempotent and returns the original
`who`/`noted_at`. The window is 600 s and is **reported, not enforced**: `inside_window: false` still records the
acknowledgement, because a page that rang four minutes before an answer is exactly the number that tells you whether
escalation is set correctly.

## 4. What runs on a timer

| unit | every | what it does |
|---|---|---|
| `security-page-fallback.timer` | 2 min | pages for a level-3 decision where the record shows **nothing paged** within ±300 s — through the same webhook, never a second sender |
| `security-page-escalate.timer` | 2 min | **voice-calls** for a delivered page that has no acknowledgement and is older than 300 s |

Both are oneshot services over `company-api.service`, both refuse safely, and both were tested to refusal:

```bash
systemctl list-timers 'security-page-*'
journalctl -u security-page-fallback.service -n 5
journalctl -u security-page-escalate.service -n 5
```

## 5. Testing it without sending anything

`/root/security-page-fallback.py --dry-run` reads the real record and prints what it *would* do, and sends nothing.
To exercise the branches, plant a row and delete it by its exact id:

```sql
-- a level-3 decision the judge has not paged for
INSERT INTO security_decision (id, event_id, episode_id, rule_id, rule_version, decided_by,
  considered, decision, avs_level, confidence, reason_one_line, fallback_used, build_sha, created_at)
VALUES ('selftest-l3', NULL, 'shop_door@2026-10-27T22:52:00Z', 'T_SELFTEST', 'v0', 'selftest',
  '{}', 'ESCALATE', 3, 0.6, 'selftest', 0, 'selftest', strftime('%Y-%m-%dT%H:%M:%SZ','now'));
-- then: /opt/company/.venv/bin/python /root/security-page-fallback.py --dry-run
DELETE FROM security_decision WHERE id='selftest-l3';
```

`page_decision(avs_level, quiet_now)` in `app/security_page_audit.py` is pure and units-tested (7 cases), so the
priority rule can be checked without touching the network.

```bash
# the priority rule, pure, 7 cases
cd /opt/company && PYTHONPATH=/opt/company .venv/bin/python -c "from app.security_page_audit import page_decision as p; print(p(3, True), p(2, True), p(None, True))"
# ok reports the OWNER'S send - stubs the transport, sends nothing, exits 0 on pass
cd /opt/company && PYTHONPATH=/opt/company .venv/bin/python /root/test-security-page-ok.py
```

`PYTHONPATH` is not optional for the second: a script run by absolute path puts its own directory on `sys.path`, not
the working directory.

## 6. When something looks wrong

| symptom | first check |
|---|---|
| a page never arrived | `sqlite3 /root/authority.db "select * from security_action order by id desc limit 5"` — nothing there means nothing was attempted |
| a page arrived twice | the fallback dedupes on a ±300 s window, not an identifier; check whether HA's page and the fallback both fired |
| the shop door never alarms | `/root/security-state.py show` — with no declaration, level 3 is unreachable by design |
| the picture is missing | the body says why (`📷 No picture attached — <reason>`); check `camera.cam_front_hallway_main` answers |
| owner SMS silent | `ls /opt/company/data/OWNER_SMS_KILL_SWITCH` — if that file exists, **all** owner SMS are blocked |

## 7. Rolling anything back

Every live edit left a timestamped backup beside the file:

```bash
ls /opt/company/app/*.bak-*
cp -p /opt/company/app/sms_service.py.bak-quota-security-20261027T224114Z /opt/company/app/sms_service.py
systemctl restart company-api.service
```

For the sentinel: `/root/security-sentinel.py.bak-declared-state-20261027T224507Z`.

**Never `git checkout`, `git stash` or `git reset` in `/opt/company`.** It is a deployment checkout on
`keepalive/323-pickup-live-restore-20261021` at `7673b21f9` with **364 modified paths**; the deployment is what is on
disk, not what is in git. Edit surgically, back up first, `py_compile`, restart, and verify by **file mtime before
process start** plus `/health`.

## 8. What is verified and what is not — read before trusting it

| verified with evidence | **not** verified |
|---|---|
| quota exemption (mtime < start, health 200, 401s) | that a page gets through **while over quota** — needs 20 real owner sends or a stubbed counter |
| `ok` = the owner's send; `paged` mirrors `ok` | that HA's retry loop no longer repeats (needs a real failed recipient) |
| the audit writer (a real row written, then removed) | the **handler-level** write end to end — needs a real page |
| the declared state (table, tool, mapping, sentinel live) | that a level-3 row is produced by a real door event |
| the fallback in **both** branches (dry run, synthetic rows) | the `COVERED` branch against a page HA actually sent |
| the cancel across all three paths, idempotent | — |
| the escalation's **four refusal gates** | the **voice call itself** |
| `page_decision` 7/7 cases | a real MMS carrying the picture |
| the picture chain to "a verified public URL exists" | delivery to a handset |

**Corrected 2026-10-28 15:39:48Z:** a page HAS now been sent — the owner's MMS is **delivered**, `media=1`, sid
`MM1801cd7f0c87ebf59072fb71c2fabcd2` — and the voice escalation has dialled (three completed calls: 15:45:03,
15:47:03, 15:49:08, two of which were a bug now fixed). What is still unproven is the `COVERED` branch against a page
Home Assistant itself sent, and delivery to a handset as reported by the recipient rather than by Twilio.

## 9. The Shop dashboard — how to run it, change it, and check it

The owner opens **`shop-view`** on his phone: `http://192.168.50.34:8123/shop-view`, or
`ha.abletelsolutions.com/shop-view` from outside. One view, six cards, built entirely from built-in card types.

**What is on it, in order:** the status banner · the shop-door camera · both doors in words (`Open`/`Closed`) · the
last four keypad entries · a 24-hour band graph of both doors · a 2×2 grid of the other four cameras.

### The files

| file | what it is |
|---|---|
| `scripts/ha-shop-dashboard.py` | **the source of truth** — the layout, the banner Jinja, the severity colours, plus an idempotent applier with a `--dry` mode and an entity preflight |
| `scripts/check-shop-entities.py` | standalone preflight: every entity must exist, and every camera must return a frame |
| `scripts/render-shop.py` | renders the dashboard headless at phone size and saves a PNG |
| `scripts/watch-shop.py` | samples the live DOM twice to prove the banner updates and the cameras refresh |
| `scripts/test-banner-states.py` | ten banner states through Jinja2 with stubbed `states()` |
| `scripts/make-forced-states.py` | builds a throwaway dashboard with forced alarm states, to see red without sounding an alarm |
| `dashboards/shop-view-390.png`, `-390-dark.png`, `-360.png`, `-forced-states.png` | what it actually looks like |

### The commands

```bash
cd /opt/company
P="PYTHONPATH=/opt/company"

# change the layout, then:
PYTHONPATH=/opt/company .venv/bin/python /root/ha-shop-dashboard.py --dry     # show the card list
PYTHONPATH=/opt/company .venv/bin/python /root/ha-shop-dashboard.py           # preflight + apply + readback

# prove it is not broken before trusting it
PYTHONPATH=/opt/company .venv/bin/python /root/check-shop-entities.py          # entities + a frame from each camera
PYTHONPATH=/opt/company .venv/bin/python /root/test-banner-states.py           # 10 banner states
PYTHONPATH=/opt/company .venv/bin/python /root/render-shop.py                  # screenshot at 390 px
PYTHONPATH=/opt/company .venv/bin/python /root/render-shop.py --dark           # and in dark mode
PYTHONPATH=/opt/company .venv/bin/python /root/render-shop.py --width 360 --height 640
PYTHONPATH=/opt/company .venv/bin/python /root/watch-shop.py --seconds 20      # does it update by itself?
```

**Then look at the PNG.** Reading the config back proves nothing about how it looks; two of the defects found in this
work were invisible to every API readback.

### The traps, each paid for

- **`/config` is unreachable** (only 8123 answers), so everything goes over the websocket: `lovelace/dashboards/create`,
  `lovelace/config/save`, `lovelace/config`, `lovelace/dashboards/list|update|delete`.
- **A storage dashboard's `url_path` must contain a hyphen** — Home Assistant refuses `shop`.
- **`websockets.connect` rejects `ssl=` for a `ws://` URI**; pass an SSL context only for `wss://`.
- **`lovelace/config/save` validates nothing.** A bad card is stored and fails at render as a generic error box. That is
  why the generator refuses to save when an entity id is missing, and why every change is read back.
- **Markdown template errors are suppressed** outside the editor: the card goes blank or stale. Render every template
  through `/api/template` before applying it.
- **Cards live in shadow DOM.** A plain `document.querySelectorAll` finds nothing; Playwright's locators pierce one
  level, and the banner needs an explicit walk of nested roots.
- **Home Assistant pauses image polling for cards that are off screen.** A card outside the viewport has nothing to
  refresh, so sampling it proves nothing. Scroll before measuring.
- **`card_mod` is a key on a standard card, not a `custom:` card.** If card-mod disappears the style is ignored and the
  card still works; the view depends on **zero** custom cards.
- **The logbook card renders nothing on this instance** — measured empty with both `target.entity_id` and the
  deprecated `entities` form, while `logbook/get_events` returns rows for the same entities. It was deleted rather than
  shipped as 479 px of white.

### What cannot be done in Home Assistant

**A visit with its picture.** Home Assistant's cards cannot join a history entry to a stored image, and there is no
file access to add a template sensor that would. The band graph gives the *visits* (start, end, duration); the keypad
card gives the *people*; the cameras give the *pictures*. Tying one to the others needs a store that can hold both —
which is the company's `/root/authority.db`, where `security_evidence` already holds a picture and a hash per event.
That page was built and rejected as too complex; if it comes back, it should be one list of visits with thumbnails,
not a dashboard.
