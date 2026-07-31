"""Per-layer memory-read latency: measure, emit, aggregate, ENFORCE (S18 + S19).

S18 (FR-26) is measure-first: it built the histogram and shipped no budget.
S19 (FR-27) is the enforcement half that reads it -- :func:`load_reads`, the
per-layer deadline, the fail-open skip and the pool. The two live in one module
because they are one seam: the thing that times a read is the thing that has to
give up on it.

**S19 ships OFF, and that is what the evidence says to do.** FR-27 is explicit
that only what the histogram indicts may be optimized, and on this deployment the
histogram indicts nothing: the whole pre-turn read total tops out at 41ms against
a 150ms p95 line. So :func:`load_reads` defaults to the sequential inline path
the two turn seams already had, and
:func:`~hermes_runtime.tool_backend.memory_read_budget_enabled` is the switch for
the day a total tile goes red.

**One caveat on the total under the pool**, because the tile's meaning shifts and
a silent shift would be worse than the shift: :data:`LATENCY_PRE_TURN_TOTAL` is
the per-turn SUM of the three reads. Sequentially that is exactly the wall clock
the turn spent. In parallel the three overlap, so the sum becomes an upper bound
on it -- never an understatement. Left as the sum deliberately: an SLO tile that
flattered a turn would be a worse failure than one that over-charges it, and a
second wall-clock metric would need a gate of its own for a mode that is off.

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
total too. No budget in this module is invented: S19's per-layer deadline is
derived from the connect budget for the reasons written at
:data:`MEMORY_READ_DEADLINE_MS`, and every other tile reports its percentiles and
passes no verdict.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator, List, Optional, Sequence, Tuple

from .datastore.config import CONNECT_TIMEOUT_TURN_SECONDS
from .injection_ledger import LAYER_L4, LAYER_L6, LAYER_L7, _LAYER_GATES
from .metrics import KNOWLEDGE_SEARCH, emit_metric_samples
from .tool_backend import _flag_on

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

# --- S19 (FR-27): the budget ---------------------------------------------------

# The switch for the whole enforcement half of this module.
#
# DEFAULT OFF, and that is a decision made against evidence rather than caution.
# FR-27 says to optimize only what the histogram indicts, and on this deployment
# S18's histogram indicts nothing: 415 measured turns, the whole pre-turn read
# total topping out at 41ms against a 150ms p95 line. So the mechanism lands
# ready and dark; the day a total tile goes red, this is the switch. Off, the
# reads run inline exactly as they did before -- which is what keeps the existing
# turn suites and the replay gate byte-identical (NFR-4).
#
# ONE flag for both halves on purpose: a deadline can only be ENFORCED
# off-thread (a bound checked after the slow call returns is a comment), so the
# pool is the enforcement vehicle, not a separate feature to switch separately.
# It reuses `tool_backend._flag_on` -- the shared fail-closed parser every other
# injection flag uses -- rather than a sixth spelling of "is this on". Reaching
# for that module's underscore name is the established pattern here, not a new
# liberty: `openrouter.py` already imports `_gateway_store` and
# `_turn_extra_drivers` from it for the same "one implementation, no drift"
# reason. The flag lives HERE rather than beside the injection flags because it
# switches THIS module's behaviour, and because `tool_backend.py` is not S19's
# file to touch this wave.
MEMORY_READ_BUDGET_ENV = "MEMORY_READ_BUDGET"


def memory_read_budget_enabled() -> bool:
    """Whether pre-turn memory reads run under the S19 deadline + pool (FR-27).

    Fail-closed: unset, empty, or anything outside the shared on-set is ``False``.
    """
    return _flag_on(MEMORY_READ_BUDGET_ENV)


# The deadline ONE pre-turn layer read gets before it is dropped.
#
# DERIVED, never a third number. `b989048` already decided how long anything on
# the reply path may wait for the database, and decided it against a measured
# 130-second hang on an unbounded connect: `CONNECT_TIMEOUT_TURN_SECONDS`, whose
# own comment sets the bar at "shorter than a person notices". A layer READ asks
# exactly that question, so it inherits exactly that answer.
#
# It also cannot sensibly be SHORTER. A read that has to open its connection
# spends up to the connect budget before it has issued any SQL at all, so a
# tighter read deadline would fire on every cold connect -- a layer dropped
# because it was first, not because the database was slow. That converts a
# working fail-open into routine, invisible context loss.
#
# What it actually buys, since the connect is already bounded: the pooled
# acquire. `datastore/pool.py` deliberately leaves the pool's queue-wait at 30s
# (shortening it turns queuing under load into errors under load), so under
# saturation a memory read can block for half a minute with the customer's reply
# behind it. Nothing bounded that before this constant.
MEMORY_READ_DEADLINE_MS = CONNECT_TIMEOUT_TURN_SECONDS * 1000.0

# A breach emits its own countable row alongside the timing row. Derived from the
# read's metric name so there is one naming rule and no read site can invent a
# second convention that leaves its skips uncountable.
SKIP_SUFFIX = "_skipped"


def skip_metric(metric: str) -> str:
    """The countable "this layer was dropped by the deadline" metric for ``metric``."""
    return metric + SKIP_SUFFIX


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
# A skip row rides the SAME gate as the read it replaces, derived from the table
# above rather than restated -- so it is impossible to add a skip that lands on
# the eval record/replay path when the read itself would not have. The budgeted
# reads are exactly the SLO's reads: the merge is a write (D5.3) and L5 enforces
# its own deadline (D5.2), so neither is ever skipped by this mechanism.
_METRIC_LAYER.update({skip_metric(m): _METRIC_LAYER[m] for m in SLO_TOTAL_METRICS})

# Tile order + labels, shared by the live aggregation and the zero-sample payload
# so the Postgres twin and the mock twin cannot render different tiles.
#
# S19's skip metrics are still NOT tiled here, and since 0.0.5 S22 that is a
# decision rather than a deferral. Every tile in this table is a DURATION tile:
# p50/p95 over `duration_ms`, judged against a budget. A skip is an EVENT — the
# number that matters is how many turns lost a layer, and its p95 would only ever
# report how long the deadline is. Rendered here, a layer nothing has ever
# dropped would read "Not yet measured", which is the opposite of the truth.
# S22 places the tile where the shape fits: `toee_hermes.lifecycle_metrics`
# renders one COUNT per injected layer, and `datastore/handlers/metrics.py`
# derives the metric names from `skip_metric` + `_METRIC_LAYER` below rather than
# restating them.
_TILE_LABELS = (
    (LATENCY_L4_LOAD, "L4", "L4 customer memory read"),
    (LATENCY_L6_LOAD, "L6", "L6 confirmed learnings read"),
    (LATENCY_L7_LOAD, "L7", "L7 lexicon glossary read"),
    (LATENCY_L4_MERGE, "L4", "L4 provisional merge (write)"),
    (LATENCY_L5_RETRIEVAL, "L5", "L5 knowledge retrieval"),
)
_TOTAL_LABEL = (LATENCY_PRE_TURN_TOTAL, "L4+L6+L7", "Pre-turn reads, total")

LatencySample = Tuple[str, float]
# (metric, thunk) -- one independent pre-turn layer read, ready to run.
LayerRead = Tuple[str, Callable[[], Any]]


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


# --- enforcement: the deadline + the pool (S19, FR-27) --------------------------


def _timed(read: Callable[[], Any]) -> Tuple[Any, float]:
    """Run ``read`` on a worker thread, returning ``(value, elapsed_ms)``.

    The timing is taken INSIDE the worker and carried back with the value rather
    than appended to the caller's sample list, so a worker abandoned by a
    deadline never mutates a list the caller is already reading. It also keeps
    the per-layer number honest under the pool: the caller's own wait for the
    second and third futures is near zero once it has waited for the first.
    """
    started = time.perf_counter()
    return read(), (time.perf_counter() - started) * 1000.0


def _inline(samples: List[LatencySample], metric: str, read: Callable[[], Any]) -> Any:
    """Today's path: run the read on this thread, timed, unbounded."""
    with measure(samples, metric):
        return read()


