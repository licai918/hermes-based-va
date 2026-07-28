"""0.0.5 S05 (FR-5, D6): L7 hit accounting + the live-Postgres vocabulary.

Two things this proves that the mock twin cannot:

1. **Hit accounting never touches the lexicon row in-turn.** D6 forbids a
   per-turn ``UPDATE`` of ``hit_count`` -- row-lock contention on the small hot
   set of confirmed entries, on the reply path NFR-5 protects. Applications
   append a ``lexicon_hit_event``; a scheduled rollup materializes the column.
2. **The rollup does not move ``updated_at``.** The console renders "(edited)"
   from ``updated_at > coalesce(decided_at, created_at)`` and the process cache
   keys on ``lexicon_version`` = ``MAX(updated_at)``. Both rest on an invariant
   nothing else writes down: only a CONTENT write moves that column. A rollup
   that stamped it would put a permanent false "edited" badge on every hot entry
   and invalidate the cache on hit traffic -- a cache and its own defeat in one
   slice.

Skip-if-no-DB via the shared ``datastore`` fixture; it executes for real in CI.
"""

from __future__ import annotations

import pytest
from toee_hermes.lexicon_seam import normalize_product_query

from hermes_runtime.lexicon_hits import (
    confirmed_lexicon_entries,
    lexicon_version,
    postgres_lexicon_vocabulary,
    record_lexicon_hits,
    roll_up_lexicon_hits,
    run_lexicon_hit_rollup_job,
)

TIRE_NORMALIZER_ID = "seed_lex_tire_size"
COMPANY_ALIAS_ID = "seed_lex_company_toee"
THREE_NOTATIONS = ("2055516", "205 55 16", "20555r16")
CANONICAL = "205/55R16"


def _row(conn, entry_id: str) -> tuple:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT hit_count, updated_at, status FROM semantic_lexicon WHERE id = %s",
            (entry_id,),
        )
        return cur.fetchone()


