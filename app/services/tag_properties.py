"""Tag properties (docs/design/tag-properties.md): jogging:miles=3:duration=30.

The tag is everything before the first colon; what follows are its properties. For
search, inheritance, ontology rules and tag counts a token with properties is its tag:
jogging:miles=3 is jogging. Meta tags (@size=2) and tags inside scopes have none.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
import re
from typing import Any, Dict, FrozenSet, List, Mapping, Tuple

from app.services.input_errors import InputRejected
from app.services.quoted_values import (
    find_outside_values, is_quoted, opens_value, quote_value, quoted_value_end, unquote_value,
)
from app.services.text_terms import text_term_matches

PROPERTY_SEPARATOR = ":"
META_TAG_PREFIX = "@"
_PROPERTY_SEPARATORS = frozenset(PROPERTY_SEPARATOR)


def _property_separator_index(token: str) -> int:
    """The colon that ends the tag, outside any quoted value (author="a:b" has none), or -1."""
    return find_outside_values(token, _PROPERTY_SEPARATORS, 0)


def has_property_syntax(token: str) -> bool:
    if not isinstance(token, str):
        raise TypeError(f"token must be a string, got {type(token)}")
    return _property_separator_index(token) > 0 and not token.startswith(META_TAG_PREFIX)


def tag_part_of_token(token: str) -> str:
    """The tag a token names: jogging for jogging:miles=3, the token itself otherwise."""
    if not has_property_syntax(token):
        return token
    return token[: _property_separator_index(token)]


# --- Values and search conditions -------------------------------------------------

PROPERTY_ASSIGNMENT = "="
# Search's OR operator is never a tag, so never a property term's tag either.
RESERVED_OR = "OR"
# The property a valued tag carries without naming it: jogging=3 is jogging:value=3.
IMPLICIT_PROPERTY = "value"
MISSING_OPERATOR = "?"
# A bare property name in a search: the note has the property, with any value.
PRESENT_OPERATOR = ""
COMPARISON_OPERATORS = (">=", "<=", ">", "<", "=")
_OPERATOR_CHARACTERS = frozenset("<>=")
# Comparisons a search can write without naming a property: date>=2024-01. (date=2024-01
# stays the valued tag it has always been.)
IMPLICIT_COMPARISON_OPERATORS = (">=", "<=", ">", "<")

# jogging:miles=MAX and =MIN: the notes with the largest or smallest value, among those
# the rest of the search finds. Exact capitals, as OR is.
MAX_KEYWORD = "MAX"
MIN_KEYWORD = "MIN"
EXTREME_KEYWORDS = (MAX_KEYWORD, MIN_KEYWORD)

# The stats tags (subtree_stats.py): in a search, `@sum:calories>2000` compares the figure
# a note carrying `@sum=calories` shows (docs/ui/search-semantics.md, Stats figures). Only
# search reads them as terms; in the tag bar a meta tag has no properties.
STATS_TERM_TAGS = frozenset({"@sum", "@avg", "@min", "@max", "@count"})
# A stats tag followed by what makes it a term rather than the tag (`@sum=calories`).
_STATS_TERM_START_RE = re.compile(r"^(?P<tag>@(?:sum|avg|min|max|count))(?=[:<>?])", re.IGNORECASE)
_STATS_TERM_EXAMPLE = "{tag}:calories>2000"

VALUE_NUMBER = "number"
VALUE_TEMPORAL = "temporal"
VALUE_TIME = "time"
VALUE_TEXT = "text"
# Which kind MAX and MIN compare when a property's values are of several, on a tie.
VALUE_KIND_ORDER = (VALUE_NUMBER, VALUE_TEMPORAL, VALUE_TIME, VALUE_TEXT)

_NUMBER_RE = re.compile(r"^(?P<number>-?(?:\d+(?:\.\d+)?|\.\d+))(?P<unit>[A-Za-z%][A-Za-z%/]*)?$")
_DATE_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})(?:-(?P<day>\d{2}))?$")
_DATE_TIME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$")
_TIME_RE = re.compile(
    r"^(\d{1,2})(?::(\d{2})(?::(\d{2}))?)?\s*(am|pm|a\.m\.|p\.m\.)?$", re.IGNORECASE,
)
# What a property name may not hold after its first letter.
_PROPERTY_NAME_DISALLOWED = frozenset(":=<>?")
_HOURS_ON_A_CLOCK = 12
_HOURS_IN_DAY = 24
_MINUTES_IN_HOUR = 60
_SECONDS_IN_MINUTE = 60
_FIRST_DAY = 1
_AFTERNOON = "p"


@dataclass(frozen=True, slots=True)
class PropertyValue:
    """A property's value as compared: its kind, what orders it, and a number's unit."""

    kind: str
    # A number's value, a date's or date-time's moment, a time's seconds after midnight,
    # or casefolded text.
    # Keys of one kind compare with each other (comparisons check the kind first).
    sort_key: Any
    # A number's unit as written after it, casefolded ("mg" for 10mg); "" for none.
    unit: str
    # The value as written, without quotes: what a quoted search value matches inside.
    text: str


def _number_value(text: str) -> PropertyValue | None:
    match = _NUMBER_RE.match(text)
    if match is None:
        return None
    unit = match.group("unit")
    if unit is None:
        unit = ""
    if unit.casefold() in {"am", "pm"}:
        return None
    return PropertyValue(kind=VALUE_NUMBER, sort_key=Decimal(match.group("number")), unit=unit.casefold(), text=text)


def _temporal_value(text: str) -> PropertyValue | None:
    date_time = _DATE_TIME_RE.match(text)
    if date_time is not None:
        year, month, day, hour, minute, second = (int(part) if part else 0 for part in date_time.groups())
        moment = _valid_moment(year, month, day, hour=hour, minute=minute, second=second)
    else:
        date_only = _DATE_RE.match(text)
        if date_only is None:
            return None
        # A month without a day is its first day: 2024-01 is 2024-01-01.
        day = _FIRST_DAY
        if date_only.group("day") is not None:
            day = int(date_only.group("day"))
        moment = _valid_moment(
            int(date_only.group("year")), int(date_only.group("month")), day, hour=0, minute=0, second=0,
        )
    if moment is None:
        return None
    return PropertyValue(kind=VALUE_TEMPORAL, sort_key=moment, unit="", text=text)


def _valid_moment(year: int, month: int, day: int, *, hour: int, minute: int, second: int) -> datetime | None:
    if not 1 <= month <= len(calendar.month_abbr) - 1:
        return None
    if not 1 <= day <= calendar.monthrange(year, month)[1]:
        return None
    if hour >= _HOURS_IN_DAY or minute >= _MINUTES_IN_HOUR or second >= _SECONDS_IN_MINUTE:
        return None
    return datetime(year, month, day, hour, minute, second)


def _time_value(text: str) -> PropertyValue | None:
    match = _TIME_RE.match(text)
    if match is None:
        return None
    hour_text, minute_text, second_text, meridiem = match.groups()
    # A bare number (10) is a number; a time has minutes or am/pm.
    if minute_text is None and meridiem is None:
        return None
    hour = int(hour_text)
    # 10am has no minutes and 10:30 no seconds: none.
    minute = 0
    if minute_text is not None:
        minute = int(minute_text)
    second = 0
    if second_text is not None:
        second = int(second_text)
    if meridiem is not None:
        if not 1 <= hour <= _HOURS_ON_A_CLOCK:
            return None
        # 12am is midnight and 12pm noon.
        hour %= _HOURS_ON_A_CLOCK
        if meridiem.casefold().startswith(_AFTERNOON):
            hour += _HOURS_ON_A_CLOCK
    if hour >= _HOURS_IN_DAY or minute >= _MINUTES_IN_HOUR or second >= _SECONDS_IN_MINUTE:
        return None
    return PropertyValue(
        kind=VALUE_TIME, sort_key=(hour * _MINUTES_IN_HOUR + minute) * _SECONDS_IN_MINUTE + second, unit="",
        text=text,
    )


def parse_property_value(text: str) -> PropertyValue:
    """A value as the first kind it reads as: a time (10:30, 10:30pm, 10am), a date or
    date-time (2024-01, 2024-01-15, 2024-01-15T10:30), a number with an optional unit
    (3, -2.5, 10mg), else text. A year alone (2026) is a number."""
    if not isinstance(text, str) or text == "":
        raise ValueError("A property value must be non-empty text")
    for reader in (_time_value, _temporal_value, _number_value):
        value = reader(text)
        if value is not None:
            return value
    return PropertyValue(kind=VALUE_TEXT, sort_key=text.casefold(), unit="", text=text)


def is_property_name(name: str) -> bool:
    """A property's name: a letter first, in any script (str.isalpha, the browser's \\p{L}),
    then no : = < > ?."""
    return name != "" and name[0].isalpha() and not any(char in _PROPERTY_NAME_DISALLOWED for char in name)


def split_property_segments(text: str) -> List[str]:
    """The text after a tag, split where a colon is followed by a letter (or ends it); a
    quoted value is kept whole (title="Dune: Messiah")."""
    segments: List[str] = []
    current = ""
    index = 0
    while index < len(text):
        if opens_value(text, index):
            end = quoted_value_end(text, index).end
            current += text[index:end]
            index = end
            continue
        char = text[index]
        index += 1
        is_last = index == len(text)
        if char == PROPERTY_SEPARATOR and (is_last or text[index].isalpha()):
            segments.append(current)
            current = ""
            continue
        current += char
    segments.append(current)
    return segments


def token_properties(token: str) -> Tuple[str, Dict[str, PropertyValue]]:
    """A tag token's tag name (casefolded, without its value) and its properties by
    casefolded name: jogging=3:miles=3 is ("jogging", {"value": 3, "miles": 3}). A
    property the tag bar would not keep (no value, repeated) is left out."""
    tag_part = tag_part_of_token(token)
    name, assignment, implicit_value = tag_part.partition(PROPERTY_ASSIGNMENT)
    properties: Dict[str, PropertyValue] = {}
    if assignment and unquote_value(implicit_value) != "":
        properties[IMPLICIT_PROPERTY] = parse_property_value(unquote_value(implicit_value))
    if has_property_syntax(token):
        for segment in split_property_segments(token[len(tag_part) + 1:]):
            property_name, has_value, value = segment.partition(PROPERTY_ASSIGNMENT)
            key = property_name.casefold()
            text = unquote_value(value)
            if not has_value or text == "" or not is_property_name(property_name) or key in properties:
                continue
            properties[key] = parse_property_value(text)
    return name.casefold(), properties


@dataclass(frozen=True, slots=True)
class PropertyCondition:
    """One property search term: jogging:miles>2, jogging:miles?, jogging:miles, date>=2024-01."""

    tag: str
    name: str
    operator: str
    # The compared value as typed, quotes included; "" for ? and a bare name.
    value_text: str
    # The term's further conditions (:foo="bar":baz>3), each met by the same tag as this
    # one (decided 2026-10-31); () for a term with one condition.
    chained: Tuple["PropertyCondition", ...]

    @property
    def links(self) -> Tuple["PropertyCondition", ...]:
        """Every condition of the term, this one first, none with a chain of its own."""
        return (replace(self, chained=()),) + self.chained

    @property
    def key(self) -> Tuple[str, str]:
        return self.tag.casefold(), self.name.casefold()

    @property
    def is_extreme(self) -> bool:
        """jogging:miles=MAX or =MIN: decided across the notes found, not one note alone."""
        return self.operator == "=" and self.value_text in EXTREME_KEYWORDS

    @property
    def reads_values(self) -> bool:
        """jogging:miles>2, jogging:miles, jogging:miles=MAX: about a value a note has,
        its own or inherited (docs/ui/search-semantics.md, Super Tag Searches); not a
        missing one (jogging:miles?) or a stats figure, which stay the note's own."""
        return self.operator != MISSING_OPERATOR and not self.is_stats

    @property
    def is_stats(self) -> bool:
        """@sum:calories>2000: about the figure a stats tag shows, not a value on a note."""
        return self.key[0] in STATS_TERM_TAGS

    @property
    def is_text_match(self) -> bool:
        """:foo="ba": a quoted value after =, matched inside the note's value as quoted
        text is (decided 2026-10-31); a bare value after = matches the whole value."""
        return self.operator == "=" and is_quoted(self.value_text)

    @property
    def compared_text(self) -> str:
        """The compared value without its quotes."""
        return unquote_value(self.value_text)

    def format(self) -> str:
        chain = "".join(f"{PROPERTY_SEPARATOR}{link.name}{link.operator}{link.value_text}" for link in self.chained)
        if self.tag != ANY_TAG and self.name == IMPLICIT_PROPERTY and _is_implicit_term(self.operator, self.value_text):
            return f"{self.tag}{self.operator}{self.value_text}{chain}"
        return f"{self.tag}{PROPERTY_SEPARATOR}{self.name}{self.operator}{self.value_text}{chain}"


