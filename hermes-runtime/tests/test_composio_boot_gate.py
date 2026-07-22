"""Every tool-executing process fails at BOOT on a broken Composio config.

0.0.4 S12 fix wave 1, review Finding 4. The driver is built inside
``_build_driver_selector``, which runs per ``boot_profile()`` -- i.e. once per
TURN. So the S12 report's and runbook's claim that a missing toolkit pin "raises
``configuration_missing`` at process boot" was false: the process booted clean and
then threw a raw exception out of ``register_turn`` on the first customer message,
where dispatch expects a governed result.

``require_composio_configuration()`` at each composition root is what makes the
claim true. These tests hold both halves: that the gate fires, and that every
composition root still calls it.
"""

from __future__ import annotations

import inspect
import sys
import types

import pytest

from toee_hermes.errors import ToolDriverError


def _fake_composio_sdk(monkeypatch) -> None:
    """Stand in for the optional SDK so the gate can be exercised without it."""

    class _Composio:
        def __init__(self, **kwargs) -> None:
            pass

    module = types.ModuleType("composio")
    module.Composio = _Composio  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "composio", module)


def test_dispatch_server_refuses_to_boot_on_a_missing_pin(monkeypatch) -> None:
    from hermes_runtime.tool_dispatch_composition import build_tool_dispatch_app

    _fake_composio_sdk(monkeypatch)
    monkeypatch.setenv("TOEE_HERMES_PROFILE", "internal_copilot")
    monkeypatch.setenv("DISPATCH_API_TOKEN", "dev-copilot-token")
    monkeypatch.setenv("INTEGRATION_DRIVER", "composio")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_test_not_used_for_network")
    monkeypatch.setenv("COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID", "ca_shopify")
    monkeypatch.delenv("COMPOSIO_TOOLKIT_VERSION_SHOPIFY", raising=False)

    with pytest.raises(ToolDriverError) as excinfo:
        build_tool_dispatch_app()

    assert excinfo.value.error_class == "configuration_missing"
    assert "COMPOSIO_TOOLKIT_VERSION_SHOPIFY" in str(excinfo.value)


def test_every_composition_root_calls_the_boot_gate() -> None:
    """The five deployed processes come from four composition roots.

    A root that forgets the call is a process that goes back to failing on the
    first customer turn -- silently, because nothing else would notice.
    """
    from hermes_runtime import (
        background_worker,
        gateway_composition,
        tool_dispatch_composition,
        turn_worker,
    )

    roots = {
        "build_gateway_app": gateway_composition.build_gateway_app,
        "turn_worker.main": turn_worker.main,
        "background_worker.main": background_worker.main,
        "build_tool_dispatch_app": tool_dispatch_composition.build_tool_dispatch_app,
    }
    for name, fn in roots.items():
        assert "require_composio_configuration()" in inspect.getsource(fn), name
