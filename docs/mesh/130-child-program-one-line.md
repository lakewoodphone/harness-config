# 130 — The mesh child's program must be ONE line

**Date:** 2026-10-05 (machine-local) · **Author:** Zabz on ZABZ-YOGA
**Owner's instruction that started it:** *"time to shift and focus just on this and get it way more
robustly fixed for once and for all, the mesh and fanning is the underpinnings of our system"*, after four
`subagent` placements in one batch all came back with *"the remote process exited 0 but printed no completion
frame — the target profile did not run"*.
**Package:** `packages/plugin-remote-fanout` · **Tests:** 154 tests, 153 pass / 0 fail (one POSIX-only guard
skips on Windows) · **Recurrences this closes:** pains **P2826** (5/5 dispatches, 2026-10-02), **P2835**
(2026-10-02), handoff **H3188** (4/4, 2026-10-05).

---

## 1. Two independent faults, found in order, both on the same node

The transport was never the problem. ZABZ-TECH could not boot a child at all, for one reason; and once it
could, the transport still lost every **real** brief, for a second, unrelated reason.

### 1.1 `profiles\node_modules` was a dangling/untrusted junction — the child died in 74 ms

`C:\Users\ezabz\.dsh\profiles\node_modules` was a **junction** to a live target. Reading *through* it was
refused by Windows itself:

```
cmd /c type  …\profiles\node_modules\@deepseek-ai\dsh\package.json
  → The path cannot be traversed because it contains an untrusted mount point.
```

`dsh-app-boot` owns that directory (`healProfilesModuleFallback`, `dsh-app-boot/lib/index.js:657`) and
`mkdir`s it on every profile boot; `mkdir` on a reparse point in that state fails, so the child aborted before
running anything:

```
exit=1 elapsed=74ms
Error: UNKNOWN: unknown error, mkdir 'C:\Users\ezabz\.dsh\profiles\node_modules'
    at healProfilesModuleFallback (dsh-app-boot/lib/index.js:660)
    at composeProfile (dsh/lib/profile-boot-Dk-7KqJc.js:234)
```

**Removing the link is the fix, not re-pointing it.** `plugin-remote-fanout`'s own README says so (rule 3:
*"do not pre-create `<home>/profiles/node_modules` — dsh-app-boot owns that directory and pre-creating it as
a junction makes the child's boot fail with `UNKNOWN: unknown error, mkdir`"*). After removal the child booted
and answered in 16.9 s, and dsh recreated the directory itself as a real directory. A control junction created
from the same ssh session, to the same target, traversed fine — so the defect was the link's trust state, not
its target, and not the node.

### 1.2 With the node fixed, the transport still lost every multi-line brief

Reproduced through the package's own transport (`createSshTransport` + `buildPwshScript`), one variable at a
time, all to `desktop-ts`:

| task | task lines | task bytes | program bytes | framed? |
|---|---|---|---|---|
| `Reply with exactly: TECH_OK` | 1 | 27 | 829 | ✅ TECH_OK |
| `Line one.\nReply with exactly: TWOLINE_OK` | 2 | 40 | 827 | ❌ no frame, exit 0, 1.0 s |
| 8-line brief | 8 | 130 | ~930 | ❌ no frame, exit 0, 1.7 s |
| 3 lines, 1242 chars | 3 | 1242 | 2019 | ❌ no frame, exit 0, 1.2 s |
| **one** line, 1232 chars | **1** | 1232 | 2019 | ✅ ONELINE_OK |
| **one** line, 836 chars | **1** | 836 | 1623 | ✅ NINEHUNDRED_OK |

**The trigger is a newline in the task, not its size** — a 2 KB program framed fine when its task was one
line, and an 827-byte program failed when its task was not.

**Mechanism.** The transport delivers the program on the target's **stdin** (`ssh <node> powershell -Command -`,
the D4 fix that removed the argv ceiling). PowerShell reads such a program **lazily, statement by statement**.
When the child is launched it inherits that same pipe with **the rest of the program still unread in it**, and
the child's own stdio users swallow it — DSH starts MCP servers over stdin, and the target logged
`mcp_launcher.py firecrawl|jina` on every run. PowerShell then hits EOF, never reaches
`[Console]::Out.WriteLine($FANOUT_END…)`, never sets `$fanoutExit`, and exits **0** — so the transport settles
with a node-proven, lease-released, exit-0 run that did no work. That is exactly the field diagnostic, and it
is why a one-line probe always passed while every real brief failed.

Two independent confirmations of the mechanism, from the same session: the same multi-line program run **by
hand** (stdin from a PowerShell pipeline) framed correctly; and the **argv** delivery (`-EncodedCommand`) also
framed correctly, because argv does not share a pipe with the child.

## 2. The fix

`buildPwshScript` no longer returns a multi-line program. It returns **one line** whose payload is the real
program, base64-encoded UTF-16, evaluated inside the target:

```powershell
$ErrorActionPreference = 'Continue'; try { Invoke-Expression ([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('<payload>'))) } catch { [Console]::Error.WriteLine('…could not be decoded or started: ' + $_.Exception.Message); [Environment]::Exit(91) }
```

- PowerShell must read a single line to its end before executing anything, so **nothing is left in the pipe**
  for the child to consume — the defect cannot recur through that channel.
