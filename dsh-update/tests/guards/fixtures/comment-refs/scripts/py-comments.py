# FIXTURE for tests/guards/comment-refs.mjs — the `#`-comment rule for Python.
# Names are invented on purpose; see the note in scripts/comment-shapes.mjs.

# @deepseek-ai/dsh-fixture-py-comment must NOT be reported
#!/usr/bin/env python3

import os  # @deepseek-ai/dsh-fixture-py-trailing must NOT be reported

STRING_REF = "@deepseek-ai/dsh-fixture-py-string"
OWN_REF = "dsh-plugin-fixture-py-own"
HASH_INSIDE_STRING = "port 3099 # @deepseek-ai/dsh-fixture-py-hash-in-string"

DOCSTRING = """A docstring is prose, not code:
# @deepseek-ai/dsh-fixture-py-docstring must NOT be reported
"""


def main() -> None:
    print(STRING_REF, OWN_REF, HASH_INSIDE_STRING, DOCSTRING, os.sep)


if __name__ == "__main__":
    main()
