"""0.0.5 S15 (FR-22): the ``review_item`` store against live Postgres.

Live-Postgres half of the mock twin's ``hermes/tests/test_review_item.py``. Every
gate and validator is the SAME shared resolver both handler modules import
(NFR-7), so this file is deliberately narrow: it pins only the things real
Postgres can prove and a mock cannot.

* the partial unique index (``review_item_open_subject_idx``) really is what
  makes a scheduled re-emission a no-op, and really does stop covering an item
  once it has been decided;
* ``UPDATE ... WHERE status = 'open'`` is the idempotency floor, and each
  governed action's audit row lands with the right actor;
* a fail-closed ``policy_blocked`` persists NOTHING -- no status change, no
  audit row;
* Re-classify writes BOTH sides' audit rows plus the row that links them, and
  the whole thing is ONE transaction: a target that collides on
  ``UNIQUE(domain, surface_form)`` rolls the source's rejection back with it.
  That last one is the property the mock structurally cannot have.

Migration 0024 seeds L7 domain #1 into every migrated schema, so the lexicon
assertions here work in a domain the seed does not own.
"""

from __future__ import annotations

import pytest

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import TOOLS_DISPATCH_ROUTE, ToolExecutionContext

_TOOL = "toee_review_inbox"

_TARGET = {
    "domain": "wheel",
    "entry_kind": "alias",
    "surface_form": "2055516",
    "canonical_form": "205/55R16",
}


def _ok(result):
    assert result.ok is True, f"{result.error_class}: {result.message}"
    return result.data


def _err(result):
    assert result.ok is False, f"expected a governed refusal, got {result.data!r}"
    return result


def _emit(driver, **params):
    """A sweep/job emission: internal profile, NO actor -- there is no human."""
    return execute_tool(
        tool=_TOOL,
        action="propose_review_item",
        params=params,
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )


def _admin(driver, action, *, user_id="acct_admin_1", **params):
    return execute_tool(
        tool=_TOOL,
        action=action,
        params=params,
        context=ToolExecutionContext(
            profile="internal_copilot",
            user_id=user_id,
            dispatch_route=TOOLS_DISPATCH_ROUTE,
        ),
        driver=driver,
    )


def _propose_l6(driver, content="reps confirm 2055516 means the tire size"):
    return _ok(
        execute_tool(
            tool="toee_agent_experience",
            action="propose_experience",
            params={"kind": "note", "content": content},
            context=ToolExecutionContext(profile="internal_copilot"),
            driver=driver,
        )
    )


def _rows(conn, sql, args=()):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def _audit(conn, action, target_id=None):
    if target_id is None:
        return _rows(
            conn,
            "SELECT account_id, target_type, target_id, details "
            "FROM workbench_audit_log WHERE action = %s",
            (action,),
        )
    return _rows(
        conn,
        "SELECT account_id, target_type, target_id, details "
        "FROM workbench_audit_log WHERE action = %s AND target_id = %s",
        (action, target_id),
    )


# --- emission + the partial unique index -------------------------------------


def test_an_emission_lands_an_open_row_with_the_annotations_column(datastore) -> None:
    driver, conn, _schema = datastore
    item = _ok(
        _emit(
            driver,
            kind="graduation",
            subject_ref="aexp_seed",
            evidence={"hits": 12, "window_days": 30},
        )
    )

    row = _rows(
        conn,
        "SELECT kind, subject_ref, evidence, annotations, status, "
        "decider_account_id, decided_at FROM review_item WHERE id = %s",
        (item["id"],),
    )
    assert row == [
        (
            "graduation",
            "aexp_seed",
            {"hits": 12, "window_days": 30},
            # D8's column, defaulted -- S16 assigns its own `copilot` key into it.
            {},
            "open",
            None,
            None,
        )
    ]
    assert _audit(conn, "review_item_proposed", item["id"])[0][3] == {
        "kind": "graduation",
        "subject_ref": "aexp_seed",
    }


