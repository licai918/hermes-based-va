"""Postgres-backed ToolDriver for the Toee Business Datastore (ADR-0140, Slice 33).

Real CRUD for the structured ``toee_*`` actions behind the *same* governed
:func:`toee_hermes.execute.execute_tool` the mock path uses: the catalog check,
Tool Gate, and profile allowlist all run before the driver is ever called, so
swapping MockDriver for this driver introduces no governance drift. ``psycopg``
lives only here in the hermes-runtime venv, never in the dependency-free
``toee_hermes`` plugin (ADR-0096/0100).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator, Optional

import psycopg

from toee_hermes.errors import ToolDriverError

from .config import database_url
from .handlers import DatastoreRegistry, build_datastore_registry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.execute import ToolRequest
    from toee_hermes.tool_gate import ToolExecutionContext


class PostgresDriver:
    """Dispatches a gate-approved request to a per-tool SQL handler.

    Two connection modes:

    * ``connection=`` — a caller-owned open connection (tests / single-process
      local dev). Its lifecycle (and ``search_path``) belong to the caller; the
      driver only commits/rolls back its unit of work, never closes it.
    * ``dsn=`` (default) — open a fresh connection per ``execute`` and close it.
      Simple and correct for local-first; pooling is a later cloud concern
      (ADR-0142, Slice 34/37).
    """

    kind = "datastore"

    def __init__(
        self,
        *,
        connection: Optional[psycopg.Connection] = None,
        dsn: Optional[str] = None,
        registry: Optional[DatastoreRegistry] = None,
    ) -> None:
        if connection is None and dsn is None:
            dsn = database_url()
        self._connection = connection
        self._dsn = dsn
        self._registry = registry if registry is not None else build_datastore_registry()

    @contextmanager
    def _acquire(self) -> Iterator[psycopg.Connection]:
        if self._connection is not None:
            yield self._connection
        else:
            conn = psycopg.connect(self._dsn)
            try:
                yield conn
            finally:
                conn.close()

    def execute(self, request: "ToolRequest", context: "ToolExecutionContext") -> Any:
        actions = self._registry.get(request.tool)
        if actions is None:
            # Catalog-valid but not a datastore tool: a governed configuration gap,
            # mirroring MockDriver, never a raise that escapes dispatch (ADR-0020).
            raise ToolDriverError(
                "configuration_missing",
                f"No datastore handler registered for tool '{request.tool}'.",
            )
        handler = actions.get(request.action)
        if handler is None:
            raise ToolDriverError(
                "configuration_missing",
                f"No datastore handler for '{request.tool}.{request.action}'.",
            )
        with self._acquire() as conn:
            try:
                result = handler(conn, request.params, context)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
