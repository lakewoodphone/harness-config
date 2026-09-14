/**
 * Smoke-test the browser half the way the DSH client module system loads it.
 *
 * The bundle is a plain script that only REGISTERS a factory; module side effects live
 * inside the factory closure. So this test installs a fake `window.__ModuleLoader__`,
 * evaluates the bundle, materializes the factory with a stub `react`, drives `apply()`
 * against a fake Slot registry, and then invokes each registered cell's click handler
 * against a fake `window` to prove the two controls do two different things.
 *
 * It cannot prove pixels or that the app's bootstrap honours an empty
 * `dsh.sessions.current` — a real browser session is the only proof of that.
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

// ── a fake browser: module loader, DOM element factory, storage, location ─────
const registered = [];
const storage = new Map([['dsh.sessions.current', JSON.stringify({ sessionId: 'session-old' })]]);
const navigations = [];
let protocolHits = 0;

const fakeWindow = {
  __ModuleLoader__: { load: (entry) => registered.push(entry) },
  localStorage: {
    removeItem: (k) => storage.delete(k),
    getItem: (k) => (storage.has(k) ? storage.get(k) : null),
    setItem: (k, v) => storage.set(k, v),
  },
  location: {
    pathname: '/',
    get href() { return 'http://127.0.0.1:3099/'; },
    set href(value) { protocolHits++; navigations.push(value); },
    replace(value) { navigations.push(value); },
  },
  console: { warn: () => {} },
};

// React stub: record the props of the created element so a test can drive onClick.
function createElement(type, props, children) {
  return { type, props: props || {}, children };
}
const React = { createElement, useEffect: () => {}, useState: (v) => [v, () => {}] };

// The bundle uses React both as the injected module AND, for the helper components, as a
// bare global inside the factory closure, so the sandbox global and the injected module
// must be the same object or the elements are created by two different stubs.
const sandbox = { window: fakeWindow, globalThis: fakeWindow, React };
sandbox.window.window = fakeWindow;
sandbox.window.React = React;
sandbox.window.localStorage = fakeWindow.localStorage;
sandbox.window.location = fakeWindow.location;
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: 'lib/client.js' });

console.log('registration');
check('the bundle registers exactly one module entry', registered.length === 1, String(registered.length));
check('the entry id is the package id', registered[0] && registered[0].id === 'dsh-plugin-windows');

const moduleExports = registered[0].factory((name) => {
  if (name === 'react') return React;
  throw new Error('unexpected require: ' + name);
});
check('the factory returns an exports object', moduleExports && typeof moduleExports === 'object');
check('it exports apply', typeof moduleExports.apply === 'function');
check('it declares exactly the slots dependency',
  Array.isArray(moduleExports.inject) && moduleExports.inject.length === 1 && moduleExports.inject[0] === 'slots',
  JSON.stringify(moduleExports.inject));
console.log('slot registration');
let declaredSlot = null;
const registeredCells = [];
const fakeSlots = {
  inject: (name, callback) => { declaredSlot = name; callback(); },
  register: (options, cell) => { registeredCells.push({ options, cell }); },
};
const ctx = { slots: fakeSlots }; // the shipped client plugins reach the registry as ctx.slots
moduleExports.apply(ctx);
check('it waits for the composer dock slot', declaredSlot === 'conversation.composer.dock', String(declaredSlot));
check('it registers the two controls in each place', registeredCells.length === 4, String(registeredCells.length));
check('the first control is the in-window one',
  registeredCells[0] && registeredCells[0].options.id === 'new-session-here');
check('the second control is the new-window one',
  registeredCells[1] && registeredCells[1].options.id === 'new-session-window');
check('each control has its own slot id (list slots are keyed by id)',
  registeredCells[0].options.id !== registeredCells[1].options.id);

console.log('behaviour');
// Each registered cell returns a small wrapper element for the shared Control component.
// In the real browser the closure's `React` IS the injected module; in this sandbox the
// wrapper's element is built by the global stub, so render it through the same stub.
function renderCell(cell, props) {
  const outer = cell(props);
  if (!outer || !outer.props) return outer;
  if (typeof outer.type === 'function') {
    const inner = outer.type(outer.props);
    if (inner && inner.props) return inner;
  }
  return outer;
}
const hereElement = renderCell(registeredCells[0].cell, {});
const windowElement = renderCell(registeredCells[1].cell, {});
check('the first control renders a +', hereElement.children === '+', String(hereElement.children));
check('the second control renders a distinct glyph', windowElement.children !== '+', String(windowElement.children));
check('the first control is clickable', typeof hereElement.props.onClick === 'function');
check('the second control is clickable', typeof windowElement.props.onClick === 'function');

hereElement.props.onClick();
check('in-window control forgets the remembered session', !storage.has('dsh.sessions.current'));
check('in-window control navigates inside the same origin',
  /^\/\?new=/.test(navigations[navigations.length - 1] || ''), String(navigations[navigations.length - 1]));
check('in-window control does NOT touch the protocol', protocolHits === 0, String(protocolHits));

windowElement.props.onClick();
check('new-window control navigates to the launcher protocol',
  navigations[navigations.length - 1] === 'dsh-new://open', String(navigations[navigations.length - 1]));

console.log('');
if (failures === 0) { console.log('client smoke OK'); process.exit(0); }
console.log(failures + ' check(s) failed');
process.exit(1);
