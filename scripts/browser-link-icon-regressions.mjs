import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// A site's icon before a fetched link title (docs/ui/content-formatting.md, Link icons;
// agreed 2026-10-25): as tall as the title's text and centred on it, a fixed gap before the
// text, in an open note, a collapsed note and a compact reference alike; in the dark theme
// on a light tile. The test server fetches nothing, so each case writes the markup the
// server renders for a titled link with an icon into the rendered view and measures it.

const WINDOW = {width: 1280, height: 800};
const URL = 'https://example.com/article';
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const GAP_EM = 0.3;
// Sub-pixel layout rounds each edge to a device pixel at most.
const PIXEL_ROUNDING = 0.5;
// A margin is placed on the layout grid: 1/64 px in Chrome, 1/60 px in Firefox.
const GAP_PRECISION = 1 / 60;
const TILE = 'rgb(233, 237, 242)';
// A note link's icon follows its text at this gap (main.css, .note-reference-link-icon).
const NOTE_LINK_ICON_GAP_EM = 0.2;
const LONG_FIRST_LINE = 'Make up avatars for your various agents the same way you would in a video game, '
  + 'where you can choose their faces, clothes and voices, and then keep them for every conversation you have';
const NO_TILE = 'rgba(0, 0, 0, 0)';

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
  return page.evaluate(async (url, longFirstLine) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const make = async html => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, '');
      return note.id;
    };
    const open = await make(`<p>${url}</p><p>open note</p>`);
    const collapsed = await make(`<p>${url}</p><p>collapsed note</p>`);
    await NotesAPI.setCollapsedBulk([collapsed], true);
    const target = await make(`<p>${url}</p><p>referenced note</p>`);
    const holder = await make(`<p>See [[${target}]] here</p>`);
    // A link with its own text inside a sentence, as the server draws it (agreed 2026-10-26).
    const sentence = await make(`<p>Read <a href="${url}">the paper on recurrent networks</a> before Monday.</p>`);
    // Note links whose text is longer than the line (reported 2026-10-28: the icon wrapped below).
    const longTarget = await make(`<p>${longFirstLine}</p>`);
    const shortTarget = await make('<p>liv lab</p>');
    const longLink = await make(`<p>[[${shortTarget}]]</p><p>[[${longTarget}]]</p>`);
    const longLinkCollapsed = await make(`<p>[[${longTarget}]]</p><p>second line</p>`);
    await NotesAPI.setCollapsedBulk([longLinkCollapsed], true);
    const longLinkAfterText = await make(`<p>See [[${longTarget}]]</p>`);
    return {open, collapsed, target, holder, sentence, longTarget, shortTarget, longLink, longLinkCollapsed, longLinkAfterText};
  }, URL, LONG_FIRST_LINE);
}

// Writes the server's markup for a titled link with an icon in place of the plain link
// (or of the compact reference's preview) and measures the icon against the title's text.
async function measure(page, selector) {
  return page.evaluate(selector => {
    const canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    canvas.getContext('2d').fillRect(0, 0, canvas.width, canvas.height);
    const host = document.querySelector(selector);
    if (host.tagName === 'A') host.className = 'link-title';
    host.innerHTML = `<img class="link-title-icon" src="${canvas.toDataURL('image/png')}" alt="">`
      + '<span class="link-title-text">An Article</span><span class="link-title-domain"> · example.com</span>';
    const icon = host.querySelector('img.link-title-icon').getBoundingClientRect();
    const text = host.querySelector('.link-title-text');
    const textBox = text.getBoundingClientRect();
    return {
      fontSize: parseFloat(getComputedStyle(text).fontSize),
      width: icon.width, height: icon.height,
      iconCentre: icon.top + icon.height / 2, textCentre: textBox.top + textBox.height / 2,
      gap: textBox.left - icon.right,
      background: getComputedStyle(host.querySelector('img.link-title-icon')).backgroundColor,
      screenPixel: 1 / window.devicePixelRatio,
    };
  }, selector);
}

function assertIconFitsText(box, label, background) {
  assert.equal(box.width, box.fontSize, `${label}: the icon is as wide as the text is tall`);
  assert.equal(box.height, box.fontSize, `${label}: the icon is as tall as the text`);
  // Within one screen pixel: the icon's offset is tuned to the Mac's font, and with Linux's
  // font on a 1x screen it lands 0.9 px off (agreed 2026-10-28).
  assert.equal(typeof box.screenPixel, 'number', `${label}: the measurement gives the screen pixel`);
  assert.ok(Math.abs(box.iconCentre - box.textCentre) <= Math.max(PIXEL_ROUNDING, box.screenPixel),
    `${label}: the icon is centred on the text (${box.iconCentre} vs ${box.textCentre})`);
  assert.ok(Math.abs(box.gap - box.fontSize * GAP_EM) <= GAP_PRECISION,
    `${label}: the gap before the text is ${GAP_EM}em (${box.gap}px at ${box.fontSize}px)`);
  assert.equal(box.background, background, `${label}: the tile behind the icon`);
}

const noteLink = id => `#notes-container .note[data-note-id="${id}"] > .note-content a[href="${URL}"]`;

async function inTheme(page, theme, run) {
  const original = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
  await page.evaluate(theme => document.documentElement.setAttribute('data-theme', theme), theme);
  try {
    return await run();
  } finally {
    await page.evaluate(original => {
      if (original === null) document.documentElement.removeAttribute('data-theme');
      else document.documentElement.setAttribute('data-theme', original);
    }, original);
  }
}

