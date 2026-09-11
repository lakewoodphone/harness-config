/**
 * Smoke-test the browser half the way the client module system loads it.
 *
 * The bundle is a plain script that only REGISTERS a factory; module side effects
 * live inside the factory closure. So this test:
 *   1. installs a fake `window.__ModuleLoader__` that captures the registration,
 *   2. evaluates the bundle source in that scope,
 *   3. materializes the factory with a stub `react`,
 *   4. drives `apply()` against a fake Slot registry, and
 *   5. renders the registered cell with fake projection props.
 *
 * It proves registration shape and render output. It cannot prove pixels — a real
 * browser session is the only proof of that.
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
const check = (name, ok, detail) => {
  if (ok) console.log(`  ok    ${name}`);
  else {
    failures += 1;
    console.log(`  FAIL  ${name}${detail === undefined ? '' : ` — ${detail}`}`);
  }
};

// ── a minimal React that records the tree it is asked to build ────────────────
const created = [];
const element = (type, props, ...children) => {
  const node = { type, props: { ...(props ?? {}), ...(children.length === 0 ? {} : { children: children.length === 1 ? children[0] : children }) } };
  created.push(node);
  return node;
};
let stateSlots = 0;
const React = {
  createElement: element,
  useState: (initial) => {
    stateSlots += 1;
    return [typeof initial === 'function' ? initial() : initial, () => {}];
  },
  useMemo: (factory) => factory(),
  memo: (component) => component,
};

/** Flatten a React-ish tree into every string it contains. */
function textOf(node) {
  if (node === null || node === undefined || node === false) return [];
  if (typeof node === 'string' || typeof node === 'number') return [String(node)];
  if (Array.isArray(node)) return node.flatMap(textOf);
  if (typeof node === 'object' && node.props) return textOf(node.props.children);
  return [];
}

// ── evaluate the bundle as a script in a fake browser scope ───────────────────
let registration;
const context = vm.createContext({});
// In a browser `window` IS the global object; reproduce that, do not fake it.
context.window = context;
context.__ModuleLoader__ = { load: (r) => { registration = r; } };
vm.runInContext(source, context, { filename: 'lib/client.js' });

console.log('bundle registration');
check('the bundle registered exactly one module', registration !== undefined);
check('the module id is the package name', registration.id === 'dsh-plugin-cost', registration?.id);
check('the registration carries a factory', typeof registration.factory === 'function');

const exports_ = registration.factory((specifier) => {
  if (specifier === 'react') return React;
  throw new Error(`unexpected require(${specifier})`);
});

console.log('module face');
check('the factory returns an exports object', typeof exports_ === 'object' && exports_ !== null);
check('it exports apply', typeof exports_.apply === 'function');
// The browser loader resolves every declared dependency as a SERVICE and refuses to
// activate the entry until each one exists. On 2026-09-11 this entry declared two package
// ids and then optional:['slots']; none resolved, the entry stayed pending, and the loader
// blanked the whole web UI with "Failed to load plugins". The ABSENCE of a declaration is
// therefore a requirement, and this assertion is its regression test.
check('it declares no dependencies (a wrong name here blanks the UI)',
  exports_.inject === undefined || Object.keys(exports_.inject).length === 0,
  JSON.stringify(exports_.inject));
check('it exposes the rate table for diagnostics', typeof exports_.PRICING === 'object');

// ── drive apply() against a fake Slot registry ────────────────────────────────
let registeredName;
let registeredOptions;
let registeredCell;
let injectedSlot;
const fakeContext = {
  get: (key) => {
    if (key !== 'slots') return undefined;
    return {
      inject: (name, callback) => {
        injectedSlot = name;
        callback();
      },
      register: (options, cell) => {
        registeredOptions = options;
        registeredCell = cell;
        return () => {};
      },
    };
  },
};

exports_.apply(fakeContext);
console.log('slot registration');
check('it waits for the composer dock slot', injectedSlot === 'conversation.composer.dock', injectedSlot);
check('it registers into the composer dock', registeredOptions?.name === 'conversation.composer.dock');
check('it uses a fresh id so the shipped stats pill is untouched', registeredOptions?.id === 'cost', registeredOptions?.id);
check('it places itself after the shipped stats pill', registeredOptions?.order === 10, String(registeredOptions?.order));
check('it registers a renderable cell', typeof registeredCell === 'function');

// ── render with and without the projection ───────────────────────────────────
console.log('rendering');
const withUsage = registeredCell({
  useProjection: (key) =>
    key === 'tokenUsage'
      ? { uncachedInputTokens: 6260, cacheReadTokens: 186368, cacheWriteTokens: 0, outputTokens: 1151 }
      : { turns: 2, steps: 9 },
});
const withText = textOf(withUsage).join(' ');
check('the cell renders an element', withUsage !== null && withUsage !== undefined);
check('it shows a dollar figure', /\$\d/.test(withText), withText);
check('the total shown is a cost, not a token count', !withText.includes('193,779'), withText);

const withoutUsage = registeredCell({ useProjection: () => undefined });
check('it renders nothing when no usage projection is available', withoutUsage === null);

// A zero-usage session must not claim "$0.00" as a real reading.
const zeroUsage = registeredCell({
  useProjection: (key) => (key === 'tokenUsage' ? { uncachedInputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, outputTokens: 0 } : undefined),
});
check('it renders nothing for an all-zero session', zeroUsage === null);

// No projection hook at all must be survivable, not fatal.
const noHook = registeredCell({});
check('it survives missing standard props', noHook === null);

console.log(`\n${failures === 0 ? 'client smoke OK' : `${failures} check(s) failed`}`);
process.exit(failures === 0 ? 0 : 1);
