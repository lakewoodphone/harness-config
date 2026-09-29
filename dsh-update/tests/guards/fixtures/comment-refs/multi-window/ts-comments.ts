/**
 * FIXTURE for tests/guards/comment-refs.mjs — the `.ts` arm of the JS family.
 *
 * WHY THIS FILE LIVES UNDER `multi-window/` AND NOT UNDER `scripts/`: the module's own scan roots
 * restrict `scripts/**` to `.mjs/.js/.py/.ps1/.sh` and `packages/**` to
 * `.js/.mjs/.cjs/.json/.yml/.yaml/.sh/.ps1/.py`, so NO `.ts` file is reachable through a real
 * `consumed.mjs` run today. `multi-window/**` is walked with no extension filter, which is the only
 * way to exercise the `.ts` rule the SPEC asks for. That is a statement about coverage, not a
 * workaround: if a `.ts` file ever becomes reachable, this is the rule it will meet.
 */

// @deepseek-ai/dsh-fixture-ts-comment must NOT be reported
/* @deepseek-ai/dsh-fixture-ts-block must NOT be reported */

export const tsString = '@deepseek-ai/dsh-fixture-ts-string';

export const tsHeader = ['#   gone (`@deepseek-ai/dsh-fixture-ts-prose` is removed)'];

export const tsTrailing = 1; // @deepseek-ai/dsh-fixture-ts-trailing must NOT be reported
