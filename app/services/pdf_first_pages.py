"""A PDF's first page as a picture, for galleries (docs/future-plans/gallery.md, "PDF first pages").

Each PDF's first page is drawn once, in the background (pdf_first_page_worker.py, a process of its
own at low priority), and stored with the file, encrypted (file_storage writes and reads it): after
a PDF arrives, and at login for the PDFs stored before. A PDF that can't be drawn is stored with no
picture, so it is not tried again until it changes. Each page stored raises the revision the page's
status check reads (auth.py), so the notes showing that PDF are drawn again with its picture.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Callable, Dict, List, Optional, Tuple

from app.services.auth_cache_state import after_page_ready
from app.services.background_work import DRAWING_PDF_PAGES_KEY, IMPORT_KEY, background_work
from app.services.requests_in_flight import requests_in_flight

# Raise it when the drawing changes (its size, its quality): every first page is drawn again.
DRAWER_VERSION = 1
FIRST_PAGE_MIME_TYPE = "image/jpeg"
# Stored for a PDF that could not be drawn: no picture.
NO_PICTURE_MIME_TYPE = ""
# The work card.
DRAWING_PAGES_LABEL = "Drawing PDF first pages"
# The worker process's creation flags: none (subprocess's own default) but on Windows, where it
# runs at below-normal priority.
_NO_CREATION_FLAGS = 0


def _draw_on() -> None:
    """Between PDFs when the pages are wanted now (a test): nothing to wait for."""


@dataclass(frozen=True)
class DrawnPage:
    """A PDF's first page as stored: a JPEG, or b"" with no MIME type when it can't be drawn."""

    picture: bytes
    mime_type: str
    content_revision: int
    drawer_version: int


@dataclass(frozen=True)
class FirstPageStorage:
    """How the files database is reached (file_storage installs it: this module stays free of it)."""

    # (file id, content revision) of every stored PDF.
    pdf_files: Callable[[], Dict[str, int]]
    # (content revision, drawer version) of every first page stored.
    drawn_versions: Callable[[], Dict[str, Tuple[int, int]]]
    # A file deleted meanwhile (drawing races deletions): None.
    read_file_bytes: Callable[[str], Optional[bytes]]
    is_too_large_to_draw: Callable[[str], bool]
    store_page: Callable[[str, DrawnPage], None]


def draw_first_page(content: bytes) -> bytes:
    """The first page as a JPEG, drawn by a process of its own at low priority; b"" when the PDF
    is locked or can't be read."""
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    creation_flags = _NO_CREATION_FLAGS
    if sys.platform == "win32":
        creation_flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS
    completed = subprocess.run(
        [sys.executable, "-m", "app.services.pdf_first_page_worker"],
        input=content, capture_output=True, check=True, creationflags=creation_flags,
    )
    return completed.stdout


class PdfFirstPages:
    """Draws the first page of every PDF that has none yet, or one of an older revision or drawing."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._storage: Optional[FirstPageStorage] = None
        self._worker: Optional[Thread] = None
        self._needs_another_pass = False
        # Raised with each page stored: the page draws its notes again when it changes.
        self._revision = 0

    def install_storage(self, storage: FirstPageStorage) -> None:
        self._storage = storage

    def revision(self) -> int:
        with self._lock:
            return self._revision

    def _require_storage(self) -> FirstPageStorage:
        if self._storage is None:
            raise RuntimeError("file_storage installs the first page storage at import")
        return self._storage

    def pending(self) -> List[Tuple[str, int]]:
        """(file id, content revision) of each PDF to draw."""
        storage = self._require_storage()
        drawn = storage.drawn_versions()
        return [
            (file_id, content_revision)
            for file_id, content_revision in sorted(storage.pdf_files().items())
            if file_id not in drawn or drawn[file_id] != (content_revision, DRAWER_VERSION)
        ]

    def refresh(self) -> None:
        """Draw every PDF still without its first page, each stored as soon as it is drawn: a stop
        part way (a restart) goes on with the PDFs not drawn yet."""
        self._refresh(between_files=_draw_on)

    def _refresh(self, *, between_files: Callable[[], None]) -> None:
        pending = self.pending()
        if not pending:
            return
        # Shown as it goes (background-work-cards.js); PDFs arriving meanwhile join the count.
        with background_work.track(DRAWING_PDF_PAGES_KEY, DRAWING_PAGES_LABEL, total=len(pending)) as progress:
            handled: set[str] = set()
            while pending:
                between_files()
                file_id, content_revision = pending[0]
                self.draw_and_store(file_id, content_revision)
                progress.advance()
                handled.add(file_id)
                pending = [entry for entry in self.pending() if entry[0] not in handled]
                progress.set_total(len(handled) + len(pending))

    def draw_and_store(self, file_id: str, content_revision: int) -> None:
        storage = self._require_storage()
        if storage.is_too_large_to_draw(file_id):
            self._keep(file_id, DrawnPage(b"", NO_PICTURE_MIME_TYPE, content_revision, DRAWER_VERSION))
            return
        content = storage.read_file_bytes(file_id)
        # Deleted meanwhile: nothing to keep.
        if content is None:
            return
        picture = draw_first_page(content)
        mime_type = NO_PICTURE_MIME_TYPE
        if picture != b"":
            mime_type = FIRST_PAGE_MIME_TYPE
        self._keep(file_id, DrawnPage(picture, mime_type, content_revision, DRAWER_VERSION))

    def _keep(self, file_id: str, page: DrawnPage) -> None:
        self._require_storage().store_page(file_id, page)
        with self._lock:
            self._revision += 1

    def refresh_in_background(self) -> None:
        """refresh() on a thread of its own, once no import runs; a call while one runs makes it go
        round once more."""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                self._needs_another_pass = True
                return
            self._worker = Thread(target=self._refresh_until_settled, name="metalist-pdf-first-pages", daemon=True)
            self._worker.start()

    def wait_for_background(self) -> None:
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.join()

    def _refresh_until_settled(self) -> None:
        while True:
            # What an import shows comes first, as for PDF text (file_text_search.py).
            background_work.wait_until_finished(IMPORT_KEY)
            # One PDF at a time, each after the requests being answered (requests_in_flight.py).
            self._refresh(between_files=requests_in_flight.give_way)
            with self._lock:
                if not self._needs_another_pass:
                    return
                self._needs_another_pass = False


pdf_first_pages = PdfFirstPages()
# After login (and unlock): any first page still missing, beside the requests.
after_page_ready(pdf_first_pages.refresh_in_background)
