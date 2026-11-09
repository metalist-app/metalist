"""One file per stored item (docs/design/file-storage.md): written whole or not at
all, padded while the vault has a password, and never deleted while something still needs it."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
import pytest

from app.db.blob_store import BlobSeal, BlobSealError, BlobStore, padded_size

_ONE_PERCENT_DIVISOR = 100


@pytest.fixture
def store(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "blobs")


@pytest.mark.parametrize("is_encrypted", [True, False])
@pytest.mark.parametrize("size", [0, 1, 1000, 65_536, 65_537, 300_000])
def test_a_blob_reads_back_exactly(store: BlobStore, is_encrypted: bool, size: int) -> None:
    content = os.urandom(size)

    stored = store.write(content, is_encrypted=is_encrypted)

    assert store.read_all(stored.blob_id, stored.seal) == content
    assert stored.seal.real_size == size


def test_without_a_password_the_file_is_its_own_bytes(store: BlobStore) -> None:
    stored = store.write(b"plain words", is_encrypted=False)

    assert store.path_of(stored.blob_id).read_bytes() == b"plain words"
    assert stored.seal.file_key is None


def test_with_a_password_the_file_shows_nothing_of_the_content(store: BlobStore) -> None:
    stored = store.write(b"secret words", is_encrypted=True)

    assert b"secret words" not in store.path_of(stored.blob_id).read_bytes()
    assert stored.seal.file_key is not None


def test_names_are_random_and_fan_out_by_their_first_two_characters(store: BlobStore) -> None:
    first, second = store.write(b"same", is_encrypted=False), store.write(b"same", is_encrypted=False)

    assert first.blob_id != second.blob_id
    assert store.path_of(first.blob_id).parent.name == first.blob_id[:2]
    assert store.path_of(first.blob_id).name == f"{first.blob_id}.mlb"


@pytest.mark.parametrize("blob_id", ["../../etc/passwd", "short", "a" * 31 + "/"])
def test_a_blob_id_cannot_name_another_path(store: BlobStore, blob_id: str) -> None:
    with pytest.raises(ValueError, match="Not a blob ID"):
        store.path_of(blob_id)


@pytest.mark.parametrize(
    ("real_size", "expected"),
    [(0, 0), (1, 1), (2, 2), (3, 3), (9, 10), (100, 104), (1000, 1024), (1_000_000, 1_015_808)],
)
def test_padme_rounds_to_the_published_sizes(real_size: int, expected: int) -> None:
    assert padded_size(real_size) == expected


def test_padme_adds_at_most_about_twelve_percent() -> None:
    for real_size in range(2, 200_000, 997):
        assert real_size <= padded_size(real_size) <= real_size * 1.13


def test_stored_size_is_padded_up_by_at_most_one_percent_more(store: BlobStore) -> None:
    size = 200_000
    sizes = {store.stored_size(store.write(os.urandom(size), is_encrypted=True).blob_id) for _ in range(8)}
    segments = padded_size(size) // 65_536 + 3
    overhead = 11 + segments * 16

    assert len(sizes) > 1, "the random part should vary"
    assert all(padded_size(size) <= stored <= padded_size(size) + size // _ONE_PERCENT_DIVISOR + overhead for stored in sizes)


def test_padding_never_reaches_a_reader(store: BlobStore) -> None:
    content = os.urandom(70_000)
    stored = store.write(content, is_encrypted=True)

    with pytest.raises(ValueError, match="outside"):
        store.read_range(stored.blob_id, stored.seal, start=0, length=stored.seal.real_size + 1)
    assert b"".join(store.read_range(stored.blob_id, stored.seal, start=69_990, length=10)) == content[-10:]


@pytest.mark.parametrize("is_encrypted", [True, False])
def test_a_range_is_exactly_those_bytes(store: BlobStore, is_encrypted: bool) -> None:
    content = os.urandom(200_000)
    stored = store.write(content, is_encrypted=is_encrypted)

    assert b"".join(store.read_range(stored.blob_id, stored.seal, start=65_000, length=70_000)) == content[65_000:135_000]


def test_a_failed_write_leaves_nothing_behind(store: BlobStore) -> None:
    with pytest.raises(OSError, match="disk full"):
        with store.writer(is_encrypted=True) as writer:
            writer.write(b"part of it")
            raise OSError("disk full")

    assert list(store.directory.glob("*/*")) == []


def test_a_write_not_finished_is_not_a_blob_yet(store: BlobStore) -> None:
    with store.writer(is_encrypted=False) as writer:
        writer.write(b"part")
        assert [path.suffix for path in store.directory.glob("*/*")] == [".tmp"]
        writer.finish()

    assert [path.suffix for path in store.directory.glob("*/*")] == [".mlb"]


def test_a_changed_byte_is_refused_with_a_password(store: BlobStore) -> None:
    stored = store.write(os.urandom(1000), is_encrypted=True)
    path = store.path_of(stored.blob_id)
    data = bytearray(path.read_bytes())
    data[40] ^= 1
    path.write_bytes(bytes(data))

    with pytest.raises(InvalidTag):
        store.verify(stored.blob_id, stored.seal)


def test_a_changed_byte_is_refused_without_a_password(store: BlobStore) -> None:
    stored = store.write(b"plain words", is_encrypted=False)
    store.path_of(stored.blob_id).write_bytes(b"plain wordz")

    with pytest.raises(BlobSealError, match="checksum"):
        store.verify(stored.blob_id, stored.seal)


def test_the_wrong_seal_is_refused(store: BlobStore) -> None:
    first, second = store.write(b"first", is_encrypted=True), store.write(b"second", is_encrypted=True)

    with pytest.raises(InvalidTag):
        store.read_all(first.blob_id, second.seal)


@pytest.mark.parametrize("file_key", [None, bytes(range(32))])
def test_a_seal_survives_being_stored(file_key: bytes | None) -> None:
    seal = BlobSeal(file_key=file_key, real_size=12, sha256="ab" * 32)

    assert BlobSeal.from_bytes(seal.to_bytes()) == seal


def test_a_seal_with_other_fields_is_refused() -> None:
    with pytest.raises(BlobSealError, match="exactly"):
        BlobSeal.from_bytes(b'{"key":null,"size":1}')


@pytest.mark.parametrize("to_encrypted", [True, False])
def test_copying_changes_only_the_encryption(store: BlobStore, to_encrypted: bool) -> None:
    content = os.urandom(150_000)
    original = store.write(content, is_encrypted=not to_encrypted)

    copied = store.copy(original.blob_id, original.seal, is_encrypted=to_encrypted)

    assert copied.blob_id != original.blob_id
    assert store.read_all(copied.blob_id, copied.seal) == content
    assert store.contains(original.blob_id)


def test_retiring_deletes_a_blob_nothing_is_reading(store: BlobStore) -> None:
    stored = store.write(b"old", is_encrypted=False)

    store.retire([stored.blob_id])

    assert not store.contains(stored.blob_id)


def test_a_blob_being_read_is_deleted_only_when_the_read_ends(store: BlobStore) -> None:
    """Windows refuses to delete an open file, and a read in progress must finish."""
    content = os.urandom(3_000_000)
    stored = store.write(content, is_encrypted=False)
    pieces = store.read_range(stored.blob_id, stored.seal, start=0, length=len(content))
    first = next(pieces)

    store.retire([stored.blob_id])

    assert store.contains(stored.blob_id)
    assert first + b"".join(pieces) == content
    assert not store.contains(stored.blob_id)


def test_a_read_abandoned_part_way_still_lets_the_blob_go(store: BlobStore) -> None:
    stored = store.write(os.urandom(3_000_000), is_encrypted=False)
    pieces = store.read_range(stored.blob_id, stored.seal, start=0, length=stored.seal.real_size)
    next(pieces)
    store.retire([stored.blob_id])

    pieces.close()

    assert not store.contains(stored.blob_id)


def test_a_blob_with_two_readers_waits_for_both(store: BlobStore) -> None:
    stored = store.write(b"shared", is_encrypted=False)
    store.pin([stored.blob_id])
    store.pin([stored.blob_id])
    store.retire([stored.blob_id])

    store.unpin([stored.blob_id])
    assert store.contains(stored.blob_id)
    store.unpin([stored.blob_id])
    assert not store.contains(stored.blob_id)


def test_unpinning_what_was_not_pinned_is_a_bug(store: BlobStore) -> None:
    stored = store.write(b"x", is_encrypted=False)

    with pytest.raises(AssertionError, match="not pinned"):
        store.unpin([stored.blob_id])


def _make_old(path: Path, seconds: int) -> None:
    old_time = path.stat().st_mtime - seconds
    os.utime(path, (old_time, old_time))


def test_the_sweep_removes_only_old_files_no_row_names(store: BlobStore) -> None:
    named, young, old = (store.write(b"x", is_encrypted=False) for _ in range(3))
    _make_old(store.path_of(named.blob_id), 7200)
    _make_old(store.path_of(old.blob_id), 7200)

    removed = store.sweep(referenced_blob_ids={named.blob_id}, grace_seconds=3600)

    assert removed == 1
    assert store.contains(named.blob_id) and store.contains(young.blob_id)
    assert not store.contains(old.blob_id)


def test_the_sweep_removes_an_old_half_written_file(store: BlobStore) -> None:
    stored = store.write(b"x", is_encrypted=False)
    leftover = store.path_of(stored.blob_id).with_name("a" * 32 + ".mlb.tmp")
    leftover.write_bytes(b"half")
    _make_old(leftover, 7200)

    assert store.sweep(referenced_blob_ids={stored.blob_id}, grace_seconds=3600) == 1
    assert not leftover.exists()


def test_the_sweep_of_a_vault_with_no_blobs_does_nothing(store: BlobStore) -> None:
    assert store.sweep(referenced_blob_ids=set(), grace_seconds=0) == 0
