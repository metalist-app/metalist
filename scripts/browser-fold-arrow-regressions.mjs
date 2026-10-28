import assert from 'node:assert/strict';
import { runThenCleanUp } from './suite-outcome.mjs';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Where a note's fold arrow (▾/▸) sits (agreed 2026-10-26, docs/ui/references.md and
// docs/ui/controls.md): on the baseline of the note's first line of text, as a bullet
// sits on its line, so it is level with that line at any size: plain, the top-level
// note sizes, a heading, a line that wraps, a line starting with a checkbox, a
// credential row or a link, an empty line. Folding moves neither the arrow nor the
// line; while editing it follows the edited line. A first line that is not text (a
// picture, a formula, a diagram, a table, code) keeps the arrow at the note's top,
// 3 px down, as before. The same rule holds for notes in embeds, an embed amid
// other text, phone width and downloaded exports.
//
// Which notes get an arrow (agreed 2026-10-26, docs/ui/references.md): a note that
// is only an embed folds when its source can, so an embed of a one-line note with
// no children has none, even saved as folded; it gets one once the source gains a
// second line.
//
// A folded note shows its first line as it is shown (agreed 2026-10-26): an embed
// always starts a line of its own and stays an embed folded, so "Snack: ![[Almonds]]"
// has an arrow and folds to "Snack:"; "![[Almonds]] for snack" folds to the Almonds
// embed; a note that is only an embed of a longer note folds to that embed, its
// source folded. Folding moves neither the arrow nor the first line.
//
// Each check reads two baselines with zero-size markers the page lays out itself:
// one placed before the first letter of the first line, one placed in the arrow.
// They must agree to the pixel.

const REQUESTS_QUIET_MS = 300;
const SETTLE_MS = 400;
// A difference under one pixel is the same pixel row.
const SAME_PIXEL = 1;
// The arrow's place when the first line is not text: its top this far below the note's top.
const TOP_ARROW_OFFSET_PX = 3;
const PHONE_WIDTH_PX = 375;
const PHONE_HEIGHT_PX = 812;
const LONG_LINE = 'A first line long enough to wrap onto more lines in any window MetaList is shown in, '
  + 'because it keeps going well past the width of a note and on again past it once more.';
const PNG_BASE64 = 'iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAAQklEQVR4nO3OQQ0AIAwAsQlDBLKRhQuOR5MK6Jy9vjL5QEhISKgeCAkJCdUDISEhoXogJCQkVA+EhISE6oGQkNBjF21V9KbVaAsfAAAAAElFTkSuQmCC';

