"""Launch Eval fixture loading + merge (ADR-0071, ADR-0073, ADR-0119, ADR-0075).

Ports packages/eval-runner/src/fixtures.ts. Reads eval/mocks/base.yaml and the
scenario YAML, validates shape, and merges baseline -> identity_preset ->
mock_overrides into a MergedScenario. Python mock data are frozen dataclasses, so
the merge builds new instances rather than cloning + mutating in place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional, Union

import yaml

from toee_hermes.drivers.mock import (
    MemoryMockData,
    ShopifyMockData,
    easyroutes_baseline_data,
    identity_baseline_data,
    knowledge_baseline_data,
    memory_baseline_data,
    qbo_baseline_data,
    shopify_baseline_data,
    square_baseline_data,
)
from toee_hermes.drivers.mock.shopify import ShopifyLineItem, ShopifyOrder, ShopifyProduct

from .types import (
    SUITE_VALUES,
    BaseMocks,
    MergedMockContext,
    MergedScenario,
    ScenarioAssertions,
    ScenarioFixture,
    ScenarioTurn,
)

# Deterministic Session Identity Snapshot timestamp. Ingress resolves identity
# before the turn (ADR-0043); eval pins it so reports never depend on wall time.
RESOLVED_AT = "2026-01-01T00:00:00.000Z"

PathLike = Union[str, Path]


def _last_segment(label: str) -> str:
    return re.split(r"[\\/]", label)[-1]


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


# ---------------------------------------------------------------------------
# base.yaml
# ---------------------------------------------------------------------------


def load_base_mocks(eval_dir: PathLike) -> BaseMocks:
    path = Path(eval_dir) / "mocks" / "base.yaml"
    if not path.exists():
        raise ValueError(f"Eval base mocks not found at {path}.")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"Failed to parse {path}: {error}") from error
    if not _is_object(raw) or not _is_object(raw.get("identities")):
        raise ValueError(f'Eval base mocks at {path} must define "identities".')
    return BaseMocks(identities=raw["identities"])


# ---------------------------------------------------------------------------
# Scenario fixture parsing + validation
# ---------------------------------------------------------------------------


def _fail(label: str, message: str) -> None:
    raise ValueError(f"Scenario {label}: {message}")


def _require_string(raw: dict[str, Any], field: str, label: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or len(value) == 0:
        _fail(label, f'missing required "{field}".')
    return value


def _validate_turns(raw: Any, label: str) -> list[ScenarioTurn]:
    if not isinstance(raw, list) or len(raw) == 0:
        _fail(label, '"turns" must be a non-empty list.')
    turns: list[ScenarioTurn] = []
    for index, turn in enumerate(raw):
        if not _is_object(turn) or "inbound" not in turn:
            _fail(label, f'turn {index} must define "inbound".')
        inbound = turn["inbound"]
        if isinstance(inbound, str):
            turns.append(ScenarioTurn(inbound=inbound))
        elif _is_object(inbound) and isinstance(inbound.get("body"), str):
            obj: dict[str, str] = {"body": inbound["body"]}
            if isinstance(inbound.get("subject"), str):
                obj["subject"] = inbound["subject"]
            turns.append(ScenarioTurn(inbound=obj))
        else:
            _fail(label, f'turn {index} "inbound" must be a string or {{ body }}.')
    return turns


def _validate_assertions(raw: Any, label: str) -> ScenarioAssertions:
    if not _is_object(raw):
        _fail(label, '"assertions" must be an object.')
    severity = raw.get("max_severity")
    if severity not in ("high", "medium"):
        _fail(label, '"assertions.max_severity" must be "high" or "medium".')
    return ScenarioAssertions(
        max_severity=severity,
        behavioral=raw.get("behavioral"),
        tool=raw.get("tool"),
        disclosure=raw.get("disclosure"),
        text=raw.get("text"),
        memory_assertions=raw.get("memory_assertions"),
    )


def parse_scenario_content(content: str, label: str) -> ScenarioFixture:
    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise ValueError(f"Failed to parse {label}: {error}") from error
    if not _is_object(raw):
        _fail(label, "file is not a YAML mapping.")

    scenario_id = _require_string(raw, "scenario_id", label)

    # scenario_id must match the numeric filename prefix (ADR-0119).
    prefix = re.match(r"^(\d+)", _last_segment(label))
    if prefix:
        file_prefix = int(prefix.group(1))
        try:
            id_number: Optional[int] = int(scenario_id)
        except ValueError:
            id_number = None
        if id_number is None or file_prefix != id_number:
            _fail(
                label,
                f'scenario_id "{scenario_id}" does not match filename numeric '
                f'prefix "{prefix.group(1)}".',
            )

    suite = _require_string(raw, "suite", label)
    if suite not in SUITE_VALUES:
        _fail(label, f'unknown suite "{suite}".')

    memory_preset = raw.get("memory_preset")
    if memory_preset is not None and not _is_object(memory_preset):
        _fail(label, '"memory_preset" must be an object when present.')

    mock_overrides = raw.get("mock_overrides") or {}
    if not _is_object(mock_overrides):
        _fail(label, '"mock_overrides" must be an object.')

    return ScenarioFixture(
        scenario_id=scenario_id,
        title=_require_string(raw, "title", label),
        suite=suite,
        channel=_require_string(raw, "channel", label),
        identity_preset=_require_string(raw, "identity_preset", label),
        turns=_validate_turns(raw.get("turns"), label),
        mock_overrides=mock_overrides,
        assertions=_validate_assertions(raw.get("assertions"), label),
        memory_preset=memory_preset,
    )


def parse_scenario_file(path: PathLike) -> ScenarioFixture:
    return parse_scenario_content(Path(path).read_text(encoding="utf-8"), str(path))


# ---------------------------------------------------------------------------
# Merge: baseline -> identity_preset -> mock_overrides (ADR-0119, ADR-0073)
# ---------------------------------------------------------------------------


def _build_session_identity(preset: dict[str, Any]) -> dict[str, Any]:
    shopify_customer_id = preset.get("shopify_customer_id")
    if isinstance(shopify_customer_id, str):
        return {
            "outcome": "verified_customer",
            "shopify_customer_id": shopify_customer_id,
            "resolved_at": RESOLVED_AT,
        }
    ids = preset.get("shopify_customer_ids")
    if isinstance(ids, list) and len(ids) > 0:
        return {
            "outcome": "ambiguous_phone_match",
            "shopify_customer_ids": list(ids),
            "resolved_at": RESOLVED_AT,
        }
    return {"outcome": "unmatched_caller", "resolved_at": RESOLVED_AT}


def _normalize_email_link(value: Any) -> str:
    # base/override use linked|failed|unlinked; the mock enum is linked|unlinked,
    # so any non-linked state (e.g. scenario 04 "failed") collapses to unlinked.
    return "linked" if value == "linked" else "unlinked"


def _apply_email_link_overrides(
    qbo_email_links: dict[str, str],
    identity_email_links: dict[str, str],
    base: BaseMocks,
    overrides: dict[str, Any],
) -> None:
    for preset_key, raw_status in overrides.items():
        preset = base.identities.get(preset_key)
        customer_id = preset.get("shopify_customer_id") if preset else None
        if customer_id is None:
            continue
        status = _normalize_email_link(raw_status)
        qbo_email_links[customer_id] = status
        identity_email_links[customer_id] = status
        email = preset.get("email") if preset else None
        if email is not None:
            identity_email_links[email] = status


def _to_shopify_order(
    raw: dict[str, Any], fallback_customer_id: Optional[str]
) -> ShopifyOrder:
    raw_items = raw.get("line_items")
    line_items = tuple(
        ShopifyLineItem(
            sku=str(item.get("sku", "")), title=str(item.get("title", ""))
        )
        for item in (raw_items if isinstance(raw_items, list) else [])
        if _is_object(item)
    )
    return ShopifyOrder(
        order_number=str(raw.get("order_number", "")),
        customer_id=str(raw.get("customer_id") or fallback_customer_id or ""),
        line_items=line_items,
    )


def _apply_shopify_order_overrides(
    orders: list[ShopifyOrder],
    raw_orders: dict[str, Any],
    active_customer_id: Optional[str],
) -> None:
    incoming: list[ShopifyOrder] = []
    for value in raw_orders.values():
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if _is_object(entry):
                incoming.append(_to_shopify_order(entry, active_customer_id))
    # Upsert by order_number so an override replaces the baseline order it shadows.
    for order in incoming:
        index = next(
            (i for i, e in enumerate(orders) if e.order_number == order.order_number),
            -1,
        )
        if index >= 0:
            orders[index] = order
        else:
            orders.append(order)


def _str_field(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def _int_field(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _apply_shopify_product_overrides(
    products: list[ShopifyProduct], raw_products: dict[str, Any]
) -> None:
    for key, value in raw_products.items():
        if not _is_object(value):
            continue
        sku = _str_field(value.get("sku"))
        index = next(
            (i for i, p in enumerate(products) if sku is not None and p.sku == sku),
            -1,
        )
        title = _str_field(value.get("title"))
        product_url = _str_field(value.get("product_url"))
        media_url = _str_field(value.get("media_url"))
        price = str(value["price"]) if value.get("price") is not None else None
        inventory = _int_field(value.get("inventory"))
        if index >= 0:
            existing = products[index]
            products[index] = replace(
                existing,
                sku=sku if sku is not None else existing.sku,
                title=title if title is not None else existing.title,
                product_url=product_url
                if product_url is not None
                else existing.product_url,
                media_url=media_url if media_url is not None else existing.media_url,
                price=price if price is not None else existing.price,
                inventory=inventory if inventory is not None else existing.inventory,
            )
        else:
            products.append(
                ShopifyProduct(
                    product_id=f"gid://shopify/Product/mock-{key}",
                    sku=sku if sku is not None else key,
                    title=title if title is not None else (sku if sku is not None else key),
                    product_url=product_url if product_url is not None else "",
                    media_url=media_url if media_url is not None else "",
                    price=price,
                    inventory=inventory,
                )
            )


def _apply_operational_policy_overrides(
    operational_policy: dict[str, str], raw_policy: dict[str, Any]
) -> None:
    for slot, value in raw_policy.items():
        if value == "empty" or value == "" or value is None:
            # Explicitly empty slot -> governed no-policy fallback (ADR-0067).
            operational_policy.pop(slot, None)
        else:
            operational_policy[slot] = str(value)


def _apply_mock_overrides(
    overrides: dict[str, Any],
    base: BaseMocks,
    active_customer_id: Optional[str],
    orders: list[ShopifyOrder],
    products: list[ShopifyProduct],
    qbo_email_links: dict[str, str],
    identity_email_links: dict[str, str],
    operational_policy: dict[str, str],
    domain_errors: dict[str, str],
) -> None:
    for domain, raw in overrides.items():
        if not _is_object(raw):
            continue
        # A domain marked with an `error` is forced into a governed failure for
        # this scenario (e.g. scenario 13 shopify.error: unavailable).
        if isinstance(raw.get("error"), str):
            domain_errors[domain] = raw["error"]
        if domain == "qbo" and _is_object(raw.get("email_links")):
            _apply_email_link_overrides(
                qbo_email_links, identity_email_links, base, raw["email_links"]
            )
        if domain == "shopify" and _is_object(raw.get("orders")):
            _apply_shopify_order_overrides(orders, raw["orders"], active_customer_id)
        if domain == "shopify" and _is_object(raw.get("products")):
            _apply_shopify_product_overrides(products, raw["products"])
        if domain == "knowledge" and _is_object(raw.get("operational_policy")):
            _apply_operational_policy_overrides(
                operational_policy, raw["operational_policy"]
            )


def resolve_scenario(
    fixture: ScenarioFixture, base: BaseMocks, source_file: str
) -> MergedScenario:
    preset = base.identities.get(fixture.identity_preset)
    if preset is None:
        _fail(source_file, f'unknown identity_preset "{fixture.identity_preset}".')

    session_identity = _build_session_identity(preset)
    active_customer_id = (
        session_identity.get("shopify_customer_id")
        if session_identity["outcome"] == "verified_customer"
        else None
    )

    orders = list(shopify_baseline_data.orders)
    products = list(shopify_baseline_data.products)
    qbo_email_links = dict(qbo_baseline_data.email_links)
    identity_email_links = dict(identity_baseline_data.email_links)
    operational_policy = dict(knowledge_baseline_data.operational_policy)
    domain_errors: dict[str, str] = {}
    memory_preferences = (
        dict(fixture.memory_preset)
        if fixture.memory_preset is not None
        else dict(memory_baseline_data.preferences)
    )

    _apply_mock_overrides(
        fixture.mock_overrides,
        base,
        active_customer_id,
        orders,
        products,
        qbo_email_links,
        identity_email_links,
        operational_policy,
        domain_errors,
    )

    mock_context = MergedMockContext(
        identity=replace(identity_baseline_data, email_links=identity_email_links),
        shopify=ShopifyMockData(orders=tuple(orders), products=tuple(products)),
        qbo=replace(qbo_baseline_data, email_links=qbo_email_links),
        easyroutes=easyroutes_baseline_data,
        square=square_baseline_data,
        knowledge=replace(knowledge_baseline_data, operational_policy=operational_policy),
        memory=MemoryMockData(preferences=memory_preferences),
        domain_errors=domain_errors,
    )

    return MergedScenario(
        scenario_id=fixture.scenario_id,
        title=fixture.title,
        suite=fixture.suite,
        channel=fixture.channel,
        identity_preset=fixture.identity_preset,
        session_identity=session_identity,
        turns=fixture.turns,
        assertions=fixture.assertions,
        mock_context=mock_context,
        source_file=source_file,
        memory_preset=fixture.memory_preset,
    )


# ---------------------------------------------------------------------------
# Suite discovery
# ---------------------------------------------------------------------------


def _scenario_files_for(eval_dir: PathLike, suite: str) -> list[Path]:
    scenarios_dir = Path(eval_dir) / "scenarios"
    if suite == "email_go_live":
        email_dir = scenarios_dir / "email"
        if not email_dir.exists():
            return []
        return [p for p in email_dir.iterdir() if p.suffix == ".yaml"]
    # text_first_launch / policy_publish source from the top-level scenarios dir.
    return [p for p in scenarios_dir.iterdir() if p.suffix == ".yaml"]


def load_suite(suite: str, eval_dir: PathLike) -> list[MergedScenario]:
    base = load_base_mocks(eval_dir)
    merged: list[MergedScenario] = []
    for file in _scenario_files_for(eval_dir, suite):
        fixture = parse_scenario_file(file)
        if fixture.suite != suite:
            continue
        merged.append(resolve_scenario(fixture, base, str(file)))
    merged.sort(key=lambda scenario: scenario.scenario_id)
    return merged


def load_scenario(suite: str, scenario_id: str, eval_dir: PathLike) -> MergedScenario:
    target = int(scenario_id)
    for scenario in load_suite(suite, eval_dir):
        if int(scenario.scenario_id) == target:
            return scenario
    raise ValueError(f'Scenario "{scenario_id}" not found in suite "{suite}".')


# ---------------------------------------------------------------------------
# policy_publish suite (ADR-0075, ADR-0121)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicySlotMap:
    regression_subset: list[int]
    slots: dict[str, dict[str, Any]]


def load_policy_slot_map(eval_dir: PathLike) -> PolicySlotMap:
    path = Path(eval_dir) / "policy_slot_map.yaml"
    if not path.exists():
        raise ValueError(f"Policy slot map not found at {path}.")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"Failed to parse {path}: {error}") from error
    if not _is_object(raw) or not _is_object(raw.get("slots")):
        raise ValueError(f'Policy slot map at {path} must define "slots".')
    regression = raw.get("regression_subset")
    return PolicySlotMap(
        regression_subset=regression if isinstance(regression, list) else [],
        slots=raw["slots"],
    )


def load_policy_publish_suite(eval_dir: PathLike, slot: str) -> list[MergedScenario]:
    policy_map = load_policy_slot_map(eval_dir)
    slot_def = policy_map.slots.get(slot)
    if slot_def is None:
        raise ValueError(
            f'Unknown policy slot "{slot}" in '
            f'{Path(eval_dir) / "policy_slot_map.yaml"}.'
        )
    ids = set(slot_def.get("scenario_ids") or []) | set(policy_map.regression_subset)
    return [
        scenario
        for scenario in load_suite("text_first_launch", eval_dir)
        if int(scenario.scenario_id) in ids
    ]
