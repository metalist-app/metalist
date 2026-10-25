import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// The menu past the notes (right-click beside the list, not on a note) fits a window 800 px
// tall without scrolling (agreed 2026-10-25): related actions sit in submenus, as Move does in
// the note menu. Checked in its longest form: a note copied and the list scrolled to the
// middle, so Add and Go to each hold all their actions.

const WINDOW = {width: 1280, height: 800};
const NOTE_COUNT = 40;
// Past the notes: right of the list, left of the floating buttons.
const BESIDE_LIST_X = 1150;
const BESIDE_LIST_Y = 400;
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const EXPECTED_ROWS = [
  'Add', 'Undo', 'Redo', 'Go to', 'Outline', 'View', 'Sort by', 'Date Range', 'Notes with Files', 'Show',
  'Open', 'Export & Print', 'Log Out',
];

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
  return page.evaluate(async count => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const ids = [];
    for (let index = 0; index < count; index += 1) {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<p>View menu note ${index}</p>`, '');
      ids.push(note.id);
    }
    return ids;
  }, NOTE_COUNT);
}

async function clickMenuItem(page, label) {
  const item = await page.evaluateHandle(text => [...document.querySelectorAll('#context-menu.is-visible .context-menu-item')]
    .find(node => node.querySelector('.context-menu-item-label').textContent.trim() === text), label);
  assert.notEqual(item.asElement(), null, `the menu offers ${label}`);
  await item.asElement().click();
  await idle(page);
}

async function copyANote(page) {
  const box = await page.evaluate(() => {
    const inView = [...document.querySelectorAll('.note > .note-content')]
      .find(node => node.getBoundingClientRect().top > 0 && node.getBoundingClientRect().bottom < window.innerHeight);
    const rect = inView.getBoundingClientRect();
    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
  });
  await page.mouse.click(box.x, box.y, {button: 'right'});
  await page.waitForSelector('#context-menu.is-visible');
  await clickMenuItem(page, 'Copy Note');
}

async function fitCase(page) {
  await page.evaluate(() => window.scrollTo(0, (document.documentElement.scrollHeight - window.innerHeight) / 2));
  await idle(page);
  await copyANote(page);
  await page.mouse.click(BESIDE_LIST_X, BESIDE_LIST_Y, {button: 'right'});
  await page.waitForSelector('#context-menu.is-visible');
  await settle(page);
  const menu = await page.$eval('#context-menu', node => {
    const rect = node.getBoundingClientRect();
    return {
      rows: [...node.querySelectorAll(':scope .context-menu-item-label')].map(label => label.textContent.trim()),
      top: rect.top, bottom: rect.bottom,
      scrollHeight: node.scrollHeight, clientHeight: node.clientHeight,
    };
  });
  assert.deepEqual(menu.rows, EXPECTED_ROWS, 'the menu past the notes shows its groups');
  assert.equal(menu.scrollHeight, menu.clientHeight, 'the menu past the notes does not scroll');
  assert.equal(menu.top >= 0 && menu.bottom <= WINDOW.height, true, 'the menu past the notes fits the window');
  await page.keyboard.press('Escape');
  await idle(page);
}

export async function checkViewMenu(page) {
  await page.setViewport(WINDOW);
  const noteIds = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('view menu', () => fitCase(page), async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, noteIds);
  });
}
