/**
 * dsh-plugin-windows — the browser half.
 *
 * WHAT IT DOES
 * Puts a `+` control beside the composer. Clicking it asks Windows to open a NEW DSH
 * window for a new conversation on this machine. The browser cannot start a process, so
 * the click navigates to a URL protocol the launcher registered:
 *
 *     dsh-new://open      ->   pwsh dshw.ps1 new
 *
 * `dshw new` starts a fresh browser profile + window against the running engine, which
 * is exactly "another conversation". Registering the protocol is a one-line Windows
 * command, documented in multi-window/README.md:
 *
 *     New-Item 'HKCU:\Software\Classes\dsh-new\shell\open\command' -Force |
 *       Set-ItemProperty -Name '(default)' -Value '"C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile -WindowStyle Hidden -File "C:\Users\ezabz\code\harness-config\multi-window\dshw.ps1" new'
 *
 * WHY IT OWNS NO DEPENDENCIES
 * The browser loader treats every name in a Plugin's `inject` and in the package's
 * `dsh.client.inject` as a SERVICE it must resolve before the entry may activate. A
 * wrong name there does not degrade the plugin — it stops the whole web UI from booting
 * ("Failed to load plugins"). This file therefore declares nothing and reads the Slot
 * registry defensively with `ctx.get('slots')`. See packages/plugin-cost for the day
 * that exact mistake was made and cost the owner his interface.
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

    /** True when the host registered the protocol (a click would otherwise do nothing). */
    function askForWindow() {
      try {
        window.location.href = PROTOCOL;
      } catch (error) {
        // A missing protocol registration throws here on some builds; nothing to do
        // from the page, and swallowing it keeps the composer usable.
        if (window.console) window.console.warn('dsh-plugin-windows: ' + error);
      }
    }

    /**
     * The + control.
     *
     * It is deliberately a plain button with inline styles from the shipped theme tokens
     * so it needs no CSS insertion and no theme override.
     */
    function NewWindowButton(props) {
      const title = 'Open a new DSH window (new conversation)';
      const style = {
        font: 'var(--dsw-font-xs-strong-13)',
        color: 'var(--dsw-alias-label-primary)',
        background: 'transparent',
        border: '1px solid var(--dsw-alias-border-l2, rgba(128,128,128,0.35))',
        borderRadius: '6px',
        padding: '0 8px',
        cursor: 'pointer',
        lineHeight: '20px',
        marginRight: '4px',
      };
      return React.createElement(
        'button',
        { type: 'button', title: title, 'aria-label': title, style: style, onClick: askForWindow },
        '+',
      );
    }

    function apply(ctx) {
      const slots = ctx.get('slots');
      if (slots === undefined) return;
      slots.inject('conversation.composer.dock', () =>
        slots.register(
          { name: 'conversation.composer.dock', id: 'new-window', order: 5, label: 'New window' },
          NewWindowButton,
        ),
      );
    }

    exports.apply = apply;
    return module.exports;
  },
});
