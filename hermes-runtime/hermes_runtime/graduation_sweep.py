"""Graduation sweep + zero-hit retirement feed (0.0.5 S20, FR-19/FR-20).

ONE scheduled, propose-only job with two arms, both of which end at the SAME
place -- a ``review_item`` a human decides:

* **FR-19, graduation.** A confirmed L6 note that is lexicon-SHAPED
  ("2055516 means 205/55R16") will never be applied by the deterministic seam and
  never reaches the prompt glossary; it is an L7 entry wearing an L6 costume.
  The sweep re-applies :func:`~toee_hermes.lexicon.structurable_shape` -- the
  same heuristic S13 uses at propose time -- to the CONFIRMED rows and raises
  "graduate to L7?".
* **FR-20, retirement.** A confirmed L7 entry that nothing has used since it was
  confirmed is dead vocabulary. It surfaces as a ``retirement_candidate``.

**Nothing here retires, graduates, edits or deletes anything (NFR-3).** Every
emission goes through the governed ``propose_review_item`` action -- never a
direct INSERT -- because the write-side scans live on that action and an
emitter's evidence is derived from customer-facing text.

## The landmine this job was dispatched to avoid (D22)

``hit_count`` counts **deterministic-seam applications**, and the seam
(``lexicon_seam.normalize_product_query``) only ever applies ``alias`` and
``normalizer`` rows. A ``default_rule`` is never "applied" -- it renders into the
prompt as an imperative ASK. **So every ``default_rule`` earns exactly zero hits,
permanently, no matter how well it works.** FR-20 read literally -- "zero
``hit_count`` means retire" -- puts every ``default_rule`` in the system into the
queue on day one, including the two seeded seasonal rows that are this
iteration's flagship behaviour, and an admin who approves one hands control of
the seasonal default back to the calendar.

So usage here is **both** already-materialized numbers summed, never
``hit_count`` alone (D6, and the gap audit's ruling):

``usage = semantic_lexicon.hit_count + entry_effectiveness.injections``

The second is S26's ledger-derived count, read through the public, layer-generic
:func:`~hermes_runtime.entry_effectiveness.entry_effectiveness_for`. A glossary
entry that is rendered but never seam-applied earns its usage there.

## What is excluded, and why silence would be the bug

``season=`` condition rows -- the whole family, override first. The brief's ⚠
names ``season=override``: it is CONSULTED by the render (it decides which
seasonal default applies) and is **never itself rendered**, so it can never earn
a ledger row and crediting it with one would be inventing an injection record
(D4.3). To a zero-hit sweep it therefore looks completely unused, and the failure
inverts intent -- *the sweep proposes retiring the row an admin created
specifically to override the calendar, and retiring it hands control back to the
calendar.*

The two seeded ``season=winter`` / ``season=all_season`` defaults are the same
failure in slow motion, and the arithmetic is why they are excluded too: out of
season a default_rule earns no injections (D22), the Ontario off-season is 182
days (``WINTER_MONTHS``), and the ledger keeps 180
(``PRUNE_WINDOW_SECONDS``). 182 > 180, so once a year the absence of injections
stops meaning "dead" and starts meaning "out of season" -- and the two are
indistinguishable from here. The exclusion is by CONDITION SHAPE, not by
``entry_kind``: an ordinary ``default_rule`` has no calendar gate, earns
injections whenever it is rendered, and is swept like anything else. Excluding
the kind would also make the D22 test above vacuous.

The count of excluded rows rides the run's audit row and the retention status
read, so they are visibly spared rather than silently missing.

## Idempotence, and why there is no work-skipping watermark (D13)

"Job failure leaves queues clean" means **idempotent on retry**, not
transactional rollback -- each propose is its own transaction and no compensating
path exists. Two legs deliver it:

1. *The store.* ``review_item`` is idempotent on the OPEN set via its partial
   unique index (S15), so a re-run of a still-open subject is a no-op.
2. *This job's own already-raised check.* The store's index is partial on
   purpose: for a recurring signal, a subject becoming a candidate again after a
   decision is new news. Both of this job's subjects are STATIC -- an L6 note
   stays structurable forever, an unused entry stays unused -- so a dismissed
   item would come back on every tick. The sweep therefore suppresses any
   subject it has already raised in ANY status. Same shape as S25's
   ``_open_feedback_proposal``: the store's leg is a floor, not a ceiling.

A watermark that skipped WORK would be a correctness bug here, and that is worth
stating rather than leaving as an omission. S25's input is a stream, so "nothing
newer than last time" is a safe skip. This job's candidate set changes with the
CLOCK -- an entry crosses the zero-hit window with no row changing anywhere -- so
any watermark keyed on data recency would freeze the feed permanently at
whatever the newest row happened to be. The run still records itself (the
retention surface's "last run"), it just never uses that record to skip.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from toee_hermes.errors import ToolDriverError
from toee_hermes.lexicon import (
    SEASON_CONDITION_PREFIX,
    LexiconShape,
    structurable_shape,
)

from .entry_effectiveness import entry_effectiveness_for, refresh_entry_effectiveness
from .injection_ledger import LAYER_L7, PRUNE_WINDOW_SECONDS, ZERO_HIT_WINDOW_SECONDS

logger = logging.getLogger(__name__)

# D9 (BINDING): the two item kinds this job emits, spelled the way S15's enum
# spells them. `retirement_candidate`, never `retirement-candidate`.
KIND_GRADUATION = "graduation"
KIND_RETIREMENT = "retirement_candidate"

# The run's own record, on the surface the retention sweep, the ledger prune and
# the L7 hit rollup already use (a `workbench_audit_log` row) -- no state table
# for four numbers. `get_retention_status` reads it back.
GRADUATION_SWEEP_AUDIT_ACTION = "graduation_sweep"

# FR-34's conversion counters. `blocked` is D13's requirement: a propose that
# returns `policy_blocked` must never fail the job and must never vanish.
METRIC_SWEEP_PROPOSED = "graduation_sweep_proposed"
METRIC_SWEEP_BLOCKED = "graduation_sweep_blocked"

# The brief asks for the seasonal exclusion to be SAID rather than silently
# applied. It travels as data on the run record so a surface cannot render the
# spared count without its reason.
SEASONAL_EXCLUSION_REASON = (
    "season= condition rows are never proposed for retirement: season=override is "
    "consulted by the render and never itself rendered, and a seasonal default "
    "earns no injections out of season for longer than the ledger is kept -- so "
    "an absence of usage cannot distinguish dead from out-of-season."
)

# The L6 status the graduation arm sweeps. A `proposed` note is already in the
# inbox as an `l6_proposal`; raising a graduation for it would be two rows to
# decide about one undecided note.
L6_CONFIRMED_STATUS = "confirmed"
L7_CONFIRMED_STATUS = "confirmed"

_GRADUATION_CANDIDATE_SQL = """
SELECT id, content
  FROM agent_experience
 WHERE status = %s
 ORDER BY created_at, id
