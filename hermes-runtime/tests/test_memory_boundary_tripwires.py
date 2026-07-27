"""Memory-boundary tripwires (0.0.5 S12 -- FR-15, FR-16, FR-17).

``docs/architecture/memory-layers.md`` documents the L1-L7 layers and a boundary
matrix in prose. This file is the machine-checked half. It lives in
``hermes-runtime/tests`` (not ``hermes/tests``) because the L5 rows below assert
against ``hermes_runtime.knowledge.ingest``, which ``toee_hermes`` cannot import;
everything else it needs comes from ``toee_hermes``, which hermes-runtime depends
on. Both suites are CI gates (``.github/workflows/ci.yml``).

FR-15 -- ``LAYER_OF_ACTION`` completeness. The map declares every catalog action,
writes and non-writes alike, and the tripwire is a pure set equality in both
directions: no undeclared catalog action, no map entry naming an action that no
longer exists. There is deliberately NO read/write classification logic --
``TOOL_CATALOG`` is action names only, so any derivation of "the writes" would be
a name-prefix heuristic that silently mis-files ``dismiss_proposal`` and silently
misses the next write that breaks the pattern. See ``toee_hermes.memory_layers``.
Scope limit: ``TOOL_CATALOG`` is the only source, so a memory write reached
outside a catalog action -- ingress identity resolution, the background job
worker, the CLI entrypoints, inbound webhooks -- is invisible to this tripwire.

FR-16 -- injection composition. ``render_injection`` must give each layer at most
one fence and let no memory content escape one. S06 extends this section with the
cross-layer PRECEDENCE assertion once L7 renders; ``_fenced_blocks`` already
returns the blocks in document order for it. Not asserted here -- 0.0.5 S01
landed the L7 STORE but nothing renders a lexicon entry yet (S06 adds the
glossary fence), and an order assertion over two fences would pin S25's
rendering, not a boundary.

FR-17 -- boundary-matrix rows (memory-layers.md "Boundaries -- what must never
mix"). Honest accounting, three buckets:

**Asserted in this file**

- *Knowledge (L5) never holds the governed operational-policy copy* -- fully
  enforced: ``check_boundaries`` EXCLUDES a policy-duplicate chunk from the
  indexable set.
- *Knowledge (L5) never holds live price/stock facts* -- partially enforced:
  ``check_boundaries`` DETECTS and reports a price-/stock-like chunk but still
  indexes it (human review). The test asserts exactly that, including the
  still-indexed half, so the gap is visible rather than implied.

**Asserted elsewhere -- referenced, not duplicated**

- *Customer Memory (L4) never holds live facts, policy text, consent state* --
  the slot enum is closed: ``hermes/tests/test_memory.py::
  test_upsert_rejects_open_ended_key`` (and its ``clear``/``dismiss`` siblings).
- *No layer holds model-supplied write attribution* (ADR-0148) -- source and
  actor are framework-derived: ``hermes/tests/
  test_customer_memory_write_source.py`` and ``hermes-runtime/tests/
  test_copilot_memory_write_overlay.py``.
- *L6 shared content is operational-only/no-PII* -- write-side scan:
  ``scan_agent_experience_content`` in ``toee_hermes.drivers.mock
  .agent_experience``, tested in ``hermes/tests/test_agent_experience.py``.
  0.0.5 S01 (D2) split its pattern sets into ``toee_hermes.content_scan``'s
  ``scan_injection`` / ``scan_pii`` (L6 composes both and is unchanged), tested
  in ``hermes/tests/test_content_scan.py``.
- *L7 shared content is operational-only/no-PII* -- the same split scan under
  L7's per-field policy (injection everywhere; PII redacted in place on
  ``evidence``/``proposer_context``, never applied to the digit-shaped
  ``surface_form``): ``scan_lexicon_write`` in ``toee_hermes.drivers.mock
  .semantic_lexicon``, tested in ``hermes/tests/test_semantic_lexicon.py`` and
  ``hermes-runtime/tests/test_datastore_driver_semantic_lexicon.py``.
- *``match_phone`` is an L1 WRITE, not a lookup* -- the fact behind that
  declaration is asserted behaviourally by ``hermes-runtime/tests/
  test_datastore_driver_identity.py::
  test_match_phone_shopify_fallback_creates_identity_link`` (the single-match
  Shopify fallback persists an ``identity_link`` row). Nothing is re-asserted
  here: a test comparing ``LAYER_OF_ACTION`` to its own value would restate the
  map rather than check it. This pairing is also the standing caveat on FR-15 --
  the completeness tripwire forces an ENTRY for every action, never a CORRECT
  one; only a behavioural test elsewhere can pin a value.

**Doc-only -- no assertion exists or can honestly be written**

- *Knowledge (L5) never holds customer PII.* The exclusion is Stage A of
  ingestion -- an OPERATOR running the Shopify connector with products/orders/PII
  excluded (``hermes_runtime/knowledge/ingest.py`` module docstring). Nothing in
  this repo executes Stage A and the Stage B boundary check has no PII scanner,
  so there is no code path to assert against. Writing one anyway would be an
  assert-nothing test.
- *A fence can be closed by the content it is fencing.*
  ``toee_hermes.plugin.hooks._render_memory`` interpolates the raw slot value
  into the block (``f"- {name}: {value}"``) with no escaping of the fence tag.
  A customer-authored value that contains the literal
  ``</untrusted_customer_memory>`` followed by a newline therefore CLOSES the
  fence early, and everything the customer wrote after that token lands OUTSIDE
  it -- in the same unfenced region as the framework-derived Session Identity
  Snapshot, where it reads as trusted narration instead of untrusted data. That
  is exactly the persistent prompt-injection surface ``_render_memory``'s own
  comment names, and it is reachable by anyone who can set a preference slot.
  ``test_no_memory_content_escapes_its_fence`` below does NOT catch it: it
  checks that KNOWN-GOOD values sit inside their fence and nowhere outside,
  which a malicious value's *prefix* still satisfies -- nothing asserts that a
  fence survives its own body. ``_render_experience`` has the identical shape
  with ``</confirmed_operational_learnings>``, though its content is
  human-confirmed rather than customer-authored. Recorded and NOT asserted on
  purpose: the honest assertion (render a tag-bearing value, expect it neutered)
  requires ``_render_memory`` to escape or reject the tag first, which is a
  runtime behaviour change and belongs to its own slice, not to a tripwire
  slice. **Partly closed by 0.0.5 S01 (D19) -- on two layers out of three.**
  ``scan_injection`` hard-rejects fence-delimiter tokens, and the write paths
  that CALL it are **L6 (``scan_agent_experience_content``) and L7
  (``scan_lexicon_write``) only**, so a value carrying one can no longer be
  stored *in those two* (``hermes/tests/test_content_scan.py``). **L4 does not
  call ``scan_injection`` at all** -- wiring it is S08's slice -- so the value
  described above, the customer-authored slot value that is the REACHABLE one,
  is still storable today. Sharing a resolver covers its callers and nothing
  more. The RENDER side is unescaped for EVERY layer and owns the residual risk
  for anything already stored -- S06 closes it and extends this file's
  composition test.
- *Nothing pins a value to the RIGHT fence.* The two composition tests assert
  "each layer has exactly one fence" and "each declared value appears in its own
  fence and nowhere outside any fence". A value duplicated into a SECOND layer's
  fence -- an L4 slot value also rendered into the L6 block -- satisfies both
  and passes. Not asserted here: the rendered fences carry no provenance, so a
  checker would have to re-derive which layer a string came from, which is the
  classification machinery this file deliberately does without.
"""

