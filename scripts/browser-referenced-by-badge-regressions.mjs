import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// The backlinks icon (docs/ui/references.md; the link icon mirrored since 2026-11-14, a number in a
// circle before): at the top right of a referenced note's first line, centred on it, the same size
// in an open and a collapsed note; the first line's text never runs under it; beside an embed
// holder's ↗; the count is in its tooltip, and nothing is written as text. A click (or Enter)
// opens Backlinks, also while another note is being edited: that note is saved and left first.

const WINDOW = {width: 1100, height: 800};
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
// Sub-pixel layout rounds each edge to a device pixel at most.
const PIXEL_ROUNDING = 0.5;
// The icon is this many of the note's ems wide and high (main.css, .note-backlinks-badge).
const ICON_SIZE_EM = 1.2;
// The link icon, mirrored left to right.
const MIRRORED = 'matrix(-1, 0, 0, 1, 0, 0)';
const KYOTO_REFERRERS = 3;
const READING_REFERRERS = 12;
const PACKING_REFERRERS = 150;
const LONG_LINE = 'with a first line long enough to run past the badge and wrap or be cut when the note is collapsed';
const TYPED = 'zq';

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
  return page.evaluate(async counts => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const make = async html => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, '');
      return note.id;
    };
    const child = async (parentId, html) => {
      const note = await NotesAPI.createChild(parentId, '');
      await NotesAPI.saveNote(note.id, html, '');
      return note.id;
    };
    const plain = await make('<div>Nothing references this note</div>');
    const packing = await make(`<div>Packing list ${counts.longLine}</div>`);
    const reading = await make(`<div>Reading list ${counts.longLine}</div>`);
    const recipe = await make('<div>Sourdough recipe</div>');
    const kyoto = await make('<div>Kyoto trip plan</div><div>Day 1: temples</div>');
    const holder = await make(`<div>![[${recipe}]]</div>`);
    const readingReferrers = await make('<div>Reading referrers</div>');
    for (let index = 0; index < counts.reading; index += 1) await child(readingReferrers, `<div>Book [[${reading}]]</div>`);
    const packingReferrers = await make('<div>Packing referrers</div>');
    for (let index = 0; index < counts.packing; index += 1) await child(packingReferrers, `<div>Trip [[${packing}]]</div>`);
    await NotesAPI.setCollapsedBulk([readingReferrers, packingReferrers, reading], true);
    const kyotoReferrers = [];
    for (const word of ['Flights', 'Hotel', 'Budget']) kyotoReferrers.push(await make(`<div>${word} for [[${kyoto}]]</div>`));
    await make(`<div>Links the holder [[${holder}]]</div>`);
    return {plain, packing, reading, recipe, kyoto, holder, readingReferrers, packingReferrers, kyotoReferrers};
  }, {longLine: LONG_LINE, reading: READING_REFERRERS, packing: PACKING_REFERRERS});
}

const contentOf = id => `#notes-container .note[data-note-id="${id}"] > .note-content`;
const badgeOf = id => `${contentOf(id)} .note-backlinks-badge`;

// The badge against the first line of the text beside it (an embed holder: its embed's text).
async function measureBadge(page, id) {
  return page.evaluate(selector => {
    const badge = document.querySelector(selector);
    const wrapper = badge.parentElement;
    const textElement = wrapper.classList.contains('note-reference-only')
      ? wrapper.querySelector('.note-embed-content')
      : [...wrapper.children].find(child => child !== badge);
    const range = document.createRange();
    range.selectNodeContents(textElement);
    const lineRects = [...range.getClientRects()].filter(rect => rect.width > 0);
    const firstTop = Math.min(...lineRects.map(rect => rect.top));
    const firstLine = lineRects.filter(rect => rect.top - firstTop < 1);
    const box = badge.getBoundingClientRect();
    const arrow = wrapper.querySelector('.note-embed-with-source > .note-source-arrow > span');
    const style = getComputedStyle(badge);
    return {
      drawn: getComputedStyle(badge, '::after').content,
      text: badge.textContent,
      mask: style.maskImage === undefined ? style.webkitMaskImage : style.maskImage,
      transform: style.transform,
      title: badge.title,
      isCollapsed: badge.closest('.note').classList.contains('collapsed'),
      noteFont: parseFloat(getComputedStyle(wrapper).fontSize),
      badgeWidth: box.width, badgeHeight: box.height,
      badgeLeft: box.left, badgeRight: box.right, badgeCentre: box.top + box.height / 2,
      lineRight: Math.max(...firstLine.map(rect => rect.right)),
      lineCentre: firstLine[0].top + firstLine[0].height / 2,
      lineHeight: firstLine[0].height,
      arrowLeft: arrow === null ? null : arrow.getBoundingClientRect().left,
    };
  }, badgeOf(id));
}

