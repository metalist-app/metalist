from __future__ import annotations

from app.services.search_index import FOLDER_TAG_END, extract_tags_for_search, search_index
from app.services.search_query import SearchClause, parse_search_query
from app.services.tag_properties import ANY_TAG, IMPLICIT_PROPERTY, PROPERTY_SEPARATOR, PropertyCondition
from app.services.search_text import build_searchable_text_casefold
from app.services.text_terms import text_term_matches
from app.services.store import store
from app.services.tag_case import (
    build_preferred_tag_case_map,
    dedupe_tag_terms_by_casefold,
    prefer_existing_tag_case,
)


def compute_inherited_non_meta_tag_terms(parent_id: str | None) -> set[str]:
    inherited: set[str] = set()
    current_id = parent_id
    while current_id is not None:
        ancestor = store.get(current_id)
        for term in extract_tags_for_search(ancestor.tags):
            if term.startswith("@"):  # meta tags do not inherit
                continue
            inherited.add(term)
        current_id = ancestor.parent_id
    return inherited


def ensure_tags_match_search_query(
    *,
    parent_id: str | None,
    content: str,
    tags: str,
    search_query: str,
) -> str:
    if not isinstance(content, str):
        raise TypeError(f"content must be a string, got {type(content)}")
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")
    if not isinstance(search_query, str):
        raise TypeError(f"search_query must be a string, got {type(search_query)}")

    parsed = parse_search_query(search_query)
    # A stats term (@sum:calories>2000) names no value to give a note: it adds nothing.
    return _tags_matching_clause(parsed.first_clause.without_stats_terms(), parent_id=parent_id, content=content, tags=tags)


def search_clauses_matching_note(note_id: str, search_query: str) -> tuple[SearchClause, ...]:
    """The parts of a search (its OR clauses) a note matches where it is now; none for an
    empty search."""
    if not isinstance(search_query, str):
        raise TypeError(f"search_query must be a string, got {type(search_query)}")
    if search_query.strip() == "":
        return ()
    parsed = parse_search_query(search_query)
    return tuple(clause for clause in parsed.clauses if note_id in search_index.query_clause_note_ids(clause))


def tags_keeping_moved_note_in_search(note_id: str, clauses_matched_before: tuple[SearchClause, ...]) -> str:
    """A note just moved to another parent never leaves the search it was found by
    (docs/ui/search-semantics.md, Moving Notes During Search): when no part of the search it matched before matches it
    at its new place, it gets the tags it misses for the first of them, as its own. A note
    that matched nothing (shown only above a match) keeps its tags."""
    record = store.get(note_id)
    if not clauses_matched_before:
        return record.tags
    for clause in clauses_matched_before:
        if note_id in search_index.query_clause_note_ids(clause):
            return record.tags
    return _tags_matching_clause(
        clauses_matched_before[0].without_stats_terms(),
        parent_id=record.parent_id, content=record.content, tags=record.tags,
    )