from __future__ import annotations

import re
from collections import Counter

from hermes_runtime.knowledge.ingest import check_boundaries

from toee_hermes.memory_layers import DECLARABLE_LAYERS, LAYER_OF_ACTION
from toee_hermes.plugin.hooks import render_injection
from toee_hermes.tool_catalog import TOOL_CATALOG

# --- FR-15: LAYER_OF_ACTION completeness -----------------------------------


def _catalog_actions() -> set[tuple[str, str]]:
    """Every ``(tool, action)`` the registry itself enumerates."""
    return {(tool, action) for tool, actions in TOOL_CATALOG.items() for action in actions}


def test_layer_of_action_covers_every_catalog_action_and_nothing_else() -> None:
    declared = set(LAYER_OF_ACTION)
    catalog = _catalog_actions()

    assert not (catalog - declared), (
        "catalog actions with no declared memory layer: "
        f"{sorted(catalog - declared)}. Add each to toee_hermes.memory_layers"
        ".LAYER_OF_ACTION -- the layer it writes, or None if it writes no"
        " memory-layer content."
    )
    assert not (declared - catalog), (
        "LAYER_OF_ACTION declares actions that are not in the catalog: "
        f"{sorted(declared - catalog)}. Stale entries make the map lie; remove"
        " them."
    )


def test_declared_layers_come_from_the_documented_model() -> None:
    undeclarable = {key: value for key, value in LAYER_OF_ACTION.items() if value not in DECLARABLE_LAYERS}
    assert undeclarable == {}, (
        f"layer values outside docs/architecture/memory-layers.md: {undeclarable}"
    )


