"""0.0.4 S22 (FR-31): scheduled honored-rate judge job.

Two layers, mirroring S16's integration_probe test posture:

- The sample -> judge honored leg -> aggregate flow, the cap/skip logging, the
  fail-closed no-key path and the honest never-run state are exercised with a
  SCRIPTED judge client (no network, no OPENROUTER_API_KEY) -- a wrong verdict can
  only be one the script wrote.
- Sampling, persistence and the metrics-handler read are exercised live-Postgres
  against an isolated schema (the ``datastore`` fixture applies migration 0017).

The job is a plain typed job (no entry in the replay/concurrency blocklists), so it
inherits S01's retry/dead-letter on a judge/API fault -- asserted structurally.
"""

from __future__ import annotations

import pytest

from hermes_runtime.background_worker import BACKGROUND_JOB_TYPES, SCHEDULES, job_bodies
from hermes_runtime.datastore.handlers.metrics import _get_aggregate_metrics
from hermes_runtime.honored_rate import (
    JUDGE_LEGS,
    HonoredRateAggregate,
    Transcript,
    honored_rate_metric,
    measure_honored_rate,
    record_honored_rate_aggregate,
    run_honored_rate_job,
    sample_transcripts,
)
from hermes_runtime.job_queue import (
    HONORED_RATE_JOB_TYPE,
    NON_CONCURRENT_JOB_TYPES,
    REPLAY_BLOCKED_JOB_TYPES,
)
from toee_hermes.tool_gate import ToolExecutionContext

_CTX = ToolExecutionContext(profile="supervisor_admin")


class _ScriptedJudge:
    """A JudgeClient that answers a fixed verdict per reply substring.

    ``{reply_substring: "yes"|"no"|"undetermined"}``. Anything unmatched is
    undetermined -- the judge declining to score, not a crash.
    """

    def __init__(self, verdicts: dict[str, str]) -> None:
        self._verdicts = verdicts

    def complete(self, prompt: str, *, model: str) -> str:
        for needle, token in self._verdicts.items():
            if needle in prompt:
                return f'{{"verdict": "{token}", "reason": "scripted"}}'
        return '{"verdict": "undetermined", "reason": "unscripted"}'


# --------------------------------------------------------------------------
# the sample -> judge -> aggregate flow (DB-free, scripted verdicts)
# --------------------------------------------------------------------------


def test_measure_scores_the_honored_leg_over_the_sample() -> None:
    transcripts = [
        Transcript("ZZQ_A honored", {"contact_time_preference": "after 2pm"}),
        Transcript("ZZQ_B honored", {"channel_preference": "sms"}),
        Transcript("ZZQ_C ignored", {"contact_time_preference": "mornings"}),
    ]
    judge = _ScriptedJudge({"ZZQ_A": "yes", "ZZQ_B": "yes", "ZZQ_C": "no"})

    agg = measure_honored_rate(transcripts, client=judge, candidate_total=3)

    assert agg.honored_count == 2
    assert agg.sample_size == 3
    assert agg.undetermined_count == 0
    assert agg.rate == pytest.approx(0.6667, abs=1e-4)


def test_undetermined_verdicts_are_excluded_from_the_rate_denominator() -> None:
    # A verdict the judge can't make is counted but never enters the rate -- the
    # rate is over what was scored determinately, not inflated or deflated.
    transcripts = [
        Transcript("ZZQ_clear honored", {"channel_preference": "sms"}),
        Transcript("ZZQ_ambiguous", {"channel_preference": "sms"}),
    ]
    judge = _ScriptedJudge({"ZZQ_clear": "yes", "ZZQ_ambiguous": "undetermined"})

    agg = measure_honored_rate(transcripts, client=judge, candidate_total=2)

    assert agg.honored_count == 1
    assert agg.sample_size == 1  # only the determinate one
    assert agg.undetermined_count == 1
    assert agg.rate == 1.0


def test_rate_is_none_when_nothing_scored_determinate() -> None:
    # An all-undetermined sample is an honest None over a real sample, never a 0.
    judge = _ScriptedJudge({})  # everything unscripted -> undetermined
    agg = measure_honored_rate(
        [Transcript("x", {"channel_preference": "sms"})], client=judge, candidate_total=1
    )
    assert agg.rate is None
    assert agg.sample_size == 0 and agg.undetermined_count == 1


