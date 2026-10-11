# 167 — the frozen host was never a node-table problem: a placement is now gated on machine posture

**Machine:** ZABZ-TECH · **Worktree:** `_meshfrozen` @ `origin/main` = `4cb7600` (detached) · **Author:** a child on the
mesh thread. Reads only: nothing was started, stopped, masked, unmasked, enabled, disabled or restarted anywhere, and
`~/.dsh` was not touched. One bounded read-only ssh **to `secratary-cloud` (writable)** for the measurement in §5. The
frozen office box was **not contacted at all**.

Read first: **`docs/mesh/166-web-profile-office-references.md`** (the sibling that retargeted `brokerSsh` and reported
this defect rather than guessing at it).

## 1. The placement path, measured rather than assumed

A broker placement becomes a child in exactly one place, and it is not the broker:

```
provider.start()                                     packages/plugin-remote-fanout/lib/provider.js:504
  → placer.acquire()                                 lib/placement.js  (createNodePlacer)
      → broker.place({kind:'oneShot', …})            POST /place — the broker RANKS and names ONE node
      → placement.node                               ← a name in the BROKER's vocabulary (a Tailscale DNS label)
      → nodes[placement.node]                        lib/nodes.js NODES — the name becomes ssh + driver/bin/cwd
      → createSshTransport({target: facts.ssh})      the ssh destination the child actually runs over
  → transport.start()                                the child turn
```

`lib/nodes.js` is the dispatcher's table and the only thing that turns a broker-named node into a destination. Its
`secratary` row (lines 132–144) maps the node to **ssh `secratary-ts`** plus the office `driver`/`bin`/`cwd`
(`/home/zabz/node/bin/node`, `/home/zabz/dsh-current/…`, `/home/zabz/code`).

**Who consumes it:** `lib/placement.js` (broker placer), `lib/failover-placer.js` (the direct-probe fallback when the
broker cannot be *reached*), `bin/mesh-run.mjs`, and `packages/plugin-mesh-http/bin/mesh-dispatch.mjs`. The broker's own
roster (`packages/mesh-broker/nodes.json`) is a **separate** file; the broker never reads `nodes.js` and `nodes.js`
never reads the roster.

**Whether the `secratary` entry is reached at all: yes, three ways, all of them measured.**
1. the broker names it (its roster carries the row, so it is a candidate);
2. a human sets it — `MESH_TARGET_NODE=secratary-ts`, which makes `placement: 'fixed'` and goes through
   `createFixedPlacer`, bypassing the broker entirely;
3. the direct-probe fallback ranks it from the health documents when the broker is unreachable
   (`lib/failover-placement.js`), and its hint YIELDS rather than emptying the list.

**Nothing in `packages/**` consulted a posture file.** `grep -rn 'host-posture' packages/` was empty before this
change: the only readers were `scripts/mesh/guard-service-state.sh` (service state) and `AGENTS.md` (prose).

## 2. What is gated, and where the frozen set comes from

**New: `packages/plugin-remote-fanout/lib/posture.js`.** One module, one decision, read by every placer.

* It reads **`settings/machines/host-posture.tsv`** — the single authority `AGENTS.md` §5 names — and does **not**
  carry a copy of the frozen set. The estate's own rule is in that file's header: *"The guard reads the designation
  from HERE, never from a hardcoded list."* A second copy of "which hosts are frozen" is the drift that let this
  defect survive a claimed fix once already (§3 of `166`).
* Search order mirrors `guard-service-state.sh`, including the env var name: `HARNESS_CONFIG_POSTURE`,
  `HARNESS_CONFIG_ROOT/settings/…`, the repo-relative path resolved from `import.meta.url`, then the two conventional
  checkouts. The repo-relative candidate works in the live layout because
  `~/.dsh/profiles/web/node_modules/dsh-plugin-remote-fanout` is a **junction into the checkout** (measured on
  ZABZ-TECH) and Node resolves a module's realpath.
