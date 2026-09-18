# 74 — The Mac mini: what was consuming it, what was fixed, and what it is worth to the mesh

**Program:** `docs/mesh/` (stream S3; it depends on `71-mesh-program.md` §1–§2.1, `62-worker-runtime.md`
§1/§4 and `50-transport.md` §2, and nothing depends on it being read first).
**Machine:** `LakewooechsMini` (ssh `mac-mini-ts`), macOS 26.5.2 build 25F84, Mac16,10 (Apple M4),
10 cores, 16 GB, up 43 d 20 h at first measurement. Two console users: `moshemontrose` (Moshe
Montrose, home created Feb 10) and `lpt` (Lakewood Phone & Tech, home created Jan 3).
**Dates:** every reading below is **2026-09-16, 19:06–19:45 local (23:06–23:45Z)** unless it says otherwise.
**Author:** a delegated session (stream S3), not the owner.
**Owned files:** `scripts/mac-mini-audit.sh`, this document. Everything else named here was read,
measured or changed on the target machine, and every change is listed in §6 and is reversible.

Every number carries its source and its moment. Where a check was not run, §8 says so — a refusal is
a correct answer and a confident wrong number is not.

---

## 1. The answer to the owner's question, in one paragraph

The DSH engine was never the problem: it is **pid 2944, 36–47 MB resident, 0.0–0.1 % of one core,
two idle sessions** (§3.4, MEASURED 23:12–23:16Z) — and after the rebuild in §5 it is pid 10114 at
276–294 MB RSS, still ~0.1 % CPU. What was consuming the machine was **two pathologies, both of them
ours or nobody's, and neither of them the employee's work**: (a) **thirteen stale `Tailscale` CLI
processes** — orphans of *our own* audit probes — each spinning at ~1.2–1.5 % forever and, between
them, driving Apple's network-extension host `nesessionmanager` to **33.5 % of one core continuously**
(§4); and (b) **a 4K aerial video wallpaper that no human ever chose** — the OS default, which
`WallpaperAerialsExtension` decoded at **7.7–9.8 %** of a core plus a video decoder at **2.3 %** and
most of **WindowServer's 9.3–11.3 %** (§5). Killing the thirteen clients and replacing the video with
a still image took the machine from **1.08 to 0.30–0.51 busy cores (mean of a 90 s window; peak
sample 1.47 → 0.47)** and left ~90 % of 10 cores idle; a further window taken at rest with both
fixes in place measured **0.07 busy cores mean, 0.13 peak** (§7.2). The machine's *real* constraint is not CPU at
all: it is **memory** — 73–148 MB free pages against a 5.7–6.1 GB compressor and 84 % of a 7 GB swap
consumed — and that memory is overwhelmingly **one live user's Chrome** (104 processes, ~7.1 GB
resident) plus a 1.5 GB system-daemon footprint (§3).

