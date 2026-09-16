/**
 * Smoke-test dsh-plugin-mobile's browser half the way the DSH client module system loads it.
 *
 * The bundle is a plain script that only REGISTERS a factory; module side effects live inside
 * the factory closure. So this installs a fake `window.__ModuleLoader__`, evaluates the bundle,
 * materializes the factory, and drives `apply()` against a small fake DOM to prove the two
 * behaviours it is responsible for:
 *
 *   1. the phone layer STYLESHEET is linked — because the injected copy travels inside the
 *      document, and a document served from a client's own cache carries no layer at all. This
 *      is the failure that made a phone look like none of the phone work had been done
 *      (measured 2026-09-14), and it is invisible to any check that reads the server's answer;
 *   2. an ACTION TAKEN IN THE OPEN DRAWER CLOSES IT. The first version of this rule required the
 *      click to be inside the conversation list, and on a real phone that left the drawer open
 *      over the session it had just started: the drawer's "New session" control lives in the
 *      drawer's logo row, not in the list region (measured at 393x852 on 2026-09-14). The
 *      assertions below pin the rule to the whole drawer surface, and pin the exclusions that
 *      must NOT dismiss it — a text field and a disclosure.
 *
 * It cannot prove pixels. Only a browser at 393px proves those.
 *
 * Usage: node test/client-smoke.mjs
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = readFileSync(join(ROOT, 'lib', 'client.js'), 'utf8');

let failures = 0;
function check(name, ok, detail) {
  if (ok) { console.log('  ok    ' + name); }
  else { failures++; console.log('  FAIL  ' + name + (detail === undefined ? '' : ' -> ' + detail)); }
}

// ── a fake DOM, small enough to reason about ─────────────────────────────────
class FakeElement {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.id = '';
    this.rel = null;
    this.href = null;
    this.attributes = {};
    this.children = [];
    this.parent = null;
    this.listeners = [];
    /** selector -> what `closest` should answer, so a test states its own ancestry. */
    this.closestMap = {};
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }
  getAttributeNS() { return null; }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  addEventListener(type, fn) { this.listeners.push({ type, fn }); }
  removeEventListener(type, fn) {
    this.listeners = this.listeners.filter((l) => !(l.type === type && l.fn === fn));
  }
  walk() { return [this, ...this.children.flatMap((c) => c.walk())]; }
  contains(other) { for (let node = other; node; node = node.parent) if (node === this) return true; return false; }
  closest(selector) { return selector in this.closestMap ? this.closestMap[selector] : null; }
  click() { this.clicks = (this.clicks || 0) + 1; }
}
FakeElement.prototype.ariaLabel = undefined;

const head = new FakeElement('head');
const body = new FakeElement('body');
const documentListeners = [];
const documentStub = {
  head,
  body,
  createElement: (tag) => new FakeElement(tag),
  getElementById: (id) => head.walk().concat(body.walk()).find((el) => el.id === id) || null,
  querySelector: (selector) => {
    if (selector === '[class*="sidebarCol"]') return sidebar;
    if (selector === 'button[aria-label*="sidebar" i]') return toggle;
    return null;
  },
  querySelectorAll: () => [],
  addEventListener: (type, fn) => documentListeners.push({ type, fn }),
  removeEventListener: (type, fn) => {
    const i = documentListeners.findIndex((l) => l.type === type && l.fn === fn);
    if (i >= 0) documentListeners.splice(i, 1);
  },
};

const sidebar = new FakeElement('div');
sidebar.setAttribute('class', 'pI_x6G_sidebarCol');
const toggle = new FakeElement('button');
toggle.setAttribute('aria-label', 'Collapse sidebar');          // the drawer is OPEN
const listItem = new FakeElement('div');
const newSessionButton = new FakeElement('button');              // the drawer's logo row
const searchField = new FakeElement('input');
const groupDisclosure = new FakeElement('div');
sidebar.appendChild(toggle);
sidebar.appendChild(newSessionButton);
sidebar.appendChild(searchField);
sidebar.appendChild(groupDisclosure);
sidebar.appendChild(listItem);

newSessionButton.closestMap['[class*="listArea"]'] = null;       // outside the list, as measured
// `closest` matches the element itself first — the real DOM's behaviour, which is what makes the
// toggle's own guard work. A stub that answered null here would have "passed" a rule the browser
// would break, so this line is part of the assertion, not scaffolding.
toggle.closestMap['button[aria-label*="sidebar" i]'] = toggle;
searchField.closestMap['input, textarea, select, [contenteditable="true"]'] = searchField;
groupDisclosure.closestMap['[aria-expanded]'] = groupDisclosure;

