# What a DSH window costs, and why its session list was empty

**Measured and implemented 2026-09-18 on ZABZ-YOGA.** Engine pid 4416 on 3099, never restarted.
Every number below has its command and its raw output.

Two complaints, one launcher:

1. Opening many DSH windows makes the laptop slow.
2. A newly opened window shows "Choose a workspace to start" with **zero** session rows.

They turned out to have separate causes and one shared home — `multi-window/dshw.ps1` and the
proxy it now owns.

---

## 0. The two lines that decide everything

`multi-window/dshw.ps1`, in `Open-SlotWindow`, was:

```powershell
$profDir = Join-Path $Cfg.browser.profileRoot $slot.profile    # w1, w2, ... w16
...
"--user-data-dir=$profDir",
```

**That is the line that decides the profile per window**, and therefore the cost. One
`--user-data-dir` per window means one Chromium *user-data-dir*, and Chromium pays for a
user-data-dir with a whole process tree: browser, GPU, crashpad, network and utility processes that
are **not** shared between profiles.

It is now:

```powershell
$profDir   = Get-SlotProfileDir $slot      # '_shared' for every slot in the default mode
$originPort = Get-SlotOriginPort $slot     # 3200 + slot index; the per-window identity
```

---

## 1. The measured per-window cost

Live process table, 7 windows open on 7 private profiles (`Get-CimInstance Win32_Process -Filter
"Name='msedge.exe'"`, grouped by `--user-data-dir`):

| profile | processes | MB |
|---|---|---|
| w1 | 9 | 917 |
| w2 | 9 | 1027 |
| w3 | 9 | 807 |
| w4 | 9 | 886 |
| w5 | 9 | 692 |
| w7 | 9 | 1064 |
| w8 | 9 | 854 |

**74 msedge processes, 6,804 MB. Nine processes and a mean of 892 MB per window** — for a UI that
renders one page.

Then the same machine, two windows opened through the launcher into the **shared** profile on two
alias origins:

| snapshot | all msedge procs | all MB | shared-profile procs | shared MB |
|---|---|---|---|---|
| baseline (6 legacy windows) | 65 | 6,499 | 0 | 0 |
| after window A (origin 3200) | 74 | 6,941 | 9 | 612 |
| after window B (origin 3201) | 74 | 7,000 | 9 | 764 |

A cleaner earlier run of the same experiment:

| snapshot | all procs | all MB | shared procs | shared MB |
|---|---|---|---|---|
| baseline | 66 | 6,927 | 0 | 0 |
| after window A | 76 | 7,562 | 10 | 672 |
| after window B | 77 | 7,858 | 11 | 926 |

**Window A costs the shared tree plus one renderer (+9-10 processes, +440-635 MB). Window B costs
one renderer: +0-1 processes, +59-296 MB.** Processor count is noisier than memory because Chromium
utility processes come and go; the memory delta is the reliable figure, and both runs agree on the
shape.

**Per-window marginal cost: ~9 processes / ~892 MB → ~1 process / ~60-296 MB.** The one-time shared
tree is the floor: for N windows the total is `tree + N x renderer` instead of `N x tree`. The
projection at 8 windows is 17 processes against 72.

### Why sharing is safe: the origin is the window, not the profile

`localStorage["dsh.sessions.current"]` — "which session am I on" — is keyed **by origin**
(`dsh-api-session-controller/lib/client.js:3058`). A distinct loopback **port** is a distinct
origin, so each window keeps its own session slot *without* owning a browser.

The engine binds `127.0.0.1:3099` only, so `127.0.0.2..` are unreachable, and the `/api`
browser-trust fence **403s** `w1.localhost` while accepting **any** `127.0.0.1:<port>` (401 = fence
passed, auth missing). A loopback port alias is therefore the only origin trick that needs no
engine config change and no engine restart. `dshw-proxy.mjs` serves 24 of them (`3200..3223`), one
per slot index, as a raw TCP splice to 3099 for everything except the one call it caches.

### What the owner loses

**Nothing he uses.** Separate windows: kept. One window per slot/workspace: kept, because the origin
is per-slot. Restore after a reboot: kept, and the registry was migrated so the working set is not
forgotten. Per-window session *and* cookie isolation: the session slot is preserved by origin; the
cookie jar is now shared, which is a *gain* here — a window can no longer land on
`dsh web authentication required` because a sibling already authenticated that origin family.

The real cost is **blast radius, not features**: the browser process is now a single point of
failure for every window. A renderer crash still takes only its own window; a **browser-process**
crash takes all of them. That is the one thing to know, and it is why `profileMode` remains a config
key (`shared` default, `per-window` the escape hatch) rather than a deletion.

`profileMode: "per-window"` restores the old behaviour exactly, including its cost.

---

## 2. The session list

### The client's real RPC shape — read, not guessed

