# L6 Agent-experience: confirmed-entry injection, external read-only, and the eval pin

> **Superseded in part by 0.0.5 S04 (FR-4) — see the superseding note at the end
> of this file.** Decision 5 ("External is READ-ONLY") stands for the **agent**;
> it never constrained a **fork**, and 0.0.5 puts one on the gateway turn path.
> Read that note before concluding that a proposal originating on an external
> conversation contradicts this ADR.

> **Status: Accepted — implemented** (decided during 0.0.3, 2026-07-21). Closes
> the L6 Agent-experience chain opened by S22
> ([migration 0008](../../hermes-runtime/migrations/0008_agent_experience.sql)),
> S23 (the review pass that proposes), and S24 (the human Accept/Reject confirm
> gate). Ships on `feat/0.0.3-land-all`: S25 (FR-25/26/27, NFR-5/6/8, PRD Track
> T6). This is the ADR the L6 store DDL and the S23 flag comment both forward-
> reference ("S25 formalizes the eval pin + the L6 ADR").

## Context

L6 ("what the agent learns from doing the job") is a net-new retention surface,
governed **propose → confirm → inject**. The chain to here:

- **S22** created one `agent_experience` table with a `kind` field
  (`note`|`procedure`) — one store, not Hermes's separate notes/skills stores
  (audit finding 4) — plus the governed `toee_agent_experience` tool and the
  write-side PII/injection scan.
- **S23** added the bounded post-copilot-turn review fork that may call
  `propose_experience`, persisting `status='proposed'`. Gated behind its OWN L6
  flag `AGENT_EXPERIENCE_LEARNING` (default OFF) so the eval record/replay path
  is byte-identical.
- **S24** added the admin Accept/Reject gate that flips a proposed row to
  `status='confirmed'` or `'rejected'`, decider framework-derived.

A proposed row has been **inert** the whole time. S25 is the only slice that ever
reads a confirmed entry and puts it in front of a model. That makes it
EVAL-SENSITIVE (it injects into turns) and TURN-CRITICAL (it runs on the turn
path), so the make-or-break properties are structural, not conventional.

Two questions had to be resolved before injecting:

1. **Where does a confirmed entry go?** The copilot draft turn (US19) is the
   obvious first consumer — reps review every draft, so a confirmed learning
   surfaces where a human is already in the loop. The grilled decision also said
   the **external agent reads already-confirmed entries** (「外部 agent 只读已确认
   条目」): read-only over confirmed learnings, never proposing. Audit finding 5
   required that the external read be **independently disable-able** — a separate
   flag, so the external surface can be turned off without touching the copilot
   path.
2. **How does this not break eval determinism?** The deterministic replay gate is
   the CI hard gate (ADR-0121 record/replay). Any per-turn injection that varies
   with datastore state would make recordings non-reproducible.

## Decision

### 1. One store, `kind`-tagged (reaffirmed from S22)

L6 stays **one** `agent_experience` table with a `kind` column, not separate
per-kind stores. Confirmed entries are read back as a flat, bounded list. **Revisit
condition:** if `kind` ever needs materially different retrieval, ranking, or
retention per kind (e.g. procedures scored differently from notes), split then —
not pre-emptively.

### 2. Operational-only, NOT customer-scoped

The confirmed read (`PostgresGatewayStore.load_confirmed_experience`) is keyed by
nothing but `status='confirmed'` — unlike the L4 Customer Memory read, which is
keyed by a customer binding. L6 learnings are **shared operational knowledge**
("check `get_delivery_status` with the bare order number before escalating"), not
facts about one customer. There is deliberately no binding key and no PII path:
S22's write-side scan, S23's review prompt, and S24's human gate already enforce
operational-only on the way IN; injection just renders what survived all three,
fenced.

### 3. Confirmed-only, ever

`load_confirmed_experience` returns ONLY `status='confirmed'` rows. `proposed` and
`rejected` entries are never read and never reach any turn — the copilot draft
turn OR the external turn. This is enforced at the SQL `WHERE status = 'confirmed'`
and asserted at both seams plus at the source (live Postgres).

