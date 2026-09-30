/**
 * The pure half of the remote transport: build the script that runs on the
 * TARGET node, and parse the bytes that come back.
 *
 * No I/O, no timers, one static import (`./nodes.js`, which is a pure table and a
 * pure resolver) — so this module is unit-testable on its own and the transport
 * module holds nothing but process handling.
 *
 * WHY THE INVOCATION IS A DECISION AND NOT TWO PATHS
 * `node <bin.js>` is not "how you run a worker"; it is one of two ways, and the
 * other way is the one the machine provisioned. Measured 2026-09-17: the
 * `zabz-tech-linux` node completes a real child turn through its own `dsh`
 * executor (`LINUX NODE OK`, exit 0, 3 s) and dies with `MISSING_CREDENTIAL:
 * llm-deepseek` through an explicit interpreter pair, because the wrapper is the
 * only thing that sources the worker's credential file. So the script is built
 * from a RESOLVED INVOCATION (`invocationFor`), and the credential travels with
 * it as an explicit file to source. See `nodes.js` for the full measurement and
 * `docs/mesh/102-linux-dispatch.md` for the table.
 *
 * WHY A FRAME
 * The remote script's stdout carries three kinds of line: a transport-level
 * fact recorded by the *target shell* (which machine actually ran this), the
 * DSH child's own final answer, and the child's exit code. A shell that starts
 * a nested PowerShell can also print a banner, so the answer is fenced between
 * two markers carrying a per-run nonce rather than "everything after line N".
 * The nonce means a child that prints the marker word itself cannot forge or
 * truncate the frame.
 */

import { normalizeNodeFacts, resolveNodeInvocation as defaultResolveNodeInvocation } from './nodes.js';

/** A marker namespace: `FANOUT_<suffix>_<nonce>`. */
export function markers(nonce = '') {
  const tail = nonce ? `_${nonce}` : '';
  return {
    host: `FANOUT_TRANSPORT_HOST${tail}=`,
    cwd: `FANOUT_TRANSPORT_CWD${tail}=`,
    begin: `FANOUT_BEGIN${tail}`,
    end: `FANOUT_END${tail}`,
    exit: `FANOUT_EXIT${tail}=`,
  };
}

