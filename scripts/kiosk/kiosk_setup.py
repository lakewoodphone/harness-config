#!/usr/bin/env python3
"""Take a shop kiosk tablet from "box on the desk" to "recorded in the fleet with a profile".

WHY THIS EXISTS
    A used iPad has one failure mode that cannot be fixed afterwards: it is still Activation Locked
    to a previous owner, or it is enrolled in somebody else's Apple Business Manager. No MDM can
    supervise such a device at any price. That failure is discoverable in two minutes and only
    inside the return window, so it should be the FIRST thing checked, not the last.

    This walks the order that actually matters, says plainly which step CANNOT be verified
    automatically, and refuses to pretend a step it cannot do.

WHAT IT DOES NOT DO
    It does not push a profile to a real device. Mosyle does that, through the ABM assignment. This
    records intent and checks the things that are checkable, and tells you the exact next action.

USAGE
    python3 kiosk_setup.py --serial ABC123XYZ                 # full checklist for one device
    python3 kiosk_setup.py --serial ABC123XYZ --register     # also record it in the fleet table
    python3 kiosk_setup.py --list                             # what is in the fleet now
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

DEVICE_CLASS = "lpt_shop_kiosk"
DEPARTMENT = "shop-counter"
DESIRED_PROFILE = "shop_kiosk_allowlist"
DISPLAY_NAME = "Shop intake kiosk"

DEFAULT_DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"

#: Steps that MUST be true before the device is any use. Each names who can do it and how it is
#: proved. `auto` means this tool can check it; `manual` means a human has to look and say so.
CHECKLIST = [
    (
        "serial is not Activation Locked",
        "manual",
        "On the device: Settings > General > About, or check the serial against Apple's coverage page. "
        "A device tied to someone else's Apple ID cannot be supervised by ANY MDM, at any price. "
        "THIS IS THE ONE THAT CANNOT BE FIXED LATER - do it inside the return window.",
    ),
    (
        "device appears in Apple Business Manager",
        "manual",
        "business.apple.com > Devices > search this serial. If it is not there, it must be added with "
        "Apple Configurator on the Mac, and only a device bought from an ABM-reporting reseller or "
        "added by hand can be supervised.",
    ),
    (
        "device is assigned to the Mosyle MDM service in ABM",
        "manual",
        "business.apple.com > the device > Edit MDM Server > assign to the same service that holds the "
        "Waze fleet. This is what makes the profile installable at all.",
    ),
    (
        "fleet registry accepts the kiosk device class",
        "auto",
        "mdm_fleet_registry must define lpt_shop_kiosk and allow shop_kiosk_allowlist for it. "
        "Until it does, the device cannot be recorded and _normalize_desired_profile raises.",
    ),
    (
        "the kiosk profile is built and valid",
        "auto",
        "scripts/kiosk/build_kiosk_profile.py --check must pass: three-app allowlist, web filter, "
        "and Safari allowed (without it the intake page cannot open).",
    ),
    (
        "the device is recorded in the fleet table",
        "auto",
        "mdm_fleet_devices gains a row: device_class, department, desired_profile, display_name, and "
        "profile_state='pending' until the device reports back.",
    ),
    (
        "profile_state reaches 'installed'",
        "manual",
        "Poll Mosyle until the device reports the profile applied. 'pending' forever means it never "
        "enrolled - most often because ABM assignment was skipped.",
    ),
    (
        "ON THE DEVICE: Dialpad opens",
        "manual",
        "This is the check the original single-app spec would have FAILED. If Dialpad will not open, "
        "the allowlist is wrong and the bundle id needs confirming.",
    ),
    (
        "ON THE DEVICE: LPT Management opens and the intake page loads",
        "manual",
        "Open both. The intake page must be reachable in the locked state, not only from a laptop.",
    ),
    (
        "ON THE DEVICE: nothing else is launchable, and a link that leaves the page dead-ends",
        "manual",
        "Try to leave deliberately. A redirect off-site must not be followable.",
    ),
    (
        "ON THE DEVICE: power-cycle with the cable out - it must come back locked, unattended",
        "manual",
        "An unattended tablet that comes back to the home screen after a power blip is not a kiosk.",
    ),
    (
        "ON THE DEVICE: one real submission on each of the three paths, and a label prints",
        "manual",
        "Card, in person, wait-to-speak. The in-person and wait-to-speak ones must be VISIBLY NOT PAID "
        "in the console. And a real label, not a request that reached the printer service.",
    ),
]


def registry_supports_kiosk() -> tuple[bool, str]:
    """Can the fleet registry even record this device class yet?"""
    path = "/home/zabz/personal-secretary-mvp/app/services/mdm_fleet_registry.py"
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as exc:
        return False, f"cannot read {path}: {exc}"
    if DEVICE_CLASS not in text:
        return False, f"'{DEVICE_CLASS}' is NOT defined in the registry — the device cannot be recorded"
    if DESIRED_PROFILE not in text:
        return False, f"'{DESIRED_PROFILE}' is NOT defined in the registry"
    return True, "registry defines the kiosk class and profile"


def profile_is_valid() -> tuple[bool, str]:
    here = os.path.dirname(os.path.abspath(__file__))
    tool = os.path.join(here, "build_kiosk_profile.py")
    if not os.path.exists(tool):
        return False, f"profile builder missing at {tool}"
    import subprocess

    r = subprocess.run([sys.executable, tool, "--check"], capture_output=True, text=True)
    if r.returncode == 0:
        return True, "profile builds and validates"
    return False, (r.stderr or r.stdout or "unknown failure").strip().splitlines()[-1]


def fleet_rows(db: str) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT serial_number, device_class, department, desired_profile, profile_state, display_name "
            "FROM mdm_fleet_devices ORDER BY device_class, serial_number"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def register(db: str, serial: str) -> str:
    """Record the device. Deliberately refuses to invent a class the registry does not know."""
    ok, why = registry_supports_kiosk()
    con = sqlite3.connect(db)
    try:
        cur = con.execute("SELECT serial_number FROM mdm_fleet_devices WHERE serial_number = ?", (serial,))
        if cur.fetchone():
            return f"already recorded: {serial}"
        if not ok:
            return f"REFUSED to record: {why}. Fix the registry first (see the checklist)."
        con.execute(
            "INSERT INTO mdm_fleet_devices "
            "(serial_number, device_class, department, desired_profile, profile_state, display_name, "
            " allowed_bundle_ids_json, metadata_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, '[]', ?, datetime('now'), datetime('now'))",
            (serial, DEVICE_CLASS, DEPARTMENT, DESIRED_PROFILE, DISPLAY_NAME,
             json.dumps({"source": "kiosk_setup.py", "kiosk": True})),
        )
        con.commit()
        return f"recorded: {serial} as {DEVICE_CLASS} / {DESIRED_PROFILE} / pending"
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Set up a shop kiosk tablet, in the order that matters.")
    ap.add_argument("--serial")
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        print(f"fleet devices in {a.db}:")
        for r in fleet_rows(a.db):
            print(f"  {r['serial_number']:<16} {r['device_class']:<18} {r['desired_profile']:<22} {r['profile_state']}")
        ok, why = registry_supports_kiosk()
        print(f"\nregistry kiosk support: {'YES' if ok else 'NO'} — {why}")
        return 0

    if not a.serial:
        ap.error("--serial is required (or --list)")

    serial = a.serial.strip().upper()
    print(f"KIOSK TABLET SETUP — serial {serial}\n")

    reg_ok, reg_why = registry_supports_kiosk()
    prof_ok, prof_why = profile_is_valid()
    auto = {"fleet registry accepts the kiosk device class": (reg_ok, reg_why),
            "the kiosk profile is built and valid": (prof_ok, prof_why)}

    recorded = {r["serial_number"] for r in fleet_rows(a.db)}
    auto["the device is recorded in the fleet table"] = (
        serial in recorded,
        "recorded" if serial in recorded else "not recorded yet — run with --register",
    )

    done = 0
    for label, kind, how in CHECKLIST:
        if kind == "auto":
            ok, why = auto.get(label, (False, "unknown"))
            mark = "OK  " if ok else "TODO"
            if ok:
                done += 1
            print(f"[{mark}] {label}\n        {why}")
        else:
            print(f"[ ?? ] {label}\n        {how}")
    print(f"\n{len(CHECKLIST)} steps; {done} verifiable step(s) already satisfied.")

    if a.register:
        print()
        print(register(a.db, serial))

    print("\nThe checks marked ? cannot be done by software. Do them in order; the first two must pass")
    print("inside the return window or the device is not a shop asset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
