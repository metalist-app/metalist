import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';

// The login screen fades out over the notes (docs/ui/login-screen.md, After login; agreed
// 2026-10-27): the notes show underneath at once; once the progress bar has visibly filled,
// the screen fades out over 300 ms, covering the floating buttons and cards until it has gone
// so everything appears together, with the logo and the notes standing still and a click
// reaching the notes. With Animated transitions off the screen goes at once. Each login is
// sampled every frame, from the click on Log In until the screen has gone.

const WINDOW = {width: 1100, height: 700};
// A test-only password for this suite's own disposable vault.
const PASSWORD = 'Login-fade-only-password!2026';
const FADE_MS = 300;
// Frames fall on a 16.7 ms grid: a 300 ms fade spans at least this long between samples.
const SHORTEST_SAMPLED_FADE_MS = FADE_MS - 2 * 17;
const COVERING_Z_INDEX = '21000';
const LOGIN_TIMEOUT_MS = 30_000;

async function seedNotes(page) {
  return page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    for (const text of ['Plan the week', 'Garden plan', 'Groceries']) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<p>${text}</p>`, '');
      ids.push(note.id);
    }
    return ids;
  });
}

async function setAnimatedTransitions(page, isOn) {
  await page.evaluate(async isOn => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference('pref.animated_transitions', isOn);
  }, isOn);
}

// Records, every frame, the login screen, its progress bar and logo, and the first note.
async function startSampling(page) {
  await page.evaluate(() => {
    const samples = [];
    window.__loginFadeSamples = samples;
    const round = value => Math.round(value * 10) / 10;
    const sample = () => {
      const login = document.getElementById('login-page');
      const app = document.getElementById('main-app');
      const style = getComputedStyle(login);
      const bar = document.getElementById('login-progress-bar').getBoundingClientRect();
      const track = document.getElementById('login-progress-bar').parentElement.getBoundingClientRect();
      const note = document.querySelector('.note > .note-content');
      const noteBox = note === null ? null : note.getBoundingClientRect();
      const hit = noteBox === null ? null : document.elementFromPoint(noteBox.left + noteBox.width / 2, noteBox.top + noteBox.height / 2);
      samples.push({
        time: performance.now(),
        isAppShown: app.style.display === 'block',
        isLoginShown: style.display !== 'none',
        isLeaving: login.classList.contains('login-page-leaving'),
        isCovering: login.classList.contains('login-page-covering'),
        opacity: Number(style.opacity),
        zIndex: style.zIndex,
        barFill: track.width === 0 ? null : round(bar.width / track.width),
        logoLeft: round(document.getElementById('login-logo').getBoundingClientRect().left),
        noteLeft: noteBox === null ? null : round(noteBox.left),
        isClickOnNote: hit !== null && note.contains(hit),
        scrollbarGutter: getComputedStyle(document.documentElement).scrollbarGutter,
      });
      if (style.display !== 'none' || !app.style.display) requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
}

async function logIn(page) {
  await page.waitForSelector('#login-panel[data-revealed="true"] #login-password', {visible: true});
  await page.type('#login-password', PASSWORD);
  await startSampling(page);
  await page.click('#login-form button[type="submit"]');
  await page.waitForSelector('[data-app-ready="true"]', {timeout: LOGIN_TIMEOUT_MS});
  await page.waitForFunction(() => getComputedStyle(document.getElementById('login-page')).display === 'none');
  return page.evaluate(() => window.__loginFadeSamples);
}

async function logOut(page) {
  await page.evaluate(async () => {
    const {Auth} = await import('/static/js/modules/auth.js');
    await Auth.logout();
  });
}

// Once the notes are under it, the page keeps its scrollbar strip, so the notes lay out
// at their final width before anything shows (the release startup check reads it the
// moment the app is ready; it found the strip off while the progress bar finished,
// 2026-10-28). The login screen fills the window either way, so the logo stays put.
function assertStripKeptUnderTheScreen(samples) {
  // From the moment the notes are revealed: covered by the screen, or with it gone.
  const revealed = samples.filter(sample => sample.isAppShown && (sample.isCovering || !sample.isLoginShown));
  assert.ok(revealed.length > 0, 'no sample after the notes were revealed');
  const gutters = new Set(revealed.map(sample => sample.scrollbarGutter));
  assert.deepEqual([...gutters], ['stable'], 'the scrollbar strip was off while the notes were under the screen');
}

function assertFade(samples) {
  assertStripKeptUnderTheScreen(samples);
  const shownSamples = samples.filter(sample => sample.isAppShown && sample.isLoginShown);
  const fadeSamples = shownSamples.filter(sample => sample.isLeaving);
  assert.ok(fadeSamples.length > 0, 'the login screen never faded');
  // Until it has gone, the screen covers everything, floating buttons and cards too.
  assert.deepEqual([...new Set(shownSamples.map(sample => sample.zIndex))], [COVERING_Z_INDEX]);
  // Opaque until the fade starts, with the progress bar visibly full when it does. A fast
  // machine can start the fade before a frame is sampled (Firefox in CI, 2026-10-28): then
  // there is no frame before it to check.
  const beforeFade = shownSamples.filter(sample => !sample.isLeaving).map(sample => sample.opacity);
  assert.ok(beforeFade.every(opacity => opacity === 1), `the screen was not opaque before the fade: ${beforeFade}`);
  assert.equal(fadeSamples[0].barFill, 1, 'the progress bar was not full when the fade started');
  assert.ok(fadeSamples.every((sample, index) => index === 0 || sample.opacity <= fadeSamples[index - 1].opacity), 'the fade went back');
  const hidden = samples.find(sample => sample.isAppShown && !sample.isLoginShown);
  assert.ok(hidden.time - fadeSamples[0].time >= SHORTEST_SAMPLED_FADE_MS, 'the screen went faster than a 300 ms fade');
  // The logo and the notes stand still, and a click reaches the notes.
  assert.deepEqual([...new Set(samples.filter(sample => sample.isLoginShown).map(sample => sample.logoLeft))].length, 1, 'the logo moved');
  assert.deepEqual([...new Set(fadeSamples.map(sample => sample.noteLeft))].length, 1, 'the notes moved during the fade');
  assert.ok(fadeSamples.every(sample => sample.isClickOnNote), 'a click during the fade did not reach the notes');
}

function assertNoFade(samples) {
  assertStripKeptUnderTheScreen(samples);
  assert.equal(samples.some(sample => sample.isLeaving), false, 'the screen faded with Animated transitions off');
  assert.equal(samples.some(sample => sample.isAppShown && sample.isLoginShown), false, 'the screen stayed over the notes');
}

async function fadeCases(page) {
  const failures = [];
  const cases = [
    ['fades out over the notes', true, assertFade],
    ['goes at once with Animated transitions off', false, assertNoFade],
  ];
  for (const [label, isAnimated, check] of cases) {
    await setAnimatedTransitions(page, isAnimated);
    await logOut(page);
    const samples = await logIn(page);
    // A suite runs every case and reports all their failures at once.
    try {
      check(samples);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  }
  assert.deepEqual(failures, []);
}

export async function checkLoginFade(page) {
  await page.setViewport(WINDOW);
  const ids = await seedNotes(page);
  await page.evaluate(async password => {
    const {buildSessionHeaders} = await import('/static/js/modules/session-auth.js');
    const response = await fetch('/api2/auth/settings/password/create', {method: 'POST', headers: buildSessionHeaders(true), body: JSON.stringify({password})});
    if (!response.ok) throw new Error(`Password setup failed: ${response.status}`);
  }, PASSWORD);
  await page.reload();
  await logIn(page);
  await runThenCleanUp('login fade', () => fadeCases(page), async () => {
    await setAnimatedTransitions(page, true);
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