The read is **bounded**: newest-confirmed first (`ORDER BY decided_at DESC NULLS
LAST, created_at DESC`), capped at `_CONFIRMED_EXPERIENCE_LIMIT = 20`. Confirmed
learnings are prepended to every gated turn, so an uncapped read would grow the
prompt unbounded as the store accumulates. The cap is a fixed count, not
relevance-ranked — sufficient at launch volume; see deferred calibration below.

### 4. Two independent injection flags (both default OFF)

Injection is a **separate axis** from learning:

- `AGENT_EXPERIENCE_INJECTION` gates the **copilot** draft turn's confirmed read.
- `AGENT_EXPERIENCE_EXTERNAL_INJECTION` gates the **external** turn's confirmed
  read.

Neither is `AGENT_EXPERIENCE_LEARNING` (the propose axis) and neither is
`memory_enabled()` (the L4 axis). Both fail closed (`agent_experience_injection_
enabled` / `agent_experience_external_injection_enabled` in `tool_backend.py`,
mirroring `agent_experience_enabled`). The external flag being independent is the
audit-finding-5 requirement made concrete: turning the external read off does not
touch the copilot path, and vice versa — each seam reads only its own flag.

### 5. External is READ-ONLY

The external turn reads confirmed learnings and injects them fenced; it **never
proposes**. S23 already kept `propose_experience` off the external profile (only
the copilot review fork proposes); S25 adds no propose surface to the external
path. External L6 is a pure read.

### 6. Fenced as human-approved-but-model-originated guidance

Confirmed entries render through the shared `render_injection`
(`hermes/toee_hermes/plugin/hooks.py`), which gains an optional `experience`
parameter and a `_render_experience` block fenced as
`<confirmed_operational_learnings>`. They are labeled human-approved operational
guidance to **apply where it fits, not unconditional instructions, and never over
a customer's own request** — the same fencing discipline `_render_memory` uses for
customer-authored text, because a confirmed entry is human-vetted but was
model-originated.

### 7. The eval pin (NFR-6) — structural, not conventional

L6 injection is OFF on the eval/record/replay path:

- **Both flags default OFF and the eval path sets neither** (the same discipline
  S23 used for `AGENT_EXPERIENCE_LEARNING`).
- **The eval RECORD path structurally cannot inject L6, even with the flags on:**
  the external record path (`eval_record.scenario_user_message` →
  `_injected_context`) calls `render_injection(snapshot, memory)` with no
  `experience` argument, and the copilot record path binds a scenario-scoped store
  (`copilot_eval_record._ScenarioCaseStore`) that has no
  `load_confirmed_experience` method, so the fail-closed loader returns `None`.
- The `experience` parameter **defaults to `None`**, so every pre-S25 caller —
  the eval path included — renders a byte-identical injection block. The
  deterministic replay gate stays the CI hard gate and stays GREEN.

### 8. Turn resilience (NFR-5)

Injection degrades to SKIP on ANY failure. `load_confirmed_experience(store)`
(the shared loader in `tool_backend.py`) swallows a store that lacks the method or
raises on read to `None`, logging the exception TYPE only (never `str(exc)`, which
could echo store-supplied content) — mirroring `_load_turn_memory` /
`_load_case_memory`. A turn NEVER fails on L6.

## Consequences

- A copilot draft turn (with `AGENT_EXPERIENCE_INJECTION` on) and an external turn
  (with `AGENT_EXPERIENCE_EXTERNAL_INJECTION` on) both prepend a
  `<confirmed_operational_learnings>` block sourced from confirmed rows only. With
  the flags off (default, and the eval path), nothing changes.
- The draft turn's tool schema still technically includes `propose_experience`
  (unfiltered `booted.tool_names`), but the draft's `_turn_extra_drivers` has no
  agent-experience override, so a draft-side `propose_experience` call lands on the
  shared mock and persists nothing — inert by construction. S25 pins this with a
  live-Postgres regression test (previously untested; only the review fork ever
  persists).
