# 97 — The three fleet repairs the 13:04Z audit found

**Program:** `docs/mesh/`. **Repairs:** `95-audit-live-mesh.md` §3.2 (the Mac cannot boot),
§4.2 (the Linux gate is fail-open), §6.3 (the laptop cannot pull).
**Date:** 2026-09-17, 13:17–13:40Z. **Author:** a delegated repair session, not the owner, not the
auditor, not the author of any `docs/mesh/8x` file.
**Owns:** this file, and the three fixes themselves on the machines concerned. Nothing under
`packages/plugin-remote-fanout/**`, `packages/plugin-mesh-http/**`, `packages/mesh-broker/**`,
`scripts/make_zabz_preset.py` or `scripts/mesh-e2e.ps1` was edited — other streams own those.

**What was NOT done.** No engine was restarted on any node: the Mac's engine is still **pid 12458**
and the Linux node's engine is still **pid 3572114**, the same processes before and after. No process
was killed. The only process restarted was the Linux node's **`phone-gate`**, which the brief named
explicitly. No history was rewritten: there is no `reset`, no `rebase`, no `--force` anywhere in the
record, and `git reflog` is quoted in §3 to prove it.

| # | repair | verdict |
|---|---|---|
| 1 | the Mac Mini's `web` profile cannot compose | **FIXED** — `--dump-config` now exits **0** (was **1**) |
| 2 | `zabz-tech-linux`'s gate signs in every tailnet device | **FIXED** — the employee's Mac now gets **403** (was **200 + a session**); all five owner paths still **200** |
| 3 | the laptop's `git pull --ff-only` is refused | **FIXED** — `Already up to date.`, exit **0** (was `fatal: Not possible to fast-forward`, exit **128**); `journal.py check` **0 errors** |

---

## 1. Repair 1 — the Mac Mini's engine could not boot

### 1.1 The found state, recorded before anything changed

Measured over ssh to `mac-mini-ts` at **2026-09-17T13:18:58Z** (`node` is not on the non-interactive
ssh `PATH`; the binary is `/Users/lpt/.local/node-v24.12.0-darwin-arm64/bin/node`, v24.12.0):

```
$ NODE=/Users/lpt/.local/node-v24.12.0-darwin-arm64/bin/node
$ $NODE /Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js --profile web --dump-config
Error: dsh: profile bundle "dsh-mesh-broker" declares no dsh.bundle in its package.json
    at loadProfileDirectory (…/dsh-app-boot/lib/index.js:852:34)
    at loadProfile  (…/dsh-app-boot/lib/index.js:894:9)
    at prepareProfile (…/dsh/lib/profile-boot-Dk-7KqJc.js:208:18)
    at runDumpConfig (…/dsh/lib/dump-config-lFgMwK8i.js:25:17)
    at runCli (…/dsh/lib/bin.js:162:4)
Node.js v24.12.0
EXIT_WEB=1
```

```
$ $NODE …/dsh/lib/bin.js --profile headless --dump-config   →  EXIT_HEADLESS=0, 348 lines
$ stat -f "%Sm %z %N" ~/.dsh/profiles/web/package.json
2026-09-17T08:48:28  551 bytes  /Users/lpt/.dsh/profiles/web/package.json
$ sha256 …/web/package.json
5ffb443c918c74ff1bb55c705c889eb247ac46a6fda86401dcba028a270d2625
$ ls -la ~/.dsh/profiles/web/node_modules/dsh-mesh-broker
lrwxr-xr-x … dsh-mesh-broker -> /Users/lpt/code/harness-config/packages/mesh-broker
$ ps -eo pid,command | grep mesh-broker          →  (no mesh-broker process on this node)
```

The manifest's bundle list, verbatim:

```
["@deepseek-ai/dsh-base","@deepseek-ai/dsh-web-app","dsh-mesh-broker","dsh-plugin-attention",
 "dsh-plugin-attention-badge","dsh-plugin-cost","dsh-plugin-health","dsh-plugin-mesh-http",
 "dsh-plugin-mobile","dsh-plugin-remote-fanout","dsh-plugin-session-link","dsh-plugin-windows"]
```

### 1.2 Which fix, and why not the other one

The brief offered two: drop the row, or give `packages/mesh-broker/package.json` a `dsh.bundle`.
**I dropped the row.** The reason is in the loader's own source, read from the machine rather than
inferred (`dsh-app-boot/lib/index.js:849-855`):

```js
const declared = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8")).dsh?.bundle?.patch;
if (declared === void 0) throw new Error(`${binName}: profile bundle … declares no dsh.bundle …`);
const patchPath = join(packageDir, declared);
… patches: loadOverlayPatches(binName, patchPath)
```

