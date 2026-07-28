"""0.0.5 S03 (FR-2): the in-code normalizers + seeded domain #1.

The three L7 entry kinds become real here, graded by how much determinism each
deserves:

* ``alias`` -- pure data (``TOEE`` -> ``TOEE TIRE``). An admin adds one from the
  console with no deploy.
* ``normalizer`` -- the regex lives in CODE (:func:`parse_tire_size`); the row is
  only the per-domain TOGGLE. Admin-editable regex is out of scope by decision
  (PRD 6): a bad regex typed into a console is a production incident with no
  review step.
* ``default_rule`` -- a structured condition -> default -> **confirm**. The
  seasonal default is the example, and it can never become a silent assumption.

Nothing here APPLIES a normalizer to a turn: parameter normalization is S05 and
the prompt glossary is S06. This slice provides the vocabulary and the
transformation rules only.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

import pytest

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.semantic_lexicon import (
    LEXICON_ENTRY_KINDS,
    create_semantic_lexicon_mock_handlers,
)
from toee_hermes.execute import execute_tool
from toee_hermes.lexicon import (
    DOMAIN_COMPANY,
    DOMAIN_TIRE,
    LEXICON_SEED_ENTRIES,
    SEASON_ALL_SEASON,
    SEASON_OVERRIDE_SURFACE_FORM,
    SEASON_WINTER,
    SeasonalDefault,
    TireSize,
    current_season,
    normalizer_enabled,
    parse_tire_size,
    resolve_seasonal_default,
)
from toee_hermes.tool_gate import TOOLS_DISPATCH_ROUTE, ToolExecutionContext

# --- the tire-size normalizer: three notations, ONE TireSize ------------------


@pytest.mark.parametrize(
    "notation",
    ("2055516", "205 55 16", "20555r16", "20555R16", "205/55R16", "205-55-16",
     "205/55/16", "  205 55 16  ",
     # `\d` is Unicode-wide, so non-ASCII decimal digits parse too and the
     # OUTPUT is still canonical ASCII. Claimed in parse_tire_size's boundary
     # section, so it is pinned here rather than left as an accident.
     "٢٠٥ ٥٥ ١٦",   # Arabic-Indic 205 55 16
     "２０５５５１６"),    # fullwidth 2055516
)
def test_every_accepted_notation_parses_to_the_same_tire_size(notation: str) -> None:
    # THE headline behaviour of the iteration (US2): a customer texting any of
    # these reaches the same product.
    assert parse_tire_size(notation) == TireSize(205, 55, 16)


def test_the_three_flagship_notations_are_mutually_equal_and_canonical() -> None:
    packed = parse_tire_size("2055516")
    spaced = parse_tire_size("205 55 16")
    lowercase_r = parse_tire_size("20555r16")
    assert packed == spaced == lowercase_r
    assert packed is not None and packed.canonical == "205/55R16"


@pytest.mark.parametrize(
    "value",
    (
        "4165550199",        # a 10-digit phone
        "+14165550199",      # E.164
        "416-555-0199",
        "10311",             # an order number
        "2026-07-27",        # a date
        "1234567890",
        "",
        "   ",
        "205/55",            # no rim
        "205/55R16 91V",     # load index + speed rating -- not claimed
        "P205/55R16",        # P-metric prefix -- not claimed
        "LT265/75R16",       # load-range prefix -- not claimed
        "205/55ZR16",        # speed-rated Z -- not claimed
        "31x10.50R15",       # flotation sizing -- a different grammar entirely
        "205/55R16.5",       # half-inch rim
        "my size is 205 55 16",   # prose: the normalizer takes a PARAMETER
        "5551234",           # width 555 is not a tire width
        "1234567",           # rim 67 is not a rim diameter
        "20555165",          # 8 digits: ambiguous, never guessed
    ),
)
def test_strings_the_normalizer_does_not_claim_return_none(value: str) -> None:
    # Returning None means S05 leaves the parameter EXACTLY as the customer
    # wrote it. Silently mangling input it does not understand would be worse
    # than not normalizing at all.
    assert parse_tire_size(value) is None


def test_out_of_range_components_are_rejected_not_canonicalized() -> None:
    assert parse_tire_size("999 99 99") is None
    assert parse_tire_size("100 20 10") is None


# --- current_season: deterministic given a date -------------------------------


@pytest.mark.parametrize("month", (10, 11, 12, 1, 2, 3))
def test_winter_months_are_winter(month: int) -> None:
    assert current_season(date(2026, month, 15)) == SEASON_WINTER


@pytest.mark.parametrize("month", (4, 5, 6, 7, 8, 9))
def test_every_other_month_is_all_season(month: int) -> None:
    assert current_season(date(2026, month, 15)) == SEASON_ALL_SEASON


def test_current_season_is_pure_and_deterministic() -> None:
    day = date(2026, 11, 3)
    assert current_season(day) == current_season(day) == SEASON_WINTER


# --- the seasonal default_rule: a QUESTION, never an assumption ---------------


def _confirmed_seed_rows(**overrides):
    rows = [{**asdict(entry), "status": "confirmed"} for entry in LEXICON_SEED_ENTRIES]
    for row in rows:
        row.update(overrides)
    return rows


def test_a_seasonal_default_always_requires_confirmation() -> None:
    # US3's whole point. A customer who wanted all-seasons and got quoted
    # winters because the calendar said November is the failure this prevents.
    default = resolve_seasonal_default(_confirmed_seed_rows(), today=date(2026, 11, 3))
    assert default is not None
    assert default.season == SEASON_WINTER
    assert default.value == "winter tires"
    assert default.source == "date_derived"
    assert default.confirm_required is True


def test_confirm_required_cannot_be_switched_off() -> None:
    # Not a field with a default -- a read-only property. There is no
    # constructor argument, no keyword, and no attribute assignment that
    # produces a seasonal default the agent may apply silently.
    #
    # Asserting ONLY that assignment raises would pass for the wrong reason:
    # dataclasses.FrozenInstanceError subclasses AttributeError, so a plain
    # frozen field `confirm_required: bool = True` raises IDENTICALLY here while
    # still permitting SeasonalDefault(..., confirm_required=False) at
    # construction. So pin the two claims the comment above actually makes.
    assert "confirm_required" not in SeasonalDefault.__dataclass_fields__
    with pytest.raises(TypeError):
        SeasonalDefault(  # type: ignore[call-arg]
            season=SEASON_WINTER,
            value="winter tires",
            source="date_derived",
            confirm_required=False,
        )

    default = resolve_seasonal_default(_confirmed_seed_rows(), today=date(2026, 11, 3))
    assert default is not None
    with pytest.raises(AttributeError):
        default.confirm_required = False  # type: ignore[misc]


def test_outside_winter_the_date_derived_default_is_all_season() -> None:
    default = resolve_seasonal_default(_confirmed_seed_rows(), today=date(2026, 7, 27))
    assert default is not None
    assert default.season == SEASON_ALL_SEASON
    assert default.value == "all-season tires"
    assert default.confirm_required is True


def test_an_admin_override_row_beats_the_date_derived_season() -> None:
    # The admin's escape hatch: one extra confirmed default_rule row pins the
    # season regardless of the calendar. No deploy, no code change.
    rows = _confirmed_seed_rows()
    rows.append(
        {
            "domain": DOMAIN_TIRE,
            "entry_kind": "default_rule",
            "surface_form": SEASON_OVERRIDE_SURFACE_FORM,
            "canonical_form": SEASON_ALL_SEASON,
            "status": "confirmed",
        }
    )

    default = resolve_seasonal_default(rows, today=date(2026, 11, 3))  # winter

    assert default is not None
    assert default.season == SEASON_ALL_SEASON
    assert default.source == "admin_override"
    # ...and an override is still a proposal, never an assumption.
    assert default.confirm_required is True


def test_an_unconfirmed_override_row_does_not_win() -> None:
    rows = _confirmed_seed_rows()
    rows.append(
        {
            "domain": DOMAIN_TIRE,
            "entry_kind": "default_rule",
            "surface_form": SEASON_OVERRIDE_SURFACE_FORM,
            "canonical_form": SEASON_ALL_SEASON,
            "status": "proposed",
        }
    )
    default = resolve_seasonal_default(rows, today=date(2026, 11, 3))
    assert default is not None
    assert default.season == SEASON_WINTER
    assert default.source == "date_derived"


@pytest.mark.parametrize("typo", ("override", "Winter", "wintre", "all season", ""))
def test_an_override_that_is_not_a_known_season_is_ignored(typo: str) -> None:
    # Every other typo in this table fails safe. This one did not: an override
    # row whose canonical_form is the literal "override" used to yield
    # SeasonalDefault(season="override", value="override") -- and the value is
    # what S06 reads out to the CUSTOMER as the confirmation question. An
    # override the code cannot recognise is a typo, not an instruction.
    rows = _confirmed_seed_rows()
    rows.append(
        {
            "domain": DOMAIN_TIRE,
            "entry_kind": "default_rule",
            "surface_form": SEASON_OVERRIDE_SURFACE_FORM,
            "canonical_form": typo,
            "status": "confirmed",
        }
    )

    default = resolve_seasonal_default(rows, today=date(2026, 11, 3))

    assert default is not None
    assert default.season == SEASON_WINTER
    assert default.value == "winter tires"
    assert default.source == "date_derived"


def test_no_confirmed_default_rule_yields_no_default_rather_than_a_guess() -> None:
    assert resolve_seasonal_default([], today=date(2026, 11, 3)) is None
    assert (
        resolve_seasonal_default(
            _confirmed_seed_rows(status="proposed"), today=date(2026, 11, 3)
        )
        is None
    )


# --- the normalizer TOGGLE lives in the row's status, not in a new column -----


def test_a_confirmed_normalizer_row_enables_the_domains_normalizer() -> None:
    assert normalizer_enabled(_confirmed_seed_rows(), DOMAIN_TIRE) is True


def test_toggling_the_row_off_disables_the_normalizer_for_that_domain() -> None:
    # No enable/params columns were added: the existing status lifecycle IS the
    # toggle. Retiring the row turns tire-size parsing off for the tire domain.
    retired = _confirmed_seed_rows(status="retired")
    assert normalizer_enabled(retired, DOMAIN_TIRE) is False


def test_a_domain_with_no_normalizer_row_is_not_enabled() -> None:
    assert normalizer_enabled(_confirmed_seed_rows(), DOMAIN_COMPANY) is False
    assert normalizer_enabled(_confirmed_seed_rows(), "wheel") is False


# --- the seed itself ----------------------------------------------------------


def test_the_seed_covers_all_three_entry_kinds_with_legal_values() -> None:
    kinds = {entry.entry_kind for entry in LEXICON_SEED_ENTRIES}
    assert kinds == {"alias", "normalizer", "default_rule"}
    # The kind vocabulary is owned by the store module; this pins the pure
    # module's plain strings to it rather than letting the two drift.
    assert kinds <= set(LEXICON_ENTRY_KINDS)


def test_the_company_alias_is_seeded_as_pure_data() -> None:
    alias = next(e for e in LEXICON_SEED_ENTRIES if e.entry_kind == "alias")
    assert (alias.domain, alias.surface_form, alias.canonical_form) == (
        DOMAIN_COMPANY,
        "TOEE",
        "TOEE TIRE",
    )


def test_seed_ids_are_unique_and_namespaced() -> None:
    ids = [entry.id for entry in LEXICON_SEED_ENTRIES]
    assert len(ids) == len(set(ids))
    # The `seed_` namespace is what lets a test count rows a TEST wrote without
    # counting the schema's own seeded baseline.
    assert all(entry_id.startswith("seed_") for entry_id in ids)


def test_the_seed_has_no_duplicate_domain_surface_form_pair() -> None:
    pairs = [(e.domain, e.surface_form) for e in LEXICON_SEED_ENTRIES]
    assert len(pairs) == len(set(pairs)), "UNIQUE(domain, surface_form) would reject"


# --- the seed lands through the REAL governed write path ----------------------


def _admin_ctx() -> ToolExecutionContext:
    """The deterministic admin BFF route (ADR-0141) -- provenance admin_manual."""
    return ToolExecutionContext(
        profile="internal_copilot",
        user_id="acct_admin_1",
        dispatch_route=TOOLS_DISPATCH_ROUTE,
    )


def _propose_seed(driver, entry):
    return execute_tool(
        tool="toee_semantic_lexicon",
        action="propose_lexicon_entry",
        params={
            "domain": entry.domain,
            "entry_kind": entry.entry_kind,
            "surface_form": entry.surface_form,
            "canonical_form": entry.canonical_form,
            "evidence": entry.evidence,
        },
        context=_admin_ctx(),
        driver=driver,
    )


@pytest.mark.parametrize(
    "entry", LEXICON_SEED_ENTRIES, ids=lambda e: e.id
)
def test_every_seeded_entry_survives_the_governed_write_scan(entry) -> None:
    # The seed DOES bypass the scanner in production: migration 0024 is a raw
    # INSERT and never calls scan_lexicon_write. So the guarantee that these
    # exact constants would survive the governed path is carried HERE (and on
    # the PG twin), not by the migration. D2 split scan_injection from scan_pii
    # precisely so the rows below are storable.
    driver = MockDriver(create_semantic_lexicon_mock_handlers())
    result = _propose_seed(driver, entry)
    assert result.ok is True, result.error_class
    assert result.data["provenance"] == "admin_manual"
    assert result.data["surface_form"] == entry.surface_form
    assert result.data["canonical_form"] == entry.canonical_form


def test_the_spaced_tire_size_survives_the_write_scanner() -> None:
    # `205 55 16` matches the shared scanner's _PHONE_RE. Before D2's split it
    # was policy_blocked -- the flagship seeded surface form of the whole
    # iteration, rejected by its own guard. This is the regression pin.
    seed = next(e for e in LEXICON_SEED_ENTRIES if e.surface_form == "205 55 16")
    driver = MockDriver(create_semantic_lexicon_mock_handlers())

    result = _propose_seed(driver, seed)

    assert result.ok is True, result.error_class
    assert result.data["surface_form"] == "205 55 16"
    # The evidence quotes the surface form; the keep exemption spares it rather
    # than redacting the entry down to something an admin cannot decide on...
    assert result.data["pii_redacted"] is False
    # ...and the waiver is named, not silent.
    assert "205 55 16" in result.data["pii_keep_exempt"]


def test_the_whole_seed_lands_in_one_store_without_a_conflict() -> None:
    driver = MockDriver(create_semantic_lexicon_mock_handlers())
    for entry in LEXICON_SEED_ENTRIES:
        assert _propose_seed(driver, entry).ok is True, entry.id

    listed = execute_tool(
        tool="toee_semantic_lexicon",
        action="list_lexicon_entries",
        params={},
        context=_admin_ctx(),
        driver=driver,
    )
    assert len(listed.data["entries"]) == len(LEXICON_SEED_ENTRIES)
