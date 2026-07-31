"""The "is this L6 note lexicon-shaped?" heuristic (0.0.5 S13/S20, FR-18/FR-19).

Pure, no store. S20's graduation sweep re-applies it to CONFIRMED rows and S13
applies it at propose time -- ONE function, so a note the sweep would graduate
and a note the propose handler annotates can never be two different sets.

The fixture deliberately holds notes the heuristic must REJECT as well as ones it
must accept. A selection test whose every case matches proves only that the
function returns something.
"""

from __future__ import annotations

import pytest

from toee_hermes.lexicon import (
    STRUCTURABLE_CANONICAL_MAX_WORDS,
    STRUCTURABLE_SURFACE_MAX_WORDS,
    structurable_shape,
)


@pytest.mark.parametrize(
    "content,surface,canonical",
    [
        # S13's acceptance case, verbatim.
        ("2055516 means 205/55R16", "2055516", "205/55R16"),
        # The other seeded notation, whose surface form is three digit groups.
        ("205 55 16 means 205/55R16", "205 55 16", "205/55R16"),
        ("TOEE = TOEE TIRE", "TOEE", "TOEE TIRE"),
        # Case-insensitive connective, trailing period, ragged whitespace.
        ("  20555r16   MEANS   205/55R16.  ", "20555r16", "205/55R16"),
    ],
)
def test_a_mapping_shaped_note_yields_its_two_halves(content, surface, canonical) -> None:
    shape = structurable_shape(content)
    assert shape is not None
    assert (shape.surface_form, shape.canonical_form) == (surface, canonical)


@pytest.mark.parametrize(
    "content",
    [
        # A plain procedure note -- the majority of L6, and the case that must
        # never reach the graduation queue.
        "Always confirm the vehicle year before quoting a winter set.",
        "When a customer asks about warranty, link the manufacturer page first.",
        # Prose that happens to contain the connective. Bounded word counts are
        # what keeps a sentence from being read as a mapping.
        "Escalate to a human when the customer means to file a warranty claim",
        # A mapping with nothing on one side.
        "= 205/55R16",
        "2055516 means",
        "",
        None,
        123,
    ],
)
def test_a_note_that_is_not_a_mapping_yields_nothing(content) -> None:
    assert structurable_shape(content) is None


def test_the_word_bounds_are_the_thing_that_rejects_prose() -> None:
    # N words pass, N+1 fail, on BOTH sides -- the bound is load-bearing rather
    # than incidental, and a fixture sitting only on one side of it could not
    # tell "bounded" from "unbounded".
    surface_ok = " ".join(["w"] * STRUCTURABLE_SURFACE_MAX_WORDS)
    surface_over = " ".join(["w"] * (STRUCTURABLE_SURFACE_MAX_WORDS + 1))
    canonical_ok = " ".join(["c"] * STRUCTURABLE_CANONICAL_MAX_WORDS)
    canonical_over = " ".join(["c"] * (STRUCTURABLE_CANONICAL_MAX_WORDS + 1))

    assert structurable_shape(f"{surface_ok} = {canonical_ok}") is not None
    assert structurable_shape(f"{surface_over} = {canonical_ok}") is None
    assert structurable_shape(f"{surface_ok} = {canonical_over}") is None


def test_the_first_connective_splits_the_note() -> None:
    # "A = B = C" is one mapping onto a value that contains an equals sign, not
    # two mappings. Splitting on the LAST one would silently move the boundary.
    shape = structurable_shape("size = 205/55R16 = winter")
    assert shape is not None
    assert (shape.surface_form, shape.canonical_form) == ("size", "205/55R16 = winter")
