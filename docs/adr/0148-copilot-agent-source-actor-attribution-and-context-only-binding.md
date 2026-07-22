# `copilot_agent` source, actor attribution, and context-only binding for Customer Memory writes

> **Status: Accepted — implemented** (decided 2026-07-14, shipped 2026-07-15,
> 0.0.2). Amends [ADR-0111](0111-customer-memory-slots-and-write-sources.md),
> [ADR-0112](0112-provisional-customer-memory-merge-on-verified-ingress.md), and
> [ADR-0114](0114-toee-customer-memory-v1-actions.md). Ships on
> `feat/0.0.2-memory-governance`: S01 `37806ea`, S02 `38644f1`, S04 `1ad97fe`.

> **Superseded in part by [ADR-0150](0150-s20-reversal-copilot-draft-turn-propose-only.md)**
> (0.0.3, S13). The `copilot_agent` **source discriminator and vocabulary** (decision 1),
> the **`actor_account_id` column** (decision 2), and the **context-only binding**
> (decision 3) all still hold exactly as decided here. What ADR-0150 removes is the
> *production write path* that could ever exercise decision 1's `copilot_agent` branch
> with a real datastore write: the copilot draft turn's write overlay is gone, so an
> agent-initiated write is discarded on the shared mock driver, never persisted.
> `copilot_agent` becomes history/vocabulary-only going forward.

## Context

0.0.1 shipped Customer Memory's governed write path (ADR-0111/0112/0114): the
External profile always writes `customer_explicit`; the Internal Copilot profile
always writes `employee_confirmed`; binding derives from the turn's resolved
identity, with an `internal_copilot`-only fallback that let a model-supplied
`channel_identity_id` tool param mint a `provisional:{param}` key when context
carried none. The Copilot **draft turn** — the agent drafting a reply, unbound
to any human action — already had `toee_customer_memory` in its boot allowlist
(ADR-0114) and could call `upsert_preference` on its own initiative, guarded
only by a prompt instruction not to infer; a later 0.0.1 slice (S20) routed
that write to the real datastore instead of an ephemeral mock, making the
mislabeling below consequential rather than moot.

That combination exposed three gaps the 0.0.2 PRD (§4.1/§4.2, FR-2/FR-4/FR-5)
tracks as RK-1/RK-2/RK-4:

1. **`resolve_memory_write_source` discriminated on `context.profile` alone.**
   Every `internal_copilot` write — including one the agent decided to make on
   its own, mid-draft, with no employee at the keyboard — was labelled
   `employee_confirmed`. The audit could not tell an AI-inferred write from a
   rep's deliberate correction.
2. **The acting employee was resolved, then dropped.** The dispatch route
   already resolved `context.user_id` from the request's `actor_account_id`,
   but no column persisted it — 0.0.1 NFR-3 closed the gap in principle, not in
   the schema.
3. **Binding was partly model-directed on one profile.** Every other profile's
   binding derives solely from the framework-resolved identity
   (`binding_key_from_identity`); `internal_copilot` alone kept a fallback onto
   a model-supplied param when context had no identity — undocumented in any
   ADR, introduced during 0.0.1's own S02 slice, and exercised only by the
   since-deleted S15 characterization test.

All three fixes share the same shared resolvers
(`hermes/toee_hermes/drivers/mock/memory.py`), which the Postgres datastore
handler (`hermes-runtime/hermes_runtime/datastore/handlers/memory.py`) imports
by name — one source of truth for both — so this ADR records them together.

## Decision

### 1. `copilot_agent` source, discriminated by `context.user_id` presence (amends ADR-0111)

`resolve_memory_write_source(context)` now branches:

| `context.profile` | `context.user_id` | `source` |
| --- | --- | --- |
| `customer_service_external` | n/a | `customer_explicit` (unchanged) |
| `internal_copilot` | present | `employee_confirmed` |
| `internal_copilot` | absent | **`copilot_agent`** (new) |
| any other profile | n/a | fail-closed `policy_blocked` (defense in depth; not reachable today — allowlist) |

`merged_provisional` is untouched — set exclusively by the async
provisional→verified merge path (S10,
`PostgresGatewayStore.merge_provisional_memory`), never by this resolver.

