/**
 * artifact-provenance.mjs — every verdict must say WHICH CONFIG it judged, and a verdict about the
 * wrong config must not be able to open the gate.
 *
 * THE DEFECT THIS EXISTS FOR (measured 2026-10-05, on this repository).
 * --------------------------------------------------------------------------------------------
 * The pipeline stages: a version-coupled config change cannot be judged against the live config, so
 * `analyze`, `patch-effect`, `preset-gate` and `verify` all honour `DSH_HOME` and are meant to be run
 * against a STAGED copy. Their verdicts are written to `state/candidates/<version>/*.json` — the same
 * files for a real run and for a test run.
 *
 * Nothing recorded which home a verdict came from. So on 2026-09-28 a test suite that pointed
 * `DSH_HOME` at `%TEMP%\switch-rework-<stamp>\staged-home` — a synthetic home built from fixtures —
 * overwrote the authoritative per-candidate artifacts, and every downstream reading then described a
 * config that does not exist on this machine:
 *
 *   state/candidates/0.1.7-rc.2/patch-effect.json
 *     "our patch layer C:\Users\ezabz\AppData\Local\Temp\switch-rework-20260928T203232Z\
 *      staged-home\profiles\web\cordis.patch.yml entry 2 targets row id \"remote-fanout\""
 *
 * `status` then reported `0.1.7-rc.2 ... verify=FAIL`, `preflight` reported NO-GO, and the switch
 * suite's own README recorded that the repository's real preflight was NO-GO "for reasons that have
 * nothing to do with the switch". Both statements were about a fixture.
 *
 * This is the single worst failure mode in this system's history — reading the wrong data and
 * believing it — and here it was built into the tool: the artefacts of a judgment are anonymous, and
 * an anonymous judgment cannot be checked, only believed.
 *
 * WHAT THIS MODULE DOES. It stamps a `configIdentity` block into every artifact the pipeline writes,
 * and answers one question about any of them: *was this verdict computed about the config that the
 * operation now being gated will actually affect?* Anything short of an exact match is a problem, and
 * a missing identity is a problem rather than a pass — an artifact from before this schema cannot
 * demonstrate what it judged, and "cannot demonstrate" is not "fine".
 *
 * It is deliberately NOT satisfied by a staged run being "close enough". The whole point of staging is
 * that the staged config is judged against a candidate ENGINE; the artifact is then used to decide
 * whether to install that config and that engine onto the LIVE home. Those are two different
 * questions, and the second one must be judged by artifacts that name the home they were asked about.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export const SCHEMA = 1;

/** The live DSH config home — the one a promote affects when nothing is staged. */
export function liveConfigHome() {
  return path.resolve(path.join(os.homedir(), '.dsh'));
}

function samePath(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !a || !b) return false;
  const na = path.resolve(a);
  const nb = path.resolve(b);
  return process.platform === 'win32' ? na.toLowerCase() === nb.toLowerCase() : na === nb;
}

/**
 * True when `dir` sits under any temp root — the shape a test fixture's staged home has.
 *
 * WHY THERE IS MORE THAN ONE ROOT. `os.tmpdir()` is not a stable answer here: measured on ZABZ-TECH
 * 2026-10-05, a DSH child process sees `os.tmpdir()` as `C:\Users\ezabz\.dsh\tmp`, because the engine
 * redirects TMP/TEMP into its own home — while the fixture that caused the 2026-09-28 defect was at
 * `C:\Users\ezabz\AppData\Local\Temp\switch-rework-<stamp>\staged-home`. Keying on one root would make
 * this check silently depend on which process was asking, and a fixture detector that answers
 * differently depending on the caller is not a detector.
 */
