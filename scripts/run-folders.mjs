// The temporary folders the test and development runners make (browser-smoke.mjs,
// run-browser-suites.mjs, throwaway-metalist.mjs, the backup reminder suite), and how
// they go away (docs/ready-to-build/unbounded-growth-audit.md, T1-T4). A run removes its
// own folder once it is done with it, after the processes writing there have exited; a
// failed run keeps its folder as the evidence. Folders an interrupted or failed run left
// behind are removed by a later run once they are a day old: suites run in parallel, so
// a recent folder may still be in use.
//
// Only folders directly in the OS temp folder, named as mkdtemp names them for one of
// these prefixes, are ever removed.

import {lstatSync, readdirSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {basename, dirname, join, resolve} from 'node:path';

const HOURS_PER_DAY = 24;
const MINUTES_PER_HOUR = 60;
const SECONDS_PER_MINUTE = 60;
const MS_PER_SECOND = 1000;
// Folders of earlier runs younger than this may belong to a run still going.
const STALE_RUN_FOLDER_AGE_MS = HOURS_PER_DAY * MINUTES_PER_HOUR * SECONDS_PER_MINUTE * MS_PER_SECOND;
// mkdtemp appends six letters and digits to the prefix (libuv's uv_fs_mkdtemp).
const MKDTEMP_SUFFIX = '[A-Za-z0-9]{6}';
// A runner's prefix: `metalist-<what>-`.
const RUN_FOLDER_PREFIX = /^metalist-[a-z]+(?:-[a-z]+)*-$/;

function requirePrefix(prefix) {
  if (typeof prefix !== 'string' || !RUN_FOLDER_PREFIX.test(prefix)) {
    throw new Error(`A run folder prefix looks like metalist-<what>-, not ${JSON.stringify(prefix)}`);
  }
}

function runFolderName(prefix) {
  requirePrefix(prefix);
  return new RegExp(`^${prefix}${MKDTEMP_SUFFIX}$`);
}

// Refuses any path that is not one of this prefix's run folders directly in the temp folder.
export function assertRunFolder(path, prefix) {
  const name = basename(path);
  if (dirname(resolve(path)) !== resolve(tmpdir()) || !runFolderName(prefix).test(name)) {
    throw new Error(`Not a ${prefix}XXXXXX run folder in the temp folder ${tmpdir()}: ${path}`);
  }
}

export async function makeRunFolder(prefix) {
  requirePrefix(prefix);
  const path = await mkdtemp(join(tmpdir(), prefix));
  assertRunFolder(path, prefix);
  return path;
}

// Removes the run's own folder: it must exist, as nothing else removes a recent one.
export async function removeRunFolder(path, prefix) {
  assertRunFolder(path, prefix);
  await rm(path, {recursive: true});
}

// Removes this prefix's run folders last changed more than a day before `nowMs` (ms since
// the epoch), and returns their paths. Another run may be sweeping the same folders at the
// same moment, so one already gone is no longer there to remove.
export async function sweepStaleRunFolders(prefix, nowMs) {
  if (!Number.isFinite(nowMs)) throw new Error(`nowMs must be a time in ms, not ${nowMs}`);
  const pattern = runFolderName(prefix);
  const removed = [];
  for (const name of readdirSync(tmpdir())) {
    if (!pattern.test(name)) continue;
    const path = join(tmpdir(), name);
    const stats = lstatSync(path, {throwIfNoEntry: false});
    if (stats === undefined || !stats.isDirectory()) continue;
    if (nowMs - stats.mtimeMs <= STALE_RUN_FOLDER_AGE_MS) continue;
    assertRunFolder(path, prefix);
    await rm(path, {recursive: true, force: true});
    removed.push(path);
  }
  return removed;
}

function hasExited(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

// Resolves once the child process has exited; at once when it already has.
export function waitForExit(child) {
  if (hasExited(child)) return Promise.resolve();
  return new Promise(exited => child.once('exit', () => exited()));
}

// Asks the child to stop (SIGTERM), forces it (SIGKILL) after `graceMs`, and resolves only
// once it has exited, so nothing it still writes lands in a folder about to be removed.
// A child that never started (no pid: the spawn itself failed) has nothing to stop.
export async function stopAndWait(child, graceMs) {
  if (!Number.isFinite(graceMs) || graceMs < 0) throw new Error(`graceMs must be a duration, not ${graceMs}`);
  if (child.pid === undefined || hasExited(child)) return;
  const exited = waitForExit(child);
  const force = setTimeout(() => {
    if (!hasExited(child)) child.kill('SIGKILL');
  }, graceMs);
  child.kill('SIGTERM');
  await exited;
  clearTimeout(force);
}
