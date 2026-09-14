/**
 * GENERATED FILE — do not edit.
 * Built by scripts/build.mjs. The host half is concatenated from
 * src/cost-core.mjs, src/session-log.mjs and src/command.mjs; the browser half is
 * generated from pricing.json. Edit the sources and run `node scripts/build.mjs`.
 */

/**
 * A browser module for the DSH client loader.
 *
 * The client loader has no module body of its own: a bundle is a plain script that
 * registers a factory with `window.__ModuleLoader__.load`. The factory receives a
 * module-scoped `require` and must populate `module.exports`, which is this file's
 * only channel to the surface that mounts it. An ES module here is loaded but
 * silently contributes nothing.
 */
window.__ModuleLoader__.load({
  id: 'dsh-plugin-cost',
  factory: (require) => {
    const module = { exports: {} };
    const exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

    const React = require('react');

/**
 * The composer cost pill.
 *
 * It reads the same `tokenUsage` projection the shipped stats pill shows —
 * four integers covering the whole durable log — and prices them with the rate
 * table inlined below. Cost needs route attribution and a wall-clock instant to
 * choose the peak/off-peak rate, and neither survives into `tokenUsage`, so the
 * popover states the route assumption it made rather than implying exactness.
 */
const PRICING = {
  "$comment": "USD per 1,000,000 tokens, by provider+model, for the /cost command and the composer cost pill. Every rate carries its source and the date it was read. Edit a rate only by also updating effectiveFrom/source/readAt.",
  "version": 1,
  "updated": "2026-09-11",
  "defaultRoute": {
    "provider": "deepseek-official",
    "model": "deepseek-flash"
  },
  "routes": [
    {
      "provider": "deepseek-official",
      "models": [
        "deepseek-flash",
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp"
      ],
      "modelVersion": "DeepSeek-V4.1-Flash",
      "currency": "USD",
      "unit": "per_1m_tokens",
      "effectiveFrom": "2026-09-10T04:00:00Z",
      "readAt": "2026-09-11",
      "source": "https://api-docs.deepseek.com/quick_start/pricing",
      "sourceNote": "Footnote 1: the ids deepseek-v4-flash and deepseek-v4-flash-vision-exp are retired names still served by DeepSeek-V4.1-Flash at the Flash price. The provider's live /models endpoint returns exactly deepseek-flash and deepseek-v4-pro (re-read 2026-09-11).",
      "notes": "The card has three line items and no cache-write row, so cacheWriteTokens is unpriced. Do not charge it at the miss rate.",
      "rates": {
        "missPer1M": 0.15,
        "hitPer1M": 0.003,
        "writePer1M": 0,
        "outputPer1M": 0.6
      },
      "tiers": [
        {
          "name": "peak",
          "multiplier": 2,
          "days": [
            "Mon",
            "Tue",
            "Wed",
            "Thu",
            "Fri"
          ],
          "windows": [
            [
              "01:00",
              "04:00"
            ],
            [
              "06:00",
              "10:00"
            ]
          ],
          "timezone": "UTC"
        }
      ]
    },
    {
      "provider": "deepseek-official",
      "models": [
        "deepseek-v4-pro"
      ],
      "modelVersion": "DeepSeek-V4-Pro-0813",
      "currency": "USD",
      "unit": "per_1m_tokens",
      "effectiveFrom": "2026-09-10T04:00:00Z",
      "readAt": "2026-09-11",
      "source": "https://api-docs.deepseek.com/quick_start/pricing",
      "sourceNote": "Rates as published for V4 Pro; footnote 2 states V4 Pro continues past 2026-09-14 with billing unchanged.",
      "notes": "Re-read this card after 2026-09-14.",
      "rates": {
        "missPer1M": 0.66,
        "hitPer1M": 0.022,
        "writePer1M": 0,
        "outputPer1M": 1.98
      },
      "tiers": [
        {
          "name": "peak",
          "multiplier": 2,
          "days": [
            "Mon",
            "Tue",
            "Wed",
            "Thu",
            "Fri"
          ],
          "windows": [
            [
              "01:00",
              "04:00"
            ],
            [
              "06:00",
              "10:00"
            ]
          ],
          "timezone": "UTC"
        }
      ]
    },
    {
      "provider": "deepinfra",
      "models": [
        "deepseek-ai/DeepSeek-V4.1-Flash"
      ],
      "modelVersion": "DeepSeek-V4.1-Flash",
      "currency": "USD",
      "unit": "per_1m_tokens",
      "effectiveFrom": "2026-09-11",
      "readAt": "2026-09-11",
      "source": "https://deepinfra.com/deepseek-ai/DeepSeek-V4.1-Flash",
      "sourceNote": "Machine-readable at https://api.deepinfra.com/models/deepseek-ai/DeepSeek-V4.1-Flash.",
      "notes": "Flat rate, no time-of-day tier. The optional explicit-cache-write premium is null for this id, so writes are unpriced. Priority (1.5x) and Flex (0.8x) service tiers are not enabled by this harness.",
      "rates": {
        "missPer1M": 0.2,
        "hitPer1M": 0.006,
        "writePer1M": 0,
        "outputPer1M": 0.6
      },
      "tiers": []
    },
    {
      "provider": "deepinfra",
      "models": [
        "deepseek-ai/DeepSeek-V4-Flash-0731"
      ],
      "modelVersion": "DeepSeek-V4-Flash-0731",
      "currency": "USD",
      "unit": "per_1m_tokens",
      "effectiveFrom": "2026-09-11",
      "readAt": "2026-09-11",
      "source": "https://deepinfra.com/deepseek-ai/DeepSeek-V4-Flash-0731",
      "sourceNote": "Machine-readable at https://api.deepinfra.com/models/deepseek-ai/DeepSeek-V4-Flash-0731.",
      "notes": "A genuinely different, cheaper model id than deepseek-flash on deepseek-official. Flat rate.",
      "rates": {
        "missPer1M": 0.06,
        "hitPer1M": 0.015,
        "writePer1M": 0,
        "outputPer1M": 0.18
      },
      "tiers": []
    }
  ],
  "unpriced": {
    "deepseek-official/deepseek-reasoner": "Not present in the provider's live model list on 2026-09-11 and absent from the pricing card; deliberately not priced rather than guessed."
  }
};

/** 1 USD in micro-dollars; money stays integral so sums are exact. */
const MICRO = 1000000;

/** provider\0model -> route entry. */
const PRICE_INDEX = (() => {
  const index = new Map();
  for (const route of PRICING.routes) {
    for (const model of route.models) index.set(route.provider + '\u0000' + model, route);
  }
  return index;
})();

/** Local weekday and HH:MM in a named IANA timezone. */
function inZone(timestampMs, timeZone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(new Date(timestampMs));
  const pick = (type) => {
    const found = parts.find((part) => part.type === type);
    return found === undefined ? '' : found.value;
  };
  const hour = pick('hour') === '24' ? '00' : pick('hour');
  return { weekday: pick('weekday'), hhmm: hour + ':' + pick('minute') };
}

/** The tier covering an instant, if any. */
function tierAt(route, timestampMs) {
  for (const tier of route.tiers || []) {
    if (timestampMs === undefined || timestampMs === null) continue;
    const local = inZone(timestampMs, tier.timezone || 'UTC');
    if (tier.days && tier.days.indexOf(local.weekday) === -1) continue;
    for (const window of tier.windows || []) {
      if (local.hhmm >= window[0] && local.hhmm < window[1]) return tier;
    }
  }
  return undefined;
}

/** Effective per-1M rates for one route at one instant. */
function ratesAt(route, timestampMs) {
  const tier = tierAt(route, timestampMs);
  const multiplier = tier === undefined ? 1 : tier.multiplier;
  return {
    tier: tier === undefined ? 'off-peak' : tier.name,
    missPer1M: route.rates.missPer1M * multiplier,
    hitPer1M: route.rates.hitPer1M * multiplier,
    outputPer1M: route.rates.outputPer1M * multiplier,
  };
}

/**
 * Price one usage bucket.
 * @returns {{microUsd:number, tier:string, model:string}|undefined} undefined for an
 *   unpublished route, so the UI can say "unpriced" instead of showing a guess.
 */
function priceUsage(usage, route, timestampMs) {
  const entry = PRICE_INDEX.get(route.provider + '\u0000' + route.model);
  if (entry === undefined) return undefined;
  const rates = ratesAt(entry, timestampMs);
  const microUsd = Math.round(
    (usage.uncachedInputTokens || 0) * rates.missPer1M +
      (usage.cacheReadTokens || 0) * rates.hitPer1M +
      (usage.cacheWriteTokens || 0) * (entry.rates.writePer1M || 0) +
      (usage.outputTokens || 0) * rates.outputPer1M,
  );
  return { microUsd, tier: rates.tier, model: entry.modelVersion, route: rates };
}

/** Format micro-dollars for a compact pill. */
function formatUsd(microUsd) {
  const usd = microUsd / MICRO;
  if (usd === 0) return '$0';
  if (usd < 0.01) return '$' + usd.toFixed(4);
  if (usd < 10) return '$' + usd.toFixed(2);
  return '$' + usd.toFixed(2);
}

/** Which route to price this session at, and how confident that is. */
function chooseRoute() {
  const fallback = PRICING.defaultRoute;
  return { provider: fallback.provider, model: fallback.model, assumed: true };
}

/** A labelled row in the popover. */
function row(React, label, value, key) {
  return React.createElement(
    'div',
    { key, style: { display: 'flex', justifyContent: 'space-between', gap: '16px' } },
    React.createElement('span', { style: { color: 'var(--dsw-alias-label-tertiary)' } }, label),
    React.createElement('span', { style: { color: 'var(--dsw-alias-label-primary)', fontVariantNumeric: 'tabular-nums' } }, value),
  );
}

/** The cost pill itself. */
function CostPill(props) {
  const usage = props.useProjection ? props.useProjection('tokenUsage') : undefined;
  const stats = props.useProjection ? props.useProjection('sessionStats') : undefined;
  const [open, setOpen] = React.useState(false);

  if (usage === undefined) return null;
  const total = (usage.uncachedInputTokens || 0) + (usage.cacheReadTokens || 0) + (usage.cacheWriteTokens || 0) + (usage.outputTokens || 0);
  if (total === 0) return null;

  const route = chooseRoute();
  const priced = priceUsage(usage, route, Date.now());
  const prompt = (usage.uncachedInputTokens || 0) + (usage.cacheReadTokens || 0) + (usage.cacheWriteTokens || 0);
  const hit = prompt > 0 ? Math.round(((usage.cacheReadTokens || 0) / prompt) * 100) : null;
  const label = priced === undefined ? 'cost n/a' : formatUsd(priced.microUsd);

  const rows = [];
  if (priced !== undefined) {
    rows.push(row(React, 'Session cost', formatUsd(priced.microUsd), 'cost'));
    rows.push(row(React, 'Rate tier', priced.tier + ' ($' + priced.route.missPer1M + ' in / $' + priced.route.hitPer1M + ' cached / $' + priced.route.outputPer1M + ' out per 1M)', 'tier'));
  }
  rows.push(row(React, 'Billed tokens', total.toLocaleString('en-US'), 'tokens'));
  rows.push(row(React, 'Uncached input', (usage.uncachedInputTokens || 0).toLocaleString('en-US'), 'in'));
  rows.push(row(React, 'Cached input', (usage.cacheReadTokens || 0).toLocaleString('en-US'), 'cache'));
  if ((usage.cacheWriteTokens || 0) > 0) rows.push(row(React, 'Cache write', usage.cacheWriteTokens.toLocaleString('en-US'), 'write'));
  rows.push(row(React, 'Output', (usage.outputTokens || 0).toLocaleString('en-US'), 'out'));
  if (hit !== null) rows.push(row(React, 'Cache hit', hit + '%', 'hit'));
  if (stats !== undefined) rows.push(row(React, 'Turns / steps', stats.turns + ' / ' + stats.steps, 'steps'));

  return React.createElement(
    'span',
    { style: { position: 'relative', flex: 'none', display: 'inline-flex' } },
    React.createElement(
      'button',
      {
        type: 'button',
        onClick: () => setOpen(!open),
        title: 'Estimated session cost. Open for the rate card it used.',
        style: {
          display: 'inline-flex',
          alignItems: 'center',
          gap: '4px',
          padding: '0 8px',
          height: '20px',
          border: '1px solid var(--dsw-alias-border-l2)',
          borderRadius: '10px',
          background: open ? 'var(--dsw-alias-interactive-bg-hover)' : 'var(--dsw-alias-bg-layer-1)',
          color: 'var(--dsw-alias-label-secondary)',
          font: 'var(--dsw-font-xxs-12)',
          fontVariantNumeric: 'tabular-nums',
          cursor: 'pointer',
          whiteSpace: 'nowrap',
        },
      },
      label,
    ),
    open &&
      React.createElement(
        'div',
        {
          style: {
            position: 'absolute',
            bottom: '26px',
            left: '50%',
            transform: 'translateX(-50%)',
            minWidth: '300px',
            padding: '10px 12px',
            border: '1px solid var(--dsw-alias-border-l3)',
            borderRadius: '8px',
            background: 'var(--dsw-alias-bg-base)',
            boxShadow: 'var(--dsw-elevation-panel)',
            color: 'var(--dsw-alias-label-secondary)',
            font: 'var(--dsw-font-xxs-12)',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            zIndex: 30,
          },
        },
        React.createElement('div', { style: { font: 'var(--dsw-font-xs-strong-13)', color: 'var(--dsw-alias-label-primary)' } }, 'Session cost estimate'),
        rows,
        React.createElement(
          'div',
          { style: { marginTop: '6px', paddingTop: '6px', borderTop: '1px solid var(--dsw-alias-separator-primary)', color: 'var(--dsw-alias-label-tertiary)' } },
          'Priced at ' + route.provider + '/' + route.model + ' (the deployment default). The session projection carries no provider or model, so a session on another model is mispriced here. /cost prices from the log, per turn, with the real route.',
        ),
        React.createElement(
          'div',
          { style: { color: 'var(--dsw-alias-label-tertiary)' } },
          'Rates: ' + PRICING.routes[0].modelVersion + ', read ' + PRICING.updated + ' from ' + PRICING.routes[0].source,
        ),
      ),
  );
}

/**
 * No declared dependencies — deliberately.
 *
 * The browser loader treats EVERY name in the Plugin's own `inject` declaration, and
 * every name in the package's `dsh.client.inject` list, as a SERVICE it must resolve
 * through the client context before the entry may activate. This half needs only the
 * Slot registry, which it already reads defensively as `ctx.get('slots')`, so a
 * declaration here buys nothing and costs everything: on 2026-09-11 `optional:
 * ['slots']` (and earlier, two package-id entries in `dsh.client.inject`) never
 * resolved, the entry sat pending forever, and every window rendered
 * "Failed to load plugins" instead of the app.
 *
 * Declare a dependency here only when the plugin genuinely cannot function without it,
 * and then declare a SERVICE name — the shipped client plugins use plain names such as
 * `slots`, `locale`, `connection`, `remote` (see dsh-client-ui-settings-general).
 */

/**
 * Mount the pill into the composer dock.
 *
 * The dock is an additive list slot: a fresh `id` lands beside the shipped stats
 * pill and replaces nothing, and `order: 10` places it after that pill's `order: 0`.
 * @param ctx the browser plugin context
 */
function apply(ctx) {
  // ctx.slots, not ctx.get('slots'): the shipped client plugins register their own
  // composer pills with ctx.slots, and the by-name lookup returned undefined, so this
  // plugin silently contributed nothing. The owner's report was "I don't see any of that".
  // NOTE: this file GENERATES client source inside a template literal, so a backtick in a
  // comment here ends the literal. Escape it or do not use one.
  const slots = ctx.slots;
  if (slots === undefined) return;
  slots.inject('conversation.composer.dock', () =>
    slots.register({ name: 'conversation.composer.dock', id: 'cost', order: 10, label: 'Session cost' }, CostPill),
  );
}

    exports.apply = apply;
    // The slots dependency MUST be declared: reaching the registry as ctx.slots without
    // declaring it refuses the plugin at activation with 'cannot get property slots without
    // inject', which is exactly what the owner saw.
    exports.inject = ['slots'];
    exports.PRICING = PRICING;
    return module.exports;
  },
});
