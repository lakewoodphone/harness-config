/**
 * provenance.mjs — the guard that holds "a verdict must name the config it judged".
 *
 * THE DEFECT IT HOLDS FIXED (measured 2026-10-05, on this repository).
 * --------------------------------------------------------------------------------------------
 * `state/candidates/<version>/*.json` is where every verdict about a candidate lands. The pipeline is
 * DESIGNED to judge a staged config, so the same filenames are written by a real run and by a test run
 * — and nothing recorded which home a verdict came from. On 2026-09-28 a test suite pointed `DSH_HOME`
 * at `%TEMP%\switch-rework-<stamp>\staged-home`, overwrote the authoritative artifacts, and every
 * later reading then described a config that does not exist on this machine:
 *
 *   patch-effect.json: "our patch layer C:\Users\ezabz\AppData\Local\Temp\
 *                       switch-rework-20260928T203232Z\staged-home\profiles\web\cordis.patch.yml
 *                       entry 2 targets row id \"remote-fanout\""
 *
 * `status` reported `0.1.7-rc.2 verify=FAIL`; the switch suite's own README recorded that the
 * repository's real preflight was NO-GO "for reasons that have nothing to do with the switch". Both
 * were statements about a fixture presented as statements about this deployment.
 *
 * Run:  node dsh-update/tests/guards/provenance.mjs      (exit 0 pass, 1 fail)
 *
 * It writes only under its own unique temp directory and removes nothing outside it. Two homes are
 * deliberately distinguished in the fixtures: the DIRECTORY the artifacts live in is under temp (that
 * is just scratch space), while the config home they CLAIM to have judged is a normal path — those are
 * different things and conflating them is what made the first version of this test prove nothing.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  SCHEMA, candidateProvenanceProblem, configIdentity, liveConfigHome, provenanceVerdict,
  stampCandidateArtifacts, stampIdentity,
} from '../../lib/artifact-provenance.mjs';

let failures = 0;
let checks = 0;

function check(name, actual, expected) {
  checks += 1;
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) process.stdout.write(`  ok    ${name}\n`);
  else { failures += 1; process.stdout.write(`  FAIL  ${name}\n        expected ${e}\n        actual   ${a}\n`); }
}

function checkThat(name, cond, why) {
  checks += 1;
  if (cond) process.stdout.write(`  ok    ${name}\n`);
  else { failures += 1; process.stdout.write(`  FAIL  ${name}\n        ${why}\n`); }
}

const scratch = path.join(os.tmpdir(), `provenance-guard-${process.pid}-${Date.now()}`);
fs.mkdirSync(scratch, { recursive: true });

const LIVE = liveConfigHome();
/** A plausible deliberately-built staged home: NOT the live home, NOT under any temp root. */
const STAGED = path.join(os.homedir(), '.dsh-stage-guard-fixture', 'staged-home');
const FIXTURE = path.join(os.tmpdir(), 'switch-rework-guard', 'staged-home');

const dir = (n) => { const d = path.join(scratch, n); fs.mkdirSync(d, { recursive: true }); return d; };
const put = (d, name, obj) => fs.writeFileSync(path.join(d, name), `${JSON.stringify(obj, null, 2)}\n`);
/** An artifact carrying a chosen identity, written directly — this is how a mixed directory arises. */
const artifactWith = (home, extra = {}) => ({ ...extra, configIdentity: configIdentity({ dshHome: home, profile: 'web' }) });

process.stdout.write('provenance: every verdict must name the config it judged\n');

// ── the identity itself ──────────────────────────────────────────────────────────────────────────
check('the live home is labelled kind=live', configIdentity({ dshHome: LIVE }).kind, 'live');
check('another home is labelled kind=staged', configIdentity({ dshHome: STAGED }).kind, 'staged');
check('the identity never lets a caller choose its own kind', 'kind' in configIdentity({ dshHome: LIVE, kind: 'live' }) && configIdentity({ dshHome: STAGED, kind: 'live' }).kind, 'staged');
check('the identity records the schema version', configIdentity({ dshHome: LIVE }).schemaVersion, SCHEMA);
checkThat('a home under a temp root is flagged temporary', configIdentity({ dshHome: FIXTURE }).temporary === true,
  'the 2026-09-28 path shape must be detectable');
checkThat('a temp home under the engine\'s own redirected tmp is ALSO flagged temporary',
  configIdentity({ dshHome: path.join(LIVE, 'tmp', 'switch-rework-y', 'staged-home') }).temporary === true,
  'DSH redirects TMP/TEMP into <live>\\tmp, so os.tmpdir() alone would miss this shape');
checkThat('a normal staged home is NOT flagged temporary', configIdentity({ dshHome: STAGED }).temporary === false,
  'a deliberately built staged home is the pipeline\'s normal subject and must not be treated as a fixture');

