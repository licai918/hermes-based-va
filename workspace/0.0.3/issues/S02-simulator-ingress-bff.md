# S02 — Simulator ingress BFF: flat-JSON webhook + legacy HMAC → gateway; reply read-back

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T2 Conversation Simulator
- **Size:** M
- **Depends on:** S01
- **Delivers:** FR-9
- **Surface:** workbench BFF (ingress + read-back routes); real gateway webhook `POST /webhooks/textline`

## Goal

FR-9: the simulator posts the **flat-JSON Textline webhook** (id /
conversation_id / from / body / received_at / type) with the **legacy HMAC
signature** (`TEXTLINE_WEBHOOK_SECRET`) to the real gateway — identity match,
memory, knowledge, live model all run the production path. This slice is the
BFF half: ingress composition + reply read-back from `message_turn`.

## Approach

- BFF ingress route accepts a simulated-customer message + identity params,
  composes the flat-JSON webhook, signs with the legacy HMAC, and posts to the
  real `POST /webhooks/textline` (§7 seam 1 — no bypass chat; the production
  pipeline is the thing under test; the PS simulation script already proves the shape).
- Read-back route fetches the agent reply from `message_turn` (S01's mirror).
- **NFR-4:** simulated identities only — never a real customer's phone number;
  simulated traffic must not be able to trigger a real Textline send (the S01
  gate fails closed; whether the BFF additionally checks `REPLY_SENDER` is
  implementer's choice).
- Vitest BFF route tests per 0.0.2 prior art.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest: ingress route → correct flat-JSON shape + valid
  HMAC; read-back route returns the mirrored reply. Integration (live
  Postgres): webhook-in → reply-in-store round trip through the real gateway.
- **② E2E (browser):** drive the round trip from the browser and observe the
  inbound message and mirrored reply in the existing copilot case view;
  screenshot. (The simulator page that consumes these routes is S03.)
- **③ Product (PAC):** feeds PAC-2 at S33; the owner drives it via S03.

## Out of scope

- Simulator page, thread view, composer — **S03**.
- Identity presets / reset — **S04**.
