import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';

// Changing Theme cross-fades the page over 300 ms (docs/ui/command-palette.md, Animated
// transitions; agreed 2026-10-27): one fade of the whole page per change, in each direction;
// none with Animated transitions off; and changing it again mid-fade (Enter cycles Theme)
// skips the first fade without an error and ends on the last theme. Each change is sampled
// every frame until its fade has ended.

const FADE_MS = 300;
const SAMPLE_MS = 600;
const ONE_FADE = [
  `::view-transition-new(root) ${FADE_MS}`, `::view-transition-new(root) ${FADE_MS}`,
  `::view-transition-old(root) ${FADE_MS}`, `::view-transition-old(root) ${FADE_MS}`,
];

async function applyPreference(page, key, value) {
  await page.evaluate(async ({key, value}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference(key, value);
  }, {key, value});
}

// Setting a preference to the value it has is refused, so only a change is made.
async function setAnimatedTransitions(page, isOn) {
  const isOnNow = await page.evaluate(() => document.body.classList.contains('pref-animated-transitions'));
  if (isOnNow !== isOn) await applyPreference(page, 'pref.animated_transitions', isOn);
}

// The page's own view-transition animations, sampled every frame while the theme changes.
// An earlier change's fade (the setup's, the case before) ends first, so only this one counts.
async function changeTheme(page, themes) {
  return page.evaluate(async ({themes, sampleMs}) => {
    // A fade's animations start a frame or two after its change; wait for those to show first.
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().map(animation => animation.finished));
    const fades = new Set();
    const start = performance.now();
    await new Promise(resolve => {
      const sample = () => {
        for (const animation of document.getAnimations()) {
          // Only the page's own fade: animations on its old and new snapshots.
          if (animation.effect === null || animation.effect.pseudoElement === null) continue;
          const pseudo = animation.effect.pseudoElement;
          if (pseudo.startsWith('::view-transition-old(root)') || pseudo.startsWith('::view-transition-new(root)')) {
            fades.add(animation);
          }
        }
        if (performance.now() - start < sampleMs) requestAnimationFrame(sample);
        else resolve();
      };
      requestAnimationFrame(sample);
      const {CommandPalette} = window.__themeFadePalette;
      for (const theme of themes.slice(0, -1)) void CommandPalette.applyPreference('pref.theme', theme);
      void CommandPalette.applyPreference('pref.theme', themes.at(-1));
    });
    return {
      theme: document.documentElement.getAttribute('data-theme'),
      fades: [...fades].map(animation => ({pseudo: animation.effect.pseudoElement, duration: animation.effect.getTiming().duration})),
      hasErrorOverlay: document.getElementById('fatal-error-overlay') !== null,
    };
  }, {themes, sampleMs: SAMPLE_MS});
}

async function themeCases(page) {
  await page.evaluate(async () => {
    window.__themeFadePalette = await import('/static/js/modules/command-palette/command-palette-controller.js');
  });
  const failures = [];
  const cases = [
    ['to Dark fades the page once', true, ['dark'], 'dark', true],
    ['to Light fades the page once', true, ['light'], 'light', true],
    ['with Animated transitions off it switches at once', false, ['dark'], 'dark', false],
    ['two quick changes end on the last theme without an error', true, ['light', 'dark'], 'dark', null],
  ];
  for (const [label, isAnimated, themes, expectedTheme, isOneFade] of cases) {
    await setAnimatedTransitions(page, isAnimated);
    const outcome = await changeTheme(page, themes);
    // A suite runs every case and reports all their failures at once.
    try {
      assertThemeChange(outcome, expectedTheme, isOneFade);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  }
  assert.deepEqual(failures, []);
}

// isOneFade: true for exactly one fade, false for none, null when the count doesn't matter.
function assertThemeChange(outcome, expectedTheme, isOneFade) {
  assert.equal(outcome.theme, expectedTheme);
  assert.equal(outcome.hasErrorOverlay, false);
  if (isOneFade === true) {
    // One fade: the browser animates the old snapshot and the new one, two animations each.
    assert.deepEqual(outcome.fades.map(fade => `${fade.pseudo} ${fade.duration}`).sort(), ONE_FADE);
  } else if (isOneFade === false) {
    assert.deepEqual(outcome.fades, []);
  }
}

export async function checkThemeFade(page) {
  // The cases start from Light, set without a fade of its own.
  await setAnimatedTransitions(page, false);
  await applyPreference(page, 'pref.theme', 'light');
  await runThenCleanUp('theme fade', () => themeCases(page), async () => {
    await setAnimatedTransitions(page, true);
    await page.evaluate(async () => {
      const {CommandPalette} = window.__themeFadePalette;
      if (document.documentElement.getAttribute('data-theme') !== null) await CommandPalette.applyPreference('pref.theme', 'system');
    });
  });
}
