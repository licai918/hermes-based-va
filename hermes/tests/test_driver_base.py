"""Driver-kind/selection contracts (`toee_hermes.drivers.base`)."""

from __future__ import annotations

from typing import get_args

import pytest

from toee_hermes.drivers.base import (
    KNOWN_DRIVERS,
    IntegrationDriver,
    resolve_integration_driver,
)


def test_datastore_is_a_valid_driver_kind() -> None:
    # The Postgres system-of-record driver (ADR-0140) reports kind="datastore"
    # on its audit records, so it must be a valid IntegrationDriver literal.
    assert "datastore" in get_args(IntegrationDriver)


def test_datastore_is_not_an_integration_driver_env_value() -> None:
    # INTEGRATION_DRIVER selects the external vendor backend (mock/composio/rest).
    # The datastore is a separate axis wired in the runtime, never via this env.
    assert "datastore" not in KNOWN_DRIVERS
    with pytest.raises(ValueError):
        resolve_integration_driver("datastore")


def test_resolve_defaults_to_mock_when_unset() -> None:
    assert resolve_integration_driver(None) == "mock"
    assert resolve_integration_driver("") == "mock"
