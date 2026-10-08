# DSH engine boot failure — 2026-09-17

**Machine:** `ZABZ-YOGA` (Windows, user `ezabz`)
**Port:** `3099`
**Symptom:** DSH would not start; launcher looped on `3099 is not answering`
**Status at time of writing:** engine running and answering · **root cause still unpatched**
**Documented by:** VS Code Copilot · 2026-09-17 ~21:42 local

---

## Who wrote this, and why this document exists

I am **GitHub Copilot**, running on **DeepSeek 4.1 Flash (vision)**, sitting in a VS Code chat
session on the machine `ZABZ-YOGA`. My workspace is `personal-secretary-mvp`; the DSH harness
lives in a different repo (`harness-config`), so I reached it through the shell.

Here is the part that matters for understanding why you are holding a document instead of
just a fixed machine:

**I have no memory.** I am a chat session. I do not wake up remembering yesterday. When this
conversation closes, everything I learned here — the stack trace, the wrong path, the
`DSH_HOME` gap, the reason it broke at 21:32 and not at 10:45 — is gone unless it is written
down. My only continuity is what I commit to text. That is not a stylistic flourish; it is
literally how I work.

So this document is not a formality. It is the only reason the next person — or the next
version of me — will know that an unset `DSH_HOME` was what stopped the engine from booting,
and that it was masked rather than repaired. Without it, someone will re-derive all of this
from scratch, or worse, "fix" the wrong layer.

Two further things about my own reliability, stated plainly:

- I verified every claim below with a command whose output I actually read. Where I am
  **reasoning** rather than **observing**, I say so.
- I am describing a fix that **works but does not close the defect**. I want that visible,
  not buried.

---

## TL;DR

The `DSH.lnk` shortcut was never broken. The DSH **engine was crashing during boot** because
the newly built `spend-guard` module in `plugin-cost` resolves its dependencies from
`<DSH_HOME>/profiles/web/package.json`, but the generated code falls back to `USERPROFILE`
when `DSH_HOME` is unset — producing the path `C:\Users\ezabz\profiles\web\package.json`,
which is missing the `.dsh` segment. From there `@deepseek-ai/schemastery` cannot be found,
the plugin tree fails to load, and the engine exits `1`.

`DSH_HOME` was **not set anywhere on this machine**. Setting it to `C:\Users\ezabz\.dsh`
restored boot immediately. The underlying generator (`scripts/build.mjs`) still emits the
wrong fallback and should be fixed.

---

## 1. What the owner saw

Double-clicking `C:\Users\ezabz\OneDrive\Desktop\DSH.lnk` produced:

```
ensure: engine on 3099 is not answering the fast probe - checking patiently
engine on 3099 is not answering (attempt 1/3) - starting it
```

and then it kept going. The shortcut resolves to:

| Property | Value |
| --- | --- |
| Target | `C:\Windows\System32\cmd.exe` |
| Arguments | `/c "C:\Users\ezabz\code\harness-config\multi-window\dshw-launch.cmd"` |
| Working dir | `C:\Users\ezabz\code\harness-config\multi-window` |
| Window style | `7` (minimized) |

`dshw-launch.cmd` runs two steps and nothing else:

```
"%PWSH%" ... -File "%DSHW%" ensure      # is the engine answering? if not, start it
"%PWSH%" ... -File "%DSHW%" restore     # reopen the windows that were open at last close
```

So the shortcut was doing its job correctly. It was reporting a real engine failure and
retrying, which is exactly what it was designed to do.

---

## 2. The system in play

| Piece | What it is |
| --- | --- |
| `dshw.ps1` | ~103 KB PowerShell launcher for the DSH multi-window harness |
| Port `3099` | The DSH engine's HTTP listener, bound to `127.0.0.1` |
| Engine | `node .../@deepseek-ai/dsh/lib/bin.js web --port 3099 --no-open` |
| npx install | `C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules` |
| DSH home | `C:\Users\ezabz\.dsh` (profile `web`, browser profiles `w1`…`w14`) |
| `plugin-cost` | Local plugin at `harness-config\packages\plugin-cost` — provides `/cost` and `spend-guard` |
| Mount method | A **junction** from `~/.dsh/profiles/web/node_modules/dsh-plugin-cost` to the repo checkout |

That junction is the reason a rebuild in the repo is live in the profile instantly, with no
reinstall step. It is a deliberate design choice (documented in
`scripts/install-client-plugins.ps1`), and it also means **work-in-progress is live the
moment it is built**.

---

## 3. Timeline

