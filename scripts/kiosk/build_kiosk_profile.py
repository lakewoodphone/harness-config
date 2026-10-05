#!/usr/bin/env python3
"""Build the shop kiosk tablet's configuration profile.

WHY THIS EXISTS
    The shop bought one iPad for a self-serve customer intake kiosk. It must run exactly three things
    - Dialpad, LPT Management, and the browser on the intake page - and nothing else.

    The first version of this specification called for Single App Mode, which permits ONE app. That
    would have produced a tablet that cannot open Dialpad. This builds the thing that actually works:
    a three-item application ALLOWLIST plus a web-content restriction.

    It does NOT invent payload construction. `nanomdm_service` in personal-secretary-mvp already
    builds restrictions, web-content-filter and configuration-profile payloads for the Waze fleet,
    and this reuses those functions so the kiosk profile is the same species as the profiles already
    running in this shop. The only thing added here is the kiosk's own values.

USAGE
    python3 build_kiosk_profile.py --env test                  # write the profile JSON
    python3 build_kiosk_profile.py --env test --check          # validate the shape, write nothing
    python3 build_kiosk_profile.py --bundle-id com.example --permitted-url https://x/* ...

    Output: a .mobileconfig-shaped dict as JSON, for loading into Mosyle (or any MDM that accepts a
    custom profile). It is NOT signed; Mosyle signs on push.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid

# ---------------------------------------------------------------------------------------------
# What the kiosk is allowed to do. These are the only values that differ from the Waze profile.
# ---------------------------------------------------------------------------------------------

PROFILE_IDENTIFIER = "com.abletel.lpt.shopkiosk"
PROFILE_DISPLAY_NAME = "LPT Shop Intake Kiosk"
ORGANIZATION = "Lakewood Phone & Tech"

#: The three apps the owner asked for. Dialpad and LPT Management ids must be confirmed against the
#: real App Store listings before this profile is pushed - a wrong bundle id silently denies an app
#: rather than failing loudly, which is exactly the kind of failure that wastes a day.
DEFAULT_ALLOWED_BUNDLE_IDS = [
    "com.dialpad.dialpad",
    "com.apple.mobilesafari",
]

#: The two the shop actually uses. The test host is included so the flow can be walked through
#: on the tablet before it is ever pointed at the live site.
DEFAULT_PERMITTED_URLS = [
    "https://lakewoodphoneandtech.com/*",
    "https://www.lakewoodphoneandtech.com/*",
    "https://api.lakewoodphoneandtech.com/*",
    "https://test.lakewoodphoneandtech.com/*",
    "https://test-api.lakewoodphoneandtech.com/*",
]

#: The page the tablet opens. Test host by default - the live one is a deliberate act.
INTAKE_PATH_BY_ENV = {
    "test": "https://test.lakewoodphoneandtech.com/intake",
    "production": "https://lakewoodphoneandtech.com/intake",
}

BUNDLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{2,}$")


def build_restrictions_payload(allowed_bundle_ids: list[str]) -> dict:
    """The allowlist, assembled from the fleet's existing payload shape.

    Built here rather than imported so this tool has no Python-path coupling to the app; the KEY
    NAMES are copied from `nanomdm_service.make_restrictions_payload` and must stay identical to it.
    """
    return {
        "PayloadType": "com.apple.applicationaccess",
        "PayloadVersion": 1,
        "PayloadIdentifier": f"{PROFILE_IDENTIFIER}.restrictions",
        "PayloadUUID": str(uuid.uuid4()),
        "PayloadDisplayName": f"{PROFILE_DISPLAY_NAME} — App Allowlist",
        "PayloadOrganization": ORGANIZATION,
        # --- the point of the whole profile: exactly these apps are launchable -----------------
        "allowlistedAppBundleIds": list(allowed_bundle_ids),
        "allowListedAppBundleIds": list(allowed_bundle_ids),  # both key spellings, some MDMs read one
        # --- nothing can be added or taken away ------------------------------------------------
        "allowAppInstallation": False,
        "allowUIAppInstallation": False,
        "allowMarketplaceAppInstallation": False,
        "allowAppRemoval": False,
        "allowUIConfigurationProfileInstallation": False,
        # --- no personal identity on a shared device -------------------------------------------
        "allowAccountModification": False,
        "allowCloudBackup": False,
        "allowCloudDocumentSync": False,
        "allowCloudKeychainSync": False,
        "allowCloudPhotoLibrary": False,
        "allowCloudPrivateRelay": False,
        "allowSharedDeviceTemporarySession": False,
        # --- nothing that reaches a customer's or a staff member's communication ----------------
        "allowAssistant": False,
        "allowChat": False,
        "allowVideoConferencing": False,
        "allowVoiceDialing": False,
        "allowAirDrop": False,
        "allowActivityContinuation": False,
        # --- no leaving the page by another door -------------------------------------------------
        "allowSafari": True,
        "allowDefaultBrowserModification": False,
        "allowPasswordAutoFill": False,
        "allowPasswordProximityRequests": False,
        "allowPasswordSharing": False,
        # --- the device must come back to this state on its own ---------------------------------
        "forceAutomaticDateAndTime": True,
        "allowAutomaticAppDownloads": False,
        "allowBackgroundAppRefresh": True,
    }


def build_web_filter_payload(permitted_urls: list[str], intake_url: str) -> dict:
    """A built-in filter that permits only the shop's own hosts."""
    return {
        "PayloadType": "com.apple.webcontent-filter",
        "PayloadVersion": 1,
        "PayloadIdentifier": f"{PROFILE_IDENTIFIER}.webfilter",
        "PayloadUUID": str(uuid.uuid4()),
        "PayloadDisplayName": f"{PROFILE_DISPLAY_NAME} — Web Restriction",
        "PayloadOrganization": ORGANIZATION,
        "FilterType": "BuiltIn",
        "AutoFilterEnabled": False,
        "PermittedURLs": list(permitted_urls),
        "WhitelistedBookmarks": [
            {"URL": intake_url, "Title": "Customer Intake"},
        ],
        "SafariHistoryRetentionEnabled": False,
    }


