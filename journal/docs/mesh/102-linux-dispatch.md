# 102 — The linux node's dispatch: a working machine behind a broken invocation, and the two halves of the fix

**Program:** `docs/mesh/` (the dispatcher seam, `packages/plugin-remote-fanout/**`; stream S5's sibling to
`98-broker-fixes.md` §4). **Date:** 2026-09-17 (14:25–15:05Z). **Author:** a delegated session, not the owner.
**Reads with:** `98-broker-fixes.md` §4 (the measurement this fixes: the roster flag and the stale note),
`62-worker-runtime.md` §3.1–§3.2 (the version-stamped install that was never run in that form),
`76-broker.md` §5 item 15 (a capability is a dated measurement), `92-provider-placement.md` §5,
`71-mesh-program.md` §2.2–§2.4 (the frozen transport and the location proof).

**Provenance convention.** **MEASURED** = taken live in this session by running the thing, with the command
given. **READ** = read out of source, with `path`. **REFUSED** = asked for and not obtained, stated as a
refusal rather than a silence. Every number carries the run that produced it.

**What was NOT done.** No engine was started, stopped or restarted anywhere. The owner's laptop engine
**pid 4880** was alive with the same start time (`2026-09-17 08:51:07`) before the first command and after
the last. `zabz-tech-linux`'s own `dsh-engine` was **checked and left alone**: `ps` over its own sshd at
14:33Z and again at 14:47Z showed `MainPID 3572114`, `node … bin.js web --port 3099 --no-open
--trusted-host …`, uptime 15:23:01, with `phone-gate.py` (pid 3626230) in front of it — the machine's engine
was serving its own web UI, so it was not restarted, and every child this document dispatched was a
**fresh `--profile headless` process**, not a turn on that engine. `git commit` was not run. No file in
`packages/mesh-broker/**` or `packages/plugin-mesh-http/**` was touched.

---

## 1. The defect, in one line

**The machine was a working worker and the dispatcher's invocation was broken, and the roster recorded the
second fact as the first.** `zabz-tech-linux` completes a real v1 child turn through its own `dsh` wrapper
(`LINUX NODE OK`, exit 0, 3 s — `98` §4.1 row 7, re-obtained this session). The dispatcher, meanwhile, built
`<nodeExe> <dshBin> --profile headless <task>` from `lib/nodes.js`, where `nodeExe` was
`/home/zabz/.local/node-v24.12.0-linux-x64/bin/node` — a path that does not exist on the machine — so a child
placed there died before it ran and the mesh read the failure as "that node is weak".

This session's own before-measurement, through the **real dispatcher** (`bin/mesh-run.mjs -Node
zabz-tech-linux`, which bypasses the broker's flag entirely because it places by hand):

```
$ node bin/mesh-run.mjs -Prompt 'Delegate this to a subagent using the subagent_remote tool: …' -Node zabz-tech-linux -TimeoutMs 300000
mesh-run: {"phase":"result","outcome":"failed","reason":"only 0 MESH-HOST lines for 1 children (0 literal, 0 summarised)"}   exit 1
… the child's own report: "The child exited 127 in ~1.2s with no final assistant message.
  stderr tail: sh: 6: /home/zabz/.local/node-v24.12.0-linux-x64/bin/node: not found"
