import assert from 'node:assert/strict';
import test from 'node:test';

// Two quick clicks on the chat's $ (spend) or eye (diagnostics) button: the second
// click toggles back, even while the first click's save is still on its way
// (0.13.0 crashed with "Redundant state change: preferences" here).

function createStorage() {
    const values = new Map();
    return {
        getItem: (key) => (values.has(key) ? values.get(key) : null),
        setItem: (key, value) => values.set(key, String(value)),
        removeItem: (key) => values.delete(key),
    };
}

globalThis.sessionStorage = createStorage();
globalThis.localStorage = createStorage();
globalThis.window = {};
const { AiChatPanel } = await import('../../app/static/js/modules/ai-chat/ai-chat-panel-controller.js');
const controllerClass = Object.getPrototypeOf(AiChatPanel);

function fakePanel(field, saverName) {
    const saved = [];
    const panel = {
        [field]: false,
        synced: [],
        _syncSpendToggle() { this.synced.push(this[field]); },
        _syncOpenAiCostVisibility() {},
        _syncDiagnosticActivityToggle() { this.synced.push(this[field]); },
        _render() {},
        [saverName](value) {
            saved.push(value);
            // The save takes a while; the next click arrives before it finishes.
            return new Promise((resolve) => { setTimeout(resolve, 10); });
        },
    };
    return { panel, saved };
}

for (const [method, field, saver] of [
    ['_toggleSpend', '_showSpend', '_saveSpendVisible'],
    ['_toggleDiagnosticActivities', '_showDiagnosticActivities', '_saveDiagnosticsVisible'],
]) {
    test(`${method}: a second quick click toggles back instead of asking for the same value again`, async () => {
        const { panel, saved } = fakePanel(field, saver);
        const first = controllerClass[method].call(panel);
        const second = controllerClass[method].call(panel);
        await Promise.all([first, second]);
        assert.deepEqual(saved, [true, false]);
        assert.equal(panel[field], false);
        // The button showed each state at once, before its save finished.
        assert.deepEqual(panel.synced, [true, false]);
    });
}

// The estimated spend is a developer tool: where the server does not offer it
// (production), the $ never shows, whatever the saved choice.
for (const [offered, shown] of [['true', true], ['false', false]]) {
    test(`the $ shows only where the server offers the cost estimate (${offered})`, () => {
        const elements = {
            panel: { dataset: { showsCostEstimate: offered } },
            openAiCost: { hidden: true },
            spendToggle: { hidden: true },
        };
        const panel = {
            _elements: elements,
            _showSpend: true,
            _getSettings: () => ({ provider: 'openai' }),
            _showsCostEstimate: controllerClass._showsCostEstimate,
        };
        assert.equal(controllerClass._syncOpenAiCostVisibility.call(panel), shown);
        assert.equal(elements.spendToggle.hidden, !shown);
        assert.equal(elements.openAiCost.hidden, !shown);
    });
}
