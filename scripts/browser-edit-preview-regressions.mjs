import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Previews while editing (docs/ui/content-formatting.md, "Previews while editing"; agreed
// 2026-10-29): with the caret inside a formula of the note being edited, a panel 6 px below
// the caret's line shows it drawn, its left edge at the caret, following the caret; above the
// line near the window's bottom. Nothing outside a formula, with only its opening delimiter,
// or for a formula that looks as typed. Broken mid-typing, the last good drawing fades to a
// ghost (0.25) and a pause shows "Invalid LaTeX"; a command not finished shows as typed after
// the pause. The panel never moves the note's text. Escape hides it until the caret leaves the
// formula; scrolling hides it; a selection keeps it as it was; Previews While Editing off shows none.
// The note's text never holds the caret mark.
//
// CSV tables (2026-10-29): with the caret in an @csv note or a ((@csv)) region, the panel
// shows the table exactly as the note draws it, at most 40% of the window tall, scrolled
// so the caret's row is in its middle; broken, the last good table fades and a pause
// shows "Invalid CSV" with why. In a Markdown note with a ((@csv)) region and a formula,
// each shows its own; the text around the region shows nothing.
//
// Mermaid diagrams and JSON (2026-10-29): in a ```mermaid fence the panel shows the diagram
// as the note draws it, never scaled up; a tall one is scaled down, in proportion, to fit
// 40% of the window; nothing on the fence's lines; a dangling arrow fades it and a pause
// shows "Invalid Mermaid diagram". Compact JSON shows laid out as the note draws it; broken,
// it fades and a pause says why and where.
//
// References (slice 4, 2026-10-29): with the caret inside `[[UUID]]` or `![[UUID]]` the
// preview card shows the note, picture or file it names, 6 px below the line from the
// reference's left edge; moving within keeps it, leaving hides it; a picture's card shows
// the picture (it had stayed "Loading image preview..."); Escape hides it, editing goes
// on, until the caret leaves the reference.

const WINDOW = {width: 1100, height: 800};
const REQUESTS_QUIET_MS = 300;
const FRAMES_TO_SETTLE = 3;
// Longer than the wait after typing (150 ms) and the answer: no panel by then means none.
const NO_PANEL_WAIT_MS = 600;
// Longer than the pause after which a broken formula shows why (1.5 s).
const BROKEN_PAUSE_WAIT_MS = 2500;
const PANEL_WAIT_MS = 2000;
// Between the caret's line and the panel (paste-format-offer-service.js, CARD_GAP_PX).
const GAP_PX = 6;
// The panel's place is rounded to whole pixels.
const ROUNDING_PX = 0.5;
const GHOST_OPACITY = '0.25';
const FULL_OPACITY = '1';
const FILLER_NOTES = 30;
const TABLE_ROWS = 40;
const CARET_ROW = 30;
// The panel's height, at most this share of the window's (main.css, .edit-preview).
const PANEL_HEIGHT_SHARE = 0.4;
// The panel's scroll is a whole number of pixels: the row's middle is this close to the panel's.
const ROW_CENTERING_PX = 1;
const TALL_DIAGRAM_STEPS = 14;
// The window's width less the panel's 8 px margin on each side (paste-format-offer-service.js).
const WINDOW_MARGINS_PX = 16;
// A scaled diagram keeps its proportions to this share of either side.
const PROPORTION_TOLERANCE = 0.01;
// Browsers lay an SVG's size out in floats: equal to this.
const SAME_SIZE_PX = 0.01;
const CARD = '.reference-preview';
const PNG_BASE64 = 'iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAAQklEQVR4nO3OQQ0AIAwAsQlDBLKRhQuOR5MK6Jy9vjL5QEhISKgeCAkJCdUDISEhoXogJCQkVA+EhISE6oGQkNBjF21V9KbVaAsfAAAAAElFTkSuQmCC';
const PANEL = '.edit-preview';
// What marks the caret in the note sent for a preview (edit-preview-service.js).
const CARET_MARK = '\ufdd0';

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

async function pause(milliseconds) {
  await new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function seedNotes(page) {
  return page.evaluate(async ({fillerCount, rowCount, tallSteps, png}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const make = async (html, tags) => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tags);
      return note.id;
    };
    const fillers = [];
    for (let index = 0; index < fillerCount; index += 1) fillers.push(await make(`<div>Filler note ${index}</div>`, ''));
    const formulas = await make([
      'A half: $$\\frac{1}{2}$$ done.',
      'Plain $$x$$ here.',
      // Last: a $$ with no $$ after it anywhere opens nothing.
      'Only an opening $$\\frac{1}{2} and no closing one.',
    ].map(line => `<div>${line}</div>`).join(''), '@markdown');
    const tableLines = ['Day,Steps,Sleep,Mood'];
    for (let day = 1; day <= rowCount; day += 1) tableLines.push(`Day ${day},${4000 + day * 137},7.0,good`);
    const table = await make(tableLines.map(line => `<div>${line}</div>`).join(''), '@csv');
    const groceries = await make([
      'Groceries this week ((Item,Qty,Price',
      'Milk,2,1.20',
      'Eggs,12,3.40)) and the energy $$E = mc^2$$ here.',
    ].map(line => `<div>${line}</div>`).join(''), '@markdown ((@csv))');
    const release = await make(['Release steps:', '```mermaid', 'flowchart LR', 'A[Write] --> B[Review] --> C[Ship]', '```', 'Done when shipped.']
      .map(line => `<div>${line}</div>`).join(''), '@markdown');
    const tallLines = ['flowchart TD'];
    for (let step = 0; step < tallSteps; step += 1) tallLines.push(`N${step}[Step ${step}: a fairly long label] --> N${step + 1}[Step ${step + 1}]`);
    const tall = await make(tallLines.map(line => `<div>${line}</div>`).join(''), '@mermaid');
    const settings = await make('<div>{"name": "MetaList", "tags": ["notes", "search"], "port": 8443}</div>', '@json');
    const {FilesAPI} = await import('/static/js/modules/api-client.js');
    const kyoto = await make('<div>Kyoto trip plan</div><div>Day 1: temples</div>', '');
    const bytes = Uint8Array.from(atob(png), character => character.charCodeAt(0));
    const picture = (await FilesAPI.uploadFile(new File([bytes], 'dot.png', {type: 'image/png'}))).file_id;
    const pdf = (await FilesAPI.uploadFile(new File([new TextEncoder().encode('%PDF-1.4 lease')], 'lease.pdf', {type: 'application/pdf'}))).file_id;
    const plan = await make(`<div>Plan: [[${kyoto}]] and the photo ![[${picture}]] and the lease [[${pdf}|lease]] end</div>`, '');
    return {fillers, formulas, table, groceries, release, tall, settings, kyoto, picture, pdf, plan};
  }, {fillerCount: FILLER_NOTES, rowCount: TABLE_ROWS, tallSteps: TALL_DIAGRAM_STEPS, png: PNG_BASE64});
}

