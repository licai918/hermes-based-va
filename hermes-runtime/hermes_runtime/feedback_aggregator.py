"""The feedback aggregator: ONE scheduled propose-only job (0.0.5 S25, FR-32).

C6 §§6.2-6.3. Both quality-feedback tables are read on the background worker's
tick, clustered by reason tag, and a cluster that trips the threshold raises a
PROPOSAL for a human. Nothing here ever writes memory content: NFR-3 is absolute,
and the job's whole purpose is to turn a pile of rep/supervisor judgments into one
question somebody already has a queue for.

**Every emission goes through a governed propose action.** Never a direct INSERT
into ``agent_experience`` or ``review_item`` -- the write-side scans (injection
hard-reject, PII policy) live on those actions, and this job's input is aggregated
CUSTOMER-facing text. A direct insert would put unscanned customer-derived content
into a shared layer, which is the boundary NFR-6 exists to hold. The two handler
fragments are called exactly the way ``handlers/review_item._reclassify_proposal``
calls its two, so each write gets its layer's own attribution, scan and audit row.

**Provenance.** The job builds its own ``ToolExecutionContext`` carrying
:data:`~toee_hermes.tool_gate.FEEDBACK_AGGREGATOR_ROUTE`, and the L6/L7 resolvers
derive ``feedback_derived`` from it (D3). That is a literal set at this
construction site -- never a param, never a runtime kwarg -- so an aggregator
proposal is distinguishable from an agent-proposed one in every queue, and nothing
inside a turn can claim to be this job.

**Idempotence has two independent legs, and they do not fight (D13).**

1. *The watermark* stops WORK. It is the newest feedback row this job has already
   consumed; a run that finds nothing newer emits nothing and records nothing.
   That is what makes a retry after a mid-run failure safe, and what makes the
   hourly/daily tick free when no one has left feedback.
2. *The stores* stop DUPLICATES. ``review_item`` is idempotent on the OPEN set via
   its partial unique index (S15), and the L6 arm asks the same question of
   ``agent_experience`` before proposing (:func:`_open_feedback_proposal`) because
   that table has no such index.

The watermark deliberately does NOT bound the READ. If it did, a cluster that
accumulates across two runs would be split in half and never trip -- two fails
seen on Monday and the third on Tuesday would be one row short forever. The read
spans :data:`CLUSTER_WINDOW_SECONDS`; the watermark only decides whether there is
anything new to look at.

**What this slice does NOT do**, stated here rather than discovered later:

* the M-threshold's edit-diff MINING is S27 (FR-33). :data:`SIMILAR_EDIT_DIFF_THRESHOLD`
  is declared here because D16 wants both knobs named in the slice that first
  needs one, and because the two arms share the plumbing -- nothing in this module
  reads it yet.
* three of the routing table's rows terminate OUTSIDE the memory layers and this
  job cannot emit into them under NFR-3; each says so at its entry, and the run's
  audit row counts them so they are visible rather than dropped.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from toee_hermes.errors import ToolDriverError

logger = logging.getLogger(__name__)

# --- knobs (D16: named constants from day one, so S22's panel reads them) ------

# N -- the grill-locked starting value. "N same-tag fails on SIMILAR SUBJECTS",
# so it counts DISTINCT SUBJECTS, not rows: one bad interaction re-reviewed three
# times is one problem, and treating it as three would manufacture proposals from
# a single supervisor's thoroughness.
SAME_TAG_FAIL_THRESHOLD = 3

# M -- the edit-diff arm's threshold. S27 (FR-33) owns the mining that consumes
# it; it lives here so both knobs sit on one panel and neither gets re-invented.
SIMILAR_EDIT_DIFF_THRESHOLD = 3

# How far back a run looks. ponytail: 30 days, one constant, no per-tag windows.
# It has to be wide enough that a cluster can ACCUMULATE across runs (see the
# module docstring) and short enough that a fixed problem stops re-proposing
# itself once its evidence ages out. The cost of widening it is a longer scan of
# two small tables; the cost of narrowing it is missed clusters.
CLUSTER_WINDOW_SECONDS = 30 * 24 * 60 * 60

# The job's own "last run" record, on the surface the retention sweep, the ledger
# prune and the L7 hit rollup already use (a `workbench_audit_log` row) -- no
# state table for one number. It also carries the machine-readable evidence link;
# see `_record_run`.
AGGREGATOR_AUDIT_ACTION = "feedback_aggregator"

# FR-34's feedback->proposal conversion counters. `blocked` is D13's requirement:
# a propose that returns `policy_blocked` (a rep comment carrying a customer name
# or phone will do it) must never fail the job and must never vanish silently.
METRIC_FEEDBACK_PROPOSED = "feedback_aggregator_proposed"
METRIC_FEEDBACK_BLOCKED = "feedback_aggregator_blocked"

# What a fail looks like in each table. The two mechanisms keep separate verdict
# vocabularies on purpose (ADR-0154), so the aggregator names both.
INTERACTION_FAIL_VERDICT = "fail"
DRAFT_FAIL_VERDICT = "down"


# --- the Signal Routing Table (C6 §6.2) ---------------------------------------

# A route's destination. The first two have a governed propose action this job
# may call; the last two are terminal declarations, and the difference is the
# whole reason this is a table of objects rather than a dict of strings.
DEST_L6_PROCEDURE = "l6_procedure_proposal"
DEST_PERSONA_REVIEW = "persona_review_item"
DEST_KNOWLEDGE_OPS = "knowledge_ops"
DEST_NOT_ROUTED = "not_routed"

EMITTING_DESTINATIONS: tuple[str, ...] = (DEST_L6_PROCEDURE, DEST_PERSONA_REVIEW)


@dataclass(frozen=True)
class SignalRoute:
    """Where one reason tag's cluster terminates, and why."""

    destination: str
    note: str