def is_property_term(token: str) -> bool:
    """Whether a search term is about a property rather than a tag: it names one
    (jogging:miles>2), compares (date>=2024-01) or matches a quoted value (author="Le Guin")."""
    if token.startswith(META_TAG_PREFIX):
        return False
    if has_property_syntax(token):
        return True
    _name, operator, value = _split_at_operator(token)
    return _is_implicit_term(operator, value)


def _is_implicit_term(operator: str, value: str) -> bool:
    """A term about a tag's own value, without naming the property: date>=2024-01 or
    author="Le Guin" (date=2024-01, bare, stays the valued tag it has always been)."""
    if operator in IMPLICIT_COMPARISON_OPERATORS:
        return True
    return operator == PROPERTY_ASSIGNMENT and is_quoted(value)


def property_term_tag(token: str) -> str:
    """The tag a property term is about, read without checking the rest of it."""
    return re.split(r"[:<>]", token, maxsplit=1)[0]


def parse_property_term(token: str) -> PropertyCondition:
    """A property search term, or InputRejected saying how to write one. Its conditions
    after the first (jogging:miles>2:duration<40) are chained to it."""
    problem = property_term_problem(token)
    if problem != "":
        raise InputRejected(problem)
    return _chained_condition([
        PropertyCondition(tag=tag, name=name, operator=operator, value_text=value_text, chained=())
        for tag, name, operator, value_text in _chain_parts(token)
    ])


