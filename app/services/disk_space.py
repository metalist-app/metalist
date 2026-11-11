"""A file is refused before it is stored when it wouldn't fit, and when the disk fills while it
is being written (docs/design/file-storage.md, section 14): a full disk would stop
notes saving and backups, and refusing one file is far better."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import errno
import os
import shutil

from app.data_directory import resolve_data_directory
from app.db.blob_store import most_stored_bytes
from app.services.input_errors import InputRejected
from app.utils.byte_sizes import GIB, MIB

# What stays free: 1 GiB or 5% of the disk, whichever is smaller (proposed in the plan, 2026-11-06).
_FREE_RESERVE_BYTES = GIB
_FREE_RESERVE_DISK_DIVISOR = 20
_FULL_DISK_MESSAGE = "The disk filled up while this file was being stored, so it wasn't kept. Free up some space and try again."


def _readable_size(byte_count: int) -> str:
    if byte_count >= GIB:
        return f"{byte_count / GIB:.1f} GB"
    return f"{max(byte_count, MIB) / MIB:.0f} MB"


def require_room_for_files(incoming_sizes: list[int]) -> None:
    """Refuse files that would leave the disk with less than its reserve, saying how much is missing."""
    usage = shutil.disk_usage(resolve_data_directory(environ=os.environ))
    needed = sum(most_stored_bytes(size) for size in incoming_sizes) + min(_FREE_RESERVE_BYTES, usage.total // _FREE_RESERVE_DISK_DIVISOR)
    if needed > usage.free:
        raise InputRejected(f"There isn't enough free space for this. It needs about {_readable_size(needed - usage.free)} more.")


@contextmanager
def full_disk_is_rejected() -> Iterator[None]:
    """A disk that fills mid-write (something else wrote to it) is the same plain message. The
    half-written file is removed by whatever was writing it."""
    # lint: allow-PY001 rationale="a full disk is an expected external failure, shown to the person as a plain message"
    try:
        yield  # shockharness: ignore[EXC003] reason="the one operation is the caller's write to disk, which this context manager wraps"
    # lint: allow-PY001 rationale="a full disk is an expected external failure, shown to the person as a plain message"
    except OSError as exc:
        if exc.errno != errno.ENOSPC:
            raise
        raise InputRejected(_FULL_DISK_MESSAGE) from exc
