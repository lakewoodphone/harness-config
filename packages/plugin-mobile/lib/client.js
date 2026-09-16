/**
 * dsh-plugin-mobile — the browser half.
 *
 * THREE BEHAVIOURS, all for a phone-width viewport:
 *
 *   1. The phone layer stylesheet is linked, so the layout does not depend on a document the
 *      client may have cached (see `ensureStylesheet`).
 *   2. An action taken in the open drawer closes it — a conversation, or a header control like
 *      "New session" — so the reader ends up looking at what they asked for.
 *   3. An agent's question card is pinned to the band the reader can actually see, because the
 *      sheet's own stylesheet can only reach the layout viewport and on iOS the question sat
 *      above the visible area (see the block above `questionFrame`).
 *
 * WHY THIS EXISTS
 * The harness composes its desktop layout at phone width. `assets/mobile.css` (injected by
 * the gate) turns the open sidebar into an overlay, which is the right shape on a phone —
 * but it stays open afterwards. Measured 2026-09-11 at 393x852: tap a session in the drawer,
 * the conversation loads behind it, and the drawer keeps covering the screen the reader
 * wanted. That is state, not style, so it cannot be fixed in a stylesheet — and neither can
 * behaviour 3, which needs a measurement (`visualViewport`) that CSS cannot read.
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

    /**
     * Keep the phone layer current IN A TAB THAT IS ALREADY OPEN.
     *
     * A phone tab lives for days. The layer reaches the browser by REWRITING the document the
     * gate serves, and this file only runs when a document loads — so a tab opened before a
     * layout fix keeps the old layout until the reader reloads, and nothing tells them to.
     *
     * Measured 2026-09-16, and it is the whole of the owner's second report. The question-card
     * sheet had been repaired and verified on a cold load (`scripts/question-card-live-probe.py`,
     * band 240-660 on a 393x852 screen: the question title sits at y=279, inside the band, with
     * Submit at y=608). He still could not read a question from his phone — "I can see the ask a
     * question and the options but I can't see the actual question". The repair had shipped after
     * his tab was opened, and the tab had no way to find out a fix existed.
     *
     * So the layer is COMPARED, not assumed. A version token travels inside the layer
     * (`phone-layer-version` in `assets/mobile.css`); every minute, and each time the tab returns
     * to the foreground, the served layer is fetched (`no-store`) and its token compared with the
     * token this document is actually using:
     *
     *   - different → the newer bytes are put in place immediately, so a layout fix lands without
     *     a reload and without losing the reader's place;
     *   - and the document is reloaded as well whenever it is SAFE, because only a reload can
     *     bring a new version of THIS file.
     *
     * A reload is never allowed to interrupt an answer: while a question card is mounted, or while
     * an editable element has focus or holds text, only the stylesheet is refreshed in place.
     *
     * Comparing a token rather than the bytes is deliberate: a byte comparison that is wrong by a
     * newline would reload the phone every minute, and a token that is missing simply does
     * nothing. Bump `phone-layer-version` in `assets/mobile.css` whenever the layer changes.
     */
    const LAYER_POLL_MS = 60000;
    const LAYER_VERSION = /phone-layer-version:\s*([^\s*]+)/;

    function layerVersion(text) {
      if (typeof text !== 'string') return null;
      const found = text.match(LAYER_VERSION);
      return found === null ? null : found[1];
    }

    /** The token of the layer this document is actually rendering with. */
    function appliedLayerVersion() {
      const injected = document.getElementById('dsh-phone-mobile');
      if (injected !== null && injected !== undefined) return layerVersion(injected.textContent || '');
      // No injected copy: the layer came from the linked stylesheet, which `ensureStylesheet`
      // has just fetched with `no-store`, so this document is current by construction.
      return null;
    }

    /**
     * True when refreshing the layer cannot cost the reader anything they were doing: no
     * question waiting for an answer, nothing focused, nothing typed into a composer.
     */
    function layerSwapIsSafe() {
      try {
        if (questionFrame() !== null) return false;
        const active = document.activeElement;
        if (active !== null && active !== undefined) {
          const tag = String(active.tagName || '').toUpperCase();
          if (tag === 'INPUT' || tag === 'TEXTAREA' || active.isContentEditable === true) return false;
        }
        if (typeof document.querySelectorAll === 'function') {
          for (const field of document.querySelectorAll('textarea, input[type="text"]')) {
            if (typeof field.value === 'string' && field.value.trim() !== '') return false;
          }
        }
      } catch (error) {
        return false;
      }
      return true;
    }

    function refreshLayerInPlace(text) {
      const injected = document.getElementById('dsh-phone-mobile');
      if (injected !== null && injected !== undefined) {
        injected.textContent = text;
        return;
      }
      const link = document.getElementById(STYLESHEET_ID);
      if (link !== null && link !== undefined) {
        link.href = STYLESHEET + '?v=' + String(Date.now());
      }
    }

    function keepLayerCurrent() {
      let reloadedFor = null;
      const run = () => {
        try {
          if (typeof window.fetch !== 'function') return;
          window.fetch(STYLESHEET, { cache: 'no-store' })
            .then((response) => (response !== undefined && response !== null && response.ok === true
              ? response.text() : null))
            .then((text) => {
              const served = layerVersion(text);
              const applied = appliedLayerVersion();
              if (served === null || applied === null || served === applied) return;
              refreshLayerInPlace(text);
              if (window.console) {
                window.console.info('dsh-plugin-mobile: phone layer ' + applied + ' -> ' + served);
              }
              if (reloadedFor === served || !layerSwapIsSafe()) return;
              reloadedFor = served;
              window.location.reload();
            })
            .catch(() => {});
        } catch (error) {
          if (window.console) window.console.warn('dsh-plugin-mobile: ' + error);
        }
      };
      run();
      return run;
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

    // ----------------------------------------------------------------------
    // 3. Question card: make the question reachable
    //
    // WHY THIS EXISTS, AND WHY IT IS NOT IN THE STYLESHEET
    // `assets/question-card.css` presents an agent's question as a sheet over the
    // conversation. It anchors the sheet to `top: 0` with `height: 100dvh`, which is the
    // LAYOUT viewport. On a phone the reader's visible area is the VISUAL viewport, and it is
    // not the same box: with the keyboard up (and, differently, with Safari's bars showing)
    // the visual viewport is shorter AND offset. A sheet pinned to the layout viewport's top
    // then begins above the first pixel the reader can see, and the question — the first
    // thing in the card — is the part that goes off-screen, while the options sit in the
    // visible middle. Nothing scrolls it back, because the page behind the sheet has nothing
    // to scroll. Measured as the owner described it on 2026-09-14 23:2x UTC: "I can't scroll
    // up enough to see the actual question. I just see the options for responses."
    //
    // No stylesheet can read `visualViewport`; only script can. So the layout is asserted
    // here, in pixels, against the band the reader can actually see: if the sheet or its
    // title is outside that band, the frame is pinned to it with inline `!important` styles
    // (which beat every stylesheet), and the repair is removed again once it fits. The
    // measurement is left at `window.__dshPhoneCard` so a probe can read what the phone
    // really did instead of guessing.
    //
    // It is deliberately narrow: phones only (the same 768px breakpoint as the stylesheet),
    // no pinch-zoomed pages, and it never touches a card that already fits.
    // ----------------------------------------------------------------------
    const CARD_SELECTOR = '[class*="_frame"]:has(> [class*="_card"])';
    const CARD_REPAIR_Z = '2147483600';

    /** The frame that wraps an agent's question card, or null. */
    function questionFrame() {
      try {
        const direct = document.querySelector(CARD_SELECTOR);
        if (direct !== null) return direct;
      } catch (error) {
        // No `:has` support: fall back to reading each frame's first child.
      }
      const frames = document.querySelectorAll('[class*="_frame"]');
      for (const frame of frames) {
        const child = frame.firstElementChild;
        if (child !== null && typeof child.className === 'string' &&
            child.className.indexOf('_card') >= 0) {
          return frame;
        }
      }
      return null;
    }

    /**
     * The band the reader can see, in layout-viewport coordinates, or null when the
     * measurement would be meaningless (no `visualViewport`, or a pinch-zoomed page).
     */
    function visibleBand() {
      const vv = window.visualViewport;
      if (vv === null || vv === undefined) {
        return { top: 0, height: window.innerHeight };
      }
      const scale = typeof vv.scale === 'number' && vv.scale > 0 ? vv.scale : 1;
      // A zoomed page scales the visual viewport instead of offsetting it, and pinning a
      // sheet to it would fight the reader's own zoom. Leave it to the stylesheet.
      if (scale > 1.01) return null;
      return { top: vv.offsetTop, height: vv.height };
    }

    function clearCardRepair(frame, card) {
      try {
        for (const name of ['position', 'top', 'left', 'right', 'bottom', 'height',
                            'max-height', 'overflow', 'z-index']) {
          frame.style.removeProperty(name);
        }
        if (card !== null) {
          card.style.removeProperty('height');
          card.style.removeProperty('max-height');
        }
      } catch (error) {
        if (window.console) window.console.warn('dsh-plugin-mobile: ' + error);
      }
    }

    function repairQuestionCard(frame) {
      try {
        const band = visibleBand();
        if (band === null) return;
        const card = frame.firstElementChild;
        const title = frame.querySelector('[class*="_title"]');
        const box = frame.getBoundingClientRect();
        const titleBox = title === null ? null : title.getBoundingClientRect();
        const bottom = band.top + band.height;
        const boxFits = box.top >= band.top - 1 && box.bottom <= bottom + 1;
        const titleFits = titleBox === null || (titleBox.top >= band.top - 1 && titleBox.bottom <= bottom + 1);
        // Reported under one name so a probe (or a future session) can read the phone's own
        // numbers rather than infer them from a screenshot.
        window.__dshPhoneCard = {
          at: new Date().toISOString(),
          viewport: { innerHeight: window.innerHeight, bandTop: Math.round(band.top),
                      bandHeight: Math.round(band.height) },
          box: { top: Math.round(box.top), height: Math.round(box.height) },
          title: titleBox === null ? null : { top: Math.round(titleBox.top), bottom: Math.round(titleBox.bottom) },
          fits: boxFits && titleFits,
          repaired: false,
        };
        if (boxFits && titleFits) {
          clearCardRepair(frame, card);
          return;
        }
        frame.style.setProperty('position', 'fixed', 'important');
        frame.style.setProperty('top', Math.round(band.top) + 'px', 'important');
        frame.style.setProperty('left', '0', 'important');
        frame.style.setProperty('right', '0', 'important');
        frame.style.setProperty('bottom', 'auto', 'important');
        frame.style.setProperty('height', Math.round(band.height) + 'px', 'important');
        frame.style.setProperty('max-height', Math.round(band.height) + 'px', 'important');
        frame.style.setProperty('overflow', 'hidden', 'important');
        frame.style.setProperty('z-index', CARD_REPAIR_Z, 'important');
        if (card !== null) {
          card.style.setProperty('height', '100%', 'important');
          card.style.setProperty('max-height', 'none', 'important');
        }
        window.__dshPhoneCard.repaired = true;
      } catch (error) {
        if (window.console) window.console.warn('dsh-plugin-mobile: ' + error);
      }
    }

    function apply(ctx) {
      let observer = null;
      let bodyObserver = null;
      let cardFrame = null;
      let queued = false;
      let layerTimer = null;

      const settleCard = () => {
        queued = false;
        if (!isNarrow()) return;
        if (cardFrame !== null && !cardFrame.isConnected) cardFrame = null;
        if (cardFrame === null) return;
        const child = cardFrame.firstElementChild;
        if (child === null || typeof child.className !== 'string' || child.className.indexOf('_card') < 0) {
          // The frame outlived its card; take our repair off it and stop watching this node.
          clearCardRepair(cardFrame, null);
          cardFrame = null;
          return;
        }
        repairQuestionCard(cardFrame);
      };

      const schedule = () => {
        if (queued) return;
        queued = true;
        // Coalesced to one pass per frame: the app mutates the DOM continuously while it
        // streams, and this must not add work per token.
        window.requestAnimationFrame(settleCard);
      };

      /** True when a mutation could have mounted or moved a question card. */
      const touchedCard = (records) => {
        for (const record of records) {
          const added = record.addedNodes;
          for (let i = 0; i < added.length; i += 1) {
            const node = added[i];
            if (node.nodeType !== 1 || typeof node.className !== 'string') continue;
            if (node.className.indexOf('_frame') >= 0) { cardFrame = node; return true; }
            const inside = node.closest && node.closest('[class*="_frame"]');
            if (inside !== undefined && inside !== null) { cardFrame = inside; return true; }
            const nested = node.querySelector && node.querySelector('[class*="_frame"]');
            if (nested !== undefined && nested !== null) { cardFrame = nested; return true; }
          }
          if (record.removedNodes.length > 0 && cardFrame !== null) return true;
        }
        return false;
      };

      const detach = () => {
        document.removeEventListener('click', onClick, true);
        document.removeEventListener('keydown', onKeydown, true);
        if (observer !== null) observer.disconnect();
        if (bodyObserver !== null) bodyObserver.disconnect();
        if (window.visualViewport) {
          window.visualViewport.removeEventListener('resize', schedule);
          window.visualViewport.removeEventListener('scroll', schedule);
        }
        window.removeEventListener('resize', schedule);
        window.removeEventListener('orientationchange', schedule);
        document.removeEventListener('visibilitychange', checkLayer);
        if (layerTimer !== null) window.clearInterval(layerTimer);
      };
      // The layer first: it is what makes the rest of this file's behaviour visible at all.
      ensureStylesheet();
      // ...and then kept current, so a tab opened before a fix does not keep the old layout.
      // `keepLayerCurrent()` performs its first check itself; the interval and the visibility
      // listener are what make it survive a tab that stays open for days.
      const checkLayer = keepLayerCurrent();
      if (typeof window.setInterval === 'function') {
        layerTimer = window.setInterval(checkLayer, LAYER_POLL_MS);
      }
      document.addEventListener('visibilitychange', checkLayer);
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

      try {
        if (typeof MutationObserver === 'function' && document.body) {
          bodyObserver = new MutationObserver((records) => {
            if (touchedCard(records)) schedule();
          });
          bodyObserver.observe(document.body, { childList: true, subtree: true });
        }
        // The keyboard opening, and Safari's bars collapsing, move the visible band WITHOUT
        // mutating the DOM — so the observers above cannot see the event that actually hid
        // the question. This is the listener that can.
        if (window.visualViewport) {
          window.visualViewport.addEventListener('resize', schedule);
          window.visualViewport.addEventListener('scroll', schedule);
        }
        window.addEventListener('resize', schedule);
        window.addEventListener('orientationchange', schedule);
        // A card may already be mounted when the plugin loads (a reload mid-question).
        cardFrame = questionFrame();
        if (cardFrame !== null) schedule();
      } catch (error) {
        if (window.console) window.console.warn('dsh-plugin-mobile: ' + error);
      }

      // The plugin is unwound with its session; a listener that outlives it would be a leak.
      if (ctx !== undefined && ctx !== null && typeof ctx.effect === 'function') {
        ctx.effect(() => detach);
      }
    }

    exports.apply = apply;
    return module.exports;
  },
});
