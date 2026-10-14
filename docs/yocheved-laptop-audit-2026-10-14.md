# DESKTOP-FGV6KMH — end-to-end audit, 2026-10-14

Yocheved's laptop. Written after a full session of measuring, breaking, fixing and re-measuring.
**Every claim below carries its evidence.** Where something is unverified it says so.

Owner's reports this session, and where each stands:

| report | status |
|---|---|
| "keeps stopping to work" | **FIXED** — she was crash-looping; root cause found and closed |
| "no yocheved mode, opens in standard" | **HALF** — `yocheved` now REGISTERS; it is still not the DEFAULT |
| "can't reach the provider / message transport failed" | **FIXED** — engine was dead, not the provider |
| "it says DeepSeek Flash Vision, not 4.1 Flash" | **FIXED** — model + label |
| "can't load" selecting a model | **on the proxy it works, measured**; DeepSeek-direct cannot work behind the filter |
| "model operation failed waiting for workflow engine tool ralph" | **FIXED** — a renamed package her preset still named |
| sidebar new-session / workspace-picker bugs | **new-session works at the protocol level**; picker blocked by a first-run overlay |

---

## 1. The crash-loop — root cause, and it is the September outage again

`harness-sync.mjs` on her `master` lineage had **no `declaresBundle` guard at all** (14,705 B, blob
`25b2a6a9`). The fleet's has it (15,770 B, blob `4e2da4d5`), added by commit `75dd24c8` —
*"sync: never NAME a package that declares no dsh.bundle - **the root cause of her recurring outage**"* —
and `git merge-base --is-ancestor 75dd24c8 db24b4ea` returns **1**: **that fix never reached her lineage.**

The sync therefore wrote `dsh-mesh-broker` into `dsh.profile.bundles` **while its own log line said it
would not** ("declares no dsh.bundle.patch — naming it in the profile would stop the engine booting").
`dsh-app-boot:852` throws for a named bundle with no marker, so **the engine could not start at all**.
It crash-looped at least four times in one evening; the health watchdog restarted 3099 every minute just
to watch it die. **That one fault produced "can't reach the provider", "no yocheved mode" and the
picker doing nothing — the engine was simply not running.**

Fixed by delivering the guard to `master` (`141e9f7c`). **Proven across a sync:**
```
BEFORE sync: 11 bundles; mesh-broker named? False
AFTER  sync: 11 bundles; mesh-broker named? False
```
Log and file now agree, and that agreement is the fix.

## 2. The preset — 0.1.5 discovers by directory, 0.2.0 requires generated rows

`scripts/make-preset-rows.mjs` generates one `preset-<name>` **row** per user preset and splices them
into `profiles/web/cordis.patch.yml`. The tool said it about her box:

```
--check: DRIFT -- the `preset-rows` managed block is absent from profiles\web\cordis.patch.yml;
         the generated rows are not in any layer the engine loads.
```

and its own header states the consequence — *"leaves `settings.agent-presets.default: zabz` naming a
[preset that does not exist] — **silently, with no error**."* That is the missing yocheved mode exactly:
**it vanished because of the 0.1.5 → 0.2.0 move**, which is the migration that script performs.

Rows generated, installed into the live profile, **and committed** (`9217c876`). **Proven durable across
her updater:** `repo rows=9, live rows=9` before and after. Verified present in the booting config:
`- id: preset-yocheved / name: '@deepseek-ai/dsh-agent-preset' / order: 11`.

Live roster, measured (full body):

```
standard(1,isDefault:true) ptc(2) minimal(3) cordis(4)
cordis-bg(10,trust:user) yocheved(11,trust:user) zabz(12,trust:user)
```

**OPEN: `standard` is still `isDefault: true`.** `settings.yaml` says `agent-presets.default: yocheved`
but `/api/session/create` returns `agentPreset: "standard"`. So the default is not coming from that
settings key on 0.2.0. **This is the last thing standing between her and a working yocheved mode.**

## 3. The renamed package that broke every model operation

`scripts/check-version-coupled-config.py` against her 0.2.0-rc.2 engine:

```
presets/cordis-bg/agent.cordis.yml
  line 225   MISSING @deepseek-ai/dsh-workflow-worker-thread
  line 233   ok      @deepseek-ai/dsh-tool-ralph
```

0.1.5 ships `dsh-workflow-worker-thread`; 0.2.0 ships **`dsh-workflow-ptc`**. Her presets named the old
one, so the **workflow engine could not mount**, and every model operation gated on it failed with
*"model operation failed waiting for workflow engine tool ralph"* — for every model. `dsh-tool-ralph`
was present and fine; it is the thing that waits.

Renamed in all 5 files (`0a8d4ba4`). **Re-run of the guard: `MISSING lines: 0` —
"every name resolves — engine 0.2.0-rc.2, 195 occurrences, 29 distinct packages, 5 files".**