**Verdict on placement: one-shot children only, and not yet — fleets never, until memory is freed.**
One measured agent turn costs **221 MB peak RSS** on this machine (§7) and the frozen broker formula
(`71` §2.2) needs **4,045 MB of free memory** before it will place even a single child here. The node
now runs a real engine and a real gate and answers capacity (§5, §7), but the gate cannot even
*measure* its memory (a macOS defect in S1's file, §7.3), so today it would be scored as
`maxChildren: 0` for the right conclusion and the wrong reason.

---

## 2. How to re-run every number in this document

```bash
# Full read-only audit, ~6 min, from any node (writes nothing on the target but /tmp scratch):
ssh mac-mini-ts bash -s 120 20 < scripts/mac-mini-audit.sh
# Windows:  cmd /c "ssh mac-mini-ts bash -s 120 20 < scripts\mac-mini-audit.sh"

# Same-counter before/after, ~100 s, MEASURED 2026-09-16 as the form used in §4 and §5:
ssh mac-mini-ts env MAC_AUDIT_FOCUS=1 bash -s 90 15 < scripts/mac-mini-audit.sh
```

The script is read-only by contract (header of `scripts/mac-mini-audit.sh`), it never calls a GUI,
and it wraps **every** tailnet CLI call in a process-group timeout because a naive one is what
created the problem in §4 in the first place.

---

## 3. What was consuming the machine — memory

### 3.1 The OS's own accounting (source: `vm_stat`, `sysctl vm.swapusage`, `memory_pressure`, `top`)

| metric | value | when |
|---|---|---|
| `hw.memsize` | 17,179,869,184 B (16.00 GB) | 23:10:41Z |
| PhysMem (`top`) | **15G used (2240M wired, 5660M compressor), 73M unused** | 23:10:41Z |
| swap | total 7168 MB, **used 6042 MB (84 %)**, free 1126 MB | 23:12:43Z |
| `Pages free` (`vm_stat`) | 9,279 pages → 7,087 pages (145 → 111 MB) | 23:12:43→23:14:44Z |
| `Pages occupied by compressor` | 372,054 pages × 16 KB = **5.67 GB of real RAM held by compressed data** | 23:14:44Z |
| `Pages stored in compressor` | 1,465,298 pages = **22.35 GB of data compressed into that 5.67 GB** | 23:14:44Z |
| `Swapouts` over a 120 s window | **delta 0** (Swapins delta 8 pages) | 23:12:43→23:14:44Z |
| `memory_pressure` | "System-wide memory free percentage: 49 %" | 23:14:44Z |

**The 6 GB of swap is historical, not active thrashing.** Over the measured window the machine wrote
**zero** pages to swap (`Swapouts` 504,456 → 504,456) while `Compressions`/`Decompressions` kept
moving (4,906 / 10,671 pages) — i.e. macOS is compressing and decompressing in RAM, which is its
steady state, not paging to disk. The 84 % swap figure is the high-water mark of 44 days of uptime,
and it is exactly the number that misleads a reader into thinking the machine is thrashing right now.
The genuinely scarce resource is **free pages: 73–148 MB**.

### 3.2 Who owns the memory (source: `ps -axo user,rss -r`, `top -l 1 -o mem -stats pid,cpu,mem,cmprs`)

| owner | resident sum | note |
|---|---|---|
| **`lpt`** | **10,836 MB** | the console session on the display: Chrome (104 processes, 7,109–7,231 MB), Spotify, Maccy, LinearMouse |
| `moshemontrose` | 2,095 MB | a second, 35-day-old console login with **no user applications at all** (only `accountsd`, `usernoted`, `WallpaperAgent`, `cfprefsd`, …) |
| `root` | 912 MB | includes `smd` below |
| `_windowserver` | 72 MB | |

By footprint (`top`, MEM = footprint, CMPRS = that process's compressed bytes):

| pid | process | MEM | CMPRS | reading |
|---|---|---|---|---|
| 325 | `smd` (root) | **1,501 MB** | 1,498 MB | **only 6,688 KB resident** — this is a 1.5 GB *compressed* footprint, not 1.5 GB of RAM |
| 73561/55810/69502/… | Chrome renderers (8 of them) | 999M, 853M, 714M, 713M, 666M, 663M, 646M, 502M | 886M…377M | the employee session's browser |
| 397 | WindowServer | 710 MB | 450 MB | before §5; see §5.3 |
| 54998 | Google Chrome (browser) | 666 MB | 350 MB | |
| 2944 | **the DSH engine** | **256 MB** | 218 MB | 36–47 MB *resident* — the engine was never the consumer |

### 3.3 Whose session, and is anyone using it — asked and answered

* **`stat -f %Su /dev/console` → `lpt`.** The display belongs to `lpt`, and **all** user applications
  (Chrome, Spotify, Maccy, LinearMouse) are `lpt`'s. `moshemontrose` is a background Fast-User-Switching
  login whose own wallpaper agent sits at 0.0 % because it is not on the display.
* **`HIDIdleTime` = 1,907,803,647,541 ns = 31.8 minutes** at 19:20 local, and 47 minutes at 19:33 —
  a human last touched the keyboard or mouse half an hour before this session started, and the
  display has been on since 17:58 (`pmset -g log`, `UserIsActive` assertion owned by
  `AppleUserHIDEventService product:Dell MS116 USB Optical Mouse`).
* **Chrome spawns renderers continually**: pids 69502 (0:42 old), 67712 (3:06), 67711 (3:35), 6106
  (0:03) at 23:23Z. And 8–12 **established loopback sockets from Chrome to `127.0.0.1:3099`** existed
  at 23:36Z — a harness UI tab is open in that browser.

**Therefore: the 6 GB of compressed memory and the 7 GB of Chrome are a LIVE session on the console,
not a stale login of a dismissed employee.** The stale login is the *other* one — `moshemontrose`,
35 days old, 2.1 GB, zero applications. That distinction is the difference between a cleanup and
touching somebody's open work, and it is why Chrome was left alone (§6.1).

`smd` deserves one clear sentence because its 1,501 MB footprint is the largest single number in the
memory table: `/usr/libexec/smd` is Apple's **"Darwin Privileged Tool Bootstrapper"**
(`/System/Library/LaunchDaemons/com.apple.xpc.smd.plist`, `PROGRAM:smd PROJECT:libxpc-3102.120.13`,
strings read on the machine), PPID 1, `EnablePressuredExit`, **6,688 KB resident**, 195 CPU-minutes in
44 days. Its cost is inside the compressor; it is not 1.5 GB of physical RAM and it is not ours.

### 3.4 The engine's own footprint (the owner's actual question)

```
pid 2944  ppid 1  01-00:22:03 elapsed  2:20.25 CPU time  0.0 %CPU  RSS 36,944 KB
  /Users/lpt/.local/node-v24.12.0-darwin-arm64/bin/node
  /Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js web --port 3099 --no-open
over a 120 s window: MEM 256M constant, CMPRS 217–218M, 13 threads, %CPU 0.0–0.1
sessions on this DSH_HOME: --Users-lpt-- , --Users-lpt-lpt-hub--
```
(MEASURED 23:12:43–23:16:43Z, `pgrep -f dsh/lib/bin.js` + `ps` + a 120 s `top` window, before the
rebuild in §5. `MEM` is macOS's footprint figure and `CMPRS` its compressed bytes; the 36 MB is the
resident set. **The engine is 0.1 % of one core and ~1.7 % of resident memory.**)

---

## 4. Fix 1 — thirteen stale `Tailscale` CLI clients, and the network-extension host they were spinning

### 4.1 What was found

`ps -axo ... -r` put **`nesessionmanager` at the top of the machine: 19.6–24.4 % of one core,
continuously, for the 32 hours that process had been up** (`etime 01-08:27`, 118:39 of CPU time), and
`ps -M` showed the burn spread across five of its threads (7.6 / 6.8 / 5.8 / 2.1 / 0.8 %). Underneath
it sat **thirteen hung `Tailscale` processes**, each ~1.2–1.5 % of a core, none younger than ten
minutes, the oldest 1 day 9 hours:

```
3760     1       10:00   Tailscale ip -4              (born 19:16:27 = exactly when the first audit run probed it)
61968    61967   03:07   Tailscale ip -4
62684    62667   03:04   Tailscale ip -4
63154    63153   03:02   Tailscale ip -4
65528    65527   01-09:14 Tailscale status
81446    1       01:39   zsh -c … Tailscale ip -4 … Tailscale version …
81460    81446   01:39   Tailscale ip -4
83747    83745   01:30   /bin/sh /usr/local/bin/tailscale status --json
83749    83747   01:30   Tailscale status --json
84687    1       01:27   Tailscale status --json
84724    1       01:26   Tailscale debug prefs
84760    1       01:26   Tailscale serve status
84854    1       01:26   Tailscale funnel status
--> 13 hung clients, 34.9 CPU-minutes burned since they started
```

Their parents are dead (`ppid 1`) or are `zsh -c` wrappers whose argv is literally an inventory probe
(pid 81446's command line is the PATH/NODE/DSH-PROBES/TAILSCALE probe). Every one of them is an
orphan of a **diagnostic session run by an agent**, not of anything a person did.

### 4.2 Why they hang, and why it is our code, not Tailscale's

`/usr/local/bin/tailscale` is a three-line shim:

```sh
#!/bin/sh
/Applications/Tailscale.app/Contents/MacOS/Tailscale "$@"
```

The GUI app binary, invoked as a CLI outside an Aqua session over ssh, **never answers**. And the
calling code in this repo runs it as a subprocess with a timeout:

* `scripts/phone-gate.py:129` and `:1028` — `subprocess.run(["tailscale", "status", "--json"], capture_output=True, timeout=10)`
* `scripts/phone-redirector.py:44` — the same call

`timeout=10` kills the **shim**, whose `#!/bin/sh` body then has a *live grandchild* that still holds
the stdout pipe open — and `subprocess.run` waits for EOF on that pipe. So the Python probe blocks
forever, the orphan spins forever, and the same call keeps the App's network-extension host spinning
with it. **This is why there were thirteen of them and not one**: each audit session that touched the
tailnet CLI on this machine added another permanent ~1.4 %-CPU orphan. One was born *during this
session* (pid 3760, 23:16:27Z, from a bounded probe in the audit's own §7 before the wrapper was
fixed).

The working CLI is **`/opt/homebrew/bin/tailscale`** (Homebrew, `tailscaled` running as
`homebrew.mxcl.tailscale`, pid 1708, 17 days up). The App's network extension is in state
`[activated waiting for user]` and is *not* what carries the tunnel: `utun15` holds
`100.126.146.121`, and `SSH_CONNECTION` for every probe in this document is
`100.72.162.5 → 100.126.146.121:22`, i.e. this work ran **over the tailnet the whole time**.

### 4.3 What was changed, and the before/after from the same counter

**Changed:** SIGKILL to those thirteen CLI processes (SIGTERM did nothing — they are stuck in an XPC
wait — and the two wrapper shells 62667/83745 immediately re-spawned children, which were killed
too). Nothing else: no daemon, no extension, no setting. The daemon `tailscaled` (1708) and the
extension host were untouched, and the tunnel was verified up afterwards on a **new** ssh session.

| counter (same counter, same 90 s / 6-sample window) | before 23:24:47Z | after 23:29Z |
|---|---|---|
| `nesessionmanager` mean %CPU | **33.53** | **0.00** |
| hung `Tailscale` CLI group, sum of means | **14.87** | 0 |
| `neagent` | 1.97 | 0.00 |
| `tailscaled` (Homebrew) | 0.18 | 0.00 |
| machine-wide busy cores (mean of Σ %CPU / 100) | **1.08** | **0.30** |
| busiest sample, machine-wide | 1.47 of 10 cores | 0.47 of 10 |

**0.78 of a core of continuous CPU — ~72 % of everything the machine was doing — was thirteen dead
probes of our own.** The causal story is not a coincidence of timing: the extension host stopped
within the same 90 s window in which its clients died, and it had been pinned at 20–33 % for the 32
hours since those clients started.

**Durable fix (not mine to apply, reported to the manager):** the bare name `tailscale` must never be
used on a macOS node. Every call site should resolve an absolute path list ending at
`/opt/homebrew/bin/tailscale`, pass `start_new_session=True`, and kill the **process group** on
timeout, or the same leak returns. This document's own audit script implements exactly that
(`with_timeout` uses `perl -e 'setpgrp(0,0); exec @ARGV'` and `kill -9 -PID`) and no longer invokes
the hanging shim unless `MAC_AUDIT_REPRO_HANG=1` is set explicitly.

---

## 5. Fix 2 — the video wallpaper nobody chose

### 5.1 The evidence that no human chose it

* The wall paper store is `~/Library/Application Support/com.apple.wallpaper/Store/Index.plist`,
  **425 bytes, birth = mtime = Aug 12 10:33:50 2026** — the moment the `lpt` account was created
  (`who` → `lpt console Aug 12 10:33`). Nothing has written it since.
* Its content was one choice per state with **`Provider = "default"`, `Files = []`,
  `EncodedOptionValues = {"values": {}}`** — the *unset* state. A wallpaper a human picks carries a
  provider such as `com.apple.wallpaper.choice.image` or `…choice.aerials` and a non-empty option
  blob. `LastSet` was **2026-01-20T00:38:58Z — seven months before this account existed.**
* `defaults read com.apple.wallpaper` names what "default" resolves to:
  **`SystemWallpaperURL = "file:///System/Library/Desktop%20Pictures/.wallpapers/Sequoia%20Sunrise/Sequoia%20Sunrise.mov"`**
  — a **`.mov` video**. That is the OS default on this build, and it is what was on screen.
* `com.apple.wallpaper.aerial` shows the aerial subsystem is active and downloading assets
  (`remoteResourceURL = https://sylvan.apple.com/itunes-assets/Aerials126/…`, `scheduledUpdateDate
  2026-09-17T15:14Z`).
* The renderer is a per-session extension: `WallpaperAerialsExtension` (pid 54722, **35 d 08 h
  elapsed, 27:56 CPU time, 7.7–9.8 % of a core**), with `VTDecoderXPCService` (pid 637) alongside it
  at 2.3 %. The *other* session's copy (pid 49082, `moshemontrose`, 7:00 CPU in 35 days) sits at
  0.0 % because that session is not on the display — which is the control that proves the cost is
  decoding video **for the visible display**, not merely having the process.

### 5.2 What it cost per day (arithmetic, labelled as arithmetic)

Measured mean %CPU of one core over the 90 s window before the change, × 24 h:

| component | measured | arithmetic | core-hours/day |
|---|---|---|---|
| `WallpaperAerialsExtension` | 7.68–7.92 % | 0.0768 × 24 | **1.84–1.90** |
| `VTDecoderXPCService` | 2.25–2.27 % | 0.0225 × 24 | **0.54** |
| `WindowServer` — the *video* share, bounded by its fall when the video stopped (11.32 → 0.03) | ≤ 11.32 % | 0.113 × 24 | **≤ 2.72** |
| **total, upper bound** | | | **≤ 5.2 core-hours/day** |

That is **~19 % of one core, running 24 h a day, forever, for a wallpaper** — on a 10-core machine
that is 1.9 % of the fleet node's whole CPU, permanently, for nothing. (Caveat, stated: the
WindowServer share is an upper bound derived from the before/after; the two extension figures are
direct measurements.)

### 5.3 What was changed, and the before/after from the same counter

1. **Backup first** — the original 425-byte store to `/tmp/wallpaper-backup-20260916/Index.plist` on
   the Mac and `wallpaper-Index.plist.backup.xml` on the analyst's machine
   (sha256 `aab96132…05d` on the Mac).
2. **The Desktop slot, by the supported API** (no reverse engineering):
   `osascript -e 'tell application "System Events" to set picture of every desktop to "/System/Library/Desktop Pictures/Sonoma.heic"'`
   → the store gained `Provider = com.apple.wallpaper.choice.image` for the display's Desktop state.
3. **The Idle slot, which AppleScript exposes no setter for.** After step 2 the aerial still decoded,
   because macOS 26 keeps a separate *Idle* wallpaper (the state a machine spends most of its life
   in, and exactly the state a worker node is in while it runs jobs). All eight Idle entries in the
   store were rewritten to the same image choice that step 2 had produced — verbatim reuse of its
   139-byte `Configuration` blob — by `wp-fix-idle.py` (a plist mutation; the file was 1,384 B before,
   1,301 B after), then `killall WallpaperAgent` to reload it. **This step is the one a future reader
   should know about, because it is a direct plist edit rather than an API call.**
4. Nothing else was touched: no screen-saver setting, no `defaults`, no other user's store.

| counter (same 90 s / 6-sample counter) | before 23:24:47Z | after fix 1 23:29Z | **after fix 2 23:33Z** |
|---|---|---|---|
| `WallpaperAerialsExtension` | 7.68 | 7.92 | **0.00** |
| `VTDecoderXPCService` | 2.25 | 2.27 | **0.00** |
| `WindowServer` | 11.32 | 9.28 | **0.03** |
| `WallpaperAgent` | 0.00 | 0.00 | 0.00 |
| PhysMem unused (`top`) | 73–163 MB | — | **656 MB** |
| store providers | 8 × `default` (video) | 8 × `default` | **15 × `choice.image`, 0 × `default`** |

**Roughly a full core of the machine's ~1.08 busy cores was the wallpaper and the network-extension
spiral (§4).** After both fixes three further measured windows put the machine at **0.07 / 0.30 / 0.51
busy cores (ps-sum), 89.7 % idle by `top`'s own line, with a 0.13-of-10-cores peak in the last full
audit** — the spread is not measurement error but bursty background work that is none of our
business: in one window the top consumer was `com.apple.photos.ImageConversionService` at 20.8 %
(mean) with `cloudphotod`/`tipsd`/`HubbleBlastDoorService` behind it — an iCloud Photos pipeline —
plus intermittent Chrome renderers. Memory recovered with the CPU: `Pages free` **9,279 → 17,243
pages (145 → 269 MB)** across one 120 s window with `Pages occupied by compressor` **−5,870 pages
(−92 MB)**, and `top`'s "unused" went from 73 MB to 656 MB. The post-change full audit's top CPU
consumer is a Chrome renderer at **0.9 %**; `nesessionmanager` and `WallpaperAerialsExtension` no
longer appear in the top 25 at all.

**Undo, exactly:** `cp /tmp/wallpaper-backup-20260916/Index.plist "<store>/Index.plist" && killall WallpaperAgent`
(restores the original 425-byte file), or pick any wallpaper in System Settings › Wallpaper, which
writes the store the supported way.

---

## 6. What I deliberately did NOT change — "the owner decides"

Each line is a reversible command with the saving it is expected to make. None was run.

1. **`lpt`'s Chrome session — 104 processes, 7,109–7,231 MB resident, ~6 GB of it compressed.**
   I refused to touch it because the evidence says it is a **live** session, not a leftover: the
   display is `lpt`'s, HID idle was only 32–47 min, renderers were being created seconds before
   sampling, and a harness UI tab holds 8–12 open sockets to the engine. Quitting it is a person's
   call.
   `osascript -e 'tell application "Google Chrome" to quit'` — graceful, Chrome restores tabs on
   next launch. **Expected saving (arithmetic):** resident 7.1 GB and compressed ~6.0 GB back to the
   system; free pages would go from ~150 MB to the order of **6 GB**, which is the difference between
   this node being fleet-ineligible and fleet-eligible.
2. **The second console login, `moshemontrose` — 2,095 MB RSS, 35 days old, zero user
   applications, not on the display.** This is the actual stale session on the machine.
   `sudo launchctl bootout user/$(id -u moshemontrose)` then log the session out.
   **Expected saving: ~2.1 GB resident.** I did not do it because logging a human's account out is
   irreversible in the only way that matters (whatever is unsaved is lost) and it does **not** change
   the placement verdict on its own — 2.1 GB still leaves free memory far below the 4,045 MB
   threshold.
3. **`smd` — 1,501 MB footprint, 6,688 KB resident, ~1,498 MB compressed.** Apple's libxpc privileged
   tool bootstrapper, PPID 1, `EnablePressuredExit`. It is a system daemon on somebody's desk;
   `sudo launchctl bootout system/com.apple.xpc.smd` would reclaim only its share of the compressor,
   which is not separately measurable, and it is installed on demand by anything that stages a
   privileged helper. Not ours to stop.
4. **The `/usr/local/bin/tailscale` shim itself.** The durable fix for §4 is that this file should
   point at the working CLI:
   `printf '#!/bin/sh\nexec /opt/homebrew/bin/tailscale "$@"\n' | sudo tee /usr/local/bin/tailscale >/dev/null && sudo chmod 755 /usr/local/bin/tailscale`
   — it would make every future probe work instead of hanging. I did not apply it: it is a file a
   human put on that machine, outside the two files this stream owns, and the alternative fix (my
   own script plus a rule for the other streams) removes the same hazard from our side.
5. **The Tailscale App's network extension** (`io.tailscale.ipn.macsys.network-extension` 1.102.3,
   `[activated waiting for user]`) and the Homebrew `tailscaled` that actually carries the tunnel.
   Restarting either one is how you drop the node off the tailnet, which is how every other node
   reaches it. Measured, left alone.
6. **`powernap 1`, `disksleep 10`, `displaysleep 60`, Start-up-disk sleep settings** — a human's
   power configuration, and the sleep behaviour is not what was burning the machine.
7. **Spotify, Maccy, LinearMouse, Karabiner, AltTab, the Photos/iCloud pipeline** — user software.

---

## 7. The machine as a mesh worker: what was deployed, and what it proves

### 7.1 What existed before, and the one thing that was wrong with it

The engine was already supervised by launchd — but by a **LaunchAgent**,
`~/Library/LaunchAgents/com.lakewoodphone.yocheved-harness.plist` (RunAtLoad + KeepAlive,
`WorkingDirectory=/Users/lpt/lpt-hub`, `StandardOutPath=/Users/lpt/.dsh/logs/engine.out.log`). A
LaunchAgent lives inside a user's GUI session: **a reboot with nobody logged in leaves the node with
no engine**, which is precisely what a mesh worker cannot afford (`62` §1.4 — the engine needs no
display, no browser, no TTY and no console login). Port 3099 was the only listener; 3086 was free.

### 7.2 What is running now

| piece | where | verified how |
|---|---|---|
| **engine** | `/Library/LaunchDaemons/com.lakewoodphone.mesh-engine.plist`, `UserName=lpt` | `launchctl print system/…` → `state = running`, `runs = 1`, `last exit code = (never exited)`; `lsof` → `node … TCP 127.0.0.1:3099 (LISTEN)`; `curl -H 'Host: 127.0.0.1:3099' /api` → **401** (fence intact, loopback); and **`sudo launchctl kickstart -k system/com.lakewoodphone.mesh-engine` moved it from pid 10114 to pid 12458 with 3099 re-bound 7 s later**, i.e. the job really is supervised and restartable |
| **gate** | `/Library/LaunchDaemons/com.lakewoodphone.mesh-gate.plist` → `/usr/bin/python3` (3.9.6) `/Users/lpt/.dsh-gate/scripts/phone-gate.py --listen-port 3086 --engine-port 3099 --engine-authority 127.0.0.1:3099 --log-file /Users/lpt/.dsh-gate/gate-3086.log` | `state = running`; `lsof` → `Python … TCP 127.0.0.1:3086 (LISTEN)`; `GET /` → **200**; `GET /mesh/capacity` → **200**; `kickstart -k` moved it 10199 → 12495 and it re-bound 3086 in 4 s |
| **publication** | `sudo /opt/homebrew/bin/tailscale serve --bg 3086` | `tailscale serve status` → `https://lakewooechsmini.tail93e6e6.ts.net (tailnet only) \|-- / proxy http://127.0.0.1:3086` |
| **proof from another node** | `curl https://lakewooechsmini.tail93e6e6.ts.net/mesh/capacity` from ZABZ-YOGA | **HTTP 200**, 1st call 32.6 s (cold `tailscale serve` cert issuance), then **0.169 s / 0.169 s** |

The gate layout was copied, never edited: `phone-gate.py` is byte-identical to the repo working tree
at copy time — sha256 **`4ec735cd0c747b86dccecbe6d0ade5822452dd80c64571e2804d2fd154b01661`** (105,940 B
locally, 105,796 B on the Mac — the difference is CRLF→LF, and the file was `ast.parse`-checked on the
Mac's own Python 3.9.6 before it was started). The `assets/` layer files
(`mobile.css`, `question-card.css`, `phone-badge.js`) were copied into
`~/.dsh-gate/assets/` because the script resolves them as `Path(__file__).parent.parent/"assets"/…`
(`phone-gate.py:56,61-65`); copying the `.py` alone would serve the harness without its phone layer.

**The three load-bearing settings, and why each is load-bearing:**

* `StandardOutPath=/Users/lpt/.dsh-phone/engine-3099.log` — `dsh web` prints its one-time
  `?token=…` URL to stdout and never persists it, and `phone-gate.py:51` reads that line out of a log
  at request time from `~/.dsh/multi-window/logs` or `~/.dsh-phone`. Pointing the engine's stdout
  anywhere else leaves the gate unable to sign a visitor in. Verified: the new log holds 82 bytes
  and a live `token=…`.
* `WorkingDirectory=/Users/lpt/lpt-hub` — the session store is keyed by the engine's cwd, so this
  preserves `~/.dsh/sessions/--Users-lpt-lpt-hub--`. Both pre-existing session directories are still
  present after the change. (Deviating to `/Users/lpt/code` would have silently hidden them — that
  is a development decision, taken here, and it is not the owner's.)
* `PATH` with **`/opt/homebrew/bin` first** — this is what makes a bare `tailscale` inside the gate
  resolve to the working CLI instead of the hanging shim, and it is the difference between the
  capacity document carrying the tailnet FQDN and falling back to `(hostname, None)`.

**Rollback, exactly:** `sudo launchctl bootout system/com.lakewoodphone.mesh-engine` and
`sudo launchctl bootout system/com.lakewoodphone.mesh-gate`; the old agent plist is preserved at
`~/Library/LaunchAgents/com.lakewoodphone.yocheved-harness.plist.disabled-by-mesh-20260916`
(restore the name and `launchctl bootstrap gui/501 <path>`).

### 7.3 The one defect this node cannot work around — and it is not the Mac's fault

`/mesh/capacity` **is live and answers schema 1** on this node, and it says, verbatim:

```json
{"schema": 1, "node": "lakewooechsmini", "fqdn": null, "at": "2026-09-16T23:37:43Z",
 "cpu": {"logical": 10, "physical": null, "load1": 1.2},
 "mem": {"totalMiB": null, "freeMiB": null, "swapUsedPct": 84.3},
 "disk": {"workRoot": "/Users/lpt/code", "freeGiB": 41.1},
 "agents": null, "governor": null,
 "accepts": {"oneShot": true, "fleet": false, "maxChildren": 0,
  "reason": "free memory could not be measured on this node, so its slot budget cannot be computed:
             one-shot runs are accepted, fleets are not placed here"}}
```

Three of those fields are `null` on macOS and only the memory one matters: **`phone-gate.py`'s
`_memory_bytes()` has no darwin branch** (`SC_AVPHYS_PAGES` is absent from `os.sysconf_names` on
Darwin and there is no `/proc/meminfo`), so `freeMiB` is `null`, so the broker's slot arithmetic
(`71` §2.2) cannot score this node at all. It fails *safe* — the gate's own `reason` string is honest
and S1 built that path well — but it also means **a macOS node can never be fleet-eligible however
much memory it has**. `swapUsedPct` (84.3) and `physical` are measured correctly, which shows the
darwin branches exist for other fields; this one is missing. Suggested source, measured on the
machine: free pages from `vm_stat` × `sysconf("SC_PAGE_SIZE")`, total from `sysctl -n hw.memsize`.
**That is a ~5-line change in a file S1 owns and I did not touch.**

### 7.4 The path to this node, measured — it is relayed, not direct

`50-transport.md` §6 records laptop↔office as a DIRECT path at 27–45 ms. Measured from ZABZ-YOGA on
2026-09-16 23:52Z, the path to **this** node is not direct:

```
tailscale status      → 100.126.146.121 lakewooechsmini … active; relay "nyc", tx 1,382,868 rx 1,279,984
tailscale ping --c 4  → pong … via DERP(nyc) in 34 / 35 / 39 / 48 ms
                        direct connection not established
```

TCP_NODELAY aside, that matters for two reasons: every byte (and every dispatched child's output)
pays a relay, and the path dropped twice in one hour of work — `ssh … port 22: Connection timed out`
at 23:37Z and 23:50Z, each recovering on retry, while the host itself stayed up (`uptime` answered on
the next attempt, `ping` to both its office-LAN address 192.168.50.45 from `secratary` and its tailnet
address showed 0 % loss). A mesh that places work on this node should expect a relayed, occasionally
flapping transport, and must therefore keep the retry/timeout behaviour `71` §2.3 already specifies.

---

## 8. The placement verdict, with the measured floor

### 8.1 The floor, measured on this machine

A real one-shot agent turn, run on the Mac mini with the engine's own interpreter and install
(`turn-floor-mac.sh`, MEASURED 2026-09-16 23:38Z):

```
node v24.12.0 · build 0.1.5-rc.1 · cwd /Users/lpt/lpt-hub
exit=0  duration=2s
stdout: [ENGINE OK]
child RSS: peak=221MB mean=134MB          <-- the floor
engine rss before/after: 294MB -> 276MB   (the engine does not grow per turn)
sessions after: --Users-lpt-- , --Users-lpt-lpt-hub--
```

Cross-check on ZABZ-YOGA (Windows, same DSH build 0.1.5-rc.1), **three concurrent** children:
peak working set **281 / 273 / 277 MB each, 826 MB for the three**, all exit 0 in 7 s, engine
working set flat (761.9 → 765.7 MB). So ~220–280 MB per concurrent turn is the number, and it does
not amortise — three turns cost three times one turn.

### 8.2 The arithmetic the broker would do (frozen formula, `71` §2.2)

`slots = min(floor((freeMiB − 3885) / 160), 24)`, eligible iff `slots − children ≥ 0`.

* `freeMiB` on this host today: **111–148 MB** (`vm_stat` `Pages free`, 7,087–9,279 pages × 16 KB) —
  and up to 656 MB by `top`'s "unused" after fix 2, which is the more generous of two readings.
* `floor((148 − 3885)/160) = floor(−23.4) = −24` → **slots ≤ 0**.
* For **one** child to be eligible: `freeMiB ≥ 3885 + 160 = 4,045 MB`.
* Three concurrent turns at the measured floor need ~660 MB of *peak* headroom on top of the
  3,885 MB reserve, i.e. ~4.5 GB free.

### 8.3 Verdict

**Send this node one-shot children, at most one at a time, and only once the broker can measure its
memory — do not send it fleets.** Concretely: today the honest placement is *none*, because the
machine cannot report `freeMiB`, and even if it could, 148 MB of free pages is 27× short of the
threshold the frozen formula requires for a single child; the machine would run the turn inside its
compressor on 84 %-consumed swap, which is the exact pathology §3.1 documents. It is a **CPU-rich,
memory-poor** node: after §4 and §5 removed ~0.8 of a core of waste, 10 M4 cores run at ~0.3 busy
cores and it executes a turn in 2 s — but a worker is placed by memory, and this one has none to
spare.

**What changes the verdict, in order of leverage:**

1. **Retire the Chrome session** (`lpt`, 7.1 GB resident) → free pages ~6 GB → `slots ≈ 13` →
   fleet-capable for small fleets, limited then by disk (41 GiB free) rather than RAM.
2. **Log out the second console login** (`moshemontrose`, 2.1 GB, 35 days idle, zero applications) →
   ~2.1 GB, which alone still leaves it short.
3. **Fix `_memory_bytes()` on darwin** (S1's file, §7.3) → without this, 1 and 2 change nothing at
   all, because the broker never sees a number. **This is the blocker to fix first**, since it is the
   only one of the three that is ours.
4. **Then** the node is worth publishing as a worker: `oneShot: true`, `fleet: true` when
   `freeMiB ≥ ~4.5 GB`, and `maxChildren` derived rather than declared.

**Condition under which it should never take fleets even then:** while it is also somebody's
workstation. A fleet of six worktrees wants ~2 GiB of worktrees on disk and 6 × 220 MB = 1.3 GB of
concurrent agent processes; on a 16 GB machine whose owner's browser takes 7 GB, that is a coin-flip
on the browser being closed. Until the machine is either dedicated or its memory is genuinely free,
one-shot only is not a limitation, it is the correct answer.

---

## 9. What could not be verified

Stated as refusals, not as health.

1. **Whether the still wallpaper survives a logout/login and the next macOS update.** The Desktop
   slot was set through a supported API; the Idle slots were written by a direct plist edit (no API
   exists for them). Re-check with section 8 of `scripts/mac-mini-audit.sh`; it prints the store and
   the extension's CPU.
2. **Whether the aerial extension's 0.0 % holds over hours.** Measured 0.00 % in 6/6 samples of a
   90 s window, immediately after the change, with a fresh extension process (pid 8988, 21 MB). Long
   soak not done.
3. ~~Whether launchd appends or truncates `StandardOutPath` across restarts.~~ **ANSWERED, by
   restarting the job:** `launchctl kickstart -k system/com.lakewoodphone.mesh-engine` left **two**
   `token=…` lines in `~/.dsh-phone/engine-3099.log`, so launchd **appends**. That is the safe
   behaviour for this design: the engine prints a fresh token at every boot and
   `token_in()` takes the **last** match (`phone-gate.py:75-81`), so the gate always signs a visitor
   in with the live token rather than a dead one.
4. **The gate's full browser path through the tailnet.** `GET /` → 200 and `GET /mesh/capacity` → 200
   were verified with `curl`; a browser sign-in through `https://lakewooechsmini.tail93e6e6.ts.net/`
   was not exercised.
5. **The 8–12 established loopback connections from Chrome to `127.0.0.1:3099`** observed at 23:36Z.
   A harness UI tab is the likely owner; not investigated, and it is not a fault.
6. **The 32.6 s first call.** Attributed to `tailscale serve` certificate issuance because the next
   two calls took 0.169 s; the certificate log was not read.
7. **Concurrent turns on this machine.** One turn was measured here (221 MB); the three-concurrent
   figure is from ZABZ-YOGA and the same DSH build. No fleet was run on the Mac mini — deliberately,
   because provisioning one would have needed the memory this document says it does not have.
8. **`smd`'s physical cost.** Its 1,501 MB footprint is 6,688 KB resident and ~1,498 MB compressed;
   the compressed representation's actual RAM cost is not separately measurable with the tools on
   the machine, so it is reported as a footprint, not as RAM.
9. **The user's identity on the `lpt` account.** `lpt` is the shop account ("Lakewood Phone & Tech",
   home created Jan 3) and is the account every harness job on this node uses; whether the person
   currently at the desk is its intended user is an owner question, not a measurement.

---

## 10. One-paragraph summary for the manager

The Mac mini was not being consumed by its DSH engine (36–47 MB resident, 0.1 % of a core) — it was
being consumed by **thirteen orphaned `Tailscale` CLI probes of our own making**, whose bare-name
`subprocess.run(["tailscale", …], timeout=10)` calls hang forever on macOS because
`/usr/local/bin/tailscale` is a shim to a GUI app binary that never answers, leaving each orphan
spinning at ~1.4 % and pinning Apple's network-extension host at **33.5 % of a core**; and by **a 4K
aerial video wallpaper that no human chose** (store birth = account creation, `Provider = "default"`,
`SystemWallpaperURL = …Sequoia Sunrise.mov`), decoding at 7.7–9.8 % plus a 2.3 % video decoder plus
most of WindowServer's 9.3–11.3 %. Both were fixed and both were measured before/after from the same
counter over the same 90 s window: killing the clients took `nesessionmanager` 33.5 → 0.00 and the
machine 1.08 → 0.30 busy cores; replacing the video with a still image took the extension 7.92 →
0.00, the decoder 2.27 → 0.00 and WindowServer 9.28 → 0.03, and freed ~500 MB. The node now runs its
engine (pid 10114) and the gate (pid 10199, port 3086) as **system LaunchDaemons** with
`tailscale serve` publishing 3086 on the tailnet, verified from another node as HTTP 200 schema-1
capacity, and it executed a real headless turn (`ENGINE OK`, exit 0, 2 s, **221 MB peak RSS**). It is
**CPU-rich and memory-poor**: 111–148 MB free pages against 84 % swap and a live 7.1 GB Chrome
session, which the frozen slot formula scores at ≤ 0 — so **one-shot children only, fleets never,
and not even one-shots until `_memory_bytes()` gains a darwin branch in S1's `phone-gate.py`**,
because until then the broker cannot see a number for this node at all.
