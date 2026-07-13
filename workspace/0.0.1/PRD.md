# PRD — Memory Architecture Activation

- **Version:** 0.0.1
- **Date:** 2026-07-10
- **Status:** Draft for review
- **Owner:** licai
- **Engineering spec:** [docs/superpowers/specs/2026-07-10-memory-architecture-activation-design.md](../../docs/superpowers/specs/2026-07-10-memory-architecture-activation-design.md)
- **Related ADRs:** 0110 (four-layer model), 0111–0114 (customer memory), 0116 (retention), 0140 (datastore = system of record), 0043 (ingress snapshot), 0031/0041 (knowledge)

---

## 1. Background & problem

The Hermes VA already persists three of its four memory layers (Identity Graph,
Conversation, Operational) into the Toee Business Datastore. The fourth layer —
**Customer Memory** (per-customer service preferences) — is fully designed
(ADR-0110–0114), has database tables, a governed tool, and handlers, but is
**not wired into the live customer-service turn**. Three concrete gaps (verified
in code):

1. **Reads are never injected** — the live turn injects the identity snapshot but
   passes the memory argument as a hard-coded `None`.
2. **Writes never persist** — the `toee_customer_memory` tool resolves to an
   ephemeral in-process mock during a live turn; nothing reaches Postgres.
3. **Provisional→verified merge is unimplemented** — the audit table has no
   writer.

Separately, the **knowledge layer** the agent uses for company/brand/product
information is hollow: brand voice is a code-level persona, operational policy is
six eval-gated slots, but "public site knowledge" search is a 2-entry hard-coded
mock. The weekly RAG/crawl mechanisms in ADR-0001/0002/0031 were never built.

