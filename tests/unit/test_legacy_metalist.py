"""The old MetaList's own file, found in MetaList's data folder and only read
(app/services/legacy_metalist.py; docs/ui/legacy-import.md). The encrypted fixture was written by
the old MetaList's own code (tests/fixtures/legacy-export/make-encrypted-fixture.mjs)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.services.input_errors import InputRejected
from app.services.legacy_metalist import (
    LegacyDatabase,
    any_legacy_item,
    decrypted_legacy_items,
    find_legacy_database,
    legacy_password_opens,
    read_legacy_database,
)
from tests.unit.legacy_database_fixture import (
    ENCRYPTED_BUNDLE_PASSWORD,
    SECRET_TEXT,
    encrypted_bundle,
    plain_bundle,
    write_legacy_database,
)


def test_no_old_file_is_nothing_offered(tmp_path: Path) -> None:
    assert find_legacy_database(tmp_path) is None


@pytest.mark.parametrize("bundle, encrypted", [(encrypted_bundle(), True), (plain_bundle(), False)],
                         ids=["protected", "not protected"])
def test_the_old_file_is_found_and_says_whether_it_is_protected(tmp_path: Path, bundle: dict, encrypted: bool) -> None:
    path = write_legacy_database(tmp_path / "metalist.db", bundle)
    assert find_legacy_database(tmp_path) == LegacyDatabase(path=path, encrypted=encrypted)


def test_another_sqlite_file_of_that_name_is_not_the_old_metalist(tmp_path: Path) -> None:
    with closing(sqlite3.connect(tmp_path / "metalist.db")) as connection:
        connection.execute("CREATE TABLE something (value TEXT)")
        connection.commit()
    assert find_legacy_database(tmp_path) is None


def test_a_file_of_that_name_that_is_no_database_is_not_the_old_metalist(tmp_path: Path) -> None:
    (tmp_path / "metalist.db").write_text("not a database", encoding="utf-8")
    assert find_legacy_database(tmp_path) is None


def test_the_notes_come_in_the_old_order_whatever_order_the_rows_are_in(tmp_path: Path) -> None:
    # write_legacy_database writes the rows last item first; prev and next give the order.
    path = write_legacy_database(tmp_path / "metalist.db", plain_bundle())
    payload = read_legacy_database(path)
    assert [item["id"] for item in payload["data"]] == [7, 8]
    assert payload["encryption"] == {"encrypted": False}
    assert payload["data_schema_version"] == 23


def test_reading_the_old_file_leaves_it_unchanged(tmp_path: Path) -> None:
    path = write_legacy_database(tmp_path / "metalist.db", encrypted_bundle())
    before = path.read_bytes()
    read_legacy_database(path)
    any_legacy_item(path)
    find_legacy_database(tmp_path)
    assert path.read_bytes() == before
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["metalist.db"]


def test_notes_that_are_not_one_list_are_refused(tmp_path: Path) -> None:
    bundle = plain_bundle()
    bundle["data"][1]["prev"] = 99
    path = write_legacy_database(tmp_path / "metalist.db", bundle)
    with pytest.raises(InputRejected, match="not one list"):
        read_legacy_database(path)


def test_notes_from_an_older_old_metalist_ask_to_open_them_there_first(tmp_path: Path) -> None:
    bundle = plain_bundle()
    bundle["data_schema_version"] = 22
    path = write_legacy_database(tmp_path / "metalist.db", bundle)
    with pytest.raises(InputRejected, match="Open them once in the old MetaList"):
        read_legacy_database(path)


def test_the_old_password_decrypts_every_note(tmp_path: Path) -> None:
    payload = read_legacy_database(write_legacy_database(tmp_path / "metalist.db", encrypted_bundle()))
    items = decrypted_legacy_items(payload["data"], ENCRYPTED_BUNDLE_PASSWORD)
    assert [item["id"] for item in items] == [1, 2]
    assert items[0]["subitems"][1] == {"indent": 1, "data": SECRET_TEXT, "tags": "@password", "collapse": False}
    assert items[1]["subitems"] == [{"indent": 0, "data": "Groceries", "tags": "todo", "collapse": False}]
    for item in items:
        assert "iv" not in item and "subitems_enc" not in item


@pytest.mark.parametrize("password, opens", [(ENCRYPTED_BUNDLE_PASSWORD, True), ("not-it", False)],
                         ids=["right", "wrong"])
def test_one_note_tells_whether_a_password_opens_them(tmp_path: Path, password: str, opens: bool) -> None:
    path = write_legacy_database(tmp_path / "metalist.db", encrypted_bundle())
    assert legacy_password_opens([any_legacy_item(path)], password) is opens


def test_a_later_note_that_does_not_open_is_damage_not_a_wrong_password() -> None:
    items = encrypted_bundle()["data"]
    ciphertext = items[1]["subitems_enc"]
    items[1]["subitems_enc"] = ("0" if ciphertext[0] != "0" else "1") + ciphertext[1:]
    with pytest.raises(ValueError, match="id=2"):
        decrypted_legacy_items(items, ENCRYPTED_BUNDLE_PASSWORD)


def test_an_old_metalist_without_notes_has_nothing_to_bring_in(tmp_path: Path) -> None:
    bundle = encrypted_bundle()
    bundle["data"] = []
    path = write_legacy_database(tmp_path / "metalist.db", bundle)
    with pytest.raises(InputRejected, match="nothing to bring in"):
        any_legacy_item(path)


def test_the_export_and_the_file_hold_the_same_notes(tmp_path: Path) -> None:
    """The file is read into the bundle its Backup exports: one converter reads both."""
    exported = json.loads(json.dumps(encrypted_bundle()))
    from_file = read_legacy_database(write_legacy_database(tmp_path / "metalist.db", encrypted_bundle()))
    assert from_file["data"] == exported["data"]
    assert from_file["encryption"] == exported["encryption"]
