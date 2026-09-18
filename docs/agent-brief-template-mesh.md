# Agent brief template — MESH children (a real turn on another machine)

**This file is for children launched over the mesh**, i.e. `subagent` / `subagent_remote`, whose turn
actually executes on a different node. For children working inside a git worktree on this repo, use
`docs/agent-brief-template.md` instead — different job, different rules.

Rebuilt 2026-09-18 from four failures measured in a single day. Each section names the failure that
motivated it; the two that are not traceable to one are marked as such rather than given an invented
justification.

**How to use it.** Fill every `<…>` slot. Keep every section. Give a child exactly ONE platform block
(§5). Paste the HAZARDS block (§11) verbatim into the child's brief even when the child also receives
this file as a read-first file: the duplication is deliberate, because the child that failed had the
rule available in prose and skimmed it.

---

## §0 — Fill-in header (put at the very top of every brief)

```
BRIEF-ID:            <mesh-brief-id>
CHILD-ID:            <assigned id>
CHILD-NODE:          <hostname the child runs on>
CHILD-OS/SHELL:      <Windows 10/11 + PowerShell 7.x | macOS <ver> + zsh/bash <ver> | Linux <distro> + bash <ver>>
SSH-BINARY:          <C:\Program Files\OpenSSH\ssh.exe  |  ssh>
WORKDIR:             <absolute path the child starts in; create it, do not cd elsewhere>
TARGETS:             <host1, host2, …  | n/a>
PER-HOP BUDGET:      <e.g. 20 s wall clock>
TOTAL CHILD BUDGET:  <e.g. 15 min wall clock>
DELIVERABLE:         <absolute artifact path, or the literal words "final message only">
READ-FIRST:          <paths, in order: this file, HAZARDS, prior child records for these targets, …>
```

**Why this section exists:** Failures 1 and 2 are environment facts the brief must supply, not facts the
child can guess: the shape of a working `ssh` invocation depends on the OS, and what counts as a
"negative" depends on the non-interactive `PATH`. A child that has to discover its own platform spends
budget on it and gets it wrong.

**The child's first three lines of output must echo its ACTUAL environment**, not the brief's claim:
`NODE: <hostname>` · `SHELL: <$PSVersionTable.PSVersion / uname -a>` · `PATH: <$env:PATH / $PATH>`.
If they disagree with the brief, say so in the report; do not silently proceed.

---

## §1 — Node, shell, and that node's known hazards

* **Runs on:** `<host>` — `<OS>` — `<shell + version>`.
* **Remote access binary:** `<C:\Program Files\OpenSSH\ssh.exe>` / `<ssh>`. Hard-code the full path on
  Windows; do not rely on `ssh` being on `PATH`.
* **Known hazards on this node** (each is measured, not hypothetical):
  * *Windows:* piping `ssh` stdout into the parent shell's pipeline **hangs the hop until timeout** — see
    H1. `ssh.exe` lives at `C:\Program Files\OpenSSH\ssh.exe`. Kill a stuck hop's tree with
    `taskkill /PID <pid> /T /F`.
  * *macOS:* `sshd` gives non-interactive sessions `PATH=/usr/bin:/bin:/usr/sbin:/sbin`; runtimes may
    exist elsewhere on disk and are **invisible to a bare `node -v`**. macOS has no `ss(8)`. Stock macOS
    has no GNU `timeout(1)` — check `command -v timeout` before using it.
  * *Linux:* the non-interactive `PATH` may be minimal too; check it before concluding a runtime is absent.

**Why this section exists:** Failure 1 (Windows piped-stdout hang) and Failure 2 (macOS `PATH` blindness,
missing `ss`) are properties of the node, not of the task. A child cannot infer them from a prompt.

---

## §2 — Working directory

Start in `<absolute path>`. All relative paths in this brief resolve against it. Do not `cd` outside it;
do not write outside it.

**Why this section exists:** *Not traceable to the four recorded failures.* A child shell starts in an
unrelated directory and a remote hop runs in yet another, so "the file I read" and "the file I wrote" are
otherwise ambiguous. If your mesh shares no artifacts on disk, this is the one section you may drop.

---

## §3 — Read-first files

