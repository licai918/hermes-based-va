"""Mock handlers for ``toee_case`` (ports mock/case.ts, ADR-0064).

The External Customer Service Profile opens Follow-up Cases (``create_case``) and
adjusts urgency / contact reason on an open case (``update_case``). Output is fully
deterministic — the case id is a 32-bit FNV-1a hash of the request params, never
random and never clock-derived — so the Launch Eval runner can assert a case was
created without network access. Data is injectable so per-scenario fixtures can
override the baseline (e.g. non-customer playbooks supplying a default urgency).

ADR note: ADR-0064 defines the allowed adjustable field as ``urgency`` (not
``priority``); this module follows ADR-0064.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .driver import MockHandlerRegistry


@dataclass(frozen=True)
class CaseMockData:
    # Prefix for the deterministic case id, e.g. "case" -> "case_1a2b3c4d".
    case_id_prefix: str
    # Cases opened by the external profile are always "open" on creation.
    default_status: str
    # Optional default urgency from non-customer playbooks (e.g. government
    # traffic marked Urgent Follow-up Case) when the caller supplies none.
    default_urgency: str | None = None


case_baseline_data = CaseMockData(case_id_prefix="case", default_status="open")


def _read_string(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _deterministic_id(prefix: str, parts: list[str | None]) -> str:
    """Deterministic 32-bit FNV-1a hash rendered as an 8-char hex suffix.

    Stable for identical inputs and distinct for different inputs; no randomness
    or clock. Ports the TS ``deterministicId`` (offset basis 0x811c9dc5, prime
    0x01000193) using 32-bit unsigned arithmetic so equal inputs yield equal ids
    across both runtimes.
    """
    text = "|".join(part if part is not None else "" for part in parts)
    hash_value = 0x811C9DC5
    for char in text:
        hash_value ^= ord(char)
        hash_value = (hash_value * 0x01000193) & 0xFFFFFFFF
    return f"{prefix}_{hash_value:08x}"


def _create_case(data: CaseMockData, params: dict[str, Any]) -> dict[str, Any]:
    contact_reason = _read_string(params, "contactReason", "contact_reason")
    summary = _read_string(params, "summary")
    channel_thread_id = _read_string(params, "channelThreadId", "channel_thread_id")
    urgency = _read_string(params, "urgency") or data.default_urgency

    record: dict[str, Any] = {
        "case_id": _deterministic_id(
            data.case_id_prefix, [contact_reason, summary, channel_thread_id]
        ),
        "status": data.default_status,
    }
    if contact_reason is not None:
        record["contact_reason"] = contact_reason
    if urgency is not None:
        record["urgency"] = urgency
    if summary is not None:
        record["summary"] = summary
    if channel_thread_id is not None:
        record["channel_thread_id"] = channel_thread_id
    return record


def _update_case(data: CaseMockData, params: dict[str, Any]) -> dict[str, Any]:
    contact_reason = _read_string(params, "contactReason", "contact_reason")
    urgency = _read_string(params, "urgency")
    case_id = _read_string(params, "caseId", "case_id") or _deterministic_id(
        data.case_id_prefix, [contact_reason, urgency]
    )

    record: dict[str, Any] = {"case_id": case_id, "status": data.default_status}
    # update_case only adjusts urgency and contact_reason per ADR-0064.
    if contact_reason is not None:
        record["contact_reason"] = contact_reason
    if urgency is not None:
        record["urgency"] = urgency
    return record


def create_case_mock_handlers(
    data: CaseMockData = case_baseline_data,
) -> MockHandlerRegistry:
    """Build the registry fragment bound to a specific data set.

    The Launch Eval fixture loader passes per-scenario data; the default uses the
    baseline (prefix ``case``, status ``open``, no default urgency).
    """
    # Case writes derive everything from ``params``; the governed profile/identity
    # checks live in the Tool Gate, so the handlers ignore ``context``.
    return {
        "toee_case": {
            "create_case": lambda params, context: _create_case(data, params),
            "update_case": lambda params, context: _update_case(data, params),
        }
    }
