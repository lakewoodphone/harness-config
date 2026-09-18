"""Foreign absolute paths are honoured only when a root of that shape is approved.

The fail-closed patch blocked every foreign absolute path, which fixed two of the three failing
tests and broke the third: `test_sanitize_tool_call_out_of_workspace` explicitly approves
`C:\\Users\\ezabz\\Downloads` as an extra gateway root and then expects a Windows path under it to be
preserved. That is a real cross-platform configuration story (one gateway config can be used on the
Windows laptop and the Linux server), so the rule is:

    a path that is absolute on another platform is allowed only if an approved root is itself of
    that shape; otherwise it is blocked.

On the Linux authority the extra root is normalised to `<repo>/C:\\Users\\ezabz\\Downloads`, so its
*name* is the foreign shape and the path resolves under it. With no foreign root approved -- the
default -- `C:\\Users\\...` and `/etc/passwd` stay blocked, and traversal is already handled by
`resolve()`.
"""

from __future__ import annotations

import pathlib
import sys

GW = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "services" / "ai_gateway.py"

ANCHOR = '''        if not candidate.is_absolute():
            if _looks_absolute_elsewhere(normalized):
                # Fail CLOSED. Quietly rooting a foreign absolute path inside the workspace made
                # this guard answer "inside approved roots" for `C:\\\\Users\\\\...\\\\Downloads\\\\f.txt`
                # on Linux (and for `/etc/passwd` on Windows) and let the call through -- three
                # failing tests, measured 2026-09-15. Returning it unresolved makes the caller's
                # subpath test fail, so the call is blocked with its path in the reason.
                return candidate
            candidate = approved_roots[0] / candidate'''

REPLACE = '''        if not candidate.is_absolute():
            if _looks_absolute_elsewhere(normalized):
                # A path absolute on another platform is honoured only when a root of that same
                # shape is explicitly approved (one gateway config can serve the Windows laptop
                # and this Linux server). Quietly rooting it inside the workspace -- which is what
                # happened before -- made the guard answer "inside approved roots" for
                # `C:\\Users\\...\\Downloads\\f.txt` on Linux and for `/etc/passwd` on Windows and let
                # the call through. With no foreign root approved (the default) this stays blocked.
                foreign = [
                    root
                    for root in approved_roots
                    if _looks_absolute_elsewhere(str(root))
                    or _looks_absolute_elsewhere(root.name)
                ]
                if not foreign:
                    return candidate
                return Path(str(foreign[0])) / candidate
            candidate = approved_roots[0] / candidate'''


def main() -> int:
    text = GW.read_text(encoding="utf-8")
    if text.count(ANCHOR) != 1:
        print(f"REFUSE: anchor count {text.count(ANCHOR)} (expected 1)")
        return 2
    if "foreign = [" in text:
        print("REFUSE: already applied")
        return 2
    GW.write_text(text.replace(ANCHOR, REPLACE, 1), encoding="utf-8")
    print(f"WROTE {GW}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
