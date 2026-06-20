"""Mock handlers for ``toee_knowledge_search`` (ports mock/knowledge.ts, ADR-0067).

Serves Public Site Knowledge search and Required Operational Policy Slot lookups
(ADR-0003). Every Required Operational Policy Slot starts unfilled, so
``search_operational_policy`` returns the governed no-policy fallback
(``found: False`` with empty content) rather than improvised policy until a later
slice injects published content.

``eval/mocks/base.yaml`` carries no ``knowledge`` section, so the baseline mirrors
the inline ``knowledgeBaselineData`` from the TypeScript source: empty operational
policy plus two neutral Public Site placeholder entries. Data is injectable so the
Launch Eval fixture loader can override the baseline per scenario.

Every response is a pure function of ``(data, params)`` -- no clocks, randomness,
or external calls -- so eval runs and BFF slices get stable, ordered shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .driver import MockHandlerRegistry


@dataclass(frozen=True)
class KnowledgeMockData:
    # Required Operational Policy Slot (ADR-0003) -> Published Operational Policy
    # content. A missing or empty slot yields the governed no-policy fallback.
    operational_policy: dict[str, str] = field(default_factory=dict)
    # Deterministic Public Site Knowledge corpus. Each entry carries title, url,
    # and snippet (rebuilt from Shopify Knowledge Sync + Tavily Gap Crawl).
    public_site: list[dict[str, str]] = field(default_factory=list)


# Baseline mirrors the TS inline default: every operational policy slot unfilled
# (ADR-0003) so the safe no-policy fallback holds, and a couple of neutral Public
# Site placeholder entries.
knowledge_baseline_data = KnowledgeMockData(
    operational_policy={},
    public_site=[
        {
            "title": "Contact & Store Hours",
            "url": "https://www.toeetire.com/pages/contact",
            "snippet": "How to reach Toee Tire support and current service hours.",
        },
        {
            "title": "Shipping & Delivery",
            "url": "https://www.toeetire.com/pages/shipping",
            "snippet": "Overview of order delivery options and timelines.",
        },
    ],
)


def _read_string_param(params: dict[str, Any], key: str) -> str | None:
    """Return the param as a string when present (echoing ``""`` verbatim).

    Mirrors the TS ``readStringParam``: only a non-string (or absent) value is
    treated as missing, so an empty string is a real, preserved value.
    """
    value = params.get(key)
    return value if isinstance(value, str) else None


def _search_operational_policy(
    data: KnowledgeMockData, params: dict[str, Any]
) -> dict[str, Any]:
    slot = _read_string_param(params, "slot")
    if slot is None:
        slot = _read_string_param(params, "query")
    content = data.operational_policy.get(slot, "") if slot is not None else ""
    return {"slot": slot, "content": content, "found": len(content) > 0}


def _search_public_site(
    data: KnowledgeMockData, params: dict[str, Any]
) -> dict[str, Any]:
    query = _read_string_param(params, "query")
    normalized = query.strip().lower() if query is not None else None
    if not normalized:
        results = data.public_site
    else:
        results = [
            entry
            for entry in data.public_site
            if normalized in f"{entry['title']} {entry['snippet']}".lower()
        ]
    return {"results": [dict(entry) for entry in results]}


def create_knowledge_mock_handlers(
    data: KnowledgeMockData = knowledge_baseline_data,
) -> MockHandlerRegistry:
    """Build the registry fragment bound to a specific knowledge data set.

    The Launch Eval fixture loader passes per-scenario data; the default uses the
    inline baseline (knowledge reads are stateless, so sharing it is safe).
    """
    # Handlers take ``(params, context)`` to match the driver's call convention;
    # knowledge search is identity-agnostic, so ``context`` is intentionally unused.
    return {
        "toee_knowledge_search": {
            "search_public_site": (
                lambda params, context: _search_public_site(data, params)
            ),
            "search_operational_policy": (
                lambda params, context: _search_operational_policy(data, params)
            ),
        }
    }
