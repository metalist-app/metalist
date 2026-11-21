"""What an empty tag bar offers (the maintainer, 2026-11-19, with a note reading "bug: dragging a
.md file…", tagged `ML3`, in the search `ML3 -ML3-business -journal`: the bar offered `__file__`
first, then `business`, `bug`, `ML3-business`, `tags`, `tag`). Three rules
(docs/ui/tag-bar.md, "Tag Suggestions"):

1. connectors around one word (`__file__`) do not make a tag more specific than a plain word the
   note names as well (`bug`): the more used of the two comes first;
2. a tag the current search excludes (`-ML3-business`) is not offered with nothing typed, since
   accepting it takes the note out of the list; typing its letters still offers it;
3. of a singular and its plural (`tag`, `tags`), only the more used is offered with nothing
   typed, where the first of the two stood."""

from __future__ import annotations

import pytest

from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required
from app.services import auth_service
from app.services.content_cache import clear_cache
from app.services.file_registry import file_registry
from app.services.note_store import store
from app.services.ontology_rules_store import bootstrap_ontology_rules_store
from app.services.search_query import tags_excluded_by_search
from app.services.tag_suggestions import suggest_tags_for_note, suggest_tags_with_reasons_for_note
from app.usecases.create_note import apply_insert_note

_LIMIT = 20
BUG_NOTE = "<div>bug: dragging a .md file into an empty note should add tag @markdown</div>"
SEARCH = "ML3 -ML3-business -journal"


@pytest.fixture
def live_database(tmp_path, monkeypatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "fixture.metalist.db")
    monkeypatch.setattr(SafeSession, "_use_memory", False)
    clear_encryption_key()
    set_encryption_required(False)
    clear_cache()
    store.reset()
    file_registry.reset()
    session = SafeSession()
    auth_service.AuthService(session).initialize_settings()
    bootstrap_ontology_rules_store(connection=session.connection())
    store.load_from_db(None, prefetched_rows=[])
    yield session
    session.close()
    store.reset()
    clear_cache()
    file_registry.reset()
    clear_encryption_key()
    set_encryption_required(False)


def _note(note_id: str, *, content: str, tags: str) -> None:
    apply_insert_note(note_id, None, None, None, "", content=content, tags=tags, proposed_tags="")


def _offered(note_id: str, *, tags: list[str], prefix: str, search: str) -> list[str]:
    # The tag bar sends the tag being typed as its last token.
    in_the_bar = [tag for tag in (*tags, prefix) if tag != ""]
    return [suggestion.tag for suggestion in suggest_tags_with_reasons_for_note(
        note_id=note_id, anchors=tags, explicit_tags=in_the_bar, prefix=prefix,
        content_html=store.get_note(note_id).content, limit=_LIMIT, search=search,
    )]


# 1. Connectors around one word.

def test_a_plain_word_the_note_names_comes_before_a_less_used_word_wrapped_in_connectors(live_database) -> None:
    for index in range(3):
        _note(f"bug-{index}", content="<div>other</div>", tags="bug")
    _note("dunder", content="<div>other</div>", tags="__file__")
    _note("report", content=BUG_NOTE, tags="")

    offered = _offered("report", tags=[], prefix="", search="")

    assert offered.index("bug") < offered.index("__file__")


def test_a_wrapped_word_still_comes_first_when_it_is_the_more_used(live_database) -> None:
    for index in range(3):
        _note(f"dunder-{index}", content="<div>other</div>", tags="__file__")
    _note("bug-0", content="<div>other</div>", tags="bug")
    _note("report", content=BUG_NOTE, tags="")

    offered = _offered("report", tags=[], prefix="", search="")

    assert offered.index("__file__") < offered.index("bug")


def test_connectors_between_words_still_make_a_tag_more_specific(live_database) -> None:
    # `empty-note` joins two words the note names: it stays ahead of the far more used `bug`.
    for index in range(5):
        _note(f"bug-{index}", content="<div>other</div>", tags="bug")
    _note("joined", content="<div>other</div>", tags="empty-note")
    _note("report", content=BUG_NOTE, tags="")

    offered = _offered("report", tags=[], prefix="", search="")

    assert offered.index("empty-note") < offered.index("bug")


