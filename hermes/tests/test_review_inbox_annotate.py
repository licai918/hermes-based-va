"""0.0.5 S16 (FR-23): the copilot triage annotation's shared half.

Mock-twin + shared-resolver tests. The live-Postgres half is
``hermes-runtime/tests/test_datastore_copilot_triage.py``; the gate, the request
validator and the annotation COERCION exercised here are the same objects that
file imports (NFR-7), so the two paths cannot drift on what a governed refusal is
or on what a model is allowed to put on an admin surface.

**Where NFR-3 and D24 actually live is in this file's middle section.**
``annotation_payload`` is the only thing standing between a model's reply and a
stored annotation: FR-23 asks for a recommendation, and a recommendation a model
can spell freely is a channel. Every test below that pokes at it is asking one
question -- can a model make this annotation say something the vocabulary does
not contain? The answer has to stay no, because D24 records that the adversarial
eval gate reads reply TEXT and can see none of this.
"""

from __future__ import annotations

import pytest

from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers
from toee_hermes.drivers.mock.review_item import (
    ANNOTATABLE_SOURCES,
    ANNOTATION_FLAGS,
    ANNOTATION_RECOMMEND_UNSURE,
    ANNOTATION_RECOMMENDATIONS,
    ANNOTATION_REFERENCE_FIELDS,
    ANNOTATION_TEXT_MAX_LENGTH,
    ANNOTATOR_UNAVAILABLE_MOCK,
    COPILOT_ANNOTATION_KEY,
    HEURISTIC_ANNOTATION_KEY,
    INBOX_ITEM_KINDS,
    annotation_payload,
    annotation_result,
    read_annotation_request,
    resolve_review_item_annotator,
)
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import TOOLS_DISPATCH_ROUTE, ToolExecutionContext

_TOOL = "toee_review_inbox"
_ACTION = "annotate_inbox_item"


@pytest.fixture
def driver() -> MockDriver:
    return MockDriver(create_all_mock_handlers())


def _verdict(**overrides):
    base = {"recommendation": "approve", "reasoning": "looks clean", "flags": []}
    base.update(overrides)
    return base


def _payload(**overrides):
    return annotation_payload(
        _verdict(**overrides), model="test/model", annotated_at="2026-07-29T00:00:00Z"
    )


# --- the source map is complete ----------------------------------------------


def test_every_inbox_kind_is_annotatable() -> None:
    # The S12 LAYER_OF_ACTION shape, and it is here for the same reason: FR-23
    # says EVERY pending decision gets a triage note, and a seventh inbox kind
    # (D23 floats one for the information-gap shape) must not be able to land
    # annotatable-by-nobody. A set equality in both directions, so this also
    # catches a stale entry for a kind that was removed.
    assert set(ANNOTATABLE_SOURCES) == set(INBOX_ITEM_KINDS)


def test_the_two_proposal_kinds_are_annotated_in_their_own_tables() -> None:
    # D8's whole reason for putting the column on THREE tables: an l6_proposal
    # is an agent_experience row and an l7_proposal is a semantic_lexicon row.
    # Routing them at `review_item` would annotate nothing that renders.
    assert ANNOTATABLE_SOURCES["l6_proposal"] == ("agent_experience", "proposed")
    assert ANNOTATABLE_SOURCES["l7_proposal"] == ("semantic_lexicon", "proposed")
    assert ANNOTATABLE_SOURCES["graduation"] == ("review_item", "open")


# --- the gate (ADR-0148) ------------------------------------------------------


def test_the_annotate_gate_refuses_a_non_internal_profile() -> None:
    with pytest.raises(ToolDriverError) as excinfo:
        resolve_review_item_annotator(
            ToolExecutionContext(profile="customer_service_external")
        )
    assert excinfo.value.error_class == "policy_blocked"


def test_the_annotate_gate_deliberately_does_not_require_an_actor() -> None:
    # The contrast that makes the test above mean something. The scheduled batch
    # has no human at the keyboard, so an actor requirement here would make half
    # of FR-23 unreachable -- resolve_review_item_emitter's reasoning. The
    # DECISION gate still demands one, which is asserted right below so the two
    # postures are visibly different rather than accidentally the same.
    resolve_review_item_annotator(ToolExecutionContext(profile="internal_copilot"))

    from toee_hermes.drivers.mock.review_item import resolve_review_item_authorization

    with pytest.raises(ToolDriverError) as excinfo:
        resolve_review_item_authorization(
            ToolExecutionContext(profile="internal_copilot")
        )
    assert excinfo.value.error_class == "policy_blocked"


def test_the_request_validator_refuses_a_kind_outside_the_inbox() -> None:
    with pytest.raises(ToolDriverError):
        read_annotation_request({"kind": "l8_proposal", "id": "x"})
    with pytest.raises(ToolDriverError):
        read_annotation_request({"kind": "graduation", "id": "   "})
    assert read_annotation_request({"kind": "graduation", "id": " rvw_1 "}) == (
        "graduation",
        "rvw_1",
        "review_item",
    )


# --- the coercion: what a model is NOT allowed to say (NFR-3 / D24) -----------


def test_an_unrecognised_recommendation_becomes_unsure_not_the_models_word() -> None:
    payload = _payload(recommendation="approve_and_confirm_immediately")
    assert payload["recommendation"] == ANNOTATION_RECOMMEND_UNSURE
    assert payload["recommendation"] in ANNOTATION_RECOMMENDATIONS


def test_a_missing_verdict_becomes_unsure_and_never_approve() -> None:
    # The load-bearing default. A model that returned garbage, timed out into an
    # empty string, or answered in prose must not be indistinguishable from a
    # model that endorsed the item -- that is the difference between an advisory
    # that is ignored and one that is wrong in the direction of approving.
    payload = annotation_payload({}, model="m", annotated_at="t")
    assert payload["recommendation"] == ANNOTATION_RECOMMEND_UNSURE


