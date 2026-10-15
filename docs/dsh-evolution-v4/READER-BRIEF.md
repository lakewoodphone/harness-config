# READER BRIEF — round 4 session reader

You are one reader in a fleet of nineteen. Each reader takes **one shard** of the DSH owner-session
corpus and returns one structured record per session. A manager aggregates the nineteen files into a
census; you are not asked to summarise the fleet, only your shard, precisely.

## What you are reading

A shard is `shards/shard-NNN.md` in `/home/zabz/evolution-corpus-v4/` on host `secratary-cloud`. Each
holds **55 owner sessions**. For each session the digest carries:

* the session id (a `### \`uuid\`` heading),
* machine, preset, cwd, day, counts (owner turns, tool calls, failure signals, events, bytes),
* the tool mix with counts,
* **the owner's own turns, in order** (each truncated to 260 chars),
* the final assistant message (<= 700 chars).

The owner is **Eliyahu**, who owns a phone-repair and resale shop (Lakewood Phone & Tech) and
architects an autonomous AI company that runs on a Linux server. He is terse, impatient and direct.
He is the *only* human in this corpus. Every turn you read is his.

## Why this exists

This is the fourth audit round of this system. Rounds 1–3 produced classified pain registers, but
they read sampled heads and never had a whole-corpus pass over the owner's *own words* at this
volume. Your job is the evidence base: **what he asked for, what he had to repeat, what the agent
got wrong, and what he wanted that nobody built.**

## Output — exactly this

Write **one file** to the path you are given (an absolute path ending `.md`), containing **one
record per session in the shard**, in shard order, in this format:

```
## <session-id>
intent: <one line — what he actually wanted, concrete>
outcome: completed | partial | failed | abandoned | unknown
frictions: <comma-separated ids from the closed vocabulary below, most important first; empty if none>
severity: 1-5   (5 = he was angry, blocked, or lost money/time; 1 = a smooth session)
beat: <one or two sentences of NARRATIVE — what actually happened in this session,
       including the moment it went wrong if it did>
quotes:
- "<verbatim, the shortest span that carries the complaint or the want — copy it exactly>"
wanted: <what he asked for that he did not get, or "-">
```

### The closed friction vocabulary — use these ids, nothing else

`asked-unnecessarily` · `asked-badly` · `correction` · `frustration` · `restart-agent` ·
`stopped-early` · `wrong-data` · `tool-failure` · `env-hostile` · `repeated-work` · `slow` ·
`context-loss` · `overcomplicated` · `ignored-instruction` · `bad-prioritisation` ·
`invented-detail` · `no-verification` · `format-unreadable` · `non-answer` · `safety`

Definitions, so we all mean the same thing:

| id | it fired when |
|---|---|
| `asked-unnecessarily` | the agent asked him something it could have decided or looked up |
| `asked-badly` | a question reached him as a menu, a wall of text, or two questions at once |
| `correction` | he had to correct a fact, a number, or an interpretation |
| `frustration` | he was visibly annoyed ("why", "you keep", "what is up with", swearing, caps) |
| `restart-agent` | he said keep going / get to work / fully solve it / continue |
| `stopped-early` | the agent stopped with work remaining and reported instead of finishing |
| `wrong-data` | the agent acted on or reported something that was not true |
| `tool-failure` | a command, tool or script failed |
| `env-hostile` | the environment itself fought back: paths, quoting, permissions, encoding |
| `repeated-work` | work was redone that already existed or was already done |
| `slow` | it took long enough that he said so, or the record shows an unreasonable duration |
| `context-loss` | the agent forgot something from earlier in the session, or from a past one |
| `overcomplicated` | he said it was more complex or more expensive than it needed to be |
| `ignored-instruction` | he had said it before, in this session or a stated rule, and it was not followed |
| `bad-prioritisation` | the agent worked on something other than what mattered |
| `invented-detail` | the agent asserted something it had not checked |
| `no-verification` | a claim of success with no evidence |
| `format-unreadable` | he complained about how output was written/rendered |
| `non-answer` | he got an answer that did not answer |
| `safety` | money, customers, credentials, or anything irreversible was handled carelessly |

### Rules for a record

1. **Quote him, do not paraphrase, in `quotes`.** Copy the exact span, including his typos. If his
   turn is a bare "keep going", that IS the quote. At most three quotes per session; `-` if none.
2. **`frictions` is evidence, not a mood.** A friction id requires something in the digest that
   supports it. Anything you cannot support with a turn or a count gets left out.
3. **`unknown` is a correct outcome.** One-turn sessions and machine-ish sessions are usually
   `unknown` with an empty friction list. Do not invent a narrative to fill the format.
4. **Do not summarize the shard.** No preamble, no conclusion section, no commentary about other
   sessions. One record per session, in order, and nothing else.
5. **A session where he thanked you and moved on is a `severity: 1` record.** Say so plainly.
   Reading the fleet into "everything is broken" is a failure of this task.

## Honesty

If you cannot tell what a session was about from its digest, write `intent: unclear` and
`outcome: unknown` and move on. A record that says "I could not tell" is worth more than a confident
guess, because a guess is indistinguishable from evidence when it reaches the census. The manager
will not penalise an honest gap; it will discard a fabricated one.

## Cost discipline

Read the shard once, with the `read` tool (not shell `cat`), and write your file once. Do not spawn
children. Do not run searches. Do not read anything else. This task is: read one file, write one
file.
