"""Only parents pass tags on; embeds and links pass none (the maintainer, 2026-11-03;
docs/ready-to-build/embeds-pass-no-tags.md). Before, an embed passed its source's tags (and
its whole subtree's) to the host, so a search for a tag listed every note embedding the
note that had it, and embedding a note from a folder pulled the host into that folder.
Links passed none since 2026-10-31."""

from random import Random

import pytest

import app.services.note_store as note_store_module
from app.services.note_store import NotePosition
from app.services.note_store import NoteStore
from app.services.search_index import SearchIndex
from app.services.tag_ontology import TagOntology, compile_rules, parse_rules_text
import app.services.snapshot as snapshot_module


SOURCE = "11111111-1111-4111-8111-111111111111"
HOST = "22222222-2222-4222-8222-222222222222"
CHILD = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"
PARENT = "55555555-5555-4555-8555-555555555555"
HOST_CHILD = "66666666-6666-4666-8666-666666666666"


def _load(monkeypatch, specs):
    """Specs map IDs to (parent, content, accepted tags, proposed tags)."""
    children = {}
    for note_id, (parent, _, _, _) in specs.items():
        if parent not in children:
            children[parent] = []
        children[parent].append(note_id)
    rows = []
    for note_id, (parent, _, _, _) in specs.items():
        siblings = children[parent]
        position = siblings.index(note_id)
        prev_id = None
        next_id = None
        if position > 0:
            prev_id = siblings[position - 1]
        if position + 1 < len(siblings):
            next_id = siblings[position + 1]
        rows.append(dict(id=note_id, parent_id=parent, is_collapsed=False, created_at=None, updated_at=None,
                         prev_id=prev_id, next_id=next_id))
    index = SearchIndex()
    monkeypatch.setattr(note_store_module, "search_index", index)
    monkeypatch.setattr(note_store_module, "get_ontology", TagOntology.empty)
    monkeypatch.setattr(note_store_module, "get_cached_content", lambda n: specs[n][1])
    monkeypatch.setattr(note_store_module, "get_cached_text", lambda n: specs[n][1])
    monkeypatch.setattr(note_store_module, "get_cached_tags", lambda n: specs[n][2])
    monkeypatch.setattr(note_store_module, "get_cached_proposed_tags", lambda n: specs[n][3])
    store = NoteStore()
    store._timing_enabled = False
    store.load_from_db(None, prefetched_rows=rows)
    return store, index


def _save(store, note_id, *, content, tags):
    store.update_note_content(note_id=note_id, plaintext=content, tags=tags, proposed_tags="",
                              updated_at=store.get_note(note_id).updated_at)


def _embedding_specs(reference):
    """PARENT > SOURCE > CHILD, and HOST (tagged host) > HOST_CHILD, HOST holding `reference`
    to SOURCE."""
    return {
        PARENT: (None, "Parent", "ancestor", ""),
        SOURCE: (PARENT, "Source", "source", "source-proposal"),
        CHILD: (SOURCE, "Child", "descendant", ""),
        HOST: (None, f"Host {reference}", "host", ""),
        HOST_CHILD: (HOST, "Host child", "", ""),
    }


@pytest.mark.parametrize("reference", [f"![[{SOURCE}]]", f"[[{SOURCE}]]"], ids=["embed", "link"])
def test_an_embed_or_link_passes_no_tags(monkeypatch, reference):
    store, index = _load(monkeypatch, _embedding_specs(reference))
    assert index.query_note_ids("source") == {SOURCE, CHILD}
    assert index.query_note_ids("source-proposal") == {SOURCE, CHILD}
    assert index.query_note_ids("descendant") == {CHILD}
    assert index.query_note_ids("ancestor") == {PARENT, SOURCE, CHILD}
    # An excluded tag doesn't leave out a note embedding a note with it.
    assert index.query_note_ids("host -source") == {HOST, HOST_CHILD}
    assert store.get_inherited_non_meta_tag_terms(HOST) == frozenset()
    assert store.get_inherited_proposed_non_meta_tag_terms(HOST) == frozenset()
    assert store.get_inherited_non_meta_tag_terms(HOST_CHILD) == {"host"}


