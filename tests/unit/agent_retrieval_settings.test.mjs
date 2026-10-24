import assert from 'node:assert/strict';
import test from 'node:test';

import {
    DEFAULT_OPENAI_AGENT_RETRIEVAL_SETTINGS,
    OPENAI_AGENT_RETRIEVAL_PREFERENCE_KEYS,
    readAgentRetrievalSettings,
    validateAgentRetrievalSettings,
} from '../../app/static/js/modules/ai-chat/agent-retrieval-settings.js';


test('one limit covers answers and tagging batches', () => {
    assert.deepEqual(DEFAULT_OPENAI_AGENT_RETRIEVAL_SETTINGS, {
        maxPageApproximateTokens: 500000,
    });
});


test('retired local settings do not affect OpenAI limits', () => {
    const values = new Map([
        ['pref.ai.retrieval.max_page_approximate_tokens', '7000'],
        [OPENAI_AGENT_RETRIEVAL_PREFERENCE_KEYS.maxPageApproximateTokens, '500000'],
        ['pref.ai.tagging.batch_tokens', '3000'],
        ['pref.ai.openai.tagging.batch_tokens', '12000'],
    ]);
    const getPreference = (key) => values.get(key) ?? null;
    assert.deepEqual(readAgentRetrievalSettings(getPreference, 'openai'), {
        maxPageApproximateTokens: 500000,
    });
});


test('legacy OpenAI default migrates to current default', () => {
    const getPreference = (key) => (
        key === OPENAI_AGENT_RETRIEVAL_PREFERENCE_KEYS.maxPageApproximateTokens
            ? '24000'
            : null
    );
    assert.deepEqual(
        readAgentRetrievalSettings(getPreference, 'openai'),
        DEFAULT_OPENAI_AGENT_RETRIEVAL_SETTINGS,
    );
});


test('validation rejects limits outside the provider range', () => {
    assert.throws(() => validateAgentRetrievalSettings({
        maxPageApproximateTokens: 24001,
    }, 'ollama'));
    assert.throws(() => validateAgentRetrievalSettings({
        maxPageApproximateTokens: 500001,
    }, 'openai'));
});
