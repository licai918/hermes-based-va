"""Loop-closure metrics: did the control loop actually close? (0.0.5 S28, FR-34b)

C6 §6.5. Three joins over rows earlier slices already write -- **zero new emit
seams, and no migration**:

* **conversion** -- S25's aggregator run audit rows x the two feedback tables.
* **post-fix re-fail** -- confirmed feedback-derived L6 proposals x the feedback
  that arrived afterwards.
* **per-entry honored trend** -- S09's ``injection_ledger`` x S26's
  ``judged_turn``, split at each L7 entry's own edit.

Read-only, admin-panel-only. Nothing here reaches a turn, gates a build, or
writes anything (NFR-3/NFR-4/NFR-5 are satisfied by construction, not by care).

**The shape is not built here.** Every label, every caveat and the
below-the-floor "no percentage off one data point" rule live in
:func:`toee_hermes.lifecycle_metrics.loop_closure_payload`, which the mock twin
calls with no arguments -- so the two twins cannot render different tiles
(NFR-7). This module owns only the SQL and the one window this slice introduces.

**Two join keys this module does NOT own, and how it avoids restating them.**
``details->'emissions'`` is S25's audit shape and ``proposer_context->>...`` is
S25's evidence key; both are pinned in ``test_datastore_loop_closure.py`` against
the shipped builders rather than trusted, because a rename there would otherwise
surface here as "conversion quietly went to zero" rather than as a red test.

**What routability MEANS is S25's decision, read not re-decided.** A tag is
routable iff the Signal Routing Table sends it to a destination this job may
emit into. Six of the eleven declared tags qualify today and five terminate
elsewhere (D23) -- but that split is derived on every call, never written down
here, because it is exactly the sort of count that is true on the day it is
typed and wrong afterwards.
"""

from __future__ import annotations

from typing import Any, Optional

from toee_hermes.lifecycle_metrics import loop_closure_payload

from .entry_effectiveness import HEALTH_HONORED_LEG as HONORED_LEG
from .feedback_aggregator import (
    AGGREGATOR_AUDIT_ACTION,
    CLUSTER_WINDOW_SECONDS,
    DRAFT_FAIL_VERDICT,
    EMITTING_DESTINATIONS,
    FEEDBACK_SIGNAL_ROUTES,
    INTERACTION_FAIL_VERDICT,
)
from .injection_ledger import LAYER_L7

# How long after a confirmed fix a recurrence still counts as that fix failing,
# AND how old a fix must be before it is judged at all. ONE constant for both
# halves on purpose: it is what makes the sides comparable -- every matured fix
# is watched for exactly the same length of time, and a fix confirmed this
# morning cannot contribute a flattering "clean" to a rate.
#
# ponytail: 30 days, matching the aggregator's clustering window, because a
# recurrence only becomes actionable once it can cluster. There is no coupling
# constraint of D12's kind here -- neither feedback table is pruned, so a
# recurrence cannot be garbage-collected out from under this window.
POST_FIX_WATCH_WINDOW_SECONDS = 30 * 24 * 60 * 60

# The key S25's `cluster_evidence` stores the cluster's reason tag under. Pinned
# against the real builder by a test rather than imported, because it is a dict
# literal in that module and not a constant to import.
CLUSTER_TAG_EVIDENCE_KEY = "feedback_cluster"

# Every failing feedback row exploded to one (row, subject, tag, created_at)
# signal -- the same union `read_feedback_signals` uses, expressed as a CTE body
# so the three queries below can each scope it their own way. DISTINCT because
# "a signal" is a (row, tag) pair: a reason_tags array carrying one tag twice is
# one signal, not two.
_SIGNALS_CTE = """
SELECT DISTINCT ir.id, ir.subject_kind || ':' || ir.subject_id AS subject_ref,
       tag, ir.created_at
  FROM interaction_review ir, unnest(ir.reason_tags) AS tag
 WHERE ir.verdict = %(interaction_fail)s
UNION
SELECT DISTINCT df.id, 'draft:' || df.draft_correlation_id, tag, df.created_at
  FROM draft_feedback df, unnest(df.reason_tags) AS tag
 WHERE df.verdict = %(draft_fail)s
"""

