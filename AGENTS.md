# AGENTS.md — harness-config

Standing rules for every agent that runs on this estate. Each one is here because a session
discovered the hard way that it existed only in the owner's head, or in a chat nobody opens.
**These are rules, not notes.** If you are about to touch anything they name, read the rule first.

---

## 1. Every DSH session and every VS Code Copilot chat is archived forever. A copy must always exist.

**The owner's words, 2026-10-09:**

> *"we need copies of all vscode copilot chats and all dsh sessions forever for data and training
> data, and those a copy always needs to exist of this should be documented"*

**Why:** it is the company's training data and its institutional memory. A conversation that
exists only on one laptop is one disk failure, one theft, or one `pm clear` away from gone. This
business has lost customer data twice; this rule exists so its own reasoning cannot be lost the
same way.

### Where the archive is

| What | Where | Held by |
|---|---|---|
| **Raw transcript archive** (NEW, 2026-10-09) | `secratary:/home/zabz/lpt-transcripts/` | this rule |
| DSH sessions, parsed, in the company database | `secratary:/home/zabz/personal-secretary-mvp/data/secretary.db` → `dsh_sessions`, `dsh_session_events` | `scripts/push-dsh-sessions.mjs`, hourly |
| Copilot chats, parsed, in the company database | same DB → `vscode_chat_sessions`, `vscode_chat_messages` | `scripts/push_vscode_chats.py`, hourly |
| **DEPRECATED — do not read to decide freshness** | `secratary:/home/zabz/dsh-archive/dsh-archive.db` | frozen 2026-09-11 by design; see its `RETIRED.md` |

The parsed stores in `secretary.db` are a **projection**: they keep messages and an indexed
summary, not the bytes. The raw archive below keeps the bytes, including files the parser never
read. Both matter; the raw one is the one that cannot be reconstructed.

### How it stays current

One scheduler, on the machine that is always on. `cron` on `secratary`, hourly, via
`cron-wrap.sh` (the estate's convention — it records every run's exit code in
`~/.cron-status/runs.tsv`) running `~/bin/transcript-archive-run.sh`, which:

1. `transcript-archive-pull.py --all` — for each machine, pull the list of what the archive
   already holds, run that machine's own `archive-transcripts.py` to pack only what is new, copy
   the tar back, and ingest it;
2. `transcript-archive-server.py --check` — the staleness check;
3. on a failed check, write `~/.transcript-archive/ALARM` and append one journal `pain` entry
   (guarded so the same alarm is not filed hourly).

The scripts are in `scripts/`, and are synced to every node with the rest of `harness-config`.

### How to tell whether it is current — and the check that fails when it is not

```
ssh secratary-ts 'python3 ~/code/harness-config/scripts/transcript-archive-server.py --stats'
ssh secratary-ts 'python3 ~/code/harness-config/scripts/transcript-archive-server.py --check'
cat ~/.transcript-archive/status.json        # last run, from the cron job
```

`--check` answers two different questions and **exits non-zero**, because they fail differently:

* **GAP (exit 1, a real defect)** — a machine's own newest source file is newer than anything
  archived from it. Data exists on the box and the archive does not have it.
* **SILENCE (exit 2, cannot be judged from here)** — a machine that used to report has stopped.
  From the authority a powered-off laptop and a broken pull look identical, so this is reported
  as exactly that, never as health.

### How to read one entry

```
python3 ~/code/harness-config/scripts/transcript-archive-server.py \
    --read zabz-yoga copilot-chats <rel_path> --out /tmp/one.json
```

Objects are content-addressed (`objects/<sha[0:2]>/<sha>[.zst]`) and the manifest is
`manifest.sqlite` (`object`, `arrival`, `machine_contact`, `ingest_run`, `quarantine`).

### The four traps this rule has already paid for — do not re-introduce them

1. **Never treat a frozen store as a gap.** `dsh-archive.db` is frozen *by design*; reading it
   as the live archive is how a non-existent crisis gets reported. `RETIRED.md` says so.
2. **Never let a client-side scheduled task be the only thing that ships.** Measured 2026-10-09:
   `PersonalSecretary-PushVSCodeChats` on ZABZ-YOGA reported `LastTaskResult=0` — success —
   every hour for **21 days** while the Copilot archive stood still. That is why the pull is
   driven from the always-on host.
3. **Never skip a file because it is large.** `scripts/vscode_chat_extractor.py` silently skips
   any chat file over 50 MB (`_MAX_JSONL_BYTES`). Measured on ZABZ-YOGA 2026-10-09: **14 chat
   files exceed 50 MB** and are in no store anywhere. The raw archive packs bytes and has no
   size cap. If you fix the extractor, keep this note.
4. **Redaction changes bytes, so never key a cursor on the stored hash.** The cursor is keyed on
   `source_sha256` — the sha of the file as it sat on the machine. Keying it on the stored copy
   makes every redacted file look new forever and re-sends it on every run.

### Secrets and card data — never copied

Credential stores are refused **by name** and recorded in `quarantine`: VS Code `state.vscdb`
(its `ItemTable` *is* the encrypted secret store), the Copilot CLI `session-store.db`, `.env`,
`id_*`, `*.pem`, `*.key`, `.netrc`, `authorized_keys`. Card numbers and credential-shaped
strings inside text are **redacted** (`[REDACTED:card]`, `[REDACTED:openai_key]`, …) and counted,
and the bytes that *arrive* at the authority are scanned again — so a redaction is verified
rather than trusted. Precedent: journal **P13b**, 2026-09-11, *"I leaked a live API key into the
session transcript."*

**Never weaken this to make an archive more complete.** A conversation missing a card number is
recoverable; a card number in a training corpus is not.

---

## 2. Ask the owner one question, never a document

He does not review documents. A deliverable is for the record, not a reading assignment. If a
decision is genuinely his — money, customers, legal posture, family, anything irreversible, real
taste — convert it into **one plain-language question with one recommendation**, asked in the
conversation. Development decisions are not his: decide, record, move on.

## 3. Standing rules that are actually his to be asked about live in `owner_decision_queue`

Table `owner_decision_queue` on the authority; read it at the start of substantial work.
`~/bin/owner-queue.py next` on `secratary`, or `ssh secratary-ts "python3 ~/bin/owner-queue.py next"`.
Anything solvable without him does not belong there.

## 4. Nothing outbound without a per-message yes in the current conversation

Email, SMS, calls, to anyone. Show the exact body first. A task-level directive ("handle it",
"settle it with X") authorises the work, never specific words. After a send, read the `To` header
back — `SENT` describes what we did, not who received it. Full procedure:
`docs/outbound-comms-hard-stop.md`.
