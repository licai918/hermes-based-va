-- 0007_customer_memory_actor
-- Actor attribution (PRD 0.0.2 FR-4/R2, NFR-3 closure). Records which employee
-- made a memory write: a UI correction (dispatch route, context.user_id set from
-- the request's asserted actor_account_id, ADR-0141) persists the rep's account
-- id; an AI draft-turn write or a provisional->verified merge persists NULL.
-- Additive and nullable, no backfill (RK-6/NFR-1): existing rows read NULL, no
-- read dependency until this slice's handler threading lands. A new migration
-- (not an edit to 0001) because the runner skips already-applied versions.

ALTER TABLE customer_memory_slot ADD COLUMN actor_account_id TEXT;