def _tags_matching_clause(clause: SearchClause, *, parent_id: str | None, content: str, tags: str) -> str:
    """The note's tags plus what it misses to match the clause at a place under parent_id:
    its required tags not carried or inherited, its property tags, and a comment for each
    required phrase its text lacks."""
    if not clause.required_tags and not clause.required_text and not clause.required_properties:
        return tags

    inherited_non_meta = compute_inherited_non_meta_tag_terms(parent_id)
    explicit_terms = extract_tags_for_search(tags)
    inherited_non_meta_casefold = {term.casefold() for term in inherited_non_meta}
    explicit_terms_casefold = {term.casefold() for term in explicit_terms}
    preferred_by_casefold = build_preferred_tag_case_map(search_index.list_tag_frequencies())

    additions: list[str] = []
    required_tag_terms = dedupe_tag_terms_by_casefold(
        [
            prefer_existing_tag_case(term, preferred_by_casefold)
            for term in sorted(clause.required_tags)
        ]
    )
    # Folder terms add results (docs/ready-to-build/folders-tab-and-multiple-folders.md §4): a
    # note in one of them, or a folder below one, misses none; a note in none gets them all.
    carried_casefold = inherited_non_meta_casefold | explicit_terms_casefold
    folder_terms_casefold = [term.casefold() for term in required_tag_terms if term.endswith(FOLDER_TAG_END)]
    is_in_a_folder = any(
        carried.endswith(FOLDER_TAG_END) and carried.startswith(folder)
        for carried in carried_casefold for folder in folder_terms_casefold
    )
    for term in required_tag_terms:
        if is_in_a_folder and term.endswith(FOLDER_TAG_END):
            continue
        if term.startswith("@"):
            if term.casefold() in explicit_terms_casefold:
                continue
            additions.append(term)
            continue
        if term.casefold() in inherited_non_meta_casefold or term.casefold() in explicit_terms_casefold:
            continue
        if any(term.casefold() == condition.tag.casefold() for condition in clause.required_properties):
            continue  # added below, with its values
        additions.append(term)
    additions += property_tag_tokens(
        clause.required_properties,
        present_casefold=explicit_terms_casefold | inherited_non_meta_casefold,
        preferred_by_casefold=preferred_by_casefold,
    )

    next_tags = tags.strip()
    if additions:
        if next_tags == "":
            next_tags = " ".join(additions)
        else:
            next_tags = f"{next_tags} {' '.join(additions)}"

    if not clause.required_text:
        return next_tags

    searchable = build_searchable_text_casefold(content, next_tags)
    missing_phrases: list[str] = []
    for phrase in clause.required_text:
        if text_term_matches(phrase, searchable):
            continue
        missing_phrases.append(phrase)

    if not missing_phrases:
        return next_tags

    comment_tokens: list[str] = []
    for phrase in missing_phrases:
        if not isinstance(phrase, str):
            raise TypeError(f"search phrase must be a string, got {type(phrase)}")
        if "/*" in phrase or "*/" in phrase:
            continue
        # The words only: a comment matches the term's word boundaries by itself.
        comment_tokens.append(f"/*{phrase.strip()}*/")

    if not comment_tokens:
        return next_tags

    suffix = " ".join(comment_tokens)
    if next_tags == "":
        return suffix
    return f"{next_tags} {suffix}"


def property_tag_tokens(
    conditions: tuple[PropertyCondition, ...], *, present_casefold: set[str],
    preferred_by_casefold: dict[str, str],
) -> list[str]:
    """What a note added in a property search carries (docs/design/tag-properties.md): the
    tag of each property term, with the values its = terms name (jogging:miles=3 adds
    jogging:miles=3; a chain, jogging:miles=3:duration=30, each of its values). Other
    comparisons name no value, so they add the tag alone."""
    values_by_tag: dict[str, list[str]] = {}
    own_value_by_tag: dict[str, str] = {}
    spelling_by_tag: dict[str, str] = {}
    for condition in (link for term in conditions for link in term.links):
        # A property on any tag (:foo="ba") names no tag to give the note.
        if condition.tag == ANY_TAG:
            continue
        key = condition.tag.casefold()
        if key not in values_by_tag:
            values_by_tag[key] = []
            spelling_by_tag[key] = prefer_existing_tag_case(condition.tag, preferred_by_casefold)
        # MAX and MIN pick among notes; they are no value to give one.
        if condition.operator != "=" or condition.is_extreme:
            continue
        # The tag's own value (author="Le Guin") is written on the tag, not as a property.
        if condition.name == IMPLICIT_PROPERTY:
            own_value_by_tag[key] = condition.value_text
            continue
        values_by_tag[key].append(f"{condition.name}={condition.value_text}")
    tokens: list[str] = []
    for key, values in values_by_tag.items():
        tag = spelling_by_tag[key]
        if key in own_value_by_tag:
            tag = f"{tag}={own_value_by_tag[key]}"
        if values or key in own_value_by_tag:
            tokens.append(PROPERTY_SEPARATOR.join([tag, *values]))
        elif key not in present_casefold:
            tokens.append(tag)
    return tokens


__all__ = [
    "compute_inherited_non_meta_tag_terms",
    "property_tag_tokens",
    "ensure_tags_match_search_query",
    "search_clauses_matching_note",
    "tags_keeping_moved_note_in_search",
]
