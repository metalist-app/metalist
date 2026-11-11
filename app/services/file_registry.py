"""In-memory UUID registry for encrypted file references."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
from threading import RLock

from app.services.file_kinds import FILE_FILTER_ANY, file_kind_of, is_file_filter_kind

# A reference written in a note's text: [[id]] links, ![[id]] embeds.
# A link may carry text after a | ([[id|shown text]], docs/ui/references.md, "Link text").
_FILE_REFERENCE_TOKEN_RE = re.compile(
    r"!?\[\[([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:\|[^\[\]\n]*[^\s\[\]][^\[\]\n]*)?\]\]"
)


def referenced_file_ids(text: str) -> list[str]:
    """The UUIDs a note's text references as [[id]] or ![[id]], in order, once each:
    files among them, and notes, which the caller tells apart."""
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, got {type(text)}")
    if "[[" not in text:
        # Most notes reference nothing; skip the scan during hydration.
        return []
    return list(dict.fromkeys(match.group(1) for match in _FILE_REFERENCE_TOKEN_RE.finditer(text)))


@dataclass(frozen=True)
class FileDetails:
    """What the registry reads of a file once it can be decrypted."""

    title: str
    thumbnail_kind: str
    size_bytes: int


class FileRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._ids: set[str] = set()
        self._thumbnail_kinds_by_id: dict[str, str] = {}
        # File names by id, read from the files database with their kinds the first
        # time one is needed. An encrypted vault registers its files at startup and
        # at lock time, when only their ids can be read; their names and kinds can be
        # read once it is unlocked, and notes are read, searched and filtered only
        # then. None: not read yet.
        self._titles_by_id: dict[str, str] | None = None
        # Real sizes by id, read with the names and known exactly when they are.
        self._sizes_by_id: dict[str, int] | None = None
        self._details_loader: Callable[[], dict[str, FileDetails]] | None = None
        # How to read one file's stored bytes with the session's key (file_storage.read_stored_file).
        self._content_reader: Callable[[str], object] | None = None
        # Counts renames, so views rendered with an old file name are rendered again
        # (snapshot.py keys its render cache on it).
        self._names_generation = 0

    def install_details_loader(self, loader: Callable[[], dict[str, FileDetails]]) -> None:
        """How to read every file's name and kind (file_storage.py, which this module cannot import)."""
        if not callable(loader):
            raise TypeError("install_details_loader requires a callable")
        with self._lock:
            self._details_loader = loader

    def install_content_reader(self, reader: Callable[[str], object]) -> None:
        """How to read a file's stored bytes (file_storage.py, which this module and the
        search text it feeds cannot import): an email's words for search."""
        if not callable(reader):
            raise TypeError("install_content_reader requires a callable")
        with self._lock:
            self._content_reader = reader

    def read_stored_file(self, file_id: str) -> object:
        """The file's record and bytes (file_storage.DownloadedFile)."""
        with self._lock:
            reader = self._content_reader
        if reader is None:
            raise RuntimeError("A file is read before file storage installed its reader")
        # Outside the lock: reading a file decrypts it, and searches wait on the lock.
        return reader(file_id)

    def _ensure_details_locked(self) -> None:
        if self._titles_by_id is not None:
            return
        if self._details_loader is None:
            raise RuntimeError("File details are read before file storage installed their loader")
        details_by_id = self._details_loader()
        self._titles_by_id = {file_id: details.title for file_id, details in details_by_id.items()}
        self._sizes_by_id = {file_id: details.size_bytes for file_id, details in details_by_id.items()}
        for file_id, details in details_by_id.items():
            self._thumbnail_kinds_by_id[file_id] = details.thumbnail_kind

    def _thumbnail_kind_locked(self, file_id: str) -> str | None:
        """A registered file's kind, read with the details when startup could not; None for no file."""
        if file_id not in self._ids:
            return None
        if file_id not in self._thumbnail_kinds_by_id:
            self._ensure_details_locked()
        if file_id not in self._thumbnail_kinds_by_id:
            raise RuntimeError(f"File {file_id} is registered but has no stored kind")
        return self._thumbnail_kinds_by_id[file_id]

    def _forget_details_locked(self) -> None:
        self._titles_by_id = None
        self._sizes_by_id = None

    def reset(self) -> None:
        with self._lock:
            self._ids.clear()
            self._thumbnail_kinds_by_id.clear()
            self._forget_details_locked()

    def replace_all(self, file_ids: set[str]) -> None:
        if not isinstance(file_ids, set):
            raise TypeError(f"file_ids must be a set, got {type(file_ids)}")
        for file_id in file_ids:
            if not isinstance(file_id, str) or file_id == "":
                raise TypeError("file_ids must contain non-empty strings")
        with self._lock:
            self._ids = set(file_ids)
            self._thumbnail_kinds_by_id = {}
            self._forget_details_locked()

    def replace_all_with_thumbnail_kinds(self, thumbnail_kinds_by_id: dict[str, str]) -> None:
        if not isinstance(thumbnail_kinds_by_id, dict):
            raise TypeError(
                f"thumbnail_kinds_by_id must be a dict, got {type(thumbnail_kinds_by_id)}"
            )
        for file_id, thumbnail_kind in thumbnail_kinds_by_id.items():
            if not isinstance(file_id, str) or file_id == "":
                raise TypeError("thumbnail_kinds_by_id keys must be non-empty strings")
            if not isinstance(thumbnail_kind, str) or thumbnail_kind == "":
                raise TypeError("thumbnail_kinds_by_id values must be non-empty strings")
        with self._lock:
            self._ids = set(thumbnail_kinds_by_id.keys())
            self._thumbnail_kinds_by_id = dict(thumbnail_kinds_by_id)
            self._forget_details_locked()

    def add(self, file_id: str) -> None:
        if not isinstance(file_id, str) or file_id == "":
            raise TypeError("file_id must be a non-empty string")
        with self._lock:
            self._ids.add(file_id)

    def add_with_thumbnail_kind(self, file_id: str, *, thumbnail_kind: str, title: str, size_bytes: int) -> None:
        if not isinstance(file_id, str) or file_id == "":
            raise TypeError("file_id must be a non-empty string")
        if not isinstance(thumbnail_kind, str) or thumbnail_kind == "":
            raise TypeError("thumbnail_kind must be a non-empty string")
        if not isinstance(title, str) or title == "":
            raise TypeError("title must be a non-empty string")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise TypeError("size_bytes must be a non-negative integer")
        with self._lock:
            self._ids.add(file_id)
            self._thumbnail_kinds_by_id[file_id] = thumbnail_kind
            if self._titles_by_id is not None:
                assert self._sizes_by_id is not None
                self._titles_by_id[file_id] = title
                self._sizes_by_id[file_id] = size_bytes

    def rename(self, file_id: str, *, title: str) -> None:
        if not isinstance(file_id, str) or file_id == "":
            raise TypeError("file_id must be a non-empty string")
        if not isinstance(title, str) or title == "":
            raise TypeError("title must be a non-empty string")
        with self._lock:
            if file_id not in self._ids:
                raise KeyError(f"File {file_id} is not registered")
            if self._titles_by_id is not None:
                self._titles_by_id[file_id] = title
            self._names_generation += 1

    def set_size(self, file_id: str, *, size_bytes: int) -> None:
        """A file's content was replaced."""
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise TypeError("size_bytes must be a non-negative integer")
        with self._lock:
            if file_id not in self._ids:
                raise KeyError(f"File {file_id} is not registered")
            if self._sizes_by_id is not None:
                self._sizes_by_id[file_id] = size_bytes

    def names_generation(self) -> int:
        """Changes whenever a file is renamed."""
        with self._lock:
            return self._names_generation

    def remove_many(self, file_ids: set[str]) -> None:
        if not isinstance(file_ids, set):
            raise TypeError(f"file_ids must be a set, got {type(file_ids)}")
        with self._lock:
            self._ids.difference_update(file_ids)
            for file_id in file_ids:
                # Removing files may name some the registry never had.
                if file_id in self._thumbnail_kinds_by_id:
                    del self._thumbnail_kinds_by_id[file_id]
                if self._titles_by_id is not None and file_id in self._titles_by_id:
                    assert self._sizes_by_id is not None
                    del self._titles_by_id[file_id]
                    del self._sizes_by_id[file_id]

    def has_file(self, file_id: str) -> bool:
        if not isinstance(file_id, str) or file_id == "":
            raise TypeError("file_id must be a non-empty string")
        with self._lock:
            return file_id in self._ids

    def title_of(self, file_id: str) -> str | None:
        """The file's name, or None when the id is no file's (a [[id]] naming a note)."""
        if not isinstance(file_id, str) or file_id == "":
            raise TypeError("file_id must be a non-empty string")
        with self._lock:
            if file_id not in self._ids:
                return None
            self._ensure_details_locked()
            assert self._titles_by_id is not None
            if file_id not in self._titles_by_id:
                raise RuntimeError(f"File {file_id} is registered but has no stored name")
            return self._titles_by_id[file_id]

    def referenced_file_names(self, text: str) -> list[tuple[str, str]]:
        """(id, name) of each file a note's text references, in order, once each."""
        if not isinstance(text, str):
            raise TypeError(f"text must be a string, got {type(text)}")
        names: list[tuple[str, str]] = []
        for file_id in referenced_file_ids(text):
            title = self.title_of(file_id)
            if title is not None:
                names.append((file_id, title))
        return names

    def thumbnail_kind_of(self, file_id: str) -> str | None:
        """A file's thumbnail kind (file_storage._derive_thumbnail_kind), or None when the id is no file's."""
        if not isinstance(file_id, str) or file_id == "":
            raise TypeError("file_id must be a non-empty string")
        with self._lock:
            return self._thumbnail_kind_locked(file_id)

    def file_ids_of_kind(self, kind: str) -> set[str]:
        """The files a Files filter keeps (file_kinds.py): every file for "any"."""
        if not is_file_filter_kind(kind):
            raise ValueError(f"Unknown file filter kind {kind!r}")
        with self._lock:
            if kind == FILE_FILTER_ANY:
                return set(self._ids)
            return {file_id for file_id, file_kind in self.kinds_by_id().items() if file_kind == kind}

    def kinds_by_id(self) -> dict[str, str]:
        """Each file's kind (file_kinds.file_kind_of)."""
        with self._lock:
            kinds: dict[str, str] = {}
            for file_id in self._ids:
                thumbnail_kind = self._thumbnail_kind_locked(file_id)
                file_name = self.title_of(file_id)
                assert thumbnail_kind is not None and file_name is not None
                kinds[file_id] = file_kind_of(thumbnail_kind=thumbnail_kind, file_name=file_name)
            return kinds

    def sizes_of_kind(self, kind: str) -> dict[str, int]:
        """The real size in bytes of each file a Files filter keeps, by id (the File size order)."""
        with self._lock:
            kept = self.file_ids_of_kind(kind)
            self._ensure_details_locked()
            assert self._sizes_by_id is not None
            return {file_id: self._sizes_by_id[file_id] for file_id in kept}

    def list_ids(self) -> set[str]:
        with self._lock:
            return set(self._ids)

    def has_resizable_file(self, file_id: str) -> bool:
        """Embedded files whose rendered size can be changed with a size wrapper: images and diagrams."""
        if not isinstance(file_id, str) or file_id == "":
            raise TypeError("file_id must be a non-empty string")
        with self._lock:
            return self._thumbnail_kind_locked(file_id) in {"image", "excalidraw"}

    def has_image_file(self, file_id: str) -> bool:
        if not isinstance(file_id, str) or file_id == "":
            raise TypeError("file_id must be a non-empty string")
        with self._lock:
            return self._thumbnail_kind_locked(file_id) == "image"


file_registry = FileRegistry()
