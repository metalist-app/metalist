// A script's child processes (a throwaway MetaList server) end with it. Node exits at once
// on SIGINT (Ctrl-C), SIGTERM (kill, a test runner's timeout) or SIGHUP (the terminal
// closing), skipping `finally` blocks, so a server they would stop kept running (found
// 2026-10-29: nine from browser test runs). On one of these signals the children are
// killed and the script exits as the signal would have ended it. Windows has no such
// signals: a kill there ends the process outright.

import {constants} from 'node:os';

const EXIT_SIGNALS = ['SIGINT', 'SIGTERM', 'SIGHUP'];
// A process ended by a signal exits with 128 plus the signal's number, as shells report it.
const SIGNAL_EXIT_BASE = 128;

export function stopChildrenOnExitSignals(children) {
  if (!Array.isArray(children) || children.length === 0) {
    throw new Error('stopChildrenOnExitSignals requires the child processes to stop');
  }
  for (const signal of EXIT_SIGNALS) {
    process.once(signal, () => {
      for (const child of children) {
        if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
      }
      process.exit(SIGNAL_EXIT_BASE + constants.signals[signal]);
    });
  }
}