class UnroutedFeedbackSignal(LookupError):
    """A reason tag with no entry in the routing table.

    Raised rather than returned-as-None so an unrecognised tag FAILS CLOSED: it
    cannot be emitted anywhere, and the job counts and logs it instead of
    dropping it. The structural test over
    ``EXTERNAL_REVIEW_REASON_TAGS | INTERNAL_REVIEW_REASON_TAGS`` is what makes
    this unreachable in practice -- adding a tag without deciding its route
    fails the suite.
    """


# C6 §6.2, transcribed. Every tag in BOTH reason-tag vocabularies
# (``toee_hermes.plugin.schemas``) appears exactly once; the test asserts set
# equality in both directions, so this table cannot silently fall behind them.
#
# The tag-cluster arm is what S25 lands. The table's other rows belong to other
# slices and are deliberately absent from this dict because they are not keyed on
# a reason tag at all: consistent `sent_edited` diffs are S27, judge
# low-honored/stale are S26, zero-hit is S20.
FEEDBACK_SIGNAL_ROUTES: dict[str, SignalRoute] = {
    # -- row 3: the action tags -> an L6 procedure proposal -------------------
    "tool_misuse": SignalRoute(
        DEST_L6_PROCEDURE,
        "propose_experience(kind=procedure), source=feedback_derived.",
    ),
    "wrong_action": SignalRoute(
        DEST_L6_PROCEDURE,
        "propose_experience(kind=procedure), source=feedback_derived.",
    ),
    "should_have_escalated": SignalRoute(
        DEST_L6_PROCEDURE,
        "propose_experience(kind=procedure), source=feedback_derived.",
    ),
    # -- row 5: the tone tags -> OUT of memory, a persona review item ---------
    "wrong_tone": SignalRoute(
        DEST_PERSONA_REVIEW,
        "OUT of memory: a persona-change inbox item. The persona itself changes "
        "by dev edit + eval re-record; this item is advisory, with acknowledge "
        "and dismiss as its only actuators.",
    ),
    "too_verbose": SignalRoute(
        DEST_PERSONA_REVIEW,
        "OUT of memory: a persona-change inbox item (see wrong_tone).",
    ),
    "tone_inappropriate": SignalRoute(
        DEST_PERSONA_REVIEW,
        "OUT of memory: a persona-change inbox item (see wrong_tone).",
    ),
    # -- row 6: policy -> the existing KnowledgeOps publish gate --------------
    "policy_violation": SignalRoute(
        DEST_KNOWLEDGE_OPS,
        "OUT of the memory layers: policy slots via the existing publish gate. "
        "NOT emitted by this job, and that is the propose-only law rather than a "
        "gap in it -- KnowledgeOps has no propose-shaped action (update_policy_slot "
        "writes slot CONTENT and requires a human actor), so a job writing there "
        "would be the auto-write NFR-3 forbids. KnowledgeOps is already a queue a "
        "human works; the run's audit row counts these so they stay visible.",
    ),
    # -- row 1 / row 2: the knowledge-shaped tags -----------------------------
    "factual_error": SignalRoute(
        DEST_KNOWLEDGE_OPS,
        "C6 6.2 row 1: an L5 knowledge-slot draft via KnowledgeOps submit_for_eval, "
        "OR an L7 alias fix. NOT emitted by this job: the L5 half is the same "
        "auto-write policy_violation is blocked by, and the L7 half needs a "
        "surface->canonical PAIR that a tag cluster does not contain -- deriving "
        "one is edit-diff mining (FR-33 / S27).",
    ),
    "missed_information": SignalRoute(
        DEST_KNOWLEDGE_OPS,
        "C6 6.2 row 2: an L5 gap or L4 injection-miss review item. NOT emitted by "
        "this job: D9 pins the review_item kind enum at six values and none of "
        "them is an L5-gap or L4-miss kind, so there is nothing legal to emit.",
    ),
    "missing_context": SignalRoute(
        DEST_KNOWLEDGE_OPS,
        "C6 6.2 row 2, internal vocabulary (see missed_information).",
    ),
    # -- the escape hatch ----------------------------------------------------
    "other": SignalRoute(
        DEST_NOT_ROUTED,
        "Declared unrouted. `other` is the free-text escape hatch: its meaning "
        "lives in the reviewer's comment, so clustering on the tag says nothing "
        "about what to propose. An explicit entry rather than an omission, so a "
        "future reader sees a decision instead of a hole.",
    ),
}


