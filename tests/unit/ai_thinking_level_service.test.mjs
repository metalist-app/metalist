import assert from 'node:assert/strict';
import test from 'node:test';

import {
    AI_THINKING_LEVEL_OPTIONS,
    DEFAULT_AI_THINKING_LEVEL,
    isThinkingLevelAvailableForModel,
    normalizeThinkingLevelForModel,
    validateAiThinkingLevel,
} from '../../app/static/js/modules/ai-chat/ai-thinking-level-service.js';


test('AI thinking levels expose the product abstraction with low default', () => {
    assert.equal(DEFAULT_AI_THINKING_LEVEL, 'low');
    assert.deepEqual(
        AI_THINKING_LEVEL_OPTIONS.map((option) => option.value),
        ['high', 'medium', 'low', 'off'],
    );
    assert.deepEqual(
        AI_THINKING_LEVEL_OPTIONS.map((option) => option.label),
        ['High Thinking', 'Medium Thinking', 'Low Thinking', 'Thinking Off'],
    );
    for (const thinkingLevel of ['off', 'low', 'medium', 'high']) {
        assert.equal(validateAiThinkingLevel(thinkingLevel), thinkingLevel);
    }
    assert.throws(() => validateAiThinkingLevel('max'), /Unsupported AI thinking level/);
});


test('OpenAI models preserve the selected thinking level', () => {
    assert.equal(
        isThinkingLevelAvailableForModel({ model: 'gpt-5.6-sol', thinkingLevel: 'off' }),
        true,
    );
    assert.equal(
        normalizeThinkingLevelForModel({ model: 'gpt-5.6-sol', thinkingLevel: 'off' }),
        'off',
    );
    assert.equal(
        normalizeThinkingLevelForModel({ model: 'gpt-5.6-terra', thinkingLevel: 'off' }),
        'off',
    );
});
