"""Mock handlers for ``toee_review_inbox`` (0.0.5 S15, FR-22).

The unified review inbox: ONE queue holding every pending memory decision, and
the ``review_item`` STORE that makes it possible.

**Why the store ships here and not with its emitters.** L6 and L7 proposals have
tables of their own, but the other four inbox kinds do not: S10 emits
``blast_radius`` reviews, S20 emits ``graduation`` and ``retirement_candidate``,
S25 routes ``persona_review`` -- and none of those slices defines any storage.
The gap audit found exactly that hole, so this module is designed for those four
emitters rather than for what the inbox happens to render today. Concretely, that
means: an emission action a scheduled job can call without a human
(``propose_review_item``), open-set idempotence so a job that runs every hour does
not manufacture a queue, the ``annotations`` column S16 writes into (D8), and a
``kind`` vocabulary that already contains D9's six values.

Every validator, gate and vocabulary here is imported by the Postgres twin
(``hermes-runtime/hermes_runtime/datastore/handlers/review_item.py``) -- ONE
resolver, both twins (NFR-7, the S15-0.0.4/S21-0.0.4 lesson), so the two paths
cannot drift on what a governed rejection is.

The MERGE itself is not here. The inbox reads the two proposal tables through
their own existing governed reads and this store through
``list_review_items``; merging and badging them is the admin BFF's job
(``apps/workbench/lib/bff/admin/review-inbox.ts``). Decisions likewise dispatch
to each layer's EXISTING governed decide actions -- this slice adds no decision
primitive for a proposal, only for the rows it owns.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional

from ...blast_radius import blast_radius_result, read_blast_radius_query
from ...content_scan import (
    PII_IN_VALUES_REDACT,
    read_proposer_context,
    scan_proposer_context,
)
from ...errors import ToolDriverError
from .driver import MockHandlerRegistry
from .semantic_lexicon import read_lexicon_proposal

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext

# D9 (BINDING, correcting the brief's five): the inbox's typed item kinds. The
# first two are rendered FROM their own tables; the rest are rows in this store.
PROPOSAL_ITEM_KINDS: tuple[str, ...] = ("l6_proposal", "l7_proposal")
REVIEW_ITEM_KINDS: tuple[str, ...] = (
    "graduation",
    "blast_radius",
    "persona_review",
    "retirement_candidate",
)
INBOX_ITEM_KINDS: tuple[str, ...] = PROPOSAL_ITEM_KINDS + REVIEW_ITEM_KINDS

REVIEW_ITEM_STATUS_OPEN = "open"
REVIEW_ITEM_STATUS_VALUES: tuple[str, ...] = ("open", "acknowledged", "dismissed")

# The two TERMINAL statuses a governed decision may land, mapped to their audit
# action. ONE table, both twins -- the LEXICON_DECISIONS precedent. "open" is
# deliberately absent: it is where an item starts, not somewhere an admin can put
# one back, and a re-open would erase the decider of the decision it undid.
#
# ONE action (``decide_review_item``) carries both, rather than the L7 pattern of
# one catalog action per transition. L7 needed the split because its three
# transitions guard on DIFFERENT from-statuses (retire may only touch a confirmed
# row); here both decisions come from ``open`` and differ only in the terminal
# value, so a second catalog action would mean a second row in all nine
# catalog-sync files to express one bit.
REVIEW_ITEM_DECISIONS: dict[str, str] = {
    "acknowledged": "review_item_acknowledged",
    "dismissed": "review_item_dismissed",
}

# Re-classify's routing table: source inbox kind -> target inbox kind. ONE entry
# today, and that is a decision rather than an oversight -- see
# read_reclassification.
RECLASSIFY_ROUTES: dict[str, str] = {"l6_proposal": "l7_proposal"}

# A subject_ref is a foreign key into whichever store the item is ABOUT (an
# agent_experience id, a lexicon entry id, an L4 binding_key + slot). Bounded so
# an emitter cannot use it as a payload channel.
REVIEW_ITEM_SUBJECT_REF_MAX_LENGTH = 200

# The human-readable half of a re-classification's provenance, written into the
# target's `evidence`. See reclassified_target_params for why it is not an id.
RECLASSIFIED_EVIDENCE_PREFIX = "Re-classified from an L6 proposal: "

UNATTRIBUTED_DECISION_MESSAGE = (
    "A governed review_item decision requires an attributed actor (ADR-0148: a "
    "decided item with no decider is unfalsifiable governance)."
)

# --- 0.0.5 S16 (FR-23): copilot triage annotations ----------------------------
#
# D8's shared column has exactly two reserved top-level keys. S13 owns
# `heuristic` (its write-time advisory), S16 owns `copilot` (this one), and
# neither writer ever reads-modifies-writes the whole column -- each assigns its
# own key, so the two cannot lost-update each other on the same row.
COPILOT_ANNOTATION_KEY = "copilot"
HEURISTIC_ANNOTATION_KEY = "heuristic"

# Which store each inbox kind lives in, and the status that means "still
# pending" there. ONE table, both twins: the Postgres handler UPDATEs `table`
# and the mock walks its own list. Its completeness against INBOX_ITEM_KINDS is
# a set-equality test (the LAYER_OF_ACTION shape), so a seventh kind cannot land
# annotatable-by-nobody.
#
# `agent_experience` / `semantic_lexicon` are here because FR-23 says EVERY
# pending proposal, not just the four kinds this store owns -- D8's whole reason
# for putting the column on three tables.
ANNOTATABLE_SOURCES: dict[str, tuple[str, str]] = {
    "l6_proposal": ("agent_experience", "proposed"),
    "l7_proposal": ("semantic_lexicon", "proposed"),
    "graduation": ("review_item", REVIEW_ITEM_STATUS_OPEN),
    "blast_radius": ("review_item", REVIEW_ITEM_STATUS_OPEN),
    "persona_review": ("review_item", REVIEW_ITEM_STATUS_OPEN),
    "retirement_candidate": ("review_item", REVIEW_ITEM_STATUS_OPEN),
}

# The bounded vocabulary a copilot annotation may express. NFR-3 is the whole
# reason it is bounded: an annotation informs a human triaging the queue and
# decides nothing, so the model is never allowed to invent a value here. An
# unrecognised recommendation becomes `unsure` rather than the model's own word.
ANNOTATION_RECOMMEND_APPROVE = "approve"
ANNOTATION_RECOMMEND_REJECT = "reject"
ANNOTATION_RECOMMEND_UNSURE = "unsure"
ANNOTATION_RECOMMENDATIONS: tuple[str, ...] = (
    ANNOTATION_RECOMMEND_APPROVE,
    ANNOTATION_RECOMMEND_REJECT,
    ANNOTATION_RECOMMEND_UNSURE,
)

# FR-23's four annotation shapes, as a closed flag set. A flag the model made up
# is dropped, not stored -- the admin surface renders these, and a free-text flag
# channel is a payload channel.
ANNOTATION_FLAGS: tuple[str, ...] = (
    "likely_duplicate",
    "conflicts",
    "pii_suspect",
    "lexicon_shaped",
)

# FR-23's three reference fields: "likely-duplicate-of X", "conflicts-with Y",
# "suggested canonical form". Free text, and therefore bounded and scanned.
ANNOTATION_REFERENCE_FIELDS: tuple[str, ...] = (
    "duplicate_of",
    "conflicts_with",
    "suggested_canonical_form",
)

# ponytail: one length for every free-text field. Long enough for the one-line
# reasoning FR-23 asks for, short enough that a model cannot use the annotation
# as a bulk channel onto a shared admin surface (NFR-6).
ANNOTATION_TEXT_MAX_LENGTH = 400

# The honest "nothing was annotated" reasons, shared so both twins and the batch
# job say the same thing. An annotation that was not produced is never a blank
# one: a rendered empty triage note reads as "the copilot had no concerns",
# which is the one answer an admin cannot check.
ANNOTATOR_UNAVAILABLE_MOCK = (
    "the mock driver has no annotator: copilot triage needs a model, and this "
    "driver is the DB-free substrate (the get_blast_radius precedent)"
)
ANNOTATOR_DISABLED = (
    "copilot triage annotations are off for this deployment "
    "(COPILOT_TRIAGE_ANNOTATIONS is unset or off -- default OFF, FR-23)"
)
ANNOTATOR_NO_MODEL = (
    "copilot triage has no annotator model on this process: OPENROUTER_API_KEY "
    "is not configured, so nothing was annotated and nothing was fabricated"
)


def resolve_review_item_annotator(context: "ToolExecutionContext") -> None:
    """Gate ONE advisory annotation write (ADR-0148 framework-derived).

    Asserts a profile and NOT an actor, for exactly ``resolve_review_item_
    emitter``'s reason and one more. The scheduled triage batch has no human at
    the keyboard, so requiring an actor would make the batch half of FR-23
    unreachable; and an annotation is inert by construction under NFR-3 -- it
    informs a human triaging the queue and retires, confirms, rejects and
    decides nothing. The DECISION is still where attribution becomes mandatory,
    and that gate (``resolve_review_item_authorization``) is unchanged.
    """
    from ...plugin.profiles import INTERNAL

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            "review_inbox triage annotations are not permitted for profile "
            f'"{context.profile}".',
        )


def read_annotation_request(params: dict[str, Any]) -> tuple[str, str, str]:
    """``(kind, item id, table)`` for one ``annotate_inbox_item`` call.

    ``kind`` is checked against :data:`ANNOTATABLE_SOURCES` -- i.e. all SIX
    inbox kinds, unlike ``read_review_item_emission``'s four. An annotation is
    not a second source of truth for a decision the proposal tables own; it is
    metadata beside the row, which is why it may legally land on a kind this
    store does not itself hold.
    """
    kind = _require_choice(params, "kind", tuple(ANNOTATABLE_SOURCES))
    item_id = _require_text(params, "id", REVIEW_ITEM_SUBJECT_REF_MAX_LENGTH)
    return kind, item_id, ANNOTATABLE_SOURCES[kind][0]


def _bounded_text(value: Any) -> str:
    """One free-text annotation field: a string, trimmed and length-capped."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:ANNOTATION_TEXT_MAX_LENGTH]