def test_parents_still_pass_tags_and_proposals_down(monkeypatch):
    store, index = _load(monkeypatch, {
        PARENT: (None, "Parent", "ancestor @red /*comment*/", "ancestor-proposal"),
        SOURCE: (PARENT, "Source", "", ""),
        CHILD: (SOURCE, "Child", "", ""),
    })
    assert index.query_note_ids("ancestor") == {PARENT, SOURCE, CHILD}
    assert index.query_note_ids("ancestor-proposal") == {PARENT, SOURCE, CHILD}
    assert index.query_note_ids("@red") == {PARENT}
    assert store.get_inherited_non_meta_tag_terms(CHILD) == {"ancestor"}
    assert store.get_inherited_proposed_non_meta_tag_terms(CHILD) == {"ancestor-proposal"}
    _save(store, PARENT, content="Parent", tags="replacement")
    assert index.query_note_ids("ancestor") == set()
    assert index.query_note_ids("replacement") == {PARENT, SOURCE, CHILD}


def test_adding_or_removing_an_embed_changes_no_search_and_recomputes_nothing(monkeypatch):
    store, index = _load(monkeypatch, _embedding_specs(f"[[{SOURCE}]]"))
    affected_sets = []
    original = store._propagate_inherited_tag_terms_locked

    def track(affected):
        affected_sets.append(affected)
        return original(affected)

    monkeypatch.setattr(store, "_propagate_inherited_tag_terms_locked", track)
    for content in (f"Host ![[{SOURCE}]]", f"Host ![[{SOURCE}]] ![[{SOURCE}]]", "Host"):
        _save(store, HOST, content=content, tags="host")
        assert index.query_note_ids("source") == {SOURCE, CHILD}
        assert index.query_note_ids("host") == {HOST, HOST_CHILD}
    assert affected_sets == []
    assert store.get_backlink_counts(SOURCE) == {}


def test_a_tag_change_recomputes_the_note_and_its_descendants_only(monkeypatch):
    store, index = _load(monkeypatch, _embedding_specs(f"![[{SOURCE}]]"))
    affected_sets = []
    original = store._propagate_inherited_tag_terms_locked

    def track(affected):
        affected_sets.append(affected)
        return original(affected)

    monkeypatch.setattr(store, "_propagate_inherited_tag_terms_locked", track)
    _save(store, SOURCE, content="Source", tags="renamed")
    assert affected_sets == [{SOURCE, CHILD}]
    assert index.query_note_ids("renamed") == {SOURCE, CHILD}
    affected_sets.clear()
    store.set_collapsed(HOST, True)
    store.set_collapsed(HOST, False)
    assert affected_sets == []


@pytest.mark.parametrize("bulk", [False, True])
def test_moving_a_note_takes_its_new_parents_tags(monkeypatch, bulk):
    store, index = _load(monkeypatch, {
        PARENT: (None, "Parent", "old-home", ""),
        OTHER: (None, "Other", "new-home", ""),
        CHILD: (PARENT, "Child", "", ""),
        HOST: (None, f"![[{CHILD}]]", "", ""),
    })
    move = NotePosition(note_id=CHILD, parent_id=OTHER, prev_id=None, next_id=None)
    if bulk:
        store.move_notes([move])
    else:
        store.move_note(move)
    assert index.query_note_ids("old-home") == {PARENT}
    assert index.query_note_ids("new-home") == {OTHER, CHILD}
    store.rebuild_search_index_tag_terms()
    assert index.query_note_ids("new-home") == {OTHER, CHILD}


def test_deleting_an_embedded_note_leaves_the_host_alone(monkeypatch):
    store, index = _load(monkeypatch, _embedding_specs(f"![[{SOURCE}]]"))
    store.remove_note(SOURCE)
    assert index.query_note_ids("source") == set()
    assert index.query_note_ids("host") == {HOST, HOST_CHILD}
    assert store.get_inherited_non_meta_tag_terms(HOST) == frozenset()


def test_parent_cycles_still_fail_loudly(monkeypatch):
    store, _ = _load(monkeypatch, {
        HOST: (None, "Host", "foo", ""),
        CHILD: (HOST, "Child", "bar", ""),
    })
    with pytest.raises(RuntimeError, match="hierarchy cycle"):
        store.move_note(NotePosition(note_id=HOST, parent_id=CHILD, prev_id=None, next_id=None))


