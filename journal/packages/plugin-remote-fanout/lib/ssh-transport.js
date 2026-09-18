/**
 * The ssh transport: run one script on ANOTHER node and bring back its stdout,
 * stderr and exit code — with a bound on time and on retained bytes.
 *
 * WHY SSH AND NOT AN HTTP ROUTE
 * `docs/mesh/66-dsh-remote-capability.md` ranks a plugin-owned HTTP route on the
 * target first, and it is right in general. It is not available for this proof:
 * a route exists only once the plugin is mounted in the target's *engine*, and
 * mounting a bundle into a running engine needs a restart (measured — see
 * `docs/dsh-at-scale/90-plugin-health-governor.md` §0). The constraint here is
 * that no engine anywhere restarts, so the one transport that works today with
 * no new code, no new auth and no restart is `ssh` + a fresh `--profile
 * headless` process. `/api/session/prompt` remains unusable for a different
 * reason the same document names: the launch token is minted per process and
 * never persisted, so a cookie cannot be kept valid across a restart.
 *
 * The child is NOT a script. The command this transport runs is `node
 * <dsh>/lib/bin.js --profile <profile> "<prompt>"` — the same one-shot DSH
 * entry point whose toolbelt is the full `dsh-base` agent plane (bash/pwsh, fs,
 * search, jobs, web). What comes back is a real agent turn's final message.
 *
 * WHY STDOUT GOES TO A FILE AND NOT A PIPE (measured, 2026-09-17)
 * On Windows, `ssh.exe` does not exit when its stdout is a PIPE: the remote
 * command runs, its output is delivered, and the client then hangs forever
 * waiting on something that never arrives. Measured on ZABZ-TECH against
 * ZABZ-YOGA, `ssh laptop-ts hostname`, 20 s bound:
 *
 *   stdio ['ignore'|'pipe'|'inherit', 'pipe', 'pipe'] → output "zabz-yoga"
 *       arrived, client STILL ALIVE at 20 s (killed) — three variants, all hang
 *   stdio ['ignore', <file fd>, 'pipe']              → exit 0 in 1075 ms
 *   stdio ['ignore', <file fd>, <file fd>]           → exit 0 in 1049 ms
 *
 * This is why every earlier probe in this program that redirected to files
 * "worked" while the same command from PowerShell `&` or from `spawn` with
 * `pipe` hung: it is the stdout handle type, not the command. The transport
 * therefore redirects BOTH streams to temp files (a shape that also works on
 * POSIX) and reads them after the client exits, and it unlinks them in a
 * finally. Without this the parent's delegation would sit until its own timeout
 * and report a timeout for work that had actually succeeded.
 */