const contentOf = id => `.note[data-note-id="${id}"] > .note-content`;

async function enterEditing(page, id) {
  await page.evaluate(selector => document.querySelector(selector).scrollIntoView({block: 'start'}), contentOf(id));
  await settle(page);
  await page.click(contentOf(id));
  await idle(page);
  await page.waitForSelector(`.note.editing[data-note-id="${id}"]`);
}

// Puts the caret `after` characters past the start of `needle` in the note being edited.
async function placeCaret(page, needle, after) {
  await page.evaluate(({needle, after}) => {
    const content = document.querySelector('.note.editing > .note-content');
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
    for (let text = walker.nextNode(); text !== null; text = walker.nextNode()) {
      const start = text.data.indexOf(needle);
      if (start === -1) continue;
      const range = document.createRange();
      range.setStart(text, start + after);
      range.collapse(true);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      return;
    }
    throw new Error(`no text ${needle}`);
  }, {needle, after});
}

// The panel, the caret's line and every note's box, measured in one frame.
async function measure(page) {
  return page.evaluate(selector => {
    const panel = document.querySelector(selector);
    const caret = getSelection().getRangeAt(0).getClientRects()[0];
    const boxes = [...document.querySelectorAll('.note, .note-content')].map(element => {
      const box = element.getBoundingClientRect();
      return [box.left, box.top, box.width, box.height].join(',');
    }).join('|');
    if (panel === null) return {panel: null, caret: {left: caret.left, top: caret.top, bottom: caret.bottom}, boxes};
    const box = panel.getBoundingClientRect();
    return {
      panel: {
        left: box.left, top: box.top, bottom: box.bottom, height: box.height,
        opacity: getComputedStyle(panel).opacity, text: panel.textContent, html: panel.innerHTML,
        hasFraction: panel.querySelector('math mfrac') !== null, hasError: panel.classList.contains('edit-preview-has-error'),
      },
      caret: {left: caret.left, top: caret.top, bottom: caret.bottom},
      boxes,
    };
  }, PANEL);
}

