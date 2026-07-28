"""0.0.5 S05 (FR-5): the deterministic seam -- L7 applied to product-read params.

S03 shipped the rules and the vocabulary; nothing applied them. This is the
application: ``2055516``, ``205 55 16`` and ``20555r16`` all reach ONE product,
without asking a model, because a model that is right 97% of the time is wrong
about one order in thirty.

Everything here drives the seam through a REAL handler -- the mock twin's
``search_products``/``get_product`` and the ComposioDriver's -- rather than
calling the pure function in isolation, because "the helper normalizes" and "the
handler that customers reach normalizes" are different claims and only the second
one is FR-5.

The mock lexicon store is deliberately unseeded (S03), so every test here builds
its vocabulary explicitly from :data:`toee_hermes.lexicon.LEXICON_SEED_ENTRIES`.
"""

from __future__ import annotations

from typing import Any

import pytest

from toee_hermes.drivers.composio import ComposioDriver
from toee_hermes.drivers.mock.shopify import (
    ShopifyMockData,
    ShopifyProduct,
    create_shopify_mock_handlers,
)
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import ToolRequest
from toee_hermes.lexicon import LEXICON_SEED_ENTRIES
from toee_hermes.lexicon_seam import (
    LexiconVocabulary,
    normalize_product_query,
)
from toee_hermes.tool_gate import ToolExecutionContext

# The three notations the iteration is named after. They are the SAME size.
THREE_NOTATIONS = ("2055516", "205 55 16", "20555r16")
CANONICAL = "205/55R16"

TIRE_NORMALIZER_ID = "seed_lex_tire_size"
COMPANY_ALIAS_ID = "seed_lex_company_toee"

_V1 = "2026-07-28T00:00:00+00:00"
_V2 = "2026-07-29T00:00:00+00:00"


# --- vocabulary fixtures ------------------------------------------------------


def seed_rows(
    *, status: str = "confirmed", updated_at: str = _V1, only: str | None = None
) -> list[dict[str, Any]]:
    """The seeded domain #1 rows, as the store hands them to a reader.

    Built from ``LEXICON_SEED_ENTRIES`` rather than retyped, so a change to the
    seed cannot leave these tests asserting a vocabulary nobody ships.
    """
    return [
        {
            "id": entry.id,
            "domain": entry.domain,
            "entry_kind": entry.entry_kind,
            "surface_form": entry.surface_form,
            "canonical_form": entry.canonical_form,
            "status": status,
            "updated_at": updated_at,
        }
        for entry in LEXICON_SEED_ENTRIES
        if only is None or entry.id == only
    ]


class RecordingVocabulary(LexiconVocabulary):
    """A vocabulary whose reads and hits are observable."""

    def __init__(self, rows: list[dict[str, Any]], *, version: str = _V1) -> None:
        self.hits: list[str] = []
        self.loads = 0
        self.version_value: str | None = version
        self.rows = rows
        super().__init__(
            version=lambda: self.version_value,
            confirmed=self._load,
            record_hits=self.hits.extend,
        )

    def _load(self) -> list[dict[str, Any]]:
        self.loads += 1
        # The store filters by status; mirror that so a non-confirmed fixture is
        # a genuine "the reader never saw it" rather than a helper-side filter.
        return [row for row in self.rows if row["status"] == "confirmed"]


def product(size: str) -> ShopifyProduct:
    slug = size.replace("/", "-").lower()
    return ShopifyProduct(
        product_id=f"gid://shopify/Product/{slug}",
        sku=f"TIRE-{size.replace('/', '-')}",
        title=f"All-Season {size}",
        product_url=f"https://shop.toee.example/products/{slug}",
        media_url=f"https://cdn.toee.example/products/{slug}.jpg",
        price="189.99",
        inventory=24,
    )


def catalog(*sizes: str) -> ShopifyMockData:
    return ShopifyMockData(products=tuple(product(size) for size in sizes))


def mock_search(
    query: str, *, data: ShopifyMockData, vocabulary: LexiconVocabulary | None
) -> list[dict[str, Any]]:
    handlers = create_shopify_mock_handlers(data, vocabulary=vocabulary)
    return handlers["toee_shopify_read"]["search_products"](
        {"query": query}, ToolExecutionContext(profile="customer_service_external")
    )


# --- gate 1: the three notations ----------------------------------------------------


def test_the_three_notations_reach_one_and_the_same_product() -> None:
    data = catalog(CANONICAL, "225/60R16")
    vocab = RecordingVocabulary(seed_rows())
    found = [mock_search(n, data=data, vocabulary=vocab) for n in THREE_NOTATIONS]
    assert all(len(result) == 1 for result in found), found
    assert {result[0]["product_id"] for result in found} == {
        "gid://shopify/Product/205-55r16"
    }


