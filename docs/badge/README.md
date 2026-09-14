# The attention badge — the system, the contract, and how to prove it works

The badge answers one question in the place the owner already looks: **what is the company reporting
right now?** It is the only channel in this system that has ever successfully delivered a finding to
him (`owner_message_queue` had delivered nothing since 2026-07-19; see `journal/PAIN.md` P55).

This file is the reference of record. It exists because the badge is spread across five files in two
repos, in three languages, and the coupling between them is invisible from any single one.

---

## 1. The pieces

| Piece | File | Language | Job |
|---|---|---|---|
| the badge | `assets/phone-badge.js` | browser JS | renders the pill and the card, fetches the findings |
| the gate's half | `scripts/phone-gate.py` | Python | serves the badge and the findings, injects the script into every document it proxies |
| the phone delivery | `phone-gate.py` → `inject_all()` | Python | rewrites the document on its way to the phone |
| the everywhere delivery | `packages/plugin-attention-badge/` | JS | one script tag, pointing at the authority, on machines that run their own engine |
| the digest's copy | `personal-secretary-mvp/scripts/server/owner-attention-digest.sh` §1b | bash | the same facts, in the terminal, for a human reading the digest |
| the source of truth | `~/ceo-kernel-var/latest.json` on `secratary` | JSON | written every 5 minutes by `ck/sentinel.py` via cron |

```
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  secratary                                                               │
  │                                                                          │
  │   ceo-kernel cron (5 min)                                                 │
  │        └─> writes ~/ceo-kernel-var/latest.json    ← 13 checks, provenance │
  │                     │                                                     │
  │   phone-gate.py  ───┴─> GET /dsh-attention.json   ← findings, CORS        │
  │   (127.0.0.1:3086) ────> GET /dsh-attention.js     ← the badge            │
  │        └─ injects <script id="dsh-attention-badge-loader"> into documents  │
  └──────────────────────────────────────────────────────────────────────────┘
             ▲                                    ▲
             │ tailnet HTTPS                      │ tailnet HTTPS (script)
      ┌──────┴───────┐                    ┌───────┴────────────────┐
      │ the iPhone   │                    │ desktop / yoga         │
      │ (via the gate│                    │ local engine on 3099,   │
      │  as its URL) │                    │ plugin injects the tag  │
      └──────────────┘                    └────────────────────────┘
```

---

## 2. The wire contract

`GET /dsh-attention.json` — served by the gate, **unauthenticated by design** (see §5).

```json
{
  "read": true,                    // the flag. true only when the document was understood.
  "at": "2026-09-14T06:00:00Z",    // when the kernel wrote it. Drives the staleness clock.
  "host": "secratary",
  "total": 13,                     // checks run
  "healthy": 7,                    // checks that passed
  "ok_count": 7,                   // legacy alias of `healthy`, for a cached old badge
  "attention": 6,                  // checks needing attention
  "unknown": 0,
  "dropped": 0,                    // findings that were not objects and were discarded
  "highest": "critical",           // worst severity among the findings
  "checks": [                      // only the findings needing attention, worst first
    {"check": "delivery", "severity": "critical", "summary": "...", "needs_attention": true}
  ],
  "quiet": ["replication", "liveness"]
}
```

**A refusal is `{"read": false, "error": "..."}` and carries no `checks` key at all.** There are five
ways to get one: the kill switch is set, the state file is missing, unreadable, not JSON, or not an
object — and a sixth: it is an object whose `summary` is not a dict or whose `findings` is not a list.

### The three rules that keep this honest

1. **`read` is a flag; `ok` is a count.** They shared the key `ok` once, and because `summary.ok` is a
   number, an all-clear arrived as `ok: 0` — falsy — so a perfectly healthy system read as
   *"findings unavailable"* to any truthiness test. The rename is why `healthy` and `ok_count` exist.
2. **The badge decides readability from the shape**, not from the boolean: a payload carrying a
   `checks` list is a reading. That is the only test that distinguishes `0 problems` from
   `could not read`, because both arrive as `0` otherwise.
3. **A missing count is `null`, never 0.** `Number(null)` is `0`, so a naive coercion turns an absent
   field into a confident all-clear. `countOf()` refuses null, undefined and blank explicitly.

---

## 3. The rendered states

| State | Pill | Card | Trigger |
|---|---|---|---|
| good | `6 needing attention` + severity colour | findings, age, counts | a reading, fresh |
| all clear | `nothing needs attention` | `nothing needs attention` | a reading, `attention: 0`, fresh |
| stale | `6 needing attention · stale 9h ago` + amber border | head marked `(stale)` | age > 20 min, **or** age unparseable |
| unresolved | `6 needing attention · last good` | `last attempt failed: <reason>` | a fetch failed but a previous reading exists |
| blind | `findings unavailable`, dashed border | `Findings NOT READABLE` + the reason | no reading ever arrived, or the gate refused |

The staleness threshold is 20 minutes against a kernel that writes every 5 — three missed writes.

---

## 4. How to verify it

```bash
node scripts/verify-badge.js          # 130 checks: render, failure modes, escaping, plugin, round trip
python scripts/verify-badge-gate.py   # 55 checks: payload shapes, refusals, CORS, injection, cache
```

