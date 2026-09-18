<!-- e:lessons|L1969|2026-09-18|SECRATARY|open -->
**L1969 · A count whose collector had no input reads as a confident 0 - pair every count with its input count**

## The rule

When a monitor prints a number, check whether the collector had any **input** before you
decide the number is a fact. A collector whose input is empty returns a confident `0`, and
`0` is indistinguishable from a true zero at the label. The tell is the collector's own
input count, not the label.

## The case (measured 2026-09-18, personal-secretary-mvp)

`docs/ai-company-next-stage/generated/world-index-current.md` printed
`- Pending owner decision rows: 0` while `owner_decision_queue` held 28 pending rows.

The label was right; the count was wrong -- and worse than the audit that found it said.
`_decision_packet_status()` (`app/services/next_stage_runtime.py:318`) counted
`| <ID> | PENDING |` rows in `AI_COMPANY_DOC_DIR.glob("*.md")`. That directory holds only
the **gitignored** `generated/` subdirectory, so the non-recursive glob matched zero files
and every field came back `0`.

The proof was already in the artifact: `packet_file_count: 0` in
`world-index-current.json`. The collector was not "answering a different question than its
label asks" -- it was answering **nothing at all**. That distinction changed the fix: not a
rename, but a re-source.

Confirmed live twice: the unfixed deployed code regenerated the file at
`2026-09-18T02:10:41Z` and still wrote `0`; the fixed code, given the same DB read-only,
rendered `16`, matching `owner-queue.py stats` exactly at that moment.

## The two habits this buys

1. **Every count must be paired with its input count.** `packet_file_count` next to
 `pending_decision_rows` is what made this findable without reading the source. A bare
 count is unverifiable; a count with its denominator is auditable.
2. **Unreadable must never render as zero.** The fix returns `None` -> the label renders
 `"unknown"`, never `0`. "An empty result is not evidence of health -- it is a refusal"
 is only enforceable if the code has somewhere to put the refusal. Give it one.

## Corollary for generated artifacts

A generated artifact is a claim with a timestamp, not a source. This one was regenerated
hourly **during** the investigation and kept asserting `0`, because the generator ran the
deployed code. Read the artifact to learn what the *system* believes; read the code and the
database to learn what is *true*. They disagreed by 16, and only the timestamp told me the
artifact was fresh -- a fresh artifact repeating a stale falsehood looks maximally healthy.

<!-- j2 tags=provenance,monitors,generated-artifacts refs= alias_of= legacy_id= sha=1872bba709fa26d2 -->
