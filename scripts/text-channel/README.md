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

## 2026-10-19 — the production pager sends one complete question

`owner_attention.py` is the daily pager, and on the production authority
(`secratary-cloud`) the running copy is
`/root/personal-secretary-mvp/scripts/owner_attention.py`. It is **not** in
`/home/zabz/bin` and it is **not** the copy on `secratary`; a change made only
there does not reach the phone.

The scorecard's worst family was the old `10-13 02:24 UTC 36 items, 26 urgent`
wall. That wall was retired on 2026-10-15, but the replacement still cut the one
selected item at 79 characters. The 2026-10-19 14:12 text ended
`the contact block you supplied is` — half a sentence, no question, no reply
instruction. The next body would have ended `Grow the`.

`compose_sms_body()` now returns `(body, rendered-key)`; `send()` records the
rendered key (not the body), and `_compose_one()` sends the complete first
question plus `Reply with your answer, or say 'your call'.` The 79-character
preview remains the no-repeat key, so the existing `sent-items.json` still
matches and the same item is not repeated.

Before/after on the same three delivered family texts
(`measure-production-pager.py`): 108 item-slots -> 3; 64 `urgent` labels -> 0;
3/3 server paths -> 0/3; 0/3 reply instructions -> 3/3; 3 distinct items.
The 2026-10-19 14:12 text: 79 chars, no question, cut mid-word -> 205 chars,
complete question, instruction, no mid-word cut. The next live body is 224 chars.

Verify (neither sends):

```bash
cd /root/personal-secretary-mvp
.venv/bin/python3 /root/code/harness-config/scripts/text-channel/test-production-pager.py scripts/owner_attention.py
.venv/bin/python3 /root/code/harness-config/scripts/text-channel/measure-production-pager.py
```

The timer's next send is 2026-10-20 14:23 UTC; that is the first live test.

The app-repo record is branch `owner-text/pager-one-question-20261019`
(commit `c5d9ccb27`), based on `1e459e49b` — the commit whose 853-line
`owner_attention.py` was actually running. The app repo's current branch
(`hk/559-bound-repo-reads`) carries a newer, unreleased 1,137-line
`owner_attention.py` from the config-env merge. The live file deliberately
remains the deployed base plus this patch; the newer branch's composer is a
different architecture and deploying it is a larger change than this one. The
next deploy of the newer branch must carry the complete-question + item-key
patch forward.

## 2026-10-20 — the pager now sends only what he can answer

The 2026-10-19 fix made the one selected item **complete**. It did not make it
**answerable**. `pick_one_item()` chose by rank alone, and `_compose_one()`
appended `Reply with your answer, or say 'your call'.` to whatever it found —
including a statement. On the live digest
(`/root/personal-secretary-mvp/data/owner-attention/latest.txt`, 34 items, saved
for the measurement at `/tmp/digest-20261020.txt`):

- **25 of 34 items** composed to a body with NO `?` and WITH the reply
  instruction, e.g. `OVERDUE 2026-08-15 — Elantra — New York toll bill
  collection (bill)` and `Supplier hasn't answered RMA request for
  dead-digitizer Surface panel (order 108746338)`.
- One pass over that digest would therefore text him **34 times, 25 of them
  statements he cannot answer**. Those are the same dead-text class as the
  retired 36-item wall: the wall asked nothing, and a statement asks nothing.

The scorecard's 3-of-3 family (`10-13 02:24 UTC 36 items, 26 urgent`) is the
historical wall, and those rows stay in the 14-day window until 2026-10-27; no
change can make an already-sent text answered. This change is about the texts the
pager would send next.

Change: `_compose_one()` returns `""` when the extracted text has no `?`;
`pick_one_item()` skips an item that composes empty and takes the next answerable
one, or nothing. Notices remain in the digest file; the phone carries only what
he can answer. The first live body after the change is
`Should the company's agent work move out of DeepSeek's peak-price window?`
(117 chars, question + instruction).

Before/after (`measure-pager-answerability.py`, same saved 34-item digest):