"""

# The age gate is `coalesce(decided_at, created_at)`: an entry becomes eligible
# to be injected when it is CONFIRMED, so that is the moment from which "nothing
# has used it" starts to mean something. `created_at` is the fallback for rows
# whose decision predates the column being populated.
_RETIREMENT_CANDIDATE_SQL = """
SELECT id, domain, entry_kind, surface_form, hit_count
  FROM semantic_lexicon
 WHERE status = %s
   AND coalesce(decided_at, created_at) < now() - make_interval(secs => %s)
 ORDER BY id
"""

_ALREADY_RAISED_SQL = "SELECT subject_ref FROM review_item WHERE kind = %s"


@dataclass(frozen=True)
class SweepRun:
    """One run's outcome. Returned for tests and logged; not persisted as-is."""

    graduation_candidates: int = 0
    retirement_candidates: int = 0
    emitted: int = 0
    already_raised: int = 0
    blocked: int = 0
    excluded_seasonal: int = 0
    emissions: tuple[dict[str, Any], ...] = field(default_factory=tuple)


# --- what an emission carries -------------------------------------------------
#
# Both evidence builders keep to short tokens and ints, the `cluster_evidence`
# discipline. The ONE exception is the surface/canonical text, which is what
# makes an inbox row readable -- and it is exposed to `review_item`'s write scan,
# which REDACTS PII in values rather than rejecting them (D2). A digit-spaced
# surface form like "205 55 16" matches `_PHONE_RE`, so it can reach the row as
# "[redacted]". That is a degraded DISPLAY, not a broken join: `subject_ref` is
# the entry id, it is not scanned, and the exact halves also ride the run's audit
# row where nothing scans them.


