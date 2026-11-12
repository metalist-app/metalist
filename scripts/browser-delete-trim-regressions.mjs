import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { clickAndSelectAll } from './browser-select-field.mjs';

// Deleting notes in bulk checks the trim reminder at once (docs/ui/command-palette.md,
// `Trim Reminder`; the maintainer, 2026-11-12): Delete Folder with its notes, and Delete Notes
// (Current View)…, clear undo, so the deleted notes' files are unused right away, and the card
// shows as the deletion finishes, with no click or key after it, once unused files reach 10 MB.
// Below that, nothing shows. Driven as a person does it: right-click the folder, Delete
// Folder…, tick "Also delete its notes", Delete Folder and Notes; or search, the command
// palette's Delete Notes (Current View)…, confirm.

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 300;
const PALETTE_OPEN_MS = 400;
// Wide enough for the tree beside the column (scripts/browser-edge-tab-regressions.mjs).
const WINDOW = {width: 1440, height: 900};
const MIB = 1024 * 1024;
// Below the reminder's 10 MB, and enough to take the total over it.
const SMALL_FILE_MIB = 1;
const LARGE_FILE_MIB = 6;
const SMALL_SIZES = Object.freeze([SMALL_FILE_MIB]);
const LARGE_SIZES = Object.freeze([LARGE_FILE_MIB, LARGE_FILE_MIB]);
const TOTAL_MIB = SMALL_FILE_MIB + LARGE_FILE_MIB + LARGE_FILE_MIB;
const SMALL_FOLDER = 'Trimtestsmall/';
const LARGE_FOLDER = 'Trimtestlarge/';
const SMALL_TAG = 'trimtestsmall';
const LARGE_TAG = 'trimtestlarge';
const DELETE_IN_VIEW = 'Delete Notes (Current View)';
const CARD = '#trim-reminder-notice';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function reload(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await pause(SETTLE_MS);
}

