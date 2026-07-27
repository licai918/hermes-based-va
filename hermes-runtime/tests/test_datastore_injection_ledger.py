"""0.0.5 S09 (FR-11): the injection provenance ledger against live Postgres.

Live half of ``tests/test_injection_ledger.py``. What is proven HERE and nowhere
else, because it is a schema/SQL claim rather than a Python one:

1. **The grain.** A real external turn with BOTH an L4 slot and an L6 confirmed
   entry in its prompt writes one row per (turn, layer, entry), and the
   ``turn x layer x entry`` JOIN resolves every row back to the live entry in
   its OWN layer -- the C6 6.6 clause S10 (blast radius) and S26 (per-entry
   effectiveness) are both built on.
2. **The merge survives.** ``merge_provisional_memory`` DELETEs and re-INSERTs
   L4 rows with FRESH ids. The join still resolves afterwards, because
   ``entry_ref`` is ``binding_key + slot_name`` and not a row id (D4.3).
3. **No values.** The table carries ids and slot NAMES only -- no slot value,
   no L6 content (NFR-6: the content stays in the layer that owns it).
4. **The prune.** The windowed DELETE ages rows out and records its run where
   the retention sweep records its own ("last run" alongside the existing
   sweep surfaces).

Skip-if-no-DB via the shared ``datastore``/``temp_schema_conn`` fixtures; these
genuinely execute in CI (the NFR-7 anti-skip gate).
"""

from __future__ import annotations

from types import SimpleNamespace

from hermes_runtime.injection_ledger import (
    LAYER_L4,
    LAYER_L6,
    PRUNE_AUDIT_ACTION,
    PRUNE_WINDOW_SECONDS,
    run_injection_ledger_prune_job,
)
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import OpenRouterConfig, make_openrouter_run_turn

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1", api_key="sk-or-test", model="m", fallback_model="f"
)
_PHONE = "+14165550199"
_BINDING_KEY = f"provisional:sms:{_PHONE}"
_SLOT = "contact_time"
_L6_ID = "aexp_confirmed_1"

# Resolves every ledger row back to the live entry in its own layer. THIS query is
# the grain: it is keyed on (turn_ref, layer, entry_ref) and nothing else.
_GRAIN_JOIN = """
    SELECT il.layer, il.entry_ref
    FROM injection_ledger il
    LEFT JOIN customer_memory_slot cms
      ON il.layer = 'l4' AND il.entry_ref = cms.binding_key || ':' || cms.slot_name
    LEFT JOIN agent_experience ae
      ON il.layer = 'l6' AND il.entry_ref = ae.id
    WHERE il.turn_ref = %s
      AND (cms.id IS NOT NULL OR ae.id IS NOT NULL)
    ORDER BY il.layer, il.entry_ref
"""


def _seed(conn, *, with_memory: bool = True) -> None:
    with conn.cursor() as cur:
        if with_memory:
            cur.execute(
                "INSERT INTO customer_memory_slot "
                "(id, binding_key, binding_kind, slot_name, slot_value, source) "
                "VALUES (%s, %s, 'provisional', %s, %s, 'customer_stated')",
                ("cms_seed", _BINDING_KEY, _SLOT, "evenings after 6pm"),
            )
        cur.execute(
            "INSERT INTO agent_experience (id, kind, status, content, source) "
            "VALUES (%s, 'procedure', 'confirmed', %s, 'copilot_agent')",
            (_L6_ID, "Check get_delivery_status before quoting a delivery date."),
        )
    conn.commit()


def _run_external_turn(monkeypatch, conn, *, event_id: str) -> None:
    """Drive ONE real external turn bound to the isolated schema's connection."""
    import hermes_runtime.openrouter as openrouter_mod

    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    # The S26 counter emit opens its OWN unpooled connection (metrics.py), which
    # would land outside this test's throwaway schema. Not what is under test.
    monkeypatch.setattr(openrouter_mod, "record_memory_injection_metric", lambda _flag: None)
    monkeypatch.setattr(
        openrouter_mod,
        "run_agent_turn",
        lambda **_kwargs: {"final_response": "REPLY", "messages": []},
    )
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        openai_factory=_scripted_openai_factory([{"content": "ok"}]),
        store=PostgresGatewayStore(connection=conn),
    )
    context = SimpleNamespace(
        event_id=event_id,
        conversation_id="conv-s09",
        sms_session_id=None,
        from_phone=_PHONE,
        session_identity_snapshot=None,
    )
    run_turn(context, "Any update on my order?")


# --- the grain ------------------------------------------------------------------


def test_a_turn_with_l4_and_l6_injections_writes_matching_rows(datastore, monkeypatch) -> None:
    _driver, conn, _schema = datastore
    _seed(conn)
    _run_external_turn(monkeypatch, conn, event_id="evt_grain")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT turn_ref, case_or_binding_ref, layer, entry_ref FROM injection_ledger "
            "ORDER BY layer",
        )
        rows = cur.fetchall()
    assert rows == [
        ("evt_grain", _BINDING_KEY, LAYER_L4, f"{_BINDING_KEY}:{_SLOT}"),
        ("evt_grain", _BINDING_KEY, LAYER_L6, _L6_ID),
    ]

    # The turn x layer x entry join: every row resolves to its live entry.
    with conn.cursor() as cur:
        cur.execute(_GRAIN_JOIN, ("evt_grain",))
        joined = cur.fetchall()
    assert joined == [(LAYER_L4, f"{_BINDING_KEY}:{_SLOT}"), (LAYER_L6, _L6_ID)]