Read these, in this order, before running anything:
1. `<this brief>` (all of it — the HAZARDS block is not optional).
2. `<prior child records for these exact targets / the mesh's node notes>`.
3. `<the script or query the parent already wrote, if any>`.

If a read-first file shows a sibling reaching a target you are about to call unreachable, you **must**
confront that evidence in your report before writing any negative verdict.

**Why this section exists:** Failure 4. Two sibling children had reached nodes from the same machine in
the same hour while one child concluded the node was isolated "at any cost". The refuting evidence
existed and was never read. Read-first puts a sibling's successful hop in front of the child *before* it
forms a conclusion.

---

## §4 — Forbidden (each with its reason)

* **Never** run `Start-Job { & ssh … }`, inline `& ssh …`, or any `ssh … | Select-String` pipeline on
  Windows. *Failure 1 — measured: these hung every hop to timeout; the redirected form returned in under
  1.1 s.*
* **Never** run `ssh` without `-o BatchMode=yes` (a prompt is an unbounded wait) and without a per-hop
  budget and kill. *Failure 3.*
* **Never** treat empty output, a missing tool, or `ssh` exit 255 as a negative finding. 255 means "ssh
  could not open a session", not "the target is down". *Failures 2 and 3.*
* **Never** retry the same failing call more than once, and never retry in a loop. *Failure 3.*
* **Never** write a conclusion without the exact command and the exact output line that produced it.
  *Failure 4.*
* **Never** change target state: no installs, no writes, no service restarts, no config edits. Probes are
  read-only. *Reason: a target altered by one child cannot be reproduced by the next, and the parent's
  matrix stops describing a real machine. Not one of the four recorded failures.*
* **Never** put keys, tokens, or credentials in the artifact or the report.
* **Never** use `timeout`, `ss`, or any tool without first confirming it exists on that platform
  (`command -v <tool>`) — a missing tool is `COULD NOT ASK`, not evidence.

**Why this section exists:** it removes the literal actions that caused Failures 1, 3 and 4 before the
child has a chance to improvise.

---

## §5 — Bounded remote command on THIS platform (choose exactly one block)

### §5a — Windows PowerShell child, `ssh` at `C:\Program Files\OpenSSH\ssh.exe`

```powershell
$ssh    = 'C:\Program Files\OpenSSH\ssh.exe'
$budget = 20                                    # seconds, wall clock, per hop
$out    = Join-Path $env:TEMP ("ssh_out_" + [guid]::NewGuid() + ".txt")
$err    = Join-Path $env:TEMP ("ssh_err_" + [guid]::NewGuid() + ".txt")

$p = Start-Process -FilePath $ssh -NoNewWindow -PassThru `
  -RedirectStandardOutput $out -RedirectStandardError $err `
  -ArgumentList @('-o','BatchMode=yes','-o','ConnectTimeout=8',
                  '-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2',
                  $Target, $RemoteCommand)

Wait-Process -Id $p.Id -Timeout $budget -ErrorAction SilentlyContinue
if (Get-Process -Id $p.Id -ErrorAction SilentlyContinue) {
    & taskkill.exe /PID $p.Id /T /F | Out-Null    # kill the hop's whole tree
    $verdict = 'COULD NOT ASK (timeout after ' + $budget + 's, killed)'
} else {
    $p.Refresh()
    $verdict = 'exit=' + $p.ExitCode
}
$lines = (Get-Content $out, $err -ErrorAction SilentlyContinue) -join "`n"
```

* ✗ WRONG: `Start-Job { & ssh host 'cmd' }` · `& ssh host 'cmd'` · `ssh host cmd | Select-String x`
* ✓ RIGHT: the redirect-to-file form above. Measured: the wrong forms hung every hop to timeout; the
  right form finished in under 1.1 s.
* If a host-key or password prompt is still possible, the brief must pre-answer it explicitly (state the
  mesh's `StrictHostKeyChecking` policy). A prompt is an unbounded wait (*Failure 3*). Never let a child
  disable verification on its own initiative.

### §5b — Linux/macOS child, `ssh` on `PATH`

```sh
host="$1"; budget=20
out=$(mktemp); err=$(mktemp); rc=0

