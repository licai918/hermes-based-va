# S01 — `REPLY_SENDER=simulated` composition gate

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T2 Conversation Simulator
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-10, NFR-4
- **Surface:** reply composition root (sender selection); `message_turn` mirror

## Goal

FR-10 (confirmed seam): "a `REPLY_SENDER=simulated` composition gate — skips the
real Textline POST, still mirrors the reply into `message_turn`; the simulator
reads the reply from there. Production default remains the real sender;
misconfiguration fails closed."

## Approach

- One-point seam in the composition root (§7 seam 2): the reply sender is
  selected by `REPLY_SENDER`; default (unset/`textline`) = the real Textline sender.
- `simulated` sender makes **no** Textline POST and mirrors the reply into
  `message_turn`, so the S02 read-back path works.
- **NFR-4:** simulated traffic never reaches real Textline. An unrecognized
  `REPLY_SENDER` value **fails closed** (no send, error surfaced) — it never
  falls through to the real sender.
- The real sender path is untouched beyond the selection point.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit seam (hermes/tests, 0.0.2 driver-seam pattern):
  `simulated` → no Textline client call + mirror invoked; unset → real sender;
  unrecognized value → fail closed, no send. Datastore integration
  (hermes-runtime/tests, live Postgres): the mirrored reply row is read back
  from `message_turn` directly.
- **② E2E (browser):** with `REPLY_SENDER=simulated`, post a webhook (the
  existing PS simulation script shape) and open the conversation's case in the
  existing copilot workbench — the mirrored reply is visible in the thread;
  screenshot. (The dedicated simulator page arrives in S03.)
- **③ Product (PAC):** feeds PAC-2 (and every simulator PAC) at S33; the owner
  exercises this gate through the S03 UI.

## Out of scope

- Ingress BFF + reply read-back route — **S02**.
- Simulator page/thread UI — **S03**.
