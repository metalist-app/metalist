"""The @datetime tag (app/services/note_datetime.py): reading a note's date from its tag
line, and the date a tag bar suggests."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.services.note_datetime import datetime_tag_in_text, note_date_of_tags, suggested_datetime_tag

NOW = datetime(2026, 10, 30, 9, 9)
# The year a note was last updated, for a date written without one.
YEAR_LAST_UPDATED = 2025


@pytest.mark.parametrize(("tags", "day"), [
    ("journal @datetime=2026-10-24", date(2026, 10, 24)),
    ("@datetime=2026-10-24T08:30 food", date(2026, 10, 24)),
    ("@DateTime=2026-10-24t23:59", date(2026, 10, 24)),
    # The first one counts; the tag bar refuses a second.
    ("@datetime=2026-10-24 @datetime=2026-10-25", date(2026, 10, 24)),
    ("journal", None),
    # Not a real day or time, or not a whole token: dates nothing.
    ("@datetime=2026-02-30", None),
    ("@datetime=2026-10-24T24:00", None),
    ("@datetime=2026-10", None),
    ("x@datetime=2026-10-24", None),
])
def test_a_notes_date_is_its_own_datetime_tag(tags: str, day: date | None) -> None:
    assert note_date_of_tags(tags) == day


@pytest.mark.parametrize(("text", "tag"), [
    ("2026.10.29 - Thurs: {[Possibility Atlas project]}", "@datetime=2026-10-29"),
    ("met 2026-10-29 08:30 for coffee", "@datetime=2026-10-29T08:30"),
    ("2026/3/1", "@datetime=2026-03-01"),
    # The month by name; a year left out is the one given (the note's last update).
    ("I went to the dentist on Jan 3rd at 4:30pm", "@datetime=2025-01-03T16:30"),
    ("the 3rd of January 2024, 16:30", "@datetime=2024-01-03T16:30"),
    ("Sept. 9 at 9 p.m.", "@datetime=2025-09-09T21:00"),
    # A colon after the day; the first time after it, not a later one or a number.
    ("Oct 30th: 3pm (arrive 2:45) 1400 (urology)", "@datetime=2025-10-30T15:00"),
    ("May 5 at 12am", "@datetime=2025-05-05T00:00"),
    # The time need not be next to the date.
    ("Dentist Jan 3rd. Appointment moved to 4pm.", "@datetime=2025-01-03T16:00"),
    # The first real date; one that is not a day is passed over.
    ("2026/2/30 then 2026/3/1", "@datetime=2026-03-01"),
    ("Feb 29, then March 2", "@datetime=2025-03-02"),
    # Not dates: version numbers, addresses, dates of numbers that are not year first,
    # "may" the word, a time alone.
    ("v1.2026.10.29.3", None),
    ("192.168.10.1", None),
    ("10/29/2026", None),
    ("we may 5 people", None),
    ("4:30pm only", None),
    # A day followed by minutes is a time, not a date.
    ("Jan 3:30 call", None),
])
def test_the_first_date_in_a_notes_text(text: str, tag: str | None) -> None:
    assert datetime_tag_in_text(text, year_if_missing=YEAR_LAST_UPDATED) == tag


def test_the_suggestion_is_the_texts_date_else_now() -> None:
    assert suggested_datetime_tag(
        text="2026.10.29 - Thurs", now=NOW, year_if_missing=YEAR_LAST_UPDATED,
    ) == "@datetime=2026-10-29"
    assert suggested_datetime_tag(
        text="no date here", now=NOW, year_if_missing=YEAR_LAST_UPDATED,
    ) == "@datetime=2026-10-30T09:09"