**The invariant this rests on (RK-2).** `context.user_id` is set in exactly one
place: the deterministic `POST /v1/tools:dispatch` route
(`tool_dispatch_app.py:190-204`), from the request body's `actor_account_id` —
an explicit, framework-asserted rep identity the Workbench BFF supplies for a
UI-initiated correction. The Copilot draft turn boots on a structurally
different path (`copilot_turn.py`'s `make_copilot_run_turn` →
`boot_profile(INTERNAL, identity=..., extra_drivers=...)`); `boot_profile` takes
**no `user_id` parameter at all**, so a tool call the agent makes on its own
during a draft turn can never carry one, regardless of which employee is
nominally viewing the draft. UI route ⟺ actor present; unbound draft turn ⟺
actor absent — the discriminator is a structural fact about which boot path ran,
not a guess about intent.

`source` stays framework-derived only in both branches: `resolve_memory_write_source`
reads `context`, never `params`, so a model-supplied `source` or `user_id`
inside a tool call's params is always ignored (proven for both the mock and
datastore handlers).

No migration was needed for this decision: `customer_memory_slot.source` is
`TEXT NOT NULL` with no `CHECK` constraint, so a fourth Python-side enum value
is schema-compatible (NFR-1).

### 2. `actor_account_id` column persists the acting rep (amends ADR-0111)

`customer_memory_slot` gains a nullable `actor_account_id TEXT` column
(`migrations/0007_customer_memory_actor.sql`, additive `ALTER`, no `DEFAULT`, no
backfill). `_upsert_preference` reads `actor_account_id = context.user_id` — the
same field, the same presence check as decision 1 — and threads it into the
`INSERT` and the `ON CONFLICT ... DO UPDATE SET actor_account_id =
EXCLUDED.actor_account_id` (latest-write-wins, matching `source`/`evidence`/
`binding_kind`):

- a UI correction persists the rep's account id;
- an AI draft-turn write persists `NULL` (no `user_id` on that boot path);
- a provisional→verified merge persists `NULL` (`PostgresGatewayStore`'s merge
  `INSERT` never lists the column; unmodified this slice).