/** Quote one value as a literal PowerShell single-quoted string. */
export function psQuote(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

/** Quote one value as a literal POSIX shell single-quoted word. */
export function shQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

/**
 * Quote for the POSIX program we generate: a name, flag or absolute path is
 * emitted bare, anything else is quoted. An executor is invoked BY NAME
 * (`dsh --profile …`) for the reason in `nodes.js` — the name is the machine's
 * own contract and it is what makes the credential file get sourced — while a
 * path keeps the quoting it needs for spaces and Windows drive colons.
 */
export function shellWord(value) {
  const text = String(value ?? '');
  return /^[A-Za-z0-9_./@:=+-]+$/.test(text) ? text : shQuote(text);
}

/**
 * The TASK is ALWAYS quoted, whatever it contains. It is the one argument whose
 * text comes from a model, and a word that happens to be shell-safe today must
 * not become a bare word because of how it read this time.
 */
function taskWord(text) {
  return shQuote(text ?? '');
}

/**
 * HOW TO INVOKE A WORKER — ONE decision, and it lives here so the script
 * builder and the provider cannot disagree about it.
 *
 * PREFERENCE, IN ORDER:
 *   1. an EXECUTOR (`command`): `dsh --profile headless <task>`. The executor is
 *      the machine's own launcher — it resolves the interpreter and SOURCES THE
 *      CREDENTIAL FILE, which is the half of the 2026-09-17 defect that did not
 *      show up as a missing path. See `nodes.js` for the measurements.
 *   2. an INTERPRETER pair (`driver` + `bin`) with a declared credential env
 *      file, sourced by this script before it runs — a POSIX node provisioned
 *      with an explicit root-owned env file and no executor.
 *   3. an INTERPRETER pair alone — the Windows case, where the credential comes
 *      from the dispatching process's own environment.
 *
 * A spec may still carry the pre-2026-09-17 `nodeExe`/`dshBin` field names; that
 * shape is read, never produced, so a caller that has not moved cannot silently
 * lose its invocation.
 *
 * @param {{invocation?:object, command?:string, driver?:string, nodeExe?:string,
 *          bin?:string, dshBin?:string, credentialEnvFiles?:string[], shell?:string}} spec
 */
export function invocationFor(spec = {}, { resolveNodeInvocation } = {}) {
  if (spec.invocation !== undefined && spec.invocation !== null) return spec.invocation;
  const resolver = resolveNodeInvocation ?? defaultResolveNodeInvocation;
  const resolved = resolver(spec);
  if (resolved !== undefined) return resolved;
  // NO HALF-PAIR, EVER. `{ nodeExe }` with no `bin.js`, or a `bin.js` with no
  // interpreter, is not an invocation and never resolves to one — that is the
  // config shape that produced `node …: not found` on the target.
  const facts = normalizeNodeFacts(spec);
  const complete = typeof facts?.driver === 'string' && facts.driver !== ''
    && typeof facts.bin === 'string' && facts.bin !== '';
  return complete
    ? {
      form: 'interpreter',
      command: facts.driver,
      argvPrefix: [facts.bin],
      driver: facts.driver,
      bin: facts.bin,
      credentialEnvFiles: [],
      credentialSource: 'the interpreter inherits its credential from the dispatching process environment',
    }
    : undefined;
}

/** Build a `-EncodedCommand` program out of argv-style parts, quoting each word. */
function psCommandLine(parts) {
  return parts.map((part) => psQuote(part)).join(' ');
}

/**
 * Should a run whose output this is be retried with the invocation's fallback?
 *
 * YES only for the two shapes that mean "this invocation could not be launched":
 * the client failed to spawn, or the command was not found on the target
 * (`sh: 6: …: not found` / `command not found`, exit 127). Everything else —
 * a wrong model answer, a credential error, a timeout — is the child's own
 * outcome and must never be silently re-run.
 *
 * WHY A RETRY EXISTS AT ALL: the interpreter path is a fallback, and a fallback
 * that is never exercised is a fallback that is never checked. The executor is
 * preferred because it is right, not because a missing one is fatal.
 */
export function shouldRetryWithFallback(outcome, parsed) {
  if (outcome === undefined || outcome === null) return false;
  if (typeof outcome.spawnError === 'string' && outcome.spawnError !== '') return true;
  if (outcome.timedOut === true || outcome.killed === 'aborted' || outcome.killed === 'disposed') return false;
  if (outcome.exitCode !== 127) return false;
  if (parsed !== undefined && parsed !== null && parsed.framed === true) return false;
  const stderr = String(outcome.stderr ?? '');
  return /(^|\s|\/|:)not found\b|\bcommand not found\b|cannot find module\b|MODULE_NOT_FOUND/.test(stderr);
}

/**
 * The task travels as ONE command-line argument, so a newline in it would be
 * harmless inside a quoted string but is collapsed anyway: `dsh-headless` reads
 * its task from argv and every remote quoting layer is simpler with one line.
 */
export function singleLine(text) {
  return String(text ?? '').replace(/\r/g, ' ').replace(/\n/g, ' ').replace(/\s+/g, ' ').trim();
}

/**
 * Build the invocation for one spec, or throw naming the missing half. A caller
 * that has neither an executor nor a complete interpreter pair cannot dispatch,
 * and finding that out at script-build time is cheaper than a 127 from a node.
 */
function requiredInvocation(spec) {
  const invocation = invocationFor(spec);
  if (invocation === undefined) {
    throw new Error('remote-fanout: no invocation for this node — it needs either an executor (`command`, e.g. the mesh `dsh` wrapper) or both a `driver` and a `bin` (the interpreter fallback)');
  }
  return invocation;
}

/**
 * The PowerShell program the target runs, delivered with `-EncodedCommand`
 * (base64 UTF-16LE) so no layer ever re-parses the task text.
 *
 * @param spec.invocation RESOLVED invocation (`invocationFor`) — an executor command, or a driver+bin pair
 * @param spec.command    shorthand: an executor on PATH, used when `invocation` is absent
 * @param spec.driver     shorthand: the target's node interpreter (also read as the legacy `nodeExe`)
 * @param spec.bin        shorthand: the target's `@deepseek-ai/dsh/lib/bin.js` (also read as the legacy `dshBin`)
 * @param spec.profile    the DSH profile to boot on the target (default `headless`)
 * @param spec.task       the child's prompt
 * @param spec.dshHome    optional DSH_HOME for the child process (isolation)
 * @param spec.cwd        optional working directory for the child
 * @param spec.nonce      frame nonce
 * @param spec.progressFile optional target-side progress log: when supplied, a
 *                          `FANOUT_PROGRESS:START` line, the child's own
 *                          stdout/stderr, and a `FANOUT_PROGRESS:EXIT` line are
 *                          appended to it (so a parent can tell a silent child
 *                          from a working one and can salvage progress after a
 *                          transport fault). The framed stdout contract is
 *                          byte-identical when it is not supplied.
 */
export function buildPwshScript({ invocation, profile, task, dshHome, cwd, nonce = '', progressFile, ...rest }) {
  const m = markers(nonce);
  const resolved = requiredInvocation({ invocation, ...rest });
  const profileWord = profile ?? 'headless';
  const argv = [resolved.command, ...(resolved.argvPrefix ?? []), '--profile', profileWord, singleLine(task)];
  const lines = [
    '# generated by dsh-plugin-remote-fanout — one remote one-shot subagent turn',
    `# invocation form: ${resolved.form} — ${resolved.credentialSource}`,
    "$ErrorActionPreference = 'Continue'",
    "$ProgressPreference = 'SilentlyContinue'",
  ];
  if (dshHome) lines.push(`$env:DSH_HOME = ${psQuote(dshHome)}`);
  if (cwd) lines.push(`Set-Location -LiteralPath ${psQuote(cwd)}`);
  if (progressFile) {
    // PROBE, THEN TEE. The start line doubles as the writability probe: if the
    // log cannot be written the run continues unteed rather than failing. The
    // append is the only thing that may fail and it is wrapped.
    lines.push(
      `$fanoutProgress = ${psQuote(progressFile)}`,
      '$fanoutProgressOk = $false',
      'try {',
      `  Add-Content -LiteralPath $fanoutProgress -Value ("FANOUT_PROGRESS:START host=" + $env:COMPUTERNAME + " pid=" + $PID + " at=" + [DateTime]::UtcNow.ToString('o')) -ErrorAction Stop`,
      '  $fanoutProgressOk = $true',
      '} catch { }',
    );
  }
  lines.push(
    `[Console]::Out.WriteLine(${psQuote(m.host)} + $env:COMPUTERNAME)`,
    `[Console]::Out.WriteLine(${psQuote(m.cwd)} + (Get-Location).Path)`,
    `[Console]::Out.WriteLine(${psQuote(m.begin)})`,
  );
  if (progressFile) {
    // stdout is tee'd to the log and still flows to the frame; stderr is
    // appended to the log. (PowerShell has no portable stderr tee that keeps
    // the error stream intact, so progress carries stderr rather than
    // duplicating it — the child's stderr is still recorded, in the log.)
    lines.push(
      'if ($fanoutProgressOk) {',
      `  & ${psCommandLine(argv)} 2>> $fanoutProgress | Tee-Object -FilePath $fanoutProgress -Append`,
      '} else {',
      `  & ${psCommandLine(argv)}`,
      '}',
      '$fanoutExit = $LASTEXITCODE',
      'if ($fanoutProgressOk) {',
      `  try { Add-Content -LiteralPath $fanoutProgress -Value ("FANOUT_PROGRESS:EXIT code=" + $fanoutExit + " at=" + [DateTime]::UtcNow.ToString('o')) -ErrorAction Stop } catch { }`,
      '}',
    );
  } else {
    lines.push(
      `& ${psCommandLine(argv)}`,
      '$fanoutExit = $LASTEXITCODE',
    );
  }
  lines.push(
    `[Console]::Out.WriteLine(${psQuote(m.end)})`,
    `[Console]::Out.WriteLine(${psQuote(m.exit)} + $fanoutExit)`,
    // `[Environment]::Exit` rather than `exit`: PowerShell's own exit path waits
    // on teardown after a native child has run, and on Windows that wait can
    // outlive the work (measured 2026-09-17: the frame closes, the answer is
    // written, and the ssh session stays open until the client's own timeout).
    // The transport settles on the frame, so this is belt and braces.
    '[Environment]::Exit($fanoutExit)',
  );
  return lines.join('\n');
}

/**
 * The POSIX twin, for a Linux/macOS worker node. Delivered on stdin to `sh -s`
 * so the task text never reaches an argument-parsing layer either.
 *
 * THE CREDENTIAL IS THE POINT OF THIS FUNCTION. When the resolved invocation
 * names a credential env file (a node with an explicit root-owned worker env and
 * no executor), the script sources it with `set -a` FIRST, so the child process
 * inherits it — reproducing what the wrapper would have done. When the executor
 * form is used, the executor does that itself and this script adds nothing.
 *
 * THE PROGRESS LOG IS OPT-IN (`progressFile`). When supplied, a start line, the
 * child's own stdout AND stderr (each tee'd, so both keep flowing to their real
 * destination), and an exit line are appended to it. The fd dance that tees
 * stderr is `{ { child 2>&1 1>&3; printf '%s' "$?" > exitfile; } | tee -a log >&2; } 3>&1`:
 * fd 3 holds the frame's stdout, so the child's stdout reaches the outer tee
 * (log + frame) while its stderr reaches the inner tee (log + stderr) without
 * either stream crossing into the other. The framed stdout is BYTE-IDENTICAL
 * when `progressFile` is omitted.
 */
export function buildPosixScript({ invocation, profile, task, dshHome, cwd, nonce = '', progressFile, ...spec }) {
  const m = markers(nonce);
  const resolved = requiredInvocation({ invocation, ...spec });
  const profileWord = profile ?? 'headless';
  const childCommand = [
    ...[resolved.command, ...(resolved.argvPrefix ?? [])].map(shellWord),
    '--profile',
    shellWord(profileWord),
    taskWord(singleLine(task)),
  ].join(' ');
  const lines = [
    '# generated by dsh-plugin-remote-fanout — one remote one-shot subagent turn',
    `# invocation form: ${resolved.form} — ${resolved.credentialSource}`,
  ];
  // ONLY THE INTERPRETER FORM SOURCES THE FILE ITSELF. The executor form is the
  // wrapper, and the wrapper sources it already — sourcing it twice would be one
  // credential path too many (and the wrapper's own resolution must stay the
  // authority on where the file is).
  const envFile = resolved.form === 'interpreter' ? (resolved.credentialEnvFiles ?? [])[0] : undefined;
  if (envFile !== undefined) {
    lines.push(
      `# source what the executor would have sourced, and export it — POSIX ONLY,`,
      `# and only when this row's node makes that file readable to the worker user.`,
      `# (The generated program deliberately does NOT \`set -e\`: a failed \`cd\` must`,
      `# not skip the closing frame, because a missing frame is what turns a`,
      `# readable failure into a mystery.)`,
      `if [ -r ${shQuote(envFile)} ]; then set -a; . ${shQuote(envFile)}; set +a; fi`,
    );
  }
  if (dshHome) lines.push(`export DSH_HOME=${shQuote(dshHome)}`);
  if (cwd) lines.push(`cd ${shQuote(cwd)}`);
  lines.push(
    `printf -v fanout_host '%s' "$(hostname)"`,
    `printf '%s\\n' "${m.host}$fanout_host"`,
    `printf '%s\\n' "${m.cwd}$(pwd)"`,
    `printf '%s\\n' "${m.begin}"`,
  );
  if (progressFile) {
    // PROBE, THEN TEE. The start line doubles as the writability probe: if the
    // log cannot be written, the run continues unteed rather than failing.
    lines.push(
      `# progress log (opt-in): the parent can read it while the child runs.`,
      `fanout_progress=${shQuote(progressFile)}`,
      `if { printf '%s\\n' "FANOUT_PROGRESS:START host=$(hostname) pid=$$ at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$fanout_progress"; } 2>/dev/null; then`,
      `  fanout_exitfile="\${TMPDIR:-/tmp}/fanout-exit-$$"`,
      `  { { ${childCommand} 2>&1 1>&3; printf '%s' "$?" > "$fanout_exitfile"; } | tee -a "$fanout_progress" >&2; } 3>&1 | tee -a "$fanout_progress"`,
      `  fanout_exit=$(cat "$fanout_exitfile" 2>/dev/null || echo 1)`,
      `  rm -f "$fanout_exitfile"`,
      `  { printf '%s\\n' "FANOUT_PROGRESS:EXIT code=$fanout_exit at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$fanout_progress"; } 2>/dev/null || true`,
      `else`,
      `  ${childCommand}`,
      `  fanout_exit=$?`,
      `fi`,
    );
  } else {
    lines.push(childCommand, 'fanout_exit=$?');
  }
  lines.push(
    `printf '%s\\n' "${m.end}"`,
    `printf '%s\\n' "${m.exit}$fanout_exit"`,
    'exit $fanout_exit',
  );
  return lines.join('\n');
}

/**
 * Read the framed result out of the remote stdout.
 *
 * `answer` is the child's own final assistant message, exactly as
 * `dsh --profile headless` prints it. `host` and `cwd` are facts recorded by
 * the TARGET's shell before the child ran — they are the transport's own
 * evidence of where the turn happened, independent of anything the model wrote.
 */
export function parseFanout(stdout, nonce = '') {
  const m = markers(nonce);
  const text = String(stdout ?? '');
  const lines = text.split(/\r?\n/);
  let host;
  let cwd;
  let exitCode;
  let beginAt = -1;
  let endAt = -1;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim();
    if (line.startsWith(m.host)) host = line.slice(m.host.length).trim();
    else if (line.startsWith(m.cwd)) cwd = line.slice(m.cwd.length).trim();
    else if (line === m.begin) beginAt = i;
    else if (line === m.end && beginAt >= 0) endAt = i;
    else if (line.startsWith(m.exit)) {
      const parsed = Number.parseInt(line.slice(m.exit.length).trim(), 10);
      if (Number.isFinite(parsed)) exitCode = parsed;
    }
  }
  const framed = beginAt >= 0 && endAt > beginAt;
  return {
    host,
    cwd,
    exitCode,
    framed,
    answer: framed ? lines.slice(beginAt + 1, endAt).join('\n').trim() : '',
  };
}

