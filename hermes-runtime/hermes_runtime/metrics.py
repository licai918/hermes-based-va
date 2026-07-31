"""Fire-and-forget metric-event emit (0.0.3 S26, FR-28; 0.0.5 S18, FR-26).

Two boolean counters land in one tiny table (``metric_event``, migration
0009): memory injection (``openrouter.py``/``copilot_turn.py``, gap #1) and
knowledge found/miss (``knowledge/driver.py``, gap #2). Each call site gates
the emit on its OWN feature axis (``memory_enabled()`` / ``knowledge_enabled()``)
before calling here, mirroring ``tool_backend.load_confirmed_experience``'s
philosophy -- a mock/unset deployment never attempts a metrics connection.

Since 0.0.5 S18 a row may also carry a ``duration_ms`` (migration 0023) instead
of, or alongside, its boolean -- see :mod:`hermes_runtime.latency` for the
per-layer read timings and why they live in this table rather than a new one.
:func:`emit_metric_samples` is the batched form: N rows on ONE connection, so a
turn that timed four layers still opens exactly one.

Turn-safe (NFR-5): ANY failure here -- missing DSN, unreachable Postgres, a
migration not yet applied -- is caught and logged by TYPE ONLY and never
raised. A metrics emit must never fail a turn or a knowledge search. No PII
(FR-4/RK-2): only a metric name, a boolean and a duration ever leave the call
site, never a customer value or the knowledge query text.
"""

from __future__ import annotations

import logging
import uuid
from typing import Iterable, Optional, Sequence, Tuple

import psycopg

from .datastore.config import CONNECT_TIMEOUT_TURN_SECONDS, database_url

logger = logging.getLogger(__name__)

MEMORY_INJECTION = "memory_injection"
KNOWLEDGE_SEARCH = "knowledge_search"

# (metric, flag, duration_ms). Either signal may be None; migration 0023's CHECK
# refuses a row with neither.
MetricSample = Tuple[str, Optional[bool], Optional[float]]

_INSERT_SQL = (
    "INSERT INTO metric_event (id, metric, flag, duration_ms) VALUES (%s, %s, %s, %s)"
)


def emit_metric_samples(rows: Iterable[MetricSample]) -> None:
    """Insert N ``metric_event`` rows on ONE connection; swallow ANY failure.

    One connection for the whole batch is the point: the per-layer latency emit
    (S18) times four sites per turn, and four separate connects would make the
    instrumentation itself the thing NFR-5 forbids. A plain loop rather than
    ``executemany`` -- at four rows the round-trips are noise, and one SQL string
    with one shape is cheaper to keep honest than two.
    """
    batch: Sequence[MetricSample] = list(rows)
    if not batch:
        return
    try:
        with psycopg.connect(
            database_url(), connect_timeout=CONNECT_TIMEOUT_TURN_SECONDS
        ) as conn:
            with conn.cursor() as cur:
                for metric, flag, duration_ms in batch:
                    cur.execute(
                        _INSERT_SQL,
                        (f"metric_{uuid.uuid4().hex}", metric, flag, duration_ms),
                    )
            conn.commit()
    except Exception as exc:
        logger.warning(
            "metric emit failed metric=%s error_type=%s",
            ",".join(metric for metric, _flag, _ms in batch),
            type(exc).__name__,
        )


def emit_metric_event(
    metric: str, flag: Optional[bool], duration_ms: Optional[float] = None
) -> None:
    """Insert one ``metric_event`` row; swallow ANY failure, never raises.

    # ponytail: intentionally NOT pooled (S29/FR-31 named only 4 sites; this
    # S26 5th connect is a related follow-up, not in scope). A pool's
    # getconn() can block up to its `timeout` waiting for a free slot, which
    # would turn a "never fail a turn" fire-and-forget emit into a stall --
    # pool it only alongside a bounded, non-blocking acquire (e.g. timeout=0
    # + treat PoolTimeout as just another swallowed failure).
    #
    # That reasoning was right about the hazard and wrong about which option
    # carried it. Avoiding the pool to dodge a BOUNDED 30s wait, and then
    # connecting with no `connect_timeout`, bought an UNBOUNDED one: a host that
    # blackholes rather than refuses blocks until the OS TCP timeout, with the
    # customer's reply queued behind it. The timeout below (in
    # :func:`emit_metric_samples`, which this delegates to) is what makes the
    # "swallow ANY failure" promise above actually true.
    """
    emit_metric_samples(((metric, flag, duration_ms),))
