#!/usr/bin/env python3
"""Keep the phone's workspace registered, and give the owner a name that means something.

WHY A KEEPER AND NOT A ONE-TIME EDIT
The workspace list is host state in `$DSH_HOME/storages/workspace.json` — not in git, not derived
from anything. A machine rebuilt from `harness-config`, a wiped `~/.dsh`, or a session that
archives the last workspace can take it away silently, and the symptom is a phone that asks the
owner to choose a workspace on every new conversation. That is the "component that can silently
disappear" pattern this repo already keeps for client plugins (DECISIONS D38), so it gets the same
treatment: a script that checks and repairs, and is safe to run on every boot.

WHAT IT DOES NOT DO
It does not touch the older `_scratch` workspace. Nine sessions record it as their working
directory, and DSH REFUSES to open a session whose stored cwd no longer resolves — so renaming or
moving it would make the owner's own history unopenable. The cost of keeping it is one entry in a
list.

The engine holds this store in memory, so the edit is done with the engine stopped and started
again. That is a ~5 second gap and it only happens when the workspace is actually missing.

Usage: ensure-phone-workspace.py [--check]   (exit 1 under --check when a repair is needed)
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import uuid

PHONE_PATH = pathlib.Path(os.environ.get("PHONE_WORKSPACE_PATH", str(pathlib.Path.home() / "phone")))
PHONE_TITLE = "Phone"
DSH_HOME = pathlib.Path(os.environ.get("DSH_HOME", str(pathlib.Path.home() / ".dsh")))
STORE = DSH_HOME / "storages" / "workspace.json"

README = """# phone — where the harness works when you talk to it from your iPhone

**Deliberately not a git checkout.** A session started from the phone can run shell commands in its
working directory, and pointing that at a repository of the company's code would let a phone
conversation modify real code by accident. This directory is the agent's desk for phone
conversations: notes, drafts, and throwaway scripts land here and nothing here is load-bearing.

Registered as a DSH workspace titled **Phone**, so a new conversation lands somewhere whose name
means what it is. The older `_scratch` workspace stays registered because nine sessions record it as
their working directory and DSH cannot open a session whose directory is gone.
"""


def systemctl(*args: str) -> None:
    """Best effort: sudo when it is passwordless, plain systemctl otherwise."""
    for prefix in (["sudo", "-n", "systemctl"], ["systemctl"]):
        try:
            if subprocess.run([*prefix, *args], capture_output=True, timeout=60).returncode == 0:
                return
        except Exception:  # noqa: BLE001 - a host without systemd is not an error here
            continue


def main() -> int:
    check_only = "--check" in sys.argv

    PHONE_PATH.mkdir(parents=True, exist_ok=True)
    readme = PHONE_PATH / "README.md"
    if not readme.exists() and not check_only:
        readme.write_text(README, encoding="utf-8")

    if not STORE.exists():
        print(f"no workspace store at {STORE} — is the enum running with a different DSH_HOME?")
        return 1 if check_only else 0

    data = json.loads(STORE.read_text(encoding="utf-8"))
    if data.get("unit", {}).get("name") != "workspace" or "workspaces" not in data.get("tables", {}):
        print("unexpected workspace store shape - refusing to touch it", file=sys.stderr)
        return 1

    workspaces = data["tables"]["workspaces"]
    registered = {w.get("path") for w in workspaces.values()}
    if str(PHONE_PATH) in registered:
        print(f"ok: {PHONE_PATH} is registered as a workspace")
        return 0

    print(f"missing: {PHONE_PATH} is not a registered workspace")
    if check_only:
        return 1

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(STORE, STORE.with_suffix(f".json.bak-{stamp}"))
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    wid = str(uuid.uuid4())
    workspaces[wid] = {
        "path": str(PHONE_PATH),
        "title": PHONE_TITLE,
        "sessionIds": [],
        "createdAt": now,
        "updatedAt": now,
    }
    data["global"].setdefault("workspaceIds", []).insert(0, wid)
    STORE.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"registered {PHONE_PATH} as '{PHONE_TITLE}' ({wid[:8]}), first in the order; backup written")

    # The engine caches this store in memory and would write its own copy back over the edit.
    systemctl("stop", "phone-engine.service")
    systemctl("start", "phone-engine.service")
    print("phone-engine.service restarted so the new workspace is the one it serves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
