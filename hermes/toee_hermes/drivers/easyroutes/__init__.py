"""EasyRoutes direct REST driver package (FR-20/21, NFR-6/8).

Importing this package pulls in only stdlib (``urllib``) — the direct REST client
needs no SDK, so ``toee_hermes`` stays dependency-free and importable anywhere
(mirrors the Composio package's discipline, ADR-0137).
"""

from .driver import (
    API_BASE_ENV,
    API_TOKEN_ENV,
    CLIENT_ID_ENV,
    DEADLINE_ENV,
    EASYROUTES_READ_TOOL,
    EasyroutesClient,
    EasyroutesDriver,
    build_easyroutes_driver,
    easyroutes_configured,
)

__all__ = [
    "API_BASE_ENV",
    "API_TOKEN_ENV",
    "CLIENT_ID_ENV",
    "DEADLINE_ENV",
    "EASYROUTES_READ_TOOL",
    "EasyroutesClient",
    "EasyroutesDriver",
    "build_easyroutes_driver",
    "easyroutes_configured",
]