def route_for(tag: str) -> SignalRoute:
    """The routing-table entry for ``tag``, or fail closed."""
    try:
        return FEEDBACK_SIGNAL_ROUTES[tag]
    except KeyError as exc:
        raise UnroutedFeedbackSignal(
            f'no route for feedback reason tag "{tag}"; the Signal Routing Table '
            "must gain an entry before the tag can be aggregated"
        ) from exc


# --- clustering ---------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackSignal:
    """One (feedback row x reason tag) pair, from either table.

    ``subject_ref`` is what "similar subjects" is measured on: the reviewed audit
    subject for an ``interaction_review``, the draft's correlation id for a
    ``draft_feedback`` row. ``at`` is epoch seconds, which is also how the
    watermark is compared -- one scalar, no timezone to get wrong.
    """

    row_id: str
    subject_ref: str
    tag: str
    at: float


@dataclass(frozen=True)
class FeedbackCluster:
    """Every signal carrying one tag, plus the evidence behind it."""

    tag: str
    subjects: tuple[str, ...]
    row_ids: tuple[str, ...]
    first_seen: float
    last_seen: float

    @property
    def size(self) -> int:
        """DISTINCT SUBJECTS -- what the threshold counts. See the constant."""
        return len(self.subjects)


def cluster_feedback(signals: Iterable[FeedbackSignal]) -> list[FeedbackCluster]:
    """Group signals by tag. Deterministic order (by tag) for stable audit rows.

    A feedback row carrying two tags lands in two clusters, which is correct: the
    routing table is per-tag, and a draft that was both too verbose and a wrong
    action is genuinely two signals.
    """
    grouped: dict[str, list[FeedbackSignal]] = {}
    for signal in signals:
        grouped.setdefault(signal.tag, []).append(signal)
    clusters = []
    for tag in sorted(grouped):
        members = grouped[tag]
        clusters.append(
            FeedbackCluster(
                tag=tag,
                subjects=tuple(sorted({m.subject_ref for m in members})),
                row_ids=tuple(sorted({m.row_id for m in members})),
                first_seen=min(m.at for m in members),
                last_seen=max(m.at for m in members),
            )
        )
    return clusters


