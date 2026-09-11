# Research: does any URL select a DSH session? (`research-session-urls.md`)

**Question.** How does the running DSH Web GUI represent "which session am I looking at" — and therefore, can a
window be restored to a specific session?

**Answer in one line.** No. The URL carries no session identity at all. The selected session lives in
`localStorage["dsh.sessions.current"]`, is scoped to that browser **origin** (scheme + host + **port**), and is
re-applied only when the page loads. Session choice at runtime is purely in-app.

**Provenance.**
Read on `ZABZ-YOGA` (Windows 11) on **2026-09-11**, between 13:00 and 13:15 local (-04:00) / 17:00–17:15 UTC.
Method for all code citations: `[System.IO.File]::ReadAllText()` + regex/`IndexOf` over the installed packages
under `C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\`, and `Select-String` for line-numbered matches.
Shell-bundle positions are cited as **absolute character offsets**, because that file is minified and has almost
no newlines.
Live probe target: the `dsh web` instance at `http://127.0.0.1:3080` (`DSH_WEB_URL=http://127.0.0.1:3080`,
observed from `Get-ChildItem env: DSH*`), plus a read-only inspection of already-running second/third instances.

### Instances observed running at the time of writing

`Get-CimInstance Win32_Process` filtered on command line, 2026-09-11 13:13 local:

| PID | command line (truncated to 160 chars) |
|---|---|
| 54868 | `npx-cli.js @deepseek-ai/dsh web` (the hand-started 3080 instance) |
| 23888 | `...\dsh\lib\bin.js web --port 3081 --no-op…` |
| 59480 | `...\dsh\lib\bin.js web --port 3082 --no-op…` |
| 34416 | `...\dsh\lib\bin.js web --port 3083 --no-op…` |
| 17984 | `...\dsh-subprocess-local\lib\runner.js` |

The `--no-op…` is my 160-character truncation (`--no-open`); I did not read the full line. **Notable for the
parent: three additional `dsh web` servers (3081/3082/3083) are already running**, launched by the existing
`dshw` harness described in `C:\Users\ezabz\.dsh\multi-window\test3.json`.

---

## 1. Is there any URL that selects a session (path, `#`, or query)?

**No.** There is no path route, no `#` fragment, and no query parameter that selects a session.

### 1a. No History/URL routing exists in the client at all

Command (all 65 `client.js` files under `@deepseek-ai`, case-insensitive occurrence counts on the full text of
each file):

```powershell
$all | ... ; foreach ($pat in @('pushState','replaceState','popstate','hashchange','location\.hash',
  'location\.search','location\.href','location\.pathname','history\.pushState','history\.replaceState')) { ... }
```

Observed output:

```
files=65
pushState               total=0
replaceState            total=0
popstate                total=0
hashchange              total=0
location\.hash          total=0
location\.search        total=4   (2 files × 2)
location\.href          total=0
location\.pathname      total=0
history\.pushState      total=0
history\.replaceState   total=0
```

The `location.search` total of 4 is 3 real call sites plus one case-insensitive false positive
(`pageLocation.search`); the exact lines:

```
\dsh-client-connection\lib\client.js:6146: const query = new URLSearchParams(location.search);
\dsh-client-connection\lib\client.js:6306: const fixtureRpc = pageLocation !== void 0 && new URLSearchParams(pageLocation.search).has("fixture") ? createFixtureConnectionRpc() : void 0;
\dsh-client-file-upload\lib\client.js:283: return typeof pageLocation === "object" && pageLocation !== null && "search" in pageLocation && typeof pageLocation.search === "string" && new URLSearchParams(pageLocation.search).has("fixture");
```

**All three read the `fixture` dev switch only** — nothing reads a session id. See §4 for the full parameter list.

Shell bundle, same method on
`C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\dsh-web-frontend\dist\assets\index-BKQ_L1z6.js`
(555,926 chars):

```
sessionId : 0
pushState : 0
replaceState (case-sensitive) : 0
location.hash : 0
location.search : 0
URLSearchParams : 0
hashchange : 1
```

- The 4 case-*insensitive* `replaceState` hits are React's `enqueueReplaceState` (case-sensitive count is 0);
  the matched context reads `enqueueForceUpdate:function(){},enqueueReplaceState:function(){},enqueueSetState:function(){}`.
- The single `hashchange` hit at char offset **82697** is React's discrete-event priority list
  (`case"blur":case"fullscreenchange":case"focus":case"hashchange":case"popstate":case"select":…`), not a listener.
