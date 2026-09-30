# Generated configuration: the `zabz` preset and the web patch layer (2026-09-30)

**The rule, in one line:** a hand-edit to a generated file is forbidden — edit the source and regenerate.

This document exists because a hand edit to `presets/zabz/agent.cordis.yml` was silently reverted
twice. Each time, the generator's row definitions were the real source and the committed file had
drifted from them, so the next regeneration deleted the change.

## Which files are generated, and what generates them

| Generated file | Written by | Source of truth it is generated FROM |
|---|---|---|
| `presets/zabz/agent.cordis.yml` | `scripts/make_zabz_preset.py` | `presets/cordis-bg/agent.cordis.yml` (shared base) **+** `presets/zabz/rows/*.yml` (zabz-only rows) |
| `presets/zabz/preset.yml` | `scripts/make_zabz_preset.py` | the `PRESET_YML` literal in that script |
| `presets/zabz/skills/**` | `scripts/make_zabz_preset.py` | `presets/cordis-bg/skills/**` (additively — see below) |
| `profiles/web/cordis.patch.yml`, the `preset-rows` managed block (lines between the two `# <<< preset-rows: … >>>` markers) | `scripts/make-preset-rows.mjs` | every `presets/*/agent.cordis.yml` |
| `profiles/web/presets.generated.patch.yml` | `scripts/make-preset-rows.mjs` | every `presets/*/agent.cordis.yml` (same patch entries, standalone `--patch` form) |

**The source of truth is exactly two things:**

1. `presets/cordis-bg/agent.cordis.yml` — the shared base composition. Every row `zabz` does not
   override is inherited from here, so one fix reaches both presets.
2. `presets/zabz/rows/` — the rows `zabz` changes or adds, as plain YAML:
   * `persona.row.yml` — the whole `- id: persona` row.
   * `delegation.rows.yml` — the rows that replace the base's local `tool-subagent` row.
   * `mcp.rows.yml` — the whole MCP bridge section, appended.

Nothing else defines a `zabz` row. The Python file holds no row literals; it only transforms the two
inputs above and stamps the output.

## Regenerate — the exact command

```powershell
# from the harness-config repo root
python scripts/make_zabz_preset.py             # rows/ -> presets/zabz/agent.cordis.yml
node scripts/make-preset-rows.mjs --install    # presets/* -> the patch layer (block + standalone file)
```

Both steps are required: the second reads the file the first writes. Verified output on
ZABZ-YOGA 2026-09-30 (24 rows, `fetch` and `context7` gone, Playwright pinned):

```
wrote presets\zabz\agent.cordis.yml
  rows: 24
  persona, agent-instructions, tool-bash, tool-pwsh, tool-fs, tool-fs-search, tool-jobs,
  command-goal, tool-goal, planning, compaction, delegation, tool-ask-user, tool-todo,
  tool-web, tool-cordis, skill-filesystem, tool-skill, present, mcp-secretary,
  mcp-secretary-linux, mcp-firecrawl, mcp-jina, mcp-playwright

make-preset-rows.mjs — 3 preset(s) from ...\presets
  preset-cordis-bg  id=cordis-bg  order=10  plugins=19  !!js=4
  preset-yocheved   id=yocheved   order=11  plugins=20  !!js=4
  preset-zabz       id=zabz       order=12  plugins=24  !!js=9
  managed block: 3 entries, 1311 lines, 17 !!js; self-check: PASS
  wrote profiles\web\presets.generated.patch.yml (77872 bytes, 921 lines)
  updated the managed block in profiles\web\cordis.patch.yml (patch entries 8 -> 8)
  outside the block: byte-identical, sha256 ca9568639fc44e01… (proved by removing the block region from both texts and comparing)
```

## Check — the exact command

```powershell
python scripts/make_zabz_preset.py --check ; node scripts/make-preset-rows.mjs --check
```

Both must exit 0. On a clean tree 2026-09-30:

