"""Notes suggested while typing `[[` in a note (docs/ui/references.md, "Suggestions").

The note copied last comes first whenever it matches at all (and with nothing typed). Then four
tiers, strictly in order: the query exactly in the note's first line, then fuzzily (every typed
word a prefix of a word there, or one edit away from one: a typo, a partial word), then exactly in
the note's text, then fuzzily there. Within a tier, the notes the tab's view shows come first, then
the most recently edited: the view ranks, it never filters. The note being edited is never
suggested. An @password note holds the password itself, so it is never found
or shown by what it holds: it follows its parent when the parent's first line matches, masked.

A vault holds over a hundred thousand notes and the list updates as the user types, so the notes'
first lines and text are kept in a catalog, updated for the notes that changed, with the words in
them grouped by first letter: a fuzzy search looks for the words that match, then for the notes
holding them, and every tier stops once the list is full.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re
from threading import Lock
from typing import Callable, Dict, FrozenSet, Hashable, Iterable, List, Set, Tuple

from app.security.sensitive_cache import register_sensitive_cache, sensitive_caches_enabled
from app.services.content_formatting import CREDENTIAL_MASK, find_global_credential_tag
from app.services.embedded_references import EMPTY_NOTE_PREVIEW, first_line_preview, sole_reference_token
from app.services.note_store import NoteRecord, store
from app.utils.text_utils import strip_sanitized_html

# How many suggestions the list shows: enough to choose from, short enough to read at a glance.
REFERENCE_SUGGESTION_LIMIT = 8
# A typed word this long may differ by one edit (a typo) after its first letter; shorter words
# must be the start of a word.
_TYPO_WORD_LENGTH = 4
# Two neighbouring letters swapped differ in two places.
_SWAP_DIFFERENCES = 2
# Characters of text kept on each side of a content match in its snippet.
_SNIPPET_CONTEXT = 40
_ELLIPSIS = "…"
_PASSWORD = "password"
# The catalog's revision before it first reads the note store.
_NEVER_REFRESHED = -1
_NEVER_EDITED = datetime.min.replace(tzinfo=timezone.utc)
_WORD_RE = re.compile(r"\w+")


@dataclass(frozen=True, slots=True)
class ReferenceSuggestion:
    note_id: str
    # The note's first line as text (the mask for a password).
    first_line: str
    # Where a password sits: its parent's first line; '' for other notes.
    context: str
    # A content match's surroundings, and where the match is in them; '' for first-line matches.
    snippet: str
    highlight_start: int
    highlight_end: int
    # 'password', 'username' or ''.
    credential: str
    # The note's first lines as text, for the preview of the highlighted suggestion; a password masked.


@dataclass(frozen=True, slots=True)
class _Entry:
    record: NoteRecord
    first_line: str
    first_line_casefold: str
    first_line_words: FrozenSet[str]
    # The note's text on one line, as written and casefolded.
    text: str
    text_casefold: str
    credential: str
    edited_at: datetime

    @property
    def is_password(self) -> bool:
        return self.credential == _PASSWORD


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _credential_of(record: NoteRecord) -> str:
    credential = find_global_credential_tag(record.tags)
    if credential is None:
        return ""
    return credential


def _edited_at(record: NoteRecord) -> datetime:
    if record.updated_at is None:
        return _NEVER_EDITED
    return record.updated_at


def _entry(record: NoteRecord) -> _Entry:
    first_line = first_line_preview(record.content)
    first_line_casefold = _normalized(first_line).casefold()
    text = strip_sanitized_html(record.content)
    return _Entry(
        record=record, first_line=first_line, first_line_casefold=first_line_casefold,
        first_line_words=frozenset(_WORD_RE.findall(first_line_casefold)), text=text,
        text_casefold=text.casefold(), credential=_credential_of(record), edited_at=_edited_at(record),
    )


def _within_one_edit(typed: str, word: str) -> bool:
    """One substitution, insertion, deletion or swap of neighbours apart, or equal."""
    if typed == word:
        return True
    if abs(len(typed) - len(word)) > 1:
        return False
    if len(typed) == len(word):
        differences = [index for index, (left, right) in enumerate(zip(typed, word)) if left != right]
        if len(differences) == 1:
            return True
        first = differences[0]
        return (len(differences) == _SWAP_DIFFERENCES and differences[1] == first + 1
                and typed[first] == word[first + 1] and typed[first + 1] == word[first])
    shorter, longer = sorted((typed, word), key=len)
    return any(longer[:index] + longer[index + 1:] == shorter for index in range(len(longer)))


def _word_matches(typed: str, word: str) -> bool:
    if word.startswith(typed):
        return True
    if len(typed) < _TYPO_WORD_LENGTH or word[0] != typed[0]:
        return False
    if _within_one_edit(typed, word):
        return True
    # A typo in a word not finished yet.
    return _within_one_edit(typed, word[:len(typed)])


class _Words:
    """How many notes hold each word, with the words grouped by first letter."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._by_letter: Dict[str, Set[str]] = {}

    def add(self, words: FrozenSet[str]) -> None:
        for word in [word for word in words if word not in self._counts]:
            self._by_letter.setdefault(word[0], set()).add(word)
        self._counts.update(words)

    def remove(self, words: FrozenSet[str]) -> None:
        self._counts.subtract(words)
        for word in words:
            if self._counts[word] == 0:
                del self._counts[word]
                self._by_letter[word[0]].discard(word)

    def matching(self, typed: str) -> List[str]:
        if typed[0] not in self._by_letter:
            return []
        return [word for word in self._by_letter[typed[0]] if _word_matches(typed, word)]