```
bodies_without_question 25  skipped  0   COLD-START TEXTS 34  statements 25
bodies_without_question  0  skipped 25   COLD-START TEXTS  9  statements  0
```

Verify (neither sends):

```bash
cd /root/personal-secretary-mvp
.venv/bin/python3 /root/code/harness-config/scripts/text-channel/test-production-pager.py scripts/owner_attention.py
.venv/bin/python3 /root/code/harness-config/scripts/text-channel/measure-pager-answerability.py
```

The app-repo record is branch `owner-text/pager-answerable-20261020`, based on
`owner-text/pager-one-question-20261019` (`c5d9ccb27`). The live file's md5
before this change was `d5145cbdfb7aeec682784fa160171e72`; a byte copy is
`scripts/owner_attention.py.bak-answerable-20261020T000537Z`. The next deploy of
the newer `hk/559-bound-repo-reads` composer must carry BOTH patches forward.

## 2026-10-20 — a retired family no longer wakes a shift

The 2026-10-20 00:02 wake quoted `Worst family: '10 utc items urgent (3 dead of 3)`
— the 36-item wall retired on 10-15 and already fixed by item 720 on 10-19. Its
three delivered rows are 10-12/10-13/10-15; no text in that family has been sent
since 10-15, but the 14-day window keeps it listed until 2026-10-27. So the
scorecard kept naming a retired producer as the worst, and the weekly `--flag`
would re-wake a defect that no longer exists. A retired family and a live one
scored the same (ledger item 733).

Change: `owner-text-scorecard.py` now records, per family, the newest delivered
text's age and whether it is inside the live window (`max(reply window, 48h)`).
The report prints `[LIVE]` or `[HISTORICAL]` on every worst family and, for a
historical one, the date it drops below the 2-text table. The dead-text `--flag`
branch names the worst **live** family (including a live family with one text);
if every dead text is historical it files no dead-text flag and prints the
retired family, its age and its age-out date instead of waking another shift.
(The conformance flag is a separate condition and still fires on its own rate.)

Before/after on the same 14 days of `sms_log` (the scorecard as it was in
`2dde8d07^` against the current one):

```bash
cd /root/code/harness-config
python3 scripts/text-channel/measure-scorecard-liveness.py --before 2dde8d07^
```

```
BEFORE  worst named: '10 utc items urgent (3 dead of 3, newest 4.5d old) -- no liveness
AFTER   worst LIVE family: asking something should found (1 dead of 1, newest 43.6h old)
AFTER   historical family: '10 utc items urgent (3 dead of 3, newest 4.5d old, drops below 2 rows 2026-10-27)
COUNT   wake target is a retired family: 1 -> 0
COUNT   live dead texts the old reader could not distinguish: 1
```

The live target is a different, current text (`I was asking you for something I
should have found myself.`, 2026-10-18 01:46 EDT), not the retired wall. The
three wall rows still count in the 53.1% dead-text rate until 2026-10-27; that is
history, not a thing this shift can change.

Verify (neither sends a text nor files a flag):

```bash
cd /root/code/harness-config
python3 scripts/text-channel/test-owner-text-scorecard.py          # 29 checks, RESULT: PASS
python3 scripts/text-channel/owner-text-scorecard.py --days 14     # worst LIVE family + HISTORICAL line
python3 scripts/text-channel/measure-scorecard-liveness.py --before 2dde8d07^
```

`--flag` was deliberately not run while landing this: rule 6, no wake flag from
inside a session. The next scheduled `run-wake-sources.sh` reads the new
live-family selection through `/root/bin/sources/owner-text-scorecard.py` (a thin
wrapper that imports this file).

## 2026-10-20 — a capture is confirmed in a sentence, not a token

The conformance census still named 28 of 184 delivered texts (15.2%) that the live guards
would refuse. Two of them were the personal-ops capture replies `Remembered.` (2026-10-16)
and `Captured as a task.` (2026-10-18) — bare tokens the guard refuses as content-free
acknowledgements. `app/main.py` sends that reply directly, so the relay never saw it.

