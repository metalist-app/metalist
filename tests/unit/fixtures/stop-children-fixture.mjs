// Starts a long-lived child the way browser-smoke starts its server, prints its pid, then
// waits to be interrupted (tests/unit/stop_children_on_exit.test.mjs).
import {spawn} from 'node:child_process';
import {stopChildrenOnExitSignals} from '../../../scripts/stop-children-on-exit.mjs';

const KEEP_ALIVE_MS = 1000;
const child = spawn(process.execPath, ['-e', `setInterval(() => {}, ${KEEP_ALIVE_MS})`], {stdio: 'ignore'});
stopChildrenOnExitSignals([child]);
console.log(child.pid);
setInterval(() => {}, KEEP_ALIVE_MS);
