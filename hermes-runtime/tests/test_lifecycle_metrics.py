"""0.0.5 S22 (FR-34a): the lifecycle metric block + the read-only knob panel.

Layer ① of the three-layer gate. What only live Postgres can prove is the
SCOPING of each count, so the fixture below is deliberately uneven: **every
lifecycle number is different, and every one of them has at least one row it
must exclude.** A fixture with one row per metric cannot tell a correct query
from one that returns everything -- the same trap the Memory Hub's fixture was
built to avoid.

The knob-panel half is DB-free on purpose: a knob is a module constant, and the
thing worth pinning is that the panel READS it (D16) rather than carrying a
second copy of its current value that can drift.
"""

from __future__ import annotations

import ast
import inspect

from hermes_runtime import knobs as knobs_mod
from hermes_runtime.datastore.handlers._common import (
    METRIC_MEMORY_POLLUTION_REJECTED,
    METRIC_SELF_SERVICE_USAGE,
    insert_audit,
    insert_metric_event,
)
from hermes_runtime.datastore.handlers.metrics import _get_aggregate_metrics
from hermes_runtime.injection_ledger import LAYER_L4, LAYER_L6, LAYER_L7
from hermes_runtime.knobs import knob_panel
from hermes_runtime.latency import (
    LATENCY_L4_LOAD,
    LATENCY_L6_LOAD,
    LATENCY_L7_LOAD,
    skip_metric,
)
from toee_hermes.drivers.mock.memory import (
    MEMORY_ACTION_ERASED,
    MEMORY_ACTION_PREFERENCE_UPDATED,
    MEMORY_PREFERENCE_SLOTS,
)
from toee_hermes.drivers.mock.metrics import create_metrics_mock_handlers
from toee_hermes.lifecycle_metrics import (
    LIFECYCLE_CONFLICT,
    LIFECYCLE_DROP_KEY_PREFIX,
    LIFECYCLE_ERASURES,
    LIFECYCLE_POLLUTION,
    LIFECYCLE_SELF_SERVICE,
    lifecycle_payload,
)
from toee_hermes.tool_gate import ToolExecutionContext

_CTX = ToolExecutionContext(profile="internal_copilot")


def _counts(payload) -> dict[str, object]:
    return {row["key"]: row["value"] for row in payload["lifecycle"]}


def _audit(conn, action: str, binding_key: str) -> None:
    insert_audit(
        conn,
        profile="internal_copilot",
        account_id="acct_supervisor_1",
        action=action,
        target_type="customer_memory_slot",
        target_id="contact_time",
        details={"binding_key": binding_key, "slot": "contact_time"},
    )