def test_without_the_lexicon_the_three_notations_reach_nothing() -> None:
    # The control. Without this, the test above could pass because the mock's
    # substring filter happens to be generous rather than because L7 applied.
    data = catalog(CANONICAL, "225/60R16")
    assert [mock_search(n, data=data, vocabulary=None) for n in THREE_NOTATIONS] == [
        [],
        [],
        [],
    ]


# --- gate 1: only confirmed entries apply (PAC-2's deterministic half) --------------


@pytest.mark.parametrize("status", ["proposed", "rejected", "retired"])
def test_a_non_confirmed_entry_never_applies(status: str) -> None:
    data = catalog(CANONICAL)
    vocab = RecordingVocabulary(seed_rows(status=status))
    assert mock_search("20555r16", data=data, vocabulary=vocab) == []
    assert vocab.hits == []


def test_a_rejected_alias_never_applies() -> None:
    data = ShopifyMockData(
        products=(
            ShopifyProduct(
                product_id="gid://shopify/Product/9",
                sku="TOEE-TIRE-HOUSE-BRAND",
                title="TOEE TIRE house brand",
                product_url="https://shop.toee.example/products/house",
                media_url="https://cdn.toee.example/products/house.jpg",
            ),
        )
    )
    rejected = seed_rows(status="rejected", only=COMPANY_ALIAS_ID)
    # "TOEE TIRE" would match the title; the raw "TOEE" does too, so search on a
    # term the alias alone can resolve.
    vocab = RecordingVocabulary(rejected)
    assert mock_search("toee", data=data, vocabulary=vocab) != []  # raw substring
    assert vocab.hits == []  # ... but the rejected alias contributed nothing


@pytest.mark.parametrize("status", ["proposed", "rejected", "retired"])
def test_the_helper_itself_refuses_a_non_confirmed_row(status: str) -> None:
    """The belt-and-braces claim, proven rather than asserted in a docstring.

    The store's reader filters by status, so the handler tests above would stay
    green even if this filter were deleted. Hand the helper the rows DIRECTLY --
    the one way a reader that forgot could reach it -- and it must still refuse.
    """
    rows = seed_rows(status=status)
    assert (
        normalize_product_query("search_products", {"query": "20555r16"}, rows).canonical
        is None
    )
    assert (
        normalize_product_query("search_products", {"query": "TOEE"}, rows).canonical
        is None
    )


def test_a_confirmed_alias_applies() -> None:
    rows = seed_rows(only=COMPANY_ALIAS_ID)
    normalization = normalize_product_query("search_products", {"query": "TOEE"}, rows)
    assert normalization.params["query"] == "TOEE TIRE"
    assert normalization.entry_ids == (COMPANY_ALIAS_ID,)


# --- gate 1: the normalizer toggle --------------------------------------------------


def test_a_retired_normalizer_row_switches_tire_normalization_off() -> None:
    rows = seed_rows(status="retired", only=TIRE_NORMALIZER_ID)
    normalization = normalize_product_query(
        "search_products", {"query": "20555r16"}, rows
    )
    assert normalization.params == {"query": "20555r16"}
    assert normalization.canonical is None


def test_a_confirmed_normalizer_row_switches_it_on() -> None:
    rows = seed_rows(only=TIRE_NORMALIZER_ID)
    normalization = normalize_product_query(
        "search_products", {"query": "20555r16"}, rows
    )
    assert normalization.params == {"query": CANONICAL}
    assert normalization.entry_ids == (TIRE_NORMALIZER_ID,)


# --- gate 1: catalog verification ---------------------------------------------------


def test_a_size_absent_from_the_catalog_downgrades_to_the_raw_query() -> None:
    # 205/55R16 parses cleanly, but this catalog has no such product. Searching
    # the canonical anyway and reporting the empty result as authoritative is
    # worse than not normalizing: the raw term is what the customer said.
    data = catalog("225/60R16")
    vocab = RecordingVocabulary(seed_rows())
    assert mock_search("20555r16", data=data, vocabulary=vocab) == []
    assert vocab.hits == []  # an unverified canonical is never credited


def test_the_downgrade_returns_what_the_raw_term_would_have_found() -> None:
    data = ShopifyMockData(
        products=(
            ShopifyProduct(
                product_id="gid://shopify/Product/odd",
                sku="20555R16-CLEARANCE",
                title="Clearance lot",
                product_url="https://shop.toee.example/products/odd",
                media_url="https://cdn.toee.example/products/odd.jpg",
            ),
        )
    )
    vocab = RecordingVocabulary(seed_rows())
    # The canonical 205/55R16 matches nothing here; the raw 20555r16 matches the
    # sku. The downgrade must return that, not the canonical's empty result.
    found = mock_search("20555r16", data=data, vocabulary=vocab)
    assert [item["product_id"] for item in found] == ["gid://shopify/Product/odd"]
    assert vocab.hits == []


