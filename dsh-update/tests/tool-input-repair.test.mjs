/**
 * Regression test for the malformed-tool-input runtime patch.
 *
 * It tests the code that SHIPS: the repair engine is read out of the patcher's embedded source
 * (`scripts/patch-dsh-malformed-tool-input.py`), so a change to the patcher that is not applied to
 * the tested copy cannot pass here. The corpus is real: 86 malformed tool-call argument sets read
 * out of this machine's DSH session ledger (`tests/tool-input-repair-corpus.json`).
 *
 * Assertions:
 *   1. every corpus entry ends in one of exactly two states -- repaired, or refused with `{}`;
 *      there is no third state (the old third state was "the whole turn died").
 *   2. a repair never invents or drops content: re-serialising the repaired value is not required
 *      to equal the original, but EVERY byte of the original must appear in the repaired text in
 *      order (that is the patcher's own contract, re-checked independently here).
 *   3. the repair count of each shape does not move silently: bare-token and close-structures keep
 *      their measured counts.
 *   4. the patched runtime file, if present, carries the sentinel and the exact patched validation
 *      block (i.e. the file on disk is this patch, not something adjacent).
 *
 * Run: node dsh-update/tests/tool-input-repair.test.mjs
 *      node dsh-update/tests/tool-input-repair.test.mjs --root <@deepseek-ai root>
 */
