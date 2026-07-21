"""Parse a Hermes turn transcript into the deterministic AgentTurnResult.

A Hermes turn returns an OpenAI-style ``messages`` list (assistant messages whose
``tool_calls`` reference later ``role: "tool"`` result messages) plus a
``final_response`` string. This module derives the observable facts the Launch
Eval assertion package consumes — purely from what the agent actually did — so a
recorded transcript can be replayed deterministically without a model or network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from toee_hermes.drivers.mock.memory import MEMORY_PREFERENCE_SLOTS

from .harness import AgentTurnResult, RecordedToolCall


def _parse_json(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return content


@dataclass(frozen=True)
class _ParsedCall:
    """One assistant tool call paired with its governed result."""

    tool: str
    action: str
    args: dict[str, Any]
    result: Any
    ok: bool


def _parsed_calls(messages: list[dict]) -> list[_ParsedCall]:
    """Pair each assistant ``tool_calls`` entry with its ``role: "tool"`` result.

    Governed dispatch serializes success as the data object and failure as
    ``{"error", "error_class"}`` (see ``plugin/tools.py``), so an ``error_class``
    key in the result marks a governed failure (ADR-0020).
    """
    results_by_id: dict[str, Any] = {}
    for msg in messages:
        if msg.get("role") == "tool":
            call_id = msg.get("tool_call_id")
            if isinstance(call_id, str):
                results_by_id[call_id] = _parse_json(msg.get("content"))

    calls: list[_ParsedCall] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tool_call in msg.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            tool, _, action = (function.get("name") or "").partition("__")
            call_id = tool_call.get("id")
            result = results_by_id.get(call_id) if isinstance(call_id, str) else None
            args = _parse_json(function.get("arguments"))
            calls.append(
                _ParsedCall(
                    tool=tool,
                    action=action,
                    args=args if isinstance(args, dict) else {},
                    result=result,
                    ok=not (isinstance(result, dict) and "error_class" in result),
                )
            )
    return calls


def tool_calls_from_messages(messages: list[dict]) -> list[RecordedToolCall]:
    """Recorded tool calls, in order, parsed from a Hermes transcript."""
    return [
        RecordedToolCall(tool=call.tool, action=call.action, ok=call.ok)
        for call in _parsed_calls(messages)
    ]


def _textline_body(call: _ParsedCall) -> str | None:
    """The customer-facing SMS body of a successful governed Textline send."""
    if call.tool != "toee_textline_reply" or call.action != "send_message" or not call.ok:
        return None
    source = call.result if isinstance(call.result, dict) else call.args
    body = source.get("body")
    return body if isinstance(body, str) and body else None


def _str_field(call: _ParsedCall, *keys: str) -> str | None:
    """Read a string field, preferring the governed result echo over the call args."""
    result = call.result if isinstance(call.result, dict) else {}
    for source in (result, call.args):
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return None


@dataclass(frozen=True)
class MemoryProposal:
    """One structured Customer Memory proposal extracted from a turn (S14, FR-15).

    ``evidence_turn`` is the optional verbatim customer phrase the write carried as
    ``evidence`` (PRD FR-3) -- named to match the PRD's ``(slot, value,
    evidence-turn)`` envelope wording.
    """

    slot: str
    value: str
    evidence_turn: str | None = None


def memory_proposals_from_messages(messages: list[dict]) -> list[MemoryProposal]:
    """Structured ``toee_customer_memory.upsert_preference`` proposals (S14, FR-15).

    Reads each successful call's governed RESULT -- the tool gate already validated
    the slot/value there -- never the raw model-supplied call arguments, so a
    proposal can't smuggle prose past the tool (mirrors the framework-derived, not
    model-narrated, discipline ``resolve_memory_write_source``/``resolve_customer_
    memory_binding`` already hold to). A failed call (bad slot, oversized value,
    unresolvable identity, ...) is already ``ok is False`` from ``_parsed_calls`` and
    is skipped; a slot outside the current ``MEMORY_PREFERENCE_SLOTS`` enum is
    dropped too, defense in depth against a future driver that behaves differently.
    This turn is propose-only (S13/ADR-0150): nothing here writes anywhere.
    """
    proposals: list[MemoryProposal] = []
    for call in _parsed_calls(messages):
        if (
            call.tool != "toee_customer_memory"
            or call.action != "upsert_preference"
            or not call.ok
        ):
            continue
        result = call.result if isinstance(call.result, dict) else {}
        slot = result.get("slot")
        value = result.get("value")
        if slot not in MEMORY_PREFERENCE_SLOTS or not isinstance(value, str):
            continue
        evidence = result.get("evidence")
        proposals.append(
            MemoryProposal(
                slot=slot,
                value=value,
                evidence_turn=evidence if isinstance(evidence, str) else None,
            )
        )
    return proposals


def turn_result_from_transcript(
    *, final_response: str, messages: list[dict]
) -> AgentTurnResult:
    """Compose the deterministic AgentTurnResult from a Hermes turn transcript.

    Customer-facing text is the governed Textline reply body (ADR-0083); when the
    turn sent none, the agent's ``final_response`` stands in.
    """
    calls = _parsed_calls(messages)
    tool_calls = [
        RecordedToolCall(tool=call.tool, action=call.action, ok=call.ok)
        for call in calls
    ]

    bodies = [body for call in calls if (body := _textline_body(call)) is not None]
    outbound_text = "\n".join(bodies) if bodies else (final_response or "")

    case_created = any(
        call.tool == "toee_case" and call.action == "create_case" and call.ok
        for call in calls
    )

    # Contact reason / urgency from successful case writes (last write wins, so an
    # update_case re-classification supersedes the create).
    contact_reason: str | None = None
    case_urgency: str | None = None
    for call in calls:
        if call.tool in ("toee_case", "toee_case_manage") and call.ok:
            reason = _str_field(call, "contact_reason", "contactReason")
            if reason is not None:
                contact_reason = reason
            urgency = _str_field(call, "urgency")
            if urgency is not None:
                case_urgency = urgency

    # Explicit preference slots written this turn (ADR-0111 four-slot model).
    memory_upserts = [
        slot
        for call in calls
        if call.tool == "toee_customer_memory"
        and call.action == "upsert_preference"
        and call.ok
        and (slot := _str_field(call, "slot", "key")) is not None
    ]

    return AgentTurnResult(
        outbound_text=outbound_text,
        tool_calls=tool_calls,
        case_created=case_created,
        memory_upserts=memory_upserts,
        contact_reason=contact_reason,
        case_urgency=case_urgency,
    )
