"""Mock handlers for ``toee_semantic_lexicon`` (0.0.5 S01, FR-1/FR-3).

L7 "the domain language the business speaks" -- the seventh and last memory
layer, a NEW governed store in the Toee Business Datastore (ADR-0140), distinct
from L4 Customer Memory (per-customer PII), L5's authored corpus, and L6 agent
experience (model-originated operational learnings). ``TOEE`` means
``TOEE TIRE``; ``2055516``, ``205 55 16`` and ``20555r16`` are all the tire size
``205/55R16``; in winter a bare size defaults to winter tires. Today all of that
rides on model guesswork.

This slice builds the STORE and its WRITE side only: ``propose_lexicon_entry``
always writes ``status="proposed"`` (the propose/confirm gate is STATUS-based,
exactly the L6 skeleton in ``agent_experience.py``, which this file mirrors) plus
a minimal admin-only read. **Nothing applies a lexicon entry yet** -- the
deterministic parameter normalizer is S03/S05, the prompt glossary S06, the
admin decide/CRUD console S02, and the capture forks S04. A proposed row here is
inert by construction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from ...content_scan import redact_pii, scan_injection
from ...errors import ToolDriverError
from .agent_experience import _context_strings, _read_proposer_context
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext

# FR-2: three kinds graded by determinism. ``alias`` is an exact surface ->
# canonical mapping and is admin-editable freely; ``normalizer`` toggles a
# pattern class whose regex lives in CODE (never in the row); ``default_rule``
# is a structured condition -> default that always confirms with the customer.
# Only the vocabulary is pinned here -- S03/S05 own what each kind DOES.
LEXICON_ENTRY_KINDS: tuple[str, ...] = ("alias", "normalizer", "default_rule")

# FR-1's status lifecycle, written out as documentation of the full enum. This
# slice only ever produces "proposed"; S02 is what moves a row on.
LEXICON_STATUS_VALUES: tuple[str, ...] = (
    "proposed",
    "confirmed",
    "rejected",
    "retired",
)

# D3: THREE provenance values, not two. ``feedback_derived`` exists because
# S25's aggregator must emit proposals distinguishable from agent-proposed ones
# in every queue; without it those proposals have no legal provenance at all.
LEXICON_PROVENANCE_ADMIN_MANUAL = "admin_manual"
LEXICON_PROVENANCE_CONVERSATION_CONFIRMED = "conversation_confirmed"
LEXICON_PROVENANCE_FEEDBACK_DERIVED = "feedback_derived"
LEXICON_PROVENANCE_VALUES: tuple[str, ...] = (
    LEXICON_PROVENANCE_ADMIN_MANUAL,
    LEXICON_PROVENANCE_CONVERSATION_CONFIRMED,
    LEXICON_PROVENANCE_FEEDBACK_DERIVED,
)

# A surface/canonical form is a domain TOKEN, not prose ("TOEE", "205 55 16").
# Same discipline as L6's AGENT_EXPERIENCE_CONTENT_MAX_LENGTH, tighter ceiling.
LEXICON_FORM_MAX_LENGTH = 200
# Evidence is a short exchange excerpt, not a transcript.
LEXICON_EVIDENCE_MAX_LENGTH = 2000


def _require_choice(params: dict[str, Any], key: str, allowed: tuple[str, ...]) -> str:
    value = params.get(key)
    if value not in allowed:
        raise ToolDriverError(
            "unexpected_error",
            f'propose_lexicon_entry rejects {key} "{value}"; allowed: '
            f'{", ".join(allowed)}.',
        )
    return str(value)


def _require_domain(params: dict[str, Any]) -> str:
    """``domain`` is an open vocabulary (tire | company | wheel | ...).

    Deliberately NOT an enum: S03 seeds domain #1 and later domains are added by
    admins, not by a code change. It is still required and length-bounded.
    """
    domain = params.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        raise ToolDriverError(
            "unexpected_error", "propose_lexicon_entry requires a non-empty domain."
        )
    if len(domain) > LEXICON_FORM_MAX_LENGTH:
        raise ToolDriverError(
            "unexpected_error",
            f"propose_lexicon_entry rejects a domain longer than "
            f"{LEXICON_FORM_MAX_LENGTH} characters.",
        )
    return domain.strip()


def _require_form(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolDriverError(
            "unexpected_error", f"propose_lexicon_entry requires a non-empty {key}."
        )
    if len(value) > LEXICON_FORM_MAX_LENGTH:
        raise ToolDriverError(
            "unexpected_error",
            f"propose_lexicon_entry rejects a {key} longer than "
            f"{LEXICON_FORM_MAX_LENGTH} characters.",
        )
    return value.strip()


def _read_evidence(params: dict[str, Any]) -> Optional[str]:
    evidence = params.get("evidence")
    if evidence is None:
        return None
    if not isinstance(evidence, str):
        raise ToolDriverError(
            "unexpected_error", "evidence must be a string when provided."
        )
    if len(evidence) > LEXICON_EVIDENCE_MAX_LENGTH:
        raise ToolDriverError(
            "unexpected_error",
            f"propose_lexicon_entry rejects evidence longer than "
            f"{LEXICON_EVIDENCE_MAX_LENGTH} characters.",
        )
    return evidence


def scan_lexicon_write(
    *,
    surface_form: str,
    canonical_form: str,
    evidence: Optional[str],
    proposer_context: Optional[dict[str, Any]],
) -> tuple[Optional[str], Optional[dict[str, Any]], bool]:
    """Apply D2's per-field write-scan policy; return the storable values.

    ONE resolver for both twins (NFR-7), so the mock and Postgres paths cannot
    drift on what a governed rejection is:

    * ``surface_form`` / ``canonical_form`` -- :func:`scan_injection` only. The
      PII leg is NOT applied: ``_PHONE_RE`` matches ``205 55 16``, the flagship
      seeded surface form, so running it here would ``policy_blocked`` the
      headline demo of the whole iteration.
    * ``evidence`` / ``proposer_context`` -- injection hard-rejects; PII is
      REDACTED IN PLACE and the entry is kept. The evidence is exactly what an
      admin needs in order to decide; throwing the entry away over a phone
      number in a quoted exchange is the wrong trade. The entry's own forms are
      exempt from redaction (see :func:`redact_pii`'s ``keep``).

    Returns ``(evidence, proposer_context, pii_redacted)``.
    """
    scan_injection(surface_form, canonical_form)
    scan_injection(evidence, *_context_strings(proposer_context))

    keep = (surface_form, canonical_form)
    scrubbed_evidence, redacted = redact_pii(evidence, keep=keep)
    scrubbed_context = proposer_context
    if proposer_context:
        # ponytail: shallow, top-level string values only -- the same convention
        # _context_strings already scans by. Deepen if a nested shape becomes
        # common (it would need to be scanned deeper too, not just redacted).
        scrubbed_context = dict(proposer_context)
        for key, value in proposer_context.items():
            if isinstance(value, str):
                scrubbed_context[key], hit = redact_pii(value, keep=keep)
                redacted = redacted or hit
    return scrubbed_evidence, scrubbed_context, redacted


def resolve_lexicon_provenance(context: "ToolExecutionContext") -> str:
    """Framework-derived ``provenance`` for a lexicon write (ADR-0148, D3).

    ONE shared resolver for the mock and Postgres twins, same discipline as
    ``resolve_agent_experience_source`` / ``resolve_memory_write_source``: the
    value comes from the EXECUTION CONTEXT, never from a caller param, so a
    model (or a compromised fork) cannot claim ``admin_manual`` for a proposal
    it invented. Any ``provenance`` in ``params`` is ignored outright.

    ``toee_semantic_lexicon`` is allowlisted on ``internal_copilot`` only, and
    within it the context's attributed actor is the discriminator:

    * an attributed ``user_id`` -- the admin BFF's deterministic
      ``tools:dispatch`` call, i.e. an admin at the keyboard -> ``admin_manual``;
    * no actor -- an unbound agent fork reflecting on a conversation in which
      the customer confirmed the mapping (S04) -> ``conversation_confirmed``.

    ``feedback_derived`` is the third legal value (D3) and is reachable only
    from S25's aggregator job, which owns introducing the branch keyed on its
    OWN execution context -- exactly as S25 does for L6's source enum. It is
    declared here so the store, the schema and every queue can already carry it.
    """
    from ...plugin.profiles import INTERNAL

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            f'semantic_lexicon writes are not permitted for profile "{context.profile}".',
        )
    if context.user_id:
        return LEXICON_PROVENANCE_ADMIN_MANUAL
    return LEXICON_PROVENANCE_CONVERSATION_CONFIRMED


def read_lexicon_proposal(
    params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    """Validate + scan one ``propose_lexicon_entry`` call; both twins call this.

    Returns the framework-derived, storable field set. Everything a caller could
    forge -- ``status``, ``provenance``, ``decider_account_id``, ``hit_count`` --
    is derived here or fixed, never read from ``params``.
    """
    domain = _require_domain(params)
    entry_kind = _require_choice(params, "entry_kind", LEXICON_ENTRY_KINDS)
    surface_form = _require_form(params, "surface_form")
    canonical_form = _require_form(params, "canonical_form")
    evidence = _read_evidence(params)
    proposer_context = _read_proposer_context(params)
    evidence, proposer_context, pii_redacted = scan_lexicon_write(
        surface_form=surface_form,
        canonical_form=canonical_form,
        evidence=evidence,
        proposer_context=proposer_context,
    )
    return {
        "domain": domain,
        "entry_kind": entry_kind,
        "surface_form": surface_form,
        "canonical_form": canonical_form,
        "evidence": evidence,
        "proposer_context": proposer_context,
        "pii_redacted": pii_redacted,
        "provenance": resolve_lexicon_provenance(context),
    }


def duplicate_entry_error(domain: str, surface_form: str) -> ToolDriverError:
    """The governed ``UNIQUE(domain, surface_form)`` denial, shared by both twins."""
    return ToolDriverError(
        "conflict",
        f'semantic_lexicon already has an entry for domain "{domain}" and '
        f'surface_form "{surface_form}".',
    )


def create_semantic_lexicon_mock_handlers() -> MockHandlerRegistry:
    """Build ``toee_semantic_lexicon`` handlers backed by an in-memory list.

    A fresh store per factory call, closed over by the handlers (mirrors every
    other mock fragment). No baseline data: S03 seeds domain #1 by calling
    ``propose_lexicon_entry``.
    """
    store: list[dict[str, Any]] = []

    def propose_lexicon_entry(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        fields = read_lexicon_proposal(params, context)
        for existing in store:
            if (
                existing["domain"] == fields["domain"]
                and existing["surface_form"] == fields["surface_form"]
            ):
                raise duplicate_entry_error(fields["domain"], fields["surface_form"])
        now = datetime.now(timezone.utc).isoformat()
        entry = {
            "id": f"lex_{len(store) + 1}",
            **fields,
            # Always "proposed": a caller-supplied status is ignored, the same
            # way provenance is. The confirm gate is S02's.
            "status": "proposed",
            "decider_account_id": None,
            "decided_at": None,
            "hit_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        store.append(entry)
        return {**entry, "proposed": True}

    def list_lexicon_entries(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Admin-only read (see _AGENT_EXCLUDED_ACTIONS, the list_agent_experience
        # precedent) -- never reached by a live agent's tool loop.
        return {"entries": list(store)}

    return {
        "toee_semantic_lexicon": {
            "propose_lexicon_entry": propose_lexicon_entry,
            "list_lexicon_entries": list_lexicon_entries,
        }
    }