import { spawn } from 'node:child_process';
import { closeSync, openSync, readFileSync, rmSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';

/** Maximum time a remote one-shot may take before the ssh client is killed. */
export const DEFAULT_TIMEOUT_MS = 900_000;
/** Maximum bytes retained from each remote stream. */
export const DEFAULT_MAX_OUTPUT_BYTES = 200_000;

/** Encode a PowerShell program for `-EncodedCommand` (base64 of UTF-16LE). */
export function encodePwshCommand(script) {
  return Buffer.from(script, 'utf16le').toString('base64');
}

/**
 * The argv ssh receives after the target: either an encoded PowerShell program
 * (nothing left for cmd.exe or PowerShell to re-parse) or `sh -s` with the
 * program on stdin.
 */
export function remoteArgv(shell, script) {
  if (shell === 'posix') return ['sh', '-s'];
  return ['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encodePwshCommand(script)];
}

/** Kill a process tree, best effort, on the platform we are on. */
function killTree(child) {
  if (!child || child.killed || child.exitCode !== null) return;
  try {
    if (process.platform === 'win32') {
      const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
      killer.unref?.();
    }
  } catch {
    // fall through to the direct kill below
  }
  try {
    child.kill('SIGKILL');
  } catch {
    // already gone
  }
}

/**
 * Build the transport for one target node.
 *
 * @param config.sshExe         the ssh client (default `ssh`, resolved on PATH)
 * @param config.sshArgs        extra argv before the target (e.g. `-i <key>`, `-o BatchMode=yes`)
 * @param config.target         the ssh destination, e.g. `laptop-ts` or `ezabz@100.72.162.5`
 * @param config.timeoutMs      bound on one remote turn
 * @param config.maxOutputBytes bound on retained stdout/stderr
 */
export function createSshTransport(config = {}) {
  const sshExe = config.sshExe || 'ssh';
  const sshArgs = Array.isArray(config.sshArgs) ? config.sshArgs.map(String) : [];
  const target = config.target;
  if (typeof target !== 'string' || target.trim() === '') {
    throw new Error('remote-fanout: transport `target` is required — the ssh destination of the worker node (e.g. laptop-ts)');
  }

  return {
    kind: 'ssh',
    describe() {
      return `${sshExe} ${[...sshArgs, target].join(' ')}`.trim();
    },

    /**
     * Start one remote run. Returns immediately with a handle so the caller can
     * cancel it; `done` settles exactly once, and the temp stream files are
     * always removed.
     *
     * `completeMarker`, when supplied, is the prefix of the remote script's last
     * line. When that line appears in the captured stdout the run is finished —
     * the transport settles immediately and kills the client, instead of waiting
     * for a Windows ssh client that may not exit on its own (see the module
     * header). The caller's frame nonce makes the marker unforgeable by the
     * child's own output.
     *
     * @returns {{done: Promise<object>, kill: (reason?: string) => void}}
     */
    start({ shell = 'powershell', script, timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS, maxOutputBytes = config.maxOutputBytes ?? DEFAULT_MAX_OUTPUT_BYTES, completeMarker } = {}) {
      const argv = [...sshArgs, target, ...remoteArgv(shell, script)];
      const startedAt = Date.now();
      const tag = randomBytes(6).toString('hex');
      const outPath = path.join(os.tmpdir(), `fanout-${tag}.out`);
      const errPath = path.join(os.tmpdir(), `fanout-${tag}.err`);

      let settled = false;
      let timer;
      let poll;
      let killed;
      let markerSettled = false;
      let child;
      let outFd;
      let errFd;
      let finish;
      const done = new Promise((resolve) => {
        finish = resolve;
      });

      const cleanupFiles = () => {
        for (const fd of [outFd, errFd]) {
          if (fd === undefined) continue;
          try { closeSync(fd); } catch { /* already closed */ }
        }
        outFd = undefined;
        errFd = undefined;
      };

      const readCapped = (file) => {
        try {
          const text = readFileSync(file, 'utf8');
          return text.length > maxOutputBytes
            ? { text: text.slice(0, maxOutputBytes), truncated: true }
            : { text, truncated: false };
        } catch {
          return { text: '', truncated: false };
        }
      };

      const settle = (extra) => {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        if (poll) clearInterval(poll);
        cleanupFiles();
        const out = readCapped(outPath);
        const err = readCapped(errPath);
        for (const file of [outPath, errPath]) {
          try { rmSync(file, { force: true }); } catch { /* temp dir cleanup will get it */ }
        }
        finish({
          ok: extra.ok,
          exitCode: extra.exitCode,
          signal: extra.signal,
          spawnError: extra.spawnError,
          timedOut: extra.timedOut === true,
          killed,
          markerSettled,
          ms: Date.now() - startedAt,
          stdout: out.text,
          stderr: err.text,
          truncated: out.truncated || err.truncated,
          argv,
        });
      };

      try {
        outFd = openSync(outPath, 'w');
        errFd = openSync(errPath, 'w');
        child = spawn(sshExe, argv, {
          // stdin: 'ignore' for PowerShell (`-EncodedCommand` needs no stdin) and
          // a pipe for POSIX, where the script itself is delivered on stdin.
          // stdout/stderr: files, never pipes — see the module header.
          stdio: [shell === 'posix' ? 'pipe' : 'ignore', outFd, errFd],
          windowsHide: true,
        });
      } catch (error) {
        cleanupFiles();
        return {
          done: Promise.resolve({ ok: false, spawnError: String(error?.message ?? error), ms: Date.now() - startedAt, stdout: '', stderr: '', truncated: false }),
          kill() {},
        };
      }

      child.on('error', (error) => settle({ ok: false, spawnError: String(error?.message ?? error) }));
      child.on('close', (code, signal) => settle({
        ok: code === 0,
        exitCode: code === null ? undefined : code,
        signal: signal ?? undefined,
        timedOut: killed === 'timeout',
      }));

      if (shell === 'posix' && child.stdin) {
        child.stdin.on('error', () => {});
        child.stdin.end(script);
      }

      const bound = Number.isFinite(timeoutMs) && timeoutMs > 0 ? timeoutMs : DEFAULT_TIMEOUT_MS;
      timer = setTimeout(() => {
        killed = 'timeout';
        killTree(child);
      }, bound);
      timer.unref?.();

      // Settle on the frame, not on the client's exit. See the module header:
      // a Windows ssh client can hold the session open long after the work is
      // done, and the work is done exactly when the closing marker is written.
      if (typeof completeMarker === 'string' && completeMarker.length > 0) {
        let lastSize = -1;
        let stable = 0;
        poll = setInterval(() => {
          if (settled) return;
          let text;
          try {
            text = readFileSync(outPath, 'utf8');
          } catch {
            return;
          }
          const line = text.split(/\r?\n/).find((candidate) => candidate.startsWith(completeMarker));
          if (line === undefined) {
            lastSize = text.length;
            stable = 0;
            return;
          }
          if (text.length === lastSize) stable += 1;
          else {
            lastSize = text.length;
            stable = 0;
          }
          if (stable < 2) return; // two quiet polls: the script has stopped writing
          const parsed = Number.parseInt(line.slice(completeMarker.length).trim(), 10);
          markerSettled = true;
          killed = killed ?? 'frame-complete';
          killTree(child);
          settle({
            ok: parsed === 0,
            exitCode: Number.isFinite(parsed) ? parsed : undefined,
            timedOut: false,
          });
        }, 200);
        poll.unref?.();
      }

      return {
        done,
        kill(reason = 'aborted') {
          if (settled) return;
          killed = killed ?? reason;
          killTree(child);
        },
      };
    },
  };
}
