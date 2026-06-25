"""Mock STUB handlers for the Copilot and Supervisor Admin tools (ports mock/admin-stubs.ts).

Deterministic no-op stubs for the six Copilot/Admin tools: case manage
(ADR-0065), copilot draft (ADR-0067), workbench read (ADR-0068), admin
governance (ADR-0069), plus knowledge ops and eval review. Each action returns a
minimal, structurally usable shape so later resource-oriented BFF slices can call
it without inventing new mock contracts; those slices replace these with real
reads and governed writes.

These stubs make no external calls, use no clock or randomness, and persist
nothing, so the factory needs no injected data. Output keys are snake_case (the
TS catalog's camelCase is converted, e.g. ``caseId``->``case_id``); inputs are
read snake_case-first with a camelCase fallback, like identity's ``_read_string``.
"""

from __future__ import annotations

from typing import Any

from ...operational_policy import policy_slots_payload
from .driver import MockHandlerRegistry


def _read_string(params: dict[str, Any], *keys: str, default: str) -> str:
    """Return the first string value among ``keys``, else ``default``.

    Faithful to the TS ``readStringParam`` (any string value wins, including an
    empty one). ``keys`` is listed snake_case-first with a camelCase fallback so
    callers on either naming convention resolve to the same stub output.
    """
    for key in keys:
        value = params.get(key)
        if isinstance(value, str):
            return value
    return default


def create_admin_stub_mock_handlers() -> MockHandlerRegistry:
    """Build the registry fragment of deterministic Copilot/Admin stubs.

    Returns handlers for all six tools. The stubs are static, so (unlike the
    data-injectable read mocks) this factory takes no arguments.
    """
    return {
        "toee_workbench_read": {
            "get_case": lambda params, context: {
                "case_id": _read_string(
                    params, "case_id", "caseId", default="case_stub"
                ),
                "status": "open",
            },
            "list_cases": lambda params, context: {"cases": []},
            "get_audit_log": lambda params, context: {
                "case_id": _read_string(
                    params, "case_id", "caseId", default="case_stub"
                ),
                "entries": [],
            },
            "get_thread": lambda params, context: {
                "case_id": _read_string(
                    params, "case_id", "caseId", default="case_stub"
                ),
                "messages": [],
            },
        },
        "toee_case_manage": {
            "claim_case": lambda params, context: {
                "case_id": _read_string(
                    params, "case_id", "caseId", default="case_stub"
                ),
                "claimed": True,
            },
            "assign_case": lambda params, context: {
                "case_id": _read_string(
                    params, "case_id", "caseId", default="case_stub"
                ),
                "assignee_id": _read_string(
                    params, "assignee_id", "assigneeId", default="account_stub"
                ),
                "assigned": True,
            },
            "update_priority": lambda params, context: {
                "case_id": _read_string(
                    params, "case_id", "caseId", default="case_stub"
                ),
                "priority": _read_string(params, "priority", default="normal"),
                "updated": True,
            },
            "update_contact_reason": lambda params, context: {
                "case_id": _read_string(
                    params, "case_id", "caseId", default="case_stub"
                ),
                "contact_reason": _read_string(
                    params, "contact_reason", "contactReason", default="general"
                ),
                "updated": True,
            },
            "resolve_case": lambda params, context: {
                "case_id": _read_string(
                    params, "case_id", "caseId", default="case_stub"
                ),
                "status": "resolved",
            },
        },
        "toee_copilot_draft": {
            "draft_sms": lambda params, context: {
                "channel": "sms",
                "draft": "[stub SMS draft]",
            },
            "draft_email": lambda params, context: {
                "channel": "email",
                "subject": "[stub subject]",
                "draft": "[stub email draft]",
            },
            "draft_internal_note": lambda params, context: {
                "kind": "internal_note",
                "draft": "[stub internal note]",
            },
        },
        "toee_knowledge_ops": {
            # Not a hollow stub: ADR-0003 requires the six Required Operational
            # Policy Slots to exist as structured placeholders at onboarding, so
            # this returns the canonical registry (empty content until published).
            "get_policy_slots": lambda params, context: policy_slots_payload(),
            "update_policy_slot": lambda params, context: {
                "slot": _read_string(params, "slot", default="slot_stub"),
                "state": "draft",
                "updated": True,
            },
            "submit_for_eval": lambda params, context: {
                "submitted": True,
                "status": "pending_eval",
            },
            "rollback_published_policy": lambda params, context: {
                "slot": _read_string(params, "slot", default="slot_stub"),
                "rolled_back": True,
            },
        },
        "toee_eval_review": {
            "list_eval_runs": lambda params, context: {"runs": []},
            "get_eval_run": lambda params, context: {
                "run_id": _read_string(params, "run_id", "runId", default="run_stub"),
                "status": "passed",
            },
            "sign_off_medium_failure": lambda params, context: {
                "run_id": _read_string(params, "run_id", "runId", default="run_stub"),
                "signed_off": True,
            },
            "promote_pending_policy": lambda params, context: {
                "slot": _read_string(params, "slot", default="slot_stub"),
                "promoted": True,
                "status": "published",
            },
        },
        "toee_workbench_admin": {
            "list_accounts": lambda params, context: {"accounts": []},
            "create_account": lambda params, context: {
                "account_id": "account_stub",
                "created": True,
            },
            "update_account_role": lambda params, context: {
                "account_id": _read_string(
                    params, "account_id", "accountId", default="account_stub"
                ),
                "role": _read_string(
                    params, "role", default="customer_service_rep"
                ),
                "updated": True,
            },
            "disable_account": lambda params, context: {
                "account_id": _read_string(
                    params, "account_id", "accountId", default="account_stub"
                ),
                "disabled": True,
            },
        },
    }
