import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { waitForAppQuiet } from './browser-app-idle.mjs';

// Bringing in the old MetaList's notes (docs/ui/legacy-import.md; the maintainer, 2026-11-04):
// a namespace with no notes and no password, whose data folder holds the old MetaList's file,
// offers them once it opens. A wrong password says so under its field; declining is remembered
// and the palette's command stays; bringing them in restarts the server, the page reloads into
// the login screen, and the old password opens the notes. The server and its data folder are
// the suite's own (browser-smoke.mjs); the old file is the fixture the old MetaList's own code
// encrypted (tests/fixtures/legacy-export).

const REQUESTS_QUIET_MS = 300;
const RESTART_TIMEOUT_MS = 60_000;
const DIALOG = '#legacy-import-modal .modal-content';
const OLD_PASSWORD = '#legacy-import-old-password';
const SUBMIT = '#legacy-import-submit';
const COMMAND_LABEL = 'Bring In Notes from Old MetaList…';

function writeOldMetaList(python, directory) {
    const script = [
        'import sys',
        'from pathlib import Path',
        'sys.path.insert(0, ".")',
        'from tests.unit.legacy_database_fixture import encrypted_bundle, write_legacy_database, ENCRYPTED_BUNDLE_PASSWORD',
        'write_legacy_database(Path(sys.argv[1]) / "metalist.db", encrypted_bundle())',
        'print(ENCRYPTED_BUNDLE_PASSWORD)',
    ].join('\n');
    const written = spawnSync(python, ['-c', script, directory], { encoding: 'utf-8' });
    assert.equal(written.status, 0, written.stderr);
    return written.stdout.trim();
}

async function reloadApp(page) {
    await page.reload();
    await page.waitForSelector('[data-app-ready="true"]');
    await waitForAppQuiet(page, REQUESTS_QUIET_MS);
}

async function dialogIsOpen(page) {
    return page.$eval('body', (body, selector) => {
        const dialog = body.querySelector(selector);
        return dialog !== null && dialog.offsetParent !== null;
    }, DIALOG);
}

async function commandIsOffered(page) {
    return page.evaluate(async (label) => {
        const { CommandPalette } = await import('/static/js/modules/command-palette/command-palette-controller.js');
        return CommandPalette._availableEndpoints().some((endpoint) => endpoint.label === label);
    }, COMMAND_LABEL);
}

export async function checkLegacyImport(page, { python, directory }) {
    const password = writeOldMetaList(python, directory);
    await reloadApp(page);

    // Offered once it opens, its field ready to type in.
    assert.equal(await dialogIsOpen(page), true);
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'legacy-import-old-password');
    assert.equal(await commandIsOffered(page), true);

    // A wrong password says so under its field, and the dialog stays.
    await page.type(OLD_PASSWORD, 'not-it');
    await page.click(SUBMIT);
    await page.waitForSelector('#legacy-import-old-password-message');
    assert.equal(await page.$eval('#legacy-import-old-password-message', (message) => message.textContent), 'Incorrect password');
    assert.equal(await dialogIsOpen(page), true);

    // Not Now is remembered: no dialog on the next start, the command still there.
    await page.click('#legacy-import-cancel');
    await waitForAppQuiet(page, REQUESTS_QUIET_MS);
    await reloadApp(page);
    assert.equal(await dialogIsOpen(page), false);
    assert.equal(await commandIsOffered(page), true);

    // From the palette's command: the old password brings them in, the server restarts and
    // the page reloads into the login screen, where the same password opens them.
    await page.evaluate(async () => {
        const { CommandPalette } = await import('/static/js/modules/command-palette/command-palette-controller.js');
        await CommandPalette.openLegacyImport();
    });
    await page.waitForSelector(OLD_PASSWORD, { visible: true });
    await page.type(OLD_PASSWORD, password);
    await Promise.all([
        page.waitForNavigation({ timeout: RESTART_TIMEOUT_MS }),
        page.click(SUBMIT),
    ]);
    await page.waitForSelector('#login-panel[data-revealed="true"] #login-password', { visible: true, timeout: RESTART_TIMEOUT_MS });
    await page.type('#login-password', password);
    await page.click('#login-form button[type="submit"]');
    await page.waitForSelector('[data-app-ready="true"]', { timeout: RESTART_TIMEOUT_MS });
    await waitForAppQuiet(page, REQUESTS_QUIET_MS);
    const roots = await page.$$eval('#notes-container > .note > .note-content', (contents) => contents.map((content) => content.textContent.trim()));
    assert.deepEqual(roots, ['Bank login', 'Groceries']);
    // Now it has notes: nothing is offered.
    assert.equal(await dialogIsOpen(page), false);
    assert.equal(await commandIsOffered(page), false);
}
