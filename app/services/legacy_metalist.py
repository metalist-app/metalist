"""The old MetaList's notes (the maintainer, 2026-11-04: friend Joe moves over; docs/ui/legacy-import.md).

The old MetaList (MetaList_old, a Node app) kept every top-level note as a row of an SQLite file,
`~/MetaList/metalist.db`: in MetaList's own data folder, so a new MetaList finds it. Each row is
one item, its children in `subitems`; `prev` and `next` chain the items in order. A password
protected the subitems only: AES-GCM keyed by one SHA-256 of the password, each item with its
own 12-byte IV (MetaList_old/js/utils/crypto.js, persist.js). The old file is only ever read,
never changed, like a backup.

convert-from-legacy.py does the conversion; MetaList finds the file, checks a password and runs
the converter (legacy_metalist_conversion.py)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services.exception_capture import CapturedExceptionContext
from app.services.input_errors import InputRejected

LEGACY_DATABASE_FILENAME = "metalist.db"
# The only scheme the old MetaList wrote (persist.js ENCRYPTION_SCHEME_VERSION, crypto.js).
LEGACY_ENCRYPTION_SCHEME = {"encryption_scheme_version": 1, "digest": "SHA-256", "alg": "AES-GCM"}
# The data version of the old MetaList's last release (MetaList_old/js/model/schema.js): it
# updates its notes to it when it opens them, so an older one has not been opened since.
LEGACY_DATA_SCHEMA_VERSION = 23
_LEGACY_IV_BYTES = 12
_BYTE_VALUE_COUNT = 256
_BUNDLE_KEY = "bundle"
# The first item has no previous one (MetaList_old/js/model/model.js getSortedItems).
_FIRST_ITEM_PREV = None


@dataclass(frozen=True)
class LegacyDatabase:
    path: Path
    encrypted: bool


def legacy_database_path(data_directory: Path) -> Path:
    return data_directory / LEGACY_DATABASE_FILENAME


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _read_bundle(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute("SELECT value FROM config WHERE key = ?", (_BUNDLE_KEY,)).fetchone()
    if row is None:
        raise InputRejected("The old MetaList's file has no settings row: it is not one MetaList wrote.")
    bundle = json.loads(row[0])
    if not isinstance(bundle, dict) or "encryption" not in bundle or not isinstance(bundle["encryption"], dict):
        raise InputRejected("The old MetaList's settings are not in the form MetaList wrote.")
    return bundle


def _is_legacy_database(connection: sqlite3.Connection) -> bool:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"items", "config"} <= tables:
        return False
    return connection.execute("SELECT 1 FROM config WHERE key = ?", (_BUNDLE_KEY,)).fetchone() is not None


def _holds_legacy_notes(path: Path) -> bool:
    with closing(_connect_read_only(path)) as connection:
        return _is_legacy_database(connection)


def find_legacy_database(data_directory: Path) -> LegacyDatabase | None:
    """The old MetaList's file in this data folder, or None when there is none (or the file
    there is some other SQLite file, or no SQLite file at all)."""
    path = legacy_database_path(data_directory)
    if not path.is_file():
        return None
    not_a_database_capture = CapturedExceptionContext(
        sqlite3.DatabaseError, boundary="app/services/legacy_metalist.py:find_legacy_database:not_a_database_capture"
    )
    is_legacy = False
    with not_a_database_capture:
        is_legacy = _holds_legacy_notes(path)
    if not_a_database_capture.captured_exception is not None or not is_legacy:
        return None
    with closing(_connect_read_only(path)) as connection:
        encryption = _read_bundle(connection)["encryption"]
    if "encrypted" not in encryption or not isinstance(encryption["encrypted"], bool):
        raise InputRejected("The old MetaList's settings do not say whether its notes are encrypted.")
    return LegacyDatabase(path=path, encrypted=encryption["encrypted"])


def _items_in_order(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The items as the old MetaList showed them: from the one with no previous item, along `next`."""
    by_prev: dict[Any, dict[str, Any]] = {}
    for item in items:
        if "prev" not in item or "id" not in item:
            raise InputRejected("An old MetaList note has no place in the list (no id or prev).")
        if item["prev"] in by_prev:
            raise InputRejected(f"Two old MetaList notes follow the same note ({item['prev']!r}).")
        by_prev[item["prev"]] = item
    ordered: list[dict[str, Any]] = []
    previous_id = _FIRST_ITEM_PREV
    while previous_id in by_prev:
        ordered.append(by_prev[previous_id])
        previous_id = by_prev[previous_id]["id"]
    if len(ordered) != len(items):
        raise InputRejected(
            f"The old MetaList's notes are not one list: {len(ordered)} of {len(items)} follow each other."
        )
    return ordered