// ---------------------------------------------------------------------------
// PROGRESS — what a run was doing while it ran.
//
// F5: between start and settle nothing is known about the child, so a silent
// child and a working child look identical and a run that dies mid-flight
// leaves nothing to salvage. The remote program (opt-in, `progressFile`)
// appends a START line, the child's own stdout/stderr, and an EXIT line to a
// target-side log. `parseProgress` turns that text back into the facts and the
// child's own lines, so the parent can tell "working" from "silent" and can
// salvage the child's output after any transport fault.
// ---------------------------------------------------------------------------

const PROGRESS_PREFIX = 'FANOUT_PROGRESS:';

/** Pull `key=value` tokens out of a control line (values are space-free). */
function progressTokens(text) {
  const tokens = {};
  const re = /([A-Za-z_][A-Za-z0-9_]*)=(\S*)/g;
  let match;
  while ((match = re.exec(text)) !== null) tokens[match[1]] = match[2];
  return tokens;
}

/**
 * Parse a target-side progress log.
 *
 * @returns {{startedAt: (string|undefined), host: (string|undefined),
 *            pid: (number|string|undefined), lines: string[],
 *            lastAt: (string|undefined), exit: (number|string|undefined)}}
 *   `lines` is the child's OWN output (both streams, in arrival order) with the
 *   control lines removed. `parseProgress` never throws, even on a log that was
 *   cut off mid-write.
 */
