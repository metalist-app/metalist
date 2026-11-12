"""Verified pre-update backups of every vault. Importing this module reads no app configuration:
`main.py` and `self_update.py` import it before the command line has chosen a vault."""
from __future__ import annotations

from pathlib import Path

from app.server_runtime import validate_namespace


def namespace_database_paths(namespaces_directory: Path) -> tuple[Path, ...]:
    if not namespaces_directory.exists():
        return ()
    if not namespaces_directory.is_dir():
        raise RuntimeError(f"Namespace root is not a directory: {namespaces_directory}")
    databases = []
    for directory in sorted(namespaces_directory.iterdir()):
        if not directory.is_dir():
            continue
        namespace = validate_namespace(namespace=directory.name)
        database = directory / f"{namespace}.metalist.db"
        if not database.is_file():
            raise RuntimeError(f"Namespace database is missing or not a file: {database}")
        databases.append(database)
    return tuple(databases)


def backup_all_namespaces_for_update(*, namespaces_directory: Path) -> tuple[Path, ...]:
    """Back up all saved namespace data after writers stop. Old archives stay: the update
    has not succeeded yet (`metalist trim-safety-backups` runs once it has). Each is the same
    archive as any other backup (notes, file catalog and every blob it names)."""
    # Here, not at the top: the backup service reads app.config, which fixes the vault (as in
    # main.py's trim-safety-backups). By now the command has chosen to update, not to serve.
    from app.services.backup_service import create_verified_backup_for_update
    if not isinstance(namespaces_directory, Path):
        raise TypeError("namespaces_directory must be a Path")
    databases = namespace_database_paths(namespaces_directory.resolve())
    archives = []
    for database in databases:
        print(f"Backing up vault {database.parent.name}...", flush=True)
        archive = create_verified_backup_for_update(database)
        archives.append(archive)
        print(f"Verified backup: {archive}", flush=True)
    return tuple(archives)
