import assert from 'node:assert/strict';
import { waitForAppQuiet, waitForAppQuietWithin } from './browser-app-idle.mjs';

// Requests count as quiet after this long without one starting or ending.
const REQUESTS_QUIET_MS = 300;

// A drop's uploads and preview children follow one another; requests quiet this long
// mean the last has been made.
const DROP_REQUESTS_QUIET_MS = 800;
const DROP_SETTLE_TIMEOUT_MS = 15000;

// Dropped files are shown, not copied (docs/ready-to-build/files-shown-not-copied.md, agreed
// 2026-11-03): a dropped file is a card, with no preview note under it. A dropped .md file
// opens the import walkthrough at its Markdown screen; a dropped .txt file asks Note or File
// (checks 22 to 26). Before, every text, CSV or JSON file got a preview child.

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

// A synthetic file drop, as Finder or Explorer sends one, at a point in `selector`.
function drop(page, selector, files, where) {
  return page.evaluate(({selector, files, where}) => {
    const target = document.querySelector(selector);
    const rect = target.getBoundingClientRect();
    const data = new DataTransfer();
    for (const file of files) data.items.add(new File([file.text], file.name, {type: file.type}));
    const x = where === 'end' ? rect.right - 5 : rect.left + rect.width / 2;
    let y = where === 'end' ? rect.bottom - 5 : rect.top + rect.height / 2;
    // A file is dropped where the user sees it: never below the window.
    y = Math.min(y, window.innerHeight - 5);
    target.dispatchEvent(new DragEvent('drop', {dataTransfer: data, bubbles: true, cancelable: true, clientX: x, clientY: y}));
  }, {selector, files, where});
}

// Each root note holding a pill: its pills, and its child notes in order.
function filesView(page) {
  return page.evaluate(() => {
    const own = (note, selector) => [...note.querySelectorAll(selector)].filter(
      element => element.closest('.note') === note);
    return [...document.querySelectorAll('.note')]
      .filter(note => note.parentElement.closest('.note') === null)
      .map(note => ({
        id: note.dataset.noteId,
        top: Math.round(note.getBoundingClientRect().top),
        editing: own(note, '.note-content[contenteditable="true"]').length === 1,
        pills: own(note, '.note-file-reference-header').map(header => [
          header.querySelector('.note-file-reference-badge').textContent,
          header.querySelector('.note-file-reference-title').textContent]),
        tooltips: own(note, '.note-file-reference-link').map(link => link.title),
        children: [...document.querySelectorAll('.note')]
          .filter(child => child.parentElement.closest('.note') === note)
          .map(child => ({
            visible: child.getBoundingClientRect().height > 0,
            markdownHeading: own(child, '.meta-markdown h1').map(heading => heading.textContent).join(''),
            csvCells: own(child, '.meta-csv td').map(cell => cell.textContent.trim()),
            json: own(child, '.meta-json:not(.meta-json-error) .meta-json-pre').map(pre => pre.textContent).join(''),
            text: own(child, '.note-content')[0].innerText.trim(),
          })),
      }));
  });
}

// While a note is edited its pills show as raw ![[…]] tokens: find it by id.
function byId(view, noteId) {
  const found = view.find(note => note.id === noteId);
  assert.ok(found, `note ${noteId}`);
  return found;
}

function byFirstPill(view, title) {
  const found = view.find(note => note.pills.length > 0 && note.pills[0][1] === title);
  assert.ok(found, `a note holding ${title}`);
  return found;
}

// A drop is finished when its uploads and preview children are in (while
// editing, a pill shows as its raw ![[…]] token, so wait for the requests).
async function settle(page) {
  await waitForAppQuietWithin(page, DROP_REQUESTS_QUIET_MS, DROP_SETTLE_TIMEOUT_MS);
}

async function waitForNote(page, title) {
  await page.waitForFunction(title => [...document.querySelectorAll('.note-file-reference-title')]
    .some(element => element.textContent === title), {timeout: 10000}, title);
  await idle(page);
}

async function leaveEditing(page) {
  await page.keyboard.press('Escape');
  await idle(page);
}

async function textDropChoice(page) {
  await page.waitForSelector('#text-drop-choice-modal .text-drop-choice-title', {visible: true, timeout: 10000});
  return page.evaluate(() => ({
    title: document.querySelector('#text-drop-choice-modal .text-drop-choice-title').textContent,
    files: document.querySelector('#text-drop-choice-modal .text-drop-choice-files').textContent,
    focused: document.activeElement?.id,
  }));
}

async function noteTexts(page) {
  return page.$$eval('#notes-container > .note > .note-content', contents => contents.map(content => content.innerText.trim()));
}

