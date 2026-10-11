# 165 — the web profile's last office-box reference: the real generator, and the row the generator does not own

**Machine:** ZABZ-TECH · **Worktree:** `_officefix-web` @ `origin/main` = `074bac9` · **Author:** child on the
mesh thread, dispatched after L3668. Read-only against `secratary`; no service was restarted anywhere.

## 1. The generator is `scripts/make-preset-rows.mjs` — and it is genuinely a generator

The artefact is **derived**, confirmed by reading the converter rather than inferring it from the name:

| what it reads | what it writes |
|---|---|
| `presets/<name>/agent.cordis.yml` (the row list) | `profiles/web/presets.generated.patch.yml` (standalone, block style) |
| the same, plus `order = 10 + index in ascending name order` | the `preset-rows: BEGIN/END` managed block **inside `profiles/web/cordis.patch.yml`** (flow style) |

The row list is copied **verbatim** (`config.plugins`), and the converter re-parses its own output and proves
the `!!js` source texts survive byte-for-byte before it writes. `--install` splices only the lines between the
markers and proves the text outside them is byte-identical. So the generated file is **not** hand-maintained;
hand-editing it was correctly refused by the previous child.

**The managed block in `profiles/web/cordis.patch.yml` is lines 294–1643.** Everything before 294 and after
1643 is hand-authored and is **not** owned by the generator. That boundary is the whole story below.

## 2. What the previous child reported is now fixed — the record is corrected here

L3668 reported `profiles/web/cordis.patch.yml` 962-964 / 1515-1517 and `presets.generated.patch.yml` 862-864
holding `secretary-ts`. **Those rows already read `secratary-cloud` on `origin/main`.** Commits **`bb73261`**
("point the secretary bridge at the cloud authority, not the shadow office box", 20:13Z) and **`e51de44`**
("the regenerated preset-rows block", 20:17Z) landed the fix at the source *before* L3668 was written; the
line numbers in L3668 were the pre-fix ones and shifted. Verified: all three `serverName: secretary` rows in
the web profile now target `secratary-cloud`, and the Linux one runs `/opt/company/.venv/bin/python
/opt/company/scripts/ps_mcp_server.py`. **No MCP row in the web profile points at the office box.**

## 3. What was actually still wrong, and why it regenerated itself back

### (a) The generator was in committed drift — `--check` exits 1 on `origin/main`

```
$ node scripts/make-preset-rows.mjs --check     # on origin/main
--check: DRIFT — profiles/web/presets.generated.patch.yml does not match what the converter would write
  first difference at line 29
  committed: ...presets/zabz/agent.cordis.yml rows=26 sha256=c6d0121d70621bebb9ef056ad4a502338772eeabe45b5c8afe90e40168c9c380
  generated: ...presets/zabz/agent.cordis.yml rows=26 sha256=7c79b04f237aac4f2a87640157a862a43b178ed6f83496f4a4a25aab5dc47cf2
--check: DRIFT — the `preset-rows` block in profiles/web/cordis.patch.yml does not match ...
EXIT=1
```

Two deltas only: the recorded source sha256, and the `owner-queue` paragraph inside `preset-zabz`, which the
source had already rewritten to `ssh secratary-cloud` while the generated copies still said
`` **on `secratary` only** — … `ssh secratary-ts "python3 ~/bin/owner-queue.py next"` ``. **A generated artefact
one generation behind its source is exactly the mechanism by which a fixed row comes back.**

### (b) `brokerSsh` — the one office *service target* left in the web profile

`profiles/web/cordis.patch.yml:137`, **outside** the managed block, so no generator owns it:

```yaml
brokerSsh: !!js "process.env.MESH_BROKER_SSH ?? 'secratary-ts'",
```

This is the ssh destination the mesh broker is on, i.e. **where a dispatched child is run**.
`settings/machines/host-posture.tsv` marks `secratary`, `secratary-ts`, `secratary-lan` and `192.168.50.77`
**`frozen`**; `secratary-cloud` is `writable` and the sole writer of `/root/authority.db`. So the profile's
default placed children on the rollback anchor.

