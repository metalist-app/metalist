import assert from 'node:assert/strict';

// Work the server does beside the user's is shown as it goes (the maintainer, 2026-11-02):
// reading PDFs' text shows a floating card "Reading document text: 3 of 7" over a bar, gone when
// done. The reading runs in a process of its own, so the server answers at once meanwhile
// (a 4 KB image had waited 10 to 15 seconds behind 15 MB of PDFs).

const PDF_COUNT = 6;
const PAGES_PER_PDF = 1500;
const CARD = '#floating-work .floating-message-work';
const CARD_TIMEOUT_MS = 30000;
// The server answers a request in this long while PDFs are read (it took seconds before).
const QUICK_ANSWER_MS = 1500;
// The work card's width, wherever its text would end (main.css .floating-work).
const WORK_CARD_WIDTH_PX = 420;
// A window the folders show in, beside the notes and the chat's least.
const FOLDERS_WINDOW_WIDTH = 1600;

// A PDF whose pages each hold a line (Helvetica), with a correct cross-reference table.
function pdf(pageCount, word) {
  const fontNumber = 3;
  const firstPageNumber = 4;
  const objects = new Map([[1, '<< /Type /Catalog /Pages 2 0 R >>'], [fontNumber, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']]);
  const kids = [];
  for (let index = 0; index < pageCount; index += 1) {
    const pageNumber = firstPageNumber + index * 2;
    const stream = `BT /F1 12 Tf 20 700 Td (${word} page ${index} of the benefits guide) Tj ET`;
    objects.set(pageNumber, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 ${fontNumber} 0 R >> >> /Contents ${pageNumber + 1} 0 R >>`);
    objects.set(pageNumber + 1, `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
    kids.push(`${pageNumber} 0 R`);
  }
  objects.set(2, `<< /Type /Pages /Kids [${kids.join(' ')}] /Count ${pageCount} >>`);
  let out = '%PDF-1.4\n';
  const offsets = new Map();
  for (const number of [...objects.keys()].sort((a, b) => a - b)) {
    offsets.set(number, out.length);
    out += `${number} 0 obj\n${objects.get(number)}\nendobj\n`;
  }
  const xrefAt = out.length;
  const size = Math.max(...objects.keys()) + 1;
  out += `xref\n0 ${size}\n0000000000 65535 f \n`;
  for (let number = 1; number < size; number += 1) out += `${String(offsets.get(number)).padStart(10, '0')} 00000 n \n`;
  out += `trailer\n<< /Size ${size} /Root 1 0 R >>\nstartxref\n${xrefAt}\n%%EOF\n`;
  return out;
}

export async function checkBackgroundWork(page) {
  const pdfs = Array.from({length: PDF_COUNT}, (_, index) => pdf(PAGES_PER_PDF, `guide${index}`));
  // The PDFs stay as files no note shows, in the suite's own data, deleted with it.
  await page.evaluate(async texts => {
    const {FilesAPI} = await import('/static/js/modules/api-client.js');
    const {checkBackgroundWork} = await import('/static/js/modules/mode-manager/services/background-work-cards.js');
    const ids = [];
    for (const [index, text] of texts.entries()) {
      ids.push((await FilesAPI.uploadFile(new File([text], `guide${index}.pdf`, {type: 'application/pdf'}))).file_id);
    }
    void checkBackgroundWork();
    return ids;
  }, pdfs);
  await page.waitForSelector(CARD, {visible: true, timeout: CARD_TIMEOUT_MS});
  // The line, then above the bar the time spent at the left and the time left at the right,
  // without words around the times (2026-11-03).
  const shown = await page.$eval(CARD, card => {
    const box = selector => card.querySelector(selector).getBoundingClientRect();
    const [spent, left, bar] = [box('.floating-message-work-spent'), box('.floating-message-work-left'), box('.floating-message-progress')];
    return {
      text: card.querySelector('.floating-message-text').textContent,
      spent: card.querySelector('.floating-message-work-spent').textContent,
      left: card.querySelector('.floating-message-work-left').textContent,
      isSpentAtLeftAboveBar: Math.round(spent.left) === Math.round(bar.left) && spent.bottom <= bar.top,
      isLeftAtRightAboveBar: left.width === 0 || (Math.round(left.right) === Math.round(bar.right) && left.bottom <= bar.top),
      width: Math.round(card.getBoundingClientRect().width),
    };
  });
  assert.match(shown.text, new RegExp(`^Reading document text: \\d+ of ${PDF_COUNT}$`), 'the card says what runs and how far it got');
  assert.match(shown.spent, /^\d+:\d\d$/, 'the time spent, with no words');
  assert.match(shown.left, /^(~\d+:\d\d)?$/, 'the time left after ~, with no words (none before an estimate)');
  assert.equal(shown.isSpentAtLeftAboveBar, true, 'the time spent is above the bar at its left');
  assert.equal(shown.isLeftAtRightAboveBar, true, 'the time left is above the bar at its right');
  // A fixed width: sized to its text, it grew and shrank as the numbers changed (2026-11-03).
  assert.equal(shown.width, WORK_CARD_WIDTH_PX, 'the card is its fixed width, whatever its text');
  // In the lower left, above the folders' pull tab: at the top right it covered the search bar
  // and the menu (the maintainer, 2026-11-02). It stays put whether the folders show or not
  // (2026-11-03).
  const placeCard = () => page.evaluate(card => {
    const box = selector => document.querySelector(selector).getBoundingClientRect();
    const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    const cardBox = box(card);
    return {
      left: cardBox.left, bottom: cardBox.bottom,
      overlapsSearch: overlaps(cardBox, box('.controls')), overlapsMenu: overlaps(cardBox, box('#menu-button')),
      overlapsFoldersTab: overlaps(cardBox, box('#virtual-folders-button')),
      isLowerLeft: cardBox.bottom > window.innerHeight * 0.75 && cardBox.left < window.innerWidth / 2,
    };
  }, CARD);
  const toggleFolders = async () => {
    const wasOn = await page.evaluate(() => document.body.classList.contains('virtual-folders-on'));
    await page.click('#virtual-folders-button');
    await page.waitForFunction(on => document.body.classList.contains('virtual-folders-on') === on, {}, !wasOn);
  };
  // Wide enough for the folders to show (they hide at 900px and below).
  const smokeWindow = page.viewport();
  await page.setViewport({...smokeWindow, width: FOLDERS_WINDOW_WIDTH});
  const place = await placeCard();
  const {left, bottom, ...clearance} = place;
  assert.deepEqual(clearance, {overlapsSearch: false, overlapsMenu: false, overlapsFoldersTab: false, isLowerLeft: true},
    'the card sits in the lower left, clear of the search bar, the menu and the folders tab');
  await toggleFolders();
  assert.deepEqual(await placeCard(), place, 'showing or hiding the folders leaves the card where it is');
  await toggleFolders();
  await page.setViewport(smokeWindow);
  const answerMs = await page.evaluate(async () => {
    const {NotesAPI} = await import('/static/js/modules/api-client.js');
    const started = performance.now();
    await NotesAPI.fetchBackgroundWork();
    return performance.now() - started;
  });
  assert.ok(answerMs < QUICK_ANSWER_MS, `the server answers at once while PDFs are read (${Math.round(answerMs)} ms)`);
  await page.waitForFunction(card => document.querySelector(card) === null, {timeout: CARD_TIMEOUT_MS * PDF_COUNT}, CARD);
}
