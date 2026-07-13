# S05 — Graceful degradation without a datastore

- **Milestone:** 0.0.1 / M1
- **Size:** S
- **Depends on:** S04
- **Delivers:** FR-7, RK-6
- **Surface:** hermes-runtime boot wiring

## Goal

Customer Memory is never a hard dependency of answering. When the turn process has
no Postgres (`TOOL_BACKEND` unset / mock deployment), memory reads inject nothing
and writes are silent no-ops — the turn still completes and replies.

## Problem

The composite driver (S04) and read load (S06) assume Postgres. A mock-mode
gateway (no `DATABASE_URL`) must not throw or block the reply.

## Files (likely)

- `hermes-runtime/hermes_runtime/openrouter.py` / boot caller — only inject the
  memory `PostgresDriver` and the memory read when a datastore is configured;
  otherwise skip both.
- Optionally a tiny `memory_enabled()` helper keyed on the same signal as
  `resolve_tool_backend()`.

## Approach

- No datastore configured → no `extra_drivers` entry (tool falls to mock, writes
  are ephemeral/no-op) **and** the read injection is skipped (no block).
- No exceptions surface to the customer path.

## Acceptance

- E2E (part of S13): an external turn with no DB configured completes and replies;
  no error; no empty "Customer Memory:" artifact.
- Unit: `memory_enabled()` false when backend is mock/unset.

## Out of scope

- The read/write paths themselves (S04/S06/S07).