# --- gate 1: hit accounting ---------------------------------------------------------


def test_a_verified_application_records_exactly_one_hit() -> None:
    data = catalog(CANONICAL)
    vocab = RecordingVocabulary(seed_rows())
    mock_search("20555r16", data=data, vocabulary=vocab)
    assert vocab.hits == [TIRE_NORMALIZER_ID]


def test_a_query_that_is_already_canonical_records_no_hit() -> None:
    data = catalog(CANONICAL)
    vocab = RecordingVocabulary(seed_rows())
    assert mock_search(CANONICAL, data=data, vocabulary=vocab) != []
    assert vocab.hits == []


def test_three_applications_record_three_hits() -> None:
    data = catalog(CANONICAL)
    vocab = RecordingVocabulary(seed_rows())
    for notation in THREE_NOTATIONS:
        mock_search(notation, data=data, vocabulary=vocab)
    assert vocab.hits == [TIRE_NORMALIZER_ID] * 3


# --- gate 1: the process cache and its version bump --------------------------------


def test_the_cache_loads_once_across_many_reads() -> None:
    vocab = RecordingVocabulary(seed_rows())
    for _ in range(5):
        vocab.entries()
    assert vocab.loads == 1


def test_a_version_bump_reloads_on_the_very_next_read() -> None:
    vocab = RecordingVocabulary(seed_rows())
    assert vocab.entries()  # first read primes the cache
    vocab.rows = seed_rows(status="retired", updated_at=_V2)
    vocab.version_value = _V2
    assert vocab.entries() == ()
    assert vocab.loads == 2


def test_a_retirement_stops_applying_on_the_first_request_after_the_bump() -> None:
    data = catalog(CANONICAL)
    vocab = RecordingVocabulary(seed_rows())
    assert mock_search("20555r16", data=data, vocabulary=vocab) != []
    vocab.rows = seed_rows(status="retired", updated_at=_V2)
    vocab.version_value = _V2
    assert mock_search("20555r16", data=data, vocabulary=vocab) == []


# --- gate 1: fail-open --------------------------------------------------------------


def test_a_failing_version_probe_serves_the_last_good_vocabulary() -> None:
    data = catalog(CANONICAL)
    vocab = RecordingVocabulary(seed_rows())
    assert mock_search("20555r16", data=data, vocabulary=vocab) != []

    def boom() -> str:
        raise RuntimeError("postgres is having a day")

    vocab._version = boom  # type: ignore[assignment]
    assert mock_search("20555r16", data=data, vocabulary=vocab) != []


def test_a_failing_load_with_no_cache_passes_the_raw_params_through() -> None:
    data = catalog(CANONICAL)
    vocab = LexiconVocabulary(
        version=lambda: _V1,
        confirmed=_explode,
        record_hits=lambda ids: None,
    )
    # Never raises into the handler, and the customer's own term is what runs.
    assert mock_search("20555r16", data=data, vocabulary=vocab) == []
    assert mock_search(CANONICAL, data=data, vocabulary=vocab) != []


def test_a_failing_hit_sink_never_reaches_the_handler() -> None:
    data = catalog(CANONICAL)
    vocab = LexiconVocabulary(
        version=lambda: _V1,
        confirmed=lambda: seed_rows(),
        record_hits=lambda ids: _explode(),
    )
    assert mock_search("20555r16", data=data, vocabulary=vocab) != []


def _explode() -> Any:
    raise RuntimeError("the store is down")


# --- gate 1: get_product goes through the same seam --------------------------------


def test_get_product_normalizes_its_sku_through_the_same_helper() -> None:
    data = ShopifyMockData(
        products=(
            ShopifyProduct(
                product_id="gid://shopify/Product/1",
                sku=CANONICAL,
                title="All-Season 205/55R16",
                product_url="https://shop.toee.example/products/p",
                media_url="https://cdn.toee.example/products/p.jpg",
            ),
        )
    )
    vocab = RecordingVocabulary(seed_rows())
    handlers = create_shopify_mock_handlers(data, vocabulary=vocab)
    found = handlers["toee_shopify_read"]["get_product"](
        {"sku": "20555r16"}, ToolExecutionContext(profile="customer_service_external")
    )
    assert found["product_id"] == "gid://shopify/Product/1"
    assert vocab.hits == [TIRE_NORMALIZER_ID]