def _text_words(entry: _Entry) -> FrozenSet[str]:
    if entry.is_password:
        return frozenset()
    return frozenset(_WORD_RE.findall(entry.text_casefold))


@dataclass(frozen=True, slots=True)
class _FuzzyWord:
    """The words a typed word matches: text holding none of the fragments cannot hold one of them,
    and the pattern finds them as whole words (a fragment is far quicker to look for)."""

    fragments: Tuple[str, ...]
    pattern: re.Pattern[str]

    @staticmethod
    def of(typed: str, words: List[str]) -> _FuzzyWord:
        # The words starting with what was typed are found by that start; the rest are typos.
        typos = sorted((word for word in words if not word.startswith(typed)), key=len, reverse=True)
        alternatives = "|".join([rf"{re.escape(typed)}\w*", *[re.escape(word) for word in typos]])
        return _FuzzyWord(fragments=(typed, *typos), pattern=re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)"))

    def search(self, text: str) -> re.Match[str] | None:
        if not any(fragment in text for fragment in self.fragments):
            return None
        return self.pattern.search(text)


class _Catalog:
    """Every note's first line and text, most recently edited first, and the words in them, kept
    up to date with the note store: only notes whose record changed are worked out again."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._empty()

    def _empty(self) -> None:
        self._revision = _NEVER_REFRESHED
        self._entries: Dict[str, _Entry] = {}
        self._by_recency: List[str] = []
        # First-line word -> the notes whose first line holds it.
        self._first_line_notes: Dict[str, Set[str]] = {}
        self._first_line_words = _Words()
        self._text_words = _Words()

    def _index(self, note_id: str, entry: _Entry) -> None:
        for word in entry.first_line_words:
            self._first_line_notes.setdefault(word, set()).add(note_id)
        self._first_line_words.add(entry.first_line_words)
        self._text_words.add(_text_words(entry))

    def _unindex(self, note_id: str, entry: _Entry) -> None:
        for word in entry.first_line_words:
            notes = self._first_line_notes[word]
            notes.discard(note_id)
            if not notes:
                del self._first_line_notes[word]
        self._first_line_words.remove(entry.first_line_words)
        self._text_words.remove(_text_words(entry))

    def clear(self) -> None:
        with self._lock:
            self._empty()

    def refreshed(self) -> Tuple[Dict[str, _Entry], List[str]]:
        """The entries and their order, as of now; neither is changed afterwards, only replaced.
        Locking MetaList clears the catalog: it holds the notes' text."""
        with self._lock:
            entries, by_recency = self._refreshed_locked()
        if not sensitive_caches_enabled():
            self.clear()
            return {}, []
        return entries, by_recency

    def _refreshed_locked(self) -> Tuple[Dict[str, _Entry], List[str]]:
        revision = store.revision
        if revision == self._revision:
            return self._entries, self._by_recency
        records = store.snapshot()
        entries = dict(self._entries)
        for note_id in [note_id for note_id in entries if note_id not in records]:
            self._unindex(note_id, entries.pop(note_id))
        for note_id, record in records.items():
            if note_id in entries and entries[note_id].record is record:
                continue
            if note_id in entries:
                self._unindex(note_id, entries[note_id])
            entries[note_id] = _entry(record)
            self._index(note_id, entries[note_id])
        self._entries = entries
        self._by_recency = sorted(entries, key=lambda note_id: entries[note_id].edited_at, reverse=True)
        self._revision = revision
        return self._entries, self._by_recency

    def fuzzy_first_line_notes(self, typed_words: Tuple[str, ...]) -> Set[str]:
        """The notes whose first line has, for every typed word, a word it matches fuzzily."""
        assert typed_words, "a fuzzy search needs a typed word"
        with self._lock:
            found = self._first_lines_matching_locked(typed_words[0])
            for typed in typed_words[1:]:
                if not found:
                    break
                found &= self._first_lines_matching_locked(typed)
            return found

    def _first_lines_matching_locked(self, typed: str) -> Set[str]:
        matching: Set[str] = set()
        for word in self._first_line_words.matching(typed):
            matching |= self._first_line_notes[word]
        return matching

    def fuzzy_text_matchers(self, typed_words: Tuple[str, ...]) -> List[_FuzzyWord]:
        """For every typed word, what finds the words it matches fuzzily in a note's text; none at
        all when one typed word matches no word in any note."""
        with self._lock:
            matchers = []
            for typed in typed_words:
                words = self._text_words.matching(typed)
                if not words:
                    return []
                matchers.append(_FuzzyWord.of(typed, words))
            return matchers


