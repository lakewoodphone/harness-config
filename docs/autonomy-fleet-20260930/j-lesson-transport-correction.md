CORRECTION to L3106. That entry asserted a mechanism (the transport single-quotes the task string, so an
apostrophe in the prompt terminates the argument and the child cannot run) and drew a rule from it. The
mechanism is NOT supported by the evidence, and the rule was applied wastefully.

WHAT DISPROVED IT. Two of the eleven inline-prompt children whose briefs contained apostrophes did their
work completely. `b1-landscape.md` (51 KB) and `b3-infra.md` (46 KB) were written by children whose jobs
reported `failed ... the remote one-shot exited 1 and produced no final message`, and both reports follow
the brief's exact section structure, numbering and headings, so the brief arrived INTACT. One of them
carried stderr `error: unknown option '--profile'` - which is not a symptom of a mangled task string; it
is a command that actually ran and rejected an argument.

WHAT IS STILL TRUE, measured:
- Three of eleven inline-prompt children lost their answer and produced no final message.
- A controlled probe with no apostrophe made a clean round trip.
- All eleven file-brief children started.

WHAT IS THEREFORE UNKNOWN: whether the apostrophe has anything to do with it, and whether the failure is
the input path, the result path, or the child's own last action erroring. Stated plainly because the
previous entry stated it as fact.

THE CORRECTED RULES.
1. When a mesh child reports `failed` with `exited 1 and produced no final message`, CHECK ITS OUTPUT FILE
   BEFORE CONCLUDING IT DID NOTHING. Measured here: two children had completed and written their full
   deliverable while the job status said failed. I re-dispatched both workstreams before checking, which
   cost two duplicate sessions and two killed children. Read the artefact, then decide.
2. File-based briefs stay the practice anyway, for two reasons that do not depend on the failed
   mechanism: a long inline prompt is unreproducible after the fact, while a brief file is an audit trail
   the manager and the child both read; and a filename-only dispatch prompt cannot be mangled by any
   quoting layer. That is the value, not the apostrophe.
3. Do not promote a hypothesis to a lesson after two data points. L3106 was written within ten minutes of
   the failures and before a single child had reported. The system's own documented worst failure is a
   confident wrong claim; this was a small instance of exactly that, in the file that exists to prevent
   it.