def annotation_payload(
    verdict: dict[str, Any], *, model: str, annotated_at: str
) -> dict[str, Any]:
    """The bounded ``copilot`` value BOTH twins store. Framework-derived.

    **This function is where NFR-3 and D24 are enforced, not in the prompt.**
    ``verdict`` is whatever fell out of a model's reply, so nothing in it is
    trusted to be a value: the recommendation is coerced into
    :data:`ANNOTATION_RECOMMENDATIONS` (an unrecognised one becomes ``unsure``,
    never the model's own word and never a default of ``approve``), flags are
    intersected with :data:`ANNOTATION_FLAGS`, free text is capped, and every
    other key the model invented is dropped on the floor. The result is a fixed
    shape with a fixed key set, so a model that "replies" with an instruction,
    a decision, or a payload produces an annotation that says ``unsure`` and
    carries its text as text.

    ``model`` and ``annotated_at`` are FRAMEWORK-derived and overwrite anything
    of the same name in ``verdict``: provenance a model can author is not
    provenance.
    """
    recommendation = verdict.get("recommendation")
    if recommendation not in ANNOTATION_RECOMMENDATIONS:
        recommendation = ANNOTATION_RECOMMEND_UNSURE
    raw_flags = verdict.get("flags")
    flags = (
        [f for f in ANNOTATION_FLAGS if f in raw_flags]
        if isinstance(raw_flags, (list, tuple, set))
        else []
    )
    payload: dict[str, Any] = {
        "recommendation": recommendation,
        "reasoning": _bounded_text(verdict.get("reasoning")),
        "flags": flags,
        "model": model,
        "annotated_at": annotated_at,
        # NFR-3, said on the row itself rather than only in a docstring: this
        # value travels to an admin surface, and the surface must not have to
        # remember what it is allowed to mean.
        "advisory": True,
    }
    for field in ANNOTATION_REFERENCE_FIELDS:
        text = _bounded_text(verdict.get(field))
        if text:
            payload[field] = text
    return payload


