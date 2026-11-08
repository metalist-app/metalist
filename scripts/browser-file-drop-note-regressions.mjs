import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Files not aimed at a note get one note each; files aimed at a note go in it (the maintainer,
// 2026-11-08). Images dropped on a folder in the tree go through the import's Images screen.
// Each check below is one of the agreed cases, by its number (docs/ui/references.md).

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 300;
const WINDOW = {width: 1440, height: 900};
const FOLDER = 'Dropzone/';
const IMAGES_TITLE = 'Should images be compressed?';
const SUMMARY_TITLE = 'Ready to import';
const IMAGE_DIALOG = '#image-file-insert-choice-modal';
const SAVE_AS_FILE = '#image-file-insert-choice-attach';
const CANCEL_IMAGE_DIALOG = '#image-file-insert-choice-cancel';
const WAIT_MS = 20000;
// The first estimate starts the server's image workers.
const IMAGE_ESTIMATE_WAIT_MS = 90000;
// A one-pixel PNG: real enough for the browser and the server to read as an image.
const PNG_BASE64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
const GIF_BASE64 = 'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
  await pause(SETTLE_MS);
}

// Runs in the page: a list of {name, base64} or {name, text} as Files.
const FILES_IN_PAGE = `(specs) => specs.map(({name, text, base64, type}) => {
  if (text !== undefined) return new File([text], name, {type});
  const bytes = Uint8Array.from(atob(base64), character => character.charCodeAt(0));
  // Padded so no two are the same bytes: the paste handling takes identical ones as one image.
  return new File([bytes, new Uint8Array(name.charCodeAt(name.lastIndexOf('.') - 1))], name, {type});
})`;

function csv(name) {
  return {name, text: `${name},dropped`, type: 'text/csv'};
}

function png(name) {
  return {name, base64: PNG_BASE64, type: 'image/png'};
}

function gif(name) {
  return {name, base64: GIF_BASE64, type: 'image/gif'};
}

async function drop(page, selector, specs) {
  await page.evaluate((target, fileSpecs, toFiles) => {
    const element = document.querySelector(target);
    if (element === null) throw new Error(`Nothing to drop on: ${target}`);
    const dataTransfer = new DataTransfer();
    // eslint-disable-next-line no-eval
    for (const file of (0, eval)(toFiles)(fileSpecs)) dataTransfer.items.add(file);
    const box = element.getBoundingClientRect();
    const at = {clientX: box.left + box.width / 2, clientY: box.top + box.height / 2, bubbles: true, cancelable: true, dataTransfer};
    element.dispatchEvent(new DragEvent('dragover', at));
    element.dispatchEvent(new DragEvent('drop', at));
  }, selector, specs, FILES_IN_PAGE);
}

async function pasteFiles(page, specs) {
  await page.evaluate((fileSpecs, toFiles) => {
    const clipboardData = new DataTransfer();
    // eslint-disable-next-line no-eval
    for (const file of (0, eval)(toFiles)(fileSpecs)) clipboardData.items.add(file);
    const target = document.querySelector('.note-content[contenteditable="true"]') || document.body;
    target.dispatchEvent(Object.defineProperty(new ClipboardEvent('paste', {bubbles: true, cancelable: true}), 'clipboardData', {value: clipboardData}));
  }, specs, FILES_IN_PAGE);
}

async function rootIds(page) {
  return page.evaluate(() => [...document.querySelectorAll('#notes-container > .note')].map(note => note.dataset.noteId));
}

async function isEditing(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode.isEditing;
  });
}

async function imageDialogShows(page) {
  return page.$eval(IMAGE_DIALOG, node => getComputedStyle(node).display !== 'none').catch(() => false);
}

async function waitForImageDialog(page) {
  await page.waitForFunction(id => {
    const node = document.querySelector(id);
    return node !== null && getComputedStyle(node).display !== 'none';
  }, {timeout: WAIT_MS}, IMAGE_DIALOG);
}

async function answerImageDialog(page, button) {
  await waitForImageDialog(page);
  await page.click(button);
}

async function waitForStep(page, title) {
  await page.waitForFunction(expected => {
    const node = document.querySelector('#import-wizard .wizard-screen:not(.is-leaving) .wizard-screen-title');
    return node !== null && node.textContent === expected;
  }, {timeout: WAIT_MS}, title);
  await pause(SETTLE_MS);
}

async function nextStep(page) {
  await page.click('#import-wizard .wizard-footer .wizard-next');
}

async function waitForRootCount(page, count) {
  await page.waitForFunction(expected => document.querySelectorAll('#notes-container > .note').length === expected, {timeout: WAIT_MS}, count);
  await idle(page);
}

