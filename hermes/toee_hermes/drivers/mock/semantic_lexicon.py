"""Mock handlers for ``toee_semantic_lexicon`` (0.0.5 S01, FR-1/FR-3).

L7 "the domain language the business speaks" -- the seventh and last memory
layer, a NEW governed store in the Toee Business Datastore (ADR-0140), distinct
from L4 Customer Memory (per-customer PII), L5's authored corpus, and L6 agent
experience (model-originated operational learnings). ``TOEE`` means
``TOEE TIRE``; ``2055516``, ``205 55 16`` and ``20555r16`` are all the tire size
``205/55R16``; in winter a bare size defaults to winter tires. Today all of that
rides on model guesswork.

S01 built the STORE and its WRITE side: ``propose_lexicon_entry`` always writes
``status="proposed"`` (the propose/confirm gate is STATUS-based, exactly the L6
skeleton in ``agent_experience.py``, which this file mirrors) plus a minimal
admin-only read.

0.0.5 S02 (FR-3 decide side / FR-8) adds the HUMAN GATE on top of it:
``confirm``/``reject``/``retire``/``edit``/``add``, all admin-only and all
excluded from the LLM tool-calling surface, plus the filters the console's queue
reads through the SAME ``list_lexicon_entries`` action. **Nothing applies a
lexicon entry yet** -- the deterministic parameter normalizer is S03/S05, the
prompt glossary S06, and the capture forks S04.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
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

# 0.0.5 S02 (FR-3 decide side): the human gate's transition table -- action name
# -> (status a row must be IN, status it moves to, audit action). ONE table, both
# twins, so the mock and Postgres paths cannot disagree about which transitions
# exist (NFR-7). Each transition is guarded on its FROM status, which is the
# idempotency floor: a redelivered decision finds the row already moved and is a
# safe no-op, and `retire` cannot reach a `proposed` row (a proposal is rejected,
# never retired).
LEXICON_DECISIONS: dict[str, tuple[str, str, str]] = {
    "confirm_lexicon_entry": ("proposed", "confirmed", "lexicon_entry_confirmed"),
    "reject_lexicon_entry": ("proposed", "rejected", "lexicon_entry_rejected"),
    "retire_lexicon_entry": ("confirmed", "retired", "lexicon_entry_retired"),
}

# D7: an edit changes the MAPPING in place and nothing else. See read_lexicon_edit
# for why domain/entry_kind/evidence are deliberately not here.
LEXICON_EDITABLE_FIELDS: tuple[str, ...] = ("surface_form", "canonical_form")

# An entry can be edited while it is still live. `rejected`/`retired` are
# terminal: editing one would resurrect a decision an admin already made.
LEXICON_EDITABLE_STATUSES: tuple[str, ...] = ("proposed", "confirmed")

UNATTRIBUTED_ADMIN_MESSAGE = (
    "A governed semantic_lexicon admin action requires an attributed actor "
    "(D20: admin_manual with no decider is unfalsifiable provenance)."
)


def _require_choice(params: dict[str, Any], key: str, allowed: tuple[str, ...]) -> str:
    value = params.get(key)
    if value not in allowed:
        raise ToolDriverError(
            "unexpected_error",
            f'semantic_lexicon rejects {key} "{value}"; allowed: '
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
            "unexpected_error", "semantic_lexicon requires a non-empty domain."
        )
    if len(domain) > LEXICON_FORM_MAX_LENGTH:
        raise ToolDriverError(
            "unexpected_error",
            f"semantic_lexicon rejects a domain longer than "
            f"{LEXICON_FORM_MAX_LENGTH} characters.",
        )
    return domain.strip()


def _require_form(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolDriverError(
            "unexpected_error", f"semantic_lexicon requires a non-empty {key}."
        )
    if len(value) > LEXICON_FORM_MAX_LENGTH:
        raise ToolDriverError(
            "unexpected_error",
            f"semantic_lexicon rejects a {key} longer than "
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
            f"semantic_lexicon rejects evidence longer than "
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

    **D20 (0.0.5 S02): ``admin_manual`` must be ATTRIBUTABLE.** The route says a
    human was driving; ADR-0141's actor resolution fails open, so before this
    guard a write on the admin route with nobody attached persisted as
    ``admin_manual`` with a NULL decider -- provenance nothing can falsify, which
    is the precise failure ``decider_account_id`` exists to prevent. Everywhere
    else in this codebase a missing actor on a governed write is a fail-closed
    ``policy_blocked``; the provenance path is no different. The AGENT route is
    untouched: an unattributed capture fork is normal, and
    ``conversation_confirmed`` asserts nothing about a human.
    """
    from ...plugin.profiles import INTERNAL
    from ...tool_gate import TOOLS_DISPATCH_ROUTE

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            f'semantic_lexicon writes are not permitted for profile "{context.profile}".',
        )
    if context.dispatch_route == TOOLS_DISPATCH_ROUTE:
        if not context.user_id:
            raise ToolDriverError("policy_blocked", UNATTRIBUTED_ADMIN_MESSAGE)
        return LEXICON_PROVENANCE_ADMIN_MANUAL
    return LEXICON_PROVENANCE_CONVERSATION_CONFIRMED


