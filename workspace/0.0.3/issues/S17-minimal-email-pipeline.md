# S17 — Minimal email pipeline: channel generalization, simulated email ingress, Email Sender Match, email turn + memory injection, reply mirror

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T4 Email + merge
- **Size:** L
- **Depends on:** S01
- **Delivers:** FR-18
- **Surface:** inbound channel type; email ingress route; identity match; email turn profile; reply mirror

## Goal

FR-18: "minimal email pipeline, simulator-driven only (no real email provider):
generalize the inbound channel type beyond `textline_sms`; an email ingress
route accepting simulated inbound email ({from, subject, body}); **Email Sender
Match** identity (ADR-0052/0054 semantics); an email turn running the same
governed profile with memory read-injection; reply mirrored for the simulator;
email-channel structural disclosures per existing eval rules."

## Approach

- Generalize the channel literal beyond `textline_sms`; reuse the SMS pipeline
  shape end-to-end (§7 seam 3).
- Simulated email ingress route accepting {from, subject, body}.
- **Hard fence (RK-4): simulated ingress only — no real email provider.** Any
  real-provider integration is a new iteration (§9); scope creep here is the
  named risk.
- Email Sender Match identity per ADR-0052/0054 semantics.
- Email turn runs the same governed profile with memory read-injection; the
  reply is mirrored through the S01 gate so the simulator can read it back.
- Email-channel structural disclosures per the existing eval rules.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** integration (live Postgres): simulated email in → Email
  Sender Match → email turn → mirrored reply in the store (webhook-in →
  reply-in-store seam, email flavor); channel generalization regresses no SMS
  suite; disclosure eval rules green.
- **② E2E (browser):** post a simulated inbound email and see the reply from
  the front end (interim: the copilot case view; the simulator channel
  switcher is S18); screenshot.
- **③ Product (PAC):** PAC-4's email leg — "an email conversation reads the
  same memory" (full PAC after S19).

## Out of scope

- Simulator channel switcher UI — **S18**.
- Cross-channel provisional merge — **S19**.
- Real email provider — **out of scope this iteration (§9)**.
