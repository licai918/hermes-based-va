"""0.0.5 S28 (FR-34b): does the memory control loop actually CLOSE?

Layer ① of the three-layer gate for the three loop-closure numbers: feedback ->
proposal conversion, post-fix re-fail, and the per-entry honored trend after an
edit. All three are joins over rows S25/S26/S27/S09 already write, so what is
worth proving is not that SQL runs -- it is **scoping**.

Every fixture below is deliberately uneven: each number is different from every
other, and each one carries at least one row the scoping rule must EXCLUDE. A
fixture with one row per metric cannot tell a correct query from one that
returns everything.

Named ``test_datastore_*`` on purpose: CI's NFR-7 anti-skip gate matches that
prefix, so the live-Postgres half fails the build if it ever silently skips
where a Postgres is provisioned. The DB-free half (the shared builder, the
routing-table derivation, the mock twin) lives here too rather than in a second
file -- it is the same slice's contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hermes_runtime.datastore.handlers._common import insert_audit
from hermes_runtime.datastore.handlers.metrics import _get_aggregate_metrics
from hermes_runtime.feedback_aggregator import (
    AGGREGATOR_AUDIT_ACTION,
    CLUSTER_WINDOW_SECONDS,
    EMITTING_DESTINATIONS,
    FEEDBACK_SIGNAL_ROUTES,
    FeedbackCluster,
    aggregate_feedback,
    cluster_evidence,
)
from hermes_runtime.injection_ledger import LAYER_L6, LAYER_L7
from hermes_runtime.knobs import knob_panel
from hermes_runtime.loop_closure import (
    CLUSTER_TAG_EVIDENCE_KEY,
    HONORED_LEG,
    POST_FIX_WATCH_WINDOW_SECONDS,
    conversion_counts,
    entry_trend_counts,
    is_routable_feedback_tag,
    loop_closure_metrics,
    post_fix_refail_counts,
    routable_feedback_tags,
)
from toee_hermes.drivers.mock.agent_experience import (
    AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED,
)
from toee_hermes.drivers.mock.metrics import create_metrics_mock_handlers
from toee_hermes.lifecycle_metrics import (
    LOOP_CONVERSION,
    LOOP_ENTRY_TREND,
    LOOP_REFAIL,
    LOOP_UNROUTABLE,
    MIN_OBSERVATIONS_FOR_RATE,
    loop_closure_payload,
)
from toee_hermes.plugin.schemas import (
    EXTERNAL_REVIEW_REASON_TAGS,
    INTERNAL_REVIEW_REASON_TAGS,
)
from toee_hermes.tool_gate import ToolExecutionContext

_CTX = ToolExecutionContext(profile="internal_copilot")

_NOW = datetime.now(timezone.utc)


def _rows(payload) -> dict[str, dict]:
    return {row["key"]: row for row in payload["loop_closure"]}


# --- seeding helpers ----------------------------------------------------------


def _review(conn, row_id, subject, tags, *, verdict="fail", at=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO interaction_review
                (id, subject_kind, subject_id, verdict, reason_tags,
                 reviewer_account_id, created_at)
            VALUES (%s, 'auto_handled_record', %s, %s, %s, %s,
                    coalesce(%s, now()))
            """,
            (row_id, subject, verdict, tags, "acct_supervisor_1", at),
        )


def _case(conn, case_id):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cases (id, channel, status) VALUES (%s, 'sms', 'open') "
            "ON CONFLICT (id) DO NOTHING",
            (case_id,),
        )


def _draft(conn, row_id, correlation, tags, *, verdict="down", outcome="rated_only"):
    _case(conn, "case_s28")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO draft_feedback
                (id, case_id, draft_correlation_id, draft_kind, draft_text,
                 outcome, verdict, reason_tags, rep_account_id)
            VALUES (%s, 'case_s28', %s, 'sms', 'a draft', %s, %s, %s, %s)
            """,
            (row_id, correlation, outcome, verdict, tags, "acct_rep_1"),
        )


def _experience(conn, entry_id, *, tag, status, decided_at, source=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_experience
                (id, kind, status, content, source, proposer_context,
                 decider_account_id, decided_at)
            VALUES (%s, 'procedure', %s, %s, %s, %s, %s, %s)
            """,
            (
                entry_id,
                status,
                f"a proposal about {tag}",
                source or AGENT_EXPERIENCE_SOURCE_FEEDBACK_DERIVED,
                _jsonb({CLUSTER_TAG_EVIDENCE_KEY: tag}),
                "acct_supervisor_1",
                decided_at,
            ),
        )