def tripped_clusters(
    clusters: Iterable[FeedbackCluster], *, threshold: int = SAME_TAG_FAIL_THRESHOLD
) -> list[FeedbackCluster]:
    """The clusters at or over the threshold, counted in DISTINCT SUBJECTS."""
    return [cluster for cluster in clusters if cluster.size >= threshold]


# --- what an emission carries -------------------------------------------------


def cluster_evidence(cluster: FeedbackCluster) -> dict[str, Any]:
    """The emitter's reason to believe, in a shape the write scans keep intact.

    **Why there are no feedback row ids in here, and where they went instead.**
    L6 hard-REJECTS PII-shaped values (D2, unchanged) and L7/``review_item``
    REDACT them, while ``_PHONE_RE`` matches any run of 8+ digits -- which a
    ``irev_<32 hex>`` id hits roughly two times in five. Putting the ids here
    would ``policy_blocked`` most L6 proposals outright and silently mangle the
    rest into ``irev_ab[redacted]cd``. That is precisely the trap S15 recorded for
    ``reclassified_target_params``, and the answer is the same one: the
    machine-readable link lives where nothing scans it -- the run's audit row (see
    :func:`_record_run`).

    What survives here is what a human actually triages on, and every value is
    either a short lowercase token or an int (ints are not scanned at all): how
    many rows, how many distinct subjects, and the epoch bounds of the window they
    span, which is enough to reproduce the cluster through ``list_feedback``.
    """
    return {
        "feedback_cluster": cluster.tag,
        "signal_rows": len(cluster.row_ids),
        "distinct_subjects": cluster.size,
        "window_days": CLUSTER_WINDOW_SECONDS // 86400,
        "first_seen_epoch": int(cluster.first_seen),
        "last_seen_epoch": int(cluster.last_seen),
        "emitted_by": AGGREGATOR_AUDIT_ACTION,
    }


def l6_proposal_content(cluster: FeedbackCluster) -> str:
    """The L6 procedure proposal's text: a question, never an answer.

    Deliberately digit-light -- an ISO date here would trip L6's PII reject leg
    (``2026-07-28`` matches ``_PHONE_RE``) and block the whole write.
    """
    return (
        f"Feedback signal: {cluster.size} distinct subjects were flagged "
        f'"{cluster.tag}" across {len(cluster.row_ids)} feedback rows in the last '
        f"{CLUSTER_WINDOW_SECONDS // 86400} days. Review the procedure this "
        "recurring failure points at, then confirm or reject. Proposed by the "
        "feedback aggregator; nothing has been written to memory."
    )


def persona_subject_ref(tag: str) -> str:
    """The ``review_item.subject_ref`` a tone cluster raises.

    One open item per tag, which is what makes the store's partial unique index do
    the de-duplication: a daily tick on a still-open persona question is a no-op,
    and once an admin has decided it the same tag becoming a problem again is new
    news rather than a duplicate.
    """
    return f"feedback_tag:{tag}"


# --- the run ------------------------------------------------------------------


@dataclass(frozen=True)
class AggregatorRun:
    """One run's outcome. Returned for tests and logged; not persisted as-is."""

    signals: int = 0
    clusters: int = 0
    tripped: int = 0
    emitted: int = 0
    already_open: int = 0
    blocked: int = 0
    unrouted: int = 0
    terminal_elsewhere: int = 0
    watermark: float = 0.0
    emissions: tuple[dict[str, Any], ...] = field(default_factory=tuple)


_SIGNAL_SQL = """
SELECT id, subject_kind || ':' || subject_id AS subject_ref, reason_tags,
       extract(epoch FROM created_at) AS at
  FROM interaction_review
 WHERE verdict = %s
   AND created_at >= now() - make_interval(secs => %s)
UNION ALL
SELECT id, 'draft:' || draft_correlation_id, reason_tags,
       extract(epoch FROM created_at)
  FROM draft_feedback
 WHERE verdict = %s
   AND created_at >= now() - make_interval(secs => %s)
"""


