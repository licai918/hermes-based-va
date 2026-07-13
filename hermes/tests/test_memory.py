"""Mock handlers for ``toee_customer_memory`` (ports mock/memory.test.ts).

Exercises the v1 Customer Memory actions (ADR-0114: ``upsert_preference``,
``clear_preference``, ``get_preferences``) end-to-end through ``execute_tool`` so
the governed boundary is covered. Asserts the fixed four-slot rule (ADR-0111),
identity-binding isolation (verified ``shopify_customer_id`` vs the provisional
channel binding of ADR-0112), and the lightweight injection read path (ADR-0113).
"""

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.memory import (
    MemoryMockData,
    create_memory_mock_handlers,
)
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

VERIFIED_CUSTOMER_ID = "gid://shopify/Customer/1001"


def _driver(
    data: MemoryMockData | None = None,
    *,
    evidence_store: dict[str, dict[str, str]] | None = None,
) -> MockDriver:
    handlers = (
        create_memory_mock_handlers(evidence_store=evidence_store)
        if data is None
        else create_memory_mock_handlers(data, evidence_store=evidence_store)
    )
    return MockDriver(handlers)


def _verified_ctx(shopify_customer_id: str = VERIFIED_CUSTOMER_ID) -> ToolExecutionContext:
    return ToolExecutionContext(
        profile="customer_service_external",
        identity={
            "outcome": "verified_customer",
            "shopify_customer_id": shopify_customer_id,
            "company_name": "Acme Fleet",
        },
    )


def _unmatched_ctx() -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external", identity=None)


def _provisional_ctx(channel_identity: str, channel: str = "sms") -> ToolExecutionContext:
    # S01: the caller's ingress-controlled channel identity rides context.identity,
    # never a model-supplied tool param.
    return ToolExecutionContext(
        profile="customer_service_external",
        identity={"channel": channel, "channel_identity": channel_identity},
    )


def _call(driver: MockDriver, action: str, params: dict, context: ToolExecutionContext):
    return execute_tool(
        tool="toee_customer_memory",
        action=action,
        params=params,
        context=context,
        driver=driver,
    )


# --- upsert_preference -----------------------------------------------------


def test_upsert_records_explicit_preference() -> None:
    result = _call(
        _driver(),
        "upsert_preference",
        {
            "key": "contact_time_preference",
            "value": "after 2pm Eastern",
        },
        _verified_ctx(),
    )

    assert result.ok is True
    assert result.data["slot"] == "contact_time_preference"
    assert result.data["value"] == "after 2pm Eastern"
    assert result.data["source"] == "customer_explicit"
    assert result.data["stored"] is True
    assert result.data["binding_key"] == VERIFIED_CUSTOMER_ID


def test_upsert_then_get_reflects_it() -> None:
    driver = _driver()
    ctx = _verified_ctx()

    _call(
        driver,
        "upsert_preference",
        {
            "key": "contact_time_preference",
            "value": "after 2pm Eastern",
        },
        ctx,
    )
    read = _call(driver, "get_preferences", {}, ctx)

    assert read.ok is True
    assert read.data["preferences"] == {"contact_time_preference": "after 2pm Eastern"}


def test_upsert_rejects_open_ended_key() -> None:
    result = _call(
        _driver(),
        "upsert_preference",
        {
            "key": "favorite_color",
            "value": "blue",
        },
        _verified_ctx(),
    )

    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_upsert_rejects_non_string_value() -> None:
    result = _call(
        _driver(),
        "upsert_preference",
        {"key": "channel_preference", "value": 123},
        _verified_ctx(),
    )

    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_slot_alias_is_accepted() -> None:
    driver = _driver()
    ctx = _verified_ctx()

    result = _call(
        driver,
        "upsert_preference",
        {
            "slot": "communication_style_note",
            "value": "prefers brief replies",
        },
        ctx,
    )
    assert result.ok is True
    assert result.data["slot"] == "communication_style_note"

    read = _call(driver, "get_preferences", {}, ctx)
    assert read.data["preferences"]["communication_style_note"] == "prefers brief replies"


