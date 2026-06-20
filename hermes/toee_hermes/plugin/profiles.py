"""Hermes Profiles and their Profile Tool Allowlists (ADR-0139, ADR-0034/35/38).

The three Toee profiles are three Hermes profiles (separate ``HERMES_HOME``
homes). Enforcement is default-deny by non-registration: :func:`register` only
registers the toolsets a profile allows, so unavailable tools are never exposed
to the model in the first place (ADR-0034 enforcement order). This module is the
authoritative allowlist; each profile's Hermes ``config.yaml`` selects its
profile via ``TOEE_HERMES_PROFILE`` and enables the ``toee`` plugin.
"""

from __future__ import annotations

import os
from typing import Any, Optional

EXTERNAL = "customer_service_external"
INTERNAL = "internal_copilot"
SUPERVISOR = "supervisor_admin"

PROFILES: tuple[str, ...] = (EXTERNAL, INTERNAL, SUPERVISOR)
DEFAULT_PROFILE = EXTERNAL

PROFILE_ENV_VAR = "TOEE_HERMES_PROFILE"

# Per-profile Profile Tool Allowlist by toolset (= ``toee_*`` tool name).
PROFILE_TOOL_ALLOWLIST: dict[str, frozenset[str]] = {
    # ADR-0034 External Customer Service Profile.
    EXTERNAL: frozenset(
        {
            "toee_knowledge_search",
            "toee_shopify_read",
            "toee_qbo_read",
            "toee_easyroutes_read",
            "toee_square_payment_link",
            "toee_textline_reply",
            "toee_case",
            "toee_identity_lookup",
            "toee_customer_memory",
        }
    ),
    # ADR-0035 Internal Copilot Profile (external reads + case/draft/workbench).
    INTERNAL: frozenset(
        {
            "toee_knowledge_search",
            "toee_shopify_read",
            "toee_qbo_read",
            "toee_easyroutes_read",
            "toee_identity_lookup",
            "toee_case_manage",
            "toee_copilot_draft",
            "toee_workbench_read",
            "toee_customer_memory",
        }
    ),
    # ADR-0038 Supervisor Admin Profile (governance only).
    SUPERVISOR: frozenset(
        {
            "toee_knowledge_ops",
            "toee_eval_review",
            "toee_workbench_admin",
            "toee_workbench_read",
            "toee_knowledge_search",
        }
    ),
}


def allowlisted_tools(profile: str) -> frozenset[str]:
    """Return the toolsets allowed for ``profile`` (raises on unknown profile)."""
    try:
        return PROFILE_TOOL_ALLOWLIST[profile]
    except KeyError:
        raise ValueError(
            f'Unknown profile "{profile}". Expected one of: {", ".join(PROFILES)}.'
        ) from None


def resolve_profile(ctx: Optional[Any] = None) -> str:
    """Resolve the active profile: ``ctx.profile`` → env → default external.

    An explicitly provided but unrecognized profile is a configuration error and
    raises, so a misconfigured home fails loudly instead of silently exposing the
    wrong toolset.
    """
    candidate = getattr(ctx, "profile", None) if ctx is not None else None
    if not candidate:
        candidate = os.environ.get(PROFILE_ENV_VAR)
    if not candidate:
        return DEFAULT_PROFILE
    if candidate not in PROFILE_TOOL_ALLOWLIST:
        raise ValueError(
            f'Unknown profile "{candidate}". Expected one of: {", ".join(PROFILES)}.'
        )
    return candidate