- `sessionId` appears **zero** times in the shell bundle — the BRIEF's item 6 is confirmed independently.

### 1b. The server cannot route on anything but the pathname

`dsh-host-webserver\lib\index.js:231`:

```js
const rawPath = new URL(req.url ?? "/", "http://x").pathname;
const route = this.match(rawPath);
```

Only `pathname` is used; the query string is never part of route matching.

`dsh-host-frontend-static\lib\index.js:59–62, 85` — the SPA fallback renders index.html **only** at the dist
root or at the configured index path, and forces a base href:

```js
if (target === distRoot || target === distIndex) {
        if (!authorizeIndex()) return;
        body = await renderIndex();
        type = HTML_MIME;
} else { body = await readFile(target); … }
…
return ctx.webServer.renderIndex(await readFile(distIndex, "utf8")).replace(/<head(?:\s[^>]*)?>/i, (open) => `${open}<base href="/">`);
```

Everything else falls through to `readFile` and 404s. **There is no SPA catch-all**, so a deep link of the form
`/session/<id>` cannot even reach the app. Confirmed empirically (§3).

### 1c. The `?token=` exchange discards every other query parameter

`dsh-client-connection\lib\index.js:386–425` (`authorizeIndex`):

```js
const url = new URL(req.url ?? "/", "http://dsh.invalid");
const tokens = url.searchParams.getAll(TOKEN_QUERY);
if (tokens.length > 0) {
        const authority = requestAuthority(req.headers);
        if (req.method === "GET" && url.pathname === "/" && tokens.length === 1 && authority !== void 0 && tokenMatches(tokens.join(""), this.launchToken)) {
                … res.writeHead(303, { … "location": "/", … "set-cookie": sessionCookie(...) });
```

- Only `pathname === "/"` is accepted, so `/?token=…` works but `/anything?token=…` does not.
- The 303 target is the literal `"/"`. **Any other query parameter riding along is dropped**, so a session
  parameter cannot survive authentication even if someone later added a reader for it.
- A request carrying a `token` parameter that does *not* match, with a valid cookie, is also 303'd to `"/"`;
  otherwise it gets the 401.

**Conclusion for Q1:** the only URL that means anything is `http://<host>:<port>/` (optionally
`/index.html`), with an optional single `?token=` on first contact. Session identity is never in the URL.

---

## 2. Where is the currently-selected session remembered?

**`localStorage`, key `dsh.sessions.current`, on the page's own origin. Owner package:
`@deepseek-ai/dsh-api-session-controller`.**

### 2a. The authoritative declaration

`C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\dsh-api-session-controller\lib\client.js`

Line **3058** (inside the client session-controller constructor):

```js
this.selection = (0, _deepseek_ai_dsh_client_store.createSnapshotStore)({}, { persist: { name: "dsh.sessions.current" } });
const restored = this.selection.getSnapshot();
this.manager = new SessionManager(remote, restored.sessionId, restored.subagentAddress);
```

Lines **3052–3039** (doc comments, verbatim) describe it as the *"Persisted selection cell (the durable half of
`list.current`)"* and *"a selection survives transient list states (reconnect re-pull) and resurfaces when its
session returns."*

It is **read once, at construction**, and handed to the `SessionManager` — i.e. **the last selected session is
what a freshly loaded page opens**.

### 2b. The write path (last writer wins, whole object replaced)

Same file, `projectList()`, lines **3409–3415**:

```js
const persisted = this.selection.getSnapshot().sessionId;
if (current === void 0) {
        if (persisted !== void 0) this.selection.set({});
} else if (byId[current] !== void 0 && (persisted !== current || … subagentAddress mismatches …)) this.selection.set({
        sessionId: current,
        ...currentAddress === void 0 ? {} : { subagentAddress: currentAddress }
});
```

`ClientSessions.open(id)` → `this.manager.select(id)` (line 3093–3095) is the only user-driven path; the write
happens when the projected `list.current` changes.

So the persisted value is a **single object**, normally
`{"sessionId":"<id>"}`, or `{sessionId, subagentAddress}` when a subagent view is open. There is one slot per
origin, not a map.

### 2c. The persistence mechanism itself

The store library is **not shipped as its own package** — `Test-Path ...\@deepseek-ai\dsh-client-store` →
`False`; it is bundled into the shell shell and into each consumer bundle. Implementation in
`dsh-web-frontend\dist\assets\index-BKQ_L1z6.js` at **char offset 198631**:

