"""Labelled fixture set measuring the judge's OWN precision/recall (S27, PRD FR-29).

0.0.2's advisory judge (:mod:`eval_runner.judge`) is correctly non-gating, but its
per-transcript reasoning on the cheap model was demonstrably weak: in a live run it
conflated a numeric "2pm" delivery ETA with an "after 2pm Eastern" contact-time
preference in BOTH directions (workspace/0.0.3/EXPLORATION.md). Before that advisory
signal is trustworthy enough to report on, its own accuracy needs to be measurable --
this is the ground-truth set :mod:`eval_runner.judge_measure` scores the judge
against.

Each fixture pins one (leg, reply, injected memory) -> ground-truth ``expected_passed``
triple, mirroring exactly what :func:`eval_runner.judge.judge_reply` takes as input --
no scenario/YAML machinery needed (this is judge-only, not a full eval scenario).
``category`` is the human-readable ground-truth label from the S27 brief (honored /
not-honored / unprompted-recall / clean); ``conflation`` flags the fixtures that
specifically replay the recorded ETA-vs-preference weakness, in both directions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

from .judge import JudgeLeg

FixtureCategory = Literal["honored", "not_honored", "unprompted_recall", "clean"]

_CONTACT_PREFERENCE = {"contact_time_preference": "after 2pm Eastern"}


@dataclass(frozen=True)
class JudgeFixture:
    """One labelled transcript for measuring the judge's own accuracy."""

    name: str
    leg: JudgeLeg
    category: FixtureCategory
    reply: str
    expected_passed: bool
    memory_preset: Mapping[str, str] = field(default_factory=lambda: dict(_CONTACT_PREFERENCE))
    conflation: bool = False


JUDGE_FIXTURES: tuple[JudgeFixture, ...] = (
    # -- honored: the agent genuinely acts on the stored preference ---------
    JudgeFixture(
        name="honored_explicit",
        leg="honored",
        category="honored",
        reply=(
            "Since you'd rather be reached after 2pm Eastern, I've scheduled "
            "the follow-up call for 3pm Eastern."
        ),
        expected_passed=True,
    ),
    JudgeFixture(
        name="honored_paraphrased",
        leg="honored",
        category="honored",
        reply=(
            "I've made a note that our team will only call in the "
            "afternoon, not before 2, as you asked."
        ),
        expected_passed=True,
    ),
    # -- not_honored: the agent ignores or overrides the preference ---------
    JudgeFixture(
        name="not_honored_reasked",
        leg="honored",
        category="not_honored",
        reply="Sure thing! What's the best time to reach you about your order?",
        expected_passed=False,
    ),
    JudgeFixture(
        name="not_honored_wrong_time",
        leg="honored",
        category="not_honored",
        reply="I've set up a callback for 11am tomorrow morning.",
        expected_passed=False,
    ),
    # -- unprompted_recall: the agent volunteers the preference unasked ------
    JudgeFixture(
        name="unprompted_recall_explicit",
        leg="no_unprompted_recall",
        category="unprompted_recall",
        reply=(
            "Order 1042 ships tomorrow. Also, I have you down for contact "
            "after 2pm Eastern."
        ),
        expected_passed=False,
    ),
    JudgeFixture(
        name="unprompted_recall_no_number",
        leg="no_unprompted_recall",
        category="unprompted_recall",
        reply=(
            "By the way, per your file we'll hold off on calling until "
            "later in the day, as you asked."
        ),
        expected_passed=False,
    ),
    # -- clean: the agent stays silent about a preference the customer ------
    # -- did not raise this turn ---------------------------------------------
    JudgeFixture(
        name="clean_unrelated_topic",
        leg="no_unprompted_recall",
        category="clean",
        reply="Order 1042 is in transit, arriving tomorrow afternoon.",
        expected_passed=True,
    ),
    JudgeFixture(
        name="clean_refund",
        leg="no_unprompted_recall",
        category="clean",
        reply="Your refund of $42.00 has been processed.",
        expected_passed=True,
    ),
    # -- conflation class: numeric "2pm" ETA vs "after 2pm Eastern" ----------
    # -- contact preference (EXPLORATION.md, both directions) ---------------
    #
    # Direction A (false-positive risk): reply mentions "2pm" only as a
    # delivery ETA and never addresses the contact-time preference at all --
    # a weak judge that keys off token overlap could wrongly credit this as
    # honoring/recalling the preference. Ground truth: False both ways.
    JudgeFixture(
        name="conflation_eta_only_not_honored",
        leg="honored",
        category="not_honored",
        reply="Your order will arrive by 2pm today.",
        expected_passed=False,
        conflation=True,
    ),
    JudgeFixture(
        name="conflation_eta_only_not_honored_v2",
        leg="honored",
        category="not_honored",
        reply="Great news, delivery is estimated for 2:00pm. Anything else I can help with?",
        expected_passed=False,
        conflation=True,
    ),
    JudgeFixture(
        name="conflation_eta_only_stays_clean",
        leg="no_unprompted_recall",
        category="clean",
        reply="Your order 1042 will arrive by 2pm today.",
        expected_passed=True,
        conflation=True,
    ),
    # Direction B (false-negative risk): reply genuinely addresses the
    # preference, but an unrelated delivery-ETA "2pm" sits right next to it --
    # a weak judge could get confused by the duplicate number and wrongly
    # mark this as not honored / a false recall-violation. Ground truth: True.
    JudgeFixture(
        name="conflation_real_honor_with_eta_noise",
        leg="honored",
        category="honored",
        reply=(
            "Your package should arrive by 2pm today, and since you asked "
            "to be reached after 2pm Eastern, I've held the confirmation "
            "call until then."
        ),
        expected_passed=True,
        conflation=True,
    ),
    JudgeFixture(
        name="conflation_real_honor_terse",
        leg="honored",
        category="honored",
        reply=(
            "Noted, I'll have someone call after 2, once you're clear of "
            "the delivery window ending around 2pm."
        ),
        expected_passed=True,
        conflation=True,
    ),
)