// Whether the preview comes to meet `condition` within PANEL_WAIT_MS, checked every frame.
async function becomes(page, condition, value) {
  return page.evaluate(({condition, value, selector, timeout}) => new Promise(resolve => {
    const panel = () => document.querySelector(selector);
    const checks = {
      shown: () => panel() !== null,
      hidden: () => panel() === null,
      opacity: () => panel() !== null && getComputedStyle(panel()).opacity === value,
      fraction: () => panel() !== null && panel().querySelector('math mfrac') !== null,
      diagram: () => panel() !== null && panel().querySelector('svg') !== null,
      // A diagram placed for where the caret is now, not for where it was before.
      diagramAtCaret: () => {
        if (panel() === null || panel().querySelector('svg') === null) return false;
        const caret = getSelection().getRangeAt(0).getClientRects()[0];
        return Math.abs(panel().getBoundingClientRect().left - caret.left) <= 1;
      },
      movedFrom: () => panel() !== null && Math.abs(panel().getBoundingClientRect().left - value) > 1,
      // The row `value` (counted from 0) in the panel's middle, to a pixel.
      rowCentered: () => {
        if (panel() === null) return false;
        const row = panel().querySelectorAll('tbody > tr')[value];
        if (row === undefined) return false;
        const box = panel().getBoundingClientRect();
        const rowBox = row.getBoundingClientRect();
        return Math.abs((rowBox.top + rowBox.bottom) / 2 - (box.top + box.bottom) / 2) <= 1;
      },
    };
    const started = performance.now();
    const step = () => {
      if (checks[condition]()) {
        resolve(true);
        return;
      }
      if (performance.now() - started > timeout) {
        resolve(false);
        return;
      }
      requestAnimationFrame(step);
    };
    step();
  }), {condition, value, selector: PANEL, timeout: PANEL_WAIT_MS});
}

async function waitForPanel(page, label) {
  assert.ok(await becomes(page, 'shown', null), `${label}: a preview`);
  await settle(page);
}

async function assertNoPanel(page, label) {
  await pause(NO_PANEL_WAIT_MS);
  assert.equal(await page.$(PANEL), null, `${label}: no preview`);
}

function assertBelowCaret(measured, label) {
  assert.notEqual(measured.panel, null, `${label}: a preview`);
  assert.ok(Math.abs(measured.panel.left - measured.caret.left) <= ROUNDING_PX,
    `${label}: its left edge at the caret (${measured.panel.left}, caret ${measured.caret.left})`);
  assert.ok(Math.abs(measured.panel.top - (measured.caret.bottom + GAP_PX)) <= ROUNDING_PX,
    `${label}: ${GAP_PX} px below the caret's line (${measured.panel.top}, line bottom ${measured.caret.bottom})`);
}

async function shownBelowAndFollowing(page) {
  await placeCaret(page, 'done', 1);
  await assertNoPanel(page, 'caret in plain text');
  const before = await measure(page);
  await placeCaret(page, '{1}{2}', 4);
  await waitForPanel(page, 'caret in \\frac{1}{2}');
  const shown = await measure(page);
  assertBelowCaret(shown, 'caret in \\frac{1}{2}');
  assert.equal(shown.panel.hasFraction, true, 'the fraction is drawn');
  assert.equal(shown.panel.opacity, FULL_OPACITY, 'at full strength');
  assert.equal(shown.boxes, before.boxes, 'no note moved when the preview appeared');
  await placeCaret(page, '\\frac', 1);
  assert.ok(await becomes(page, 'movedFrom', shown.panel.left), 'the preview follows the caret');
  await settle(page);
  assertBelowCaret(await measure(page), 'caret moved within the formula');
}

async function nothingOutsideAFormula(page) {
  await placeCaret(page, 'A half', 2);
  await assertNoPanel(page, 'caret before the formula');
  await placeCaret(page, '$$ done', 1);
  await assertNoPanel(page, 'caret between the closing $$');
  await placeCaret(page, 'and no closing', 4);
  await assertNoPanel(page, 'only an opening $$');
  await placeCaret(page, '$$x$$', 3);
  await assertNoPanel(page, '$$x$$ looks as typed');
}