Change: `compose_capture_reply(kind, detail)` in the shared relay writes one sentence and
keeps the captured fact when it is clean; a path or a credential ask falls back to the plain
sentence. `app/services/personal_ops.py` calls it for both memory and task captures, and
`_rescue_reminder` rewrites the two bare bodies already on the wire with the same words, so
the phone and the census cannot disagree.

Before/after (`owner-text-scorecard.py --days 14`):

```
BEFORE  28 of 184 (15.2%) refused; 6 rewritten; internal_prose 26, credential_request 3
AFTER   26 of 184 (14.1%) refused; 8 rewritten; internal_prose 24, credential_request 3
```

Verify (none sends):

```bash
cd /root/code/harness-config/scripts/text-channel && python3 test-capture-composer.py
cd /opt/company && .venv/bin/python -m pytest tests/test_capture_composer.py -q
cd /root/code/harness-config/scripts/text-channel && python3 owner-text-scorecard.py --days 14 | grep -A6 CONFORMANCE
```

The remaining 26 are other composers: the historical digest wall, the budget string, the
library/offsite prose and the 3 NJ Premier credential asks. This change does not touch the
guard and does not suppress anything.


## 2026-10-20 — an apology is not a result: the promise-salvage stops sending the leftover

The 02:08 wake named the LIVE family `asking something should found` (1 dead of 1). Its one
text — `I was asking you for something I should have found myself.` — is not a producer of
its own. It is the SALVAGE of a longer body sent at **2026-10-18 05:46Z**:

```
You're right - I was asking you for something I should have found myself. Let me actually dig.
```

`classify_owner_body()` dropped the promise sentence correctly. It then admitted the
remaining apology as a RESULT (`reported_fact`: 58 chars, three words), because the floor
that stops a refusal silencing a person is generous. Nothing in that sentence asks him
anything, names a specific or reports an outcome, so there was nothing to answer — the
scorecard records it IGNORED. The same defect delivered two more bodies on **2026-10-12**
(13:39Z and 16:25Z), each its own four-word family, which is why the table names one and not
three.

Change in `mirror/textsend.py`:

- `_SELF_ADMISSION_RE` names a sentence that only admits we asked for what we should have
  found, or that he already told us (`I was asking`, `you told me`, `I should have found`,
  `that's on me`, an apology) — anchored at the start, and only when the sentence has no
  specific and asks nothing.
- `_noise_sentence_code()` returns `NOISE_ACK` for it.
- `_strip_noise_prefix()` now drops an un-prefixed noise sentence whole. Before, it only
  re-checked after a strip changed the text; `I was asking you...` matched `NOISE_ACK` but
  had no prefix to strip, so the loop kept it and `_classify_positive()` admitted it.

Before/after on the same 14 days of `sms_log` (one body per provider sid, longest row):

```
self-admission texts the gate delivers      3      0
substantive salvages still delivered        3      3
bodies whose fate changed                   3
COUNT   self-admission texts the gate would deliver: 3 -> 0
COUNT   substantive salvages lost: 0
COUNT   other bodies whose fate changed: 0
```

The three changed bodies are exactly the three self-admissions. The dress-purchase salvage,
`You're right - the $58 ... closed`, an apology followed by a question, and every clean
result are unchanged.

Deployed with `mirror/deploy-owner-text.sh textsend.py` (live md5 `671717c8799e`, backup
`/root/text-deploy-backup/20261020T021258Z/`). Verify (none sends):

```bash
cd /root/code/harness-config
python3 scripts/text-channel/test-self-admission-salvage.py      # 19 checks, RESULT: PASS
python3 scripts/text-channel/measure-self-admission-salvage.py --days 14 --before HEAD^
python3 /root/bin/text-health.py                                  # 20 checks, 0 FAIL
python3 /root/bin/sms-responder.py run --dry-run                  # 0 to decide
```

The catalogue was refreshed (`textdecide.py --refresh-catalog`) because `text-health` A3 was
red on a stale cache (35 vs 33 ids, missing `deepseek-flash`); that is unrelated to this
change and is now green. `verify-owner-text.sh` reports one pre-existing drift,
`merchant_resolve.py` (live `95e4f91b`, mirror `4d6fba2f`, live mtime 01:07Z) — not touched
here.

