import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';
import { clickAndSelectAll } from './browser-select-field.mjs';

// Deleting notes in bulk takes their files with them (the maintainer, 2026-11-18; before, the
// files stayed until Trim Unused Files and only a reminder card showed): Delete Folder with its
// notes, and Delete Notes (Current View)…, say how many files and how much space go, and
// delete them in the same step. The folder dialog's box starts ticked. A file a note that
// stays also uses is kept, and a file unused before the deletion is left for Trim. Driven as
// a person does it: right-click the folder, Delete Folder…, Delete Folder and Notes; or
// search, the command palette's Delete Notes (Current View)…, confirm.

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 300;
const PALETTE_OPEN_MS = 400;
// Wide enough for the tree beside the column (scripts/browser-edge-tab-regressions.mjs).
const WINDOW = {width: 1440, height: 900};
const MIB = 1024 * 1024;
// Two notes' files, and a file no note uses from before the deletion.
const FILE_SIZES_MIB = Object.freeze([1, 6]);
const TOTAL_MIB = 7;
const OLD_UNUSED_MIB = 1;
const FOLDER = 'Trimtestfiles/';
const KEPT_FOLDER = 'Trimtestkept/';
const TAG = 'trimtestfiles';
const KEPT_TAG = 'trimtestkept';
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

async function openDeleteFolder(page, folder) {
  await page.click(`#virtual-folders [data-virtual-folder="${folder}"]`, {button: 'right'});
  await page.waitForSelector('#context-menu.is-visible', {visible: true});
  const item = await page.evaluateHandle(() => [...document.querySelectorAll('#context-menu.is-visible .context-menu-item')]
    .find(node => node.querySelector('.context-menu-item-label').textContent.trim() === 'Delete Folder…'));
  await item.click();
  await page.waitForSelector('#delete-folder-notes', {visible: true});
}

function folderDialog(page) {
  return page.evaluate(() => ({
    isTicked: document.getElementById('delete-folder-notes').checked,
    text: document.querySelector('.delete-folder-notes-toggle span').textContent.trim(),
    button: document.getElementById('delete-folder-submit-btn').textContent.trim(),
  }));
}

async function sizeText(page, mib) {
  return page.evaluate(async bytes => {
    const {formatByteSize} = await import('/static/js/modules/byte-sizes.js');
    return formatByteSize(bytes);
  }, mib * MIB);
}

function notesThere(page, ids) {
  return page.evaluate(async ids => {
    const found = [];
    for (const id of ids) {
      const response = await fetch(`/api2/notes/${id}/preview`, {headers: {'X-Metalist-Tab-Id': sessionStorage.getItem('metalist_tab_id')}});
      if ((await response.json()).status === 'ready') found.push(id);
    }
    return found;
  }, ids);
}

// A file no note uses, there before the deletion: not the deletion's to take.
async function uploadUnused(page, mib) {
  await page.evaluate(async bytes => {
    const {FilesAPI} = await import('/static/js/modules/api-client.js');
    await FilesAPI.uploadFile(new File([new Uint8Array(bytes)], 'trim-test-old.bin', {type: 'application/octet-stream'}));
  }, mib * MIB);
}

async function checkDeleteFolder(page) {
  await startFromNothingUnused(page);
  const ids = await fileNotes(page, FOLDER, FILE_SIZES_MIB);
  await uploadUnused(page, OLD_UNUSED_MIB);
  await reload(page);

  // Cases 1 and 2: ticked at first, the files said with their size, and deleted with the notes.
  await openDeleteFolder(page, FOLDER);
  assert.deepEqual(await folderDialog(page), {
    isTicked: true,
    text: `Also delete its 2 notes and their 2 files (${await sizeText(page, TOTAL_MIB)})`,
    button: 'Delete Folder and Notes',
  });
  await page.click('#delete-folder-submit-btn');
  await idle(page);
  await pause(SETTLE_MS);
  assert.deepEqual(await notesThere(page, ids), [], 'Delete Folder and Notes: the notes are gone');
  // Case 9: only the file unused from before is left for Trim; the deleted notes' files went.
  assert.equal(await unusedBytes(page), OLD_UNUSED_MIB * MIB, 'Delete Folder and Notes: the notes\' files went with them');
  assert.equal(await cardText(page), null, 'no trim card: nothing of the deletion is left to trim');

  // Case 3: unticked, the folder alone comes off; its notes and their files stay.
  const kept = await fileNotes(page, `${KEPT_FOLDER} ${KEPT_TAG}`, [OLD_UNUSED_MIB]);
  await reload(page);
  await openDeleteFolder(page, KEPT_FOLDER);
  await page.click('#delete-folder-notes');
  assert.equal((await folderDialog(page)).button, 'Delete Folder');
  await page.click('#delete-folder-submit-btn');
  await idle(page);
  await pause(SETTLE_MS);
  assert.deepEqual(await notesThere(page, kept), kept, 'Delete Folder: its notes stay');
  assert.equal(await unusedBytes(page), OLD_UNUSED_MIB * MIB, 'Delete Folder: its notes\' files stay in use');
  // Deleted as a view's notes, so its file goes with it (a single delete would keep the file for undo).
  await searchFor(page, KEPT_TAG);
  await page.evaluate(async count => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.deleteNotesInView(count);
  }, kept.length);
  await searchFor(page, '');
}

async function checkDeleteInView(page) {
  await startFromNothingUnused(page);
  const ids = await fileNotes(page, TAG, FILE_SIZES_MIB);
  await reload(page);
  await searchFor(page, TAG);
  await page.keyboard.down('Meta');
  await page.keyboard.press('/');
  await page.keyboard.up('Meta');
  await pause(PALETTE_OPEN_MS);
  await page.keyboard.type(DELETE_IN_VIEW);
  await pause(SETTLE_MS);
  await page.keyboard.press('Enter');
  await page.waitForSelector('#confirmation-submit-btn', {visible: true});
  const said = await page.$eval('#confirmation-modal .alphabetize-root-notes-warning p', text => text.textContent);
  assert.ok(said.includes(`Their 2 files (${await sizeText(page, TOTAL_MIB)}) are deleted too.`), `the confirmation says the files: ${said}`);
  await page.click('#confirmation-submit-btn');
  await page.waitForFunction(() => [...document.querySelectorAll('.floating-message-text')]
    .some(text => text.textContent === 'Deleted 2 notes and 2 files.'));
  await idle(page);
  await pause(SETTLE_MS);
  assert.deepEqual(await notesThere(page, ids), [], `${DELETE_IN_VIEW}: the notes are gone`);
  assert.equal(await unusedBytes(page), 0, `${DELETE_IN_VIEW}: the notes' files went with them`);
  assert.equal(await cardText(page), null, 'no trim card');
}

export async function checkDeleteTrim(page) {
  await page.setViewport(WINDOW);
  await reload(page);
  const treeWasShown = await isTreeShown(page);
  await runThenCleanUp('delete trim', async () => {
    if (!treeWasShown) await clickFoldersTab(page);
    await checkDeleteFolder(page);
    console.log('PASS Delete Folder: ticked at first, says its notes\' files, and deletes them with the notes');
    await checkDeleteInView(page);
    console.log('PASS Delete Notes (Current View): says the notes\' files and deletes them with the notes');
  }, async () => {
    await searchFor(page, '');
    if ((await isTreeShown(page)) !== treeWasShown) await clickFoldersTab(page);
    await startFromNothingUnused(page);
  });
}