```js
function Tc(t,r){if(!(typeof localStorage>"u")){
  try{const i=localStorage.getItem(r);i!==null&&t.setState(M6(JSON.parse(i)),!0)}
  catch(i){console.error(`snapshot store '${r}' rehydration failed:`,i)}
  t.subscribe(i=>{try{localStorage.setItem(r,JSON.stringify(i))}catch(s){console.error(`snapshot store '${r}' persistence failed:`,s)}})}}
```

and at **char offset 198819** (the scoping rule):

```js
const i = t.persist === void 0 ? void 0 : r === void 0 ? t.persist : `${t.persist}.${r}`;
```

`r` is a per-instance scope suffix (a session id, for the session-scoped stores). So:
**the localStorage key is exactly `persist.name`, JSON-encoded value, plain `localStorage` — no prefix, no
server round-trip.**

### 2d. Every persisted client key I can find (complete list)

Per-file scan of all 65 `client.js` files for `localStorage|sessionStorage` returned matches in **exactly one
file** (`dsh-client-ui-conversation\lib\client.js`); all other keys come through the bundled store
(`persist:`/`createSnapshotStore`) and therefore also land in `localStorage` via `Tc` above.

| Key | Owner package / file:line | Contents |
|---|---|---|
| **`dsh.sessions.current`** | `dsh-api-session-controller\lib\client.js:3058` | **the selected session** — `{sessionId[, subagentAddress]}` |
| `dsh.conversation.<sessionId>` | `dsh-client-ui-conversation\lib\client.js:2703, 2715, 2744` | per-session draft text + View selection (`readConversationViewPreference(sessionId)` at 2741 reads `localStorage.getItem(\`${CONVERSATION_STORE_KEY}.${sessionId}\`)`) |
| `dsh.conversation.contentWidth` | `dsh-client-ui-conversation\lib\client.js:14691, 14703, 14849` | dragged transcript width (px) — global, last-writer-wins |
| `dsh.workspace.view.v5` | `dsh-client-ui-workspace\lib\client.js:203` | workspace/sidebar grouping, ordering, session order |
| `dsh.trajectory.duration` | `dsh-client-ui-trajectory\lib\client.js:41` | trajectory timing display toggle |
| `dsh.open-in-app.choice` | `dsh-client-ui-open-in-app\lib\client.js:41` | preferred external app |

`sessionStorage`: **zero** occurrences in any `client.js` (per-file count) and **zero** in the shell bundle.
Everything is `localStorage` — i.e. shared across every tab/window of the same origin and persistent.

### 2e. On-disk confirmation (independent of the app)

The `dshw` harness runs each window in its own Edge profile
(`C:\Users\ezabz\.dsh\multi-window\browser\w1`, `w2`, …; see `test3.json`). I read the LevelDB files under
`…\browser\w1\Default\Local Storage\leveldb\000003.log` (opened `FileShare.ReadWrite` because the profile is
live). Chromium stores `localStorage` as `<prefix><origin>` `\x00` `<key>` `\x00` `<value>`; printable runs:

```
-_http://127.0.0.1:3081..dsh.workspace.view.v5…{"groupBy":"workspace","orderBy":"updated",…}
-_http://127.0.0.1:3081..dsh.sessions.current..{"sessionId":"session-1b8e6fa7-bb02-4025-8996-4cfe005e4dc6"}
```

and in profile `w2`:

```
,_http://127.0.0.1:3082..dsh.sessions.current..{"sessionId":"session-1b8e6fa7-bb02-4025-8996-4cfe005e4dc6"}
-_http://127.0.0.1:3082..dsh.workspace.view.v5…{…,"__flat_session_order__":["session-1b8e6fa7-…"]}
```

Three things this proves independently of the source code:

1. The key **`dsh.sessions.current` is exactly right, with no prefix** — matching §2c.
2. The value is the small JSON object `{"sessionId":"…"}`.
3. The record is **tagged by full origin including the port** — `http://127.0.0.1:3081` and
   `http://127.0.0.1:3082` are separate namespaces in the *same* browser profile. Profile `w1` is the only
   place I saw the same key overwritten in place: LevelDB (append-only) retains two successive generations of
   the neighbouring `dsh.workspace.view.v5` value for origin `127.0.0.1:3081` — the first without
   `session-1b8e6fa7-…`, the second with it and with a newer `sessionUpdatedAtByAccount` entry
   (`1789146645526` ms = **2026-09-11 13:10:45 -04:00**) — while `dsh.sessions.current` appears once and holds
   `session-1b8e6fa7-…`, i.e. that key is a single slot whose value was replaced, not appended to. I did **not**
   capture an earlier distinct value of `dsh.sessions.current` itself.