def _view(store, index, monkeypatch, *, search, is_untagged_view):
    monkeypatch.setattr(snapshot_module, "note_store", store)
    monkeypatch.setattr(snapshot_module, "search_index", index)
    monkeypatch.setattr(snapshot_module, "get_all_locks", lambda: {})
    return snapshot_module.build_view_state(
        editing_note_id=None, find_reveal_note_id=None, search=search, sort_mode="normal", date_filter=None,
        file_filter=None, client_known_note_ids=set(), previous_root_ids=[], visible_top_root_id=None,
        visible_bottom_root_id=None, is_untagged_view=is_untagged_view, start_at_list_end=False,
    )


def test_a_search_shows_the_note_with_the_tag_not_the_notes_embedding_it(monkeypatch):
    store, index = _load(monkeypatch, {
        SOURCE: (None, "Source", "foo", ""),
        CHILD: (SOURCE, "Child", "", ""),
        HOST: (None, f"![[{SOURCE}]]", "", ""),
        HOST_CHILD: (HOST, "Host child", "", ""),
    })
    assert set(_view(store, index, monkeypatch, search="foo", is_untagged_view=False).payloads) == {SOURCE, CHILD}
    # A note whose only tags came through an embed is untagged.
    untagged = _view(store, index, monkeypatch, search=None, is_untagged_view=True)
    assert set(untagged.payloads) == {HOST, HOST_CHILD}


def test_an_embed_still_shows_its_source_and_children(monkeypatch):
    store, index = _load(monkeypatch, {
        SOURCE: (None, "bar", "", ""),
        CHILD: (SOURCE, "baz", "", ""),
        HOST: (None, f"![[{SOURCE}]]", "host", ""),
    })
    state = _view(store, index, monkeypatch, search="host", is_untagged_view=False)
    rendered = state.payloads[HOST]["content"]
    assert f'data-embed-note-id="{SOURCE}"' in rendered
    assert f'data-embed-note-id="{CHILD}"' in rendered
    assert "bar" in rendered and "baz" in rendered


def test_tag_rules_read_each_notes_own_and_parents_tags_only(monkeypatch):
    store, index = _load(monkeypatch, {
        SOURCE: (None, "Source", "foo", ""),
        HOST: (None, f"Special ![[{SOURCE}]]", "", ""),
        CHILD: (HOST, "Child", "", ""),
        OTHER: (None, "Special", "foo", ""),
    })
    ontology = compile_rules(
        rules=parse_rules_text(text='foo => category\n(foo "special") => matched', filename="test"),
        filename="test",
    )
    monkeypatch.setattr(note_store_module, "get_ontology", lambda: ontology)
    store.rebuild_search_index_tag_terms()
    assert index.query_note_ids("category") == {SOURCE, OTHER}
    assert index.query_note_ids("matched") == {OTHER}


@pytest.mark.parametrize("seed", [714, 715, 716])
def test_incremental_updates_match_an_ancestry_oracle(monkeypatch, seed):
    random = Random(seed)
    ids = [f"{n:08x}-1111-4111-8111-111111111111" for n in range(16)]
    tag_count = 4
    specs = {}
    own_tags = {}
    for n, note_id in enumerate(ids):
        parent = None
        if n % 2:
            parent = ids[n - 1]
        targets = random.sample(ids, 2)
        own_tags[note_id] = {f"tag-{n % tag_count}"}
        specs[note_id] = (parent, " ".join(f"![[{target}]]" for target in targets), f"tag-{n % tag_count}", "")
    store, index = _load(monkeypatch, specs)

    def assert_matches_oracle():
        for note_id in ids:
            expected = set()
            current = note_id
            while current is not None:
                expected.update(own_tags[current])
                current = specs[current][0]
            assert index.list_raw_tag_terms_for_note(note_id) == expected

    assert_matches_oracle()
    for _ in range(60):
        note_id = random.choice(ids)
        targets = random.sample(ids, random.randrange(3))
        tags = set(random.sample([f"tag-{n}" for n in range(tag_count)], random.randrange(2)))
        own_tags[note_id] = tags
        content = " ".join(f"![[{target}]]" for target in targets)
        specs[note_id] = (specs[note_id][0], content, " ".join(tags), "")
        _save(store, note_id, content=content, tags=" ".join(tags))
        assert_matches_oracle()
    store.rebuild_search_index_tag_terms()
    assert_matches_oracle()
