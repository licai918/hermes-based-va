# S18 — Live agent eval harness

- **Milestone:** 0.0.4 — land all seven
- **Track:** T6 Eval completion
- **Size:** M
- **Depends on:** S02 (turn path on the durable queue), S25 (CI topology —
  for the CI leg; local development of the harness needs only S02 + S10)
- **Delivers:** FR-26
- **Surface:** `hermes/eval_runner/harness.py` + runner CLI; no UI

## Goal

FR-26: `_StubAgentHarness` (returns empty `AgentTurnResult`) is replaced by
a harness that drives a **real turn** through the dispatch/gateway path —
simulated ingress + `REPLY_SENDER=simulated` — so the eval gate proves the
pipeline, not just replay plumbing.

## Approach

- Harness posts the scenario's inbound events through the simulator ingress
  seam (0.0.3 S01/S02 machinery), reads the reply from `message_turn`, and
  maps to `AgentTurnResult` for the existing assertion layer.
- Two model modes: `scripted` (dispatch server `scripted_completions`,
  deterministic — CI's mode) and `live` (real OpenRouter model — S20's
  advisory runs and local use).
- Recorder integration: the same harness records transcripts (feeds S19).

## Acceptance — three-layer gate

- **① Technical:** scripted-mode harness run over `text_first_launch`
  passes deterministically twice in a row **in CI on the S25 topology**;
  live-mode smoke on 2 scenarios locally.
- **② E2E (browser):** n/a (CLI) — CI artifact as evidence.
- **③ Product (PAC):** feeds PAC-8.

## Out of scope

- CI wiring of live mode — **S20**. Email transcripts — **S19**.
