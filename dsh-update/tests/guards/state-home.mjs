#!/usr/bin/env node
/**
 * tests/guards/state-home.mjs — the guard for the 2026-09-28 two-homes defect in lib/verify.mjs.
 *
 * WHAT HAPPENED, AND WHY THIS FILE EXISTS. `--dsh-home` meant TWO things at once: the config under
 * test AND where the runtime state lives. That is the same directory in a normal run and two
 * different ones in a staged run, and the pipeline's whole staging story depends on the staged run:
 * a version-coupled config change cannot be judged against the live config, which by definition is
 * not migrated yet. Measured against `%TEMP%\dsh-staged-migrated`:
 *
 *   G4/G5  ran:false — "the model credential could not be resolved from
 *          C:\Users\ezabz\AppData\Local\Temp\dsh-staged-migrated\.credentials.yaml"
 *   G8     ran:false — "the live session files could not be counted (there is no sessions directory
 *          at C:\Users\ezabz\AppData\Local\Temp\dsh-staged-migrated\sessions)"
 *
 * — a third of the gates, all dark, on the one run that decides whether to promote. (And once the
 * staged home did carry a partial `sessions/`, G8 compared the candidate against those 20 staged
 * files while the operator's real history is 1,258: a gate reading the wrong directory is worse than
 * a gate that refuses to run.)
 *
 * WHAT THIS GUARD PROVES, without booting anything:
 *   1. the state home resolves to the operator's real home when `$env:DSH_HOME` points at a staged
 *      location (a path under the system temp directory or under dsh-update/state);
 *   2. it resolves to `$env:DSH_HOME` itself when that is the operator's home — the non-staged case,
 *      where behaviour must be exactly as it was before `--state-home` existed;
 *   3. an explicit `--state-home` and `$env:DSH_STATE_HOME` each win, in that order;
 *   4. the credential reader behaves the same way it always did — the file OR the reason, never a
 *      guess — and a short or whitespace-bearing value is refused rather than half-read;
 *   5. resolution never throws and never fabricates: an absent home is a named failure.
 *
 * It imports lib/verify.mjs (which is safe: the module only runs `main()` when it is the entry
 * point), so no engine is started, no port is opened and no session file is read.
 *
 *   node dsh-update/tests/guards/state-home.mjs        # exit 0 = pass, 1 = the defect is back
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');                 // dsh-update/
const VERIFY = path.join(ROOT, 'lib', 'verify.mjs');

const failures = [];
const check = (ok, label, detail) => {
  if (!ok) failures.push(`${label}${detail ? `: ${detail}` : ''}`);
  process.stdout.write(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}\n`);
};

if (!fs.existsSync(VERIFY)) {
  process.stdout.write(`FAIL  ${VERIFY} does not exist\n`);
  process.exit(1);
}
const mod = await import(pathToFileURL(VERIFY).href);
const { resolveStateHome, stagedHomeReason, resolveCredential } = mod;
check(typeof resolveStateHome === 'function' && typeof stagedHomeReason === 'function' && typeof resolveCredential === 'function',
  'lib/verify.mjs exports resolveStateHome, stagedHomeReason and resolveCredential');

/* ---- the environment is manipulated around each call, and restored at the end ----------------- */
const saved = { DSH_HOME: process.env.DSH_HOME, DSH_STATE_HOME: process.env.DSH_STATE_HOME };
const setEnv = (name, value) => {
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
};
const REAL_HOME = path.resolve(process.env.USERPROFILE ?? process.env.HOME ?? '.', '.dsh');
const STAGED = path.join(os.tmpdir(), `dsh-guard-staged-${process.pid}`);
const OTHER = path.join(os.tmpdir(), `dsh-guard-other-${process.pid}`);
fs.mkdirSync(STAGED, { recursive: true });

