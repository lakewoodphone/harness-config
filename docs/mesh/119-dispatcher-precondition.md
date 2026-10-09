# 119 — The dispatcher's own precondition: a green probe is not a placement

**Program:** `docs/mesh/`. **Date:** 2026-10-09, 00:15–00:35Z. **Author:** a delegated session, not the owner.
**Owns:** `packages/mesh-broker/nodes.json` (the `zabz-yoga-1` row) and its deployment at
`/home/zabz/mesh-broker/nodes.json`; the profile-junction state of the node `zabz-yoga-1`.
**Reads with:** `76-broker.md` §5 item 15 and §10.4 (a capability is a dated measurement, ranked
`false` below `true`), `70-remote-fanout-proof.md` §4.4 (the untrusted-reparse-point condition and
the only remedy that works), `102-linux-dispatch.md` and `104-node-enabled.md` (the same shape of
decision on another node).

**Provenance convention.** **MEASURED** = taken live in this session by running the thing, with the
command given. **READ** = read out of source or a document, with the path. **REFUSED** = asked for
and not obtained, stated as a refusal rather than a silence. Every number carries the run that
produced it.

**What was NOT done.** No engine was started, stopped or restarted anywhere; in particular the
broker on the authority was **not** restarted, and no `dsh` session on any node was interrupted. No
`rm -rf` was run: the 83 links removed were individual junctions whose target provably does not
exist, removed with `rmdir` on the link (which never touches a target). The owner's packages were
not modified, moved or reinstalled. `packages/plugin-remote-fanout/**` and
`packages/mesh-broker/lib/**` were read, never edited. Nothing was published; the broker is
loopback-only and `tailscale serve` still carries nothing on 3091. The roster value was deliberately
**not** flipped to `false`, and §6 says why.

---

## 1. The finding in one line

`packages/mesh-broker/nodes.json` read `dispatch.v1: true` for `zabz-yoga-1`, and the mesh's own
probe agreed — while the dispatcher refused the node at its own precondition. Two instruments answer
"can this node take v1 work", they disagreed for 40 minutes, and the roster was being written from
the weaker one.

The wake row that produced this session (`mesh-node-dispatch-failed:zabz-yoga-1`, filed
2026-10-08T23:15:20Z) instructed: *re-measure, set `dispatch.v1` to false with the evidence, and fix
the node.* The re-measurement below **confirmed a real, reproducible refusal**, and the node was
repaired the same hour — so the flag's *prescription* (`false`) would have been immediately stale and
was not applied. `true` is the measured value; §6 records that decision and its basis.

## 2. The two instruments, and what each one actually measures

| instrument | invocation | what it proves | result 2026-10-09 |
|---|---|---|---|
| `~/bin/mesh-node-probe.sh` (cron, every 15 min) | `ssh zabz-yoga-1 <node.exe> <dsh>/lib/bin.js --profile headless '<prompt>'` | that a child **can be started over that node's sshd** and returns a final message | **ok, exit 0, `MESH-PROBE-OK`, 12 s** (00:17:11Z) |
| `mesh-run.mjs` (the dispatcher) | `probeTraversal()` **before** a parent is started — reads one child through 5 EXISTING links under `<DSH_HOME>/profiles` | that the sshd session can **resolve the profile bundle**, which is the precondition for any child | **REFUSED** at `phase=traversal` before the repair (00:23:18Z); **ok** after it (00:28:16Z, 00:28:53Z) |

The probe's green is real but partial. It never calls `probeTraversal`, so a node whose profile
bundle is unresolvable from the sshd session can read green for as long as the links it happens to
need are intact — and then every **dispatch** placed there dies while the roster says it works. That
is the sense in which the 2026-10-08 revision of this row, which certified the node on probe-only
evidence, was wrong.

## 3. The failure that filed the flag — verified, and it was real

**READ+MEASURED.** `~/.mesh-probe/cron.log` on the authority records two consecutive failing runs,
`ok=false exit=1 6000 ms` and `ok=false exit=1 5000 ms`; the first filed the wake row (`filed`), the
second `deduped`.

