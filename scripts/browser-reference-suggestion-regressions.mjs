import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Typing `[[` in a note opens a list of notes to reference (docs/ui/references.md,
// "Suggestions"; agreed 2026-10-26): exact first-line matches, then fuzzy ones,
// then matches in the text with a snippet, the most recently edited first in each;
// an @password note follows its parent, masked. The list sits below the `[[`;
// ↑/↓ and Enter, Tab or a click choose, putting `[[UUID]]` in place of `[[` and
// the typed text; Escape closes it and leaves the text. Nothing matching, or
// `[[@` (a wrapper tag), shows no list.

const REQUESTS_QUIET_MS = 300;
// Longer than the list's wait for typing to settle (reference-suggestions-service.js).
const SETTLE_MS = 400;
// The list's gap below the `[[` (paste-format-offer-service.js).
const LIST_GAP_PX = 6;
const WORD = 'Zephyrine';
const PASSWORD = 'hunter2-correct-horse';
const MASK = '••••••••';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function reloadApp(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
}

// Made oldest first: each later one is the more recently edited.
async function seedNotes(page) {
  return page.evaluate(async ({word, password}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const fill = async (note, html, tags) => {
      await NotesAPI.saveNote(note.id, html, tags);
      return note.id;
    };
    const make = async html => fill(await NotesAPI.createNote(null, ''), html, '');
    const ids = {};
    ids.content = await make(`<div>Trip notes</div><div>We put up the ${word} trellis by the shed</div>`);
    ids.garden = await make(`<div>${word} garden plan</div>`);
    ids.bank = await make(`<div>${word} bank login</div>`);
    ids.password = await fill(await NotesAPI.createChild(ids.bank, ''), `<div>${password}</div>`, '@password');
    ids.holder = await make('<div>Holder</div>');
    return ids;
  }, {word: WORD, password: PASSWORD});
}

function contentSelector(noteId) {
  return `.note[data-note-id="${noteId}"] > .note-content`;
}

// Edits the note with the caret after its last letter: a click just past the end of its text.
async function editAtEnd(page, noteId) {
  await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), noteId);
  const end = await page.evaluate(selector => {
    const range = document.createRange();
    range.selectNodeContents(document.querySelector(selector));
    const rects = range.getClientRects();
    const last = rects[rects.length - 1];
    return {x: last.right + 1, y: last.top + last.height / 2};
  }, contentSelector(noteId));
  await page.mouse.click(end.x, end.y);
  await page.waitForFunction(async id => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode.isEditing && mode.currentNoteId === id;
  }, {}, noteId);
  await idle(page);
  const caret = await page.evaluate(selector => {
    const selection = window.getSelection();
    const content = document.querySelector(selector);
    const before = document.createRange();
    before.selectNodeContents(content);
    before.setEnd(selection.anchorNode, selection.anchorOffset);
    return {before: before.toString(), all: content.textContent};
  }, contentSelector(noteId));
  assert.equal(caret.before, caret.all, 'the caret is after the last letter');
}

async function leaveEditing(page) {
  await page.keyboard.press('Escape');
  await idle(page);
}

async function typeAndSettle(page, text) {
  await page.keyboard.type(text);
  await pause(SETTLE_MS);
  await idle(page);
}

async function shownList(page) {
  return page.evaluate(() => {
    const list = document.querySelector('.reference-suggestions');
    if (list === null) return null;
    // The text of what an item has of each part; '' for a part it has none of.
    const textsOf = (item, selector) => [...item.querySelectorAll(selector)].map(part => part.textContent).join('');
    return [...list.querySelectorAll('.reference-suggestion')].map(item => ({
      noteId: item.dataset.noteId,
      text: textsOf(item, '.reference-suggestion-text'),
      context: textsOf(item, '.reference-suggestion-context'),
      match: textsOf(item, '.reference-suggestion-snippet mark'),
      icon: [...item.querySelectorAll('.reference-suggestion-icon')].map(icon => icon.getAttribute('aria-label')).join(''),
      selected: item.classList.contains('is-selected'),
    }));
  });
}

async function noteText(page, noteId) {
  return page.$eval(contentSelector(noteId), content => content.textContent);
}

async function isEditing(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    return mode.isEditing;
  });
}

// Puts the holder back to its one word, editing it with the caret at the end.
async function resetHolder(page, ids) {
  if (await isEditing(page)) await leaveEditing(page);
  await page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.saveNote(id, '<div>Holder</div>', '');
  }, ids.holder);
  await reloadApp(page);
  await editAtEnd(page, ids.holder);
}