_catalog = _Catalog()
register_sensitive_cache(_catalog.clear)


class _ViewOrder:
    """The catalog's notes with the ones a view shows first, each part most recently edited first:
    worked out once for a view and catalog revision, as the user types on in the same `[[`."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._key: Tuple[object, ...] = ()
        self._order: List[str] = []

    def clear(self) -> None:
        with self._lock:
            self._key = ()
            self._order = []

    def ordered(self, by_recency: List[str], view: Hashable, view_note_ids: Callable[[], FrozenSet[str]]) -> List[str]:
        # The catalog replaces its order whenever a note changes, so the list itself names the revision.
        key = (id(by_recency), view)
        with self._lock:
            if key == self._key:
                return self._order
        shown = view_note_ids()
        order = [note_id for note_id in by_recency if note_id in shown]
        order.extend(note_id for note_id in by_recency if note_id not in shown)
        with self._lock:
            self._key = key
            self._order = order
        return order


_view_order = _ViewOrder()
register_sensitive_cache(_view_order.clear)


def _snippet(entry: _Entry, start: int, end: int) -> Tuple[str, int, int]:
    """The note's text around a match found in its casefolded text."""
    text = entry.text
    if len(entry.text) != len(entry.text_casefold):
        # Casefolding lengthened a character (ß -> ss): the casefolded text shows the match.
        text = entry.text_casefold
    begin = max(0, start - _SNIPPET_CONTEXT)
    finish = min(len(text), end + _SNIPPET_CONTEXT)
    snippet = text[begin:finish]
    highlight_start = start - begin
    if begin > 0:
        snippet = _ELLIPSIS + snippet
        highlight_start += len(_ELLIPSIS)
    if finish < len(text):
        snippet += _ELLIPSIS
    return snippet, highlight_start, highlight_start + end - start


def _suggestion(entry: _Entry) -> ReferenceSuggestion:
    return ReferenceSuggestion(
        note_id=entry.record.id, first_line=entry.first_line, context="", snippet="",
        highlight_start=0, highlight_end=0, credential=entry.credential,
    )


def _content_suggestion(entry: _Entry, start: int, end: int) -> ReferenceSuggestion:
    snippet, highlight_start, highlight_end = _snippet(entry, start, end)
    return ReferenceSuggestion(
        note_id=entry.record.id, first_line=entry.first_line, context="", snippet=snippet,
        highlight_start=highlight_start, highlight_end=highlight_end, credential=entry.credential,
    )


def _masked(entry: _Entry, *, context: str) -> ReferenceSuggestion:
    return ReferenceSuggestion(
        note_id=entry.record.id, first_line=CREDENTIAL_MASK, context=context, snippet="",
        highlight_start=0, highlight_end=0, credential=_PASSWORD,
    )


class _Collected:
    """The suggestions found so far, in their final order, up to the limit."""

    def __init__(self, entries: Dict[str, _Entry], editing_note_id: str) -> None:
        self._entries = entries
        self.suggestions: List[ReferenceSuggestion] = []
        self._seen: Set[str] = {editing_note_id}

    @property
    def is_full(self) -> bool:
        return len(self.suggestions) >= REFERENCE_SUGGESTION_LIMIT

    def has(self, note_id: str) -> bool:
        return note_id in self._seen

    def add(self, suggestion: ReferenceSuggestion) -> None:
        if self.is_full or suggestion.note_id in self._seen:
            return
        self._seen.add(suggestion.note_id)
        if suggestion.first_line == "":
            suggestion = replace(suggestion, first_line=self._as_a_link_reads(suggestion.note_id))
        # A note with nothing to read is no help to choose (agreed 2026-10-26).
        if suggestion.first_line == EMPTY_NOTE_PREVIEW:
            return
        self.suggestions.append(suggestion)

    def _as_a_link_reads(self, note_id: str) -> str:
        """A note with no text of its own reads as a link to it does: one that is only a
        reference as that reference's source (a password masked), else as empty."""
        seen = {note_id}
        entry = self._entries[note_id]
        while entry.first_line == "":
            token = sole_reference_token(entry.record.content)
            if token is None or token.note_id not in self._entries or token.note_id in seen:
                return EMPTY_NOTE_PREVIEW
            seen.add(token.note_id)
            entry = self._entries[token.note_id]
        if entry.is_password:
            return CREDENTIAL_MASK
        return entry.first_line

    def add_with_passwords(self, entry: _Entry) -> None:
        """A first-line match, then the @password notes under it, masked."""
        self.add(_suggestion(entry))
        for child_id in store.get_children(entry.record.id):
            if child_id in self._entries and self._entries[child_id].is_password:
                self.add(_masked(self._entries[child_id], context=entry.first_line))


