"""Shopify ingress identity fallback: missing-tool detection + scan bound (ADR-0128)."""

from __future__ import annotations

import time

from hermes_runtime.datastore import shopify_identity
from hermes_runtime.datastore.shopify_identity import _SEARCH_ACTION, _PAGE_SIZE
from toee_hermes.errors import ToolDriverError


def test_is_missing_search_tool_requires_the_action_name() -> None:
    # A generic vendor "not found" (e.g. no customer) must NOT be read as
    # "search tool absent" — that would trigger a full catalog scan.
    generic = ToolDriverError("composio_api_error", "Resource not found for id 42")
    assert shopify_identity._is_missing_search_tool(generic) is False

    tool_missing = ToolDriverError(
        "composio_api_error",
        f"Action {_SEARCH_ACTION} not found in toolkit",
    )
    assert shopify_identity._is_missing_search_tool(tool_missing) is True

    # "tool_execution_failed" style noise must not count as a missing tool.
    noisy = ToolDriverError("composio_api_error", "tool_execution_failed: upstream 500")
    assert shopify_identity._is_missing_search_tool(noisy) is False


def test_pagination_scan_is_bounded(monkeypatch) -> None:
    calls = {"n": 0}

    def _full_page_no_match(action: str, params: dict) -> dict:
        calls["n"] += 1
        base = calls["n"] * 100_000
        return {
            "customers": [
                {"id": base + i, "phone": "+15550000000"} for i in range(_PAGE_SIZE)
            ]
        }

    monkeypatch.setattr(shopify_identity, "_execute_shopify", _full_page_no_match)

    result = shopify_identity._lookup_via_pagination("+19999999999")

    assert result == []
    # Bounded: stops at the page cap instead of scanning the whole catalog forever.
    assert calls["n"] == shopify_identity._MAX_SCAN_PAGES


def test_scan_also_stops_at_the_aggregate_ack_budget(monkeypatch) -> None:
    """The page cap is not an ack budget; wall clock is (S12 fix wave 1, Finding 3).

    Identity resolves before ``persist_accepted_inbound`` returns the provider's
    200, so this scan sits on the webhook ack path. 40 pages x an 8 s per-call
    deadline is ~320 s -- the page cap alone bounds the number of calls, not the
    time they take.
    """
    calls = {"n": 0}

    def _slow_full_page(action: str, params: dict) -> dict:
        calls["n"] += 1
        time.sleep(0.03)
        base = calls["n"] * 100_000
        return {
            "customers": [
                {"id": base + i, "phone": "+15550000000"} for i in range(_PAGE_SIZE)
            ]
        }

    monkeypatch.setattr(shopify_identity, "_execute_shopify", _slow_full_page)
    monkeypatch.setattr(shopify_identity, "_lookup_budget_s", lambda: 0.05)

    result = shopify_identity._lookup_via_pagination("+19999999999")

    assert result == []
    assert 0 < calls["n"] < shopify_identity._MAX_SCAN_PAGES


def test_lookup_budget_tracks_the_composio_deadline(monkeypatch) -> None:
    # One knob, not two: the ack budget is stated in units of the per-call deadline
    # the operator already tunes.
    monkeypatch.setenv("COMPOSIO_DEADLINE_MS", "5000")

    assert shopify_identity._lookup_budget_s() == 10.0
