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
            "get_thread_by_phone": lambda params, context: {
                "case": None,
                "messages": [],
            },
            "get_thread_by_email": lambda params, context: {
                "case": None,
                "messages": [],
            },
            "list_auto_handled": lambda params, context: {"records": []},
            "get_auto_handled": lambda params, context: {"record": None},
            "list_sales_outreach": lambda params, context: {"cases": []},
            "get_sales_outreach": lambda params, context: {"case": None},
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
            "send_sms_message": lambda params, context: {
                "message": {
                    "message_id": "msg_stub",
                    "conversation_id": _read_string(
                        params, "case_id", "caseId", default="thread_stub"
                    ),
                    "body": _read_string(params, "body", default=""),
                },
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
            # S11: deterministic empty-corpus shape — the mock has no corpus, so
            # counts are zero and there is no ingest to report yet. The real
            # datastore handler (hermes-runtime) returns the live toee_knowledge
            # counts.
            "get_corpus_status": lambda params, context: {
                "doc_count": 0,
                "chunk_count": 0,
                "last_ingest_at": None,
                "by_type": [],
                # 0.0.4 S04: the `job` table is Postgres-only, so the mock has no
                # re-ingest job to report either.
                "last_ingest_job": None,
            },
            "enqueue_corpus_reingest": lambda params, context: {
                "job_id": None,
                "status": "unavailable",
            },
        },
        # 0.0.4 S05 (FR-13): the dead-letter view + governed Replay. The `job`
        # and `outbound_send` tables are Postgres-only, so the mock has nothing
        # stuck to report and nothing to replay -- an honest empty view and an
        # "unavailable" receipt, never a fabricated job id (same shape as
        # enqueue_corpus_reingest above).
        "toee_job_queue": {
            "list_dead_letters": lambda params, context: {
                "jobs": [],
                "outbound": [],
                "recent_replays": [],
            },
            "replay_job": lambda params, context: {
                "job_id": _read_string(params, "job_id", "jobId", default=""),
                "type": None,
                "status": "unavailable",
            },
        },
        # 0.0.4 S15 (FR-23): the /admin/integrations status read. Config presence is
        # a live, env-backed question the datastore handler (hermes-runtime) answers;
        # the mock backend makes no live external calls (INTEGRATION_DRIVER is not
        # `composio` under a mock run), so it reports every integration as
        # not_configured with an honest reason rather than a fabricated "healthy" --
        # same discipline as enqueue_corpus_reingest returning "unavailable".
        "toee_integrations": {
            "get_integrations_status": lambda params, context: {
                "active_driver": "mock",
                "integrations": [
                    {
                        "key": key,
                        "label": label,
                        "kind": kind,
                        "configured": False,
                        "status": "not_configured",
                        "pinned_version": None,
                        "last_successful_call": None,
                        "last_probe": None,
                        "detail": "Mock backend: no live integration view.",
                    }
                    for key, label, kind in (
                        ("shopify", "Shopify (Composio)", "composio_toolkit"),
                        ("qbo", "QuickBooks (Composio)", "composio_toolkit"),
                        ("square", "Square (Composio)", "composio_toolkit"),
                        ("easyroutes", "EasyRoutes", "easyroutes"),
                        ("simpletexting", "SimpleTexting", "simpletexting"),
                        ("openrouter", "OpenRouter", "openrouter"),
                        (
                            "gadget",
                            "Gadget mapping endpoint (paymentstatussync)",
                            "gadget",
                        ),
                    )
                ],
            },
            # 0.0.4 S17 (FR-25): the two reconnect actions. The mock backend makes no
            # live external calls, so it can neither generate a real Composio re-auth
            # link nor run a live probe -- it returns a deterministic "unavailable"
            # receipt, never a fabricated redirect URL or a fake "ok" (same discipline
            # as replay_job / enqueue_corpus_reingest returning "unavailable").
            "initiate_reconnect": lambda params, context: {
                "integration_key": _read_string(
                    params, "integration_key", "integrationKey", default=""
                ),
                "redirect_url": None,
                "status": "unavailable",
            },
            "reprobe_now": lambda params, context: {
                "integration_key": _read_string(
                    params, "integration_key", "integrationKey", default=""
                ),
                "status": "unavailable",
                "reason": "Mock backend: no live probe.",
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
            # Deterministic no-op (ADR-0144): the mock verifies nothing and is never
            # an auth authority — a real login surface must run TOOL_BACKEND=datastore.
            "authenticate": lambda params, context: {
                "account": {
                    "account_id": _read_string(
                        params, "username", default="account_stub"
                    ),
                    "role": "customer_service_rep",
                    "status": "active",
                },
            },
        },
    }
