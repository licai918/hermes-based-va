"""L7 applied: the deterministic product-read seam (0.0.5 S05, FR-5).

S01 built the governed store, S02 the human gate, S03 the in-code rules and the
seeded vocabulary. Nothing APPLIED any of it. This module is the application's
deterministic half -- ``2055516``, ``205 55 16`` and ``20555r16`` all reach one
product, decided by a regex and an exact map rather than by a model. (The prompt
glossary, for what determinism cannot cover, is S06 and is not here.)

## The shape, and why it is this shape

**A per-handler helper, never dispatch middleware (FR-5's "grill-locked hook
point").** Middleware would rewrite the parameters of every tool in the catalog
on a guess about which ones carry domain language. :func:`resolve_product_query`
is called explicitly by the two product-read actions, in both driver twins, and
by nothing else.

**ONE helper, both twins (NFR-7).** The mock handler and the live ComposioDriver
call the same function with the same matcher; the only twin-specific part is the
``lookup`` callable that reaches that twin's catalog. Parity is held by
``hermes/tests/test_lexicon_seam.py``'s twin tests, which drive the same notation
through both and assert one answer -- not by intent.

**Only ``confirmed`` entries act (PAC-2's deterministic half).** ``proposed``,
``rejected`` and ``retired`` rows can never change a customer-facing result.
Enforced HERE as well as in the store's reader, because a reader that forgets is
the difference between "an admin has not approved this yet" and "an admin
approved this".

**A parsed size is verified against the live catalog before it is asserted.**
Normalizing ``20555r16`` into a size the catalog does not carry and then
confidently searching for it is worse than not normalizing at all: the customer's
own words are replaced by a canonical nobody can buy, and the empty result reads
as "we don't have it". So the normalized query runs first; if it finds nothing,
the RAW query runs and the canonical is not asserted (``clarify``). S06 owns
telling the customer; this half's job is refusing to assert.

**Fail-open, always (NFR-5).** A vocabulary that cannot be read, a cache miss
against an unreachable database, a hit sink that raises -- every one of them
degrades to "the raw parameters pass through unchanged". Memory never stalls a
reply and never fails one.

**Hit accounting is append-only (D6).** :meth:`LexiconVocabulary.record_hits` is
fire-and-forget and NEVER updates a counter on the lexicon row: a per-turn
``UPDATE`` over the small hot set of confirmed entries is textbook row-lock
contention on the reply path. ``semantic_lexicon.hit_count`` is a materialized
column a scheduled rollup maintains (``hermes_runtime.lexicon_hits``).
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Sequence

from .lexicon import (
    DOMAIN_TIRE,
    ENTRY_KIND_ALIAS,
    ENTRY_KIND_NORMALIZER,
    STATUS_CONFIRMED,
    TIRE_SIZE_PATTERN,
    parse_tire_size,
)

logger = logging.getLogger(__name__)

# The two product-read actions, and the parameter on each that can carry the
# customer's own words. Explicit rather than "every string param": `product_id`
# is a vendor gid and `order_number` is an identifier -- rewriting either would
# be the normalizer inventing meaning it was never given.
#
# `get_product.sku` is here even though the model normally sources it from a
# previous `search_products` result (see plugin/schemas.py), because "normally"
# is not "always" and the catalog check below makes the seam safe either way: a
# normalized sku that finds nothing loses to the raw one it was handed.
PRODUCT_QUERY_PARAM_KEYS: dict[str, tuple[str, ...]] = {
    "search_products": ("query",),
    "get_product": ("sku",),
}

# The searchable fields of a product, in both twins' shaped contract. ONE tuple
# so the mock's filter and the live driver's cannot drift into two different
# ideas of "matches" -- which is exactly how a normalization that works in the
# mock ships broken (the S15/S21 lesson, NFR-7).
PRODUCT_MATCH_FIELDS = ("title", "sku")


@dataclass(frozen=True)
class ProductQueryNormalization:
    """What the confirmed vocabulary would make of one call's parameters."""

    params: dict[str, Any]
    # The canonical form the vocabulary produced, or None when nothing applied.
    # Present even on the downgrade path: the caller needs to know a canonical
    # was ATTEMPTED to take a clarify posture over it.
    canonical: Optional[str]
    # The confirmed entries credited with this application. Empty unless a
    # canonical was produced; still empty until the catalog verifies it.
    entry_ids: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.canonical is not None