* The decision is the guard's own exit contract, so a reader who knows one knows the other:
  `frozen` → **refused, no override**; `read-only` → refused unless `allowReadOnly` (the analogue of
  `--owner-confirmed`; it **never** unlocks a frozen host); `writable` → allowed, and the reading is recorded;
  `undesignated` → refused (*"an unrecognised host is not permission"* — the guard's exit 4).
* **The file is re-read on EVERY acquisition, never cached.** A cached freeze is a freeze a later decision does not
  reach, which is the same class of defect in a smaller frame.
* A node is matched through **every spelling** it has (the broker name, the ssh alias, the host part of
  `user@host`, and the `hosts` list), and the **strictest match wins**: one frozen alias makes the node frozen. That
  is deliberate — `secratary` is a prefix of `secratary-cloud`, and confusing those two is the whole incident.

**Where the gate sits, and why it is on the ANSWER and not on the hint:**

| placer | hint sent to the chooser | the guarantee |
|---|---|---|
| `createNodePlacer` (broker) | every non-writable node is added to the broker's `exclude` | the node the broker **names** is checked; on a refusal the lease is **released unspent** (recorded), the ledger gets `state: posture-refused`, and no transport is ever built |
| `createFailoverPlacer` (direct probe) | same list, passed to `chooseFailoverPlacement` | the **winner** of the probe is checked |
| `createFixedPlacer` (`MESH_TARGET_NODE`) | — | the **ssh destination** (`target`) is checked |

`exclude` is SOFT by the broker's own contract (*queue, never amputate*: an exclusion that names every node yields),
so it cannot be the guarantee — a hint that hid the refusal would be a silent default. The check on the answer is the
guarantee, and the refusal is refused even though a lease is already held: dispatching anyway "because the lease
exists" is the argument that put a child on the anchor, and leaving it to expire would hold a slot on a host nobody
may use.

**Fail-closed, measured:** if the designation cannot be read at all (no file, unreadable, or zero parsed rows) the
placement is refused with `placement-posture-unknown` **before the broker is asked**, so no ssh is spent and no lease
is stranded; the error names the search order and the one-line remedy. Same choice `guard-service-state.sh` makes
when the file is missing.

**One boundary, stated rather than hidden:** a fixed placer given only a transport and *no* `target`/`node` cannot
name the machine it aims at. That case is **reported** (`posture.posture === 'unreadable'`) and warned about, not
refused — refusing it would refuse every embedding that passes only a transport, and the deployment path always names
its target (`target: !!js "process.env.MESH_TARGET_NODE ?? 'desktop-ts'"`, `profiles/web/cordis.patch.yml`).

## 3. `secratary`: legitimate node, kept, and never placeable

**Decision: KEEP the row, gated — and switch the broker's roster row OFF, rather than delete either.**

* The row is the measured record of a real machine (`verified`: a live child turn answered `SEC_OK`, 2026-10-08), and
  `nodes.js` is where that record lives. Deleting it would destroy the record and change `hostMatchesNode`'s
  behaviour for no safety gain, because the gate is what makes it unplaceable.
* The row's office paths were **left exactly as they are**. Retargeting only `ssh` would leave
  `driver`/`bin`/`cwd` pointing into `/home/zabz` — the half-migrated pair that took a node down on 2026-10-07/08
  (`6d686e4`) — and the cloud box's node paths are not a `secratary`-shaped thing anyway: pointing a node **named
  `secratary`** at `secratary-cloud` would be the exact alias confusion `AGENTS.md` §5 exists to prevent.
* `packages/mesh-broker/nodes.json`: the `secratary` row is marked **`"excluded": true`**, using the roster's own
  purpose-built mechanism (*"a node can be switched off in the roster without being deleted from it, so its absence
  from placement is a configuration fact rather than a network accident"*), with the reason in
  `_excluded_on_purpose` pointing at `host-posture.tsv` as the authority. Its `dispatch.v1` is already `null`
  (UNMEASURED — there is no `headless` profile on that box) and it is frozen with every writer stopped, so this is
  not journal **W209**'s defect (an excluded node that was actually working and had its capacity wasted). The broker
  must not spend a lease on a node the dispatcher will refuse.
* A **new decision is not created** by that flag: if the freeze were lifted, `excluded` would still hold the node out,
  visibly (the boot log prints `[SWITCHED OFF]`, `GET /nodes` reports *switched off in the roster*, and
  `_excluded_on_purpose` gives the reason). The dangerous direction — roster included, host frozen — is caught by the
  gate. That asymmetry is why the duplication is acceptable here and not in `nodes.js`.

## 4. What was deliberately NOT done

The sibling's classification in `166` §6 stands, and nothing in it was tidied: persona/history prose,
`settings/machines/SECRATARY.yaml`, `docs/**`, `journal/**`, `scripts/mesh/cutover-authority.sh` (naming the cutover
*source* is its job), `scripts/mesh-restart-when-idle.ps1`'s `$PLACEMENT_KEYS`, and the `dsh-update/tests/**`
fixtures that must keep their old bytes to remain fixtures.

**Still open, and reported rather than half-fixed** (the sibling's class A1, unchanged): runnable office-box commands
in prose — `AGENTS.md:81-82,145` (read-only `--stats`/`--check` invocations),
`presets/{cordis-bg,yocheved,zabz}/skills/lpt-production-case-work/SKILL.md:144-145` (a read-only audit), and
`presets/zabz/skills/secretary-wake/SKILL.md:111,133-136,179-180` (**`~/bin/wake.py` — this one can WRITE**). They are
not placement paths and were not touched. Fixing them properly means pointing them at `secratary-cloud`, and that
needs the cloud paths measured for each tool — which is a separate, owner-visible job, not a string swap.

## 5. The cloud box, measured — and NOT written into a node row

Measured 2026-10-11 over `ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1` (bounded, read-only; the ssh client
did not exit, which is the known defect — the output below is what it printed before the bound):

```
HOST=secratary-cloud
EXISTS /opt/company
EXISTS /opt/company/scripts/ps_mcp_server.py
EXISTS /opt/company/.venv/bin/python
EXISTS /root/.dsh
ABSENT /root/dsh-current
ABSENT /etc/dsh-worker.env
node=/usr/bin/node
```

**No node row was written for the cloud box, and this is the reason.** A dispatcher row needs a `@deepseek-ai/dsh`
`bin.js` path **and** a `headless` profile on the target to be a *verified* placement, and neither was measured
(`/root/dsh-current` is absent; `/root/.dsh` exists but its profile set was not read). Beyond the measurement gap,
`secratary-cloud` is **THE AUTHORITY and the sole writer of `/root/authority.db`**: deciding to run model turns on it
is a placement-policy decision that belongs to the owner, not to a child dispatched to close a placement path. So the
absence is recorded here instead of guessed at.

## 6. Proof

Everything below was run in the `_meshfrozen` worktree. `npm run verify` in `packages/plugin-remote-fanout`:
**222 tests, 220 pass, 0 fail, 2 skipped.**

**Frozen host refused, and nothing ran.** `test/posture.test.mjs` — a broker that NAMES `secratary` while a lease is
held: the acquire rejects with `placement-host-frozen`, the message carries the node, the token that matched, *what the
host is FOR*, who decided it, since when and what to read; `POST /done` is called with `(lease, false)` so the
reservation is **released unspent**; **no ssh transport is constructed at all**; the ledger holds
`state: posture-refused` with the broker's answer and the posture reading on it.

**A normal placement still succeeds.** The same suite places on `zabz-tech` and `zabz-tech-linux`: the placement and
the ledger carry `posture.posture === 'writable'`, `matchedBy`, and the file it was read from — and the broker request
carries `exclude: ['secratary']`.

**Fail-closed.** With the loader pointed at no candidate at all: `placement-posture-unknown`, and
`broker.calls.place.length === 0` — the broker was never asked.

**The other two placers.** `MESH_TARGET_NODE=secratary-ts` (fixed) is refused; a frozen winner on the direct-probe
path (broker unreachable, only the frozen node answering so the hint yields) is refused. Both in `test/posture.test.mjs`.

**The authority itself is asserted.** The same file reads the **real** `settings/machines/host-posture.tsv` and asserts
`secratary`, `secratary-ts`, `secratary-lan` and `192.168.50.77` are frozen, `secratary-cloud` is writable, **every**
node in `lib/nodes.js` is designated, and `secratary` is the **only** barred node.

**Two deliberate test changes**, each the change being visible: `placement.test.mjs`'s `ONESHOT` constant and
`pressure.test.mjs`'s four exclusion assertions now read `exclude: ['secratary']`, with the reason in the constant's
comment. `packages/mesh-broker` gains one assertion that the shipped roster switches the frozen box off *and* that a
reason exists for it — the W209 precedent.

## 7. The unhooked gate from `166` §7 — now hooked, in the place this estate actually runs checks

`make-preset-rows.mjs --check` was documented as living "in CI" and run by nothing: `.github/workflows/` is empty, there
is no root `package.json`, and the only caller was `dsh-update/tests/preset-rows/verify-managed-block.mjs`, which a
human must remember to run. **There is no CI to hook into, and building one would be the wrong instrument.**

**Where the estate actually runs its checks:** `scripts/sync.py` — the 15-minute HarnessSync tick that applies
committed HEAD onto `~/.dsh` on every machine, and which *publishes* exactly the artefacts this generator writes. It
already carried this convention: a precondition function plus a `report_step` that prints the verdict and **skips the
guarded step, never the sync** (`check_version_coupled`, added after the 2026-09-28 engine-line incident). That is the
smallest gate that exists, so the check went there rather than beside it.

**What was added:** `check_generated_preset_rows()` + `report_generated_step()`, gating the **profile** step only.

```
$ python scripts/sync.py --dry-run --hostname ZABZ-TECH
 profiles: generated preset rows UP TO DATE (--check: managed block UP TO DATE — …)
 profiles: version check passed (engine 0.2.0-rc.2)
 profile web: WOULD UPDATE cordis.patch.yml
```

**And with the artefact deliberately made one generation stale** (a line appended to
`profiles/web/presets.generated.patch.yml`, then `git checkout --` to restore):

```
 profiles: SKIPPED -- the committed generated preset rows are STALE: --check: DRIFT — profiles\web\presets.generated.patch.yml does not match what the converter would write
 profiles:           regenerate and commit them with `node scripts/make-preset-rows.mjs --install`; the live profile patch is left untouched
```

Note what is *not* skipped: `presets` still applies (they are the SOURCE and they are correct), and every other step
still applies. Only the file that is one generation behind its source is withheld — which is the whole of what §3 of
`166` asked for.

Two details that cost a run each and are now pinned by tests: the DRIFT verdict for the standalone artefact goes to
**stderr** while the managed-block verdict goes to **stdout**, so a check that reports "the first `--check:` line"
reports a cheerful UP TO DATE as the reason for a skip; and **neither skip message may contain the word `WOULD`**,
because `autosync.ps1` reads that word as "did not converge" and would stall the whole tick.

`tests/test_sync_generated_rows.py` — **5 tests, all passing** — covers up-to-date, drift (naming the artefact),
a check that cannot run, no `node` on PATH, and the **real** repo with the **real** generator: `status == 0`, so a
stale commit fails this test.

<!-- tags=placement,host-posture,frozen,posture-gate,nodes.js,mesh-broker-roster,generated-drift,sync.py,gate-not-hooked refs=166,L3668,L3511,H3416,4cb7600,d143fb7,W209,6d686e4 -->