async function brokenFormulaFades(page) {
  await placeCaret(page, '{1}{2}', 6);
  await waitForPanel(page, 'before typing');
  const good = await measure(page);
  await page.keyboard.type('^');
  assert.ok(await becomes(page, 'opacity', GHOST_OPACITY), 'broken: the last good drawing fades to the ghost');
  const faded = await measure(page);
  assert.equal(faded.panel.html, good.panel.html, 'broken: the last good drawing stays');
  assert.equal(faded.panel.hasError, false, 'broken: no reason while typing');
  await pause(BROKEN_PAUSE_WAIT_MS);
  const paused = await measure(page);
  assert.deepEqual([paused.panel.text, paused.panel.hasError, paused.panel.opacity], ['Invalid LaTeX', true, FULL_OPACITY],
    'broken after a pause: why');
  await page.keyboard.press('Backspace');
  assert.ok(await becomes(page, 'fraction', null), 'fixed: the fraction is drawn again');
  await settle(page);
  const fixed = await measure(page);
  assert.deepEqual([fixed.panel.opacity, fixed.panel.hasError], [FULL_OPACITY, false], 'fixed: back at full strength');

  await page.keyboard.type(' + \\fra');
  assert.ok(await becomes(page, 'opacity', GHOST_OPACITY), 'a command not finished: the last good drawing fades');
  await pause(BROKEN_PAUSE_WAIT_MS);
  const unknown = await measure(page);
  assert.equal(unknown.panel.opacity, FULL_OPACITY, 'a command not finished, after a pause: full strength');
  assert.ok(unknown.panel.html.includes('<mi>\\fra</mi>') && unknown.panel.hasFraction,
    `a command not finished, after a pause: drawn as the note draws it (${unknown.panel.html})`);
  for (let index = 0; index < ' + \\fra'.length; index += 1) await page.keyboard.press('Backspace');
  await idle(page);
}

async function escapeHidesIt(page) {
  await placeCaret(page, '{1}{2}', 4);
  await waitForPanel(page, 'before Escape');
  const before = await measure(page);
  await page.keyboard.press('Escape');
  await settle(page);
  const after = await measure(page);
  assert.equal(after.panel, null, 'Escape hides the preview');
  assert.equal(after.boxes, before.boxes, 'no note moved when it was hidden');
  assert.notEqual(await page.$('.note.editing'), null, 'Escape leaves editing alone');
  await page.keyboard.press('ArrowLeft');
  await assertNoPanel(page, 'after Escape, inside the same formula');
  await placeCaret(page, 'done', 1);
  await assertNoPanel(page, 'after Escape, outside the formula');
  await placeCaret(page, '{1}{2}', 4);
  await waitForPanel(page, 'back in the formula after Escape');
}

async function aboveNearTheBottom(page) {
  await placeCaret(page, '{1}{2}', 4);
  await waitForPanel(page, 'before the window shrinks');
  const below = await measure(page);
  const height = Math.floor(below.caret.bottom + GAP_PX + below.panel.height);
  await page.setViewport({width: WINDOW.width, height});
  try {
    await settle(page);
    await placeCaret(page, '{1}{2}', 3);
    await waitForPanel(page, 'near the window\'s bottom');
    const above = await measure(page);
    assert.ok(Math.abs(above.panel.bottom - (above.caret.top - GAP_PX)) <= ROUNDING_PX,
      `near the window's bottom: ${GAP_PX} px above the caret's line (${above.panel.bottom}, line top ${above.caret.top})`);
  } finally {
    await page.setViewport(WINDOW);
    await settle(page);
  }
}

