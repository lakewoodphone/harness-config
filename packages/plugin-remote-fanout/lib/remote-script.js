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
 * THE TASK BYTE CEILING, AND WHY IT EXISTS AT ALL (D4, lesson L3060 is NOT the
 * cause — a double quote never killed a run; the ARGV LENGTH did).
 *
 * MEASURED on ZABZ-TECH: a 12000-character task produced an ssh argv of 33859,
 * because the whole program was base64'd into `-EncodedCommand` (~2.67 argv
 * characters per task character) on top of the fixed prefix. `spawn` failed with
 * ENAMETOOLONG and the child never started. The real ceiling was ~11400
 * characters of task, and the fleet's 8-part brief standard routinely exceeds it.
 *
 * THE FIX IS DELIVERY, NOT TRUNCATION: the generated program now travels on the
 * target's STDIN (`ssh <target> sh -s` / `ssh <target> powershell -Command -`),
 * so argv is constant and no longer grows with the task. This ceiling is the
 * backstop for the encoded fallback and for an absurd payload; when it trips the
 * builder REFUSES, naming the size and the limit. It never cuts a brief.
 */
export const MAX_TASK_BYTES = 2 * 1024 * 1024;

/** UTF-8 byte length of a task, the number the ceiling is measured in. */
export function taskBytes(text) {
  return Buffer.byteLength(String(text ?? ''), 'utf8');
}

/** Throw — legibly — when a task cannot be delivered whole. Never truncates. */
export function assertTaskSize(task, { maxBytes = MAX_TASK_BYTES } = {}) {
  const bytes = taskBytes(task);
  if (bytes <= maxBytes) return bytes;
  throw new Error(
    `remote-fanout: the task is too large for the transport — ${bytes} bytes encoded, `
    + `the documented limit is ${maxBytes} bytes (MAX_TASK_BYTES); nothing was truncated and no child was started. `
    + 'Split the brief, or write it to a file on the target and have the child read it by path.',
  );
}

/**
 * The per-child MAILBOX PATHS ON THE TARGET (R3/R5/R6).
 *
 * The parent must not guess another machine's home. When the placement names a
 * `dshHome`, the paths are exact absolute paths in that node's own shape; when it
 * does not, the path stays a POSIX/PowerShell expression (`$HOME/.dsh`,
 * `$env:USERPROFILE\.dsh`) that the TARGET shell expands — so the child, and
 * `mesh_message`/`mesh_collect` over ssh, resolve the same directory the child's
 * own engine uses.
 */
