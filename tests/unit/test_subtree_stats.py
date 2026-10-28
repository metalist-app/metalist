"""Totals of a note's subtree (@stats, @sum=…; app/services/subtree_stats.py)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.search_index import tag_bar_values
from app.services.subtree_stats import (
    SummaryRequest,
    parse_summary_requests,
    render_subtree_stats_footer,
    suggest_summary_properties,
    typed_summary_property,
)


@dataclass(frozen=True)
class _Note:
    tags: str


@dataclass(frozen=True)
class _Tree:
    """The render context's lookups over a small tree of notes, in a vault where the
    properties in `used_elsewhere` have values on notes outside the tree."""

    notes: dict[str, _Note]
    children: dict[str, list[str]]
    used_elsewhere: frozenset[str]

    def get_note(self, note_id: str) -> _Note:
        return self.notes[note_id]

    def get_children(self, note_id: str) -> list[str]:
        return self.children[note_id]

    def is_property_used(self, property_name: str) -> bool:
        if property_name in self.used_elsewhere:
            return True
        for note in self.notes.values():
            for tag_name, name in tag_bar_values(note.tags)[1]:
                if property_name in (name, tag_name):
                    return True
        return False


def _diet(diet_tags: str) -> _Tree:
    """A diet note with three meals: 300, 500, and 200 + 400 calories; fat on two."""
    return _Tree(
        notes={
            "diet": _Note(diet_tags),
            "breakfast": _Note("meal:calories=300 butter:fat=10"),
            "lunch": _Note("meal:calories=500 cheese:fat=20"),
            "dinner": _Note("fruit:calories=200 bread:calories=400"),
        },
        children={"diet": ["breakfast", "lunch", "dinner"], "breakfast": [], "lunch": [], "dinner": []},
        used_elsewhere=frozenset(),
    )


def _footer(tree: _Tree) -> str:
    return render_subtree_stats_footer(note_id="diet", tags=tree.notes["diet"].tags, context=tree)


def _groups(footer: str) -> list[tuple[str, ...]]:
    """Each group: its name (for @stats) and its figures as "label: value"."""
    groups = []
    for group in re.findall(r'<div class="meta-stats-group">(.*?)</div></div>(?=<div class="meta-stats-group">|<div class="meta-stats-skipped">|</section>)', footer):
        name = re.findall(r'<div class="meta-stats-name">([^<]*)</div>', group)
        items = [
            f"{label}: {value}"
            for label, value in re.findall(
                r'<span class="meta-stats-label">([^<]*)<span class="meta-stats-colon">:</span></span> '
                r'<span class="meta-stats-leader"></span><span class="meta-stats-value">([^<]*)</span>', group,
            )
        ]
        groups.append(tuple(name + items))
    return groups


def test_stats_shows_each_property_with_its_figures() -> None:
    assert _groups(_footer(_diet("@stats"))) == [
        ("calories", "Total: 1,400", "Min: 300", "Max: 600", "Count: 3"),
        ("fat", "Total: 30", "Min: 10", "Max: 20", "Count: 2"),
    ]


def test_a_summary_tag_without_a_property_covers_every_number_property() -> None:
    assert _groups(_footer(_diet("@sum"))) == [("Total calories: 1,400", "Total fat: 30")]
    assert _groups(_footer(_diet("@max"))) == [("Max calories: 600", "Max fat: 20")]
    assert _groups(_footer(_diet("@count"))) == [("Notes with calories: 3", "Notes with fat: 2")]


def test_a_summary_tag_with_a_property_shows_that_property_only() -> None:
    assert _groups(_footer(_diet("@sum=calories @avg=calories"))) == [
        ("Total calories: 1,400", "Average calories: 466.7"),
    ]


def test_a_named_property_no_note_has_shows_a_dash() -> None:
    assert _groups(_footer(_diet("@sum=calroies"))) == [("Total calroies: —",)]


def _tree(diet_tags: str, children: dict[str, str], grandchildren: dict[str, dict[str, str]]) -> _Tree:
    """A diet note with the given children (id -> tags) and, under some, grandchildren,
    in a vault where calories are logged elsewhere too."""
    notes = {"diet": _Note(diet_tags)}
    tree_children: dict[str, list[str]] = {"diet": list(children)}
    for child_id, tags in children.items():
        notes[child_id] = _Note(tags)
        tree_children[child_id] = []
    for parent_id, kids in grandchildren.items():
        for kid_id, tags in kids.items():
            notes[kid_id] = _Note(tags)
            tree_children[parent_id].append(kid_id)
            tree_children[kid_id] = []
    return _Tree(notes=notes, children=tree_children, used_elsewhere=frozenset({"calories"}))


def test_the_notes_own_values_and_its_grandchildrens_count() -> None:
    tree = _tree("@sum meal:calories=100", {"lunch": "meal:calories=500"}, {"lunch": {"dessert": "treat:calories=250"}})
    assert _groups(_footer(tree)) == [("Total calories: 850",)]


def test_values_are_per_note_before_min_and_max() -> None:
    # Dinner's two foods make one 600-calorie note: the heaviest meal, not the largest food.
    assert _groups(_footer(_diet("@min=calories @max=calories"))) == [("Min calories: 300", "Max calories: 600")]


def test_a_note_that_only_links_or_embeds_another_adds_nothing() -> None:
    # The note a child links to or embeds is not in the subtree; the child has no values.
    tree = _tree("@sum", {"lunch": "meal:calories=500", "linking": ""}, {})
    assert _groups(_footer(tree)) == [("Total calories: 500",)]


def test_mixed_units_are_kept_apart_and_never_converted() -> None:
    tree = _tree("@sum=fat", {"a": "butter:fat=10g", "b": "cheese:fat=500mg", "c": "oil:fat=5g"}, {})
    assert _groups(_footer(tree)) == [("Total fat: 15g, 500mg",)]


def test_a_negative_value_lowers_the_total() -> None:
    tree = _tree("@sum=calories", {"a": "meal:calories=500", "b": "walk:calories=-200"}, {})
    assert _groups(_footer(tree)) == [("Total calories: 300",)]


def test_values_that_are_not_numbers_are_left_out_and_counted() -> None:
    tree = _tree("@stats", {"a": "meal:calories=500", "b": "snack:calories=lots", "c": "drink:calories=10:30"}, {})
    footer = _footer(tree)
    assert _groups(footer) == [("calories", "Total: 500", "Min: 500", "Max: 500", "Count: 1")]
    assert '<div class="meta-stats-skipped">2 calories values are not numbers and are left out</div>' in footer


def test_stats_skips_what_it_already_shows_and_keeps_the_average() -> None:
    assert _groups(_footer(_diet("@stats @sum=calories @avg=calories"))) == [
        ("calories", "Total: 1,400", "Min: 300", "Max: 600", "Count: 3"),
        ("fat", "Total: 30", "Min: 10", "Max: 20", "Count: 2"),
        ("Average calories: 466.7",),
    ]


def test_a_note_without_summary_tags_has_no_footer() -> None:
    assert _footer(_diet("project")) == ""
    assert _footer(_tree("@sum", {"a": "meal"}, {})) == ""


def test_summary_tags_inside_a_scope_do_not_count() -> None:
    assert parse_summary_requests("((@sum=calories)) @stats") == (SummaryRequest(kind="stats", property_name=""),)


def test_suggestions_after_a_summary_tag_are_the_subtrees_properties_most_used_first() -> None:
    tree = _tree("", {"a": "meal:calories=1 x:fat=2", "b": "meal:calories=3", "c": "y:carbs=4"}, {})
    assert typed_summary_property("@avg=ca") == ("@avg", "ca")
    assert typed_summary_property("@avg") is None
    suggestions = suggest_summary_properties(note_id="diet", typed_tag="@sum", typed_property="", context=tree, limit=8)
    assert [suggestion.replacement for suggestion in suggestions] == ["@sum=calories", "@sum=carbs", "@sum=fat"]
    assert suggestions[0].reasons == ("Used under this note, on 2 notes",)
    narrowed = suggest_summary_properties(note_id="diet", typed_tag="@sum", typed_property="ca", context=tree, limit=8)
    assert [suggestion.label for suggestion in narrowed] == ["calories", "carbs"]


def test_a_value_written_on_the_tag_itself_counts_as_that_property() -> None:
    # `calories=700` is the tag calories with its own value; for stats it is calories=700,
    # added up with `burger:calories=450` (agreed 2026-10-27).
    tree = _tree("@sum", {"a": "burger:calories=450", "b": "calories=700"}, {})
    assert _groups(_footer(tree)) == [("Total calories: 1,150",)]
    suggestions = suggest_summary_properties(note_id="diet", typed_tag="@sum", typed_property="", context=tree, limit=8)
    assert [suggestion.replacement for suggestion in suggestions] == ["@sum=calories"]


def test_with_nothing_under_the_note_the_sum_and_count_are_0_and_the_rest_a_dash() -> None:
    # A new day of a food log, before any meal (agreed 2026-10-28); calories are logged elsewhere.
    tree = _tree("@sum=calories @count=calories @avg=calories @min=calories @max=calories", {"a": "walk"}, {})
    assert _groups(_footer(tree)) == [(
        "Total calories: 0", "Notes with calories: 0", "Average calories: —", "Min calories: —", "Max calories: —",
    )]


def test_a_property_used_nowhere_in_the_vault_is_a_dash_for_every_tag() -> None:
    tree = _tree("@sum=calroies @count=calroies", {"a": "meal:calories=500"}, {})
    assert _groups(_footer(tree)) == [("Total calroies: —", "Notes with calroies: —")]


def test_only_text_values_give_0_and_say_they_are_left_out() -> None:
    tree = _tree("@sum=calories @avg=calories", {"a": "snack:calories=lots"}, {})
    footer = _footer(tree)
    assert _groups(footer) == [("Total calories: 0", "Average calories: —")]
    assert footer.count('<div class="meta-stats-skipped">') == 1
    assert '<div class="meta-stats-skipped">1 calories value is not a number and is left out</div>' in footer


def test_stats_says_a_property_with_only_text_values_is_left_out() -> None:
    # No figures for it, only the line (agreed 2026-10-28).
    tree = _tree("@stats", {"a": "meal:calories=500", "b": "mood:feeling=good"}, {})
    footer = _footer(tree)
    assert _groups(footer) == [("calories", "Total: 500", "Min: 500", "Max: 500", "Count: 1")]
    assert '<div class="meta-stats-skipped">1 feeling value is not a number and is left out</div>' in footer


def test_stats_and_a_sum_of_a_text_only_property_say_it_once() -> None:
    tree = _tree("@stats @sum=calories", {"a": "snack:calories=lots"}, {})
    footer = _footer(tree)
    assert _groups(footer) == [("Total calories: 0",)]
    assert footer.count('<div class="meta-stats-skipped">') == 1
