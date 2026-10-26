import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// The robot count (🤖 N) sits in its note's top-right corner, 4 px inside the border, over the
// end of a long first line on a background as solid as the note's: nothing moves when it
// comes, changes or goes (docs/ui/tag-bar.md; agreed 2026-10-25, cases C1-C12). It used to
// stand past the note's right edge, where the right-hand buttons covered it. Its corner in
// every window layout (C1, C3) is checked by the right-edge suite, pressing and right-clicking
// it (C4, C5) by the robot-proposals suite.

const WINDOW = {width: 1280, height: 800};
const PHONE = {width: 390, height: 844};
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
const SETTLE_MS = 400;
const ROBOT_INSET_PX = 4;
// Browsers place boxes on a layout grid: 1/64 px in Chrome, 1/60 px in Firefox.
const LAYOUT_STEP_PX = 1 / 60;
// A click lands between two letters: the caret is within a letter's width of it.
const LETTER_PX = 12;
// The robot's left edge, and a click this far left of it, on the first line.
const BESIDE_ROBOT_PX = 6;
// One unbroken run of letters: a note breaks it anywhere, so its first line fills to the edge
// and runs under the robot whatever the window's width.
const LONG_LINE = 'abcdefghijklmnopqrstuvwxyz'.repeat(12);
const DARK_ROBOT_COLOR = 'rgb(199, 210, 254)';
const LIGHT_ROBOT_COLOR = 'rgb(67, 56, 202)';

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

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

async function reloadApp(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
}

// Lines as the editor writes them (<div>s, no paragraph margin). long: a long first line with one proposal; short: a short line with one; grows: one
// proposal, later twelve; arrives: a long line, no proposal yet; parent: a parent with one
// proposal and an open child; folded: a collapsed parent whose child has proposals.
async function seedNotes(page) {
  return page.evaluate(async longLine => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = async (created, html, proposals) => {
      await NotesAPI.saveNote(created.id, html, '');
      if (proposals.length > 0) await NotesAPI.addTagProposals(created.id, {[created.id]: proposals});
      return created.id;
    };
    const ids = {};
    ids.long = await note(await NotesAPI.createNote(null, ''), `<div>${longLine}</div><div>Second paragraph</div>`, ['travel']);
    ids.short = await note(await NotesAPI.createSibling(ids.long, ''), '<div>Short</div>', ['travel']);
    ids.grows = await note(await NotesAPI.createSibling(ids.short, ''), '<div>Grows</div>', ['one']);
    ids.arrives = await note(await NotesAPI.createSibling(ids.grows, ''), `<div>${longLine}</div>`, []);
    ids.parent = await note(await NotesAPI.createSibling(ids.arrives, ''), '<div>Parent with a robot</div>', ['parent']);
    ids.child = await note(await NotesAPI.createChild(ids.parent, ''), '<div>Its open child</div>', []);
    ids.folded = await note(await NotesAPI.createSibling(ids.parent, ''), '<div>Folded parent</div>', []);
    ids.foldedChild = await note(await NotesAPI.createChild(ids.folded, ''), '<div>Hidden child</div>', ['hidden', 'child']);
    await NotesAPI.setCollapsedBulk([ids.folded], true);
    return ids;
  }, LONG_LINE);
}

// The robot against its note's border, the note, the first line's text and the note after it.
function robotLayout(page, noteId) {
  return page.evaluate(id => {
    const note = document.querySelector(`.note[data-note-id="${id}"]`);
    const robot = note.querySelector(':scope > .note-proposal-indicator');
    const box = element => {
      const rect = element.getBoundingClientRect();
      return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height};
    };
    // The lines of text alone (a range over the whole content also returns its paragraphs' boxes).
    const walker = document.createTreeWalker(note.querySelector(':scope > .note-content'), NodeFilter.SHOW_TEXT);
    const lines = [];
    for (let text = walker.nextNode(); text !== null; text = walker.nextNode()) {
      if (text.textContent.trim() === '') continue;
      const range = document.createRange();
      range.selectNodeContents(text);
      lines.push(...[...range.getClientRects()].map(rect => ({left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom})));
    }
    const next = note.nextElementSibling;
    const style = robot === null ? null : getComputedStyle(robot);
    return {
      note: {...box(note), borderTop: note.clientTop, borderRight: note.offsetWidth - note.clientWidth - note.clientLeft,
        background: getComputedStyle(note).backgroundColor},
      robot: robot === null ? null : box(robot),
      robotStyle: style === null ? null : {color: style.color, backgroundColor: style.backgroundColor, backgroundImage: style.backgroundImage},
      lines,
      nextTop: next === null ? null : next.getBoundingClientRect().top,
    };
  }, noteId);
}

