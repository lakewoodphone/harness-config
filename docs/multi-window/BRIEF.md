# Multi-window / multi-session DSH — shared research brief

**Question this work answers.** How do we run at least 8 (target 12) independent DSH sessions, each in its
own window, robustly, on both `ZABZ-YOGA` (Windows laptop) and `ZABZ-TECH` (Windows desktop, i9/64 GB) —
including: reopening every window after the machine/app restarts, and a one-click way to open a new
window for a new session.

## Facts already established (do not re-derive; verify only if cheap)

Established on **ZABZ-YOGA**, 2026-09-11, by reading the installed packages directly
(`C:\Users\ezabz\.dsh\profiles\node_modules\@deepseek-ai\...`):

1. `dsh web` = `dsh --profile web`. The launcher (`@deepseek-ai/dsh` 0.1.5-rc.1) parses only its own
   flags; anything after them belongs to the booted profile's app plugin. So `--port`, `--host`,
   `--trusted-host`, `--no-open` are *web-app* flags (`dsh-web-app` README, `src/startup.ts`).
2. The host HTTP server is `@deepseek-ai/dsh-host-webserver`: config `host` (only `127.0.0.1` or
   `0.0.0.0`; `--host 0.0.0.0` is *rejected* at startup by the web app) and `port` (`0` = OS-assigned).
   `EADDRINUSE` rejects plugin init with a bind diagnostic — it does not silently pick another port.
3. One server process hosts **many independent agent sessions** ("Each browser session composes its own
   agent from the shipped presets … instead of sharing one process-wide tool set" — `dsh-web-app` README).
   Multiple browser windows/tabs pointing at one port are all clients of the same process.
4. Browser auth: each process mints a random launch token; only `GET /?token=...` is accepted and it
   writes an authority-bound signed cookie (name binds **normalized hostname + port**, `HttpOnly`,
   `SameSite=Strict`, default 30-day max age) then redirects to clean `/`. The signing secret is in
   `$DSH_HOME/.credentials.yaml` (`client-connection/browser-session`), so **cookies survive a server
   restart** and a relaunch can simply open the clean root URL. `Host`/`Origin` checks: loopback or a
   `trustedHosts` entry; `sec-fetch-site: cross-site` refused.
5. The frontend dist (`dsh-web-frontend`) is a shell only. It has **no service worker** and the
   `manifest.webmanifest` exists with `"display": "fullscreen"`, `start_url: "/"`, `scope: "/"`.
   Client plugin code is served at runtime from each package's `lib/client.js` through
   `dsh-client-modules` and injected as `window.__DSH_BOOT__`; the shell bundle is one Vite chunk, so any
   new UI component must be added as a **client-side package** (see the `cordis-plugin-development` skill),
   not by editing the shell.
6. The shell bundle contains no `pushState`/`location.hash` routing and the string `sessionId` appears
   zero times in it — **suspected: no per-session deep-link URL.** Must be confirmed from the client
   packages and the live app.
7. `DSH_HOME` = `C:\Users\ezabz\.dsh` (state: `profiles/`, `sessions/`, `storages/`, `.agent-presets/`,
   `settings.yaml`, `.credentials.yaml`). The profile's plugin layering is
   `profiles/web/package.json` → `dsh.profile.bundles` (currently `dsh-base`, `dsh-web-app`), then
   `profiles/web/cordis.patch.yml`, then `$DSH_HOME/cordis.patch.yml`, then `--patch` overlays.
   `patchReload: live` watches the profile and home patch files.
8. Observed process cost on ZABZ-YOGA (idle, 2026-09-11): the `dsh web` server process (~830 MB working
   set) plus 8 `dsh-subprocess-local/lib/runner.js` children at ~60 MB each. MCP servers are separate
   `npx`/node processes (firecrawl, jina, context7, fetch, playwright) and are the same kind of cost per
   server process — this matters when multiplying processes.
9. The launcher README states: the profile name **`desktop` is reserved for the Electron-owned profile**,
   and the CLI rejects boot/config-dump/plugin management for it. **Status of that desktop app on these
   machines is unknown** — no `dsh-desktop`-like package is installed under `.dsh/profiles/node_modules`,
   and no global `dsh` desktop app was found.
10. There is no `dsh web` supervisor/launcher today; the session that produced this brief was started by
    hand (`npx @deepseek-ai/dsh web`) and died with the terminal/OS.

## Constraints that are not negotiable

- Windows. PowerShell 7 (`pwsh`) is the shell. `ZABZ-YOGA` and `ZABZ-TECH` are on **separate networks**;
  Tailscale (`tail93e6e6.ts.net`) is the only path between them.
- Never destroy data. No deleting `$DSH_HOME` content, no `rm -rf`, no killing processes that hold
  another human's work without explicit per-action approval.
- Anything that must survive or be seen from another machine is committed in `~/code/harness-config`
  (git, remote on `secratary`), never left only on one machine.
- Do not spend more than ~10 minutes per task; prefer a precise answer with evidence and explicitly
  named unknowns over a broad one.

## Deliverable style

Write findings into your assigned file under `C:\Users\ezabz\code\harness-config\docs\multi-window\`.
Every claim carries **where it came from** (file path + line, command + its output, or URL) and **when**
it was read. An unverifiable guess is labelled `UNVERIFIED:`. A refusal to answer ("cannot determine
from what is installed") is a valid, useful finding — a confident wrong claim is not.