async function suggestionCases(page, ids) {
  const failures = [];
  const attempt = async (label, run) => {
    await resetHolder(page, ids);
    try {
      await run();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  };
  const word = WORD.toLowerCase();

  await attempt('the tiers in order, the password masked after its parent', async () => {
    await typeAndSettle(page, ` [[${word}`);
    const shown = await shownList(page);
    assert.deepEqual(shown.map(item => item.noteId), [ids.bank, ids.password, ids.garden, ids.content]);
    assert.deepEqual(shown[1], {
      noteId: ids.password, text: MASK, context: `${WORD} bank login`, match: '', icon: 'Password', selected: false,
    });
    assert.equal(shown[0].selected, true);
    assert.equal(shown[3].match, WORD);
    assert.equal(await page.$eval('.reference-suggestions', list => list.textContent.includes('hunter2')), false);
  });

  await attempt('the list sits just below the [[', async () => {
    await typeAndSettle(page, ' [[garden');
    const place = await page.evaluate(selector => {
      const text = [...document.querySelector(selector).childNodes].flatMap(function walk(node) {
        return node.nodeType === Node.TEXT_NODE ? [node] : [...node.childNodes].flatMap(walk);
      }).find(node => node.data.includes('[['));
      const range = document.createRange();
      const start = text.data.lastIndexOf('[[');
      range.setStart(text, start);
      range.setEnd(text, start + 2);
      const anchor = range.getBoundingClientRect();
      const list = document.querySelector('.reference-suggestions').getBoundingClientRect();
      return {left: list.left, top: list.top, anchorLeft: Math.round(anchor.left), anchorBottom: anchor.bottom};
    }, contentSelector(ids.holder));
    assert.deepEqual({left: place.left, top: place.top},
      {left: place.anchorLeft, top: Math.round(place.anchorBottom + LIST_GAP_PX)});
  });

  await attempt('↓ and Enter choose, as [[UUID]] in place of the typed text', async () => {
    await typeAndSettle(page, ` [[${word}`);
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    assert.equal((await shownList(page))[2].selected, true);
    await page.keyboard.press('Enter');
    await idle(page);
    assert.equal(await noteText(page, ids.holder), `Holder [[${ids.garden}]]`);
    assert.equal(await shownList(page), null);
    assert.equal(await isEditing(page), true);
  });

  await attempt('Tab chooses the selected note', async () => {
    await typeAndSettle(page, ' [[garden plan');
    await page.keyboard.press('Tab');
    await idle(page);
    assert.equal(await noteText(page, ids.holder), `Holder [[${ids.garden}]]`);
  });

  await attempt('a click chooses, and the reference shows as a link', async () => {
    await typeAndSettle(page, ` [[${word} gardn`);
    await page.click(`.reference-suggestion[data-note-id="${ids.garden}"]`);
    await idle(page);
    assert.equal(await noteText(page, ids.holder), `Holder [[${ids.garden}]]`);
    // The click ends where the list was: it neither leaves the note nor reaches what was under the list.
    assert.equal(await page.evaluate(async () => {
      const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
      return mode.currentNoteId;
    }), ids.holder);
    await leaveEditing(page);
    assert.equal(await page.$(`.note[data-note-id="${ids.holder}"] .note-reference-link[data-ref-note-id="${ids.garden}"]`) !== null, true);
  });

  await attempt('Escape closes the list, leaves the text and stays in the note', async () => {
    await typeAndSettle(page, ' [[garden');
    assert.notEqual(await shownList(page), null);
    await page.keyboard.press('Escape');
    await idle(page);
    assert.equal(await shownList(page), null);
    assert.equal(await isEditing(page), true);
    await typeAndSettle(page, ' plan');
    assert.equal(await shownList(page), null);
    assert.equal(await noteText(page, ids.holder), 'Holder [[garden plan');
  });

  await attempt('nothing matching shows no list', async () => {
    await typeAndSettle(page, ' [[qqxxzzyy');
    assert.equal(await shownList(page), null);
    assert.equal(await noteText(page, ids.holder), 'Holder [[qqxxzzyy');
  });

  await attempt('[[@ starts a wrapper tag, not a reference', async () => {
    await typeAndSettle(page, ' [[@');
    assert.equal(await shownList(page), null);
  });

  await attempt('moving the caret away from the [[ closes the list', async () => {
    const typed = ' [[garden';
    await typeAndSettle(page, typed);
    assert.notEqual(await shownList(page), null);
    // Back before what was typed (Home moves no caret in Firefox on a Mac).
    for (const _ of typed) await page.keyboard.press('ArrowLeft');
    await pause(SETTLE_MS);
    assert.equal(await shownList(page), null);
  });

  if (await isEditing(page)) await leaveEditing(page);
  assert.deepEqual(failures, []);
}

export async function checkReferenceSuggestions(page) {
  const ids = await seedNotes(page);
  await reloadApp(page);
  await runThenCleanUp('reference suggestions', () => suggestionCases(page, ids), async () => {
    await reloadApp(page);
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of [ids.holder, ids.content, ids.garden, ids.bank]) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
