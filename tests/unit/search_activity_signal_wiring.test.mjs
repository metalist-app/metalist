import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const KEYBOARD_EVENTS_URL = new URL(
    '../../app/static/js/modules/mode-manager/events/keyboard-events.js',
    import.meta.url,
);

test('deliberate tab clicks record the selected tab search while programmatic switches stay neutral', async () => {
    const source = await readFile(KEYBOARD_EVENTS_URL, 'utf8');
    const clickHandlerStart = source.indexOf("item.addEventListener('click'");
    const duplicateHandlerStart = source.indexOf(
        "searchContextsList.querySelectorAll('.duplicate-context')",
        clickHandlerStart,
    );
    assert.notEqual(clickHandlerStart, -1);
    assert.notEqual(duplicateHandlerStart, -1);

    // A click and a number key choose a context the same way (chooseSearchContext, 2026-11-21).
    assert.match(source.slice(clickHandlerStart, duplicateHandlerStart), /await chooseSearchContext\(tabId\)/);
    const chooseStart = source.indexOf('async function chooseSearchContext');
    assert.notEqual(chooseStart, -1);
    const clickHandlerSource = source.slice(chooseStart, source.indexOf('function handleSearchContextDigit', chooseStart));
    assert.match(clickHandlerSource, /recordTabSearchSelection/);
    const recordIndex = clickHandlerSource.indexOf('recordTabSearchSelection');
    const commandGateIndex = clickHandlerSource.indexOf("CommandGate.run('tab.select'");
    assert.ok(recordIndex < commandGateIndex, 'tab click must be credited before navigation can be dropped');

    const switchFunctionStart = source.indexOf('export async function switchToTabContext');
    const createTabFunctionStart = source.indexOf(
        'function snapshotActiveTabScrollState',
        switchFunctionStart,
    );
    assert.notEqual(switchFunctionStart, -1);
    assert.notEqual(createTabFunctionStart, -1);
    const switchFunctionSource = source.slice(switchFunctionStart, createTabFunctionStart);
    assert.doesNotMatch(switchFunctionSource, /recordTabSearchSelection/);
});