async function noteOf(page, noteId) {
  return page.evaluate(id => {
    const note = document.querySelector(`#notes-container > .note[data-note-id="${id}"]`);
    const content = note.querySelector('.note-content');
    return {text: note.textContent, html: content.innerHTML, tags: note.dataset.noteTags.split(/\s+/)};
  }, noteId);
}

// How many files a note shows: a dropped file is one reference in its text or one picture.
async function fileCountOf(page, noteId) {
  return page.evaluate(id => {
    const content = document.querySelector(`#notes-container > .note[data-note-id="${id}"] > .note-body .note-content, #notes-container > .note[data-note-id="${id}"] .note-content`);
    return content.querySelectorAll('[data-file-id], [data-file-reference], img').length;
  }, noteId);
}

function newOnes(after, before) {
  return after.filter(id => !before.includes(id));
}

async function startEditing(page, noteId) {
  await page.click(`#notes-container > .note[data-note-id="${noteId}"] .note-content`);
  await page.waitForFunction(id => document.querySelector(`#notes-container > .note[data-note-id="${id}"] .note-content[contenteditable="true"]`) !== null,
    {timeout: WAIT_MS}, noteId);
  await idle(page);
}

// Saved and closed, the list drawn again, so a note's files show as files.
async function leaveEditing(page) {
  await page.evaluate(async () => {
    const {actionSaveAndExitEditingWithoutRefreshing: leave} = await import('/static/js/modules/mode-manager/actions/selection-actions.js');
    const {actionRefreshAndMaybeSelect: refresh} = await import('/static/js/modules/mode-manager/actions/ui-actions.js');
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    if (mode.isEditing) await leave();
    await refresh({startedAt: performance.now(), context: 'tests.leaveEditing'});
  });
  await idle(page);
}