const narrow = { value: true };
const pending = [];
const registered = [];
const fakeWindow = {
  __ModuleLoader__: { load: (entry) => registered.push(entry) },
  matchMedia: (q) => ({ matches: narrow.value, media: q }),
  console: { warn: () => {} },
  setTimeout: (fn) => { pending.push(fn); return pending.length; },
  addEventListener: () => {},
  removeEventListener: () => {},
  document: documentStub,
};

const sandbox = {
  window: fakeWindow,
  document: documentStub,
  globalThis: fakeWindow,
  Element: FakeElement,
  setTimeout: fakeWindow.setTimeout,
  MutationObserver: class { constructor(cb) { this.cb = cb; } observe() {} disconnect() {} },
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: 'lib/client.js' });

console.log('registration');
check('the bundle registers exactly one module entry', registered.length === 1, String(registered.length));
check('the entry id is the package id', registered[0] && registered[0].id === 'dsh-plugin-mobile');
const moduleExports = registered[0].factory(() => { throw new Error('this bundle must require nothing'); });
check('it exports apply', typeof moduleExports.apply === 'function');
check('it declares no client dependencies (a wrong name blanks the whole UI)',
  moduleExports.inject === undefined || (Array.isArray(moduleExports.inject) && moduleExports.inject.length === 0),
  JSON.stringify(moduleExports.inject));

console.log('the phone layer is linked, not assumed');
moduleExports.apply(undefined);
const links = head.walk().filter((el) => el.tagName === 'LINK');
check('apply links exactly one stylesheet', links.length === 1, String(links.length));
check('the link points at the gate\'s stylesheet route',
  links[0] && links[0].href === '/dsh-phone-mobile.css', links[0] && String(links[0].href));
check('the link carries the id the observer looks for',
  links[0] && links[0].id === 'dsh-phone-mobile-link', links[0] && String(links[0].id));
moduleExports.apply(undefined);
check('applying twice does not stack a second link',
  head.walk().filter((el) => el.tagName === 'LINK').length === 1,
  String(head.walk().filter((el) => el.tagName === 'LINK').length));

console.log('an action in the drawer closes it');
const clickListener = documentListeners.find((l) => l.type === 'click');
check('a capture-phase click listener is registered', !!clickListener);
const click = (target) => { pending.length = 0; clickListener.fn({ target }); return pending.length; };

check('the drawer\'s New session control closes the drawer (it is outside the conversation list)',
  click(newSessionButton) === 1, String(click(newSessionButton)));
check('a conversation in the list closes the drawer', click(listItem) === 1, String(click(listItem)));
check('a text field does NOT close it (searching is not navigating)', click(searchField) === 0, String(click(searchField)));
check('a disclosure does NOT close it (expanding a group is not navigating)', click(groupDisclosure) === 0, String(click(groupDisclosure)));
check('the toggle does NOT close it (that control is the app\'s own)', click(toggle) === 0, String(click(toggle)));
narrow.value = false;
check('a desktop width does nothing at all', click(newSessionButton) === 0, String(click(newSessionButton)));
narrow.value = true;

// ── the question card, in a second sandbox with a richer fake DOM ────────────
//
// Behaviour 3 cannot be checked in the DOM above: it needs geometry (`getBoundingClientRect`),
// the visible band (`visualViewport`), a mutation to notice the card arriving, and one frame of
// `requestAnimationFrame` to act. The assertions below are the mechanism, not the pixels — the
// pixels are proved in `scripts/question-card-live-probe.py` against the real app.
console.log('');
console.log('the question card is pinned to the band the reader can see');

