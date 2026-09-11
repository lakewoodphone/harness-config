/**
 * dsh-plugin-mobile — the browser half.
 *
 * ONE BEHAVIOUR: on a narrow viewport, picking a conversation closes the sidebar.
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
 *   - conversations live inside the sidebar's list region.
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
    const LIST = '[class*="listArea"]';
    /** The app applies a selection, then re-renders; 150ms is below noticing, above a frame. */
    const SETTLE_MS = 150;

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
        if (isTextEntry(target) || isDisclosure(target)) return;
        if (target.closest(LIST) === null) return;

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
      const detach = () => {
        document.removeEventListener('click', onClick, true);
        document.removeEventListener('keydown', onKeydown, true);
      };
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
