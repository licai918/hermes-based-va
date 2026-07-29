"""0.0.5 S27 (FR-33): the deterministic half of edit-diff mining.

Pure functions only -- the span diff, the four mineability rules, the
distinct-draft clustering, the L7-vs-L6 shape split, and the PII boundary.
``test_datastore_edit_diff_mining.py`` is the live-Postgres half; nothing here
touches a database.

**Every negative case in this file is named in the slice brief**, and they are
tested at least as hard as the positive one: an advisory that fires on every
edit is noise, and noise gets switched off. Each rule kills exactly one shape:

* a *trim for length* leaves an edit region with nothing on the sent side;
* an *insertion* leaves one with nothing on the draft side;
* a *sentence reorder* leaves a region whose two sides are the same words;
* a *paragraph rewrite* leaves a region far too long to be a rule;
* an *idiosyncratic edit* (typo or otherwise) never recurs across three drafts.
"""

from __future__ import annotations

import pytest

from hermes_runtime.edit_diff_mining import (
    ALIAS_MAX_TOKENS,
    MINEABLE_MAX_SPAN_TOKENS,
    SHAPE_L6_PROCEDURE,
    SHAPE_L7_ALIAS,
    Rewrite,
    carries_pii,
    cluster_rewrites,
    mineable_rewrites,
    rewrite_evidence,
    rewrites_for,
    tripped_rewrites,
)
from hermes_runtime.feedback_aggregator import SIMILAR_EDIT_DIFF_THRESHOLD

# A real-looking phone and street address, in the SURROUNDING prose of every
# draft below that uses them. NFR-6's boundary is that neither can cross into a
# shared layer; the fixture has to contain them for the test to mean anything.
_PHONE = "604-555-1212"
_ADDRESS = "1725 Kingsway, Vancouver"


def _drafts(pairs):
    """``[(draft, sent), ...]`` -> the mined rewrites, one draft ref per pair."""
    out = []
    for n, (draft, sent) in enumerate(pairs):
        out.extend(rewrites_for(draft_ref=f"corr_{n}", draft_text=draft, sent_text=sent, at=float(n)))
    return out


def _tripped(pairs):
    return tripped_rewrites(cluster_rewrites(_drafts(pairs)))


# --- the positive case --------------------------------------------------------


def test_three_consistent_surface_rewrites_yield_one_l7_alias_pair():
    """The headline: reps keep rewriting X to Y, so propose X -> Y as an alias."""
    tripped = _tripped(
        [
            ("We have mud tires in stock for your truck.", "We have all-terrain tires in stock for your truck."),
            ("The mud tires you asked about are here.", "The all-terrain tires you asked about are here."),
            ("Yes, mud tires fit that rim.", "Yes, all-terrain tires fit that rim."),
        ]
    )

    assert len(tripped) == 1
    cluster = tripped[0]
    assert (cluster.surface_form, cluster.canonical_form) == ("mud", "all-terrain")
    assert cluster.size == 3
    assert cluster.shape == SHAPE_L7_ALIAS


def test_a_recurring_clause_rewrite_is_an_l6_shape_and_yields_no_junk_alias():
    """A clause rewrite is ONE signal, not one per word the diff happened to split.

    Without region coalescing this pair diffs into two opcodes separated by the
    two-token equal run "the difference" -- and the short one would trip the
    alias threshold as ``refund -> put``, which is not a domain alias at all. A
    junk L7 proposal beside every real L6 one is exactly the noise that gets an
    advisory switched off, so the assertion is on the WHOLE tripped set.
    """
    draft = "We can refund the difference to your card."
    sent = "We can put the difference on a store credit."
    tripped = _tripped([(draft, sent)] * 3)

    assert len(tripped) == 1
    cluster = tripped[0]
    assert cluster.shape == SHAPE_L6_PROCEDURE
    assert cluster.surface_form == "refund the difference to your card."
    assert cluster.canonical_form == "put the difference on a store credit."


# --- the negative cases -------------------------------------------------------


def test_two_similar_diffs_yield_nothing():
    """M-1 is silence. Without this an implementation with ``>= 1`` passes."""
    pairs = [
        ("We have mud tires in stock.", "We have all-terrain tires in stock."),
        ("The mud tires are here.", "The all-terrain tires are here."),
    ]
    assert len(pairs) == SIMILAR_EDIT_DIFF_THRESHOLD - 1
    assert _tripped(pairs) == []
    # ... and the cluster genuinely exists, it is only under the line -- so this
    # test cannot pass because the diff itself silently found nothing.
    assert [c.size for c in cluster_rewrites(_drafts(pairs))] == [2]


