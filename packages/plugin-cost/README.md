# dsh-plugin-cost

Session and per-turn USD cost for DSH, priced from a cited rate card.

Two surfaces, one price table:

| Surface | What it shows | Where it lives |
|---|---|---|
| `/cost [turns]` | Exact session total plus a per-turn table, priced from the durable log with the real provider/model and the real call time | Host half: `lib/index.js` |
| Composer cost pill | A `$0.00` figure beside the shipped stats pill in the chat footer; click for the bucket breakdown and the rate card it used | Browser half: `lib/client.js` |

## Why this exists

The harness shows tokens and no money. Nothing in the installed `@deepseek-ai/*`
tree prices anything in currency — the only USD rates that ship anywhere are in the
upstream `@earendil-works/pi-ai` catalogs, which the harness deliberately zeroes
(`NO_COST` in `dsh-llm-pi-ai`). So the rate card here is the project's own, and every
rate in it carries the URL and the date it was read.

## The rule this plugin follows

A cost that cannot be established is reported as a gap, never guessed:

- an unpriced provider/model returns `undefined`, and the surfaces say "unpriced"
  rather than falling back to a nearby model's rate;
- a model call that settled with no usage sample is counted and named, and the
  session total is labelled a **lower bound**, because the provider may still have
  billed it;
- `cacheWriteTokens` is not charged at the miss rate on a card that has no
  cache-write line item — inventing that number would double-count.

## Priced routes

USD per 1,000,000 tokens. `miss` = uncached input, `hit` = cached input.

| provider | model ids | miss | hit | write | output |
|---|---|---|---|---|---|
| `deepseek-official` | `deepseek-flash`, `deepseek-v4-flash`, `deepseek-v4-flash-vision-exp` | 0.15 | 0.003 | — | 0.60 |
| `deepseek-official` | `deepseek-v4-pro` | 0.66 | 0.022 | — | 1.98 |
| `deepinfra` | `deepseek-ai/DeepSeek-V4.1-Flash` | 0.20 | 0.006 | — | 0.60 |
| `deepinfra` | `deepseek-ai/DeepSeek-V4-Flash-0731` | 0.06 | 0.015 | — | 0.18 |

`deepseek-official` is **time-of-day priced**: peak is 01:00–04:00 and 06:00–10:00 UTC
Monday–Friday, and peak is exactly 2× off-peak. A single constant rate would be wrong
roughly half the time, so the cost function branches on each call's own timestamp and
the report also prints a peak-rate upper bound.

`deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` are retired names that the
provider still serves from DeepSeek-V4.1-Flash at the Flash price. The provider's live
`/models` endpoint returns exactly `deepseek-flash` and `deepseek-v4-pro` (re-read
2026-09-11), which is why only two official cards exist here.

Sources: [DeepSeek models & pricing](https://api-docs.deepseek.com/quick_start/pricing) ·
[DeepInfra V4.1-Flash](https://deepinfra.com/deepseek-ai/DeepSeek-V4.1-Flash) ·
[DeepInfra V4-Flash-0731](https://deepinfra.com/deepseek-ai/DeepSeek-V4-Flash-0731)

## Install

```bash
# from the harness-config checkout
node packages/plugin-cost/scripts/build.mjs          # regenerate lib/ from src/
node packages/plugin-cost/scripts/build.mjs --check  # fail if lib/ is stale

# into the web profile
cd ~/.dsh/profiles/web
pnpm add "file:<path-to>/harness-config/packages/plugin-cost"
# then add "dsh-plugin-cost" to dsh.profile.bundles in that profile's package.json
```

The bundle list is read when the profile boots, so **restart the profile** for the
plugin to mount.

## Verifying it, not assuming it

```bash
node test/verify.mjs
```

Runs four independent checks, because a passing build implies none of the others:

- **build** — `lib/` matches the sources it is generated from.
- **cost** — the rates, the peak/off-peak arithmetic, sample validation, and the fold
  run against real session logs; asserts that a session total equals the sum of its
  turns and that the peak bound is never below the actual cost.
- **client** — the browser half is evaluated the way the module system does it: a fake
  `window.__ModuleLoader__` captures the registration, the factory is materialized with
  a stub React, and the registered cell is rendered with fake projection props.
- **profile** — the package resolves by name from the profile directory and its
  manifest carries a usable `dsh.client` and `dsh.bundle`.

What the suite cannot prove: that the pill looks right on screen. Only a browser
session proves that.

## Layout

```
pricing.json          the authoritative rate card (source of truth; the build inlines it)
cordis.patch.yml      the bundle patch that mounts the host row
src/cost-core.mjs     rates, tiers, money arithmetic, the usage fold, the text report
src/session-log.mjs   locate and decode a session's .jsonl.zstd log
src/command.mjs       the /cost command definition and handler
scripts/build.mjs     generates lib/index.js and lib/client.js from the sources
test/                 the four checks above
lib/                  GENERATED — do not edit
```

`src/*.mjs` are real modules so they can be tested directly; `lib/index.js` is the same
code flattened into one module, because a Cordis plugin is a single module and the
generated half must be the tested half.

## What breaks on a harness upgrade

- The composer dock slot `conversation.composer.dock` is an additive `list` slot
  declared by `dsh-client-ui-conversation`. Registering with a fresh `id` (`cost`)
  replaces nothing; if the slot's protocol changes, the pill stops appearing and the
  `/cost` command is unaffected.
- `pricing.json` is manual data. Rates change; nothing detects that on its own.
  Re-read the source URLs when a report looks wrong.
- A `pnpm install` in the profile rewrites `dependencies` but leaves the `bundles`
  array alone, so the plugin survives installs and only needs re-adding if the
  profile's `package.json` is reset.
