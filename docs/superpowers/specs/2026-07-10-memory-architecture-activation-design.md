# Memory architecture activation: Customer Memory wiring (M1) + gbrain knowledge layer (M2)

> **Superseded in part (2026-07-20).** **M1 (Customer Memory wiring) SHIPPED** — 0.0.1 (PR #54)
> and 0.0.2 (PR #55); the "L4 Dormant / three broken wires" state described below is now
> historical. **M2 (gbrain knowledge layer) is SUPERSEDED** — the 0.0.3 spike evaluated gbrain
> and rejected it, choosing an in-house **hybrid lexical + dense-embedding** retriever over a
> separate index. Current direction →
> [`docs/architecture/memory-layers.md`](../../architecture/memory-layers.md) (L5) and
> [`workspace/0.0.3/knowledge-spike/`](../../../workspace/0.0.3/knowledge-spike/).
> Retained as the historical record of how M1 was designed.

Date: 2026-07-10
Status: **superseded in part** (M1 shipped; M2 superseded 2026-07-20) — was: approved-direction
Decision owner: licai

## Context (verified against code, 2026-07-10)

The four-layer memory model (ADR-0110) stores in the Toee Business Datastore
(ADR-0140); Hermes native memory is conversation-only. Verified wiring state of
the live external customer-service turn:

| Layer | State | Evidence |
| --- | --- | --- |
| L1 Identity Graph | Active | ingress phone match + snapshot persistence |
| L2 Conversation | Active | `PostgresGatewayStore` (`TOOL_BACKEND=datastore`) |
| L3 Operational | Active | cases / audit / eval records |
| L4 Customer Memory | **Dormant** | three broken wires, below |
| Upstream Hermes memory (mem0/honcho/MEMORY.md) | Unwired by design | ADR-0140 |

The three broken wires (all confirmed by code reading):

1. **Read injection**: `openrouter.py` `run_turn` manually prepends
   `render_injection(identity, None)` — the second argument (memory) is
   hard-coded `None`. (The `pre_llm_call` hook registered via `register_turn`
   never fires in the live turn: it registers on a local `PluginManager` while
   `AIAgent` consults the global singleton. The manual prepend is the proven
   path; we extend it rather than fix the hook.)
2. **Write persistence**: `toee_customer_memory` is allowlisted (EXTERNAL +
   INTERNAL) but the live driver selector only knows mock/composio, and the tool
   is not in `COMPOSIO_LAYER1_TOOLS` — every live call lands in an ephemeral
   in-process mock dict. The Postgres handlers (`datastore/handlers/memory.py`)
   are reachable only from the Copilot/Admin dispatch servers.
3. **Provisional merge**: `customer_memory_merge_audit` has no writer; the
   ADR-0112 merge is unimplemented.

Knowledge layer: product facts are live Shopify reads (ADR-0031 — correct,
unchanged); brand voice is `persona.py`; operational policy is the six
eval-gated slots (`workbench_policy_slot`). `toee_knowledge_search
.search_public_site` is a 2-entry hard-coded mock; the RAG/crawl mechanisms in
ADR-0001/0002/0031 were never implemented.

## Decision (Option A)

Finish the native-seam wiring for Customer Memory (no new memory system, no
external memory provider), and back the public-knowledge search with gbrain
(github.com/garrytan/gbrain) as a knowledge layer only. Rejected alternatives:
Hermes memory providers (mem0/honcho — external SaaS, no governed slots,
conflicts with ADR-0111 write rules) and gbrain-as-customer-memory (free-text
pages cannot provide deterministic reads, governed writes, merge, or
retention).

Hard boundary table (what lives where):

| Information | Home | Update path |
| --- | --- | --- |
| Price / stock / order / AR | Live Shopify/QBO tool reads | vendor-side edits |
| Six operational policy slots | `workbench_policy_slot` | draft → eval gate → publish (ADR-0040) |
| Brand voice / behavior contract | `persona.py` system prompt | code change + release |
| Company / brand story / product education / FAQ | **gbrain (M2)** | git PR in `brain/` → auto-sync |
| Per-customer preferences (4 slots) | `customer_memory_slot` | governed `toee_customer_memory` writes only |

`brain/` content must never contain: live facts (prices, stock, orders, AR),
operational policy slot copy, or customer PII.

## M1 — Customer Memory activation (est. 5–7 days)

Scope: external customer-service turn **and** Copilot case-scoped turns
(decision: ship both surfaces together).

### M1a Read injection

- `PostgresGatewayStore.load_customer_memory(binding_key) -> list[{slot, value}]`
  (single indexed SELECT; `_get_preferences` logic reused).
- External turn: in `openrouter.py` `run_turn`, replace
  `render_injection(identity, None)` with the loaded memory block. Binding key:
  verified → `shopify_customer_id`; otherwise → provisional key (canonical form
  below). No slots → no block injected (ADR-0113).
- Copilot turn: the copilot agent-turn composition injects the same block,
  binding key derived from the selected case's `customer_thread` identity.
- Ambiguous phone match: inject the provisional block (same phone, no
  cross-customer leak), but never merge (ADR-0112).

### M1b Write persistence (composite driver overlay)

- Extend the per-tool driver selector (`_build_driver_selector`, already
  per-tool for Composio Layer 1) with an optional
  `extra_drivers: dict[tool_name, ToolDriver]` parameter threaded through
  `register_turn → _register`.
- hermes-runtime (the embedding layer) injects
  `{"toee_customer_memory": PostgresDriver(dsn=...)}` at `boot_profile` time.
  The dependency-free `toee_hermes` plugin never imports psycopg — it receives
  an object satisfying the `ToolDriver` protocol. Audit rows carry
  `driver.kind = "datastore"` automatically.
- Governance unchanged: catalog check, Tool Gate, and profile allowlist run
  before the driver (by construction of `execute_tool`).

### M1c Merge + binding-key hardening

Merge (per ADR-0112, verbatim rules):

- Trigger: **every verified ingress** (not only link creation) — one SELECT
  probes for provisional slots keyed by the caller's channel identity; merge
  runs only when rows exist (idempotent: merged provisional rows are deleted).
  This covers manually seeded `identity_link` rows.
- Behavior: upsert provisional slots onto the verified key; on conflict the
  verified value wins and the provisional value is recorded in
  `customer_memory_merge_audit.details`; delete provisional copies; write the
  audit row (`provisional_key`, `verified_key`, `details`, `mergedAt`).
- Ambiguous matches never merge.

Hardening (grilled decisions):

1. **Fail-closed binding**: the bare `"provisional"` fallback key in
   `_resolve_binding` (all anonymous callers sharing one key — cross-customer
   leak) is removed. No channel identity in context → `policy_blocked`.
2. **Context-only binding for customers**: binding identity comes from the
   ingress-injected `ToolExecutionContext.identity` (model-unforgeable). The
   `channel_identity_id` tool param remains only for Copilot employee-confirmed
   corrections.
3. **Canonical provisional key**: `provisional:{channel}:{E.164}` (e.g.
   `provisional:sms:+17786803250`), using the existing `normalize_e164`. No data
   migration needed — the table has never been written by the live path.
4. **Value length cap**: 200 chars per slot value, enforced in the handler
   (ADR-0111 "defined maximum length").
5. **Source enum**: `source ∈ {customer_explicit, employee_confirmed,
   merged_provisional}`, validated in the handler (replaces the silent
   `"unspecified"` default).

### M1 verification

- Unit: injection rendering, composite-driver routing, merge three-state
  (no-conflict / conflict-verified-wins / ambiguous-no-merge), fail-closed
  binding, length cap, source validation — on the existing throwaway-schema
  Postgres test harness.
- Eval: rerun the ADR-0117/0118 memory assertions package against the real
  path (was mock-only).
- E2E: simulated webhook, two inbound rounds (state preference → verify
  injection); provisional-then-verified merge chain.

## M2 — gbrain knowledge layer (est. 1–2 weeks, gated on spikes)

### Spikes first (half a day; hard gates)

1. **Latency**: gbrain retrieval (non-synthesis mode) must return < 800 ms for
   an SMS-turn tool call; the LLM-synthesis mode is out of scope for in-turn
   retrieval regardless.
2. **Server API shape**: confirm a server-side-callable retrieval endpoint
   (plain HTTP preferred; otherwise a minimal MCP-HTTP client, read scope
   only).
3. **Deployment**: gbrain's Postgres+pgvector runs in the same instance as the
   business datastore but in a **separate database** (knowledge store carries
   no PII; physical separation from customer data).

### Integration

- Tool surface unchanged: the external agent sees only the allowlisted
  `toee_knowledge_search`. `search_public_site` is backed by a
  `GbrainKnowledgeDriver` injected via the same `extra_drivers` seam as M1b;
  `search_operational_policy` continues to read policy slots (untouched).
- Degradation: gbrain timeout/unavailable → governed `found=False` (the
  existing knowledge-gap path); the turn never fails on knowledge retrieval.
- Security: gbrain's 30+ MCP tools (incl. write/admin scopes) are never exposed
  to the customer-facing agent; only the driver holds a read-scoped credential.

### Authoring flow (git is the gate)

- Content lives in the main repo under `brain/` (decision: subdirectory, not a
  separate repo). Staff author markdown (company profile, brand story, product
  education, FAQ, tire knowledge); PR review is the human gate; on merge,
  gbrain syncs (its own dedup/citation/contradiction loop) and content becomes
  retrievable.
- ADR-0041 confirms Public Site Knowledge is exempt from the eval gate, so the
  PR gate introduces no conflicting governance.

### Terminology + ADR deliverables (ship with M2, not before)

- Redefine **Public Site Knowledge** in CONTEXT.md: customer-facing knowledge
  authored in `brain/` and indexed/retrieved by gbrain.
- Mark **Shopify Knowledge Sync** and **Tavily Gap Crawl** glossary entries as
  superseded by gbrain ingestion.
- New ADR: gbrain replaces the ADR-0001 weekly-RAG and ADR-0031 sync/crawl
  implementation mechanisms (supersession notes on both); live-facts rule of
  ADR-0031 is reaffirmed unchanged.

## Out of scope

- Fixing the local-vs-global PluginManager hook registration (manual prepend is
  the proven seam; hook fix is a separate refactor if ever needed).
- Cross-channel provisional merge (ADR-0112 v1 non-goal).
- mem0/honcho/upstream memory providers (rejected alternative).
- Automated Shopify-content sync into `brain/` (possible later; superseded
  ADRs note the option).
- Retention-job implementation for memory slots (ADR-0004/0116 enforcement is
  a separate slice; `created_at`/`last_interaction_at` columns already exist).

## Risks

| Risk | Mitigation |
| --- | --- |
| gbrain retrieval too slow for SMS turns | Spike gate; fallback stays mock/`found=False`; M1 unaffected |
| gbrain project churn (714 open issues) | Read-only driver behind our governed tool; content is our git markdown, portable to any retriever |
| Memory injection token growth | 4 slots × 200 chars cap; no-slots → no block |
| Copilot-surface coupling delays M1 | Both surfaces reviewed as one milestone per decision; if copilot seam surprises, external surface can still ship first within the milestone |

## Glossary changes already applied (ADR-0140 lag fixes)

- `Hermes Native Memory` redefined as upstream conversation-only memory.
- New `Toee Business Datastore` entry (four layers + retention).
- `Customer Memory` storage home corrected to the datastore.
