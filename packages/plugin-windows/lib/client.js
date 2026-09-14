/**
 * dsh-plugin-windows — the browser half.
 *
 * TWO CONTROLS, BESIDE THE COMPOSER:
 *
 *   +   new session, this window. Forgets this window's remembered session and reloads,
 *       so the app boots blank — the same state as a window that has never been used. The
 *       previous conversation is not lost: it stays in the session list and can be reopened
 *       from the sidebar. This is the "many conversations in one window" path.
 *
 *   ⧉   new session, new window. Hands `dsh-new://open` to Windows, which runs the
 *       launcher (`dshw new`); the launcher opens a fresh browser profile + window against
 *       the same engine, so it is a new conversation in its own window. This is the "several
 *       conversations side by side" path.
 *
 * WHY THE FIRST ONE IS A STORAGE RESET AND NOT AN API CALL
 * The app decides which conversation a window shows from one persisted key,
 * `dsh.sessions.current`, read once at page load (dsh-api-session-controller, client half:
 * `createSnapshotStore({}, { persist: { name: 'dsh.sessions.current' } })` -> the restored
 * `sessionId` is handed to `SessionManager`). Clearing that key and reloading therefore
 * produces exactly the blank-window state, using the app's own bootstrap path instead of a
 * private API. Nothing is deleted and nothing on the host changes.
 *
 * WHY IT OWNS NO DEPENDENCIES
 * The browser loader treats every name in a Plugin's `inject` and in the package's
 * `dsh.client.inject` as a SERVICE it must resolve before the entry may activate. A wrong
 * name there does not degrade the plugin — it stops the whole web UI booting ("Failed to
 * load plugins"). This file therefore declares nothing and reads the Slot registry
 * defensively with `ctx.get('slots')`. See packages/plugin-cost for the day that exact
 * mistake was made and cost the owner his interface.
 *
 * The client loader has no module body of its own: a bundle is a plain script that
 * registers a factory with `window.__ModuleLoader__.load`, and the factory must populate
 * `module.exports`. It is NOT an ES module.
 */
window.__ModuleLoader__.load({
  id: 'dsh-plugin-windows',
  factory: (require) => {
    const module = { exports: {} };
    const exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

    const React = require('react');

    const PROTOCOL = 'dsh-new://open';
    const SESSION_KEY = 'dsh.sessions.current';

    /**
     * Start a new conversation in THIS window.
     *
     * Forgetting the remembered session and reloading is the app's own blank-window state:
     * the loader finds no stored sessionId, so the session manager boots with none and the
     * composer opens fresh. `windows.log`-style bookkeeping is unnecessary — the previous
     * session lives on in the host's session list either way.
     */
    function newSessionHere() {
      try {
        window.localStorage.removeItem(SESSION_KEY);
      } catch (error) {
        // Private mode or a storage policy can refuse; the reload below still gets a blank
        // window whenever nothing was stored in the first place.
        if (window.console) window.console.warn('dsh-plugin-windows: ' + error);
      }
      const target = window.location.pathname + '?new=' + Date.now().toString(36);
      window.location.replace(target);
    }

    /** Open a new window for a new conversation (the launcher does the real work). */
    function newSessionInNewWindow() {
      try {
        window.location.href = PROTOCOL;
      } catch (error) {
        if (window.console) window.console.warn('dsh-plugin-windows: ' + error);
      }
    }

    const BUTTON_STYLE = {
      font: 'var(--dsw-font-xs-strong-13)',
      color: 'var(--dsw-alias-label-primary)',
      background: 'transparent',
      border: '1px solid var(--dsw-alias-border-l2, rgba(128,128,128,0.35))',
      borderRadius: '6px',
      padding: '0 8px',
      cursor: 'pointer',
      lineHeight: '20px',
    };

    function Control(props) {
      const isNewWindow = props && props.kind === 'window';
      const title = isNewWindow
        ? 'New session in a new window'
        : 'New session in this window';
      return React.createElement(
        'button',
        {
          type: 'button',
          title: title,
          'aria-label': title,
          style: Object.assign({}, BUTTON_STYLE, isNewWindow ? { marginLeft: '4px' } : { marginRight: '0px' }),
          onClick: isNewWindow ? newSessionInNewWindow : newSessionHere,
        },
        isNewWindow ? '\u29C9' : '+',
      );
    }

    /**
     * Register the two controls.
     *
     * Reach the registry the way the SHIPPED client plugins do — `ctx.slots` with
     * `inject: ['slots']` — not `ctx.get('slots')`. That mistake shipped once already: the
     * plugin asked for a service by name, got `undefined`, and returned quietly, so the entry
     * was active, in the roster, and contributed nothing. The owner's report was exactly
     * "I only see a new session button".
     *
     * Both the input row and the composer dock are registered on purpose: whichever of them
     * this build actually renders, the owner gets both controls.
     */
    function apply(ctx) {
      const slots = ctx.slots;
      if (slots === undefined) return;
      // ONE place, and it is the composer's LEFT seat - the same seat as the access-mode
      // control and the plan chip, which is "the far left, beside the New session button"
      // the owner asked for. Registering in two places put a second pair next to the model
      // picker and a third under the input, which is what he saw and rejected.
      // conversation.input.left renders for every session, so ordering is the only thing
      // that decides position: attachments/access come first, these sit just after them.
      const controls = [
        { id: 'new-session-here', order: 40, kind: 'here', label: 'New session' },
        { id: 'new-session-window', order: 50, kind: 'window', label: 'New session in a new window' },
      ];
      slots.inject('conversation.input.left', () => {
        for (const c of controls) {
          slots.register(
            { name: 'conversation.input.left', id: c.id, order: c.order, label: c.label },
            () => React.createElement(Control, { kind: c.kind }),
          );
        }
      });
    }

    exports.apply = apply;
    exports.inject = ['slots'];
    return module.exports;
  },
});
