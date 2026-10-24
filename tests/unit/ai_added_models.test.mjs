import assert from 'node:assert/strict';
import test from 'node:test';

import {
    addedModelNameProblem, modelChoiceValue, parseModelChoiceValue, validateModelGroups,
} from '../../app/static/js/modules/ai-chat/ai-model-names.js';

// Add a model in AI Agent Settings checks a name as the server does (app/services/ai_catalog.py).
const lists = { installedModels: ['gpt-5.6-sol', 'gpt-5.6-luna', 'gpt-5.7-nova'], addedModels: ['gpt-5.7-nova'] };

test('a well-formed new model name can be added', () => {
    assert.equal(addedModelNameProblem('gpt-5.8-terra', lists), '');
    assert.equal(addedModelNameProblem('ft:gpt-5.6-luna:me::abc', lists), '');
});

test('a name that cannot be a model, or is listed already, says why', () => {
    assert.match(addedModelNameProblem('', lists), /Type the model/);
    assert.match(addedModelNameProblem('gpt 5', lists), /not a model name/);
    assert.match(addedModelNameProblem('-gpt', lists), /not a model name/);
    assert.match(addedModelNameProblem('gpt-5.6-luna', lists), /already in the list/);
    assert.match(addedModelNameProblem('gpt-5.7-nova', lists), /already in the list/);
    const full = { installedModels: [], addedModels: Array.from({ length: 20 }, (_, index) => `m${index}`) };
    assert.match(addedModelNameProblem('one-more', full), /At most 20/);
});

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