export function looksTemporary(dir) {
  if (typeof dir !== 'string' || !dir) return false;
  const roots = [os.tmpdir(), envPath('TEMP'), envPath('TMP')];
  const localAppData = envPath('LOCALAPPDATA');
  if (localAppData) roots.push(path.join(localAppData, 'Temp'));
  // The engine's own redirected temp directory, which is inside the live home.
  roots.push(path.join(liveConfigHome(), 'tmp'));
  let d;
  try { d = path.resolve(dir); } catch { return false; }
  const lower = process.platform === 'win32' ? d.toLowerCase() : d;
  return roots.some((root) => {
    if (!root) return false;
    let r;
    try { r = path.resolve(root); } catch { return false; }
    const rl = process.platform === 'win32' ? r.toLowerCase() : r;
    return lower === rl || lower.startsWith(rl + path.sep);
  });
}

function envPath(name) {
  const v = process.env[name];
  return v && v.trim() ? v : null;
}

/**
 * Build the block that gets stamped into an artifact.
 * `kind` is derived, never passed: a caller that could label its own run 'live' would be able to
 * launder a fixture verdict, which is the defect this file exists to prevent.
 */
export function configIdentity({ dshHome, profile = null, host = null, at = null } = {}) {
  const home = dshHome ? path.resolve(dshHome) : null;
  const live = liveConfigHome();
  return {
    schemaVersion: SCHEMA,
    dshHome: home,
    liveConfigHome: live,
    kind: home && samePath(home, live) ? 'live' : 'staged',
    temporary: home ? looksTemporary(home) : null,
    profile,
    host,
    at: at ?? new Date().toISOString(),
  };
}

/**
 * Stamp a parsed artifact object in place and return it.
 * Refuses to overwrite an identity that is already present and DIFFERENT: two verdicts about two
 * different configs do not become one verdict because they were written to the same filename.
 */
export function stampIdentity(artifact, identity) {
  if (!artifact || typeof artifact !== 'object') return artifact;
  const existing = artifact.configIdentity;
  if (existing && existing.schemaVersion === SCHEMA && !samePath(existing.dshHome, identity.dshHome)) {
    throw new Error(
      `refusing to re-stamp an artifact that already records configIdentity.dshHome=${existing.dshHome} `
      + `with a verdict about ${identity.dshHome}: these are two different configs and they must not `
      + 'share a verdict file. Re-run the verb against this config instead.',
    );
  }
  artifact.configIdentity = identity;
  return artifact;
}

/** Read, stamp and atomically rewrite a JSON artifact. Returns the stamped identity, or null. */
export function stampIdentityFile(file, identity) {
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null; // the caller's own read already reports absence/unparseable; never mask that here
  }
  stampIdentity(parsed, identity);
  const tmp = `${file}.tmp-identity-${process.pid}`;
  fs.writeFileSync(tmp, `${JSON.stringify(parsed, null, 2)}\n`);
  fs.renameSync(tmp, file);
  return identity;
}

/**
 * Was `artifact` computed about `expectedHome`?
 *
 * @param {object|null|undefined} artifact  the parsed artifact (or null)
 * @param {{expectedHome: string, what: string}} opts
 * @returns {{ok: boolean, reason: string|null, identity: object|null}}
 */
export function provenanceVerdict(artifact, opts = {}) {
  const what = opts.what || 'this artifact';
  const expectedHome = opts.expectedHome ? path.resolve(opts.expectedHome) : null;
  if (!expectedHome) {
    return { ok: false, reason: `${what} cannot be checked: no expected config home was resolved`, identity: null };
  }
  if (!artifact || typeof artifact !== 'object') {
    return { ok: false, reason: `${what} could not be read`, identity: null };
  }
  const id = artifact.configIdentity;
  if (!id || typeof id !== 'object') {
    return {
      ok: false,
      identity: null,
      reason: `${what} records no configIdentity, so it does not say which config it judged. It was written `
        + `before the provenance schema (${SCHEMA}) existed, or by a code path that does not stamp. Re-run `
        + 'the verb that produced it — a verdict that cannot name its subject is not evidence about this one.',
    };
  }
  if (id.schemaVersion !== SCHEMA) {
    return { ok: false, identity: id, reason: `${what} carries configIdentity schemaVersion=${JSON.stringify(id.schemaVersion)}, not ${SCHEMA}` };
  }
  if (!id.dshHome) {
    return { ok: false, identity: id, reason: `${what} carries a configIdentity with no dshHome` };
  }
  if (!samePath(id.dshHome, expectedHome)) {
    const temp = looksTemporary(id.dshHome) ? ' (a TEMP path — that is a test fixture, not a config home)' : '';
    return {
      ok: false,
      identity: id,
      reason: `${what} was computed about ${id.dshHome}${temp}, but the operation being gated affects `
        + `${expectedHome}. A verdict about one config is not evidence about another — this is the `
        + '2026-09-28 15:32:08 failure mode.',
    };
  }
  return { ok: true, identity: id, reason: null };
}

