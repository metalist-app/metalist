"""Totals of a note's subtree: `@stats`, `@sum=`, `@avg=`, `@min=`, `@max=`, `@count=`.

A footer under the note's own text (docs/ui/content-formatting.md, Totals): the numeric
super tag values of the note and every note under it, each counted once on the note that
writes it (values are never inherited, and links and embeds are not part of the subtree).
Values are read through the render context, so the cached rendering of the note is
redrawn whenever a note under it changes (snapshot.py, _DependencyRecorder).
"""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Protocol, Tuple

from app.services.search_index import tag_bar_values
from app.services.tag_properties import (
    IMPLICIT_PROPERTY, META_TAG_PREFIX, VALUE_NUMBER, PropertyCondition, PropertySuggestion,
    PropertyValue,
)


STATS_TAG = "stats"
SUM = "sum"
AVERAGE = "avg"
MINIMUM = "min"
MAXIMUM = "max"
COUNT = "count"
SUMMARY_KINDS = (SUM, AVERAGE, MINIMUM, MAXIMUM, COUNT)
# How the totals look (Stats Style in the command palette; main.css): an accent strip,
# number tiles or a ledger. The same markup takes each look.
STATS_STYLES = frozenset({"strip", "tiles", "ledger"})
# The parts of an @stats line, in order; avg has a tag of its own only.
_STATS_KINDS = (SUM, MINIMUM, MAXIMUM, COUNT)

# A whole token on the note's own tag line (not inside a scope): @stats, @sum, @sum=calories.
# Property names start with a letter (docs/design/tag-properties.md, Syntax).
_SUMMARY_TAG_RE = re.compile(
    r"(?<!\S)@(?P<kind>stats|sum|avg|min|max|count)(?:=(?P<property>[^\s=:]*))?(?!\S)",
    re.IGNORECASE,
)
_PROPERTY_NAME_RE = re.compile(r"[A-Za-z][^\s=:]*")
# What is being typed after a summary tag's = (`@sum=cal`), for suggestions.
_TYPED_SUMMARY_PROPERTY_RE = re.compile(r"@(?P<kind>sum|avg|min|max|count)=(?P<typed>[^\s=:]*)", re.IGNORECASE)

# Decimal places shown: an average to one place, any other number to two at most.
_AVERAGE_PLACES = 1
_NUMBER_PLACES = 2
_SIGN_AND_DIGITS_SEPARATOR = ","
_UNIT_SEPARATOR = ", "
_MISSING = "—"
# The sum and the count of no values (an empty day reads 0).
_ZERO_WHEN_EMPTY = frozenset({SUM, COUNT})
_ZERO = "0"
# A @stats property's figures, and each precise tag's label.
_STATS_FIGURES = ((SUM, "Total"), (MINIMUM, "Min"), (MAXIMUM, "Max"), (COUNT, "Count"))
_FIGURE_LABELS = {SUM: "Total {}", AVERAGE: "Average {}", MINIMUM: "Min {}", MAXIMUM: "Max {}", COUNT: "Notes with {}"}


class NoteTree(Protocol):
    """What the suggestions read: a note by id and the ids of its children. The render
    context (embedded_references.EmbedRenderContext) and the note store both are one."""

    def get_note(self, note_id: str) -> object: ...

    def get_children(self, note_id: str) -> List[str]: ...


class StatsContext(NoteTree, Protocol):
    """What the footer reads: the tree, and whether some note in the vault gives a
    property a value. The render context is one."""

    def is_property_used(self, property_name: str) -> bool: ...


def _note_tags(record: object) -> str:
    """A note record's tag line; every note record has one."""
    tags = getattr(record, "tags")
    if not isinstance(tags, str):
        raise TypeError(f"a note's tags must be a string, got {type(tags)}")
    return tags


@dataclass(frozen=True, slots=True)
class SummaryRequest:
    """One footer line asked for: every property (`@stats`) or one number of one property."""

    kind: str
    # The property's casefolded name; "" for @stats, and for a tag that names none (every
    # number property).
    property_name: str


@dataclass(slots=True)
class _PropertyTotals:
    # Per unit (casefolded, "" for none), each note's own total, in tree order.
    note_totals_by_unit: Dict[str, List[Decimal]]
    # Notes holding a number for the property, in any unit.
    note_count: int
    # Values that are not numbers (text, dates, times), skipped.
    skipped_count: int


