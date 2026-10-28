import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { clickAndSelectAll } from './browser-select-field.mjs';

// @stats and @sum, @avg, @min, @max, @count (docs/ui/content-formatting.md, Stats of a
// subtree; agreed 2026-10-27): the stats sit right under the note's own text and above its
// children, follow an edit to a note under it at once, go while the note is folded, and take
// the Stats Style chosen in the command palette (a strip, tiles or a ledger, each on a light
// accent tint). After `@sum=`, the tag bar suggests the properties used under the note. With
// nothing under a note, `@sum` reads 0 and `@avg` a dash; `@sum:calories>2000` in the search
// box finds the days over 2000 with their meals, after `@sum:` suggesting calories (agreed
// 2026-10-28, docs/ui/search-semantics.md, Stats Figures). The numbers themselves are
// checked by tests/unit/test_subtree_stats.py and tests/unit/test_stats_search.py.

const WINDOW = {width: 1100, height: 760};
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
// The stats take back the paragraph's bottom margin and start this far under its box
// (main.css, .note-content > p + .meta-stats); before, the margin left 23px.
const GAP_UNDER_PARAGRAPH_PX = 4;
const STYLES = ['strip', 'tiles', 'ledger'];

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

async function seedNotes(page) {
  return page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const diet = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(diet.id, '<p>Diet this week</p>', '@stats');
    const ids = {diet: diet.id};
    let previous = null;
    for (const [key, text, tags] of [
      ['breakfast', 'Breakfast', 'meal:calories=300 butter:fat=10'],
      ['lunch', 'Lunch', 'meal:calories=500'],
      ['dinner', 'Dinner', 'fruit:calories=200 bread:calories=400'],
    ]) {
      // The first meal goes under the diet note, each next one after the meal before.
      let note;
      if (previous === null) note = await NotesAPI.createChild(diet.id, '');
      else note = await NotesAPI.createSibling(previous, '');
      await NotesAPI.saveNote(note.id, `<p>${text}</p>`, tags);
      ids[key] = note.id;
      previous = note.id;
    }
    // Days of a food log, each a root note: one over 2000 calories, one under, one empty.
    for (const [key, text, tags, mealTags] of [
      ['bigDay', 'Big day', '@sum=calories', 'meal:calories=2400'],
      ['smallDay', 'Small day', '@sum=calories', 'meal:calories=300'],
      ['emptyDay', 'Empty day', '@sum=calories @avg=calories', null],
    ]) {
      const day = await NotesAPI.createSibling(diet.id, '');
      await NotesAPI.saveNote(day.id, `<p>${text}</p>`, tags);
      ids[key] = day.id;
      if (mealTags !== null) {
        const meal = await NotesAPI.createChild(day.id, '');
        await NotesAPI.saveNote(meal.id, '<p>Meal</p>', mealTags);
        ids[`${key}Meal`] = meal.id;
      }
    }
    return ids;
  });
}

async function reload(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
}

// The diet note's stats as shown: each group's text, and where they sit.
function stats(page, noteId) {
  return page.evaluate(noteId => {
    const content = document.querySelector(`.note[data-note-id="${noteId}"] > .note-content`);
    const panel = content.querySelector(':scope > .meta-stats');
    if (panel === null || getComputedStyle(panel).display === 'none') return null;
    const text = content.querySelector(':scope > p');
    const children = document.querySelector(`.note[data-note-id="${noteId}"] > .note-children`);
    const groups = [...panel.querySelectorAll('.meta-stats-group')].map(group => [...group.children]
      .map(part => part.textContent.replace(/\s+/g, ' ').trim()));
    return {
      groups,
      gapUnderText: Math.round(panel.getBoundingClientRect().top - text.getBoundingClientRect().bottom),
      isAboveChildren: panel.getBoundingClientRect().bottom <= children.getBoundingClientRect().top,
    };
  }, noteId);
}

