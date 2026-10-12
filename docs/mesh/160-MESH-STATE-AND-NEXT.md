# 160 — MESH: WHAT WAS DONE, THE STATE OF THINGS, AND WHAT TO DO NEXT

**This is the one document to read.** It is a map, not a replacement: every claim below names the
document or file that carries its full evidence, and every state line carries the moment it was
measured. Written 2026-10-12 03:50Z from ZABZ-YOGA by the session that did the work.
**Subject:** the mesh (fan-out to subagents), audited after the 2026-10-11 office→cloud cutover,
at the owner's request: *"check the entire mesh system in regards to orchestrating fanning out in sub
agents and make sure that it works even better than before and nothing is broken and everything got
faster … the parents able to talk to the children and the children to the parents."*

---

## 1. The state of things, measured (2026-10-12 03:05–03:45Z)

| thing | state right now | measured how |
|---|---|---|
| **placement broker** | **running on the authority** `secratary-cloud` (`127.0.0.1:3091`), `active` + `enabled` since 03:18Z; roster = 5 nodes with the frozen box `excluded: true`; reads 3 live nodes; a real placement returns `position 0, tier fits` | `systemctl is-active/is-enabled`; `curl /healthz` → `ok=true nodes=5 leases=0`; `POST /place` → released |
| **the old broker** | **still `active`/`enabled` on the FROZEN office box** — one live dependency left on a box declared inert; two brokers keep two lease ledgers | `systemctl is-active mesh-broker` on `secratary-ts` |
| **nothing changed on the frozen box** | every command against it in this work was a read (`systemctl is-active/cat`, `ss`, `sha256sum`, `curl`, `cat`) | the session's own command log; `docs/mesh/131-MIGRATION-BRIEF.md` Rule 1 |
| **`zabz-tech`** | healthy: `/mesh/health` 200, `/mesh/capacity` 200, 18 free slots, 32 cores | gate probes from the laptop and from the cloud |
| **`zabz-yoga-1`** (this laptop) | healthy: 200 / 200, 12 free slots. Its `/mesh/health` reports `host: "zabz-yoga"` while `node: "zabz-yoga-1"` — harmless today | same |
| **`zabz-tech-linux`** | dispatchable and used: a child ran there, exit 0, 31 s. Answers **404 on `/mesh/health`, 200 on `/mesh/capacity`** (its gate forwards only the latter) | broker placement record + the child's own report |
| **`lakewooechsmini`** | not down, but unreachable from the broker: `/mesh/capacity` answers a *live* document to a listed device, ssh times out at 12.4 s, and `tailscale status` says `offline`. Costs **4,000 ms** on every cold placement | probes from the laptop and the cloud; see §5 step 4 |
| **`secratary`** (frozen) | answers capacity 200, refuses the cloud with 403, `excluded` from the roster, refused by `lib/posture.js` | probes + `settings/machines/host-posture.tsv` |
| **the gate allow-list** | the authority is listed in `zabz-tech`, `zabz-yoga-1`, `zabz-tech-linux`. **Not** on the Mac mini, **not** on the frozen box (both deliberate) | the file + `curl` from the cloud |
| **dispatcher defaults** | the repo names the authority in **both** paths (provider row and `mesh-run.mjs`). Installed profiles on each machine still name the office box until that machine's engine restarts (P210) | `profiles/web/cordis.patch.yml`, `bin/mesh-run.mjs` |
| **fan-out itself** | **works.** Two real children placed by the broker, on two different nodes, `MESH-HOST` matched both times, exit 0 | child reports `subagent-238`, `subagent-246` |
| **parent ↔ child while a child works** | **does not exist** for a mesh child: `list_agents` → `(no subagents)`, `send_message` → `subagent "…" is unavailable` mid-turn. Child → parent = its final report, plus a mailbox thread that is **not created for the child** | measured live, §4 |
| **tests** | `plugin-remote-fanout` 222 tests, **220 pass / 0 fail / 2 skip**; `mesh-broker` **72/72** | `node --test` on a quiet machine |
| **git** | local `main` = `origin/main` = `ce8912cf`, no divergence. **The GitHub mirror has diverged** and the GitHub half of every push fails | `git status -sb`; P3135 |