- The task's text never reaches a parser: no newline, quote or shell metacharacter of a brief is ever parsed
  by PowerShell, ssh or anything between them. (`psQuote` still guards the inner program; the outer channel is
  now inert.)
- **The D4 property is kept**: stdin delivery means constant argv and no Windows command-line ceiling. Measured
  with a 24,220-byte, 900-line brief: framed, `TWELVEK_OK`, 11.1 s. (`-EncodedCommand` was the other working
  shape, but it puts the program back in the command line and caps the task near 11 KB — the ceiling D4
  removed.)
- `unwrapPwshProgram` is exported so tests, a reader of a captured script, or any future tool can recover what
  the target will actually run.
- **POSIX gets the same protection in one word**: the child's command line now ends `< /dev/null`, so a child
  on a Linux node cannot eat the rest of the `sh -s` program either.

The provider's related blind spot is closed too: when a run is unframed it now prints the **stdout tail** as
well as the stderr tail. The reason this defect stayed invisible for a week is that everything the child said
landed on the stream nobody was showing.

## 3. The guard: `scripts/mesh-node-health.ps1` + task "Zabz mesh node health"

Deployed on ZABZ-TECH, runs every 10 minutes as `ZABZ-TECH\ezabz` (S4U, limited).

- **Repairs exactly one thing**, whose correct state is unambiguous: if `$DSH_HOME\profiles\node_modules` is a
  reparse point, it is removed and dsh recreates it as a real directory on the next profile boot. That is
  tonight's outage, prevented rather than diagnosed.
- **Reports, never repairs, everything else.** It walks `profiles\*\node_modules\*`, tests each link by
  *reading a file through it*, and classifies it `ok` / `UNTRUSTED` / `DANGLING` / `unreadable`. Whether a link
  is traversable depends on its **ACL owner** and on the **reader's logon class**
  (`106-desktop-last-mile.md` §1–§3), so a guard that "repaired" those would destroy links that are fine for
  the reader that matters. It logs a line only when something changes, and writes
  `.dsh\logs\mesh-node-health-state.json`.
- First run, verified: `LastTaskResult 0`, **11 links checked, all `ok`, nothing to heal**.

## 4. Verification (all observed, none assumed)

| check | result |
|---|---|
| Package test suite | **154 tests, 153 pass, 0 fail** (1 POSIX-only test skips on Windows) |
| Child boots on ZABZ-TECH by hand, after the link was removed | `TECH_OK`, exit 0, 16.9 s |
| Transport harness, multi-line brief (85 B, 5 lines) | **framed**, exit 0, 12.2 s |
| Transport harness, 120-line brief (5,082 B) | **framed, LONGMULTI_OK**, 5.2 s |
| Transport harness, 900-line brief (24,220 B) | **framed, TWELVEK_OK**, 11.1 s |
| The same program run by hand, and via `-EncodedCommand` | both framed — the two controls that isolated stdin laziness |
| Guard task on ZABZ-TECH | `LastTaskResult 0`, 11 links checked, 0 problems |

**One honest limitation: this is proven in a fresh process, not yet in a running engine.** The dispatcher's
provider is loaded when the engine starts, so an engine that was already running keeps the old code in memory
until it is restarted. Every verification above ran in a fresh Node process importing the fixed files — which
is precisely what a restarted dispatcher does. Until the engines restart, `subagent` from an already-running
session may still fail the old way; the code on disk is correct.

## 5. Still open, with evidence

1. **Engine restarts** to load the fix (dispatchers: this session's engine, and any other machine that
   dispatches). No code change needs to follow it.
2. **Every child on ZABZ-TECH pays ~1–2 s and a wall of errors** for MCP servers it cannot launch:
   `Unable to create process using 'C:\Users\ezabz\code\personal-secretary-mvp\.venv\Scripts\python.exe …
   mcp_launcher.py firecrawl': The file cannot be accessed by the system.` — the file exists (255,320 bytes,
   `zabz-tech\ezabz` owner, full-control ACLs for SYSTEM/Administrators/ezabz) and launching it fails from
   both the child and an interactive `cmd`. Not the reparse-point class (the `.venv` directory is a real
   directory). Unexplained; it does not stop a child, but it slows one and it is what made a test child
   answer *"I could not complete step 1"*.
3. **Version drift on that node**: `nodes.js` names an `_npx` cache `bin.js` whose engine is `0.2.0-rc.2`
   while the harness vendor prefix also carries `0.2.0-rc.2` and the checkout is shared. Worth a row in the
   table's `verified` field with a fresh date.

## 6. How to re-verify

```powershell
# the suite
cd ~/code/harness-config/packages/plugin-remote-fanout ; node --test test/*.test.mjs
# a real multi-line brief through the transport (the exact code path the provider uses)
node $env:TEMP\mesh-harness5.mjs          # built in this session; rebuild from the same three imports if gone
# the node-level preconditions
ssh 100.85.153.96 'powershell -NoProfile -Command "Get-Content C:\Users\ezabz\.dsh\logs\mesh-node-health-state.json -Raw"'
# and the rule itself, which must NOT be a junction
ssh 100.85.153.96 'cmd /c dir /a "C:\Users\ezabz\.dsh\profiles"'
```