def annotation_result(
    kind: str,
    item_id: str,
    *,
    annotation: Optional[dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """The ONE response shape every annotate path returns, both twins.

    ``annotated`` is the whole contract: False plus a ``reason`` means nothing
    was written and says why, and there is deliberately no third state -- a
    caller cannot mistake "the annotator was not configured" for "the copilot
    had no concerns about this item".
    """
    return {
        "kind": kind,
        "id": item_id,
        "annotated": annotation is not None,
        "annotation": annotation,
        "reason": reason,
    }


def missing_item_error(item_id: str) -> ToolDriverError:
    """The governed "no such row" denial, shared by both twins."""
    return ToolDriverError("not_found", f'review_item "{item_id}" not found.')


def _require_choice(params: dict[str, Any], key: str, allowed: tuple[str, ...]) -> str:
    value = params.get(key)
    if value not in allowed:
        raise ToolDriverError(
            "unexpected_error",
            f'review_inbox rejects {key} "{value}"; allowed: {", ".join(allowed)}.',
        )
    return str(value)


def _require_text(params: dict[str, Any], key: str, limit: int) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolDriverError(
            "unexpected_error", f"review_inbox requires a non-empty {key}."
        )
    if len(value) > limit:
        raise ToolDriverError(
            "unexpected_error",
            f"review_inbox rejects a {key} longer than {limit} characters.",
        )
    return value.strip()


def resolve_review_item_emitter(context: "ToolExecutionContext") -> None:
    """Gate an EMISSION (ADR-0148 framework-derived, propose-only).

    Deliberately asserts a profile and NOT an actor. The emitters are S10's
    blast-radius pass, S20's graduation/retirement sweep and S25's aggregator --
    scheduled jobs with no human at the keyboard, so requiring an actor here
    would make the store unreachable by the three slices it exists for. An
    emission is inert by construction (``status='open'`` decides nothing), which
    is why propose-only writes need no attribution; the DECISION is where the
    actor becomes mandatory, and that gate is fail-closed below.
    """
    from ...plugin.profiles import INTERNAL

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            f'review_item emissions are not permitted for profile "{context.profile}".',
        )


def resolve_review_item_authorization(context: "ToolExecutionContext") -> str:
    """Framework-derived decider for every governed review-inbox admin action.

    ONE shared resolver for the mock and Postgres twins -- the
    ``resolve_lexicon_decision_authorization`` skeleton, same reasoning: this
    gate is security-sensitive, so the two paths must not be able to drift on who
    may decide. Callers run it BEFORE any row lookup, so a missing actor is
    ``policy_blocked`` regardless of ``id`` and an unattributed caller cannot use
    the error class to probe which ids exist.
    """
    from ...plugin.profiles import INTERNAL

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            f'review_inbox decisions are not permitted for profile "{context.profile}".',
        )
    if not context.user_id:
        raise ToolDriverError("policy_blocked", UNATTRIBUTED_DECISION_MESSAGE)
    return context.user_id


