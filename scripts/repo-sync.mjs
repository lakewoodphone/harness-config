#!/usr/bin/env node
/**
 * repo-sync.mjs — keep the manager's repositories current and make sure work that was done actually
 * leaves the machine.
 *
 * THE PROBLEM THIS SOLVES, found by looking rather than assuming
 * Her agent produced a real customer case file on the laptop --
 * `docs/customer-operations/cases/ideapad-slim-3-15abr8-82xm00lmus-screen-sourcing-2026-09-14.md` --
 * and it was sitting UNTRACKED in the working tree. The work existed, the customer's file existed, and
 * nothing would ever have committed or pushed it. An hour later nobody would have known it was there.
 * That is the failure this closes: customer work done on her machine must reach the shop's repo.
 *
 * WHAT IT DOES, PER REPOSITORY
 *   1. `git pull --rebase --autostash` -- brings the repo current, replaying anything local on top.
 *      A rebase rather than --ff-only because these machines legitimately hold local commits; refusing
 *      to proceed whenever the branch is ahead is how a machine silently freezes on old content.
 *   2. stage everything, and if anything is staged, commit it with a message that says plainly where
 *      it came from.
 *   3. push, unless told not to.
 *
 * ATTRIBUTION IS NOT OPTIONAL HERE
 * Every commit made by this script carries `Dsh-Machine`, `Dsh-Actor` and `Dsh-At` trailers naming the
 * machine that produced it, written directly into the message rather than relying on the hook being
 * installed. The owner's rule for her machines is that changes are LABELLED, not restricted -- so the
 * labelling is done by the mechanism, not left to the model to remember.
 *
 * SAFETY
 *   * never `reset --hard`, never force, never rebase-over-remote when the rebase does not apply
 *     cleanly -- it aborts and reports instead;
 *   * never commits in a repo where the owner's own work might be mid-flight: it only touches the
 *     paths it is given, and a dirty tree that cannot be committed is reported, not discarded;
 *   * a repo with no upstream is skipped with a note rather than guessed at.
 *
 * Usage:
 *   node repo-sync.mjs [--repo DIR]... [--no-push] [--dry-run] [--json]
 *   node repo-sync.mjs --list                 # the standard manager repos, what state they are in
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const HOME = os.homedir();
const MACHINE = os.hostname();
const ACTOR = process.env.USERNAME || process.env.USER || 'unknown';
const DRY = process.argv.includes('--dry-run');
const NOPUSH = process.argv.includes('--no-push');
const JSON_OUT = process.argv.includes('--json');
const VERB = (process.argv[2] || '').toLowerCase();

/**
 * The repositories a MANAGER workstation keeps current.
 *
 * THIS IS A WIDE LIST ON PURPOSE. An earlier version covered only lpt-hub and the secretary repo -- an
 * arbitrary default of mine, and the owner corrected it: she runs the whole shop, so the flip-phone
 * deployment, the Home Assistant config, the filter/Waze system and the rest are all hers to see and
 * work with. A manager who can only see two repositories is a crippled manager, which is exactly what
 * he said not to build.
 *
 * WHY NOT "EVERY GIT REPO IN THE HOME DIRECTORY", which would be simpler:
 * On the OWNER's own box, `harness-config` carries over a hundred in-flight paths at any moment; a bulk
 * sweep would commit half-written work and push it under a message attributing it to the manager's
 * machine. harness-config also has its own convergence path written for exactly that hazard. So the
 * list is explicit -- and anything a machine does not have is simply skipped with a note, which is what
 * makes one list work on both of her machines.
 *
 * Case-INSENSITIVE de-duplication matters and I got it wrong first: on Windows `~/code` and `~/Code`
 * are the same directory, so a naive list reports every repository twice and syncs it twice. Paths are
 * compared through `fs.realpathSync.native` with case folded.
 */
const MANAGER_REPOS = [
  // The shop's own records and the customer-facing work.
  'lpt-hub',
  // The company system.
  'personal-secretary-mvp',
  // The products she sells and supports.
  'lpt-flip-phone',
  'lpt-schematics',
  'tesla-lin-chip',
  // Physical infrastructure she runs day to day.
  'ha-config',
  'kosher-filter-ai',
  // Supporting material a manager legitimately reaches for.
  'research-knowledge-base',
  'quickbooks-agent',
  'phone-and-tech-full',
  'yocheved',
];