/** The per-candidate artifacts that carry a verdict about a config. */
export const CANDIDATE_ARTIFACTS = Object.freeze([
  'diff.json', 'patch-effect.json', 'preset-gate.json', 'settings-effective.json', 'verify.json',
]);

/** Stamp every candidate artifact that exists. Returns the names it stamped. */
export function stampCandidateArtifacts(dir, identity) {
  const stamped = [];
  for (const name of CANDIDATE_ARTIFACTS) {
    const file = path.join(dir, name);
    if (!fs.existsSync(file)) continue;
    if (stampIdentityFile(file, identity)) stamped.push(name);
  }
  return stamped;
}

/**
 * Do the candidate's artifacts agree, between themselves, on which config home they judged — and is
 * that home the one this operation may act on?
 *
 * THREE RULES, each one earned by the 2026-09-28 defect:
 *  1. Every artifact that carries a verdict must record a subject. A missing identity is a problem,
 *     not a pass: an artifact written before this schema cannot demonstrate what it judged.
 *  2. The artifacts must agree. Two verdicts about two different configs written to one candidate
 *     directory is exactly how a fixture verdict ends up gating the live deployment — each file looks
 *     fine on its own, and only the comparison shows the seam.
 *  3. The home must not be an OS-temp path. A temp home is a fixture by construction (the switch tests
 *     point -TargetHome at %TEMP%), and a verdict about a fixture must never open a gate on the real
 *     deployment. A deliberately built staged home — the thing the pipeline is designed to be run
 *     against — is fine, and is why this is not simply "must equal the live home".
 *
 * @returns {{ok: boolean, homes: string[], stamped: string[], unstamped: string[], reason: string|null}}
 */
export function candidateProvenanceProblem(dir, opts = {}) {
  const expectedHome = opts.expectedHome ? path.resolve(opts.expectedHome) : null;
  const homes = new Set();
  const stamped = [];
  const unstamped = [];
  const problems = [];
  for (const name of CANDIDATE_ARTIFACTS) {
    const file = path.join(dir, name);
    if (!fs.existsSync(file)) continue;
    let parsed;
    try {
      parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    } catch {
      unstamped.push(name);
      problems.push(`${name} cannot be parsed, so its subject is unknown`);
      continue;
    }
    const id = parsed?.configIdentity;
    if (!id || id.schemaVersion !== SCHEMA || !id.dshHome) {
      unstamped.push(name);
      problems.push(`${name} records no configIdentity (schema ${SCHEMA}), so it does not say which config it judged`);
      continue;
    }
    stamped.push(name);
    homes.add(path.resolve(id.dshHome));
  }
  if (stamped.length === 0) {
    problems.push('no artifact in this candidate directory records which config it judged, so nothing here can be checked');
  }
  if (homes.size > 1) {
    problems.push(`the artifacts disagree on which config they judged: ${[...homes].join(' vs ')}`);
  }
  const only = homes.size === 1 ? [...homes][0] : null;
  if (only && looksTemporary(only)) {
    problems.push(`${only} is under the OS temp directory — that is a TEST FIXTURE, and a verdict about a fixture must not gate this deployment`);
  }
  if (only && expectedHome && path.resolve(expectedHome) !== only) {
    problems.push(`the artifacts judged ${only}, but this operation is about ${expectedHome}`);
  }
  return {
    ok: problems.length === 0,
    homes: [...homes],
    stamped,
    unstamped,
    reason: problems.length ? problems.join('; ') : null,
  };
}