def test_trimming_for_length_is_not_a_rewrite():
    """A delete has no canonical form. Three of them still say nothing."""
    draft = "Your order ships tomorrow. Thanks so much for reaching out to us."
    sent = "Your order ships tomorrow."
    assert mineable_rewrites(draft, sent) == []
    assert _tripped([(draft, sent)] * 3) == []


def test_padding_a_draft_is_not_a_rewrite():
    """The sibling of the trim: an insert has no surface form."""
    draft = "Your order ships tomorrow."
    sent = "Your order ships tomorrow. Thanks so much for reaching out to us."
    assert mineable_rewrites(draft, sent) == []


@pytest.mark.parametrize(
    "draft,sent",
    [
        # A long reorder: the diff renders it as a delete and a distant insert.
        (
            "Your order ships tomorrow. We appreciate your patience.",
            "We appreciate your patience. Your order ships tomorrow.",
        ),
        # A SHORT reorder, where the delete and the insert are close enough to
        # be coalesced into one region -- so the region's two sides are the same
        # words in a different order, and only the permutation rule catches it.
        ("Ready today. Call ahead.", "Call ahead. Ready today."),
    ],
)
def test_reordering_a_sentence_is_not_a_rewrite(draft, sent):
    assert mineable_rewrites(draft, sent) == []
    assert _tripped([(draft, sent)] * 3) == []


def test_a_case_only_change_is_not_a_rewrite():
    """Same words, same order, different case -- a permutation of itself."""
    assert mineable_rewrites("Winter tires are in.", "WINTER tires are in.") == []


def test_a_paragraph_rewrite_is_prose_not_a_rule():
    """Longer than ``MINEABLE_MAX_SPAN_TOKENS`` on either side is not a mapping."""
    draft = "We " + " ".join(f"alpha{n}" for n in range(MINEABLE_MAX_SPAN_TOKENS + 1)) + " today."
    sent = "We " + " ".join(f"beta{n}" for n in range(MINEABLE_MAX_SPAN_TOKENS + 1)) + " today."
    assert mineable_rewrites(draft, sent) == []


def test_unrelated_edits_cluster_to_nothing():
    """Three real edits that share nothing: three clusters of one, none tripped."""
    pairs = [
        ("We have mud tires in stock.", "We have all-terrain tires in stock."),
        ("Your invoice is attached here.", "Your receipt is attached here."),
        ("We open at nine sharp.", "We open at eight sharp."),
    ]
    assert [c.size for c in cluster_rewrites(_drafts(pairs))] == [1, 1, 1]
    assert _tripped(pairs) == []


def test_typo_fixes_that_differ_per_draft_cluster_to_nothing():
    """The brief's typo case. Three typo fixes are three different pairs.

    A typo the model makes CONSISTENTLY and reps fix consistently three times
    does emit -- see the ``ponytail:`` note on the rules. That is a proposal for
    a human, not a write, and it is arguably a real normalizer.
    """
    pairs = [
        ("Please recieve the quote.", "Please receive the quote."),
        ("Your adress is on file.", "Your address is on file."),
        ("We recomend the winter set.", "We recommend the winter set."),
    ]
    assert _tripped(pairs) == []


def test_one_draft_edited_the_same_way_three_times_is_one_draft():
    """The threshold counts DISTINCT DRAFTS, not rows (S25's lesson, restated).

    One rep re-editing one draft three times is one opinion. A row count would
    emit on it, so the fixture has to be able to tell the two apart.
    """
    rewrites = [
        Rewrite(surface_form="mud", canonical_form="all-terrain", draft_ref="corr_same", at=float(n))
        for n in range(SIMILAR_EDIT_DIFF_THRESHOLD)
    ]
    clusters = cluster_rewrites(rewrites)

    assert [c.size for c in clusters] == [1]
    assert tripped_rewrites(clusters) == []


# --- the shape split ----------------------------------------------------------


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (1, SHAPE_L7_ALIAS),
        (3, SHAPE_L7_ALIAS),
        (4, SHAPE_L6_PROCEDURE),
        (6, SHAPE_L6_PROCEDURE),
    ],
)
def test_the_shape_split_sits_exactly_at_three_tokens(tokens, expected):
    """Both sides of the boundary, so neither branch can go unexercised.

    The counts are LITERALS, not ``ALIAS_MAX_TOKENS +/- 1``. Deriving them from
    the constant makes the test move with the seam it is supposed to pin -- it
    was written that way first and a deliberate break of the constant left it
    green, which is the whole reason it now reads 3 and 4.
    """
    assert ALIAS_MAX_TOKENS == 3, "the seam moved; this test's literals must be re-argued"
    before = " ".join(f"old{n}" for n in range(tokens))
    after = " ".join(f"new{n}" for n in range(tokens))
    tripped = _tripped([(f"We {before} today.", f"We {after} today.")] * 3)

    assert len(tripped) == 1
    assert tripped[0].shape == expected