# Every (tag, feedback row) pair the aggregator has ever named as the evidence
# behind a proposal it raised. The emissions live in the run's audit row because
# S25 could not put the ids on the proposal itself -- the write scans would have
# rejected or mangled them.
_CONVERTED_CTE = """
SELECT DISTINCT e->>'tag' AS tag,
       jsonb_array_elements_text(e->'feedback_row_ids') AS row_id
  FROM workbench_audit_log w,
       jsonb_array_elements(w.details->'emissions') AS e
 WHERE w.action = %(aggregator_action)s
"""


def routable_feedback_tags() -> set[str]:
    """The reason tags S25's routing table sends to a governed propose action."""
    return {
        tag
        for tag, route in FEEDBACK_SIGNAL_ROUTES.items()
        if route.destination in EMITTING_DESTINATIONS
    }


def is_routable_feedback_tag(tag: str) -> bool:
    """Fail-closed: an undeclared tag is NOT routable.

    It then lands in the unroutable row rather than silently inflating the
    conversion denominator with a signal that could never have converted.
    """
    return tag in routable_feedback_tags()


def conversion_counts(
    conn, *, window_seconds: int = CLUSTER_WINDOW_SECONDS
) -> tuple[int, int, int, int]:
    """``(converted, routable, unroutable, total)`` signals in the window.

    The conversion side is a LEFT JOIN, not a second count: an emission may cite
    a feedback row that has since aged out of this window (the aggregator's read
    window is the same length but not the same span), and counting those in the
    numerator alone would produce a conversion rate above 100%.
    """
    sql = f"""
        WITH signal AS ({_SIGNALS_CTE}), converted AS ({_CONVERTED_CTE})
        SELECT s.tag,
               count(*) FILTER (WHERE c.row_id IS NOT NULL) AS converted,
               count(*) AS total
          FROM signal s
          LEFT JOIN converted c ON c.tag = s.tag AND c.row_id = s.id
         WHERE s.created_at >= now() - make_interval(secs => %(window)s)
         GROUP BY s.tag
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "interaction_fail": INTERACTION_FAIL_VERDICT,
                "draft_fail": DRAFT_FAIL_VERDICT,
                "aggregator_action": AGGREGATOR_AUDIT_ACTION,
                "window": window_seconds,
            },
        )
        rows = cur.fetchall()

    routable_tags = routable_feedback_tags()
    converted = routable = unroutable = total = 0
    for tag, tag_converted, tag_total in rows:
        total += tag_total
        if tag in routable_tags:
            routable += tag_total
            converted += tag_converted
        else:
            unroutable += tag_total
    return converted, routable, unroutable, total


def post_fix_refail_counts(
    conn, *, window_seconds: int = POST_FIX_WATCH_WINDOW_SECONDS
) -> tuple[int, int, int]:
    """``(refailed, matured, maturing)`` confirmed feedback-derived fixes.

    A fix is one CONFIRMED L6 procedure proposal whose source is
    ``feedback_derived`` and whose ``proposer_context`` names the reason tag it
    was clustered from. Persona-review items are deliberately absent: an
    acknowledged one changes nothing by itself (the persona moves by dev edit +
    eval re-record), so counting it as a fix would put a rate on an intervention
    that never happened.
    """
    from toee_hermes.drivers.mock.agent_experience import (
        AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED,
    )

    sql = f"""
        WITH signal AS ({_SIGNALS_CTE}),
        fix AS (
            SELECT ae.id,
                   ae.proposer_context->>%(tag_key)s AS tag,
                   ae.decided_at
              FROM agent_experience ae
             WHERE ae.source = %(feedback_derived)s
               AND ae.status = 'confirmed'
               AND ae.decided_at IS NOT NULL
               AND ae.proposer_context->>%(tag_key)s IS NOT NULL
        ),
        origin AS (
            SELECT e->>'target_id' AS target_id,
                   jsonb_array_elements_text(e->'subject_refs') AS subject_ref
              FROM workbench_audit_log w,
                   jsonb_array_elements(w.details->'emissions') AS e
             WHERE w.action = %(aggregator_action)s
        ),
        matured AS (
            SELECT * FROM fix
             WHERE decided_at <= now() - make_interval(secs => %(window)s)
        )
        SELECT
            (SELECT count(*) FROM matured),
            (SELECT count(*) FROM fix) - (SELECT count(*) FROM matured),
            (SELECT count(*) FROM matured m
              WHERE EXISTS (
                SELECT 1 FROM signal s
                 WHERE s.tag = m.tag
                   AND s.created_at > m.decided_at
                   AND s.created_at <= m.decided_at
                                      + make_interval(secs => %(window)s)
                   AND NOT EXISTS (
                        SELECT 1 FROM origin o
                         WHERE o.target_id = m.id
                           AND o.subject_ref = s.subject_ref
                   )
              ))
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "interaction_fail": INTERACTION_FAIL_VERDICT,
                "draft_fail": DRAFT_FAIL_VERDICT,
                "aggregator_action": AGGREGATOR_AUDIT_ACTION,
                "feedback_derived": AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED,
                "tag_key": CLUSTER_TAG_EVIDENCE_KEY,
                "window": window_seconds,
            },
        )
        matured, maturing, refailed = cur.fetchone()
    return int(refailed), int(matured), int(maturing)


