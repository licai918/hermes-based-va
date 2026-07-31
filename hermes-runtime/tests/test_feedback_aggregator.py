"""0.0.5 S25 (FR-32): the aggregator's routing table and its thresholds.

The DB-free half. Everything here is a pure function of the feedback rows, so it
can be exercised at every threshold boundary without a database; the live-Postgres
half (emission, idempotence, the watermark, swallowed ``policy_blocked``) is
``test_datastore_feedback_aggregator.py``.

Two of these tests are structural on purpose, because the alternative is an
allowlist somebody has to remember to extend:

* the routing table is asserted against the ACTUAL reason-tag vocabularies
  (``plugin/schemas.py``) in BOTH directions, so adding a tag there without
  deciding its route fails here rather than being silently dropped at runtime;
* the thresholds are asserted at N-1, N and N+1, because a fixture with exactly
  N members cannot tell "requires N" from "requires any".
"""

from __future__ import annotations

import pytest

from hermes_runtime.feedback_aggregator import (
    DEST_KNOWLEDGE_OPS,
    DEST_L6_PROCEDURE,
    DEST_NOT_ROUTED,
    DEST_PERSONA_REVIEW,
    EMITTING_DESTINATIONS,
    FEEDBACK_SIGNAL_ROUTES,
    SAME_TAG_FAIL_THRESHOLD,
    SIMILAR_EDIT_DIFF_THRESHOLD,
    FeedbackSignal,
    UnroutedFeedbackSignal,
    cluster_feedback,
    route_for,
    tripped_clusters,
)
from toee_hermes.plugin.schemas import (
    EXTERNAL_REVIEW_REASON_TAGS,
    INTERNAL_REVIEW_REASON_TAGS,
)


def _signal(row_id: str, subject_ref: str, tag: str, at: float = 1.0) -> FeedbackSignal:
    return FeedbackSignal(row_id=row_id, subject_ref=subject_ref, tag=tag, at=at)


def _fails(tag: str, subjects: int, *, per_subject: int = 1) -> list[FeedbackSignal]:
    """``subjects`` distinct subjects, each flagged ``per_subject`` times."""
    return [
        _signal(f"irev_{s}_{n}", f"auto_handled_record:rec_{s}", tag, at=float(s))
        for s in range(subjects)
        for n in range(per_subject)
    ]


# --- the thresholds are named constants (D16) ---------------------------------


def test_the_grill_locked_starting_values_are_named_constants() -> None:
    # D16: S22's knob panel reads these BY NAME, so they may not be inline
    # literals. The values themselves are the grill's locked starting point.
    assert SAME_TAG_FAIL_THRESHOLD == 3
    assert SIMILAR_EDIT_DIFF_THRESHOLD == 3


# --- the routing table, asserted structurally ---------------------------------


def test_every_declared_reason_tag_has_a_route() -> None:
    # Set equality in BOTH directions. A new tag in schemas.py with no route
    # fails here; a route for a tag that no longer exists fails here too. An
    # allowlist of "the tags the fixture happens to use" would catch neither.
    declared = set(EXTERNAL_REVIEW_REASON_TAGS) | set(INTERNAL_REVIEW_REASON_TAGS)
    assert set(FEEDBACK_SIGNAL_ROUTES) == declared


def test_every_route_names_a_known_destination_and_says_why() -> None:
    known = {
        DEST_L6_PROCEDURE,
        DEST_PERSONA_REVIEW,
        DEST_KNOWLEDGE_OPS,
        DEST_NOT_ROUTED,
    }
    for tag, route in FEEDBACK_SIGNAL_ROUTES.items():
        assert route.destination in known, tag
        # A destination with no stated reason is how a table rots into folklore.
        assert route.note.strip(), tag


def test_an_unknown_tag_fails_closed_rather_than_being_dropped() -> None:
    # "Fails closed" = no emission AND visible. Silently returning None here
    # would route an unrecognised signal into nothing at all.
    with pytest.raises(UnroutedFeedbackSignal):
        route_for("a_tag_nobody_declared")


@pytest.mark.parametrize(
    "tag", ["tool_misuse", "wrong_action", "should_have_escalated"]
)
def test_the_action_tags_route_to_an_l6_procedure_proposal(tag: str) -> None:
    # C6 6.2 row 3, verbatim: `propose_experience`, source=feedback_derived.
    assert route_for(tag).destination == DEST_L6_PROCEDURE


