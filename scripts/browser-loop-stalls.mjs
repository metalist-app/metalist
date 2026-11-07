// The stall gate of every browser run (PLAN.md, scale testing, part 2): the server lists
// each time its event loop stalled for a second or longer in the file METALIST_LOOP_STALL_LOG
// names (app/services/diagnostics.py, one JSON line per stall), and a run with any stall
// fails, naming what was running. 0.26.0 held the loop for 100 s under tests that passed.

import {readFile} from 'node:fs/promises';

// The lines of a stalled thread's stack shown per stall: enough to name the code holding
// the loop, not the whole dump (which stays in the file).
const STACK_LINES_SHOWN = 12;
const MAIN_THREAD_HEADING = '# Thread MainThread';

function stackOfMainThread(stacks) {
  const start = stacks.indexOf(MAIN_THREAD_HEADING);
  if (start === -1) return '    (stall ended before the watchdog looked: no stacks)';
  const rest = stacks.slice(start + MAIN_THREAD_HEADING.length);
  const end = rest.indexOf('\n# Thread ');
  const lines = (end === -1 ? rest : rest.slice(0, end)).split('\n').filter(line => line.trim() !== '');
  return lines.slice(-STACK_LINES_SHOWN).map(line => `    ${line.trimEnd()}`).join('\n');
}

// The failure message for the stalls in a stall log's text, or null when it holds none.
export function describeLoopStalls(text) {
  const stalls = text.split('\n').filter(line => line.trim() !== '').map(line => JSON.parse(line));
  if (stalls.length === 0) return null;
  const details = stalls.map(stall => {
    const during = stall.requests.length === 0 ? 'no request active' : `during ${stall.requests.join(', ')}`;
    return `  at ${stall.at}: ${stall.seconds.toFixed(1)} s, ${during}\n${stackOfMainThread(stall.stacks)}`;
  });
  return `The server's event loop stalled ${stalls.length} time(s) for a second or longer; MetaList answered nothing meanwhile:\n${details.join('\n')}`;
}

// Fails the run when the stall log at path lists any stall; a missing file is a run with none.
export async function assertNoLoopStalls(path) {
  let text;
  try {
    text = await readFile(path, 'utf8');
  } catch (error) { // shockharness: ignore[EXC001] reason="a server that never stalled wrote no file; any other error is rethrown"
    if (error.code !== 'ENOENT') throw error;
    return;
  }
  const message = describeLoopStalls(text);
  if (message !== null) throw new Error(`${message}\n(the whole record: ${path})`);
}