try {
  /* ---- 1. what "staged" means ----------------------------------------------------------------- */
  check(Boolean(stagedHomeReason(STAGED)), 'a home under the system temp directory is recognised as staged', stagedHomeReason(STAGED) ?? 'null');
  check(Boolean(stagedHomeReason(path.join(ROOT, 'state', 'candidates', '0.1.7-rc.2', 'home'))),
    'the isolated home this module builds under dsh-update/state is recognised as staged');
  check(stagedHomeReason(REAL_HOME) === null, `the operator's real home ${REAL_HOME} is NOT treated as staged`, stagedHomeReason(REAL_HOME) ?? undefined);

  /* ---- 2. the staged case: DSH_HOME is the config under test, not the state home --------------- */
  setEnv('DSH_STATE_HOME', undefined);
  setEnv('DSH_HOME', STAGED);
  const staged = resolveStateHome(undefined, STAGED);
  if (path.resolve(REAL_HOME) === path.resolve(STAGED)) {
    check(true, 'SKIPPED: the real home IS the staged path on this machine, so there is nothing to distinguish');
  } else if (!fs.existsSync(REAL_HOME)) {
    check(true, `SKIPPED: ${REAL_HOME} does not exist on this machine, so the fallback cannot be exercised`);
  } else {
    check(path.resolve(staged.home) === path.resolve(REAL_HOME),
      `with $env:DSH_HOME=${STAGED} the state home is the operator's real home`, `got ${staged.home}`);
    check(/staged/i.test(staged.source), 'the resolution SAYS that $env:DSH_HOME was treated as staged', staged.source);
    check(staged.source.includes(REAL_HOME), 'the resolution names the real home it chose', staged.source);
  }

  /* ---- 3. the non-staged case: unchanged behaviour --------------------------------------------- */
  setEnv('DSH_HOME', REAL_HOME);
  const plain = resolveStateHome(undefined, REAL_HOME);
  check(path.resolve(plain.home) === path.resolve(REAL_HOME),
    'with $env:DSH_HOME = the real home, the state home is that home (the pre-change behaviour)', `got ${plain.home}`);
  check(/\$env:DSH_HOME/.test(plain.source), 'the resolution says it came from $env:DSH_HOME', plain.source);

  setEnv('DSH_HOME', undefined);
  const noEnv = resolveStateHome(undefined, undefined);
  check(path.resolve(noEnv.home) === path.resolve(REAL_HOME),
    "with no $env:DSH_HOME the state home is the operator's real home", `got ${noEnv.home}`);

  setEnv('DSH_HOME', STAGED);
  setEnv('DSH_STATE_HOME', OTHER);
  const byStateEnv = resolveStateHome(undefined, STAGED);
  check(path.resolve(byStateEnv.home) === path.resolve(OTHER),
    '$env:DSH_STATE_HOME wins over $env:DSH_HOME', `got ${byStateEnv.home} (source: ${byStateEnv.source})`);

  const byFlag = resolveStateHome(OTHER, STAGED);
  check(path.resolve(byFlag.home) === path.resolve(OTHER) && /^--state-home/.test(byFlag.source),
    '--state-home wins over every environment variable', `got ${byFlag.home} (source: ${byFlag.source})`);

  /* ---- 4. the credential reader: a file or a reason, never a guess ------------------------------ */
  const scratch = path.join(os.tmpdir(), `dsh-guard-cred-${process.pid}`);
  fs.mkdirSync(scratch, { recursive: true });
  const FAKE = 'fixture-not-a-real-credential-0001';
  fs.writeFileSync(path.join(scratch, '.credentials.yaml'),
    `records:\n  DEEPSEEK_API_KEY:\n    secret: ${FAKE}\n`, 'utf8');
  const got = resolveCredential(scratch);
  check(got.ok === true, 'a credential file in the given home resolves', got.reason ?? '');
  check(got.ok && got.value === FAKE, 'the value read is the value in the file');
  check(got.ok && got.file === path.join(scratch, '.credentials.yaml'), 'the reading names the file it came from', got.file);
  check(got.ok && typeof got.value === 'string' && got.value.length === FAKE.length,
    'its length is reportable without the value', `length ${got.ok ? got.value.length : '?'}`);

  const absent = resolveCredential(path.join(os.tmpdir(), `dsh-guard-absent-${process.pid}`));
  check(absent.ok === false && /there is no file at/.test(absent.reason ?? ''),
    'an absent home yields a named reason, not a throw and not an empty success', absent.reason ?? '(no reason)');

  const stagedCred = resolveCredential(STAGED);
  check(stagedCred.ok === false, 'a staged home with no .credentials.yaml does NOT resolve a credential', stagedCred.reason ?? '');

  const shortHome = path.join(os.tmpdir(), `dsh-guard-short-${process.pid}`);
  fs.mkdirSync(shortHome, { recursive: true });
  fs.writeFileSync(path.join(shortHome, '.credentials.yaml'), 'records:\n  DEEPSEEK_API_KEY: abc\n', 'utf8');
  const short = resolveCredential(shortHome);
  check(short.ok === false, 'a too-short value is refused rather than half-read', short.reason ?? '');

  const spaceyHome = path.join(os.tmpdir(), `dsh-guard-spacey-${process.pid}`);
  fs.mkdirSync(spaceyHome, { recursive: true });
  fs.writeFileSync(path.join(spaceyHome, '.credentials.yaml'), 'records:\n  DEEPSEEK_API_KEY: "two words here"\n', 'utf8');
  const spacey = resolveCredential(spaceyHome);
  check(spacey.ok === false, 'a value containing whitespace is refused (whitespace means we misread)', spacey.reason ?? '');

  /* ---- 5. the credential is never echoed into anything this guard prints ------------------------ */
  check(!JSON.stringify({ ...got, value: undefined }).includes(FAKE),
    'the credential object carries the value only under `value`, never in another field');
} finally {
  setEnv('DSH_HOME', saved.DSH_HOME);
  setEnv('DSH_STATE_HOME', saved.DSH_STATE_HOME);
}

process.stdout.write(`\n${failures.length === 0 ? 'PASS' : `FAIL (${failures.length})`} — tests/guards/state-home.mjs\n`);
process.exit(failures.length === 0 ? 0 : 1);
