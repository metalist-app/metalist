"""One encrypted item as one stream, a segment at a time, so memory stays small at any file size
(docs/design/file-storage.md, section 4). Not connected to file storage yet.

The format, version 1:

    header    "ML", suite byte (1: AES-256-GCM), version byte (1), 7 random nonce-prefix bytes
    segments  each 64 KiB of plaintext sealed with AES-256-GCM, its 16-byte tag after it;
              the last holds what is left: 1 to 64 KiB, or nothing only for an empty file

A segment's nonce is the prefix, its index (4 bytes, big-endian) and a final flag (1 byte, 1 on
the last segment only), and the whole header is its associated data. So a segment moved, taken
from another blob or cut off fails its tag. The prefix makes a blob's nonces its own even if a
revision of an item keeps the item's key.

A failed tag raises cryptography's InvalidTag and stops, as everywhere in MetaList's decryption.
Padding sits above this layer: the writer is given padded bytes, the catalog knows the real size.
"""

from __future__ import annotations

from collections.abc import Iterator
import os
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.security.crypto_sizes import AES_256_KEY_BYTES, GCM_NONCE_BYTES, GCM_TAG_BYTES

_MAGIC = b"ML"
_SUITE_AES_256_GCM = 1
_FORMAT_VERSION = 1
_COUNTER_BYTES = 4
_MORE_SEGMENTS_FOLLOW = b"\x00"
_FINAL_SEGMENT = b"\x01"
_NONCE_PREFIX_BYTES = GCM_NONCE_BYTES - _COUNTER_BYTES - len(_FINAL_SEGMENT)
_SUITE_POSITION = len(_MAGIC)
_VERSION_POSITION = _SUITE_POSITION + 1
_PREFIX_POSITION = _VERSION_POSITION + 1
_HEADER_BYTES = _PREFIX_POSITION + _NONCE_PREFIX_BYTES
_PLAINTEXT_SEGMENT_BYTES = 64 * 1024
_SEALED_SEGMENT_BYTES = _PLAINTEXT_SEGMENT_BYTES + GCM_TAG_BYTES


class BlobFormatError(ValueError):
    """The stored bytes cannot be a blob of a format this MetaList reads."""


def _require_file_key(file_key: bytes) -> None:
    if len(file_key) != AES_256_KEY_BYTES:
        raise ValueError(f"A file key is {AES_256_KEY_BYTES} bytes, got {len(file_key)}")


def _segment_nonce(prefix: bytes, index: int, *, is_final: bool) -> bytes:
    # to_bytes raises OverflowError past 2^32 segments (256 TiB), before any nonce could repeat.
    counter = index.to_bytes(_COUNTER_BYTES, "big")
    if is_final:
        return prefix + counter + _FINAL_SEGMENT
    return prefix + counter + _MORE_SEGMENTS_FOLLOW


class StreamingBlobWriter:
    """Encrypts into destination as bytes arrive. Holds at most one segment of plaintext.

    finish() must be called or the blob is refused when read. Syncing, renaming and closing the
    destination are the caller's.
    """

    def __init__(self, destination: BinaryIO, *, file_key: bytes) -> None:
        _require_file_key(file_key)
        self._destination = destination
        self._aead = AESGCM(file_key)
        self._nonce_prefix = os.urandom(_NONCE_PREFIX_BYTES)
        self._header = _MAGIC + bytes((_SUITE_AES_256_GCM, _FORMAT_VERSION)) + self._nonce_prefix
        assert len(self._header) == _HEADER_BYTES
        self._pending = bytearray()
        self._next_index = 0
        self._is_finished = False
        destination.write(self._header)

    def write(self, plaintext: bytes) -> None:
        self._require_unfinished()
        remaining = memoryview(plaintext)
        # Strictly more than a segment waiting proves this one is not the last.
        while len(self._pending) + len(remaining) > _PLAINTEXT_SEGMENT_BYTES:
            taken = _PLAINTEXT_SEGMENT_BYTES - len(self._pending)
            self._pending += remaining[:taken]
            remaining = remaining[taken:]
            self._seal_pending(is_final=False)
        self._pending += remaining

    def finish(self) -> None:
        self._require_unfinished()
        self._seal_pending(is_final=True)
        self._is_finished = True

    def _require_unfinished(self) -> None:
        if self._is_finished:
            raise RuntimeError("This blob is finished: nothing more can be written to it")

    def _seal_pending(self, *, is_final: bool) -> None:
        assert len(self._pending) <= _PLAINTEXT_SEGMENT_BYTES
        nonce = _segment_nonce(self._nonce_prefix, self._next_index, is_final=is_final)
        self._destination.write(self._aead.encrypt(nonce, bytes(self._pending), self._header))
        self._pending.clear()
        self._next_index += 1