The already-delivered 2026-10-18 row stays in the scorecard's 14-day count until
**2026-11-01**; the producer that would send another is what changed.

## 2026-10-20 — a family the live gate already refuses is not a wake target

The 03:08 wake named `asking something should found` (1 dead of 1, newest 45.5h old)
again, one hour after item 750 had fixed its producer. The text itself is settled:
`classify_owner_body` now returns `acknowledgement_only` / `refused: True` for
`I was asking you for something I should have found myself.` and
`restatement_only` / `refused: True` for the longer promise it was salvaged from.
Nothing was left to repair, yet the same weekly subject kept producing sessions.

Two readings combined to manufacture the duplicate:

1. **Liveness was age only.** `summarise()` called a family LIVE whenever its newest
   text was inside `LIVE_FAMILY_H` (48h), even when every body in it was one the live
   gate refuses. The one self-admission row stays inside 48h until 2026-10-20 ~05:00.
2. **`wake.py flag` revives a terminal subject.** The `owner-text:scorecard:2026-W43`
   subject was done at 02:14; the source re-filed it at 02:37 because the 30-minute
   cooldown had passed, and the dispatcher released it at 03:08. A weekly subject that
   re-files after its own release is a session roughly hourly (four releases between
   00:00Z and 03:08Z), not one a week.

Change in `owner-text-scorecard.py`:

- `summarise()` now takes the live `textsend.classify_owner_body` (or an injected
  callable; `gate=None` means the live tree, an unreadable gate means no demotion) and
  records one more bit per family: **GATED** = every body in the family is refused by
  the gate AND the newest is past the reply window. A GATED family is not LIVE. The
  reply-window condition keeps a text he may still answer in play.
- The report prints `[GATED]` in the family table and, when no LIVE family remains,
  `worst LIVE family      none - the dead family '...' is refused by the live gate: no
  text in it can be delivered`.
- `file_flag()` files nothing for a GATED family and prints why. It does not touch the
  historical branch (item 733) or the conformance flag.

Before/after on the same 14 days of `sms_log` (the scorecard at `HEAD` against this
one, same data, same reply window):

```bash
cd /root/code/harness-config
git show HEAD:scripts/text-channel/owner-text-scorecard.py > /tmp/score-before.py
python3 /tmp/score-before.py --days 14 | grep 'worst LIVE'
python3 scripts/text-channel/owner-text-scorecard.py --days 14 | grep 'worst LIVE'
```

```
BEFORE worst LIVE family : asking something should found (1 dead of 1, newest 45.48h)
AFTER  worst LIVE family : none
AFTER  gated family      : asking something should found (1 dead of 1, newest 45.48h)
COUNT  live wake targets whose every body the live gate refuses: 1 -> 0
```