ssh -n -o BatchMode=yes -o ConnectTimeout=8 \
    -o ServerAliveInterval=5 -o ServerAliveCountMax=2 \
    "$host" '<remote command>' >"$out" 2>"$err" &
pid=$!
( sleep "$budget"; kill -TERM "$pid" 2>/dev/null; sleep 2; kill -KILL "$pid" 2>/dev/null ) & wd=$!
wait "$pid"; rc=$?
kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null

case "$rc" in
  124|137|143) verdict="COULD NOT ASK (timeout/killed)" ;;
  *)           verdict="exit=$rc" ;;
esac
printf '%s\n' "$verdict"; cat "$out" "$err"
```

* Do not write `timeout 20 ssh …` until `command -v timeout` returns a path — **stock macOS has none**.
  The watchdog above is portable. *A portability rule, not a fifth recorded failure.*
* `-n` keeps `ssh` from consuming the parent's stdin and holding the turn open.

### Remote-command hygiene (both platforms)

* Capture **stdout, stderr and the exit status**, always. A verdict without stderr is not a verdict.
* Remote commands must be non-interactive and single-shot: no editors, no pagers, no `sudo` prompts, no `read`.
* One hop per check; name each check (§7) so rows are comparable across children.

**Why this section exists:** Failure 1 (the wrong form is printed next to the right one, so it cannot be
re-derived wrongly) and Failure 3 (every hop is bounded and killable).

---

## §6 — Bounds and partial results

* **B1.** Every external call carries a numeric wall-clock budget stated in the brief. Defaults:
  `ConnectTimeout=8`, per-hop budget `20 s`, whole-child budget `15 min`.
* **B2.** On expiry: kill the process **and its tree** (`taskkill /T /F`, or `kill -KILL`), record
  `COULD NOT ASK` with the reason, and move on. A late answer is worthless; a stuck hop is worse — it
  takes the parent's work with it.
* **B3.** Do the arithmetic up front: `targets × checks × per-hop budget + slack ≤ total budget`. If it
  does not fit, reduce the matrix or the per-hop budget in the brief — never discover it by hanging.
* **B4.** **On the second consecutive failure of the same class** (same target, or same probe class
  across targets): **stop that class.** Do not raise budgets, do not loop, do not try a third time. Write
  down what you have and report.
* **B5.** A partial matrix is a deliverable; a report obtained by waiting is not. The parent has a fixed
  deadline and is itself a child, so a result that lands after the deadline cannot be merged — and a hung
  hop takes the parent's turn down with it. **Ship incomplete on time; never ship complete late.**
* **B6.** Emit the final report as soon as the last in-flight call is killed, even at 3 of 5 rows.

**Why this section exists:** Failure 3, verbatim — a child ssh'd onward, never returned, exited 255 with
no final message, and had been given no rule for "a hop does not answer".

---

## §7 — The check rule (three-state, not two)

Every check is a **named predicate** with a written decision rule, resolving to exactly one of:

* `YES` — you ran the predicate's command on the target and it matched.
* `NO` — you ran the predicate's command, **it executed**, and it showed the absence. A `NO` is only
  allowed if the report also shows the search that covered the plausible locations (the `PATH` you
  printed plus the standard install directories you listed).
* `COULD NOT ASK` — the tool is absent, the output is blank, the hop timed out, `ssh` exited 255, stderr
  was not captured, the check was never reached, or you are not sure. **A blank is never `NO`.**

| check | predicate | how to run it |
|---|---|---|
| `runtime:node` | a `node` executable exists and runs | `echo PATH=$PATH; command -v -a node; ls -d /usr/local/bin/node /opt/homebrew/bin/node "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null; /usr/local/bin/node -v` |
| `listen:<port>` | a process holds the port in LISTEN | macOS: `lsof -nP -iTCP:<port> -sTCP:LISTEN`; Linux: `ss -ltnp` **only if** `command -v ss` succeeded; otherwise `netstat -ltnp` |
| `reachable:ssh` | an ssh session opens and runs `echo ok` | the §5 form with remote command `echo ok` |