def entry_trend_counts(conn) -> tuple[int, int, int]:
    """``(improved, compared, one_sided)`` edited L7 entries.

    Per entry, the honored leg over the turns the ledger says carried it, split
    at that entry's own ``updated_at``. Deliberately NOT read from
    ``entry_effectiveness``: that table is a full-recompute SNAPSHOT with no
    history, so its per-entry score mixes pre-edit and post-edit turns into one
    number -- which is the exact comparability failure this metric exists to
    avoid. The raw join is one query on an admin read path, off every turn.
    """
    sql = """
        WITH edited AS (
            SELECT id, updated_at
              FROM semantic_lexicon
             WHERE status = 'confirmed'
               AND updated_at > coalesce(decided_at, created_at)
        ),
        split AS (
            SELECT e.id,
                   count(*) FILTER (
                       WHERE il.injected_at < e.updated_at AND jt.passed IS NOT NULL
                   ) AS before_determinate,
                   count(*) FILTER (
                       WHERE il.injected_at < e.updated_at AND jt.passed IS TRUE
                   ) AS before_passed,
                   count(*) FILTER (
                       WHERE il.injected_at >= e.updated_at AND jt.passed IS NOT NULL
                   ) AS after_determinate,
                   count(*) FILTER (
                       WHERE il.injected_at >= e.updated_at AND jt.passed IS TRUE
                   ) AS after_passed
              FROM edited e
              JOIN injection_ledger il
                ON il.layer = %(layer)s AND il.entry_ref = e.id
              JOIN judged_turn jt
                ON jt.turn_ref = il.turn_ref AND jt.leg = %(leg)s
             GROUP BY e.id
        )
        SELECT
            count(*) FILTER (
                WHERE before_determinate > 0 AND after_determinate > 0
                  AND after_passed::float / after_determinate
                      >= before_passed::float / before_determinate
            ),
            count(*) FILTER (WHERE before_determinate > 0 AND after_determinate > 0),
            count(*) FILTER (
                WHERE (before_determinate > 0) <> (after_determinate > 0)
            )
          FROM split
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"layer": LAYER_L7, "leg": HONORED_LEG})
        improved, compared, one_sided = cur.fetchone()
    return int(improved), int(compared), int(one_sided)


def loop_closure_metrics(
    conn, *, window_seconds: Optional[int] = None
) -> dict[str, Any]:
    """The FR-34b block, in the shared shape both twins render."""
    converted, routable, unroutable, total = conversion_counts(
        conn, window_seconds=window_seconds or CLUSTER_WINDOW_SECONDS
    )
    refailed, matured, maturing = post_fix_refail_counts(conn)
    improved, compared, one_sided = entry_trend_counts(conn)
    return loop_closure_payload(
        converted_signals=converted,
        routable_signals=routable,
        unroutable_signals=unroutable,
        total_signals=total,
        refailed_fixes=refailed,
        matured_fixes=matured,
        maturing_fixes=maturing,
        improved_entries=improved,
        compared_entries=compared,
        one_sided_entries=one_sided,
    )


__all__ = [
    "CLUSTER_TAG_EVIDENCE_KEY",
    "HONORED_LEG",
    "POST_FIX_WATCH_WINDOW_SECONDS",
    "conversion_counts",
    "entry_trend_counts",
    "is_routable_feedback_tag",
    "loop_closure_metrics",
    "post_fix_refail_counts",
    "routable_feedback_tags",
]
