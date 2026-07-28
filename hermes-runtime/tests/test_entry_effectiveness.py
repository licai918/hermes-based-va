"""0.0.5 S26 (FR-31 / FR-6 upgrade clause): per-entry effectiveness + ranked selection.

Three things this pins that nothing else can:

1. **The join is an inner join, not a cross join.** Both sides carry several rows
   and a deliberate non-match, because a one-row-per-side fixture cannot tell the
   two apart -- the fixture-too-small defect class this iteration keeps finding.
2. **Every rate states its denominator, and the zero-denominator case is a
   ``None`` rate, never a 0.** A rate with no denominator is a count wearing a
   percentage sign.
3. **The ranked glossary strategy cannot starve an entry kind that earns few hits
   BY DESIGN.** A ``default_rule`` never earns a ``hit_count`` at all -- hits come
   from the deterministic seam, which only ever applies aliases and normalizers --
   so ANY selection ordered on hits alone evicts every seasonal default the moment
   a domain outgrows ``LEXICON_GLOSSARY_LIMIT``. The fixture therefore holds MORE
   than the limit, with defaults that lose on hits by construction.

Live-PG tests skip without a database locally and execute for real in CI.
"""

from __future__ import annotations

import pytest

from hermes_runtime.entry_effectiveness import (
    EXTERNAL_PATH_SCOPE,
    HEALTH_USAGE_SATURATION,
    HEALTH_WEIGHT_HONORED,
    HEALTH_WEIGHT_MISAPPLIED,
    HEALTH_WEIGHT_STALE,
    HEALTH_WEIGHT_USAGE,
    entry_effectiveness_for,
    record_judged_turns,
    refresh_entry_effectiveness,
)
from hermes_runtime.injection_ledger import LAYER_L6, LAYER_L7
from toee_hermes.drivers.mock.semantic_lexicon import (
    lexicon_entry_health,
    select_ranked_entries,
)

# ---------------------------------------------------------------------------
# the health formula (pure -- no database)
# ---------------------------------------------------------------------------


def _legs(**counts: tuple[int, int, int]) -> dict[str, dict[str, int]]:
    return {
        leg: {"passed": p, "determinate": d, "undetermined": u}
        for leg, (p, d, u) in counts.items()
    }


def test_every_rate_carries_its_own_numerator_and_denominator() -> None:
    health = lexicon_entry_health(
        hits=4,
        injections=6,
        leg_results=_legs(honored=(9, 10, 1), no_misapplication=(7, 8, 0)),
    )

    assert health["honored"] == {
        "rate": 0.9,
        "passed": 9,
        "determinate": 10,
        "undetermined": 1,
    }
    # A "misapplied" rate is the INVERSE of its leg: the leg is phrased so a pass
    # means the agent behaved well, so misapplication is 1 - passed/determinate.
    assert health["misapplied"]["rate"] == pytest.approx(0.125)
    assert health["misapplied"]["determinate"] == 8
    assert health["usage"] == {
        "hits": 4,
        "injections": 6,
        "saturation": HEALTH_USAGE_SATURATION,
    }


def test_a_leg_with_no_determinate_verdicts_has_a_none_rate_not_a_zero() -> None:
    # The zero-denominator case. `no_stale_use` is not in the production sampling
    # set today, so this is not hypothetical -- it is the live state of the stale
    # component, and reporting it as 0.0 would draw "never stale" on a panel.
    health = lexicon_entry_health(hits=0, injections=0, leg_results={})

    assert health["honored"]["rate"] is None
    assert health["misapplied"]["rate"] is None
    assert health["stale"]["rate"] is None
    assert health["honored"]["determinate"] == 0