def _chained_condition(conditions: List[PropertyCondition]) -> PropertyCondition:
    """The first condition of a term with the rest chained to it."""
    assert conditions, "a term has a condition"
    return replace(conditions[0], chained=tuple(conditions[1:]))


def _chain_parts(token: str) -> List[Tuple[str, str, str, str]]:
    """Each condition of a term as its tag, property name, operator and value, as written:
    jogging:miles>2:duration<40 is two, split where a colon is followed by a letter."""
    if not has_property_syntax(token):
        return [_split_property_term(token)]
    tag = tag_part_of_token(token)
    return [
        _split_property_term(f"{tag}{PROPERTY_SEPARATOR}{segment}")
        for segment in split_property_segments(token[len(tag) + len(PROPERTY_SEPARATOR):])
    ]


_CHAIN_EXAMPLE = "jogging:miles>2:duration<40"


def _chain_problem(parts: List[Tuple[str, str, str, str]]) -> str:
    """What a chained term may not hold: ?, MAX and MIN go in terms of their own (each is
    about the property alone, or across notes), and each property is named once."""
    if len(parts) == 1:
        return ""
    names = [name.casefold() for _tag, name, _operator, _value in parts]
    if len(set(names)) != len(names):
        return f"Name each property once in a search term (for example {_CHAIN_EXAMPLE})"
    for _tag, name, operator, value_text in parts:
        if operator == MISSING_OPERATOR:
            return f"Search a missing property in a term of its own (for example jogging:miles>2 jogging:{name}?)"
        if value_text in EXTREME_KEYWORDS:
            return f"{value_text} goes in a term of its own (for example jogging:{name}={value_text})"
    return ""