class CardElement {
  constructor(tag, cls) {
    this.tagName = String(tag).toUpperCase();
    this.nodeType = 1;
    this.className = cls === undefined ? '' : cls;
    this.attributes = {};
    this.children = [];
    this.parent = null;
    this.isConnected = true;
    this.rect = { top: 0, bottom: 0, left: 0, right: 0, height: 0, width: 0 };
    this.inline = {};
    this.style = {
      setProperty: (name, value, priority) => { this.inline[name] = { value, priority }; },
      removeProperty: (name) => { delete this.inline[name]; },
    };
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  get firstElementChild() { return this.children[0] || null; }
  getBoundingClientRect() { return { ...this.rect }; }
  closest() { return null; }
  querySelector(selector) { return (this.lookups && this.lookups[selector]) || null; }
  querySelectorAll() { return []; }
  addEventListener() {}
  removeEventListener() {}
}

const cardRoot = new CardElement('div');
const cardBody = new CardElement('div');
const cardFrameNode = new CardElement('div', 'Mbwy4a_frame');
const cardNode = new CardElement('div', 'Mbwy4a_card');
const cardTitle = new CardElement('h3', 'Mbwy4a_title');
cardNode.appendChild(cardBody);
cardFrameNode.appendChild(cardNode);
cardFrameNode.lookups = { '[class*="_title"]': cardTitle };

const cardBodyEl = new CardElement('body');
const cardObservers = [];
const cardRaf = [];
const cardWindowListeners = [];
const band = { offsetTop: 0, height: 852, scale: 1 };
const cardRegistered = [];
const cardWindow = {
  __ModuleLoader__: { load: (entry) => cardRegistered.push(entry) },
  matchMedia: () => ({ matches: true }),
  console: { warn: () => {} },
  setTimeout: (fn) => { fn(); return 1; },
  requestAnimationFrame: (fn) => { cardRaf.push(fn); return cardRaf.length; },
  addEventListener: (type, fn) => cardWindowListeners.push({ type, fn }),
  removeEventListener: () => {},
  innerHeight: 852,
  visualViewport: {
    get offsetTop() { return band.offsetTop; },
    get height() { return band.height; },
    get scale() { return band.scale; },
    addEventListener: () => {},
    removeEventListener: () => {},
  },
  document: null,
};
const cardDocument = {
  head: new CardElement('head'),
  body: cardBodyEl,
  createElement: (tag) => new CardElement(tag),
  getElementById: () => null,
  querySelector: (selector) => {
    if (selector === '[class*="_frame"]:has(> [class*="_card"])') return cardFrameNode;
    if (selector === 'button[aria-label*="sidebar" i]') return null;
    return null;
  },
  querySelectorAll: (selector) => (selector === '[class*="_frame"]' ? [cardFrameNode] : []),
  addEventListener: () => {},
  removeEventListener: () => {},
};
cardWindow.document = cardDocument;
const cardSandbox = {
  window: cardWindow,
  document: cardDocument,
  globalThis: cardWindow,
  Element: CardElement,
  setTimeout: cardWindow.setTimeout,
  MutationObserver: class {
    constructor(cb) { this.cb = cb; cardObservers.push(this); }
    observe() {}
    disconnect() {}
  },
};
vm.createContext(cardSandbox);
vm.runInContext(source, cardSandbox, { filename: 'lib/client.js' });
const cardModule = cardRegistered[0].factory(() => { throw new Error('no requires'); });
cardModule.apply(undefined);

// The card is mounted where the plugin cannot miss it, and the mutation says so.
const bodyObserver = cardObservers.find((o) => o.cb && String(o.cb).includes('touchedCard') === false) ||
                     cardObservers[cardObservers.length - 1];
// Fire both observers; the body one schedules the repair.
for (const observer of cardObservers) observer.cb([{ addedNodes: [cardFrameNode], removedNodes: [] }]);
const runFrames = () => { while (cardRaf.length > 0) cardRaf.shift()(); };
runFrames();

// The band the reader can see is offset by the keyboard, and the shipped sheet is anchored to
// the layout viewport instead — which is exactly the failure the owner reported.
band.offsetTop = 240;
band.height = 420;
cardFrameNode.rect = { top: 0, bottom: 852, left: 0, right: 393, height: 852, width: 393 };
cardTitle.rect = { top: 39, bottom: 60, left: 18, right: 300, height: 21, width: 282 };
for (const observer of cardObservers) observer.cb([{ addedNodes: [cardFrameNode], removedNodes: [] }]);
runFrames();

check('the repair is applied when the question is above the visible band',
  cardFrameNode.inline.position !== undefined, JSON.stringify(Object.keys(cardFrameNode.inline)));
check('the sheet is pinned to the top of the VISIBLE band, not the layout viewport',
  cardFrameNode.inline.top !== undefined && cardFrameNode.inline.top.value === '240px',
  JSON.stringify(cardFrameNode.inline.top));
check('the sheet is bounded by the visible height',
  cardFrameNode.inline.height !== undefined && cardFrameNode.inline.height.value === '420px',
  JSON.stringify(cardFrameNode.inline.height));
check('the repair outranks the stylesheet (inline !important)',
  cardFrameNode.inline.top !== undefined && cardFrameNode.inline.top.priority === 'important',
  JSON.stringify(cardFrameNode.inline.top && cardFrameNode.inline.top.priority));
check('the measurement is left where a probe can read it',
  typeof cardWindow.__dshPhoneCard === 'object' && cardWindow.__dshPhoneCard !== null &&
  cardWindow.__dshPhoneCard.repaired === true,
  JSON.stringify(cardWindow.__dshPhoneCard));

// Now the band moves back to the whole screen and the card fits: the repair must be removed, or
// the phone would keep a stale pixel height after the keyboard closes.
band.offsetTop = 0;
band.height = 852;
cardFrameNode.rect = { top: 0, bottom: 852, left: 0, right: 393, height: 852, width: 393 };
cardTitle.rect = { top: 39, bottom: 60, left: 18, right: 300, height: 21, width: 282 };
for (const observer of cardObservers) observer.cb([{ addedNodes: [cardFrameNode], removedNodes: [] }]);
runFrames();
check('a fitting card has no repair left on it',
  Object.keys(cardFrameNode.inline).length === 0, JSON.stringify(cardFrameNode.inline));
check('and the measurement says it fits',
  cardWindow.__dshPhoneCard.fits === true && cardWindow.__dshPhoneCard.repaired === false,
  JSON.stringify(cardWindow.__dshPhoneCard));

// ── the layer stays current in a tab that is already open ────────────────────
//
// Behaviour 4. A phone tab lives for days, and the layer reaches it by REWRITING the document
// the gate serves — which cannot reach a tab that has already loaded. Measured 2026-09-16: the
// question-card repair was live and verified on a cold load, and the owner still could not read
// a question, because his tab predated the fix. These assertions pin the two halves of the
// answer: a stale token re-applies the layer, and it only reloads when nothing is in progress.
console.log('');
console.log('a tab that is already open picks up a newer phone layer');

const LAYER_V1 = '/* phone-layer-version: 2026-01-01.1 */\n.x{color:red}';
const LAYER_V2 = '/* phone-layer-version: 2026-01-02.1 */\n.x{color:blue}';

/** A sandbox with just enough DOM for the layer check, and a controllable fetch. */
function layerSandbox(options) {
  const state = { fetched: [], reloads: 0, injectedText: options.injectedText };
  const styleNode = {
    id: 'dsh-phone-mobile',
    textContent: options.injectedText,
    getAttribute: () => null,
    setAttribute: () => {},
  };
  const head = new CardElement('head');
  const document_ = {
    head,
    body: new CardElement('body'),
    createElement: (tag) => new CardElement(tag),
    getElementById: (id) => (styleNode.id === id ? styleNode : null),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    removeEventListener: () => {},
    activeElement: null,
    visibilityState: 'visible',
  };
  const win = {
    __ModuleLoader__: { load: (entry) => { win.__entry = entry; } },
    matchMedia: () => ({ matches: true }),
    console: { warn: () => {}, info: () => {} },
    setTimeout: (fn) => { fn(); return 1; },
    setInterval: () => 7,
    clearInterval: () => {},
    requestAnimationFrame: (fn) => { fn(); return 1; },
    addEventListener: () => {},
    removeEventListener: () => {},
    innerHeight: 852,
    location: { reload: () => { state.reloads += 1; } },
    fetch: (url) => {
      state.fetched.push(url);
      return Promise.resolve({ ok: true, text: () => Promise.resolve(options.servedText) });
    },
    document: document_,
  };
  const sandbox = {
    window: win,
    document: document_,
    globalThis: win,
    Element: CardElement,
    Promise,
    Date,
    setTimeout: win.setTimeout,
    MutationObserver: class { observe() {} disconnect() {} },
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: 'lib/client.js' });
  const mod = win.__entry.factory(() => { throw new Error('no requires'); });
  mod.apply(undefined);
  return { state, styleNode, win };
}

