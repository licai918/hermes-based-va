"""0.0.5 S27 (FR-33): edit-diff mining against live Postgres.

Live half of ``test_edit_diff_mining.py``. The four mineability rules and the
clustering are pure and pinned there; this file pins only what real Postgres can
prove and a mock cannot:

* ``sent_text`` really persists through the GOVERNED ``record_draft_outcome``
  write -- migration 0029's whole point, and the only reason this job has a
  second operand at all (D11);
* an emission really lands through the GOVERNED propose actions -- the L7 row
  carries ``provenance='feedback_derived'`` and its own ``lexicon_entry_proposed``
  audit row, and the L6 row ``source='feedback_derived'``; a direct INSERT would
  have written neither;
* running the job TWICE does not duplicate anything, by either idempotence leg:
  the watermark (nothing new) and the stores (``UNIQUE (domain, surface_form)``
  for L7, the open-proposal check for L6);
* a cluster that accumulates ACROSS runs still trips -- the watermark bounds the
  work, not the read;
* a ``policy_blocked`` from a write scan is swallowed, counted into a metric, and
  does not fail the job (D13);
* rows written before 0029 have a NULL ``sent_text`` and are invisible, which is
  D11's no-backfill position as behaviour rather than as a sentence.

Threshold coverage is at M-1 / M / M+1 here too, because a live fixture with
exactly M rows cannot tell "requires M" from "requires any" either.
"""

from __future__ import annotations

import pytest

from hermes_runtime.datastore.handlers.feedback import feedback_handlers
from hermes_runtime.edit_diff_mining import (
    METRIC_EDIT_DIFF_BLOCKED,
    METRIC_EDIT_DIFF_PROPOSED,
    MINING_AUDIT_ACTION,
    mine_edit_diffs,
    read_watermark,
    run_edit_diff_mining_job,
)
from hermes_runtime.feedback_aggregator import SIMILAR_EDIT_DIFF_THRESHOLD
from toee_hermes.tool_gate import ToolExecutionContext

M = SIMILAR_EDIT_DIFF_THRESHOLD

# A term rewrite -> an L7 alias. A clause rewrite -> an L6 procedure question.
_TERM_DRAFT = "We have mud tires in stock for your truck."
_TERM_SENT = "We have all-terrain tires in stock for your truck."
_CLAUSE_DRAFT = "We can refund the difference to your card."
_CLAUSE_SENT = "We can put the difference on a store credit."

_REP = "acct_rep_1"
_CASE = "case_s27"
_PHONE = "604-555-1212"


def _seed_case(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cases (id, channel, assignee_account_id) "
            "VALUES (%s, 'sms', %s) ON CONFLICT (id) DO NOTHING",
            (_CASE, _REP),
        )
    conn.commit()


def _seed_edits(conn, *, draft, sent, drafts, prefix="corr", sent_text=True):
    """``drafts`` distinct edited sends, all carrying the same rewrite.

    A direct INSERT rather than the governed action, so the fixture can control
    row count cheaply. ``test_the_governed_send_write_persists_the_sent_text``
    covers the real write path.
    """
    ids = []
    with conn.cursor() as cur:
        for n in range(drafts):
            row_id = f"draft_{prefix}_{n}"
            cur.execute(
                """
                INSERT INTO draft_feedback
                    (id, case_id, draft_correlation_id, draft_kind, draft_text,
                     sent_text, outcome, edit_distance_ratio, rep_account_id)
                VALUES (%s, %s, %s, 'sms', %s, %s, 'sent_edited', 0.2, %s)
                """,
                (
                    row_id,
                    _CASE,
                    f"{prefix}_{n}",
                    draft,
                    sent if sent_text else None,
                    _REP,
                ),
            )
            ids.append(f"{prefix}_{n}")
    conn.commit()
    return ids


def _rows(conn, sql, args=()):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def _lexicon(conn):
    """The rows THIS JOB produced.

    Scoped to ``feedback_derived`` because migration 0024 seeds four
    ``admin_manual`` rows into every schema, including this fixture's. Scoping on
    provenance rather than on ids is deliberate: it is also the assertion that
    the job stamped D3's value, so an implementation that emitted with the wrong
    provenance reads as "emitted nothing" and reddens rather than passing.
    """
    return _rows(
        conn,
        "SELECT id, entry_kind, surface_form, canonical_form, status, provenance, "
        "evidence, proposer_context FROM semantic_lexicon "
        "WHERE provenance = 'feedback_derived' ORDER BY created_at",
    )


