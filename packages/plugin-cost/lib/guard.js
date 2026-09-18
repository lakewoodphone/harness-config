/**
 * GENERATED FILE — do not edit.
 * Built by scripts/build.mjs. The host half is concatenated from
 * src/cost-core.mjs, src/session-log.mjs and src/command.mjs; the spend guard
 * from src/cost-core.mjs, src/session-log.mjs and src/guard.mjs plus its entry
 * src/guard-entry.mjs; the browser half is generated from pricing.json. Edit the
 * sources and run `node scripts/build.mjs`.
 */
import { createRequire } from 'node:module';
function requireAnchor() {
  const base = process.env.USERPROFILE || process.env.HOME || '';
  const home = (process.env.DSH_HOME && process.env.DSH_HOME.length > 0)
    ? process.env.DSH_HOME
    : (base ? base + (base.indexOf('\\') >= 0 ? '\\' : '/') + '.dsh' : '.dsh');
  const sep = home.indexOf('\\') >= 0 ? '\\' : '/';
  return home + sep + 'profiles' + sep + 'web' + sep + 'package.json';
}
const require = createRequire(requireAnchor());
const { existsSync, readFileSync } = require('node:fs');
const { homedir } = require('node:os');
const { join } = require('node:path');
const { zstdDecompressSync } = require('node:zlib');
const Schema = require('@deepseek-ai/schemastery');

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





const ZSTD_MAGIC = 0xfd2fb528;

/**
 * The harness's home directory, in the same precedence the CLI uses.
 * @returns {string} absolute path to the DSH home
 */
function dshHome() {
  return process.env.DSH_HOME ?? join(homedir(), '.dsh');
}

/**
 * Directory name the session store derives from a cwd.
 * Observed: `C:\Users\ezabz\code` -> `--C-Users-ezabz-code--`. The drive colon is
 * dropped rather than replaced, and separators become `-`.
 */
function workspaceDirName(cwd) {
  return `--${cwd.replace(/:/g, '').replace(/[\\/]/g, '-')}--`;
}

/**
 * The session-store directory name for a session id. Root sessions opened from the
 * GUI are stored with a `session-` prefix; other identities are not.
 */
function sessionDirName(sessionId) {
  return /^session-/.test(sessionId) ? sessionId : `session-${sessionId}`;
}

/**
 * Find one session log by id.
 * @param {string} sessionId the live agent's session id
 * @param {string|undefined} cwd the live agent's working directory
 * @returns {{file:string, candidates:string[]}} the first existing log and every path tried
 */
function findSessionLog(sessionId, cwd) {
  const root = join(dshHome(), 'sessions');
  const candidates = [];
  if (typeof cwd === 'string' && cwd.length > 0) {
    candidates.push(join(root, workspaceDirName(cwd), sessionDirName(sessionId), 'session.v3.jsonl.zstd'));
    candidates.push(join(root, workspaceDirName(cwd), sessionId, 'session.v3.jsonl.zstd'));
  }
  return { file: candidates.find((path) => existsSync(path)), candidates };
}

/**
 * Decode a session log into its event records.
 * @param {string} file absolute path to a `.jsonl.zstd` session log
 * @returns {Array<object>} one object per JSONL line
 */
function readSessionLog(file) {
  const buffer = readFileSync(file);
  const offsets = [];
  for (let i = 0; i + 3 < buffer.length; i += 1) {
    if (buffer.readUInt32LE(i) === ZSTD_MAGIC) offsets.push(i);
  }
  const parts = [];
  let frames = 0;
  for (let i = 0; i < offsets.length; i += 1) {
    const end = i + 1 < offsets.length ? offsets[i + 1] : buffer.length;
    try {
      parts.push(zstdDecompressSync(buffer.subarray(offsets[i], end)));
      frames += 1;
    } catch {
      // Torn tail frame: legal, and the only frame allowed to be incomplete.
    }
  }
  if (frames === 0) throw new Error(`no decodable zstd frame in ${file}`);
  const events = [];
  for (const line of Buffer.concat(parts).toString('utf8').split('\n')) {
    if (line.length === 0) continue;
    try {
      events.push(JSON.parse(line));
    } catch {
      // A torn write can leave one partial line; skip it and keep the rest.
    }
  }
  return events;
}




const DAY_MS = 86400000;

