"""Tool schemas exposed to the LLM (Hermes plugin contract).

Each v1 Domain Adapter Tool action (ADR-0059/0070 catalog) becomes one Hermes
tool named ``<tool>__<action>`` whose ``toolset`` is the ``toee_*`` tool, so
per-profile allowlisting (ADR-0034/35/38) gates by toolset. Parameters default
to an open object -- the LLM passes the action's params at the top level and
the handler forwards them to governed dispatch, which validates tool+action
against the catalog -- but an open `{}` schema means the model has to guess
param names from persona prose, which is non-deterministic per call (the S10
``search_public_site`` incident: same process, same turn shape, guessed
``{"query": ...}`` once and an empty/wrong payload the next). ``PARAM_SCHEMAS``
layers real ``properties``/``required`` onto specific actions so the model
sees the param names instead of guessing; ``additionalProperties`` stays
``True`` throughout since governed dispatch -- not this schema -- validates
tool+action against the catalog.
"""

from __future__ import annotations

from typing import Any

from ..tool_catalog import TOOL_CATALOG

# The two Review Reason Tag enums (ADR-0154, 0.0.4 S02). EXTERNAL is used by
# toee_feedback.submit_interaction_review (supervisor/admin pass/fail review of
# an auto_handled_record or sales_outreach_case); INTERNAL is used by
# toee_feedback.submit_draft_rating (a rep's thumbs up/down on a copilot
# draft). The sets are deliberately separate -- an external tag on an internal
# rating (or vice versa) is a validation error the S03/S06 handlers enforce.
# TS keeps its own mirror at packages/shared/src/feedback.ts -- update both
# lists together so the two runtimes can't silently drift.
EXTERNAL_REVIEW_REASON_TAGS: tuple[str, ...] = (
    "factual_error",
    "tone_inappropriate",
    "policy_violation",
    "tool_misuse",
    "missed_information",
    "should_have_escalated",
    "other",
)

INTERNAL_REVIEW_REASON_TAGS: tuple[str, ...] = (
    "factual_error",
    "wrong_tone",
    "missing_context",
    "too_verbose",
    "wrong_action",
    "other",
)

