"""Renaming, moving and deleting virtual folders, an experiment
(docs/ready-to-build/virtual-folders.md §4–§5; app/services/virtual_folders.py). A folder is
its tag and every tag below it (`Projects/` and `Projects/Client-A/`): each is renamed or
deleted on every note, with the rules mentioning it, through the tag rename and delete Edit
Tag Relationships uses. Renaming onto a folder that exists merges the two."""

from __future__ import annotations

from typing import Dict, List

from app.services.input_errors import InputRejected
from app.services.virtual_folders import FOLDER_MARK, all_folder_tags, is_folder_tag, virtual_folder_state
from app.usecases.delete_tag import apply_delete_tag_everywhere
from app.usecases.rename_tag import apply_rename_tag_everywhere


def folder_tags_under(folder: str) -> List[str]:
    """The folder's own tag and every folder tag below it that some note carries."""
    assert is_folder_tag(folder), folder
    return [tag for tag in all_folder_tags() if tag.casefold().startswith(folder.casefold())]


def rename_folder(*, folder: str, new_path: str, token: str) -> Dict[str, object]:
    """Rename (or move: the same thing) a folder and everything below it to new_path."""
    if not is_folder_tag(folder) or not is_folder_tag(new_path):
        raise InputRejected("A folder's name is a tag ending in /, with no spaces.")
    if new_path.casefold() == folder.casefold():
        return {"renamedTagCount": 0}
    if new_path.casefold().startswith(folder.casefold()):
        raise InputRejected(f"{folder} can't go into itself or one of its own folders.")
    tags = folder_tags_under(folder)
    for tag in tags:
        apply_rename_tag_everywhere(old=tag, new=new_path + tag[len(folder):], token=token)
    virtual_folder_state.move_filters(folder, new_path)
    return {"renamedTagCount": len(tags)}


def move_folder(*, folder: str, into: str, token: str) -> Dict[str, object]:
    """Move a folder into another ('' for the top), keeping its name."""
    if into != "" and not is_folder_tag(into):
        raise InputRejected(f"{into} is not a folder.")
    name = folder.rstrip(FOLDER_MARK).split(FOLDER_MARK)[-1]
    return rename_folder(folder=folder, new_path=f"{into}{name}{FOLDER_MARK}", token=token)


def delete_folder(*, folder: str, token: str) -> Dict[str, object]:
    """Take the folder and every folder below it off every note; the notes stay, unfiled."""
    if not is_folder_tag(folder):
        raise InputRejected(f"{folder} is not a folder.")
    tags = folder_tags_under(folder)
    for tag in tags:
        apply_delete_tag_everywhere(tag=tag, token=token)
    virtual_folder_state.drop_filters_under(folder)
    return {"deletedTagCount": len(tags)}