# A property on any tag (`:version`, `:version=0.24.5`, `:version>0.24`): a search term
# with no tag before its colon (docs/ui/search-syntax.md; agreed 2026-10-25). Search only:
# rules always name their tag.
ANY_TAG = ""
_TAGLESS_EXAMPLE = ":version=0.24"


def is_tagless_property_term(token: str) -> bool:
    """Whether a search term is a property on any tag: it starts with the colon."""
    if not isinstance(token, str):
        raise TypeError(f"token must be a string, got {type(token)}")
    return token.startswith(PROPERTY_SEPARATOR)


def parse_tagless_property_term(token: str) -> PropertyCondition:
    """`:version`, `:version=0.24.5` or `:version>0.24`, or InputRejected saying how to
    write one. A missing property (`:version?`) needs its tag: on any tag it matches too
    much (decided 2026-10-25)."""
    if not is_tagless_property_term(token):
        raise ValueError(f"{token} does not start with {PROPERTY_SEPARATOR}")
    parts = [_tagless_part(segment) for segment in split_property_segments(token[len(PROPERTY_SEPARATOR):])]
    problem = _chain_problem(parts)
    if problem != "":
        raise InputRejected(problem.replace("jogging:", PROPERTY_SEPARATOR))
    return _chained_condition([
        PropertyCondition(tag=tag, name=name, operator=operator, value_text=value_text, chained=())
        for tag, name, operator, value_text in parts
    ])


