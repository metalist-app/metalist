// Which zxcvbn scores the Password Audit counts as weak (docs/ui/password-audit.md): below 3, the
// usual line for site passwords (zxcvbn's "safely unguessable" starts at 3), or below 4, the vault's
// own line. As WEAK_THRESHOLDS in app/usecases/password_audit.py.
export const WEAK_BELOW_USUAL = 3;
export const WEAK_BELOW_STRICT = 4;
export const WEAK_THRESHOLDS = Object.freeze([WEAK_BELOW_USUAL, WEAK_BELOW_STRICT]);