export function parseProgress(text) {
  const result = { startedAt: undefined, host: undefined, pid: undefined, lines: [], lastAt: undefined, exit: undefined };
  try {
    for (const raw of String(text ?? '').split(/\r?\n/)) {
      const line = raw.replace(/\r$/, '');
      if (line.startsWith(`${PROGRESS_PREFIX}START`)) {
        const tokens = progressTokens(line.slice(`${PROGRESS_PREFIX}START`.length));
        if (tokens.host !== undefined) result.host = tokens.host;
        if (tokens.pid !== undefined) {
          const pid = Number.parseInt(tokens.pid, 10);
          result.pid = Number.isFinite(pid) ? pid : tokens.pid;
        }
        if (tokens.at !== undefined) {
          result.startedAt = tokens.at;
          result.lastAt = tokens.at;
        }
      } else if (line.startsWith(`${PROGRESS_PREFIX}EXIT`)) {
        const tokens = progressTokens(line.slice(`${PROGRESS_PREFIX}EXIT`.length));
        if (tokens.code !== undefined) {
          const code = Number.parseInt(tokens.code, 10);
          result.exit = Number.isFinite(code) ? code : tokens.code;
        }
        if (tokens.at !== undefined) result.lastAt = tokens.at;
      } else if (line.startsWith(PROGRESS_PREFIX)) {
        // A control line this parser does not know: never the child's output.
      } else if (line !== '') {
        result.lines.push(line);
      }
    }
  } catch {
    // A progress log that cannot be parsed is not worth failing a run over.
  }
  return result;
}