# --- get_preferences -------------------------------------------------------


def test_get_empty_without_explicit_write() -> None:
    read = _call(_driver(), "get_preferences", {}, _verified_ctx())

    assert read.ok is True
    assert read.data["preferences"] == {}


def test_get_honors_injected_baseline() -> None:
    driver = _driver(
        MemoryMockData(preferences={"contact_time_preference": "after 2pm Eastern"})
    )

    read = _call(driver, "get_preferences", {}, _verified_ctx())

    assert read.ok is True
    assert read.data["preferences"] == {"contact_time_preference": "after 2pm Eastern"}


def test_get_preferences_returns_independent_copy() -> None:
    driver = _driver(MemoryMockData(preferences={"channel_preference": "email"}))
    ctx = _verified_ctx()

    first = _call(driver, "get_preferences", {}, ctx)
    first.data["preferences"]["channel_preference"] = "MUTATED"

    second = _call(driver, "get_preferences", {}, ctx)
    assert second.data["preferences"]["channel_preference"] == "email"


# --- clear_preference ------------------------------------------------------


def test_clear_acknowledges_removal() -> None:
    driver = _driver(MemoryMockData(preferences={"channel_preference": "sms"}))
    ctx = _verified_ctx()

    cleared = _call(driver, "clear_preference", {"key": "channel_preference"}, ctx)
    assert cleared.ok is True
    assert cleared.data["slot"] == "channel_preference"
    assert cleared.data["cleared"] is True

    read = _call(driver, "get_preferences", {}, ctx)
    assert read.data["preferences"] == {}


def test_clear_missing_slot_is_idempotent() -> None:
    cleared = _call(
        _driver(), "clear_preference", {"key": "channel_preference"}, _verified_ctx()
    )

    assert cleared.ok is True
    assert cleared.data["cleared"] is True


def test_clear_rejects_open_ended_key() -> None:
    result = _call(
        _driver(), "clear_preference", {"key": "favorite_color"}, _verified_ctx()
    )

    assert result.ok is False
    assert result.error_class == "unexpected_error"


# --- round-trip ------------------------------------------------------------


def test_round_trip_upsert_get_clear_get() -> None:
    driver = _driver()
    ctx = _verified_ctx()

    upsert = _call(
        driver,
        "upsert_preference",
        {
            "key": "delivery_habit_note",
            "value": "leave at side door",
        },
        ctx,
    )
    assert upsert.ok is True
    assert upsert.data["stored"] is True

    after_upsert = _call(driver, "get_preferences", {}, ctx)
    assert after_upsert.data["preferences"]["delivery_habit_note"] == "leave at side door"

    cleared = _call(driver, "clear_preference", {"key": "delivery_habit_note"}, ctx)
    assert cleared.ok is True
    assert cleared.data["cleared"] is True

    after_clear = _call(driver, "get_preferences", {}, ctx)
    assert after_clear.data["preferences"] == {}


# --- identity binding isolation (ADR-0112) ---------------------------------


def test_writes_isolated_by_verified_binding() -> None:
    driver = _driver()

    _call(
        driver,
        "upsert_preference",
        {
            "key": "contact_time_preference",
            "value": "mornings",
        },
        _verified_ctx("gid://shopify/Customer/1001"),
    )

    other = _call(driver, "get_preferences", {}, _verified_ctx("gid://shopify/Customer/2002"))
    assert other.ok is True
    assert other.data["preferences"] == {}


def test_provisional_binding_uses_channel_identity_from_context() -> None:
    # S02: binding derives from context (S01 ingress identity), never a
    # model-supplied ``channel_identity_id`` param, on the external profile.
    driver = _driver()
    ctx = _provisional_ctx("+14165550999")

    upsert = _call(
        driver,
        "upsert_preference",
        {
            "key": "channel_preference",
            "value": "sms",
        },
        ctx,
    )
    assert upsert.ok is True
    assert upsert.data["binding_key"] == "provisional:sms:+14165550999"

    read = _call(driver, "get_preferences", {}, ctx)
    assert read.data["preferences"]["channel_preference"] == "sms"