# --- FR-16: injection composition -------------------------------------------

# layer -> the fence tag toee_hermes.plugin.hooks wraps that layer's block in.
# S06 adds L7 here when the lexicon glossary block lands.
FENCE_TAG_OF_LAYER: dict[str, str] = {
    "L4": "untrusted_customer_memory",
    "L6": "confirmed_operational_learnings",
}

_FENCE_RE = re.compile(r"<(?P<tag>[a-z0-9_]+)>\n(?P<body>.*?)\n</(?P=tag)>", re.DOTALL)

# Distinctive values so a containment check cannot pass on an incidental substring.
_SNAPSHOT = {"shopify_customer_id": "cust_snapshot_42", "verified": True}
_MEMORY = [
    {"slot": "preferred_name", "value": "memoryvaluealpha"},
    {"slot": "contact_time_preference", "value": "memoryvaluebeta"},
]
_EXPERIENCE = [
    {"kind": "note", "content": "experiencevaluegamma"},
    {"kind": "procedure", "content": "experiencevaluedelta"},
]


def _fenced_blocks(text: str) -> list[tuple[str, str]]:
    """``(tag, body)`` for every fenced block, in document order."""
    return [(m.group("tag"), m.group("body")) for m in _FENCE_RE.finditer(text)]


def _all_layers_populated() -> str:
    text = render_injection(_SNAPSHOT, _MEMORY, _EXPERIENCE)
    assert text is not None
    return text


def test_composition_gives_each_layer_exactly_one_fence() -> None:
    text = _all_layers_populated()

    assert Counter(tag for tag, _ in _fenced_blocks(text)) == Counter(FENCE_TAG_OF_LAYER.values())
    # Raw-tag counts too: a stray unclosed duplicate opener would slip past the
    # balanced-pair regex above but is still a second fence for that layer.
    for tag in FENCE_TAG_OF_LAYER.values():
        assert text.count(f"<{tag}>") == 1
        assert text.count(f"</{tag}>") == 1


def test_no_memory_content_escapes_its_fence() -> None:
    text = _all_layers_populated()
    blocks = _fenced_blocks(text)
    bodies = dict(blocks)
    # dict() keeps only the LAST block per tag, so a duplicate fence would be
    # silently dropped here and the lookups below would still pass. The sibling
    # test above is what makes that safe -- assert it locally rather than depend
    # on another test having run.
    assert len(blocks) == len(bodies)

    for slot in _MEMORY:
        assert slot["value"] in bodies[FENCE_TAG_OF_LAYER["L4"]]
    for entry in _EXPERIENCE:
        assert entry["content"] in bodies[FENCE_TAG_OF_LAYER["L6"]]

    outside = _FENCE_RE.sub("", text)
    # The L1 Session Identity Snapshot is deliberately UNFENCED: it is
    # framework-derived, not customer- or model-authored, so it is not what the
    # fences exist to contain. Asserting it survives also proves the strip above
    # did not simply empty the string, which would make the rest vacuous.
    assert "cust_snapshot_42" in outside
    for slot in _MEMORY:
        assert slot["value"] not in outside
    for entry in _EXPERIENCE:
        assert entry["content"] not in outside


# --- FR-17: boundary-matrix rows --------------------------------------------


def test_matrix_row_l5_never_holds_the_governed_operational_policy_copy() -> None:
    policy_text = "Returns are accepted within 30 days of delivery."
    rows: list[dict[str, str]] = [
        {"chunk_text": policy_text},
        {"chunk_text": "Toee Tire has fitted winter tires in the GTA since 2009."},
    ]

    report, indexable = check_boundaries(rows, [policy_text])

    assert [row["reason"] for row in report] == ["policy_duplicate"]
    assert indexable == [rows[1]], "a policy duplicate must be excluded from the corpus"


def test_matrix_row_l5_live_facts_are_flagged_by_the_ingest_boundary_check() -> None:
    rows: list[dict[str, str]] = [
        {"chunk_text": "The 205/55R16 is $129.99 installed."},
        {"chunk_text": "Only 12 units left in stock."},
        {"chunk_text": "We stand behind our fitment advice."},
    ]

    report, indexable = check_boundaries(rows)

    assert [row["reason"] for row in report] == ["live_fact_pattern", "live_fact_pattern"]
    # Honest scope: this row is DETECT-only. live_fact_pattern chunks are
    # reported for human review and still indexed (only policy duplicates are
    # excluded) -- so the matrix row is half-enforced, and this assertion says so
    # rather than implying a block that does not happen.
    assert indexable == rows
