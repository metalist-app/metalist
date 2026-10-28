from types import SimpleNamespace

import app.usecases.search_comment_autofill as search_comment_autofill_module
from app.usecases.search_comment_autofill import compute_initial_tags_for_new_note


def test_compute_initial_tags_for_new_note_keeps_meta_for_root() -> None:
    tags = compute_initial_tags_for_new_note(
        parent_id=None,
        search_query="@bullets",
    )
    assert tags == "@bullets"


def test_compute_initial_tags_for_new_note_drops_meta_for_children() -> None:
    tags = compute_initial_tags_for_new_note(
        parent_id="parent-note",
        search_query="@bullets",
    )
    assert tags == ""


def test_compute_initial_tags_for_new_note_uses_existing_tag_case(monkeypatch) -> None:
    monkeypatch.setattr(
        search_comment_autofill_module.search_index,
        "list_tag_frequencies",
        lambda: {"ML3": 4, "ml3": 1},
    )

    tags = compute_initial_tags_for_new_note(
        parent_id=None,
        search_query="ml3",
    )

    assert tags == "ML3"


def test_compute_initial_tags_for_new_note_dedupes_case_equivalent_search_tags(monkeypatch) -> None:
    monkeypatch.setattr(
        search_comment_autofill_module.search_index,
        "list_tag_frequencies",
        lambda: {"ML3": 4},
    )

    tags = compute_initial_tags_for_new_note(
        parent_id=None,
        search_query="ml3 ML3",
    )

    assert tags == "ML3"


def test_compute_initial_tags_for_new_note_uses_only_first_or_clause() -> None:
    tags = compute_initial_tags_for_new_note(
        parent_id=None,
        search_query='alpha beta "first phrase" OR gamma "second phrase"',
    )

    assert tags == "alpha beta /*first phrase*/"


def test_compute_initial_tags_for_new_note_compares_inherited_tags_case_insensitively(monkeypatch) -> None:
    monkeypatch.setattr(
        search_comment_autofill_module.search_index,
        "list_tag_frequencies",
        lambda: {"ML3": 4},
    )
    monkeypatch.setattr(
        search_comment_autofill_module,
        "store",
        SimpleNamespace(
            get=lambda note_id: SimpleNamespace(
                id=note_id,
                parent_id=None,
                content="",
                tags="ML3",
            )
        ),
    )

    tags = compute_initial_tags_for_new_note(
        parent_id="parent-note",
        search_query="ml3",
    )

    assert tags == ""
