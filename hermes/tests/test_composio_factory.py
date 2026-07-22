"""build_composio_driver() env wiring (ADR-0136/0137, 0.0.4 S12).

The factory is the only place that touches the optional Composio SDK (lazy import),
so importing ``toee_hermes`` stays dependency-free. A missing ``COMPOSIO_API_KEY``
is a governed configuration failure, never a raw crash, and the SDK is never
imported when the env is not configured.

S12 adds the two production-cutover preconditions the factory now enforces:
an exact toolkit-version pin per configured toolkit (FR-18) and a bounded
per-call deadline (NFR-8).
"""

from __future__ import annotations

import importlib.util

import pytest

from toee_hermes.drivers.composio import (
    CONNECTED_ACCOUNT_ENV,
    TOOLKIT_SLUG,
    TOOLKIT_VERSION_ENV,
    build_composio_driver,
    deadline_seconds,
    pinned_toolkit_versions,
)
from toee_hermes.drivers.composio.driver import DEFAULT_DEADLINE_MS
from toee_hermes.errors import ToolDriverError

_COMPOSIO_INSTALLED = importlib.util.find_spec("composio") is not None


def test_build_composio_driver_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)

    with pytest.raises(ToolDriverError) as excinfo:
        build_composio_driver()

    assert excinfo.value.error_class == "configuration_missing"


@pytest.mark.skipif(
    _COMPOSIO_INSTALLED, reason="composio SDK is intentionally not a dependency (ADR-0137)"
)
def test_build_composio_driver_without_sdk_is_governed(monkeypatch) -> None:
    # With a key present but the optional SDK absent, the lazy import must surface a
    # governed ToolDriverError rather than an ImportError escaping dispatch.
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_test_not_used_for_network")
    monkeypatch.setenv("COMPOSIO_USER_ID", "toee-local-test")
    for env_var in TOOLKIT_VERSION_ENV.values():
        monkeypatch.setenv(env_var, "20260506_00")

    with pytest.raises(ToolDriverError) as excinfo:
        build_composio_driver()

    assert excinfo.value.error_class == "configuration_missing"


# --- toolkit version pin (FR-18) --------------------------------------------


def test_qbo_pin_is_read_from_the_vendor_slug_env_var() -> None:
    # The pin is keyed by Composio's OWN toolkit slug, not our toolkit key: the SDK
    # resolves a call's version with get_toolkit_version(tool.toolkit.slug, ...).
    # "qbo" is a Toee-side name, so COMPOSIO_TOOLKIT_VERSION_QBO is never read.
    assert TOOLKIT_SLUG["qbo"] == "quickbooks"
    assert TOOLKIT_VERSION_ENV["qbo"] == "COMPOSIO_TOOLKIT_VERSION_QUICKBOOKS"
    assert TOOLKIT_VERSION_ENV["shopify"] == "COMPOSIO_TOOLKIT_VERSION_SHOPIFY"
    assert TOOLKIT_VERSION_ENV["square"] == "COMPOSIO_TOOLKIT_VERSION_SQUARE"
    # Every toolkit with a connected-account env var needs a pin env var.
    assert set(TOOLKIT_VERSION_ENV) == set(CONNECTED_ACCOUNT_ENV)


def test_pinned_versions_keyed_by_vendor_slug(monkeypatch) -> None:
    monkeypatch.setenv("COMPOSIO_TOOLKIT_VERSION_SHOPIFY", "20260506_00")
    monkeypatch.setenv("COMPOSIO_TOOLKIT_VERSION_QUICKBOOKS", "20260623_00")

    versions = pinned_toolkit_versions({"shopify": "ca_1", "qbo": "ca_2"})

    assert versions == {"shopify": "20260506_00", "quickbooks": "20260623_00"}


def test_missing_pin_fails_closed_naming_the_env_var(monkeypatch) -> None:
    monkeypatch.setenv("COMPOSIO_TOOLKIT_VERSION_SHOPIFY", "20260506_00")
    monkeypatch.delenv("COMPOSIO_TOOLKIT_VERSION_SQUARE", raising=False)

    with pytest.raises(ToolDriverError) as excinfo:
        pinned_toolkit_versions({"shopify": "ca_1", "square": "ca_3"})

    assert excinfo.value.error_class == "configuration_missing"
    assert "COMPOSIO_TOOLKIT_VERSION_SQUARE" in str(excinfo.value)


def test_latest_is_not_a_pin(monkeypatch) -> None:
    # "latest" is what the SDK falls back to when unpinned, and it raises
    # ToolVersionRequiredError inside tools.execute. Reject it at boot instead.
    monkeypatch.setenv("COMPOSIO_TOOLKIT_VERSION_SHOPIFY", "latest")

    with pytest.raises(ToolDriverError) as excinfo:
        pinned_toolkit_versions({"shopify": "ca_1"})

    assert "COMPOSIO_TOOLKIT_VERSION_SHOPIFY" in str(excinfo.value)


def test_unconfigured_toolkit_needs_no_pin(monkeypatch) -> None:
    # Only toolkits that actually have a connected account are called, so only
    # those need a pin -- a Shopify-only deployment must still boot.
    monkeypatch.setenv("COMPOSIO_TOOLKIT_VERSION_SHOPIFY", "20260506_00")
    monkeypatch.delenv("COMPOSIO_TOOLKIT_VERSION_QUICKBOOKS", raising=False)
    monkeypatch.delenv("COMPOSIO_TOOLKIT_VERSION_SQUARE", raising=False)

    assert pinned_toolkit_versions({"shopify": "ca_1"}) == {"shopify": "20260506_00"}


# --- per-call deadline (NFR-8) ----------------------------------------------


def test_deadline_defaults_and_overrides(monkeypatch) -> None:
    monkeypatch.delenv("COMPOSIO_DEADLINE_MS", raising=False)
    assert deadline_seconds() == DEFAULT_DEADLINE_MS / 1000
    # Well under the SDK's own 60s default, which is longer than a whole SMS turn.
    assert DEFAULT_DEADLINE_MS <= 15_000

    monkeypatch.setenv("COMPOSIO_DEADLINE_MS", "2500")
    assert deadline_seconds() == 2.5

    # A typo must not silently remove the bound.
    monkeypatch.setenv("COMPOSIO_DEADLINE_MS", "soon")
    assert deadline_seconds() == DEFAULT_DEADLINE_MS / 1000
