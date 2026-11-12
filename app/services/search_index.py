from __future__ import annotations

from collections import Counter
import dataclasses
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
import re
from threading import RLock
import time
from typing import Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Set, Tuple, TypeVar

from app.services import safe_log

from app.services.quoted_values import canonical_valued_token, quote_value, token_end, unquote_value
from app.services.content_formatting import (
    _tokenize_tag_bar, _unwrap_tag_token, is_known_meta_tag_term, list_known_meta_tag_terms,
)
from app.services.shared_sets import SharedSetColumn, SharedSets
from app.services.search_query import SearchClause, comment_term_words, is_comment_term, parse_search_query
from app.services.tag_term_matching import tag_term_matches_prefix
from app.services.tag_characters import normalize_text
from app.services.tag_properties import (
    ANY_TAG,
    IMPLICIT_PROPERTY,
    MISSING_OPERATOR,
    PRESENT_OPERATOR,
    PROPERTY_SUGGESTION_PLACES,
    PROPERTY_SUGGESTIONS_IN_SEARCH,
    PROPERTY_SUGGESTIONS_IN_TAG_BAR,
    MAX_KEYWORD,
    MIN_KEYWORD,
    EXTREME_KEYWORDS,
    VALUE_KIND_ORDER,
    VALUE_NUMBER,
    VALUE_TEXT,
    PropertyCompletion,
    PropertySuggestion,
    read_property_completion,
    value_completes,
    PROPERTY_ASSIGNMENT,
    PropertyCondition,
    PropertyValue,
    condition_holds,
    is_property_term,
    is_stats_term,
    is_tagless_property_term,
    property_term_tag,
    tag_part_of_token,
    token_properties,
    value_satisfies,
)
from app.services.link_titles import link_title_store
from app.services.note_datetime import DATETIME_TAG, is_datetime_tag_term
from app.services.ontology_rules_store import get_ontology_if_ready
from app.services.tag_ontology import FOLDER_TAG_END, TagOntology
from app.services.search_text import (
    append_link_titles_casefold,
    build_searchable_base_text_casefold,
    list_link_title_urls,
    tag_bar_comments,
)
from app.services.file_registry import file_registry
from app.services.file_text_search import file_texts, is_searchable_file_name
from app.services.text_terms import comment_term_matches, text_term_matches
from app.utils.time_units import MS_PER_SECOND


_QUOTE_CHARS = {"'", '"'}
# A backslash and the character it escapes.
_ESCAPE_SEQUENCE_LENGTH = 2
# Walking one anchor-note term in Python costs roughly this many times less
# than one C set intersection per suggestion candidate (measured on 107k notes).
SUGGESTION_INTERSECT_COST_RATIO = 8


@dataclass(frozen=True, slots=True)
class _SearchSuggestionContext:
    anchors: Tuple[str, ...]
    partial_prefix: str | None
    completed_clause: str
    is_exclusion: bool


def _add_posting(postings: Dict[str, Set[int]], key: str, note_int_id: int) -> None:
    if key not in postings:
        postings[key] = set()
    postings[key].add(note_int_id)


class _NoteCounts:
    """How many live notes carry each key, for the postings only ever counted: a set
    of note ids per tag held about 100 MB in a 107,500-note namespace (2026-10-19).
    Each note adds a key once and removes it once, so a count never goes below one;
    a key goes with its last note."""

    __slots__ = ("_counts",)

    def __init__(self) -> None:
        self._counts: Dict[str, int] = {}

    def add(self, key: str) -> None:
        if key in self._counts:
            self._counts[key] += 1
        else:
            self._counts[key] = 1

    def remove(self, key: str) -> None:
        count = self._counts[key]
        assert count > 0, f"no note carries {key!r}"
        if count == 1:
            del self._counts[key]
        else:
            self._counts[key] = count - 1

    def count(self, key: str) -> int:
        return self._counts[key]

    def __contains__(self, key: str) -> bool:
        return key in self._counts

    def items(self) -> Iterable[tuple[str, int]]:
        return self._counts.items()

    def __len__(self) -> int:
        return len(self._counts)

    def clear(self) -> None:
        self._counts.clear()


# A tag's name and its value: @code=python is the tag @code with the value python.
TAG_VALUE_SEPARATOR = "="


def tag_family_of(term: str) -> str:
    """The tag a term is a member of: itself, or for one carrying a value (jogging=3) the tag
    the value is on (jogging). The tag bar ranks a tag over all its notes, whatever their values
    (docs/design/tag-properties.md, "Last time's values")."""
    return term.split(TAG_VALUE_SEPARATOR, 1)[0]


def tag_family_prefix(tag_casefold: str) -> str | None:
    """What every valued member of a tag's family starts with ("@code=" for @code), or
    None for a tag that carries a value itself (it matches only itself)."""
    if TAG_VALUE_SEPARATOR in tag_casefold:
        return None
    return f"{tag_casefold}{TAG_VALUE_SEPARATOR}"


# Up to this many anchors, a term's co-occurrence is found from intersections of its
# notes with each group of anchors, in C; beyond it, groups outnumber the notes and each
# note's anchors are collected one by one. Both give the same answer.
_MAX_ANCHORS_BY_GROUPS = 6


def _most_anchors_cooccurrence(shared_by_anchor: Mapping[str, Set[int]]) -> TagCooccurrence | None:
    """The most anchors any of a term's notes carries, how many notes carry that many,
    and which anchors they carry. shared_by_anchor: each anchor's notes that are the
    term's (none empty). From the largest group of anchors down, the first size whose
    notes are shared is the most: a note there carries exactly that group (it carries no
    more), so each counts in one group and the groups' counts add up. Collecting each
    note's anchors one by one in Python took 0.3 s for a 50,000-note anchor (2026-10-20)."""
    if not shared_by_anchor:
        return None
    anchors = sorted(shared_by_anchor)
    if len(anchors) > _MAX_ANCHORS_BY_GROUPS:
        anchors_by_note: Dict[int, Set[str]] = {}
        for anchor in anchors:
            for note_id in shared_by_anchor[anchor]:
                if note_id not in anchors_by_note:
                    anchors_by_note[note_id] = set()
                anchors_by_note[note_id].add(anchor)
        most_anchors = max(len(note_anchors) for note_anchors in anchors_by_note.values())
        at_most = [frozenset(note_anchors) for note_anchors in anchors_by_note.values()
                   if len(note_anchors) == most_anchors]
        return TagCooccurrence(anchor_count=most_anchors, note_count=len(at_most), anchor_sets=frozenset(at_most))
    for size in range(len(anchors), 0, -1):
        notes_by_group: Dict[FrozenSet[str], int] = {}
        for group in combinations(anchors, size):
            notes = shared_by_anchor[group[0]]
            for anchor in group[1:]:
                notes = notes & shared_by_anchor[anchor]
                if not notes:
                    break
            if notes:
                notes_by_group[frozenset(group)] = len(notes)
        if notes_by_group:
            return TagCooccurrence(
                anchor_count=size, note_count=sum(notes_by_group.values()), anchor_sets=frozenset(notes_by_group),
            )
    raise AssertionError("every anchor shares a note, so the single anchors do")


def _carries_tag_family(tag_terms_casefold: FrozenSet[str], tag_casefold: str) -> bool:
    """Whether a note's tags include the tag or, for a tag without a value, any tag=value."""
    if tag_casefold in tag_terms_casefold:
        return True
    prefix = tag_family_prefix(tag_casefold)
    if prefix is None:
        return False
    return any(term.startswith(prefix) for term in tag_terms_casefold)


_PostingKey = TypeVar("_PostingKey")
# What MAX and MIN keep of a property's values.
_EXTREME_PICKS = {MAX_KEYWORD: max, MIN_KEYWORD: min}
_EXTREME_WORDS = {MAX_KEYWORD: "largest", MIN_KEYWORD: "smallest"}
# A stats term being typed in a search: @sum:ca, or @sum:calories=MA for MAX and MIN.
_TYPED_STATS_TERM_RE = re.compile(
    r"(?P<tag>@(?:sum|avg|min|max|count)):(?P<name>[^\W\d_][^:=<>?]*|)(?:(?P<assignment>=)(?P<partial>[A-Z]*))?",
    re.IGNORECASE,
)
# The figure a note's stats tag shows for a term (subtree_stats.stats_figure_values): its
# numbers per unit, () for a dash, None when the note shows no such figure. It walks the
# note's subtree in the note store, so the index calls it outside its own lock.
StatsFigureReader = Callable[[str, PropertyCondition], Optional[Tuple[PropertyValue, ...]]]


@dataclass(frozen=True, slots=True)
class InheritedValues:
    """The super tag values a note inherits, as its tags (docs/ui/search-semantics.md, Super
    Tag Searches; agreed 2026-11-01): from_ancestors, its ancestors' values by casefolded
    (tag, property), the nearest ancestor's where several give one. Embeds and links pass
    none (2026-11-03). A note's own value hides an ancestor's for the same (tag, property)."""
    from_ancestors: Mapping[Tuple[str, str], PropertyValue]


NOTHING_INHERITED = InheritedValues(from_ancestors={})
# The values notes inherit, read from the note store's tree outside the index's lock, as
# stats figures are: an InheritedValues for each note asked about.
InheritedValuesReader = Callable[[FrozenSet[str]], Mapping[str, InheritedValues]]


def _note_noun(count: int) -> str:
    if count == 1:
        return "note"
    return "notes"


# A property name being completed, or None while the name itself is typed.
def _casefold_name(property_name: str | None) -> str | None:
    if property_name is None:
        return None
    return property_name.casefold()


def _figure_meets(figure: Optional[Tuple[PropertyValue, ...]], condition: PropertyCondition) -> bool:
    """Whether a stats figure meets a term: shown at all (`@sum:calories`), or a number of it
    compares (`@sum:calories>2000`; a unit in the term must match). A dash never compares."""
    if figure is None:
        return False
    if condition.operator == PRESENT_OPERATOR:
        return True
    return any(value_satisfies(value, condition) for value in figure)


@dataclass(frozen=True, slots=True)
class _NoteValues:
    """The values of a clause's found notes: their own (from the index) and what they inherit
    (from the note tree; empty when the clause reads no values)."""
    own_values: Mapping[str, Mapping[Tuple[str, str], PropertyValue]]
    inherited: Mapping[str, InheritedValues]

    def maps(self, note_id: str) -> Tuple[Mapping[Tuple[str, str], PropertyValue], ...]:
        """The note's values, a term holding when one map meets it: its own over its
        ancestors' (the nearest value wins)."""
        inherited = self.inherited[note_id]
        return ({**inherited.from_ancestors, **self.own_values[note_id]},)


def _notes_with_extreme_value(found_by_note: Mapping[str, List[PropertyValue]], condition: PropertyCondition) -> Set[str]:
    """Of these notes (each with the values of the term's property it has), those holding the
    largest (MAX) or smallest (MIN), ties included. Values are compared within one kind: the
    kind most of the values are (numbers first on a tie); units are labels and do not count."""
    if not found_by_note:
        return set()
    kind_counts = Counter(value.kind for found in found_by_note.values() for value in found)
    kind = max(VALUE_KIND_ORDER, key=lambda candidate: (kind_counts[candidate], -VALUE_KIND_ORDER.index(candidate)))
    pick = _EXTREME_PICKS[condition.value_text]
    best_by_note = {
        note_id: pick(value.sort_key for value in found if value.kind == kind)
        for note_id, found in found_by_note.items()
        if any(value.kind == kind for value in found)
    }
    extreme = pick(best_by_note.values())
    return {note_id for note_id, best in best_by_note.items() if best == extreme}


def _posting_or_empty(postings: Mapping[_PostingKey, Set[int]], key: _PostingKey) -> Set[int]:
    """The notes with this term; a term no note has has no posting."""
    if key not in postings:  # shockharness: ignore[DEF002] reason="a term no note has has no posting"
        return set()
    return postings[key]