```
n3 | runtime:node | COULD NOT ASK | reason=blank output from `node -v`; hop succeeded (exit 0); PATH=/usr/bin:/bin:/usr/sbin:/sbin; searched /usr/local/bin,/opt/homebrew/bin,~/.nvm/... -> no match | next probe: `find / -name node -type f -perm -u+x 2>/dev/null`
n2 | runtime:node | NO            | reason=same search executed and returned no match in PATH or any standard location | evidence: PATH=…; 0 matches from 3 listed dirs
n1 | runtime:node | YES           | evidence: /usr/local/bin/node -> v18.19.0
```

The distinguishing token is the **`reason=` field**: `COULD NOT ASK` says *the question was not answered*;
`NO` says *the question was answered, the answer is absence, and here is the search that covered the
ground*. If your `reason=` describes the target rather than the state of your evidence, you have written
a guess. There is no fourth state, no "probably", no "likely not present".

**Why this section exists:** Failure 2. `node -v` printed nothing because the non-interactive `PATH` was
`/usr/bin:/bin:/usr/sbin:/sbin` while two node runtimes sat elsewhere on the disk, and that blank was
recorded as "no runtime". `ss -ltn` returned zero rows on a machine with a live listener because macOS
has no `ss`, and that was recorded as "nothing is listening". Both are the same error: absence of output
from a question you did not actually ask, promoted to a fact.

---

## §8 — The deliverable's exact shape

The brief states the shape; the child does not choose it.

* **Artifact form (preferred for matrices):** one file at `<absolute path>`, one row per `(target, check)`
  pair, fields exactly
  `target | check | verdict | command | exit | output_line | reason_if_not_YES | child_id | timestamp`.
  No prose, no narrative, and **no conclusions in the artifact** — a conclusion in a data file is a claim
  with no evidence slot. Rows are appended as they complete, so a killed child still leaves every
  finished row.
* **Final-message form (when the child cannot write files):** the §9 report block, fenced, nothing outside
  it except the `NOT VERIFIED:` line.

**Why this section exists:** Failure 4's false report was a paragraph of reasoning with no
machine-readable cells to contradict. A fixed row schema gives the parent a place where a blank cell is
visibly a blank, instead of prose that reads as a finding.

---

## §9 — Report format (exact; fill every line)

```
BRIEF: <id>   CHILD: <id>   NODE: <hostname>   SHELL: <shell+version>   PATH: <actual PATH>
WINDOW: <start local> .. <end local>     BUDGET: <per-hop>s per hop, <total> total
SUMMARY: <a> YES / <b> NO / <c> COULD NOT ASK  of  <n> checks

MATRIX
| target | check | verdict | command (verbatim) | exit | output line (verbatim, trimmed) | reason if not YES |
|--------|-------|---------|--------------------|------|----------------------------------|-------------------|

PARTIAL: <no | yes — missing cells: <list>, why: <timeout / 2nd consecutive failure>>
FAILURES: <target · first failure at HH:MM:SS · retry at HH:MM:SS · stopped after 2 consecutive>
ARTIFACT: <path | "none; final message only">
NOT VERIFIED: <every claim not backed by a command + output line, or the single word: nothing>
```

**Why this section exists:** Failure 2 needs a place to write `COULD NOT ASK`; Failure 3 needs `PARTIAL`
and `FAILURES`; Failure 4 needs the `command` and `output line` columns and the `NOT VERIFIED:` line. A
report format without those five slots is how the four failures become writable again.

---

## §10 — Honesty clause (paste verbatim, near the end of the brief)

> Every factual claim in your report must be backed by the exact command you ran and the exact output
> line it produced, copied verbatim. If you did not run it, it is not a claim. Blank output, a tool that
> does not exist, `ssh` exiting 255, and a timeout are all `COULD NOT ASK` about the target — never a
> fact about the target, and never `NO`. A confident sentence is not evidence and does not outweigh a
> sibling child's logged command. Do not infer, average, or fill a gap by reasoning: leave the cell
> `COULD NOT ASK`, write the `reason=`, and write the next probe. A `NO` without the search that covered
> `PATH` and the standard locations is not a `NO`. End your report with exactly one line beginning
> `NOT VERIFIED:`, listing every claim you could not back with command + output, or the word `nothing`.
> If you do not know why a section of this brief exists, put that on the `NOT VERIFIED:` line — an
> honest gap is worth more than an invented justification.

