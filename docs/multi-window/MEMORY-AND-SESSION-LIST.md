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

---

## 7. Liveness on every origin, and the watchdog that was switched off (2026-09-18, later the same night)

The task **`DSH Window Fleet Watchdog`** (every 5 minutes, `wscript` → `dshw.ps1 health`) was
disabled by hand as an emergency stop, because a window-opening loop was traced to it: slots 1 and 2
appeared in `~/.dsh/multi-window/windows.log` at 23:13:29/23:13:52 and **again** at
23:21:28/23:21:59, with 229 open events accumulated.

### The cause was not the watchdog

`health` opens no windows, and never did — `Invoke-Health` starts missing ENGINES and exits. Every
one of its runs that night is in `logs/health-20260917.log`, and the 23:17:27 and 23:22:29 runs each
printed a single line, `healthy: all 1 enabled engine(s) listening`, with no open in between. The
windows were opened by `new`/`restore`, and the reason they repeated is the liveness test below.
Re-enabling the task was therefore correct, and it now does the window work it was named for.

### The liveness test could only see one shape of window

`Get-WindowCount` asked the proxy for the origin's live connections **only when
`profileMode=shared`**, and otherwise fell back to a process scan keyed on the slot's
`--user-data-dir`. Two shapes fell through it:

| window opened | how it was counted before | why |
|---|---|---|
| shared profile, on a proxy origin | proxy, exact | worked |
| shared profile, on the engine port (the documented fallback when the proxy is down) | profile scan | one shared profile, so every slot matched or none did |
| any window while the proxy was unreachable | profile scan | the origin port is in the command line, the profile is not |

`Get-OpenOriginPorts` now returns the union of three signals, so the answer no longer depends on the
profile mode, on the proxy being up, or on which model opened the window:

1. the proxy's own per-port live-connection count (`/__dshw/open`, requesting connection excluded);
2. a process scan keyed on **each window's `--app=http://127.0.0.1:<port>` origin**, including the
   engine port, so a window on `3099` is found by the same code path;
3. if the first sample is empty, two more samples 600 ms apart — a window is only visible through
   (1) once its page has connected, and `new` asks the question immediately after the previous open
   returned. Paid only when the first sample is empty.

Measured on a test window of my own on origin **3201**: 2 live connections sustained for 15 s while
open, and a stable **0** within 3 s of a graceful `WM_CLOSE` — so `live > 0` is the signal, and a
closed window does not linger. With a *later* test window on **3202** and the owner's five legacy
windows open on `3099`, one call read `{"ports":[3202],"live":{"3202":2}}`; the process-scan part of
the union separately reported `3099` while those legacy windows were up.

### A window that dies now comes back

Nothing watched the windows, so a crash mid-session left the slot empty until the owner clicked `+`.
`Invoke-WindowRecovery` (`dshw health`) now does that, under five guards: the registry must say the
window was open; the port it RECORDED must equal the slot's origin now (a legacy `port: 3099` entry
cannot be told apart slot by slot, so it is left alone); the origin must have a listener; the origin
must not be in the live set; and a 600 s per-slot cooldown so a window that was just reopened and has
not connected yet is not reopened again. At most **2** windows are opened per run, the rest are held
for the next run and named in the transcript. `dshw health` now always prints what the pass saw:
`windows: live origins [...]; registry-open-and-missing N; reopened M; held for the next run: ...`.

Measured, raw counts from `windows.log` (each row is one run of `dshw health`, in order):

