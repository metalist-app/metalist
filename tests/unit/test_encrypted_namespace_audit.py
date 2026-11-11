from __future__ import annotations

from contextlib import closing

import sqlite3
from pathlib import Path
import subprocess
import sys

import pytest

from app.db.blob_store import blob_store_for_database, resolve_file_catalog_path
from app.db.file_schema import initialize_file_schema as initialize_catalog_schema
from app.db.legacy_file_schema import initialize_file_schema
from app.db.move_files_to_blobs import move_files_to_blobs
from app.db.blob_store import resolve_legacy_file_database_path as resolve_file_database_path
from app.db.schema import LINK_ICONS_TABLE, initialize_schema
from app.encryption_audit import audit_all_namespaces, main
from app.services.encryption import EncryptionService


_NOW = "2026-08-01T00:00:00+00:00"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_importing_encryption_audit_does_not_initialize_runtime_config() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import app.encryption_audit; "
                "assert 'app.config' not in sys.modules"
            ),
        ],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _create_namespace_database(
    namespaces_directory: Path,
    *,
    namespace: str,
    encryption_enabled: bool,
) -> Path:
    namespace_directory = namespaces_directory / namespace
    namespace_directory.mkdir(parents=True)
    database_path = namespace_directory / f"{namespace}.metalist.db"
    connection = sqlite3.connect(database_path)
    initialize_schema(connection)
    connection.execute(
        """
        INSERT INTO app_settings (
            id,
            auth_verifier,
            auth_salt,
            auth_iterations,
            kek_salt,
            kek_iterations,
            vault_version,
            kdf_algorithm,
            kdf_memory_cost_kib,
            kdf_parallelism,
            encryption_enabled,
            encryption_algorithm,
            encrypted_dek,
            dek_nonce,
            dek_tag,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "verifier" if encryption_enabled else None,
            b"a" * 32 if encryption_enabled else None,
            3 if encryption_enabled else None,
            b"k" * 32 if encryption_enabled else None,
            3 if encryption_enabled else None,
            3 if encryption_enabled else None,
            "ARGON2ID" if encryption_enabled else None,
            65_536 if encryption_enabled else None,
            4 if encryption_enabled else None,
            int(encryption_enabled),
            "AES-256-GCM" if encryption_enabled else None,
            b"d" * 32 if encryption_enabled else None,
            b"n" * 12 if encryption_enabled else None,
            b"t" * 16 if encryption_enabled else None,
            _NOW,
            _NOW,
        ),
    )
    connection.commit()
    connection.close()
    return database_path


def _insert_encrypted_note(database_path: Path, *, note_id: str, nonce_byte: bytes) -> None:
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        INSERT INTO notes (
            id, content, tags, proposed_tags, is_collapsed,
            encryption_nonce, encryption_tag,
            tags_encryption_nonce, tags_encryption_tag,
            proposed_tags_encryption_nonce, proposed_tags_encryption_tag,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            note_id,
            "Y2lwaGVydGV4dA==",
            "dGFnLWNpcGhlcnRleHQ=",
            "cHJvcG9zZWQtY2lwaGVydGV4dA==",
            nonce_byte * 12,
            b"c" * 16,
            bytes([nonce_byte[0] + 1]) * 12,
            b"g" * 16,
            bytes([nonce_byte[0] + 2]) * 12,
            b"p" * 16,
            _NOW,
            _NOW,
        ),
    )
    connection.commit()
    connection.close()


@pytest.mark.parametrize("version", [0, 1, 2, 3, 4, 5, 6, 8])
def test_namespaces_without_retired_table_pass_read_only_audit(tmp_path: Path, version: int) -> None:
    database_path = _create_namespace_database(tmp_path, namespace="legacy", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version = {version}")
    before = database_path.read_bytes()
    report = audit_all_namespaces(namespaces_directory=tmp_path)
    assert report.startup_allowed, report.render_text()
    assert database_path.read_bytes() == before


def test_v7_namespace_missing_diagram_table_still_fails_audit(tmp_path: Path) -> None:
    database_path = _create_namespace_database(tmp_path, namespace="broken", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 7")
    report = audit_all_namespaces(namespaces_directory=tmp_path)
    assert not report.startup_allowed
    assert any(finding.table == "embedded_documents" and finding.message == "expected table is missing"
               for finding in report.findings)


@pytest.mark.parametrize("version", [6, 7, 8])
def test_retired_table_payloads_remain_subject_to_encryption_audit(tmp_path: Path, version: int) -> None:
    database_path = _create_namespace_database(tmp_path, namespace="plaintext", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version = {version}")
        connection.execute("CREATE TABLE embedded_documents (id TEXT PRIMARY KEY, payload TEXT NOT NULL, nonce BLOB, tag BLOB)")
        connection.execute("INSERT INTO embedded_documents(id, payload) VALUES (?, ?)", ("document-id", "private diagram"))
    report = audit_all_namespaces(namespaces_directory=tmp_path)
    assert not report.startup_allowed
    assert any(finding.table == "embedded_documents" and finding.field == "payload"
               and not finding.is_migration_deferred for finding in report.findings)
    assert "private diagram" not in report.render_text()
    if version == 8:
        assert any(finding.table == "embedded_documents" and "unknown table" in finding.message
                   for finding in report.findings)


def _replace_with_legacy_search_history(database_path: Path) -> None:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("DROP TABLE search_interaction_history")
        connection.execute(
            """
            CREATE TABLE search_interaction_history (
                query_hash TEXT PRIMARY KEY,
                query_key TEXT NOT NULL,
                query_key_encryption_nonce BLOB,
                query_key_encryption_tag BLOB,
                root_tag TEXT NOT NULL,
                root_tag_encryption_nonce BLOB,
                root_tag_encryption_tag BLOB,
                tags_json TEXT NOT NULL,
                tags_json_encryption_nonce BLOB,
                tags_json_encryption_tag BLOB,
                score REAL NOT NULL,
                created_at TEXT NOT NULL,
                last_interacted_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO search_interaction_history VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "deterministic-query-hash",
                "YQ==",
                b"1" * 12,
                b"a" * 16,
                "Yg==",
                b"2" * 12,
                b"b" * 16,
                "Yw==",
                b"3" * 12,
                b"c" * 16,
                1.0,
                _NOW,
                _NOW,
                _NOW,
            ),
        )
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    finally:
        connection.close()


