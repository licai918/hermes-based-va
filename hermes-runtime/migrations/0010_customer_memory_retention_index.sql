-- 0.0.3 S28 follow-up (final-review Important): the retention sweep's DELETE
-- filters customer_memory_slot by (binding_kind, last_interaction_at) --
--   WHERE (binding_kind='verified'    AND last_interaction_at < :verified_threshold)
--      OR (binding_kind='provisional' AND last_interaction_at < :provisional_threshold)
-- Without an index on those columns it is a full-table scan holding a lock for
-- the whole sweep transaction, which only bites at production PII volume
-- (ADR-0142 is local-first, so no such volume yet). A composite index on
-- (binding_kind, last_interaction_at) serves each OR branch: equality on
-- binding_kind then a range scan on last_interaction_at. Additive, IF NOT
-- EXISTS so it is a safe no-op on any DB that already has it.
CREATE INDEX IF NOT EXISTS idx_customer_memory_slot_retention
    ON customer_memory_slot (binding_kind, last_interaction_at);
