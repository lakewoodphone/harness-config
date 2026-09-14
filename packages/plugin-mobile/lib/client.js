/**
 * dsh-plugin-mobile — the browser half.
 *
 * TWO BEHAVIOURS, both for a phone-width viewport:
 *
 *   1. The phone layer stylesheet is linked, so the layout does not depend on a document the
 *      client may have cached (see `ensureStylesheet`).
 *   2. An action taken in the open drawer closes it — a conversation, or a header control like
 *      "New session" — so the reader ends up looking at what they asked for.
 *
 * WHY THIS EXISTS
 * The harness composes its desktop layout at phone width. `assets/mobile.css` (injected by
 * the gate) turns the open sidebar into an overlay, which is the right shape on a phone —
 * but it stays open afterwards. Measured 2026-09-11 at 393x852: tap a session in the drawer,
 * the conversation loads behind it, and the drawer keeps covering the screen the reader
 * wanted. That is state, not style, so it cannot be fixed in a stylesheet.
 *
 * HOW IT KNOWS, WITHOUT REACHING INTO THE APP
 * It reads the two things the UI already says about itself:
 *
 *   - the sidebar toggle is a `button` whose accessible name is "Open sidebar" when the
 *     drawer is closed and "Collapse sidebar" when it is open, so the drawer's own state is
 *     readable from the DOM;
 *   - the drawer's surface is the sidebar column, so "an action taken in the drawer" is a
 *     click inside that column that is not one of the three exclusions below.
 *
 * A click inside that region, on a narrow viewport, while the drawer is open, closes the
 * drawer shortly afterwards — short enough to feel immediate, long enough that the app has
 * applied its own selection first. Nothing is intercepted, nothing is prevented, and the
 * click still reaches the app: this only reacts to it.
 *
 * DELIBERATE EXCLUSIONS. Anything that is not a selection leaves the drawer alone: text
 * fields (searching is not navigating), disclosures with `aria-expanded` (expanding a
 * workspace group), and the toggle itself. A tap outside the drawer also closes it, which
 * is the gesture a phone user expects from an overlay.
 *
 * WIDTH IS A RUNTIME CONDITION, NOT AN INSTALL-TIME ONE. The same browser window is a phone
 * and a desktop at different moments — a rotated device, a resized window — so the check
 * runs per click against `matchMedia('(max-width: 768px)')`, the same breakpoint the
 * stylesheet uses. Nothing happens above it, so a desktop session is untouched.
 *
 * The client loader has no module body of its own: a bundle is a plain script that
 * registers a factory with `window.__ModuleLoader__.load`, and the factory must populate
 * `module.exports`. It is NOT an ES module.
 */
