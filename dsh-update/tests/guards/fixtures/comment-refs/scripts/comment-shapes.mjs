/**
 * FIXTURE for tests/guards/comment-refs.mjs — every line below is one rule of `blankComments`.
 *
 * THE PACKAGE NAMES ARE DELIBERATELY INVENTED (`-fixture-…`) AND MUST STAY THAT WAY. They are not
 * real upstream packages, so the guard can compare against an exact expected set instead of against
 * whatever upstream happens to ship. Nothing here is scanned by a real `consumed.mjs` run: the
 * module's scan roots are `<configRoot>/{presets,profiles,settings,packages,scripts,multi-window}`,
 * and this tree is under `dsh-update/tests/…`, which is none of them.
 */

// @deepseek-ai/dsh-fixture-comment-line must NOT be reported
/* @deepseek-ai/dsh-fixture-comment-block must NOT be reported */

const realString = '@deepseek-ai/dsh-fixture-real-string';
const realRow = { id: 'fixture-row', name: '@deepseek-ai/dsh-fixture-real-rowname' };
const ownReal = 'dsh-plugin-fixture-real-own';

const trailing = 1; // @deepseek-ai/dsh-fixture-comment-trailing must NOT be reported

/**
 * The measured defect, reproduced: a generator that emits a YAML `#` comment header holds each line
 * of that header in a string literal. Nothing consumes these names.
 */
const generatedHeader = [
  '#   gone (`@deepseek-ai/dsh-fixture-generated-prose-ref` is removed, and',
  "#   gone (`@deepseek-ai/dsh-fixture-generated-prose-dq` is removed)",
  `#   gone (\`@deepseek-ai/dsh-fixture-generated-prose-tpl\` is removed)`,
];

/** The same prose WITHOUT a leading `#` is a documented limitation: it is left in the inventory. */
const proseWithoutHash = 'see @deepseek-ai/dsh-fixture-prose-no-hash for the old name';

// dsh-plugin-fixture-comment-only must NOT be reported

/* A `//` inside a string is content, not a comment: this one IS reported. */
const fakeComment = 'http://example.invalid/@deepseek-ai/dsh-fixture-url-string';

class Fixture {
  /** A `#` that does not begin a string's content is not a comment in JS (private field marker). */
  #privateField = 1;

  read() { return this.#privateField; }
}

void [realString, realRow, ownReal, trailing, generatedHeader, proseWithoutHash, fakeComment, Fixture];