export async function checkFileDropPreviews(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  const createdIds = [];
  const track = async () => {
    for (const note of await filesView(page)) if (!createdIds.includes(note.id)) createdIds.push(note.id);
  };
  try {
    // A CSV and a JSON file dropped together, aimed at no note: a note each (docs/ui/references.md),
    // each with its card, no preview notes.
    await drop(page, '#notes-container', [
      {name: 'data.csv', type: 'text/csv', text: 'name,count\napples,3'},
      {name: 'config.json', type: 'application/json', text: '{"name": "apples", "count": 3}'},
    ], 'center');
    await settle(page);
    await leaveEditing(page);
    await waitForNote(page, 'config.json');
    await waitForNote(page, 'data.csv');
    const csvNote = byFirstPill(await filesView(page), 'data.csv');
    const jsonNote = byFirstPill(await filesView(page), 'config.json');
    await track();
    assert.deepEqual([csvNote.pills, jsonNote.pills], [[['.CSV', 'data.csv']], [['.JSON', 'config.json']]], 'csv and json: a note each, with its card');
    assert.notEqual(csvNote.id, jsonNote.id, 'csv and json: two notes');
    assert.deepEqual([csvNote.children.length, jsonNote.children.length], [0, 0], 'csv and json: no preview notes');

    // A .txt file alone asks Note or File, Note focused; Cancel makes nothing.
    const before = await noteTexts(page);
    await drop(page, '#notes-container', [{name: 'notes.txt', type: 'text/plain', text: 'First line\n<b>not bold</b>'}], 'center');
    assert.deepEqual(await textDropChoice(page), {title: 'Text file', files: 'notes.txt', focused: 'text-drop-choice-note'},
      'txt: it asks Note or File, Note focused');
    await page.click('#text-drop-choice-cancel');
    await idle(page);
    assert.deepEqual(await noteTexts(page), before, 'txt, Cancel: nothing is made');

    // Note: a note at the top holding its text, as plain text.
    await drop(page, '#notes-container', [{name: 'notes.txt', type: 'text/plain', text: 'First line\n<b>not bold</b>'}], 'center');
    await textDropChoice(page);
    await page.click('#text-drop-choice-note');
    await settle(page);
    await leaveEditing(page);
    assert.equal((await noteTexts(page))[0], 'First line\n<b>not bold</b>', 'txt, Note: a note at the top with its text');
    await track();

    // File: a card, as any file, with no preview note.
    await drop(page, '#notes-container', [{name: 'kept.txt', type: 'text/plain', text: 'kept as a file'}], 'center');
    await textDropChoice(page);
    await page.click('#text-drop-choice-file');
    await settle(page);
    await leaveEditing(page);
    await waitForNote(page, 'kept.txt');
    const kept = byFirstPill(await filesView(page), 'kept.txt');
    await track();
    assert.deepEqual([kept.pills, kept.children.length], [[['.TXT', 'kept.txt']], 0], 'txt, File: a card alone');

    // A .md file alone opens the import walkthrough at its Markdown screen.
    await drop(page, '#notes-container', [{name: 'readme.md', type: 'text/markdown', text: '# Hello\n\n- one\n- two'}], 'center');
    await page.waitForSelector('#import-wizard [data-choice-key="markdownAs"]', {visible: true, timeout: 10000});
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.getElementById('import-wizard').style.display !== 'block', {timeout: 10000});
    await idle(page);

    // Dropped into the note being edited: the card goes into it, editing continues, and the
    // note does not move; no preview note.
    const contentSelector = `.note[data-note-id="${csvNote.id}"] .note-content`;
    // In the middle of the window: a drop that keeps everything in sight moves nothing.
    // (At the window's bottom edge the inserted file would be out of sight, and Firefox
    // scrolls it back in view.)
    await page.$eval(contentSelector, content => content.scrollIntoView({block: 'center'}));
    await settle(page);
    const box = await page.evaluate(selector => {
      const rect = document.querySelector(selector).getBoundingClientRect();
      return {x: rect.right - 20, y: rect.top + rect.height / 2};
    }, contentSelector);
    await page.mouse.click(box.x, box.y);
    await page.waitForFunction(selector => document.querySelector(selector).getAttribute('contenteditable') === 'true',
      {timeout: 5000}, contentSelector);
    // A drop while entering edit mode is still running is refused ("another command is still running").
    await settle(page);
    const topBefore = byId(await filesView(page), csvNote.id).top;
    await drop(page, contentSelector, [{name: 'extra.csv', type: 'text/csv', text: 'x,y\n1,2'}], 'end');
    await settle(page);
    const edited = byId(await filesView(page), csvNote.id);
    assert.equal(edited.editing, true, 'drop while editing: the note is still being edited');
    assert.equal(edited.top, topBefore, 'drop while editing: the note stays where it was');
    assert.equal(edited.children.length, 0, 'drop while editing: no preview note');
    await leaveEditing(page);
    assert.deepEqual(byFirstPill(await filesView(page), 'data.csv').pills,
      [['.CSV', 'data.csv'], ['.CSV', 'extra.csv']], 'drop while editing: the card is in the note');
  } finally {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of ids) await NotesAPI.deleteNote(id);
    }, createdIds);
  }
  await dropKeepsTheFileInSight(page);
}

