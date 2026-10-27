import assert from 'node:assert/strict';

// The phone prototype (docs/ui/phone.md and docs/ui/phone-mocks.html;
// agreed case by case 2026-10-24): under 640 px the search bar alone on top with term and view
// pills, rows below without tag chips, a bottom bar with the menu sheet and capture; a tapped
// note never edits, it shows its own tags; a tag pill searches; back restores the search.

const PHONE = {width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3};
const FRAMES_TO_SETTLE = 3;
const EDGE_PX = 1;
// The developer switch for what a tag pill does (phone-mode.js).
const TAG_PILL_SWITCH = 'metalist.dev.phoneTagPills';
// Escape presses and a reload that clear whatever a failed case left behind.
const ESCAPES_AFTER_A_FAILURE = 2;

async function settle(page) {
  await page.evaluate(frames => new Promise(resolve => {
    const step = left => (left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1)));
    step(frames);
  }), FRAMES_TO_SETTLE);
}

async function waitQuiet(page) {
  await page.waitForFunction(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {CommandGate} = await import('/static/js/modules/mode-manager/services/command-gate-service.js');
    return !state.isLoading && !CommandGate.isBusy();
  });
  await settle(page);
}

async function searchQuery(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    return state.searchQuery;
  });
}

async function search(page, query) {
  await page.evaluate(async text => {
    const {syncSearchInputValue} = await import('/static/js/modules/mode-manager/services/search-input-service.js');
    // As typing does: the field gets focus, the text changes, then the field is left.
    const input = document.getElementById('search-input');
    input.focus();
    syncSearchInputValue(input, text);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.blur();
  }, query);
  // A typed search runs after a short pause: wait until it has run, not only been typed.
  await page.waitForFunction(async text => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    const {isDebouncedSearchPending} = await import('/static/js/modules/mode-manager/services/search-debounce-service.js');
    return state.searchQuery === text && !isDebouncedSearchPending() && !state.isLoading;
  }, {}, query);
  await waitQuiet(page);
}

function box(page, selector) {
  return page.$eval(selector, element => {
    const rect = element.getBoundingClientRect();
    return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width,
      shown: element.getClientRects().length > 0};
  });
}

async function noteSelector(page, text) {
  const ids = await page.evaluate(wanted => [...document.querySelectorAll('.note')]
    .filter(element => element.querySelector(':scope > .note-content')?.textContent.trim() === wanted)
    .map(element => element.dataset.noteId), text);
  assert.equal(ids.length, 1, `note "${text}" must be in the list once`);
  return `.note[data-note-id="${ids[0]}"]`;
}

async function tapNote(page, text) {
  const selector = await noteSelector(page, text);
  await page.tap(`${selector} > .note-content`);
  await waitQuiet(page);
  return selector;
}

async function isEditing(page) {
  return page.evaluate(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    return state.isEditing;
  });
}

async function seedNotes(page) {
  await page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const add = async (text, tags) => {
      const note = await NotesAPI.createNote(null, '');
      await NotesAPI.saveNote(note.id, `<p>${text}</p>`, tags);
      return note.id;
    };
    await add('Phone noodle machine', 'phonetest kitchen');
    const parent = await add('Phone ramen experiments', 'phonetest recipes japanese');
    const child = await NotesAPI.createChild(parent, '');
    await NotesAPI.saveNote(child.id, '<p>Phone tare ratio</p>', '');
    await NotesAPI.collapseNote(parent);
  });
}

async function layoutCase(page) {
  const viewport = page.viewport();
  const bar = await box(page, '#phone-bar');
  assert.equal(bar.shown, true, 'the bottom bar must show');
  assert(Math.abs(bar.bottom - viewport.height) <= EDGE_PX, 'the bottom bar must sit at the bottom');
  assert(Math.abs(bar.width - viewport.width) <= EDGE_PX, 'the bottom bar must span the screen');
  const menu = await box(page, '#phone-menu-button');
  const capture = await box(page, '#phone-capture-button');
  assert(menu.right < viewport.width / 2, 'the menu button must sit at the left');
  assert(capture.left > viewport.width / 2, 'the capture button must sit at the right');
  for (const hidden of ['#tab-hover-zone', '.global-controls']) {
    assert.equal((await box(page, hidden)).shown, false, `${hidden} must be hidden on the phone`);
  }
  const row = await box(page, '.search-input-row');
  assert(row.left >= 0 && row.right <= viewport.width, 'the search bar must fit the screen');
  const hasRowChips = await page.$$eval('.note-tags', elements => elements.some(element => element.getClientRects().length > 0));
  assert.equal(hasRowChips, false, 'rows must show no tag chips');
  const toggle = await box(page, `${await noteSelector(page, 'Phone ramen experiments')} > .note-collapse-toggle`);
  assert(toggle.left >= 0, 'the expand arrow must be on screen');
  const lastNoteBottom = await page.evaluate(() => {
    const notes = [...document.querySelectorAll('#notes-container .note')];
    const container = document.getElementById('notes-container').getBoundingClientRect();
    return {containerBottom: container.bottom, scrollHeight: document.scrollingElement.scrollHeight, notes: notes.length};
  });
  assert(lastNoteBottom.notes > 0, 'the list must show notes');
}