def read_feedback_signals(
    conn, *, window_seconds: int = CLUSTER_WINDOW_SECONDS
) -> list[FeedbackSignal]:
    """Every failing feedback row in the window, exploded to one row per tag.

    Both tables in one query. A row with no tags contributes nothing -- a bare
    ``fail`` cannot reach ``interaction_review`` (the 0018 CHECK), but a
    ``sent_edited`` outcome row legitimately has none and must not become a
    signal here (that stream is S27's).
    """
    with conn.cursor() as cur:
        cur.execute(
            _SIGNAL_SQL,
            (
                INTERACTION_FAIL_VERDICT,
                window_seconds,
                DRAFT_FAIL_VERDICT,
                window_seconds,
            ),
        )
        rows = cur.fetchall()
    return [
        FeedbackSignal(row_id=row_id, subject_ref=subject_ref, tag=tag, at=float(at))
        for row_id, subject_ref, tags, at in rows
        for tag in (tags or ())
    ]


def read_watermark(conn) -> float:
    """The newest feedback row a previous run consumed, or ``0.0``.

    Kept in the run's audit row rather than a table of its own. A pruned or
    missing audit row costs nothing worse than one replayed window, because the
    stores are the leg that stops duplicates.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT (details->>'watermark')::float8
              FROM workbench_audit_log
             WHERE action = %s AND details->>'watermark' IS NOT NULL
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (AGGREGATOR_AUDIT_ACTION,),
        )
        row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def _aggregator_context():
    """The job's own execution context (ADR-0148, D3).

    ``profile`` is internal_copilot because that is the only home the governed
    stores are allowlisted on; ``dispatch_route`` is the literal that makes the
    resolvers derive ``feedback_derived``. NO ``user_id``: there is no human at
    the keyboard, an emission asserts nothing, and attribution becomes mandatory
    at the DECISION -- which is fail-closed in each store's own resolver.
    """
    from toee_hermes.plugin.profiles import INTERNAL
    from toee_hermes.tool_gate import FEEDBACK_AGGREGATOR_ROUTE, ToolExecutionContext

    return ToolExecutionContext(
        profile=INTERNAL, dispatch_route=FEEDBACK_AGGREGATOR_ROUTE
    )


def _open_feedback_proposal(conn, tag: str) -> bool:
    """Is a feedback-derived L6 proposal for this cluster still undecided?

    ``review_item`` gets this for free from its partial unique index;
    ``agent_experience`` has none, so the L6 arm asks the same question here
    rather than manufacturing one proposal per tick for a queue nobody has got to
    yet. Scoped to ``proposed`` for the same reason the index is partial: once an
    admin has decided it, the tag recurring is new news.
    """
    from toee_hermes.drivers.mock.agent_experience import (
        AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM agent_experience
             WHERE status = 'proposed'
               AND source = %s
               AND proposer_context->>'feedback_cluster' = %s
             LIMIT 1
            """,
            (AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED, tag),
        )
        return cur.fetchone() is not None


def _emit(conn, context, cluster: FeedbackCluster, destination: str):
    """Dispatch ONE cluster through its layer's governed propose action.

    Returns ``(target_type, target_id)`` on a real emission, or ``None`` when the
    store already holds an undecided item for this cluster.
    """
    from .datastore.handlers.agent_experience import agent_experience_handlers
    from .datastore.handlers.review_item import review_item_handlers

    if destination == DEST_L6_PROCEDURE:
        if _open_feedback_proposal(conn, cluster.tag):
            return None
        result = agent_experience_handlers()["toee_agent_experience"][
            "propose_experience"
        ](
            conn,
            {
                "kind": "procedure",
                "content": l6_proposal_content(cluster),
                "proposer_context": cluster_evidence(cluster),
            },
            context,
        )
        return "agent_experience", result["id"]

    if destination != DEST_PERSONA_REVIEW:
        # Fail closed rather than falling through. Without this, adding a third
        # value to EMITTING_DESTINATIONS and forgetting a branch here would
        # quietly file it as a persona_review -- a signal in the wrong queue is
        # worse than a job that stops and says so.
        raise ToolDriverError(
            "unexpected_error",
            f'feedback_aggregator has no emitter for destination "{destination}".',
        )
    result = review_item_handlers()["toee_review_inbox"]["propose_review_item"](
        conn,
        {
            "kind": "persona_review",
            "subject_ref": persona_subject_ref(cluster.tag),
            "evidence": cluster_evidence(cluster),
        },
        context,
    )
    # The store's ON CONFLICT DO NOTHING already answered "still open?" for us.
    return ("review_item", result["id"]) if result["proposed"] else None


