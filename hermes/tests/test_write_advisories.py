"""Write-time advisories on a memory proposal (0.0.5 S13, FR-18).

The PURE half -- the one resolver both twins call (NFR-7) -- plus the two mock
propose handlers that call it.

Two properties this file exists to pin, because both are the kind that read as
covered while being vacuous:

* **Selection is tested from both sides.** Every dedup fixture carries a
  near-miss the advisory must NOT fire on beside the genuine duplicate it must.
  A fixture whose every row matches cannot tell "compares" from "returns
  everything" (the S05 one-product-fixture lesson).
* **The comparison never leaves the two SHARED layers.** L4 is per-customer PII
  by design (NFR-6); an advisory that surfaced "this looks like something in
  customer X's memory" onto a shared-layer proposal row would have moved that
  customer's data across the boundary the architecture is built on. The resolver
  takes exactly two row sets and has no seam for a third.
"""

from __future__ import annotations

import pytest

from toee_hermes.drivers.mock.agent_experience import (
    create_agent_experience_mock_handlers,
)
from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.semantic_lexicon import (
    create_semantic_lexicon_mock_handlers,
)
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import TOOLS_DISPATCH_ROUTE, ToolExecutionContext
from toee_hermes.write_advisories import (
    ADVISORY_DUPLICATE_L7_SURFACE,
    ADVISORY_REFILE_TO_L7,
    ADVISORY_SIMILAR_L6_NOTE,
    ANNOTATION_KEY_HEURISTIC,
    SIMILAR_NOTE_MIN_SIMILARITY,
    l6_write_advisories,
    l7_write_advisories,
    note_similarity,
)

# --- fixtures the comparison must tell apart ---------------------------------
#
# The similarity numbers below are MEASURED, not assumed (see the constant's own
# comment). They are stated here so a threshold change makes this file's intent
# fail loudly rather than silently reclassifying a near-miss as a duplicate.

NOTE = "Always confirm the vehicle year before quoting a winter set."
# Same instruction, different words -- what a second reviewer actually writes.
NOTE_DUPLICATE = "Always confirm the vehicle year before quoting winter sets"
# Same TEMPLATE, different subject. This is the case that must stay quiet: it is
# the shape a real L6 store fills up with, and an advisory that fires on it is
# noise, and noise gets turned off.
NOTE_NEAR_MISS = "Always confirm the delivery address before quoting a winter set."
NOTE_UNRELATED = "When a customer asks about warranty, link the manufacturer page first."


def _codes(annotations) -> list[str]:
    block = annotations.get(ANNOTATION_KEY_HEURISTIC)
    return [] if block is None else [a["code"] for a in block["advisories"]]


def _advisory(annotations, code) -> dict:
    block = annotations[ANNOTATION_KEY_HEURISTIC]
    return next(a for a in block["advisories"] if a["code"] == code)


def _l7(entry_id, surface, canonical="x", *, status="confirmed", domain="tire"):
    return {
        "id": entry_id,
        "domain": domain,
        "entry_kind": "alias",
        "surface_form": surface,
        "canonical_form": canonical,
        "status": status,
    }


def _l6(entry_id, content, *, status="confirmed"):
    return {"id": entry_id, "kind": "note", "content": content, "status": status}


# --- the shape heuristic, reused rather than re-implemented -------------------


def test_a_lexicon_shaped_note_is_annotated_for_re_filing() -> None:
    # S13's acceptance case, verbatim.
    annotations = l6_write_advisories(
        "2055516 means 205/55R16", lexicon_entries=(), experience_entries=()
    )
    assert _codes(annotations) == [ADVISORY_REFILE_TO_L7]
    advisory = _advisory(annotations, ADVISORY_REFILE_TO_L7)
    # The two halves an admin would re-file WITH -- derived by the SAME
    # structurable_shape S20's sweep uses, so the sweep and the annotation can
    # never disagree about which notes are structurable.
    assert advisory["surface_form"] == "2055516"
    assert advisory["canonical_form"] == "205/55R16"


