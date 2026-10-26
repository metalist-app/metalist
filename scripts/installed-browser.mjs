import { existsSync } from 'node:fs';
import { delimiter, join } from 'node:path';

// The browser the local suites run in: the one installed on this computer, as CI's
// browser jobs use (scripts/smoke_installed_package.py, _browser_candidates), never
// Puppeteer's own downloaded Chrome. That copy is pinned to Puppeteer's release and fell
// years behind: on 2026-10-25 the whole suite passed in its Chrome 131 while every CI
// browser job failed in Chrome 156. BROWSER_TEST_EXECUTABLE names another one.

const WINDOWS_PATHS = {
  chrome: 'Google/Chrome/Application/chrome.exe',
  firefox: 'Mozilla Firefox/firefox.exe',
};
const WINDOWS_FOLDERS = ['ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'];
const MAC_PATHS = {
  chrome: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  firefox: '/Applications/Firefox.app/Contents/MacOS/firefox',
};
const LINUX_NAMES = {
  chrome: ['google-chrome', 'google-chrome-stable'],
  firefox: ['firefox'],
};

function onSearchPath(name, environment) {
  return environment.PATH.split(delimiter).map(folder => join(folder, name));
}

export function browserCandidates(browserName, platform, environment) {
  if (!(browserName in MAC_PATHS)) throw new Error(`No installed-browser lookup for ${browserName}`);
  if (platform === 'win32') {
    return WINDOWS_FOLDERS.filter(name => name in environment)
      .map(name => join(environment[name], WINDOWS_PATHS[browserName]));
  }
  if (platform === 'darwin') return [MAC_PATHS[browserName]];
  return LINUX_NAMES[browserName].flatMap(name => onSearchPath(name, environment));
}

export function installedBrowserExecutable(browserName, environment) {
  if ('BROWSER_TEST_EXECUTABLE' in environment) return environment.BROWSER_TEST_EXECUTABLE;
  const candidates = browserCandidates(browserName, process.platform, environment);
  const found = candidates.find(path => existsSync(path));
  if (found === undefined) {
    throw new Error(`${browserName} is not installed where CI looks for it (${candidates.join(', ')}); `
      + 'install it, or set BROWSER_TEST_EXECUTABLE to its executable');
  }
  return found;
}

// Closes the browser and lets the run end. The installed Chrome starts its crash reporter and
// Google's updater, which inherit its output pipes and outlive it: the run then waited on those
// pipes for minutes after passing, and the whole suite took 14 minutes instead of 5
// (2026-10-26). Nothing is read from them once the browser is closed.
export async function closeBrowser(browser) {
  const chrome = browser.process();
  await browser.close();
  if (chrome === null) return;
  for (const stream of [chrome.stdin, chrome.stdout, chrome.stderr]) {
    if (stream !== null) stream.destroy();
  }
}