async function scrollSelectionAndSetting(page) {
  await placeCaret(page, '{1}{2}', 4);
  await waitForPanel(page, 'before scrolling');
  await page.mouse.wheel({deltaY: 1});
  assert.ok(await becomes(page, 'hidden', null), 'scrolling hides the preview');
  await placeCaret(page, '{1}{2}', 3);
  await waitForPanel(page, 'a caret move after scrolling');

  // Selecting text to type over it keeps the preview as it was (2026-10-29): dragging over
  // `{1}` with the mouse, then typing `3` in its place.
  const beforeSelecting = await measure(page);
  const drag = await page.evaluate(() => {
    const content = document.querySelector('.note.editing > .note-content');
    const text = [...content.querySelectorAll('div')][0].firstChild;
    const start = text.data.indexOf('{1}');
    const at = offset => {
      const range = document.createRange();
      range.setStart(text, offset);
      range.collapse(true);
      const box = range.getClientRects()[0];
      return {x: box.left, y: (box.top + box.bottom) / 2};
    };
    return {from: at(start), to: at(start + 3)};
  });
  await page.mouse.move(drag.from.x + 1, drag.from.y);
  await page.mouse.down();
  await page.mouse.move(drag.to.x - 1, drag.to.y, {steps: 5});
  await page.mouse.up();
  await pause(NO_PANEL_WAIT_MS);
  const selecting = await page.evaluate(selector => {
    const panel = document.querySelector(selector);
    return {
      selected: getSelection().toString(),
      panel: panel === null ? null : {left: panel.getBoundingClientRect().left, top: panel.getBoundingClientRect().top, html: panel.innerHTML},
    };
  }, PANEL);
  assert.equal(selecting.selected, '{1}', 'the drag selected {1}');
  assert.deepEqual(selecting.panel, {left: beforeSelecting.panel.left, top: beforeSelecting.panel.top, html: beforeSelecting.panel.html},
    'a selection keeps the preview where and as it was');
  await page.keyboard.type('3');
  assert.ok(await becomes(page, 'fraction', null), 'typing over the selection: the preview goes on');
  await page.keyboard.press('Backspace');
  await page.keyboard.type('{1}');
  await idle(page);

  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.applyPreference('pref.edit_previews', false);
  });
  try {
    await placeCaret(page, '{1}{2}', 4);
    await assertNoPanel(page, 'Previews While Editing off');
  } finally {
    await page.evaluate(async () => {
      const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
      await CommandPalette.applyPreference('pref.edit_previews', true);
    });
  }
  await placeCaret(page, '{1}{2}', 3);
  await waitForPanel(page, 'Previews While Editing on again');
}

// The table a note draws outside editing (the one in its ((@csv)) region, or the whole note).
async function drawnTable(page, id) {
  return page.$eval(contentOf(id), content => content.querySelector('.meta-csv').outerHTML);
}

async function panelTable(page) {
  return page.$eval(PANEL, panel => {
    const table = panel.querySelector('.meta-csv');
    return table === null ? null : table.outerHTML;
  });
}

async function leaveEditing(page) {
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');
  await idle(page);
}

async function tableNote(page, ids) {
  const drawn = await drawnTable(page, ids.table);
  await enterEditing(page, ids.table);
  // The caret's line in the middle of the window, as when a person clicks it.
  await page.evaluate(needle => {
    const line = [...document.querySelectorAll('.note.editing > .note-content > div')].find(div => div.textContent.startsWith(needle));
    line.scrollIntoView({block: 'center'});
  }, `Day ${CARET_ROW},`);
  await settle(page);
  // Clicking into the note put the caret on another row, whose preview may already show:
  // wait for the one with the caret's row in the middle.
  await placeCaret(page, `Day ${CARET_ROW},`, 2);
  assert.ok(await becomes(page, 'rowCentered', CARET_ROW), `the caret's row (Day ${CARET_ROW}) in the panel's middle`);
  await settle(page);
  assert.equal(await panelTable(page), drawn, 'the table as the note draws it');
  const rows = await page.$eval(PANEL, panel => {
    const box = panel.getBoundingClientRect();
    return {
      panel: {top: box.top, bottom: box.bottom, height: box.height},
      row: [...panel.querySelectorAll('tbody > tr')].map(row => {
        const rowBox = row.getBoundingClientRect();
        return {text: row.cells[0].textContent, middle: (rowBox.top + rowBox.bottom) / 2};
      }),
      windowHeight: window.innerHeight,
    };
  });
  assert.ok(rows.panel.height <= rows.windowHeight * PANEL_HEIGHT_SHARE + ROUNDING_PX,
    `at most ${PANEL_HEIGHT_SHARE * 100}% of the window tall (${rows.panel.height} of ${rows.windowHeight})`);
  const caretRow = rows.row[CARET_ROW];
  assert.equal(caretRow.text, `Day ${CARET_ROW}`, 'the caret\'s row');
  assert.ok(Math.abs(caretRow.middle - (rows.panel.top + rows.panel.bottom) / 2) <= ROW_CENTERING_PX,
    `the caret's row in the panel's middle (${caretRow.middle}, panel ${rows.panel.top}–${rows.panel.bottom})`);
  assertBelowCaret(await measure(page), 'caret in a cell');

  await placeCaret(page, `Day ${CARET_ROW},`, `Day ${CARET_ROW},${4000 + CARET_ROW * 137},7.0,good`.length);
  await page.keyboard.type(',x');
  assert.ok(await becomes(page, 'opacity', GHOST_OPACITY), 'broken: the last good table fades');
  assert.equal(await panelTable(page), drawn, 'broken: the last good table stays');
  await pause(BROKEN_PAUSE_WAIT_MS);
  const paused = await measure(page);
  assert.deepEqual([paused.panel.text, paused.panel.hasError, paused.panel.opacity],
    [`Invalid CSV: Row ${CARET_ROW + 1} has 5 columns, expected 4`, true, FULL_OPACITY], 'broken after a pause: why');
  await page.keyboard.press('Backspace');
  await page.keyboard.press('Backspace');
  assert.ok(await becomes(page, 'opacity', FULL_OPACITY), 'fixed: back at full strength');
  await idle(page);
  assert.equal(await panelTable(page), drawn, 'fixed: the table again');
  await leaveEditing(page);
}

