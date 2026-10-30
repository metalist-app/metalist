"""OR on a rule's left side (docs/design/ontology-rules-v1.md; agreed 2026-10-25): groups
separated by OR, adjacent atoms ANDed as in a search, each group its own rule; About this
tag names the group that inferred a tag."""

from __future__ import annotations

import pytest

import app.api.routes.ontology as ontology_route
from app.services.tag_ontology import OntologyParseError, TagAtom, compile_rules, parse_rules_text
from app.services.tag_suggestion_reasons import AppliesThrough


def _rules(text: str):
    return parse_rules_text(text=text, filename="rules")


def test_or_is_one_rule_per_group() -> None:
    rules = _rules("metalist:version OR metalist version => metalist-version")
    assert [(tuple(type(atom).__name__ for atom in rule.lhs), rule.rhs) for rule in rules] == [
        (("PropertyAtom",), "metalist-version"),
        (("TagAtom", "TagAtom"), "metalist-version"),
    ]


def test_adjacent_atoms_are_anded_and_parentheses_still_group() -> None:
    assert [rule.lhs for rule in _rules("a b OR c d e => f")] == [
        (TagAtom("a"), TagAtom("b")), (TagAtom("c"), TagAtom("d"), TagAtom("e")),
    ]
    assert [rule.lhs for rule in _rules("(a b c) => d")] == [(TagAtom("a"), TagAtom("b"), TagAtom("c"))]
    assert [rule.lhs for rule in _rules('(a b) OR "kyoto trip" => travel')][0] == (TagAtom("a"), TagAtom("b"))


@pytest.mark.parametrize(("line", "message"), [
    ("OR a => b", "OR needs a term before it"),
    ("a OR => b", "OR needs a term after it"),
    ("a OR OR b => c", "OR needs a term before it"),
    ("a OR b = c", "'=' is only allowed between tag atoms"),
])
def test_a_misplaced_or_says_so(line: str, message: str) -> None:
    with pytest.raises(OntologyParseError, match=message):
        _rules(line)


def test_a_group_infers_only_when_all_of_it_is_there() -> None:
    ontology = compile_rules(rules=_rules("a b OR c d e => f"), filename="rules")
    satisfied = {rule.rhs for rule in ontology.matcher_rules if rule.satisfied(plaintext="", tags={"c", "d", "e"})}
    assert satisfied == {"f"}
    assert not any(rule.satisfied(plaintext="", tags={"a", "c", "d"}) for rule in ontology.matcher_rules)


def test_about_this_tag_names_the_group_that_inferred_it() -> None:
    ontology = compile_rules(rules=_rules("metalist:version OR metalist version => metalist-version\nmetalist-version => software"), filename="rules")
    applies = AppliesThrough.build(inherited_non_meta=frozenset(), base_tags=frozenset({"metalist", "version"}), ontology=ontology)
    assert applies.lines("metalist-version", lead="Also ") == ('Also implied by "metalist" and "version" together',)
    # A tag the group's tag implies is named the same way.
    assert applies.lines("software", lead="Also ") == ('Also implied by "metalist" and "version" together',)
    single = AppliesThrough.build(inherited_non_meta=frozenset(), base_tags=frozenset({"metalist"}), ontology=ontology)
    assert single.lines("metalist-version", lead="Also ") == ()


# Found in the throwaway MetaList (2026-10-30): saving `metalist:version OR metalist version
# => metalist-version` refreshed only the notes with values, so a note tagged `metalist
# version` did not get metalist-version until something else recomputed its tags.
def test_saving_an_or_rule_refreshes_both_kinds_of_group(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(ontology_route.note_store, "refresh_tags_for_value_rules", lambda rule_texts: calls.append("values"))
    monkeypatch.setattr(ontology_route.note_store, "rebuild_search_index_tag_terms_for_notes", lambda note_ids: calls.append("tags"))

    ontology_route._refresh_note_tags({"note"}, rule_texts=["metalist:version OR metalist version => metalist-version"])
    assert calls == ["values", "tags"]
    calls.clear()
    ontology_route._refresh_note_tags({"note"}, rule_texts=["metalist:version => metalist-version"])
    assert calls == ["values"]
    calls.clear()
    ontology_route._refresh_note_tags({"note"}, rule_texts=["metalist version => metalist-version"])
    assert calls == ["tags"]
