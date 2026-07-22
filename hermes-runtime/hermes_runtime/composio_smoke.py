"""Production smoke for the three Composio Layer 1 tools (0.0.4 S12, FR-18/NFR-8).

    uv run python -m hermes_runtime.composio_smoke

Run it FROM THE DEPLOYMENT ENVIRONMENT (the Cloud Run revision's shell, or a box
carrying the same `hermes-runtime/.env`). It reads real credentials from the
process environment and talks to the live Composio backend -- there is no
recorded or mocked mode, on purpose: a smoke that can pass without a backend is
not evidence of a cutover.

Three phases, each printing one PASS/FAIL/SKIP line per check:

1. **config**   -- INTEGRATION_DRIVER, connected accounts, and the exact toolkit
   version pins. A missing pin fails the driver build (see
   ``pinned_toolkit_versions``), so this phase is what tells the operator which
   env var to set.
2. **surface**  -- every callable slug in ``ACTION_MAPPING`` is resolved against
   the live toolkit AT THE PINNED VERSION. This is the check that catches "the
   pin is a real version, but this action does not exist in it" before a customer
   does -- it is how S12 found that Composio's Square toolkit has no
   create-payment-link action at all.
3. **per-tool** -- happy path (a real governed call through ``execute_tool``,
   asserting the public contract shape) and fail-closed path (the same call with
   the backend unreachable, asserting a governed unavailable result inside the
   driver deadline -- NFR-8 -- and never a mock payload).

Actions the driver deliberately gates off (``ActionSpec.unavailable``) are not
probed; their happy-path check asserts the governed refusal instead. A check that
did not run prints SKIP and never counts as a pass -- the point of this script is
that it cannot be made green without a live backend.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from toee_hermes.drivers.composio import (
    ACTION_MAPPING,
    CONNECTED_ACCOUNT_ENV,
    TOOLKIT_VERSION_ENV,
    build_composio_driver,
    deadline_seconds,
)
from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import execute_tool
from toee_hermes.plugin.profiles import EXTERNAL
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.tool_dispatch_app import profile_allowlist_gate

# An address nothing listens on, so a call attempt fails at connect. Used only by
# the fail-closed phase, which rebuilds the driver against it.
_BLACKHOLE_BASE_URL = "http://127.0.0.1:9"

# Slack over the deadline before we call a "fail-closed" degrade a hang instead.
# Same shape as the knowledge driver's deadline gate.
_DEADLINE_SLACK_S = 2.0


@dataclass
class Check:
    name: str
    ok: Optional[bool]  # None == skipped
    detail: str

    @property
    def label(self) -> str:
        return "SKIP" if self.ok is None else ("PASS" if self.ok else "FAIL")


def _env_customer_id() -> str:
    """The PAC-6 test customer's Shopify gid (``SMOKE_SHOPIFY_CUSTOMER_ID``).

    Deliberately env-supplied and deliberately NOT defaulted: the happy path is
    an identity-scoped read, and defaulting it would point the smoke at whichever
    customer happens to be first in the live store -- a real person's orders.
    """
    return (os.environ.get("SMOKE_SHOPIFY_CUSTOMER_ID") or "").strip()


def _verified_context(customer_id: str) -> ToolExecutionContext:
    return ToolExecutionContext(
        profile=EXTERNAL,
        identity={"outcome": "verified_customer", "shopify_customer_id": customer_id},
        user_id=os.environ.get("COMPOSIO_USER_ID"),
    )


# --- phase 1: config ---------------------------------------------------------


def check_config() -> list[Check]:
    checks: list[Check] = []
    driver_kind = os.environ.get("INTEGRATION_DRIVER") or "(unset -> mock)"
    checks.append(
        Check(
            "INTEGRATION_DRIVER=composio",
            driver_kind == "composio",
            driver_kind,
        )
    )
    checks.append(
        Check("COMPOSIO_API_KEY present", bool(os.environ.get("COMPOSIO_API_KEY")), "")
    )
    for toolkit, env_var in CONNECTED_ACCOUNT_ENV.items():
        checks.append(
            Check(f"{toolkit}: {env_var}", bool(os.environ.get(env_var)), "")
        )
    for toolkit, env_var in TOOLKIT_VERSION_ENV.items():
        pin = (os.environ.get(env_var) or "").strip()
        checks.append(
            Check(
                f"{toolkit}: {env_var}",
                bool(pin) and pin != "latest",
                pin or "(unset)",
            )
        )
    checks.append(
        Check(
            "SMOKE_SHOPIFY_CUSTOMER_ID (PAC-6 test customer)",
            bool(_env_customer_id()),
            _env_customer_id() or "(unset -- happy paths will SKIP)",
        )
    )
    return checks


# --- phase 2: surface --------------------------------------------------------


def check_surface() -> list[Check]:
    """Resolve every mapped action slug against the live toolkit at its pin.

    ``Tools.get_raw_composio_tool_by_slug`` is the same lookup ``execute`` does
    first, so a slug that resolves here is a slug ``execute`` can reach.
    """
    try:
        driver = build_composio_driver()
    except ToolDriverError as err:
        return [Check("build driver", False, str(err))]

    sdk = getattr(driver._client, "_sdk", None)
    if sdk is None:  # pragma: no cover - only when the client seam is faked
        return [Check("sdk client", False, "driver is not backed by the Composio SDK")]

    checks: list[Check] = []
    for (tool, action), spec in sorted(ACTION_MAPPING.items()):
        if spec.unavailable is not None:
            checks.append(
                Check(
                    f"{tool}.{action} -> {spec.action_slug}",
                    None,
                    f"gated off in the driver: {spec.unavailable}",
                )
            )
            continue
        try:
            resolved = sdk.tools.get_raw_composio_tool_by_slug(spec.action_slug)
            toolkit = getattr(getattr(resolved, "toolkit", None), "slug", "?")
            checks.append(
                Check(
                    f"{tool}.{action} -> {spec.action_slug}",
                    True,
                    f"toolkit={toolkit}",
                )
            )
        except Exception as err:  # noqa: BLE001 - any resolution failure is a FAIL
            checks.append(
                Check(
                    f"{tool}.{action} -> {spec.action_slug}",
                    False,
                    f"{type(err).__name__}: {err}",
                )
            )
    return checks


# --- phase 3: per-tool happy path + fail-closed ------------------------------


@dataclass(frozen=True)
class SmokeCall:
    tool: str
    action: str
    params: dict[str, Any]
    shape_ok: Callable[[Any], bool]

    @property
    def gated_off(self) -> bool:
        """True when the driver refuses this action before touching the backend."""
        return ACTION_MAPPING[(self.tool, self.action)].unavailable is not None


def _shopify_orders_shape(data: Any) -> bool:
    return isinstance(data, list) and all(
        isinstance(row, dict) and "order_number" in row and "line_items" in row
        for row in data
    )


def _qbo_invoices_shape(data: Any) -> bool:
    return isinstance(data, list) and all(
        isinstance(row, dict) and "invoice_number" in row and "balance" in row
        for row in data
    )


# One representative action per tool: the identity-scoped list read each tool
# actually serves on a live turn. Both are reads -- there is no write in this
# script, and Square's only action is gated off in the driver anyway.
SMOKE_CALLS: tuple[SmokeCall, ...] = (
    SmokeCall("toee_shopify_read", "list_customer_orders", {}, _shopify_orders_shape),
    SmokeCall("toee_qbo_read", "list_customer_invoices", {}, _qbo_invoices_shape),
    SmokeCall(
        "toee_square_payment_link",
        "send_payment_link",
        {"invoice_number": "SMOKE-1", "amount": 1.0},
        lambda _data: False,  # gated off; a success here would be the bug
    ),
)


def _run_governed(driver: Any, call: SmokeCall, customer_id: str) -> Any:
    return execute_tool(
        tool=call.tool,
        action=call.action,
        context=_verified_context(customer_id),
        driver=driver,
        params=dict(call.params),
        gate=profile_allowlist_gate(EXTERNAL),
    )


def check_happy_paths() -> list[Check]:
    try:
        driver = build_composio_driver()
    except ToolDriverError as err:
        return [Check("build driver", False, str(err))]

    customer_id = _env_customer_id()
    checks: list[Check] = []
    for call in SMOKE_CALLS:
        name = f"{call.tool}.{call.action} happy path"
        if call.gated_off:
            # No customer needed: the driver must refuse before any backend call.
            result = _run_governed(driver, call, customer_id or "gid://shopify/Customer/0")
            checks.append(
                Check(
                    f"{call.tool}.{call.action} refused (gated off)",
                    not result.ok and result.error_class == "configuration_missing",
                    f"{result.error_class}: {result.message}",
                )
            )
            continue
        if not customer_id:
            checks.append(Check(name, None, "SMOKE_SHOPIFY_CUSTOMER_ID unset"))
            continue
        result = _run_governed(driver, call, customer_id)
        if not result.ok:
            checks.append(Check(name, False, f"{result.error_class}: {result.message}"))
        else:
            checks.append(
                Check(
                    name,
                    call.shape_ok(result.data),
                    f"{len(result.data) if isinstance(result.data, list) else 1} row(s)",
                )
            )
    return checks


def check_fail_closed() -> list[Check]:
    """Backend unreachable -> governed unavailable inside the deadline (NFR-8).

    Points the SDK at a dead address rather than mocking the client, so this
    exercises the real timeout/connect path the deadline is supposed to bound.
    Also asserts the result is NOT a mock payload: FR-21's "never a silent
    fallback to mock in production" is the failure mode with teeth.
    """
    customer_id = _env_customer_id() or "gid://shopify/Customer/0"
    deadline = deadline_seconds()
    budget = deadline + _DEADLINE_SLACK_S

    previous = os.environ.get("COMPOSIO_BASE_URL")
    os.environ["COMPOSIO_BASE_URL"] = _BLACKHOLE_BASE_URL
    try:
        try:
            driver = build_composio_driver()
        except ToolDriverError as err:
            return [Check("build driver (blackhole)", False, str(err))]

        mock = MockDriver(create_all_mock_handlers())
        checks: list[Check] = []
        for call in SMOKE_CALLS:
            name = f"{call.tool}.{call.action} fail-closed"
            if call.gated_off:
                # Its refusal is asserted in 3a and never depends on the backend.
                checks.append(Check(name, None, "gated off in the driver"))
                continue
            started = time.monotonic()
            result = _run_governed(driver, call, customer_id)
            elapsed = time.monotonic() - started

            if result.ok:
                checks.append(
                    Check(name, False, f"backend down but result ok=True after {elapsed:.1f}s")
                )
                continue
            if elapsed > budget:
                checks.append(
                    Check(
                        name,
                        False,
                        f"governed {result.error_class} but took {elapsed:.1f}s "
                        f"(deadline {deadline:.1f}s + {_DEADLINE_SLACK_S:.0f}s slack)",
                    )
                )
                continue
            mock_result = _run_governed(mock, call, customer_id)
            if mock_result.ok and result.data == mock_result.data:
                checks.append(Check(name, False, "returned the MOCK payload (FR-21 violation)"))
                continue
            checks.append(
                Check(name, True, f"{result.error_class} in {elapsed:.1f}s (deadline {deadline:.1f}s)")
            )
        return checks
    finally:
        if previous is None:
            os.environ.pop("COMPOSIO_BASE_URL", None)
        else:
            os.environ["COMPOSIO_BASE_URL"] = previous


# --- CLI ---------------------------------------------------------------------


def _print(title: str, checks: Sequence[Check]) -> bool:
    print(f"\n{title}")
    for check in checks:
        detail = f"  -- {check.detail}" if check.detail else ""
        print(f"  [{check.label}] {check.name}{detail}")
    return all(c.ok is not False for c in checks)


def main() -> int:
    print("Composio production smoke (0.0.4 S12) -- live backend, no mock fallback")
    passed = _print("1. config", check_config())
    passed &= _print("2. surface (slugs resolve at the pinned toolkit version)", check_surface())
    passed &= _print("3a. happy path", check_happy_paths())
    passed &= _print("3b. fail-closed (backend unreachable)", check_fail_closed())

    print(f"\nsmoke: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