```

**And the path was only half of it.** With the interpreter path corrected, the same direct invocation fails
on the credential — because the thing that supplies it is the wrapper the dispatcher bypasses:

| # | MEASURED 2026-09-17, over `ssh linux-pc-ts` | result |
|---|---|---|
| 1 | `/usr/local/bin/node /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js --profile headless 'Reply with exactly: INTERPRETER FORM OK'` (path corrected) | **exit 1**, `dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official"; store DEEPSEEK_API_KEY … or export DEEPSEEK_API_KEY in the launching environment` |
| 2 | `dsh --profile headless 'Reply with exactly: LIVE CHILD OK'` (the wrapper, by name) | **exit 0**, framed, `MESH-HOST: zabz-tech-linux` |
| 3 | the same wrapper by name under `env -i PATH=/usr/local/bin:/usr/bin:/bin sh -s` — **`HOME` unset, `DEEPSEEK_API_KEY` absent from the environment** | **exit 0**, `EXECUTOR UNDER EMPTY ENV OK` |
| 4 | `cat /usr/local/bin/dsh` | `set -e`; `home="${HOME:-$(getent passwd "$(id -un)" | cut -d: -f6)}"`; `node="$home/.local/node/bin/node"`; `bin="$home/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js"`; `env_file="${DSH_WORKER_ENV:-/etc/dsh-worker.env}"`; `set -a; . "$env_file"; set +a`; `exec "$node" "$bin" "$@"` |
| 5 | `ls -l /etc/dsh-worker.env` | `-rw-r----- 1 root zabz 108`, keys `DEEPSEEK_API_KEY`, `DEEPINFRA_API_KEY` |
| 6 | `ls -l /home/zabz/.local/node-v24.12.0-linux-x64/bin/node` | **No such file or directory** — the row's old path |

Row 3 is the one that matters most: the wrapper does not need the ssh session's environment *at all* — it
resolves both paths from `$HOME` with a `getent` fallback and sources the credential file itself. **That is
why the fix is "invoke the executor by name", not "export a key into the ssh session".**

---

## 2. The fix, and why the shape is this one

**Two halves, and the credential half is the one that generalises.**

