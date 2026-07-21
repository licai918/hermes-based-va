"""Pure metric-computation unit tests on fixture data (0.0.3 S26, FR-28 layer ①).

No DB: ``_rate``/``_distribution_dict`` are the pure arithmetic the aggregate
metrics handler layers real SQL rows onto (``datastore/handlers/metrics.py``).
Kept here (not import-cycled into the handler test) so the acceptance's "unit
-- metric computations correct on fixture data" is a fast, DB-free check.
"""

from __future__ import annotations

from hermes_runtime.datastore.handlers.metrics import _distribution_dict, _rate


def test_rate_is_none_for_zero_total() -> None:
    assert _rate(0, 0) is None


def test_rate_divides_hits_by_total() -> None:
    assert _rate(3, 4) == 0.75


def test_rate_is_zero_when_no_hits() -> None:
    assert _rate(0, 5) == 0.0


def test_distribution_dict_defaults_every_slot_count_to_zero() -> None:
    assert _distribution_dict([]) == {"1": 0, "2": 0, "3": 0, "4": 0}


def test_distribution_dict_fills_in_seeded_counts() -> None:
    rows = [(1, 5), (2, 3), (4, 1)]
    assert _distribution_dict(rows) == {"1": 5, "2": 3, "3": 0, "4": 1}


def test_distribution_dict_ignores_an_out_of_range_populated_count() -> None:
    # Defensive: customer_memory_slot's UNIQUE(binding_key, slot_name) caps a
    # binding at the 4 v1 slots, so a >4 row should never occur -- but a
    # pure-function test still pins this doesn't blow up or corrupt the shape.
    rows = [(1, 2), (5, 99)]
    assert _distribution_dict(rows) == {"1": 2, "2": 0, "3": 0, "4": 0}
