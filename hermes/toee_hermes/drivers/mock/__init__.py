"""Mock driver and per-tool handler fragments (ADR-0137).

Each ``toee_*`` tool contributes a registry fragment; :func:`create_all_mock_handlers`
merges them into the single registry a :class:`MockDriver` serves for local dev and
the Launch Eval runner.
"""

from .admin_stubs import create_admin_stub_mock_handlers
from .case import (
    CaseMockData,
    case_baseline_data,
    create_case_mock_handlers,
)
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
from .memory import (
    MemoryMockData,
    create_memory_mock_handlers,
    memory_baseline_data,
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
from .square import (
    SquareMockData,
    create_square_mock_handlers,
    square_baseline_data,
)
from .sms_reply import (
    SmsReplyMockData,
    create_sms_reply_mock_handlers,
    sms_reply_baseline_data,
)


def create_all_mock_handlers() -> MockHandlerRegistry:
    """Merge every tool's baseline mock fragment into one registry (all 15 v1 tools)."""
    return merge_registries(
        create_identity_mock_handlers(),
        create_shopify_mock_handlers(),
        create_qbo_mock_handlers(),
        create_easyroutes_mock_handlers(),
        create_knowledge_mock_handlers(),
        create_case_mock_handlers(),
        create_memory_mock_handlers(),
        create_sms_reply_mock_handlers(),
        create_square_mock_handlers(),
        create_admin_stub_mock_handlers(),
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
    "CaseMockData",
    "create_case_mock_handlers",
    "case_baseline_data",
    "MemoryMockData",
    "create_memory_mock_handlers",
    "memory_baseline_data",
    "SmsReplyMockData",
    "create_sms_reply_mock_handlers",
    "sms_reply_baseline_data",
    "SquareMockData",
    "create_square_mock_handlers",
    "square_baseline_data",
    "create_admin_stub_mock_handlers",
]
