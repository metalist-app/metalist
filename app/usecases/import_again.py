"""Importing a folder again (docs/ready-to-build/import-export-launch.md §5, "Importing again"): which of its files came in
before, which changed since, which of their notes were edited in MetaList, and what the person
chose for them: keep both (the first choice: nothing is lost without a click), or replace the
old notes. And "Changed since": only the files changed on or after a day.

Decided by the maintainer, 2026-11-20, going back on "an import only adds" (2026-11-02)."""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Dict, List

from app.services.import_origins import EarlierFile, earlier_files, notes_fingerprint
from app.services.input_errors import InputRejected

# What happens to the notes of files that came in before and changed since.
KEEP_BOTH = "keep"
REPLACE = "replace"
# Also the ones edited in MetaList.
REPLACE_EDITED = "replace-edited"
EARLIER_NOTES_CHOICES = (KEEP_BOTH, REPLACE, REPLACE_EDITED)
# "Changed since", as a date field gives it: 2026-11-01.
_DAY_RE = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})")
_NO_DAY = ""
# The standing note of a file that never came in.
NO_NOTE = ""
_FIRST_MONTH = 1
_LAST_MONTH = 12


def changed_since_day(changed_since: str) -> date | None:
    """The day typed into "Changed since", or None when the field is empty."""
    if changed_since == _NO_DAY:
        return None
    written = _DAY_RE.fullmatch(changed_since)
    if written is None:
        raise InputRejected("Changed since takes a date, such as 2026-11-01.")
    year, month, day = int(written["year"]), int(written["month"]), int(written["day"])
    if year < date.min.year or not _FIRST_MONTH <= month <= _LAST_MONTH:
        raise InputRejected(f"{changed_since} is not a date.")
    _first_weekday, days_in_month = calendar.monthrange(year, month)
    if not 1 <= day <= days_in_month:
        raise InputRejected(f"{changed_since} is not a date.")
    return date(year, month, day)


def is_changed_since(modified_at: datetime, since: date | None) -> bool:
    """Whether a file last changed on that day or later, by this computer's clock."""
    if since is None:
        return True
    return modified_at >= datetime.combine(since, time.min).astimezone()


def nothing_changed_since(since: date) -> InputRejected:
    return InputRejected(f"No file in the folder changed since {since.isoformat()}. Choose an earlier date, or none.")


@dataclass(frozen=True)
class MetFile:
    """A file that came in before, met again."""

    earlier: EarlierFile
    # The file is not as it was imported.
    is_changed: bool
    # Its notes are not as the import wrote them.
    is_edited: bool


@dataclass(frozen=True)
class ImportedBefore:
    """The files of an import that came in before, by path, and what was chosen for them."""

    met: Mapping[str, MetFile]
    choice: str
    # Every file the folder brought into this place before, by path, its root note still there.
    earlier: Mapping[str, EarlierFile]
    # The files Changed since leaves out, by path: read, for the links to them, never written.
    left_out: AbstractSet[str]

    def is_left(self, path: str) -> bool:
        """The file is as it was imported and its notes are to be replaced when it changes:
        nothing to bring in."""
        return self.choice != KEEP_BOTH and path in self.met and not self.met[path].is_changed

    def is_replaced(self, path: str) -> bool:
        """The file's old notes go and its new ones take their place."""
        if self.choice == KEEP_BOTH or path not in self.met:
            return False
        met = self.met[path]
        if not met.is_changed:
            return False
        if met.is_edited:
            return self.choice == REPLACE_EDITED
        return True

    def is_written(self, path: str) -> bool:
        """The file's notes come in: it is neither left out by Changed since nor left as it is."""
        return path not in self.left_out and not self.is_left(path)

    def standing_root_id(self, path: str) -> str:
        """The root note a file this import does not write has in the vault already, '' when
        it never came in: where a link to the file leads."""
        assert not self.is_written(path), "only a file that is not written has a note standing for it"
        if path in self.earlier:
            return self.earlier[path].file.root_id
        return NO_NOTE

    def root_id(self, path: str, new_id: str) -> str:
        """The id the file's root note has: its old note's when that one stays or is replaced
        (links to it keep leading there), else the new one."""
        if self.is_replaced(path):
            return self.met[path].earlier.file.root_id
        if not self.is_written(path) and self.standing_root_id(path) != NO_NOTE:
            return self.standing_root_id(path)
        return new_id

    def summary(self) -> Dict[str, object]:
        """For the walkthrough's Summary: when the folder last came in ('' for never), how many
        of these files came in before, how many changed since, and which of those were edited."""
        changed = [path for path, met in self.met.items() if met.is_changed]
        edited = sorted(path for path in changed if self.met[path].is_edited)
        imported_at = ""
        if self.met:
            imported_at = max(met.earlier.imported_at for met in self.met.values()).isoformat()
        return {
            "importedAt": imported_at, "fileCount": len(self.met), "changedCount": len(changed),
            "editedCount": len(edited), "edited": edited,
        }


def meet_earlier_import(
    *, folder_name: str, prefix_folder: str, fingerprints: Mapping[str, Callable[[], str]], choice: str,
    left_out: AbstractSet[str],
) -> ImportedBefore:
    """Which of the files about to come in (each path with a way to fingerprint it, asked only
    for a file that came in before) the same folder brought into the same place before."""
    if choice not in EARLIER_NOTES_CHOICES:
        raise InputRejected("Choose Keep both or Replace the old notes.")
    earlier = earlier_files(folder_name=folder_name, prefix_folder=prefix_folder)
    met: Dict[str, MetFile] = {}
    for path, fingerprint in fingerprints.items():
        if path not in earlier:
            continue
        before = earlier[path]
        met[path] = MetFile(
            earlier=before, is_changed=fingerprint() != before.file.fingerprint,
            is_edited=notes_fingerprint(before.file.root_id) != before.file.written,
        )
    return ImportedBefore(met=met, choice=choice, earlier=earlier, left_out=left_out)


def nothing_to_bring_in(before: ImportedBefore, paths: List[str]) -> bool:
    """Every file is as it was imported, and none is to come in beside its old notes."""
    return all(before.is_left(path) for path in paths)