// ---------------------------------------------------------------------------
// HARVEST — the salvage half of a failed run.
//
// F1/F2 (the incident record): a child exits 4294967295 (== -1) with no final
// message and sometimes no stderr, or ssh dies at 255 after a half-written
// report, and the parent learns nothing. The bytes are usually still on disk —
// in the framed answer, in stdout, or in stderr — but nothing turns them into
// something a person can read. `harvestOutput` is that turn: a BOUNDED,
// human-readable salvage assembled from whatever survived, plus a `parts` array
// so a caller can tell what came from where and a `complete` flag that is true
// only when the child's own frame closed.
//
// It is pure and total: no I/O, and it never throws. Buffers with invalid UTF-8
// boundaries become replacement characters rather than exceptions, and every
// field may be undefined.
// ---------------------------------------------------------------------------

/** A byte limit that can never make the harvest throw. */
function harvestLimit(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : fallback;
}

/** Coerce anything to a string without throwing, decoding buffers as UTF-8. */
function safeText(value) {
  if (value === undefined || value === null) return '';
  if (typeof value === 'string') return value;
  if (Buffer.isBuffer(value)) return value.toString('utf8');
  if (value instanceof Uint8Array) return Buffer.from(value).toString('utf8');
  try {
    return String(value);
  } catch {
    return '';
  }
}

