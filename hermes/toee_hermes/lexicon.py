"""L7 in-code normalizers + seeded domain #1 (0.0.5 S03, FR-2).

The seventh memory layer stores the domain language the business speaks. S01
built the governed store; this module supplies the two halves S01 deliberately
left out -- the **transformation rules** (pure functions) and the
**vocabulary** (the seeded rows) -- so that the iteration's headline behaviours
become possible: ``2055516``, ``205 55 16`` and ``20555r16`` all reach one
product; ``TOEE`` resolves to ``TOEE TIRE``; and in winter a bare tire size
implies winter tires *after the agent asks*.

**Dependency-free on purpose**, same discipline as
:func:`toee_hermes.gateway.normalize.normalize_e164` /
:func:`~toee_hermes.gateway.normalize.canonicalize_email`: stdlib only, no store,
no driver, no I/O. Both twins, the eval runner and the workbench BFF can import
it without dragging a database along.

**Nothing here is APPLIED.** Wiring these into tool parameters is S05; rendering
confirmed entries as a prompt glossary is S06. This module is the vocabulary and
the rules, not the seam.

## Why the three entry kinds are graded the way they are (FR-2)

``alias``
    Admin-free data: an exact surface-form -> canonical-form mapping over a
    finite vocabulary. Safe for an admin to add from a console with no deploy,
    because the worst a bad row can do is map one string to another.

``normalizer``
    The regex lives in **CODE** (:func:`parse_tire_size`). The row is only the
    per-domain **toggle** -- and the toggle is the ``status`` column the schema
    already has, not a new ``enabled`` column. Admin-editable regex is rejected
    for this iteration (PRD 6): a bad pattern typed into a console is a
    production incident with no review step, and the mapping is infinite anyway
    (every tire size that exists), so it could never be data.

``default_rule``
    A structured condition -> default -> **confirm**. Date-derived, overridable
    by an admin row, and it can never become a silent assumption -- see
    :class:`SeasonalDefault`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional

# Domains seeded by this slice. `domain` is an open vocabulary (S01's
# `_require_domain`): later domains are added by admins, not by a code change.
DOMAIN_TIRE = "tire"
DOMAIN_COMPANY = "company"

ENTRY_KIND_ALIAS = "alias"
ENTRY_KIND_NORMALIZER = "normalizer"
ENTRY_KIND_DEFAULT_RULE = "default_rule"

STATUS_CONFIRMED = "confirmed"


# --------------------------------------------------------------------------- #
# The tire-size normalizer -- regex in CODE (FR-2)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TireSize:
    """A parsed P-metric tire size. ``205/55R16`` is width/aspect R rim."""

    width_mm: int
    aspect_ratio: int
    rim_in: int

    @property
    def canonical(self) -> str:
        """The one spelling every notation collapses to."""
        return f"{self.width_mm}/{self.aspect_ratio}R{self.rim_in}"


# ponytail: plausibility bounds, not a catalogue. They exist so a 7-digit order
# number or local phone cannot masquerade as a size -- `1234567` would otherwise
# "parse" to a 67-inch rim. Widen here (a deploy-time config commit, D14) if the
# catalogue ever carries sizes outside passenger/light-truck ranges.
TIRE_WIDTH_MM_RANGE = (125, 395)
TIRE_ASPECT_RATIO_RANGE = (25, 85)
TIRE_RIM_IN_RANGE = (12, 26)

# Three digit groups (3-2-2) with optional `/`, `-` or space separators and an
# optional R construction marker. Anchored end to end: this normalizes a tool
# PARAMETER, it does not go fishing for a size inside prose.
_TIRE_SIZE_RE = re.compile(r"^(\d{3})[\s/-]*(\d{2})[\s/-]*[rR]?[\s/-]*(\d{2})$")


def _in_range(value: int, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= value <= bounds[1]


def parse_tire_size(value: Any) -> Optional[TireSize]:
    """The three-notation equivalence, or ``None`` when nothing is claimed.

    **What this handles.** A whole parameter value holding three digit groups in
    width-aspect-rim order: ``2055516``, ``205 55 16``, ``20555r16``,
    ``205/55R16``, ``205-55-16``, ``205/55/16``, in any case, with surrounding
    whitespace. All of them yield one :class:`TireSize`, so a customer who texts
    any of them reaches the same product.

    Also handled, because ``\\d`` is Unicode-wide and this module never turned
    that off: non-ASCII decimal digits. Arabic-Indic ``٢٠٥ ٥٥ ١٦`` and fullwidth
    ``２０５５５１６`` both parse, and the OUTPUT is still canonical ASCII
    ``205/55R16``. Harmless and arguably desirable, but named here because the
    value of this boundary section is that it is exhaustive.

    **What this deliberately does NOT handle**, each returning ``None`` so the
    caller leaves the value exactly as the customer wrote it:

    * free text -- ``"my size is 205 55 16"``. This is a parameter normalizer,
      not an extractor. Fishing a size out of prose is how a normalizer starts
      rewriting sentences it does not understand;
    * service-description prefixes and suffixes -- ``P205/55R16``,
      ``LT265/75R16``, ``205/55ZR16``, ``205/55R16 91V``. Each carries meaning
      (P-metric, light truck, speed rating, load index) that this slice does not
      model, and dropping it silently would change what the customer asked for;
    * flotation sizing -- ``31x10.50R15``. A different grammar entirely;
    * half-inch rims -- ``205/55R16.5``;
    * anything whose components fall outside the plausibility bounds above, and
      any 8-or-more-digit run, which is ambiguous and never guessed.

    The boundary is drawn on purpose: an honest ``None`` is strictly better than
    a confident mangling, because S05 applies the result to a real tool call.
    """
    if not isinstance(value, str):
        return None
    match = _TIRE_SIZE_RE.match(value.strip())
    if match is None:
        return None
    width, aspect, rim = (int(group) for group in match.groups())
    if not (
        _in_range(width, TIRE_WIDTH_MM_RANGE)
        and _in_range(aspect, TIRE_ASPECT_RATIO_RANGE)
        and _in_range(rim, TIRE_RIM_IN_RANGE)
    ):
        return None
    return TireSize(width, aspect, rim)


# --------------------------------------------------------------------------- #
# The seasonal default_rule -- date-derived, admin-overridable, always confirmed
# --------------------------------------------------------------------------- #

SEASON_WINTER = "winter"
SEASON_ALL_SEASON = "all_season"

# ponytail: the Ontario winter-tire window, as a calibration knob. A real
# market's season is a business call, not a fact -- move it here (a deploy-time
# config commit, D14) rather than deriving it from anything cleverer.
WINTER_MONTHS = frozenset({10, 11, 12, 1, 2, 3})

# `default_rule` rows are keyed by their CONDITION. Two shapes exist:
#   season=<season>  -- the default for that season (the seeded rows)
#   season=override  -- an admin-set row pinning the season outright
SEASON_CONDITION_PREFIX = "season="
SEASON_OVERRIDE_SURFACE_FORM = "season=override"

SOURCE_DATE_DERIVED = "date_derived"
SOURCE_ADMIN_OVERRIDE = "admin_override"


def current_season(today: date) -> str:
    """``winter`` or ``all_season``, derived from the date and nothing else."""
    return SEASON_WINTER if today.month in WINTER_MONTHS else SEASON_ALL_SEASON


@dataclass(frozen=True)
class SeasonalDefault:
    """A proposed seasonal default and where it came from.

    ``confirm_required`` is a read-only PROPERTY that is always ``True``, not a
    field with a convenient default. There is deliberately no constructor
    argument and no assignment that yields ``False``: a default_rule produces a
    question for the customer, never an assumption. A customer who wanted
    all-seasons and got quoted winters because the calendar said November is
    exactly the failure this shape makes unreachable -- S06 renders the
    confirmation, and it has nothing to branch on.
    """

    season: str
    value: str
    source: str

    @property
    def confirm_required(self) -> bool:
        return True


def _confirmed(
    entries: Iterable[dict[str, Any]], domain: str, entry_kind: str
) -> list[dict[str, Any]]:
    """Confirmed rows of one kind in one domain.

    Only ``confirmed`` rows ever act. A proposed row is inert by construction
    (S01) and a retired one is switched off -- the status lifecycle is the whole
    control surface, which is why no slice needed to widen the table.
    """
    return [
        entry
        for entry in entries
        if entry.get("status") == STATUS_CONFIRMED
        and entry.get("domain") == domain
        and entry.get("entry_kind") == entry_kind
    ]


def resolve_seasonal_default(
    entries: Iterable[dict[str, Any]],
    *,
    today: date,
    domain: str = DOMAIN_TIRE,
) -> Optional[SeasonalDefault]:
    """The default a bare tire size implies right now, or ``None``.

    Date-derived by :func:`current_season`, unless a confirmed
    ``season=override`` row is present -- an admin who wants the calendar
    ignored adds that one row from the console and it wins, with no deploy. Its
    value must be a season this module knows; anything else is a console typo
    and is ignored rather than passed through, because ``value`` is read out to
    the CUSTOMER as the confirmation question.

    ``None`` when no confirmed ``default_rule`` covers the resolved season:
    nothing is invented, and the agent simply asks what the customer wants.
    """
    rules = {
        entry.get("surface_form"): entry.get("canonical_form")
        for entry in _confirmed(entries, domain, ENTRY_KIND_DEFAULT_RULE)
    }
    override = rules.get(SEASON_OVERRIDE_SURFACE_FORM)
    if override not in (SEASON_WINTER, SEASON_ALL_SEASON):
        override = None  # a typo is not an instruction -- fall back to the calendar
    season = override or current_season(today)
    value = rules.get(f"{SEASON_CONDITION_PREFIX}{season}")
    if not value:
        return None
    return SeasonalDefault(
        season=season,
        value=value,
        source=SOURCE_ADMIN_OVERRIDE if override else SOURCE_DATE_DERIVED,
    )


def normalizer_enabled(entries: Iterable[dict[str, Any]], domain: str) -> bool:
    """Whether this domain's in-code normalizer is switched on.

    The toggle is the ``status`` of the domain's ``normalizer`` row -- no
    ``enabled`` column was added, because the schema already had one that means
    exactly this and a concurrent slice owns the table's shape.

    ponytail: one normalizer per domain, so the row needs no key. Give the row a
    key in ``surface_form`` and match on it the day a domain has two.
    """
    return bool(_confirmed(entries, domain, ENTRY_KIND_NORMALIZER))


# --------------------------------------------------------------------------- #
# Seeded domain #1 -- the single source of truth for migration 0024
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SeedEntry:
    """One seeded ``semantic_lexicon`` row.

    Fields match the store's columns so a row read back is comparable to the
    seed field for field -- which is what pins the SQL in
    ``hermes-runtime/migrations/0024_lexicon_seed_domain_1.sql`` to this tuple.
    """

    id: str
    domain: str
    entry_kind: str
    surface_form: str
    canonical_form: str
    evidence: str


LEXICON_SEED_ENTRIES: tuple[SeedEntry, ...] = (
    SeedEntry(
        id="seed_lex_tire_size",
        domain=DOMAIN_TIRE,
        entry_kind=ENTRY_KIND_NORMALIZER,
        # The flagship. `205 55 16` matches the write scanner's phone pattern,
        # which is why D2 split scan_injection from scan_pii: surface forms get
        # the injection leg only. Seeding it is the proof that the split holds.
        surface_form="205 55 16",
        canonical_form="205/55R16",
        evidence=(
            "Toggle row for the in-code tire-size normalizer (parse_tire_size). "
            "The pattern lives in code, never in this row; retiring this entry "
            "switches tire-size normalization off for the whole tire domain. "
            "The forms are the canonical exemplar: 205 55 16, 2055516 and "
            "20555r16 all parse to 205/55R16."
        ),
    ),
    SeedEntry(
        id="seed_lex_company_toee",
        domain=DOMAIN_COMPANY,
        entry_kind=ENTRY_KIND_ALIAS,
        surface_form="TOEE",
        canonical_form="TOEE TIRE",
        evidence=(
            "Customers write TOEE for TOEE TIRE. An exact mapping over a finite "
            "vocabulary, so it is data an admin adds from the console with no "
            "deploy -- the reason alias is the least deterministic-privileged "
            "of the three kinds."
        ),
    ),
    SeedEntry(
        id="seed_lex_season_winter",
        domain=DOMAIN_TIRE,
        entry_kind=ENTRY_KIND_DEFAULT_RULE,
        surface_form=f"{SEASON_CONDITION_PREFIX}{SEASON_WINTER}",
        canonical_form="winter tires",
        evidence=(
            "In the winter window a bare tire size means winter tires. The "
            "condition is date-derived by current_season(); an admin pins it by "
            "adding a confirmed season=override row. The agent must ASK before "
            "quoting -- this rule proposes, it never assumes."
        ),
    ),
    SeedEntry(
        id="seed_lex_season_all_season",
        domain=DOMAIN_TIRE,
        entry_kind=ENTRY_KIND_DEFAULT_RULE,
        surface_form=f"{SEASON_CONDITION_PREFIX}{SEASON_ALL_SEASON}",
        canonical_form="all-season tires",
        evidence=(
            "Outside the winter window a bare tire size means all-season tires. "
            "Same confirm-first rule as the winter row: a default is a question."
        ),
    ),
)