def read_review_item_emission(params: dict[str, Any]) -> dict[str, Any]:
    """Validate one ``propose_review_item`` call; return the storable fields.

    ``kind`` is checked against :data:`REVIEW_ITEM_KINDS`, NOT
    :data:`INBOX_ITEM_KINDS`: ``l6_proposal``/``l7_proposal`` are inbox kinds that
    already have governed propose actions and tables of their own, so a row here
    claiming to be one would be a second source of truth for the same pending
    decision -- two rows to decide, one of which nothing can act on. The error
    names the kind so the caller sees which action it wanted instead.

    ``status``/``decider_account_id``/``decided_at``/``annotations`` are absent by
    design: the first three are framework-derived (an emission is always ``open``
    and undecided) and ``annotations`` belongs to S13/S16, whose writers own their
    own reserved top-level key. A caller-supplied value for any of them is ignored.

    **``evidence`` is write-scanned, and it is not belt-and-braces.** A review
    item never reaches a customer turn, so at first glance the injection leg has
    nothing to protect -- but S16 feeds these very items to a model for triage
    annotation, which puts emitter-authored text in a prompt. Scanning at the
    write is the only place that covers it once, for all four emitters, before
    the consumer exists. The policy is L7's, for L7's reason: injection
    hard-rejects at every depth, PII REDACTS in place. Rejecting on PII here
    would be the D2-amendment-3 false positive in a new costume -- an emitter's
    natural keys and values are order ids, epoch stamps and dates, and
    ``_PHONE_RE`` reads ``order_1234567890`` as a phone number. Destroying a
    sweep's whole governance record over that is the harm redact-don't-reject
    exists to prevent.
    """
    kind = params.get("kind")
    if kind in PROPOSAL_ITEM_KINDS:
        raise ToolDriverError(
            "unexpected_error",
            f'review_item does not store "{kind}": L6/L7 proposals live in their '
            "own tables and are proposed through their own governed actions "
            "(propose_experience / propose_lexicon_entry).",
        )
    # Shape first, content second: a caller who got the kind wrong should be told
    # that, not handed a scan verdict on evidence that was never going to be
    # stored anyway.
    checked_kind = _require_choice(params, "kind", REVIEW_ITEM_KINDS)
    subject_ref = _require_text(
        params, "subject_ref", REVIEW_ITEM_SUBJECT_REF_MAX_LENGTH
    )
    # The emitter's own reason-to-believe: hit counts, affected case ids, a
    # window. Reuses L6/L7's object validator rather than a second one.
    evidence = read_proposer_context({"proposer_context": params.get("evidence")})
    scanned, _redacted, _spared = scan_proposer_context(
        evidence, pii_in_values=PII_IN_VALUES_REDACT
    )
    return {
        "kind": checked_kind,
        "subject_ref": subject_ref,
        "evidence": scanned or {},
    }


