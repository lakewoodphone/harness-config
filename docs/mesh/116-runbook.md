# 116 — Mesh runbook: add a node, verify the mesh, recover from the ways it breaks

Written 2026-09-18 from the repairs actually performed that day. Every procedure here was executed at least
once; the ones that were not are marked `NOT YET DONE`.

---

## 1. Add a node — the full checklist

This is the sequence that added the fifth node, with the step that cost two days marked.

1. **Reach it.** `ssh -T -o BatchMode=yes -o ConnectTimeout=25 <alias> hostname` and confirm the hostname
   is the machine you meant. An alias that lands somewhere else has happened in this repo's history.
2. **Find a runtime — and do not conclude from a blank.** `node -v` printing nothing is a statement about
   *sshd's non-interactive PATH*, not about the machine. Check the absolute locations before writing
   "no runtime": `/usr/local/bin/node`, `/opt/homebrew/bin/node`, `~/.local/node-*/bin/node`. Measured
   case: a macOS node had **two** working runtimes while `node -v` printed nothing.
3. **Find the gate — and probe the URL the roster actually uses.** Fetch
   `https://<node>.tail93e6e6.ts.net/mesh/capacity`. **`http://` and `https://` are different machines to a
   probe**, and testing port 80 is what excluded the fifth node for two days (`http://` → curl exit 7,
   `https://` → HTTP 200 with a valid body, the whole time).
4. **Run a real turn, not a version check.** `--version` proves the binary exists; a headless turn proves
   the machine can host work:
   `/usr/local/bin/node <dsh>/lib/bin.js --profile headless "Reply with exactly: OK"` → exit 0.
5. **Measure its unit cost** with `scripts/mesh/Start-AgentFleet.ps1` at K ∈ {0,2,4,6}. Until this exists,
   placing work there is arithmetic in another machine's units.
6. **Add a dispatcher row** in `packages/plugin-remote-fanout/lib/nodes.js`: `ssh` alias, `hosts`
   allow-list, `shell`, and **the credential source** — a POSIX interpreter row must name a file or record
   `!none` / `!self-store`, and the test suite enforces it. A row with no credential declaration now fails
   `npm test` the moment the node claims v1 work.
7. **Add a broker roster row** in `packages/mesh-broker/nodes.json`: `node` **must equal**
   `fqdn.split('.')[0]` (the loader refuses the roster otherwise), plus `baseUrl`, `dispatch.v1` with its
   measurement, and `note`. Omit `location` rather than guess it — `lib/config.js` maps an unrecognised
   value to `null`, and a guess silently disables the preference bonus.
8. **Deploy the roster.**
   `git push` → on the authority: `cd ~/harness-config && git fetch origin` →
   **`git show origin/master:packages/mesh-broker/nodes.json > /tmp/n.json`** → validate it parses →
   `cp` to `/home/zabz/mesh-broker/nodes.json` → update `PROVENANCE.md`'s hash →
   `sudo -n systemctl restart mesh-broker.service`.
   **Do not `git merge` the authority's clone** — it is divergent and has its own unpushed work.
   `git show ref:path` touches no working tree and cannot conflict.
9. **Verify from the running service, not the file**: `curl -sS http://127.0.0.1:3091/nodes` and count.

---

## 2. Verify the mesh is healthy

```powershell
# who does the broker think exists?
ssh secratary-ts "curl -sS -m 8 http://127.0.0.1:3091/nodes"
# does a dispatch go where it is told and prove it?
node scripts\mesh\Start-AgentFleet.ps1 -Node desktop-ts -Count 1 -Tag verify
```

What a **healthy** dispatch looks like, verbatim, and all five parts matter:

```
placement      = broker → node "zabz-tech", position 0 (tier fits) … lease … — started immediately
pressure       = OK … under no pressure: committed 76.6 % of physical, below the 85 % line;
                 prefer-remote is ON and needed no exclusion - the broker named "zabz-tech", not this machine
transport host = ZABZ-TECH  (recorded by the target shell before the agent started)
location check = matched the node the broker named (zabz-tech)
exit = 0 in 5785 ms (ssh client terminated after the completion frame)
```

