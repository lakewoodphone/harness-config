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
| the source of truth | `~/ceo-kernel-var/latest.json` on the **authority** (`secratary-cloud` since the 2026-10-11 cutover; the office box `secratary` before it) | JSON | written every 5 minutes by `ck/sentinel.py` via cron |

```
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  secratary-cloud   (THE AUTHORITY; the office box is a frozen anchor)     │
  │                                                                          │
  │   ceo-kernel cron (5 min)                                                 │
  │        └─> writes /root/ceo-kernel-var/latest.json  ← 19 checks, provenance│
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
| **frozen source** | `6 needing attention · stale 6h ago` (and the age grows forever) | head marked `(stale)`, naming the host it came from | every declared source answered but all of them are stale — the state you are in when the machine that computes the findings has stopped, or when you are reading a rollback anchor |
| unresolved | `6 needing attention · last good` | `last attempt failed: <reason>` | a fetch failed but a previous reading exists |
| blind | `findings unavailable`, dashed border | `Findings NOT READABLE` + the reason | the gate answered `read:false`, or no reading ever arrived |
| **unreachable** | `findings unavailable`, dashed border — **from the plugin, locally** | which host could not be reached, and that it is retrying | the badge *script itself* cannot be fetched from the authority |

The staleness threshold is 20 minutes against a kernel that writes every 5 — three missed writes.

**The last row is the one that took an outage to notice.** On a desktop or laptop the badge is loaded
*from the authority*, so when the authority is unreachable there is no badge and — before 2026-09-14 —
nothing said so. The state that most needed reporting could not report itself, because its reporter
was the thing that had failed. `dsh-plugin-attention-badge` now renders that row from code it carries
locally. The phone is unaffected: it loads the badge and the document from the same origin, so if the
document arrived, the script can too.

---

## 4. How to verify it

```bash
node scripts/verify-badge.js          # 181 checks: render, failure modes, escaping, plugin fallback, sources, round trip
python scripts/verify-badge-gate.py   # 55 checks: payload shapes, refusals, CORS, injection, cache
```

Both run on Windows and Linux with no browser and no network. `verify-badge.js` prints a
`PASS`/`FAIL` line per check and exits non-zero on any failure, so it can gate a change.

**What they cover.** Every one of the six rendered states; a good reading followed by a failed
refresh; timeout, network error and a throwing `send`; malformed JSON and a 200-carrying-a-refusal;
HTML injection through a check name and a summary; the request contract (GET, no credentials, 12 s
timeout, data origin from the loader attribute); **a frozen first source losing to a live second one,
a refusal falling through, an unreachable source not ending the chain, every source stale, and
nothing declared at all**; the cache's key and TTL; the CORS allowlist; the injection's idempotence;
the plugin's loader contract and bundle patch.

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
| `secratary-cloud` (the authority, since 2026-10-11T05:43Z) | `phone-gate.py` (gate) + `/usr/local/assets/phone-badge.js` (served), `/root/ceo-kernel` + cron (the source) | copy the asset to **both** `/usr/local/assets/` and the checkout's `assets/`, then nothing needs restarting — the gate re-reads on `(mtime, size)` |
| `secratary` (office, FROZEN rollback anchor) | the same three things, frozen: `cron` masked, last kernel write 2026-10-11T20:20Z | **do not update it.** It is a stand-in source only, and it is read-only by decision (`docs/mesh/142-ANCHOR-WRITE-NOTICE.md`) |
| the iPhone | nothing; it uses whatever URL its document came from | hard-refresh the page |
| `ZABZ-TECH`, `ZABZ-YOGA` | their own engine + `dsh-plugin-attention-badge` | the package is mounted from the repo, so a `git pull`/sync is the update; then reload the page |

**Deployment order matters, and it is the reverse of what it looks like.** The badge *implementation*
is fetched from the authority and the *origin list* lives on each machine, so: (1) put the asset on the
authority, (2) let the machines receive the plugin, (3) reload the pages. Getting 1 and 3 out of order
is survivable — a machine with the new plugin and an old authority-side badge asks both sources and
still renders correctly, because the list lives in the plugin's attribute and the old badge only reads
the first entry it is given.

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
2. **The badge's sources are a list with a fallback, which is not the same as a health check.** Since
   2026-10-12 the plugin declares the authority *and* the frozen office box, and the freshest readable
   reading wins. That makes a source move survivable without reinstalling every machine; it does not
   make a *stale* authority visible as a problem, because the pill says `stale <age>` and nothing
   escalates. The alarm for "the kernel stopped" is still the badge's age and a human noticing it — see
   `docs/mesh/168-ATTENTION-AUTHORITY.md` for what was and was not closed.
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
was built to fix: **silence looks exactly like health**. Hence the six states above, three of which
are deliberately not green, and the staleness flag that refuses to present an old reading as current.

## 9. Incident: the badge repeated its own founding mistake (2026-09-14)

**Reported by the owner:** *"I think I saw the badge earlier today but I don't see it now."*

**Cause, measured.** His laptop had rebooted at 16:41. `tailscaled` started 20 seconds later and then
sat at `BackendState: NoState` for **51 minutes** — the tunnel never came back, `C:\ProgramData\
Tailscale` was empty, and the hostname did not resolve. The badge script is fetched *from* the
authority over that tunnel, so it could not load; the pill vanished and nothing said why.

**The design defect this exposed — and it is the same one as §8, one level up.** The badge's
unreachable-state was unreachable: the code that says *"I cannot reach the authority"* was itself being
fetched from the authority. *Silence looked like health* about the badge's own delivery. A monitoring
component must not depend on the thing it monitors in order to report that thing's failure.

**Fixes.**
1. `dsh-plugin-attention-badge` now carries a local refusal pill (§3, last row) plus a retry, with
   tests for: the fallback appearing, naming the host, claiming no all-clear, removing itself when the
   real badge arrives, replacing a dead `<script>` tag, and cleaning up on teardown.
2. The **id-guard** flaw: a failed script load leaves the element in the document, so the guard read
   the failure as *already loading* and never retried. A dead tag is now replaced.
3. Nothing was changed about the phone path, which never had this defect: there, the document and the
   badge script come from the same server, so a script that cannot load means a page that never arrived.

**The isolation was in fact fixable without elevation — a first attempt said otherwise.** `Restart-Service
Tailscale` returned *"Cannot open 'Tailscale' service"* (a genuine access-denied for service control), and
I nearly handed the owner a task on that basis. Two user-level actions fixed it, both verified:

1. **Launching the GUI** (`tailscale-ipn.exe`) drove the stuck backend from `NoState` to `Running`. The
   daemon had been running for 51 minutes without ever initialising; the tray process is evidently what
   completes the handshake.
2. **`tailscale set --accept-dns=true`** — `CorpDNS` was **false**, so `secratary.tail93e6e6.ts.net` did
   not resolve *even with the tunnel up*. That is the second half of the outage and the less obvious
   half: a working tunnel is not the same as a resolvable name. After it: the name resolves to
   `100.84.72.88` and `GET /dsh-attention.js` returns **200, 21,232 bytes**.

*Lesson:* "needs admin" was true of the *service*, not of the *problem*. Check the user-level path before
telling the owner something is his to do.

**What remains uncovered:** no check alarms when the *tailnet itself* is down on a machine, and nothing
distinguishes "tunnel down" from "DNS off" in the badge's own message. A machine can be isolated while
every local check reads green. Recorded, not solved.

Recorded in `journal/PAIN.md` P55, `journal/LESSONS.md` L174–L177 and L190–L192.

## 10. Incident: the badge read a stopped clock for six hours (2026-10-12)

**Reported by the owner, looking at the pill in the Web GUI:**

> *"6 needing attention · stale 6h ago … Why does it say stale? We migrated from the office secretary
> to the cloud secretary, but the cloud secretary has taken over this job. Why is everything stable?
> What's going on?"*

**Every word of that reading was true, and that is what made it dangerous.** The badge was working
exactly as designed — a reading it could not prove current was labelled stale — and its source had
stopped. "Stable" meant *stopped*: the same six findings, at the same numbers, forever.

**What was measured**

| thing | reading | how |
|---|---|---|
| `secratary.tail93e6e6.ts.net` (= the office box, `100.84.72.88`) | the URL every badge in the fleet fetched | `curl -w '%{remote_ip}'`, `tailscale status` |
| that box's `~/ceo-kernel-var/latest.json` | `generatedAt 2026-10-11T20:20:06Z`, `host: secratary` — and nothing since | `ls -l --time-style=full-iso`, `run.log` tail ends `20:20:06 exit=1` |
| why it stopped at 20:20 | the box is a **frozen rollback anchor** (`cron` `masked`+`inactive`); that last write is inside the accidental 19:04–20:26Z unfreeze window of 2026-10-11 (`AGENTS.md` §5) | `systemctl is-enabled cron` → `masked` |
| the live authority, one hostname away | `secratary-cloud` was already serving `/dsh-attention.js` (200) and answering `/dsh-attention.json` with `{"read": false, "error": "cannot read /root/ceo-kernel-var/latest.json: No such file or directory"}` | `curl` from this laptop |
| whether the authority computed the findings | **it did not.** The kernel port to the cloud was prepared on 2026-10-11 and never installed (`docs/mesh/140-PORT-CORE-AND-GAPS.md` §A1, blocked mid-session by an SSH refusal) | `ls /root/ceo-kernel*` → absent; no `run-sentinel` row in the cloud crontab |

**The two defects, and they are different kinds**

1. **A missing consumer of an existing producer.** The authority had the database, the API, the
   dashboard and the gate — everything except the one job that computes what the badge shows. Nothing
   noticed, because nothing was watching *for a missing reading*: the badge reported staleness and no
   other surface cared.
2. **A hardcoded origin in a client bundle.** `BADGE_AUTHORITY` named the office box. Even after the
   authority computes the findings, a machine whose page was already loaded would ask the wrong host
   for up to a year (client bundles are served immutable). The reading would then be *honest and
   useless*, forever, with no error anywhere.

**The fixes, and their evidence**

| # | change | proof |
|---|---|---|
| 1 | `ceo-kernel` installed on the authority: checkout at `/root/ceo-kernel` (cloned from a bundle, HEAD `7be7fde`, tree == HEAD), state seeded from the frozen box for trend continuity, `ck/sources.py` patched to read the authority from `CEO_KERNEL_DB`/`CEO_KERNEL_AUTHORITY_HOST` (the values default to the old ones, so nothing changes anywhere else) | first run: `generatedAt`, `host: secratary-cloud`, `db.selected /root/authority.db`, `db.authoritative true`, 15 s wall |
| 2 | scheduled every 5 min (measured 15 s, so `*/5` not `*/15`) through the estate's own `cron-wrap.sh`, under `nice -n 10`, with the crontab backed up first; the name `run-sentinel` is unchanged so any monitor keyed on it keeps reading true | `crontab -l` tail, and a ledger row `/root/.cron-status/runs.tsv` written by the wrapper: `run-sentinel 0 9` |
| 3 | the authority's `phone-gate.service` now serves a live report **with no restart at all** — its `CEO_KERNEL_STATE` default is `$HOME/ceo-kernel-var`, which is where the port put the state | `curl http://127.0.0.1:3086/dsh-attention.json` → `read true, age_seconds 0.3, host secratary-cloud` |
| 4 | `assets/phone-badge.js` v4: the data-origin attribute is a **list**, candidates are asked in order, the **freshest readable reading wins**, a stale one is kept only if nothing fresher answers and is still labelled with its host and age; `packages/plugin-attention-badge` declares both the authority and the frozen box | `node scripts/verify-badge.js` → **181/181**, including a frozen-first/live-second case, a refusal falling through, an unreachable source, all-stale, and nothing-declared; before the change the same file ran 163 |
| 5 | the fixed asset deployed to the authority's `/usr/local/assets/` **and** its checkout, both backed up as `*.pre-multisource-<stamp>` | the gate's served bytes hash-match this repo's file (`46fb7f1f…`) and report `var VERSION = '4'` |

