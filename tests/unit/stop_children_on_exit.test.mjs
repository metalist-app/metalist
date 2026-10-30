import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {once} from 'node:events';
import test from 'node:test';
import {setTimeout as delay} from 'node:timers/promises';

// A browser test run that is interrupted (Ctrl-C) or stopped (kill, the terminal closing)
// stops the MetaList server it started; it had left it running (found 2026-10-29: nine
// servers from Oct 27-28 still up). Windows has no POSIX signals a process can handle
// (a kill there ends the process outright), so these run on macOS and Linux.
const FIXTURE = new URL('./fixtures/stop-children-fixture.mjs', import.meta.url);
const CHILD_EXIT_POLLS = 50;
const CHILD_EXIT_POLL_MS = 100;

// `ps -p` exits 0 only while the process exists.
function isRunning(pid) {
  return spawnSync('ps', ['-p', String(pid)], {stdio: 'ignore'}).status === 0;
}

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  test(`a run stopped by ${signal} stops the server it started`, {skip: process.platform === 'win32' && 'no POSIX signals on Windows'}, async () => {
    const run = spawn(process.execPath, [FIXTURE.pathname], {stdio: ['ignore', 'pipe', 'inherit']});
    const [firstOutput] = await once(run.stdout, 'data');
    const childPid = Number(String(firstOutput).trim());
    assert.ok(Number.isInteger(childPid) && isRunning(childPid), `the child started: ${firstOutput}`);

    run.kill(signal);
    await once(run, 'exit');
    for (let poll = 0; poll < CHILD_EXIT_POLLS && isRunning(childPid); poll += 1) await delay(CHILD_EXIT_POLL_MS);
    const leftRunning = isRunning(childPid);
    if (leftRunning) process.kill(childPid, 'SIGKILL');
    assert.equal(leftRunning, false, `the child ${childPid} was left running after ${signal}`);
  });
}
