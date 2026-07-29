"""Edit-diff mining: what reps keep rewriting, asked as a question (S27, FR-33).

C6 §6.4. The `sent_edited` stream is the highest-volume signal the system has --
nobody has to click anything to produce it -- and it is the only one that carries
a **pair**: the draft as generated and the text a rep actually sent. S25's
aggregator clusters reason TAGS and can therefore never derive a
``surface_form -> canonical_form`` mapping (its ``factual_error`` row says so at
its own routing entry, and D23 records it). This job derives one.

It is the second arm of the same propose-only machine, and it shares that arm's
plumbing deliberately: the M threshold (:data:`SIMILAR_EDIT_DIFF_THRESHOLD`) and
the clustering window are S25's constants, and provenance rides the SAME
``dispatch_route`` axis (:data:`FEEDBACK_AGGREGATOR_ROUTE`), so "a job proposed
this" means one thing in every layer. Only the input, the clustering key and the
destinations differ, which is why it is a module rather than a branch.

**Nothing here ever writes memory content.** NFR-3 is absolute: however
consistent three reps look, the output is a proposal a human confirms or throws
away. Every emission goes through a GOVERNED propose action --
``propose_lexicon_entry`` for the L7 arm, ``propose_experience`` for the L6 arm
-- never a direct INSERT, because the write-side scans live on those actions and
this job's raw material is **customer-facing draft text**.

**What can and cannot cross into a shared layer.** This is the riskiest thing in
the slice and it is worth being exact, because a draft is by definition a reply
to a named customer about their order.

*Crosses:* the replacement span itself -- and only after it has recurred across
:data:`SIMILAR_EDIT_DIFF_THRESHOLD` DISTINCT drafts and passed :func:`carries_pii`
-- plus integer counts and epoch bounds.

*Does not cross:* any surrounding draft or sent text, the case id, the draft
correlation id, the rep's account id, the reviewer's comment. The SQL does not
even select them. The machine-readable draft refs live on the run's audit row,
where nothing scans them and only an admin reads them -- the same place S25 put
its feedback row ids, and for the same reason (``_PHONE_RE`` matches any run of
8+ digits, which a correlation id hits roughly two times in five).

Two independent things hold that boundary, and NEITHER is sufficient alone:

1. :func:`carries_pii` runs the SHARED ``redact_pii`` resolver over the pair and
   DROPS it on a hit. This is the leg nothing downstream provides: D2 turns the
   PII scan OFF for L7's forms, because it cannot tell the tire size
   ``205 55 16`` from a phone number. That exemption was written for a human at
   the keyboard; an unattended job is not one, so it re-arms the scan for itself.
   The cost is stated rather than hidden: **this job can never propose a
   digit-shaped domain token.** A bare tire size trips ``_PHONE_RE``, so
   size normalizers remain an admin's job.
2. **Recurrence across three distinct drafts.** A street address is not a shape
   ``scan_pii`` knows; what keeps a customer's address out is that it appears in
   one customer's draft and cannot recur across three. Operational text (the
   shop's own address, a policy phrase) can recur -- and that is the content
   these layers are for.

**Idempotence has the same two legs as S25's and they do not fight (D13).** The
WATERMARK stops work; the STORES stop duplicates -- ``UNIQUE (domain,
surface_form)`` for L7 (a re-proposed pair comes back a governed ``conflict``,
which is counted, not raised) and an open-proposal check for L6, which has no
such index. The watermark deliberately does not bound the READ: a pair seen
twice on Monday and once on Tuesday must still trip.

**No LLM.** The brief allows a fork-pattern advisory annotator whose output is a
proposal draft. It is not built: it would write to the ``annotations`` column D8
assigns to migration 0025, which is another in-flight slice's and has not landed.
Deterministic mining is the whole of this slice, and it is the half FR-33 calls
the hard part.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Optional

from toee_hermes.errors import ToolDriverError

from .feedback_aggregator import CLUSTER_WINDOW_SECONDS, SIMILAR_EDIT_DIFF_THRESHOLD

logger = logging.getLogger(__name__)

# --- the rules that decide a diff is MEANINGFUL -------------------------------
#
# A diff of two strings is not a signal. Each constant below kills exactly one
# shape of edit that means nothing, and each is exercised from both sides in
# `tests/test_edit_diff_mining.py`.

# Adjacent edits separated by an equal run this short are ONE edit region, the
# way a diff tool merges hunks that share context. Without it a clause rewrite
# splits at every word it happens to keep, and each fragment clusters on its own
# -- so a single recurring procedural edit would raise its L6 proposal AND a junk
# alias ("refund" -> "put") beside it. A junk proposal next to every real one is
# how an advisory gets switched off.
MAX_EQUAL_GAP_TOKENS = 2

# Longer than this on either side and it is prose, not a mapping. A rewrite a
# human could restate as a rule is short; a paragraph replaced wholesale is a
# different reply, and proposing it as memory content would be a category error.
MINEABLE_MAX_SPAN_TOKENS = 12

# The L7-vs-L6 shape split, applied to the recurring replacement. A TERM
# substitution (both sides this short) is what an alias IS -- surface form to
# canonical form. A CLAUSE substitution is how we say or do something, which is
# an L6 procedure question for a human.
#
# The brief points at "the S13 lexicon-shape heuristic" for this decision. S13
# had not landed when this shipped, so the split is length-shaped and lives in
# ONE function: replace :func:`proposal_shape`'s body with the heuristic when it
# exists, and nothing else in this module moves.
ALIAS_MAX_TOKENS = 3

SHAPE_L7_ALIAS = "l7_alias"
SHAPE_L6_PROCEDURE = "l6_procedure"

# The job's own "last run" record, on the same surface S25's watermark uses -- a
# `workbench_audit_log` row, not a state table for one number.
MINING_AUDIT_ACTION = "edit_diff_mining"

# FR-34's conversion counters, mirroring the aggregator's pair.
METRIC_EDIT_DIFF_PROPOSED = "edit_diff_mining_proposed"
METRIC_EDIT_DIFF_BLOCKED = "edit_diff_mining_blocked"

# The one outcome this job mines. `sent_as_is` rows carry no second operand and
# `rated_only` rows are S25's stream.
EDITED_OUTCOME = "sent_edited"


# --- the deterministic diff ---------------------------------------------------


def _edit_regions(
    before: list[str], after: list[str]
) -> list[tuple[int, int, int, int]]:
    """Coalesce ``difflib``'s opcodes into edit REGIONS.

    Returns ``(i1, i2, j1, j2)`` spans covering everything that changed, with
    runs of up to :data:`MAX_EQUAL_GAP_TOKENS` unchanged tokens absorbed into the
    region either side of them. A pure delete keeps an empty ``after`` side and a
    pure insert an empty ``before`` side -- :func:`mineable_rewrites` is what
    drops those, so this function stays a diff and nothing else.
    """
    regions: list[tuple[int, int, int, int]] = []
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if regions:
            pi1, pi2, pj1, pj2 = regions[-1]
            if i1 - pi2 <= MAX_EQUAL_GAP_TOKENS and j1 - pj2 <= MAX_EQUAL_GAP_TOKENS:
                regions[-1] = (pi1, i2, pj1, j2)
                continue
        regions.append((i1, i2, j1, j2))
    return regions


def mineable_rewrites(draft_text: str, sent_text: str) -> list[tuple[str, str]]:
    """The ``(surface, canonical)`` spans in one edit that could be a rule.

    Whitespace is normalized by tokenizing on it; case is normalized only for the
    comparisons, so the forms that reach a human keep the spelling a rep used.

    Four rules, each killing one named non-signal:

    * **both sides non-empty** -- a trim for length is a delete and an
      embellishment is an insert; neither carries a pair, so neither is mineable;
    * **neither side longer than** :data:`MINEABLE_MAX_SPAN_TOKENS` -- prose;
    * **the two sides are not the same words** (case-insensitive multiset) -- a
      sentence reorder is exactly that, and so is a pure case change;
    * ...and the fourth is not here: **recurrence**, which :func:`cluster_rewrites`
      applies across drafts. It is the rule that does most of the work.

    ponytail: no character-distance "is this just a typo" filter. It was tried
    and rejected -- at any ceiling that catches ``recieve -> receive`` (0.857) it
    also catches ``2055516 -> 205/55R16`` (0.875), which is a real normalizer and
    the flagship one in this domain. So an idiosyncratic typo is filtered by
    never recurring, and a typo the model makes CONSISTENTLY does raise a
    proposal -- which is a normalizer somebody should probably confirm. The
    upgrade path, if this ever proves noisy, is a dictionary check rather than a
    distance: a typo is a non-word, a notation is not.
    """
    before = draft_text.split()
    after = sent_text.split()
    out: list[tuple[str, str]] = []
    for i1, i2, j1, j2 in _edit_regions(before, after):
        left, right = before[i1:i2], after[j1:j2]
        if not left or not right:
            continue
        if len(left) > MINEABLE_MAX_SPAN_TOKENS or len(right) > MINEABLE_MAX_SPAN_TOKENS:
            continue
        if sorted(t.casefold() for t in left) == sorted(t.casefold() for t in right):
            continue
        out.append((" ".join(left), " ".join(right)))
    return out


def carries_pii(*forms: str) -> bool:
    """Does any form trip the SHARED PII resolver? See the module docstring.

    ``redact_pii`` rather than ``scan_pii`` only because a boolean is wanted
    where the other raises -- it is the same function over the same pattern list
    (``scan_pii`` is a raise around this exact call), so there is no second copy
    of the patterns to drift (NFR-7).
    """
    from toee_hermes.content_scan import redact_pii

    return any(redact_pii(form)[1] for form in forms)


# --- clustering ---------------------------------------------------------------


@dataclass(frozen=True)
class Rewrite:
    """One replacement span, seen in one edited send."""

    surface_form: str
    canonical_form: str
    draft_ref: str
    at: float

    @property
    def key(self) -> tuple[str, str]:
        """What "the same rewrite" means: case- and whitespace-insensitive."""
        return (self.surface_form.casefold(), self.canonical_form.casefold())


def rewrites_for(
    *, draft_ref: str, draft_text: str, sent_text: str, at: float
) -> tuple[list[Rewrite], int]:
    """Mine one edited send: ``(rewrites kept, pairs dropped for PII)``.

    The drop happens HERE rather than at emit time so a PII-bearing span is never
    clustered, never logged and never counted into anything but the drop counter
    -- and so both arms inherit it, not just L7's.

    The count is RETURNED rather than inferred by the caller. Inferring it
    (mine once, filter once, subtract the lengths) was the first shape, and it
    quietly attributes every future filter to PII -- a number in a governance
    audit row has to mean what its name says, and only the branch that drops the
    pair can honestly report it.
    """
    kept: list[Rewrite] = []
    dropped = 0
    for surface, canonical in mineable_rewrites(draft_text, sent_text):
        if carries_pii(surface, canonical):
            dropped += 1
            continue
        kept.append(
            Rewrite(
                surface_form=surface,
                canonical_form=canonical,
                draft_ref=draft_ref,
                at=at,
            )
        )
    return kept, dropped


@dataclass(frozen=True)
class RewriteCluster:
    """One recurring replacement, plus the drafts that produced it."""

    surface_form: str
    canonical_form: str
    draft_refs: tuple[str, ...]
    first_seen: float
    last_seen: float

    @property
    def size(self) -> int:
        """DISTINCT DRAFTS -- what M counts. One rep re-editing one draft three
        times is one opinion, and a row count would emit on it."""
        return len(self.draft_refs)

    @property
    def shape(self) -> str:
        return proposal_shape(self)

    @property
    def cluster_key(self) -> str:
        """The stable idempotence handle, also the human-readable summary."""
        return f"{self.surface_form} => {self.canonical_form}"


def proposal_shape(cluster: "RewriteCluster") -> str:
    """L7 alias or L6 procedure. See :data:`ALIAS_MAX_TOKENS` for the seam."""
    widest = max(
        len(cluster.surface_form.split()), len(cluster.canonical_form.split())
    )
    return SHAPE_L7_ALIAS if widest <= ALIAS_MAX_TOKENS else SHAPE_L6_PROCEDURE


def cluster_rewrites(rewrites: Iterable[Rewrite]) -> list[RewriteCluster]:
    """Group by the case-folded pair. Deterministic order, for stable audit rows.

    The cluster's FORMS come from its earliest member rather than from the folded
    key, so what an admin decides on is the spelling a rep actually typed.
    """
    grouped: dict[tuple[str, str], list[Rewrite]] = {}
    for rewrite in rewrites:
        grouped.setdefault(rewrite.key, []).append(rewrite)
    clusters = []
    for key in sorted(grouped):
        members = grouped[key]
        first = min(members, key=lambda m: (m.at, m.draft_ref))
        clusters.append(
            RewriteCluster(
                surface_form=first.surface_form,
                canonical_form=first.canonical_form,
                draft_refs=tuple(sorted({m.draft_ref for m in members})),
                first_seen=min(m.at for m in members),
                last_seen=max(m.at for m in members),
            )
        )
    return clusters


def tripped_rewrites(
    clusters: Iterable[RewriteCluster], *, threshold: int = SIMILAR_EDIT_DIFF_THRESHOLD
) -> list[RewriteCluster]:
    """The clusters at or over M, counted in DISTINCT DRAFTS."""
    return [cluster for cluster in clusters if cluster.size >= threshold]


# --- what an emission carries -------------------------------------------------


def rewrite_evidence(cluster: RewriteCluster) -> dict[str, Any]:
    """The emitter's reason to believe. No identifiers -- see the module docstring.

    Every value is a short token or an int. The pair itself is here because it IS
    the proposal; it has already passed :func:`carries_pii`, so this dict cannot
    carry PII the ``surface_form`` column does not carry anyway.
    """
    return {
        "edit_diff_cluster": cluster.cluster_key,
        "surface_form": cluster.surface_form,
        "canonical_form": cluster.canonical_form,
        "edited_sends": cluster.size,
        "window_days": CLUSTER_WINDOW_SECONDS // 86400,
        "first_seen_epoch": int(cluster.first_seen),
        "last_seen_epoch": int(cluster.last_seen),
        "emitted_by": MINING_AUDIT_ACTION,
    }


def l7_evidence_text(cluster: RewriteCluster) -> str:
    """The L7 row's ``evidence``: what an admin needs to decide, in one sentence."""
    return (
        f'Reps rewrote "{cluster.surface_form}" to "{cluster.canonical_form}" in '
        f"{cluster.size} separate edited sends over the last "
        f"{CLUSTER_WINDOW_SECONDS // 86400} days. Mined from the sent_edited "
        "stream; nothing has been written to memory."
    )


