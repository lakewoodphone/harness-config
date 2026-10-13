# 07 — The target system: what is needed, and what is not

**Prepared:** 2026-10-13 · The owner's ask: *"an entire refreshed [system] about what's needed and
what's not in this setup, and that absolutely evolved to be way smarter, way more capable, way more
autonomous."*

**Evidence base:** `01-corpus.md` (945 of his 1,059 sessions classified), `07-pain-register.md` (the
ranked friction and 393 open pains clustered), `10-instruction-surface-audit.md`,
`20-memory-continuity-audit.md`, `30-systems-and-autonomy-audit.md`, and the open-work triage.

**One line of purpose, from the measurement and not from ambition:** *he uses this to find out what
is true and then fix it.* Investigation and repair are **56% of his intent**; building is 18%. So the
target is not a more autonomous builder. It is a system that **finds the truth, proves it, remembers
it, and repairs the thing** — with the owner's attention spent only where it is genuinely his.

---

## 1. What the measurement says the system is FOR

| | share of 945 sessions |
|---|---:|
| investigate · fix | **56%** |
| build | 18% |
| verify · document | 16% |
| communicate · decide · plan | 7% |

| domain | |
|---|---:|
| shop (customers, devices, parts, pricing) | **22%** |
| build + harness + infra (the estate itself) | **38.6%** |
| **his own life** | **11.9%** |
| everything else | 27.5% |

**Three facts that should shape every design decision:**

1. **The technical estate is where most of the work is.** 38.6% of his sessions are about the system
   itself. A tool that makes the harness cheaper and more truthful pays for itself more often than any
   shop feature.
2. **His life is a first-class domain** — 112 sessions, larger than comms and finance combined. A
   design that treats "personal" as an edge case is wrong about one eighth of the workload.
3. **Investigation is the product.** 33% of sessions are him finding out something. That means the
   *quality of a reading* matters more than the speed of an action.

---

## 2. Needed — ranked, and each traceable to a measurement

### N1. Truthfulness as a mechanism, not an intention
The #1 friction is `wrong-data` at **11.4% of sessions**, and it is what this estate's worst incident
was. What "needed" means concretely:

- every claim about work carries the **command and its output line**;
- a reading is not evidence until its **source and age** are known — a file mtime is not content
  freshness, and a mirror, a cache and a replica are all older than the thing they copy;
- **an empty result is a refusal, not health**, and the two must never print the same;
- **a log line from before a fix describes the state before the fix** — read the timestamp
  (`L3774`, and I violated this twice in one day).

### N2. One record, not 120
`~120` divergent git refs; "open pain" reads **162 / 366 / 373 / 393** depending on the machine;
**121 base-id collisions**; `check` calls it healthy. Until one lineage is canonical, every other
memory property is a promise the estate cannot keep. **This is the cheapest large win available.**

### N3. An alarm that reaches a human, on an outcome
**45 recorded pains** are "silent failure / an alarm with no transport", and the live instance is
`estate-monitor` computing `CRITICAL crit=4` every two minutes with `escalated=0` because its
escalation allow-list is one condition. The estate's monitors overwhelmingly check **liveness**; the
failures that cost money are **outcome** failures. Needed: every monitored thing gets a check that
fails when it *produced nothing*, and that check runs **off the box it watches**.

### N4. Cheap, batched execution — the shell tax
`pwsh` is **40.65% of all tool calls**, ≈13 hours of process start-up in one month; and the agent
polls its own job machinery **10,916 times**. Needed: fewer, batched shell calls; in-process reads;
and background jobs that are **read once, not polled**.

### N5. Look before you redo
`repeated-work` is **#3 at 9.4%**, with 66 both-live duplicate lessons and 9 duplicate pains. Needed:
a mandatory `journal.py search` on the area before starting, and a **queryable audit registry** so an
audit is never re-commissioned.

