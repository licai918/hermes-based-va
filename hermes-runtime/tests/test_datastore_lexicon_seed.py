"""0.0.5 S03 (FR-2): seeded domain #1 against live Postgres.

Migration ``0024_lexicon_seed_domain_1`` puts the first real domain language in
``semantic_lexicon``: the tire-size normalizer toggle, the ``TOEE`` company
alias, and the two seasonal ``default_rule`` rows. The rows are ``confirmed``
and ``admin_manual`` -- they are the owner's curated vocabulary, not a proposal.

Two things are proven here that the mock twin cannot prove:

1. the SQL and :data:`toee_hermes.lexicon.LEXICON_SEED_ENTRIES` say the SAME
   thing, so the migration can never drift away from the constant every other
   slice reads;
2. ``205 55 16`` -- the surface form that matches the write scanner's phone
   pattern and nearly took the iteration down -- survives the REAL governed
   write path against a real table, not just the in-memory twin.

Skip-if-no-DB via the shared ``datastore`` fixture; it executes for real in CI.
"""

from __future__ import annotations

import pytest
from toee_hermes.execute import execute_tool
from toee_hermes.lexicon import LEXICON_SEED_ENTRIES
from toee_hermes.tool_gate import TOOLS_DISPATCH_ROUTE, ToolExecutionContext

_SEED_BY_ID = {entry.id: entry for entry in LEXICON_SEED_ENTRIES}


def _seed_rows(conn) -> dict[str, tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, domain, entry_kind, surface_form, canonical_form, "
            "evidence, status, provenance, pii_redacted, hit_count, "
            "decider_account_id, decided_at "
            "FROM semantic_lexicon WHERE starts_with(id, 'seed_')"
        )
        return {row[0]: row for row in cur.fetchall()}


# --- the seed landed ----------------------------------------------------------


def test_migration_seeds_exactly_the_declared_entries(datastore) -> None:
    _driver, conn, _ = datastore
    assert set(_seed_rows(conn)) == set(_SEED_BY_ID)


@pytest.mark.parametrize("entry", LEXICON_SEED_ENTRIES, ids=lambda e: e.id)
def test_each_seeded_row_matches_the_python_seed_field_for_field(
    datastore, entry
) -> None:
    # The pin. `LEXICON_SEED_ENTRIES` is the single source of truth and the SQL
    # is its transcription; without this test the two drift silently and every
    # later slice reads a constant the database does not agree with.
    _driver, conn, _ = datastore
    row = _seed_rows(conn)[entry.id]
    (
        _id, domain, entry_kind, surface_form, canonical_form, evidence,
        status, provenance, pii_redacted, hit_count, decider, decided_at,
    ) = row
    assert (domain, entry_kind) == (entry.domain, entry.entry_kind)
    assert (surface_form, canonical_form) == (entry.surface_form, entry.canonical_form)
    assert evidence == entry.evidence
    # Seeded vocabulary is DECIDED, not proposed: S05/S06 only ever read
    # confirmed rows, so a proposed seed would be invisible to them.
    assert status == "confirmed"
    assert provenance == "admin_manual"
    assert pii_redacted is False
    assert hit_count == 0
    # `admin_manual` must be attributable (D20). A migration has no account, so
    # the decider names the reviewable commit that carried the decision.
    assert decider == "seed:0024_lexicon_seed_domain_1"
    assert decided_at is not None


def test_the_spaced_tire_size_is_seeded_verbatim(datastore) -> None:
    _driver, conn, _ = datastore
    with conn.cursor() as cur:
        cur.execute(
            "SELECT surface_form, canonical_form FROM semantic_lexicon "
            "WHERE id = 'seed_lex_tire_size'"
        )
        assert cur.fetchone() == ("205 55 16", "205/55R16")


def test_the_seed_respects_the_unique_domain_surface_form_constraint(
    datastore,
) -> None:
    # Re-proposing a seeded pair through the governed path is a `conflict`, not
    # a duplicate row -- proof the seed sits under the same constraint as every
    # admin write rather than beside it.
    driver, _conn, _ = datastore
    seed = _SEED_BY_ID["seed_lex_company_toee"]
    result = execute_tool(
        tool="toee_semantic_lexicon",
        action="propose_lexicon_entry",
        params={
            "domain": seed.domain,
            "entry_kind": seed.entry_kind,
            "surface_form": seed.surface_form,
            "canonical_form": seed.canonical_form,
        },
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )
    assert not result.ok
    assert result.error_class == "conflict"


# --- the seed content survives the REAL write scanner, on real Postgres -------


@pytest.mark.parametrize("entry", LEXICON_SEED_ENTRIES, ids=lambda e: e.id)
def test_every_seeded_entry_survives_the_governed_write_path(datastore, entry) -> None:
    """Each seed row, pushed through ``propose_lexicon_entry`` for real.

    A seed that only ever arrives by ``INSERT`` never meets ``scan_lexicon_write``
    -- so the one thing worth proving would go untested. The domain is suffixed
    only because the real pair is already seeded and would (correctly) conflict;
    every scanned field is the seed's own.
    """
    driver, conn, _ = datastore
    result = execute_tool(
        tool="toee_semantic_lexicon",
        action="propose_lexicon_entry",
        params={
            "domain": f"{entry.domain}__scan_probe",
            "entry_kind": entry.entry_kind,
            "surface_form": entry.surface_form,
            "canonical_form": entry.canonical_form,
            "evidence": entry.evidence,
        },
        context=ToolExecutionContext(
            profile="internal_copilot",
            user_id="acct_admin_1",
            dispatch_route=TOOLS_DISPATCH_ROUTE,
        ),
        driver=driver,
    )
    assert result.ok, result.error_class
    assert result.data["provenance"] == "admin_manual"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT surface_form, evidence, pii_redacted FROM semantic_lexicon "
            "WHERE id = %s",
            (result.data["id"],),
        )
        surface_form, evidence, pii_redacted = cur.fetchone()
    # Nothing was rejected and nothing was scrubbed: the seed's evidence quotes
    # the entry's own forms, which the keep exemption spares (D2).
    assert surface_form == entry.surface_form
    assert evidence == entry.evidence
    assert pii_redacted is False