**What the live authority then said** (and why it mattered that it was live): the frozen report named
`config_sync`, `session_archive`, `agent_dead_weight`, `attention_debt`, `owner_queue` and
`model_lane_health`. The authority's first real report named **`db_writable` (HIGH — "the
authoritative database refuses writes: database is locked")**, `web_currency_math` (HIGH — money
typeset as LaTeX on the phone), `owner_queue`, `attention_debt`, `agent_dead_weight` and
`model_lane_health`, with `unknown: 3`. Two of the six old findings (`config_sync`, `session_archive`)
were **artifacts of the frozen box** — they described a machine that had stopped, not the company. And
`db_writable` was reproduced independently four times out of four. A stopped clock does not only fail
to tell the time; it hides the emergencies.

**What is NOT closed here** (each is a live, named gap, not a hope):

1. **No alarm on the sentinel's own death.** The badge says `stale <age>` and nothing escalates. The
   property that failed tonight was *silence about a missing reading*; the badge's honesty is not the
   same as a monitor. Filed where it belongs: the kernel's own `history.jsonl` has no reader, and
   `docs/mesh/140-PORT-CORE-AND-GAPS.md` §A1 already recorded that "nothing would notice its failure".
2. **Three checks are blind on the authority** (`config_sync`, `app_voice`, `model_failover`) and the
   kernel exits **2 — "cannot see"** on every run. `app_voice` is a porting error (it names the office
   unit `secretary-api`; the authority's unit is `company-api`). These are being corrected, but they
   were blind at the time of writing and the record should say so.
3. **The office box still serves a v3 badge to anything that asks it**, and will until it is retired.
   With the plugin's list and freshest-wins that is now a stand-in rather than a trap, but it is still
   a second source of the same name. Retire the entry in `BADGE_AUTHORITIES` when the box goes.
4. **The kernel repo's canonical copy is still a bare repo on the frozen office box.** The authority's
   checkout is ahead of it, so the port's patch lives on one machine. That is the same shape of defect
   as everything above and is named here rather than quietly left.

**The lesson this incident actually teaches.** The badge did not fail. The bundle constant did not
fail. The *estate* failed to move a producer when it moved its authority, and every surface that
depended on it kept rendering a true, stale, useless reading. A monitoring surface must be able to say
**"the thing I read has stopped"** in a way someone acts on — and the hostname of a source never
belongs in a client bundle, because the next move is always one edit and a year of cached copies away.
