"""Composio Layer 1 driver package (ADR-0127/0128/0130/0132/0136/0137).

Importing this package must NOT import the ``composio`` SDK; only
:func:`build_composio_driver` touches it lazily, so ``toee_hermes`` stays
dependency-free and importable anywhere (ADR-0137).
"""

from .driver import (
    ACTION_MAPPING,
    COMPOSIO_LAYER1_TOOLS,
    CONNECTED_ACCOUNT_ENV,
    ActionSpec,
    ComposioClient,
    ComposioDriver,
    build_composio_driver,
)

__all__ = [
    "ACTION_MAPPING",
    "COMPOSIO_LAYER1_TOOLS",
    "CONNECTED_ACCOUNT_ENV",
    "ActionSpec",
    "ComposioClient",
    "ComposioDriver",
    "build_composio_driver",
]
