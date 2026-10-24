// Model names in the chat's model picker (app/services/ai_catalog.py checks them the same way).

// A model name as providers write them.
const MODEL_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/-]*$/;

// The chat's model picker lists every provider's models (POST /ai/model-choices); an
// option names both, since picking a model picks its provider. A provider id is
// lowercase letters and a model name has no space, so a space separates them.
const PROVIDER_ID_PATTERN = /^[a-z]+$/;
const MODEL_CHOICE_SEPARATOR = ' ';

export function modelChoiceValue(provider, model) {
    if (!PROVIDER_ID_PATTERN.test(provider) || !MODEL_NAME_PATTERN.test(model)) {
        throw new Error(`Not a model choice: ${provider} ${model}`);
    }
    return `${provider}${MODEL_CHOICE_SEPARATOR}${model}`;
}

export function parseModelChoiceValue(value) {
    if (typeof value !== 'string') throw new Error('A model choice must be a string');
    const separatorIndex = value.indexOf(MODEL_CHOICE_SEPARATOR);
    if (separatorIndex === -1) throw new Error(`Not a model choice: ${value}`);
    const provider = value.slice(0, separatorIndex);
    const model = value.slice(separatorIndex + MODEL_CHOICE_SEPARATOR.length);
    // Round-tripping checks both halves.
    if (modelChoiceValue(provider, model) !== value) throw new Error(`Not a model choice: ${value}`);
    return { provider, model };
}

export function validateModelGroups(payload) {
    if (!payload || typeof payload !== 'object' || !Array.isArray(payload.groups) || payload.groups.length === 0) {
        throw new Error('AI model choices must list at least one provider');
    }
    return payload.groups.map((group) => {
        if (!group || typeof group.label !== 'string' || group.label === '' || !Array.isArray(group.models)) {
            throw new Error('AI model choice group is malformed');
        }
        for (const model of group.models) modelChoiceValue(group.provider, model);
        return { provider: group.provider, label: group.label, models: [...group.models] };
    });
}
