"""Each stored item as one file on disk, named by a random ID
(docs/design/file-storage.md, sections 2, 4, 5 and 7).

A blob is written once and never changed: it goes to `<id>.mlb.tmp`, is synced, and only then
takes its name, so a catalog row never points at a half-written file. In a vault with a password
it is encrypted with its own key (streaming_blob.py) and padded; without one it is the file's
bytes as they are. A blob's key, real size and checksum are its seal, kept in the catalog.

A blob nothing needs is retired. A blob still being read or backed up is pinned, and goes when the
last pin is released: Windows refuses to delete an open file, and a backup must find every blob
its catalog snapshot names.
"""

from __future__ import annotations

import base64
from collections import Counter
from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from threading import RLock
import time
from typing import BinaryIO

from app.security.crypto_sizes import AES_256_KEY_BYTES
from app.security.streaming_blob import StreamingBlobReader, StreamingBlobWriter
from app.utils.byte_sizes import MIB

BLOB_ID_BYTES = 16
_BLOB_ID_RE = re.compile(r"[0-9a-f]+")
BLOB_ID_HEX_CHARACTERS = len(secrets.token_hex(BLOB_ID_BYTES))
BLOB_FILE_SUFFIX = ".mlb"
_TEMPORARY_SUFFIX = ".tmp"
BLOB_FAN_OUT_CHARACTERS = 2
_READ_CHUNK_BYTES = MIB
# The random part of the padding is at most this fraction of the file: 1 / 100 (maintainer, 2026-11-08).
_RANDOM_PADDING_DIVISOR = 100
_SMALLEST_SIZE_WITH_PADDING = 2
_ZERO_CHUNK = bytes(_READ_CHUNK_BYTES)


FILES_DIRECTORY_NAME = "files"
CATALOG_FILE_NAME = "catalog.db"
BLOBS_DIRECTORY_NAME = "blobs"


def resolve_legacy_file_database_path(note_database_path: Path) -> Path:
    """The single files database of a vault from before database version 17."""
    if not isinstance(note_database_path, Path):
        raise TypeError(f"note_database_path must be a Path, got {type(note_database_path)}")
    suffix = note_database_path.suffix
    stem = note_database_path.stem
    if suffix == "":
        return note_database_path.with_name(f"{stem}.files")
    return note_database_path.with_name(f"{stem}.files{suffix}")


def resolve_files_directory(note_database_path: Path) -> Path:
    if not isinstance(note_database_path, Path):
        raise TypeError(f"note_database_path must be a Path, got {type(note_database_path)}")
    return note_database_path.with_name(FILES_DIRECTORY_NAME)


def resolve_file_catalog_path(note_database_path: Path) -> Path:
    return resolve_files_directory(note_database_path) / CATALOG_FILE_NAME


class BlobSealError(ValueError):
    """A blob's bytes do not match its seal."""


