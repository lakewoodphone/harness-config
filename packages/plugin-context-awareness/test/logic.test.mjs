/**
 * The pure half of dsh-plugin-context-awareness: banding, formatting, and the text.
 *
 * What is NOT tested here is the wiring (`tools/post-execute`, `session/event`,
 * `tokenMeter`) — that is only true when a real session runs, which is what
 * `scripts/verify-context-awareness.mjs` and a headless session prove. A test that
 * mocked those would prove the mock.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  bandIndexFor,
  bandNameFor,
  bandText,
  compactedText,
  deepFreeze,
  describeReading,
  formatTokens,
  normalizeBands,
  noticeMessage,
  orientationText,
  percentOf,
  statusText,
} from '../lib/index.js';

test('bands: defaults are three increasing fractions and the top band is beyond the last', () => {
  const bands = normalizeBands(undefined);
  assert.deepEqual(bands, [0.35, 0.55, 0.7]);
  assert.equal(bandIndexFor(0, bands), 0);
  assert.equal(bandIndexFor(0.34, bands), 0);
  assert.equal(bandIndexFor(0.35, bands), 1);
  assert.equal(bandIndexFor(0.69, bands), 2);
  assert.equal(bandIndexFor(0.7, bands), 3);
  assert.equal(bandIndexFor(0.99, bands), 3);
  assert.equal(bandNameFor(0), 'comfortable');
  assert.equal(bandNameFor(3), 'critical');
  assert.equal(bandNameFor(99), 'critical');
});

test('bands: a bad authored value fails loud instead of silently defaulting', () => {
  assert.throws(() => normalizeBands([]), /non-empty/);
  assert.throws(() => normalizeBands([0.5, 0.4]), /strictly increasing/);
  assert.throws(() => normalizeBands([0]), /strictly between 0 and 1/);
  assert.throws(() => normalizeBands([1]), /strictly between 0 and 1/);
  assert.throws(() => normalizeBands(['nope']), /strictly between 0 and 1/);
});

test('format: grouped integers, and no locale dependence', () => {
  assert.equal(formatTokens(0), '0');
  assert.equal(formatTokens(999), '999');
  assert.equal(formatTokens(1000), '1,000');
  assert.equal(formatTokens(792576), '792,576');
  assert.equal(formatTokens(1234567), '1,234,567');
  assert.equal(formatTokens(undefined), '0');
});

test('percent: whole numbers, clamped, and never NaN', () => {
  assert.equal(percentOf(41230, 1000000), 4);
  assert.equal(percentOf(700000, 1000000), 70);
  assert.equal(percentOf(999999, 1000000), 100);
  assert.equal(percentOf(2000000, 1000000), 100);
  assert.equal(percentOf(0, 1000000), 0);
  assert.equal(percentOf(1, 0), 0);
});

test('reading: the fire point is the real threshold, not a guess', () => {
  const reading = describeReading({ tokens: 41230, window: 1000000, band: 'comfortable', thresholdRatio: 0.7, exact: true });
  assert.equal(reading.percent, 4);
  assert.equal(reading.fireAt, 700000);
  assert.equal(reading.exact, true);
});

test('orientation names the number, the band, the fire point, and forbids the panic', () => {
  const text = orientationText(describeReading({ tokens: 41230, window: 1000000, band: 'comfortable', thresholdRatio: 0.7, exact: true }));
  assert.match(text, /41,230 of 1,000,000 tokens \(4%\)/);
  assert.match(text, /band comfortable/);
  assert.match(text, /compaction fires near 700,000/);
  assert.match(text, /Never announce that your context is spent/);
  assert.match(text, /context_status/);
  assert.match(text, /ps_search what=sessions/);
  assert.doesNotMatch(text, /estimated from the request surface/, 'an exact reading must not be labelled an estimate');
});

test('orientation says so when the number is only an estimate', () => {
  const text = orientationText(describeReading({ tokens: 10, window: 1000, band: 'working', thresholdRatio: 0.7, exact: false, basis: 'estimated' }));
  assert.match(text, /estimated from the request surface/);
});

test('band texts carry the number and the instruction, and never a false reassurance', () => {
  const tightening = bandText(describeReading({ tokens: 561000, window: 1000000, band: 'tightening', thresholdRatio: 0.7, exact: true }));
  assert.match(tightening, /56%/);
  assert.match(tightening, /write down anything expensive to lose now/);

  const critical = bandText(describeReading({ tokens: 731000, window: 1000000, band: 'critical', thresholdRatio: 0.7, exact: true }));
  assert.match(critical, /73%/);
  assert.match(critical, /Do not restart the session to "save" context/);

  const comfortable = bandText(describeReading({ tokens: 1000, window: 1000000, band: 'comfortable', thresholdRatio: 0.7, exact: true }));
  assert.match(comfortable, /You have room; keep working\./);
});

test('compaction text: what survives, what is at risk, where the transcript is, and no restart', () => {
  const text = compactedText({
    shadowedTokens: 288000,
    reading: describeReading({ tokens: 41000, window: 1000000, band: 'comfortable', thresholdRatio: 0.7, exact: true }),
  });
  assert.match(text, /a checkpoint: a summary, not a transcript/);
  assert.match(text, /288,000 tokens/);
  assert.match(text, /41,000 of 1,000,000 \(4%\)/);
  assert.match(text, /treat anything you know only from the checkpoint as unverified/);
  assert.match(text, /Nothing was destroyed/);
  assert.match(text, /do not restart/);
});

test('compaction text omits the arithmetic when the engine reported no span', () => {
  const text = compactedText({
    shadowedTokens: 0,
    reading: describeReading({ tokens: 0, window: 1000000, band: 'comfortable', thresholdRatio: 0.7, exact: false }),
  });
  assert.doesNotMatch(text, /The engine replaced/);
  assert.match(text, /Nothing was destroyed/);
});

test('status text distinguishes a session that never compacted from one that did', () => {
  const reading = describeReading({ tokens: 200000, window: 1000000, band: 'working', thresholdRatio: 0.7, exact: true });
  assert.match(statusText({ reading, compactions: 0 }), /No compaction has happened in this session\./);
  const after = statusText({ reading, compactions: 2, sinceCompactionMs: 124000 });
  assert.match(after, /2 compaction\(s\) in this session; the last was 124s ago/);
});

test('a notice is a frozen, marked user message — never an unlabelled user prompt', () => {
  const message = noticeMessage('hello', 'context 4% · comfortable');
  assert.equal(message.role, 'user');
  assert.equal(message.source.kind, 'context-awareness');
  assert.equal(message.source.form, 'notice');
  assert.equal(message.content[0].type, 'text');
  assert.equal(message.content[0].text, 'hello');
  assert.ok(Object.isFrozen(message), 'the message must be frozen');
  assert.ok(Object.isFrozen(message.content[0]), 'its blocks must be frozen');
  assert.match(message.id, /^[0-9a-f-]{36}$/, 'the message needs a real identity');
  assert.notEqual(noticeMessage('a', 'a').id, noticeMessage('a', 'a').id, 'every notice gets a fresh identity');
});

test('deepFreeze walks the whole tree', () => {
  const value = deepFreeze({ a: { b: [1, { c: 2 }] } });
  assert.ok(Object.isFrozen(value.a.b));
  assert.ok(Object.isFrozen(value.a.b[1]));
});
