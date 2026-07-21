# S09 — Governed driver via `extra_drivers` + `knowledge_enabled()` + driver deadline → found=false

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T1 Knowledge layer L5
- **Size:** M
- **Depends on:** S08
- **Delivers:** FR-4, NFR-5
- **Surface:** `search_public_site` driver behind the `extra_drivers` seam; knowledge-store logging

## Goal

FR-4: "`search_public_site` backed by the retriever via `extra_drivers`, behind
a `knowledge_enabled()` gate; **driver-side deadline** → governed `found=false`
(no tool-call timeout exists in-repo — this wiring is mandatory); retrieval
queries sanitized in knowledge-store logs; `search_operational_policy`
untouched."

## Approach

- Driver registered via the existing `extra_drivers` seam (§7 seam 4 — the
  pattern L4 already proved).
- `knowledge_enabled()` gate, named and documented so it cannot be confused
  with `memory_enabled()` (=L4) or Hermes's `memory.memory_enabled` (=agent
  notes) — the collision the architecture map warns about.
- **Deadline semantics are driver-side:** on expiry the driver returns a
  governed `found=false`; it degrades, never raises, and **never blocks the
  turn** (NFR-5: the turn never fails on retrieval). Deadline value is
  configurable; default is implementer's choice within the FR-7b budget.
- Retrieval queries sanitized in knowledge-store logs.
- `search_operational_policy` untouched.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit (hermes/tests driver seam): gate off → tool
  unavailable; forced-slow store stub → governed `found=false`, no exception,
  turn continues; log-sanitization assertion. Integration (live Postgres):
  driver returns grounded results against the real knowledge DB.
- **② E2E (browser):** drive the S08 admin probe through the governed driver;
  with the deadline set to a tiny dev value, the probe visibly returns the
  governed not-found degrade; screenshot.
- **③ Product (PAC):** feeds PAC-1's honest "don't have that" leg (owner-run at
  S10/S33).

## Out of scope

- Wiring the tool onto the external/copilot turn profiles — **S10**.
- The hybrid p95 gate around this deadline (FR-7b) — **S12**.
