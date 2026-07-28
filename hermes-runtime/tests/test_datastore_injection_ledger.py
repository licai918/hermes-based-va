"""0.0.5 S09 (FR-11): the injection provenance ledger against live Postgres.

Live half of ``tests/test_injection_ledger.py``. What is proven HERE and nowhere
else, because it is a schema/SQL claim rather than a Python one:

1. **The grain.** A real external turn with BOTH an L4 slot and an L6 confirmed
   entry in its prompt writes one row per (turn, layer, entry), and the
   ``turn x layer x entry`` JOIN resolves every row back to the live entry in
   its OWN layer -- the C6 6.6 clause S10 (blast radius) and S26 (per-entry
   effectiveness) are both built on.
2. **The merge re-points the ledger.** ``merge_provisional_memory`` inserts the
   slots under ``verified_key`` and deletes the provisional rows -- the binding
   KEY changes, so a natural key alone does not survive verification either. The
   merge updates the ledger's ``entry_ref`` in the same transaction, and the
   pre-verification turn stays joinable (D4.3 as amended).
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

import psycopg
import pytest

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.injection_ledger import (
    LAYER_L4,
    LAYER_L6,
    LAYERS,
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
# What binding_key_from_identity returns for a verified snapshot: the bare
# Shopify customer id, kind "verified". The merge moves slots from the former
# to the latter, which is why the ledger has to move with them.
_VERIFIED_KEY = "cust_verified_s09"
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


# --- the REAL merge re-points the ledger onto the verified key (D4.3) -----------


def _merge(conn) -> None:
    """The production merge, not an imitation of it."""
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    PostgresGatewayStore(connection=conn).merge_provisional_memory(_BINDING_KEY, _VERIFIED_KEY)


def test_the_merge_repoints_pre_verification_ledger_rows_onto_the_verified_key(
    datastore, monkeypatch
) -> None:
    """A turn that ran BEFORE verification is still joinable after it.

    The shipped test deleted and re-inserted under the SAME binding key, which
    is not what ``merge_provisional_memory`` does: it inserts under
    ``verified_key`` and deletes the provisional rows, so the binding key -- and
    therefore the L4 ``entry_ref`` built from it -- CHANGES. Without the merge
    re-pointing the ledger, retiring this customer's ``contact_time`` entry
    would leave S10's blast radius silently missing every pre-verification turn
    that used it.
    """
    _driver, conn, _schema = datastore
    _seed(conn)
    _run_external_turn(monkeypatch, conn, event_id="evt_pre_verification")

    _merge(conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT turn_ref, entry_ref FROM injection_ledger WHERE layer = %s", (LAYER_L4,)
        )
        assert cur.fetchall() == [("evt_pre_verification", f"{_VERIFIED_KEY}:{_SLOT}")]
        # ...and the grain join resolves it back to the LIVE (now verified) slot.
        cur.execute(_GRAIN_JOIN, ("evt_pre_verification",))
        joined = cur.fetchall()
    assert (LAYER_L4, f"{_VERIFIED_KEY}:{_SLOT}") in joined


def test_the_merge_leaves_other_layers_and_other_customers_alone(datastore, monkeypatch) -> None:
    # The re-point is scoped to the L4 refs for the slots this merge actually
    # moved: an L6 ref in the same turn, and another customer's identically-named
    # slot, must be untouched.
    _driver, conn, _schema = datastore
    _seed(conn)
    _run_external_turn(monkeypatch, conn, event_id="evt_pre_verification")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO injection_ledger (turn_ref, case_or_binding_ref, layer, entry_ref) "
            "VALUES (%s, %s, %s, %s)",
            ("evt_other_customer", "provisional:sms:+14165550188", LAYER_L4,
             f"provisional:sms:+14165550188:{_SLOT}"),
        )
    conn.commit()

    _merge(conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT turn_ref, layer, entry_ref FROM injection_ledger ORDER BY turn_ref, layer"
        )
        assert cur.fetchall() == [
            ("evt_other_customer", LAYER_L4, f"provisional:sms:+14165550188:{_SLOT}"),
            ("evt_pre_verification", LAYER_L4, f"{_VERIFIED_KEY}:{_SLOT}"),
            ("evt_pre_verification", LAYER_L6, _L6_ID),
        ]


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


def _status(driver) -> dict:
    result = execute_tool(
        tool="toee_retention",
        action="get_retention_status",
        params={},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )
    assert result.ok, result
    return result.data


def test_the_prune_last_run_surfaces_on_the_retention_status_read(datastore) -> None:
    # Writing the audit row is only half of "last-run visibility alongside the
    # existing sweep surfaces": get_retention_status keys on
    # action = 'retention_sweep' alone, so until it reads this action too the
    # prune's last run is a row nothing queries.
    driver, conn, _schema = datastore
    _insert_row(conn, turn_ref="old", age_seconds=PRUNE_WINDOW_SECONDS + 3600)
    run_injection_ledger_prune_job({}, conn=conn)

    prune = _status(driver)["ledger_prune"]
    assert prune["last_run_at"]
    assert prune["deleted"] == 1
    assert prune["window_seconds"] == PRUNE_WINDOW_SECONDS


def test_the_retention_status_reports_a_never_run_prune_honestly(datastore) -> None:
    driver, _conn, _schema = datastore
    assert _status(driver)["ledger_prune"] == {
        "last_run_at": None,
        "deleted": 0,
        "window_seconds": PRUNE_WINDOW_SECONDS,
    }


# --- the layer column has a domain (a typo is not a new layer) ------------------


def test_a_layer_outside_the_known_set_is_rejected_by_the_schema(datastore) -> None:
    # Without the CHECK, a typo'd layer produces a row that joins to nothing in
    # any layer -- permanently invisible to both readers, and nothing ever fails.
    _driver, conn, _schema = datastore
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO injection_ledger (turn_ref, layer, entry_ref) "
                "VALUES ('t_typo', 'L4', 'x')"
            )
    conn.rollback()


def test_every_layer_the_writer_can_emit_is_accepted(datastore) -> None:
    # ...and the constraint must not drift narrower than the writer's own set.
    _driver, conn, _schema = datastore
    with conn.cursor() as cur:
        for index, layer in enumerate(LAYERS):
            cur.execute(
                "INSERT INTO injection_ledger (turn_ref, layer, entry_ref) VALUES (%s, %s, 'x')",
                (f"t_{index}", layer),
            )
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM injection_ledger")
        assert cur.fetchone()[0] == len(LAYERS)
