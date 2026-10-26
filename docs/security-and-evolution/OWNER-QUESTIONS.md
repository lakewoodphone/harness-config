# Owner questions — security department & evolution engine

**Started:** 2026-10-26 · **Host:** ZABZ-YOGA · **Status:** OPEN (working document)

Everything here is something I cannot decide for you: money, customers, legal, irreversible
change, or real taste. Each has my recommendation. Nothing here is a menu — it is one call per row.

Numbers in this file were read in the session that wrote them; the command or table is named
beside each one.

---

## Q1 — The SerpAPI key is still live and still in a transcript

**What I read.** Owner queue row #850 ("Rotate the live SerpAPI key?") is open. The mirror at
`journal/state/owner-questions.md` was generated 2026-10-25 04:41 UTC. The key was printed into a
session transcript, and the session archive is copied to
`secratary:/home/zabz/lpt-transcripts/` and to the authority — so the key exists in at least three
stores, and the transcript archive is a permanent, append-only copy by your own standing rule.

**Why it is yours.** A provider key is a money credential. I will not rotate a credential that can
bill you without your yes, and I will not quietly leave it.

**My recommendation.** Rotate it, and let me do the mechanical part: I generate the replacement,
prove the new one answers, prove the old one is dead, update every consumer, and put both proofs in
the journal. One command from you starts it.

**Decision needed:** rotate now / leave it / you rotate it yourself.

---

## Q2 — The GitHub token that is the only way to read the shop repos

**What I read.** Owner queue row #883 is described in the `dept_security` credential-hygiene work
order as "a leaked GitHub token still live and still the only credential that can read the shop
repos". Owner queue shows 13 open rows (mirror generated 2026-10-25 04:41 UTC).

**Why it is yours.** Rotating it can break repository access for every agent and every deploy at
once. The blast radius is the whole engineering function.

**My recommendation.** Create a *second* token first, prove it works against the shop repos, cut
everything over to it, then revoke the first. That way there is no window where the company cannot
read its own code. I can do the whole sequence; I need your yes because it touches your GitHub
account.

**Decision needed:** yes to the second-token cutover / not now.

---

## Q3 — The mesh trusts every tailnet device, and the office box's engine accepts an anonymous cookie

**What I read.** `harness-config/docs/mesh/63-security-audit.md` §0, written 2026-09-16, states
as MEASURED: (1) any tailnet device could sign into the DSH engine on `secratary` and ZABZ-YOGA
with one unauthenticated HTTPS GET and receive a 30-day cookie that controls an engine which runs
shell commands as you; (2) the tailnet packet filter was default allow-all; (3) PostgreSQL on the
laptop listened on `0.0.0.0:5432`. The document says plainly it is **audit only, nothing was
changed**.

**Why it is yours.** Tightening the tailnet ACL can lock your phone, Yisroel's mini, or your own
laptop out of the mesh. That is a decision about your working day, not an engineering detail.

**My recommendation.** Close the cookie issue first — it is the one that needs no ACL change and no
risk of locking anyone out. I have not yet re-measured whether it is still open; that is the first
thing the Security department should do, and I will report the raw response before touching
anything. The tailnet ACL I would do second, with you awake, because the failure mode is
"you cannot reach your own machine".

**Decision needed:** authorise me to close the open-cookie issue (no ACL change), and tell me
whether the tailnet ACL is in scope at all.

---

## Q4 — What may the Security department do without asking you, ever?

**What I read.** The existing `dept_security` standing orders on the authority already say: patch
what the system owns, rotate only credentials the system generated, never rotate money/customer/
third-party credentials, and leave the frozen office box alone. That is a good line. But there is
no written answer to the sharper question: may it **restart a service to apply a patch** at 3am.

**Why it is yours.** A restart is reversible; a restart during shop hours is a customer-facing
outage. This is the one authority boundary I will not invent.

**My recommendation.** Patch freely and restart freely on `zabz-tech`, `zabz-tech-linux`,
`zabz-yoga-1` and the Mac mini. On `secratary-cloud` (the authority) — the box that writes the
company database — patch but do **not** restart without a queue row. Never touch `secratary`.

**Decision needed:** accept that split, or narrow it.

---

## Q5 — Sending you a weekly security digest

**What I read.** Nothing in the company currently reports security state to you on any cadence. The
five host-posture rows marked `writable` (read from
`harness-config/settings/machines/host-posture.tsv`) are the permitted scope.

