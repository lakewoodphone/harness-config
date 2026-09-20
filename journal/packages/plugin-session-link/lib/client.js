/**
 * dsh-plugin-session-link — open the session a URL fragment names.
 *
 * WHAT IT IS FOR
 * A DSH window cannot be pointed at a session by URL. Session selection lives in
 * `localStorage["dsh.sessions.current"]`, read once at page load; nothing in the client reads a
 * fragment, and the server matches pathname only (`/session/<id>` is a 404 — measured, and restated
 * in `docs/mesh/20-placement.md` §3.2). So `https://<node>.tail93e6e6.ts.net/#session=<id>` — the
 * link a handoff, a journal entry or a fleet report wants to write down — used to land on whatever
 * that origin last selected, which on a phone is usually not what was meant.
 *
 * WHY THE FRAGMENT, AND WHY IT CAN WORK TODAY
 * Three positions were considered in `docs/mesh/20-placement.md` §3.2 and the measurements under
 * it: a PATH route is a 404 because the static fallback serves `index.html` only at `/`; a QUERY
 * parameter cannot survive, because the engine's `?token=` exchange 303s to the literal `/` and
 * discards every other parameter; the FRAGMENT is the only position the client keeps.
 *
 * ON A COLD VISIT THAT IS NEW, AND IT IS WHAT MAKES THIS SUFFICIENT. A first visit used to mean a
 * redirect through `/?token=<live>`, which drops the fragment. The phone gate
 * (`scripts/phone-gate.py`) no longer redirects: it signs a cold visitor in *in flight* and answers
 * the document itself — measured 2026-09-16, one `200` with the `Set-Cookie` attached and no
 * navigation at all — so a browser keeps the fragment it arrived with. Behind a proxy that
 * redirects instead, a deep link still works, but only for an already-signed-in browser.
 *
 * WHAT IT DOES
 *   1. reads `#session=<id>` at boot; with no fragment it does nothing at all, at any width;
 *   2. reaches the session service the way the shipped client does — `inject: ['sessions']` and
 *      `ctx.get('sessions')` (`dsh-api-session-controller` provides `sessions` on the client and
 *      exposes `open(id)`, which selects a listed or retained session: the same call the UI's own
 *      session list makes when a row is clicked);
 *   3. waits for the list to arrive, because at boot it is `phase: 'pending'`;
 *   4. if the id never appears, leaves the reader on the default selection and says so in ONE
 *      `console.info` line — nothing visual, and never a blank window;
 *   5. clears the fragment once it has acted, so a reload does not re-open a session the reader has
 *      since left, and a later click in the drawer is not undone by a stale URL.
 *
 * The client loader has no module body of its own: a bundle is a plain script that registers a
 * factory with `window.__ModuleLoader__.load`, and the factory must populate `module.exports`. It is
 * NOT an ES module.
 */