- `transport host` is written **by the target before the agent starts** — it is the part of the proof a
  model cannot author. **A `MESH-HOST:` line without a matching transport block is not proof of placement**
  (journal: a child once opened with a fabricated `MESH-HOST: ZABZER` before running anything).
- Absent `location check` means the node was not verified against the broker's choice.
- `lease … COULD NOT be released` is reported but not fatal: the broker reclaims at its TTL.

---

## 3. Recover

### The engine is dead or wedged (port 3099)
```powershell
pwsh -NoProfile -File multi-window\dshw.ps1 status    # is anything listening?
pwsh -NoProfile -File multi-window\dshw.ps1 up        # start it; windows are NOT reopened
```
For a **config reload** use the verified sequence — stop, up, then poll HTTP on 3099 and fall back to
`ensure`. **`dshw restart` also reopens every declared window**, which on a shared-profile machine means
opening the full declared set; use `stop` + `up` when you only want the config reloaded.
`_scratch/engine-reload.ps1` does this and logs the outcome, **but it hangs after `up`** because the
engine's stdout keeps its pipeline open — kill the orphan and delete its scheduled task afterwards. That
bug is unfixed.

### The new-window control does nothing
Check `dshw status`. If every slot shows `windows 1` with the same memory figure, one browser tree is being
counted once per slot — the shared-profile fallback in `Get-WindowCount` (`P`/`L1996`). The control runs
under `-WindowStyle Hidden`, so a failure is silent by construction: **always test via `dshw new` and read
`windows.log`, never by clicking.**

### A child died mid-turn
Record what the diagnostic said before doing anything else. The three seen on 2026-09-18: the remote turn
cap (`300000 ms` — **fixed**, now 1800 s), a transport timeout (`ConnectTimeout` — **raised to 25 s**), and a
piped-stdout hang (**never pipe ssh** — `Start-Process -RedirectStandardOutput`). A child that produced *no*
output at all died in transport. Then: **the workstream returns to the queue; keep the branch if it has
commits.**

### The journal disagrees across machines
`journal.py check` first — exit non-zero is a real error. A cross-branch id collision is **invisible to
`repair-ids`** (it inspects the working tree, where an id still means one thing) and is only found by
attempting a merge. Repair by **re-filing the local entries through `journal.py append`** and taking
origin's version at the contested paths — **never by hand**: three invariants (LF, heading position, a
self-hash) are enforced by `check` and maintained only by the writer. Then `git push`.

---

## 4. Daily, cheap

| check | command | healthy |
|---|---|---|
| authority swap | `ssh secratary-ts "grep SwapFree /proc/meminfo"` | **it is not** — 712 kB free of 4 GiB; the number to watch |
| broker alive | `ssh secratary-ts "systemctl is-active mesh-broker"` | `active` |
| broker roster | `curl -sS http://127.0.0.1:3091/nodes` | five nodes |
| engine | `dshw status` | one window open, engine pid present |
| journal | `journal.py check` | exit 0 |
| job balance | `job_list` | no node carrying more than ~2 of your children (`P332`) |

## 5. What is missing, so nobody re-derives it

- **No per-node child cap.** Five children on one node pushed its sshd handshake to 8,041 ms and cost a
  child its turn. Until that is fixed, spread a fan-out deliberately — **two per node** is what has worked.
- **No unforgeable placement nonce.** A patch is in flight; until it lands, weigh `transport host` more
  heavily than `MESH-HOST`.
- **`secratary`'s swap is unexplained.** It is the authority's binding constraint and the reason not to
  co-locate anything large with `secretary-api`.
- **The responsiveness question is still open** — the first probe returned a null because its children were
  sleeping. `NOT YET DONE`: a CPU-active probe at higher N.
- **No costed hardware plan yet** — and until the responsiveness question is settled, any recommendation to
  the owner should say so rather than imply that buying something fixes a measurement nobody has taken.