def test_the_score_is_the_documented_weighted_sum() -> None:
    health = lexicon_entry_health(
        hits=5,
        injections=5,  # usage 10 == saturation -> the usage term is 1.0
        leg_results=_legs(honored=(8, 10, 0), no_misapplication=(9, 10, 0)),
    )
    expected = (
        HEALTH_WEIGHT_USAGE * 1.0
        + HEALTH_WEIGHT_HONORED * 0.8
        - HEALTH_WEIGHT_MISAPPLIED * 0.1
        - HEALTH_WEIGHT_STALE * 0.0
    )
    assert health["score"] == pytest.approx(expected)


def test_an_unjudged_entry_is_neither_credited_nor_punished_for_quality() -> None:
    # A never-judged entry scoring 0 on quality would be a RATCHET: low score ->
    # evicted from the glossary -> never injected -> never sampled -> never
    # judged. The neutral midpoint is what breaks that loop.
    unjudged = lexicon_entry_health(hits=10, injections=0, leg_results={})
    perfect = lexicon_entry_health(
        hits=10, injections=0, leg_results=_legs(honored=(10, 10, 0))
    )
    awful = lexicon_entry_health(
        hits=10, injections=0, leg_results=_legs(honored=(0, 10, 0))
    )
    assert awful["score"] < unjudged["score"] < perfect["score"]


def test_the_score_travels_with_its_scope_as_data() -> None:
    # S14's rule, applied to a score: the caveat is a FIELD, so no renderer can
    # drop it. Per-entry effectiveness is external-path only (D4.3) -- the copilot
    # draft turn's turn_ref is a synthetic id with no durable identity.
    health = lexicon_entry_health(hits=1, injections=1, leg_results={})
    assert health["scope"] == EXTERNAL_PATH_SCOPE
    assert "copilot" in EXTERNAL_PATH_SCOPE.lower()


# ---------------------------------------------------------------------------
# the ranked selection -- the FR-6 upgrade clause and its starvation guard
# ---------------------------------------------------------------------------


def _entry(entry_id: str, kind: str, *, hits: int = 0, health=None) -> dict:
    return {
        "id": entry_id,
        "domain": "tire",
        "entry_kind": kind,
        "surface_form": entry_id,
        "canonical_form": entry_id.upper(),
        "status": "confirmed",
        "hit_count": hits,
        "entry_health": health,
    }


def test_ranking_cannot_starve_a_kind_that_earns_no_hits_by_design() -> None:
    # 24 aliases, every one of them hotter than every default_rule, and a limit of
    # 20. A `default_rule` earns NO hit_count at all -- the deterministic seam that
    # writes hit events only ever applies aliases and normalizers -- so ranking on
    # hits alone evicts both seasonal defaults, and a seasonal default that stops
    # rendering does not announce itself.
    # Hit counts spread across the saturation ceiling so the alias ordering is
    # genuinely discriminating -- otherwise every alias ties at max usage and a
    # "take the first 18" implementation would pass this test.
    rows = [_entry(f"alias_{i:02d}", "alias", hits=i) for i in range(24)]
    rows += [
        _entry("season=winter", "default_rule", hits=0),
        _entry("season=all_season", "default_rule", hits=0),
    ]

    selected = select_ranked_entries(rows, limit=20)

    assert len(selected) == 20
    kinds = {row["entry_kind"] for row in selected}
    assert kinds == {"alias", "default_rule"}
    ids = {row["id"] for row in selected}
    assert {"season=winter", "season=all_season"} <= ids
    # ...and the aliases that DID make it are the healthiest ones, not an
    # arbitrary slice: the hottest alias is in, the two coldest are out.
    assert "alias_23" in ids
    assert "alias_00" not in ids and "alias_01" not in ids
    # The guard is a per-kind SHARE, not a hard-coded exemption for default_rule:
    # 18 of the 20 seats still go to the kind that has the volume.
    assert sum(1 for row in selected if row["entry_kind"] == "alias") == 18


