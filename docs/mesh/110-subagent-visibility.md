# 110 — Why a mesh child can never appear in the Subagents UI, exactly, and what would change that

Written 2026-09-18 from ZABZ-YOGA. Closes the investigation behind pain entry **P269**. This is the
single most-repeated complaint in this seat's history — *"if a bunch of subagents are running why
doesn't the top left subagents tab show anything running"* — and it now has an exact answer, two lines
long, that is not a bug in anything we wrote.

## The mechanism, in two lines

`dsh-subagent` builds the parent's child catalogue here:

```js
// @deepseek-ai/dsh-subagent/lib/types/index.js:437-441
const run = await provider.start(resolved);
const child = run.localAgent?.session;
if (child !== undefined) {
    establishCatalogChild(request.parent.session, child.header, descriptor);
```

and our remote provider answers here:

```js
// harness-config/packages/plugin-remote-fanout/lib/provider.js:639
localAgent: undefined,
```

`localAgent` is undefined because the child is not local — it is an agent turn on `ZABZ-TECH`, or
`secratary`, or the mac mini. So the guard at `:439` is never satisfied, `establishCatalogChild` is
never called, no `subagent/catalog` event is ever appended to the parent session, and the projection
the UI reads is legitimately empty.

**Measured, with three background children alive:** `subagentCatalog: {"inheritedEventCount":0}` and
`subagent: {}` on the parent session. The UI is not lying and is not broken; it has been told nothing.

## Why it is deliberate, and therefore not a bug to patch out

`README.md:56-59` of the same package says so in as many words:

> **Not continuable.** `prepareContinuable` is deliberately absent, so the seam rejects continuable
> starts on this provider. A remote child is one prompt, one [result] … need an Activation ownership
> contract before they can support continuable [children].

and two tests pin it: `assert.equal(run.localAgent, undefined)` and
`assert.equal(provider.prepareContinuable, undefined)`. A remote child is fire-and-forget by design —
there is no durable child identity this engine owns, so there is nothing for a catalogue row to point
at. The UI's assumption ("a child is a session in this engine") and the provider's design ("a child is
a turn on another machine") are simply different models, and neither is wrong.

## What is actually visible today, and it is honest

The **background-job** list. `dsh-tool-subagent/lib/index.js:536-555` registers a real job per
background child with `kind: "subagent"`, `owner: parent` and the brief's own label; the host publishes
it per session in `baseline().jobs` and broadcasts every change
(`dsh-api-session-controller/lib/index.js:1055-1098`); the header renders it
(`dsh-client-ui-jobs`, `count.live.one: "{count} background job running"`). That surface is correct,
and with `enableRunInBackground: true` (D267/L1999) it is populated the moment a child starts.

Its one weakness is the label: it names the task but not the machine, so `3 background jobs running`
does not say *where* the work went — which is the thing the owner actually wants to see when he is
checking that offloading happened.

## The two changes that would close it properly — and why BOTH are core changes, not ours

The first version of this section proposed a cheap fix of our own: put the placed node into the job's
label. **That is not possible, and the check is one grep.** `dsh-jobs` exposes no relabel or update: a
job's label is set at `start()` and the only code that touches it afterwards *validates* it
(`dsh-jobs/lib/invariant.js:19`: `if (snapshot.label.length === 0) fail(...)`). The label is also
chosen **before** placement happens (`dsh-tool-subagent/lib/index.js:540` passes
`args.description`, the model's own words), and the node is not known until the broker answers
afterwards. So the node cannot reach the label from where we sit.

What IS already true, and it is better than nothing: **the node is in the job's OUTPUT.** Every mesh
child's result opens with the transport's own block — `MESH-HOST: zabz-tech`, the `placement = broker →
node "…"` line with its lease id, the pressure block, `transport host`, and the `location check` that
confirms the node the broker named is the node that answered. Expanding the job shows exactly where the
work went. What is missing is only that this is not summarised in the collapsed row.

So both real remedies are in the harness, in order of cost:

1. **Let a job be relabelled once, at placement.** A small addition to `dsh-jobs` (an
   `update(id, {label})` or a `settledLabel`), called by the provider when the broker answers, would
   turn `Mesh latency matrix` into `Mesh latency matrix → zabz-tech` in the surface that already
   works. This is the cheapest change that answers "where did my work go" without touching the
   subagent model at all.
2. **Let a provider publish a remote child identity.** A new optional provider capability — call it
   `remoteChild` — carrying `{id, node, leaseId, label, createdAt}`. `dsh-subagent` would then append a
   catalogue fact for it and the UI would render it as a **non-navigable** row. The UI already has the
   vocabulary: `dsh-client-ui-subagent`'s i18n includes
   `readonly.oneShot.title: "One-shot subagent record"` and
   `readonly.oneShot.body: "One-shot tasks do not accept follow-ups; review the full execution record
   here."` — a child with a record but no session is a concept the UI already models.

**Do not do the naive thing.** Appending a synthetic `subagent/catalog` event from the provider without
the capability above would populate the chip and leave a switcher that tries to open a session which
does not exist. The silence is currently truthful; a row that lies is not an improvement.

## The third possibility, which was checked and is NOT the cause

That the client simply had a stale job list after the engine restart (journal **P270**). The client
does reset correctly on a new baseline — `replaceControlBaseline` clears `jobsBySession` and
repopulates it (`dsh-api-session-controller/lib/client.js:2685-2689`) — so a reconnected client shows
current jobs. P270 stays open as *unconfirmed*: the observation that produced it (a chip reading
"1 background job" while three children ran) is real, the explanation written beside it was a
hypothesis, and it has not been reproduced. It is recorded this way on purpose — the alternative is a
pain entry that reads as a finding when it is a guess, which is the failure mode this whole programme
has spent the day correcting.