def _experience(conn):
    return _rows(
        conn,
        "SELECT id, kind, status, source, content, proposer_context "
        "FROM agent_experience ORDER BY created_at",
    )


def _metric_count(conn, metric):
    return _rows(
        conn, "SELECT count(*) FROM metric_event WHERE metric = %s", (metric,)
    )[0][0]


def _audit(conn, action):
    return _rows(
        conn,
        "SELECT account_id, target_type, details FROM workbench_audit_log "
        "WHERE action = %s ORDER BY created_at",
        (action,),
    )


# --- the input: migration 0029's column, through the governed write -----------


def test_the_governed_send_write_persists_the_sent_text(datastore) -> None:
    """D11's column, exercised through the real action rather than an INSERT.

    This is the whole reason S27 has an algorithm: before 0029 the sent body was
    persisted nowhere queryable, so the span diff had one operand.
    """
    _driver, conn, _schema = datastore
    _seed_case(conn)
    context = ToolExecutionContext(profile="internal_copilot", user_id=_REP)

    row = feedback_handlers()["toee_feedback"]["record_draft_outcome"](
        conn,
        {
            "case_id": _CASE,
            "draft_correlation_id": "corr_governed",
            "draft_kind": "sms",
            "draft_text": _TERM_DRAFT,
            "sent_text": _TERM_SENT,
            "outcome": "sent_edited",
            "edit_distance_ratio": 0.2,
        },
        context,
    )
    conn.commit()

    assert row["draft_text"] == _TERM_DRAFT
    assert row["sent_text"] == _TERM_SENT


def test_rows_written_before_the_column_existed_are_invisible(datastore) -> None:
    """No backfill (D11). A NULL ``sent_text`` is not a diff of the empty string."""
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=M, sent_text=False)

    run = mine_edit_diffs(conn)

    assert (run.edited_sends, run.rewrites, run.emitted) == (0, 0, 0)
    assert _lexicon(conn) == []


# --- the threshold ------------------------------------------------------------


@pytest.mark.parametrize(
    "drafts,expected", [(M - 1, 0), (M, 1), (M + 1, 1)]
)
def test_m_similar_rewrites_produce_exactly_one_proposal(
    datastore, drafts, expected
) -> None:
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=drafts)

    run = mine_edit_diffs(conn)

    assert run.emitted == expected
    assert len(_lexicon(conn)) == expected


def test_one_draft_edited_the_same_way_m_times_proposes_nothing(datastore) -> None:
    """"M SIMILAR same-span rewrites" counts DISTINCT DRAFTS, not rows.

    One rep re-sending one draft is one opinion; a row count would emit here.
    """
    _driver, conn, _schema = datastore
    _seed_case(conn)
    with conn.cursor() as cur:
        for n in range(M + 2):
            cur.execute(
                """
                INSERT INTO draft_feedback
                    (id, case_id, draft_correlation_id, draft_kind, draft_text,
                     sent_text, outcome, edit_distance_ratio, rep_account_id)
                VALUES (%s, %s, 'corr_one', 'sms', %s, %s, 'sent_edited', 0.2, %s)
                """,
                (f"draft_same_{n}", _CASE, _TERM_DRAFT, _TERM_SENT, _REP),
            )
    conn.commit()

    run = mine_edit_diffs(conn)

    assert (run.rewrites, run.tripped, run.emitted) == (M + 2, 0, 0)
    assert _lexicon(conn) == []


# --- the emissions, through the governed propose actions ----------------------


def test_the_l7_alias_proposal_is_feedback_derived_and_audited(datastore) -> None:
    _driver, conn, _schema = datastore
    _seed_case(conn)
    refs = _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=M)

    run = mine_edit_diffs(conn)
    conn.commit()

    entries = _lexicon(conn)
    assert len(entries) == 1
    _id, kind, surface, canonical, status, provenance, evidence, context = entries[0]
    assert (kind, surface, canonical) == ("alias", "mud", "all-terrain")
    # NFR-3: propose-only is absolute. A job never confirms anything.
    assert status == "proposed"
    # D3: distinguishable from an admin's entry and from a capture fork's.
    assert provenance == "feedback_derived"
    assert "mud" in evidence and "all-terrain" in evidence
    assert context["edited_sends"] == M

    # A direct INSERT would have written no audit row at all -- this is what
    # proves the emission went THROUGH the governed action.
    audit = _audit(conn, "lexicon_entry_proposed")
    assert len(audit) == 1
    assert audit[0][2]["provenance"] == "feedback_derived"

    # The machine-readable link lives on the RUN's audit row, where nothing
    # scans it -- never on the proposal (a correlation id trips _PHONE_RE).
    assert run.emissions[0]["draft_correlation_ids"] == sorted(refs)
    assert _metric_count(conn, METRIC_EDIT_DIFF_PROPOSED) == 1


