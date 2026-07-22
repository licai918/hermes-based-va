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
import sys
import types

import pytest

from toee_hermes.drivers.composio import (
    CONNECTED_ACCOUNT_ENV,
    TOOLKIT_SLUG,
    TOOLKIT_VERSION_ENV,
    build_composio_driver,
    deadline_seconds,
    pinned_toolkit_versions,
    require_composio_configuration,
)
from toee_hermes.drivers.composio.driver import (
    DEFAULT_DEADLINE_MS,
    _ROUND_TRIPS_PER_EXECUTE,
)
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
    # A connected account must be configured so this test still reaches the SDK
    # import it means to exercise, rather than tripping the (0.0.4 S12 fix wave
    # 2) zero-connected-account boot gate first.
    monkeypatch.setenv("COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID", "ca_shopify")
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


def _fake_composio_sdk(monkeypatch) -> dict:
    """Swap the optional SDK for a constructor that records its kwargs."""
    captured: dict = {}

    class _Composio:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    module = types.ModuleType("composio")
    module.Composio = _Composio  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "composio", module)
    return captured


def test_sdk_timeout_divides_the_deadline_across_the_round_trips(monkeypatch) -> None:
    """NFR-8 bounds one TOOL CALL; the SDK ``timeout`` bounds one HTTP REQUEST.

    ``Tools.execute`` makes three HTTP requests (schema retrieve, a second
    *uncached* retrieve inside ``_execute_tool``, then the vendor call), so passing
    the whole deadline made the real per-call bound 3x the advertised one --
    24 s at the 8 s default (0.0.4 S12 fix wave 1, review Finding 2).
    """
    captured = _fake_composio_sdk(monkeypatch)
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_test_not_used_for_network")
    monkeypatch.setenv("COMPOSIO_DEADLINE_MS", "9000")
    # A connected account is required since 0.0.4 S12 fix wave 2 (a driver with
    # zero connected accounts now fails closed at boot instead of building).
    monkeypatch.setenv("COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID", "ca_shopify")
    for env_var in TOOLKIT_VERSION_ENV.values():
        monkeypatch.setenv(env_var, "20260506_00")

    build_composio_driver()

    # Retries would make the deadline per-ATTEMPT instead of per-call.
    assert captured["max_retries"] == 0
    assert captured["timeout"] == pytest.approx(9.0 / _ROUND_TRIPS_PER_EXECUTE)
    # The property that matters: worst case for one execute_action <= the deadline.
    assert captured["timeout"] * _ROUND_TRIPS_PER_EXECUTE == pytest.approx(
        deadline_seconds()
    )


# --- boot gate (review Finding 4) --------------------------------------------


def test_require_composio_configuration_is_a_noop_off_composio(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATION_DRIVER", "mock")
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)

    require_composio_configuration()  # must not raise: mock deployments boot clean


def test_require_composio_configuration_fails_on_a_missing_pin(monkeypatch) -> None:
    # The whole point: this runs at process boot, so the operator reading the
    # message is the one who can fix it. Before it existed, build_composio_driver
    # was only reached per boot_profile() -- per TURN -- and this ToolDriverError
    # escaped register_turn as a raw exception on the first customer message.
    _fake_composio_sdk(monkeypatch)
    monkeypatch.setenv("INTEGRATION_DRIVER", "composio")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_test_not_used_for_network")
    monkeypatch.setenv("COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID", "ca_shopify")
    monkeypatch.delenv("COMPOSIO_TOOLKIT_VERSION_SHOPIFY", raising=False)

    with pytest.raises(ToolDriverError) as excinfo:
        require_composio_configuration()

    assert excinfo.value.error_class == "configuration_missing"
    assert "COMPOSIO_TOOLKIT_VERSION_SHOPIFY" in str(excinfo.value)


def test_require_composio_configuration_fails_on_zero_connected_accounts(
    monkeypatch,
) -> None:
    """0.0.4 S12 fix wave 2, review Finding 5.

    ``INTEGRATION_DRIVER=composio`` with every ``*_CONNECTED_ACCOUNT_ID`` unset
    used to boot clean: ``pinned_toolkit_versions({})`` iterates nothing, finds
    nothing missing, and the process starts with a driver that cannot serve a
    single tool call. A Composio driver connected to no vendor account is
    unusable, so this now fails closed at boot instead of on the first call.
    """
    _fake_composio_sdk(monkeypatch)
    monkeypatch.setenv("INTEGRATION_DRIVER", "composio")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_test_not_used_for_network")
    for env_var in CONNECTED_ACCOUNT_ENV.values():
        monkeypatch.delenv(env_var, raising=False)

    with pytest.raises(ToolDriverError) as excinfo:
        require_composio_configuration()

    assert excinfo.value.error_class == "configuration_missing"
    assert "connected account" in str(excinfo.value)