def test_a_plain_procedure_note_is_annotated_with_nothing_at_all() -> None:
    # "Neither" means an EMPTY annotations blob, not an empty advisory list:
    # a row with no advice must not render a heuristic block in the inbox.
    assert l6_write_advisories(NOTE, lexicon_entries=(), experience_entries=()) == {}


# --- cross-layer dedup: L6 propose -> confirmed L7 ----------------------------


def test_an_l6_note_whose_surface_already_exists_in_l7_is_annotated() -> None:
    entries = [
        _l7("lex_dup", "2055516"),
        # The exclusion case. Without a row the comparison must REJECT, this
        # test passes against an implementation that ignores the surface
        # entirely and reports the first confirmed entry it sees.
        _l7("lex_other", "2156016"),
    ]
    annotations = l6_write_advisories(
        "2055516 means 205/55R16", lexicon_entries=entries, experience_entries=()
    )
    assert _codes(annotations) == [ADVISORY_REFILE_TO_L7, ADVISORY_DUPLICATE_L7_SURFACE]
    duplicate = _advisory(annotations, ADVISORY_DUPLICATE_L7_SURFACE)
    assert duplicate["entry_ref"] == "lex_dup"
    assert duplicate["domain"] == "tire"


def test_the_surface_match_ignores_case_and_surrounding_whitespace() -> None:
    annotations = l6_write_advisories(
        "  toee = TOEE TIRE  ",
        lexicon_entries=[_l7("lex_toee", "TOEE", "TOEE TIRE", domain="company")],
        experience_entries=(),
    )
    assert ADVISORY_DUPLICATE_L7_SURFACE in _codes(annotations)


def test_a_proposed_l7_entry_is_not_a_duplicate_yet() -> None:
    # Only CONFIRMED rows are the vocabulary. A proposed one is inert by
    # construction (S01), so telling an admin their note duplicates something
    # nobody has accepted would be advice about a row that may never exist.
    annotations = l6_write_advisories(
        "2055516 means 205/55R16",
        lexicon_entries=[_l7("lex_pending", "2055516", status="proposed")],
        experience_entries=(),
    )
    assert _codes(annotations) == [ADVISORY_REFILE_TO_L7]


def test_prose_has_no_surface_form_so_it_can_duplicate_nothing_in_l7() -> None:
    # An L6 note that is not a mapping has no surface form to compare, and the
    # empty string must not match an L7 row (or every prose note would be
    # annotated as a duplicate of whatever row has a blank surface).
    annotations = l6_write_advisories(
        NOTE, lexicon_entries=[_l7("lex_blank", "")], experience_entries=()
    )
    assert annotations == {}


# --- cross-layer dedup: propose -> confirmed L6 notes -------------------------


def test_a_reworded_duplicate_of_a_confirmed_note_is_annotated() -> None:
    annotations = l6_write_advisories(
        NOTE_DUPLICATE,
        lexicon_entries=(),
        experience_entries=[
            _l6("aexp_dup", NOTE),
            # Two rows the comparison MUST exclude, sitting in the same fixture
            # as the one it must find.
            _l6("aexp_near", NOTE_NEAR_MISS),
            _l6("aexp_far", NOTE_UNRELATED),
        ],
    )
    assert _codes(annotations) == [ADVISORY_SIMILAR_L6_NOTE]
    similar = _advisory(annotations, ADVISORY_SIMILAR_L6_NOTE)
    assert similar["entry_ref"] == "aexp_dup"
    assert similar["similarity"] >= SIMILAR_NOTE_MIN_SIMILARITY


def test_the_same_template_with_a_different_subject_is_not_a_duplicate() -> None:
    # The load-bearing negative. These two sentences share every word but the
    # subject, which is exactly what a busy L6 store looks like; if the
    # threshold cannot separate them the advisory fires on everything.
    annotations = l6_write_advisories(
        NOTE, lexicon_entries=(), experience_entries=[_l6("aexp_near", NOTE_NEAR_MISS)]
    )
    assert annotations == {}


def test_a_rejected_note_is_not_something_to_duplicate() -> None:
    annotations = l6_write_advisories(
        NOTE_DUPLICATE,
        lexicon_entries=(),
        experience_entries=[_l6("aexp_dead", NOTE, status="rejected")],
    )
    assert annotations == {}


