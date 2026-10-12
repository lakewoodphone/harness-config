# 154 — MOVING THE MESH BROKER OFF THE FROZEN BOX: THE EXACT ACTION, AND THE ONE DECISION IN IT

**Author:** coordinator session (ZABZ-TECH), 2026-10-11 ~21:35Z. **Facts measured, nothing changed.**

> **EXECUTED IN PART 2026-10-12 — read this banner before acting on anything below.**
> The move was done: `mesh-broker` on `secratary-cloud` is **enabled and running** (03:18Z), with the
> repo roster copied over the staged one (which failed to exclude the frozen box — an error worth
> remembering in itself). And it was made to **actually work**: the authority had to be added to every
> node's `scripts/phone-gate-allow.txt`, because until then it read **0 of 5 nodes** (`HTTP 403` on
> every route of every node) and answered every placement blind — a broker that reads nothing still
> returns a well-formed `position 1, blockedBy ["unreachable","no-free-slots"]`.
> **The one item below that is still open is decision option 1 — stopping the office copy.** It is
> owner question **#447**; until it is answered the office broker is still `active/enabled` and there
> are two brokers for one mesh (two lease ledgers, §"THE ONE DECISION" below).
> Every measurement, and the things that are still open besides this one:
> `159-MESH-POST-MIGRATION.md`.

## Why this matters

`docs/mesh/000-SYSTEMS-REGISTER.md` declares the placement broker as running on the authority. **It does
not.** Measured: the broker listens on `127.0.0.1:3091` on the **frozen office box** (`node`, pid 105841,
`mesh-broker.service` active/enabled), and on the cloud authority `mesh-broker.service` is
**inactive/disabled** with **nothing** on `:3091`.

So the thing that makes `subagent` fan-out work runs on the box the migration froze and told every agent
is read-only. That is why fan-out kept working today, and it is why the freeze is not total. Rule 1 says
do not change anything on that box; the broker is a live dependency that Rule 1's own reasoning says
should not be there.

## The good news: the move is staged and needs no building

Everything the cloud broker needs is already in place, put there at 13:27 today:

    /opt/mesh-broker/bin/mesh-broker.mjs   5670 B   (identical size to the office copy)
    /opt/mesh-broker/nodes.json           14335 B   (DIFFERENT size from the office's 15217 B,
                                                     so the node list has been adapted)
    /opt/mesh-broker/{PROVENANCE.md,bin,deploy,lib}
    node                                   v20.20.2 at /usr/bin/node

and its unit has already been re-written for this box - `WorkingDirectory=/opt/mesh-broker`,
`Environment=HOME=/root`, and a comment recording that *"the original unit was written for the office
box: User=zabz, WorkingDirectory=/home/zabz/mesh-broker"*. `:3091` on the cloud is **free**.

**So starting it is one command:**

    ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 systemctl enable --now mesh-broker
    # verify:  ss -ltnp | grep 3091     -> should show /usr/bin/node on 127.0.0.1:3091
    #          curl -s http://127.0.0.1:3091/mesh/health   -> expect the broker's own health shape
    #          then dispatch one test subagent and confirm placement still works

## THE ONE DECISION, AND IT IS THE OWNER'S

**The office broker must then be stopped** - otherwise two brokers serve one mesh. Measured state on that
box: `mesh-broker.service` `active` / `enabled`, holding `127.0.0.1:3091` as pid 105841.

**That is a state change on the FROZEN host, which `131-MIGRATION-BRIEF.md` Rule 1 forbids** and which
`scripts/mesh/guard-service-state.sh` now refuses by name. So it is not mine to do, and doing it quietly
would be the exact failure this whole day has been about. The two options:

1. **Stop and disable it on the office box** - completes the move; the frozen box stops doing work.
   Reversible (the unit is untouched, only stopped and disabled).
2. **Leave it** - then the mesh keeps depending on a box that is supposed to be inert, and the cloud
   broker must NOT be started, because two brokers for one mesh is a double-dispatch hazard.

**Recommendation: option 1.** The freeze is meant to make that box inert; a live broker contradicts it,
and the cloud copy is already staged and verified present. Leaving it means the estate's fan-out has a
single point of failure sitting on the one machine the migration deliberately stopped maintaining.

## What I did NOT do

I started nothing, stopped nothing, and touched no unit on either box - all of the above is `systemctl
cat`, `ss`, `ls` and `curl`. The guard workstream's scan already found the same divergence and also left
it alone.