// Escape closes the suggestion list first, then leaves editing.
async function leaveEditing(page) {
  while (await page.$('.note.editing') !== null) {
    await page.keyboard.press('Escape');
    await idle(page);
  }
}

async function setTags(page, noteId, tags) {
  await page.click(`.note[data-note-id="${noteId}"] > .note-content`);
  await page.waitForSelector('.note.editing .note-tag-bar-input');
  await clickAndSelectAll(page, '.note.editing .note-tag-bar-input');
  await page.keyboard.type(`${tags} `);
  await leaveEditing(page);
}

async function placeAndLiveCases(page, ids) {
  const shown = await stats(page, ids.diet);
  assert.deepEqual(shown.groups, [
    ['calories', 'Total: 1,400', 'Min: 300', 'Max: 600', 'Count: 3'],
    ['fat', 'Total: 10', 'Min: 10', 'Max: 10', 'Count: 1'],
  ]);
  assert.equal(shown.gapUnderText, GAP_UNDER_PARAGRAPH_PX, 'the stats sit right under the text');
  assert.equal(shown.isAboveChildren, true, 'the stats sit above the children');
  // An edit to a note under it shows at once, with no reload.
  await setTags(page, ids.lunch, 'meal:calories=900');
  assert.deepEqual((await stats(page, ids.diet)).groups[0], ['calories', 'Total: 1,800', 'Min: 300', 'Max: 900', 'Count: 3']);
}

async function suggestionCase(page, ids) {
  await page.click(`.note[data-note-id="${ids.diet}"] > .note-content`);
  await page.waitForSelector('.note.editing .note-tag-bar-input');
  await clickAndSelectAll(page, '.note.editing .note-tag-bar-input');
  // A click in the tag bar readies it for a new tag just after (mouse-events.js); a person
  // types later than that, so the test lets it finish and selects again before typing.
  await idle(page);
  await page.$eval('.note.editing .note-tag-bar-input', input => input.select());
  await page.keyboard.type('@stats @sum=');
  // The list for `@sum=`, not the one still open from before typing.
  await page.waitForFunction(() => {
    const list = document.querySelector('.note.editing .note-tag-suggestions');
    return list !== null && !list.hidden && list.querySelector('.note-tag-suggestion[data-tag^="@sum="]') !== null;
  });
  const entries = await page.$$eval('.note.editing .note-tag-suggestions .note-tag-suggestion', items => items.map(item => item.dataset.tag));
  assert.deepEqual(entries, ['@sum=calories', '@sum=fat'], 'the properties under the note, the most used first');
  await clickAndSelectAll(page, '.note.editing .note-tag-bar-input');
  await page.keyboard.type('@stats ');
  await leaveEditing(page);
}

async function styleCases(page, ids) {
  const note = await page.evaluate(id => {
    const element = document.querySelector(`.note[data-note-id="${id}"]`);
    return {editing: element.classList.contains('editing'), tags: element.dataset.noteTags,
      hasPanel: element.querySelector(':scope > .note-content > .meta-stats') !== null};
  }, ids.diet);
  assert.equal(note.hasPanel, true, `the diet note shows its stats: ${JSON.stringify(note)}`);
  const looks = {};
  for (const style of STYLES) {
    await page.evaluate(async style => {
      const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
      if (document.documentElement.dataset.statsStyle !== style) await CommandPalette.applyPreference('pref.stats_style', style);
    }, style);
    await settle(page);
    looks[style] = await page.evaluate(noteId => {
      const panel = document.querySelector(`.note[data-note-id="${noteId}"] > .note-content > .meta-stats`);
      const item = panel.querySelector('.meta-stats-item');
      const transparent = 'rgba(0, 0, 0, 0)';
      return {
        tinted: [panel, item].some(element => getComputedStyle(element).backgroundColor !== transparent),
        leftBar: getComputedStyle(panel).borderLeftWidth,
        numberOverLabel: getComputedStyle(item).flexDirection === 'column-reverse',
        dottedLeader: getComputedStyle(panel.querySelector('.meta-stats-leader')).display !== 'none',
      };
    }, ids.diet);
  }
  assert.deepEqual(looks, {
    strip: {tinted: true, leftBar: '3px', numberOverLabel: false, dottedLeader: false},
    tiles: {tinted: true, leftBar: '0px', numberOverLabel: true, dottedLeader: false},
    ledger: {tinted: true, leftBar: '0px', numberOverLabel: false, dottedLeader: true},
  });
}

