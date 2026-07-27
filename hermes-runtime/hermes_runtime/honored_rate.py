"""Scheduled honored-rate judge job (0.0.4 S22, FR-31).

Closes S21's honored-rate gap. The tile was an honestly-labelled non-live
PLACEHOLDER (``datastore/handlers/metrics.py``) because the rate genuinely
cannot be computed inline -- it needs an LLM judge call over sampled live turns,
not a SQL aggregation. This slice makes it live: a NEW recurring ``honored_rate``
job on the SAME ``(type, window)`` schedule tick the background worker already
runs (S01/S04) samples recent memory-injection turns, runs the S27-tuned judge's
HONORED leg over the sample, and persists ONE aggregate row the metrics handler
serves. Closest prior-art is S16's ``integration_probe`` (a scheduled typed job
that persists a result the panel reads) -- this mirrors its structure.

**Reuses the judge's HONORED leg (S20).** ``client`` is the injected
:class:`eval_runner.judge.JudgeClient` boundary -- a SCRIPTED client in tests, the
real ``OpenRouterJudgeClient`` (keyed by ``OPENROUTER_API_KEY``) in prod. Same
``judge_reply(..., leg="honored")`` call the advisory report uses.

**Fail-closed, worker never crashes (S20 posture).** No ``OPENROUTER_API_KEY`` ->
the job SKIPS with a structured note and persists nothing (the panel keeps its
last good aggregate, or "not yet computed" if none) -- it does not fabricate a
rate. A judge/API fault propagates so the job retries then dead-letters (S01
inherited), rather than persisting a wrong rate. Either way the last good
aggregate and its (now stale) "as of" survive.

**Honest states (never a fabricated number):**
- No aggregate row at all  -> "not yet computed" (never run, or every run skipped).
- A row with rate == None   -> a real sample scored nothing determinate (all
                               undetermined); shown as "-" over that sample, not 0.
- A capped run              -> ``sample_size`` + ``candidate_total`` make the
                               partial sample legible; the rate is over the sample,
                               never presented as the whole population.

**No silent truncation (FR-31).** The eligible population is counted BEFORE the
per-run cap; the job logs sampled-vs-skipped when the cap bites.

**S21 (0.0.5, FR-28) -- more legs, same sample.** The job now runs every leg in
:data:`JUDGE_LEGS` over the SAME sampled transcripts: the honored leg (unchanged,
still the tile's number and still in its own columns) plus the two new advisory
legs and the adversarial safety leg. Per-leg counts persist in the aggregate's
``leg_results`` for 0.0.5 S22/S26 to read. Nothing here gates -- including the
safety leg: a stored score can only ever report. The safety leg's gating half is
the deterministic marker check inside the CI replay gate
(``eval_runner.assertions._eval_safety``), which makes no model call.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from eval_runner.judge import JudgeClient, JudgeLeg, judge_reply, resolve_judge_model

from .datastore.config import database_url
from .datastore.pool import get_database_pool
from .openrouter import openrouter_configured

logger = logging.getLogger(__name__)

# The CADENCE (interval/window) is a scheduling policy and lives with the schedule
# in `background_worker.SCHEDULES`, mirroring retention/integration_probe.

# ponytail: 7-day lookback for the sample. Honored rate is a quality trend, not a
# health signal -- a week smooths per-day traffic noise into a stable rate while
# staying "recent". Widen if a run's candidate population is routinely too small.
DEFAULT_WINDOW_SECONDS = 7 * 24 * 60 * 60

# The COST BOUND (FR-31): at most this many TRANSCRIPTS per run. Each transcript
# costs one billed OpenRouter completion PER LEG (S21), so a run's spend is
# `cap * len(JUDGE_LEGS)` completions -- 200 at today's values, up from 50 when
# the honored leg ran alone. The cap stays expressed in transcripts because that
# is what the sample means; the eligible population is counted before it and the
# gap is logged (no silent truncation). Raise it only if a wider sample is worth
# the linear cost, and remember the multiplier when you do.
SAMPLE_CAP = 50

# Every leg the scheduled job scores, in report order (S21, 0.0.5 FR-28). The
# honored leg keeps its dedicated aggregate columns; all legs (honored included)
# also land in `leg_results` so a reader never has to special-case one of them.
# Each name is phrased so a PASS means the agent behaved well, so a
# misapplication/stale-use RATE is `1 - passed/determinate` (see JudgeLeg).
JUDGE_LEGS: tuple[JudgeLeg, ...] = (
    "honored",
    "no_misapplication",
    "no_stale_use",
    "injection_resisted",
)

HONORED_LEG: JudgeLeg = "honored"


@dataclass(frozen=True)
class Transcript:
    """One judged unit: a Hermes reply plus the Customer Memory injected into its
    turn. ``injected_memory`` is ``{slot_name: slot_value}`` -- what the judge's
    honored leg checks the reply against."""

    reply: str
    injected_memory: dict[str, str]


@dataclass(frozen=True)
class HonoredRateAggregate:
    """One run's aggregate. ``rate`` is derived (honored / sample_size), ``None``
    when no transcript scored determinate.

    ``leg_results`` (S21) is ``{leg: {"passed", "determinate", "undetermined"}}``
    over the same sample, for every leg in :data:`JUDGE_LEGS` -- advisory data
    for 0.0.5 S22/S26, never a gate. It defaults to empty so a caller that only
    cares about the honored leg (and every pre-S21 row) still constructs.
    """

    honored_count: int
    sample_size: int
    undetermined_count: int
    candidate_total: int
    window_seconds: int
    leg_results: Mapping[str, Mapping[str, int]] = field(default_factory=dict)

    @property
    def rate(self) -> Optional[float]:
        return round(self.honored_count / self.sample_size, 4) if self.sample_size else None


# The Honored-rate tile's label when no aggregate has ever been persisted -- the
# honest "not yet computed" state, NEVER a fabricated rate or a silent zero.
NOT_COMPUTED_LABEL = (
    "Honored rate is advisory and judge-sampled (S22/S27, C7 core question) -- "
    "never gating. Not yet computed: the scheduled honored_rate job has not "
    "persisted an aggregate (no OPENROUTER_API_KEY, or no eligible transcripts "
    "sampled yet)."
)


def _live_label(agg: Mapping[str, Any]) -> str:
    """Provenance line for a computed aggregate: sample vs population + as-of."""
    return (
        "Advisory, judge-sampled honored leg over "
        f"{agg['sample_size']} of {agg['candidate_total']} recent memory-injection "
        f"turns (undetermined: {agg['undetermined_count']}); as of {agg['as_of']}."
    )


def sample_transcripts(
    cur, *, window_seconds: int = DEFAULT_WINDOW_SECONDS, cap: int = SAMPLE_CAP
) -> tuple[list[Transcript], int]:
    """Sample recent memory-injection transcripts on a caller-owned cursor.

    Returns ``(transcripts, candidate_total)`` where ``candidate_total`` is the
    FULL eligible population in the window (before the cap) so the caller can log
    sampled-vs-skipped -- ``len(transcripts) < candidate_total`` means the cap bit.

    Eligible = a Hermes outbound reply whose customer thread has Customer Memory
    slots (i.e. memory was available to inject that turn), newest first, capped.

    # ponytail: the thread->slots join reconstructs the memory binding key from the
    # thread's persisted channel/identity (`binding_key_from_identity`'s provisional
    # form) and its verified Shopify id. message_turn does not record the injected
    # memory per-turn, so this is the honest available signal. If the channel
    # literal ever drifts between the write-time binding and the persisted thread
    # channel, the upgrade path is a per-turn injected-memory record on message_turn
    # -- not a fancier join. Owner-blocked today (no live traffic), so untested
    # against real data, exactly like S16's live probe wire.
    """
    cur.execute(
        """
        SELECT mt.id
        FROM message_turn mt
        JOIN customer_thread ct ON ct.id = mt.customer_thread_id
        WHERE mt.direction = 'outbound'
          AND mt.author = 'hermes'
          AND mt.body <> ''
          AND mt.created_at >= now() - make_interval(secs => %s)
          AND EXISTS (
              SELECT 1 FROM customer_memory_slot cms
              WHERE cms.binding_key
                        = 'provisional:' || ct.channel || ':' || ct.channel_identity
                 OR (ct.shopify_customer_id IS NOT NULL
                     AND cms.binding_key = ct.shopify_customer_id)
          )
        ORDER BY mt.created_at DESC
        """,
        (window_seconds,),
    )
    turn_ids = [row[0] for row in cur.fetchall()]
    candidate_total = len(turn_ids)
    sampled_ids = turn_ids[:cap]
    if not sampled_ids:
        return [], candidate_total

    cur.execute(
        """
        SELECT mt.id, mt.body, cms.slot_name, cms.slot_value
        FROM message_turn mt
        JOIN customer_thread ct ON ct.id = mt.customer_thread_id
        JOIN customer_memory_slot cms
          ON cms.binding_key = 'provisional:' || ct.channel || ':' || ct.channel_identity
          OR (ct.shopify_customer_id IS NOT NULL
              AND cms.binding_key = ct.shopify_customer_id)
        WHERE mt.id = ANY(%s)
        """,
        (sampled_ids,),
    )
    replies: dict[str, str] = {}
    memory: dict[str, dict[str, str]] = {}
    for turn_id, body, slot_name, slot_value in cur.fetchall():
        replies[turn_id] = body
        memory.setdefault(turn_id, {})[slot_name] = slot_value

    # Preserve the newest-first order of the sampled ids.
    return (
        [Transcript(replies[tid], memory[tid]) for tid in sampled_ids if tid in replies],
        candidate_total,
    )


def measure_honored_rate(
    transcripts: Sequence[Transcript],
    *,
    client: JudgeClient,
    candidate_total: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    model: Optional[str] = None,
) -> HonoredRateAggregate:
    """Run EVERY leg in :data:`JUDGE_LEGS` over ``transcripts``; aggregate them.

    An ``undetermined`` verdict (the judge could not score it) is counted but does
    NOT enter that leg's denominator -- each leg's rate is over the transcripts it
    scored determinately, never inflated or deflated by a verdict the judge itself
    declined to make. The honored leg's counts additionally fill the aggregate's
    dedicated columns, so the shipped tile reads exactly as it did before S21.

    Named for the honored rate it has always produced; S21 widened what it scores
    rather than adding a second near-identical sweep over the same sample.
    """
    counts = {
        leg: {"passed": 0, "determinate": 0, "undetermined": 0} for leg in JUDGE_LEGS
    }
    for transcript in transcripts:
        for leg in JUDGE_LEGS:
            verdict = judge_reply(
                reply=transcript.reply,
                leg=leg,
                injected_memory=transcript.injected_memory or None,
                client=client,
                model=model,
            )
            if verdict.passed is None:
                counts[leg]["undetermined"] += 1
            else:
                counts[leg]["determinate"] += 1
                if verdict.passed:
                    counts[leg]["passed"] += 1
    honored = counts[HONORED_LEG]
    return HonoredRateAggregate(
        honored_count=honored["passed"],
        sample_size=honored["determinate"],
        undetermined_count=honored["undetermined"],
        candidate_total=candidate_total,
        window_seconds=window_seconds,
        leg_results=counts,
    )


def record_honored_rate_aggregate(cur, agg: HonoredRateAggregate) -> None:
    """Insert one aggregate row on a CALLER-OWNED cursor (no commit).

    Rides the job's pooled connection and commits in the job's transaction
    (S21/S29 pooled-connection discipline) -- never its own unpooled connection.
    """
    cur.execute(
        """
        INSERT INTO honored_rate_aggregate
            (honored_count, sample_size, undetermined_count, candidate_total,
             window_seconds, leg_results)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            agg.honored_count,
            agg.sample_size,
            agg.undetermined_count,
            agg.candidate_total,
            agg.window_seconds,
            # Serialized here rather than via a driver adapter so the one INSERT
            # behaves identically on any psycopg configuration.
            json.dumps(dict(agg.leg_results)),
        ),
    )


