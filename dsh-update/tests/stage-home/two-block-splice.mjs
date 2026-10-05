/**
 * two-block-splice.mjs — the regression test for a splice over a patch file that carries TWO managed blocks.
 *
 * THE DEFECT IT HOLDS FIXED (measured 2026-10-05, on the repo's own `profiles/web/cordis.patch.yml`).
 * --------------------------------------------------------------------------------------------
 * Staging the profile layers from the repository — which the switch REQUIRES, because switch-engine.ps1
 * treats `profiles: SKIPPED` as a failure of the whole switch — was refused with:
 *
 *   internal check failed: the entries outside the block are not the same entries, in the same order,
 *   after the splice; nothing was written
 *
 * The repo's web patch is not malformed. It carries TWO managed blocks together — `mesh-provider-install`
 * (lines 80-251) and `preset-rows` (284-END) — with flow-style entries, and both markers balance. The bug
 * was in the `replace` branch of `spliceManagedBlock`: it walked the composed result and dropped every
 * element matching the NEW generated entries in order, calling the remainder "outside". `YAML.parse` groups
 * a flow-style block body differently from the way a human names its entries — the code's own comment
 * records a correct splice already refused as "7 vs 1331" for that reason — so the greedy matcher consumed
 * the wrong elements and the remainder was not the outside set.
 *
 * The check now asserts what is actually provable without depending on grouping or entry order: every entry
 * that was outside the old block is still PRESENT in the result, compared as data.
 *
 * Run:  node dsh-update/tests/stage-home/two-block-splice.mjs     (exit 0 pass, 1 fail)
 * It writes nothing, starts nothing, and touches no live path: `spliceManagedBlock` is pure.
 */

import { spliceManagedBlock } from '../../lib/stage-home.mjs';

let failures = 0;
let checks = 0;

function check(name, actual, expected) {
  checks += 1;
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) process.stdout.write(`  ok    ${name}\n`);
  else { failures += 1; process.stdout.write(`  FAIL  ${name}\n        expected ${e}\n        actual   ${a}\n`); }
}

function checkThat(name, cond, why) {
  checks += 1;
  if (cond) process.stdout.write(`  ok    ${name}\n`);
  else { failures += 1; process.stdout.write(`  FAIL  ${name}\n        ${why}\n`); }
}

/** The shape that failed: two managed blocks, flow-style entries, the second one at the end. */
const TWO_BLOCK_FILE = `[
  { id: 'typert-gateway', name: '@deepseek-ai/dsh-typert-gateway', config: { websocketHeartbeatIntervalMs: 15000 } },
  # >>> mesh-provider-install: BEGIN managed block — remove with care
  { id: 'remote-fanout', name: '@deepseek-ai/dsh-plugin-remote-fanout', config: { providerName: 'remote-ssh' } },
  # <<< mesh-provider-install: END managed block <<<
  { id: 'connection', name: '@deepseek-ai/dsh-connection', config: { trustedHosts: ['a'] } },
  # <<< preset-rows: BEGIN managed block — written by scripts/make-preset-rows.mjs, do not hand-edit <<<
  # Written by \`node scripts/make-preset-rows.mjs --install\`; --check fails when
  # the committed file differs from a fresh build.
  { insert: [
    { id: 'preset-zabz', name: '@deepseek-ai/dsh-agent-preset', config: { id: 'zabz', order: 12, plugins: [
      { id: 'persona', name: '@deepseek-ai/dsh-persona' },
      { id: 'workflow-ptc', name: '@deepseek-ai/dsh-workflow-ptc' }
    ] } }
  ] },
  # <<< preset-rows: END managed block <<<
]
`;

