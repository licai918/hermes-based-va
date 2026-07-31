"""0.0.5 S10 (FR-12): the blast-radius vocabulary both twins share.

Mock-twin + shared-resolver half. The live-Postgres half -- the ledger join, the
emission hook on the decide paths, and D21's one-time L4 re-scan -- is
``hermes-runtime/tests/test_datastore_blast_radius.py``.

What is worth pinning HERE is exactly what a Postgres test cannot see: that the
answer's SHAPE is the same object on both sides, that "the mock has no ledger"
does not render as "nothing touched this entry", and that the evidence stays out
of the way of S15's PII redaction.
"""

from __future__ import annotations

import pytest

from toee_hermes.blast_radius import (
    BLAST_RADIUS_KIND,
    LEDGER_LAYERS,
    OPEN_CASE_STATUSES,
    REASON_ENTRY_RETIRED,
    REASON_UNSCANNED_INJECTION,
    blast_radius_evidence,
    blast_radius_result,
    blast_radius_subject_ref,
    parse_since,
    read_blast_radius_query,
    unscanned_subject_ref,
)
from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers
from toee_hermes.drivers.mock.review_item import (
    REVIEW_ITEM_KINDS,
    read_review_item_emission,
)
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import TOOLS_DISPATCH_ROUTE, ToolExecutionContext

_TOOL = "toee_review_inbox"


@pytest.fixture
def driver() -> MockDriver:
    return MockDriver(create_all_mock_handlers())


def _admin_raw(driver, action, *, user_id="acct_admin_1", **params):
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


def _admin(driver, action, **params):
    result = _admin_raw(driver, action, **params)
    assert result.ok is True, f"{result.error_class}: {result.message}"
    return result.data


# --- the kind is D9's, not a seventh one -----------------------------------


def test_the_emitted_kind_is_one_of_d9s_six() -> None:
    # D9 pins the review_item kind enum. S10 emits into an EXISTING value rather
    # than inventing a seventh, which would be a D9 amendment (D23 records the
    # same tension from S25).
    assert BLAST_RADIUS_KIND in REVIEW_ITEM_KINDS


# --- the query validator ----------------------------------------------------


@pytest.mark.parametrize("layer", ["L4", "l5", "", None, "l4 "])
def test_the_query_refuses_a_layer_the_ledger_cannot_hold(layer) -> None:
    # Not defaulted: the same entry_ref under the wrong layer joins to nothing
    # and reads as "this entry touched no cases" -- the one wrong answer this
    # action must never give. Note "L4" (upper) is memory_layers.py's vocabulary,
    # not the ledger's, and is refused rather than quietly coerced.
    with pytest.raises(ToolDriverError) as excinfo:
        read_blast_radius_query({"layer": layer, "entry_ref": "lex_1"})
    assert excinfo.value.error_class == "unexpected_error"


@pytest.mark.parametrize("entry_ref", ["", "   ", None, 7])
def test_the_query_refuses_a_missing_entry_ref(entry_ref) -> None:
    with pytest.raises(ToolDriverError):
        read_blast_radius_query({"layer": "l7", "entry_ref": entry_ref})


def test_the_query_accepts_every_layer_the_ledger_can_hold() -> None:
    for layer in LEDGER_LAYERS:
        assert read_blast_radius_query({"layer": layer, "entry_ref": " x "}) == (
            layer,
            "x",
            None,
        )


def test_a_malformed_since_is_refused_rather_than_widened_to_all_time() -> None:
    # A console that sent a bad string would otherwise get the ALL-TIME blast
    # radius back under a window's label -- over-reporting the very number an
    # admin is about to act on.
    with pytest.raises(ToolDriverError):
        parse_since("last tuesday")
    with pytest.raises(ToolDriverError):
        parse_since("")


def test_since_accepts_the_z_suffix_and_lands_in_utc() -> None:
    parsed = parse_since("2026-07-01T00:00:00Z")
    assert parsed is not None
    assert parsed.utcoffset().total_seconds() == 0
    naive = parse_since("2026-07-01T00:00:00")
    assert naive is not None and naive.utcoffset().total_seconds() == 0


# --- the result shape: open vs closed --------------------------------------


def test_the_result_splits_open_cases_from_closed_ones() -> None:
    # A SELECTION assertion, so the fixture carries a case the split must
    # EXCLUDE: 'resolved' is reported in `cases` (FR-12 samples closed ones by
    # judgment) and absent from `open_cases` (which is what the item counts).
    result = blast_radius_result(
        [
            {"id": "case_open", "status": "open", "turn_count": 2},
            {"id": "case_wip", "status": "in_progress", "turn_count": 1},
            {"id": "case_done", "status": "resolved", "turn_count": 5},
        ],
        layer="l7",
        entry_ref="lex_1",
    )
    assert [c["id"] for c in result["open_cases"]] == ["case_open", "case_wip"]
    assert [c["id"] for c in result["cases"]] == ["case_open", "case_wip", "case_done"]
    assert result["open_case_count"] == 2
    assert result["case_count"] == 3
    # Turns are counted over EVERY case, open or not: it is the entry's usage,
    # not the review queue's size.
    assert result["turn_count"] == 8


