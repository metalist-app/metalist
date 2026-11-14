"""Values follow tags in a search (agreed 2026-11-01; docs/ui/search-semantics.md, Super Tag
Searches): through parents only, never embeds or links (2026-11-03); the nearest value wins;
missing-value searches and stats figures stay the note's own. Before, a search on values found only the
note the value was written on, so an import's search (imported:source=obsidian:at=...)
showed every note under the imported files as grey bars."""

import pytest

import app.services.note_store as note_store_module
from app.services.note_store import NoteStore
from app.services.search_index import SearchIndex
from app.services.tag_ontology import TagOntology

RUN = "10000000-0000-4000-8000-000000000001"
RUN_NOTE = "10000000-0000-4000-8000-000000000002"
KNEE = "10000000-0000-4000-8000-000000000003"
LAP = "10000000-0000-4000-8000-000000000004"
LONG_RUN = "10000000-0000-4000-8000-000000000005"
LONG_RUN_NOTE = "10000000-0000-4000-8000-000000000006"
BARE_RUN = "10000000-0000-4000-8000-000000000007"
BARE_RUN_NOTE = "10000000-0000-4000-8000-000000000008"
WEEK = "10000000-0000-4000-8000-000000000009"
WEEK_DAY = "10000000-0000-4000-8000-00000000000a"
LINKING = "10000000-0000-4000-8000-00000000000b"
MEAL = "10000000-0000-4000-8000-00000000000c"
MEAL_TOTAL = "10000000-0000-4000-8000-00000000000d"
FILE = "10000000-0000-4000-8000-00000000000e"
FILE_SECTION = "10000000-0000-4000-8000-00000000000f"
FILE_PARAGRAPH = "10000000-0000-4000-8000-000000000010"
TRAINING = "10000000-0000-4000-8000-000000000011"
TRAINING_BLOCK = "10000000-0000-4000-8000-000000000012"
TRAINING_DAY = "10000000-0000-4000-8000-000000000013"

IMPORT_TAG = "imported:source=obsidian:at=2026-11-01T10:00"

# id: (parent, content, tags)
NOTES = {
    RUN: (None, "Morning run", "jogging:miles=3"),
    RUN_NOTE: (RUN, "Felt good", ""),
    KNEE: (RUN, "Knee hurt at the end", "knee"),
    LAP: (RUN, "Warm-up lap", "jogging:miles=1"),
    LONG_RUN: (None, "Long run", "jogging:miles=12"),
    LONG_RUN_NOTE: (LONG_RUN, "Bonked at 10", ""),
    BARE_RUN: (None, "Run, distance not noted", "jogging"),
    BARE_RUN_NOTE: (BARE_RUN, "Rainy", ""),
    WEEK: (None, f"Week review ![[{RUN}]]", ""),
    WEEK_DAY: (WEEK, "Monday", ""),
    LINKING: (None, f"See [[{RUN}]]", ""),
    MEAL: (None, "Big dinner", "meal:calories=2500"),
    MEAL_TOTAL: (MEAL, "Total", "@sum=calories"),
    FILE: (None, "Plan", IMPORT_TAG),
    FILE_SECTION: (FILE, "Goals", ""),
    FILE_PARAGRAPH: (FILE_SECTION, "Ship it", ""),
    TRAINING: (None, "Training plan", "jogging:miles=10"),
    TRAINING_BLOCK: (TRAINING, "Easy week", "jogging:miles=1"),
    TRAINING_DAY: (TRAINING_BLOCK, "Monday", ""),
}


@pytest.fixture
def index(monkeypatch) -> SearchIndex:
    rows = []
    for note_id, (parent, _content, _tags) in NOTES.items():
        siblings = [other for other, (other_parent, _, _) in NOTES.items() if other_parent == parent]
        position = siblings.index(note_id)
        prev_id = None
        next_id = None
        if position > 0:
            prev_id = siblings[position - 1]
        if position + 1 < len(siblings):
            next_id = siblings[position + 1]
        rows.append(dict(
            id=note_id, parent_id=parent, is_collapsed=False, created_at=None, updated_at=None,
            prev_id=prev_id, next_id=next_id,
        ))
    search_index = SearchIndex()
    monkeypatch.setattr(note_store_module, "search_index", search_index)
    monkeypatch.setattr(note_store_module, "get_ontology", TagOntology.empty)
    monkeypatch.setattr(note_store_module, "get_cached_content", lambda note_id: NOTES[note_id][1])
    monkeypatch.setattr(note_store_module, "get_cached_text", lambda note_id: NOTES[note_id][1])
    monkeypatch.setattr(note_store_module, "get_cached_tags", lambda note_id: NOTES[note_id][2])
    monkeypatch.setattr(note_store_module, "get_cached_proposed_tags", lambda note_id: "")
    store = NoteStore()
    store._timing_enabled = False
    store.load_from_db(None, prefetched_rows=rows)
    monkeypatch.setattr(note_store_module, "store", store)
    return search_index


