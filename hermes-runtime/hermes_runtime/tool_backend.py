"""Tool-driver backend selection for the deterministic dispatch surface.

The per-profile ``tools:dispatch`` app (ADR-0141) runs the same governed
:func:`toee_hermes.execute.execute_tool` the channel pipeline uses; this module
picks which :class:`~toee_hermes.execute.ToolDriver` backs it. Mock-first
(ADR-0137): unset or ``mock`` selects the in-memory MockDriver; ``datastore``
selects the Postgres system-of-record driver (ADR-0140).

This is a **separate axis** from ``INTEGRATION_DRIVER`` (the external-vendor
backend, ADR-0137): ``TOOL_BACKEND`` chooses the system-of-record store for the
internal ``toee_*`` tools, while ``INTEGRATION_DRIVER`` chooses the external
integration backend (mock/composio/rest). The PostgresDriver lives in this
embedding venv because ``psycopg`` must never reach the dependency-free
``toee_hermes`` plugin (ADR-0096/0100); importing it is deferred to the datastore
branch so a mock-first app never imports the database adapter.
"""

from __future__ import annotations

import os
from typing import Optional

from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers
from toee_hermes.execute import ToolDriver

# Env var selecting the dispatch backend. Values: "mock" | "datastore".
TOOL_BACKEND_ENV = "TOOL_BACKEND"
KNOWN_BACKENDS: tuple[str, ...] = ("mock", "datastore")

_UNSET = object()


def resolve_tool_backend(value: object = _UNSET) -> str:
    """Resolve the configured backend, defaulting to ``mock`` when unset/empty.

    An unrecognized non-empty value is a configuration error and raises (mirrors
    :func:`toee_hermes.drivers.base.resolve_integration_driver`, ADR-0137).
    """
    if value is _UNSET:
        value = os.environ.get(TOOL_BACKEND_ENV)

    if value is None or value == "":
        return "mock"

    if value in KNOWN_BACKENDS:
        return value  # type: ignore[return-value]

    raise ValueError(
        f'Unknown {TOOL_BACKEND_ENV} "{value}". '
        f"Expected one of: {', '.join(KNOWN_BACKENDS)}."
    )


def select_tool_driver(backend: Optional[str] = None) -> ToolDriver:
    """Build the dispatch ToolDriver for ``backend`` (env-resolved when ``None``).

    Mock-first: returns a MockDriver unless ``datastore`` is selected, in which
    case a :class:`~hermes_runtime.datastore.driver.PostgresDriver` is built. The
    Postgres driver resolves its DSN lazily and only connects inside ``execute``,
    so constructing it never requires a reachable database.
    """
    resolved = resolve_tool_backend(_UNSET if backend is None else backend)
    if resolved == "datastore":
        from hermes_runtime.datastore.driver import PostgresDriver

        return PostgresDriver()
    return MockDriver(create_all_mock_handlers())
