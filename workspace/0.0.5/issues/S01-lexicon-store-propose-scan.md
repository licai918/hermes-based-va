# S01 — `semantic_lexicon` store + governed propose tool + write scan

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T1 L7 Semantic Lexicon
- **Size:** M
- **Depends on:** none
- **Delivers:** FR-1, FR-3 (write side)
- **Surface:** new migration (~0020, re-verify); governed tool (mock+PG twins); catalog

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

These override the text below wherever they conflict. Read the linked decisions in full.

- **D1** — this slice's migration prefix is **0020** (0.0.4 now tops out at 0019). Re-verify by
  listing the directory before writing it.
- **D2** — **split the scanner.** `scan_agent_experience_content` today hard-rejects PII as well
  as injection, and its `_PHONE_RE` **matches `205 55 16`** — the flagship seeded surface form of
  this very iteration. This slice lands `scan_injection` + `scan_pii` as two named resolvers in
  ONE shared module used by both twins: `surface_form`/`canonical_form` get injection only;
  `evidence`/`proposer_context` get injection (reject) plus PII (**redact in place, do not
  reject** — the evidence is what the admin needs to decide). L6's existing behaviour and tests
  must not change: compose the two resolvers to preserve `scan_agent_experience_content`.
- **D3** — the provenance enum is **three** values: `admin_manual | conversation_confirmed |
  feedback_derived`. Provenance is framework-derived from the execution context, never from a
  caller param. (Without the third value, S25's aggregator proposals have no legal provenance.)
- **D0** — bare `Sxx` below means a **0.0.3** slice: "S22-scanned" = the scanner from
  **S22-0.0.3**; "S14 result-extraction" = the envelope from **S14-0.0.3**; the draft-turn-inert
  pattern is **S25-0.0.3**. None of them are 0.0.5 slices.
- **D19** — `scan_injection` must also hard-reject **fence-delimiter tokens** (a memory value
  containing `</untrusted_customer_memory>` closes the prompt fence early and puts the rest of
  the value outside it — a structural escape today's injection patterns do not catch). Because
  every layer calls this one shared resolver, fixing it here covers L4, L6 and L7 at once.
- **D17** — this is the only catalog-touching slice in flight; the nine-file sync set is yours
  alone right now.
- A `LAYER_OF_ACTION` map now exists (0.0.5 S12) covering **every** catalog action. Your new
  actions must be declared there in this same diff or the completeness test fails CI.

## Goal

FR-1/FR-3: the L7 store — `semantic_lexicon` with `UNIQUE(domain, surface_form)`, status
lifecycle proposed|confirmed|rejected|retired, provenance admin_manual|conversation_confirmed,
evidence/proposer_context/decider/decided_at/hit_count — plus the governed write tool
`propose_lexicon_entry` (writes `proposed` ONLY), S22-scanned, S14 result-extraction.
Exploration C1 §Store/§Governance.

## Approach

- Mirror the L4/L6 governance skeleton exactly (handlers/agent_experience.py is the template):
  registry fragment, `insert_audit` on propose, framework-derived source; mock+PG twins share
  ONE scanner and ONE resolver module (NFR-7).
- `propose_lexicon_entry(domain, entry_kind, surface_form, canonical_form, evidence?,
  proposer_context?)` — INTERNAL-allowlisted ONLY; reached through fork-restricted toolsets
  (S04); param schema declares+requires the four core fields.
- Extend `scan_agent_experience_content` usage to lexicon writes (injection + PII patterns →
  hard-reject).
- **Re-list the post-0.0.4-S11 catalog sync set** in the report (tool_catalog / plugin.yaml /
  schemas / mock twin / registry / profiles — whatever now exists) and mirror every point;
  drift + tool-count tests updated.
- **Draft-turn-inert pinning test** (S25 pattern): a draft-turn `propose_lexicon_entry` call
  persists NOTHING.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit (mock) — propose writes a `proposed` row with framework-derived
  provenance; forged status/provenance params are ignored; adversarial content hard-rejected
  with zero rows. Live Postgres — schema round-trip incl. UNIQUE conflict on same
  (domain,surface); audit row present; draft-turn-inert test green; drift tests green.
- **② E2E (browser):** a seeded proposed entry visible via the S02 console (interim: direct
  dispatch probe if S02 not yet landed); screenshot.
- **③ Product (PAC):** feeds PAC-1/PAC-2 at S02-S06.

## Out of scope

- Decide/CRUD actions + console — **S02**. Normalizer code + seeding — **S03**.
- Capture forks — **S04**. Any application/injection — **S05/S06**.