def test_provisional_bindings_isolated_by_channel_identity() -> None:
    driver = _driver()

    _call(
        driver,
        "upsert_preference",
        {
            "key": "channel_preference",
            "value": "sms",
        },
        _provisional_ctx("+14165550001"),
    )

    other = _call(driver, "get_preferences", {}, _provisional_ctx("+14165550002"))
    assert other.data["preferences"] == {}


def test_unmatched_caller_with_no_channel_identity_is_policy_blocked() -> None:
    # R6 fail-closed: no usable channel identity in context => policy_blocked,
    # never the old bare shared "provisional" key (cross-customer leak).
    result = _call(
        _driver(),
        "upsert_preference",
        {
            "key": "channel_preference",
            "value": "sms",
        },
        _unmatched_ctx(),
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_external_profile_channel_identity_id_param_is_ignored() -> None:
    # R6: a model-supplied phone param cannot substitute for context on the
    # external profile — still fail-closed when context has no identity.
    result = _call(
        _driver(),
        "upsert_preference",
        {
            "key": "channel_preference",
            "value": "sms",
            "channel_identity_id": "+19998887777",
        },
        _unmatched_ctx(),
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


# --- write discipline: framework source, value cap, evidence (S03, PRD FR-3) -


def test_upsert_value_at_max_length_is_accepted() -> None:
    result = _call(
        _driver(),
        "upsert_preference",
        {"key": "delivery_habit_note", "value": "x" * 200},
        _verified_ctx(),
    )
    assert result.ok is True


def test_upsert_value_over_max_length_is_rejected() -> None:
    result = _call(
        _driver(),
        "upsert_preference",
        {"key": "delivery_habit_note", "value": "x" * 201},
        _verified_ctx(),
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_upsert_ignores_model_supplied_source_and_uses_framework_value() -> None:
    # RK-1: the model could try to tag an inferred write as customer_explicit
    # (or any other value) via the tool param — the framework must ignore it.
    result = _call(
        _driver(),
        "upsert_preference",
        {
            "key": "channel_preference",
            "value": "sms",
            "source": "employee_confirmed",  # forged: this context is external
        },
        _verified_ctx(),
    )
    assert result.ok is True
    assert result.data["source"] == "customer_explicit"


def test_upsert_internal_copilot_resolves_employee_confirmed() -> None:
    ctx = ToolExecutionContext(profile="internal_copilot", identity=None)
    result = _call(
        _driver(),
        "upsert_preference",
        {
            "key": "channel_preference",
            "value": "sms",
            "channel_identity_id": "case:12345",
        },
        ctx,
    )
    assert result.ok is True
    assert result.data["source"] == "employee_confirmed"


def test_upsert_evidence_is_persisted_and_retrievable() -> None:
    evidence_store: dict[str, dict[str, str]] = {}
    driver = _driver(evidence_store=evidence_store)
    ctx = _verified_ctx()

    result = _call(
        driver,
        "upsert_preference",
        {
            "key": "contact_time_preference",
            "value": "after 2pm Eastern",
            "evidence": "only text me after 2pm eastern please",
        },
        ctx,
    )
    assert result.ok is True
    assert result.data["evidence"] == "only text me after 2pm eastern please"

    # Retrievable: the write survives past the call that made it, not just
    # echoed back in the same response.
    assert (
        evidence_store[VERIFIED_CUSTOMER_ID]["contact_time_preference"]
        == "only text me after 2pm eastern please"
    )


def test_upsert_without_evidence_stores_nothing() -> None:
    evidence_store: dict[str, dict[str, str]] = {}
    driver = _driver(evidence_store=evidence_store)

    result = _call(
        driver,
        "upsert_preference",
        {"key": "channel_preference", "value": "sms"},
        _verified_ctx(),
    )
    assert result.ok is True
    assert result.data["evidence"] is None
    assert evidence_store == {}
