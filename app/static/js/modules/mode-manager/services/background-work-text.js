// How a piece of the server's background work reads (background-work-cards.js, the import's bar).

const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const TWO_DIGITS = 2;

// 0:07, 12:30, 1:05:00.
function clockText(seconds) {
    const whole = Math.round(seconds);
    const minutes = Math.floor(whole / SECONDS_PER_MINUTE);
    const secondsText = String(whole % SECONDS_PER_MINUTE).padStart(TWO_DIGITS, '0');
    if (minutes < MINUTES_PER_HOUR) return `${minutes}:${secondsText}`;
    const minutesText = String(minutes % MINUTES_PER_HOUR).padStart(TWO_DIGITS, '0');
    return `${Math.floor(minutes / MINUTES_PER_HOUR)}:${minutesText}:${secondsText}`;
}

/**
 * A piece of work's parts, for its card (the maintainer, 2026-11-03): what runs and how far it
 * got ("Reading document text: 3 of 7"), then above its bar how long it has run ("0:12", at the
 * left) and, once some is done, about how long is left at that pace ("0:16", at the right; ""
 * until then), with no words around the times.
 */
export function workProgressParts(entry) {
    const spent = clockText(entry.elapsedSeconds);
    if (entry.total === 0) return { label: `${entry.label}…`, spent, left: '' };
    const label = `${entry.label}: ${entry.done} of ${entry.total}`;
    if (entry.done === 0 || entry.done >= entry.total) return { label, spent, left: '' };
    return { label, spent, left: clockText((entry.elapsedSeconds / entry.done) * (entry.total - entry.done)) };
}

/**
 * What a piece of work says in one line, under the import's bar: its parts as words (the
 * maintainer, 2026-11-02: elapsed time and an estimate, for very large folders):
 * "Reading document text: 3 of 7 · 0:12 so far, about 0:16 left".
 */
export function workProgressText(entry) {
    const parts = workProgressParts(entry);
    const elapsed = `${parts.spent} so far`;
    if (parts.left === '') return `${parts.label} · ${elapsed}`;
    return `${parts.label} · ${elapsed}, about ${parts.left} left`;
}