# --- the PII boundary (NFR-6) -------------------------------------------------


def test_a_pair_that_trips_the_pii_scanner_is_dropped_entirely():
    """A phone number recurring as the REPLACEMENT emits nothing at all.

    This is the leg nothing downstream provides: D2 deliberately turns the PII
    scan OFF for L7's ``surface_form``/``canonical_form``, because it cannot
    tell a tire size from a phone number. So the miner -- which is unattended,
    and therefore not the human that exemption was written for -- runs the same
    shared resolver itself and DROPS rather than redacts: a redacted alias is a
    wrong alias.
    """
    pairs = [
        (f"Call us at 604-555-1211 today.", f"Call us at {_PHONE} today."),
    ] * 3
    assert carries_pii(_PHONE) is True
    assert _drafts(pairs) == []
    assert _tripped(pairs) == []


def test_pii_in_the_surrounding_text_never_reaches_the_mined_pair():
    """Only the replacement span crosses. The rest of the draft never does.

    The fixture's drafts carry a real-looking phone AND a street address in the
    prose either side of a clean rewrite. The address matters: it is NOT a shape
    ``scan_pii`` knows, so if surrounding text could cross, nothing at all would
    stop it.
    """
    pairs = [
        (
            f"Hi Dana, call {_PHONE} or come to {_ADDRESS}. We have mud tires ready.",
            f"Hi Dana, call {_PHONE} or come to {_ADDRESS}. We have all-terrain tires ready.",
        ),
        (
            f"Dana, your mud tires are at {_ADDRESS}; reach us on {_PHONE}.",
            f"Dana, your all-terrain tires are at {_ADDRESS}; reach us on {_PHONE}.",
        ),
        (
            f"The mud tires are held under {_PHONE}.",
            f"The all-terrain tires are held under {_PHONE}.",
        ),
    ]
    tripped = _tripped(pairs)
    assert len(tripped) == 1
    cluster = tripped[0]
    assert (cluster.surface_form, cluster.canonical_form) == ("mud", "all-terrain")

    # Everything an emission can carry, flattened. Nothing else leaves this
    # module, so this is the whole boundary rather than a sample of it.
    emitted = repr(
        (cluster.surface_form, cluster.canonical_form, rewrite_evidence(cluster))
    )
    for leak in (_PHONE, "604", "Kingsway", "1725", "Dana"):
        assert leak not in emitted


def test_a_rewrite_that_coalesces_a_phone_number_into_its_span_is_dropped():
    """Coalescing can pull PII into a span, and the drop is what catches it.

    Two edits two tokens apart merge into one region (that is the whole point of
    :data:`MAX_EQUAL_GAP_TOKENS`), so a phone-number correction beside a genuine
    term fix produces a span carrying the number. The span is asserted to contain
    it, so this test proves the DROP rather than an absent diff.
    """
    draft = "Call 604-555-1211 about the mud tires."
    sent = f"Call {_PHONE} about the all-terrain tires."
    spans = mineable_rewrites(draft, sent)

    assert len(spans) == 1 and _PHONE in spans[0][1]
    assert _drafts([(draft, sent)] * 3) == []


def test_the_proposed_forms_keep_the_spelling_a_rep_actually_typed():
    """Clustering folds case; the emitted pair does not.

    An admin decides on ``Mud``, the way the earliest rep wrote it -- not on the
    case-folded key the cluster is grouped by.
    """
    tripped = _tripped(
        [
            ("We have Mud tires.", "We have All-Terrain tires."),
            ("We have mud tires.", "We have all-terrain tires."),
            ("Any mud tires left?", "Any all-terrain tires left?"),
        ]
    )

    assert len(tripped) == 1
    assert (tripped[0].surface_form, tripped[0].canonical_form) == ("Mud", "All-Terrain")


def test_evidence_carries_the_pair_and_counts_but_no_row_identifiers():
    """The S25 rule, restated: identifiers live on the run's audit row.

    ``_PHONE_RE`` matches any run of 8+ digits, which a correlation id hits
    roughly two times in five -- so an id on the row would ``policy_blocked``
    the L6 arm and mangle the L7 one. Every value here is a short token or an
    int, and ints are not scanned at all.
    """
    tripped = _tripped(
        [("We have mud tires.", "We have all-terrain tires.")] * SIMILAR_EDIT_DIFF_THRESHOLD
    )
    evidence = rewrite_evidence(tripped[0])

    assert evidence["surface_form"] == "mud"
    assert evidence["canonical_form"] == "all-terrain"
    assert evidence["edited_sends"] == SIMILAR_EDIT_DIFF_THRESHOLD
    assert "corr_0" not in repr(evidence)
    assert all(
        isinstance(v, (int, str)) and (isinstance(v, int) or len(v) <= 200)
        for v in evidence.values()
    )
