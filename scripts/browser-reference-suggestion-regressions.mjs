import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Typing `[[` in a note opens a list of notes to reference (docs/ui/references.md,
// "Suggestions"; agreed 2026-10-26): exact first-line matches, then fuzzy ones,
// then matches in the text with a snippet, the most recently edited first in each;
// an @password note follows its parent, masked. The note copied last comes first
// whenever it matches. The list sits below the `[[`, the highlighted note's first
// lines float beside it; ↑/↓, pointing, and Enter, Tab or a click choose, putting
// `[[UUID]]` in place of `[[` and the typed text; Escape closes it and leaves the
// text. Nothing matching, or `[[@` (a wrapper tag), shows no list. Link to… and
// Embed… in the note menu type `[[` or `![[` where the right-click was
// (⌘R, which pasted references, is checked by browser-note-paste-regressions.mjs).
//
// The preview card (agreed 2026-10-26) shows the top of the note as the list draws
// it (Markdown rendered, a green heading, a password hidden), cut with a fade. The
// pointer resting 0.3 s on a `[[UUID]]` or `![[UUID]]` in the note being edited, or
// on a link elsewhere, shows it just below that line (above it near the window's
// bottom) from the link's left edge, moving nothing; passing over shows none;
// moving off, typing or a click hides it; a deleted note shows none; with the list
// open only the list's card shows.

const REQUESTS_QUIET_MS = 300;
// Longer than the list's wait for typing to settle (reference-suggestions-service.js).
const SETTLE_MS = 400;
// The list's gap below the `[[` (paste-format-offer-service.js), and the preview's beside the list.
const LIST_GAP_PX = 6;
const PREVIEW_GAP_PX = 6;
// A window wide enough for the preview beside the list.
const WIDE_WINDOW_PX = 1400;
const WINDOW_HEIGHT_PX = 800;
const WORD = 'Zephyrine';
const PASSWORD = 'hunter2-correct-horse';
const MASK = '••••••••';
// The pointer rests this long before a link's card shows (reference-hover-preview-service.js).
const HOVER_DELAY_MS = 300;
// Between a link's line and its card.
const HOVER_GAP_PX = 6;
// Long enough for a card to have shown had it been going to.
const CARD_WAIT_MS = 1000;
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
    ids.ears = await fill(await NotesAPI.createNote(null, ''),
      ['# Earsquill title', '---', 'Claude is **strong** here'].map(line => `<div>${line}</div>`).join(''), '@markdown');
    ids.green = await fill(await NotesAPI.createNote(null, ''), '<div>Verdigris heading</div>', '@heading @green');
    ids.long = await fill(await NotesAPI.createNote(null, ''),
      Array.from({length: 20}, (_, index) => `<div>Quillon line ${index + 1}</div>`).join(''), '');
    ids.gone = await make('<div>Soon deleted</div>');
    return ids;
  }, {word: WORD, password: PASSWORD});
}

function contentSelector(noteId) {
  return `.note[data-note-id="${noteId}"] > .note-content`;
}

// Just past the end of a note's text.
async function endOfText(page, noteId) {
  return page.evaluate(selector => {
    const range = document.createRange();
    range.selectNodeContents(document.querySelector(selector));
    const rects = range.getClientRects();
    const last = rects[rects.length - 1];
    return {x: last.right + 1, y: last.top + last.height / 2};
  }, contentSelector(noteId));
}

// Edits the note with the caret after its last letter: a click just past the end of its text.
async function editAtEnd(page, noteId) {
  await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), noteId);
  const end = await endOfText(page, noteId);
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

// The preview card once it shows `noteId`'s note: its text, what it holds, and where it sits
// (and the list's place, with the list open).
async function shownPreview(page, noteId) {
  await page.waitForSelector(`.reference-preview:not([hidden])[data-preview-note-id="${noteId}"]`);
  return page.evaluate(() => {
    const card = document.querySelector('.reference-preview');
    const root = card.shadowRoot;
    const box = card.getBoundingClientRect();
    const shown = {
      text: root.querySelector('.reference-preview-tree').innerText.split('\n').map(line => line.trim()).filter(Boolean),
      html: root.querySelector('.reference-preview-tree').innerHTML,
      isCut: root.querySelector('.reference-preview-clip').classList.contains('is-cut'),
      clipHeight: root.querySelector('.reference-preview-clip').getBoundingClientRect().height,
      left: box.left, top: box.top, bottom: box.bottom, height: box.height, windowHeight: window.innerHeight,
      treeHeight: root.querySelector('.reference-preview-tree').getBoundingClientRect().height,
    };
    const list = document.querySelector('.reference-suggestions');
    if (list === null) return shown;
    const listBox = list.getBoundingClientRect();
    const item = list.querySelector('.reference-suggestion.is-selected').getBoundingClientRect();
    return {...shown, listLeft: listBox.left, listRight: listBox.right, listTop: listBox.top, listBottom: listBox.bottom, itemTop: item.top};
  });
}

