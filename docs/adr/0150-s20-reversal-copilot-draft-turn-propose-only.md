# S20 reversal: the copilot draft turn's Customer Memory write is propose-only

> **Status: Accepted — implemented** (decided during 0.0.3, 2026-07-20). Amends
> [ADR-0148](0148-copilot-agent-source-actor-attribution-and-context-only-binding.md)
> and [ADR-0111](0111-customer-memory-slots-and-write-sources.md) — reverts the
> **production write-routing consequence** of 0.0.1's S20 slice (formalized by
> ADR-0148), NOT the `copilot_agent` source vocabulary or the resolver mapping
> those ADRs introduced, which both stand unchanged. Ships on
> `feat/0.0.3-land-all`: S13 (FR-14, PRD Track T3, PRD §7 decision 5).

## Context

0.0.1's S20 slice threaded the same per-tool `extra_drivers` overlay S04 gave the
bound External turn onto the copilot draft turn's UNBOUND boot path
(`copilot_turn.py`'s `make_copilot_run_turn` → `boot_profile(INTERNAL,
extra_drivers=...)`). Before S20, an agent-initiated
`toee_customer_memory.upsert_preference` during a draft always fell to the
ephemeral MockDriver and was silently discarded; after S20, with
`TOOL_BACKEND=datastore`, it reached Postgres and persisted — attributed
`source=copilot_agent` (ADR-0148, decided the following day, gave that write its
honest label and a `NULL` actor once it became consequential).

The only guardrail on that write was a system-prompt instruction ("never save a
preference you merely inferred" — `copilot_turn.py`'s
`_MEMORY_WRITE_DISCIPLINE`, mirroring `persona.py`'s proven external rule) plus
the eval-path assertion `forbid_inferred_upsert` (`eval/scenarios/30-copilot-
memory-no-inferred-write.yaml`). That is a **soft** guarantee: it depends on the
model reliably following the instruction, not on structure. ADR-0148 itself
named this directly (decision 1's rationale): "`copilot_agent` makes an inferred
write **visible** even on the turns the guard holds" — visible after the fact,
not prevented.

0.0.2's grilled exploration (`workspace/0.0.2/EXPLORATION.md`) shipped the
lightweight A+B+E+NFR-3 guardrail (the honest label, the actor column, the
context-only binding — ADR-0148) as the deliberate interim: "promote if UAT of
the 0.0.2 autonomous-write path feels loose." The 0.0.3 exploration's Candidate
2 ("propose → confirm", option D) is the promotion: the governance-faithful
target where an LLM can never write customer memory directly, full stop — it
can only *propose*, and a human decides. 0.0.3's grilled decision G5 confirmed
adopting it, which by construction requires *disabling* S20's autonomous write
(reverting to read-only on the draft turn's write path — option C) before the
proposal surface (S14/S15) is built on top. This ADR is that reversal.

## Decision

**The copilot draft turn's `toee_customer_memory` tool no longer receives the
datastore write overlay. It always writes through the shared mock driver — an
agent-initiated write during a draft is never persisted.**

Mechanically (`hermes_runtime/tool_backend.py`):

```python
def _turn_extra_drivers(*, include_memory_write: bool = True) -> Optional[dict[str, Any]]:
    mem = _customer_memory_extra_drivers() if include_memory_write else None
    kn = _knowledge_extra_drivers()
    if mem is None and kn is None:
        return None
    return {**(mem or {}), **(kn or {})}