def read_review_item_filters(
    params: dict[str, Any],
) -> tuple[Optional[str], Optional[str]]:
    """``(status, kind)`` filters for ``list_review_items`` -- ONE resolver.

    Both optional. An unknown value is a validation error rather than a silently
    empty list: a queue that renders "nothing pending" for a typo is worse than
    one that errors (the S02 precedent).
    """
    status = params.get("status")
    if status is not None:
        status = _require_choice(params, "status", REVIEW_ITEM_STATUS_VALUES)
    kind = params.get("kind")
    if kind is not None:
        kind = _require_choice(params, "kind", REVIEW_ITEM_KINDS)
    return status, kind


def read_review_item_decision(
    params: dict[str, Any], context: "ToolExecutionContext"
) -> tuple[str, str, str, str]:
    """``(id, status, audit action, decider)`` for ``decide_review_item``."""
    item_id = _require_text(params, "id", REVIEW_ITEM_SUBJECT_REF_MAX_LENGTH)
    decision = _require_choice(params, "decision", tuple(REVIEW_ITEM_DECISIONS))
    decider = resolve_review_item_authorization(context)
    return item_id, decision, REVIEW_ITEM_DECISIONS[decision], decider


def read_reclassification(
    params: dict[str, Any], context: "ToolExecutionContext"
) -> tuple[str, str, str, str]:
    """``(source kind, target kind, source id, actor)`` for ``reclassify_proposal``.

    Validates EVERYTHING -- the route, the source id, the actor, and the whole
    target proposal including its write scan -- before either side is touched, so
    a malformed re-file cannot leave the source rejected with nothing to show for
    it. The Postgres twin runs both writes in one transaction; the mock cannot,
    which is precisely why the validation has to be front-loaded rather than
    trusted to a rollback.

    **Only ``l6_proposal -> l7_proposal`` is routed, and that is a decision.** The
    reverse direction is not merely unbuilt: L6 hard-REJECTS PII-shaped content by
    NFR-6, and ``_PHONE_RE`` matches ``205 55 16`` -- so re-filing an L7 tire-size
    entry as an L6 learning would be ``policy_blocked`` for exactly the digit-shaped
    domain tokens L7 exists to hold. Shipping a route that fails on its own
    flagship case would be worse than not shipping it; if the reverse is ever
    wanted, it needs a ruling on L6's scan first, not an extra dict entry here.
    """
    source_kind = params.get("source_kind")
    if source_kind not in RECLASSIFY_ROUTES:
        raise ToolDriverError(
            "unexpected_error",
            f'review_inbox cannot re-classify "{source_kind}"; routes: '
            f'{", ".join(f"{s} -> {t}" for s, t in RECLASSIFY_ROUTES.items())}.',
        )
    source_id = _require_text(params, "id", REVIEW_ITEM_SUBJECT_REF_MAX_LENGTH)
    actor = resolve_review_item_authorization(context)
    # Full target validation + the D2 write scan + the framework-derived
    # provenance, with no side effects. Runs here so an invalid target never
    # reaches the reject.
    read_lexicon_proposal(params, context)
    return source_kind, RECLASSIFY_ROUTES[source_kind], source_id, actor


def require_pending_source(
    row: Optional[dict[str, Any]], source_id: str
) -> dict[str, Any]:
    """The source proposal must still be undecided. Shared by both twins.

    An already-decided proposal is a ``conflict``, not a silent success: mining a
    row an admin rejected months ago for a fresh L7 entry would leave an audit
    trail that says the L6 decision happened then, and the propose happened now,
    with nothing connecting them to the same act.
    """
    if row is None:
        raise ToolDriverError(
            "not_found", f'agent_experience entry "{source_id}" not found.'
        )
    if row.get("status") != "proposed":
        raise ToolDriverError(
            "conflict",
            f'agent_experience entry "{source_id}" is already {row.get("status")}; '
            "only a pending proposal can be re-classified.",
        )
    return row


