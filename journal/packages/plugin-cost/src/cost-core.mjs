/**
 * Cost accounting for DeepSeek-family token usage.
 *
 * This module is written so its body can be embedded verbatim into a Cordis
 * dynamic plugin's `code.host`, where ES module syntax is unavailable but the
 * plain functions below are. It is developed and tested as a real module first
 * (`node test/cost.test.mjs`) and inlined second, so the shipped code is the
 * tested code.
 *
 * Money is integer micro-dollars (1e-6 USD) throughout. Sums of per-attempt costs
 * are therefore exact, and the only rounding happens once, at display.
 */

/** 1 USD in micro-dollars. */
var MICRO = 1000000;

/**
 * The rate table. Rates are USD per 1M tokens, which is also micro-dollars per
 * token — that identity is why the arithmetic below needs no scaling factor.
 * Mirrored from pricing.json; `scripts/build-plugin.mjs` fails if they diverge.
 */
var PRICING = {
  version: 1,
  updated: '2026-09-11',
  defaultRoute: { provider: 'deepseek-official', model: 'deepseek-flash' },
  routes: [
    {
      provider: 'deepseek-official',
      models: ['deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp'],
      modelVersion: 'DeepSeek-V4.1-Flash',
      effectiveFrom: '2026-09-10T04:00:00Z',
      source: 'https://api-docs.deepseek.com/quick_start/pricing',
      rates: { missPer1M: 0.15, hitPer1M: 0.003, writePer1M: 0, outputPer1M: 0.6 },
      tiers: [
        {
          name: 'peak',
          multiplier: 2,
          days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
          windows: [['01:00', '04:00'], ['06:00', '10:00']],
          timezone: 'UTC',
        },
      ],
    },
    {
      provider: 'deepseek-official',
      models: ['deepseek-v4-pro'],
      modelVersion: 'DeepSeek-V4-Pro-0813',
      effectiveFrom: '2026-09-10T04:00:00Z',
      source: 'https://api-docs.deepseek.com/quick_start/pricing',
      rates: { missPer1M: 0.66, hitPer1M: 0.022, writePer1M: 0, outputPer1M: 1.98 },
      tiers: [
        {
          name: 'peak',
          multiplier: 2,
          days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
          windows: [['01:00', '04:00'], ['06:00', '10:00']],
          timezone: 'UTC',
        },
      ],
    },
    {
      provider: 'deepinfra',
      models: ['deepseek-ai/DeepSeek-V4.1-Flash'],
      modelVersion: 'DeepSeek-V4.1-Flash',
      effectiveFrom: '2026-09-11',
      source: 'https://deepinfra.com/deepseek-ai/DeepSeek-V4.1-Flash',
      rates: { missPer1M: 0.2, hitPer1M: 0.006, writePer1M: 0, outputPer1M: 0.6 },
      tiers: [],
    },
    {
      provider: 'deepinfra',
      models: ['deepseek-ai/DeepSeek-V4-Flash-0731'],
      modelVersion: 'DeepSeek-V4-Flash-0731',
      effectiveFrom: '2026-09-11',
      source: 'https://deepinfra.com/deepseek-ai/DeepSeek-V4-Flash-0731',
      rates: { missPer1M: 0.06, hitPer1M: 0.015, writePer1M: 0, outputPer1M: 0.18 },
      tiers: [],
    },
  ],
};

/** Build a provider\0model -> route index once. */
function indexRoutes(pricing) {
  var byKey = {};
  for (var i = 0; i < pricing.routes.length; i += 1) {
    var route = pricing.routes[i];
    for (var j = 0; j < route.models.length; j += 1) {
      byKey[route.provider + '\u0000' + route.models[j]] = route;
    }
  }
  return byKey;
}

/** Local weekday and HH:MM in a named IANA timezone. */
function inZone(timestampMs, timeZone) {
  var fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: timeZone,
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  var parts = fmt.formatToParts(new Date(timestampMs));
  var weekday = '';
  var hour = '';
  var minute = '';
  for (var i = 0; i < parts.length; i += 1) {
    if (parts[i].type === 'weekday') weekday = parts[i].value;
    else if (parts[i].type === 'hour') hour = parts[i].value;
    else if (parts[i].type === 'minute') minute = parts[i].value;
  }
  if (hour === '24') hour = '00';
  return { weekday: weekday, hhmm: hour + ':' + minute };
}

