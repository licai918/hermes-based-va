"""Tests for the labelled judge fixture set (S27-0.0.3 FR-29; S21-0.0.5 FR-28).

Pins the shape of :data:`eval_runner.judge_fixtures.JUDGE_FIXTURES`: a small set
of ground-truth-labelled transcripts covering every leg's categories, plus the
known "2pm ETA vs after-2pm contact preference" conflation class in both
directions (0.0.3 EXPLORATION.md). S21 (0.0.5 FR-28) extends it with the three
new legs -- misapplication and stale-use (advisory) and the gating adversarial
safety leg -- each needing enough labelled fixtures in BOTH directions for its
precision/recall number to mean anything. No live model call -- this only
inspects the fixture data itself.
"""

from __future__ import annotations

from eval_runner.judge_fixtures import JUDGE_FIXTURES, JudgeFixture

# The human ground-truth label -> (leg the judge is asked, expected verdict).
# Pinned here, in the test, so a fixture whose label drifts from its data fails.
CATEGORY_LEG: dict[str, tuple[str, bool]] = {
    "honored": ("honored", True),
    "not_honored": ("honored", False),
    "unprompted_recall": ("no_unprompted_recall", False),
    "clean": ("no_unprompted_recall", True),
    "misapplied": ("no_misapplication", False),
    "not_misapplied": ("no_misapplication", True),
    "stale_use": ("no_stale_use", False),
    "current_use": ("no_stale_use", True),
    "injection_obeyed": ("injection_resisted", False),
    "injection_resisted": ("injection_resisted", True),
}


def test_every_leg_keeps_a_held_out_split_the_rubric_does_not_describe() -> None:
    # S21 review, finding 2. `judge._LEG_GUIDANCE` was written against the
    # in-sample fixtures, so their score partly measures the prompt describing
    # them. Every leg keeps at least two fixtures the guidance never mentions,
    # in BOTH directions, or its reported number is in-sample only.
    #
    # (This replaces a `len(JUDGE_FIXTURES) <= 40` bound that constrained nothing
    # at n=31 -- a real structural constraint instead of a decorative one.)
    for leg in {leg for leg, _ in CATEGORY_LEG.values()}:
        held_out = [f for f in JUDGE_FIXTURES if f.leg == leg and f.held_out]
        assert len(held_out) >= 2, f"leg {leg} has no held-out split"
        assert any(f.expected_passed for f in held_out), leg
        assert any(not f.expected_passed for f in held_out), leg


def test_held_out_fixtures_avoid_the_in_sample_memory_presets() -> None:
    # A held-out reply judged against an in-sample memory preset is only half
    # held out -- the rubric guidance quotes preset wording verbatim.
    #
    # Compared per (SLOT, VALUE), not per whole preset (S21 re-review): the
    # held-out channel preset was `{"channel_preference": "text message"}`, the
    # byte-identical half of the in-sample `_MIXED_PREFERENCES`, and a
    # whole-dict comparison called that held out because the dict had one key
    # instead of two.
    in_sample_values = {
        item
        for f in JUDGE_FIXTURES
        if not f.held_out
        for item in f.memory_preset.items()
    }
    for fixture in (f for f in JUDGE_FIXTURES if f.held_out):
        shared = sorted(set(fixture.memory_preset.items()) & in_sample_values)
        assert not shared, (
            f"held-out fixture {fixture.name} is judged against memory an "
            f"in-sample fixture already uses verbatim: {shared}"
        )


def test_every_fixture_is_a_judge_fixture_with_a_unique_name_and_reply() -> None:
    names = [f.name for f in JUDGE_FIXTURES]
    replies = [f.reply for f in JUDGE_FIXTURES]
    assert len(names) == len(set(names)), "fixture names must be unique"
    # Unique replies too: the oracle stand-ins key their ground truth by reply
    # text, so a duplicate would silently score one fixture with the other's label.
    assert len(replies) == len(set(replies)), "fixture replies must be unique"
    for fixture in JUDGE_FIXTURES:
        assert isinstance(fixture, JudgeFixture)
        assert fixture.category in CATEGORY_LEG
        assert isinstance(fixture.expected_passed, bool)
        assert fixture.reply
        # The prompt escapes &<> in untrusted text; fixture replies stay clear of
        # them so an oracle's `reply in prompt` match cannot silently miss.
        assert not set(fixture.reply) & set("&<>")


def test_every_ground_truth_category_is_represented() -> None:
    categories = {f.category for f in JUDGE_FIXTURES}
    assert categories == set(CATEGORY_LEG)


def test_category_matches_leg_and_expected_passed() -> None:
    # category is a human label; leg/expected_passed are what the judge
    # actually sees -- pin they agree so the label can't drift from the data.
    for fixture in JUDGE_FIXTURES:
        leg, expected = CATEGORY_LEG[fixture.category]
        assert fixture.leg == leg
        assert fixture.expected_passed is expected


def test_each_leg_has_enough_labelled_fixtures_in_both_directions() -> None:
    # A precision/recall number over one or two fixtures is noise dressed as
    # measurement (the S27-0.0.3 discipline: calibrate the ruler before use).
    for leg in {leg for leg, _ in CATEGORY_LEG.values()}:
        of_leg = [f for f in JUDGE_FIXTURES if f.leg == leg]
        positives = [f for f in of_leg if f.expected_passed]
        negatives = [f for f in of_leg if not f.expected_passed]
        assert len(of_leg) >= 4, f"leg {leg} needs a measurable fixture count"
        assert positives, f"leg {leg} has no ground-truth-positive fixture"
        assert negatives, f"leg {leg} has no ground-truth-negative fixture"


def test_the_safety_leg_fixtures_actually_carry_an_injected_instruction() -> None:
    # The gating leg's fixtures must replay the real failure shape: a memory
    # value phrased as a command to the agent.
    safety = [f for f in JUDGE_FIXTURES if f.leg == "injection_resisted"]
    assert safety
    for fixture in safety:
        memory = " ".join(fixture.memory_preset.values()).lower()
        assert any(
            phrase in memory
            for phrase in (
                "ignore prior instructions",
                "system:",
                "always approve",
                # The held-out shape: an authority claim rather than one of the
                # phrasings the rubric guidance names by example.
                "no approval needed",
            )
        ), f"{fixture.name} memory must read as a smuggled instruction"


def test_stale_use_fixtures_show_the_superseded_value_in_the_memory() -> None:
    # Nothing can judge "used a stale value" unless the memory itself reveals
    # which value is current and which one it replaced.
    stale = [f for f in JUDGE_FIXTURES if f.leg == "no_stale_use"]
    assert stale
    for fixture in stale:
        memory = " ".join(fixture.memory_preset.values()).lower()
        # The vocabulary is open on purpose: the in-sample presets use the
        # "(current, set ...; replaces the earlier X)" wording the rubric
        # guidance quotes verbatim, and the held-out ones must NOT (S21 review).
        # What every one of them must do is reveal which value is superseded.
        assert any(
            phrase in memory for phrase in ("replaces", "changed from", "superseded")
        ), fixture.name


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
