"""Make the kernel's delivery check tell the truth about a channel the owner closed.

The owner decided on 2026-07-14 to keep owner SMS off, and again on 2026-09-15:
"Keep SMS off, and I surface the urgent ones in the app."

check_delivery measures `MAX(sent_at)`. With SMS off that timestamp can only
advance when a send *escapes* the kill switch -- which is exactly what happened at
00:59 on 2026-09-15, twice, and the check then read "owner delivery flowing (newest
12.8h ago)". Today the escaped path is closed, so within 24 h the same check will
flip to CRITICAL "nothing delivered to the owner for 1d" and stay red forever. Both
readings are wrong: the first is a false green built on a defect, the second is a
false red about a channel he deliberately turned off. An alarm that can never go
green is an alarm that gets ignored (L5).

So: read the switch the app itself reads, derive its path from the database path so
kernel and sender cannot disagree, and measure the channel he chose instead -- the
app surface whose payload the badge renders. CRITICAL is reserved for "there is no
channel to him at all": SMS off *and* no payload or a stale one. SMS off with a
current surface is not a fault, it is a decision, and the summary says which.
"""

from __future__ import annotations

import pathlib
import sys

SENT = pathlib.Path("/home/zabz/ceo-kernel/ck/sentinel.py")

HELPERS_ANCHOR = '''def check_delivery(
    max_age_hours: float = 24.0,
    max_draft_hours: float = 72.0,
) -> Finding:'''

HELPERS_REPLACE = '''def _owner_sms_switch() -> tuple[bool, str]:
    """(is owner SMS off by the owner's own decision, evidence).

    Reads the file the app's sms_service checks at its send choke point -- derived
    from the database path rather than hard-coded, so the kernel and the sender
    cannot disagree about whether the owner's channel is on. An absent or unreadable
    switch means the channel is ON: the safe direction here is to keep the alarm,
    never to assume an exemption.
    """
    import datetime as _dt
    import pathlib as _p

    path = _p.Path(sources.AUTHORITATIVE_DB).parent / "OWNER_SMS_KILL_SWITCH"
    try:
        if not path.exists():
            return False, f"no switch file at {path}"
        when = _dt.datetime.fromtimestamp(
            path.stat().st_mtime, _dt.timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")
        return True, f"{path.name} present, written {when}"
    except OSError as exc:
        return False, f"switch unreadable ({exc}) -- treating SMS as on"


def _badge_payload_age_minutes() -> float | None:
    """Minutes since the app's badge payload was last written, or None if absent.

    This is the surface the owner actually looks at, so its freshness is the thing
    that decides whether anything can reach him while SMS is off.
    """
    import os
    import pathlib as _p
    import time

    state = _p.Path(
        os.environ.get("CEO_KERNEL_STATE", str(_p.Path.home() / "ceo-kernel-var"))
    )
    payload = state / "latest.json"
    try:
        if not payload.exists():
            return None
        return (time.time() - payload.stat().st_mtime) / 60.0
    except OSError:
        return None


def check_delivery(
    max_age_hours: float = 24.0,
    max_draft_hours: float = 72.0,
    max_badge_minutes: float = 45.0,
) -> Finding:'''

METRICS_ANCHOR = '''        "oldest_pending_email_draft": oldest_draft,
    }

    problems: list[str] = []
    draft_problems: list[str] = []

    if sent_age_h is None:
        problems.append("no message has ever been delivered to the owner")
    elif sent_age_h > max_age_hours:
        problems.append(
            f"nothing delivered to the owner for {sent_age_h/24:.0f}d "
            f"(newest sent {msg_sent.value})"
        )
        if int(msg_held.value or 0):
            problems.append(f"{int(msg_held.value)} message(s) waiting undelivered")'''

