import assert from 'node:assert/strict';
import {mkdtemp, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';

import {assertNoLoopStalls, describeLoopStalls} from '../../scripts/browser-loop-stalls.mjs';

const STACKS = [
  '\n# Thread metalist-event-loop-watchdog ident=2 daemon=True',
  '  File "diagnostics.py", line 1, in _watch_loop\n    self._stopped.wait()\n',
  '\n# Thread MainThread ident=1 daemon=False',
  '  File "agent_tools.py", line 10, in _search_view_notes\n    for note in notes:\n',
  '  File "note_aliases.py", line 20, in from_snapshot\n    ordered.append(note_id)\n',
].join('');

const STALL = {at: '2026-11-06T18:00:00+00:00', seconds: 4.68, requests: ['POST /api2/ai/chat 3.2s', 'GET /api2/background-work 0.4s'], stacks: STACKS};

test('a stall log with no stalls is a run with none', () => {
  assert.equal(describeLoopStalls(''), null);
  assert.equal(describeLoopStalls('\n'), null);
});

test('each stall is described with its length, its requests and the main thread stack', () => {
  const message = describeLoopStalls(`${JSON.stringify(STALL)}\n${JSON.stringify({...STALL, requests: [], stacks: ''})}\n`);
  assert.match(message, /stalled 2 time\(s\) for a second or longer/);
  assert.match(message, /at 2026-11-06T18:00:00\+00:00: 4\.7 s, during POST \/api2\/ai\/chat 3\.2s, GET \/api2\/background-work 0\.4s/);
  assert.match(message, /ordered\.append\(note_id\)/);
  assert.doesNotMatch(message, /_watch_loop/);
  assert.match(message, /4\.7 s, no request active\n {4}\(stall ended before the watchdog looked: no stacks\)/);
});

test('a missing stall log passes and one with a stall fails the run', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'loop-stalls-'));
  await assertNoLoopStalls(join(directory, 'absent.jsonl'));
  const path = join(directory, 'loop-stalls.jsonl');
  await writeFile(path, `${JSON.stringify(STALL)}\n`);
  await assert.rejects(assertNoLoopStalls(path), error => error.message.includes('stalled 1 time(s)') && error.message.includes(path));
});