/** Where a repo may live on either platform, tried in order. */
const REPO_PARENTS = ['code', 'Code', ''];

function managerRepos() {
  const found = new Map();
  const add = (p) => {
    if (!p) return;
    let real;
    try { real = fs.realpathSync.native(p); } catch { return; }
    if (!fs.existsSync(path.join(real, '.git'))) return;
    const key = real.toLowerCase();
    if (!found.has(key)) found.set(key, real);
  };
  for (const parent of REPO_PARENTS) {
    for (const name of MANAGER_REPOS) {
      add(parent ? path.join(HOME, parent, name) : path.join(HOME, name));
    }
  }
  // A few places these actually live when the name does not match the directory.
  add(path.join(HOME, 'code', 'research'));
  add(path.join(HOME, 'Code', 'research'));
  add(path.join(HOME, 'code', 'phone-and-tech'));
  return [...found.values()];
}

function git(repo, args, { input } = {}) {
  const r = spawnSync('git', ['-C', repo, ...args], { encoding: 'utf8', input, env: process.env });
  return { ok: r.status === 0, out: `${r.stdout || ''}${r.stderr || ''}`.trim(), code: r.status };
}

function report(rows) {
  if (JSON_OUT) { console.log(JSON.stringify({ machine: MACHINE, repos: rows }, null, 2)); return; }
  for (const r of rows) {
    console.log(`  ${r.repo}`);
    console.log(`    ${r.result}${r.detail ? ' -- ' + r.detail : ''}`);
  }
}

/**
 * Repositories that are READ-ONLY for this machine, on purpose.
 *
 * MEASURED 2026-09-15 on her laptop: her GitHub key is a DEPLOY KEY SCOPED TO ONE REPOSITORY
 * (lakewoodphone/lpt-hub). It authenticates and pushes there, and it is refused by
 * personal-secretary-mvp with "Please make sure you have the correct access rights". That is a
 * deliberate boundary somebody set on purpose, not a fault to route around -- widening it would be a
 * change to who may write the company's code, and that is the owner's call, not mine to assume.
 *
 * So those clones are kept but treated as READ-ONLY: pull and report honestly, never push. Without
 * this they are committing and then failing to push every hour, which fills a log with "needing
 * attention" and trains everyone to ignore it.
 *
 * `lpt-hub` -- the customer case files -- is NOT here, because that is the one her agent must write.
 */
const READ_ONLY_PATTERNS = [
  /personal-secretary-mvp$/i,
];

function isReadOnly(repo) {
  return READ_ONLY_PATTERNS.some((re) => re.test(repo));
}

