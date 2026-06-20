"""Mock ``toee_case`` handlers (ports mock/case.test.ts, ADR-0064).

The External Customer Service Profile opens Follow-up Cases (``create_case``) and
adjusts urgency / contact reason on an open case (``update_case``). The case id is
a deterministic FNV-1a hash of the request params (no randomness, no clock) so the
Launch Eval runner can assert a case was created without network access. Exercised
through ``execute_tool`` so the governed boundary is covered end-to-end.
"""

import re

from toee_hermes.drivers.mock.case import CaseMockData, create_case_mock_handlers
from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

_CASE_ID_PATTERN = re.compile(r"case_[0-9a-f]{8}")


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external")


def _call(action: str, params: dict, *, data: CaseMockData | None = None):
    handlers = (
        create_case_mock_handlers() if data is None else create_case_mock_handlers(data)
    )
    return execute_tool(
        tool="toee_case",
        action=action,
        params=params,
        context=_ctx(),
        driver=MockDriver(handlers),
    )


def test_create_case_returns_open_case_echoing_contact_reason() -> None:
    result = _call(
        "create_case",
        {
            "contact_reason": "billing_question",
            "summary": "Customer asked about invoice INV-9001",
            "channel_thread_id": "conv_1",
        },
    )

    assert result.ok is True
    assert result.data["status"] == "open"
    assert result.data["contact_reason"] == "billing_question"
    assert result.data["channel_thread_id"] == "conv_1"
    assert result.data["summary"] == "Customer asked about invoice INV-9001"
    assert isinstance(result.data["case_id"], str)
    assert result.data["case_id"]


def test_create_case_id_is_prefixed_eight_char_hex() -> None:
    result = _call(
        "create_case",
        {"contact_reason": "delivery_status", "channel_thread_id": "conv_42"},
    )

    assert _CASE_ID_PATTERN.fullmatch(result.data["case_id"])


def test_create_case_is_deterministic_for_identical_params() -> None:
    params = {"contact_reason": "delivery_status", "channel_thread_id": "conv_42"}

    first = _call("create_case", params)
    second = _call("create_case", params)

    assert first.ok is True
    assert second.ok is True
    assert first.data == second.data
    assert first.data["case_id"] == second.data["case_id"]


def test_create_case_distinct_ids_for_distinct_threads() -> None:
    first = _call(
        "create_case",
        {"contact_reason": "delivery_status", "channel_thread_id": "conv_a"},
    )
    second = _call(
        "create_case",
        {"contact_reason": "delivery_status", "channel_thread_id": "conv_b"},
    )

    assert first.data["case_id"] != second.data["case_id"]


def test_create_case_applies_injected_default_urgency() -> None:
    data = CaseMockData(
        case_id_prefix="case", default_status="open", default_urgency="urgent"
    )

    result = _call(
        "create_case",
        {"contact_reason": "government_inquiry", "channel_thread_id": "conv_g"},
        data=data,
    )

    assert result.ok is True
    assert result.data["status"] == "open"
    assert result.data["urgency"] == "urgent"
    assert result.data["contact_reason"] == "government_inquiry"


def test_create_case_explicit_urgency_overrides_default() -> None:
    data = CaseMockData(
        case_id_prefix="case", default_status="open", default_urgency="urgent"
    )

    result = _call(
        "create_case",
        {"contact_reason": "government_inquiry", "urgency": "low"},
        data=data,
    )

    assert result.data["urgency"] == "low"


def test_create_case_omits_absent_optional_fields() -> None:
    result = _call("create_case", {"contact_reason": "delivery_status"})

    assert result.ok is True
    assert "summary" not in result.data
    assert "channel_thread_id" not in result.data
    assert "urgency" not in result.data


def test_create_case_reads_camel_case_aliases() -> None:
    result = _call(
        "create_case",
        {"contactReason": "billing_question", "channelThreadId": "conv_1"},
    )

    assert result.data["contact_reason"] == "billing_question"
    assert result.data["channel_thread_id"] == "conv_1"


def test_update_case_echoes_urgency_and_contact_reason() -> None:
    result = _call(
        "update_case",
        {
            "case_id": "case_abc123",
            "urgency": "high",
            "contact_reason": "delivery_escalation",
        },
    )

    assert result.ok is True
    assert result.data["case_id"] == "case_abc123"
    assert result.data["status"] == "open"
    assert result.data["urgency"] == "high"
    assert result.data["contact_reason"] == "delivery_escalation"


def test_update_case_derives_deterministic_id_when_case_id_absent() -> None:
    params = {"contact_reason": "delivery_escalation", "urgency": "high"}

    first = _call("update_case", params)
    second = _call("update_case", params)

    assert _CASE_ID_PATTERN.fullmatch(first.data["case_id"])
    assert first.data["case_id"] == second.data["case_id"]


def test_update_case_ignores_non_adjustable_fields() -> None:
    result = _call(
        "update_case",
        {
            "case_id": "case_abc123",
            "urgency": "high",
            "summary": "ignored",
            "channel_thread_id": "conv_x",
        },
    )

    assert result.ok is True
    assert "summary" not in result.data
    assert "channel_thread_id" not in result.data
