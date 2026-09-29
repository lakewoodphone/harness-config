#!/usr/bin/env bash
# FIXTURE for tests/guards/comment-refs.mjs — shell `#` comments, and `#` inside a string.

# @deepseek-ai/dsh-fixture-sh-comment must NOT be reported
BIN="@deepseek-ai/dsh-fixture-sh-string"
OWN="dsh-plugin-fixture-sh-own"
QUOTED='a literal # @deepseek-ai/dsh-fixture-sh-hash-in-string stays content'

echo "$BIN" "$OWN" "$QUOTED" # @deepseek-ai/dsh-fixture-sh-trailing must NOT be reported