# Known (tool, action) -> {"properties": ..., "required": [...]} overrides.
# Populated only for actions with a diagnosed param-guessing failure so far
# (S10). Filling the rest of the catalog -- notably the get_order family
# from the 0.0.2 {order_id vs order_number} incident -- is tracked debt, not
# this fix's scope; add entries here as they're diagnosed.
PARAM_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = {
    ("toee_knowledge_search", "search_public_site"): {
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The customer's question or topic to search the public "
                    "knowledge corpus for."
                ),
            }
        },
        "required": ["query"],
    },
    ("toee_knowledge_search", "search_operational_policy"): {
        "properties": {
            "query": {
                "type": "string",
                "description": "Policy topic or question.",
            },
            "slot": {
                "type": "string",
                "description": "Operational policy slot identifier, when known.",
            },
        },
        # Neither is required -- the mock driver accepts either (slot first,
        # falling back to query).
    },
    # 0.0.4 S31b: the delivery-promise tool. The verified customer id is supplied
    # from the Session Identity Snapshot by the driver (never a tool param, ADR-0043),
    # so only the order/variant references are declared — name-guessing them would be
    # the S10 failure mode.
    ("toee_delivery_promise", "get_order_delivery"): {
        "properties": {
            "order_name": {
                "type": "string",
                "description": (
                    "The order name/number of the verified customer's own order "
                    '(e.g. "OL49597"), as returned by toee_shopify_read.get_order / '
                    "list_customer_orders in their order_number field, or as the customer "
                    "stated it. Never fabricate an order name or id."
                ),
            },
        },
        "required": ["order_name"],
    },
    ("toee_delivery_promise", "get_product_promise"): {
        "properties": {
            "sku": {
                "type": "string",
                "description": (
                    "The SKU of the specific product variant (size) to get a delivery "
                    "promise for, taken from the variants list of "
                    "toee_shopify_read.get_product / search_products. Never fabricate a sku."
                ),
            },
            "quantity": {
                "type": "integer",
                "description": "Optional quantity being considered (defaults to 1).",
            },
        },
        "required": ["sku"],
    },
    # 0.0.4 S32 (Tier 3b): the PUBLIC pre-purchase quote by postal code. No customer id
    # (it's a hypothetical for a prospect); sourced sku + a caller-supplied postal.
    ("toee_delivery_promise", "get_delivery_quote"): {
        "properties": {
            "sku": {
                "type": "string",
                "description": (
                    "The SKU of the specific product variant (size), taken from the "
                    "variants list of toee_shopify_read.get_product / search_products. "
                    "Never fabricate a sku."
                ),
            },
            "postal_code": {
                "type": "string",
                "description": (
                    'The Canadian postal code to quote delivery to (e.g. "M3J 1P3"), as '
                    "the customer gave it. Ask the customer for it if not provided; never "
                    "fabricate one."
                ),
            },
            "quantity": {
                "type": "integer",
                "description": "Optional quantity being considered (defaults to 1).",
            },
        },
        "required": ["sku", "postal_code"],
    },
    # 0.0.3 S22 (FR-23): the governed L6 propose write -- kind/content name-
    # guessing would be exactly the S10 failure mode, so both are declared and
    # required rather than left to an open object.
    ("toee_agent_experience", "propose_experience"): {
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["note", "procedure"],
                "description": "Whether this is an operational note or a procedure.",
            },
            "content": {
                "type": "string",
                "description": (
                    "The operational learning to propose. Operational-only -- "
                    "no customer PII."
                ),
            },
            "proposer_context": {
                "type": "object",
                "description": (
                    "Optional redacted operational context the proposal was "
                    "drawn from."
                ),
            },
        },
        "required": ["kind", "content"],
    },
    # 0.0.3 S24 (FR-24): the human confirm-gate decision actions. Neither is
    # LLM-callable (both are in _AGENT_EXCLUDED_ACTIONS), but the admin BFF's
    # deterministic dispatch still goes through this same schema/param
    # validation path, so `id` is declared the same way as every other
    # diagnosed action rather than left to an open object.
    ("toee_agent_experience", "confirm_experience"): {
        "properties": {
            "id": {
                "type": "string",
                "description": "The agent_experience entry id to confirm.",
            },
        },
        "required": ["id"],
    },
    ("toee_agent_experience", "reject_experience"): {
        "properties": {
            "id": {
                "type": "string",
                "description": "The agent_experience entry id to reject.",
            },
        },
        "required": ["id"],
    },
    # 0.0.5 S01 (FR-1/FR-3): the governed L7 propose write. All FOUR core fields
    # are declared and required -- name-guessing on a store whose whole job is
    # exact surface->canonical mapping would be the S10 failure mode with a
    # governance cost. Deliberately ABSENT: status, provenance, decider,
    # hit_count. Those are framework-derived (ADR-0148) and a caller-supplied
    # value is ignored, so advertising them would only invite a forged param.
    ("toee_semantic_lexicon", "propose_lexicon_entry"): {
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "The vocabulary this term belongs to, e.g. 'tire' or "
                    "'company'. Open vocabulary, not an enum."
                ),
            },
            "entry_kind": {
                "type": "string",
                "enum": ["alias", "normalizer", "default_rule"],
                "description": (
                    "'alias' for an exact surface->canonical mapping, "
                    "'normalizer' for a pattern class, 'default_rule' for a "
                    "conditional default that must still be confirmed."
                ),
            },
            "surface_form": {
                "type": "string",
                "description": (
                    "Exactly what the customer wrote, e.g. '2055516' or 'TOEE'."
                ),
            },
            "canonical_form": {
                "type": "string",
                "description": (
                    "What it means in Toee's own vocabulary, e.g. '205/55R16' "
                    "or 'TOEE TIRE'."
                ),
            },
            "evidence": {
                "type": "string",
                "description": (
                    "Optional short excerpt of the exchange that confirms the "
                    "mapping. Customer PII in it is redacted, not rejected."
                ),
            },
            "proposer_context": {
                "type": "object",
                "description": (
                    "Optional redacted operational context the proposal was "
                    "drawn from."
                ),
            },
        },
        "required": ["domain", "entry_kind", "surface_form", "canonical_form"],
    },
    # 0.0.4 S17 (FR-25): the two reconnect actions. Neither is LLM-callable (both are
    # in _AGENT_EXCLUDED_ACTIONS), but the admin BFF's deterministic dispatch still
    # goes through this schema/param validation, so params are declared explicitly.
    ("toee_integrations", "initiate_reconnect"): {
        "properties": {
            "integration_key": {
                "type": "string",
                "enum": ["shopify", "qbo", "square"],
                "description": "The Composio-managed connection to reconnect.",
            },
            "callback_url": {
                "type": "string",
                "description": (
                    "Workbench callback URL (carries the session-bound state) the "
                    "provider returns to after re-auth. Built server-side, never "
                    "client-supplied."
                ),
            },
        },
        "required": ["integration_key", "callback_url"],
    },
    ("toee_integrations", "reprobe_now"): {
        "properties": {
            "integration_key": {
                "type": "string",
                "description": "The integration to run an on-demand health probe for.",
            },
        },
        "required": ["integration_key"],
    },
    # 0.0.4 S02 (ADR-0154): the toee_feedback tool shell's four actions. None
    # are LLM-callable (all are in _AGENT_EXCLUDED_ACTIONS), but the BFF's
    # deterministic dispatch still goes through this same schema/param
    # validation, so params are declared now rather than left open -- S03/S06/
    # S08/S10 add the handlers that enforce these shapes for real.
    ("toee_feedback", "submit_interaction_review"): {
        "properties": {
            "subject_kind": {
                "type": "string",
                "enum": ["auto_handled_record", "sales_outreach_case"],
                "description": "Which audit subject this review is about.",
            },
            "subject_id": {
                "type": "string",
                "description": (
                    "The id of the auto_handled_record or sales_outreach_case "
                    "being reviewed."
                ),
            },
            "verdict": {
                "type": "string",
                "enum": ["pass", "fail"],
                "description": "The reviewer's pass/fail judgment on the interaction.",
            },
            "reason_tags": {
                "type": "array",
                "items": {"type": "string", "enum": list(EXTERNAL_REVIEW_REASON_TAGS)},
                "description": (
                    "Reason tags for a fail verdict; at least one is required "
                    "when verdict is fail."
                ),
            },
            "comment": {
                "type": "string",
                "description": "Optional free-text color, never required.",
            },
        },
        "required": ["subject_kind", "subject_id", "verdict"],
    },
    ("toee_feedback", "record_draft_outcome"): {
        "properties": {
            "case_id": {
                "type": "string",
                "description": "The case the draft belongs to; the acting rep must hold it.",
            },
            "draft_correlation_id": {
                "type": "string",
                "description": (
                    "The correlation id shared with the draft this outcome is about."
                ),
            },
            "draft_kind": {
                "type": "string",
                "enum": ["sms", "email", "note"],
                "description": "Which copilot draft surface generated the draft.",
            },
            "outcome": {
                "type": "string",
                "enum": ["sent_as_is", "sent_edited"],
                "description": (
                    "Whether the rep sent the draft unchanged or edited it first."
                ),
            },
            "edit_distance_ratio": {
                "type": "number",
                "description": (
                    "Normalized edit distance; required when outcome is "
                    "sent_edited, rejected when outcome is sent_as_is."
                ),
            },
            "draft_text": {
                "type": "string",
                "description": (
                    "The generated-draft snapshot this outcome is about; always "
                    "available (the rep sends the draft card), so required."
                ),
            },
        },
        "required": [
            "case_id",
            "draft_correlation_id",
            "draft_kind",
            "outcome",
            "draft_text",
        ],
    },
    ("toee_feedback", "submit_draft_rating"): {
        "properties": {
            "case_id": {
                "type": "string",
                "description": "The case the rated draft belongs to; the acting rep must hold it.",
            },
            "draft_correlation_id": {
                "type": "string",
                "description": "The correlation id shared with the draft being rated.",
            },
            "draft_kind": {
                "type": "string",
                "enum": ["sms", "email", "note"],
                "description": "Which copilot draft surface generated the draft.",
            },
            "verdict": {
                "type": "string",
                "enum": ["up", "down"],
                "description": "The rep's thumbs up/down on the draft.",
            },
            "reason_tags": {
                "type": "array",
                "items": {"type": "string", "enum": list(INTERNAL_REVIEW_REASON_TAGS)},
                "description": (
                    "Reason tags for a down verdict; at least one is required "
                    "when verdict is down."
                ),
            },
            "comment": {
                "type": "string",
                "description": "Optional free-text color, never required.",
            },
            "draft_text": {
                "type": "string",
                "description": (
                    "The generated-draft snapshot being rated; always available "
                    "(you rate the draft card), so required -- a rated_only row "
                    "has no linked outcome row to recover it from otherwise."
                ),
            },
        },
        "required": [
            "case_id",
            "draft_correlation_id",
            "draft_kind",
            "verdict",
            "draft_text",
        ],
    },
    ("toee_feedback", "list_feedback"): {
        "properties": {
            "since": {
                "type": "string",
                "description": (
                    "Optional ISO-8601 timestamp; only rows created at/after "
                    "this are returned."
                ),
            },
            "verdict": {
                "type": "string",
                "description": "Optional verdict filter (pass/fail/up/down).",
            },
            "limit": {
                "type": "integer",
                "description": "Optional bounded page size.",
            },
        },
    },
}