def _parse_search_suggestion_context(raw_input: str) -> _SearchSuggestionContext:
    if not isinstance(raw_input, str):
        raise TypeError(f"raw_input must be a string, got {type(raw_input)}")

    anchors: List[str] = []
    partial_prefix: Optional[str] = None
    clause_term_count = 0
    clause_start = 0
    has_trailing_whitespace = len(raw_input) > 0 and raw_input[-1].isspace()

    index = 0
    length = len(raw_input)
    while index < length:
        while index < length and raw_input[index].isspace():
            index += 1
        if index >= length:
            break

        term_start = index
        prefix: Optional[str] = None
        if raw_input[index] in ("+", "-"):
            prefix = raw_input[index]
            index += 1
            if index >= length or raw_input[index].isspace():
                return _SearchSuggestionContext(tuple(anchors), None, '', False)

        if raw_input[index] in _QUOTE_CHARS:
            quote_char = raw_input[index]
            index += 1
            closed = False
            while index < length:
                char = raw_input[index]
                if char == quote_char:
                    closed = True
                    index += 1
                    break
                if char == "\\" and index + 1 < length:
                    next_char = raw_input[index + 1]
                    if next_char in (quote_char, "\\"):
                        index += _ESCAPE_SEQUENCE_LENGTH
                        continue
                index += 1
            if not closed:
                return _SearchSuggestionContext(tuple(anchors), None, '', False)
            clause_term_count += 1
            continue

        start = index
        index = token_end(raw_input, start)

        token = raw_input[start:index]
        if token == "":
            continue

        if token == "OR":
            if prefix is not None:
                return _SearchSuggestionContext(tuple(anchors), None, '', False)
            if clause_term_count == 0:
                return _SearchSuggestionContext(tuple(anchors), None, '', False)
            if index >= length and not raw_input[-1].isspace():
                return _SearchSuggestionContext(tuple(anchors), None, '', False)
            anchors = []
            clause_term_count = 0
            clause_start = index
            continue

        is_partial = index >= length and not raw_input[-1].isspace()
        if is_partial:
            # Typing a property term (jogging:mi, date>2, @sum:ca, :ver) suggests no tags.
            if is_property_term(token) or is_stats_term(token) or is_tagless_property_term(token):
                return _SearchSuggestionContext(tuple(anchors), None, '', False)
            return _SearchSuggestionContext(
                tuple(anchors), token, raw_input[clause_start:term_start], prefix == '-',
            )

        if prefix == "-" or is_stats_term(token) or is_tagless_property_term(token):
            # A stats term (@sum:calories>2000) anchors nothing: its tag is a meta tag; nor
            # does a property on any tag (:version), which has none.
            clause_term_count += 1
            continue
        # A property term anchors suggestions by its tag: jogging:miles>2 is jogging.
        if is_property_term(token):
            token = property_term_tag(token)
        anchors.append(token)
        clause_term_count += 1

    if partial_prefix is None and has_trailing_whitespace:
        partial_prefix = ""
    return _SearchSuggestionContext(tuple(anchors), partial_prefix, raw_input[clause_start:], False)


def _parse_search_query_for_suggestions(raw_input: str) -> tuple[Tuple[str, ...], Optional[str]]:
    context = _parse_search_suggestion_context(raw_input)
    return context.anchors, context.partial_prefix


@dataclass(frozen=True, slots=True)
class TagCooccurrence:
    """A tag's notes that carry the most of some anchor tags, as tag suggestions rank them."""

    anchor_count: int
    note_count: int
    # The anchors (casefolded) those notes carry; one set when they all carry the same ones.
    anchor_sets: FrozenSet[FrozenSet[str]]

    def __post_init__(self) -> None:
        if self.anchor_count <= 0 or self.note_count <= 0:
            raise ValueError("A tag co-occurrence needs at least one anchor and one note")
        if not self.anchor_sets or any(len(anchors) != self.anchor_count for anchors in self.anchor_sets):
            raise ValueError("Every anchor set holds anchor_count anchors")


@dataclass(frozen=True, slots=True)
class SearchSuggestionFacts:
    """What the search-bar ranking used for some shown suggestions, to say why each is there."""

    partial_prefix: str
    # Tags (and words) already typed in the clause; with them the ranking is by co-occurrence.
    anchors: Tuple[str, ...]
    has_completed_clause: bool
    is_exclusion: bool
    # Notes the search so far finds (every note when nothing precedes the typed tag).
    matching_note_count: int
    note_counts: Dict[str, int]
    matching_counts: Dict[str, int]
    cooccurrences: Dict[str, TagCooccurrence]


@dataclass(frozen=True, slots=True)
class SearchRecord:
    note_id: str
    content_text: str
    tags: str
    tag_terms: FrozenSet[str]


def extract_ordered_tags_for_search(tags: str) -> tuple[str, ...]:
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")
    if tags == "":
        return ()

    ordered_terms: list[str] = []
    seen_terms: set[str] = set()
    for token in _tokenize_tag_bar(tags):
        base, wrapper = _unwrap_tag_token(token)
        if wrapper is None:
            # A tag with properties is its tag: jogging:miles=3 is jogging. A quoted value
            # is the same value bare when it needs no quotes: author="Le-Guin" is author=Le-Guin.
            base = canonical_valued_token(tag_part_of_token(base))
            if base != "OR" and base not in seen_terms:
                seen_terms.add(base)
                ordered_terms.append(base)
            continue
        for inner in base.split():
            if inner and inner != "OR" and inner not in seen_terms:
                seen_terms.add(inner)
                ordered_terms.append(inner)
    return tuple(ordered_terms)


def tag_bar_values(tags: str) -> Tuple[FrozenSet[str], Dict[Tuple[str, str], PropertyValue]]:
    """A tag bar's written tag names (casefolded, without values) and its super tag values
    by casefolded (tag, property). Meta tags and tags inside scopes have none."""
    own_tag_names: Set[str] = set()
    values: Dict[Tuple[str, str], PropertyValue] = {}
    for token in _tokenize_tag_bar(tags):
        base, wrapper = _unwrap_tag_token(token)
        if wrapper is not None or base.startswith("@"):
            continue
        tag_name, token_values = token_properties(base)
        own_tag_names.add(tag_name)
        for property_name, value in token_values.items():
            values[(tag_name, property_name)] = value
    return frozenset(own_tag_names), values


def own_value_token(tags: str, tag_casefold: str) -> str:
    """The token, as written, that gives a tag its values on a note's own tag line
    (`breakfast-burrito:calories=800:fat=10g`), or '' when none does. Meta tags and tags
    inside scopes have no own values, as in tag_bar_values."""
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")
    for token in _tokenize_tag_bar(tags):
        base, wrapper = _unwrap_tag_token(token)
        if wrapper is not None or base.startswith("@"):
            continue
        tag_name, token_values = token_properties(base)
        if tag_name == tag_casefold and token_values:
            return base
    return ""


def extract_ordered_tags_for_agent(tags: str) -> tuple[str, ...]:
    """The tags the AI is shown for a note: as for search, but a super tag whole with its
    values (jogging:miles=3), so the AI sees them and can propose its own."""
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")
    ordered: list[str] = []
    for token in _tokenize_tag_bar(tags):
        base, wrapper = _unwrap_tag_token(token)
        if wrapper is None and base != "OR" and base not in ordered:
            ordered.append(base)
            continue
        for inner in base.split():
            if inner and inner != "OR" and inner not in ordered:
                ordered.append(inner)
    return tuple(ordered)


def extract_tags_for_search(tags: str) -> FrozenSet[str]:
    return frozenset(extract_ordered_tags_for_search(tags))