def _events(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT entry_id FROM lexicon_hit_event ORDER BY occurred_at, id")
        return [row[0] for row in cur.fetchall()]


# --- the write path is append-only -------------------------------------------


def test_a_hit_appends_an_event_and_leaves_the_lexicon_row_alone(datastore) -> None:
    _driver, conn, _ = datastore
    before = _row(conn, TIRE_NORMALIZER_ID)
    with conn.cursor() as cur:
        record_lexicon_hits(cur, [TIRE_NORMALIZER_ID, TIRE_NORMALIZER_ID])
    conn.commit()
    assert _events(conn) == [TIRE_NORMALIZER_ID, TIRE_NORMALIZER_ID]
    # D6: no in-turn UPDATE. Not hit_count, and above all not updated_at.
    assert _row(conn, TIRE_NORMALIZER_ID) == before


def test_recording_no_hits_writes_nothing(datastore) -> None:
    _driver, conn, _ = datastore
    with conn.cursor() as cur:
        record_lexicon_hits(cur, [])
    conn.commit()
    assert _events(conn) == []


# --- the rollup ---------------------------------------------------------------


def test_the_rollup_materializes_hit_count_and_consumes_the_events(datastore) -> None:
    _driver, conn, _ = datastore
    with conn.cursor() as cur:
        record_lexicon_hits(cur, [TIRE_NORMALIZER_ID] * 3 + [COMPANY_ALIAS_ID])
    conn.commit()

    consumed, updated = roll_up_lexicon_hits(conn)
    conn.commit()

    assert (consumed, updated) == (4, 2)
    assert _row(conn, TIRE_NORMALIZER_ID)[0] == 3
    assert _row(conn, COMPANY_ALIAS_ID)[0] == 1
    assert _events(conn) == []


def test_the_rollup_does_not_move_updated_at(datastore) -> None:
    """The invariant the admin console's "(edited)" marker rests on.

    Delete the ``updated_at`` guard from the rollup's UPDATE and this goes red;
    nothing else in the repo would.
    """
    _driver, conn, _ = datastore
    before = _row(conn, TIRE_NORMALIZER_ID)[1]
    with conn.cursor() as cur:
        record_lexicon_hits(cur, [TIRE_NORMALIZER_ID])
    conn.commit()
    roll_up_lexicon_hits(conn)
    conn.commit()
    after_count, after_updated, _status = _row(conn, TIRE_NORMALIZER_ID)
    assert after_count == 1  # the rollup really did run
    assert after_updated == before


def test_hit_traffic_never_moves_the_lexicon_version(datastore) -> None:
    # The cache S05/S06 key on is MAX(updated_at). If hit accounting moved it,
    # every hot entry would invalidate the cache continuously for no semantic
    # change -- the second half of why the rollup leaves updated_at alone.
    _driver, conn, _ = datastore
    with conn.cursor() as cur:
        before = lexicon_version(cur)
        record_lexicon_hits(cur, [TIRE_NORMALIZER_ID])
    conn.commit()
    roll_up_lexicon_hits(conn)
    conn.commit()
    with conn.cursor() as cur:
        assert lexicon_version(cur) == before


def test_the_rollup_is_idempotent_across_runs(datastore) -> None:
    _driver, conn, _ = datastore
    with conn.cursor() as cur:
        record_lexicon_hits(cur, [TIRE_NORMALIZER_ID] * 2)
    conn.commit()
    roll_up_lexicon_hits(conn)
    conn.commit()
    roll_up_lexicon_hits(conn)
    conn.commit()
    assert _row(conn, TIRE_NORMALIZER_ID)[0] == 2


def test_hit_counts_accumulate_across_rollups(datastore) -> None:
    _driver, conn, _ = datastore
    for _ in range(2):
        with conn.cursor() as cur:
            record_lexicon_hits(cur, [TIRE_NORMALIZER_ID])
        conn.commit()
        roll_up_lexicon_hits(conn)
        conn.commit()
    assert _row(conn, TIRE_NORMALIZER_ID)[0] == 2


def test_an_event_for_an_unknown_entry_is_consumed_without_failing(datastore) -> None:
    # No foreign key, on purpose (see the migration): an FK insert takes a lock
    # on the parent row, which is exactly the per-turn contention D6 forbids.
    # The cost is an orphan event, and it must not wedge the rollup.
    _driver, conn, _ = datastore
    with conn.cursor() as cur:
        record_lexicon_hits(cur, ["lex_gone", TIRE_NORMALIZER_ID])
    conn.commit()
    consumed, updated = roll_up_lexicon_hits(conn)
    conn.commit()
    assert (consumed, updated) == (2, 1)
    assert _events(conn) == []


def test_the_rollup_job_records_its_run(datastore) -> None:
    _driver, conn, _ = datastore
    with conn.cursor() as cur:
        record_lexicon_hits(cur, [TIRE_NORMALIZER_ID])
    conn.commit()
    run_lexicon_hit_rollup_job({}, conn=conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT details FROM workbench_audit_log WHERE action = 'lexicon_hit_rollup'"
        )
        (details,) = cur.fetchone()
    assert details["consumed"] == 1
    assert _row(conn, TIRE_NORMALIZER_ID)[0] == 1


# --- the live-Postgres vocabulary --------------------------------------------


def test_the_vocabulary_reads_confirmed_rows_only(datastore) -> None:
    _driver, conn, _ = datastore
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE semantic_lexicon SET status = 'retired' WHERE id = %s",
            (COMPANY_ALIAS_ID,),
        )
        conn.commit()
        rows = confirmed_lexicon_entries(cur)
    ids = {row["id"] for row in rows}
    assert TIRE_NORMALIZER_ID in ids
    assert COMPANY_ALIAS_ID not in ids
    assert {row["status"] for row in rows} == {"confirmed"}