**The cause, from the child's own stderr:** the node's credential file carried two stray **top-level**
keys beside `version`/`refs`/`records` — `LPT_VERIFICATION_EMAIL` and `LPT_VERIFICATION_PASSWORD`, an
LPT production verification login that a verification session parked there at
2026-10-08T23:10:19Z. `dsh-credentials-local` **rejects** an unknown top-level key, so the whole
store failed to load and the one-shot died `dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for
provider route "deepseek-official"`.

**Repaired 23:39:43Z** by indenting both keys under the existing `refs:` mapping; the original is kept
as `.credentials.yaml.bak-straykeys-20261008T233942Z`. A dependent session then re-measured the
one-shot `ok` (23:39:52Z) and wrote `dispatch.v1: true` at 23:47:56Z (commit `f1d73288`).

**MEASURED in this session, after all of that:** the credential file is 860 bytes, last written
2026-10-08T23:39:43Z, top-level key set exactly `{version, records, refs}` with the two LPT keys
indented at depth 2 under `refs:` — and a real headless child turn returned `MESH-PROBE-OK`, exit 0,
12 s. That repair **holds**.

## 4. The failure the probe cannot see — and the reason `true` was still wrong

**MEASURED, 00:23:18Z.** `mesh-run -DshBin <dsh> -Node zabz-yoga-1` exits **1** at
`phase=traversal`:

```
mesh-run: node "zabz-yoga-1" cannot accept v1 ssh work: this node's sshd session cannot traverse a
reparse point (2 of 5 link(s) :: C:\Users\ezabz\.dsh\profiles\node_modules\accepts :: Could not find
a part of the path 'C:\Users\ezabz\.dsh\profiles\node_modules\accepts'.)
```

**MEASURED, full audit of `<DSH_HOME>/profiles` on the node:** 492 junction directories, **150
unreadable**, and they are two different faults that the 5-link sample reports as one:

| population | count | evidence | nature |
|---|---|---|---|
| target provably gone | **83** | `Target` under `_npx\1e7f6d9597241db0\node_modules` no longer exists | stale entries from an older install generation. `healProfilesModuleFallback` (`@deepseek-ai/dsh-app-boot/lib/index.js`) treats a junction whose target string already matches as current, and these fall outside the current dependency closure, so it never repairs them. |
| target exists, link unreadable | **67** | `cmd /c type <link>\package.json` → **`The path cannot be traversed because it contains an untrusted mount point.`** | the `70-remote-fanout-proof.md` §4.4 condition, **recurred**. The same read through the target succeeds. |

The refusal's *wording* was therefore partly false — the sshd session **can** traverse reparse points
on this node (a real child turn over that same sshd returns `MESH-PROBE-OK`); what it cannot read is
67 links that are untrusted and 83 whose target is gone. The distinction is recorded here rather than
fixed in code, because §4.4 is explicit that trust "must be probed, never assumed" and this session
did not measure the correct predicate for a stale link.

## 5. The repair, and its proof

**MEASURED, 00:27:36Z, run from inside an ssh session** (the §4.4 rule: a link created in another
logon session is not trusted by sshd, so a relink from a local session is a no-op):

1. the 83 provably-dangling links reaped — `rmdir` on the link only; manifest kept at
   `C:\Users\ezabz\.dsh\profiles-links-repair-20261009T002707Z.txt`;
2. the 67 untrusted links deleted and recreated with the **same target**, `New-Item -ItemType
   Junction` — **67 relinked, 0 failed**.

**Verified:**

| check | before | after |
|---|---|---|
| junctions under `<DSH_HOME>/profiles` | 492 | 409 |
| unreadable over the node's own sshd | 150 | **0** |
| full audit | — | **409/409 traversable** |
| `mesh-run` `probeTraversal`, from the authority | REFUSED | **`MESH-TRAVERSAL=OK existing 5 of 5 link(s) traversable`** (00:28:16Z) |
| `mesh-run` `probeTraversal`, from `zabz-tech` | not run | **`ok:true`** (00:28:53Z) |
| broker `GET /nodes?fresh=1` | — | `state=ok`, `slots 12`, `freeSlots 12`, `transport.v1 true` (00:20Z) |

