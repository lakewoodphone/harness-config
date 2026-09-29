# 120 — Can a mesh child be a first-class, addressable, continuable child?

Written 2026-09-30 from **secratary** (this lane ran on the authority server, not the laptop).
Question: can the `remote-ssh` provider make a child that `list_agents` shows, `send_message`
steers, `interrupt_agent` stops, and that can push a message back to the parent while running —
from our plugin alone?

**Answer: no. It requires an engine change.** The continuable path is, by construction, a
*local* Agent that the continuation manager composes itself; the provider's entire participation
is detached data. The engine's own README names the missing thing: *"remote providers need an
Activation ownership contract before they can support continuable children"*
(`@deepseek-ai/dsh-subagent/README.md:170`).

Unless stated otherwise, `$E = /home/zabz/.dsh/profiles/node_modules/@deepseek-ai`, read at the
installed versions on this node. I did not run the engine (DOC ONLY); every claim is a static
source reading with the quoted line.

---

## 1. THE SEAM, EXACTLY

### The provider contract

`$E/dsh-subagent/lib/types/types.d.ts:327-337`:

```ts
export interface SubagentProvider {
    /** Unique registry name (e.g. `spawn`, `fork`, `acp`). */
    readonly name: string;
    /** The start-time features this provider supports (see {@link SubagentCapabilities}). */
    readonly capabilities: SubagentCapabilities;
    /**
     * Whether the child sees the parent's completed-turn prefix. ...
     */
    readonly inheritsParentContext: boolean;
```

Optional route defaults, `types.d.ts:344-347`:

```ts
    readonly agentRouteDefaults?: Readonly<{
        provider: string;
        model: string;
    }>;
```

The two methods, `types.d.ts:359` and `:375`:

```ts
    start(request: ResolvedSubagentStartRequest): Promise<SubagentRun>;
...
    prepareContinuable?(request: ContinuableCreateRequest): Promise<ContinuableCreateSpec>;
```

`capabilities` is the five start-time flags (`types.d.ts:122-128`):

```ts
export interface SubagentCapabilities {
    readonly agentOptions: boolean;
    readonly outputSchema: boolean;
    readonly depthLimit: boolean;
    readonly toolFilter: boolean;
    readonly persona: boolean;
}
```

### What `start()` receives

`start()` is handed a `ResolvedSubagentStartRequest`, not the raw request
(`types.d.ts:197-200`):

```ts
export interface ResolvedSubagentStartRequest extends SubagentStartRequest {
    /** Detached descriptor a session-backed provider persists in the child log. */
    readonly descriptor: SubagentDescriptorData;
}
```

`SubagentStartRequest` (`types.d.ts:136-154`, `:162`, `:168`, `:175`, `:183`, `:191`) carries
`label?`, `prompt: ContentBlock[]`, `parent: Agent`, `signal: AbortSignal`, and the optional
`agentOptions`, `outputSchema`, `maxDepth`, `toolFilter`, `persona`. The service has already
validated those capabilities and snapshotted the descriptor before calling the provider: the
one-shot service `start` is `$E/dsh-subagent/lib/types/index.js:425-427` —
`async start(name, request) { const provider = this.expectProvider(name); this.assertCapabilities(provider, request);`
(the same entry bundled at `$E/dsh-subagent/lib/index.js:3145`).

### The exact return shape

`types.d.ts:292-318`:

```ts
export interface SubagentRun {
    readonly id: SessionId;
    /**
     * The exact published in-process child, or `undefined` for a remote run.
     * When present, its id is {@link id}; ...
     */
    readonly localAgent: Agent | undefined;
    /**
     * Resolves with the child's terminal {@link SubagentResult} when the run
     * settles. Does NOT reject on a child-level failure ...
     */
    readonly result: Promise<SubagentResult>;
    /**
     * Cancel remaining work, reach child quiescence, and release resources.
     * Idempotent.
     */
    dispose(): Promise<void>;
}
```

`SubagentResult` (`types.d.ts:256-282`) is `{ output: ContentBlock[]; structured?: unknown;
diagnostic?: string; stopReason: SubagentStopReason }`.

The two shipped shapes of this handle:

- remote / out-of-process, `$E/dsh-subagent/lib/types/out-of-process.js:203-218`:
  ```js
  export function subprocessRunHandle(parts) {
      let disposal;
      return {
          id: parts.id,
          localAgent: undefined,
          result: parts.result,
          dispose() { ... }
      };
  }
  ```
