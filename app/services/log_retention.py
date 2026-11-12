"""The logs folder's one owner: which log files MetaList keeps, and for how long.

Agreed 2026-11-11 (docs/ready-to-build/unbounded-growth-audit.md, L1-L6): logs live and die
with their vault. A vault's server log rotates at 25 MB and keeps its newest 2 rotated files;
its fault log and its child-process output are compacted at 25 MB (diagnostics.py). So each
vault's logs stay under about 125 MB, and nothing refuses to start over the folder's size.

Logs of a vault that no longer exists (deleted, renamed, a test vault) go once nothing has
written them for a day: a delete or rename worker may still be writing its own, and Windows
cannot delete a file that is open. Files named some other way are never touched.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import os
import sys
from pathlib import Path
import re

from app.utils.time_units import SECONDS_PER_DAY

# OS-specific locking modules are selected at import time.
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


ROTATED_SERVER_LOGS_KEPT = 2
# Nothing has written a removed vault's log for this long: no worker still holds it open.
_REMOVED_VAULT_LOG_GRACE_SECONDS = SECONDS_PER_DAY
# Two vaults start together; one trims at a time, so none finds a file gone under it.
LOCK_FILE_NAME = ".retention.lock"
# Left by MetaList versions with Ollama support (removed in fd09d7fd); nothing writes it now.
_LEFTOVER_LOG_NAMES = frozenset({"ollama-managed.log"})
# The byte msvcrt locks: a lock file needs one to lock.
_WINDOWS_LOCK_BYTES = 1

# A vault name, as server_runtime.validate_namespace accepts it: no dots, no slashes.
_VAULT = r"[a-z0-9]+(?:-[a-z0-9]+)*"
# loguru's rotated name: "<vault>-server.<%Y-%m-%d_%H-%M-%S_%f>[.<n>].log" (generate_rename_path).
_ROTATED_SERVER_LOG = re.compile(
    rf"(?P<vault>{_VAULT})-server\.(?P<stamp>\d{{4}}-\d{{2}}-\d{{2}}_\d{{2}}-\d{{2}}-\d{{2}}_\d{{6}})"
    r"(?:\.(?P<counter>\d+))?\.log"
)
# Every other log a vault owns, named in diagnostics.py and namespace_switcher.py.
_VAULT_LOGS = (
    re.compile(rf"(?P<vault>{_VAULT})-server\.log"),
    re.compile(rf"(?P<vault>{_VAULT})-server\.fault\.log"),
    re.compile(rf"namespace-(?P<vault>{_VAULT})\.log"),
    re.compile(rf"namespace-delete-(?P<vault>{_VAULT})\.log"),
)
# An encrypted per-login log, written until 2026-11-11 (diagnostics.py before 595ddca2): nothing
# can read one, so every one goes at start-up, whichever vault wrote it (decided 2026-11-12,
# docs/ready-to-build/error-reports.md section 6).
_RETIRED_ENCRYPTED_LOG = re.compile(
    rf"(?P<vault>{_VAULT})-server\.auth-\d{{8}}T\d{{6}}\.\d{{6}}Z-[0-9a-f]{{16}}\.log\.enc"
)
# A rename's log belongs to the vault it renamed: "namespace-rename-<source>-to-<target>.log".
_RENAME_LOG = re.compile(rf"namespace-rename-(?P<pair>{_VAULT})\.log")
_RENAME_SEPARATOR = "-to-"


def is_rotated_server_log(name: str) -> bool:
    return _ROTATED_SERVER_LOG.fullmatch(name) is not None


def _rotation_order(name: str) -> tuple[str, int]:
    match = _ROTATED_SERVER_LOG.fullmatch(name)
    if match is None:
        raise ValueError(f"Not a rotated server log: {name}")
    counter = match.group("counter")
    if counter is None:
        return match.group("stamp"), 0
    return match.group("stamp"), int(counter)


def _rotated_log_vault(name: str) -> str:
    """The vault a rotated log file belongs to; only rotated logs are passed here."""
    match = _ROTATED_SERVER_LOG.fullmatch(name)
    assert match is not None, name
    return match.group("vault")


def _rotated_beyond_kept(paths: Sequence[Path]) -> tuple[Path, ...]:
    """The rotated files of one vault, all but its newest ROTATED_SERVER_LOGS_KEPT."""
    vaults = {_rotated_log_vault(path.name) for path in paths}
    if len(vaults) > 1:
        raise ValueError(f"Rotated logs of more than one vault: {sorted(vaults)}")
    newest_first = sorted(paths, key=lambda path: _rotation_order(path.name), reverse=True)
    return tuple(newest_first[ROTATED_SERVER_LOGS_KEPT:])


def retain_newest_rotated_server_logs(log_paths: list[str]) -> None:
    """loguru's retention for a vault's server log. Its glob ("<vault>-server.*.log") also
    finds the fault log, which it must never delete: only rotated files are counted."""
    rotated = [Path(path) for path in log_paths if is_rotated_server_log(Path(path).name)]
    for path in _rotated_beyond_kept(rotated):
        # Another vault starting may have just deleted it (trim_logs_directory).
        path.unlink(missing_ok=True)


def _owners(name: str) -> frozenset[str]:
    """Every vault a log file of this name could belong to. A name can read two ways (vault
    "namespace-x"'s server log, or vault "x-server"'s child output): it is kept while either
    vault exists. Empty: not a name MetaList gives a vault's log."""
    owners = set()
    for pattern in (_ROTATED_SERVER_LOG, *_VAULT_LOGS):
        match = pattern.fullmatch(name)
        if match is not None:
            owners.add(match.group("vault"))
    rename = _RENAME_LOG.fullmatch(name)
    if rename is not None:
        pair = rename.group("pair")
        for separator in re.finditer(re.escape(_RENAME_SEPARATOR), pair):
            owners.add(pair[: separator.start()])
    return frozenset(owners)