/** Which named tier covers this instant, if any. */
function tierAt(route, timestampMs) {
  var tiers = route.tiers || [];
  for (var i = 0; i < tiers.length; i += 1) {
    var tier = tiers[i];
    if (timestampMs === undefined || timestampMs === null) continue;
    var local = inZone(timestampMs, tier.timezone || 'UTC');
    if (tier.days && tier.days.indexOf(local.weekday) === -1) continue;
    var windows = tier.windows || [];
    for (var w = 0; w < windows.length; w += 1) {
      if (local.hhmm >= windows[w][0] && local.hhmm < windows[w][1]) return tier;
    }
  }
  return undefined;
}

/** Effective per-1M rates for a route at one instant. */
function ratesAt(route, timestampMs) {
  var tier = tierAt(route, timestampMs);
  var multiplier = tier === undefined ? 1 : tier.multiplier;
  return {
    tier: tier === undefined ? 'off-peak' : tier.name,
    multiplier: multiplier,
    missPer1M: route.rates.missPer1M * multiplier,
    hitPer1M: route.rates.hitPer1M * multiplier,
    writePer1M: (route.rates.writePer1M || 0) * multiplier,
    outputPer1M: route.rates.outputPer1M * multiplier,
  };
}

/** 1M threshold used only in documentation of the unit. */
var PER_MILLION = 1000000;

/**
 * Cost one usage bucket.
 * @returns {{microUsd:number, tier:string, modelVersion:string}|undefined}
 *   undefined when the route carries no published price. A refusal is the correct
 *   answer here: a confident wrong rate is worse than a stated gap.
 */
function costOf(usage, byKey, route, timestampMs) {
  var entry = byKey[route.provider + '\u0000' + route.model];
  if (entry === undefined) return undefined;
  var rates = ratesAt(entry, timestampMs);
  var microUsd = Math.round(
    (usage.uncachedInputTokens || 0) * rates.missPer1M +
      (usage.cacheReadTokens || 0) * rates.hitPer1M +
      (usage.cacheWriteTokens || 0) * rates.writePer1M +
      (usage.outputTokens || 0) * rates.outputPer1M,
  );
  return { microUsd: microUsd, tier: rates.tier, modelVersion: entry.modelVersion, route: route };
}

/** Upper bound: every token at the route's highest multiplier. */
function peakCostOf(usage, byKey, route) {
  var entry = byKey[route.provider + '\u0000' + route.model];
  if (entry === undefined) return undefined;
  var max = 1;
  var tiers = entry.tiers || [];
  for (var i = 0; i < tiers.length; i += 1) if (tiers[i].multiplier > max) max = tiers[i].multiplier;
  return Math.round(
    (usage.uncachedInputTokens || 0) * entry.rates.missPer1M * max +
      (usage.cacheReadTokens || 0) * entry.rates.hitPer1M * max +
      (usage.cacheWriteTokens || 0) * (entry.rates.writePer1M || 0) * max +
      (usage.outputTokens || 0) * entry.rates.outputPer1M * max,
  );
}

/** Provider/money formatting for text surfaces. */
function formatUsd(microUsd) {
  if (microUsd === undefined || microUsd === null) return 'n/a';
  var usd = microUsd / MICRO;
  var abs = usd < 0 ? -usd : usd;
  if (abs === 0) return '$0.00';
  if (abs < 0.01) return '$' + usd.toFixed(6);
  if (abs < 1) return '$' + usd.toFixed(4);
  return '$' + usd.toFixed(2);
}

/** Prompt-side tokens the provider billed. */
function billedInput(usage) {
  return (usage.uncachedInputTokens || 0) + (usage.cacheReadTokens || 0) + (usage.cacheWriteTokens || 0);
}

/** Total tokens the GUI's "Usage" figure names. */
function billedTotal(usage) {
  return billedInput(usage) + (usage.outputTokens || 0);
}

/** Cache-hit share of prompt-side tokens, or null when there is no prompt. */
function cacheHitPercent(usage) {
  var prompt = billedInput(usage);
  if (prompt <= 0) return null;
  return Math.round(((usage.cacheReadTokens || 0) / prompt) * 100);
}

