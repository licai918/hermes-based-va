"""Integration backend selection (ports driver.ts).

Local dev and eval default to ``mock``; ``composio`` and ``rest`` are wired per
ADR-0132 and ADR-0137.
"""

from __future__ import annotations

import os
from typing import Literal

# Driver kinds an audit record can attribute a tool call to. "datastore" is the
# Postgres system-of-record driver (ADR-0140), wired in the hermes-runtime
# embedding; it is intentionally NOT a KNOWN_DRIVERS value because it is selected
# on a separate axis from the external-vendor INTEGRATION_DRIVER backend.
IntegrationDriver = Literal["mock", "composio", "rest", "datastore"]

# Valid INTEGRATION_DRIVER env values (the external vendor backend, ADR-0137).
KNOWN_DRIVERS: tuple[IntegrationDriver, ...] = ("mock", "composio", "rest")

_UNSET = object()


def resolve_integration_driver(value: object = _UNSET) -> IntegrationDriver:
    """Resolve the configured driver, defaulting to ``mock`` when unset/empty.

    An unrecognized non-empty value is a configuration error and raises
    (ADR-0137).
    """
    if value is _UNSET:
        value = os.environ.get("INTEGRATION_DRIVER")

    if value is None or value == "":
        return "mock"

    if value in KNOWN_DRIVERS:
        return value  # type: ignore[return-value]

    raise ValueError(
        f'Unknown INTEGRATION_DRIVER "{value}". '
        f"Expected one of: {', '.join(KNOWN_DRIVERS)}."
    )
