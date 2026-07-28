"""Blast radius: which turns and cases a memory entry actually reached (S10, FR-12).

When an entry is corrected, retired or cleared, the question a supervisor has is
"who did I already answer with it?". S09's ``injection_ledger`` holds the answer
-- one row per (turn, layer, entry) -- and this is the vocabulary both twins read
it through, plus the ONE shape the answer comes back in (NFR-7).

**Why the SQL is not here.** The ledger is a Postgres table with no mock twin, so
the query itself lives in ``hermes_runtime.blast_radius`` beside
``injection_ledger`` and ``entry_effectiveness`` -- the same split S26 made for
the effectiveness formula, and for the same reason: the *rule* is shared so the
twins cannot disagree about what an answer looks like, while the *storage* stays
where the storage is. The mock's ``get_blast_radius`` returns this module's shape
with ``ledger_available=False``, which is why that flag exists at all: "no ledger
here" and "the ledger says nothing touched it" are different answers and a
console must not render them the same way.

**The evidence deliberately carries counts, not the case id list.** Two reasons,
both load-bearing:

* ``review_item.evidence`` is PII-redacted on the way in (S15's
  ``read_review_item_emission``, D2's redact-don't-reject policy), and
  ``_PHONE_RE`` matches any run of 8+ digits -- which a ``case_<32 hex>`` id hits
  roughly two times in five. That is the same mangled-breadcrumb trap
  ``reclassified_target_params`` documented: an id silently rewritten to
  ``case_ab[redacted]cd`` breaks the link AND reads like a PII incident.
* A frozen list goes stale. Cases get resolved after an item is raised, so the
  list an admin needs is the one :func:`hermes_runtime.blast_radius.affected_cases`
  returns *now* -- reachable from the item's own ``subject_ref``, which is the
  query's two coordinates joined.

So the item says "N open cases, M turns, since T"; ``get_blast_radius`` says
which ones.

**Nothing here decides anything (NFR-3).** An item is raised ``open`` and its
only actuators are acknowledge/dismiss. No case is reopened, mutated, or even
read for anything but its status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from .errors import ToolDriverError

# D9's enum, pinned in drivers/mock/review_item.py. Named here so the emitters
# and the query agree without importing the store's whole vocabulary.
BLAST_RADIUS_KIND = "blast_radius"

# Mirrors hermes_runtime.injection_ledger.LAYERS, which cannot be imported here:
# hermes_runtime depends on toee_hermes, never the reverse. The two are pinned
# equal by a test in the runtime suite, so this copy cannot drift silently.
LEDGER_LAYERS: tuple[str, ...] = ("l4", "l6", "l7")

# A case that is still somebody's problem. Matches the `status IN (...)` the
# gateway store and the case handlers already use for "is there an open case";
# 'resolved' is the third and only other value writable today (resolve_case).
# FR-12: closed cases are sampled by business judgment, never auto-reopened, so
# they are REPORTED and never counted into the review item.
OPEN_CASE_STATUSES: tuple[str, ...] = ("open", "in_progress")

# Why an item was raised. Carried in the evidence so a reviewer sees which
# governance act (or which sweep) put it in front of them.
REASON_ENTRY_RETIRED = "entry_retired"
REASON_ENTRY_EDITED = "entry_edited"
REASON_SLOT_CLEARED = "slot_cleared"
# D21: the one-time re-scan of L4 values written before S08 wired the injection
# scan into the write path. NOT a governance decision -- a suspicion.
REASON_UNSCANNED_INJECTION = "unscanned_injection_pattern"

REASONS: tuple[str, ...] = (
    REASON_ENTRY_RETIRED,
    REASON_ENTRY_EDITED,
    REASON_SLOT_CLEARED,
    REASON_UNSCANNED_INJECTION,
)


def blast_radius_subject_ref(layer: str, entry_ref: str) -> str:
    """``review_item.subject_ref`` for an entry whose blast radius was measured.

    The ledger's two coordinates joined, so the item can be taken straight back
    to ``get_blast_radius`` -- ``entry_ref`` alone is ambiguous by construction
    (the same string could in principle be an L6 id and an L7 id) and the layer
    is half of the ledger's own index.
    """
    return f"{layer}:{entry_ref}"


def unscanned_subject_ref(entry_ref: str) -> str:
    """``subject_ref`` for a D21 re-scan hit -- a DIFFERENT namespace, on purpose.

    Emission is idempotent on ``(kind, subject_ref)`` over the open set. Sharing
    the namespace with :func:`blast_radius_subject_ref` would mean a slot that is
    both cleared and re-scan-flagged collapses into ONE item, and whichever
    arrived second would be silently swallowed -- taking its reason with it. The
    two say different things ("this was changed, review who saw it" versus "this
    was never scanned, review whether it should be there"), so they are two items.
    """
    return f"l4_unscanned:{entry_ref}"


def parse_since(value: Any) -> Optional[datetime]:
    """The optional ``since`` window bound, as an aware UTC datetime.

    A malformed timestamp is a validation error, never a silent "no filter": a
    blast radius that quietly widened to all-time because a console sent a bad
    string would over-report the very number an admin is about to act on.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolDriverError(
            "unexpected_error", "blast radius `since` must be an ISO-8601 timestamp."
        )
    # ponytail: no Z-suffix rewrite. `fromisoformat` has parsed "Z" since 3.11
    # and both packages floor at 3.11, so a hand-rolled `text[:-1] + "+00:00"`
    # is dead code -- proven dead by disabling it and watching the Z test stay
    # green. Restore it only if the floor ever drops to 3.10.
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ToolDriverError(
            "unexpected_error",
            f'blast radius cannot read `since` "{value}" as an ISO-8601 timestamp.',
        ) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_blast_radius_query(params: dict[str, Any]) -> tuple[str, str, Optional[datetime]]:
    """Validate one ``get_blast_radius`` call -> ``(layer, entry_ref, since)``.

    ONE validator, both twins. ``layer`` is required and checked against
    :data:`LEDGER_LAYERS` rather than defaulted, because a defaulted layer would
    answer a question nobody asked: the same ``entry_ref`` under the wrong layer
    joins to nothing and reads as "this entry touched no cases", which is the one
    wrong answer this action must never give.
    """
    layer = params.get("layer")
    if layer not in LEDGER_LAYERS:
        raise ToolDriverError(
            "unexpected_error",
            f'blast radius rejects layer "{layer}"; allowed: '
            f'{", ".join(LEDGER_LAYERS)}.',
        )
    entry_ref = params.get("entry_ref")
    if not isinstance(entry_ref, str) or not entry_ref.strip():
        raise ToolDriverError(
            "unexpected_error", "blast radius requires a non-empty entry_ref."
        )
    return str(layer), entry_ref.strip(), parse_since(params.get("since"))


def blast_radius_result(
    cases: Sequence[dict[str, Any]],
    *,
    layer: str,
    entry_ref: str,
    since: Optional[datetime] = None,
    ledger_available: bool = True,
) -> dict[str, Any]:
    """The ONE response shape ``get_blast_radius`` returns, from either twin.

    ``cases`` are already deduplicated to one row per case by the query (D4's
    copilot-path note: a draft turn's ``turn_ref`` is synthetic and never
    repeats, so a re-drafted case would otherwise appear once per draft).
    ``open_cases`` is the subset a review item counts; the closed ones stay in
    ``cases`` because FR-12 wants them sampled by judgment, not hidden.
    """
    ordered = list(cases)
    open_cases = [c for c in ordered if c.get("status") in OPEN_CASE_STATUSES]
    return {
        "layer": layer,
        "entry_ref": entry_ref,
        "since": since.isoformat() if since else None,
        # False only from the mock twin, which has no injection_ledger at all.
        # Without it "the mock has no ledger" renders identically to "nothing
        # touched this entry" -- the answer an admin is least able to check.
        "ledger_available": ledger_available,
        "cases": ordered,
        "open_cases": open_cases,
        "open_case_count": len(open_cases),
        "case_count": len(ordered),
        "turn_count": sum(int(c.get("turn_count") or 0) for c in ordered),
    }


def blast_radius_evidence(result: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """The emitter's reason-to-believe, for ``review_item.evidence``.

    Counts and coordinates only -- see the module docstring for why the case ids
    are not in here and where they are instead. ``entry_ref`` is likewise absent:
    for L4 it is ``binding_key + slot_name``, i.e. the customer's own phone or
    Shopify id, and the write scan would redact it into a broken join anyway. It
    lives in ``subject_ref``, which nothing scans.
    """
    if reason not in REASONS:
        raise ToolDriverError(
            "unexpected_error",
            f'blast radius has no reason "{reason}"; known: {", ".join(REASONS)}.',
        )
    return {
        "reason": reason,
        "layer": result["layer"],
        "open_case_count": result["open_case_count"],
        "case_count": result["case_count"],
        "turn_count": result["turn_count"],
        "since": result["since"],
    }