class StreamingBlobReader:
    """Decrypts any range of a blob, reading only the segments it covers.

    Opening authenticates the last segment, so plaintext_size can be trusted and a blob cut off
    at any point is refused at once. Each segment is authenticated before any of it is returned.
    One reader per open source: it moves the source's position.
    """

    def __init__(self, source: BinaryIO, *, file_key: bytes) -> None:
        _require_file_key(file_key)
        self._source = source
        self._aead = AESGCM(file_key)
        self._header = self._read_exactly(_HEADER_BYTES)
        self._require_known_format()
        self._nonce_prefix = self._header[_PREFIX_POSITION:]
        sealed_bytes = source.seek(0, os.SEEK_END) - _HEADER_BYTES
        if sealed_bytes < GCM_TAG_BYTES:
            raise BlobFormatError("This blob has been cut off: it has no complete segment")
        self._segment_count = (sealed_bytes + _SEALED_SEGMENT_BYTES - 1) // _SEALED_SEGMENT_BYTES
        self._last_sealed_bytes = sealed_bytes - (self._segment_count - 1) * _SEALED_SEGMENT_BYTES
        if self._segment_count > 1 and self._last_sealed_bytes == GCM_TAG_BYTES:
            raise BlobFormatError("This blob has been cut off: its last segment is empty")
        if self._last_sealed_bytes < GCM_TAG_BYTES:
            raise BlobFormatError("This blob has been cut off inside a segment's tag")
        last_segment = self._open_segment(self._segment_count - 1)
        self._plaintext_size = (self._segment_count - 1) * _PLAINTEXT_SEGMENT_BYTES + len(last_segment)

    @property
    def plaintext_size(self) -> int:
        return self._plaintext_size

    def read(self, start: int, length: int) -> Iterator[bytes]:
        """The plaintext from start, length bytes, a segment at a time. A range outside the file
        is refused here, when asked for, not on the first iteration."""
        if start < 0 or length < 0 or start + length > self._plaintext_size:
            raise ValueError(f"Bytes {start}+{length} are outside this {self._plaintext_size}-byte blob")
        return self._segments_of_range(start, length)

    def _segments_of_range(self, start: int, length: int) -> Iterator[bytes]:
        if length == 0:
            return
        end = start + length
        first_index = start // _PLAINTEXT_SEGMENT_BYTES
        last_index = (end - 1) // _PLAINTEXT_SEGMENT_BYTES
        for index in range(first_index, last_index + 1):
            segment_start = index * _PLAINTEXT_SEGMENT_BYTES
            yield self._open_segment(index)[max(start - segment_start, 0):end - segment_start]

    def _open_segment(self, index: int) -> bytes:
        assert 0 <= index < self._segment_count
        is_final = index == self._segment_count - 1
        sealed_bytes = _SEALED_SEGMENT_BYTES
        if is_final:
            sealed_bytes = self._last_sealed_bytes
        self._source.seek(_HEADER_BYTES + index * _SEALED_SEGMENT_BYTES)
        sealed = self._read_exactly(sealed_bytes)
        return self._aead.decrypt(_segment_nonce(self._nonce_prefix, index, is_final=is_final), sealed, self._header)

    def _read_exactly(self, byte_count: int) -> bytes:
        stored = self._source.read(byte_count)
        if len(stored) != byte_count:
            raise BlobFormatError(f"This blob has been cut off: wanted {byte_count} bytes, found {len(stored)}")
        return stored

    def _require_known_format(self) -> None:
        if not self._header.startswith(_MAGIC):
            raise BlobFormatError("This is not a MetaList blob")
        if self._header[_SUITE_POSITION] != _SUITE_AES_256_GCM:
            raise BlobFormatError(f"Unknown encryption suite {self._header[_SUITE_POSITION]} in this blob")
        if self._header[_VERSION_POSITION] != _FORMAT_VERSION:
            raise BlobFormatError(f"Unknown format version {self._header[_VERSION_POSITION]} in this blob")