// Firefox lays out in sixtieths of a pixel: a place it reports agrees with one
// worked out from other boxes to that resolution.
const LAYOUT_UNIT_PX = 1 / 60;

function assertSamePixel(actual, expected, what) {
  assert.ok(Math.abs(actual - expected) <= LAYOUT_UNIT_PX, `${what}: ${actual}, expected ${expected}`);
}

function assertAt(card, place) {
  assertSamePixel(card.left, place.left, 'the card\'s left');
  assertSamePixel(card.top, place.top, 'the card\'s top');
}

// Under the list, or over it when the window's bottom leaves no room.
function underOrOverList(card) {
  const under = card.listBottom + PREVIEW_GAP_PX;
  if (under + card.height <= card.windowHeight) return under;
  return card.listTop - PREVIEW_GAP_PX - card.height;
}

async function isCardShown(page) {
  return page.evaluate(() => {
    const card = document.querySelector('.reference-preview');
    return card !== null && !card.hidden;
  });
}

// The box of the line under `[[`…`]]` (the `occurrence`th reference) in a note's text, and its middle.
async function referenceBox(page, noteId, occurrence) {
  return page.evaluate(({selector, occurrence}) => {
    const walker = document.createTreeWalker(document.querySelector(selector), NodeFilter.SHOW_TEXT);
    let seen = 0;
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      for (const match of node.data.matchAll(/!?\[\[[0-9a-f-]{36}\]\]/g)) {
        if (seen++ !== occurrence) continue;
        const range = document.createRange();
        range.setStart(node, match.index);
        range.setEnd(node, match.index + match[0].length);
        const line = range.getClientRects()[0];
        return {left: line.left, top: line.top, bottom: line.bottom, x: line.left + line.width / 2, y: line.top + line.height / 2};
      }
    }
    throw new Error(`no reference ${occurrence} in ${selector}`);
  }, {selector: contentSelector(noteId), occurrence});
}

// Where the caret and the page are: a card must move neither.
async function caretAndScroll(page) {
  return page.evaluate(() => {
    const selection = window.getSelection();
    return {node: selection.anchorNode.textContent, offset: selection.anchorOffset, scrollY: window.scrollY};
  });
}