def test_ranking_within_a_kind_is_by_health_then_deterministic() -> None:
    rows = [
        _entry("cold", "alias", hits=0),
        _entry("hot", "alias", hits=HEALTH_USAGE_SATURATION),
        _entry("warm", "alias", hits=HEALTH_USAGE_SATURATION // 2),
    ]
    assert [r["id"] for r in select_ranked_entries(rows, limit=3)] == [
        "hot",
        "warm",
        "cold",
    ]


def test_a_precomputed_health_score_beats_raw_hits_in_the_ranking() -> None:
    # The score is what ranks, not the hit column: a heavily-used entry the judge
    # says is misapplied must lose to a quieter one that is honored.
    misapplied = _entry(
        "loud",
        "alias",
        hits=50,
        health=lexicon_entry_health(
            hits=50,
            injections=0,
            leg_results=_legs(honored=(0, 20, 0), no_misapplication=(0, 20, 0)),
        ),
    )
    honored = _entry(
        "quiet",
        "alias",
        hits=2,
        health=lexicon_entry_health(
            hits=2, injections=0, leg_results=_legs(honored=(20, 20, 0))
        ),
    )
    assert [r["id"] for r in select_ranked_entries([misapplied, honored], limit=2)] == [
        "quiet",
        "loud",
    ]


def test_selection_below_the_limit_returns_everything() -> None:
    rows = [_entry("a", "alias"), _entry("b", "default_rule")]
    assert len(select_ranked_entries(rows, limit=20)) == 2


# ---------------------------------------------------------------------------
# the score x ledger join (live Postgres, isolated schema)
# ---------------------------------------------------------------------------


def _ledger(conn, rows: list[tuple[str, str, str]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO injection_ledger (turn_ref, layer, entry_ref) VALUES (%s, %s, %s)",
            rows,
        )
    conn.commit()


def test_the_join_attributes_a_verdict_only_to_the_entries_that_turn_carried(
    datastore,
) -> None:
    _driver, conn, _schema = datastore
    # THREE turns, THREE entries, and a deliberate non-match on BOTH sides: a
    # turn with a verdict but no ledger row, and a ledger entry whose turn was
    # never judged. A cross join would credit every entry with every verdict.
    _ledger(
        conn,
        [
            ("turn_a", LAYER_L7, "lex_1"),
            ("turn_a", LAYER_L7, "lex_2"),
            ("turn_b", LAYER_L7, "lex_1"),
            ("turn_c", LAYER_L7, "lex_3"),  # never judged
            ("turn_b", LAYER_L6, "exp_1"),  # a different layer, same turn
        ],
    )
    with conn.cursor() as cur:
        record_judged_turns(
            cur,
            [
                ("turn_a", "honored", True),
                ("turn_b", "honored", False),
                ("turn_z", "honored", True),  # judged, but carried no injection
            ],
        )
    conn.commit()
    refresh_entry_effectiveness(conn)
    conn.commit()

    with conn.cursor() as cur:
        l7 = entry_effectiveness_for(cur, layer=LAYER_L7)
        l6 = entry_effectiveness_for(cur, layer=LAYER_L6)

    # lex_1 was in BOTH judged turns; lex_2 only in the honored one.
    assert l7["lex_1"]["leg_results"]["honored"] == {
        "passed": 1,
        "determinate": 2,
        "undetermined": 0,
    }
    assert l7["lex_2"]["leg_results"]["honored"] == {
        "passed": 1,
        "determinate": 1,
        "undetermined": 0,
    }
    # lex_3's turn was never judged: injections counted, no verdict attributed.
    assert l7["lex_3"]["leg_results"] == {}
    assert l7["lex_3"]["injections"] == 1
    # turn_z is judged but joins to nothing -- it never invents an entry.
    assert set(l7) == {"lex_1", "lex_2", "lex_3"}
    # The layer is part of the key, so L6's entry gets turn_b's verdict and only
    # the L7 read's rows come back from the L7 read.
    assert l6["exp_1"]["leg_results"]["honored"]["determinate"] == 1


def test_an_undetermined_verdict_is_counted_but_never_enters_a_denominator(
    datastore,
) -> None:
    _driver, conn, _schema = datastore
    _ledger(conn, [("turn_a", LAYER_L7, "lex_1"), ("turn_b", LAYER_L7, "lex_1")])
    with conn.cursor() as cur:
        record_judged_turns(
            cur, [("turn_a", "honored", True), ("turn_b", "honored", None)]
        )
    conn.commit()
    refresh_entry_effectiveness(conn)
    conn.commit()

    with conn.cursor() as cur:
        rows = entry_effectiveness_for(cur, layer=LAYER_L7)
    counts = rows["lex_1"]["leg_results"]["honored"]
    assert counts == {"passed": 1, "determinate": 1, "undetermined": 1}
    assert lexicon_entry_health(hits=0, injections=2, leg_results=rows["lex_1"]["leg_results"])[
        "honored"
    ]["rate"] == 1.0


def test_the_refresh_is_a_full_recompute_so_re_judging_never_double_counts(
    datastore,
) -> None:
    _driver, conn, _schema = datastore
    _ledger(conn, [("turn_a", LAYER_L7, "lex_1")])
    with conn.cursor() as cur:
        record_judged_turns(cur, [("turn_a", "honored", True)])
    conn.commit()
    refresh_entry_effectiveness(conn)
    conn.commit()

    # The judge job's window overlaps run to run, so the SAME turn is re-sampled
    # and re-judged routinely. Accumulating would inflate that turn's evidence
    # once per run; the recompute makes one turn worth exactly one verdict.
    with conn.cursor() as cur:
        record_judged_turns(cur, [("turn_a", "honored", True)])
    conn.commit()
    refresh_entry_effectiveness(conn)
    conn.commit()

    with conn.cursor() as cur:
        rows = entry_effectiveness_for(cur, layer=LAYER_L7)
    assert rows["lex_1"]["leg_results"]["honored"]["determinate"] == 1
    assert rows["lex_1"]["injections"] == 1


def test_the_refresh_drops_entries_whose_ledger_rows_have_aged_out(datastore) -> None:
    _driver, conn, _schema = datastore
    _ledger(conn, [("turn_a", LAYER_L7, "lex_gone")])
    refresh_entry_effectiveness(conn)
    conn.commit()
    with conn.cursor() as cur:
        assert "lex_gone" in entry_effectiveness_for(cur, layer=LAYER_L7)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM injection_ledger WHERE entry_ref = 'lex_gone'")
    conn.commit()
    refresh_entry_effectiveness(conn)
    conn.commit()
    with conn.cursor() as cur:
        assert entry_effectiveness_for(cur, layer=LAYER_L7) == {}


def test_the_ledger_prune_tick_recomputes_the_aggregate(datastore) -> None:
    # The refresh has no schedule of its own: it rides the job that already owns
    # the ledger's lifecycle, AFTER the prune, so the numbers describe the rows
    # that survive rather than a window already garbage-collected.
    from hermes_runtime.injection_ledger import run_injection_ledger_prune_job

    _driver, conn, _schema = datastore
    _ledger(conn, [("turn_keep", LAYER_L7, "lex_1"), ("turn_old", LAYER_L7, "lex_old")])
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE injection_ledger SET injected_at = now() - interval '400 days' "
            "WHERE turn_ref = 'turn_old'"
        )
    conn.commit()

    run_injection_ledger_prune_job({"schedule_window": 1}, conn=conn)

    with conn.cursor() as cur:
        rows = entry_effectiveness_for(cur, layer=LAYER_L7)
    assert set(rows) == {"lex_1"}


# ---------------------------------------------------------------------------
# FR-6's upgrade clause: the selection knob, end to end against Postgres
# ---------------------------------------------------------------------------

_WINTER = "seed_lex_season_winter"
_ALL_SEASON = "seed_lex_season_all_season"


def _crowd_out_the_seeded_defaults(conn, count: int = 24) -> None:
    """Confirm `count` aliases decided AFTER the seeded rows.

    Migration 0024 seeds four confirmed rows, two of them the seasonal
    `default_rule`s. Anything decided later pushes them out of a newest-first
    window of LEXICON_GLOSSARY_LIMIT -- which is the silent failure this slice
    exists to close.
    """
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO semantic_lexicon (id, domain, entry_kind, surface_form, "
            "canonical_form, status, provenance, decided_at, hit_count) "
            "VALUES (%s, 'company', 'alias', %s, %s, 'confirmed', 'admin_manual', "
            "now() + make_interval(secs => %s), %s)",
            [
                (f"lex_crowd_{i:02d}", f"SURFACE{i:02d}", f"CANON{i:02d}", i, 50 + i)
                for i in range(count)
            ],
        )
    conn.commit()


def test_the_default_strategy_is_still_newest_first_and_evicts_the_default_rule(
    datastore, monkeypatch
) -> None:
    # The BEFORE half of the fix, asserted rather than assumed: with the knob
    # unset the shipped behaviour is unchanged, and past 20 confirmed entries a
    # seasonal default silently stops rendering. If this ever goes green with the
    # defaults present, the default flipped without anyone saying so.
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
    from hermes_runtime.tool_backend import (
        LEXICON_GLOSSARY_LIMIT,
        LEXICON_SELECTION_ENV,
        LEXICON_SELECTION_NEWEST,
        lexicon_selection_strategy,
    )

    _driver, conn, _schema = datastore
    monkeypatch.delenv(LEXICON_SELECTION_ENV, raising=False)
    assert lexicon_selection_strategy() == LEXICON_SELECTION_NEWEST
    _crowd_out_the_seeded_defaults(conn)

    entries = PostgresGatewayStore(connection=conn).load_confirmed_lexicon()

    assert len(entries) == LEXICON_GLOSSARY_LIMIT
    ids = {entry["id"] for entry in entries}
    assert not ({_WINTER, _ALL_SEASON} & ids)


def test_the_health_strategy_keeps_the_default_rule_the_newest_window_evicts(
    datastore, monkeypatch
) -> None:
    # The headline. 24 aliases, every one of them decided later AND hotter than
    # the seasonal defaults, which earn no hit_count at all because the
    # deterministic seam never applies a default_rule. Newest-20 evicts them;
    # health-ranked keeps them, without pinning the kind by name -- the aliases
    # still take the overwhelming majority of the seats.
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
    from hermes_runtime.tool_backend import (
        LEXICON_GLOSSARY_LIMIT,
        LEXICON_SELECTION_ENV,
        LEXICON_SELECTION_HEALTH,
    )

    _driver, conn, _schema = datastore
    monkeypatch.setenv(LEXICON_SELECTION_ENV, LEXICON_SELECTION_HEALTH)
    _crowd_out_the_seeded_defaults(conn)

    entries = PostgresGatewayStore(connection=conn).load_confirmed_lexicon()

    assert len(entries) == LEXICON_GLOSSARY_LIMIT
    ids = {entry["id"] for entry in entries}
    assert {_WINTER, _ALL_SEASON} <= ids
    # ...and the glossary is still mostly vocabulary, not a wall of seasonal rules.
    assert sum(1 for e in entries if e["entry_kind"] == "alias") >= 15
    # The rows still carry every key the renderer and the ledger read (the S06
    # key contract), which a Python-side re-selection is exactly where to break.
    for entry in entries:
        assert {"id", "domain", "entry_kind", "surface_form", "canonical_form", "status"} <= set(entry)


def test_an_unknown_strategy_falls_back_to_the_shipped_behaviour(monkeypatch) -> None:
    # Fail-SAFE, not fail-closed: a typo'd knob must never be able to empty the
    # prompt, so anything but the exact literal is `newest`.
    from hermes_runtime.tool_backend import (
        LEXICON_SELECTION_ENV,
        LEXICON_SELECTION_HEALTH,
        LEXICON_SELECTION_NEWEST,
        lexicon_selection_strategy,
    )

    for raw in ("", "  ", "ranked", "hit", "1", "true"):
        monkeypatch.setenv(LEXICON_SELECTION_ENV, raw)
        assert lexicon_selection_strategy() == LEXICON_SELECTION_NEWEST, raw
    monkeypatch.setenv(LEXICON_SELECTION_ENV, " HEALTH ")
    assert lexicon_selection_strategy() == LEXICON_SELECTION_HEALTH


def test_the_console_row_carries_the_score_its_components_and_its_scope(
    datastore,
) -> None:
    # Where it RENDERS, not only in a docstring: the console's own governed read
    # is what the admin sees, so the caveat has to be in this payload.
    from hermes_runtime.datastore.handlers.semantic_lexicon import _list_lexicon_entries
    from toee_hermes.tool_gate import ToolExecutionContext

    _driver, conn, _schema = datastore
    _ledger(conn, [("turn_a", LAYER_L7, _WINTER), ("turn_b", LAYER_L7, _WINTER)])
    with conn.cursor() as cur:
        record_judged_turns(cur, [("turn_a", "honored", True), ("turn_b", "honored", False)])
    conn.commit()
    refresh_entry_effectiveness(conn)
    conn.commit()

    payload = _list_lexicon_entries(
        conn, {"domain": "tire"}, ToolExecutionContext(profile="supervisor_admin")
    )
    winter = next(e for e in payload["entries"] if e["id"] == _WINTER)
    health = winter["entry_health"]

    assert health["scope"] == EXTERNAL_PATH_SCOPE
    assert health["basis"]
    assert health["honored"] == {
        "rate": 0.5,
        "passed": 1,
        "determinate": 2,
        "undetermined": 0,
    }
    # hit_count is the MATERIALIZED column (D6) -- structurally zero for a
    # default_rule -- and the ledger count is the other half of usage.
    assert health["usage"]["hits"] == 0 and health["usage"]["injections"] == 2
    assert health["score"] is not None
    # Every entry carries the block, so no row renders a bare number.
    assert all(e["entry_health"]["scope"] for e in payload["entries"])


# ---------------------------------------------------------------------------
# FR-31: injection-stratified sampling (live Postgres)
# ---------------------------------------------------------------------------


def _seed_external_turn(
    conn, *, n: int, age_seconds: int, injected: bool, slots: dict
) -> str:
    """Seed one external turn end to end and return its ledger key (event_id).

    Reproduces the real id rules: the outbound reply id is
    ``sms_session_id || ':' || event_id || ':out'`` (postgres_gateway_store's
    ``record_hermes_reply``), which is the only thing that lets a sampled reply be
    joined back to the ledger's ``turn_ref``.
    """
    thread = f"customer_thread:sms:+1555{n:07d}"
    identity = f"+1555{n:07d}"
    session = f"sms_session:{thread}:conv{n}"
    event = f"evt_{n}"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity) "
            "VALUES (%s, 'sms', %s)",
            (thread, identity),
        )
        cur.execute(
            "INSERT INTO sms_session (id, customer_thread_id, expires_at) "
            "VALUES (%s, %s, now() + interval '1 day')",
            (session, thread),
        )
        cur.execute(
            "INSERT INTO message_turn (id, sms_session_id, customer_thread_id, "
            "direction, author, body, created_at) VALUES (%s, %s, %s, 'outbound', "
            "'hermes', %s, now() - make_interval(secs => %s))",
            (f"{session}:{event}:out", session, thread, f"reply {n}", age_seconds),
        )
        cur.execute(
            "INSERT INTO agent_turn_context (id, event_id, customer_thread_id, "
            "sms_session_id) VALUES (%s, %s, %s, %s)",
            (f"agent_ctx_{n}", event, thread, session),
        )
        for slot_name, slot_value in slots.items():
            cur.execute(
                "INSERT INTO customer_memory_slot (id, binding_key, binding_kind, "
                "slot_name, slot_value, source) VALUES (%s, %s, 'provisional', %s, %s, "
                "'customer_explicit')",
                (f"slot:{n}:{slot_name}", f"provisional:sms:{identity}", slot_name, slot_value),
            )
        if injected:
            cur.execute(
                "INSERT INTO injection_ledger (turn_ref, layer, entry_ref) "
                "VALUES (%s, %s, %s)",
                (event, LAYER_L7, _WINTER),
            )
    conn.commit()
    return event


