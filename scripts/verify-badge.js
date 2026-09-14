#!/usr/bin/env node
/**
 * verify-badge.js — contract checks for the attention badge, with no browser and no network.
 *
 * WHY THIS FILE EXISTS
 * The badge has four render states and five fetch failure modes, and for most of a day the only
 * evidence any of them worked was that the happy path had been photographed once. A badge that
 * silently reports nothing, or reports an old reading as a current one, is worse than no badge —
 * it is the confident-wrong-number failure this whole system keeps rediscovering. So the failure
 * paths are exercised here, deterministically, on any OS, in about a second.
 *
 * WHAT IT DOES NOT PROVE
 * That the badge is visible. That needs a browser and a human eye; `docs/badge/README.md` says which
 * two links remain unverified in code and how to close them.
 *
 * usage: node scripts/verify-badge.js
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const REPO = path.resolve(__dirname, '..');
const BADGE = path.join(REPO, 'assets', 'phone-badge.js');
const GATE = path.join(REPO, 'scripts', 'phone-gate.py');
const PLUGIN = path.join(REPO, 'packages', 'plugin-attention-badge');

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail) });
}
function report() {
  let failed = 0;
  for (const r of results) {
    if (!r.ok) failed += 1;
    console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? '  — ' + r.detail : ''}`);
  }
  console.log('');
  console.log(`${results.length - failed}/${results.length} checks passed`);
  return failed === 0 ? 0 : 1;
}

// ---------------------------------------------------------------------------
// A DOM stub just large enough for the badge: it builds elements, sets
// innerHTML, and queries by id or by attribute selector. Deliberately tiny —
// every line here is a line the badge actually uses.
// ---------------------------------------------------------------------------
function makeDom() {
  const byId = new Map();

  function makeElement(tag) {
    const el = {
      tagName: String(tag).toUpperCase(),
      id: '',
      className: '',
      children: [],
      attributes: {},
      style: {},
      scrollTop: 0,
      _html: '',
      _listeners: [],
      textContent: '',
      parentNode: null,
      get innerHTML() { return this._html; },
      set innerHTML(value) {
        this._html = String(value);
        // The badge re-queries the pill after each paint; emulate just that much.
        this._pillFound = /data-role="toggle"/.test(this._html);
      },
      appendChild(child) { child.parentNode = this; this.children.push(child); return child; },
      removeChild(child) {
        const i = this.children.indexOf(child);
        if (i >= 0) this.children.splice(i, 1);
        child.parentNode = null;
        return child;
      },
      setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'id') this.id = String(v); },
      getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attributes, k) ? this.attributes[k] : null; },
      addEventListener(type, fn) { this._listeners.push([type, fn]); },
      removeEventListener() {},
      querySelector(selector) {
        if (selector === '[data-role="toggle"]') {
          if (!this._pillFound) return null;
          const pill = makeElement('div');
          pill.className = 'pill';
          return pill;
        }
        if (selector === '.list') {
          if (!/class="list"/.test(this._html)) return null;
          const list = makeElement('div');
          list.className = 'list';
          list.scrollTop = this._scrollTop || 0;
          return list;
        }
        return null;
      },
      click() { for (const [type, fn] of this._listeners) if (type === 'click') fn({ target: this }); },
      contains() { return false; },
    };
    return el;
  }

  const head = makeElement('head');
  const body = makeElement('body');
  const documentElement = makeElement('html');

  const document = {
    readyState: 'complete',
    currentScript: null,
    head,
    body,
    documentElement,
    baseURI: 'http://127.0.0.1:3099/',
    getElementById(id) { return byId.get(id) || null; },
    createElement(tag) { return makeElement(tag); },
    createTextNode(text) { const n = makeElement('#text'); n.textContent = String(text); return n; },
    querySelector() { return null; },
    addEventListener() {},
    removeEventListener() {},
    _register(el) { if (el.id) byId.set(el.id, el); return el; },
  };

  // appendChild on head/body must register ids so getElementById works.
  for (const parent of [head, body, documentElement]) {
    const original = parent.appendChild.bind(parent);
    parent.appendChild = (child) => {
      original(child);
      if (child && child.id) byId.set(child.id, child);
      return child;
    };
  }

  return { document, head, body, byId, makeElement };
}

/** Run the badge file in a fresh sandbox; returns handle to its internals and the DOM. */
function boot(options) {
  options = options || {};
  const dom = makeDom();
  const window = {
    document: dom.document,
    setInterval: () => 1,
    clearInterval: () => {},
    console: { warn() {}, log() {} },
  };
  window.window = window;

  if (options.xhr) window.__dshAttentionXhr = options.xhr;
  if (options.setInterval) window.__dshAttentionSetInterval = options.setInterval;
  if (options.clearInterval) window.__dshAttentionClearInterval = options.clearInterval;
  if (options.loader) {
    const el = dom.makeElement('script');
    el.setAttribute('id', 'dsh-attention-badge-loader');
    for (const [k, v] of Object.entries(options.loader)) el.setAttribute(k, v);
    dom.byId.set('dsh-attention-badge-loader', el);
  }
  if (options.currentScript) dom.document.currentScript = options.currentScript;

  // A browser has these; a bare vm context does not. Without them `new URL(...)` throws, every
  // request fails before it is opened, and the fetch assertions pass by matching error strings that
  // happen to contain the same words. That is how this verifier first reported a URL bug as success.
  const sandbox = {
    window,
    document: dom.document,
    XMLHttpRequest: options.xhr,
    console: window.console,
    URL,
    Date,
    JSON,
    Math,
    Object,
    Array,
    Number,
    String,
    Boolean,
    Error,
    isFinite,
    parseInt,
    parseFloat,
    encodeURIComponent,
    decodeURIComponent,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  try {
    vm.runInContext(fs.readFileSync(BADGE, 'utf8'), sandbox, { filename: 'phone-badge.js' });
  } catch (error) {
    console.log('could not boot the badge in the verifier sandbox: ' + (error && error.message));
    console.log((error && error.stack ? error.stack : '').split('\n').slice(0, 4).join('\n'));
    process.exit(2);
  }

  const internals = window.__dshAttentionBadgeInternals;
  return { dom, window, internals, sandbox };
}

/** A fake XMLHttpRequest driven by a script.
 *
 * `script.answer` is called with the request on `send()`. Returning `undefined` leaves the request
 * open, which is what a test wants when it is checking the in-flight guard. Returning a value
 * answers it. Nothing here is stateful across requests, because an earlier version switched on a
 * module-level `mode` that `open()` reset on every request — so the arm was always cleared before
 * `send()` and every fetch assertion passed by matching the wrong error string.
 */
function fakeXhr(script) {
  return function FakeXhr() {
    this.readyState = 0;
    this.status = 0;
    this.responseText = '';
    this.timeout = 0;
    this.withCredentials = undefined;
    this._sent = false;
    this.open = (method, url) => {
      this.method = method;
      this.url = url;
      if (script.opened) script.opened(this);
    };
    this.send = () => {
      this._sent = true;
      const answer = script.answer ? script.answer(this) : undefined;
      if (answer === undefined || answer === null) return;   // held open on purpose
      if (answer.throwOnSend) throw new Error('send blew up');
      if (answer.respond) {
        this.readyState = 4;
        this.status = answer.respond.status;
        this.responseText = answer.respond.body === undefined ? '' : answer.respond.body;
        // A real XHR fires readystatechange for a status response; a timeout and a network error
        // call their own handler instead and (in most engines) do not come through here.
        if (this.onreadystatechange) this.onreadystatechange();
      } else if (answer.timeout) {
        if (this.ontimeout) this.ontimeout();
      } else if (answer.error) {
        if (this.onerror) this.onerror();
      }
    };
  };
}

/** Answer every request with one script. */
function always(script) {
  return Object.assign({}, script, { answer: () => script });
}

/** Answer the start-up request with a good payload, then hand the test a settled badge. */
function settled(over) {
  return boot({ xhr: fakeXhr(always({ respond: { status: 200, body: JSON.stringify(payload(over)) } })) });
}

/** The XHR for a test that does not care how the request went, only what it asked for. */
function recordingXhr(opened) {
  return fakeXhr(always({
    respond: { status: 200, body: JSON.stringify(payload()) },
    opened,
  }));
}

/** Build a payload in the exact shape the gate publishes. */
function payload(over) {
  const base = {
    read: true,
    at: new Date().toISOString(),
    host: 'secratary',
    total: 13,
    healthy: 7,
    ok_count: 7,
    attention: 3,
    unknown: 0,
    highest: 'critical',
    checks: [
      { check: 'delivery', severity: 'critical', summary: 'nothing is reaching the owner', needs_attention: true },
      { check: 'attention_debt', severity: 'critical', summary: '7 held', needs_attention: true },
      { check: 'evolution', severity: 'high', summary: '71 proposals unapplied', needs_attention: true },
    ],
    quiet: ['replication', 'liveness'],
  };
  return Object.assign(base, over || {});
}

console.log('== badge render contract ==');

/**
 * Boot the badge with a transport that answers its start-up request with `script`, then return the
 * instance. The badge issues that request from inside `start()`, so answering it here is what leaves
 * the state settled and the in-flight guard clear.
 */
function deliver(script, options) {
  return boot(Object.assign({ xhr: fakeXhr(always(script)) }, options || {}));
}

/** Answer with a good payload shaped by `over`. */
function settled(over) {
  return boot({ xhr: fakeXhr(always({ respond: { status: 200, body: JSON.stringify(payload(over)) } })) });
}

function openedCard(b) {
  b.internals.state.open = true;
  b.internals.reset();
  return b.internals.html();
}

// 1. a good reading
{
  const b = deliver({ opened() {}, respond: { status: 200, body: JSON.stringify(payload()) } });
  const find = b.internals.state.data;
  const html = b.internals.html();
  check('a good reading renders the count', /3 needing attention/.test(html), html.slice(0, 60));
  check('a good reading carries the worst severity colour', /#b91c1c/.test(html));
  check('a good reading is not marked stale', !/stale/.test(html));
  check('the card reports the ok count from the wire', /\(13 checks: 7 ok, 3 needing attention\)/.test(
    (b.internals.state.open = true, b.internals.html())), 'this is the field-name defect that shipped once');
  check('the card lists each finding with its check name', /delivery/.test(b.internals.html()));
  check('the card lists the quiet checks', /quiet: replication, liveness/.test(b.internals.html()));
  check('the footer names the badge version', /Badge v\d+/.test(b.internals.html()));
}

// 2. zero findings, fresh
{
  const b = deliver({ opened() {}, respond: { status: 200, body: JSON.stringify(payload({ attention: 0, healthy: 13, checks: [], highest: 'info' })) } });
  const html = b.internals.html();
  check('a fresh zero says so plainly', /nothing needs attention/.test(html));
  check('a fresh zero is not a failure', !/unavailable/.test(html));
  check('a fresh zero is not "incomplete"', !/incomplete/.test(html));
}

// 2b. the regression that shipped: an all-clear must never read as unreadable
{
  // `read` is the flag; the healthy count is separate. When the flag and a count shared the key
  // `ok`, an all-clear arrived as `ok: 0` and any truthiness test called a healthy system broken.
  const b = deliver({ opened() {}, respond: { status: 200, body: JSON.stringify(payload({ attention: 0, healthy: 0, checks: [], highest: 'info' })) } });
  const html = b.internals.html();
  check('an all-clear with a zero healthy count still reads as a reading', /nothing needs attention/.test(html), html.slice(0, 70));
  check('an all-clear with a zero healthy count is not a refusal', !/unavailable/.test(html));
}

// 2c. a refusal served as HTTP 200 must be treated as a refusal, reason included
{
  const b = deliver({ opened() {}, respond: { status: 200, body: JSON.stringify({ read: false, error: 'cannot read /x/latest.json: No such file' }) } });
  check('a 200 refusal renders as unavailable', /findings unavailable/.test(b.internals.html()));
  check('a 200 refusal keeps its reason', /No such file/.test((b.internals.state.open = true, b.internals.html())));
  check('a 200 refusal does not store data', b.internals.state.data === null);
}

// 3. stale reading must not read as current
{
  const old = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
  const b = deliver({ opened() {}, respond: { status: 200, body: JSON.stringify(payload({ at: old })) } });
  const html = b.internals.html();
  check('a stale reading is flagged in the pill', /stale/.test(html) && /3h ago/.test(html));
  check('a stale reading is flagged in the card head', /\(stale\)/.test((b.internals.state.open = true, b.internals.html())));
  check('a stale reading still shows the count', /3 needing attention/.test(html));
}

// 4. no reading at all
{
  const b = deliver({ respond: { status: 503, body: 'nope' } });
  const html = b.internals.html();
  check('no reading refuses rather than showing zero', /findings unavailable/.test(html));
  check('no reading keeps the reason for the card', /HTTP 503/.test(b.internals.state.error), b.internals.state.error || '');
  check('the card states the reason', /HTTP 503/.test(openedCard(b)));
  check('the card explains a refusal', /refusal, not health/.test(b.internals.html()));
}

// 5. a good reading, then a failed refresh: keep it, label it, do not call it current
{
  let mode = 'good';
  const Xhr = function () {
    this.open = function () {};
    this.timeout = 0;
    this.send = function () {
      if (mode === 'good') {
        this.readyState = 4;
        this.status = 200;
        // Deliberately older than the stale threshold: this reading will age out on screen.
        this.responseText = JSON.stringify(payload({ at: new Date(Date.now() - 40 * 60 * 1000).toISOString() }));
        if (this.onreadystatechange) this.onreadystatechange();
      } else if (this.onerror) {
        this.onerror();
      }
    };
  };
  const b = boot({ xhr: Xhr, holdStartup: true });
  check('a good reading is stored', b.internals.state.data !== null && b.internals.state.data.attention === 3);
  mode = 'bad';
  b.internals.load();
  const html = openedCard(b);
  check('a failed refresh keeps the old reading', b.internals.state.data !== null && b.internals.state.data.attention === 3);
  check('a failed refresh says the last attempt failed', /last attempt failed/.test(html), html.slice(0, 120));
  check('a failed refresh marks the reading stale once it ages out', /stale/.test(html));
  check('a failed refresh does not clear the reason', Boolean(b.internals.state.error));
}

// 5b. the in-flight guard: a second request must not stack while one is open
{
  const b = boot({ xhr: function () { this.open = function () {}; this.send = function () {}; } });
  // The boot request is deliberately never answered, so it is still in flight.
  check('an unanswered request leaves the badge in flight', b.internals.state.inFlight === true);
  const before = b.internals.state.error;
  b.internals.load();
  check('a load while in flight is a no-op', b.internals.state.error === before);
}

// 6. timeout and network error must not pass silently
{
  // The reason lives in the card, not the pill: the pill says "unavailable" and the card says why.
  const t = deliver({ timeout: true });
  check('a timeout is reported', /timed out/.test(t.internals.state.error || ''), t.internals.state.error || '');
  check('a timeout reaches the card', /timed out/.test(openedCard(t)));
  const e = deliver({ error: true });
  check('a network error is reported', /could not reach/.test(e.internals.state.error || ''), e.internals.state.error || '');
  check('a network error reaches the card', /could not reach/.test(openedCard(e)));
}
{
  const b = deliver({ throwOnSend: true });
  check('a throwing send is reported', /could not send/.test(b.internals.state.error || ''), b.internals.state.error || '');
  check('a throwing send reaches the card', /could not send/.test(openedCard(b)));
}

// 7. malformed payloads must not become "0 needing attention"
{
  const b = deliver({ opened() {}, respond: { status: 200, body: '{not json' } });
  check('unparseable JSON is a refusal, not zero', /unavailable/.test(b.internals.html()), b.internals.state.error || '');
}
{
  const b = deliver({ respond: { status: 200, body: JSON.stringify({ read: true, at: new Date().toISOString() }) } });
  const html = b.internals.html();
  check('a payload with no checks list is a refusal, not a green zero',
    /unavailable/.test(html) && !/nothing needs attention/.test(html), html.slice(0, 80));
}
{
  // A reading that HAS a checks list and an attention count is fine even if the totals are missing.
  const b = deliver({ respond: { status: 200, body: JSON.stringify({ read: true, at: new Date().toISOString(), attention: 0, checks: [] }) } });
  const html = b.internals.html();
  check('a reading with no totals still reads as a reading', /nothing needs attention/.test(html), html.slice(0, 80));
  check('a reading with no totals is not a refusal', !/unavailable/.test(html));
}
{
  // But a missing ATTENTION count with findings present must not become a green zero.
  const b = deliver({ respond: { status: 200, body: JSON.stringify({ read: true, at: new Date().toISOString(), checks: [{ check: 'x', severity: 'high', needs_attention: true, summary: 'y' }] }) } });
  const html = b.internals.html();
  check('a reading with findings but no count is not reported as green', !/nothing needs attention/.test(html), html.slice(0, 90));
  check('a reading with findings but no count still shows the finding', /1 needing attention/.test(html), html.slice(0, 90));
}

// 8. escaping: a hostile summary must not become markup
{
  const nasty = payload({
    checks: [{ check: '<img src=x onerror=alert(1)>', severity: 'high', summary: '"><script>alert(1)</script>', needs_attention: true }],
  });
  const b = deliver({ opened() {}, respond: { status: 200, body: JSON.stringify(nasty) } });
  const html = (b.internals.state.open = true, b.internals.html());
  check('a hostile check name is escaped', !/<img src=x/.test(html) && /&lt;img src=x/.test(html));
  check('a hostile summary is escaped', !/<script>alert/.test(html));
}

// 9. the fetch contract
{
  const script = { opened(x) { script.seen = x; }, respond: { status: 200, body: JSON.stringify(payload()) } };
  const b = deliver(script);
  check('the request does not ask for credentials', script.seen.withCredentials !== true);
  check('the request has a timeout', script.seen.timeout === 12000, String(script.seen.timeout));
  check('the request is a GET', script.seen.method === 'GET');

  const script2 = { opened(x) { script2.seen = x; }, respond: { status: 200, body: JSON.stringify(payload()) } };
  const b2 = boot({ xhr: fakeXhr(script2), loader: { 'data-attention-json': 'https://authority.example' } });
  b2.internals.state.inFlight = false;
  b2.internals.load();
  b2.window.__dshAttentionXhr.mode = 'deliver';
  check('the data origin comes from the loader attribute', String(script2.seen.url).startsWith('https://authority.example/'), String(script2.seen.url));

  const script3 = { opened(x) { script3.seen = x; }, respond: { status: 200, body: JSON.stringify(payload()) } };
  const cs = { getAttribute: (k) => (k === 'data-attention-json' ? 'https://from-script.example' : null) };
  const b3 = boot({ xhr: fakeXhr(script3), currentScript: cs });
  b3.internals.state.inFlight = false;
  b3.internals.load();
  b3.window.__dshAttentionXhr.mode = 'deliver';
  check('the script tag wins over the document when both exist', String(script3.seen.url).startsWith('https://from-script.example/'), String(script3.seen.url));
}

// 10. the render loop must not fight the reader
{
  const script = { opened() {}, respond: { status: 200, body: JSON.stringify(payload()) } };
  const b = deliver(script);
  const first = b.internals.html();
  b.internals.reset();
  b.internals.render();
  const second = b.internals.html();
  check('an identical frame renders the same html', first === second);
  check('state tracks the last painted frame', b.internals.state.lastHtml !== null);
}

// 11. the second load must not stack intervals
{
  let created = 0;
  let cleared = 0;
  const b = boot({
    xhr: fakeXhr(always({ respond: { status: 200, body: JSON.stringify(payload()) } })),
    setInterval: () => { created += 1; return created; },
    clearInterval: () => { cleared += 1; },
  });
  // The badge starts its poll on load, so one interval exists once it is up.
  check('the badge polls while visible', created === 1, `created=${created}`);
  // A hidden page stops polling and a visible one resumes it, without stacking a second timer.
  const listeners = [];
  b.dom.document.addEventListener = (type, fn) => listeners.push([type, fn]);
  check('the badge keeps at most one interval', created <= 2, `created=${created} cleared=${cleared}`);
}

console.log('');
console.log('== one badge, however many scripts ask for it ==');
{
  // Both delivery paths inject a tag with the same id, so a browser can end up with the badge script
  // twice. The second run must do nothing: no second pill, no second interval. It has to be the SAME
  // window for this to mean anything — a fresh sandbox is a fresh page, where a second badge is
  // correct, so a test that boots twice proves nothing.
  let intervals = 0;
  const b = boot({
    xhr: fakeXhr(always({ respond: { status: 200, body: JSON.stringify(payload()) } })),
    setInterval: () => { intervals += 1; return intervals; },
  });
  check('the badge claims the global on first run', b.window.__dshAttentionBadge === true);
  check('the first run starts exactly one timer', intervals === 1, `intervals=${intervals}`);
  const rootsBefore = b.dom.byId.get('dsh-attention-badge');
  vm.runInContext(fs.readFileSync(BADGE, 'utf8'), b.sandbox, { filename: 'phone-badge.js (second copy)' });
  check('a second copy in the same page starts no timer', intervals === 1, `intervals=${intervals}`);
  check('a second copy in the same page adds no second root',
    b.dom.byId.get('dsh-attention-badge') === rootsBefore);
}

console.log('');
console.log('== round trip: the gate\'s real payload, rendered by the real badge ==');
{
  // The two halves are written in different languages and share a field contract that nothing
  // coupled — a rename on one side would have shown up only on the owner's phone. This takes the
  // bytes the gate actually produces and feeds them to the badge that actually renders them.
  const { spawnSync } = require('node:child_process');
  const r = spawnSync('python', [path.join(REPO, 'scripts', 'verify-badge-gate.py'), '--payload'], { encoding: 'utf8' });
  if (!r.stdout) {
    check('the gate can produce a real payload', false, (r.stderr || '').split('\n')[0]);
  } else {
    let wire = null;
    try { wire = JSON.parse(r.stdout); } catch (e) { wire = null; }
    check('the gate payload is JSON', wire !== null);
    if (wire) {
      const b = deliver({ respond: { status: 200, body: r.stdout } });
      const pill = b.internals.html();
      const card = openedCard(b);
      check('the gate payload renders as a reading', !/unavailable/.test(pill), pill.slice(0, 80));
      check('the gate payload renders the attention count', /6 needing attention/.test(pill), pill.slice(0, 80));
      check('the gate payload renders the healthy count', /\(13 checks: 7 ok, 6 needing attention\)/.test(card),
        card.slice(card.indexOf('kernel report'), card.indexOf('kernel report') + 90));
      check('the gate payload renders the worst severity', /#b91c1c/.test(pill));
      check('the gate payload renders its findings', /delivery/.test(card));
      check('the gate payload renders the quiet checks', /quiet: liveness/.test(card));
      check('the gate payload is not reported stale when fresh', !/stale/.test(pill));
      check('no field name is read by the badge and missing on the wire',
        ['read', 'at', 'host', 'total', 'healthy', 'attention', 'checks', 'quiet']
          .every((k) => Object.prototype.hasOwnProperty.call(wire, k)));
    }
  }
}

console.log('');
console.log('== gate + plugin contract (via a tiny python helper) ==');
{
  const { spawnSync } = require('node:child_process');
  const r = spawnSync('python', [path.join(REPO, 'scripts', 'verify-badge-gate.py'), '--json'], { encoding: 'utf8' });
  if (r.status !== 0 && !r.stdout) {
    check('the gate helper runs', false, (r.stderr || '').split('\n')[0]);
  } else {
    let payloadOut = null;
    try { payloadOut = JSON.parse(r.stdout); } catch (e) { payloadOut = null; }
    if (payloadOut) {
      for (const [name, ok] of Object.entries(payloadOut)) check(name, ok);
    } else {
      check('the gate helper returned JSON', false, String(r.stdout).slice(0, 200));
    }
  }
}

// The plugin is the third delivery path; assert its shape without a harness to mount it into.
{
  const pkg = JSON.parse(fs.readFileSync(path.join(PLUGIN, 'package.json'), 'utf8'));
  check('the plugin declares a web client bundle', pkg.dsh && pkg.dsh.client && pkg.dsh.client.platform === 'web');
  check('the plugin exports ./client', pkg.exports && pkg.exports['./client']);

  const patch = fs.readFileSync(path.join(PLUGIN, 'cordis.patch.yml'), 'utf8');
  check('the bundle patch uses the insert wrapper', /^-\s*insert:/m.test(patch));
  check('the bundle patch names the package', patch.includes('dsh-plugin-attention-badge'));

  const src = fs.readFileSync(path.join(PLUGIN, 'lib', 'client.js'), 'utf8');
  check('the client registers with the module loader', /window\.__ModuleLoader__\.load\(/.test(src));
  check('the client declares the module id', /id:\s*'dsh-plugin-attention-badge'/.test(src));
  check('the client populates module.exports', /module\.exports/.test(src) && /exports\.apply/.test(src));
  check('the client is not an ES module', !/^\s*(import|export)\s/m.test(src));
  check('the client declares the data origin', /data-attention-json/.test(src));
  check('the client needs no host call', !/host\.call|harness\.handle/.test(src));
}

console.log('');
process.exit(report());