---

## 3. Empirical check against the live app

### 3a. Playwright navigation — **401 Unauthorized**

I drove the Playwright MCP browser (one pre-existing `about:blank` page; no user windows touched, nothing
typed, nothing submitted, no window closed).

```
browser_navigate  url: http://127.0.0.1:3080/
```

Observed:

```
- Page URL: http://127.0.0.1:3080/
- HTTP status: 401 Unauthorized
- Console: 2 errors, 0 warnings
```

**Verbatim finding: the page returns 401 and requires the launch token.** Exact evaluation run
(`browser_evaluate`, single call, verbatim source):

```js
async () => {
  const out = {};
  out.href = document.location.href;
  out.origin = document.location.origin;
  out.pathname = document.location.pathname;
  out.search = document.location.search;
  out.hash = document.location.hash;
  out.cookie = document.cookie;
  try { out.localStorageKeys = Object.keys(localStorage); } catch (e) { out.localStorageKeys = 'THREW: ' + String(e); }
  try { out.sessionStorageKeys = Object.keys(sessionStorage); } catch (e) { out.sessionStorageKeys = 'THREW: ' + String(e); }
  out.bootType = typeof window.__DSH_BOOT__;
  out.bootIsNull = window.__DSH_BOOT__ === null;
  out.bootKeys = (window.__DSH_BOOT__ && typeof window.__DSH_BOOT__ === 'object') ? Object.keys(window.__DSH_BOOT__) : null;
  out.bootJson = window.__DSH_BOOT__ === undefined ? 'undefined' : JSON.stringify(window.__DSH_BOOT__).slice(0, 400);
  out.dshGlobals = Object.keys(window).filter(k => k.startsWith('__DSH'));
  out.manifestLinks = [...document.querySelectorAll('link[rel=manifest]')].map(l => ({ rel: l.rel, href: l.href, getAttributeHref: l.getAttribute('href') }));
  out.title = document.title;
  out.bodyText = document.body ? document.body.innerText.slice(0, 300) : null;
  out.docHTMLHead = document.documentElement.outerHTML.slice(0, 400);
  return out;
}
```

Raw observed result:

```json
{
  "href": "http://127.0.0.1:3080/",
  "origin": "http://127.0.0.1:3080",
  "pathname": "/",
  "search": "",
  "hash": "",
  "cookie": "",
  "localStorageKeys": [],
  "sessionStorageKeys": [],
  "bootType": "undefined",
  "bootIsNull": false,
  "bootKeys": null,
  "bootJson": "undefined",
  "dshGlobals": [],
  "manifestLinks": [],
  "title": "",
  "bodyText": "dsh web authentication required; reopen the URL printed by dsh web.\n",
  "docHTMLHead": "<html><head><meta name=\"color-scheme\" content=\"light dark\"></head><body><pre style=\"word-wrap: break-word; white-space: pre-wrap;\">dsh web authentication required; reopen the URL printed by dsh web.\n</pre></body></html>"
}
```

Interpretation, stated plainly:

- `window.__DSH_BOOT__` is `undefined` and there are **no** `__DSH*` globals, because the shell module never
  ran — the 401 body is a plain `<pre>` document, not `index.html`. The boot object therefore **cannot be
  observed from an unauthenticated context**. This is a refusal, not a null result: I did not obtain a boot
  object, I obtained proof the app was not loaded.