/** Normalize one provider usage sample; undefined when it cannot be trusted. */
function normalizeUsage(usage, route) {
  if (usage === undefined || usage === null) return undefined;
  var inputTokens = usage.inputTokens;
  var outputTokens = usage.outputTokens;
  if (!Number.isSafeInteger(inputTokens) || inputTokens < 0) return undefined;
  if (!Number.isSafeInteger(outputTokens) || outputTokens < 0) return undefined;
  var cacheReadTokens = usage.cacheReadTokens;
  var cacheWriteTokens = usage.cacheWriteTokens;
  var reasoningTokens = usage.reasoningTokens;
  var totalTokens = usage.totalTokens;
  if (cacheReadTokens !== undefined && !(Number.isSafeInteger(cacheReadTokens) && cacheReadTokens >= 0)) return undefined;
  if (cacheWriteTokens !== undefined && !(Number.isSafeInteger(cacheWriteTokens) && cacheWriteTokens >= 0)) return undefined;
  if (reasoningTokens !== undefined && !(Number.isSafeInteger(reasoningTokens) && reasoningTokens >= 0 && reasoningTokens <= outputTokens)) return undefined;
  var knownPrompt = inputTokens + (cacheReadTokens || 0) + (cacheWriteTokens || 0);
  if (totalTokens !== undefined) {
    if (!Number.isSafeInteger(totalTokens) || totalTokens < 0) return undefined;
    var exactPrompt = totalTokens - outputTokens;
    if (exactPrompt < 0 || exactPrompt < knownPrompt) return undefined;
    if (cacheReadTokens !== undefined && cacheWriteTokens !== undefined && exactPrompt !== knownPrompt) return undefined;
  } else if (cacheReadTokens === undefined || cacheWriteTokens === undefined) {
    return undefined;
  }
  var out = {
    uncachedInputTokens: inputTokens,
    outputTokens: outputTokens,
    cacheReadTokens: cacheReadTokens || 0,
    cacheWriteTokens: cacheWriteTokens || 0,
  };
  if (reasoningTokens !== undefined) out.reasoningTokens = reasoningTokens;
  return out;
}

/** The last `usage` chunk embedded in an assistant stream, if the stream carries one. */
function streamUsage(stream) {
  var chunks = Array.isArray(stream) ? stream : (stream && (stream.chunks || stream.content));
  if (!Array.isArray(chunks)) return undefined;
  for (var i = chunks.length - 1; i >= 0; i -= 1) {
    if (chunks[i] && chunks[i].type === 'usage' && chunks[i].usage !== undefined) return chunks[i].usage;
  }
  return undefined;
}

/**
 * Fold a session's durable events into per-message priced usage.
 *
 * Unlike the harness's stricter per-turn fold, a step that settled without a
 * usage sample is recorded as a named gap rather than voiding its whole turn: the
 * other steps in that turn were really billed, and hiding them understates spend.
 *
 * @returns {{rows:Array<object>, gaps:number, malformed:Array<string>}}
 */
