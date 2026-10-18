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

## `/home/zabz/bin` is a symlink to `/root/bin`

Verified 2026-10-18: `ls -ld /home/zabz/bin` → `-> /root/bin`, and the same file has the same
inode from both paths. The older `scripts/text-channel/README.md` says the running copies are in
`/home/zabz/bin` and that this directory is a copy — both statements describe the same single
store, and there is no second copy to fall out of step. Everything in this mirror lives in
`/root/bin`.

## The drift of 2026-10-18, recorded rather than erased

The mirror was taken at **01:33Z** from 17 files. By **01:43Z** three of them differed:

| file | mirrored 01:33 | live by 01:43 | cause |
|---|---|---|---|
| `owner_text_relay.py` | `1c4f022a…` | `f89641f6…` | **mine** — the recipient-aware ceiling, deployed 01:42:08 |
| `sms-inbox.py` | `1a24dfeb…` | `2e2dfbba…` | **not mine, not attributed** — mtime 01:42:27 |
| `mirror-owner-sms.py` | `86a4e6e3…` | `311e689f…` | **not mine, not attributed** — mtime 01:43:14 |

The two unattributed writes are the `P4254` class: something writes files in `/root/bin` and no
job admits to it. Checked and excluded this time: `crontab -l` has no line that writes them,
`deployed-drift-check.timer` last ran 00:47 (next 06:47), `cron-script-guard` only restores a
*missing* file, and `/root/bin` is not the target of any repo sync (this checkout's
`scripts/text-channel/` on the authority holds only the two files added on 2026-10-18). **The
manifest was then refreshed to what is actually running, and this table is the record of the
transition** — re-freezing a manifest without writing down what moved is how a mirror becomes a
comfortable fiction.

**A manifest is a cross-platform artefact.** Rewriting it on Windows with `Set-Content` produced
CRLF, and `read -r want name` in `verify-owner-text.sh` then read every filename with a trailing
`\r`, so all 17 files reported MISSING against paths that existed. Write it with `\n`.