def parse_summary_requests(tags: str) -> Tuple[SummaryRequest, ...]:
    """The summary tags on a note's own tag line, in the order written."""
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")
    requests: List[SummaryRequest] = []
    for match in _SUMMARY_TAG_RE.finditer(tags):
        kind = match.group("kind").casefold()
        property_name = match.group("property")
        if kind == STATS_TAG:
            requests.append(SummaryRequest(kind=STATS_TAG, property_name=""))
            continue
        if property_name is None or _PROPERTY_NAME_RE.fullmatch(property_name) is None:
            property_name = ""
        requests.append(SummaryRequest(kind=kind, property_name=property_name.casefold()))
    return tuple(requests)


def render_subtree_stats_footer(*, note_id: str, tags: str, context: StatsContext) -> str:
    """The footer for a note with summary tags, or "" for one without."""
    requests = parse_summary_requests(tags)
    if not requests:
        return ""
    totals = _collect_subtree_totals(note_id=note_id, context=context)
    lines = _footer_lines(requests, totals)
    if not lines:
        return ""
    # A property whose values are all text has no figures under @stats, only its line
    # saying they are left out (agreed 2026-10-28).
    stats_lines = [line for line in lines if line.kind == STATS_TAG]
    figure_lines = [line for line in lines if line.kind != STATS_TAG]
    parts = ['<section class="meta-stats" aria-label="Stats">']
    parts.extend(_render_stats_group(line) for line in stats_lines if _has_numbers(line.totals))
    if figure_lines:
        parts.append(_render_figures_group(figure_lines, context))
    # Each property's values that are not numbers, said once, under @stats and under
    # the precise tags alike, so a 0 never hides them.
    said: set[str] = set()
    for line in lines:
        if line.totals is None or line.totals.skipped_count == 0 or line.property_name in said:
            continue
        said.add(line.property_name)
        skipped = _skipped_text(line.totals.skipped_count, line.property_name)
        parts.append(f'<div class="meta-stats-skipped">{html.escape(skipped)}</div>')
    parts.append("</section>")
    return "".join(parts)


def stats_figure_values(
    *, note_id: str, condition: PropertyCondition, context: StatsContext,
) -> Tuple[PropertyValue, ...] | None:
    """The figure a note's stats tag shows for a search term (`@sum:calories>2000`;
    docs/ui/search-semantics.md, Stats figures): one number per unit, as the footer rounds
    it; () for a dash; None when the note shows no such figure (it carries neither
    `@sum=calories` nor a bare `@sum` that shows calories). Counted as the footer counts,
    so search and footer agree."""
    if not condition.is_stats:
        raise ValueError(f"{condition.format()} is not a stats term")
    kind = condition.key[0][len(META_TAG_PREFIX):]
    property_name = condition.key[1]
    requests = parse_summary_requests(_note_tags(context.get_note(note_id)))
    is_named = SummaryRequest(kind=kind, property_name=property_name) in requests
    covers_every_property = SummaryRequest(kind=kind, property_name="") in requests
    if not is_named and not covers_every_property:
        return None
    totals = _collect_subtree_totals(note_id=note_id, context=context)
    if property_name in totals and _has_numbers(totals[property_name]):
        return _figure_values(totals[property_name], kind)
    # A bare @sum shows only the properties with numbers under the note.
    if not is_named:
        return None
    is_used = property_name in totals
    if not is_used:
        is_used = context.is_property_used(property_name)
    if _empty_figure(kind, is_used=is_used) == _ZERO:
        return (PropertyValue(kind=VALUE_NUMBER, sort_key=Decimal(0), unit=""),)
    return ()


def _figure_values(totals: _PropertyTotals, kind: str) -> Tuple[PropertyValue, ...]:
    if kind == COUNT:
        return (PropertyValue(kind=VALUE_NUMBER, sort_key=Decimal(totals.note_count), unit=""),)
    return tuple(
        PropertyValue(
            kind=VALUE_NUMBER, sort_key=_rounded(_calculate(kind, note_totals), kind), unit=unit,
        )
        for unit, note_totals in sorted(totals.note_totals_by_unit.items())
    )


def typed_summary_property(prefix: str) -> Tuple[str, str] | None:
    """(the tag typed, `@sum`; the property's beginning) while a summary tag's property is
    being typed (`@sum=cal`), else None."""
    match = _TYPED_SUMMARY_PROPERTY_RE.fullmatch(prefix)
    if match is None:
        return None
    return f"@{match.group('kind').casefold()}", match.group("typed").casefold()