async function regionInMarkdown(page, ids) {
  const drawn = await drawnTable(page, ids.groceries);
  await enterEditing(page, ids.groceries);
  await placeCaret(page, 'Milk', 2);
  await waitForPanel(page, 'caret in the region');
  assert.equal(await panelTable(page), drawn, 'the region\'s table as the note draws it');
  await placeCaret(page, 'mc^2', 3);
  await pause(NO_PANEL_WAIT_MS);
  const formula = await page.$eval(PANEL, panel => ({math: panel.querySelector('math') !== null, table: panel.querySelector('table') !== null}));
  assert.deepEqual(formula, {math: true, table: false}, 'caret in the formula: the formula');
  await placeCaret(page, 'Groceries', 3);
  await assertNoPanel(page, 'caret before the region');
  await leaveEditing(page);
}

// The diagram in the panel: its drawn size, its own (viewBox) size, and the panel's box.
async function panelDiagram(page) {
  return page.$eval(PANEL, panel => {
    const svg = panel.querySelector('svg');
    const box = panel.getBoundingClientRect();
    const drawn = svg.getBoundingClientRect();
    return {
      drawn: {width: drawn.width, height: drawn.height},
      own: {width: svg.viewBox.baseVal.width, height: svg.viewBox.baseVal.height},
      panel: {width: box.width, height: box.height},
      window: {width: window.innerWidth, height: window.innerHeight},
    };
  });
}

async function mermaidCases(page, ids) {
  await enterEditing(page, ids.release);
  // Clicking into the note may already have drawn the diagram for another caret.
  await placeCaret(page, 'A[Write]', 4);
  assert.ok(await becomes(page, 'diagramAtCaret', null), 'caret in the fence: the diagram, at the caret');
  await settle(page);
  assertBelowCaret(await measure(page), 'caret in the fence');
  const small = await panelDiagram(page);
  assert.ok(Math.abs(small.drawn.width - small.own.width) <= SAME_SIZE_PX && Math.abs(small.drawn.height - small.own.height) <= SAME_SIZE_PX,
    `a small diagram at its own size, never scaled up (${JSON.stringify(small)})`);
  await placeCaret(page, '```mermaid', 1);
  assert.ok(await becomes(page, 'hidden', null), 'caret on the fence line: nothing');

  await placeCaret(page, 'C[Ship]', 'C[Ship]'.length);
  assert.ok(await becomes(page, 'diagram', null), 'back in the fence: the diagram');
  const good = await measure(page);
  await page.keyboard.type(' -->');
  assert.ok(await becomes(page, 'opacity', GHOST_OPACITY), 'a dangling arrow: the last good diagram fades');
  assert.equal((await measure(page)).panel.html, good.panel.html, 'a dangling arrow: the last good diagram stays');
  await pause(BROKEN_PAUSE_WAIT_MS);
  const paused = await measure(page);
  assert.deepEqual([paused.panel.text, paused.panel.hasError, paused.panel.opacity], ['Invalid Mermaid diagram', true, FULL_OPACITY],
    'broken after a pause');
  for (let index = 0; index < ' -->'.length; index += 1) await page.keyboard.press('Backspace');
  assert.ok(await becomes(page, 'diagram', null), 'fixed: the diagram again');
  assert.ok(await becomes(page, 'opacity', FULL_OPACITY), 'fixed: at full strength');
  await leaveEditing(page);

  await enterEditing(page, ids.tall);
  await page.evaluate(() => document.querySelector('.note.editing > .note-content > div').scrollIntoView({block: 'start'}));
  await settle(page);
  await placeCaret(page, 'N2[Step', 2);
  assert.ok(await becomes(page, 'diagram', null), 'caret in a tall diagram: the diagram');
  await settle(page);
  const tall = await panelDiagram(page);
  assert.ok(tall.drawn.height < tall.own.height, `a tall diagram is scaled down (${JSON.stringify(tall)})`);
  assert.ok(tall.panel.height <= tall.window.height * PANEL_HEIGHT_SHARE + ROUNDING_PX, `it fits 40% of the window (${JSON.stringify(tall)})`);
  assert.ok(tall.panel.width <= tall.window.width - WINDOW_MARGINS_PX, `and the window's width (${JSON.stringify(tall)})`);
  assert.ok(Math.abs(tall.drawn.width / tall.drawn.height - tall.own.width / tall.own.height) <= PROPORTION_TOLERANCE * (tall.own.width / tall.own.height),
    `in proportion (${JSON.stringify(tall)})`);
  await leaveEditing(page);
}

