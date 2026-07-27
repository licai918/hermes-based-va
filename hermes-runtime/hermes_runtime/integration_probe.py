"""Scheduled integration health probes (0.0.4 S16, FR-24).

Closes ADR-0136's "lazy discovery only" gap: instead of an expired or missing
credential surfacing as a *failing customer turn*, a recurring background job runs
one cheap AUTHENTICATED read per integration on a cadence and records the outcome,
which the ``/admin/integrations`` page (S15 seam) surfaces as a per-integration
badge. No paging/email in v1 -- a failure is a page badge plus a structured ERROR
log line (alert-greppable).

**On the SAME schedule mechanism retention uses (S01/S04).** There is no cron in
this repo. This is a NEW recurring job type on the ``(type, window)`` dedupe-key
tick the background worker already runs; the worker claims it (allowlist), the turn
worker never can (FR-9). See :mod:`hermes_runtime.background_worker`.

**Three honest states, never conflated (the track's spine -- do NOT lie on a health
surface):**

- ``not_configured`` -- no credential, so the probe was SKIPPED. This is the
  owner-blocked reality for all seven integrations today. It is NOT ``failed`` (the
  owner simply hasn't supplied the key) and NOT ``ok``.
- ``failed`` -- the credential IS present but the read errored (401/timeout/vendor
  error) OR returned an ambiguous/empty response. Per the empty-vs-error lesson this
  track has paid for repeatedly, an ambiguous read records ``failed``, never a false
  ``ok``. ``reason`` carries a short, secret-free explanation.
- ``ok`` -- the authenticated read succeeded (reachable + authorized).

**Deadline-bound (NFR-8 posture).** Each probe runs in a single-worker ThreadPool
that bounds the WHOLE probe call by one wall-clock budget, so a hung backend cannot
hang the probe job or the worker (the EasyRoutes/Gadget per-call pattern, applied
once here rather than per driver).

**Secret-safe (NFR-6).** A ``ProbeResult`` carries a status + a reason STRING only;
no credential value is ever read into it, logged, or stored. Each driver's own
error messages already reference env-derived URLs and status codes, never a token.

**Owner-blocked reality.** All seven credentials are owner-blocked today, so a live
probe records ``not_configured`` for every row. The live wire calls are isolated to
the same UNVERIFIED path the T4 drivers already carry; a wrong guess records
``failed``, never a false ``ok``. The scheduling, storage, the not-configured path,
and the fail-closed error path are all exercised against fake probes.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

import psycopg

from toee_hermes.drivers.composio.driver import (
    composio_config_status,
    probe_composio_toolkit,
)
from toee_hermes.drivers.easyroutes.driver import (
    build_easyroutes_driver,
    easyroutes_configured,
)
from toee_hermes.drivers.gadget import build_qbo_attribution, gadget_configured
from toee_hermes.errors import ToolDriverError

from .datastore.config import database_url
from .openrouter import openrouter_configured, probe_openrouter
from .simpletexting_reply import (
    probe_simpletexting_token,
    simpletexting_configured,
)

logger = logging.getLogger(__name__)

# The probe CADENCE (interval/window) is a scheduling policy and lives with the
# schedule in `background_worker.SCHEDULES` (mirroring how retention's interval
# lives there, not in retention_sweep) -- see that module for the 15-min choice and
# its `(type, window)` dedupe reasoning.

# ponytail: 8 s per probe, matching the live drivers' default per-call deadline
# (Composio/EasyRoutes/Gadget). Bounds the WHOLE probe call in a worker thread so a
# hung backend cannot stall the job or the worker. Env-tune only if a real backend
# needs a different budget.
PROBE_DEADLINE_MS = 8000.0

# ponytail: keep 30 days of probe history, pruned in the same write. Enough to see
# a recent flap on the page without unbounded growth; the page only ever reads the
# LATEST row per integration, so history depth is operator-forensics only. Widen if
# an operator ever wants a longer probe timeline.
PROBE_RETENTION_DAYS = 30


@dataclass(frozen=True)
class ProbeResult:
    """One integration's probe outcome for one cycle. ``reason`` is None on ``ok``
    and ``not_configured``; a short secret-free string on ``failed``."""

    key: str
    status: str  # 'ok' | 'failed' | 'not_configured'
    reason: Optional[str] = None


@dataclass(frozen=True)
class Probe:
    """One integration's probe wiring.

    ``configured`` is the driver's OWN cheap env-presence gate (the same signal the
    S15 page uses); ``check`` performs the live authenticated read and RAISES on any
    fault. ``not_configured_reason`` is the honest, secret-free note recorded when
    ``configured`` is False (names the env var the owner must set).
    """

    key: str
    configured: Callable[[], bool]
    check: Callable[[], None]
    not_configured_reason: str


def _composio_configured(toolkit_key: str) -> Callable[[], bool]:
    return lambda: bool(composio_config_status()[toolkit_key]["configured"])


# The seven integrations from S15, each mapped to its cheap authenticated read.
PROBES: tuple[Probe, ...] = (
    Probe(
        key="shopify",
        configured=_composio_configured("shopify"),
        check=lambda: probe_composio_toolkit("shopify"),
        not_configured_reason="not configured: Composio Shopify toolkit",
    ),
    Probe(
        key="qbo",
        configured=_composio_configured("qbo"),
        check=lambda: probe_composio_toolkit("qbo"),
        not_configured_reason="not configured: Composio QuickBooks toolkit",
    ),
    Probe(
        key="square",
        configured=_composio_configured("square"),
        check=lambda: probe_composio_toolkit("square"),
        not_configured_reason="not configured: Composio Square toolkit",
    ),
    Probe(
        key="easyroutes",
        configured=easyroutes_configured,
        check=lambda: build_easyroutes_driver().health(),
        not_configured_reason="not configured: EASYROUTES_SECRET + EASYROUTES_CLIENT_ID",
    ),
    Probe(
        key="simpletexting",
        configured=simpletexting_configured,
        check=probe_simpletexting_token,
        not_configured_reason="not configured: SIMPLETEXTING_API_TOKEN",
    ),
    Probe(
        key="openrouter",
        configured=openrouter_configured,
        check=probe_openrouter,
        not_configured_reason="not configured: OPENROUTER_API_KEY",
    ),
    Probe(
        key="gadget",
        configured=gadget_configured,
        check=lambda: build_qbo_attribution().health(),
        not_configured_reason="not configured: GADGET_API_KEY",
    ),
)


def _run_one(probe: Probe, *, deadline_ms: float) -> ProbeResult:
    """Run one probe under a wall-clock deadline; classify into the three states.

    A probe that CANNOT run (no credential) is ``not_configured`` -- skipped, never
    ``failed`` and never ``ok``. A configured probe is bounded in a worker thread; a
    timeout, a governed :class:`ToolDriverError`, or ANY other exception is
    ``failed`` with a short reason. Only a clean return is ``ok``.
    """
    if not probe.configured():
        return ProbeResult(probe.key, "not_configured", probe.not_configured_reason)

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(probe.check)
        try:
            future.result(timeout=deadline_ms / 1000)
        except FutureTimeoutError:
            return ProbeResult(
                probe.key, "failed", f"exceeded the {deadline_ms:.0f}ms deadline"
            )
        except ToolDriverError as err:
            return ProbeResult(probe.key, "failed", f"{err.error_class}: {err}")
        except Exception as err:  # noqa: BLE001 - any fault is a failed probe
            return ProbeResult(probe.key, "failed", f"{type(err).__name__}: {err}")
        return ProbeResult(probe.key, "ok", None)
    finally:
        pool.shutdown(wait=False)


def run_probes(
    probes: Sequence[Probe] = PROBES, *, deadline_ms: float = PROBE_DEADLINE_MS
) -> list[ProbeResult]:
    """Run every probe once. Never raises -- each probe's fault becomes a result."""
    return [_run_one(probe, deadline_ms=deadline_ms) for probe in probes]