- No eval scenario needed re-recording: the pin is that the eval path never reads
  L6, so all existing recordings replay unchanged.

## Deferred to post-launch (FR-27): real-traffic calibration

The 0.0.3 exploration's Candidate-8 calibration probe — measuring, on **real**
confirmed-entry traffic, whether the fixed count-20 cap and newest-first ordering
actually surface the most useful learnings, and whether injected learnings measurably
improve draft quality — is **deferred to post-launch**. At launch there is no
confirmed-entry corpus to calibrate against; the cap and ordering are a
deliberate minimal default with an upgrade path (relevance ranking / per-kind
retrieval) named in the store method's `ponytail:` comment. This is recorded here
rather than silently shipped as final so the calibration is a tracked follow-up,
not lost.

## Considered options

- **Inject on the external turn WITHOUT a separate flag, reusing the copilot flag
  (rejected).** Violates audit finding 5 — the external read must be disable-able
  independently. Two flags, one per seam.
- **Give the external turn a propose surface too (rejected).** The grilled
  decision is explicit: external is read-only over confirmed entries. Proposing
  from the external profile would cross the profile boundary S23 deliberately kept
  closed.
- **Customer-scope the confirmed read by binding key, like L4 (rejected).** L6
  learnings are operational team knowledge, not per-customer facts; scoping them
  to a binding would both mis-model them and reintroduce a PII surface the three
  upstream gates exist to keep out.
- **Pin eval determinism by scrubbing the flags in the record entrypoint
  (rejected as insufficient alone).** The structural pin (the eval path never
  passes `experience` / binds a store without the read) is stronger than an
  env-scrub, because it holds even if a flag leaks into the environment. The
  default-OFF flags are the belt; the structural no-read is the suspenders.

## Verification

- **Unit, hooks** (`hermes/tests/test_plugin_profiles.py`):
  `test_confirmed_experience_block_is_fenced_as_approved_guidance`,
  `test_render_injection_without_experience_is_unchanged` (the byte-identical
  pin invariant).
- **Seam, deterministic** (`hermes-runtime/tests/test_l6_injection.py`): confirmed
  injected only when the seam's own flag is on (copilot + external); each seam
  ignores the other's flag (two-flag independence, both directions); injection
  failure degrades to skip and the turn completes (NFR-5); flags default OFF and
  the external/copilot eval RECORD paths never surface a confirmed learning (the
  eval pin).
- **Live Postgres** (same file):
  `test_load_confirmed_experience_returns_only_confirmed_rows` (proposed/rejected
  filtered at the source), `test_draft_turn_propose_experience_persists_nothing`
  (the folded-in S23 follow-up: draft-turn-inert, with `select_tool_driver`
  patched to the fixture's schema-bound driver so a reintroduced overlay would
  flip the row-count readback RED).
- **Regression, unchanged green**: the eval record/replay/recorder suite
  (`test_eval_record.py`, `test_record_suite.py`, `test_copilot_eval_record.py`) —
  the determinism gate; `test_copilot_turn.py`, `test_copilot_learning_loop.py`,
  `test_openrouter_memory_injection.py`, `test_postgres_gateway_store.py`.
- Full-suite regression: `hermes-runtime` and `hermes`, live Postgres.

---

## Superseding note (0.0.5 S04, FR-4): a fork is not the agent

Decision 5 above says *"External is READ-ONLY"* and decision 2 says the shared
layers have *"deliberately no PII path"*. 0.0.5 S04 adds a **gateway-side capture
fork** that runs after an external customer turn and proposes L7 semantic-lexicon
entries. That is not a reversal of either sentence, and this note exists so the
next reader does not have to decide for themselves which one won.

