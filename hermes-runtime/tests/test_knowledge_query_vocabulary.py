"""Customers do not use the corpus's words, and the corpus cannot be rewritten.

MEASURED, NOT ASSUMED. S24's real question set -- 22 questions traced to a real
customer SMS transcript -- scored recall@3 = 13/22 while the synthetic interim set
scored 22/30. The gap is not difficulty, it is **authorship**: the synthetic set
was written by someone who had read the corpus, so its phrasing echoes the pages.
Three of the real questions have near-twins in the synthetic set; the twins hit and
the real ones missed:

    synthetic "do i have to PICK THEM UP"   vs   real "do i have to COME GET THEM"
    synthetic "do you CARRY windforce"      vs   real "do you SELL grenlander"
    synthetic "a discount if i buy A LOT"   vs   real "if i take a BIGGER LOT"

Expanding the real questions with trade synonyms lifted them to exactly 16/22 --
the same 73% the synthetic set scores. That is the cleanest evidence available that
the two sets were never measuring different difficulty, only different vocabulary.

WHAT THIS IS NOT. It is not L7. L7 is *business* vocabulary under human governance
with a disclosure consequence (0.0.6 D1: customer wording -> facet value in, and an
approved label out). This is *search* vocabulary: it never reaches a customer, never
renames a product, and is not rendered anywhere. It appends; it never deletes what
the customer wrote, because the raw term is frequently the one the lexical leg
matches.
"""

from __future__ import annotations

from hermes_runtime.knowledge.query_vocabulary import expand_query


def test_a_trade_synonym_reaches_the_word_the_corpus_actually_uses():
    """`come get` is what a shop owner says; `pick up` is what the page says."""
    expanded = expand_query("do you deliver or do i have to come get them")

    assert "pick up" in expanded
    assert "come get them" in expanded, "the customer's own words must survive"


def test_a_closed_compound_is_reached_from_its_open_spelling():
    """The corpus says `login`; the customer types `log in`.

    Two tokens versus one is a lexeme mismatch that no amount of ranking fixes --
    the lexical leg simply never matches. This is the narrowest possible case for
    a vocabulary layer and the clearest.
    """
    expanded = expand_query("how do i log in to your website to order")

    assert "login" in expanded


def test_expansion_never_deletes_the_customers_words():
    """A normalizer that discards the raw term is a different, worse thing.

    The raw wording is often exactly what the lexical leg matches, so replacing it
    would trade one miss for another. Every expansion is additive.
    """
    original = "do i get a better price if i take a bigger lot"
    expanded = expand_query(original)

    assert expanded.startswith(original)


def test_a_query_with_no_trade_vocabulary_is_returned_unchanged():
    """No silent rewriting of questions the table has nothing to say about."""
    query = "how many days do i have to send tires back"

    assert expand_query(query) == query


def test_an_already_canonical_query_is_not_padded_with_itself():
    """Appending a term the query already contains is noise in the ranking."""
    expanded = expand_query("can i pick up instead of delivery")

    assert expanded.count("pick up") == 1


def test_the_table_holds_no_entry_that_would_rewrite_a_product_claim():
    """The boundary with L7/0.0.6-D1, enforced rather than described.

    A search synonym that mapped a product class onto another -- `all season` ->
    `winter`, say -- would be making a product claim through the back door, in a
    layer with no human gate. The seasonal words are exactly where the business has
    a disclosure policy, so this table must not touch them.
    """
    from hermes_runtime.knowledge.query_vocabulary import TRADE_SYNONYMS

    forbidden = {"all season", "all-season", "all weather", "all-weather", "winter", "summer", "passenger"}
    for surface, canonical in TRADE_SYNONYMS.items():
        assert surface.lower() not in forbidden, f"{surface!r} is business vocabulary, not search vocabulary"
        assert canonical.lower() not in forbidden, f"{canonical!r} is business vocabulary, not search vocabulary"