def _tagless_part(segment: str) -> Tuple[str, str, str, str]:
    """One condition of a property on any tag (version>0.24), or InputRejected."""
    if segment.endswith(MISSING_OPERATOR):
        raise InputRejected("A search for a missing property needs its tag (for example jogging:miles?)")
    name, operator, value_text = _split_at_operator(segment)
    if operator == "":
        name, operator = segment, PRESENT_OPERATOR
    if name == "":
        raise InputRejected(f"Name a property after the colon (for example {_TAGLESS_EXAMPLE})")
    problem = _name_and_value_problem(name, operator, value_text)
    if problem != "":
        raise InputRejected(problem)
    return ANY_TAG, name, operator, value_text


def is_stats_term(token: str) -> bool:
    """Whether a search term compares a stats figure (`@sum:calories>2000`), or tries to
    (`@sum>2000`, refused by parse_stats_term with how to write it)."""
    if not isinstance(token, str):
        raise TypeError(f"token must be a string, got {type(token)}")
    return _STATS_TERM_START_RE.match(token) is not None


def parse_stats_term(token: str) -> PropertyCondition:
    """A stats figure term (`@sum:calories>2000`, `@sum:calories`, `@sum:calories=MAX`), or
    InputRejected saying how to write one. The figure is a number, so the value is one."""
    match = _STATS_TERM_START_RE.match(token)
    if match is None:
        raise ValueError(f"{token} is not a stats term")
    tag = match.group("tag").casefold()
    example = _STATS_TERM_EXAMPLE.format(tag=tag)
    rest = token[match.end():]
    if not rest.startswith(PROPERTY_SEPARATOR):
        raise InputRejected(f"Name the property after {tag} (for example {example})")
    rest = rest[len(PROPERTY_SEPARATOR):]
    if rest.endswith(MISSING_OPERATOR):
        raise InputRejected(f"{tag} always has a figure; compare it (for example {example})")
    if len(split_property_segments(rest)) > 1:
        raise InputRejected(f"Compare one figure per term (for example {example} {tag}:fat<30)")
    name, operator, value_text = _split_at_operator(rest)
    if operator == "":
        name = rest
    problem = _condition_problem("tag", name, operator, value_text)
    if problem != "":
        raise InputRejected(problem.replace("jogging:miles", f"{tag}:calories"))
    is_comparison = operator != PRESENT_OPERATOR and value_text not in EXTREME_KEYWORDS
    if is_comparison and (is_quoted(value_text) or parse_property_value(value_text).kind != VALUE_NUMBER):
        raise InputRejected(f"Compare {tag} with a number (for example {example})")
    return PropertyCondition(tag=tag, name=name, operator=operator, value_text=value_text, chained=())


def property_term_problem(token: str) -> str:
    """What is wrong with a super tag term, said so the user can fix it; "" for nothing.
    The rule editor's parser reports it as its own error (tag_ontology)."""
    parts = _chain_parts(token)
    for part in parts:
        problem = _condition_problem(*part)
        if problem != "":
            return problem
    return _chain_problem(parts)


def _split_property_term(token: str) -> Tuple[str, str, str, str]:
    """A term's tag, property name, operator and value, as written."""
    if has_property_syntax(token):
        tag, rest = token.split(PROPERTY_SEPARATOR, 1)
        if rest.endswith(MISSING_OPERATOR):
            return tag, rest[:-1], MISSING_OPERATOR, ""
        name, operator, value = _split_at_operator(rest)
        if operator == "":
            return tag, rest, PRESENT_OPERATOR, ""
        return tag, name, operator, value
    tag, operator, value = _split_at_operator(token)
    if _is_implicit_term(operator, value):
        return tag, IMPLICIT_PROPERTY, operator, value
    raise InputRejected(f"{token} is not a property search (for example jogging:miles>2)")


def _condition_problem(tag: str, name: str, operator: str, value_text: str) -> str:
    if tag == RESERVED_OR:
        return "OR is reserved and cannot be used as a tag"
    if tag == "" or any(mark in tag for mark in (PROPERTY_ASSIGNMENT, PROPERTY_SEPARATOR)) or tag.startswith(META_TAG_PREFIX):
        return f"Name the tag before the property (for example jogging:miles>2), not {tag!r}"
    return _name_and_value_problem(name, operator, value_text)


