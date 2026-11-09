import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// A view that now shows other notes starts at its top (docs/ui/interaction-principles.md, principle
// 2). Reported 2026-11-09: the view held on to the note that had been on top, so a note the new view
// lists far down took the page with it. Each case narrows the list to a note the full list has at
// its bottom, then widens it again. The sort order and Notes with Files: browser-file-size-sort-regressions.mjs.

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 700;
// Wide enough for the tree beside the column (scripts/browser-edge-tab-regressions.mjs).
const WINDOW = {width: 1440, height: 900};
const FOLDER = 'Vctopfolder/';
const FILLER_TAG = 'vctopfiller';
const OLD_DATETIME = '@datetime=2020-01-15';
const OLD_RANGE = {field: 'created', rangeKind: 'custom', fromDate: '2020-01-01', toDate: '2020-01-31'};
// Enough notes above the three that their place in the full list is far down the page.
const FILLER_NOTES = 40;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await pause(SETTLE_MS);
}

async function seed(page) {
  return page.evaluate(async ({folder, fillerTag, oldDatetime, fillerNotes}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    // New notes go to the top: the three are created first, so they end at the bottom.
    const note = async (text, tags) => {
      const created = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(created.id, `<p>${text}</p><p>Second line</p><p>Third line</p>`, tags);
      ids.push(created.id);
    };
    await note('Dated long ago', `${fillerTag} ${oldDatetime}`);
    await note('Has no tags', '');
    await note('In the folder', `${fillerTag} ${folder}`);
    for (let index = 0; index < fillerNotes; index += 1) await note(`Filler ${index}`, fillerTag);
    return ids;
  }, {folder: FOLDER, fillerTag: FILLER_TAG, oldDatetime: OLD_DATETIME, fillerNotes: FILLER_NOTES});
}

function runOnPalette(page, method, argument) {
  return page.evaluate(async ({method, argument}) => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette[method](argument);
  }, {method, argument});
}

function chooseTreeFolder(page, folder) {
  return page.evaluate(async folder => {
    const {chooseFolder} = await import('/static/js/modules/mode-manager/events/keyboard-events.js');
    await chooseFolder(folder);
  }, folder);
}

// Where the page ends once `widen` shows the full list again, the narrowed list having been at its top.
async function scrollAfterWidening(page, widen) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await idle(page);
  await widen();
  await idle(page);
  return page.evaluate(() => window.scrollY);
}

async function dateRangeCase(page) {
  await runOnPalette(page, 'setDateFilter', OLD_RANGE);
  await idle(page);
  return scrollAfterWidening(page, () => page.click('#date-range-indicator-clear'));
}

async function untaggedCase(page) {
  await runOnPalette(page, 'setIsUntaggedView', true);
  await idle(page);
  return scrollAfterWidening(page, () => page.click('#untagged-view-indicator-clear'));
}

async function folderChipCase(page) {
  await runOnPalette(page, 'setVirtualFolder', FOLDER);
  await idle(page);
  return scrollAfterWidening(page, () => page.click('#virtual-folder-indicator-clear'));
}

async function folderInTreeCase(page) {
  await chooseTreeFolder(page, FOLDER);
  await idle(page);
  return scrollAfterWidening(page, () => chooseTreeFolder(page, ''));
}

export async function checkViewChangeTop(page) {
  const originalViewport = page.viewport();
  await page.setViewport(WINDOW);
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  const ids = await seed(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('view change top', async () => {
    const landed = {dateRange: await dateRangeCase(page), untagged: await untaggedCase(page)};
    // The tree and its folders show in a folder context.
    await page.click('#virtual-folders-button');
    await idle(page);
    landed.folderChip = await folderChipCase(page);
    landed.folderInTree = await folderInTreeCase(page);
    assert.deepEqual(landed, {dateRange: 0, untagged: 0, folderChip: 0, folderInTree: 0});
  }, async () => {
    await page.evaluate(async ids => {
      if (document.body.classList.contains('virtual-folders-on')) document.getElementById('virtual-folders-button').click();
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, ids);
    await page.setViewport(originalViewport);
  });
}
