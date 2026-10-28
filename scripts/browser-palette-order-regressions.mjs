import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// The command palette keeps its order while it is open (docs/ui/command-palette.md; agreed
// 2026-10-27, "keep the user's point of attention still"). It ranks its rows by how often
// each was used; cycling Stats Style used to count at once, so the row jumped up under the
// pointer. The cases agreed with the user:
//   1. Enter on a setting: every row stays where it was, and so does the highlight
//   2. several commands in a row with the palette open: the order never changes
//   3. editing the keywords while it is open: rows sort as they did at opening
//   4. the suggested keywords under the input keep their order too
//   5. closed and opened again: the new uses count (Stats Style moves above Theme)
// Theme and Stats Style are each cycled through all their values, so both end as they began.

const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
// Both settings carry this keyword (command_palette_tags.json).
const QUERY = 'appearance';
const THEME = 'pref.theme';
const STATS_STYLE = 'pref.stats_style';
// Each setting's number of values: cycling that many times brings it back.
const THEME_VALUE_COUNT = 3;
const STATS_STYLE_VALUE_COUNT = 3;

async function settle(page) {
  await page.evaluate(frames => new Promise(resolve => {
    const step = left => (left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1)));
    step(frames);
  }), FRAMES_TO_SETTLE);
}

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await settle(page);
}

async function openWith(page, query) {
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.open();
  });
  await page.waitForSelector('#command-palette-input', {visible: true});
  await page.type('#command-palette-input', query);
  await idle(page);
}

async function close(page) {
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.querySelector('#command-palette-input') === null
    || document.getElementById('command-palette-modal').style.display === 'none');
  await idle(page);
}

// What the palette shows: its rows in order, the highlighted one, and the suggested keywords.
function shown(page) {
  return page.evaluate(() => ({
    rows: [...document.querySelectorAll('#command-palette-results [data-endpoint-id]')].map(row => row.dataset.endpointId),
    selected: document.querySelector('#command-palette-results .command-palette-row.selected').dataset.endpointId,
    suggestions: [...document.querySelectorAll('#command-palette-suggestions .command-palette-suggestion')].map(word => word.textContent),
  }));
}

async function highlight(page, endpointId) {
  const {rows} = await shown(page);
  const index = rows.indexOf(endpointId);
  assert.ok(index >= 0, `${endpointId} is listed for "${QUERY}"`);
  for (let step = 0; step < index; step += 1) await page.keyboard.press('ArrowDown');
  await settle(page);
  assert.equal((await shown(page)).selected, endpointId);
}

async function press(page, times) {
  for (let count = 0; count < times; count += 1) {
    await page.keyboard.press('Enter');
    await idle(page);
  }
}

async function orderCases(page) {
  // Theme gets 3 uses and Stats Style none, so Theme is listed above it. One use per
  // opening, as anyone would before this was fixed: the row moved after each use.
  for (let use = 0; use < THEME_VALUE_COUNT; use += 1) {
    await openWith(page, QUERY);
    await highlight(page, THEME);
    await press(page, 1);
    await close(page);
  }

  await openWith(page, QUERY);
  const opened = await shown(page);
  assert.ok(opened.rows.indexOf(THEME) < opened.rows.indexOf(STATS_STYLE), `Theme above Stats Style: ${opened.rows}`);
  await highlight(page, STATS_STYLE);
  const before = await shown(page);

  // Cases 1 and 2: three uses, each one counted, and nothing moves.
  await press(page, STATS_STYLE_VALUE_COUNT);
  assert.deepEqual(await shown(page), before, 'cycling Stats Style moved the rows');

  // Cases 3 and 4: editing the keywords sorts and suggests as at opening.
  await page.keyboard.press('Backspace');
  await idle(page);
  await page.keyboard.type(QUERY.at(-1));
  await idle(page);
  const edited = await shown(page);
  assert.deepEqual({rows: edited.rows, suggestions: edited.suggestions}, {rows: before.rows, suggestions: before.suggestions},
    'editing the keywords reordered the rows');
  await close(page);

  // Case 5: opened again, the new uses count.
  await openWith(page, QUERY);
  const reopened = await shown(page);
  assert.ok(reopened.rows.indexOf(STATS_STYLE) < reopened.rows.indexOf(THEME), `Stats Style above Theme: ${reopened.rows}`);
  await close(page);
}

export async function checkPaletteOrder(page) {
  await idle(page);
  const initial = await page.evaluate(() => ({
    theme: document.documentElement.getAttribute('data-theme'),
    statsStyle: document.documentElement.dataset.statsStyle,
  }));
  await runThenCleanUp('palette order', () => orderCases(page), async () => {
    const final = await page.evaluate(() => ({
      theme: document.documentElement.getAttribute('data-theme'),
      statsStyle: document.documentElement.dataset.statsStyle,
    }));
    // Cycled through all their values, both settings are as they began.
    assert.deepEqual(final, initial);
  });
}