@dataclass(frozen=True)
class ProductQueryResult:
    """One product read, plus what the lexicon did or declined to do to it."""

    value: Any
    canonical: Optional[str] = None
    # The canonical was catalog-verified and is what produced ``value``.
    applied: bool = False
    # A canonical was produced but no live product matched it, so ``value`` came
    # from the customer's RAW term and the canonical is NOT asserted.
    clarify: bool = False
    entry_ids: tuple[str, ...] = ()


# The SAME grammar as the parameter parser, unanchored, for reading a size out of
# a shop-authored title or sku. The digit lookarounds preserve the parser's
# refusal of an 8-or-more-digit run, so an order number embedded in a title can
# still never masquerade as a size.
_TIRE_SIZE_IN_TEXT_RE = re.compile(rf"(?<!\d){TIRE_SIZE_PATTERN}(?!\d)")


def tire_sizes_in(text: Any) -> set[str]:
    """Canonical forms of every tire size spelled anywhere in ``text``.

    This is an EXTRACTOR, which :func:`~toee_hermes.lexicon.parse_tire_size`
    deliberately is not -- and the difference is which side of the seam it reads.
    The parser handles the customer's parameter, where fishing a size out of prose
    would rewrite words nobody chose. This reads the CATALOG, where nothing is
    rewritten: the only question asked of the answer is "does this product carry
    the size we already parsed", so a wrong extraction costs a non-match, never a
    mangled query. Every candidate is re-validated by the parser, plausibility
    bounds included.
    """
    if not isinstance(text, str):
        return set()
    return {
        size.canonical
        for match in _TIRE_SIZE_IN_TEXT_RE.finditer(text)
        if (size := parse_tire_size(match.group())) is not None
    }


def is_canonical_size(term: Any) -> bool:
    """Is ``term`` exactly a canonical tire size (``205/55R16``)?

    True only of the vocabulary's own output and of a customer who happened to
    type it that way -- never of ``20555r16``, which is a notation the confirmed
    normalizer row decides about. That asymmetry is what keeps the catalog-side
    tolerance below from quietly becoming ungoverned normalization.
    """
    size = parse_tire_size(term)
    return size is not None and size.canonical == term.strip()


def product_matches(term: Optional[str], product: dict[str, Any]) -> bool:
    """Does ``product`` match ``term``? The one matcher both twins use.

    Case-insensitive substring over :data:`PRODUCT_MATCH_FIELDS`, which is what
    the mock twin has always done. An empty/absent term matches everything --
    ``search_products`` with no query lists the catalog.

    **Plus, for a canonical size only, the catalog's own spelling.** The seam
    parses the customer's text; a raw substring made the catalog's spelling the
    contract, so a shop that writes ``205/55 R16`` or ``205-55-16`` -- or puts the
    size in the sku -- fails verification, the seam downgrades to the raw
    notation, that fails too, and the agent reports a tire on the shelf as one we
    do not carry. So the size is parsed out of the title/sku and compared, rather
    than being required to match our spelling character for character.

    Strictly additive: the substring is tried first and still decides everything
    it decided before.
    """
    if not isinstance(term, str) or not term:
        return True
    needle = term.strip().casefold()
    if not needle:
        return True
    if any(
        needle in value.casefold()
        for field in PRODUCT_MATCH_FIELDS
        if isinstance(value := product.get(field), str)
    ):
        return True
    if not is_canonical_size(term):
        return False
    canonical = term.strip()
    return any(
        canonical in tire_sizes_in(product.get(field))
        for field in PRODUCT_MATCH_FIELDS
    )