def _timing_row(conn, metric: str, duration_ms: float) -> None:
    """A latency SAMPLE, not a counter -- the row a drop count must not count."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO metric_event (id, metric, flag, duration_ms) "
            "VALUES (%s, %s, NULL, %s)",
            (f"metric_{metric}_{duration_ms}", metric, duration_ms),
        )


def _seed(conn) -> None:
    # conflict: 2 preference_updated rows. The two neighbours below are governed
    # audit rows on the SAME target_type, so a query that forgot its action
    # filter returns 4.
    _audit(conn, MEMORY_ACTION_PREFERENCE_UPDATED, "gid://shopify/Customer/1001")
    _audit(conn, MEMORY_ACTION_PREFERENCE_UPDATED, "gid://shopify/Customer/2002")
    _audit(conn, "preference_cleared", "gid://shopify/Customer/1001")
    _audit(conn, "proposal_dismissed", "gid://shopify/Customer/1001")
    # ... and exactly ONE erase, so conflict (2) and erases (1) cannot be
    # satisfied by the same number.
    _audit(conn, MEMORY_ACTION_ERASED, "gid://shopify/Customer/3003")

    # pollution: 3 rejections; the 4 self-service rows and the timing rows below
    # live in the same table, so a missing metric filter returns 7+.
    for _ in range(3):
        insert_metric_event(conn, metric=METRIC_MEMORY_POLLUTION_REJECTED)
    for _ in range(4):
        insert_metric_event(conn, metric=METRIC_SELF_SERVICE_USAGE)

    # drops: 1 L4, 0 L6, 2 L7 -- three different answers, one of them zero, so a
    # query that returns "every skip row" (3) matches none of them. The two
    # timing rows carry the READ metric name, which a `LIKE 'latency_%'` would
    # sweep in.
    insert_metric_event(conn, metric=skip_metric(LATENCY_L4_LOAD))
    insert_metric_event(conn, metric=skip_metric(LATENCY_L7_LOAD))
    insert_metric_event(conn, metric=skip_metric(LATENCY_L7_LOAD))
    _timing_row(conn, LATENCY_L4_LOAD, 11.5)
    _timing_row(conn, LATENCY_L6_LOAD, 12.5)
    conn.commit()


def test_every_lifecycle_count_is_scoped_to_the_rows_its_label_claims(datastore) -> None:
    _driver, conn, _schema = datastore
    _seed(conn)

    counts = _counts(_get_aggregate_metrics(conn, {}, _CTX))

    assert counts[LIFECYCLE_CONFLICT] == 2
    assert counts[LIFECYCLE_POLLUTION] == 3
    assert counts[LIFECYCLE_SELF_SERVICE] == 4
    assert counts[LIFECYCLE_ERASURES] == 1
    assert counts[f"{LIFECYCLE_DROP_KEY_PREFIX}{LAYER_L4.upper()}"] == 1
    assert counts[f"{LIFECYCLE_DROP_KEY_PREFIX}{LAYER_L6.upper()}"] == 0
    assert counts[f"{LIFECYCLE_DROP_KEY_PREFIX}{LAYER_L7.upper()}"] == 2


def test_the_lifecycle_block_is_empty_of_counts_on_a_fresh_database(datastore) -> None:
    # Zero is the right answer for a database that has recorded nothing -- and
    # every key is still present, so the panel renders "0", never a missing tile.
    _driver, conn, _schema = datastore
    counts = _counts(_get_aggregate_metrics(conn, {}, _CTX))
    assert set(counts) == {row["key"] for row in lifecycle_payload()["lifecycle"]}
    assert all(value == 0 for value in counts.values()), counts


# --- the house rule: a count never travels without its scope -------------------


def test_no_lifecycle_count_can_reach_a_renderer_without_its_label_and_scope() -> None:
    for row in lifecycle_payload()["lifecycle"]:
        assert row["label"].strip(), row
        # `detail` is where the caveat lives -- what is counted, over what
        # window, and what is deliberately NOT in the number.
        assert len(row["detail"].strip()) > 40, row


def test_the_two_components_with_no_source_are_named_rather_than_silently_zero() -> None:
    # S13's queue conflict annotations and a "poisoned retirement" reason are
    # both part of FR-34a's wording and neither is shipped. Rendering the count
    # without saying so would report a partial number as a total one.
    detail = {row["key"]: row["detail"] for row in lifecycle_payload()["lifecycle"]}
    assert "annotation" in detail[LIFECYCLE_CONFLICT].lower()
    assert "poison" in detail[LIFECYCLE_POLLUTION].lower()


def test_the_mock_twin_reports_the_same_lifecycle_block_at_zero() -> None:
    # NFR-7 through the SHARED builder, not a restatement: the mock calls the
    # same function, so the two cannot render different tiles.
    handler = create_metrics_mock_handlers()["toee_metrics"]["get_aggregate_metrics"]
    assert handler({}, _CTX)["lifecycle"] == lifecycle_payload()["lifecycle"]


# --- D14/D16: the knob panel is READ-ONLY and reads its constants --------------


def test_every_knob_renders_the_live_module_constant_not_a_copied_number() -> None:
    values = {knob["key"]: knob["value"] for knob in knob_panel()["knobs"]}
    from hermes_runtime.feedback_aggregator import SAME_TAG_FAIL_THRESHOLD
    from hermes_runtime.injection_ledger import (
        PRUNE_WINDOW_SECONDS,
        ZERO_HIT_WINDOW_SECONDS,
    )
    from hermes_runtime.latency import PRE_TURN_READ_SLO_P95_MS
    from hermes_runtime.tool_backend import LEXICON_GLOSSARY_LIMIT

    assert values["LEXICON_GLOSSARY_LIMIT"] == str(LEXICON_GLOSSARY_LIMIT)
    assert values["PRUNE_WINDOW_SECONDS"] == str(PRUNE_WINDOW_SECONDS)
    assert values["ZERO_HIT_WINDOW_SECONDS"] == str(ZERO_HIT_WINDOW_SECONDS)
    assert values["SAME_TAG_FAIL_THRESHOLD"] == str(SAME_TAG_FAIL_THRESHOLD)
    assert values["PRE_TURN_READ_SLO_P95_MS"] == str(PRE_TURN_READ_SLO_P95_MS)


def test_no_knob_row_carries_a_literal_value_instead_of_its_constant() -> None:
    """D16, checked structurally rather than by grep.

    A copied literal that AGREES with its constant is invisible to the test
    above -- ``str(20) == str(LEXICON_GLOSSARY_LIMIT)`` whichever one the row
    holds -- and goes wrong silently on the day someone tunes the real one. The
    first version of this test was a grep for ``"= 20"``, and a bait proved it
    could not see ``_knob(..., 20, ...)``: the literal in argument position is
    exactly the shape a copy actually takes.

    So the value argument of every ``_knob`` call must be a NAME (an imported
    constant) or a CALL (a resolver like ``lexicon_selection_strategy()``) --
    never a literal of any type. The grep is kept as the second half, because
    ``ast`` alone would not see a module-level ``_LIMIT = 20`` re-declaration
    passed in by name.
    """
    source = inspect.getsource(knobs_mod)
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_knob"
    ]
    assert len(calls) >= 10, "the panel lost most of its knobs"
    for call in calls:
        value_arg = call.args[2]
        assert not isinstance(value_arg, ast.Constant), (
            f"{call.args[0].value} carries a literal, not its constant: "
            f"{ast.dump(value_arg)}"
        )
    for name in ("LEXICON_GLOSSARY_LIMIT", "PRUNE_WINDOW_SECONDS", "ZERO_HIT_WINDOW_SECONDS"):
        assert name in source
    for literal in ("= 20", "15552000", "7776000", "= 150.0"):
        assert literal not in source, literal


def test_every_knob_says_where_it_is_changed_and_that_it_is_not_changed_here() -> None:
    # D14: the panel ships honestly READ-ONLY. NFR-3's knob clause is satisfied
    # by deploy-time config only, so each row must name the module (and env var,
    # where one exists) an admin edits, and the block must say so once.
    panel = knob_panel()
    assert "read-only" in panel["label"].lower()
    for knob in panel["knobs"]:
        assert knob["source"], knob
        assert knob["note"].strip(), knob


def test_the_mock_twin_reports_no_knob_values_rather_than_copied_ones() -> None:
    # The knob constants are hermes_runtime's, and toee_hermes must not import
    # back (the same reason the mock retention twin reports a null ledger-prune
    # window). Absent is the honest answer; a copied number would be the wrong
    # one on the day someone tunes the real constant.
    handler = create_metrics_mock_handlers()["toee_metrics"]["get_aggregate_metrics"]
    assert handler({}, _CTX)["knobs"] is None


def test_the_postgres_twin_ships_the_knob_panel(datastore) -> None:
    _driver, conn, _schema = datastore
    panel = _get_aggregate_metrics(conn, {}, _CTX)["knobs"]
    assert panel is not None
    assert panel["knobs"]


# --- the memory-health strip's one non-existing read: last-injection recency ---


def _ledger(conn, turn_ref: str, layer: str, entry_ref: str, injected_at: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO injection_ledger (turn_ref, layer, entry_ref, injected_at) "
            "VALUES (%s, %s, %s, %s)",
            (turn_ref, layer, entry_ref, injected_at),
        )


def test_last_injection_recency_is_scoped_to_this_binding_and_to_l4(datastore) -> None:
    """The strip's "when did this customer's memory last reach a prompt".

    Four rows the answer must EXCLUDE, each newer than the right one: another
    customer's L4 row, an L6 row, an L4 row on a binding whose key merely STARTS
    with this one, and an L4 ref naming something that is not one of the four
    slots. The last two are what the obvious `LIKE` queries would sweep in, and
    the tail of this test runs those queries to show they really do.
    """
    _driver, conn, _schema = datastore
    mine = "gid://shopify/Customer/1001"
    theirs = "gid://shopify/Customer/2002"
    contact, _channel, habit, _style = MEMORY_PREFERENCE_SLOTS

    _ledger(conn, "turn_a", LAYER_L4, f"{mine}:{contact}", "2026-07-01T10:00:00Z")
    _ledger(conn, "turn_b", LAYER_L4, f"{mine}:{habit}", "2026-07-02T10:00:00Z")
    _ledger(conn, "turn_c", LAYER_L4, f"{theirs}:{contact}", "2026-07-20T10:00:00Z")
    _ledger(conn, "turn_d", LAYER_L6, "aexp_1", "2026-07-21T10:00:00Z")
    _ledger(conn, "turn_e", LAYER_L4, f"{mine}9:{contact}", "2026-07-22T10:00:00Z")
    _ledger(conn, "turn_f", LAYER_L4, f"{mine}:not_a_slot", "2026-07-23T10:00:00Z")
    conn.commit()

    from hermes_runtime.datastore.handlers.memory import last_injection_at

    with conn.cursor() as cur:
        assert last_injection_at(cur, mine).startswith("2026-07-02T10:00:00")
        # ... and a binding that never reached a prompt reads "never", not "now".
        assert last_injection_at(cur, "gid://shopify/Customer/9009") is None

        # The exact-ref match is load-bearing, PROVEN rather than asserted: the
        # two prefix queries a reader reaches for first both answer with a row
        # this customer's memory-health strip must not claim.
        for naive in (f"{mine}:%", f"{mine}%"):
            cur.execute(
                "SELECT max(injected_at) FROM injection_ledger WHERE entry_ref LIKE %s",
                (naive,),
            )
            assert not cur.fetchone()[0].isoformat().startswith("2026-07-02"), naive