`dsh.bundle.patch` is **not a declaration of identity — it is a path to a Cordis patch layer that the
loader will mount into every booting engine.** `dsh-mesh-broker` is the broker *service*: it has a
`bin`, it is started as its own process by systemd, and it has no `cordis.patch.yml` and no host rows
to contribute. Giving it a `dsh.bundle` would have meant inventing a patch layer for a service so that
a line in one machine's bundle list would stop being meaningless — **and it would have changed the
meaning of `packages/mesh-broker` for every node in the fleet**, three of which do not name it at all.
The row-drop is the same repair `install-client-plugins.ps1` now performs automatically
(`install-client-plugins.ps1:211`, *"declares no dsh.bundle — REMOVING from the bundle list (naming it
stops the engine booting)"*), and the same one the Windows nodes received overnight
(`90-provider-mount.md` §3). It is the fleet's established pattern; the package change would have been
a new one, made for a single machine's symptom.

**The package's own `bin` still resolves** — the symlink is untouched, so anything that wants to run
the broker from this node still can. What changed is one name in one list.

### 1.3 The repair

Backup first, then drop the name with the machine's own `node` (JSON round-trip, no hand-editing):

```
$ cp -p ~/.dsh/profiles/web/package.json ~/.dsh/profiles/web/package.json.bak-repair1-20260917T131938Z
-rw-r--r-- 1 lpt staff 551 Sep 17 08:48 …/package.json.bak-repair1-20260917T131938Z
$ node -e '… filter(n => n !== "dsh-mesh-broker") …'
removed: ["dsh-mesh-broker"]
bundles after: ["@deepseek-ai/dsh-base","@deepseek-ai/dsh-web-app","dsh-plugin-attention",
 "dsh-plugin-attention-badge","dsh-plugin-cost","dsh-plugin-health","dsh-plugin-mesh-http",
 "dsh-plugin-mobile","dsh-plugin-remote-fanout","dsh-plugin-session-link","dsh-plugin-windows"]
```

### 1.4 The proof, and that nothing else moved

```
$ $NODE …/dsh/lib/bin.js --profile web --dump-config > /tmp/mac-dump-web-after.txt 2>&1
EXIT_AFTER=0
585 lines
$ grep -nE "remote-fanout|tool-subagent-remote|plugin-mesh-http" /tmp/mac-dump-web-after.txt
564:# == dsh-plugin-mesh-http
565:- id: plugin-mesh-http
571:- id: remote-fanout
572:  name: dsh-plugin-remote-fanout
573:- id: tool-subagent-remote
$ $NODE …/dsh/lib/bin.js --profile headless --dump-config      →  EXIT_HEADLESS=0
$ ps -eo pid,lstart,command | grep "bin.js"
12458 Wed Sep 16 19:44:36 2026  …/node …/dsh/lib/bin.js web --port 3099 --no-open
$ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3086/mesh/capacity      →  200
$ curl -s https://lakewooechsmini.tail93e6e6.ts.net/mesh/capacity                 →  200
```

Engine **pid 12458 is the same process**, up since 2026-09-16 19:44:36, exactly as the brief required.

### 1.5 The severity was higher than the audit stated, and here is the measurement

The audit said the node "runs exactly one engine … there is no supervision that would report it". The
engine **is** supervised, and that makes the defect worse, not better. Measured at **13:39Z**:

```
$ sudo launchctl print system/com.lakewoodphone.mesh-engine | grep -E "state|pid|runs"
	state = running
	runs = 2
	pid = 12458
$ plutil -p /Library/LaunchDaemons/com.lakewoodphone.mesh-engine.plist
  "KeepAlive" => { "SuccessfulExit" => false }
  "RunAtLoad" => true
  "Label" => "com.lakewoodphone.mesh-engine"
  "ProgramArguments" => [ … "/Users/lpt/.dsh-install/node_modules/@deepseek-ai/dsh/lib/bin.js",
                          "web", "--port", "3099", "--no-open" ]
$ launchctl list | grep lakewood
12458	0	com.lakewoodphone.mesh-engine
26384	-15	com.lakewoodphone.mesh-gate
```

`RunAtLoad` + `KeepAlive{SuccessfulExit:false}` means launchd **would have restarted this engine by
itself** — the audit thought a human had to act and that the node would simply go quiet. What actually
happens with a broken profile under that supervisor is a **crash loop**: the new engine exits non-zero
on the bundle error, launchd starts it again, forever, writing `engine-3099.err.log` each time, with
no engine ever coming up. So this was not a latent risk waiting for a reboot; it was a
**time-and-event-armed outage** whose trigger the node's own supervisor would have pulled.

*(Correction to the audit's §3.2 consequence paragraph, which says the opposite. The measurement is
the plist and `launchctl print` above.)*

**Honest limit:** I did **not** restart the engine to demonstrate the crash loop. The brief forbids it
and the plist is the stronger evidence anyway — a `--dump-config` exit 1 is deterministic, and
`KeepAlive` is a declaration launchd enforces. The crash loop is a **prediction from two measured
facts**, not something I watched happen. What I watched happen is the boot failure and, after the
repair, its absence.