def graduation_evidence(shape: LexiconShape) -> dict[str, Any]:
    """The emitter's reason to believe an L6 note belongs in L7.

    No L6 row id in here on purpose: the join lives in the unscanned
    ``subject_ref``, and an ``aexp_<32 hex>`` id trips ``_PHONE_RE`` roughly two
    times in five (the S15 ``reclassified_target_params`` finding).
    """
    return {
        "graduation_from": "l6",
        "surface_form": shape.surface_form,
        "canonical_form": shape.canonical_form,
        "emitted_by": GRADUATION_SWEEP_AUDIT_ACTION,
    }


def retirement_evidence(row: Mapping[str, Any], injections: int) -> dict[str, Any]:
    """The emitter's reason to believe an L7 entry is dead.

    Both usage numbers ship, separately and named, because the whole D22 point is
    that neither one alone is usage: a ``default_rule`` has ``hit_count = 0``
    while it is working perfectly, and a seam-applied ``normalizer`` can have no
    ledger row at all. The two windows differ and are named for what they are --
    the age gate is the zero-hit window, the injections count spans however much
    ledger survives the prune (D12 keeps the second >= the first).
    """
    return {
        "retirement_of": "l7",
        "surface_form": row["surface_form"],
        "entry_kind": row["entry_kind"],
        "domain": row["domain"],
        "hit_count": int(row["hit_count"] or 0),
        "ledger_injections": int(injections),
        "unused_for_days": ZERO_HIT_WINDOW_SECONDS // 86400,
        "ledger_window_days": PRUNE_WINDOW_SECONDS // 86400,
        "emitted_by": GRADUATION_SWEEP_AUDIT_ACTION,
    }


# --- the candidate sets -------------------------------------------------------


def _sweep_context():
    """The job's own execution context (ADR-0148).

    ``profile`` is internal_copilot because that is the only home the governed
    stores are allowlisted on. NO ``user_id``: there is no human at the keyboard,
    an emission asserts nothing (``status='open'`` decides nothing), and
    attribution becomes mandatory at the DECISION -- fail-closed in
    ``resolve_review_item_authorization``.
    """
    from toee_hermes.plugin.profiles import INTERNAL
    from toee_hermes.tool_gate import ToolExecutionContext

    return ToolExecutionContext(profile=INTERNAL)


def _already_raised(conn, kind: str) -> set[str]:
    """Every subject this job has raised for ``kind``, in ANY status."""
    with conn.cursor() as cur:
        cur.execute(_ALREADY_RAISED_SQL, (kind,))
        return {row[0] for row in cur.fetchall()}


def graduation_candidates(conn) -> list[tuple[str, LexiconShape]]:
    """``(l6 entry id, LexiconShape)`` for every structurable CONFIRMED note."""
    with conn.cursor() as cur:
        cur.execute(_GRADUATION_CANDIDATE_SQL, (L6_CONFIRMED_STATUS,))
        rows = cur.fetchall()
    found = []
    for entry_id, content in rows:
        shape = structurable_shape(content)
        if shape is not None:
            found.append((entry_id, shape))
    return found