def reclassified_target_params(
    params: dict[str, Any], source_row: dict[str, Any]
) -> dict[str, Any]:
    """The L7 proposal a re-classified L6 row becomes. ONE builder, both twins.

    Evidence preserved is the whole point of re-classify over reject-and-retype:
    the L6 content becomes the L7 ``evidence``, prefixed so a human reading the
    lexicon queue can see where the proposal came from. The source's own
    ``proposer_context`` rides along unchanged.

    **The source ID is deliberately NOT written into any scanned field.** L7
    redacts PII spans inside ``evidence`` and ``proposer_context`` (D2), and
    ``_PHONE_RE`` matches any run of 8+ digits -- which a Postgres
    ``aexp_<32 hex>`` id hits roughly two times in five. A breadcrumb that is
    silently mangled into ``aexp_ab[redacted]cd`` two times in five is worse than
    no breadcrumb: it breaks the join AND reads like a PII incident. The
    machine-readable link therefore lives where nothing scans it -- the action's
    response, and (Postgres twin) the ``review_item_reclassified`` audit row.
    The prefix above is digit-free, and the L6 content already passed L6's PII
    *reject* leg, so the human-readable half survives redaction intact.
    """
    return {
        "domain": params.get("domain"),
        "entry_kind": params.get("entry_kind"),
        "surface_form": params.get("surface_form"),
        "canonical_form": params.get("canonical_form"),
        "evidence": RECLASSIFIED_EVIDENCE_PREFIX + str(source_row.get("content") or ""),
        "proposer_context": source_row.get("proposer_context") or None,
    }