// ── the verdict about one artifact ───────────────────────────────────────────────────────────────
check('live judged, live gated -> ok', provenanceVerdict(artifactWith(LIVE), { expectedHome: LIVE }).ok, true);
check('a fixture judged, live gated -> REFUSED', provenanceVerdict(artifactWith(FIXTURE), { expectedHome: LIVE }).ok, false);
check('no identity at all -> REFUSED, never a pass', provenanceVerdict({}, { expectedHome: LIVE }).ok, false);
check('a wrong schema version -> REFUSED', provenanceVerdict({ configIdentity: { schemaVersion: 99, dshHome: LIVE } }, { expectedHome: LIVE }).ok, false);
check('an identity with no dshHome -> REFUSED', provenanceVerdict({ configIdentity: { schemaVersion: SCHEMA } }, { expectedHome: LIVE }).ok, false);
check('a staged home judged, live gated -> REFUSED (a staged verdict is not evidence about live)',
  provenanceVerdict(artifactWith(STAGED), { expectedHome: LIVE }).ok, false);
checkThat('the refusal names BOTH configs, not just "something is wrong"',
  /but the operation being gated affects/.test(provenanceVerdict(artifactWith(STAGED), { expectedHome: LIVE }).reason ?? ''),
  'a refusal that does not name both homes is not actionable');
checkThat('and it says the word fixture when the subject is a temp path',
  /fixture/i.test(provenanceVerdict(artifactWith(FIXTURE), { expectedHome: LIVE }).reason ?? ''));

// ── re-stamping may not launder a verdict ────────────────────────────────────────────────────────
checkThat('re-stamping an artifact with a DIFFERENT home throws',
  (() => { try { stampIdentity(artifactWith(FIXTURE), configIdentity({ dshHome: LIVE })); return false; } catch { return true; } })(),
  'two verdicts about two configs must not become one verdict because they share a filename');
checkThat('re-stamping with the SAME home is allowed',
  (() => { try { stampIdentity(artifactWith(LIVE), configIdentity({ dshHome: LIVE })); return true; } catch { return false; } })());

// ── the candidate-directory reading, which is what promote and preflight consume ─────────────────
const okDir = dir('ok');
put(okDir, 'diff.json', { verdict: 'SAFE' });
put(okDir, 'verify.json', { pass: true });
checkThat('stampCandidateArtifacts stamps every artifact present',
  stampCandidateArtifacts(okDir, configIdentity({ dshHome: STAGED, profile: 'web' })).sort().join(','), 'diff.json,verify.json');
check('all artifacts agree on one non-temp staged home -> ok',
  candidateProvenanceProblem(okDir, { expectedHome: STAGED }).ok, true);
checkThat('and it reports which artifacts it checked', candidateProvenanceProblem(okDir, {}).stamped.length === 2,
  'a provenance check that does not say what it read is not auditable');

const mixedDir = dir('mixed');
put(mixedDir, 'diff.json', artifactWith(STAGED, { verdict: 'SAFE' }));
put(mixedDir, 'verify.json', artifactWith(FIXTURE, { pass: true }));
check('artifacts that DISAGREE on their subject -> problem', candidateProvenanceProblem(mixedDir, {}).ok, false);
checkThat('the disagreement names the homes',
  /disagree on which config they judged/.test(candidateProvenanceProblem(mixedDir, {}).reason ?? ''),
  'the seam between two verdicts is only useful if it is named');

const fixtureDir = dir('fixture');
put(fixtureDir, 'verify.json', artifactWith(FIXTURE, { pass: true }));
check('a TEMP fixture home never opens a gate, even with no expected home given',
  candidateProvenanceProblem(fixtureDir, {}).ok, false);

const unstampedDir = dir('unstamped');
put(unstampedDir, 'verify.json', { pass: true });
check('artifacts from before the schema cannot gate anything', candidateProvenanceProblem(unstampedDir, {}).ok, false);
checkThat('and the refusal explains that they do not say what they judged',
  /does not say which config it judged/.test(candidateProvenanceProblem(unstampedDir, {}).reason ?? ''));
checkThat('and they are listed as unstamped, not silently skipped',
  candidateProvenanceProblem(unstampedDir, {}).unstamped.join(',') === 'verify.json');

const mismatchDir = dir('mismatch');
put(mismatchDir, 'verify.json', artifactWith(path.join(os.homedir(), '.dsh-somewhere-else'), { pass: true }));
check('a real staged home that is not the one being gated -> problem',
  candidateProvenanceProblem(mismatchDir, { expectedHome: STAGED }).ok, false);

check('a candidate directory with no artifacts at all -> problem, not a pass',
  candidateProvenanceProblem(dir('empty'), {}).ok, false);

// ── teardown: only what this run created ─────────────────────────────────────────────────────────
fs.rmSync(scratch, { recursive: true, force: true });

process.stdout.write(`\nprovenance: ${checks - failures}/${checks} assertion(s) passed\n`);
if (failures > 0) {
  process.stdout.write('provenance: FAIL — an anonymous verdict can gate an irreversible change.\n');
  process.exit(1);
}
process.exit(0);