**This is a recurrence, and the record shows it.** Handoff **H3416** (06:29Z) states the row *was* changed
`secratary-ts` → `secratary-cloud` "and the change propagated to the live `~/.dsh/profiles/web/cordis.patch.yml`".
Measured now, all three read `secratary-ts`: `origin/main`, the dirty working tree, and the live layer
(mtime 2026-10-11 20:16:38). The change never reached a commit, so a later sync restored the office value —
**which is precisely why a fix belongs in the repo and not in `~/.dsh`.**

## 4. The change, at the outermost layer each artefact has

1. **Source presets (`presets/*`) — no change needed.** They already target `secratary-cloud` / `/opt/company`,
   and neither `secretary-ts` nor an office `/home/zabz` path appears in any preset **row**.
2. **Generated layer — regenerated, not hand-edited:**
   ```
   node scripts/make-preset-rows.mjs --install
   ```
   ```
   wrote profiles/web/presets.generated.patch.yml (79920 bytes, 945 lines)
   updated the managed block in profiles/web/cordis.patch.yml (patch entries 17 -> 17, 1350 lines)
   outside the block: byte-identical, sha256 5779c0f409bd819d… (proved by removing the block region from both texts and comparing)
   ```
   `--check` afterwards: **`UP TO DATE` for both, exit 0.**
3. **The hand-authored row the generator does not own** — `profiles/web/cordis.patch.yml:137`
   `'secratary-ts'` → `'secratary-cloud'`, with the reason written in the file in that file's own convention
   (the same reason H3416 intended, which is what was lost).

`git diff --stat`: `profiles/web/cordis.patch.yml | 21 ++++++------`, `presets.generated.patch.yml | 4 ++--`.
`~/.dsh` was **not** touched. No engine, service, unit or cron was started, stopped or restarted.

## 5. Proof, by the engine's own composition path

Both runs use the pinned candidate engine
(`…\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js`, `0.1.5-rc.1`) and the real
`--dump-config`/`applyEntryPatches` path, with the repo's own `cordis.patch.yml` as a patch layer so the
**repo** file is what is being measured. `origin/main`'s version was extracted with
`git show HEAD:profiles/web/cordis.patch.yml`, so the "before" is the committed bytes, not a remembered state.

```
node dsh-update/lib/compose.mjs --profile web --bin <pin> \
  --patch profiles/web/presets.generated.patch.yml --patch <cordis.patch.yml> \
  --out <tree.json> --log-dir <logs>
```

Reading the composed `remote-fanout` row out of each tree:

```
BEFORE (origin/main) -> [{"brokerSsh":{"__js":"process.env.MESH_BROKER_SSH ?? 'secratary-ts'"}}]
AFTER  (this change) -> [{"brokerSsh":{"__js":"process.env.MESH_BROKER_SSH ?? 'secratary-cloud'"}}]
```

Re-applying the profile therefore no longer points the broker at the office box. And the round-trip check:

```
node dsh-update/tests/preset-rows/verify-preset-rows.mjs --bin <pin> --profile web
RESULT: PASS — every checked claim held      (compose exit 0, 169 rows, 19/19 !!js byte-identical,
                                              preset-{cordis-bg,yocheved,zabz} deep-equal to source)
```

