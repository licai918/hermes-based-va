"""Mock handlers for ``toee_customer_memory`` (ports mock/memory.ts, ADR-0114).

Implements the v1 Customer Memory actions over the fixed four preference slots of
ADR-0111: open-ended keys are rejected rather than silently stored. Memory binds
to the verified ``shopify_customer_id`` from the Session Identity Snapshot
(``context.identity``, ADR-0043) or, when unverified, to a canonical provisional
channel key derived from context — fail-closed when no channel identity resolves,
never a shared bucket (:func:`resolve_customer_memory_binding`, ADR-0112, PRD
FR-5/S02). Reads honor an injected baseline so a scenario ``memory_preset``
is reflected on first read (ADR-0113 lightweight injection). Writes are
explicit-only: this driver never infers or fabricates a preference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...content_scan import scan_injection
from ...errors import ToolDriverError
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext

# The four v1 Customer Memory preference slots (ADR-0111). Only these slots may be
# written, cleared, or read; anything else is a governed rejection.
MEMORY_PREFERENCE_SLOTS: tuple[str, ...] = (
    "contact_time_preference",
    "channel_preference",
    "delivery_habit_note",
    "communication_style_note",
)

# Framework-derived write sources (PRD FR-2/FR-3, RK-1). ``customer_explicit``,
# ``employee_confirmed``, and ``copilot_agent`` are set by
# :func:`resolve_memory_write_source`, never by a model-supplied tool param.
# ``merged_provisional`` is reserved for the async provisional-to-verified merge
# path (S10) and is not produced by either write handler in this module -- it is
# listed here so the enum never needs a second change when that path lands.
MEMORY_SOURCE_VALUES: tuple[str, ...] = (
    "customer_explicit",
    "employee_confirmed",
    "copilot_agent",
    "merged_provisional",
)

# Named handles onto the four MEMORY_SOURCE_VALUES entries -- unpacked FROM the
# tuple (not re-typed as separate literals) so every emit site (the resolver
# below, and the S10 merge SQL in postgres_gateway_store.py) shares the exact same
# object the enum holds. A future reorder/add/remove in MEMORY_SOURCE_VALUES fails
# this unpacking at import time instead of silently drifting a scattered literal
# out of sync with it.
(
    MEMORY_SOURCE_CUSTOMER_EXPLICIT,
    MEMORY_SOURCE_EMPLOYEE_CONFIRMED,
    MEMORY_SOURCE_COPILOT_AGENT,
    MEMORY_SOURCE_MERGED_PROVISIONAL,
) = MEMORY_SOURCE_VALUES

# The audit action a genuine L4 value change records (0.0.5 S07, FR-9). Named
# here beside the predicate below because the emit site (the Postgres handler's
# ``insert_audit``) and every later COUNT of these rows -- S22's conflict-rate
# metric is SQL over exactly this action -- must spell it the same way.
MEMORY_ACTION_PREFERENCE_UPDATED = "preference_updated"

# The SUMMARY audit action a whole-binding erase records (0.0.5 S11, FR-13),
# one per binding it touches, alongside the per-slot ``preference_cleared`` rows
# the looped clear already writes. Named here for the same reason as the line
# above, and one stronger: FR-14's deletion-success tripwire is a query ANCHORED
# on exactly this action, so the emit site and the query must not drift.
MEMORY_ACTION_ERASED = "memory_erased"

# FR-14's window N, in days: how long after an erase a binding is watched. Any
# slot row still on -- or back on -- an erased binding inside this window is
# flagged. A named constant per D16, because S22's knob panel renders it rather
# than hunting a magic number.
ERASE_REAPPEARANCE_WINDOW_DAYS = 30


def is_differing_value_overwrite(old_value: Any, new_value: str) -> bool:
    """The "differing-value overwrite" rule, in ONE place (0.0.5 S07, FR-9).

    True only when a PRIOR value existed and the write genuinely changes it.
    ``old_value is None`` is the slot's first-ever write: already fully
    attributed by the slot row itself (source/actor/created_at), so a "changed
    from nothing" audit row would be pure noise -- and S22 defines conflict rate
    over *differing-value overwrites*, so counting every new slot as a conflict
    would inflate it outright. An identical re-write (the common re-confirm)
    changes nothing and is likewise not a conflict.

    Named and shared rather than inlined at the emit site because S22 must
    re-derive exactly this definition for its metric, and two independent
    spellings of one rule are how the two silently drift apart.
    """
    return old_value is not None and old_value != new_value


# ADR-0111 slots hold a short preference note (e.g. "after 2pm"), not free text;
# PRD FR-3 caps the stored value so a write can't smuggle an essay into a slot.
MEMORY_VALUE_MAX_LENGTH = 200

# ``evidence`` (the optional verbatim customer phrase kept for audit, PRD FR-3) is
# a quoted excerpt rather than a slot value, so it gets a looser but still bounded
# ceiling -- same governed-rejection treatment as MEMORY_VALUE_MAX_LENGTH, just a
# larger cap, so a write can't smuggle an unbounded essay in via evidence either.
MEMORY_EVIDENCE_MAX_LENGTH = 500


@dataclass(frozen=True)
class MemoryMockData:
    # Slot map injected for the active identity binding before a turn runs — the
    # mock equivalent of ADR-0113 lightweight injection (a scenario
    # ``memory_preset``). Default empty: nothing is remembered until an explicit
    # write happens.
    preferences: dict[str, str] = field(default_factory=dict)


# Baseline fixtures: empty, so nothing is remembered without an explicit write.
memory_baseline_data = MemoryMockData()


def _is_preference_slot(value: Any) -> bool:
    return isinstance(value, str) and value in MEMORY_PREFERENCE_SLOTS


def _require_slot(params: dict[str, Any]) -> str:
    """Resolve the target slot from ``key`` (the v1 param) or its ``slot`` alias.

    Open-ended preference keys are rejected per ADR-0111 rather than silently
    stored, so an inferred or non-v1 write never lands in memory.
    """
    requested = params.get("key")
    if requested is None:
        requested = params.get("slot")
    if not _is_preference_slot(requested):
        raise ToolDriverError(
            "unexpected_error",
            (
                f'Customer Memory rejects open-ended preference key "{requested}"; '
                "only the four v1 slots are allowed (ADR-0111)."
            ),
        )
    return requested


def _require_value(params: dict[str, Any]) -> str:
    """Resolve and validate ``value``: a string, capped at 200 chars (PRD FR-3)."""
    value = params.get("value")
    if not isinstance(value, str):
        raise ToolDriverError(
            "unexpected_error", "upsert_preference requires a string value."
        )
    if len(value) > MEMORY_VALUE_MAX_LENGTH:
        raise ToolDriverError(
            "unexpected_error",
            "Customer Memory rejects a value longer than "
            f"{MEMORY_VALUE_MAX_LENGTH} characters.",
        )
    return value


def _read_evidence(params: dict[str, Any]) -> str | None:
    """Resolve the optional ``evidence`` param: a string, capped at 500 chars."""
    evidence = params.get("evidence")
    if evidence is None:
        return None
    if not isinstance(evidence, str):
        raise ToolDriverError(
            "unexpected_error",
            "upsert_preference evidence must be a string when provided.",
        )
    if len(evidence) > MEMORY_EVIDENCE_MAX_LENGTH:
        raise ToolDriverError(
            "unexpected_error",
            "Customer Memory rejects evidence longer than "
            f"{MEMORY_EVIDENCE_MAX_LENGTH} characters.",
        )
    return evidence


def scan_memory_write(value: str, evidence: str | None) -> None:
    """L4's whole write scan, in ONE place both twins call (0.0.5 S08, FR-10).

    Mirrors L6's ``scan_agent_experience_write`` and L7's ``scan_lexicon_write``:
    one named resolver per layer, imported by the mock driver AND the Postgres
    datastore handler, so the two cannot drift on what a governed rejection is
    (NFR-7, the S15/S21 lesson). Raises ``policy_blocked``; returns nothing,
    because L4 stores exactly what it was given or nothing at all.

    **Injection ONLY. The PII leg is deliberately NOT applied, and that is the
    whole reason this function exists rather than a bare ``scan_injection`` call
    at each site.** NFR-6's no-PII rule governs the SHARED layers (L6/L7); L4 is
    the layer customer PII legitimately lives in, bound to its own customer (D2).
    A correct delivery habit reads ``leave at back door, call 604-555-1212``, and
    ``scan_pii``'s phone heuristic would ``policy_blocked`` it. Adding
    :func:`toee_hermes.content_scan.scan_pii` here would not harden L4; it would
    break the one layer that is supposed to remember a customer.

    **Hard-reject, never scrub-and-store.** A slot value is re-injected into the
    prompt every turn, so instructions hidden in one are a live prompt-injection
    surface -- but a sanitized value that still persists would record something
    the customer never said, in the store a rep reads to decide what to do. So
    the write fails and the prior value stands.

    ``evidence`` is scanned too, on a weaker but real justification: unlike the
    slot value it is NOT injected into the turn prompt (``get_preferences``
    withholds it deliberately), so it is not a live injection surface today. It
    is a verbatim customer phrase persisted for audit and rendered to a human in
    the Memory Audit console -- and S16's copilot triage will read the same rows
    back to a model. Rejecting the write is also the only coherent option: the
    value and its evidence are one governed write, so accepting half of one would
    store a slot whose stated justification was thrown away.

    The read-side fence (``hooks._fence_safe``, S06) stays as defence in depth
    for rows written before this guard existed; it is not a substitute for it --
    escaping a stored instruction still leaves the instruction stored.
    """
    scan_injection(value, evidence)


def is_verified_customer_identity(identity: Any) -> bool:
    """True when ``identity`` is a resolved Session Identity Snapshot for a
    VERIFIED customer (``identity["outcome"] == "verified_customer"``).

    The SAME signal :func:`binding_key_from_identity` uses to bind to the
    Shopify customer id rather than a provisional channel key. 0.0.3 S21 (FR-21,
    NFR-2) reuses it as the verified-only gate for EXTERNAL customer
    self-service (the customer-safe summary read and the customer's own
    governed clear): an unverified caller -- unmatched, provisional, or
    ambiguous -- still resolves a binding (their own provisional channel key,
    see ``test_unmatched_caller_outcome_still_binds_provisionally_from_context``)
    but is NOT a verified customer, so self-service must still refuse it
    (fail-closed, US13) -- a resolvable binding alone is not authorization.
    """
    return isinstance(identity, dict) and identity.get("outcome") == "verified_customer"


def binding_key_from_identity(identity: Any) -> tuple[str, str] | None:
    """Pure identity dict -> ``(binding_key, binding_kind)`` core, or ``None``.

    The security-sensitive derivation shared by BOTH the governed WRITE path
    (:func:`resolve_customer_memory_binding`) and the turn-time READ injection
    (openrouter/copilot, S07/S08): reads and writes MUST compute a byte-identical
    key for a given identity or the memory round-trip silently returns nothing.

    A verified Session Identity Snapshot (``identity["outcome"] ==
    "verified_customer"``) binds to its Shopify customer id, kind ``"verified"``.
    Otherwise the caller's ingress-controlled channel identity
    (``identity["channel"]`` / ``["channel_identity"]``, S01) is canonicalized to
    ``provisional:{channel}:{E.164}`` (e.g. ``provisional:sms:+17786803250``), kind
    ``"provisional"`` — never a model-supplied param (RK-3). A degenerate channel
    identity (missing, empty, or normalizing to a bare ``"+"``) yields ``None``, not
    a shared bucket.

    Returns ``None`` when nothing resolves — the caller decides the fail-closed
    policy: the write path raises ``policy_blocked``; the read path injects nothing.
    """
    # Deferred import: this module loads as part of ``drivers.mock``'s own package
    # init (which ``toee_hermes.plugin`` imports in turn), so importing ``gateway``
    # at module scope here would re-enter that partially-initialized package during
    # a cold import and raise ImportError.
    from ...gateway.normalize import canonicalize_email, is_email_channel, normalize_e164

    if not isinstance(identity, dict):
        return None

    if is_verified_customer_identity(identity):
        shopify_customer_id = identity.get("shopify_customer_id")
        if isinstance(shopify_customer_id, str) and shopify_customer_id:
            return shopify_customer_id, "verified"

    channel = identity.get("channel")
    channel_identity = identity.get("channel_identity")
    if isinstance(channel, str) and channel and isinstance(channel_identity, str):
        # S17: email channel identities are addresses, not phones — canonicalize
        # them (never E.164, which strips an address to a bare "+"). SMS keeps the
        # E.164 normalization so the provisional key round-trips byte-for-byte.
        if is_email_channel(channel):
            normalized = canonicalize_email(channel_identity)
            if normalized:
                return f"provisional:{channel}:{normalized}", "provisional"
        else:
            normalized = normalize_e164(channel_identity)
            if normalized != "+":
                return f"provisional:{channel}:{normalized}", "provisional"

    return None


def resolve_customer_memory_binding(
    context: "ToolExecutionContext", params: dict[str, Any]
) -> tuple[str, str]:
    """Resolve ``(binding_key, binding_kind)`` for a WRITE, fail-closed (S02, FR-5).

    Thin wrapper over :func:`binding_key_from_identity` (the shared pure core) that
    adds the one write-only concern: the fail-closed ``policy_blocked`` raise. Kept
    here since hermes-runtime already imports ``MEMORY_PREFERENCE_SLOTS`` from this
    module as the single source of truth for the slot enum.

    Binding is context-only on EVERY profile — ``params`` is accepted for call-shape
    symmetry with the other handlers but never consulted. The former
    ``internal_copilot`` ``channel_identity_id`` carve-out (a model-supplied param
    could mint a ``provisional:{param}`` key when context had no identity) is
    removed (R3, PRD FR-5, S04): a Workbench correction now binds via the case's
    resolved identity (S16, ``tool_dispatch_app._resolve_case_identity``), not a
    model-named param.

    No resolvable identity at all raises a fail-closed ``policy_blocked``; neither
    the bare shared ``"provisional"`` key from pre-S02 nor the model-named
    ``provisional:{param}`` key from the removed carve-out is ever produced.
    """
    # ``params`` is unused: matches the (context, params) call convention the other
    # handlers share; binding itself never consults model-supplied params (R3).
    resolved = binding_key_from_identity(context.identity)
    if resolved is not None:
        return resolved

    raise ToolDriverError(
        "policy_blocked",
        "Customer Memory requires a resolvable channel identity; the turn has "
        "none (fail-closed, ADR-0112 / PRD FR-5).",
    )


def resolve_memory_write_source(context: "ToolExecutionContext") -> str:
    """Framework-derived ``source`` for a preference write (RK-1, PRD FR-2/§9).

    ONE shared resolver for both the mock and Postgres datastore handlers, same
    reasoning as :func:`resolve_customer_memory_binding`: this is
    security-sensitive governance logic that must not drift between the two.

    Never taken from the model-supplied tool params -- the model cannot forge
    ``employee_confirmed`` for an inferred write. The External Customer Service
    Profile always writes ``customer_explicit``. The Internal Copilot Profile
    discriminates on ``context.user_id`` (PRD §9): the dispatch route sets it
    from the request's ``actor_account_id`` when a rep is at the keyboard, so
    present -> a deliberate UI correction, ``employee_confirmed``; absent -> the
    unbound AI draft-turn write (S20), honestly labelled ``copilot_agent``
    rather than the (false) ``employee_confirmed`` a profile-only check used to
    give it. ``merged_provisional`` is set only by the merge path (S10), never
    by this resolver. Any other profile is fail-closed -- ``toee_customer_
    memory`` is not allowlisted outside these two today (ADR-0034/35), so this
    is defense in depth, not a reachable path.
    """
    # Deferred import: same partially-initialized-package hazard documented on
    # resolve_customer_memory_binding above.
    from ...plugin.profiles import EXTERNAL, INTERNAL

    if context.profile == EXTERNAL:
        return MEMORY_SOURCE_CUSTOMER_EXPLICIT
    if context.profile == INTERNAL:
        if context.user_id:
            return MEMORY_SOURCE_EMPLOYEE_CONFIRMED
        return MEMORY_SOURCE_COPILOT_AGENT
    raise ToolDriverError(
        "policy_blocked",
        f'Customer Memory writes are not permitted for profile "{context.profile}".',
    )


def resolve_clear_authorization(context: "ToolExecutionContext") -> tuple[str | None, str]:
    """Framework-derived ``(account_id, initiator)`` gate for a governed
    ``clear_preference`` (0.0.3 S20/S21, FR-20/FR-21).

    ONE shared resolver for both the mock and Postgres datastore handlers --
    same reasoning as :func:`resolve_memory_write_source` and
    :func:`resolve_customer_memory_binding`: this is the security-sensitive
    authorization gate for the clear action, and a duplicated gate is exactly
    the kind of thing that silently drifted before (the S15 mock/dismiss
    audit-sink gap). Raises the fail-closed ``ToolDriverError("policy_blocked",
    ...)`` itself when unauthorized, so both call sites just call it and use
    the returned tuple:

    - EXTERNAL + a verified customer identity (:func:`is_verified_customer_identity`)
      -> ``(None, "customer")``: the customer clearing their own binding: no
      ``account_id`` since the customer is not a workbench account.
    - EXTERNAL + not verified (unmatched, provisional, or ambiguous) ->
      ``policy_blocked`` -- a resolvable provisional binding is not
      authorization (US13).
    - INTERNAL + ``context.user_id`` -> ``(context.user_id, "rep")``.
    - INTERNAL with no ``context.user_id`` -> ``policy_blocked`` -- a clear is
      always an attributed actor at the keyboard, never the unbound AI draft
      turn.
    - Any other profile -> ``policy_blocked`` (fail-closed, defense in depth --
      ``toee_customer_memory`` is not allowlisted outside these two today,
      ADR-0034/35, same posture as ``resolve_memory_write_source``).
    """
    # Deferred import: same partially-initialized-package hazard documented on
    # resolve_memory_write_source above.
    from ...plugin.profiles import EXTERNAL, INTERNAL

    if context.profile == EXTERNAL:
        if is_verified_customer_identity(context.identity):
            return None, "customer"
        raise ToolDriverError(
            "policy_blocked",
            "A governed preference clear requires a verified customer identity.",
        )
    if context.profile == INTERNAL:
        if context.user_id:
            return context.user_id, "rep"
        raise ToolDriverError(
            "policy_blocked",
            "A governed preference clear requires an attributed actor.",
        )
    raise ToolDriverError(
        "policy_blocked",
        f'Customer Memory clears are not permitted for profile "{context.profile}".',
    )


def resolve_erase_authorization(context: "ToolExecutionContext") -> tuple[str, str]:
    """Framework-derived ``(account_id, initiator)`` gate for the whole-binding
    erase (0.0.5 S11, FR-13, US7). ONE shared resolver, both twins (NFR-7).

    COMPOSES :func:`resolve_clear_authorization` rather than restating it -- the
    erase is a loop over the existing per-slot clear, so it must not be able to
    authorize a clear the clear itself would refuse -- and then adds the one
    thing an erase needs on top: **an attributed actor is mandatory**.

    That extra requirement is not decoration. ``resolve_clear_authorization``
    deliberately returns ``(None, "customer")`` for a verified EXTERNAL customer
    clearing their own slot (FR-21), and the erase's ``4+1`` audit rows are
    attributed to a supervisor. A row asserting "somebody erased this customer's
    whole memory" with nobody attached is unfalsifiable provenance -- the exact
    shape D20 refused for ``admin_manual`` -- so this is fail-closed
    ``policy_blocked``, on the single most destructive governed action there is.
    Org-wide / customer-initiated erasure is PRD §6, not this action.

    Returns the tuple (not a bare id) so the audit rows keep deriving their
    ``initiator`` instead of hardcoding the only value that can reach them.
    """
    account_id, initiator = resolve_clear_authorization(context)
    if not account_id:
        raise ToolDriverError(
            "policy_blocked",
            "A whole-binding memory erase requires an attributed administrator.",
        )
    return account_id, initiator


def erase_binding_keys(
    context: "ToolExecutionContext",
    linked_channel_identities: Any = (),
) -> list[str]:
    """Every binding key one erase must clear, deduped, in a deterministic order
    (0.0.5 S11, FR-13, D10). ONE shared derivation, both twins (NFR-7).

    The primary binding comes first, from the same fail-closed
    :func:`resolve_customer_memory_binding` every other L4 write uses -- so no
    resolvable identity is ``policy_blocked`` here too, before anything is
    deleted.

    **Why there is ever more than one.** ``merge_provisional_memory`` copies
    provisional slots from every linked channel identity onto the verified key
    on the customer's next verified turn. An erase that stopped at the verified
    binding would therefore be silently undone by the customer's next SMS, and
    the FR-14 tripwire would fire on the erase's own aftermath rather than on a
    real event (D10 inverts S11's original acceptance for exactly this reason).
    So the caller's OWN pre-verification provisional key is derived from the
    identity's channel fields (a verified identity short-circuits
    ``binding_key_from_identity`` to its Shopify id, so the channel form has to
    be asked for separately -- the same move ``openrouter._provisional_key_for``
    makes), and ``linked_channel_identities`` -- ``(channel, channel_identity)``
    pairs from the Identity Graph -- contributes the rest.

    The mock twin passes nothing there and cannot pass anything: it has no
    ``identity_link`` store, and equally no merge path, so it has no linked
    provisional slots to leave behind. The Postgres twin, which owns both, reads
    the links and passes them.
    """
    keys = [resolve_customer_memory_binding(context, {})[0]]
    identity = context.identity if isinstance(context.identity, dict) else {}
    candidates = [(identity.get("channel"), identity.get("channel_identity"))]
    candidates.extend(linked_channel_identities)
    for channel, channel_identity in candidates:
        resolved = binding_key_from_identity(
            {"channel": channel, "channel_identity": channel_identity}
        )
        if resolved is not None and resolved[0] not in keys:
            keys.append(resolved[0])
    return keys


# FR-14's tile label. The metric is "cleared and STAYED cleared", so it reports
# a rate over erases rather than a count of deletions -- a deletion count says
# nothing about whether the data came back.
DELETION_SUCCESS_LABEL = (
    "Share of erases in the window whose bindings are still empty. A flagged "
    "binding is either residue (a row the erase itself left) or a re-appearance "
    "(a row written afterwards) -- both are alerts for a human, never an "
    "automatic re-delete."
)


def deletion_success_payload(
    *,
    erased_bindings: int = 0,
    flagged_bindings: int = 0,
    residue_bindings: int = 0,
    reappeared_bindings: int = 0,
    flagged_slots: Any = (),
) -> dict[str, Any]:
    """The FR-14 metric's shape, built in ONE place both twins call.

    Shared rather than restated (the ``empty_latency_metrics`` lesson, one step
    further -- ``hermes_runtime`` already imports this module, so the mock twin's
    zero payload and the Postgres twin's real one are literally the same
    function rather than two spellings pinned by an equality test).

    Carries **counts and slot names only, never a binding key**: a binding key
    is the customer's raw identity (a Shopify id or their phone/email), and this
    payload renders on an org-wide admin panel. Slot names are the four ADR-0111
    enum values, so they identify nobody.
    """
    return {
        "window_days": ERASE_REAPPEARANCE_WINDOW_DAYS,
        "erased_bindings": erased_bindings,
        "flagged_bindings": flagged_bindings,
        # A single binding can be both (residue plus a later write), so these
        # two do not have to sum to flagged_bindings.
        "residue_bindings": residue_bindings,
        "reappeared_bindings": reappeared_bindings,
        "rate": (
            round((erased_bindings - flagged_bindings) / erased_bindings, 4)
            if erased_bindings
            else None
        ),
        "flagged_slots": dict(flagged_slots),
        "label": DELETION_SUCCESS_LABEL,
    }


def create_memory_mock_handlers(
    data: MemoryMockData = memory_baseline_data,
    *,
    evidence_store: dict[str, dict[str, str]] | None = None,
) -> MockHandlerRegistry:
    """Build ``toee_customer_memory`` handlers backed by a per-binding store.

    A fresh store is created per factory call and closed over by the handlers, so
    in-memory writes persist across calls within one handler-set instance while
    staying isolated per identity binding. Each binding is lazily seeded from the
    injected baseline so a scenario ``memory_preset`` is honored on first read.

    ``evidence_store``, when supplied, is mutated in place with each write's
    ``evidence`` (``binding_key -> {slot: evidence}``) -- mirrors the datastore
    handler's ``evidence`` column so a caller (a test, mainly) can prove evidence
    is actually persisted and retrievable, not just echoed back on the same call
    (PRD FR-3). Not exposed through ``get_preferences``, matching how ``source``
    already isn't -- both are write-time governance/audit metadata, not part of
    the live preference value re-injected into the prompt every turn (RK-2).
    """
    store: dict[str, dict[str, str]] = {}
    evidence: dict[str, dict[str, str]] = (
        {} if evidence_store is None else evidence_store
    )

    def slots_for(binding_key: str) -> dict[str, str]:
        slots = store.get(binding_key)
        if slots is None:
            slots = dict(data.preferences)
            store[binding_key] = slots
        return slots

    def upsert_preference(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Records one explicit preference slot and echoes the stored value
        # (scenario 24). The Tool Gate — not this driver — enforces that the write
        # came from explicit customer language (ADR-0114).
        slot = _require_slot(params)
        value = _require_value(params)
        write_evidence = _read_evidence(params)
        # S08 (FR-10): the shared L4 write scan, same call as the Postgres twin.
        # Placed after the type/length checks so those keep their own governed
        # error class, and before any store mutation so a rejection leaves the
        # slot exactly as it was.
        scan_memory_write(value, write_evidence)
        # RK-1: source is framework-derived from context.profile, never the
        # model-supplied params — any "source" the caller passed is ignored.
        source = resolve_memory_write_source(context)
        binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
        slots_for(binding_key)[slot] = value
        if write_evidence is not None:
            evidence.setdefault(binding_key, {})[slot] = write_evidence
        return {
            "binding_key": binding_key,
            "slot": slot,
            "value": value,
            "source": source,
            "evidence": write_evidence,
            "stored": True,
        }

    def clear_preference(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Clears one preference slot and acknowledges the removal. The gate --
        # who is authorized to clear (rep/supervisor with an attributed actor,
        # or a verified EXTERNAL customer clearing their own binding) -- lives
        # in the shared resolve_clear_authorization (see its docstring for the
        # full S20/S21 rationale), the SAME resolver the Postgres handler calls,
        # so the two twins can't drift the way the S15 mock/dismiss gate did.
        # The Postgres handler additionally writes a preference_cleared audit
        # row from the returned (account_id, initiator); this mock driver has
        # no audit sink (same no-op-in-mock-mode convention as
        # dismiss_proposal), so it only needs the gate check here.
        slot = _require_slot(params)
        resolve_clear_authorization(context)
        binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
        slots_for(binding_key).pop(slot, None)
        # ``evidence`` is a SECOND store here, where the Postgres twin has a
        # COLUMN on the row it just deleted -- so popping only the slot map left
        # the verbatim customer phrase behind and the two twins disagreed about
        # what a clear removes (NFR-7). One line, on the shared path, so the S11
        # erase that loops this clear inherits it rather than fixing it twice.
        evidence.get(binding_key, {}).pop(slot, None)
        return {"binding_key": binding_key, "slot": slot, "cleared": True}

    def erase_customer_memory(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # 0.0.5 S11 (FR-13, US7): the whole-binding erase -- a governed LOOP over
        # the four slots and every binding this customer reaches, not a new write
        # primitive. The gate and the key derivation are the shared resolvers the
        # Postgres twin calls (NFR-7); the audit rows are the Postgres twin's
        # alone, same no-audit-sink-in-mock-mode convention as clear_preference.
        resolve_erase_authorization(context)
        bindings = []
        cleared_total = 0
        for binding_key in erase_binding_keys(context):
            slots = slots_for(binding_key)
            cleared = [slot for slot in MEMORY_PREFERENCE_SLOTS if slot in slots]
            # The whole binding, not just the four slots this build knows about:
            # `slots.clear()` after recording the enum outcomes means a key that
            # somehow holds anything else goes too. Scoped to ONE binding_key --
            # the neighbouring binding's dict is a different object.
            extra = len(slots) - len(cleared)
            slots.clear()
            evidence.pop(binding_key, None)
            cleared_total += len(cleared)
            bindings.append(
                {
                    "binding_key": binding_key,
                    "cleared_slots": cleared,
                    "extra_rows_removed": extra,
                }
            )
        return {
            "binding_key": bindings[0]["binding_key"],
            "bindings": bindings,
            "cleared": cleared_total,
            "erased": True,
        }

    def get_preferences(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Returns the current preference slots for the active binding, honoring any
        # injected baseline (scenario 25).
        binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
        return {
            "binding_key": binding_key,
            "preferences": dict(slots_for(binding_key)),
        }

    def get_my_memory_summary(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # 0.0.3 S21 (FR-21, NFR-2): the customer-facing "what do you remember
        # about me" read -- verified-only (same signal as the extended
        # clear_preference gate above), and strips ALL internal metadata: slot
        # values only, no source, no actor, no timestamps, no binding_key. An
        # unverified caller (unmatched/provisional/ambiguous) must get ZERO
        # data, never a probe surface for whoever holds a phone number/email
        # (US13) -- a resolvable provisional binding is not authorization.
        # NOTE: despite the "customer-facing" framing, this action is also
        # LLM-callable on internal_copilot -- it isn't in _AGENT_EXCLUDED_ACTIONS,
        # so it rides the shared toolset registration onto INTERNAL's tool loop
        # too. Not a gap: INTERNAL already has get_preferences, a superset read.
        if not is_verified_customer_identity(context.identity):
            raise ToolDriverError(
                "policy_blocked",
                "Customer Memory self-service requires a verified customer "
                "identity.",
            )
        binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
        return {"preferences": dict(slots_for(binding_key))}

    def dismiss_proposal(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # 0.0.3 S15 (FR-16/US17): a dismissed proposal persists NO slot -- a bad
        # guess can't quietly land in memory. Only the Postgres datastore handler
        # records the FR-17 audit row (this mock driver has no audit sink, same
        # no-op-in-mock-mode convention as every other governed write here), so
        # this is just a governed acknowledgment.
        slot = _require_slot(params)
        _require_value(params)
        # Requires an attributed actor, same gate as the Postgres twin
        # (_dismiss_proposal): a dismissal is always a rep at the keyboard, never
        # the customer and never the unbound AI draft turn -- so on the EXTERNAL
        # profile (no context.user_id) this is policy_blocked, same as every
        # other governed write on toee_customer_memory (FR-16).
        if not context.user_id:
            raise ToolDriverError(
                "policy_blocked",
                "A governed proposal dismissal requires an attributed actor.",
            )
        binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
        return {"binding_key": binding_key, "slot": slot, "dismissed": True}

    def get_memory_audit(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # 0.0.3 S20 (FR-20): the Supervisor Memory Audit View read. Shape-compatible
        # with the Postgres handler (same keys) so a caller can't drift between
        # backends, but the mock has no per-write source/actor/timestamp store and
        # no audit sink (same convention as dismiss_proposal/clear_preference above)
        # -- source/actor/timestamps come back null and audit is always empty (so
        # there is never a row lacking the Postgres twin's joined actor_username --
        # the empty list is itself the documented null for that field). 0.0.5 S07
        # (FR-9) extends the Postgres twin's audit sink with a preference_updated
        # row on a genuine value change -- the same convention holds here: this
        # mock still never emits one, "audit": [] stays the documented null even
        # after a real change (test_get_memory_audit_history_stays_empty_after_a_
        # real_value_change, hermes/tests/test_memory.py). What DOES stay in
        # lockstep is the write itself: upsert_preference below unconditionally
        # overwrites and returns the same shape whether the value changed or
        # not, exactly like the Postgres handler's write step (only the audit
        # is gated there, never the write).
        binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
        slots = [
            {
                "slot_name": slot,
                "slot_value": value,
                "source": None,
                "actor_account_id": None,
                "evidence": evidence.get(binding_key, {}).get(slot),
                "created_at": None,
                "updated_at": None,
            }
            for slot, value in slots_for(binding_key).items()
        ]
        # 0.0.5 S22 (FR-34a): the memory-health strip's last-injection recency
        # comes from the injection ledger, which is Postgres-only -- there is no
        # ledger behind the mock backend and no turn writes one. `None` is the
        # documented null here for the same reason `audit` is `[]`, and the
        # strip renders it as "never", not as a fabricated timestamp.
        return {
            "binding_key": binding_key,
            "slots": slots,
            "audit": [],
            "last_injection_at": None,
        }

    return {
        "toee_customer_memory": {
            "upsert_preference": upsert_preference,
            "clear_preference": clear_preference,
            "erase_customer_memory": erase_customer_memory,
            "get_preferences": get_preferences,
            "get_my_memory_summary": get_my_memory_summary,
            "dismiss_proposal": dismiss_proposal,
            "get_memory_audit": get_memory_audit,
        }
    }