/**
 * Defaults. These are the protective values `docs/mesh/96-gateway-at-scale.md` §5
 * justifies from measurement, and every one of them is a one-line change in
 * `settings/base.yaml` or in the row's `config`.
 *
 * $35 / $80 / $150 is deliberately NOT the $25 / $35 / $50 that doc 65 first
 * proposed: $50 is 44 minutes of a 55-agent fleet at the measured $68/hour, and
 * a ceiling crossed in the first hour of normal work gets raised by accident.
 * Above $150 the design already knows what to do — refuse, block the turn,
 * resume tomorrow.
 */
const DEFAULTS = {
  warnUsd: 35,
  fanoutUsd: 80,
  ceilingUsd: 150,
  concurrencyCap: 12,
  onInternalError: 'closed', // 'closed' refuses the step; 'open' allows it and says so
  seedFromLogs: true,
  seedLookbackHours: 24,
  stateFile: '', // '' -> <dshHome>/spend-guard/day.json
  sessionsRoot: '', // '' -> <dshHome>/sessions
};

/** The money limits, in USD. */
const MONEY_KEYS = ['warnUsd', 'fanoutUsd', 'ceilingUsd'];

/** Every key the guard understands; anything else is named and ignored. */
const KNOWN_KEYS = [...MONEY_KEYS, 'concurrencyCap', 'onInternalError', 'seedFromLogs', 'seedLookbackHours', 'stateFile', 'sessionsRoot'];

/** Namespace of the shared settings block this guard owns. */
const SETTINGS_NAMESPACE = 'spend-guard';

