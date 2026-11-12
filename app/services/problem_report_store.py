"""Kept problem reports (docs/ready-to-build/error-reports.md, section 4): the last 20, in the
vault's own folder (`reports/` beside its database; no schema change). In a vault with a
password each is sealed with a key derived from the vault's key (AES-256-GCM); a vault without
one keeps them plain, as its notes are. A new one is written with exclusive creation and fsync;
the oldest beyond 20 are deleted, so the folder never grows past that.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import ACTIVE_NAMESPACE
from app.security.crypto_sizes import AES_256_KEY_BYTES, GCM_NONCE_BYTES
from app.server_runtime import resolve_namespace_directory
from app.utils.encryption import get_encryption_service

REPORTS_DIRECTORY_NAME = "reports"
KEPT_REPORTS = 20
_SEALED_SUFFIX = ".report.sealed"
_PLAIN_SUFFIX = ".report.json"
_SEAL_PREFIX = b"MLREPORT1 "
_SEAL_AAD = b"MetaList problem report v1"
_SEAL_KEY_INFO = b"MetaList problem report key v1"
_NAME_RANDOM_BYTES = 4
# 20261112T103112123456Z-a1b2c3d4.report.sealed: sorts by when it was made.
REPORT_ID = re.compile(r"^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{8}$")


class ReportUnreadable(RuntimeError):
    """A kept report sealed under a key this session does not have (the vault's password was
    added or removed since): it cannot be read, and is reported as such."""


@dataclass(frozen=True)
class KeptReport:
    report_id: str
    report: dict


def reports_directory() -> Path:
    return resolve_namespace_directory(namespace=ACTIVE_NAMESPACE) / REPORTS_DIRECTORY_NAME


def _seal_key(dek: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=AES_256_KEY_BYTES, salt=None, info=_SEAL_KEY_INFO).derive(dek)


def _session_key() -> bytes | None:
    """The vault's key while it is unlocked; None for a vault without a password."""
    service = get_encryption_service()
    if service is None:
        return None
    return service.dek


def _encode(report: dict, *, dek: bytes | None) -> tuple[bytes, str]:
    plaintext = json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if dek is None:
        return plaintext, _PLAIN_SUFFIX
    nonce = os.urandom(GCM_NONCE_BYTES)
    sealed = AESGCM(_seal_key(dek)).encrypt(nonce, plaintext, _SEAL_AAD)
    return _SEAL_PREFIX + base64.b64encode(nonce + sealed), _SEALED_SUFFIX


def _decode(path: Path, *, dek: bytes | None) -> dict:
    data = path.read_bytes()
    if path.name.endswith(_PLAIN_SUFFIX):
        return json.loads(data.decode("utf-8"))
    if dek is None:
        raise ReportUnreadable(f"A kept report is sealed and this vault has no key now: {path.name}")
    if not data.startswith(_SEAL_PREFIX):
        raise ValueError(f"A sealed report lacks its prefix: {path.name}")
    payload = base64.b64decode(data[len(_SEAL_PREFIX):], validate=True)
    nonce, sealed = payload[:GCM_NONCE_BYTES], payload[GCM_NONCE_BYTES:]
    return json.loads(AESGCM(_seal_key(dek)).decrypt(nonce, sealed, _SEAL_AAD).decode("utf-8"))


def _report_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = [
        path for path in directory.iterdir()
        if path.is_file() and (path.name.endswith(_SEALED_SUFFIX) or path.name.endswith(_PLAIN_SUFFIX))
    ]
    return sorted(files, key=lambda path: path.name)


def _report_id(path: Path) -> str:
    for suffix in (_SEALED_SUFFIX, _PLAIN_SUFFIX):
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)]
    raise AssertionError(f"not a report file: {path.name}")


def keep_report(report: dict) -> str:
    """Writes a checked report and deletes the oldest beyond the last 20. Returns its id."""
    directory = reports_directory()
    directory.mkdir(parents=True, exist_ok=True)
    data, suffix = _encode(report, dek=_session_key())
    made = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_id = f"{made}-{secrets.token_hex(_NAME_RANDOM_BYTES)}"
    if REPORT_ID.fullmatch(report_id) is None:
        raise AssertionError(f"a report id of an unexpected form: {report_id}")
    with open(directory / f"{report_id}{suffix}", "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    files = _report_files(directory)
    for path in files[: max(len(files) - KEPT_REPORTS, 0)]:
        path.unlink()
    return report_id


def kept_reports() -> list[KeptReport]:
    """Every kept report, newest first."""
    dek = _session_key()
    return [
        KeptReport(report_id=_report_id(path), report=_decode(path, dek=dek))
        for path in reversed(_report_files(reports_directory()))
    ]


def reports_by_id(report_ids: Sequence[str]) -> list[KeptReport]:
    wanted = set(report_ids)
    for report_id in wanted:
        if REPORT_ID.fullmatch(report_id) is None:
            raise ValueError("a report id of an unexpected form")
    found = [kept for kept in kept_reports() if kept.report_id in wanted]
    if len(found) != len(wanted):
        raise KeyError("a report asked for is no longer kept")
    return found