async function idle(page) {
  await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function reloadApp(page) {
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await idle(page);
}

// Each note gets a second line or a child, so it can fold and shows its arrow.
async function seedNotes(page) {
  return page.evaluate(async ({longLine, png}) => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const make = async (html, tags) => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, html, tags);
      return note.id;
    };
    const child = async (parentId, html, tags) => {
      const note = await NotesAPI.createChild(parentId, '');
      await NotesAPI.saveNote(note.id, html, tags);
      return note.id;
    };
    const ids = {};
    ids.plain = await make('<div>Plain first line</div><div>Second line</div>', '');
    ids.heading = await make('<div>Heading first line</div><div>Second line</div>', '@heading @green');
    ids.markdownHeading = await make('<div># Markdown title</div><div>Body text</div>', '@markdown');
    // A child keeps the arrow while the note is edited (an arrow that folds only text hides then).
    await child(ids.markdownHeading, '<div>A child of the Markdown note</div>', '');
    ids.wrapping = await make(`<div>${longLine}</div><div>Second line</div>`, '');
    ids.todo = await make('<div>A thing to do</div><div>Details</div>', '@todo');
    ids.username = await make('<div>tom@example.org</div>', '@username');
    await child(ids.username, '<div>Where it is used</div>', '');
    ids.link = await make(`<div>[[${ids.plain}]] and more</div><div>Second line</div>`, '');
    // Pasted or AI-written text starts with a paragraph.
    ids.paragraph = await make('<p>A paragraph first</p><p>Another paragraph</p>', '');
    ids.empty = await make('', '');
    await child(ids.empty, '<div>A child of the empty note</div>', '');
    ids.picture = await make(`<div><img src="data:image/png;base64,${png}" alt="dot"></div><div>Text after</div>`, '');
    ids.formula = await make('<div>$$x^2 + y^2 = z^2$$</div><div>After the formula</div>', '@markdown');
    ids.mermaid = await make(['```mermaid', 'flowchart TD', 'A[Start] --> B[End]', '```', 'After the diagram']
      .map(line => `<div>${line}</div>`).join(''), '@markdown');
    ids.table = await make(['| A | B |', '|---|---|', '| 1 | 2 |', '', 'After the table']
      .map(line => `<div>${line}</div>`).join(''), '@markdown');
    ids.code = await make(['```', 'code first', '```', 'After the code'].map(line => `<div>${line}</div>`).join(''), '@markdown');
    ids.source = await make('<div>Embedded source</div>', '@heading');
    ids.sourceChild = await child(ids.source, '<div>Source child first line</div><div>Its second line</div>', '');
    ids.holder = await make(`<div>![[${ids.source}]]</div>`, '');
    ids.amid = await make(`<div>Before</div><div>![[${ids.source}]]</div><div>After</div>`, '');
    ids.oneLine = await make('<div>Almonds</div>', '');
    ids.oneLineHolder = await make(`<div>![[${ids.oneLine}]]</div>`, '');
    ids.foldedOneLine = await make('<div>Cashews</div>', '');
    ids.foldedOneLineHolder = await make(`<div>![[${ids.foldedOneLine}]]</div>`, '');
    await NotesAPI.setCollapsedBulk([ids.foldedOneLine, ids.foldedOneLineHolder], true);
    ids.oneLineAmid = await make(`<div>Snack: ![[${ids.oneLine}]]</div>`, '');
    ids.almonds = await make('<div>Almonds</div>', '');
    ids.nuts = await make('<div>Nuts</div><div>Almonds, cashews</div>', '');
    ids.embedFirst = await make(`<div>![[${ids.almonds}]] for snack</div>`, '');
    ids.nutsHolder = await make(`<div>![[${ids.nuts}]]</div>`, '');
    // Folded, each shows one line, cut with … when too long (2026-10-27).
    ids.foldedTodo = await make('<div>Buy milk</div>', '@todo');
    await child(ids.foldedTodo, '<div>Whole milk</div>', '');
    ids.longSource = await make(`<div>${longLine}</div><div>Second line</div>`, '');
    await child(ids.longSource, '<div>A child of the long note</div>', '');
    ids.longHolder = await make(`<div>![[${ids.longSource}]]</div>`, '');
    ids.longFirst = await make(`<div>![[${ids.longSource}]] for snack</div>`, '');
    ids.openSource = await make('<div>Open source</div>', '');
    ids.foldedLongChild = await child(ids.openSource, `<div>${longLine}</div><div>Second line</div>`, '');
    ids.openHolder = await make(`<div>![[${ids.openSource}]]</div>`, '');
    ids.todoSource = await make('<div>Feed the cat</div>', '@todo');
    await child(ids.todoSource, '<div>Twice a day</div>', '');
    ids.todoHolder = await make(`<div>![[${ids.todoSource}]]</div>`, '');
    // One line that wraps: it folds, as text typed in the editor (a <div>) or in an embed.
    ids.wrappingOnly = await make(`<div>${longLine}</div>`, '');
    ids.wrappingHolder = await make(`<div>![[${ids.wrappingOnly}]]</div>`, '');
    await NotesAPI.setCollapsedBulk([ids.foldedLongChild], true);
    return ids;
  }, {longLine: LONG_LINE, png: PNG_BASE64});
}

