/**
 * dsh-plugin-attention-badge - the attention badge on every machine, not just the phone.
 *
 * WHY THIS EXISTS
 * The first version of the badge was delivered by the phone gate, which rewrites the document
 * before the phone's browser sees it. That works, and only there: every other machine runs its
 * own DSH engine and talks to it over loopback, so nothing rewrites its document and nothing
 * injects the badge. Measured on ZABZ-YOGA 2026-09-14: a local engine on 127.0.0.1:3099, the
 * profile holding dsh-base, dsh-web-app, plugin-cost, plugin-windows and plugin-mobile - and no
 * badge. The owner asked the obvious question ("why just my iphone and not the desktop and
 * yoga"), and the answer was that the delivery path had been chosen for one surface and never
 * generalised.
 *
 * WHAT IT DOES
 * It loads the badge that already exists, from the one host that already serves it:
 *
 *   https://secratary.tail93e6e6.ts.net/dsh-attention.js   (the same file the phone gets)
 *
 * The badge then fetches its findings from the same origin, which is the authority's live reading
 * of the kernel's state file.
 *
 * ...AND WHY IT NO LONGER VANISHES SILENTLY WHEN THAT HOST IS UNREACHABLE
 * Measured 2026-09-14, by the owner: "I think I saw the badge earlier today but I don't see it
 * now." The cause was Tailscale being stuck on his laptop after a reboot, so the badge script -
 * which is fetched FROM the authority - could not load, and the pill simply disappeared. Nothing
 * said why. That is the exact failure this whole subsystem exists to prevent: silence looking
 * like health. The design had a circular dependency: **the code that reports "cannot reach the
 * authority" was itself fetched from the authority**, so the one state it could never render was
 * the one it most needed to.
 *
 * So this half carries a second, tiny, LOCAL reporter. If the real badge has not appeared within
 * `MOUNT_GRACE_MS`, this renders a refusal pill from code that shipped with the plugin (served by
 * the local engine, needing no network), says which host it cannot reach, and keeps retrying. When
 * the authority comes back the real badge loads and the fallback removes itself.
 *
 * WHY NOT BUNDLE THE WHOLE BADGE. A second copy would drift from `assets/phone-badge.js` the first
 * time either side changed, and the drift would be invisible: the phone and the desktop would
 * disagree about what the company is reporting with no error anywhere. The fallback is deliberately
 * NOT a copy of the badge - it renders no findings at all, only the fact that it cannot get them,
 * so there is nothing in it to drift. One implementation, one truth, and a local voice for the one
 * thing that must be said when the truth is unavailable.
 *
 * WHY NO SLOT. The badge is a fixed-position overlay on the whole frame, deliberately: it must be
 * visible from any page, not only where a conversation is open. `plugin-mobile` in this same
 * checkout establishes that a static client half may touch the document directly, so this needs
 * no Slot query, no host RPC and no dynamic Cordis runner - the three things that blocked the
 * first attempt.
 *
 * THE CLIENT LOADER'S SHAPE. A bundle is a plain script that registers a factory with
 * `window.__ModuleLoader__.load` and populates `module.exports`. It is NOT an ES module: an ESM
 * here is loaded and silently contributes nothing.
 */

const BADGE_LOADER_ID = 'dsh-attention-badge-loader';
const FALLBACK_ID = 'dsh-attention-badge-offline';
const FALLBACK_STYLE_ID = 'dsh-attention-badge-offline-style';
const FALLBACK_VERSION = '1';

const BADGE_AUTHORITY = 'https://secratary.tail93e6e6.ts.net';
const BADGE_SRC = BADGE_AUTHORITY + '/dsh-attention.js';

/** How long the real badge gets before this says something. A cold tailnet connect can take a second. */
const MOUNT_GRACE_MS = 6000;
/** How often to try again while it is absent. Cheap: one script tag and one element check. */
const RETRY_MS = 30000;