async function jsonCases(page, ids) {
  const drawn = await page.$eval(contentOf(ids.settings), content => content.querySelector('.meta-json').outerHTML);
  await enterEditing(page, ids.settings);
  await placeCaret(page, '"tags"', 3);
  await waitForPanel(page, 'caret in compact JSON');
  assert.equal(await page.$eval(PANEL, panel => panel.querySelector('.meta-json').outerHTML), drawn, 'laid out as the note draws it');
  await placeCaret(page, '8443', '8443'.length);
  await page.keyboard.type(' "x"');
  assert.ok(await becomes(page, 'opacity', GHOST_OPACITY), 'broken: the last good drawing fades');
  await pause(BROKEN_PAUSE_WAIT_MS);
  const paused = await measure(page);
  assert.deepEqual([paused.panel.text, paused.panel.hasError, paused.panel.opacity],
    ["Invalid JSON: Expecting ',' delimiter: line 1 column 64 (char 63)", true, FULL_OPACITY], 'broken after a pause: why and where');
  for (let index = 0; index < ' "x"'.length; index += 1) await page.keyboard.press('Backspace');
  assert.ok(await becomes(page, 'opacity', FULL_OPACITY), 'fixed: at full strength');
  await idle(page);
  assert.equal(await page.$eval(PANEL, panel => panel.querySelector('.meta-json').outerHTML), drawn, 'fixed: laid out again');
  await leaveEditing(page);
}

// Whether the reference card comes to meet `condition` within PANEL_WAIT_MS, checked every frame.
async function cardBecomes(page, condition, value) {
  return page.evaluate(({condition, value, selector, timeout}) => new Promise(resolve => {
    const card = () => {
      const element = document.querySelector(selector);
      return element === null || element.hidden ? null : element;
    };
    const checks = {
      hidden: () => card() === null,
      showing: () => card() !== null && card().shadowRoot.textContent.includes(value),
      pictureLoaded: () => card() !== null && card().shadowRoot.querySelector('.note-file-image-embed[data-preview-state="loaded"] img') !== null,
    };
    const started = performance.now();
    const step = () => {
      if (checks[condition]()) {
        resolve(true);
        return;
      }
      if (performance.now() - started > timeout) {
        resolve(false);
        return;
      }
      requestAnimationFrame(step);
    };
    step();
  }), {condition, value, selector: CARD, timeout: PANEL_WAIT_MS});
}

// The card's box, and the line and left edge of the reference holding the caret.
async function cardAndReference(page, needle) {
  return page.evaluate(({selector, needle}) => {
    const card = document.querySelector(selector).getBoundingClientRect();
    const selection = getSelection().getRangeAt(0);
    const text = selection.startContainer;
    const start = text.data.lastIndexOf(needle, selection.startOffset);
    const range = document.createRange();
    range.setStart(text, start);
    range.setEnd(text, start + 1);
    const box = range.getClientRects()[0];
    return {card: {left: card.left, top: card.top}, reference: {left: box.left, bottom: box.bottom}};
  }, {selector: CARD, needle});
}