**Half 1 — the invocation is a decision, made in one place, and an executor wins when the node has one.**
`lib/nodes.js` gained `resolveNodeInvocation()` / `invocationForNode()` and a row shape with
`command` (an executor on the node's PATH) ahead of `driver` + `bin` (the interpreter fallback). The
generated program is built from that resolution (`lib/remote-script.js: invocationFor`, used by both script
builders), so **the script and the provider cannot disagree about how a node is launched**.

**Half 2 — the credential travels with the invocation, and the wrong path is gone.** The `zabz-tech-linux`
row's `command: 'dsh'` is the fix; its `driver` is now the **version-free symlink** `/usr/local/bin/node`
(`→ /home/zabz/.local/node/bin/node`, v22.23.2) rather than the version-stamped path that rotted, and its
`credentialEnvFiles: ['/etc/dsh-worker.env']` states where the credential comes from.

**Why an executor is preferred rather than a sourced env file.** They are not equivalent, and the difference
is measured:

* the wrapper sources the file **as root** (`/usr/local/bin/dsh` is `root:root 0755`, installed by
  `scripts/provision-mesh-node.sh`), so `root:zabz 0640` is readable to it;
* the dispatcher's `sh -s` session runs as **`zabz`**, which is in the file's group — but a node whose worker
  env file is `0640 root:root` would be **silently unsourceable** from the same script, and a silent skip is
  the failure mode this whole change exists to remove.

So the interpreter form does source `credentialEnvFiles` when a row names one (that is the honest fallback and
it is implemented and tested), but **the preferred form is the one where the machine owns the question**.

**What was discovered rather than assumed.** The executor, the interpreter, the credential file and the
absent path are all recorded in each row's `verified` string with the commands that produced them, because a
hardcoded path is exactly what broke this (`62-worker-runtime.md` §3.2's point). The table is computed from
the module, not typed into this document — `_scratch/102-invocation-table.mjs` prints it.

### 2.1 The per-node invocation table (computed, 2026-09-17)

| node | ssh | shell | form | command the dispatcher runs | credential source | how the form was determined |
|---|---|---|---|---|---|---|
| `zabz-tech` | `desktop-ts` | powershell | **interpreter** | `C:/Program Files/nodejs/node.exe …bin.js` | the dispatching process's own environment | Windows has no `dsh` executor on PATH; the parent engine runs with its key |
| `zabz-yoga-1` | `laptop-ts` | powershell | **interpreter** | `C:/Program Files/nodejs/node.exe …bin.js` | the dispatching process's own environment | same; `70-remote-fanout-proof.md` §4.4 records the relink that made it work |
| `zabz-tech-linux` | `linux-pc-ts` | posix | **executor** | `dsh` | the executor sources `/etc/dsh-worker.env` itself | `command -v dsh` → `/usr/local/bin/dsh`; `command -v node` → `/usr/local/bin/node`; config `0640 root:zabz`; the version-stamped path **absent** |
| `secratary` | `secratary-ts` | posix | **interpreter** | `/home/zabz/node/bin/node …bin.js` | the dispatching process's own environment (**checked**: no executor, no worker env file) | `command -v dsh` → nothing; `/etc/dsh-worker.env` and `/etc/secretary-worker.env` absent |
| `lakewooechsmini` | `mac-mini-ts` | posix | **interpreter** | `/usr/local/bin/node …bin.js` | the dispatching process's own environment (**checked**: no executor, no worker env file) | `command -v dsh` → nothing; no `/etc/dsh-worker.env`; `/usr/local/bin/node → …/node-v24.19.0-darwin-arm64/bin/node` |

**What is NOT verified, stated as a refusal.** That `secratary` and `lakewooechsmini` can complete a child
turn through the interpreter form. `secratary`'s credential is a service-environment fact this session did not
measure, and the mac mini has never been exercised as a worker (`62` §3.2). Both rows say so in `verified`,
and no flag was changed on the strength of a guess.

### 2.2 What was added beyond the two halves, and why each one earns its place

1. **A one-shot fallback (`shouldRetryWithFallback`).** If the executor cannot be *launched* — spawn failure,
   or `not found` / exit 127 with no frame — the run is retried **once** with the interpreter pair, and the
   report names both forms. Nothing else retries: a credential error, a timeout, a wrong answer and a
   cancelled run are the child's own outcome and are never silently re-run. The fallback is a fallback, and a
   fallback that is never exercised is one that is never checked.
2. **The invocation is printed in the child's own report** (`invocation = dsh --profile <profile> <task>
   [executor]`, `credential = …`). The whole cost of this defect was that a report could say "ran on node X"
   while the command it used could not have run there.
3. **The placement ledger records the invocation before the dispatch** (`placement.invocation`), so a
   placement that names a node also states how that node will be launched.
4. **A half-pair no longer resolves.** `{ nodeExe }` with no `bin.js` — or a `bin.js` with no interpreter —
   is not an invocation, and the provider refuses to mount on one. That is the config shape that produced
   `not found`.
5. **The generated POSIX program does not `set -e`**, deliberately: a failed `cd` must not skip the closing
   frame, because a missing frame is what turns a readable failure into a mystery. The hostname is captured
   with `printf -v` so the frame cannot interleave.
6. **`profiles/mesh` and `profiles/web` pass the new facts through** (`MESH_NODE_COMMAND`,
   `MESH_WORKER_ENV_FILES`), because the child engine boots its *own* provider from its own profile: a
   dispatcher that passes the executor only in its environment leaves the child on the interpreter form.
   That was caught live — the first post-fix `mesh-run` still died `MISSING_CREDENTIAL` (§4, run 3), and the
   cause was the installed profile copy, not the library.

---

## 3. The test that would have caught it

`test/nodes.test.mjs` (new, 11 tests). It reads the **broker's own roster** (`packages/mesh-broker/nodes.json`,
read-only — the file is not this session's to edit) and asserts the two properties the defect violated, for
every node that makes a v1 capability claim (`dispatch.v1 === true`, or no `dispatch` block at all, which is
the unmeasured state `secratary` is in):

1. **`every node this roster claims can take v1 work has a resolvable invocation`** — an executor, or both
   halves of an interpreter pair. The shipped row fails this immediately: it resolved to an interpreter whose
   path was a version-stamped one that did not exist.
2. **`every v1 node's invocation declares its credential source …`** — and an *interpreter-only POSIX row
   must name a credential file or record that it was checked and has none* (`!none`). This is the assertion
   that catches the **second** half: a row that fixes the path but still says nothing about the credential is
   rejected. The shipped row fails it (`UNKNOWN — nothing in this row says where a credential comes from`).

**And the test is not vacuous**: `the check above would have caught the shipped invocation` reconstructs the
shipped row, asserts it resolves to the interpreter form, asserts its driver carries the version stamp, and
asserts its credential source is `UNKNOWN` — i.e. it re-runs the §2 rejection against the old shape inside the
suite. The mutation proof is `§6`.

Also new: `remote-script.test.mjs` gained the executor form, the credential-sourcing order (the env file is
sourced **before** the child is launched), the half-pair refusal, the legacy `nodeExe`/`dshBin` reading, and
`shouldRetryWithFallback`'s five negative cases. `provider.test.mjs` gained executor-first dispatch, the
retry-once-then-report-both-forms path, and the rule that a credential error is **not** retried.

---

## 4. The proof: a real child on `zabz-tech-linux`, through the live code path

**Run 1 — the exact dispatch the provider performs, using only the package's own modules**
(`_scratch/102-live-child.mjs`: `nodes.js` → `remote-script.js` → `ssh-transport.js`, with the provider's own
`MESH-HOST` preamble). Task: *"Run the shell command `hostname` and then reply with exactly the text it
printed … Do not guess or copy the name from anywhere."* — worded that way on purpose, because a child that
can see its own node name in the prompt may echo it, and an echoed name proves nothing.

```
node        = zabz-tech-linux  (ssh linux-pc-ts, shell posix)
form        = executor
command     = dsh
credential  = the executor sources /etc/dsh-worker.env itself
--- the program the target runs (stdout lines only) ---
# invocation form: executor — the executor sources /etc/dsh-worker.env itself
cd '/home/zabz/code'
dsh --profile headless 'Report where you ran, first, … --- task --- Run the shell command `hostname` …'
--- dispatching ---
transport   = ssh linux-pc-ts
exit        = 0 in 8592 ms (framed=true)
host line   = zabz-tech-linux   cwd = /home/zabz/code
--- child final message ---
MESH-HOST: zabz-tech-linux
zabz-tech-linux
```

The child's own reasoning in stderr confirms it **ran the command** rather than guessing:

```
dsh: reasoning:
… Let me run hostname. I'll run bash hostname.
dsh: reasoning:
The output is "zabz-tech-linux". Now, the reply must begin with "MESH-HOST: zabz-tech-linux" …
```

**Run 2 — the full dispatcher, `mesh-run`, with a real `subagent_remote` child** (this is the shape the
provider ships: a local parent that delegates):

```
$ node bin/mesh-run.mjs -Prompt 'Delegate this to a subagent using the subagent_remote tool: …' \
      -Node zabz-tech-linux -TimeoutMs 300000
mesh-run: {"phase":"run","node":"zabz-tech-linux","alias":"linux-pc-ts","shell":"posix",
  "invocation":{"form":"executor","command":"dsh","driver":"/usr/local/bin/node",
                "bin":"/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js",
                "credentialEnvFiles":["/etc/dsh-worker.env"],
                "credentialSource":"the executor sources /etc/dsh-worker.env itself"}, …}
mesh-run: {"phase":"run-end","node":"zabz-tech-linux","exitCode":0,"timedOut":false,"ms":22584,…}
mesh-run: {"phase":"verify","node":"zabz-tech-linux","meshHostLines":1,"meshHostLinesLiteral":1,
           "childHosts":["zabz-tech-linux"],"disagreements":[],"ok":true}
mesh-run: {"phase":"result","outcome":"completed","node":"zabz-tech-linux","childHosts":["zabz-tech-linux"]}

----- dispatcher output -----
Delegated via `subagent_remote` (I didn't run the command myself).
**Child's reply:**
MESH-HOST: zabz-tech-linux
```

**exit 0**, one `MESH-HOST:` line, naming `zabz-tech-linux`, zero disagreements. The same command exited **1**
with `only 0 MESH-HOST lines` at 14:35Z, before the fix — `§1`.

**Run 3 — the failure that proved the profile half was needed.** The first post-fix `mesh-run` (14:45:40Z)
still failed:

```
mesh-run: {"phase":"run-end",…,"exitCode":0,…}   # the PARENT was fine
the child's report: the remote one-shot exited 1 after ~3s with no final message:
  dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official"; …
```

Cause: the child engine boots its own provider from `~/.dsh/profiles/mesh/cordis.patch.yml`, which was the
**stale copy** (2026-09-16 19:27) with no `remoteCommand` passthrough — so the executor the dispatcher had
resolved never reached the child. `node bin/install-mesh-profile.mjs` re-materialised it from
`profiles/mesh/cordis.patch.yml` (idempotent; it also rewrote the manifest and re-checked the bundles), and
run 2 above is the result. **This is worth knowing for any node, not just this one: a dispatcher that passes
the invocation only in its own environment leaves the child on the old form.**

---

## 5. The diffs

`git diff --stat` for the owned paths (the tree keeps its uncommitted state, which is how it arrived):

```
 packages/plugin-remote-fanout/bin/mesh-run.mjs     | 131 +++----
 packages/plugin-remote-fanout/lib/index.js         | 166 +++++++--
 packages/plugin-remote-fanout/lib/provider.js      | 380 +++++++++++++++++++--
 packages/plugin-remote-fanout/lib/remote-script.js | 183 +++++++++-
 packages/plugin-remote-fanout/package.json         |  11 +-
 packages/plugin-remote-fanout/test/provider.test.mjs      | 316 ++++++++++++++-
 packages/plugin-remote-fanout/test/remote-script.test.mjs | 102 +++++-
 profiles/mesh/cordis.patch.yml                     |  18 +-
 profiles/web/cordis.patch.yml                      |  47 ++-
 9 files changed, 1160 insertions(+), 194 deletions(-)
```

**Read that stat honestly:** those files were already modified in the working tree when this session started
(`lib/nodes.js`, `lib/placement.js`, `lib/broker-client.js` and three test files are untracked, so they do not
appear in the diff at all), so the ± counts are against `HEAD` and **not all of them are mine**. This
session's changes are:

* **`lib/nodes.js`** — the row shape (`command` / `credentialEnvFiles` / `driver` / `bin` replacing
  `nodeExe` / `dshBin`), `normalizeNodeFacts()`, `resolveNodeInvocation()`, `invocationForNode()`,
  `invocationResolvable()`, `DEFAULT_WORKER_ENV_FILES`, and a re-measured `zabz-tech-linux` row plus
  re-confirmed `secratary` and `lakewooechsmini` rows.
* **`lib/remote-script.js`** — `shellWord`, `invocationFor`, `shouldRetryWithFallback`,
  `psCommandLine`, the `taskWord` rule, and both script builders rebuilt from a resolved invocation (the
  interpreter form sources its credential file first; the executor form does not double-source it; no
  `set -e`; `printf -v` hostname).
* **`lib/provider.js`** — the invocation is resolved per run from the placed node's facts, the fallback retry,
  `describeInvocation` / `fallbackInvocation`, the invocation lines in the report and the ledger, the
  "no invocation" throw, and the `remote` block carrying `command` / `credentialEnvFiles`.
* **`lib/remote-script.js`, `lib/provider.js`, `package.json`** — the new tests are registered; `npm test` and
  `npm run verify` both run `test/nodes.test.mjs`.
* **`bin/mesh-run.mjs`** — `MESH_NODE_COMMAND` / `MESH_WORKER_ENV_FILES` / `MESH_NODE_EXE` / `MESH_DSH_BIN`
  passed from the placed node's row, and the resolved invocation recorded in the run log.
* **`profiles/mesh/cordis.patch.yml`, `profiles/web/cordis.patch.yml`** — `remoteCommand` and
  `remoteCredentialEnvFiles`, documented in each header, executor first.
* **`test/nodes.test.mjs`** — new. `test/remote-script.test.mjs`, `test/provider.test.mjs`,
  `test/placement.test.mjs` — the new cases.
* **`_scratch/102-live-child.mjs`, `_scratch/102-invocation-table.mjs`, `_scratch/102-empty-env-probe.sh`** —
  the drivers that produced `§2.1`, `§2`, `§4`. Scratch by the repo's convention, not part of the package.

---

## 6. Verification: every claim, its command, its result

| claim | command | result (MEASURED, 2026-09-17) |
|---|---|---|
| every source file parses and the whole suite passes | `cd packages/plugin-remote-fanout && npm run verify` | **exit 0**; `tests 89 · pass 89 · fail 0` |
| the package's own suite passes | `npm test` | **tests 89 · pass 89 · fail 0 · duration_ms 5378** |
| the suite grew by the right tests | `node --test --test-name-pattern "" test/nodes.test.mjs` and `npm test` | `nodes.test.mjs`: **tests 11 · pass 11**; the package total is **89** (`npm test`), of which 11 are the new file and 8 are new cases in the two edited files |
| **the new check fails on the shipped row** | `resolveNodeInvocation()` on the row as it was, inside the suite | `form: interpreter`, driver `/home/zabz/.local/node-v24.12.0-linux-x64/bin/node`, `credentialSource: UNKNOWN …` — both §3 assertions fire (`the check above would have caught the shipped invocation`) |
| the shipped invocation is *live* broken, through the dispatcher | `node bin/mesh-run.mjs … -Node zabz-tech-linux` at 14:34Z | `exit 1`; child report: `sh: 6: /home/zabz/.local/node-v24.12.0-linux-x64/bin/node: not found` (exit 127) (`§1`) |
| the corrected path is *still* not enough without the wrapper | `/usr/local/bin/node …/bin.js --profile headless '<task>'` over ssh | `exit 1`, `MISSING_CREDENTIAL: llm-deepseek` (`§2` row 1) |
| the executor succeeds under a stripped, login-less, credential-free environment | `env -i PATH=… sh -s` piped over ssh, then `dsh --profile headless …` | `HOME=[<unset>]`, `KEY=<absent>`, **`EXECUTOR UNDER EMPTY ENV OK`, exit 0** (`§2` row 3) |
| a real child runs on the node through the live modules | `node _scratch/102-live-child.mjs zabz-tech-linux` | exit 0 in 8592 ms, framed, `host line = zabz-tech-linux`, child ran `hostname` (`§4` run 1) |
| a real child through the full dispatcher names the machine | `node bin/mesh-run.mjs -Prompt 'Delegate … subagent_remote …' -Node zabz-tech-linux` | **exit 0**, `meshHostLines 1`, `childHosts ["zabz-tech-linux"]`, `disagreements []`, `outcome completed` (`§4` run 2) |
| the value is measured, not echoed | the child's own stderr in run 1 | `"Let me run hostname. I'll run bash hostname."` → `"The output is \"zabz-tech-linux\""` |
| the per-node table is computed, not typed | `node _scratch/102-invocation-table.mjs` | the table in `§2.1`, printed from `nodes.js` |
| the executor/credential facts are what the machine actually has | `ssh linux-pc-ts 'command -v dsh; command -v node; ls -l /etc/dsh-worker.env; cat /usr/local/bin/dsh'` | `/usr/local/bin/dsh`; `/usr/local/bin/node` → v22.23.2; `-rw-r----- root zabz 108`; the wrapper that sources it (`§2` rows 4–6) |
| the other three nodes' forms are measured, not inherited | `command -v dsh` and the env-file check over ssh on `secratary-ts`, `mac-mini-ts`; `nodes.js` for the Windows pair | both POSIX nodes: no executor, no worker env file; the Windows pair: no executor on PATH (`§2.1`) |
| the profile rows parse and the passthrough is installed | `python -c "yaml.safe_load(...)"` on both patched profiles; `node bin/install-mesh-profile.mjs` | **YAML OK** for both (2 and 4 top-level entries); `install-mesh-profile: ready` |
| the owner's engine was never touched | `Get-Process -Id 4880` | alive, same start time `2026-09-17 08:51:07` |
| the linux node's engine was never touched | `ps` over its sshd at 14:33Z and 14:47Z | same `MainPID 3572114`, uptime 15:23:01, `web --port 3099` still serving; every child was a fresh `--profile headless` process |

**One thing this session changed on the owner's machines**, stated plainly because it is a write:
`node bin/install-mesh-profile.mjs` re-materialised `C:\Users\ezabz\.dsh\profiles\mesh\` (its documented,
idempotent job: manifest, plugin link, patch copy, bundle check). It wrote nothing outside
`$DSH_HOME/profiles/mesh/`, and it did not restart anything.

---

## 7. What could not be verified, stated as refusals

* **A live child on `zabz-tech-linux` chosen by the BROKER.** The broker's roster still says
  `dispatch.v1: false` for this node (`98` §4.3), and `packages/mesh-broker/**` is not this session's to
  edit. Every live dispatch here therefore used `mesh-run -Node zabz-tech-linux`, which **bypasses the broker**
  (`-Node` places by hand) and takes exactly the same provider path afterwards. **The one-line roster change
  is handed over in `§8` and has not been made.**
* **A child on `secratary` or `lakewooechsmini` through the interpreter form.** Not run: the brief named the
  linux node, and their rows say `v1: null` / never exercised. The interpreter form's path resolution is
  unit-tested; the credential for `secratary` is a service-environment fact this session did not measure.
* **Whether `sh -s` and the mesh transport differ in how the wrapper's stdin is used.** The wrapper was
  measured from Windows through `sh -s` under `env -i` (`§2` row 3) — the same program, the same non-tty,
  non-interactive conditions the transport creates. It was **not** run through `ssh-transport.js` with
  `env -i`, because the transport does not offer an environment override; the transport path itself was
  proven by `§4` run 1, which used it.
* **The `102-*` scratch drivers on any node other than the linux one.** They take a node name argument but
  were only run against `zabz-tech-linux`.
* **Whether any other consumer reads `placement.facts.nodeExe` / `dshBin`.** The field names in
  `placement.facts` changed to `driver` / `bin` (the old spellings are still *read* by the resolver, so a
  profile that passes them keeps working). A grep over `harness-config` found one other node table —
  `packages/plugin-mesh-http/bin/mesh-dispatch.mjs`, which is not this session's file and **still hardcodes
  `/home/zabz/.local/node-v24.12.0-linux-x64/bin/node` for this node (line 113)**. It is a second copy of
  this same table and the same class of bug; reported, not touched.
* **`markerSettled` on POSIX runs.** Both live runs settled on the ssh client's own exit
  (`markerSettled=false`) rather than on the completion frame, so the frame-poll path was not exercised on
  this node. The runs completed correctly; the observation is recorded because a future session will see it.

---

## 8. What the next session should know

1. **The dispatcher half is done; the roster half is one line and is not mine.** `packages/mesh-broker/nodes.json`
   for `zabz-tech-linux` — `dispatch.v1` can go back to `true`, with its `evidence` string replaced by the
   measurement above. **Recommendation: set it `true`**, because a child placed there now runs (`§4` run 2),
   and the `false` was a dispatcher defect wearing a node defect's clothes. The condition `98` §4.2 named is
   satisfied on both counts it listed — the invocation is corrected *and* the credential reaches the process,
   the second by using the executor rather than by exporting a key.
2. **Do not put a version-stamped interpreter path in `lib/nodes.js`.** That is the whole lesson
   (`62-worker-runtime.md` §3.2). A row's `driver` should be a stable symlink or an executor name, and the
   test in `test/nodes.test.mjs` asserts it for the linux row.
3. **A node with an executor must be invoked through the executor, and the child engine needs the same
   facts.** `MESH_NODE_COMMAND` / `MESH_WORKER_ENV_FILES` are the passthrough; without them a child boots the
   interpreter form and dies `MISSING_CREDENTIAL` (`§4` run 3). If a node is added, add its row to
   `lib/nodes.js` **and** re-run `node bin/install-mesh-profile.mjs`.
4. **`plugin-mesh-http/bin/mesh-dispatch.mjs` carries a second copy of this table with the rotted path**
   (`§7`). It is not in this package; it should be made to read `lib/nodes.js` or be corrected the same way.
5. **The `dsh` wrapper is the node's contract, not a convenience.** `scripts/provision-mesh-node.sh`
   installs it, it resolves the interpreter from `$HOME` and sources `DSH_WORKER_ENV` (default
   `/etc/dsh-worker.env`) itself. A dispatcher that names an interpreter bypasses all three facts at once.