# 2. Tags the search excludes.

@pytest.mark.parametrize(
    ("search", "excluded"),
    [
        ("", frozenset()),
        (SEARCH, frozenset({"ml3-business", "journal"})),
        ("ML3 -Journal", frozenset({"journal"})),
        # A tag one OR part excludes can still be on a note the other part shows.
        ("ML3 -journal OR recipes", frozenset()),
        ("ML3 -journal OR recipes -journal -draft", frozenset({"journal"})),
        ('ML3 -"some words"', frozenset()),
    ],
)
def test_the_tags_a_search_excludes(search: str, excluded: frozenset[str]) -> None:
    assert tags_excluded_by_search(search) == excluded


@pytest.fixture
def business_notes(live_database):
    for index in range(3):
        _note(f"llc-{index}", content="<div>other</div>", tags="ML3 ML3-business LLC")
    _note("report", content="<div>report</div>", tags="ML3")


def test_a_tag_the_search_excludes_is_not_offered_with_nothing_typed(business_notes) -> None:
    assert "ML3-business" in _offered("report", tags=["ML3"], prefix="", search="ML3")

    offered = _offered("report", tags=["ML3"], prefix="", search=SEARCH)

    assert "ML3-business" not in offered
    assert "LLC" in offered, "the tags that go with ML3 are still offered"


def test_typing_its_letters_still_offers_a_tag_the_search_excludes(business_notes) -> None:
    assert "ML3-business" in _offered("report", tags=["ML3"], prefix="ML3-", search=SEARCH)
    assert "ML3-business" in _offered("report", tags=["ML3"], prefix="bus", search=SEARCH)


def test_the_suggestions_asked_for_without_a_search_leave_nothing_out(business_notes) -> None:
    # The AI's vocabulary and Tag Notes in View… ask without a view's search.
    assert "ML3-business" in suggest_tags_for_note(
        note_id="report", anchors=["ML3"], explicit_tags=["ML3"], prefix="",
        content_html=store.get_note("report").content, limit=_LIMIT,
    )


# 3. A singular and its plural.

def _tagged(count: int, *, name: str, tags: str) -> None:
    for index in range(count):
        _note(f"{name}-{index}", content="<div>other</div>", tags=tags)


def test_only_the_more_used_of_a_singular_and_its_plural_is_offered(live_database) -> None:
    _tagged(3, name="singular", tags="ML3 tag")
    _tagged(2, name="plural", tags="ML3 tags")
    _note("report", content="<div>report</div>", tags="ML3")

    offered = _offered("report", tags=["ML3"], prefix="", search="")

    assert "tag" in offered
    assert "tags" not in offered


def test_the_plural_is_the_one_offered_when_it_is_the_more_used(live_database) -> None:
    _tagged(2, name="singular", tags="ML3 tag")
    _tagged(3, name="plural", tags="ML3 tags")
    _note("report", content="<div>report</div>", tags="ML3")

    offered = _offered("report", tags=["ML3"], prefix="", search="")

    assert "tags" in offered
    assert "tag" not in offered


def test_the_one_offered_stands_where_the_first_of_the_two_stood(live_database) -> None:
    # The note names `tags`, so it ranks first of the two; `tag` is the more used.
    _tagged(4, name="singular", tags="ML3 tag")
    _tagged(1, name="plural", tags="ML3 tags")
    _tagged(2, name="other", tags="ML3 LLC")
    _note("report", content="<div>about tags</div>", tags="ML3")

    with_pair = suggest_tags_for_note(
        note_id="report", anchors=["ML3"], explicit_tags=["ML3"], prefix="",
        content_html=store.get_note("report").content, limit=_LIMIT,
    )

    assert with_pair[0] == "tag", with_pair
    assert "tags" not in with_pair


def test_typing_offers_both_spellings(live_database) -> None:
    _tagged(3, name="singular", tags="ML3 tag")
    _tagged(2, name="plural", tags="ML3 tags")
    _note("report", content="<div>report</div>", tags="ML3")

    offered = _offered("report", tags=["ML3"], prefix="ta", search="")

    assert offered[:2] == ["tag", "tags"]
