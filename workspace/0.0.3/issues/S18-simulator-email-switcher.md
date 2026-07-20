# S18 — Simulator channel switcher (SMS / email)

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T4 Email + merge
- **Size:** S
- **Depends on:** S17, S03
- **Delivers:** FR-11
- **Surface:** simulator page control; routing to S17's email ingress

## Goal

FR-11: "channel switcher: SMS / email; the email option drives T4's ingress."
US4: the owner tests the email pipeline the same way as SMS, from the same
simulator page.

## Approach

- Switcher on the S03 simulator page: SMS mode posts through S02 (unchanged);
  email mode composes {from, subject, body} to S17's simulated email ingress.
- Reply read-back is identical — both channels mirror into the message store.
- S04's presets/reset apply per channel; email identities are simulated
  addresses only (NFR-4 posture).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest: switcher state routes the composer to the correct
  ingress with the correct payload shape per channel; SMS behavior unchanged.
- **② E2E (browser):** switch to email, send a simulated email, the reply
  appears in the thread; switch back to SMS and send again; screenshots of
  both channels.
- **③ Product (PAC):** PAC-4's E2E path (with S05's link control and S19's
  merge).

## Out of scope

- The email pipeline itself — **S17**.
- Provisional-slot merge across channels — **S19**.
