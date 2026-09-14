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

console.log('');
if (failures === 0) { console.log('client smoke OK'); process.exit(0); }
console.log(failures + ' check(s) failed');
process.exit(1);
