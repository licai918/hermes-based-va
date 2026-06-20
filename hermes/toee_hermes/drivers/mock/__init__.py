"""Mock driver and per-tool handler fragments (ADR-0137).

Each ``toee_*`` tool contributes a registry fragment; :func:`create_all_mock_handlers`
merges them into the single registry a :class:`MockDriver` serves for local dev and
the Launch Eval runner.
"""

from .driver import (
    MockDriver,
    MockHandler,
    MockHandlerRegistry,
    merge_registries,
)
from .easyroutes import (
    EasyroutesMockData,
    create_easyroutes_mock_handlers,
    easyroutes_baseline_data,
)
from .identity import (
    IdentityMockData,
    create_identity_mock_handlers,
    identity_baseline_data,
)
from .knowledge import (
    KnowledgeMockData,
    create_knowledge_mock_handlers,
    knowledge_baseline_data,
)
from .qbo import (
    QboMockData,
    create_qbo_mock_handlers,
    qbo_baseline_data,
)
from .shopify import (
    ShopifyMockData,
    create_shopify_mock_handlers,
    shopify_baseline_data,
)


def create_all_mock_handlers() -> MockHandlerRegistry:
    """Merge every tool's baseline mock fragment into one registry."""
    return merge_registries(
        create_identity_mock_handlers(),
        create_shopify_mock_handlers(),
        create_qbo_mock_handlers(),
        create_easyroutes_mock_handlers(),
        create_knowledge_mock_handlers(),
    )


__all__ = [
    "MockDriver",
    "MockHandler",
    "MockHandlerRegistry",
    "merge_registries",
    "create_all_mock_handlers",
    "IdentityMockData",
    "create_identity_mock_handlers",
    "identity_baseline_data",
    "ShopifyMockData",
    "create_shopify_mock_handlers",
    "shopify_baseline_data",
    "QboMockData",
    "create_qbo_mock_handlers",
    "qbo_baseline_data",
    "EasyroutesMockData",
    "create_easyroutes_mock_handlers",
    "easyroutes_baseline_data",
    "KnowledgeMockData",
    "create_knowledge_mock_handlers",
    "knowledge_baseline_data",
]
