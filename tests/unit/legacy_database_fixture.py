"""An old MetaList's own file (MetaList_old/app.js): an `items` table of one JSON row per
top-level note, and a `config` table whose `bundle` row holds the rest of its Backup's bundle.
The rows are written last item first, as nothing in the file orders them: `prev` and `next` do."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "legacy-export"
ENCRYPTED_BUNDLE_PATH = FIXTURE_DIRECTORY / "encrypted.json"
# The password the fixture was encrypted with (make-encrypted-fixture.mjs).
ENCRYPTED_BUNDLE_PASSWORD = "velvet-orbit-canyon-pickle"
SECRET_TEXT = "hunter2 — pässwörd ✓"
LEGACY_IV_BYTES = 12


def encrypted_bundle() -> dict[str, Any]:
    return json.loads(ENCRYPTED_BUNDLE_PATH.read_text(encoding="utf-8"))


def plain_bundle() -> dict[str, Any]:
    return {
        "data_schema_version": 23,
        "encryption": {"encrypted": False},
        "data": [
            {"id": 7, "prev": None, "next": 8, "creation": 1_700_000_000_000, "last_edit": 1_700_000_001_000,
             "subitems": [{"indent": 0, "data": "Plain first", "tags": "", "collapse": False}]},
            {"id": 8, "prev": 7, "next": None, "creation": 1_700_000_002_000, "last_edit": 1_700_000_003_000,
             "subitems": [{"indent": 0, "data": "Plain second", "tags": "", "collapse": False}]},
        ],
    }


def write_legacy_database(path: Path, bundle: dict[str, Any]) -> Path:
    settings = {key: value for key, value in bundle.items() if key != "data"}
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE items (key INTEGER PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID")
        connection.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID")
        for item in reversed(bundle["data"]):
            connection.execute("INSERT INTO items (key, value) VALUES (?, ?)", (item["id"], json.dumps(item)))
        connection.execute("INSERT INTO config (key, value) VALUES ('bundle', ?)", (json.dumps(settings),))
        connection.commit()
    return path


def encrypted_with(bundle: dict[str, Any], password: str) -> dict[str, Any]:
    """bundle encrypted as the old MetaList does it (crypto.js): the same scheme as the fixture
    its own code wrote, for passwords the fixture doesn't have (a weak one)."""
    key = AESGCM(hashlib.sha256(password.encode("utf-8")).digest())
    data = []
    for item in bundle["data"]:
        iv = os.urandom(LEGACY_IV_BYTES)
        encrypted_item = {name: value for name, value in item.items() if name != "subitems"}
        encrypted_item["iv"] = {str(index): byte for index, byte in enumerate(iv)}
        encrypted_item["subitems_enc"] = key.encrypt(iv, json.dumps(item["subitems"]).encode("utf-8"), None).hex()
        data.append(encrypted_item)
    encryption = {"encrypted": True, "encryption_scheme_version": 1, "digest": "SHA-256", "alg": "AES-GCM"}
    return {"data_schema_version": bundle["data_schema_version"], "encryption": encryption, "data": data}
