import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildPosixScript,
  buildPwshScript,
  markers,
  parseFanout,
  psQuote,
  shQuote,
  singleLine,
} from '../lib/remote-script.js';

test('psQuote doubles single quotes and never leaves a bare one', () => {
  assert.equal(psQuote("it's"), "'it''s'");
  assert.equal(psQuote('C:\\Program Files\\nodejs\\node.exe'), "'C:\\Program Files\\nodejs\\node.exe'");
});

test('shQuote closes and reopens around a single quote', () => {
  assert.equal(shQuote("it's"), "'it'\\''s'");
});

test('singleLine collapses newlines and runs of whitespace', () => {
  assert.equal(singleLine('  a\nb\r\n\n c  '), 'a b c');
});

test('the pwsh script sets DSH_HOME, frames the answer, and propagates the exit code', () => {
  const script = buildPwshScript({
    nodeExe: 'C:\\Program Files\\nodejs\\node.exe',
    dshBin: 'C:\\cache\\dsh\\lib\\bin.js',
    profile: 'headless',
    dshHome: 'C:\\tmp\\child-home',
    cwd: 'C:\\Users\\ezabz',
    task: "read it's file",
    nonce: 'abcd1234',
  });
  assert.match(script, /\$env:DSH_HOME = 'C:\\tmp\\child-home'/);
  assert.match(script, /Set-Location -LiteralPath 'C:\\Users\\ezabz'/);
  assert.match(script, /FANOUT_TRANSPORT_HOST_abcd1234=/);
  assert.match(script, /FANOUT_BEGIN_abcd1234/);
  assert.match(script, /--profile 'headless' 'read it''s file'/);
  assert.match(script, /\[Environment\]::Exit\(\$fanoutExit\)/);
});

test('the posix script is a sh program with the same frame', () => {
  const script = buildPosixScript({
    nodeExe: '/home/zabz/.local/node/bin/node',
    dshBin: '/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js',
    profile: 'headless',
    dshHome: '/home/zabz/.dsh-worker',
    cwd: '/home/zabz/code',
    task: 'hostname',
    nonce: 'ff00',
  });
  assert.match(script, /export DSH_HOME='\/home\/zabz\/\.dsh-worker'/);
  assert.match(script, /^cd '\/home\/zabz\/code'$/m);
  assert.match(script, /FANOUT_BEGIN_ff00/);
  assert.match(script, /exit \$fanout_exit/);
});

test('parseFanout reads the transport facts, the answer, and the exit code', () => {
  const nonce = 'abcd1234';
  const m = markers(nonce);
  const stdout = [
    'Windows PowerShell',
    'Copyright (C) Microsoft Corporation. All rights reserved.',
    `${m.host}ZABZ-YOGA`,
    `${m.cwd}C:\\Users\\ezabz`,
    m.begin,
    'CHILD_HOST=ZABZ-YOGA',
    'CHILD_FILE=LAPTOP-MARKER',
    'TOKEN=REMOTE-CHILD-1',
    m.end,
    `${m.exit}0`,
  ].join('\r\n');
  const parsed = parseFanout(stdout, nonce);
  assert.equal(parsed.host, 'ZABZ-YOGA');
  assert.equal(parsed.cwd, 'C:\\Users\\ezabz');
  assert.equal(parsed.exitCode, 0);
  assert.equal(parsed.framed, true);
  assert.equal(parsed.answer, 'CHILD_HOST=ZABZ-YOGA\nCHILD_FILE=LAPTOP-MARKER\nTOKEN=REMOTE-CHILD-1');
});

test('parseFanout refuses to frame a run whose markers never arrived', () => {
  const parsed = parseFanout('Error: dsh: cannot resolve profile bundle "x"\n', 'abcd1234');
  assert.equal(parsed.framed, false);
  assert.equal(parsed.answer, '');
  assert.equal(parsed.host, undefined);
});

test('a child that prints the marker words itself cannot truncate the frame', () => {
  const nonce = 'abcd1234';
  const m = markers(nonce);
  const stdout = [m.begin, 'FANOUT_END', 'still inside', m.end, `${m.exit}0`].join('\n');
  const parsed = parseFanout(stdout, nonce);
  assert.equal(parsed.answer, 'FANOUT_END\nstill inside');
});