### N6. A decision, once made, is never lost or re-asked
The queue holds **162 pending**; the mirror under-reported by 19 and showed 11 already-answered rows as
waiting on him (fixed 2026-10-13). Needed: the owner's words appended to the journal **at answer
time**, a content-hash dedup key, and freshness measured from the `generated` line — never mtime.

### N7. Capacity that matches the corpus
The database is 25.9 GB growing ~2.3 MB/h on a 75 GB disk at 91-92%; the archive is 6.6 GB and shares
that filesystem; `company-api` runs with **no `MemoryMax`** and swap sits at 93.5% with 11 OOM kills
in 24 hours. Needed: a bounded archive temp (done), a memory ceiling on the API, and one decision about
disk — see §4.

### N8. One canonical surface per fact
The same rule lives in the persona, `AGENTS.md` and a skill with three different ages, and the failure
mode is a **hostname or path that is right in one and wrong in another**. Needed: when a fact changes,
correct every surface that states it, and put the rule where the work happens.

---

## 3. NOT needed — and saying so is part of the spec

- **More autonomy.** The company runs 134 ticks/day at 0.14 USD and 121 of 134 complete. The problem
  is not that it does too little; it is that **nobody sees what it does**. Adding autonomy before N3
  adds unobserved risk.
- **More instructions.** The always-on surface was 45,474 bytes and ~40% of the persona restated a
  rule already in a skill. The target is **fewer bytes carrying the same rules** — done, 28,697 →
  25,531 including two new rules.
- **More monitors of the same kind.** The estate has monitors; it lacks transports. A new dashboard
  nobody opens is the defect wearing a new hat.
- **A rebuild of the company.** `personal-secretary-mvp` is an asset with real integrations. The
  predecessor audit's conclusion still holds: *replace the console, keep the company.*
- **A new store for anything.** The estate already has R2, restic, a standby with a promotion tool, a
  journal, a session reader and an indexed search surface. The measured failure is **not building
  where something exists** — it has already cost a storage purchase and a 51.59/month DNS change that
  was done twice.
- **A queue that asks him more.** ~137 of 162 pending rows are engineering. The queue's own doctrine
  says *"anything I can fix. Fix it. A queue row is an admission that I could not"* — and nothing
  enforces it. That is a guard to add, not a queue to feed.

---

## 4. The one decision that is genuinely the owner's

Everything in §2 is mine to do. **One thing is not:** capacity.

The authority's disk is at 91-92% with ~7 GB free above a 25.9 GB database growing ~2.3 MB/h and a
6.6 GB archive on the same filesystem. The reclaim path is **much smaller than the queue believed** —
`/root/work` is active, `/root/git-rescue-20261012` (2.4 GB) is irreplaceable rescue work, and
`checkout-health-preserved` is live code — which leaves one plausible candidate of ~1.3 GB. **Reclaiming
does not close the gap.**

So it is his call, and it is already row **#473**: *enlarge the disk*, or move the archive offsite into
the R2 store the estate already pays for. I have amended **#484** (which recommended deleting the
rescue) to recommend adding disk instead. **This is asked as one question, with a recommendation, when
the tax question in `00-SYNTHESIS.md` §7 is off the table — not two at once.**

---

## 5. The test

A specification with no test is a wish. These are re-measured in 30 days from the same scripts
(`~/code/_evolve/finalize_corpus.py`, `aggregate_readers.py`, `journal.py status`):

| measure | today | target |
|---|---:|---:|
| `wrong-data` share of sessions | 11.4% | **< 5%** |
| tool calls per owner turn | 38.18 | **< 25** |
| `pwsh` share of tool calls | 40.65% | **< 25%** |
| job-polling calls per month | 10,916 | **< 3,000** |
| `repeated-work` share | 9.4% | **< 4%** |
| always-on instruction bytes (`zabz`) | 25,531 | **< 22,000** |
| journal lineages holding open pain | 3+ | **1** |
| silent failures with no transport | 45 recorded | **0, and the number re-measured** |
| owner questions pending, of which mis-filed | 162 / ~137 | **< 20 / 0** |