@pytest.mark.parametrize(
    "tag", ["wrong_tone", "too_verbose", "tone_inappropriate"]
)
def test_the_tone_tags_route_out_of_memory_to_a_persona_review(tag: str) -> None:
    # C6 6.2 row 5: OUT of memory -> persona-change inbox item. Routed, never
    # stored as memory content.
    assert route_for(tag).destination == DEST_PERSONA_REVIEW


def test_policy_violation_routes_out_of_the_memory_layers(tag: str = "policy_violation") -> None:
    # C6 6.2 row 6: policy slots via the existing publish gate. KnowledgeOps is a
    # queue a human already works, and it has no propose-shaped action a job may
    # call -- see the route's note.
    assert route_for(tag).destination == DEST_KNOWLEDGE_OPS


def test_the_emitting_destinations_are_exactly_the_two_with_a_governed_action() -> None:
    # The gap-audit non-negotiable: an emission goes through a governed propose
    # action or it does not happen. These are the two that have one.
    assert EMITTING_DESTINATIONS == (DEST_L6_PROCEDURE, DEST_PERSONA_REVIEW)


# --- clustering ---------------------------------------------------------------


def test_a_cluster_is_keyed_on_the_tag_and_carries_its_rows_as_evidence() -> None:
    clusters = cluster_feedback(_fails("tool_misuse", 2) + _fails("wrong_tone", 1))

    by_tag = {c.tag: c for c in clusters}
    assert set(by_tag) == {"tool_misuse", "wrong_tone"}
    assert by_tag["tool_misuse"].size == 2
    assert len(by_tag["tool_misuse"].row_ids) == 2


def test_one_feedback_row_lands_in_a_cluster_for_each_of_its_tags() -> None:
    rows = [
        _signal("irev_a", "auto_handled_record:rec_a", "tool_misuse"),
        _signal("irev_a", "auto_handled_record:rec_a", "wrong_tone"),
    ]
    assert {c.tag for c in cluster_feedback(rows)} == {"tool_misuse", "wrong_tone"}


@pytest.mark.parametrize(
    "subjects,expected",
    [
        (SAME_TAG_FAIL_THRESHOLD - 1, False),
        (SAME_TAG_FAIL_THRESHOLD, True),
        (SAME_TAG_FAIL_THRESHOLD + 1, True),
    ],
)
def test_the_threshold_needs_n_distinct_subjects(subjects: int, expected: bool) -> None:
    # N-1 / N / N+1. Without the N-1 leg a `>= 1` implementation passes.
    tripped = tripped_clusters(cluster_feedback(_fails("tool_misuse", subjects)))
    assert bool(tripped) is expected


def test_one_subject_flagged_n_times_is_not_a_cluster() -> None:
    # "N same-tag fails on SIMILAR SUBJECTS": one bad interaction re-reviewed
    # three times is one problem, not three. The fixture is deliberately one the
    # threshold must EXCLUDE -- counting rows instead of subjects passes without
    # it.
    signals = _fails("tool_misuse", 1, per_subject=SAME_TAG_FAIL_THRESHOLD + 2)

    (cluster,) = cluster_feedback(signals)
    assert len(cluster.row_ids) == SAME_TAG_FAIL_THRESHOLD + 2
    assert cluster.size == 1
    assert tripped_clusters([cluster]) == []


def test_the_job_is_wired_into_the_background_worker_and_not_the_turn_worker() -> None:
    # A schedule with no body in the allowlist is a job that fails on every tick;
    # a body with no schedule is a job that never runs at all.
    from hermes_runtime.background_worker import (
        BACKGROUND_JOB_TYPES,
        SCHEDULES,
        job_bodies,
    )
    from hermes_runtime.job_queue import (
        AGENT_TURN_JOB_TYPE,
        FEEDBACK_AGGREGATOR_JOB_TYPE,
    )

    assert FEEDBACK_AGGREGATOR_JOB_TYPE in BACKGROUND_JOB_TYPES
    assert FEEDBACK_AGGREGATOR_JOB_TYPE in job_bodies()
    assert any(s.job_type == FEEDBACK_AGGREGATOR_JOB_TYPE for s in SCHEDULES)
    # FR-9 isolation: nothing on this worker may claim a customer turn.
    assert AGENT_TURN_JOB_TYPE not in BACKGROUND_JOB_TYPES


def test_a_cluster_records_the_window_its_rows_span() -> None:
    signals = [
        _signal("irev_1", "auto_handled_record:rec_1", "tool_misuse", at=100.0),
        _signal("irev_2", "auto_handled_record:rec_2", "tool_misuse", at=300.0),
    ]
    (cluster,) = cluster_feedback(signals)
    assert (cluster.first_seen, cluster.last_seen) == (100.0, 300.0)
