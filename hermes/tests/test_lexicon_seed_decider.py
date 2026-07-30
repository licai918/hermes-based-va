"""`admin_manual` with a MIGRATION as its decider is not a named admin either.

FOUND BY LOOKING AT THE CONSOLE. The 0.0.5 walkthrough showed `/admin/lexicon` with
four confirmed rows, every one of them:

    provenance = admin_manual        decider = seed:0024_lexicon_seed_domain_1

D20 established that `admin_manual` "means exactly one thing: a human administrator
typed this", and made a write with **no resolvable actor** fail closed. It then
derived `provenance_unattributed` so rows written before that gate could be rendered
distinctly instead of looking authoritative.

D20's flag tests for a **NULL** decider. A seeded row is a THIRD case: attributed,
but attributed to a migration. It is not a D20 hole — nothing is null — yet the
misreading it produces is identical: a reviewer scanning the queue sees
`admin_manual` beside a decider and concludes a person approved it.

So the flag's real question is not "is anyone attached" but **"is a NAMED HUMAN
attached"**, and that is what it now answers. The rendering path is reused rather
than duplicated, because the consequence is the same one D20 already handled.

Not in scope: changing the seed rows' provenance. There is no fourth provenance value
for "seeded", adding one is a catalog-wide change, and the seeded rows genuinely are
a human decision — the code author's — that happens to arrive by migration. Making
the console *say so* is the honest fix; relabelling the data is a bigger claim.
"""

from __future__ import annotations

from toee_hermes.drivers.mock.semantic_lexicon import (
    LEXICON_PROVENANCE_ADMIN_MANUAL,
    LEXICON_PROVENANCE_CONVERSATION_CONFIRMED,
    lexicon_provenance_unattributed,
)


def test_a_seeded_decider_is_not_a_named_admin():
    """The one that reddened: a `seed:` decider read as an admin's own approval."""
    row = {
        "provenance": LEXICON_PROVENANCE_ADMIN_MANUAL,
        "decider_account_id": "seed:0024_lexicon_seed_domain_1",
    }

    assert lexicon_provenance_unattributed(row) is True, (
        "a migration is not a human administrator; an admin_manual row deciderd by "
        "one must render distinctly, exactly as a NULL-decider row does"
    )


def test_a_null_decider_still_flags_which_is_D20s_original_case():
    """The widening must not lose what D20 built the flag for."""
    row = {"provenance": LEXICON_PROVENANCE_ADMIN_MANUAL, "decider_account_id": None}

    assert lexicon_provenance_unattributed(row) is True


def test_a_real_account_id_does_NOT_flag():
    """The load-bearing negative: without it the flag could mark everything.

    A flag that fires on every row tells a reviewer nothing, which is the failure
    mode that gets a badge ignored.
    """
    row = {
        "provenance": LEXICON_PROVENANCE_ADMIN_MANUAL,
        "decider_account_id": "acct_7f3c9e21",
    }

    assert lexicon_provenance_unattributed(row) is False


def test_a_non_admin_provenance_never_flags_whatever_its_decider():
    """The flag is a claim about `admin_manual` specifically.

    `conversation_confirmed` does not assert that a human typed it, so a seeded or
    absent decider there is not a contradiction and must not be badged as one.
    """
    for decider in (None, "seed:0024_lexicon_seed_domain_1", "acct_7f3c9e21"):
        row = {
            "provenance": LEXICON_PROVENANCE_CONVERSATION_CONFIRMED,
            "decider_account_id": decider,
        }
        assert lexicon_provenance_unattributed(row) is False, decider