**What decision 5 constrains is the AGENT — the thing that talks to the customer.**
That constraint is structural and unchanged: `PROFILE_TOOL_ALLOWLIST` gives
`customer_service_external` neither `toee_agent_experience` nor
`toee_semantic_lexicon`, so the external agent cannot propose to any shared layer,
in this iteration or any previous one. Removing a tool from an allowlist is the
only way that fact could change, and nothing in S04 touches it.

**A fork is different in four ways that are each checkable**, and the four together
are what make it internal infrastructure rather than an external write path:

| | external agent | capture fork (S04) |
| --- | --- | --- |
| profile | `customer_service_external` | `internal_copilot` |
| when | during the turn, with the customer waiting | after the reply, on the background worker (`l7_capture`) |
| toolset | the External allowlist | `CAPTURE_FORK_TOOL_NAMES` — one action, `propose_lexicon_entry` |
| what it can land | nothing in a shared layer | `status='proposed'` only; an admin decides |

The same distinction already existed for L6 and was simply never written down:
S23-0.0.3's review fork also boots `internal_copilot` and proposes, and it also
runs after a turn that the external agent could not have proposed from. S04 does
for the gateway path exactly what S23 did for the copilot path. **The invariant
worth stating, because it is the one both forks actually obey, is: *the model that
is talking to a customer never writes to a shared layer; a separate, restricted,
after-the-fact pass may propose into one.***

**Decision 2's "no PII path" is narrowed, honestly, rather than left to imply more
than it delivers.** For L6 it still holds as written — the review prompt forbids
person-specific data and the L6 write scan hard-rejects PII in content and in
`proposer_context` values (D2, amendment 3's clarification). For **L7** the honest
statement is different: `evidence` is *designed* to carry a verbatim customer
exchange, because that exchange is what an administrator needs in order to judge
the proposal, so the L7 leg of the scan **redacts PII in place and keeps the
entry** rather than rejecting it (D2). NFR-6 is satisfied by the PII being
*removed*, not by the exchange never being read. A fork that carries a callback
number in a `proposer_context` value has that value redacted on L7 and the whole
write rejected on L6 — and in both cases the fix is for the fork to carry ids and
refs, which its prompt tells it to do.

**A correction to decision 5's own machinery, found while building S04's tests.**
"Restricted to `toee_agent_experience` only" was, until now, an **offer list and
not a fence**. `run_agent_turn` UNIONs `governed_tool_names` into the agent's
existing `valid_tool_names` unless `tools_exclusive=True`, and the fork boots the
whole `internal_copilot` profile first — so a review fork that decided to call
`toee_customer_memory` or `toee_case_manage` would have been dispatched. The
external production turn has passed `tools_exclusive=True` since it shipped; both
forks now do too. Found by a bait: removing the restriction from the fork's call
site left every routing test green, which is what a restriction that restricts
nothing looks like from inside its own test suite. Pinned at both call sites by
`test_the_gateway_fork_hands_the_model_only_the_lexicon_propose_tool` and
`test_the_review_fork_hands_the_model_only_the_two_propose_tools`, each asserting
the exclusivity flag alongside the names.

**The eval pin generalizes unchanged.** `LEXICON_CAPTURE` is default OFF and its
own axis (neither injection flag, neither L6 flag), so the record/replay path
enqueues nothing; and the structural half is stronger than the flag, exactly as
decision 7 argued for L6 — the eval record path builds its turn from
`boot_profile_eval` + `run_agent_turn` and never goes through
`make_openrouter_run_turn`, which is the only thing in the repo that enqueues an
`l7_capture` job. Pinned by
`test_the_eval_record_path_does_not_go_through_the_capture_enqueue_seam`.

**Turn resilience generalizes too, and gets stronger.** Decision 8 made L6
*injection* degrade to skip. The capture fork cannot degrade a turn at all: it is
not on the turn's thread. `openrouter.run_turn` only enqueues, after the model
call and after the metric writes, with the enqueue itself swallowed — so a dead
queue, a dead worker or a fork that raises all leave the customer's reply exactly
as it was.

Verification for this note: `hermes-runtime/tests/test_lexicon_capture.py`.
