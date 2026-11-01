"""Back Up Now's settings, kept per vault in its own database (docs/ui/command-palette.md,
`Back Up Now…`): the backup folder, how many backups to keep, and the vaults left out.

The vaults left out are kept, not the ones checked, so a vault created since the last
backup starts checked; the vault in use is never left out (agreed 2026-10-28). Settings
saved before that kept the checked vaults: each database converts them once after
unlock (convert_backup_settings_to_unchecked), recorded in namespace_content_migrations,
so a restored older backup is converted again."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3

from app.config import ACTIVE_NAMESPACE
from app.db.backup_settings_sql import fetch_backup_settings_row, upsert_backup_settings_row
from app.db.content_migrations_sql import is_content_migration_complete, record_content_migration_complete
from app.db.raw_connection import raw_sqlite_connection
from app.db.session import begin_writer
from app.models.database import SafeSession
from app.security.encryption import get_encryption_service
from app.security.encryption import get_encryption_service_with_token
from app.security.encryption import is_encryption_required
from app.server_runtime import resolve_namespaced_database_path
from app.server_runtime import resolve_namespaces_directory
from app.server_runtime import validate_namespace


_DEFAULT_RETENTION_COUNT = 30
_DEFAULT_NAMESPACE = "default"
BACKUP_SETTINGS_UNCHECKED_PREFIX = "backup-settings-unchecked:"
# ".2" also adds the synced-folder warnings already answered (an empty list).
BACKUP_SETTINGS_UNCHECKED_MIGRATION_ID = BACKUP_SETTINGS_UNCHECKED_PREFIX + "2026-10-29.2"
# The settings as saved before 2026-10-29: the vaults checked.
_SAVED_CHECKED_KEY = "selected_namespaces"


def _default_backup_settings() -> dict[str, object]:
    return {
        "retention_count": _DEFAULT_RETENTION_COUNT,
        "folder_path": "",
        "unchecked_namespaces": [],
        "synced_plaintext_acknowledged": [],
    }


def order_namespaces(*, namespaces: list[str]) -> list[str]:
    """The vaults named, each once, sorted with `default` first."""
    if not isinstance(namespaces, list):
        raise TypeError("namespaces must be a list")
    normalized_namespaces: list[str] = []
    seen_namespaces: set[str] = set()
    for namespace in namespaces:
        if not isinstance(namespace, str):
            raise TypeError("namespaces entries must be strings")
        normalized_namespace = validate_namespace(namespace=namespace)
        if normalized_namespace in seen_namespaces:
            continue
        seen_namespaces.add(normalized_namespace)
        normalized_namespaces.append(normalized_namespace)
    normalized_namespaces.sort()
    if _DEFAULT_NAMESPACE in normalized_namespaces:
        normalized_namespaces.remove(_DEFAULT_NAMESPACE)
        normalized_namespaces.insert(0, _DEFAULT_NAMESPACE)
    return normalized_namespaces


def list_available_namespaces() -> list[str]:
    """The vaults on this computer: those whose database exists."""
    discovered_namespaces: list[str] = []
    namespaces_directory = resolve_namespaces_directory()
    if namespaces_directory.exists():
        if not namespaces_directory.is_dir():
            raise RuntimeError(f"namespaces directory is not a directory: {namespaces_directory}")
        for child in namespaces_directory.iterdir():
            if not child.is_dir():
                continue
            namespace = validate_namespace(namespace=child.name)
            database_path = resolve_namespaced_database_path(namespace=namespace)
            if database_path.is_file():
                discovered_namespaces.append(namespace)
    return order_namespaces(namespaces=discovered_namespaces)


def _serialize_settings_payload(settings: dict[str, object]) -> str:
    validated = _validate_backup_settings(settings)
    return json.dumps(validated, separators=(",", ":"), sort_keys=True)


def _deserialize_settings_payload(payload_json: str) -> dict[str, object]:
    if not isinstance(payload_json, str) or payload_json == "":
        raise RuntimeError("backup settings payload must be a non-empty string")
    parsed = json.loads(payload_json)
    if not isinstance(parsed, dict):
        raise RuntimeError("backup settings payload must be an object")
    return _validate_backup_settings(parsed)


def _validate_backup_settings(settings: dict[str, object]) -> dict[str, object]:
    if "retention_count" not in settings:
        raise RuntimeError("backup settings missing retention_count")
    retention_count = settings["retention_count"]
    if not isinstance(retention_count, int) or retention_count <= 0:
        raise RuntimeError("backup settings retention_count must be a positive integer")

    folder_path = ""
    if "folder_path" in settings:
        folder_path = settings["folder_path"]
        if not isinstance(folder_path, str):
            raise RuntimeError("backup settings folder_path must be a string")

    if "unchecked_namespaces" not in settings:
        raise RuntimeError("backup settings missing unchecked_namespaces")
    unchecked_namespaces = _validated_namespaces(settings["unchecked_namespaces"], field="unchecked_namespaces")
    if ACTIVE_NAMESPACE in unchecked_namespaces:
        raise RuntimeError("backup settings must not leave out the vault in use")

    if "synced_plaintext_acknowledged" not in settings:
        raise RuntimeError("backup settings missing synced_plaintext_acknowledged")
    acknowledged = _validated_acknowledgments(settings["synced_plaintext_acknowledged"])

    return {
        "retention_count": retention_count,
        "folder_path": folder_path,
        "unchecked_namespaces": unchecked_namespaces,
        "synced_plaintext_acknowledged": acknowledged,
    }


# Vaults without a password the person chose to back up into a synced folder anyway: asked
# once per folder and vault (docs/ui/command-palette.md, `Back Up Now…`).
def _validated_acknowledgments(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        raise RuntimeError("backup settings synced_plaintext_acknowledged must be a list")
    acknowledged: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != {"namespace", "folder_path"}:
            raise RuntimeError("each synced_plaintext_acknowledged entry is a namespace and a folder_path")
        if not isinstance(entry["namespace"], str) or not isinstance(entry["folder_path"], str):
            raise RuntimeError("synced_plaintext_acknowledged entries hold strings")
        acknowledged.append({"namespace": validate_namespace(namespace=entry["namespace"]), "folder_path": entry["folder_path"]})
    return acknowledged


def _validated_namespaces(raw_namespaces: object, *, field: str) -> list[str]:
    if not isinstance(raw_namespaces, list):
        raise RuntimeError(f"backup settings {field} must be a list")
    namespaces: list[str] = []
    for raw_namespace in raw_namespaces:
        if not isinstance(raw_namespace, str):
            raise RuntimeError(f"backup settings {field} entries must be strings")
        normalized_namespace = validate_namespace(namespace=raw_namespace)
        if normalized_namespace in namespaces:
            raise RuntimeError(f"backup settings {field} duplicate: {normalized_namespace}")
        namespaces.append(normalized_namespace)
    return namespaces


def _resolve_encryption_service(*, token: str):
    if token:
        return get_encryption_service_with_token(token)
    return get_encryption_service()


# The stored settings' JSON, decrypted, or None when none are stored.
def _stored_payload_json(row: dict[str, object], *, token: str) -> str | None:
    stored_json = row["backup_settings_json"]
    if stored_json is None:
        return None
    if not isinstance(stored_json, str):
        raise RuntimeError("backup_settings_json must be a string")

    nonce = row["backup_settings_encryption_nonce"]
    tag = row["backup_settings_encryption_tag"]
    if (nonce is None) != (tag is None):
        raise RuntimeError(
            "backup settings row has incomplete encryption metadata: "
            f"nonce={nonce is not None} tag={tag is not None}"
        )

    if nonce is None:
        return stored_json

    service = _resolve_encryption_service(token=token)
    if service is None:
        raise RuntimeError("backup settings decryption requires an active DEK")
    plaintext = service.decrypt_from_storage(stored_json, nonce, tag)
    if not isinstance(plaintext, str):
        raise TypeError("decrypted backup settings payload must be a string")
    return plaintext


def load_backup_settings(*, token: str) -> dict[str, object]:
    if not isinstance(token, str):
        raise TypeError("token must be a string")
    session = SafeSession()
    try:
        with SafeSession.allow_reads("backup_settings:load"):
            row = fetch_backup_settings_row(session.connection())
        if row is None:
            raise RuntimeError("app_settings row missing while loading backup settings")
        payload_json = _stored_payload_json(row, token=token)
        if payload_json is None:
            return _default_backup_settings()
        return _deserialize_settings_payload(payload_json)
    finally:
        session.close()


def save_backup_settings(*, token: str, settings: dict[str, object]) -> dict[str, object]:
    if not isinstance(token, str):
        raise TypeError("token must be a string")
    normalized_settings = _validate_backup_settings(settings)
    with begin_writer() as connection:
        _store_settings(raw_sqlite_connection(connection), normalized_settings, token=token)
    return normalized_settings


def _store_settings(connection: sqlite3.Connection, settings: dict[str, object], *, token: str) -> None:
    plaintext_json = _serialize_settings_payload(settings)
    stored_json = plaintext_json
    nonce: bytes | None = None
    tag: bytes | None = None

    service = _resolve_encryption_service(token=token)
    if service is not None:
        stored_json, nonce, tag = service.encrypt_for_storage(plaintext_json)
    elif is_encryption_required():
        raise RuntimeError("backup settings persistence requires an active DEK")

    upsert_backup_settings_row(
        connection,
        backup_settings_json=stored_json,
        backup_settings_encryption_nonce=nonce,
        backup_settings_encryption_tag=tag,
        updated_at=datetime.now(timezone.utc),
    )


# The vaults that settings saved with the vaults checked leave out.
def _left_out_by(stored: dict[str, object], *, available_namespaces: list[str]) -> list[str]:
    if _SAVED_CHECKED_KEY not in stored:
        return []
    checked = _validated_namespaces(stored[_SAVED_CHECKED_KEY], field=_SAVED_CHECKED_KEY)
    return [namespace for namespace in available_namespaces if namespace not in checked and namespace != ACTIVE_NAMESPACE]


def convert_backup_settings_to_unchecked(*, available_namespaces: list[str]) -> None:
    """Converts settings saved with the vaults checked to the vaults left out, once per
    database, after unlock (content_cache.populate_cache_from_db asks whether this
    database still needs it). A vault available now and not checked then is left out; the
    vault in use never is. Settings from before vaults could be chosen leave none out."""
    if not isinstance(available_namespaces, list):
        raise TypeError("available_namespaces must be a list")
    with begin_writer() as writer:
        connection = raw_sqlite_connection(writer)
        converted_count = _convert_stored_settings(connection, available_namespaces=available_namespaces)
        record_content_migration_complete(
            connection, migration_id=BACKUP_SETTINGS_UNCHECKED_MIGRATION_ID,
            converted_count=converted_count, superseded_prefix=BACKUP_SETTINGS_UNCHECKED_PREFIX,
        )


def backup_settings_need_conversion(connection: sqlite3.Connection) -> bool:
    """Whether this database's backup settings are converted at this unlock: never yet, or
    saved in the old form again since by an older MetaList opened on the vault (2026-11-01:
    the conversion was recorded, the settings were old again, and every login failed)."""
    if not is_content_migration_complete(connection, BACKUP_SETTINGS_UNCHECKED_MIGRATION_ID):
        return True
    row = fetch_backup_settings_row(connection)
    if row is None:
        return False
    payload_json = _stored_payload_json(row, token="")
    if payload_json is None:
        return False
    stored = json.loads(payload_json)
    if not isinstance(stored, dict):
        raise RuntimeError("backup settings payload must be an object")
    return not _is_current_form(stored)


# Settings saved since 2026-10-29 name the vaults left out and the synced-folder warnings answered.
def _is_current_form(stored: dict[str, object]) -> bool:
    return "unchecked_namespaces" in stored and "synced_plaintext_acknowledged" in stored


# Stores the settings as the vaults left out; how many settings that converted (0 or 1).
def _convert_stored_settings(connection: sqlite3.Connection, *, available_namespaces: list[str]) -> int:
    row = fetch_backup_settings_row(connection)
    if row is None:
        # A new vault may have no settings row yet.
        return 0
    payload_json = _stored_payload_json(row, token="")
    if payload_json is None:
        return 0
    stored = json.loads(payload_json)
    if not isinstance(stored, dict):
        raise RuntimeError("backup settings payload must be an object")
    if _is_current_form(stored):
        return 0
    if "unchecked_namespaces" not in stored:
        stored["unchecked_namespaces"] = _left_out_by(stored, available_namespaces=available_namespaces)
    if "synced_plaintext_acknowledged" not in stored:
        stored["synced_plaintext_acknowledged"] = []
    _store_settings(connection, _validate_backup_settings(stored), token="")
    return 1


def acknowledged_unprotected_namespaces(settings: dict[str, object], *, folder_path: str) -> frozenset[str]:
    """The vaults without a password the person already chose to back up into this folder."""
    acknowledged = settings["synced_plaintext_acknowledged"]
    assert isinstance(acknowledged, list)
    return frozenset(entry["namespace"] for entry in acknowledged if entry["folder_path"] == folder_path)


def update_backup_settings(
    *,
    token: str,
    folder_path: str,
    unchecked_namespaces: list[str],
    retention_count: int,
    newly_acknowledged_namespaces: list[str],
) -> dict[str, object]:
    if not isinstance(folder_path, str):
        raise TypeError("folder_path must be a string")
    if not isinstance(unchecked_namespaces, list):
        raise TypeError("unchecked_namespaces must be a list")
    if not isinstance(retention_count, int) or retention_count <= 0:
        raise ValueError("retention_count must be a positive integer")

    settings = load_backup_settings(token=token)
    settings["folder_path"] = folder_path
    settings["unchecked_namespaces"] = unchecked_namespaces
    acknowledged = settings["synced_plaintext_acknowledged"]
    assert isinstance(acknowledged, list)
    for namespace in newly_acknowledged_namespaces:
        entry = {"namespace": namespace, "folder_path": folder_path}
        if entry not in acknowledged:
            acknowledged.append(entry)
    settings["retention_count"] = retention_count
    return save_backup_settings(token=token, settings=settings)
