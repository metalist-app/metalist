// Clicks a text field and selects all its text, as a person's triple-click does,
// so the next key replaces it. Not page.click(selector, {clickCount: 3}): in
// Firefox Puppeteer's triple-click leaves the caret at the end with nothing
// selected, so Backspace took one character and the next text was typed onto the
// old (2026-10-27, docs/testing/harness.md).
export async function clickAndSelectAll(page, selector) {
  await page.click(selector);
  await page.$eval(selector, field => {
    if (!(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement)) {
      throw new Error(`clickAndSelectAll needs an input or textarea, got ${field.tagName}`);
    }
    field.select();
  });
}
