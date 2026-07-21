-- Idempotency for inbound events that intentionally persist no AgentTurnContext.
--
-- The opt-out branch (ADR-0108/0016) short-circuits before persist, so
-- agent_turn_context — the table is_duplicate reads — never learned about it.
-- SimpleTexting does not sign webhooks (ADR-0153), so a captured request replays
-- verbatim, and every replay re-sent the fixed confirmation: one real SMS per
-- replay, billed to us. This table is the durable claim that makes it
-- at-most-once across instances and restarts.

CREATE TABLE inbound_event_claim (
    event_id   TEXT PRIMARY KEY,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
