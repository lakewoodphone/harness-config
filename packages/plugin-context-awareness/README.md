# dsh-plugin-context-awareness

The agent can see its own context, and is told plainly when a compaction happened.

## The defect it removes

The engine has a token meter, three context projections, and a `/cost` command. The **agent**
could read none of them, so its belief about its own context was a guess — and the guess had a
direction: pessimistic, early, and acted on. Sessions stopped coherent work, announced a limit,
and proposed a fresh window at a fraction of real occupancy.

The instruction surface made it worse rather than better: the persona told the agent the harness
"does not tell you when either happened" (rule 8, corrected 2026-10-26). An unobservable lossy
event, described as silent, produces pre-emptive panic — and the restart the panic asks for does
not save the context it fears, it pays a fresh prefix.

## What it does

| Surface | When | What it says |
|---|---|---|
| `context_status` tool | on demand | tokens, window, percent, band, when compaction fires, compaction count, and what to do in this band |
| `CONTEXT …` notice | first measurable step, then on each band **crossing** | the number, the band, and — at `tightening`/`critical` — write down what is expensive to lose; never restart to "save" context |
| `COMPACTED …` notice | once after `compaction/summary` or `compaction/prune` | what a checkpoint keeps, what is at risk, that nothing was destroyed, where the transcript is, and that the agent must not re-do recorded work or restart |

Bands are fractions of the window, default `[0.35, 0.55, 0.70]` → `comfortable / working /
tightening / critical`. Compaction in the `zabz` preset fires at `thresholdRatio 0.7` of a
1,000,000-token window, and the notice states that real number rather than a vague warning.

## Where the number comes from — deliberately not a second fold

`ctx.tokenMeter.measure(session)`: the engine's own pricing of its own request image, the same
number the browser meter shows. A plugin that re-derived token pressure is the drift defect this
estate has paid for twice. If the meter is absent **or throws**, the notice says so in one line
and the agent is told not to guess; it never invents a reading.

## Plane, and why

Host plane (a profile bundle row, `cordis.patch.yml`), not a preset row: blindness is a property
of the engine, not of one persona — a mesh subagent and a session on any other preset have the
same missing sense. One row sees every session in the process; state is keyed by `Session`, so
two windows never share a band. It publishes no service, so it needs no isolate realm.

## Verify it

```sh
cd packages/plugin-context-awareness
node --test test/logic.test.mjs test/wiring.test.mjs    # 23 assertions, no engine needed
```

Then in a live session, the first tool result after the profile loads carries a `CONTEXT` line.
Measured 2026-10-26 in the session that shipped it: `208,587 of 1,000,000 tokens (21%) · band
comfortable`, and the `context_status` schema registered in the same step.

What the tests cannot prove — and do not claim — is that the engine *delivers* `additionalContexts`
to the model. That was measured live, not asserted.

## The gap this does not close

`dsh-compaction-basic`'s summariser is told `Do NOT mention this summarization request or that the
context was compacted`, and its summary template has no section for **what was dropped**. The
ticket that started this work (`docs/self-audit-2026-10-26/97-MASTER-FINDINGS.md` §10) called that
"the compaction notice is suppressed by design". This plugin does not change that prompt — it
cannot, the wording is hardcoded and patching `node_modules` dies at the next engine upgrade.
What it does instead is put the truth in front of the agent *after* the event, so the checkpoint is
no longer indistinguishable from a transcript. Changing the summariser itself means shipping our
own compaction plugin, and that should be done against the benchmark harness from arXiv 2610.20116
rather than on faith.

## Config

Every key is optional: `enabled`, `bands`, `thresholdRatio`, `toolName`, `speakOnFirstStep`,
`contextWindow`.