function checkBadge(box, label, title, isCollapsed) {
  assert.ok(box.mask.includes('svg'), `${label}: the badge is the link icon (${box.mask.slice(0, 40)})`);
  assert.equal(box.transform, MIRRORED, `${label}: mirrored, its arrow pointing back`);
  assert.ok(box.drawn === 'none' || box.drawn === 'normal', `${label}: no number drawn (${box.drawn})`);
  assert.equal(box.text, '', `${label}: nothing written as text`);
  assert.equal(box.title, title, `${label}: the tooltip gives the count`);
  assert.equal(box.isCollapsed, isCollapsed, `${label}: the note is ${isCollapsed ? '' : 'not '}collapsed`);
  for (const [side, size] of [['wide', box.badgeWidth], ['high', box.badgeHeight]]) {
    assert.ok(Math.abs(size - box.noteFont * ICON_SIZE_EM) <= PIXEL_ROUNDING,
      `${label}: the icon is ${ICON_SIZE_EM} of the note's text ${side} (${size} vs ${box.noteFont})`);
  }
  assert.ok(Math.abs(box.badgeCentre - box.lineCentre) <= Math.max(box.lineHeight - box.badgeHeight, 0) / 2 + PIXEL_ROUNDING,
    `${label}: the icon is centred on the first line (${box.badgeCentre} vs ${box.lineCentre})`);
  assert.ok(box.lineRight <= box.badgeLeft + PIXEL_ROUNDING,
    `${label}: the first line's text ends before the badge (${box.lineRight} vs ${box.badgeLeft})`);
  if (box.arrowLeft !== null) {
    assert.ok(box.badgeRight <= box.arrowLeft + PIXEL_ROUNDING,
      `${label}: the badge sits before the embed's ↗ (${box.badgeRight} vs ${box.arrowLeft})`);
  }
}

async function layoutCases(page, ids) {
  const failures = [];
  const check = async (label, id, number, isCollapsed) => {
    const measured = await measureBadge(page, id);
    try {
      checkBadge(measured, label, number, isCollapsed);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(error.message);
    }
  };
  await check('a note three notes reference', ids.kyoto, `${KYOTO_REFERRERS} backlinks`, false);
  await check('twelve, collapsed', ids.reading, `${READING_REFERRERS} backlinks`, true);
  await check('a hundred and fifty, wrapping', ids.packing, `${PACKING_REFERRERS} backlinks`, false);
  await check('an embed holder', ids.holder, '1 backlink', false);
  await check('the embedded source', ids.recipe, '1 backlink', false);
  const unreferenced = await page.$(badgeOf(ids.plain));
  if (unreferenced !== null) failures.push('a note nothing references shows no icon');
  assert.deepEqual(failures, []);
}

async function rootIds(page) {
  return page.$$eval('#notes-container > .note', notes => notes.map(note => note.dataset.noteId));
}

async function clickWhileEditing(page, ids) {
  await page.click(contentOf(ids.plain));
  await idle(page);
  await page.keyboard.press('End');
  await page.keyboard.type(TYPED);
  await page.click(badgeOf(ids.kyoto));
  await idle(page);
  const opened = await page.evaluate(async () => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return {isEditing: ModeContextInstance.isEditing};
  });
  assert.deepEqual(opened, {isEditing: false}, 'the edited note was left');
  assert.deepEqual(new Set(await rootIds(page)), new Set(ids.kyotoReferrers), 'Backlinks lists the referring notes');
  await page.keyboard.press('Escape');
  await idle(page);
  const plainText = await page.$eval(contentOf(ids.plain), content => content.textContent);
  assert.ok(plainText.includes(TYPED), `the edited note was saved before the view opened: ${plainText}`);
}

async function keyboardOpens(page, ids) {
  await page.focus(badgeOf(ids.kyoto));
  await page.keyboard.press('Enter');
  await idle(page);
  assert.deepEqual(new Set(await rootIds(page)), new Set(ids.kyotoReferrers), 'Enter on the icon opens Backlinks');
  await page.keyboard.press('Escape');
  await idle(page);
}

export async function checkReferencedByBadge(page) {
  await page.setViewport(WINDOW);
  const ids = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('backlinks icon', async () => {
    await layoutCases(page, ids);
    await keyboardOpens(page, ids);
    await clickWhileEditing(page, ids);
  }, async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      const roots = [ids.plain, ids.packing, ids.reading, ids.recipe, ids.kyoto, ids.holder,
        ids.readingReferrers, ids.packingReferrers, ...ids.kyotoReferrers];
      for (const id of roots) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