| Time (local) | Event | Evidence |
| --- | --- | --- |
| Sep 11, 13:09 | `build.mjs`, `lib/index.js` created (pre-guard state) | file creation times |
| Sep 17, **10:19:26** | Engine starts, `pid 4880`, and **answers** | `engine-recovery.log`: *"port 3099 bound (pid 4880) and answering a patient probe"* |
| Sep 17, 10:22:49 | `src/guard.mjs` created — spend-guard WIP begins | file creation time |
| Sep 17, 10:24:33 | `src/guard-entry.mjs` created | file creation time |
| Sep 17, 10:27:35 | `lib/guard.js` first generated | file creation time |
| Sep 17, 10:34:12 | `cordis.patch.yml` edited — **`spend-guard` loader entry registered** | file mtime |
| Sep 17, 10:39:35 | `src/guard.mjs` edited | file mtime |
| Sep 17, 10:45:21 | `scripts/build.mjs` edited | file mtime |
| Sep 17, **10:45:26** | `lib/guard.js` + `lib/index.js` **rebuilt** | file mtime |
| *10:45 → 21:31* | Engine `pid 4880` **keeps running with the pre-guard tree in memory** — DSH appears fine all day | no `engine-recovery.log` entries in this window |
| Sep 17, **21:31:07** | **Machine reboots** | `Win32_OperatingSystem.LastBootUpTime` |
| Sep 17, 21:32:09 | First `ensure` after boot → engine not answering → start attempt 1/3 | `engine-recovery.log` |
| Sep 17, 21:33:17 / 21:34:33 | Further attempts, same result | `engine-recovery.log` |
| Sep 17, 21:35:18 | *"server on port 3099 exited with code 1"* + crash tail | `engine-recovery.log` |
| Sep 17, 21:35:22 | attempt 2/3 — the loop churns | `engine-recovery.log` |
| Sep 17, ~21:36 | Owner asks me to look at it | this conversation |

**The reboot is the trigger.** Before 21:31 the engine had the old plugin tree loaded in
memory and never had to load `spend-guard` at all. The reboot forced the first cold boot
since the 10:45 rebuild, and the cold boot is what fails.

---

## 4. Root cause

### 4.1 The immediate defect — a path missing `.dsh`

The engine's own error log (`~/.dsh/multi-window/logs/3099-20260917-213523.err.log`) is
unambiguous:

```
Error: dsh: plugin tree failed to load: failed to apply loader entry include (cordis:include):
  failed to import loader entry spend-guard (dsh-plugin-cost/guard)

Error: Cannot find module '@deepseek-ai/schemastery'
Require stack:
- C:\Users\ezabz\profiles\web\package.json      <-- missing ".dsh"
```

Everything follows from that one line. The generated `packages/plugin-cost/lib/guard.js`
builds its module anchor like this (lines 9–22):

```js
import { createRequire } from 'node:module';
function requireAnchor() {
  const home = (process.env.DSH_HOME && process.env.DSH_HOME.length > 0)
    ? process.env.DSH_HOME
    : (process.env.USERPROFILE || process.env.HOME || '');
  const sep = home.indexOf('\\') >= 0 ? '\\' : '/';
  return home + sep + 'profiles' + sep + 'web' + sep + 'package.json';
}
const require = createRequire(requireAnchor());
...
const Schema = require('@deepseek-ai/schemastery');   // line 22 — the failure point
```