# --------------------------------------------------------------------------
# S21 (0.0.5 FR-28): the new legs ride the same sample into the aggregate
# --------------------------------------------------------------------------


def test_every_judge_leg_is_scored_over_the_same_sample() -> None:
    transcripts = [Transcript("ZZQ_A reply", {"contact_time_preference": "after 2pm"})]
    judge = _ScriptedJudge({"ZZQ_A": "yes"})

    agg = measure_honored_rate(transcripts, client=judge, candidate_total=1)

    assert set(agg.leg_results) == set(JUDGE_LEGS)
    for leg in JUDGE_LEGS:
        assert agg.leg_results[leg] == {
            "passed": 1,
            "determinate": 1,
            "undetermined": 0,
        }, leg
    # The honored columns stay the honored leg's own counts (no drift).
    assert agg.honored_count == agg.leg_results["honored"]["passed"]
    assert agg.sample_size == agg.leg_results["honored"]["determinate"]


def test_a_leg_the_judge_cannot_score_is_undetermined_not_a_failure() -> None:
    # Per-leg undetermined never inflates or deflates the leg's own rate -- the
    # same honesty rule the honored leg already holds to.
    transcripts = [Transcript("ZZQ_B reply", {"channel_preference": "sms"})]

    class _OnlyHonored:
        def complete(self, prompt: str, *, model: str) -> str:
            if "Leg: honored" in prompt:
                return '{"verdict": "no", "reason": "scripted"}'
            return "not json at all"

    agg = measure_honored_rate(transcripts, client=_OnlyHonored(), candidate_total=1)

    assert agg.leg_results["honored"] == {
        "passed": 0,
        "determinate": 1,
        "undetermined": 0,
    }
    assert agg.leg_results["injection_resisted"] == {
        "passed": 0,
        "determinate": 0,
        "undetermined": 1,
    }


def test_the_dormant_stale_use_leg_never_reaches_the_aggregate() -> None:
    # S21 review, finding 3. `no_stale_use` is calibrated but has nothing to read
    # in production: no shipped code renders supersession into the injected
    # memory. Sampling it would spend ~50 completions a run to persist a ~100%
    # pass rate that a later memory-health panel would draw as health.
    assert "no_stale_use" not in JUDGE_LEGS
    assert "no_unprompted_recall" not in JUDGE_LEGS  # needs the inbound turn

    # ...and it stays CALIBRATED, so re-enabling is one line in JUDGE_LEGS: the
    # rubric still builds and the labelled fixtures are still there.
    from eval_runner.judge import build_judge_prompt
    from eval_runner.judge_fixtures import JUDGE_FIXTURES

    assert "Leg: no_stale_use" in build_judge_prompt(reply="x", leg="no_stale_use")
    assert [f for f in JUDGE_FIXTURES if f.leg == "no_stale_use"]