`GET /api/session/list` returns **404 "not found"**. That is a verb error, not a symptom:
`dsh-client-connection/lib/index.js:640` answers 404 for anything that is not a POST to an endpoint
path, and 415 for a non-JSON content type.

The real call, from `dsh-client-connection/lib/client.js:6194-6216` (`createWebConnectionRpc.call`):

```
POST http://127.0.0.1:<origin>/api/session/list
content-type: application/json
{"type":"client-request","rpcId":"<uuid>","method":"session/list","payload":{"args":{"_request":{}}}}
  -> {"type":"server-response","rpcId":"<same>","result":{"ok":true,"value":{"items":[...]}}}
```

Two things had to be read rather than assumed. The payload is `{args:{...}}` — `{"_request":{}}`
alone is accepted by the connection layer and then rejected by
`dsh-api-gateway/lib/index.js:remoteRequest` with *"Remote payload must contain exactly one
plain-object args field"*. And the client **throws** on `full.rpcId !== rpcId`, which is why a
cached reply must be re-labelled with each caller's own id rather than replayed verbatim.

### Timed

Probe against the live engine (`tools/probe-session-list.ps1`):

```
run 1 : HTTP 200 in 25370.8 ms  ok=True  rows=679
run 2 : HTTP 200 in 25069   ms  ok=True
run 3 : HTTP 200 in 31357.1 ms  ok=True
```

1.46 MB of JSON, 679 rows. Every other RPC on the same page load answered promptly, so this is not a
saturated event loop — it is **this one code path**.

### Why it is slow

`dsh-session-persistence-jsonl`'s `listArtifacts()` walks **every session directory on every call**:
one `readdir` per project, one per session, one `stat`, and one first-zstd-line read against each.
Reproduced in plain Node (`tools/replicate-list-scan.mjs`, same tree, no engine involved):

```
project dirs         : 6                        24 ms
session dirs         : 681                      26 ms
first-zstd-line read : 681 parsed, 40.6 MB read  2723 ms
stat per artifact    : 681                      3127 ms
TOTAL                : 5900 ms
```

5.9 s of raw filesystem work, none of it cached anywhere, and the engine multiplies it. The cost is
**linear in the number of stored sessions** and there is no paging parameter to lean on — the RPC's
own documentation calls `_request` a "reserved empty list request".

### The visible bug

The client renders the workspace tree from the *workspace* list (fast) and the session rows from
*this* call, with **no loading state** in between. Reproduced live with Playwright against a fresh
origin: the sidebar showed `treeitem "code"` and nothing under it, and the composer showed
`placeholder.workspace` = "Choose a workspace to start"
(`dsh-client-ui-conversation/lib/client.js:13805`). One request was still open — the session list —
and it landed ~27 s later, at which point 6 rows and "Show 51 more sessions" appeared. **Nothing was
empty; it was simply not there yet, and it said nothing.**

### The fix

The engine serves the owner's live work and must not be restarted, and its client bundles ship
inside it, so the fix lives in the proxy that already sits in front of every window.

`dshw-proxy.mjs` keeps **one** cached `session/list` response and re-labels it per caller:

* **cold** — the first caller pays the real walk; the response is cached.
* **warm (< 15 s)** — served from cache.
* **stale** — served from cache *immediately* and refreshed in the background
  (stale-while-revalidate), so the caller never waits for the walk.
* `GET /__dshw/prewarm` lets the launcher warm it; `dshw ensure` already runs **every minute** as a
  scheduled task, so the cache is essentially always warm and even the first window after a boot is
  fast.
* A failed cold fill triggers a proxy-side refetch, so one bad response cannot leave the cache cold.

Measured through the proxy: **25,371 ms → 29 / 29 / 92 ms (n=3)** with `rpcId` re-labelled
correctly each time, 685 rows, 1,472,207 bytes.

### THE BUG INSIDE THE FIX, because it is the one that would have bitten later

With a plain splice the cache **never filled**: the proxy's own counters read `spliced=19, cold=0`
while the sidebar sat empty. The cause is keep-alive connection reuse — the page's first requests
open ~6 connections, each is handed to a raw pipe because it is not `session/list`, and the browser
then reuses one of those pipes for `session/list`. **A connection that has become a pipe can never be
intercepted again.**

So a forwarded request now has its `Connection:` header rewritten to `close` (measured: the engine
honours it and ends the response, where `keep-alive` makes it answer `Keep-Alive: timeout=5`), which
stops the browser reusing anything and makes every request arrive on its own connection. Upgrade
requests are never rewritten — a WebSocket upgrade needs `Connection: Upgrade` intact — and are
spliced byte-for-byte.

---

## 3. Three defects found on the way, all fixed

