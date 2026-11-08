import assert from 'node:assert/strict';
import test from 'node:test';

import {
    AGENT_RETRIEVAL_PREFERENCE_KEYS,
    DEFAULT_AGENT_RETRIEVAL_SETTINGS,
    readAgentRetrievalSettings,
    validateAgentRetrievalSettings,
} from '../../app/static/js/modules/ai-chat/agent-retrieval-settings.js';

const OLD_TOKEN_KEY = 'pref.ai.openai.retrieval.max_page_approximate_tokens';

function preferences(values) {
    const stored = new Map(Object.entries(values));
    return (key) => stored.get(key) ?? null;
}


test('one percentage of the model\'s window covers answers and tagging batches', () => {
    assert.deepEqual(DEFAULT_AGENT_RETRIEVAL_SETTINGS, { windowPercent: 50 });
});


test('a saved percentage is read back', () => {
    assert.deepEqual(readAgentRetrievalSettings(preferences({
        [AGENT_RETRIEVAL_PREFERENCE_KEYS.windowPercent]: '30',
        [OLD_TOKEN_KEY]: '500000',
    }), 'openai'), { windowPercent: 30 });
});


test('a value saved as tokens reads as its share of OpenAI\'s window', () => {
    assert.deepEqual(readAgentRetrievalSettings(preferences({ [OLD_TOKEN_KEY]: '500000' }), 'openai'), { windowPercent: 48 });
});


test('the legacy default and retired settings read as the default', () => {
    assert.deepEqual(readAgentRetrievalSettings(preferences({ [OLD_TOKEN_KEY]: '24000' }), 'openai'), DEFAULT_AGENT_RETRIEVAL_SETTINGS);
    assert.deepEqual(readAgentRetrievalSettings(preferences({
        'pref.ai.retrieval.max_page_approximate_tokens': '7000',
        'pref.ai.tagging.batch_tokens': '3000',
    }), 'anthropic'), DEFAULT_AGENT_RETRIEVAL_SETTINGS);
});


test('validation keeps the percentage from 1 to 100', () => {
    assert.deepEqual(validateAgentRetrievalSettings({ windowPercent: 1 }, 'openai'), { windowPercent: 1 });
    assert.deepEqual(validateAgentRetrievalSettings({ windowPercent: 100 }, 'gemini'), { windowPercent: 100 });
    for (const windowPercent of [0, 101, 1.5]) {
        assert.throws(() => validateAgentRetrievalSettings({ windowPercent }, 'openai'));
    }
    assert.throws(() => validateAgentRetrievalSettings({ windowPercent: 50 }, 'ollama'));
});