def retirement_candidates(
    conn, *, window_seconds: int = ZERO_HIT_WINDOW_SECONDS
) -> tuple[list[dict[str, Any]], int]:
    """``(candidates, seasonal rows excluded)`` -- the zero-usage confirmed L7 set.

    Recomputes ``entry_effectiveness`` first rather than trusting the last ledger
    prune to have run. The aggregate is a full recompute by construction, so this
    costs one extra pass over a small table and removes a silent failure mode:
    without it, a deployment whose prune has never run reads an EMPTY aggregate,
    sees zero injections everywhere, and proposes retiring the entire lexicon.
    """
    refresh_entry_effectiveness(conn)
    with conn.cursor() as cur:
        cur.execute(_RETIREMENT_CANDIDATE_SQL, (L7_CONFIRMED_STATUS, window_seconds))
        rows = [
            {
                "id": entry_id,
                "domain": domain,
                "entry_kind": entry_kind,
                "surface_form": surface_form,
                "hit_count": hit_count,
            }
            for entry_id, domain, entry_kind, surface_form, hit_count in cur.fetchall()
        ]
    aged, seasonal = [], 0
    for row in rows:
        if str(row["surface_form"]).startswith(SEASON_CONDITION_PREFIX):
            seasonal += 1
        else:
            aged.append(row)
    if not aged:
        return [], seasonal
    # A DEFAULT (tuple) row-factory cursor: `entry_effectiveness_for` unpacks
    # positionally, so a borrowed `dict_row` cursor fails on the first row (S26).
    with conn.cursor() as cur:
        effectiveness = entry_effectiveness_for(
            cur, layer=LAYER_L7, entry_refs=[r["id"] for r in aged]
        )
    unused = []
    for row in aged:
        injections = int((effectiveness.get(row["id"]) or {}).get("injections") or 0)
        # BOTH numbers, D22's whole point. Either one non-zero is usage.
        if int(row["hit_count"] or 0) + injections == 0:
            row["injections"] = injections
            unused.append(row)
    return unused, seasonal


# --- the run ------------------------------------------------------------------


def _propose(conn, context, *, kind: str, subject_ref: str, evidence: dict[str, Any]):
    """ONE emission through the governed propose action. Never a direct INSERT."""
    from .datastore.handlers.review_item import review_item_handlers

    return review_item_handlers()["toee_review_inbox"]["propose_review_item"](
        conn,
        {"kind": kind, "subject_ref": subject_ref, "evidence": evidence},
        context,
    )


def sweep_memory_lifecycle(
    conn, *, window_seconds: int = ZERO_HIT_WINDOW_SECONDS
) -> SweepRun:
    """Scan -> propose, on a CALLER-OWNED connection.

    No commit: the caller owns the transaction, the retention-sweep / prune /
    aggregator discipline.
    """
    context = _sweep_context()
    counts: Counter[str] = Counter()
    emissions: list[dict[str, Any]] = []

    graduations = graduation_candidates(conn)
    retirements, excluded_seasonal = retirement_candidates(
        conn, window_seconds=window_seconds
    )

    raised_graduations = _already_raised(conn, KIND_GRADUATION)
    for entry_id, shape in graduations:
        if entry_id in raised_graduations:
            counts["already_raised"] += 1
            continue
        _emit(
            conn,
            context,
            counts,
            emissions,
            kind=KIND_GRADUATION,
            subject_ref=entry_id,
            evidence=graduation_evidence(shape),
            extra={
                "surface_form": shape.surface_form,
                "canonical_form": shape.canonical_form,
            },
        )

    raised_retirements = _already_raised(conn, KIND_RETIREMENT)
    for row in retirements:
        if row["id"] in raised_retirements:
            counts["already_raised"] += 1
            continue
        _emit(
            conn,
            context,
            counts,
            emissions,
            kind=KIND_RETIREMENT,
            subject_ref=row["id"],
            evidence=retirement_evidence(row, row["injections"]),
            extra={"surface_form": row["surface_form"]},
        )

    run = SweepRun(
        graduation_candidates=len(graduations),
        retirement_candidates=len(retirements),
        emitted=counts["emitted"],
        already_raised=counts["already_raised"],
        blocked=counts["blocked"],
        excluded_seasonal=excluded_seasonal,
        emissions=tuple(emissions),
    )
    _record_run(conn, run, window_seconds=window_seconds)
    return run


