/**
 * phone-badge.js — the attention badge for the harness the owner actually opens.
 *
 * WHY THIS IS A PLAIN SCRIPT SERVED BY THE GATE
 * The badge has to show data the browser does not have: the company's own findings, written on the
 * authority at ~/ceo-kernel-var/latest.json by the kernel's 5-minute cron. The client cannot read a
 * host file, and the channel that would normally carry it (`host.call`) belongs to the dynamic Cordis
 * runner, which is deliberately disabled in this preset. So the gate carries it instead:
 *
 *   GET /dsh-attention.json   -> {at, total, attention, unknown, ok, checks:[...], highest}
 *   GET /dsh-attention.js     -> this file
 *
 * Both are served WITHOUT auth, deliberately, for the same reason the mobile stylesheet is: they carry
 * no secrets (check names and one-line summaries), and requiring a cookie would break the badge in
 * exactly the case it exists to cover - a document the client had cached.
 *
 * WHAT IT RENDERS
 * A small pill, bottom-right, showing how many findings need attention and the worst severity among
 * them. Tapping it opens the list: severity, check, summary, and the age of the reading. Tapping again
 * closes it. When the findings cannot be read, it says so instead of showing a green zero - an
 * unreadable source is a refusal, not health.
 *
 * IT IS DELIVERED TWICE, LIKE THE PHONE LAYER: once as a <script> the gate injects into the document,
 * and once by this file re-asserting itself, because a document served from the browser cache carries
 * no injection and an app that rewrites <head> can drop a node it does not own.
 */
(function () {
  'use strict';

  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (window.__dshAttentionBadge) return;
  window.__dshAttentionBadge = true;

  var STYLE_ID = 'dsh-attention-badge-style';
  var ROOT_ID = 'dsh-attention-badge';
  var POLL_MS = 60000;

  var COLORS = {
    critical: '#b91c1c',
    high: '#b45309',
    medium: '#4d7c0f',
    low: '#475569',
    info: '#334155',
    unknown: '#6b7280'
  };

  var state = {
    data: null,
    error: null,
    open: false,
    timer: null
  };

  function age(stamp) {
    if (!stamp) return 'age unknown';
    var millis = Date.parse(stamp);
    if (!isFinite(millis)) return 'age unknown';
    var minutes = Math.max(0, Math.round((Date.now() - millis) / 60000));
    if (minutes < 1) return 'just now';
    if (minutes < 60) return minutes + 'm ago';
    var hours = Math.floor(minutes / 60);
    if (hours < 48) return hours + 'h ago';
    return Math.floor(hours / 24) + 'd ago';
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
      + '#' + ROOT_ID + ' .dot{width:9px;height:9px;border-radius:50%;flex:none;}'
      + '#' + ROOT_ID + ' .count{font-weight:600;overflow:hidden;text-overflow:ellipsis;'
      + 'white-space:nowrap;}'
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
      + '#' + ROOT_ID + ' .empty{opacity:.85;}';
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
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    (document.body || document.documentElement).appendChild(el);
    return el;
  }

  function severityColor(sev) {
    return COLORS[String(sev || 'unknown').toLowerCase()] || COLORS.unknown;
  }

  function render() {
    var el = root();
    var data = state.data;
    var findings = (data && data.checks) || [];
    var count = data ? Number(data.attention || 0) : 0;
    var highest = (data && data.highest) || 'unknown';

    var dotColor = state.error ? COLORS.unknown : severityColor(highest);
    var label;
    if (state.error && data === null) label = 'findings unavailable';
    else if (count === 0) label = 'nothing needs attention';
    else label = count + ' needing attention';

    var html = '';
    html += '<div class="pill" data-role="toggle">';
    html += '<span class="dot" style="background:' + dotColor + '"></span>';
    html += '<span class="count">' + escapeHtml(label) + '</span>';
    html += '</div>';

    if (state.open) {
      html += '<div class="list">';
      if (state.error && data === null) {
        html += '<div class="head">Findings NOT READABLE</div>';
        html += '<div class="src">' + escapeHtml(state.error) + '</div>';
        html += '<div class="sum">An unreadable source is a refusal, not health - nothing below is proven current.</div>';
      } else {
        html += '<div class="head">Company findings</div>';
        html += '<div class="src">kernel report written ' + escapeHtml(age(data && data.at))
          + ' on ' + escapeHtml((data && data.host) || '?')
          + ' (' + (data && data.total) + ' checks: ' + (data && data.ok) + ' ok, '
          + count + ' needing attention)</div>';
        if (findings.length === 0) {
          html += '<div class="empty">nothing needs attention</div>';
        } else {
          for (var i = 0; i < findings.length; i += 1) {
            var f = findings[i];
            html += '<div class="item">'
              + '<span class="sev" style="color:' + severityColor(f.severity) + '">'
              + escapeHtml(String(f.severity || '?').toUpperCase()) + '</span> '
              + '<span class="chk">' + escapeHtml(f.check || '?') + '</span><br>'
              + '<span class="sum">' + escapeHtml(f.summary || '') + '</span>'
              + '</div>';
          }
        }
        if (data && data.quiet && data.quiet.length) {
          html += '<div class="quiet">quiet: ' + escapeHtml(data.quiet.join(', ')) + '</div>';
        }
      }
      html += '<div class="src" style="margin-top:8px">Read-only. Tap the pill to close.</div>';
      html += '</div>';
    }

    el.innerHTML = html;
    el.className = state.open ? 'open' : '';
    var toggle = el.querySelector('[data-role="toggle"]');
    if (toggle !== null) {
      toggle.addEventListener('click', function () {
        state.open = !state.open;
        render();
      });
    }
  }

  function escapeHtml(value) {
    return String(value === undefined || value === null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function load() {
    var url = '/dsh-attention.json?t=' + Date.now();
    var req = new XMLHttpRequest();
    req.open('GET', url, true);
    req.timeout = 12000;
    req.onreadystatechange = function () {
      if (req.readyState !== 4) return;
      if (req.status >= 200 && req.status < 300) {
        try {
          state.data = JSON.parse(req.responseText);
          state.error = null;
        } catch (error) {
          state.error = 'the report did not parse';
        }
      } else if (state.data === null) {
        // Keep the last good reading rather than flashing empty; say it is stale instead.
        state.error = 'the gate answered HTTP ' + req.status;
      }
      render();
    };
    try {
      req.send();
    } catch (error) {
      state.error = 'could not reach the gate';
      render();
    }
  }

  function start() {
    style();
    render();
    load();
    if (state.timer === null) state.timer = window.setInterval(load, POLL_MS);
    // Some pages rewrite <body>; re-assert rather than assume we survive.
    if (typeof MutationObserver === 'function' && document.body) {
      var observer = new MutationObserver(function () {
        if (document.getElementById(ROOT_ID) === null) render();
      });
      observer.observe(document.body, { childList: true });
    }
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') load();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