METRICS_REPLACE = '''        "oldest_pending_email_draft": oldest_draft,
    }

    # Whether the owner's SMS channel is supposed to be on at all. He closed it on
    # 2026-07-14 and confirmed it on 2026-09-15. Measuring a channel he deliberately
    # shut is not a health signal.
    sms_off, sms_evidence = _owner_sms_switch()
    badge_age_min = _badge_payload_age_minutes()
    metrics["owner_sms_off"] = sms_off
    metrics["owner_sms_off_evidence"] = sms_evidence
    metrics["badge_payload_age_minutes"] = (
        round(badge_age_min, 1) if badge_age_min is not None else None
    )

    problems: list[str] = []
    draft_problems: list[str] = []
    surface_problems: list[str] = []

    if sms_off:
        # SMS silence is his decision, so it is not a fault. What can still be a
        # fault is the surface he chose instead: if its payload has stopped being
        # written, nothing reaches him on any channel and that IS critical.
        if badge_age_min is None:
            surface_problems.append(
                "owner SMS are off by his decision and no badge payload exists -- "
                "there is no channel to him at all"
            )
        elif badge_age_min > max_badge_minutes:
            surface_problems.append(
                f"owner SMS are off by his decision and the app surface is stale "
                f"(payload written {badge_age_min/60:.1f}h ago, expected "
                f"<{max_badge_minutes/60:.1f}h)"
            )
    elif sent_age_h is None:
        problems.append("no message has ever been delivered to the owner")
    elif sent_age_h > max_age_hours:
        problems.append(
            f"nothing delivered to the owner for {sent_age_h/24:.0f}d "
            f"(newest sent {msg_sent.value})"
        )
        if int(msg_held.value or 0):
            problems.append(f"{int(msg_held.value)} message(s) waiting undelivered")'''

SURFACE_ANCHOR = '''    if problems:
        return Finding(
            check="delivery",
            severity=CRITICAL,
            ok=False,
            summary="nothing is reaching the owner: "
            + "; ".join(problems + draft_problems),'''

SURFACE_REPLACE = '''    if surface_problems:
        return Finding(
            check="delivery",
            severity=CRITICAL,
            ok=False,
            summary="the owner cannot be reached: " + "; ".join(surface_problems),
            metrics=metrics,
            refusals=refusals,
            provenance=prov,
        )
    if problems:
        return Finding(
            check="delivery",
            severity=CRITICAL,
            ok=False,
            summary="nothing is reaching the owner: "
            + "; ".join(problems + draft_problems),'''

FINAL_ANCHOR = '''    return Finding(
        check="delivery",
        severity=INFO,
        ok=True,
        summary=f"owner delivery flowing (newest {sent_age_h:.1f}h ago)",
        metrics=metrics,
        provenance=prov,
    )'''

FINAL_REPLACE = '''    if sms_off:
        held_n = int(msg_held.value or 0)
        if badge_age_min is None:
            badge_note = "app surface: no payload on this host"
        else:
            badge_note = f"app surface last written {badge_age_min:.0f} min ago"
        return Finding(
            check="delivery",
            severity=INFO,
            ok=True,
            summary=(
                "owner SMS off by his decision ("
                + sms_evidence
                + f"); the app surface is the channel -- {badge_note}, "
                f"{held_n} held item(s) for him, none of them a delivery fault"
            ),
            metrics=metrics,
            provenance=prov,
        )
    return Finding(
        check="delivery",
        severity=INFO,
        ok=True,
        summary=f"owner delivery flowing (newest {sent_age_h:.1f}h ago)",
        metrics=metrics,
        provenance=prov,
    )'''

EDITS = [
    (HELPERS_ANCHOR, HELPERS_REPLACE, "sentinel.py: switch + payload helpers"),
    (METRICS_ANCHOR, METRICS_REPLACE, "sentinel.py: decision-aware problems"),
    (SURFACE_ANCHOR, SURFACE_REPLACE, "sentinel.py: CRITICAL only when no channel exists"),
    (FINAL_ANCHOR, FINAL_REPLACE, "sentinel.py: report the decision instead of a false green"),
]


def main() -> int:
    text = SENT.read_text(encoding="utf-8")
    for old, new, label in EDITS:
        count = text.count(old)
        if count != 1:
            print(f"REFUSE {label}: anchor count {count} (expected 1)")
            return 2
        if new in text:
            print(f"REFUSE {label}: replacement already present")
            return 2
        text = text.replace(old, new, 1)  # accumulate, never write from a stale copy
        print(f"planned  {label}")
    SENT.write_text(text, encoding="utf-8")
    print(f"WROTE {SENT}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