def _emit(
    conn,
    context,
    counts: Counter,
    emissions: list[dict[str, Any]],
    *,
    kind: str,
    subject_ref: str,
    evidence: dict[str, Any],
    extra: dict[str, Any],
) -> None:
    """Propose one item; count a governed refusal instead of failing the run."""
    try:
        result = _propose(
            conn, context, kind=kind, subject_ref=subject_ref, evidence=evidence
        )
    except ToolDriverError as exc:
        if exc.error_class != "policy_blocked":
            # A conflict/not_found here is a real fault, not a governed refusal
            # of content: let it fail the job so it retries and ultimately
            # dead-letters where somebody sees it.
            raise
        # D13: routine, never fatal, never silent. A pre-scan L6 note whose
        # derived surface form is an injection pattern is exactly what the write
        # scan is for; the job counts the refusal and carries on.
        counts["blocked"] += 1
        _count_metric(conn, METRIC_SWEEP_BLOCKED)
        logger.info(
            "graduation_sweep: %s for %s was refused by the review_item write "
            "scan (policy_blocked); counted, not retried.",
            kind,
            subject_ref,
        )
        return
    if not result["proposed"]:
        # The store's ON CONFLICT already answered "still open?" for us.
        counts["already_raised"] += 1
        return
    counts["emitted"] += 1
    _count_metric(conn, METRIC_SWEEP_PROPOSED)
    emissions.append(
        {
            "kind": kind,
            "subject_ref": subject_ref,
            "item_id": result["id"],
            # The un-scanned copy of whatever the row's evidence may have had
            # redacted -- the S15/S25 precedent for a breadcrumb that must
            # survive intact.
            **extra,
        }
    )


def _count_metric(conn, metric: str) -> None:
    from .datastore.handlers._common import insert_metric_event

    insert_metric_event(conn, metric=metric)


def _record_run(conn, run: SweepRun, *, window_seconds: int) -> None:
    """The run's audit row: the counts, the exclusions and the evidence link."""
    from toee_hermes.plugin.profiles import INTERNAL

    from .datastore.handlers._common import insert_audit

    insert_audit(
        conn,
        # Unattended, exactly like the retention sweep and the ledger prune.
        profile=INTERNAL,
        account_id=None,
        action=GRADUATION_SWEEP_AUDIT_ACTION,
        target_type="review_item",
        target_id=None,
        details={
            "window_seconds": window_seconds,
            "graduation_candidates": run.graduation_candidates,
            "retirement_candidates": run.retirement_candidates,
            "emitted": run.emitted,
            "already_raised": run.already_raised,
            "blocked": run.blocked,
            "excluded_seasonal": run.excluded_seasonal,
            "excluded_reason": SEASONAL_EXCLUSION_REASON,
            "emissions": run.emissions,
            "run_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def run_graduation_sweep_job(
    payload: Mapping[str, Any], *, conn: Optional[Any] = None
) -> None:
    """The ``graduation_sweep`` job body (FR-19/FR-20).

    ``conn`` is injectable for tests (an isolated-schema connection); production
    takes a pooled connection, matching the ledger prune and the aggregator. A
    failure propagates so the job retries then dead-letters -- the retry is safe
    by construction (see the module docstring's two idempotence legs), and a
    sweep that fails silently is a queue that quietly stops filling.
    """
    del payload  # scheduled job; the (schedule_window, window_start) payload is unused.
    if conn is not None:
        _sweep_and_commit(conn)
        return
    from .datastore.config import database_url
    from .datastore.pool import get_database_pool

    with get_database_pool(database_url()).connection() as pooled:
        _sweep_and_commit(pooled)


def _sweep_and_commit(conn) -> SweepRun:
    run = sweep_memory_lifecycle(conn)
    conn.commit()
    logger.info(
        "graduation_sweep: %s graduation + %s retirement candidate(s); "
        "proposed=%s already_raised=%s blocked=%s seasonal_excluded=%s",
        run.graduation_candidates,
        run.retirement_candidates,
        run.emitted,
        run.already_raised,
        run.blocked,
        run.excluded_seasonal,
    )
    return run


__all__ = [
    "GRADUATION_SWEEP_AUDIT_ACTION",
    "KIND_GRADUATION",
    "KIND_RETIREMENT",
    "METRIC_SWEEP_BLOCKED",
    "METRIC_SWEEP_PROPOSED",
    "SEASONAL_EXCLUSION_REASON",
    "ZERO_HIT_WINDOW_SECONDS",
    "SweepRun",
    "graduation_candidates",
    "graduation_evidence",
    "retirement_candidates",
    "retirement_evidence",
    "run_graduation_sweep_job",
    "sweep_memory_lifecycle",
]
