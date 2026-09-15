#!/usr/bin/env python3
"""Stop the draft loop replying to machines, and expire what is too old to send.

Evidence (secratary, 2026-09-14, email_drafts): 64 drafts stuck in pending_review,
almost all replies to automated senders. The gate `_is_noreply_sender` existed but
its pattern list only caught literal "noreply" spellings, so the drafter wrote
replies to enews@em.fultonbank.com, notice@info.aliexpress.com,
onlinebanking@ealerts.bankofamerica.com, hello@usmobile.com, developer@groq.co,
s-<hash>@relay.walmart.com, reply+<hash>@messaging.yelp.com and
failed-payments+acct_...@stripe.com. One "draft" was not a reply at all. And
email_drafts has carried expires_at since it was written, but nothing ever read
it, so June drafts were still awaiting a human in September.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

# ── 1. the noreply gate ────────────────────────────────────────────────────
OLD_GATE = '''_NOREPLY_SENDER_PATTERNS: list[str] = [
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "voicemail@dialpad.com", "bot@", "auto-reply", "auto_reply",
    "gustonoreply", "notifications@", "notification@",
    "alerts@", "alert@", "bounces@", "bounce@",
]


def _is_noreply_sender(sender: str) -> bool:
    """Return True if sender is a noreply/service address."""
    sender_lower = (sender or "").lower()
    return any(p in sender_lower for p in _NOREPLY_SENDER_PATTERNS)
'''

NEW_GATE = '''_NOREPLY_SENDER_PATTERNS: list[str] = [
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "voicemail@dialpad.com", "bot@", "auto-reply", "auto_reply",
    "gustonoreply", "notifications@", "notification@",
    "alerts@", "alert@", "bounces@", "bounce@",
    # 2026-09-14: the list above caught only literal "noreply" spellings, so the
    # drafter wrote replies to bank alerts, marketplace relays and payment
    # failures. 64 of those sat pending_review, unsendable, for up to three
    # months. Matched as substrings against the whole "Name <addr>" header.
    "mailer-daemon", "postmaster@", "automated@", "failed-payments",
    "enews@", "news@", "newsletter@", "marketing@", "updates@", "update@",
    "notice@", "announce@", "transaction@", "statement@", "epay@",
    "billing@", "invoice@", "receipt@", "receipts@", "payments@",
    "service@", "accounts@", "account@", "reply+", "relay.",
    # domains that only ever send machine mail
    "@txt.voice.google.com", "@messaging.yelp.com", "@em.fultonbank.com",
    "@ealerts.bankofamerica.com", "@aliexpress.com", "@telnyx.com",
    "@netlify.com", "@groq.co", "@usmobile.com", "@stripe.com",
    "@amazon.com", "@ebay.com", "@paypal.com", "@americanexpress.com",
    "@amex.com", "@gusto.com", "@deepinfra.com", "@kinguin.net",
]


def _is_noreply_sender(sender: str) -> bool:
    """Return True if sender is an automated address that cannot receive a reply.

    Deliberately errs toward blocking: a suppressed draft costs nothing, while a
    draft sent to a payment-failure bot is worse than useless. Anything blocked
    here still reaches the owner as mail; only the auto-draft is skipped.
    """
    sender_lower = (sender or "").lower()
    return any(p in sender_lower for p in _NOREPLY_SENDER_PATTERNS)
'''

OLD_CALL = '''        # Draft generation for actionable emails.
        # Blocked for: (a) noreply senders, (b) voicemail notifications.
        if (
            sub_category in DRAFT_SUB_CATEGORIES
            and not _is_noreply_sender(sender)
            and not _voicemail_intercepted
        ):'''

NEW_CALL = '''        # Draft generation for actionable emails.
        # Blocked for: (a) automated senders, (b) voicemail notifications.
        if (
            sub_category in DRAFT_SUB_CATEGORIES
            and not _is_noreply_sender(sender)
            and not _voicemail_intercepted
        ):'''

OLD_ELSE = '''        if (
            sub_category in FOLLOWUP_TASK_SUB_CATEGORIES'''

NEW_ELSE = '''        elif (
            sub_category in DRAFT_SUB_CATEGORIES
            and not _voicemail_intercepted
            and _is_noreply_sender(sender)
        ):
            # Say so rather than skipping silently: without this the loop looks
            # like it simply had nothing to do.
            actions_taken.append("draft_skipped_automated_sender")

        if (
            sub_category in FOLLOWUP_TASK_SUB_CATEGORIES'''

# ── 2. internal notes must not become drafts ───────────────────────────────
OLD_GEN = '''    draft_text = _generate_draft_text(
        sender=sender,
        subject=subject,
        body_text=body_text,
        account_email=account_email,
        settings=settings,
    )
    if not draft_text:
        return {"ok": False, "error": "Draft generation returned empty text"}
'''

NEW_GEN = '''    draft_text = _generate_draft_text(
        sender=sender,
        subject=subject,
        body_text=body_text,
        account_email=account_email,
        settings=settings,
    )
    if not draft_text:
        return {"ok": False, "error": "Draft generation returned empty text"}

    # Never turn a note ABOUT the mail into a sendable draft. On 2026-09-14 a
    # pending draft's entire body was "No reply needed (cryptic internal message:
    # 'Device 45 says device 8')." -- written into Gmail's Drafts folder, where a
    # human would eventually have sent it.
    if _looks_like_internal_note(draft_text):
        log.info("draft skipped: generated text is a note about the mail, not a reply")
        return {"ok": False, "error": "internal_note_not_a_reply"}
'''

OLD_SANITIZE = '''def _sanitize_draft_text(text: str) -> str:'''

NEW_SANITIZE = '''_INTERNAL_NOTE_RE = re.compile(
    r"(no\\s+reply\\s+needed|cryptic\\s+internal|internal\\s+message\\s*:|"
    r"do\\s+not\\s+reply|nothing\\s+to\\s+reply|no\\s+action\\s+(?:is\\s+)?needed)",
    re.IGNORECASE,
)


def _looks_like_internal_note(text: str) -> bool:
    """True when the model wrote a note about the mail instead of a reply to it."""
    stripped = (text or "").strip()
    if not stripped:
        return True
    return bool(_INTERNAL_NOTE_RE.search(stripped))


def _sanitize_draft_text(text: str) -> str:'''

# ── 3. enforce the expiry the table has always carried ─────────────────────
OLD_SWEEP_DICT = '''        "terminal_waiting_steps_cleaned": 0,
    }'''
NEW_SWEEP_DICT = '''        "terminal_waiting_steps_cleaned": 0,
        "drafts_expired": 0,
    }'''

OLD_SWEEP_CALL = '''    summary["stale_released"] = _release_stale_claims(conn, _db_lock)'''
NEW_SWEEP_CALL = '''    summary["drafts_expired"] = _close_expired_drafts(conn, _db_lock)
    summary["stale_released"] = _release_stale_claims(conn, _db_lock)'''

OLD_SWEEP_FN = '''def run_lifecycle_sweep(db_url: str) -> dict:'''
NEW_SWEEP_FN = '''def _close_expired_drafts(conn, lock) -> int:
    """Close email drafts whose own expires_at has passed.

    email_drafts has carried expires_at since it was created and nothing ever
    read it, so drafts from 2026-06 were still pending_review on 2026-09-14,
    waiting for a review that was never offered. A draft too old to send is not
    a pending decision; it is clutter in the only queue the owner reads.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with lock:
            cur = conn.execute(
                "UPDATE email_drafts SET status = 'expired', "
                "rejection_reason = coalesce(rejection_reason, 'expired before review') "
                "WHERE status = 'pending_review' "
                "AND expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            conn.commit()
            return int(cur.rowcount or 0)
    except Exception as exc:
        log.warning("lifecycle sweep: draft expiry failed: %s", exc)
        return 0


def run_lifecycle_sweep(db_url: str) -> dict:'''

EDITS = [
    ("app/services/email_actions.py", OLD_GATE, NEW_GATE),
    ("app/services/email_actions.py", OLD_CALL, NEW_CALL),
    ("app/services/email_actions.py", OLD_ELSE, NEW_ELSE),
    ("app/services/email_drafts.py", OLD_GEN, NEW_GEN),
    ("app/services/email_drafts.py", OLD_SANITIZE, NEW_SANITIZE),
    ("app/services/lifecycle_sweep.py", OLD_SWEEP_DICT, NEW_SWEEP_DICT),
    ("app/services/lifecycle_sweep.py", OLD_SWEEP_CALL, NEW_SWEEP_CALL),
    ("app/services/lifecycle_sweep.py", OLD_SWEEP_FN, NEW_SWEEP_FN),
]

TEST = '''"""The draft loop must not reply to machines, or send notes to customers.

Evidence, secratary 2026-09-14: 64 drafts sat in pending_review, almost all of
them replies to automated senders, one of them an internal annotation written
into Gmail's Drafts folder. Every address below is one that actually appeared in
email_drafts and produced a draft.
"""

import pytest

from app.services.email_actions import _is_noreply_sender
from app.services.email_drafts import _looks_like_internal_note

# Senders that produced drafts and should never produce one again.
AUTOMATED = [
    "Fulton Bank, N.A. <enews@em.fultonbank.com>",
    "AliExpress <notice@info.aliexpress.com>",
    "AliExpress <transaction@notice.aliexpress.com>",
    "Bank of America <onlinebanking@ealerts.bankofamerica.com>",
    "Team at US Mobile <hello@usmobile.com>",
    "Groq <developer@groq.co>",
    "Bison Commerce <s-B645CF118DEA4CE481C05E8B79B21C19@relay.walmart.com>",
    "Yelp Inbox <reply+97a7d8e8af5c462fa28fd9d9f1a11d1a@messaging.yelp.com>",
    "Deep Infra Inc. <failed-payments+acct_1M7T5mAfqHmFttwV@stripe.com>",
    "\\"(732) 444-7361\\" <17325691594.17324447361.8C7QxC1K1j@txt.voice.google.com>",
    "no-reply@amazon.com",
    "service@paypal.com",
]

# Real people who wrote in and must still get drafts.
HUMANS = [
    "Michelle Wasserlauf <mwasserlauf@heichalhatorah.org>",
    "moishe bachrach <moshbachrach@gmail.com>",
    "Yocheved Yanofsky <chevedy@gmail.com>",
    "Ivan Luna <ivan.luna@dialpad.com>",
]


@pytest.mark.parametrize("sender", AUTOMATED)
def test_automated_senders_are_blocked(sender):
    assert _is_noreply_sender(sender) is True, sender


@pytest.mark.parametrize("sender", HUMANS)
def test_real_people_are_not_blocked(sender):
    assert _is_noreply_sender(sender) is False, sender


def test_substring_traps_are_not_triggered():
    """A short pattern must not accidentally swallow ordinary names."""
    for sender in ("james-smith@gmail.com", "sarah.levi@outlook.com",
                   "moshe-berkowitz@yahoo.com"):
        assert _is_noreply_sender(sender) is False, sender


def test_internal_note_is_not_a_draft():
    note = "No reply needed (cryptic internal message: 'Device 45 says device 8')."
    assert _looks_like_internal_note(note) is True


def test_a_real_reply_is_a_draft():
    reply = (
        "Hi Michelle,\\n\\nThank you for the note - I'm sorry for the delay in getting "
        "back to you. I'll call you at 646-702-8577 shortly to finalize the order."
    )
    assert _looks_like_internal_note(reply) is False
'''


def main() -> int:
    # validate everything first, then write
    for rel, old, new in EDITS:
        src = pathlib.Path(rel).read_text(encoding="utf-8")
        assert src.count(old) == 1, f"{rel}: expected 1 match, found {src.count(old)} for {old[:60]!r}"

    # names the new code depends on must actually exist in the modules patched
    for rel, name in (
        ("app/services/email_actions.py", "actions_taken"),
        ("app/services/email_drafts.py", "log = "),
        ("app/services/email_drafts.py", "import re"),
        ("app/services/lifecycle_sweep.py", "log = "),
    ):
        assert name in pathlib.Path(rel).read_text(encoding="utf-8"), f"{rel}: {name!r} not found"

    for rel, old, new in EDITS:
        path = pathlib.Path(rel)
        backup = BACKUPS / f"{path.name}.{STAMP}.bak"
        if not backup.exists():
            shutil.copy(rel, backup)
        path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        print(f"  patched {rel}")

    tests = pathlib.Path("tests/test_draft_gate.py")
    tests.write_text(TEST, encoding="utf-8")
    print("  wrote tests/test_draft_gate.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
