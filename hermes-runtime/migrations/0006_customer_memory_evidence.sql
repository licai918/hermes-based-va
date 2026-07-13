-- 0006_customer_memory_evidence
-- Write-discipline hardening (PRD FR-3, S03, #52-ish). upsert_preference now
-- accepts an optional evidence param (a verbatim customer phrase) persisted
-- alongside the slot write for audit -- so a preference stored under
-- customer_explicit can be traced back to what the customer actually said.
-- Additive and nullable: existing rows read NULL, no backfill needed. A new
-- migration (not an edit to 0001) because the runner skips already-applied
-- versions.

ALTER TABLE customer_memory_slot ADD COLUMN evidence TEXT;