/** The last `maxBytes` UTF-8 bytes of a value, decoded leniently. */
function tailBytes(value, maxBytes) {
  const limit = harvestLimit(maxBytes, 0);
  if (limit <= 0) return { text: '', truncated: false, bytes: 0 };
  let buffer;
  if (Buffer.isBuffer(value)) buffer = value;
  else if (value instanceof Uint8Array) buffer = Buffer.from(value);
  else buffer = Buffer.from(safeText(value), 'utf8');
  if (buffer.length <= limit) return { text: buffer.toString('utf8'), truncated: false, bytes: buffer.length };
  return { text: buffer.subarray(buffer.length - limit).toString('utf8'), truncated: true, bytes: buffer.length };
}

/** The one-line outcome summary that is always present, even for an empty run. */
function outcomeSummary(outcome) {
  const o = outcome ?? {};
  const exit = o.exitCode === undefined || o.exitCode === null ? 'none' : safeText(o.exitCode);
  const signal = o.signal === undefined || o.signal === null || o.signal === '' ? 'none' : safeText(o.signal);
  const timedOut = o.timedOut === true ? 'true' : 'false';
  const ms = Number.isFinite(o.ms) ? String(o.ms) : 'unknown';
  const spawn = o.spawnError ? ` spawnError=${safeText(o.spawnError)}` : '';
  return `outcome: exit=${exit}, signal=${signal}, timedOut=${timedOut}, ms=${ms}${spawn}`;
}

