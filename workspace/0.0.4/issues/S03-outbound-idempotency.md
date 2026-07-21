# S03 — Outbound send record + idempotency check

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T2 Durable job queue
- **Size:** M
- **Depends on:** S02
- **Delivers:** FR-12, NFR-3
- **Surface:** reply-sender path + outbound-send migration; no UI

## Goal

FR-12 (grilled decision 8): every turn job's outbound send carries a
deterministic idempotency key checked against an outbound-send record before
the Textline POST — so any retry or replay is safe; a customer never receives
the same message twice.

## Approach

- Migration: outbound-send record keyed by a deterministic idempotency key
  derived from job id + turn/reply identity (never model output).
- Sender wrap: write-ahead intent → check existing key → skip-and-record if
  already sent → POST → mark sent. **Every outbound/mirror action goes
  through the same wrap (gap-review fix T2): the Textline POST, the email
  reply mirror (0.0.3 S17 pipeline — a replayed email turn must not write a
  duplicate reply row into `message_turn`), and the `REPLY_SENDER=simulated`
  gate (0.0.3 S01)** — so the drill is provable in the simulator on both
  channels.
- Crash-window coverage: crash between POST and commit → on re-run the intent
  row exists → treated as sent (at-most-once toward the customer; the skip is
  recorded for audit).

## Acceptance — three-layer gate

- **① Technical:** unit + DB tests — same key never POSTs twice; skip is
  recorded; crash-window simulation (kill between intent and mark) re-runs
  without re-send; **email-channel replay test — no duplicate mirror row**.
- **② E2E (browser):** simulator: force a retry of a sent turn; thread shows
  exactly one reply; screenshot.
- **③ Product (PAC):** PAC-2 — owner kills the worker mid-turn, restarts,
  and sees exactly one reply; the skip visible in the outbound record.

## Out of scope

- Replay UI (uses this guarantee) — **S05**.
