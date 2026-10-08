# The text channel — the code that owns the owner's phone

Mirrored from `/home/zabz/bin/` on the authority (`secratary`) on **2026-09-30**, so it is
versioned in a git repository that a deployment cannot silently delete. `~/bin` is **not a
git repo**, and that is not a detail: `scripts/server/prune-backups.sh` under
`personal-secretary-mvp` was untracked and a copy-style deploy removed it, which left the
backup volume at 99% with 7.6 GB free and an 18 GB backup due in two hours.

**These files are COPIES. The running copies are in `/home/zabz/bin/`.** Deploy a change by
editing here, copying to `/home/zabz/bin/`, and running the verification below — never the
other way round, or this tree stops describing what is running.

## What each file owns

| File | Owns |
|---|---|
| `sms-inbox.py` | The sensor. Gets texts from Twilio into the store. Cron `*/5`. |
| `textstore.py` | The store schema and every write to it. Nothing else writes `inbox.db`. |
| `textctx.py` | Who is this and what is going on: identity, permissions, thread, owner state. |
| `textdecide.py` | What should happen to a text. Owns the catalog read, the model choice, and the JSON decision. Also `--refresh-catalog`. |
| `textwork.py` | Doing the thing: a bounded read-only tool loop (9 tools) that returns an answer or an honest account of what blocked it. |
| `textsend.py` | Getting a text to a person and knowing that it went. Owns the send gate AND the owner conversation ledger read/write. |
| `sms-responder.py` | The loop: read the inbox, decide, act, reply. Cron `*/5`, `--send --max-sends 2`. |
| `mirror-owner-sms.py` | Bridges the owner's live texts from the app's `sms_log` into `inbox.db`. Cron `*/5`. |
| `text-health.py` | Twelve invariants over the whole channel. Read-only, exit 1 on any failure. This is the instrument, not a document. |

## The one rule that matters most

A text to the owner may not go out while he has not answered the previous one. That rule
lives in `app/owner_text.py` as `gate()` and, since 2026-09-30, in `textsend.py` as
`open_owner_turn()` / `record_owner_turn()`, reading and writing the **same**
`owner_text_turn` table in the app's database. Before that fix the app enforced it and this
sender did not, so a question either side was waiting on did not block the other — measured
as 118 texts to him in seven days against 14 replies.

`direct_request=True` is the one way past it, and it means "he asked for this message". It is
set in exactly one place: the owner-queue question, because answering his request is what the
turn is for.

## Verify after any change here

```bash
python3 ~/bin/text-health.py                 # must print "0 FAIL"
python3 ~/bin/sms-responder.py run --dry-run # must print "0 to decide" and no traceback
python3 ~/bin/textdecide.py --refresh-catalog # must print source=live, exit 0
```