/**
 * Salvage a bounded, human-readable result from whatever a run left behind.
 *
 * @param {object} outcome the transport's settle record (exitCode, signal, timedOut, ms, stdout, stderr, …)
 * @param {object} parsed  the output of `parseFanout` (framed, answer, host, cwd, exitCode)
 * @param {{maxBytes?: number}} [options] per-section byte bound (default 12000)
 * @returns {{text: string, complete: boolean, parts: Array<{source: string, text: string, truncated: boolean, bytes: number}>}}
 */
export function harvestOutput(outcome, parsed, options = {}) {
  const parts = [];
  try {
    const { maxBytes = 12000 } = options ?? {};
    const limit = harvestLimit(maxBytes, 12000);
    const framed = parsed?.framed === true;

    const answerText = framed ? safeText(parsed?.answer) : '';
    if (answerText !== '') {
      const answer = tailBytes(answerText, limit);
      parts.push({ source: 'answer', text: answer.text, truncated: answer.truncated, bytes: answer.bytes });
    }
    const stdout = tailBytes(outcome?.stdout, limit);
    if (stdout.text !== '') {
      parts.push({ source: 'stdout-tail', text: stdout.text, truncated: stdout.truncated, bytes: stdout.bytes });
    }
    const stderr = tailBytes(outcome?.stderr, limit);
    if (stderr.text !== '') {
      parts.push({ source: 'stderr-tail', text: stderr.text, truncated: stderr.truncated, bytes: stderr.bytes });
    }
    const summary = outcomeSummary(outcome);
    parts.push({ source: 'outcome', text: summary, truncated: false, bytes: summary.length });

    const headers = {
      answer: '--- child answer (from the closed frame) ---',
      'stdout-tail': '--- raw stdout tail ---',
      'stderr-tail': '--- raw stderr tail ---',
      outcome: '---',
    };
    const blocks = parts.map((part) => (part.source === 'outcome'
      ? `${headers.outcome} ${part.text} ---`
      : `${headers[part.source]}\n${part.text}`));
    if (parts.length === 1) blocks.unshift('no output was recovered from this run.');

    return {
      text: blocks.join('\n\n'),
      complete: framed,
      parts,
    };
  } catch (error) {
    // A salvage function that throws on the very input it exists to describe is
    // worse than useless, so the failure itself becomes the salvage.
    const fallback = `harvest failed: ${safeText(error?.message ?? error)}; ${outcomeSummary(outcome)}`;
    return {
      text: fallback,
      complete: parsed?.framed === true,
      parts: [{ source: 'harvest-error', text: fallback, truncated: false, bytes: fallback.length }],
    };
  }
}
