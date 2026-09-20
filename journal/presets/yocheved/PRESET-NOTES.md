# The `yocheved` agent preset -- the Lakewood Phone & Tech manager workstation.

This preset exists so that the person sitting at Yocheved's laptop talks to an assistant that
is built for **running the shop**, not for coding or for the owner's own systems. It derives
from `cordis-bg`, which carries the background-first shell policy (long commands start as
background jobs instead of dying at the 120-second foreground timeout). That policy is
retained, so this preset is safe.

What differs from the deployment default is one row: the `persona`. Everything else --
toolset, sandbox, approval policy, background-first shell rule -- comes from the shared host
composition and must NOT be restated here. Restating a host-plane row in a preset is how the
two planes drift apart.

The persona is deliberately written in the second person and in plain language, because its
reader is a busy shop manager rather than an engineer. It states her authority and the four
rules that actually matter:

1. Every customer record she creates or edits names its source machine.
2. Look it up before changing it.
3. Never leave a customer's device or data in a worse state than found.
4. Never send anything outbound without her saying so in that conversation.

The sandbox here is `workspace-write` (set in `settings/machines/DESKTOP-FGV6KMH.yaml`), never
`danger-full-access`. Her machine must be powerful enough for the shop and unable to make
breaking changes to the owner's systems without him seeing it.