def suggest_summary_properties(
    *, note_id: str, typed_tag: str, typed_property: str, context: NoteTree, limit: int,
) -> List[PropertySuggestion]:
    """Property names used in the note and under it that start with what is typed, the
    ones on most notes first (docs/ui/content-formatting.md, Totals)."""
    note_counts: Counter[str] = Counter()
    pending = [note_id]
    while pending:
        current_id = pending.pop(0)
        named_values = _own_values_by_property(_note_tags(context.get_note(current_id)))
        for property_name in {name for name, _ in named_values}:
            note_counts[property_name] += 1
        pending.extend(context.get_children(current_id))
    names = sorted(
        (name for name in note_counts if name.startswith(typed_property)),
        key=lambda name: (-note_counts[name], name),
    )
    return [
        PropertySuggestion(
            replacement=f"{typed_tag}={name}",
            label=name,
            reasons=(f"Used under this note, on {_note_count_text(note_counts[name])}",),
            note_count=note_counts[name],
        )
        for name in names[:limit]
    ]


def _own_values_by_property(tags: str) -> List[Tuple[str, PropertyValue]]:
    """A note's own values by property name. A value written on the tag itself
    (`calories=700`, the tag's implicit property) counts as that property, beside
    `burger:calories=450` (agreed 2026-10-27)."""
    _, values = tag_bar_values(tags)
    named = []
    for (tag_name, property_name), value in values.items():
        if property_name == IMPLICIT_PROPERTY:
            property_name = tag_name
        named.append((property_name, value))
    return named


def _collect_subtree_totals(*, note_id: str, context: NoteTree) -> Dict[str, _PropertyTotals]:
    """Each property's per-note totals over the note and its descendants, by name."""
    totals: Dict[str, _PropertyTotals] = {}
    pending = [note_id]
    while pending:
        current_id = pending.pop(0)
        _add_note_values(totals, _note_tags(context.get_note(current_id)))
        pending.extend(context.get_children(current_id))
    return totals


def _add_note_values(totals: Dict[str, _PropertyTotals], tags: str) -> None:
    """Adds one note's own values: per property, the note's values summed per unit."""
    note_sums: Dict[str, Dict[str, Decimal]] = {}
    for property_name, value in _own_values_by_property(tags):
        if property_name not in totals:
            totals[property_name] = _PropertyTotals(note_totals_by_unit={}, note_count=0, skipped_count=0)
        property_totals = totals[property_name]
        if value.kind != VALUE_NUMBER:
            property_totals.skipped_count += 1
            continue
        if property_name not in note_sums:
            note_sums[property_name] = {}
        unit_sums = note_sums[property_name]
        if value.unit not in unit_sums:
            unit_sums[value.unit] = Decimal(0)
        unit_sums[value.unit] += value.sort_key
    for property_name, unit_sums in note_sums.items():
        property_totals = totals[property_name]
        property_totals.note_count += 1
        for unit, note_total in unit_sums.items():
            if unit not in property_totals.note_totals_by_unit:
                property_totals.note_totals_by_unit[unit] = []
            property_totals.note_totals_by_unit[unit].append(note_total)


@dataclass(frozen=True, slots=True)
class _FooterLine:
    # "stats" for a whole @stats line, else one summary kind.
    kind: str
    property_name: str
    totals: _PropertyTotals | None


def _footer_lines(requests: Tuple[SummaryRequest, ...], totals: Dict[str, _PropertyTotals]) -> List[_FooterLine]:
    """The lines in the order written. A summary tag without a property (`@sum`) gives a line
    for every number property, alphabetically; with @stats, a line it already shows is skipped."""
    has_stats = any(request.kind == STATS_TAG for request in requests)
    lines: List[_FooterLine] = []
    seen: set[Tuple[str, str]] = set()
    for request in requests:
        if request.kind == STATS_TAG:
            if (STATS_TAG, "") in seen:
                continue
            seen.add((STATS_TAG, ""))
            for property_name in sorted(totals):
                lines.append(_FooterLine(kind=STATS_TAG, property_name=property_name, totals=totals[property_name]))
            continue
        property_names = [request.property_name]
        if request.property_name == "":
            property_names = [name for name in sorted(totals) if totals[name].note_count > 0]
        for property_name in property_names:
            key = (request.kind, property_name)
            is_in_stats = has_stats and request.kind in _STATS_KINDS and property_name in totals and _has_numbers(totals[property_name])
            if key in seen or is_in_stats:
                continue
            seen.add(key)
            # A named property no note under it has gets its line too: 0 or a dash
            # (_empty_figure).
            property_totals = None
            if property_name in totals:
                property_totals = totals[property_name]
            lines.append(_FooterLine(kind=request.kind, property_name=property_name, totals=property_totals))
    return lines