// Notes carrying the tags, each holding a file of random bytes (stored as large as it is).
async function fileNotes(page, tags, sizesMib) {
  return page.evaluate(async ({tags, sizesMib, mib}) => {
    const {NotesAPI, FilesAPI} = await import('/static/js/modules/api-client.js');
    const chunk = 65536;
    const ids = [];
    for (const [index, sizeMib] of sizesMib.entries()) {
      const bytes = new Uint8Array(sizeMib * mib);
      for (let offset = 0; offset < bytes.length; offset += chunk) {
        crypto.getRandomValues(bytes.subarray(offset, Math.min(offset + chunk, bytes.length)));
      }
      const uploaded = await FilesAPI.uploadFile(new File([bytes], `trim-test-${index}.bin`, {type: 'application/octet-stream'}));
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<p>Trim test ${index}</p><p>${uploaded.reference_token}</p>`, tags);
      ids.push(note.id);
    }
    return ids;
  }, {tags, sizesMib, mib: MIB});
}

async function unusedBytes(page) {
  return page.evaluate(async () => {
    const {FilesAPI} = await import('/static/js/modules/api-client.js');
    return (await FilesAPI.fetchUnusedFiles()).size_bytes;
  });
}

// Nothing unused, and the page reloaded so no card is left from before.
async function startFromNothingUnused(page) {
  await page.evaluate(async () => {
    const {FilesAPI} = await import('/static/js/modules/api-client.js');
    await FilesAPI.trimUnusedFiles();
  });
  await reload(page);
  assert.equal(await unusedBytes(page), 0, 'nothing unused to start from');
}

async function cardText(page) {
  return page.evaluate(selector => {
    const card = document.querySelector(selector);
    return card === null ? null : card.querySelector('.backup-reminder-text').textContent;
  }, CARD);
}

async function expectedCardText(page, bytes) {
  return page.evaluate(async bytes => {
    const {trimReminderMessage} = await import('/static/js/modules/trim-reminder-schedule.js');
    return trimReminderMessage(bytes);
  }, bytes);
}

async function isTreeShown(page) {
  return page.evaluate(() => !document.getElementById('virtual-folders').hidden);
}

async function clickFoldersTab(page) {
  await page.click('#virtual-folders-button');
  await idle(page);
  await pause(SETTLE_MS);
}

async function searchFor(page, query) {
  await clickAndSelectAll(page, '#search-input');
  if (query === '') await page.keyboard.press('Backspace');
  else await page.keyboard.type(query);
  await page.keyboard.press('Escape');
  await idle(page);
  await pause(SETTLE_MS);
}

async function deleteFolderAndNotes(page, folder) {
  await page.click(`#virtual-folders [data-virtual-folder="${folder}"]`, {button: 'right'});
  await page.waitForSelector('#context-menu.is-visible', {visible: true});
  const item = await page.evaluateHandle(() => [...document.querySelectorAll('#context-menu.is-visible .context-menu-item')]
    .find(node => node.querySelector('.context-menu-item-label').textContent.trim() === 'Delete Folder…'));
  await item.click();
  await page.waitForSelector('#delete-folder-notes', {visible: true});
  await page.click('#delete-folder-notes');
  await page.click('#delete-folder-submit-btn');
  // No click or key after this: the card must come from the deletion itself.
  await idle(page);
  await pause(SETTLE_MS);
}

async function deleteNotesInView(page, tag) {
  await searchFor(page, tag);
  await page.keyboard.down('Meta');
  await page.keyboard.press('/');
  await page.keyboard.up('Meta');
  await pause(PALETTE_OPEN_MS);
  await page.keyboard.type(DELETE_IN_VIEW);
  await pause(SETTLE_MS);
  await page.keyboard.press('Enter');
  await page.waitForSelector('#confirmation-submit-btn', {visible: true});
  await page.click('#confirmation-submit-btn');
  // No click or key after this: the card must come from the deletion itself.
  await idle(page);
  await pause(SETTLE_MS);
}

// One way of deleting, below 10 MB and then over it: { label, prepare(sizes), remove(small) }.
async function checkBelowThenAbove(page, way) {
  await startFromNothingUnused(page);
  await way.prepare(true, SMALL_SIZES);
  await reload(page);
  assert.equal(await cardText(page), null, `${way.label}, below: no card before the deletion`);
  await way.remove(true);
  assert.equal(await unusedBytes(page), SMALL_FILE_MIB * MIB, `${way.label}, below: the deleted note's file is unused`);
  assert.equal(await cardText(page), null, `${way.label}, below: still no card, 1 MB being under 10 MB`);

  await way.prepare(false, LARGE_SIZES);
  await reload(page);
  assert.equal(await cardText(page), null, `${way.label}, above: no card before the deletion`);
  await way.remove(false);
  const bytes = await unusedBytes(page);
  assert.equal(bytes, TOTAL_MIB * MIB, `${way.label}, above: every deleted note's file is unused`);
  assert.equal(await cardText(page), await expectedCardText(page, bytes), `${way.label}, above: the card shows at once, with the total`);
}

const DELETE_FOLDER = Object.freeze({
  label: 'Delete Folder',
  prepare: (page, isSmall, sizes) => fileNotes(page, isSmall ? SMALL_FOLDER : LARGE_FOLDER, sizes),
  remove: (page, isSmall) => deleteFolderAndNotes(page, isSmall ? SMALL_FOLDER : LARGE_FOLDER),
});

const DELETE_IN_VIEW_WAY = Object.freeze({
  label: DELETE_IN_VIEW,
  prepare: (page, isSmall, sizes) => fileNotes(page, isSmall ? SMALL_TAG : LARGE_TAG, sizes),
  remove: (page, isSmall) => deleteNotesInView(page, isSmall ? SMALL_TAG : LARGE_TAG),
});

function onPage(page, way) {
  return {
    label: way.label,
    prepare: (isSmall, sizes) => way.prepare(page, isSmall, sizes),
    remove: isSmall => way.remove(page, isSmall),
  };
}

export async function checkDeleteTrim(page) {
  await page.setViewport(WINDOW);
  await reload(page);
  const treeWasShown = await isTreeShown(page);
  await runThenCleanUp('delete trim', async () => {
    if (!treeWasShown) await clickFoldersTab(page);
    await checkBelowThenAbove(page, onPage(page, DELETE_FOLDER));
    console.log('PASS Delete Folder: the trim reminder shows at once above 10 MB, and not below');
    await checkBelowThenAbove(page, onPage(page, DELETE_IN_VIEW_WAY));
    console.log('PASS Delete Notes (Current View): the trim reminder shows at once above 10 MB, and not below');
  }, async () => {
    await searchFor(page, '');
    if ((await isTreeShown(page)) !== treeWasShown) await clickFoldersTab(page);
    await startFromNothingUnused(page);
  });
}