The column name matches the existing actor-reference convention
(`cases.assignee_account_id`, `cases.resolved_by_account_id`,
`workbench_audit_log.account_id`). It is deliberately **not** echoed in
`upsert_preference`'s returned dict — the write must be read back directly from
Postgres (the PRD's "live, not mock" proof principle), and NFR-1 asks for no new
read dependency until a caller needs one.

This closes 0.0.1 NFR-3, which resolved the actor and then discarded it.

### 3. Binding is context-only; the `channel_identity_id` carve-out is removed (amends ADR-0112)

`resolve_customer_memory_binding(context, params)` now derives the binding key
**solely** from `binding_key_from_identity(context.identity)`, on every profile.
The deleted branch:

```python
if context.profile == INTERNAL:
    channel_identity_id = _read_string(params, "channel_identity_id", "channelIdentityId")
    if channel_identity_id is not None:
        return f"provisional:{channel_identity_id}", "provisional"
```

let a model-supplied tool param mint a `provisional:{param}` binding key on
`internal_copilot` whenever context carried no identity — the one profile whose
binding was partly model-directed. It is gone, along with its now-dead
`_read_string` helper. Every profile — `internal_copilot` included — now fails
closed to `policy_blocked` when no identity resolves; no code path produces a
model-named `provisional:{param}` key.

**Why the UI correction path is unaffected.** A Workbench correction still binds
correctly without the carve-out because a *different* 0.0.1 mechanism (S16,
`tool_dispatch_app._resolve_case_identity`) already populates `context.identity`
from the case's resolved identity before dispatch — a real, framework-resolved
identity, not a model-supplied param. The carve-out was a redundant fallback.
The Postgres datastore handler needed no separate change: it imports
`resolve_customer_memory_binding` from this same module, so it inherits the fix.

**Test evidence, not just the deletion.** The three existing tests that
asserted the carve-out succeeding were updated to assert `policy_blocked`
instead; the S15 characterization test that documented the old carve-out
contract was deleted (the behavior it documented no longer exists); a new
removal-tripwire test (real Postgres) reproduces the exact deleted-S15 scenario
and asserts **zero rows ever land under the old dead
`provisional:{channel_identity_id}` key** — so a reintroduced carve-out fails
this test, not just a code review (RK-4).

## Governance matrix (now true, proven against live Postgres)

| Write origin | `source` | actor | binding |
| --- | --- | --- | --- |
| UI correction (dispatch route, `case_id`) | `employee_confirmed` | rep account id | case-resolved identity |
| AI draft-turn write | `copilot_agent` | `NULL` | case-resolved identity |
| provisional→verified merge | `merged_provisional` | `NULL` | verified key |
| unresolvable-identity write | — (blocked) | — | `policy_blocked` |
| model-supplied `channel_identity_id` | — (blocked) | — | `policy_blocked` (carve-out removed) |

## Consequences

- A supervisor or auditor reading a case's write history can now tell an
  AI-inferred write from a rep's deliberate correction, and who made the
  correction — the audit trail's honesty is the point of all three decisions
  together (NFR-2).
- `MEMORY_SOURCE_VALUES` grows from three entries to four; a consumer that
  assumed only three, or exhaustively switched on the old set, would need to
  handle `copilot_agent` — none does today (repo-wide grep, S01).
- The nullable actor column has no reader yet: no index, no audit/reporting view
  filters by it. Not a regression — adding one now would be speculative for a
  column nothing reads, consistent with RK-6's minimal-migration-risk
  mitigation (nullable, no backfill, no read dependency until FR-4 needed one).
- **RK-2 remains open by design, not closed by this ADR.** Both `source` and
  `actor_account_id` are only as honest as `context.user_id`'s own contract: a
  future non-UI internal caller that sets `user_id` without a real employee at
  the keyboard, or a UI path that forgets to, would mislabel both fields at
  once, since both read the same value. This ADR documents the invariant
  (decision 1) so a future change to who sets `context.user_id` is reviewed
  against it; it is not itself an enforcement mechanism beyond the tests cited
  below.

## Addendum — a SECOND source of `context.user_id` (0.0.4 S04, FR-11)

> Added 2026-07-21 (0.0.4 S04 fix wave 1). Decision 1's invariant above is
> **amended, not repealed**: `context.user_id` no longer has exactly one source.
> Recorded here rather than in [ADR-0155](0155-durable-postgres-job-queue-supersedes-cloud-tasks.md)
> because it is *this* ADR's invariant that moved — anyone who touches
> `resolve_memory_write_source`, the `actor_account_id` column, or the
> `context.user_id` contract reads this file, and none of them would think to
> read a queue ADR. ADR-0155 carries a one-line pointer back here.

### What changed

0.0.4 S04 moved the Customer Memory retention sweep off the request thread: the
admin panel's button now enqueues a `retention` job (`datastore/handlers/
retention.py::_enqueue_retention_sweep`) and the background worker runs it. To
keep the sweep's `workbench_audit_log` row attributed to the supervisor who
clicked, the enqueue writes `{"profile": …, "actor_account_id": context.user_id}`
into the job's JSONB payload, and `hermes_runtime/retention_sweep.py::run_sweep`
rebuilds a `ToolExecutionContext(profile=…, user_id=payload["actor_account_id"])`
before calling `execute_tool`.

So the invariant's true statement is now:

> `context.user_id` is set in **two** places: the deterministic
> `POST /v1/tools:dispatch` route, from the request body's `actor_account_id`;
> and `retention_sweep.run_sweep`, from a `job.payload` field that the dispatch
> route itself wrote one hop earlier.

An audit attribution now flows from **data** (a queue row) rather than only from
an authenticated request. That is the property to keep an eye on — it is not
weaker attribution today, but it is a different *kind* of attribution.

### Why it is safe today — the specific properties that bound it

1. **The payload's writer is the dispatch route.** The only two ways a
   `retention` job exists are `_enqueue_retention_sweep` (reached only through
   `tools:dispatch`, where `context.user_id` came from an authenticated request)
   and `PostgresJobQueue.tick_schedules`, whose payload has no
   `actor_account_id` at all — an unattended run is `None`, exactly like the CLI
   entrypoint always was. There is no third writer: `insert_job` is Python-only,
   the `job` table has no external write path, and both enqueue actions are in
   `_AGENT_EXCLUDED_ACTIONS` so no model can reach them.
2. **The reconstructed context never reaches the discriminator.** `run_sweep`
   dispatches `toee_retention.trigger_retention_sweep`, which touches
   `customer_memory_slot` only through a DELETE-by-age. It never calls
   `resolve_memory_write_source`, never writes `source`, and never writes
   `actor_account_id` — the one field it feeds is `workbench_audit_log.account_id`
   on its own `retention_sweep` row, whose semantics ("who asked for this sweep")
   are exactly what the payload carries.
3. **Absent means unattended, and that is already a legal value.** A payload with
   no actor produces `user_id=None`, the same "no attributed actor" the cron-shaped
   CLI entrypoint has had since 0.0.3 S28 — not a fallback that invents one.

### What a future slice must preserve

- **Do not reconstruct a `ToolExecutionContext` from a job payload for anything
  that reaches `resolve_memory_write_source`.** A payload-derived `user_id` on a
  Customer Memory write path would let the *queue* decide `employee_confirmed`
  vs `copilot_agent` — the forgery decision 1 exists to prevent, one indirection
  further away. If a memory write ever has to run asynchronously, carry the
  resolved `source` in the payload as a framework-derived fact, or re-resolve it
  from something authenticated; do not re-derive it from a rebuilt context.
- **Keep `job.payload` writable only from Python enqueue sites.** The safety of
  (1) is entirely "the only writer is the authenticated route". A replay/redrive
  feature (S05) that lets an operator *edit* a payload before re-running it would
  break that; a replay that re-runs the payload verbatim does not, but its own
  audit must name the replaying admin (FR-13) so the trail stays honest about who
  asked twice.
- **Any new job type that rebuilds a context must be listed here.** Today there is
  exactly one: `retention`. `ingest` *carries* an `actor_account_id` in its payload
  but never reads it (`background_worker._run_ingest` reads only the corpus path),
  and `l6_review`'s payload carries no actor at all. A second rebuilder added
  without an entry here makes this an unwritten pattern rather than a documented
  exception, which is how invariants rot.

## Considered options

- **Keep the profile-only source mapping and rely on the FR-1 prompt guard alone
  to prevent inferred writes (rejected).** A soft prompt rule can still slip;
  even when it doesn't, an inferred-but-correct write and a rep's deliberate
  correction were indistinguishable in the audit. `copilot_agent` makes an
  inferred write **visible** even on the turns the guard holds (RK-1).
- **Trust a model-supplied actor/source tool param instead of deriving from
  `context` (rejected).** The model could then forge `employee_confirmed` for
  its own draft-turn write — exactly the forgery "framework-derived only"
  exists to prevent.
- **Backfill `actor_account_id` for historical rows (rejected).** No reliable
  historical actor exists to backfill from, and FR-4 has no read dependency on
  pre-migration rows; nullable with no backfill is the minimal-risk migration
  (NFR-1/RK-6).
- **Keep the `channel_identity_id` carve-out but log its use (rejected).** Still
  lets a model-supplied param direct a governed write's binding; FR-5 calls for
  removal, and S16's case-identity resolution already made the fallback
  redundant.
- **Fail open to a shared/synthetic key when identity is unresolvable
  (rejected).** Reintroduces the pre-S02 cross-customer bucket ADR-0112 already
  rejected; fail-closed `policy_blocked` is the only acceptable outcome for an
  unresolvable identity.

## Verification

Live, not mock (PRD §6.0 proof principle #1) — every assertion below reads back
from Postgres directly, not a tool return value, except the pure-resolver unit
tests:

- **Unit** (framework-derived, model-cannot-forge): `test_customer_memory_write_source.py`
  (R1), `test_memory.py` (R1/R3 driver-level, including a model-supplied
  `user_id`/`source`/`channel_identity_id` inside tool params being ignored),
  `test_customer_memory_binding.py` (R3).
- **Datastore, live Postgres** (direct `conn.cursor()` SELECT):
  `test_datastore_driver_memory.py` (source per origin — R1; actor per origin —
  R2; carve-out → `policy_blocked` — R3), `test_datastore_migrate.py` (column
  exists post-migrate; a pre-existing row reads `NULL` after the 0007 `ALTER`,
  proving no backfill), `test_datastore_merge_provisional.py` (merge persists a
  `NULL` actor — R2, matrix row 3).
- **Removal tripwire**
  (`test_removal_tripwire_internal_copilot_channel_identity_id_never_binds`,
  real Postgres): reproduces the deleted S15 scenario and asserts zero rows
  land under the old dead key — the "removal tripwire" proof principle (§6.0
  #4); it replaces the S15 characterization test it supersedes.
- Full-suite regression, live Postgres, no skips: `hermes` 423 passed;
  `hermes-runtime` 326 passed (S01 session) and 331 passed (S02 session), 0
  failures — both runs exercise decision 3's code (already on the branch) live,
  closing the live-Postgres verification gap S04's own report flagged (Docker
  unreachable that session, so its datastore tests only collected + skipped).