| step | open events |
|---|---|
| two test windows open, run 1 | 230 → **231** (slot 1: recorded open, no live window) |
| run 2, immediately after | **231** (nothing) |
| slot 2 closed by hand (`WM_CLOSE`), next run | 231 → **232**, `[reopen] 2 (origin :3201)` — exactly one |
| run immediately after that | **232** (nothing) |
| run C, after the 600 s cooldown | 232 → **233** (slot 1's cooldown had expired) |
| run D, immediately after | **233** (nothing) |
| slot closed with `dshw open -Slot 3` (not in the registry), run E | 233 → **235**, `reopened 2` (slots 1 and 2, both recorded open) |
| both test windows closed, registry reconciled, after the cooldown: runs F and G | **235 → 235 → 235** (nothing, twice) |

A second consecutive run never opens anything, the count is stable across runs, and the set of open
origins is stable across runs.

### The re-enabled task, measured on its own schedule

`Enable-ScheduledTask` (not a re-register, so the action, trigger and settings are the originals it was
born with: `wscript //B //NoLogo DSH_Window_Fleet_Watchdog.vbs`, interval `PT5M`,
`MultipleInstances IgnoreNew`, `ExecutionTimeLimit PT15M`). State `Ready`, `LastTaskResult 0`. It had
missed 9 runs while disabled and fired immediately on re-enable.

Then 12 consecutive samples across three of its own firings — **00:12:14, 00:17:14, 00:22:14**:

```
00:12:20  opens=235  appWins320x=0  sharedProcs=0  lastTask=00:12:14 res=0  /open={"ports":[],"live":{}}
00:17:30  opens=235  appWins320x=0  sharedProcs=0  lastTask=00:17:14 res=0  /open={"ports":[],"live":{}}
00:22:40  opens=235  appWins320x=0  sharedProcs=0  lastTask=00:22:14 res=0  /open={"ports":[],"live":{}}
```

The open-event count never moved off **235** and no shared-profile browser process was left running —
which is the outcome that matters most here, because "opens nothing when there is nothing to fix" is
the half of this that was broken.

### One real defect found while testing, and one false alarm I have to own

* **`dshw open <slot>` was broken outright, and the cause was a NAME COLLISION.** PowerShell variable
  names are case-INSENSITIVE, so `$slot` and the script's own `$Slot` parameter are the SAME variable.
  The `'open'` dispatch branch began `$slot = $null` before parsing its selector, which therefore
  blanked the selector: the next line reported `no slot matches ''` and the command exited 1 having
  opened nothing. Every command whose job is to act on one named slot was affected when invoked as
  `dshw open 3` / `dshw open -Slot 3`; `dshw new`, which takes no selector, worked, which is why it
  went unnoticed. The branch now binds to `$slotCfg`, and `dshw open -Slot 3` was verified end to end:
  `opened window for slot '3'`, a `windows.log` line `open slot=3 profile=w3 origin=3202 pid=5372`,
  and `GET /__dshw/open` reading `{"ports":[3202],"live":{"3202":2}}`.
* **`Open-SlotWindow` named `$slot.port` on the branch that `Set-StrictMode` evaluates even when it is
  not taken**, and a raw config row has no `port` key at all in single mode, so that call died before
  opening anything. It uses `Get-Prop` now. This one was reached through `dshw open`'s own path and is
  a genuine hardening rather than a second bug in the same place.
* **FALSE ALARM, recorded because it cost an hour and the reasoning is the lesson.** I first reported
  that `Get-SlotCfgByPortOrLabel` "returned the selector string instead of a slot" and changed it, on
  the strength of an isolated probe. The probe was wrong: I had loaded the launcher by dot-sourcing a
  CUT COPY, and a script dot-sourced from inside a script resolves `$PSScriptRoot` to the COPY's
  directory, so it read a *different* `windows.json` and returned rows for a fleet whose slots did not
  match the selector. The function was never at fault. A probe that does not reproduce the production
  call path is not evidence, and the fix for that is to probe the real entry point (which is what
  finally located the `$slot`/`$Slot` collision) rather than to trust a convenient harness.

### What is still true, and what is not yet done

* The registry holds **12 entries with `open: true`, all of them legacy `port: 3099`** rows that no
  single slot can claim. They are not recovered (guard 2) and they are not silently deleted; a
  `dshw restore` would try to open all 12, and `restore` was deliberately **not** run — see §8.
* The owner's five on-screen windows are the legacy engine-port shape. The launcher cannot map them
  to slots, so it neither counts them per slot nor recovers them per slot.
* **The two registry rows my own test windows created (`1 - main` on 3200, `2` on 3201) were marked
  `open: false` afterwards**, which is the state those rows were in before the tests in the sense
  that matters — no live window existed for either — so no later health run reopens a window that
  belongs to a test rather than to the owner's working set.
* **Window lifetime and the 23:13/23:21 pairs are still unexplained, and I am not going to guess.**
  Observed twice: a shared-profile browser the launcher opened was gone within 3-5 minutes with
  `exit_type = Normal`, no Crashpad dump and no Application-error event — a GRACEFUL close, not a crash.
  Observed later: three of the owner's five legacy windows closed between 00:22 and 00:25, most likely
  he closed them himself since he was awake, and the remaining two then held steady for seven minutes
  with six origin connections on `3099` decaying to four. So some closes are real deaths and some are
  the owner, and from outside this session I cannot yet tell them apart. Which call path opened the
  23:13/23:21 pairs is likewise unidentified; `dshw health` is excluded by evidence (one transcript line
  per run, no open between), and `dshw.exe` on PATH is the older build. The one candidate found in the
  harness is `scripts/mesh-hygiene.ps1:824`, `CloseMainWindow()` on an explicit target list matched by
  executable path — I could not confirm whether Edge is on that list. What is settled is the consequence:
  because the liveness answer is now right in every shape, and because recovery is capped at one window
  per slot per 600 s and at two per run, a window that dies is restored once instead of stampeding.

---

## 8. Restore after a reboot: what is proven, and what only a reboot can test

No reboot was taken. What was proven instead, with nothing opened:

* **The registry and the restore plan agree.** Computed from `windows-registry.json` and
  `windows.json` in a scratch copy (the real registry re-read afterwards and unchanged), slot by slot
  with each slot's origin port and profile:

  | slot | origin | registry | recorded port | live? | `restore` would |
  |---|---|---|---|---|---|
  | `1 - main` | 3200 | open=true | 3200 | no | OPEN on :3200 |
  | `2` | 3201 | open=true | 3201 | no | OPEN on :3201 |
  | `3` … `12` | 3202 … 3211 | open=true | 3099 | no | OPEN on :3202 … :3211 |
  | `13 - auto` | 3212 | open=true | 3099 | no | OPEN on :3212 |
  | `14 - auto` | 3213 | open=true | 3099 | no | OPEN on :3213 |
  | `15 - auto` | 3214 | — | — | no | nothing (not in the registry) |
  | `16 - auto` | 3215 | — | — | no | nothing (not in the registry) |

  That is the state at the time of the measurement. Afterwards, my two test rows (`1 - main`, `2`) were
  set to `open: false` — see §7 — so a `restore` from the registry as it stands now would open **12**
  windows, not 14, all of them in the shared `_shared` profile, all of them legacy rows whose recorded
  port is `3099`. Every slot's resolved profile is `_shared` and every origin is `3200 + index`, read
  from `windows.json` rather than assumed.
* **The decision logic runs in isolation without opening anything.** `Invoke-WindowRecovery -DryRun`
  against that same copied registry produced a plan and opened nothing (`windows.log` unchanged,
  registry unchanged), and separately produced exactly two candidates (`1 - main` and `2`) while
  skipping the twelve legacy rows on guard 2. That is the difference between the two mechanisms in one
  number: `restore` opens what the registry remembers (**14** at measurement time), **recovery** opens
  only what the registry remembers *and* the liveness check confirms is gone (**2**, and at most 2 per
  run).
* **`Resolve-WindowUrl` picks a token that answers.** The token the new test window was launched with
  (`--app=http://127.0.0.1:3201/?token=zUobELIIen-...`) is the one `Test-TokenAccepted` accepted
  against the live engine, which is the 303 answer — not the dead recorded token (pid 29116 / 13:45)
  that answered 401 while pid 4416 / 21:39 served the port.

**AND THE ONE THING THAT IS ACTUALLY WRONG AT BOOT, found while answering this.** There is no
automatic restore at logon, and there never was on this machine: the logon task `DSH Multi-Window
Launcher` runs `dshw.ps1 up -WindowsMode no`, which starts the ENGINE and stops; `dshw-launch.cmd` — the
file whose whole job is `ensure` then `restore` — is referenced by no task and no shortcut; and the
desktop `DSH Windows.lnk` runs `dshw.cmd up`, not that file. So after a reboot the engine comes back and
the windows do not, until someone runs `dshw restore` or double-clicks the OneDrive "DSH" shortcut.
Changing it is a one-line change to the logon task's argument (`-WindowsMode no` → `-WindowsMode
restore`), and it was NOT made here: with 12 stale legacy rows in the registry it would open 12 windows
at once, and auto-restore-at-logon is a visible behaviour change that is the owner's to choose.

**What a reboot alone would still test:** that Edge comes up with the shared `_shared` profile and
opens the remembered origins with the right geometry; that the restore path is reached with no engine
running yet (`Get-PortOwner` false → `Ensure-Engine`); and that the browser's own `--user-data-dir` lock
is free at logon, which is the one condition a running browser cannot be made to reproduce. Everything
above was proven without one.

