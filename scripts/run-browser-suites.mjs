// Runs the whole browser smoke in parallel: `core` (the full smoke's own steps) and every
// focused suite once, several at a time. Each run already has its own server, free ports
// and temporary namespace (browser-smoke.mjs), so runs cannot disturb one another or the
// user's own MetaList.
//
//   node scripts/run-browser-suites.mjs --browser chrome --workers 6
//   node scripts/run-browser-suites.mjs --browser firefox --workers 2 --shard 3/10
//
// --shard i/n runs only the i-th of n slices, so n machines can share the suites (the
// browser-suites CI workflow). The suites are dealt out in turn, slowest first, so each
// slice gets its share of the long ones.
//
// Every output line is prefixed with the seconds since its run started, so slow steps show.
// Exits non-zero when any run failed, after all runs have finished, and prints each failed
// run's log path and last lines. The logs' folder is removed when every run passed and kept
// when one failed (run-folders.mjs); earlier runners' folders a day old are removed at start.
// Stopped by a signal, it stops its runs first (each stops its own MetaList server), so
// none is left running.
import {spawn} from 'node:child_process';
import {writeFile} from 'node:fs/promises';
import {createWriteStream} from 'node:fs';
import {constants} from 'node:os';
import {join} from 'node:path';
import {parseArgs} from 'node:util';
import {FOCUSED_SUITES} from './browser-suite-names.mjs';
import {makeRunFolder, removeRunFolder, stopAndWait, sweepStaleRunFolders} from './run-folders.mjs';

const CORE = 'core';
// The longest runs (from timed runs, 2026-10-18) start first, so no worker is left
// running one of them alone at the end. Only the order depends on this list: a suite
// missing from it still runs, after these.
// Suites that measure how fast MetaList answers (input-target types 50 ms after a
// click, faster than a person but slower than the ~20 ms in which a note switch takes
// no keys) run alone after the others: sharing the CPU with other runs makes the app
// slower than those budgets, and loosening them would let a real slowdown pass.
const RUN_ALONE = ['input-target'];
const SLOWEST_FIRST = ['exit-edit-scroll', 'click-caret', 'ai-note-tags', CORE, 'sorted-tabs',
  'delete-warning', 'list-edges', 'editable-embeds'];
// A run that takes longer than this is stuck: it is stopped and reported as failed.
const RUN_TIMEOUT_MS = 30 * 60 * 1000;
// A timed-out run gets SIGTERM, so it stops its MetaList server (stop-children-on-exit.mjs),
// then SIGKILL this much later if it is still running.
const STOP_GRACE_MS = 10 * 1000;
const MS_PER_SECOND = 1000;
// How many of a failed run's last lines the summary prints.
const FAILURE_TAIL_LINES = 25;
const BROWSERS = ['chrome', 'firefox'];
// Wide enough for the seconds prefix up to 9999.9s, so log lines stay aligned.
const SECONDS_COLUMN_WIDTH = 6;
const RUN_FOLDER_PREFIX = 'metalist-browser-suites-';
// The signals that end the runner (stop-children-on-exit.mjs); it then exits as the signal
// would have ended it, with 128 plus the signal's number.
const EXIT_SIGNALS = ['SIGINT', 'SIGTERM', 'SIGHUP'];
const SIGNAL_EXIT_BASE = 128;

const {values: options} = parseArgs({options: {browser: {type: 'string'}, workers: {type: 'string'}, shard: {type: 'string'}}});
if (!BROWSERS.includes(options.browser)) throw new Error(`--browser must be one of ${BROWSERS.join(', ')}`);
if (options.workers === undefined || !/^[1-9][0-9]*$/.test(options.workers)) {
  throw new Error('--workers must be a positive whole number (6 suits an 8-core machine)');
}
const workerCount = Number(options.workers);
// Which slice of the suites to run: all of them unless --shard i/n says otherwise.
let shard = {index: 1, count: 1};
if (options.shard !== undefined) {
  const match = /^(?<index>[1-9][0-9]*)\/(?<count>[1-9][0-9]*)$/.exec(options.shard);
  if (match === null) throw new Error('--shard must be i/n, for example 3/10');
  shard = {index: Number(match.groups.index), count: Number(match.groups.count)};
  if (shard.index > shard.count) throw new Error('--shard i/n needs i no larger than n');
}

await sweepStaleRunFolders(RUN_FOLDER_PREFIX, Date.now());
const directory = await makeRunFolder(RUN_FOLDER_PREFIX);
const startedAt = performance.now();

// On a signal, the runs going now (`running`) are stopped and waited for, so each stops its
// own server, before the runner exits.
function stopRunsOnExitSignals(running) {
  for (const signal of EXIT_SIGNALS) {
    process.once(signal, async () => {
      await Promise.all([...running].map(child => stopAndWait(child, STOP_GRACE_MS)));
      process.exit(SIGNAL_EXIT_BASE + constants.signals[signal]);
    });
  }
}