def l6_proposal_content(cluster: RewriteCluster) -> str:
    """The L6 procedure proposal's text: a question, never an answer.

    Deliberately digit-light for the same reason S25's is -- L6 hard-REJECTS
    PII-shaped values, and ``_PHONE_RE`` reads an ISO date as a phone number.
    """
    return (
        f'Feedback signal: reps rewrote "{cluster.surface_form}" to '
        f'"{cluster.canonical_form}" in {cluster.size} separate edited sends '
        f"over the last {CLUSTER_WINDOW_SECONDS // 86400} days. Review the "
        "procedure this recurring correction points at, then confirm or reject. "
        "Mined by edit-diff mining; nothing has been written to memory."
    )


# --- the run ------------------------------------------------------------------


@dataclass(frozen=True)
class MiningRun:
    """One run's outcome. Returned for tests and logged; not persisted as-is."""

    edited_sends: int = 0
    rewrites: int = 0
    pii_dropped: int = 0
    clusters: int = 0
    tripped: int = 0
    emitted: int = 0
    already_open: int = 0
    blocked: int = 0
    watermark: float = 0.0
    emissions: tuple[dict[str, Any], ...] = field(default_factory=tuple)


# The SELECT list is the boundary, stated as SQL. `comment`, `case_id` and
# `rep_account_id` are never read at all -- a fixture can only show that they did
# not leak this time; the statement shows they cannot.
_EDITED_SEND_SQL = """
SELECT draft_correlation_id, draft_text, sent_text,
       extract(epoch FROM created_at) AS at
  FROM draft_feedback
 WHERE outcome = %s
   AND sent_text IS NOT NULL
   AND draft_text IS NOT NULL
   AND created_at >= now() - make_interval(secs => %s)
 ORDER BY created_at
"""