**Why it is yours.** It is your attention. A weekly digest is a recurring claim on it, and you are
the only one who can say whether that is welcome or noise.

**My recommendation.** One short weekly message, sent only when something changed, with a hard rule
of at most one item needing you. Silence means a clean week. If it ever exceeds five lines you tell
me and I cut it.

**Decision needed:** yes / no / only when something is actually broken.

---

## Q6 — How hard should the evolution engine push?

**What I read.** `evolution_log` holds 186 rows: 103 applied, 74 dismissed, 9 still `open`; the
newest row is 2026-10-14T22:30:54Z. `evolution_verification` holds 25 rows — 11 passed, 14 failed —
and **the newest is 2026-07-04T09:54:09Z**, so nothing has been measured for roughly sixteen weeks.
`mashgiach_dept_scores` holds 6,244 rows whose `findings_count`, `auto_fixes` and `escalations` are
**0 in every single row**, because `app/services/mashgiach.py:396` writes a literal `0`.

**Why it is yours.** "Constantly evolving" can mean anything from "tidy the codebase weekly" to
"rewrite its own architecture". The second one needs your appetite, because it changes the thing
you rely on.

**My recommendation.** Aggressive on improvements it can prove and revert; conservative on anything
that changes money, customers, or the company database. Concretely: it may change code and
configuration on a workstation freely, and must bring a queue row for anything on the authority.
Every change carries a measured before/after or it does not count as an improvement.

**Decision needed:** accept that line, or move it.

---

## Q7 — Is "efficiency" allowed to mean spending less?

**What it read.** Today's model spend is 74.8M tokens on `deepseek-flash` (3335 calls) and 39.4M on
`deepseek-v4-pro` (3086 calls), from `model_usage_today` in the company status snapshot.

**Why it is yours.** An engine told to "increase efficiency" will eventually decide the cheapest
model is the best one, and the company will get quieter and dumber while every dashboard improves.
That is a business-shape decision.

**My recommendation.** Efficiency means more real work per dollar, never less real work. The engine
may not trade away capability to hit a cost target; if it wants to downgrade a model it must show a
measured quality comparison first.

**Decision needed:** accept that constraint, or amend it.

---

## Q8 — Deleting things the engine decides are dead

**What I read.** The authority's live tree carries **329 modified files** (`git status --porcelain |
wc -l` on `/opt/company`, read 2026-10-26). A large fraction of this estate's machinery is deployed
rather than committed, so "unused" is not the same as "safe to delete".

**Why it is yours.** This business has lost data twice. I will not let an evolution engine delete
anything on a guess.

**My recommendation.** The engine may propose deletion, never perform it. It may archive. Anything
destructive stays a queue row with the exact path and the evidence it is unreferenced.

**Decision needed:** accept the archive-only rule.

---

## Q9 — There are now two security owners, and one of them is a duplicate

**What I read.** `tasks` 30549–30552 (created 2026-10-25 15:54) assign a `security_owner` agent
under `dept_systems_custody` a weekly hardening pass. That happened *before* `dept_security` was
scaffolded. So the company currently has a `dept_security` department **and** a `security_owner`
agent, with overlapping mandates, and `dept_systems_custody` already owns the "monthly posture
review + gap register" work order (`fbd122f4f369`, completed 2026-10-25 18:59).

**Why it is yours.** Only if you disagree with the direction — see my recommendation.

**My recommendation (and what I will do unless you stop me).** Consolidate: `dept_security` owns
security, `security_owner` is retired into it, and `dept_systems_custody` keeps custody
(inventory/backups/filesystem) but hands the security mandate over. One source of truth per thing
is already this estate's rule. I am treating this as an engineering decision, not a question —
recording it here so you can overrule it.

**Decision needed:** only if you want it the other way round.

---

## Where the work stands at the end of 2026-10-26

Fixed and verified in production: the Security department now exists in the agent tree and has
ticked for the first time (`tick_telemetry` `ab0b7dbfb5dd47c9`, 02:16:56Z, outcome `complete`,
quality `productive`); the weekly scorecard now reports real finding counts (19 of 32 departments
non-zero, was 0 of 88).

Still open and **not** yours: the two seeded security work orders must be re-fired (they are
terminal `failed` from 2026-10-25), `evolution_verification` has no writer, and no stagnation
detector exists. Those are mine to finish. Full detail:
`00-FINDINGS-2026-10-26.md`.

---

*New questions are appended as they arise, and each is closed here with your answer and the date.*