// A note's single figures as shown: "Total calories: 0" and so on.
function figures(page, noteId) {
  return page.evaluate(noteId => [...document.querySelectorAll(
    `.note[data-note-id="${noteId}"] > .note-content > .meta-stats .meta-stats-item`,
  )].map(item => item.textContent.replace(/\s+/g, ' ').trim()), noteId);
}

async function emptyFiguresCase(page, ids) {
  // Calories are logged on other days, so an empty day's total is 0, its average a dash.
  assert.deepEqual(await figures(page, ids.emptyDay), ['Total calories: 0', 'Average calories: —']);
}

async function search(page, text) {
  await clickAndSelectAll(page, '#search-input');
  await page.keyboard.press('Backspace');
  await page.keyboard.type(text);
  await idle(page);
}

// The root notes the search shows, by their first line, and whether each note is greyed.
function searchResult(page, ids) {
  return page.evaluate(ids => {
    const shown = [...document.querySelectorAll('#notes-container > .note, #notes-container [data-note-id]')]
      .filter(note => !note.parentElement.closest('[data-note-id]') && !note.classList.contains('search-redacted'))
      .map(note => note.querySelector(':scope > .note-content > p').textContent);
    const meal = document.querySelector(`.note[data-note-id="${ids.bigDayMeal}"]`);
    return {roots: [...new Set(shown)].sort(), mealIsShown: meal !== null && !meal.classList.contains('search-redacted')};
  }, ids);
}

async function statsSearchCase(page, ids) {
  await search(page, '@sum:');
  await page.waitForFunction(() => [...document.querySelectorAll('.search-suggestion')].some(item => item.offsetParent !== null));
  const labels = await page.$$eval('.search-suggestion', items => items.filter(item => item.offsetParent !== null).map(item => item.textContent.trim()));
  assert.equal(labels[0], 'calories', `after @sum: the box suggests calories: ${labels}`);
  await page.keyboard.type('calories>2000');
  await page.keyboard.press('Escape');
  await idle(page);
  assert.deepEqual(await searchResult(page, ids), {roots: ['Big day'], mealIsShown: true},
    'the day over 2000 calories, with the meal under it');
  await search(page, '');
}

async function foldedCase(page, ids) {
  await page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.setCollapsedBulk([id], true);
  }, ids.diet);
  await reload(page);
  assert.equal(await stats(page, ids.diet), null, 'a folded note shows no stats');
}

async function statsCases(page, ids) {
  const failures = [];
  for (const run of [placeAndLiveCases, suggestionCase, styleCases, emptyFiguresCase, statsSearchCase, foldedCase]) {
    // A suite runs every case and reports all their failures at once.
    try {
      await run(page, ids);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${run.name}: ${error.message}`);
    }
    // A case that failed while editing leaves the next one a note that is not.
    await leaveEditing(page);
  }
  assert.deepEqual(failures, []);
}

export async function checkStatsTags(page) {
  await page.setViewport(WINDOW);
  const initialStyle = await page.evaluate(() => document.documentElement.dataset.statsStyle);
  const ids = await seedNotes(page);
  await reload(page);
  await runThenCleanUp('stats tags', () => statsCases(page, ids), async () => {
    await page.evaluate(async ({ids, initialStyle}) => {
      const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
      if (document.documentElement.dataset.statsStyle !== initialStyle) await CommandPalette.applyPreference('pref.stats_style', initialStyle);
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const key of ['diet', 'bigDay', 'smallDay', 'emptyDay']) await NotesAPI.deleteNote(ids[key]);
    }, {ids, initialStyle});
  });
}