function foldSession(events, byKey) {
  var rows = [];
  var gaps = 0;
  var malformed = [];
  var note = function (reason) {
    if (malformed.indexOf(reason) === -1) malformed.push(reason);
  };
  var current;

  for (var i = 0; i < events.length; i += 1) {
    var event = events[i];
    if (event.type === 'turn/start') {
      if (current !== undefined) {
        if (current.samples.length === 0) gaps += 1;
        note('turn/start arrived while a turn was open');
      }
      current = { turn: event.data.turn, samples: [], malformed: false };
      continue;
    }
    if (event.type === 'turn/end') {
      if (current === undefined) {
        note('turn/end with no open turn');
      } else {
        flushStep();
        current = undefined;
      }
      continue;
    }
    if (current === undefined) continue;

    if (event.type === 'step/start') {
      flushStep();
      if (event.data.turn !== current.turn) note('step/start for a different turn');
      current.text = false;
      continue;
    }
    if (event.type === 'step/end') {
      flushStep();
      continue;
    }
    if (event.type === 'assistant/message') {
      var usage = normalizeUsage(event.data.usage, undefined);
      var message = event.data.message;
      var source = message && message.source;
      var route =
        source && typeof source.provider === 'string' && source.provider.length > 0 && typeof source.model === 'string' && source.model.length > 0
          ? { provider: source.provider, model: source.model }
          : undefined;
      if (usage === undefined) {
        gaps += 1;
      } else {
        current.samples.push({
          usage: usage,
          route: route,
          time: event.time,
          seq: event.seq,
          final: hasText(message),
        });
      }
      continue;
    }
    if (event.type === 'user/message') {
      current.label = describeUserMessage(event.data);
    }
  }
  if (current !== undefined) {
    flushStep();
    note('the last turn was still open when the log was read');
  }

  function flushStep() {
    // Each assistant settlement is one billed attempt; `current.samples` is the
    // step's list of them, and a step may hold more than one after a retry.
    for (var s = 0; s < current.samples.length; s += 1) {
      var sample = current.samples[s];
      var cost = sample.route === undefined ? undefined : costOf(sample.usage, byKey, sample.route, sample.time);
      var peak = sample.route === undefined ? undefined : peakCostOf(sample.usage, byKey, sample.route);
      rows.push({
        turn: current.turn,
        seq: sample.seq,
        time: sample.time,
        label: current.label || '',
        route: sample.route,
        usage: sample.usage,
        billedTokens: billedTotal(sample.usage),
        microUsd: cost === undefined ? undefined : cost.microUsd,
        peakMicroUsd: peak,
        tier: cost === undefined ? undefined : cost.tier,
        modelVersion: cost === undefined ? undefined : cost.modelVersion,
        final: sample.final === true,
      });
    }
    current.samples = [];
  }

  return { rows: rows, gaps: gaps, malformed: malformed };
}

/** True when an assistant message carries any non-empty text block. */
function hasText(message) {
  var content = message && message.content;
  if (!Array.isArray(content)) return false;
  for (var i = 0; i < content.length; i += 1) {
    var block = content[i];
    if (block && block.type === 'text' && typeof block.text === 'string' && block.text.trim().length > 0) return true;
  }
  return false;
}

/** First line of a user message, for labelling a turn in the report. */
function describeUserMessage(data) {
  if (data === undefined || data === null) return '';
  var content = data.content;
  var text = '';
  if (typeof content === 'string') text = content;
  else if (Array.isArray(content)) {
    for (var i = 0; i < content.length; i += 1) {
      var block = content[i];
      if (block && block.type === 'text' && typeof block.text === 'string') {
        text = text.length === 0 ? block.text : text + ' ' + block.text;
      }
    }
  }
  text = text.replace(/\s+/g, ' ').trim();
  if (text.length > 64) text = text.slice(0, 61) + '...';
  return text;
}

/**
 * Total a folded session per turn and overall.
 * @returns {{turns:Array<object>, session:object, unpriced:Array<object>, gaps:number}}
 */
function totalSession(rows, gaps) {
  var turns = [];
  var byTurn = {};
  var session = { usage: { uncachedInputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, outputTokens: 0 }, microUsd: 0, peakMicroUsd: 0, pricedRows: 0 };
  var unpriced = [];
  var routes = {};

  for (var i = 0; i < rows.length; i += 1) {
    var row = rows[i];
    var key = String(row.turn);
    if (byTurn[key] === undefined) {
      byTurn[key] = {
        turn: row.turn,
        label: row.label,
        usage: { uncachedInputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, outputTokens: 0 },
        microUsd: 0,
        peakMicroUsd: 0,
        attempts: 0,
        unpriced: 0,
        lastWriteMs: 0,
        routeKeys: {},
      };
      turns.push(byTurn[key]);
    }
    var turn = byTurn[key];
    turn.attempts += 1;
    turn.label = row.label.length > turn.label.length ? row.label : turn.label;
    if (row.time !== undefined) turn.lastWriteMs = row.time;
    for (var field in row.usage) turn.usage[field] += row.usage[field];
    for (var field2 in row.usage) session.usage[field2] += row.usage[field2];
    if (row.route !== undefined) {
      var routeKey = row.route.provider + '/' + row.route.model;
      turn.routeKeys[routeKey] = true;
      routes[routeKey] = (routes[routeKey] || 0) + (row.microUsd === undefined ? 0 : 1);
    }
    if (row.microUsd === undefined) {
      turn.unpriced += 1;
      unpriced.push({ turn: row.turn, seq: row.seq, reason: row.route === undefined ? 'no route recorded' : 'no published price for ' + row.route.provider + '/' + row.route.model });
      continue;
    }
    turn.microUsd += row.microUsd;
    turn.peakMicroUsd += row.peakMicroUsd === undefined ? row.microUsd : row.peakMicroUsd;
    session.microUsd += row.microUsd;
    session.peakMicroUsd += row.peakMicroUsd === undefined ? row.microUsd : row.peakMicroUsd;
    session.pricedRows += 1;
  }

  for (var t = 0; t < turns.length; t += 1) {
    turns[t].routeKeys = Object.keys(turns[t].routeKeys);
    turns[t].billedTokens = billedTotal(turns[t].usage);
    turns[t].cacheHitPercent = cacheHitPercent(turns[t].usage);
  }
  session.billedTokens = billedTotal(session.usage);
  session.cacheHitPercent = cacheHitPercent(session.usage);
  session.gaps = gaps;
  session.routes = Object.keys(routes);
  return { turns: turns, session: session, unpriced: unpriced, gaps: gaps };
}

