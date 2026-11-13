// One name for every problem report file, by the local date and time it was saved: a report from
// the red error or Report a Problem…, from the login page, or a bundle of kept ones from Export
// Problem Reports… (plural). Three ways had grown, two of them in UTC, so a 6:52 PM export said
// 02-52 (the maintainer, 2026-11-12). The report's id stays inside the file, where the server's
// log lines are matched by it; two saved in the same second are told apart by the browser's (1).

// Two digits for a month, day, hour, minute or second.
const TWO_DIGITS = 2;

function twoDigits(value) {
    return String(value).padStart(TWO_DIGITS, '0');
}

export function problemReportFileName({ isBundle, savedAt }) {
    if (typeof isBundle !== 'boolean') {
        throw new Error('problemReportFileName requires isBundle');
    }
    if (!(savedAt instanceof Date) || Number.isNaN(savedAt.getTime())) {
        throw new Error('problemReportFileName requires the time it was saved');
    }
    const date = `${savedAt.getFullYear()}-${twoDigits(savedAt.getMonth() + 1)}-${twoDigits(savedAt.getDate())}`;
    const time = `${twoDigits(savedAt.getHours())}-${twoDigits(savedAt.getMinutes())}-${twoDigits(savedAt.getSeconds())}`;
    const kind = isBundle ? 'reports' : 'report';
    return `metalist-problem-${kind}-${date} ${time}`;
}
