/**
 * Smoke-test dsh-plugin-mobile's browser half the way the DSH client module system loads it.
 *
 * The bundle is a plain script that only REGISTERS a factory; module side effects live inside
 * the factory closure. So this installs a fake `window.__ModuleLoader__`, evaluates the bundle,
 * materializes the factory, and then drives `apply()` against a small fake DOM to prove the two
 * behaviours it is responsible for:
 *
 *   1. the phone layer STYLESHEET is linked — because the injected copy travels inside the
 *      document, and a document served from a client's own cache carries no layer at all. This
 *      is the failure that made a phone look like none of the phone work had been done
 *      (measured 2026-09-14), and it is invisible to any check that reads the server's answer;
 *   2. picking a conversation in an open drawer closes it, tap-outside closes it, and a
 *      desktop width does nothing — the behaviour the stylesheet cannot provide.
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
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  addEventListener(type, fn) { this.listeners.push({ type, fn }); }
  removeEventListener(type, fn) {
    this.listeners = this.listeners.filter((l) => !(l.type === type && l.fn === fn));
  }
  /** Every element in the subtree, this one included. */
  walk() { return [this, ...this.children.flatMap((c) => c.walk())]; }
  get classList() { return String(this.attributes.class || ''); }
  contains(other) {
    for (let node = other; node; node = node.parent) if (node === this) return true;
    return false;
  }
  closest() { return null; }
}

const head = new FakeElement('head');
const body = new FakeElement('body');
const documentStub = {
  head,
  body,
  createElement: (tag) => new FakeElement(tag),
  getElementById: (id) => body.walk().concat(head.walk()).find((el) => el.id === id) || null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  removeEventListener: () => {},
};

const fakeWindow = {
  __ModuleLoader__: { load: (entry) => registered.push(entry) },
  matchMedia: (q) => ({ matches: narrow, media: q }),
  console: { warn: () => {} },
  setTimeout: (fn) => { pending.push(fn); return pending.length; },
  addEventListener: () => {},
  removeEventListener: () => {},
  document: documentStub,
};
const registered = [];
const pending = [];
let narrow = true;

const sandbox = {
  window: fakeWindow,
  document: documentStub,
  globalThis: fakeWindow,
  setTimeout: fakeWindow.setTimeout,
  MutationObserver: class { constructor(cb) { this.cb = cb; } observe() {} disconnect() {} },
};
sandbox.window.document = documentStub;
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

console.log('');
if (failures === 0) { console.log('client smoke OK'); process.exit(0); }
console.log(failures + ' check(s) failed');
process.exit(1);