- `Object.keys(localStorage)` → `[]`, and `document.cookie` → `""`. This Playwright browser context has never
  authenticated to this origin, so the origin has no first-party storage yet. **This is not evidence about
  what the authenticated app writes**; for that see §2e (read from a real profile's LevelDB).
- `link[rel=manifest]` → `[]` — the 401 page has no manifest link. The real `index.html` does (see §3c).
- The 401 body string matches the packaged source verbatim: `dsh-client-connection\lib\index.js:442`

```js
writeUnauthorized(req, res) {
        res.writeHead(401, { "cache-control": "no-store", "content-type": "text/plain; charset=utf-8" });
        res.end(req.method === "HEAD" ? void 0 : "dsh web authentication required; reopen the URL printed by dsh web.\n");
}
```

### 3b. Direct HTTP probes of the same instance

Commands (PowerShell `Invoke-WebRequest -MaximumRedirection 0`), observed output:

```
=== GET / (no token, no cookie) ===        STATUS 401
=== GET /manifest.webmanifest ===          STATUS 200   CT: application/manifest+json
=== GET /some/random/path ===              STATUS 404
=== GET /?token=bogus ===                  STATUS 401
=== GET /?session=abc (no token) ===       STATUS 401
```

Two findings worth naming explicitly:

- **`/some/random/path` → 404.** Confirms §1b: a path segment cannot reach the SPA. There is no route to be
  exploited, deliberately or accidentally.
- **`/?session=abc` → 401**, i.e. an unknown query parameter grants nothing and (per §1c) is discarded by the
  token exchange.

(The `RedirectStandardError` note in the transcript — a disposed `GZipDecompressedContent` stream when I tried
to re-read the 401 body through .NET — is a PowerShell artifact of my own probe; the body was captured
cleanly by the browser instead, above.)

### 3c. Manifest

`http://127.0.0.1:3080/manifest.webmanifest` → **200**, `content-type: application/manifest+json`; the response
body was returned by `Invoke-WebRequest` as a byte array which decodes exactly to the packaged file
`C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\dsh-web-frontend\dist\manifest.webmanifest`:

```json
{
  "id": "/",
  "name": "DeepSeek Harness",
  "short_name": "DSH",
  "start_url": "/",
  "scope": "/",
  "display": "fullscreen",
  "icons": [
    { "src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any" }
  ]
}
```

The document's only manifest reference is in the packaged `dist\index.html`:

```html
<link rel="manifest" href="./manifest.webmanifest" />
```

Relative, and the fallback injects `<base href="/">` into every index response
(`dsh-host-frontend-static\lib\index.js:85`), so it resolves to `/manifest.webmanifest`.

**PWA relevance to the multi-window goal:** `start_url: "/"`, `scope: "/"`, and there is no service worker
(confirmed by the BRIEF; I did not re-verify). A PWA/`--app` shortcut therefore always opens **the origin
root**, i.e. the last-selected session — it cannot be made to open a chosen session. `"display": "fullscreen"`
also means an installed shortcut would lose window chrome, which is probably wrong for 8–12 tiled windows.

---

## 4. What an independent window needs to show a chosen session

**Session choice is purely in-app after load.** No startup parameter selects a session. A window shows a
chosen session only if (a) its origin's `localStorage["dsh.sessions.current"]` already names that session, or
(b) a human clicks it.

### 4a. Complete list of parameters the app honours at load

| Parameter | Where honoured | What it does |
|---|---|---|
| `?token=<launchToken>` | `dsh-client-connection\lib\index.js:386–425` (server) | **the only auth path.** Requires `GET`, `pathname === "/"`, exactly **one** `token` param, and a `Host`/`Origin` that passes the loopback/trusted fence. On success: 303 → `/` and `set-cookie: dsh-auth-<base64url(sha256(authority))>=…; Max-Age=…; Path=/; Expires=…; HttpOnly; SameSite=Strict`. |
| (the resulting cookie) | same file, `isAuthenticated()` | Cookie name binds **normalized host+port**; signing secret is stored at credential key `client-connection/browser-session` in `$DSH_HOME/.credentials.yaml`; `cookieMaxAgeDays` default **30** (`lib\index.js:740`, `753`). So cookies survive a server restart and a relaunch can simply open the clean root URL. |
| `fixture` | `dsh-client-connection\lib\client.js:6306` | **Presence alone** swaps the entire connection transport for an in-memory fixture world: `new URLSearchParams(pageLocation.search).has("fixture") ? createFixtureConnectionRpc() : void 0`. Live in shipped code — *not* gated by a build flag. |
| `fixture=empty`, `fixturePrompt=reject`, `fixtureAttach=fail`, `fixtureSessionCreate=drop-response`, `fixtureFrames=workspace-first`, `fixtureFileChanges=demo` | `dsh-client-connection\lib\client.js:6144–6155` (`fixtureOptionsFromLocation`) | Dev/test switch values. `dsh-client-file-upload\lib\client.js:283` has a parallel `has("fixture")` check. |
| `--host`, `--port`, `--trusted-host`, `--no-open` | `dsh-web-app\lib\startup.js:21–48` | **Server launch flags, not URL parameters.** `--host 0.0.0.0` is rejected at startup with an explicit safety error. |

**Nothing else.** No `session`, no `sessionId`, no `workspace`, no `window`, no `#` fragment is read by any
installed client bundle (see the §1a counts).

### 4b. The consequence for restore

To restore a window onto a specific session you must control one of:

1. **The origin** — because the selection is per-origin, a distinct port gives a distinct, independent
   selection slot for free. This is exactly what `test3.json` already does (`basePort: 3081`, one port and one
   browser profile per window slot).
2. **`localStorage["dsh.sessions.current"]`** on that origin — writable before load by any same-origin
   mechanism, but as of now nothing in the product exposes it as a URL or flag. **UNVERIFIED:** whether a
   pre-load write is possible without a client-plugin/shell change; I did not attempt it, because that would
   mean modifying the running app's state, which this task forbids.
3. **A click.** Always available.

Passing a chosen session id in the URL is **not** possible today: nothing reads it, the SPA fallback 404s every
path but `/`, and the token exchange strips extra query parameters.

---

## 5. Can several windows on the *same origin* each sit on a different session?

**Yes while they are open; no across a reload.** And yes, there is a genuine last-writer-wins conflict.

### 5a. What is proven

- There is exactly **one** `localStorage` slot per origin for the selection:
  `createSnapshotStore({}, { persist: { name: "dsh.sessions.current" } })`
  (`dsh-api-session-controller\lib\client.js:3058`) — a single key, and `selection.set(...)` replaces the whole
  object (`:3411–3415`).
- `localStorage` is per-origin and shared by all windows/tabs of that origin in one browser profile — this is
  what makes §2e readable in a single LevelDB per profile, where the origin tag
  `http://127.0.0.1:3081` appears once and the key appears under it once.
- The value is read **only at construction** (`:3059–3060`), i.e. **at page load**. A live window does not
  listen for storage events to follow another window's selection.

### 5b. The resulting behaviour, stated exactly

- N windows on the *same* origin: each holds its own in-memory selection, so they can be on N different
  sessions simultaneously and remain so while open. ✓
- Any of those windows selecting a session writes the one shared key. A **reload / new window / crash-restore
  / PWA launch / "reopen last session"** then opens whichever session was selected **most recently by any
  window on that origin** — not necessarily the one that window was showing. That is the last-writer-wins
  conflict, and it is real.
- Two windows on the same origin **cannot** be independently restored to two different sessions by any
  URL/flag mechanism that exists today.
- **Different ports are different origins.** `http://127.0.0.1:3080` and `http://127.0.0.1:3081` each have
  their own `dsh.sessions.current` and their own auth cookie (the cookie name is derived from the request
  authority, `cookieName(authority)`), so **the conflict does not exist between windows on different ports.**
  This is why the existing `dshw` design (`basePort: 3081`, unique `profile` per window) already sidesteps it.
  §2e is the direct evidence: profiles `w1` and `w2` hold fully independent per-origin key spaces.

### 5c. What I would need in order to prove the reload-conflict end-to-end

I could not complete the live end-to-end demonstration, and I will not claim it:

1. **A credible credential for one instance.** Port 3080 returned 401 and its launch token is **not on disk**:
   `authenticatedUrl()` builds `http://127.0.0.1:<port>/?token=<random 32-byte base64url>` from
   `processLaunchToken(owner)` held in a `WeakMap` in memory (`dsh-client-connection\lib\index.js:240–246`,
   `370–377`). I searched `$env:TEMP` (6 recent `*.log`) and `$HOME\.dsh` for the printed line
   `dsh web: http` and found it **only** for a different, separately-launched instance:
   `C:\Users\ezabz\.dsh\multi-window\logs-test\3081.log:1` → `dsh web: http://127.0.0.1:3081/?token=<REDACTED>`
   (value deliberately redacted here — it is a live credential for the running 3081 process, and this file is
   committed to git). The token is never written to disk by the app itself; it exists on disk only in `dshw`'s
   captured stdout.
2. **Two pages on that same origin in one browser context**, then: select session A in page 1, select session
   B in page 2, read `localStorage["dsh.sessions.current"]` (expect B), reload page 1, and observe which
   session it opens (expect B). That is the decisive experiment.
3. I deliberately **did not** run it on 3081/3082/3083, because doing so would require pasting a live launch
   token and driving the user's currently-running multi-window test browsers — out of scope for a read-only
   research task.

**UNVERIFIED:** the reload-conflict's exact user-visible outcome. The mechanism (single shared key, read at
load only, one writer) is proven from source plus on-disk state; the end-to-end reload demo is not.

