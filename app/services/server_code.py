"""Whether this server still runs the code on disk (asked for 2026-10-30).

The browser loads its files from disk on every page load, but the server's Python code is
read once, when it starts. After a change on disk (a checkout updated while MetaList runs,
or an update that replaced its files and is still restarting) a new page can talk to an
old server, and an answer in the old shape fails loudly in the browser ("Tab state
response missing summaries"). The page asks here when it starts and when an error shows,
and says to restart MetaList instead of leaving the error unexplained.

The code is fingerprinted by each Python file's path, size and modification time: cheap
enough to recompute on demand (a few hundred stats), and any edit changes it."""

from __future__ import annotations

import hashlib
from pathlib import Path

# This file is app/services/server_code.py: the checkout (or installed package's folder)
# is two folders up from its folder.
_FOLDERS_UP_TO_ROOT = 2
_ROOT = Path(__file__).resolve().parents[_FOLDERS_UP_TO_ROOT]
# The server's own code: the app package and the scripts that start it.
_CODE_GLOBS = ("app/**/*.py", "main.py", "serve_namespace.py")


def _code_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted(path for pattern in _CODE_GLOBS for path in _ROOT.glob(pattern)):
        stat = path.stat()
        digest.update(f"{path.relative_to(_ROOT).as_posix()}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


# Read when the server starts (this module is imported with the app).
_STARTED_WITH = _code_fingerprint()


def is_server_code_stale() -> bool:
    """Whether the Python code on disk changed since this server started."""
    return _code_fingerprint() != _STARTED_WITH