def probe_one(key: str, *, deadline_ms: float = PROBE_DEADLINE_MS) -> ProbeResult:
    """Run the single probe for ``key`` (S17 on-demand re-probe, FR-25).

    The reconnect flows (both the Composio OAuth return and the static-token env
    rotation) want a FRESH badge now, not on the next 15-min scheduled cycle. Reuses
    the exact same per-integration wiring the scheduled job runs -- same
    ``configured`` gate, same authenticated ``check``, same three honest states -- so
    a manual re-probe cannot report anything the scheduled one wouldn't.
    """
    for probe in PROBES:
        if probe.key == key:
            return _run_one(probe, deadline_ms=deadline_ms)
    raise KeyError(f"no integration probe for '{key}'")


def write_probe_rows(
    cur, results: Sequence[ProbeResult], retention_days: int = PROBE_RETENTION_DAYS
) -> None:
    """Insert probe rows + prune history on a CALLER-OWNED cursor (no commit).

    The S17 re-probe handler writes through the datastore driver's single unit of
    work (which commits once, around the whole handler), so it needs the cursor-level
    write WITHOUT :func:`record_probe_results`' own connection + commit -- otherwise
    the probe row would land in a separate transaction from its audit row.
    """
    _write_probe_results(cur, results, retention_days)