export function meshChildPaths({ dshHome, id, shell = 'posix' } = {}) {
  const win = shell === 'powershell';
  const sep = win ? '\\' : '/';
  const configured = typeof dshHome === 'string' && dshHome.trim() !== '' ? dshHome.trim().replace(/[\\/]+$/, '') : undefined;
  const home = configured === undefined
    ? (win ? '$env:USERPROFILE\\.dsh' : '$HOME/.dsh')
    : configured;
  const dir = [home, 'mesh', 'children', String(id ?? 'child')].join(sep);
  return { dir, inbox: `${dir}${sep}inbox.jsonl`, outbox: `${dir}${sep}outbox.jsonl` };
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
 * Retained for the callers that predate the stdin delivery. The TASK is no
 * longer passed through it: flattening a brief to one line was half of the D4
 * delivery defect (the other half was argv size), so the builders now carry the
 * task verbatim.
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
 */
export function buildPwshScript({ invocation, profile, task, dshHome, cwd, nonce = '', ...rest }) {
  const m = markers(nonce);
  const resolved = requiredInvocation({ invocation, ...rest });
  const profileWord = profile ?? 'headless';
  assertTaskSize(task ?? '');
  // THE TASK KEEPS ITS NEWLINES. `psQuote` makes it one PowerShell string
  // literal, so a multi-line brief is still ONE argv word to the child while no
  // layer has to re-parse it; flattening was never required, only convenient.
  const argv = [resolved.command, ...(resolved.argvPrefix ?? []), '--profile', profileWord, String(task ?? '')];
  const lines = [
    '# generated by dsh-plugin-remote-fanout — one remote one-shot subagent turn',
    `# invocation form: ${resolved.form} — ${resolved.credentialSource}`,
    "$ErrorActionPreference = 'Continue'",
    "$ProgressPreference = 'SilentlyContinue'",
  ];
  if (dshHome) lines.push(`$env:DSH_HOME = ${psQuote(dshHome)}`);
  if (cwd) lines.push(`Set-Location -LiteralPath ${psQuote(cwd)}`);
  lines.push(
    `[Console]::Out.WriteLine(${psQuote(m.host)} + $env:COMPUTERNAME)`,
    `[Console]::Out.WriteLine(${psQuote(m.cwd)} + (Get-Location).Path)`,
    `[Console]::Out.WriteLine(${psQuote(m.begin)})`,
    `& ${psCommandLine(argv)}`,
    '$fanoutExit = $LASTEXITCODE',
    `[Console]::Out.WriteLine(${psQuote(m.end)})`,
    `[Console]::Out.WriteLine(${psQuote(m.exit)} + $fanoutExit)`,
    // `[Environment]::Exit` rather than `exit`: PowerShell's own exit path waits
    // on teardown after a native child has run, and on Windows that wait can
    // outlive the work (measured 2026-09-17: the frame closes, the answer is
    // written, and the ssh session stays open until the client's own timeout).
    // The transport settles on the frame, so this is belt and braces.
    '[Environment]::Exit($fanoutExit)',
  );
  return wrapPwshProgram(lines.join('\n'));
}

/**
 * DELIVER THE PROGRAM AS ONE LINE, WITH THE REAL PROGRAM INSIDE IT.
 *
 * MEASURED 2026-10-05 on ZABZ-YOGA → ZABZ-TECH, through this transport's own
 * code path (`createSshTransport` + this builder), one variable at a time:
 *
 *   task `Reply with exactly: TECH_OK`                 (1 line)  → framed, answer OK
 *   task `Line one.\nReply with exactly: TWOLINE_OK`   (2 lines) → NO frame, exit 0, 1.0 s
 *   8-line brief, 130 chars                                       → NO frame, exit 0, 1.7 s
 *   1242 chars in 3 lines                                         → NO frame, exit 0, 1.2 s
 *   1232 chars in ONE line, 2019-byte program                     → framed, answer OK
 *
 * So the trigger is a NEWLINE ANYWHERE IN THE TASK, not its size: the transport
 * delivers the program on the target's STDIN (`ssh <node> powershell -Command -`,
 * the D4 fix that removed the argv ceiling), PowerShell reads that program
 * LAZILY — statement by statement — and the moment the child is launched it
 * inherits the same pipe with the REST OF THE PROGRAM still unread in it. The
 * child's own stdio users (DSH starts its MCP servers over stdin, and the target
 * logged `mcp_launcher.py firecrawl/jina` on every run) then swallow those
 * remaining lines. PowerShell reaches EOF, prints no closing frame, never sets
 * `$fanoutExit`, and the client exits 0 — which is exactly the field report:
 * *"the remote process exited 0 but printed no completion frame — the target
 * profile did not run"*, with `FANOUT_TRANSPORT_HOST/CWD/BEGIN` and nothing
 * after. It is why every real brief failed and every one-line probe passed
 * (pains P2826, P2835; handoff H3188).
 *
 * THE FIX KEEPS STDIN DELIVERY AND REMOVES THE HAZARD. The launcher is a SINGLE
 * line, so PowerShell must read it to its end before executing anything and
 * nothing is left in the pipe for the child to consume. The real program travels
 * inside it as base64 — no newline of the program and no character of the task
 * ever reaches a parser, so the task can also no longer be re-quoted, re-split or
 * truncated by any shell between here and the child.
 *
 * The alternative measured in the same session — `-EncodedCommand` (argv) — also
 * framed correctly, but it puts the program back into the Windows command line
 * and caps the task near 11 KB, which is the ceiling D4 removed. This shape has
 * no ceiling on stdin and no parse surface at all.
 */
export function wrapPwshProgram(program) {
  const payload = Buffer.from(String(program ?? ''), 'utf16le').toString('base64');
  return "$ErrorActionPreference = 'Continue'; try { Invoke-Expression ([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('"
    + payload
    + "'))) } catch { [Console]::Error.WriteLine('dsh-plugin-remote-fanout: the remote program could not be decoded or started: ' + $_.Exception.Message); [Environment]::Exit(91) }";
}

/**
 * The inverse of `wrapPwshProgram`, for tests, for reading a captured script by
 * eye, and for anything that has to inspect what the target will actually run.
 * Throws when the input is not a wrapped program — a silent empty string here
 * would hide the very defect the wrapper exists to fix.
 */
export function unwrapPwshProgram(launcher) {
  const match = /FromBase64String\('([A-Za-z0-9+/=]*)'\)/.exec(String(launcher ?? ''));
  if (match === null) {
    throw new Error('remote-fanout: this is not a wrapped pwsh program — no base64 payload found (see wrapPwshProgram)');
  }
  return Buffer.from(match[1], 'base64').toString('utf16le');
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
 */
export function buildPosixScript({ invocation, profile, task, dshHome, cwd, nonce = '', ...spec }) {
  const m = markers(nonce);
  const resolved = requiredInvocation({ invocation, ...spec });
  const profileWord = profile ?? 'headless';
  assertTaskSize(task ?? '');
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
    // THE HOST IS CAPTURED PORTABLY, AND THIS IS NOT COSMETIC.
    // `sh -s` means POSIX `sh`, which is `dash` on Debian and Ubuntu — the shell
    // of two nodes in this mesh. `dash` has no `printf -v` (measured 2026-09-29:
    // `sh: 1: printf: Illegal option -v`), so the previous form left `fanout_host`
    // EMPTY, the transport recorded host "", and `provider.js` refused the run at
    // the location check — AFTER the child had already done its work. Every child
    // placed on a Linux node was discarded this way: 19 of 19 placements on
    // `secratary` in the 48 h to 2026-09-29 ended with
    // `the transport reported host "", which is not one of the hostnames the
    // placement named`. A command substitution is POSIX and works in every shell
    // this mesh runs; `uname -n` is the fallback for a target whose
    // non-interactive PATH has no `hostname`. Do not "simplify" this back.
    `fanout_host=$(hostname 2>/dev/null || uname -n)`,
    `printf '%s\\n' "${m.host}$fanout_host"`,
    `printf '%s\\n' "${m.cwd}$(pwd)"`,
    `printf '%s\\n' "${m.begin}"`,
    // THE CHILD GETS ITS OWN STDIN, and this is the POSIX half of the same
    // defect the PowerShell wrapper fixes (see `wrapPwshProgram`): the program is
    // delivered to `sh -s` on stdin, so a child that inherits that pipe can eat
    // the rest of the program — every line after the child, including the closing
    // frame. `/dev/null` is portable, costs one word, and leaves the parent's
    // stdin untouched for the shell that is still reading it.
    [
      ...[resolved.command, ...(resolved.argvPrefix ?? [])].map(shellWord),
      '--profile',
      shellWord(profileWord),
      taskWord(task),
      '< /dev/null',
    ].join(' '),
    'fanout_exit=$?',
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
