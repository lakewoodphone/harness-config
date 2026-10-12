#!/usr/bin/env python3
"""transcript-archive-pull.py — one pull, every machine, run from the always-on host.

WHY THE ALWAYS-ON HOST DRIVES IT
  The rule is that a copy must always exist and that this must not depend on anybody
  remembering. A per-workstation scheduled task fails softly: when the workstation's task
  is disabled, or its Python moves, or its clock skips, the archive just stops growing and
  nothing notices. Measured 2026-10-09: `PersonalSecretary-PushVSCodeChats` on ZABZ-YOGA
  had been reporting LastTaskResult=0 — success — hourly while the Copilot archive stood
  still for 21 days. One scheduler on the machine that is always on removes that whole
  class of silence, because the pull either happens or it fails where the timer can see it.

  (ZABZ-TECH 2026-10-09 was refusing ssh entirely from its own side and its DNS was dead —
  which is exactly the kind of thing a workstation-side scheduler reports as success.)

THE PULL, PER MACHINE
  1. the authority writes a cursor of what it already holds  (--cursor-out)
  2. the cursor is copied to the machine
  3. the machine's own archive-transcripts.py packs only what is new into a tar
  4. the tar is copied back and ingested here
  5. a contact row is recorded, so "no new transcripts" is distinguishable from "dead pull"

USAGE
  transcript-archive-pull.py --machine zabz-yoga-1          # one machine
  transcript-archive-pull.py --all                          # every configured machine
  transcript-archive-pull.py --all --max-bytes 2000000000   # chunk a first backfill
  transcript-archive-pull.py --all --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(HERE, "transcript-archive-server.py")
ARCHIVE_ROOT = os.environ.get("TRANSCRIPT_ARCHIVE_ROOT", "/home/zabz/lpt-transcripts")
SPOOL = os.path.join(ARCHIVE_ROOT, "incoming")
LOG_DIR = os.path.join(ARCHIVE_ROOT, "logs")

# Client-side script locations, tried in order. harness-config is synced to every node.
CLIENT_CANDIDATES = [
    # THE AUTHORITY'S OWN PATH, and it is not `~/code/...`: this host is a root-owned server whose
    # canonical checkout is /root/code/harness-config. Measured 2026-10-11: the local machine was
    # reported as "no working (python, client) pair" because the candidate list only knew the
    # laptop and office layouts.
    "/root/code/harness-config/scripts/archive-transcripts.py",
    "~/code/harness-config/scripts/archive-transcripts.py",
    "~/harness-config/scripts/archive-transcripts.py",
    "C:/Users/ezabz/code/harness-config/scripts/archive-transcripts.py",
    "/Users/lpt/code/harness-config/scripts/archive-transcripts.py",
    "/home/zabz/code/harness-config/scripts/archive-transcripts.py",
]

# alias = the ssh alias ON THIS HOST. `local` means run the client here.
# `push: True` marks a machine that SHIPS ITS OWN ARCHIVE rather than being pulled. Measured
# 2026-10-11: a laptop that sleeps, roams networks and is sometimes shut cannot be a reliable pull
# target, and its key was refused from the authority anyway - while the PUSH direction (the one the
# estate already uses for DSH sessions) worked on its first run and shipped 5,357 files. Marking it
# here means the pull stops reporting a failure it can never fix and says why instead. The pusher is
# `scripts/archive-push-laptop.ps1` + the `PersonalSecretary-ArchivePush` task on that machine.
MACHINES = {
    "secratary":       {"alias": "local",        "os": "linux"},
    # WAS: {"alias": None, "os": "windows", "push": True}. The repo marked the laptop push-fed
    # (commit aba858d, 2026-10-11) because the pull flapped on it, and that push half IS deployed on
    # ZABZ-YOGA (`archive-push-laptop.ps1` present, task PersonalSecretary-ArchivePush LastTaskResult
    # 0). But the PULL is the path that is verifiably working right now: the 03:23 pass on
    # 2026-10-12 pulled files_new=5 from it and the archive holds its arrivals up to 03:40. Switching
    # the pull OFF is not this workstream's to do, and doing it in the same change as an exit-code
    # fix means nobody could tell which one moved the archive. So the pull stays an explicit target;
    # if it genuinely becomes unreachable the patched runner reports it honestly instead of failing
    # the unit. Revisit only with the push proven to deliver on its own.
    "zabz-yoga":       {"alias": "zabz-yoga-1",  "os": "windows"},
    "zabz-tech":       {"alias": "zabz-tech",    "os": "windows"},
    "zabz-tech-linux": {"alias": "linux-pc-ts",  "os": "linux"},
    "lakewooechsmini": {"alias": "mac-mini-ts",  "os": "mac"},
}
DEFAULT_MAX_BYTES = 2_000_000_000
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
# `-O` forces the legacy SCP protocol. Measured 2026-10-09: a Windows OpenSSH target here has no
# sftp subsystem, so plain `scp` dies with "subsystem request failed on channel 0" while `scp -O`
# moves the same file both ways. Tried first, with a plain retry behind it.
SCP_OPTS = [*SSH_OPTS, "-O"]


def norm_scp(p: str) -> str:
    """`host:path` with the path's backslashes turned into forward slashes.

    Measured 2026-10-09: `scp -O` to a Windows target is fine with `C:/Windows/Temp/x.tar` and
    fails with `protocol error: filename does not match request` on `C:\\Windows\\Temp\\x.tar` —
    the remote echoes a normalised name and the client refuses the mismatch.
    """
    if ":" in p:
        host, _, path = p.partition(":")
        return f"{host}:{path.replace(chr(92), '/')}"
    return p


def remote_size(alias: str, path: str, windows: bool, timeout: int = 60) -> int:
    """Byte size of a file on the target, or -1. Used to decide whether a transfer completed
    even though the transport never exited (see copy_from_remote)."""
    p = path.replace(chr(92), "/")
    if windows:
        cmd = f'powershell -NoProfile -Command "(Get-Item \'{p}\').Length"'
    else:
        cmd = f'stat -c %s "{p}"'
    rc, out, _ = run(["ssh", *SSH_OPTS, alias, cmd], timeout=timeout)
    for token in reversed((out or "").strip().split()):
        if token.isdigit():
            return int(token)
    return -1


def scp(src: str, dst: str, timeout: int) -> tuple[int, str, str]:
    """Prefers `-O`. When both fail, report BOTH errors — the legacy attempt's message is the
    informative one and silently returning only the fallback's made a real failure invisible.

    Remote paths are normalised to forward slashes. Measured 2026-10-09: `scp -O` to a Windows
    target is fine with `C:/Windows/Temp/x.tar` and fails with `protocol error: filename does not
    match request` on `C:\\Windows\\Temp\\x.tar` — the remote echoes a normalised name and the
    client refuses the mismatch.
    """
    src, dst = norm_scp(src), norm_scp(dst)
    rc1, out1, err1 = run(["scp", *SCP_OPTS, src, dst], timeout=timeout)
    if rc1 == 0:
        return rc1, out1, err1
    rc2, out2, err2 = run(["scp", *SSH_OPTS, src, dst], timeout=timeout)
    if rc2 == 0:
        return rc2, out2, err2
    return rc2, out2, f"scp -O failed: {err1[-400:]}\nscp (sftp) failed: {err2[-200:]}"


def run(cmd: list[str], timeout: int = 3600, input_text: str | None = None) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: {' '.join(cmd[:3])}"
    except OSError as exc:
        return 125, "", f"cannot run {cmd[0]}: {exc}"


def last_json(text: str):
    """The client prints one JSON object; tolerate noise before it (ssh banners, warnings)."""
    for start in range(len(text)):
        if text[start] != "{":
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
    return None


def probe_client_and_python(machine: str, cfg: dict, python_bin: str | None,
                            client_path: str | None) -> tuple[str, str] | None:
    """Find a working (interpreter, client) pair by RUNNING it, not by testing a path.

    A `Test-Path` probe through Windows OpenSSH + cmd + PowerShell is three quoting layers and it
    lied once already (2026-10-09: reported the client absent while `dir` showed it present). The
    client answers `--list --json` in a few seconds, so asking it to answer is both a better
    existence test and a better interpreter test — and it is the same command we are about to run.
    """
    alias = cfg["alias"]
    windows = cfg["os"] == "windows"
    pythons = [python_bin] if python_bin else (["python", "py -3"] if windows else ["python3", "python"])
    clients = [client_path] if client_path else [
        c for c in CLIENT_CANDIDATES
        if alias == "local" or not windows or c[1:3] == ":/" or c.startswith("C:")
    ]
    last_error = ""
    for py in pythons:
        for cand in clients:
            if alias == "local":
                argv = [*py.split(), os.path.expanduser(cand), "--list", "--json"]
            else:
                argv = ["ssh", *SSH_OPTS, alias, f'{py} "{cand}" --list --json']
            rc, out, err = run(argv, timeout=300)
            summary = last_json(out)
            if summary and summary.get("ok"):
                return py, os.path.expanduser(cand) if alias == "local" else cand
            # KEEP the real reason. Measured 2026-10-12 on lakewooechsmini: this probe threw
            # stderr away, so "Permission denied (publickey)" and a genuinely missing client
            # file both printed one sentence and the reader was sent to the wrong machine.
            blob = (err or out or "").strip()
            last_error = blob.splitlines()[-1].strip() if blob else f"rc={rc}, no output"
    return None, last_error


def pull_one(machine: str, cfg: dict, *, max_bytes: int, dry_run: bool,
             python_bin: str | None, client_path: str | None, timeout: int) -> dict:
    started = time.time()
    alias = cfg["alias"]
    if cfg.get("push"):
        return {"machine": machine, "alias": None, "started_at": time.time(), "ok": True,
                "skipped": "push",
                "note": "this machine SHIPS its own archive (archive-push-laptop.ps1); the pull does "
                        "not reach it by design. Nothing is wrong when this line appears."}
    is_local = alias == "local"
    result: dict = {"machine": machine, "alias": alias, "started_at": started}

    probed = probe_client_and_python(machine, cfg, python_bin, client_path)
    if not probed or not probed[0]:
        # REPORT WHAT THE PROBE ACTUALLY SAW. The old text named only two causes, one of them
        # ("the authority is not on the tailnet", owner question 445) is no longer true -
        # measured 2026-10-12 every alias resolves from the authority. What a reader needs is
        # the probe's own last error, because each one means a different thing:
        #   "Permission denied (publickey)"  -> permissions on THAT machine, not the checkout
        #   "No such file or directory"      -> stale/missing harness-config checkout there
        #   "Could not resolve hostname"     -> a network path gap (silence, not a gap)
        last_error = (probed[1] if probed else "") or "the probe produced no output"
        result.update(ok=False, error="no working (python, archive-transcripts.py) pair on "
                                      f"that machine. The probe's own last error was: "
                                      f"{last_error!r}. Read that string rather than guessing: "
                                      "a permission failure and a missing checkout are "
                                      "different faults on different machines, and a host that "
                                      "will not resolve is SILENCE, not a GAP.")
        return result
    py, client = probed
    result["client"] = client
    result["python"] = py

    if cfg["os"] == "windows":
        remote_tar = r"C:\Windows\Temp\transcript-archive.tar"
        remote_cursor = r"C:\Windows\Temp\transcript-archive-cursor.json"
        local_tar = os.path.join(SPOOL, f"{machine}.tar")
        local_cursor = os.path.join(SPOOL, f"{machine}-cursor.json")
        local_sidecar = os.path.join(SPOOL, f"{machine}.manifest.json")
        remote_sidecar = remote_tar + ".manifest.json"
        q = f'"{client}"'
        cursor_q = f'"{remote_cursor}"'
        tar_q = f'"{remote_tar}"'
        side_q = f'"{remote_sidecar}"'
    else:
        remote_base = f"/tmp/transcript-archive-{machine.replace('/', '_')}"
        remote_tar = remote_base + ".tar"
        remote_cursor = remote_base + "-cursor.json"
        remote_sidecar = remote_tar + ".manifest.json"
        local_tar = os.path.join(SPOOL, f"{machine}.tar")
        local_cursor = os.path.join(SPOOL, f"{machine}-cursor.json")
        local_sidecar = os.path.join(SPOOL, f"{machine}.manifest.json")
        q, cursor_q, tar_q, side_q = client, remote_cursor, remote_tar, remote_sidecar
        makedirs = None

    os.makedirs(SPOOL, exist_ok=True)
    if is_local:
        # Nothing to copy: write straight into the spool and read the cursor where it already is.
        remote_tar, remote_sidecar, remote_cursor = local_tar, local_sidecar, local_cursor

    def copy_to_remote(local_path: str, remote_path: str) -> tuple[int, str, str]:
        if is_local:
            import shutil
            try:
                shutil.copyfile(local_path, remote_path)
                return 0, "copied", ""
            except OSError as exc:
                return 1, "", str(exc)
        return scp(local_path, f"{alias}:{remote_path}", 600)

    def copy_from_remote(remote_path: str, local_path: str) -> tuple[int, str, str]:
        """Copy down, then VERIFY THE BYTES rather than trusting the exit code.

        Measured 2026-10-09 on secratary -> ZABZ-YOGA: `scp -O` moved a 384 MB tar correctly
        (764 members, valid) and then **never exited** — it was still running at 900 s. That is the
        same pathology push-dsh-sessions.mjs already documents ("ssh does not reliably exit after
        the remote command completes, seen on both workstations") and it solves it by killing the
        child the moment its reply parses. The equivalent here: bound the transfer, then compare
        the local byte count against the remote's. Equal and non-empty means it arrived, whatever
        the transport says about itself.
        """
        if is_local:
            import shutil
            try:
                shutil.copyfile(remote_path, local_path)
                return 0, "copied", ""
            except OSError as exc:
                return 1, "", str(exc)
        if os.path.exists(local_path):
            os.remove(local_path)
        want = remote_size(alias, remote_path, cfg["os"] == "windows")

        # Poll the destination and END THE TRANSFER AS SOON AS THE BYTES ARE THERE, instead of
        # waiting for a process that never returns. `scp -O` does not exit on this fleet once a
        # transfer completes (measured 2026-10-09: still running 900 s after a complete 384 MB
        # copy). Waiting out that timeout costs the full wall-clock on every round, and with tens
        # of gigabytes to backfill that is the difference between an afternoon and a week. The
        # arrived file IS the reply — the same rule push-dsh-sessions.mjs applies to ssh.
        if want > 0:
            src_s, dst_s = f"{alias}:{remote_path}", local_path
            proc = subprocess.Popen(["scp", *SCP_OPTS, norm_scp(src_s), dst_s],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.time() + timeout
            got = 0
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                got = os.path.getsize(local_path) if os.path.exists(local_path) else 0
                if got >= want:
                    break
                time.sleep(1.0)
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=30)
                except Exception:
                    pass
            got = os.path.getsize(local_path) if os.path.exists(local_path) else 0
            if got == want:
                return 0, "", (f"{got} bytes verified; the transfer was ended by the poller "
                               f"because scp does not exit reliably on this fleet")
            if got == 0 and os.path.exists(local_path):
                os.remove(local_path)
            if got:
                return 1, "", f"[verify] remote={want} local={got} after {timeout}s"
            # the polled attempt moved nothing: fall back to the plain path so a wrong guess about
            # the destination cannot lose the round
        rc, out, err = scp(f"{alias}:{remote_path}", local_path, timeout)
        if rc == 0:
            return rc, out, err
        got = os.path.getsize(local_path) if os.path.exists(local_path) else 0
        if want > 0 and got == want:
            return 0, "", (f"transfer of {got} bytes completed; the transport never exited and was "
                           f"ended by its timeout — bytes verified against the remote size")
        return rc, out, (err + f"\n[verify] remote={want} local={got}")[-800:]

    def run_remote(cmd: str, argv: list[str]) -> tuple[int, str, str]:
        if is_local:
            return run(argv, timeout=timeout)
        return run(["ssh", *SSH_OPTS, alias, cmd], timeout=timeout)

    # 1. what does the archive already hold for this machine?
    gen = run([sys.executable, SERVER_SCRIPT, "--cursor-out", local_cursor, "--machine", machine])
    if gen[0] != 0:
        result.update(ok=False, error=f"cursor generation failed: {gen[2][:300]}")
        return result

    if dry_run:
        result.update(ok=True, dry_run=True, note="cursor generated; nothing copied")
        return result

    # 2. hand the cursor to the machine (locally it is already in place, and it IS the same path)
    if not is_local:
        rc, out, err = copy_to_remote(local_cursor, remote_cursor)
        if rc != 0:
            result.update(ok=False, error=f"cursor copy failed: {(err or out)[:300]}")
            return result

    # 3. the machine packs only what is new
    client_argv = [*py.split(), client, "--machine", machine, "--held", remote_cursor,
                   "--out", remote_tar, "--sidecar", remote_sidecar,
                   "--max-bytes", str(max_bytes), "--json"]
    remote_cmd = (f'{py} {q} --machine {machine} --held {cursor_q} --out {tar_q} '
                  f'--sidecar {side_q} --max-bytes {max_bytes} --json')
    rc, out, err = run_remote(remote_cmd, client_argv)
    summary = last_json(out)
    if summary is None:
        result.update(ok=False, error=f"client produced no summary (rc={rc}): "
                                      f"{(err or out)[-500:]}")
        return result
    result["client_summary"] = {k: v for k, v in summary.items() if k != "redacted_files"}
    result["refused_credential_stores"] = summary.get("refused_credential_stores") or []
    result["redacted_files"] = summary.get("redacted_files") or []

    # 4. bring it back and ingest it
    if summary.get("members_written"):
        if is_local:
            rc, out, err = 0, "", ""          # already written into the spool
        else:
            rc, out, err = copy_from_remote(remote_tar, local_tar)
        if rc != 0:
            result.update(ok=False, error=f"tar copy failed: {(err or out)[:300]}")
            return result
        if not is_local:
            rc, out, err = copy_from_remote(remote_sidecar, local_sidecar)
        sidecar_arg = ["--sidecar", local_sidecar] if os.path.exists(local_sidecar) else []
        run_id = f"{machine}-{int(started)}"
        ing = run([sys.executable, SERVER_SCRIPT, "--tar", local_tar, "--machine", machine,
                   "--run-id", run_id, *sidecar_arg], timeout=timeout)
        ingested = last_json(ing[1])
        result["ingest"] = ingested
        result["ingest_rc"] = ing[0]
        if ingested is None:
            result.update(ok=False, error=f"ingest produced no summary: {(ing[2] or ing[1])[-400:]}")
            return result
    else:
        result["ingest"] = {"members": 0, "new_objects": 0, "note": "nothing new to send"}

    # 5. contact row: "nothing new" must be distinguishable from "no pull happened"
    contact = {
        "files_seen": summary.get("files_seen"),
        "files_new": summary.get("members_written"),
        "newest_source_mtime": summary.get("newest_source_mtime"),
        "new_bytes": summary.get("new_bytes"),
        "note": "truncated; more to pull" if summary.get("truncated") else None,
    }
    run([sys.executable, SERVER_SCRIPT, "--machine", machine, "--run-id", f"{machine}-{int(started)}",
         "--contact", json.dumps(contact)])

    result.update(ok=True, elapsed_s=round(time.time() - started, 1), contact=contact)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull every machine's transcripts into the archive.")
    ap.add_argument("--machine", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--python", dest="python_bin", default=None)
    ap.add_argument("--client-path", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    targets = args.machine or (list(MACHINES) if args.all else ["secratary"])
    unknown = [m for m in targets if m not in MACHINES]
    if unknown:
        print(json.dumps({"ok": False, "error": f"unknown machine(s): {unknown}",
                          "known": list(MACHINES)}))
        return 2

    results = []
    for machine in targets:
        try:
            results.append(pull_one(machine, MACHINES[machine], max_bytes=args.max_bytes,
                                    dry_run=args.dry_run, python_bin=args.python_bin,
                                    client_path=args.client_path, timeout=args.timeout))
        except Exception as exc:                     # one machine must never stop the others
            results.append({"machine": machine, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    failed = [r["machine"] for r in results if not r.get("ok")]
    print(json.dumps({"ok": not failed, "pulled": results, "failed": failed}, indent=1, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