def _latest(entries: Dict[str, _Entry], by_recency: List[str], collected: _Collected) -> None:
    """With nothing typed yet: the most recently edited notes."""
    for note_id in by_recency:
        if collected.is_full:
            return
        entry = entries[note_id]
        if not entry.is_password:
            collected.add(_suggestion(entry))
            continue
        collected.add(_masked(entry, context=_parent_first_line(entries, entry)))


def _parent_first_line(entries: Dict[str, _Entry], entry: _Entry) -> str:
    parent_id = entry.record.parent_id
    if parent_id is None or parent_id not in entries:
        return ""
    return entries[parent_id].first_line


def _searchable(entries: Dict[str, _Entry], by_recency: List[str], collected: _Collected) -> Iterable[_Entry]:
    """Notes not yet suggested, most recently edited first, until the list is full."""
    for note_id in by_recency:
        if collected.is_full:
            return
        entry = entries[note_id]
        if not entry.is_password and not collected.has(note_id):
            yield entry


def _collect_exact_first_lines(query: str, entries: Dict[str, _Entry], by_recency: List[str], collected: _Collected) -> None:
    for entry in _searchable(entries, by_recency, collected):
        if query in entry.first_line_casefold:
            collected.add_with_passwords(entry)


def _collect_fuzzy_first_lines(typed_words: Tuple[str, ...], entries: Dict[str, _Entry], by_recency: List[str],
                               collected: _Collected) -> None:
    fuzzy = _catalog.fuzzy_first_line_notes(typed_words)
    for entry in _searchable(entries, by_recency, collected):
        if entry.record.id in fuzzy:
            collected.add_with_passwords(entry)


def _collect_exact_texts(query: str, entries: Dict[str, _Entry], by_recency: List[str], collected: _Collected) -> None:
    for entry in _searchable(entries, by_recency, collected):
        start = entry.text_casefold.find(query)
        if start >= 0:
            collected.add(_content_suggestion(entry, start, start + len(query)))


def _collect_fuzzy_texts(typed_words: Tuple[str, ...], entries: Dict[str, _Entry], by_recency: List[str],
                         collected: _Collected) -> None:
    matchers = _catalog.fuzzy_text_matchers(typed_words)
    if not matchers:
        return
    first, rest = matchers[0], matchers[1:]
    for entry in _searchable(entries, by_recency, collected):
        found = first.search(entry.text_casefold)
        if found is not None and all(matcher.search(entry.text_casefold) is not None for matcher in rest):
            collected.add(_content_suggestion(entry, found.start(), found.end()))


def _collect_matches(query: str, entries: Dict[str, _Entry], by_recency: List[str], collected: _Collected) -> None:
    """The four tiers in order, each only while the list has room."""
    typed_words = tuple(_WORD_RE.findall(query))
    _collect_exact_first_lines(query, entries, by_recency, collected)
    if typed_words and not collected.is_full:
        _collect_fuzzy_first_lines(typed_words, entries, by_recency, collected)
    _collect_exact_texts(query, entries, by_recency, collected)
    if typed_words and not collected.is_full:
        _collect_fuzzy_texts(typed_words, entries, by_recency, collected)


def suggest_references(
    *,
    query: str,
    editing_note_id: str,
    copied_note_ids: FrozenSet[str],
    view: Hashable,
    view_note_ids: Callable[[], FrozenSet[str]],
) -> List[ReferenceSuggestion]:
    """`view` names the tab's view (its search and filters) and view_note_ids() gives the notes it
    shows, asked for only when that view hasn't been seen with these notes yet."""
    if not isinstance(query, str) or not isinstance(editing_note_id, str):
        raise TypeError("suggest_references requires a query and the edited note's id")
    entries, by_recency = _catalog.refreshed()
    order = _view_order.ordered(by_recency, view, view_note_ids)
    collected = _Collected(entries, editing_note_id)
    normalized = _normalized(query).casefold()
    def collect(entries: Dict[str, _Entry], order: List[str], collected: _Collected) -> None:
        if normalized == "":
            _latest(entries, order, collected)
            return
        _collect_matches(normalized, entries, order, collected)
    # The same tiers over the copied note alone: matching any of them puts it first.
    collect(entries, [note_id for note_id in copied_note_ids if note_id in entries], collected)
    collect(entries, order, collected)
    return collected.suggestions