function seconds(fromMs) {
  return ((performance.now() - fromMs) / MS_PER_SECOND).toFixed(1);
}

// Runs one suite to the end, in `running` while it goes; resolves with its outcome, never rejects.
function runSuite(suite, running) {
  const logPath = join(directory, `${suite}.log`);
  const log = createWriteStream(logPath);
  const runStartedAt = performance.now();
  const env = {...process.env, BROWSER_TEST_BROWSER: options.browser, BROWSER_TEST_SUITE: suite};
  const child = spawn(process.execPath, ['scripts/browser-smoke.mjs'], {env, stdio: ['ignore', 'pipe', 'pipe']});
  running.add(child);
  child.once('exit', () => running.delete(child));
  const tail = [];
  let pending = '';
  const write = chunk => {
    pending += chunk;
    const lines = pending.split('\n');
    pending = lines.pop();
    for (const line of lines) {
      const stamped = `[${seconds(runStartedAt).padStart(SECONDS_COLUMN_WIDTH)}s] ${line}`;
      log.write(`${stamped}\n`);
      tail.push(stamped);
      if (tail.length > FAILURE_TAIL_LINES) tail.shift();
    }
  };
  child.stdout.on('data', write);
  child.stderr.on('data', write);
  const timer = setTimeout(() => {
    child.kill('SIGTERM');
    setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    }, STOP_GRACE_MS).unref();
  }, RUN_TIMEOUT_MS);
  // Resolves once the log file is closed too: Windows cannot remove an open file.
  return new Promise(resolve => child.on('close', (code, signal) => {
    clearTimeout(timer);
    if (pending !== '') write('\n');
    const outcome = {suite, passed: code === 0, code, signal, seconds: seconds(runStartedAt), logPath, tail};
    log.once('close', () => resolve(outcome));
    log.end();
  }));
}

// Runs the suites `workers` at a time, each worker taking the next waiting suite.
async function runAll(suites, workers, running) {
  const waiting = [...suites];
  const finished = [];
  const worker = async () => {
    while (waiting.length > 0) {
      const result = await runSuite(waiting.shift(), running);
      finished.push(result);
      console.log(`${result.passed ? 'PASS' : 'FAIL'} ${result.suite} in ${result.seconds}s (${finished.length}/${suites.length})`);
    }
  };
  await Promise.all(Array.from({length: workers}, worker));
  return finished;
}

const allSuites = [CORE, ...FOCUSED_SUITES];
for (const suite of [...SLOWEST_FIRST, ...RUN_ALONE]) {
  if (!allSuites.includes(suite)) throw new Error(`SLOWEST_FIRST or RUN_ALONE names an unknown suite: ${suite}`);
}
// Dealt out in turn from the slowest, so every slice gets its share of the long runs.
const inShard = (_suite, position) => position % shard.count === shard.index - 1;
const ordered = [...SLOWEST_FIRST, ...allSuites.filter(suite => !SLOWEST_FIRST.includes(suite))];
const shardSuites = ordered.filter(inShard);
const parallelSuites = shardSuites.filter(suite => !RUN_ALONE.includes(suite));
const aloneSuites = shardSuites.filter(suite => RUN_ALONE.includes(suite));
let aloneNote = '';
if (aloneSuites.length > 0) aloneNote = ` and then ${aloneSuites.join(', ')} alone`;
console.log(`Running ${shardSuites.length} of ${allSuites.length} browser runs (slice ${shard.index}/${shard.count}) `
  + `in ${options.browser}, ${workerCount} at a time${aloneNote}; logs in ${directory}`);
const runningSuites = new Set();
stopRunsOnExitSignals(runningSuites);
const results = [...await runAll(parallelSuites, workerCount, runningSuites), ...await runAll(aloneSuites, 1, runningSuites)];

const failed = results.filter(result => !result.passed);
const summary = results
  .sort((first, second) => Number(second.seconds) - Number(first.seconds))
  .map(result => `${result.passed ? 'PASS' : 'FAIL'} ${result.suite} ${result.seconds}s`)
  .join('\n');
await writeFile(join(directory, 'summary.txt'), `${summary}\n`);
console.log(`\nAll runs finished in ${seconds(startedAt)}s; slowest first:\n${summary}`);
for (const result of failed) {
  console.log(`\nFAILED ${result.suite} (exit code ${result.code}, signal ${result.signal}), log: ${result.logPath}\n${result.tail.join('\n')}`);
}
if (failed.length > 0) {
  console.log(`\n${failed.length} of ${results.length} runs failed; logs kept in ${directory}`);
  process.exitCode = 1;
} else {
  await removeRunFolder(directory, RUN_FOLDER_PREFIX);
}
