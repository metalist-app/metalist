"""Folders a cloud app keeps in sync (docs/ui/command-palette.md, `Back Up Now…`): Back Up
Now suggests a `MetaList Backups` folder in each, and warns before a vault without a
password is backed up into one (agreed 2026-10-27). MetaList holds no cloud credentials:
the provider's desktop app uploads what lands in the folder.

Only folder names are read, never their contents: the provider folders in the home folder,
and on macOS the entries of ~/Library/CloudStorage (where current Dropbox, Google Drive
and OneDrive clients mount) and iCloud Drive's folder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUGGESTED_SUBFOLDER = "MetaList Backups"
# Names a provider's folder starts with, in ~/Library/CloudStorage or the home folder.
_PROVIDER_PREFIXES = (("Dropbox", "Dropbox"), ("GoogleDrive", "Google Drive"), ("Google Drive", "Google Drive"),
                      ("OneDrive", "OneDrive"), ("iCloudDrive", "iCloud Drive"))
# Google Drive mounts each account with its files under "My Drive".
_GOOGLE_DRIVE_FILES = "My Drive"
_ICLOUD_DRIVE = Path("Library") / "Mobile Documents" / "com~apple~CloudDocs"
_CLOUD_STORAGE = Path("Library") / "CloudStorage"


@dataclass(frozen=True)
class SyncedFolder:
    provider: str
    # Where the provider's files are: what a backup folder is checked against.
    root: Path

    @property
    def suggestion(self) -> Path:
        return self.root / SUGGESTED_SUBFOLDER

    @property
    def label(self) -> str:
        """`Dropbox › MetaList Backups`, `Google Drive › My Drive › MetaList Backups`."""
        if self.root.name == _GOOGLE_DRIVE_FILES:
            return f"{self.provider} › {_GOOGLE_DRIVE_FILES} › {SUGGESTED_SUBFOLDER}"
        return f"{self.provider} › {SUGGESTED_SUBFOLDER}"


def _provider_of(name: str) -> str | None:
    for prefix, provider in _PROVIDER_PREFIXES:
        if name.startswith(prefix):
            return provider
    return None


def _folders_in(directory: Path) -> list[SyncedFolder]:
    if not directory.is_dir():
        return []
    found = []
    for child in sorted(directory.iterdir(), key=lambda path: path.name):
        provider = _provider_of(child.name)
        if provider is None or not child.is_dir():
            continue
        root = child
        if provider == "Google Drive" and (child / _GOOGLE_DRIVE_FILES).is_dir():
            root = child / _GOOGLE_DRIVE_FILES
        found.append(SyncedFolder(provider=provider, root=root))
    return found


def find_synced_folders(home: Path) -> list[SyncedFolder]:
    """The synced folders on this computer, each once."""
    if not isinstance(home, Path):
        raise TypeError("home must be a Path")
    folders = [*_folders_in(home / _CLOUD_STORAGE), *_folders_in(home)]
    if (home / _ICLOUD_DRIVE).is_dir():
        folders.append(SyncedFolder(provider="iCloud Drive", root=home / _ICLOUD_DRIVE))
    unique: dict[Path, SyncedFolder] = {}
    for folder in folders:
        resolved = folder.root.resolve()
        if resolved not in unique:
            unique[resolved] = folder
    return list(unique.values())


@dataclass(frozen=True)
class SuggestedFolder:
    label: str
    path: Path


_DOWNLOADS = "Downloads"


def suggested_backup_folders(home: Path) -> list[SuggestedFolder]:
    """Back Up Now's folder buttons: Downloads itself first (where browsers and many people
    keep backups), then a MetaList Backups folder in each synced folder. Only folders that
    exist are offered."""
    suggestions = []
    if (home / _DOWNLOADS).is_dir():
        suggestions.append(SuggestedFolder(label=_DOWNLOADS, path=home / _DOWNLOADS))
    suggestions.extend(SuggestedFolder(label=folder.label, path=folder.suggestion) for folder in find_synced_folders(home))
    return suggestions


def provider_syncing(path: Path, *, home: Path) -> str:
    """The provider whose synced folder holds `path`, or "" when none does."""
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    resolved = path.expanduser().resolve()
    for folder in find_synced_folders(home):
        if resolved == folder.root.resolve() or folder.root.resolve() in resolved.parents:
            return folder.provider
    return ""
