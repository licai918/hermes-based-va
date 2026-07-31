"""Write-time advisories over live Postgres (0.0.5 S13, FR-18).

Both propose handlers, against the real tables migration 0025 adds the column
to. The mock twin and the pure resolver are covered in
``hermes/tests/test_write_advisories.py``; what only a database can show is here:

* the ``annotations`` column actually holds what the handler computed, and
  survives the queue read the inbox uses;
* the cross-layer comparison reaches the OTHER layer's table, which the mock
  structurally cannot do (its two fragments close over separate stores);
* an advisory that blows up leaves the proposal standing (NFR-3).

Skip-if-no-DB via the shared ``datastore`` fixture. The last test needs no
database at all -- it is the NFR-6 boundary assertion and must run everywhere.
"""

from __future__ import annotations

import pytest

from hermes_runtime import write_advisories as runtime_advisories
from hermes_runtime.datastore.handlers import agent_experience as l6_handlers
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import TOOLS_DISPATCH_ROUTE, ToolExecutionContext
from toee_hermes.write_advisories import (
    ADVISORY_DUPLICATE_L7_SURFACE,
    ADVISORY_REFILE_TO_L7,
    ADVISORY_SIMILAR_L6_NOTE,
    ANNOTATION_KEY_HEURISTIC,
)

NOTE = "Always confirm the vehicle year before quoting a winter set."
NOTE_DUPLICATE = "Always confirm the vehicle year before quoting winter sets"
# Same template, different subject -- the row the advisory must stay quiet about.
NOTE_NEAR_MISS = "Always confirm the delivery address before quoting a winter set."


