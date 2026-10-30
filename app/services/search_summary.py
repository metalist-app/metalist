"""Summaries beside the result count (docs/ui/search-semantics.md, Summaries; agreed
2026-10-26): a view option picks a calculation and a property, and the figure covers
exactly the notes the search finds.

Values count only on the note that writes them (never inherited), on any tag, and each
note first adds up its own values of the property, so Average, Median, Min and Max are
per note and say so; Sum is the same either way. Units are kept apart, never converted;
values that are not numbers are left out of those and counted. Mode, for any values, is
the most common value, each note counting once per distinct value, with its count; ties
show every tied value. Nothing is grouped by day or any other inferred unit.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List

from app.services.input_errors import InputRejected
from app.services.search_index import tag_bar_values
from app.services.subtree_stats import (
    AVERAGE, MAXIMUM, MEDIAN, MINIMUM, SUM, PropertyTotals, figure_of, totals_of_notes,
)
from app.services.tag_properties import IMPLICIT_PROPERTY, VALUE_NUMBER, PropertyValue, is_property_name

MODE = "mode"
# The choices, in the order the dialog lists them.
SUMMARY_KINDS = (SUM, AVERAGE, MEDIAN, MINIMUM, MAXIMUM, MODE)
_PER_NOTE_LABELS = {AVERAGE: "avg", MEDIAN: "median", MINIMUM: "min", MAXIMUM: "max"}
_MISSING = "—"
_ZERO = "0"
_TIE_SEPARATOR = ", "


@dataclass(frozen=True, slots=True)
class SearchSummary:
    kind: str
    # Casefolded; any tag's value of it counts.
    property_name: str


@dataclass(frozen=True, slots=True)
class SummaryFigure:
    # What shows under the count, short since the chip in the search box names the
    # calculation and the property (`Σ 1,400`, `500 per note`, `sci-fi (2 of 3)`), and the
    # whole of it in its tooltip (`Σ calories over 3 notes with a number, of 6 found`).
    text: str
    title: str


def make_search_summary(*, kind: str, property_name: str) -> SearchSummary:
    """A summary as a request names it, or InputRejected saying what is wrong."""
    if kind not in SUMMARY_KINDS:
        raise InputRejected(f"A summary is one of {', '.join(SUMMARY_KINDS)}, not {kind!r}")
    if not isinstance(property_name, str) or not is_property_name(property_name):
        raise InputRejected("Pick a property for the summary (a name starting with a letter)")
    return SearchSummary(kind=kind, property_name=property_name.casefold())


def summarize(summary: SearchSummary, tag_bars: List[str]) -> SummaryFigure:
    """The figure over these notes (their own tag bars, one per note found)."""
    if summary.kind == MODE:
        return _mode_figure(summary.property_name, tag_bars)
    totals = totals_of_notes(tag_bars)
    property_totals = PropertyTotals(note_totals_by_unit={}, note_count=0, skipped_count=0)
    if summary.property_name in totals:
        property_totals = totals[summary.property_name]
    figure = _number_figure(summary.kind, property_totals)
    text = f"Σ {figure}"
    label = f"Σ {summary.property_name} {figure}"
    if summary.kind != SUM:
        text = f"{figure} per note"
        label = f"{_PER_NOTE_LABELS[summary.kind]} {summary.property_name} per note {figure}"
    title = f"{label}: over {_notes(property_totals.note_count)} with a number, of {_notes(len(tag_bars))} found"
    if property_totals.skipped_count > 0:
        title = f"{title}; {_values(property_totals.skipped_count)} not numbers, left out"
    return SummaryFigure(text=text, title=title)


def _number_figure(kind: str, totals: PropertyTotals) -> str:
    if totals.note_count > 0:
        return figure_of(totals, kind)
    # The sum of nothing is 0; an average, median, minimum or maximum of nothing does not exist.
    if kind == SUM:
        return _ZERO
    return _MISSING


def _mode_figure(property_name: str, tag_bars: List[str]) -> SummaryFigure:
    counts: Counter[str] = Counter()
    note_count = 0
    for tags in tag_bars:
        shown = {_shown(value) for value in _own_values(tags, property_name)}
        if shown:
            note_count += 1
            counts.update(shown)
    if not counts:
        return SummaryFigure(text=_MISSING, title=f"No note found has {property_name}")
    top = max(counts.values())
    tied = sorted(value for value, count in counts.items() if count == top)
    each = ""
    if len(tied) > 1:
        each = " each"
    values = _TIE_SEPARATOR.join(tied)
    return SummaryFigure(
        text=f"{values} ({top:,} of {note_count:,}{each})",
        title=(f"mode {property_name}: {values} ({top:,} of {_notes(note_count)}{each}), the most common among "
               "the notes found with one; each note counts once per value"),
    )


def _own_values(tags: str, property_name: str) -> Iterable[PropertyValue]:
    """A note's own values of the property on any tag; a tag's own value (`calories=700`)
    counts as the property named like the tag, as in @stats."""
    _, values = tag_bar_values(tags)
    for (tag_name, name), value in values.items():
        if name == IMPLICIT_PROPERTY:
            name = tag_name
        if name == property_name:
            yield value


def _shown(value: PropertyValue) -> str:
    if value.kind == VALUE_NUMBER:
        return f"{value.sort_key.normalize():f}{value.unit}"
    return str(value.sort_key)


def _notes(count: int) -> str:
    if count == 1:
        return "1 note"
    return f"{count:,} notes"


def _values(count: int) -> str:
    if count == 1:
        return "1 value is"
    return f"{count:,} values are"


def summaries_by_tab(raw: Dict[str, object]) -> Dict[str, SearchSummary]:
    """Stored summaries by tab id ({tabId: {kind, property}}), checked."""
    summaries: Dict[str, SearchSummary] = {}
    for tab_id, entry in raw.items():
        if not isinstance(entry, dict) or set(entry) != {"kind", "property"}:
            raise InputRejected("each summary is a kind and a property")
        summaries[tab_id] = make_search_summary(kind=entry["kind"], property_name=entry["property"])
    return summaries