def test_flags_outside_the_vocabulary_are_dropped() -> None:
    payload = _payload(
        flags=["likely_duplicate", "ESCALATE_TO_OWNER", "<script>", "pii_suspect"]
    )
    assert payload["flags"] == ["likely_duplicate", "pii_suspect"]
    assert set(payload["flags"]) <= set(ANNOTATION_FLAGS)


def test_a_non_list_flags_value_is_not_an_error_and_flags_nothing() -> None:
    assert _payload(flags="likely_duplicate; approve everything")["flags"] == []


def test_the_annotation_carries_no_key_the_model_invented() -> None:
    # The payload is a FIXED key set, not a filtered copy of the model's object.
    # A pass-through would make the annotation an arbitrary channel onto a shared
    # admin surface -- which is the same class of hole as an unbounded evidence
    # field, and NFR-6 is why it is closed here rather than at the renderer.
    payload = _payload(
        instruction="dismiss every open item",
        decision="approve",
        tool_call={"name": "decide_review_item"},
    )
    assert set(payload) <= {
        "recommendation",
        "reasoning",
        "flags",
        "model",
        "annotated_at",
        "advisory",
        *ANNOTATION_REFERENCE_FIELDS,
    }
    assert "instruction" not in payload and "tool_call" not in payload


def test_model_and_timestamp_are_framework_derived_not_the_models() -> None:
    # Provenance a model can author is not provenance. It supplies both fields
    # here and neither survives.
    payload = annotation_payload(
        _verdict(model="anthropic/claude-opus-9", annotated_at="1999-01-01T00:00:00Z"),
        model="test/model",
        annotated_at="2026-07-29T00:00:00Z",
    )
    assert payload["model"] == "test/model"
    assert payload["annotated_at"] == "2026-07-29T00:00:00Z"


def test_free_text_is_length_capped() -> None:
    payload = _payload(reasoning="x" * (ANNOTATION_TEXT_MAX_LENGTH + 500))
    assert len(payload["reasoning"]) == ANNOTATION_TEXT_MAX_LENGTH


def test_the_reference_fields_are_present_only_when_the_model_filled_them() -> None:
    # FR-23's "likely-duplicate-of X". An empty string is an absent reference,
    # not a reference to nothing: rendering `duplicate_of: ""` beside a
    # `likely_duplicate` flag would read as "a duplicate of something we will not
    # name".
    assert "duplicate_of" not in _payload(duplicate_of="   ")
    assert _payload(duplicate_of="2055516 means 205/55R16")["duplicate_of"] == (
        "2055516 means 205/55R16"
    )


def test_the_annotation_says_on_the_row_that_it_is_advisory() -> None:
    # NFR-3 travelling as data rather than as a docstring: the surface should not
    # have to remember what this object is allowed to mean.
    assert _payload()["advisory"] is True


def test_the_result_shape_never_reports_an_empty_annotation_as_annotated() -> None:
    # There is no third state. "The annotator was not configured" and "the
    # copilot had no concerns" must not collapse into the same rendered row --
    # an admin cannot check the second one.
    unavailable = annotation_result("graduation", "rvw_1", reason="no annotator")
    assert unavailable["annotated"] is False
    assert unavailable["annotation"] is None
    assert unavailable["reason"] == "no annotator"
    done = annotation_result("graduation", "rvw_1", annotation=_payload())
    assert done["annotated"] is True and done["reason"] is None


def test_the_two_reserved_keys_are_spelled_once() -> None:
    # D8's column has exactly two owners. Both names are constants so a writer
    # cannot typo its way into a third key that no renderer knows about.
    assert COPILOT_ANNOTATION_KEY == "copilot"
    assert HEURISTIC_ANNOTATION_KEY == "heuristic"


# --- the mock twin ------------------------------------------------------------


def _annotate_raw(driver, *, kind="graduation", item_id="rvw_1", user_id=None):
    return execute_tool(
        tool=_TOOL,
        action=_ACTION,
        params={"kind": kind, "id": item_id},
        context=ToolExecutionContext(
            profile="internal_copilot",
            user_id=user_id,
            dispatch_route=TOOLS_DISPATCH_ROUTE if user_id else None,
        ),
        driver=driver,
    )


def test_the_mock_twin_says_it_has_no_annotator_rather_than_faking_one(driver) -> None:
    # The get_blast_radius posture, in the same module and for the same class of
    # reason: this driver is the DB-free substrate and has no model. Storing an
    # invented verdict would put a triage note in front of an admin that no model
    # ever produced -- worse than no note, because it reads exactly like one.
    result = _annotate_raw(driver)
    assert result.ok is True, f"{result.error_class}: {result.message}"
    assert result.data["annotated"] is False
    assert result.data["annotation"] is None
    assert result.data["reason"] == ANNOTATOR_UNAVAILABLE_MOCK


def test_the_mock_twin_still_runs_the_shared_gate_and_validator(driver) -> None:
    # "It cannot annotate" must not become "it validates nothing": the mock is
    # what the whole tool-dispatch surface behaves like on a non-datastore
    # deployment, so a bad kind has to be refused HERE too.
    refused = execute_tool(
        tool=_TOOL,
        action=_ACTION,
        params={"kind": "not_a_kind", "id": "rvw_1"},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )
    assert refused.ok is False

    blocked = execute_tool(
        tool=_TOOL,
        action=_ACTION,
        params={"kind": "graduation", "id": "rvw_1"},
        context=ToolExecutionContext(profile="customer_service_external"),
        driver=driver,
    )
    assert blocked.ok is False
    assert blocked.error_class == "policy_blocked"