// A note being edited shows each file as its ![[token]] in the text.
async function waitForFileTokens(page, noteId, count) {
  await page.waitForFunction((id, expected) => {
    const text = document.querySelector(`#notes-container > .note[data-note-id="${id}"] .note-content`).textContent;
    return (text.match(/!\[\[/g) || []).length === expected;
  }, {timeout: WAIT_MS}, noteId, count);
}

const TRIP_SELECTOR = tripId => `#notes-container > .note[data-note-id="${tripId}"] .note-content`;

// 9: one file on the column: a note at the top, as before.
async function checkOneFileOnTheColumn(page, created) {
  const before = await rootIds(page);
  await drop(page, '#notes-container', [csv('nine.csv')]);
  await waitForRootCount(page, before.length + 1);
  const after = await rootIds(page);
  created.push(...newOnes(after, before));
  assert.equal(await isEditing(page), true, 'case 9: one file stays open, as before');
  await leaveEditing(page);
  assert.ok((await noteOf(page, after[0])).text.includes('nine.csv'), 'case 9: the file is in the note at the top');
}

// 10 and 16: several on the column: one note each, in the order dropped, the image question once, none left open.
async function checkSeveralFilesOnTheColumn(page, created) {
  const before = await rootIds(page);
  await drop(page, '#notes-container', [csv('ten-first.csv'), png('ten-picture.png'), csv('ten-last.csv')]);
  await answerImageDialog(page, SAVE_AS_FILE);
  await waitForRootCount(page, before.length + 3);
  assert.equal(await imageDialogShows(page), false, 'case 10: the image question is asked once');
  const after = await rootIds(page);
  created.push(...newOnes(after, before));
  assert.ok((await noteOf(page, after[0])).text.includes('ten-first.csv'), 'case 10: the first file on top');
  assert.ok(!(await noteOf(page, after[0])).text.includes('ten-last.csv'), 'case 10: each file in its own note');
  assert.ok((await noteOf(page, after[2])).text.includes('ten-last.csv'), 'case 10: the last file third');
  assert.equal(await isEditing(page), false, 'case 16: none left open');
}

// 11 and 16: several non-images on a folder: one note each, filed in it, no walkthrough.
async function checkSeveralFilesOnAFolder(page, created) {
  const before = await rootIds(page);
  await drop(page, `#virtual-folders [data-virtual-folder="${FOLDER}"]`, [csv('eleven-first.csv'), csv('eleven-last.csv')]);
  await waitForRootCount(page, before.length + 2);
  const after = await rootIds(page);
  created.push(...newOnes(after, before));
  for (const [id, name] of [[after[0], 'eleven-first.csv'], [after[1], 'eleven-last.csv']]) {
    const note = await noteOf(page, id);
    assert.ok(note.text.includes(name), `case 11: ${name} has its own note`);
    assert.ok(note.tags.includes(FOLDER), `case 11: ${name} is filed in the folder`);
  }
  assert.equal(await isEditing(page), false, 'case 16: none left open');
}

// A clipboard carries one picture in several formats, so a paste keeps the largest: one image, one note.
async function checkAPasteMakesOneNote(page, created) {
  const before = await rootIds(page);
  await pasteFiles(page, [png('paste-small.png'), png('paste-z.png')]);
  await answerImageDialog(page, SAVE_AS_FILE);
  await waitForRootCount(page, before.length + 1);
  created.push(...newOnes(await rootIds(page), before));
  await leaveEditing(page);
}

// 15: files dropped on the note being edited go in it, on its text or its margin.
async function checkFilesOnTheEditedNote(page, tripId) {
  const before = await rootIds(page);
  await drop(page, TRIP_SELECTOR(tripId), [csv('fifteen-text.csv'), png('fifteen.png')]);
  await answerImageDialog(page, SAVE_AS_FILE);
  await waitForFileTokens(page, tripId, 2);
  await idle(page);
  assert.deepEqual(await rootIds(page), before, 'case 15: on its text, no new notes');
  await drop(page, `#notes-container > .note[data-note-id="${tripId}"]`, [csv('fifteen-margin.csv')]);
  await waitForFileTokens(page, tripId, 3);
  await idle(page);
  assert.deepEqual(await rootIds(page), before, 'case 15: on its margin, no new notes');
}

// 14: files dropped outside the note being edited: saved and closed, one note each. Runs right after 15, the note open.
async function checkFilesOutsideTheEditedNote(page, tripId, created) {
  const before = await rootIds(page);
  await drop(page, '#notes-container', [csv('fourteen-a.csv'), csv('fourteen-b.csv')]);
  await waitForRootCount(page, before.length + 2);
  const after = await rootIds(page);
  created.push(...newOnes(after, before));
  assert.equal(await isEditing(page), false, 'case 14: nothing left open');
  assert.ok(!(await noteOf(page, tripId)).text.includes('fourteen-a.csv'), 'case 14: not in the note that was open');
  assert.ok((await noteOf(page, after[0])).text.includes('fourteen-a.csv'), 'case 14: the first file has its own note');
  assert.ok((await noteOf(page, tripId)).text.includes('fifteen-margin.csv'), 'case 14: the open note was saved');
}

// 17: a file that fails: the notes made stay, the error names it.
async function checkOneFileFails(page, created) {
  const before = await rootIds(page);
  await page.evaluate(() => {
    window.__originalFetch = window.fetch;
    window.fetch = async (url, options) => {
      if (options && options.body instanceof FormData && options.body.get('file')?.name === 'seventeen-bad.csv') {
        return new Response(JSON.stringify({detail: 'Refused for the test'}), {status: 413, headers: {'Content-Type': 'application/json'}});
      }
      return window.__originalFetch(url, options);
    };
  });
  await drop(page, '#notes-container', [csv('seventeen-first.csv'), csv('seventeen-bad.csv'), csv('seventeen-last.csv')]);
  await page.waitForFunction(name => [...document.querySelectorAll('.floating-message-text')].some(node => node.textContent.includes(name)),
    {timeout: WAIT_MS}, 'seventeen-bad.csv');
  await idle(page);
  await page.evaluate(() => { window.fetch = window.__originalFetch; });
  const after = await rootIds(page);
  const made = newOnes(after, before);
  created.push(...made);
  assert.equal(made.length, 1, 'case 17: the note already made stays');
  assert.ok((await noteOf(page, made[0])).text.includes('seventeen-last.csv'), 'case 17: it holds the file brought in');
  await leaveEditing(page);
}

// 1 and 8: one image on a folder: the Images screen, no dialog; its own note, in the folder, at the bottom.
async function checkOneImageOnAFolder(page, created) {
  const before = await rootIds(page);
  await drop(page, `#virtual-folders [data-virtual-folder="${FOLDER}"]`, [png('one-image.png')]);
  await waitForStep(page, IMAGES_TITLE);
  assert.equal(await imageDialogShows(page), false, 'case 1: no Handle image file dialog');
  await nextStep(page);
  await waitForStep(page, SUMMARY_TITLE);
  await nextStep(page);
  await waitForRootCount(page, before.length + 1);
  await page.waitForFunction(() => document.querySelector('#import-wizard') === null || getComputedStyle(document.querySelector('#import-wizard')).display === 'none', {timeout: WAIT_MS});
  const after = await rootIds(page);
  created.push(...newOnes(after, before));
  assert.deepEqual(after.slice(0, before.length), before, 'case 8: the notes there stay put');
  assert.ok((await noteOf(page, after.at(-1))).tags.includes(FOLDER), 'case 8: filed in the folder');
  await page.waitForFunction(() => [...document.querySelectorAll('.floating-message-text')].some(node => node.textContent.startsWith('Imported 1 note')), {timeout: WAIT_MS});
}

// 2: several images on a folder: the same screen, their count.
async function checkSeveralImagesOnAFolder(page, created) {
  const before = await rootIds(page);
  await drop(page, `#virtual-folders [data-virtual-folder="${FOLDER}"]`, [png('two-a.png'), png('two-b.png')]);
  await waitForStep(page, IMAGES_TITLE);
  await page.waitForFunction(() => document.querySelector('#import-wizard .wizard-image-estimate').textContent.includes('2 images'), {timeout: IMAGE_ESTIMATE_WAIT_MS});
  await nextStep(page);
  await waitForStep(page, SUMMARY_TITLE);
  await nextStep(page);
  await waitForRootCount(page, before.length + 2);
  created.push(...newOnes(await rootIds(page), before));
}

// 3: an image into a note: the dialog, unchanged.
async function checkImageIntoANote(page, tripId) {
  await startEditing(page, tripId);
  await drop(page, TRIP_SELECTOR(tripId), [png('three.png')]);
  await answerImageDialog(page, CANCEL_IMAGE_DIALOG);
  await idle(page);
  await leaveEditing(page);
}

// 4: an image on the column: the dialog, unchanged.
async function checkImageOnTheColumn(page) {
  const before = await rootIds(page);
  await drop(page, '#notes-container', [png('four.png')]);
  await answerImageDialog(page, CANCEL_IMAGE_DIALOG);
  await idle(page);
  assert.deepEqual(await rootIds(page), before, 'case 4: cancelled, nothing comes in');
}

// 5: images and other files on a folder: all through the walkthrough.
async function checkImagesAndFilesOnAFolder(page, created) {
  const before = await rootIds(page);
  await drop(page, `#virtual-folders [data-virtual-folder="${FOLDER}"]`, [png('five.png'), csv('five.csv')]);
  await waitForStep(page, IMAGES_TITLE);
  await nextStep(page);
  await waitForStep(page, SUMMARY_TITLE);
  await nextStep(page);
  await waitForRootCount(page, before.length + 2);
  created.push(...newOnes(await rootIds(page), before));
}

// 6: images that can't be compressed on a folder: no question, each its own note.
async function checkUncompressibleImagesOnAFolder(page, created) {
  const before = await rootIds(page);
  await drop(page, `#virtual-folders [data-virtual-folder="${FOLDER}"]`, [gif('six-a.gif'), gif('six-b.gif')]);
  await waitForRootCount(page, before.length + 2);
  assert.equal(await imageDialogShows(page), false, 'case 6: no question');
  const after = await rootIds(page);
  created.push(...newOnes(after, before));
  assert.ok((await noteOf(page, after[0])).tags.includes(FOLDER), 'case 6: filed in the folder');
}

// 7: closing the Images screen: nothing comes in.
async function checkClosingTheImagesScreen(page) {
  const before = await rootIds(page);
  await drop(page, `#virtual-folders [data-virtual-folder="${FOLDER}"]`, [png('seven.png')]);
  await waitForStep(page, IMAGES_TITLE);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => {
    const wizard = document.querySelector('#import-wizard');
    return wizard === null || getComputedStyle(wizard).display === 'none';
  }, {timeout: WAIT_MS});
  await idle(page);
  assert.deepEqual(await rootIds(page), before, 'case 7: nothing comes in');
}

export async function checkFileDropNotes(page) {
  const tripId = await page.evaluate(async folder => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, '<p>Trip</p>', folder);
    return note.id;
  }, FOLDER);
  await page.setViewport(WINDOW);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await page.click('#virtual-folders-button');
  await idle(page);
  const created = [tripId];
  await runThenCleanUp('file drops make one note each', async () => {
    await page.waitForSelector(`#virtual-folders [data-virtual-folder="${FOLDER}"]`, {visible: true});
    await checkOneFileOnTheColumn(page, created);
    await checkSeveralFilesOnTheColumn(page, created);
    await checkSeveralFilesOnAFolder(page, created);
    await checkAPasteMakesOneNote(page, created);
    await startEditing(page, tripId);
    await checkFilesOnTheEditedNote(page, tripId);
    await checkFilesOutsideTheEditedNote(page, tripId, created);
    await checkOneFileFails(page, created);
    await checkImageOnTheColumn(page);
    await checkImageIntoANote(page, tripId);
    await checkUncompressibleImagesOnAFolder(page, created);
    await checkClosingTheImagesScreen(page);
    await checkOneImageOnAFolder(page, created);
    await checkSeveralImagesOnAFolder(page, created);
    await checkImagesAndFilesOnAFolder(page, created);
  }, async () => {
    await page.evaluate(async ({ids}) => {
      if (document.body.classList.contains('virtual-folders-on')) document.getElementById('virtual-folders-button').click();
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, {ids: created});
  });
}