// The arrow's baseline and the first line's, for a note in the list or in an embed.
// `arrowSelector` and `contentSelector` find the arrow and the text it folds.
async function baselines(page, arrowSelector, contentSelector) {
  return page.evaluate(({arrowSelector, contentSelector}) => {
    const marker = () => {
      const node = document.createElement('span');
      node.style.cssText = 'display:inline-block;width:0;height:0;padding:0;margin:0;border:0;vertical-align:baseline';
      return node;
    };
    const arrow = document.querySelector(arrowSelector);
    // An export holds a folded and an unfolded copy of the text: the one shown.
    const content = [...document.querySelectorAll(contentSelector)].find(node => getComputedStyle(node).display !== 'none');
    if (arrow === null || content === undefined) return {missing: `${arrowSelector} or ${contentSelector}`};
    if (getComputedStyle(arrow).display === 'none') return {missing: `${arrowSelector} (hidden)`};
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, {
      acceptNode: text => (/\S/.test(text.data) && text.parentElement.getClientRects().length > 0
        ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
    });
    const text = walker.nextNode();
    if (text === null) return {missing: `text in ${contentSelector}`};
    const parent = text.parentNode;
    const range = document.createRange();
    range.setStart(text, text.data.search(/\S/));
    const lineMarker = marker();
    range.insertNode(lineMarker);
    const line = lineMarker.getBoundingClientRect().bottom;
    lineMarker.remove();
    parent.normalize();
    const arrowMarker = marker();
    arrow.appendChild(arrowMarker);
    const glyph = arrowMarker.getBoundingClientRect().bottom;
    arrowMarker.remove();
    // Both again from the top of the note the arrow belongs to, which scrolling doesn't change.
    const top = arrow.parentElement.getBoundingClientRect().top;
    return {arrow: glyph, line, arrowInNote: glyph - top, lineInNote: line - top, screenPixel: 1 / window.devicePixelRatio};
  }, {arrowSelector, contentSelector});
}

function assertLevel(measured, label) {
  assert.equal(measured.missing, undefined, `${label}: no arrow to measure: ${measured.missing}`);
  // Within one screen pixel: on a 1x screen Firefox rounds the font's metrics to whole pixels,
  // and with Linux's font the arrow lands a pixel off (agreed 2026-10-28; a 2x Mac is exact).
  assert.equal(typeof measured.screenPixel, 'number', `${label}: the measurement gives the screen pixel`);
  assert.ok(Math.abs(measured.arrow - measured.line) <= Math.max(SAME_PIXEL, measured.screenPixel),
    `${label}: the arrow's baseline (${measured.arrow}) is the first line's (${measured.line})`);
}

const noteArrow = id => `.note[data-note-id="${id}"] > .note-collapse-toggle`;
const noteContent = id => `.note[data-note-id="${id}"] > .note-content`;

async function noteBaselines(page, id) {
  await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), id);
  return baselines(page, noteArrow(id), noteContent(id));
}

// For a first line that is not text: the arrow's top below the note's top.
async function arrowOffset(page, id) {
  return page.evaluate(selector => {
    const arrow = document.querySelector(selector);
    // From the inside of the note's border, where the arrow's offset is measured.
    const note = arrow.parentElement;
    return arrow.getBoundingClientRect().top - (note.getBoundingClientRect().top + note.clientTop);
  }, noteArrow(id));
}

// Whether the note shows its arrow, and whether it is drawn folded.
async function arrowState(page, id) {
  return page.evaluate(id => {
    const note = document.querySelector(`.note[data-note-id="${id}"]`);
    note.scrollIntoView({block: 'center'});
    const arrow = note.querySelector(':scope > .note-collapse-toggle');
    return {
      shown: arrow !== null && getComputedStyle(arrow).display !== 'none' && arrow.getClientRects().length > 0,
      folded: note.classList.contains('collapsed'),
    };
  }, id);
}