- in-process, `$E/dsh-subagent-in-process-driver/lib/index.js:218-222`:
  ```js
  return {
      ...
      localAgent: child,
      result,
  ```

Our provider is the first shape, verbatim —
`packages/plugin-remote-fanout/lib/provider.js:637-651`:

```js
    return {
      id,
      localAgent: undefined,
      result,
      dispose() { ... },
    };
```

### What `localAgent` is used for

It is the *only* signal that the child is a session this engine owns. Exactly two consumers
exist (a full-tree grep finds no others):

1. **The parent's child catalogue.** `$E/dsh-subagent/lib/types/index.js:437-441`:
   ```js
   const run = await provider.start(resolved);
   const child = run.localAgent?.session;
   if (child !== undefined) {
       establishCatalogChild(request.parent.session, child.header, descriptor);
   }
   ```
   `establishCatalogChild` appends the `subagent/catalog` event
   (`$E/dsh-subagent/lib/types/catalog.js:86-102`). No `localAgent` → no event → no catalogue row.
2. **The lifecycle `local` flag.** `lib/index.js:298`: `local: run.localAgent !== void 0`, and
   `lib/types/lifecycle.js:61`: `local: run.localAgent !== undefined`.

Our provider answers `undefined`, so `dsh-subagent` treats every mesh child as a
non-addressable remote run — deliberately (`packages/plugin-remote-fanout/lib/provider.js:48-52`).

---

## 2. THE CONTINUABLE CAPABILITY

**The capability name is `prepareContinuable`.** Method presence *is* the capability;
`types.d.ts:360-375`:

```ts
    /**
     * OPTIONAL (continuable-creation capability): contribute the detached
     * creation inputs that distinguish this provider's continuable children —
     * only whether the child session is seeded with parent history. Method
     * presence IS the capability: the service rejects continuable starts on
     * providers without it, while a provider that has it may still serve
     * ordinary one-shot delegations.
     *
     * This is the provider's ONLY participation in a continuable child. The
     * continuation manager owns identity reservation, composition, Agent
     * creation, prompt delivery, cold resume, ownership, and disposal, so a
     * provider never sees the child's Agent, handle, turns, or teardown.
     */
    prepareContinuable?(request: ContinuableCreateRequest): Promise<ContinuableCreateSpec>;
```

What it may return is data only (`types.d.ts:225-232`; the single field is line `:231`):

```ts
export interface ContinuableCreateSpec {
    /**
     * Completed-turn prefix of the parent's log to seed the child session with,
     * or absent for a fresh child. ...
     */
    readonly seed?: readonly SessionEvent[];
}
```

### Where the engine refuses it

Runtime, the service (`$E/dsh-subagent/lib/types/index.js:462-468`):

```js
async prepareContinuable(name, request) {
    const provider = this.expectProvider(name);
    if (provider.prepareContinuable === undefined) {
        throw new SubagentError(`subagent provider "${provider.name}" does not support continuable children `
            + '(no prepareContinuable capability)', 'UNSUPPORTED_CAPABILITY');
    }
    return provider.prepareContinuable(request);
}
```

At tool-mount time (`$E/dsh-tool-subagent/lib/index.js:372`, `:380`):

```js
const continuable = (config.backgroundMode ?? "one-shot") === "continuable";
...
if (continuable && subagentProvider.prepareContinuable === void 0) throw new Error(`tool-subagent: provider "${subagentProvider.name}" does not support \`backgroundMode: continuable\``);
```

### What the engine does when it is present

`$E/dsh-subagent/lib/types/continuation.js:134-142` takes the returned `seed`:

```js
const prepared = await this.host.prepareContinuable(spec.provider, {
    sessionId: childId,
    parent,
    signal: spec.signal,
});
spec.signal.throwIfAborted();
...
const seed = prepared.seed;
```

and then `:156-170` composes the child **itself**:

```js
const activation = await this.activations.materialize({
    childId,
    provider: spec.provider,
    parent,
    create: { seed, meta: ..., inheritedEventCount, delegatedPolicies, descriptor },
    ...
});
```

`materialize`/`materializeTracked` is where "composition" actually happens
(`$E/dsh-subagent/lib/types/continuation-activation.js:404-440`):

```js
const handle = create === undefined
    ? await this.ownerCtx.agents.resume({ resumeSessionId: childId, parentAgent: parent, ... })
    : await this.ownerCtx.agents.create({ sessionId: childId, parentAgent: parent, ... });
