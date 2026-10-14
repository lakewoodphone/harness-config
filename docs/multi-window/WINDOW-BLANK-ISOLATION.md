# Blank DSH windows shared one session — cause, fix, and how it was verified

**Measured and fixed 2026-10-14 on ZABZ-YOGA.** Live engine pid 10668 (`dsh web --port 3099`),
never restarted; the client bundle is served per request and keyed on mtime, so a *window reload*
picks the fix up and no engine restart is involved.

## The complaint

> *"When I have a few DSH windows open, so when there's content running in them, they stay separate.
> But let's say I have two or three windows open that are blank. There's no session yet on them.
> Then when I talk in one, they all turn into that session and all 3 start running that session with
> the same words, meaning it's not a duplicate session, but it's the same session getting displayed
> across all empty windows."*

He is right about the mechanism, and windows that already have content are unaffected for exactly
the reason he observed: a window only asks for a blank session when it has none, and a window with
content never asks.

## The cause, in one method

`~/.dsh/engine/node_modules/@deepseek-ai/dsh-client-ui-workspace/lib/client.js`,
`UiWorkspaceService.reuseOrCreateBlank()` — upstream text:

```js
reuseOrCreateBlank(workspace) {
	const archived = this.workspaces.list.getSnapshot().archivedSessionIds;
	const sessions = this.sessions.list.getSnapshot();
	for (const id of sessions.ids) {
		const summary = sessions.byId[id];
		if (summary === void 0 || !summary.blank || summary.cwd !== workspace.path || !workspace.sessionIds.includes(id) || archived.includes(id)) continue;
		return this.reuseBlank(workspace.workspaceId, id);
	}
	return this.sessions.create({ workspaceId: workspace.workspaceId });
}
```

The scan is over **the whole session catalog**, and nothing in it belongs to the calling window. A
"blank" session is host-side and shared: `blank` is `session.seq === 0` (a projection that flips to
`false` only on `turn/start`, `dsh-api-session-controller/lib/index.js:1808`), so the session the
first empty window creates is a normal catalog row that the next empty window finds and adopts with
`sessions.create({ workspaceId, sessionId })`. Every window then retains that one session as its
`mainView` and renders the same conversation.

This is why the window-per-origin trick in `MEMORY-AND-SESSION-LIST.md` did **not** cover it: the
origin isolates `localStorage["dsh.sessions.current"]`, but the *blank catalogue* is shared by every
window on the engine, whatever its origin.

## The fix

`window-blank-isolation`, three changes to that one client bundle:

1. a per-origin record of the blank **this window** created — `localStorage["dsh.sessions.ownedBlank"]`,
   the same keying as `dsh.sessions.current`, so one window slot keeps its blank across reloads while
   a new window slot starts with nothing;
2. `reuseOrCreateBlank()` reuses **only** that blank, and otherwise creates a fresh one;
3. `restoreSelection()` refuses to restore or adopt a blank the window does not own — which also
   detaches an already-doubled window on its next reload, as long as the shared session is still
   blank (if someone has already typed in it, the session is ordinary content and the window
   restores it like any other session; that window needs one *New session* click).

It is applied, re-applied and verified by `multi-window/tools/patch-window-blank-isolation.mjs`:

```
node multi-window/tools/patch-window-blank-isolation.mjs --check    # 0 applied, 4 absent, 5 unverifiable
node multi-window/tools/patch-window-blank-isolation.mjs --apply    # idempotent, refuses on unknown upstream
node multi-window/tools/patch-window-blank-isolation.mjs --revert   # rollback door
```

**Why a script and not a hand edit:** the fix lives in an npm-installed tree that `dsh-update`
replaces, and `dsh-update` tracks *cordis composition* patches (`cordis.patch.yml` rows) only —
it has no registry for a hand patch to a package file, so a bare edit is silently lost on the next
engine update. The script is the registry; `--check` is how a post-update step (or a human) finds
out. Backup of the pre-patch file: `client.js.bak-harness-20261014T010103Z` beside it.

## The verification — `multi-window/tools/verify-window-session-isolation.mjs`

Two independent Playwright browser contexts are two windows: separate storage, separate JS context,
one engine. The evidence is the session pointer each window persists
(`localStorage["dsh.sessions.current"]`) — the value the Workspace service restores and the Session
area renders, so **two windows with the same id are two windows displaying one session**.

Before the patch — 2 windows, one session (**the complaint, reproduced**):

```
{"window":1,"stage":"opened","sessionId":"session-8c62e107-642f-4bb4-9aa6-124fcf12a808","ownedBlank":null,"ui":"New Session Ctrl + Alt + N …"}
{"window":2,"stage":"opened","sessionId":"session-8c62e107-642f-4bb4-9aa6-124fcf12a808","ownedBlank":null,"ui":"New Session Ctrl + Alt + N …"}
{ "verdict": "SHARED", "distinct": 1, "windows": 2 }
```

After the patch — 3 windows, three sessions, and a reload keeps its own:

```
{"window":1,"stage":"opened","sessionId":"session-154a53ca-…","ownedBlank":"session-154a53ca-…"}
{"window":2,"stage":"opened","sessionId":"session-ef2c4f29-…","ownedBlank":"session-ef2c4f29-…"}
{"window":3,"stage":"opened","sessionId":"session-76a5dd4d-…","ownedBlank":"session-76a5dd4d-…"}
{"window":1,"stage":"after-reload","sessionId":"session-154a53ca-…","sameAsBeforeReload":true}
{ "verdict": "ISOLATED", "distinct": 3, "windows": 3 }
```

And again on the **window slots the owner actually uses** — two different loopback origins
(3215, 3216) through `dshw-proxy.mjs`, which is where the per-window origin lives:

```
node multi-window/tools/verify-window-session-isolation.mjs windows --count 2 --origin-port 3215 --reload
{ "verdict": "ISOLATED", "distinct": 2, "windows": 2 }        # reload also kept its own id
```

Catalog census before and after (`… snapshot`): 646 rows / **0 blank rows** before, 6 blank rows
after — exactly the six blanks the two test runs created, all `cwd: C:\Users\ezabz\code`, all
archived afterwards with `… archive <id>…` (`confirmedInArchiveSet: true`). Archived blanks are
excluded from reuse by the retained `archived.includes(...)` guard. Note `snapshot`'s `blankRows`
counts rows with `blank: true`, which includes archived ones.

### What this does and does not prove

* **Proved:** two and three windows no longer share a blank session; a reload of a window keeps its
  own blank instead of making another; the same holds on the proxy slot origins.
* **Not proved by execution:** a live turn typed in one window with the other window watched for the
  text. That needs a real agent turn in a scratch session; the shared-session identity above is the
  necessary and sufficient cause of the word-for-word doubling, and it is gone.
* **Litter:** orphans are the price of not sharing — a blank abandoned by a closed window, or one
  whose workspace is switched away, is no longer adopted by anyone. The estate's archival pass
  already hides blanks; a *stale* catalog answer (the proxy caches `session/list`) can also make a
  window create a fresh blank when its own is missing from the reply. Both are one directory each.

## Residual behaviour worth knowing

* A window that is **already** doubled keeps restoring the shared session until it is given a new
  one — *New session* in that window, or a reload **while the shared session is still blank**.
* `startSession()` on a window whose current session is still its own blank reuses that blank rather
  than creating another (upstream behaviour, kept).
* The fix is per *origin*. Two tabs on one origin share it — as they already share
  `dsh.sessions.current`; the estate's window model is one origin per window
  (`docs/multi-window/MEMORY-AND-SESSION-LIST.md`).