```

- The **external** turn (`openrouter.py`) keeps calling `_turn_extra_drivers()`
  with no arguments — the default `include_memory_write=True` leaves its write
  path (`source=customer_explicit`) completely untouched. This is the same
  function both turns have shared since S10 (Standards fix #1); it now takes one
  keyword so the two turns can diverge on this single axis without forking the
  whole overlay-merge function into two copies.
- The **copilot draft turn** (`copilot_turn.py`) now calls
  `_turn_extra_drivers(include_memory_write=False)`. `toee_customer_memory` is
  left out of the merged overlay regardless of `memory_enabled()` /
  `TOOL_BACKEND` — the tool falls back to the shared `MockDriver`, whose writes
  are ephemeral and per-process. The Knowledge overlay (S09/FR-5,
  `toee_knowledge_search`) is unaffected: it is gated on its own independent
  axis (`KNOWLEDGE_BACKEND`) and still merges in exactly as before — the S20
  reversal is scoped to the memory-write axis only, not a rollback of S10's
  knowledge wiring.

**What is preserved, deliberately:**

- **The `internal_copilot` allowlist still carries `toee_customer_memory`.** The
  draft agent still calls `upsert_preference` (guarded by the unchanged
  no-inferred prompt discipline as defense in depth) — the call itself is not
  removed, only its consequence. This matters for S14: the proposal envelope is
  built from the SAME tool-call shape the agent already produces, not a new
  tool.
- **Memory READS are untouched.** The draft turn's Customer Memory injection
  (`copilot_turn._load_case_memory`, S08) goes through the gateway store
  directly — it was never routed through `extra_drivers` in the first place, so
  this reversal has no read-side surface at all. A draft still opens grounded in
  the customer's existing preferences.
- **`resolve_memory_write_source`'s mapping is unchanged.** `internal_copilot`
  with no `context.user_id` still resolves to `copilot_agent`
  (`hermes/toee_hermes/drivers/mock/memory.py`, ADR-0148 decision 1); the enum
  keeps all four values. This ADR removes the **production path** that could
  ever exercise that branch with a real datastore write — not the vocabulary.
  Historical `copilot_agent` rows (from 0.0.1/0.0.2 deployments where S20 was
  live) keep their honest meaning; the source stays reachable in principle for
  any future non-UI internal write path a later ADR might introduce, reviewed
  against ADR-0148's decision-1 invariant same as always.
- **ADR-0148's invariants all still hold, unchanged**: `source` /
  `actor_account_id` / binding keys are framework-derived only; binding is
  context-only (no model-supplied `channel_identity_id` carve-out); an
  unresolvable identity still fails closed to `policy_blocked`; the removal
  tripwire (`channel_identity_id` never binds) is untouched code and stays
  green. This ADR touches none of those three decisions — it operates one layer
  up, at *whether the write overlay is wired in at all* for this one turn.

**What comes next (out of scope here, PRD Track T3):** S14 threads a structured
`proposals[]` array (slot, value, evidence-turn) through the draft turn's result
alongside `draft`. S15 renders pending proposals in the Workbench preferences
panel with Accept/Dismiss — Accept routes through the **existing** governed
dispatch write (`upsert_preference` via `POST /v1/tools:dispatch`, actor-
attributed → `employee_confirmed`), Dismiss persists nothing. No new write path
is introduced by either slice; propose→confirm reuses the confirmed-write
machinery ADR-0148 already governs.

## Why (RK-3: prevents "why is this off" archaeology)

Without this ADR, a future reader finds `toee_customer_memory` in the copilot
allowlist, sees `_MEMORY_WRITE_DISCIPLINE` in the prompt, and reasonably
concludes the draft turn is meant to write — because until this slice, it was.
`git blame` on `_turn_extra_drivers`'s `include_memory_write` parameter finds
this ADR; the docstring on the parameter and the boot-site comment in
`copilot_turn.py` both point here directly, so "why is this off" resolves in one
hop instead of an archaeology dig through S20/ADR-0148/S13 in sequence.

The reversal is deliberately a one-line-of-consequence structural change (a
boolean flag at one call site), not a removal of `toee_customer_memory` from
the allowlist or a rewrite of the resolver — because S14/S15 need the exact same
tool-call shape to build the proposal envelope on top of. Making the LLM
literally unable to persist (never routed to a real driver) is the governance
property Candidate 2 wants: "can the LLM write autonomously" becomes moot by
construction, not by convention.

## Consequences

- A copilot draft turn's `upsert_preference` call is now **inert** in
  production (`TOOL_BACKEND=datastore` or not) — it always resolves against the
  mock driver and is discarded when the turn ends. This is intentional and is
  exactly S13's acceptance criterion; S14 gives that inert call somewhere useful
  to go (the proposal envelope) instead of leaving it a dead end.
- 0.0.2's S20 test suite (`test_copilot_memory_write_overlay.py`,
  `test_tool_backend.py`'s `_turn_extra_drivers` coverage) is **rewritten, not
  deleted** (RK-3): the tests that proved "the write reaches Postgres" now prove
  its opposite — "the write never reaches Postgres, even with memory fully
  enabled" — using the same fixtures and the same regression-tripwire shape
  (patch `select_tool_driver` to the fixture's real schema-bound driver, so a
  reintroduced overlay would flip the readback RED instead of silently missing
  the write).
- No eval scenario needed re-recording. `eval/scenarios/30-copilot-memory-no-
  inferred-write.yaml` (`forbid_inferred_upsert`) already asserted the model
  never calls `upsert_preference` when nothing was explicitly stated — a
  transcript/tool-call assertion, not a persistence assertion, so it holds
  under propose-only exactly as it held under S20. No other recorded scenario
  targets the `internal_copilot` channel or asserts a persisted draft-turn
  write; the eval-artifact audit finding this ADR was scoped against (0.0.3 PRD
  FR-14 / audit finding 8) found nothing to re-record.
- `docs/architecture/memory-layers.md` L4 write-attribution note is updated: the
  bullet documenting `copilot_agent` now says it is history/vocabulary-only in
  production since S13, pointing here.

## Considered options

- **Remove `toee_customer_memory` from the `internal_copilot` allowlist
  entirely (rejected).** Would also remove the tool-call shape S14 needs to
  build the proposal envelope from, and would remove memory reads too if not
  done carefully (reads happen through a separate seam, but the allowlist gates
  the tool as a whole) — a coarser, riskier change than gating the one overlay
  that actually persists.
- **Keep the overlay but make `upsert_preference` itself check `context.
  user_id` and refuse to write without one (rejected).** Duplicates
  `resolve_memory_write_source`'s existing discriminator logic in a second
  place, and still requires the mock driver / real driver split to express "the
  call happens but nothing is stored" cleanly — the overlay toggle is the
  narrower, single-point change.
- **A copilot-specific driver-selection function, forked from
  `_turn_extra_drivers` (rejected).** Two copies of the merge logic is exactly
  what S10's Standards fix #1 consolidated away; a keyword argument keeps one
  function, one place to read the contract between the two turns.
- **Remove `copilot_agent` from `MEMORY_SOURCE_VALUES` (rejected).** Historical
  rows already carry it (0.0.1/0.0.2 deployments where S20 was live); removing
  the enum value would make those rows unrepresentable. The resolver mapping
  and vocabulary are explicitly out of this ADR's scope (see Decision, above).

## Verification

- **Unit** (`hermes-runtime/tests/test_tool_backend.py`):
  `test_turn_extra_drivers_excludes_memory_write_even_when_backend_is_datastore`,
  `test_turn_extra_drivers_keeps_knowledge_when_memory_write_excluded` — the
  merge-function contract, both overlay axes independently.
- **Hermetic seam** (`hermes-runtime/tests/test_copilot_memory_write_overlay.py`):
  `test_copilot_run_turn_never_injects_the_datastore_driver_for_memory_write`,
  `test_copilot_run_turn_keeps_the_knowledge_overlay_without_memory_write` —
  what `copilot_turn.py` hands `boot_profile`, `boot_profile` stubbed.
- **Datastore, live Postgres** (same file):
  `test_copilot_draft_turn_scripted_write_does_not_persist_to_datastore` — a
  real scripted `AIAgent` turn drives the real governed dispatch path end to
  end; `select_tool_driver` is still patched to the fixture's schema-bound
  driver (RED-capable: a regression that reintroduced the overlay would land in
  this throwaway schema and the row-count readback would flip from 0, not miss
  the write by writing to an unrelated connection).
- **Unaffected, reverified green**: `test_composite_driver_overlay.py` and
  `test_openrouter.py` (the external turn's write path, its own
  `_turn_extra_drivers()` default-argument call); `hermes/tests/
  test_customer_memory_write_source.py` (the resolver mapping, unchanged);
  `test_copilot_turn.py`'s no-send allowlist tripwire and no-inferred-write
  system-message tests.
- Full-suite regression: `hermes-runtime` and `hermes`, live Postgres, no
  skips.