---

## 6. Answers to the five questions, compressed

1. **No URL selects a session.** Zero `pushState`/`replaceState`/`popstate`/`hashchange`/`location.hash` in all
   65 client bundles and the shell bundle; `sessionId` appears 0 times in the shell bundle; the server matches
   on pathname only; the SPA fallback serves index.html only at `/` (every other path 404s, verified live);
   the `?token=` exchange 303s to the literal `"/"`, discarding other query parameters. Nothing to cite but
   absence — and the absence is total.
2. **`localStorage["dsh.sessions.current"]`**, owned by `@deepseek-ai/dsh-api-session-controller`
   (`lib\client.js:3058`), written by the list projection (`:3411–3415`), read once at page load
   (`:3059–3060`), JSON value `{sessionId[, subagentAddress]}`, persisted by the bundled store via plain
   `localStorage.setItem` (shell bundle char 198631). Confirmed on disk in profile `w1`/`w2`.
   Other keys are listed in §2d; `sessionStorage` is used nowhere.
3. **Live app: `http://127.0.0.1:3080/` returns `401 Unauthorized` with body
   `"dsh web authentication required; reopen the URL printed by dsh web.\n"`.** In that state
   `location.href` = `http://127.0.0.1:3080/`, `search` = `""`, `hash` = `""`, `document.cookie` = `""`,
   `Object.keys(localStorage)` = `[]`, `window.__DSH_BOOT__` = `undefined`, no `__DSH*` globals,
   `querySelectorAll('link[rel=manifest]')` = `[]`. `GET /manifest.webmanifest` = **200**
   `application/manifest+json`, byte-identical to the packaged manifest (`start_url: "/"`, `scope: "/"`,
   `display: "fullscreen"`). `GET /some/random/path` = **404**. `GET /?session=abc` = **401**.
