"""The workspace-folder URI decoder was Windows-only, so every path was mangled on Linux.

Measured 2026-09-15:

    input  : file:///tmp/tmpr4a5qchs/Code/personal-secretary-mvp
    decoded: 'tmp\\tmpr4a5qchs\\Code\\personal-secretary-mvp'      <- leading slash gone
    want   : '/tmp/tmpr4a5qchs/Code/personal-secretary-mvp'

`_decode_folder_uri` did `re.sub(r"^file:///", "", uri)` and then `uri.replace("/", "\\")`, which is
right for `file:///c%3A/Users/...` and wrong for anything else. On the Linux authority every
workspace `folder_path` therefore came out as `home\\zabz\\code\\...` -- a string that matches no
path any consumer holds, so per-workspace chat attribution silently found nothing. The failing test
`test_discover_workspaces_aggregates_matching_workspace_profiles` was right and the code was wrong.

Fixed by decoding to the *host's* form: on Windows, `file:///c:/Users/x` -> `C:\\Users\\x`; on
POSIX, `file:///home/zabz/x` -> `/home/zabz/x` with the separators left alone.
"""

from __future__ import annotations

import pathlib
import sys

EX = pathlib.Path.home() / "personal-secretary-mvp" / "scripts" / "vscode_chat_extractor.py"

ANCHOR = '''def _decode_folder_uri(uri: str) -> str:
    """Convert file:///c%3A/Users/... to a readable path like C:\\\\Users\\\\..."""
    if not uri:
        return ""
    uri = unquote(uri)
    uri = re.sub(r"^file:///", "", uri)
    # c:/Users/... \u2192 C:\\Users\\...
    if len(uri) >= 2 and uri[1] == ":":
        uri = uri[0].upper() + uri[1:]
    return uri.replace("/", "\\\\")'''

REPLACE = '''def _decode_folder_uri(uri: str) -> str:
    """Convert a VS Code workspace folder URI to a path in THIS host's form.

    `file:///c%3A/Users/x` -> `C:\\\\Users\\\\x` on Windows, and `file:///home/zabz/x` ->
    `/home/zabz/x` on POSIX. The previous version stripped the leading slash and replaced
    every separator with a backslash, which is right for a Windows drive URI and wrong for
    everything else: on the Linux authority every workspace path decoded to
    `home\\\\zabz\\\\code\\\\...`, a string that matches no path a consumer holds, so chat
    attribution per workspace silently found nothing (measured 2026-09-15).
    """
    if not uri:
        return ""
    decoded = unquote(uri)
    if not decoded.lower().startswith("file://"):
        return decoded
    rest = decoded[len("file://"):]
    if os.name == "nt":
        rest = rest.lstrip("/")
        if len(rest) >= 2 and rest[1] == ":":
            rest = rest[0].upper() + rest[1:]
        return rest.replace("/", "\\\\")
    # POSIX (and anything else): VS Code writes an absolute path after `file://`; keep it
    # exactly as written, including the leading slash and the forward separators.
    return rest'''


def main() -> int:
    text = EX.read_text(encoding="utf-8")
    if text.count(ANCHOR) != 1:
        print(f"REFUSE: anchor count {text.count(ANCHOR)} (expected 1)")
        return 2
    if "in THIS host's form" in text:
        print("REFUSE: already applied")
        return 2
    EX.write_text(text.replace(ANCHOR, REPLACE, 1), encoding="utf-8")
    print(f"WROTE {EX}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