async function iconCases(page, ids) {
  const failures = [];
  const check = async (label, theme, selector, background) => {
    const box = await inTheme(page, theme, () => measure(page, selector));
    try {
      assertIconFitsText(box, label, background);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(error.message);
    }
  };
  const isCollapsed = await page.$eval(`#notes-container .note[data-note-id="${ids.collapsed}"]`,
    note => note.classList.contains('collapsed'));
  assert.equal(isCollapsed, true, 'the collapsed note is shown collapsed');
  await check('open note, light', 'light', noteLink(ids.open), NO_TILE);
  await check('open note, dark', 'dark', noteLink(ids.open), TILE);
  await check('collapsed note, light', 'light', noteLink(ids.collapsed), NO_TILE);
  await check('collapsed note, dark', 'dark', noteLink(ids.collapsed), TILE);
  const reference = `#notes-container .note[data-note-id="${ids.holder}"] > .note-content `
    + `.note-reference-link[data-ref-note-id="${ids.target}"] .note-reference-link-title`;
  await check('compact reference, light', 'light', reference, NO_TILE);
  await check('compact reference, dark', 'dark', reference, TILE);
  try {
    await sentenceCase(page, ids);
  } catch (error) {
    if (!(error instanceof assert.AssertionError)) throw error;
    failures.push(error.message);
  }
  const checkNoteLink = async (label, holderId, targetId, isCut) => {
    try {
      assertNoteLinkIconFollowsText(await measureNoteLink(page, holderId, targetId), label, isCut);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(error.message);
    }
  };
  await checkNoteLink('a short note link', ids.longLink, ids.shortTarget, false);
  await checkNoteLink('a note link longer than its line', ids.longLink, ids.longTarget, true);
  await checkNoteLink('a note link longer than its line, collapsed', ids.longLinkCollapsed, ids.longTarget, true);
  await checkNoteLink('a note link longer than its line, after text', ids.longLinkAfterText, ids.longTarget, true);
  assert.deepEqual(failures, []);
}

// A note link's icon follows its text on the same line, also when the text is cut with "…"
// to fit the line (docs/ui/references.md, Links).
async function measureNoteLink(page, holderId, targetId) {
  return page.evaluate((holderId, targetId) => {
    const content = document.querySelector(`#notes-container .note[data-note-id="${holderId}"] > .note-content`);
    const link = content.querySelector(`.note-reference-link[data-ref-note-id="${targetId}"]`);
    const title = link.querySelector('.note-reference-link-title').getBoundingClientRect();
    const titleElement = link.querySelector('.note-reference-link-title');
    const icon = link.querySelector('.note-reference-link-icon').getBoundingClientRect();
    return {
      fontSize: parseFloat(getComputedStyle(link).fontSize),
      titleTop: title.top, titleBottom: title.bottom, titleRight: title.right,
      iconLeft: icon.left, iconRight: icon.right, iconCentre: icon.top + icon.height / 2,
      contentRight: content.getBoundingClientRect().right,
      isCut: titleElement.scrollWidth > titleElement.clientWidth,
    };
  }, holderId, targetId);
}

function assertNoteLinkIconFollowsText(box, label, isCut) {
  assert.equal(box.isCut, isCut, `${label}: the text is ${isCut ? '' : 'not '}cut with "…"`);
  assert.ok(box.iconCentre > box.titleTop && box.iconCentre < box.titleBottom,
    `${label}: the icon is on the text's line (icon centre ${box.iconCentre}, text ${box.titleTop}–${box.titleBottom})`);
  assert.ok(Math.abs(box.iconLeft - box.titleRight - box.fontSize * NOTE_LINK_ICON_GAP_EM) <= PIXEL_ROUNDING,
    `${label}: the icon follows the text at ${NOTE_LINK_ICON_GAP_EM}em (${box.iconLeft - box.titleRight}px)`);
  assert.ok(box.iconRight <= box.contentRight + PIXEL_ROUNDING,
    `${label}: the icon stays inside the note (${box.iconRight} vs ${box.contentRight})`);
}

// A link with its own text in a sentence: the server draws its text and " · example.com"
// (the test server fetches no icon); with its icon added, it sits as a titled link's does.
async function sentenceCase(page, ids) {
  const selector = `#notes-container .note[data-note-id="${ids.sentence}"] > .note-content a[href="${URL}"]`;
  const drawn = await page.$eval(selector, link => ({
    isTitled: link.classList.contains('link-title'),
    text: link.textContent,
    sentence: link.parentElement.textContent,
  }));
  assert.deepEqual(drawn, {
    isTitled: true,
    text: 'the paper on recurrent networks · example.com',
    sentence: 'Read the paper on recurrent networks · example.com before Monday.',
  }, 'a link with its own text in a sentence: its text, then its domain');
  const box = await page.evaluate(selector => {
    const canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    canvas.getContext('2d').fillRect(0, 0, canvas.width, canvas.height);
    const link = document.querySelector(selector);
    const icon = document.createElement('img');
    icon.className = 'link-title-icon';
    icon.alt = '';
    icon.src = canvas.toDataURL('image/png');
    link.prepend(icon);
    const iconBox = icon.getBoundingClientRect();
    const range = document.createRange();
    range.setStart(link.childNodes[1], 0);
    range.setEnd(link.childNodes[1], 1);
    const letter = range.getBoundingClientRect();
    return {
      fontSize: parseFloat(getComputedStyle(link).fontSize),
      width: iconBox.width, height: iconBox.height,
      iconCentre: iconBox.top + iconBox.height / 2, textCentre: letter.top + letter.height / 2,
      screenPixel: 1 / window.devicePixelRatio,
      gap: letter.left - iconBox.right,
      background: getComputedStyle(icon).backgroundColor,
    };
  }, selector);
  assertIconFitsText(box, 'a link with its own text in a sentence', NO_TILE);
}

export async function checkLinkIcons(page) {
  await page.setViewport(WINDOW);
  const ids = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('link icons', () => iconCases(page, ids), async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of Object.values(ids)) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
