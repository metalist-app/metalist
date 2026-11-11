"""Embedded searches, `![[search:…]]`: a search's results drawn in a note, live
(docs/ready-to-build/search-links.md §11). The renderer (embedded_references.py) asks this module
for a search's results; the view (snapshot.py), which knows how a search orders its notes,
installs what answers, so the renderer needs no import of the view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

# An embedded search shows this many results, then how many more.
SHOWN_RESULTS = 10


@dataclass(frozen=True, slots=True)
class SearchResults:
    """How many notes the search finds, and the first SHOWN_RESULTS of them in the list's order."""

    count: int
    first_note_ids: Tuple[str, ...]


class _SearchRunner:
    def __init__(self) -> None:
        self._run: Optional[Callable[[str], SearchResults]] = None

    def install(self, run: Callable[[str], SearchResults]) -> None:
        self._run = run

    def results(self, search: str) -> SearchResults:
        """The search's results; InputRejected for a search that doesn't parse."""
        if self._run is None:
            raise RuntimeError("snapshot installs the search runner at import")
        found = self._run(search)
        assert len(found.first_note_ids) <= SHOWN_RESULTS and found.count >= len(found.first_note_ids), found
        return found


search_runner = _SearchRunner()
