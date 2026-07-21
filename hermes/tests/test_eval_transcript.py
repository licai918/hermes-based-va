"""Tests for the transcript -> AgentTurnResult parser (record/replay core).

The live/record-replay harness runs a real Hermes turn and gets back an
OpenAI-style ``messages`` transcript plus a ``final_response`` string. This
module turns that transcript into the deterministic :class:`AgentTurnResult`
the assertion package consumes, deriving observable facts mechanically from the
tool calls the agent made and the governed tool results it got back.
"""

from __future__ import annotations

import json

from eval_runner.transcript import (
    memory_proposals_from_messages,
    tool_calls_from_messages,
    turn_result_from_transcript,
)


def _assistant_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def _tool_result(call_id: str, name: str, content: object) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": content if isinstance(content, str) else json.dumps(content),
    }


def test_parses_successful_tool_call_into_tool_and_action() -> None:
    messages = [
        {"role": "user", "content": "where is my order?"},
        _assistant_call("c1", "toee_qbo_read__get_invoice", {"invoice_number": "INV-9001"}),
        _tool_result("c1", "toee_qbo_read__get_invoice", {"invoice_number": "INV-9001", "balance": 0}),
    ]

    calls = tool_calls_from_messages(messages)

    assert len(calls) == 1
    assert calls[0].tool == "toee_qbo_read"
    assert calls[0].action == "get_invoice"
    assert calls[0].ok is True


def test_governed_failure_result_marks_tool_call_not_ok() -> None:
    messages = [
        _assistant_call("c1", "toee_qbo_read__get_invoice", {"invoice_number": "INV-9001"}),
        _tool_result(
            "c1",
            "toee_qbo_read__get_invoice",
            {"error": "blocked", "error_class": "policy_blocked"},
        ),
    ]

    calls = tool_calls_from_messages(messages)

    assert calls[0].ok is False


def test_composer_reads_outbound_text_from_textline_send_body() -> None:
    body = "Your invoice INV-9001 is paid in full."
    messages = [
        _assistant_call("c1", "toee_qbo_read__get_invoice", {"invoice_number": "INV-9001"}),
        _tool_result("c1", "toee_qbo_read__get_invoice", {"balance": 0}),
        _assistant_call(
            "c2",
            "toee_textline_reply__send_message",
            {"conversation_id": "conv1", "body": body},
        ),
        _tool_result(
            "c2",
            "toee_textline_reply__send_message",
            {"message_id": "msg_x", "conversation_id": "conv1", "body": body},
        ),
    ]

    result = turn_result_from_transcript(final_response="(internal)", messages=messages)

    assert result.outbound_text == body
    assert [(c.tool, c.action) for c in result.tool_calls] == [
        ("toee_qbo_read", "get_invoice"),
        ("toee_textline_reply", "send_message"),
    ]
    assert result.case_created is False


def test_composer_falls_back_to_final_response_without_textline_send() -> None:
    messages = [
        _assistant_call("c1", "toee_knowledge_search__search_public_site", {"query": "hours"}),
        _tool_result("c1", "toee_knowledge_search__search_public_site", {"results": []}),
    ]

    result = turn_result_from_transcript(final_response="We are open 9-5.", messages=messages)

    assert result.outbound_text == "We are open 9-5."


def test_composer_derives_case_created_contact_reason_and_urgency() -> None:
    messages = [
        _assistant_call(
            "c1",
            "toee_case__create_case",
            {"contact_reason": "delivery_delay", "urgency": "urgent", "summary": "late"},
        ),
        _tool_result(
            "c1",
            "toee_case__create_case",
            {
                "case_id": "case_x",
                "status": "open",
                "contact_reason": "delivery_delay",
                "urgency": "urgent",
            },
        ),
    ]

    result = turn_result_from_transcript(final_response="", messages=messages)

    assert result.case_created is True
    assert result.contact_reason == "delivery_delay"
    assert result.case_urgency == "urgent"


def test_composer_collects_explicit_memory_upsert_slots() -> None:
    messages = [
        _assistant_call(
            "c1",
            "toee_customer_memory__upsert_preference",
            {"key": "channel_preference", "value": "sms"},
        ),
        _tool_result(
            "c1",
            "toee_customer_memory__upsert_preference",
            {"slot": "channel_preference", "value": "sms", "stored": True},
        ),
    ]

    result = turn_result_from_transcript(final_response="", messages=messages)

    assert result.memory_upserts == ["channel_preference"]


# --- S14 (FR-15): structured proposals[] extracted from upsert_preference calls ---


def test_memory_proposals_extracts_slot_value_and_evidence_from_two_calls() -> None:
    messages = [
        _assistant_call(
            "c1",
            "toee_customer_memory__upsert_preference",
            {"key": "contact_time_preference", "value": "after 2pm"},
        ),
        _tool_result(
            "c1",
            "toee_customer_memory__upsert_preference",
            {
                "slot": "contact_time_preference",
                "value": "after 2pm",
                "evidence": "call me after 2pm please",
                "stored": True,
            },
        ),
        _assistant_call(
            "c2",
            "toee_customer_memory__upsert_preference",
            {"key": "channel_preference", "value": "sms"},
        ),
        _tool_result(
            "c2",
            "toee_customer_memory__upsert_preference",
            {"slot": "channel_preference", "value": "sms", "stored": True},
        ),
    ]

    proposals = memory_proposals_from_messages(messages)

    assert [(p.slot, p.value, p.evidence_turn) for p in proposals] == [
        ("contact_time_preference", "after 2pm", "call me after 2pm please"),
        ("channel_preference", "sms", None),
    ]


def test_memory_proposals_empty_when_no_memory_tool_calls() -> None:
    messages = [
        _assistant_call("c1", "toee_qbo_read__get_invoice", {"invoice_number": "INV-9001"}),
        _tool_result("c1", "toee_qbo_read__get_invoice", {"balance": 0}),
    ]

    assert memory_proposals_from_messages(messages) == []


def test_memory_proposals_drops_a_failed_or_unknown_slot_call() -> None:
    messages = [
        # A governed rejection (e.g. an open-ended/unknown slot, ADR-0111): ok=False.
        _assistant_call(
            "c1",
            "toee_customer_memory__upsert_preference",
            {"key": "favorite_color", "value": "blue"},
        ),
        _tool_result(
            "c1",
            "toee_customer_memory__upsert_preference",
            {"error": "rejected", "error_class": "unexpected_error"},
        ),
        # A successful call whose echoed slot is somehow outside the current enum
        # (a stale/mismatched driver) -- dropped too, defense in depth.
        _assistant_call(
            "c2",
            "toee_customer_memory__upsert_preference",
            {"key": "channel_preference", "value": "sms"},
        ),
        _tool_result(
            "c2",
            "toee_customer_memory__upsert_preference",
            {"slot": "not_a_real_slot", "value": "sms", "stored": True},
        ),
    ]

    assert memory_proposals_from_messages(messages) == []


def test_composer_ignores_blocked_case_create_for_case_created() -> None:
    messages = [
        _assistant_call("c1", "toee_case__create_case", {"contact_reason": "billing"}),
        _tool_result(
            "c1",
            "toee_case__create_case",
            {"error": "blocked", "error_class": "policy_blocked"},
        ),
    ]

    result = turn_result_from_transcript(final_response="", messages=messages)

    assert result.case_created is False
    assert result.contact_reason is None