@dataclass(frozen=True, slots=True)
class BlobSeal:
    """What opens a blob and proves it whole. file_key is None in a vault without a password."""

    file_key: bytes | None
    real_size: int
    sha256: str

    def to_bytes(self) -> bytes:
        file_key = None
        if self.file_key is not None:
            file_key = base64.b64encode(self.file_key).decode("ascii")
        return json.dumps({"key": file_key, "size": self.real_size, "sha256": self.sha256}, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_bytes(cls, payload: bytes) -> BlobSeal:
        fields = json.loads(payload)
        if not isinstance(fields, dict) or set(fields) != {"key", "size", "sha256"}:
            raise BlobSealError("A blob seal must hold exactly its key, size and checksum")
        file_key = None
        if fields["key"] is not None:
            file_key = base64.b64decode(fields["key"], validate=True)
        return cls(file_key=file_key, real_size=fields["size"], sha256=fields["sha256"])


@dataclass(frozen=True, slots=True)
class StoredBlob:
    blob_id: str
    seal: BlobSeal


def padded_size(real_size: int) -> int:
    """Padmé: the size rounded up so that only its top bits vary, at most about 12% more."""
    if real_size < _SMALLEST_SIZE_WITH_PADDING:
        return real_size
    exponent = real_size.bit_length() - 1
    rounded_bits = exponent - exponent.bit_length()
    mask = (1 << rounded_bits) - 1
    return (real_size + mask) & ~mask


def _random_padding(real_size: int) -> int:
    return secrets.randbelow(real_size // _RANDOM_PADDING_DIVISOR + 1)


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return  # Windows cannot open a directory this way; its renames are flushed with the file.
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class _BlobPins:
    """Which blobs are in use, and which are waiting to go when the last use ends."""

    def __init__(self) -> None:
        self.lock = RLock()
        self._counts: Counter[Path] = Counter()
        self._retired: set[Path] = set()

    def pin(self, paths: Iterable[Path]) -> None:
        with self.lock:
            self._counts.update(paths)

    def unpin(self, paths: Iterable[Path]) -> None:
        with self.lock:
            for path in paths:
                assert self._counts[path] > 0, f"unpinned a blob that was not pinned: {path.name}"
                self._counts[path] -= 1
                if self._counts[path] == 0:
                    del self._counts[path]
                    if path in self._retired:
                        self._retired.remove(path)
                        path.unlink()

    def retire(self, paths: Iterable[Path]) -> None:
        with self.lock:
            for path in paths:
                if self._counts[path] > 0:
                    self._retired.add(path)
                else:
                    path.unlink()


# One per process: pins are by full path, so two stores for one folder share them.
_pins = _BlobPins()


def blob_store_for_database(note_database_path: Path) -> "BlobStore":
    return BlobStore(resolve_files_directory(note_database_path) / BLOBS_DIRECTORY_NAME)


class BlobWriter:
    """One blob being written. finish() publishes it; leaving BlobStore.writer() without that
    removes the temporary file."""

    def __init__(self, *, handle: BinaryIO, temporary_path: Path, final_path: Path, blob_id: str, is_encrypted: bool) -> None:
        self._handle = handle
        self._temporary_path = temporary_path
        self._final_path = final_path
        self._blob_id = blob_id
        self._is_encrypted = is_encrypted
        self._file_key: bytes | None = None
        self._encryptor: StreamingBlobWriter | None = None
        if is_encrypted:
            self._file_key = secrets.token_bytes(AES_256_KEY_BYTES)
            self._encryptor = StreamingBlobWriter(handle, file_key=self._file_key)
        self._digest = hashlib.sha256()
        self._real_size = 0
        self.is_finished = False

    def write(self, content: bytes) -> None:
        self._digest.update(content)
        self._real_size += len(content)
        self._write_out(content)

    def _write_out(self, content: bytes) -> None:
        if self._encryptor is None:
            self._handle.write(content)
        else:
            self._encryptor.write(content)

    def _write_padding(self) -> None:
        remaining = padded_size(self._real_size) + _random_padding(self._real_size) - self._real_size
        while remaining > 0:
            chunk = _ZERO_CHUNK[:remaining]
            self._write_out(chunk)
            remaining -= len(chunk)

    def finish(self) -> StoredBlob:
        assert not self.is_finished
        if self._encryptor is not None:
            self._write_padding()
            self._encryptor.finish()
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        os.rename(self._temporary_path, self._final_path)
        _sync_directory(self._final_path.parent)
        self.is_finished = True
        seal = BlobSeal(file_key=self._file_key, real_size=self._real_size, sha256=self._digest.hexdigest())
        return StoredBlob(blob_id=self._blob_id, seal=seal)


class BlobStore:
    """The blobs of one vault: `<vault>/files/blobs/ab/abcd….mlb`."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()

    @property
    def lifecycle_lock(self) -> RLock:
        """Held while finding a blob in the catalog and pinning it, so it cannot go between."""
        return _pins.lock

    def path_of(self, blob_id: str) -> Path:
        if len(blob_id) != BLOB_ID_HEX_CHARACTERS or _BLOB_ID_RE.fullmatch(blob_id) is None:
            raise ValueError(f"Not a blob ID: {blob_id!r}")
        return self.directory / blob_id[:BLOB_FAN_OUT_CHARACTERS] / f"{blob_id}{BLOB_FILE_SUFFIX}"

    def contains(self, blob_id: str) -> bool:
        return self.path_of(blob_id).exists()

    @contextmanager
    def writer(self, *, is_encrypted: bool) -> Iterator[BlobWriter]:
        blob_id = secrets.token_hex(BLOB_ID_BYTES)
        final_path = self.path_of(blob_id)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = final_path.with_name(final_path.name + _TEMPORARY_SUFFIX)
        with temporary_path.open("xb") as handle:
            writer = BlobWriter(
                handle=handle, temporary_path=temporary_path, final_path=final_path, blob_id=blob_id, is_encrypted=is_encrypted,
            )
            try:
                yield writer
            finally:
                if not writer.is_finished:
                    handle.close()
                    temporary_path.unlink()

    def write(self, content: bytes, *, is_encrypted: bool) -> StoredBlob:
        with self.writer(is_encrypted=is_encrypted) as writer:
            writer.write(content)
            return writer.finish()

    def read_range(self, blob_id: str, seal: BlobSeal, *, start: int, length: int) -> Iterator[bytes]:
        """The real bytes from start, length of them, a chunk at a time. Pins the blob from this
        call until the iterator, which must be iterated, ends or is closed. A range past the real
        size is refused when asked for."""
        if start < 0 or length < 0 or start + length > seal.real_size:
            raise ValueError(f"Bytes {start}+{length} are outside this {seal.real_size}-byte file")
        path = self.path_of(blob_id)
        self.pin([blob_id])
        return self._pieces(path=path, blob_id=blob_id, seal=seal, start=start, length=length)

    def _pieces(self, *, path: Path, blob_id: str, seal: BlobSeal, start: int, length: int) -> Iterator[bytes]:
        try:
            with path.open("rb") as source:
                if seal.file_key is None:
                    yield from self._plain_pieces(source=source, start=start, length=length)
                else:
                    yield from StreamingBlobReader(source, file_key=seal.file_key).read(start, length)
        finally:
            self.unpin([blob_id])

    @staticmethod
    def _plain_pieces(*, source: BinaryIO, start: int, length: int) -> Iterator[bytes]:
        source.seek(start)
        remaining = length
        while remaining > 0:
            piece = source.read(min(_READ_CHUNK_BYTES, remaining))
            if piece == b"":
                raise BlobSealError("This file is shorter than its seal says")
            remaining -= len(piece)
            yield piece

    def read_all(self, blob_id: str, seal: BlobSeal) -> bytes:
        content = b"".join(self.read_range(blob_id, seal, start=0, length=seal.real_size))
        if hashlib.sha256(content).hexdigest() != seal.sha256:
            raise BlobSealError(f"Blob {blob_id} does not match its checksum")
        return content

    def verify(self, blob_id: str, seal: BlobSeal) -> None:
        """Read the whole blob a piece at a time: it must decrypt and match its seal."""
        digest = hashlib.sha256()
        for piece in self.read_range(blob_id, seal, start=0, length=seal.real_size):
            digest.update(piece)
        if digest.hexdigest() != seal.sha256:
            raise BlobSealError(f"Blob {blob_id} does not match its checksum")

    def copy(self, blob_id: str, seal: BlobSeal, *, is_encrypted: bool) -> StoredBlob:
        """A new blob with the same content, encrypted or not. The old one is left for retire()."""
        with self.writer(is_encrypted=is_encrypted) as writer:
            for piece in self.read_range(blob_id, seal, start=0, length=seal.real_size):
                writer.write(piece)
            copied = writer.finish()
        if copied.seal.sha256 != seal.sha256:
            raise BlobSealError(f"Blob {blob_id} does not match its checksum")
        return copied

    def install_stored(self, blob_id: str, source: BinaryIO, *, sha256: str) -> None:
        """Put a blob's stored bytes back from a backup. Blobs never change, so one already here
        under this ID must be this same blob, and stays."""
        final_path = self.path_of(blob_id)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = final_path.with_name(final_path.name + _TEMPORARY_SUFFIX)
        digest = hashlib.sha256()
        with temporary_path.open("xb") as handle:
            for chunk in iter(lambda: source.read(_READ_CHUNK_BYTES), b""):
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if digest.hexdigest() != sha256:
            temporary_path.unlink()
            raise BlobSealError(f"Backup holds different bytes for blob {blob_id}")
        if final_path.exists():
            temporary_path.unlink()
            with final_path.open("rb") as existing:
                existing_digest = hashlib.file_digest(existing, "sha256").hexdigest()
            if existing_digest != sha256:
                raise BlobSealError(f"Blob {blob_id} differs from the backup's copy of it")
            return
        os.rename(temporary_path, final_path)
        _sync_directory(final_path.parent)

    def stored_size(self, blob_id: str) -> int:
        return self.path_of(blob_id).stat().st_size

    def pin(self, blob_ids: Collection[str]) -> None:
        _pins.pin(self.path_of(blob_id) for blob_id in blob_ids)

    def unpin(self, blob_ids: Collection[str]) -> None:
        _pins.unpin(self.path_of(blob_id) for blob_id in blob_ids)

    @contextmanager
    def pinned(self, blob_ids: Collection[str]) -> Iterator[None]:
        self.pin(blob_ids)
        try:
            yield
        finally:
            self.unpin(blob_ids)

    def retire(self, blob_ids: Collection[str]) -> None:
        """Delete blobs the committed catalog no longer names, each once nothing is reading it."""
        _pins.retire(self.path_of(blob_id) for blob_id in blob_ids)

    def sweep(self, *, referenced_blob_ids: Collection[str], grace_seconds: int) -> int:
        """Delete what no catalog row names and is older than the grace period: a crash's
        leftovers. Needs no key: blob IDs and file ages are all it reads. Returns how many went."""
        if not self.directory.exists():
            return 0
        oldest_kept = time.time() - grace_seconds
        referenced_names = {f"{blob_id}{BLOB_FILE_SUFFIX}" for blob_id in referenced_blob_ids}
        removed_count = 0
        with _pins.lock:
            for path in sorted(self.directory.glob(f"*/*{BLOB_FILE_SUFFIX}*")):
                if path.name in referenced_names or path.stat().st_mtime > oldest_kept:
                    continue
                path.unlink()
                removed_count += 1
        return removed_count