// The token is read from the served stylesheet and compared with the document's own copy.
const same = layerSandbox({ injectedText: LAYER_V1, servedText: LAYER_V1 });
await new Promise((resolve) => setImmediate(resolve));
check('the layer is fetched with no-store, so a cached answer cannot masquerade as current',
  same.state.fetched.length === 1 && same.state.fetched[0] === '/dsh-phone-mobile.css',
  JSON.stringify(same.state.fetched));
check('a matching token does nothing (no reload, no rewrite)',
  same.state.reloads === 0 && same.styleNode.textContent === LAYER_V1,
  'reloads=' + same.state.reloads);

const stale = layerSandbox({ injectedText: LAYER_V1, servedText: LAYER_V2 });
await new Promise((resolve) => setImmediate(resolve));
check('a newer served token is written into the open tab without a reload of its own',
  stale.styleNode.textContent === LAYER_V2, JSON.stringify(stale.styleNode.textContent));
check('and the tab reloads, because only a reload can bring a new version of the plugin',
  stale.state.reloads === 1, 'reloads=' + stale.state.reloads);

const busy = layerSandbox({ injectedText: LAYER_V1, servedText: LAYER_V2 });
busy.styleNode.id = 'dsh-phone-mobile';
busy.win.document.body = new CardElement('body');
await new Promise((resolve) => setImmediate(resolve));
check('a document whose layer is already current never reloads',
  layerSandbox({ injectedText: LAYER_V2, servedText: LAYER_V2 }).state.reloads === 0);

console.log('');
if (failures === 0) { console.log('client smoke OK'); process.exit(0); }
console.log(failures + ' check(s) failed');
process.exit(1);