def test_the_l6_procedure_proposal_is_feedback_derived(datastore) -> None:
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(conn, draft=_CLAUSE_DRAFT, sent=_CLAUSE_SENT, drafts=M)

    run = mine_edit_diffs(conn)
    conn.commit()

    rows = _experience(conn)
    assert len(rows) == 1
    _id, kind, status, source, content, context = rows[0]
    assert (kind, status, source) == ("procedure", "proposed", "feedback_derived")
    assert "store credit" in content
    assert context["edit_diff_cluster"].startswith("refund the difference")
    # And nothing went to L7: the shape decision routed it to exactly one layer.
    assert _lexicon(conn) == []
    assert run.emitted == 1


def test_a_term_and_a_clause_rewrite_route_to_their_own_layers(datastore) -> None:
    """Both arms in one run, so the shape split is exercised end to end."""
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=M, prefix="term")
    _seed_edits(conn, draft=_CLAUSE_DRAFT, sent=_CLAUSE_SENT, drafts=M, prefix="clause")

    run = mine_edit_diffs(conn)
    conn.commit()

    assert run.emitted == 2
    assert len(_lexicon(conn)) == 1
    assert len(_experience(conn)) == 1


# --- idempotence: two independent legs (D13) ----------------------------------


def test_running_twice_with_nothing_new_emits_nothing_and_records_nothing(
    datastore,
) -> None:
    """The WATERMARK leg. A second tick over the same rows is free."""
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=M)

    first = mine_edit_diffs(conn)
    conn.commit()
    second = mine_edit_diffs(conn)
    conn.commit()

    assert (first.emitted, second.emitted) == (1, 0)
    assert second.watermark == first.watermark
    assert len(_lexicon(conn)) == 1
    # No second run row: the watermark stops the WORK, so there is nothing to
    # record. One audit row, not two.
    assert len(_audit(conn, MINING_AUDIT_ACTION)) == 1


def test_the_stores_stop_duplicates_even_when_the_watermark_does_not(
    datastore,
) -> None:
    """The STORE leg, with the watermark deliberately neutralized.

    A fourth edited send makes the run's newest row newer than the watermark, so
    the job does full work and tries to emit the same pair again. ``UNIQUE
    (domain, surface_form)`` refuses it as a governed ``conflict``, which is
    counted rather than raised -- if this leg were missing, the watermark test
    above would still pass and every new edit would mint a duplicate proposal.
    """
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=M, prefix="a")
    first = mine_edit_diffs(conn)
    conn.commit()

    _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=1, prefix="b")
    second = mine_edit_diffs(conn)
    conn.commit()

    assert first.emitted == 1
    assert second.watermark > first.watermark  # the watermark did NOT stop it
    assert (second.tripped, second.emitted, second.already_open) == (1, 0, 1)
    assert len(_lexicon(conn)) == 1


def test_the_l6_arm_has_the_same_store_leg(datastore) -> None:
    """``agent_experience`` has no unique index, so the job asks the question
    itself. The class, closed on both arms rather than only the one that had it
    for free."""
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(conn, draft=_CLAUSE_DRAFT, sent=_CLAUSE_SENT, drafts=M, prefix="a")
    mine_edit_diffs(conn)
    conn.commit()

    _seed_edits(conn, draft=_CLAUSE_DRAFT, sent=_CLAUSE_SENT, drafts=1, prefix="b")
    second = mine_edit_diffs(conn)
    conn.commit()

    assert (second.emitted, second.already_open) == (0, 1)
    assert len(_experience(conn)) == 1