def _name_and_value_problem(name: str, operator: str, value_text: str) -> str:
    if not is_property_name(name):
        return "A property name starts with a letter (for example jogging:miles>2)"
    if value_text in EXTREME_KEYWORDS and operator != "=":
        return f"{value_text} goes after = (for example jogging:miles={value_text})"
    if operator not in (MISSING_OPERATOR, PRESENT_OPERATOR) and unquote_value(value_text).strip() == "":
        return f"Write a value after {operator} (for example jogging:miles{operator}2)"
    if is_quoted(value_text):
        return ""
    if any(mark in value_text for mark in ("<", ">", "?", PROPERTY_ASSIGNMENT)):
        return 'Quote a value holding <, >, ? or = (for example book:title="a=b")'
    return ""


def value_satisfies(value: PropertyValue, condition: PropertyCondition) -> bool:
    """Whether a note's value meets a comparison. Values of another kind are skipped
    (miles=far never answers miles>2); a query's unit, when it has one, must match."""
    if condition.operator in (MISSING_OPERATOR, PRESENT_OPERATOR) or condition.is_extreme:
        raise ValueError("Only comparisons compare values")
    if condition.is_text_match:
        return text_term_matches(condition.compared_text, value.text.casefold())
    wanted = parse_property_value(condition.compared_text)
    if value.kind != wanted.kind:
        return False
    if wanted.unit != "" and value.unit != wanted.unit:
        return False
    actual_key = value.sort_key
    wanted_key = wanted.sort_key
    if condition.operator == "=":
        return actual_key == wanted_key
    if condition.operator == ">":
        return actual_key > wanted_key
    if condition.operator == "<":
        return actual_key < wanted_key
    if condition.operator == ">=":
        return actual_key >= wanted_key
    assert condition.operator == "<=", condition.operator
    return actual_key <= wanted_key


# --- Suggestions --------------------------------------------------------------------

# "1 note", "2 notes", by whether the count is one.
_NOTE_NOUNS = {True: "note", False: "notes"}
PROPERTY_SUGGESTIONS_IN_TAG_BAR = "tag-bar"
PROPERTY_SUGGESTIONS_IN_SEARCH = "search"
# A rule's condition in Edit Tag Relationships: read as a search reads, without MAX/MIN.
PROPERTY_SUGGESTIONS_IN_RULE = "rule"
PROPERTY_SUGGESTION_PLACES = frozenset({
    PROPERTY_SUGGESTIONS_IN_TAG_BAR, PROPERTY_SUGGESTIONS_IN_SEARCH, PROPERTY_SUGGESTIONS_IN_RULE,
})
# A number and the start of its unit: 10, 10m, -2.5k.
_NUMBER_AND_PARTIAL_UNIT_RE = re.compile(r"^(?P<number>-?(?:\d+(?:\.\d+)?|\.\d+))(?P<unit>[A-Za-z%][A-Za-z%/]*)?$")


@dataclass(frozen=True, slots=True)
class PropertySuggestion:
    # What replaces the typed text (jogging:miles=), what the list shows (miles=), and
    # why it is suggested (shown when it is right-clicked).
    replacement: str
    label: str
    reasons: Tuple[str, ...]
    # How many notes use it (none for MAX and MIN).
    note_count: int


@dataclass(frozen=True, slots=True)
class PropertyCompletion:
    """What is being typed in a property: a name after a tag's colon (property_name
    None), or the unit after a value's number."""

    tag: str
    property_name: str | None
    # The typed start of the name or unit, and everything typed before it.
    partial: str
    before: str
    # A value's number, for the unit's label (5 for 5mg).
    number: str
    # Names the token already has (the tag bar never offers one twice).
    excluded_names: FrozenSet[str]
    # In the tag bar a chosen name gets its =, ready for the value.
    name_suffix: str
    # A search's = with no value yet (or MA, MI): MAX and MIN are offered.
    offers_extremes: bool
    # After =: the values notes give the property (partial is the value typed so far).
    offers_values: bool

    def suggestion(self, completed: str, notes_by_tag: Dict[str, int]) -> PropertySuggestion:
        reasons = tuple(
            f"On {count} {_NOTE_NOUNS[count == 1]} tagged {tag}"
            for tag, count in sorted(notes_by_tag.items(), key=lambda item: (-item[1], item[0]))
        )
        # A name gets its suffix (= in the tag bar); a unit shows with its number.
        note_count = sum(notes_by_tag.values())
        if self.property_name is None:
            label = f"{completed}{self.name_suffix}"
            return PropertySuggestion(
                replacement=f"{self.before}{label}", label=label, reasons=reasons, note_count=note_count,
            )
        return PropertySuggestion(
            replacement=f"{self.before}{completed}", label=f"{self.number}{completed}", reasons=reasons,
            note_count=note_count,
        )


