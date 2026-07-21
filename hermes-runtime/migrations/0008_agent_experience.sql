-- 0008_agent_experience
-- L6 Agent-experience store (0.0.3 S22, FR-23/NFR-3): "what the agent learns
-- from doing the job" -- a NEW governed table in the Toee Business Datastore
-- (ADR-0140), distinct from Customer Memory (L4, customer_memory_slot) and the
-- authored knowledge corpus (L5). Ports Hermes's learning-loop PATTERN, not
-- its store (MEMORY.md/state.db stays untouched, skip_memory=True). ONE store
-- with a `kind` field (note|procedure), not Hermes's separate notes/skills
-- stores (audit finding 4). Proposals persist with status='proposed' directly
-- -- the propose/confirm gate is status-based, not an envelope: S24 flips
-- status on accept/reject, S25 injects only confirmed entries. A proposed row
-- here is inert until then. Plain TEXT columns (no enum CHECK), consistent
-- with the rest of this schema.
CREATE TABLE agent_experience (
    id                  TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'proposed',
    content             TEXT NOT NULL,
    source              TEXT NOT NULL,
    proposer_context    JSONB,
    decider_account_id  TEXT,
    decided_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
