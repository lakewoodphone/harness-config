# DECISIONS — what was decided, and why

**Append-only.** A decision that is later reversed is not deleted; it is superseded by a new entry
citing it. The record of having changed course is itself useful.

The full working log, with evidence and the owner's own words, is
`~/code/personal-secretary-mvp/docs/secretary-replacement-audit/06-decision-log.md`. This file is the
short form, so a future self does not have to read seven documents to avoid relitigating something.

---

**D1 · 2026-09-11 · The CEO replaces the console, and owns the systems.**
DSH takes the seat Copilot held, as CEO. It commands `secratary` and evolves it. It does **not**
rebuild the secretary — 216k lines, 618 routes and working integrations are the asset.
*Owner's words:* "you take on the ceo instead of copilot and you take charge of all teh systems."

**D2 · 2026-09-11 · The secretary's orchestrator is the Chief of Staff.**
DSH decides; the company executes continuously on its own tick loop. Putting orchestration in DSH
would idle the company whenever the owner closed a window — the failure being migrated away from.

**D3 · 2026-09-11 · Visibility before capability.**
Build order: outcome monitor → digest → bridge → then evolve. An owner who cannot see his own systems
repeats the six silent days.

**D4 · 2026-09-11 · Keep GitHub and chat sync; make the secretary the only authoritative chat store.**
Transport was never the problem — 1,585 sessions were indexed correctly. Provenance was.

**D5 · 2026-09-11 · One authoritative database.**
Three copies of `secretary.db` exist (203 / 194 / 173 tables, three different last-tick dates). The
one on `secratary` is the truth; everything else is a replica and must say so.

**D6 · 2026-09-11 · Authority on `secratary`, compute on the desktop.**
The durable monitor lives on the always-on Linux host (8-day uptime, same LAN as the database); the
primary console is the office desktop (i9, 63 GB). *The thing watching must outlive the thing being
watched.*

**D7 · 2026-09-11 · `harness-config` is the single source of truth for the harness.**
Presets, settings and skills are git-tracked with a remote on `secratary`, synced by
`scripts/sync.py`. Never edit `~/.dsh` directly.

**D8 · 2026-09-11 · Do not stop for permission already granted.**
A turn ends only for completion with evidence, a genuine blocker, an owner-only decision, or an
irreversible action.

**D9 · 2026-09-11 · Build the conversational interface first.**
*Owner's words:* "what affects me most right now and day to day is the you i talk to, the
conversational interface." The CEO and the secretary evolution are long-term; the face is now.
→ the `zabz` preset, set as default after mount validation.

**D10 · 2026-09-11 · The journal is the memory.**
Because every session starts blank, growth is only possible if lessons, handoffs, pain and decisions
are written down. `journal/` is the organ, not documentation. The persona requires writing for the
self that wakes up without memory.

**D11 · 2026-09-11 · The kernel is version-controlled the same way the harness is.**
`ceo-kernel` is a git repo with remote `secretary-ts:/home/zabz/ceo-kernel.git`. `secratary` holds a
**checkout**. The server copy is never edited in place — that is the same rule as D7 and the same
failure as L13. Rationale: the kernel is code that runs on the always-on host, so it must be
deployable, reviewable and revertible from one source, or the server silently becomes a second,
divergent truth. Runtime output is explicitly excluded: the sentinel writes to
`/home/zabz/ceo-kernel-var/`, outside the working tree, because observations of a moment are not
source and a scheduled job must never dirty the repo it lives in.

**D12 · 2026-09-11 · The sentinel runs on cron as the interim Phase 6, and deliberately sends nothing.**
Every 5 minutes on `secratary`, via a script **in the repo** (`scripts/run-sentinel.sh`) rather than an
inline crontab command, so the behaviour is versioned instead of living in someone's crontab.
It records `latest.json` + `history.jsonl` and routes nothing.
*Why not alert:* the inbox (Phase 2) owns escalation and the interrupt quota (design §3.3). Mailing on
every run before that exists would recreate the alert fatigue that buried 7 critical and 46 urgent
messages (PAIN P6) — a monitor that trains its reader to ignore it is worse than a silent one.
*Superseded when:* Phase 6 lands a systemd daemon; this entry is then **replaced, not duplicated**.