# One markup for every Stats Style (strip, tiles, ledger; main.css): each figure is a
# label, a colon, a leader the ledger draws dots in, and its value.
def _render_item(label: str, value: str) -> str:
    return (
        '<div class="meta-stats-item">'
        f'<span class="meta-stats-label">{html.escape(label)}<span class="meta-stats-colon">:</span></span> '
        '<span class="meta-stats-leader"></span>'
        f'<span class="meta-stats-value">{value}</span>'
        "</div>"
    )


def _render_stats_group(line: _FooterLine) -> str:
    """@stats: a property's name, then its figures."""
    assert line.totals is not None
    items = "".join(_render_item(label, _figure(line.totals, kind)) for kind, label in _STATS_FIGURES)
    return (
        '<div class="meta-stats-group">'
        f'<div class="meta-stats-name">{html.escape(line.property_name)}</div>{items}'
        "</div>"
    )


def _render_figures_group(lines: List[_FooterLine], context: StatsContext) -> str:
    """The precise tags (`@sum=calories`, `@sum`): a labelled figure each."""
    items = []
    for line in lines:
        if _has_numbers(line.totals):
            assert line.totals is not None
            number = _figure(line.totals, line.kind)
        elif line.totals is not None:
            # Only text values under the note: the property is used.
            number = _empty_figure(line.kind, is_used=True)
        else:
            number = _empty_figure(line.kind, is_used=context.is_property_used(line.property_name))
        items.append(_render_item(_FIGURE_LABELS[line.kind].format(line.property_name), number))
    return f'<div class="meta-stats-group">{"".join(items)}</div>'


def _has_numbers(totals: _PropertyTotals | None) -> bool:
    return totals is not None and totals.note_count > 0


def _empty_figure(kind: str, *, is_used: bool) -> str:
    """A figure with no number under the note (agreed 2026-10-28): the sum and the count
    of nothing are 0, so a new day with `@sum=calories` reads 0; an average, minimum or
    maximum of nothing does not exist. A property used nowhere in the vault is a dash for
    every tag, so a typo shows."""
    if is_used and kind in _ZERO_WHEN_EMPTY:
        return _ZERO
    return _MISSING


def _figure(totals: _PropertyTotals, kind: str) -> str:
    if kind == COUNT:
        return f"{totals.note_count:,}"
    return _per_unit(totals, kind)


def _per_unit(totals: _PropertyTotals, kind: str) -> str:
    """One number per unit: a plain number first, then the units alphabetically."""
    numbers = []
    units = sorted(totals.note_totals_by_unit, key=lambda unit: (unit != "", unit))
    for unit in units:
        note_totals = totals.note_totals_by_unit[unit]
        numbers.append(_format_number(_calculate(kind, note_totals), kind) + html.escape(unit))
    return _UNIT_SEPARATOR.join(numbers)


def _calculate(kind: str, note_totals: List[Decimal]) -> Decimal:
    assert note_totals, "a unit is only listed with at least one note's total"
    if kind == SUM:
        return sum(note_totals, Decimal(0))
    if kind == MINIMUM:
        return min(note_totals)
    if kind == MAXIMUM:
        return max(note_totals)
    if kind == AVERAGE:
        return sum(note_totals, Decimal(0)) / Decimal(len(note_totals))
    raise ValueError(f"no number to calculate for {kind!r}")


def _rounded(value: Decimal, kind: str) -> Decimal:
    """Rounded to the kind's places, as the footer shows it."""
    places = _NUMBER_PLACES
    if kind == AVERAGE:
        places = _AVERAGE_PLACES
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _format_number(value: Decimal, kind: str) -> str:
    """Thousands separated, rounded to the kind's places, with no trailing zeros."""
    rounded = _rounded(value, kind)
    text = f"{rounded:,f}".replace(",", _SIGN_AND_DIGITS_SEPARATOR)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _note_count_text(count: int) -> str:
    if count == 1:
        return "1 note"
    return f"{count:,} notes"


def _skipped_text(count: int, property_name: str) -> str:
    if count == 1:
        return f"1 {property_name} value is not a number and is left out"
    return f"{count:,} {property_name} values are not numbers and are left out"
