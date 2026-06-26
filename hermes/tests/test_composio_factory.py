"""build_composio_driver() env wiring (ADR-0136/0137).

The factory is the only place that touches the optional Composio SDK (lazy import),
so importing ``toee_hermes`` stays dependency-free. A missing ``COMPOSIO_API_KEY``
is a governed configuration failure, never a raw crash, and the SDK is never
imported when the env is not configured.
"""

from __future__ import annotations

import importlib.util

import pytest

from toee_hermes.drivers.composio import build_composio_driver
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

    with pytest.raises(ToolDriverError) as excinfo:
        build_composio_driver()

    assert excinfo.value.error_class == "configuration_missing"
