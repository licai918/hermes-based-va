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

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from ...content_scan import (
    PII_IN_VALUES_REJECT,
    read_proposer_context,
    scan_injection,
    scan_pii,
    scan_proposer_context,
)
from ...errors import ToolDriverError
from ...write_advisories import l6_write_advisories
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
# internal_copilot only (S22); 0.0.3 shipped the copilot review fork (S23) as its
# sole caller, so there was exactly one value until 0.0.5 S25.
AGENT_EXPERIENCE_SOURCE_COPILOT_AGENT = "copilot_agent"

# 0.0.5 S25 (FR-32, D3): the scheduled feedback aggregator's own value. It exists
# so a feedback-derived proposal is DISTINGUISHABLE from an agent-proposed one in
# every queue -- the one thing FR-32 is for. Like its L7 twin
# (LEXICON_PROVENANCE_FEEDBACK_DERIVED) it is framework-derived from the job's own
# execution context and can never be reached by a caller param.
AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED = "feedback_derived"

AGENT_EXPERIENCE_SOURCE_VALUES: tuple[str, ...] = (
    AGENT_EXPERIENCE_SOURCE_COPILOT_AGENT,
    AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED,
)

# NFR-3: the store is operational-only. A "learning" is a short note/procedure,
# not an essay -- same discipline as Customer Memory's MEMORY_VALUE_MAX_LENGTH,
# just a larger ceiling since a procedure needs more room than a preference slot.
AGENT_EXPERIENCE_CONTENT_MAX_LENGTH = 2000

# --- write-side injection/PII scan (S22, the S09 hardening discipline floor) -


def scan_agent_experience_content(*texts: Optional[str]) -> None:
    """Reject seeded adversarial content BEFORE it reaches the INSERT.

    Shared by the mock and Postgres datastore handlers (same "one resolver,
    both twins" discipline as resolve_memory_write_source), so the two can't
    silently drift on what counts as a governed rejection. Any positional
    ``None``/empty string is skipped, so callers can pass ``content`` plus
    every string value out of ``proposer_context`` in one call.

    0.0.5 S01 (D2) SPLIT the pattern sets into ``toee_hermes.content_scan``'s
    two named resolvers, because L4 and L7 need the injection leg WITHOUT the
    PII leg (the phone heuristic matches the tire size ``205 55 16``). L6 is
    unchanged: it is both legs, per text, in the original order -- so an input
    that used to be rejected still is, with the same ``policy_blocked`` class.
    """
    for text in texts:
        scan_injection(text)
        scan_pii(text)


def scan_agent_experience_write(
    content: str, proposer_context: Optional[dict[str, Any]]
) -> tuple[Optional[dict[str, Any]], bool]:
    """L6's whole write scan, in ONE place both twins call. Mirrors L7's
    ``scan_lexicon_write``.

    Returns ``(storable proposer_context, pii_redacted)``. The context comes back
    because it is no longer necessarily what the caller sent: a PII-shaped KEY is
    redacted rather than rejected (D2 amendment 3), so a twin that scans and then
    stores the ORIGINAL dict re-opens the NFR-6 hole.

    ``PII_IN_VALUES_REJECT`` is stated here, once, rather than at each twin's call
    site: L6's no-PII-in-content rule is unchanged since 0.0.3 S22, and one
    resolver per layer is what keeps the mock and Postgres paths in lockstep
    (NFR-7). Naming it at all is the point -- see
    :func:`toee_hermes.content_scan.scan_proposer_context`.
    """
    scan_agent_experience_content(content)
    scanned, pii_redacted, _ = scan_proposer_context(
        proposer_context, pii_in_values=PII_IN_VALUES_REJECT
    )
    return scanned, pii_redacted


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


def resolve_agent_experience_source(context: "ToolExecutionContext") -> str:
    """Framework-derived ``source`` for a propose_experience write (RK-1 parity).

    ONE shared resolver for the mock and Postgres datastore handlers, same
    reasoning as Customer Memory's ``resolve_memory_write_source``: never taken
    from a model-supplied tool param. ``toee_agent_experience`` is allowlisted
    on ``internal_copilot`` only (S22, ADR-0034/35), so the profile alone cannot
    separate the two writers that share that home. Any other profile is
    fail-closed -- defense in depth, since the profile allowlist already keeps
    this unreachable elsewhere.

    **0.0.5 S25 (D3) adds the second value, on the SAME axis L7 provenance
    already uses.** The discriminator is ``context.dispatch_route``, i.e. which
    surface reached dispatch:

    * ``FEEDBACK_AGGREGATOR_ROUTE`` -- the scheduled aggregator's own job body,
      running in the background worker -> ``feedback_derived``;
    * anything else -- the copilot review fork (S23), an eval run, the admin BFF
      -> ``copilot_agent``, exactly as in 0.0.3.

    **NOT a param and NOT ``user_id``**, for the reason the L7 twin spells out:
    ``plugin/__init__.py`` reads ``user_id`` out of the framework's runtime
    kwargs, so an attributed rep's session says WHO, never WHICH PATH. The route
    marker is a literal set at the construction site and the agent path's context
    provider never reads it from kwargs, so it is framework-derived rather than
    forgeable -- pinned by
    ``test_the_agent_path_cannot_claim_the_aggregator_route_via_a_runtime_kwarg``.
    """
    from ...plugin.profiles import INTERNAL
    from ...tool_gate import FEEDBACK_AGGREGATOR_ROUTE

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            f'agent_experience proposals are not permitted for profile "{context.profile}".',
        )
    if context.dispatch_route == FEEDBACK_AGGREGATOR_ROUTE:
        return AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED
    return AGENT_EXPERIENCE_SOURCE_COPILOT_AGENT