def read_edited_sends(
    conn, *, window_seconds: int = CLUSTER_WINDOW_SECONDS
) -> tuple[list[Rewrite], int, int]:
    """Every mineable rewrite in the window: ``(rewrites, rows read, PII drops)``.

    Rows written before migration 0029 have a NULL ``sent_text`` and are skipped
    by the statement -- D11 takes no backfill, so mining sees only sends made
    after that column landed. That is the honest statement of this job's reach.
    """
    with conn.cursor() as cur:
        cur.execute(_EDITED_SEND_SQL, (EDITED_OUTCOME, window_seconds))
        rows = cur.fetchall()
    rewrites: list[Rewrite] = []
    dropped = 0
    for draft_ref, draft_text, sent_text, at in rows:
        kept, pii_hits = rewrites_for(
            draft_ref=draft_ref,
            draft_text=draft_text,
            sent_text=sent_text,
            at=float(at),
        )
        rewrites.extend(kept)
        dropped += pii_hits
    return rewrites, len(rows), dropped


def read_watermark(conn) -> float:
    """The newest edited send a previous run consumed, or ``0.0``.

    Same surface and same reasoning as the aggregator's: a pruned or missing
    audit row costs one replayed window, because the stores are the leg that
    stops duplicates.
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
            (MINING_AUDIT_ACTION,),
        )
        row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def _mining_context():
    """The job's own execution context (ADR-0148, D3).

    Identical to the aggregator's, deliberately: ``FEEDBACK_AGGREGATOR_ROUTE`` is
    the one axis every layer reads for "a job proposed this", and D3's amendment
    says not to invent a fourth discriminator. A literal at this construction
    site -- never a param, never a runtime kwarg. No ``user_id``: there is no
    human here, and attribution becomes mandatory at the DECISION.
    """
    from toee_hermes.plugin.profiles import INTERNAL
    from toee_hermes.tool_gate import FEEDBACK_AGGREGATOR_ROUTE, ToolExecutionContext

    return ToolExecutionContext(
        profile=INTERNAL, dispatch_route=FEEDBACK_AGGREGATOR_ROUTE
    )


def _open_mined_proposal(conn, cluster_key: str) -> bool:
    """Is a feedback-derived L6 proposal for this cluster still undecided?

    ``semantic_lexicon`` gets this for free from ``UNIQUE (domain,
    surface_form)``; ``agent_experience`` has no such index, so the L6 arm asks
    here rather than manufacturing one proposal per tick for a queue nobody has
    got to yet. Scoped to ``proposed`` for the same reason S25's is: once an
    admin has decided it, the pattern recurring is new news.
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
               AND proposer_context->>'edit_diff_cluster' = %s
             LIMIT 1
            """,
            (AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED, cluster_key),
        )
        return cur.fetchone() is not None


def _emit(conn, context, cluster: RewriteCluster):
    """Dispatch ONE cluster through its layer's governed propose action.

    Returns ``(target_type, target_id)`` on a real emission, or ``None`` when the
    store already holds this proposal.
    """
    from toee_hermes.lexicon import DOMAIN_TIRE, ENTRY_KIND_ALIAS

    from .datastore.handlers.agent_experience import agent_experience_handlers
    from .datastore.handlers.semantic_lexicon import semantic_lexicon_handlers

    if cluster.shape == SHAPE_L6_PROCEDURE:
        if _open_mined_proposal(conn, cluster.cluster_key):
            return None
        result = agent_experience_handlers()["toee_agent_experience"][
            "propose_experience"
        ](
            conn,
            {
                "kind": "procedure",
                "content": l6_proposal_content(cluster),
                "proposer_context": rewrite_evidence(cluster),
            },
            context,
        )
        return "agent_experience", result["id"]

    if cluster.shape != SHAPE_L7_ALIAS:
        # Fail closed rather than falling through, the way S25's emitter does: a
        # third shape with no branch would otherwise be filed as an alias, and a
        # signal in the wrong layer is worse than a job that stops and says so.
        raise ToolDriverError(
            "unexpected_error",
            f'edit_diff_mining has no emitter for shape "{cluster.shape}".',
        )
    # A `conflict` here is UNIQUE(domain, surface_form) -- the L7 store's own
    # idempotence leg -- and it is NOT caught in this function. It is caught by
    # `mine_edit_diffs`, OUTSIDE the savepoint that call site opens, because a
    # unique violation aborts the whole Postgres transaction: catching it in here
    # would leave the savepoint releasing an already-aborted transaction, and
    # every later statement (the next cluster, the metric, the run's audit row)
    # would fail with InFailedSqlTransaction. Handling and unwinding have to
    # happen in that order, which means at that level.
    result = semantic_lexicon_handlers()["toee_semantic_lexicon"][
        "propose_lexicon_entry"
    ](
        conn,
        {
            # ponytail: one shipped domain. Aliases are matched across every
            # domain by the seam (`lexicon_seam.resolve_product_query`), so this
            # is a label -- but it must be the SAME label an admin uses, or
            # UNIQUE(domain, surface_form) stops de-duplicating against curated
            # entries and two rows could claim one surface form. The day a second
            # domain ships, this job needs a domain signal it does not have.
            "domain": DOMAIN_TIRE,
            "entry_kind": ENTRY_KIND_ALIAS,
            "surface_form": cluster.surface_form,
            "canonical_form": cluster.canonical_form,
            "evidence": l7_evidence_text(cluster),
            "proposer_context": rewrite_evidence(cluster),
        },
        context,
    )
    return "semantic_lexicon", result["id"]


def mine_edit_diffs(
    conn, *, window_seconds: int = CLUSTER_WINDOW_SECONDS
) -> MiningRun:
    """Read -> diff -> cluster -> propose, on a CALLER-OWNED connection.

    No commit: the caller owns the transaction, matching the aggregator and the
    retention sweep. A run either lands whole or is retried, and a retry is safe
    because both idempotence legs are.
    """
    watermark = read_watermark(conn)
    rewrites, rows_read, pii_dropped = read_edited_sends(
        conn, window_seconds=window_seconds
    )
    newest = max((r.at for r in rewrites), default=0.0)
    if not rewrites or newest <= watermark:
        logger.info(
            "edit_diff_mining: no mineable edited send newer than the watermark "
            "(%s row(s), %s rewrite(s), %s dropped for PII in the %ss window); "
            "nothing proposed.",
            rows_read,
            len(rewrites),
            pii_dropped,
            window_seconds,
        )
        return MiningRun(
            edited_sends=rows_read,
            rewrites=len(rewrites),
            pii_dropped=pii_dropped,
            watermark=watermark,
        )

    clusters = cluster_rewrites(rewrites)
    tripped = tripped_rewrites(clusters)
    counts: Counter[str] = Counter()
    emissions: list[dict[str, Any]] = []

    for cluster in tripped:
        try:
            # ONE savepoint per emission, around every arm rather than around the
            # one that happened to need it. A governed refusal must not take the
            # run down with it, and two of them can: a `conflict` is a real
            # UniqueViolation, which aborts the whole Postgres transaction, so
            # catching the exception without unwinding leaves every later
            # statement -- the next cluster, the metric, the run's audit row --
            # failing with InFailedSqlTransaction. `conn.transaction()` issues a
            # SAVEPOINT inside the caller's transaction and rolls back to it, so
            # a refused emission leaves no partial row and no audit row for a
            # write that did not happen.
            with conn.transaction():
                emitted = _emit(conn, _mining_context(), cluster)
        except ToolDriverError as exc:
            if exc.error_class == "conflict":
                # The L7 store's idempotence leg: this surface form already has a
                # row, in some status. A re-run is a no-op rather than a failure.
                # It also absorbs the case where an admin's own entry maps the
                # same surface form elsewhere -- counted on the run's audit row,
                # because a scheduled job cannot adjudicate a disagreement and
                # must not stop every other cluster in order to report one.
                counts["already_open"] += 1
                logger.info(
                    "edit_diff_mining: %r already has a lexicon row; not "
                    "re-proposed.",
                    cluster.cluster_key,
                )
                continue
            if exc.error_class != "policy_blocked":
                raise
            # D13: routine, never fatal, never silent. A recurring rewrite whose
            # span carries an injection pattern is exactly what the write scans
            # are for; the job counts the refusal and carries on.
            counts["blocked"] += 1
            _count_metric(conn, METRIC_EDIT_DIFF_BLOCKED)
            logger.info(
                "edit_diff_mining: cluster %r was refused by the %s write scan "
                "(policy_blocked); counted, not retried.",
                cluster.cluster_key,
                cluster.shape,
            )
            continue

        if emitted is None:
            counts["already_open"] += 1
            continue
        target_type, target_id = emitted
        counts["emitted"] += 1
        _count_metric(conn, METRIC_EDIT_DIFF_PROPOSED)
        emissions.append(
            {
                "cluster": cluster.cluster_key,
                "shape": cluster.shape,
                "target_type": target_type,
                "target_id": target_id,
                # The machine-readable evidence link, in the one place nothing
                # scans it. See the module docstring for why it cannot ride the
                # proposal row.
                "draft_correlation_ids": list(cluster.draft_refs),
            }
        )

    run = MiningRun(
        edited_sends=rows_read,
        rewrites=len(rewrites),
        pii_dropped=pii_dropped,
        clusters=len(clusters),
        tripped=len(tripped),
        emitted=counts["emitted"],
        already_open=counts["already_open"],
        blocked=counts["blocked"],
        watermark=newest,
        emissions=tuple(emissions),
    )
    _record_run(conn, run, window_seconds=window_seconds)
    return run


def _count_metric(conn, metric: str) -> None:
    from .datastore.handlers._common import insert_metric_event

    insert_metric_event(conn, metric=metric)


def _record_run(conn, run: MiningRun, *, window_seconds: int) -> None:
    """The run's audit row: the watermark, the counts, and the evidence link."""
    from toee_hermes.plugin.profiles import INTERNAL

    from .datastore.handlers._common import insert_audit

    insert_audit(
        conn,
        # Unattended, exactly like the aggregator and the retention sweep.
        profile=INTERNAL,
        account_id=None,
        action=MINING_AUDIT_ACTION,
        target_type="draft_feedback",
        target_id=None,
        details={
            "watermark": run.watermark,
            "window_seconds": window_seconds,
            "edited_sends": run.edited_sends,
            "rewrites": run.rewrites,
            "pii_dropped": run.pii_dropped,
            "clusters": run.clusters,
            "tripped": run.tripped,
            "emitted": run.emitted,
            "already_open": run.already_open,
            "blocked": run.blocked,
            "emissions": run.emissions,
        },
    )