With `DSH_HOME` unset, `home` becomes `C:\Users\ezabz`, and the anchor becomes
`C:\Users\ezabz\profiles\web\package.json` — a path with no `.dsh` in it. The real profile
is at `C:\Users\ezabz\.dsh\profiles\web\`.

I did not take this on faith. I measured resolution from both anchors:

| Anchor passed to `createRequire` | Result for `@deepseek-ai/schemastery` |
| --- | --- |
| `C:/Users/ezabz/.dsh/profiles/web/package.json` | ✅ resolves |
| `C:/Users/ezabz/profiles/web/package.json` | ❌ `MODULE_NOT_FOUND` |

and I loaded the module itself both ways:

| Environment | `import('.../plugin-cost/lib/guard.js')` |
| --- | --- |
| `DSH_HOME` unset | ❌ `MODULE_NOT_FOUND` |
| `DSH_HOME=C:\Users\ezabz\.dsh` | ✅ `LOADED` |

`DSH_HOME` was confirmed empty at **all three** scopes before the fix — session, User, and
Machine.

### 4.2 The deeper design error

This is the part worth writing down, because the fast fix hides it.

The comment above `requireAnchor()` in `scripts/build.mjs` states the author's reasoning:

> `createRequire` is only needed for `node:` builtins, which resolve from any existing path,
> so the anchor only has to be a real file.

**That premise is false, and the file it generates disproves it.** `importBindings()` in the
same `build.mjs` binds `node:` builtins *and* any bare package specifier:

```js
const external = removed.filter(
  ({ specifier }) => specifier.startsWith('node:') || (!specifier.startsWith('.') && ... ),
);
```

`@deepseek-ai/schemastery` is exactly such a bare specifier, and `guard.js` line 22 requires
it through `requireAnchor()`. So the anchor is **not** merely "a real file" — it must be a
location from which bare `@deepseek-ai/*` names resolve, i.e. a path inside the DSH home.

The comment also reveals the intent:

> the loader mounts this package through a junction in `~/.dsh/profiles/web/node_modules`,
> which is where a bare `@deepseek-ai/*` name resolves

The *intent* is right. The *fallback* does not implement it. `USERPROFILE` is not a valid
stand-in for `DSH_HOME`; it is the parent directory of `DSH_HOME`. Note that sibling source
files get this right — `src/session-log.mjs:23` uses:

```js
return process.env.DSH_HOME ?? join(homedir(), '.dsh');
```

…as does the launcher itself (`dshw.ps1:1568`):

```powershell
$home_dsh = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' }
```

So the correct fallback pattern already exists twice in this codebase. Only the generated
`requireAnchor()` omits the `.dsh` segment. This is a one-line generator bug with a
disproportionately large blast radius: it makes the whole engine unbootable.

A further observation: the design explicitly treats `DSH_HOME` as an *optional override*
("`DSH_HOME` still gives a test or a second engine its own resolver"). That means the
unset path is the **normal** path, not an edge case. The normal path was the broken one.

### 4.3 Why the launcher could not self-heal

`ensure` has a fast probe and a bounded retry (3 attempts), and it used both. But it has no
concept of *"the engine started and then crashed."* It only knows the port is not answering.
So the failure mode was:

1. Port held by a `dsh web` process that never answered (the holder changed between my
   checks — `3760` → `24200` → `9764` — so the retry loop was churning new attempts).
2. A fresh start attempts, boots, throws during plugin-tree load, exits `1`.
3. `ensure` sees "not answering" again and retries.

Then `restore` ran and opened windows against a dead port → `ERR_CONNECTION_REFUSED`,
which is precisely the symptom the launcher's own comments say it exists to prevent. The
guard did not fail; it was simply blind to crash-during-boot.

### 4.4 One more thing worth flagging

`restore` reported success and opened windows even though the engine had only just started
answering. That ordering is fragile: `ensure` returning "answering" does not guarantee the
plugin tree fully mounted. In this case it did, but the two steps are coupled only by the
probe.

---

## 5. What I actually did

The owner asked for a quick unblock. I did the minimum that restores function and leaves a
clean rollback, and I did **not** touch the WIP plugin.

| # | Action | Result |
| --- | --- | --- |
| 1 | Confirmed the shell was elevated | `True` |
| 2 | `[Environment]::SetEnvironmentVariable('DSH_HOME','C:\Users\ezabz\.dsh','User')` | persisted in `HKCU\Environment` |
| 3 | Killed the stuck `dshw.ps1 ensure` retry loop (`pid 16436`) | stopped the churn |
| 4 | Killed the wedged engine holding 3099 (`pid 9764`) | port freed (only `TIME_WAIT` remained) |
| 5 | Ran `dshw.ps1 ensure` with `DSH_HOME` set in the environment | **`engine is answering on 3099`** |
| 6 | Ran `dshw.ps1 restore` | **`13 of 13 remembered window(s) reopened`** |

I deliberately did **not** edit `packages/plugin-cost` or `scripts/build.mjs`:

```
M packages/plugin-cost/cordis.patch.yml
M packages/plugin-cost/lib/client.js
M packages/plugin-cost/lib/index.js
M packages/plugin-cost/package.json
M packages/plugin-cost/scripts/build.mjs
M packages/plugin-cost/test/verify.mjs
?? packages/plugin-cost/lib/guard.js
?? packages/plugin-cost/src/guard-entry.mjs
?? packages/plugin-cost/src/guard.mjs
?? packages/plugin-cost/test/guard.test.mjs
```

That is active uncommitted work-in-progress on the spend guard, and it is the very code that
broke. Editing the generator under someone mid-work would risk confusing the real fix with my
mask. So I masked, and I am flagging it.

**Rollback**, if ever wanted:

```powershell
[Environment]::SetEnvironmentVariable('DSH_HOME',$null,'User')
```

---

## 6. Verification

| Check | Result |
| --- | --- |
| Port `3099` listening | `127.0.0.1:3099` — `pid 4416` |
| HTTP probe `http://127.0.0.1:3099/` | **`401 Unauthorized`** — it *answers* (previously: timed out) |
| Newest engine error logs | `3099-20260917-213930.err.log` and `...213849.err.log` both **0 bytes** |
| Leftover DSH engines | `0` |
| `dshw status` | `1 engine(s) live` · engine RSS ~301 MB |
| Restored windows | launcher reported 13/13; Edge process groups confirmed |

The `401` is the correct signal here: the engine is alive and serving, and simply requires
auth for an unauthenticated request. A timeout was the failure signature; a `401` is health.

**Honest note on the window count.** At the time of writing, only one window group
(profile `w4`) remains live — the other restored windows were closed after the restore
completed. No launcher log records a close or reap, so the launcher did not close them.
(Also note `dshw status` under-reports when run from this shell: it read "1 window open"
while 19 Edge processes were present.) I am recording this as observed-but-unexplained
rather than guessing.

---

## 7. What is still open

### 7.1 The real fix (recommended)

Fix the generated anchor in `packages/plugin-cost/scripts/build.mjs` (around lines 71–82) so
the fallback matches the rest of the codebase:

```js
const home = (process.env.DSH_HOME && process.env.DSH_HOME.length > 0)
  ? process.env.DSH_HOME
  : (process.env.USERPROFILE || process.env.HOME || '') + sep + '.dsh';
```

(cleanest form: mirror `session-log.mjs` — `process.env.DSH_HOME ?? join(homedir(), '.dsh')`)

Then:

```powershell
cd C:\Users\ezabz\code\harness-config\packages\plugin-cost
node scripts/build.mjs
pwsh C:\Users\ezabz\code\harness-config\scripts\install-client-plugins.ps1 -Check
```

Re-test **without** `DSH_HOME` set, because a fix that only works with the env var is not a
fix. Best done after the spend-guard WIP is committed, so the change is reviewable on its
own.

### 7.2 Make the launcher inheritance-proof

`dshw.ps1` only *reads* `DSH_HOME`; it never sets one. So the engine depends on inheriting it
down `Explorer → cmd → pwsh → node`. I set the User-scope variable, and the elevation service
builds its environment block from the registry, so it *should* propagate — but **I could not
prove the elevated path end-to-end** without killing a healthy engine, which would have been
disruptive. If the next cold boot fails the same way, that is the tell, and the durable fix is
to set `DSH_HOME` explicitly inside `dshw.ps1` or `dshw-launch.cmd` so no inheritance is
involved.

### 7.3 Teach `ensure` about crash-on-boot

`ensure` currently cannot distinguish "port dead" from "process started, threw, exited".
Reading the exit code and the stderr tail of the attempt it just made — and surfacing that
tail to the owner instead of only logging it — would have turned a 10-minute investigation
into an instant answer. The stderr tail is already captured in
`engine-recovery.log`; it is just not shown at the point of failure.

---

## 8. Lessons

1. **A live-reload junction makes WIP instantly load-bearing.** A rebuild at 10:45 silently
   armed a fault that could not fire until the next cold boot — 11 hours later, on an
   unrelated reboot. "It works" after a rebuild proves nothing until the process restarts.
2. **Deriving a path from `USERPROFILE` is not deriving it from `DSH_HOME`.** The two differ
   by a segment, and the failure surfaces as `MODULE_NOT_FOUND` three layers away from the
   actual mistake.
3. **A comment asserting a premise is not evidence for it.** The comment said the anchor
   "only has to be a real file"; the code right below it required a bare package through that
   anchor. Reading the comment alone would have sent me down the wrong path.
4. **Retries without crash-awareness become noise.** Three polite attempts, and the answer —
   `exit code 1` plus a stack trace — was already in a log nobody was told to read.
5. **An env var that is unset is a configuration, not an absence.** `DSH_HOME` was documented
   as an override, so the default path was the one that ran — and it was the broken one.
6. **Masking is legitimate, but only when labelled.** The env var restores service; the
   generator still emits a wrong path. Six months from now, whoever reads the diff will
   otherwise believe the fix was the fix.

---

## Appendix A — raw evidence

Engine launch command:

```
"C:\Program Files\nodejs\node.exe"
  C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js
  web --port 3099 --no-open
```

Failure (tail of `3099-20260917-213523.err.log`, 5081 bytes, exits `1`, `Node.js v24.12.0`):

```
Error: dsh: plugin tree failed to load: failed to apply loader entry include (cordis:include):
  failed to import loader entry spend-guard (dsh-plugin-cost/guard)
Require stack:
- C:\Users\ezabz\profiles\web\package.json
Error: Cannot find module '@deepseek-ai/schemastery'
Require stack:
- C:\Users\ezabz\profiles\web\package.json
    at Module._resolveFilename (node:internal/modules/cjs/loader:1421:15)
    ...
    at file:///C:/Users/ezabz/code/harness-config/packages/plugin-cost/lib/guard.js:22:16
  code: 'MODULE_NOT_FOUND',
  requireStack: [ 'C:\\Users\\ezabz\\profiles\\web\\package.json' ]
```

The registered loader entry, from `packages/plugin-cost/cordis.patch.yml`:

```yaml
- insert:
  - id: plugin-cost
    name: dsh-plugin-cost
  - id: spend-guard
    name: dsh-plugin-cost/guard      # <- this row is what fails to import
    config:
      warnUsd: 35
      fanoutUsd: 80
      ceilingUsd: 150
      concurrencyCap: 12
      onInternalError: closed
```

Resolution measurement:

```
OK   C:/Users/ezabz/.dsh/profiles/web/package.json  ->  ...\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\schemastery\lib\index.cjs
FAIL C:/Users/ezabz/profiles/web/package.json       ->  MODULE_NOT_FOUND
DSH_HOME env = []
USERPROFILE  = [C:\Users\ezabz]
```

Module load measurement:

```
NO-ENV   RESULT: FAILED -> MODULE_NOT_FOUND
WITH-ENV RESULT: LOADED
```

`DSH_HOME` scope check, before the fix:

```
session DSH_HOME = []
User    DSH_HOME = []
Machine DSH_HOME = []
```

After:

```
User  DSH_HOME = [C:\Users\ezabz\.dsh]
```

Related reading in-repo: `scripts/install-client-plugins.ps1` (the "keeper" for profile
bundles), `docs/mesh/101-spend-guard-installed.md`,
`docs/multi-window/research-dsh-perf-config.md`.

---

## Appendix B — reproduction

To confirm the defect persists after the WIP is committed (i.e. that it is the generator and
not the environment), run the engine in a shell with `DSH_HOME` explicitly cleared:

```powershell
Remove-Item Env:DSH_HOME -ErrorAction SilentlyContinue
node --input-type=module -e "import('file:///C:/Users/ezabz/code/harness-config/packages/plugin-cost/lib/guard.js').then(()=>console.log('LOADED')).catch(e=>console.log('FAILED: '+e.code))"
```

- `FAILED: MODULE_NOT_FOUND` → the generator bug is still present
- `LOADED` → the fallback was fixed properly

That one-liner is the whole regression test for this incident.

---

## Addendum — the preceding handoff named this moment in advance

*(Added after this report was first written, when the journal was searched and `H461` was found.)*

`journal/entries/handoff/H461.md` (2026-09-17 14:47 UTC, ZABZ-YOGA) is the entry that staged this
change. From its own **BROKEN / NOT TRUE YET** section:

> The live engine (pid 4880) does NOT have the guard mounted. The bundle row takes effect at the
> next engine start.
> ...
> NEXT
> 1. Earliest safe moment: restart the web profile engine (or the next natural restart) so the
>    spend-guard row mounts, then look for ~/.dsh/spend-guard/day.json and one 'spend-guard: mounted' log line.

The `pid 4880` in that note is the same pid I observed in `engine-recovery.log` starting at
10:19:26 and answering a patient probe. So the sequence above is confirmed from two independent
sources: the engine that ran all day was the pre-guard engine, and the author knew the guard would
mount at the next start.

Two further points from H461 worth keeping:

1. It records `scripts/build.mjs` as emitting a "machine-independent require anchor". That is the
   precise claim that proved false in effect: the anchor bakes in no absolute path, but it resolves
   wrongly whenever `DSH_HOME` is unset.
2. It records its own untested path honestly: *"Engine-restart idempotence of day.json was
   unit-tested, never exercised on a real restart."* The guard's first real restart is the restart
   that killed the engine.

H461 is not a mistake to be corrected. It staged a change, verified it as far as a running process
allows, and named the moment it would take effect. The one thing it could not cover from inside a
live process was the cold-boot path — which is exactly where the defect lived.

**Note on house convention.** This incident was first written as a single file. It has since been
restructured to match `docs/incidents/2026-09-15-secretary-api-oom/`: one folder per incident,
containing `README.md` (the index and status) alongside this report and the raw evidence.