def _require_id(params: dict[str, Any]) -> str:
    entry_id = params.get("id")
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise ToolDriverError(
            "unexpected_error",
            "confirm_experience/reject_experience requires a non-empty string id.",
        )
    return entry_id


def resolve_experience_decision_authorization(context: "ToolExecutionContext") -> str:
    """Framework-derived decider account id for confirm/reject (0.0.3 S24, FR-24).

    ONE shared resolver for the mock and Postgres datastore handlers -- same
    "one resolver, both twins" discipline as ``resolve_agent_experience_source``
    and Customer Memory's ``resolve_clear_authorization``, so this
    security-sensitive gate can't drift between the two. A decision is always
    an admin at the keyboard, reached only via the admin BFF's deterministic
    ``tools:dispatch`` call over the internal_copilot profile (the only profile
    ``toee_agent_experience`` is allowlisted on) -- never a model-supplied
    param, never the unbound AI review-fork turn. No ``context.user_id`` ->
    ``policy_blocked``. Any other profile is fail-closed, defense in depth
    (both actions are also excluded from the LLM tool-calling surface via
    ``_AGENT_EXCLUDED_ACTIONS``).
    """
    from ...plugin.profiles import INTERNAL

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            f'agent_experience decisions are not permitted for profile "{context.profile}".',
        )
    if not context.user_id:
        raise ToolDriverError(
            "policy_blocked",
            "A governed agent_experience decision requires an attributed actor.",
        )
    return context.user_id


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
        proposer_context = read_proposer_context(params)
        proposer_context, pii_redacted = scan_agent_experience_write(
            content, proposer_context
        )
        # RK-1: source is framework-derived from context.profile, never the
        # model-supplied params -- any "source" the caller passed is ignored.
        source = resolve_agent_experience_source(context)
        # 0.0.5 S13 (FR-18, D8): write-time advisories, computed AFTER the scan
        # so nothing rejected is ever compared, and stored under the `heuristic`
        # key alone (S16 owns `copilot`). Advisory only -- the row below is
        # identical whether this returns anything or not (NFR-3).
        #
        # ponytail: `lexicon_entries=()` because the mock's L6 and L7 fragments
        # close over SEPARATE stores, so this handler genuinely cannot see the
        # lexicon. The Postgres twin -- the only one with real cross-layer data
        # -- runs both legs. Close it by handing the lexicon fragment in from
        # `create_all_mock_handlers`, exactly as S15 hands both fragments to the
        # review inbox; that file belongs to the serialized catalog lane (D17),
        # which is why it was not touched here.
        annotations = l6_write_advisories(
            content, lexicon_entries=(), experience_entries=store
        )
        entry = {
            "id": f"aexp_{len(store) + 1}",
            "kind": kind,
            "status": "proposed",
            "content": content,
            "source": source,
            "proposer_context": proposer_context,
            "annotations": annotations,
            "decider_account_id": None,
            "decided_at": None,
        }
        store.append(entry)
        # pii_redacted rides on the RESPONSE only, not the row: L6 has no column
        # for it, and inventing one on the mock would break lockstep with the
        # Postgres twin (NFR-7). Postgres records it in the audit row instead.
        return {**entry, "pii_redacted": pii_redacted, "proposed": True}

    def list_agent_experience(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Admin-only read (see _AGENT_EXCLUDED_ACTIONS, the get_memory_audit
        # precedent) -- never reached by a live agent's tool loop.
        return {"entries": list(store)}

    def _decide(
        params: dict[str, Any], context: "ToolExecutionContext", new_status: str
    ) -> dict[str, Any]:
        # 0.0.3 S24 (FR-24): the human confirm gate. Decider is framework-
        # derived (never a model/client param); the gate runs BEFORE the store
        # lookup so a missing actor is always policy_blocked regardless of
        # entry_id. Only a "proposed" entry transitions -- an already-decided
        # or missing entry is idempotency-safe, never corrupted or re-decided.
        entry_id = _require_id(params)
        decider = resolve_experience_decision_authorization(context)
        for entry in store:
            if entry["id"] == entry_id:
                if entry["status"] == "proposed":
                    entry["status"] = new_status
                    entry["decider_account_id"] = decider
                    entry["decided_at"] = datetime.now(timezone.utc).isoformat()
                return dict(entry)
        raise ToolDriverError(
            "not_found", f'agent_experience entry "{entry_id}" not found.'
        )

    def confirm_experience(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return _decide(params, context, "confirmed")

    def reject_experience(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return _decide(params, context, "rejected")

    return {
        "toee_agent_experience": {
            "propose_experience": propose_experience,
            "list_agent_experience": list_agent_experience,
            "confirm_experience": confirm_experience,
            "reject_experience": reject_experience,
        }
    }