def resolve_lexicon_decision_authorization(context: "ToolExecutionContext") -> str:
    """Framework-derived decider account id for every L7 admin action (FR-3/FR-8).

    ONE shared resolver for the mock and Postgres twins -- the
    ``resolve_experience_decision_authorization`` skeleton, same reasoning: this
    gate is security-sensitive, so the two paths must not be able to drift on who
    is authorized to decide (the S15-0.0.4/S21-0.0.4 lesson). A decision is always
    an admin at the keyboard, reached only through the admin BFF's deterministic
    ``tools:dispatch`` call over ``internal_copilot`` (the only profile
    ``toee_semantic_lexicon`` is allowlisted on). Never a model-supplied param,
    never a capture fork. Callers run it BEFORE the row lookup, so a missing
    actor is ``policy_blocked`` regardless of ``id``.
    """
    from ...plugin.profiles import INTERNAL

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            f'semantic_lexicon decisions are not permitted for profile "{context.profile}".',
        )
    if not context.user_id:
        raise ToolDriverError("policy_blocked", UNATTRIBUTED_ADMIN_MESSAGE)
    return context.user_id


def resolve_manual_add_provenance(context: "ToolExecutionContext") -> str:
    """``add_lexicon_entry``'s provenance -- ``admin_manual`` or nothing.

    Manual-add's whole meaning is "a human administrator typed this, and the
    admin IS the gate", which is why it lands ``confirmed`` with no proposal step.
    Off the deterministic admin route the framework cannot derive that claim, so
    the write is REFUSED rather than quietly downgraded to
    ``conversation_confirmed`` -- a silent downgrade would turn an admin's
    intent into an agent-shaped row nobody asked for. Belt and braces behind
    ``_AGENT_EXCLUDED_ACTIONS``, which already keeps this off every model's
    tool-calling surface.
    """
    provenance = resolve_lexicon_provenance(context)
    if provenance != LEXICON_PROVENANCE_ADMIN_MANUAL:
        raise ToolDriverError(
            "policy_blocked",
            "add_lexicon_entry is reachable only from the deterministic admin "
            "dispatch route: admin_manual provenance cannot be derived here.",
        )
    return provenance


def _require_id(params: dict[str, Any]) -> str:
    entry_id = params.get("id")
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise ToolDriverError(
            "unexpected_error",
            "a semantic_lexicon decision requires a non-empty string id.",
        )
    return entry_id


def read_lexicon_decision(
    params: dict[str, Any], context: "ToolExecutionContext"
) -> tuple[str, str]:
    """``(entry id, decider)`` for confirm/reject/retire -- ONE resolver, both twins."""
    entry_id = _require_id(params)
    return entry_id, resolve_lexicon_decision_authorization(context)


def read_lexicon_edit(
    params: dict[str, Any], context: "ToolExecutionContext"
) -> tuple[str, str, dict[str, str]]:
    """``(entry id, editor, changed fields)`` for ``edit_lexicon_entry`` (D7).

    ONE resolver, both twins. Only the MAPPING is editable: ``surface_form`` and
    ``canonical_form``. ``domain`` and ``entry_kind`` deliberately are not --
    ``domain`` is the scope of ``UNIQUE(domain, surface_form)`` and ``entry_kind``
    selects which in-code machinery S03/S05 apply, so changing either in place
    turns one entry into a different one. That is the retire-then-add intent, not
    an edit. ``evidence``/``proposer_context`` are the PROPOSER's record of why
    the entry was suggested; an admin rewriting them would be editing the
    evidence they are judging.

    At least one field must actually be supplied: an empty edit would otherwise
    write an audit row claiming a change that never happened.
    """
    entry_id = _require_id(params)
    editor = resolve_lexicon_decision_authorization(context)
    changes = {
        field: _require_form(params, field)
        for field in LEXICON_EDITABLE_FIELDS
        if params.get(field) is not None
    }
    if not changes:
        raise ToolDriverError(
            "unexpected_error",
            "edit_lexicon_entry requires at least one of: "
            f'{", ".join(LEXICON_EDITABLE_FIELDS)}.',
        )
    # Same injection policy the propose path applies to these two fields (D2):
    # hard-reject, and no PII leg -- a domain token is short and digit-shaped.
    scan_injection(*changes.values())
    return entry_id, editor, changes


