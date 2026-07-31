"""Search-side vocabulary: reach the corpus's words from the customer's (FR-30).

The knowledge corpus is authored prose. Customers are tire shops typing on a phone.
When those two use different words for the same thing, the lexical leg of the hybrid
retriever matches nothing and the semantic leg is left carrying the query alone --
which is how ``do you sell grenlander`` misses a page literally titled *Grenlander*.

MEASURED. S24's real question set scored recall@3 = 13/22 raw and 16/22 expanded --
the second number being exactly what the synthetic interim set scores. The synthetic
set was written by someone who had read the corpus, so it never had this problem;
the real one does, and the difference was vocabulary rather than difficulty.

**This is not L7, and the distinction is load-bearing.** L7 is *business* vocabulary:
governed by humans, injected into prompts, and carrying a disclosure consequence
(0.0.6 D1 -- customer wording maps IN to a facet value, and a single approved label
comes OUT; calling a PASSENGER tire "all-season" to a Canadian customer is the
misleading claim that policy exists to forbid). This table is *search* vocabulary:
it never reaches a customer, never renames a product, is never rendered, and is
tested to hold nothing seasonal. If 0.0.6 consolidates vocabulary ownership, this is
a consumer of that decision, not a competitor to it.

The expansion **appends and never replaces**. The customer's own wording is
frequently the term the lexical leg matches, so dropping it would trade one miss for
another.
"""

from __future__ import annotations

# surface form (what a shop owner types) -> canonical (what the corpus prints).
#
# Every entry earns its place by a miss in the real question set or by being the
# same shape as one. Deliberately small: an expansion table that grows by guessing
# starts adding noise to every query, and the ranking has no way to tell a helpful
# term from a decorative one.
TRADE_SYNONYMS: dict[str, str] = {
    # collection vs delivery -- the corpus says "pickup"/"pick up" throughout
    "come get": "pick up",
    "come and get": "pick up",
    "collect": "pick up",
    "picking up": "pick up",
    # stocking a brand
    "sell": "carry",
    "stock": "carry",
    "do you have": "carry",
    # volume
    "bigger lot": "bulk order",
    "big lot": "bulk order",
    "large lot": "bulk order",
    "a lot at once": "bulk order",
    # credit terms -- the shop-owner program page calls this "Payment Terms"
    "bill me": "payment terms",
    "bill me out": "payment terms",
    "invoice me": "payment terms",
    "net terms": "payment terms",
    # a closed compound the corpus spells shut and customers spell open. Two
    # tokens vs one is a lexeme mismatch no ranking change can repair.
    "log in": "login",
    "sign in": "login",
    "logging in": "login",
}


def expand_query(query: str) -> str:
    """Append the corpus's word for any trade term the query uses.

    Returns ``query`` unchanged when the table has nothing to say about it -- no
    silent rewriting. Appended terms are deduplicated and never include a term the
    query already contains, because repeating a word the ranking already counted is
    noise rather than signal.
    """
    if not query:
        return query

    lowered = query.lower()
    additions: list[str] = []
    for surface, canonical in TRADE_SYNONYMS.items():
        if surface in lowered and canonical not in lowered and canonical not in additions:
            additions.append(canonical)

    return f"{query} {' '.join(additions)}" if additions else query
