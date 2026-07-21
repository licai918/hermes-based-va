"""Slice 33 / #36: tool-driver backend selection for the dispatch surface.

The per-profile ``tools:dispatch`` app (ADR-0141) runs the same governed
``execute_tool`` the channel pipeline uses; ``select_tool_driver`` picks which
``ToolDriver`` backs it. Mock-first (ADR-0137): unset/``mock`` -> MockDriver;
``datastore`` -> the Postgres system-of-record driver (ADR-0140). The no-drift
test pins the datastore registry to the v1 catalog and the mock registry so the
two backends cannot diverge for the system-of-record tools.

These tests need no Postgres: ``PostgresDriver()`` resolves its DSN lazily and
only connects inside ``execute``.
"""

from __future__ import annotations

import pytest

from toee_hermes.drivers.mock import create_all_mock_handlers
from toee_hermes.tool_catalog import is_tool_action

from hermes_runtime.datastore.handlers import build_datastore_registry
from hermes_runtime.tool_backend import (
    _turn_extra_drivers,
    memory_enabled,
    record_memory_injection_metric,
    resolve_tool_backend,
    select_tool_driver,
    simulated_mode_enabled,
)


def test_resolve_defaults_to_mock_when_unset_or_empty() -> None:
    assert resolve_tool_backend(None) == "mock"
    assert resolve_tool_backend("") == "mock"


def test_resolve_accepts_known_backends() -> None:
    assert resolve_tool_backend("mock") == "mock"
    assert resolve_tool_backend("datastore") == "datastore"


def test_resolve_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError):
        resolve_tool_backend("redis")


def test_select_mock_driver_is_mock_kind() -> None:
    driver = select_tool_driver("mock")
    assert driver.kind == "mock"


def test_select_datastore_driver_is_datastore_kind() -> None:
    # Constructed without a connection; DSN resolves lazily so no DB is needed.
    driver = select_tool_driver("datastore")
    assert driver.kind == "datastore"


def test_memory_enabled_false_when_backend_unset_or_mock() -> None:
    # S05/FR-7: Customer Memory is active only on the datastore backend; the
    # single-source-of-truth signal the write overlay (S04) and read gates
    # (S07/S08) share.
    assert memory_enabled(None) is False
    assert memory_enabled("") is False
    assert memory_enabled("mock") is False


def test_memory_enabled_true_when_backend_is_datastore() -> None:
    assert memory_enabled("datastore") is True


def test_memory_enabled_reads_the_env_var_when_called_with_no_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    assert memory_enabled() is False

    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    assert memory_enabled() is True


# --- simulated_mode_enabled (0.0.3 S05, NFR-4 gate reuse) --------------------


def test_simulated_mode_disabled_when_unset_or_empty() -> None:
    assert simulated_mode_enabled(None) is False
    assert simulated_mode_enabled("") is False


# Every REPLY_SENDER value worth asking about, including ones neither module
# accepts. The test derives which are "real" from the resolver rather than
# assuming — a hardcoded list is what let the old assertion look like a
# relationship check while still only testing what its author already believed.
_REPLY_SENDER_CANDIDATES = ("", "simpletexting", "simulated", "SIMULATED", "bogus")