// A folded note's line in `boxSelector` (the note's content, or a folded note's in an
// embed): the box's height and line height, where its first text sits in it, whether
// more was cut off, and the box of a checkbox on the line.
async function foldedLine(page, boxSelector) {
  return page.evaluate(selector => {
    const box = [...document.querySelectorAll(selector)].find(node => node.getClientRects().length > 0);
    if (box === undefined) return {missing: selector};
    const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT, {
      acceptNode: text => (/\S/.test(text.data) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
    });
    const text = walker.nextNode();
    if (text === null) return {missing: `text in ${selector}`};
    const range = document.createRange();
    range.selectNodeContents(text);
    const textRect = range.getClientRects()[0];
    const boxRect = box.getBoundingClientRect();
    const checkbox = box.querySelector('.meta-status-toggle');
    return {
      text: text.data.trim(),
      height: boxRect.height,
      lineHeight: parseFloat(getComputedStyle(box).lineHeight),
      textInside: textRect.top >= boxRect.top && textRect.bottom <= boxRect.bottom,
      textLines: range.getClientRects().length,
      cut: box.scrollHeight > box.clientHeight || box.scrollWidth > box.clientWidth,
      textMiddle: (textRect.top + textRect.bottom) / 2,
      checkbox: checkbox === null ? null : {top: checkbox.getBoundingClientRect().top, bottom: checkbox.getBoundingClientRect().bottom},
    };
  }, boxSelector);
}

// One line shown: as tall as one line of its text, the text in it, the rest cut off.
function assertOneCutLine(line, label) {
  assert.equal(line.missing, undefined, `${label}: ${line.missing}`);
  assert.equal(line.textInside, true, `${label}: the first line's text is shown`);
  assert.ok(Math.abs(line.height - line.lineHeight) < SAME_PIXEL, `${label}: one line tall (${line.height}, a line is ${line.lineHeight})`);
  assert.equal(line.cut, true, `${label}: the rest of the long line is cut off`);
}

// The checkbox and its text on one shown line.
function assertCheckboxLine(line, text, label) {
  assert.equal(line.missing, undefined, `${label}: ${line.missing}`);
  assert.equal(line.text, text, `${label}: the line's text`);
  assert.equal(line.textInside, true, `${label}: the text is shown, not cut off below the checkbox`);
  assert.equal(line.textLines, 1, `${label}: the text stays on one line`);
  assert.notEqual(line.checkbox, null, `${label}: a checkbox`);
  assert.ok(line.textMiddle > line.checkbox.top && line.textMiddle < line.checkbox.bottom, `${label}: the text is level with the checkbox`);
}

async function setTopLevelSize(page, size) {
  await page.evaluate(size => { document.body.dataset.topLevelNoteSize = size; }, size);
  await new Promise(resolve => setTimeout(resolve, SETTLE_MS));
}

