import assert from 'node:assert/strict';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Pasting a copied note (docs/ui/controls.md), and the keys and menus around it
// that the reference-paste suite checked until Paste as Reference was removed
// (2026-10-26, docs/ui/references.md): ⌘C while editing a note (no text
// selected) copies it; ⇧⌘V pastes it as the first child; ⌘V fills an empty
// note without children; ⌘R and ⇧⌘R do nothing, and the page does not reload;
// right-clicking one of two selected images opens the image menu. Control works
// like ⌘. Keys are sent as a keyboard reports them: with Shift held the letter
// arrives in upper case. V also sends the browser's paste command (Chrome's
// `commands`), so the Control cases stand for Windows and Linux on a Mac: run it
// in Chrome, as the reference-paste suite it came from was.

const SETTLE_MS = 400;
// Requests count as quiet after this long without one starting or ending.
const REQUESTS_QUIET_MS = 300;
// Clicks land this far inside the note's text, near its start.
const CLICK_INSET_PX = 10;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function reloadApp(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
}

async function createNote(page, content) {
  return page.evaluate(async content => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, content, '');
    return note.id;
  }, content);
}

async function deleteNotes(page, ids) {
  await page.evaluate(async ids => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    for (const id of ids) await NotesAPI.deleteNote(id);
  }, ids);
}

function middleY(box) {
  return box.y + box.height / 2;
}

async function startEditing(page, noteId) {
  await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), noteId);
  const box = await (await page.$(`.note[data-note-id="${noteId}"] > .note-content`)).boundingBox();
  await page.mouse.click(box.x + CLICK_INSET_PX, middleY(box));
  await page.waitForFunction(async id => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const content = document.querySelector(`.note[data-note-id="${id}"] > .note-content`);
    return mode.isEditing && mode.currentNoteId === id && content !== null && content.isContentEditable;
  }, {}, noteId);
  await idle(page);
}

async function leaveEditing(page) {
  await page.keyboard.press('Escape');
  await idle(page);
}

// modifier is 'Meta' (⌘) or 'Control'; with Shift, the letter goes in upper case.
// V also runs the browser's own command, as a real keystroke does: ⌘V pastes, and
// ⇧⌘V is Chrome's Paste and Match Style, whose paste carries the clipboard's plain
// text only. MetaList decides from what is pasted.
// Whether the modifier's V pastes. Chrome runs its paste command for either (the
// `commands` option below). Firefox pastes only with the platform's own key: ⌘ on
// macOS, Control elsewhere; Control+V on a Mac pastes nothing there, for anyone.
function pastesWith(modifier) {
  if (process.env.BROWSER_TEST_BROWSER === 'chrome') return true;
  return modifier === (process.platform === 'darwin' ? 'Meta' : 'Control');
}

async function shortcut(page, modifier, letter, withShift) {
  let options = {};
  if (letter === 'v') options = {commands: ['paste']};
  if (letter === 'v' && withShift) options = {commands: ['pasteAndMatchStyle']};
  await page.keyboard.down(modifier);
  if (withShift) {
    await page.keyboard.down('Shift');
    await page.keyboard.press(letter.toUpperCase(), options);
    await page.keyboard.up('Shift');
  } else {
    await page.keyboard.press(letter, options);
  }
  await page.keyboard.up(modifier);
  await pause(SETTLE_MS);
  await idle(page);
}

function modeState(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {editing: mode.isEditing, current: mode.currentNoteId, clipboardMode: mode.clipboardMode};
  });
}

function noteText(page, noteId) {
  return page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"] > .note-content`).textContent, noteId);
}

function rootOrder(page) {
  return page.evaluate(() => [...document.querySelectorAll('#notes-container > .note')].map(note => note.dataset.noteId));
}

function childrenOf(page, noteId) {
  return page.evaluate(id => [...document.querySelectorAll(`.note[data-note-id="${id}"] > .note-children > .note`)]
    .map(child => child.dataset.noteId), noteId);
}

async function copyNote(page, modifier, sourceId) {
  await startEditing(page, sourceId);
  await shortcut(page, modifier, 'c', false);
  assert.equal((await modeState(page)).clipboardMode, 'note', `${modifier}+C copies the edited note`);
}

// ⇧⌘V: the copy becomes the target's first child; the target's own text stays.
async function childPasteCase(page, modifier) {
  const label = `${modifier}+Shift+V`;
  const targetId = await createNote(page, '<p>Target note</p>');
  const sourceId = await createNote(page, '<p>The copied note</p>');
  await reloadApp(page);
  await copyNote(page, modifier, sourceId);
  await startEditing(page, targetId);
  await shortcut(page, modifier, 'v', true);
  assert.equal(await noteText(page, targetId), 'Target note', `${label}: the note's own text is unchanged`);
  const children = await childrenOf(page, targetId);
  assert.equal(children.length, 1, `${label}: one child is added`);
  assert.equal(await noteText(page, children[0]), 'The copied note', `${label}: the child is the copy`);
  await leaveEditing(page);
  await deleteNotes(page, [children[0], targetId, sourceId]);
}