def test_the_partial_index_makes_a_re_emission_a_no_op(datastore) -> None:
    # The property a scheduled emitter depends on: S20's sweep sees the same
    # still-open subject every cycle. A second row here, or a second audit row,
    # would turn the inbox badge into noise within a day.
    driver, conn, _schema = datastore
    first = _ok(_emit(driver, kind="graduation", subject_ref="aexp_seed"))
    _ok(_emit(driver, kind="graduation", subject_ref="aexp_other"))
    again = _ok(_emit(driver, kind="graduation", subject_ref="aexp_seed"))

    assert again["id"] == first["id"]
    assert again["proposed"] is False
    assert _rows(
        conn, "SELECT count(*) FROM review_item WHERE subject_ref = %s", ("aexp_seed",)
    ) == [(1,)]
    assert len(_audit(conn, "review_item_proposed", first["id"])) == 1


def test_the_index_stops_covering_an_item_once_it_is_decided(datastore) -> None:
    # PARTIAL on purpose: a subject that becomes a candidate again after an admin
    # dealt with it is new news, not a duplicate. A total UNIQUE would suppress
    # it forever, and this test is what tells the two designs apart.
    driver, conn, _schema = datastore
    first = _ok(_emit(driver, kind="graduation", subject_ref="aexp_seed"))
    _ok(_admin(driver, "decide_review_item", id=first["id"], decision="dismissed"))
    second = _ok(_emit(driver, kind="graduation", subject_ref="aexp_seed"))

    assert second["id"] != first["id"]
    assert sorted(
        r[0]
        for r in _rows(
            conn,
            "SELECT status FROM review_item WHERE subject_ref = %s",
            ("aexp_seed",),
        )
    ) == ["dismissed", "open"]


# --- deciding ----------------------------------------------------------------


def test_a_decision_stamps_the_decider_and_writes_its_audit_row(datastore) -> None:
    driver, conn, _schema = datastore
    item = _ok(_emit(driver, kind="blast_radius", subject_ref="mem_9"))
    decided = _ok(
        _admin(driver, "decide_review_item", id=item["id"], decision="acknowledged")
    )

    assert decided["status"] == "acknowledged"
    assert _rows(
        conn,
        "SELECT status, decider_account_id, decided_at IS NOT NULL "
        "FROM review_item WHERE id = %s",
        (item["id"],),
    ) == [("acknowledged", "acct_admin_1", True)]
    assert _audit(conn, "review_item_acknowledged", item["id"]) == [
        ("acct_admin_1", "review_item", item["id"], {"status": "acknowledged"})
    ]


def test_a_redelivered_decision_writes_no_second_audit_row(datastore) -> None:
    driver, conn, _schema = datastore
    item = _ok(_emit(driver, kind="blast_radius", subject_ref="mem_9"))
    _ok(_admin(driver, "decide_review_item", id=item["id"], decision="dismissed"))
    again = _ok(
        _admin(
            driver,
            "decide_review_item",
            user_id="acct_admin_2",
            id=item["id"],
            decision="acknowledged",
        )
    )

    assert again["status"] == "dismissed"
    assert again["decider_account_id"] == "acct_admin_1"
    assert _audit(conn, "review_item_acknowledged", item["id"]) == []


def test_a_decision_without_an_actor_persists_nothing(datastore) -> None:
    # ADR-0148 / D20: fail-closed, never a silent write with a null decider.
    driver, conn, _schema = datastore
    item = _ok(_emit(driver, kind="graduation", subject_ref="aexp_seed"))
    failure = _err(
        _admin(
            driver,
            "decide_review_item",
            user_id=None,
            id=item["id"],
            decision="dismissed",
        )
    )

    assert failure.error_class == "policy_blocked"
    assert _rows(
        conn,
        "SELECT status, decider_account_id FROM review_item WHERE id = %s",
        (item["id"],),
    ) == [("open", None)]
    assert _audit(conn, "review_item_dismissed", item["id"]) == []


# --- Re-classify -------------------------------------------------------------


