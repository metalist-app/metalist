import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
    readPasswordOperationResponse,
} from '../../app/static/js/modules/password-operation-response.js';

const MODAL_SOURCE_URL = new URL(
    '../../app/static/js/modules/modals/password-modal.js',
    import.meta.url,
);
const RANDOM_MODAL_SOURCE_URL = new URL(
    '../../app/static/js/modules/modals/random-password-modal.js',
    import.meta.url,
);
const MAIN_CSS_URL = new URL('../../app/static/css/main.css', import.meta.url);


test('create and change password forms show locally computed strength', () => {
    const source = readFileSync(MODAL_SOURCE_URL, 'utf8');

    assert.match(source, /evaluatePasswordStrength/);
    assert.match(source, /loadPasswordStrengthEstimator/);
    assert.match(source, /generateNewPasswordStrengthHTML\(\)/);
    assert.match(source, /newPasswordInput\.addEventListener\('input'/);
    assert.match(source, /this\.renderNewPasswordStrength\(newPasswordInput\.value\)/);

    const strengthMarkupUses = source.match(/\$\{this\.generateNewPasswordStrengthHTML\(\)\}/g) ?? [];
    assert.equal(strengthMarkupUses.length, 2);
});


test('create, change, and random password flows share one four-segment strength component', () => {
    const passwordModalSource = readFileSync(MODAL_SOURCE_URL, 'utf8');
    const randomModalSource = readFileSync(RANDOM_MODAL_SOURCE_URL, 'utf8');
    const css = readFileSync(MAIN_CSS_URL, 'utf8');

    assert.match(passwordModalSource, /class="password-strength"/);
    assert.match(randomModalSource, /class="password-strength"/);
    assert.match(css, /\.password-strength-meter\s*\{[\s\S]*grid-template-columns:\s*repeat\(4,/);
    assert.match(
        css,
        /\.password-strength\[data-score="4"\] \.password-strength-meter span:nth-child\(-n\+4\)/,
    );
    assert.doesNotMatch(css, /\.random-password-modal-content \.password-strength\s*\{/);
});


test('create and change password forms show live minimum-length progress', () => {
    const source = readFileSync(MODAL_SOURCE_URL, 'utf8');

    assert.match(source, /generateNewPasswordLengthHTML\(\)/);
    assert.match(source, /renderNewPasswordLength\(newPasswordInput\.value\)/);
    assert.match(source, /calculatePasswordLengthProgress\(password\)/);
    assert.match(source, /password-length-check/);
    assert.match(source, /Minimum length reached/);

    const lengthMarkupUses = source.match(/\$\{this\.generateNewPasswordLengthHTML\(\)\}/g) ?? [];
    assert.equal(lengthMarkupUses.length, 2);
});


test('password management exposes three explicit modal flows', () => {
    const source = readFileSync(MODAL_SOURCE_URL, 'utf8');

    assert.match(source, /export class AddPasswordModal/);
    assert.match(source, /export class ChangePasswordModal/);
    assert.match(source, /export class RemovePasswordModal/);
    assert.doesNotMatch(source, /id="remove-password-btn"/);
    assert.doesNotMatch(source, /id="change-password-btn"/);
});


test('create and change password forms begin with their fields instead of filler copy', () => {
    const source = readFileSync(MODAL_SOURCE_URL, 'utf8');

    assert.doesNotMatch(source, /Set a password to encrypt your notes/);
    assert.doesNotMatch(source, /Enter your current password and choose a new one/);
    assert.match(source, /<h3>Add Password<\/h3>\s*<form id="password-form">/);
    assert.match(source, /<h3>Change Password<\/h3>\s*<form id="password-form" autocomplete="off">/);
});


test('password forms block submission until client validation passes', () => {
    const source = readFileSync(MODAL_SOURCE_URL, 'utf8');

    assert.match(source, /minlength="\$\{PASSWORD_MIN_LENGTH\}"/);
    assert.match(source, /maxlength="\$\{PASSWORD_MAX_LENGTH\}"/);
    // The submit button starts disabled (action-row.js writes the attribute).
    assert.match(source, /disabled: true, attributes: \['data-password-submit'\]/);
    assert.match(source, /syncSubmitAvailability\(\)/);
    // The dimmed button says what is missing; a mismatch floats under Confirm.
    assert.match(source, /submitButton\.title = validation\.valid \? '' : validation\.error;/);
    assert.match(source, /setFieldMessage\(confirmField, confirmationMismatch\(formData\), 'error'\)/);

    const validationIndex = source.indexOf('const validation = this.validateFormData');
    const processingIndex = source.indexOf('this.showProcessingState()', validationIndex);
    assert.notEqual(validationIndex, -1);
    assert.notEqual(processingIndex, -1);
    assert.ok(validationIndex < processingIndex);
});


test('password operations replace non-JSON server failures with an HTTP error', async () => {
    const response = new Response('Internal Server Error', {
        status: 500,
        headers: { 'content-type': 'text/plain' },
    });

    await assert.rejects(
        readPasswordOperationResponse(response),
        /Password request failed with HTTP 500 and returned invalid JSON/,
    );
});


test('password operations preserve JSON API error details', async () => {
    const response = new Response(JSON.stringify({ detail: 'Password rejected' }), {
        status: 400,
        headers: { 'content-type': 'application/json' },
    });

    await assert.rejects(
        readPasswordOperationResponse(response),
        /Password rejected/,
    );
});