`file_flag()` on the AFTER summary returns 0 with `no subprocess was called` (the
source's `wake.py flag` is never reached). The 53.1% dead-text rate is unchanged: the
three wall rows and the self-admission row are already delivered, and the 2026-10-18
row stays in the count until 2026-11-01. This change stops the re-wake; it cannot
un-send a text.

Verify (none sends, none files a flag):

```bash
cd /root/code/harness-config
python3 scripts/text-channel/test-owner-text-scorecard.py     # 41 checks, RESULT: PASS
python3 scripts/text-channel/owner-text-scorecard.py --days 14 # worst LIVE family: none (GATED)
```

The gate is still the gate: a family whose bodies the gate allows stays LIVE, and an
unreadable gate demotes nothing (`test-owner-text-scorecard.py` covers both). A
producer that *bypasses* the gate is a conformance defect, not a dead-text one; the
conformance census still names it and still files its own flag.

One latent trap found while proving this, not changed here: the app's
`app/services/owner_text_classification.py` caches the `textsend` module on first use
(`_module`), so a deploy of `/root/bin/textsend.py` is NOT live in a running
`company-api` until it restarts. It is not biting today (the process started 01:22Z
and its last app-door owner send was 2026-10-19 18:24Z, so its cache was empty at
deploy time), but the next textsend deploy has no such guarantee.

## 2026-10-20 — a credential ask is a reminder, not a suppression

The conformance census named 3 `credential_request` rows in the 14-day window: the
2026-10-08 library ask ("Send me the barcode and password"), and the 2026-10-16/17 NJ
Premier asks ("Give me the NJ Premier Business Services login"). Rule 1g refuses each
body whole, which is right for the secret and wrong for the reminder: the NJ returns and
the library count are real work, and a refusal deletes them. The pager made it worse —
once the answerable rule landed, `_compose_one()` returned `""` for a credential item
because it carries no question, so the pager skipped the reminder before the gate ever
saw it.

The repair is at the composer, not the guard:

* `rewrite_credential_ask()` in `mirror/owner_text_relay.py` keeps the subject before the
  ask, cuts the clause that asks for the secret, and closes with one question:
  `... - can you restore the access I need today?`
* `_rescue_reminder()` calls it for every owner-scoped body that `credential_request()`
  names, so the shared sender writes the safe sentence whatever door produced the ask.
* `owner_attention.py::_compose_one()` asks the relay for that sentence, so the pager
  sends the reminder instead of dropping it. It imports nothing at module load; a relay
  that is missing leaves the old statement rule in place.

Before/after on the same 14 days of `sms_log` + `messages`:

```
BEFORE  26 of 186 (14.0%) refused; 8 rewritten; internal_prose 24, credential_request 3
AFTER   23 of 186 (12.4%) refused; 11 rewritten; internal_prose 23, credential_request 0
```

The 3 changed rows are exactly the 3 credential asks. They are now scored through the
same rewrite the live gate would apply, so they are delivered, not lost. The other 23 are
untouched history (the retired digest wall, the 10-08 budget string, the one-off library
/ offsite / Topgolf / Newegg prose, the family-chat forward, the 10-19 fragment); this
change does not rewrite them and does not touch the guard.

The composer test uses the three bodies as delivered:

```
cd /root/code/harness-config
python3 scripts/text-channel/test-credential-ask-composer.py
OK  2026-10-08 library     -> The collector's letter ... - can you restore the access I need today?
OK  2026-10-16 NJ payroll  -> NJ payroll returns have no filer ... - can you restore the access I need today?
OK  2026-10-17 NJ sales tax -> The NJ sales tax return for Q3 2026, form ST-50 - can you restore the access I need today?
BEFORE  3/3 measured bodies refused by the guards; pager would skip or the gate refuse 3/3
AFTER   0/3 refused; 3/3 delivered as one question, no credential, no path
RESULT: PASS (151 checks)
```

Controls are unchanged: a broken login page (a status report), "Your password is on the
desk." (a statement that provides a secret), "Can you reset the password?" (a task for
us, not an ask) and a normal question are not rewritten.

Verify (none sends):

```bash
cd /root/code/harness-config
python3 scripts/text-channel/test-credential-ask-composer.py      # 151 checks, PASS
python3 scripts/text-channel/owner-text-scorecard.py --days 14 | grep -A9 CONFORMANCE
python3 /root/bin/text-health.py                                  # 20 checks, 0 FAIL
python3 /root/bin/sms-responder.py run --dry-run --limit 5         # 0 to decide
```

Deployed relay md5 `3583c8aba509`; live pager md5
`1e7cb47bd1aa2101abe3fca426f77f67`. Backups:
`/root/text-deploy-backup/20261020T031709Z/owner_text_relay.py` and
`/root/text-deploy-backup/20261020T031636Z/owner_attention.py`. The pager is the app-repo
file at `/opt/company/scripts/owner_attention.py` (`/root/personal-secretary-mvp` is the
same checkout); the working tree already carried the uncommitted one-question and
answerable patches, so this change is recorded by hash, this section, and the exact diff at
`scripts/text-channel/patches/owner_attention-credential-ask-20261020.patch`.