def read_property_completion(typed: str, *, in_tag_bar: bool, offers_extremes: bool) -> PropertyCompletion | None:
    """The property name or unit being typed at the end of a tag-bar token
    (jogging:miles=3:du, drug:dosage=10m) or a search term (exercise:mi, drug:dosage>5m,
    date>5), or None when neither is."""
    if typed.startswith(META_TAG_PREFIX):
        return None
    if not in_tag_bar and is_tagless_property_term(typed):
        return _tagless_completion(typed, offers_extremes=offers_extremes)
    # In the tag bar a chosen name gets its =, ready for the value.
    name_suffix = ""
    if in_tag_bar:
        name_suffix = PROPERTY_ASSIGNMENT
    if has_property_syntax(typed):
        tag, rest = typed.split(PROPERTY_SEPARATOR, 1)
        if PROPERTY_ASSIGNMENT in tag:
            tag = tag.split(PROPERTY_ASSIGNMENT, 1)[0]
        # Suggestions follow the last property (jogging:miles=3:du, or in a search the
        # last condition of a chain, book:title="Dune":ye); names it has are not offered.
        segments = split_property_segments(rest)
        current = segments[-1]
        excluded = frozenset(_split_at_operator(segment)[0].casefold() for segment in segments[:-1])
        if in_tag_bar:
            name, operator, value = current.partition(PROPERTY_ASSIGNMENT)
        else:
            name, operator, value = _split_at_operator(current)
            # MAX and MIN go in a term of their own (_chain_problem).
            offers_extremes = offers_extremes and len(segments) == 1
        if operator == "":
            if name != "" and not is_property_name(name):
                return None
            return PropertyCompletion(
                tag=tag, property_name=None, partial=name, before=typed[: len(typed) - len(name)], number="",
                excluded_names=excluded, name_suffix=name_suffix, offers_extremes=False,
                offers_values=False,
            )
        if offers_extremes and operator == "=" and any(keyword.startswith(value) for keyword in EXTREME_KEYWORDS):
            return PropertyCompletion(
                tag=tag, property_name=name, partial=value, before=typed[: len(typed) - len(value)], number="",
                excluded_names=frozenset(), name_suffix="", offers_extremes=True,
                offers_values=True,
            )
        return _unit_or_value_completion(typed, tag=tag, property_name=name, operator=operator, value=value)
    if in_tag_bar:
        return None
    name, operator, value = _split_at_operator(typed)
    if operator not in IMPLICIT_COMPARISON_OPERATORS or name == "":
        return None
    return _unit_completion(typed, tag=name, property_name=IMPLICIT_PROPERTY, value=value)


# A search's `:` (any tag): property names used anywhere (`:ver`), then MAX and MIN or a
# value's unit, as after a tag's colon.
def _tagless_completion(typed: str, *, offers_extremes: bool) -> PropertyCompletion | None:
    # In a chain (:foo="bar":ba), the last condition.
    segments = split_property_segments(typed[len(PROPERTY_SEPARATOR):])
    rest = segments[-1]
    excluded = frozenset(_split_at_operator(segment)[0].casefold() for segment in segments[:-1])
    offers_extremes = offers_extremes and len(segments) == 1
    name, operator, value = _split_at_operator(rest)
    if operator == "":
        if rest != "" and not is_property_name(rest):
            return None
        return PropertyCompletion(
            tag=ANY_TAG, property_name=None, partial=rest, before=typed[: len(typed) - len(rest)], number="",
            excluded_names=excluded, name_suffix="", offers_extremes=False, offers_values=False,
        )
    if offers_extremes and operator == "=" and any(keyword.startswith(value) for keyword in EXTREME_KEYWORDS):
        return PropertyCompletion(
            tag=ANY_TAG, property_name=name, partial=value, before=typed[: len(typed) - len(value)], number="",
            excluded_names=frozenset(), name_suffix="", offers_extremes=True, offers_values=True,
        )
    return _unit_or_value_completion(typed, tag=ANY_TAG, property_name=name, operator=operator, value=value)