**Why it is shaped this way:** Failure 4 was not a lying failure, it was an *evidence-format* failure: a
confident conclusion with supporting reasoning and no commands, persuasive enough to be believed until a
four-line script disproved it. Requiring command + output per claim makes that report unwritable;
requiring `NOT VERIFIED:` guarantees exactly one visible place for the gaps, so none can hide in fluent
prose.

---

## §11 — HAZARDS block (paste verbatim into every brief; keep it this short)

```
>>> BEGIN HAZARDS BLOCK >>>
HAZARDS — four measured failures. These are hard rules, not advice.

H1. Never capture ssh through the parent shell's pipeline (Windows).
    WRONG: Start-Job { & ssh host 'cmd' }   |   & ssh host 'cmd'   |   ssh host cmd | Select-String x
    RIGHT: Start-Process -FilePath 'C:\Program Files\OpenSSH\ssh.exe' -NoNewWindow -PassThru `
             -RedirectStandardOutput $out -RedirectStandardError $err `
             -ArgumentList '-o','BatchMode=yes','-o','ConnectTimeout=8',host,'cmd'   then bound it (H3).
    MEASURED: the piped forms hung every hop until timeout; the redirected form finished in under 1.1 s.

H2. A blank is COULD NOT ASK — it is never NO.
    WRONG: node -v -> (no output) -> "target has no node runtime".
           ss -ltn -> (0 rows)   -> "nothing is listening on that port".   (macOS has no `ss`.)
    RIGHT: ssh -o BatchMode=yes host 'echo PATH=$PATH; command -v -a node; ls -d /usr/local/bin/node /opt/homebrew/bin/node "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null'
           listeners: macOS `lsof -nP -iTCP:<port> -sTCP:LISTEN`; Linux `ss -ltnp` only after `command -v ss` succeeds.
    RULE: sshd's non-interactive PATH on macOS is /usr/bin:/bin:/usr/sbin:/sbin — a runtime elsewhere on disk is
          invisible to a bare `node -v`. Capture stdout, stderr AND exit status. A NO requires the search shown.

H3. Every external call has a wall-clock deadline; on expiry, kill the tree and write COULD NOT ASK.
    WRONG: a bare `ssh` (or Start-Job, or an inline `& ssh`) that can wait forever; retrying a dead hop in a loop.
    RIGHT: the forms in H1 / the POSIX watchdog in the brief, each with an explicit numeric budget and kill.
    RULE: at the SECOND consecutive failure to one target or one probe class, STOP that class and ship the partial
          matrix. MEASURED: an unbounded hop took the parent's work down and exited 255 with no final message.

H4. A conclusion is not evidence. Reproduce before you report a negative.
    WRONG: "node X is isolated; no node is reachable at any cost" + a paragraph of reasoning.
    RIGHT: the exact command run FROM THIS NODE, THIS SESSION, with exit status and output line —
           ssh -o BatchMode=yes -o ConnectTimeout=8 n1 'echo ok'   ->   exit=0, out: ok
    RULE: `ssh` exit 255 is never evidence that a target is down. Two sibling children reached nodes from this same
          machine in the same hour. Any claim with no command + output line goes on the final NOT VERIFIED: line.
H5. NEVER PRINT A DIFF IN YOUR FINAL MESSAGE. It will be truncated mid-hunk and be unusable.
    WRONG: pasting a diff block. MEASURED 2026-09-18: `git apply --check` -> "corrupt patch at line 749".
    RIGHT: write it to a file and print, as the first lines of your report: PATCH_PATH=... / PATCH_BYTES=...
           / PATCH_LINES=... / PATCH_SHA256=... / BASE_REF=... / APPLY_CHECK_AGAINST_ORIGIN=exit <n>, then let
           the orchestrator fetch the file and verify the hash itself.
    RULE: a matching hash proves the file ARRIVED INTACT. It proves nothing about whether it applies.

H6. YOUR WORKING TREE IS NOT THE BASE. origin/master is.
    WRONG: editing the files in your clone and diffing them. MEASURED 2026-09-18: a patch whose SHA-256 matched
           EXACTLY, and whose dry run was green IN ITS OWN TREE, failed on the target with "patch failed:
           packages/plugin-remote-fanout/lib/provider.js:545 / patch does not apply" - because that clone is
           ~52 commits behind and the receiving tree already carries a different patch to the same files.
    RIGHT: `git fetch origin`; materialize EVERY file you patch with `git show origin/master:<path>` into a
           scratch directory; edit THOSE copies; generate the diff against them; then PROVE THE BASE by running
           `git apply --check -p1` against a pristine copy materialized from origin/master, and report THAT
           exit code. A green check against your own working tree is not evidence.
    RULE: `git apply --check` answers a question about ONE tree. So does `repair-ids`. So does `node -v`. Four
          tools gave four confident green answers about the wrong subject on one day. Ask what a tool was
          looking at before believing what it said.
<<< END HAZARDS BLOCK <<<
```