---

## 2. What was done, and why each thing mattered

**1. A staged broker that could read nothing was made to work — and that was the real finding.**
The broker had been "staged but not started" on the authority since 2026-10-11 while every installed
dispatcher still used the copy on the frozen office box. Starting the staged copy was not enough:
measured from the cloud, **every node answered `HTTP 403 "Not signed in"`**, the broker read **5 of 5
nodes as unreachable**, and its answer to a real job was blind — `zabz-tech, position 1, blockedBy
["unreachable","no-free-slots"]`. A broker that reads nothing still answers, so this state was worse
than not moving at all. Cause: the nodes' gates (`scripts/phone-gate.py`) refuse any tailnet device
not listed in `phone-gate-allow.txt`, and the authority was never listed. Fixed by listing it, with
the cost and two one-line reverts written into the file itself.
→ **`docs/mesh/159-MESH-POST-MIGRATION.md` §2.1** · journal **L3737** (the lesson) · **D3050** (the decision)

**2. The half-applied retarget was closed.** After the cutover the provider row already named
`secratary-cloud` while `bin/mesh-run.mjs` still named `secratary-ts` — two dispatch paths, two
brokers, one of them on a box declared inert. Both now name the authority.
→ **`docs/mesh/159` §1** · journal **L3739** is the *different* amendment hazard found the same hour

**3. The staged roster would have placed work on the frozen anchor.** The cloud copy of
`/opt/mesh-broker/nodes.json` did not mark the frozen office box `excluded`, unlike the repo roster.
Replaced with the repo roster (old copy kept as `nodes.json.bak-20261012`).

**4. The broker-unreachable fallback was throwing working nodes away.** It read only
`/mesh/health`, which two live nodes answer **404** and **502** while answering `/mesh/capacity` 200,
so the path that exists for exactly the case "the broker is down" could see two of four working
machines. It now falls back to capacity, marks such a node *usable over v1 with slots UNMEASURED*,
ranks it below every measured node, and keeps `position 0` (unknown is not short). No slot arithmetic
was reimplemented on the dispatcher — that lives only in the broker.
→ **`docs/mesh/159` §2.2** · journal **L3738** · code: `packages/plugin-remote-fanout/lib/node-probes.js`, `lib/failover-placement.js`

**5. The record was put where the next session reads first.** The systems register still said the
broker runs on the office box; it now says the authority, and carries three new traps (a half-applied
retarget; a control plane that reads nothing and still answers; a pinned comment mistaken for a fix).
→ **`docs/mesh/000-SYSTEMS-REGISTER.md` §1, §2.3, §4**

**6. Fan-out was proven, not assumed.** Two children, two nodes, both `MESH-HOST` matched, both exit
0, leases released; plus a direct v1 child turn on `zabz-tech-linux` (exit 0, 13.6 s). → journal **W2738**

---

## 3. What was measured about speed — including what is NOT faster

| measurement | value |
|---|---|
| ssh round trip, laptop → office box (5 calls) | avg **790 ms** (716–905) |
| ssh round trip, laptop → cloud (5 calls) | avg **810 ms** (700–983) |
| broker `POST /place` cold / warm | **6,768 / 856–1,211 ms** (office); **6,826 / 1,124–2,577 ms** (cloud) |
| broker `POST /done` | 1,391–1,618 ms per child |
| the single largest cold term | one node that cannot be read: `timed out after 4000 ms` (§5 step 4) |

**The move is not a speed win by itself** — the transport floor is the same either way. What changed
is that placement is no longer *blind*, that two nodes are back in the fallback's ranking, and that
the control plane no longer lives on a box that goes off and cannot be woken. No claim is made that a
dispatch feels faster. → **`docs/mesh/159` §3**, **`docs/mesh/143-TRANSPORT-POLICY.md`** (the LAN /
Tailscale / Cloudflare precedence this respects)

