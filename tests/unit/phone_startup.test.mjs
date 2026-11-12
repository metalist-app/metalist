import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Both ways the workspace starts start phone mode too: opening the page already logged in
// (main.js) and logging in (auth.js). The phone layout once came only with the first, so a
// phone that had just logged in showed the desktop (2026-10-24). Both now start it through
// app-start.js (2026-11-12), so its steps are written once.
test('the workspace starts phone mode after the command palette', () => {
    const source = readFileSync(new URL('../../app/static/js/modules/app-start.js', import.meta.url), 'utf8');
    assert.match(source, /await CommandPalette\.init\(\);[\s\S]*?PhoneMode\.init\(\);[\s\S]*?AiChatPanel\.init\(/);
});

for (const path of ['app/static/js/main.js', 'app/static/js/modules/auth.js']) {
    test(`${path} starts the workspace through app-start.js`, () => {
        const source = readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');
        assert.match(source, /await app\.startWorkspace\(\{[\s\S]*?await app\.afterWorkspaceReady\(/);
    });
}
