"""Registry merge semantics and the merged all-tools factory (ADR-0137)."""

from toee_hermes.drivers.mock import create_all_mock_handlers, merge_registries
from toee_hermes.tool_catalog import TOOL_CATALOG, tool_names


def test_merge_registries_later_fragment_wins_on_collision() -> None:
    first = {"t": {"x": lambda params, context: "first"}}
    second = {
        "t": {"x": lambda params, context: "second", "y": lambda params, context: "y"}
    }

    merged = merge_registries(first, second)

    assert merged["t"]["x"]({}, None) == "second"
    assert merged["t"]["y"]({}, None) == "y"


def test_merge_registries_does_not_mutate_input_fragments() -> None:
    first = {"t": {"x": lambda params, context: "x"}}
    second = {"t": {"y": lambda params, context: "y"}}

    merge_registries(first, second)

    assert set(first["t"]) == {"x"}
    assert set(second["t"]) == {"y"}


def test_create_all_mock_handlers_registers_every_catalog_tool() -> None:
    registry = create_all_mock_handlers()

    assert set(registry) == set(tool_names())


def test_create_all_mock_handlers_registers_every_catalog_action() -> None:
    registry = create_all_mock_handlers()

    for tool, actions in TOOL_CATALOG.items():
        assert set(registry[tool]) == set(actions), tool
