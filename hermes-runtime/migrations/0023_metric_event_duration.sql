-- 0023_metric_event_duration
-- Per-layer memory read latency (0.0.5 S18, FR-26, D5.1).
--
-- D5.1: `metric_event` (migration 0009) is (id, metric, flag, created_at) -- no
-- numeric column, so p50/p95 over it is arithmetically IMPOSSIBLE. Encoding a
-- duration into the metric NAME, or degrading it to a boolean "was slow",
-- satisfies the letter of S18's Approach and is named a defect. Two legal shapes
-- were offered: a latency-sample table, or a nullable numeric column here.
--
-- This takes the COLUMN, and the deciding reason is L5. `knowledge/driver.py`'s
-- `_emit_found` already writes exactly one `metric_event` row per retrieval
-- attempt, so the retrieval duration rides a row that was being written anyway:
-- zero extra rows and -- the part that matters -- zero extra connections in
-- front of a customer reply. A separate table would have doubled L5's write
-- volume and put a second per-search connect on the turn path, which is the
-- NFR-5 hazard this slice exists to MEASURE, not to create. The column also
-- inherits the existing writer, its bounded connect timeout
-- (`CONNECT_TIMEOUT_TURN_SECONDS`), its `metric` index and its retention story,
-- rather than starting four new ones.
--
-- NULL `duration_ms` means "this row is a boolean counter, not a latency
-- sample" -- every pre-0023 row and every untimed emit. The aggregation
-- (`hermes_runtime.latency.latency_metrics`) filters on `duration_ms IS NOT
-- NULL`, so counters and samples never contaminate each other even when they
-- share a metric name, which `knowledge_search` deliberately does.
ALTER TABLE metric_event ADD COLUMN duration_ms DOUBLE PRECISION;

-- A latency sample carries no boolean signal, and writing an arbitrary `true`
-- to satisfy NOT NULL would be a fabricated flag sitting in the same column the
-- found/miss and injection rates are computed from.
ALTER TABLE metric_event ALTER COLUMN flag DROP NOT NULL;

-- ... and the CHECK is what stops that weakening from becoming "a counter emit
-- may silently write a row with no signal at all". Every row says something.
ALTER TABLE metric_event
    ADD CONSTRAINT metric_event_carries_a_signal
    CHECK (flag IS NOT NULL OR duration_ms IS NOT NULL);