def test_the_measured_gap_the_threshold_sits_in_is_still_there() -> None:
    # The threshold is a measurement, so it is pinned as one. If someone widens
    # the connective set, changes the tokenizer, or moves the constant, this is
    # the test that says which side of the gap moved.
    assert note_similarity(NOTE, NOTE_DUPLICATE) >= SIMILAR_NOTE_MIN_SIMILARITY
    assert note_similarity(NOTE, NOTE_NEAR_MISS) < SIMILAR_NOTE_MIN_SIMILARITY
    assert note_similarity(NOTE, NOTE_UNRELATED) < SIMILAR_NOTE_MIN_SIMILARITY
    # The sharpest near-miss this domain can produce: a neighbouring tire size.
    assert (
        note_similarity("2055516 = 205/55R16", "2055517 = 205/55R17")
        < SIMILAR_NOTE_MIN_SIMILARITY
    )


def test_one_mapping_is_compared_however_each_side_spells_it() -> None:
    # An L7 proposal and an L6 note describing the SAME mapping must compare as
    # the same thing whether the note wrote `=` or `means`. Both sides are put
    # through structurable_shape first -- one spelling, one comparison, and no
    # second regex.
    annotations = l7_write_advisories(
        "TOEE",
        "TOEE TIRE",
        lexicon_entries=(),
        experience_entries=[
            _l6("aexp_says_it", "TOEE means TOEE TIRE"),
            _l6("aexp_other", "TOEE means the front counter"),
        ],
    )
    assert _codes(annotations) == [ADVISORY_SIMILAR_L6_NOTE]
    assert _advisory(annotations, ADVISORY_SIMILAR_L6_NOTE)["entry_ref"] == "aexp_says_it"


# --- cross-layer dedup: L7 propose -> confirmed L7 ----------------------------


def test_an_l7_surface_already_confirmed_in_another_domain_is_annotated() -> None:
    # UNIQUE(domain, surface_form) makes a SAME-domain collision a governed
    # conflict, so this advisory is about the case the constraint permits: FR-1
    # allows one surface form in two domains, and an admin deciding the second
    # one should be told the first exists.
    annotations = l7_write_advisories(
        "TOEE",
        "TOEE TIRE",
        lexicon_entries=[
            _l7("lex_company", "TOEE", "TOEE TIRE", domain="company"),
            _l7("lex_unrelated", "2055516", domain="tire"),
        ],
        experience_entries=(),
    )
    assert _codes(annotations) == [ADVISORY_DUPLICATE_L7_SURFACE]
    assert _advisory(annotations, ADVISORY_DUPLICATE_L7_SURFACE)["domain"] == "company"


def test_an_l7_proposal_that_duplicates_nothing_is_annotated_with_nothing() -> None:
    assert (
        l7_write_advisories(
            "2156016",
            "215/60R16",
            lexicon_entries=[_l7("lex_other", "2055516")],
            experience_entries=[_l6("aexp_prose", NOTE)],
        )
        == {}
    )


# --- NFR-3: the advisory rides the row, it never decides anything ------------


def _experience_driver() -> MockDriver:
    return MockDriver(create_agent_experience_mock_handlers())


def _lexicon_driver() -> MockDriver:
    return MockDriver(create_semantic_lexicon_mock_handlers())


