# The cloud cutover broke both halves of the phone — measured, fixed, and guarded

**2026-10-12.** Applies to every device the owner opens the harness on: iPhone 15 Pro,
iPad Air 5, and the two shop iPhone 11s (LPT STORE 1/2). Server side is
`secratary-cloud` — `phone-engine.service` (3089), `phone-gate.service` (3086),
`phone-redirector.service` (3087), fronted by `tailscale serve` at
`https://secratary-cloud.tail93e6e6.ts.net/` and, from outside, Cloudflare
`ai.abletelsolutions.com/phone` → 302 → that tailnet name.

The owner's report, verbatim in substance:

> when I try to send it a message … it says agent busy or session busy or
> something. Also, the interface is not optimized for the iPhone 15 which it's
> supposed to be, meaning on the office secretary it was already fully optimized.

Two independent defects. Neither was in the code that had been working; both came
from **how the cloud box installs and deploys**, which is why they appeared
together on the first day after the migration and nowhere else.

---

## Defect 1 — every prompt rejected: `session/agent-busy`

### What the phone showed

Reproduced from a real browser at 393×852 through the gate, so the client side is
excluded:

```
POST /api/session/prompt -> 200
{"result":{"ok":false,"error":{"code":"session/agent-busy","message":"prompt rejected",
 "details":{"reason":"Error: file-upload: operation requires the Agent's own scope"}}}}
```

and the UI printed exactly what the owner sees: `prompt rejected (session/agent-busy)`.

### Why the error name is misleading

`dsh-api-session-controller` wraps *any* unexpected throw during prompt admission:

```js
// dsh-api-session-controller/lib/index.js
} catch (error) {
  if (remoteErrorOf(error) !== undefined) throw error;
  if (error instanceof AttachmentError) throw new RemoteError("session/attachment-invalid", ...);
  throw new RemoteError("session/agent-busy", "prompt rejected", { reason: String(error) });
}
```

So `session/agent-busy` does **not** mean "an agent is running". It means "the
prompt was rejected and we are not telling you why". The real reason only reached
the wire under `details.reason`, and nothing in the UI shows `details`. The first
diagnostic step was therefore to read the response body, not the message.

### The actual failure

`dsh-client-file-upload` guards every upload operation with:

```js
assertAgentScope(agent) {
  if (scopeOf(agent.ctx) !== agent) throw new Error("file-upload: operation requires the Agent's own scope");
}
```

`scopeOf` reads a **module-level symbol**:

```js
// dsh-scope/lib/index.js
const kScope = Symbol("dsh.scope");
function createScope(ctx, key, options) { … ctx.extend({ [kScope]: key }) … }
function scopeOf(ctx) { return ctx[kScope]; }
```

The cloud box carries **two installed copies** of that package, because two
different trees load the packages:

| tree | path | who loads from it |
|---|---|---|
| flat npm install (the service's `ExecStart`) | `/opt/dsh-phone/node_modules/@deepseek-ai/…` | `dsh-agent-loop` |
| the profile's pnpm install | `~/.dsh/profiles/web/node_modules/.pnpm/@deepseek-ai+…` | `dsh-client-file-upload` |

Two module instances ⇒ two `Symbol("dsh.scope")` values. The agent loop stamped
the agent's context with *its* symbol; the file-upload plugin read *its own* and
got `undefined`.

Measured, not deduced — one log line in each copy's constructor named the copy
that ran:

```
[SCOPE6] file:///opt/dsh-phone/node_modules/@deepseek-ai/dsh-agent-loop/lib/index.js
[SCOPE5] {"acopy":"file:///root/.dsh/profiles/web", "agentCtor":"ReactLoopAgent",
          "scopeIsSame":false, "ownSymbols":"Symbol(dsh.scope)"}
```

The context **had** a `Symbol(dsh.scope)`; it was the other copy's.

### The fix

One symlink, so both trees resolve the module to one file and therefore one symbol:

```bash
/opt/dsh-phone/node_modules/@deepseek-ai/dsh-scope
  -> ~/.dsh/profiles/web/node_modules/.pnpm/@deepseek-ai+dsh-scope@0.2.0-rc.2_…/node_modules/@deepseek-ai/dsh-scope
```

The canonical copy is the profile's, because the profile's own packages resolve
there and the engine can be pointed at it in one step. The flat copy was **moved
aside with a timestamp**, never deleted.

Same session, same prompt, after the change: the agent answered `pong` in 1 s.

### Why it will come back, and what stops it

`npm install` in the engine tree re-creates the flat `dsh-scope` directory and
splits the symbol again — silently, and only on the phone.
`scripts/repair-phone-engine.sh` re-asserts the single copy, compares resolved
inodes, moves a disowned copy aside, and is wired in as
`phone-engine.service` → `ExecStartPre=/usr/local/bin/repair-phone-engine.sh --check`
(`settings/phone-engine-repair.conf`). `--check` fails the start rather than
repairing silently, so a recurrence appears in `systemctl status phone-engine`.

---

## Defect 2 — the phone layer served as **0 bytes**

### The reading

```
gate log:  GET /dsh-phone-mobile.css -> phone layer stylesheet: 64 bytes
browser:   Failed to load resource: 404  http://…/dsh-phone-mobile.css
document:  no <style id="dsh-phone-mobile"> tag at all
```

`assets/mobile.css` is 17,539 B and `assets/question-card.css` 10,586 B in the
repo; the served layer was empty because the gate concatenates those files and
**found none of them**.

### Why

`phone-gate.py` resolved them as `Path(__file__).parent.parent / "assets"`. Run
from a checkout, that is `<repo>/assets` and correct. Deployed as
`/usr/local/bin/phone-gate.py` — how every Linux node runs it — it is
`/usr/local/assets/`, a directory the install step has to create. The office box
had it; the cloud box did not.

The consequence is the whole mobile experience, because the layer is what makes
the app usable in a hand:

| what the layer provides | without it |
|---|---|
| off-canvas drawer, one-column frame | sidebar takes the screen |
| 44×44 drawer toggle pinned top-left | control under the thumb, in-scroll |
| `html, body { overflow: hidden }` + contained scrollers | "funny scroll" — page moves, panel stays |
| ≥44 px touch targets | sub-44px controls |
| 16px text fields | iOS zooms the page on focus |
| `env(safe-area-inset-*)` | content under the notch and home bar |

### The fix

* `resolve_asset(name)` in `phone-gate.py` now **searches** beside the checkout,
  beside the deployed script, and under `/usr/local`, instead of computing one
  path. It is layout-independent: the same file works in place and deployed.
* The three assets are installed to `/usr/local/assets/`, and
  `repair-phone-engine.sh` re-deploys them whenever the repo copy differs.

### Verified after the fix, 393×852 through the gate

```
/dsh-phone-mobile.css         200  28,167 B
dsh-phone-mobile-link         present, styleSheet loaded with rules
Open sidebar button           44x44
body / html overflow          hidden   (page scroll contained)
composer font-size            16px     (iOS will not zoom)
the conversation              answered in 2.5 s
```

---

## What was NOT broken (checked, so it is not re-investigated)

| check | reading |
|---|---|
| `tailscale serve` target | `:443 → http://127.0.0.1:3086` correct |
| the redirector | `/phone` → 302 to the tailnet name, correct target |
| the device allow-list | all five owner devices present, and identical to the repo copy |
| the secretary MCP toolbelt from the phone | answered with `ps_comms_search`, `ps_db_query`, `ps_company_status`, … |
| sessions and workspace | `cwd=/home/zabz/phone` resolves on the cloud box |
| the *engine's own* node version | Node 22 (v20 exits silently — unchanged, correct) |
| abandoned sessions in the drawer | the owner's old phone conversations, by design |

## Traps for the next session

1. **`install-from-repo.sh` is the deploy path.** Editing
   `<repo>/scripts/phone-gate.py` on the cloud box changes nothing that runs;
   `/usr/local/bin/phone-gate.py` is what executes. The repo copy is the source,
   the deployed copy is the program.
2. **`phone-gate-allow.txt` keys on the client address `tailscale serve` appends
   (`X-Forwarded-For`), and only from Serve.** A request with no such header is a
   loopback client and is trusted by construction. So a phone that is **not on the
   tailnet** is refused with *"This node does not sign in this device"* — that is a
   device-side fault (Tailscale not installed or not running), not a server one.
   The Cloudflare `/phone` icon only redirects into the tailnet; it is not a
   second way in.
3. **One engine serves every device** (`--port 3089`). All phones share its
   sessions. That is deliberate — the same agent, the same history — and it is not
   the cause of a rejection; a busy agent accepts a queued message.

## The guard, one command

```bash
ssh secratary-cloud '/usr/local/bin/repair-phone-engine.sh --check'
# scope: one copy (…/dsh-scope@0.2.0-rc.2_…/node_modules/@deepseek-ai/dsh-scope)
# phone engine: healthy
```