---

## 4. The owner's actual question: can the parent talk to the child?

* **Parent → child, while it works: NO.** Measured live: `list_agents` → `(no subagents)` and
  `send_message` → `Error: subagent "subagent-246" is unavailable` while that child was mid-turn.
  This is the engine's shape, not a mesh fault — a remote child is never a *resident continuable*
  child, and `send_message` requires one. → **`docs/mesh/119-mesh-fanout-audit.md` §6** (the engine
  audit it comes from)
* **Child → parent: YES, but only in two ways.** Its final report always arrives (proven twice). The
  designed progress channel is a durable mailbox thread on the child's node — and **nothing creates
  that directory for the child**, so on `zabz-tech-linux` the header pointed at
  `/home/zabz/code/.dsh-mesh-mailboxes/<id>/inbox.jsonl`, which did not exist, and the report said
  `0 message(s)` while the conversation was silently empty. → **`docs/mesh/159` §4.2**, §5.3
* **A mesh child is a full agent** with `subagent`, `send_message`, `list_agents` and `subagent_fork`
  in its toolbelt (verified from the child's own report), so depth beyond one hop exists — its own
  children are local to its machine unless the mesh profile is named there.

---

## 5. What to do next, in order

**Step 1 — needs the owner (queue #447).** Stop and disable the office box's broker, so one mesh has
one broker. Two brokers keep two lease ledgers, so two dispatches could both fill one machine. It is
a state change on a **frozen** host, which this estate's own guard refuses without the owner
(`scripts/mesh/guard-service-state.sh --host secratary --op …` → exit 2; `settings/machines/host-posture.tsv`;
`docs/mesh/131-MIGRATION-BRIEF.md` Rule 1). Reversible: the unit is stopped and disabled, nothing is
deleted. **Recommended: yes.** Then:
```bash
ssh secratary-ts 'systemctl disable --now mesh-broker'      # only after the owner's explicit yes
ssh secratary-ts 'systemctl is-active mesh-broker'          # expect: inactive
```

**Step 2 — bring the offsite GitHub mirror back in step (P3135).** `origin` has two push URLs and they
have diverged, so the GitHub half of every push fails and the offsite copy of the code *and the
journal* is stale. A merge, never a force push — and in **its own worktree**, because this shared tree
holds another session's uncommitted index churn:
```bash
git worktree add -b gh-mirror-merge ../_gh-mirror-merge main
cd ../_gh-mirror-merge && git merge offsite/main      # expect conflicts in journal/index/* (generated)
#   resolve: keep ours, then regenerate with journal.py, then commit the merge
git push secretary-ts:/home/zabz/harness-config.git gh-mirror-merge:main
git push offsite gh-mirror-merge:main
```
Check it in one line at any time: `git fetch offsite && git merge-base --is-ancestor origin/main offsite/main; echo $?` (0 = in sync).

**Step 3 — create the mailbox thread directory at dispatch.** Small, and it restores the only
cross-turn conversation channel the engine allows. It belongs with the mailbox design, not with this
audit: `packages/plugin-remote-fanout/lib/mailbox.js`, `lib/provider.js:583`.

**Step 4 — list the authority in the Mac mini's `phone-gate-allow.txt`** when that machine's ssh
answers again. It removes the 4,000 ms cold-placement tax **and** returns a real worker (10 cores) to
the ranking. Until then the tax is known and recorded: journal **P3134**,
`docs/mesh/159` §5.2.

**Step 5 — re-verify the one link this session could not.** This session's engine bound
`MESH_BROKER_SSH` at boot (`secratary-ts`), so a full child dispatched **through the cloud broker by
the resident engine** is proven only at the broker level, not end to end. At the next engine restart
on any machine, run one child and check the placement line says the broker answered and the child's
`MESH-HOST` matches. → **`docs/mesh/159` §6** (the "NOT VERIFIED" row)

---

## 6. Every document this work touches, and what each one answers

| document | what it answers |
|---|---|
| **`docs/mesh/160-MESH-STATE-AND-NEXT.md`** | **this file** — the map |
| `docs/mesh/159-MESH-POST-MIGRATION.md` | the full record: every measurement, every defect, what is fixed, what is open, what was NOT verified |
| `docs/mesh/000-SYSTEMS-REGISTER.md` | the estate register every session reads first: machines, roles, the mesh rows, and traps 1–11 |
| `docs/mesh/154-MESH-BROKER-MOVE.md` | the broker move: what was staged, the one decision in it, and the executed-in-part banner |
| `docs/mesh/119-mesh-fanout-audit.md` | why the fan-out plane kept going down before this, and the engine limits on messaging (§6) |
| `docs/mesh/143-TRANSPORT-POLICY.md` | LAN / Tailscale / Cloudflare precedence, and the authority's private path |
| `docs/mesh/131-MIGRATION-BRIEF.md`, `142-ANCHOR-WRITE-NOTICE.md` | Rules 1–2: the office box is a read-only rollback anchor, one writer for the company database |
| `settings/machines/host-posture.tsv` | the one place a machine's posture is decided (`frozen` / `read-only` / `writable`) |
| `scripts/phone-gate-allow.txt` | the gates' device allow-list, with the reason and the cost of the authority's line |
| `scripts/phone-gate.py` | the gate: device check, sign-in, and the mesh capacity route |
| `packages/plugin-remote-fanout/lib/node-probes.js`, `lib/failover-placement.js` | the fallback: a missing health route no longer discards a node |
| `packages/plugin-remote-fanout/bin/mesh-run.mjs`, `profiles/web/cordis.patch.yml` | the two dispatcher paths, both now naming the authority |
| `packages/mesh-broker/nodes.json` | the roster the broker reads, with the frozen box excluded |
| journal **D3050** | the decision: broker to the authority, authority into every node's allow-list, and its cost |
| journal **L3737**, **L3738**, **L3739** | a blind broker still answers · a missing health route is not a dead machine · never `git commit --amend` in this repo |
| journal **P3134**, **P3135** | the 4 s unreachable-node tax · the diverged GitHub mirror |
| journal **W2738**, **H3570** | what measurably worked · the state of play for the next session |
| owner queue **#447** | the one question that is genuinely the owner's |

---

## 7. Verify the mesh yourself in 60 seconds

```bash
# 1. is the broker up on the authority, and can it SEE the fleet? ("unreachable" for every node = blind)
ssh secratary-cloud 'systemctl is-active mesh-broker; curl -s http://127.0.0.1:3091/nodes?fresh=1' | head -20

# 2. does a real placement name a node with free slots?
ssh secratary-cloud 'curl -s -X POST http://127.0.0.1:3091/place -H "content-type: application/json" \
  -d "{\"task\":{\"kind\":\"oneShot\",\"children\":1}}"' | head -5

# 3. what would the fallback do if the broker were gone? (read-only; dispatches nothing)
node packages/plugin-remote-fanout/bin/failover-place.mjs

# 4. is the office broker still the second broker? (expect active until question #447 is answered)
ssh secratary-ts 'systemctl is-active mesh-broker'
```

**How to read a bad answer:** a placement that says `blockedBy: ["unreachable","no-free-slots"]`, or a
`/nodes` where every node is `unreachable`, means the broker is **blind**, not busy — see §2 item 1.
An empty result is a refusal, never health.

---

## 8. Honest limits of this document

* The end-to-end dispatch **through the cloud broker by a resident engine** is unverified (§5 step 5).
* The Mac mini's state was measured from two vantages that disagree (its gate answers; ssh and the
  broker do not), so "unreachable from the broker" is what is claimed, not "down".
* `secratary-cloud`'s gate advertises `auth.secretConfigured: false`, so v2 `POST /mesh/run` cannot be
  signed there; the authority is not a worker and does not need it.
* Step 1 and step 2 are the only items that need anyone's decision; steps 3–5 are ordinary work and
  need no one.
