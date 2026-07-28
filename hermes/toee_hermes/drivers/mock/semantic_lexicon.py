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

from ...content_scan import (
    PII_IN_VALUES_REDACT,
    read_proposer_context,
    redact_pii,
    scan_injection,
    scan_proposer_context,
)
from ...errors import ToolDriverError
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
) -> tuple[Optional[str], Optional[dict[str, Any]], bool, tuple[str, ...]]:
    """Apply D2's per-field write-scan policy; return the storable values.

    ONE resolver for both twins (NFR-7), so the mock and Postgres paths cannot
    drift on what a governed rejection is:

    * ``surface_form`` / ``canonical_form`` -- :func:`scan_injection` only. The
      PII leg is NOT applied: ``_PHONE_RE`` matches ``205 55 16``, the flagship
      seeded surface form, so running it here would ``policy_blocked`` the
      headline demo of the whole iteration.
    * ``evidence`` / ``proposer_context`` -- injection hard-rejects at every
      depth; PII is REDACTED IN PLACE, in KEYS as well as values (S01 re-review:
      a key was a way past NFR-6), and the entry is kept. The evidence is exactly
      what an admin needs in order to decide; throwing the entry away over a
      phone number in a quoted exchange is the wrong trade. The entry's own forms
      are exempt from redaction (see :func:`redact_pii`'s ``keep``).
      ``PII_IN_VALUES_REDACT`` says that out loud at this call site, because the
      other shared layer says ``PII_IN_VALUES_REJECT`` over the same walk.

    Returns ``(evidence, proposer_context, pii_redacted, pii_keep_exempt)``.
    ``pii_keep_exempt`` names the spans the exemption spared, so a waived
    redaction is auditable instead of silent: ``surface_form`` is model-supplied
    and PII-unscanned by design, so a proposal CAN arrive with
    ``surface_form="416-555-0199"`` quoted in its own evidence and keep the
    number. That is the mechanism working as designed -- but it must leave a
    trace. ``pii_redacted`` deliberately does NOT flip for it: it means "text was
    removed", the thing an admin cannot see for themselves. The spared spans
    equal this entry's own forms, which are already on the row in front of them.
    """
    scan_injection(surface_form, canonical_form, evidence)

    keep = (surface_form, canonical_form)
    scrubbed_evidence, redacted, spared = redact_pii(evidence, keep=keep)
    scrubbed_context, context_hit, context_spared = scan_proposer_context(
        proposer_context, pii_in_values=PII_IN_VALUES_REDACT, keep=keep
    )
    return (
        scrubbed_evidence,
        scrubbed_context,
        redacted or context_hit,
        spared + context_spared,
    )


def resolve_lexicon_provenance(context: "ToolExecutionContext") -> str:
    """Framework-derived ``provenance`` for a lexicon write (ADR-0148, D3).

    ONE shared resolver for the mock and Postgres twins, same discipline as
    ``resolve_agent_experience_source`` / ``resolve_memory_write_source``: the
    value comes from the EXECUTION CONTEXT, never from a caller param, so a
    model (or a compromised fork) cannot claim ``admin_manual`` for a proposal
    it invented. Any ``provenance`` in ``params`` is ignored outright.

    ``toee_semantic_lexicon`` is allowlisted on ``internal_copilot`` only, so the
    profile alone cannot separate the two writers that share that home. The
    discriminator is the DISPATCH ROUTE, i.e. which surface reached dispatch:

    * ``context.dispatch_route == TOOLS_DISPATCH_ROUTE`` -- the admin BFF's
      deterministic ``tools:dispatch`` request (ADR-0141), a human at the
      keyboard -> ``admin_manual``;
    * anything else -- inside an agent turn (S04's capture fork), eval, a job
      -> ``conversation_confirmed``.

    **NOT ``user_id``** (S01 review finding 1). The L6 twin
    ``resolve_agent_experience_source`` deliberately ignores it, for the reason
    that bites here: ``plugin/__init__.py`` reads ``user_id`` straight out of the
    framework's runtime kwargs, and ADR-0141 puts a rep's account on an
    internal_copilot session -- so a capture fork running on that session would
    stamp every guess the AGENT invented with ``admin_manual``, the one value
    whose entire meaning is "a human admin typed this". The console queue would
    then be unable to tell a guess from a decision, destroying the exact
    discrimination D3 exists to provide. An actor says WHO, not WHICH PATH.

    The marker is unforgeable from a turn: the dispatch app sets it as a literal
    behind the shared bearer, and the agent path's context provider never reads
    it from kwargs -- so it is framework-derived, not a caller parameter.

    ``feedback_derived`` is the third legal value (D3) and is reachable only
    from S25's aggregator job, which owns introducing the branch keyed on its
    OWN execution context -- exactly as S25 does for L6's source enum. It is
    declared here so the store, the schema and every queue can already carry it.
    """
    from ...plugin.profiles import INTERNAL
    from ...tool_gate import TOOLS_DISPATCH_ROUTE

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            f'semantic_lexicon writes are not permitted for profile "{context.profile}".',
        )
    if context.dispatch_route == TOOLS_DISPATCH_ROUTE:
        return LEXICON_PROVENANCE_ADMIN_MANUAL
    return LEXICON_PROVENANCE_CONVERSATION_CONFIRMED


def read_lexicon_proposal(
    params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    """Validate + scan one ``propose_lexicon_entry`` call; both twins call this.

    Returns the framework-derived, storable field set. Everything a caller could
    forge -- ``status``, ``provenance``, ``decider_account_id``, ``hit_count`` --
    is derived here or fixed, never read from ``params``.

    ``pii_keep_exempt`` rides along but is NOT a column: both twins report it on
    the propose response and the Postgres twin records it in the audit row's
    ``details``. It is per-write governance evidence, not entry state.
    """
    domain = _require_domain(params)
    entry_kind = _require_choice(params, "entry_kind", LEXICON_ENTRY_KINDS)
    surface_form = _require_form(params, "surface_form")
    canonical_form = _require_form(params, "canonical_form")
    evidence = _read_evidence(params)
    proposer_context = read_proposer_context(params)
    evidence, proposer_context, pii_redacted, pii_keep_exempt = scan_lexicon_write(
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
        "pii_keep_exempt": pii_keep_exempt,
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
        # Per-write governance evidence, not entry state -- kept off the stored
        # row so the mock and the (column-less) Postgres row stay in lockstep.
        pii_keep_exempt = fields.pop("pii_keep_exempt")
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
        return {**entry, "pii_keep_exempt": pii_keep_exempt, "proposed": True}

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
