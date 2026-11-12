"""The sqlite3 connection under MetaList's connection wrappers."""

from __future__ import annotations

import sqlite3
from typing import Protocol

_RAW_CONNECTION_ATTRIBUTE = "raw_connection"


class ConnectionWrapper(Protocol):
    """Either GuardedConnection (app.db.engine's or app.db.session's), as a type: the sqlite3
    connection it wraps is its raw_connection."""

    @property
    def raw_connection(self) -> sqlite3.Connection: ...


def raw_sqlite_connection(connection: object) -> sqlite3.Connection:
    """A plain sqlite3 connection as it is, or the one a GuardedConnection wraps.

    Both wrappers (app.db.engine and app.db.session) expose it as raw_connection;
    session's cannot be imported here without an import cycle, so the wrapper is
    recognized by that attribute.
    """
    if isinstance(connection, sqlite3.Connection):
        return connection
    # No default: a connection that is neither sqlite3 nor a wrapper fails here.
    raw_connection = getattr(connection, _RAW_CONNECTION_ATTRIBUTE)
    assert isinstance(raw_connection, sqlite3.Connection), type(connection)
    return raw_connection