## 4. The company bridge was pointed at the FROZEN office box

`presets/zabz/agent.cordis.yml` L437 targeted `secretary-ts` on a row that **is enabled on Windows**
(L420 `disabled: !!js process.platform !== 'win32'`). The file's own comment 150 lines below describes
this exact defect as the estate's worst recorded failure — *"every DSH session on Windows ran the company
bridge against the OFFICE box… `ps_db_query` returned the office's 135,455 SMS rows where the authority
held 135,486"*. **The comment documented the fix; the row never got it.**

Measured: **nine `ssh: Could not resolve hostname secretary-ts` on every engine boot** (497 B of stderr),
and on any machine where it resolves the bridge answers from a shadow copy of the company.

Retargeted to `secratary-cloud` (`82456550`; interpreter path verified to exist there). **Boot stderr is
now 0 bytes.** Also removed the same frozen box as the attention badge's fallback authority
(`8568ca06`, `eda221e1`).

## 5. Model

Default was pinned to `deepseek-v4-flash-vision-exp` since 2026-09-14. Her config's own measurements say
`deepseek-flash` reads images at the same speed (IMAGE 3/3 381ms vs 400ms), so the pin bought nothing.
Default is now `deepseek-flash`, **labelled `DeepSeek V4.1 Flash`** (`098efe7a`, `574a23ce`).

**Selecting it works — measured by clicking it:** `CLICKED text="DeepSeek V4.1 Flash" (n=1)` with **no
failing request**. "DeepSeek direct" cannot work from her laptop: that route's host is `api.deepseek.com`,
which the Techloq filter blocks. The reachable path to the same model is the proxy.

## 6. Two sync bugs still open

1. **The sync leaves `settings.yaml` missing.** It writes `settings.yaml.imported` and never completes the
   rename; both sync tasks then report **`result=0`** — success over incomplete work. The file was
   genuinely absent from disk (not a transient; I mis-read that twice). Mitigated with a
   `Yocheved Settings Watch` task (5-min, restores from `.imported` if absent). **The sync itself needs fixing.**
2. **The sync does not deploy `profiles/web/cordis.patch.yml`** into `~/.dsh` — repo had 9 preset rows,
   live had 0 after `HarnessSync`. The rows were installed by hand. `make-preset-rows.mjs --check`
   belongs in the sync path, which is what that script recommends.

## 7. Verified state

```
engine      : 0.2.0-rc.2 pin at ~/.dsh/engine, pid 19536, port 3099, boot stderr 0 bytes
settings    : present, 1433 b, model deepseek-flash, agent-presets.default: yocheved
profile     : 11 bundles, mesh-broker NOT named, cordis.patch.yml 116,243 b / 9 preset rows
guard       : check-version-coupled-config.py -> MISSING lines: 0
roster      : standard ptc minimal cordis cordis-bg yocheved zabz  (yocheved registers)
session API : POST /api/session/create -> ok:true, sessionId session-91f4d3d1-...
instruments : Engine Watchdog(1m) Window Fleet Watchdog Profile Gate(15m) Engine Vitals(5m)
              Yocheved Settings Watch, Yocheved DSH Window, YochevedExecWatchdog  -- all Ready
launcher    : open.cmd 8116 b, windowstate 7024 b, focuswindow 7497 b, sync guard present,
              dsh-new:// registered in cheve's hive
presets     : yocheved live 31,787 b, skills = cordis-plugin-development, dissertation-and-research,
              editing-cordis-compositions, lpt-production-case-work, parallel-agent-orchestration
backup      : ~/.dsh/backups/sessions-pre-0.2.0-rc.2-20261013-211549, 92 files, 13,277,777 bytes
git         : her checkout HEAD 82456550 on master
```

## 8. Method notes, because this took far too long

Five separate mechanisms were asserted in this area and four were wrong. Every wrong one came from
skipping one of these:

* **Never reason from a truncated body.** A `.slice(0, 240)` on the roster JSON cost four rounds — I
  "knew" `yocheved` was absent from a list I had cut.
* **Never assert on `document.body.innerText`.** Opening a session leaves it identical. Assert on
  structure a session *creates* — and even a row count can lag: **`/api/session/create` returning
  `ok:true` is the authoritative signal.**
* **Check a machine where the thing WORKS before theorising about why it fails.** The owner's `zabz`
  registering with an identical `preset.yml` killed four hypotheses in one look.
* **Read the tool that documents its own failure mode FIRST.** `make-preset-rows.mjs` had been sitting in
  the repo describing this silent fallback the whole time.
* **One job per call.** Her exec channel has a hard 60-second cap; batching several jobs into one call is
  why so many calls died mid-way.