def _ctx(user_id: str | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(profile="internal_copilot", user_id=user_id)


def _admin_ctx(user_id: str = "admin_1") -> ToolExecutionContext:
    # D20: `admin_manual` is derivable only on the deterministic admin route
    # WITH an attributed actor, and `add_lexicon_entry` refuses anything else.
    return ToolExecutionContext(
        profile="internal_copilot", user_id=user_id, dispatch_route=TOOLS_DISPATCH_ROUTE
    )


def _propose_experience(driver, **params):
    return execute_tool(
        tool="toee_agent_experience",
        action="propose_experience",
        params=params,
        context=_ctx(),
        driver=driver,
    )


def _propose_lexicon(driver, **params):
    return execute_tool(
        tool="toee_semantic_lexicon",
        action="propose_lexicon_entry",
        params=params,
        context=_ctx(),
        driver=driver,
    )


def _confirm_experience(driver, entry_id):
    return execute_tool(
        tool="toee_agent_experience",
        action="confirm_experience",
        params={"id": entry_id},
        context=_admin_ctx(),
        driver=driver,
    )


def test_the_l6_mock_annotates_and_still_persists_a_proposed_row() -> None:
    driver = _experience_driver()
    result = _propose_experience(driver, kind="note", content="2055516 means 205/55R16")
    assert result.ok
    # NFR-3: the annotation is metadata. The row lands, unchanged, as `proposed`.
    assert result.data["status"] == "proposed"
    assert result.data["content"] == "2055516 means 205/55R16"
    assert _codes(result.data["annotations"]) == [ADVISORY_REFILE_TO_L7]

    listed = execute_tool(
        tool="toee_agent_experience",
        action="list_agent_experience",
        params={},
        context=_ctx(),
        driver=driver,
    )
    # The queue read is where the inbox picks the advisory up (S15 already maps
    # `annotations` off the raw proposal row), so the column has to survive it.
    assert _codes(listed.data["entries"][0]["annotations"]) == [ADVISORY_REFILE_TO_L7]


def test_the_l6_mock_compares_a_new_note_against_its_own_confirmed_notes() -> None:
    driver = _experience_driver()
    first = _propose_experience(driver, kind="note", content=NOTE)
    _confirm_experience(driver, first.data["id"])
    # A second, still-PROPOSED note that must not become a candidate itself.
    _propose_experience(driver, kind="note", content=NOTE_UNRELATED)

    echo = _propose_experience(driver, kind="note", content=NOTE_DUPLICATE)
    assert _codes(echo.data["annotations"]) == [ADVISORY_SIMILAR_L6_NOTE]
    assert (
        _advisory(echo.data["annotations"], ADVISORY_SIMILAR_L6_NOTE)["entry_ref"]
        == first.data["id"]
    )

    near = _propose_experience(driver, kind="note", content=NOTE_NEAR_MISS)
    assert near.data["annotations"] == {}


def test_the_l7_mock_annotates_and_still_persists_a_proposed_row() -> None:
    driver = _lexicon_driver()
    seeded = _propose_lexicon(
        driver,
        domain="company",
        entry_kind="alias",
        surface_form="TOEE",
        canonical_form="TOEE TIRE",
    )
    assert seeded.data["annotations"] == {}
    # Confirm it so it becomes vocabulary, then propose the same surface in a
    # second domain -- legal under UNIQUE(domain, surface_form), and exactly the
    # collision an admin should be told about.
    execute_tool(
        tool="toee_semantic_lexicon",
        action="confirm_lexicon_entry",
        params={"id": seeded.data["id"]},
        context=_admin_ctx(),
        driver=driver,
    )
    second = _propose_lexicon(
        driver,
        domain="tire",
        entry_kind="alias",
        surface_form="TOEE",
        canonical_form="TOEE all-season",
    )
    assert second.ok
    assert second.data["status"] == "proposed"
    assert _codes(second.data["annotations"]) == [ADVISORY_DUPLICATE_L7_SURFACE]


def test_an_admin_added_entry_carries_no_write_time_advisory() -> None:
    # FR-18 annotates a PROPOSAL, which is a thing a human still has to decide.
    # An admin add IS the decision; advising the decider about the row they just
    # authored would be advice with nowhere to go.
    driver = _lexicon_driver()
    added = execute_tool(
        tool="toee_semantic_lexicon",
        action="add_lexicon_entry",
        params={
            "domain": "tire",
            "entry_kind": "alias",
            "surface_form": "2055516",
            "canonical_form": "205/55R16",
        },
        context=_admin_ctx(),
        driver=driver,
    )
    assert added.ok
    assert added.data["annotations"] == {}


@pytest.mark.parametrize("content", ["", "   "])
def test_an_empty_note_is_never_a_duplicate_of_anything(content) -> None:
    # Degenerate input reaches the resolver before the validators on some paths;
    # an empty comparison text must score 0, not match everything.
    assert l6_write_advisories(
        content, lexicon_entries=(), experience_entries=[_l6("aexp_1", NOTE)]
    ) == {}