The row was then rewritten with the measured evidence (§6) and deployed — repo and `/home/zabz/mesh-broker/nodes.json`
are byte-identical at `3c820e20dc934ba908974d08c922cc75aec1a7e852c29fc5b1aa02f8e1361885` — committed as
`e3b2448e`. `node --test packages/mesh-broker/test/` → **71/71 pass**. `node --test
packages/plugin-remote-fanout/test/` → 153/182 with **5 fail / 24 cancelled, an identical set with
and without this change**, so those are pre-existing on the authority and not attributable here.

## 6. Why the roster was NOT set to `false`

The flag asked for `false`. Three measurements are why the written value is `true`:

1. **`false` is a claim, and it was false.** By the time this session measured the node (00:27:36Z)
   the precondition passed: `probeTraversal` `ok:true` from two machines and 409/409 junctions
   traversable. `76-broker.md` §5 item 15 makes the capability a dated measurement **in both
   directions**; a stale `false` on this very node is item 15's worked example of wasting 12 effective
   slots.
2. **The value did not need changing to tell the truth.** The roster already read `true`; what was
   wrong was its **evidence**, which certified the node on the probe's one-shot and declared the
   reparse-point cause "stale" while it was live. The commit therefore rewrites
   `dispatch.evidence` and `note` — naming both faults, the repair, the revoke clause, and the rule
   that a green probe is not a placement — and leaves `v1: true`, which is the measurement.
3. **Flipping and flipping back is the churn this document exists to stop.** The authority already
   carries the mirror evidence: `mesh-node-probe.sh` filed `mesh-node-dispatch-restored:zabz-yoga-1`
   at 23:45:31Z, four minutes after a session had flipped the row to `false`, and that row is `done`.
   A second pair of flips inside 20 minutes would have been noise around a value that never changed.

**What would have made `false` the right write:** if the repair had failed, or if
`mesh-run -Node zabz-yoga-1` had still exited 1 at `phase=traversal` afterwards. It did not, so
`false` is not on the record.

## 7. Left open — measured, handed back, deliberately not repaired here

1. **The instrument gap is the actual regression.** `~/bin/mesh-node-probe.sh` measures only the
   one-shot, so it cannot see a profile-bundle precondition that the dispatcher enforces. Until the
   probe runs the same `probeTraversal` (or the roster requires a real dispatch as its evidence), a
   node can read green while every dispatch to it is refused. `dispatch.v1`'s evidence field now
   carries that rule; the probe itself was **not** changed, because it runs every 15 minutes on the
   authority and this session did not test a modified instrument.
2. **The authority cannot run the mesh parent at all.** `MEASURED`: `/usr/bin/node` is **v20.20.2**,
   and `dsh` refuses (`exit 78`) with *"this launcher needs Node >= 22.18"*; its `<DSH_HOME>/profiles`
   also has no `mesh` profile. So `mesh-run` from the authority fails at `phase=run` (exit 78) even
   when the target is healthy.
3. **`zabz-tech` cannot boot the `mesh` profile either.** `MEASURED`: `--profile mesh headless` exits
   1 with `Cannot find package '@deepseek-ai/dsh-agent-preset-registry' imported from
   C:\Users\ezabz\.dsh\profiles\mesh\`, and that package is absent from both
   `profiles/node_modules/@deepseek-ai` and the npx install. Until 2 and 3 are fixed, **no** dispatch
   can be placed on any node from either machine, which is a fleet-wide blocker larger than this row.
4. **A production LPT verification login was parked in a DSH credential file.** `LPT_VERIFICATION_EMAIL`
   / `LPT_VERIFICATION_PASSWORD` (users.id 300, role MANAGER, live RDS) spent 29 minutes as top-level
   keys in `C:\Users\ezabz\.dsh\.credentials.yaml`, where any stray key disables the node's entire
   credential store. The repair preserved both values verbatim under `refs:`; whether that login
   should exist in that file at all is an owner/security question, not a mesh one, and is **not**
   decided here.