window.__ModuleLoader__.load({
  id: 'dsh-plugin-session-link',
  factory: (require) => {
    const module = { exports: {} };
    const exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

    const PARAM = 'session';
    /** 40 x 250 ms = 10 s, the same order as the connection's own reconnect ladder. */
    const ATTEMPTS = 40;
    const RETRY_MS = 250;

    /** The session id in `#session=<id>`, or "" when the fragment says nothing about a session. */
    function fragmentSessionId() {
      try {
        const hash = String(window.location.hash || '');
        if (hash.length < 2) return '';
        const body = hash.replace(/^#/, '').replace(/^\?/, '');
        for (const part of body.split('&')) {
          const eq = part.indexOf('=');
          if (eq <= 0) continue;
          let key = part.slice(0, eq);
          try {
            key = decodeURIComponent(key);
          } catch (error) {
            continue;
          }
          if (key !== PARAM) continue;
          const value = decodeURIComponent(part.slice(eq + 1));
          // A session id is an opaque token; refuse anything that could only be an accident
          // (empty, whitespace, or a document-length string) rather than select on it.
          return /^[^\s/]{1,200}$/.test(value) ? value : '';
        }
      } catch (error) {
        if (window.console) window.console.warn('dsh-plugin-session-link: ' + error);
      }
      return '';
    }

    /** Drop the fragment without reloading, so the URL cannot re-open a session on the next load. */
    function clearFragment() {
      try {
        if (String(window.location.hash || '') === '') return;
        if (window.history === undefined || typeof window.history.replaceState !== 'function') return;
        window.history.replaceState(null, '', window.location.pathname + window.location.search);
      } catch (error) {
        if (window.console) window.console.warn('dsh-plugin-session-link: ' + error);
      }
    }

    /**
     * The client's session service, however this build exposes it.
     *
     * `inject: ['sessions']` is declared below, so the loader resolves the service before this entry
     * activates — that is the mechanism, and reaching a service WITHOUT declaring it is the mistake
     * this repo already paid for once (`packages/plugin-cost/lib/client.js`, which was refused at
     * activation with "cannot get property slots without inject"). The fallback read is a belt on
     * that brace, not the mechanism.
     */
    function sessionService(ctx) {
      try {
        const injected = ctx.get('sessions');
        if (injected !== undefined && injected !== null) return injected;
      } catch (error) {
        // not provided yet
      }
      try {
        const property = ctx.sessions;
        if (property !== undefined && property !== null) return property;
      } catch (error) {
        // same
      }
      return null;
    }

    /**
     * Whether the projected list knows this id: `{present, settled}`, or null when it cannot be read.
     *
     * `sessions.list` is the snapshot store the controller projects (`ids`, `byId`, `current`,
     * `phase`); its `phase` is `'pending'` until the first listing arrives. A null here means "this
     * build does not let me look", which is treated as "keep trying and select anyway" rather than
     * as "absent" — the controller's own contract is that a selection survives a list that has not
     * arrived and resurfaces when its session does.
     */
    function projected(sessions, id) {
      try {
        const list = sessions.list;
        if (list === null || list === undefined) return null;
        const snapshot = typeof list.getSnapshot === 'function' ? list.getSnapshot() : list;
        if (snapshot === null || snapshot === undefined || !Array.isArray(snapshot.ids)) return null;
        return { present: snapshot.ids.indexOf(id) >= 0, settled: snapshot.phase !== 'pending' };
      } catch (error) {
        return null;
      }
    }

    function say(message) {
      if (window.console) window.console.info('dsh-plugin-session-link: ' + message);
    }

    function apply(ctx) {
      const id = fragmentSessionId();
      if (id === '') return;                 // no fragment: this plugin is completely inert
      let attempts = 0;

      const attempt = () => {
        attempts += 1;
        const sessions = sessionService(ctx);
        if (sessions === null || typeof sessions.open !== 'function') {
          if (attempts < ATTEMPTS) {
            window.setTimeout(attempt, RETRY_MS);
            return;
          }
          say('the session service never became available; staying on the default selection');
          clearFragment();
          return;
        }
        const state = projected(sessions, id);
        if (state !== null && state.present === true) {
          try {
            sessions.open(id);
            say('opened ' + id + ' from the URL fragment');
          } catch (error) {
            say('could not select ' + id + ': ' + error);
          }
          clearFragment();
          return;
        }
        if (state !== null && state.settled === true) {
          // The list has arrived and does not contain the id: it does not exist on this node.
          // Nothing visible is changed, and the reader is told once, in the console.
          say('no session ' + id + ' on this node; staying on the default selection');
          clearFragment();
          return;
        }
        if (attempts < ATTEMPTS) {
          // Still loading. Nothing is selected yet: waiting is what keeps a bad id from blanking
          // the window, which is the failure this ordering exists to prevent.
          window.setTimeout(attempt, RETRY_MS);
          return;
        }
        // Out of time with the list never settling. Select anyway — the controller stages a
        // selection across an unarrived list — and say what happened.
        try {
          sessions.open(id);
          say('selected ' + id + ' without ever seeing the session list settle; verify it exists');
        } catch (error) {
          say('the session list never settled and ' + id + ' could not be selected');
        }
        clearFragment();
      };

      attempt();
    }

    exports.apply = apply;
    // Declared, not assumed: a service reached without this refuses the plugin at activation.
    exports.inject = ['sessions'];
    return module.exports;
  },
});
