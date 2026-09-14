/**
 * phone-badge.js - the attention badge for the harness the owner actually opens.
 *
 * WHAT IT IS
 * A pill, fixed bottom-right, showing how many of the kernel's checks need attention and the worst
 * severity among them. Tapping it opens the list: severity, check, summary, and how old the reading
 * is. Tapping again closes it.
 *
 * WHERE THE DATA COMES FROM, AND WHY IT IS NOT A HOST CALL
 * The kernel writes its findings to `~/ceo-kernel-var/latest.json` on the authority every 5 minutes.
 * The browser cannot read a host file, and the client-to-host channel (`host.call`) belongs to the
 * dynamic Cordis runner, which is deliberately disabled in this preset. So the phone gate carries it:
 *
 *   GET /dsh-attention.json   -> {ok, at, host, total, ok, attention, unknown, highest, checks[], quiet[]}
 *   GET /dsh-attention.js     -> this file
 *
 * Both are served WITHOUT auth, deliberately: the payload is check names, severities and one-line
 * summaries - no credentials, no customer data - and requiring a cookie would break the badge in
 * exactly the case it exists to cover, a document the client had cached.
 *
 * THREE WAYS IN, ONE IMPLEMENTATION
 *   1. the phone gate injects `<script id="dsh-attention-badge-loader" src="/dsh-attention.js">`
 *   2. `dsh-plugin-attention-badge` injects the same tag, pointing at the authority, on every other
 *      machine (which runs its own engine on loopback and has nothing rewriting its document)
 *   3. a cached document carries no injection, so this file re-asserts itself - and refuses to run twice
 *
 * THE DATA ORIGIN IS READ FROM THE SCRIPT TAG, NOT GUESSED
 * The injected tag carries `data-attention-json`. The badge resolves its fetch against that, falling
 * back to `document.baseURI`. This matters: on a desktop the script comes from the authority while the
 * page is `http://127.0.0.1:3099`, so a relative fetch would ask the local engine for a route it does
 * not have. Guessing the origin worked only while the phone and the authority happened to share a
 * hostname - an invisible coupling that would have broken the day either changed.
 *
 * IT IS HONEST ABOUT WHAT IT CANNOT SEE. Four states are rendered distinctly, and three of them are
 * deliberately not green:
 *   - no reading ever received      -> "findings unavailable" + the reason
 *   - a reading that is too old     -> the count, plus "· stale" and the age, because a stale reading
 *                                      presented as current is the same lie as a confident wrong number
 *   - a good reading                -> the count and the severity dot
 *   - zero findings, fresh          -> "nothing needs attention"
 *
 * VERIFYING IT
 *   node scripts/verify-badge.js          contract checks that need no browser and either OS
 *   bash scripts/verify-badge-live.sh     the routes, over HTTP, against a running gate
 * Contract and failure modes: docs/badge/README.md in this repo.
 */
