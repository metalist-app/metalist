import assert from 'node:assert/strict';

// How the command palette and the right-click menus look (docs/ui/command-palette.md and
// docs/ui/modals.md, rule 8; agreed 2026-11-09): the suggested keywords on a grey strip, the
// choices in the app's normal font at the menus' size with a hand over them, nothing red.
const THEMES = [
  {name: 'light', stripBackground: 'rgb(232, 234, 237)'},
  {name: 'dark', stripBackground: 'rgb(38, 45, 56)'},
];
const MENU_FONT_SIZE = '13px';
// A destructive command, so a list with no such row can't pass as having no red.
const DESTRUCTIVE_COMMAND = 'action.delete_notes_in_view';
const DELETE_NOTE_LABEL = 'Delete Note';

async function showOneNote(page) {
  await page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const note = await NotesAPI.createNote(null, '');
    await NotesAPI.saveNote(note.id, '<p>A note to right-click</p>', '');
  });
  await page.reload({waitUntil: 'load'});
  await page.waitForSelector('[data-app-ready="true"]');
  await page.waitForSelector('.note > .note-content', {visible: true});
}

async function setTheme(page, theme) {
  await page.evaluate(theme => {
    if (theme === null) document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
  }, theme);
}

async function readPalette(page) {
  return page.evaluate(destructiveCommand => {
    const rows = [...document.querySelectorAll('#command-palette-results .command-palette-row')];
    const style = element => getComputedStyle(element);
    const strip = document.getElementById('command-palette-suggestions');
    const label = rows[0].querySelector('.command-palette-row-label');
    return {
      keywordCount: strip.querySelectorAll('.command-palette-suggestion').length,
      stripBackground: style(strip).backgroundColor,
      bodyFont: style(document.body).fontFamily,
      labelFont: style(label).fontFamily,
      labelSize: style(label).fontSize,
      rowCursor: style(rows[0]).cursor,
      rowSelection: style(rows[0]).userSelect,
      labelColors: [...new Set(rows.map(row => style(row.querySelector('.command-palette-row-label')).color))],
      hasDestructiveRow: rows.some(row => row.dataset.endpointId === destructiveCommand),
    };
  }, DESTRUCTIVE_COMMAND);
}

async function checkPalette(page, theme) {
  await page.evaluate(async () => {
    const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
    await CommandPalette.open();
  });
  await page.waitForSelector('#command-palette-results .command-palette-row', {visible: true});
  const palette = await readPalette(page);
  await page.keyboard.press('Escape');
  await page.waitForSelector('#command-palette-results .command-palette-row', {hidden: true});
  const label = `the palette, ${theme.name} theme`;
  assert.ok(palette.keywordCount > 0, `${label}: no suggested keywords were shown`);
  assert.equal(palette.stripBackground, theme.stripBackground, `${label}: the keywords' strip`);
  assert.equal(palette.labelFont, palette.bodyFont, `${label}: a choice's font`);
  assert.equal(palette.labelSize, MENU_FONT_SIZE, `${label}: a choice's size`);
  assert.equal(palette.rowCursor, 'pointer', `${label}: the pointer over a choice`);
  assert.equal(palette.rowSelection, 'none', `${label}: a choice's text must not be selectable`);
  assert.ok(palette.hasDestructiveRow, `${label}: ${DESTRUCTIVE_COMMAND} was not listed`);
  assert.equal(palette.labelColors.length, 1, `${label}: the choices differ in colour: ${palette.labelColors}`);
}

async function checkNoteMenu(page, theme) {
  await page.click('.note > .note-content', {button: 'right'});
  await page.waitForSelector('.context-menu.is-visible .context-menu-item', {visible: true});
  const menu = await page.evaluate(deleteLabel => {
    const items = [...document.querySelectorAll('.context-menu.is-visible .context-menu-item')];
    const deleteItem = items.find(item => item.textContent.includes(deleteLabel));
    return {
      deleteColor: deleteItem === undefined ? null : getComputedStyle(deleteItem).color,
      firstColor: getComputedStyle(items[0]).color,
      size: getComputedStyle(items[0]).fontSize,
    };
  }, DELETE_NOTE_LABEL);
  await page.keyboard.press('Escape');
  await page.waitForSelector('.context-menu.is-visible', {hidden: true});
  const label = `the note menu, ${theme.name} theme`;
  assert.notEqual(menu.deleteColor, null, `${label}: ${DELETE_NOTE_LABEL} was not listed`);
  assert.equal(menu.deleteColor, menu.firstColor, `${label}: ${DELETE_NOTE_LABEL} must look like the other items`);
  assert.equal(menu.size, MENU_FONT_SIZE, `${label}: an item's size`);
}

export async function checkMenuLook(page) {
  await showOneNote(page);
  const initialTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
  try {
    for (const theme of THEMES) {
      await setTheme(page, theme.name);
      await checkPalette(page, theme);
      await checkNoteMenu(page, theme);
    }
  } finally {
    await setTheme(page, initialTheme);
  }
}