def honored_rate_metric(cur) -> dict[str, Any]:
    """The Honored-rate tile's payload from the LATEST aggregate, on a caller cursor.

    Never raises on a missing row and never fabricates a number: with no aggregate
    it returns the honest ``live=False`` "not yet computed" state; with one it
    returns the live rate plus provenance (sample size, population, window, as-of).
    Shared by the datastore metrics handler and its tests -- one source for the
    tile's shape so the handler and the mock twin cannot drift.
    """
    cur.execute(
        """
        SELECT honored_count, sample_size, undetermined_count, candidate_total,
               window_seconds, computed_at, leg_results
        FROM honored_rate_aggregate
        ORDER BY computed_at DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if row is None:
        return {
            "live": False,
            "rate": None,
            "sample_size": None,
            "candidate_total": None,
            "undetermined_count": None,
            "window_seconds": None,
            "as_of": None,
            # S21: advisory per-leg counts; empty is the honest "no breakdown",
            # the same stance as a None rate. Key present in BOTH branches (and
            # in the mock twin) so the BFF mapper never sees a missing field.
            "leg_results": {},
            "label": NOT_COMPUTED_LABEL,
        }
    (
        honored_count,
        sample_size,
        undetermined_count,
        candidate_total,
        window_seconds,
        computed_at,
        leg_results,
    ) = row
    agg = {
        "live": True,
        "rate": round(honored_count / sample_size, 4) if sample_size else None,
        "sample_size": sample_size,
        "candidate_total": candidate_total,
        "undetermined_count": undetermined_count,
        "window_seconds": window_seconds,
        "as_of": computed_at.isoformat(),
        "leg_results": leg_results if isinstance(leg_results, dict) else {},
    }
    agg["label"] = _live_label(agg)
    return agg


def _build_live_judge_client() -> JudgeClient:
    """The real OpenRouter-backed judge client (only when a key is present)."""
    from .judge_eval import OpenRouterJudgeClient
    from .openrouter import resolve_openrouter_config

    config = resolve_openrouter_config()
    return OpenRouterJudgeClient(base_url=config.base_url, api_key=config.api_key)


def run_honored_rate_job(
    payload: Mapping[str, Any],
    *,
    client: Optional[JudgeClient] = None,
    conn: Optional[Any] = None,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    cap: int = SAMPLE_CAP,
) -> None:
    """The ``honored_rate`` job body (S22). Sample -> judge honored leg -> persist.

    ``client``/``conn`` are injectable for tests (a scripted judge, an isolated-
    schema connection); production passes neither -- the live OpenRouter client is
    built here and a pooled connection is taken from the process pool.

    Fail-closed: no ``OPENROUTER_API_KEY`` (and no injected client) -> SKIP with a
    structured note, persist NOTHING. No eligible transcripts -> SKIP likewise. A
    judge/API fault is NOT caught here -- it propagates so the job retries then
    dead-letters (S01), never persisting a wrong rate.
    """
    del payload  # scheduled job; the (schedule_window, window_start) payload is unused.

    judge = client
    if judge is None:
        if not openrouter_configured():
            logger.warning(
                "honored_rate skipped: OPENROUTER_API_KEY not configured. No "
                "aggregate persisted; the panel keeps its last good rate (or "
                "'not yet computed'). Set the key to light this up, no code change."
            )
            return
        judge = _build_live_judge_client()
    model = resolve_judge_model()

    if conn is not None:
        _sample_judge_persist(conn, judge, model, window_seconds, cap)
        return
    # Pooled connection (S29/S21 discipline), never an unpooled connect. The worker
    # loop is sequential -- one job at a time -- so holding this one slot across the
    # judge calls costs nothing; the pool has headroom (4). ponytail: revisit only
    # if this worker ever runs jobs concurrently.
    with get_database_pool(database_url()).connection() as pooled:
        _sample_judge_persist(pooled, judge, model, window_seconds, cap)


def _sample_judge_persist(conn, judge, model, window_seconds, cap) -> None:
    with conn.cursor() as cur:
        transcripts, candidate_total = sample_transcripts(
            cur, window_seconds=window_seconds, cap=cap
        )
    if not transcripts:
        logger.info(
            "honored_rate skipped: %s eligible memory-injection transcript(s) in "
            "the %ss window; nothing to compute. No aggregate persisted.",
            candidate_total,
            window_seconds,
        )
        return

    if candidate_total > len(transcripts):
        logger.info(
            "honored_rate sampling cap bit: judging %s of %s eligible transcripts "
            "(cap=%s); %s skipped this run (no silent truncation -- the rate is over "
            "the sample).",
            len(transcripts),
            candidate_total,
            cap,
            candidate_total - len(transcripts),
        )

    agg = measure_honored_rate(
        transcripts,
        client=judge,
        candidate_total=candidate_total,
        window_seconds=window_seconds,
        model=model,
    )
    with conn.cursor() as cur:
        record_honored_rate_aggregate(cur, agg)
    conn.commit()
    logger.info(
        "honored_rate computed: honored=%s/%s (undetermined=%s) over %s of %s "
        "candidates; rate=%s; legs=%s",
        agg.honored_count,
        agg.sample_size,
        agg.undetermined_count,
        len(transcripts),
        candidate_total,
        agg.rate,
        # Advisory per-leg breakdown (S21) in the same line, so a run's legs are
        # legible from the worker log without querying the aggregate.
        {
            leg: f"{c['passed']}/{c['determinate']} (u={c['undetermined']})"
            for leg, c in agg.leg_results.items()
        },
    )