def _collect(samples: List[LatencySample], metric: str, future: Any) -> Any:
    """Wait out ``future`` under the deadline; on breach drop the layer, countably."""
    waited_from = time.perf_counter()

    def waited_ms() -> float:
        return (time.perf_counter() - waited_from) * 1000.0

    try:
        value, elapsed_ms = future.result(timeout=MEMORY_READ_DEADLINE_MS / 1000.0)
    except FutureTimeoutError:
        # Fail OPEN: this layer contributes nothing to the prompt and the turn
        # carries on. Two rows: the time it cost (so the breach stays visible on
        # the SLO tile rather than making a struggling deployment read as a fast
        # one) and the countable skip.
        logger.warning(
            "pre-turn memory read deadline exceeded metric=%s deadline_ms=%s; "
            "the layer is skipped for this turn and the reply is unaffected",
            metric,
            MEMORY_READ_DEADLINE_MS,
        )
        spent = waited_ms()
        samples.append((metric, spent))
        samples.append((skip_metric(metric), spent))
        return None
    except Exception as exc:
        # Every reader below this already swallows its own errors, so this is the
        # backstop for a future that raised anyway. NOT counted as a skip: a
        # failed read is not a breached budget, and conflating them would inflate
        # the number the owner reads as "the deadline is too tight".
        logger.warning(
            "pre-turn memory read failed metric=%s error_type=%s; "
            "the layer is skipped for this turn and the reply is unaffected",
            metric,
            type(exc).__name__,
        )
        samples.append((metric, waited_ms()))
        return None
    samples.append((metric, elapsed_ms))
    return value


