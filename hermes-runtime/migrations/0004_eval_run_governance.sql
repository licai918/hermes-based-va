-- 0004_eval_run_governance
-- Workbench Launch Eval Review governance + the authoring->publish bridge
-- (ADR-0146; #44). Increment 7 cuts the Supervisor Admin /admin/eval routes
-- (ADR-0088) over to Postgres to match the in-memory EvalStore (behavioral
-- source of truth) and wires ADR-0145's deferred divergences #1/#2.
--
-- The EvalStore overlays TWO independent, OVERLAPPING governance flags on each
-- run -- signed_off and promoted, either or both can be true -- which the single
-- legacy `status` column cannot represent; they become their own BOOLEAN columns.
-- The full ADR-0074 report (suite/model/prompt/knowledge/timestamp/scenarios/
-- summary{...,failed_medium}/signoff_required) stays in the `report` JSONB and is
-- the projection's source of truth; these columns are only the governance overlay.
--
-- slot_key bridges a policy_publish run to the ADR-0003 policy slot it gates (the
-- snake eval-gate key, shared with eval/policy_slot_map.yaml). On promotion the
-- handler maps it to the kebab authoring id and publishes that workbench_policy_slot
-- (ADR-0145), pushing the prior published text onto its history so rollback has
-- data -- closing ADR-0145 divergence #2.
--
-- Append-only: the live local schema already applied 0001-0003, so a new file
-- (not an edit to 0001); the runner skips already-applied versions.

ALTER TABLE eval_run
    ADD COLUMN signed_off BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN promoted   BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN slot_key   TEXT;