def filter_products(
    term: Optional[str], products: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """``products`` narrowed to ``term`` by :func:`product_matches`."""
    return [item for item in products if product_matches(term, item)]


def _confirmed_rows(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in entries if row.get("status") == STATUS_CONFIRMED]


def normalize_product_query(
    action: str,
    params: dict[str, Any],
    entries: Iterable[dict[str, Any]],
) -> ProductQueryNormalization:
    """Pure: the confirmed alias map + the enabled in-code normalizers, applied.

    Precedence is alias-then-normalizer, because an alias is an admin's explicit
    statement about one exact string and the normalizer is a pattern: where both
    could fire, the human's row wins.

    Returns the parameters unchanged (``canonical is None``) when nothing
    confirmed applies, when the value is already canonical -- rewriting a string
    to itself is not an application and must not earn a hit -- or when anything
    at all goes wrong. Never raises: this sits on the reply path (NFR-5).
    """
    keys = PRODUCT_QUERY_PARAM_KEYS.get(action, ())
    unchanged = ProductQueryNormalization(params, None)
    if not keys:
        return unchanged
    try:
        confirmed = _confirmed_rows(entries)
        # Aliases are exact string mappings over a finite vocabulary, so the map
        # spans every domain: "TOEE" means "TOEE TIRE" whichever product read
        # sees it. ponytail: no domain scoping -- UNIQUE(domain, surface_form)
        # allows a cross-domain collision only in theory, and no shipped domain
        # has one. Scope it here the day two domains disagree about one string.
        aliases = {
            str(row.get("surface_form", "")).strip().casefold(): row
            for row in confirmed
            if row.get("entry_kind") == ENTRY_KIND_ALIAS and row.get("canonical_form")
        }
        tire_normalizer = next(
            (
                row
                for row in confirmed
                if row.get("entry_kind") == ENTRY_KIND_NORMALIZER
                and row.get("domain") == DOMAIN_TIRE
            ),
            None,
        )
        for key in keys:
            value = params.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            alias = aliases.get(value.strip().casefold())
            if alias is not None:
                canonical, row = str(alias["canonical_form"]), alias
            elif tire_normalizer is not None and (size := parse_tire_size(value)):
                canonical, row = size.canonical, tire_normalizer
            else:
                continue
            if canonical == value:
                return unchanged
            entry_id = row.get("id")
            return ProductQueryNormalization(
                {**params, key: canonical},
                canonical,
                (str(entry_id),) if entry_id else (),
            )
        return unchanged
    except Exception as exc:  # noqa: BLE001 - fail-open, never fail a reply
        logger.warning(
            "Lexicon normalization skipped action=%s error_type=%s; "
            "the raw parameters pass through",
            action,
            type(exc).__name__,
        )
        return unchanged


def resolve_product_query(
    action: str,
    params: dict[str, Any],
    *,
    lookup: Callable[[dict[str, Any]], Any],
    vocabulary: Optional["LexiconVocabulary"],
) -> ProductQueryResult:
    """THE shared per-handler seam. Both product-read twins call exactly this.

    ``lookup`` runs one product read for a given parameter set and returns that
    twin's own result (a list for ``search_products``, a product dict or ``None``
    for ``get_product``). It is called ONCE when nothing normalized, and at most
    TWICE when something did -- the second call is the downgrade to the raw
    parameters, and only happens when the canonical matched no live product.

    A ``lookup`` that RAISES on the normalized parameters is treated as a miss,
    not as an error: a normalization must never turn a lookup that would have
    worked into a failure. The raw attempt's exception is the caller's to handle,
    exactly as it was before this seam existed.
    """
    entries = vocabulary.entries() if vocabulary is not None else ()
    normalization = normalize_product_query(action, params, entries)
    if not normalization.changed:
        return ProductQueryResult(lookup(params))

    try:
        found = lookup(normalization.params)
    except Exception:  # noqa: BLE001 - a normalized miss is a miss, not a fault
        found = None
    if found:
        if vocabulary is not None:
            vocabulary.record_hits(normalization.entry_ids)
        return ProductQueryResult(
            found,
            normalization.canonical,
            applied=True,
            entry_ids=normalization.entry_ids,
        )

    # Catalog verification failed. Never assert an unverified canonical: run the
    # customer's own term, credit nobody, and report the clarify posture.
    logger.info(
        "Lexicon canonical %r matched no live product for %s; falling back to the "
        "raw parameters",
        normalization.canonical,
        action,
    )
    return ProductQueryResult(lookup(params), normalization.canonical, clarify=True)


# --------------------------------------------------------------------------- #
# The process-level vocabulary cache
# --------------------------------------------------------------------------- #


class LexiconVocabulary:
    """Confirmed L7 entries, cached per process and keyed by ``lexicon_version``.

    ``version`` is S02's shipped ``lexicon_version`` -- ``MAX(updated_at)`` over
    the whole table, which moves on every add/confirm/reject/retire/edit and can
    never go backwards. Consumed rather than reinvented: a second notion of
    freshness is a second thing to keep true.

    **What happens on the first request after a bump.** The version probe is a
    single indexed read and runs on every request; the full confirmed set is
    re-read only when the probe reports a different version. So the first request
    after any governed decision pays one extra small SELECT and immediately sees
    the new vocabulary -- there is no staleness window and no TTL to tune. Every
    request until the next decision reads process memory.

    **Failure serves the last good vocabulary, and an empty one if there is
    none.** One rule, not two: a probe that raises, a load that raises, or a
    first-ever load that fails all degrade to "whatever we already had", which
    for a cold process is nothing at all and therefore raw pass-through (NFR-5).
    Confirmed vocabulary changes on an admin's timescale, so serving the last
    good set through a database blip is strictly better than switching
    normalization off mid-conversation.

    The rollup that maintains ``hit_count`` is NOT here and must never be: see
    :meth:`record_hits`.
    """

    def __init__(
        self,
        *,
        version: Callable[[], Optional[str]],
        confirmed: Callable[[], list[dict[str, Any]]],
        record_hits: Optional[Callable[[Sequence[str]], None]] = None,
    ) -> None:
        self._version = version
        self._confirmed = confirmed
        self._record_hits = record_hits
        # Guards the SWAP and nothing else: three assignments, no I/O, no waiting.
        # Both callables take a pooled connection and do a Postgres round trip, so
        # holding this across either one would serialize concurrent turns on a
        # mutex for the length of a query -- and a thread that saturates the pool
        # would then wait for a connection while holding it. That is D6's own
        # hazard (something on the reply path that can stall it, NFR-5) rebuilt one
        # layer up. Pinned by
        # `test_neither_the_version_probe_nor_the_load_holds_the_process_lock`.
        self._lock = threading.Lock()
        self._cached: tuple[dict[str, Any], ...] = ()
        self._cached_version: Optional[str] = None
        self._primed = False

    def entries(self) -> tuple[dict[str, Any], ...]:
        """The confirmed rows, from cache unless the version moved.

        Both database calls run OUTSIDE the lock; only the swap is inside it.
        ponytail: so a version bump can have two concurrent turns each load the
        confirmed set once, and the loser's work is discarded. That costs one
        duplicated SELECT on an admin's timescale, which is the right trade
        against every turn queueing behind one -- add single-flight only if a
        trace ever shows a bump storm.
        """
        try:
            version = self._version()
        except Exception as exc:  # noqa: BLE001
            self._warn("version probe", exc)
            return self._cached
        if self._primed and version == self._cached_version:
            return self._cached
        try:
            rows = tuple(self._confirmed())
        except Exception as exc:  # noqa: BLE001
            self._warn("load", exc)
            return self._cached
        with self._lock:
            # Rows BEFORE version, and version before `_primed`: readers outside
            # the lock must never see a new version paired with the old rows,
            # which would pin the stale set until the next bump. The reverse
            # (an old version beside new rows) costs one redundant reload.
            self._cached = rows
            self._cached_version = version
            self._primed = True
        return rows

    def record_hits(self, entry_ids: Sequence[str]) -> None:
        """Fire-and-forget: note that these entries just changed a real query.

        **Append-only, never an in-turn UPDATE (D6).** The sink writes a hit
        EVENT; ``semantic_lexicon.hit_count`` is materialized from those events
        by a scheduled rollup. Updating the counter here would take a row lock on
        the small hot set of confirmed entries on every turn -- the contention
        NFR-5 forbids on the reply path -- and would drag ``updated_at`` with it,
        which the console reads as "an admin edited this".

        Swallows everything. A hit that is not recorded costs a retirement
        heuristic some precision months from now; an exception here would cost a
        customer their reply.
        """
        if not entry_ids or self._record_hits is None:
            return
        try:
            self._record_hits(list(entry_ids))
        except Exception as exc:  # noqa: BLE001
            self._warn("hit record", exc)

    @staticmethod
    def _warn(what: str, exc: BaseException) -> None:
        # Exception TYPE only -- never str(exc), which could echo store content.
        logger.warning(
            "Lexicon vocabulary %s failed error_type=%s; the seam degrades to the "
            "last good vocabulary (raw pass-through if there is none)",
            what,
            type(exc).__name__,
        )


# The process-installed vocabulary. Both twins default to it, so a deployment
# wires L7 in ONE place (hermes_runtime's two composition roots, beside
# warm_knowledge_embedder) rather than threading it through every driver factory.
#
# Absent by default, and that is load-bearing in three ways: a mock deployment,
# a unit test and the eval record/replay path all run with nothing installed, so
# the seam is a no-op there and the eval stays byte-identical (NFR-4).
_installed_vocabulary: Optional[LexiconVocabulary] = None


def install_lexicon_vocabulary(vocabulary: Optional[LexiconVocabulary]) -> None:
    """Install (or with ``None``, remove) the process-wide vocabulary."""
    global _installed_vocabulary
    _installed_vocabulary = vocabulary


def current_lexicon_vocabulary() -> Optional[LexiconVocabulary]:
    """The installed vocabulary, or ``None`` -- meaning raw pass-through."""
    return _installed_vocabulary
