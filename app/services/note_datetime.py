"""The `@datetime` tag: which date a note belongs to (docs/design/tag-properties.md, Dates).

`@datetime=2026-10-24` or `@datetime=2026-10-24T08:30`, the user's local time. A date
alone means that whole day. The Created date range uses it in place of the root's
creation time (root_date_filter.py); sorting by Created keeps when the note was typed.
The tag bar refuses a value that is not one of these forms (tag-syntax-service.js), so a
token that is not one dates nothing.
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime

from app.services.quoted_values import VALUE_QUOTE, split_tokens

DATETIME_TAG = "@datetime"
DATETIME_TAG_PREFIX = DATETIME_TAG + "="
# A whole token on the tag line: @datetime=<value>.
_DATETIME_TOKEN_RE = re.compile(r"(?<!\S)@datetime=(?P<value>\S*)(?!\S)", re.IGNORECASE)
_DATETIME_VALUE_RE = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?:T(?P<hour>\d{2}):(?P<minute>\d{2}))?",
    re.IGNORECASE,
)
# How the suggestion writes now: the stored form, to the minute.
_SUGGESTED_FORMAT = "%Y-%m-%dT%H:%M"
_TWO_DIGITS = "{:02d}"
_FIRST_MONTH = 1
_MONTHS_IN_YEAR = 12
_FIRST_DAY = 1
# monthrange() returns (weekday of the first day, number of days).
_DAYS_IN_MONTH = 1
_LAST_HOUR = 23
_LAST_MINUTE = 59
_NOON_HOUR = 12

# A date in a note's text, wherever it is: year first (2026-10-29, 2026.10.29, 2026/10/29)
# or with the month's name (Jan 3rd, January 3, 2026, 3 Jan, the 3rd of January). A date
# of numbers only that is not year first (10/29/2026, 3/1) is ambiguous and not read.
_YEAR_FIRST_DATE_RE = re.compile(
    r"(?<![\d.\-/])(?P<year>\d{4})(?P<separator>[-./])(?P<month>\d{1,2})(?P=separator)(?P<day>\d{1,2})(?![\d.\-/])"
)
_MONTH_NAME = (
    r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_DAY_NUMBER = r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
_OPTIONAL_YEAR = r"(?:,?\s+(?P<year>\d{4})(?!\d))?"
# The day is not the hour of a time (Jan 3:30); a colon after it is fine (Oct 30th: …).
_MONTH_DAY_RE = re.compile(rf"(?<!\w){_MONTH_NAME}\s+{_DAY_NUMBER}(?!\w|:\d){_OPTIONAL_YEAR}", re.IGNORECASE)
_DAY_MONTH_RE = re.compile(rf"(?<!\w){_DAY_NUMBER}\s+(?:of\s+)?{_MONTH_NAME}(?!\w){_OPTIONAL_YEAR}", re.IGNORECASE)
# A month is named by its first three letters.
_MONTH_KEY_LENGTH = 3
_MONTH_NUMBERS = {
    name: number for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=_FIRST_MONTH,
    )
}
# "may" is a common word; only "May" names the month.
_AMBIGUOUS_MONTH_WORD = "may"
# A time in the text, wherever it is: 4:30pm, 4 pm, 4:30 p.m., or 24-hour 16:30.
_TWELVE_HOUR_TIME_RE = re.compile(
    r"(?<![\d:.])(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>[ap])\.?m\b\.?", re.IGNORECASE,
)
# A 24-hour time has no am or pm after it (4:30pm is the 12-hour pattern's).
_TWENTY_FOUR_HOUR_TIME_RE = re.compile(
    r"(?<![\d:.])(?P<hour>\d{1,2}):(?P<minute>\d{2})(?![\d:])(?!\s*[ap]\.?m\b)", re.IGNORECASE,
)
_AFTERNOON = "p"
_NO_MINUTES = "00"


@dataclass(frozen=True)
class _FoundDay:
    start: int
    end: int
    # None when the text does not say the year.
    year: int | None
    month: int
    day: int


def _is_real_day(year: int, month: int, day: int) -> bool:
    return _FIRST_MONTH <= month <= _MONTHS_IN_YEAR and _FIRST_DAY <= day <= monthrange(year, month)[_DAYS_IN_MONTH]


def note_date_of_tags(tags: str) -> date | None:
    """The day a note's own first `@datetime` names, or None when it has none that is a
    real date."""
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")
    token_value = _datetime_token_value(tags)
    if token_value is None:
        return None
    value = _DATETIME_VALUE_RE.fullmatch(token_value)
    if value is None:
        return None
    year, month, day = int(value["year"]), int(value["month"]), int(value["day"])
    if not _is_real_day(year, month, day):
        return None
    if value["hour"] is not None and (int(value["hour"]) > _LAST_HOUR or int(value["minute"]) > _LAST_MINUTE):
        return None
    return date(year, month, day)


def _datetime_token_value(tags: str) -> str | None:
    """The value of the first @datetime token, not one inside a quoted value
    (title="moved @datetime=2026-01-01"), or None."""
    if VALUE_QUOTE not in tags:
        match = _DATETIME_TOKEN_RE.search(tags)
        if match is None:
            return None
        return match["value"]
    for token in split_tokens(tags):
        match = _DATETIME_TOKEN_RE.fullmatch(token)
        if match is not None:
            return match["value"]
    return None


def is_datetime_tag_term(term: str) -> bool:
    """Whether a tag term is `@datetime` or one of its values."""
    if not isinstance(term, str):
        raise TypeError(f"term must be a string, got {type(term)}")
    folded = term.casefold()
    if folded == DATETIME_TAG:
        return True
    return folded.startswith(DATETIME_TAG_PREFIX)


def may_be_datetime_tag(typed: str) -> bool:
    """Whether a tag being typed (`@d`, `@datetime=2026`) can still become `@datetime`."""
    if not isinstance(typed, str):
        raise TypeError(f"typed must be a string, got {type(typed)}")
    folded = typed.casefold()
    if DATETIME_TAG_PREFIX.startswith(folded):
        return True
    return folded.startswith(DATETIME_TAG_PREFIX)


def _days_in_text(text: str) -> list[_FoundDay]:
    """Every date the text writes, real or not, in no particular order."""
    found = [
        _FoundDay(start=match.start(), end=match.end(), year=int(match["year"]), month=int(match["month"]), day=int(match["day"]))
        for match in _YEAR_FIRST_DATE_RE.finditer(text)
    ]
    for pattern in (_MONTH_DAY_RE, _DAY_MONTH_RE):
        for match in pattern.finditer(text):
            month_name = match["month"]
            if month_name.casefold() == _AMBIGUOUS_MONTH_WORD and not month_name[0].isupper():
                continue
            year = None
            if match["year"] is not None:
                year = int(match["year"])
            month = _MONTH_NUMBERS[month_name[:_MONTH_KEY_LENGTH].casefold()]
            found.append(_FoundDay(start=match.start(), end=match.end(), year=year, month=month, day=int(match["day"])))
    return found


def _first_time_in_text(text: str, *, outside: _FoundDay) -> str | None:
    """The first real time the text writes outside the date, as HH:MM, or None."""
    times: list[tuple[int, str]] = []
    for match in _TWELVE_HOUR_TIME_RE.finditer(text):
        hour = int(match["hour"])
        minute = _NO_MINUTES
        if match["minute"] is not None:
            minute = match["minute"]
        if not _FIRST_DAY <= hour <= _NOON_HOUR or int(minute) > _LAST_MINUTE:
            continue
        # 12am is midnight, 12pm noon.
        hour %= _NOON_HOUR
        if match["meridiem"].casefold() == _AFTERNOON:
            hour += _NOON_HOUR
        times.append((match.start(), f"{_TWO_DIGITS.format(hour)}:{minute}"))
    for match in _TWENTY_FOUR_HOUR_TIME_RE.finditer(text):
        if int(match["hour"]) > _LAST_HOUR or int(match["minute"]) > _LAST_MINUTE:
            continue
        times.append((match.start(), f"{_TWO_DIGITS.format(int(match['hour']))}:{match['minute']}"))
    times = [(start, time) for start, time in times if not outside.start <= start < outside.end]
    if not times:
        return None
    return min(times)[1]


def datetime_tag_in_text(text: str, *, year_if_missing: int) -> str | None:
    """`@datetime=` and the first real date in a note's text, with the first time written
    anywhere in it, or None when it names no date. A date without its year (Jan 3rd) takes
    year_if_missing."""
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, got {type(text)}")
    if not isinstance(year_if_missing, int):
        raise TypeError(f"year_if_missing must be an int, got {type(year_if_missing)}")
    real_days: list[tuple[int, _FoundDay, int]] = []
    for found in _days_in_text(text):
        year = year_if_missing
        if found.year is not None:
            year = found.year
        if _is_real_day(year, found.month, found.day):
            real_days.append((found.start, found, year))
    if not real_days:
        return None
    _start, first, year = min(real_days, key=lambda entry: entry[0])
    value = f"{year}-{_TWO_DIGITS.format(first.month)}-{_TWO_DIGITS.format(first.day)}"
    time = _first_time_in_text(text, outside=first)
    if time is not None:
        value += f"T{time}"
    return DATETIME_TAG_PREFIX + value


def suggested_datetime_tag(*, text: str, now: datetime, year_if_missing: int) -> str:
    """The `@datetime` a tag bar suggests: the first date the note's text names (a year
    it leaves out is year_if_missing, the year the note was last updated), else now."""
    named = datetime_tag_in_text(text, year_if_missing=year_if_missing)
    if named is not None:
        return named
    return datetime_tag_for_now(now)


def datetime_tag_for_now(now: datetime) -> str:
    """The tag the suggestion offers: `@datetime=` and now, as stored."""
    if not isinstance(now, datetime):
        raise TypeError(f"now must be a datetime, got {type(now)}")
    return DATETIME_TAG_PREFIX + now.strftime(_SUGGESTED_FORMAT)
