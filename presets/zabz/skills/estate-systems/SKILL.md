---
name: estate-systems
description: Use BEFORE designing, building, proposing, replacing, migrating or buying anything for this estate — a new backup, a failover, a server, a migration, a monitor, a deployment path, or "let's move X to Y". Triggers on "set up", "build", "migrate", "replace", "new server", "we should", "I want to move", "add a", or any moment you are about to propose architecture or spend the owner's money. Also use when told something is broken and you are about to write a fix, because the fixed version may already exist. This estate already contains a proven failover system, an offsite backup chain, a mesh, and a journal; building a parallel version of any of them has twice cost the owner money and hours.
---

# Before you design anything: survey the estate

**This skill exists because of two failures in 48 hours, both the same shape — an agent proposed to
build something the estate already had.**

1. An agent recommended buying a **Hetzner Storage Box** for backups. The estate already had
   **Cloudflare R2** holding `authority/secretary.db.gz` plus a bucket-scoped token, and a restic
   repo. The purchase was unnecessary.
2. An agent **designed and began a DNS cutover by hand** — and made the owner spend **$51.59/month**
   and hours of work — before discovering that `company-promote.py` had performed exactly that
   promotion since **2026-10-06**, with five pre-flight refusals, including the "two writers on one
   database" hazard the agent had "independently derived".

Both were caught late. The owner's words: *"It didn't even plan out properly what you were even
doing. This was just in the wind."*

## The rule

> **Before the first design sentence, spend ten minutes proving the thing does not already exist.**

## The survey, in order

**1. Read the register.** `~/code/harness-config/docs/mesh/000-SYSTEMS-REGISTER.md` — the machines
and their roles, every system and where it lives, what is authoritative, and the eight traps that
have already cost this estate. If your idea is in the register, **use it. If it exists but is broken,
fix it.** Do not build a parallel one.

**2. Search the code.** 
```bash
grep -ril "<the thing>" ~/code/harness-config ~/code/personal-secretary-mvp 2>/dev/null | head
ls ~/bin /opt/company/deploy/hosting-migration/scripts 2>/dev/null
```
Also look on the hosts, because much of this estate's machinery is deployed rather than committed:
`lpt-survivor-01` holds the failover tooling, `secratary-cloud` and `secratary` hold the authority,
`lpt-apps` is the vault and the Caddy front door.

**3. Search the journal** — the estate's own memory, which records what was built and what it cost:
```bash
python ~/code/harness-config/journal/tools/journal.py search "<the thing>"
python ~/code/harness-config/journal/tools/journal.py list --kind lessons --status open | head -40
python ~/code/harness-config/journal/tools/journal.py list --kind pain --status open | head -40
```

**4. Check what is RUNNING**, not just what is committed:
```bash
for h in secratary-cloud secratary-ts desktop-ts lpt-apps survivor; do
  echo "--- $h"
  ssh -o ConnectTimeout=8 -o BatchMode=yes $h \
    'systemctl list-units --type=service --state=running --no-legend 2>/dev/null | head -25; crontab -l 2>/dev/null | head -10'
done
```

## What is already here, so you do not have to find out the hard way

| need | use | do NOT |
|---|---|---|
| fail over the company to a standby | `lpt-survivor-01:/opt/company/deploy/hosting-migration/scripts/company-promote.py` (dry-run by default; refuses on two writers) | hand-edit Cloudflare DNS |
| offsite backup | `~/bin/push-db-offsite.sh` → R2; `~/bin/company-offsite-push.sh` → restic `psm-backups/company-offsite` | rent storage |
| fan work out to other machines | the `subagent` tool (the mesh). **Pass `run_in_background: true`** — it defaults to foreground and blocks the turn | fan out locally while the mesh is reachable |
| know where a child could run | `GET /mesh/health` on every node; the broker is an optimisation, not a veto | assume the broker must be up |
| continuity across sessions | `journal.py` (`status`, `list`, `show`, `search`, `newest handoff`) | re-derive from scratch |
| read any session anywhere | the `read-sessions` skill / `scripts/sessions.mjs` | ssh around guessing |

## If you do have to build

Then, and only then: write down **why the existing thing could not be used**, in the same commit.
That sentence is what lets the next session trust your work instead of re-doing the survey.