def _write_probe_results(
    cur, results: Sequence[ProbeResult], retention_days: int
) -> None:
    """Insert one cycle and prune history beyond the window, on a caller's cursor."""
    cur.executemany(
        "INSERT INTO integration_probe (integration_key, status, reason) "
        "VALUES (%s, %s, %s)",
        [(r.key, r.status, r.reason) for r in results],
    )
    cur.execute(
        "DELETE FROM integration_probe "
        "WHERE checked_at < now() - make_interval(days => %s)",
        (retention_days,),
    )


def record_probe_results(
    results: Sequence[ProbeResult],
    *,
    conn=None,
    retention_days: int = PROBE_RETENTION_DAYS,
) -> None:
    """Persist one probe cycle and prune history beyond the retention window.

    Two connection modes, like :class:`PostgresJobQueue`: a caller-owned ``conn``
    (tests, a single isolated schema) or a fresh direct connection (production).
    Unlike the fire-and-forget metric emit, this DOES raise on a write failure: the
    probe job must fail (and retry/dead-letter) rather than report success on a cycle
    the page never saw. Insert + prune in one transaction.

    # ponytail: a fresh direct connection per cycle (like metric emit), not the
    # pool -- this runs at most a few times an hour on the background worker, so a
    # pooled slot buys nothing. Pool it only if the cadence ever grows enough to
    # matter.
    """
    if conn is not None:
        with conn.cursor() as cur:
            _write_probe_results(cur, results, retention_days)
        conn.commit()
        return
    with psycopg.connect(database_url()) as fresh:
        with fresh.cursor() as cur:
            _write_probe_results(cur, results, retention_days)
        fresh.commit()


def run_integration_probe_job(payload: Mapping[str, object]) -> None:
    """The ``integration_probe`` job body (S16). Run all probes, record, alert.

    A ``failed`` probe emits a structured ERROR line (alert-greppable) carrying the
    integration key and the secret-free reason. ``not_configured`` is the expected
    owner-blocked state today, so it logs at INFO, not as an alert. The job succeeds
    once the results are recorded; a DB write failure raises so the job retries.
    """
    del payload  # scheduled job; the (schedule_window, window_start) payload is unused
    results = run_probes()
    record_probe_results(results)
    for result in results:
        if result.status == "failed":
            logger.error(
                "integration probe FAILED key=%s reason=%s", result.key, result.reason
            )
        elif result.status == "not_configured":
            logger.info("integration probe skipped key=%s (not configured)", result.key)
        else:
            logger.info("integration probe ok key=%s", result.key)
