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
 * yoga"), and the answer was that the delivery path was chosen for one surface and never
 * generalised. A component that works only on the surface its author tested is the same defect
 * as the one where `/attention` reached the phone host and not the desktop.
 *
 * WHAT IT DOES, AND WHY IT IS THIS SMALL
 * It loads the badge that already exists, from the one host that already serves it, into
 * whatever document it is mounted in:
 *
 *   https://secratary.tail93e6e6.ts.net/dsh-attention.js   the badge (same file the phone gets)
 *
 * One script tag. The badge then fetches its own data from the same origin
 * (`/dsh-attention.json`), which is the authority's live reading of the kernel's findings.
 *
 * WHY NOT BUNDLE A COPY. A second copy of the badge would drift from `assets/phone-badge.js`
 * the first time either side changed, and drift here is invisible: the phone and the desktop
 * would disagree about what the company is reporting with no error anywhere. Loading the one
 * file means one implementation and one truth. The cost is that a machine with no route to the
 * authority shows nothing, which is the honest outcome - it genuinely cannot know the findings,
 * and `phone-badge.js` renders that as "findings unavailable" rather than a green zero.
 *
 * WHY NO SLOT. The badge is a fixed-position overlay on the whole frame, deliberately: it must
 * be visible from any page, not only where a conversation is open. `plugin-mobile` in this same
 * checkout establishes that a static client half may touch the document directly, so this needs
 * no Slot query, no host RPC and no dynamic Cordis runner - the three things that blocked the
 * first attempt.
 *
 * THE CLIENT LOADER'S SHAPE. A bundle is a plain script that registers a factory with
 * `window.__ModuleLoader__.load` and populates `module.exports`. It is NOT an ES module: an ESM
 * here is loaded and silently contributes nothing.
 */

const BADGE_LOADER_ID = 'dsh-attention-badge-loader';
const BADGE_AUTHORITY = 'https://secratary.tail93e6e6.ts.net';
const BADGE_SRC = BADGE_AUTHORITY + '/dsh-attention.js';

window.__ModuleLoader__.load({
  id: 'dsh-plugin-attention-badge',
  factory: () => {
    const module = { exports: {} };
    const exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

    /**
     * Add the badge script once. Returns the element so the caller can remove it.
     *
     * The guard is on the id, not a local flag: the phone gate injects a script with this same
     * id, so on the phone path this becomes a no-op instead of a second badge.
     */
    function loadBadge() {
      if (document.getElementById(BADGE_LOADER_ID) !== null) return null;
      const script = document.createElement('script');
      script.id = BADGE_LOADER_ID;
      script.src = BADGE_SRC;
      script.async = true;
      script.setAttribute('data-layer', 'attention-badge-plugin');
      (document.head || document.documentElement).appendChild(script);
      return script;
    }

    function apply(ctx) {
      const script = loadBadge();
      // The badge owns its own DOM and style and cleans up after itself when it loads again;
      // dropping the script element on unload is all this half has to undo.
      if (ctx !== undefined && ctx !== null && typeof ctx.effect === 'function') {
        ctx.effect(() => () => {
          if (script !== null && script.parentNode !== null) script.parentNode.removeChild(script);
        });
      }
    }

    exports.apply = apply;
    return module.exports;
  },
});
