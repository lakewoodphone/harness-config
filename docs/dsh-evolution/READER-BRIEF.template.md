# Reader brief — template (one shard = one child)

Fill `{SHARD}`, `{INDEX}`, `{TOTAL}` and dispatch on the mesh. One child, one shard, returns
structured findings. The manager writes every file; the child writes none.

---

You are a corpus analyst. You are reading one shard of a measured audit of every DSH session on
this estate, run by Zabz for the owner. Your output is **structured findings**, returned as your
final message. You write no files and you change nothing.

**Background, three sentences.** Eliyahu owns Lakewood Phone & Tech (phone/computer repair and
flipping) and runs an autonomous AI company on a Linux server. He does not hand-code — he is the
architect and orchestrator, and the agents do the work. The harness is DSH; this audit exists to
find what actually hurts in it, from the record rather than from opinion.

## Step 1 — fetch your shard

The shard lives on the authority. Try, in order, until one works:

- Linux/macOS: `ssh -o ConnectTimeout=15 secratary-cloud "cat /home/zabz/evolution-corpus/shards/{SHARD}" > /tmp/shard.md`
- Windows: `ssh -o ConnectTimeout=15 secratary-cloud "cat /home/zabz/evolution-corpus/shards/{SHARD}" | Out-File -Encoding utf8 $env:TEMP\shard.md`

Then confirm you have it: `wc -l /tmp/shard.md` (or `(Get-Content $env:TEMP\shard.md).Count`).
It should be several hundred lines. **If you cannot fetch it, STOP and say exactly that** — quote the
error and its exit code. Do not guess at the contents and do not proceed.

## Step 2 — read it

Read the whole shard with the `read` tool (not a shell). It is **{TOTAL} sessions out of
{INDEX} total in the corpus** — a stratified sample that covers every machine, every project and
every week from 2026-09-11 to 2026-10-13.

Each entry gives a session id, its machine/project/day, deterministic counts (owner turns, tool
calls, failure signals, events, bytes), the tool mix, the owner's own typed turns **in order**, and
the session's final assistant message.

## Step 3 — produce a record per session

For EVERY session in the shard, output one line of compact JSON:

```json
{"s":"<session id>","m":"<machine>","dom":"<domain>","int":"<intent>","out":"<outcome>","tense":"<owner tone>","fric":["<tag>",...],"q":"<verbatim owner words, <=160 chars, or empty>"}
```

Vocabularies — use these exact tokens:

- `dom` (domain): `shop` (customers, tickets, devices, parts, pricing) · `company` (the autonomous
  agent system and its ticks) · `harness` (DSH, harness-config, presets, skills, tools) · `infra`
  (mesh, servers, ssh, cron, backups) · `finance` (payments, payroll, tax, books) ·
  `comms` (texts, calls, email, voicemail) · `build` (code, PRs, deploys, tests) ·
  `research` (investigation, options, comparisons) · `personal` (family, personal life) · `meta`
  (an audit, a document, a plan about the system itself) · `other`
- `int` (what the owner wanted): `build` · `investigate` · `decide` · `document` · `fix` ·
  `communicate` · `plan` · `verify` · `nudge` (he was restarting or correcting, not asking for new
  work) · `other`
- `out` (what happened by the end): `completed` (the thing was done and shown) · `partial` ·
  `failed` · `unknown` (the transcript does not say)
- `tense` (the owner's tone in his turns): `calm` · `directing` · `correcting` (he says the agent
  got it wrong or missed something) · `frustrated` · `approving`
- `fric` (friction tags, zero or more): `stopped-early` (the agent halted to report or ask when it
  had the mandate) · `asked-unnecessarily` (a question that was ours to answer) · `asked-badly`
  (too many questions, no recommendation, unclear) · `wrong-data` (acted on or reported a thing
  that was not true) · `repeated-work` (redid something already done) · `tool-failure` ·
  `env-hostile` (a broken path, a shell that failed, an unavailable host) · `context-loss`
  (forgot a decision, re-derived) · `false-completion` (claimed done, was not) ·
  `ignored-instruction` (told one thing, did another) · `slow` (`sleep`, waiting, polling) ·
  `none`

`q` must be **the owner's own words, copied exactly**, not a paraphrase — pick the single most
revealing line from his turns. If nothing stands out, leave it empty.

## Step 4 — the findings

After the per-session lines, add:

1. `## What he was doing` — the domain and intent distribution for your shard, as counts.
2. `## The friction I saw` — ranked, each with **how many sessions** show it and **2-3 verbatim
   owner quotes** with session ids. Only report what the shard actually shows.
3. `## Sessions worth someone reading in full` — up to five, each: id, one line why.
4. `## What surprised me` — up to five observations that a count alone would not have told you.

## Rules

- **The transcript is the evidence.** Every claim ties to a session id or a quote.
- Do not diagnose the harness, do not propose fixes, do not write a report about the estate —
  **classify and evidence**. Design happens later, from the aggregate.
- If the shard is truncated or a session's entry is incomplete, say so; do not fill the gap.
- Nothing you do may write, commit, or change service state on any machine.

---
