# ESTATE — every DSH engine, measured, and what its update costs

Measured 2026-10-20. This page exists because two rounds of this work reported "the estate" while only some of it
had been looked at: `zabz-tech-linux` timed out from ZABZ-YOGA and was left unmeasured, and the phone engine on
`secratary-cloud` was not in the picture at all until it was found by looking. **A machine you did not check is not
a machine that is up to date.**

| host | what it is | engine | how it runs | state |
|---|---|---|---|---|
| **ZABZ-TECH** | office desktop, primary | **0.2.1-rc.2** | `~/.dsh/engine`, launcher `dshInstall`, pid on 3099 | **updated** 2026-10-19; config corrected; patches applied/superseded; receipt `state/install-receipts/0.2.1-rc.2-20261019T223705Z.json` |
| **ZABZ-YOGA** | laptop | 0.2.0-rc.2 | `~/.dsh/engine`, launcher probe | staged: pin bootstrapped, candidate fetched and verified, staged home with anchors + roster, **preflight GO on 8/8**, verified backup. One stop-window from done (`dsh-update/tools/switch-yoga.ps1 -Execute`) |
| **secratary-cloud → phone** | the owner's phone assistant | 0.2.0-rc.2 | `phone-engine.service`, `/opt/dsh-phone`, port 3089, node22 | attempted 2026-10-20, **rolled back safely** (engine exited 2: two copies of `dsh-scope`). Candidate at `/opt/dsh-phone.failed-20261020T002419Z`. Needs the profile anchor rebuilt at 0.2.1 **with the service stopped** |
| **zabz-tech-linux** | office Linux worker + vault | **0.1.5-rc.1** | `/home/zabz/dsh-engine`, node at `/home/zabz/.local/node/bin/node`, web on 3099; no systemd user unit found | **not started.** Home `/home/zabz/.dsh` with `headless` + `web` profiles; profile patches name ZERO coupled packages (so it is NOT on the rename seam in the config layer); `~/code/harness-config` present; **no dsh-update pin** (the pipeline has never run there) |
| **lakewooechsmini** | Yisroel's macOS mini | unknown | unknown | **unreachable**: publickey denied from ZABZ-YOGA and from `secratary-cloud`, as `ezabz` and as root. Tailscale shows it active. Until someone with the mac's key measures it, its version is NOT VERIFIED |
| **secratary** | the office box | — | frozen rollback anchor (`host-posture.tsv`) | **never touch** |

## What each remaining update costs, in the order I would take them

1. **ZABZ-YOGA — ~4 minutes.** Everything is staged; `switch-yoga.ps1` stops every engine, corrects the live
   patch, regenerates the preset rows and the settings document, installs, starts one engine, verifies. It cannot
   run from inside the session that machine serves.
2. **secratary-cloud phone — ~8 minutes.** With `phone-engine` stopped: `pnpm install` in `/root/.dsh/profiles/web`
   against the 0.2.1 engine root (the profile carries `pnpm-workspace.yaml`), prove by composing with the candidate
   binary, swap `/opt/dsh-phone` by rename, start, verify version + HTTP + a real turn, roll back on any failure.
   `scripts/switch-phone-engine.sh` already does everything except the pnpm rebuild.
3. **zabz-tech-linux — half a day, and it is the only one that crosses the rename seam.** It is on the 0.1.5 line,
   where `dsh-agent-presets` and `dsh-workflow-worker-thread` exist and their 0.1.7+ replacements do not. That is
   the case `switch-engine.ps1` was written for: engine and coupled config as ONE operation, with the staged home
   proven first. Its config layer currently names neither, which makes it *simpler* than ZABZ-TECH was, but the
   engine binary and its own `.agent-presets` still have to move together. It does not even have a pin, so step one
   is `bootstrap-pin.cjs` there.
4. **lakewooechsmini — unmeasured.** Nothing can be said about it until a key works.

## How to measure one, without touching it

```bash
# the engine version a host actually runs
ls -d ~/.dsh/engine ~/dsh-engine /opt/dsh-phone 2>/dev/null
python3 -c "import json,sys;print(json.load(open('<root>/node_modules/@deepseek-ai/dsh/package.json'))['version'])"
# what it is running right now
pgrep -af 'dsh.*bin.js'
# is it on the rename seam?
grep -c 'dsh-agent-presets\|dsh-workflow-worker-thread' ~/.dsh/profiles/*/cordis.patch.yml ~/.dsh/.agent-presets/*/agent.cordis.yml
```

## Readiness of the two hosts that are not done (measured 2026-10-20)

**zabz-tech-linux** — node v22.23.2, npm 10.9.8, credentials present, 11 GB RAM (3 free + 7 cache). Two things
must be fixed BEFORE any update there:
- **disk is at 99 % — 9.2 GB free on `/`.** A fetch (453 MB) plus a staged copy (~500 MB) plus a verified backup
  (~0.5-1 GB) fits, but this estate has broken itself twice by writing into a nearly-full disk (P3929, P8396), so
  free space first or point the backup elsewhere.
- **its harness-config checkout is at `985f9378` and does NOT contain `dsh-update/tools/install-engine.mjs`.** Its
  tools predate tonight's work, so step zero is bringing that checkout up to the branch that has them.
`vendor/prefix` is empty (nothing ever fetched) and there is no pin, so the pipeline has never run on it.

**lakewooechsmini** — nothing measured. `publickey` denied from two hosts under two users while Tailscale reports it
active. Someone with that mac's key has to run the four commands above.

## The rule this page exists to enforce

The estate is not "the machines I happened to touch". It is: ZABZ-TECH, ZABZ-YOGA, secratary-cloud's phone engine,
zabz-tech-linux, lakewooechsmini — and `secratary`, which is frozen and is never counted as work. **Report a
version per host, with the command that read it, or say NOT VERIFIED.**