async function searchPillsCase(page) {
  await search(page, 'phonetest -journal');
  const pills = await page.$$eval('.phone-search-pills .phone-search-pill',
    elements => elements.map(element => [element.dataset.term, element.classList.contains('is-exclusion')]));
  assert.deepEqual(pills, [['phonetest', false], ['-journal', true]], 'each term must show as a pill');
  assert.equal((await box(page, '#search-input')).shown, false, 'the typed text hides behind its pills');
  await page.tap('.phone-search-pill[data-term="-journal"] .phone-search-pill-remove');
  await page.waitForFunction(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    return state.searchQuery === 'phonetest' && !state.isLoading;
  });
  await waitQuiet(page);
}

async function tapCase(page) {
  await search(page, 'phonetest');
  const selector = await tapNote(page, 'Phone noodle machine');
  assert.equal(await isEditing(page), false, 'a tap must never edit on the phone');
  const pills = await page.$$eval(`${selector} > .phone-note-tags .phone-tag-pill`, elements => elements.map(element => element.textContent.trim()));
  assert.deepEqual(pills, ['phonetest', 'kitchen'], "the note's own tags must show as pills");
  assert.equal((await box(page, '#phone-readonly')).shown, true, 'the bar must say Read-only');
  await tapNote(page, 'Phone noodle machine');
  assert.equal(await page.$(`${selector} > .phone-note-tags`), null, 'a second tap must hide the pills');
  assert.equal((await box(page, '#phone-readonly')).shown, false, 'Read-only must go with the pills');
  const parent = await tapNote(page, 'Phone ramen experiments');
  await page.waitForFunction(target => document.querySelector(target)?.dataset.isCollapsed === 'false', {}, parent);
  assert.equal(await isEditing(page), false, 'expanding must not edit');
  await page.waitForSelector(`${parent} > .phone-note-tags .phone-tag-pill`);
  await tapNote(page, 'Phone ramen experiments');
  assert.equal(await page.evaluate(target => document.querySelector(target).dataset.isCollapsed, parent), 'false',
    'a second tap hides the pills and leaves the note expanded');
}

async function tagPillCase(page) {
  for (const [mode, expected] of [['replace', 'recipes'], ['narrow', 'phonetest recipes']]) {
    await page.evaluate((key, value) => localStorage.setItem(key, value), TAG_PILL_SWITCH, mode);
    await search(page, 'phonetest');
    const parent = await tapNote(page, 'Phone ramen experiments');
    await page.tap(`${parent} > .phone-note-tags .phone-tag-pill[data-tag="recipes"]`);
    await page.waitForFunction(async text => {
      const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
      return state.searchQuery === text && !state.isLoading;
    }, {}, expected);
    await waitQuiet(page);
  }
  await page.evaluate(key => localStorage.removeItem(key), TAG_PILL_SWITCH);
}

async function backCase(page) {
  await search(page, 'phonetest');
  const parent = await tapNote(page, 'Phone ramen experiments');
  await page.tap(`${parent} > .phone-note-tags .phone-tag-pill[data-tag="japanese"]`);
  await page.waitForFunction(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    return state.searchQuery === 'japanese' && !state.isLoading;
  });
  await waitQuiet(page);
  await page.goBack();
  await page.waitForFunction(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    return state.searchQuery === 'phonetest' && !state.isLoading;
  });
  await waitQuiet(page);
}