(function () {
  'use strict';

  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (window.__dshAttentionBadge) return;
  window.__dshAttentionBadge = true;

  /** Bumped by hand when the rendering or the fetch changes, and shown in the card footer. */
  var VERSION = '3';
  var STYLE_ID = 'dsh-attention-badge-style';
  var ROOT_ID = 'dsh-attention-badge';
  var LOADER_ID = 'dsh-attention-badge-loader';
  var POLL_MS = 60000;
  /**
   * The kernel writes every 5 minutes. Three missed writes is a stopped kernel, not a quiet one, so
   * past this the reading is labelled stale rather than shown as current.
   */
  var STALE_MS = 20 * 60 * 1000;

  var COLORS = {
    critical: '#b91c1c',
    high: '#b45309',
    medium: '#4d7c0f',
    low: '#475569',
    info: '#334155',
    unknown: '#6b7280'
  };

  /**
   * Read the data origin while the script is still executing; it is null in any later callback.
   *
   * The two `window.__dsh*` overrides exist so `scripts/verify-badge.js` can drive this file in a
   * bare JS environment - no browser, no network - and assert what it renders in each failure mode.
   * A badge whose failure paths have never been executed is a badge whose failure paths do not work;
   * assuming otherwise is how the "findings unavailable" path would have shipped untested.
   */
  var SELF = document.currentScript;
  var DATA_ORIGIN = (function () {
    try {
      var declared = SELF && SELF.getAttribute && SELF.getAttribute('data-attention-json');
      if (declared) return declared;
      var loader = document.getElementById(LOADER_ID);
      if (loader && loader.getAttribute) {
        var fromLoader = loader.getAttribute('data-attention-json');
        if (fromLoader) return fromLoader;
      }
    } catch (error) { /* fall through to the document's own base */ }
    return '';
  })();

  var state = {
    data: null,          // last successfully parsed payload
    error: null,         // why the last attempt failed, if it did
    open: false,
    timer: null,
    lastHtml: null,
    inFlight: false
  };

  /** Present only for the verifier; harmless in a page. */
  window.__dshAttentionBadgeInternals = {
    state: state,
    render: function () { render(); },
    load: function () { load(); },
    html: function () { return html(state); },
    reset: function () { state.lastHtml = null; },
    version: VERSION,
    staleMs: STALE_MS
  };

  /**
   * Coerce a count that came off the wire.
   *
   * `Number(null)` is 0 and `Number(undefined)` is NaN, so a naive coercion turns a MISSING count
   * into a confident zero - and "0 needing attention" is the one reading that looks like good news.
   * A count that is absent, null or blank is therefore `null`, which the renderer shows as
   * "findings incomplete" rather than as an all-clear.
   */
  function countOf(value) {
    if (value === null || value === undefined || value === '') return null;
    var n = Number(value);
    return isFinite(n) ? n : null;
  }

  /** Own-property lookup, so `severity: "constructor"` cannot resolve an inherited value. */
  function ownColor(sev) {
    var key = String(sev === null || sev === undefined ? '' : sev).toLowerCase();
    if (!Object.prototype.hasOwnProperty.call(COLORS, key)) return null;
    return COLORS[key];
  }

  /** Array.isArray without depending on it: this file is written to run in old mobile Safari. */
  function isArray(value) {
    return Object.prototype.toString.call(value) === '[object Array]';
  }

  /** Age in ms of the reading the payload carries, or undefined when it carries no usable stamp. */
  function readingAgeMs(data) {
    if (!data || typeof data.at !== 'string' || !data.at) return undefined;
    var millis = Date.parse(data.at);
    if (!isFinite(millis)) return undefined;
    return Math.max(0, Date.now() - millis);
  }

  /**
   * A reading whose age cannot be established is treated as stale, not as current.
   *
   * The earlier version answered `false` when the age was unknown, which meant a payload with no
   * parseable timestamp rendered as "6 needing attention" with no staleness flag at all - a reading
   * of unknown age presented as a fresh one. Not knowing how old something is cannot be a reason to
   * call it new.
   */
  function isStale(data) {
    var age = readingAgeMs(data);
    if (age === undefined) return true;
    return age > STALE_MS;
  }

  function humanAge(ms) {
    if (ms === undefined) return 'age unknown';
    var minutes = Math.round(ms / 60000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return minutes + 'm ago';
    var hours = Math.floor(minutes / 60);
    if (hours < 48) return hours + 'h ago';
    return Math.floor(hours / 24) + 'd ago';
  }

  function severityColor(sev) {
    // A severity that is not a known string (an object, a prototype key, a number) gets the neutral
    // colour rather than resolving through Object.prototype or stringifying to "[object Object]".
    return ownColor(sev) || COLORS.unknown;
  }

  function severityLabel(sev) {
    if (typeof sev !== 'string' || !sev) return '?';
    return sev.toUpperCase();
  }

  function escapeHtml(value) {
    return String(value === undefined || value === null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /** Array.isArray without depending on it: this file is written to run in old mobile Safari. */
  function isArray(value) {
    return Object.prototype.toString.call(value) === '[object Array]';
  }

  function style() {
    if (document.getElementById(STYLE_ID) !== null) return;
    var css = ''
      + '#' + ROOT_ID + '{position:fixed;left:16px;right:16px;bottom:14px;z-index:2147483000;'
      + 'display:flex;flex-direction:column;align-items:flex-end;pointer-events:none;'
      + 'font:13px/1.35 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;'
      + 'color:#e5e7eb;}'
      + '#' + ROOT_ID + ',#' + ROOT_ID + ' *{box-sizing:border-box;}'
      + '#' + ROOT_ID + ' .pill{pointer-events:auto;display:inline-flex;align-items:center;gap:8px;'
      + 'max-width:100%;padding:8px 12px;border-radius:999px;'
      + 'border:1px solid rgba(255,255,255,.22);background:rgba(15,23,42,.92);color:#f8fafc;'
      + 'cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.35);'
      + '-webkit-tap-highlight-color:transparent;}'
      + '#' + ROOT_ID + ' .pill.warn{border-color:rgba(180,83,9,.85);}'
      + '#' + ROOT_ID + ' .pill.blind{border-style:dashed;border-color:rgba(148,163,184,.7);}'
      + '#' + ROOT_ID + ' .dot{width:9px;height:9px;border-radius:50%;flex:none;}'
      + '#' + ROOT_ID + ' .count{font-weight:600;overflow:hidden;text-overflow:ellipsis;'
      + 'white-space:nowrap;}'
      + '#' + ROOT_ID + ' .flag{opacity:.8;font-weight:500;}'
      + '#' + ROOT_ID + ' .list{pointer-events:auto;display:none;width:100%;max-width:440px;'
      + 'margin-top:8px;padding:10px 12px;border-radius:10px;'
      + 'border:1px solid rgba(255,255,255,.18);background:rgba(15,23,42,.96);'
      + 'box-shadow:0 6px 22px rgba(0,0,0,.4);max-height:52vh;overflow:auto;}'
      + '#' + ROOT_ID + '.open .list{display:block;}'
      + '#' + ROOT_ID + ' .head{font-weight:600;margin-bottom:6px;}'
      + '#' + ROOT_ID + ' .src{opacity:.75;font-size:12px;margin-bottom:8px;}'
      + '#' + ROOT_ID + ' .item{margin:0 0 9px 0;}'
      + '#' + ROOT_ID + ' .sev{font-weight:700;letter-spacing:.03em;font-size:11px;}'
      + '#' + ROOT_ID + ' .chk{font-weight:600;}'
      + '#' + ROOT_ID + ' .sum{opacity:.9;font-size:12px;overflow-wrap:anywhere;}'
      + '#' + ROOT_ID + ' .quiet{opacity:.7;font-size:12px;overflow-wrap:anywhere;}'
      + '#' + ROOT_ID + ' .empty{opacity:.85;}'
      + '#' + ROOT_ID + ' .foot{opacity:.6;font-size:11px;margin-top:8px;}';
    var el = document.createElement('style');
    el.id = STYLE_ID;
    el.setAttribute('data-layer', 'phone-badge');
    el.appendChild(document.createTextNode(css));
    (document.head || document.documentElement).appendChild(el);
  }

  function root() {
    var el = document.getElementById(ROOT_ID);
    if (el !== null) return el;
    el = document.createElement('div');
    el.id = ROOT_ID;
    el.setAttribute('data-layer', 'phone-badge');
    el.setAttribute('data-badge-version', VERSION);
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    (document.body || document.documentElement).appendChild(el);
    return el;
  }

  /** Everything the card shows, as a string. Pure: same state in, same html out. */
  function html(state) {
    var data = state.data;
    // Readability is decided by the shape, not by a boolean: a payload that carries a list of checks
    // is a reading; anything else is a refusal. That is what makes a healthy `0 needing attention`
    // distinguishable from `could not read`, which a truthiness test on a count field cannot do --
    // a system with zero problems and a system that cannot be read both arrive as `0`.
    var readable = Boolean(data) && isArray(data.checks);
    var findings = readable ? data.checks : [];
    var count = readable ? countOf(data.attention) : null;
    var healthy = readable ? countOf(data.healthy) : null;
    if (healthy === null) healthy = readable ? countOf(data.ok_count) : null;
    var total = readable ? countOf(data.total) : null;
    var highest = (readable && data.highest) || 'unknown';
    var blind = !readable;
    var stale = readable && isStale(data);
    var ageMs = readingAgeMs(data);

    var out = '';
    var pillClass = 'pill' + (blind ? ' blind' : (stale ? ' warn' : ''));
    var dotColor = blind ? COLORS.unknown : severityColor(highest);
    // The pill's number is derived from the list it is about to show when the two disagree. A pill
    // that says "nothing needs attention" above a red CRITICAL row is worse than either reading on
    // its own: it invites the reader to dismiss a card that is showing them a problem.
    var shown = readable ? Math.max(findings.length, count === null ? 0 : count) : 0;
    var label;
    if (blind) label = 'findings unavailable';
    else if (count === null && findings.length === 0) label = 'findings incomplete';
    else if (shown === 0) label = 'nothing needs attention';
    else label = shown + ' needing attention';
    var flag = stale ? '· stale ' + humanAge(ageMs) : (state.error ? '· last good' : '');

    out += '<div class="' + pillClass + '" data-role="toggle">';
    out += '<span class="dot" style="background:' + dotColor + '"></span>';
    out += '<span class="count">' + escapeHtml(label) + '</span>';
    if (flag) out += '<span class="flag">' + escapeHtml(flag) + '</span>';
    out += '</div>';

    if (state.open) {
      out += '<div class="list">';
      if (blind) {
        out += '<div class="head">Findings NOT READABLE</div>';
        out += '<div class="src">' + escapeHtml(state.error || (data && data.error) || 'no reading has arrived') + '</div>';
        out += '<div class="sum">An unreadable source is a refusal, not health. Nothing here is'
          + ' proven current.</div>';
      } else {
        out += '<div class="head">Company findings' + (stale ? ' (stale)' : '') + '</div>';
        out += '<div class="src">kernel report written ' + escapeHtml(humanAge(ageMs))
          + ' on ' + escapeHtml(data.host || '?')
          + ' (' + escapeHtml(String(total === null ? '?' : total)) + ' checks: '
          + escapeHtml(String(healthy === null ? '?' : healthy)) + ' ok, '
          + escapeHtml(String(count === null ? '?' : count)) + ' needing attention)'
          + (state.error ? '<br>last attempt failed: ' + escapeHtml(state.error) : '')
          + '</div>';
        if (findings.length === 0) {
          out += '<div class="empty">'
            + (count === null ? 'no findings list in this reading' : 'nothing needs attention')
            + '</div>';
        } else {
          for (var i = 0; i < findings.length; i += 1) {
            var f = findings[i] || {};
            out += '<div class="item">'
              + '<span class="sev" style="color:' + severityColor(f.severity) + '">'
              + escapeHtml(severityLabel(f.severity)) + '</span> '
              + '<span class="chk">' + escapeHtml(f.check || '?') + '</span><br>'
              + '<span class="sum">' + escapeHtml(f.summary || '') + '</span>'
              + '</div>';
          }
        }
        if (data.quiet && data.quiet.length) {
          out += '<div class="quiet">quiet: ' + escapeHtml(data.quiet.join(', ')) + '</div>';
        }
      }
      out += '<div class="foot">Read-only. Tap the pill to close. Badge v' + escapeHtml(VERSION) + '.'
        + '</div>';
      out += '</div>';
    }
    return out;
  }

  function render() {
    var el = root();
    var next = html(state);
    // Skip an identical frame. Replacing the DOM every minute resets the card's scroll position and
    // any text selection, which is exactly what someone reading a long finding does not want.
    if (next === state.lastHtml) return;
    state.lastHtml = next;

    // Preserve the card's scroll offset across a genuine re-render.
    var previous = el.querySelector('.list');
    var scrollTop = previous === null ? 0 : previous.scrollTop;

    el.innerHTML = next;
    el.className = state.open ? 'open' : '';

    var list = el.querySelector('.list');
    if (list !== null && scrollTop) list.scrollTop = scrollTop;

    var toggle = el.querySelector('[data-role="toggle"]');
    if (toggle !== null) {
      toggle.addEventListener('click', function () {
        state.open = !state.open;
        state.lastHtml = null;   // the open state is not in state.data; force a repaint
        render();
      });
    }
  }

  function fail(reason) {
    state.error = reason;
    render();
  }

  function load() {
    if (state.inFlight) return;
    state.inFlight = true;
    var url;
    try {
      url = new URL('/dsh-attention.json?t=' + Date.now(), DATA_ORIGIN || document.baseURI
        || (window.location && window.location.href) || '/').href;
    } catch (error) {
      state.inFlight = false;
      fail('could not build a URL for the findings');
      return;
    }

    var req = new (window.__dshAttentionXhr || XMLHttpRequest)();
    // No credentials: the endpoint needs none, and asking for them would make the CORS answer
    // unusable with the wildcard the gate also serves to the phone.
    try {
      req.open('GET', url, true);
    } catch (error) {
      state.inFlight = false;
      fail('could not open a request for the findings');
      return;
    }
    req.timeout = 12000;

    function done() {
      state.inFlight = false;
    }

    req.onreadystatechange = function () {
      if (req.readyState !== 4) return;
      done();
      if (req.status >= 200 && req.status < 300) {
        var parsed;
        try {
          parsed = JSON.parse(req.responseText);
        } catch (error) {
          fail(state.data === null
            ? 'the report did not parse'
            : 'the latest report did not parse; showing the last good reading');
          return;
        }
        // The gate answers 200 with `read:false` when it cannot read the kernel's file. That is a
        // refusal carrying its reason, not a reading: storing it would make the badge claim it has
        // data while showing an empty list.
        if (parsed && parsed.read === false) {
          fail(parsed.error || 'the findings are not readable on the host');
          return;
        }
        state.data = parsed;
        state.error = null;
        render();
        return;
      }
      // Keep the last good reading rather than flashing empty, but say so out loud - and because the
      // pill then shows a reading that is not current, the age check marks it stale as time passes.
      fail(state.data === null
        ? 'the findings answered HTTP ' + req.status
        : 'HTTP ' + req.status + ' on the last attempt');
    };
    // A timeout and a network error do NOT go through onreadystatechange in every browser: without
    // these two handlers a hung or unreachable gate produced no error at all, and the badge simply
    // sat on its last reading with nothing said.
    req.ontimeout = function () {
      done();
      fail(state.data === null ? 'the findings timed out' : 'the last attempt timed out');
    };
    req.onerror = function () {
      done();
      fail(state.data === null
        ? 'could not reach the findings'
        : 'could not reach the findings on the last attempt');
    };

    try {
      req.send();
    } catch (error) {
      done();
      fail('could not send the request for the findings');
    }
  }

  /** Poll only while the page is visible: a backgrounded tab does not need 60 reads an hour. */
  function startPolling() {
    if (state.timer !== null) return;
    var set = window.__dshAttentionSetInterval || window.setInterval;
    state.timer = set(load, POLL_MS);
  }

  function stopPolling() {
    if (state.timer === null) return;
    var clear = window.__dshAttentionClearInterval || window.clearInterval;
    clear(state.timer);
    state.timer = null;
  }

  function start() {
    style();
    render();
    load();
    startPolling();

    // Some apps rewrite <body>. Re-assert rather than assume we survive; the observer guards on the
    // element being absent so this converges instead of looping.
    if (typeof MutationObserver === 'function' && document.body) {
      try {
        var observer = new MutationObserver(function () {
          if (document.getElementById(ROOT_ID) === null) {
            state.lastHtml = null;
            render();
          }
        });
        observer.observe(document.body, { childList: true });
      } catch (error) { /* an engine without MutationObserver keeps the badge, just less resilient */ }
    }

    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') {
        load();
        startPolling();
      } else {
        stopPolling();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
