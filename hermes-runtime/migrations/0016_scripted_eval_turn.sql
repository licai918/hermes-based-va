-- 0016_scripted_eval_turn
-- Scripted-eval turn seam (0.0.4 S18, FR-26).
--
-- The live agent eval harness drives a REAL turn through the dispatch/gateway
-- pipeline while keeping the model deterministic (no OpenRouter). The seam is a
-- one-row-per-scenario handshake on the shared datastore, the only channel that
-- crosses from the harness process to the RUNNING turn-worker process:
--
--   1. before POSTing the inbound webhook, the harness INSERTs a row here keyed
--      by the event id it will post, carrying the scenario's scripted model
--      completions;
--   2. the turn-worker -- ONLY when EVAL_SCRIPTED_MODE is armed (off by default,
--      refused in a prod config; see hermes_runtime/scripted_eval.py) -- reads the
--      row, runs the scenario's scripted turn through the real governed dispatch,
--      and writes the captured {final_response, messages} transcript back to
--      `captured`;
--   3. the harness polls `captured`, maps it to an AgentTurnResult, and runs the
--      existing eval assertion package on it.
--
-- PROD-INERT: nothing reads this table unless EVAL_SCRIPTED_MODE is armed, and the
-- arming guard refuses a prod DEPLOY_ENVIRONMENT. The table being empty (and the
-- eval fixtures absent from the prod image) is the belt to that suspenders.
CREATE TABLE IF NOT EXISTS scripted_eval_turn (
    event_id     TEXT PRIMARY KEY,
    suite        TEXT NOT NULL,
    scenario_id  TEXT NOT NULL,
    completions  JSONB NOT NULL,
    captured     JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    captured_at  TIMESTAMPTZ
);