function assertNear(actual, expected, tolerance, message) {
  assert(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} instead of ${expected}`);
}

function assertInCorner(layout, label) {
  assert.notEqual(layout.robot, null, `${label}: the robot shows`);
  const {robot, note} = layout;
  assertNear(robot.right, note.right - note.borderRight - ROBOT_INSET_PX, LAYOUT_STEP_PX, `${label}: the robot's right edge is ${ROBOT_INSET_PX} px inside the border`);
  assertNear(robot.top, note.top + note.borderTop + ROBOT_INSET_PX, LAYOUT_STEP_PX, `${label}: the robot's top is ${ROBOT_INSET_PX} px inside the border`);
  assert(robot.left >= note.left && robot.bottom <= note.bottom, `${label}: the robot lies wholly in its note`);
}

// Everything in the note, measured from the note's top-left, and the note after it.
function shape(layout) {
  const {note} = layout;
  return {
    height: note.height,
    lines: layout.lines.map(line => [line.left - note.left, line.top - note.top, line.right - note.left]),
    nextOffset: layout.nextTop === null ? null : layout.nextTop - note.top,
  };
}

async function showNote(page, noteId) {
  await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), noteId);
  await idle(page);
}

// C2: a collapsed note's rolled-up robot, in the same corner.
async function foldedCase(page, ids) {
  await showNote(page, ids.folded);
  assertInCorner(await robotLayout(page, ids.folded), 'collapsed note');
}

// C6: more proposals widen the robot to the left; its right edge stays.
async function growsCase(page, ids) {
  await showNote(page, ids.grows);
  const before = await robotLayout(page, ids.grows);
  await page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.addTagProposals(id, {[id]: ['two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve']});
  }, ids.grows);
  await reloadApp(page);
  await showNote(page, ids.grows);
  const after = await robotLayout(page, ids.grows);
  assertInCorner(after, 'twelve proposals');
  assert(after.robot.width > before.robot.width, 'the robot widens for 🤖 12');
  assertNear(after.note.right - after.robot.right, before.note.right - before.robot.right, LAYOUT_STEP_PX, 'its right edge stays');
}

// C7: a robot arriving or going moves nothing in the note or after it.
async function arrivesAndGoesCase(page, ids) {
  await showNote(page, ids.arrives);
  const without = await robotLayout(page, ids.arrives);
  assert.equal(without.robot, null, 'no robot before proposals');
  await page.evaluate(async id => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    await NotesAPI.addTagProposals(id, {[id]: ['arrived']});
  }, ids.arrives);
  await reloadApp(page);
  await showNote(page, ids.arrives);
  const arrived = await robotLayout(page, ids.arrives);
  assertInCorner(arrived, 'an arrived robot');
  assert(arrived.lines.some(line => line.top < arrived.robot.bottom && line.right > arrived.robot.left),
    'the long first line runs under the robot');
  assert.deepEqual(shape(arrived), shape(without), 'a robot arriving moves nothing');
  // Its last proposal rejected from its menu: it goes, without a reload.
  const robot = arrived.robot;
  await page.mouse.click((robot.left + robot.right) / 2, (robot.top + robot.bottom) / 2, {button: 'right'});
  await page.waitForSelector('#context-menu.is-visible');
  const item = await page.evaluateHandle(() => [...document.querySelectorAll('#context-menu.is-visible .context-menu-item')]
    .find(node => node.querySelector('.context-menu-item-label').textContent.trim() === 'Reject All Suggested Tags'));
  await item.asElement().click();
  await pause(SETTLE_MS);
  await idle(page);
  const gone = await robotLayout(page, ids.arrives);
  assert.equal(gone.robot, null, 'the robot goes with its last proposal');
  assert.deepEqual(shape(gone), shape(arrived), 'a robot going moves nothing');
}