def test_the_grain_separates_two_turns_over_the_same_entries(datastore, monkeypatch) -> None:
    _driver, conn, _schema = datastore
    _seed(conn)
    _run_external_turn(monkeypatch, conn, event_id="evt_a")
    _run_external_turn(monkeypatch, conn, event_id="evt_b")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT turn_ref, count(*) FROM injection_ledger GROUP BY turn_ref ORDER BY turn_ref"
        )
        assert cur.fetchall() == [("evt_a", 2), ("evt_b", 2)]
        # ...and the blast-radius direction: which turns did THIS entry touch?
        cur.execute(
            "SELECT turn_ref FROM injection_ledger WHERE layer = %s AND entry_ref = %s "
            "ORDER BY turn_ref",
            (LAYER_L6, _L6_ID),
        )
        assert [r[0] for r in cur.fetchall()] == ["evt_a", "evt_b"]


def test_a_no_injection_turn_writes_no_rows(datastore, monkeypatch) -> None:
    _driver, conn, _schema = datastore
    # No slots and no confirmed entries -> render_injection returns None.
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "off")
    _run_external_turn(monkeypatch, conn, event_id="evt_empty")

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM injection_ledger")
        assert cur.fetchone()[0] == 0


def test_rows_carry_no_memory_values(datastore, monkeypatch) -> None:
    # NFR-6: ids and slot NAMES only. The slot's value lives in L4 and the L6
    # entry's content lives in agent_experience; neither is copied here.
    _driver, conn, _schema = datastore
    _seed(conn)
    _run_external_turn(monkeypatch, conn, event_id="evt_novalues")

    with conn.cursor() as cur:
        cur.execute("SELECT entry_ref FROM injection_ledger")
        refs = " ".join(r[0] for r in cur.fetchall())
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'injection_ledger' AND table_schema = current_schema()"
        )
        columns = {r[0] for r in cur.fetchall()}
    assert "evenings after 6pm" not in refs
    assert "get_delivery_status" not in refs
    assert columns == {"turn_ref", "case_or_binding_ref", "layer", "entry_ref", "injected_at"}


# --- entry_ref survives the merge path's delete-and-reinsert (D4.3) -------------


def test_entry_ref_survives_the_merge_paths_delete_and_reinsert(datastore, monkeypatch) -> None:
    _driver, conn, _schema = datastore
    _seed(conn)
    _run_external_turn(monkeypatch, conn, event_id="evt_merge")

    # What merge_provisional_memory does to an L4 row: DELETE, then INSERT a NEW
    # id under the verified key. A row-id entry_ref would be orphaned here.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM customer_memory_slot WHERE binding_key = %s", (_BINDING_KEY,))
        cur.execute(
            "INSERT INTO customer_memory_slot "
            "(id, binding_key, binding_kind, slot_name, slot_value, source) "
            "VALUES (%s, %s, 'provisional', %s, %s, 'merged_provisional')",
            ("cms_reinserted_with_a_fresh_id", _BINDING_KEY, _SLOT, "evenings after 6pm"),
        )
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(_GRAIN_JOIN, ("evt_merge",))
        joined = cur.fetchall()
    assert (LAYER_L4, f"{_BINDING_KEY}:{_SLOT}") in joined


# --- retention: the windowed prune ----------------------------------------------


def _insert_row(conn, *, turn_ref: str, age_seconds: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO injection_ledger (turn_ref, case_or_binding_ref, layer, entry_ref, "
            "injected_at) VALUES (%s, %s, %s, %s, now() - make_interval(secs => %s))",
            (turn_ref, "k", LAYER_L6, "aexp_x", age_seconds),
        )
    conn.commit()


def test_the_prune_job_deletes_past_the_window_and_keeps_the_rest(datastore) -> None:
    _driver, conn, _schema = datastore
    _insert_row(conn, turn_ref="old", age_seconds=PRUNE_WINDOW_SECONDS + 3600)
    _insert_row(conn, turn_ref="fresh", age_seconds=3600)

    run_injection_ledger_prune_job({}, conn=conn)

    with conn.cursor() as cur:
        cur.execute("SELECT turn_ref FROM injection_ledger")
        assert [r[0] for r in cur.fetchall()] == ["fresh"]


def test_the_prune_job_records_its_run_where_the_sweeps_do(datastore) -> None:
    _driver, conn, _schema = datastore
    _insert_row(conn, turn_ref="old", age_seconds=PRUNE_WINDOW_SECONDS + 3600)

    run_injection_ledger_prune_job({}, conn=conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT details FROM workbench_audit_log WHERE action = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (PRUNE_AUDIT_ACTION,),
        )
        row = cur.fetchone()
    assert row is not None, "the prune must leave a last-run record on the sweep surface"
    assert row[0]["deleted"] == 1
    assert row[0]["window_seconds"] == PRUNE_WINDOW_SECONDS
    assert row[0]["run_at"]