async function sheetCase(page) {
  await page.tap('#phone-menu-button');
  await page.waitForSelector('#phone-sheet', {visible: true});
  const labels = await page.$$eval('#phone-sheet [data-phone-choice]', elements => elements.map(element => element.textContent.trim()));
  for (const label of ['Normal', 'Created', 'Reverse', 'Untagged Notes', 'Lock', 'Sign Out']) {
    assert(labels.some(text => text.startsWith(label)), `the sheet must offer ${label}`);
  }
  await page.tap('#phone-sheet [data-phone-choice="sort:created"]');
  await page.waitForFunction(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    return state.activeTabSortMode === 'created' && !state.isLoading;
  });
  await waitQuiet(page);
  assert.equal((await box(page, '#phone-sheet')).shown, false, 'picking an option closes the sheet');
  await page.tap('#phone-menu-button');
  await page.waitForSelector('#phone-sheet', {visible: true});
  await page.tap('#phone-sheet [data-phone-choice="sort:normal"]');
  await page.waitForFunction(async () => {
    const {ModeContextInstance: state} = await import('/static/js/modules/mode-manager/mode-context.js');
    return state.activeTabSortMode === 'normal' && !state.isLoading;
  });
  await waitQuiet(page);
}

async function saveButtonState(page) {
  return page.$eval('#phone-capture-save', button => ({disabled: button.disabled, title: button.title}));
}

// Cancel and Save side by side at the lower right of the sheet, as in the mock, with the
// shared dialog row's markup (action-row.js): exact edges, no tolerance.
async function captureRowCase(page) {
  const row = await page.$eval('#phone-capture .dialog-actions', element => {
    const content = element.closest('.phone-capture-content');
    const contentBox = content.getBoundingClientRect();
    const contentStyle = getComputedStyle(content);
    const [cancel, save] = [...element.querySelectorAll('button')].map(button => button.getBoundingClientRect());
    return {
      innerRight: contentBox.right - parseFloat(contentStyle.paddingRight) - parseFloat(contentStyle.borderRightWidth),
      gap: parseFloat(getComputedStyle(element).columnGap),
      cancel: {left: cancel.left, right: cancel.right, top: cancel.top},
      save: {left: save.left, right: save.right, top: save.top},
      saveIsMain: element.querySelector('#phone-capture-save').classList.contains('primary-btn'),
      cancelIsSafe: element.querySelector('#phone-capture-cancel').hasAttribute('data-modal-safe-focus'),
    };
  });
  assert.equal(row.save.right, row.innerRight, 'Save ends at the sheet\'s right edge');
  assert.equal(row.cancel.top, row.save.top, 'Cancel and Save side by side');
  assert.equal(row.cancel.right + row.gap, row.save.left, 'Cancel just left of Save');
  assert.equal(row.saveIsMain, true, 'Save is the main action');
  assert.equal(row.cancelIsSafe, true, 'the row is the shared dialog row (Cancel is its safe focus)');
}

async function captureCase(page) {
  await search(page, '');
  for (const [text, typedTags, savedTags] of [['Phone captured thought', '', '@inbox'], ['Phone tagged thought', 'reading', 'reading']]) {
    await page.tap('#phone-capture-button');
    await page.waitForSelector('#phone-capture', {visible: true});
    assert.equal(await page.evaluate(() => document.activeElement.id), 'phone-capture-text', 'capture starts in its text box');
    const buttons = await page.$$eval('#phone-capture .dialog-actions button', elements => elements.map(element => element.textContent.trim()));
    assert.deepEqual(buttons, ['Cancel', 'Save'], 'Cancel, then Save at the lower right');
    await captureRowCase(page);
    assert.deepEqual(await saveButtonState(page), {disabled: true, title: 'Write the note first.'},
      'Save is dimmed, and says why, while the note is empty');
    await page.type('#phone-capture-text', text);
    assert.deepEqual(await saveButtonState(page), {disabled: false, title: ''}, 'Save is ready once the note has text');
    if (typedTags !== '') {
      await page.type('#phone-capture-tags', `${typedTags} `);
    }
    await page.tap('#phone-capture-save');
    await page.waitForFunction(() => document.querySelector('#phone-capture')?.getClientRects().length === 0);
    // The sheet closes at once; the saved note then appears at the top of the list.
    await page.waitForFunction(wanted => [...document.querySelectorAll('.note > .note-content')]
      .some(element => element.textContent.trim() === wanted), {}, text);
    await waitQuiet(page);
    const selector = await noteSelector(page, text);
    assert.equal(await page.$eval(selector, element => element.dataset.noteTags), savedTags, `"${text}" must be tagged ${savedTags}`);
  }
  // The reserved tag finds what was captured without tags, and only that.
  await search(page, '@inbox');
  const found = await page.$$eval('#notes-container .note > .note-content', elements => elements.map(element => element.textContent.trim()));
  assert.deepEqual(found, ['Phone captured thought'], 'searching @inbox finds the untagged capture');
  await search(page, '');
}