def _downgrade_to_version_4_schema(database_path: Path) -> None:
    connection = sqlite3.connect(database_path)
    try:
        for column in (
            "openai_api_key_ciphertext",
            "openai_api_key_encryption_nonce",
            "openai_api_key_encryption_tag",
        ):
            connection.execute(f"ALTER TABLE app_settings DROP COLUMN {column}")
        connection.execute("PRAGMA user_version = 4")
        connection.commit()
    finally:
        connection.close()


def test_audit_allows_encrypted_version_4_namespace_before_migration(
    tmp_path: Path,
) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    _downgrade_to_version_4_schema(database_path)

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is True
    assert report.findings == ()


def test_audit_scans_all_namespaces_and_skips_plaintext_namespaces(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    encrypted_database = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    _insert_encrypted_note(encrypted_database, note_id="note-1", nonce_byte=b"1")
    _create_namespace_database(
        namespaces_directory,
        namespace="public",
        encryption_enabled=False,
    )

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.namespace_count == 2
    assert report.encrypted_namespace_count == 1
    assert report.checked_payload_count == 3
    assert report.findings == ()
    assert [result.namespace for result in report.results] == ["private", "public"]
    assert report.results[0].is_encrypted is True
    assert report.results[1].is_encrypted is False
    rendered = report.render_text()
    assert "- private: PASS" in rendered
    assert "- public: SKIPPED (not encrypted)" in rendered


def test_audit_reports_plaintext_without_disclosing_values(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        INSERT INTO notes (id, content, tags, is_collapsed, created_at, updated_at)
        VALUES ('note-secret', 'TOP SECRET NOTE', '@private', 0, ?, ?)
        """,
        (_NOW, _NOW),
    )
    connection.execute(
        "UPDATE app_settings SET command_palette_usage_json = ? WHERE id = 1",
        ('{"lastQueryTokens":["TOP SECRET SEARCH"]}',),
    )
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)
    rendered = report.render_text()

    assert len(report.findings) == 4
    assert "notes.content" in rendered
    assert "notes.tags" in rendered
    assert "app_settings.command_palette_usage_json" in rendered
    assert "- private: FAIL" in rendered
    assert "TOP SECRET" not in rendered
    assert "note-secret" not in rendered
    assert report.startup_allowed is False


def test_audit_requires_authenticated_migration_for_legacy_search_history_schema(
    tmp_path: Path,
) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    _replace_with_legacy_search_history(database_path)

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is True
    assert report.fatal_findings == ()
    assert len(report.migration_findings) == 1
    assert report.migration_findings[0].table == "search_interaction_history"
    assert "deterministic" in report.migration_findings[0].message


def test_startup_allows_only_known_password_dependent_migration_payloads(
    tmp_path: Path,
) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE app_settings SET client_preferences_json = ? WHERE id = 1",
        ('{"pref.theme":"dark"}',),
    )
    connection.execute("PRAGMA user_version = 0")
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.passed is False
    assert report.startup_allowed is True
    assert len(report.migration_findings) == 1
    assert report.fatal_findings == ()
    assert report.migration_findings[0].field == "client_preferences_json"


def test_current_database_plaintext_is_fatal_even_for_a_former_migration_field(
    tmp_path: Path,
) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE app_settings SET client_preferences_json = ? WHERE id = 1",
        ('{"pref.theme":"dark"}',),
    )
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is False
    assert len(report.fatal_findings) == 1
    assert report.migration_findings == ()


def test_incomplete_migration_field_encryption_metadata_is_fatal(
    tmp_path: Path,
) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        UPDATE app_settings
        SET client_preferences_json = ?,
            client_preferences_encryption_nonce = ?,
            client_preferences_encryption_tag = NULL
        WHERE id = 1
        """,
        ('{"pref.theme":"dark"}', b"n" * 12),
    )
    connection.execute("PRAGMA user_version = 0")
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is False
    assert len(report.fatal_findings) == 1
    assert "incomplete encryption metadata" in report.fatal_findings[0].message


def test_audit_checks_file_database_and_nonce_reuse_across_databases(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    _insert_encrypted_note(database_path, note_id="note-1", nonce_byte=b"1")
    file_database_path = resolve_file_database_path(database_path)
    connection = sqlite3.connect(file_database_path)
    initialize_file_schema(connection)
    connection.execute(
        """
        INSERT INTO files (
            id, title, title_encryption_nonce, title_encryption_tag,
            metadata_json, metadata_encryption_nonce, metadata_encryption_tag,
            blob_data, blob_encryption_nonce, blob_encryption_tag,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "file-1",
            "dGl0bGU=",
            b"1" * 12,
            b"a" * 16,
            "bWV0YWRhdGE=",
            b"3" * 12,
            b"b" * 16,
            b"encrypted-blob",
            b"4" * 12,
            b"c" * 16,
            _NOW,
            _NOW,
        ),
    )
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert any("AES-GCM nonce is reused" in finding.message for finding in report.findings)
    assert any(finding.field == "title" for finding in report.findings)


def test_audit_checks_binary_storage_type_without_reading_payloads(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    file_database_path = resolve_file_database_path(database_path)
    connection = sqlite3.connect(file_database_path)
    initialize_file_schema(connection)
    for index, blob_data in enumerate((b"encrypted-blob", b"", "stored-as-text")):
        connection.execute(
            """
            INSERT INTO files (
                id, title, title_encryption_nonce, title_encryption_tag,
                metadata_json, metadata_encryption_nonce, metadata_encryption_tag,
                blob_data, blob_encryption_nonce, blob_encryption_tag,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"file-{index}", "dGl0bGU=", bytes([index, 1]) * 6, b"a" * 16,
                "bWV0YWRhdGE=", bytes([index, 2]) * 6, b"b" * 16,
                blob_data, bytes([index, 3]) * 6, b"c" * 16,
                _NOW, _NOW,
            ),
        )
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    blob_findings = [finding for finding in report.findings if finding.field == "blob_data"]
    assert [finding.message for finding in blob_findings] == ["encrypted binary payload must be stored as a BLOB"]
    assert "stored-as-text" not in report.render_text()


def test_audit_fails_closed_for_unknown_tables_and_columns(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    connection = sqlite3.connect(database_path)
    connection.execute("ALTER TABLE notes ADD COLUMN future_payload TEXT")
    connection.execute("CREATE TABLE plugin_secrets (secret TEXT NOT NULL)")
    connection.execute("INSERT INTO plugin_secrets (secret) VALUES ('plaintext')")
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)
    messages = [finding.message for finding in report.findings]

    assert any("unknown table" in message for message in messages)
    assert any("unknown column" in message for message in messages)


def test_audit_reports_missing_contract_columns_without_crashing(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    replacement_path = database_path.with_suffix(".replacement")
    connection = sqlite3.connect(replacement_path)
    connection.execute(
        """
        CREATE TABLE app_settings (
            id INTEGER PRIMARY KEY,
            encryption_enabled INTEGER NOT NULL
        )
        """
    )
    connection.execute("INSERT INTO app_settings (id, encryption_enabled) VALUES (1, 1)")
    connection.commit()
    connection.close()
    replacement_path.replace(database_path)

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.namespace_count == 1
    assert any("expected column is missing" in finding.message for finding in report.findings)


def test_audit_reports_missing_namespace_directory_as_configuration_failure(tmp_path: Path) -> None:
    missing_directory = tmp_path / "not-created"

    report = audit_all_namespaces(namespaces_directory=missing_directory)

    assert report.namespace_count == 0
    assert len(report.findings) == 1
    assert "does not exist" in report.findings[0].message


def test_cli_returns_nonzero_and_does_not_print_plaintext(
    tmp_path: Path,
    capsys,
) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(
        namespaces_directory,
        namespace="private",
        encryption_enabled=True,
    )
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        INSERT INTO notes (id, content, tags, is_collapsed, created_at, updated_at)
        VALUES ('secret-id', 'SECRET BODY', '@secret', 0, ?, ?)
        """,
        (_NOW, _NOW),
    )
    connection.commit()
    connection.close()

    exit_code = main(["--namespaces-dir", str(namespaces_directory)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Encrypted namespace audit: FAIL" in output
    assert "SECRET BODY" not in output
    assert "secret-id" not in output


_LEGACY_FILES_TABLE = """
CREATE TABLE files (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    title_encryption_nonce BLOB,
    title_encryption_tag BLOB,
    metadata_json TEXT NOT NULL,
    metadata_encryption_nonce BLOB,
    metadata_encryption_tag BLOB,
    blob_data BLOB NOT NULL,
    blob_encryption_nonce BLOB,
    blob_encryption_tag BLOB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _insert_encrypted_file(connection: sqlite3.Connection, *, file_id: str, nonce_byte: int) -> None:
    connection.execute(
        """
        INSERT INTO files (
            id, title, title_encryption_nonce, title_encryption_tag,
            metadata_json, metadata_encryption_nonce, metadata_encryption_tag,
            blob_data, blob_encryption_nonce, blob_encryption_tag,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id, "dGl0bGU=", bytes([nonce_byte]) * 12, b"a" * 16,
            "bWV0YWRhdGE=", bytes([nonce_byte + 1]) * 12, b"b" * 16,
            b"encrypted-blob", bytes([nonce_byte + 2]) * 12, b"c" * 16,
            _NOW, _NOW,
        ),
    )


def _insert_preview(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    variant: str,
    preview_data: bytes,
    nonce: bytes | None,
    tag: bytes | None,
) -> None:
    connection.execute(
        """
        INSERT INTO file_previews (
            file_id, variant, mime_type, preview_data, preview_encryption_nonce,
            preview_encryption_tag, content_revision, updated_at
        ) VALUES (?, ?, 'image/svg+xml', ?, ?, ?, 1, ?)
        """,
        (file_id, variant, preview_data, nonce, tag, _NOW),
    )


def test_audit_accepts_files_databases_before_and_after_the_diagram_upgrade(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    legacy_path = _create_namespace_database(namespaces_directory, namespace="legacy", encryption_enabled=True)
    connection = sqlite3.connect(resolve_file_database_path(legacy_path))
    connection.execute(_LEGACY_FILES_TABLE)
    _insert_encrypted_file(connection, file_id="legacy-file", nonce_byte=20)
    connection.commit()
    connection.close()

    current_path = _create_namespace_database(namespaces_directory, namespace="current", encryption_enabled=True)
    connection = sqlite3.connect(resolve_file_database_path(current_path))
    initialize_file_schema(connection)
    _insert_encrypted_file(connection, file_id="current-file", nonce_byte=10)
    for variant, nonce_byte in (("light", b"L"), ("dark", b"D")):
        _insert_preview(
            connection, file_id="current-file", variant=variant,
            preview_data=b"encrypted-preview", nonce=nonce_byte * 12, tag=b"d" * 16,
        )
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.findings == ()
    assert report.startup_allowed is True
    assert report.checked_payload_count == 2 * 3 + 2  # three payloads per file, one per preview


def test_audit_reports_plaintext_diagram_previews_in_encrypted_namespaces(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    connection = sqlite3.connect(resolve_file_database_path(database_path))
    initialize_file_schema(connection)
    _insert_encrypted_file(connection, file_id="file-1", nonce_byte=10)
    _insert_preview(
        connection, file_id="file-1", variant="light",
        preview_data=b"<svg>secret diagram text</svg>", nonce=None, tag=None,
    )
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is False
    assert [(finding.table, finding.field) for finding in report.fatal_findings] == [("file_previews", "preview_data")]
    assert "secret diagram text" not in report.render_text()


@pytest.mark.parametrize(("version", "upgraded", "allowed"), [(9, False, True), (9, True, True), (10, True, True), (10, False, False)])
def test_version_10_requires_the_editable_files_schema(tmp_path: Path, version: int, upgraded: bool, allowed: bool) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version = {version}")
    connection = sqlite3.connect(resolve_file_database_path(database_path))
    if upgraded:
        initialize_file_schema(connection)
    else:
        connection.execute(_LEGACY_FILES_TABLE)
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is allowed, report.render_text()
    if not allowed:
        assert {(finding.table, finding.field) for finding in report.fatal_findings} == {
            ("file_previews", "*"),
            ("files", "content_revision"),
        }


_AI_PROVIDER_KEY_COLUMNS = (
    "anthropic_api_key_ciphertext", "anthropic_api_key_encryption_nonce", "anthropic_api_key_encryption_tag",
    "gemini_api_key_ciphertext", "gemini_api_key_encryption_nonce", "gemini_api_key_encryption_tag",
)


@pytest.mark.parametrize(("version", "has_slots", "allowed"), [(10, False, True), (10, True, True), (11, True, True), (11, False, False)])
def test_version_11_requires_the_claude_and_gemini_key_slots(tmp_path: Path, version: int, has_slots: bool, allowed: bool) -> None:
    # Before version 11 the slots may be absent, or already added by the on-open schema helper.
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        if not has_slots:
            for column in _AI_PROVIDER_KEY_COLUMNS:
                connection.execute(f"ALTER TABLE app_settings DROP COLUMN {column}")
        connection.execute(f"PRAGMA user_version = {version}")

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is allowed, report.render_text()
    if not allowed:
        assert {(finding.table, finding.field) for finding in report.fatal_findings} == {
            ("app_settings", column) for column in _AI_PROVIDER_KEY_COLUMNS
        }


def test_a_plaintext_claude_key_in_an_encrypted_namespace_is_reported(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE app_settings SET anthropic_api_key_ciphertext = 'sk-ant-secret-key-in-the-clear'")

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is False
    assert ("app_settings", "anthropic_api_key_ciphertext") in {
        (finding.table, finding.field) for finding in report.fatal_findings
    }
    assert "sk-ant-secret" not in report.render_text()


# Before version 12 the link_icons table may be absent, or already added by the on-open schema helper.
@pytest.mark.parametrize(("version", "has_table", "allowed"), [(11, False, True), (11, True, True), (12, True, True), (12, False, False)])
def test_version_12_requires_the_link_icons_table(tmp_path: Path, version: int, has_table: bool, allowed: bool) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        if not has_table:
            connection.execute(f"DROP TABLE {LINK_ICONS_TABLE}")
        connection.execute(f"PRAGMA user_version = {version}")

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is allowed, report.render_text()
    if not allowed:
        assert {(finding.table, finding.field) for finding in report.fatal_findings} == {(LINK_ICONS_TABLE, "*")}


@pytest.mark.parametrize("column", ["origin", "icon_png"])
def test_a_plaintext_icon_or_site_in_an_encrypted_namespace_is_reported(tmp_path: Path, column: str) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            f"INSERT INTO {LINK_ICONS_TABLE} (origin, origin_encryption_nonce, origin_encryption_tag, icon_png, "
            "icon_png_encryption_nonce, icon_png_encryption_tag, status, failure_count, last_checked_at, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, 'ok', 0, 'now', 'now', 'now')",
            (
                "https://secret.example.com" if column == "origin" else "b3JpZ2lu",
                None if column == "origin" else b"o" * 12,
                None if column == "origin" else b"p" * 16,
                "iVBORw0KGgo=" if column == "icon_png" else "aWNvbg==",
                None if column == "icon_png" else b"i" * 12,
                None if column == "icon_png" else b"j" * 16,
            ),
        )

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is False
    assert (LINK_ICONS_TABLE, column) in {(finding.table, finding.field) for finding in report.fatal_findings}
    assert "secret.example.com" not in report.render_text()


# Version 13 adds file_texts (a file's text and bloom filter, for search: docs/ready-to-build/
# folder-import-and-file-previews.md, "Searchable file text"). Before 13 the table may be missing
# or already added on open; from 13 it is required, and its two payloads are encrypted.
@pytest.mark.parametrize(("version", "has_table", "allowed"), [(12, False, True), (12, True, True), (13, True, True), (13, False, False)])
def test_version_13_requires_the_file_texts_table(tmp_path: Path, version: int, has_table: bool, allowed: bool) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version = {version}")
    connection = sqlite3.connect(resolve_file_database_path(database_path))
    initialize_file_schema(connection)
    if not has_table:
        connection.execute("DROP TABLE file_texts")
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is allowed, report.render_text()
    if not allowed:
        assert {(finding.table, finding.field) for finding in report.fatal_findings} == {("file_texts", "*")}


def _insert_file_text(connection: sqlite3.Connection, *, file_id: str, text: bytes, filter_data: bytes, nonce_byte: int | None) -> None:
    # Nonces must never repeat: the text's and the filter's differ.
    text_nonce, filter_nonce, tag = None, None, None
    if nonce_byte is not None:
        text_nonce, filter_nonce, tag = bytes([nonce_byte]) * 12, bytes([nonce_byte + 1]) * 12, b"t" * 16
    connection.execute(
        "INSERT INTO file_texts VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, 'now', 1, 1)",
        (file_id, text, text_nonce, tag, filter_data, filter_nonce, tag),
    )


def test_audit_accepts_encrypted_file_texts_and_reports_plaintext_ones(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    connection = sqlite3.connect(resolve_file_database_path(database_path))
    initialize_file_schema(connection)
    _insert_encrypted_file(connection, file_id="sealed", nonce_byte=10)
    _insert_encrypted_file(connection, file_id="open", nonce_byte=20)
    _insert_file_text(connection, file_id="sealed", text=b"ciphertext", filter_data=b"cipherfilter", nonce_byte=30)
    _insert_file_text(connection, file_id="open", text=b"rent is due on the first", filter_data=b"\x00\x04bits", nonce_byte=None)
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is False
    assert {(finding.table, finding.field) for finding in report.fatal_findings} == {
        ("file_texts", "text_data"), ("file_texts", "filter_data"),
    }
    assert "rent is due" not in report.render_text()


# Version 14 adds file_texts' reader and filter versions (docs/ready-to-build/folder-import-and-
# file-previews.md, "Text versions"). Before 14 they may be missing or already added on open; from
# 14 they are required.
@pytest.mark.parametrize(("version", "has_additions", "allowed"), [(13, False, True), (13, True, True), (14, True, True), (14, False, False)])
def test_version_14_requires_text_versions(tmp_path: Path, version: int, has_additions: bool, allowed: bool) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version = {version}")
    connection = sqlite3.connect(resolve_file_database_path(database_path))
    initialize_file_schema(connection)
    if not has_additions:
        connection.execute("ALTER TABLE file_texts DROP COLUMN reader_version")
        connection.execute("ALTER TABLE file_texts DROP COLUMN filter_version")
    connection.commit()
    connection.close()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is allowed, report.render_text()
    if not allowed:
        assert {(finding.table, finding.field) for finding in report.fatal_findings} == {
            ("file_texts", "reader_version"), ("file_texts", "filter_version"),
        }


_PROVIDER_RATE_LIMIT_COLUMNS = (
    "provider_rate_limits_json", "provider_rate_limits_encryption_nonce", "provider_rate_limits_encryption_tag",
)


# Before version 15 the saved rate limits may be absent, or already added by the on-open schema helper.
@pytest.mark.parametrize(("version", "has_columns", "allowed"), [(14, False, True), (14, True, True), (15, True, True), (15, False, False)])
def test_version_15_requires_the_saved_rate_limits(tmp_path: Path, version: int, has_columns: bool, allowed: bool) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        if not has_columns:
            for column in _PROVIDER_RATE_LIMIT_COLUMNS:
                connection.execute(f"ALTER TABLE app_settings DROP COLUMN {column}")
        connection.execute(f"PRAGMA user_version = {version}")

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is allowed, report.render_text()
    if not allowed:
        assert {(finding.table, finding.field) for finding in report.fatal_findings} == {
            ("app_settings", column) for column in _PROVIDER_RATE_LIMIT_COLUMNS
        }


_MODEL_TIMING_COLUMNS = (
    "model_timings_json", "model_timings_encryption_nonce", "model_timings_encryption_tag",
)


# Before version 16 the saved timings may be absent, or already added by the on-open schema helper.
@pytest.mark.parametrize(("version", "has_columns", "allowed"), [(15, False, True), (15, True, True), (16, True, True), (16, False, False)])
def test_version_16_requires_the_saved_model_timings(tmp_path: Path, version: int, has_columns: bool, allowed: bool) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        if not has_columns:
            for column in _MODEL_TIMING_COLUMNS:
                connection.execute(f"ALTER TABLE app_settings DROP COLUMN {column}")
        connection.execute(f"PRAGMA user_version = {version}")

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is allowed, report.render_text()
    if not allowed:
        assert {(finding.table, finding.field) for finding in report.fatal_findings} == {
            ("app_settings", column) for column in _MODEL_TIMING_COLUMNS
        }


def test_plaintext_saved_model_timings_in_an_encrypted_namespace_are_reported(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE app_settings SET model_timings_json = "
            "'[{\"baseUrl\": \"https://api.openai.com/v1\", \"model\": \"gpt-5.6-sol\"}]'"
        )

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is False
    assert ("app_settings", "model_timings_json") in {
        (finding.table, finding.field) for finding in report.fatal_findings
    }


def test_plaintext_saved_rate_limits_in_an_encrypted_namespace_are_reported(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE app_settings SET provider_rate_limits_json = "
            "'[{\"baseUrl\": \"https://api.openai.com/v1\", \"model\": \"gpt-5.6-sol\"}]'"
        )

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.startup_allowed is False
    assert ("app_settings", "provider_rate_limits_json") in {
        (finding.table, finding.field) for finding in report.fatal_findings
    }


def _vault_with_moved_files(namespaces_directory: Path) -> Path:
    """An encrypted vault whose file really went through migration 16→17."""
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    service = EncryptionService()
    service.dek = bytes(range(32))
    # closing(): a connection's own `with` commits but leaves the file open, and Windows can't
    # delete an open file (the migration deletes this one).
    with closing(sqlite3.connect(resolve_file_database_path(database_path))) as connection:
        initialize_file_schema(connection)
        title = service.encrypt_for_storage("report.pdf")
        metadata = service.encrypt_for_storage("{}")
        content = service.encrypt_bytes_for_storage(b"secret content")
        connection.execute(
            "INSERT INTO files (id, title, title_encryption_nonce, title_encryption_tag, metadata_json, metadata_encryption_nonce, "
            "metadata_encryption_tag, blob_data, blob_encryption_nonce, blob_encryption_tag, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("report", *title, *metadata, *content, _NOW, _NOW),
        )
        connection.commit()
    with closing(sqlite3.connect(database_path)) as connection:
        move_files_to_blobs(connection=connection, encryption_enabled=True, encryption_service=service)
        connection.execute("PRAGMA user_version = 17")
        connection.commit()
    return database_path


def _catalog_blob_path(database_path: Path) -> Path:
    with sqlite3.connect(resolve_file_catalog_path(database_path)) as connection:
        blob_id = connection.execute("SELECT blob_id FROM files").fetchone()[0]
    return blob_store_for_database(database_path).path_of(blob_id)


def test_audit_accepts_a_vault_before_and_after_its_files_moved(tmp_path: Path) -> None:
    before = tmp_path / "before"
    database_path = _create_namespace_database(before, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 16")
    with sqlite3.connect(resolve_file_database_path(database_path)) as connection:
        initialize_file_schema(connection)
    assert audit_all_namespaces(namespaces_directory=before).fatal_findings == ()

    after = tmp_path / "after"
    _vault_with_moved_files(after)
    report = audit_all_namespaces(namespaces_directory=after)
    assert report.fatal_findings == (), report.render_text()
    assert report.startup_allowed is True


def test_audit_ignores_the_empty_catalog_of_a_vault_not_yet_unlocked(tmp_path: Path) -> None:
    """Opening the vault creates the catalog; its files stay in the old database until unlock."""
    namespaces_directory = tmp_path / "namespaces"
    database_path = _create_namespace_database(namespaces_directory, namespace="private", encryption_enabled=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 16")
    with sqlite3.connect(resolve_file_database_path(database_path)) as connection:
        initialize_file_schema(connection)
    catalog_path = resolve_file_catalog_path(database_path)
    catalog_path.parent.mkdir()
    with sqlite3.connect(catalog_path) as connection:
        initialize_catalog_schema(connection)

    assert audit_all_namespaces(namespaces_directory=namespaces_directory).fatal_findings == ()


def test_audit_requires_the_catalog_schema_from_version_17(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _vault_with_moved_files(namespaces_directory)
    with sqlite3.connect(resolve_file_catalog_path(database_path)) as connection:
        connection.execute("ALTER TABLE files ADD COLUMN surprise TEXT")

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert ("files", "surprise") in {(finding.table, finding.field) for finding in report.fatal_findings}


def _set_version(database_path: Path, version: int) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version = {version}")


def _drop_first_pages(database_path: Path) -> None:
    with sqlite3.connect(resolve_file_catalog_path(database_path)) as connection:
        connection.execute("DROP TABLE file_first_pages")


@pytest.mark.parametrize("has_first_pages", [False, True], ids=["before-open", "added-on-open"])
def test_audit_accepts_a_version_17_catalog_with_or_without_first_pages(tmp_path: Path, has_first_pages: bool) -> None:
    """Migration 17→18 adds file_first_pages; opening the catalog may have added it already."""
    namespaces_directory = tmp_path / "namespaces"
    database_path = _vault_with_moved_files(namespaces_directory)
    if not has_first_pages:
        _drop_first_pages(database_path)

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert report.fatal_findings == (), report.render_text()


def test_audit_accepts_version_18_with_first_pages_and_requires_them(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _vault_with_moved_files(namespaces_directory)
    _set_version(database_path, 18)
    assert audit_all_namespaces(namespaces_directory=namespaces_directory).fatal_findings == ()

    _drop_first_pages(database_path)
    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert "file_first_pages" in {finding.table for finding in report.fatal_findings}, report.render_text()


def test_audit_reports_a_seal_stored_in_plaintext(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _vault_with_moved_files(namespaces_directory)
    with sqlite3.connect(resolve_file_catalog_path(database_path)) as connection:
        connection.execute("UPDATE files SET blob_seal = ?, blob_seal_encryption_nonce = NULL, blob_seal_encryption_tag = NULL", (b'{"key":"secret"}',))

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert ("files", "blob_seal") in {(finding.table, finding.field) for finding in report.fatal_findings}
    assert "secret" not in report.render_text()


def test_audit_reports_a_missing_blob(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _vault_with_moved_files(namespaces_directory)
    _catalog_blob_path(database_path).unlink()

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert [finding.message for finding in report.fatal_findings] == ["names a blob that is missing"]


def test_audit_reports_a_blob_that_is_not_encrypted(tmp_path: Path) -> None:
    namespaces_directory = tmp_path / "namespaces"
    database_path = _vault_with_moved_files(namespaces_directory)
    _catalog_blob_path(database_path).write_bytes(b"plain secret content")

    report = audit_all_namespaces(namespaces_directory=namespaces_directory)

    assert [finding.message for finding in report.fatal_findings] == ["names a blob that is not encrypted"]
    assert "plain secret content" not in report.render_text()