def load_reads(samples: List[LatencySample], reads: Sequence[LayerRead]) -> List[Any]:
    """Run the independent pre-turn layer reads; return their values IN ORDER.

    Off (the default, :func:`memory_read_budget_enabled`),
    each read runs inline under :func:`measure` -- byte-for-byte the sequential
    path both turn seams had before, which is what keeps the existing turn suites
    and the replay gate unmoved (NFR-4).

    On, all of them are submitted to ONE :class:`~concurrent.futures.ThreadPoolExecutor`
    and collected under :data:`MEMORY_READ_DEADLINE_MS` each. Running off-thread
    is not an optimization bolted onto the deadline, it is the only way to HAVE
    one: a bound checked after the slow call returns has already waited.

    **What happens to abandoned work, stated rather than implied.**
    ``concurrent.futures`` cannot cancel a running future, and ``shutdown(wait=False)``
    -- the same choice ``KnowledgeDriver`` makes for the L5 deadline -- means the
    turn does not block on it either. So a breached read keeps running and keeps
    its pooled connection until its own query returns. That is acceptable here,
    bounded on three sides: every read is a side-effect-free ``SELECT``, so
    abandoning it corrupts nothing and its result is simply discarded; the merge
    is a WRITE and is deliberately NOT in this pool (D5.3), so no write is ever
    abandoned or double-run; and connection consumption is capped by the pool's
    own ``max_size``, past which the reader's existing fail-closed wrapper
    swallows the ``PoolTimeout`` and the turn still answers. What is NOT bounded
    is the SQL execution itself -- a ``statement_timeout`` on the read connection
    is the belt-and-braces half, the same follow-up ``KnowledgeDriver`` names, and
    it is out of this slice because it would move every datastore call in the
    process, not just these three.

    ANY pool failure degrades to the sequential path with the same results
    (FR-27). Since the reads are idempotent ``SELECT``s, a failure part-way
    through submission may re-run one; nothing is written twice.
    """
    # `and reads` because `ThreadPoolExecutor(max_workers=0)` raises, and it would
    # raise HERE -- outside the try below -- i.e. straight into a turn. No caller
    # passes an empty sequence today; one word is cheaper than trusting that.
    if reads and memory_read_budget_enabled():
        pool = ThreadPoolExecutor(max_workers=len(reads))
        try:
            futures = [(metric, pool.submit(_timed, read)) for metric, read in reads]
            return [_collect(samples, metric, future) for metric, future in futures]
        except Exception as exc:
            logger.warning(
                "pre-turn memory read pool unavailable error_type=%s; "
                "falling back to the sequential path",
                type(exc).__name__,
            )
        finally:
            pool.shutdown(wait=False)
    return [_inline(samples, metric, read) for metric, read in reads]


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
