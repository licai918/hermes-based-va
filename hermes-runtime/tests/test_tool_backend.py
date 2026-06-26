"""Slice 33 / #36: tool-driver backend selection for the dispatch surface.

The per-profile ``tools:dispatch`` app (ADR-0141) runs the same governed
``execute_tool`` the channel pipeline uses; ``select_tool_driver`` picks which
``ToolDriver`` backs it. Mock-first (ADR-0137): unset/``mock`` -> MockDriver;
``datastore`` -> the Postgres system-of-record driver (ADR-0140). The no-drift
test pins the datastore registry to the v1 catalog and the mock registry so the
two backends cannot diverge for the system-of-record tools.

These tests need no Postgres: ``PostgresDriver()`` resolves its DSN lazily and
only connects inside ``execute``.
"""

from __future__ import annotations

import pytest

from toee_hermes.drivers.mock import create_all_mock_handlers
from toee_hermes.tool_catalog import is_tool_action

from hermes_runtime.datastore.handlers import build_datastore_registry
from hermes_runtime.tool_backend import resolve_tool_backend, select_tool_driver


def test_resolve_defaults_to_mock_when_unset_or_empty() -> None:
    assert resolve_tool_backend(None) == "mock"
    assert resolve_tool_backend("") == "mock"


def test_resolve_accepts_known_backends() -> None:
    assert resolve_tool_backend("mock") == "mock"
    assert resolve_tool_backend("datastore") == "datastore"


def test_resolve_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError):
        resolve_tool_backend("redis")


def test_select_mock_driver_is_mock_kind() -> None:
    driver = select_tool_driver("mock")
    assert driver.kind == "mock"


def test_select_datastore_driver_is_datastore_kind() -> None:
    # Constructed without a connection; DSN resolves lazily so no DB is needed.
    driver = select_tool_driver("datastore")
    assert driver.kind == "datastore"


def test_datastore_registry_has_no_catalog_drift() -> None:
    # Every datastore (tool, action) is a real v1 catalog action: handler keys
    # cannot drift from the governed catalog (ADR-0059/0070).
    registry = build_datastore_registry()
    for tool, actions in registry.items():
        for action in actions:
            assert is_tool_action(tool, action), f"{tool}.{action} not in catalog"


def test_datastore_registry_is_subset_of_mock() -> None:
    # The datastore backs the system-of-record tools only; every action it
    # implements must also exist in the mock registry so swapping the backend
    # never references a tool/action the mock path lacks (no mock/datastore drift).
    datastore = build_datastore_registry()
    mock = create_all_mock_handlers()
    for tool, actions in datastore.items():
        assert tool in mock, f"datastore tool {tool} missing from mock registry"
        for action in actions:
            assert action in mock[tool], f"datastore {tool}.{action} missing from mock"