def read_legacy_database(path: Path) -> dict[str, Any]:
    """The old MetaList's notes as its Backup exported them: {data_schema_version, encryption,
    data}, the items in order and, when protected, still encrypted. The file is only read."""
    with closing(_connect_read_only(path)) as connection:
        if not _is_legacy_database(connection):
            raise InputRejected(f"{path} is not a file the old MetaList wrote.")
        bundle = _read_bundle(connection)
        rows = connection.execute("SELECT value FROM items").fetchall()
    if "data_schema_version" not in bundle or bundle["data_schema_version"] != LEGACY_DATA_SCHEMA_VERSION:
        raise InputRejected(
            "The old MetaList's notes are from an older version of it. "
            "Open them once in the old MetaList, then try again."
        )
    items = [json.loads(row[0]) for row in rows]
    if not all(isinstance(item, dict) for item in items):
        raise InputRejected("An old MetaList note is not in the form MetaList wrote.")
    payload = {
        "data_schema_version": bundle["data_schema_version"],
        "encryption": bundle["encryption"],
        "data": _items_in_order(items),
    }
    return payload


def any_legacy_item(path: Path) -> dict[str, Any]:
    """One of the old MetaList's notes, still encrypted: every one has the same key, so one tells
    whether a password opens them all, without reading them all."""
    with closing(_connect_read_only(path)) as connection:
        if not _is_legacy_database(connection):
            raise InputRejected(f"{path} is not a file the old MetaList wrote.")
        row = connection.execute("SELECT value FROM items LIMIT 1").fetchone()
    if row is None:
        raise InputRejected("The old MetaList holds no notes: there is nothing to bring in.")
    item = json.loads(row[0])
    if not isinstance(item, dict):
        raise InputRejected("An old MetaList note is not in the form MetaList wrote.")
    return item


def require_legacy_encryption_scheme(encryption: dict[str, Any]) -> None:
    for field, expected in LEGACY_ENCRYPTION_SCHEME.items():
        if field not in encryption:
            raise KeyError(f"Missing required field: encryption.{field}")
        if encryption[field] != expected:
            raise ValueError(
                f"Legacy export has encryption.{field} = {encryption[field]!r}; "
                f"this converter reads only {expected!r}"
            )


def _legacy_key(password: str) -> AESGCM:
    return AESGCM(hashlib.sha256(password.encode("utf-8")).digest())


def _legacy_iv(item: dict[str, Any]) -> bytes:
    # JSON.stringify wrote the Uint8Array as {"0": byte, ..., "11": byte}.
    raw_iv = item["iv"]
    expected_keys = [str(index) for index in range(_LEGACY_IV_BYTES)]
    if not isinstance(raw_iv, dict) or sorted(raw_iv, key=int) != expected_keys:
        raise ValueError(f"Legacy item id={item['id']} has an IV that is not {_LEGACY_IV_BYTES} bytes")
    iv_bytes = [raw_iv[key] for key in expected_keys]
    if not all(isinstance(value, int) and value in range(_BYTE_VALUE_COUNT) for value in iv_bytes):
        raise ValueError(f"Legacy item id={item['id']} has an IV that is not bytes")
    return bytes(iv_bytes)


def _decrypted_subitems(item: dict[str, Any], key: AESGCM) -> list[Any]:
    """Raises InvalidTag when the key does not open the item."""
    ciphertext_hex = item["subitems_enc"]
    if not isinstance(ciphertext_hex, str):
        raise TypeError(f"Legacy item id={item['id']} has subitems_enc that is not text")
    subitems = json.loads(key.decrypt(_legacy_iv(item), bytes.fromhex(ciphertext_hex), None).decode("utf-8"))
    if not isinstance(subitems, list):
        raise TypeError(f"Legacy item id={item['id']} decrypted to {type(subitems).__name__}, not a list")
    return subitems


def legacy_password_opens(items: list[dict[str, Any]], password: str) -> bool:
    """Every item is encrypted with the same key, so the first one tells."""
    if len(items) == 0:
        raise InputRejected("The old MetaList holds no notes: there is nothing to bring in.")
    wrong_password_capture = CapturedExceptionContext(
        InvalidTag, boundary="app/services/legacy_metalist.py:legacy_password_opens:wrong_password_capture"
    )
    key = _legacy_key(password)
    with wrong_password_capture:
        _decrypted_subitems(items[0], key)
    return wrong_password_capture.captured_exception is None


def decrypted_legacy_items(items: list[dict[str, Any]], password: str) -> list[dict[str, Any]]:
    key = _legacy_key(password)
    decrypted_items = []
    for item in items:
        if not isinstance(item, dict):
            raise TypeError("Each entry in data must be an object.")
        corruption_capture = CapturedExceptionContext(
            InvalidTag, boundary="app/services/legacy_metalist.py:decrypted_legacy_items:corruption_capture"
        )
        with corruption_capture:
            subitems = _decrypted_subitems(item, key)
        if corruption_capture.captured_exception is not None:
            raise ValueError(
                f"Legacy item id={item['id']} does not open with the password that opened the first item: "
                "the export is damaged"
            ) from corruption_capture.captured_exception
        decrypted_item = {name: value for name, value in item.items() if name not in {"iv", "subitems_enc"}}
        decrypted_item["subitems"] = subitems
        decrypted_items.append(decrypted_item)
    if len(decrypted_items) != len(items):
        raise AssertionError("every legacy item is decrypted")
    return decrypted_items