def test_resolved_is_not_in_the_open_set() -> None:
    # The constant, not just its consequence -- so widening OPEN_CASE_STATUSES to
    # include 'resolved' cannot pass by the test above's fixture happening to
    # order things conveniently.
    assert "resolved" not in OPEN_CASE_STATUSES
    assert set(OPEN_CASE_STATUSES) == {"open", "in_progress"}


# --- the two subject_ref namespaces ----------------------------------------


def test_a_cleared_slot_and_a_rescan_hit_are_two_items_not_one() -> None:
    # Emission is idempotent on (kind, subject_ref) over the OPEN set, so sharing
    # a namespace would collapse these two into one item and silently swallow
    # whichever arrived second -- along with its reason.
    entry_ref = "provisional:sms:+14165550199:contact_time"
    assert blast_radius_subject_ref("l4", entry_ref) != unscanned_subject_ref(entry_ref)


def test_the_subject_ref_carries_both_ledger_coordinates() -> None:
    # An item has to be takeable straight back to get_blast_radius, and entry_ref
    # alone is half of the ledger's index.
    assert blast_radius_subject_ref("l7", "lex_1") == "l7:lex_1"


# --- the evidence -----------------------------------------------------------


def test_the_evidence_survives_the_write_scan_that_would_mangle_a_case_id() -> None:
    # The reason the case ids are NOT in the evidence, pinned rather than
    # asserted in prose. review_item.evidence is PII-redacted on the way in and
    # _PHONE_RE matches any run of 8+ digits, which a case_<32 hex> id hits
    # roughly two times in five.
    digit_heavy_case_id = "case_12345678abcdef"
    result = blast_radius_result(
        [{"id": digit_heavy_case_id, "status": "open", "turn_count": 1}],
        layer="l7",
        entry_ref="lex_1",
    )
    evidence = blast_radius_evidence(result, reason=REASON_ENTRY_RETIRED)

    # 1. What we DO send survives the emission byte-for-byte.
    stored = read_review_item_emission(
        {
            "kind": BLAST_RADIUS_KIND,
            "subject_ref": blast_radius_subject_ref("l7", "lex_1"),
            "evidence": evidence,
        }
    )
    assert stored["evidence"] == evidence
    assert stored["kind"] == BLAST_RADIUS_KIND

    # 2. What we deliberately do NOT send would have been mangled into a broken
    #    link. This is the whole argument for counts-plus-coordinates.
    mangled = read_review_item_emission(
        {
            "kind": BLAST_RADIUS_KIND,
            "subject_ref": "l7:lex_1",
            "evidence": {"open_case_ids": [digit_heavy_case_id]},
        }
    )
    assert mangled["evidence"]["open_case_ids"] != [digit_heavy_case_id]
    assert "[redacted]" in mangled["evidence"]["open_case_ids"][0]


def test_the_evidence_refuses_an_unknown_reason() -> None:
    result = blast_radius_result([], layer="l4", entry_ref="k:contact_time")
    with pytest.raises(ToolDriverError):
        blast_radius_evidence(result, reason="because_i_said_so")
    # ...and accepts D21's, which is the one a later reader is most likely to
    # assume was never wired up.
    assert (
        blast_radius_evidence(result, reason=REASON_UNSCANNED_INJECTION)["reason"]
        == REASON_UNSCANNED_INJECTION
    )


# --- the mock twin ----------------------------------------------------------


def test_the_mock_says_it_has_no_ledger_rather_than_no_affected_cases(driver) -> None:
    # The mock driver has no injection_ledger at all, so it CANNOT answer this
    # question -- and "I cannot answer" must not render as "nothing touched it".
    data = _admin(driver, "get_blast_radius", layer="l7", entry_ref="lex_1")
    assert data["ledger_available"] is False
    assert data["cases"] == [] and data["open_cases"] == []
    assert data["layer"] == "l7" and data["entry_ref"] == "lex_1"


def test_the_mock_runs_the_same_validator_as_the_postgres_twin(driver) -> None:
    # NFR-7: one resolver. A bad layer is refused by the mock for the same reason
    # and with the same error class the live path uses.
    result = _admin_raw(driver, "get_blast_radius", layer="l9", entry_ref="lex_1")
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_the_mock_and_the_shared_builder_return_the_same_keys(driver) -> None:
    # The twins' drift guard: whatever the shape gains, both sides gain.
    data = _admin(driver, "get_blast_radius", layer="l6", entry_ref="aexp_1")
    assert set(data) == set(
        blast_radius_result([], layer="l6", entry_ref="aexp_1", ledger_available=False)
    )