async function foldArrowCases(browser, page, ids) {
  const failures = [];
  const attempt = async (label, run) => {
    try {
      await run();
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`${label}: ${error.message}`);
    }
  };

  await attempt('1 a plain first line at normal size', async () => {
    assertLevel(await noteBaselines(page, ids.plain), 'plain');
  });
  await attempt('2 the larger and largest top-level note sizes', async () => {
    for (const size of ['larger', 'largest']) {
      await setTopLevelSize(page, size);
      assertLevel(await noteBaselines(page, ids.plain), `plain, ${size}`);
      assertLevel(await noteBaselines(page, ids.heading), `heading, ${size}`);
    }
    await setTopLevelSize(page, 'same');
  });
  await attempt('3 a bigger first line: @heading and a Markdown heading', async () => {
    assertLevel(await noteBaselines(page, ids.heading), '@heading');
    assertLevel(await noteBaselines(page, ids.markdownHeading), 'Markdown #');
  });
  await attempt('4 a first line that wraps: on its first visual line', async () => {
    assertLevel(await noteBaselines(page, ids.wrapping), 'wrapping');
  });
  await attempt('5 a checkbox, a credential row or a link before the text', async () => {
    assertLevel(await noteBaselines(page, ids.todo), '@todo');
    assertLevel(await noteBaselines(page, ids.username), '@username');
    assertLevel(await noteBaselines(page, ids.link), 'link first');
  });
  await attempt('6 an empty first line: level with an empty line', async () => {
    const measured = await page.evaluate(selectors => {
      const arrow = document.querySelector(selectors.arrow);
      const content = document.querySelector(selectors.content);
      const probe = document.createElement('div');
      probe.textContent = 'x';
      content.appendChild(probe);
      const range = document.createRange();
      range.setStart(probe.firstChild, 0);
      const marker = document.createElement('span');
      marker.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline';
      range.insertNode(marker);
      const line = marker.getBoundingClientRect().bottom;
      probe.remove();
      const arrowMarker = marker.cloneNode();
      arrow.appendChild(arrowMarker);
      const glyph = arrowMarker.getBoundingClientRect().bottom;
      arrowMarker.remove();
      return {arrow: glyph, line, screenPixel: 1 / window.devicePixelRatio};
    }, {arrow: noteArrow(ids.empty), content: noteContent(ids.empty)});
    assertLevel(measured, 'empty');
  });
  await attempt('7 folding moves neither the arrow nor the line', async () => {
    // A link first and a paragraph first were drawn differently folded (a tighter line, no margin).
    for (const name of ['plain', 'link', 'paragraph', 'heading']) {
      await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), ids[name]);
      const before = await baselines(page, noteArrow(ids[name]), noteContent(ids[name]));
      await page.click(noteArrow(ids[name]));
      await idle(page);
      const folded = await baselines(page, noteArrow(ids[name]), noteContent(ids[name]));
      assert.equal(await page.$eval(`.note[data-note-id="${ids[name]}"]`, note => note.classList.contains('collapsed')), true, `${name}: folded`);
      assert.ok(Math.abs(folded.arrowInNote - before.arrowInNote) < SAME_PIXEL && Math.abs(folded.lineInNote - before.lineInNote) < SAME_PIXEL,
        `${name}: folding moves nothing (before ${JSON.stringify(before)}, folded ${JSON.stringify(folded)})`);
      await page.click(noteArrow(ids[name]));
      await idle(page);
    }
  });
  await attempt('8 while editing: on the edited first line', async () => {
    await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), ids.markdownHeading);
    const box = await (await page.$(noteContent(ids.markdownHeading))).boundingBox();
    await page.mouse.click(box.x + box.width - 4, box.y + box.height - 4);
    await page.waitForFunction(async id => {
      const {ModeContextInstance: mode} = await import('/static/js/modules/mode-manager/mode-context.js');
      return mode.isEditing && mode.currentNoteId === id;
    }, {}, ids.markdownHeading);
    await idle(page);
    await new Promise(resolve => setTimeout(resolve, SETTLE_MS));
    assertLevel(await baselines(page, noteArrow(ids.markdownHeading), noteContent(ids.markdownHeading)), 'editing');
    await page.keyboard.press('Escape');
    await idle(page);
    await new Promise(resolve => setTimeout(resolve, SETTLE_MS));
    assertLevel(await noteBaselines(page, ids.markdownHeading), 'after editing');
  });
  await attempt('9 and 10 a first line that is not text: the arrow at the top, as before', async () => {
    for (const name of ['picture', 'formula', 'mermaid', 'table', 'code']) {
      await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), ids[name]);
      const offset = await arrowOffset(page, ids[name]);
      assert.ok(Math.abs(offset - TOP_ARROW_OFFSET_PX) < SAME_PIXEL, `${name}: the arrow's top is ${TOP_ARROW_OFFSET_PX} px below the note's (${offset})`);
    }
  });
  await attempt('11 a note that is only an embed: on the source\'s first line', async () => {
    assertLevel(await noteBaselines(page, ids.holder), 'holder');
  });
  await attempt('12 a note inside an embed: on its own first line', async () => {
    await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), ids.holder);
    const node = `.note[data-note-id="${ids.holder}"] .note-embed-node[data-embed-note-id="${ids.sourceChild}"]`;
    assertLevel(await baselines(page, `${node} > .note-embed-body > .note-embed-collapse-toggle`,
      `${node} > .note-embed-body > .note-embed-content`), 'note in an embed');
  });
  await attempt('13 an embed amid other text: on the source\'s first line', async () => {
    await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), ids.amid);
    const root = `.note[data-note-id="${ids.amid}"] .note-embed-block:not(.note-embed-held) .note-embed-root`;
    assertLevel(await baselines(page, `${root} > .note-embed-body > .note-embed-collapse-toggle`,
      `${root} > .note-embed-body > .note-embed-content`), 'embed amid text');
  });
  await attempt('14 phone width', async () => {
    const window = page.viewport();
    await page.setViewport({width: PHONE_WIDTH_PX, height: PHONE_HEIGHT_PX});
    await reloadApp(page);
    try {
      assertLevel(await noteBaselines(page, ids.heading), 'phone, heading');
    } finally {
      await page.setViewport(window);
      await reloadApp(page);
    }
  });
  await attempt('14 a downloaded export', async () => {
    const htmlText = await page.evaluate(async () => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      const {blob} = await NotesAPI.exportCurrentViewAsHtml('light', {noteId: null, includeCredentials: false, title: ''});
      return blob.text();
    });
    const file = await browser.newPage();
    try {
      await file.setContent(htmlText, {waitUntil: 'load'});
      await new Promise(resolve => setTimeout(resolve, SETTLE_MS));
      for (const name of ['plain', 'heading']) {
        assertLevel(await baselines(file, `#note-${ids[name]} > .note-collapse-toggle`, `#note-${ids[name]} > .note-content`), `export, ${name}`);
      }
    } finally {
      await file.close();
    }
  });
  await attempt('15 an embed of a one-line note: no arrow', async () => {
    assert.deepEqual(await arrowState(page, ids.oneLineHolder), {shown: false, folded: false});
    assert.equal(await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).textContent.trim(), ids.oneLineHolder),
      'Almonds', 'the embed shows its source');
  });
  await attempt('16 an embed of a one-line note saved as folded: no arrow, shown unfolded', async () => {
    assert.deepEqual(await arrowState(page, ids.foldedOneLineHolder), {shown: false, folded: false});
  });
  // Folds the note by its arrow and returns what it shows folded; the arrow and the first line must not move.
  const foldShows = async (id, label) => {
    await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), id);
    const before = await baselines(page, noteArrow(id), noteContent(id));
    assertLevel(before, `${label}, unfolded`);
    await page.click(noteArrow(id));
    await idle(page);
    const folded = await baselines(page, noteArrow(id), noteContent(id));
    assertLevel(folded, `${label}, folded`);
    assert.ok(Math.abs(folded.arrowInNote - before.arrowInNote) < SAME_PIXEL && Math.abs(folded.lineInNote - before.lineInNote) < SAME_PIXEL,
      `${label}: folding moves nothing (before ${JSON.stringify(before)}, folded ${JSON.stringify(folded)})`);
    const shown = await page.evaluate(selector => {
      const content = document.querySelector(selector);
      return {text: content.innerText.split(/\s+/).filter(Boolean).join(' '), embeds: content.querySelectorAll('.note-embed-block').length};
    }, noteContent(id));
    await page.click(noteArrow(id));
    await idle(page);
    return shown;
  };
  await attempt('17 "Snack: ![[Almonds]]" folds to "Snack:"', async () => {
    assert.deepEqual(await foldShows(ids.oneLineAmid, 'Snack'), {text: 'Snack:', embeds: 0});
  });
  await attempt('19 "![[Almonds]] for snack" folds to the Almonds embed', async () => {
    assert.deepEqual(await foldShows(ids.embedFirst, 'embed first'), {text: 'Almonds', embeds: 1});
  });
  await attempt('20 a note that is only an embed of a longer note folds to that embed, its source folded', async () => {
    assert.deepEqual(await foldShows(ids.nutsHolder, 'Nuts holder'), {text: 'Nuts', embeds: 1});
  });
  // Folds the note by its arrow, measures the folded line in `boxSelector` with `measure`, and unfolds it.
  const whileFolded = async (id, measure) => {
    await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), id);
    await page.click(noteArrow(id));
    await idle(page);
    const measured = await measure();
    await page.click(noteArrow(id));
    await idle(page);
    return measured;
  };
  const foldedEmbedLine = id => `.note[data-note-id="${id}"] > .note-content .note-embed-root.note-embed-collapsed > .note-embed-body > .note-embed-content`;
  await attempt('21 a to-do with a child, folded: its checkbox and text on one line', async () => {
    assertCheckboxLine(await whileFolded(ids.foldedTodo, () => foldedLine(page, noteContent(ids.foldedTodo))), 'Buy milk', 'folded to-do');
  });
  await attempt('22 a note that is only an embed of a note with a long first line, folded: one line', async () => {
    assertOneCutLine(await whileFolded(ids.longHolder, () => foldedLine(page, foldedEmbedLine(ids.longHolder))), 'long holder');
  });
  await attempt('23 "![[long note]] for snack", folded: the embed, folded to one line', async () => {
    const folded = await whileFolded(ids.longFirst, async () => ({
      line: await foldedLine(page, foldedEmbedLine(ids.longFirst)),
      // One arrow for the one line: the note's own.
      embedArrow: await page.$eval(`.note[data-note-id="${ids.longFirst}"] > .note-content .note-embed-root > .note-embed-body > .note-embed-collapse-toggle`,
        arrow => getComputedStyle(arrow).visibility),
    }));
    assertOneCutLine(folded.line, 'long embed first');
    assert.equal(folded.embedArrow, 'hidden', 'the embed\'s own arrow is hidden while its note is folded');
  });
  await attempt('24 a folded note in an open embed: one line', async () => {
    await page.evaluate(id => document.querySelector(`.note[data-note-id="${id}"]`).scrollIntoView({block: 'center'}), ids.openHolder);
    const node = `.note[data-note-id="${ids.openHolder}"] .note-embed-node[data-embed-note-id="${ids.foldedLongChild}"].note-embed-collapsed`;
    assertOneCutLine(await foldedLine(page, `${node} > .note-embed-body > .note-embed-content`), 'folded note in an embed');
  });
  await attempt('25 a note that is only an embed of a to-do, folded: its checkbox and text on one line', async () => {
    assertCheckboxLine(await whileFolded(ids.todoHolder, () => foldedLine(page, foldedEmbedLine(ids.todoHolder))), 'Feed the cat', 'folded to-do embed');
  });
  await attempt('26 one line that wraps: an arrow', async () => {
    assert.deepEqual(await arrowState(page, ids.wrappingOnly), {shown: true, folded: false});
  });
  await attempt('27 a note that is only an embed of one line that wraps: an arrow, folding to one line', async () => {
    assert.deepEqual(await arrowState(page, ids.wrappingHolder), {shown: true, folded: false});
    assertOneCutLine(await whileFolded(ids.wrappingHolder, () => foldedLine(page, foldedEmbedLine(ids.wrappingHolder))), 'wrapping holder');
    assert.deepEqual(await arrowState(page, ids.wrappingHolder), {shown: true, folded: false});
  });
  await attempt('18 the source gains a second line: the embed gets an arrow', async () => {
    await page.evaluate(async id => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      await NotesAPI.saveNote(id, '<div>Almonds</div><div>raw, unsalted</div>', '');
    }, ids.oneLine);
    await reloadApp(page);
    assert.deepEqual(await arrowState(page, ids.oneLineHolder), {shown: true, folded: false});
  });

  assert.deepEqual(failures, []);
}

export async function checkFoldArrows(browser, page) {
  const ids = await seedNotes(page);
  await reloadApp(page);
  await runThenCleanUp('fold arrows', () => foldArrowCases(browser, page, ids), async () => {
    await reloadApp(page);
    await page.evaluate(async ids => {
      const {NotesAPI} = await import('/static/js/modules/api-client.js');
      for (const id of [ids.wrappingHolder, ids.wrappingOnly, ids.todoHolder, ids.todoSource, ids.openHolder, ids.openSource, ids.longFirst, ids.longHolder, ids.longSource, ids.foldedTodo,
        ids.nutsHolder,ids.embedFirst, ids.nuts, ids.almonds, ids.oneLineAmid, ids.oneLineHolder, ids.oneLine, ids.foldedOneLineHolder, ids.foldedOneLine,
        ids.holder, ids.amid, ids.link, ids.paragraph, ids.plain, ids.heading, ids.markdownHeading, ids.wrapping, ids.todo,
        ids.username, ids.empty, ids.picture, ids.formula, ids.mermaid, ids.table, ids.code, ids.source]) {
        await NotesAPI.deleteNote(id);
      }
    }, ids);
  });
}