// C8 (with C1 for an edited note): in edit mode the robot keeps its corner, and a click just
// left of it on the first line puts the caret there.
async function editingCase(page, ids) {
  await showNote(page, ids.long);
  await page.click(`.note[data-note-id="${ids.long}"] > .note-content`);
  await page.waitForSelector(`.note.editing[data-note-id="${ids.long}"]`);
  await idle(page);
  const editing = await robotLayout(page, ids.long);
  assertInCorner(editing, 'an edited note');
  const firstLine = editing.lines[0];
  // Among the line's last letters, just left of the robot (or of the line's end, if it ends first).
  const click = {x: Math.min(editing.robot.left, firstLine.right) - BESIDE_ROBOT_PX, y: (firstLine.top + firstLine.bottom) / 2};
  await page.mouse.click(click.x, click.y);
  await pause(SETTLE_MS);
  const caret = await page.evaluate(async () => {
    const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
    const range = window.getSelection().getRangeAt(0).cloneRange();
    const rect = range.getClientRects()[0];
    return {noteId: mode.currentNoteId, isEditing: mode.isEditing, x: rect.left, y: (rect.top + rect.bottom) / 2};
  });
  assert.equal(caret.isEditing, true, 'the note is still edited');
  assert.equal(caret.noteId, ids.long, 'the same note is edited');
  assertNear(caret.x, click.x, LETTER_PX, 'the caret is where the first line was clicked');
  assert(caret.y >= firstLine.top && caret.y <= firstLine.bottom, 'the caret is on the first line');
  await page.keyboard.press('Escape');
  await idle(page);
}

// C9: a parent's robot never lies over its child.
async function childCase(page, ids) {
  await showNote(page, ids.parent);
  const parent = await robotLayout(page, ids.parent);
  assertInCorner(parent, 'a parent note');
  const child = await page.$eval(`.note[data-note-id="${ids.child}"]`, node => {
    const rect = node.getBoundingClientRect();
    return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom};
  });
  const {robot} = parent;
  const overlaps = robot.left < child.right && child.left < robot.right && robot.top < child.bottom && child.top < robot.bottom;
  assert(!overlaps, 'the parent\'s robot is not over its child');
}

// C11: the robot's colours, on a background as solid as its note's.
async function coloursCase(page, ids) {
  await showNote(page, ids.short);
  for (const [theme, color] of [['light', LIGHT_ROBOT_COLOR], ['dark', DARK_ROBOT_COLOR]]) {
    const original = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    await page.evaluate(theme => document.documentElement.setAttribute('data-theme', theme), theme);
    await settle(page);
    const layout = await robotLayout(page, ids.short);
    await page.evaluate(original => {
      if (original === null) document.documentElement.removeAttribute('data-theme');
      else document.documentElement.setAttribute('data-theme', original);
    }, original);
    assert.equal(layout.robotStyle.color, color, `${theme} theme: the robot's text colour`);
    assert.equal(layout.robotStyle.backgroundColor, layout.note.background, `${theme} theme: the robot is as solid as its note`);
    assert.match(layout.robotStyle.backgroundImage, /gradient/, `${theme} theme: the robot keeps its tint`);
  }
}

// C12: a short first line and the robot do not meet.
async function shortLineCase(page, ids) {
  await showNote(page, ids.short);
  const layout = await robotLayout(page, ids.short);
  assertInCorner(layout, 'a short line');
  assert(layout.lines.every(line => line.right <= layout.robot.left), 'the short line ends before the robot');
}

// C10: on a phone the robot stays in its note and in the window.
async function phoneCase(page, ids) {
  await page.setViewport(PHONE);
  await reloadApp(page);
  await showNote(page, ids.long);
  const layout = await robotLayout(page, ids.long);
  assertInCorner(layout, 'phone');
  assert(layout.robot.right <= PHONE.width, 'the robot stays in the window');
  await page.setViewport(WINDOW);
  await reloadApp(page);
}

async function cornerCases(page, ids) {
  const failures = [];
  const cases = [
    ['collapsed note', foldedCase], ['short line', shortLineCase], ['parent and child', childCase],
    ['colours', coloursCase], ['editing', editingCase], ['arriving and going', arrivesAndGoesCase],
    ['growing count', growsCase], ['phone', phoneCase],
  ];
  for (const [label, run] of cases) {
    try {
      await run(page, ids);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  }
  assert.deepEqual(failures, []);
}

export async function checkRobotCorner(page) {
  const viewport = page.viewport();
  await page.setViewport(WINDOW);
  const ids = await seedNotes(page);
  await reloadApp(page);
  await runThenCleanUp('robot corner', () => cornerCases(page, ids), async () => {
    await page.setViewport(viewport);
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of [ids.foldedChild, ids.folded, ids.child, ids.parent, ids.arrives, ids.grows, ids.short, ids.long]) {
        await NotesAPI.deleteNote(id);
      }
    }, ids);
  });
}