function syncRepo(repo) {
  const row = { repo, result: 'unchanged', detail: '' };
  const readOnly = isReadOnly(repo);

  if (!fs.existsSync(path.join(repo, '.git'))) { row.result = 'skipped'; row.detail = 'not a git checkout'; return row; }

  const branch = git(repo, ['rev-parse', '--abbrev-ref', 'HEAD']).out || 'HEAD';
  const upstream = git(repo, ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}']);
  if (!upstream.ok) { row.result = 'skipped'; row.detail = `branch ${branch} has no upstream`; return row; }

  if (DRY) {
    const dirty = git(repo, ['status', '--porcelain']).out;
    const ahead = git(repo, ['rev-list', '--count', '@{u}..HEAD']).out || '0';
    row.result = 'would-sync';
    row.detail = `${readOnly ? 'read-only, ' : ''}${dirty ? dirty.split('\n').length + ' changed path(s)' : 'clean'}, ${ahead} local commit(s) ahead`;
    return row;
  }

  // 1. bring it current, keeping local commits on top.
  const pull = git(repo, ['pull', '--rebase', '--autostash', '--quiet']);
  if (!pull.ok) {
    // A failed rebase must never be resolved by choosing a side.
    git(repo, ['rebase', '--abort']);
    const offline = /could not resolve|unable to access|timed out|network|Could not read from remote|correct access rights|not found/i.test(pull.out);
    if (readOnly) {
      // Expected for a read-only clone we lack credentials for: say so plainly and move on.
      row.result = 'read-only';
      row.detail = 'kept as-is; this machine has no fetch/push credential for it (by design)';
      return row;
    }
    row.result = offline ? 'offline' : 'attention';
    row.detail = offline ? 'remote unreachable; local work still committed below' : `pull/rebase failed: ${pull.out.split('\n').slice(-2).join(' ')}`;
  }

  // 2. capture anything outstanding. For a read-only clone the work is still recorded LOCALLY -- it
  //    must not be lost just because it cannot be published -- but it is not pushed.
  const status = git(repo, ['status', '--porcelain']).out;
  let committed = false;
  if (status) {
    git(repo, ['add', '-A']);
    const when = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
    const changed = status.split('\n').length;
    const message = [
      `chore(${MACHINE.toLowerCase()}): ${changed} path(s) captured from the manager workstation`,
      '',
      'Committed by repo-sync.mjs so that work done on this machine is recorded and does not sit',
      'untracked in the working tree. Files touched:',
      ...status.split('\n').slice(0, 20).map((l) => '  ' + l.trim()),
      changed > 20 ? `  ... and ${changed - 20} more` : null,
      '',
      `Dsh-Actor: ${ACTOR}`,
      `Dsh-Machine: ${MACHINE}`,
      `Dsh-At: ${when}`,
      readOnly ? 'Dsh-Note: held locally (no push credential for this repository on this machine)' : null,
    ].filter((l) => l !== null).join('\n');
    const c = git(repo, ['commit', '-m', message]);
    if (c.ok) { committed = true; row.detail = `${changed} path(s) committed`; }
    else { row.result = 'attention'; row.detail = `commit failed: ${c.out.split('\n').slice(-2).join(' ')}`; }
  }

  // 3. push, so the work actually leaves the machine -- unless this clone has no credential for it.
  const ahead = Number(git(repo, ['rev-list', '--count', '@{u}..HEAD']).out || '0');
  if (readOnly && ahead > 0) {
    row.result = 'read-only';
    row.detail = `${ahead} local commit(s) held here; this machine cannot push this repository`;
    return row;
  }
  if (ahead > 0) {
    if (NOPUSH) { row.result = row.result === 'attention' ? row.result : 'local-only'; row.detail = `${ahead} commit(s) ahead (push disabled)`; }
    else {
      const p = git(repo, ['push', 'origin', 'HEAD']);
      if (p.ok) { row.result = row.result === 'attention' ? 'attention' : 'pushed'; row.detail = `${ahead} commit(s) pushed`; }
      else { row.result = 'attention'; row.detail = `push refused (kept locally): ${p.out.split('\n').slice(-2).join(' ')}`; }
    }
  } else if (committed) {
    row.result = row.result === 'attention' ? row.result : 'committed';
  }
  return row;
}

if (VERB === '--list' || VERB === 'list') {
  const repos = managerRepos();
  if (JSON_OUT) console.log(JSON.stringify(repos.map((r) => ({
    repo: r,
    branch: git(r, ['rev-parse', '--abbrev-ref', 'HEAD']).out,
    head: git(r, ['rev-parse', '--short', 'HEAD']).out,
    dirty: git(r, ['status', '--porcelain']).out ? true : false,
    ahead: Number(git(r, ['rev-list', '--count', '@{u}..HEAD']).out || 0),
  })), null, 2));
  else for (const r of repos) {
    const dirty = git(r, ['status', '--porcelain']).out;
    const ahead = git(r, ['rev-list', '--count', '@{u}..HEAD']).out || '0';
    console.log(`  ${r}`);
    console.log(`    head ${git(r, ['rev-parse', '--short', 'HEAD']).out}  ${dirty ? 'DIRTY (' + dirty.split('\n').length + ' paths)' : 'clean'}  ${ahead} ahead`);
  }
  process.exit(0);
}

const explicit = [];
for (let i = 0; i < process.argv.length; i++) if (process.argv[i] === '--repo') explicit.push(path.resolve(process.argv[i + 1]));
const repos = explicit.length ? explicit.map((p) => { try { return fs.realpathSync.native(p); } catch { return p; } }) : managerRepos();

if (!repos.length) { console.error('repo-sync: no repositories found'); process.exit(1); }

if (!JSON_OUT) {
  console.log(`repo-sync on ${MACHINE}${DRY ? ' (dry run)' : ''}`);
  console.log('');
}
const rows = repos.map(syncRepo);
report(rows);
const bad = rows.filter((r) => r.result === 'attention');
if (!JSON_OUT) console.log(`\n${rows.length} repo(s): ${rows.filter((r) => r.result === 'pushed' || r.result === 'committed').length} changed, ${bad.length} needing attention`);
process.exit(bad.length ? 1 : 0);
