# S01 — `semantic_lexicon` store + governed propose tool + write scan

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T1 L7 Semantic Lexicon
- **Size:** M
- **Depends on:** none
- **Delivers:** FR-1, FR-3 (write side)
- **Surface:** new migration (~0020, re-verify); governed tool (mock+PG twins); catalog

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
