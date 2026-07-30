"""A confirmed L7 row must not carry wording the business forbids saying (0.0.6 D1).

FOUND BY LOOKING AT THE CONSOLE, not by a test. The 0.0.5 sign-off walkthrough put
`/admin/lexicon` on screen and the seeded seasonal row read:

    tire | default_rule | season=all_season | all-season tires | confirmed

The owner's vocabulary policy, recorded in 0.0.6's exploration as **D1**:

    "加拿大冬天雪特别厚，我们不会称之为 ALL SEASON，避免出现 misleading information"
    PASSENGER -> "passenger tires" — never "all-season tires"

So a **confirmed** row — one the S06 prompt seam is built to render as an imperative
ASK — was telling the model it may offer a Canadian customer "all-season tires".
That is not a naming quibble: in a market where winter capability is a safety
question, the phrase is the misleading claim the policy exists to forbid.

WHAT THIS TEST DOES AND DOES NOT DECIDE. It does not invent product language --
the approved outward label is the owner's own, quoted above. It pins the narrow
property that the seeded rows carry no forbidden phrase, so the next seeded entry
cannot reintroduce one silently. The full two-direction mapping (customer wording
IN to a facet value, one approved label OUT) is 0.0.6's spec layer and deliberately
not built here.
"""

from __future__ import annotations

import pytest

from toee_hermes.lexicon import (
    ENTRY_KIND_DEFAULT_RULE,
    LEXICON_SEED_ENTRIES,
)

# Phrases the business will not say to a customer. Lowercased, matched as
# substrings, because "all season" and "all-season" are the same claim.
FORBIDDEN_OUTWARD_PHRASES = ("all-season", "all season", "allseason")


def _rendered_forms() -> list[tuple[str, str]]:
    """(entry id, canonical_form) for every seed entry.

    `canonical_form` is the field the prompt seam renders into an imperative ASK
    (`hooks._default_rule_line`), which is why it is the one that must be clean.
    """
    return [(e.id, e.canonical_form) for e in LEXICON_SEED_ENTRIES]


@pytest.mark.parametrize("entry_id,canonical", _rendered_forms())
def test_no_seeded_entry_tells_the_agent_to_say_a_forbidden_phrase(entry_id, canonical):
    """The one that reddened: `seed_lex_season_all_season` said "all-season tires"."""
    lowered = canonical.lower()
    hit = next((p for p in FORBIDDEN_OUTWARD_PHRASES if p in lowered), None)
    assert hit is None, (
        f"seed entry {entry_id!r} has canonical_form {canonical!r}, which contains "
        f"{hit!r}. That phrase is rendered to the model as wording it may offer a "
        "customer, and the business vocabulary policy (0.0.6 D1) forbids it in this "
        "market. Use the approved label for the product class instead."
    )


def test_the_seasonal_defaults_still_name_two_DIFFERENT_products():
    """Guards the fix against the lazy version of itself.

    Renaming both seasonal rows to the same phrase would satisfy the check above
    and destroy the rule: the whole point is that the winter window implies a
    different product from the rest of the year. A fix that makes the two rows
    identical is worse than the wording it replaced.
    """
    seasonal = [e for e in LEXICON_SEED_ENTRIES if e.entry_kind == ENTRY_KIND_DEFAULT_RULE]

    assert len(seasonal) >= 2, "expected a winter and a non-winter seasonal default"
    forms = {e.canonical_form for e in seasonal}
    assert len(forms) == len(seasonal), (
        f"the seasonal defaults collapsed onto {forms} — they must name different "
        "products, or the seasonal rule says nothing"
    )


def test_the_winter_row_is_untouched_because_winter_is_not_the_forbidden_word():
    """Scope check: the policy is about ALL SEASON, not about naming winter tires.

    Without this, a future reader could take the rule above as "no seasonal wording
    at all" and strip the winter row too, which would remove a correct claim.
    """
    winter = next(e for e in LEXICON_SEED_ENTRIES if e.id == "seed_lex_season_winter")

    assert winter.canonical_form == "winter tires"
