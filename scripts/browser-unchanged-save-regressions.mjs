import assert from 'node:assert/strict';

// A settings dialog's Save with nothing changed closes the dialog like any Save; the
// preferences store rejects a write that changes nothing, so it must write nothing.
// (AI Agent Settings is covered in browser-ai-settings-regressions.mjs.)
export async function checkUnchangedSettingsSaves(page) {
  for (const {open, modal, save} of [
    {open: 'openNoteLayoutAppearance', modal: '#note-layout-appearance-modal', save: '#note-layout-save-btn'},
    {open: 'openDictationSettings', modal: '#dictation-settings-modal', save: '#dictation-settings-modal [data-dictation-save]'},
  ]) {
    // The first Save stores the dialog's defaults; the second saves exactly those again.
    for (const round of ['first', 'unchanged']) {
      await page.evaluate(async method => {
        const {CommandPalette} = await import('/static/js/modules/command-palette/command-palette-controller.js');
        await CommandPalette[method]();
      }, open);
      await page.waitForSelector(save, {visible: true});
      await page.click(save);
      await page.waitForSelector(modal, {hidden: true});
      assert.equal(await page.$('#fatal-error-overlay'), null, `${open}, ${round} Save: must not raise a fatal error`);
    }
  }
  console.log('PASS settings dialogs: an unchanged Save closes quietly');
}