// ⌘V on an empty note with no children fills it instead of adding a sibling.
async function emptyNoteCase(page, modifier) {
  const label = `${modifier}+V on an empty note`;
  const emptyId = await createNote(page, '');
  const sourceId = await createNote(page, '<p>The copied note</p>');
  await reloadApp(page);
  await copyNote(page, modifier, sourceId);
  await startEditing(page, emptyId);
  const rootsBefore = await rootOrder(page);
  await shortcut(page, modifier, 'v', false);
  assert.deepEqual(await rootOrder(page), rootsBefore, `${label}: no note is added`);
  assert.equal(await noteText(page, emptyId), 'The copied note', `${label}: the copy fills the note`);
  await leaveEditing(page);
  await deleteNotes(page, [emptyId, sourceId]);
}

// ⌘R and ⇧⌘R pasted references until 2026-10-26: now nothing happens, with a
// note copied or not, editing or not, and the browser's own reload does not run.
async function referenceKeysCase(page, modifier) {
  const targetId = await createNote(page, '<p>Target note</p>');
  const sourceId = await createNote(page, '<p>The copied note</p>');
  await reloadApp(page);
  await page.evaluate(() => { window.__noReloadMarker = true; });
  for (const isCopied of [false, true]) {
    if (isCopied) await copyNote(page, modifier, sourceId);
    for (const isEditing of [true, false]) {
      if (isEditing) await startEditing(page, targetId);
      if (!isEditing && (await modeState(page)).editing) await leaveEditing(page);
      const rootsBefore = await rootOrder(page);
      for (const withShift of [false, true]) {
        const label = `${modifier}+${withShift ? 'Shift+' : ''}R, ${isCopied ? 'a note copied' : 'nothing copied'}, ${isEditing ? 'editing' : 'not editing'}`;
        await shortcut(page, modifier, 'r', withShift);
        assert.equal(await page.evaluate(() => window.__noReloadMarker === true), true, `${label}: the page is not reloaded`);
        assert.deepEqual(await rootOrder(page), rootsBefore, `${label}: nothing is added`);
        assert.deepEqual(await childrenOf(page, targetId), [], `${label}: no child is added`);
        assert.equal(await noteText(page, targetId), 'Target note', `${label}: the note's text is unchanged`);
      }
    }
  }
  if ((await modeState(page)).editing) await leaveEditing(page);
  await deleteNotes(page, [targetId, sourceId]);
}

// A note of pasted images and no text, its images selected, right-clicked on an
// image: the image's menu opens (a selection of images was remembered as text
// positions, which images have none of, and the menu threw instead).
const PNG_BASE64 = 'iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAAQklEQVR4nO3OQQ0AIAwAsQlDBLKRhQuOR5MK6Jy9vjL5QEhISKgeCAkJCdUDISEhoXogJCQkVA+EhISE6oGQkNBjF21V9KbVaAsfAAAAAElFTkSuQmCC';
const IMAGE = `<img src="data:image/png;base64,${PNG_BASE64}" alt="dot">`;
const IMAGE_SIZE_ITEMS = ['Make Bigger', 'Make Smaller', 'Reset Size'];

async function selectedImagesMenuCase(page) {
  const targetId = await createNote(page, `<p>${IMAGE}${IMAGE}</p>`);
  await reloadApp(page);
  await startEditing(page, targetId);
  const imagePoint = await page.evaluate(id => {
    const content = document.querySelector(`.note[data-note-id="${id}"] > .note-content`);
    const images = content.querySelectorAll('img');
    if (images.length !== 2) throw new Error(`expected the two pasted images, found ${images.length}`);
    const range = document.createRange();
    range.setStartBefore(images[0]);
    range.setEndAfter(images[1]);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
    const box = images[0].getBoundingClientRect();
    return {x: box.left + box.width / 2, y: box.top + box.height / 2};
  }, targetId);
  await page.mouse.click(imagePoint.x, imagePoint.y, {button: 'right'});
  await page.waitForSelector('#context-menu.is-visible');
  const labels = await page.evaluate(() => [...document.querySelectorAll('#context-menu .context-menu-item')]
    .filter(item => item.offsetParent !== null).map(item => item.textContent.trim()));
  for (const item of IMAGE_SIZE_ITEMS) {
    assert(labels.some(label => label.startsWith(item)), `images selected, right-click on one: the image menu offers ${item} (${JSON.stringify(labels)})`);
  }
  await page.keyboard.press('Escape');
  await idle(page);
  if ((await modeState(page)).editing) await leaveEditing(page);
  await deleteNotes(page, [targetId]);
}

export async function checkNotePaste(page) {
  await reloadApp(page);
  for (const modifier of ['Meta', 'Control']) {
    if (pastesWith(modifier)) {
      await childPasteCase(page, modifier);
      await emptyNoteCase(page, modifier);
    }
    await referenceKeysCase(page, modifier);
  }
  await selectedImagesMenuCase(page);
  await reloadApp(page);
}
