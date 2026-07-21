# S02 — Turn worker cutover: fast-ack enqueues to Postgres

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T2 Durable job queue
- **Size:** M
- **Depends on:** S01
- **Delivers:** FR-9 (turn half), FR-10, NFR-1, NFR-2
- **Surface:** gateway composition + new turn-worker process (docker-compose service)

## Goal

FR-10: the gateway's fast-ack path enqueues the turn job to the Postgres
queue instead of the in-process thread; a **turn worker** process consumes it.
US3: a message that arrives while the service crashes runs when it returns.

## Approach

- `gateway_composition.py` wires the S01 queue in place of
  `LocalDispatchingJobQueue`; delete `LocalDispatchingJobQueue` and its tests
  after cutover (no dual path left behind).
- Turn worker: a new entrypoint claiming `type=turn` jobs only, executing the
  existing bound-turn job body unchanged. docker-compose service added.
- Webhook ack budget: enqueue is one INSERT (NFR-1 — measure ack p95
  before/after in the simulator, no regression).
- Claim latency: poll interval tuned so queue claim adds < 500 ms p95 over
  the thread handoff (NFR-2); if polling can't meet it, LISTEN/NOTIFY is the
  named upgrade (append to S01's ADR).
- Kill-worker drill (NFR-3 first half): kill the worker mid-turn; lease
  reclaim re-runs the job to completion. (Duplicate-send protection lands in
  S03 — until then the drill asserts completion, not single-send.)

## Acceptance — three-layer gate

- **① Technical:** integration test — enqueue → worker claims → reply
  mirrored to `message_turn`; kill/reclaim test; ack + claim latency numbers
  recorded in the PR.
- **② E2E (browser):** simulator SMS round-trip through the real queue;
  screenshot of the reply in the simulator thread.
- **③ Product (PAC):** PAC-2 (with S03): kill the turn worker before reply,
  restart, reply arrives exactly once.

## Out of scope

- Outbound idempotency — **S03**. Background job types — **S04**.