def _is_removable_when_old(*, name: str, existing_vaults: frozenset[str]) -> bool:
    if name in _LEFTOVER_LOG_NAMES:
        return True
    owners = _owners(name)
    return len(owners) > 0 and owners.isdisjoint(existing_vaults)


def _existing_vaults(*, namespaces_directory: Path, own_vault: str) -> frozenset[str]:
    """The vaults with a folder, and the one starting now, whose folder may not exist yet
    and whose child log is already open."""
    vaults = {own_vault}
    if namespaces_directory.is_dir():
        vaults.update(path.name for path in namespaces_directory.iterdir() if path.is_dir())
    return frozenset(vaults)


@contextmanager
def _folder_lock(logs_directory: Path) -> Iterator[None]:
    path = logs_directory / LOCK_FILE_NAME
    with path.open("a+b") as handle:
        if sys.platform == "win32":
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, _WINDOWS_LOCK_BYTES)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _WINDOWS_LOCK_BYTES)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _own_rotated_beyond_kept(*, files: Sequence[Path], own_vault: str) -> tuple[Path, ...]:
    own_rotated = [
        path for path in files
        if is_rotated_server_log(path.name) and _owners(path.name) == frozenset({own_vault})
    ]
    return _rotated_beyond_kept(own_rotated)


def _removed_vault_logs(
    *, files: Sequence[Path], existing_vaults: frozenset[str], now: float,
) -> tuple[Path, ...]:
    """Logs of vaults that no longer exist, and leftovers, that nothing wrote for a day."""
    removable = [path for path in files if _is_removable_when_old(name=path.name, existing_vaults=existing_vaults)]
    return tuple(
        path for path in removable
        if now - path.stat().st_mtime >= _REMOVED_VAULT_LOG_GRACE_SECONDS
    )


def trim_logs_directory(
    *, logs_directory: Path, namespaces_directory: Path, own_vault: str, now: float,
) -> tuple[Path, ...]:
    """Run as a vault starts, before its server log opens: its own rotated logs come down
    to the newest ROTATED_SERVER_LOGS_KEPT (each running vault's loguru keeps them there
    after), logs of vaults that no longer exist go once a day old, and old encrypted logs go.
    Returns what it deleted."""
    if not isinstance(logs_directory, Path) or not isinstance(namespaces_directory, Path):
        raise TypeError("logs_directory and namespaces_directory must be Paths")
    if re.fullmatch(_VAULT, own_vault) is None:
        raise ValueError(f"Not a vault name: {own_vault!r}")
    logs_directory.mkdir(parents=True, exist_ok=True)
    existing_vaults = _existing_vaults(namespaces_directory=namespaces_directory, own_vault=own_vault)
    with _folder_lock(logs_directory):
        files = sorted(path for path in logs_directory.iterdir() if path.is_file())
        deleted = (
            *_own_rotated_beyond_kept(files=files, own_vault=own_vault),
            *_removed_vault_logs(files=files, existing_vaults=existing_vaults, now=now),
            *(path for path in files if _RETIRED_ENCRYPTED_LOG.fullmatch(path.name) is not None),
        )
        if len(set(deleted)) != len(deleted):
            raise AssertionError("Log retention chose one file twice")
        for path in deleted:
            path.unlink()
    return deleted