def test_leg_results_round_trip_through_the_aggregate_row(datastore) -> None:
    _driver, conn, _schema = datastore
    legs = {leg: {"passed": 2, "determinate": 3, "undetermined": 1} for leg in JUDGE_LEGS}
    with conn.cursor() as cur:
        record_honored_rate_aggregate(
            cur,
            HonoredRateAggregate(
                honored_count=2,
                sample_size=3,
                undetermined_count=1,
                candidate_total=9,
                window_seconds=604800,
                leg_results=legs,
            ),
        )
    conn.commit()

    with conn.cursor() as cur:
        metric = honored_rate_metric(cur)

    assert metric["leg_results"] == legs
    # Pre-S21 rows read as an honest empty map, never a zero rate. Insert one the
    # way a pre-S21 row actually arrived -- WITHOUT the column -- so migration
    # 0021's `DEFAULT '{}'::jsonb` is what produces the empty map. Going through
    # record_honored_rate_aggregate would send an explicit '{}' and never
    # exercise the default at all (S21 review).
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO honored_rate_aggregate
                (honored_count, sample_size, undetermined_count, candidate_total,
                 window_seconds)
            VALUES (1, 1, 0, 1, 604800)
            """
        )
    conn.commit()
    with conn.cursor() as cur:
        assert honored_rate_metric(cur)["leg_results"] == {}


def test_never_run_state_still_carries_the_leg_results_key(datastore) -> None:
    # The mock twin and the Postgres twin feed the same BFF mapper, so the
    # not-yet-computed shape must carry every key the live shape does (NFR-7).
    _driver, conn, _schema = datastore
    with conn.cursor() as cur:
        metric = honored_rate_metric(cur)
    assert metric["leg_results"] == {}

    from toee_hermes.drivers.mock.metrics import create_metrics_mock_handlers

    mock = create_metrics_mock_handlers()["toee_metrics"]["get_aggregate_metrics"]
    assert set(mock({}, _CTX)["honored_rate"]) == set(metric)


# --------------------------------------------------------------------------
# the job is a normal typed job -> inherits retry/dead-letter (structural)
# --------------------------------------------------------------------------


def test_job_is_scheduled_and_claimable_by_the_background_worker() -> None:
    assert HONORED_RATE_JOB_TYPE in BACKGROUND_JOB_TYPES
    assert HONORED_RATE_JOB_TYPE in {s.job_type for s in SCHEDULES}
    assert HONORED_RATE_JOB_TYPE in job_bodies()


def test_job_inherits_default_retry_and_dead_letter() -> None:
    # Not in either blocklist -> default max_attempts retry then dead-letter on a
    # judge/API fault (S01), and replayable from the S05 dead-letter view. This is
    # the "don't reinvent retry" assertion: a wrong rate never lands silently.
    assert HONORED_RATE_JOB_TYPE not in REPLAY_BLOCKED_JOB_TYPES
    assert HONORED_RATE_JOB_TYPE not in NON_CONCURRENT_JOB_TYPES


def test_job_fails_closed_without_a_key_and_persists_nothing(monkeypatch) -> None:
    # No OPENROUTER_API_KEY and no injected client -> skip-with-note, no judge call,
    # no persistence. A sentinel connection proves nothing touched the DB.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    class _Boom:
        def cursor(self, *a, **k):
            raise AssertionError("must not open a cursor when failing closed")

        def commit(self):
            raise AssertionError("must not commit when failing closed")

    # conn is provided but must never be used, because the key check returns first.
    run_honored_rate_job({"schedule_window": 1}, conn=_Boom())


# --------------------------------------------------------------------------
# persistence + the metrics-handler read (live Postgres, isolated schema)
# --------------------------------------------------------------------------


def _seed_injection_turn(conn, *, thread_key, channel, identity, reply, slots) -> None:
    """Seed the minimal rows sample_transcripts joins: a thread, an sms session, a
    Hermes outbound reply, and the customer's memory slots (so memory 'was
    injected')."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity) VALUES (%s, %s, %s)",
            (thread_key, channel, identity),
        )
        cur.execute(
            "INSERT INTO sms_session (id, customer_thread_id, expires_at) "
            "VALUES (%s, %s, now() + interval '1 day')",
            (f"sess:{thread_key}", thread_key),
        )
        cur.execute(
            "INSERT INTO message_turn (id, sms_session_id, customer_thread_id, "
            "direction, author, body) VALUES (%s, %s, %s, 'outbound', 'hermes', %s)",
            (f"turn:{thread_key}", f"sess:{thread_key}", thread_key, reply),
        )
        for slot_name, slot_value in slots.items():
            cur.execute(
                "INSERT INTO customer_memory_slot "
                "(id, binding_key, binding_kind, slot_name, slot_value, source) "
                "VALUES (%s, %s, 'provisional', %s, %s, 'customer_explicit')",
                (
                    f"slot:{thread_key}:{slot_name}",
                    f"provisional:{channel}:{identity}",
                    slot_name,
                    slot_value,
                ),
            )
    conn.commit()


def test_metric_is_honest_not_yet_computed_before_any_run(datastore) -> None:
    _driver, conn, _schema = datastore
    with conn.cursor() as cur:
        metric = honored_rate_metric(cur)
    assert metric["live"] is False
    assert metric["rate"] is None
    assert metric["sample_size"] is None and metric["as_of"] is None
    assert metric["label"]  # a non-empty honest label

    # And the whole aggregate-metrics payload carries that honest state, not a zero.
    payload = _get_aggregate_metrics(conn, {}, _CTX)
    assert payload["honored_rate"]["live"] is False
    assert payload["honored_rate"]["rate"] is None


