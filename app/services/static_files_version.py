"""The version of MetaList's own files (app/static), for addresses the browser may keep.

A page loads its scripts and stylesheets from /static/v/<version>/…, and an import map points
/static/js/ there too, so all 318 scripts the page imports share one versioned folder. The
browser keeps them until the version changes, and a later visit downloads none of them (the
maintainer, 2026-11-12: over Wi-Fi the vault list came a second or more later, every one of
those files fetched again on each visit).

The version is a fingerprint of every file's path, size and change time, worked out again
each time a page is made (about 10 ms for 455 files): a file saved while MetaList runs, as
in the maintainer's own copy served from the checkout, gives the next page a new version.
Files are answered as kept-for-good only under the version the pages were last given; any
other version is answered as never kept.
"""

from __future__ import annotations

import hashlib
from http import HTTPStatus
import os
from pathlib import Path
import threading

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

STATIC_DIRECTORY = Path(__file__).resolve().parent.parent / "static"
# Where app/static is served.
STATIC_URL_PREFIX = "/static/"
# The folder segment that names a version: /static/v/<version>/js/main.js.
VERSIONED_FOLDER = "v"
# Hex digits of the fingerprint kept in addresses: enough that two versions never share one.
_VERSION_HEX_DIGITS = 16
# Matches no fingerprint (those are hex digits).
_NO_VERSION_GIVEN = "none"
# A file under /static/v/<version>/ is the one that version names: kept for good when the
# version is the one pages were last given, never kept otherwise. Any other file is asked about
# again on each use: the browser keeps it, and while it is unchanged the answer is a short
# "not modified".
_KEPT_FOR_GOOD = "public, max-age=31536000, immutable"
_NEVER_KEPT = "no-store"
_ASKED_AGAIN = "no-cache"
# v, the version, then the file's own path.
_VERSIONED_PATH_LEAST_PARTS = 3
_KEPT_STATUSES = frozenset({HTTPStatus.OK, HTTPStatus.NOT_MODIFIED})


def fingerprint_static_files(directory: Path) -> str:
    """Every file under directory, by path, size and change time."""
    if not directory.is_dir():
        raise FileNotFoundError(f"Static files folder missing: {directory}")
    digest = hashlib.sha256()
    for folder, subfolders, names in os.walk(directory):
        subfolders.sort()
        for name in sorted(names):
            path = Path(folder) / name
            facts = path.stat()
            digest.update(f"{path.relative_to(directory).as_posix()}\0{facts.st_size}\0{facts.st_mtime_ns}\n".encode())
    return digest.hexdigest()[:_VERSION_HEX_DIGITS]


class StaticFilesVersion:
    """The version pages are given, worked out again for each page."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = threading.Lock()
        # No page made yet: no version is kept for good.
        self._given = _NO_VERSION_GIVEN

    def for_page(self) -> str:
        """The version a page being made links to; from now on it is the one kept for good."""
        version = fingerprint_static_files(self._directory)
        with self._lock:
            self._given = version
        return version

    def is_current(self, version: str) -> bool:
        """Whether files asked for under version may be kept for good."""
        with self._lock:
            return version == self._given


static_files_version = StaticFilesVersion(STATIC_DIRECTORY)


class MetaListStaticFiles(StaticFiles):
    """app/static, at /static/ and under each version's folder."""

    def __init__(self, *, directory: str, version: StaticFilesVersion) -> None:
        super().__init__(directory=directory)
        self._version = version

    async def get_response(self, path: str, scope: Scope) -> Response:
        # Starlette passes the path with the system's separators, '..' already resolved.
        parts = path.split(os.sep)
        if len(parts) >= _VERSIONED_PATH_LEAST_PARTS and parts[0] == VERSIONED_FOLDER:
            response = await super().get_response(os.path.join(*parts[2:]), scope)
            cache_control = _NEVER_KEPT
            if self._version.is_current(parts[1]):
                cache_control = _KEPT_FOR_GOOD
        else:
            response = await super().get_response(path, scope)
            cache_control = _ASKED_AGAIN
        # A file's answer and "not modified" say how long to keep it; anything else, never.
        if response.status_code not in _KEPT_STATUSES:
            cache_control = _NEVER_KEPT
        response.headers["Cache-Control"] = cache_control
        return response
