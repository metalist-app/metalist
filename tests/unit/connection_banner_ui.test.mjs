import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


const ERROR_HANDLER_URL = new URL(
    '../../app/static/js/modules/error-handler.js',
    import.meta.url,
);
const MAIN_CSS_URL = new URL('../../app/static/css/main.css', import.meta.url);


test('disconnect uses a calm dedicated lasting card', async () => {
    const [handlerSource, cssSource] = await Promise.all([
        readFile(ERROR_HANDLER_URL, 'utf8'),
        readFile(MAIN_CSS_URL, 'utf8'),
    ]);

    assert.match(handlerSource, /type: 'connection',[\s\S]*?isLasting: true,/);
    assert.match(
        cssSource,
        /\.floating-message-connection\s*\{[\s\S]*?background-color:\s*#fff8e6;[\s\S]*?color:\s*#5b4820;/,
    );
});
