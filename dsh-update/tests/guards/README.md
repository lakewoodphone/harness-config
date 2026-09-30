# `tests/guards/` — the two 2026-09-28 correctness fixes, with the guards that hold them

Two measured defects made a guard in this pipeline give the wrong answer. Both are fixed in
`lib/consumed.mjs` and `lib/verify.mjs`, and both fixes are held by a guard here that fails loudly if
the defect comes back. Run them directly:

```
node dsh-update/tests/guards/comment-refs.mjs      # lib/consumed.mjs: comments are not references
node dsh-update/tests/guards/state-home.mjs        # lib/verify.mjs:  the two homes are two homes
```

Both exit 0 on pass, 1 on failure, and print one line per assertion (including the ones that
SKIP with a reason on a machine where the condition cannot be exercised). Neither starts an engine,
opens a port, or reads a session file.

## `comment-refs.mjs` — a comment is not a dependency

`consumed.mjs` matched package names against the whole text of a file, comments included. Line 309 of
`harness-config/scripts/make-preset-rows.mjs` is a generated YAML `#` comment header held in
JavaScript string literals, and it names `@deepseek-ai/dsh-agent-presets`; the module reported it as
consumed by a `kind: "script"` line and `diff.mjs` answered with

```
F001 [B1] BREAKS @deepseek-ai/dsh-agent-presets   evidenceTier=AUTHORITATIVE
```

which is false. A false `BREAKS` refuses a valid upgrade at the one tier the SPEC says may only rest
on authoritative evidence.

The guard runs the real module against `fixtures/comment-refs/` and checks both directions:

* every name that appears **only** in a comment is absent from `packageRefs`, **and** really is
  present in the fixture's raw bytes — so its absence is suppression, not a typo in the fixture;
* every name in real code or in a string literal is still reported, at its real line, with the right
  `kind`.

The fixture tree is under `dsh-update/tests/`, which is inside none of the module's scan roots
(`<configRoot>/{presets,profiles,settings,packages,scripts,multi-window}`), so it can never
contaminate a real inventory. Its package names are invented (`-fixture-…`) on purpose, so the
expected set is exact rather than "whatever upstream ships today".

### What the comment blanking does, and its stated limits

`blankComments()` in `lib/consumed.mjs` replaces comment characters with spaces **in place**, so the
string keeps its exact length and every value a finding cites still points at the byte it came from.

| File family | Comment forms blanked |
|---|---|
| `.js/.mjs/.cjs/.jsx/.ts/.tsx/.mts/.cts` | `//` to end of line, `/* … */` blocks, and a `#` that **begins** a string literal's content (the measured defect: a generator's `#` header held in JS strings) |
| `.py/.sh/.ps1` and every other extension | `#` to end of line, outside an open string; `<# … #>` (PowerShell) and `"""…"""` (Python) as blocks |
| `.html/.htm/.xhtml` | `<!-- … -->` |

ITS LIMITS, deliberately preferred to over-blanking, and asserted by the guard so a change to either
one has to change this document too:

1. **A `#` in a string that does not begin the string's content is left alone.** So a package name in
   mid-sentence prose inside a `.py`/`.sh`/`.ps1` string is still reported. Suppressing too little
   adds an entry nothing can satisfy to the unverified list; suppressing too much would HIDE a real
   dependency, which is the one failure mode this inventory cannot afford.
2. **`//` is a comment only outside a string literal.** A `//` inside a URL in a string is therefore
   not a comment, and a package name after it is reported.
3. **String state is tracked per line by counting unescaped quotes** — a heuristic, not a parser. It
   does not model a string that opens on one line and closes on another outside the block forms
   above, and shell heredocs / PowerShell here-strings are still not modelled as prose (the module
   already emits its own note when it finds one).
4. **`.ts` is in the JS family but is currently unreachable**: no scan root admits `.ts`, so that arm
   is exercised only by `fixtures/comment-refs/multi-window/ts-comments.ts`, which is walked by the
   unfiltered `multi-window/**` root. That is a statement about coverage, not a workaround.

Every run also reports the count it actually suppressed, measured by comparing each line's raw text
with its comment-blanked text (`notes[]`, "N package name mention(s) … are INSIDE A COMMENT").

## `state-home.mjs` — the config under test is not where runtime state lives

`--dsh-home` meant two things at once, and they are only the same directory in a non-staged run. The
pipeline's staging story depends on them being different: a version-coupled config change cannot be
judged against the live config. Against `%TEMP%\dsh-staged-migrated` the conflation made G4/G5
`ran:false` (no credential — a staged home deliberately has none) and G8 either refuse to run
("there is no sessions directory at …staged-migrated\sessions") or, once that directory existed with
20 files, compare the candidate against 20 staged files while the operator's real history is 1,258.

`--state-home` (default: `$env:DSH_STATE_HOME`, else `$env:DSH_HOME` when that is not a staged
location, else `%USERPROFILE%\.dsh`) now names where runtime state lives; G4/G5 read the credential
from `<state-home>/.credentials.yaml` and G8 counts `<state-home>/sessions`. The guard proves the
resolution order, the staged detection, the "exactly as before when both homes are the same
directory" property, and that the credential reader returns **the file or a reason, never a guess**
(a too-short value and a value containing whitespace are both refused).

Every gate's `detail` now ends with the two homes it worked with, so no reading in `verify.json` is
anonymous. `verify.json.notes` names both homes as well, plus the source of the resolution.