**Consequence today:** a customer who states a durable preference ("text me,
don't call, after 5pm") is forgotten the moment the turn ends, and the agent has
no retrievable body of company/product knowledge beyond the persona and six
policy slots.

## 2. Goals

- **G1 — Per-customer durable memory.** A customer's stated service preferences
  survive across sessions, bound to their identity, and are visible to the agent
  on the next turn.
- **G2 — Governed, auditable writes.** Preferences are written only from explicit
  customer statements or employee confirmation — never model inference — and
  every write is attributable and retention-governed.
- **G3 — Continuity through verification.** Preferences a caller states before
  they are verified follow them onto their verified customer record.
- **G4 — A real knowledge layer** (later iteration) for company/brand/product
  education/FAQ content, authored by staff and retrievable by the agent, without
  weakening the existing policy-slot governance or exposing live facts/PII.

### Non-goals

- No new memory system and no external memory provider (mem0/honcho/etc.).
- No change to how live facts (price/stock/order/AR) are served — those stay
  real-time Shopify/QBO reads (ADR-0031).
- No cross-channel provisional merge (ADR-0112 v1 non-goal).
- No fix to the dormant `pre_llm_call` hook registration (the manual injection
  seam is the proven path).
- No retention **job** implementation in this iteration (columns exist; the
  sweep is a later slice).

## 3. Users

| Persona | Relationship to memory |
| --- | --- |
| **Verified Customer** | Preferences bound to `shopifyCustomerId`; read on every turn |
| **Unmatched / Ambiguous caller** | Preferences bound provisionally to the channel identity; merged on verification (unmatched only) |
| **Customer Service Rep / Supervisor / Admin (Copilot)** | Read the same preferences on a case; may correct/clear after confirmation |
| **Content author (staff)** | Authors company/brand/product knowledge via git (M2) |

## 4. Requirements

### 4.1 Customer Memory (this iteration — "M1")

- **FR-1 Read injection.** At the start of each external customer-service turn
  **and** each Copilot case-scoped turn, the current customer's preference slots
  are injected into the model context.
  - *Accept:* verified caller sees slots bound to `shopifyCustomerId`; provisional
    caller sees slots for their channel identity; no slots → no block injected.
- **FR-2 Governed persistence.** `toee_customer_memory` writes/reads hit Postgres
  `customer_memory_slot` on the live external turn (via a per-tool composite
  driver), with no change to gate/allowlist governance.
  - *Accept:* a preference written during a live turn is retrievable on the next
    turn and appears in the datastore; audit records `driver.kind = "datastore"`.
- **FR-3 Write discipline.** Only the four v1 slots are writable; open-ended keys
  are rejected; the external agent writes only on explicit customer statements;
  values are capped (200 chars); `source` is one of a fixed enum.
  - *Accept:* an open-ended key is rejected; an over-length value is rejected;
    the model cannot autonomously write from inference (persona-enforced + tested).
- **FR-4 Provisional→verified merge.** On verified ingress, provisional slots for
  the caller's channel identity merge onto the verified record: verified values
  win on conflict, provisional values are recorded in merge audit, provisional
  copies are removed, and an audit row is written.
  - *Accept:* preference stated while unmatched appears under the verified id
    after verification; a conflicting verified slot is preserved; ambiguous
    matches never merge.
- **FR-5 Binding safety (fail-closed).** Binding identity for a customer turn
  comes from the ingress-provided context, not model-supplied parameters; a turn
  with no resolvable channel identity is `policy_blocked`, never bound to a shared
  key.
  - *Accept:* the model cannot read or write another caller's memory by supplying
    a phone number as a tool argument.

### 4.2 Knowledge layer (next iteration — "M2", roadmap here)

- **FR-6** `toee_knowledge_search.search_public_site` is backed by gbrain
  (read-scoped) behind the unchanged governed tool; `search_operational_policy`
  keeps reading policy slots.
- **FR-7** Company/brand/product-education/FAQ content is authored as markdown
  under `brain/` in the main repo; a PR merge is the publish gate; gbrain syncs
  on merge.
- **FR-8** `brain/` never contains live facts, policy-slot copy, or customer PII;
  gbrain's write/admin tools are never exposed to the customer-facing agent;
  retrieval failure degrades to a governed "not found", never a turn failure.

### 4.3 Non-functional

- **NFR-1 Latency.** Memory read adds one indexed SELECT per turn (negligible).
  M2 knowledge retrieval must return < 800 ms or the feature is not shipped
  in-turn.
- **NFR-2 Privacy.** Customer PII lives only in the business datastore, never in
  the knowledge store; the knowledge store runs in a separate database.
- **NFR-3 Governance & audit.** Every memory write is attributable; retention
  columns are present for the ADR-0004/0116 sweep; the knowledge PR flow is the
  human gate (ADR-0041 exempts it from the eval gate).
- **NFR-4 Evaluability.** The ADR-0117/0118 memory assertion package runs against
  the real path (previously mock-only).

## 5. Scope for 0.0.1

**In:** Section 4.1 (FR-1…FR-5) — Customer Memory activation across the external
and Copilot surfaces, with tests + the memory eval package rerun.

**Out (→ 0.0.2):** Section 4.2 (gbrain knowledge layer), gated on three spikes
(latency, server API shape, deployment isolation) before commitment.

> Recommendation: keep 0.0.1 = M1 (self-contained, no external dependency,
> ~5–7 days). M2 opens 0.0.2 after the spikes. Adjustable if you want both in
> 0.0.1.

## 6. Success metrics

- A stated preference is correctly injected on the following turn (functional +
  eval).
- 100% of live-turn memory writes land in Postgres with a datastore audit row
  (0% land in the ephemeral mock).
- Provisional-then-verified flow carries preferences forward with verified-wins
  conflict handling (eval scenario green).
- No memory read/write can cross customer boundaries via model-supplied
  parameters (security test green).

## 7. Milestones

| Milestone | Content | Est. |
| --- | --- | --- |
| **0.0.1 / M1** | Customer Memory activation (read, write, merge, hardening; external + Copilot) | 5–7 days |
| **0.0.2 / M2** | gbrain knowledge layer (spikes → driver → `brain/` authoring → terminology + ADR) | 1–2 weeks post-spike |

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| Composite-driver seam surprises on the Copilot path | Both surfaces one milestone; external can still ship first within it |
| Memory injection token growth | 4 slots × 200-char cap; no-slots → no block |
| gbrain too slow for SMS turns (M2) | Spike gate; fallback stays mock/`found=False` |
| gbrain project churn (714 open issues) | Read-only driver; content is portable git markdown |

## 9. Open questions / dependencies

- Confirm 0.0.1 = M1-only vs M1+M2 (recommendation: M1-only).
- Local Postgres must be running to exercise the datastore path
  (`docker compose up -d postgres` + migrate with `HERMES_APPLY_DEV_SEED`).
- M2 depends on the three spikes passing before any commitment.

## 10. References

- Engineering spec (implementation detail): see header link.
- gbrain: https://github.com/garrytan/gbrain
- ADRs: 0110, 0111, 0112, 0113, 0114, 0116, 0140, 0043, 0031, 0041.
