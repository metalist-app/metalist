import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Both ways the workspace starts start phone mode too: opening the page already logged in
// (main.js) and logging in (auth.js). The phone layout once came only with the first, so a
// phone that had just logged in showed the desktop (2026-10-24).
for (const path of ['app/static/js/main.js', 'app/static/js/modules/auth.js']) {
    test(`${path} starts phone mode after the command palette`, () => {
        const source = readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');
        assert.match(source, /await CommandPalette\.init\(\);[\s\S]*?PhoneMode\.init\(\);[\s\S]*?AiChatPanel\.init\(/);
    });
}