const activation = {
    childId,
    parentSession: parent.id,
    provider,
    handle,
    inbox: new SubagentInbox(handle.agent),
    ancestry: new WeakSet([handle.agent, ...parentLineage]),
    ...
};
```

So even a provider that implements `prepareContinuable` gets a **local** `Agent` from
`ownerCtx.agents.create/resume`; it can never make that Agent live on another node. Our provider
deliberately omits the method (`packages/plugin-remote-fanout/lib/provider.js:48-52`), and the
shipped only other implementer is the in-process backend
(`$E/dsh-subagent-spawn-in-process/lib/index.js:37-39`, `prepareContinuable() { return Promise.resolve({}); }`).

---

## 3. HOW THE CONTROL TOOLS RESOLVE A CHILD

### `list_agents`

Tool: `$E/dsh-tool-subagent-control/lib/types/list-agents.js:52-54`
(`name: 'list_agents'`). Execute at `:134-146`:

```js
case 'children': {
    const entries = await ctx.subagents.listChildren(parent.id, exec.signal);
    ...
case 'descendants': {
    const entries = await ctx.subagents.listDescendants(parent.id, exec.signal);
```

Service method `$E/dsh-subagent/lib/types/index.js:248`; implementation
`$E/dsh-subagent/lib/types/list-children.js:95-102`:

```js
export async function listChildren(ctx, parentSessionId, signal) {
    const listing = await prepareListing(ctx, signal);
    const candidates = [...listing.corpus.values()]
        .filter(record => record.header.parentSession === parentSessionId
        && record.header.origin === 'subagent')
        .sort(compareCorpusRecords);
```

The corpus is built from `query.listSessions(signal)` (`list-children.js:157`) merged with the
**local** live session store, `ctx.get('sessions')` (`:142`, `:168`). `list-agents.js:38` then
drops anything not continuable: `if (entry.mode !== 'continuable') return undefined;`, and
`:24-29` reads live status from `ctx.agents.get(id)`.

**A child must possess:** a durable Session in *this engine's* session store/persistence whose
`header.origin === 'subagent'` and `header.parentSession` is the caller, plus a `subagent`
projection identity whose `mode` is `continuable` (`list-children.js:344-361`). None of that
exists for a process on another machine.

### `send_message`

Tool: `$E/dsh-tool-subagent-control/lib/index.js:22-60`; execute at `:58`:

```js
return { messageId: await ctx.subagents.sendMessage(sender, brandString(args.agent_id), message, { signal: exec.signal }) };
```

Service `$E/dsh-subagent/lib/types/index.js:160`, implementing manager
`$E/dsh-subagent/lib/types/continuation.js:193-212`:

```js
async sendMessage(sender, targetId, content, options) {
    if (this.ctx.agents.get(sender.id) !== sender) {
        throw new SubagentError('message delivery requires the exact live sender agent', 'UNAUTHORIZED');
    }
    ...
    const senderActivation = this.activations.get(sender.id);
    if (senderActivation !== undefined && senderActivation.handle.agent === sender
        && senderActivation.parentSession === targetId) {
        return this.sendToParent(senderActivation, sender, content);
    }
    ...
    return this.deliverToChild(sender, targetId, content, ...);
}
```

`deliverToChild`/`deliverFollowup` (`continuation.js:250-280`) either takes the **resident**
activation (`:253`) or cold-resumes (`:255`), and cold resume reads the local session store
(`:344 query.observeSession(childId)`) and refuses anything whose folded descriptor is not
`continuable` (`:356-357`).

**A child must possess:** a process-local resident Activation, or a durable local session with a
folded `mode: 'continuable'` descriptor — which cold-resume then re-materializes as a *local*
Agent (`:361`).

### `interrupt_agent`

Tool: `$E/dsh-tool-subagent-control/lib/index.js:61-92`; execute at `:86`:

```js
ctx.subagents.interrupt(brandString(args.agent_id), { kind: "ancestor", agent: caller });
```

Service `$E/dsh-subagent/lib/types/index.js:195-197`; implementation
`$E/dsh-subagent/lib/types/continuation-activation.js:137-163`, and the decisive lines `:147-149`:

```js
const activation = this.resident.get(targetSessionId);
if (activation === undefined)
    return;
```

**A child must possess:** an entry in the registry's `resident` map — a live process-local
Activation. Interrupting an unknown id is an accepted no-op (the service JSDoc says so at
`$E/dsh-subagent/lib/types/index.js:187-189`: *"An absent target — including a one-shot or unknown
id — is an accepted no-op"*).

---

## 4. CAN A NON-LOCAL CHILD BE ADDRESSED

**No.** Three independent blockers, all in the engine:

1. **The one-shot remote path is explicitly excluded from discovery.** `localAgent` is
   `undefined` (`out-of-process.js:207`; our `provider.js:639`), so `establishCatalogChild` is
   never called (`types/index.js:437-441`).
2. **The continuable path materialises a local Agent and stores it.** The manager calls
   `this.ownerCtx.agents.create/resume` (`continuation-activation.js:417-425`) and records
   `handle` + `new SubagentInbox(handle.agent)` (`:439-440`). The provider's only input is
   `ContinuableCreateSpec.seed` (`types.d.ts:225-232`); there is no way for our transport to
   place that child on another node.
3. **Every control surface resolves through process-local state:** `activations.resident` for
   interrupt (`continuation-activation.js:147`), `ctx.agents` for status (`list-agents.js:25`),
   the local session store/query for listing and cold resume (`list-children.js:142,157`).

**The engine file and function that would have to change:**
`ContinuableActivationRegistry.materializeTracked` in
`$E/dsh-subagent/lib/types/continuation-activation.js:404-434` — it hardcodes
`ownerCtx.agents.create/resume`. A remote-aware Activation would also need branches in
`interrupt` (`continuation-activation.js:137`), `sendWaking` (`:170`), `sendToParent`
(`continuation.js:298`), `listChildren`/`listDescendants` (`list-children.js:95`, `:117`) and the
catalogue (`catalog.js:86`). This is the "Activation ownership contract" of
`README.md:170`.

**How small is it?** Not small. The engine's own limitation list says the missing pieces are a
durable mailbox and a cross-process lease: *"Process-local residency — the Activation inbox and
ownership graph do not coordinate two harness processes; concurrent access to one persistence
store needs a durable mailbox and cross-process lease protocol"* (`README.md:175`), and *"a
durable mailbox and lease protocol would let two harness processes share one persistence store"*
(`README.md:188-189`). A provider method plus a remote handle abstraction is the seam; the
mailbox/lease underneath is the real work.

---

## 5. CHILD TO PARENT, MID-FLIGHT

### What the engine already supports (local children only)

- **The tool**: `send_message` (`$E/dsh-tool-subagent-control/lib/index.js:22-60`), and the
  prompt the engine injects into every continuable child telling it to use that tool:
  `continuation-messages.js:36-49` (*"send your result to that agent with
  `send_message({ agent_id: ..., message: ... })`"*).
- **The child→parent route**: `continuation.js:198-204` requires a **resident** child
  Activation whose `parentSession` is the target; `sendToParent` (`:292-305`) then requires the
  parent to be live in `this.ctx.agents.get(activation.parentSession)` (`:298`, throws
  `PARENT_UNAVAILABLE` at `:300`).
- **The delivery primitive**: `sendAgentMessage` → `sendWaking`
  (`continuation-activation.js:170-185`), which ends in `parent.steer(message)` or
  `parent.followup(message)` (`:181-184`). The `Agent` surface it uses is
  `send`/`followup`/`steer`/`inject`/`cancel`/`status`
  (`$E/dsh-agent/lib/types/runtime-types.d.ts:147-209`).
- **Live progress**: `list_agents` status is `ctx.agents.get(id).status` (`list-agents.js:24-29`);
  lifecycle edges `subagent/start` / `subagent/end` are emitted observe-only
  (`lib/index.js:293-313`, `:326-354`); the settlement notice is `continuation-messages.js:85-101`;
  agent-level events `agent/status` and `agent/inbox/claimed` exist
  (`runtime-types.d.ts:247`; `$E/dsh-agent-loop/lib/index.js:107`).

### What does not exist for a mesh child

Nothing. The engine has **no** durable parent mailbox (`README.md:172`, `:177`), and our two
transports have no mid-flight channel:

- ssh: stdout/stderr go to temp files and are read only when the client settles
  (`packages/plugin-remote-fanout/lib/ssh-transport.js:163-188`, `:231-265`);
- HTTP: `plugin-mesh-http` is a one-shot request/response route — `OneShotRunner`
  (`packages/plugin-mesh-http/lib/runner.js:129`), mounted at `/mesh/run`
  (`packages/plugin-mesh-http/lib/index.js:63`, `:325-329`).

### The smallest honest mechanism that would work

An **inbound authenticated HTTP callback on the parent engine**, because that process is already
running and already able to mount routes: `plugin-mesh-http` registers through `webServer`
(`packages/plugin-mesh-http/lib/index.js:74`, `:325-329`). The remote child would POST
`{ parentSessionId, childId, message }`; the parent-side handler would resolve the live parent
`Agent` with `ctx.agents.get(parentSessionId)` and call `parent.steer(createUserMessage(...))` —
the same primitive `sendWaking` uses (`continuation-activation.js:181-184`). This is a **shim, not
first-class adjacency**: it has no `activations` authorization (`continuation.js:194`), no
accepted durable inbox id, and no guarantee the parent is live. Over ssh it is not available at
all without a new streaming channel, because the current transport buffers to a file.

---

## 6. VERDICT AND OPTIONS, RANKED

**Option A — implementable in our plugin alone: does NOT deliver what was asked.** If
`RemoteOneShotProvider` added `prepareContinuable() { return {} }` (the spawn backend's shape,
`dsh-subagent-spawn-in-process/lib/index.js:37-39`), the tool gate
(`dsh-tool-subagent/lib/index.js:380`) and the service gate (`types/index.js:464-466`) would pass,
but the manager would then build the child with `ownerCtx.agents.create` (`continuation-activation.js:425`).
The result is a **local** agent that is addressable and continuable — but it did *not* run on the
mesh, which is the entire point of the provider. That is a silent behaviour change worse than
today's honest failure.

**Option B — needs a named engine change: this is the real answer, and my recommendation.**
The engine must gain an *Activation ownership contract* for out-of-process children. Files and
functions to change (engine side):
- `@deepseek-ai/dsh-subagent/lib/types/types.d.ts` — a new optional provider method (e.g.
  `startContinuable`) alongside `prepareContinuable` (`:375`), returning a handle the registry can
  own instead of only a `seed`.
- `@deepseek-ai/dsh-subagent/lib/types/continuation-activation.js` —
  `materializeTracked` (`:404-434`) to branch on that handle; `interrupt` (`:137-163`) and
  `sendWaking` (`:170-185`) to act on a remote handle rather than assuming `handle.agent`.
- `@deepseek-ai/dsh-subagent/lib/types/continuation.js` — `sendToParent` (`:292-305`) and
  `sendMessage` (`:193-212`) for child→parent over a transport.
- `@deepseek-ai/dsh-subagent/lib/types/list-children.js` (`:95`, `:117`) and
  `catalog.js` (`:86`) — remote rows/catalogue facts.
Ours to write once that contract exists: the method on `RemoteOneShotProvider`
(`packages/plugin-remote-fanout/lib/provider.js`) plus a new
`packages/plugin-remote-fanout/lib/remote-activation.js` holding child-id ↔ node/lease/transport
state, and an inbound-route counterpart in `plugin-mesh-http` for child→parent.

**Option C — infeasible now: the operative truth on today's pinned engine.** With the installed
packages, B cannot be delivered from `packages/remote-fanout`; the honest short-term posture is
one-shot mesh children plus the background-job + `MESH-HOST`/placement report already built.

**Recommendation: B**, with C as the explicit interim. **Riskiest assumption:** that a remote
activation handle can be substituted behind the local `AgentHandle`/`Agent` surface without a
durable cross-process mailbox and lease — i.e. that two harness processes can share the inbox and
ownership graph safely. The engine says they currently cannot (`README.md:175`, `:188-189`); if
that is not built first, the "remote Activation" will look addressable and then lose or
double-deliver messages on restart.

---

## 7. WHAT I COULD NOT VERIFY

- Whether a **newer** engine than the one installed on this node already ships the Activation
  ownership contract. I read only the local installs (`$E` and `/home/zabz/dsh-engine`); I did no
  registry/network check.
- Whether the **35 diverged commits on `origin/master`** contain such a change. The base under
  test is `f97626b`; I did not read master (instructed not to touch it).
- Whether a plugin has a **supported way to inject** into `ctx.agents` or the private
  `activations.resident` map. I found no exposed registration API for the Activation graph, but I
  did not exhaustively read every engine package.
- The exact projection definition that folds `subagent/descriptor` into the `subagent` identity
  (`list-children.js:197`, `:328`); I inferred `mode` from `childRow` (`:344-361`) rather than
  reading that unit's source.
- All findings are **static source readings**. I did not run the engine or dispatch a child
  (constraints: doc-only, no dispatch), so no behaviour here is measured live on the mesh.