window.__ModuleLoader__.load({
  id: 'dsh-plugin-mobile',
  factory: (require) => {
    const module = { exports: {} };
    const exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

    const NARROW = '(max-width: 768px)';
    const SIDEBAR = '[class*="sidebarCol"]';
    /** The app applies a selection, then re-renders; 150ms is below noticing, above a frame. */
    const SETTLE_MS = 150;
    const STYLESHEET = '/dsh-phone-mobile.css';
    const STYLESHEET_ID = 'dsh-phone-mobile-link';

    /**
     * Make sure the phone layer is in THIS document, whatever this document was.
     *
     * The gate also injects the layer as a `<style>` while it serves the document, and that
     * is the fast path. This is the path that cannot be lost:
     *
     *   - a document served from the browser's own cache carries whatever it had at the
     *     time, and the layer is delivered by REWRITING documents, so a reused document is a
     *     shell with no layer. Measured 2026-09-14: a warm browser in this session rendered
     *     the app with the layer absent (`body` scrollable, sidebar a 56px column at 393px)
     *     while a cold one rendered it correctly in the same minute — and a fetch of `/` from
     *     that warm client returned the engine's un-injected 28,141-byte document.
     *   - an app that rewrites its own `<head>` can drop a node it does not know about; a
     *     link this plugin owns can be put back, and the observer below does exactly that.
     *
     * Linked at every width on purpose: the stylesheet scopes itself with media queries, so
     * there is no viewport for which loading it is wrong, and no resize logic to get wrong.
     * The gate answers it without auth and with `no-store`, so a stale layer is impossible.
     */
    function ensureStylesheet() {
      try {
        const head = document.head;
        if (head === null || head === undefined) return;
        if (document.getElementById(STYLESHEET_ID) !== null) return;
        const link = document.createElement('link');
        link.id = STYLESHEET_ID;
        link.rel = 'stylesheet';
        link.href = STYLESHEET;
        link.setAttribute('data-layer', 'phone-gate');
        head.appendChild(link);
      } catch (error) {
        if (window.console) window.console.warn('dsh-plugin-mobile: ' + error);
      }
    }

    function isNarrow() {
      try {
        return window.matchMedia(NARROW).matches;
      } catch (error) {
        return false;
      }
    }

    function sidebarElement() {
      return document.querySelector(SIDEBAR);
    }

    function toggleButton() {
      try {
        return document.querySelector('button[aria-label*="sidebar" i]');
      } catch (error) {
        // An engine without :has/@-insensitive support falls back to the plain scan.
        const buttons = document.querySelectorAll('button[aria-label]');
        for (const button of buttons) {
          if (/sidebar/i.test(button.getAttribute('aria-label') || '')) return button;
        }
        return null;
      }
    }

    /** The drawer is open when its toggle offers to collapse it. */
    function drawerIsOpen() {
      const button = toggleButton();
      if (button === null) return false;
      const label = button.getAttribute('aria-label') || '';
      return /collapse/i.test(label);
    }

    function closeDrawer() {
      const button = toggleButton();
      if (button !== null && drawerIsOpen()) button.click();
    }

    function isTextEntry(element) {
      if (element.closest('input, textarea, select, [contenteditable="true"]') !== null) return true;
      // Searching is not navigating, so the search field and its controls keep the drawer.
      return element.closest('[class*="search" i]') !== null;
    }

    function isDisclosure(element) {
      // Workspace groups expand in place; that is not a selection either.
      return element.closest('[aria-expanded]') !== null;
    }

    function onClick(event) {
      try {
        if (!isNarrow() || !drawerIsOpen()) return;
        const target = event.target;
        if (!(target instanceof Element)) return;

        const sidebar = sidebarElement();
        if (sidebar !== null && !sidebar.contains(target)) {
          // A tap on the scrim beside an open drawer: the gesture a phone user expects.
          window.setTimeout(() => closeDrawer(), 0);
          return;
        }
        if (sidebar === null) return;
        // The toggle IS the app's own control for this; acting on it would fight it.
        if (target.closest('button[aria-label*="sidebar" i]') !== null) return;
        if (isTextEntry(target) || isDisclosure(target)) return;

        // Anything else inside the drawer is an action the reader took, and each one should
        // leave them looking at what they asked for rather than at the drawer.
        //
        // The first version required the click to be inside the conversation LIST, and that was
        // wrong in a way only a phone shows. Measured at 393x852 on 2026-09-14: the drawer's
        // "New session" control lives in the drawer's logo row (`hHd-Xa_logoRow`), NOT inside
        // `bhn1Oq_listArea`, so tapping it started a brand-new session BEHIND an open drawer and
        // the reader had to tap the toggle again before they could reach the composer. The rule
        // is now the drawer's whole surface minus what genuinely must not dismiss it: text fields
        // (searching is not navigating), disclosures carrying `aria-expanded` (expanding a
        // workspace group), and the toggle itself.
        window.setTimeout(() => closeDrawer(), SETTLE_MS);
      } catch (error) {
        if (window.console) window.console.warn('dsh-plugin-mobile: ' + error);
      }
    }

    function onKeydown(event) {
      try {
        if (event.key !== 'Escape' || !isNarrow() || !drawerIsOpen()) return;
        window.setTimeout(() => closeDrawer(), 0);
      } catch (error) {
        if (window.console) window.console.warn('dsh-plugin-mobile: ' + error);
      }
    }

    function apply(ctx) {
      let observer = null;
      const detach = () => {
        document.removeEventListener('click', onClick, true);
        document.removeEventListener('keydown', onKeydown, true);
        if (observer !== null) observer.disconnect();
      };
      // The layer first: it is what makes the rest of this file's behaviour visible at all.
      ensureStylesheet();
      // Re-asserted if the app rewrites <head>. Appending fires this observer once more, finds
      // the link present, and does nothing, so it converges rather than looping.
      try {
        if (typeof MutationObserver === 'function' && document.head) {
          observer = new MutationObserver(() => ensureStylesheet());
          observer.observe(document.head, { childList: true });
        }
      } catch (error) {
        if (window.console) window.console.warn('dsh-plugin-mobile: ' + error);
      }
      // Capture phase so a handler that stops propagation cannot hide the click from us.
      document.addEventListener('click', onClick, true);
      document.addEventListener('keydown', onKeydown, true);
      // The plugin is unwound with its session; a listener that outlives it would be a leak.
      if (ctx !== undefined && ctx !== null && typeof ctx.effect === 'function') {
        ctx.effect(() => detach);
      }
    }

    exports.apply = apply;
    return module.exports;
  },
});