def hermes_tool_name(tool: str, action: str) -> str:
    """Flat Hermes tool name for a ``(tool, action)`` pair."""
    return f"{tool}__{action}"


def build_tool_schema(tool: str, action: str) -> dict[str, Any]:
    """JSON schema for one ``(tool, action)`` the model can call.

    Merges :data:`PARAM_SCHEMAS` for known actions; falls back to today's
    open object (empty ``properties``, no ``required``) otherwise.
    """
    layered = PARAM_SCHEMAS.get((tool, action), {})
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": layered.get("properties", {}),
        "additionalProperties": True,
    }
    if layered.get("required"):
        parameters["required"] = layered["required"]

    return {
        "name": hermes_tool_name(tool, action),
        "description": (
            f'Toee Domain Adapter Tool "{tool}", action "{action}". '
            "Pass the action's parameters as top-level fields. Returns governed "
            "JSON; on failure an object with an \"error\" message and "
            '"error_class" (never raw vendor errors, never fabricated data).'
        ),
        "parameters": parameters,
    }


def build_tool_schemas() -> list[dict[str, Any]]:
    """All catalog actions as ``{tool, action, toolset, schema}`` entries."""
    entries: list[dict[str, Any]] = []
    for tool, actions in TOOL_CATALOG.items():
        for action in actions:
            entries.append(
                {
                    "tool": tool,
                    "action": action,
                    "toolset": tool,
                    "schema": build_tool_schema(tool, action),
                }
            )
    return entries