// A file dropped into the note being edited stays in sight (docs/ui/interaction-principles.md,
// principle 3; agreed 2026-10-27): its reference goes on a line of its own where it was
// dropped. That line in view, nothing moves (a); below the window, the page scrolls just
// enough to put it at the window's bottom edge (b, c), and no further for the preview child
// that follows it (e); under the search controls, just enough to put it the usual gap below
// them (d). The same in Chrome and Firefox, which on its own scrolls by other amounts.
// Long enough that every line used below can be scrolled to any height in the window.
const LONG_NOTE_LINES = 60;
// A line just partly in sight: this much of it shows, the rest is beyond the edge.
const PARTLY_SHOWN_PX = 10;
// Just inside an edge, a line, or a window: a point that is certainly on it.
const INSIDE_PX = 3;
// The space kept between the search controls and what is shown below them (viewport-reference.js).
const CONTROLS_GAP_PX = 8;
// Positions within this are the same pixel (Firefox lays out in 1/60 px).
const SAME_PIXEL = 1;
const FILE_TOKEN_RE = '!?\\[\\[[0-9a-f-]{36}\\]\\]';

function lineOf(page, contentSelector, text) {
  return page.evaluate(({contentSelector, text}) => {
    const walker = document.createTreeWalker(document.querySelector(contentSelector), NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      if (node.data !== text) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const rect = range.getBoundingClientRect();
      return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom};
    }
    throw new Error(`no line reading ${text}`);
  }, {contentSelector, text});
}

// Scrolls the page at once so the line's top is at `top` on screen; fails if the page
// cannot scroll that far, so a case never runs from the wrong place.
async function putLineTopAt(page, contentSelector, text, top) {
  const line = await lineOf(page, contentSelector, text);
  await page.evaluate(delta => window.scrollBy({top: delta, behavior: 'instant'}), line.top - top);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const placed = await lineOf(page, contentSelector, text);
  assert.ok(Math.abs(placed.top - top) < SAME_PIXEL, `setup: "${text}" at ${top} on screen (it is at ${placed.top})`);
}

// The note's file tokens, in order (matchAll: none is an empty list, not null).
function fileTokens(page, contentSelector) {
  return page.evaluate(({contentSelector, pattern}) =>
    [...document.querySelector(contentSelector).textContent.matchAll(new RegExp(pattern, 'g'))].map(match => match[0]),
  {contentSelector, pattern: FILE_TOKEN_RE});
}

// The screen box of the one file token that is new since `before`, and where the page is.
async function newTokenPlace(page, contentSelector, before) {
  const tokens = await fileTokens(page, contentSelector);
  const added = tokens.filter(token => !before.includes(token));
  assert.equal(added.length, 1, 'the drop adds one file reference');
  return page.evaluate(({contentSelector, token}) => {
    const walker = document.createTreeWalker(document.querySelector(contentSelector), NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      const at = node.data.indexOf(token);
      if (at === -1) continue;
      const range = document.createRange();
      range.setStart(node, at);
      range.setEnd(node, at + token.length);
      const rect = range.getBoundingClientRect();
      const controls = document.querySelector('.controls').getBoundingClientRect();
      const text = document.querySelector(contentSelector).textContent;
      const place = text.indexOf(token);
      return {top: rect.top, bottom: rect.bottom, windowHeight: window.innerHeight, controlsBottom: controls.bottom,
        scrollY: window.scrollY, between: [text.slice(Math.max(0, place - 24), place), text.slice(place + token.length, place + token.length + 24)]};
    }
    throw new Error(`no text holding ${token}`);
  }, {contentSelector, token: added[0]});
}

function dropAt(page, contentSelector, point, name) {
  return page.evaluate(({contentSelector, point, name}) => {
    const data = new DataTransfer();
    data.items.add(new File([`Dropped ${name}`], name, {type: 'text/csv'}));
    document.querySelector(contentSelector).dispatchEvent(new DragEvent('drop',
      {dataTransfer: data, bubbles: true, cancelable: true, clientX: point.x, clientY: point.y}));
  }, {contentSelector, point, name});
}

