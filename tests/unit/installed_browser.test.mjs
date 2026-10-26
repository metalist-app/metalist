import assert from 'node:assert/strict';
import test from 'node:test';

import { browserCandidates, installedBrowserExecutable } from '../../scripts/installed-browser.mjs';

// The local browser suites run in the browser CI's jobs use: the installed one, looked up
// in the same places as scripts/smoke_installed_package.py (_browser_candidates).

test('macOS looks in Applications', () => {
  assert.deepEqual(browserCandidates('chrome', 'darwin', {}), ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']);
  assert.deepEqual(browserCandidates('firefox', 'darwin', {}), ['/Applications/Firefox.app/Contents/MacOS/firefox']);
});

test('Windows looks in the program folders that are set', () => {
  const candidates = browserCandidates('chrome', 'win32', { ProgramFiles: 'C:/Program Files', LOCALAPPDATA: 'C:/Users/me/AppData/Local' });
  assert.equal(candidates.length, 2);
  assert.match(candidates[0].replaceAll('\\', '/'), /^C:\/Program Files\/Google\/Chrome\/Application\/chrome\.exe$/);
  assert.match(candidates[1].replaceAll('\\', '/'), /^C:\/Users\/me\/AppData\/Local\/Google\/Chrome\/Application\/chrome\.exe$/);
});

test('Linux looks for google-chrome on the search path', () => {
  const candidates = browserCandidates('chrome', 'linux', { PATH: ['/usr/bin', '/opt/bin'].join(process.platform === 'win32' ? ';' : ':') });
  assert.deepEqual(candidates.map((path) => path.replaceAll('\\', '/')),
    ['/usr/bin/google-chrome', '/opt/bin/google-chrome', '/usr/bin/google-chrome-stable', '/opt/bin/google-chrome-stable']);
});

test('a named executable wins, and a missing browser stops the run', () => {
  assert.equal(installedBrowserExecutable('chrome', { BROWSER_TEST_EXECUTABLE: '/somewhere/chrome' }), '/somewhere/chrome');
  assert.throws(() => browserCandidates('edge', 'darwin', {}), /No installed-browser lookup for edge/);
});
