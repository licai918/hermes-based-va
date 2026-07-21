# S06 — Knowledge DB productionized: `toee_knowledge` migrations, `KNOWLEDGE_DATABASE_URL` lazy seam

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T1 Knowledge layer L5
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-1
- **Surface:** knowledge store (schema + migrations + DSN seam); no turn-path change

## Goal

FR-1: "productionize the knowledge store: separate `toee_knowledge` DB (never
the business DB), `knowledge_chunk` schema + FTS index, own migration path,
`KNOWLEDGE_DATABASE_URL` env seam (lazy DSN, mirroring the datastore driver
pattern)." Replaces the 2-entry mock's storage story.

## Approach

- Own migration path for `toee_knowledge`; `knowledge_chunk` table + FTS index
  matching the shape the spike's 167-chunk corpus was staged against.
- `KNOWLEDGE_DATABASE_URL` lazy-DSN seam per the datastore driver pattern — no
  connection attempt until first use.
- Strict separation: the knowledge DSN never defaults to the business DB; the
  knowledge DB carries no customer data (NFR-3).
- Retrieval logic, ingestion, and admin UI all come later (S07/S08/S11) — this
  slice is schema + seam only.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** migration applies cleanly on a fresh Postgres
  (hermes-runtime/tests, live Postgres); schema + FTS index asserted by
  introspection; lazy-seam unit: with no DSN set, importing/constructing makes
  no connection attempt; missing DSN at first use surfaces a clear error.
- **② E2E (browser):** the existing `/admin/knowledge` entry loads healthy with
  the productionized store configured; screenshot. (The corpus-status panel is
  S11's.)
- **③ Product (PAC):** feeds PAC-1 at S33 (infrastructure slice).

## Out of scope

- Ingestion job — **S07**; hybrid retriever — **S08**.
- Admin corpus status panel + re-ingest — **S11**.