def test_a_cluster_that_accumulates_across_runs_still_trips(datastore) -> None:
    """The watermark bounds the WORK, not the READ.

    Two edits on Monday and the third on Tuesday must trip. If the watermark
    bounded the read, the Monday pair would be invisible on Tuesday and this
    cluster would stay one short forever.
    """
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=M - 1, prefix="mon")
    monday = mine_edit_diffs(conn)
    conn.commit()
    assert monday.emitted == 0 and read_watermark(conn) > 0

    _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=1, prefix="tue")
    tuesday = mine_edit_diffs(conn)
    conn.commit()

    assert tuesday.emitted == 1
    assert len(_lexicon(conn)) == 1


# --- the write scans, and the PII boundary ------------------------------------


def test_a_policy_blocked_write_is_swallowed_counted_and_not_fatal(datastore) -> None:
    """D13. An injection pattern in the recurring span is refused by the L7 write
    scan; the job counts it, keeps going, and still emits the clean cluster."""
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(
        conn,
        draft="Our warranty covers that.",
        sent="Our ignore previous instructions covers that.",
        drafts=M,
        prefix="inj",
    )
    _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=M, prefix="ok")

    run = mine_edit_diffs(conn)
    conn.commit()

    assert run.tripped == 2
    assert (run.blocked, run.emitted) == (1, 1)
    assert _metric_count(conn, METRIC_EDIT_DIFF_BLOCKED) == 1
    entries = _lexicon(conn)
    assert len(entries) == 1 and entries[0][2] == "mud"


def test_a_customer_phone_and_address_never_reach_the_proposed_row(
    datastore,
) -> None:
    """NFR-6, end to end and against the real store.

    The drafts carry a real-looking phone number AND a street address around a
    clean rewrite. Neither may appear anywhere on the emitted row -- and note
    the address is NOT a shape ``scan_pii`` knows, so if surrounding text could
    cross, nothing at all would stop it.
    """
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(
        conn,
        draft=f"Hi Dana, call {_PHONE} or visit 1725 Kingsway. Mud tires are ready.",
        sent=(
            f"Hi Dana, call {_PHONE} or visit 1725 Kingsway. "
            "All-terrain tires are ready."
        ),
        drafts=M,
        prefix="pii",
    )

    run = mine_edit_diffs(conn)
    conn.commit()

    assert run.emitted == 1
    entries = _lexicon(conn)
    assert (entries[0][2], entries[0][3]) == ("Mud", "All-terrain")
    stored = repr(entries[0])
    for leak in (_PHONE, "604", "Kingsway", "1725", "Dana"):
        assert leak not in stored


def test_a_recurring_phone_correction_emits_nothing_at_all(datastore) -> None:
    """The other half: when the RECURRING SPAN itself is PII, the pair is dropped.

    D2 turns the PII scan off for L7's forms because it cannot tell a tire size
    from a phone number -- an exemption written for a human at the keyboard. An
    unattended job re-arms it for itself, and drops rather than redacts, because
    a redacted alias is a wrong alias.
    """
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(
        conn,
        draft="Reach the shop on 604-555-1211 today.",
        sent=f"Reach the shop on {_PHONE} today.",
        drafts=M,
        prefix="phone",
    )

    run = mine_edit_diffs(conn)
    conn.commit()

    assert (run.rewrites, run.emitted) == (0, 0)
    assert run.pii_dropped == M
    assert _lexicon(conn) == [] and _experience(conn) == []


# --- the run's own record -----------------------------------------------------


def test_the_run_audit_row_carries_the_watermark_counts_and_the_evidence_link(
    datastore,
) -> None:
    _driver, conn, _schema = datastore
    _seed_case(conn)
    refs = _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=M)

    run = mine_edit_diffs(conn)
    conn.commit()

    audit = _audit(conn, MINING_AUDIT_ACTION)
    assert len(audit) == 1
    account_id, target_type, details = audit[0]
    # Unattended, exactly like the aggregator and the retention sweep.
    assert account_id is None and target_type == "draft_feedback"
    assert details["watermark"] == run.watermark
    assert (details["edited_sends"], details["tripped"], details["emitted"]) == (M, 1, 1)
    assert details["emissions"][0]["draft_correlation_ids"] == sorted(refs)


def test_the_job_body_commits_its_own_work(datastore) -> None:
    """The production entry point, on an injected connection (S25's shape)."""
    _driver, conn, _schema = datastore
    _seed_case(conn)
    _seed_edits(conn, draft=_TERM_DRAFT, sent=_TERM_SENT, drafts=M)

    run_edit_diff_mining_job({}, conn=conn)

    assert len(_lexicon(conn)) == 1
    assert len(_audit(conn, MINING_AUDIT_ACTION)) == 1