def test_the_sampler_prefers_injection_turns_and_keeps_a_non_injection_floor(
    datastore,
) -> None:
    from hermes_runtime.honored_rate import SAMPLE_NON_INJECTION_FLOOR, sample_transcripts

    _driver, conn, _schema = datastore
    # The NON-injection turns are the NEWEST, so a plain newest-first sampler
    # would take all five of them and no injection turn at all. That is the whole
    # discriminating power of this fixture.
    injected = {
        _seed_external_turn(
            conn, n=i, age_seconds=1000 - i, injected=True, slots={"channel_preference": "sms"}
        )
        for i in range(5)
    }
    for i in range(5, 10):
        _seed_external_turn(
            conn, n=i, age_seconds=10 - i, injected=False, slots={"channel_preference": "sms"}
        )

    transcripts, candidate_total = sample_transcripts(conn.cursor(), cap=5)

    assert candidate_total == 10
    assert len(transcripts) == 5
    from_ledger = [t for t in transcripts if t.turn_ref in injected]
    # Injection-first, but not injection-only: the documented floor is kept.
    assert len(from_ledger) == 4
    assert len(transcripts) - len(from_ledger) == 1
    assert SAMPLE_NON_INJECTION_FLOOR == 0.2


def test_a_ledger_turn_with_no_memory_slots_is_eligible_and_keeps_its_ref(
    datastore,
) -> None:
    # The widening, and the LEFT JOIN that makes it real. An L6/L7-only injection
    # lands on a thread with no L4 slots; the old predicate could not see it, and
    # an inner join to customer_memory_slot would have dropped it again after the
    # predicate admitted it -- a sample that looks stratified and never contains
    # the new stratum.
    from hermes_runtime.honored_rate import sample_transcripts

    _driver, conn, _schema = datastore
    event = _seed_external_turn(conn, n=42, age_seconds=5, injected=True, slots={})

    transcripts, candidate_total = sample_transcripts(conn.cursor(), cap=5)

    assert candidate_total == 1
    assert [t.turn_ref for t in transcripts] == [event]
    assert transcripts[0].injected_memory == {}
    assert transcripts[0].reply == "reply 42"


def test_the_job_writes_verdicts_that_join_back_to_the_entries(datastore) -> None:
    # End to end: sample -> judge -> per-turn verdicts -> ledger join -> a score
    # on the entry that was actually in that turn's prompt.
    from hermes_runtime.honored_rate import run_honored_rate_job

    class _Judge:
        def complete(self, prompt: str, *, model: str) -> str:
            return '{"verdict": "yes", "reason": "scripted"}'

    _driver, conn, _schema = datastore
    _seed_external_turn(
        conn, n=77, age_seconds=5, injected=True, slots={"channel_preference": "sms"}
    )

    run_honored_rate_job({"schedule_window": 1}, client=_Judge(), conn=conn)
    refresh_entry_effectiveness(conn)
    conn.commit()

    with conn.cursor() as cur:
        rows = entry_effectiveness_for(cur, layer=LAYER_L7)
    assert rows[_WINTER]["leg_results"]["honored"] == {
        "passed": 1,
        "determinate": 1,
        "undetermined": 0,
    }
