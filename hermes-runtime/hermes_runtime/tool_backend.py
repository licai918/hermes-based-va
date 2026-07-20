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
from typing import Any, Optional

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


def memory_enabled(value: object = _UNSET) -> bool:
    """Whether Customer Memory is active for this deployment (S05, FR-7/RK-6).

    True only when the datastore backend is configured (``TOOL_BACKEND=datastore``).
    Single source of truth shared by the write overlay (S04's per-tool
    ``extra_drivers`` injection) and the read injection gates (S07/S08): a
    mock/unset deployment never hard-depends on Postgres — reads inject nothing,
    writes stay on the ephemeral mock, and the turn still completes and replies.
    """
    return resolve_tool_backend(value) == "datastore"


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


def _customer_memory_extra_drivers() -> Optional[dict[str, Any]]:
    """Route ``toee_customer_memory`` to the Postgres datastore for an agent turn.

    Shared by the live External turn (``openrouter.py``, S04) and the unbound
    Copilot draft turn (``copilot_turn.py``, S20/PAC-4 gap #2) -- both boot paths
    need the SAME overlay, so it lives here next to the two things it uses
    (:func:`memory_enabled`, :func:`select_tool_driver`) instead of being
    reimplemented per caller (Standards fix #1). Gated by :func:`memory_enabled`
    (S05) -- the single source of truth for whether Customer Memory is active,
    shared with the read injection gates (S07/S08). ``False`` (mock/unset
    backend) returns ``None`` so the tool stays on the shared mock driver and a
    mock deployment never hard-depends on Postgres. ``select_tool_driver`` builds
    the ``PostgresDriver`` (psycopg stays in hermes-runtime); the plugin overlay
    only ever sees a ``ToolDriver``, whose ``kind = "datastore"`` attributes the
    audit rows (anti-mock, ADR-0140).
    """
    if not memory_enabled():
        return None
    return {"toee_customer_memory": select_tool_driver("datastore")}


def _knowledge_extra_drivers() -> Optional[dict[str, Any]]:
    """Route ``toee_knowledge_search`` to the S08 retriever for an agent turn.

    The knowledge twin of :func:`_customer_memory_extra_drivers`: same
    ``extra_drivers`` seam (§7 seam 4), same shape, gated by its own axis
    (:func:`hermes_runtime.knowledge.driver.knowledge_enabled`, ``KNOWLEDGE_BACKEND``)
    rather than :func:`memory_enabled`'s ``TOOL_BACKEND`` -- knowledge is on/off
    independently of the business datastore. ``False`` (unset/off) returns
    ``None`` so the tool stays on the shared mock driver's 2-entry stub and a
    deployment without a knowledge store never hard-depends on it.

    Not called from any turn composition path yet (S10 wires it onto the
    external/copilot turn profiles); this only builds the overlay dict.
    """
    from hermes_runtime.knowledge.driver import KnowledgeDriver, knowledge_enabled

    if not knowledge_enabled():
        return None
    return {"toee_knowledge_search": KnowledgeDriver()}


def _turn_extra_drivers() -> Optional[dict[str, Any]]:
    """Merge the Customer Memory and Knowledge per-tool overlays for one agent turn.

    Single source for both turn paths (external ``openrouter.py`` + copilot draft
    ``copilot_turn.py``, S10): each overlay is gated on its own independent axis
    (:func:`memory_enabled`'s ``TOOL_BACKEND`` vs
    :func:`hermes_runtime.knowledge.driver.knowledge_enabled`'s ``KNOWLEDGE_BACKEND``),
    mirroring how the two gates already stay independent -- no coupling introduced
    by merging them here. ``None`` only when BOTH overlays are off, so a turn with
    neither backend enabled boots with ``extra_drivers=None`` exactly as before.
    """
    mem = _customer_memory_extra_drivers()
    kn = _knowledge_extra_drivers()
    if mem is None and kn is None:
        return None
    return {**(mem or {}), **(kn or {})}


def _gateway_store() -> Any:
    """Build the Postgres gateway store for a Customer Memory read/merge/lookup.

    Shared by the turn-time memory read + provisional merge (``openrouter.py``,
    S06/S07/S10), the Copilot case-identity/memory read (``copilot_turn.py``,
    S08), and the Workbench dispatch-time case identity lookup
    (``tool_dispatch_app.py``, S16) -- every caller wants the SAME default
    construction, only ever overridden by an explicit ``store=`` param in tests
    (Standards fix #1). Deferred import keeps ``psycopg`` out of a mock
    deployment's import path (same reasoning as ``select_tool_driver``'s
    ``PostgresDriver`` branch above); every call site only reaches this under
    :func:`memory_enabled`, so a mock/unset deployment never constructs it.
    DSN-based, matching how ``select_tool_driver`` obtains its datastore driver.
    """
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    return PostgresGatewayStore()