def _unit_or_value_completion(
    typed: str, *, tag: str, property_name: str, operator: str, value: str,
) -> PropertyCompletion | None:
    """After =, the values notes give the property (book:title=, :author="Le), then a
    number's units; after a comparison, a number's units (drug:dosage>10m)."""
    if operator != PROPERTY_ASSIGNMENT or not is_property_name(property_name):
        return _unit_completion(typed, tag=tag, property_name=property_name, value=value)
    # After = a number's units follow the values (number names the number typed).
    number = ""
    match = _NUMBER_AND_PARTIAL_UNIT_RE.match(value)
    if match is not None:
        number = match.group("number")
    return PropertyCompletion(
        tag=tag, property_name=property_name, partial=value, before=typed[: len(typed) - len(value)],
        number=number, excluded_names=frozenset(), name_suffix="", offers_extremes=False, offers_values=True,
    )


def value_completes(text: str, partial: str) -> bool:
    """Whether a property's value (as written, unquoted) completes a typed value: a bare
    one by its start, a quoted one anywhere, as a quoted value searches (decided
    2026-10-31). Never the value exactly as typed."""
    written = quote_value(text)
    if written == partial:
        return False
    typed = unquote_value(partial).casefold()
    if is_quoted(partial):
        return typed in text.casefold()
    return text.casefold().startswith(typed)


def _split_at_operator(text: str) -> Tuple[str, str, str]:
    """A term's name, its first operator and the value after it (which may be quoted and
    hold operators of its own); the operator "" when there is none."""
    index = find_outside_values(text, _OPERATOR_CHARACTERS, 0)
    if index == -1:
        return text, "", ""
    for operator in COMPARISON_OPERATORS:
        if text.startswith(operator, index):
            return text[:index], operator, text[index + len(operator):]
    raise AssertionError(f"{text[index]!r} starts no comparison operator")


def _unit_completion(typed: str, *, tag: str, property_name: str, value: str) -> PropertyCompletion | None:
    match = _NUMBER_AND_PARTIAL_UNIT_RE.match(value)
    if match is None or not is_property_name(property_name):
        return None
    partial = match.group("unit")
    if partial is None:
        partial = ""
    return PropertyCompletion(
        tag=tag, property_name=property_name, partial=partial, before=typed[: len(typed) - len(partial)],
        number=match.group("number"), excluded_names=frozenset(), name_suffix="", offers_extremes=False,
        offers_values=False,
    )


def condition_holds(
    condition: PropertyCondition, *, values: Mapping[Tuple[str, str], PropertyValue],
    own_tag_names: FrozenSet[str], tag_names: FrozenSet[str],
) -> bool:
    """Whether one note's values meet a super tag term, as search and rules read it.
    values: the note's own values by casefolded (tag, property); own_tag_names: the
    casefolded names of the tags written on the note; tag_names: the term's tag and every
    tag implying it. The term has its property (jogging:miles), lacks it on a tag of its
    own (jogging:miles?), or has a value that compares (jogging:miles>2); any one value
    is enough. MAX and MIN need the property; which notes hold the extreme is decided
    across the notes found."""
    if condition.chained:
        # One tag meets every condition of the term (:foo="bar":baz>3).
        return any(
            all(_holds_on_tag(link, tag_name, values) for link in condition.links) for tag_name in tag_names
        )
    keys = [(tag_name, condition.key[1]) for tag_name in tag_names if (tag_name, condition.key[1]) in values]
    if condition.operator == MISSING_OPERATOR:
        return bool(own_tag_names & tag_names) and not keys
    if condition.operator == PRESENT_OPERATOR or condition.is_extreme:
        return len(keys) > 0
    return any(value_satisfies(values[key], condition) for key in keys)


def _holds_on_tag(
    condition: PropertyCondition, tag_name: str, values: Mapping[Tuple[str, str], PropertyValue],
) -> bool:
    """Whether one tag's value meets one condition of a chain: present, or comparing. A
    chain holds no ?, MAX or MIN (_chain_problem)."""
    assert condition.operator != MISSING_OPERATOR and not condition.is_extreme, condition
    key = (tag_name, condition.key[1])
    if key not in values:
        return False
    if condition.operator == PRESENT_OPERATOR:
        return True
    return value_satisfies(values[key], condition)