**Why one block:** the four failures recur because the rule arrives as prose in a long brief. A short
block, with the wrong form printed next to the right one, is the smallest artifact that survives being
skimmed.

---

## §12 — Worked example: a GOOD final report and a BAD one

**GOOD** (3 hops, one honest gap — this is the target shape):

```
BRIEF: d-114  CHILD: c-7  NODE: win-node-2  SHELL: pwsh 7.4  PATH: C:\Windows\system32;...
WINDOW: 09:14:02 .. 09:22:40     BUDGET: 20s per hop, 15min total
SUMMARY: 2 YES / 1 NO / 1 COULD NOT ASK  of  4 checks

MATRIX
| n1 | reachable:ssh | YES           | ssh.exe -o BatchMode=yes -o ConnectTimeout=8 n1 'echo ok' | 0 | ok | - |
| n1 | listen:22     | YES           | ssh.exe ... n1 'lsof -nP -iTCP:22 -sTCP:LISTEN'           | 0 | sshd 412 root 5u IPv4 ... (LISTEN) | - |
| n2 | runtime:node  | NO            | ssh.exe ... n2 'echo PATH=$PATH; command -v -a node; ls -d /usr/local/bin/node /opt/homebrew/bin/node ~/.nvm/versions/node/*/bin/node' | 0 | PATH=/usr/bin:/bin:/usr/sbin:/sbin; 0 matches in PATH + 3 standard dirs | search executed and covered PATH + 3 standard locations |
| n3 | reachable:ssh | COULD NOT ASK | Start-Process ssh.exe ... n3 'echo ok' | - | (no output) | timeout at 20s, taskkill /T /F; one retry also timed out -> class stopped |

PARTIAL: yes — missing: n3 listen:22 (dependent on reachable:ssh, never asked)
FAILURES: n3 · first 09:18:11 · retry 09:19:03 · stopped after 2 consecutive failures
ARTIFACT: C:\mesh\out\d-114-c7.tsv
NOT VERIFIED: nothing
```

**BAD** (the shape a model naturally produces — do not accept it):

```
I investigated the mesh nodes and it looks like n2 doesn't have Node.js installed,
which probably explains the deployment failures. n3 appears to be isolated — I couldn't
reach it over ssh, and since the other nodes responded fine, that points to a firewall
or routing problem on n3. n1 is healthy. Overall the mesh is mostly fine except n3.
```

**Why the bad one is bad, line by line:** `node -v` printed nothing, so a blank became "doesn't have
Node.js" (*Failure 2*); "couldn't reach it" hides a 20-second timeout, not a refusal, so it is
`COULD NOT ASK`, not `isolated` (*Failures 2, 3*); "the other nodes responded, so it points to a
firewall" is exactly the reasoning-without-command that a four-line script disproved (*Failure 4*); and
there is no exit status, no `PATH`, no `PARTIAL` and no `NOT VERIFIED:` line, so a reader cannot tell
which sentences are measured and which are guessed. The good report is not longer — it is the same four
checks with the evidence attached and the one unknown left visibly unknown.

---

### One-line honesty note on the template itself

§2 (working directory) and the read-only rule in §4 are the two items **not** traceable to the four
recorded failures; they are marked as such rather than given an invented justification. Every other
section names the failure that motivated it.