def read_lexicon_filters(params: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """``(status, domain)`` filters for ``list_lexicon_entries`` -- ONE resolver.

    S01 shipped the unfiltered read because its acceptance needed one; S02
    EXTENDS it rather than adding a second read action, so the console's queue
    and the full CRUD list are the same governed surface. Both filters are
    optional; an unknown ``status`` is a validation error rather than a silently
    empty list, because a queue that renders "nothing pending" for a typo is
    worse than one that errors.
    """
    status = params.get("status")
    if status is not None:
        if status not in LEXICON_STATUS_VALUES:
            raise ToolDriverError(
                "unexpected_error",
                f'list_lexicon_entries rejects status "{status}"; allowed: '
                f'{", ".join(LEXICON_STATUS_VALUES)}.',
            )
        status = str(status)
    domain = params.get("domain")
    if domain is not None:
        domain = _require_domain(params)
    return status, domain


def lexicon_provenance_unattributed(row: dict[str, Any]) -> bool:
    """Is this row an ``admin_manual`` claim with nobody attached? (D20 sweep.)

    D20 closes the hole going forward, but rows written between S01 and S02 can
    already carry ``provenance='admin_manual'`` with a NULL decider. They arrive
    in the queue looking authoritative. Both twins derive this flag on the READ
    -- no column, no migration, no backfill guessing at who the admin was -- so
    the console can render an unattributed claim distinctly from one a named
    admin actually made. It is derived rather than stored on purpose: the answer
    is a property of the two columns, and a stored copy could drift from them.
    """
    return (
        row.get("provenance") == LEXICON_PROVENANCE_ADMIN_MANUAL
        and not row.get("decider_account_id")
    )


def lexicon_entry_view(row: dict[str, Any]) -> dict[str, Any]:
    """One response shape for every governed L7 action, both twins.

    S02 review finding B: the D20 derivation was applied on the LIST only, so an
    EDIT response -- which the console maps straight over the row it replaces --
    reported ``provenance_unattributed`` as absent/false on a row that is still
    ``admin_manual`` with a NULL decider. The badge went dark at the exact moment
    an admin was touching the row. Deriving it here, on the way out of every
    action, is the only place that cannot be forgotten by the next one.
    """
    return {**row, "provenance_unattributed": lexicon_provenance_unattributed(row)}


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


def _make_clock() -> Any:
    """A strictly increasing ISO-8601 UTC clock for one mock store.

    Postgres gives every write its own transaction ``now()``, so ``created_at
    DESC`` and ``MAX(updated_at)`` are unambiguous there. Windows' system clock
    granularity is coarse enough (tens of milliseconds) that two consecutive mock
    writes land on the SAME microsecond -- which would make the mock's ordering
    and its confirmed-set version ambiguous where the Postgres twin's are not.
    Nudging forward keeps the two honest about the same thing.
    """
    last = ""

    def now() -> str:
        nonlocal last
        text = datetime.now(timezone.utc).isoformat()
        if text <= last:
            text = (
                datetime.fromisoformat(last) + timedelta(microseconds=1)
            ).isoformat()
        last = text
        return text

    return now


def _lexicon_version(store: list[dict[str, Any]]) -> Optional[str]:
    """The marker S05/S06 compare their caches against -- ``MAX(updated_at)``.

    Every governed L7 write moves ``updated_at`` on the row it touches, so the
    maximum over the table is a monotonic version of the whole store: it changes
    on every confirm/reject/retire/edit/add and can never go backwards. Derived,
    so there is no column to migrate, nothing to keep in sync, and no way for a
    stored counter to disagree with the rows it claims to describe.

    Named ``lexicon_version``, not ``confirmed_set_version`` (S02 review finding
    F): it is a max over the WHOLE table, so a reject -- which changes nothing in
    the confirmed set -- moves it too, and the old name promised otherwise.
    Table-wide is nonetheless the RIGHT computation, which is why the name moved
    instead of the query: a max scoped to the confirmed rows would go DOWN when a
    retire moves a row out of that subset, and a cache must never see a version
    go backwards.

    ponytail: one number for the whole store. If a per-domain version ever
    matters, group by domain here; nothing needs it today.
    """
    return max((entry["updated_at"] for entry in store), default=None)


def missing_entry_error(entry_id: str) -> ToolDriverError:
    """The governed "no such row" denial, shared by both twins."""
    return ToolDriverError("not_found", f'semantic_lexicon entry "{entry_id}" not found.')


def not_editable_error(entry_id: str, status: str) -> ToolDriverError:
    """Editing a terminal row is refused, not silently ignored (shared by both twins)."""
    return ToolDriverError(
        "conflict",
        f'semantic_lexicon entry "{entry_id}" is {status}; only '
        f'{" or ".join(LEXICON_EDITABLE_STATUSES)} entries can be edited. '
        "Add a new entry instead.",
    )


def create_semantic_lexicon_mock_handlers(
    store: Optional[list[dict[str, Any]]] = None,
) -> MockHandlerRegistry:
    """Build ``toee_semantic_lexicon`` handlers backed by an in-memory list.

    A fresh store per factory call, closed over by the handlers (mirrors every
    other mock fragment). No baseline data, and deliberately NOT in lockstep with
    Postgres here: migration 0024 seeds domain #1 into the real table, but the mock
    stays empty. Seeding it via ``propose_lexicon_entry`` would write
    ``status='proposed'`` rows, and every L7 reader consumes ``confirmed`` rows
    only -- so the mock's "baseline" would be invisible to exactly the code it
    stands in for, which is worse than having none. Tests that need the seeded
    vocabulary build it explicitly from ``toee_hermes.lexicon.LEXICON_SEED_ENTRIES``.

    ``store`` is an injection point for tests that must set up state no governed
    action can produce -- an interim unattributed ``admin_manual`` row (D20 now
    refuses to write one) or a non-zero ``hit_count`` (D6: a scheduled rollup owns
    that column).
    """
    store = [] if store is None else store
    # Mock/Postgres divergence #2 (S01 review): `f"lex_{len(store) + 1}"` reuses
    # an id the moment the store shrinks, and S02 is where rows start moving.
    # Postgres mints a uuid per row and never reuses one; a monotonic counter is
    # the mock's equivalent. Ids stay short and readable for test assertions.
    ids = itertools.count(1)
    now = _make_clock()

    def _find(entry_id: str) -> dict[str, Any]:
        for entry in store:
            if entry["id"] == entry_id:
                return entry
        raise missing_entry_error(entry_id)

    def _reject_duplicate(domain: str, surface_form: str, *, ignore: str = "") -> None:
        for existing in store:
            if (
                existing["id"] != ignore
                and existing["domain"] == domain
                and existing["surface_form"] == surface_form
            ):
                raise duplicate_entry_error(domain, surface_form)

    def _insert(fields: dict[str, Any], **overrides: Any) -> dict[str, Any]:
        _reject_duplicate(fields["domain"], fields["surface_form"])
        stamp = now()
        entry = {
            "id": f"lex_{next(ids)}",
            **fields,
            "status": "proposed",
            "decider_account_id": None,
            "decided_at": None,
            "hit_count": 0,
            "created_at": stamp,
            "updated_at": stamp,
            **overrides,
        }
        store.append(entry)
        return entry

    def propose_lexicon_entry(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        fields = read_lexicon_proposal(params, context)
        # Per-write governance evidence, not entry state -- kept off the stored
        # row so the mock and the (column-less) Postgres row stay in lockstep.
        pii_keep_exempt = fields.pop("pii_keep_exempt")
        # Always "proposed": a caller-supplied status is ignored, the same way
        # provenance is. Only add_lexicon_entry lands a row already decided.
        entry = _insert(fields)
        return {
            **lexicon_entry_view(entry),
            "pii_keep_exempt": pii_keep_exempt,
            "proposed": True,
        }

    def add_lexicon_entry(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # FR-8/US1: an admin adds "TOEE = TOEE TIRE" and it is LIVE, no deploy.
        # The admin IS the gate, so there is no proposal step -- the row lands
        # `confirmed` with the adding admin as its decider. Same validation and
        # the same split write scan as a proposal: being an admin does not exempt
        # content from the injection guard.
        decider = resolve_lexicon_decision_authorization(context)
        resolve_manual_add_provenance(context)
        fields = read_lexicon_proposal(params, context)
        pii_keep_exempt = fields.pop("pii_keep_exempt")
        entry = _insert(fields, status="confirmed", decider_account_id=decider)
        # Created and decided in one act -- the Postgres twin's INSERT sets both
        # from the same now(), so the mock must not drift them apart either.
        entry["decided_at"] = entry["created_at"]
        return {
            **lexicon_entry_view(entry),
            "pii_keep_exempt": pii_keep_exempt,
            "added": True,
        }

    def _decide(
        params: dict[str, Any], context: "ToolExecutionContext", action: str
    ) -> dict[str, Any]:
        from_status, to_status, _audit = LEXICON_DECISIONS[action]
        entry_id, decider = read_lexicon_decision(params, context)
        entry = _find(entry_id)
        # Guarded on the FROM status: a redelivered decision, or one aimed at a
        # row in another state, returns the current row unchanged rather than
        # re-deciding it. Missing id -> not_found (raised by _find above).
        if entry["status"] == from_status:
            entry["status"] = to_status
            entry["decider_account_id"] = decider
            entry["decided_at"] = now()
            entry["updated_at"] = entry["decided_at"]
        return lexicon_entry_view(entry)

    def edit_lexicon_entry(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # D7: IN-PLACE UPDATE, and the entry id is STABLE. An edited entry is the
        # same entry -- S09's entry_ref, S10's blast-radius join and S26's
        # per-entry health score all key on the id, and `hit_count` is the
        # accumulated evidence of use, so none of them may be reset by a typo fix.
        # Status/decider/decided_at are untouched: an edit is not a decision, and
        # WHO edited is recorded on the audit row (Postgres twin), not by
        # overwriting who decided. Retire-then-add remains the different intent
        # ("that mapping was wrong, kill it and start a new one").
        #
        # The editor is dropped here because the mock has no audit sink to write
        # it to -- inventing one would be a mock/Postgres divergence, not
        # lockstep. That the SHARED resolver names the acting admin is pinned
        # directly, by test_the_edit_resolver_names_the_acting_admin_as_the_editor
        # (S02 review finding G).
        entry_id, _editor, changes = read_lexicon_edit(params, context)
        entry = _find(entry_id)
        if entry["status"] not in LEXICON_EDITABLE_STATUSES:
            raise not_editable_error(entry_id, entry["status"])
        _reject_duplicate(
            entry["domain"],
            changes.get("surface_form", entry["surface_form"]),
            ignore=entry_id,
        )
        entry.update(changes)
        entry["updated_at"] = now()
        return lexicon_entry_view(entry)

    def list_lexicon_entries(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Admin-only read (see _AGENT_EXCLUDED_ACTIONS, the list_agent_experience
        # precedent) -- never reached by a live agent's tool loop. S02 EXTENDS
        # this one action with the console's queue filters rather than adding a
        # second read.
        status, domain = read_lexicon_filters(params)
        entries = [
            entry
            for entry in store
            if (status is None or entry["status"] == status)
            and (domain is None or entry["domain"] == domain)
        ]
        # Mock/Postgres divergence #1 (S01 review): Postgres ORDERs BY created_at
        # DESC and the mock returned insertion order, so the queue would have
        # inherited a disagreement between the twins. Sorting the REVERSED list
        # keeps newest-inserted first among same-timestamp ties (sorted is
        # stable), which is the closest honest match to the SQL.
        entries = sorted(
            reversed(entries), key=lambda e: e["created_at"], reverse=True
        )
        return {
            "entries": [lexicon_entry_view(e) for e in entries],
            "lexicon_version": _lexicon_version(store),
        }

    return {
        "toee_semantic_lexicon": {
            "propose_lexicon_entry": propose_lexicon_entry,
            "list_lexicon_entries": list_lexicon_entries,
            "add_lexicon_entry": add_lexicon_entry,
            "edit_lexicon_entry": edit_lexicon_entry,
            "confirm_lexicon_entry": lambda p, c: _decide(p, c, "confirm_lexicon_entry"),
            "reject_lexicon_entry": lambda p, c: _decide(p, c, "reject_lexicon_entry"),
            "retire_lexicon_entry": lambda p, c: _decide(p, c, "retire_lexicon_entry"),
        }
    }