def test_get_product_falls_back_to_the_raw_sku_it_was_given() -> None:
    # Normalization must never break a lookup that would have worked: the
    # model sources this sku from a previous search_products result.
    data = catalog("225/60R16")
    vocab = RecordingVocabulary(seed_rows())
    handlers = create_shopify_mock_handlers(data, vocabulary=vocab)
    found = handlers["toee_shopify_read"]["get_product"](
        {"sku": "TIRE-225-60R16"},
        ToolExecutionContext(profile="customer_service_external"),
    )
    assert found["sku"] == "TIRE-225-60R16"
    assert vocab.hits == []


def test_get_product_still_fails_closed_when_nothing_matches_either_form() -> None:
    data = catalog("225/60R16")
    vocab = RecordingVocabulary(seed_rows())
    handlers = create_shopify_mock_handlers(data, vocabulary=vocab)
    with pytest.raises(ToolDriverError) as excinfo:
        handlers["toee_shopify_read"]["get_product"](
            {"sku": "20555r16"},
            ToolExecutionContext(profile="customer_service_external"),
        )
    assert excinfo.value.error_class == "unexpected_error"


# --- gate 1: mock/live twin parity (NFR-7) -----------------------------------------


class FakeComposioClient:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def execute_action(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self._response


def _composio_catalog(data: ShopifyMockData) -> dict[str, Any]:
    """The same products, in the raw vendor shape the live driver reshapes."""
    return {
        "products": [
            {
                "product_id": item.product_id,
                "sku": item.sku,
                "title": item.title,
                "product_url": item.product_url,
                "media_url": item.media_url,
            }
            for item in data.products
        ]
    }


def composio_search(
    query: str, *, data: ShopifyMockData, vocabulary: LexiconVocabulary | None
) -> list[dict[str, Any]]:
    driver = ComposioDriver(
        FakeComposioClient(_composio_catalog(data)),
        user_id="toee-staging",
        connected_accounts={"shopify": "ca_shopify"},
        vocabulary=vocabulary,
    )
    return driver.execute(
        ToolRequest(
            tool="toee_shopify_read", action="search_products", params={"query": query}
        ),
        ToolExecutionContext(profile="customer_service_external"),
    )


@pytest.mark.parametrize("notation", THREE_NOTATIONS)
def test_both_twins_resolve_each_notation_to_the_same_product(notation: str) -> None:
    """The parity that NFR-7 asks for, held by a test rather than by intent.

    Same catalog, same vocabulary, same notation -- through the mock handler and
    through the live ComposioDriver. If either twin's seam is removed, mis-wired
    or given a different matcher, these two lists stop agreeing.
    """
    data = catalog(CANONICAL, "225/60R16")
    mock_result = mock_search(
        notation, data=data, vocabulary=RecordingVocabulary(seed_rows())
    )
    live_result = composio_search(
        notation, data=data, vocabulary=RecordingVocabulary(seed_rows())
    )
    assert [item["product_id"] for item in mock_result] == [
        "gid://shopify/Product/205-55r16"
    ]
    assert [item["product_id"] for item in live_result] == [
        item["product_id"] for item in mock_result
    ]


def test_both_twins_downgrade_the_same_way_when_the_catalog_lacks_the_size() -> None:
    data = catalog("225/60R16")
    mock_vocab = RecordingVocabulary(seed_rows())
    live_vocab = RecordingVocabulary(seed_rows())
    assert mock_search("20555r16", data=data, vocabulary=mock_vocab) == []
    assert composio_search("20555r16", data=data, vocabulary=live_vocab) == []
    assert mock_vocab.hits == live_vocab.hits == []


def test_both_twins_credit_the_same_entry_with_a_hit() -> None:
    data = catalog(CANONICAL)
    mock_vocab = RecordingVocabulary(seed_rows())
    live_vocab = RecordingVocabulary(seed_rows())
    mock_search("2055516", data=data, vocabulary=mock_vocab)
    composio_search("2055516", data=data, vocabulary=live_vocab)
    assert mock_vocab.hits == live_vocab.hits == [TIRE_NORMALIZER_ID]


def test_the_live_twin_without_a_vocabulary_normalizes_nothing() -> None:
    # Eval/replay and every mock deployment run with no vocabulary installed, and
    # the NORMALIZATION must be a no-op there or NFR-4 is gone. The query FILTER
    # is not part of that no-op and is stated plainly rather than implied: before
    # S05 this path returned the whole catalog for every query while the mock
    # filtered, which is the mock/live divergence NFR-7 exists to stop.
    data = catalog(CANONICAL, "225/60R16")
    assert composio_search("2055516", data=data, vocabulary=None) == []
    assert [
        item["product_id"]
        for item in composio_search("225", data=data, vocabulary=None)
    ] == ["gid://shopify/Product/225-60r16"]
    assert len(composio_search("", data=data, vocabulary=None)) == 2
