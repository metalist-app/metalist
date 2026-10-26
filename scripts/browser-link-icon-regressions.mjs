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
const GAP_PRECISION = 0.01;
const TILE = 'rgb(233, 237, 242)';
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
  return page.evaluate(async url => {
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
    return {open, collapsed, target, holder};
  }, URL);
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
    };
  }, selector);
}

function assertIconFitsText(box, label, background) {
  assert.equal(box.width, box.fontSize, `${label}: the icon is as wide as the text is tall`);
  assert.equal(box.height, box.fontSize, `${label}: the icon is as tall as the text`);
  assert.ok(Math.abs(box.iconCentre - box.textCentre) <= PIXEL_ROUNDING,
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
  assert.deepEqual(failures, []);
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
