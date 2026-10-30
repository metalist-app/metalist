export const DEFAULT_PASSWORD_LENGTH = 16;
export const DEFAULT_PASSWORD_CHARSET = `abcdefghijklmnopqrstuvwxyz
ABCDEFGHIJKLMNOPQRSTUVWXYZ
0123456789
@%+\\/\'!#$^?:,.(){}[]~`;
// Random values drawn per missing character, so rejected (biased) samples rarely need another round.
const RANDOM_SAMPLES_PER_CHARACTER = 2;
// Distinct values one Uint32Array sample can take (2**32).
const UINT32_VALUE_COUNT = 0x100000000;

function resolveRandomValuesFunction(fillRandomValues) {
    if (typeof fillRandomValues === 'function') {
        return fillRandomValues;
    }
    const cryptoObject = globalThis.crypto;
    if (!cryptoObject || typeof cryptoObject.getRandomValues !== 'function') {
        throw new Error('Secure random source unavailable');
    }
    return (buffer) => cryptoObject.getRandomValues(buffer);
}

export function normalizePasswordCharset(rawCharsetInput) {
    if (typeof rawCharsetInput !== 'string') {
        throw new Error('normalizePasswordCharset requires string input');
    }

    const withoutCarriageReturns = rawCharsetInput.replace(/\r/g, '');
    let normalized = '';
    for (const character of withoutCarriageReturns) {
        if (character === '\n') {
            continue;
        }
        normalized += character;
    }

    if (normalized.length === 0) {
        throw new Error('Character set must not be empty');
    }
    return Array.from(new Set(normalized)).join('');
}

// `count` indexes below `size`, each equally likely: samples past the largest multiple of
// `size` are dropped, so no index is favoured (no modulo bias).
export function pickRandomIndexes(count, size, fillRandomValues) {
    if (!Number.isInteger(count) || count <= 0) {
        throw new Error('count must be a positive integer');
    }
    if (!Number.isInteger(size) || size <= 0 || size > UINT32_VALUE_COUNT) {
        throw new Error('size must be a positive integer no larger than 2**32');
    }
    const randomValues = resolveRandomValuesFunction(fillRandomValues);
    const unbiasedUpperBound = Math.floor(UINT32_VALUE_COUNT / size) * size;
    const indexes = [];
    while (indexes.length < count) {
        const randomBuffer = new Uint32Array((count - indexes.length) * RANDOM_SAMPLES_PER_CHARACTER);
        randomValues(randomBuffer);
        for (const value of randomBuffer) {
            if (value >= unbiasedUpperBound) {
                continue;
            }
            indexes.push(value % size);
            if (indexes.length === count) {
                return indexes;
            }
        }
    }
    return indexes;
}

export function generateRandomPassword(length, charset, fillRandomValues) {
    if (!Number.isInteger(length) || length <= 0) {
        throw new Error('length must be a positive integer');
    }
    if (typeof charset !== 'string' || charset.length === 0) {
        throw new Error('charset must be a non-empty string');
    }

    const characters = Array.from(normalizePasswordCharset(charset));
    if (characters.length === 0) {
        throw new Error('charset must contain at least one character');
    }

    return pickRandomIndexes(length, characters.length, fillRandomValues).map((index) => characters[index]).join('');
}