def run_edit_diff_mining_job(
    payload: Mapping[str, Any], *, conn: Optional[Any] = None
) -> None:
    """The ``edit_diff_mining`` job body (FR-33).

    ``conn`` is injectable for tests (an isolated-schema connection); production
    takes a pooled connection, matching the aggregator and the ledger prune. A
    failure propagates so the job retries then dead-letters -- both idempotence
    legs make the retry safe.
    """
    del payload  # scheduled job; the (schedule_window, window_start) payload is unused.
    if conn is not None:
        _mine_and_commit(conn)
        return
    from .datastore.config import database_url
    from .datastore.pool import get_database_pool

    with get_database_pool(database_url()).connection() as pooled:
        _mine_and_commit(pooled)


def _mine_and_commit(conn) -> MiningRun:
    run = mine_edit_diffs(conn)
    conn.commit()
    logger.info(
        "edit_diff_mining: %s edited send(s) -> %s rewrite(s) (%s PII-dropped) -> "
        "%s cluster(s), %s tripped; proposed=%s already_open=%s blocked=%s",
        run.edited_sends,
        run.rewrites,
        run.pii_dropped,
        run.clusters,
        run.tripped,
        run.emitted,
        run.already_open,
        run.blocked,
    )
    return run


__all__ = [
    "ALIAS_MAX_TOKENS",
    "EDITED_OUTCOME",
    "MAX_EQUAL_GAP_TOKENS",
    "METRIC_EDIT_DIFF_BLOCKED",
    "METRIC_EDIT_DIFF_PROPOSED",
    "MINEABLE_MAX_SPAN_TOKENS",
    "MINING_AUDIT_ACTION",
    "SHAPE_L6_PROCEDURE",
    "SHAPE_L7_ALIAS",
    "MiningRun",
    "Rewrite",
    "RewriteCluster",
    "carries_pii",
    "cluster_rewrites",
    "l6_proposal_content",
    "l7_evidence_text",
    "mine_edit_diffs",
    "mineable_rewrites",
    "proposal_shape",
    "read_edited_sends",
    "read_watermark",
    "rewrite_evidence",
    "rewrites_for",
    "run_edit_diff_mining_job",
    "tripped_rewrites",
]