window.__ModuleLoader__.load({
  id: 'dsh-plugin-attention-badge',
  factory: () => {
    const module = { exports: {} };
    const exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

    // Injectable so `scripts/verify-badge.js` can drive every timer path without waiting; the same
    // reason `phone-badge.js` exposes timer hooks. Without them the failure states of this file
    // would be untestable and would therefore never have been tested.
    const setT = window.__dshBadgeSetTimeout || ((fn, ms) => window.setTimeout(fn, ms));
    const clearT = window.__dshBadgeClearTimeout || ((id) => window.clearTimeout(id));
    const setI = window.__dshBadgeSetInterval || ((fn, ms) => window.setInterval(fn, ms));
    const clearI = window.__dshBadgeClearInterval || ((id) => window.clearInterval(id));

    const state = {
      lastError: '',
      fallbackShown: false,
      graceTimer: null,
      retryTimer: null,
      checksWithTag: 0,
      disposed: false,
    };

    /** Is the real badge present AND did it manage to render its own root? */
    function badgeMounted() {
      try {
        return window.__dshAttentionBadge === true
          && document.getElementById('dsh-attention-badge') !== null;
      } catch (error) {
        return false;
      }
    }

    /**
     * Add the badge script once. Returns the element, or null if one is already there.
     *
     * The guard is on the id, not a local flag: the phone gate injects a script with this same id,
     * so on the phone path this becomes a no-op instead of a second badge.
     *
     * `onerror` removes the element. A failed load leaves a dead `<script>` sitting in the document
     * forever, and the id guard would then refuse to ever try again - which is how a transient
     * tunnel outage became a permanent absence.
     */
    function injectBadge() {
      if (document.getElementById(BADGE_LOADER_ID) !== null) return null;
      const script = document.createElement('script');
      script.id = BADGE_LOADER_ID;
      script.src = BADGE_SRC;
      script.async = true;
      script.setAttribute('data-layer', 'attention-badge-plugin');
      // Names the origin the badge must ask for its findings. It must be the authority: this page is
      // a local engine on loopback, which serves no `/dsh-attention.json`, so a relative fetch would
      // fail here while working perfectly on the phone - the asymmetry this package exists to remove.
      script.setAttribute('data-attention-json', BADGE_AUTHORITY);
      script.setAttribute('data-badge-source', 'plugin');
      script.onerror = () => {
        state.lastError = 'the badge script did not load from ' + BADGE_AUTHORITY;
        try {
          if (script.parentNode !== null) script.parentNode.removeChild(script);
        } catch (error) { /* nothing useful to do; the retry will try again */ }
      };
      (document.head || document.documentElement).appendChild(script);
      state.checksWithTag = 0;
      return script;
    }

    function style() {
      if (document.getElementById(FALLBACK_STYLE_ID) !== null) return;
      const css = ''
        + '#' + FALLBACK_ID + '{position:fixed;left:16px;right:16px;bottom:14px;z-index:2147483000;'
        + 'display:flex;flex-direction:column;align-items:flex-end;pointer-events:none;'
        + 'font:13px/1.35 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;'
        + 'color:#e5e7eb;}'
        + '#' + FALLBACK_ID + ' *{box-sizing:border-box;}'
        + '#' + FALLBACK_ID + ' .pill{pointer-events:auto;display:inline-flex;align-items:center;'
        + 'gap:8px;max-width:100%;padding:8px 12px;border-radius:999px;border-style:dashed;'
        + 'border-width:1px;border-color:rgba(148,163,184,.7);background:rgba(15,23,42,.92);'
        + 'color:#f8fafc;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.35);}'
        + '#' + FALLBACK_ID + ' .dot{width:9px;height:9px;border-radius:50%;flex:none;'
        + 'background:#6b7280;}'
        + '#' + FALLBACK_ID + ' .count{font-weight:600;white-space:nowrap;}'
        + '#' + FALLBACK_ID + ' .why{display:none;margin-top:8px;width:100%;max-width:440px;'
        + 'padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.18);'
        + 'background:rgba(15,23,42,.96);font-size:12px;opacity:.9;overflow-wrap:anywhere;}'
        + '#' + FALLBACK_ID + '.open .why{display:block;}';
      const el = document.createElement('style');
      el.id = FALLBACK_STYLE_ID;
      el.setAttribute('data-layer', 'attention-badge-plugin');
      el.appendChild(document.createTextNode(css));
      (document.head || document.documentElement).appendChild(el);
    }

    function escapeHtml(value) {
      return String(value === undefined || value === null ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /** The local refusal pill. Renders no findings: it has none, and inventing a zero would be a lie. */
    function showFallback() {
      if (state.disposed || badgeMounted()) return;
      style();
      let el = document.getElementById(FALLBACK_ID);
      if (el === null) {
        el = document.createElement('div');
        el.id = FALLBACK_ID;
        el.setAttribute('data-layer', 'attention-badge-plugin');
        el.setAttribute('data-badge-version', FALLBACK_VERSION);
        el.setAttribute('role', 'status');
        el.setAttribute('aria-live', 'polite');
        (document.body || document.documentElement).appendChild(el);
      }
      el.innerHTML = ''
        + '<div class="pill" data-role="toggle">'
        + '<span class="dot"></span>'
        + '<span class="count">findings unavailable</span>'
        + '</div>'
        + '<div class="why">'
        + 'The attention badge could not be loaded from <b>' + escapeHtml(BADGE_AUTHORITY) + '</b>.'
        + ' The harness is otherwise unaffected. '
        + (state.lastError ? escapeHtml(state.lastError) + '. ' : '')
        + 'Retrying every ' + Math.round(RETRY_MS / 1000) + 's.'
        + '<br><br>Nothing about the company is shown here on purpose: this pill has no findings to '
        + 'report, and an empty list would look like good news.'
        + '</div>';
      const toggle = el.querySelector('[data-role="toggle"]');
      if (toggle !== null) {
        toggle.addEventListener('click', () => {
          el.className = el.className === 'open' ? '' : 'open';
        });
      }
      state.fallbackShown = true;
    }

    function hideFallback() {
      if (!state.fallbackShown) return;
      state.fallbackShown = false;
      for (const id of [FALLBACK_ID, FALLBACK_STYLE_ID]) {
        const el = document.getElementById(id);
        if (el !== null) {
          try {
            if (el.parentNode !== null) el.parentNode.removeChild(el);
          } catch (error) { /* already detached */ }
        }
      }
    }

    /** One pass: is the real badge here, and if not, say so and try again. */
    function check() {
      if (state.disposed) return;
      if (badgeMounted()) {
        hideFallback();
        return;
      }
      showFallback();
      // A tag is not proof of a load. A failed load leaves a dead `<script>` in the document, and
      // the id guard would then refuse to ever try again - which is how one transient tunnel outage
      // became a permanent absence. So: replace a tag that errored, and replace one that has now
      // survived a full retry cycle without producing a badge (presumed hung).
      const tag = document.getElementById(BADGE_LOADER_ID);
      if (tag !== null) {
        state.checksWithTag += 1;
        if (state.lastError || state.checksWithTag >= 2) {
          try {
            if (tag.parentNode !== null) tag.parentNode.removeChild(tag);
          } catch (error) { /* already detached */ }
          state.checksWithTag = 0;
        }
      }
      injectBadge();
    }

    function apply(ctx) {
      injectBadge();
      // The grace period exists so a healthy machine never sees the fallback flash: the real badge
      // normally mounts in well under a second.
      state.graceTimer = setT(check, MOUNT_GRACE_MS);
      state.retryTimer = setI(check, RETRY_MS);

      if (ctx !== undefined && ctx !== null && typeof ctx.effect === 'function') {
        ctx.effect(() => () => {
          state.disposed = true;
          if (state.graceTimer !== null) clearT(state.graceTimer);
          if (state.retryTimer !== null) clearI(state.retryTimer);
          state.graceTimer = null;
          state.retryTimer = null;
          hideFallback();
          const tag = document.getElementById(BADGE_LOADER_ID);
          if (tag !== null && tag.getAttribute('data-badge-source') === 'plugin') {
            try {
              if (tag.parentNode !== null) tag.parentNode.removeChild(tag);
            } catch (error) { /* already detached */ }
          }
        });
      }
    }

    // Present for the verifier; harmless in a page.
    window.__dshAttentionBadgePlugin = {
      state,
      check,
      badgeMounted,
      showFallback,
      hideFallback,
      injectBadge,
      authority: BADGE_AUTHORITY,
      graceMs: MOUNT_GRACE_MS,
      retryMs: RETRY_MS,
    };

    exports.apply = apply;
    return module.exports;
  },
});
