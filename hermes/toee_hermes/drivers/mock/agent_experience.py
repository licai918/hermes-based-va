"""Mock handlers for ``toee_agent_experience`` (0.0.3 S22, FR-23/NFR-3).

L6 "what the agent learns from doing the job" -- a NEW governed store in the
Toee Business Datastore, distinct from L4 Customer Memory
(``toee_customer_memory``, customer PII) and L5's authored corpus (ADR-0140).
Ports Hermes's learning-loop PATTERN, not its store: a proposal is written with
``status="proposed"`` directly rather than through a separate envelope, so the
propose/confirm gate is STATUS-based -- a proposed row sitting here is inert
until an admin flips it to ``confirmed``/``rejected`` (S24); only confirmed
entries are ever injected into a turn (S25). This slice builds the STORE +
the governed WRITE tool (``propose_experience``) + the write-side injection
scan + a minimal admin-only read (``list_agent_experience``). The review-pass
loop that GENERATES proposals is S23 -- out of scope here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional

from ...errors import ToolDriverError
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext

# v1 kinds (audit finding 4): ONE store with a `kind` field, not Hermes's
# separate notes/skills stores.
AGENT_EXPERIENCE_KINDS: tuple[str, ...] = ("note", "procedure")

# The status lifecycle (FR-23). Written here as documentation of the full
# enum; this slice only ever produces "proposed" -- S24 is what moves a row to
# "confirmed"/"rejected".
AGENT_EXPERIENCE_STATUS_VALUES: tuple[str, ...] = ("proposed", "confirmed", "rejected")

# Framework-derived write source (RK-1 parity with Customer Memory's
# resolve_memory_write_source). toee_agent_experience is allowlisted on
# internal_copilot only (S22) and the sole caller is the copilot review fork
# (S23), so there is exactly one L6 source value today.
AGENT_EXPERIENCE_SOURCE_COPILOT_AGENT = "copilot_agent"

# NFR-3: the store is operational-only. A "learning" is a short note/procedure,
# not an essay -- same discipline as Customer Memory's MEMORY_VALUE_MAX_LENGTH,
# just a larger ceiling since a procedure needs more room than a preference slot.
AGENT_EXPERIENCE_CONTENT_MAX_LENGTH = 2000

# --- write-side injection/PII scan (S22, the S09 hardening discipline floor) -
#
# ponytail: a heuristic keyword/regex floor, not a semantic classifier -- this
# is the FIRST of three lines of defense (S23 layers prompt-side enforcement
# on the review fork itself; S24's human confirm gate is the third, and the
# only one a proposal must clear before it can ever be injected). Extend the
# pattern tuples below as new seeded adversarial cases get diagnosed, the same
# way plugin/schemas.py's PARAM_SCHEMAS grows from diagnosed failures.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior)\s+instructions",
        r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior)\s+instructions",
        r"\bsystem\s*:",
        r"\bassistant\s*:",
        r"\byou are now\b",
        r"<\s*/?\s*tool_call",
        r"\bnew\s+instructions\b",
        r"\boverride\s+(your|the)\s+(instructions|system prompt)\b",
    )
)

# Email / phone / Shopify-customer-id-shaped tokens -- the store is
# operational-only (NFR-3), never customer PII.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\-\s]{6,14}\d")
_CUSTOMER_ID_RE = re.compile(r"gid://shopify/Customer/\d+|\bcust_[A-Za-z0-9]{4,}\b")


def scan_agent_experience_content(*texts: Optional[str]) -> None:
    """Reject seeded adversarial content BEFORE it reaches the INSERT.

    Shared by the mock and Postgres datastore handlers (same "one resolver,
    both twins" discipline as resolve_memory_write_source), so the two can't
    silently drift on what counts as a governed rejection. Any positional
    ``None``/empty string is skipped, so callers can pass ``content`` plus
    every string value out of ``proposer_context`` in one call.
    """
    for text in texts:
        if not text:
            continue
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                raise ToolDriverError(
                    "policy_blocked",
                    "agent_experience write rejected: instruction-injection "
                    "pattern detected in proposed content (S22 write-side scan).",
                )
        if _EMAIL_RE.search(text) or _PHONE_RE.search(text) or _CUSTOMER_ID_RE.search(text):
            raise ToolDriverError(
                "policy_blocked",
                "agent_experience write rejected: content must be "
                "operational-only, no customer PII (NFR-3).",
            )


def _require_kind(params: dict[str, Any]) -> str:
    kind = params.get("kind")
    if kind not in AGENT_EXPERIENCE_KINDS:
        raise ToolDriverError(
            "unexpected_error",
            f'agent_experience rejects kind "{kind}"; only "note" or '
            '"procedure" are allowed (FR-23, audit finding 4).',
        )
    return kind


def _require_content(params: dict[str, Any]) -> str:
    content = params.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ToolDriverError(
            "unexpected_error",
            "propose_experience requires non-empty string content.",
        )
    if len(content) > AGENT_EXPERIENCE_CONTENT_MAX_LENGTH:
        raise ToolDriverError(
            "unexpected_error",
            "agent_experience rejects content longer than "
            f"{AGENT_EXPERIENCE_CONTENT_MAX_LENGTH} characters.",
        )
    return content


def _read_proposer_context(params: dict[str, Any]) -> Optional[dict[str, Any]]:
    ctx = params.get("proposer_context")
    if ctx is None:
        return None
    if not isinstance(ctx, dict):
        raise ToolDriverError(
            "unexpected_error",
            "proposer_context must be an object when provided.",
        )
    return ctx


def _context_strings(ctx: Optional[dict[str, Any]]) -> list[str]:
    # ponytail: shallow scan only (top-level string values) -- proposer_context
    # is a flat redacted operational snapshot by convention, not nested prose.
    # Deepen if a nested shape becomes common.
    if not ctx:
        return []
    return [value for value in ctx.values() if isinstance(value, str)]


def resolve_agent_experience_source(context: "ToolExecutionContext") -> str:
    """Framework-derived ``source`` for a propose_experience write (RK-1 parity).

    ONE shared resolver for the mock and Postgres datastore handlers, same
    reasoning as Customer Memory's ``resolve_memory_write_source``: never taken
    from a model-supplied tool param. ``toee_agent_experience`` is allowlisted
    on ``internal_copilot`` only (S22, ADR-0034/35) and the sole caller is the
    copilot review fork (S23), so the resolved source is always
    ``"copilot_agent"``. Any other profile is fail-closed -- defense in depth,
    since the profile allowlist already keeps this unreachable elsewhere.
    """
    from ...plugin.profiles import INTERNAL

    if context.profile == INTERNAL:
        return AGENT_EXPERIENCE_SOURCE_COPILOT_AGENT
    raise ToolDriverError(
        "policy_blocked",
        f'agent_experience proposals are not permitted for profile "{context.profile}".',
    )


def create_agent_experience_mock_handlers() -> MockHandlerRegistry:
    """Build ``toee_agent_experience`` handlers backed by an in-memory list.

    A fresh store is created per factory call and closed over by the handlers
    (mirrors every other mock fragment in this package). No baseline/preset
    data: there is nothing to seed here (unlike Customer Memory's
    ``memory_preset``) -- an S22 acceptance run seeds entries by calling
    ``propose_experience`` directly.
    """
    store: list[dict[str, Any]] = []

    def propose_experience(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        kind = _require_kind(params)
        content = _require_content(params)
        proposer_context = _read_proposer_context(params)
        scan_agent_experience_content(content, *_context_strings(proposer_context))
        # RK-1: source is framework-derived from context.profile, never the
        # model-supplied params -- any "source" the caller passed is ignored.
        source = resolve_agent_experience_source(context)
        entry = {
            "id": f"aexp_{len(store) + 1}",
            "kind": kind,
            "status": "proposed",
            "content": content,
            "source": source,
            "proposer_context": proposer_context,
            "decider_account_id": None,
            "decided_at": None,
        }
        store.append(entry)
        return {**entry, "proposed": True}

    def list_agent_experience(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Admin-only read (see _AGENT_EXCLUDED_ACTIONS, the get_memory_audit
        # precedent) -- never reached by a live agent's tool loop.
        return {"entries": list(store)}

    return {
        "toee_agent_experience": {
            "propose_experience": propose_experience,
            "list_agent_experience": list_agent_experience,
        }
    }