async function dropKeepsTheFileInSight(page) {
  const lines = Array.from({length: LONG_NOTE_LINES}, (_, index) => `Line ${index + 1} of the long note`);
  const noteId = await page.evaluate(async lines => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, lines.map(line => `<div>${line}</div>`).join(''), '');
    return note.id;
  }, lines);
  const contentSelector = `.note[data-note-id="${noteId}"] > .note-content`;
  const failures = [];
  const attempt = async (label, run) => {
    try {
      await run();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  };
  try {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await idle(page);
    // The note is first in the list: at the page's top its first line is in view (the page
    // keeps its scroll across a reload).
    await page.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const first = await lineOf(page, contentSelector, lines[0]);
    await page.mouse.click(first.right - INSIDE_PX, first.top + INSIDE_PX);
    await page.waitForFunction(selector => document.querySelector(selector).getAttribute('contenteditable') === 'true',
      {timeout: 5000}, contentSelector);
    await settle(page);

    await attempt('a: a line in the middle', async () => {
      const text = lines[24];
      await putLineTopAt(page, contentSelector, text, await page.evaluate(() => window.innerHeight / 2));
      const line = await lineOf(page, contentSelector, text);
      const before = await fileTokens(page, contentSelector);
      const scrollBefore = await page.evaluate(() => window.scrollY);
      await dropAt(page, contentSelector, {x: line.right - INSIDE_PX, y: line.top + INSIDE_PX}, 'middle.csv');
      await settle(page);
      await newTokenPlace(page, contentSelector, before);
      assert.ok(Math.abs(await page.evaluate(() => window.scrollY) - scrollBefore) < SAME_PIXEL, 'nothing scrolls');
    });

    for (const [label, text, place] of [
      ['b: the bottom line, partly below the window', lines[29], height => height - PARTLY_SHOWN_PX],
      ['c: the bottom line in view, the file on a new line below it', lines[37], (height, lineHeight) => height - lineHeight - INSIDE_PX],
    ]) {
      await attempt(label, async () => {
        const height = await page.evaluate(() => window.innerHeight);
        const lineHeight = (await lineOf(page, contentSelector, text)).bottom - (await lineOf(page, contentSelector, text)).top;
        await putLineTopAt(page, contentSelector, text, place(height, lineHeight));
        const line = await lineOf(page, contentSelector, text);
        const before = await fileTokens(page, contentSelector);
        await dropAt(page, contentSelector, {x: line.right - INSIDE_PX, y: Math.min(line.bottom, height) - INSIDE_PX}, 'bottom.csv');
        await settle(page);
        const token = await newTokenPlace(page, contentSelector, before);
        assert.ok(Math.abs(token.bottom - token.windowHeight) < SAME_PIXEL,
          `the file's line ends at the window's bottom, no further (${JSON.stringify(token)})`);
      });
    }

    // Dropped at a line's start, the file takes that line's place on a line of its own,
    // with no empty line above it (one was added: the line's start read the line above as
    // text before the caret, since <div> lines carry no line break; 2026-10-27).
    await attempt('f: a file dropped at the start of a line takes its place', async () => {
      const text = lines[44];
      await putLineTopAt(page, contentSelector, text, await page.evaluate(() => window.innerHeight / 2));
      const line = await lineOf(page, contentSelector, text);
      const before = await fileTokens(page, contentSelector);
      await dropAt(page, contentSelector, {x: line.left + 1, y: line.top + INSIDE_PX}, 'start.csv');
      await settle(page);
      const token = await newTokenPlace(page, contentSelector, before);
      assert.ok(Math.abs(token.top - line.top) < SAME_PIXEL, `the file's line is where the line was (${line.top}; ${JSON.stringify(token)})`);
      assert.equal(token.between[1], text.slice(0, 24), 'the line follows the file');
    });

    await attempt('d: a line partly under the search controls', async () => {
      const text = lines[14];
      const controlsBottom = await page.evaluate(() => document.querySelector('.controls').getBoundingClientRect().bottom);
      const lineHeight = (await lineOf(page, contentSelector, text)).bottom - (await lineOf(page, contentSelector, text)).top;
      await putLineTopAt(page, contentSelector, text, controlsBottom - lineHeight + PARTLY_SHOWN_PX);
      const line = await lineOf(page, contentSelector, text);
      const before = await fileTokens(page, contentSelector);
      await dropAt(page, contentSelector, {x: line.left + 1, y: line.bottom - INSIDE_PX}, 'top.csv');
      await settle(page);
      const token = await newTokenPlace(page, contentSelector, before);
      assert.ok(Math.abs(token.top - (token.controlsBottom + CONTROLS_GAP_PX)) < SAME_PIXEL,
        `the file's line sits the usual gap below the search controls (${JSON.stringify(token)})`);
    });
    await leaveEditing(page);
  } finally {
    await page.evaluate(async noteId => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      await NotesAPI.deleteNote(noteId);
    }, noteId);
  }
  assert.deepEqual(failures, [], 'a dropped file stays in sight');
}
