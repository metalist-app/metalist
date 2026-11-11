"""One encrypted item as one stream (docs/design/file-storage.md, section 4):
any size in or out a segment at a time, and a blob someone cut, reordered or spliced never
reads back as if it were whole. The format numbers are written out here rather than imported,
so a change to the format on disk fails these tests instead of following along."""

from __future__ import annotations

import io
import os
from pathlib import Path
import tracemalloc

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

from app.security.streaming_blob import BlobFormatError, StreamingBlobReader, StreamingBlobWriter

_KEY = bytes(range(32))
_OTHER_KEY = bytes(range(1, 33))
_HEADER_BYTES = 11
_SEGMENT_BYTES = 65_536
_TAG_BYTES = 16
_SEALED_BYTES = _SEGMENT_BYTES + _TAG_BYTES
_DAMAGED = (BlobFormatError, InvalidTag)
_LARGE_FILE_BYTES = 32 * 1024 * 1024
_MEMORY_CEILING_BYTES = 512 * 1024


def _plaintext(size: int) -> bytes:
    """size bytes in which every position differs from its neighbours' segments."""
    pattern = bytes(index % 251 for index in range(size % 251 + 251))
    return (pattern * (size // len(pattern) + 1))[:size]


def _sealed(plaintext: bytes, key: bytes, chunk_bytes: int) -> bytes:
    destination = io.BytesIO()
    writer = StreamingBlobWriter(destination, file_key=key)
    for start in range(0, len(plaintext), chunk_bytes):
        writer.write(plaintext[start:start + chunk_bytes])
    writer.finish()
    return destination.getvalue()


def _opened(stored: bytes, key: bytes) -> bytes:
    reader = StreamingBlobReader(io.BytesIO(stored), file_key=key)
    return b"".join(reader.read(0, reader.plaintext_size))


def _segment_start(index: int) -> int:
    return _HEADER_BYTES + index * _SEALED_BYTES


def _three_segments(key: bytes) -> bytes:
    return _sealed(_plaintext(_SEGMENT_BYTES * 2 + 100), key, _SEGMENT_BYTES)


@pytest.mark.parametrize(
    "size",
    [0, 1, _SEGMENT_BYTES - 1, _SEGMENT_BYTES, _SEGMENT_BYTES + 1, _SEGMENT_BYTES * 2, _SEGMENT_BYTES * 2 + 1],
)
@pytest.mark.parametrize("chunk_bytes", [1000, _SEGMENT_BYTES, _SEGMENT_BYTES * 3])
def test_any_size_reads_back_exactly_however_it_was_written(size: int, chunk_bytes: int) -> None:
    plaintext = _plaintext(size)
    stored = _sealed(plaintext, _KEY, chunk_bytes)

    reader = StreamingBlobReader(io.BytesIO(stored), file_key=_KEY)

    assert reader.plaintext_size == size
    assert b"".join(reader.read(0, size)) == plaintext


@pytest.mark.parametrize(
    ("size", "stored_size"),
    [
        (0, _HEADER_BYTES + _TAG_BYTES),
        (1, _HEADER_BYTES + _TAG_BYTES + 1),
        (_SEGMENT_BYTES, _HEADER_BYTES + _SEALED_BYTES),
        (_SEGMENT_BYTES + 1, _HEADER_BYTES + _SEALED_BYTES + _TAG_BYTES + 1),
    ],
)
def test_the_stored_size_follows_from_the_format(size: int, stored_size: int) -> None:
    """A file of exactly one segment has no empty segment after it."""
    assert len(_sealed(_plaintext(size), _KEY, _SEGMENT_BYTES)) == stored_size


def test_a_blob_built_by_hand_from_the_written_format_reads_back() -> None:
    """The format on disk, stated independently of the code that writes it."""
    prefix = bytes.fromhex("01020304050607")
    header = b"ML" + bytes((1, 1)) + prefix
    first, last = b"a" * _SEGMENT_BYTES, b"the end"
    aead = AESGCM(_KEY)
    stored = (
        header
        + aead.encrypt(prefix + (0).to_bytes(4, "big") + b"\x00", first, header)
        + aead.encrypt(prefix + (1).to_bytes(4, "big") + b"\x01", last, header)
    )

    assert _opened(stored, _KEY) == first + last


def test_two_blobs_of_the_same_bytes_under_one_key_differ() -> None:
    """A revision of an item may keep its key, so a blob's nonces must be its own."""
    plaintext = _plaintext(_SEGMENT_BYTES + 5)

    first, second = _sealed(plaintext, _KEY, _SEGMENT_BYTES), _sealed(plaintext, _KEY, _SEGMENT_BYTES)

    assert first[_HEADER_BYTES:_HEADER_BYTES + _SEALED_BYTES] != second[_HEADER_BYTES:_HEADER_BYTES + _SEALED_BYTES]


@pytest.mark.parametrize(
    ("start", "length"),
    [
        (0, 1),
        (_SEGMENT_BYTES - 1, 1),
        (_SEGMENT_BYTES, 1),
        (_SEGMENT_BYTES - 1, 2),
        (10, _SEGMENT_BYTES * 2 + 20),
        (_SEGMENT_BYTES * 2 + 99, 1),
        (_SEGMENT_BYTES * 2 + 100, 0),
        (500, 0),
    ],
)
def test_a_range_is_exactly_those_bytes(start: int, length: int) -> None:
    plaintext = _plaintext(_SEGMENT_BYTES * 2 + 100)
    reader = StreamingBlobReader(io.BytesIO(_sealed(plaintext, _KEY, _SEGMENT_BYTES)), file_key=_KEY)

    assert b"".join(reader.read(start, length)) == plaintext[start:start + length]


@pytest.mark.parametrize(("start", "length"), [(-1, 1), (0, -1), (0, _SEGMENT_BYTES * 2 + 101), (_SEGMENT_BYTES * 2 + 101, 0)])
def test_a_range_outside_the_file_is_refused_when_asked_for(start: int, length: int) -> None:
    reader = StreamingBlobReader(io.BytesIO(_three_segments(_KEY)), file_key=_KEY)

    with pytest.raises(ValueError, match="outside"):
        reader.read(start, length)


class _CountingSource(io.BytesIO):
    def __init__(self, stored: bytes, bytes_read: list[int]) -> None:
        super().__init__(stored)
        self._bytes_read = bytes_read

    def read(self, size: int) -> bytes:  # type: ignore[override]
        data = super().read(size)
        self._bytes_read.append(len(data))
        return data


def test_reading_one_byte_reads_only_the_segment_it_is_in() -> None:
    stored = _sealed(_plaintext(_SEGMENT_BYTES * 20), _KEY, _SEGMENT_BYTES)
    bytes_read: list[int] = []
    reader = StreamingBlobReader(_CountingSource(stored, bytes_read), file_key=_KEY)
    bytes_read.clear()

    list(reader.read(_SEGMENT_BYTES * 7 + 3, 1))

    assert bytes_read == [_SEALED_BYTES]


@pytest.mark.parametrize(
    "stored_size",
    [
        0,
        1,
        _HEADER_BYTES,
        _HEADER_BYTES + _TAG_BYTES - 1,
        _segment_start(1),
        _segment_start(1) + 1,
        _segment_start(1) + _TAG_BYTES,
        _segment_start(1) + _TAG_BYTES + 1,
        _segment_start(2),
        _segment_start(2) + 50,
    ],
)
def test_a_cut_off_blob_is_refused_when_opened(stored_size: int) -> None:
    """Refused at open, so a size is never believed and a short read never looks like the end."""
    with pytest.raises(_DAMAGED):
        StreamingBlobReader(io.BytesIO(_three_segments(_KEY)[:stored_size]), file_key=_KEY)


def test_a_blob_never_finished_is_refused() -> None:
    """A crash mid-write leaves segments with no final one."""
    destination = io.BytesIO()
    writer = StreamingBlobWriter(destination, file_key=_KEY)
    writer.write(_plaintext(_SEGMENT_BYTES * 3))

    with pytest.raises(_DAMAGED):
        StreamingBlobReader(io.BytesIO(destination.getvalue()), file_key=_KEY)


# Named by size: pytest keeps the running test's name in an environment variable, which Windows
# caps at 32,767 characters.
@pytest.mark.parametrize("extra", [b"x", b"x" * _TAG_BYTES, b"x" * _SEALED_BYTES], ids=["a-byte", "a-tag", "a-segment"])
def test_bytes_added_to_the_end_are_refused(extra: bytes) -> None:
    with pytest.raises(_DAMAGED):
        StreamingBlobReader(io.BytesIO(_three_segments(_KEY) + extra), file_key=_KEY)


def test_a_segment_after_the_final_one_is_refused() -> None:
    stored = _sealed(_plaintext(_SEGMENT_BYTES), _KEY, _SEGMENT_BYTES)

    with pytest.raises(_DAMAGED):
        StreamingBlobReader(io.BytesIO(stored + stored[_HEADER_BYTES:]), file_key=_KEY)


def test_swapped_segments_are_refused() -> None:
    stored = _three_segments(_KEY)
    first = stored[_segment_start(0):_segment_start(1)]
    second = stored[_segment_start(1):_segment_start(2)]
    swapped = stored[:_segment_start(0)] + second + first + stored[_segment_start(2):]

    with pytest.raises(InvalidTag):
        _opened(swapped, _KEY)


def test_a_segment_from_another_blob_under_the_same_key_is_refused() -> None:
    stored, other = _three_segments(_KEY), _three_segments(_KEY)
    spliced = stored[:_segment_start(1)] + other[_segment_start(1):_segment_start(2)] + stored[_segment_start(2):]

    with pytest.raises(InvalidTag):
        _opened(spliced, _KEY)


def test_a_range_never_returns_bytes_from_a_damaged_segment() -> None:
    stored = bytearray(_three_segments(_KEY))
    stored[_segment_start(1) + 40] ^= 1
    reader = StreamingBlobReader(io.BytesIO(bytes(stored)), file_key=_KEY)

    assert b"".join(reader.read(0, _SEGMENT_BYTES)) == _plaintext(_SEGMENT_BYTES * 2 + 100)[:_SEGMENT_BYTES]
    with pytest.raises(InvalidTag):
        list(reader.read(_SEGMENT_BYTES, 1))


@pytest.mark.parametrize(
    "position",
    [
        _HEADER_BYTES - 1,
        _segment_start(0),
        _segment_start(1) - 1,
        _segment_start(1),
        _segment_start(2),
    ],
)
def test_one_changed_bit_is_refused(position: int) -> None:
    stored = bytearray(_three_segments(_KEY))
    stored[position] ^= 1

    with pytest.raises(InvalidTag):
        _opened(bytes(stored), _KEY)


def test_the_wrong_key_is_refused() -> None:
    with pytest.raises(InvalidTag):
        StreamingBlobReader(io.BytesIO(_three_segments(_KEY)), file_key=_OTHER_KEY)


@pytest.mark.parametrize(
    ("position", "replacement", "complaint"),
    [(0, 0x58, "not a MetaList blob"), (2, 2, "suite"), (3, 2, "version")],
)
def test_an_unknown_header_says_what_is_wrong(position: int, replacement: int, complaint: str) -> None:
    stored = bytearray(_three_segments(_KEY))
    stored[position] = replacement

    with pytest.raises(BlobFormatError, match=complaint):
        StreamingBlobReader(io.BytesIO(bytes(stored)), file_key=_KEY)


@pytest.mark.parametrize("key", [b"", b"short", bytes(31), bytes(33)])
def test_a_key_of_the_wrong_length_is_refused(key: bytes) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        StreamingBlobWriter(io.BytesIO(), file_key=key)
    with pytest.raises(ValueError, match="32 bytes"):
        StreamingBlobReader(io.BytesIO(_three_segments(_KEY)), file_key=key)


def test_a_finished_writer_takes_nothing_more() -> None:
    writer = StreamingBlobWriter(io.BytesIO(), file_key=_KEY)
    writer.finish()

    with pytest.raises(RuntimeError, match="finished"):
        writer.write(b"more")
    with pytest.raises(RuntimeError, match="finished"):
        writer.finish()


class _Discard(io.RawIOBase):
    def write(self, data: bytes) -> int:  # type: ignore[override]
        return len(data)


def test_writing_a_large_file_holds_only_a_segment_or_so_in_memory() -> None:
    chunk = os.urandom(_SEGMENT_BYTES // 2)
    writer = StreamingBlobWriter(_Discard(), file_key=_KEY)

    tracemalloc.start()
    for _ in range(_LARGE_FILE_BYTES // len(chunk)):
        writer.write(chunk)
    writer.finish()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak < _MEMORY_CEILING_BYTES


def test_reading_a_large_file_holds_only_a_segment_or_so_in_memory(tmp_path: Path) -> None:
    path = tmp_path / "large.mlb"
    chunk = os.urandom(_SEGMENT_BYTES // 2)
    with path.open("wb") as destination:
        writer = StreamingBlobWriter(destination, file_key=_KEY)
        for _ in range(_LARGE_FILE_BYTES // len(chunk)):
            writer.write(chunk)
        writer.finish()

    total_bytes = 0
    with path.open("rb") as source:
        reader = StreamingBlobReader(source, file_key=_KEY)
        tracemalloc.start()
        for piece in reader.read(0, reader.plaintext_size):
            total_bytes += len(piece)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    assert total_bytes == _LARGE_FILE_BYTES
    assert peak < _MEMORY_CEILING_BYTES
