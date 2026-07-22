"""The Composio SDK call surface the driver is pinned to (0.0.4 S12, FR-18).

`_ComposioSdkClient` is the one place in the repo that calls the vendor SDK, and
it cannot be unit-tested through: exercising it needs an API key and network.
What CAN be checked without either is that the surface it was pinned against is
still the surface the installed SDK exposes -- so this introspects the real
`composio` package (a hermes-runtime dependency) and fails the day an upgrade
moves the method, renames an argument, or changes the response envelope.

That is the whole point of "pinned": the driver stops guessing at staging-smoke
time and starts failing in CI instead.
"""

from __future__ import annotations

import inspect

import pytest

composio = pytest.importorskip("composio", reason="composio SDK not installed")

from composio.core.models.tools import Tools, ToolExecutionResponse  # noqa: E402
from toee_hermes.drivers.composio.driver import _ComposioSdkClient  # noqa: E402


def test_tools_execute_signature_is_what_the_driver_calls() -> None:
    params = inspect.signature(Tools.execute).parameters

    # The driver calls tools.execute(slug, arguments, connected_account_id=..., user_id=...)
    positional = [
        name
        for name, p in params.items()
        if name != "self" and p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    ]
    assert positional == ["slug", "arguments"]

    for name in ("connected_account_id", "user_id", "version"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name


def test_response_envelope_is_the_three_keys_the_driver_reads() -> None:
    # ToolExecutionResponse is a TypedDict the SDK model_dump()s into, so the
    # driver reads it as a plain dict: successful / error / data.
    assert set(ToolExecutionResponse.__annotations__) == {"data", "error", "successful"}


def test_unpinned_toolkit_version_raises_in_the_sdk() -> None:
    # Why pinned_toolkit_versions() fails closed at boot: left unpinned, the SDK
    # resolves "latest" and raises this from inside execute(), mid-turn.
    from composio.exceptions import ToolVersionRequiredError

    assert issubclass(ToolVersionRequiredError, Exception)
    source = inspect.getsource(Tools._execute_tool)
    assert "ToolVersionRequiredError()" in source


def test_driver_client_translates_an_unsuccessful_envelope() -> None:
    from toee_hermes.errors import ToolDriverError

    class _Sdk:
        class tools:  # noqa: N801 - mirrors the SDK attribute name
            @staticmethod
            def execute(slug, arguments, *, connected_account_id=None, user_id=None):
                return {"data": {}, "error": "connection expired", "successful": False}

    with pytest.raises(ToolDriverError) as excinfo:
        _ComposioSdkClient(_Sdk()).execute_action(
            action="SHOPIFY_GET_PRODUCTS",
            params={},
            connected_account_id="ca_x",
            user_id="u",
        )

    assert excinfo.value.error_class == "composio_api_error"
    # The raw vendor text stays on the exception for logs; dispatch renders the
    # governed Tool Unavailable Response from the error_class (ADR-0136).
    assert "SHOPIFY_GET_PRODUCTS" in str(excinfo.value)


def test_smoke_calls_name_real_mapped_actions() -> None:
    # The smoke script is run by hand from a deployment box, so a typo in
    # SMOKE_CALLS would only surface during a cutover. Cheap to hold here.
    from toee_hermes.drivers.composio import ACTION_MAPPING

    from hermes_runtime.composio_smoke import SMOKE_CALLS

    assert {c.tool for c in SMOKE_CALLS} == {
        "toee_shopify_read",
        "toee_qbo_read",
        "toee_square_payment_link",
    }
    for call in SMOKE_CALLS:
        spec = ACTION_MAPPING[(call.tool, call.action)]
        assert call.gated_off == (spec.unavailable is not None)


def test_driver_client_fails_closed_on_a_missing_data_object() -> None:
    from toee_hermes.errors import ToolDriverError

    class _Sdk:
        class tools:  # noqa: N801
            @staticmethod
            def execute(slug, arguments, *, connected_account_id=None, user_id=None):
                return {"data": None, "error": None, "successful": True}

    with pytest.raises(ToolDriverError) as excinfo:
        _ComposioSdkClient(_Sdk()).execute_action(
            action="QUICKBOOKS_LIST_INVOICES",
            params={},
            connected_account_id="ca_x",
            user_id="u",
        )

    assert excinfo.value.error_class == "composio_api_error"