**Zero office-box service targets remain in the web profile.** The only `secratary-ts` strings left in it are
inside **yocheved's persona prompt**, as example commands that read from the server
(`node $M file secratary-ts /home/zabz/x.txt`, `node $M env secratary-ts …/.env` at
`presets.generated.patch.yml:309-310` and the block's copy at `cordis.patch.yml:686,688`) — the read-only
`file`/`env` verbs, not a service. They are the next tidy-up, listed in §6.

## 6. Remaining office references in the repo, classified

**A. `POSTURE = frozen` (from `settings/machines/host-posture.tsv`). "Would run something on the frozen box"
is the test; only class A1 is the defect this artifact fixes.**

**A1 — a path used to run something on the frozen box (a defect):**

| file:line | what | status |
|---|---|---|
| `profiles/web/cordis.patch.yml:137` | `brokerSsh ?? 'secratary-ts'` — the broker's ssh destination | **FIXED here** |
| `packages/plugin-remote-fanout/lib/nodes.js:132-144` | node `secratary` → `ssh: 'secratary-ts'`, `driver: /home/zabz/node/bin/node`, `bin: /home/zabz/dsh-current/…`, `cwd: /home/zabz/code` — the table that turns a broker-named node into a destination, so a placement on `secratary` **runs a DSH child there** | **REPORTED, not changed** — see below |
| `presets/zabz/skills/secretary-wake/SKILL.md:111,133-136,179-180` | runnable `ssh secratary-ts "python3 ~/bin/wake.py …"` — the wake CLI would be driven on the frozen box | **REPORTED** |
| `presets/{cordis-bg,yocheved,zabz}/skills/lpt-production-case-work/SKILL.md:144-145` | runnable `ssh secratary-ts '/home/zabz/personal-secretary-mvp/.venv/bin/python3 /home/zabz/repos/lpt-hub/tools/customer/audit.py'` | **REPORTED** |
| `AGENTS.md:81-82,145` | runnable `ssh secratary-ts 'python3 ~/code/harness-config/scripts/transcript-archive-server.py …'` and the owner-queue one-liner, in the file every agent reads | **REPORTED** |
| `journal/profiles/web/cordis.patch.yml:137`, `journal/packages/plugin-remote-fanout/lib/nodes.js:114-116` | archived copies of the same two rows, still `secratary-ts` | **REPORTED** (archive) |

**Why `nodes.js` was NOT changed.** `secratary` is a real mesh node and its roster entry is legitimate (the same
is true of `packages/mesh-broker/nodes.json:46-49`). Retargeting only its `ssh` field would leave the office
`driver`/`bin`/`cwd` and produce exactly the half-migrated pair that took a node down on 2026-10-07/08
(commit `6d686e4`) — and the cloud box's node/dsh paths are **unmeasured** from here. A guess is worse than a
report. Also measured: **nothing gates placement on frozen posture** — `packages/**` consults no posture file
(the `frozen` hits there are all the *frozen slot arithmetic*), so `nodes.json` still offers `secratary` as a
placement candidate with no runtime refusal. That is the next migration item, and it needs a design decision
(drop the node from the roster, or add a posture gate), not a hostname swap.

**A2 — a path in the profile used only when a Linux node runs a child, where the Linux branch is generic:**
`profiles/web/cordis.patch.yml:190-193` and `profiles/mesh/cordis.patch.yml:115-118`
(`remoteNodeExe`/`remoteDshBin`/`remoteCwd` → `/home/zabz/…`). Not office-specific by construction, but
`remoteCwd: '/home/zabz'` is an office-shaped default. Reported, unchanged.

**B. Documents that mention it — legitimate, leave alone:** `presets/zabz/agent.cordis.yml:28,69,89,110,595` and
`presets/yocheved/agent.cordis.yml:51,63,117,118,460` (persona/history prose), their generated copies,
`presets/*/skills/{fast-search,parallel-agent-orchestration}/SKILL.md`, `settings/machines/SECRATARY.yaml`
(the frozen-box mission file, which is *supposed* to name it), `docs/**`, `journal/docs/**`,
`journal/entries/**` (H3416, L3668, D251/D257, docs 92/100/103/105), `scripts/mesh/cutover-authority.sh:28-29`
(`${CUTOVER_OFFICE_DB}` — naming the office *source* of a cutover is its job),
`scripts/mesh-restart-when-idle.ps1:161` (`$PLACEMENT_KEYS` contains `brokerSsh` as a key **name**),
`dsh-update/tests/fixtures/raw/dump-config-web-0.1.5-rc.1.txt:590` and
`dsh-update/tests/switch/fixtures/**` (captured fixtures; they must keep the old bytes to stay fixtures).

## 7. The reason the drift survived, and the one-line fix for it

`make-preset-rows.mjs` documents its own `--check` as existing "in CI rather than a one-off". **Nothing runs
it.** `.github/workflows/` is empty, there is no root `package.json`, and the only caller is
`dsh-update/tests/preset-rows/verify-managed-block.mjs`, which runs when a human runs it. So the committed
artefact was free to sit one generation behind the source indefinitely — which is how a corrected row came
back. Wiring `node scripts/make-preset-rows.mjs --check` into whatever runs the estate's gates would have
caught this on 2026-10-11 and will catch the next one.

<!-- tags=generator,web-profile,office-row,brokerSsh,three-layer-drift,host-posture refs=L3668,L3511,H3416,bb73261,e51de44,165 -->