// Right-clicks just past the end of the edited note's text and chooses `label` in the note menu.
async function chooseFromNoteMenu(page, noteId, label) {
  const end = await endOfText(page, noteId);
  await page.mouse.click(end.x, end.y, {button: 'right'});
  await page.waitForSelector('.context-menu.is-visible');
  const items = await page.$$('.context-menu.is-visible:not(.context-menu-submenu) .context-menu-item');
  for (const item of items) {
    if (await item.$eval('.context-menu-item-label', node => node.textContent) === label) {
      await item.click();
      return;
    }
  }
  throw new Error(`The note menu has no ${label}`);
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

  await attempt('the highlighted note shows its card beside the list, or under it; a password stays masked', async () => {
    const testWindow = page.viewport();
    await typeAndSettle(page, ` [[${word}`);
    const first = await shownPreview(page, ids.bank);
    assert.equal(first.text[0], `${WORD} bank login`);
    // The test window (800 px) has no room beside the list: the preview sits under it, or over it near the bottom.
    assertAt(first, {left: first.listLeft, top: underOrOverList(first)});
    await page.keyboard.press('ArrowDown');
    const masked = await shownPreview(page, ids.password);
    assert.equal(masked.html.includes('hunter2'), false);
    assert.equal(masked.text.join(' ').includes(MASK), true);
    await page.setViewport({width: WIDE_WINDOW_PX, height: WINDOW_HEIGHT_PX});
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowUp');
    // With room on the right: beside the list, level with the highlighted suggestion.
    const beside = await shownPreview(page, ids.password);
    assertAt(beside, {left: beside.listRight + PREVIEW_GAP_PX, top: beside.itemTop});
    await page.setViewport(testWindow);
  });

  await attempt('the card draws the note as the list does: Markdown, a green heading, cut with a fade', async () => {
    await typeAndSettle(page, ' [[earsquill');
    const ears = await shownPreview(page, ids.ears);
    assert.match(ears.html, /<h1[^>]*>Earsquill title<\/h1>/);
    assert.match(ears.html, /<hr/);
    assert.match(ears.html, /<strong>strong<\/strong>/);
    assert.equal(ears.isCut, false);
    await page.keyboard.press('Escape');
    await typeAndSettle(page, ' [[verdigris');
    assert.match((await shownPreview(page, ids.green)).html, /meta-heading[^"]*meta-green|meta-green[^"]*meta-heading/);
    await page.keyboard.press('Escape');
    await typeAndSettle(page, ' [[quillon');
    const long = await shownPreview(page, ids.long);
    assert.equal(long.isCut, true);
    assert.ok(long.clipHeight < long.treeHeight / 2, `the card shows the top of a long note (${long.clipHeight} of ${long.treeHeight} px)`);
  });

  await attempt('pointing at a suggestion highlights it, and its preview follows', async () => {
    await typeAndSettle(page, ` [[${word}`);
    const third = await page.$eval(`.reference-suggestion[data-note-id="${ids.garden}"]`, item => {
      const box = item.getBoundingClientRect();
      return {x: box.left + box.width / 2, y: box.top + box.height / 2};
    });
    await page.mouse.move(third.x, third.y);
    assert.equal((await shownList(page))[2].selected, true);
    assert.equal((await shownPreview(page, ids.garden)).text[0], `${WORD} garden plan`);
    assert.equal(await isEditing(page), true);
  });

  await attempt('Link to… types [[ where the right-click was and opens the list', async () => {
    await chooseFromNoteMenu(page, ids.holder, 'Link to…');
    await pause(SETTLE_MS);
    await idle(page);
    assert.equal(await noteText(page, ids.holder), 'Holder[[');
    assert.notEqual(await shownList(page), null);
    await typeAndSettle(page, 'garden plan');
    await page.keyboard.press('Enter');
    await idle(page);
    assert.equal(await noteText(page, ids.holder), `Holder[[${ids.garden}]]`);
  });

  await attempt('Embed… types ![[ and the chosen note goes in as an embed', async () => {
    await chooseFromNoteMenu(page, ids.holder, 'Embed…');
    await pause(SETTLE_MS);
    await idle(page);
    assert.equal(await noteText(page, ids.holder), 'Holder![[');
    await typeAndSettle(page, 'garden plan');
    await page.keyboard.press('Enter');
    await idle(page);
    assert.equal(await noteText(page, ids.holder), `Holder![[${ids.garden}]]`);
    await leaveEditing(page);
    assert.notEqual(await page.$(`.note[data-note-id="${ids.holder}"] .note-embed-block[data-ref-note-id="${ids.garden}"]`), null);
  });

  // A link's card: the pointer resting on `[[UUID]]` while editing, or on a link elsewhere.
  const writeLinks = async () => {
    await leaveEditing(page);
    await page.evaluate(async ({holder, ears, gone}) => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      await NotesAPI.saveNote(holder, `<div>Holder [[${ears}]] and ![[${ears}]] and [[${gone}]] end</div>`, '');
    }, ids);
    await reloadApp(page);
    await editAtEnd(page, ids.holder);
  };
  const restOn = async (point) => {
    await page.mouse.move(point.x, point.y);
    await pause(HOVER_DELAY_MS);
  };
  const moveAway = async () => {
    await page.mouse.move(1, 1);
    await pause(CARD_WAIT_MS);
  };

  await attempt('resting on [[UUID]] while editing shows its card below that line, moving nothing', async () => {
    await writeLinks();
    const before = await caretAndScroll(page);
    const link = await referenceBox(page, ids.holder, 0);
    await restOn(link);
    const card = await shownPreview(page, ids.ears);
    assert.equal(card.text[0], 'Earsquill title');
    assertAt(card, {left: link.left, top: link.bottom + HOVER_GAP_PX});
    assert.deepEqual(await caretAndScroll(page), before, 'the caret and the page stay put');
    await page.mouse.move(1, 1);
    assert.equal(await isCardShown(page), false, 'moving off hides it at once');
  });

  await attempt('resting on ![[UUID]] shows the same card; typing hides it', async () => {
    await writeLinks();
    await restOn(await referenceBox(page, ids.holder, 1));
    await shownPreview(page, ids.ears);
    await page.keyboard.type('x');
    assert.equal(await isCardShown(page), false);
    await moveAway();
  });

  await attempt('passing over a link, or resting on a deleted note\'s, shows no card', async () => {
    await writeLinks();
    const link = await referenceBox(page, ids.holder, 0);
    await page.mouse.move(link.x, link.y);
    await pause(HOVER_DELAY_MS / 3);
    await page.mouse.move(1, 1);
    await pause(CARD_WAIT_MS);
    assert.equal(await isCardShown(page), false);
    await page.evaluate(async id => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      await NotesAPI.deleteNote(id);
    }, ids.gone);
    await restOn(await referenceBox(page, ids.holder, 2));
    await pause(CARD_WAIT_MS);
    assert.equal(await isCardShown(page), false);
    await moveAway();
  });

  await attempt('with no room below, the card shows above the line', async () => {
    await writeLinks();
    await page.evaluate(selector => {
      // Room for the note's line only: the window's bottom just under it.
      const box = document.querySelector(selector).getBoundingClientRect();
      window.scrollBy({top: box.bottom - window.innerHeight + 4, behavior: 'instant'});
    }, contentSelector(ids.holder));
    // The scroll's own events end before the pointer comes.
    await pause(SETTLE_MS);
    const link = await referenceBox(page, ids.holder, 0);
    await restOn(link);
    const card = await shownPreview(page, ids.ears);
    assertSamePixel(card.bottom, link.top - HOVER_GAP_PX, 'the card\'s bottom');
    await moveAway();
  });

  await attempt('with the [[ list open, resting on a link shows only the list\'s card', async () => {
    await writeLinks();
    await typeAndSettle(page, ' [[garden');
    await shownPreview(page, ids.garden);
    await restOn(await referenceBox(page, ids.holder, 0));
    await pause(CARD_WAIT_MS);
    const card = await shownPreview(page, ids.garden);
    assertAt(card, {left: card.listLeft, top: underOrOverList(card)});
    await page.keyboard.press('Escape');
    await moveAway();
  });

  await attempt('not editing, resting on a link shows its card below it', async () => {
    await writeLinks();
    await leaveEditing(page);
    const link = await page.evaluate(id => {
      const block = document.querySelector(`.note[data-note-id="${id}"] .note-reference-link-mode[data-ref-note-id]`);
      const line = block.getClientRects()[0];
      return {left: line.left, bottom: line.bottom, x: line.left + line.width / 2, y: line.top + line.height / 2};
    }, ids.holder);
    await restOn(link);
    const card = await shownPreview(page, ids.ears);
    assertAt(card, {left: link.left, top: link.bottom + HOVER_GAP_PX});
    await moveAway();
  });

  // A card's note is not a note in the list: following the link to a note the view
  // doesn't show, after its card showed, brings that note in without an error
  // (the list took the card for the note; 2026-10-27).
  await attempt('following a link to a note the view doesn\'t show, after its card showed, opens it', async () => {
    await writeLinks();
    await leaveEditing(page);
    // With animated transitions, as reported: the list's collapse animation looked the note up first.
    await page.evaluate(() => document.body.classList.add('pref-animated-transitions'));
    await page.click('#search-input', {clickCount: 3});
    await page.keyboard.type('"Holder"');
    await pause(SETTLE_MS);
    await idle(page);
    assert.equal(await page.$(`#notes-container .note[data-note-id="${ids.ears}"]`), null, 'the search hides the linked note');
    const link = await page.evaluate(id => {
      const line = document.querySelector(`.note[data-note-id="${id}"] .note-reference-link-mode[data-ref-note-id]`).getClientRects()[0];
      return {x: line.left + line.width / 2, y: line.top + line.height / 2};
    }, ids.holder);
    await restOn(link);
    await shownPreview(page, ids.ears);
    await page.click(`.note[data-note-id="${ids.holder}"] .note-reference-link-mode[data-ref-note-id="${ids.ears}"] .note-reference-link-title`);
    await pause(SETTLE_MS);
    await idle(page);
    assert.equal(await page.$('#fatal-error-overlay'), null, 'no error');
    assert.notEqual(await page.$(`#notes-container .note[data-note-id="${ids.ears}"]`), null, 'the Source note view shows the linked note');
    // Back from the Source note view, and the search cleared.
    await page.keyboard.press('Escape');
    await idle(page);
    await page.click('#search-input', {clickCount: 3});
    await page.keyboard.press('Backspace');
    await pause(SETTLE_MS);
    await idle(page);
    await reloadApp(page);
  });

  // Last: the copied note stays first for every later `[[`.
  await attempt('the copied note comes first, even from a lower tier, and with nothing typed', async () => {
    await page.evaluate(async id => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      await NotesAPI.copyNote(id);
    }, ids.content);
    await typeAndSettle(page, ` [[${word}`);
    assert.deepEqual((await shownList(page)).map(item => item.noteId), [ids.content, ids.bank, ids.password, ids.garden]);
    await page.keyboard.press('Escape');
    await typeAndSettle(page, ' [[');
    assert.equal((await shownList(page))[0].noteId, ids.content);
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
      for (const id of [ids.holder, ids.content, ids.garden, ids.bank, ids.ears, ids.green, ids.long]) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