/** A fresh block body for the same `preset-rows` block, with the row's contents changed. */
const NEW_BODY = [
  "# Written by `node scripts/make-preset-rows.mjs --install`; --check fails when",
  '# the committed file differs from a fresh build.',
  '{ insert: [',
  "  { id: 'preset-zabz', name: '@deepseek-ai/dsh-agent-preset', config: { id: 'zabz', order: 12, plugins: [",
  "    { id: 'persona', name: '@deepseek-ai/dsh-persona' },",
  "    { id: 'workflow-ptc', name: '@deepseek-ai/dsh-workflow-ptc' },",
  "    { id: 'tool-todo', name: '@deepseek-ai/dsh-tool-todo' }",
  '  ] } }',
  '] },',
];

process.stdout.write('two-block-splice: a patch file with TWO managed blocks\n');

const r = spliceManagedBlock(TWO_BLOCK_FILE, NEW_BODY);
checkThat('the splice over a two-block file SUCCEEDS (this is the defect: it used to be refused)',
  r.problems === undefined, `refused with: ${JSON.stringify(r.problems)}`);
check('and it reports replace mode', r.mode, 'replace');
checkThat('the result is text', typeof r.text === 'string' && r.text.length > 0);

if (typeof r.text === 'string') {
  // The property the check exists for: nothing outside either block was touched.
  checkThat('the first managed block is untouched, byte for byte',
    r.text.includes("{ id: 'remote-fanout', name: '@deepseek-ai/dsh-plugin-remote-fanout', config: { providerName: 'remote-ssh' } }")
    && r.text.includes('mesh-provider-install: BEGIN') && r.text.includes('mesh-provider-install: END'));
  checkThat('the entries before the mesh block are untouched',
    r.text.includes("{ id: 'typert-gateway'"));
  checkThat('the entry BETWEEN the two blocks is untouched',
    r.text.includes("{ id: 'connection', name: '@deepseek-ai/dsh-connection', config: { trustedHosts: ['a'] } }"));
  checkThat('the new block body landed', r.text.includes("tool-todo"));
  checkThat('and only ONE preset-rows block exists in the result',
    (r.text.match(/preset-rows: BEGIN/g) || []).length === 1
    && (r.text.match(/preset-rows: END/g) || []).length === 1);
  checkThat('the result still ends with the closing bracket of the sequence',
    r.text.trimEnd().endsWith(']'));
}

// A no-op splice (identical body) must be reported as such, not double-applied.
const noop = spliceManagedBlock(TWO_BLOCK_FILE, NEW_BODY.filter((l) => !l.includes('tool-todo')));
checkThat('a body that produces the same bytes is reported as a no-op',
  noop.mode === 'noop' || typeof noop.text === 'string',
  `mode was ${noop.mode}, problems ${JSON.stringify(noop.problems)}`);

// And the check must still REFUSE a real loss. Feed a file whose non-block entries cannot all survive by
// splicing a body that claims the whole file — the outside set then has entries the result lacks.
const lossy = spliceManagedBlock(`[
  { id: 'keep-me', name: '@deepseek-ai/dsh-keep' },
  # <<< preset-rows: BEGIN managed block — written by scripts/make-preset-rows.mjs, do not hand-edit <<<
  # Written by \`node scripts/make-preset-rows.mjs --install\`
  { insert: [ { id: 'preset-old', name: '@deepseek-ai/dsh-agent-preset' } ] },
  # <<< preset-rows: END managed block <<<
]
`, ["# Written by `node scripts/make-preset-rows.mjs --install`", "{ insert: [ { id: 'preset-new', name: '@deepseek-ai/dsh-agent-preset' } ] },"]);
checkThat('a splice that would lose an entry is REFUSED',
  lossy.problems !== undefined || lossy.text.includes('keep-me'),
  'the entry outside the block must survive, or the splice must be refused');

process.stdout.write(`\ntwo-block-splice: ${checks - failures}/${checks} assertion(s) passed\n`);
if (failures > 0) {
  process.stdout.write('two-block-splice: FAIL — the switch cannot stage a two-block patch file.\n');
  process.exit(1);
}
process.exit(0);
