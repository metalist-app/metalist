"""Bringing the old MetaList's notes into an empty namespace, from MetaList itself (the
maintainer, 2026-11-04; docs/ui/legacy-import.md): what convert-from-legacy.py does at a
terminal, with nothing to type there.

The converter runs as its own process: it writes a whole namespace, and setting its password
there leaves this server's keys alone. It writes into a staging data folder; the namespace it
writes is installed as the live one as a restore installs an archive's (backup_service), and the
server then restarts, as after a restore. The old MetaList's file is only read: it is hashed
before and after the conversion, as a restore hashes its archive, and a change installs nothing."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.db.file_session import resolve_file_database_path
from app.utils.byte_sizes import MIB
from app.services.backup_service import install_converted_databases
from app.services.input_errors import InputRejected
from app.services.legacy_metalist import LegacyDatabase
from app.server_runtime import NamespaceLaunchProfile

CONVERTER_SCRIPT_NAME = "convert-from-legacy.py"
# A source checkout runs its own converter, as its tests do; an installed MetaList's is in its
# environment's scripts folder (pyproject.toml, script-files).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SOURCE_CHECKOUT_MARKER = _PROJECT_ROOT / "pyproject.toml"
_STAGING_PREFIX = ".legacy-import-"
_EXIT_OK = 0
_HASH_CHUNK_BYTES = MIB


@dataclass(frozen=True)
class LegacyConversionRequest:
    legacy: LegacyDatabase
    # The old notes' password (None when they were not protected) and the converted namespace's
    # (None for none).
    legacy_password: str | None
    password: str | None
    launch_profile: NamespaceLaunchProfile
    kdf_time_cost: int


def converter_script_path() -> Path:
    if _SOURCE_CHECKOUT_MARKER.is_file():
        path = _PROJECT_ROOT / CONVERTER_SCRIPT_NAME
    else:
        path = Path(sysconfig.get_path("scripts")) / CONVERTER_SCRIPT_NAME
    if not path.is_file():
        raise FileNotFoundError(f"The legacy converter is missing: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _converter_arguments(request: LegacyConversionRequest) -> list[str]:
    profile = request.launch_profile
    arguments = [
        sys.executable, str(converter_script_path()),
        "--namespace", profile.namespace,
        "--kdf-iterations", str(request.kdf_time_cost),
        "--legacy-database", str(request.legacy.path),
        "--passwords-from-stdin",
    ]
    # An omitted port is the namespace's default; the live profile is saved again after install.
    if profile.port is not None:
        arguments += ["--port", str(profile.port)]
    if profile.https_port is not None:
        arguments += ["--https-port", str(profile.https_port)]
    return arguments


def _converter_environment(staging_directory: Path) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("METALIST_") and key != "TEST_MODE"}
    environment["METALIST_DATA_DIRECTORY"] = str(staging_directory)
    return environment


def _run_converter(request: LegacyConversionRequest, staging_directory: Path) -> None:
    passwords = json.dumps({"legacy_password": request.legacy_password, "password": request.password})
    completed = subprocess.run(
        _converter_arguments(request),
        input=passwords + "\n",
        env=_converter_environment(staging_directory),
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if completed.returncode != _EXIT_OK:
        raise RuntimeError(f"The legacy converter failed (exit {completed.returncode}):\n{completed.stderr}")


def convert_legacy_into_live_namespace(request: LegacyConversionRequest, *, database_path: Path) -> None:
    """Replace the live namespace at database_path, an empty one, with the old MetaList's notes."""
    if request.legacy.encrypted != (request.legacy_password is not None):
        raise ValueError("A legacy password is needed exactly when the old notes are encrypted")
    namespace = request.launch_profile.namespace
    if database_path.name != f"{namespace}.metalist.db":
        raise ValueError(f"{database_path} is not namespace {namespace!r}'s database")
    legacy_hash = _sha256(request.legacy.path)
    with tempfile.TemporaryDirectory(prefix=_STAGING_PREFIX, dir=request.legacy.path.parent) as staging:
        staging_directory = Path(staging)
        _run_converter(request, staging_directory)
        # Checked before anything is installed: notes read while the old MetaList wrote them may
        # be half of what it wrote.
        if _sha256(request.legacy.path) != legacy_hash:
            raise InputRejected(
                "The old MetaList's notes changed while they were brought in. "
                "Close the old MetaList and try again."
            )
        notes_stage = staging_directory / "namespaces" / namespace / database_path.name
        install_converted_databases(
            notes_stage=notes_stage,
            files_stage=resolve_file_database_path(notes_stage),
            database_path=database_path,
        )
