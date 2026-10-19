# The mirror — the live owner-text stack, versioned

`/root/bin` on `secratary-cloud` is **not a git repository**. Every text to the owner passes through
`owner_text_relay.py`, which lived there in exactly one place: no history, no review, no diff, and
one `P4254`-shaped restore away from silently reverting a fix under a session that had just verified
it — which is exactly what happened twice on 2026-10-15 (`OWNER-TEXT-AUDIT-2026-10-15.md` §2 note 12).

This directory is the remedy: a byte-for-byte mirror of the live files, a hash manifest, and two
scripts — one that proves the mirror matches what is running, one that deploys a change from here.

**The mirror is not the source of truth. It is the *record* of what was live, and the thing you edit
before you deploy.** Direction is always: edit here → deploy → verify. Never the reverse.

```
mirror/verify-owner-text.sh              # does the live stack still match MANIFEST.sha256?
mirror/deploy-owner-text.sh <file>...    # copy from here to /root/bin, backup, re-hash, compile
mirror/MANIFEST.sha256                   # the hashes as mirrored, 2026-10-18T01:33Z
```

## Why a directory and not a diff against the repo

`scripts/text-channel/*.py` (the `sms-inbox.py` / `textctx.py` / `textsend.py` family) mirrors
`/home/zabz/bin` on the **office box**, which has been the frozen rollback anchor since
2026-10-11. Those copies describe a host that no longer runs the channel. They are kept because
they are the audit trail of how the channel got here; the live path is `/root/bin` on the
authority, and `mirror/` is where it is tracked.

## The rule this directory exists to enforce

> Before you edit a file under `/root/bin`, hash it. After you edit it, hash it again. The next day,
> hash it a third time.

`verify-owner-text.sh` exits **0** (in sync), **1** (at least one live file differs from the
manifest — either someone edited live, or `P4254` restored it), or **2** (a file is missing). It
prints the diff per file. Run it at the start of any session that touches the channel, and again
before you report anything as live.

## The transition of 2026-10-19 — what moved, and why

The manifest was refreshed to the live stack at **17:02Z** by the round-3 owner-text overhaul.
Six files moved. Recorded here because re-freezing a manifest without writing down what moved is
how a mirror becomes a comfortable fiction.

| file | why it moved |
|---|---|
| `owner_text_relay.py` | three guards: **quiet hours** (23:00–07:30 America/New_York, drops rather than queues, bypassed by `urgent`/`critical`/`stuck`, by `class_hint="reply"` and by his own inbound text inside 60 min); **credential_request** (a credential noun AND a request verb in the same sentence — a status report stays a message); **internal_prose** (`path`, `instruction`, `machine`, `addressed`, `ack`, `truncated`), plus `record_inbound()` so the awake bypass is reachable |
| `textdecide.py` | `is_non_answer()` and `attribute_reply()` with `n_open`/`learnable`/`closes`; `build_alias()` refuses a non-answer, an inferred match with 2+ asks open, the ask's own guess and the literal `unknown`; `category_from(strict=True)` |
| `merchant_resolve.py` | a non-answer is not an answer; a known vendor with no category is not `solved`; a new **descriptor** rung; `provisional` and `purchase is False` are evidence, not determinations; the DeepSeek vendor entry no longer files the AI bill as scientific supplies |
| `preask.py` | the ladder counted any `solved=True` as a solved rung regardless of confidence, so a 0.55 provisional reading marked the ladder complete |
| `cfo-ask.py` | `resolved_enough()` is per-source (descriptor 0.75, everything else 0.85, never a reversal) — at one global 0.85 bar the descriptor rung resolved and the question still went out; suppression keyed on the charge, not the merchant; the body states what was checked |
| `charge_msg.py` | no guess at all ("My guess: shop supplies" was wrong for DeepSeek, Polka Dot, Newegg and Home Depot); one charge, one amount, one card; 320-char ceiling that gives up evidence before it gives up the question mark |
| `sms-responder.py` | `_learn_from_his_answer` calls `attribute_reply`, and the inbound loop marks him awake via `relay.record_inbound()` |

**Verified after the deploy**, not assumed: `text-health.py` → `15 check(s), 0 FAIL`;
`sms-responder.py run --dry-run` → `0 to decide`; `owner_text_relay.py doctor` → every check `ok`
with the three guards `ON`; `verify-owner-text.sh` → `IN SYNC (21 files)`.

**The measurement that authorised it.** `scripts/text-channel/replay-owner-text.py` replays every
text that ever reached him through the live guards and reports `WOULD-LOSE` (texts he engaged with
that a guard would refuse) separately from `WOULD-SAVE`. The first version of the guards scored
**14 lost / 61 saved** — and reading all 14 showed TEN were false positives: `addressed` treated
"Done —", "No —" and "Understood —" as names, and `instruction` silenced two genuine **security
questions** he answered ("Legitimate", "Yes, it was authorized by me"). Narrowed, it scores
**5 lost / 28 saved**, and four of the five are texts that should never have been sent in that
form. **A guard is not shipped on its own test suite; it is shipped on this replay.**
