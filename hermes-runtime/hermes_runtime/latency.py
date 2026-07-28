"""Per-layer memory-read latency: measure, emit, aggregate (0.0.5 S18, FR-26).

S18 is measure-first. It builds the histogram S19 will later enforce against and
ships **no** deadline of its own -- shipping one here would take S19's decision
away before its evidence exists.

**Where the numbers come from.** Each pre-turn read site in the two live turn
paths (``openrouter.run_turn``, ``copilot_turn.run_turn``) is wrapped in
:func:`measure`, which appends ``(metric, elapsed_ms)`` to a per-turn list. The
list is written ONCE, by :func:`record_latency_samples`, AFTER the model call --
the same posture as :mod:`hermes_runtime.injection_ledger`, and for the same two
reasons: a synchronous INSERT in front of the reply is the database round-trip
NFR-5 exists to keep off the reply path, and a turn that never produced a reply
has no reply-latency fact to record. Measuring costs two ``perf_counter`` reads
and a list append; the write costs one connection for the whole turn, bounded by
``CONNECT_TIMEOUT_TURN_SECONDS`` (the emit inherits it -- there is no second
timeout constant here).

**Eval-neutral (NFR-4), three ways.** (1) A duration never reaches the prompt,
the response or ``messages`` -- nothing here is threaded into
``render_injection`` or the turn result, so a slower read produces a
byte-identical turn. (2) Every sample is gated PER LAYER on the same flag that
layer's read rode -- :data:`_METRIC_LAYER` resolves through
``injection_ledger._LAYER_GATES`` rather than restating it -- and every one of
those flags is off on the eval record/replay path, so that path writes nothing
and opens no connection. (3) The gate is applied in ONE place, at emit time, not
scattered across the call sites: the timers themselves are unconditional, so a
later slice cannot silently disable a layer's measurement by moving a guard
upstream of it.

**Storage (D5.1).** ``metric_event`` gained a nullable ``duration_ms`` in
migration 0023 rather than a new latency-sample table; the migration records why.

**Scope of the SLO (D5.2 / D5.3).** :data:`SLO_TOTAL_METRICS` -- the L4, L6 and
L7 reads -- is what the owner's **≤150ms p95** line covers. L5 retrieval is
measured and tiled against its OWN shipped budget (``knowledge/driver.py``'s
``DEFAULT_DEADLINE_MS``, imported rather than copied -- deliberately not quoted
as a number anywhere in this module) and excluded from the total, because that
budget is several times the SLO and a total including it could never meet it.
The provisional->verified merge is a WRITE, so it gets its own tile outside the
total too. Neither this module nor the tiles invent a budget for anything else:
an unbudgeted tile reports its percentiles and no verdict.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, List, Optional, Tuple

from .injection_ledger import LAYER_L4, LAYER_L6, LAYER_L7, _LAYER_GATES
from .metrics import KNOWLEDGE_SEARCH, emit_metric_samples

logger = logging.getLogger(__name__)

# One metric name per read site. No number is ever encoded into a name (D5.1);
# the duration lives in `metric_event.duration_ms`.
LATENCY_L4_LOAD = "latency_l4_load"
LATENCY_L4_MERGE = "latency_l4_merge"
LATENCY_L6_LOAD = "latency_l6_load"
LATENCY_L7_LOAD = "latency_l7_load"
LATENCY_PRE_TURN_TOTAL = "latency_pre_turn_total"

# L5 rides the row `knowledge/driver.py._emit_found` already writes per retrieval
# attempt -- see migration 0023. Aliased rather than duplicated so the tile, the
# aggregation and the emit all name the same string.
LATENCY_L5_RETRIEVAL = KNOWLEDGE_SEARCH

# Owner decision (2), FR-26: the recorded SLO line for the pre-turn READS.
PRE_TURN_READ_SLO_P95_MS = 150.0

# What the 150ms line covers: the non-L5 READS (D5.2), merge excluded as a write
# (D5.3). The per-turn SUM of these is emitted as its own row, so the total's p95
# is a real percentile over turns -- summing per-layer p95s would overstate it,
# because no single turn is at the 95th percentile of every layer at once.
SLO_TOTAL_METRICS: Tuple[str, ...] = (LATENCY_L4_LOAD, LATENCY_L6_LOAD, LATENCY_L7_LOAD)

NOT_MEASURED_LABEL = "Not yet measured (no latency samples on this deployment)"

# metric -> the memory layer whose injection flag gates it. Resolved through the
# ledger's `_LAYER_GATES` rather than restating the flags: a second copy of that
# table is how the L6 hole D4.1 corrected got in, and the rule is identical here
# -- a layer's latency row rides the same flag that layer's READ rode. The merge
# rides L4's flag because `_merge_provisional_memory` is gated on `memory_enabled`.
_METRIC_LAYER = {
    LATENCY_L4_LOAD: LAYER_L4,
    LATENCY_L4_MERGE: LAYER_L4,
    LATENCY_L6_LOAD: LAYER_L6,
    LATENCY_L7_LOAD: LAYER_L7,
}

# Tile order + labels, shared by the live aggregation and the zero-sample payload
# so the Postgres twin and the mock twin cannot render different tiles.
_TILE_LABELS = (
    (LATENCY_L4_LOAD, "L4", "L4 customer memory read"),
    (LATENCY_L6_LOAD, "L6", "L6 confirmed learnings read"),
    (LATENCY_L7_LOAD, "L7", "L7 lexicon glossary read"),
    (LATENCY_L4_MERGE, "L4", "L4 provisional merge (write)"),
    (LATENCY_L5_RETRIEVAL, "L5", "L5 knowledge retrieval"),
)
_TOTAL_LABEL = (LATENCY_PRE_TURN_TOTAL, "L4+L6+L7", "Pre-turn reads, total")

LatencySample = Tuple[str, float]


# --- measurement ---------------------------------------------------------------


@contextmanager
def measure(samples: List[LatencySample], metric: str) -> Iterator[None]:
    """Time the wrapped block and append ``(metric, elapsed_ms)`` to ``samples``.

    Unconditional on purpose. The gate lives at emit time
    (:func:`record_latency_samples`), so there is exactly one place a layer can
    be switched off and no call site can be silently de-instrumented by a guard
    landing upstream of it. ``finally`` so a read that raised -- the fail-open
    path -- is still measured; a read that failed slowly is precisely the
    datapoint S19 needs.
    """
    started = time.perf_counter()
    try:
        yield
    finally:
        samples.append((metric, (time.perf_counter() - started) * 1000.0))


def record_latency_samples(samples: Iterable[LatencySample]) -> None:
    """Best-effort: write this turn's per-layer durations. Never raises.

    Rows are filtered per layer by the flag that layer's read rode, then the
    surviving :data:`SLO_TOTAL_METRICS` samples are summed into one
    ``latency_pre_turn_total`` row. Deriving the total from the ALREADY-GATED
    rows is what keeps it honest: a deployment with L7 off contributes no L7 time
    and its total does not silently include a layer it never read.

    Called from the two live turn paths only, after the model call. Wrapped
    whole: ``emit_metric_samples`` already swallows its own failures, and this
    outer guard is what makes "never fails a turn" true of the summing and gating
    above it too, rather than true only by inspection.
    """
    try:
        gated = [
            (metric, duration)
            for metric, duration in samples
            # Fail CLOSED on an unregistered metric. A later slice that wraps a
            # new read site in `measure` without adding it to `_METRIC_LAYER`
            # gets no rows rather than ungated ones -- an ungated row is one that
            # lands on the eval record/replay path, which is the NFR-4 break this
            # module exists to avoid. Missing data is recoverable; a
            # nondeterministic write into the replay gate is not.
            if metric in _METRIC_LAYER and _LAYER_GATES[_METRIC_LAYER[metric]]()
        ]
        if not gated:
            # Every layer's gate shut -- the eval record/replay path, and any
            # mock/unset deployment. Return before the emit rather than handing
            # it an empty batch, so "that path attempts no metrics write at all"
            # is checkable from the outside.
            return
        rows = [(metric, None, duration) for metric, duration in gated]
        in_total = [d for metric, d in gated if metric in SLO_TOTAL_METRICS]
        if in_total:
            rows.append((LATENCY_PRE_TURN_TOTAL, None, sum(in_total)))
        emit_metric_samples(rows)
    except Exception as exc:
        # ponytail: swallow so a metrics hiccup can never fail or delay a reply
        # (NFR-5). Exception TYPE only, never str(exc).
        logger.warning(
            "Latency emit failed error_type=%s; the turn is unaffected",
            type(exc).__name__,
        )


# --- aggregation: the tile payload ---------------------------------------------


def _budget_ms(metric: str) -> Optional[float]:
    """The line a tile is judged against, or ``None`` for "measured, not budgeted".

    Only two metrics have a budget, and neither number is invented here. The
    total carries the owner's SLO; L5 carries the deadline its own driver already
    enforces. Everything else reports percentiles and no verdict -- S19 owns
    budgets, this slice owns the histogram.
    """
    if metric == LATENCY_PRE_TURN_TOTAL:
        return PRE_TURN_READ_SLO_P95_MS
    if metric == LATENCY_L5_RETRIEVAL:
        # Imported lazily for the same reason `tool_backend` imports this module
        # lazily: the knowledge driver pulls in the retriever, which has no
        # business joining the turn path's import graph. This function runs on
        # the admin read path only.
        from .knowledge.driver import DEFAULT_DEADLINE_MS

        return DEFAULT_DEADLINE_MS
    return None


def _tile(
    metric: str,
    layer: str,
    label: str,
    p50: Optional[float],
    p95: Optional[float],
    samples: int,
) -> dict[str, Any]:
    budget = _budget_ms(metric)
    return {
        "metric": metric,
        "layer": layer,
        "label": label,
        "p50_ms": p50,
        "p95_ms": p95,
        "samples": samples,
        "budget_ms": budget,
        "in_slo_total": metric in SLO_TOTAL_METRICS,
        # None, never False, when there is nothing to judge: a `False` here would
        # render an unmeasured tile as a green "within budget" on a deployment
        # that has measured nothing at all.
        "breached": None if (budget is None or p95 is None) else p95 > budget,
    }


def _payload(measured: dict[str, Tuple[float, float, int]]) -> dict[str, Any]:
    def build(spec: Tuple[str, str, str]) -> dict[str, Any]:
        metric, layer, label = spec
        p50, p95, count = measured.get(metric, (None, None, 0))
        return _tile(metric, layer, label, p50, p95, count)

    return {
        "slo_p95_ms": PRE_TURN_READ_SLO_P95_MS,
        "not_measured_label": NOT_MEASURED_LABEL,
        "total": build(_TOTAL_LABEL),
        "layers": [build(spec) for spec in _TILE_LABELS],
    }


def empty_latency_metrics() -> dict[str, Any]:
    """The zero-sample payload: what a fresh database and the mock twin report.

    Shared so the two twins cannot drift into rendering different tiles (NFR-7);
    ``tests/test_latency.py`` asserts the mock returns exactly this.
    """
    return _payload({})


def latency_metrics(cur) -> dict[str, Any]:
    """The latency tiles' payload, on a caller-owned cursor.

    ``duration_ms IS NOT NULL`` is the load-bearing filter: ``knowledge_search``
    rows are BOTH found/miss counters and L5 latency samples, and a counter row
    entering the percentile as an implicit zero would silently flatter L5.
    Percentiles are computed in Postgres (``percentile_cont``) rather than by a
    scheduled rollup -- at this volume the aggregation is one indexed scan on an
    admin-only read, so a rollup job would be a second moving part with a
    staleness window and nothing to buy with it.
    """
    cur.execute(
        """
        SELECT metric,
               percentile_cont(0.5)  WITHIN GROUP (ORDER BY duration_ms),
               percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms),
               COUNT(*)
        FROM metric_event
        WHERE duration_ms IS NOT NULL AND metric = ANY(%s)
        GROUP BY metric
        """,
        ([_TOTAL_LABEL[0], *(metric for metric, _l, _lbl in _TILE_LABELS)],),
    )
    measured = {
        metric: (float(p50), float(p95), int(count))
        for metric, p50, p95, count in cur.fetchall()
    }
    return _payload(measured)