def _ctx(user_id: str | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(profile="internal_copilot", user_id=user_id)


def _admin_ctx(user_id: str = "admin_1") -> ToolExecutionContext:
    return ToolExecutionContext(
        profile="internal_copilot", user_id=user_id, dispatch_route=TOOLS_DISPATCH_ROUTE
    )


def _call(driver, tool, action, context, **params):
    return execute_tool(
        tool=tool, action=action, params=params, context=context, driver=driver
    )


def _propose_note(driver, content, kind="note"):
    return _call(
        driver,
        "toee_agent_experience",
        "propose_experience",
        _ctx(),
        kind=kind,
        content=content,
    )


def _confirmed_note(driver, content) -> str:
    proposed = _propose_note(driver, content)
    assert proposed.ok, proposed.message
    _call(
        driver,
        "toee_agent_experience",
        "confirm_experience",
        _admin_ctx(),
        id=proposed.data["id"],
    )
    return proposed.data["id"]


def _confirmed_lexicon_entry(driver, *, domain, surface_form, canonical_form) -> str:
    added = _call(
        driver,
        "toee_semantic_lexicon",
        "add_lexicon_entry",
        _admin_ctx(),
        domain=domain,
        entry_kind="alias",
        surface_form=surface_form,
        canonical_form=canonical_form,
    )
    assert added.ok, added.message
    return added.data["id"]


def _stored_annotations(conn, table, entry_id) -> dict:
    with conn.cursor() as cur:
        cur.execute(f"SELECT annotations FROM {table} WHERE id = %s", (entry_id,))
        row = cur.fetchone()
    assert row is not None
    return row[0]


def _codes(annotations) -> list[str]:
    block = (annotations or {}).get(ANNOTATION_KEY_HEURISTIC)
    return [] if block is None else [a["code"] for a in block["advisories"]]


def _advisory(annotations, code) -> dict:
    return next(
        a for a in annotations[ANNOTATION_KEY_HEURISTIC]["advisories"] if a["code"] == code
    )


# --- L6 propose ---------------------------------------------------------------


def test_a_lexicon_shaped_note_is_annotated_and_still_persists(datastore) -> None:
    driver, conn, _ = datastore
    # The cross-layer half the mock cannot reach: an L7 row in the OTHER table.
    lex_id = _confirmed_lexicon_entry(
        driver, domain="tire", surface_form="2055516", canonical_form="205/55R16"
    )
    # And a confirmed L7 row the comparison must EXCLUDE, so "matches the
    # surface" and "reports whatever is confirmed" are distinguishable.
    _confirmed_lexicon_entry(
        driver, domain="tire", surface_form="2156016", canonical_form="215/60R16"
    )

    result = _propose_note(driver, "2055516 means 205/55R16")
    assert result.ok
    # NFR-3: annotated or not, the proposal is stored unchanged.
    assert result.data["status"] == "proposed"
    assert result.data["content"] == "2055516 means 205/55R16"

    stored = _stored_annotations(conn, "agent_experience", result.data["id"])
    assert _codes(stored) == [ADVISORY_REFILE_TO_L7, ADVISORY_DUPLICATE_L7_SURFACE]
    assert _advisory(stored, ADVISORY_REFILE_TO_L7)["canonical_form"] == "205/55R16"
    assert _advisory(stored, ADVISORY_DUPLICATE_L7_SURFACE)["entry_ref"] == lex_id
    # The response carries the same blob the column does -- the interim surface,
    # before S16's render lands.
    assert result.data["annotations"] == stored


def test_a_plain_procedure_note_is_annotated_with_nothing(datastore) -> None:
    driver, conn, _ = datastore
    # A near-miss sitting confirmed in L6 and a confirmed L7 row: the fixture is
    # populated on BOTH legs, so "no advisories" is a decision, not an empty
    # candidate set.
    _confirmed_note(driver, NOTE_NEAR_MISS)
    _confirmed_lexicon_entry(
        driver, domain="tire", surface_form="2055516", canonical_form="205/55R16"
    )

    result = _propose_note(driver, NOTE, kind="procedure")
    assert result.ok
    assert _stored_annotations(conn, "agent_experience", result.data["id"]) == {}


def test_a_reworded_duplicate_of_a_confirmed_note_is_annotated(datastore) -> None:
    driver, conn, _ = datastore
    original = _confirmed_note(driver, NOTE)
    # A confirmed row the comparison must EXCLUDE, so "finds the duplicate" and
    # "reports the first confirmed note it sees" are distinguishable.
    _confirmed_note(
        driver, "When a customer asks about warranty, link the manufacturer page first."
    )

    result = _propose_note(driver, NOTE_DUPLICATE)
    stored = _stored_annotations(conn, "agent_experience", result.data["id"])
    assert _codes(stored) == [ADVISORY_SIMILAR_L6_NOTE]
    assert _advisory(stored, ADVISORY_SIMILAR_L6_NOTE)["entry_ref"] == original

    # The same fixture, answered the other way: a note built on the same
    # template with a different subject is NOT a duplicate.
    near = _propose_note(driver, NOTE_NEAR_MISS)
    assert _stored_annotations(conn, "agent_experience", near.data["id"]) == {}


def test_an_undecided_note_is_not_yet_something_to_duplicate(datastore) -> None:
    driver, conn, _ = datastore
    # Never confirmed -- it sits in the queue as `proposed`, which is inert by
    # construction (S01). Telling the next writer their note duplicates a row
    # nobody has accepted is advice about something that may never exist.
    #
    # This pins the rule against the DATABASE. The pure resolver owns the filter
    # (the SQL deliberately does not), so without a live-PG case the rule could
    # be deleted and only the mock-side tests would notice.
    _propose_note(driver, "Ring the customer before dispatching an oversized order.")
    echo = _propose_note(driver, "Ring the customer before dispatching oversized orders")
    assert _stored_annotations(conn, "agent_experience", echo.data["id"]) == {}


def test_the_annotation_survives_the_queue_read_the_inbox_uses(datastore) -> None:
    driver, _conn, _ = datastore
    result = _propose_note(driver, "2055516 means 205/55R16")
    listed = _call(
        driver, "toee_agent_experience", "list_agent_experience", _ctx()
    )
    entry = next(e for e in listed.data["entries"] if e["id"] == result.data["id"])
    # `handleListInboxViaApi` reads `annotations` straight off this raw row.
    assert _codes(entry["annotations"]) == [ADVISORY_REFILE_TO_L7]


# --- L7 propose ---------------------------------------------------------------


def test_a_surface_form_confirmed_in_another_domain_is_annotated(datastore) -> None:
    driver, conn, _ = datastore
    # NOT "TOEE": migration 0024 seeds it into `company` already, and adding it
    # again is the governed UNIQUE conflict rather than the case under test.
    company = _confirmed_lexicon_entry(
        driver, domain="company", surface_form="TT", canonical_form="TOEE TIRE"
    )
    _confirmed_lexicon_entry(
        driver, domain="company", surface_form="TTX", canonical_form="TOEE TIRE EXPRESS"
    )

    result = _call(
        driver,
        "toee_semantic_lexicon",
        "propose_lexicon_entry",
        _ctx(),
        domain="tire",
        entry_kind="alias",
        surface_form="TT",
        canonical_form="TOEE all-season",
    )
    assert result.ok
    assert result.data["status"] == "proposed"
    stored = _stored_annotations(conn, "semantic_lexicon", result.data["id"])
    assert _codes(stored) == [ADVISORY_DUPLICATE_L7_SURFACE]
    assert _advisory(stored, ADVISORY_DUPLICATE_L7_SURFACE)["entry_ref"] == company
    assert _advisory(stored, ADVISORY_DUPLICATE_L7_SURFACE)["domain"] == "company"


def test_an_l7_proposal_sees_a_confirmed_l6_note_saying_the_same_thing(
    datastore,
) -> None:
    driver, conn, _ = datastore
    # The other cross-layer direction, and the one the mock's L7 fragment cannot
    # reach: L7 propose -> the L6 table.
    note = _confirmed_note(driver, "2055516 means 205/55R16")
    _confirmed_note(driver, NOTE)

    result = _call(
        driver,
        "toee_semantic_lexicon",
        "propose_lexicon_entry",
        _ctx(),
        domain="tire",
        entry_kind="alias",
        surface_form="2055516",
        canonical_form="205/55R16",
    )
    stored = _stored_annotations(conn, "semantic_lexicon", result.data["id"])
    assert _codes(stored) == [ADVISORY_SIMILAR_L6_NOTE]
    assert _advisory(stored, ADVISORY_SIMILAR_L6_NOTE)["entry_ref"] == note


def test_an_admin_added_entry_carries_no_write_time_advisory(datastore) -> None:
    driver, conn, _ = datastore
    _confirmed_lexicon_entry(
        driver, domain="company", surface_form="TT", canonical_form="TOEE TIRE"
    )
    added = _confirmed_lexicon_entry(
        driver, domain="tire", surface_form="TT", canonical_form="TOEE all-season"
    )
    # The same surface form a PROPOSAL is annotated for (see the test above): the
    # difference is that an admin add is itself the decision.
    assert _stored_annotations(conn, "semantic_lexicon", added) == {}


# --- NFR-3: an advisory never fails the write it describes ---------------------


def test_the_proposal_persists_when_the_advisory_computation_explodes(
    datastore, monkeypatch
) -> None:
    driver, conn, _ = datastore

    def _explode(*args, **kwargs):
        raise RuntimeError("advisory computation is broken")

    # Patched where the handler BOUND it (`from ... import l6_write_advisories`),
    # not where it is defined -- patching the definition would leave the handler
    # holding the original and this test would pass whatever the code did.
    monkeypatch.setattr(l6_handlers, "l6_write_advisories", _explode)

    result = _propose_note(driver, "2055516 means 205/55R16")
    assert result.ok, result.message
    # The write stands, and it stands UNANNOTATED rather than half-annotated.
    assert _stored_annotations(conn, "agent_experience", result.data["id"]) == {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT content FROM agent_experience WHERE id = %s", (result.data["id"],)
        )
        assert cur.fetchone()[0] == "2055516 means 205/55R16"


# --- NFR-6: the boundary the whole architecture is built on -------------------


@pytest.mark.parametrize("sql", runtime_advisories.CANDIDATE_SQL)
def test_the_candidate_queries_never_reach_outside_the_shared_layers(sql) -> None:
    """The cross-layer comparison runs L6 <-> L7 and stops there.

    L6 and L7 are the SHARED, operational-only layers (NFR-6). L4
    (``customer_memory_slot``) is per-customer PII by design, and an advisory
    that told an admin reading a shared-layer proposal "this resembles something
    in a customer's memory" would have carried that customer's data onto a row
    every admin sees. The pure resolver takes exactly two row sets and has no
    seam for a third; these two statements are the only place a third could be
    introduced, so this is where it is refused.

    No database needed: this is an assertion about the code, and it must hold on
    every machine, including the ones that skip the live-PG tests above.
    """
    lowered = sql.lower()
    assert any(
        table in lowered for table in ("semantic_lexicon", "agent_experience")
    ), sql
    for forbidden in (
        "customer_memory_slot",
        "customer_memory_audit",
        "knowledge_slot",
        "sms_message",
        "outbound_send",
        "draft_feedback",
        "account",
    ):
        assert forbidden not in lowered, (
            f"{forbidden!r} is not a shared memory layer; a write-time advisory "
            f"reading it moves data across the NFR-6 boundary: {sql}"
        )
