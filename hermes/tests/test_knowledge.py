"""toee_knowledge_search mock handlers (ports mock/knowledge.test.ts).

Covers Public Site Knowledge search and Required Operational Policy Slot lookup
(ADR-0003, ADR-0067). An empty or unpublished slot must yield the governed
no-policy fallback (``found: false`` with empty content), never improvised
policy. Every handler is exercised through ``execute_tool`` so the governed
dispatch boundary is covered end-to-end.
"""

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.knowledge import (
    KnowledgeMockData,
    create_knowledge_mock_handlers,
    knowledge_baseline_data,
)
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external")


def _call(action: str, params: dict, handlers=None):
    registry = handlers if handlers is not None else create_knowledge_mock_handlers()
    return execute_tool(
        tool="toee_knowledge_search",
        action=action,
        params=params,
        context=_ctx(),
        driver=MockDriver(registry),
    )


# --- search_operational_policy ------------------------------------------------


def test_operational_policy_empty_slot_is_governed_no_policy_fallback() -> None:
    result = _call(
        "search_operational_policy", {"slot": "business_hours_service_boundaries"}
    )

    assert result.ok is True
    assert result.data == {
        "slot": "business_hours_service_boundaries",
        "content": "",
        "found": False,
    }


def test_operational_policy_returns_injected_published_content() -> None:
    handlers = create_knowledge_mock_handlers(
        KnowledgeMockData(
            operational_policy={
                "business_hours_service_boundaries": "Open Mon-Fri 9-5 ET."
            },
            public_site=knowledge_baseline_data.public_site,
        )
    )

    result = _call(
        "search_operational_policy",
        {"slot": "business_hours_service_boundaries"},
        handlers=handlers,
    )

    assert result.ok is True
    assert result.data == {
        "slot": "business_hours_service_boundaries",
        "content": "Open Mon-Fri 9-5 ET.",
        "found": True,
    }


def test_operational_policy_resolves_slot_from_query_alias() -> None:
    handlers = create_knowledge_mock_handlers(
        KnowledgeMockData(
            operational_policy={"payment_payment_link_rules": "Card on file only."},
            public_site=[],
        )
    )

    result = _call(
        "search_operational_policy",
        {"query": "payment_payment_link_rules"},
        handlers=handlers,
    )

    assert result.ok is True
    assert result.data == {
        "slot": "payment_payment_link_rules",
        "content": "Card on file only.",
        "found": True,
    }


def test_operational_policy_no_slot_or_query_yields_null_slot_fallback() -> None:
    result = _call("search_operational_policy", {})

    assert result.data == {"slot": None, "content": "", "found": False}


def test_operational_policy_empty_string_slot_is_preserved_not_treated_as_missing() -> None:
    # readStringParam returns "" (not undefined) for an empty string, so the
    # query alias is NOT consulted and the empty slot is echoed back verbatim.
    result = _call(
        "search_operational_policy",
        {"slot": "", "query": "payment_payment_link_rules"},
    )

    assert result.data == {"slot": "", "content": "", "found": False}


# --- search_public_site -------------------------------------------------------


def test_public_site_returns_deterministic_non_empty_baseline() -> None:
    first = _call("search_public_site", {})
    second = _call("search_public_site", {})

    assert first.ok is True
    assert second.ok is True
    assert first.data == second.data
    assert isinstance(first.data["results"], list)
    assert len(first.data["results"]) > 0


def test_public_site_baseline_results_use_snake_case_entry_keys() -> None:
    result = _call("search_public_site", {})

    assert result.data["results"][0] == {
        "title": "Contact & Store Hours",
        "url": "https://www.toeetire.com/pages/contact",
        "snippet": "How to reach Toee Tire support and current service hours.",
    }


def test_public_site_filters_by_case_insensitive_query() -> None:
    handlers = create_knowledge_mock_handlers(
        KnowledgeMockData(
            operational_policy={},
            public_site=[
                {
                    "title": "Store Hours",
                    "url": "https://example.test/hours",
                    "snippet": "We are open daily.",
                },
                {
                    "title": "Shipping",
                    "url": "https://example.test/shipping",
                    "snippet": "Ships in 2 days.",
                },
            ],
        )
    )

    result = _call("search_public_site", {"query": "HOURS"}, handlers=handlers)

    assert result.ok is True
    assert result.data == {
        "results": [
            {
                "title": "Store Hours",
                "url": "https://example.test/hours",
                "snippet": "We are open daily.",
            }
        ]
    }


def test_public_site_whitespace_only_query_returns_full_corpus() -> None:
    # "   ".strip() -> "" which mirrors an omitted query and returns everything.
    result = _call("search_public_site", {"query": "   "})

    assert len(result.data["results"]) == len(knowledge_baseline_data.public_site)


def test_public_site_results_are_copies_not_baseline_references() -> None:
    result = _call("search_public_site", {})
    result.data["results"][0]["title"] = "MUTATED"

    again = _call("search_public_site", {})

    assert again.data["results"][0]["title"] == "Contact & Store Hours"