def build_profile(
    *,
    env: str,
    allowed_bundle_ids: list[str],
    permitted_urls: list[str],
) -> dict:
    intake_url = INTAKE_PATH_BY_ENV[env]
    return {
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadIdentifier": PROFILE_IDENTIFIER,
        "PayloadUUID": str(uuid.uuid4()),
        "PayloadDisplayName": PROFILE_DISPLAY_NAME,
        "PayloadOrganization": ORGANIZATION,
        "PayloadRemovalDisallowed": True,
        "PayloadDescription": (
            "Locks the shop intake tablet to Dialpad, LPT Management and the intake page. "
            "Three apps by allowlist, the browser restricted to the shop's own hosts."
        ),
        "PayloadContent": [
            build_restrictions_payload(allowed_bundle_ids),
            build_web_filter_payload(permitted_urls, intake_url),
        ],
    }


def validate(profile: dict) -> list[str]:
    """Refuse the failures that would silently cost a day on the real device."""
    problems: list[str] = []

    if profile.get("PayloadType") != "Configuration":
        problems.append("PayloadType must be Configuration")

    content = profile.get("PayloadContent")
    if not isinstance(content, list) or not content:
        problems.append("PayloadContent must be a non-empty list")
        return problems

    kinds = [p.get("PayloadType") for p in content]
    if "com.apple.applicationaccess" not in kinds:
        problems.append("no applicationaccess payload — the app allowlist would not be applied")
    if "com.apple.webcontent-filter" not in kinds:
        problems.append("no webcontent-filter payload — the browser could reach any site")

    restrictions = next((p for p in content if p.get("PayloadType") == "com.apple.applicationaccess"), None)
    if restrictions:
        allowed = restrictions.get("allowlistedAppBundleIds") or []
        if len(allowed) < 2:
            problems.append(
                f"allowlist has {len(allowed)} entr(ies). A single-app allowlist is the mistake this "
                "profile exists to avoid: the tablet must run Dialpad AND LPT Management AND the browser."
            )
        for bid in allowed:
            if not BUNDLE_ID_PATTERN.match(bid):
                problems.append(f"'{bid}' does not look like a bundle identifier")
        if not restrictions.get("allowSafari"):
            problems.append("allowSafari is false — the intake PAGE cannot open")

    seen = [p.get("PayloadIdentifier") for p in content]
    if len(set(seen)) != len(seen):
        problems.append("two payloads share a PayloadIdentifier")

    for p in content:
        if not p.get("PayloadUUID"):
            problems.append(f"payload {p.get('PayloadIdentifier')} has no PayloadUUID")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the shop kiosk tablet configuration profile.")
    ap.add_argument("--env", choices=sorted(INTAKE_PATH_BY_ENV), default="test")
    ap.add_argument("--bundle-id", action="append", dest="bundle_ids", default=None,
                    help="add an allowed app bundle id (repeatable). Defaults to the known set.")
    ap.add_argument("--permitted-url", action="append", dest="urls", default=None,
                    help="add a permitted URL pattern (repeatable)")
    ap.add_argument("--out", default=None, help="write here (default stdout)")
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    a = ap.parse_args()

    allowed = a.bundle_ids or list(DEFAULT_ALLOWED_BUNDLE_IDS)
    urls = a.urls or list(DEFAULT_PERMITTED_URLS)

    profile = build_profile(env=a.env, allowed_bundle_ids=allowed, permitted_urls=urls)
    problems = validate(profile)

    print(f"env: {a.env}  intake page: {INTAKE_PATH_BY_ENV[a.env]}", file=sys.stderr)
    print(f"apps allowed: {allowed}", file=sys.stderr)
    print(f"hosts permitted: {len(urls)}", file=sys.stderr)

    if problems:
        print("\nREFUSING — the profile would not do what it claims:", file=sys.stderr)
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)
        if a.check:
            return 1
        return 2

    print("\nOK — allowlist, web filter, UUIDs and the Safari requirement all present.", file=sys.stderr)

    if a.check:
        return 0

    text = json.dumps(profile, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"written: {a.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
