"""S13 (FR-14, ADR-0150): the copilot draft turn's memory write is propose-only.

**This reverses 0.0.2's S20** (PAC-4 gap #2), which gave the copilot draft turn's
UNBOUND boot path the SAME ``extra_drivers`` overlay S04 gave the bound external
turn, so an agent-initiated ``toee_customer_memory.upsert_preference`` reached
Postgres instead of the ephemeral MockDriver. The governance-faithful design
(0.0.3 Candidate 2, "propose -> confirm") makes the LLM never write customer
memory directly: the draft turn calls the SAME tool, but ``_turn_extra_drivers
(include_memory_write=False)`` (``tool_backend.py``) leaves ``toee_customer_memory``
OUT of the merged overlay, so the call always lands on the shared mock driver and
is discarded, regardless of ``TOOL_BACKEND``. S14 builds the structured
``proposals[]`` envelope; S15 the Accept/Dismiss UI routing an accepted proposal
through the EXISTING governed dispatch write (``employee_confirmed``).

Rewritten deliberately, not deleted (RK-3): the old S20 "reaches the datastore"
tests below are now their propose-only mirror image -- same fixtures, same seams,
opposite assertion. ``resolve_memory_write_source`` still maps an unbound draft
turn to ``copilot_agent`` (historical-vocabulary only now -- see
``test_customer_memory_write_source.py``, unchanged); this file is about whether
that code path is ever reachable in production, and after S13 it is not.

This mirrors ``test_composite_driver_overlay.py`` (the overlay/injection shape) and
``test_copilot_memory_injection.py`` (the copilot seam + real-Postgres fixture
conventions). The hermetic tests stub ``boot_profile`` so nothing registers into the
shared upstream ``tools.registry``; the integration test drives a REAL scripted
``AIAgent`` turn through the real governed dispatch path, substituting only the
datastore driver's CONNECTION (via ``select_tool_driver``) so a regression (a
reintroduced write overlay) would land in the test's throwaway schema instead of a
fresh connection to the default schema -- the readback would flip RED, not just
silently miss the write.
"""

from __future__ import annotations

from types import SimpleNamespace

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

_VERIFIED_SHOPIFY_ID = "gid://shopify/Customer/50501"


class _NullStore:
    """A store with no case/memory -- keeps the hermetic tests DB-independent.

    The hermetic tests below only care about what ``make_copilot_run_turn`` hands
    ``boot_profile``; the case/memory READ side (S08, already covered by
    ``test_copilot_memory_injection.py``) is irrelevant here, so this avoids a real
    Postgres round trip for tests that stub ``boot_profile`` anyway.
    """

    def load_case_identity(self, case_id):
        return None

    def load_customer_memory(self, binding_key):
        return []


def _capture_copilot_boot_kwargs(monkeypatch, *, store=None) -> dict:
    """Run one copilot draft turn with boot + agent-loop stubbed; return boot_profile kwargs.

    Stubbing keeps this hermetic -- no profile registers into the shared upstream
    ``tools.registry`` -- so it observes exactly what ``make_copilot_run_turn`` hands
    ``boot_profile`` (mirrors ``_capture_extra_drivers`` in
    ``test_composite_driver_overlay.py``, one seam further in).
    """
    import hermes_runtime.copilot_turn as copilot_mod

    captured: dict[str, object] = {}

    def fake_boot(profile: str, **kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(profile=profile, tool_names=[], manager=None)

    monkeypatch.setattr(copilot_mod, "boot_profile", fake_boot)
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "ok"}],
        store=store if store is not None else _NullStore(),
    )
    run_turn(channel="sms", case_id="case-x")
    return captured


def test_copilot_run_turn_never_injects_the_datastore_driver_for_memory_write(monkeypatch) -> None:
    # S13/FR-14 (ADR-0150) central proof at the boot-kwargs seam: even with
    # TOOL_BACKEND=datastore (memory fully enabled), the copilot draft turn's
    # extra_drivers never carries a toee_customer_memory entry -- the write side
    # of S20 is gone; the tool stays on the shared mock driver.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")

    captured = _capture_copilot_boot_kwargs(monkeypatch)

    extra = captured.get("extra_drivers")
    assert extra is None or "toee_customer_memory" not in extra


def test_copilot_run_turn_keeps_the_knowledge_overlay_without_memory_write(monkeypatch) -> None:
    # S10 (FR-5) regression, updated for S13: the Knowledge overlay still merges
    # in on its own independent gate even though the memory-write overlay is
    # permanently excluded on this turn.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setenv("KNOWLEDGE_BACKEND", "retriever")

    captured = _capture_copilot_boot_kwargs(monkeypatch)

    extra = captured.get("extra_drivers")
    assert extra is not None
    assert set(extra.keys()) == {"toee_knowledge_search"}
    assert extra["toee_knowledge_search"].kind == "knowledge"