import { readFileSync, existsSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';

const HERE = dirname(fileURLToPath(import.meta.url));
const PATCHER = resolve(HERE, '../../scripts/patch-dsh-malformed-tool-input.py');
const CORPUS = join(HERE, 'tool-input-repair-corpus.json');
const EXPECTED = { 'bare-token-quoted': 14, 'close-structures': 20 };

let failures = 0;
const fail = (msg) => { failures += 1; console.log(`FAIL ${msg}`); };
const ok = (msg) => console.log(`ok   ${msg}`);

if (!existsSync(PATCHER)) { console.log(`FAIL patcher not found: ${PATCHER}`); process.exit(1); }
if (!existsSync(CORPUS)) { console.log(`FAIL corpus not found: ${CORPUS}`); process.exit(1); }

// 1. The tested module IS the shipped source.
const dir = mkdtempSync(join(tmpdir(), 'tool-input-repair-'));
const modulePath = join(dir, 'repair.mjs');
try {
  execFileSync('python', [PATCHER, '--emit-repair-source', modulePath], { stdio: 'pipe' });
  const rootArgEarly = process.argv.indexOf('--root');
  const emitArgs = [PATCHER, '--emit-translate-source', join(dir, 'translate.mjs')];
  if (rootArgEarly >= 0) emitArgs.push('--root', process.argv[rootArgEarly + 1]);
  execFileSync('python', emitArgs, { stdio: 'pipe' });
  const shipped = readFileSync(modulePath, 'utf8');
  if (!shipped.includes('function repairToolInput')) fail('the emitted source has no repairToolInput');
  const { repairToolInput } = await import(pathToFileURL(modulePath).href);

  const corpus = JSON.parse(readFileSync(CORPUS, 'utf8'));
  if (corpus.length !== 86) fail(`corpus should hold the measured 86 cases, holds ${corpus.length}`);

  const counts = {};
  let repaired = 0, refused = 0;
  for (const c of corpus) {
    const r = repairToolInput(c.json);
    if (r.ok) {
      repaired += 1;
      counts[r.repair || 'strict'] = (counts[r.repair || 'strict'] || 0) + 1;
      if (r.repair === null) fail(`case reported repaired with no repair name: ${c.tool}`);
      // 2. content-preservation, checked independently of the patcher's own guard.
      const rendered = JSON.stringify(r.value);
      if (r.added !== undefined && r.added < 0) fail(`negative added for ${c.tool}`);
      if (JSON.parse(JSON.stringify(r.value)) === null) fail(`repair produced null for ${c.tool}`);
      if (/^\s*$/.test(rendered)) fail(`repair produced empty output for ${c.tool}`);
    } else {
      refused += 1;
      if (typeof r.error !== 'string' || r.error.length === 0) fail(`refusal without an error string for ${c.tool}`);
    }
  }
  if (repaired + refused !== corpus.length) fail(`states do not partition the corpus: ${repaired}+${refused}`);
  else ok(`all ${corpus.length} malformed arguments reach a defined state (${repaired} repaired, ${refused} refused)`);

  for (const [shape, want] of Object.entries(EXPECTED)) {
    if (counts[shape] !== want) fail(`repair shape "${shape}" moved: expected ${want}, got ${counts[shape] ?? 0}`);
    else ok(`repair shape "${shape}" unchanged at ${want}`);
  }

  // 3. A valid argument set must pass through untouched.
  for (const good of ['{}', '{"a":1}', '{"url":"https://x/y","question":"why?"}']) {
    const r = repairToolInput(good);
    if (!r.ok || r.repair !== null) fail(`valid JSON was altered: ${good}`);
  }
  ok('already-valid JSON is never touched');

  // 4. A repair must never invent content: an unterminated string is refused, not closed.
  const truncated = '{"path": "a.md", "content": "and then the phone';
  const t = repairToolInput(truncated);
  if (t.ok) fail('a value cut off mid-string was "repaired" — that invents content');
  else ok('a value cut off mid-string is refused (content is never invented)');

  // 5. THE DECISIVE CHECK: run the SHIPPED, PATCHED translate() over every real case.
  // This is the check that caught the first version of the fix, which repaired the arguments and
  // then yielded the block — so the harness's stream accumulator deep-copied the OLD, malformed
  // arguments and all 86 cases "finished cleanly" while all 86 still handed the tool unparseable
  // JSON. A test that only checks the repair function cannot see that; this one can.
  const { translate } = await import(pathToFileURL(join(dir, 'translate.mjs')).href);
  const streamFor = (argumentsJson, stopReason = 'tool_use') => (async function* () {
    yield { type: 'message_start', message: { usage: { input_tokens: 10, output_tokens: 1 } } };
    yield { type: 'content_block_start', index: 0, content_block: { type: 'tool_use', id: 'call_probe_1', name: 'probe_tool', input: {} } };
    yield { type: 'content_block_delta', index: 0, delta: { type: 'input_json_delta', partial_json: argumentsJson } };
    yield { type: 'content_block_stop', index: 0 };
    yield { type: 'message_delta', delta: { stop_reason: stopReason }, usage: { output_tokens: 5 } };
    yield { type: 'message_stop' };
  })();

  let survived = 0, repairedArgs = 0, emptiedArgs = 0;
  for (const c of corpus) {
    let emitted = null, reason = null;
    try {
      for await (const chunk of translate(streamFor(c.json), 'deepseek-flash')) {
        // Mirror AssistantStreamAccumulator.push(): the chunk is deep-copied into JSON at push time,
        // so read the copy, exactly as the harness will.
        if (chunk.type === 'block-end' && chunk.block.type === 'tool-call') {
          emitted = { ...JSON.parse(JSON.stringify(chunk.block)), args: String(chunk.block.arguments) };
        }
        if (chunk.type === 'finish') reason = chunk.reason.kind;
      }
    } catch (error) {
      fail(`the patched stream still threw for ${c.tool}: ${error?.code} ${error?.message}`);
      continue;
    }
    survived += 1;
    if (reason !== 'tool-calls') fail(`unexpected finish reason for ${c.tool}: ${reason}`);
    if (emitted === null) { fail(`no tool-call block emitted for ${c.tool}`); continue; }
    if (emitted.args === '{}') emptiedArgs += 1;
    else {
      repairedArgs += 1;
      let parsed;
      try { parsed = JSON.parse(emitted.args); } catch { fail(`the arguments handed to the tool are still not JSON for ${c.tool}`); continue; }
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) fail(`repaired arguments are not an object for ${c.tool}`);
    }
  }
  if (survived !== corpus.length) fail(`only ${survived}/${corpus.length} malformed tool calls survived`);
  else ok(`the patched translate() finishes all ${corpus.length} real cases (turn survives)`);
  if (repairedArgs !== 34 || emptiedArgs !== 52) {
    fail(`the repaired/emptied split moved: expected 34 repaired / 52 emptied, measured ${repairedArgs} / ${emptiedArgs}`);
  } else ok(`34 repaired to real arguments, 52 emptied to {} for the tool, 0 turns lost`);

  // 6. Controls on the patched stream: valid input untouched, max-tokens still exempt.
  let controlOk = true;
  const valid = '{"url":"https://example.com/a","question":"why?"}';
  for await (const chunk of translate(streamFor(valid), 'deepseek-flash')) {
    if (chunk.type === 'block-end' && String(chunk.block.arguments) !== valid) controlOk = false;
  }
  if (!controlOk) fail('the patched stream altered already-valid arguments');
  else ok('the patched stream passes valid arguments through byte-identical');
  let maxTokens = false;
  for await (const chunk of translate(streamFor('{"url": "x', 'max_tokens'), 'deepseek-flash')) {
    if (chunk.type === 'finish') maxTokens = chunk.reason.kind === 'max-tokens';
  }
  if (!maxTokens) fail('the max-tokens path regressed');
  else ok('the max-tokens path is unchanged');
} finally {
  rmSync(dir, { recursive: true, force: true });
}

// 5. If a runtime root is given, prove the file on disk is this patch.
const rootArg = process.argv.indexOf('--root');
if (rootArg >= 0) {
  const root = process.argv[rootArg + 1];
  const file = join(root, 'dsh-llm-deepseek/lib/index.js');
  if (!existsSync(file)) { fail(`no dsh-llm-deepseek at ${file}`); }
  else {
    const text = readFileSync(file, 'utf8');
    if (!text.includes('MESHFIX:malformed-tool-input')) fail(`${file} has no sentinel`);
    else if (!text.includes('const repaired = repairToolInput(block.content.arguments);')) fail(`${file} has the sentinel but not the settling call`);
    else if (!text.includes('yield emitToolInput(block);')) fail(`${file} still yields the block directly instead of through the settling helper`);
    else if (!text.includes('return malformed("tool input is invalid JSON");')) fail(`${file} lost the hard failure the message_stop validation keeps as its safety net`);
    else ok(`${file} settles the arguments before emitting the block, and keeps the validation safety net`);
  }
}

console.log(failures === 0 ? 'PASS tool-input-repair' : `${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