def test_reclassify_moves_the_proposal_and_writes_both_sides_audit_rows(
    datastore,
) -> None:
    driver, conn, _schema = datastore
    proposal = _propose_l6(driver)
    result = _ok(
        _admin(
            driver,
            "reclassify_proposal",
            source_kind="l6_proposal",
            id=proposal["id"],
            **_TARGET,
        )
    )
    target_id = result["target"]["id"]

    # Source rejected, in its own table, by its own governed action.
    assert _rows(
        conn,
        "SELECT status, decider_account_id FROM agent_experience WHERE id = %s",
        (proposal["id"],),
    ) == [("rejected", "acct_admin_1")]
    # Target proposed, with the L6 content preserved as its evidence and
    # admin_manual provenance derived from the dispatch route (never a param).
    assert _rows(
        conn,
        "SELECT status, provenance, surface_form, evidence "
        "FROM semantic_lexicon WHERE id = %s",
        (target_id,),
    ) == [
        (
            "proposed",
            "admin_manual",
            "2055516",
            "Re-classified from an L6 proposal: " + proposal["content"],
        )
    ]

    # BOTH sides audited, each by its own layer, plus the ONE row that links the
    # two ids (they are deliberately absent from the PII-scanned lexicon fields).
    assert _audit(conn, "agent_experience_rejected", proposal["id"])[0][0] == (
        "acct_admin_1"
    )
    assert _audit(conn, "lexicon_entry_proposed", target_id)[0][0] == "acct_admin_1"
    assert _audit(conn, "review_item_reclassified", proposal["id"]) == [
        (
            "acct_admin_1",
            "agent_experience",
            proposal["id"],
            {
                "from": {"kind": "l6_proposal", "id": proposal["id"]},
                "to": {"kind": "l7_proposal", "id": target_id},
            },
        )
    ]


def test_a_colliding_target_rolls_the_source_rejection_back_with_it(
    datastore,
) -> None:
    # The property the mock structurally cannot have: both writes ride the single
    # transaction PostgresDriver.execute opens, so a UNIQUE(domain, surface_form)
    # collision leaves the source proposal still pending rather than rejected
    # with nothing to show for it.
    driver, conn, _schema = datastore
    _ok(
        execute_tool(
            tool="toee_semantic_lexicon",
            action="propose_lexicon_entry",
            params=_TARGET,
            context=ToolExecutionContext(profile="internal_copilot"),
            driver=driver,
        )
    )
    proposal = _propose_l6(driver)

    failure = _err(
        _admin(
            driver,
            "reclassify_proposal",
            source_kind="l6_proposal",
            id=proposal["id"],
            **_TARGET,
        )
    )
    assert failure.error_class == "conflict"
    assert _rows(
        conn, "SELECT status FROM agent_experience WHERE id = %s", (proposal["id"],)
    ) == [("proposed",)]
    assert _audit(conn, "agent_experience_rejected", proposal["id"]) == []


def test_reclassify_without_an_actor_persists_neither_side(datastore) -> None:
    driver, conn, _schema = datastore
    proposal = _propose_l6(driver)
    failure = _err(
        _admin(
            driver,
            "reclassify_proposal",
            user_id=None,
            source_kind="l6_proposal",
            id=proposal["id"],
            **_TARGET,
        )
    )

    assert failure.error_class == "policy_blocked"
    assert _rows(
        conn, "SELECT status FROM agent_experience WHERE id = %s", (proposal["id"],)
    ) == [("proposed",)]
    assert _rows(
        conn,
        "SELECT count(*) FROM semantic_lexicon WHERE domain = %s",
        (_TARGET["domain"],),
    ) == [(0,)]


def test_reclassify_refuses_an_already_decided_source(datastore) -> None:
    driver, conn, _schema = datastore
    proposal = _propose_l6(driver)
    _ok(
        execute_tool(
            tool="toee_agent_experience",
            action="reject_experience",
            params={"id": proposal["id"]},
            context=ToolExecutionContext(
                profile="internal_copilot", user_id="acct_admin_1"
            ),
            driver=driver,
        )
    )
    failure = _err(
        _admin(
            driver,
            "reclassify_proposal",
            source_kind="l6_proposal",
            id=proposal["id"],
            **_TARGET,
        )
    )

    assert failure.error_class == "conflict"
    assert _rows(
        conn,
        "SELECT count(*) FROM semantic_lexicon WHERE domain = %s",
        (_TARGET["domain"],),
    ) == [(0,)]