def aggregate_feedback(
    conn, *, window_seconds: int = CLUSTER_WINDOW_SECONDS
) -> AggregatorRun:
    """Read -> cluster -> route -> propose, on a CALLER-OWNED connection.

    No commit: the caller owns the transaction, the retention-sweep/prune/rollup
    discipline. A run either lands whole or is retried, and a retry is safe
    because both idempotence legs are.
    """
    watermark = read_watermark(conn)
    signals = read_feedback_signals(conn, window_seconds=window_seconds)
    newest = max((s.at for s in signals), default=0.0)
    if not signals or newest <= watermark:
        # Nothing has happened since the last run. Emitting nothing here is the
        # watermark leg of D13's idempotence -- and it is why running this job
        # twice in a row cannot produce a second copy of anything.
        logger.info(
            "feedback_aggregator: no feedback newer than the watermark "
            "(%s signal(s) in the %ss window); nothing proposed.",
            len(signals),
            window_seconds,
        )
        return AggregatorRun(signals=len(signals), watermark=watermark)

    clusters = cluster_feedback(signals)
    tripped = tripped_clusters(clusters)
    counts: Counter[str] = Counter()
    emissions: list[dict[str, Any]] = []

    for cluster in tripped:
        try:
            route = route_for(cluster.tag)
        except UnroutedFeedbackSignal as exc:
            # Fail CLOSED: no emission, and loud. Unreachable while the structural
            # test holds, which is the point of having it.
            counts["unrouted"] += 1
            logger.warning("feedback_aggregator: %s", exc)
            continue

        if route.destination not in EMITTING_DESTINATIONS:
            counts["terminal_elsewhere"] += 1
            logger.info(
                "feedback_aggregator: cluster %s (%s subjects) terminates at %s; "
                "no memory-layer emission. %s",
                cluster.tag,
                cluster.size,
                route.destination,
                route.note,
            )
            continue

        try:
            emitted = _emit(conn, _aggregator_context(), cluster, route.destination)
        except ToolDriverError as exc:
            if exc.error_class != "policy_blocked":
                # A conflict/not_found here is a real fault, not a governed
                # refusal of content: let it fail the job so it retries and
                # ultimately dead-letters where somebody sees it.
                raise
            # D13: routine, never fatal, never silent. A rep's comment carrying a
            # customer name is exactly what the write scans are for; the job
            # counts the refusal and carries on with the next cluster.
            counts["blocked"] += 1
            _count_metric(conn, METRIC_FEEDBACK_BLOCKED)
            logger.info(
                "feedback_aggregator: cluster %s was refused by the %s write scan "
                "(policy_blocked); counted, not retried.",
                cluster.tag,
                route.destination,
            )
            continue

        if emitted is None:
            counts["already_open"] += 1
            continue
        target_type, target_id = emitted
        counts["emitted"] += 1
        _count_metric(conn, METRIC_FEEDBACK_PROPOSED)
        emissions.append(
            {
                "tag": cluster.tag,
                "destination": route.destination,
                "target_type": target_type,
                "target_id": target_id,
                # The machine-readable evidence link, in the one place nothing
                # scans it. See cluster_evidence for why it cannot ride the row.
                "feedback_row_ids": list(cluster.row_ids),
                "subject_refs": list(cluster.subjects),
            }
        )

    run = AggregatorRun(
        signals=len(signals),
        clusters=len(clusters),
        tripped=len(tripped),
        emitted=counts["emitted"],
        already_open=counts["already_open"],
        blocked=counts["blocked"],
        unrouted=counts["unrouted"],
        terminal_elsewhere=counts["terminal_elsewhere"],
        watermark=newest,
        emissions=tuple(emissions),
    )
    _record_run(conn, run, window_seconds=window_seconds)
    return run


