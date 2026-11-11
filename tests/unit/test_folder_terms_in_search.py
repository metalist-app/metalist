"""A term ending in / matches that folder and every folder below it (docs/ready-to-build/folder-tags-in-search.md §1)."""
from __future__ import annotations

import pytest

from app.services.search_index import NOTHING_INHERITED, SearchIndex, SearchRecord, extract_tags_for_search
from app.services.tag_ontology import TagOntology
from app.services.virtual_folders import ChosenFolders, chosen_folders_of, rename_folder_in_search, without_folder_terms


def _index(tags_by_note: dict[str, str]) -> SearchIndex:
    """The index as the note store fills it: each note's tags with what they imply, the folders
    above a folder tag included (folders-tab-and-multiple-folders.md §6)."""
    index = SearchIndex()
    index.attach_inherited_values_reader(lambda note_ids: {note_id: NOTHING_INHERITED for note_id in note_ids})
    no_rules = TagOntology.empty()
    index.rebuild(
        [SearchRecord(note_id=note_id, content_text=note_id, tags=tags,
                      tag_terms=no_rules.infer_implication_only(base_tags=extract_tags_for_search(tags)))
         for note_id, tags in tags_by_note.items()],
        raw_tag_terms_by_id={note_id: extract_tags_for_search(tags) for note_id, tags in tags_by_note.items()},
        progress_update=lambda processed: None, progress_interval=len(tags_by_note),
    )
    return index


@pytest.fixture
def vault() -> SearchIndex:
    return _index({
        "budget": "Projects/",
        "kickoff": "Projects/Client-A/",
        "invoice": "Projects/Client-A/2026/",
        "notes-tag": "Projects/notes",
        "elsewhere": "Archive/Projects/",
        "work": "work",
        "work-archive": "work-archive",
    })


@pytest.mark.parametrize(
    ("search", "found"),
    [
        ("Projects/", {"budget", "kickoff", "invoice"}),
        ("projects/client-a/", {"kickoff", "invoice"}),
        ("-Projects/", {"notes-tag", "elsewhere", "work", "work-archive"}),
        ("Projects/ -Projects/Client-A/2026/", {"budget", "kickoff"}),
        ("work", {"work"}),
        ("Projects/notes", {"notes-tag"}),
    ],
)
def test_a_folder_term_takes_in_the_folders_below_it_and_every_other_term_stays_exact(vault: SearchIndex, search: str, found: set[str]) -> None:
    assert vault.query_note_ids(search) == found


# Every positive folder term is marked, in every OR clause (folders-tab-and-multiple-folders.md §5).
@pytest.mark.parametrize(
    ("search", "kind", "folders"),
    [
        ("", "top", ()),
        ("@todo", "top", ()),
        ("Projects/", "folders", ("Projects/",)),
        ("Projects/ @todo", "folders", ("Projects/",)),
        ("@todo projects/client-a/", "folders", ("projects/client-a/",)),
        ("-Projects/", "top", ()),
        ("Projects/ Archive/", "folders", ("Archive/", "Projects/")),
        ("Projects/ OR Archive/ @todo", "folders", ("Archive/", "Projects/")),
        ("Projects/ projects/", "folders", ("Projects/",)),
        ("work OR home", "top", ()),
        ('"Projects/"', "top", ()),
    ],
)
def test_the_tree_reads_its_chosen_folders_from_the_search(search: str, kind: str, folders: tuple[str, ...]) -> None:
    assert chosen_folders_of(search) == ChosenFolders(kind=kind, folders=folders)


def test_counts_read_the_search_without_its_folder_terms() -> None:
    assert without_folder_terms('Projects/ @todo -Archive/ "Projects/ plan"') == '@todo "Projects/ plan"'
    assert without_folder_terms("Projects/") == ""
    assert without_folder_terms("Projects/ OR Archive/ @todo") == "@todo"


@pytest.mark.parametrize(
    ("search", "renamed"),
    [
        ("Projects/ @todo", "Work/ @todo"),
        ("projects/client-a/ -Projects/Client-A/2026/", "Work/client-a/ -Work/Client-A/2026/"),
        ("Archive/Projects/ Projects", "Archive/Projects/ Projects"),
        ('"Projects/"', '"Projects/"'),
    ],
)
def test_a_renamed_folder_is_renamed_in_searches_with_the_folders_below_it(search: str, renamed: str) -> None:
    assert rename_folder_in_search(search, old="Projects/", new="Work/") == renamed
