-- 0028_entry_effectiveness
-- Per-entry effectiveness: judge verdicts x the injection ledger (0.0.5 S26,
-- FR-31; prefix 0028 per DECISIONS D1, re-verified free against the directory at
-- land time -- occupied then: 0020..0024, 0026, 0030, 0031).
--
-- The system already knows two halves of the answer and can join neither:
-- `injection_ledger` (0030) records WHICH entries reached WHICH turn, and the
-- scheduled judge job records how well a SAMPLE of turns behaved -- but only as
-- ONE aggregate row per run, with no turn attribution. These two tables are the
-- missing middle.
--
--   judged_turn         one row per (turn, leg): the verdict, keyed by the SAME
--                       turn_ref the ledger uses, which is what makes the join
--                       possible at all.
--   entry_effectiveness the materialized per-entry aggregate the console and the
--                       health-ranked glossary read. Derived entirely from the
--                       two tables above -- see below for why it is materialized.
--
-- **EXTERNAL PATH ONLY, structurally (D4.3).** The judge samples `message_turn`
-- rows joined to `agent_turn_context`, so only the external customer turn can
-- ever produce a `judged_turn` row. The copilot draft path's `turn_ref` is a
-- synthetic `new_id("copilot_turn")` with no durable identity, so its ledger rows
-- are real but unjoinable and are never attributed here. That scope is carried
-- as DATA on every score the API returns (`entry_health.scope`), not only in
-- prose, so no renderer can present a partial number as a total one.
--
-- **Why entry_effectiveness is materialized rather than a view.** Its consumer
-- is the health-ranked glossary selection, which runs on the REPLY PATH once per
-- turn. `injection_ledger` gains rows on every turn and retains 180 days, so
-- aggregating it live per turn is exactly the read NFR-5 forbids. One row per
-- entry, refreshed on the ledger's own maintenance tick, turns that into a PK
-- join over a table with as many rows as there are entries.
--
-- **The refresh is a FULL RECOMPUTE (DELETE + INSERT in one transaction), not an
-- accumulation.** The judge job's 7-day sampling window overlaps run to run, so
-- the same turn is re-sampled and re-judged routinely; accumulating would count
-- one turn's evidence once per run and quietly weight the rate towards whatever
-- happens to be re-sampled. A recompute makes one turn worth exactly one verdict
-- per leg however often it is judged, needs no watermark, and lets a row whose
-- ledger rows aged out disappear instead of lingering as a ghost.
--
-- **No memory VALUES here (NFR-6), same as the ledger.** Ids, leg names and
-- counts only.

-- One judged turn, one leg, one verdict. `passed IS NULL` is the judge's own
-- "undetermined" -- counted, never in a denominator (the honored_rate rule,
-- applied per entry).
CREATE TABLE judged_turn (
    turn_ref  TEXT NOT NULL,
    leg       TEXT NOT NULL,
    passed    BOOLEAN,
    judged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (turn_ref, leg)
);

-- ponytail: no prune job. Rows are bounded by the judge's per-run SAMPLE_CAP and
-- are three narrow columns; a row whose ledger rows have aged out contributes
-- nothing to the recompute, it just sits there. If the table ever matters, fold a
-- windowed DELETE into `injection_ledger`'s existing prune tick -- that job
-- already owns this data's lifecycle and already recomputes the aggregate below.

CREATE TABLE entry_effectiveness (
    layer       TEXT NOT NULL,
    entry_ref   TEXT NOT NULL,
    -- Ledger-derived usage: how many turns carried this entry inside the ledger's
    -- retention window. The OTHER half of usage is `semantic_lexicon.hit_count`,
    -- a materialized column a different rollup owns (D6) -- read there, never
    -- recomputed here. Both are counted as usage, and they are not the same
    -- thing: hit_count is lifetime deterministic-seam applications and is
    -- STRUCTURALLY ZERO for a `default_rule`, which the seam never applies.
    injections  BIGINT NOT NULL DEFAULT 0,
    -- {leg: {"passed", "determinate", "undetermined"}} -- the shipped
    -- `honored_rate_aggregate.leg_results` shape, reused so enabling a judge leg
    -- needs no migration here.
    leg_results JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (layer, entry_ref)
);
