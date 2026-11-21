// The line under Password Audit's controls (docs/ui/password-audit.md). It says what the audit
// counts as a password, the `@password` tag (the maintainer, 2026-11-18: the audit never said
// what it reads), and, with no password in the vault, how to give it one.

const ONE = 1;
// The groups counted in the line, in its order; a password kept after a replacement is not one.
const COUNTED_GROUPS = Object.freeze([['leaked', 'leaked'], ['reused', 'reused'], ['weak', 'weak'], ['old', 'old']]);
export const NO_PASSWORDS_TEXT = 'No passwords: tag a note @password to audit it.';

// result: null while the first check runs, else { passwordCount, summary, leakCheck }.
export function auditSummaryText(result) {
    if (result === null) return 'Checking…';
    if (!Number.isInteger(result.passwordCount) || result.passwordCount < 0) {
        throw new Error('The audit\'s result has no password count');
    }
    if (result.passwordCount === 0) return NO_PASSWORDS_TEXT;
    const counts = COUNTED_GROUPS.map(([group, word]) => {
        if (!Number.isInteger(result.summary[group])) throw new Error(`The audit's result has no count of ${group} passwords`);
        return `${result.summary[group]} ${word}`;
    });
    const passwords = result.passwordCount === ONE ? 'password' : 'passwords';
    let text = `${result.passwordCount} ${passwords} tagged @password: ${counts.join(', ')}`;
    if (result.leakCheck === 'unavailable') text += ' (leak check unavailable)';
    return text;
}
