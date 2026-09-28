# dsh-update — tests

`node tests/run.mjs` runs the whole detector suite: **node alone, no network, no engine, no install.**
It exits non-zero if any case fails. `node tests/run.mjs --selftest-broken-detector` proves the suite
is not vacuous (see below).

## What is here

| File | What it is |
|---|---|
| `run.mjs` | The suite. 13 cases, each with real assertions against a real `diff.mjs` run. |
| `make-fixtures.mjs` | **Regenerator** for `fixtures/`. Reads this machine's engine install and a real `--dump-config` capture. Not run by the suite. |
| `fixtures/` | Static JSON the suite reads: contracts, trees, `consumed.json`, and `fixtures.json` (an index with the deltas each file carries). |
| `fixtures/raw/dump-config-web-0.1.5-rc.1.txt` | The real 21,151-byte `--dump-config` capture the trees were cut from (163 rows, real comment lineage). |
| `canary-g4-settings.mjs` | **Opt-in, needs an engine.** Proves verify gate G4's settings detector can fire. Not part of `run.mjs`. |

## The cases

| Case | What it asserts |
|---|---|
| `F-B2` | The known-true breakage: `@deepseek-ai/dsh-tool-subagent-control/list-agents` is gone from the candidate's exports → **BREAKS**, subject `pkg/subpath`, all three real preset `file:line` consumers attached. |
| `F-B3` | A row id in `consumed.patchRowTargets` carries no patch attribution any more → **BREAKS**, and the detail distinguishes "row still exists, patch stopped applying" from "row deleted upstream". |
| `F-B4` | The row survives but mounts a different plugin → **RISKY**, both names quoted, and **not** also reported as B3. |
| `F-B10` | An extra package and an extra row id in the candidate → verdict still **SAFE**, findings are **CAPABILITY**, and the gap list is still populated. |
| `F-advisory-downgrade` | The same B2 comparison whose contract declares its subpath data ADVISORY → **RISKY** with `downgradedFrom: "BREAKS"`, verdict RISKY. This protects "a BREAKS may only rest on AUTHORITATIVE evidence". |
| `F-determinism` | Two runs with a pinned `generatedAt` are **byte-identical**; unpinned runs differ only in that field. |
| `F-missing-input` | A nonexistent input file exits non-zero, names the file on stderr, prints no artifact; `--help` exits 0. |
| `F-failed-tree` | A tree with `rows: []` and a `failure` field → **BREAKS** TREE finding plus every patch target listed as unchecked. A failed read never looks like health. |
| `F-B1` / `F-B5` | Package gone → BREAKS/B1; profile bundle gone → BREAKS/B5, and the same missing bundle is not double-counted as B1. |
| `F-B8` | Symbol drift is RISKY/ADVISORY with its extraction limitation in the evidence, never BREAKS. |
| `F-local-packages` | Our own `dsh-plugin-*` names are never a breakage; they land in the gap list pointing at verify gate G3. |
| `F-report` | `report.mjs` prints the verdict line, counts table, full BREAKS, RISKY, CAPABILITY and a `## Not checked` section that says "nothing" when it is empty; a missing file exits non-zero. |

## The self-test (why a green suite is evidence)

`node tests/run.mjs --selftest-broken-detector` copies `lib/diff.mjs`, applies two plausible **bugs**
to the copy ("a dropped subpath is informational" and "the patch-target check is unreachable"), runs
the whole suite against the copy, and asserts that **F-B2 and F-B3 go red**. It exits 0 only when
they do. The patched copy is written to the OS temp directory, never into this repository, and the
script fails loudly if either inversion's anchor no longer exists in the detector — so the self-test
cannot silently become a no-op.

Last observed: the broken detector turned **4/13** cases red (F-B2, F-B3, F-advisory-downgrade and
F-report — the last two because they also depend on a dropped subpath being BREAKS).

## Regenerating the fixtures

```
node tests/make-fixtures.mjs \
  --dump "C:\Users\ezabz\AppData\Local\Temp\dsh-dump-probe.json" \
  --prefix "C:\Users\ezabz\AppData\Local\npm-cache\_npx\1e7f6d9597241db0"
```

Contract entries come from the real `package.json` of each named package in the install; `symbols`
is extracted by regex from the real built JavaScript (deliberately the ADVISORY tier); trees are
parsed from the real capture with the same parser verify.mjs uses, so the comment lineage survives.
`fixtures.json` lists every delta from the real data and labels the two synthetic fields.

## The G4 canary

```
node tests/canary-g4-settings.mjs                 # control + canary (one real model turn)
node tests/canary-g4-settings.mjs --no-control    # canary only; fails before any model call
```

It builds a throwaway home in `%TEMP%` (never the live `DSH_HOME`, never a port) and asserts that
(a) the untouched settings document boots cleanly with no diagnostics and (b) the same document with
a `DUPLICATE_KEY` added is refused with a matched diagnostic. Measured 2026-09-23 on 0.1.5-rc.1:
control exit 0 / 0 hits, canary exit 1 / 14 hits.
