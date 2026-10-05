/**
 * settings-map.mjs — "which settings namespace owns this key, what does the CANDIDATE's own schema say,
 * and which composition row is it?" — the tool for every settings migration.
 *
 * WHY THIS EXISTS (measured 2026-10-05). `settings-effective` reported 15 BREAKS against 0.2.0-rc.2:
 * 11 keys of ours ABSENT from the engine's resolved settings and 4 resolved to a DIFFERENT value.
 * Answering "did the keys move, or did the reader move?" needed three facts that nothing in this repo
 * could print:
 *
 *   1. the JSON-pointer PATH the candidate's schema gives each key;
 *   2. the candidate schema's own DEFAULT for it — because "the engine resolved a different value" reads
 *      very differently when the resolved value IS the schema default;
 *   3. which ROW (and therefore which package and namespace id) owns that schema, because a package can
 *      SPLIT: on 0.2.0-rc.2 the single `@deepseek-ai/dsh-llm-deepseek` row became
 *      `@deepseek-ai/dsh-llm-deepseek-api-key` (id `llm-deepseek`) plus `@deepseek-ai/dsh-llm-deepseek-account`
 *      (id `llm-deepseek-account`), and the namespace name our settings target is attached to a row whose
 *      package name no longer matches the comments in our own settings files.
 *
 * The schema dump is produced by the candidate itself:
 *   node <candidate>/node_modules/@deepseek-ai/dsh/lib/bin.js --profile <p> --dump-config-schema
 * (it takes no app arguments; capture stdout). Its top-level `x-cordis.entries` is the roster that maps
 * every `#/$defs/configN` back to `{path, id, name, status, configRef}` — that is what makes (3) possible.
 *
 * READ-ONLY. It reads one JSON file and prints. It starts nothing, boots nothing, and writes nothing.
 *
 * Usage:
 *   node dsh-update/tools/settings-map.mjs <schema.json> [--keys a,b,c] [--namespace <id>] [--json]
 */

import fs from 'node:fs';

const ARGS = process.argv.slice(2);
const JSON_MODE = ARGS.includes('--json');
const val = (name) => { const i = ARGS.indexOf(name); return i >= 0 ? ARGS[i + 1] : null; };
const schemaPath = ARGS.find((a) => !a.startsWith('--') && a !== val('--keys') && a !== val('--namespace'));

if (!schemaPath) {
  process.stdout.write('usage: node dsh-update/tools/settings-map.mjs <schema.json> [--keys a,b,c] [--namespace <id>] [--json]\n');
  process.exit(2);
}
let j;
try { j = JSON.parse(fs.readFileSync(schemaPath, 'utf8')); } catch (e) {
  process.stdout.write(`settings-map: cannot read ${schemaPath} as JSON: ${e.message}\n`);
  process.exit(2);
}

const defs = j.$defs ?? {};
const entries = j['x-cordis']?.entries ?? [];
if (entries.length === 0) {
  process.stdout.write('settings-map: this schema carries no x-cordis.entries roster, so no $defs can be '
    + 'attributed to a row or a namespace. That is a refusal, not an empty success — pass a real\n'
    + '             `--dump-config-schema` dump from the candidate.\n');
  process.exit(2);
}

const rowFor = (cfg) => entries.find((e) => String(e.configRef ?? '').endsWith(`/${cfg}`)) ?? null;
const objOf = (name) => defs[name]?.anyOf?.[0] ?? defs[name] ?? null;
const propsOf = (name) => objOf(name)?.properties ?? null;

const explicitKeys = (val('--keys') ?? '').split(',').map((s) => s.trim()).filter(Boolean);
const wantedKeys = explicitKeys.length ? explicitKeys
  : ['retryPolicy', 'maxParallelToolCalls', 'defaultPreset', 'streamIdleTimeoutMs', 'busyEnter', 'maxTokens'];

/** Namespaces, i.e. every configN that has properties, with the row that owns it. */
const namespaces = [];
for (const name of Object.keys(defs)) {
  const props = propsOf(name);
  if (!props) continue;
  const row = rowFor(name);
  namespaces.push({
    config: name,
    namespace: row?.id ?? null,
    package: row?.name ?? null,
    path: row?.path ?? null,
    status: row?.status ?? null,
    keys: Object.keys(props),
  });
}
const onlyNamespace = val('--namespace');
const shown = onlyNamespace ? namespaces.filter((n) => n.namespace === onlyNamespace) : namespaces;

const out = { schema: schemaPath, profile: j['x-cordis']?.profile ?? null, namespaces: shown, keys: [] };

for (const key of wantedKeys) {
  for (const ns of shown) {
    const props = propsOf(ns.config);
    if (!props || !Object.prototype.hasOwnProperty.call(props, key)) continue;
    const cur = props[key];
    const arm = cur?.anyOf?.[0] ?? cur;
    out.keys.push({
      key,
      namespace: ns.namespace,
      package: ns.package,
      rowPath: ns.path,
      config: ns.config,
      schemaDefault: cur?.default ?? arm?.default ?? null,
      hasDefault: (cur?.default ?? arm?.default) !== undefined,
      shape: Object.keys(arm?.properties ?? {}).slice(0, 14),
    });
  }
}

if (JSON_MODE) { process.stdout.write(`${JSON.stringify(out, null, 2)}\n`); process.exit(0); }

const pad = (s, n) => String(s ?? '(none)').padEnd(n).slice(0, n);
process.stdout.write(`settings-map   ${schemaPath}\nprofile ${out.profile}   ${entries.length} row(s) in the roster\n\n`);

process.stdout.write(`NAMESPACES${onlyNamespace ? ` matching id=${onlyNamespace}` : ''} (${shown.length})\n`);
for (const ns of shown) {
  const marker = wantedKeys.some((k) => ns.keys.includes(k)) ? '*' : ' ';
  process.stdout.write(` ${marker} ${pad(ns.namespace, 24)} ${pad(ns.package, 46)} ${pad(ns.path, 6)} [${ns.status}]\n`);
}
process.stdout.write('\n  (* = declares at least one of the keys asked about)\n');

process.stdout.write(`\nWHERE EACH KEY LIVES IN THE CANDIDATE, AND ITS SCHEMA DEFAULT\n`);
if (out.keys.length === 0) {
  process.stdout.write('  none of the requested keys is declared by any namespace in this schema.\n');
  process.stdout.write('  That is a finding about the candidate, not about your settings — read it as "this candidate\n');
  process.stdout.write('  has no home for these keys at all".\n');
}
for (const k of out.keys) {
  process.stdout.write(`  ${pad(k.key, 26)} ${pad(k.namespace, 22)} ${pad(k.package, 44)} default=${k.hasDefault ? JSON.stringify(k.schemaDefault) : '(NO DEFAULT)'}\n`);
  if (k.shape.length) process.stdout.write(`      accepts: ${k.shape.join(', ')}\n`);
}
process.stdout.write('\nA key with NO schema default that the engine reports as ABSENT is a value this deployment sets\n');
process.stdout.write('that the candidate has nowhere to put — the silent-loss case. A key whose resolved value EQUALS\n');
process.stdout.write('the schema default is the same finding from the other side: the document is not being read.\n');
process.exit(0);
