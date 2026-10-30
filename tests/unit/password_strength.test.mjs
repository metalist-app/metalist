import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

import {
    describePasswordScore,
    evaluatePasswordStrength,
} from '../../app/static/js/modules/password-strength.js';

const require = createRequire(import.meta.url);
const vendoredZxcvbn = require('../../app/static/js/vendor/zxcvbn-4.4.2.js');


test('evaluatePasswordStrength returns only the score interpretation', () => {
    let estimatorPassword = null;
    let estimatorUserInputs = null;
    const estimator = (password, userInputs) => {
        estimatorPassword = password;
        estimatorUserInputs = userInputs;
        return {
            password,
            score: 3,
            guesses: 100000000,
        };
    };

    // Vault passwords need score 4 (docs/security/README.md, raised 2026-10-29).
    assert.deepEqual(evaluatePasswordStrength('private candidate', estimator), {
        score: 3,
        label: 'Strong',
        meetsScoreThreshold: false,
    });
    assert.equal(estimatorPassword, 'private candidate');
    assert.deepEqual(estimatorUserInputs, ['metalist']);
});


test('score descriptions cover every zxcvbn score', () => {
    assert.deepEqual(describePasswordScore(0), { label: 'Very weak', meetsScoreThreshold: false });
    assert.deepEqual(describePasswordScore(1), { label: 'Weak', meetsScoreThreshold: false });
    assert.deepEqual(describePasswordScore(2), { label: 'Fair', meetsScoreThreshold: false });
    assert.deepEqual(describePasswordScore(3), { label: 'Strong', meetsScoreThreshold: false });
    assert.deepEqual(describePasswordScore(4), { label: 'Very strong', meetsScoreThreshold: true });
});


test('evaluatePasswordStrength rejects malformed estimator output', () => {
    assert.throws(
        () => evaluatePasswordStrength('private candidate', () => ({ score: 5 })),
        /zxcvbn score must be an integer from 0 through 4/,
    );
});


test('vendored browser estimator produces real zxcvbn scores', () => {
    assert.equal(evaluatePasswordStrength('password1234', vendoredZxcvbn).score, 1);
    assert.equal(evaluatePasswordStrength('aQ7!mZ2#vL9@xR4', vendoredZxcvbn).score, 4);
});