async function noMenuCase(page) {
  const selector = await noteSelector(page, 'Phone noodle machine');
  await page.$eval(`${selector} > .note-content`, element => {
    const rect = element.getBoundingClientRect();
    element.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: rect.left + 4, clientY: rect.top + 4}));
  });
  await settle(page);
  const hasMenu = await page.evaluate(() => [...document.querySelectorAll('.context-menu')].some(element => element.getClientRects().length > 0));
  assert.equal(hasMenu, false, 'a long press opens no menu on the phone');
}

// The phone layout comes from CSS alone, so the first paint, before any script runs, already
// hides the desktop's controls (a phone once showed them until the app had started).
async function firstPaintCase(browser, origin) {
  const bare = await browser.newPage();
  try {
    await bare.setViewport(PHONE);
    // No script runs: every script is refused, which the page's only scripts (no inline
    // ones) are. Not setJavaScriptEnabled, which Puppeteer has only for Chrome.
    await bare.setRequestInterception(true);
    bare.on('request', request => {
      if (new URL(request.url()).pathname.endsWith('.js')) void request.abort();
      else void request.continue();
    });
    await bare.goto(origin, {waitUntil: 'load'});
    for (const hidden of ['#tab-hover-zone', '.global-controls']) {
      assert.equal(await bare.$eval(hidden, element => element.getClientRects().length), 0,
        `${hidden} must be hidden from the first paint`);
    }
  } finally {
    await bare.close();
  }
}

// Lock and Sign Out log out (each vault has its own address, so the vault stays picked).
async function signOutCase(page) {
  for (const choice of ['lock', 'sign-out']) {
    const loggedOut = new Promise(resolve => {
      const watch = request => {
        if (request.url().endsWith('/auth/logout') && request.method() === 'POST') {
          page.off('request', watch);
          resolve(true);
        }
      };
      page.on('request', watch);
    });
    await page.tap('#phone-menu-button');
    await page.waitForSelector('#phone-sheet', {visible: true});
    // Logging out reloads the page.
    const reloaded = page.waitForNavigation({waitUntil: 'load'});
    await page.tap(`#phone-sheet [data-phone-choice="${choice}"]`);
    const sent = await Promise.race([loggedOut, new Promise(resolve => setTimeout(() => resolve(false), 5000))]);
    assert.equal(sent, true, `${choice} must log out`);
    await reloaded;
    await page.waitForSelector('[data-app-ready="true"]');
    await waitQuiet(page);
  }
}

export async function checkPhone(browser, page, origin) {
  await seedNotes(page);
  const phone = await browser.newPage();
  const failures = [];
  try {
    try {
      await firstPaintCase(browser, origin);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      failures.push(`first paint: ${error.message}`);
      console.log(`FAIL first paint: ${error.message}`);
    }
    await phone.setViewport(PHONE);
    await phone.goto(origin);
    await phone.waitForSelector('[data-app-ready="true"]');
    await waitQuiet(phone);
    const cases = [
      ['layout', layoutCase], ['search pills', searchPillsCase], ['tapping a note', tapCase],
      ['tag pills', tagPillCase], ['back', backCase], ['menu sheet', sheetCase], ['capture', captureCase],
      ['no long-press menu', noMenuCase],
      // Last: it reloads the page.
      ['lock and sign out', signOutCase],
    ];
    for (const [label, run] of cases) {
      try {
        await run(phone);
      } catch (error) {
        if (!(error instanceof assert.AssertionError)) throw error;
        failures.push(`${label}: ${error.message}`);
        console.log(`FAIL ${label}: ${error.message}`);
        for (let press = 0; press < ESCAPES_AFTER_A_FAILURE; press++) await phone.keyboard.press('Escape');
        await phone.reload();
        await phone.waitForSelector('[data-app-ready="true"]');
        await waitQuiet(phone);
      }
    }
  } finally {
    await phone.close();
  }
  if (failures.length > 0) throw new assert.AssertionError({message: failures.join('\n')});
}