def test_copilot_run_turn_passes_no_overlay_when_backend_is_unset(monkeypatch) -> None:
    # S05/FR-7 parity: unset backend -> memory_enabled() False -> no overlay -> the
    # tool stays on mock, and the datastore driver is never even constructed (a mock
    # deployment must never hard-depend on Postgres).
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    # select_tool_driver now lives behind tool_backend._customer_memory_extra_drivers
    # (Standards fix #1 -- hoisted out of copilot_turn.py so openrouter.py and
    # copilot_turn.py share one definition instead of two copies); patch it there.
    import hermes_runtime.tool_backend as tool_backend_mod

    def _boom(*_a, **_k):
        raise AssertionError("select_tool_driver must not be called when memory is disabled")

    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", _boom)

    captured = _capture_copilot_boot_kwargs(monkeypatch)

    assert captured.get("extra_drivers") is None


def test_copilot_run_turn_passes_no_overlay_when_backend_is_explicitly_mock(monkeypatch) -> None:
    # Same contract, spelled out for TOOL_BACKEND=mock (not just unset).
    monkeypatch.setenv("TOOL_BACKEND", "mock")
    # select_tool_driver now lives behind tool_backend._customer_memory_extra_drivers
    # (Standards fix #1 -- hoisted out of copilot_turn.py so openrouter.py and
    # copilot_turn.py share one definition instead of two copies); patch it there.
    import hermes_runtime.tool_backend as tool_backend_mod

    def _boom(*_a, **_k):
        raise AssertionError("select_tool_driver must not be called when memory is disabled")

    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", _boom)

    captured = _capture_copilot_boot_kwargs(monkeypatch)

    assert captured.get("extra_drivers") is None


def _seed_case(
    conn,
    *,
    case_id,
    thread_id,
    channel_identity,
    shopify_customer_id,
    channel="sms",
):
    """Seed a customer_thread + an open case bound to it (the case->thread lookup input)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity, shopify_customer_id)"
            " VALUES (%s, %s, %s, %s)",
            (thread_id, channel, channel_identity, shopify_customer_id),
        )
        cur.execute(
            "INSERT INTO cases (id, channel, customer_thread_id) VALUES (%s, %s, %s)",
            (case_id, channel, thread_id),
        )
    conn.commit()


def test_copilot_draft_turn_scripted_write_does_not_persist_to_datastore(
    datastore, monkeypatch
) -> None:
    # The S13 central proof (FR-14, ADR-0150), RED-capable by construction like
    # test_e2e_memory_acceptance.py's dormancy tripwire: a copilot draft turn's
    # SCRIPTED agent calls toee_customer_memory.upsert_preference for a
    # VERIFIED-customer case with TOOL_BACKEND=datastore (memory fully enabled) --
    # the same scenario 0.0.2's S20 proved DID persist. It must NOT any more: a
    # draft-turn write is a proposal, never a persist.
    #
    # select_tool_driver is still patched to the fixture's schema-bound real
    # datastore driver -- NOT because this turn is expected to reach it (S13
    # excludes toee_customer_memory from the overlay before select_tool_driver is
    # ever called for this turn), but so that IF a regression reintroduced the
    # write overlay, the write would land in THIS throwaway schema and the
    # readback below would flip RED, instead of silently missing the write
    # entirely by writing to a fresh connection's default schema.
    driver, conn, _ = datastore
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    import hermes_runtime.tool_backend as tool_backend_mod

    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", lambda *_a, **_k: driver)

    _seed_case(
        conn,
        case_id="case-mem-write",
        thread_id="thr-mem-write",
        channel_identity="+14165550188",
        shopify_customer_id=_VERIFIED_SHOPIFY_ID,
    )

    run_turn = make_copilot_run_turn(
        scripted_completions=[
            {
                "tool_calls": [
                    {
                        "name": "toee_customer_memory__upsert_preference",
                        "arguments": {
                            "key": "contact_time_preference",
                            "value": "mornings",
                        },
                    }
                ]
            },
            {"content": "Got it, I've noted mornings work best for you."},
        ],
        store=PostgresGatewayStore(connection=conn),
    )

    result = run_turn(channel="sms", case_id="case-mem-write")

    assert result["draft"]  # the turn still completes past the tool call
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM customer_memory_slot"
            " WHERE binding_key = %s AND slot_name = %s",
            (_VERIFIED_SHOPIFY_ID, "contact_time_preference"),
        )
        count = cur.fetchone()[0]
    assert count == 0  # propose-only: nothing lands in Postgres, ever