class SearchIndex:
    """In-memory search index (tags + trigrams) built from current note content."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._revision = 0
        # Attached by the note store once it has loaded (attach_stats_reader).
        self._stats_reader: StatsFigureReader | None = None
        # And the values notes inherit (attach_inherited_values_reader).
        self._inherited_values_reader: InheritedValuesReader | None = None

        self._uuid_to_id: Dict[str, int] = {}
        self._id_to_uuid: List[str] = []
        self._alive: Set[int] = set()

        self._note_text_casefold: List[str] = []
        # The files whose text a note is also searched by (file_text_search.py: PDFs it shows),
        # for the notes showing some.
        self._note_text_file_ids: Dict[int, Tuple[str, ...]] = {}
        # Each tag-bar comment of the notes with some, casefolded: what a comment term reads.
        self._note_comments_casefold: Dict[int, Tuple[str, ...]] = {}
        # Notes are also searchable by the cached titles of URLs written in them.
        # A title can arrive or disappear later, so keep each note's URLs (and,
        # for notes with URLs, its text without titles) to recompose its text.
        # The per-note sets share one copy of each distinct set (SharedSets). It comes
        # first, so the memory breakdown counts the sets under its own name.
        self._shared_tag_sets = SharedSets()
        self._note_link_title_urls = SharedSetColumn(self._shared_tag_sets)
        self._link_title_url_notes: Dict[str, Set[int]] = {}
        self._note_base_text_casefold: Dict[int, str] = {}
        self._note_explicit_tag_terms = SharedSetColumn(self._shared_tag_sets)
        self._note_raw_tag_terms = SharedSetColumn(self._shared_tag_sets)
        self._note_tag_terms = SharedSetColumn(self._shared_tag_sets)
        self._note_tag_terms_casefold = SharedSetColumn(self._shared_tag_sets)
        # Only counted (frequencies, suggestion spellings): counts, not sets of notes.
        self._explicit_tag_notes = _NoteCounts()
        self._explicit_tag_notes_casefold = _NoteCounts()
        self._raw_tag_notes_casefold = _NoteCounts()
        # The same two counts by tag family (tag_family_of): jogging=3 and jogging=5 count as jogging,
        # each note once.
        self._explicit_tag_family_notes = _NoteCounts()
        self._raw_tag_family_notes_casefold = _NoteCounts()
        self._tag_notes = _NoteCounts()
        self._tag_notes_casefold: Dict[str, Set[int]] = {}
        # Each tag family's valued members (@code: @code=python, @code=sql), as
        # tag_family_prefix defines them. Scanning every tag for every candidate made
        # each suggestion after a broad tag take most of a second (2026-10-20).
        self._tag_family_members: Dict[str, List[str]] = {}

        # Each note's own property values (docs/design/tag-properties.md), by casefolded
        # tag and property name: jogging:miles=3 is ("jogging", "miles"). Only notes
        # with values are kept. What a note inherits is read from the note tree when a
        # search asks (attach_inherited_values_reader).
        self._note_properties: Dict[int, Dict[Tuple[str, str], PropertyValue]] = {}
        self._property_notes: Dict[Tuple[str, str], Set[int]] = {}
        # Upward search: a property term about a tag also reads the values of every tag
        # implying it (exercise:miles>2 finds jogging:miles=3). By casefolded tag, the
        # casefolded tags implying it, for the ontology they were read from.
        self._implying_ontology: TagOntology | None = None
        self._implying_tags_by_tag: Dict[str, Set[str]] = {}
        # And the other way, for suggestions in the tag bar: the tags each tag implies
        # (jogging: exercise), whose property names it can use.
        self._implied_tags_by_tag: Dict[str, Set[str]] = {}

        self._result_cache: Dict[str, tuple[int, FrozenSet[str]]] = {}
        self._untagged_result_cache: tuple[int, FrozenSet[str]] | None = None

    def rebuild(
        self,
        records: Iterable[SearchRecord],
        *,
        raw_tag_terms_by_id: Dict[str, FrozenSet[str]],
        progress_update: Callable[[int], None],
        progress_interval: int,
    ) -> Dict[str, float]:
        """Indexes the records in place of what it held; returns the seconds spent on
        the notes' text and on their tags, for the Memory Usage dialog's Last unlock."""
        if progress_interval <= 0:
            raise ValueError("progress_interval must be > 0")
        t0 = time.perf_counter()
        materialized = list(records)
        record_ids = {record.note_id for record in materialized}
        if record_ids != set(raw_tag_terms_by_id):
            raise ValueError("raw_tag_terms_by_id must contain exactly one entry per search record")
        with self._lock:
            self._uuid_to_id.clear()
            self._id_to_uuid.clear()
            self._alive.clear()
            self._note_text_casefold.clear()
            self._note_comments_casefold.clear()
            self._note_link_title_urls.clear()
            self._link_title_url_notes.clear()
            self._note_base_text_casefold.clear()
            self._note_explicit_tag_terms.clear()
            self._note_raw_tag_terms.clear()
            self._note_tag_terms.clear()
            self._note_tag_terms_casefold.clear()
            self._explicit_tag_notes.clear()
            self._explicit_tag_notes_casefold.clear()
            self._raw_tag_notes_casefold.clear()
            self._explicit_tag_family_notes.clear()
            self._raw_tag_family_notes_casefold.clear()
            self._tag_notes.clear()
            self._tag_notes_casefold.clear()
            self._tag_family_members.clear()
            self._note_properties.clear()
            self._property_notes.clear()
            self._result_cache.clear()

            self._revision += 1

            processed = 0
            last_reported = 0
            # Rebuild-local memos: notes repeat tag strings, and inherited tag
            # sets repeat the same terms, so parse and casefold each only once.
            explicit_terms_by_tags: Dict[str, FrozenSet[str]] = {}
            casefold_by_term: Dict[str, str] = {}
            text_seconds = 0.0
            tag_seconds = 0.0
            for record in materialized:
                step_started = time.perf_counter()
                if record.tags not in explicit_terms_by_tags:
                    explicit_terms_by_tags[record.tags] = extract_tags_for_search(record.tags)
                explicit_tag_terms = explicit_terms_by_tags[record.tags]
                note_int_id = self._insert_new_locked(
                    record.note_id,
                    explicit_tag_terms,
                    raw_tag_terms_by_id[record.note_id],
                    record.tag_terms,
                    casefold_by_term,
                )
                text_started = time.perf_counter()
                tag_seconds += text_started - step_started
                self._set_note_text_locked(note_int_id, record.content_text, record.tags)
                self._set_note_properties_locked(note_int_id, record.tags)
                text_seconds += time.perf_counter() - text_started
                processed += 1
                if processed - last_reported >= progress_interval:
                    last_reported = processed
                    progress_update(processed)

            if processed != last_reported:
                progress_update(processed)

        elapsed_ms = (time.perf_counter() - t0) * MS_PER_SECOND
        safe_log.log_event(
            "INFO", "search.index.rebuild",
            elapsed_ms=elapsed_ms, notes=len(materialized), unique_tag_terms=len(self._tag_notes), revision=self._revision,
        )
        return {"search index: note text": text_seconds, "search index: tags": tag_seconds}

    def upsert(
        self,
        *,
        note_id: str,
        content_text: str,
        tags: str,
        raw_tag_terms: FrozenSet[str],
        tag_terms: FrozenSet[str],
    ) -> None:
        t0 = time.perf_counter()
        with self._lock:
            if note_id in self._uuid_to_id:
                note_int_id = self._uuid_to_id[note_id]
                if note_int_id not in self._alive:
                    # Notes can be deleted and later restored (undo/redo) with the same UUID.
                    # Treat this as a revive instead of an error.
                    self._alive.add(note_int_id)
                self._update_existing_locked(
                    note_int_id,
                    content_text,
                    tags,
                    raw_tag_terms,
                    tag_terms,
                )
            else:
                note_int_id = self._insert_new_locked(
                    note_id,
                    extract_tags_for_search(tags),
                    raw_tag_terms,
                    tag_terms,
                    {},
                )
                self._set_note_text_locked(note_int_id, content_text, tags)
                self._set_note_properties_locked(note_int_id, tags)

            self._revision += 1
            self._result_cache.clear()

        elapsed_ms = (time.perf_counter() - t0) * MS_PER_SECOND
        safe_log.log_event(
            "INFO", "search.index.upsert",
            elapsed_ms=elapsed_ms, revision=self._revision,
        )

    def refresh_link_titles(self, urls: FrozenSet[str]) -> None:
        """Recompose the text of notes containing these URLs after their cached titles changed."""
        if not isinstance(urls, frozenset):
            raise TypeError("refresh_link_titles requires a frozenset of normalized URLs")
        with self._lock:
            note_int_ids: Set[int] = set()
            for url in urls:
                if url in self._link_title_url_notes:
                    note_int_ids |= self._link_title_url_notes[url]
            if not note_int_ids:
                return
            for note_int_id in note_int_ids:
                assert note_int_id in self._alive, "deleted notes have no link-title URLs"
                self._note_text_casefold[note_int_id] = append_link_titles_casefold(
                    self._note_base_text_casefold[note_int_id],
                    self._note_link_title_urls[note_int_id],
                )
            self._revision += 1
            self._result_cache.clear()

    def refresh_note_texts(self, texts: Dict[str, Tuple[str, str]]) -> None:
        """Recompose the searchable text of notes, by id, from (content text, tags), after
        something they show changed without their own text changing: a file's name."""
        if not texts:
            return
        with self._lock:
            for note_id, (content_text, tags) in texts.items():
                note_int_id = self._uuid_to_id[note_id]
                assert note_int_id in self._alive, "only live notes are refreshed"
                self._set_note_text_locked(note_int_id, content_text, tags)
            self._revision += 1
            self._result_cache.clear()

    def bulk_update_tag_terms(self, updates: Dict[str, FrozenSet[str]]) -> None:
        if not updates:
            return

        t0 = time.perf_counter()
        touched = 0
        with self._lock:
            for note_id, new_tag_terms in updates.items():
                # Updates may name notes deleted meanwhile.
                if note_id not in self._uuid_to_id:
                    continue
                note_int_id = self._uuid_to_id[note_id]
                if note_int_id not in self._alive:
                    continue

                old_tag_terms = self._note_tag_terms[note_int_id]
                if old_tag_terms == new_tag_terms:
                    continue

                # Touch only the terms that changed: inherited term sets are
                # large and mostly stable, so remove-all/add-all dominated.
                # Postings are never deleted, so a term the note had has one.
                for term in old_tag_terms - new_tag_terms:
                    self._tag_notes.remove(term)
                new_casefold = frozenset(term.casefold() for term in new_tag_terms)
                old_casefold = self._note_tag_terms_casefold[note_int_id]
                for term_casefold in old_casefold - new_casefold:
                    self._tag_notes_casefold[term_casefold].discard(note_int_id)
                for term in new_tag_terms - old_tag_terms:
                    self._tag_notes.add(term)
                for term_casefold in new_casefold - old_casefold:
                    self._add_tag_casefold_posting_locked(term_casefold, note_int_id)

                self._note_tag_terms[note_int_id] = new_tag_terms
                self._note_tag_terms_casefold[note_int_id] = new_casefold
                touched += 1

            if touched:
                self._revision += 1
                self._result_cache.clear()

        elapsed_ms = (time.perf_counter() - t0) * MS_PER_SECOND
        safe_log.log_event(
            "INFO", "search.index.bulk_update_tag_terms",
            elapsed_ms=elapsed_ms, revision=self._revision, touched=touched, updates=len(updates),
        )

    def bulk_update_raw_tag_terms(self, updates: Dict[str, FrozenSet[str]]) -> None:
        if not updates:
            return

        touched = 0
        with self._lock:
            for note_id, new_raw_tag_terms in updates.items():
                # Updates may name notes deleted meanwhile.
                if note_id not in self._uuid_to_id or self._uuid_to_id[note_id] not in self._alive:
                    continue
                note_int_id = self._uuid_to_id[note_id]

                old_raw_tag_terms = self._note_raw_tag_terms[note_int_id]
                if old_raw_tag_terms == new_raw_tag_terms:
                    continue

                old_raw_casefold = {term.casefold() for term in old_raw_tag_terms}
                new_raw_casefold = {term.casefold() for term in new_raw_tag_terms}
                for term_casefold in old_raw_casefold - new_raw_casefold:
                    self._raw_tag_notes_casefold.remove(term_casefold)
                for term_casefold in new_raw_casefold - old_raw_casefold:
                    self._raw_tag_notes_casefold.add(term_casefold)
                self._update_raw_families_locked(old_raw_casefold, new_raw_casefold)

                self._note_raw_tag_terms[note_int_id] = new_raw_tag_terms
                touched += 1

            if touched:
                self._revision += 1
                self._result_cache.clear()

    def remove_many(self, note_ids: Set[str]) -> None:
        if not note_ids:
            return
        t0 = time.perf_counter()
        with self._lock:
            for note_id in note_ids:
                if note_id not in self._uuid_to_id:
                    continue
                note_int_id = self._uuid_to_id[note_id]
                self._remove_existing_locked(note_int_id)

            self._revision += 1
            self._result_cache.clear()

        elapsed_ms = (time.perf_counter() - t0) * MS_PER_SECOND
        safe_log.log_event(
            "INFO", "search.index.remove_many",
            elapsed_ms=elapsed_ms, notes=len(note_ids), revision=self._revision,
        )

    def list_tag_suggestion_terms(self) -> FrozenSet[str]:
        """Every term a suggestion can offer: the tag vocabulary and the meta tags the
        meta suggestions draw on (known ones, those in use, and their families), so any
        suggestion picked is a known tag."""
        with self._lock:
            # The search box offers each term (jogging=3), the tag bar each family (jogging).
            terms = self._build_suggestion_representatives_locked(
                anchor_casefold_set=frozenset(), partial_prefix="", by_family=False,
            )
            families = self._build_suggestion_representatives_locked(
                anchor_casefold_set=frozenset(), partial_prefix="", by_family=True,
            )
            suggestion_terms = {*terms.values(), *families.values(), *self._meta_tag_suggestion_terms_locked()}
            # The search box offers @datetime itself once notes carry a date.
            if self._tag_family_posting_locked(DATETIME_TAG):
                suggestion_terms.add(DATETIME_TAG)
            return frozenset(suggestion_terms)

    def list_tag_frequencies(self) -> Dict[str, int]:
        """Return tag term -> note count (excluding @meta tags)."""
        with self._lock:
            return {
                term: note_count
                for term, note_count in self._tag_notes.items()
                if term and not term.startswith("@")
            }

    def list_raw_tag_frequencies_by_casefold(self) -> Dict[str, int]:
        """Return raw tag -> distinct note count after inheritance, before ontology."""
        with self._lock:
            return {
                term_casefold: note_count
                for term_casefold, note_count in self._raw_tag_notes_casefold.items()
                if term_casefold and not term_casefold.startswith("@")
            }

    def list_raw_tag_terms_for_note(self, note_id: str) -> FrozenSet[str]:
        """Return explicit and inherited tags before ontology inference."""
        if not isinstance(note_id, str) or note_id == "":
            raise TypeError("note_id must be a non-empty string")
        with self._lock:
            if note_id not in self._uuid_to_id:
                raise KeyError(f"Note {note_id} not present in SearchIndex")
            note_int_id = self._uuid_to_id[note_id]
            if note_int_id not in self._alive:
                raise KeyError(f"Note {note_id} is not active in SearchIndex")
            return self._note_raw_tag_terms[note_int_id]

    def list_effective_tag_terms_for_note(self, note_id: str) -> FrozenSet[str]:
        """Return the exact effective tags used by canonical search matching."""
        if not isinstance(note_id, str) or note_id == "":
            raise TypeError("note_id must be a non-empty string")
        with self._lock:
            if note_id not in self._uuid_to_id:
                raise KeyError(f"Note {note_id} not present in SearchIndex")
            note_int_id = self._uuid_to_id[note_id]
            if note_int_id not in self._alive:
                raise KeyError(f"Note {note_id} is not active in SearchIndex")
            return self._note_tag_terms[note_int_id]

    def list_raw_tag_family_frequencies_by_casefold(self) -> Dict[str, int]:
        """list_raw_tag_frequencies_by_casefold by tag family: jogging counts every note with
        jogging or jogging=<value> (tag_family_of)."""
        with self._lock:
            return {
                family: note_count
                for family, note_count in self._raw_tag_family_notes_casefold.items()
                if family and not family.startswith("@")
            }

    def list_explicit_tag_family_frequencies(self) -> Dict[str, int]:
        """list_explicit_tag_frequencies by tag family (tag_family_of), each note once."""
        with self._lock:
            return {
                family: note_count
                for family, note_count in self._explicit_tag_family_notes.items()
                if family and not family.startswith("@")
            }

    def list_explicit_tag_frequencies(self) -> Dict[str, int]:
        """Return explicitly written tag term -> note count (excluding @meta tags)."""
        with self._lock:
            return {
                term: note_count
                for term, note_count in self._explicit_tag_notes.items()
                if term and not term.startswith("@")
            }

    def describe_tag_cooccurrence(
        self, *, anchors: Iterable[str], terms: Iterable[str], excluded_note_ids: FrozenSet[str], by_family: bool,
    ) -> Dict[str, TagCooccurrence]:
        """For each term, the notes carrying it together with the most of the anchors.

        The same measure `suggest_tag_completions` ranks by (the most anchors one
        of the term's notes carries, and how many notes carry that many), with
        the anchors named. Terms on no note with an anchor are left out.
        excluded_note_ids: notes not to count (the note a tag is already on).
        """
        anchor_casefold_set = frozenset(
            anchor.casefold() for anchor in anchors if anchor and not anchor.startswith("@")
        )
        described: Dict[str, TagCooccurrence] = {}
        with self._lock:
            excluded = {self._uuid_to_id[note_id] for note_id in excluded_note_ids if note_id in self._uuid_to_id}
            for term in terms:
                term_casefold = term.casefold()
                term_notes = self._suggestion_posting_locked(term_casefold, by_family=by_family)
                if not term_notes:
                    continue
                if excluded:
                    term_notes = term_notes - excluded
                shared_by_anchor = {
                    anchor_casefold: term_notes & self._tag_notes_casefold[anchor_casefold]
                    for anchor_casefold in anchor_casefold_set
                    if anchor_casefold != term_casefold and anchor_casefold in self._tag_notes_casefold
                }
                cooccurrence = _most_anchors_cooccurrence(
                    {anchor: notes for anchor, notes in shared_by_anchor.items() if notes}
                )
                if cooccurrence is not None:
                    described[term] = cooccurrence
        return described

    # Suggestions read a search's completed clause without its stats terms (no subtree walks
    # for them); one about values reads what notes inherit, from the tree, before the lock.
    # A folder suggested is read against the clause without its folder terms, as folders add
    # results (folders-tab-and-multiple-folders.md §3): after `Projects/ `, `Archive/` is offered
    # when Archive has notes the rest of the clause finds.
    @staticmethod
    def _suggestion_clause(completed_clause: str, *, without_folders: bool) -> SearchClause:
        assert completed_clause.strip() != "", "a completed clause"
        clause = parse_search_query(completed_clause).first_clause.without_stats_terms()
        if not without_folders:
            return clause
        return dataclasses.replace(
            clause, required_tags=frozenset(tag for tag in clause.required_tags if not tag.endswith(FOLDER_TAG_END)),
        )

    def _tree_matches_for_suggestions(self, completed_clause: str, *, without_folders: bool) -> FrozenSet[str]:
        """The notes the completed clause finds when it reads values (outside the lock); none
        to read otherwise, the index answering it alone (_suggestion_matching_ids_locked)."""
        if completed_clause.strip() == "":
            return frozenset()
        clause = self._suggestion_clause(completed_clause, without_folders=without_folders)
        if not clause.has_value_terms:
            return frozenset()
        return frozenset(self._tree_clause_note_ids(clause))

    def _suggestion_matching_ids_locked(
        self, completed_clause: str, tree_matches: FrozenSet[str], *, without_folders: bool,
    ) -> Set[int]:
        if completed_clause.strip() == "":
            return self._alive
        clause = self._suggestion_clause(completed_clause, without_folders=without_folders)
        if clause.has_value_terms:
            return {self._uuid_to_id[note_id] for note_id in tree_matches if note_id in self._uuid_to_id}
        return self._matching_note_int_ids_for_clause_locked(clause)

    def describe_search_suggestions(self, *, query: str, terms: Iterable[str]) -> SearchSuggestionFacts:
        """The facts `suggest_all_tag_completions` ranked and filtered these terms by."""
        context = _parse_search_suggestion_context(query)
        partial_prefix = ""
        if context.partial_prefix is not None:
            partial_prefix = context.partial_prefix
        shown = list(terms)
        tree_matches = self._tree_matches_for_suggestions(context.completed_clause, without_folders=False)
        folderless_tree_matches = self._tree_matches_for_suggestions(context.completed_clause, without_folders=True)
        with self._lock:
            has_completed_clause = context.completed_clause.strip() != ""
            matching_ids = self._suggestion_matching_ids_locked(context.completed_clause, tree_matches, without_folders=False)
            folderless_matching_ids = self._suggestion_matching_ids_locked(
                context.completed_clause, folderless_tree_matches, without_folders=True,
            )
            note_counts: Dict[str, int] = {}
            matching_counts: Dict[str, int] = {}
            for term in shown:
                if term.casefold() not in self._tag_notes_casefold:
                    note_counts[term] = 0
                    matching_counts[term] = 0
                    continue
                posting = self._tag_notes_casefold[term.casefold()]
                note_counts[term] = len(posting)
                if term.endswith(FOLDER_TAG_END) and not context.is_exclusion:
                    matching_counts[term] = len(posting & folderless_matching_ids)
                else:
                    matching_counts[term] = len(posting & matching_ids)
            cooccurrences = self.describe_tag_cooccurrence(
                anchors=context.anchors, terms=shown, excluded_note_ids=frozenset(), by_family=False,
            )
            return SearchSuggestionFacts(
                partial_prefix=partial_prefix, anchors=tuple(context.anchors),
                has_completed_clause=has_completed_clause, is_exclusion=context.is_exclusion,
                matching_note_count=len(matching_ids), note_counts=note_counts,
                matching_counts=matching_counts, cooccurrences=cooccurrences,
            )

    def count_written_tags_on_notes_with(self, term: str) -> Tuple[int, Dict[str, Tuple[int, int]]]:
        """(notes carrying `term`, for each other tag written on them: (how many of those
        notes it is written on, how many notes in all it is written on)).

        Keys are casefolded, meta tags included; `term` itself is left out. Both counts
        come from the same record, so the second is never below the first. Tag
        Relationships ranks the tags linked to a focus tag by them (app/api/routes/ontology.py)."""
        if not isinstance(term, str) or term == "":
            raise TypeError("term must be a non-empty string")
        term_casefold = term.casefold()
        with self._lock:
            if term_casefold not in self._tag_notes_casefold:
                return 0, {}
            notes = self._tag_notes_casefold[term_casefold]
            shared: Counter[str] = Counter()
            for note_int_id in notes:
                shared.update({tag.casefold() for tag in self._note_explicit_tag_terms[note_int_id]})
            if term_casefold in shared:
                del shared[term_casefold]
            return len(notes), {
                tag: (count, self._explicit_tag_notes_casefold.count(tag)) for tag, count in shared.items()
            }

    def count_tag_within_search(self, *, term: str, search: str) -> Tuple[int, int]:
        """(notes the search finds, how many of them carry the tag); a blank search finds every note."""
        if not isinstance(term, str) or term == "":
            raise TypeError("term must be a non-empty string")
        if not isinstance(search, str):
            raise TypeError("search must be a string")
        with self._lock:
            if search.strip() == "":
                found = set(self._alive)
            else:
                found = {self._uuid_to_id[note_id] for note_id in self.query_note_ids(search)}
            posting: Set[int] = set()
            if term.casefold() in self._tag_notes_casefold:
                posting = self._tag_notes_casefold[term.casefold()]
            return len(found), len(found & posting)

    def is_tag_on_any_note(self, term: str) -> bool:
        """Whether some note has the tag in its own tags (case-insensitive).

        Proposed and inherited tags don't count: an AI proposal for a tag this
        is False for would create a new tag.
        """
        if not isinstance(term, str) or term == "":
            raise TypeError("term must be a non-empty string")
        with self._lock:
            return term.casefold() in self._explicit_tag_notes_casefold

    def count_notes_with_tag(self, term: str) -> int:
        """Notes carrying the tag, as suggestions count usage (case-insensitive)."""
        if not isinstance(term, str) or term == "":
            raise TypeError("term must be a non-empty string")
        with self._lock:
            term_casefold = term.casefold()
            if term_casefold not in self._tag_notes_casefold:
                return 0
            return len(self._tag_notes_casefold[term_casefold])

    def count_notes_in_tag_family(self, tag: str) -> int:
        """Notes carrying the tag with or without a value (@datetime counts every dated note)."""
        if not isinstance(tag, str) or tag == "":
            raise TypeError("tag must be a non-empty string")
        with self._lock:
            return len(self._tag_family_posting_locked(tag.casefold()))

    def suggest_tag_completions(self, *, query: str, limit: int, by_family: bool) -> List[str]:
        """Tags ranked by how they go with the query's tags, then by use. by_family: each tag
        counted over all its notes whatever their values (jogging=3, jogging=5 as jogging), as
        the tag bar offers them; else every term on its own, as a search can name a value."""
        if not isinstance(query, str):
            raise TypeError(f"query must be a string, got {type(query)}")
        if not isinstance(limit, int) or limit <= 0:
            raise TypeError("limit must be a positive integer")

        anchors, partial_prefix = _parse_search_query_for_suggestions(query)
        if partial_prefix is None:
            if query.strip() != "":
                return []
            partial_prefix = ""

        if partial_prefix.startswith("@"):
            with self._lock:
                # A search finds no note by a date only now suggests, so it offers @datetime itself,
                # which finds every dated note (the tag bar offers it dated:
                # suggest_meta_tag_completions).
                searchable_datetime = None
                if not by_family and self._tag_family_posting_locked(DATETIME_TAG):
                    searchable_datetime = DATETIME_TAG
                return self._suggest_meta_tag_completions_locked(
                    partial_prefix=partial_prefix,
                    limit=limit,
                    datetime_term=searchable_datetime,
                )

        anchor_casefold_set = frozenset(
            anchor.casefold()
            for anchor in anchors
            if anchor and not anchor.startswith("@")
        )

        with self._lock:
            representative_by_casefold = self._build_suggestion_representatives_locked(
                anchor_casefold_set=anchor_casefold_set,
                partial_prefix=partial_prefix,
                by_family=by_family,
            )
            # By family, a date goes with tags as any tag does (journal and @datetime); the tag
            # bar offers it dated, and only for the note's own tags (tag_suggestions).
            if by_family and self._tag_family_posting_locked(DATETIME_TAG) and tag_term_matches_prefix(
                term=DATETIME_TAG, prefix=partial_prefix,
            ):
                representative_by_casefold[DATETIME_TAG] = DATETIME_TAG
            candidate_casefolds = list(representative_by_casefold.keys())
            postings = {
                term_casefold: self._suggestion_posting_locked(term_casefold, by_family=by_family)
                for term_casefold in candidate_casefolds
            }

            if not candidate_casefolds and partial_prefix != "":
                return []

            if not anchor_casefold_set:
                candidate_casefolds.sort(
                    key=lambda term_casefold: (
                        -len(postings[term_casefold]),
                        *self._suggestion_term_tiebreak_locked(representative_by_casefold[term_casefold]),
                    )
                )
                return [
                    representative_by_casefold[term_casefold]
                    for term_casefold in candidate_casefolds[:limit]
                ]

            # Postings hold only live notes (removal discards them). Group the
            # notes carrying anchors by how many they carry; each candidate's
            # co-occurrence is then a set intersection per group.
            anchor_counts: Dict[int, int] = {}
            for anchor_casefold in anchor_casefold_set:
                if anchor_casefold not in self._tag_notes_casefold:
                    continue
                for note_id in self._tag_notes_casefold[anchor_casefold]:
                    if note_id not in anchor_counts:
                        anchor_counts[note_id] = 0
                    anchor_counts[note_id] += 1

            max_anchor_count = len(anchor_casefold_set)
            notes_by_anchor_count: List[Set[int]] = [set() for _ in range(max_anchor_count + 1)]
            for note_id, count in anchor_counts.items():
                assert 0 < count <= max_anchor_count
                notes_by_anchor_count[count].add(note_id)

            support_counts = [0] * (max_anchor_count + 1)
            running = 0
            for k in range(max_anchor_count, 0, -1):
                running += len(notes_by_anchor_count[k])
                support_counts[k] = running

            # term -> (most anchors one of its notes carries, notes carrying that many)
            co_occurrence = self._suggestion_co_occurrence_locked(
                postings=postings,
                anchor_counts=anchor_counts,
                notes_by_anchor_count=notes_by_anchor_count,
                by_family=by_family,
            )

            scored: List[Tuple[int, float, int, str]] = []
            for term_casefold in candidate_casefolds:
                candidate_count = len(postings[term_casefold])
                if candidate_count == 0:
                    continue

                max_k, intersection_count = 0, 0
                if term_casefold in co_occurrence:
                    max_k, intersection_count = co_occurrence[term_casefold]
                if max_k == 0 and partial_prefix == "":
                    continue

                jaccard = 0.0
                if max_k > 0:
                    union_count = candidate_count + support_counts[max_k] - intersection_count
                    if union_count > 0:
                        jaccard = intersection_count / union_count

                representative = representative_by_casefold[term_casefold]
                lower_case_penalty, term_tiebreak = self._suggestion_term_tiebreak_locked(representative)
                scored.append((-max_k, -jaccard, lower_case_penalty, term_tiebreak))

            scored.sort()
            return [representative_by_casefold[term.casefold()] for _, __, ___, term in scored[:limit]]

    def _suggestion_posting_locked(self, term_casefold: str, *, by_family: bool) -> Set[int]:
        """The notes a suggestion candidate counts: its family's (tag_family_of) or its own."""
        if by_family:
            return self._tag_family_posting_locked(term_casefold)
        return _posting_or_empty(self._tag_notes_casefold, term_casefold)

    def _suggestion_co_occurrence_locked(
        self,
        *,
        postings: Dict[str, Set[int]],
        anchor_counts: Dict[int, int],
        notes_by_anchor_count: List[Set[int]],
        by_family: bool,
    ) -> Dict[str, Tuple[int, int]]:
        """Map each co-occurring candidate to (max anchors on one note, notes with that many).

        Few anchor notes: walk their own terms (by family when by_family). Many: intersect each
        candidate's postings with the anchor-count groups, which runs in C.
        """
        co_occurrence: Dict[str, Tuple[int, int]] = {}
        anchor_terms_size = sum(len(self._note_tag_terms_casefold[note_id]) for note_id in anchor_counts)
        if anchor_terms_size <= SUGGESTION_INTERSECT_COST_RATIO * len(postings):
            candidate_set = set(postings)
            for note_id, count in anchor_counts.items():
                note_terms = self._note_tag_terms_casefold[note_id]
                if by_family:
                    note_terms = frozenset(tag_family_of(term_casefold) for term_casefold in note_terms)
                for term_casefold in note_terms & candidate_set:
                    if term_casefold not in co_occurrence or count > co_occurrence[term_casefold][0]:
                        co_occurrence[term_casefold] = (count, 1)
                    elif count == co_occurrence[term_casefold][0]:
                        co_occurrence[term_casefold] = (count, co_occurrence[term_casefold][1] + 1)
            return co_occurrence
        for term_casefold, note_ids in postings.items():
            for k in range(len(notes_by_anchor_count) - 1, 0, -1):
                if notes_by_anchor_count[k]:
                    shared = len(note_ids & notes_by_anchor_count[k])
                    if shared:
                        co_occurrence[term_casefold] = (k, shared)
                        break
        return co_occurrence

    def suggest_all_tag_completions(self, *, query: str) -> List[str]:
        """Return ranked search completions with real matches, before UI truncation.

        Note-tag recommendations retain partial co-occurrence ranking through
        suggest_tag_completions; search completions must satisfy the whole clause.
        """
        context = _parse_search_suggestion_context(query)
        tree_matches = self._tree_matches_for_suggestions(context.completed_clause, without_folders=False)
        folderless_tree_matches = self._tree_matches_for_suggestions(context.completed_clause, without_folders=True)
        with self._lock:
            candidate_capacity = len(self._tag_notes) + len(list_known_meta_tag_terms()) + 1
            suggestions = self.suggest_tag_completions(query=query, limit=candidate_capacity, by_family=False)
            if not suggestions:
                return []
            matching_ids = self._suggestion_matching_ids_locked(context.completed_clause, tree_matches, without_folders=False)
            folderless_matching_ids = self._suggestion_matching_ids_locked(
                context.completed_clause, folderless_tree_matches, without_folders=True,
            )
            completions: List[str] = []
            for term in suggestions:
                posting = self._search_term_posting_locked(term.casefold())
                if context.is_exclusion:
                    has_matches = not matching_ids.issubset(posting)
                elif term.endswith(FOLDER_TAG_END):
                    has_matches = not folderless_matching_ids.isdisjoint(posting)
                else:
                    has_matches = not matching_ids.isdisjoint(posting)
                if has_matches:
                    completions.append(term)
            return completions
    @property
    def revision(self) -> int:
        """Counts every change to the index, so a result kept from it can tell it is stale."""
        with self._lock:
            return self._revision

    def note_ids_containing_words(self, words: Tuple[str, ...]) -> FrozenSet[str]:
        """The notes whose searchable text holds every word, anywhere (find's first pass,
        docs/ui/find.md): a superset of the notes whose visible text holds them, read
        without rendering anything."""
        if not isinstance(words, tuple) or len(words) == 0:
            raise ValueError("note_ids_containing_words requires a non-empty tuple of words")
        assert all(isinstance(word, str) and word.strip() == word and word != "" for word in words)
        clause = SearchClause(
            required_tags=frozenset(), forbidden_tags=frozenset(), required_text=words, forbidden_text=(),
            required_properties=(), forbidden_properties=(),
        )
        with self._lock:
            return frozenset(
                self._id_to_uuid[note_int_id] for note_int_id in self._matching_note_int_ids_for_clause_locked(clause)
            )

    def query_note_ids(self, search: str) -> Set[str]:
        t0 = time.perf_counter()
        if not isinstance(search, str):
            raise TypeError(f"search must be a string, got {type(search)}")

        with self._lock:
            if search in self._result_cache:
                cached_revision, cached_results = self._result_cache[search]
                if cached_revision == self._revision:
                    total_ms = (time.perf_counter() - t0) * MS_PER_SECOND
                    safe_log.log_event(
                        "INFO", "search.query.cached",
                        total_ms=total_ms, revision=self._revision, matched=len(cached_results),
                    )
                    return set(cached_results)

        parsed = parse_search_query(search)

        parse_ms = (time.perf_counter() - t0) * MS_PER_SECOND

        has_terms = any(
            clause.required_tags
            or clause.forbidden_tags
            or clause.required_text
            or clause.forbidden_text
            or clause.has_property_terms
            for clause in parsed.clauses
        )
        if not has_terms:
            return set()

        required_tag_count = sum(len(clause.required_tags) for clause in parsed.clauses)
        forbidden_tag_count = sum(len(clause.forbidden_tags) for clause in parsed.clauses)
        required_text_count = sum(len(clause.required_text) for clause in parsed.clauses)
        forbidden_text_count = sum(len(clause.forbidden_text) for clause in parsed.clauses)

        if any(clause.has_stats_terms or clause.has_value_terms for clause in parsed.clauses):
            # Stats figures and inherited values are read from the note tree, outside the
            # lock; MAX and MIN are decided per clause, across the notes it finds.
            return {note_id for clause in parsed.clauses for note_id in self.query_clause_note_ids(clause)}

        t1 = time.perf_counter()
        with self._lock:
            candidate_ids: Set[int] = set()
            for clause in parsed.clauses:
                candidate_ids.update(self._candidate_note_ids_locked(clause))
            candidate_count = len(candidate_ids)
            if not candidate_ids:
                candidate_ms = (time.perf_counter() - t1) * MS_PER_SECOND
                total_ms = (time.perf_counter() - t0) * MS_PER_SECOND
                safe_log.log_event(
                    "INFO", "search.query",
                    parse_ms=parse_ms, candidate_ms=candidate_ms, verify_ms=0.0, total_ms=total_ms,
                    candidates=0, verified=0, matched=0, required_tags=required_tag_count, forbidden_tags=forbidden_tag_count, required_texts=required_text_count, forbidden_texts=forbidden_text_count, or_clauses=len(parsed.clauses), revision=self._revision,
                )
                return set()

            t2 = time.perf_counter()
            matched_note_ids: Set[str] = set()
            verified = 0
            for note_int_id in candidate_ids:
                verified += 1
                if note_int_id not in self._alive:
                    continue
                if not any(
                    self._verify_note_matches_locked(note_int_id, clause)
                    for clause in parsed.clauses
                ):
                    continue
                matched_note_ids.add(self._id_to_uuid[note_int_id])

            candidate_ms = (t2 - t1) * MS_PER_SECOND
            verify_ms = (time.perf_counter() - t2) * MS_PER_SECOND
            total_ms = (time.perf_counter() - t0) * MS_PER_SECOND

            frozen = frozenset(matched_note_ids)
            # A property term reads the ontology rules, which change without a new
            # revision of the index: answer it afresh every time.
            if not any(clause.has_property_terms for clause in parsed.clauses):
                self._result_cache[search] = (self._revision, frozen)

        safe_log.log_event(
            "INFO", "search.query",
            parse_ms=parse_ms, candidate_ms=candidate_ms, verify_ms=verify_ms, total_ms=total_ms,
            candidates=candidate_count, verified=verified, matched=len(matched_note_ids), required_tags=required_tag_count, forbidden_tags=forbidden_tag_count, required_texts=required_text_count, forbidden_texts=forbidden_text_count, or_clauses=len(parsed.clauses), revision=self._revision,
        )
        return matched_note_ids

    def attach_stats_reader(self, reader: StatsFigureReader) -> None:
        """What answers stats terms (@sum:calories>2000): the note store's tree, which this
        index does not hold."""
        if not callable(reader):
            raise TypeError("the stats reader must be callable")
        with self._lock:
            self._stats_reader = reader

    def attach_inherited_values_reader(self, reader: InheritedValuesReader) -> None:
        """What answers terms about values (jogging:miles>2) for the values notes inherit:
        the note store's tree, which this index does not hold."""
        if not callable(reader):
            raise TypeError("the inherited values reader must be callable")
        with self._lock:
            self._inherited_values_reader = reader

    def query_clause_note_ids(self, clause: SearchClause) -> Set[str]:
        if not isinstance(clause, SearchClause):
            raise TypeError(f"clause must be SearchClause, got {type(clause)}")
        if clause.has_stats_terms or clause.has_value_terms:
            return self._tree_clause_note_ids(clause)
        with self._lock:
            return {
                self._id_to_uuid[note_int_id]
                for note_int_id in self._matching_note_int_ids_for_clause_locked(clause)
            }

    def query_untagged_note_ids(self) -> Set[str]:
        with self._lock:
            cached = self._untagged_result_cache
            if cached is not None:
                cached_revision, cached_results = cached
                if cached_revision == self._revision:
                    return set(cached_results)

            matched_note_ids = frozenset(
                self._id_to_uuid[note_int_id]
                for note_int_id in self._alive
                if all(
                    term_casefold.startswith("@")
                    for term_casefold in self._note_tag_terms_casefold[note_int_id]
                )
            )
            self._untagged_result_cache = (self._revision, matched_note_ids)
            return set(matched_note_ids)

    # Internal ----------------------------------------------------------------

    def _insert_new_locked(
        self,
        note_id: str,
        explicit_tag_terms: FrozenSet[str],
        raw_tag_terms: FrozenSet[str],
        tag_terms: FrozenSet[str],
        casefold_by_term: Dict[str, str],
    ) -> int:
        """Adds the note with its tags and no text; the caller sets its text next."""
        assert isinstance(explicit_tag_terms, frozenset)
        note_int_id = len(self._id_to_uuid)
        self._uuid_to_id[note_id] = note_int_id
        self._id_to_uuid.append(note_id)
        self._alive.add(note_int_id)

        self._note_text_casefold.append("")
        self._note_link_title_urls.append(frozenset())
        self._note_explicit_tag_terms.append(explicit_tag_terms)
        self._note_raw_tag_terms.append(raw_tag_terms)
        self._note_tag_terms.append(tag_terms)

        self._add_explicit_terms_locked(explicit_tag_terms)
        raw_casefold = set()
        for term in raw_tag_terms:
            if term not in casefold_by_term:
                casefold_by_term[term] = term.casefold()
            raw_casefold.add(casefold_by_term[term])
        # Once per note: Trip and trip are one lowercased tag.
        for term_casefold in raw_casefold:
            self._raw_tag_notes_casefold.add(term_casefold)
        self._update_raw_families_locked(set(), raw_casefold)
        tag_terms_casefold = []
        for term in tag_terms:
            if term not in casefold_by_term:
                casefold_by_term[term] = term.casefold()
            term_casefold = casefold_by_term[term]
            tag_terms_casefold.append(term_casefold)
            self._tag_notes.add(term)
            self._add_tag_casefold_posting_locked(term_casefold, note_int_id)
        self._note_tag_terms_casefold.append(frozenset(tag_terms_casefold))
        return note_int_id

    def _add_explicit_terms_locked(self, terms: FrozenSet[str]) -> None:
        for term in terms:
            self._explicit_tag_notes.add(term)
        # Once per note: Trip and trip are one lowercased tag.
        for term_casefold in {term.casefold() for term in terms}:
            self._explicit_tag_notes_casefold.add(term_casefold)
        # Once per note: jogging=3 and jogging:miles=4 on one note are one jogging.
        for family in {tag_family_of(term) for term in terms}:
            self._explicit_tag_family_notes.add(family)

    def _remove_explicit_terms_locked(self, terms: FrozenSet[str]) -> None:
        for term in terms:
            self._explicit_tag_notes.remove(term)
        for term_casefold in {term.casefold() for term in terms}:
            self._explicit_tag_notes_casefold.remove(term_casefold)
        for family in {tag_family_of(term) for term in terms}:
            self._explicit_tag_family_notes.remove(family)

    def _update_raw_families_locked(self, old_raw_casefold: Set[str], new_raw_casefold: Set[str]) -> None:
        """A note's raw tags changed from old to new: its families' counts follow, once per note."""
        old_families = {tag_family_of(term_casefold) for term_casefold in old_raw_casefold}
        new_families = {tag_family_of(term_casefold) for term_casefold in new_raw_casefold}
        for family in old_families - new_families:
            self._raw_tag_family_notes_casefold.remove(family)
        for family in new_families - old_families:
            self._raw_tag_family_notes_casefold.add(family)

    def _update_existing_locked(
        self,
        note_int_id: int,
        content_text: str,
        tags: str,
        new_raw_tag_terms: FrozenSet[str],
        new_tag_terms: FrozenSet[str],
    ) -> None:
        if note_int_id not in self._alive:
            raise RuntimeError("Cannot update deleted note")

        new_explicit_tag_terms = extract_tags_for_search(tags)
        old_explicit_tag_terms = self._note_explicit_tag_terms[note_int_id]
        old_raw_tag_terms = self._note_raw_tag_terms[note_int_id]
        old_tag_terms = self._note_tag_terms[note_int_id]

        if old_explicit_tag_terms != new_explicit_tag_terms:
            self._remove_explicit_terms_locked(old_explicit_tag_terms)
            self._add_explicit_terms_locked(new_explicit_tag_terms)
            self._note_explicit_tag_terms[note_int_id] = new_explicit_tag_terms

        if old_raw_tag_terms != new_raw_tag_terms:
            for term_casefold in {term.casefold() for term in old_raw_tag_terms}:
                self._raw_tag_notes_casefold.remove(term_casefold)
            for term_casefold in {term.casefold() for term in new_raw_tag_terms}:
                self._raw_tag_notes_casefold.add(term_casefold)
            self._update_raw_families_locked(
                {term.casefold() for term in old_raw_tag_terms}, {term.casefold() for term in new_raw_tag_terms},
            )
            self._note_raw_tag_terms[note_int_id] = new_raw_tag_terms

        if old_tag_terms != new_tag_terms:
            for term in old_tag_terms:
                self._tag_notes.remove(term)
                self._tag_notes_casefold[term.casefold()].discard(note_int_id)
            for term in new_tag_terms:
                self._tag_notes.add(term)
                self._add_tag_casefold_posting_locked(term.casefold(), note_int_id)
            self._note_tag_terms[note_int_id] = new_tag_terms
            self._note_tag_terms_casefold[note_int_id] = frozenset(
                term.casefold() for term in new_tag_terms
            )

        self._set_note_text_locked(note_int_id, content_text, tags)
        self._set_note_properties_locked(note_int_id, tags)

    def _remove_existing_locked(self, note_int_id: int) -> None:
        if note_int_id not in self._alive:
            return
        self._alive.remove(note_int_id)

        for term in self._note_tag_terms[note_int_id]:
            self._tag_notes.remove(term)
            self._tag_notes_casefold[term.casefold()].discard(note_int_id)
        self._remove_explicit_terms_locked(self._note_explicit_tag_terms[note_int_id])
        for term_casefold in {term.casefold() for term in self._note_raw_tag_terms[note_int_id]}:
            self._raw_tag_notes_casefold.remove(term_casefold)
        self._update_raw_families_locked({term.casefold() for term in self._note_raw_tag_terms[note_int_id]}, set())
        self._note_text_casefold[note_int_id] = ""
        if note_int_id in self._note_text_file_ids:
            del self._note_text_file_ids[note_int_id]
        if note_int_id in self._note_comments_casefold:
            del self._note_comments_casefold[note_int_id]
        self._set_note_properties_locked(note_int_id, "")
        self._set_link_title_urls_locked(note_int_id, frozenset())
        if note_int_id in self._note_base_text_casefold:
            del self._note_base_text_casefold[note_int_id]
        self._note_explicit_tag_terms[note_int_id] = frozenset()
        self._note_raw_tag_terms[note_int_id] = frozenset()
        self._note_tag_terms[note_int_id] = frozenset()
        self._note_tag_terms_casefold[note_int_id] = frozenset()

    def _set_note_properties_locked(self, note_int_id: int, tags: str) -> None:
        properties: Dict[Tuple[str, str], PropertyValue] = {}
        # Only a token with = has a value (jogging=3, jogging:miles=3).
        if PROPERTY_ASSIGNMENT in tags:
            _own_tag_names, properties = tag_bar_values(tags)
        previous: Dict[Tuple[str, str], PropertyValue] = {}
        if note_int_id in self._note_properties:
            previous = self._note_properties[note_int_id]
        for key in previous.keys() - properties.keys():
            self._property_notes[key].discard(note_int_id)
        for key in properties.keys() - previous.keys():
            if key not in self._property_notes:
                self._property_notes[key] = set()
            self._property_notes[key].add(note_int_id)
        if properties:
            self._note_properties[note_int_id] = properties
        elif note_int_id in self._note_properties:
            del self._note_properties[note_int_id]

    def is_property_name_used(self, property_casefold: str) -> bool:
        """Whether some note gives the property a value, a number or not: on any tag
        (`burger:calories=450`) or on the tag itself (`calories=700`). A stats figure for a
        property used nowhere shows a dash, so a typo shows (docs/ui/content-formatting.md,
        Stats of a subtree)."""
        if not isinstance(property_casefold, str) or property_casefold == "" or property_casefold != property_casefold.casefold():
            raise ValueError("is_property_name_used requires a casefolded property name")
        with self._lock:
            for (tag_name, property_name), notes in self._property_notes.items():
                if not notes:
                    continue
                if property_name == property_casefold:
                    return True
                if property_name == IMPLICIT_PROPERTY and tag_name == property_casefold:
                    return True
        return False

    def notes_with_own_values(self, tag_casefold: str) -> List[str]:
        """The live notes whose own tag line gives the tag at least one value (never an
        inherited value, never one inside a scope): where the tag bar's last-used values
        come from (docs/design/tag-properties.md, Suggestions)."""
        if not isinstance(tag_casefold, str) or tag_casefold == "" or tag_casefold != tag_casefold.casefold():
            raise ValueError("notes_with_own_values requires a casefolded tag")
        with self._lock:
            note_ids: Set[int] = set()
            for (tag, _property_name), holders in self._property_notes.items():
                if tag == tag_casefold:
                    note_ids |= holders
            return [self._id_to_uuid[note_int_id] for note_int_id in note_ids if note_int_id in self._alive]

    def _tags_implying_locked(self, tag_casefold: str) -> FrozenSet[str]:
        """The tag and every tag implying it, synonyms included, casefolded; the tag alone
        while the ontology rules cannot be read (a locked vault)."""
        self._read_ontology_locked()
        if tag_casefold not in self._implying_tags_by_tag:
            return frozenset({tag_casefold})
        return frozenset(self._implying_tags_by_tag[tag_casefold] | {tag_casefold})

    def _property_tags_locked(self, tag_casefold: str, property_name: str | None) -> FrozenSet[str]:
        """The tags whose values a property term reads: its tag and every tag implying it,
        or, for a term on any tag (`:version`), every tag with that property (any property
        while its name is still being typed)."""
        if tag_casefold != ANY_TAG:
            return self._tags_implying_locked(tag_casefold)
        return frozenset(
            tag_name for (tag_name, name), notes in self._property_notes.items()
            if notes and name != IMPLICIT_PROPERTY and (property_name is None or name == property_name)
        )

    def _tags_implied_by_locked(self, tag_casefold: str) -> FrozenSet[str]:
        """The tag and every tag it implies, synonyms included, casefolded."""
        self._read_ontology_locked()
        if tag_casefold not in self._implied_tags_by_tag:
            return frozenset({tag_casefold})
        return frozenset(self._implied_tags_by_tag[tag_casefold] | {tag_casefold})

    def _read_ontology_locked(self) -> None:
        ontology = get_ontology_if_ready()
        if ontology is self._implying_ontology:
            return
        self._implying_ontology = ontology
        self._implying_tags_by_tag = {}
        self._implied_tags_by_tag = {}
        if ontology is None:
            return
        for closure, by_tag in (
            (ontology.implied_by_closure, self._implying_tags_by_tag),
            (ontology.implication_closure, self._implied_tags_by_tag),
        ):
            for tag, related in closure.items():
                key = tag.casefold()
                if key not in by_tag:
                    by_tag[key] = set()
                by_tag[key].update(other.casefold() for other in related)

    def suggest_stats_completions(self, *, typed: str, limit: int) -> List[PropertySuggestion]:
        """In a search, after `@sum:`: the properties notes carry the tag for (`@sum=calories`),
        on the most notes first, since only those notes are searched; after
        `@sum:calories=`, MAX and MIN (docs/ui/search-semantics.md, Stats figures)."""
        match = _TYPED_STATS_TERM_RE.fullmatch(typed)
        if match is None:
            return []
        tag = match.group("tag").casefold()
        name = match.group("name")
        if match.group("assignment") is not None:
            partial = match.group("partial")
            return [
                PropertySuggestion(
                    replacement=f"{typed[: match.start('partial')]}{keyword}", label=keyword,
                    reasons=(f"The {_EXTREME_WORDS[keyword]} {tag} of {name} among the notes the rest of the search finds",),
                    note_count=0,
                )
                for keyword in EXTREME_KEYWORDS if keyword.startswith(partial)
            ]
        completion = PropertyCompletion(
            tag=tag, property_name=None, partial=name, before=typed[: match.start("name")], number="",
            excluded_names=frozenset(), name_suffix="", offers_extremes=False, offers_values=False,
        )
        prefix = tag_family_prefix(tag)
        assert prefix is not None, "a stats tag carries no value of its own"
        with self._lock:
            members = []
            if tag in self._tag_family_members:
                members = self._tag_family_members[tag]
            counts = {
                term: len(self._tag_notes_casefold[term]) for term in members
                if self._tag_notes_casefold[term] and _completes(term[len(prefix):], name, frozenset())
            }
        ranked = sorted(counts, key=lambda term: (-counts[term], term))[:limit]
        suggestions = [completion.suggestion(term[len(prefix):], {term: counts[term]}) for term in ranked]
        # Then every property with numbers in the vault: a bare @sum shows them all, and a
        # note gets `@sum=calories` only after its first search (reported 2026-10-28).
        offered = {suggestion.label for suggestion in suggestions}
        for property_name, note_count in self._number_property_note_counts(name):
            if len(suggestions) >= limit:
                break
            if property_name in offered:
                continue
            suggestions.append(PropertySuggestion(
                replacement=f"{completion.before}{property_name}", label=property_name,
                reasons=(f"Numbers on {note_count} {_note_noun(note_count)}",), note_count=note_count,
            ))
        return suggestions

    def _number_property_note_counts(self, partial: str) -> List[Tuple[str, int]]:
        """The properties some note gives a number, by how many notes do, most first. A value
        on the tag itself (`calories=700`) is that property, as the stats count it."""
        notes_by_name: Dict[str, Set[int]] = {}
        with self._lock:
            for (tag_name, property_name), notes in self._property_notes.items():
                name = property_name
                if property_name == IMPLICIT_PROPERTY:
                    name = tag_name
                if not _completes(name, partial, frozenset()):
                    continue
                for note_int_id in notes:
                    if self._note_properties[note_int_id][(tag_name, property_name)].kind != VALUE_NUMBER:
                        continue
                    if name not in notes_by_name:
                        notes_by_name[name] = set()
                    notes_by_name[name].add(note_int_id)
        return sorted(((name, len(notes)) for name, notes in notes_by_name.items()), key=lambda item: (-item[1], item[0]))

    def suggest_property_completions(self, *, typed: str, place: str, limit: int) -> List[PropertySuggestion]:
        """Property names after a tag's colon, and units after a value's number
        (docs/design/tag-properties.md, Suggestions), as replacements for what is typed.
        In the tag bar (place "tag-bar") a tag offers the names used with it and with the
        tags it implies; in a search ("search"), those used with it and with the tags
        implying it, which upward search finds. Most used first."""
        if place not in PROPERTY_SUGGESTION_PLACES:
            raise ValueError(f"Unknown place for property suggestions: {place}")
        completion = read_property_completion(
            typed, in_tag_bar=place == PROPERTY_SUGGESTIONS_IN_TAG_BAR,
            offers_extremes=place == PROPERTY_SUGGESTIONS_IN_SEARCH,
        )
        if completion is None:
            return []
        if completion.offers_values:
            return self._value_suggestions(completion=completion, place=place, limit=limit)
        with self._lock:
            if place == PROPERTY_SUGGESTIONS_IN_TAG_BAR:
                tag_names = self._tags_implied_by_locked(completion.tag.casefold())
            else:
                tag_names = self._property_tags_locked(completion.tag.casefold(), _casefold_name(completion.property_name))
            if completion.property_name is None:
                counts = self._property_name_counts_locked(tag_names)
                excluded = completion.excluded_names
            else:
                counts = self._unit_counts_locked(tag_names, completion.property_name.casefold())
                excluded = frozenset()
        ranked = sorted(
            (
                (name, by_tag) for name, by_tag in counts.items()
                if _completes(name, completion.partial, excluded)
            ),
            key=lambda item: (-sum(item[1].values()), item[0]),
        )
        if not ranked and place == PROPERTY_SUGGESTIONS_IN_TAG_BAR and completion.property_name is None:
            return self._vault_property_names(completion=completion, excluded=excluded, limit=limit)
        return [
            completion.suggestion(name, by_tag) for name, by_tag in ranked[:limit]
        ]

    def _value_suggestions(
        self, *, completion: PropertyCompletion, place: str, limit: int,
    ) -> List[PropertySuggestion]:
        """After a property's =: in a search MAX and MIN first when some value is a number,
        date or time (never for text alone, agreed 2026-10-31), then the values notes give
        it, written as they would be typed (quoted when they need it), the closest match and
        then the most used first."""
        assert completion.property_name is not None, "values follow a property"
        property_name = completion.property_name.casefold()
        with self._lock:
            if place == PROPERTY_SUGGESTIONS_IN_TAG_BAR:
                tag_names = self._tags_implied_by_locked(completion.tag.casefold())
            else:
                tag_names = self._property_tags_locked(completion.tag.casefold(), property_name)
            values = self._value_counts_locked(tag_names, property_name)
        suggestions: List[PropertySuggestion] = []
        is_ordered = any(value.kind != VALUE_TEXT for value, _ in values.values())
        if completion.offers_extremes and is_ordered:
            extreme_words = {MAX_KEYWORD: "largest", MIN_KEYWORD: "smallest"}
            suggestions += [
                PropertySuggestion(
                    replacement=f"{completion.before}{keyword}", label=keyword,
                    reasons=(f"The {extreme_words[keyword]} {completion.property_name} "
                             "among the notes the rest of the search finds",),
                    note_count=0,
                )
                for keyword in EXTREME_KEYWORDS if keyword.startswith(completion.partial)
            ]
        typed = unquote_value(completion.partial).casefold()
        ranked = sorted(
            (
                (value, by_tag) for value, by_tag in values.values()
                if value_completes(value.text, completion.partial)
            ),
            key=lambda item: (
                not item[0].text.casefold().startswith(typed), -sum(item[1].values()), item[0].text.casefold(),
            ),
        )
        for value, by_tag in ranked:
            written = quote_value(value.text)
            reasons = tuple(
                f"On {count} {_note_noun(count)} tagged {tag}"
                for tag, count in sorted(by_tag.items(), key=lambda item: (-item[1], item[0]))
            )
            suggestions.append(PropertySuggestion(
                replacement=f"{completion.before}{written}", label=written, reasons=reasons,
                note_count=sum(by_tag.values()),
            ))
        if completion.number != "":
            # Then the units the property is written in, after the number typed (10m: 10mg).
            unit_completion = dataclasses.replace(
                completion, partial=completion.partial[len(completion.number):],
                before=f"{completion.before}{completion.number}",
            )
            with self._lock:
                unit_counts = self._unit_counts_locked(tag_names, property_name)
            offered = {suggestion.replacement for suggestion in suggestions}
            for unit, by_tag in sorted(unit_counts.items(), key=lambda item: (-sum(item[1].values()), item[0])):
                suggestion = unit_completion.suggestion(unit, by_tag)
                if _completes(unit, unit_completion.partial, frozenset()) and suggestion.replacement not in offered:
                    suggestions.append(suggestion)
        return suggestions[:limit]

    def _value_counts_locked(
        self, tag_names: FrozenSet[str], property_name: str,
    ) -> Dict[str, Tuple[PropertyValue, Dict[str, int]]]:
        """Per value (casefolded text), one way it is written and how many notes give it
        with each tag."""
        values: Dict[str, Tuple[PropertyValue, Dict[str, int]]] = {}
        for tag_name in tag_names:
            key = (tag_name, property_name)
            for note_int_id in _posting_or_empty(self._property_notes, key):
                value = self._note_properties[note_int_id][key]
                folded = value.text.casefold()
                if folded not in values:
                    values[folded] = (value, {})
                by_tag = values[folded][1]
                if tag_name not in by_tag:
                    by_tag[tag_name] = 0
                by_tag[tag_name] += 1
        return values

    def _vault_property_names(
        self, *, completion: PropertyCompletion, excluded: FrozenSet[str], limit: int,
    ) -> List[PropertySuggestion]:
        """In the tag bar, when no name used with the tag (or the tags it implies) matches
        what is typed: the names used with any tag, by how many notes use each, so a new tag
        reuses `calories` rather than invent `kcal` (docs/design/tag-properties.md,
        Suggestions; agreed 2026-10-26)."""
        with self._lock:
            notes_by_name: Dict[str, Set[int]] = {}
            for (_, property_name), notes in self._property_notes.items():
                if property_name == IMPLICIT_PROPERTY or not _completes(property_name, completion.partial, excluded):
                    continue
                if property_name not in notes_by_name:
                    notes_by_name[property_name] = set()
                notes_by_name[property_name].update(notes)
            ranked_names = sorted(notes_by_name, key=lambda name: (-len(notes_by_name[name]), name))[:limit]
            counts = self._property_name_counts_locked(frozenset(tag for tag, _ in self._property_notes))
        suggestions = []
        for name in ranked_names:
            suggestion = completion.suggestion(name, counts[name])
            suggestions.append(dataclasses.replace(
                suggestion, reasons=(_FROM_OTHER_TAGS_REASON,) + suggestion.reasons[:_OTHER_TAG_REASON_LIMIT],
            ))
        return suggestions

    def note_ids_for_property_term(self, condition: PropertyCondition) -> Set[str]:
        """The notes a super tag term can hold for: those with a value of its property on its
        tag or a tag implying it, or, for a missing one (task:due?), those carrying such a tag."""
        with self._lock:
            notes: Set[int] = set()
            for tag_name in self._property_tags_locked(*condition.key):
                if condition.operator == MISSING_OPERATOR:
                    notes |= self._tag_family_posting_locked(tag_name)
                else:
                    notes |= _posting_or_empty(self._property_notes, (tag_name, condition.key[1]))
            return {self._id_to_uuid[note_int_id] for note_int_id in notes if note_int_id in self._alive}

    def uses_property(self, *, tag: str, property_name: str) -> bool:
        """Whether some note gives this property a value on the tag or a tag implying it."""
        with self._lock:
            tag_names = self._tags_implying_locked(tag.casefold())
            return any(
                _posting_or_empty(self._property_notes, (tag_name, property_name.casefold()))
                for tag_name in tag_names
            )

    def _property_name_counts_locked(self, tag_names: FrozenSet[str]) -> Dict[str, Dict[str, int]]:
        """Per property name, how many notes use it with each of these tags."""
        counts: Dict[str, Dict[str, int]] = {}
        for (tag_name, property_name), notes in self._property_notes.items():
            if tag_name not in tag_names or not notes or property_name == IMPLICIT_PROPERTY:
                continue
            if property_name not in counts:
                counts[property_name] = {}
            counts[property_name][tag_name] = len(notes)
        return counts

    def _unit_counts_locked(self, tag_names: FrozenSet[str], property_name: str) -> Dict[str, Dict[str, int]]:
        """Per unit, how many notes give this property a value in it, with each tag."""
        counts: Dict[str, Dict[str, int]] = {}
        for tag_name in tag_names:
            key = (tag_name, property_name)
            for note_int_id in _posting_or_empty(self._property_notes, key):
                unit = self._note_properties[note_int_id][key].unit
                if unit == "":
                    continue
                if unit not in counts:
                    counts[unit] = {}
                if tag_name not in counts[unit]:
                    counts[unit][tag_name] = 0
                counts[unit][tag_name] += 1
        return counts

    def _note_satisfies_property_locked(self, note_int_id: int, condition: PropertyCondition) -> bool:
        """Whether a note's own values meet a property term (tag_properties.condition_holds);
        values on a tag implying the term's tag count (jogging for exercise)."""
        values: Dict[Tuple[str, str], PropertyValue] = {}
        if note_int_id in self._note_properties:
            values = self._note_properties[note_int_id]
        own_tag_names = frozenset(
            term.casefold().split(PROPERTY_ASSIGNMENT, 1)[0] for term in self._note_explicit_tag_terms[note_int_id]
        )
        return condition_holds(
            condition, values=values, own_tag_names=own_tag_names,
            tag_names=self._property_tags_locked(*condition.key),
        )

    def _tree_clause_note_ids(self, clause: SearchClause) -> Set[str]:
        """A clause with terms read from the note tree, outside the lock: values, which notes
        inherit (jogging:miles>2, docs/ui/search-semantics.md), and stats figures
        (@sum:calories>2000). The index finds the notes the rest of the clause holds for,
        among those carrying each required term's tag (themselves or by inheritance); each
        term then reads the note's values or figure. MAX and MIN come last, in the order
        written, among the notes everything else finds."""
        rest = clause.without_stats_terms().without_value_terms()
        conditions = clause.required_properties + clause.forbidden_properties
        with self._lock:
            candidates = self._candidate_note_ids_locked(rest)
            for condition in clause.required_properties:
                if condition.is_stats:
                    candidates &= self._tag_family_posting_locked(condition.key[0])
                elif condition.reads_values:
                    candidates &= self._carrying_property_tags_locked(condition)
            matched_int_ids = {
                note_int_id for note_int_id in candidates
                if note_int_id in self._alive and self._verify_note_matches_locked(note_int_id, rest)
            }
            own_values = {
                self._id_to_uuid[note_int_id]: self._own_values_locked(note_int_id) for note_int_id in matched_int_ids
            }
            tag_names = {condition: self._property_tags_locked(*condition.key)
                         for condition in conditions if condition.reads_values}
        values = _NoteValues(own_values=own_values, inherited=self._read_inherited_values(clause, frozenset(own_values)))
        matched = set(own_values)
        for condition in clause.required_properties:
            if not condition.is_extreme:
                matched = {note_id for note_id in matched if self._meets(note_id, condition, values, tag_names)}
        for condition in clause.forbidden_properties:
            if not condition.is_extreme:
                matched = {note_id for note_id in matched if not self._meets(note_id, condition, values, tag_names)}
        for condition in clause.required_properties:
            if condition.is_extreme:
                matched = self._extreme_note_ids(matched, condition, values, tag_names)
        for condition in clause.forbidden_properties:
            if condition.is_extreme:
                matched -= self._extreme_note_ids(matched, condition, values, tag_names)
        return matched

    def _own_values_locked(self, note_int_id: int) -> Mapping[Tuple[str, str], PropertyValue]:
        if note_int_id not in self._note_properties:  # shockharness: ignore[DEF002] reason="only notes with values are kept"
            return {}
        return self._note_properties[note_int_id]

    def _carrying_property_tags_locked(self, condition: PropertyCondition) -> Set[int]:
        """The notes carrying, themselves or by inheritance, a tag whose values the term reads."""
        notes: Set[int] = set()
        for tag_name in self._property_tags_locked(*condition.key):
            notes |= self._tag_family_posting_locked(tag_name)
        return notes

    def _read_inherited_values(self, clause: SearchClause, note_ids: FrozenSet[str]) -> Mapping[str, InheritedValues]:
        """The values these notes inherit, when the clause reads values (outside the lock)."""
        if not clause.has_value_terms:
            return {}
        reader = self._inherited_values_reader
        if reader is None:
            raise RuntimeError("Terms about values need the note store's reader (attach_inherited_values_reader)")
        inherited = reader(note_ids)
        assert inherited.keys() == note_ids, "the reader answers for every note asked about"
        return inherited

    def _meets(
        self, note_id: str, condition: PropertyCondition, values: _NoteValues,
        tag_names: Mapping[PropertyCondition, FrozenSet[str]],
    ) -> bool:
        """Whether a found note meets a term read from the tree: its values (own or
        inherited, any one map of them) or its stats figure."""
        if condition.is_stats:
            return _figure_meets(self._require_stats_reader()(note_id, condition), condition)
        # A value term never asks for a missing value, the only kind reading own_tag_names.
        return any(
            condition_holds(condition, values=value_map, own_tag_names=frozenset(), tag_names=tag_names[condition])
            for value_map in values.maps(note_id)
        )

    def _require_stats_reader(self) -> StatsFigureReader:
        reader = self._stats_reader
        if reader is None:
            raise RuntimeError("Stats terms need the note store's reader (attach_stats_reader)")
        return reader

    def _extreme_note_ids(
        self, note_ids: Set[str], condition: PropertyCondition, values: _NoteValues,
        tag_names: Mapping[PropertyCondition, FrozenSet[str]],
    ) -> Set[str]:
        """Of these notes, those with the largest (MAX) or smallest (MIN) value or figure."""
        if not condition.is_stats:
            found_by_note: Dict[str, List[PropertyValue]] = {}
            for note_id in note_ids:
                found = [value_map[(tag_name, condition.key[1])] for value_map in values.maps(note_id)
                         for tag_name in tag_names[condition] if (tag_name, condition.key[1]) in value_map]
                if found:
                    found_by_note[note_id] = found
            return _notes_with_extreme_value(found_by_note, condition)
        reader = self._require_stats_reader()
        pick = _EXTREME_PICKS[condition.value_text]
        best_by_note: Dict[str, Decimal] = {}
        for note_id in note_ids:
            figure = reader(note_id, condition)
            # A dash has no number to compare; units are labels, as for values.
            if figure:
                best_by_note[note_id] = pick(value.sort_key for value in figure)
        if not best_by_note:
            return set()
        extreme = pick(best_by_note.values())
        return {note_id for note_id, best in best_by_note.items() if best == extreme}

    def _set_note_text_locked(self, note_int_id: int, content_text: str, tags: str) -> None:
        base_text_casefold = build_searchable_base_text_casefold(content_text, tags)
        link_title_urls = list_link_title_urls(content_text)
        self._set_link_title_urls_locked(note_int_id, link_title_urls)
        if link_title_urls:
            self._note_base_text_casefold[note_int_id] = base_text_casefold
        elif note_int_id in self._note_base_text_casefold:
            del self._note_base_text_casefold[note_int_id]
        self._note_text_casefold[note_int_id] = append_link_titles_casefold(base_text_casefold, link_title_urls)
        comments_casefold = tuple(normalize_text(comment).casefold() for comment in tag_bar_comments(tags))
        if comments_casefold:
            self._note_comments_casefold[note_int_id] = comments_casefold
        elif note_int_id in self._note_comments_casefold:
            del self._note_comments_casefold[note_int_id]
        text_file_ids = tuple(
            file_id for file_id, _name in file_registry.referenced_file_names(content_text)
            if is_searchable_file_name(_name)
        )
        if text_file_ids:
            self._note_text_file_ids[note_int_id] = text_file_ids
        elif note_int_id in self._note_text_file_ids:
            del self._note_text_file_ids[note_int_id]

    def file_texts_changed(self) -> None:
        """Files' text became searchable: results kept from before are worked out again (a view
        already drawn is not: only a new search shows them, docs/ui/interaction-principles.md 2)."""
        with self._lock:
            self._revision += 1
            self._result_cache.clear()

    def _text_term_matches_locked(self, note_int_id: int, term: str) -> bool:
        """Whether the quoted term is in the note's searchable text or the text of a file it shows;
        a comment term (`/*help*/`), whether it is in one of the note's own tag-bar comments."""
        if is_comment_term(term):
            if note_int_id not in self._note_comments_casefold:
                return False
            return comment_term_matches(comment_term_words(term), self._note_comments_casefold[note_int_id])
        if text_term_matches(term, self._note_text_casefold[note_int_id]):
            return True
        if note_int_id not in self._note_text_file_ids:
            return False
        return any(file_texts.term_matches(file_id, term) for file_id in self._note_text_file_ids[note_int_id])

    def _set_link_title_urls_locked(self, note_int_id: int, urls: FrozenSet[str]) -> None:
        previous_urls = self._note_link_title_urls[note_int_id]
        if previous_urls == urls:
            return
        for url in previous_urls - urls:
            bucket = self._link_title_url_notes[url]
            bucket.discard(note_int_id)
            if not bucket:
                del self._link_title_url_notes[url]
        for url in urls - previous_urls:
            _add_posting(self._link_title_url_notes, url, note_int_id)
        self._note_link_title_urls[note_int_id] = urls

    def _build_suggestion_representatives_locked(
        self,
        *,
        anchor_casefold_set: FrozenSet[str],
        partial_prefix: str,
        by_family: bool,
    ) -> Dict[str, str]:
        partial_prefix_casefold = partial_prefix.casefold()
        representatives: Dict[str, str] = {}
        # How many notes each spelling is on; by family, its members' summed (Jogging=3 is a Jogging).
        spelling_counts: Dict[str, int] = {}
        for term, note_count in self._tag_notes.items():
            if by_family:
                term = tag_family_of(term)
            if term in spelling_counts:
                spelling_counts[term] += note_count
            else:
                spelling_counts[term] = note_count
        for term in spelling_counts:
            if not term or term == "OR" or term.startswith("@"):
                continue
            term_casefold = term.casefold()
            if term_casefold in anchor_casefold_set:
                continue
            if partial_prefix != "" and term_casefold == partial_prefix_casefold:
                continue
            if partial_prefix != "" and not tag_term_matches_prefix(term=term, prefix=partial_prefix):
                continue
            if term_casefold not in representatives:
                representatives[term_casefold] = term
                continue
            current = representatives[term_casefold]
            if self._is_better_suggestion_variant_locked(candidate=term, incumbent=current, counts=spelling_counts):
                representatives[term_casefold] = term
        return representatives

    def _is_better_suggestion_variant_locked(self, *, candidate: str, incumbent: str, counts: Dict[str, int]) -> bool:
        candidate_count = counts[candidate]
        incumbent_count = counts[incumbent]
        if candidate_count != incumbent_count:
            return candidate_count > incumbent_count
        candidate_penalty, candidate_tiebreak = self._suggestion_term_tiebreak_locked(candidate)
        incumbent_penalty, incumbent_tiebreak = self._suggestion_term_tiebreak_locked(incumbent)
        if candidate_penalty != incumbent_penalty:
            return candidate_penalty < incumbent_penalty
        return candidate_tiebreak < incumbent_tiebreak

    def _suggestion_term_tiebreak_locked(self, term: str) -> Tuple[int, str]:
        lower_case_penalty = 0
        if term != term.casefold():
            lower_case_penalty = 1
        return (lower_case_penalty, term)

    def _meta_tag_suggestion_terms_locked(self) -> List[str]:
        """The known meta tags, the known @ tags notes carry (@code=python) and each one's
        family (@code), once each by casefold; a known spelling wins (@LaTeX). An @ tag
        MetaList does not know (@date-headline) is not offered: saving would drop it. The dates
        notes carry are not offered: a tag bar suggests one (suggest_meta_tag_completions)."""
        by_casefold: Dict[str, str] = {}
        in_use = [
            term for term, _note_count in self._tag_notes.items()
            if term.startswith("@") and not is_datetime_tag_term(term) and is_known_meta_tag_term(term)
        ]
        families = [term.split(TAG_VALUE_SEPARATOR, 1)[0] for term in in_use if TAG_VALUE_SEPARATOR in term]
        for term in [*families, *in_use, *list_known_meta_tag_terms()]:
            by_casefold[term.casefold()] = term
        return list(by_casefold.values())

    def suggest_meta_tag_completions(self, *, prefix: str, limit: int, datetime_term: str | None) -> List[str]:
        """The built-in tags a tag bar offers for `@…`, with `@datetime` offered as
        datetime_term (note_datetime.suggested_datetime_tag); None when what is typed
        cannot lead to it."""
        if not isinstance(prefix, str) or not prefix.startswith("@"):
            raise ValueError(f"prefix must start with @, got {prefix!r}")
        if not isinstance(limit, int) or limit <= 0:
            raise TypeError("limit must be a positive integer")
        if datetime_term is not None and not is_datetime_tag_term(datetime_term):
            raise ValueError(f"datetime_term must be a @datetime tag, got {datetime_term!r}")
        with self._lock:
            return self._suggest_meta_tag_completions_locked(
                partial_prefix=prefix, limit=limit, datetime_term=datetime_term,
            )

    def _suggest_meta_tag_completions_locked(
        self, *, partial_prefix: str, limit: int, datetime_term: str | None,
    ) -> List[str]:
        partial_prefix_casefold = partial_prefix.casefold()
        candidates: List[Tuple[int, int, str, str]] = []
        terms = self._meta_tag_suggestion_terms_locked()
        if datetime_term is not None:
            terms.append(datetime_term)
        for term in terms:
            if partial_prefix != "" and term.casefold() == partial_prefix_casefold:
                continue
            if partial_prefix != "" and not term.casefold().startswith(partial_prefix_casefold):
                continue
            usage_count = len(self._tag_family_posting_locked(term.casefold()))
            lower_case_penalty, term_tiebreak = self._suggestion_term_tiebreak_locked(term)
            candidates.append((-usage_count, lower_case_penalty, term_tiebreak, term))
        candidates.sort()
        return [term for _, __, ___, term in candidates[:limit]]

    def _candidate_note_ids_locked(self, clause: SearchClause) -> Set[int]:
        constraints: List[Set[int]] = []

        # Folder terms in a clause add results, every other term narrows: `A/ B/ @todo` finds
        # to-dos in A or B (docs/ready-to-build/folders-tab-and-multiple-folders.md §3).
        folder_terms = [tag for tag in clause.required_tags if tag.endswith(FOLDER_TAG_END)]
        if folder_terms:
            in_any_folder = set().union(*(self._search_term_posting_locked(tag.casefold()) for tag in folder_terms))
            if not in_any_folder:
                return set()
            constraints.append(in_any_folder)
        for tag in clause.required_tags:
            if tag.endswith(FOLDER_TAG_END):
                continue
            posting = self._search_term_posting_locked(tag.casefold())
            if not posting:
                return set()
            constraints.append(posting)

        candidate_ids: Optional[Set[int]] = None
        if constraints:
            ordered = sorted(constraints, key=len)
            candidate_ids = set(ordered[0])
            for constraint in ordered[1:]:
                candidate_ids.intersection_update(constraint)
                if not candidate_ids:
                    return set()

        if candidate_ids is None:
            candidate_ids = set(self._alive)

        if clause.forbidden_tags:
            for tag in clause.forbidden_tags:
                candidate_ids.difference_update(self._search_term_posting_locked(tag.casefold()))

        # A property term needs its property (or, missing it, its tag) on the note, on
        # the term's tag or a tag implying it.
        for condition in clause.required_properties:
            tag_names = self._property_tags_locked(*condition.key)
            notes: Set[int] = set()
            for tag_name in tag_names:
                if condition.operator == MISSING_OPERATOR:
                    notes |= self._tag_family_posting_locked(tag_name)
                else:
                    notes |= _posting_or_empty(self._property_notes, (tag_name, condition.key[1]))
            candidate_ids.intersection_update(notes)

        return candidate_ids

    def _matching_note_int_ids_for_clause_locked(self, clause: SearchClause) -> Set[int]:
        # Values and stats figures are read from the note tree (_tree_clause_note_ids).
        assert not clause.has_value_terms and not clause.has_stats_terms, "the index alone answers this clause"
        candidate_ids = self._candidate_note_ids_locked(clause)
        if not clause.required_text and not clause.forbidden_text and not clause.has_property_terms:
            # Tags alone: the postings answer exactly. They hold only live notes (removing
            # a note discards it from each), and the forbidden tags' notes are removed
            # already. Checking each note again took half of suggesting after a broad tag.
            return candidate_ids
        return {
            note_int_id
            for note_int_id in candidate_ids
            if note_int_id in self._alive
            and self._verify_note_matches_locked(note_int_id, clause)
        }

    def _verify_note_matches_locked(self, note_int_id: int, clause: SearchClause) -> bool:
        for term in clause.required_text:
            if not self._text_term_matches_locked(note_int_id, term):
                return False
        for term in clause.forbidden_text:
            if self._text_term_matches_locked(note_int_id, term):
                return False
        note_tag_terms_casefold = self._note_tag_terms_casefold[note_int_id]
        for tag in clause.forbidden_tags:
            if _carries_tag_family(note_tag_terms_casefold, tag.casefold()):
                return False
        for condition in clause.required_properties:
            if not self._note_satisfies_property_locked(note_int_id, condition):
                return False
        for condition in clause.forbidden_properties:
            if not condition.is_extreme and self._note_satisfies_property_locked(note_int_id, condition):
                return False
        return True

    def _add_tag_casefold_posting_locked(self, term_casefold: str, note_int_id: int) -> None:
        # Postings are never deleted: a term gets its posting, and joins its family, once.
        if term_casefold not in self._tag_notes_casefold:
            self._tag_notes_casefold[term_casefold] = set()
            if TAG_VALUE_SEPARATOR in term_casefold:
                family = term_casefold.split(TAG_VALUE_SEPARATOR, 1)[0]
                if family in self._tag_family_members:
                    self._tag_family_members[family].append(term_casefold)
                else:
                    self._tag_family_members[family] = [term_casefold]
        self._tag_notes_casefold[term_casefold].add(note_int_id)

    def _search_term_posting_locked(self, tag_casefold: str) -> Set[int]:
        """The notes a search's tag term finds: its tag's family, exactly. A folder term finds the
        folders below it too, as a folder tag implies the folders above it
        (tag_ontology.parent_folder_tags; docs/ready-to-build/folders-tab-and-multiple-folders.md §6)."""
        return self._tag_family_posting_locked(tag_casefold)

    def _tag_family_posting_locked(self, tag_casefold: str) -> Set[int]:
        """The notes carrying a tag; for a tag without a value (@code), also those
        carrying any tag=value (@code=python, @code=sql)."""
        exact = _posting_or_empty(self._tag_notes_casefold, tag_casefold)
        prefix = tag_family_prefix(tag_casefold)
        if prefix is None:
            return exact
        assert prefix == f"{tag_casefold}{TAG_VALUE_SEPARATOR}", "a family is its members' part before the first separator"
        if tag_casefold not in self._tag_family_members:
            return exact
        members = [self._tag_notes_casefold[term] for term in self._tag_family_members[tag_casefold]]
        return set(exact).union(*members)


search_index = SearchIndex()
file_texts.on_changed(search_index.file_texts_changed)
# A fetched, decrypted or cleared URL title changes which notes match a text search.
link_title_store.add_titles_changed_listener(search_index.refresh_link_titles)


# A vault-wide name's reason (SearchIndex._vault_property_names), then its busiest tags.
_FROM_OTHER_TAGS_REASON = "Not used with this tag yet: used with other tags"
_OTHER_TAG_REASON_LIMIT = 3


def _completes(name: str, partial: str, excluded: FrozenSet[str]) -> bool:
    """Whether a property name completes what is typed: it starts with it, is longer, and
    is not already in the token."""
    typed = partial.casefold()
    return name.startswith(typed) and name != typed and name not in excluded