/** True for a finite number that can be a money limit, an hour count or a cap. */
function isLimit(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

/**
 * Pick the effective limits from the composition row's `config`, which the
 * settings provider has already merged: schema defaults, then this row as the
 * `base` layer, then the user layer in `settings.yaml`. A profile with no
 * settings provider simply gets the row's config.
 * @param {object} config the composition entry's config
 * @returns {object} limits and switches with every default applied
 */
function resolveLimits(config) {
  const source = config === undefined || config === null ? {} : config;
  const out = {
    onInternalError: source.onInternalError === 'open' ? 'open' : DEFAULTS.onInternalError,
    seedFromLogs: source.seedFromLogs !== false,
    stateFile: typeof source.stateFile === 'string' ? source.stateFile : DEFAULTS.stateFile,
    sessionsRoot: typeof source.sessionsRoot === 'string' ? source.sessionsRoot : DEFAULTS.sessionsRoot,
    concurrencyCap: Number.isInteger(source.concurrencyCap) && source.concurrencyCap >= 0 ? source.concurrencyCap : DEFAULTS.concurrencyCap,
    seedLookbackHours: isLimit(source.seedLookbackHours) ? source.seedLookbackHours : DEFAULTS.seedLookbackHours,
  };
  for (const key of MONEY_KEYS) out[key] = isLimit(source[key]) ? source[key] : DEFAULTS[key];
  // An unknown key must never silently disable a limit: it is reported instead.
  out.unknownKeys = Object.keys(source).filter((key) => KNOWN_KEYS.indexOf(key) === -1);
  return out;
}

/** Micro-USD limits derived from the dollar ones, for the counter comparison. */
function microLimits(limits) {
  return {
    warnMicro: Math.round(limits.warnUsd * MICRO),
    fanoutMicro: Math.round(limits.fanoutUsd * MICRO),
    ceilingMicro: Math.round(limits.ceilingUsd * MICRO),
  };
}

/** Start of the UTC day containing `ms`. The card's tiers are UTC, so the day is too. */
function utcDayStart(ms) {
  return Math.floor(ms / DAY_MS) * DAY_MS;
}

/**
 * The decision, as a pure function of the day's counter and the limits.
 *
 * `reject` on money wins over everything: past the hard ceiling nothing new
 * starts for any reason. `fanout` and `concurrency` are warnings, not vetoes —
 * a running turn is never interrupted, and the step is admitted with a notice.
 *
 * @param {number} dayMicro today's spend in micro-USD
 * @param {{warnMicro:number,fanoutMicro:number,ceilingMicro:number}} limits
 * @param {{generating:number,cap:number,selfGenerating:boolean}} [counts]
 * @returns {{verdict:'ok'|'warn'|'fanout'|'concurrency'|'reject',rejectReason:string,noticeClass:string}}
 */
function decide(dayMicro, limits, counts) {
  if (dayMicro >= limits.ceilingMicro) return { verdict: 'reject', rejectReason: 'daily ceiling', noticeClass: 'ceiling' };
  const cap = counts === undefined ? 0 : counts.cap;
  const generating = counts === undefined ? 0 : counts.generating;
  const self = counts === undefined ? false : counts.selfGenerating === true;
  if (cap > 0 && generating >= cap && !self) return { verdict: 'reject', rejectReason: 'concurrency cap', noticeClass: 'concurrency' };
  if (dayMicro >= limits.fanoutMicro) return { verdict: 'fanout', rejectReason: '', noticeClass: 'fanout' };
  if (cap > 0 && generating >= cap - 1 && !self) return { verdict: 'concurrency', rejectReason: '', noticeClass: 'concurrency' };
  if (dayMicro >= limits.warnMicro) return { verdict: 'warn', rejectReason: '', noticeClass: 'warn' };
  return { verdict: 'ok', rejectReason: '', noticeClass: '' };
}

/**
 * The dearest rate on the card, per token class, with the card's highest
 * multiplier applied. Used ONLY to bound a request whose route is not priced:
 * an unpriced route must be charged too much, never too little.
 *
 * With today's card it resolves to `deepseek-v4-pro` at peak — $1.32 per 1M
 * uncached input and $3.96 per 1M output, 8.8x and 6.6x the flash rate.
 * @param {object} pricing the rate table, defaulting to this package's card
 * @returns {{missPer1M:number,hitPer1M:number,writePer1M:number,outputPer1M:number,provider:string,model:string,multiplier:number}}
 */
function dearestRates(pricing) {
  const card = pricing === undefined ? PRICING : pricing;
  const dearest = { missPer1M: 0, hitPer1M: 0, writePer1M: 0, outputPer1M: 0, provider: '', model: '', multiplier: 1 };
  for (const route of (card === undefined ? [] : card.routes) || []) {
    let multiplier = 1;
    for (const tier of route.tiers || []) if (tier.multiplier > multiplier) multiplier = tier.multiplier;
    for (const key of ['missPer1M', 'hitPer1M', 'writePer1M', 'outputPer1M']) {
      const scaled = (route.rates[key] || 0) * multiplier;
      if (scaled > dearest[key]) {
        dearest[key] = scaled;
        dearest.provider = route.provider;
        dearest.model = (route.models || [])[0] || '';
        dearest.multiplier = multiplier;
      }
    }
  }
  return dearest;
}

/** The route a usage sample was served by, or the deployment default when unnamed. */
function routeOf(message, fallbackRoute) {
  const source = message === undefined || message === null ? undefined : message.source;
  if (source !== undefined && source !== null && typeof source.provider === 'string' && source.provider.length > 0 && typeof source.model === 'string' && source.model.length > 0) {
    return { provider: source.provider, model: source.model, named: true };
  }
  const fallback = fallbackRoute || (PRICING === undefined ? undefined : PRICING.defaultRoute) || { provider: 'deepseek-official', model: 'deepseek-flash' };
  return { provider: fallback.provider, model: fallback.model, named: false };
}

/** One model-facing notice, as a user message the loop admits to the step. */
function notice(text) {
  return { source: { kind: 'user' }, content: [{ type: 'text', text }] };
}

/**
 * Build the guard plugin.
 *
 * A factory, so the guard can be unit-tested and demonstrated against an
 * isolated state directory and an isolated sessions root — without an engine,
 * and without touching the owner's own counters.
 *
 * The mandatory dependency is the price core: `{PRICING, indexRoutes, costOf,
 * normalizeUsage, MICRO, readSessionLog, dshHome}`. `lib/guard.js` passes this
 * package's own sources; a test passes the same ones explicitly, which is what
 * makes the test test the shipped arithmetic.
 *
 * @param {object} deps the price core, plus optional I/O and clock overrides
 * @returns {{name:string, apply:Function, decide:Function, resolveLimits:Function, dearestRates:Function, guardState:Function}}
 */
function createGuard(deps = {}) {
  const core = deps.core;
  if (core === undefined || core.PRICING === undefined || core.indexRoutes === undefined || core.costOf === undefined || core.normalizeUsage === undefined || core.MICRO === undefined) {
    throw new Error('spend-guard: the price core is missing, so no cost can be computed. Refusing to construct (pass {core: {PRICING, indexRoutes, costOf, normalizeUsage, MICRO}}).');
  }
  const pricing = core.PRICING;
  const micro = core.MICRO;
  const byKey = core.indexRoutes(pricing);
  const home = deps.dshHome || core.dshHome || dshHome;
  const reader = deps.readSessionLog || core.readSessionLog || readSessionLog;
  const clock = deps.now || (() => Date.now());
  const dearest = dearestRates(pricing);
  const dearestZero = dearest.missPer1M === 0 && dearest.hitPer1M === 0 && dearest.outputPer1M === 0;

  /** The mounted guard's own state. One per engine; never shared with a test. */
  const state = {
    day: 0,
    micro: 0,
    requests: 0,
    unpriced: 0,
    gaps: [],
    seedRequests: 0,
    seeding: false,
    watermarkMs: 0,
    generating: 0,
    cap: 0,
    lastVerdict: 'ok',
    lastReason: '',
    lastStep: 0,
    reported: '',
    limits: undefined,
    file: '',
    started: false,
    persistError: '',
  };

  /**
   * Move the counter to a new UTC day.
   * @returns {boolean} true when the day actually rolled
   */
  function roll(atMs) {
    const day = utcDayStart(atMs);
    if (day === state.day) return false;
    const rolled = state.day !== 0;
    state.day = day;
    state.micro = 0;
    state.requests = 0;
    state.unpriced = 0;
    state.seedRequests = 0;
    state.gaps = [];
    state.watermarkMs = 0;
    state.reported = '';
    return rolled;
  }

  /**
   * Price one usage sample against the card, exactly, at the event's own instant.
   * A route that is not on the card is BOUNDED at the dearest rate, never
   * treated as free.
   * @returns {{micro:number,priced:boolean,reason:string}}
   */
  function priceSample(usage, route, timeMs) {
    const normalized = core.normalizeUsage(usage, route);
    if (normalized === undefined) return { micro: 0, priced: false, reason: 'the usage sample failed validation, so it cannot be priced' };
    const cost = core.costOf(normalized, byKey, route, timeMs);
    if (cost !== undefined) return { micro: cost.microUsd, priced: true, reason: '' };
    const bound = Math.round(
      (normalized.uncachedInputTokens || 0) * dearest.missPer1M +
        (normalized.cacheReadTokens || 0) * dearest.hitPer1M +
        (normalized.cacheWriteTokens || 0) * dearest.writePer1M +
        (normalized.outputTokens || 0) * dearest.outputPer1M,
    );
    return { micro: bound, priced: false, reason: `${route.provider}/${route.model} is not on the price card, so it was charged at the dearest card rate` };
  }

  /**
   * Add one priced sample to the day. Every path into the counter goes through
   * here, so the live stream and the seed cannot disagree about arithmetic.
   */
  function count(usage, message, timeMs) {
    const route = routeOf(message, pricing.defaultRoute);
    const priced = priceSample(usage, { provider: route.provider, model: route.model }, timeMs);
    state.micro += priced.micro;
    state.requests += 1;
    if (!priced.priced) {
      state.unpriced += 1;
      if (state.gaps.length < 32 && state.gaps.indexOf(priced.reason) === -1) state.gaps.push(priced.reason);
    }
    if (timeMs > state.watermarkMs) state.watermarkMs = timeMs;
    return priced;
  }

  /**
   * Read today's part of the durable logs once, so a restart resumes the day.
   *
   * This is the ONLY scan in the guard and it runs at activation, never per
   * step: a scan of today's logs measured 15.5 s (`docs/mesh/65-spend-guard.md`
   * §1.5), three orders of magnitude too slow to sit in front of a request.
   */
  async function seed(log) {
    const fs = await import('node:fs/promises');
    const readdir = deps.readdir || fs.readdir;
    const stat = deps.stat || fs.stat;
    const limits = state.limits;
    const root = limits.sessionsRoot.length > 0 ? limits.sessionsRoot : join(home(), 'sessions');
    const since = Math.max(state.day, clock() - limits.seedLookbackHours * 3600000);
    let scanned = 0;
    let decoded = 0;
    let unreadable = 0;
    for (const workspace of await readdir(root, { withFileTypes: true })) {
      if (!workspace.isDirectory()) continue;
      for (const session of await readdir(join(root, workspace.name), { withFileTypes: true })) {
        if (!session.isDirectory()) continue;
        const file = join(root, workspace.name, session.name, 'session.v3.jsonl.zstd');
        try {
          const info = await stat(file);
          // Sound pre-filter: logs are append-only and events are chronological,
          // so a log last written before the window holds no event inside it.
          if (info.mtimeMs < since) continue;
          scanned += 1;
          const events = reader(file);
          decoded += 1;
          for (const event of events) {
            if (event === undefined || event.type !== 'assistant/message') continue;
            const at = event.time;
            if (!Number.isFinite(at) || at < state.day || at <= state.watermarkMs) continue;
            const usage = event.data === undefined ? undefined : event.data.usage;
            if (usage === undefined) continue;
            count(usage, event.data.message, at);
            state.seedRequests += 1;
          }
        } catch (error) {
          unreadable += 1;
          if (state.gaps.length < 32) state.gaps.push(`${session.name}: ${error instanceof Error ? error.message : String(error)}`);
        }
      }
    }
    state.seeding = false;
    log(
      `spend-guard: seeded ${state.seedRequests} request(s) from ${decoded}/${scanned} log(s) written since ${new Date(since).toISOString()} ` +
        `(${unreadable} unreadable); day so far $${(state.micro / micro).toFixed(4)} — a LOWER BOUND for this machine, before this engine's own live traffic`,
    );
  }

  /** Read the persisted state, so a restart continues the day instead of resetting it. */
  async function restore(log) {
    try {
      const fs = await import('node:fs/promises');
      const saved = JSON.parse(await fs.readFile(state.file, 'utf8'));
      if (saved === null || typeof saved !== 'object') throw new Error('the state file is not an object');
      state.micro = Number.isFinite(saved.micro) ? saved.micro : 0;
      state.requests = Number.isFinite(saved.requests) ? saved.requests : 0;
      state.unpriced = Number.isFinite(saved.unpriced) ? saved.unpriced : 0;
      state.watermarkMs = Number.isFinite(saved.watermarkMs) ? saved.watermarkMs : 0;
      state.day = Number.isFinite(saved.day) ? saved.day : 0;
      log(`spend-guard: resumed ${state.requests} request(s) / $${(state.micro / micro).toFixed(4)} from ${state.file}`);
    } catch (error) {
      // A missing file is the first run, which is not a fault. Anything else is
      // a gap that must be said out loud, because the day then starts from zero.
      const missing = error !== null && error !== undefined && error.code === 'ENOENT';
      if (!missing) {
        state.gaps.push(`the state file could not be read: ${error instanceof Error ? error.message : String(error)}`);
        log(`spend-guard: WARNING could not read ${state.file} (${error instanceof Error ? error.message : String(error)}); today restarts from the logs and is a LOWER BOUND`);
      }
    }
  }

  /** Write the state. Atomic, and never fatal: the in-memory counter is the truth. */
  function persist(log) {
    const payload = JSON.stringify(
      {
        day: state.day,
        micro: state.micro,
        requests: state.requests,
        unpriced: state.unpriced,
        watermarkMs: state.watermarkMs,
        seedRequests: state.seedRequests,
        lastVerdict: state.lastVerdict,
        lastReason: state.lastReason,
        lastStep: state.lastStep,
        generatingAtLastDecision: state.generating,
        limitsUsd: state.limits === undefined ? undefined : { warn: state.limits.warnUsd, fanout: state.limits.fanoutUsd, ceiling: state.limits.ceilingUsd, concurrencyCap: state.limits.concurrencyCap },
        writtenAt: new Date(clock()).toISOString(),
      },
      null,
      1,
    );
    const write = async () => {
      const fs = await import('node:fs/promises');
      const temp = `${state.file}.tmp`;
      await fs.mkdir(state.file.replace(/[\\/][^\\/]+$/, ''), { recursive: true });
      await fs.writeFile(temp, payload);
      await fs.rename(temp, state.file);
      state.persistError = '';
    };
    write().catch((error) => {
      state.persistError = error instanceof Error ? error.message : String(error);
      log(`spend-guard: WARNING could not persist state to ${state.file}: ${state.persistError}`);
    });
  }

  /** How many agents are generating right now, and whether this step's agent is one of them. */
  function countGenerating(ctx, agent) {
    const agents = typeof ctx.get === 'function' ? ctx.get('agents') : undefined;
    if (agents === undefined || typeof agents.list !== 'function') return { generating: state.generating, available: false, self: true };
    let generating = 0;
    let self = false;
    const selfId = agent === undefined || agent === null || agent.id === undefined ? '' : String(agent.id);
    for (const live of agents.list()) {
      if (live === undefined || live === null || live.status !== 'running') continue;
      generating += 1;
      if (selfId.length > 0 && live.id !== undefined && String(live.id) === selfId) self = true;
    }
    return { generating, available: true, self };
  }

  /**
   * Cordis plugin entry.
   * @param {object} ctx the mounted context
   * @param {object} config the composition row's config, already merged with settings
   */
  function apply(ctx, config = {}) {
    const limits = resolveLimits(config);
    const log = (line) => {
      if (typeof deps.logger === 'function') deps.logger(line);
      else if (ctx.logger !== undefined && typeof ctx.logger.info === 'function') ctx.logger.info(line);
    };
    const warn = (line) => {
      if (typeof deps.logger === 'function') deps.logger(line);
      else if (ctx.logger !== undefined && typeof ctx.logger.warn === 'function') ctx.logger.warn(line);
      else if (ctx.logger !== undefined && typeof ctx.logger.error === 'function') ctx.logger.error(line);
      else if (typeof console !== 'undefined' && typeof console.error === 'function') console.error(line);
    };

    // ── the card first: no card means no enforcement and no pretence ────────
    if (!Array.isArray(pricing.routes) || pricing.routes.length === 0) {
      throw new Error('spend-guard: the price card is missing or holds no routes, so no ceiling can be computed. Refusing to mount rather than enforcing against an assumed zero (the card is packages/plugin-cost/pricing.json).');
    }
    if (dearestZero && !isLimit(config.ceilingUsd)) {
      throw new Error('spend-guard: every rate on the price card is zero, so an unpriced route could not be bounded. Refusing to mount (the card is packages/plugin-cost/pricing.json).');
    }

    state.limits = limits;
    state.cap = limits.concurrencyCap;
    state.file = limits.stateFile.length > 0 ? limits.stateFile : join(home(), 'spend-guard', 'day.json');
    state.day = utcDayStart(clock());
    state.seeding = limits.seedFromLogs;

    /**
     * Offer this guard's policy to the settings provider as the `spend-guard`
     * namespace, so `settings/base.yaml` — and any per-machine file — is honoured
     * and the repository stays the single source of truth for the values. If the
     * provider or the schema class is absent, the row's own config stands.
     */
    let source = () => config;
    const settings = typeof ctx.get === 'function' ? ctx.get('settings') : undefined;
    const Schema = deps.Schema;
    if (settings !== undefined && typeof settings.installSection === 'function' && Schema !== undefined) {
      try {
        settings.installSection(ctx, SETTINGS_NAMESPACE, deps.schema === undefined ? policySchema(Schema) : deps.schema, config, {
          setSource: (reader) => {
            source = reader;
          },
          onChange: () => {
            const next = resolveLimits(source());
            const changed =
              state.limits === undefined ||
              next.warnUsd !== state.limits.warnUsd ||
              next.fanoutUsd !== state.limits.fanoutUsd ||
              next.ceilingUsd !== state.limits.ceilingUsd ||
              next.concurrencyCap !== state.limits.concurrencyCap;
            state.limits = next;
            state.cap = next.concurrencyCap;
            if (changed) warn(`spend-guard: limits now warn $${next.warnUsd} / fan-out $${next.fanoutUsd} / ceiling $${next.ceilingUsd}, concurrency cap ${next.concurrencyCap}`);
          },
        });
      } catch (error) {
        warn(`spend-guard: could not register the "${SETTINGS_NAMESPACE}" settings namespace (${error instanceof Error ? error.message : String(error)}); the row config is in force`);
      }
    }
    if (limits.unknownKeys.length > 0) warn(`spend-guard: ignoring unknown config key(s): ${limits.unknownKeys.join(', ')}`);

    // ── count: this engine's own traffic, from the live event stream ────────
    ctx.on('session/event', (_session, event) => {
      if (event === undefined || event.type !== 'assistant/message') return;
      const usage = event.data === undefined ? undefined : event.data.usage;
      if (usage === undefined || !Number.isFinite(event.time)) return;
      try {
        // `time` is the event's own write instant, and that instant is what
        // decides peak or off-peak. The watermark excludes anything the seed
        // already counted, so a restart cannot charge the same request twice.
        if (event.time <= state.watermarkMs) return;
        roll(event.time);
        count(usage, event.data.message, event.time);
        persist(log);
      } catch (error) {
        state.gaps.push(`the live count failed: ${error instanceof Error ? error.message : String(error)}`);
        warn(`spend-guard: WARNING could not price a live usage sample (${error instanceof Error ? error.message : String(error)}); today's figure is a LOWER BOUND`);
      }
    });

    // ── enforce: once per step, before anything is billed ───────────────────
    ctx.on('agent/pre-step', async (payload, next) => {
      const step = payload === undefined ? undefined : payload.step;
      const agent = payload === undefined ? undefined : payload.agent;
      let verdict;
      let counts;
      try {
        roll(clock());
        counts = countGenerating(ctx, agent);
        state.generating = counts.generating;
        const live = state.limits === undefined ? limits : state.limits;
        verdict = decide(state.micro, microLimits(live), { generating: counts.generating, cap: state.cap, selfGenerating: counts.self });
      } catch (error) {
        // The guard's own failure is the one case where the policy is explicit.
        if (limits.onInternalError === 'closed') {
          warn(`spend-guard: INTERNAL ERROR, refusing the step because onInternalError is 'closed' (fail closed): ${error instanceof Error ? error.message : String(error)}`);
          return { kind: 'reject' };
        }
        warn(`spend-guard: INTERNAL ERROR, allowing the step because onInternalError is 'open' (fail open): ${error instanceof Error ? error.message : String(error)}`);
        return next();
      }

      const live = state.limits === undefined ? limits : state.limits;
      state.lastStep = Number.isFinite(step) ? step : 0;
      if (verdict.verdict === 'reject') {
        state.lastVerdict = 'reject';
        state.lastReason = verdict.rejectReason;
        state.reported = 'reject';
        const detail =
          verdict.rejectReason === 'daily ceiling'
            ? `daily ceiling reached: $${(state.micro / micro).toFixed(2)} of $${live.ceilingUsd}`
            : `concurrency cap reached: ${counts.generating} agent(s) generating, cap ${state.cap}`;
        warn(`spend-guard: ${detail}; refusing step ${step}. Nothing is billed for the refused step and the turn closes blocked.`);
        persist(log);
        return { kind: 'reject' };
      }

      const downstream = await next();
      if (downstream === undefined || downstream === null || downstream.kind !== 'enter') return downstream;

      state.lastVerdict = verdict.verdict;
      state.lastReason = verdict.noticeClass;
      // One notice per escalation, not one per step: a notice on every step of a
      // long turn would itself be a cost. A verdict of `ok` re-arms the notice,
      // so dropping back below a threshold and crossing it again says so again.
      if (verdict.verdict === 'ok') state.reported = '';
      if (verdict.verdict === 'ok' || state.reported === verdict.verdict) return downstream;
      state.reported = verdict.verdict;
      const text = [
        `spend-guard: today's DSH spend on this machine is $${(state.micro / micro).toFixed(2)} of a $${live.ceilingUsd} daily ceiling`,
        verdict.noticeClass === 'fanout'
          ? ` — past the $${live.fanoutUsd} fan-out threshold, so start no new subagents or workflows. Work already running continues.`
          : verdict.noticeClass === 'concurrency'
            ? ` — ${counts.generating} agent(s) are generating and the cap is ${state.cap}, so the next new agent will be refused. Start no new fan-out.`
            : ` — past the $${live.warnUsd} warn threshold. The dominant term is re-reading a long session's context: prefer finishing a coherent piece and handing off to a fresh session over continuing this one.`,
        state.seeding ? ' (still seeding today from disk, so this figure is a LOWER BOUND)' : '',
        state.unpriced > 0 ? ` (${state.unpriced} request(s) had no published rate and were charged at the dearest card rate)` : '',
      ].join('');
      warn(text);
      return { ...downstream, messages: [...downstream.messages, notice(text)] };
    });

    // ── start: restore, seed, then say what is in force ─────────────────────
    log(
      `spend-guard: mounted. warn $${limits.warnUsd} / fan-out $${limits.fanoutUsd} / ceiling $${limits.ceilingUsd} per UTC day, ` +
        `concurrency cap ${limits.concurrencyCap} generating agent(s), fail ${limits.onInternalError}, state ${state.file}, ` +
        `dearest card rate ${dearest.provider}/${dearest.model} at ${dearest.multiplier}x is what bounds an unpriced route`,
    );
    (async () => {
      await restore(log);
      roll(clock());
      if (limits.seedFromLogs) {
        try {
          await seed(log);
        } catch (error) {
          state.seeding = false;
          state.gaps.push(`the seed failed: ${error instanceof Error ? error.message : String(error)}`);
          warn(`spend-guard: could not seed from the session logs (${error instanceof Error ? error.message : String(error)}); today counts this engine's live traffic only and is a LOWER BOUND`);
        }
      } else {
        state.seeding = false;
      }
      state.started = true;
      persist(log);
    })();
    ctx.effect(() => () => persist(log));
  }

  return {
    name: 'spend-guard',
    apply,
    decide,
    resolveLimits,
    microLimits,
    utcDayStart,
    dearestRates,
    priceSample,
    /** The live counters, for a test or an operator readout. Never the durable truth. */
    guardState: () => ({ ...state, gaps: state.gaps.slice() }),
  };
}

/**
 * The policy schema, registered with the settings provider so the
 * `spend-guard:` block in `settings.yaml` (merged from `settings/base.yaml`) is
 * validated, and so its UI can render one field per limit.
 * @param {object} Schema the schemastery class, taken from the runtime
 * @returns {object} a schemastery object schema
 */
function policySchema(Schema) {
  const money = (description) => Schema.number().min(0).default(undefined).description(description);
  return Schema.object({
    warnUsd: money('Append a one-line notice to the step at this many USD in a UTC day'),
    fanoutUsd: money('Past this, new subagents and workflows are refused; running work continues'),
    ceilingUsd: money('At this many USD, refuse new billable steps; the turn closes blocked'),
    concurrencyCap: money('Refuse a new generating agent past this many on this machine'),
    onInternalError: Schema.union(['closed', 'open']).description("'closed' refuses the step when the guard itself fails; 'open' allows it"),
    seedFromLogs: Schema.boolean().description('Seed the day once at mount from the durable session logs, which is a lower bound'),
    seedLookbackHours: money('How far back the one seed scan may look'),
    stateFile: Schema.string().description('Empty means <DSH_HOME>/spend-guard/day.json'),
    sessionsRoot: Schema.string().description('Empty means <DSH_HOME>/sessions'),
  });
}

// Test surface, and the source of the mount: everything the guard entry in
// `src/guard-entry.mjs` and the suites in `test/` bind.


/** The Cordis plugin name. */
const name = 'spend-guard';

/**
 * No hard dependencies. The guard reads the session firehose, the agent
 * registry and the settings provider with `ctx.get()` behind absence checks, so
 * a profile that has none of them still mounts and still enforces the money
 * cap — and a missing optional service can never stop an engine booting.
 */
const inject = [];

/** One guard instance per process. Built at activation so limits come from config. */
let instance;

/**
 * Mount the guard.
 * @param {object} ctx the mounted plugin context
 * @param {object} config the composition row's config, merged with settings by
 *   the settings provider before this runs
 */
function apply(ctx, config = {}) {
  if (instance !== undefined) {
    // Reachable only if a composition mounts this module twice. Said out loud
    // rather than left to double-count.
    if (ctx.logger !== undefined && typeof ctx.logger.warn === 'function') {
      ctx.logger.warn('spend-guard: a second guard instance was mounted; the first one stays authoritative and this one only reports its own state');
    }
  }
  const guard = createGuard({
    core: { PRICING, MICRO, indexRoutes, costOf, normalizeUsage, readSessionLog, dshHome },
    Schema,
  });
  if (instance === undefined) instance = guard;
  guard.apply(ctx, config);
}


export { name, inject, apply };