def test_a_child_of_a_run_has_its_runs_values(index: SearchIndex) -> None:
    found = index.query_note_ids("jogging:miles>2")
    assert {RUN, RUN_NOTE, KNEE} <= found
    assert {LONG_RUN, LONG_RUN_NOTE} <= found


def test_a_childs_own_value_beats_its_parents(index: SearchIndex) -> None:
    assert LAP not in index.query_note_ids("jogging:miles>2")
    assert LAP in index.query_note_ids("jogging:miles<2")


def test_the_nearest_ancestors_value_wins(index: SearchIndex) -> None:
    assert TRAINING_DAY not in index.query_note_ids("jogging:miles>5")
    assert TRAINING_DAY in index.query_note_ids("jogging:miles=1")


def test_a_value_combines_with_a_tag_on_a_note_below_it(index: SearchIndex) -> None:
    # The week embeds the run, knee note and all, but an embed passes neither (2026-11-03).
    assert index.query_note_ids("jogging:miles>2 knee") == {KNEE}


def test_an_excluded_value_leaves_out_the_notes_under_it(index: SearchIndex) -> None:
    found = index.query_note_ids("jogging -jogging:miles>10")
    assert LONG_RUN not in found and LONG_RUN_NOTE not in found
    assert {RUN, RUN_NOTE, BARE_RUN, BARE_RUN_NOTE} <= found


def test_a_missing_value_is_still_the_notes_own(index: SearchIndex) -> None:
    found = index.query_note_ids("jogging:miles?")
    assert BARE_RUN in found
    assert BARE_RUN_NOTE not in found, "it carries jogging only by inheritance"
    assert RUN_NOTE not in found


def test_max_keeps_the_longest_run_and_the_notes_under_it(index: SearchIndex) -> None:
    assert index.query_note_ids("jogging:miles=MAX") == {LONG_RUN, LONG_RUN_NOTE}


def test_a_stats_figure_never_reads_an_inherited_value(index: SearchIndex) -> None:
    assert MEAL_TOTAL not in index.query_note_ids("@sum:calories>2000")


def test_an_embed_or_link_passes_no_values(index: SearchIndex) -> None:
    found = index.query_note_ids("jogging:miles=3")
    assert RUN in found
    assert not {WEEK, WEEK_DAY, LINKING} & found


def test_an_imports_search_finds_every_note_of_its_files(index: SearchIndex) -> None:
    assert index.query_note_ids(IMPORT_TAG) == {FILE, FILE_SECTION, FILE_PARAGRAPH}


def test_suggestions_after_a_value_read_inherited_values_too(index: SearchIndex) -> None:
    assert "knee" in index.suggest_all_tag_completions(query="jogging:miles>2 kn")


# Search suggestions run beside changes (2026-11-14), so a note can be deleted between the index's
# reading and the tree's: it is no longer found, and nothing fails. A search answering a view runs
# in the vault's write turn and never meets it.
def _deleted_before_the_tree_is_read(index: SearchIndex, monkeypatch, reader_name: str, *deleted: str) -> None:
    store = note_store_module.store
    reader = getattr(index, reader_name)

    def deleting_first(*args):
        with store._lock:
            for note_id in deleted:
                if note_id in store._note_map:
                    del store._note_map[note_id]
        return reader(*args)

    monkeypatch.setattr(index, reader_name, deleting_first)


def test_a_note_deleted_while_its_inherited_values_are_read_is_not_found(index: SearchIndex, monkeypatch) -> None:
    _deleted_before_the_tree_is_read(index, monkeypatch, "_inherited_values_reader", RUN_NOTE)
    found = index.query_note_ids("jogging:miles>2")
    assert RUN_NOTE not in found
    assert {RUN, KNEE, LONG_RUN} <= found


def test_notes_under_a_parent_deleted_meanwhile_are_not_found(index: SearchIndex, monkeypatch) -> None:
    _deleted_before_the_tree_is_read(index, monkeypatch, "_inherited_values_reader", RUN)
    found = index.query_note_ids("jogging:miles>2")
    assert not {RUN, RUN_NOTE, KNEE} & found
    assert {LONG_RUN, LONG_RUN_NOTE} <= found


def test_a_note_deleted_while_its_stats_figure_is_read_is_not_found(index: SearchIndex, monkeypatch) -> None:
    _deleted_before_the_tree_is_read(index, monkeypatch, "_stats_reader", MEAL_TOTAL)
    assert MEAL_TOTAL not in index.query_note_ids("@sum:calories")