def test_record_and_read_the_latest_aggregate(datastore) -> None:
    _driver, conn, _schema = datastore
    with conn.cursor() as cur:
        record_honored_rate_aggregate(
            cur,
            HonoredRateAggregate(
                honored_count=5,
                sample_size=6,
                undetermined_count=1,
                candidate_total=20,
                window_seconds=604800,
            ),
        )
    conn.commit()

    with conn.cursor() as cur:
        metric = honored_rate_metric(cur)
    assert metric["live"] is True
    assert metric["rate"] == pytest.approx(0.8333, abs=1e-4)
    assert metric["sample_size"] == 6
    assert metric["candidate_total"] == 20
    assert metric["undetermined_count"] == 1
    assert metric["as_of"]  # an ISO timestamp string
    # Provenance makes the partial sample legible (over the sample, not the pop).
    assert "6 of 20" in metric["label"]


def test_latest_row_supersedes_earlier_runs(datastore) -> None:
    _driver, conn, _schema = datastore
    for honored, size in [(1, 10), (9, 10)]:
        with conn.cursor() as cur:
            record_honored_rate_aggregate(
                cur,
                HonoredRateAggregate(honored, size, 0, size, 604800),
            )
        conn.commit()
    with conn.cursor() as cur:
        metric = honored_rate_metric(cur)
    # The panel reads the LATEST run (0.9), not the first (0.1).
    assert metric["rate"] == 0.9


def test_sampling_caps_and_reports_the_full_population(datastore) -> None:
    _driver, conn, _schema = datastore
    for i in range(5):
        _seed_injection_turn(
            conn,
            thread_key=f"customer_thread:sms:+1000000000{i}",
            channel="sms",
            identity=f"+1000000000{i}",
            reply=f"reply number {i}",
            slots={"contact_time_preference": "after 2pm"},
        )
    with conn.cursor() as cur:
        transcripts, candidate_total = sample_transcripts(cur, cap=2)
    # No silent truncation: population is the full 5, only 2 sampled under the cap.
    assert candidate_total == 5
    assert len(transcripts) == 2
    assert all(t.injected_memory == {"contact_time_preference": "after 2pm"} for t in transcripts)


def test_turns_without_memory_slots_are_not_eligible(datastore) -> None:
    _driver, conn, _schema = datastore
    # A thread whose reply exists but has NO memory slots -> memory was not
    # injected -> not part of the honored-rate population.
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity) "
            "VALUES ('customer_thread:sms:+19999999999', 'sms', '+19999999999')"
        )
        cur.execute(
            "INSERT INTO sms_session (id, customer_thread_id, expires_at) "
            "VALUES ('s1', 'customer_thread:sms:+19999999999', now() + interval '1 day')"
        )
        cur.execute(
            "INSERT INTO message_turn (id, sms_session_id, customer_thread_id, "
            "direction, author, body) VALUES ('t1', 's1', "
            "'customer_thread:sms:+19999999999', 'outbound', 'hermes', 'no-memory reply')"
        )
    conn.commit()
    with conn.cursor() as cur:
        transcripts, candidate_total = sample_transcripts(cur)
    assert candidate_total == 0 and transcripts == []


def test_job_samples_judges_and_persists_end_to_end(datastore) -> None:
    _driver, conn, _schema = datastore
    _seed_injection_turn(
        conn,
        thread_key="customer_thread:sms:+15550000001",
        channel="sms",
        identity="+15550000001",
        reply="Absolutely, I'll reach out after 2pm as you prefer.",
        slots={"contact_time_preference": "after 2pm"},
    )
    judge = _ScriptedJudge({"after 2pm as you prefer": "yes"})

    # Inject the scripted judge + the isolated-schema connection (production builds
    # the live client and takes a pooled connection).
    run_honored_rate_job({"schedule_window": 1}, client=judge, conn=conn)

    with conn.cursor() as cur:
        metric = honored_rate_metric(cur)
    assert metric["live"] is True
    assert metric["rate"] == 1.0
    assert metric["sample_size"] == 1 and metric["candidate_total"] == 1

    # The admin panel now serves the live rate, not the placeholder.
    payload = _get_aggregate_metrics(conn, {}, _CTX)
    assert payload["honored_rate"]["live"] is True
    assert payload["honored_rate"]["rate"] == 1.0


def test_job_skips_persist_when_no_eligible_transcripts(datastore) -> None:
    _driver, conn, _schema = datastore
    judge = _ScriptedJudge({"anything": "yes"})
    # Empty schema -> no candidates -> nothing persisted, honest not-yet-computed.
    run_honored_rate_job({"schedule_window": 1}, client=judge, conn=conn)
    with conn.cursor() as cur:
        assert honored_rate_metric(cur)["live"] is False