@pytest.mark.parametrize("value", _REPLY_SENDER_CANDIDATES)
def test_dev_only_gate_is_open_exactly_when_the_resolver_picks_the_simulated_sender(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin the two modules' readings of REPLY_SENDER to each other.

    ``resolve_reply_sender`` (gateway_composition) chooses the outbound sender;
    ``simulated_mode_enabled`` (here) opens the dev-only mutation surface. They
    parse the same env var in different modules, so the hazard is drift: a value
    that boots the REAL sender while the gate reads it as simulated would expose
    ``toee_identity_lookup.link_identity`` in production.

    Asserting a fixed list cannot see that. This asks the resolver which sender a
    value produces and requires the gate to agree, for every candidate — so adding
    a sender on one side without the other fails here.
    """
    from hermes_runtime import gateway_composition

    monkeypatch.setenv("SIMPLETEXTING_API_TOKEN", "tok-123")
    monkeypatch.setenv(gateway_composition.REPLY_SENDER_ENV, value)

    try:
        resolved = gateway_composition.resolve_reply_sender()
    except ValueError:
        # Rejected at boot: the gateway never runs, so the gate must be shut too.
        assert simulated_mode_enabled(value) is False
        return

    resolver_says_simulated = resolved is gateway_composition._simulated_reply_sender
    assert simulated_mode_enabled(value) is resolver_says_simulated, (
        f"REPLY_SENDER={value!r}: resolver picks the "
        f"{'simulated' if resolver_says_simulated else 'real'} sender but the "
        f"dev-only gate says simulated={simulated_mode_enabled(value)}"
    )


def test_simulated_mode_enabled_for_simulated_case_insensitive() -> None:
    assert simulated_mode_enabled("simulated") is True
    assert simulated_mode_enabled("SIMULATED") is True


def test_simulated_mode_disabled_for_an_unrecognized_value() -> None:
    # Fail-closed, not fail-open: an unrecognized REPLY_SENDER (which
    # resolve_reply_sender would reject at gateway boot anyway) never enables the
    # dev-only surface.
    assert simulated_mode_enabled("bogus") is False


def test_simulated_mode_reads_the_env_var_when_called_with_no_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REPLY_SENDER", raising=False)
    assert simulated_mode_enabled() is False

    monkeypatch.setenv("REPLY_SENDER", "simulated")
    assert simulated_mode_enabled() is True


def test_datastore_registry_has_no_catalog_drift() -> None:
    # Every datastore (tool, action) is a real v1 catalog action: handler keys
    # cannot drift from the governed catalog (ADR-0059/0070).
    registry = build_datastore_registry()
    for tool, actions in registry.items():
        for action in actions:
            assert is_tool_action(tool, action), f"{tool}.{action} not in catalog"


# --- _turn_extra_drivers (S10, FR-5): merges the memory + knowledge overlays ---


def test_turn_extra_drivers_none_when_both_gates_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    monkeypatch.delenv("KNOWLEDGE_BACKEND", raising=False)

    assert _turn_extra_drivers() is None


def test_turn_extra_drivers_memory_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.delenv("KNOWLEDGE_BACKEND", raising=False)

    overlay = _turn_extra_drivers()

    assert overlay is not None
    assert set(overlay.keys()) == {"toee_customer_memory"}
    assert overlay["toee_customer_memory"].kind == "datastore"


def test_turn_extra_drivers_knowledge_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    monkeypatch.setenv("KNOWLEDGE_BACKEND", "retriever")

    overlay = _turn_extra_drivers()

    assert overlay is not None
    assert set(overlay.keys()) == {"toee_knowledge_search"}
    assert overlay["toee_knowledge_search"].kind == "knowledge"


def test_turn_extra_drivers_both_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setenv("KNOWLEDGE_BACKEND", "retriever")

    overlay = _turn_extra_drivers()

    assert overlay is not None
    assert set(overlay.keys()) == {"toee_customer_memory", "toee_knowledge_search"}
    assert overlay["toee_customer_memory"].kind == "datastore"
    assert overlay["toee_knowledge_search"].kind == "knowledge"


# --- include_memory_write=False (S13, FR-14 -- the S20 reversal, ADR-0150) ------
# The copilot draft turn boots with this flag so toee_customer_memory is excluded
# from the merged overlay regardless of memory_enabled() -- the write side of the
# S20 reversal. The external turn's default call (no arguments, tested above)
# is unaffected.


def test_turn_extra_drivers_excludes_memory_write_even_when_backend_is_datastore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.delenv("KNOWLEDGE_BACKEND", raising=False)

    overlay = _turn_extra_drivers(include_memory_write=False)

    # No overlay at all: memory write excluded, knowledge off too.
    assert overlay is None


def test_turn_extra_drivers_keeps_knowledge_when_memory_write_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setenv("KNOWLEDGE_BACKEND", "retriever")

    overlay = _turn_extra_drivers(include_memory_write=False)

    assert overlay is not None
    # Knowledge overlay merges in as usual; toee_customer_memory is absent, so
    # the tool stays on the shared mock driver (a write there is discarded).
    assert set(overlay.keys()) == {"toee_knowledge_search"}
    assert overlay["toee_knowledge_search"].kind == "knowledge"


def test_datastore_registry_is_subset_of_mock() -> None:
    # The datastore backs the system-of-record tools only; every action it
    # implements must also exist in the mock registry so swapping the backend
    # never references a tool/action the mock path lacks (no mock/datastore drift).
    datastore = build_datastore_registry()
    mock = create_all_mock_handlers()
    for tool, actions in datastore.items():
        assert tool in mock, f"datastore tool {tool} missing from mock registry"
        for action in actions:
            assert action in mock[tool], f"datastore {tool}.{action} missing from mock"


# --- record_memory_injection_metric (0.0.3 S26, FR-28 gap #1) -----------------
# Gated on the SAME axis as the feature itself (memory_enabled) so a mock/unset
# deployment never attempts a metrics DB connection on every turn (NFR-5).


def test_record_memory_injection_metric_skips_when_backend_is_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "hermes_runtime.tool_backend.emit_metric_event",
        lambda metric, flag: calls.append((metric, flag)),
    )

    record_memory_injection_metric(True)

    assert calls == []


def test_record_memory_injection_metric_emits_when_backend_is_datastore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "hermes_runtime.tool_backend.emit_metric_event",
        lambda metric, flag: calls.append((metric, flag)),
    )

    record_memory_injection_metric(False)

    assert calls == [("memory_injection", False)]