4. **Session choice is purely in-app after load.** Load-time parameters honoured, exhaustively: `token`
   (server-side auth, only on `pathname === "/"`), the `fixture*` dev switches (client-side, live in shipped
   code), and the *server* flags `--host/--port/--trusted-host/--no-open`. Nothing session-related.
   An independent window needs: a distinct **origin** (its own port) to get an independent selection slot, or
   a same-origin pre-load write to `dsh.sessions.current`, or a click. The first option already exists and is
   running.
5. **Same-origin windows can be on different sessions while open, but the shared single
   `dsh.sessions.current` key is last-writer-wins, and it is re-read on every reload** — so a reload lands on
   whichever session any window on that origin selected most recently. **Different ports are different origins
   and have no such conflict** (proven by the per-origin LevelDB namespaces in profiles `w1` and `w2`). Full
   end-to-end reload proof needs one live launch token plus two same-origin pages; see §5c.

---

## 7. Residual unknowns / explicitly unverified

- `UNVERIFIED:` the end-to-end reload-conflict demonstration (§5c) — needs a live token and two same-origin
  pages.
- `UNVERIFIED:` whether the authenticated `dsh web` boot object contains anything session-related at top level.
  I did not obtain a boot object (401). From source it is the client-module graph
  (`dsh-client-modules\lib\index.js:426–430`: `{ kind: "global", name: "__DSH_BOOT__", value: graph }` where
  `graph` is the composed plugin/batch entry graph), plus `__DSH_CONNECTION_RECOVERY__`
  (`dsh-client-connection\lib\index.js:760–766`) — but "from source" is not "observed".
- The 3080 instance's *in-memory* currently-selected session is unknown to me and I did not try to infer it.
- I did not verify whether a service worker exists (took the BRIEF's word; my own counts found no
  `navigator.serviceWorker` search attempted). Treat "no service worker" as **UNVERIFIED by this task**.
- Tooling gotcha for future work, recorded because it silently produced a false negative here: in this `pwsh`
  environment, `Get-ChildItem 'C:\Users\ezabz\.dsh\...' -Recurse -Filter client.js` returned **0 files** while
  per-child-directory recursion on the same tree returned all 65. `Get-ChildItem -Recurse` from that root is
  unreliable; enumerate children in a loop instead. My first two greps were invalidated by this and their
  "no matches" results were discarded.