---

## 2. Repair 2 — `zabz-tech-linux`'s gate was fail-open

### 2.1 The before-state, measured

```
$ systemctl show phone-gate -p MainPID -p ActiveEnterTimestamp -p ActiveState
MainPID=3575411
ActiveEnterTimestamp=Wed 2026-09-16 19:30:36 EDT
ActiveState=active
$ sha256sum /home/zabz/dsh-mesh/repo/scripts/phone-gate.py
4ec735cd0c747b86dccecbe6d0ade5822452dd80c64571e2804d2fd154b01661
$ ls -la /home/zabz/dsh-mesh/repo/scripts/phone-gate-allow.txt
ls: cannot access '…/phone-gate-allow.txt': No such file or directory
$ grep -n "ALLOW_FILE = " /home/zabz/dsh-mesh/repo/scripts/phone-gate.py
1772:ALLOW_FILE = Path(__file__).resolve().parent / "phone-gate-allow.txt"

$ curl -s -o /dev/null -w '%{http_code}' -H 'X-Forwarded-For: 100.126.146.121' \
      http://127.0.0.1:3086/mesh/capacity
200   ← 567 bytes of {"schema": 1, "node": "zabz-tech-linux", …}
$ curl -s -H 'X-Forwarded-For: 100.126.146.121' http://127.0.0.1:3086/
200   ← 54057 bytes of "<!doctype html> … window.__ModuleLoader__ …"      ← a signed-in session
$ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3086/mesh/capacity
200   ← loopback, no header

$ grep "NO DEVICE RESTRICTION" /home/zabz/.dsh-phone/gate.log | tail -1
2026-09-16T19:30:46   phone-gate: NO DEVICE RESTRICTION — /home/zabz/dsh-mesh/repo/scripts/phone-gate-allow.txt
  does not exist; every device on the tailnet will be signed in automatically. …
```

Two independent confirmations of the caller's identity in that log line and in the probe: the gate is
**reading the header** (the sign-in path logged `client=100.126.146.121 … signing in in flight … 1
cookie(s)`), it simply had nothing to compare it against. `100.126.146.121` is the employee's Mac —
absent from every allow-list in the fleet on purpose, and named as such in the file's own header.

### 2.2 The repair

The file the gate reads is *beside the running script*, so that is where it went:

```
$ printf '%s' '<base64 of the canonical scripts/phone-gate-allow.txt>' | base64 -d \
      > /home/zabz/dsh-mesh/repo/scripts/phone-gate-allow.txt
$ chmod 644 /home/zabz/dsh-mesh/repo/scripts/phone-gate-allow.txt
bytes=3051
sha256=e40d88ed58725539f2ac2b92d179a881371cebb908dd8305770c1c2c5fbe6a16
$ grep -vE '^\s*(#|$)' …/phone-gate-allow.txt
100.72.162.5      # zabz-yoga-1     the owner's laptop (home)
100.85.105.93     # iphone-15-pro   the owner's iPhone
100.85.153.96     # zabz-tech       the office desktop
100.84.72.88      # secratary       the always-on company authority
100.105.248.90    # zabz-tech-linux
```

**Provenance of that content:** the identical bytes as
`C:\Users\ezabz\code\harness-config\scripts\phone-gate-allow.txt` on ZABZ-YOGA at 13:19Z, sha256
`e40d88ed…6a16`, 3051 bytes. Transfer was verified by recomputing the hash **on the far side** — both
sides print the same digest, so the file that landed is the file that was sent. The list is the same
five devices the laptop, the desktop, the Mac and the authority carry, and the employee's machine
stays excluded.

Then **only that gate**:

```
gate pid before:   3575411
engine pid before: 3572114
$ sudo systemctl restart phone-gate
gate pid after:    3626230   (state=active)
engine pid after:  3572114   (UNCHANGED=YES)
gate restarts:     0
$ tail -3 /home/zabz/.dsh-phone/gate.log
2026-09-17T09:21:00 phone-gate starting pid=3626230 parent=1 argv=--listen-port 3086 --engine-port 3099
2026-09-17T09:21:00 phone-gate listening on 127.0.0.1:3086 -> engine 127.0.0.1:3099
2026-09-17T09:21:03   phone-gate: sign-in restricted to 5 device(s) by phone-gate-allow.txt
```

### 2.3 The proof — the same measurement the audit used, and four controls