Both run on Windows and Linux with no browser and no network. `verify-badge.js` prints a
`PASS`/`FAIL` line per check and exits non-zero on any failure, so it can gate a change.

**What they cover.** Every one of the five rendered states; a good reading followed by a failed
refresh; timeout, network error and a throwing `send`; malformed JSON and a 200-carrying-a-refusal;
HTML injection through a check name and a summary; the request contract (GET, no credentials, 12 s
timeout, data origin from the loader attribute); the cache's key and TTL; the CORS allowlist; the
injection's idempotence; the plugin's loader contract and bundle patch.

**What they cannot cover**, and what to do instead:

| Unverified | How to close it |
|---|---|
| that a human sees the badge | open the harness and look. One reload; if absent, restart the engine |
| a real browser's `currentScript` timing for an `async` script | same — the browser is the only oracle |
| that the deployed authority's bytes equal this checkout | `curl -s <authority>/dsh-attention.json` and compare with the same call on the host |
| the kernel writing a *fresh* state file | `python3 -m ck status` on the authority, then read `at` |

**The round trip is the important one.** `verify-badge.js` runs
`python scripts/verify-badge-gate.py --payload` to get the gate's real bytes, and renders them with
the badge's real renderer. The two halves share a field contract across two languages and nothing
else coupled them: without that test, a rename on either side reaches the owner's phone first and is
found last.

---

## 5. Security posture, stated plainly

The findings route and the badge script are served **without authentication**. What that means:

- **Reachable only over the tailnet.** The gate binds `127.0.0.1` and is published by Tailscale
  Serve to the tailnet; it is not on the public internet.
- **The payload carries no secrets**: check names, severities, one-line summaries, counts, the host
  name. No customer data, no credentials, no paths to anything private beyond the state file's
  location in a refusal message.
- **CORS is restricted to loopback origins** (`http://127.0.0.1:*`, `http://localhost:*`, `[::1]`).
  Any other origin gets no `Access-Control-Allow-Origin` and the browser discards the answer. This
  matters because the badge is loaded onto pages that also visit the open web: without the allowlist,
  any page the owner visited could read his operational findings.
- **No credentials are accepted or echoed.** The endpoint does not send
  `Access-Control-Allow-Credentials` and the badge does not send `withCredentials`, so it cannot be
  turned into an ambient-authority read.
- **A kill switch exists**: `PHONE_ATTENTION_BADGE=0` in the gate's environment makes every response a
  refusal naming the switch. It does not stop the badge from rendering — nothing would — it stops the
  data.

The badge is delivered by **injecting a script into the harness document**. That is the same trust
model the phone layer already had for its stylesheet, and the same one the plugin uses: the
`harness-config` repo is the source of truth, and what it serves is what runs.

---

## 6. Deployment

| Where | What runs | Update |
|---|---|---|
| `secratary` | `phone-gate.py` (gate), `assets/phone-badge.js` (served), `ceo-kernel` + cron (the source) | `git pull` in `~/harness-config`, then restart the gate |
| the iPhone | nothing; it uses the authority's URL | hard-refresh the page |
| `ZABZ-TECH`, `ZABZ-YOGA` | their own engine + `dsh-plugin-attention-badge` | `git pull`, `install-client-plugins.ps1 -RequireAll`, reload the page |

**Restarting the gate is a small outage on the phone only.** It is a raw TCP relay; killing it drops
in-flight phone requests and `serve-phone.sh` brings it back. Do not confuse it with restarting the
*engine*, which ends every session the engine serves — including the session doing the work, if you
are running on that machine.

**Rebuild the cache honestly.** The badge is fetched with `no-store`, so no cache busting is needed;
the *client bundle* is served immutable by the engine, which is why a new package needs a reload or
restart on that machine.

---

## 7. Known limits, deliberately not fixed

1. **The staleness clock is the kernel's `at`**, never the fetch time. A reading fetched twelve hours
   ago whose `at` is recent would render as current. Today that cannot happen — the fetch is live and
   `at` comes from the same file — but it is an assumption, not a guarantee.
2. **`BADGE_AUTHORITY` is a constant in the plugin.** If the authority moves, every mounted machine
   shows "findings unavailable" until it is reinstalled. Recorded in the package README; not solved.
3. **The badge has no notification behaviour.** It is silent by design and by the owner's choice: he
   picked a badge over SMS and over a daily email on 2026-09-14.
4. **`phone-badge.js` re-asserts itself but does not unload.** If the app removed the badge element
   permanently, a `MutationObserver` puts it back; there is no path that stops it from doing so.
5. **One process, one language gap.** The gate is Python, the badge is JS, the plugin is JS, and the
   contract between them is tested only by the round trip. A schema would be better than prose; the
   round trip is what makes prose sufficient for now.

---

## 8. The failure that motivated all of this

`owner_message_queue` reached **nothing** between 2026-07-19 and 2026-09-14 — 298 held messages, and
the alert about the dead channel was sent *through the dead channel*. Every sensor was working; none
of it was delivered. The badge exists to close that gap, and its own failure mode is the same one it
was built to fix: **silence looks exactly like health**. Hence the four states above, two of which
are deliberately not green, and the staleness flag that refuses to present an old reading as current.

Recorded in `journal/PAIN.md` P55, `journal/LESSONS.md` L174–L177 and L190–L192.