```
zabz: in sync with the generator (rows + skills)
next: node scripts/make-preset-rows.mjs --check   # patch layer

make-preset-rows.mjs — 3 preset(s) from ...\presets
  !!js expressions carried: 17; self-check: PASS
--check: UP TO DATE — profiles\web\presets.generated.patch.yml
--check: managed block UP TO DATE — profiles\web\cordis.patch.yml (lines 285-1595, 1311 lines inside the markers)
```

`python scripts/make_zabz_preset.py --check` fails when `presets/zabz/agent.cordis.yml`,
`presets/zabz/preset.yml`, or a base skill copy has drifted from the sources.
`node scripts/make-preset-rows.mjs --check` fails when either the managed block or the standalone
file disagrees with `presets/*/agent.cordis.yml`. Neither writes anything.

**Proof that the check catches a hand edit** (run in a throwaway copy, `%TEMP%\hc-scratch`, never in
the live tree):

```
[2] hand-edit the GENERATED preset, then python check
hand-edited ...\presets\zabz\agent.cordis.yml (preset)
exit=1
DRIFT: the committed preset does not match this generator:
  presets\zabz\agent.cordis.yml

[5] hand-edit the GENERATED managed block, then node check
hand-edited ...\profiles\web\cordis.patch.yml (block)
--check: DRIFT — the `preset-rows` block in profiles\web\cordis.patch.yml does not match what the converter would write
  first difference at block line 696
  committed:                         id: mcp-fetch,
  generated:             name: "@deepseek-ai/dsh-agent-preset",
exit=1
```

## How to add or remove a row (the only correct procedure)

1. Edit `presets/zabz/rows/mcp.rows.yml` (or `delegation.rows.yml`, or `persona.row.yml`). If the row
   belongs to `cordis-bg` and `yocheved` too, edit `presets/cordis-bg/agent.cordis.yml` instead.
2. Run the two regeneration commands above.
3. Run the two `--check` commands and confirm both are green.
4. Commit the source, the regenerated preset, and the regenerated patch layer together.

## What was fixed here (2026-09-30)

* **`mcp-fetch` and `mcp-context7` are removed** (TS-1 / TS-2, `_scratch/b2-tool-stack.md` §8/§9):
  8 tools and 8,786 of 87,777 MCP schema chars (10.0%), ~2,196 tokens per request, against 5/1,611
  and 1/1,611 session mentions and full coverage by the builtin `web_search`/`web_fetch` plus jina.
* **The Playwright row carries a pinned `--user-data-dir`** (TS-5):
  `C:\Users\ezabz\AppData\Local\ms-playwright-mcp\mcp-chrome-32dbea4`, so a logged-in portal session
  survives the child that opened it.
* **The missing writer was restored.** `scripts/make-preset-rows.mjs` was created on branch
  `hk/20260928-journal-utf8-complete` (commit `4322837`) and never reached this branch, while the
  block it owns was already committed. Without it, the block in `profiles/web/cordis.patch.yml` had
  no writer and had drifted for all three presets, not just `zabz`.
* **Regeneration no longer deletes `presets/zabz/skills/secretary-wake`.** The old
  `rmtree`+`copytree` of `cordis-bg/skills` removed every zabz-only skill on each run; the copy is
  now additive (base files are overwritten, extra files are left alone), and `--check` verifies
  one-way that every base skill is present and identical.
* **Every previously hand-edited rule is now in the source**, so regeneration preserves it: owner
  rules 8 and 9, the hardened outbound-communications hard stop, the "ask him before a counterparty"
  rule, and `enableRunInBackground: true` on the two mesh `subagent` rows.

## Limits, stated rather than hidden

* This change is committed on branch `agent/deployed-truth`; it is **not installed** into `~/.dsh`.
  The point is that the change survives regeneration, not that it is live today.
* `scripts/make-preset-rows.mjs` was restored verbatim from commit `4322837`. Its own unit tests
  (`dsh-update/tests/preset-rows/`, named in its header) are not present on this branch, so the
  restored script is verified by its built-in `selfCheck`, the `--check` runs above, and the
  scratch-copy drift proof — not by that test suite.
* The historical comment path `docs/autonomy-fleet-20260930/b2-tool-stack.md` does not exist in this
  tree; the audit content is at `_scratch/b2-tool-stack.md`.
