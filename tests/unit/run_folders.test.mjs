import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {existsSync, mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {after, test} from 'node:test';

import {assertRunFolder, makeRunFolder, removeRunFolder, stopAndWait, sweepStaleRunFolders, waitForExit} from '../../scripts/run-folders.mjs';

// The test and development runners' temporary folders go away (docs/ready-to-build/
// unbounded-growth-audit.md, T1-T4): a run removes its own once its processes have exited,
// and folders of earlier runs a day old. The OS temp folder is pointed at a scratch folder
// here, so nothing in the real one is touched.
const scratch = mkdtempSync(join(tmpdir(), 'run-folders-test-'));
for (const name of ['TMPDIR', 'TEMP', 'TMP']) process.env[name] = scratch;
after(() => rmSync(scratch, {recursive: true}));

const PREFIX = 'metalist-browser-';
const DAY_MS = 24 * 60 * 60 * 1000;
const NOW_MS = Date.now();
const GRACE_MS = 300;
// A child that takes this long to stop after SIGTERM, writing a file as it goes.
const SLOW_STOP_MS = 200;
const KEEP_ALIVE_MS = 1000;
const NO_POSIX_SIGNALS = process.platform === 'win32' && 'no POSIX signals on Windows: a kill ends the process outright';

// A folder last changed `ageMs` ago, holding a file (writing it changes the folder's time,
// so the time is set after).
function folderAged(name, ageMs) {
  const path = join(scratch, name);
  mkdirSync(path);
  writeFileSync(join(path, 'server.log'), 'evidence of a run');
  const seconds = (NOW_MS - ageMs) / 1000;
  utimesSync(path, seconds, seconds);
  return path;
}

test('the temp folder used here is the scratch folder', () => {
  assert.equal(tmpdir(), scratch);
});

test('a run makes its folder in the temp folder and removes it', async () => {
  const folder = await makeRunFolder(PREFIX);
  assert.match(folder, /metalist-browser-[A-Za-z0-9]{6}$/);
  writeFileSync(join(folder, 'notes.db'), 'vault');
  await removeRunFolder(folder, PREFIX);
  assert.equal(existsSync(folder), false);
});

test('removing a run folder that is already gone fails loudly', async () => {
  const folder = await makeRunFolder(PREFIX);
  await removeRunFolder(folder, PREFIX);
  await assert.rejects(removeRunFolder(folder, PREFIX), {code: 'ENOENT'});
});

test('nothing but a run folder directly in the temp folder is ever removed', async () => {
  // Refused before anything is looked at, so this folder need not exist.
  const outside = join(process.cwd(), 'metalist-browser-abc123');
  await assert.rejects(removeRunFolder(outside, PREFIX), /Not a metalist-browser-XXXXXX run folder/);
  const own = await makeRunFolder(PREFIX);
  const nested = join(own, 'metalist-browser-abc123');
  mkdirSync(nested);
  await assert.rejects(removeRunFolder(nested, PREFIX), /Not a metalist-browser-XXXXXX run folder/);
  await assert.rejects(removeRunFolder(own, 'metalist-browser-suites-'), /Not a metalist-browser-suites-XXXXXX/);
  assert.throws(() => assertRunFolder(join(scratch, 'metalist-browser-results'), PREFIX), /Not a/);
  assert.ok(existsSync(nested));
  await removeRunFolder(own, PREFIX);
});

test('a prefix must look like metalist-<what>-', async () => {
  for (const prefix of ['', 'metalist', 'metalist-', 'other-browser-', 'metalist-browser', '../metalist-x-']) {
    await assert.rejects(makeRunFolder(prefix), /A run folder prefix looks like metalist-<what>-/);
  }
});

test('the sweep removes only this prefix\'s folders older than a day', async () => {
  const stale = folderAged('metalist-browser-aaaaaa', 2 * DAY_MS);
  const recent = folderAged('metalist-browser-bbbbbb', DAY_MS / 2);
  const otherRunner = folderAged('metalist-browser-suites-cccccc', 2 * DAY_MS);
  const notMkdtemp = folderAged('metalist-browser-results', 2 * DAY_MS);
  const aFile = join(scratch, 'metalist-browser-dddddd');
  writeFileSync(aFile, 'not a folder');
  const fileTime = (NOW_MS - 2 * DAY_MS) / 1000;
  utimesSync(aFile, fileTime, fileTime);

  assert.deepEqual(await sweepStaleRunFolders(PREFIX, NOW_MS), [stale]);
  assert.equal(existsSync(stale), false);
  for (const kept of [recent, otherRunner, notMkdtemp, aFile]) assert.ok(existsSync(kept), `${kept} is kept`);
  assert.deepEqual(await sweepStaleRunFolders(PREFIX, NOW_MS), [], 'a second sweep finds nothing to remove');
  for (const kept of [recent, otherRunner, notMkdtemp, aFile]) rmSync(kept, {recursive: true});
});

test('waiting for a process that has exited resolves at once', async () => {
  const child = spawn(process.execPath, ['-e', ''], {stdio: 'ignore'});
  await once(child, 'exit');
  await waitForExit(child);
  await stopAndWait(child, GRACE_MS);
  assert.equal(child.exitCode, 0);
});

test('stopping waits until the process has exited', async () => {
  const child = spawn(process.execPath, ['-e', `setInterval(() => {}, ${KEEP_ALIVE_MS})`], {stdio: 'ignore'});
  await stopAndWait(child, GRACE_MS);
  assert.ok(child.exitCode !== null || child.signalCode !== null, 'the process has exited');
});

test('a process still writing as it stops is waited for before its folder goes', {skip: NO_POSIX_SIGNALS}, async () => {
  const folder = await makeRunFolder(PREFIX);
  const lastWrite = join(folder, 'last-write.txt');
  const script = `process.on('SIGTERM', () => setTimeout(() => { require('fs').writeFileSync(${JSON.stringify(lastWrite)}, 'bye'); process.exit(0); }, ${SLOW_STOP_MS}));
    setInterval(() => {}, ${KEEP_ALIVE_MS}); console.log('ready');`;
  const child = spawn(process.execPath, ['-e', script], {stdio: ['ignore', 'pipe', 'inherit']});
  await once(child.stdout, 'data');
  await stopAndWait(child, KEEP_ALIVE_MS);
  assert.equal(child.exitCode, 0);
  assert.ok(existsSync(lastWrite), 'its last write landed before stopping returned');
  await removeRunFolder(folder, PREFIX);
  assert.equal(existsSync(folder), false);
});

test('a process that ignores SIGTERM is killed after the grace period, then waited for', {skip: NO_POSIX_SIGNALS}, async () => {
  const script = `process.on('SIGTERM', () => {}); setInterval(() => {}, ${KEEP_ALIVE_MS}); console.log('ready');`;
  const child = spawn(process.execPath, ['-e', script], {stdio: ['ignore', 'pipe', 'inherit']});
  await once(child.stdout, 'data');
  const started = performance.now();
  await stopAndWait(child, GRACE_MS);
  assert.equal(child.signalCode, 'SIGKILL');
  assert.ok(performance.now() - started >= GRACE_MS, 'it had the grace period to stop');
});

test('a process that never started has nothing to stop', async () => {
  const child = spawn(join(scratch, 'no-such-program'), [], {stdio: 'ignore'});
  const [error] = await once(child, 'error');
  assert.equal(error.code, 'ENOENT');
  await stopAndWait(child, GRACE_MS);
});
