"""Several folders in a search add results, and a folder tag implies the folders above it
(docs/ready-to-build/folders-tab-and-multiple-folders.md §3, §4, §6, agreed with the maintainer 2026-11-11)."""
from __future__ import annotations

import pytest

from app.services.search_index import NOTHING_INHERITED, SearchIndex, SearchRecord, extract_tags_for_search
from app.services.tag_ontology import TagOntology, compile_rules, parent_folder_tags, parse_rules_text
from app.usecases.search_context_tags import ensure_tags_match_search_query


def _index(tags_by_note: dict[str, str], ontology: TagOntology) -> SearchIndex:
    """The index as the note store fills it: each note's tags with what they imply."""
    index = SearchIndex()
    index.attach_inherited_values_reader(lambda note_ids: {note_id: NOTHING_INHERITED for note_id in note_ids})
    index.rebuild(
        [SearchRecord(note_id=note_id, content_text=note_id, tags=tags,
                      tag_terms=ontology.infer_effective_tags(base_tags=extract_tags_for_search(tags), plaintext=note_id))
         for note_id, tags in tags_by_note.items()],
        raw_tag_terms_by_id={note_id: extract_tags_for_search(tags) for note_id, tags in tags_by_note.items()},
        progress_update=lambda processed: None, progress_interval=len(tags_by_note),
    )
    return index


_NOTES = {
    "call the plumber": "Projects/",
    "kickoff agenda": "Projects/Client-A/ @todo",
    "old invoice": "Archive/ @todo",
    "old letter": "Archive/",
    "pancakes": "Recipes/ @todo",
    "loose": "@todo",
}


@pytest.fixture
def vault() -> SearchIndex:
    return _index(_NOTES, TagOntology.empty())


# §3: folder terms in a clause add results; every other term narrows; -A/ subtracts.
@pytest.mark.parametrize(
    ("search", "found"),
    [
        ("Projects/ Archive/", {"call the plumber", "kickoff agenda", "old invoice", "old letter"}),
        ("Projects/ Archive/ @todo", {"kickoff agenda", "old invoice"}),
        ("archive/ projects/client-a/ @todo", {"kickoff agenda", "old invoice"}),
        ("Projects/ -Projects/Client-A/", {"call the plumber"}),
        ("@todo -Archive/", {"kickoff agenda", "pancakes", "loose"}),
        ("Projects/ OR Archive/ @todo", {"call the plumber", "kickoff agenda", "old invoice"}),
        ("Projects/ Missing/", {"call the plumber", "kickoff agenda"}),
    ],
)
def test_folders_in_a_clause_add_results(vault: SearchIndex, search: str, found: set[str]) -> None:
    assert vault.query_note_ids(search) == found


# §3: a folder suggested after a folder is read against the rest of the clause, as it adds results.
def test_a_folder_is_suggested_when_it_adds_results(vault: SearchIndex) -> None:
    assert "Archive/" in vault.suggest_all_tag_completions(query="Projects/ A")
    assert "Archive/" in vault.suggest_all_tag_completions(query="Projects/ @todo A")
    # Recipes holds a to-do, but no note there has `@urgent`.
    assert "Recipes/" not in _index({**_NOTES, "urgent": "Projects/ @urgent"}, TagOntology.empty()).suggest_all_tag_completions(
        query="Projects/ @urgent R")


# §6: a folder tag implies the folders above it, so a rule on a folder reaches every folder below.
def test_a_folder_implies_its_parent_folders_rules_included() -> None:
    assert parent_folder_tags("Projects/Client-A/2026/") == ("Projects/", "Projects/Client-A/")
    assert parent_folder_tags("Projects/") == ()
    assert parent_folder_tags("Projects/notes") == ()
    rules = compile_rules(rules=parse_rules_text(text="Projects/ => work\n", filename="rules"), filename="rules")
    inferred = rules.infer_effective_tags(base_tags=frozenset({"Projects/Client-A/"}), plaintext="")
    assert inferred == frozenset({"Projects/Client-A/", "Projects/", "work"})
    assert rules.infer_implication_only(base_tags=frozenset({"Projects/Client-A/"})) == inferred
    index = _index({"kickoff agenda": "Projects/Client-A/", "loose": "Archive/"}, rules)
    assert index.query_note_ids("work") == {"kickoff agenda"}


# §6, the other way round: a rule giving a folder files the note in the folders above it too.
def test_a_folder_a_rule_gives_implies_its_parents() -> None:
    rules = compile_rules(rules=parse_rules_text(text="invoice => Archive/2026/\n", filename="rules"), filename="rules")
    assert rules.infer_effective_tags(base_tags=frozenset({"invoice"}), plaintext="") == frozenset(
        {"invoice", "Archive/2026/", "Archive/"})


# §4: a note made or moved under `A/ B/` gets every folder when it is in none of them; in one (or a
# folder below one), it gets none.
@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ("", {"Projects/", "Archive/", "@todo"}),
        ("Projects/Client-A/", {"Projects/Client-A/", "@todo"}),
        ("Archive/ @todo", {"Archive/", "@todo"}),
        ("Recipes/", {"Recipes/", "Projects/", "Archive/", "@todo"}),
    ],
)
def test_a_note_gets_every_folder_only_when_in_none(tags: str, expected: set[str]) -> None:
    tagged = ensure_tags_match_search_query(parent_id=None, content="", tags=tags, search_query="Projects/ Archive/ @todo")
    assert set(tagged.split()) == expected
