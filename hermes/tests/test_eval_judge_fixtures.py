"""Tests for the S27 labelled judge fixture set (PRD FR-29).

Pins the shape of :data:`eval_runner.judge_fixtures.JUDGE_FIXTURES`: a small
(~10-16) set of ground-truth-labelled transcripts covering all four
categories (honored / not-honored / unprompted-recall / clean) plus the
known "2pm ETA vs after-2pm contact preference" conflation class in both
directions (EXPLORATION.md). No live model call -- this only inspects the
fixture data itself.
"""

from __future__ import annotations

from eval_runner.judge_fixtures import JUDGE_FIXTURES, JudgeFixture


def test_fixture_set_size_is_small_but_covers_the_labelled_range() -> None:
    assert 10 <= len(JUDGE_FIXTURES) <= 16


def test_every_fixture_is_a_judge_fixture_with_a_unique_name() -> None:
    names = [f.name for f in JUDGE_FIXTURES]
    assert len(names) == len(set(names)), "fixture names must be unique"
    for fixture in JUDGE_FIXTURES:
        assert isinstance(fixture, JudgeFixture)
        assert fixture.leg in ("honored", "no_unprompted_recall")
        assert isinstance(fixture.expected_passed, bool)
        assert fixture.reply


def test_all_four_ground_truth_categories_are_represented() -> None:
    categories = {f.category for f in JUDGE_FIXTURES}
    assert categories == {"honored", "not_honored", "unprompted_recall", "clean"}


def test_category_matches_leg_and_expected_passed() -> None:
    # category is a human label; leg/expected_passed are what the judge
    # actually sees -- pin they agree so the label can't drift from the data.
    for fixture in JUDGE_FIXTURES:
        if fixture.category == "honored":
            assert fixture.leg == "honored" and fixture.expected_passed is True
        elif fixture.category == "not_honored":
            assert fixture.leg == "honored" and fixture.expected_passed is False
        elif fixture.category == "unprompted_recall":
            assert (
                fixture.leg == "no_unprompted_recall"
                and fixture.expected_passed is False
            )
        elif fixture.category == "clean":
            assert (
                fixture.leg == "no_unprompted_recall"
                and fixture.expected_passed is True
            )


def test_known_conflation_class_is_covered_in_both_directions() -> None:
    # The recorded 0.0.2 weakness: the cheap judge conflated a numeric "2pm"
    # delivery ETA with an "after 2pm Eastern" contact-time preference in
    # BOTH directions (EXPLORATION.md). Direction A: an ETA-only reply that a
    # weak judge might wrongly credit as honoring/recalling the preference
    # (ground truth False). Direction B: a reply that genuinely addresses the
    # preference despite ETA noise nearby, which a weak judge might wrongly
    # mark as not honoring / a false recall-violation (ground truth True).
    conflation = [f for f in JUDGE_FIXTURES if f.conflation]
    assert len(conflation) >= 4

    false_direction = [f for f in conflation if f.expected_passed is False]
    true_direction = [f for f in conflation if f.expected_passed is True]
    assert false_direction, "missing a conflation fixture with ground truth False"
    assert true_direction, "missing a conflation fixture with ground truth True"

    # Every conflation fixture actually exercises "2pm" so it is a realistic
    # replay of the recorded weakness, not just an unrelated hard case.
    for fixture in conflation:
        assert "2pm" in fixture.reply.lower() or "2" in fixture.reply
        assert "2pm" in " ".join(fixture.memory_preset.values()).lower()