**A. The recorded launch token was dead.** `state.json` named pid 29116 / startedAt 13:45:30 while
3099 was served by pid 4416, started 21:39. Its token answered **401**; the token in the engine's own
newest log line answered **303**. `Test-LaunchUrl` only ever checked a token's *shape*, so the
launcher would have handed new windows a dead token and landed them on
`dsh web authentication required` — the 2026-09-15 `w9` incident again. `dshw doctor` had been
printing this as a blocker without anything acting on it.
`Resolve-WindowUrl` now treats the recorded URL as a **candidate** and uses the first one that
survives a real request.

**B. `Test-OriginsProxy` memoised its own first answer.** The memo exists so a 16-slot status call
does not make 16 HTTP round trips — but `Start-OriginsProxy`'s wait loop then read its own failing
first answer 60 times and declared a proxy dead while it was up and serving. The wait loop now
passes `-Fresh`.

**C. Two proxies split the port range.** `ensure` runs every minute as a scheduled task, so a manual
`dshw ensure` and the watchdog can call `Start-OriginsProxy` at the same instant. Measured: two
instances came up, one holding 3200-3215 and the other 3216-3223 — healthy from any single port,
broken as a whole. Three guards now, in order: the launcher leaves the `DSH Origins Proxy` task
**registered** so `-MultipleInstances IgnoreNew` has something to ignore; the proxy exits 0 if
`/__dshw/stats` already answers on its base port; and it takes an atomic `wx` lock file whose pid is
checked for liveness so a crash leftover is taken over rather than honoured.

---

## 4. Which windows are open — the question a shared profile cannot answer by process scan

Measured: in a shared profile **only the FIRST window's URL appears in any process command line**.
The browser root carried `--app=http://127.0.0.1:3200/`; the second window — handed to that same
browser process — existed only as an anonymous `--type=renderer` child with no URL at all. A process
scan can therefore find one window per profile, so in shared mode it finds one window in total and
reports every other slot as empty: `dshw new` re-opens slot 1 forever, and `dshw restore` duplicates
every window.

What *is* per-window is the alias origin. A live window keeps streaming connections open on its own
port, and the proxy counts live connections per port and serves the list at `GET /__dshw/open`:

```
two windows open, one on 3200 and one on 3205
  -> {"ports":[3200,3205]}
all windows closed
  -> {"ports":[]}
```

Verified: `dshw status` reports `windows=1` for slot `1 - main` and `0` for the other fifteen.

**The probe must not count itself.** The launcher discovers liveness by calling `/__dshw/open` *on
one of those very ports*, so the first version reported `openPorts:[3200]` with every window closed —
the base port is the one the launcher probes, and slot 1 would have read as permanently open. The
list is computed with the requesting connection excluded.

---

## 5. Files

| file | what changed |
|---|---|
| `multi-window/dshw.ps1` | shared-profile/origin model; proxy lifecycle (`Ensure-OriginsProxy`, `Start-OriginsProxy`, `Invoke-OriginsPrewarm`); origin-based window counting; label-keyed registry with migration; verified launch-token selection; `doctor`/`status` reporting |
| `multi-window/dshw-proxy.mjs` | **new** — the origin proxy *and* the session-list cache |
| `multi-window/windows.json` | `browser.profileMode`, `browser.sharedProfile`, `origins` |
| `multi-window/tools/probe-session-list.ps1` | **new** — times the real RPC |
| `multi-window/tools/dump-session-list.ps1` | **new** — dumps the raw response |
| `multi-window/tools/replicate-list-scan.mjs` | **new** — reproduces the 5.9 s filesystem walk without the engine |
| `multi-window/dshw-origins.mjs` | **superseded** by `dshw-proxy.mjs`; kept, no longer referenced |

---

## 6. Not verified, and known limits

* **The 24-port range is bigger than the slot count.** `windows.json` has 16 slots and `count: 24`.
  Harmless (extra ports simply idle) but they are configured, not required.
* **Restore after a real reboot was not exercised end to end.** The mechanism was tested
  (`dshw new` picks slot 1 then slot 2 on their own origins; the registry migrates profile keys to
  slot labels and persisted through both runs), but no reboot was taken — taking it was out of scope.
* **A browser-process crash now takes every window with it.** That is the accepted cost of one
  browser tree, and `profileMode: "per-window"` is the escape hatch.
* **The 15 s TTL is a judgement, not a measurement.** A session created in one window appears in
  another within 15 s at worst; mutations do not invalidate the cache. `ttlMs` is a config key.
* **The old `w1`..`w16` profile directories are untouched** and still hold the previous cookie jars
  and session slots. Nothing reads them in shared mode. Deleting them would free disk but is not
  done here.
* **The 25-31 s walk still happens on a cold cache.** It is now paid once per proxy lifetime (and by
  `ensure`'s prewarm) rather than once per window, but the engine's own scan was not made faster —
  that needs a server-side change and therefore an engine restart.
* **Both measured windows opened at the configured geometry** (`--window-size=700,440
  --window-position`), which contradicts the old note in `dshw.ps1` claiming geometry only works
  with a private profile. Only two placements were observed; a 4x2 grid of sixteen was not.
