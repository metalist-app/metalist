"""The HTTP Range header of a file download (RFC 9110, section 14): one range of bytes, so a jump
into a long file reads only that part."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

_SINGLE_RANGE_RE = re.compile(r"bytes=(?P<start>[0-9]*)-(?P<end>[0-9]*)")


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    length: int


# A range that starts past the end of the file: 416, as opposed to None, a request for the whole file.
UNSATISFIABLE_RANGE: Final = ByteRange(start=0, length=0)


def resolve_byte_range(header: str | None, *, file_size: int) -> ByteRange | None:
    """The one range this header asks for. None (send the whole file) when there is no header, or
    one this server ignores, as RFC 9110 allows: several ranges, or one that is not well formed."""
    if header is None:
        return None
    match = _SINGLE_RANGE_RE.fullmatch(header.strip())
    if match is None:
        return None
    start_text, end_text = match.group("start"), match.group("end")
    if start_text == "" and end_text == "":
        return None
    if start_text == "":
        return _suffix_range(suffix_length=int(end_text), file_size=file_size)
    start = int(start_text)
    if start >= file_size:
        return UNSATISFIABLE_RANGE
    last = file_size - 1
    if end_text != "":
        last = min(int(end_text), last)
        if last < start:
            return None
    return ByteRange(start=start, length=last - start + 1)


def _suffix_range(*, suffix_length: int, file_size: int) -> ByteRange:
    """The last suffix_length bytes (all of them when the file is shorter)."""
    if suffix_length == 0 or file_size == 0:
        return UNSATISFIABLE_RANGE
    length = min(suffix_length, file_size)
    return ByteRange(start=file_size - length, length=length)