async function referenceCases(page, ids) {
  await enterEditing(page, ids.plan);
  await placeCaret(page, 'Plan:', 2);
  await pause(NO_PANEL_WAIT_MS);
  assert.ok(await cardBecomes(page, 'hidden', null), 'caret in plain text: no card');
  await placeCaret(page, ids.kyoto, 5);
  assert.ok(await cardBecomes(page, 'showing', 'Kyoto trip plan'), 'caret in a note link: its note\'s card');
  const placed = await cardAndReference(page, '[[');
  assert.ok(Math.abs(placed.card.left - placed.reference.left) <= ROUNDING_PX && Math.abs(placed.card.top - (placed.reference.bottom + GAP_PX)) <= ROUNDING_PX,
    `the card ${GAP_PX} px below the line from the reference's left edge (${JSON.stringify(placed)})`);
  await placeCaret(page, ids.kyoto, 20);
  await pause(NO_PANEL_WAIT_MS);
  assert.ok(await cardBecomes(page, 'showing', 'Kyoto trip plan'), 'moving within the reference keeps the card');
  await placeCaret(page, 'and the photo', 3);
  assert.ok(await cardBecomes(page, 'hidden', null), 'leaving the reference hides the card');
  await placeCaret(page, ids.picture, 5);
  assert.ok(await cardBecomes(page, 'pictureLoaded', null), 'caret in a picture\'s embed: the picture, loaded');
  await placeCaret(page, '|lease', 3);
  assert.ok(await cardBecomes(page, 'showing', 'lease.pdf'), 'caret in a file link: the file\'s card');
  await page.keyboard.press('Escape');
  assert.ok(await cardBecomes(page, 'hidden', null), 'Escape hides the card');
  assert.notEqual(await page.$('.note.editing'), null, 'Escape leaves editing alone');
  await placeCaret(page, '|lease', 4);
  await pause(NO_PANEL_WAIT_MS);
  assert.ok(await cardBecomes(page, 'hidden', null), 'after Escape, inside the same reference: still hidden');
  await placeCaret(page, ' end', 2);
  await pause(NO_PANEL_WAIT_MS);
  await placeCaret(page, ids.kyoto, 5);
  assert.ok(await cardBecomes(page, 'showing', 'Kyoto trip plan'), 'leaving and coming back shows a card again');
  await leaveEditing(page);
}

async function previewCases(page, ids) {
  const failures = [];
  const attempt = async (label, run) => {
    try {
      await run();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  };
  await enterEditing(page, ids.formulas);
  const textBefore = await page.$eval('.note.editing > .note-content', content => content.innerHTML);
  await attempt('1 below the caret, following it, moving no note', () => shownBelowAndFollowing(page));
  await attempt('2 nothing outside a formula', () => nothingOutsideAFormula(page));
  await attempt('3 broken mid-typing: the last good drawing fades, a pause shows why', () => brokenFormulaFades(page));
  await attempt('4 Escape hides it until the caret leaves the formula', () => escapeHidesIt(page));
  await attempt('5 above the line near the window\'s bottom', () => aboveNearTheBottom(page));
  await attempt('6 scrolling, a selection and the setting', () => scrollSelectionAndSetting(page));
  await attempt('7 the note\'s text never holds the caret mark', async () => {
    const textAfter = await page.$eval('.note.editing > .note-content', content => content.innerHTML);
    assert.equal(textAfter, textBefore, 'the edited text is as it was');
    assert.equal(textAfter.includes(CARET_MARK), false, 'no caret mark in the editor');
    await page.keyboard.press('Escape');
    await page.keyboard.press('Escape');
    await idle(page);
    // The note as shown again, drawn from what was saved.
    const shown = await page.$eval(`.note[data-note-id="${ids.formulas}"]`, note => note.innerHTML);
    assert.equal(await page.$('.note.editing'), null, 'editing ended');
    assert.equal(shown.includes(CARET_MARK), false, 'no caret mark saved');
  });
  await attempt('8 a CSV note: its table, scrolled to the caret\'s row; broken, it fades and says why', () => tableNote(page, ids));
  await attempt('9 a ((@csv)) region in a Markdown note, beside a formula', () => regionInMarkdown(page, ids));
  await attempt('10 Mermaid: a fence\'s diagram, broken and fixed; a tall one scaled down to fit', () => mermaidCases(page, ids));
  await attempt('11 JSON: compact shown laid out; broken, why and where', () => jsonCases(page, ids));
  await attempt('12 references: the card for the note, picture or file the caret is in', () => referenceCases(page, ids));
  assert.deepEqual(failures, []);
}

export async function checkEditPreviews(page) {
  await page.setViewport(WINDOW);
  const ids = await seedNotes(page);
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
  await runThenCleanUp('edit previews', () => previewCases(page, ids), async () => {
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of [ids.formulas, ids.table, ids.groceries, ids.release, ids.tall, ids.settings, ids.plan, ids.kyoto, ...ids.fillers]) await NotesAPI.deleteNote(id);
    }, ids);
  });
}
