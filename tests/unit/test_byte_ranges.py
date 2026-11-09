"""One Range header, resolved against a file's size (RFC 9110, section 14)."""

from __future__ import annotations

import pytest

from app.api.byte_ranges import UNSATISFIABLE_RANGE, ByteRange, resolve_byte_range

_SIZE = 1000


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-0", ByteRange(start=0, length=1)),
        ("bytes=0-999", ByteRange(start=0, length=1000)),
        ("bytes=100-199", ByteRange(start=100, length=100)),
        ("bytes=500-", ByteRange(start=500, length=500)),
        ("bytes=999-", ByteRange(start=999, length=1)),
        ("bytes=900-5000", ByteRange(start=900, length=100)),
        ("bytes=-1", ByteRange(start=999, length=1)),
        ("bytes=-100", ByteRange(start=900, length=100)),
        ("bytes=-5000", ByteRange(start=0, length=1000)),
    ],
)
def test_a_range_within_the_file(header: str, expected: ByteRange) -> None:
    assert resolve_byte_range(header, file_size=_SIZE) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=5000-6000", "bytes=-0"])
def test_a_range_past_the_end_cannot_be_satisfied(header: str) -> None:
    assert resolve_byte_range(header, file_size=_SIZE) is UNSATISFIABLE_RANGE


@pytest.mark.parametrize("header", [None, "bytes=-", "items=0-10", "bytes=0-10,20-30", "bytes=abc-def", "bytes=20-10", "nonsense"])
def test_anything_else_asks_for_the_whole_file(header: str | None) -> None:
    assert resolve_byte_range(header, file_size=_SIZE) is None


def test_any_range_of_an_empty_file_cannot_be_satisfied() -> None:
    assert resolve_byte_range("bytes=0-", file_size=0) is UNSATISFIABLE_RANGE
    assert resolve_byte_range("bytes=-5", file_size=0) is UNSATISFIABLE_RANGE
