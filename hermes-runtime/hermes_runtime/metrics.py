"""Fire-and-forget metric-event emit (0.0.3 S26, FR-28).

Two boolean counters land in one tiny table (``metric_event``, migration
0009): memory injection (``openrouter.py``/``copilot_turn.py``, gap #1) and
knowledge found/miss (``knowledge/driver.py``, gap #2). Each call site gates
the emit on its OWN feature axis (``memory_enabled()`` / ``knowledge_enabled()``)
before calling here, mirroring ``tool_backend.load_confirmed_experience``'s
philosophy -- a mock/unset deployment never attempts a metrics connection.

Turn-safe (NFR-5): ANY failure here -- missing DSN, unreachable Postgres, a
migration not yet applied -- is caught and logged by TYPE ONLY and never
raised. A metrics emit must never fail a turn or a knowledge search. No PII
(FR-4/RK-2): only a metric name + boolean ever leave the call site, never a
customer value or the knowledge query text.
"""

from __future__ import annotations

import logging
import uuid

import psycopg

from .datastore.config import CONNECT_TIMEOUT_TURN_SECONDS, database_url

logger = logging.getLogger(__name__)

MEMORY_INJECTION = "memory_injection"
KNOWLEDGE_SEARCH = "knowledge_search"


def emit_metric_event(metric: str, flag: bool) -> None:
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
    # customer's reply queued behind it. The timeout below is what makes the
    # "swallow ANY failure" promise above actually true.
    """
    try:
        with psycopg.connect(
            database_url(), connect_timeout=CONNECT_TIMEOUT_TURN_SECONDS
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO metric_event (id, metric, flag) VALUES (%s, %s, %s)",
                    (f"metric_{uuid.uuid4().hex}", metric, flag),
                )
            conn.commit()
    except Exception as exc:
        logger.warning(
            "metric emit failed metric=%s error_type=%s", metric, type(exc).__name__
        )
