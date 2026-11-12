"""The names a vault had before it was renamed, kept in `former-names.json` in its folder.

Backups are never renamed (AGENTS.md, "Backup Immutability"), so a renamed vault's safety
backups keep the name they were made under. Its own backups folder lists, restores and trims
those too (approved by the maintainer 2026-11-11, docs/ready-to-build/unbounded-growth-audit.md,
B3). Only its own folder: another vault may take the old name later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from app.server_runtime import validate_namespace

FORMER_NAMES_FILE_NAME = "former-names.json"
_FORMER_NAMES_KEY = "former_names"


def _validated_names(raw_names: object, *, path: Path) -> frozenset[str]:
    if not isinstance(raw_names, list) or not all(isinstance(name, str) for name in raw_names):
        raise RuntimeError(f"{path} must hold a list of vault names")
    names = frozenset(raw_names)
    for name in names:
        if validate_namespace(namespace=name) != name:
            raise RuntimeError(f"{path} holds {name!r}, which is not a vault name")
    return names


def read_former_vault_names(vault_directory: Path) -> frozenset[str]:
    """Every name this vault had; empty for a vault never renamed."""
    path = vault_directory / FORMER_NAMES_FILE_NAME
    if not path.exists():
        return frozenset()
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or set(record) != {_FORMER_NAMES_KEY}:
        raise RuntimeError(f"{path} must hold only {_FORMER_NAMES_KEY!r}")
    return _validated_names(record[_FORMER_NAMES_KEY], path=path)


def record_former_vault_name(*, vault_directory: Path, former_name: str, current_name: str) -> frozenset[str]:
    """After a rename has moved the folder: its names so far, plus the one it just left. Its
    current name is never a former one (a vault renamed back to an earlier name)."""
    if validate_namespace(namespace=former_name) == validate_namespace(namespace=current_name):
        raise ValueError("A rename must change the vault's name")
    names = (read_former_vault_names(vault_directory) | {former_name}) - {current_name}
    path = vault_directory / FORMER_NAMES_FILE_NAME
    staged = vault_directory / f".{FORMER_NAMES_FILE_NAME}.{uuid4().hex}.tmp"
    with staged.open("x", encoding="utf-8") as stream:
        json.dump({_FORMER_NAMES_KEY: sorted(names)}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staged, path)
    return names