def reclassification_result(
    source_kind: str,
    target_kind: str,
    source: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    """The ONE response shape both twins return for a re-classification."""
    return {
        "source": source,
        "target": target,
        "reclassified": {
            "from": {"kind": source_kind, "id": source["id"]},
            "to": {"kind": target_kind, "id": target["id"]},
        },
    }


def _make_clock() -> Any:
    """A strictly increasing ISO-8601 UTC clock -- the L7 mock's, same reason.

    Windows' clock granularity is coarse enough that two consecutive mock writes
    land on the same microsecond, which would make ``created_at DESC`` ambiguous
    where the Postgres twin's is not.
    """
    last = ""

    def now() -> str:
        nonlocal last
        text = datetime.now(timezone.utc).isoformat()
        if text <= last:
            text = (datetime.fromisoformat(last) + timedelta(microseconds=1)).isoformat()
        last = text
        return text

    return now


def create_review_inbox_mock_handlers(
    *,
    agent_experience: dict[str, Any],
    semantic_lexicon: dict[str, Any],
    store: Optional[list[dict[str, Any]]] = None,
) -> MockHandlerRegistry:
    """Build ``toee_review_inbox`` handlers over an in-memory ``review_item`` list.

    Takes the L6 and L7 handler fragments rather than re-implementing either:
    re-classify dispatches to the SAME governed ``reject_experience`` and
    ``propose_lexicon_entry`` the console calls, which is what "no new decision
    primitives" means in practice. The Postgres twin does the identical thing with
    its own module-level handlers.
    """
    store = [] if store is None else store
    ids = itertools.count(1)
    now = _make_clock()

    def _find(item_id: str) -> dict[str, Any]:
        for item in store:
            if item["id"] == item_id:
                return item
        raise missing_item_error(item_id)

    def _open_duplicate(kind: str, subject_ref: str) -> Optional[dict[str, Any]]:
        for item in store:
            if (
                item["kind"] == kind
                and item["subject_ref"] == subject_ref
                and item["status"] == REVIEW_ITEM_STATUS_OPEN
            ):
                return item
        return None

    def propose_review_item(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        resolve_review_item_emitter(context)
        fields = read_review_item_emission(params)
        # Idempotent on the OPEN set (the Postgres twin's partial unique index).
        # S20's sweep and S25's aggregator are SCHEDULED: without this they
        # re-raise every still-open subject on every cycle and the badge count
        # stops meaning anything within a day. Scoped to `open` rather than the
        # whole table on purpose -- once an admin has dealt with an item, the same
        # subject becoming a candidate again is new news, not a duplicate.
        existing = _open_duplicate(fields["kind"], fields["subject_ref"])
        if existing is not None:
            return {**existing, "proposed": False}
        stamp = now()
        item = {
            "id": f"rvw_{next(ids)}",
            **fields,
            # D8: S16 annotates graduation / blast-radius / persona-review items,
            # and those live ONLY here. Without this column S16's scope silently
            # shrinks to the two proposal tables, contradicting FR-23.
            "annotations": {},
            "status": REVIEW_ITEM_STATUS_OPEN,
            "decider_account_id": None,
            "decided_at": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        store.append(item)
        return {**item, "proposed": True}

    def list_review_items(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Admin-only read (_AGENT_EXCLUDED_ACTIONS, the list_agent_experience
        # precedent) -- reached only from the admin BFF's deterministic dispatch.
        status, kind = read_review_item_filters(params)
        items = [
            item
            for item in store
            if (status is None or item["status"] == status)
            and (kind is None or item["kind"] == kind)
        ]
        # Newest first, matching the Postgres twin's ORDER BY created_at DESC.
        # Sorting the REVERSED list keeps newest-inserted first among ties.
        items = sorted(reversed(items), key=lambda i: i["created_at"], reverse=True)
        return {"items": [dict(i) for i in items], "open_count": _open_count()}

    def _open_count() -> int:
        return sum(1 for i in store if i["status"] == REVIEW_ITEM_STATUS_OPEN)

    def decide_review_item(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        item_id, decision, _audit, decider = read_review_item_decision(params, context)
        item = _find(item_id)
        # Guarded on the FROM status: a redelivered decision, or one aimed at an
        # already-decided item, returns the current row unchanged rather than
        # re-attributing it to whoever replayed the request.
        if item["status"] == REVIEW_ITEM_STATUS_OPEN:
            item["status"] = decision
            item["decider_account_id"] = decider
            item["decided_at"] = now()
            item["updated_at"] = item["decided_at"]
        return dict(item)

    def get_blast_radius(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        """S10 (FR-12): which turns/cases an entry reached -- unanswerable here.

        The mock driver has no ``injection_ledger``: the ledger is a Postgres
        table written by the two live turn seams, and there is no in-memory turn
        history for it to mirror. So this validates the query through the SAME
        shared resolver the Postgres twin uses (NFR-7) and then says plainly that
        it has no ledger, rather than returning an empty case list that a console
        would render as "this entry touched nobody" -- the one answer an admin
        has no way to check.
        """
        layer, entry_ref, since = read_blast_radius_query(params)
        return blast_radius_result(
            [], layer=layer, entry_ref=entry_ref, since=since, ledger_available=False
        )

    def reclassify_proposal(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        source_kind, target_kind, source_id, _actor = read_reclassification(
            params, context
        )
        entries = agent_experience["list_agent_experience"]({}, context)["entries"]
        source_row = require_pending_source(
            next((e for e in entries if e["id"] == source_id), None), source_id
        )
        # Reject in the source queue, propose in the target one, through the
        # layers' OWN governed actions -- so both sides get their layer's normal
        # attribution, scan and (Postgres twin) audit row.
        rejected = agent_experience["reject_experience"]({"id": source_id}, context)
        target = semantic_lexicon["propose_lexicon_entry"](
            reclassified_target_params(params, source_row), context
        )
        return reclassification_result(source_kind, target_kind, rejected, target)

    def annotate_inbox_item(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        """S16 (FR-23): copilot triage annotation -- unanswerable here.

        Exactly ``get_blast_radius``'s posture, for the same class of reason.
        An annotation is a MODEL's advisory read of a queue item, and this
        driver is the DB-free substrate: it has no annotator, no model, and no
        network dependency to acquire one (``hermes/`` does not import
        ``hermes_runtime``). So it validates the request through the SAME shared
        resolvers the Postgres twin uses (NFR-7) and then says plainly that it
        has no annotator, rather than storing a fabricated verdict that an inbox
        would render as a real triage note -- the one answer an admin has no way
        to check.
        """
        resolve_review_item_annotator(context)
        kind, item_id, _table = read_annotation_request(params)
        return annotation_result(kind, item_id, reason=ANNOTATOR_UNAVAILABLE_MOCK)

    return {
        "toee_review_inbox": {
            "propose_review_item": propose_review_item,
            "list_review_items": list_review_items,
            "decide_review_item": decide_review_item,
            "reclassify_proposal": reclassify_proposal,
            "get_blast_radius": get_blast_radius,
            "annotate_inbox_item": annotate_inbox_item,
        }
    }
