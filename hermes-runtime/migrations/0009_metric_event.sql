-- 0009_metric_event
-- Aggregate-metrics admin panel (0.0.3 S26, FR-28). A single tiny event table
-- backs the two GAP counters the panel needs that no existing table tracks:
-- memory injection (openrouter.py/copilot_turn.py) and knowledge found/miss
-- (knowledge/driver.py). One row per turn/search attempt, boolean signal only
-- -- never a customer value or a knowledge query (FR-4/RK-2). The other six
-- FR-28 metrics are cheap aggregations over EXISTING tables (customer_memory_slot,
-- customer_memory_merge_audit, workbench_audit_log, agent_experience) and need
-- no new table.
CREATE TABLE metric_event (
    id         TEXT PRIMARY KEY,
    metric     TEXT NOT NULL,
    flag       BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_metric_event_metric ON metric_event (metric);
