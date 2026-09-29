# `scripts/deployed/` — the file that runs, kept where git can see it

Captured 2026-09-29T18:50:48Z from `secratary:/home/zabz/bin/`.

## Why this directory exists

These files **run** the autonomous company and the AI text line, and until this capture they lived
only on the authority. The repo held older, different copies. Measured that day:

| file | where | bytes | sha256 (12) |
|---|---|---|---|
| `sms-responder.py` | `secratary:/home/zabz/bin/` — the one that ran | 70,228 | `dda178099128` |
| `sms-responder.py` | `secratary:~/harness-config/scripts/` | 38,917 | `b71e1f3a8a8f` |
| `sms-responder.py` | `ZABZ-YOGA:~/code/harness-config/scripts/` | 56,311 | differs |

Three copies, three different files, and **none of the tracked copies contained the owner fast path
that was live**. An audit read the wrong one and reported the wrong byte count; another worker was
briefed with the wrong size. The same shape of failure had already frozen `phone-and-tech-full` on
an August tree for weeks behind a stale `.git/index.lock` (lesson L2798). The owner's rule is one
source of truth per thing, so the artefact is captured, with a sha for every file.

## What is here

- `MANIFEST.tsv` — `name<TAB>bytes<TAB>sha256`, one line per deployed file.
- the captured files themselves, at the same relative paths as under `~/bin/`.
- `assert-bin-matches-repo.py` — compares the LIVE file against the captured one. Read only.
- `deploy-bin-from-repo.py` — pushes a captured file to the authority with a backup, a
  read-it-back sha assertion, `py_compile`, and a manifest refresh. **Dry run by default.**

## Use

```bash
python3 assert-bin-matches-repo.py --host secratary-lan     # exit 0 = every file matches
python3 assert-bin-matches-repo.py --json | jq .not_matching
python3 deploy-bin-from-repo.py --dry-run sms-responder.py  # then without --dry-run
```

**Host alias matters.** From the office LAN use `secratary-lan` (192.168.50.77). From off-LAN only
the tailnet alias `secratary-ts` works, and it times out intermittently. From ZABZ-TECH,
`secratary-ts` prints one line and then HANGS - that cost three fleet workers their entire
30-minute budget on 2026-09-29. Both scripts use a single ssh call for every file for that reason.

If the drift test cannot read any sha it prints `UNVERIFIED` and exits 2. **That is a refusal, not
a pass, and not a drift** - do not read it as green.

## The rule this directory is meant to keep

A deploy is not a live-action. This tooling copies files; making a change take effect is a
separate, deliberate step. Nothing here restarts a service, and nothing here sends anything.
