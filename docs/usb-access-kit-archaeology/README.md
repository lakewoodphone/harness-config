# USB access kit - the archaeology, and the family tree

**Read this folder before touching, rebuilding or re-diagnosing the LPT access kit.** It exists because on
2026-10-15 an evening was spent re-deriving failures that had already been solved months earlier, and the
owner's correction was blunt: *"instead of keep on reinventing the wheel ... find all those sessions ... and
figure out how to set this up way better and more robust."*

The kit's **operational** documentation is `personal-secretary-mvp/tools/lpt-access-kit/T1-WINDOW-LIFECYCLE.md`
(deployed to the stick, pointed at from its RUNBOOK, and summarised in the `lpt-access-kit` skill). **This
folder is the HISTORY** — where the thing came from, what the previous generations did, and why the rebuild
lost their knowledge.

## The files

| file | what it is |
|---|---|
| `00-HANDOFF-the-corrected-approach.md` | the owner's correction, the three research streams that were dispatched, and the technical state at the time |
| `A-archive.md` | every archived AI session about the kit, and the fix-and-relose pairs. **Also two live estate defects, see below.** |
| `B-files.md` | every file, script, doc and git commit across the estate, with a dated family tree of the kit generations |
| `C-oldkit.md` | what the OLD kit actually did to make SSH work on Windows, quoted from source against the seven questions the rebuild kept failing |

## The family tree

```
scripts\windows                      2026-05-21   Gen A
  ->  scripts\copilot-ssh-field-kit           2026-07-05   Gen B, 89 files, PROVEN WORKING
  +   scripts\lpt-full-diagnostics             2026-08-14
  ->  tools\lpt-diagnostics-kit                2026-09-02
  ->  tools\lpt-access-kit                     2026-10-05   the rebuild
  ->  the 2026-10-15 T1 open-fix chain
```

`CopilotSshAccess` is the **USB folder name** (`D:\CopilotSshAccess\`), NOT a repo directory - which is why
months of looking for it in a repo found nothing. Both retired halves carry a `MOVED.md` dated 2026-10-05
recording the measured drift between them.

**A real working run is preserved, uncommitted, at
`personal-secretary-mvp/scripts/copilot-ssh-field-kit/latest-run/`** - MIRIAM, 2026-07-04 23:33:
`status=REVERSE_TUNNEL_ACTIVE`, `port22_listening=True`, `direct_ssh=ssh Miriam@192.168.50.239`, `problems=0`.

## The single finding that explains the whole evening

**The old kit never moved sshd off port 22.** It wrote no `Port` directive at all; the only non-default port
was the reverse-tunnel port on the desktop. The rebuild writes a random `Port` into `sshd_config` and then has
to make that config change take effect on an already-running service - a problem the original never had
because it never changed the port. Full record: journal **L5600**.

## Why the reboot happened at all

A 2026-10-05 prior-art child concluded, verbatim: *"No journal entry describes a USB-carried
remote-access/diagnostics kit - that ground is genuinely new."* True, and useless: the working kit was in the
repo the whole time. **The search asked the JOURNAL; the journal is not the estate's inventory.** Full record:
journal **L5664**, alongside `AGENTS.md §0`'s two failures of the same shape.

## Two live defects on `origin/master` this folder's research found

1. **The transcript archive has been dead since 2026-10-11.** 0 of 7,797 objects in `manifest.sqlite` is dated
   2026-10-12 or later; no host has answered `machine_contact` since `2026-10-11T19:57:27Z`. The cause is in
   `AGENTS.md §1`: the archive is driven by *cron on `secratary`*, and `secratary` was **frozen as the
   rollback anchor on 2026-10-11 05:43Z**. It must be re-homed onto a host that is not frozen, and the rule
   and the freeze reconciled in a file rather than in memory.
2. **`origin/master` still ships the literal shop-wide password.** `scripts/copilot-ssh-field-kit/Enable-ShopSsh.ps1`
   on master prints `Password: ShopRepair2024!`, `CLEANUP: Account and SSH are auto-disabled on next reboot.`
   and `sc.exe create sshd ... start=auto`. The hardening commit is **`99f7134d`, which is on three branches
   and on no master** - `git log -S 'ShopRepair2024!' origin/master` returns only the commit that ADDED it.
   `MOVED.md` IS on master, so master ships the retired folder with its retirement notice and the unhardened
   file inside it.

## The two fix-and-relose pairs - expect this shape

- **P2852** (the teardown must remove the `authorized_keys` line it added): declared closed 2026-10-05,
  broken again 2026-10-15 because T1 invented its own key comment.
- **The "tier was available" vs "access exists" conflation**: fixed 2026-10-05 (`e86a33c1`), re-lost, re-fixed
  2026-10-15 (`da382067`).

Both lived in files nobody re-read, and both were invisible because the failure looked like success.

## Known unknowns, stated rather than searched away

- `Enable-ShopSsh.ps1` (29,802 B) and `Collect-PcDiagnostics.ps1` (25,727 B) sat on the STICK with larger
  copies than the repo - **a generation that was never committed**. They are in no commit and on none of
  ZABZ-TECH, `D:\`, `_scratch`, `_worktrees`, secratary-ts, secratary-cloud or zabz-tech-linux. If they exist
  anywhere it is on a physical stick.
- One operational caution from the research: `scripts/sessions.mjs` reported five nodes `UNREACHABLE` while
  Tailscale showed them active - a bare `ssh` in a background job hangs on stdin; the `-n` wrappers work.
  **Do not read "unreachable" as fact.**
