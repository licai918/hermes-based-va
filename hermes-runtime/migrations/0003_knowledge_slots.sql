-- 0003_knowledge_slots
-- Workbench KnowledgeOps authoring slots (ADR-0145; #43). The Supervisor Admin
-- /admin/knowledge master-detail (ADR-0087) authors the six Required Operational
-- Policy Slots (ADR-0003) with a draft -> pending_eval -> published lifecycle,
-- separate draft/published text, owner/review metadata, and a published-version
-- history for rollback -- mirroring the in-memory KnowledgeStore (the behavioral
-- source of truth) field-for-field.
--
-- This is a SEPARATE table from knowledge_version (the eval publish-gate model,
-- ADR-0040): different slot-id namespace (kebab UI ids vs ADR-0003 snake keys),
-- separate draft/published columns, owner/review/gap fields, and a history stack.
-- The two are intentionally decoupled in this increment (ADR-0145 divergence #2);
-- connecting authoring to the eval publish-gate is the #44 redesign. A new
-- migration (not an edit to 0001) because the live local schema already applied
-- 0001/0002; the runner skips already-applied versions.

CREATE TABLE workbench_policy_slot (
    slot_id        TEXT PRIMARY KEY,               -- kebab UI id (ADR-0087), e.g. business-hours
    title          TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'empty',  -- empty | draft | pending_eval | published | gap
    draft_text     TEXT,
    published_text TEXT,
    owner          TEXT,
    review_date    TEXT,                           -- free-form (store parity; not a DATE, not validated)
    has_gap_prompt BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order     SMALLINT NOT NULL,              -- fixed ADR-0003 list order the UI renders
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Prior published texts, most recent last; rollback pops the latest (ADR-0145).
CREATE TABLE workbench_policy_slot_history (
    id             TEXT PRIMARY KEY,
    slot_id        TEXT NOT NULL REFERENCES workbench_policy_slot(slot_id),
    published_text TEXT NOT NULL,
    archived_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_policy_slot_history_slot ON workbench_policy_slot_history (slot_id, archived_at);

-- Seed the six Required Operational Policy Slots as empty onboarding placeholders
-- (ADR-0003): always present, empty until KnowledgeOps fills them. The in-memory
-- DEMO seed (pre-published business-hours + history, gap exception-scripts, etc.)
-- is NOT carried into Postgres -- like accounts, a real DB starts empty (ADR-0145).
INSERT INTO workbench_policy_slot (slot_id, title, sort_order) VALUES
    ('business-hours',     'Business hours and service boundaries',      1),
    ('payment-methods',    'Payment methods and Payment Link rules',     2),
    ('order-delivery',     'Order and delivery inquiry guidance',        3),
    ('accounting-inquiry', 'Accounting inquiry guidance',                4),
    ('returns-exchanges',  'Returns, exchanges, and stockout policy',    5),
    ('exception-scripts',  'Standard exception scripts',                 6);