def _count_metric(conn, metric: str) -> None:
    from .datastore.handlers._common import insert_metric_event

    insert_metric_event(conn, metric=metric)


def _record_run(conn, run: AggregatorRun, *, window_seconds: int) -> None:
    """The run's audit row: the watermark, the counts, and the evidence link."""
    from .datastore.handlers._common import insert_audit
    from toee_hermes.plugin.profiles import INTERNAL

    insert_audit(
        conn,
        # Unattended, exactly like the retention sweep and the ledger prune.
        profile=INTERNAL,
        account_id=None,
        action=AGGREGATOR_AUDIT_ACTION,
        target_type="feedback",
        target_id=None,
        details={
            "watermark": run.watermark,
            "window_seconds": window_seconds,
            "signals": run.signals,
            "clusters": run.clusters,
            "tripped": run.tripped,
            "emitted": run.emitted,
            "already_open": run.already_open,
            "blocked": run.blocked,
            "unrouted": run.unrouted,
            "terminal_elsewhere": run.terminal_elsewhere,
            "emissions": run.emissions,
        },
    )


def run_feedback_aggregator_job(
    payload: Mapping[str, Any], *, conn: Optional[Any] = None
) -> None:
    """The ``feedback_aggregator`` job body (FR-32).

    ``conn`` is injectable for tests (an isolated-schema connection); production
    takes a pooled connection, matching ``honored_rate`` / the ledger prune / the
    L7 hit rollup. A failure propagates so the job retries then dead-letters --
    both idempotence legs make the retry safe, and a silently-skipped run is a
    feedback loop that quietly stops closing.
    """
    del payload  # scheduled job; the (schedule_window, window_start) payload is unused.
    if conn is not None:
        _aggregate_and_commit(conn)
        return
    from .datastore.config import database_url
    from .datastore.pool import get_database_pool

    with get_database_pool(database_url()).connection() as pooled:
        _aggregate_and_commit(pooled)


def _aggregate_and_commit(conn) -> AggregatorRun:
    run = aggregate_feedback(conn)
    conn.commit()
    logger.info(
        "feedback_aggregator: %s signal(s) -> %s cluster(s), %s tripped; "
        "proposed=%s already_open=%s blocked=%s elsewhere=%s unrouted=%s",
        run.signals,
        run.clusters,
        run.tripped,
        run.emitted,
        run.already_open,
        run.blocked,
        run.terminal_elsewhere,
        run.unrouted,
    )
    return run


__all__ = [
    "AGGREGATOR_AUDIT_ACTION",
    "CLUSTER_WINDOW_SECONDS",
    "DEST_KNOWLEDGE_OPS",
    "DEST_L6_PROCEDURE",
    "DEST_NOT_ROUTED",
    "DEST_PERSONA_REVIEW",
    "EMITTING_DESTINATIONS",
    "FEEDBACK_SIGNAL_ROUTES",
    "METRIC_FEEDBACK_BLOCKED",
    "METRIC_FEEDBACK_PROPOSED",
    "SAME_TAG_FAIL_THRESHOLD",
    "SIMILAR_EDIT_DIFF_THRESHOLD",
    "AggregatorRun",
    "FeedbackCluster",
    "FeedbackSignal",
    "SignalRoute",
    "UnroutedFeedbackSignal",
    "aggregate_feedback",
    "cluster_evidence",
    "cluster_feedback",
    "l6_proposal_content",
    "persona_subject_ref",
    "read_feedback_signals",
    "read_watermark",
    "route_for",
    "run_feedback_aggregator_job",
    "tripped_clusters",
]