def _jsonb(value):
    import json

    return json.dumps(value)


def _emissions_audit(conn, emissions):
    """One aggregator run audit row -- the ONLY place the subject refs live."""
    insert_audit(
        conn,
        profile="internal_copilot",
        account_id=None,
        action=AGGREGATOR_AUDIT_ACTION,
        target_type="feedback",
        target_id=None,
        details={"watermark": 0.0, "emissions": emissions},
    )


def _lexicon(conn, entry_id, *, decided_at, updated_at, surface):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO semantic_lexicon
                (id, domain, entry_kind, surface_form, canonical_form, status,
                 provenance, decider_account_id, decided_at, created_at, updated_at)
            VALUES (%s, 'tire', 'alias', %s, 'canonical', 'confirmed',
                    'admin_manual', 'acct_supervisor_1', %s, %s, %s)
            """,
            (entry_id, surface, decided_at, decided_at, updated_at),
        )


def _ledger(conn, turn_ref, layer, entry_ref, injected_at):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO injection_ledger (turn_ref, layer, entry_ref, injected_at) "
            "VALUES (%s, %s, %s, %s)",
            (turn_ref, layer, entry_ref, injected_at),
        )


def _verdict(conn, turn_ref, leg, passed):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO judged_turn (turn_ref, leg, passed) VALUES (%s, %s, %s)",
            (turn_ref, leg, passed),
        )


# --- 1. conversion, end to end through the REAL aggregator ---------------------


def test_conversion_counts_only_routable_signals_and_reads_the_real_emissions(
    datastore,
) -> None:
    """The numerator comes from what the aggregator ACTUALLY wrote, not a fixture.

    Seeding the audit row by hand would prove the SQL parses and nothing else --
    the shape of ``details->emissions`` is S25's, and a rename there is exactly
    the drift this metric would otherwise report as "conversion collapsed to 0".
    So this seeds feedback, runs the shipped job, and reads the numbers back.

    The fixture answers four different questions with four different numbers, and
    carries three rows every one of them must exclude.
    """
    _driver, conn, _schema = datastore

    # 3 distinct subjects, routable -> trips N=3 and emits. 3 converted signals.
    for n in range(3):
        _review(conn, f"irev_tm_{n}", f"rec_tm_{n}", ["tool_misuse"])
    # 2 distinct subjects, routable, BELOW the threshold -> reaches nobody. It is
    # in the denominator on purpose: the question is whether feedback reached a
    # human, and N is the knob that decides.
    for n in range(2):
        _review(conn, f"irev_wa_{n}", f"rec_wa_{n}", ["wrong_action"])
    # 4 signals with nowhere legal to go (D23) -> out of the conversion
    # denominator entirely, counted in their own row.
    for n in range(4):
        _review(conn, f"irev_mi_{n}", f"rec_mi_{n}", ["missed_information"])
    # The SECOND feedback table, so a query that forgot the union is visible.
    _draft(conn, "dfb_tv_0", "corr_tv_0", ["too_verbose"])

    # --- the three rows the scoping must exclude ---
    _review(conn, "irev_pass", "rec_pass", ["tool_misuse"], verdict="pass")
    _draft(conn, "dfb_up", "corr_up", ["too_verbose"], verdict="up")
    _review(
        conn,
        "irev_old",
        "rec_old",
        ["tool_misuse"],
        at=_NOW - timedelta(seconds=CLUSTER_WINDOW_SECONDS + 86400),
    )
    conn.commit()

    aggregate_feedback(conn)
    conn.commit()

    converted, routable, unroutable, total = conversion_counts(conn)
    assert (converted, routable, unroutable, total) == (3, 6, 4, 10)

    rows = _rows(loop_closure_metrics(conn))
    assert rows[LOOP_CONVERSION]["rate"] == 0.5
    assert rows[LOOP_UNROUTABLE]["rate"] == 0.4


def test_the_conversion_numerator_can_never_exceed_its_own_denominator(
    datastore,
) -> None:
    """An emission citing a row that has aged out of the window is not a bonus.

    The aggregator's read window and this metric's window are the same length but
    not the same span, so a run inside the window can legitimately cite a feedback
    row older than it. Counting those in the numerator alone would produce a
    conversion rate above 100% -- the join, not a clamp, is what prevents it.
    """
    _driver, conn, _schema = datastore
    _review(conn, "irev_new", "rec_new", ["tool_misuse"])
    _emissions_audit(
        conn,
        [
            {
                "tag": "tool_misuse",
                "target_id": "aexp_ancient",
                "feedback_row_ids": ["irev_new", "irev_long_gone"],
                "subject_refs": ["auto_handled_record:rec_new"],
            }
        ],
    )
    conn.commit()

    converted, routable, _unroutable, _total = conversion_counts(conn)
    assert (converted, routable) == (1, 1)


# --- 2. post-fix re-fail ------------------------------------------------------


def _seed_fixes(conn) -> None:
    matured = _NOW - timedelta(seconds=POST_FIX_WATCH_WINDOW_SECONDS + 86400)
    fresh = _NOW - timedelta(days=5)

    # A: confirmed, matured, TWO recurrences on new subjects -> exactly ONE re-fail.
    _experience(conn, "aexp_a", tag="tool_misuse", status="confirmed", decided_at=matured)
    _emissions_audit(
        conn,
        [
            {
                "tag": "tool_misuse",
                "target_id": "aexp_a",
                "feedback_row_ids": ["irev_a_seed"],
                "subject_refs": ["auto_handled_record:rec_a_seed"],
            }
        ],
    )
    for n in range(2):
        _review(
            conn,
            f"irev_a_again_{n}",
            f"rec_a_new_{n}",
            ["tool_misuse"],
            at=matured + timedelta(days=1 + n),
        )

    # B: confirmed, matured, nothing came back -> clean.
    _experience(conn, "aexp_b", tag="wrong_action", status="confirmed", decided_at=matured)

    # C: the recurrence is on a subject the proposal was RAISED FROM -- a
    # re-review of pre-fix evidence, not a new failure.
    _experience(
        conn, "aexp_c", tag="should_have_escalated", status="confirmed", decided_at=matured
    )
    _emissions_audit(
        conn,
        [
            {
                "tag": "should_have_escalated",
                "target_id": "aexp_c",
                "feedback_row_ids": ["irev_c_seed"],
                "subject_refs": ["auto_handled_record:rec_c_origin"],
            }
        ],
    )
    _review(
        conn,
        "irev_c_again",
        "rec_c_origin",
        ["should_have_escalated"],
        at=matured + timedelta(days=2),
    )

    # D: the recurrence lands AFTER the watch window closed -- every fix is
    # watched for the same length of time or the sides are not comparable.
    _experience(
        conn, "aexp_d", tag="tone_inappropriate", status="confirmed", decided_at=matured
    )
    _review(
        conn,
        "irev_d_late",
        "rec_d_new",
        ["tone_inappropriate"],
        at=matured + timedelta(seconds=POST_FIX_WATCH_WINDOW_SECONDS + 3600),
    )
    # ... and a recurrence carrying a DIFFERENT tag is a different problem. This
    # row carries the tag of the REJECTED proposal below, so it is load-bearing
    # twice: drop the same-tag join and fix D re-fails, drop the confirmed-only
    # filter and F enters the denominator AND re-fails.
    _review(
        conn,
        "irev_d_other_tag",
        "rec_d_new2",
        ["wrong_tone"],
        at=matured + timedelta(days=1),
    )

    # E: confirmed 5 days ago and already re-failing -- excluded from BOTH sides,
    # because a fix nobody has had time to re-fail must not read as clean.
    _experience(conn, "aexp_e", tag="too_verbose", status="confirmed", decided_at=fresh)
    _review(
        conn, "irev_e_again", "rec_e_new", ["too_verbose"], at=fresh + timedelta(days=1)
    )

    # F/G: not fixes. A rejected proposal decided nothing, and an agent-proposed
    # entry was never a feedback signal.
    _experience(conn, "aexp_f", tag="wrong_tone", status="rejected", decided_at=matured)
    _experience(
        conn,
        "aexp_g",
        tag="tool_misuse",
        status="confirmed",
        decided_at=matured,
        source="copilot_agent",
    )
    conn.commit()


def test_a_confirmed_fix_that_comes_back_counts_once_and_a_clean_one_counts_clean(
    datastore,
) -> None:
    _driver, conn, _schema = datastore
    _seed_fixes(conn)

    refailed, matured, maturing = post_fix_refail_counts(conn)
    assert (refailed, matured, maturing) == (1, 4, 1)

    row = _rows(loop_closure_metrics(conn))[LOOP_REFAIL]
    assert row["rate"] == 0.25
    # The excluded fix is NAMED where the number renders, not only in a docstring.
    assert "1 confirmed fix" in row["detail"]


# --- 3. per-entry honored trend after an edit ---------------------------------


def _seed_entry_trends(conn) -> None:
    decided = _NOW - timedelta(days=40)
    edited = _NOW - timedelta(days=20)

    # E1 improved: before 1/2, after 2/2.
    _lexicon(conn, "lex_improved", decided_at=decided, updated_at=edited, surface="aa")
    for n, passed in ((0, True), (1, False)):
        _ledger(conn, f"t_i_b{n}", LAYER_L7, "lex_improved", decided + timedelta(days=1))
        _verdict(conn, f"t_i_b{n}", HONORED_LEG, passed)
    for n in range(2):
        _ledger(conn, f"t_i_a{n}", LAYER_L7, "lex_improved", edited + timedelta(days=1))
        _verdict(conn, f"t_i_a{n}", HONORED_LEG, True)
    # Three MISAPPLICATION verdicts on further post-edit turns. With the leg
    # filter they contribute nothing; without it E1's after rate falls to 2/5 and
    # the entry flips out of the numerator.
    for n in range(3):
        _ledger(conn, f"t_i_m{n}", LAYER_L7, "lex_improved", edited + timedelta(days=2))
        _verdict(conn, f"t_i_m{n}", "no_misapplication", False)

    # E2 regressed: before 2/2, after 0/2.
    _lexicon(conn, "lex_regressed", decided_at=decided, updated_at=edited, surface="bb")
    for n in range(2):
        _ledger(conn, f"t_r_b{n}", LAYER_L7, "lex_regressed", decided + timedelta(days=1))
        _verdict(conn, f"t_r_b{n}", HONORED_LEG, True)
    for n in range(2):
        _ledger(conn, f"t_r_a{n}", LAYER_L7, "lex_regressed", edited + timedelta(days=1))
        _verdict(conn, f"t_r_a{n}", HONORED_LEG, False)

    # E3 one-sided: judged only AFTER the edit -- a before with no after (or the
    # reverse) is not a trend. Its L6 ledger rows would supply the missing side to
    # a query that dropped the layer filter, moving `compared` from 2 to 3.
    _lexicon(conn, "lex_one_sided", decided_at=decided, updated_at=edited, surface="cc")
    _ledger(conn, "t_o_a0", LAYER_L7, "lex_one_sided", edited + timedelta(days=1))
    _verdict(conn, "t_o_a0", HONORED_LEG, True)
    _ledger(conn, "t_o_l6", LAYER_L6, "lex_one_sided", decided + timedelta(days=1))
    _verdict(conn, "t_o_l6", HONORED_LEG, True)

    # E4 never edited: updated_at == decided_at. Verdicts on both sides, so a
    # query that forgot the edited-since-decided rule returns 3 or 4, not 2.
    _lexicon(conn, "lex_unedited", decided_at=decided, updated_at=decided, surface="dd")
    _ledger(conn, "t_u_b0", LAYER_L7, "lex_unedited", decided - timedelta(days=1))
    _verdict(conn, "t_u_b0", HONORED_LEG, False)
    _ledger(conn, "t_u_a0", LAYER_L7, "lex_unedited", decided + timedelta(days=1))
    _verdict(conn, "t_u_a0", HONORED_LEG, True)
    conn.commit()


def test_the_entry_trend_splits_each_entry_at_its_own_edit_and_reads_the_judge_leg(
    datastore,
) -> None:
    _driver, conn, _schema = datastore
    _seed_entry_trends(conn)

    improved, compared, one_sided = entry_trend_counts(conn)
    assert (improved, compared, one_sided) == (1, 2, 1)

    row = _rows(loop_closure_metrics(conn))[LOOP_ENTRY_TREND]
    assert row["rate"] == 0.5
    assert "1 edited entry" in row["detail"]


# --- 4. the empty and single-observation deployments --------------------------


def test_a_deployment_with_no_history_reports_not_computed_rather_than_zero(
    datastore,
) -> None:
    """Every key present, every rate null. This is the shipped state today."""
    _driver, conn, _schema = datastore
    rows = _rows(_get_aggregate_metrics(conn, {}, _CTX))
    assert set(rows) == {LOOP_CONVERSION, LOOP_UNROUTABLE, LOOP_REFAIL, LOOP_ENTRY_TREND}
    for key, row in rows.items():
        assert row["rate"] is None, key
        assert (row["numerator"], row["denominator"]) == (0, 0), key


def test_both_twins_always_ship_the_block_so_the_bff_null_branch_is_skew_only(
    datastore,
) -> None:
    """The BFF maps an ABSENT ``loop_closure`` to null rather than to a 502.

    That branch exists for ONE situation -- an app deployed ahead of its runtime
    image -- and this is where that claim is kept true: if either twin could omit
    the block, "not reported by this backend" would start meaning "a twin dropped
    it" and the panel would render a silence as a fact about the deployment.
    """
    _driver, conn, _schema = datastore
    handler = create_metrics_mock_handlers()["toee_metrics"]["get_aggregate_metrics"]
    assert handler({}, _CTX)["loop_closure"]
    assert _get_aggregate_metrics(conn, {}, _CTX)["loop_closure"]


def test_a_single_observation_is_reported_as_evidence_but_never_as_a_percentage() -> None:
    # 1/1 is 100% and 0/1 is 0%, and neither is a fact about anything. The raw
    # counts still travel, so the reader sees "1 / 1" rather than an empty tile.
    one = _rows(loop_closure_payload(refailed_fixes=1, matured_fixes=1))[LOOP_REFAIL]
    assert one["rate"] is None
    assert (one["numerator"], one["denominator"]) == (1, 1)

    two = _rows(loop_closure_payload(refailed_fixes=1, matured_fixes=2))[LOOP_REFAIL]
    assert two["rate"] == 0.5
    assert MIN_OBSERVATIONS_FOR_RATE == 2


# --- 5. the contracts that keep the numbers readable --------------------------


def test_no_loop_closure_rate_can_reach_a_renderer_without_its_numerator_and_scope() -> None:
    for row in loop_closure_payload()["loop_closure"]:
        assert row["label"].strip(), row
        # `detail` is where the denominator's meaning lives: what is counted,
        # over what window, and what is deliberately NOT in it.
        assert len(row["detail"].strip()) > 120, row
        assert "numerator" in row and "denominator" in row, row


def test_the_unroutable_row_names_why_each_destination_is_missing() -> None:
    # D23 is an OWNER decision, not a bug in the aggregator, and the tile has to
    # say which of the three reasons applies rather than implying a defect.
    detail = _rows(loop_closure_payload())[LOOP_UNROUTABLE]["detail"].lower()
    assert "nfr-3" in detail  # policy slots: a scheduled job may not write content
    assert "d9" in detail  # no review_item kind for an information gap
    assert "free-text" in detail  # `other` carries its meaning in the comment


def test_the_conversion_row_says_what_is_not_in_its_denominator_and_numerator() -> None:
    detail = _rows(loop_closure_payload())[LOOP_CONVERSION]["detail"].lower()
    assert "edit-diff" in detail  # S27's mined proposals have no tag denominator
    assert "threshold" in detail  # a below-N signal is unconverted on purpose


def test_the_entry_trend_row_says_it_does_not_read_hit_count() -> None:
    # D22: hit_count is structurally zero for every default_rule, so a
    # hit-based trend would report a healthy seasonal rule as dead.
    detail = _rows(loop_closure_payload())[LOOP_ENTRY_TREND]["detail"].lower()
    assert "hit_count" in detail
    assert "default_rule" in detail


def test_the_mock_twin_reports_the_same_loop_closure_block_at_zero() -> None:
    # NFR-7 through the SHARED builder, not a restatement.
    handler = create_metrics_mock_handlers()["toee_metrics"]["get_aggregate_metrics"]
    assert handler({}, _CTX)["loop_closure"] == loop_closure_payload()["loop_closure"]


# --- 6. the two join keys this slice does not own -----------------------------


def test_routability_is_derived_from_the_shipped_routing_table_not_a_remembered_count() -> None:
    """The denominator's membership rule has ONE source: S25's routing table.

    A literal "five of eleven tags" here would have been wrong on the day it was
    written -- the shipped table routes SIX tags to a governed propose action and
    leaves five terminal elsewhere.
    """
    declared = set(EXTERNAL_REVIEW_REASON_TAGS) | set(INTERNAL_REVIEW_REASON_TAGS)
    assert set(FEEDBACK_SIGNAL_ROUTES) == declared
    # The two literals here are a TRIPWIRE, not a source of truth: the metric
    # derives routability and never counts, but the module docstring and ADR-0164
    # both state today's split in prose. If a route moves, this reddens and forces
    # that prose to be corrected instead of quietly going stale -- which is how
    # D23's own heading came to disagree with its body.
    assert (len(declared), len(routable_feedback_tags())) == (11, 6)
    assert routable_feedback_tags() == {
        tag
        for tag, route in FEEDBACK_SIGNAL_ROUTES.items()
        if route.destination in EMITTING_DESTINATIONS
    }
    # Fails CLOSED: a tag nobody declared is not routable, so it lands in the
    # unroutable row rather than silently inflating the conversion denominator.
    assert not is_routable_feedback_tag("a_tag_nobody_declared")


def test_the_refail_join_key_is_the_one_the_aggregator_actually_writes() -> None:
    # The tag lives in `proposer_context` under a key S25 owns. Pinning it against
    # the real builder catches a rename in either direction -- which would
    # otherwise surface as "the re-fail rate silently became 0 fixes".
    evidence = cluster_evidence(
        FeedbackCluster(
            tag="tool_misuse",
            subjects=("auto_handled_record:rec_1",),
            row_ids=("irev_1",),
            first_seen=0.0,
            last_seen=1.0,
        )
    )
    assert evidence[CLUSTER_TAG_EVIDENCE_KEY] == "tool_misuse"


def test_the_watch_window_is_on_the_knob_panel_as_its_constant() -> None:
    values = {knob["key"]: knob["value"] for knob in knob_panel()["knobs"]}
    assert values["POST_FIX_WATCH_WINDOW_SECONDS"] == str(POST_FIX_WATCH_WINDOW_SECONDS)
    assert values["MIN_OBSERVATIONS_FOR_RATE"] == str(MIN_OBSERVATIONS_FOR_RATE)


@pytest.mark.parametrize("key", [LOOP_CONVERSION, LOOP_REFAIL, LOOP_ENTRY_TREND])
def test_every_windowed_row_names_the_knob_that_moves_its_window(key: str) -> None:
    # D16/D14: a window is a deploy-time constant, and the tile points at the
    # panel row an admin would edit rather than restating the number.
    detail = _rows(loop_closure_payload())[key]["detail"]
    assert any(
        knob in detail
        for knob in (
            "CLUSTER_WINDOW_SECONDS",
            "POST_FIX_WATCH_WINDOW_SECONDS",
            "PRUNE_WINDOW_SECONDS",
        )
    ), detail