```
PROBE A  foreign  100.126.146.121  /mesh/capacity   →  HTTP 403  640 bytes
         "<h1>This node does not sign in this device</h1><p>… came from <code>100.126.146.121</code>.</p>"
PROBE B  foreign  100.126.146.121  /                →  HTTP 403  640 bytes   ← WAS 200 + the app HTML
PROBE C  owner    100.85.105.93    /mesh/capacity   →  HTTP 200  567 bytes
PROBE C2 owner    100.85.105.93    /                →  HTTP 200              ← a real session
PROBE D  loopback no header        /mesh/capacity   →  HTTP 200
PROBE D2 loopback no header        /                →  HTTP 200
PROBE E  "100.85.105.93, 100.126.146.121"           →  HTTP 403   ← only the LAST entry counts
PROBE F  "100.84.72.88, 100.126.146.121"            →  HTTP 403   ← a forged owner prefix is not a pass
PROBE G  https://zabz-tech-linux.tail93e6e6.ts.net/mesh/capacity (real Serve path)  →  HTTP 200

$ grep REFUSED /home/zabz/.dsh-phone/gate.log | tail -2
2026-09-17T09:21:03 GET /mesh/capacity client=100.126.146.121 peer=127.0.0.1 -> REFUSED: not in
  phone-gate-allow.txt; this node signs in its owner's own devices only
2026-09-17T09:21:03 GET / client=100.126.146.121 peer=127.0.0.1 -> REFUSED: not in phone-gate-allow.txt
```

E and F matter because the header is attacker-influenced: the gate takes the **last** entry — the one
`tailscale serve` appended — so a caller cannot prefix an owner address to buy a session. That was
true of the 4cf9c268 revision already; C through G prove it is true of this node's revision too, which
is the part that was untested here.

### 2.4 Fleet-wide: every gate's revision, allow-list path — and whether the file is there

