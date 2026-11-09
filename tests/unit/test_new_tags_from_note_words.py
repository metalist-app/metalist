"""A word of the note's text is offered as a brand new tag only once no existing tag matches
what is typed (docs/ui/tag-bar.md, "Tag Suggestions")."""

from __future__ import annotations

import pytest

from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required
from app.services import auth_service
from app.services.content_cache import clear_cache
from app.services.file_registry import file_registry
from app.services.note_store import store
from app.services.ontology_rules_store import bootstrap_ontology_rules_store
from app.services.link_titles import link_title_store
import app.services.tag_suggestions as tag_suggestions_module
from app.services.tag_suggestions import suggest_tags_for_note
from app.services.tag_words_in_note import tags_from_words
from app.usecases.create_note import apply_insert_note
from tests.unit.test_segment_aware_tag_suggestions import _EmptyOntology, _build_ontology
from tests.unit.test_tag_suggestion_reasons import _reasons, _use

_LIMIT = 20
_TEXT = "Went to Yellowstone with Priya to see Old Faithful"
_VIDEO = "https://www.youtube.com/watch?v=GYx4sourdough"


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


def _note(note_id: str, *, content: str, tags: str, parent_id: str | None) -> None:
    apply_insert_note(note_id, parent_id, None, None, "", content=f"<div>{content}</div>", tags=tags, proposed_tags="")


def _typed(prefix: str, *, written: tuple[str, ...]) -> list[str]:
    """The tag bar sends what is typed as its last token."""
    return suggest_tags_for_note(
        note_id="trip", anchors=[], explicit_tags=[*written, prefix], prefix=prefix,
        content_html=store.get_note("trip").content, limit=_LIMIT,
    )


def test_an_existing_tag_typed_in_full_still_rules_the_words_out(live_database) -> None:
    _note("colors", content="other", tags="yellow", parent_id=None)
    _note("trip", content=_TEXT, tags="", parent_id=None)
    assert _typed("yel", written=()) == ["yellow"]
    # Enter on a word here would turn the real tag into a new one.
    assert _typed("yellow", written=()) == []
    assert _typed("Yellow", written=()) == []
    assert _typed("yellows", written=()) == ["yellowstone"]


def test_a_word_is_offered_when_nothing_matches(live_database) -> None:
    _note("colors", content="other", tags="crimson", parent_id=None)
    _note("trip", content=_TEXT, tags="", parent_id=None)
    assert _typed("yel", written=()) == ["yellowstone"]


def test_a_tag_matching_by_a_later_part_of_its_name_rules_the_words_out(live_database) -> None:
    _note("rocks", content="other", tags="gem-stone", parent_id=None)
    _note("trip", content="stonehenge", tags="", parent_id=None)
    assert _typed("stone", written=()) == ["gem-stone"]


def test_a_built_in_tag_rules_the_words_out(live_database) -> None:
    _note("trip", content="Bolivia", tags="", parent_id=None)
    assert _typed("bol", written=()) == ["@bold"]


def test_a_tag_already_in_the_bar_is_not_offered_again(live_database) -> None:
    _note("trip", content=_TEXT, tags="", parent_id=None)
    assert _typed("yel", written=("Yellowstone",)) == []


def test_a_synonym_of_a_tag_in_the_bar_is_not_offered(live_database, monkeypatch: pytest.MonkeyPatch) -> None:
    ontology = _build_ontology(text="yellowstone = geyser-park\n")
    monkeypatch.setattr(tag_suggestions_module, "get_ontology", lambda: ontology)
    _note("trip", content=_TEXT, tags="", parent_id=None)
    assert _typed("yel", written=("geyser-park",)) == []


def test_a_parents_or_childs_words_are_not_offered(live_database) -> None:
    _note("parent", content="Yosemite", tags="", parent_id=None)
    _note("trip", content=_TEXT, tags="", parent_id="parent")
    _note("child", content="Zion", tags="", parent_id="trip")
    assert _typed("yos", written=()) == []
    assert _typed("zi", written=()) == []


class _Titles:
    def get_ok_title(self, url: str) -> str | None:
        assert url == _VIDEO, url
        return "Sourdough Starter From Scratch - YouTube"


@pytest.fixture
def linked_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(link_title_store, "get_ok_title", _Titles().get_ok_title)
    monkeypatch.setattr(link_title_store, "get_revision", lambda: 0)
    _use(monkeypatch, rows=[("other", "cooking")], ontology=_EmptyOntology())


def test_a_word_in_a_links_title_is_offered_and_says_where_it_is(linked_note) -> None:
    assert _reasons(anchors=[], prefix="scr", content=_VIDEO) == {
        "scratch": ('Named in the title of a link in this note: "scratch"', "Not a tag yet"),
    }


def test_a_word_in_the_notes_text_says_so_and_comes_before_a_titles(linked_note) -> None:
    assert _reasons(anchors=[], prefix="scr", content=f"scrap {_VIDEO}") == {
        "scrap": ('Named in this note: "scrap"', "Not a tag yet"),
        "scratch": ('Named in the title of a link in this note: "scratch"', "Not a tag yet"),
    }


def test_a_web_address_counts_only_by_its_sites_name(linked_note) -> None:
    assert _reasons(anchors=[], prefix="wat", content=_VIDEO) == {}


_WORDS = "Went to Yellowstone with Old Faithful, and Julie's dog at McDonald"


@pytest.mark.parametrize(("typed", "offered"), [
    ("yel", ["yellowstone"]),
    ("Yel", ["Yellowstone"]),
    ("Y", ["Yellowstone"]),
    ("YEL", ["YELLOWSTONE"]),
    ("Mc", ["McDonald"]),
    ("McD", ["McDonald"]),
    ("mcd", ["mcdonald"]),
    ("low", []),
    ("yellowstone", []),
    ("Yellowstone", []),
    ("ol", ["old"]),
    ("old", []),
    ("old-", ["old-faithful"]),
    ("old_", ["old_faithful"]),
    ("old/", ["old/faithful"]),
    ("old.", ["old.faithful"]),
    ("old-fa", ["old-faithful"]),
    ("Old-", ["Old-Faithful"]),
    ("OLD-", ["OLD-FAITHFUL"]),
    ("old-Fa", ["old-Faithful"]),
    ("ol-", []),
    ("old--", []),
    ("-old", []),
    ("old-faithful", []),
    ("faithful-", []),
    ("jul", ["julie"]),
    ("old:fa", []),
])
def test_what_typing_offers_from_the_words(typed: str, offered: list[str]) -> None:
    assert list(tags_from_words(typed=typed, text=_WORDS, limit=_LIMIT)) == offered


def test_a_new_line_separates_two_words() -> None:
    assert tags_from_words(typed="old-", text="Old\nFaithful", limit=_LIMIT) == ()


def test_each_further_connector_asks_for_one_more_word() -> None:
    assert tags_from_words(typed="old-faithful-", text="Old Faithful Geyser", limit=_LIMIT) == ("old-faithful-geyser",)


def test_a_curly_apostrophe_is_a_possessive_too() -> None:
    assert tags_from_words(typed="jul", text="Julie’s dog", limit=_LIMIT) == ("julie",)


def test_words_come_in_the_texts_order_once_each_up_to_the_limit() -> None:
    text = "Yellowstone yellow YELLOWSTONE yelp"
    assert tags_from_words(typed="yel", text=text, limit=_LIMIT) == ("yellowstone", "yellow", "yelp")
    assert tags_from_words(typed="yel", text=text, limit=1) == ("yellowstone",)