def test_the_version_moves_on_a_governed_decision(datastore) -> None:
    _driver, conn, _ = datastore
    with conn.cursor() as cur:
        before = lexicon_version(cur)
        cur.execute(
            "UPDATE semantic_lexicon SET updated_at = now() WHERE id = %s",
            (TIRE_NORMALIZER_ID,),
        )
        conn.commit()
        assert lexicon_version(cur) != before


@pytest.mark.parametrize("notation", THREE_NOTATIONS)
def test_each_notation_normalizes_against_the_live_seeded_vocabulary(
    datastore, notation: str
) -> None:
    """The flagship, against the REAL seeded rows rather than a fixture.

    Migration 0024's rows are what a customer's text actually meets in
    production; a mock-only proof would pass even if the seed's ``entry_kind``
    or ``status`` were wrong for the reader.
    """
    _driver, conn, _ = datastore
    vocabulary = postgres_lexicon_vocabulary(conn=conn)
    normalization = normalize_product_query(
        "search_products", {"query": notation}, vocabulary.entries()
    )
    assert normalization.params["query"] == CANONICAL
    assert normalization.entry_ids == (TIRE_NORMALIZER_ID,)


def test_a_retired_seed_row_stops_applying_on_the_next_request(datastore) -> None:
    _driver, conn, _ = datastore
    vocabulary = postgres_lexicon_vocabulary(conn=conn)
    assert normalize_product_query(
        "search_products", {"query": "20555r16"}, vocabulary.entries()
    ).canonical == CANONICAL

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE semantic_lexicon SET status = 'retired', updated_at = now() "
            "WHERE id = %s",
            (TIRE_NORMALIZER_ID,),
        )
    conn.commit()

    # No cache flush anywhere: the version probe sees the bump on the very next
    # read and the entry stops applying immediately.
    assert (
        normalize_product_query(
            "search_products", {"query": "20555r16"}, vocabulary.entries()
        ).canonical
        is None
    )


def test_the_rollup_is_actually_scheduled_and_runnable() -> None:
    # A rollup nothing runs is a hit_count that never moves, and two later slices
    # read that column as usage. No database needed for this one.
    from hermes_runtime.background_worker import (
        BACKGROUND_JOB_TYPES,
        SCHEDULES,
        job_bodies,
    )
    from hermes_runtime.job_queue import LEXICON_HIT_ROLLUP_JOB_TYPE

    assert LEXICON_HIT_ROLLUP_JOB_TYPE in BACKGROUND_JOB_TYPES
    assert LEXICON_HIT_ROLLUP_JOB_TYPE in job_bodies()
    assert any(s.job_type == LEXICON_HIT_ROLLUP_JOB_TYPE for s in SCHEDULES)


def test_the_vocabulary_is_installed_only_on_the_datastore_backend(monkeypatch) -> None:
    from toee_hermes import lexicon_seam

    from hermes_runtime.lexicon_hits import install_postgres_lexicon_vocabulary

    monkeypatch.setattr(lexicon_seam, "_installed_vocabulary", None)
    monkeypatch.setenv("TOOL_BACKEND", "mock")
    install_postgres_lexicon_vocabulary()
    assert lexicon_seam.current_lexicon_vocabulary() is None

    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    install_postgres_lexicon_vocabulary()
    assert lexicon_seam.current_lexicon_vocabulary() is not None
    # Leave the process as we found it: this is a module-level singleton.
    lexicon_seam.install_lexicon_vocabulary(None)


def test_the_vocabulary_writes_hits_through_the_append_only_path(datastore) -> None:
    _driver, conn, _ = datastore
    before = _row(conn, TIRE_NORMALIZER_ID)
    postgres_lexicon_vocabulary(conn=conn).record_hits([TIRE_NORMALIZER_ID])
    assert _events(conn) == [TIRE_NORMALIZER_ID]
    assert _row(conn, TIRE_NORMALIZER_ID) == before