Measured 2026-09-17 **13:22–13:36Z**, each node read over its own loopback `127.0.0.1:3086`; the
revision is `sha256` of the **running** script (the executable resolved from the listener's pid), not
of a checkout copy.

| node | platform | gate pid | running gate script | sha256 | bytes | revision | allow-list path (beside the running script) | file? | foreign → | owner → | loopback → |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `zabz-yoga-1` | Windows | 19076 | `…\harness-config\scripts\phone-gate.py` | `4cf9c268…632a` | 121763 | **canonical** | `…\harness-config\scripts\phone-gate-allow.txt` | **YES** 3051 B, 5 dev | **403** | 200 | 200 |
| `zabz-tech` | Windows | 27472 | `…\harness-config\scripts\phone-gate.py` | `4cf9c268…632a` | 121763 | **canonical** | `…\harness-config\scripts\phone-gate-allow.txt` | **YES** 3051 B, 5 dev | **403** | 200 | 200 |
| `secratary` | Linux | 1905952 | `/home/zabz/harness-config/scripts/phone-gate.py` | `4cf9c268…632a` | 121763 | **canonical** | `/home/zabz/harness-config/scripts/phone-gate-allow.txt` | **YES** 3051 B, 5 dev | **403** | 200 | 200 |
| `lakewooechsmini` | Darwin | 26384 | `/Users/lpt/.dsh-gate/scripts/phone-gate.py` | `9e6a8650…9545` | 121765 | **older** | `/Users/lpt/.dsh-gate/scripts/phone-gate-allow.txt` | **YES** 3053 B, 5 dev | **403** | 200 | 200 |
| `zabz-tech-linux` | Linux | 3626230 | `/home/zabz/dsh-mesh/repo/scripts/phone-gate.py` | `4ec735cd…1661` | 105940 | **third revision** | `/home/zabz/dsh-mesh/repo/scripts/phone-gate-allow.txt` | **YES** 3051 B, 5 dev *(installed by this repair)* | **403** | 200 | 200 |

**Every gate in the fleet now refuses a foreign device. Before this repair, four did and one did not.**

Three things the table itself shows, all of them standing traps:

1. **All three revisions resolve the allow-list the same way** — `ALLOW_FILE = Path(__file__).resolve().parent / "phone-gate-allow.txt"` at line 2055 (canonical, `9e6a8650`), line 2055 (`9e6a8650`), and line 1772 (`4ec735cd`). The line number moves; the meaning does not. **A file resolved beside the running script is only as durable as the deployment that put the script there** — this is the trap that produced the hole, and it is still the mechanism on all five nodes.
2. **The Mac's allow-list is not byte-identical to the canonical one** — 3053 vs 3051 bytes, differing by one trailing blank line. Same five devices, sha256 `0c4e3e3c…b643`. Harmless, and recorded so that a future hash comparison does not raise a false alarm.
3. **`zabz-tech-linux`'s running gate is a third revision** (105,940 B, 4ec735cd) that matches neither the canonical 121,763-byte file nor the Mac's 121,765-byte one, and it is the only gate not run from a checkout directory. Nothing in the file's behaviour is broken — the probes above say so — but it shares no lineage with the file every other node runs, and the drift is invisible to `git`.

**Per-node notes.**

* `zabz-yoga-1`'s gate process is `pythonw.exe` with an unreadable command line from this session
  (`Get-CimInstance` returned an empty `CommandLine`; the audit records the same process as pid 19076
  on 127.0.0.1:3086). Its script path in the table is the canonical one the audit measured, and its
  allow-file path is confirmed by `Get-FileHash` + the live 403/200/200 probes. **That is one field
  inferred rather than read directly** — see §4.
* `secratary` and `zabz-tech-linux` each carry a **second, stale `phone-gate.py`** in
  `/home/zabz/code/harness-config/scripts/` — 40,206 bytes, sha256 `8ef819be…d942`, the same ancient
  file on both. Neither is running. Both are in a checkout whose `HEAD` is far behind; the Linux one
  had **no allow-list beside it either**, so if anyone ever pointed a unit at that path the same hole
  reappears on that node. Recorded as a trap, not fixed (that checkout is not this repair's to move).
* The Mac's gate **is** supervised — `/Library/LaunchDaemons/com.lakewoodphone.mesh-gate.plist`,
  `RunAtLoad` + `KeepAlive: true`, state `running`, pid 26384, `runs` tracked by launchd — so unlike
  its engine it comes back by itself. That is why leaving its older revision in place is safe: it is
  refusing correctly, and a broken edit would be restarted into a loop by launchd rather than fail
  quietly.

---

## 3. Repair 3 — the laptop's `git pull --ff-only`

### 3.1 The refusal, and the anatomy of it

```
$ git rev-list --left-right --count HEAD...origin/master
1	1
$ git pull --ff-only
hint: Diverging branches can't be fast-forwarded, you need to either:
hint: 	git merge --no-ff
hint: or:
hint: 	git rebase
fatal: Not possible to fast-forward, aborting.
pull_exit=128

$ git log -1 --format='%H %ad %an %s' --date=iso HEAD          → ef02d55 2026-09-17 09:07:48 -0400 Zabz
$ git log -1 --format='%H %ad %an %s' --date=iso origin/master → 595c778 2026-09-17 09:07:51 -0400 zabz68
$ git merge-base HEAD origin/master                            → 62e9469
$ git diff HEAD origin/master                                  → (empty)
$ git show --stat --oneline ef02d55 → scripts/website-comms-push.py | 173 ++++  1 file, +167 -6
$ git show --stat --oneline 595c778 → scripts/website-comms-push.py | 173 ++++  1 file, +167 -6
```

And the fact that settles it, measured rather than argued — **the two tips are the same tree object**:

```
$ git rev-parse 'HEAD^{tree}'           → 54c8e430510e0c1972074856f478b662461f2d38
$ git rev-parse 'origin/master^{tree}'  → 54c8e430510e0c1972074856f478b662461f2d38
$ git rev-parse '62e9469^{tree}'        → 3fa64aad24d641fb14eb4050b356f7ad8d3807a4
```

Two commits, three seconds apart, same author's machine twice over, **same tree as each other and a
different tree from their common ancestor**. So the change is real (`62e9469 → 54c8e430`) and the
duplication is total: neither side has content the other lacks. Confirmed the cheap way as well —
`git diff HEAD origin/master` empty, and `git diff --name-status 62e9469 HEAD` and
`… 62e9469 origin/master` both `M scripts/website-comms-push.py` and nothing else.

**This is a content-free divergence**, so *either* side's tree is correct and nothing needs resolving.
What has to be repaired is only the **graph**: two tips, one shared branch, and a `--ff-only` policy
that cannot move a branch with two tips.

### 3.2 Nothing downstream was at risk — checked before acting, not assumed

Three screens, all read-only, before any verb that changes a ref:

| screen | command | result |
|---|---|---|
| would the pull touch a file I have uncommitted work in? | intersect `git diff --name-only HEAD origin/master` with `git diff --name-only` | **empty** at the time of the first merge |
| would the pull clobber an untracked file? | every `git ls-files --others --exclude-standard` path tested against `git ls-tree -r --name-only origin/master` (3139 vs 2273 paths, set membership, not 3139 `cat-file` calls) | **NONE** |
| are the two trees identical? | `rev-parse '{HEAD,origin/master}^{tree}'` + `diff --name-status` | **identical**, `diff` empty |

The working tree carries a live uncommitted set that is **not mine** — 17 modified tracked files
(`packages/plugin-mesh-http/**`, `packages/plugin-remote-fanout/**`, `profiles/web/cordis.patch.yml`,
`presets/zabz/agent.cordis.yml`, `scripts/make_zabz_preset.py`, the journal caches) and ~3,140
untracked files including `docs/mesh/91-resident-dispatch-proof.md`. None of it was touched, staged,
committed or discarded; §3.5 proves that with the diff's own blob hash.

### 3.3 The merge, and why it happened in a throwaway worktree

The first merge ran in place:

```
$ git merge --no-edit origin/master
Merge made by the 'ort' strategy.
merge_exit=0
$ git log -1 --format='%P' HEAD
ef02d55c55307bfa381b10fd6603577a8c05cde2 595c778af68601374eef3d24a656c89b6d846f01
```

**Both commits are now parents of one commit**, which is the property the brief asked for: `--ff-only`
becomes possible because there is no longer a second tip, not because anything was thrown away.

Then the authority moved. Another stream committed `c764dee` at **09:26:25 local** while this session
was working, so the divergence reopened as `2 1`. That second merge could not run in the main tree:

```
$ git merge --no-edit origin/master
error: Your local changes to the following files would be overwritten by merge:
	scripts/lpt-recon.py
Merge with strategy ort failed.
merge_exit=2
```

**Even though the working-tree file is byte-identical to `origin/master`'s** — measured, not assumed:

```
$ git hash-object -- scripts/lpt-recon.py     → 67d2d7a4a02e7bfb15af9b45ad59346f349db328
$ git rev-parse origin/master:scripts/lpt-recon.py → 67d2d7a4a02e7bfb15af9b45ad59346f349db328
```

`ort` refuses to write over a file the working tree has modified, and staging it does not help
(`git add` the file, retry → same refusal). The correct answer is not to commit another stream's
in-flight edit, and not to stash it either: it is to **do the ref surgery where no working tree is at
stake**.

```
$ git worktree add --detach "$env:TEMP\hc-merge-97" 002e7d4
$ git -C <wt> merge --no-edit origin/master
Merge made by the 'ort' strategy.
 scripts/lpt-hub-refresh.sh |  0
 scripts/lpt-recon.py       | 19 ++++++++++++++++---
 2 files changed, 16 insertions(+), 3 deletions(-)
 mode change 100644 => 100755 scripts/lpt-hub-refresh.sh
merge_exit=0
$ git -C <wt> log -1 --format='%P' HEAD
002e7d4ba6292bb2c95e7ee2b6c021d8d6485fa4 c764dee2f5aac08b8b48bf6fb47946a99a1c00a2
$ git -C <wt> merge-base --is-ancestor origin/master HEAD ; echo $?
0                     ← the push is a fast-forward
$ git worktree remove --force <wt> ; git worktree prune ; git worktree list
C:/Users/ezabz/code/harness-config  002e7d4 [master]        ← the throwaway is gone
```

Then the shared branch, with no `--force` anywhere:

```
$ git -C <wt> push origin bfeb1fa:master
To secretary-ts:/home/zabz/harness-config.git
   c764dee..bfeb1fa  bfeb1fa -> master
push_exit=0
```

```
$ git merge --ff-only bfeb1fa
Updating 002e7d4..bfeb1fa
Fast-forward
 scripts/lpt-hub-refresh.sh |  0
 scripts/lpt-recon.py       | 19 ++++++++++++++++---
 2 files changed, 16 insertions(+), 3 deletions(-)
ff_exit=0
```

### 3.4 Why the push, when nothing asked for one

Because a merge that lives only on this laptop does not repair this laptop. The `--ff-only` refusal is
a **divergence between two refs**, and `origin/master` is the shared one; the authority gains a commit
every time another machine syncs. A local-only merge is undercut by the next one — this session watched
it happen once already (`c764dee`, 09:26:25). Making both tips ancestors of `master` **on the shared
remote** is the whole repair, it is a fast-forward, it discards nothing, and it makes every other
machine's fetch linear again.

It is also not this session's work being published: `ef02d55` was already on the authority as
`origin/diverged-ZABZ-YOGA-20260917` — pushed there by the machine that wrote it, which is precisely
why the duplicate exists. Absorbing it into `master` publishes nothing new. `bfeb1fa` is a merge whose
**tree equals `c764dee`'s tree exactly** (`bf40840d6f4c1acbe5ea62a4674361294adaeb15`), so the push
changed reachability and no file content at all.

The push touched **only** the shared branch ref. No engine, no gate, no working tree on any node was
affected by it.

### 3.5 The proof

```
$ git pull --ff-only
Already up to date.
pull_exit=0
```

```
$ git merge-base --is-ancestor ef02d55 HEAD ; echo $?   → 0    both duplicate commits are ancestors
$ git merge-base --is-ancestor 595c778 HEAD ; echo $?   → 0
$ git diff HEAD origin/master                           → (empty)
$ git rev-list --left-right --count HEAD...origin/master
0	0
```

Uncommitted work, before and after, by hash:

```
working-diff blob hash  before: 73294d02b9d7c008508fa03e2c3b8cca12ac3f19
                        after:  73294d02b9d7c008508fa03e2c3b8cca12ac3f19   ← unchanged through both merges
diff --stat             before: 17 files changed, 1760 insertions(+), 435 deletions(-)
                        after:  17 files changed, 1761 insertions(+), 435 deletions(-)
```

One file left the uncommitted set — `scripts/lpt-recon.py`, +1 insertion — and **not one byte of it was
lost**: the fast-forward adopted the merge's version, which is byte-identical to what was on disk
(verified by blob hash before the fast-forward, `67d2d7a4…` on both sides). It moved from
*uncommitted* to *in `HEAD`*, which preserves it better than it was. Untracked count 3148 → 3148.

No rewrite, from the reflog:

```
bfeb1fa HEAD@{0}: merge bfeb1fa: Fast-forward
002e7d4 HEAD@{1}: merge origin/master: updating HEAD
002e7d4 HEAD@{2}: merge origin/master: Merge made by the 'ort' strategy.
ef02d55 HEAD@{3}: commit: tools: pick up the gap-closing round's fixes
```

Two merges and two fast-forwards. **No `reset`, no `rebase`, no `checkout --force`, no `push --force`.**

The journal, on both machines that hold one:

```
laptop      $ python journal/tools/journal.py check   →  -- 0 error(s), 65 warning(s), 80 info   exit 0
authority   $ python3 journal/tools/journal.py check  →  -- 0 error(s), 65 warning(s), 80 info   exit 0
```

And the authority can move again:

```
$ ssh secratary-ts 'cd /home/zabz/harness-config && git fetch && git rev-list --left-right --count HEAD...origin/master'
0	4        ← HEAD behind 4, i.e. a pure fast-forward is available to it
   git merge-base --is-ancestor HEAD origin/master ; echo $?  → 0
   git merge-base --is-ancestor ef02d55 origin/master ; echo $? → 0
```

The authority is behind and can fast-forward, which is exactly the state `87-harness-fork.md` was
written to reach. It has not been pulled there: that checkout is another stream's writer and pulling
into it from here is not this repair's call.

---

## 4. What I could not verify

Stated as refusals, because each one is a place where a future session could otherwise mistake my
silence for a green.

| not verified | why | what would verify it |
|---|---|---|
| **the Mac's crash loop actually happening** | restarting pid 12458 is forbidden by the brief and would end the only engine on that node | the plist + `launchctl print` quoted in §1.5; or, in a maintenance window, boot an isolated `DSH_HOME` from the same bundle list and watch it exit |
| **`zabz-yoga-1`'s running gate script path, read directly** | the listener is `pythonw.exe` and this session's `Win32_Process.CommandLine` for pid 19076 came back **empty** (the audit hit the same wall and used the audit's own record) | `Get-CimInstance Win32_Process -Filter "ProcessId=19076"` from an elevated shell on that machine, or a gate restart during a window |
| **whether `zabz-tech-linux`'s 4ec735cd revision logs an allow-list reload, as the canonical one does** | its log records a refusal and the startup line, but no file-change reload was exercised | touch the allow file on that node while watching `~/.dsh-phone/gate.log` |
| **the Mac's older `9e6a8650` gate under a header-forging attempt** | it has the same `ALLOW_FILE` construction and refuses the foreign device, but revisions 4 and 3 of this file were never diffed here | `diff` the three revisions, or run probes E/F of §2.3 against the Mac |
| **the authority's checkout pulled** | it is behind 4 and fast-forwardable, but it is another stream's live writer | whoever next runs `mesh-restart-at-0700.ps1` on it, which pulls as step 3 |
| **that the Mac's profile row-drop survives its next `install-client-plugin*` run** | the Mac has no POSIX equivalent of `install-client-plugins.ps1`; only the PowerShell one performs the drop, and the POSIX `install-client-plugin.sh` adds a *named* package unconditionally (`:78-85`) — but nothing on the Mac currently invokes either with `dsh-mesh-broker` | see P-pain below |

---

## 5. What this repair found that nobody asked about

Three standing defects, each measured, none of them fixed here because each is another stream's file.
They are recorded so they are not rediscovered.

1. **`install-client-plugin.sh` (POSIX) has the pre-fix bug that `install-client-plugins.ps1` was
   repaired to remove.** Measured, read from the file: `scripts/install-client-plugin.sh:77-85` pushes
   the package's `name` into `dsh.profile.bundles` with **no `dsh.bundle.patch` test at all** — the
   exact defect `90-provider-mount.md` §3 records as having made two Windows machines unbootable. It
   takes the package directory as an argument rather than enumerating `packages/`, so it cannot arm a
   node by itself; but any macOS or Linux node that is ever installed with it gets the same class of
   fault the Windows nodes had. **This is the single highest-value follow-up from this session.**
2. **Two stale `phone-gate.py` copies (40,206 bytes, sha256 `8ef819be…d942`) sit in
   `/home/zabz/code/harness-config/scripts/` on `secratary` and on `zabz-tech-linux`**, neither
   running, neither with an allow-list beside it. That checkout's `HEAD` is far behind. Nothing points
   at them today; a unit file pointed at one of them tomorrow re-creates repair 2 exactly.
3. **The macOS engine is supervised with `KeepAlive`, and macOS gate supervision is a LaunchDaemon**
   (§1.5, §2.4). Both are good news that the audit did not know, and both change the blast radius of
   the next profile defect on that node from "the Mac goes quiet" to "the Mac crash-loops".

4. **`zabz-tech`'s engine restarted at 09:32:02 local (13:32Z) while this session was working, and
   came back without this morning's provider work.** Not done by this session — the brief forbids
   touching that engine and this session issued no restart command to any node — but it is measured,
   and it is the kind of change that should never go unrecorded:

   | | audit, 13:06Z | now, 13:50Z |
   |---|---|---|
   | engine pid | `26140` | **`24556`** |
   | started | (older) | **2026-09-17 09:32:02 local** |
   | 3099 listener owner | `26140` | `24556` |
   | `/healthz` | 200 | 401 (the cold-read answer, i.e. a fresh process) |

   and its `profiles/web/package.json` bundle list is now:

   ```
   @deepseek-ai/dsh-base, @deepseek-ai/dsh-web-app, dsh-plugin-attention,
   dsh-plugin-attention-badge, dsh-plugin-cost, dsh-plugin-mobile, dsh-plugin-windows,
   dsh-plugin-health, dsh-plugin-mesh-http
   ```

   **`dsh-plugin-remote-fanout` is absent**, and `profiles/web/cordis.patch.yml` — the deployment
   config that row needs (`90-provider-mount.md` §2) — is on disk but no longer layers onto a profile
   whose bundle list does not name the package. So the resident-engine `subagent_remote` provider
   that `90` and `91` proved is **not** mounted on that node as it restarted. What still answers is
   `/mesh/health` (200 on loopback and on the tailnet) and `--dump-config` exits **0** with the
   `dsh-mesh-broker` row absent and a `package.json.bak-20260917-003227` beside it, so this is the
   00:33Z repair state, not a new defect — and the profile can still boot, which is the property this
   repair session cares about.

   Two readings I cannot separate from here and am not going to guess between: whether `/mesh/health`
   is answered by the engine or by `phone-gate`, and whether this restart was `mesh-restart-at-0700`
   running late or something else. **The window's own records name it** — `~/.dsh/mesh/restart-0700/<stamp>/run.log`
   on that machine holds the pid, the timestamp and the gate's own refusal-or-proceed decision. That
   file is the thing to read next, and it is not this session's to write.


---

## 6. Provenance

Every command in this file was run from **ZABZ-YOGA** between **2026-09-17T13:17Z and 13:40Z** unless
marked otherwise. The ssh targets were `mac-mini-ts`, `linux-pc-ts`, `secratary-ts`, `zabz-tech-ts`,
each `-o BatchMode=yes -o ConnectTimeout`, and every HTTP call used `--noproxy '*'` because this
laptop's `.pac` proxy invents 502s.

* **Repair 1:** `mac-mini-ts` at 13:18:58Z (reproduce), 13:19:38Z (backup + drop + `--dump-config`),
  13:19:5xZ (composed rows), 13:39Z (launchd state). Files written on that machine:
  `~/.dsh/profiles/web/package.json` and its backup `…package.json.bak-repair1-20260917T131938Z`.
* **Repair 2:** `linux-pc-ts` at 13:20:28Z (before-state + three probes), 13:20:5xZ (install, hash
  verified both sides), 13:21:00Z (restart, gate only), 13:21:03Z (seven probes + log). File written:
  `/home/zabz/dsh-mesh/repo/scripts/phone-gate-allow.txt`.
  Fleet table gathered 13:22Z–13:23Z (four nodes) and 13:23Z (two Windows nodes).
* **Repair 3:** ZABZ-YOGA at 13:24Z (anatomy + three screens), 13:25:17Z (refusal recorded),
  13:25:32Z (merge in the main tree), 13:27:47Z (re-fetch after `c764dee`), 13:31:48Z (worktree merge),
  13:32:13Z (push + fast-forward), 13:33:09Z (proof + `journal.py check`). Refs moved:
  `ef02d55` → `002e7d4` → `bfeb1fa` (HEAD and `origin/master`).
* Read-only cross-checks at 13:34–13:40Z: five-node capacity, the broker's `/nodes?fresh=1`, the
  authority's journal and git state, the Mac's LaunchDaemon plists.

**Files this session created or changed, in total:** the Mac's `profiles/web/package.json` (plus its
backup), `zabz-tech-linux`'s `phone-gate-allow.txt`, three refs on the shared `harness-config.git`,
this file, and the journal entries that accompany it. **No engine was restarted; no gate other than
`phone-gate` on `zabz-tech-linux` was restarted; no process was killed; no history was rewritten.**
