import assert from 'node:assert/strict';

export async function checkTagDoubleClickSelection(page) {
  const noteId = await page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, 'Double click selection test', 'foo-bar @red alpha_beta a/b.c');
    return note.id;
  });
  await page.reload();
  await page.waitForSelector('[data-app-ready="true"]');
  await page.click(`[data-note-id="${noteId}"] > .note-content`);
  await page.waitForSelector('.note.editing .note-tag-bar-input');
  await page.waitForFunction(async () => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return !ModeContextInstance.isLoading;
  });
  await page.click('.note.editing .note-tag-bar-input');
  await page.waitForFunction(() => document.activeElement.classList.contains('note-tag-bar-input'));
  // A click that leaves the caret at the end adds a space for the next tag, a moment later.
  await page.waitForFunction(() => document.activeElement.value === 'foo-bar @red alpha_beta a/b.c ');
  await checkInput(page, '.note.editing .note-tag-bar-input');
  await page.keyboard.press('Escape');
  await page.click('#search-input');
  await page.keyboard.type('foo-bar @red alpha_beta a/b.c');
  await checkInput(page, '#search-input');
  await page.$eval('#search-input', input => { input.focus(); input.select(); });
  await page.keyboard.press('Backspace');
  await page.waitForFunction(async () => {
    const {ModeContextInstance} = await import('/static/js/modules/mode-manager/mode-context.js');
    return document.getElementById('search-input').value === ''
      && ModeContextInstance.getExecutedSearchQuery() === '' && !ModeContextInstance.isLoading;
  });
  await page.keyboard.press('Escape');
  console.log('PASS native double-click selects complete tags in search and tag bar');
}

async function checkInput(page, selector) {
  for (const [tag, characterOffset] of [['foo-bar', 1], ['foo-bar', 5], ['@red', 0], ['@red', 2], ['alpha_beta', 7], ['a/b.c', 3]]) {
    const point = await page.$eval(selector, (input, tag, characterOffset) => {
      input.focus();
      input.scrollLeft = 0;
      const style = getComputedStyle(input);
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      context.font = style.font;
      const index = input.value.indexOf(tag) + characterOffset;
      const width = context.measureText(input.value.slice(0, index)).width;
      const characterWidth = context.measureText(input.value[index]).width;
      const bounds = input.getBoundingClientRect();
      return {x:bounds.left + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft) + width + characterWidth / 2,
        y:bounds.top + bounds.height / 2, value:input.value};
    }, tag, characterOffset);
    await recordTagBoxTouches(page, selector);
    await page.mouse.click(point.x, point.y, {count:2});
    const found = await page.$eval(selector, input => ({
      selection:input.value.slice(input.selectionStart, input.selectionEnd), value:input.value,
    }));
    // A failure says what touched the box during the double-click (GitHub, Firefox, now and then:
    // nothing selected, once with the box's trailing space gone).
    const touches = await page.evaluate(() => window.__tagBoxTouches);
    assert.deepEqual(found, {selection:tag, value:point.value}, `what touched ${selector}: ${JSON.stringify(touches)}`);
  }
}

// Records, from now until read, each mouse event on the box (with its click count and the
// selection after it), each write of its value (with where from), and the box leaving the page.
async function recordTagBoxTouches(page, selector) {
  await page.$eval(selector, input => {
    const touches = [];
    window.__tagBoxTouches = touches;
    const selected = () => `${input.selectionStart}-${input.selectionEnd}`;
    for (const type of ['mousedown', 'mouseup', 'click', 'dblclick', 'focus', 'blur', 'select']) {
      input.addEventListener(type, event => {
        queueMicrotask(() => touches.push(`${type}#${event.detail} ${selected()} active=${document.activeElement === input}`));
      }, {capture: true});
    }
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    Object.defineProperty(input, 'value', {
      configurable: true,
      get: Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').get,
      set(next) {
        touches.push(`value set ${JSON.stringify(next)} from ${new Error().stack.split('\n').slice(1, 4).join(' < ')}`);
        valueSetter.call(this, next);
      },
    });
    const setRange = input.setSelectionRange;
    input.setSelectionRange = function (...range) {
      touches.push(`setSelectionRange ${range.slice(0, 2).join('-')} from ${new Error().stack.split('\n').slice(1, 3).join(' < ')}`);
      return setRange.apply(this, range);
    };
    new MutationObserver(() => {
      if (!input.isConnected) touches.push('box removed from the page');
    }).observe(document.body, {childList: true, subtree: true});
  });
}
