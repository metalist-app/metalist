import assert from 'node:assert/strict';
import test from 'node:test';

import {
    modelChoiceValue, parseModelChoiceValue, validateModelGroups,
} from '../../app/static/js/modules/ai-chat/ai-model-names.js';

// The chat's model picker (ai-model-names.js): an option names a provider and one of its models.

test('a chat model choice names its provider and model, and reads back the same', () => {
    assert.equal(modelChoiceValue('openai', 'ft:gpt-5.6-luna:me::abc'), 'openai ft:gpt-5.6-luna:me::abc');
    assert.deepEqual(parseModelChoiceValue('anthropic claude-x'), { provider: 'anthropic', model: 'claude-x' });
    for (const bad of ['', 'openai', 'OpenAI gpt', 'openai gpt 5', 'openai -gpt']) {
        assert.throws(() => parseModelChoiceValue(bad), /Not a model choice/);
    }
});

test('the model choices are groups of well-formed models', () => {
    const payload = { groups: [{ provider: 'openai', label: 'OpenAI', models: ['gpt-5.6-luna'] }] };
    assert.deepEqual(validateModelGroups(payload), payload.groups);
    assert.throws(() => validateModelGroups({ groups: [] }), /at least one provider/);
    assert.throws(() => validateModelGroups({ groups: [{ provider: 'openai', label: '', models: [] }] }), /malformed/);
    assert.throws(() => validateModelGroups({ groups: [{ provider: 'openai', label: 'OpenAI', models: ['gpt 5'] }] }), /Not a model choice/);
});
