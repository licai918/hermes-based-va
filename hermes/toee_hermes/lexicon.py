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

**Nothing here is APPLIED.** This module is the vocabulary and the rules, not the
seam. The seam is :mod:`toee_hermes.lexicon_seam` (S05): it consults the confirmed
entries, calls :func:`parse_tire_size` on product-read parameters, and verifies
the result against the live catalog before anything is asserted. Rendering
confirmed entries as a prompt glossary is S06 and is elsewhere again.

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
# optional R construction marker. Anchored end to end HERE: this normalizes a
# tool PARAMETER, it does not go fishing for a size inside prose.
#
# The pattern is public and the anchors are not, because the seam's catalog
# verification scans a shop-authored TITLE with the same grammar unanchored
# (`toee_hermes.lexicon_seam.tire_sizes_in`). Two copies of this regex is how
# "205/55 R16" ends up meaning one thing to the parser and another to the matcher.
TIRE_SIZE_PATTERN = r"(\d{3})[\s/-]*(\d{2})[\s/-]*[rR]?[\s/-]*(\d{2})"
_TIRE_SIZE_RE = re.compile(rf"^{TIRE_SIZE_PATTERN}$")


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
# Is this free-text note actually lexicon-shaped? (FR-18 / FR-19)
# --------------------------------------------------------------------------- #
#
# L6 is the free-text catch-all; L7 is the structured layer. A note that says
# "2055516 means 205/55R16" is an L7 alias wearing an L6 costume: it will never
# be applied by the deterministic seam, never earn a hit, and never reach the
# prompt glossary. FR-18 (S13) annotates it at PROPOSE time; FR-19 (S20) sweeps
# the CONFIRMED rows and raises a "graduate to L7?" review item. Both must agree
# on what "lexicon-shaped" means, so it is one function here rather than one
# regex each.
#
# Advisory ONLY. Nothing here reroutes, rewrites or auto-files anything (NFR-3):
# the output is a proposal for a human, and a false positive costs one dismissed
# inbox item.


@dataclass(frozen=True)
class LexiconShape:
    """The two halves an L6 note would become as an L7 entry."""

    surface_form: str
    canonical_form: str


# D16: named from day one, so S22's knob panel reads them instead of hunting
# magic numbers. Per D14 they move by deploy-time config commit.
#
# The bounds are what separates a MAPPING from a SENTENCE, and they are the whole
# discriminator: every seeded surface form is one token ("TOEE", "2055516") or
# three digit groups ("205 55 16"), while a procedure note is a clause. Without
# them, any sentence containing "means" reads as a mapping.
STRUCTURABLE_SURFACE_MAX_WORDS = 3
STRUCTURABLE_CANONICAL_MAX_WORDS = 6

# ponytail: two connectives, `=` and `means`, matching FR-18's own wording
# ("looks like `A = B` / `A means B`"). Deliberately not "stands for" / "is short
# for" / "aka" -- each one widens the false-positive surface, and the queue this
# feeds is worked by a human who can also just re-file a note the sweep missed.
# Add one the day a real note is observed to need it.
_STRUCTURABLE_RE = re.compile(
    r"^(?P<surface>\S.*?)\s*(?:=|\bmeans\b)\s*(?P<canonical>.*?\S)\.?$",
    re.IGNORECASE,
)


def structurable_shape(content: Any) -> Optional[LexiconShape]:
    """``LexiconShape`` when this note is a mapping, ``None`` when it is prose.

    Non-greedy on the left, so the FIRST connective splits the note: "size =
    205/55R16 = winter" is one mapping onto a value containing an equals sign,
    not two mappings. Splitting on the last one would move the boundary silently.

    ponytail: a regex plus two word bounds, no NLP and no model. Its known
    ceiling is a four-word sentence built around the connective ("the customer
    means well"), which reads as a mapping and produces one dismissible review
    item. Tighten the surface bound, or require the surface to be a single
    token, if that is ever observed in the real queue -- do not reach for a
    classifier.
    """
    if not isinstance(content, str):
        return None
    match = _STRUCTURABLE_RE.match(content.strip())
    if match is None:
        return None
    surface = match.group("surface").strip()
    canonical = match.group("canonical").strip()
    if not surface or not canonical:
        return None
    if len(surface.split()) > STRUCTURABLE_SURFACE_MAX_WORDS:
        return None
    if len(canonical.split()) > STRUCTURABLE_CANONICAL_MAX_WORDS:
        return None
    return LexiconShape(surface_form=surface, canonical_form=canonical)


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
        # NOT "all-season tires". The business will not say that phrase in this
        # market -- "加拿大冬天雪特别厚，我们不会称之为 ALL SEASON，避免出现
        # misleading information" -- and 0.0.6's D1 records the approved outward
        # label for the class: PASSENGER -> "passenger tires", never "all-season".
        # `canonical_form` is what hooks._default_rule_line renders into an
        # imperative ASK, so this field IS customer-facing wording, which is why it
        # is the one that had to change. Found by looking at /admin/lexicon during
        # the 0.0.5 sign-off walkthrough: a CONFIRMED row was telling the model it
        # could offer a Canadian customer all-season tires.
        canonical_form="passenger tires",
        evidence=(
            "Outside the winter window a bare tire size means the passenger class. "
            "Same confirm-first rule as the winter row: a default is a question. "
            "The wording is the business's approved label for the class -- the "
            "phrase 'all-season' is not used with customers in this market, because "
            "where winter capability is a safety question it reads as a claim the "
            "product does not support."
        ),
    ),
)

# The CONDITION token is rendered too, and that is 0.0.6's to settle.
# `hooks._default_rule_line` prints `Seasonal default (tire, all_season): ASK ...`,
# so the string `all_season` still reaches the prompt as the name of the *window*
# this rule applies in -- not as a product label, which is why it is a smaller
# problem than the canonical form was. Renaming the condition vocabulary means
# deciding what the facet values are called, which is exactly 0.0.6 D1's spec-layer
# work (customer wording IN, one approved label OUT). Recorded here rather than
# half-fixed, so the next reader does not assume this file already handled it.
