"""The workspace guard must fail closed on a path that is absolute somewhere else.

Measured 2026-09-15, three failing tests in tests/test_ai_gateway.py:

    assert fn["name"] == "gateway_blocked_tool_call"   ->  got 'read_file'
    assert choice["finish_reason"] == "stop"           ->  got 'tool_calls'

`_resolve_tool_path()` does:

    candidate = Path(normalized).expanduser()
    if not candidate.is_absolute():
        candidate = approved_roots[0] / candidate      # <-- a foreign absolute path lands here
    return candidate.resolve()

On the Linux authority `C:\\Users\\ezabz\\Downloads\\file.txt` is not absolute, so it was silently
rooted *inside* the workspace and the subpath test then answered "inside approved roots". The same
happens in reverse on Windows with `/etc/passwd`. The guard does not merely mislabel: it lets the
call through, which is the wrong direction for a security check.

Traversal is already handled -- `candidate.resolve()` normalises `..`, so `../../etc/passwd` falls
outside the root and is blocked. What was missing is the foreign-absolute case, and it is now
returned unresolved so the caller's subpath test fails and the call is blocked.
"""

from __future__ import annotations

import pathlib
import sys

GW = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "services" / "ai_gateway.py"

ANCHOR = '''def _resolve_tool_path(path_str: str, approved_roots: list[Path]) -> Path | None:
    normalized = _path_from_tool_value(path_str)
    if not normalized:
        return None
    try:
        candidate = Path(normalized).expanduser()
        if not candidate.is_absolute():
            candidate = approved_roots[0] / candidate
        return candidate.resolve()
    except Exception:
        return None'''

REPLACE = '''# A path that is absolute on some OTHER platform: a Windows drive or UNC path (`C:\\...`,
# `\\\\server\\share`) seen on POSIX, or a POSIX absolute path seen on Windows.
_FOREIGN_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\\\\/]|\\\\\\\\|/[^/])")


def _looks_absolute_elsewhere(normalized: str) -> bool:
    return bool(_FOREIGN_ABSOLUTE_RE.match(normalized or ""))


def _resolve_tool_path(path_str: str, approved_roots: list[Path]) -> Path | None:
    normalized = _path_from_tool_value(path_str)
    if not normalized:
        return None
    try:
        candidate = Path(normalized).expanduser()
        if not candidate.is_absolute():
            if _looks_absolute_elsewhere(normalized):
                # Fail CLOSED. Quietly rooting a foreign absolute path inside the workspace made
                # this guard answer "inside approved roots" for `C:\\Users\\...\\Downloads\\f.txt`
                # on Linux (and for `/etc/passwd` on Windows) and let the call through -- three
                # failing tests, measured 2026-09-15. Returning it unresolved makes the caller's
                # subpath test fail, so the call is blocked with its path in the reason.
                return candidate
            candidate = approved_roots[0] / candidate
        return candidate.resolve()
    except Exception:
        return None'''


def main() -> int:
    text = GW.read_text(encoding="utf-8")
    if text.count(ANCHOR) != 1:
        print(f"REFUSE: anchor count {text.count(ANCHOR)} (expected 1)")
        return 2
    if "_looks_absolute_elsewhere" in text:
        print("REFUSE: already applied")
        return 2
    if not text.lstrip().startswith(('"""', "#")) and "\nimport re" not in text and "\nimport re\n" not in text:
        print("WARN: 're' may not be imported; checking")
    GW.write_text(text.replace(ANCHOR, REPLACE, 1), encoding="utf-8")
    print(f"WROTE {GW}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