/** Render the /cost report as plain text for the dispatching UI. */
function renderReport(totals, options) {
  var session = totals.session;
  var lines = [];
  var title = options && options.title ? options.title : 'Session cost';
  lines.push(title);
  lines.push('  provider / model   ' + (session.routes.length === 0 ? 'unknown' : session.routes.join(', ')));
  lines.push('  billed tokens      ' + session.billedTokens + '   cache hit ' + (session.cacheHitPercent === null ? 'n/a' : session.cacheHitPercent + '%'));
  lines.push('  uncached input     ' + session.usage.uncachedInputTokens);
  lines.push('  cached input       ' + session.usage.cacheReadTokens);
  if (session.usage.cacheWriteTokens > 0) lines.push('  cache write        ' + session.usage.cacheWriteTokens);
  lines.push('  output             ' + session.usage.outputTokens);
  var upper = session.peakMicroUsd > session.microUsd ? '   (upper bound at peak rates ' + formatUsd(session.peakMicroUsd) + ')' : '';
  lines.push('  SESSION COST       ' + formatUsd(session.microUsd) + upper);
  if (session.gaps > 0) {
    lines.push('  !! ' + session.gaps + ' model call(s) settled without a usage sample.');
    lines.push('     The provider may have billed them. The total above is a lower bound.');
  }
  if (totals.unpriced.length > 0) lines.push('  !! ' + totals.unpriced.length + ' call(s) could not be priced and are excluded.');
  if (options && options.maxTurns !== 0) {
    lines.push('');
    lines.push('  turn   tokens   hit%       cost      upper   when (UTC)');
    var list = totals.turns;
    var max = options && options.maxTurns ? options.maxTurns : list.length;
    var start = list.length > max ? list.length - max : 0;
    if (start > 0) lines.push('  ... ' + start + ' earlier turn(s) omitted');
    for (var i = start; i < list.length; i += 1) {
      var turn = list[i];
      var when = turn.lastWriteMs ? new Date(turn.lastWriteMs).toISOString().replace('T', ' ').slice(0, 19) : '?';
      var upperCell = turn.peakMicroUsd > turn.microUsd ? formatUsd(turn.peakMicroUsd) : formatUsd(turn.microUsd);
      lines.push(
        '  ' + pad(String(turn.turn), 4) + ' ' + pad(String(turn.billedTokens), 8) + ' ' + pad(turn.cacheHitPercent === null ? '?' : String(turn.cacheHitPercent), 5) + ' ' +
          pad(formatUsd(turn.microUsd), 10) + ' ' + pad(upperCell, 10) + ' ' + when +
          (turn.unpriced > 0 ? '  +' + turn.unpriced + ' unpriced' : '') +
          (turn.label.length > 0 ? '  ' + turn.label : ''),
      );
    }
  }
  return lines.join('\n');
}

/** Left-pad to a fixed width. */
function pad(text, width) {
  var out = String(text);
  while (out.length < width) out = ' ' + out;
  return out;
}

// Test surface (unused by the inlined plugin).
export {
  PRICING,
  MICRO,
  PER_MILLION,
  indexRoutes,
  tierAt,
  ratesAt,
  costOf,
  peakCostOf,
  formatUsd,
  billedInput,
  billedTotal,
  cacheHitPercent,
  normalizeUsage,
  streamUsage,
  foldSession,
  totalSession,
  renderReport,
};
